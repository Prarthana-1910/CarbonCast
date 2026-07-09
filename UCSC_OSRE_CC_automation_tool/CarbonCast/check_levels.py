import sys; sys.path.insert(0,'src/python')
import rdams_client as rc
import requests

token = rc.get_authentication()
url = rc.BASE_URL + 'metadata/ds084.1'
r = requests.get(rc.encode_url(url, token))
data = r.json()
param_list = data['data']['data']

targets = ['DSWRF', 'A PCP', 'TMP', 'DPT', 'U GRD', 'V GRD']

seen = set()
for p in param_list:
    param = p.get('param')
    if param in targets:
        levels = p.get('levels') or []
        for lv in levels:
            key = (param, lv.get('level'), lv.get('level_value'), lv.get('level_description'))
            if key not in seen:
                seen.add(key)

for param, level, level_value, level_desc in sorted(seen, key=lambda x: (x[0], str(x[1]))):
    print(f"param={param:8} level={level}:{level_value:6} | {level_desc}")
