#!/usr/bin/env python3
"""
weekly_data_rotation.py

True sliding window across the FULL combined dataset (RDA + accumulated
NOMADS weeks treated as one continuous timeline):
  1. Detect the actual gap: from (archive's current end date + 1) through
     (yesterday).
  2. Fetch each missing day from NOMADS (weather) and EIA/ENTSO-E (grid).
  3. Self-heal fuel/emissions CSVs if they are stale (fewer rows than DB).
  4. Append only new rows to existing CSVs — never overwrite history.
  5. Concatenate / trim the sliding weather window.
  6. Re-run the full retraining pipeline.

Usage:
    python3 weekly_data_rotation.py --regions AECI BANC ...
    python3 weekly_data_rotation.py --regions AECI --start 20260824 --end 20260830
"""
import argparse
import csv
import glob
import logging
import os
import subprocess
import tarfile
from datetime import datetime, timezone, timedelta, date
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

logger = logging.getLogger("weekly_rotation_retrain")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PYTHON_BIN           = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/.venv/bin/python"
NOMADS_SCRIPT        = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src/CarbonCastAPI/CarbonCastRESTAPI/services/weather_fetch/fetch_grib_nomads.py"
RETRAINING_WEATHER_DOWNLOADS = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/retraining_weather_downloads"
AUTOMATION_TOOL_ROOT = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_OSRE_CC_automation_tool/CarbonCast"
FINAL_TRAINING_DATA  = f"{AUTOMATION_TOOL_ROOT}/final_training_data"
MANAGE_PY_DIR        = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src/CarbonCastAPI"
TRAINING_DATA_ROOT   = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/data"
EIA_DATA_DIR         = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src/eiaData"
WEEKLY_TRAINING_DIR           = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src/CarbonCastAPI/CarbonCastRESTAPI/services/weekly_training"
RETRAINING_ARCHIVE_PROCESSED  = f"{AUTOMATION_TOOL_ROOT}/retraining_archive_processed"

WEATHER_VARIABLES = ["TEMP", "DPT", "DSWRF", "WIND_SPEED", "PCP"]

# Fuel sources per region (must match firstTierConfig.json)
REGION_SOURCES = {
    "AECI": ["coal", "nat_gas", "wind"],
    "AZPS": ["coal", "nat_gas", "nuclear", "oil", "hydro", "solar", "wind", "other"],
    "BANC": ["nat_gas", "hydro", "solar", "other"],
    "BPAT": ["nat_gas", "nuclear", "hydro", "solar", "wind", "other"],
    "CISO": ["coal", "nat_gas", "nuclear", "oil", "hydro", "solar", "wind", "other"],
    "DOPD": ["hydro"],
    "DUK":  ["coal", "nat_gas", "nuclear", "hydro", "solar", "other"],
    "EPE":  ["nat_gas", "solar"],
    "ERCO": ["coal", "nat_gas", "nuclear", "hydro", "solar", "wind", "other"],
    "FMPP": ["coal", "nat_gas", "nuclear", "oil", "other", "solar"],
    "FPC":  ["coal", "nat_gas", "oil", "hydro", "solar", "other"],
    "FPL":  ["nat_gas", "nuclear", "oil", "solar", "other"],
    "GCPD": ["hydro"],
    "GRID": ["coal", "nat_gas", "solar", "wind"],
    "IPCO": ["nat_gas", "oil", "hydro", "solar", "wind", "other"],
    "ISNE": ["coal", "nat_gas", "nuclear", "oil", "hydro", "solar", "wind", "other"],
    "LDWP": ["coal", "nat_gas", "hydro", "solar", "wind", "other"],
    "LGEE": ["coal", "nat_gas", "hydro", "oil", "solar"],
    "MISO": ["coal", "nat_gas", "nuclear", "hydro", "solar", "wind", "other"],
    "NEVP": ["coal", "nat_gas", "nuclear", "oil", "hydro", "solar", "wind", "other"],
    "NWMT": ["coal", "nat_gas", "oil", "hydro", "solar", "wind"],
    "NYIS": ["coal", "nat_gas", "nuclear", "oil", "hydro", "solar", "wind", "other"],
    "PACE": ["coal", "nat_gas", "hydro", "solar", "wind", "other"],
    "PACW": ["nat_gas", "hydro", "solar", "wind", "other"],
    "PGE":  ["coal", "nat_gas", "wind", "hydro", "other"],
    "PJM":  ["coal", "nat_gas", "nuclear", "oil", "hydro", "solar", "wind", "other"],
    "PNM":  ["coal", "nat_gas", "wind", "hydro", "solar", "other"],
    "PSCO": ["coal", "nat_gas", "oil", "hydro", "solar", "wind", "other"],
    "PSEI": ["coal", "nat_gas", "oil", "hydro", "solar", "wind", "other"],
    "SC":   ["coal", "nat_gas", "oil", "hydro", "solar", "other"],
    "SCEG": ["coal", "nat_gas", "nuclear", "hydro", "solar", "other"],
    "SCL":  ["hydro"],
    "SOCO": ["coal", "nat_gas", "nuclear", "oil", "solar", "wind", "other"],
    "SPA":  ["hydro"],
    "SRP":  ["coal", "nat_gas", "nuclear", "hydro", "solar", "wind", "other"],
    "SWPP": ["coal", "nat_gas", "nuclear", "oil", "hydro", "solar", "wind", "other"],
    "TAL":  ["nat_gas", "solar"],
    "TEC":  ["coal", "nat_gas", "other", "oil", "solar"],
    "TEPC": ["coal", "nat_gas", "solar", "wind", "other"],
    "TIDC": ["nat_gas", "hydro"],
    "TPWR": ["hydro"],
    "TVA":  ["coal", "nat_gas", "nuclear", "oil", "hydro", "solar", "wind", "other"],
    "WACM": ["coal", "nat_gas", "hydro", "solar", "wind"],
    "WALC": ["nat_gas", "hydro", "solar", "wind"],
}

US_REGIONS = set(REGION_SOURCES.keys())

_TS_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(cmd, cwd=None):
    logger.info(f"RUN: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def _csv_row_count(path):
    """Return number of data rows (excluding header) in a CSV, or 0 if missing."""
    if not os.path.exists(path):
        return 0
    with open(path, newline="") as f:
        return max(0, sum(1 for _ in f) - 1)  # minus header


def _csv_last_ts(path):
    """Return the latest UTC datetime in a CSV's 'UTC time' column, or None."""
    if not os.path.exists(path):
        return None
    last = None
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_str = row.get("UTC time", "").strip()
            if not ts_str:
                continue
            for fmt in _TS_FORMATS:
                try:
                    dt = datetime.strptime(ts_str, fmt).replace(tzinfo=timezone.utc)
                    if last is None or dt > last:
                        last = dt
                    break
                except ValueError:
                    continue
    return last


def _db_row_count(region):
    """Return total EmissionActual row count for the region (via manage.py shell)."""
    script = (
        f"from CarbonCastRESTAPI.models import EmissionActual; "
        f"print('ROW_COUNT=' + str(EmissionActual.objects.filter(region='{region}').count()))"
    )
    result = subprocess.run(
        [PYTHON_BIN, "manage.py", "shell", "-c", script],
        cwd=MANAGE_PY_DIR, capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        if line.startswith("ROW_COUNT="):
            try:
                return int(line.split("=", 1)[1])
            except ValueError:
                pass
    return 0


# ---------------------------------------------------------------------------
# Step 1 — Weather: NOMADS fetch + process
# ---------------------------------------------------------------------------

def _weather_days_in_archive(region):
    """
    Return the set of dates already present in the processed weather archive
    (retraining_archive_processed/{region}/{region}_AVG_TEMP.csv).
    Each row in that file represents one fully-processed day.
    """
    archive = os.path.join(
        RETRAINING_ARCHIVE_PROCESSED, region, f"{region}_AVG_TEMP.csv"
    )
    if not os.path.exists(archive):
        return set()
    try:
        df = pd.read_csv(archive, usecols=[0], header=0)
        col = df.columns[0]          # first col is the date
        dates = set()
        for val in df[col]:
            try:
                dates.add(pd.to_datetime(val).date())
            except Exception:
                pass
        return dates
    except Exception:
        return set()


def compute_gap(region):
    """
    Returns (start_date, end_date, num_days) based on the weather archive's
    last known date.  Works for both large one-time catch-ups and routine 7-day gaps.
    """
    path = f"{FINAL_TRAINING_DATA}/{region}/{region}_AVG_TEMP.csv"
    df = pd.read_csv(path, parse_dates=["datetime"])
    last_known_date = df["datetime"].max().date()

    start = last_known_date + timedelta(days=1)
    end = date.today() - timedelta(days=1)   # yesterday — today not complete yet
    num_days = (end - start).days + 1

    if num_days <= 0:
        logger.info(f"[{region}] Archive already current through {last_known_date} -- nothing to fetch")
        return None, None, 0

    logger.info(f"[{region}] Detected gap: {start} -> {end} ({num_days} days)")
    return start, end, num_days


def extract_rda_tars(region, download_dir):
    """
    RDA delivers .tar archives instead of loose GRIB2 files. Extracts
    each .tar in place, then removes it, so multi-cycle training input
    looks the same whether it came from NOMADS or RDA.
    """
    for var in ("wind", "temp", "dswrf", "rain"):
        var_dir = os.path.join(download_dir, region, var)
        if not os.path.exists(var_dir):
            continue
        tar_files = glob.glob(os.path.join(var_dir, "*.tar"))
        for tar_path in tar_files:
            logger.info(f"[{region}/{var}] Extracting {os.path.basename(tar_path)}")
            try:
                with tarfile.open(tar_path) as tf:
                    tf.extractall(path=var_dir)
                os.remove(tar_path)
            except Exception as e:
                logger.error(f"Failed extracting {tar_path}: {e}")
        if tar_files:
            extracted = glob.glob(os.path.join(var_dir, "*.grib2"))
            logger.info(f"[{region}/{var}] {len(tar_files)} tar(s) -> {len(extracted)} grib2 files")


def _day_already_downloaded(region, d_str):
    """
    Check if GRIB2 files for date d_str (YYYYMMDD) already exist locally
    in retraining_weather_downloads across all weather variables.
    """
    for var in ("temp", "wind", "dswrf", "rain"):
        v_dir = os.path.join(RETRAINING_WEATHER_DOWNLOADS, region, var)
        if not os.path.exists(v_dir):
            return False
        matches = glob.glob(os.path.join(v_dir, f"gfs.0p25.{d_str}*.grib2"))
        if not matches:
            return False
    return True


def fetch_missing_days_nomads(region, start, end):
    """
    Download NOMADS GRIB data day-by-day.  Skips any day whose processed
    output already exists in the retraining archive or whose raw GRIB files
    are already present in retraining_weather_downloads (e.g. from RDA or prior fetch).
    """
    extract_rda_tars(region, RETRAINING_WEATHER_DOWNLOADS)
    already_done = _weather_days_in_archive(region)
    current = start
    while current <= end:
        d_str = current.strftime("%Y%m%d")
        if current in already_done:
            logger.info(
                f"[{region}] {current} already in processed weather archive — skipping NOMADS download"
            )
        elif _day_already_downloaded(region, d_str):
            logger.info(
                f"[{region}] {d_str} already downloaded locally in {RETRAINING_WEATHER_DOWNLOADS} — skipping NOMADS download"
            )
        else:
            logger.info(f"[{region}] Fetching NOMADS cycle for {d_str}")
            run([PYTHON_BIN, NOMADS_SCRIPT, "--region", region, "--date", d_str, "--hour", "00",
                 "--download-dir", RETRAINING_WEATHER_DOWNLOADS])
        current += timedelta(days=1)


def process_new_days_nomads(region, start, end):
    """
    Process downloaded GRIB files into the training archive.
    Skips entirely if ALL days in [start, end] are already in the archive.
    """
    extract_rda_tars(region, RETRAINING_WEATHER_DOWNLOADS)
    already_done = _weather_days_in_archive(region)
    needed = [
        start + timedelta(days=i)
        for i in range((end - start).days + 1)
    ]
    missing = [d for d in needed if d not in already_done]

    if not missing:
        logger.info(
            f"[{region}] All {len(needed)} weather days already processed — skipping NOMADS processing"
        )
        return

    logger.info(
        f"[{region}] {len(missing)}/{len(needed)} weather days need processing: "
        f"{missing[0]} → {missing[-1]}"
    )
    run(
        [PYTHON_BIN, "process_weekly_weather_for_training.py", "--region", region,
         "--download-dir", RETRAINING_WEATHER_DOWNLOADS,
         "--output-dir", f"{AUTOMATION_TOOL_ROOT}/retraining_weather_processed"],
        cwd=WEEKLY_TRAINING_DIR,
    )


# ---------------------------------------------------------------------------
# Step 2 — Grid: fetch new days from EIA/ENTSO-E into DB
# ---------------------------------------------------------------------------

def fetch_missing_days_grid(region, start, end):
    """
    Fetch EIA/ENTSO-E data for [start, end] and store in EmissionActual DB.
    Skips if full coverage already exists in DB for that exact date range.
    """
    # --- check coverage (use semicolons, not newlines, for -c flag robustness) ---
    check_script = (
        f"from CarbonCastRESTAPI.models import EmissionActual; "
        f"count = EmissionActual.objects.filter(region='{region}', "
        f"ts__date__gte='{start.isoformat()}', ts__date__lte='{end.isoformat()}').count(); "
        f"expected = ({(end - start).days + 1}) * 24; "
        f"print('SKIP' if count >= expected else 'FETCH')"
    )
    result = subprocess.run(
        [PYTHON_BIN, "manage.py", "shell", "-c", check_script],
        cwd=MANAGE_PY_DIR, capture_output=True, text=True
    )
    # check line-by-line to ignore Django banner/warning output
    if any(line.strip() == "SKIP" for line in result.stdout.splitlines()):
        logger.info(f"[{region}] Grid data for {start} -> {end} already complete -- skipping fetch")
        return

    if region in US_REGIONS:
        service_import = "from CarbonCastRESTAPI.services import eia_service"
        # Keep both statements on one line (joined with ;) to avoid indentation bugs
        fetch_call = (
            f"eia_service.EIA_BAL_AUTH_LIST = ['{region}']; "
            f"result = eia_service.fetch_and_store_eia_data(d.isoformat())"
        )
    else:
        service_import = "from CarbonCastRESTAPI.services import entsoe_service"
        fetch_call = (
            f"entsoe_service.ENTSOE_TARGET_REGIONS = ['{region}']; "
            f"result = entsoe_service.fetch_and_store_entsoe_data(d.isoformat())"
        )

    script = (
        f"{service_import}\n"
        f"from datetime import date, timedelta\n"
        f"start = date({start.year}, {start.month}, {start.day})\n"
        f"end = date({end.year}, {end.month}, {end.day})\n"
        f"d = start\n"
        f"while d <= end:\n"
        f"    {fetch_call}\n"
        f"    print(d.isoformat(), result)\n"
        f"    d += timedelta(days=1)"
    )
    run([PYTHON_BIN, "manage.py", "shell", "-c", script], cwd=MANAGE_PY_DIR)


# ---------------------------------------------------------------------------
# Step 3 — Self-heal: ensure fuel + emissions CSVs reflect full DB history
# ---------------------------------------------------------------------------

def _repair_fuel_csvs_from_eia_archive(region):
    """
    Seed fuel CSVs from eiaData/{region}_clean.csv when the CSV is stale
    (has far fewer rows than the DB).  This recovers from a previous overwrite
    that wiped historical data.
    """
    src = os.path.join(EIA_DATA_DIR, f"{region}_clean.csv")
    if not os.path.exists(src):
        logger.warning(f"[{region}] No EIA archive at {src} — cannot seed fuel CSVs")
        return

    sources = REGION_SOURCES.get(region, [])
    if not sources:
        logger.warning(f"[{region}] No REGION_SOURCES entry — cannot seed fuel CSVs")
        return

    fuel_dir = os.path.join(TRAINING_DATA_ROOT, region, "fuel_forecast")
    os.makedirs(fuel_dir, exist_ok=True)

    df = pd.read_csv(src)
    logger.info(
        f"[{region}] Seeding fuel CSVs from EIA archive: "
        f"{len(df)} rows ({df['UTC time'].iloc[0]} → {df['UTC time'].iloc[-1]})"
    )
    for fuel in sources:
        if fuel not in df.columns:
            logger.warning(f"[{region}] Column '{fuel}' not in EIA archive — skipping")
            continue
        out = os.path.join(fuel_dir, f"{region}_{fuel}_clean.csv")
        df[["UTC time", fuel]].to_csv(out, index=False)
        logger.info(f"[{region}] Seeded {len(df)} rows -> {out}")


def _repair_emissions_csvs_from_db(region):
    """
    Regenerate direct/lifecycle emissions CSVs from ALL DB rows when the
    CSV is stale (fewer rows than DB).  Uses manage.py shell for ORM access.
    """
    region_dir = os.path.join(TRAINING_DATA_ROOT, region)
    script = (
        f"from CarbonCastRESTAPI.models import EmissionActual; "
        f"import csv, os; "
        f"rows = list(EmissionActual.objects.filter(region='{region}').order_by('ts')); "
        f"base = '{region_dir}'; "
        f"[exec(open('/dev/stdin').read()) for _ in [None]]"
    )

    # Write a small Python script via manage.py shell
    inner = (
        f"from CarbonCastRESTAPI.models import EmissionActual\n"
        f"import csv, os\n"
        f"rows = list(EmissionActual.objects.filter(region='{region}').order_by('ts'))\n"
        f"base = '{region_dir}'\n"
        f"for cef, field in [('direct','direct'),('lifecycle','lifecycle')]:\n"
        f"    out = os.path.join(base, f'{region}_{{cef}}_emissions.csv')\n"
        f"    with open(out, 'w', newline='') as f:\n"
        f"        w = csv.writer(f)\n"
        f"        w.writerow(['UTC time', 'carbon_intensity'])\n"
        f"        for row in rows:\n"
        f"            v = getattr(row, field)\n"
        f"            w.writerow([row.ts.strftime('%Y-%m-%d %H:%M'), v if v is not None else 'nan'])\n"
        f"    print(f'[{region}] Seeded {{len(rows)}} rows -> {{out}}')\n"
    )
    run([PYTHON_BIN, "manage.py", "shell", "-c", inner], cwd=MANAGE_PY_DIR)


def validate_and_repair_grid_csvs(region):
    """
    Self-healing check before appending new rows:

    1. Get total DB row count for the region.
    2. For each fuel CSV: if its row count < 80% of DB rows → stale → re-seed
       from eiaData/{region}_clean.csv.
    3. For each emissions CSV: if its row count < 80% of DB rows → stale →
       regenerate from full DB.

    After seeding, the normal append step will add any DB rows newer than
    the CSV's last timestamp.
    """
    db_rows = _db_row_count(region)
    if db_rows == 0:
        logger.warning(f"[{region}] DB is empty — skipping CSV validation")
        return

    threshold = int(db_rows * 0.80)
    logger.info(f"[{region}] DB has {db_rows} rows; CSV staleness threshold = {threshold} rows")

    # --- fuel CSVs ---
    sources = REGION_SOURCES.get(region, [])
    fuel_dir = os.path.join(TRAINING_DATA_ROOT, region, "fuel_forecast")
    stale_fuel = False
    for fuel in sources:
        csv_path = os.path.join(fuel_dir, f"{region}_{fuel}_clean.csv")
        count = _csv_row_count(csv_path)
        if count < threshold:
            logger.warning(
                f"[{region}] {fuel}_clean.csv has only {count} rows vs {db_rows} in DB "
                f"(< {threshold} threshold) — STALE, will re-seed from EIA archive"
            )
            stale_fuel = True
            break
        else:
            logger.info(f"[{region}] {fuel}_clean.csv OK ({count} rows)")

    if stale_fuel:
        _repair_fuel_csvs_from_eia_archive(region)

    # --- emissions CSVs ---
    region_dir = os.path.join(TRAINING_DATA_ROOT, region)
    stale_emissions = False
    for cef in ["direct", "lifecycle"]:
        csv_path = os.path.join(region_dir, f"{region}_{cef}_emissions.csv")
        count = _csv_row_count(csv_path)
        if count < threshold:
            logger.warning(
                f"[{region}] {cef}_emissions.csv has only {count} rows vs {db_rows} in DB "
                f"(< {threshold} threshold) — STALE, will regenerate from DB"
            )
            stale_emissions = True
            break
        else:
            logger.info(f"[{region}] {cef}_emissions.csv OK ({count} rows)")

    if stale_emissions:
        _repair_emissions_csvs_from_db(region)


# ---------------------------------------------------------------------------
# Step 4 — Append new DB rows to CSVs (never overwrite)
# ---------------------------------------------------------------------------

def append_grid_data_csvs(region):
    """
    Append only the rows newly stored in EmissionActual (since the CSV's last
    timestamp) to the fuel + emissions CSVs.  Uses the weekly_training edition
    of prepare_grid_data_for_retraining which opens files in append mode.
    """
    script = (
        f"from CarbonCastRESTAPI.services.weekly_training.prepare_grid_data_for_retraining "
        f"import verify_region, export_training_csvs; "
        f"v = verify_region('{region}'); "
        f"export_training_csvs('{region}'); "
        f"print('[{region}] CSV APPEND DONE: ' + str(v['total_days']) + ' days in DB, "
        f"' + str(v['incomplete_days']) + ' incomplete')"
    )
    run([PYTHON_BIN, "manage.py", "shell", "-c", script], cwd=MANAGE_PY_DIR)


# ---------------------------------------------------------------------------
# Step 5 — Weather: concat + trim sliding window
# ---------------------------------------------------------------------------

def concat_weather(region, start, end):
    """
    Merge processed weekly weather into the final training archive.
    Skips if the archive already contains all dates in [start, end].
    """
    archive_temp = os.path.join(FINAL_TRAINING_DATA, region, f"{region}_AVG_TEMP.csv")
    if os.path.exists(archive_temp):
        try:
            df = pd.read_csv(archive_temp, parse_dates=["datetime"])
            archive_dates = set(df["datetime"].dt.date)
            needed = {
                start + timedelta(days=i)
                for i in range((end - start).days + 1)
            }
            if needed.issubset(archive_dates):
                logger.info(
                    f"[{region}] Final weather archive already contains "
                    f"{start} → {end} — skipping concat_weather"
                )
                return
        except Exception:
            pass  # if anything goes wrong, just run concat

    run(
        [PYTHON_BIN, "build_final_training_dataset.py", "--region", region],
        cwd=WEEKLY_TRAINING_DIR,
    )


def trim_oldest_days(region, num_days):
    region_dir = f"{FINAL_TRAINING_DATA}/{region}"
    for var in WEATHER_VARIABLES:
        path = f"{region_dir}/{region}_AVG_{var}.csv"
        if not os.path.exists(path):
            logger.warning(f"[{region}] Missing {path}, skipping trim for {var}")
            continue
        df = pd.read_csv(path, parse_dates=["datetime"])
        before_min, before_max = df["datetime"].min(), df["datetime"].max()
        new_start = before_min + timedelta(days=num_days)
        df = df[df["datetime"] >= new_start].reset_index(drop=True)
        df.to_csv(path, index=False)
        logger.info(
            f"[{region}] {var}: trimmed {before_min.date()} -> {before_max.date()} "
            f"to {df['datetime'].min().date() if not df.empty else 'EMPTY'} -> "
            f"{df['datetime'].max().date() if not df.empty else 'EMPTY'}"
        )


def trim_oldest_days_grid_data(region, num_days):
    script = (
        f"from CarbonCastRESTAPI.models import EmissionActual\n"
        f"from django.db.models import Min\n"
        f"from datetime import timedelta\n"
        f"earliest = EmissionActual.objects.filter(region='{region}').aggregate(Min('ts'))['ts__min']\n"
        f"if earliest:\n"
        f"    cutoff = earliest + timedelta(days={num_days})\n"
        f"    deleted, _ = EmissionActual.objects.filter(region='{region}', ts__lt=cutoff).delete()\n"
        f"    print(f'[{region}] Deleted {{deleted}} rows before {{cutoff}}')"
    )
    run([PYTHON_BIN, "manage.py", "shell", "-c", script], cwd=MANAGE_PY_DIR)


# ---------------------------------------------------------------------------
# Step 6 — Retrain
# ---------------------------------------------------------------------------

def retrain_region(region):
    run(
        [PYTHON_BIN, "run_full_retraining_batch.py", "--regions", region],
        cwd=WEEKLY_TRAINING_DIR,
    )


# ---------------------------------------------------------------------------
# Orchestrator — Pipelined (Concurrent Fetch & Train)
# ---------------------------------------------------------------------------

def prepare_region_data(region, override_start=None, override_end=None):
    """
    Data Preparation Worker:
    Fetches weather, processes GRIB files, fetches grid data, validates/repairs CSVs,
    appends new rows, and concatenates/trims the sliding weather & grid window.
    This prepares all dataset files for 'region' so it is 100% ready for retraining.
    Returns:
        (status, num_days) where status is 'READY', 'SKIPPED', or raises on error.
    """
    logger.info(f"\n{'='*20} [DATA PREP START] {region} {'='*20}")
    if override_start and override_end:
        start = datetime.strptime(override_start, "%Y%m%d").date()
        end   = datetime.strptime(override_end,   "%Y%m%d").date()
        num_days = (end - start).days + 1
        logger.info(f"[{region}] Using explicit override range: {start} -> {end} ({num_days} days)")
    else:
        start, end, num_days = compute_gap(region)

    if num_days == 0:
        logger.info(f"[{region}] Data already current — skipping")
        return "SKIPPED", 0

    # ── WEATHER ──────────────────────────────────────────────────
    fetch_missing_days_nomads(region, start, end)   # skips days already in archive
    process_new_days_nomads(region, start, end)      # skips if all days already done

    # ── GRID DATA ─────────────────────────────────────────────────
    fetch_missing_days_grid(region, start, end)      # skips if DB already has full range

    # Self-heal: re-seed any stale CSVs BEFORE appending
    validate_and_repair_grid_csvs(region)

    # Append only new DB rows to CSVs (skips if CSV already current)
    append_grid_data_csvs(region)

    # ── WEATHER WINDOW ────────────────────────────────────────────
    concat_weather(region, start, end)               # skips if archive already has range
    trim_oldest_days(region, num_days)
    trim_oldest_days_grid_data(region, num_days)

    logger.info(f"[{region}] Data preparation COMPLETE! Ready for model training.")
    return "READY", num_days


def run_weekly_cycle(regions, override_start=None, override_end=None):
    """
    Pipelined weekly rotation orchestrator:
    Overlaps data preparation (I/O & network bound) for region N+1
    with model retraining (CPU & GPU bound) for region N.
    """
    results = {}
    if not regions:
        return results

    logger.info(f"\n{'='*20} STARTING PIPELINED ROTATION FOR {len(regions)} REGIONS {'='*20}")
    logger.info("Pipeline mode: Data prep for Region N+1 runs in background while Region N retrains.")

    # 1 worker in executor ensures exactly one region pre-fetches while one region trains
    with ThreadPoolExecutor(max_workers=1) as executor:
        # Pre-fetch the very first region
        first_region = regions[0]
        prep_future = executor.submit(prepare_region_data, first_region, override_start, override_end)

        for i, region in enumerate(regions):
            logger.info(f"\n{'#'*25} PROCESSING REGION {i+1}/{len(regions)}: {region} {'#'*25}")

            # 1. Wait for current region's data preparation to finish
            prep_status = None
            try:
                prep_status, _ = prep_future.result()
            except Exception as exc:
                import traceback
                logger.error(f"[{region}] Data preparation FAILED: {exc}")
                logger.error(traceback.format_exc())
                results[region] = f"FAILED (data prep): {exc}"
                prep_status = "FAILED"

            # 2. Immediately kick off data preparation for the NEXT region in the background
            next_idx = i + 1
            if next_idx < len(regions):
                next_region = regions[next_idx]
                logger.info(f"\n>>> [PIPELINE] Launching background data fetch for NEXT region: {next_region} <<<")
                prep_future = executor.submit(prepare_region_data, next_region, override_start, override_end)
            else:
                prep_future = None

            # 3. Check current region prep status
            if prep_status == "SKIPPED":
                results[region] = "SKIPPED (already current)"
                continue
            elif prep_status != "READY":
                # Already recorded as FAILED
                continue

            # 4. Retrain current region (while next region's data is preparing in background)
            try:
                logger.info(f"\n{'='*20} [RETRAIN START] {region} {'='*20}")
                retrain_region(region)
                results[region] = "SUCCESS"
                logger.info(f"##### {region} RETRAINING COMPLETE (SUCCESS) #####")
            except Exception as exc:
                import traceback
                logger.error(f"[{region}] Retraining FAILED: {exc}")
                logger.error(traceback.format_exc())
                results[region] = f"FAILED (retraining): {exc}"

    logger.info(f"\n{'='*20} WEEKLY ROTATION SUMMARY {'='*20}")
    for region, status in results.items():
        logger.info(f"{region}: {status}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Weekly CarbonCast retraining rotation")
    parser.add_argument("--regions", nargs="+", required=True, help="Region codes e.g. AECI BANC")
    parser.add_argument("--start", default=None, help="YYYYMMDD override gap start")
    parser.add_argument("--end",   default=None, help="YYYYMMDD override gap end")
    args = parser.parse_args()
    run_weekly_cycle(args.regions, override_start=args.start, override_end=args.end)
