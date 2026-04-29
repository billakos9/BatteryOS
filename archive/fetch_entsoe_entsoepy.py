#!/usr/bin/env python3
"""
Fetch ENTSO-E data for Greece using entsoe-py library.

Fetches four document types from 2023-01-01 to 2026-04-30:
1. Day-Ahead Market Prices
2. Day-Ahead Generation Forecast
3. Day-Ahead Load Forecast  
4. Actual Generation by Type (Solar, Wind Onshore, etc.)

Saves each as both CSV and Excel for easy inspection.
"""
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytz
from dotenv import load_dotenv
from entsoe import EntsoePandasClient

load_dotenv()

API_KEY = os.getenv("ENTSOE_API_KEY")
if not API_KEY:
    print("Error: ENTSOE_API_KEY not found in .env")
    sys.exit(1)

# Configuration
COUNTRY_CODE = "GR"  # Greece
TIMEZONE = "Europe/Athens"
START = pd.Timestamp("2023-01-01", tz=TIMEZONE)
END = pd.Timestamp("2026-04-30", tz=TIMEZONE)

OUTPUT_DIR = Path("entsoe_data")
OUTPUT_DIR.mkdir(exist_ok=True)

client = EntsoePandasClient(api_key=API_KEY)


def chunk_fetch(fetch_func, *args, **kwargs):
    """Fetch data in yearly chunks to avoid API limits."""
    all_dfs = []
    chunk_start = START
    
    while chunk_start < END:
        chunk_end = min(chunk_start + pd.DateOffset(years=1), END)
        print(f"  Fetching {chunk_start.date()} to {chunk_end.date()} ...")
        
        try:
            df = fetch_func(*args, start=chunk_start, end=chunk_end, **kwargs)
            if df is not None and not df.empty:
                if isinstance(df, pd.Series):
                    df = df.to_frame(name="value")
                all_dfs.append(df)
                print(f"    -> {len(df)} rows")
            else:
                print(f"    -> No data")
        except Exception as e:
            print(f"    -> Error: {e}")
        
        chunk_start = chunk_end
    
    if not all_dfs:
        return None
    
    combined = pd.concat(all_dfs)
    
    # Handle duplicate MultiIndex/columns
    if isinstance(combined.index, pd.MultiIndex):
        combined = combined[~combined.index.duplicated(keep='first')]
    elif isinstance(combined.index, pd.DatetimeIndex):
        combined = combined[~combined.index.duplicated(keep='first')]
    else:
        combined = combined.drop_duplicates()
    
    return combined


def save_dataframe(df: pd.DataFrame, name: str):
    """Save DataFrame as both CSV and Excel."""
    if df is None or df.empty:
        print(f"  Skipping {name} (no data)")
        return
    
    csv_path = OUTPUT_DIR / f"{name}.csv"
    excel_path = OUTPUT_DIR / f"{name}.xlsx"
    
    df.to_csv(csv_path)
    print(f"    Saved CSV:  {csv_path}")
    
    try:
        df.to_excel(excel_path)
        print(f"    Saved Excel: {excel_path}")
    except Exception as e:
        print(f"    Excel save failed: {e}")


def main():
    print(f"Fetching ENTSO-E data for Greece ({COUNTRY_CODE})")
    print(f"Period: {START.date()} to {END.date()}")
    print(f"Output directory: {OUTPUT_DIR.resolve()}")
    print("=" * 60)
    
    # 1. Day-Ahead Market Prices
    print("\n1. Day-Ahead Market Prices")
    print("-" * 40)
    df_prices = chunk_fetch(client.query_day_ahead_prices, COUNTRY_CODE)
    if df_prices is not None:
        df_prices.columns = ["price_eur_mwh"]
        save_dataframe(df_prices, "day_ahead_prices")
    
    # 2. Day-Ahead Generation Forecast
    print("\n2. Day-Ahead Generation Forecast")
    print("-" * 40)
    df_gen_forecast = chunk_fetch(client.query_generation_forecast, COUNTRY_CODE)
    if df_gen_forecast is not None:
        if isinstance(df_gen_forecast.columns, pd.MultiIndex):
            df_gen_forecast.columns = ["_".join(col).strip() if isinstance(col, tuple) else col for col in df_gen_forecast.columns]
        save_dataframe(df_gen_forecast, "generation_forecast")
    
    # 3. Day-Ahead Load Forecast
    print("\n3. Day-Ahead Load Forecast")
    print("-" * 40)
    df_load_forecast = chunk_fetch(client.query_load_forecast, COUNTRY_CODE)
    if df_load_forecast is not None:
        if isinstance(df_load_forecast.columns, pd.MultiIndex):
            df_load_forecast.columns = ["_".join(col).strip() if isinstance(col, tuple) else col for col in df_load_forecast.columns]
        save_dataframe(df_load_forecast, "load_forecast")
    
    # 4. Actual Generation by Type
    print("\n4. Actual Generation by Type")
    print("-" * 40)
    df_generation = chunk_fetch(client.query_generation, COUNTRY_CODE)
    if df_generation is not None:
        if isinstance(df_generation.columns, pd.MultiIndex):
            df_generation.columns = ["_".join(col).strip() if isinstance(col, tuple) else col for col in df_generation.columns]
        save_dataframe(df_generation, "actual_generation_by_type")
    
    # 5. Create combined summary
    print("\n5. Creating combined summary")
    print("-" * 40)
    dfs = {}
    if df_prices is not None:
        dfs["price"] = df_prices["price_eur_mwh"]
    if df_gen_forecast is not None:
        col = df_gen_forecast.columns[0]
        dfs["generation_forecast"] = df_gen_forecast[col]
    if df_load_forecast is not None:
        col = df_load_forecast.columns[0]
        dfs["load_forecast"] = df_load_forecast[col]
    
    if dfs:
        summary = pd.DataFrame(dfs)
        summary.index.name = "timestamp"
        save_dataframe(summary, "combined_summary")
        print(f"\nCombined summary shape: {summary.shape}")
        print(f"Columns: {list(summary.columns)}")
    
    print("\n" + "=" * 60)
    print("Done! Files saved to:", OUTPUT_DIR.resolve())


if __name__ == "__main__":
    main()
