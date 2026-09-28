#!/usr/bin/env python3
"""
submit_gb_weather_request.py
Submits NCAR RDA (ds084.1) subset requests for GB for the single window
2026-06-01 00:00 to 2026-09-23 00:00 in one go across all 4 variables:
  - temp (TMP/DPT, HTGL:2)
  - wind (U GRD/V GRD, HTGL:10)
  - dswrf (DSWRF, SFC:0)
  - rain (A PCP, SFC:0)
"""
import sys
import os

sys.path.insert(0, 'src/python')
import rdams_client as rc

TOKEN_FILE = "rdams_token.txt"
rc.DEFAULT_AUTH_FILE = TOKEN_FILE

REGION = "GB"
START_DATE = "202606010000"
END_DATE   = "202609230000"

BBOX = {
    "nlat": "61",
    "slat": "49.75",
    "wlon": "-8.25",
    "elon": "2.25",
}

PARAM_LEVEL = {
    "temp":  ("TMP/DPT",     "HTGL:2"),
    "wind":  ("U GRD/V GRD", "HTGL:10"),
    "dswrf": ("DSWRF",       "SFC:0"),
    "rain":  ("A PCP",       "SFC:0"),
}

def build_product(var):
    if var == "dswrf":
        return "/".join(f"3-hour Average (initial+{s} to initial+{s+3})/6-hour Average (initial+{s} to initial+{s+6})" for s in range(0, 168, 6))
    elif var == "rain":
        return "/".join(f"3-hour Accumulation (initial+{s} to initial+{s+3})/6-hour Accumulation (initial+{s} to initial+{s+6})" for s in range(0, 168, 6))
    else:
        return "Analysis/" + "/".join(f"{h}-hour Forecast" for h in range(3, 169, 3))

def main():
    os.makedirs("control_files", exist_ok=True)
    requests_submitted = {}

    for var, (param, level) in PARAM_LEVEL.items():
        label = f"{REGION}_{var}_20260601_20260923"
        ctl_path = f"control_files/{label}_control.ctl"
        product = build_product(var)

        ctl_content = f"""dataset=ds084.1
date={START_DATE}/to/{END_DATE}
datetype=init
param={param}
level={level}
nlat={BBOX['nlat']}
slat={BBOX['slat']}
wlon={BBOX['wlon']}
elon={BBOX['elon']}
product={product}
"""
        with open(ctl_path, "w") as f:
            f.write(ctl_content)
        print(f"Wrote {ctl_path}")

        print(f"Submitting {var} to RDA...")
        try:
            res = rc.submit(ctl_path)
            print(f"RDA response for {var}: {res}")
            if res and res.get("status") == "ok":
                req_id = res["data"].get("request_index") or res["data"].get("request_id")
                requests_submitted[var] = req_id
                print(f"SUCCESS: Submitted {var} with request index: {req_id}")
            else:
                requests_submitted[var] = f"FAILED: {res}"
        except Exception as exc:
            print(f"ERROR submitting {var}: {exc}")
            requests_submitted[var] = f"ERROR: {exc}"

    print("\nSummary of submissions:")
    for v, rid in requests_submitted.items():
        print(f"  {v}: {rid}")

if __name__ == "__main__":
    main()
