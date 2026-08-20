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
items = api_call("item.get", {"output": ["key_"]}, auth)
keys = [i["key_"] for i in items]

patterns = ["vfs.fs", "system.cpu", "vm.memory", "eventlog", "net.if", "sensor", "temp", "fan", "power", "raid", "disk", "log"]
stats = {p: sum(1 for k in keys if p in k) for p in patterns}
print(json.dumps(stats, indent=2))
