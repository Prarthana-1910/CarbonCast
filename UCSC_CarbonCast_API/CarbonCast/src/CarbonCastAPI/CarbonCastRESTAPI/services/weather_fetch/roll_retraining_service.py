#!/usr/bin/env python3
"""
roll_retraining_window.py

Maintains a fixed-size rolling window in retraining_archive/ and
retraining_weather_downloads/: drops the oldest ~7 days of GRIB2 files,
keeping the total training pool size constant week over week.

NOT run this week — the first cycle just accumulates RDA (3mo) + this
week's NOMADS pull with no trimming. Run this starting the FOLLOWING week,
right after that week's fresh NOMADS pull is added.
"""
import os
import re
import glob
from datetime import datetime, timedelta

ARCHIVE_ROOTS = [
    "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/retraining_archive",
    "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/retraining_weather_downloads",
]

WINDOW_DAYS = 90  # fixed rolling window size — tune once, keep constant


def prune_oldest_week(dry_run=True):
    cutoff = datetime.now() - timedelta(days=WINDOW_DAYS)
    removed = 0

    for root in ARCHIVE_ROOTS:
        for filepath in glob.glob(f"{root}/*/*/*.grib2"):
            m = re.search(r"gfs\.0p25\.(\d{8})", os.path.basename(filepath))
            if not m:
                continue
            file_date = datetime.strptime(m.group(1), "%Y%m%d")
            if file_date < cutoff:
                if dry_run:
                    print(f"[DRY RUN] would remove: {filepath} (date {file_date.date()})")
                else:
                    os.remove(filepath)
                removed += 1

    print(f"{'Would remove' if dry_run else 'Removed'} {removed} files older than {cutoff.date()}")


if __name__ == "__main__":
    import sys
    dry_run = "--apply" not in sys.argv
    prune_oldest_week(dry_run=dry_run)