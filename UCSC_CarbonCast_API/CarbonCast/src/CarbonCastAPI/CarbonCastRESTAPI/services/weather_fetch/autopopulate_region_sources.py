#!/usr/bin/env python3
"""
Patches prepare_grid_data_for_retraining.py's REGION_SOURCES dict by
reading every region's SOURCES list directly from firstTierConfig.json,
so no manual entry is needed for any region.
"""
import json
import re

FIRST_TIER_CONFIG = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src/firstTierConfig.json"
TARGET_FILE = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src/CarbonCastAPI/CarbonCastRESTAPI/services/weather_fetch/prepare_grid_data_for_retraining.py"

SKIP_KEYS = {
    "GENERAL_INFO", "REGION", "NUM_VAL_DAYS", "MODEL_SLIDING_WINDOW_LEN",
    "TRAINING_WINDOW_HOURS", "PREDICTION_WINDOW_HOURS", "MAX_PREDICTION_WINDOW_HOURS",
    "NUM_WEATHER_FEATURES", "NUMBER_OF_EXPERIMENTS_PER_REGION", "SAVED_MODEL_LOCATION",
    "ROW_START_FOR_2020", "ROW_END_FOR_2022", "SOURCE_FORECAST_ROW_END_FOR_2022",
    "TRAIN_TEST_PERIOD", "NUM_FEATURES_PER_SOURCE", "FIRST_TIER_ANN_MODEL_HYPERPARAMS",
    "IN_FILE_NAME_SUFFIX",
}

with open(FIRST_TIER_CONFIG) as f:
    config = json.load(f)

region_sources = {}
for key, val in config.items():
    if key in SKIP_KEYS or not isinstance(val, dict) or "SOURCES" not in val:
        continue
    region_sources[key] = [s.lower() for s in val["SOURCES"]]

print(f"Found SOURCES for {len(region_sources)} regions")

# Build the new REGION_SOURCES dict as Python source
lines = ["REGION_SOURCES = {\n"]
for region, sources in sorted(region_sources.items()):
    lines.append(f'    "{region}": {sources!r},\n')
lines.append("}\n")
new_block = "".join(lines)

with open(TARGET_FILE) as f:
    content = f.read()

# Replace the existing REGION_SOURCES = { ... } block
pattern = re.compile(r"REGION_SOURCES\s*=\s*\{.*?\n\}\n", re.DOTALL)
if pattern.search(content):
    content = pattern.sub(new_block, content)
    print("Replaced existing REGION_SOURCES block")
else:
    # insert after US_REGIONS block if not found
    content = content.replace("TRAINING_DATA_ROOT =", new_block + "\nTRAINING_DATA_ROOT =")
    print("Inserted new REGION_SOURCES block")

with open(TARGET_FILE, "w") as f:
    f.write(content)

print(f"Updated {TARGET_FILE}")