#!/usr/bin/env python3
"""
process_weekly_weather.py — Converts ONE week of freshly-downloaded GRIB2
files (from fetch_grib_nomads.py) into the 5 per-variable CSVs, using the
exact same wgrib2 + area-weighting logic as process_weather_data.py, but
scoped strictly to the files present right now — no 2024-2026 date scan,
no risk of mixing in stale data from previous runs.

Usage:
    python3 process_weekly_weather.py --region CISO
"""

import os
import sys
import glob
import re
import csv
import logging
import argparse
import subprocess

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("process_weekly_weather")

DOWNLOAD_DIR = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/realtime_weather_downloads"
OUTPUT_DIR = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/realtime_weather_processed"
WGRIB2 = "/Users/prarthanapatil/.local/share/mamba/bin/wgrib2"

HEADER = ["startDate", "endDate", "param", "level", "longitude", "latitude", "value"]

CSV_FILE_FIELDS_FCST = ["datetime", "param", "level", "latitude", "longitude", "Analysis"] + \
    [f"{h} hr fcst" for h in range(3, 169, 3)]

CSV_FILE_FIELDS_AVG = ["datetime", "param", "level", "latitude", "longitude"]
for s in range(0, 168, 6):
    CSV_FILE_FIELDS_AVG.append(f"{s}-{s+3} hr avg")
    CSV_FILE_FIELDS_AVG.append(f"{s}-{s+6} hr avg")

CSV_FILE_FIELDS_ACC = ["datetime", "param", "level", "latitude", "longitude"]
for s in range(0, 168, 6):
    CSV_FILE_FIELDS_ACC.append(f"{s}-{s+3} hr acc")
    CSV_FILE_FIELDS_ACC.append(f"{s}-{s+6} hr acc")


def earth_radius(lat):
    a, b = 6378137, 6356752.3142
    e2 = 1 - (b**2 / a**2)
    lat = np.deg2rad(lat)
    lat_gc = np.arctan((1 - e2) * np.tan(lat))
    return ((a * (1 - e2)**0.5) / (1 - (e2 * np.cos(lat_gc)**2))**0.5)


def area_grid(lat, lon):
    xlon, ylat = np.meshgrid(lon, lat)
    R = earth_radius(ylat)
    dlat = np.deg2rad(np.gradient(ylat, axis=0))
    dlon = np.deg2rad(np.gradient(xlon, axis=1))
    dy = dlat * R
    dx = dlon * R * np.cos(np.deg2rad(ylat))
    return dy * dx


def get_files_for_this_week(var_dir):
    files = sorted(glob.glob(os.path.join(var_dir, "gfs.0p25.*.grib2")))
    if not files:
        log.warning(f"No files found in {var_dir}")
        return files

    # Only keep the LATEST cycle (date+hour prefix) — discard stale cycles
    # from previous fetches that were never cleaned up.
    def _cycle(f):
        m = re.search(r"gfs\.0p25\.(\d{10})\.f\d{3}\.grib2$", os.path.basename(f))
        return m.group(1) if m else ""

    latest_cycle = max(_cycle(f) for f in files)
    files = [f for f in files if _cycle(f) == latest_cycle]
    return files


def _fhour_from_filename(f):
    m = re.search(r"\.f(\d{3})\.grib2$", os.path.basename(f))
    return int(m.group(1)) if m else None

def extract_rda_tars(region, var, download_dir):
    """RDA delivers .tar archives instead of loose GRIB2 files. Extracts
    each .tar in place, then removes it, so multi-cycle training input
    looks the same whether it came from NOMADS or RDA."""
    import tarfile
    var_dir = os.path.join(download_dir, region, var)
    tar_files = glob.glob(os.path.join(var_dir, "*.tar"))
    for tar_path in tar_files:
        log.info(f"[{region}/{var}] Extracting {os.path.basename(tar_path)}")
        with tarfile.open(tar_path) as tf:
            tf.extractall(path=var_dir)
        os.remove(tar_path)
    if tar_files:
        extracted = glob.glob(os.path.join(var_dir, "*.grib2"))
        log.info(f"[{region}/{var}] {len(tar_files)} tar(s) -> {len(extracted)} grib2 files")


def process_single_variable(file_list, csv_fields, out_file, paired_var, var_label):
    """Same wgrib2 + area-weighting logic as process_weather_data.py,
    but iterating in forecast-hour order over ONE week's files, not by date."""
    with open(out_file, "w") as f:
        csv.writer(f).writerow(csv_fields)

    tmp_csv = os.path.join(os.path.dirname(out_file), "tmp_weekly.csv")
    row = None
    lat = lon = grid_cell_area = total_area = grid_size = None
    row_failed = False

    files_sorted = sorted(file_list, key=lambda f: _fhour_from_filename(f) or 0)

    for i, cur_file in enumerate(files_sorted):
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
            log.info(f"[{var_label}] grid_size={grid_size} ({len(lat)} lat x {len(lon)} lon)")

        expected_rows = grid_size * 2 if paired_var else grid_size
        if len(dataset) != expected_rows:
            log.error(
                f"BAD FILE (row count mismatch): {cur_file} — "
                f"expected {expected_rows}, got {len(dataset)}. Skipping."
            )
            row_failed = True
            os.remove(tmp_csv)
            continue

        if paired_var:
            first_half = dataset[:grid_size]
            second_half = dataset[grid_size:2 * grid_size]
            dataset = first_half if var_label in ("TEMP", "WIND_U") else second_half

        if row is None:
            row = [dataset["startDate"].iloc[0], dataset["param"].iloc[0],
                   dataset["level"].iloc[0], dataset["latitude"].iloc[0],
                   dataset["longitude"].iloc[0]]

        value = np.reshape(dataset["value"].values, (len(lat), len(lon)))
        weighted_mean = np.sum((value * grid_cell_area) / total_area)
        row.append(weighted_mean)
        os.remove(tmp_csv)

    if row_failed or row is None:
        log.warning(f"[{var_label}] Incomplete — some files failed or mismatched.")
        return False

    with open(out_file, "a") as f:
        csv.writer(f).writerow(row)
    log.info(f"[{var_label}] wrote 1 row -> {out_file}")
    return True


def process_wind(file_list, out_file):
    """Wind needs vector magnitude from UGRD+VGRD stacked in the same file."""
    with open(out_file, "w") as f:
        csv.writer(f).writerow(CSV_FILE_FIELDS_FCST)

    tmp_csv = os.path.join(os.path.dirname(out_file), "tmp_wind_weekly.csv")
    row = None
    lat = lon = grid_cell_area = total_area = grid_size = None
    row_failed = False

    files_sorted = sorted(file_list, key=lambda f: _fhour_from_filename(f) or 0)

    for i, cur_file in enumerate(files_sorted):
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
            log.info(f"[WIND] grid_size={grid_size} ({len(lat)} lat x {len(lon)} lon)")

        expected_rows = grid_size * 2
        if len(dataset) != expected_rows:
            log.error(
                f"BAD FILE (row count mismatch): {cur_file} — "
                f"expected {expected_rows}, got {len(dataset)}. Skipping."
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
        log.warning("[WIND] Incomplete.")
        return False

    with open(out_file, "a") as f:
        csv.writer(f).writerow(row)
    log.info(f"[WIND] wrote 1 row -> {out_file}")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", required=True)
    parser.add_argument("--download-dir", default=DOWNLOAD_DIR)
    parser.add_argument("--output-dir", default=OUTPUT_DIR)
    args = parser.parse_args()
    region = args.region
    download_dir = args.download_dir
    output_dir = args.output_dir

    out_dir = os.path.join(output_dir, region)
    for var in ("wind", "temp", "dswrf", "rain"):
        extract_rda_tars(region, var, download_dir)
    os.makedirs(out_dir, exist_ok=True)

    wind_files  = get_files_for_this_week(os.path.join(download_dir, region, "wind"))
    temp_files  = get_files_for_this_week(os.path.join(download_dir, region, "temp"))
    dswrf_files = get_files_for_this_week(os.path.join(download_dir, region, "dswrf"))
    rain_files  = get_files_for_this_week(os.path.join(download_dir, region, "rain"))

    results = {}
    results["WIND"] = process_wind(wind_files, os.path.join(out_dir, f"{region}_AVG_WIND_SPEED.csv"))
    results["TEMP"] = process_single_variable(
        temp_files, CSV_FILE_FIELDS_FCST, os.path.join(out_dir, f"{region}_AVG_TEMP.csv"),
        paired_var=True, var_label="TEMP",
    )
    results["DPT"] = process_single_variable(
        temp_files, CSV_FILE_FIELDS_FCST, os.path.join(out_dir, f"{region}_AVG_DPT.csv"),
        paired_var=True, var_label="DPT",
    )
    results["DSWRF"] = process_single_variable(
        dswrf_files, CSV_FILE_FIELDS_AVG, os.path.join(out_dir, f"{region}_AVG_DSWRF.csv"),
        paired_var=False, var_label="DSWRF",
    )
    results["PCP"] = process_single_variable(
        rain_files, CSV_FILE_FIELDS_ACC, os.path.join(out_dir, f"{region}_AVG_PCP.csv"),
        paired_var=True, var_label="PCP",
    )

    log.info(f"Results: {results}")
    if not all(results.values()):
        log.error("Some variables failed — check warnings above before proceeding.")
        sys.exit(1)
    log.info("All variables processed successfully.")


if __name__ == "__main__":
    main()