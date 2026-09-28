
#!/usr/bin/env python3
import sys, os, glob
import pandas as pd
import json
import argparse

BASE = os.path.dirname(os.path.abspath(__file__))
WEATHER_PROCESSED_DIR = os.path.join(BASE, "processed_data")
EIA_DIR = "/Users/prarthanapatil/Documents/EnergyAPI/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src/eiaData"
DATA_OUT_DIR = os.path.join(BASE, "data")

SOURCE_LIST_ALL = ["coal", "nat_gas", "nuclear", "oil", "hydro", "solar", "wind", "other"]

def build_weather_forecast_csv(region, out_path):
    region_dir = os.path.join(WEATHER_PROCESSED_DIR, region)
    if not os.path.isdir(region_dir):
        raise FileNotFoundError(f"No processed_data folder for {region}")
    var_map = {"WIND": None, "TEMP": None, "DPT": None, "DSWRF": None, "PCP": None}
    for var in var_map:
        matches = sorted(glob.glob(os.path.join(region_dir, f"*{var}*.csv")))
        if matches:
            var_map[var] = matches[-1]  # prefer largest/most complete if multiple

    print(f"  Weather files found: { {k: os.path.basename(v) if v else None for k,v in var_map.items()} }")
    missing = [v for v, p in var_map.items() if p is None]
    if missing:
        print(f"  WARNING: missing weather vars: {missing}")

    dfs = []
    for var, path in var_map.items():
        if path is None:
            continue
        df = pd.read_csv(path)
        dt_col = next((c for c in df.columns if "date" in c.lower() or "time" in c.lower()), df.columns[0])
        df = df.rename(columns={dt_col: "datetime"})
        df["datetime"] = pd.to_datetime(df["datetime"])
        val_cols = [c for c in df.columns if c != "datetime"]
        if len(val_cols) == 1:
            df = df.rename(columns={val_cols[0]: var.lower()})
        print(f"    {var}: {len(df)} rows from {os.path.basename(path)}")
        dfs.append(df.set_index("datetime"))

    if not dfs:
        raise FileNotFoundError(f"No weather files to merge for {region}")

    merged = pd.concat(dfs, axis=1, join="inner").sort_index()  # keep only hours ALL vars have
    merged = merged.reset_index()
    merged.to_csv(out_path, index=False)
    print(f"  Wrote merged weather -> {out_path} ({len(merged)} rows)")
    return len(merged)

def find_eia_file(region):
    for name in [f"{region}_clean_mod.csv", f"{region}_clean.csv", f"{region}.csv"]:
        p = os.path.join(EIA_DIR, name)
        if os.path.exists(p):
            return p
    return None

def split_eia_by_source(region, eia_path, out_dir):
    df = pd.read_csv(eia_path)
    time_col = "UTC time" if "UTC time" in df.columns else df.columns[0]
    df[time_col] = pd.to_datetime(df[time_col])
    df = df.set_index(time_col)
    os.makedirs(out_dir, exist_ok=True)
    sources_present = []
    for source in SOURCE_LIST_ALL:
        if source in df.columns:
            sources_present.append(source)
            df[[source]].to_csv(os.path.join(out_dir, f"{region}_{source}_clean.csv"))
    print(f"  Split EIA into {len(sources_present)} sources: {sources_present} ({len(df)} rows)")
    return sources_present, len(df)

def compute_periods(total_hours, val_days, test_days):
    total_days = total_hours // 24
    train_days = total_days - val_days - test_days
    if train_days < 30:
        raise ValueError(f"Not enough data: {total_days} days total (need >= {val_days+test_days+30})")
    return {"PERIOD_0": {"DATASET_LIMITER": (train_days+val_days)*24,
                          "OUT_FILE_SUFFIX": "custom_period", "NUM_TEST_DAYS": test_days}}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("region")
    ap.add_argument("--val-days", type=int, default=30)
    ap.add_argument("--test-days", type=int, default=30)
    args = ap.parse_args()
    region = args.region
    print(f"=== {region} ===")

    region_data_dir = os.path.join(DATA_OUT_DIR, region)
    fuel_dir = os.path.join(region_data_dir, "fuel_forecast")
    os.makedirs(fuel_dir, exist_ok=True)

    weather_out = os.path.join(region_data_dir, f"{region}_weather_forecast.csv")
    weather_rows = build_weather_forecast_csv(region, weather_out)

    eia_path = find_eia_file(region)
    if eia_path is None:
        print(f"  ERROR: no EIA file for {region} in {EIA_DIR}")
        sys.exit(1)
    sources, eia_rows = split_eia_by_source(region, eia_path, fuel_dir)

    total_hours = min(weather_rows, eia_rows)
    print(f"  Overlap: {total_hours} hours (~{total_hours//24} days)")
    if total_hours < (args.val_days + args.test_days + 30) * 24:
        print(f"  ERROR: not enough overlapping data to train. Check weather_rows={weather_rows} vs eia_rows={eia_rows}")
        sys.exit(1)

    periods = compute_periods(total_hours, args.val_days, args.test_days)

    t1_region = {
        "IN_FILE_NAME_PREFIX": f"data/{region}/fuel_forecast/{region}_",
        "WEATHER_FORECAST_IN_FILE_NAME": f"data/{region}/{region}_weather_forecast.csv",
        "OUT_FILE_NAME_PREFIX": f"data/{region}/fuel_forecast/{region}_ANN",
        "AGGREGATED_FORECAST_OUT_FILE_NAME": f"data/{region}/{region}_96hr_forecasts_DA.csv",
        "SOURCES": [s.upper() for s in sources],
        "SOURCE_COL": list(range(len(sources))),
        "PARTIAL_FORECAST_AVAILABILITY_LIST": [0]*len(sources),
        "PARTIAL_FORECAST_HOURS": 24
    }
    t1 = {
        "REGION": [region], "NUM_VAL_DAYS": args.val_days,
        "MODEL_SLIDING_WINDOW_LEN": 24, "TRAINING_WINDOW_HOURS": 24,
        "PREDICTION_WINDOW_HOURS": 96, "MAX_PREDICTION_WINDOW_HOURS": 96,
        "NUM_FEATURES": 6, "NUM_WEATHER_FEATURES": 5,
        "NUMBER_OF_EXPERIMENTS_PER_REGION": 1,
        "SAVED_MODEL_LOCATION": "saved_first_tier_models/",
        "TRAIN_TEST_PERIOD": periods, "IN_FILE_NAME_SUFFIX": "_clean.csv",
        region: t1_region
    }
    p1 = os.path.join(BASE, f"{region}_first_tier_config.json")
    json.dump(t1, open(p1, "w"), indent=2)
    print(f"  Wrote {p1}")

    t2_region = {
        "DIRECT_CEF_IN_FILE_NAME": f"data/{region}/{region}_direct_emissions.csv",
        "LIFECYCLE_CEF_IN_FILE_NAME": f"data/{region}/{region}_lifecycle_emissions.csv",
        "FORECAST_IN_FILE_NAME": f"data/{region}/{region}_96hr_forecasts_DA.csv",
        "DIRECT_CEF_OUT_FILE_NAME_PREFIX": f"CI_forecast_data/{region}/{region}_direct_96hr_CI_forecasts",
        "LIFECYCLE_CEF_OUT_FILE_NAME_PREFIX": f"CI_forecast_data/{region}/{region}_lifecycle_96hr_CI_forecasts",
        "NUM_FORECAST_FEATURES": 5 + len(sources)
    }
    t2 = {
        "REGION_DIRECT": [region], "NUM_TEST_DAYS": args.test_days, "NUM_VAL_DAYS": args.val_days,
        "MODEL_SLIDING_WINDOW_LEN": 24, "TRAINING_WINDOW_HOURS": 24,
        "PREDICTION_WINDOW_HOURS": 96, "MAX_PREDICTION_WINDOW_HOURS": 96,
        "TOP_N_FEATURES": 5, "START_COL": 1, "NUM_FEATURES": 6,
        "NUMBER_OF_EXPERIMENTS_PER_REGION": 1,
        "DIRECT_SAVED_MODEL_LOCATION": "saved_second_tier_models/direct/",
        "LIFECYCLE_SAVED_MODEL_LOCATION": "saved_second_tier_models/lifecycle/",
        "WRITE_CI_FORECASTS_TO_FILE": "True",
        "SECOND_TIER_CNN_LSTM_MODEL_HYPERPARAMS": {
            "EPOCH": 100, "BATCH_SIZE": [10], "ACTIVATION_FUNC": "relu",
            "LOSS_FUNC": "mse", "LEARNING_RATE": 0.01, "MIN_LEARNING_RATE": 0.001,
            "CNN_KERNEL1": 4, "CNN_KERNEL2": 4, "CNN_NUM_FILTERS1": 4,
            "CNN_NUM_FILTERS2": 16, "CNN_POOL_SIZE": 2, "LSTM_DROPOUT_RATE": 0.1, "DENSE_UNITS": 20
        },
        region: t2_region
    }
    p2 = os.path.join(BASE, f"{region}_second_tier_config.json")
    json.dump(t2, open(p2, "w"), indent=2)
    print(f"  Wrote {p2}")

    print(f"\nRun tier 1:  $python_env firstTierForecasts.py {region}_first_tier_config.json")
    print(f"Run tier 2:  $python_env secondTierForecasts.py {region}_second_tier_config.json -d")

if __name__ == "__main__":
    main()
