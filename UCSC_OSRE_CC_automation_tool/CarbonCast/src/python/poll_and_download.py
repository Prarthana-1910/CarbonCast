import rdams_client as rc, time, os

REQUEST_IDS = ["872198", "872201", "872202", "872203"]
DOWNLOAD_DIR = os.path.expanduser("~/CarbonCast_spring26/UCSC_OSRE_CC_automation_tool/CarbonCast/downloaded_files/CISO")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

while True:
    status = rc.get_status()
    requests = {str(r['request_index']): r for r in status.get('data', [])}
    all_done = True
    for rid in REQUEST_IDS:
        r = requests.get(rid, {})
        st = r.get('status', 'unknown')
        print(f"  {rid}: {st}")
        if st == 'completed':
            print(f"  -> Downloading {rid}...")
            rc.download(rid, DOWNLOAD_DIR)
        else:
            all_done = False
    if all_done:
        print("All done!")
        break
    print("Waiting 5 min...")
    time.sleep(300)
