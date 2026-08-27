from datetime import datetime
import io
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
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://bible.usccb.org/",
    }

    raw_html = None

    # 1. Try direct fetch
    try:
        res = session.get(target_url, headers=headers, timeout=8)
        if res.status_code == 200:
            raw_html = res.text
    except Exception:
        pass

    # 2. Try proxy fallback if direct fetch fails/gets 403
    if not raw_html:
        try:
            proxy_url = (
                f"https://corsproxy.io/?{requests.utils.quote(target_url)}"
            )
            res = session.get(proxy_url, timeout=10)
            if res.status_code == 200:
                raw_html = res.text
        except Exception:
            pass

    if raw_html:
        soup = BeautifulSoup(raw_html, "html.parser")
        return parse_usccb_html(soup, date_str)

    # 3. Fallback to RSS for Today's Date
    today_str = datetime.now().strftime("%Y-%m-%d")
    if date_str == today_str:
        return fetch_today_rss(date_str)

    raise Exception(
        f"Could not retrieve readings for {date_str}. USCCB may not have published this date yet."
    )


def parse_usccb_html(soup, date_str):
    # Remove footers, scripts, navigation, UI buttons
    for tag in soup.find_all(
        ["footer", "nav", "button", "script", "style", "a"],
        class_=re.compile(
            r"footer|nav|expand|collapse|accordion|toggle", re.I
        ),
    ):
        tag.decompose()

    output_lines = []

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

    # Target reading blocks
    sections = soup.find_all(
        ["section", "article", "div"],
        class_=re.compile(r"b-verse|content|inner-overview", re.I),
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
    ]

    for sec in sections:
        headings = sec.find_all(
            ["h2", "h3", "h4"], class_=re.compile(r"title|heading", re.I)
        )

        section_heading_text = ""
        for h in headings:
            htext = h.get_text(strip=True)
            if htext and not any(
                p in htext.lower()
                for p in ["daily reading", "get daily", "subscribe", "podcast"]
            ):
                section_heading_text += " " + htext.lower()
                output_lines.append(f"\n[{htext}]")

        # Check if current section is the Responsorial Psalm
        is_psalm = "psalm" in section_heading_text

        paras = sec.find_all("p")
        for p in paras:
            if is_psalm:
                # Extract ONLY bold text elements (<strong> or <b>) for Responsorial Psalm
                bold_tags = p.find_all(["strong", "b"])
                if bold_tags:
                    bold_text_combined = " ".join(
                        tag.get_text(strip=True) for tag in bold_tags
                    )
                    clean_bold = re.sub(
                        r"\s+", " ", bold_text_combined
                    ).strip()

                    if len(clean_bold) > 3 and not any(
                        bad in clean_bold.lower() for bad in ignored_phrases
                    ):
                        output_lines.append(clean_bold)
            else:
                # Normal processing for Reading I, Gospel, etc.
                text = p.get_text(separator=" ", strip=True)
                if len(text) > 15 and not any(
                    bad in text.lower() for bad in ignored_phrases
                ):
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

    items = channel.findall("item") if channel is not None else []
    for item in items:
        title_text = item.findtext("title") or ""
        if title_text:
            output_lines.append(f"\n[{title_text.strip()}]")

        is_psalm = "psalm" in title_text.lower()
        description_text = item.findtext("description") or ""
        soup = BeautifulSoup(description_text, "html.parser")

        paragraphs = soup.find_all(["p", "div"])

        for p in paragraphs:
            if is_psalm:
                bold_tags = p.find_all(["strong", "b"])
                if bold_tags:
                    bold_text = " ".join(
                        tag.get_text(strip=True) for tag in bold_tags
                    ).strip()
                    if len(bold_text) > 3 and "copyright" not in bold_text.lower():
                        output_lines.append(bold_text)
            else:
                text = p.get_text(separator=" ", strip=True)
                if len(text) > 15 and "copyright" not in text.lower():
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
