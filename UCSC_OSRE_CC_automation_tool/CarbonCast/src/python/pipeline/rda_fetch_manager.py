"""
Script 2: RDA Fetch Manager
- Submits control files to RDA in batches of ≤10
- Polls until complete, then downloads
- Hands off to Script 3 (process_weather_data.py) per region when all 4 vars done
- Runs continuously until all regions are done; safe to restart (tracks state)
"""

import os
import sys
import json
import time
import glob
import subprocess
import logging
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────
BASE_DIR        = os.path.expanduser("~/CarbonCast_spring26/UCSC_OSRE_CC_automation_tool/CarbonCast")
CONTROL_DIR     = os.path.join(BASE_DIR, "control_files")
DOWNLOAD_DIR    = os.path.join(BASE_DIR, "downloaded_files")
STATE_FILE      = os.path.join(BASE_DIR, "pipeline_state.json")
LOG_FILE        = os.path.join(BASE_DIR, "logs", "fetch_manager.log")

RDA_CLIENT      = os.path.join(BASE_DIR, "src/python/rdams_client.py")
VENV_PYTHON     = os.path.join(BASE_DIR, "src/python/venv/bin/python")

MAX_CONCURRENT  = 10
POLL_INTERVAL   = 120   # seconds between status checks
# ─────────────────────────────────────────────────────────────────────────────

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

sys.path.insert(0, os.path.join(BASE_DIR, "src/python"))
import rdams_client as rc


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"submitted": {}, "completed": [], "failed": []}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_all_control_files():
    return sorted(glob.glob(os.path.join(CONTROL_DIR, "*.ctl")))


def region_from_ctl(ctl_path):
    fname = os.path.basename(ctl_path)
    return fname.split("_")[0]


def var_from_ctl(ctl_path):
    fname = os.path.basename(ctl_path).replace("_control.ctl", "")
    return "_".join(fname.split("_")[1:])


def get_active_requests():
    """Return dict of {request_id: status} from RDA."""
    try:
        result = rc.get_status()
        if not result or "data" not in result:
            return {}
        requests = result["data"] if isinstance(result["data"], list) else [result["data"]]
        return {str(r.get("request_index", "")): r.get("status", "") for r in requests if r.get("request_index")}
    except Exception as e:
        log.warning(f"Status check failed: {e}")
        return {}


def submit_ctl(ctl_path):
    """Submit one control file to RDA, return request_id or None."""
    try:
        result = rc.submit_json(ctl_path)
        if result and "data" in result:
            req_id = str(result["data"].get("request_index", ""))
            if req_id:
                log.info(f"Submitted {os.path.basename(ctl_path)} → request {req_id}")
                return req_id
        log.warning(f"Submit failed for {ctl_path}: {result}")
        return None
    except Exception as e:
        log.error(f"Submit error {ctl_path}: {e}")
        return None


def download_request(req_id, region, var_name):
    """Download completed request to downloaded_files/REGION/VAR/"""
    out_dir = os.path.join(DOWNLOAD_DIR, region, var_name)
    os.makedirs(out_dir, exist_ok=True)
    try:
        result = rc.get_filelist(req_id)
        if not result or "data" not in result:
            log.error(f"No filelist for request {req_id}")
            return False
        files = result["data"].get("file", [])
        for f in files:
            url = f.get("web_path", "")
            if url:
                fname = os.path.basename(url)
                out_path = os.path.join(out_dir, fname)
                if os.path.exists(out_path):
                    log.info(f"Already exists: {fname}")
                    continue
                log.info(f"Downloading {fname} → {out_dir}")
                subprocess.run(["wget", "-q", "-O", out_path, url], check=True)
        return True
    except Exception as e:
        log.error(f"Download failed for request {req_id}: {e}")
        return False


def region_download_complete(region, state):
    """True if all 4 variables for a region are in completed list."""
    vars_done = [v for (r, v) in [k.split(":", 1) for k in state["completed"] if ":" in k] if r == region]
    return set(vars_done) >= {"temp", "wind", "dswrf", "rain"}


def trigger_processing(region):
    """Call Script 3 for this region."""
    script = os.path.join(BASE_DIR, "src/python/pipeline/3_process_weather_data.py")
    log.info(f"🔄 Triggering processing for {region}")
    subprocess.Popen([VENV_PYTHON, script, "--region", region])


def main():
    log.info("=== RDA Fetch Manager started ===")
    state = load_state()

    all_ctls = get_all_control_files()
    # Filter out already completed
    pending_ctls = [
        c for c in all_ctls
        if f"{region_from_ctl(c)}:{var_from_ctl(c)}" not in state["completed"]
        and os.path.basename(c) not in [v for v in state["submitted"].values()]
    ]
    log.info(f"Total control files: {len(all_ctls)}, pending: {len(pending_ctls)}")

    ctl_queue = list(pending_ctls)

    while ctl_queue or state["submitted"]:
        active = get_active_requests()
        active_count = len(active)
        log.info(f"Active RDA requests: {active_count}, queue remaining: {len(ctl_queue)}")

        # Check completed/failed among submitted
        for req_id, ctl_basename in list(state["submitted"].items()):
            status = active.get(req_id, "unknown")
            if status in ("Completed", "completed"):
                # find matching ctl
                ctl_path = next((c for c in all_ctls if os.path.basename(c) == ctl_basename), None)
                if ctl_path:
                    region = region_from_ctl(ctl_path)
                    var    = var_from_ctl(ctl_path)
                    success = download_request(req_id, region, var)
                    if success:
                        key = f"{region}:{var}"
                        state["completed"].append(key)
                        del state["submitted"][req_id]
                        save_state(state)
                        log.info(f"✅ {region}/{var} downloaded")
                        if region_download_complete(region, state):
                            trigger_processing(region)
            elif status in ("Purged", "Error", "error"):
                log.warning(f"Request {req_id} ({ctl_basename}) failed with status: {status}")
                state["failed"].append(ctl_basename)
                del state["submitted"][req_id]
                save_state(state)

        # Submit new requests up to MAX_CONCURRENT
        slots = MAX_CONCURRENT - len(state["submitted"])
        while slots > 0 and ctl_queue:
            ctl = ctl_queue.pop(0)
            req_id = submit_ctl(ctl)
            if req_id:
                state["submitted"][req_id] = os.path.basename(ctl)
                save_state(state)
                slots -= 1
                active_count += 1
            time.sleep(2)  # brief pause between submissions

        if not ctl_queue and not state["submitted"]:
            break

        log.info(f"Sleeping {POLL_INTERVAL}s...")
        time.sleep(POLL_INTERVAL)

    log.info(f"=== Fetch complete. Completed: {len(state['completed'])}, Failed: {len(state['failed'])} ===")
    if state["failed"]:
        log.warning(f"Failed: {state['failed']}")


if __name__ == "__main__":
    main()
