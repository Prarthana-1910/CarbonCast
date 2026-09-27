#!/usr/bin/env python3

"""
populate_emission_actual_from_csv.py

Loads existing *_clean_mod.csv files from eiaData/entsoeData
into EmissionActual.

For each row:
    - Calculates direct carbon intensity
    - Calculates lifecycle carbon intensity
    - Creates/updates the corresponding EmissionActual record

NO EIA API FETCHING
NO ENTSO-E API FETCHING
NO GAP FILLING

Usage (Django shell):

    from CarbonCastRESTAPI.services.weather_fetch.populate_emission_actual_from_csv import run

    run('PGE')

    run(['PGE', 'BE', 'CISO'])
"""

import os
import logging
import pandas as pd
from datetime import datetime, timezone

logger = logging.getLogger("populate_emission_actual_from_csv")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)


# ---------------------------------------------------------------------
# CSV DIRECTORIES
# ---------------------------------------------------------------------

EIA_DATA_DIR = (
    "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src/eiaData"
)

ENTSOE_DATA_DIR = (
    "/Users/prarthanapatil/Documents/EnergyAPI11/"
    "CarbonCast/UCSC_CarbonCast_API/CarbonCast/src/entsoeData"
)


# ---------------------------------------------------------------------
# CARBON EMISSION FACTORS
# ---------------------------------------------------------------------

CARBON_RATE_DIRECT = {
    "coal": 760,
    "biomass": 0,
    "nat_gas": 370,
    "geothermal": 0,
    "hydro": 0,
    "nuclear": 0,
    "oil": 406,
    "solar": 0,
    "unknown": 575,
    "other": 575,
    "wind": 0,
}


CARBON_RATE_LIFECYCLE = {
    "coal": 820,
    "biomass": 230,
    "nat_gas": 490,
    "geothermal": 38,
    "hydro": 24,
    "nuclear": 12,
    "oil": 650,
    "solar": 45,
    "unknown": 700,
    "other": 700,
    "wind": 11,
}


# ---------------------------------------------------------------------
# DATE COLUMN DETECTION
# ---------------------------------------------------------------------

DATE_COL_CANDIDATES = [
    "UTC time",
    "utc_time",
    "datetime",
    "date",
    "Date",
    "timestamp",
]


# ---------------------------------------------------------------------
# FIND CSV
# ---------------------------------------------------------------------

def _find_csv(region):
    """
    Find the existing CSV for a region.
    EIA regions are searched first, then ENTSO-E.
    """

    eia_path = os.path.join(
        EIA_DATA_DIR,
        f"{region}_clean_mod.csv"
    )

    entsoe_path = os.path.join(
        ENTSOE_DATA_DIR,
        f"{region}_clean_mod.csv"
    )

    if os.path.exists(eia_path):
        return eia_path

    if os.path.exists(entsoe_path):
        return entsoe_path

    return None


# ---------------------------------------------------------------------
# DETECT DATE COLUMN
# ---------------------------------------------------------------------

def _detect_date_col(df):

    for column in DATE_COL_CANDIDATES:
        if column in df.columns:
            return column

    return df.columns[0]


# ---------------------------------------------------------------------
# CALCULATE CARBON INTENSITY
# ---------------------------------------------------------------------

def _compute_ci(row, source_cols):

    total = sum(
        row[c]
        for c in source_cols
        if pd.notna(row[c])
    )

    if total <= 0:
        return None, None

    direct = sum(
        (row[c] / total)
        * CARBON_RATE_DIRECT.get(
            c.lower().strip(),
            CARBON_RATE_DIRECT["other"]
        )
        for c in source_cols
        if pd.notna(row[c])
    )

    lifecycle = sum(
        (row[c] / total)
        * CARBON_RATE_LIFECYCLE.get(
            c.lower().strip(),
            CARBON_RATE_LIFECYCLE["other"]
        )
        for c in source_cols
        if pd.notna(row[c])
    )

    return round(direct, 5), round(lifecycle, 5)


# ---------------------------------------------------------------------
# POPULATE DATABASE FROM CSV
# ---------------------------------------------------------------------

def populate_from_csv(region):

    from CarbonCastRESTAPI.models import EmissionActual

    csv_path = _find_csv(region)

    if not csv_path:
        logger.warning(
            f"[{region}] No _clean_mod.csv found "
            f"in eiaData/ or entsoeData/ — skipping"
        )
        return None

    logger.info(
        f"[{region}] Loading CSV: {csv_path}"
    )

    df = pd.read_csv(csv_path)

    logger.info(
        f"[{region}] CSV rows: {len(df)}"
    )

    # Detect timestamp column
    date_col = _detect_date_col(df)

    df[date_col] = pd.to_datetime(
        df[date_col],
        errors="coerce",
        utc=True
    )

    df = df.dropna(
        subset=[date_col]
    )

    # Detect generation source columns
    source_cols = [
        c
        for c in df.columns
        if c.lower().strip() in CARBON_RATE_DIRECT
    ]

    if not source_cols:

        logger.warning(
            f"[{region}] No recognized source columns."
        )

        logger.warning(
            f"[{region}] Columns: {list(df.columns)}"
        )

        return None

    logger.info(
        f"[{region}] Timestamp column: {date_col}"
    )

    logger.info(
        f"[{region}] Source columns: {source_cols}"
    )

    inserted = 0
    updated = 0
    skipped = 0

    # -------------------------------------------------------------
    # Process rows
    # -------------------------------------------------------------

    for _, row in df.iterrows():

        direct, lifecycle = _compute_ci(
            row,
            source_cols
        )

        if direct is None:
            skipped += 1
            continue

        # Generation/source data
        data = {
            c: float(row[c])
            for c in source_cols
            if pd.notna(row[c])
        }

        data.update({

            "source": "csv_bulk_load",

            "source_file": os.path.basename(
                csv_path
            ),

            "creation_time (UTC)": (
                datetime.now(timezone.utc)
                .isoformat()
            ),

            "carbon_intensity_avg_direct": direct,

            "carbon_intensity_avg_lifecycle": lifecycle,

            "carbon_intensity_unit": "gCO2eq/kWh",
        })

        # ---------------------------------------------------------
        # Create or update database record
        # ---------------------------------------------------------

        _, created = EmissionActual.objects.update_or_create(

            region=region,

            ts=row[date_col],

            defaults={

                "direct": direct,

                "lifecycle": lifecycle,

                "data": data,

                "source_file": os.path.basename(
                    csv_path
                ),
            },
        )

        if created:
            inserted += 1
        else:
            updated += 1

    # -------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------

    logger.info(
        f"[{region}] CSV load complete:"
    )

    logger.info(
        f"[{region}]   Inserted : {inserted}"
    )

    logger.info(
        f"[{region}]   Updated  : {updated}"
    )

    logger.info(
        f"[{region}]   Skipped  : {skipped}"
    )

    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
    }


# ---------------------------------------------------------------------
# MAIN RUN FUNCTION
# ---------------------------------------------------------------------

def run(regions):

    if isinstance(regions, str):
        regions = [regions]

    logger.info(
        f"Processing {len(regions)} region(s)"
    )

    for region in regions:

        logger.info(
            f"\n{'=' * 20} {region} {'=' * 20}"
        )

        try:

            populate_from_csv(region)

        except Exception as exc:

            logger.exception(
                f"[{region}] FAILED: {exc}"
            )

    logger.info(
        "\n##### CSV DATABASE POPULATION DONE #####"
    )