"""
split_eu_combined_to_per_source.py

Splits each EU region's combined entsoeData/<REGION>_clean_mod.csv
into separate per-source files matching the working US region pattern:
    ../data/<REGION>/fuel_forecast/<REGION>_<source>_clean.csv

Only writes files for sources that are NOT all-zero for that region.

Usage:
    python3 split_eu_combined_to_per_source.py
"""

import os
import pandas as pd

REGIONS = ["RO"]

SOURCES = ["biomass","coal","nat_gas","geothermal","hydro",
           "nuclear","oil","solar","wind","other"]

ENTSOE_DIR = "entsoeData"

for region in REGIONS:
    inPath = f"{ENTSOE_DIR}/{region}_clean_mod.csv"
    if not os.path.exists(inPath):
        print(f"SKIPPING {region} -- {inPath} not found")
        continue

    df = pd.read_csv(inPath, parse_dates=["UTC time"])
    outDir = f"../data/{region}/fuel_forecast"
    os.makedirs(outDir, exist_ok=True)

    written = []
    skipped_zero = []
    for source in SOURCES:
        if source not in df.columns:
            continue
        if (df[source] == 0).all():
            skipped_zero.append(source)
            continue

        outDf = df[["UTC time", source]].copy()
        outPath = f"{outDir}/{region}_{source}_clean.csv"
        outDf.to_csv(outPath, index=False)
        written.append(source)

    print(f"{region}: wrote {len(written)} source files {written} | "
          f"skipped all-zero: {skipped_zero}")

print("\nDone.")