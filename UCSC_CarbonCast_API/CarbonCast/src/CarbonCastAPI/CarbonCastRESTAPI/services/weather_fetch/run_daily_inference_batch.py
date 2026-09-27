#!/usr/bin/env python3
"""
run_daily_inference_batch.py — runs real-time CI inference for all
retrained regions. Meant to run daily (via Celery/cron).

Usage:
    python3 run_daily_inference_batch.py
"""
import logging
import traceback

logger = logging.getLogger("run_daily_inference_batch")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# All regions with freshly retrained models today
TRAINED_REGIONS = [
    'GB', 'LDWP', 'LT', 'PNM', 'RO', 'RS', 'SCL', 'SE', 'SI', 'SK', 'TAL', 'TIDC', 'TPWR', 'WALC'
]

# ["AECI", "AT", "AZPS", "BANC", "BE", "BG",
#     "BPAT", "CH", "CISO", "CZ",
#     "DE", "DK", "DOPD", "DUK", "EE", "EPE", "ERCO", "ES", "FI", "FMPP",
#     "FPC", "FPL", "FR", "GCPD", "GR", "GRID", "HR", "HU", "IE", "IPCO",
#     "ISNE", "IT", "LDWP", "LGEE", "LT", "LV", "MISO", "NEVP", "NL", "NWMT",
#     "NYIS", "PACE", "PACW", "PGE", "PJM", "PL", "PNM", "PSCO", "PSEI", "PT",
#     "RO", "RS", "SC", "SCEG", "SCL", "SE", "SI", "SK", "SOCO", "SPA", "SRP",
#     "SWPP", "TAL", "TEC", "TEPC", "TIDC", "TPWR", "TVA", "WALC"
# ]


def run_all():
    from CarbonCastRESTAPI.services.weather_fetch.run_full_realtime_pipeline import run_pipeline

    results = {}
    for region in TRAINED_REGIONS:
        try:
            result = run_pipeline(region)
            results[region] = "SUCCESS"
        except Exception as exc:
            logger.error(f"[{region}] FAILED: {exc}")
            logger.error(traceback.format_exc())
            results[region] = f"FAILED: {exc}"

    logger.info(f"\n{'='*20} DAILY INFERENCE SUMMARY {'='*20}")
    for region, status in results.items():
        logger.info(f"{region}: {status}")

    return results