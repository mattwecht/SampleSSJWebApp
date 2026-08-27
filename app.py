import io
import re
from datetime import datetime
from bs4 import BeautifulSoup
from flask import Flask, Response, render_template, request
import requests

app = Flask(__name__)


def fetch_usccb_readings(date_str):
    # USCCB RSS Feed URL
    rss_url = "https://bible.usccb.org/readings/daily-readings.rss"
    api_url = f"https://api.rss2json.com/v1/api.json?rss_url={rss_url}"

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

    res = session.get(api_url, timeout=10)
    res.raise_for_status()

    data = res.json()
    if data.get("status") != "ok" or not data.get("items"):
        raise Exception("Could not retrieve readings from USCCB RSS feed.")

    output_lines = []
    feed_title = data.get("feed", {}).get("title", "USCCB Daily Readings")
    output_lines.append(f"--- {feed_title} ({date_str}) ---")

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

    for item in data.get("items", []):
        # Section Heading (e.g. Reading I, Gospel, Responsorial Psalm)
        title_text = item.get("title", "").strip()
        if title_text:
            output_lines.append(f"\n[{title_text}]")

        # Extract text content from description HTML
        html_content = item.get("content") or item.get("description") or ""
        soup = BeautifulSoup(html_content, "html.parser")

        # Strip navigation/footer elements
        for tag in soup.find_all(
            ["footer", "nav", "button", "a"],
            class_=re.compile(r"footer|nav|expand|collapse", re.I),
        ):
            tag.decompose()

        paragraphs = soup.find_all(["p", "div"])
        if paragraphs:
            for p in paragraphs:
                text = p.get_text(separator=" ", strip=True)
                text_lower = text.lower()
                if len(text) > 15 and not any(
                    bad in text_lower for bad in ignored_phrases
                ):
                    output_lines.append(text)
        else:
            raw_text = soup.get_text(separator=" ", strip=True)
            if len(raw_text) > 15 and not any(
                bad in raw_text.lower() for bad in ignored_phrases
            ):
                output_lines.append(raw_text)

    if len(output_lines) <= 1:
        raise Exception("Failed to parse clean text from USCCB feed.")

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
