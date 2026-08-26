from datetime import datetime
import io
import re
from bs4 import BeautifulSoup
from flask import Flask, Response, render_template, request
import requests

app = Flask(__name__)


def fetch_usccb_readings(date_str):
    # Convert YYYY-MM-DD to MMDDYY format required by USCCB
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        formatted_date = date_obj.strftime("%m%d%y")
    except ValueError:
        date_obj = datetime.now()
        formatted_date = date_obj.strftime("%m%d%y")

    url = f"https://bible.usccb.org/bible/readings/{formatted_date}.cfm"

    # Spoof a standard web browser header to prevent 403 Forbidden errors
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    res = requests.get(url, headers=headers, timeout=10)
    res.raise_for_status()

    soup = BeautifulSoup(res.text, "html.parser")
    output_lines = []

    # Title / Date Header
    title = soup.find("h1") or soup.find("title")
    if title:
        clean_title = title.get_text(strip=True).replace(" - ", " ")
        output_lines.append(f"--- {clean_title} ---")

    # Locate reading content containers
    sections = soup.find_all(
        ["section", "article", "div"],
        class_=re.compile(r"b-verse|content|inner-overview", re.I),
    )

    if not sections:
        sections = [soup.body]

    for sec in sections:
        # Extract headings (Reading 1, Responsorial Psalm, Gospel, etc.)
        headings = sec.find_all(
            ["h2", "h3", "h4"], class_=re.compile(r"title|heading", re.I)
        )
        for h in headings:
            htext = h.get_text(strip=True)
            if htext and "daily reading" not in htext.lower():
                output_lines.append(f"\n[{htext}]")

        # Extract reading text paragraphs
        paras = sec.find_all("p")
        for p in paras:
            text = p.get_text(separator=" ", strip=True)
            if len(text) > 15 and not any(
                bad in text.lower()
                for bad in [
                    "copyright",
                    "subscribe",
                    "get daily readings",
                    "listen podcasts",
                ]
            ):
                output_lines.append(text)

    # Return string separated by double line breaks (creates new slides in ProPresenter)
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
            headers={"Content-Disposition": f"attachment;filename={filename}"},
        )
    except Exception as e:
        return f"Error fetching readings: {str(e)}", 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
