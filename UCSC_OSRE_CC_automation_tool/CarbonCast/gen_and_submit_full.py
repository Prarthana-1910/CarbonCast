import sys, os, re

if len(sys.argv) < 3:
    print("Usage: python3 gen_and_submit_full.py REGION VAR")
    print("VAR must be one of: dswrf rain temp wind")
    sys.exit(1)

region, var = sys.argv[1], sys.argv[2]

PARAM_LEVEL = {
    "dswrf": ("DSWRF", "SFC:0"),
    "rain":  ("A PCP", "SFC:0"),
    "temp":  ("TMP/DPT", "HTGL:2"),
    "wind":  ("U GRD/V GRD", "HTGL:10"),
}
if var not in PARAM_LEVEL:
    print(f"Unknown var {var}")
    sys.exit(1)
param, level = PARAM_LEVEL[var]

src_ctl = f"control_files/{region}_{var}_chunk1_control.ctl"
if not os.path.exists(src_ctl):
    print(f"Can't find {src_ctl} to read bbox from")
    sys.exit(1)

bbox = {}
for line in open(src_ctl):
    m = re.match(r"^(nlat|slat|wlon|elon)=(.+)$", line.strip())
    if m:
        bbox[m.group(1)] = m.group(2)

product = "Analysis/" + "/".join(f"{h}-hour Forecast" for h in range(3, 169, 3))

out_path = f"control_files/{region}_{var}_full_control.ctl"
with open(out_path, "w") as f:
    f.write(f"""dataset=ds084.1
date=202412010000/to/202605310000
datetype=init
param={param}
level={level}
nlat={bbox['nlat']}
slat={bbox['slat']}
wlon={bbox['wlon']}
elon={bbox['elon']}
product={product}
""")

print(f"Wrote {out_path}")
os.execvp("python3", ["python3", "submit_one.py", f"{region}_{var}_full"])
