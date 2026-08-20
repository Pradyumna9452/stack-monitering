#!/usr/bin/env python3
"""
Create (or re-create) ONE combined honeycomb dashboard with a page per metric.

Dashboard "Honeycomb / All" — 4 pages, each = a honeycomb (broadcaster) + an
Item-value strip below (click a hexagon -> strip shows that item):
  1. SONIC — CPU        (Servers grp, host tag site=SONIC, "CPU utilization")
  2. SONIC — Memory     (               "Memory utilization")
  3. SONIC — Disk        (               "FS *: Space: Used, in %")
  4. Firewall — Bandwidth (Firewall grp, "*Bits received*", inbound bps)

Token read from /etc/zabbix-stack/stack.env.
"""
import json, urllib.request, ssl, os
from pathlib import Path

ZABBIX_URL     = "https://localhost/zabbix/api_jsonrpc.php"
ENV_FILE       = "/etc/zabbix-stack/stack.env"
DASHBOARD_NAME = "Honeycomb / All"

# page specs: (page_name, host_group, host_tags, item_pattern, ref, thresholds, widget_name)
PAGES = [
    ("CPU", "Servers", [("site", 1, "SONIC")], "CPU utilization", "HCCPU",
     [("0","1A9850"),("70","FFD54F"),("85","FB6A4A"),("95","E53935")], "SONIC — CPU utilization"),
    ("Memory", "Servers", [("site", 1, "SONIC")], "Memory utilization", "HCMEM",
     [("0","1A9850"),("75","FFD54F"),("85","FB6A4A"),("95","E53935")], "SONIC — Memory utilization"),
    ("Disk", "Servers", [("site", 1, "SONIC")], "FS *: Space: Used, in %", "HCDSK",
     [("0","1A9850"),("80","FFD54F"),("90","FB6A4A"),("95","E53935")], "SONIC — Filesystem space used"),
    ("Bandwidth", "Firewall", [], "*Bits received*", "HCBWF",
     [("0","1A9850"),("10000000","FFD54F"),("100000000","FB6A4A"),("500000000","E53935")],
     "Firewall interfaces — inbound (bps)"),
]

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

def group_id(name, cache={}):
    if name not in cache:
        g = api_call("hostgroup.get", {"output":["groupid"], "filter":{"name":[name]}})
        if not g: raise SystemExit(f"Host group '{name}' not found")
        cache[name] = g[0]["groupid"]
    return cache[name]

def honeycomb_fields(gid, host_tags, pattern, ref, thresholds):
    fields = [
        f_grp("groupids.0", gid), f_str("items.0", pattern),
        f_int("show.0", 1), f_int("show.1", 2),
        f_int("primary_label_type", 0), f_str("primary_label", "{HOST.NAME}"),
        f_int("secondary_label_type", 1), f_int("secondary_label_decimal_places", 0),
        f_int("interpolation", 1), f_str("reference", ref),
    ]
    for i,(tag,op,val) in enumerate(host_tags):
        fields += [f_str(f"host_tags.{i}.tag",tag), f_int(f"host_tags.{i}.operator",op), f_str(f"host_tags.{i}.value",val)]
    for i,(thr,color) in enumerate(thresholds):
        fields += [f_str(f"thresholds.{i}.threshold",thr), f_str(f"thresholds.{i}.color",color)]
    return fields

def item_fields(ref):
    return [f_str("itemid._reference", f"{ref}._itemid"),
            f_str("description", "{HOST.NAME}: {ITEM.NAME}"),
            f_int("show.0",1), f_int("show.1",2), f_int("show.2",3), f_int("show.3",5)]

def build_page(spec):
    pname, grp, htags, pattern, ref, thr, wname = spec
    gid = group_id(grp)
    return {
        "name": pname, "display_period": 0,
        "widgets": [
            {"type":"honeycomb", "name": wname, "x":0,"y":0,"width":72,"height":9,"view_mode":0,
             "fields": honeycomb_fields(gid, htags, pattern, ref, thr)},
            {"type":"item", "name":"Selected item  (click a hexagon)", "x":0,"y":9,"width":72,"height":3,
             "view_mode":0, "fields": item_fields(ref)},
        ],
    }

def main():
    dashboard = {
        "name": DASHBOARD_NAME, "display_period": 30, "auto_start": 0,  # no auto-rotate
        "pages": [build_page(s) for s in PAGES],
    }
    existing = api_call("dashboard.get", {"output":["dashboardid"], "filter":{"name":[DASHBOARD_NAME]}})
    if existing:
        api_call("dashboard.delete", [existing[0]["dashboardid"]])
    res = api_call("dashboard.create", dashboard)
    print(f"  {'re-created' if existing else 'created'}: '{DASHBOARD_NAME}' (ID {res['dashboardids'][0]}) "
          f"with {len(PAGES)} pages: " + ", ".join(p[0] for p in PAGES))
    print("  Open: Monitoring → Dashboards → " + DASHBOARD_NAME)

if __name__ == "__main__":
    main()
