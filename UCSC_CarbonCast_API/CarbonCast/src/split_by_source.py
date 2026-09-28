import os
import pandas as pd

EIA_DIR = "/Users/prarthanapatil/Documents/EnergyAPI/CarbonCast/UCSC_OSRE_CC_automation_tool/eiaData"
OUT_BASE = "../data"
CANONICAL_ORDER = ["coal", "nat_gas", "nuclear", "oil", "hydro", "solar", "wind", "other"]

for fname in sorted(os.listdir(EIA_DIR)):
    if not fname.endswith("_clean_mod.csv"):
        continue
    region = fname.replace("_clean_mod.csv", "")
    fpath = os.path.join(EIA_DIR, fname)
    df = pd.read_csv(fpath)

    date_col = df.columns[0]
    present_sources = [s for s in CANONICAL_ORDER if s in df.columns]

    out_dir = os.path.join(OUT_BASE, region, "fuel_forecast")
    os.makedirs(out_dir, exist_ok=True)

    for src in present_sources:
        out_df = df[[date_col, src]].copy()
        out_path = os.path.join(out_dir, f"{region}_{src}_clean.csv")
        out_df.to_csv(out_path, index=False)

    print(f"{region}: {present_sources} -> {out_dir}")
