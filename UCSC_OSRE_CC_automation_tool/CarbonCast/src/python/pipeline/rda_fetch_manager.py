"""
RDA Fetch Manager - single region per run
Usage: python3 fetch_manager.py REGION
"""
import os, sys, json, time, glob, subprocess, logging

BASE_DIR      = os.path.expanduser("~/CarbonCast_spring26/UCSC_OSRE_CC_automation_tool/CarbonCast")
CONTROL_DIR   = os.path.join(BASE_DIR, "control_files")
DOWNLOAD_DIR  = os.path.join(BASE_DIR, "downloaded_files")
STATE_FILE    = os.path.join(BASE_DIR, "pipeline_state.json")
LOG_FILE      = os.path.join(BASE_DIR, "logs", "rda_fetch_manager.log")

POLL_INTERVAL   = 60    # 1 min, per request
ERROR_THRESHOLD = 3
REQUEST_ID_FIELD = "request_index"

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                     handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()])
log = logging.getLogger(__name__)
sys.path.insert(0, os.path.join(BASE_DIR, "src/python"))
import rdams_client as rc


def load_state():
    default = {"submitted": {}, "downloaded": [], "error_counts": {}}
    if os.path.exists(STATE_FILE):
        s = json.load(open(STATE_FILE))
        for k, v in default.items():
            s.setdefault(k, v)
        return s
    return default


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    json.dump(state, open(tmp, "w"), indent=2)
    os.replace(tmp, STATE_FILE)


def get_rda_all():
    try:
        r = rc.get_status()
        if not r or "data" not in r:
            return {}
        reqs = r["data"] if isinstance(r["data"], list) else [r["data"]]
        out = {}
        for x in reqs:
            rid = x.get(REQUEST_ID_FIELD) or x.get("request_index")
            if rid:
                out[str(rid)] = x
        return out
    except Exception as e:
        log.warning(f"Status check failed: {e}")
        return {}


def var_from_ctl(p):
    return os.path.basename(p).replace("_control.ctl", "").split("_", 1)[1]


def count_existing_files(region):
    region_dir = os.path.join(DOWNLOAD_DIR, region)
    if not os.path.isdir(region_dir):
        return 0
    return sum(len(files) for _, _, files in os.walk(region_dir))


def download_request(req_id, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    try:
        token_file = os.path.join(BASE_DIR, "rdams_token.txt")
        token = open(token_file).read().strip() if os.path.exists(token_file) else ""
        r = rc.get_filelist(int(req_id))
        if not r or "data" not in r:
            log.error(f"No filelist for {req_id}: raw response={r}")
            return False
        data = r["data"]
        files = data.get("web_files") or data.get("file") or []
        if not files:
            log.error(f"Empty/unexpected filelist keys for {req_id}: {list(data.keys())}")
            return False
        urls = sorted({f["web_path"] for f in files if f.get("web_path")})
        for url in urls:
            fname = os.path.basename(url)
            out = os.path.join(out_dir, fname)
            if os.path.exists(out) and os.path.getsize(out) > 0:
                continue
            cmd = ["wget", "-q", "-O", out, url]
            if token:
                cmd = ["wget", "-q", "--header", f"Authorization: Bearer {token}", "-O", out, url]
            subprocess.run(cmd, check=True)
            log.info(f"  Downloaded: {fname}")
        return True
    except Exception as e:
        log.error(f"Download error for {req_id}: {e}")
        return False


def submit_ctl(ctl_path):
    try:
        result = rc.submit(ctl_path)
        if result and result.get("status") == "ok":
            req_id = result.get("data", {}).get("request_id")
            if req_id:
                log.info(f"Submitted {os.path.basename(ctl_path)} -> {req_id}")
                return str(req_id)
        log.warning(f"Submit failed {os.path.basename(ctl_path)}: {result}")
        return None
    except Exception as e:
        log.error(f"Submit error for {os.path.basename(ctl_path)}: {e}")
        return None


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 rda_fetch_manager.py REGION")
        sys.exit(1)
    region = sys.argv[1]
    os.chdir(BASE_DIR)

    existing = count_existing_files(region)
    log.info(f"=== {region}: {existing} files already on disk ===")

    state = load_state()
    region_ctls = sorted(glob.glob(os.path.join(CONTROL_DIR, f"{region}_*_control.ctl")))
    if not region_ctls:
        log.error(f"No ctl files found for region {region}")
        sys.exit(1)
    log.info(f"{region}: {len(region_ctls)} ctl files to submit (expect 8 = 4 vars x 2 chunks)")

    # submit only ctls whose var/chunk isn't already downloaded
    for ctl in region_ctls:
        bn = os.path.basename(ctl)
        if bn in state["submitted"].values():
            continue
        var = var_from_ctl(ctl)
        var_dir = os.path.join(DOWNLOAD_DIR, region, var)
        if os.path.isdir(var_dir) and os.listdir(var_dir):
            log.info(f"Skipping {bn} — {var} already has files")
            continue
        req_id = submit_ctl(ctl)
        if req_id:
            state["submitted"][req_id] = bn
            save_state(state)
            time.sleep(15)

    pending = {rid: bn for rid, bn in state["subm   itted"].items()
               if bn in [os.path.basename(c) for c in region_ctls]}

    while pending:
        all_rda = get_rda_all()
        for req_id, bn in list(pending.items()):
            rda_req = all_rda.get(req_id)
            if not rda_req:
                continue
            status = rda_req.get("status")
            if status == "Completed":
                var = var_from_ctl(os.path.join(CONTROL_DIR, bn))
                out_dir = os.path.join(DOWNLOAD_DIR, region, var)
                log.info(f"Downloading {req_id} ({region}/{var})")
                if download_request(req_id, out_dir):
                    state["downloaded"].append(f"{region}:{var}")
                    state["submitted"].pop(req_id, None)
                    state["error_counts"].pop(req_id, None)
                    pending.pop(req_id)
                    save_state(state)
                    try:
                        rc.purge_request(int(req_id))
                    except Exception as e:
                        log.warning(f"Purge failed for {req_id}: {e}")
            elif status == "Error":
                cnt = state["error_counts"].get(req_id, 0) + 1
                state["error_counts"][req_id] = cnt
                log.warning(f"{req_id} error {cnt}/{ERROR_THRESHOLD}")
                if cnt >= ERROR_THRESHOLD:
                    ctl_path = os.path.join(CONTROL_DIR, bn)
                    state["submitted"].pop(req_id, None)
                    state["error_counts"].pop(req_id, None)
                    pending.pop(req_id)
                    try:
                        rc.purge_request(int(req_id))
                    except Exception:
                        pass
                    new_id = submit_ctl(ctl_path)
                    if new_id:
                        state["submitted"][new_id] = bn
                        pending[new_id] = bn
                save_state(state)

        if pending:
            log.info(f"{len(pending)} still pending, sleeping {POLL_INTERVAL}s")
            time.sleep(POLL_INTERVAL)

    final_count = count_existing_files(region)
    log.info(f"=== {region} DONE. files before={existing}, files now={final_count} ===")
    log.info("Enter next region manually and rerun.")


if __name__ == "__main__":
    main()