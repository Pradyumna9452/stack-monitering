import json, urllib.request, ssl, sys
ZABBIX_URL = "https://localhost/zabbix/api_jsonrpc.php"
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
def api_call(method, params, auth=None):
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    headers = {'Content-Type': 'application/json-rpc'}
    if auth: headers['Authorization'] = f'Bearer {auth}'
    req = urllib.request.Request(ZABBIX_URL, data=json.dumps(payload).encode('utf-8'), headers=headers)
    return json.loads(urllib.request.urlopen(req, context=ctx).read().decode('utf-8'))["result"]

import os
auth = os.environ.get("ZABBIX_API_TOKEN", "")
items = api_call("item.get", {"output": ["itemid", "key_", "name"], "limit": 100}, auth)
print(json.dumps(items[:20], indent=2))
