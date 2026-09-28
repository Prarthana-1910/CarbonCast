#!/usr/bin/env python3
"""
populate_and_backfill_gb_grid.py

1. Ingests existing entsoeData/GB_clean_mod.csv (2024-12-01 to 2026-05-31),
   resamples 30m -> 1h, computes direct/lifecycle CI, and loads into Django EmissionActual.
2. Fetches the missing gap (2026-06-01 to today: 2026-09-23) from NESO API,
   upserts into EmissionActual, and appends to entsoeData/GB_clean_mod.csv.
3. Exports complete, hourly training CSVs into data/GB/fuel_forecast/ and data/GB/.
"""

import os
import sys
import logging
from datetime import datetime, timezone, timedelta
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gb_grid_sync")

# Setup paths & Django
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
CARBONCAST_API_DIR = os.path.join(SRC_DIR, "CarbonCastAPI")
if CARBONCAST_API_DIR not in sys.path:
    sys.path.insert(0, CARBONCAST_API_DIR)
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "CarbonCastAPI.settings")
import django
django.setup()

from CarbonCastRESTAPI.models import EmissionActual
from CarbonCastRESTAPI.services import neso_service

RAW_CSV_PATH = os.path.join(SRC_DIR, "entsoeData", "GB_clean_mod.csv")
TRAINING_DATA_DIR = os.path.join(SRC_DIR, "..", "data", "GB")
FUEL_FORECAST_DIR = os.path.join(TRAINING_DATA_DIR, "fuel_forecast")

COLUMN_MAP = {
    "GAS": "nat_gas",
    "COAL": "coal",
    "NUCLEAR": "nuclear",
    "WIND": "wind",
    "HYDRO": "hydro",
    "SOLAR": "solar",
    "BIOMASS": "biomass",
    "OTHER": "other",
}

SOURCES_LIST = ["biomass", "coal", "nat_gas", "hydro", "nuclear", "solar", "wind", "other"]

def step1_load_existing_raw_csv():
    logger.info(f"=== Step 1: Loading existing data from {RAW_CSV_PATH} ===")
    if not os.path.exists(RAW_CSV_PATH):
        raise FileNotFoundError(f"Cannot find {RAW_CSV_PATH}")

    df = pd.read_csv(RAW_CSV_PATH)
    logger.info(f"Read {len(df)} rows from existing raw CSV")

    # Filter to needed columns
    needed_cols = ["DATETIME"] + [c for c in COLUMN_MAP.keys() if c in df.columns]
    df = df[needed_cols].copy()
    df["DATETIME"] = pd.to_datetime(df["DATETIME"], utc=True)

    for col in COLUMN_MAP.keys():
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        else:
            df[col] = 0.0

    # Resample 30m -> 1h mean
    df_hourly = df.set_index("DATETIME")[list(COLUMN_MAP.keys())].resample("1h").mean().reset_index()
    df_hourly = df_hourly.rename(columns=COLUMN_MAP)
    logger.info(f"Resampled to {len(df_hourly)} hourly rows ({df_hourly['DATETIME'].min()} to {df_hourly['DATETIME'].max()})")

    # Upsert into EmissionActual
    res = neso_service.upsert_hourly_df_to_db(df_hourly)
    logger.info(f"Step 1 DB result: {res}")
    return df_hourly['DATETIME'].max()


def step2_fetch_and_append_neso_gap(last_existing_dt):
    # Start the next day or hour after last_existing_dt
    start_dt = (last_existing_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    today_dt = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    logger.info(f"=== Step 2: Fetching NESO gap from {start_dt} to {today_dt} ===")
    
    # 1. Fetch from NESO API
    start_iso = f"{start_dt}T00:00:00.000Z"
    end_iso = f"{today_dt}T23:59:59.999Z"
    records = neso_service.fetch_neso_records(start_iso, end_iso)
    logger.info(f"Fetched {len(records)} raw gap records from NESO API")

    if not records:
        logger.info("No new records returned from NESO API")
        return

    # 2. Append raw records to entsoeData/GB_clean_mod.csv
    gap_raw_df = pd.DataFrame(records)
    existing_raw_df = pd.read_csv(RAW_CSV_PATH)
    combined_raw = pd.concat([existing_raw_df, gap_raw_df], ignore_index=True)
    combined_raw = combined_raw.drop_duplicates(subset=["DATETIME"], keep="last").sort_values("DATETIME").reset_index(drop=True)
    combined_raw.to_csv(RAW_CSV_PATH, index=False)
    logger.info(f"Updated {RAW_CSV_PATH}: total rows = {len(combined_raw)}")

    # 3. Resample gap records to hourly and upsert to EmissionActual
    df_gap_hourly = neso_service.process_records_to_hourly_df(records)
    res = neso_service.upsert_hourly_df_to_db(df_gap_hourly)
    logger.info(f"Step 2 DB result: {res}")


def step3_export_training_csvs():
    logger.info(f"=== Step 3: Exporting aligned training CSVs to {TRAINING_DATA_DIR} ===")
    os.makedirs(FUEL_FORECAST_DIR, exist_ok=True)

    rows = list(EmissionActual.objects.filter(region="GB", metric_type="carbon").order_by("ts"))
    if not rows:
        raise ValueError("No EmissionActual rows found for GB!")

    logger.info(f"Found {len(rows)} hourly rows for GB in EmissionActual (from {rows[0].ts} to {rows[-1].ts})")

    # 1. Per-source clean CSVs
    for source in SOURCES_LIST:
        out_path = os.path.join(FUEL_FORECAST_DIR, f"GB_{source}_clean.csv")
        records = []
        for r in rows:
            val = (r.data or {}).get(source, 0.0)
            records.append({
                "UTC time": r.ts.strftime("%Y-%m-%d %H:%M"),
                source: val
            })
        out_df = pd.DataFrame(records)
        out_df.to_csv(out_path, index=False)
        logger.info(f"Wrote {len(out_df)} rows to {out_path}")

    # 2. Direct & Lifecycle emissions CSVs
    for cef_type in ["direct", "lifecycle"]:
        out_path = os.path.join(TRAINING_DATA_DIR, f"GB_{cef_type}_emissions.csv")
        records = []
        for r in rows:
            val = getattr(r, cef_type)
            records.append({
                "UTC time": r.ts.strftime("%Y-%m-%d %H:%M"),
                "carbon_intensity": val if val is not None else 0.0
            })
        out_df = pd.DataFrame(records)
        out_df.to_csv(out_path, index=False)
        logger.info(f"Wrote {len(out_df)} rows to {out_path}")


def main():
    last_dt = step1_load_existing_raw_csv()
    step2_fetch_and_append_neso_gap(last_dt)
    step3_export_training_csvs()
    logger.info("##### ALL GRID DATA FOR GB IS SYNCHRONIZED AND READY #####")


if __name__ == "__main__":
    main()
