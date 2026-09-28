#!/usr/bin/env python3
"""
sync_gb_training_data.py

Matches and aligns the date ranges of weather and grid data for Great Britain (GB):
1. Reads the available weather data from data/GB/GB_weather_merged.csv (or GB_weather_forecast_168.csv).
2. Reads the available grid generation data from data/GB/fuel_forecast/ and emissions files.
3. Finds the common intersection: [max(start_w, start_g), min(end_w, end_g)].
4. Trims both sides to exact 1-to-1 matching timestamps, guaranteeing identical row counts.
5. Updates DATASET_LIMITER in firstTierConfig.json to match the aligned row count.
"""

import os
import json
import logging
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sync_gb_training_data")

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
GB_DATA_DIR = os.path.normpath(os.path.join(SRC_DIR, "..", "data", "GB"))
FUEL_DIR = os.path.join(GB_DATA_DIR, "fuel_forecast")
FIRST_TIER_CONFIG = os.path.join(SRC_DIR, "firstTierConfig.json")

SOURCES = ["biomass", "coal", "nat_gas", "hydro", "nuclear", "solar", "wind", "other"]

def sync_data():
    weather_merged_path = os.path.join(GB_DATA_DIR, "GB_weather_merged.csv")
    if not os.path.exists(weather_merged_path):
        raise FileNotFoundError(f"Weather merged file not found: {weather_merged_path}")

    # 1. Read weather timestamps
    w_df = pd.read_csv(weather_merged_path)
    w_time_col = [c for c in w_df.columns if "time" in c.lower() or "date" in c.lower()][0]
    w_df["ts"] = pd.to_datetime(w_df[w_time_col], errors="coerce").dt.tz_localize(None)
    w_df = w_df.dropna(subset=["ts"]).drop_duplicates(subset=["ts"]).sort_values("ts")

    w_start = w_df["ts"].min()
    w_end = w_df["ts"].max()
    logger.info(f"Weather range: {w_start} -> {w_end} ({len(w_df)} hours)")

    # 2. Read grid timestamps (using wind as reference)
    ref_grid_path = os.path.join(FUEL_DIR, "GB_wind_clean.csv")
    if not os.path.exists(ref_grid_path):
        raise FileNotFoundError(f"Grid reference file not found: {ref_grid_path}")

    g_df = pd.read_csv(ref_grid_path)
    g_time_col = [c for c in g_df.columns if "time" in c.lower() or "date" in c.lower()][0]
    g_df["ts"] = pd.to_datetime(g_df[g_time_col], errors="coerce").dt.tz_localize(None)
    g_df = g_df.dropna(subset=["ts"]).drop_duplicates(subset=["ts"]).sort_values("ts")

    g_start = g_df["ts"].min()
    g_end = g_df["ts"].max()
    logger.info(f"Grid range: {g_start} -> {g_end} ({len(g_df)} hours)")

    # 3. Intersection
    common_start = max(w_start, g_start)
    common_end = min(w_end, g_end)
    logger.info(f"Common aligned range: {common_start} -> {common_end}")

    # Inner join timestamps
    common_ts = pd.merge(
        w_df[["ts"]],
        g_df[["ts"]],
        on="ts",
        how="inner"
    ).sort_values("ts").reset_index(drop=True)

    aligned_count = len(common_ts)
    logger.info(f"Total matching 1-hour timestamps: {aligned_count}")

    if aligned_count == 0:
        raise ValueError("No overlapping timestamps between weather and grid data!")

    common_ts_set = set(common_ts["ts"])

    # 4. Filter and overwrite fuel files
    for s in SOURCES:
        fpath = os.path.join(FUEL_DIR, f"GB_{s}_clean.csv")
        df = pd.read_csv(fpath)
        df["ts"] = pd.to_datetime(df["UTC time"], errors="coerce").dt.tz_localize(None)
        df_aligned = df[df["ts"].isin(common_ts_set)].sort_values("ts").reset_index(drop=True)
        df_aligned["UTC time"] = df_aligned["ts"].dt.strftime("%Y-%m-%d %H:%M")
        df_aligned[["UTC time", s]].to_csv(fpath, index=False)
        logger.info(f"Aligned GB_{s}_clean.csv: {len(df_aligned)} rows")

    # 5. Filter and overwrite direct & lifecycle emissions
    for cef in ["direct", "lifecycle"]:
        fpath = os.path.join(GB_DATA_DIR, f"GB_{cef}_emissions.csv")
        df = pd.read_csv(fpath)
        df["ts"] = pd.to_datetime(df["UTC time"], errors="coerce").dt.tz_localize(None)
        df_aligned = df[df["ts"].isin(common_ts_set)].sort_values("ts").reset_index(drop=True)
        df_aligned["UTC time"] = df_aligned["ts"].dt.strftime("%Y-%m-%d %H:%M")
        df_aligned[["UTC time", "carbon_intensity"]].to_csv(fpath, index=False)
        logger.info(f"Aligned GB_{cef}_emissions.csv: {len(df_aligned)} rows")

    # 6. Update DATASET_LIMITER in firstTierConfig.json
    if os.path.exists(FIRST_TIER_CONFIG):
        with open(FIRST_TIER_CONFIG, "r") as f:
            ft = json.load(f)
        ft["TRAIN_TEST_PERIOD"]["PERIOD_0"]["DATASET_LIMITER"] = aligned_count
        with open(FIRST_TIER_CONFIG, "w") as f:
            json.dump(ft, f, indent=4)
        logger.info(f"Updated DATASET_LIMITER in firstTierConfig.json to {aligned_count}")

    print(f"\nSUCCESS: GB data synchronized to {aligned_count} aligned hours ({common_start} to {common_end}).")
    return aligned_count

if __name__ == "__main__":
    sync_data()
