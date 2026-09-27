#!/usr/bin/env python3
"""
run_full_retraining_batch_v2.py — full retraining pipeline for a list of
regions. Each region isolated so one failure doesn't stop the batch.
"""
import argparse
import subprocess
import logging
import traceback
import os
import shutil
import json

logger = logging.getLogger("run_full_retraining_batch_v2")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CARBONCAST_SRC_DIR = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src"
PROCESSED_DATA_DIR = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_OSRE_CC_automation_tool/CarbonCast/processed_data"
PIPELINE_SCRIPTS_DIR = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_OSRE_CC_automation_tool/CarbonCast/src/python/pipeline"
BUILD_FINAL_DATASET_DIR = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src/CarbonCastAPI/CarbonCastRESTAPI/services/weekly_training"
PYTHON_BIN = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/.venv/bin/python"
MANAGE_PY_DIR = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src/CarbonCastAPI"


def run(cmd, cwd=None):
    logger.info(f"RUN: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)

def ensure_rda_processed(region):
    """Skip reprocessing if retraining_archive_processed/{region}/ already
    has the 5 AVG CSVs; otherwise run process_weather_data.py first."""
    import os
    check_path = f"/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_OSRE_CC_automation_tool/CarbonCast/retraining_archive_processed/{region}/{region}_AVG_TEMP.csv"
    if os.path.exists(check_path):
        logger.info(f"[{region}] RDA data already processed — skipping process_weather_data.py")
        return
    logger.info(f"[{region}] RDA data NOT processed yet — running process_weather_data.py")
    run([PYTHON_BIN, "process_weather_data.py", "--region", region], cwd=PIPELINE_SCRIPTS_DIR)

def concat_weather(region):
    run([PYTHON_BIN, "build_final_training_dataset.py", "--region", region], cwd=BUILD_FINAL_DATASET_DIR)


def prep_weather_for_training(region):
    combined_dir = f"{BUILD_FINAL_DATASET_DIR}/final_training_data/{region}"
    staging_dir = f"{combined_dir}/hourly_staging"
    training_data_dir = f"/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/data/{region}"

    os.makedirs(staging_dir, exist_ok=True)
    os.makedirs(training_data_dir, exist_ok=True)

    # expand_weather_to_hourly.py / merge_hourly_weather.py / reshape_weather_to_dayblocks.py
    # live in PROCESSED_DATA_DIR, not PIPELINE_SCRIPTS_DIR
    run([PYTHON_BIN, "expand_weather_to_hourly.py",
         f"{combined_dir}/{region}_AVG_TEMP.csv", f"{staging_dir}/{region}_temp_hourly.csv", "temp", "fcst"],
        cwd=PROCESSED_DATA_DIR)
    run([PYTHON_BIN, "expand_weather_to_hourly.py",
         f"{combined_dir}/{region}_AVG_DPT.csv", f"{staging_dir}/{region}_dpt_hourly.csv", "dpt", "fcst"],
        cwd=PROCESSED_DATA_DIR)
    run([PYTHON_BIN, "expand_weather_to_hourly.py",
         f"{combined_dir}/{region}_AVG_WIND_SPEED.csv", f"{staging_dir}/{region}_wind_hourly.csv", "wind_speed", "fcst"],
        cwd=PROCESSED_DATA_DIR)
    run([PYTHON_BIN, "expand_weather_to_hourly.py",
         f"{combined_dir}/{region}_AVG_DSWRF.csv", f"{staging_dir}/{region}_dswrf_hourly.csv", "dswrf", "avg"],
        cwd=PROCESSED_DATA_DIR)
    run([PYTHON_BIN, "expand_weather_to_hourly.py",
         f"{combined_dir}/{region}_AVG_PCP.csv", f"{staging_dir}/{region}_precip_hourly.csv", "precip", "acc"],
        cwd=PROCESSED_DATA_DIR)

    merged = f"{staging_dir}/{region}_weather_merged.csv"
    run([PYTHON_BIN, "merge_hourly_weather.py", region, merged,
         f"{staging_dir}/{region}_temp_hourly.csv",
         f"{staging_dir}/{region}_dpt_hourly.csv",
         f"{staging_dir}/{region}_dswrf_hourly.csv",
         f"{staging_dir}/{region}_wind_hourly.csv",
         f"{staging_dir}/{region}_precip_hourly.csv"],
        cwd=PROCESSED_DATA_DIR)

    out_path = f"{training_data_dir}/{region}_weather_forecast_168.csv"
    run([PYTHON_BIN, "reshape_weather_to_dayblocks.py", merged, out_path, "168"], cwd=PROCESSED_DATA_DIR)

    shutil.copy(merged, f"{training_data_dir}/{region}_weather_merged.csv")


def prep_grid_data(region, days_back=97):
    # First check if DB already has data; if not, run the full backfill.
    check_cmd = (
        "from CarbonCastRESTAPI.models import EmissionActual; "
        f"count = EmissionActual.objects.filter(region='{region}').count(); "
        f"print('AECI_ROW_COUNT=' + str(count))"
    )
    import subprocess as _sp
    check = _sp.run(
        [PYTHON_BIN, "manage.py", "shell", "-c", check_cmd],
        cwd=MANAGE_PY_DIR, capture_output=True, text=True
    )
    row_count = 0
    for line in check.stdout.splitlines():
        if line.startswith("AECI_ROW_COUNT="):
            try:
                row_count = int(line.split("=", 1)[1])
            except ValueError:
                pass

    if row_count == 0:
        logger.info(f"[{region}] No EmissionActual rows found — running backfill ({days_back} days)")
        backfill_cmd = (
            "from CarbonCastRESTAPI.services.weather_fetch.prepare_grid_data_for_retraining "
            f"import backfill_region; backfill_region('{region}', {days_back})"
        )
        run([PYTHON_BIN, "manage.py", "shell", "-c", backfill_cmd], cwd=MANAGE_PY_DIR)
    else:
        logger.info(f"[{region}] {row_count} EmissionActual rows already present — skipping backfill")

    shell_cmd = (
        "from CarbonCastRESTAPI.services.weekly_training.prepare_grid_data_for_retraining "
        "import verify_region, export_training_csvs; "
        f"verification = verify_region('{region}'); "
        f"export_training_csvs('{region}'); "
        f"print('[{region}] GRID DATA READY: ' "
        f"+ str(verification['total_days']) + ' days, ' "
        f"+ str(verification['incomplete_days']) + ' incomplete')"
    )

    cmd = [
        PYTHON_BIN,
        "manage.py",
        "shell",
        "-c",
        shell_cmd,
    ]

    run(cmd, cwd=MANAGE_PY_DIR)


def compute_dataset_limiter(region):
    import pandas as pd
    import glob
    import os

    fuel_forecast_dir = (
        f"/Users/prarthanapatil/Documents/EnergyAPI11/"
        f"CarbonCast/UCSC_CarbonCast_API/CarbonCast/data/"
        f"{region}/fuel_forecast"
    )

    candidates = glob.glob(
        f"{fuel_forecast_dir}/{region}_*_clean.csv"
    )

    if not candidates:
        raise FileNotFoundError(
            f"No *_clean.csv files found for {region} "
            f"in {fuel_forecast_dir}"
        )

    # Use the longest/most complete fuel dataset.
    path = max(candidates, key=os.path.getsize)

    df = pd.read_csv(path)

    if "UTC time" not in df.columns:
        raise ValueError(
            f"{path} does not contain 'UTC time'. "
            f"Columns: {df.columns.tolist()}"
        )

    df["UTC time"] = pd.to_datetime(
        df["UTC time"],
        errors="coerce"
    )

    df = df.dropna(subset=["UTC time"])
    df = df.drop_duplicates(subset=["UTC time"], keep="first")

    electricity_rows = len(df)

    # --- NEW: also check weather's actual continuous hourly row count ---
    # (NOT the block-reshaped {region}_weather_forecast_168.csv — that has
    # sliding-window duplication and is much larger than real hours. Use
    # the continuous merged file instead, same one used to build it.)
    weather_merged_path = (
        f"/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/"
        f"UCSC_CarbonCast_API/CarbonCast/data/{region}/{region}_weather_merged.csv"
    )

    weather_rows = None
    if os.path.exists(weather_merged_path):
        wdf = pd.read_csv(weather_merged_path)
        date_col = "datetime" if "datetime" in wdf.columns else wdf.columns[0]
        wdf[date_col] = pd.to_datetime(wdf[date_col], errors="coerce")
        wdf = wdf.dropna(subset=[date_col]).drop_duplicates(subset=[date_col])
        weather_rows = len(wdf)
    else:
        logger.warning(
            f"[{region}] Weather merged file not found at {weather_merged_path} — "
            f"cannot cross-check against electricity row count. Using electricity count only."
        )

    if weather_rows is not None:
        limiter = min(electricity_rows, weather_rows)
        if limiter < electricity_rows:
            logger.warning(
                f"[{region}] Electricity has {electricity_rows} rows but weather only "
                f"has {weather_rows} — capping DATASET_LIMITER to {limiter} to avoid "
                f"the manipulateTrainingDataShape mismatch crash."
            )
    else:
        limiter = electricity_rows

    ft_path = f"{CARBONCAST_SRC_DIR}/firstTierConfig.json"

    with open(ft_path) as f:
        ft = json.load(f)

    ft["TRAIN_TEST_PERIOD"]["PERIOD_0"]["DATASET_LIMITER"] = limiter

    with open(ft_path, "w") as f:
        json.dump(ft, f, indent=4)

    logger.info(
        f"[{region}] DATASET_LIMITER set to {limiter} "
        f"(electricity={electricity_rows}, weather={weather_rows})"
    )

    logger.info(
        f"[{region}] Grid range: "
        f"{df['UTC time'].min()} -> {df['UTC time'].max()}"
    )

def set_region_config(region):
    ft_path = f"{CARBONCAST_SRC_DIR}/firstTierConfig.json"
    with open(ft_path) as f:
        ft = json.load(f)
    ft["REGION"] = [region]
    ft["NUM_VAL_DAYS"] = 15
    if "TRAIN_TEST_PERIOD" not in ft:
        ft["TRAIN_TEST_PERIOD"] = {}
    if "PERIOD_0" not in ft["TRAIN_TEST_PERIOD"]:
        ft["TRAIN_TEST_PERIOD"]["PERIOD_0"] = {}
    ft["TRAIN_TEST_PERIOD"]["PERIOD_0"]["NUM_TEST_DAYS"] = 524
    ft["TRAIN_TEST_PERIOD"]["PERIOD_0"]["OUT_FILE_SUFFIX"] = "current"
    with open(ft_path, "w") as f:
        json.dump(ft, f, indent=4)

    st_path = f"{CARBONCAST_SRC_DIR}/secondTierConfig.json"
    with open(st_path) as f:
        st = json.load(f)
    st["REGION_DIRECT"] = [region]
    st["REGION_LIFECYCLE"] = [region]
    with open(st_path, "w") as f:
        json.dump(st, f, indent=4)


def train_tier1(region):
    run([PYTHON_BIN, "firstTierForecasts.py", f"{CARBONCAST_SRC_DIR}/firstTierConfig.json"], cwd=CARBONCAST_SRC_DIR)


def build_tier2_input(region):
    run([PYTHON_BIN, "build_tier2_forecast_input.py", region,
         f"../data/{region}/{region}_weather_merged.csv", "168", "0"], cwd=CARBONCAST_SRC_DIR)


def align_emissions(region):
    run([PYTHON_BIN, "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src/CarbonCastAPI/CarbonCastRESTAPI/services/weather_fetch/align_emissions_to_forecast.py", "--region", region], cwd=CARBONCAST_SRC_DIR)


def update_tier2_split(region):
    import pandas as pd
    fcst = pd.read_csv(
        f"/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/data/{region}/{region}_168hr_forecasts_DA_continuous.csv",
        parse_dates=["datetime"])
    total_hours = fcst["datetime"].nunique()
    total_blocks = total_hours // 168
    test_blocks = max(1, int(total_blocks * 0.15))
    val_blocks = max(1, int(total_blocks * 0.075))

    st_path = f"{CARBONCAST_SRC_DIR}/secondTierConfig.json"
    with open(st_path) as f:
        st = json.load(f)
    st["NUM_TEST_DAYS"] = test_blocks
    st["NUM_VAL_DAYS"] = val_blocks
    st["REGION_DIRECT"] = [region]
    st["REGION_LIFECYCLE"] = [region]
    with open(st_path, "w") as f:
        json.dump(st, f, indent=4)

    logger.info(f"[{region}] tier2 split: total_blocks={total_blocks}, test={test_blocks}, val={val_blocks}")


def train_tier2(region):
    st_path = f"{CARBONCAST_SRC_DIR}/secondTierConfig.json"
    with open(st_path) as f:
        st = json.load(f)
    st["REGION_DIRECT"] = [region]
    st["REGION_LIFECYCLE"] = [region]
    with open(st_path, "w") as f:
        json.dump(st, f, indent=4)

    run([PYTHON_BIN, "secondTierForecasts.py", f"{CARBONCAST_SRC_DIR}/secondTierConfig.json", "-d"], cwd=CARBONCAST_SRC_DIR)
    run([PYTHON_BIN, "secondTierForecasts.py", f"{CARBONCAST_SRC_DIR}/secondTierConfig.json", "-l"], cwd=CARBONCAST_SRC_DIR)


def run_region(region):
    logger.info(f"\n{'='*20} {region} {'='*20}")

    # WEATHER
    ensure_rda_processed(region)
    concat_weather(region)
    prep_weather_for_training(region)

    # GRID DATA — DB ONLY, NO API BACKFILL
    prep_grid_data(region)

    # CONFIGURATION
    compute_dataset_limiter(region)
    set_region_config(region)

    # TIER 1
    train_tier1(region)

    # TIER 2 PREPARATION
    build_tier2_input(region)
    align_emissions(region)
    update_tier2_split(region)

    # TIER 2
    train_tier2(region)

    logger.info(f"##### {region} COMPLETE #####")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--regions", nargs="+", required=True)
    args = parser.parse_args()

    results = {}
    for region in args.regions:
        try:
            run_region(region)
            results[region] = "SUCCESS"
        except Exception as exc:
            logger.error(f"[{region}] FAILED: {exc}")
            logger.error(traceback.format_exc())
            results[region] = f"FAILED: {exc}"

    logger.info(f"\n{'='*20} BATCH SUMMARY {'='*20}")
    for region, status in results.items():
        logger.info(f"{region}: {status}")


if __name__ == "__main__":
    main()