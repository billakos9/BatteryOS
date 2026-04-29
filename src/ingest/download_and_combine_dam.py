#!/usr/bin/env python3
"""
Download EL-DAM Results Excel files from ENEX Group for dates ranging
from 2023-01-01 to 2026-04-15, then aggregate them into a single file.

Strategy:
1. Download yearly zip archives for 2023, 2024, 2025 from the archive page.
2. Scrape the Day-Ahead Market Publications page for 2026 daily Results files.
3. Extract all xlsx files and combine them.
"""

import os
import re
import sys
import zipfile
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

# Configuration
DOWNLOAD_DIR = Path("downloaded_dam_results")
EXTRACT_DIR = Path("extracted_dam_results")
COMBINED_FILE = Path("combined_dam_results.xlsx")
REQUEST_TIMEOUT = 60

# Date range
START_DATE = date(2023, 1, 1)
END_DATE = date(2026, 4, 29)

# Archive zip URLs (from /en/web/guest/dam-idm-archive)
ARCHIVE_ZIPS = {
    2023: "https://www.enexgroup.gr/en/c/document_library/get_file?uuid=f543600f-3948-d3e9-c337-8ff7ee997794&groupId=20126",
    2024: "https://www.enexgroup.gr/en/c/document_library/get_file?uuid=6f2dc5b3-ef9b-b3a9-c935-ca44e7648b93&groupId=20126",
    2025: "https://www.enexgroup.gr/en/c/document_library/get_file?uuid=73d205d3-0885-f876-b995-d73ad1b934b8&groupId=20126",
}

# Publications page for scraping recent daily files
PUBLICATIONS_BASE = "https://www.enexgroup.gr/en/web/guest/markets-publications-el-day-ahead-market"
RESULTS_INSTANCE = "com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_6eBaUXF5VIb7"


def download_file(url: str, dest_path: Path) -> bool:
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            dest_path.write_bytes(response.content)
            return True
        else:
            print(f"  HTTP {response.status_code} for {url}")
            return False
    except requests.RequestException as exc:
        print(f"  Error downloading {url}: {exc}")
        return False


def extract_zip(zip_path: Path, extract_to: Path):
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(extract_to)


def scrape_results_publications() -> list[tuple[str, str]]:
    """Scrape the Results asset publisher on the publications page.
    Returns list of (filename, url) tuples.
    """
    files = []
    # First, fetch page 1 to determine total pages
    page1_url = (
        f"{PUBLICATIONS_BASE}?p_p_id={RESULTS_INSTANCE}"
        f"&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
        f"&_{RESULTS_INSTANCE}_delta=7&p_r_p_resetCur=false"
        f"&_{RESULTS_INSTANCE}_cur=1"
    )
    try:
        resp = requests.get(page1_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"Warning: could not fetch publications page 1: {exc}")
        return files

    soup = BeautifulSoup(resp.text, "html.parser")
    # Find pagination info
    pagination_text = ""
    for elem in soup.find_all(string=re.compile(r"Showing \d+ - \d+ of \d+ results")):
        pagination_text = elem.strip()
        break

    total_pages = 1
    if pagination_text:
        m = re.search(r"of (\d+) results", pagination_text)
        if m:
            total_results = int(m.group(1))
            total_pages = (total_results + 6) // 7  # 7 per page
            print(f"Publications Results: {total_results} files across {total_pages} pages")

    def parse_page(soup_obj):
        page_files = []
        # Links in this asset publisher point to /en/c/document_library/get_file?uuid=...
        for a in soup_obj.find_all("a", href=re.compile(r"/c/document_library/get_file")):
            href = a.get("href", "")
            text = a.get_text(strip=True)
            if "EL-DAM_Results_EN" in text and href:
                full_url = urljoin(PUBLICATIONS_BASE, href)
                page_files.append((text, full_url))
        return page_files

    files.extend(parse_page(soup))

    for page_num in range(2, total_pages + 1):
        page_url = (
            f"{PUBLICATIONS_BASE}?p_p_id={RESULTS_INSTANCE}"
            f"&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
            f"&_{RESULTS_INSTANCE}_delta=7&p_r_p_resetCur=false"
            f"&_{RESULTS_INSTANCE}_cur={page_num}"
        )
        try:
            resp = requests.get(page_url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            files.extend(parse_page(soup))
        except requests.RequestException as exc:
            print(f"Warning: could not fetch publications page {page_num}: {exc}")

    # Deduplicate by filename
    seen = set()
    unique_files = []
    for fname, furl in files:
        if fname not in seen:
            seen.add(fname)
            unique_files.append((fname, furl))
    return unique_files


def parse_date_from_filename(filename: str) -> date | None:
    m = re.search(r"(\d{8})_EL-DAM_Results_EN", filename)
    if m:
        d = m.group(1)
        try:
            return date(int(d[:4]), int(d[4:6]), int(d[6:8]))
        except ValueError:
            return None
    return None


def main():
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    EXTRACT_DIR.mkdir(exist_ok=True)

    all_xlsx_paths = []

    # Step 1: Download and extract archive zips
    print("Downloading yearly archive zips...")
    for year, url in ARCHIVE_ZIPS.items():
        zip_name = f"{year}_archive.zip"
        zip_path = DOWNLOAD_DIR / zip_name
        if zip_path.exists():
            print(f"  {zip_name} already exists, skipping download.")
        else:
            print(f"  Downloading {zip_name} ...")
            if not download_file(url, zip_path):
                print(f"  Failed to download {zip_name}")
                continue

        extract_path = EXTRACT_DIR / str(year)
        if not extract_path.exists():
            print(f"  Extracting {zip_name} ...")
            extract_zip(zip_path, extract_path)
        else:
            print(f"  {zip_name} already extracted.")

        # Find EL-DAM_Results xlsx files
        for xlsx in extract_path.rglob("*EL-DAM_Results_EN*.xlsx"):
            file_date = parse_date_from_filename(xlsx.name)
            if file_date and START_DATE <= file_date <= END_DATE:
                all_xlsx_paths.append(xlsx)

    # Step 2: Scrape and download recent daily files from publications page
    print("\nScraping Day-Ahead Market Publications page for recent files...")
    recent_files = scrape_results_publications()
    print(f"Found {len(recent_files)} recent Results files on publications page.")

    for fname, furl in recent_files:
        file_date = parse_date_from_filename(fname)
        if not file_date or file_date < START_DATE or file_date > END_DATE:
            continue

        dest_path = DOWNLOAD_DIR / fname
        if dest_path.exists():
            print(f"  {fname} already exists, skipping download.")
        else:
            print(f"  Downloading {fname} ...")
            if not download_file(furl, dest_path):
                continue
        all_xlsx_paths.append(dest_path)

    if not all_xlsx_paths:
        print("No files found in the specified date range. Exiting.")
        sys.exit(1)

    # Deduplicate by filename (prefer direct download over extracted if same name)
    by_name = {}
    for p in all_xlsx_paths:
        by_name[p.name] = p
    unique_paths = sorted(by_name.values(), key=lambda p: p.name)
    print(f"\nTotal unique files to aggregate: {len(unique_paths)}")

    # Step 3: Aggregate
    print(f"Aggregating into '{COMBINED_FILE}' ...")
    all_dfs = []
    for fpath in unique_paths:
        try:
            df = pd.read_excel(fpath, engine="openpyxl")
            df["source_file"] = fpath.name
            all_dfs.append(df)
        except Exception as exc:
            print(f"  Warning: could not read {fpath.name}: {exc}")

    if not all_dfs:
        print("No DataFrames could be read. Exiting.")
        sys.exit(1)

    combined_df = pd.concat(all_dfs, ignore_index=True)
    combined_df.to_excel(COMBINED_FILE, index=False, engine="openpyxl")

    print(f"Done. Combined shape: {combined_df.shape}")
    print(f"Saved to: {COMBINED_FILE.resolve()}")


if __name__ == "__main__":
    main()
