#!/usr/bin/env python3
"""
Create (or re-create) the "Firewall — Bandwidth Honeycomb" dashboard in Zabbix 7.4.

One hexagon per firewall interface, coloured by INBOUND traffic (item name
"*Bits received*", net.if.in, bps): green (idle) -> red (busy) via interpolated
thresholds at 0 / 10M / 100M / 500M bps. Paired with an Item-value strip below
that shows the clicked interface (honeycomb broadcasts its selection).

Scoped to the Firewall group only (121 cells) on purpose: a honeycomb has no
Top-N limit, so a wide scope (e.g. all switches = 600+ cells) hangs the browser.

Token read from /etc/zabbix-stack/stack.env.
"""
import json, urllib.request, ssl, os
from pathlib import Path

ZABBIX_URL     = "https://localhost/zabbix/api_jsonrpc.php"
ENV_FILE       = "/etc/zabbix-stack/stack.env"
DASHBOARD_NAME = "Honeycomb / Firewall — Bandwidth"
HOST_GROUP     = "Firewall"
ITEM_PATTERN   = "*Bits received*"     # inbound; use "*Bits sent*" for outbound
REFERENCE      = "HCBWF"               # honeycomb broadcast id (drill-down)
# bps threshold bands (idle green -> busy red)
THRESHOLDS     = [("0", "1A9850"), ("10000000", "FFD54F"),
                  ("100000000", "FB6A4A"), ("500000000", "E53935")]

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
def f_grp(n, v): return {"type": 2, "name": n, "value": str(v)}

def honeycomb_fields(groupid):
    fields = [
        f_grp("groupids.0", groupid),
        f_str("items.0", ITEM_PATTERN),
        f_int("show.0", 1), f_int("show.1", 2),
        f_int("primary_label_type", 0), f_str("primary_label", "{HOST.NAME}"),
        f_int("secondary_label_type", 1), f_int("secondary_label_decimal_places", 0),
        f_int("interpolation", 1),
        f_str("reference", REFERENCE),
    ]
    for i, (thr, color) in enumerate(THRESHOLDS):
        fields += [f_str(f"thresholds.{i}.threshold", thr), f_str(f"thresholds.{i}.color", color)]
    return fields

def item_fields():
    return [f_str("itemid._reference", f"{REFERENCE}._itemid"),
            f_str("description", "{HOST.NAME}: {ITEM.NAME}"),
            f_int("show.0", 1), f_int("show.1", 2), f_int("show.2", 3), f_int("show.3", 5)]

def main():
    gid = api_call("hostgroup.get", {"output":["groupid"], "filter":{"name":[HOST_GROUP]}})
    if not gid: raise SystemExit(f"Host group '{HOST_GROUP}' not found")
    gid = gid[0]["groupid"]

    dashboard = {
        "name": DASHBOARD_NAME, "display_period": 30, "auto_start": 1,
        "pages": [{"name": "", "display_period": 0, "widgets": [
            {"type":"honeycomb", "name": f"{HOST_GROUP} interfaces — inbound (bps)",
             "x":0,"y":0,"width":72,"height":9,"view_mode":0, "fields": honeycomb_fields(gid)},
            {"type":"item", "name":"Selected interface  (click a hexagon)",
             "x":0,"y":9,"width":72,"height":3,"view_mode":0, "fields": item_fields()},
        ]}],
    }
    existing = api_call("dashboard.get", {"output":["dashboardid"], "filter":{"name":[DASHBOARD_NAME]}})
    if existing:
        api_call("dashboard.delete", [existing[0]["dashboardid"]])
    res = api_call("dashboard.create", dashboard)
    print(f"  {'re-created' if existing else 'created'}: '{DASHBOARD_NAME}' (ID {res['dashboardids'][0]})")
    print("  Open: Monitoring → Dashboards → " + DASHBOARD_NAME)

if __name__ == "__main__":
    main()
