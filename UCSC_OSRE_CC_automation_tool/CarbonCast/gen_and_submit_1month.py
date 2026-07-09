import sys, os, re, time
sys.path.insert(0,'src/python')
import rdams_client as rc

if len(sys.argv) < 3:
    print("Usage: python3 gen_and_submit_3month.py REGION VAR")
    print("VAR must be one of: dswrf rain temp wind")
    sys.exit(1)

region, var = sys.argv[1], sys.argv[2]

PARAM_LEVEL = {
    "dswrf": ("DSWRF", "SFC:0"),
    "rain":  ("A PCP", "SFC:0"),
    "temp":  ("TMP/DPT", "HTGL:2"),
    "wind":  ("U GRD/V GRD", "HTGL:10"),
}
if var not in PARAM_LEVEL:
    print(f"Unknown var {var}")
    sys.exit(1)
param, level = PARAM_LEVEL[var]

src_ctl = f"control_files/{region}_{var}_chunk1_control.ctl"
if not os.path.exists(src_ctl):
    print(f"Can't find {src_ctl} to read bbox from")
    sys.exit(1)

bbox = {}
for line in open(src_ctl):
    m = re.match(r"^(nlat|slat|wlon|elon)=(.+)$", line.strip())
    if m:
        bbox[m.group(1)] = m.group(2)

product = "Analysis/" + "/".join(f"{h}-hour Forecast" for h in range(3, 169, 3))

starts = []
y, m = 2024, 12
while (y, m) <= (2026, 5):
    starts.append((y, m))
    m += 1
    if m > 12:
        m -= 12
        y += 1

windows = []
for i, (y, m) in enumerate(starts):
    start = f"{y}{m:02d}010000"
    em, ey = m + 1, y
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

def submit_and_wait(ctl_path, label):
    print(f"Submitting {label}...")
    result = rc.submit(ctl_path)
    if not result or result.get('status') != 'ok':
        print(f"SUBMIT FAILED: {result}")
        return False
    req_id = int(result['data']['request_id'])
    print(f"Got request_id {req_id}, polling...")
    while True:
        time.sleep(30)
        r = rc.get_status(req_id)
        status = r['data'].get('status') if isinstance(r['data'], dict) else r['data'][0].get('status')
        print(f"  status: {status}")
        if status == 'Completed':
            out_dir = f"downloaded_files/{region}/{var}"
            os.makedirs(out_dir, exist_ok=True)
            rc.download(req_id, out_dir)
            rc.purge_request(req_id)
            print(f"DONE: {label} -> {out_dir}")
            return True
        if status == 'Error':
            print(f"ERROR on {req_id} ({label}), not purging -- check manually")
            return False

for i, (start, end) in enumerate(windows, 1):
    out_dir = f"downloaded_files/{region}/{var}"
    month_prefix = start[:8]  # e.g. "20250801"
    already_done = False
    if os.path.exists(out_dir):
        for fname in os.listdir(out_dir):
            if fname.startswith(f"gfs.0p25.{month_prefix}"):
                already_done = True
                break
    if already_done:
        print(f"SKIP: {region}_{var} for {month_prefix} already downloaded")
        continue
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
    ok = submit_and_wait(ctl_path, ctl_name)
    if not ok:
        print(f"Stopping -- {ctl_name} failed. Fix and rerun manually for remaining windows.")
        sys.exit(1)

print(f"ALL DONE: {region} {var} -- all 3-month windows completed.")
