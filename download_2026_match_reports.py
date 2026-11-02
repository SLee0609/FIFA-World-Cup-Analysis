import os
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, unquote

PAGES = [
    "https://www.fifatrainingcentre.com/en/fifa-world-cup-2026/match-report-hub.php",
    "https://www.fifatrainingcentre.com/en/fifa-world-cup-2026/match-report-hub-knockout-stage.php",
]

OUTPUT_DIR = "2026_match_reports"

# ------------------------------------------------------------
# Choose which matches to download.
#
# None         -> download every match
# {1, 2, 3}    -> download only matches 1, 2, and 3
# set(range(1, 73)) -> group stage only
# ------------------------------------------------------------
MATCH_NUMBERS = None

os.makedirs(OUTPUT_DIR, exist_ok=True)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0"
})

pdf_urls = []

# Find every PDF linked from the two hub pages
for page_url in PAGES:
    response = session.get(page_url)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    for link in soup.find_all("a", href=True):
        href = link["href"]

        if ".pdf" in href.lower():
            pdf_urls.append(urljoin(page_url, href))

# Remove duplicates
pdf_urls = list(dict.fromkeys(pdf_urls))

print(f"Found {len(pdf_urls)} PDF reports.")

for url in pdf_urls:
    decoded_url = unquote(url)

    # Extract match number from filenames such as PMSR-M01 ...
    match = re.search(r"PMSR-M(\d+)", decoded_url, re.IGNORECASE)

    if not match:
        print(f"Skipping unrecognized URL: {url}")
        continue

    match_number = int(match.group(1))

    if MATCH_NUMBERS is not None and match_number not in MATCH_NUMBERS:
        continue

    filename = os.path.basename(urlparse(decoded_url).path).strip()

    # Remove potentially problematic filename characters
    filename = re.sub(r'[<>:"/\\|?*]', "_", filename)

    path = os.path.join(OUTPUT_DIR, filename)

    if os.path.exists(path):
        print(f"Already exists: {filename}")
        continue

    print(f"Downloading Match {match_number}: {filename}")

    response = session.get(url)
    response.raise_for_status()

    with open(path, "wb") as f:
        f.write(response.content)

print("Done.")