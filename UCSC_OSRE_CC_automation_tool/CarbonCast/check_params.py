import sys; sys.path.insert(0,'src/python')
import rdams_client as rc
import requests

token = rc.get_authentication()
url = rc.BASE_URL + 'metadata/ds084.1'
r = requests.get(rc.encode_url(url, token))
data = r.json()

param_list = data['data']['data']
print("Number of param entries:", len(param_list))

seen = set()
for p in param_list:
    key = (p.get('param'), p.get('param_description'))
    seen.add(key)

for param, desc in sorted(seen, key=lambda x: str(x[1])):
    print(f"param={param!r:15} | {desc}")
