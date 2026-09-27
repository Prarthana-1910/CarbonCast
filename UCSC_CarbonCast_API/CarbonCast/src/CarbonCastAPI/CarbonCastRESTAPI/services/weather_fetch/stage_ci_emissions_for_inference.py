#!/usr/bin/env python3
"""
stage_ci_emissions_for_inference.py

Exports EmissionActual.lifecycle / .direct values (already CEF-computed at
ingest time) into the CSV format secondTierForecasts.py's real-time path
expects:
    <output_dir>/<region>/<region>_<date>_direct_emissions.csv
    <output_dir>/<region>/<region>_<date>_lifecycle_emissions.csv

Usage (from Django shell):
    from CarbonCastRESTAPI.services.weather_fetch.stage_ci_emissions_for_inference import stage_ci_emissions
    stage_ci_emissions("CISO", "2026-08-20", "/path/to/CARBONCAST_REAL_TIME_DIR")
"""

import os
import csv
from datetime import datetime, timedelta, timezone


def stage_ci_emissions(region, date_str, output_dir):
    from CarbonCastRESTAPI.models import EmissionActual

    target_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    next_date = target_date + timedelta(days=1)

    rows = (
        EmissionActual.objects.filter(
            region=region,
            ts__gte=target_date,
            ts__lt=next_date,
        )
        .order_by("ts")
    )

    if not rows.exists():
        raise ValueError(f"No EmissionActual rows found for {region} on {date_str}")

    out_dir = os.path.join(output_dir, region)
    os.makedirs(out_dir, exist_ok=True)
    creation_time = datetime.now(timezone.utc).isoformat()

    for cef_type, field in (("direct", "direct"), ("lifecycle", "lifecycle")):
        out_path = os.path.join(out_dir, f"{region}_{date_str}_{cef_type}_emissions.csv")
        with open(out_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["UTC time", "creation_time (UTC)", "version", "carbon_intensity"])
            for row in rows:
                value = getattr(row, field)
                writer.writerow([
                    row.ts.strftime("%Y-%m-%d %H:%M"),
                    creation_time,
                    "ci-stage-v1",
                    value if value is not None else "",
                ])
        print(f"Staged {rows.count()} rows -> {out_path}")

    return out_dir