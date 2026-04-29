"""
EnExGroup Day-Ahead Market data ingestion and cleaning.

Handles downloading yearly archives, scraping recent daily publications,
and cleaning / upsampling the raw Excel data to 15-minute intervals.
"""

from __future__ import annotations

import os
import re
import zipfile
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_RAW = REPO_ROOT / "data" / "raw"
DOWNLOAD_DIR = DATA_RAW / "downloaded_dam_results"
EXTRACT_DIR = DATA_RAW / "extracted_dam_results"
COMBINED_FILE = DATA_RAW / "combined_dam_results.xlsx"
REQUEST_TIMEOUT = 60

ARCHIVE_ZIPS = {
    2023: "https://www.enexgroup.gr/en/c/document_library/get_file?uuid=f543600f-3948-d3e9-c337-8ff7ee997794&groupId=20126",
    2024: "https://www.enexgroup.gr/en/c/document_library/get_file?uuid=6f2dc5b3-ef9b-b3a9-c935-ca44e7648b93&groupId=20126",
    2025: "https://www.enexgroup.gr/en/c/document_library/get_file?uuid=73d205d3-0885-f876-b995-d73ad1b934b8&groupId=20126",
}

PUBLICATIONS_BASE = "https://www.enexgroup.gr/en/web/guest/markets-publications-el-day-ahead-market"
RESULTS_INSTANCE = "com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_6eBaUXF5VIb7"

LOAD_CLASSIFICATIONS = ["HV", "MV", "LV", "CRETE LOAD", "LOSSES"]


def _download_file(url: str, dest_path: Path) -> bool:
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


def _extract_zip(zip_path: Path, extract_to: Path) -> None:
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_to)


def _scrape_results_publications() -> list[tuple[str, str]]:
    """Scrape the Results asset publisher on the publications page."""
    files: list[tuple[str, str]] = []
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
    pagination_text = ""
    for elem in soup.find_all(string=re.compile(r"Showing \d+ - \d+ of \d+ results")):
        pagination_text = elem.strip()
        break

    total_pages = 1
    if pagination_text:
        m = re.search(r"of (\d+) results", pagination_text)
        if m:
            total_results = int(m.group(1))
            total_pages = (total_results + 6) // 7
            print(f"Publications Results: {total_results} files across {total_pages} pages")

    def _parse_page(soup_obj):
        page_files = []
        for a in soup_obj.find_all("a", href=re.compile(r"/c/document_library/get_file")):
            href = a.get("href", "")
            text = a.get_text(strip=True)
            if "EL-DAM_Results_EN" in text and href:
                full_url = urljoin(PUBLICATIONS_BASE, href)
                page_files.append((text, full_url))
        return page_files

    files.extend(_parse_page(soup))
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
            files.extend(_parse_page(soup))
        except requests.RequestException as exc:
            print(f"Warning: could not fetch publications page {page_num}: {exc}")

    seen = set()
    unique_files = []
    for fname, furl in files:
        if fname not in seen:
            seen.add(fname)
            unique_files.append((fname, furl))
    return unique_files


def _parse_date_from_filename(filename: str) -> date | None:
    m = re.search(r"(\d{8})_EL-DAM_Results_EN", filename)
    if m:
        d = m.group(1)
        try:
            return date(int(d[:4]), int(d[4:6]), int(d[6:8]))
        except ValueError:
            return None
    return None


def download_and_combine(
    start_date: date = date(2023, 1, 1),
    end_date: date | None = None,
) -> Path:
    """
    Download all EnExGroup EL-DAM Results files in the date range and
    combine them into a single Excel file.

    Returns
    -------
    Path
        Path to the combined Excel file.
    """
    if end_date is None:
        end_date = date.today()

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
            if not _download_file(url, zip_path):
                print(f"  Failed to download {zip_name}")
                continue

        extract_path = EXTRACT_DIR / str(year)
        if not extract_path.exists():
            print(f"  Extracting {zip_name} ...")
            _extract_zip(zip_path, extract_path)
        else:
            print(f"  {zip_name} already extracted.")

        for xlsx in extract_path.rglob("*EL-DAM_Results_EN*.xlsx"):
            file_date = _parse_date_from_filename(xlsx.name)
            if file_date and start_date <= file_date <= end_date:
                all_xlsx_paths.append(xlsx)

    # Step 2: Scrape recent daily files
    print("\nScraping Day-Ahead Market Publications page for recent files...")
    recent_files = _scrape_results_publications()
    print(f"Found {len(recent_files)} recent Results files on publications page.")

    for fname, furl in recent_files:
        file_date = _parse_date_from_filename(fname)
        if not file_date or file_date < start_date or file_date > end_date:
            continue

        dest_path = DOWNLOAD_DIR / fname
        if dest_path.exists():
            print(f"  {fname} already exists, skipping download.")
        else:
            print(f"  Downloading {fname} ...")
            if not _download_file(furl, dest_path):
                continue
        all_xlsx_paths.append(dest_path)

    if not all_xlsx_paths:
        raise RuntimeError("No files found in the specified date range.")

    by_name = {}
    for p in all_xlsx_paths:
        by_name[p.name] = p
    unique_paths = sorted(by_name.values(), key=lambda p: p.name)
    print(f"\nTotal unique files to aggregate: {len(unique_paths)}")

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
        raise RuntimeError("No DataFrames could be read.")

    combined_df = pd.concat(all_dfs, ignore_index=True)
    combined_df.to_excel(COMBINED_FILE, index=False, engine="openpyxl")
    print(f"Done. Combined shape: {combined_df.shape}")
    return COMBINED_FILE


def clean_dam_data(input_file: Path | str = COMBINED_FILE) -> pd.DataFrame:
    """
    Clean and standardize the combined EnExGroup Day-Ahead Market data.

    Actions:
    1. Filter columns (keep DDAY, DELIVERY_MTU, MCP, CLASSIFICATION, TOTAL_TRADES).
    2. Aggregate load classifications into Total_Domestic_Load.
    3. Pivot CLASSIFICATION into wide Vol_* columns.
    4. Fill NaN with 0.
    5. Upsample historical 1-hour data to 15-minute intervals.

    Returns
    -------
    pd.DataFrame
        Cleaned DataFrame ready for merging.
    """
    input_file = Path(input_file)
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    print("Loading combined data...")
    df = pd.read_excel(input_file, engine="openpyxl")
    print(f"Loaded {len(df):,} rows, {len(df.columns)} columns.")

    keep_cols = ["DDAY", "DELIVERY_MTU", "MCP", "CLASSIFICATION", "TOTAL_TRADES"]
    df = df[keep_cols].copy()
    print(f"Filtered to {len(df.columns)} columns: {list(df.columns)}")

    df.loc[df["CLASSIFICATION"].isin(LOAD_CLASSIFICATIONS), "CLASSIFICATION"] = "Total_Domestic_Load"
    print("Aggregated load classifications into 'Total_Domestic_Load'.")

    grouped = (
        df.groupby(["DDAY", "DELIVERY_MTU", "CLASSIFICATION"], as_index=False)["TOTAL_TRADES"]
        .sum()
    )

    mcp_map = (
        df.groupby(["DDAY", "DELIVERY_MTU"])["MCP"]
        .first()
        .reset_index()
    )

    pivoted = grouped.pivot_table(
        index=["DDAY", "DELIVERY_MTU"],
        columns="CLASSIFICATION",
        values="TOTAL_TRADES",
        aggfunc="sum",
    ).reset_index()

    rename_map = {}
    for col in pivoted.columns:
        if col in ("DDAY", "DELIVERY_MTU"):
            continue
        if col == "Total_Domestic_Load":
            continue
        rename_map[col] = f"Vol_{col.replace(' ', '_')}"
    pivoted = pivoted.rename(columns=rename_map)
    pivoted = pivoted.merge(mcp_map, on=["DDAY", "DELIVERY_MTU"], how="left")

    if "Total_Domestic_Load" not in pivoted.columns:
        pivoted["Total_Domestic_Load"] = 0.0

    pivoted = pivoted.fillna(0)
    print(f"Pivot complete. Shape: {pivoted.shape}")

    # Upsample 1-hour data to 15-minute intervals
    pivoted["MTU_dt"] = pd.to_datetime(pivoted["DELIVERY_MTU"])
    pivoted["date"] = pivoted["MTU_dt"].dt.date

    daily_mtu_counts = pivoted.groupby("date")["MTU_dt"].nunique()
    hourly_days = daily_mtu_counts[daily_mtu_counts <= 30].index.tolist()
    quarter_days = daily_mtu_counts[daily_mtu_counts > 30].index.tolist()
    print(f"Hourly days: {len(hourly_days)} | 15-min days: {len(quarter_days)}")

    hourly_df = pivoted[pivoted["date"].isin(hourly_days)].copy()
    quarter_df = pivoted[pivoted["date"].isin(quarter_days)].copy()

    volume_cols = [c for c in hourly_df.columns if c not in ("DDAY", "DELIVERY_MTU", "MTU_dt", "date", "MCP")]

    if not hourly_df.empty:
        print("Upsampling hourly data to 15-minute intervals...")
        expanded_rows = []
        for _, row in hourly_df.iterrows():
            base_time = row["MTU_dt"]
            for offset_min in (0, 15, 30, 45):
                new_row = row.to_dict()
                new_time = base_time + pd.Timedelta(minutes=offset_min)
                new_row["MTU_dt"] = new_time
                new_row["DELIVERY_MTU"] = new_time.strftime("%Y-%m-%d %H:%M:%S")
                for col in volume_cols:
                    new_row[col] = row[col] / 4.0
                expanded_rows.append(new_row)
        hourly_expanded = pd.DataFrame(expanded_rows)
        print(f"Hourly rows expanded: {len(hourly_df):,} -> {len(hourly_expanded):,}")
    else:
        hourly_expanded = pd.DataFrame()

    final_df = pd.concat([hourly_expanded, quarter_df], ignore_index=True)
    final_df = final_df.sort_values(["DDAY", "MTU_dt"]).reset_index(drop=True)
    final_df = final_df.drop(columns=["MTU_dt", "date"], errors="ignore")
    final_df["DDAY"] = final_df["DDAY"].astype(int)

    print(f"Final shape: {final_df.shape}")
    return final_df


def run_full_ingestion(
    start_date: date = date(2023, 1, 1),
    end_date: date | None = None,
    output_file: Path | str | None = None,
) -> Path:
    """
    End-to-end ingestion: download, combine, clean, and save.

    Returns
    -------
    Path
        Path to the cleaned output file.
    """
    download_and_combine(start_date, end_date)
    df_clean = clean_dam_data()
    if output_file is None:
        output_file = DATA_RAW / "cleaned_dam_results.xlsx"
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    df_clean.to_excel(output_file, index=False, engine="openpyxl")
    print(f"\nSaved cleaned data to: {output_file.resolve()}")
    return output_file
