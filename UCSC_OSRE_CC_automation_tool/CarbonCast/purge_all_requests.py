import sys
sys.path.insert(0, 'src/python')
import rdams_client as rc

TOKENS = [
    "rdams_token.txt", "rdams_token2.txt", "rdams_token3.txt", "rdams_token4.txt",
    "rdams_token5.txt", "rdams_token6.txt", "rdams_token7.txt", "rdams_token8.txt",
]

orig_get_auth = rc.get_authentication

for token_file in TOKENS:
    rc.get_authentication = lambda tf=None, _tf=token_file: orig_get_auth(_tf)
    print(f"\n=== {token_file} ===")
    try:
        r = rc.get_status()
    except Exception as e:
        print(f"  Failed to get status: {e}")
        continue

    data = r.get('data', [])
    if not data:
        print("  No open requests.")
        continue

    for x in data:
        rid = int(x.get('request_index'))
        status = x.get('status')
        try:
            rc.purge_request(rid)
            print(f"  Purged {rid} (was {status})")
        except Exception as e:
            print(f"  Failed to purge {rid} (was {status}): {e}")