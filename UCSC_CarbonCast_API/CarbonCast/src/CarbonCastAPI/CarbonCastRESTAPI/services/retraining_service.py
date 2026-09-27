"""
Weekly CarbonCast retraining orchestration.

This service prepares the database-backed inputs expected by the existing
CarbonCast scripts, optionally invokes those scripts when the runtime is
configured for full ML execution, and persists a complete 168-hour forecast
batch to Forecast96. The DB write path is deliberately independent of the ML
call so stale or missing script artifacts do not erase the last usable forecast.
"""

import csv
import logging
import os
import tempfile
import uuid
from datetime import timedelta, timezone
from pathlib import Path

from django.utils import timezone as tz

logger = logging.getLogger(__name__)

FORECAST_HORIZON_HOURS = int(os.environ.get("CARBONCAST_FORECAST_HORIZON_HOURS", "168"))
TRAINING_WINDOW_DAYS = int(os.environ.get("CARBONCAST_TRAINING_WINDOW_DAYS", "180"))
RECENT_AVERAGE_DAYS = int(os.environ.get("CARBONCAST_BASELINE_LOOKBACK_DAYS", "28"))
ENERGY_SOURCES = ("coal", "nat_gas", "nuclear", "oil", "hydro", "solar", "wind", "other")


def run_retraining() -> dict:
    """Execute the weekly pipeline for all configured regions with actuals."""
    from CarbonCastRESTAPI.models import EmissionActual, ModelRun

    configured_regions = {
        r.strip().upper()
        for r in os.environ.get("PIPELINE_REGIONS", "").split(",")
        if r.strip()
    }
    regions = list(
        EmissionActual.objects.values_list('region', flat=True).distinct().order_by('region')
    )
    if configured_regions:
        regions = [r for r in regions if r in configured_regions]

    results = {
        'regions_processed': 0,
        'regions_failed': 0,
        'forecast_horizon': FORECAST_HORIZON_HOURS,
    }

    for region in regions:
        run = ModelRun.objects.create(
            region=region,
            model_name='pending',
            status='running',
        )
        try:
            metrics = _retrain_region(region, run)
            run.status = 'completed'
            run.metrics = metrics
            run.run_completed = tz.now()
            run.save(update_fields=['status', 'metrics', 'run_completed'])
            results['regions_processed'] += 1
        except Exception as exc:
            logger.exception("Retraining failed for %s", region)
            run.status = 'failed'
            run.metrics = {'error': str(exc)}
            run.run_completed = tz.now()
            run.save(update_fields=['status', 'metrics', 'run_completed'])
            results['regions_failed'] += 1

    return results


def _retrain_region(region: str, model_run):
    """Prepare artifacts, pick a runner, invoke configured ML, write one batch."""
    from CarbonCastRESTAPI.models import EmissionActual
    from CarbonCastRESTAPI.services.model_runners import select_runner_for_region

    # Always pull the longest configured window — individual runners trim it down
    # to whatever lookback they need (CarbonCast: 180d, LiteCast: 14d).
    training_start = tz.now() - timedelta(days=TRAINING_WINDOW_DAYS)
    emissions = list(
        EmissionActual.objects.filter(region=region, ts__gte=training_start).order_by('ts')
    )
    if not emissions:
        raise ValueError(f"No EmissionActual rows available for {region}")

    runner = select_runner_for_region(region, emissions)
    model_run.model_name = runner.name
    model_run.save(update_fields=['model_name'])

    batch_id = uuid.uuid4().hex[:12]
    override = os.environ.get("CARBONCAST_FORECAST_START_OVERRIDE")
    forecast_start = datetime.fromisoformat(override) if override else _next_utc_hour()
    artifact_dir = _artifact_dir(batch_id, region)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    weather_source, weather_rows = _latest_weather_rows(region, forecast_start)
    emissions_csv = _export_emissions_csv(artifact_dir, emissions)
    weather_csv = _export_weather_csv(artifact_dir, weather_rows)

    model_run.weather_source = weather_source
    model_run.config = {
        'region': region,
        'batch_id': batch_id,
        'forecast_horizon': FORECAST_HORIZON_HOURS,
        'training_window_days': TRAINING_WINDOW_DAYS,
        'model_name': runner.name,
        'model_lookback_days': runner.lookback_days,
        'emissions_csv': str(emissions_csv),
        'weather_csv': str(weather_csv) if weather_csv else None,
        'run_ml': _truthy(os.environ.get("CARBONCAST_RUN_ML")),
    }
    model_run.model_artifact_path = str(artifact_dir)
    model_run.save(update_fields=['weather_source', 'config', 'model_artifact_path'])

    ml_result = _try_run_existing_carboncast(region, forecast_start, artifact_dir)
    real_time_dir = os.environ.get("CARBONCAST_REAL_TIME_DIR", str(artifact_dir))
    ml_persist_result = _persist_ml_forecast(region, ml_result, batch_id, real_time_dir, forecast_start)
    ml_result['persisted'] = ml_persist_result
    forecast_counts = _persist_baseline_forecast(
        region=region,
        emissions=emissions,
        batch_id=batch_id,
        forecast_start=forecast_start,
        weather_source=weather_source,
        artifact_dir=artifact_dir,
        runner=runner,
        weather_rows=weather_rows,
    )

    return {
        'method': f'{runner.name}_ml_plus_db_baseline' if ml_result.get('attempted') else f'{runner.name}_db_baseline',
        'model_name': runner.name,
        'model_lookback_days': runner.lookback_days,
        'batch_id': batch_id,
        'weather_source': weather_source,
        'weather_rows': len(weather_rows),
        'emission_rows': len(emissions),
        'forecast_rows': forecast_counts,
        'ml_result': ml_result,
    }


def _next_utc_hour():
    now = tz.now().astimezone(timezone.utc)
    return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def _artifact_dir(batch_id, region):
    root = Path(os.environ.get("CARBONCAST_ARTIFACT_DIR", tempfile.gettempdir()))
    return root / "carboncast_pipeline" / batch_id / region


def _latest_weather_rows(region, forecast_start):
    from CarbonCastRESTAPI.models import WeatherForecast

    latest = (
        WeatherForecast.objects.filter(region=region)
        .order_by('-forecast_created')
        .values('forecast_created', 'source')
        .first()
    )
    if not latest:
        return 'none', []

    rows = list(
        WeatherForecast.objects.filter(
            region=region,
            forecast_created=latest['forecast_created'],
            forecast_target__gte=forecast_start,
            forecast_target__lt=forecast_start + timedelta(hours=FORECAST_HORIZON_HOURS),
        ).order_by('forecast_target', 'variable')
    )
    return latest['source'], rows


def _export_emissions_csv(artifact_dir, emissions):
    path = artifact_dir / "emissions_training.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "UTC time",
            "creation_time (UTC)",
            "version",
            "region_code",
            "carbon_intensity_avg_lifecycle",
            "carbon_intensity_avg_direct",
            *ENERGY_SOURCES,
        ])
        for row in emissions:
            data = row.data or {}
            writer.writerow([
                row.ts.isoformat(),
                data.get("creation_time (UTC)") or data.get("creation_time") or "",
                data.get("version") or "",
                row.region,
                row.lifecycle if row.lifecycle is not None else "",
                row.direct if row.direct is not None else "",
                *[data.get(source, "") for source in ENERGY_SOURCES],
            ])
    return path


def _export_weather_csv(artifact_dir, weather_rows):
    if not weather_rows:
        return None

    path = artifact_dir / "weather_forecast_168h.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["forecast_created", "forecast_target", "region_code", "variable", "value", "source"])
        for row in weather_rows:
            writer.writerow([
                row.forecast_created.isoformat(),
                row.forecast_target.isoformat(),
                row.region,
                row.variable,
                row.value if row.value is not None else "",
                row.source,
            ])
    return path


def _try_run_existing_carboncast(region, forecast_start, artifact_dir):
    """
    Invoke existing real-time CarbonCast functions when explicitly configured.

    The historical scripts require saved models/config/min-max artifacts that
    differ by deployment, so v1 leaves this disabled unless CARBONCAST_RUN_ML is
    true and CARBONCAST_CONFIG_FILE points to a runtime config.
    """
    if not _truthy(os.environ.get("CARBONCAST_RUN_ML")):
        return {'attempted': False, 'status': 'disabled'}

    config_file = os.environ.get("CARBONCAST_CONFIG_FILE")           # first tier
    second_tier_config_file = os.environ.get("CARBONCAST_SECOND_TIER_CONFIG_FILE", config_file)  # second tier
    if not config_file:
        return {'attempted': True, 'status': 'skipped_missing_config'}

    try:
        import sys
        import csv as csv_module
        SRC_DIR = "/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src"
        if SRC_DIR not in sys.path:
            sys.path.insert(0, SRC_DIR)

        from firstTierForecasts import runFirstTierInRealTime
        from secondTierForecasts import runSecondTierInRealTime

        creation_time = tz.now().astimezone(timezone.utc).isoformat()
        start_date = forecast_start.date().isoformat()
        real_time_dir = os.environ.get("CARBONCAST_REAL_TIME_DIR", str(artifact_dir))
        weather_dir = os.environ.get("CARBONCAST_REAL_TIME_WEATHER_DIR", str(artifact_dir))
        version = os.environ.get("CARBONCAST_MODEL_VERSION", "db-pipeline-v1")

        def _row_count(csv_path):
            if not os.path.exists(csv_path):
                return None
            with open(csv_path) as f:
                return sum(1 for _ in csv_module.reader(f)) - 1  # subtract header

        # --- Try yesterday first, fall back to earlier days if thin ---
        electricity_date = None
        for days_back in range(1, 15):
            candidate_date = (forecast_start - timedelta(days=days_back)).date().isoformat()
            candidate_path = os.path.join(real_time_dir, region, f"{region}_{candidate_date}.csv")
            count = _row_count(candidate_path)

            if count is None:
                continue
            if count < 24:
                continue

            electricity_date = candidate_date
            if days_back > 1:
                logger.info("[%s] Using fallback date %s for electricity data", region, candidate_date)
            break

        if electricity_date is None:
            # Fall back to any available staged file with 24 hours
            region_dir = os.path.join(real_time_dir, region)
            if os.path.isdir(region_dir):
                for f in sorted(os.listdir(region_dir), reverse=True):
                    if f.startswith(f"{region}_") and f.endswith(".csv") and not ("emissions" in f or "forecast" in f or "weather" in f):
                        cand_date = f.replace(f"{region}_", "").replace(".csv", "")
                        if _row_count(os.path.join(region_dir, f)) >= 24:
                            electricity_date = cand_date
                            logger.info("[%s] Using latest available staged date %s for electricity data", region, electricity_date)
                            break

        # --- Check weather has a full day available; fall back to yesterday's
        # staged forecast if today's is thin (e.g. partial NOMADS download) ---
        weather_path = os.path.join(weather_dir, region, f"{region}_weather_forecast_{start_date}.csv")
        weather_count = _row_count(weather_path)

        if weather_count is None or weather_count < 24:
            yesterday_date = (forecast_start - timedelta(days=1)).date().isoformat()
            fallback_weather_path = os.path.join(weather_dir, region, f"{region}_weather_forecast_{yesterday_date}.csv")
            fallback_count = _row_count(fallback_weather_path)

            if fallback_count is not None and fallback_count >= 24:
                logger.warning(
                    "[%s] Weather data for %s only has %s hours — falling back to "
                    "yesterday's staged forecast (%s, %s hours).",
                    region, start_date, weather_count, yesterday_date, fallback_count,
                )
                weather_path = fallback_weather_path
                start_date = yesterday_date  # runFirstTierInRealTime reads this file by start_date
            else:
                logger.warning(
                    "[%s] Weather data for %s only has %s hours, and yesterday's fallback "
                    "(%s) is also unavailable/thin (%s hours) — skipping ML inference this cycle.",
                    region, start_date, weather_count, yesterday_date, fallback_count,
                )
                return {'attempted': True, 'status': 'skipped_thin_weather_data'}

        if electricity_date is None:
            logger.warning(
                "[%s] No usable electricity data available — skipping ML inference this cycle. "
                "Baseline forecast will still be used.",
                region,
            )
            return {'attempted': True, 'status': 'skipped_thin_data'}

        first_tier_files = runFirstTierInRealTime(
            config_file,
            [region],
            start_date,
            electricity_date,
            None,
            real_time_dir,
            weather_dir,
            creation_time,
            version,
        )
        for cef_type in ("-d", "-l"):
            runSecondTierInRealTime(
                second_tier_config_file,
                [region],
                cef_type,
                start_date,
                electricity_date,
                real_time_dir,
                weather_dir,
                first_tier_files if first_tier_files else {},
                creation_time,
                version,
            )
        return {'attempted': True, 'status': 'completed', 'electricity_date_used': electricity_date, 'first_tier_files': first_tier_files}
    except Exception as exc:
        logger.exception("Configured CarbonCast ML execution failed for %s", region)
        return {'attempted': True, 'status': 'failed', 'error': str(exc)}


def _persist_ml_forecast(region, ml_result, batch_id, real_time_dir, forecast_start):
    """
    Reads the CSVs written by runSecondTierInRealTime (writeRealTimeCIForecastsToFile)
    and inserts/overwrites real ML-generated forecasts into Forecast168.
    Uses update_or_create keyed on (region_code, datetime, source_type,
    emission_factor_type) -- matching the DB's actual unique constraint --
    so each new run correctly OVERWRITES the previous forecast for that
    region/hour, rather than accumulating duplicate rows.

    After writing, prunes any stale rows for this region whose datetime
    falls before this run's forecast_start -- these are leftovers from a
    previous day's run whose window no longer overlaps with today's.
    """
    import csv as csv_module
    from datetime import datetime as dt, timezone as tz_module
    from CarbonCastRESTAPI.models import Forecast168

    if not ml_result.get('attempted') or ml_result.get('status') != 'completed':
        return {'written': 0, 'reason': ml_result.get('status', 'not_attempted')}

    start_date = forecast_start.date().isoformat()
    written = 0

    for cef_label, file_suffix in (('direct', 'direct'), ('lifecycle', 'lifecycle')):
        out_path = os.path.join(
            real_time_dir, region,
            f"{region}_{file_suffix}_CI_forecasts_{start_date}.csv",
        )
        if not os.path.exists(out_path):
            logger.warning("Expected ML output not found: %s", out_path)
            continue

        with open(out_path, newline="") as f:
            reader = csv_module.DictReader(f)
            for row in reader:
                try:
                    ts = dt.fromisoformat(row["UTC time"].split(".")[0])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=tz_module.utc)
                    issued = dt.fromisoformat(row["creation_time (UTC)"].split(".")[0])
                    if issued.tzinfo is None:
                        issued = issued.replace(tzinfo=tz_module.utc)
                    value = float(row["forecasted_avg_carbon_intensity"])
                except (KeyError, ValueError) as exc:
                    logger.warning("Skipping malformed ML forecast row in %s: %s", out_path, exc)
                    continue

                Forecast168.objects.update_or_create(
                    region_code=region,
                    datetime=ts,
                    source_type='model_forecast',
                    emission_factor_type=cef_label,
                    defaults={
                        'value': value,
                        'metric_unit': 'gCO2eq/kWh',
                        'provider': 'carboncast',
                        'forecast_run_id': batch_id,
                        'issued_at': issued,
                    },
                )
                written += 1

    # Prune stale rows ONCE, after BOTH direct and lifecycle CSVs are done.
    # Use the actual minimum datetime from THIS run (matched by issued_at,
    # the batch timestamp shared by every row we just wrote) instead of
    # forecast_start -- forecast_start can drift from what the model
    # actually used as its start time by the time this prune runs, since
    # the pipeline takes several minutes between computing forecast_start
    # and writing these rows. Using the wrong cutoff was deleting this
    # run's own valid early hours.
    from django.db.models import Min
    this_run_min = Forecast168.objects.filter(
        region_code=region, issued_at=issued,
    ).aggregate(Min('datetime'))['datetime__min']

    if this_run_min:
        deleted, _ = Forecast168.objects.filter(
            region_code=region,
            datetime__lt=this_run_min,
        ).delete()
        if deleted:
            logger.info("[%s] Pruned %d stale forecast rows before %s", region, deleted, this_run_min)

    return {'written': written}


def _persist_baseline_forecast(region, emissions, batch_id, forecast_start, weather_source, artifact_dir, runner=None, weather_rows=None):
    """
    Run the selected model runner (CarbonCast/LiteCast) to produce a full
    forecast batch and upsert it into Forecast96. The runner output is the
    single source of truth; weather rows are passed through so weather-aware
    runners can align variables to each forecast hour.
    """
    from CarbonCastRESTAPI.models import Forecast96
    from CarbonCastRESTAPI.services.model_runners import CarbonCastRunner

    if runner is None:
        runner = CarbonCastRunner()
    weather_rows = weather_rows or []

    creation_time = tz.now().astimezone(timezone.utc).isoformat()
    rows_written = {'lifecycle': 0, 'direct': 0, 'energy': 0}

    forecast_rows = runner.run(
        region=region,
        emissions=emissions,
        weather_rows=weather_rows,
        forecast_start=forecast_start,
        horizon=FORECAST_HORIZON_HOURS,
    )

    output_path = artifact_dir / "db_baseline_forecasts.csv"
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["UTC time", "forecast_type", "value", "batch_id", "model"])

        for fr in forecast_rows:
            data = {
                **fr.data,
                'creation_time (UTC)': creation_time,
                'batch_id': batch_id,
                'forecast_horizon': FORECAST_HORIZON_HOURS,
                'weather_source': weather_source,
                'model_name': runner.name,
            }
            Forecast96.objects.update_or_create(
                region=region,
                ts=fr.ts,
                forecast_type=fr.forecast_type,
                defaults={
                    'value': fr.value,
                    'forecast_horizon': FORECAST_HORIZON_HOURS,
                    'batch_id': batch_id,
                    'data': data,
                },
            )
            if fr.forecast_type in rows_written:
                rows_written[fr.forecast_type] += 1
            writer.writerow([fr.ts.isoformat(), fr.forecast_type, fr.value, batch_id, runner.name])

    return rows_written


def _average(values):
    numeric = [_coerce_float(value) for value in values]
    numeric = [value for value in numeric if value is not None]
    if not numeric:
        return 0.0
    return sum(numeric) / len(numeric)


def _average_source_mix(rows):
    averages = {}
    for source in ENERGY_SOURCES:
        values = []
        for row in rows:
            data = row.data or {}
            values.append(data.get(source))
        averages[source] = _average(values)
    return averages


def _coerce_float(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
