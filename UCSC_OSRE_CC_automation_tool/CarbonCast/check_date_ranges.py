import os, re, glob

EXPECTED = {
    "chunk1": ("2024120100", "2025083100"),
    "chunk2": ("2025090100", "2026053100"),
    "full":   ("2024120100", "2026053100"),
}

for f in sorted(glob.glob("downloaded_files/*/*/*.tar")) + sorted(glob.glob("downloaded_files/*/*/*.zip")):
    parts = f.split(os.sep)
    region, var_chunk, fname = parts[1], parts[2], parts[3]

    m = re.search(r'gfs\.0p25\.(\d{10})\.f\d{3}-25\.(\d{10})\.f168', fname)
    if not m:
        print(f"UNPARSEABLE: {region} | {var_chunk} | {fname}")
        continue
    start, end = m.group(1), m.group(2)

    # figure out which chunk this folder claims to be
    key = None
    for k in EXPECTED:
        if var_chunk.endswith(k):
            key = k
            break

    if key is None:
        print(f"UNKNOWN TYPE (no chunk1/chunk2/full suffix): {region} | {var_chunk} | start={start} end={end}")
        continue

    exp_start, exp_end = EXPECTED[key]
    if start != exp_start or end != exp_end:
        print(f"MISMATCH: {region} | {var_chunk} | got {start}-{end} | expected {exp_start}-{exp_end}")
    else:
        print(f"OK: {region} | {var_chunk} | {start}-{end}")
