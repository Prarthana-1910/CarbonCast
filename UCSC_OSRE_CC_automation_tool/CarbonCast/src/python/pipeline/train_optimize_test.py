"""
Script 4: Train → Optimize → Test pipeline per region.
Called by Script 3 after CSVs are ready.
Can also be run manually: python 4_train_optimize_test.py --region CISO
"""

import os
import sys
import json
import logging
import argparse
import subprocess
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────
BASE_DIR        = os.path.expanduser("~/CarbonCast_spring26/UCSC_OSRE_CC_automation_tool/CarbonCast")
CARBONCAST_SRC  = os.path.expanduser("~/CarbonCast_spring26/UCSC_CarbonCast_API/CarbonCast/src")
PROCESSED_DIR   = os.path.join(BASE_DIR, "processed_data")
MODELS_DIR      = os.path.join(BASE_DIR, "models")
RESULTS_DIR     = os.path.join(BASE_DIR, "results")
LOG_FILE        = os.path.join(BASE_DIR, "logs", "train_pipeline.log")
STATE_FILE      = os.path.join(BASE_DIR, "pipeline_state.json")
CONFIG_FILE     = os.path.join(CARBONCAST_SRC, "config.json")   # existing CC config
VENV_PYTHON     = os.path.join(BASE_DIR, "src/python/venv/bin/python")

# Date splits — edit these before running
TRAIN_START     = "2020-01-01"
TRAIN_END       = "2022-06-30"
OPTIMIZE_START  = "2022-07-01"
OPTIMIZE_END    = "2022-12-31"
TEST_START      = "2023-01-01"
TEST_END        = "2023-06-30"
# ─────────────────────────────────────────────────────────────────────────────

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger(__name__)


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def run_first_tier(region, phase, date_start, date_end):
    """Run firstTierForecasts.py for a region/phase."""
    script = os.path.join(CARBONCAST_SRC, "firstTierForecasts.py")
    weather_dir = os.path.join(PROCESSED_DIR, region)
    model_dir   = os.path.join(MODELS_DIR, region)
    result_dir  = os.path.join(RESULTS_DIR, region, phase)
    os.makedirs(result_dir, exist_ok=True)

    log.info(f"[{region}] First tier {phase}: {date_start} → {date_end}")
    result = subprocess.run(
        [VENV_PYTHON, script,
         "--config", CONFIG_FILE,
         "--region", region,
         "--start_date", date_start,
         "--end_date", date_end,
         "--weather_dir", weather_dir,
         "--model_dir", model_dir,
         "--output_dir", result_dir,
         "--phase", phase],
        capture_output=True, text=True,
        cwd=CARBONCAST_SRC
    )
    if result.returncode != 0:
        log.error(f"First tier {phase} failed for {region}:\n{result.stderr}")
        return False
    log.info(f"[{region}] First tier {phase} complete")
    return True


def run_second_tier(region, phase, date_start, date_end, first_tier_output):
    """Run secondTierForecasts.py for a region/phase."""
    script = os.path.join(CARBONCAST_SRC, "secondTierForecasts.py")
    weather_dir = os.path.join(PROCESSED_DIR, region)
    result_dir  = os.path.join(RESULTS_DIR, region, phase)

    for cef_type in ("direct", "lifecycle"):
        log.info(f"[{region}] Second tier {phase} ({cef_type})")
        result = subprocess.run(
            [VENV_PYTHON, script,
             "--config", CONFIG_FILE,
             "--region", region,
             "--cef_type", cef_type,
             "--start_date", date_start,
             "--end_date", date_end,
             "--weather_dir", weather_dir,
             "--first_tier_output", first_tier_output,
             "--output_dir", result_dir,
             "--phase", phase],
            capture_output=True, text=True,
            cwd=CARBONCAST_SRC
        )
        if result.returncode != 0:
            log.error(f"Second tier {phase} ({cef_type}) failed for {region}:\n{result.stderr}")
            return False
    log.info(f"[{region}] Second tier {phase} complete")
    return True


def update_region_state(region, phase, status):
    state = load_state()
    if "training" not in state:
        state["training"] = {}
    if region not in state["training"]:
        state["training"][region] = {}
    state["training"][region][phase] = {"status": status, "timestamp": datetime.utcnow().isoformat()}
    save_state(state)


def main(region):
    log.info(f"=== Training pipeline for {region} ===")

    first_tier_out = os.path.join(RESULTS_DIR, region, "train", "first_tier_output.csv")

    # ── TRAINING ──────────────────────────────────────────────────────────────
    log.info(f"[{region}] Phase 1/3: Training")
    ok = run_first_tier(region, "train", TRAIN_START, TRAIN_END)
    if not ok:
        update_region_state(region, "train", "failed")
        sys.exit(1)
    ok = run_second_tier(region, "train", TRAIN_START, TRAIN_END, first_tier_out)
    if not ok:
        update_region_state(region, "train", "failed")
        sys.exit(1)
    update_region_state(region, "train", "completed")

    # ── OPTIMIZATION ──────────────────────────────────────────────────────────
    log.info(f"[{region}] Phase 2/3: Optimization")
    ok = run_first_tier(region, "optimize", OPTIMIZE_START, OPTIMIZE_END)
    if not ok:
        update_region_state(region, "optimize", "failed")
        sys.exit(1)
    opt_first_tier_out = os.path.join(RESULTS_DIR, region, "optimize", "first_tier_output.csv")
    ok = run_second_tier(region, "optimize", OPTIMIZE_START, OPTIMIZE_END, opt_first_tier_out)
    if not ok:
        update_region_state(region, "optimize", "failed")
        sys.exit(1)
    update_region_state(region, "optimize", "completed")

    # ── TESTING ───────────────────────────────────────────────────────────────
    log.info(f"[{region}] Phase 3/3: Testing")
    ok = run_first_tier(region, "test", TEST_START, TEST_END)
    if not ok:
        update_region_state(region, "test", "failed")
        sys.exit(1)
    test_first_tier_out = os.path.join(RESULTS_DIR, region, "test", "first_tier_output.csv")
    ok = run_second_tier(region, "test", TEST_START, TEST_END, test_first_tier_out)
    if not ok:
        update_region_state(region, "test", "failed")
        sys.exit(1)
    update_region_state(region, "test", "completed")

    log.info(f"✅ Full pipeline complete for {region}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", required=True)
    args = parser.parse_args()
    main(args.region)
