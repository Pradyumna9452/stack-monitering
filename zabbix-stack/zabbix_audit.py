import json
import urllib.request
import urllib.error
import ssl
import sys

ZABBIX_URL = "https://localhost/zabbix/api_jsonrpc.php"

# API token auth — load from .env or fall back to env var
import os as _os, pathlib as _pl
def _load_token():
    env_file = _pl.Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("ZABBIX_API_TOKEN="):
                val = line.split("=", 1)[1].strip()
                if val:
                    return val
    return _os.environ.get("ZABBIX_API_TOKEN", "")

ZABBIX_TOKEN = _load_token()
if not ZABBIX_TOKEN:
    raise SystemExit("ZABBIX_API_TOKEN not set in .env")

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def api_call(method, params):
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    headers = {"Content-Type": "application/json-rpc", "Authorization": f"Bearer {ZABBIX_TOKEN}"}
    req = urllib.request.Request(ZABBIX_URL, data=json.dumps(payload).encode(), headers=headers)
    try:
        response = urllib.request.urlopen(req, context=ctx)
        result = json.loads(response.read().decode())
        if "error" in result:
            raise Exception(f"API Error [{method}]: {result['error']}")
        return result["result"]
    except Exception as e:
        print(f"API Error: {e}")
        raise


def main():
    data = {}
    
    hosts = api_call("host.get", {
        "output": ["hostid", "host", "name", "status"],
        "selectParentTemplates": ["templateid", "name"],
        "selectHostGroups": ["groupid", "name"],
        "selectInterfaces": ["interfaceid", "ip", "port", "type", "details"]
    })
    data["hosts"] = hosts

    templates = api_call("template.get", {
        "output": ["templateid", "host", "name"]
    })
    data["templates"] = templates

    triggers = api_call("trigger.get", {
        "output": ["triggerid", "description", "priority", "status", "value"],
        "selectHosts": ["hostid", "name"]
    })
    data["triggers"] = triggers

    dashboards = api_call("dashboard.get", {
        "output": "extend",
        "selectPages": "extend"
    })
    data["dashboards"] = dashboards

    actions = api_call("action.get", {
        "output": "extend",
        "selectOperations": "extend",
        "selectFilter": "extend"
    })
    data["actions"] = actions

    media_types = api_call("mediatype.get", {
        "output": ["mediatypeid", "name", "type", "status"]
    })
    data["media_types"] = media_types

    patterns = [
        "vfs.fs", "system.cpu", "vm.memory", "eventlog", "net.if", 
        "sensor", "temp", "fan", "power", "raid", "disk", "log"
    ]
    item_stats = {}
    for p in patterns:
        items = api_call("item.get", {
            "output": ["itemid"],
            "search": {"key_": p},
            "searchWildcardsEnabled": True
        })
        item_stats[p] = len(items)
    data["item_stats"] = item_stats

    problems = api_call("problem.get", {
        "output": "extend",
        "recent": True,
        "sortfield": ["eventid"],
        "sortorder": "DESC",
        "limit": 50
    })
    data["problems"] = problems

    with open('zabbix-stack/zabbix_audit_data.json', 'w') as f:
        json.dump(data, f, indent=2)

if __name__ == "__main__":
    main()
