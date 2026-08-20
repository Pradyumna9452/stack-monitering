#!/usr/bin/env python3
"""
Create (or re-create) a modern SVG-graph dashboard for one interface's traffic.

Plots Bits received (in) + Bits sent (out) for a given host/interface as filled
lines with a min/avg/max legend — the Zabbix 7.x "modern" native graph, versus
the legacy history.php simple graph.

Default target: HO Sophos Internet Proxy Firewall, interface "lan" (itemid 104243
was net.if.in for this interface). Token read from /etc/zabbix-stack/stack.env.
"""
import json, urllib.request, ssl, os
from pathlib import Path

ZABBIX_URL     = "https://localhost/zabbix/api_jsonrpc.php"
ENV_FILE       = "/etc/zabbix-stack/stack.env"
DASHBOARD_NAME = "Interface Traffic — HO Sophos lan"

HOST_NAME      = "HO Sophos Internet Proxy Firewall"   # host visible name (pattern)
IN_ITEM        = "Interface lan(): Bits received"
OUT_ITEM       = "Interface lan(): Bits sent"

def _load_token() -> str:
    p = Path(ENV_FILE)
    if p.exists():
        for line in p.read_text().splitlines():
            if line.startswith("ZABBIX_API_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"')
    return os.environ.get("ZABBIX_API_TOKEN", "")

ZABBIX_TOKEN = _load_token()
if not ZABBIX_TOKEN:
    raise SystemExit(f"ZABBIX_API_TOKEN not found in {ENV_FILE}")

ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE

def api_call(method, params):
    req = urllib.request.Request(ZABBIX_URL, data=json.dumps(
        {"jsonrpc":"2.0","method":method,"params":params,"id":1}).encode(),
        headers={"Content-Type":"application/json-rpc","Authorization":f"Bearer {ZABBIX_TOKEN}"})
    r = json.loads(urllib.request.urlopen(req, context=ctx).read())
    if "error" in r: raise SystemExit(f"[{method}] {r['error']}")
    return r["result"]

def f_int(n, v): return {"type": 0, "name": n, "value": int(v)}
def f_str(n, v): return {"type": 1, "name": n, "value": str(v)}

def dataset(idx, item, color):
    # SVG_GRAPH_TYPE_LINE=0 ; filled area via fill>0 ; semi-transparent
    return [
        f_str(f"ds.{idx}.hosts.0", HOST_NAME),
        f_str(f"ds.{idx}.items.0", item),
        f_str(f"ds.{idx}.color", color),
        f_int(f"ds.{idx}.type", 0),          # line
        f_int(f"ds.{idx}.width", 2),
        f_int(f"ds.{idx}.fill", 4),          # area fill
        f_int(f"ds.{idx}.transparency", 4),
        f_int(f"ds.{idx}.missingdatafunc", 1),  # connect gaps
    ]

def graph_fields():
    fields = []
    fields += dataset(0, IN_ITEM,  "1A9850")   # received / in  = green
    fields += dataset(1, OUT_ITEM, "1F77B4")   # sent / out      = blue
    fields += [
        f_int("legend", 1),
        f_int("legend_statistic", 1),          # show min / avg / max
        f_str("reference", "SVGIF"),
    ]
    return fields

DASHBOARD = {
    "name": DASHBOARD_NAME, "display_period": 30, "auto_start": 0,
    "pages": [{"name": "", "display_period": 0, "widgets": [
        {"type": "svggraph", "name": f"{HOST_NAME} — lan traffic (in/out, bps)",
         "x": 0, "y": 0, "width": 72, "height": 13, "view_mode": 0, "fields": graph_fields()},
    ]}],
}

def main():
    existing = api_call("dashboard.get", {"output":["dashboardid"], "filter":{"name":[DASHBOARD_NAME]}})
    if existing:
        api_call("dashboard.delete", [existing[0]["dashboardid"]])
    res = api_call("dashboard.create", DASHBOARD)
    print(f"  {'re-created' if existing else 'created'}: '{DASHBOARD_NAME}' (ID {res['dashboardids'][0]})")
    print("  Open: Monitoring → Dashboards → " + DASHBOARD_NAME)

if __name__ == "__main__":
    main()
