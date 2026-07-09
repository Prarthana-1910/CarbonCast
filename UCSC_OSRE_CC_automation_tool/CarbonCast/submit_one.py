import sys, os, time, json
sys.path.insert(0,'src/python')
import rdams_client as rc

ctl_name = sys.argv[1]  # e.g. AECI_dswrf_chunk1
ctl_path = f'control_files/{ctl_name}_control.ctl'
region, var = ctl_name.split('_', 1)
out_dir = f'downloaded_files/{region}/{var}'

print(f'Submitting {ctl_name}...')
result = rc.submit(ctl_path)
if not result or result.get('status') != 'ok':
    print(f'SUBMIT FAILED: {result}')
    sys.exit(1)

req_id = int(result['data']['request_id'])
print(f'Got request_id {req_id}, polling...')

while True:
    time.sleep(30)
    r = rc.get_status(req_id)
    status = r['data'].get('status') if isinstance(r['data'], dict) else r['data'][0].get('status')
    print(f'  status: {status}')
    if status == 'Completed':
        os.makedirs(out_dir, exist_ok=True)
        rc.download(req_id, out_dir)
        rc.purge_request(req_id)
        print(f'DONE: {ctl_name} -> {out_dir}')
        break
    if status == 'Error':
        print(f'ERROR on {req_id}, not purging — check manually')
        break
