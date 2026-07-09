"""
Script 5: Master Pipeline
The single entry point. Run this and walk away.

Usage:
    python 5_master_pipeline.py
    python 5_master_pipeline.py --regions CISO ERCOT PJM   # subset first
    python 5_master_pipeline.py --skip_fetch                # if data already downloaded
    python 5_master_pipeline.py --skip_fetch --skip_process # jump straight to training
"""

import os
import sys
import argparse
import logging
import subprocess

# ── CONFIG — EDIT THESE BEFORE RUNNING ───────────────────────────────────────
BASE_DIR        = os.path.expanduser("~/CarbonCast_spring26/UCSC_OSRE_CC_automation_tool/CarbonCast")
PIPELINE_DIR    = os.path.join(BASE_DIR, "src/python/pipeline")
VENV_PYTHON     = os.path.join(BASE_DIR, "src/python/venv/bin/python")
LOG_FILE        = os.path.join(BASE_DIR, "logs", "master_pipeline.log")

# Date range for control file generation
TRAIN_START     = "202001010000"   # YYYYMMDDHHMM for RDA
TRAIN_END       = "202606250000"

# Regions to process — None = all regions in config
DEFAULT_REGIONS = ["CISO", "ERCOT", "PJM"]   # start small, expand later
# ─────────────────────────────────────────────────────────────────────────────

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

SCRIPTS = {
    "generate": os.path.join(PIPELINE_DIR, "1_generate_control_files.py"),
    "fetch":    os.path.join(PIPELINE_DIR, "2_rda_fetch_manager.py"),
    # Scripts 3 & 4 are triggered automatically by script 2 per region
}


def run(script, extra_args=None):
    cmd = [VENV_PYTHON, script] + (extra_args or [])
    log.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=BASE_DIR)
    if result.returncode != 0:
        log.error(f"Script failed: {script}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="CarbonCast retraining master pipeline")
    parser.add_argument("--regions", nargs="+", default=DEFAULT_REGIONS,
                        help="Regions to process (default: small test set)")
    parser.add_argument("--all_regions", action="store_true",
                        help="Run for all 58 regions")
    parser.add_argument("--skip_generate", action="store_true",
                        help="Skip control file generation (files already exist)")
    parser.add_argument("--skip_fetch", action="store_true",
                        help="Skip RDA fetch (data already downloaded)")
    parser.add_argument("--skip_process", action="store_true",
                        help="Skip grib2→CSV processing")
    args = parser.parse_args()

    regions = None if args.all_regions else args.regions
    log.info(f"=== CarbonCast Master Pipeline ===")
    log.info(f"Regions: {'ALL' if regions is None else regions}")
    log.info(f"Date range: {TRAIN_START} → {TRAIN_END}")

    # Step 1: Generate control files
    if not args.skip_generate:
        log.info("Step 1/2: Generating control files")
        region_args = ["--regions"] + regions if regions else ["--all_regions"]
        run(SCRIPTS["generate"], region_args +
            ["--train_start", TRAIN_START, "--train_end", TRAIN_END])
    else:
        log.info("Step 1/2: Skipped (--skip_generate)")

    # Step 2: Fetch from RDA (blocking — runs until all downloads complete)
    # Scripts 3 & 4 fire automatically per region as downloads complete
    if not args.skip_fetch:
        log.info("Step 2/2: Fetching from RDA (this runs until all regions complete)")
        region_args = ["--regions"] + regions if regions else []
        run(SCRIPTS["fetch"], region_args)
    else:
        log.info("Step 2/2: Skipped (--skip_fetch)")
        # If fetch skipped, manually trigger process+train for each region
        if not args.skip_process:
            for region in (regions or []):
                log.info(f"Manually triggering process+train for {region}")
                run(os.path.join(PIPELINE_DIR, "3_process_weather_data.py"),
                    ["--region", region])

    log.info("=== Master pipeline finished ===")


if __name__ == "__main__":
    main()
