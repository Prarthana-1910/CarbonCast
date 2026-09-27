#!/usr/bin/env python3
"""
run_batch_pipeline.py

Runs run_full_realtime_pipeline for multiple regions, logging per-region
success/failure without letting one region's crash stop the batch.

Usage (Django shell):
    from CarbonCastRESTAPI.services.weather_fetch.run_batch_pipeline import run_batch
    run_batch(['AECI', 'CISO', 'PJM', 'ISNE', 'DUK'])
"""

import logging
import traceback
from datetime import timezone, timedelta

from django.utils import timezone as tz

logger = logging.getLogger("run_batch_pipeline")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def run_batch(regions):
    from CarbonCastRESTAPI.services.weather_fetch.run_full_realtime_pipeline import run_pipeline
    from CarbonCastRESTAPI.models import Forecast168
    shared_forecast_start = tz.now().astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    results = {}
    for region in regions:
        logger.info(f"\n{'='*20} REGION: {region} {'='*20}")
        try:
            run_pipeline(region)
            count = Forecast168.objects.filter(region_code=region).count()
            results[region] = {'status': 'success', 'forecast168_rows': count}
        except Exception as exc:
            logger.error(f"FAILED for {region}: {exc}")
            logger.error(traceback.format_exc())
            results[region] = {'status': 'failed', 'error': str(exc)}

    logger.info(f"\n{'='*20} BATCH SUMMARY {'='*20}")
    for region, result in results.items():
        logger.info(f"{region}: {result}")

    return results