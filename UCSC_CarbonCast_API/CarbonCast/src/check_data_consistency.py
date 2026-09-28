import os
import csv
import sys

EIA_DIR = "/Users/prarthanapatil/Documents/EnergyAPI/CarbonCast/UCSC_OSRE_CC_automation_tool/eiaData"
WEATHER_DIR = "/Users/prarthanapatil/Documents/EnergyAPI/CarbonCast/UCSC_OSRE_CC_automation_tool/CarbonCast/processed_data"

EXPECTED_ROWS = 543

def count_rows(filepath):
    """Count data rows (excluding header). Returns -1 if unreadable."""
    try:
        with open(filepath, "r", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if len(rows) == 0:
            return 0
        # subtract header row if file has one
        return len(rows) - 1
    except Exception as e:
        print(f"  [ERROR reading {filepath}]: {e}")
        return -1

def audit_dir(label, dirpath):
    print(f"\n{'='*70}")
    print(f"AUDITING: {label}  ({dirpath})")
    print(f"{'='*70}")

    if not os.path.isdir(dirpath):
        print(f"  [MISSING DIRECTORY] {dirpath}")
        return []

    results = []
    for root, _, files in os.walk(dirpath):
        for fname in sorted(files):
            if not fname.lower().endswith(".csv"):
                continue
            fpath = os.path.join(root, fname)
            size_bytes = os.path.getsize(fpath)
            row_count = count_rows(fpath)

            status = "OK"
            if size_bytes == 0:
                status = "EMPTY_FILE"
            elif row_count == 0:
                status = "HEADER_ONLY_OR_EMPTY"
            elif row_count == -1:
                status = "UNREADABLE"
            elif row_count < EXPECTED_ROWS:
                status = f"SHORT (missing {EXPECTED_ROWS - row_count} rows)"
            elif row_count > EXPECTED_ROWS:
                status = f"EXCESS (+{row_count - EXPECTED_ROWS} rows)"

            results.append({
                "file": fpath,
                "size_bytes": size_bytes,
                "row_count": row_count,
                "status": status,
            })

    return results

def print_summary(results):
    problems = [r for r in results if r["status"] != "OK"]
    print(f"\n  Total files scanned : {len(results)}")
    print(f"  Files with issues   : {len(problems)}")
    if problems:
        print(f"\n  {'FILE':<90} {'ROWS':>6} {'STATUS'}")
        print(f"  {'-'*90} {'-'*6} {'-'*20}")
        for r in problems:
            short_name = r["file"].replace(EIA_DIR, "").replace(WEATHER_DIR, "")
            print(f"  {short_name:<90} {r['row_count']:>6}   {r['status']}")
    else:
        print("  All files match expected row count. ✅")

def main():
    eia_results = audit_dir("EIA DATA", EIA_DIR)
    weather_results = audit_dir("WEATHER DATA", WEATHER_DIR)

    print(f"\n\n{'#'*70}")
    print("SUMMARY")
    print(f"{'#'*70}")

    print("\n--- EIA DATA ---")
    print_summary(eia_results)

    print("\n--- WEATHER DATA ---")
    print_summary(weather_results)

    # Exit code non-zero if any problems found, useful for CI / scripting
    total_problems = len([r for r in eia_results + weather_results if r["status"] != "OK"])
    if total_problems > 0:
        print(f"\n⚠️  {total_problems} file(s) need attention before training.")
        sys.exit(1)
    else:
        print("\n✅ Dataset is consistent, safe to proceed to training.")
        sys.exit(0)

if __name__ == "__main__":
    main()
