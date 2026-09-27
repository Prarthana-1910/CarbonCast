#!/usr/bin/env python3
"""
fetch_retraining_grid_data.py

Backfills EIA generation data for a region across the same 90-day window
used for weather retraining data, then exports it into the format
firstTierForecasts.py/secondTierForecasts.py's offline training path expects.

Usage:
    python manage.py shell -c "
    from CarbonCastRESTAPI.services.weather_fetch.fetch_retraining_grid_data import run
    run('BANC', days_back=90)
    "
"""
import os
import csv
from datetime import date, timedelta, datetime, timezone


def backfill_emission_actual(region, days_back):
    from CarbonCastRESTAPI.services import eia_service
    eia_service.EIA_BAL_AUTH_LIST = [region]

    results = []
    for i in range(days_back, 0, -1):
        d = (date.today() - timedelta(days=i)).isoformat()
        result = eia_service.fetch_and_store_eia_data(d)
        results.append((d, result))
        print(f"{d}: {result}")
    return results


def export_training_csvs(region, output_dir):
    """
    Exports EmissionActual rows in the wide, per-source-column format
    firstTierForecasts.py's runFirstTier() reads via IN_FILE_NAME_PREFIX
    + '_clean.csv', and secondTierForecasts.py's runSecondTier() reads
    via *_direct_emissions.csv / *_lifecycle_emissions.csv.
    """
    from CarbonCastRESTAPI.models import EmissionActual

    SOURCES = ["coal", "nat_gas", "nuclear", "oil", "hydro", "solar", "wind", "other"]

    rows = EmissionActual.objects.filter(region=region).order_by('ts')
    if not rows.exists():
        raise ValueError(f"No EmissionActual rows found for {region}")

    os.makedirs(output_dir, exist_ok=True)

    # 1. Raw per-source generation CSV (for tier 1 training)
    clean_path = os.path.join(output_dir, f"{region}_clean.csv")
    with open(clean_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["UTC time"] + SOURCES)
        for row in rows:
            data = row.data or {}
            writer.writerow([row.ts.strftime("%Y-%m-%d %H:%M")] + [data.get(s, "") for s in SOURCES])

    # 2. Direct + lifecycle CI CSVs (for tier 2 training)
    for cef_type, field in (("direct", "direct"), ("lifecycle", "lifecycle")):
        out_path = os.path.join(output_dir, f"{region}_{cef_type}_emissions.csv")
        with open(out_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["UTC time", "carbon_intensity"])
            for row in rows:
                value = getattr(row, field)
                writer.writerow([row.ts.strftime("%Y-%m-%d %H:%M"), value if value is not None else ""])

    print(f"Exported: {clean_path}")
    print(f"Exported: {output_dir}/{region}_direct_emissions.csv")
    print(f"Exported: {output_dir}/{region}_lifecycle_emissions.csv")


def run(region, days_back=90):
    print(f"=== Backfilling {days_back} days of grid data for {region} ===")
    backfill_emission_actual(region, days_back)

    output_dir = f"/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/data/{region}/fuel_forecast"
    print(f"=== Exporting training CSVs to {output_dir} ===")
    export_training_csvs(region, output_dir)