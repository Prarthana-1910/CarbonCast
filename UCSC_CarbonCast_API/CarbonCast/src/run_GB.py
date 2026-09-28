import requests
import pandas as pd
from urllib.parse import urlencode
from pathlib import Path

# ==========================================================
# Configuration
# ==========================================================

RESOURCE_ID = "f93d1835-75bc-43e5-84ad-12472b180a98"

START = "2024-12-01T00:00:00.000Z"
END   = "2026-05-31T23:59:59.999Z"

OUTPUT = Path(
    "/Users/prarthanapatil/Documents/EnergyAPI11/"
    "CarbonCast/UCSC_CarbonCast_API/CarbonCast/src/"
    "entsoeData/GB_clean_mod.csv"
)

BASE_URL = "https://api.neso.energy/api/3/action/datastore_search_sql"

LIMIT = 10000

# ==========================================================

offset = 0
rows = []

while True:

    sql = f"""
    SELECT *
    FROM "{RESOURCE_ID}"
    WHERE "DATETIME" >= '{START}'
      AND "DATETIME" <= '{END}'
    ORDER BY "_id"
    LIMIT {LIMIT}
    OFFSET {offset}
    """

    response = requests.get(
        BASE_URL,
        params={"sql": sql},
        timeout=60
    )

    response.raise_for_status()

    result = response.json()["result"]["records"]

    if not result:
        break

    rows.extend(result)

    print(f"Downloaded {len(rows)} rows...")

    offset += LIMIT

df = pd.DataFrame(rows)

print(df.head())
print(df.shape)

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
df.to_csv(OUTPUT, index=False)

print(f"\nSaved to:\n{OUTPUT}")