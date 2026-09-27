#!/usr/bin/env python3
"""
process_weekly_weather_for_training.py

Companion to process_weekly_weather.py, built specifically for the weekly
retraining rotation. process_weekly_weather.py itself is UNTOUCHED and
keeps its original single-cycle behavior for daily real-time inference --
this script is a separate code path so there is zero risk of the
inference pipeline accidentally accumulating rows or changing behavior.

Processes EVERY distinct GFS cycle found in the download directory (one
row per day, for however many days were fetched), instead of only the
latest cycle.

Usage:
    python3 process_weekly_weather_for_training.py --region AECI \
        --download-dir .../retraining_weather_downloads \
        --output-dir .../retraining_weather_processed
"""
import os
import sys
import glob
import re
import csv
import logging
import argparse
import subprocess
import tarfile

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("process_weekly_weather_for_training")

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


def _cycle_of(f):
    # Match only 00z cycles (1 per day) to match CarbonCast standard daily cycle format
    m = re.search(r"gfs\.0p25\.(\d{8}00)\.f\d{3}\.grib2$", os.path.basename(f))
    return m.group(1) if m else ""


def get_all_cycles(var_dir):
    """Returns every distinct cycle (date+hour) present, sorted oldest first."""
    files = sorted(glob.glob(os.path.join(var_dir, "gfs.0p25.*.grib2")))
    if not files:
        log.warning(f"No files found in {var_dir}")
        return {}
    by_cycle = {}
    for f in files:
        c = _cycle_of(f)
        if c:
            by_cycle.setdefault(c, []).append(f)
    return by_cycle


def _fhour_from_filename(f):
    m = re.search(r"\.f(\d{3})\.grib2$", os.path.basename(f))
    return int(m.group(1)) if m else None


def process_single_variable_one_cycle(file_list, paired_var, var_label):
    """Same wgrib2 + area-weighting logic as process_weekly_weather.py,
    but returns the row instead of writing it -- caller controls output."""
    tmp_csv = f"/tmp/tmp_training_{var_label}_{os.getpid()}.csv"
    row = None
    lat = lon = grid_cell_area = total_area = grid_size = None

    files_sorted = sorted(file_list, key=lambda f: _fhour_from_filename(f) or 0)

    for i, cur_file in enumerate(files_sorted):
        ret = subprocess.call(f"{WGRIB2} {cur_file} -csv {tmp_csv}", shell=True)
        if ret != 0:
            log.error(f"wgrib2 FAILED on file: {cur_file}")
            return None

        dataset = pd.read_csv(tmp_csv, names=HEADER)

        if i == 0:
            lat = np.unique(dataset["latitude"].values)
            lon = np.unique(dataset["longitude"].values)
            grid_size = len(lat) * len(lon)
            grid_cell_area = area_grid(lat, lon)
            total_area = np.sum(grid_cell_area)

        expected_rows = grid_size * 2 if paired_var else grid_size
        actual_rows = len(dataset)

        # GFS (as of 2026) writes two identical APCP messages per GRIB2 file,
        # doubling the CSV row count to 2 * expected_rows. Both messages carry
        # the same field values, so we keep only the first expected_rows rows.
        if actual_rows == expected_rows * 2:
            log.warning(
                f"[{var_label}] Duplicate-message GRIB2 in {os.path.basename(cur_file)} "
                f"(got {actual_rows}, expected {expected_rows}). Keeping first {expected_rows} rows."
            )
            dataset = dataset.iloc[:expected_rows].reset_index(drop=True)
        elif actual_rows != expected_rows:
            log.error(f"BAD FILE (row count mismatch): {cur_file} — expected {expected_rows}, got {actual_rows}")
            os.remove(tmp_csv)
            return None

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

    return row


def process_wind_one_cycle(file_list):
    tmp_csv = f"/tmp/tmp_training_wind_{os.getpid()}.csv"
    row = None
    lat = lon = grid_cell_area = total_area = grid_size = None

    files_sorted = sorted(file_list, key=lambda f: _fhour_from_filename(f) or 0)

    for i, cur_file in enumerate(files_sorted):
        ret = subprocess.call(f"{WGRIB2} {cur_file} -csv {tmp_csv}", shell=True)
        if ret != 0:
            log.error(f"wgrib2 FAILED on file: {cur_file}")
            return None

        dataset = pd.read_csv(tmp_csv, names=HEADER)

        if i == 0:
            lat = np.unique(dataset["latitude"].values)
            lon = np.unique(dataset["longitude"].values)
            grid_size = len(lat) * len(lon)
            grid_cell_area = area_grid(lat, lon)
            total_area = np.sum(grid_cell_area)

        expected_rows = grid_size * 2
        actual_rows = len(dataset)

        # GFS (as of 2026) writes two identical UGRD+VGRD messages per file
        # in some cases, quadrupling rows. Keep first 2*grid_size (one U + one V).
        if actual_rows == expected_rows * 2:
            log.warning(
                f"[WIND] Duplicate-message GRIB2 in {os.path.basename(cur_file)} "
                f"(got {actual_rows}, expected {expected_rows}). Keeping first {expected_rows} rows."
            )
            dataset = dataset.iloc[:expected_rows].reset_index(drop=True)
        elif actual_rows != expected_rows:
            log.error(f"BAD FILE (row count mismatch): {cur_file} — expected {expected_rows}, got {actual_rows}")
            os.remove(tmp_csv)
            return None

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

    return row


def extract_rda_tars(region, download_dir):
    """RDA delivers .tar archives instead of loose GRIB2 files. Extracts
    each .tar in place, then removes it, so multi-cycle training input
    looks the same whether it came from NOMADS or RDA."""
    for var in ("wind", "temp", "dswrf", "rain"):
        var_dir = os.path.join(download_dir, region, var)
        if not os.path.exists(var_dir):
            continue
        tar_files = glob.glob(os.path.join(var_dir, "*.tar"))
        for tar_path in tar_files:
            log.info(f"[{region}/{var}] Extracting {os.path.basename(tar_path)}")
            try:
                with tarfile.open(tar_path) as tf:
                    tf.extractall(path=var_dir)
                os.remove(tar_path)
            except Exception as e:
                log.error(f"Failed extracting {tar_path}: {e}")
        if tar_files:
            extracted = glob.glob(os.path.join(var_dir, "*.grib2"))
            log.info(f"[{region}/{var}] {len(tar_files)} tar(s) -> {len(extracted)} grib2 files")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", required=True)
    parser.add_argument("--download-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    region, download_dir, output_dir = args.region, args.download_dir, args.output_dir

    out_dir = os.path.join(output_dir, region)
    os.makedirs(out_dir, exist_ok=True)

    extract_rda_tars(region, download_dir)

    # Skip entirely if all 5 output CSVs already exist AND cover the same
    # number of days as what we're about to process -- avoids redoing
    # expensive wgrib2 processing on every run.
    expected_files = [
        os.path.join(out_dir, f"{region}_AVG_WIND_SPEED.csv"),
        os.path.join(out_dir, f"{region}_AVG_TEMP.csv"),
        os.path.join(out_dir, f"{region}_AVG_DPT.csv"),
        os.path.join(out_dir, f"{region}_AVG_DSWRF.csv"),
        os.path.join(out_dir, f"{region}_AVG_PCP.csv"),
    ]
    wind_dir = os.path.join(download_dir, region, "wind")
    temp_dir = os.path.join(download_dir, region, "temp")
    dswrf_dir = os.path.join(download_dir, region, "dswrf")
    rain_dir = os.path.join(download_dir, region, "rain")

    wind_by_cycle = get_all_cycles(wind_dir)
    temp_by_cycle = get_all_cycles(temp_dir)
    dswrf_by_cycle = get_all_cycles(dswrf_dir)
    rain_by_cycle = get_all_cycles(rain_dir)

    cycles = sorted(temp_by_cycle.keys())
    log.info(f"[{region}] Found {len(cycles)} distinct cycles: {cycles}")

    if all(os.path.exists(p) for p in expected_files):
        row_counts = [sum(1 for _ in open(p)) - 1 for p in expected_files]
        if all(rc == len(cycles) for rc in row_counts):
            log.info(
                f"[{region}] All 5 output CSVs already exist with {len(cycles)} rows "
                f"matching {len(cycles)} cycles -- skipping reprocessing."
            )
            return
        else:
            log.info(
                f"[{region}] Output row counts {row_counts} do not all match {len(cycles)} cycles -- reprocessing."
            )

    variable_specs = [
        ("WIND", None, None, None),  # handled separately below
        ("TEMP", temp_by_cycle, CSV_FILE_FIELDS_FCST, "TEMP"),
        ("DPT", temp_by_cycle, CSV_FILE_FIELDS_FCST, "DPT"),
        ("DSWRF", dswrf_by_cycle, CSV_FILE_FIELDS_AVG, "DSWRF"),
        ("PCP", rain_by_cycle, CSV_FILE_FIELDS_ACC, "PCP"),
    ]

    all_ok = True

    # WIND
    wind_rows = []
    for cycle in cycles:
        row = process_wind_one_cycle(wind_by_cycle.get(cycle, []))
        if row is None:
            all_ok = False
            continue
        wind_rows.append(row)
    out_path = os.path.join(out_dir, f"{region}_AVG_WIND_SPEED.csv")
    with open(out_path, "w") as f:
        w = csv.writer(f)
        w.writerow(CSV_FILE_FIELDS_FCST)
        w.writerows(wind_rows)
    log.info(f"[WIND] wrote {len(wind_rows)} rows -> {out_path}")

    # TEMP, DPT, DSWRF, PCP
    for label, by_cycle, fields, var_label in variable_specs[1:]:
        rows = []
        for cycle in cycles:
            files = by_cycle.get(cycle, [])
            paired = label in ("TEMP", "DPT")
            row = process_single_variable_one_cycle(files, paired, var_label)
            if row is None:
                all_ok = False
                continue
            rows.append(row)
        out_path = os.path.join(out_dir, f"{region}_AVG_{label}.csv")
        with open(out_path, "w") as f:
            w = csv.writer(f)
            w.writerow(fields)
            w.writerows(rows)
        log.info(f"[{label}] wrote {len(rows)} rows -> {out_path}")

    if not all_ok:
        log.error("Some cycles/variables failed — check warnings above.")
        sys.exit(1)
    log.info(f"All {len(cycles)} cycle(s) processed successfully for {region}.")


if __name__ == "__main__":
    main()