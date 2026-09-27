#!/usr/bin/env python3
"""
fetch_grib_nomads.py — Downloads raw region-clipped GFS GRIB2 files from NOAA
NOMADS, matching the exact file layout process_weather_data.py expects:

    DOWNLOAD_DIR/<region>/<wind|temp|dswrf|rain>/gfs.0p25.<YYYYMMDD><HH>.f<fcst>.grib2

Lives in CarbonCastAPI as part of the real-time inference pipeline, but by
default still writes into the automation tool's existing downloaded_files/
directory so process_weather_data.py works unmodified. Override with
--download-dir if you consolidate paths later.
"""

import os
import sys
import time
import logging
import argparse
import requests
from pathlib import Path
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("fetch_grib_nomads")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

NOMADS_BASE = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"

# Comprehensive region coordinate mappings extracted from download_files.py
REGION_COORDINATES = {
    # North American Regions
    "CISO": (42, 32, -124.75, -113.5),
    "PJM": (43, 34.25, -91, -73.5),
    "ERCO": (36.5, 25.25, -104.5, -93.25),
    "ISNE": (48, 40, -74.25, -66.5),
    "MISO": (50.00, 28.50, -107.75, -81.75),
    "BPAT": (49.50, 39.50, -125.25, -105.50),
    "SWPP": (49.50, 30.25, -107.75, -89.50),
    "SOCO": (35.50, 29.25, -90.50, -80.25),
    "FPL": (31.25, 24.00, -83.50, -79.50),
    "NYIS": (45.50, 40.00, -80.25, -71.25),
    "BANC": (41.75, 37.00, -124.00, -120.00),
    "LDWP": (38.00, 33.25, -119.00, -117.00),
    "TIDC": (38.25, 36.75, -121.75, -119.75),
    "DUK": (37.00, 33.00, -84.75, -77.75),
    "SC": (35.25, 31.50, -82.75, -78.00),
    "SCEG": (35.25, 31.50, -83.00, -78.75),
    "SPA": (40.75, 34.25, -98.00, -89.00),
    "FMPP": (30.75, 24.00, -83.00, -79.50),
    "FPC": (31.25, 25.75, -86.50, -80.00),
    "TAL": (31.25, 29.75, -84.75, -83.50),
    "TEC": (29.00, 27.00, -83.25, -81.25),
    "AECI": (41.75, 34.25, -98.50, -88.50),
    "LGEE": (39.50, 36.00, -89.75, -82.25),
    "DOPD": (49.50, 46.75, -120.75, -118.25),
    "GCPD": (48.50, 46.25, -120.50, -118.50),
    "GRID": (46.25, 44.75, -119.75, -118.25),
    "IPCO": (47.25, 41.50, -120.50, -111.00),
    "NEVP": (42.50, 34.50, -122.00, -111.00),
    "NWMT": (49.50, 43.25, -116.50, -103.50),
    "PACE": (45.50, 33.00, -115.75, -104.25),
    "PACW": (47.50, 38.75, -124.75, -115.75),
    "PGE": (46.50, 44.25, -124.25, -121.25),
    "PSCO": (41.75, 35.75, -109.50, -102.00),
    "PSEI": (49.50, 45.75, -123.75, -119.75),
    "SCL": (48.25, 47.00, -123.00, -121.75),
    "TPWR": (48.25, 45.75, -124.00, -120.50),
    "WACM": (48.00, 35.50, -114.50, -95.75),
    "AZPS": (36.75, 30.75, -115.25, -108.75),
    "EPE": (34.00, 26.75, -108.75, -98.25),
    "PNM": (44.50, 30.75, -123.50, -101.50),
    "SRP": (34.50, 32.00, -113.75, -110.50),
    "TEPC": (36.75, 31.25, -115.25, -110.00),
    "WALC": (44.00, 30.75, -124.25, -105.00),
    "TVA": (38.00, 31.75, -90.75, -81.25),
    
    # European Regions
    "AL": (42.75, 39.50, 19.25, 21.00),
    "AT": (49.00, 46.50, 9.50, 17.00),
    "BE": (51.50, 49.50, 2.50, 6.25),
    "BG": (44.25, 41.25, 22.25, 28.50),
    "HR": (46.50, 42.50, 13.75, 19.50),
    "DK": (57.75, 54.50, 7.50, 13.25),
    "EE": (59.50, 57.50, 23.25, 28.25),
    "FI": (70.00, 59.75, 20.50, 31.50),
    "FR": (51.25, 42.25, -5.25, 8.25),
    "DE": (55.25, 47.25, 5.75, 15),
    "GR": (41.75, 35.00, 20.25, 26.50),
    "HU": (48.50, 45.75, 16.25, 22.75),
    "IE": (55.25, 51.75, -10.00, -6.00),
    "IT": (47.00, 36.50, 6.75, 18.50),
    "LV": (58.00, 55.50, 21.00, 28.25),
    "LT": (56.25, 54.00, 21.00, 26.50),
    "NL": (53.50, 50.75, 3.25, 7.00),
    "PL": (54.75, 49, 14, 24),
    "PT": (42.75, 36.50, -10.00, -5.75),
    "RO": (48.25, 43.75, 20.25, 29.50),
    "RS": (46.25, 42.25, 18.75, 23.00),
    "SK": (49.50, 47.75, 16.75, 22.50),
    "SI": (46.75, 45.50, 13.75, 16.50),
    "ES": (43.75, 36.00, -9.25, 3.50),
    "SE": (69, 55.25, 11.25, 21.25),
    "CH": (47.75, 45.75, 6.00, 10.50),
    "CZ": (51.00, 48.50, 12.25, 18.75),
    "GB": (61, 49.75, -8.25, 2.25)
}

FCST = list(range(0, 169, 3))
FCST_AVG_ACC = list(range(3, 169, 3))

VAR_GROUPS = {
    "temp": {
        "params": {"var_TMP": "on", "var_DPT": "on"},
        "level": {"lev_2_m_above_ground": "on"},
        "hours": FCST,
    },
    "wind": {
        "params": {"var_UGRD": "on", "var_VGRD": "on"},
        "level": {"lev_10_m_above_ground": "on"},
        "hours": FCST,
    },
    "dswrf": {
        "params": {"var_DSWRF": "on"},
        "level": {"lev_surface": "on"},
        "hours": FCST_AVG_ACC,
    },
    "rain": {
        "params": {"var_APCP": "on"},
        "level": {"lev_surface": "on"},
        "hours": FCST_AVG_ACC,
    },
}


def get_latest_gfs_cycle(target_date=None, target_hour=None):
    if target_date and target_hour:
        return target_date, target_hour
    now = datetime.now(timezone.utc)
    cycle_hour = (now.hour // 6) * 6
    if (now.hour - cycle_hour) < 4:
        cycle_hour -= 6
    if cycle_hour < 0:
        cycle_hour += 24
        now = now - timedelta(days=1)
    return now.strftime("%Y%m%d"), f"{cycle_hour:02d}"


def build_url(date_str, cycle, fhour, group_config, bbox):
    fhour_str = f"f{fhour:03d}"
    filename = f"gfs.t{cycle}z.pgrb2.0p25.{fhour_str}"
    nlat, slat, wlon, elon = bbox
    params = {
        "dir": f"/gfs.{date_str}/{cycle}/atmos",
        "file": filename,
        "subregion": "on",
        "leftlon": wlon,
        "rightlon": elon,
        "toplat": nlat,
        "bottomlat": slat,
    }
    params.update(group_config["params"])
    params.update(group_config["level"])
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{NOMADS_BASE}?{query}"


def download_one(url, out_path, retries=3):
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            if b"<html" in resp.content[:200].lower() or len(resp.content) < 100:
                logger.warning(f"  Not ready / too small (attempt {attempt}/{retries})")
                time.sleep(5)
                continue
            with open(out_path, "wb") as f:
                f.write(resp.content)
            return True
        except requests.RequestException as e:
            logger.warning(f"  Attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(5)
    return False


def fetch_region(region, download_dir, target_date=None, target_hour=None):
    if region not in REGION_COORDINATES:
        logger.error(f"No coordinates found for region '{region}'. Add it to REGION_COORDINATES.")
        return False

    bbox = REGION_COORDINATES[region]
    date_str, cycle = get_latest_gfs_cycle(target_date, target_hour)
    logger.info(f"GFS cycle: {date_str} {cycle}z, region={region}, bbox(nlat,slat,wlon,elon)={bbox}")

    total_ok, total_fail = 0, 0

    for var_name, group_config in VAR_GROUPS.items():
        out_dir = Path(download_dir) / region / var_name
        out_dir.mkdir(parents=True, exist_ok=True)

        for fhour in group_config["hours"]:
            fname = f"gfs.0p25.{date_str}{cycle}.f{fhour:03d}.grib2"
            out_path = out_dir / fname

            if out_path.exists() and out_path.stat().st_size > 0:
                total_ok += 1
                continue

            url = build_url(date_str, cycle, fhour, group_config, bbox)
            logger.info(f"[{var_name}] fetching f{fhour:03d} -> {fname}")
            if download_one(url, str(out_path)):
                total_ok += 1
            else:
                logger.error(f"  FAILED: {var_name} f{fhour:03d}")
                total_fail += 1
            time.sleep(0.5)

    logger.info(f"Done. {total_ok} files ok, {total_fail} failed.")
    return total_fail == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", required=True)
    parser.add_argument(
        "--download-dir", default=None,
        help="Defaults to the automation tool's existing downloaded_files directory",
    )
    parser.add_argument("--date", default=None, help="YYYYMMDD, e.g. 20260816")
    parser.add_argument("--hour", default=None, help="00/06/12/18")
    args = parser.parse_args()

    download_dir = args.download_dir or (
        "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/"
        "UCSC_CarbonCast_API/CarbonCast/realtime_weather_downloads"
    )

    ok = fetch_region(args.region, download_dir, target_date=args.date, target_hour=args.hour)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()