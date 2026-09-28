# CarbonCast Pipeline — How to Train for 168hr CI Forecasts (FPC Example)

## 0. The Core Architecture, in One Paragraph

This pipeline is a **walk-forward test-set evaluator**, not a full-history forecaster. Tier 1 trains ANN models per fuel source and produces production forecasts *only* for its held-out test days. Tier 2 trains a CNN-LSTM on carbon intensity + Tier 1's forecasts and produces CI forecasts *only* for its own held-out test days. The final CI forecast output you get will only ever cover Tier 2's test window — a sub-slice of Tier 1's test window — never your full raw data range in one run.

---

## 1. Data Requirements & Relationships

Three data sources must all agree on the same underlying date range:

| File | Granularity | Rows needed |
|---|---|---|
| Fuel/grid production data (`<REGION>_<source>_clean.csv`) | 1 row/hour | `num_days × 24` |
| Direct/lifecycle emissions (`<REGION>_direct_emissions.csv`) | 1 row/hour | `num_days × 24` |
| Weather forecast data (block-reshaped) | 168hr overlapping blocks, 24hr stride | `num_days × 168` |

**Key rule:** weather data is block-reshaped — each "day" is a full 168-hour forward-looking window, sliding forward 24 hours at a time. So for every 24 hours of grid data, you need 168 hours of weather-block data. This is computed automatically in code via:
```python
weatherDatasetLimiter = datasetLimiter // 24 * PREDICTION_WINDOW_HOURS
```
You only ever set `DATASET_LIMITER` (grid-side, in hours) — never the weather limiter directly.

**`num_days` is capped by whichever source has fewer complete days.** Always verify with:
```python
n_days = (len(hourly_weather_df) - BLOCK_HOURS) // 24 + 1
```

---

## 2. Step-by-Step Pipeline

### Step A — Build direct/lifecycle emissions file
```bash
python3 make_direct_emissions.py <REGION> <NUM_ROWS>
```
`NUM_ROWS = num_days × 24`, where `num_days` = the real ceiling from Step B below.

### Step B — Build & block-reshape weather data
1. Merge per-variable hourly weather CSVs into one continuous file (`merge_hourly_weather.py`).
2. Reshape into overlapping 168hr blocks:
```bash
python3 reshape_weather_to_dayblocks.py <continuous_weather.csv> <output_168.csv> 168
```
This prints `n_days` — **this is your true ceiling**, use it to size Step A.
3. Ensure the output filename matches whatever `WEATHER_FORECAST_IN_FILE_NAME` points to in `firstTierConfig.json` — copy/rename if needed.
4. Check for NaNs before proceeding:
```python
df.isna().sum().sum()
```
Clean with `.ffill().bfill()` if needed (don't rely solely on the pipeline's internal `fillMissingData`, which has an edge bug at row 0).

### Step C — Configure & run Tier 1
In `firstTierConfig.json`, per-region `TRAIN_TEST_PERIOD.PERIOD_0`:
```json
"DATASET_LIMITER": num_days * 24,
"NUM_TEST_DAYS": <see sizing below>
```
Top-level: `NUM_VAL_DAYS`, `PREDICTION_WINDOW_HOURS: 168`.

Run:
```bash
python3 firstTierForecasts.py firstTierConfig.json
```
This trains 6 per-source ANN models and writes **test-window-only** forecasts to `<REGION>_ANN_<source>_iter0.csv`. **Note: Tier 1 output covers `NUM_TEST_DAYS` days only — never the full range.**

### Step D — Merge Tier 1 outputs + weather into Tier 2's input file
```bash
python3 build_tier2_forecast_input.py <REGION> <continuous_weather.csv> 168 0
```
This deduplicates overlapping forecast values (averaging across forecast horizons), merges all 6 sources + weather, and block-reshapes the result. Output: `<REGION>_168hr_forecasts_DA.csv` — spans **only Tier 1's test window**, shrunk further by ~7 days for block-reshape edge trimming.

### Step E — Align emissions file to match Step D's exact range
```python
emis = emis[(emis['UTC time'] >= fcst_start) & (emis['UTC time'] <= fcst_end)]
```
Both files must have identical row counts and date ranges before Tier 2 runs — mismatched lengths cause silent positional misalignment (ragged-array crashes).

### Step F — Configure & run Tier 2
In `secondTierConfig.json`, per-region block needs `NUM_FEATURES` and `START_COL` (often missing — must be added manually):
```json
"NUM_FEATURES": 6,
"START_COL": 0,
"FORECAST_IN_FILE_NAME": "<path to Step D output>"
```
Top-level: `NUM_TEST_DAYS`, `NUM_VAL_DAYS` sized to fit within Step D's day-block count (see below).

```bash
python3 secondTierForecasts.py secondTierConfig.json direct
```
Output: CI forecasts for Tier 2's `NUM_TEST_DAYS` window — **this is your final deliverable**, and it's the innermost, smallest sub-range of the whole pipeline.

---

## 3. Sizing NUM_TEST_DAYS / NUM_VAL_DAYS (Practical Minimums)

| Stage | Training min | Validation min | Purpose |
|---|---|---|---|
| Tier 1 | ~60 days | ~30 days | Learn daily/weekly fuel-mix cycles |
| Tier 2 | ~30 days | ~14–20 days | Learn CI patterns from smaller ANN window |

**To maximize final CI forecast coverage** (Option A strategy): push Tier 1's `NUM_TEST_DAYS` as high as possible while keeping ~90 days for its own training — this maximizes the window Tier 2 has to work with. Then split that window across Tier 2's own train/val/test.

Example, for a 547-day total range:
```
Tier 1:  training=90, val=60, test=397  → forecast output spans ~397 days
Step D:  edge-trim → ~390 day-blocks
Tier 2:  training=240, val=60, test=90  → final CI forecast = 90 days
```

---

## 4. For Full-Range Coverage (2024–2026), Beyond a Single Run

A single run of this pipeline will **never** produce continuous CI forecasts across your entire raw data range — only across Tier 2's test window. To cover the full range, the original CarbonCast reference implementation uses **multiple sequential `TRAIN_TEST_PERIOD` entries** in Tier 1, each with a progressively larger `DATASET_LIMITER`, appending each period's test-output to the same file (confirmed directly from real reference data: a period-2 output file's row index started exactly where period-1's ended, e.g. at row 13128). Each period must be run through the full Tier 1 → Step D → Tier 2 pipeline separately, then all Tier 2 outputs concatenated.

---

## 5. Known Gotchas Checklist

- ✅ Weather file column name must be `UTC time` (or match whatever the reading code expects) — rename from `datetime` if needed.
- ✅ Missing directories (`../saved_second_tier_models/<direct|lifecycle>/<REGION>/`) must exist before running — `mkdir -p` first.
- ✅ `START_COL`/`NUM_FEATURES` must be added manually per-region in `secondTierConfig.json` — not all regions have these by default.
- ✅ Never merge duplicate-timestamp files directly with `pd.merge` — deduplicate first, or row counts explode multiplicatively.
- ✅ `ROW_END_FOR_2022` / `SOURCE_FORECAST_ROW_END_FOR_2022` in `firstTierConfig.json` are **dead keys**, unused by the code — don't rely on them.
- ✅ Final Tier 2 output has duplicate real-hour entries by design (ratio = `PREDICTION_WINDOW_HOURS/24`) — dedupe/average afterward if you want one CI value per real hour.