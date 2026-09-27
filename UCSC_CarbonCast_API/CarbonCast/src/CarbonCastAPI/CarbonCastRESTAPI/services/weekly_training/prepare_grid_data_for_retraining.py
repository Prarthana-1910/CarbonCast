#!/usr/bin/env python3
"""
prepare_grid_data_for_retraining.py  (weekly_training edition)

Grid-data pipeline for the WEEKLY RETRAINING cycle.

Key difference from the weather_fetch edition:
  - export_training_csvs() APPENDS new rows to the existing CSVs instead of
    overwriting them.  It reads the last "UTC time" already present in each
    file and only writes DB rows whose timestamp is strictly after that point.
  - All other logic (backfill, verify, REGION_SOURCES) is identical.

Flow:
  1. backfill_region()      — fetch new days from EIA/ENTSO-E into EmissionActual
  2. verify_region()        — report completeness
  3. export_training_csvs() — APPEND only the new rows to existing CSVs

Does NOT delete existing CSV data — safe to re-run.

Usage (Django shell):
    from CarbonCastRESTAPI.services.weekly_training.prepare_grid_data_for_retraining import run
    run('AECI', days_back=7)
"""
import os
import csv
import logging
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger("prepare_grid_data_weekly")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

US_REGIONS = {
    'AECI', 'AZPS', 'BANC', 'BPAT', 'CISO', 'DOPD', 'DUK', 'EPE', 'ERCO',
    'FMPP', 'FPC', 'FPL', 'GCPD', 'GRID', 'IPCO', 'ISNE', 'LDWP', 'LGEE',
    'MISO', 'NEVP', 'NWMT', 'NYIS', 'PACE', 'PACW', 'PGE', 'PJM', 'PNM',
    'PSCO', 'PSEI', 'SC', 'SCEG', 'SCL', 'SOCO', 'SPA', 'SRP', 'SWPP',
    'TAL', 'TEC', 'TEPC', 'TIDC', 'TPWR', 'TVA', 'WACM', 'WALC',
}

REGION_SOURCES = {
    "AECI": ['coal', 'nat_gas', 'wind'],
    "AT": ['biomass', 'nat_gas', 'geothermal', 'hydro', 'solar', 'wind', 'other'],
    "AZPS": ['coal', 'nat_gas', 'nuclear', 'oil', 'hydro', 'solar', 'wind', 'other'],
    "BANC": ['nat_gas', 'hydro', 'solar', 'other'],
    "BE": ['biomass', 'nat_gas', 'hydro', 'nuclear', 'oil', 'solar', 'wind', 'other'],
    "BG": ['biomass', 'coal', 'nat_gas', 'hydro', 'nuclear', 'solar', 'wind'],
    "BPAT": ['nat_gas', 'nuclear', 'hydro', 'solar', 'wind', 'other'],
    "CH": ['hydro', 'nuclear', 'solar', 'wind'],
    "CISO": ['coal', 'nat_gas', 'nuclear', 'oil', 'hydro', 'solar', 'wind', 'other'],
    "CZ": ['biomass', 'coal', 'nat_gas', 'hydro', 'nuclear', 'oil', 'solar', 'wind', 'other'],
    "DE": ['biomass', 'coal', 'nat_gas', 'geothermal', 'hydro', 'oil', 'solar', 'wind', 'other'],
    "DK": ['biomass', 'coal', 'nat_gas', 'oil', 'solar', 'wind'],
    "DOPD": ['hydro'],
    "DUK": ['coal', 'nat_gas', 'nuclear', 'hydro', 'solar', 'other'],
    "EE": ['biomass', 'coal', 'nat_gas', 'hydro', 'solar', 'wind', 'other'],
    "EPE": ['nat_gas', 'solar'],
    "ERCO": ['coal', 'nat_gas', 'nuclear', 'hydro', 'solar', 'wind', 'other'],
    "ES": ['biomass', 'coal', 'nat_gas', 'hydro', 'nuclear', 'oil', 'solar', 'wind', 'other'],
    "FI": ['biomass', 'coal', 'nat_gas', 'hydro', 'nuclear', 'oil', 'solar', 'wind', 'other'],
    "FMPP": ['coal', 'nat_gas', 'nuclear', 'oil', 'other', 'solar'],
    "FPC": ['coal', 'nat_gas', 'oil', 'hydro', 'solar', 'other'],
    "FPL": ['nat_gas', 'nuclear', 'oil', 'solar', 'other'],
    "FR": ['biomass', 'coal', 'nat_gas', 'hydro', 'nuclear', 'oil', 'solar', 'wind'],
    "GB": ['biomass', 'coal', 'nat_gas', 'hydro', 'nuclear', 'solar', 'wind', 'other'],
    "GCPD": ['hydro'],
    "GR": ['coal', 'nat_gas', 'hydro', 'solar', 'wind'],
    "GRID": ['coal', 'nat_gas', 'solar', 'wind'],
    "HR": ['biomass', 'coal', 'nat_gas', 'geothermal', 'hydro', 'oil', 'solar', 'wind', 'other'],
    "HU": ['biomass', 'coal', 'nat_gas', 'geothermal', 'hydro', 'nuclear', 'oil', 'solar', 'wind', 'other'],
    "IE": ['coal', 'nat_gas', 'hydro', 'oil', 'wind', 'other'],
    "IPCO": ['nat_gas', 'oil', 'hydro', 'solar', 'wind', 'other'],
    "ISNE": ['coal', 'nat_gas', 'nuclear', 'oil', 'hydro', 'solar', 'wind', 'other'],
    "IT": ['biomass', 'coal', 'nat_gas', 'geothermal', 'hydro', 'oil', 'solar', 'wind', 'other'],
    "LDWP": ['coal', 'nat_gas', 'hydro', 'solar', 'wind', 'other'],
    "LGEE": ['coal', 'nat_gas', 'hydro', 'oil', 'solar'],
    "LT": ['biomass', 'nat_gas', 'hydro', 'solar', 'wind', 'other'],
    "LV": ['biomass', 'nat_gas', 'hydro', 'solar', 'wind', 'other'],
    "MISO": ['coal', 'nat_gas', 'nuclear', 'hydro', 'solar', 'wind', 'other'],
    "NEVP": ['coal', 'nat_gas', 'nuclear', 'oil', 'hydro', 'solar', 'wind', 'other'],
    "NL": ['biomass', 'coal', 'nat_gas', 'nuclear', 'solar', 'wind', 'other'],
    "NWMT": ['coal', 'nat_gas', 'oil', 'hydro', 'solar', 'wind'],
    "NYIS": ['coal', 'nat_gas', 'nuclear', 'oil', 'hydro', 'solar', 'wind', 'other'],
    "PACE": ['coal', 'nat_gas', 'hydro', 'solar', 'wind', 'other'],
    "PACW": ['nat_gas', 'hydro', 'solar', 'wind', 'other'],
    "PGE": ['coal', 'nat_gas', 'wind', 'hydro', 'other'],
    "PJM": ['coal', 'nat_gas', 'nuclear', 'oil', 'hydro', 'solar', 'wind', 'other'],
    "PL": ['biomass', 'coal', 'nat_gas', 'hydro', 'oil', 'solar', 'wind', 'other'],
    "PNM": ['coal', 'nat_gas', 'wind', 'hydro', 'solar', 'other'],
    "PSCO": ['coal', 'nat_gas', 'oil', 'hydro', 'solar', 'wind', 'other'],
    "PSEI": ['coal', 'nat_gas', 'oil', 'hydro', 'solar', 'wind', 'other'],
    "PT": ['biomass', 'nat_gas', 'hydro', 'solar', 'wind', 'other'],
    "RO": ['biomass', 'nat_gas', 'hydro', 'nuclear', 'solar', 'wind'],
    "RS": ['biomass', 'coal', 'nat_gas', 'hydro', 'wind', 'other'],
    "SC": ['coal', 'nat_gas', 'oil', 'hydro', 'solar', 'other'],
    "SCEG": ['coal', 'nat_gas', 'nuclear', 'hydro', 'solar', 'other'],
    "SCL": ['hydro'],
    "SE": ['nat_gas', 'hydro', 'nuclear', 'solar', 'wind', 'other'],
    "SI": ['biomass', 'coal', 'nat_gas', 'hydro', 'nuclear', 'oil', 'solar', 'wind', 'other'],
    "SK": ['biomass', 'coal', 'nat_gas', 'hydro', 'nuclear', 'oil', 'solar', 'wind', 'other'],
    "SOCO": ['coal', 'nat_gas', 'nuclear', 'oil', 'solar', 'wind', 'other'],
    "SPA": ['hydro'],
    "SRP": ['coal', 'nat_gas', 'nuclear', 'hydro', 'solar', 'wind', 'other'],
    "SWPP": ['coal', 'nat_gas', 'nuclear', 'oil', 'hydro', 'solar', 'wind', 'other'],
    "TAL": ['nat_gas', 'solar'],
    "TEC": ['coal', 'nat_gas', 'other', 'oil', 'solar'],
    "TEPC": ['coal', 'nat_gas', 'solar', 'wind', 'other'],
    "TIDC": ['nat_gas', 'hydro'],
    "TPWR": ['hydro'],
    "TVA": ['coal', 'nat_gas', 'nuclear', 'oil', 'hydro', 'solar', 'wind', 'other'],
    "WACM": ['coal', 'nat_gas', 'hydro', 'solar', 'wind'],
    "WALC": ['nat_gas', 'hydro', 'solar', 'wind'],
}

TRAINING_DATA_ROOT = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/data"

# Timestamp formats stored in the CSV "UTC time" column
_TS_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S")


def _read_last_ts(csv_path):
    """
    Return the latest datetime in the 'UTC time' column of an existing CSV,
    or None if the file does not exist / is empty.
    Returned datetime is timezone-aware (UTC).
    """
    if not os.path.exists(csv_path):
        return None

    last_ts = None
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_str = row.get("UTC time", "").strip()
            if not ts_str:
                continue
            for fmt in _TS_FORMATS:
                try:
                    dt = datetime.strptime(ts_str, fmt).replace(tzinfo=timezone.utc)
                    if last_ts is None or dt > last_ts:
                        last_ts = dt
                    break
                except ValueError:
                    continue
    return last_ts


def reset_region(region):
    """Optional — call explicitly if you want a clean slate before backfilling."""
    from CarbonCastRESTAPI.models import EmissionActual
    count = EmissionActual.objects.filter(region=region).count()
    deleted, _ = EmissionActual.objects.filter(region=region).delete()
    logger.info(f"[{region}] Deleted {deleted} existing rows (had {count})")


def backfill_region(region, days_back, eia_api_key="Qc8vFrBgZhLdtFVurGbxHbCrvyP93RoPXVhKfCGx", entsoe_api_key="3d8580df-94bb-4d1f-9854-50b736a39858"):
    if region in US_REGIONS:
        from CarbonCastRESTAPI.services import eia_service
        if eia_api_key:
            os.environ["EIA_API_KEY"] = eia_api_key
        eia_service.EIA_BAL_AUTH_LIST = [region]
        fetch_fn = eia_service.fetch_and_store_eia_data
    else:
        from CarbonCastRESTAPI.services import entsoe_service
        if entsoe_api_key:
            os.environ["ENTSOE_API_KEY"] = entsoe_api_key
        entsoe_service.ENTSOE_TARGET_REGIONS = [region]
        fetch_fn = entsoe_service.fetch_and_store_entsoe_data

    for i in range(days_back, -1, -1):
        d = (date.today() - timedelta(days=i)).isoformat()
        try:
            result = fetch_fn(d)
            logger.info(f"[{region}] {d}: {result}")
        except Exception as exc:
            logger.error(f"[{region}] {d}: FAILED — {exc}")


def verify_region(region):
    from CarbonCastRESTAPI.models import EmissionActual
    from django.db.models.functions import TruncDate
    from django.db.models import Count

    qs = (
        EmissionActual.objects.filter(region=region)
        .annotate(day=TruncDate('ts'))
        .values('day')
        .annotate(count=Count('id'))
        .order_by('day')
    )
    total_days = qs.count()
    incomplete = [r for r in qs if r['count'] < 24]

    logger.info(f"[{region}] {total_days} days present, {len(incomplete)} incomplete")
    for r in incomplete:
        logger.info(f"  [{region}] {r['day']}: {r['count']} rows")

    return {'total_days': total_days, 'incomplete_days': len(incomplete)}


def export_training_csvs(region):
    """
    APPEND-mode export for the weekly retraining cycle.

    For each output CSV:
      - Reads the last 'UTC time' already present in the file.
      - Queries EmissionActual only for rows strictly AFTER that timestamp.
      - Appends those rows without touching existing data.
      - If the CSV does not exist yet, creates it with header + all DB rows
        (first-run / fresh environment behaviour).

    Writes:
      - data/{region}/fuel_forecast/{region}_{source}_clean.csv  (tier 1)
      - data/{region}/{region}_direct_emissions.csv              (tier 2)
      - data/{region}/{region}_lifecycle_emissions.csv           (tier 2)
    """
    from CarbonCastRESTAPI.models import EmissionActual

    sources = REGION_SOURCES.get(region)
    if not sources:
        raise ValueError(
            f"No SOURCES list defined for {region} in REGION_SOURCES — "
            f"add it (matching firstTierConfig.json's SOURCES for this region) before exporting."
        )

    region_dir = os.path.join(TRAINING_DATA_ROOT, region)
    fuel_forecast_dir = os.path.join(region_dir, "fuel_forecast")
    os.makedirs(fuel_forecast_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # tier 1: one file per fuel source
    # ------------------------------------------------------------------
    for source in sources:
        out_path = os.path.join(fuel_forecast_dir, f"{region}_{source}_clean.csv")
        last_ts = _read_last_ts(out_path)
        file_exists = os.path.exists(out_path)

        if last_ts is not None:
            new_rows = list(
                EmissionActual.objects.filter(region=region, ts__gt=last_ts).order_by('ts')
            )
            logger.info(
                f"[{region}] {source}: last CSV ts={last_ts.strftime('%Y-%m-%d %H:%M')}, "
                f"{len(new_rows)} new DB rows to append"
            )
        else:
            new_rows = list(EmissionActual.objects.filter(region=region).order_by('ts'))
            logger.info(
                f"[{region}] {source}: no existing CSV — writing all {len(new_rows)} DB rows"
            )

        if not new_rows and file_exists:
            logger.info(f"[{region}] {source}: already up-to-date, nothing to append")
            continue

        if not new_rows and not file_exists:
            raise ValueError(
                f"No EmissionActual rows found for {region} and CSV does not exist — "
                f"backfill may have failed"
            )

        mode = "a" if (file_exists and last_ts is not None) else "w"
        with open(out_path, mode, newline="") as f:
            writer = csv.writer(f)
            if mode == "w":
                writer.writerow(["UTC time", source])
            for row in new_rows:
                data = row.data or {}
                value = data.get(source, "nan")
                writer.writerow([row.ts.strftime("%Y-%m-%d %H:%M:%S"), value])

        action = "Appended" if mode == "a" else "Wrote"
        logger.info(f"[{region}] {action} {len(new_rows)} rows -> {out_path}")

    # ------------------------------------------------------------------
    # tier 2: direct + lifecycle carbon intensity
    # ------------------------------------------------------------------
    for cef_type, field in (("direct", "direct"), ("lifecycle", "lifecycle")):
        out_path = os.path.join(region_dir, f"{region}_{cef_type}_emissions.csv")
        last_ts = _read_last_ts(out_path)
        file_exists = os.path.exists(out_path)

        if last_ts is not None:
            new_rows = list(
                EmissionActual.objects.filter(region=region, ts__gt=last_ts).order_by('ts')
            )
            logger.info(
                f"[{region}] {cef_type}_emissions: last CSV ts={last_ts.strftime('%Y-%m-%d %H:%M')}, "
                f"{len(new_rows)} new DB rows to append"
            )
        else:
            new_rows = list(EmissionActual.objects.filter(region=region).order_by('ts'))
            logger.info(
                f"[{region}] {cef_type}_emissions: no existing CSV — writing all {len(new_rows)} DB rows"
            )

        if not new_rows and file_exists:
            logger.info(f"[{region}] {cef_type}_emissions: already up-to-date, nothing to append")
            continue

        if not new_rows and not file_exists:
            raise ValueError(
                f"No EmissionActual rows found for {region} and CSV does not exist — "
                f"backfill may have failed"
            )

        mode = "a" if (file_exists and last_ts is not None) else "w"
        with open(out_path, mode, newline="") as f:
            writer = csv.writer(f)
            if mode == "w":
                writer.writerow(["UTC time", "carbon_intensity"])
            for row in new_rows:
                value = getattr(row, field)
                writer.writerow([
                    row.ts.strftime("%Y-%m-%d %H:%M:%S"),
                    value if value is not None else "nan"
                ])

        action = "Appended" if mode == "a" else "Wrote"
        logger.info(f"[{region}] {action} {len(new_rows)} rows -> {out_path}")


def run(region, days_back=7, eia_api_key="Qc8vFrBgZhLdtFVurGbxHbCrvyP93RoPXVhKfCGx", entsoe_api_key="3d8580df-94bb-4d1f-9854-50b736a39858"):
    logger.info(f"\n{'='*20} WEEKLY GRID DATA PIPELINE: {region} {'='*20}")
    backfill_region(region, days_back, eia_api_key=eia_api_key, entsoe_api_key=entsoe_api_key)
    verification = verify_region(region)
    export_training_csvs(region)

    logger.info(
        f"##### WEEKLY GRID DATA READY FOR {region} — "
        f"{verification['total_days']} days total, "
        f"{verification['incomplete_days']} incomplete #####"
    )
    return verification
