from datetime import datetime
import io
import json
import re
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from flask import Flask, Response, render_template, request
import requests

app = Flask(__name__)


def fetch_usccb_by_date(date_str):
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        formatted_date = date_obj.strftime("%m%d%y")
    except ValueError:
        date_obj = datetime.now()
        formatted_date = date_obj.strftime("%m%d%y")

    target_url = f"https://bible.usccb.org/bible/readings/{formatted_date}.cfm"
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }
    )

    raw_html = None

    # 1. Direct fetch attempt
    try:
        res = session.get(target_url, timeout=6)
        if res.status_code == 200 and "USCCB" in res.text:
            raw_html = res.text
    except Exception:
        pass

    # 2. Proxy Fallback 1: AllOrigins JSON API
    if not raw_html:
        try:
            proxy_url = f"https://api.allorigins.win/get?url={requests.utils.quote(target_url)}"
            res = session.get(proxy_url, timeout=8)
            if res.status_code == 200:
                data = res.json()
                if data.get("contents") and "USCCB" in data["contents"]:
                    raw_html = data["contents"]
        except Exception:
            pass

    # 3. Proxy Fallback 2: CodeTabs Raw Proxy
    if not raw_html:
        try:
            proxy_url = f"https://api.codetabs.com/v1/proxy?quest={requests.utils.quote(target_url)}"
            res = session.get(proxy_url, timeout=8)
            if res.status_code == 200 and "USCCB" in res.text:
                raw_html = res.text
        except Exception:
            pass

    if raw_html:
        soup = BeautifulSoup(raw_html, "html.parser")
        return parse_usccb_html(soup, date_str)

    # 4. Fallback for TODAY'S date via RSS feed
    today_str = datetime.now().strftime("%Y-%m-%d")
    if date_str == today_str:
        return fetch_today_rss(date_str)

    raise Exception(
        f"Could not retrieve readings for {date_str}. The USCCB page for this date may not be available yet."
    )


def parse_usccb_html(soup, date_str):
    # Strip headers, footers, scripts, navigation, UI buttons
    for tag in soup.find_all(
        ["footer", "nav", "button", "script", "style", "a"],
        class_=re.compile(
            r"footer|nav|expand|collapse|accordion|toggle", re.I
        ),
    ):
        tag.decompose()

    output_lines = []
    seen_texts = set()

    # Title / Date Header
    title = (
        soup.find("h1")
        or soup.find("h2", class_=re.compile(r"heading", re.I))
        or soup.find("title")
    )
    if title:
        clean_title = title.get_text(strip=True).replace(" - ", " ")
        output_lines.append(f"--- {clean_title} ---")
    else:
        output_lines.append(f"--- USCCB Readings ({date_str}) ---")

    # Target reading blocks (.b-verse)
    sections = soup.find_all(
        ["div", "section", "article"], class_=re.compile(r"b-verse", re.I)
    )
    if not sections:
        sections = soup.find_all(
            ["div", "section"], class_=re.compile(r"inner-overview", re.I)
        )
    if not sections:
        sections = [soup.find("main") or soup.body]

    ignored_phrases = [
        "copyright",
        "subscribe",
        "get daily readings",
        "listen podcast",
        "en español",
        "view full reading",
        "united states conference of catholic bishops",
        "all rights reserved",
        "privacy policy",
        "expand all",
        "collapse all",
        "made possible by funding",
        "funding from",
        "catholic communication campaign",
        "fixcorserrors",
        "corsproxy",
    ]

    for sec in sections:
        full_sec_text = sec.get_text().lower()
        is_psalm = "psalm" in full_sec_text

        headings = sec.find_all(
            ["h2", "h3", "h4"], class_=re.compile(r"title|heading|name", re.I)
        )

        for h in headings:
            htext = h.get_text(strip=True)
            if htext and not any(
                p in htext.lower()
                for p in ["daily reading", "get daily", "subscribe", "podcast"]
            ):
                if htext not in seen_texts:
                    seen_texts.add(htext)
                    output_lines.append(f"\n[{htext}]")

        if is_psalm:
            # Strictly extract ONLY bold elements (<b> and <strong>) within Psalm blocks
            bold_tags = sec.find_all(["strong", "b"])
            for b in bold_tags:
                btext = re.sub(r"\s+", " ", b.get_text(strip=True)).strip()
                # Skip headings or short numbers/markers that might be bolded
                if (
                    len(btext) > 3
                    and not any(bad in btext.lower() for bad in ignored_phrases)
                    and "responsorial psalm" not in btext.lower()
                    and btext not in seen_texts
                ):
                    seen_texts.add(btext)
                    output_lines.append(btext)
        else:
            # Standard parsing for Reading I, Reading II, Gospel, etc.
            paras = sec.find_all("p")
            for p in paras:
                text = p.get_text(separator=" ", strip=True)
                if (
                    len(text) > 15
                    and not any(bad in text.lower() for bad in ignored_phrases)
                    and text not in seen_texts
                ):
                    seen_texts.add(text)
                    output_lines.append(text)

    if len(output_lines) <= 1:
        raise Exception("Parsed empty reading text from HTML.")

    return "\n\n".join(output_lines)


def fetch_today_rss(date_str):
    rss_url = "https://bible.usccb.org/readings/daily-readings.rss"
    res = requests.get(rss_url, timeout=10)
    res.raise_for_status()

    root = ET.fromstring(res.content)
    channel = root.find("channel")
    output_lines = [f"--- USCCB Daily Readings ({date_str}) ---"]
    seen_texts = set()

    items = channel.findall("item") if channel is not None else []
    for item in items:
        title_text = item.findtext("title") or ""
        if title_text and title_text not in seen_texts:
            seen_texts.add(title_text)
            output_lines.append(f"\n[{title_text.strip()}]")

        is_psalm = "psalm" in title_text.lower()
        description_text = item.findtext("description") or ""
        soup = BeautifulSoup(description_text, "html.parser")

        if is_psalm:
            bold_tags = soup.find_all(["strong", "b"])
            for b in bold_tags:
                bold_text = re.sub(r"\s+", " ", b.get_text(strip=True)).strip()
                if (
                    len(bold_text) > 3
                    and "copyright" not in bold_text.lower()
                    and bold_text not in seen_texts
                ):
                    seen_texts.add(bold_text)
                    output_lines.append(bold_text)
        else:
            paragraphs = soup.find_all(["p", "div"])
            for p in paragraphs:
                text = p.get_text(separator=" ", strip=True)
                if (
                    len(text) > 15
                    and "copyright" not in text.lower()
                    and text not in seen_texts
                ):
                    seen_texts.add(text)
                    output_lines.append(text)

    return "\n\n".join(output_lines)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/download", methods=["POST"])
def download():
    selected_date = request.form.get("date_input")
    if not selected_date:
        selected_date = datetime.now().strftime("%Y-%m-%d")

    try:
        content = fetch_usccb_by_date(selected_date)
        filename = f"USCCB_Readings_{selected_date}.txt"

        return Response(
            content,
            mimetype="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment;filename={filename}"
            },
        )
    except Exception as e:
        return f"Error fetching readings: {str(e)}", 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
