#!/usr/bin/env python3
"""
build_final_training_dataset.py

Concatenates the old historical archive (processed_data/) with the new
retraining archive (retraining_archive_processed/) for a region, resolving
overlapping dates by preferring the NEWER retraining data (since it was
fetched more recently and is presumably more accurate/complete).

Also computes the exact 6-month train / 6-month test split parameters
for firstTierConfig.json / secondTierConfig.json, based on the real
combined date range.

Usage:
    python3 build_final_training_dataset.py --region BANC
"""
import os
import argparse
import pandas as pd
from datetime import timedelta

OLD_PROCESSED = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_OSRE_CC_automation_tool/CarbonCast/processed_data"
NEW_PROCESSED = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_OSRE_CC_automation_tool/CarbonCast/retraining_weather_processed"
FINAL_OUT = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src/CarbonCastAPI/CarbonCastRESTAPI/services/weekly_training/final_training_data"

VARIABLES = ["TEMP", "DPT", "DSWRF", "WIND_SPEED", "PCP"]


def concat_one_variable(region, var):
    old_path = os.path.join(OLD_PROCESSED, region, f"{region}_AVG_{var}.csv")
    new_path = os.path.join(NEW_PROCESSED, region, f"{region}_AVG_{var}.csv")

    if not os.path.exists(old_path):
        print(f"  MISSING old archive file: {old_path}")
        return None
    if not os.path.exists(new_path):
        print(f"  MISSING new archive file: {new_path}")
        return None

    old_df = pd.read_csv(old_path, parse_dates=["datetime"])
    new_df = pd.read_csv(new_path, parse_dates=["datetime"])

    if list(old_df.columns) != list(new_df.columns):
        print(f"  COLUMN MISMATCH for {var}:")
        print(f"    old: {list(old_df.columns)}")
        print(f"    new: {list(new_df.columns)}")
        return None

    # Prefer NEW data on any overlapping dates: drop overlapping rows from
    # old_df first, then concat, so new_df's values win.
    overlap_mask = old_df["datetime"].isin(new_df["datetime"])
    if overlap_mask.any():
        print(f"  {var}: dropping {overlap_mask.sum()} overlapping rows from OLD (new data wins)")
    old_df = old_df[~overlap_mask]

    combined = pd.concat([old_df, new_df], ignore_index=True)
    combined = combined.sort_values("datetime").reset_index(drop=True)

    # # Trim to the most recent 12 months (6mo train + 6mo test) only
    # max_date = combined["datetime"].max()
    # window_start = max_date - timedelta(days=365)
    # combined = combined[combined["datetime"] >= window_start].reset_index(drop=True)

    out_dir = os.path.join(FINAL_OUT, region)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{region}_AVG_{var}.csv")
    combined.to_csv(out_path, index=False)

    print(f"  {var}: old={len(old_df)} + new={len(new_df)} -> combined={len(combined)} rows -> {out_path}")
    return combined


def compute_split_config(combined_temp_df, max_train_months=6, max_test_months=6):
    max_date = combined_temp_df["datetime"].max()

    test_days = max_test_months * 30       # ~6 months
    train_days = max_train_months * 30     # ~6 months
    total_window_days = train_days + test_days

    window_start = max_date - timedelta(days=total_window_days)
    test_start = max_date - timedelta(days=test_days)

    print(f"Full archive range: {combined_temp_df['datetime'].min()} -> {max_date}")
    print(f"Using ONLY the most recent {total_window_days} days (6+6 months):")
    print(f"  Train: {window_start} -> {test_start}  ({train_days} days)")
    print(f"  Test:  {test_start} -> {max_date}  ({test_days} days)")

    dataset_limiter_hours = train_days * 24
    num_test_days = test_days

    print(f"\nConfig values to set:")
    print(f"  firstTierConfig.json  -> TRAIN_TEST_PERIOD.PERIOD_0.DATASET_LIMITER = {dataset_limiter_hours}")
    print(f"  firstTierConfig.json  -> TRAIN_TEST_PERIOD.PERIOD_0.NUM_TEST_DAYS  = {num_test_days}")
    print(f"  secondTierConfig.json -> NUM_TEST_DAYS = {num_test_days}")
    print(f"  NUM_VAL_DAYS: recommend ~15 (carved out of the {train_days}-day training portion)")

    return {
        "window_start": window_start,
        "test_start": test_start,
        "max_date": max_date,
        "train_days": train_days,
        "test_days": test_days,
        "dataset_limiter_hours": dataset_limiter_hours,
        "num_test_days": num_test_days,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", required=True)
    args = parser.parse_args()
    region = args.region

    print(f"=== Building final training dataset for {region} ===")
    results = {}
    for var in VARIABLES:
        results[var] = concat_one_variable(region, var)

    failed = [v for v, r in results.items() if r is None]
    if failed:
        print(f"\nFAILED: {failed} — fix these before proceeding.")
        return

    compute_split_config(results["TEMP"])
    print(f"\nAll variables combined successfully for {region}.")
    print(f"Final files in: {os.path.join(FINAL_OUT, region)}")


if __name__ == "__main__":
    main()