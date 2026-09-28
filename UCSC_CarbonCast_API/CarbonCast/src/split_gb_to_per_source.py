"""
split_gb_to_per_source.py

Converts

    entsoeData/GB_clean_mod.csv

into

    ../data/GB/fuel_forecast/
        GB_biomass_clean.csv
        GB_coal_clean.csv
        GB_nat_gas_clean.csv
        GB_hydro_clean.csv
        GB_nuclear_clean.csv
        GB_solar_clean.csv
        GB_wind_clean.csv
        GB_other_clean.csv
"""

import os
import pandas as pd

INPUT_FILE = "entsoeData/GB_clean_mod.csv"
OUT_DIR = "../data/GB/fuel_forecast"

os.makedirs(OUT_DIR, exist_ok=True)

df = pd.read_csv(INPUT_FILE)

COLUMN_MAP = {
    "BIOMASS": "biomass",
    "COAL": "coal",
    "GAS": "nat_gas",
    "HYDRO": "hydro",
    "NUCLEAR": "nuclear",
    "SOLAR": "solar",
    "WIND": "wind",
    "OTHER": "other",
}

# Rename datetime column to match CarbonCast
df = df.rename(columns={"DATETIME": "UTC time"})

# Replace 'T' with a space
df["UTC time"] = (
    df["UTC time"]
    .astype(str)
    .str.replace("T", " ", regex=False)
)

written = []

for original, target in COLUMN_MAP.items():

    if original not in df.columns:
        print(f"Missing column: {original}")
        continue

    out = df[["UTC time", original]].copy()
    out.columns = ["UTC time", target]

    out.to_csv(
        os.path.join(
            OUT_DIR,
            f"GB_{target}_clean.csv"
        ),
        index=False
    )

    written.append(target)

print("\nCreated files:")
for w in written:
    print(f"GB_{w}_clean.csv")