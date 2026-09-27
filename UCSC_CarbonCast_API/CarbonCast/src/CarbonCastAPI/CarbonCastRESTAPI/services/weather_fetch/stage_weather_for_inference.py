#!/usr/bin/env python3
"""
stage_weather_for_inference.py

Reformats merge_hourly_weather.py's output into exactly what
firstTierForecasts.py / secondTierForecasts.py expect at:
    <output_dir>/<region>/<region>_weather_forecast_<start_date>.csv

Usage:
    python3 stage_weather_for_inference.py <merged_csv> <region> <start_date> <output_dir>

Example:
    python3 stage_weather_for_inference.py \
        CISO_weather_merged.csv CISO 2026-08-21 \
        /path/to/CARBONCAST_REAL_TIME_WEATHER_DIR
"""

import sys
import os
import pandas as pd
from datetime import datetime, timezone

# TODO: CONFIRM this order against the actual trained model before trusting
# inference output — check saved_first_tier_models/CISO/CISO_SOLAR_min_max_values.txt
# row order to verify.
WEATHER_COLUMN_ORDER = ["wind_speed", "temp", "dpt", "dswrf", "precip"]


def main():
    if len(sys.argv) != 5:
        print(__doc__)
        sys.exit(1)

    merged_csv, region, start_date, output_dir = sys.argv[1:5]

    df = pd.read_csv(merged_csv, parse_dates=["datetime"])
    df = df.drop(columns=["region"], errors="ignore")

    missing = [c for c in WEATHER_COLUMN_ORDER if c not in df.columns]
    if missing:
        raise ValueError(f"Missing expected columns: {missing}. Have: {list(df.columns)}")

    df = df[["datetime"] + WEATHER_COLUMN_ORDER]

    creation_time = datetime.now(timezone.utc).isoformat()
    df.insert(1, "creation_time (UTC)", creation_time)
    df.insert(2, "version", "weather-stage-v1")

    out_dir = os.path.join(output_dir, region)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{region}_weather_forecast_{start_date}.csv")
    df.to_csv(out_path, index=False)
    print(f"Staged {len(df)} rows -> {out_path}")
    print(f"Columns: {list(df.columns)}")


if __name__ == "__main__":
    main()