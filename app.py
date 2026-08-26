import io
import re
from bs4 import BeautifulSoup
from flask import Flask, Response, render_template, request
import requests

app = Flask(__name__)


def scrape_usccb_readings():
    url = "https://bible.usccb.org/daily-bible-reading"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    res = requests.get(url, headers=headers, timeout=10)
    res.raise_for_status()

    soup = BeautifulSoup(res.text, "html.parser")
    output_lines = []

    # Get page title/date header
    page_title = soup.find("h1")
    if page_title:
        output_lines.append(f"--- {page_title.get_text(strip=True)} ---")

    # Find reading blocks (USCCB groups readings in sections or inner-overview containers)
    sections = soup.find_all(
        ["section", "article", "div"], class_=re.compile(r"b-verse|content", re.I)
    )

    if not sections:
        sections = [soup.body]

    for sec in sections:
        # Extract headings (e.g., Reading 1, Responsorial Psalm, Gospel)
        headings = sec.find_all(
            ["h2", "h3", "h4"], class_=re.compile(r"title|heading", re.I)
        )
        for h in headings:
            htext = h.get_text(strip=True)
            if htext:
                output_lines.append(f"\n[{htext}]")

        # Extract text blocks
        paras = sec.find_all("p")
        for p in paras:
            text = p.get_text(separator=" ", strip=True)
            # Filter out UI boilerplate text
            if len(text) > 10 and not any(
                bad in text.lower()
                for bad in [
                    "copyright",
                    "subscribe",
                    "get daily readings",
                    "listen podcasts",
                ]
            ):
                output_lines.append(text)

    # ProPresenter TXT Format: Double line breaks (\n\n) separate slides
    return "\n\n".join(output_lines)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/download")
def download():
    try:
        content = scrape_usccb_readings()
        return Response(
            content,
            mimetype="text/plain",
            headers={
                "Content-Disposition": (
                    "attachment;filename=USCCB_Daily_Readings.txt"
                )
            },
        )
    except Exception as e:
        return f"Error fetching USCCB readings: {str(e)}", 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
