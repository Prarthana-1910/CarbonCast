#!/usr/bin/env python3
"""
run_full_retraining_batch.py

Full retraining pipeline for a list of regions (RDA already processed),
each isolated so one region's failure doesn't stop the batch:

  1. Concatenate old archive + new RDA archive -> final_training_data/
  2. Expand/merge/reshape combined weather -> {region}_weather_forecast_168.csv
  3. Backfill grid data (EIA or ENTSO-E, region-aware) + export training CSVs
  4. Train tier 1 (small train %, large test % -- feeds tier 2)
  5. Build tier 2 input from tier 1's test-period output
  6. Align emissions to tier 2 input (last step before training)
  7. Train tier 2 direct + lifecycle

Usage:
    python3 run_full_retraining_batch.py --regions AT AZPS BG BPAT CH CISO CZ DE DK DOPD EE FI FPC FR GCPD GR HR HU IE IPCO IT LDWP
"""
import argparse
import subprocess
import logging
import traceback
import os
import shutil
import json

logger = logging.getLogger("run_full_retraining_batch")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CARBONCAST_SRC = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src"
AUTOMATION_TOOL_SRC = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_OSRE_CC_automation_tool/CarbonCast/processed_data"
BUILD_FINAL_DATASET_SCRIPT = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_OSRE_CC_automation_tool/CarbonCast/build_final_training_dataset.py"
PYTHON_BIN = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/.venv/bin/python"

US_REGIONS = {
    'AZPS', 'BPAT', 'CISO', 'DOPD', 'FPC', 'GCPD', 'IPCO', 'LDWP',
}
# everything else in the target list is EU -> ENTSO-E


def run(cmd, cwd=None):
    logger.info(f"RUN: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def concat_weather_archives(region):
    run([PYTHON_BIN, BUILD_FINAL_DATASET_SCRIPT, "--region", region])


def prep_weather_for_training(region):
    combined_dir = f"/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_OSRE_CC_automation_tool/CarbonCast/final_training_data/{region}"
    staging_dir = f"{combined_dir}/hourly_staging"
    training_data_dir = f"/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/data/{region}"

    os.makedirs(staging_dir, exist_ok=True)
    os.makedirs(training_data_dir, exist_ok=True)

    run([PYTHON_BIN, "expand_weather_to_hourly.py",
         f"{combined_dir}/{region}_AVG_TEMP.csv", f"{staging_dir}/{region}_temp_hourly.csv", "temp", "fcst"],
        cwd=AUTOMATION_TOOL_SRC)
    run([PYTHON_BIN, "expand_weather_to_hourly.py",
         f"{combined_dir}/{region}_AVG_DPT.csv", f"{staging_dir}/{region}_dpt_hourly.csv", "dpt", "fcst"],
        cwd=AUTOMATION_TOOL_SRC)
    run([PYTHON_BIN, "expand_weather_to_hourly.py",
         f"{combined_dir}/{region}_AVG_WIND_SPEED.csv", f"{staging_dir}/{region}_wind_hourly.csv", "wind_speed", "fcst"],
        cwd=AUTOMATION_TOOL_SRC)
    run([PYTHON_BIN, "expand_weather_to_hourly.py",
         f"{combined_dir}/{region}_AVG_DSWRF.csv", f"{staging_dir}/{region}_dswrf_hourly.csv", "dswrf", "avg"],
        cwd=AUTOMATION_TOOL_SRC)
    run([PYTHON_BIN, "expand_weather_to_hourly.py",
         f"{combined_dir}/{region}_AVG_PCP.csv", f"{staging_dir}/{region}_precip_hourly.csv", "precip", "acc"],
        cwd=AUTOMATION_TOOL_SRC)

    merged = f"{staging_dir}/{region}_weather_merged.csv"
    run([PYTHON_BIN, "merge_hourly_weather.py", region, merged,
         f"{staging_dir}/{region}_temp_hourly.csv",
         f"{staging_dir}/{region}_dpt_hourly.csv",
         f"{staging_dir}/{region}_dswrf_hourly.csv",
         f"{staging_dir}/{region}_wind_hourly.csv",
         f"{staging_dir}/{region}_precip_hourly.csv"],
        cwd=AUTOMATION_TOOL_SRC)

    out_path = f"{training_data_dir}/{region}_weather_forecast_168.csv"
    run([PYTHON_BIN, "reshape_weather_to_dayblocks.py", merged, out_path, "168"], cwd=AUTOMATION_TOOL_SRC)

    shutil.copy(merged, f"{training_data_dir}/{region}_weather_merged.csv")

def compute_dataset_limiter(region):
    import pandas as pd
    path = f"{CARBONCAST_SRC}/../data/{region}/fuel_forecast/{region}_nat_gas_clean.csv"
    df = pd.read_csv(path)
    limiter = len(df)

    ft_path = f"{CARBONCAST_SRC}/firstTierConfig.json"
    with open(ft_path) as f:
        ft = json.load(f)
    ft["TRAIN_TEST_PERIOD"]["PERIOD_0"]["DATASET_LIMITER"] = limiter
    with open(ft_path, "w") as f:
        json.dump(ft, f, indent=4)
    logger.info(f"[{region}] DATASET_LIMITER set to {limiter}")


def prep_grid_data(region):
    manage_py_dir = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src/CarbonCastAPI"
    cmd = [
        PYTHON_BIN, "manage.py", "shell", "-c",
        f"from CarbonCastRESTAPI.services.weather_fetch.prepare_grid_data_for_retraining import run; "
        f"run('{region}', days_back=624)"
    ]
    run(cmd, cwd=manage_py_dir)


def set_region_config(region):
    ft_path = f"{CARBONCAST_SRC}/firstTierConfig.json"
    with open(ft_path) as f:
        ft = json.load(f)
    ft["REGION"] = [region]
    ft["TRAIN_TEST_PERIOD"]["PERIOD_0"]["NUM_TEST_DAYS"] = 524
    ft["NUM_VAL_DAYS"] = 15
    with open(ft_path, "w") as f:
        json.dump(ft, f, indent=4)

    st_path = f"{CARBONCAST_SRC}/secondTierConfig.json"
    with open(st_path) as f:
        st = json.load(f)
    st["REGION_DIRECT"] = [region]
    st["REGION_LIFECYCLE"] = [region]
    with open(st_path, "w") as f:
        json.dump(st, f, indent=4)


def train_tier1(region):
    run([PYTHON_BIN, "firstTierForecasts.py", f"{CARBONCAST_SRC}/firstTierConfig.json"], cwd=CARBONCAST_SRC)


def build_tier2_input(region):
    run([PYTHON_BIN, "build_tier2_forecast_input.py", region,
         f"../data/{region}/{region}_weather_merged.csv", "168", "0"], cwd=CARBONCAST_SRC)


def align_emissions(region):
    run([PYTHON_BIN, "align_emissions_to_forecast.py", "--region", region], cwd=CARBONCAST_SRC)


def update_tier2_split(region):
    import pandas as pd
    fcst = pd.read_csv(f"{CARBONCAST_SRC}/../data/{region}/{region}_168hr_forecasts_DA_continuous.csv",
                        parse_dates=["datetime"])
    total_hours = fcst["datetime"].nunique()
    total_blocks = total_hours // 168
    test_blocks = max(1, int(total_blocks * 0.15))
    val_blocks = max(1, int(total_blocks * 0.075))

    st_path = f"{CARBONCAST_SRC}/secondTierConfig.json"
    with open(st_path) as f:
        st = json.load(f)
    st["NUM_TEST_DAYS"] = test_blocks
    st["NUM_VAL_DAYS"] = val_blocks
    with open(st_path, "w") as f:
        json.dump(st, f, indent=4)

    logger.info(f"[{region}] tier2 split: total_blocks={total_blocks}, test={test_blocks}, val={val_blocks}")


def train_tier2(region):
    run([PYTHON_BIN, "secondTierForecasts.py", f"{CARBONCAST_SRC}/secondTierConfig.json", "-d"], cwd=CARBONCAST_SRC)
    run([PYTHON_BIN, "secondTierForecasts.py", f"{CARBONCAST_SRC}/secondTierConfig.json", "-l"], cwd=CARBONCAST_SRC)


def run_region(region):
    logger.info(f"\n{'='*20} {region} {'='*20}")
    concat_weather_archives(region)
    prep_weather_for_training(region)
    prep_grid_data(region)
    compute_dataset_limiter(region)   # <- add this
    set_region_config(region)
    train_tier1(region)
    build_tier2_input(region)
    align_emissions(region)   # MUST come right before tier 2 training
    update_tier2_split(region)
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