"""
NESO (National Energy System Operator, Great Britain) ingestion.

Pulls actual generation per production type from NESO's CKAN Data Portal API
for Great Britain (GB) and writes hourly rows into EmissionActual using the
same schema and carbon factors as EIA and ENTSO-E services.
"""

import logging
import os
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

RESOURCE_ID = "f93d1835-75bc-43e5-84ad-12472b180a98"
BASE_URL = "https://api.neso.energy/api/3/action/datastore_search_sql"
LIMIT = 10000

COLUMN_MAP = {
    "GAS": "nat_gas",
    "COAL": "coal",
    "NUCLEAR": "nuclear",
    "WIND": "wind",
    "HYDRO": "hydro",
    "SOLAR": "solar",
    "BIOMASS": "biomass",
    "OTHER": "other",
}

DIRECT_EMISSION_FACTORS = {
    "biomass": 0,
    "coal": 760,
    "geothermal": 0,
    "hydro": 0,
    "nat_gas": 370,
    "nuclear": 0,
    "oil": 406,
    "other": 575,
    "solar": 0,
    "unknown": 575,
    "wind": 0,
}

LIFECYCLE_EMISSION_FACTORS = {
    "biomass": 230,
    "coal": 820,
    "geothermal": 38,
    "hydro": 24,
    "nat_gas": 490,
    "nuclear": 12,
    "oil": 650,
    "other": 700,
    "solar": 45,
    "unknown": 700,
    "wind": 11,
}


def _calculate_ci(sources: Dict[str, float], factors: Dict[str, float]) -> Optional[float]:
    total_generation = sum(v for v in sources.values() if v is not None and v > 0)
    if total_generation <= 0:
        return None
    total_emissions = sum(
        v * factors.get(src, factors["unknown"])
        for src, v in sources.items()
        if v is not None and v > 0
    )
    return round(total_emissions / total_generation, 2)


def fetch_neso_records(start_iso: str, end_iso: str) -> List[Dict[str, Any]]:
    """Query NESO CKAN datastore for records between start_iso and end_iso."""
    offset = 0
    all_records = []

    while True:
        sql = f"""
        SELECT "DATETIME", "GAS", "COAL", "NUCLEAR", "WIND", "HYDRO", "SOLAR", "BIOMASS", "OTHER"
        FROM "{RESOURCE_ID}"
        WHERE "DATETIME" >= '{start_iso}'
          AND "DATETIME" <= '{end_iso}'
        ORDER BY "DATETIME"
        LIMIT {LIMIT}
        OFFSET {offset}
        """
        response = requests.get(BASE_URL, params={"sql": sql}, timeout=60)
        response.raise_for_status()
        result = response.json().get("result", {}).get("records", [])
        if not result:
            break
        all_records.extend(result)
        if len(result) < LIMIT:
            break
        offset += LIMIT

    return all_records


def process_records_to_hourly_df(records: List[Dict[str, Any]]) -> pd.DataFrame:
    """Convert raw NESO records into 1-hour averaged DataFrame with CarbonCast column names."""
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["DATETIME"] = pd.to_datetime(df["DATETIME"], utc=True)

    for col in COLUMN_MAP.keys():
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        else:
            df[col] = 0.0

    # Resample 30-min to 1-hour mean
    df = df.set_index("DATETIME")[list(COLUMN_MAP.keys())].resample("1h").mean().reset_index()
    df = df.rename(columns=COLUMN_MAP)
    return df


def upsert_hourly_df_to_db(df: pd.DataFrame) -> Dict[str, int]:
    """Upsert hourly DataFrame into Django EmissionActual."""
    from CarbonCastRESTAPI.models import EmissionActual

    if df.empty:
        return {"inserted": 0, "updated": 0, "skipped": 0}

    sources_list = list(COLUMN_MAP.values())
    inserted = 0
    updated = 0

    for _, row in df.iterrows():
        ts = row["DATETIME"].to_pydatetime()
        source_data = {s: float(row[s]) for s in sources_list}
        source_data["oil"] = 0.0
        source_data["geothermal"] = 0.0

        direct_ci = _calculate_ci(source_data, DIRECT_EMISSION_FACTORS)
        life_ci = _calculate_ci(source_data, LIFECYCLE_EMISSION_FACTORS)

        _, created = EmissionActual.objects.update_or_create(
            region="GB",
            ts=ts,
            metric_type="carbon",
            defaults={
                "lifecycle": life_ci,
                "direct": direct_ci,
                "source_file": "api.neso.energy",
                "data": source_data,
            }
        )
        if created:
            inserted += 1
        else:
            updated += 1

    return {"inserted": inserted, "updated": updated, "total": len(df)}


def fetch_and_store_neso_data(target_date: str) -> Dict[str, Any]:
    """
    Fetch generation for a single target_date (YYYY-MM-DD), resample to hourly,
    and upsert into EmissionActual. Matches eia_service / entsoe_service signature.
    """
    start_iso = f"{target_date}T00:00:00.000Z"
    end_dt = datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=1)
    end_iso = end_dt.strftime("%Y-%m-%dT00:00:00.000Z")

    logger.info(f"[GB] Fetching NESO generation for {target_date}")
    try:
        records = fetch_neso_records(start_iso, end_iso)
        df = process_records_to_hourly_df(records)
        res = upsert_hourly_df_to_db(df)
        logger.info(f"[GB] {target_date}: {res}")
        return res
    except Exception as exc:
        logger.error(f"[GB] Failed to fetch NESO data for {target_date}: {exc}")
        return {"inserted": 0, "updated": 0, "error": str(exc)}


def fetch_and_store_neso_range(start_date: str, end_date: str) -> Dict[str, Any]:
    """
    Fetch generation across a date range [start_date, end_date] (YYYY-MM-DD),
    resample to hourly, and upsert into EmissionActual.
    """
    start_iso = f"{start_date}T00:00:00.000Z"
    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    end_iso = end_dt.strftime("%Y-%m-%dT00:00:00.000Z")

    logger.info(f"[GB] Fetching NESO generation from {start_date} to {end_date}")
    records = fetch_neso_records(start_iso, end_iso)
    df = process_records_to_hourly_df(records)
    res = upsert_hourly_df_to_db(df)
    logger.info(f"[GB] Range {start_date} to {end_date}: {res}")
    return res
