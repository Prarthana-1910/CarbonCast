import os
import csv
from datetime import datetime
from django.utils.timezone import make_aware, is_naive
from CarbonCastRESTAPI.models import EmissionActual, Forecast96

BASE_PATH = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/CI_forecast_data"

def parse_ts(raw):
    # handles both "2026-02-25T00:00:00.000000000" and simpler formats
    raw = raw.split(".")[0].replace("T", " ")
    dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    if is_naive(dt):
        dt = make_aware(dt)
    return dt

total_actual = 0
total_forecast = 0

for region in sorted(os.listdir(BASE_PATH)):
    region_path = os.path.join(BASE_PATH, region)
    if not os.path.isdir(region_path):
        continue

    for fname in os.listdir(region_path):
        if not fname.endswith(".csv"):
            continue

        fpath = os.path.join(region_path, fname)
        forecast_type = "direct" if "_direct_" in fname else "lifecycle"

        actual_batch = []
        forecast_batch = []

        with open(fpath, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = parse_ts(row["datetime"])

                actual_val = row.get("carbon_intensity_actual")
                forecast_val = row.get("avg_carbon_intensity_forecast")

                if actual_val not in (None, ""):
                    actual_batch.append(EmissionActual(
                        region=region,
                        ts=ts,
                        metric_type="carbon",
                        direct=float(actual_val) if forecast_type == "direct" else None,
                        lifecycle=float(actual_val) if forecast_type == "lifecycle" else None,
                        source_file=fname,
                        data={},
                    ))

                if forecast_val not in (None, ""):
                    forecast_batch.append(Forecast96(
                        region=region,
                        ts=ts,
                        value=float(forecast_val),
                        metric_type="carbon",
                        forecast_type=forecast_type,
                        forecast_horizon=168,
                    ))

        if actual_batch:
            EmissionActual.objects.bulk_create(actual_batch, ignore_conflicts=True)
            total_actual += len(actual_batch)

        if forecast_batch:
            Forecast96.objects.bulk_create(forecast_batch, batch_size=1000, ignore_conflicts=True)
            total_forecast += len(forecast_batch)

        print(f"{region}/{fname}: {len(actual_batch)} actual, {len(forecast_batch)} forecast rows")

print(f"\nTOTAL: {total_actual} EmissionActual rows, {total_forecast} Forecast96 rows")