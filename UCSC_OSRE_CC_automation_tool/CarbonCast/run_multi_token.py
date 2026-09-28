import sys
import os
import subprocess
import threading
import argparse
import time
import datetime


JOBS = [
("GB", "rain"),
]


print(f"Total in-progress jobs: {len(JOBS)}")

TOKENS = [
    "rdams_token.txt", "rdams_token2.txt", "rdams_token3.txt", "rdams_token4.txt",
    "rdams_token5.txt", "rdams_token6.txt", "rdams_token7.txt", "rdams_token8.txt",
]

log_lock = threading.Lock()

def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with log_lock:
        print(f"[{ts}] {msg}", flush=True)

# ── Same window logic as gen_and_submit_batch3.py, kept in sync ─────────────
def build_windows():
    from datetime import datetime, timedelta

    end_date = datetime(2026, 8, 16)
    start_date = end_date - timedelta(days=90)

    start = start_date.strftime("%Y%m%d0000")
    end = end_date.strftime("%Y%m%d0000")

    return [(start, end)]
WINDOWS = build_windows()
MIN_SIZE = 1_000_000

def already_done(out_dir, start):
    month_prefix = start[:8]
    if not os.path.exists(out_dir):
        return False
    for f in os.listdir(out_dir):
        if f.startswith(f"gfs.0p25.{month_prefix}"):
            fpath = os.path.join(out_dir, f)
            if os.path.getsize(fpath) > MIN_SIZE:
                return True
    return False

def count_pending(region, var):
    out_dir = f"/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/retraining_weather_downloads/{region}/{var}"
    pending = 0
    for start, end in WINDOWS:
        if not already_done(out_dir, start):
            pending += 1
    return pending
# ──────────────────────────────────────────────────────────────────────────

def worker(token_file, job_list, results):
    specs = [f"{region}:{var}" for region, var in job_list]
    label = f"{token_file}:{','.join(specs)}"
    start_time = time.time()
    log(f"STARTING {label}")
    try:
        result = subprocess.run(
            [sys.executable, "gen_and_submit_batch3.py", token_file] + specs,
            capture_output=False
        )
        elapsed = round(time.time() - start_time, 1)
        if result.returncode == 0:
            log(f"FINISHED {label} ({elapsed}s)")
            results.append((token_file, specs, "OK"))
        else:
            log(f"FAILED {label} (exit code {result.returncode}, {elapsed}s)")
            results.append((token_file, specs, f"FAILED (code {result.returncode})"))
    except Exception as e:
        log(f"EXCEPTION on {label}: {e}")
        results.append((token_file, specs, f"EXCEPTION: {e}"))

def distribute_by_workload(jobs_with_weight, num_tokens):
    """Greedy load-balance: always add the next job to the currently-lightest bucket."""
    buckets = [[] for _ in range(num_tokens)]
    bucket_loads = [0] * num_tokens
    # Largest jobs first -> better balance (classic greedy bin-packing)
    for region, var, weight in sorted(jobs_with_weight, key=lambda j: -j[2]):
        idx = bucket_loads.index(min(bucket_loads))
        buckets[idx].append((region, var))
        bucket_loads[idx] += weight
    return buckets, bucket_loads

def main():
    parser = argparse.ArgumentParser(description="Run region/variable jobs across 8 RDA tokens, load-balanced by actual pending work, skipping already-complete jobs.")
    parser.add_argument('--tokens', nargs='+', default=TOKENS, help="Token files to use")
    args = parser.parse_args()
    tokens = args.tokens

    log(f"Checking disk for already-downloaded windows across {len(JOBS)} jobs...")
    jobs_with_weight = []
    skipped = []
    for region, var in JOBS:
        pending = count_pending(region, var)
        if pending == 0:
            skipped.append((region, var))
        else:
            jobs_with_weight.append((region, var, pending))

    if skipped:
        log(f"Skipping {len(skipped)} already-complete jobs: {skipped}")

    if not jobs_with_weight:
        log("Nothing pending — all jobs already complete. Exiting.")
        return

    buckets, loads = distribute_by_workload(jobs_with_weight, len(tokens))

    log(f"Distributing {len(jobs_with_weight)} pending jobs across {len(tokens)} tokens (balanced by pending window count):")
    for tk, bucket, load in zip(tokens, buckets, loads):
        log(f"  {tk}: {len(bucket)} jobs, {load} pending windows -> {bucket}")

    results = []
    threads = []
    for token_file, bucket in zip(tokens, buckets):
        if not bucket:
            continue
        t = threading.Thread(target=worker, args=(token_file, bucket, results))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    log(f"\n{'='*80}")
    log("ALL TOKEN QUEUES COMPLETE")
    log(f"{'='*80}")

    ok = [r for r in results if r[2] == "OK"]
    failed = [r for r in results if r[2] != "OK"]

    log(f"Succeeded: {len(ok)}/{len(results)}  (Skipped as already-complete: {len(skipped)})")
    if failed:
        log("Failed jobs:")
        for token_file, specs, status in failed:
            log(f"  [{token_file}] {specs}: {status}")

if __name__ == "__main__":
    main()