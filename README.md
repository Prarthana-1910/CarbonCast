# CarbonCast — Real-Time Integration Monorepo

A system to predict the **hourly carbon intensity** of electricity for ~58 grid
regions across the US and Europe using machine learning, and serve those
forecasts through an API and an interactive web map.

This repository is a **monorepo** that combines the three projects which together make up the live, real-time product. For the full narrative overview of how they fit together, read **[`HANDOFF.md`](HANDOFF.md)** and the **[`DEVELOPER_GUIDE.md`](UCSC_CarbonCast_API/CarbonCast/DEVELOPER_GUIDE.md)**.

---

## Repository layout

```
.
├── CarbonCastUI/                  # (1) Standalone React web app (MapLibre frontend)
│   └── web/                       #     Note: Energy-wide UI lives in EnergyAPI/EnergyUI
│
├── UCSC_CarbonCast_API/           # (2) Django REST API + ML forecasting pipeline
│   └── CarbonCast/                #     Real-time inference, retraining, and HTTP API service
│
├── UCSC_OSRE_CC_automation_tool/  # (3) RDA weather-download automation tool
│   └── CarbonCast/                #     Fetches NCEP GFS weather from NCAR's Research Data Archive
│
├── docs/                          # Cross-project handoff documentation
└── HANDOFF.md                     # Start here — the big-picture guide
```

How they connect: **(3) downloads weather → (2) turns it into forecasts and serves them over a REST API (port 8001) → (1) draws the map / upstream consumers (such as EnergyAPI on port 8000) ingest the forecasts.**

---

## Quick start

Each sub-project has its own README with canonical instructions. To run the backend service:

```bash
# (1) Backend API (Django + PostgreSQL)
cd UCSC_CarbonCast_API/CarbonCast/src/CarbonCastAPI
DJANGO_SETTINGS_MODULE=CarbonCastAPI.settings \
/Users/prarthanapatil/Documents/EnergyAPI11/CarbonCast/UCSC_CarbonCast_API/CarbonCast/.venv/bin/python manage.py runserver 8001
```

> **Port Convention**: When running alongside **EnergyAPI** (which serves on `http://localhost:8000`), CarbonCast typically runs on port **8001** (`http://localhost:8001`).

```bash
# (2) Standalone Frontend Map UI (React + MapLibre)
cd CarbonCastUI/web && npm install && npm run dev
# Open in browser: http://localhost:5173

# (3) Automation tool
cd UCSC_OSRE_CC_automation_tool/CarbonCast && pip install -r requirements.txt && pytest
```

---

## External Provider & On-Demand Reforecasting API

CarbonCast functions as an independent carbon intensity and forecasting provider for downstream applications (such as [EnergyAPI](https://github.com/energyapi)).

### Triggering Real-Time 168-Hour Reforecasts over HTTP

External orchestrators can trigger an immediate, on-demand 168-hour ML reforecast for any balancing authority via HTTP `POST`:

```bash
curl -X POST "http://localhost:8001/v1/TriggerReforecast?region=DUK"
```

**Success Response (200 OK):**
```json
{
  "status": "success",
  "region": "DUK",
  "message": "Real-time reforecast generated successfully.",
  "generated_rows": 336,
  "forecast_start": "2026-09-29T00:00:00Z",
  "forecast_end": "2026-10-06T00:00:00Z"
}
```

This invokes the complete real-time pipeline:
1. Ingests the latest grid actuals (EIA / ENTSO-E / NESO).
2. Downloads operational GFS 0.25° weather forecasts from NOAA NOMADS.
3. Executes Tier 1 (ANN fuel mix) and Tier 2 (CNN-LSTM carbon intensity) ML inference.
4. Stores the 336 forecast records (168 direct + 168 lifecycle) in PostgreSQL `CarbonCastRESTAPI_forecast168`.

### Fetching Carbon Intensity Forecasts

Downstream services fetch the generated forecast with:
```bash
curl -s "http://localhost:8001/v1/CarbonIntensityForecasts?regionCode=DUK&forecastPeriod=168h"
```

---

## ⚠️ Data & large files are NOT in this repo

This repo tracks **source code, configuration, and docs only.** Large datasets,
trained ML models, downloaded weather files (`.grib2`/`.tar`), local databases,
virtual environments, and build artifacts are **kept local** and excluded via
[`.gitignore`](.gitignore).

A fresh `git clone` will **not** include that data — this is intentional (GitHub
rejects files >100 MB and the datasets are multi-GB and re-fetchable). For the
full list of what's excluded and **how to regenerate or fetch it**, read
**[`docs/05-data-and-large-files.md`](docs/05-data-and-large-files.md)**.

Secrets (`.env`, `rdams_token.txt`, keys) are never committed; `.env.example`
files document the variables each project needs.

---

## Documentation

| Doc | What it covers |
|-----|----------------|
| [`HANDOFF.md`](HANDOFF.md) | Big-picture overview & how the three projects connect. |
| [`UCSC_CarbonCast_API/CarbonCast/DEVELOPER_GUIDE.md`](UCSC_CarbonCast_API/CarbonCast/DEVELOPER_GUIDE.md) | **Developer Runbook & Architecture Guide**: Daily real-time inference pipeline, weekly retraining pipeline, staleness guards, failure recovery, and PostgreSQL verification queries. |
| [`docs/01-frontend-guide.md`](docs/01-frontend-guide.md) | The React web app. |
| [`docs/02-api-guide.md`](docs/02-api-guide.md) | The Django API & forecasting backend. |
| [`docs/03-automation-tool-guide.md`](docs/03-automation-tool-guide.md) | The RDA weather-download tool. |
| [`docs/04-reorganization-recommendations.md`](docs/04-reorganization-recommendations.md) | Safe refactoring plan. |
| [`docs/05-data-and-large-files.md`](docs/05-data-and-large-files.md) | Why data isn't in git & how to get it back. |

---

## License

See the `LICENSE` files within each sub-project (Apache-2.0).
