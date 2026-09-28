#gen_and_submit_batch3.py

import sys, os, re, time
sys.path.insert(0, 'src/python')
import rdams_client as rc

# Real RDA per-token cap is 10 open requests. We deliberately target 9,
# leaving 1 slot as a buffer for errored/purged/in-flight retries.
TARGET_CONCURRENT = 9
HARD_CAP = 10

if len(sys.argv) < 3:
    print("Usage: python3 gen_and_submit_batch3.py TOKEN_FILE REGION1:VAR1 [REGION2:VAR2 ...]")
    print("VAR must be one of: dswrf rain temp wind")
    sys.exit(1)

token_file = sys.argv[1]
job_specs = sys.argv[2:]

if os.path.exists(token_file):
    orig_get_auth = rc.get_authentication
    rc.get_authentication = lambda tf=None: orig_get_auth(tf or token_file)
    print(f"Using token file: {token_file}")
else:
    print(f"Token file {token_file} not found, using default authentication")

PARAM_LEVEL = {
    "dswrf": ("DSWRF",       "SFC:0"),
    "rain":  ("A PCP",       "SFC:0"),
    "temp":  ("TMP/DPT",     "HTGL:2"),
    "wind":  ("U GRD/V GRD", "HTGL:10"),
}

def build_product(var):
    if var == "dswrf":
        return "/".join(f"3-hour Average (initial+{s} to initial+{s+3})/6-hour Average (initial+{s} to initial+{s+6})" for s in range(0, 168, 6))
    elif var == "rain":
        return "/".join(f"3-hour Accumulation (initial+{s} to initial+{s+3})/6-hour Accumulation (initial+{s} to initial+{s+6})" for s in range(0, 168, 6))
    else:
        return "Analysis/" + "/".join(f"{h}-hour Forecast" for h in range(3, 169, 3))

def build_windows():
    from datetime import datetime, timedelta
    start_date = datetime(2026, 6, 1)
    end_date = datetime(2026, 9, 23)
    start = start_date.strftime("%Y%m%d0000")
    end = end_date.strftime("%Y%m%d0000")
    return [(start, end)]

def read_bbox(region, var):
    import glob
    matches = glob.glob(f"control_files/{region}_{var}_*control.ctl")
    if not matches:
        print(f"Can't find any control file for {region}:{var} to read bbox from")
        return None
    src_ctl = matches[0]  # any existing one works, bbox is time-invariant
    bbox = {}
    for line in open(src_ctl):
        m = re.match(r"^(nlat|slat|wlon|elon)=(.+)$", line.strip())
        if m:
            bbox[m.group(1)] = m.group(2)
    return bbox

def already_done(out_dir, start):
    month_prefix = start[:8]
    if not os.path.exists(out_dir):
        return False
    for f in os.listdir(out_dir):
        if f.startswith(f"gfs.0p25.{month_prefix}"):
            fpath = os.path.join(out_dir, f)
            if os.path.getsize(fpath) > 1_000_000:
                return True
    return False

# ── Build one flat pending queue across ALL jobs assigned to this token ──────
all_windows = build_windows()
pending = []  # each item: dict with region, var, i, start, end, param, level, bbox, out_dir, product

for spec in job_specs:
    region, var = spec.split(":")
    if var not in PARAM_LEVEL:
        print(f"Unknown var {var} in spec {spec}, skipping")
        continue
    param, level = PARAM_LEVEL[var]
    bbox = read_bbox(region, var)
    if bbox is None:
        continue
    product = build_product(var)
    out_dir = f"/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/retraining_weather_downloads/{region}/{var}"
    for i, (start, end) in enumerate(all_windows, 1):
        if already_done(out_dir, start):
            continue
        pending.append({
            "region": region, "var": var, "i": i, "start": start, "end": end,
            "param": param, "level": level, "bbox": bbox,
            "out_dir": out_dir, "product": product,
        })

if not pending:
    print(f"ALL DONE already for jobs: {job_specs}")
    sys.exit(0)

print(f"[{token_file}] {len(pending)} pending windows across jobs: {job_specs}")

def label_of(w):
    return f"{w['region']}_{w['var']}_gap1"

def ctl_path_of(w):
    return f"control_files/{label_of(w)}_control.ctl"

def write_ctl(w):
    with open(ctl_path_of(w), "w") as f:
        f.write(f"""dataset=ds084.1
date={w['start']}/to/{w['end']}
datetype=init
param={w['param']}
level={w['level']}
nlat={w['bbox']['nlat']}
slat={w['bbox']['slat']}
wlon={w['bbox']['wlon']}
elon={w['bbox']['elon']}
product={w['product']}
""")

def get_open_count():
    try:
        r = rc.get_status()
        return len([x for x in r.get('data', []) if x.get('status') not in ('Error',)])
    except Exception:
        return HARD_CAP  # unknown state -> assume full, don't submit blindly

def submit(ctl_path, label):
    print(f"Submitting {label}...")
    try:
        result = rc.submit(ctl_path)
    except Exception as exc:
        print(f"SUBMIT EXCEPTION for {label}: {exc}")
        return None
    if not result or result.get('status') != 'ok':
        print(f"SUBMIT FAILED for {label}: {result}")
        return None
    req_id = int(result['data'].get('request_index') or result['data'].get('request_id'))
    print(f"  {label} -> request_index {req_id}")
    return req_id

def find_existing_request(w):
    try:
        r = rc.get_status()
    except Exception:
        return None
    start, end, bbox = w['start'], w['end'], w['bbox']
    start_fmt = f"{start[:4]}-{start[4:6]}-{start[6:8]} {start[8:10]}:{start[10:12]}"
    end_fmt = f"{end[:4]}-{end[4:6]}-{end[6:8]} {end[8:10]}:{end[10:12]}"
    nlat_fmt = f"nlat={bbox['nlat']}"
    slat_fmt = f"slat={bbox['slat']}"
    param_fmt = f"param={w['param']}"
    level_fmt = f"level={w['level']}"
    for x in r.get('data', []):
        rinfo = x.get('rinfo', '')
        status = x.get('status')
        if status in ('Error', 'Set for Purge'):
            continue
        if (start_fmt in rinfo and end_fmt in rinfo and
            nlat_fmt in rinfo and slat_fmt in rinfo and
            param_fmt in rinfo and level_fmt in rinfo):
            return int(x.get('request_index')), status
    return None

def purge_errored():
    try:
        r = rc.get_status()
    except Exception:
        return 0
    purged = 0
    for x in r.get('data', []):
        if x.get('status') == 'Error':
            rid = int(x.get('request_index'))
            try:
                rc.purge_request(rid)
                print(f"  Purged stray errored request {rid}")
                purged += 1
            except Exception as e:
                print(f"  Failed to purge {rid}: {e}")
    return purged

def wait_for_slot():
    # Fill only up to TARGET_CONCURRENT (9), keeping 1 slot free as buffer.
    while get_open_count() >= TARGET_CONCURRENT:
        freed = purge_errored()
        if freed:
            print(f"Freed {freed} slot(s) by purging errored requests.")
        else:
            print(f"At/above target {TARGET_CONCURRENT} open requests, waiting 60s...")
        time.sleep(60)

jobs = {}
queue = list(pending)
MAX_RETRIES = 3

def submit_next():
    if not queue:
        return
    w = queue.pop(0)
    label = label_of(w)

    # Re-check completeness right before submitting — prevents duplicate
    # downloads if a window got requeued after actually completing.
    if already_done(w['out_dir'], w['start']):
        print(f"SKIP {label}: already on disk (caught before resubmission)")
        return

    write_ctl(w)

    existing = find_existing_request(w)
    if existing:
        req_id, status = existing
        print(f"Found existing request {req_id} ({status}) for {label}, reusing.")
        jobs[label] = {"w": w, "req_id": req_id, "retries": 0}
        return

    wait_for_slot()
    req_id = submit(ctl_path_of(w), label)
    if req_id:
        jobs[label] = {"w": w, "req_id": req_id, "retries": 0}
    else:
        print(f"Could not submit {label}, will retry later.")
        queue.append(w)

while queue and len(jobs) < TARGET_CONCURRENT:
    submit_next()

print(f"\n[{token_file}] Submitted {len(jobs)} requests, polling until all resolved...")

while jobs or queue:
    if queue and len(jobs) < TARGET_CONCURRENT:
        submit_next()

    time.sleep(30)
    for label in list(jobs.keys()):
        job = jobs[label]
        w = job["w"]
        req_id = job["req_id"]
        try:
            r = rc.get_status(req_id)
        except Exception as e:
            print(f"  [ERROR] Status check failed for {req_id} ({label}): {e}. Skipping this iteration.")
            continue

        status = None
        if isinstance(r.get('data'), dict):
            status = r['data'].get('status')
        elif isinstance(r.get('data'), list) and len(r['data']) > 0:
            status = r['data'][0].get('status')

        print(f"  [{token_file}][{label}] {req_id}: {status}")

        if status is None:
            job["retries"] += 1
            try:
                rc.purge_request(req_id)
                print(f"  Purged None-status request {req_id} ({label})")
            except Exception as e:
                print(f"  Failed to purge {req_id} ({label}): {e}")
            if job["retries"] > MAX_RETRIES:
                print(f"GIVING UP on {label} after {MAX_RETRIES} retries (None status)")
                del jobs[label]
            else:
                print(f"Requeuing {label} (attempt {job['retries']+1}) after None status...")
                time.sleep(120)
                queue.append(w)
                del jobs[label]
            continue

        if status == 'Completed':
            os.makedirs(w['out_dir'], exist_ok=True)
            try:
                rc.download(req_id, w['out_dir'])
                rc.purge_request(req_id)
                print(f"DONE: {label} -> {w['out_dir']}")
            except Exception as e:
                print(f"  [ERROR] Download or purge failed for {req_id} ({label}): {e}")
            del jobs[label]

        elif status in ('Error', 'Set for Purge'):
            job["retries"] += 1
            try:
                rc.purge_request(req_id)
                print(f"Purged errored {req_id} ({label})")
            except Exception as e:
                print(f"Failed to purge {req_id}: {e}")
            if job["retries"] > MAX_RETRIES:
                print(f"GIVING UP on {label} after {MAX_RETRIES} retries")
                del jobs[label]
            else:
                print(f"Waiting 120s before retrying {label} (attempt {job['retries']+1})...")
                time.sleep(120)
                queue.append(w)
                del jobs[label]

print(f"\n[{token_file}] Batch complete for jobs: {job_specs}.")