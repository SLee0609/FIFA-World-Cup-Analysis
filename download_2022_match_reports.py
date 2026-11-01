import os
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup

PAGE_URL = (
    "https://www.fifatrainingcentre.com/en/fwc2022/"
    "post-match-summaries/post-match-summary-reports.php"
)

OUTPUT_DIR = "2022_match_reports"

os.makedirs(OUTPUT_DIR, exist_ok=True)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0"
})

response = session.get(PAGE_URL)
response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")

pdf_urls = []

for link in soup.find_all("a", href=True):
    text = link.get_text(" ", strip=True)

    if (
        "Post Match Summary Report" in text
        and ".pdf" in link["href"].lower()
    ):
        pdf_urls.append(urljoin(PAGE_URL, link["href"]))

pdf_urls = list(dict.fromkeys(pdf_urls))

print(f"Found {len(pdf_urls)} PDFs")

for i, url in enumerate(pdf_urls, start=1):
    filename = os.path.basename(
        urlparse(unquote(url)).path
    )

    path = os.path.join(OUTPUT_DIR, filename)

    if os.path.exists(path):
        print(f"[{i}/{len(pdf_urls)}] Already exists: {filename}")
        continue

    print(f"[{i}/{len(pdf_urls)}] Downloading: {filename}")

    response = session.get(url)
    response.raise_for_status()

    with open(path, "wb") as f:
        f.write(response.content)

print("Done.")