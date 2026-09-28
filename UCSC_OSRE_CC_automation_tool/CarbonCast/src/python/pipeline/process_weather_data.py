"""
Script 3: Process Weather Data (tar → grib2 → CSV)
Called automatically by Script 2 when all 4 vars for a region are downloaded.
Can also be run manually: python process_weather_data.py --region CISO
"""

import os
import shutil
import sys
import csv
import glob
import math
import json
import tarfile
import logging
import argparse
import re
import subprocess
from calendar import monthrange

import numpy as np
import pandas as pd

# ── CONFIG ────────────────────────────────────────────────────────────────────
BASE_DIR       = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_OSRE_CC_automation_tool/CarbonCast"
CARBONCAST_SRC = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src"
DOWNLOAD_DIR   = os.path.join(BASE_DIR, "retraining_archive")
PROCESSED_DIR = os.path.join(BASE_DIR, "retraining_archive_processed")
LOG_FILE       = os.path.join(BASE_DIR, "logs", "process_weather.log")
VENV_PYTHON    = "/Users/prarthanapatil/Documents/EnergyAPI11/src/python/venv/bin/python3"
STATE_FILE     = os.path.join(BASE_DIR, "pipeline_state.json")
WGRIB2         = "/Users/prarthanapatil/.local/share/mamba/bin/wgrib2"
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
YEARS       = [2026]

FCST = [f"{h:03d}" for h in range(0, 169, 3)]

FCST_AVG_ACC = [f"{h:03d}" for h in range(3, 169, 3)]

HEADER = ["startDate", "endDate", "param", "level", "longitude", "latitude", "value"]

CSV_FILE_FIELDS_FCST = ["datetime", "param", "level", "latitude", "longitude", "Analysis"] + [f"{h} hr fcst" for h in range(3, 169, 3)]

CSV_FILE_FIELDS_AVG = ["datetime", "param", "level", "latitude", "longitude"]
for s in range(0, 168, 6):
    CSV_FILE_FIELDS_AVG.append(f"{s}-{s+3} hr avg")
    CSV_FILE_FIELDS_AVG.append(f"{s}-{s+6} hr avg")

CSV_FILE_FIELDS_ACC = ["datetime", "param", "level", "latitude", "longitude"]
for s in range(0, 168, 6):
    CSV_FILE_FIELDS_ACC.append(f"{s}-{s+3} hr acc")
    CSV_FILE_FIELDS_ACC.append(f"{s}-{s+6} hr acc")

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

import re

def _parse_date_from_filename(filepath):
    """Extract YYYYMMDD from a grib2 filename like gfs.0p25.2025060100.f003.grib2"""
    m = re.search(r"gfs\.0p25\.(\d{8})\d{2}\.f\d{3}\.grib2", os.path.basename(filepath))
    return m.group(1) if m else None


def _group_files_by_date(file_list):
    """Group a flat file_list into {date: [files...]} instead of relying on
    positional slicing. Fixes misalignment when any date has missing files."""
    grouped = {}
    for f in file_list:
        date = _parse_date_from_filename(f)
        if date is None:
            log.error(f"Could not parse date from filename, skipping: {f}")
            continue
        grouped.setdefault(date, []).append(f)
    return grouped


def get_weather_data(file_list, csv_fields, out_file, fcst_col, weather_variable, region):
    with open(out_file, 'w') as f:
        csv.writer(f).writerow(csv_fields)

    rows = []
    tmp_csv = os.path.join(os.path.dirname(out_file), "tmp.csv")
    paired_var = weather_variable in ("TEMP", "DPT")

    grouped = _group_files_by_date(file_list)

    for date in sorted(grouped.keys()):
        date_files = sorted(grouped[date])  # sorted so forecast hours are in order
        row = None
        lat = None
        lon = None
        grid_cell_area = None
        total_area = None
        grid_size = None
        row_failed = False

        # Only process this date if it has the FULL expected set of files
        if len(date_files) != len(fcst_col):
            log.warning(
                f"Skipping date {date} for {weather_variable}: "
                f"expected {len(fcst_col)} files, found {len(date_files)}."
            )
            continue

        for i, cur_file in enumerate(date_files):
            ret = subprocess.call(f"{WGRIB2} {cur_file} -csv {tmp_csv}", shell=True)

            if ret != 0:
                log.error(f"wgrib2 FAILED on file: {cur_file}")
                row_failed = True
                continue

            dataset = pd.read_csv(tmp_csv, names=HEADER)

            if i == 0:
                lat = np.unique(dataset["latitude"].values)
                lon = np.unique(dataset["longitude"].values)
                grid_size = len(lat) * len(lon)
                grid_cell_area = area_grid(lat, lon)
                total_area = np.sum(grid_cell_area)

            expected_rows = grid_size * 2 if paired_var else grid_size
            if len(dataset) != expected_rows:
                log.error(
                    f"BAD FILE (row count mismatch): {cur_file} — "
                    f"expected {expected_rows} rows, got {len(dataset)}. "
                    f"Skipping this entire row/date."
                )
                row_failed = True
                os.remove(tmp_csv)
                continue

            if paired_var:
                if weather_variable == "TEMP":
                    dataset = dataset[:grid_size]
                elif weather_variable == "DPT":
                    dataset = dataset[grid_size:2 * grid_size]

            if row is None:
                row = [dataset["startDate"].iloc[0], dataset["param"].iloc[0],
                       dataset["level"].iloc[0], dataset["latitude"].iloc[0],
                       dataset["longitude"].iloc[0]]

            value = np.reshape(dataset["value"].values, (len(lat), len(lon)))
            weighted_mean = np.sum((value * grid_cell_area) / total_area)
            row.append(weighted_mean)
            os.remove(tmp_csv)

        if row_failed or row is None:
            log.warning(f"Skipping date {date} due to bad file(s) above — no row written.")
        else:
            rows.append(row)

    with open(out_file, 'a') as f:
        csv.writer(f).writerows(rows)


def get_wind_data(file_list, csv_fields, out_file, region):
    with open(out_file, 'w') as f:
        csv.writer(f).writerow(csv_fields)

    rows = []
    tmp_csv = os.path.join(os.path.dirname(out_file), "tmp.csv")

    grouped = _group_files_by_date(file_list)

    for date in sorted(grouped.keys()):
        date_files = sorted(grouped[date])
        row = None
        lat = None
        lon = None
        grid_cell_area = None
        total_area = None
        grid_size = None
        row_failed = False

        if len(date_files) != len(FCST):
            log.warning(
                f"Skipping date {date} for WIND: "
                f"expected {len(FCST)} files, found {len(date_files)}."
            )
            continue

        for i, cur_file in enumerate(date_files):
            ret = subprocess.call(f"{WGRIB2} {cur_file} -csv {tmp_csv}", shell=True)

            if ret != 0:
                log.error(f"wgrib2 FAILED on file: {cur_file}")
                row_failed = True
                continue

            dataset = pd.read_csv(tmp_csv, names=HEADER)

            if i == 0:
                lat = np.unique(dataset["latitude"].values)
                lon = np.unique(dataset["longitude"].values)
                grid_size = len(lat) * len(lon)
                grid_cell_area = area_grid(lat, lon)
                total_area = np.sum(grid_cell_area)

            expected_rows = grid_size * 2
            if len(dataset) != expected_rows:
                log.error(
                    f"BAD FILE (row count mismatch): {cur_file} — "
                    f"expected {expected_rows} rows (2 x {grid_size} grid points), "
                    f"got {len(dataset)}. Skipping this entire row/date."
                )
                row_failed = True
                os.remove(tmp_csv)
                continue

            udataset = dataset[:grid_size]
            vdataset = dataset[grid_size:2 * grid_size]

            if row is None:
                row = [dataset["startDate"].iloc[0], dataset["param"].iloc[0],
                       dataset["level"].iloc[0], dataset["latitude"].iloc[0],
                       dataset["longitude"].iloc[0]]

            wind_speed = (udataset["value"].values**2 + vdataset["value"].values**2)**0.5
            value = np.reshape(wind_speed, (len(lat), len(lon)))
            weighted_mean = np.sum((value * grid_cell_area) / total_area)
            row.append(weighted_mean)
            os.remove(tmp_csv)

        if row_failed or row is None:
            log.warning(f"Skipping date {date} due to bad file(s) above — no row written.")
        else:
            rows.append(row)

    with open(out_file, 'a') as f:
        csv.writer(f).writerows(rows)

def extract_tars(region):
    """Extract all .tar files for a region into their variable directories.
    Handles nested tars: DOWNLOAD_DIR/region/var.tar may itself contain a
    var/ folder full of further chunked .tar files (date-range tars), which
    also need to be extracted before grib2 files are usable.
    Corrupted tars are logged and skipped instead of crashing the whole region."""
    for var in VARIABLES:
        var_dir = os.path.join(DOWNLOAD_DIR, region, var)
        single_tar = os.path.join(DOWNLOAD_DIR, region, f"{var}.tar")

        extract_target = var_dir
        tar_paths = []

        if os.path.isdir(var_dir):
            tar_paths = glob.glob(os.path.join(var_dir, "*.tar"))
        elif os.path.isfile(single_tar):
            os.makedirs(var_dir, exist_ok=True)
            tar_paths = [single_tar]
        else:
            log.warning(f"Missing directory or file: {var_dir} or {single_tar}")
            continue  # nothing at all for this var, truly skip

        # Extract any top-level tars found (outer tar, or chunk tars directly in var_dir)
        for tar_path in tar_paths:
            log.info(f"Extracting {tar_path}")
            try:
                with tarfile.open(tar_path) as tf:
                    tf.extractall(extract_target)
                log.info(f"Extracted to {extract_target}")
            except (tarfile.ReadError, EOFError) as e:
                log.error(f"Corrupted/truncated tar, skipping: {tar_path} ({e})")
                continue

        # ALWAYS run this pass if extract_target exists — even if no top-level
        # tars were found this run, previous runs may have left nested tars
        # still unextracted one or more levels deep.
        if os.path.isdir(extract_target):
            while True:
                inner_tars = glob.glob(os.path.join(extract_target, "**", "*.tar"), recursive=True)
                if not inner_tars:
                    break
                for inner_tar in inner_tars:
                    log.info(f"Extracting nested tar {inner_tar}")
                    inner_extract_dir = os.path.dirname(inner_tar)
                    try:
                        with tarfile.open(inner_tar) as tf:
                            tf.extractall(inner_extract_dir)
                        os.remove(inner_tar)
                        log.info(f"Extracted nested tar to {inner_extract_dir}")
                    except (tarfile.ReadError, EOFError) as e:
                        log.error(f"Corrupted/truncated nested tar, skipping: {inner_tar} ({e})")
                        os.remove(inner_tar)
                        continue

            # Flatten: move any grib2 files sitting in nested subfolders
            # directly into var_dir, then remove now-empty subfolders.
            for grib_path in glob.glob(os.path.join(extract_target, "**", "*.grib2"), recursive=True):
                if os.path.dirname(grib_path) != extract_target:
                    dest = os.path.join(extract_target, os.path.basename(grib_path))
                    if not os.path.exists(dest):
                        shutil.move(grib_path, dest)

            for root, dirs, files in os.walk(extract_target, topdown=False):
                if root != extract_target and not os.listdir(root):
                    os.rmdir(root)



# ── PIPELINE STEPS ────────────────────────────────────────────────────────────


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

    processed_vars = []
    for var_type, file_dir, fcst_col, csv_fields, out_file in tasks:
        if os.path.exists(out_file) and os.path.getsize(out_file) > 1000:
            log.info(f"✅ {var_type} already exists (cached) → {out_file}")
            processed_vars.append(var_type)
            continue
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
        processed_vars.append(var_type)

    return processed_vars


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

    processed_vars = run_data_collection(region)
    if not processed_vars:
        log.error(f"Processing failed: no variables were processed for {region}")
        sys.exit(1)

    mark_processed(region)
    log.info(f"✅ Processing complete for {region} (Variables: {processed_vars})")

    # Only trigger training if all weather features are available
    required_vars = {"WIND", "TEMP", "DPT", "DSWRF", "PCP"}
    if required_vars.issubset(set(processed_vars)):
        log.info(f"Weather variables complete, but skipping training trigger for {region} as requested.")
        # trigger_training(region)
    else:
        log.info(f"Skipping training trigger for {region} because some weather variables are missing (required: {required_vars}, got: {processed_vars})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", required=True, help="Region code e.g. CISO")
    args = parser.parse_args()
    main(args.region)