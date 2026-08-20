#!/usr/bin/env python3
"""
Create (or re-create) the SONIC Site Overview dashboard in Zabbix.

The dashboard contains a single full-page custom widget (sonicoverview)
that displays a live grid of all SONIC-tagged hosts with:
  Hostname | IP | Status | CPU % | Memory % | Disk % | BW In | BW Out | Alarms

Requires the sonic_overview module to be loaded in Zabbix (mounted into
/usr/share/zabbix/modules/sonic_overview/ and enabled via Administration →
General → Modules).
"""
import json, urllib.request, ssl, os, sys
from pathlib import Path

ZABBIX_URL    = "https://localhost/zabbix/api_jsonrpc.php"
DASHBOARD_NAME = "SONIC Site Overview"

# ── Auth ──────────────────────────────────────────────────────────────────────

ENV_FILE = "/etc/zabbix-stack/stack.env"

def _load_token() -> str:
    env_file = Path(ENV_FILE)
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("ZABBIX_API_TOKEN="):
                val = line.split("=", 1)[1].strip().strip('"')
                if val:
                    return val
    return os.environ.get("ZABBIX_API_TOKEN", "")

ZABBIX_TOKEN = _load_token()
if not ZABBIX_TOKEN:
    raise SystemExit(f"ZABBIX_API_TOKEN not found in {ENV_FILE} or environment")

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def api_call(method: str, params):
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    headers = {
        "Content-Type": "application/json-rpc",
        "Authorization": f"Bearer {ZABBIX_TOKEN}",
    }
    req = urllib.request.Request(
        ZABBIX_URL, data=json.dumps(payload).encode(), headers=headers
    )
    try:
        resp = urllib.request.urlopen(req, context=ctx)
        result = json.loads(resp.read().decode())
        if "error" in result:
            raise Exception(f"[{method}] {result['error']}")
        return result["result"]
    except Exception as exc:
        print(f"API error: {exc}", file=sys.stderr)
        raise

# ── Dashboard definition ──────────────────────────────────────────────────────

DASHBOARD = {
    "name": DASHBOARD_NAME,
    "display_period": 30,
    "auto_start": 1,
    "pages": [
        {
            "name": "",
            "display_period": 0,
            "widgets": [
                {
                    "type": "sonic_overview",
                    "name": "SONIC Site — Live Host Grid",
                    "x": 0,
                    "y": 0,
                    "width": 24,
                    "height": 28,
                    "view_mode": 0,
                    "fields": [],
                }
            ],
        }
    ],
}

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # Remove stale dashboard if it exists
    existing = api_call("dashboard.get", {
        "output": ["dashboardid", "name"],
        "filter": {"name": [DASHBOARD_NAME]},
    })
    if existing:
        api_call("dashboard.delete", [existing[0]["dashboardid"]])
        print(f"  Removed existing dashboard: {DASHBOARD_NAME}")

    result = api_call("dashboard.create", DASHBOARD)
    dash_id = result["dashboardids"][0]
    print(f"  Created dashboard: '{DASHBOARD_NAME}' (ID: {dash_id})")
    print()
    print("Next steps:")
    print("  1. Restart zabbix-web so the module is picked up:")
    print("       docker compose restart zabbix-web")
    print("  2. Enable the module in Zabbix:")
    print("       Administration → General → Modules → SONIC Site Overview → Enable")
    print(f"  3. Open: Monitoring → Dashboards → {DASHBOARD_NAME}")


if __name__ == "__main__":
    main()
