#!/usr/bin/env python3
"""
Clean and standardize the combined EnExGroup Day-Ahead Market data.

Pipeline:
1. Filter columns (keep only DDAY, DELIVERY_MTU, MCP, CLASSIFICATION, TOTAL_TRADES).
2. Aggregate load classifications into Total_Domestic_Load.
3. Pivot CLASSIFICATION into wide Vol_* columns.
4. Fill NaN with 0.
5. Upsample historical 1-hour data to 15-minute intervals:
   - MCP: forward-fill (same price for all 4 quarters).
   - Volumes: divide by 4.
6. Save cleaned file.
"""

import sys
from pathlib import Path

import pandas as pd

INPUT_FILE = Path("combined_dam_results.xlsx")
OUTPUT_FILE = Path("cleaned_dam_results.xlsx")

LOAD_CLASSIFICATIONS = ["HV", "MV", "LV", "CRETE LOAD", "LOSSES"]


def main():
    if not INPUT_FILE.exists():
        print(f"Input file not found: {INPUT_FILE}")
        sys.exit(1)

    print("Loading combined data...")
    df = pd.read_excel(INPUT_FILE, engine="openpyxl")
    print(f"Loaded {len(df):,} rows, {len(df.columns)} columns.")

    # ------------------------------------------------------------------
    # 1. Filter columns
    # ------------------------------------------------------------------
    keep_cols = ["DDAY", "DELIVERY_MTU", "MCP", "CLASSIFICATION", "TOTAL_TRADES"]
    df = df[keep_cols].copy()
    print(f"Filtered to {len(df.columns)} columns: {list(df.columns)}")

    # ------------------------------------------------------------------
    # 2. Aggregate load demand
    # ------------------------------------------------------------------
    df.loc[df["CLASSIFICATION"].isin(LOAD_CLASSIFICATIONS), "CLASSIFICATION"] = "Total_Domestic_Load"
    print("Aggregated load classifications into 'Total_Domestic_Load'.")

    # Group by DDAY + DELIVERY_MTU + CLASSIFICATION, sum TOTAL_TRADES
    # MCP is constant per timestamp, so we keep it via a separate lookup.
    grouped = (
        df.groupby(["DDAY", "DELIVERY_MTU", "CLASSIFICATION"], as_index=False)
        ["TOTAL_TRADES"]
        .sum()
    )

    # Extract MCP per timestamp (constant across classifications)
    mcp_map = (
        df.groupby(["DDAY", "DELIVERY_MTU"])["MCP"]
        .first()
        .reset_index()
    )

    # ------------------------------------------------------------------
    # 3. Pivot (long -> wide)
    # ------------------------------------------------------------------
    pivoted = grouped.pivot_table(
        index=["DDAY", "DELIVERY_MTU"],
        columns="CLASSIFICATION",
        values="TOTAL_TRADES",
        aggfunc="sum",
    ).reset_index()

    # Rename volume columns to Vol_*
    rename_map = {}
    for col in pivoted.columns:
        if col in ("DDAY", "DELIVERY_MTU"):
            continue
        if col == "Total_Domestic_Load":
            continue
        rename_map[col] = f"Vol_{col.replace(' ', '_')}"
    pivoted = pivoted.rename(columns=rename_map)

    # Merge MCP back
    pivoted = pivoted.merge(mcp_map, on=["DDAY", "DELIVERY_MTU"], how="left")

    # Ensure Total_Domestic_Load exists even if empty
    if "Total_Domestic_Load" not in pivoted.columns:
        pivoted["Total_Domestic_Load"] = 0.0

    # Fill NaN with 0
    pivoted = pivoted.fillna(0)
    print(f"Pivot complete. Shape: {pivoted.shape}")
    print(f"Columns: {list(pivoted.columns)}")

    # ------------------------------------------------------------------
    # 4. Upsample 1-hour data to 15-minute intervals
    # ------------------------------------------------------------------
    pivoted["MTU_dt"] = pd.to_datetime(pivoted["DELIVERY_MTU"])
    pivoted["date"] = pivoted["MTU_dt"].dt.date

    # Determine granularity per day (hourly <= 30 unique MTUs, else 15-min)
    daily_mtu_counts = pivoted.groupby("date")["MTU_dt"].nunique()
    hourly_days = daily_mtu_counts[daily_mtu_counts <= 30].index.tolist()
    quarter_days = daily_mtu_counts[daily_mtu_counts > 30].index.tolist()
    print(f"Hourly days: {len(hourly_days)} | 15-min days: {len(quarter_days)}")

    hourly_df = pivoted[pivoted["date"].isin(hourly_days)].copy()
    quarter_df = pivoted[pivoted["date"].isin(quarter_days)].copy()

    # Identify volume columns (everything except identifiers + MCP)
    volume_cols = [c for c in hourly_df.columns if c not in ("DDAY", "DELIVERY_MTU", "MTU_dt", "date", "MCP")]

    # Expand hourly rows to 15-min rows
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
                # Divide volumes by 4; keep MCP unchanged
                for col in volume_cols:
                    new_row[col] = row[col] / 4.0
                expanded_rows.append(new_row)

        hourly_expanded = pd.DataFrame(expanded_rows)
        print(f"Hourly rows expanded: {len(hourly_df):,} -> {len(hourly_expanded):,}")
    else:
        hourly_expanded = pd.DataFrame()

    # Combine
    final_df = pd.concat([hourly_expanded, quarter_df], ignore_index=True)

    # Sort and clean up
    final_df = final_df.sort_values(["DDAY", "MTU_dt"]).reset_index(drop=True)
    final_df = final_df.drop(columns=["MTU_dt", "date"], errors="ignore")

    # Ensure DDAY stays as integer YYYYMMDD
    final_df["DDAY"] = final_df["DDAY"].astype(int)

    # ------------------------------------------------------------------
    # 5. Save
    # ------------------------------------------------------------------
    final_df.to_excel(OUTPUT_FILE, index=False, engine="openpyxl")
    print(f"\nSaved cleaned data to: {OUTPUT_FILE.resolve()}")
    print(f"Final shape: {final_df.shape}")
    print(f"Columns: {list(final_df.columns)}")


if __name__ == "__main__":
    main()
