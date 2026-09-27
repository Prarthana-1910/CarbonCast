#!/usr/bin/env python3
"""
stage_electricity_for_inference.py
Exports EmissionActual rows (already ingested via eia_service.py/entsoe_service.py)
into the CSV format firstTierForecasts.py's real-time path expects:
    <output_dir>/<region>/<region>_<date>.csv
Must be run inside Django shell context (uses the ORM).
Usage (from Django shell):
    from CarbonCastRESTAPI.services.weather_fetch.stage_electricity_for_inference import stage_electricity
    stage_electricity("CISO", "2026-08-20", "/path/to/CARBONCAST_REAL_TIME_DIR")
"""
import os
import csv
from datetime import datetime, timedelta, timezone

# Per-region source lists, matching each region's SOURCES declared in
# firstTierConfig.json (lowercased to match EmissionActual.data dict keys).
REGION_SOURCES = {
    "AECI": ["coal", "nat_gas", "wind"],
    "AT": ["biomass", "nat_gas", "geothermal", "hydro", "solar", "wind", "other"],
    "AZPS": ["coal", "nat_gas", "nuclear", "oil", "hydro", "solar", "wind", "other"],
    "BANC": ["nat_gas", "hydro", "solar", "other"],
    "BE": ["biomass", "nat_gas", "hydro", "nuclear", "oil", "solar", "wind", "other"],
    "BG": ["biomass", "coal", "nat_gas", "hydro", "nuclear", "solar", "wind"],
    "BPAT": ["nat_gas", "nuclear", "hydro", "solar", "wind", "other"],
    "CH": ["hydro", "nuclear", "solar", "wind"],
    "CISO": ["coal", "nat_gas", "nuclear", "oil", "hydro", "solar", "wind", "other"],
    "CZ": ["biomass", "coal", "nat_gas", "hydro", "nuclear", "oil", "solar", "wind", "other"],
    "DE": ["biomass", "coal", "nat_gas", "geothermal", "hydro", "oil", "solar", "wind", "other"],
    "DK": ["biomass", "coal", "nat_gas", "oil", "solar", "wind"],
    "DOPD": ["hydro"],
    "DUK": ["coal", "nat_gas", "nuclear", "hydro", "solar", "other"],
    "EE": ["biomass", "coal", "nat_gas", "hydro", "solar", "wind", "other"],
    "EPE": ["nat_gas", "solar"],
    "ERCO": ["coal", "nat_gas", "nuclear", "hydro", "solar", "wind", "other"],
    "ES": ["biomass", "coal", "nat_gas", "hydro", "nuclear", "oil", "solar", "wind", "other"],
    "FI": ["biomass", "coal", "nat_gas", "hydro", "nuclear", "oil", "solar", "wind", "other"],
    "FMPP": ["coal", "nat_gas", "nuclear", "oil", "other", "solar"],
    "FPC": ["coal", "nat_gas", "oil", "hydro", "solar", "other"],
    "FPL": ["nat_gas", "nuclear", "oil", "solar", "other"],
    "FR": ["biomass", "coal", "nat_gas", "hydro", "nuclear", "oil", "solar", "wind"],
    "GB": ["biomass", "coal", "nat_gas", "hydro", "nuclear", "solar", "wind", "other"],
    "GCPD": ["hydro"],
    "GR": ["coal", "nat_gas", "hydro", "solar", "wind"],
    "GRID": ["coal", "nat_gas", "solar", "wind"],
    "HR": ["biomass", "coal", "nat_gas", "geothermal", "hydro", "oil", "solar", "wind", "other"],
    "HU": ["biomass", "coal", "nat_gas", "geothermal", "hydro", "nuclear", "oil", "solar", "wind", "other"],
    "IE": ["coal", "nat_gas", "hydro", "oil", "wind", "other"],
    "IPCO": ["nat_gas", "oil", "hydro", "solar", "wind", "other"],
    "ISNE": ["coal", "nat_gas", "nuclear", "oil", "hydro", "solar", "wind", "other"],
    "IT": ["biomass", "coal", "nat_gas", "geothermal", "hydro", "oil", "solar", "wind", "other"],
    "LDWP": ["coal", "nat_gas", "hydro", "solar", "wind", "other"],
    "LGEE": ["coal", "nat_gas", "hydro", "oil", "solar"],
    "LT": ["biomass", "nat_gas", "hydro", "solar", "wind", "other"],
    "LV": ["biomass", "nat_gas", "hydro", "solar", "wind", "other"],
    "MISO": ["coal", "nat_gas", "nuclear", "hydro", "solar", "wind", "other"],
    "NEVP": ["coal", "nat_gas", "nuclear", "oil", "hydro", "solar", "wind", "other"],
    "NL": ["biomass", "coal", "nat_gas", "nuclear", "solar", "wind", "other"],
    "NWMT": ["coal", "nat_gas", "oil", "hydro", "solar", "wind"],
    "NYIS": ["coal", "nat_gas", "nuclear", "oil", "hydro", "solar", "wind", "other"],
    "PACE": ["coal", "nat_gas", "hydro", "solar", "wind", "other"],
    "PACW": ["nat_gas", "hydro", "solar", "wind", "other"],
    "PGE": ["coal", "nat_gas", "wind", "hydro", "other"],
    "PJM": ["coal", "nat_gas", "nuclear", "oil", "hydro", "solar", "wind", "other"],
    "PL": ["biomass", "coal", "nat_gas", "hydro", "oil", "solar", "wind", "other"],
    "PNM": ["coal", "nat_gas", "wind", "hydro", "solar", "other"],
    "PSCO": ["coal", "nat_gas", "oil", "hydro", "solar", "wind", "other"],
    "PSEI": ["coal", "nat_gas", "oil", "hydro", "solar", "wind", "other"],
    "PT": ["biomass", "nat_gas", "hydro", "solar", "wind", "other"],
    "RO": ["biomass", "nat_gas", "hydro", "nuclear", "solar", "wind"],
    "RS": ["biomass", "coal", "nat_gas", "hydro", "wind", "other"],
    "SC": ["coal", "nat_gas", "oil", "hydro", "solar", "other"],
    "SCEG": ["coal", "nat_gas", "nuclear", "hydro", "solar", "other"],
    "SCL": ["hydro"],
    "SE": ["nat_gas", "hydro", "nuclear", "solar", "wind", "other"],
    "SI": ["biomass", "coal", "nat_gas", "hydro", "nuclear", "oil", "solar", "wind", "other"],
    "SK": ["biomass", "coal", "nat_gas", "hydro", "nuclear", "oil", "solar", "wind", "other"],
    "SOCO": ["coal", "nat_gas", "nuclear", "oil", "solar", "wind", "other"],
    "SPA": ["hydro"],
    "SRP": ["coal", "nat_gas", "nuclear", "hydro", "solar", "wind", "other"],
    "SWPP": ["coal", "nat_gas", "nuclear", "oil", "hydro", "solar", "wind", "other"],
    "TAL": ["nat_gas", "solar"],
    "TEC": ["coal", "nat_gas", "other", "oil", "solar"],
    "TEPC": ["coal", "nat_gas", "solar", "wind", "other"],
    "TIDC": ["nat_gas", "hydro"],
    "TPWR": ["hydro"],
    "TVA": ["coal", "nat_gas", "nuclear", "oil", "hydro", "solar", "wind", "other"],
    "WACM": ["coal", "nat_gas", "hydro", "solar", "wind"],
    "WALC": ["nat_gas", "hydro", "solar", "wind"],
}

CISO_SOURCE_ORDER = REGION_SOURCES["CISO"]  # kept for backward-compat imports elsewhere


def stage_electricity(region, date_str, output_dir, source_order=None):
    from CarbonCastRESTAPI.models import EmissionActual

    source_order = source_order or REGION_SOURCES.get(region, CISO_SOURCE_ORDER)

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

    # 1. Write the combined file for legacy support
    combined_path = os.path.join(out_dir, f"{region}_{date_str}.csv")
    with open(combined_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["UTC time", "creation_time (UTC)", "version", *source_order])
        for row in rows:
            data = row.data or {}
            writer.writerow([
                row.ts.strftime("%Y-%m-%d %H:%M"),
                creation_time,
                "electricity-stage-v1",
                *[data.get(src, 0) for src in source_order],
            ])

    # 2. Write per-source files for real-time inference
    for src in source_order:
        src_path = os.path.join(out_dir, f"{region}_{src}_{date_str}.csv")
        with open(src_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["UTC time", "creation_time (UTC)", src])
            for row in rows:
                data = row.data or {}
                writer.writerow([
                    row.ts.strftime("%Y-%m-%d %H:%M"),
                    creation_time,
                    data.get(src, 0),
                ])