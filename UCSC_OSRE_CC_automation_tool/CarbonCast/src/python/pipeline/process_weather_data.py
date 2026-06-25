"""
Script 3: Process Weather Data (tar → grib2 → CSV)
Called automatically by Script 2 when all 4 vars for a region are downloaded.
Can also be run manually: python 3_process_weather_data.py --region CISO
"""

import os
import sys
import glob
import tarfile
import logging
import argparse
import subprocess

# ── CONFIG ────────────────────────────────────────────────────────────────────
BASE_DIR         = os.path.expanduser("~/CarbonCast_spring26/UCSC_OSRE_CC_automation_tool/CarbonCast")
CARBONCAST_SRC   = os.path.expanduser("~/CarbonCast_spring26/UCSC_CarbonCast_API/CarbonCast/src")
DOWNLOAD_DIR     = os.path.join(BASE_DIR, "downloaded_files")
PROCESSED_DIR    = os.path.join(BASE_DIR, "processed_data")   # CSVs go here
LOG_FILE         = os.path.join(BASE_DIR, "logs", "process_weather.log")
VENV_PYTHON      = os.path.join(BASE_DIR, "src/python/venv/bin/python")
WGRIB2           = os.path.join(CARBONCAST_SRC, "grib2/wgrib2/wgrib2")

STATE_FILE       = os.path.join(BASE_DIR, "pipeline_state.json")
# ─────────────────────────────────────────────────────────────────────────────

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

VARIABLES = ["temp", "wind", "dswrf", "rain"]


def extract_tars(region):
    """Extract all .tar files for a region into their variable directories."""
    for var in VARIABLES:
        var_dir = os.path.join(DOWNLOAD_DIR, region, var)
        if not os.path.exists(var_dir):
            log.warning(f"Missing directory: {var_dir}")
            continue
        for tar_path in glob.glob(os.path.join(var_dir, "*.tar")):
            log.info(f"Extracting {tar_path}")
            with tarfile.open(tar_path) as tf:
                tf.extractall(var_dir)
            log.info(f"Extracted to {var_dir}")


def run_data_collection(region):
    """
    Invoke the existing dataCollectionScript.py for this region.
    The script reads grib2 files and produces CSVs.
    We patch ISO_LIST and FILE_DIR via env vars or by calling it as subprocess.
    """
    script = os.path.join(CARBONCAST_SRC, "weather", "dataCollectionScript.py")
    out_dir = os.path.join(PROCESSED_DIR, region)
    os.makedirs(out_dir, exist_ok=True)

    log.info(f"Running dataCollectionScript for {region}")
    env = os.environ.copy()
    env["CARBONCAST_REGION"] = region
    env["CARBONCAST_INPUT_DIR"] = os.path.join(DOWNLOAD_DIR, region)
    env["CARBONCAST_OUTPUT_DIR"] = out_dir

    result = subprocess.run(
        [VENV_PYTHON, script, "--region", region,
         "--input_dir", os.path.join(DOWNLOAD_DIR, region),
         "--output_dir", out_dir],
        capture_output=True, text=True, env=env,
        cwd=os.path.join(CARBONCAST_SRC, "weather")
    )
    if result.returncode != 0:
        log.error(f"dataCollectionScript failed for {region}:\n{result.stderr}")
        return False
    log.info(f"dataCollectionScript completed for {region}")
    log.debug(result.stdout)
    return True


def run_separate_by_region(region):
    """Run separateWeatherByRegion.py to aggregate grid points → region CSV."""
    script = os.path.join(CARBONCAST_SRC, "weather", "separateWeatherByRegion.py")
    out_dir = os.path.join(PROCESSED_DIR, region)

    result = subprocess.run(
        [VENV_PYTHON, script, "--region", region,
         "--input_dir", os.path.join(PROCESSED_DIR, region),
         "--output_dir", out_dir],
        capture_output=True, text=True,
        cwd=os.path.join(CARBONCAST_SRC, "weather")
    )
    if result.returncode != 0:
        log.error(f"separateWeatherByRegion failed for {region}:\n{result.stderr}")
        return False
    log.info(f"separateWeatherByRegion completed for {region}")
    return True


def mark_processed(region):
    import json
    if not os.path.exists(STATE_FILE):
        return
    with open(STATE_FILE) as f:
        state = json.load(f)
    if "processed" not in state:
        state["processed"] = []
    if region not in state["processed"]:
        state["processed"].append(region)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def trigger_training(region):
    script = os.path.join(BASE_DIR, "src/python/pipeline/4_train_optimize_test.py")
    log.info(f"🔄 Triggering training for {region}")
    subprocess.Popen([VENV_PYTHON, script, "--region", region])


def main(region):
    log.info(f"=== Processing weather data for {region} ===")

    log.info(f"Step 1/3: Extracting tar files for {region}")
    extract_tars(region)

    log.info(f"Step 2/3: Running dataCollectionScript for {region}")
    ok = run_data_collection(region)
    if not ok:
        log.error(f"Processing failed at dataCollectionScript for {region}")
        sys.exit(1)

    log.info(f"Step 3/3: Running separateWeatherByRegion for {region}")
    ok = run_separate_by_region(region)
    if not ok:
        log.error(f"Processing failed at separateWeatherByRegion for {region}")
        sys.exit(1)

    mark_processed(region)
    log.info(f"✅ Processing complete for {region}")
    trigger_training(region)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", required=True, help="Region code e.g. CISO")
    args = parser.parse_args()
    main(args.region)
