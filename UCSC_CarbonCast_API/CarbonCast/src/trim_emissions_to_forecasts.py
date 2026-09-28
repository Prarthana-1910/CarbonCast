"""
trim_emissions_to_forecast_aligned.py

Aligns each region's <REGION>_direct_emissions.csv to exactly match
<REGION>_168hr_forecasts_DA_continuous.csv on real timestamps (inner join),
not just date-range bounds. This guarantees identical row counts and
identical row-by-row timestamps, preventing the positional-mismatch
crash in Tier 2's manipulateTrainingDataShape().

Usage:
    python3 trim_emissions_to_forecast_aligned.py
"""

import pandas as pd
import os

REGIONS = ["BANC"]
# Add/adjust this list to match whatever regions you're processing.

for region in REGIONS:
    print("="*42)
    print(f"Processing {region}")
    print("="*42)

    fcstPath = f"../data/{region}/{region}_168hr_forecasts_DA_continuous.csv"
    emisPath = f"../data/{region}/{region}_direct_emissions.csv"

    if not os.path.exists(fcstPath):
        print(f"SKIPPING {region} -- {fcstPath} not found")
        continue
    if not os.path.exists(emisPath):
        print(f"SKIPPING {region} -- {emisPath} not found")
        continue

    fcst = pd.read_csv(fcstPath, parse_dates=["datetime"])
    emis = pd.read_csv(emisPath, parse_dates=["UTC time"])

    beforeFcst = len(fcst)
    beforeEmis = len(emis)

    # Inner join on exact timestamp -- guarantees same length AND same
    # row-by-row order on both sides, unlike date-bounds trimming.
    merged = fcst[["datetime"]].drop_duplicates().merge(
        emis, left_on="datetime", right_on="UTC time", how="inner"
    )

    aligned = merged[["UTC time", "carbon_intensity"]].sort_values("UTC time").reset_index(drop=True)

    aligned.to_csv(emisPath, index=False)

    print(f"Forecast unique hours: {fcst['datetime'].nunique()} (raw rows: {beforeFcst})")
    print(f"Emissions before: {beforeEmis} rows")
    print(f"Aligned emissions: {len(aligned)} rows | "
          f"{aligned['UTC time'].min()} -> {aligned['UTC time'].max()}")

    if len(aligned) != fcst["datetime"].nunique():
        print(f"WARNING: aligned emissions ({len(aligned)}) still doesn't match "
              f"forecast unique hours ({fcst['datetime'].nunique()}) -- "
              f"check for duplicate timestamps in emissions file.")

print("\n========== DONE ==========")