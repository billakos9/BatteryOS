#!/usr/bin/env python3
"""
Fetch Day-Ahead Market (DAM) price data from ENTSO-E Transparency Platform
for Greece (10YGR-HTSO-----Y / IPTO) from 2023-01-01 to 2026-04-30.

Outputs:
    entsoe_dam_prices_greece.csv
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

import pandas as pd
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

API_KEY = os.getenv("ENTSOE_API_KEY")
if not API_KEY:
    print("Error: ENTSOE_API_KEY not found. Please set it in the .env file.")
    sys.exit(1)

BASE_URL = "https://web-api.tp.entsoe.eu/api"
AREA_CODE = "10YGR-HTSO-----Y"  # Greece / IPTO
DOCUMENT_TYPE = "A44"  # Price Document
PROCESS_TYPE = "A01"  # Day ahead

OUTPUT_FILE = Path("entsoe_dam_prices_greece.csv")


def _local_tag(elem) -> str:
    """Return local tag name without namespace."""
    tag = elem.tag
    if isinstance(tag, str) and "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def fetch_entsoe_chunk(period_start: datetime, period_end: datetime) -> pd.DataFrame:
    params = {
        "securityToken": API_KEY,
        "documentType": DOCUMENT_TYPE,
        "processType": PROCESS_TYPE,
        "in_Domain": AREA_CODE,
        "out_Domain": AREA_CODE,
        "periodStart": period_start.strftime("%Y%m%d%H%M"),
        "periodEnd": period_end.strftime("%Y%m%d%H%M"),
    }

    resp = requests.get(BASE_URL, params=params, timeout=120)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)

    records = []
    for ts in root.iter():
        if _local_tag(ts) != "TimeSeries":
            continue

        period = None
        for child in ts:
            if _local_tag(child) == "Period":
                period = child
                break
        if period is None:
            continue

        # Find timeInterval and resolution
        interval = None
        resolution = "PT60M"
        for child in period:
            tag = _local_tag(child)
            if tag == "timeInterval":
                interval = child
            elif tag == "resolution":
                resolution = child.text or "PT60M"

        if interval is None:
            continue

        start_elem = None
        for child in interval:
            if _local_tag(child) == "start":
                start_elem = child
                break

        if start_elem is None or not start_elem.text:
            continue

        base_time = datetime.fromisoformat(start_elem.text.replace("Z", "+00:00"))

        if resolution == "PT60M":
            delta = timedelta(hours=1)
        elif resolution == "PT30M":
            delta = timedelta(minutes=30)
        elif resolution == "PT15M":
            delta = timedelta(minutes=15)
        else:
            delta = timedelta(hours=1)

        for child in period:
            if _local_tag(child) != "Point":
                continue

            position = None
            price = None
            for pchild in child:
                ptag = _local_tag(pchild)
                if ptag == "position" and pchild.text:
                    position = int(pchild.text)
                elif ptag == "price.amount" and pchild.text:
                    price = float(pchild.text)

            if position is None or price is None:
                continue

            timestamp = base_time + (position - 1) * delta
            records.append({"timestamp": timestamp, "price_eur_mwh": price})

    return pd.DataFrame(records)


def main():
    # ENTSO-E periodEnd is the end of the interval; use May 1st 00:00 to include all of Apr 30
    start_date = datetime(2023, 1, 1)
    end_date = datetime(2026, 5, 1)

    all_dfs = []
    chunk_start = start_date

    while chunk_start < end_date:
        chunk_end = min(chunk_start + timedelta(days=365), end_date)
        print(f"Fetching {chunk_start.date()} to {chunk_end.date()} ...")
        try:
            df = fetch_entsoe_chunk(chunk_start, chunk_end)
            if not df.empty:
                all_dfs.append(df)
                print(f"  Retrieved {len(df)} records.")
            else:
                print("  No records found in this chunk.")
        except requests.HTTPError as exc:
            print(f"  HTTP error: {exc}")
        except Exception as exc:
            print(f"  Error: {exc}")

        chunk_start = chunk_end

    if not all_dfs:
        print("No data retrieved. Exiting.")
        sys.exit(1)

    combined = pd.concat(all_dfs, ignore_index=True)
    combined = combined.sort_values("timestamp").drop_duplicates(subset=["timestamp"])
    combined.to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved {len(combined):,} records to {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    main()
