import sys, os
sys.path.insert(0, 'src/python')
import rdams_client as rc

TOKENS = [
    "rdams_token.txt", "rdams_token2.txt", "rdams_token3.txt", "rdams_token4.txt",
    "rdams_token5.txt", "rdams_token6.txt", "rdams_token7.txt", "rdams_token8.txt",
]

orig_get_auth = rc.get_authentication

total_purged = 0
total_failed = 0

for token_file in TOKENS:
    if not os.path.exists(token_file):
        print(f"[{token_file}] not found, skipping")
        continue

    rc.get_authentication = lambda tf=None, _tf=token_file: orig_get_auth(_tf)
    print(f"\n=== {token_file} ===")
    try:
        r = rc.get_status()
    except Exception as e:
        print(f"  Failed to get status: {e}")
        continue

    data = r.get('data', [])
    errored = [x for x in data if x.get('status') == 'Error']

    if not errored:
        print("  No errored requests.")
        continue

    for x in errored:
        req_id = int(x.get('request_index'))
        try:
            rc.purge_request(req_id)
            print(f"  Purged errored request {req_id}")
            total_purged += 1
        except Exception as e:
            print(f"  [ERROR] Failed to purge {req_id}: {e}")
            total_failed += 1

print(f"\n{'='*60}")
print(f"Total purged: {total_purged}, failed: {total_failed}")