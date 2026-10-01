# CarbonCast: Developer Runbook & Architecture Guide

This document is the comprehensive, implementation-grounded developer guide for **CarbonCast**. It details the **Daily Real-Time Inference Pipeline** and the **Weekly Retraining Pipeline**, their architectures, data schemas, staleness guards, failure recovery strategies, and known regional exceptions.

---

## Terminology & Concepts

* **Carbon Intensity (CI)**: Emissions per unit of electricity generated, expressed in $\text{gCO}_2\text{eq/kWh}$.
  * **Direct CI**: Point-of-combustion emissions (fuel burning only).
  * **Lifecycle CI**: Upstream extraction, transport, refining, construction, and combustion emissions.
* **Tier 1 (First-Tier Forecast)**: An Artificial Neural Network (ANN) that predicts hourly power generation ($\text{MW}$) for each individual fuel source (e.g., Coal, Gas, Solar, Wind, Hydro, Nuclear) over a 168-hour horizon.
* **Tier 2 (Second-Tier Forecast)**: A Convolutional Neural Network + Long Short-Term Memory (CNN-LSTM) hybrid model that consumes the 168h fuel generation forecasts alongside 168h GFS numerical weather forecasts to predict the resulting Direct and Lifecycle Carbon Intensity.
* **Forecast168**: The primary Django ORM table storing the final 168-hour (7-day) hourly carbon intensity forecasts ($168 \text{ hours} \times 2 \text{ emission types} = 336 \text{ rows}$ per region).
* **EmissionActual**: The primary Django ORM table storing ground-truth hourly generation by fuel type, direct carbon intensity, and lifecycle carbon intensity.
* **NOMADS**: NOAA Operational Model Archive and Distribution System — real-time HTTP server providing the latest operational GFS $0.25^\circ$ weather forecasts.
* **NCAR RDA**: National Center for Atmospheric Research Research Data Archive — long-term archive (`ds084.1`) delivering historical GFS GRIB2 cycles packaged in `.tar` files.

---

# 1. DAILY REAL-TIME INFERENCE PIPELINE

## 1.1 Prerequisites

### Python & Environment
* **Python Runtime**: Python 3.10 in virtual environment:
  `/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/.venv/bin/python`
* **Django Environment**: `DJANGO_SETTINGS_MODULE="CarbonCastAPI.settings"`
* **System Binaries**: `wgrib2` compiled and available at `/Users/prarthanapatil/.local/share/mamba/bin/wgrib2`.

### API Credentials & Environment Variables
* `EIA_API_KEY`: U.S. Energy Information Administration v2 API key (default: `Qc8vFrBgZhLdtFVurGbxHbCrvyP93RoPXVhKfCGx`).
* `ENTSOE_API_KEY`: ENTSO-E Transparency Platform API key (default: `3d8580df-94bb-4d1f-9854-50b736a39858`).
* `CARBONCAST_RUN_ML`: Set to `"true"` to invoke neural network inference.
* `CARBONCAST_CONFIG_FILE`: Absolute path to `src/firstTierConfig.json`.
* `CARBONCAST_SECOND_TIER_CONFIG_FILE`: Absolute path to `src/secondTierConfig.json`.
* `CARBONCAST_REAL_TIME_DIR`: Root staging directory (`realtime_electricity_staged/`).
* `CARBONCAST_REAL_TIME_WEATHER_DIR`: Root weather staging directory (`realtime_weather_staged/`).

### Directory Structure & Pre-trained Models
* Staging directories:
  * `realtime_electricity_staged/<REGION>/`
  * `realtime_weather_staged/<REGION>/`
  * `realtime_weather_downloads/<REGION>/`
  * `realtime_weather_processed/<REGION>/`
* Saved model artifacts:
  * Tier 1 weights: `saved_first_tier_models/<REGION>/<REGION>_<SOURCE>_best_model_ann.h5`
  * Tier 1 scalers: `saved_first_tier_models/<REGION>/<REGION>_<SOURCE>_min_max_values.txt`
  * Tier 2 Direct weights & scalers: `saved_second_tier_models/direct/<REGION>/<REGION>.h5` and `GB_min_max_values.txt`
  * Tier 2 Lifecycle weights & scalers: `saved_second_tier_models/lifecycle/<REGION>/<REGION>.h5` and `GB_min_max_values.txt`

---

## 1.2 Running Inference

### Option A: Via HTTP API (Recommended for External Orchestration / EnergyAPI)
When CarbonCast is running as an HTTP service (e.g., on port 8001), any external orchestrator or client can trigger real-time inference on-demand via a `POST` request:

```bash
curl -X POST "http://localhost:8001/v1/TriggerReforecast?region=CISO"
```

**JSON Response (200 OK):**
```json
{
  "status": "success",
  "region": "CISO",
  "message": "Real-time reforecast generated successfully.",
  "generated_rows": 336,
  "forecast_start": "2026-09-29T00:00:00Z",
  "forecast_end": "2026-10-06T00:00:00Z"
}
```

The endpoint triggers `run_pipeline(region)` synchronously:
1. Ingests latest generation actuals from EIA / ENTSO-E.
2. Pulls live GFS 0.25° weather from NOAA NOMADS.
3. Performs Tier 1 ANN generation forecasting + Tier 2 CNN-LSTM carbon intensity forecasting.
4. Saves 336 hourly rows (168 direct + 168 lifecycle) to PostgreSQL table `CarbonCastRESTAPI_forecast168`.

### Option B: Single Region Python Command
To run real-time inference directly in the local environment:

```bash
cd /Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src/CarbonCastAPI

/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/.venv/bin/python manage.py shell -c "
from CarbonCastRESTAPI.services.weather_fetch.run_full_realtime_pipeline import run_pipeline
result = run_pipeline('CISO')
print('Pipeline Result:', result)
"
```

Or via direct script invocation:
```bash
/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/.venv/bin/python \
  /Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src/CarbonCastAPI/CarbonCastRESTAPI/services/weather_fetch/run_full_realtime_pipeline.py \
  --regions CISO
```

### Option C: Batch Inference Command
To run inference across all active regions:

```bash
cd /Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src/CarbonCastAPI

/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/.venv/bin/python manage.py shell -c "
from CarbonCastRESTAPI.services.weather_fetch.run_full_realtime_pipeline import run_batch
summary = run_batch()
print('Batch Summary:', summary)
"
```

**Batch Failure Isolation**:
In `run_batch()`, each region is wrapped in an individual `try...except` block (`run_full_realtime_pipeline.py:299-305`). If an individual region fails, the error is logged, stored in the `failed` dictionary, and execution immediately continues with the next region.

---

## 1.3 Execution Order & Data Flow

```text
┌────────────────────────────────────────────────────────┐
│ Step 1: Ingest Grid Actuals (EIA / ENTSO-E / NESO)     │
│  → Write to Django ORM: EmissionActual                 │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ Step 2: Download NOAA NOMADS GFS Weather GRIB2 files   │
│  → realtime_weather_downloads/<REGION>/<var>/*.grib2   │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ Step 3: Area-Weighted Spatial Averaging (wgrib2)       │
│  → realtime_weather_processed/<REGION>/*_AVG_<VAR>.csv │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ Step 4: Hourly Expansion & Merging                     │
│  → <REGION>_weather_merged.csv                         │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ Step 5: Input Staging                                  │
│  → realtime_weather_staged/<REGION>/                   │
│  → realtime_electricity_staged/<REGION>/               │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ Step 6a: Tier 1 Fuel Generation Inference (ANN)        │
│  → fuel_forecast/<REGION>_ANN_<source>_<date>.csv      │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ Step 6b: Tier 2 Direct & Lifecycle CI (CNN-LSTM)       │
│  → <REGION>_direct_CI_forecasts_<date>.csv             │
│  → <REGION>_lifecycle_CI_forecasts_<date>.csv          │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ Step 6c: Database Write & Pruning                      │
│  → Upsert 336 rows into Forecast168                    │
│  → Prune stale forecast hours prior to run start       │
└────────────────────────────────────────────────────────┘
```

### Detailed Call Chain:

| Step | Function | Source File | Consumes | Produces |
|---|---|---|---|---|
| **1. Grid Fetch** | `step1_fetch_electricity(region)` | `run_full_realtime_pipeline.py:69` | Remote API (EIA / ENTSO-E / NESO) | `EmissionActual` database records |
| **2. Weather Fetch** | `step2_fetch_weather(region)` | `run_full_realtime_pipeline.py:101` | NOAA NOMADS HTTP Server | Raw GRIB2 files in `realtime_weather_downloads/` |
| **3. Weather Process** | `step3_process_weather(region)` | `run_full_realtime_pipeline.py:125` | Raw GRIB2 files | `realtime_weather_processed/<REGION>/<REGION>_AVG_<VAR>.csv` |
| **4. Weather Reshape** | `step4_expand_merge_reshape(region)` | `run_full_realtime_pipeline.py:133` | Processed variable CSVs | `hourly_staging/<REGION>_weather_merged.csv` |
| **5. Staging** | `step5_stage_all(region, merged_csv)` | `run_full_realtime_pipeline.py:167` | `EmissionActual` + merged weather CSV | Staged 24h electricity CSVs & 168h weather CSV |
| **6a. Tier 1 ML** | `runFirstTierInRealTime()` | `firstTierForecasts.py:465` | Staged electricity + weather CSVs | `realtime_electricity_staged/<REGION>/fuel_forecast/` |
| **6b. Tier 2 ML** | `runSecondTierInRealTime()` | `secondTierForecasts.py:350` | Tier 1 predictions + staged weather CSV | `realtime_electricity_staged/<REGION>/<REGION>_<cef>_CI_forecasts_<date>.csv` |
| **6c. DB Persistence** | `_persist_ml_forecast()` | `retraining_service.py:356` | Tier 2 output CSVs | Writes 336 rows into `Forecast168` |

---

## 1.4 Previous-Day Data Design

### Why Yesterday's Data is Used
Real-time power generation data from grid operators (EIA, ENTSO-E, NESO) is published with a delay of several hours. Current-day generation tables typically contain incomplete or partially uploaded hours.

The Tier 1 ANN models require a continuous, complete 24-hour input vector ($[24, \text{features}]$) representing yesterday's full diurnal cycle to seed the 168-hour autoregressive forecast:

```text
Inference Run Date:        2026-09-23
Electricity Date Selected: 2026-09-22 (00:00 to 23:00 UTC, 24 complete hours)
Weather Forecast Used:     2026-09-23 (07:00 UTC to 2026-09-30 06:00 UTC, 168 hours)
Forecast168 Horizon:       2026-09-23 07:00 UTC → 2026-09-30 06:00 UTC (168 hourly steps)
```

---

## 1.5 Freshness & Staleness Guards

1. **EmissionActual Staleness Check in Step 1 (`run_full_realtime_pipeline.py:74-77`)**:
   * **Condition**: `(tz.now() - latest.ts) < timedelta(hours=6)`
   * **Action**: Skips the upstream network fetch if database actuals are less than 6 hours old.
2. **EmissionActual Staleness Guard in Run Pipeline (`run_full_realtime_pipeline.py:258-262`)**:
   * **Condition**: `(tz.now() - latest.ts) > timedelta(hours=96)`
   * **Action**: Logs a warning that grid actuals are older than 96 hours, but proceeds using the latest available actual data as a fallback rather than failing the run.
3. **Weather Download Freshness Guard (`run_full_realtime_pipeline.py:106-118`)**:
   * **Condition**: Compares the 8-digit date in existing downloaded GRIB filenames against `date.today().strftime("%Y%m%d")`.
   * **Action**: If today's cycle is already downloaded, skips the NOMADS download step.
4. **Electricity Staging Fallback Loop (`retraining_service.py:264-279`)**:
   * **Condition**: Checks candidate electricity CSVs backwards from `days_back=1` to `days_back=14`.
   * **Threshold**: Must have $\ge 24$ rows (excluding header).
   * **Action**: Selects the newest complete 24-hour day.
5. **Weather Forecast Staging Fallback (`retraining_service.py:295-316`)**:
   * **Condition**: Checks if today's weather forecast CSV has $< 24$ rows.
   * **Action**: Attempts to fall back to yesterday's staged weather forecast file. If yesterday's file is also missing or thin, skips ML execution for that cycle and sets status to `'skipped_thin_weather_data'`.

---

## 1.6 Thin-Data and Fallback Behavior

* **Incomplete Grid Data**: The pipeline searches backwards up to 14 days in `realtime_electricity_staged/<REGION>/` for a CSV containing $\ge 24$ rows. If none exists, ML execution is skipped, and a database baseline forecast is generated into `Forecast96`.
* **Incomplete Weather Forecast**: If NOAA NOMADS returns a truncated forecast ($< 24$ hours), the service attempts to load yesterday's staged forecast. If unavailable, ML inference is safely bypassed without crashing the service.
* **Missing Fuel Sources**: If a fuel type configured in `REGION_SOURCES` is absent from the grid data, `_calculate_carbon_intensity` treats the generation as 0 and falls back to the default emission factors.

---

## 1.7 Verifying a Successful Inference Run in PostgreSQL

A successful real-time inference run generates and upserts **336 rows** into the PostgreSQL `"CarbonCastRESTAPI_forecast168"` table ($168 \text{ hours} \times 2 \text{ emission types [direct + lifecycle]} = 336 \text{ rows}$ per region).

### 1. Single Region Verification Query

Run this query directly via `psql` to check row counts, time horizon, and mean/min/max carbon intensity values for a given region (e.g. `CISO` or `GB`):

```sql
SELECT 
    region_code, 
    emission_factor_type, 
    COUNT(*) AS total_hours, 
    MIN(datetime) AS horizon_start, 
    MAX(datetime) AS horizon_end,
    ROUND(AVG(value)::numeric, 2) AS avg_ci,
    ROUND(MIN(value)::numeric, 2) AS min_ci,
    ROUND(MAX(value)::numeric, 2) AS max_ci
FROM "CarbonCastRESTAPI_forecast168"
WHERE region_code = 'CISO'
GROUP BY region_code, emission_factor_type;
```

**Single-Line Terminal Command:**
```bash
psql -d carboncast -c "SELECT region_code, emission_factor_type, count(*) AS total_hours, min(datetime) AS horizon_start, max(datetime) AS horizon_end, round(avg(value)::numeric, 2) AS avg_ci, round(min(value)::numeric, 2) AS min_ci, round(max(value)::numeric, 2) AS max_ci FROM \"CarbonCastRESTAPI_forecast168\" WHERE region_code = 'CISO' GROUP BY region_code, emission_factor_type;"
```

**Expected Healthy Result**:
```text
 region_code | emission_factor_type | total_hours |        horizon_start        |         horizon_end         | avg_ci | min_ci | max_ci 
-------------+----------------------+-------------+-----------------------------+-----------------------------+--------+--------+--------
 CISO        | direct               |         168 | 2026-09-26 23:00:00+00      | 2026-10-03 22:00:00+00      | 154.21 |  88.40 | 285.60
 CISO        | lifecycle            |         168 | 2026-09-26 23:00:00+00      | 2026-10-03 22:00:00+00      | 248.75 | 161.41 | 392.10
(2 rows)
```

---

### 2. Multi-Region Batch Sanity Check

To verify all regions across the entire database after a batch inference run:

```bash
# Check total distinct regions and total forecast rows (e.g. 69 regions = 23,184 rows):
psql -d carboncast -c "SELECT count(DISTINCT region_code) AS total_regions, count(*) AS total_rows FROM \"CarbonCastRESTAPI_forecast168\";"

# List row count per region (every active region should have exactly 336 rows):
psql -d carboncast -c "SELECT region_code, count(*) AS row_count FROM \"CarbonCastRESTAPI_forecast168\" GROUP BY region_code ORDER BY region_code;"
```

---

### 3. Model Quality & Non-Saturation Validation

To ensure predictions are not saturated (e.g. flatlined scalers, zeroes, or constant values):

```sql
SELECT 
    region_code,
    emission_factor_type,
    ROUND(MIN(value)::numeric, 2) AS min_val,
    ROUND(MAX(value)::numeric, 2) AS max_val,
    ROUND(STDDEV(value)::numeric, 2) AS std_dev
FROM "CarbonCastRESTAPI_forecast168"
GROUP BY region_code, emission_factor_type
HAVING STDDEV(value) = 0 OR STDDEV(value) IS NULL OR MIN(value) = MAX(value);
```
*(A healthy database will return **0 rows** for this query, confirming that every region displays genuine diurnal variance).*

---

## 1.8 Visualizing Results: Running Backend API & Frontend Map UI

To interactively explore and visualize the 168-hour forecasts, actuals, and regional carbon intensities:

### Terminal 1: Start the Backend API (Direct Python / PostgreSQL)
```bash
cd /Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src/CarbonCastAPI
DJANGO_SETTINGS_MODULE=CarbonCastAPI.settings \
/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/.venv/bin/python manage.py runserver 8001
```

> [!NOTE]
> * **Port Convention:** By default, Django serves on port 8000. When co-located with **EnergyAPI** (which serves on `http://localhost:8000`), run CarbonCast on port **8001** (`manage.py runserver 8001`).
> * Running the Django backend directly with Python connects straight to your local PostgreSQL database (`carboncast`), which holds the full 168-hour ML forecasts and historical grid data.

* **Swagger API Docs:** [http://localhost:8001/doc/](http://localhost:8001/doc/)
* **Test 168h Forecast Endpoint:** [http://localhost:8001/v1/CarbonIntensityForecasts?regionCode=CISO&forecastPeriod=168h](http://localhost:8001/v1/CarbonIntensityForecasts?regionCode=CISO&forecastPeriod=168h)
* **Trigger Reforecast Endpoint:** [http://localhost:8001/v1/TriggerReforecast?region=CISO](http://localhost:8001/v1/TriggerReforecast?region=CISO)

### Terminal 2: Frontend Visualization Options

#### Option A: Energy UI (Integrated Energy Ecosystem)
The production energy dashboard lives in the `energyapi` repository (`energyapi/EnergyUI`). It connects directly to EnergyAPI (port 8000) and visualizes regional carbon intensity data synced from CarbonCast and other providers:
```bash
cd /Users/prarthanapatil/energyapi/EnergyUI
npm run dev
# Dashboard URL: http://localhost:5173 (or 5174)
```

#### Option B: Standalone CarbonCast Map UI (React + MapLibre)
To test CarbonCast directly with its standalone React map interface:
```bash
cd /Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/CarbonCastUI/web
npm install   # (only needed on initial setup)
npm run dev
```
* **Interactive Map URL:** [http://localhost:5173](http://localhost:5173)
* Ensure `CarbonCastUI/web/.env` contains `VITE_API_BASE_URL=http://localhost:8001` (or `8000`) so the React frontend queries the CarbonCast API server. Click any region on the map to view the 168-hour forecast timeline and carbon intensity metrics.

---

# 2. WEEKLY MODEL RETRAINING PIPELINE

## 2.1 Running Retraining

### Single / Multiple Regions Command
The weekly retraining workflow is managed by `weekly_data_rotation.py`:

```bash
cd /Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/src/CarbonCastAPI/CarbonCastRESTAPI/services/weather_fetch

/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/.venv/bin/python weekly_data_rotation.py \
  --regions AECI BANC CISO GB
```

**Pipelined Concurrency**:
`weekly_data_rotation.py` uses a `ThreadPoolExecutor(max_workers=1)` to overlap I/O operations with ML training:
* While Region $N$ is actively training its neural networks on the CPU/GPU, the background worker is pre-fetching NOMADS weather and grid actuals for Region $N+1$.

---

## 2.2 Retraining Architecture: `weather_fetch/` vs `weekly_training/`

To prevent regressions in real-time inference, the training and inference modules are strictly isolated:

```text
services/
├── weather_fetch/                     ← DAILY REAL-TIME INFERENCE & ORCHESTRATION
│   ├── run_full_realtime_pipeline.py  (Daily end-to-end inference)
│   ├── run_daily_inference_batch.py   (Daily batch cron runner)
│   ├── fetch_grib_nomads.py           (Daily NOAA NOMADS fetcher)
│   ├── process_weekly_weather.py      (Single-cycle wgrib2 processor)
│   ├── stage_electricity_for_inference.py
│   ├── stage_ci_emissions_for_inference.py
│   └── weekly_data_rotation.py        (Weekly sliding-window manager)
│
└── weekly_training/                   ← WEEKLY RETRAINING ENGINE
    ├── build_final_training_dataset.py       (Concatenates archives + computes train/test splits)
    ├── process_weekly_weather_for_training.py (Multi-cycle batch GRIB2 processor)
    ├── prepare_grid_data_for_retraining.py   (Append-mode CSV exporter)
    └── run_full_retraining_batch.py          (Batch model trainer for Tier 1 & Tier 2)
```

---

## 2.3 Sliding-Window Behavior

The CarbonCast training dataset maintains a rolling 12-month temporal window (approx. 6 months train / 6 months test):

```text
Before Weekly Rotation:
  Training Window: 2024-12-01 00:00 UTC → 2026-09-16 23:00 UTC (15,720 hours)

New Week Ingested:
  New Data Gap:    2026-09-17 00:00 UTC → 2026-09-23 23:00 UTC (168 hours)

After Sliding-Window Trimming:
  1. Append new rows to existing fuel & weather CSVs.
  2. Trim oldest 7 days (168 hours) from the start of the weather CSVs (`trim_oldest_days()`).
  3. Delete oldest 7 days from `EmissionActual` in DB (`trim_oldest_days_grid_data()`).
  Resulting Window: 2024-12-08 00:00 UTC → 2026-09-23 23:00 UTC (15,720 hours)
```

**Dataset Limiter Calculation**:
`compute_dataset_limiter()` in `run_full_retraining_batch.py:136-224` dynamically inspects the exact row counts of both the fuel CSVs and `_weather_merged.csv`. It sets `DATASET_LIMITER = min(electricity_rows, weather_rows)` in `firstTierConfig.json` to prevent array size mismatch errors during `manipulateTrainingDataShape()`.

---

## 2.4 NOMADS vs NCAR RDA Weather Paths

| Feature | NOAA NOMADS | NCAR RDA (`ds084.1`) |
|---|---|---|
| **Use Case** | Daily real-time inference & recent 7-day gaps | Historical archives & gaps $> 10$ days |
| **Retention Window** | Last $\approx 7\text{--}10$ days only | Full historical record (2015 to present) |
| **Format Delivered** | Loose single-cycle `.grib2` files | Compressed multi-cycle `.tar` archives |
| **Extraction Requirement** | None (direct `.grib2`) | Requires `extract_rda_tars()` to extract and delete `.tar` archives before parsing |

> [!WARNING]
> **RDA Extraction Failure Mode**: If RDA `.tar` archives are downloaded into `retraining_weather_downloads/` but `extract_rda_tars()` is not called, `process_weekly_weather_for_training.py` will find 0 `.grib2` files and silently produce empty weather datasets.

---

## 2.5 File & Directory Dependency Map

| Step | Producer Script | Output Path / File Pattern | Consumer Script | Expected Input Pattern |
|---|---|---|---|---|
| **1. RDA Extraction** | `weekly_data_rotation.py:extract_rda_tars` | `retraining_weather_downloads/<R>/<var>/gfs.0p25.*.grib2` | `process_weekly_weather_for_training.py` | Loose `.grib2` files |
| **2. Multi-Cycle Weather** | `process_weekly_weather_for_training.py` | `retraining_weather_processed/<R>/<R>_AVG_<VAR>.csv` | `build_final_training_dataset.py` | Wide CSV with `datetime`, `latitude`, `longitude`, `Analysis`, and forecast columns |
| **3. Archive Concat** | `build_final_training_dataset.py` | `weekly_training/final_training_data/<R>/<R>_AVG_<VAR>.csv` | `run_full_retraining_batch.py:prep_weather_for_training` | Continuous multi-month wide CSVs |
| **4. Hourly Weather** | `expand_weather_to_hourly.py` & `merge_hourly_weather.py` | `data/<R>/<R>_weather_merged.csv` | `build_tier2_forecast_input.py` | Hourly CSV (`datetime,temp,dpt,dswrf,wind_speed,precip`) |
| **5. Weather Dayblocks** | `reshape_weather_to_dayblocks.py` | `data/<R>/<R>_weather_forecast_168.csv` | `firstTierForecasts.py` | 168h block-reshaped weather forecasts |
| **6. Fuel CSVs** | `prepare_grid_data_for_retraining.py` | `data/<R>/fuel_forecast/<R>_<source>_clean.csv` | `firstTierForecasts.py` | Clean hourly fuel generation with `UTC time` |
| **7. Emissions CSVs** | `prepare_grid_data_for_retraining.py` | `data/<R>/<R>_<cef>_emissions.csv` | `align_emissions_to_forecast.py` | Clean hourly carbon intensity |
| **8. Tier 1 Models** | `firstTierForecasts.py` | `saved_first_tier_models/<R>/<R>_<source>_best_model_ann.h5` | `build_tier2_forecast_input.py` & `runFirstTierInRealTime` | Trained Keras `.h5` model files |
| **9. Tier 2 Input** | `build_tier2_forecast_input.py` | `data/<R>/<R>_168hr_forecasts_DA_continuous.csv` | `align_emissions_to_forecast.py` & `secondTierForecasts.py` | 168h continuous day-ahead fuel predictions |
| **10. Tier 2 Models** | `secondTierForecasts.py` | `saved_second_tier_models/<cef>/<R>/<R>.h5` | `runSecondTierInRealTime` | Trained CNN-LSTM Keras model files |

---

## 2.6 Training & Model Validation

When retraining completes, evaluate the generated MAPE score file:
`data/<REGION>/<REGION>_MAPE_iter0.txt`

### Healthy Model Characteristics
* **Validation Loss**: Steady decrease during training epochs (`val_loss` drops from $\approx 0.030$ to $< 0.019$).
* **Median MAPE**: Between $15\%$ and $45\%$ across 24h--168h forecast horizons.
* **Unscaled RMSE**: Typically between $25.0$ and $55.0\text{ gCO}_2\text{eq/kWh}$ for Direct CI.

### Broken / Degenerate Model Indicators
* **Mean MAPE $> 1,000,000\%$**: Occurs when actual carbon intensity contains exact $0.0$ values (division by zero in MAPE formula).
* **Flat/Constant Prediction**: Scaler min-max saturation (e.g., fuel column ordering mismatch where power generation in kW was scaled using wind speed scaler).
* **NaN Loss / Predictions**: Missing values in training CSVs or unhandled nulls in `EmissionActual`.

---

# 3. KNOWN REGION-SPECIFIC EXCEPTIONS

1. **100% Single-Source Hydro Regions (`GCPD`, `SCL`, `SPA`, `TPWR`, `DOPD`)**:
   * These regions rely almost exclusively on hydro power.
   * Direct carbon intensity is mathematically $0.0\text{ gCO}_2/\text{kWh}$.
   * Direct CI forecasts for these regions will legitimately be flat zeros.
2. **Inconsistent / Volatile Reporting Regions (`BANC`, `FPC`, `GRID`, `PSEI`, `WALC`)**:
   * Flagged in `secondTierConfig.json` under `REGION_WITH_INCONSISTENT_DATA`.
   * These balancing authorities exhibit frequent reporting gaps from upstream EIA endpoints and may require larger backfill windows.
3. **Great Britain (GB) Upstream Transition**:
   * GB is no longer reported under ENTSO-E.
   * Ingestion is routed via `neso_service.py` consuming the National Energy System Operator (NESO) CKAN API. Native 30-minute intervals are resampled to 1-hour means.
4. **Nuclear Feature Ordering in Tier 2**:
   * European regions and certain US balancing authorities feature Nuclear generation.
   * In `secondTierForecasts.py`, `TRAINING_FEATURE_ORDER` must explicitly include `"avg_nuclear_production_forecast"` in alphabetical order between `"avg_nat_gas_production_forecast"` and `"avg_oil_production_forecast"`.

---

# 4. COMMON FAILURE MODES & DIAGNOSTICS

## 4.1 Forecast is Flat / Repeating Across 7 Days

```text
Symptom: 168-hour CI forecast is completely flat or repeats identical values
↓
Check 1: Inspect generated forecast CSV
Command: head -n 30 realtime_electricity_staged/<REGION>/<REGION>_direct_CI_forecasts_<DATE>.csv
↓
Result A: All values are identical (e.g. 0.0 or 150.0)
  → Cause: Scaler saturation or column order mismatch in secondTierForecasts.py:TRAINING_FEATURE_ORDER.
  → Action: Verify that feature column names in fuel_forecast matches training order.
↓
Result B: First Tier ANN forecasts in fuel_forecast/ are flat
  → Cause: Tier 1 input scaling saturated.
  → Action: Inspect saved_first_tier_models/<REGION>/<REGION>_<SOURCE>_min_max_values.txt.
```

## 4.2 Forecast Output is NaN

```text
Symptom: Forecast168 contains NaN values or inference throws ValueError during float conversion
↓
Check 1: Inspect staged electricity CSVs for NaNs
Command: grep "nan" realtime_electricity_staged/<REGION>/<REGION>_<DATE>.csv
↓
Result A: Staged electricity has unhandled NaNs
  → Cause: Upstream EIA/ENTSO-E API returned null generation values.
  → Action: Run fillMissingData() or check EmissionActual.data JSON blob.
↓
Result B: Staged weather has missing timestamps
  → Cause: Incomplete GRIB2 cycle download.
  → Action: Re-run fetch_grib_nomads.py --region <REGION> to refresh weather files.
```

## 4.3 API Response Contains Fewer Than 168 Hours

```text
Symptom: Forecast168 has fewer than 336 rows (e.g., 24 rows or 144 rows)
↓
Check 1: Query database row counts by type and issuance
Command:
  python manage.py shell -c "
  from CarbonCastRESTAPI.models import Forecast168
  print(Forecast168.objects.filter(region_code='<REGION>').values('emission_factor_type', 'issued_at').annotate(count=models.Count('id')))
  "
↓
Result A: Old issued_at rows were not pruned
  → Cause: Stale rows from previous runs overlapping current horizon.
  → Action: Ensure retraining_service.py:_persist_ml_forecast() runs the this_run_min cleanup.
↓
Result B: Weather forecast file had < 168 hours
  → Cause: NOMADS GFS download stopped at forecast hour f120 instead of f168.
  → Action: Verify FCST list in fetch_grib_nomads.py covers list(range(0, 169, 3)).
```

---
