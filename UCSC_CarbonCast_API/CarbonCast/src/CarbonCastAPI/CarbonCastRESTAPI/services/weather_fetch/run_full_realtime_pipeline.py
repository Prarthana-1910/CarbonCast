#!/usr/bin/env python3
"""
run_full_realtime_pipeline.py

End-to-end real-time CarbonCast pipeline for one region:
  1. Fetch latest EIA generation data (today + yesterday, to ensure a full
     24h window for the electricity_date the ML path needs)
  2. Fetch NOMADS weather GRIB2 files
  3. Process GRIB2 -> wide CSVs (process_weekly_weather.py logic)
  4. Expand -> hourly, merge, reshape into a 168h block
  5. Stage weather + electricity + CI-emissions CSVs into the exact
     filenames/formats the real-time ML scripts expect
  6. Run retraining (which triggers ML inference + Forecast168 write-back)

Must be run inside the Django project (uses the ORM + ML imports).
Usage:
    python manage.py shell -c "
    from CarbonCastRESTAPI.services.weather_fetch.run_full_realtime_pipeline import run_pipeline
    run_pipeline('CISO')
    "
"""

import os
import subprocess
import logging
import sys
from datetime import date, timedelta

os.environ.setdefault("EIA_API_KEY", "Qc8vFrBgZhLdtFVurGbxHbCrvyP93RoPXVhKfCGx")
os.environ.setdefault("ENTSOE_API_KEY", "3d8580df-94bb-4d1f-9854-50b736a39858")

logger = logging.getLogger("run_full_realtime_pipeline")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---- Paths — adjust if your layout differs ----
CARBONCAST_ROOT = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast"
if f"{CARBONCAST_ROOT}/src/CarbonCastAPI" not in sys.path:
    sys.path.insert(0, f"{CARBONCAST_ROOT}/src/CarbonCastAPI")
if f"{CARBONCAST_ROOT}/src" not in sys.path:
    sys.path.insert(0, f"{CARBONCAST_ROOT}/src")
AUTOMATION_TOOL_PROCESSED_DATA = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_OSRE_CC_automation_tool/CarbonCast/processed_data"
PYTHON_BIN = f"{CARBONCAST_ROOT}/.venv/bin/python"

WEATHER_STAGE_DIR = f"{CARBONCAST_ROOT}/realtime_weather_staged"
ELECTRICITY_STAGE_DIR = f"{CARBONCAST_ROOT}/realtime_electricity_staged"
WEATHER_DOWNLOADS_DIR="/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/realtime_weather_downloads"
FIRST_TIER_CONFIG = f"{CARBONCAST_ROOT}/src/firstTierConfig.json"
SECOND_TIER_CONFIG = f"{CARBONCAST_ROOT}/src/secondTierConfig.json"


def _run(cmd, cwd=None):
    logger.info(f"RUN: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"FAILED: {result.stderr[-2000:]}")
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    logger.info(result.stdout[-500:])
    return result


US_REGIONS = {
    'AECI',#'AL',
    'AZPS','BANC','BPAT','CISO','DOPD','DUK','EPE','ERCO','FMPP','FPC','FPL',
    'GCPD','GRID','IPCO','ISNE','LDWP','LGEE','MISO','NEVP','NWMT','NYIS','PACE','PACW',
    'PGE','PJM','PNM','PSCO','PSEI','SC','SCEG','SCL','SOCO','SPA','SRP','SWPP','TAL','TEC',
    'TEPC','TIDC','TPWR','TVA','WACM','WALC',
}

def step1_fetch_electricity(region):
    from CarbonCastRESTAPI.models import EmissionActual
    from django.utils import timezone as tz
    from datetime import timedelta

    latest = EmissionActual.objects.filter(region=region).order_by('-ts').first()
    if latest and (tz.now() - latest.ts) < timedelta(hours=6):
        logger.info(f"[{region}] EmissionActual already fresh (latest: {latest.ts}) — skipping fetch")
        return

    logger.info(f"=== Step 1: Fetch generation data for {region} ===")
    if region in US_REGIONS:
        from CarbonCastRESTAPI.services import eia_service
        eia_service.EIA_BAL_AUTH_LIST = [region]
        for i in range(2, -1, -1):
            d = (date.today() - timedelta(days=i)).isoformat()
            result = eia_service.fetch_and_store_eia_data(d)
            logger.info(f"  {d}: {result}")
    elif region == "GB":
        from CarbonCastRESTAPI.services import neso_service
        for i in range(2, -1, -1):
            d = (date.today() - timedelta(days=i)).isoformat()
            result = neso_service.fetch_and_store_neso_data(d)
            logger.info(f"  {d}: {result}")
    else:
        from CarbonCastRESTAPI.services import entsoe_service
        entsoe_service.ENTSOE_TARGET_REGIONS = [region]
        for i in range(2, -1, -1):
            d = (date.today() - timedelta(days=i)).isoformat()
            result = entsoe_service.fetch_and_store_entsoe_data(d)
            logger.info(f"  {d}: {result}")

def step2_fetch_weather(region):
    import os
    from datetime import date

    # Skip ONLY if we already have a complete, fresh NOMADS pull for ALL required variables
    all_vars = ["temp", "wind", "dswrf", "rain"]
    today_str = date.today().strftime("%Y%m%d")
    all_fresh_and_complete = True

    for var in all_vars:
        check_dir = f"{WEATHER_DOWNLOADS_DIR}/{region}/{var}"
        if not os.path.isdir(check_dir):
            all_fresh_and_complete = False
            break
        gribs = [f for f in os.listdir(check_dir) if f.endswith(".grib2")]
        # We expect ~56-57 grib files per variable for a full 168-hour forecast
        if len(gribs) < 50:
            all_fresh_and_complete = False
            break
        latest_cycle = max(f.split(".")[2][:8] for f in gribs)
        if latest_cycle != today_str:
            all_fresh_and_complete = False
            break

    if all_fresh_and_complete:
        logger.info(f"[{region}] NOMADS data for today's cycle ({today_str}) already complete for all variables — skipping fetch")
        return

    logger.info(f"[{region}] NOMADS data is missing, incomplete, or stale — fetching via fetch_grib_nomads.py")
    script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "fetch_grib_nomads.py"
    )
    _run([PYTHON_BIN, script, "--region", region])


def step3_process_weather(region):
    logger.info(f"=== Step 3: GRIB2 -> wide CSVs for {region} ===")
    script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "process_weekly_weather.py"
    )
    _run([PYTHON_BIN, script, "--region", region])


def step4_expand_merge_reshape(region):
    logger.info(f"=== Step 4: expand/merge/reshape weather for {region} ===")
    raw_dir = f"{CARBONCAST_ROOT}/realtime_weather_processed/{region}"
    staging_dir = f"{raw_dir}/hourly_staging"
    os.makedirs(staging_dir, exist_ok=True)

    _run([PYTHON_BIN, "expand_weather_to_hourly.py",
          f"{raw_dir}/{region}_AVG_TEMP.csv", f"{staging_dir}/{region}_temp_hourly.csv", "temp", "fcst"],
         cwd=AUTOMATION_TOOL_PROCESSED_DATA)
    _run([PYTHON_BIN, "expand_weather_to_hourly.py",
          f"{raw_dir}/{region}_AVG_DPT.csv", f"{staging_dir}/{region}_dpt_hourly.csv", "dpt", "fcst"],
         cwd=AUTOMATION_TOOL_PROCESSED_DATA)
    _run([PYTHON_BIN, "expand_weather_to_hourly.py",
          f"{raw_dir}/{region}_AVG_WIND_SPEED.csv", f"{staging_dir}/{region}_wind_hourly.csv", "wind_speed", "fcst"],
         cwd=AUTOMATION_TOOL_PROCESSED_DATA)
    _run([PYTHON_BIN, "expand_weather_to_hourly.py",
          f"{raw_dir}/{region}_AVG_DSWRF.csv", f"{staging_dir}/{region}_dswrf_hourly.csv", "dswrf", "avg"],
         cwd=AUTOMATION_TOOL_PROCESSED_DATA)
    _run([PYTHON_BIN, "expand_weather_to_hourly.py",
          f"{raw_dir}/{region}_AVG_PCP.csv", f"{staging_dir}/{region}_precip_hourly.csv", "precip", "acc"],
         cwd=AUTOMATION_TOOL_PROCESSED_DATA)

    merged = f"{staging_dir}/{region}_weather_merged.csv"
    _run([PYTHON_BIN, "merge_hourly_weather.py", region, merged,
          f"{staging_dir}/{region}_temp_hourly.csv",
          f"{staging_dir}/{region}_dpt_hourly.csv",
          f"{staging_dir}/{region}_dswrf_hourly.csv",
          f"{staging_dir}/{region}_wind_hourly.csv",
          f"{staging_dir}/{region}_precip_hourly.csv"],
         cwd=AUTOMATION_TOOL_PROCESSED_DATA)

    return merged


def step5_stage_all(region, merged_weather_csv, forecast_start=None):
    logger.info(f"=== Step 5: stage weather + electricity + CI emissions for {region} ===")
    from CarbonCastRESTAPI.models import EmissionActual
    from django.utils import timezone as tz
    from CarbonCastRESTAPI.services.weather_fetch.stage_electricity_for_inference import stage_electricity
    from CarbonCastRESTAPI.services.weather_fetch.stage_ci_emissions_for_inference import stage_ci_emissions

    import pandas as pd
    import os
    from datetime import datetime, timezone, timedelta, date

    # --- Staleness check: warn if older than 48h, but proceed with latest available ---
    latest = EmissionActual.objects.filter(region=region).order_by('-ts').first()
    if not latest:
        raise ValueError(f"EmissionActual for {region} is missing.")
    if (tz.now() - latest.ts) > timedelta(hours=48):
        logger.warning(
            f"[{region}] Grid actuals are from {latest.ts} (>48h ago). "
            f"Using latest available actual data as fallback."
        )

    today = (forecast_start.date() if forecast_start else date.today())
    yesterday = today - timedelta(days=1)

    WEATHER_COLUMN_ORDER = ["wind_speed", "temp", "dpt", "dswrf", "precip"]
    df = pd.read_csv(merged_weather_csv, parse_dates=["datetime"])
    df = df.drop(columns=["region"], errors="ignore")
    df = df[["datetime"] + WEATHER_COLUMN_ORDER]
    creation_time = datetime.now(timezone.utc).isoformat()
    df.insert(1, "creation_time (UTC)", creation_time)
    df.insert(2, "version", "weather-stage-v1")
    out_dir = os.path.join(WEATHER_STAGE_DIR, region)
    os.makedirs(out_dir, exist_ok=True)
    weather_out = os.path.join(out_dir, f"{region}_weather_forecast_{today.isoformat()}.csv")
    df.to_csv(weather_out, index=False)
    logger.info(f"Staged weather -> {weather_out}")

    # Stage up to 14 days back so the ML inference path can find a full 24h electricity window
    for days_back in range(1, 15):
        d_str = (today - timedelta(days=days_back)).isoformat()
        try:
            stage_electricity(region, d_str, ELECTRICITY_STAGE_DIR)
            stage_ci_emissions(region, d_str, ELECTRICITY_STAGE_DIR)
            logger.info(f"[{region}] Staged electricity & emissions for {d_str}")
        except Exception as e:
            logger.debug(f"[{region}] Staging {d_str} skipped: {e}")

    # Also explicitly stage the latest available date from EmissionActual if present
    if latest:
        latest_d_str = latest.ts.date().isoformat()
        try:
            stage_electricity(region, latest_d_str, ELECTRICITY_STAGE_DIR)
            stage_ci_emissions(region, latest_d_str, ELECTRICITY_STAGE_DIR)
            logger.info(f"[{region}] Staged fallback electricity & emissions for {latest_d_str}")
        except Exception as e:
            logger.debug(f"[{region}] Fallback staging {latest_d_str} skipped: {e}")

    fuel_forecast_dir = os.path.join(ELECTRICITY_STAGE_DIR, region, "fuel_forecast")
    os.makedirs(fuel_forecast_dir, exist_ok=True)

def step6_run_retraining(region,forecast_start=None):
    logger.info(f"=== Step 6: run retraining/ML inference for {region} ===")
    os.environ["CARBONCAST_RUN_ML"] = "true"
    os.environ["CARBONCAST_CONFIG_FILE"] = FIRST_TIER_CONFIG
    os.environ["CARBONCAST_SECOND_TIER_CONFIG_FILE"] = SECOND_TIER_CONFIG
    os.environ["CARBONCAST_REAL_TIME_DIR"] = ELECTRICITY_STAGE_DIR + "/"
    os.environ["CARBONCAST_REAL_TIME_WEATHER_DIR"] = WEATHER_STAGE_DIR + "/"
    os.environ["PIPELINE_REGIONS"] = region

    from CarbonCastRESTAPI.services.retraining_service import run_retraining
    if forecast_start:
        os.environ["CARBONCAST_FORECAST_START_OVERRIDE"] = forecast_start.isoformat()
    from CarbonCastRESTAPI.services.retraining_service import run_retraining
    result = run_retraining()
    logger.info(f"Retraining result: {result}")
    return result


def run_pipeline(region, forecast_start=None):
    logger.info(f"##### STARTING FULL PIPELINE FOR {region} #####")

    step1_fetch_electricity(region)  # attempts to refresh EmissionActual

    # --- Check actuals exist ---
    from CarbonCastRESTAPI.models import EmissionActual
    from django.utils import timezone as tz
    from datetime import timedelta

    latest = EmissionActual.objects.filter(region=region).order_by('-ts').first()
    if not latest:
        raise ValueError(f"EmissionActual for {region} is missing after fetch attempt.")
    if (tz.now() - latest.ts) > timedelta(hours=96):
        logger.warning(
            f"EmissionActual for {region} is from {latest.ts} (>96h ago). "
            f"Proceeding with latest available grid data as fallback."
        )

    step2_fetch_weather(region)
    step3_process_weather(region)
    merged = step4_expand_merge_reshape(region)
    step5_stage_all(region, merged, forecast_start=forecast_start)
    result = step6_run_retraining(region, forecast_start=forecast_start)

    from CarbonCastRESTAPI.models import Forecast168
    count = Forecast168.objects.filter(region_code=region).count()
    logger.info(f"##### PIPELINE COMPLETE — Forecast168 rows for {region}: {count} #####")
    return result


ALL_68_REGIONS = [
    # 44 US Balancing Authorities
    'AECI', 'AZPS', 'BANC', 'BPAT', 'CISO', 'DOPD', 'DUK', 'EPE', 'ERCO',
    'FMPP', 'FPC', 'FPL', 'GCPD', 'GRID', 'IPCO', 'ISNE', 'LDWP', 'LGEE',
    'MISO', 'NEVP', 'NWMT', 'NYIS', 'PACE', 'PACW', 'PGE', 'PJM', 'PNM',
    'PSCO', 'PSEI', 'SC', 'SCEG', 'SCL', 'SOCO', 'SPA', 'SRP', 'SWPP',
    'TAL', 'TEC', 'TEPC', 'TIDC', 'TPWR', 'TVA', 'WACM', 'WALC',
    # European Regions
    'AT', 'BE', 'BG', 'CH', 'CZ', 'DE', 'DK', 'EE', 'ES', 'FI',
    'FR', 'GB', 'GR', 'HR', 'HU', 'IE', 'IT', 'LT', 'LV', 'NL', 'PL',
    'PT', 'RO', 'RS', 'SE', 'SI', 'SK'
]


def run_batch(regions=None, forecast_start=None):
    if regions is None:
        regions = ALL_68_REGIONS
    logger.info(f"Starting real-time batch inference for {len(regions)} regions...")
    success = []
    failed = {}

    for idx, region in enumerate(regions, 1):
        logger.info(f"\n[{idx}/{len(regions)}] >>> Processing {region} <<<")
        try:
            run_pipeline(region, forecast_start=forecast_start)
            success.append(region)
        except Exception as exc:
            logger.error(f"[{region}] Failed: {exc}")
            failed[region] = str(exc)

    logger.info(f"\n{'='*20} BATCH INFERENCE SUMMARY {'='*20}")
    logger.info(f"Successful: {len(success)} / {len(regions)}")
    logger.info(f"Failed: {len(failed)} / {len(regions)}")
    if failed:
        for r, err in failed.items():
            logger.warning(f"  {r}: {err}")
    return {'success': success, 'failed': failed}


if __name__ == "__main__":
    import argparse
    import django

    # Setup django environment if run directly
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "CarbonCastAPI.settings")
    django.setup()

    parser = argparse.ArgumentParser(description="Run real-time inference pipeline for CarbonCast.")
    parser.add_argument("--regions", nargs="+", default=None, help="Specific regions to run, or defaults to all 68.")
    args = parser.parse_args()

    res = run_batch(regions=args.regions)
    if res.get('failed') and not res.get('success'):
        sys.exit(1)