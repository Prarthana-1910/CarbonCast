"""
Build Tier 2's FORECAST_IN_FILE_NAME by merging:
  1. Tier 1's per-source production forecast outputs
     (../data/<REGION>/fuel_forecast/<REGION>_ANN_<source>_iter<N>.csv)
  2. The continuous hourly weather file
     (../data/<REGION>/<REGION>_weather_merged.csv, or similar)
Then block-reshapes the result into overlapping BLOCK_HOURS-hour windows
(sliding 24hrs at a time), matching the same structure used for the
Tier 1 weather input file.

Usage:
    python3 build_tier2_forecast_input.py <REGION> <WEATHER_MERGED_CSV> <BLOCK_HOURS> [ITER_NUM]

Example:
    python3 build_tier2_forecast_input.py FPC ../data/FPC/FPC_weather_merged.csv 168 0

Output:
    ../data/<REGION>/<REGION>_<BLOCK_HOURS>hr_forecasts_DA.csv
    (continuous, pre-block version also saved alongside as
     ../data/<REGION>/<REGION>_<BLOCK_HOURS>hr_forecasts_DA_continuous.csv for inspection)
"""

import sys
import glob
import pandas as pd

if len(sys.argv) < 4:
    print(__doc__)
    sys.exit(1)

region = sys.argv[1]
weatherMergedFile = sys.argv[2]
BLOCK_HOURS = int(sys.argv[3])
iterNum = sys.argv[4] if len(sys.argv) > 4 else "0"

fuelForecastDir = f"../data/{region}/fuel_forecast"
outDir = f"../data/{region}"

# ---- Step 1: find and merge all per-source Tier 1 forecast outputs ----
pattern = f"{fuelForecastDir}/{region}_ANN_*_iter{iterNum}.csv"
sourceFiles = sorted(glob.glob(pattern))

if len(sourceFiles) == 0:
    print(f"ERROR: no files matched pattern {pattern}")
    print("Check that Tier 1 has been run and iter number is correct.")
    sys.exit(1)

print(f"Found {len(sourceFiles)} source forecast files:")
for f in sourceFiles:
    print(" ", f)

merged = None
for f in sourceFiles:
    df = pd.read_csv(f)
    df["datetime"] = pd.to_datetime(df["datetime"], format="mixed")
    # keep only datetime + avg_<source>_production_forecast column
    fcstCols = [c for c in df.columns if c.startswith("avg_") and c.endswith("_production_forecast")]
    if len(fcstCols) != 1:
        print(f"WARNING: expected exactly 1 forecast column in {f}, found {fcstCols}. Using first.")
    keepCol = fcstCols[0]
    df = df[["datetime", keepCol]]

    beforeDedup = len(df)
    dupCount = df["datetime"].duplicated().sum()
    if dupCount > 0:
        # Each real hour may appear multiple times (once per overlapping day-ahead
        # forecast window). Collapse to one row per real hour by averaging the
        # forecasted value across all forecast horizons that covered that hour.
        df = df.groupby("datetime", as_index=False)[keepCol].mean()
        print(f"{f}: {beforeDedup} rows -> deduplicated to {len(df)} unique hours "
              f"({dupCount} duplicate rows averaged)")
    else:
        print(f"{f}: {beforeDedup} rows, no duplicates")

    merged = df if merged is None else merged.merge(df, on="datetime", how="inner")

print(f"\nAfter merging all sources: {len(merged)} rows")
print(f"Date range: {merged['datetime'].min()} -> {merged['datetime'].max()}")

# ---- Step 2: merge with continuous weather data ----
weather = pd.read_csv(weatherMergedFile)
weather["datetime"] = pd.to_datetime(weather["datetime"], format="mixed")
weatherCols = [c for c in weather.columns if c != "datetime" and c != "region"]
weather = weather[["datetime"] + weatherCols]

combined = merged.merge(weather, on="datetime", how="inner")
combined = combined.sort_values("datetime").reset_index(drop=True)

print(f"\nAfter merging with weather: {len(combined)} rows")
print(f"Date range: {combined['datetime'].min()} -> {combined['datetime'].max()}")
print(f"Columns: {list(combined.columns)}")

nanCount = combined.isna().sum().sum()
print(f"Total NaNs: {nanCount}")
if nanCount > 0:
    print("WARNING: NaNs present. Consider forward/back-filling before proceeding.")

continuousOutPath = f"{outDir}/{region}_{BLOCK_HOURS}hr_forecasts_DA_continuous.csv"
combined.to_csv(continuousOutPath, index=False)
print(f"\nWrote continuous merged file: {continuousOutPath}")

# ---- Step 3: block-reshape into overlapping BLOCK_HOURS windows ----
n_days = (len(combined) - BLOCK_HOURS) // 24 + 1
if n_days <= 0:
    print(f"ERROR: only {len(combined)} rows after merge -- not enough for one {BLOCK_HOURS}-hour block.")
    sys.exit(1)

blocks = []
for day in range(n_days):
    start = day * 24
    block = combined.iloc[start:start + BLOCK_HOURS].copy()
    if len(block) < BLOCK_HOURS:
        break
    blocks.append(block)

blocked = pd.concat(blocks, ignore_index=True)
blockedOutPath = f"{outDir}/{region}_{BLOCK_HOURS}hr_forecasts_DA.csv"
blocked.to_csv(blockedOutPath, index=False)

print(f"\n{len(combined)} hourly rows -> {len(blocks)} day-blocks x {BLOCK_HOURS}hr -> {len(blocked)} rows")
print(f"Wrote block-reshaped file: {blockedOutPath}")
print(f"\nNUM_TEST_DAYS + NUM_VAL_DAYS must be <= {len(blocks)} for splitWeatherDataset to work in Tier 2")