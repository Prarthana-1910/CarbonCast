import sys, os, re, time
sys.path.insert(0,'src/python')
import rdams_client as rc

MAX_CONCURRENT = 10

if len(sys.argv) < 3:
    print("Usage: python3 gen_and_submit_batch3.py REGION VAR")
    print("VAR must be one of: dswrf rain temp wind")
    sys.exit(1)

region, var = sys.argv[1], sys.argv[2]

PARAM_LEVEL = {
    "dswrf": ("DSWRF",     "SFC:0"),
    "rain":  ("A PCP",     "SFC:0"),
    "temp":  ("TMP/DPT",   "HTGL:2"),
    "wind":  ("U GRD/V GRD", "HTGL:10"),
}
if var not in PARAM_LEVEL:
    print(f"Unknown var {var}")
    sys.exit(1)
param, level = PARAM_LEVEL[var]

# ── Correct product vocabulary per variable type ──────────────────────────────
# temp/wind: instantaneous, use standard forecast labels
# dswrf:     3-hr average windows  (RDA rejects "X-hour Forecast" for this)
# rain:      3-hr accumulation windows (same issue)

def _make_product(template, hours=range(3, 169, 3)):
    return "/".join(template.format(a=h-3, b=h) for h in hours)

if var == "dswrf":
    product = _make_product("{a}-{b} hour ave fcst")
elif var == "rain":
    product = _make_product("{a}-{b} hour acc fcst")
else:  # temp, wind
    product = "Analysis/" + "/".join(f"{h}-hour Forecast" for h in range(3, 169, 3))

# ─────────────────────────────────────────────────────────────────────────────

src_ctl = f"control_files/{region}_{var}_chunk1_control.ctl"
if not os.path.exists(src_ctl):
    print(f"Can't find {src_ctl} to read bbox from")
    sys.exit(1)

bbox = {}
for line in open(src_ctl):
    m = re.match(r"^(nlat|slat|wlon|elon)=(.+)$", line.strip())
    if m:
        bbox[m.group(1)] = m.group(2)

starts = []
y, m = 2024, 12
while (y, m) <= (2026, 5):
    starts.append((y, m))
    m += 3
    if m > 12:
        m -= 12
        y += 1

windows = []
for i, (y, m) in enumerate(starts):
    start = f"{y}{m:02d}010000"
    em, ey = m + 3, y
    if em > 12:
        em -= 12
        ey += 1
    if (ey, em) > (2026, 5) or (ey == 2026 and em > 5):
        end = "202605310000"
    else:
        end = f"{ey}{em:02d}010000"
    windows.append((start, end))
    if end == "202605310000":
        break

out_dir = f"downloaded_files/{region}/{var}"

def already_done(start):
    month_prefix = start[:8]
    if not os.path.exists(out_dir):
        return False
    return any(f.startswith(f"gfs.0p25.{month_prefix}") for f in os.listdir(out_dir))

pending = [(i, s, e) for i, (s, e) in enumerate(windows, 1) if not already_done(s)]
if not pending:
    print(f"ALL DONE already: {region} {var}")
    sys.exit(0)

print(f"Pending windows for {region} {var}: {[p[0] for p in pending]}")

def write_ctl(i, start, end):
    ctl_name = f"{region}_{var}_3m{i}"
    ctl_path = f"control_files/{ctl_name}_control.ctl"
    with open(ctl_path, "w") as f:
        f.write(f"""dataset=ds084.1
date={start}/to/{end}
datetype=init
param={param}
level={level}
nlat={bbox['nlat']}
slat={bbox['slat']}
wlon={bbox['wlon']}
elon={bbox['elon']}
product={product}
""")
    return ctl_name, ctl_path

def get_open_count():
    try:
        r = rc.get_status()
        return len([x for x in r.get('data', []) if x.get('status') not in ('Error',)])
    except Exception:
        return 0

def submit(ctl_path, label):
    print(f"Submitting {label}...")
    result = rc.submit(ctl_path)
    if not result or result.get('status') != 'ok':
        print(f"SUBMIT FAILED for {label}: {result}")
        return None
    req_id = int(result['data'].get('request_index') or result['data'].get('request_id'))
    print(f"  {label} -> request_index {req_id}")
    return req_id

def find_existing_request(start, end):
    try:
        r = rc.get_status()
    except Exception:
        return None
    start_fmt = f"{start[:4]}-{start[4:6]}-{start[6:8]} {start[8:10]}:{start[10:12]}"
    end_fmt = f"{end[:4]}-{end[4:6]}-{end[6:8]} {end[8:10]}:{end[10:12]}"
    nlat_fmt = f"nlat={bbox['nlat']}"
    slat_fmt = f"slat={bbox['slat']}"
    for x in r.get('data', []):
        rinfo = x.get('rinfo', '')
        status = x.get('status')
        if status == 'Error':
            continue
        if (start_fmt in rinfo and end_fmt in rinfo
                and nlat_fmt in rinfo and slat_fmt in rinfo):
            return int(x.get('request_index')), status
    return None

def wait_for_slot():
    while get_open_count() >= MAX_CONCURRENT:
        print(f"At/above {MAX_CONCURRENT} open requests, waiting 60s...")
        time.sleep(60)

jobs = {}
queue = list(pending)
MAX_RETRIES = 3

def submit_next():
    if not queue:
        return
    i, start, end = queue.pop(0)
    label, ctl_path = write_ctl(i, start, end)

    existing = find_existing_request(start, end)
    if existing:
        req_id, status = existing
        print(f"Found existing request {req_id} ({status}) for {label}, reusing.")
        jobs[label] = {"i": i, "start": start, "end": end, "req_id": req_id, "retries": 0}
        return

    wait_for_slot()
    req_id = submit(ctl_path, label)
    if req_id:
        jobs[label] = {"i": i, "start": start, "end": end, "req_id": req_id, "retries": 0}
    else:
        print(f"Could not submit {label}, will retry later.")
        queue.append((i, start, end))

while queue and len(jobs) < MAX_CONCURRENT:
    submit_next()

print(f"\nSubmitted {len(jobs)} requests, polling until all resolved...")

while jobs or queue:
    if queue and len(jobs) < MAX_CONCURRENT:
        submit_next()

    time.sleep(30)
    for label in list(jobs.keys()):
        job = jobs[label]
        req_id = job["req_id"]
        r = rc.get_status(req_id)
        status = r['data'].get('status') if isinstance(r['data'], dict) else r['data'][0].get('status')
        print(f"  [{label}] {req_id}: {status}")

        if status == 'Completed':
            os.makedirs(out_dir, exist_ok=True)
            rc.download(req_id, out_dir)
            rc.purge_request(req_id)
            print(f"DONE: {label} -> {out_dir}")
            del jobs[label]

        elif status == 'Error':
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
                queue.append((job["i"], job["start"], job["end"]))
                del jobs[label]

print(f"\nBatch complete for {region} {var}.")