import sys, os, time, json
sys.path.insert(0,'src/python')
import rdams_client as rc

region = 'AECI'
ctl_dir = 'control_files'
download_dir = 'downloaded_files'
state_file = 'pipeline_state.json'

# Only the 6 missing ones, in order
missing = [
    'AECI_all_chunk1_control.ctl',
    'AECI_all_chunk2_control.ctl'
]

state = json.load(open(state_file))

for ctl in missing:
    ctl_path = os.path.join(ctl_dir, ctl)
    var = ctl.replace('_control.ctl','').split('_',1)[1]
    print(f'Submitting {var}...')
    result = rc.submit(ctl_path)
    print(f'  raw response: {result}')
    if result and result.get('status') == 'ok':
        req_id = result.get('data',{}).get('request_id')
        if req_id:
            # verify it's actually a new unique ID
            if req_id in state['submitted']:
                print(f'  WARNING: {req_id} already in state — possible duplicate!')
            else:
                state['submitted'][str(req_id)] = ctl
                json.dump(state, open(state_file,'w'), indent=2)
                print(f'  -> OK: {req_id}')
    else:
        print(f'  -> FAILED')
    print('  waiting 30s...')
    time.sleep(30)

print('Done submitting. Current state submitted:')
for k,v in state['submitted'].items():
    print(f'  {k} -> {v}')
