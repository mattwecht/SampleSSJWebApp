import io
import re
from datetime import datetime
from bs4 import BeautifulSoup
from flask import Flask, Response, render_template, request
import requests

app = Flask(__name__)


def fetch_usccb_readings(date_str):
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        formatted_date = date_obj.strftime("%m%d%y")
    except ValueError:
        date_obj = datetime.now()
        formatted_date = date_obj.strftime("%m%d%y")

    url = f"https://bible.usccb.org/bible/readings/{formatted_date}.cfm"

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://bible.usccb.org/",
        }
    )

    res = session.get(url, timeout=10)

    # Fallback to standard daily URL if date-specific URL fails
    if res.status_code != 200:
        res = session.get(
            "https://bible.usccb.org/daily-bible-reading", timeout=10
        )
        res.raise_for_status()

    soup = BeautifulSoup(res.text, "html.parser")

    # 1. REMOVE FOOTER, NAVIGATION, & UI CONTROLS FROM DOM
    for unwanted_tag in soup.find_all(
        ["footer", "nav", "button", "script", "style"],
        class_=re.compile(
            r"footer|nav|site-footer|b-footer|expand|collapse|accordion|toggle",
            re.I,
        ),
    ):
        unwanted_tag.decompose()

    # Decompose specific elements matching UI controls (e.g. "Expand All Topics")
    for btn in soup.find_all(["a", "button", "div", "span"]):
        b_text = btn.get_text(strip=True).lower()
        if "expand all" in b_text or "collapse all" in b_text:
            btn.decompose()

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

    # Content Containers (targeting core passage structures)
    sections = soup.find_all(
        ["section", "article", "div"],
        class_=re.compile(r"b-verse|content|inner-overview", re.I),
    )

    if not sections:
        main_body = soup.find("main") or soup.body
        sections = [main_body]

    # Expanded list of UI phrases, footer links, and funding notices to ignore
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
        "bishops' emergency disaster fund",
    ]

    for sec in sections:
        headings = sec.find_all(
            ["h2", "h3", "h4"], class_=re.compile(r"title|heading", re.I)
        )
        for h in headings:
            htext = h.get_text(strip=True)
            if htext and not any(
                phrase in htext.lower()
                for phrase in [
                    "daily reading",
                    "get daily",
                    "subscribe",
                    "podcast",
                    "expand",
                ]
            ):
                output_lines.append(f"\n[{htext}]")

        paras = sec.find_all("p")
        for p in paras:
            text = p.get_text(separator=" ", strip=True)
            text_lower = text.lower()

            # Filter out UI controls, funding text, and boilerplate links
            if len(text) > 15 and not any(
                bad in text_lower for bad in ignored_phrases
            ):
                output_lines.append(text)

    if not output_lines or len(output_lines) <= 1:
        raise Exception(
            "Failed to parse clean reading text from USCCB page."
        )

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
        content = fetch_usccb_readings(selected_date)
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
