#!/usr/bin/env python3
"""
align_emissions_to_forecast.py

Aligns both direct and lifecycle emissions CSVs to exactly match
<REGION>_168hr_forecasts_DA.csv on real timestamps. MUST be the last
step before tier-2 training — do not re-export grid data after this.

Usage:
    python3 align_emissions_to_forecast.py --region BANC
"""
import argparse
import pandas as pd
import os


def align(region):
    fcst_path = f"../data/{region}/{region}_168hr_forecasts_DA.csv"
    fcst = pd.read_csv(fcst_path)
    # Coerce to tz-naive datetime64 regardless of source format
    fcst["datetime"] = pd.to_datetime(fcst["datetime"], errors="coerce").dt.tz_localize(None)
    unique_hours = fcst[["datetime"]].drop_duplicates()

    for cef_type in ("direct", "lifecycle"):
        emis_path = f"../data/{region}/{region}_{cef_type}_emissions.csv"
        emis = pd.read_csv(emis_path)
        # Coerce 'UTC time' to the same tz-naive datetime64 type
        emis["UTC time"] = pd.to_datetime(emis["UTC time"], errors="coerce").dt.tz_localize(None)
        emis = emis.dropna(subset=["UTC time"])

        merged = unique_hours.merge(emis, left_on="datetime", right_on="UTC time", how="inner")
        aligned = (
            merged[["UTC time", "carbon_intensity"]]
            .sort_values("UTC time")
            .reset_index(drop=True)
        )
        # Write back as readable string (no timezone suffix)
        aligned["UTC time"] = aligned["UTC time"].dt.strftime("%Y-%m-%d %H:%M")
        aligned.to_csv(emis_path, index=False)
        print(
            f"[{region}][{cef_type}] aligned to {len(aligned)} rows "
            f"({aligned['UTC time'].min()} -> {aligned['UTC time'].max()})"
        )
        if len(aligned) != len(unique_hours):
            print(f"  WARNING: {len(aligned)} != {len(unique_hours)} forecast hours")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", required=True)
    args = parser.parse_args()
    align(args.region)