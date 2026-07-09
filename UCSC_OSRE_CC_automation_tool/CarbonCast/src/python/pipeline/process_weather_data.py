"""
Script 3: Process Weather Data (tar → grib2 → CSV)
Called automatically by Script 2 when all 4 vars for a region are downloaded.
Can also be run manually: python process_weather_data.py --region CISO
"""

import os
import sys
import csv
import glob
import math
import json
import tarfile
import logging
import argparse
import subprocess
from calendar import monthrange

import numpy as np
import pandas as pd

# ── CONFIG ────────────────────────────────────────────────────────────────────
BASE_DIR       = os.path.expanduser("~/CarbonCast_spring26/UCSC_OSRE_CC_automation_tool/CarbonCast")
CARBONCAST_SRC = os.path.expanduser("~/CarbonCast_spring26/UCSC_CarbonCast_API/CarbonCast/src")
DOWNLOAD_DIR   = os.path.join(BASE_DIR, "downloaded_files")
PROCESSED_DIR  = os.path.join(BASE_DIR, "processed_data")
LOG_FILE       = os.path.join(BASE_DIR, "logs", "process_weather.log")
VENV_PYTHON    = os.path.join(BASE_DIR, "src/python/venv/bin/python")
STATE_FILE     = os.path.join(BASE_DIR, "pipeline_state.json")
WGRIB2         = "/usr/local/bin/wgrib2"
# ─────────────────────────────────────────────────────────────────────────────

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

VARIABLES = ["temp", "wind", "dswrf", "rain"]

FILE_PREFIX = "gfs.0p25."
HOUR        = ["00"]
YEARS       = [2024, 2025, 2026]

FCST = ["000", "003", "006", "009", "012", "015", "018", "021", "024",
        "027", "030", "033", "036", "039", "042", "045", "048",
        "051", "054", "057", "060", "063", "066", "069", "072",
        "075", "078", "081", "084", "087", "090", "093", "096"]

FCST_AVG_ACC = ["003", "006", "009", "012", "015", "018", "021", "024",
                "027", "030", "033", "036", "039", "042", "045", "048",
                "051", "054", "057", "060", "063", "066", "069", "072",
                "075", "078", "081", "084", "087", "090", "093", "096"]

HEADER = ["startDate", "endDate", "param", "level", "longitude", "latitude", "value"]

CSV_FILE_FIELDS_FCST = ["datetime", "param", "level", "latitude", "longitude", "Analysis",
        "3 hr fcst", "6 hr fcst", "9 hr fcst", "12 hr fcst", "15 hr fcst", "18 hr fcst",
        "21 hr fcst", "24 hr fcst", "27 hr fcst", "30 hr fcst", "33 hr fcst",
        "36 hr fcst", "39 hr fcst", "42 hr fcst", "45 hr fcst", "48 hr fcst",
        "51 hr fcst", "54 hr fcst", "57 hr fcst", "60 hr fcst", "63 hr fcst",
        "66 hr fcst", "69 hr fcst", "72 hr fcst", "75 hr fcst", "78 hr fcst",
        "81 hr fcst", "84 hr fcst", "87 hr fcst", "90 hr fcst", "93 hr fcst", "96 hr fcst"]

CSV_FILE_FIELDS_AVG = ["datetime", "param", "level", "latitude", "longitude",
        "0-3 hr avg", "0-6 hr avg", "6-9 hr avg", "6-12 hr avg", "12-15 hr avg",
        "12-18 hr avg", "18-21 hr avg", "18-24 hr avg", "24-27 hr avg", "24-30 hr avg",
        "30-33 hr avg", "30-36 hr avg", "36-39 hr avg", "36-42 hr avg", "42-45 hr avg",
        "42-48 hr avg", "48-51 hr avg", "48-54 hr avg", "54-57 hr avg", "54-60 hr avg",
        "60-63 hr avg", "60-66 hr avg", "66-69 hr avg", "66-72 hr avg", "72-75 hr avg",
        "72-78 hr avg", "78-81 hr avg", "78-84 hr avg", "84-87 hr avg", "84-90 hr avg",
        "90-93 hr avg", "90-96 hr avg"]

CSV_FILE_FIELDS_ACC = ["datetime", "param", "level", "latitude", "longitude",
        "0-3 hr acc", "0-6 hr acc", "6-9 hr acc", "6-12 hr acc", "12-15 hr acc",
        "12-18 hr acc", "18-21 hr acc", "18-24 hr acc", "24-27 hr acc", "24-30 hr acc",
        "30-33 hr acc", "30-36 hr acc", "36-39 hr acc", "36-42 hr acc", "42-45 hr acc",
        "42-48 hr acc", "48-51 hr acc", "48-54 hr acc", "54-57 hr acc", "54-60 hr acc",
        "60-63 hr acc", "60-66 hr acc", "66-69 hr acc", "66-72 hr acc", "72-75 hr acc",
        "72-78 hr acc", "78-81 hr acc", "78-84 hr acc", "84-87 hr acc", "84-90 hr acc",
        "90-93 hr acc", "90-96 hr acc"]

UGRD_VGRD_SEPARATOR = {"CISO": 1886, "PJM": 2556, "SE": 2296, "DK-DK2": 221,
                        "ERCO": 2116, "ISNE": 1056, "GB": 1978, "DE": 1254,
                        "PL": 984, "AUS_NSW": 64, "AUS_QLD": 5695, "AUS_SA": 2809}

TMP_DPT_SEPARATOR = {"CISO": 1886, "PJM": 2556, "SE": 2296, "DK-DK2": 221,
                      "ERCO": 2116, "ISNE": 1056, "GB": 1978, "DE": 1254,
                      "PL": 984, "AUS_NSW": 64, "AUS_QLD": 5695, "AUS_SA": 2809}


# ── GEOMETRY HELPERS (from dataCollectionScript.py) ──────────────────────────

def earth_radius(lat):
    from numpy import deg2rad
    a  = 6378137
    b  = 6356752.3142
    e2 = 1 - (b**2 / a**2)
    lat    = deg2rad(lat)
    lat_gc = np.arctan((1 - e2) * np.tan(lat))
    r = ((a * (1 - e2)**0.5) / (1 - (e2 * np.cos(lat_gc)**2))**0.5)
    return r


def area_grid(lat, lon):
    from numpy import meshgrid, deg2rad, gradient, cos
    xlon, ylat = meshgrid(lon, lat)
    R    = earth_radius(ylat)
    dlat = deg2rad(gradient(ylat, axis=0))
    dlon = deg2rad(gradient(xlon, axis=1))
    dy   = dlat * R
    dx   = dlon * R * cos(deg2rad(ylat))
    return dy * dx


# ── FILE LIST (skip missing files cleanly, no fallback duplicates) ────────────

def get_file_list(file_dir, fcst_col):
    file_list = []
    skipped   = 0
    for year in YEARS:
        for month in range(1, 13):
            for day in range(1, monthrange(year, month)[1] + 1):
                cur_date  = str(year) + f"{month:02d}" + f"{day:02d}"
                base_name = FILE_PREFIX + cur_date
                for hr in HOUR:
                    for fcst in fcst_col:
                        fname = base_name + str(hr) + ".f" + str(fcst) + ".grib2"
                        fpath = os.path.join(file_dir, fname)
                        if os.path.exists(fpath):
                            file_list.append(fpath)
                        else:
                            skipped += 1
    log.info(f"Found {len(file_list)} grib2 files ({skipped} skipped — outside date range)")
    return file_list


# ── PROCESSING FUNCTIONS (inlined from dataCollectionScript.py) ───────────────

def get_weather_data(file_list, csv_fields, out_file, fcst_col, weather_variable, region):
    with open(out_file, 'w') as f:
        csv.writer(f).writerow(csv_fields)

    file_idx = 0
    rows     = []
    tmp_csv  = os.path.join(os.path.dirname(out_file), "tmp.csv")

    while file_idx < len(file_list):
        row              = None
        lat              = None
        lon              = None
        grid_cell_area   = None
        total_area       = None

        for i in range(len(fcst_col)):
            if file_idx >= len(file_list):
                break
            ret = subprocess.call(f"{WGRIB2} {file_list[file_idx]} -csv {tmp_csv}", shell=True)
            file_idx += 1
            if ret == 0:
                dataset = pd.read_csv(tmp_csv, names=HEADER)
                if weather_variable == "TEMP":
                    dataset = dataset[:TMP_DPT_SEPARATOR[region]]
                elif weather_variable == "DPT":
                    dataset = dataset[TMP_DPT_SEPARATOR[region]:]
                if i == 0:
                    lat            = np.unique(dataset["latitude"].values)
                    lon            = np.unique(dataset["longitude"].values)
                    grid_cell_area = area_grid(lat, lon)
                    total_area     = np.sum(grid_cell_area)
                if row is None:
                    row = [dataset["startDate"].iloc[0], dataset["param"].iloc[0],
                           dataset["level"].iloc[0], dataset["latitude"].iloc[0],
                           dataset["longitude"].iloc[0]]
                value         = np.reshape(dataset["value"].values, (len(lat), len(lon)))
                weighted_mean = np.sum((value * grid_cell_area) / total_area)
                row.append(weighted_mean)
                os.remove(tmp_csv)
            else:
                log.error(f"wgrib2 failed on {file_list[file_idx - 1]}")
        rows.append(row)

    with open(out_file, 'a') as f:
        csv.writer(f).writerows(rows)


def get_wind_data(file_list, csv_fields, out_file, region):
    with open(out_file, 'w') as f:
        csv.writer(f).writerow(csv_fields)

    file_idx       = 0
    rows           = []
    tmp_csv        = os.path.join(os.path.dirname(out_file), "tmp.csv")

    while file_idx < len(file_list):
        row            = None
        lat            = None
        lon            = None
        grid_cell_area = None
        total_area     = None

        for i in range(len(FCST)):
            if file_idx >= len(file_list):
                break
            ret = subprocess.call(f"{WGRIB2} {file_list[file_idx]} -csv {tmp_csv}", shell=True)
            file_idx += 1
            if ret == 0:
                dataset  = pd.read_csv(tmp_csv, names=HEADER)
                vdataset = dataset[UGRD_VGRD_SEPARATOR[region]:]
                udataset = dataset[:UGRD_VGRD_SEPARATOR[region]]
                if i == 0:
                    lat            = np.unique(dataset["latitude"].values)
                    lon            = np.unique(dataset["longitude"].values)
                    grid_cell_area = area_grid(lat, lon)
                    total_area     = np.sum(grid_cell_area)
                if row is None:
                    row = [dataset["startDate"].iloc[0], dataset["param"].iloc[0],
                           dataset["level"].iloc[0], dataset["latitude"].iloc[0],
                           dataset["longitude"].iloc[0]]
                wind_speed    = (udataset["value"].values**2 + vdataset["value"].values**2)**0.5
                value         = np.reshape(wind_speed, (len(lat), len(lon)))
                weighted_mean = np.sum((value * grid_cell_area) / total_area)
                row.append(weighted_mean)
                os.remove(tmp_csv)
            else:
                log.error(f"wgrib2 failed on {file_list[file_idx - 1]}")
        rows.append(row)

    with open(out_file, 'a') as f:
        csv.writer(f).writerows(rows)


# ── PIPELINE STEPS ────────────────────────────────────────────────────────────

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
    """Process all 4 weather variables for a region and write CSVs."""
    out_dir = os.path.join(PROCESSED_DIR, region)
    os.makedirs(out_dir, exist_ok=True)

    var_dirs = {
        "ugrd_vgrd": os.path.join(DOWNLOAD_DIR, region, "wind")  + os.sep,
        "tmp_dpt":   os.path.join(DOWNLOAD_DIR, region, "temp")  + os.sep,
        "dswrf":     os.path.join(DOWNLOAD_DIR, region, "dswrf") + os.sep,
        "apcp":      os.path.join(DOWNLOAD_DIR, region, "rain")  + os.sep,
    }

    tasks = [
        ("WIND",  var_dirs["ugrd_vgrd"], FCST,         CSV_FILE_FIELDS_FCST, os.path.join(out_dir, f"{region}_AVG_WIND_SPEED.csv")),
        ("TEMP",  var_dirs["tmp_dpt"],   FCST,         CSV_FILE_FIELDS_FCST, os.path.join(out_dir, f"{region}_AVG_TEMP.csv")),
        ("DPT",   var_dirs["tmp_dpt"],   FCST,         CSV_FILE_FIELDS_FCST, os.path.join(out_dir, f"{region}_AVG_DPT.csv")),
        ("DSWRF", var_dirs["dswrf"],     FCST_AVG_ACC, CSV_FILE_FIELDS_AVG,  os.path.join(out_dir, f"{region}_AVG_DSWRF.csv")),
        ("PCP",   var_dirs["apcp"],      FCST_AVG_ACC, CSV_FILE_FIELDS_ACC,  os.path.join(out_dir, f"{region}_AVG_PCP.csv")),
    ]

    for var_type, file_dir, fcst_col, csv_fields, out_file in tasks:
        log.info(f"Processing {var_type} → {out_file}")
        file_list = get_file_list(file_dir, fcst_col)
        if not file_list:
            log.warning(f"No grib2 files found for {var_type} in {file_dir}, skipping")
            continue
        if var_type == "WIND":
            get_wind_data(file_list, csv_fields, out_file, region)
        else:
            get_weather_data(file_list, csv_fields, out_file, fcst_col, var_type, region)
        log.info(f"✅ {var_type} done → {out_file}")

    return True


def run_separate_by_region(region):
    """Run separateWeatherByRegion.py to aggregate grid points → region CSV."""
    script  = os.path.join(CARBONCAST_SRC, "weather", "separateWeatherByRegion.py")
    out_dir = os.path.join(PROCESSED_DIR, region)

    result = subprocess.run(
        [VENV_PYTHON, script, "--region", region,
         "--input_dir", out_dir, "--output_dir", out_dir],
        capture_output=True, text=True,
        cwd=os.path.join(CARBONCAST_SRC, "weather")
    )
    if result.returncode != 0:
        log.error(f"separateWeatherByRegion failed for {region}:\n{result.stderr}")
        return False
    log.info(f"separateWeatherByRegion completed for {region}")
    return True


def mark_processed(region):
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
    script = os.path.join(BASE_DIR, "src/python/pipeline/train_optimize_test.py")
    log.info(f"Triggering training for {region}")
    subprocess.Popen([VENV_PYTHON, script, "--region", region])


def main(region):
    log.info(f"=== Processing weather data for {region} ===")

    log.info(f"Step 1/3: Extracting tar files for {region}")
    extract_tars(region)

    log.info(f"Step 2/3: Running data collection for {region}")
    ok = run_data_collection(region)
    if not ok:
        log.error(f"Processing failed at data collection for {region}")
        sys.exit(1)
    
    mark_processed(region)
    log.info(f"✅ Processing complete for {region}")
    trigger_training(region)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", required=True, help="Region code e.g. CISO")
    args = parser.parse_args()
    main(args.region)