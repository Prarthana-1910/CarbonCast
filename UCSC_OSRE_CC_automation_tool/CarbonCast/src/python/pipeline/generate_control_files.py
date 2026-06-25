"""
Script 1: Generate RDA control files for all regions.
Edit TRAIN_START / TRAIN_END before running.
"""

import json
import os

# ── CONFIG ────────────────────────────────────────────────────────────────────
AUTOMATION_CONFIG = os.path.expanduser(
    "~/CarbonCast_spring26/UCSC_OSRE_CC_automation_tool/CarbonCast/config/automation_config.json"
)
CONTROL_FILES_DIR = os.path.expanduser(
    "~/CarbonCast_spring26/UCSC_OSRE_CC_automation_tool/CarbonCast/control_files"
)

# Set your desired date range here (YYYYMMDDHHMM format)
TRAIN_START = "202001010000"
TRAIN_END   = "202606250000"

# To run for a subset first, set REGIONS_TO_RUN = ["CISO", "ERCOT", "PJM"]
# Set to None to generate for ALL regions in config
REGIONS_TO_RUN = ["CISO", "ERCOT", "PJM"]  # change to None for all 58

PRODUCT_LINE = (
    "Analysis/3-hour Forecast/6-hour Forecast/9-hour Forecast/12-hour Forecast/"
    "15-hour Forecast/18-hour Forecast/21-hour Forecast/24-hour Forecast/"
    "27-hour Forecast/30-hour Forecast/33-hour Forecast/36-hour Forecast/"
    "39-hour Forecast/42-hour Forecast/45-hour Forecast/48-hour Forecast/"
    "51-hour Forecast/54-hour Forecast/57-hour Forecast/60-hour Forecast/"
    "63-hour Forecast/66-hour Forecast/69-hour Forecast/72-hour Forecast/"
    "75-hour Forecast/78-hour Forecast/81-hour Forecast/84-hour Forecast/"
    "87-hour Forecast/90-hour Forecast/93-hour Forecast/96-hour Forecast/"
    "99-hour Forecast/102-hour Forecast/105-hour Forecast/108-hour Forecast/"
    "111-hour Forecast/114-hour Forecast/117-hour Forecast/120-hour Forecast/"
    "123-hour Forecast/126-hour Forecast/129-hour Forecast/132-hour Forecast/"
    "135-hour Forecast/138-hour Forecast/141-hour Forecast/144-hour Forecast/"
    "147-hour Forecast/150-hour Forecast/153-hour Forecast/156-hour Forecast/"
    "159-hour Forecast/162-hour Forecast/165-hour Forecast/168-hour Forecast"
)

# variable name → (param string, level string)
VARIABLES = {
    "temp":  ("TMP/DPT",   "HTGL:2"),
    "wind":  ("UGRD/VGRD", "HTGL:10"),
    "dswrf": ("DSWRF",     "SFC:0"),
    "rain":  ("A PCP",     "SFC:0"),
}
# ─────────────────────────────────────────────────────────────────────────────

def load_regions(config_path):
    with open(config_path) as f:
        cfg = json.load(f)
    return cfg.get("regions", cfg)  # handle both wrapped and flat formats

def make_ctl(region, coords, var_name, date_start, date_end):
    nlat, slat, wlon, elon = coords
    param, level = VARIABLES[var_name]
    return (
        f"dataset=ds084.1\n"
        f"date={date_start}/to/{date_end}\n"
        f"datetype=init\n"
        f"param={param}\n"
        f"level={level}\n"
        f"nlat={nlat}\n"
        f"slat={slat}\n"
        f"wlon={wlon}\n"
        f"elon={elon}\n"
        f"product={PRODUCT_LINE}\n"
        f"targetdir=/glade/scratch\n"
    )

def main():
    os.makedirs(CONTROL_FILES_DIR, exist_ok=True)
    regions_cfg = load_regions(AUTOMATION_CONFIG)

    target_regions = REGIONS_TO_RUN if REGIONS_TO_RUN else list(regions_cfg.keys())
    count = 0
    for region in target_regions:
        if region not in regions_cfg:
            print(f"WARNING: {region} not found in config, skipping")
            continue
        coords = regions_cfg[region]["coordinates"]  # [nlat, slat, wlon, elon]
        for var_name in VARIABLES:
            fname = f"{region}_{var_name}_control.ctl"
            fpath = os.path.join(CONTROL_FILES_DIR, fname)
            content = make_ctl(region, coords, var_name, TRAIN_START, TRAIN_END)
            with open(fpath, "w") as f:
                f.write(content)
            count += 1

    print(f"Generated {count} control files in {CONTROL_FILES_DIR}")
    print(f"Regions: {target_regions}")
    print(f"Date range: {TRAIN_START} → {TRAIN_END}")

if __name__ == "__main__":
    main()
