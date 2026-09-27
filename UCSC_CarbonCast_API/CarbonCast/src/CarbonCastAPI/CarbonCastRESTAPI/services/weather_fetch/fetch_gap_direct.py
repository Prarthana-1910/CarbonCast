#!/usr/bin/env python3
"""
fetch_gap_direct.py

Direct, single-region, date-range API calls (no service-file loops, no
day-by-day iteration). Auto-detects the actual gap in EmissionActual for
a region, fetches only that gap from EIA or ENTSO-E in a handful of
calls, computes direct/lifecycle CI, writes to CSV AND to EmissionActual.

Usage (Django shell):
    from CarbonCastRESTAPI.services.weather_fetch.fetch_gap_direct import run
    run('CISO', eia_api_key='YOUR_KEY')
    run('BE', entsoe_api_key='YOUR_KEY')
    run('CISO', end_date='2026-08-24', eia_api_key='YOUR_KEY')  # optional explicit end date

If a region has NO existing data at all, run() will warn and skip --
use run(region, start_date=..., end_date=...) for a full backfill instead.
"""
import os
import csv
import logging
import requests
import pandas as pd
from datetime import datetime, timezone, date, timedelta

logger = logging.getLogger("fetch_gap_direct")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

US_REGIONS = {
    'AECI', 'AZPS', 'BANC', 'BPAT', 'CISO', 'DOPD', 'DUK', 'EPE', 'ERCO',
    'FMPP', 'FPC', 'FPL', 'GCPD', 'GRID', 'IPCO', 'ISNE', 'LDWP', 'LGEE',
    'MISO', 'NEVP', 'NWMT', 'NYIS', 'PACE', 'PACW', 'PGE', 'PJM', 'PNM',
    'PSCO', 'PSEI', 'SC', 'SCEG', 'SCL', 'SOCO', 'SPA', 'SRP', 'SWPP',
    'TAL', 'TEC', 'TEPC', 'TIDC', 'TPWR', 'TVA', 'WACM', 'WALC',
}

EIA_SOURCE_MAP = {
    "OTH": "other", "COL": "coal", "SUN": "solar", "NG": "nat_gas",
    "NUC": "nuclear", "WND": "wind", "WAT": "hydro", "OIL": "oil",
    "SNB": "solar", "OES": "other", "WNB": "other", "UNK": "other",
    "UES": "other", "BAT": "other", "GEO": "other", "MWH": "other", "PS": "other",
}

ENTSOE_PSR_TYPE_TO_SOURCE = {
    "B01": "biomass", "B02": "coal", "B03": "coal", "B04": "coal",
    "B05": "coal", "B06": "oil", "B09": "geothermal",
    "B10": "hydro", "B11": "hydro", "B12": "hydro",
    "B14": "nuclear", "B15": "other", "B16": "solar",
    "B17": "coal", "B18": "coal", "B19": "wind", "B20": "other",
}

CARBON_RATE_DIRECT = {
    "coal": 760, "biomass": 0, "nat_gas": 370, "geothermal": 0,
    "hydro": 0, "nuclear": 0, "oil": 406, "solar": 0, "unknown": 575,
    "other": 575, "wind": 0,
}
CARBON_RATE_LIFECYCLE = {
    "coal": 820, "biomass": 230, "nat_gas": 490, "geothermal": 38,
    "hydro": 24, "nuclear": 12, "oil": 650, "solar": 45, "unknown": 700,
    "other": 700, "wind": 11,
}

CSV_OUT_DIR = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_OSRE_CC_automation_tool/eiaData_gapfill"


def _compute_ci(sources_mw):
    total = sum(sources_mw.values())
    if total <= 0:
        return None, None
    direct = sum((v / total) * CARBON_RATE_DIRECT.get(k, 575) for k, v in sources_mw.items())
    lifecycle = sum((v / total) * CARBON_RATE_LIFECYCLE.get(k, 700) for k, v in sources_mw.items())
    return round(direct, 5), round(lifecycle, 5)


def fetch_eia_range(region, start_date, end_date, api_key):
    """One region, full date range, paginated (5000 rows/page)."""
    url = "https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/"
    all_rows = []
    offset = 0
    length = 5000

    while True:
        params = {
            "api_key": api_key,
            "frequency": "hourly",
            "data[0]": "value",
            "facets[respondent][]": region,
            "start": f"{start_date}T00",
            "end": f"{end_date}T23",
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
            "offset": offset,
            "length": length,
        }
        resp = requests.get(url, params=params, timeout=60)
        resp.raise_for_status()
        payload = resp.json().get("response", {})
        rows = payload.get("data", [])
        all_rows.extend(rows)
        logger.info(f"[{region}] EIA fetched offset={offset}, got {len(rows)} rows (total: {len(all_rows)})")
        if len(rows) < length:
            break
        offset += length

    return all_rows


def fetch_entsoe_range(region, start_date, end_date, api_key):
    """One region (one area code), full date range, single client call."""
    from entsoe import EntsoePandasClient
    from CarbonCastRESTAPI.services.entsoe_service import ENTSOE_AREA_CODES

    area_code = ENTSOE_AREA_CODES.get(region)
    if not area_code:
        raise ValueError(f"No ENTSO-E area code found for region '{region}'")

    client = EntsoePandasClient(api_key=api_key)
    start = pd.Timestamp(f"{start_date}T00:00", tz="UTC")
    end = pd.Timestamp(f"{end_date}T23:59", tz="UTC")

    logger.info(f"[{region}] ENTSO-E fetching {start} -> {end} (single call)")
    df = client.query_generation(area_code, start=start, end=end, psr_type=None)
    if isinstance(df.columns, pd.MultiIndex):
        try:
            df = df.xs("Actual Aggregated", axis=1, level=-1)
        except KeyError:
            df = df.droplevel(-1, axis=1)
    df = df.resample("h").mean()
    return df


def process_and_save(region, hourly_data, is_eia):
    from CarbonCastRESTAPI.models import EmissionActual

    os.makedirs(CSV_OUT_DIR, exist_ok=True)
    csv_path = os.path.join(CSV_OUT_DIR, f"{region}_gapfill.csv")

    inserted, updated = 0, 0
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["UTC time", "direct", "lifecycle"])

        for ts, sources_mw in hourly_data.items():
            direct, lifecycle = _compute_ci(sources_mw)
            if direct is None:
                continue

            writer.writerow([ts.isoformat(), direct, lifecycle])

            data = {**sources_mw, "source": "eia_api" if is_eia else "entsoe_api",
                     "creation_time (UTC)": datetime.now(timezone.utc).isoformat(),
                     "carbon_intensity_avg_direct": direct,
                     "carbon_intensity_avg_lifecycle": lifecycle,
                     "carbon_intensity_unit": "gCO2eq/kWh"}

            _, created = EmissionActual.objects.update_or_create(
                region=region, ts=ts,
                defaults={"direct": direct, "lifecycle": lifecycle, "data": data,
                          "source_file": f"{region}_gapfill.csv"},
            )
            if created:
                inserted += 1
            else:
                updated += 1

    logger.info(f"[{region}] Saved {inserted} new, {updated} updated -> {csv_path}")
    return {"inserted": inserted, "updated": updated}


def _fetch_and_save(region, start_date, end_date, eia_api_key, entsoe_api_key):
    if region in US_REGIONS:
        key = eia_api_key or os.environ.get("EIA_API_KEY")
        if not key:
            raise ValueError("EIA_API_KEY required")
        raw_rows = fetch_eia_range(region, start_date, end_date, key)

        hourly = {}
        for row in raw_rows:
            period = row["period"]
            ts = pd.Timestamp(period, tz="UTC") if "T" in period else pd.Timestamp(f"{period}T00", tz="UTC")
            source = EIA_SOURCE_MAP.get(row.get("fueltype", ""), "other")
            value = float(row.get("value") or 0)
            hourly.setdefault(ts, {})
            hourly[ts][source] = hourly[ts].get(source, 0.0) + value

        return process_and_save(region, hourly, is_eia=True)

    else:
        key = entsoe_api_key or os.environ.get("ENTSOE_API_KEY")
        if not key:
            raise ValueError("ENTSOE_API_KEY required")
        df = fetch_entsoe_range(region, start_date, end_date, key)

        hourly = {}
        for ts, row in df.iterrows():
            sources = {}
            for psr, value in row.items():
                if value is None or (isinstance(value, float) and value != value):
                    continue
                source = ENTSOE_PSR_TYPE_TO_SOURCE.get(str(psr), "other")
                sources[source] = sources.get(source, 0.0) + max(float(value), 0.0)
            hourly[ts] = sources

        return process_and_save(region, hourly, is_eia=False)


def run(region, start_date=None, end_date=None, eia_api_key=None, entsoe_api_key=None):
    """
    If start_date is not given, auto-detects the gap: DB's latest ts + 1 day
    through end_date (default: today). If the region has no existing data
    at all, you must pass start_date explicitly.
    """
    from CarbonCastRESTAPI.models import EmissionActual
    from django.db.models import Max

    end_date = end_date or date.today().isoformat()

    if start_date is None:
        latest = EmissionActual.objects.filter(region=region).aggregate(Max('ts'))['ts__max']
        if not latest:
            logger.warning(f"[{region}] No existing data in DB — pass start_date explicitly for a full backfill")
            return None
        start_date = (latest.date() + timedelta(days=1)).isoformat()
        logger.info(f"[{region}] DB has data through {latest} — auto-detected gap: {start_date} -> {end_date}")

    if start_date > end_date:
        logger.info(f"[{region}] No gap to fill — already current through {start_date}")
        return {"inserted": 0, "updated": 0, "status": "already_current"}

    logger.info(f"##### DIRECT GAP FETCH: {region}, {start_date} -> {end_date} #####")
    return _fetch_and_save(region, start_date, end_date, eia_api_key, entsoe_api_key)