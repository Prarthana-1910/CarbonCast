"""
ENTSO-E (European Network of Transmission System Operators) ingestion.

Pulls actual generation per production type from ENTSO-E for European
control areas and writes hourly rows into EmissionActual using the same
schema as the EIA service. This complements EIA (US) so the daily
ingestion task can keep both regions current.

Requires ENTSOE_API_KEY env var. Uses entsoe-py if available; falls back
to a no-op (with logged error) so the rest of the pipeline keeps running.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

##########################################################################
# Mapping from ENTSOE fuel names to CarbonCast names
##########################################################################
FUEL_MAP = {
    "Biomass": "BIO",
    "Waste": "BIO",

    "Fossil Brown coal/Lignite": "COAL",
    "Fossil Hard coal": "COAL",
    "Fossil Coal-derived gas": "NG",
    "Fossil Gas": "NG",
    "Fossil Oil": "OIL",
    "Fossil Oil shale": "COAL",
    "Fossil Peat": "COAL",

    "Geothermal": "GEO",

    "Hydro Pumped Storage": "STOR",
    "Hydro Run-of-river and poundage": "HYD",
    "Hydro Water Reservoir": "HYD",

    "Marine": "UNK",

    "Nuclear": "NUC",

    "Other": "UNK",
    "Other renewable": "UNK",

    "Solar": "SOL",

    "Wind Offshore": "WND",
    "Wind Onshore": "WND",

    "Energy storage": "STOR",
}

##########################################################################
# PSR mapping (backup)
##########################################################################

# ENTSO-E generation type code -> our internal source name.
# Only codes that map onto EIA's source taxonomy are kept; everything else
# is bucketed into "other" so downstream emission factors stay consistent.
ENTSOE_PSR_TYPE_TO_SOURCE = {

    "B01":"biomass",
    "B02":"coal",
    "B03":"coal",
    "B04":"nat_gas",
    "B05":"coal",
    "B06":"oil",
    "B07":"oil",
    "B08":"coal",
    "B09":"geothermal",
    "B10":"hydro",
    "B11":"hydro",
    "B12":"hydro",
    "B13":"other",
    "B14":"nuclear",
    "B15":"other",
    "B16":"solar",
    "B17":"other",
    "B18":"wind",
    "B19":"wind",
    "B20":"other",
    "B25":"other",
}
SOURCE_MAP = {
    "BIO": "biomass",
    "COAL": "coal",
    "NG": "nat_gas",
    "OIL": "oil",
    "GEO": "geothermal",
    "HYD": "hydro",
    "NUC": "nuclear",
    "SOL": "solar",
    "WND": "wind",
    "UNK": "other",

    # storage isn't one of your output columns,
    # so map it wherever you want
    "STOR": "hydro",      # recommended
    # or
    # "STOR": "other"
}

# Region code (our internal) -> ENTSO-E control area EIC code.
# Trimmed to the regions we already serve in `consts.US_region_codes`.

##########################################################################
# Area codes
##########################################################################

ENTSOE_AREA_CODES = {
    "AT":"10YAT-APG------L",
    "BE":"10YBE----------2",
    "BG":"10YCA-BULGARIA-R",
    "CH":"10YCH-SWISSGRIDZ",
    "CZ":"10YCZ-CEPS-----N",
    "DE":"10Y1001A1001A83F",
    "DK":"10Y1001A1001A65H",
    "EE":"10Y1001A1001A39I",
    "ES":"10YES-REE------0",
    "FI":"10YFI-1--------U",
    "FR":"10YFR-RTE------C",
    "GR":"10YGR-HTSO-----Y",
    "HR":"10YHR-HEP------M",
    "HU":"10YHU-MAVIR----U",
    "IE":"10YIE-1001A00010",
    "IT":"10YIT-GRTN-----B",
    "LT":"10YLT-1001A0008Q",
    "LV":"10YLV-1001A00074",
    "NL":"10YNL----------L",
    "PL":"10YPL-AREA-----S",
    "PT":"10YPT-REN------W",
    "RO":"10YRO-TEL------P",
    "RS":"10YCS-SERBIATSOV",
    "SE":"10YSE-1--------K",
    "SI":"10YSI-ELES-----O",
    "SK":"10YSK-SEPS-----K",
}



ENTSOE_TARGET_REGIONS = None

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


def _calculate_carbon_intensity(sources, factors):
    total_generation = 0.0
    total_emissions = 0.0
    for source, generation in sources.items():
        if generation is None:
            continue
        try:
            value = float(generation)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        total_generation += value
        total_emissions += value * factors.get(source, factors["unknown"])
    if total_generation <= 0:
        return None
    return total_emissions / total_generation


def _coerce_datetime(value):
    """Normalize an ENTSO-E pandas Timestamp / datetime into tz-aware UTC."""
    if value is None:
        return None
    if hasattr(value, 'to_pydatetime'):
        value = value.to_pydatetime()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def fetch_and_store_entsoe_data(target_date: str) -> dict:
    """
    Fetch generation per production type for `target_date` (YYYY-MM-DD)
    across all configured ENTSO-E control areas and upsert into
    EmissionActual.
    """
    from CarbonCastRESTAPI.models import EmissionActual

    api_key = os.environ.get("ENTSOE_API_KEY", "")
    if not api_key:
        logger.warning("ENTSOE_API_KEY not set; skipping ENTSO-E ingestion")
        return {"inserted": 0, "updated": 0, "errors": 0, "skipped": True}

    try:
        import pandas as pd  # noqa: F401  (used by entsoe-py)
        from entsoe import EntsoePandasClient
    except ImportError:
        logger.exception("entsoe-py not installed; skipping ENTSO-E ingestion")
        return {"inserted": 0, "updated": 0, "errors": 0, "skipped": True}

    import pandas as pd

    client = EntsoePandasClient(api_key=api_key)
    start = pd.Timestamp(f"{target_date}T00:00", tz="UTC")
    end = start + pd.Timedelta(days=1)

    inserted = 0
    updated = 0
    errors = 0

    target_regions = ENTSOE_TARGET_REGIONS if ENTSOE_TARGET_REGIONS else ENTSOE_AREA_CODES.keys()
    for region_code, area_code in ENTSOE_AREA_CODES.items():
        if region_code not in target_regions:
            continue
        try:
            df = client.query_generation(area_code, start=start, end=end, psr_type=None)
            if df is None or df.empty:
                continue

            # ENTSO-E returns a multi-index column DataFrame (psr_type, direction).
            # Flatten to one column per psr_type using "Actual Aggregated" generation.
            if isinstance(df.columns, pd.MultiIndex):
                try:
                    df = df.xs("Actual Aggregated", axis=1, level=-1)
                except KeyError:
                    df = df.droplevel(-1, axis=1)

            # Resample raw resolution (15min/30min/60min) into hourly means in MW.
            df = df.resample("h").mean()

            for ts, row in df.iterrows():
                ts_utc = _coerce_datetime(ts)
                if ts_utc is None:
                    continue

                sources = {}
                for psr, value in row.items():
                    if value is None or (isinstance(value, float) and value != value):
                        continue

                    # Resolve column name to CarbonCast source name.
                    # entsoe-py returns either B-codes ("B16"), human-readable
                    # fuel names ("Solar"), or tuples depending on country/version.
                    # Try all paths so wrong values are not silently bucketed as "other".
                    psr_str = str(psr)
                    source_name = None

                    # 1. Tuple column (MultiIndex not fully flattened)
                    if isinstance(psr, tuple):
                        for part in psr:
                            part_str = str(part)
                            if part_str in FUEL_MAP:
                                source_name = SOURCE_MAP.get(FUEL_MAP[part_str], "other")
                                break
                            if part_str in ENTSOE_PSR_TYPE_TO_SOURCE:
                                source_name = ENTSOE_PSR_TYPE_TO_SOURCE[part_str]
                                break

                    # 2. Human-readable fuel name string ("Solar", "Fossil Gas", …)
                    if source_name is None and psr_str in FUEL_MAP:
                        source_name = SOURCE_MAP.get(FUEL_MAP[psr_str], "other")

                    # 3. B-code ("B16", "B04", …)
                    if source_name is None:
                        source_name = ENTSOE_PSR_TYPE_TO_SOURCE.get(psr_str, "other")

                    sources[source_name] = sources.get(source_name, 0.0) + max(float(value), 0.0)

                if not sources:
                    continue

                lifecycle = _calculate_carbon_intensity(sources, LIFECYCLE_EMISSION_FACTORS)
                direct = _calculate_carbon_intensity(sources, DIRECT_EMISSION_FACTORS)

                _, created = EmissionActual.objects.update_or_create(
                    region=region_code,
                    ts=ts_utc,
                    defaults={
                        "lifecycle": lifecycle,
                        "direct": direct,
                        "data": {
                            **sources,
                            "creation_time (UTC)": datetime.utcnow().isoformat(),
                            "version": "entsoe_api",
                            "carbon_intensity_avg_lifecycle": lifecycle,
                            "carbon_intensity_avg_direct": direct,
                            "carbon_intensity_unit": "gCO2eg/kWh",
                            "source": "entsoe",
                        },
                        "source_file": f"entsoe_api_{target_date}",
                    },
                )
                if created:
                    inserted += 1
                else:
                    updated += 1

        except Exception:
            logger.exception("ENTSO-E fetch failed for %s on %s", region_code, target_date)
            errors += 1

    return {"inserted": inserted, "updated": updated, "errors": errors, "skipped": False}
