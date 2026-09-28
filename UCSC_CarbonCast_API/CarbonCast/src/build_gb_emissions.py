"""
Builds GB's direct and lifecycle emissions files from ACTUAL generation-by-source
data, using the exact same carbon-rate formula as every other region.

Output structure matches every other region exactly:
    UTC time, carbon_intensity, <source1>, <source2>, ...

Run:
    python3 build_gb_emissions.py
"""

import pandas as pd

GB_SOURCE_FILE = "entsoeData/GB_clean_mod.csv"  # update path if it actually lives elsewhere

DATETIME_COL = "DATETIME"

# Map GB's actual column names -> standard lowercase source names used
# everywhere else in the pipeline (matches carbonRateDirect/carbonRateLifecycle keys)
GB_COLUMN_MAP = {
    "COAL": "coal",
    "GAS": "nat_gas",
    "NUCLEAR": "nuclear",
    "HYDRO": "hydro",
    "WIND": "wind",
    "SOLAR": "solar",
    "BIOMASS": "biomass",
    "OTHER": "other",
}

CARBON_RATE_DIRECT = {
    "coal": 760, "biomass": 0, "nat_gas": 370, "geothermal": 0, "hydro": 0,
    "nuclear": 0, "oil": 406, "solar": 0, "unknown": 575, "other": 575, "wind": 0,
}
CARBON_RATE_LIFECYCLE = {
    "coal": 820, "biomass": 230, "nat_gas": 490, "geothermal": 38, "hydro": 24,
    "nuclear": 12, "oil": 650, "solar": 45, "unknown": 700, "other": 700, "wind": 11,
}


def calculate_ci(df: pd.DataFrame, source_cols: list, carbon_rate: dict) -> pd.Series:
    row_sum = df[source_cols].sum(axis=1)
    ci = pd.Series(0.0, index=df.index)

    for col in source_cols:
        rate = carbon_rate[col]
        frac = df[col] / row_sum.replace(0, pd.NA)
        ci += frac.fillna(0) * rate

    zero_mask = row_sum == 0
    ci[zero_mask] = ci.shift(1)[zero_mask]

    return ci.round(2)


df = pd.read_csv(GB_SOURCE_FILE)

missing_raw_cols = [c for c in GB_COLUMN_MAP if c not in df.columns]
if missing_raw_cols:
    raise ValueError(f"Expected raw columns not found: {missing_raw_cols}. "
                      f"Actual columns: {list(df.columns)}")

renamed = df.rename(columns=GB_COLUMN_MAP)
source_cols = list(GB_COLUMN_MAP.values())

ci_direct = calculate_ci(renamed, source_cols, CARBON_RATE_DIRECT)
ci_lifecycle = calculate_ci(renamed, source_cols, CARBON_RATE_LIFECYCLE)

# Build output with SAME structure as every other region:
# UTC time, carbon_intensity, <source1>, <source2>, ...
out_direct = pd.DataFrame({"UTC time": df[DATETIME_COL], "carbon_intensity": ci_direct})
out_lifecycle = pd.DataFrame({"UTC time": df[DATETIME_COL], "carbon_intensity": ci_lifecycle})

for col in source_cols:
    out_direct[col] = renamed[col]
    out_lifecycle[col] = renamed[col]

direct_out_path = "../data/GB/GB_direct_emissions.csv"
lifecycle_out_path = "../data/GB/GB_lifecycle_emissions.csv"

out_direct.to_csv(direct_out_path, index=False)
out_lifecycle.to_csv(lifecycle_out_path, index=False)

print(f"Columns in output: {list(out_direct.columns)}")
print(f"Wrote {len(out_direct)} rows to {direct_out_path}")
print(f"Wrote {len(out_lifecycle)} rows to {lifecycle_out_path}")
print(f"\nSample (first 3 rows, direct):")
print(out_direct.head(3))