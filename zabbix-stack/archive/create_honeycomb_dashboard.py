#!/usr/bin/env python3
"""
Create (or re-create) honeycomb dashboards in Zabbix 7.4 for the "Servers" group.

One hexagon per matching (host, item), coloured green (idle) -> red (busy) via
interpolated thresholds. Uses the native `honeycomb` widget (no custom module).

Dashboards built (see DASHBOARDS below):
  - Servers — CPU Honeycomb      item "CPU utilization"          (system.cpu.util)
  - Servers — Memory Honeycomb   item "Memory utilization"       (vm.memory.util*)
  - Servers — Disk Honeycomb     item "FS *: Space: Used, in %"  (vfs.fs.*,pused)

Token is read from /etc/zabbix-stack/stack.env (COMPOSE_ENV_FILES location).
"""
import json, urllib.request, ssl, os, sys
from pathlib import Path

ZABBIX_URL = "https://localhost/zabbix/api_jsonrpc.php"
ENV_FILE   = "/etc/zabbix-stack/stack.env"
HOST_GROUP = "Servers"

# Optional host-tag filter applied to every honeycomb: list of (tag, operator, value).
# operator: 0=Contains, 1=Equals, 4=Exists. Empty list = no filter (all Servers hosts).
HOST_TAGS  = [("site", 1, "SONIC")]

# ── Dashboard definitions ─────────────────────────────────────────────────────
# thresholds: list of (value, hex-color) bands, low -> high.
DASHBOARDS = [
    {
        "name": "Honeycomb / SONIC — CPU",
        "widget_name": "SONIC — CPU utilization",
        "item_pattern": "CPU utilization",
        "ref": "HCCPU",   # broadcast reference id (unique per dashboard, 5 chars)
        "thresholds": [("0", "1A9850"), ("70", "FFD54F"), ("85", "FB6A4A"), ("95", "E53935")],
    },
    {
        "name": "Honeycomb / SONIC — Memory",
        "widget_name": "SONIC — Memory utilization",
        "item_pattern": "Memory utilization",
        "ref": "HCMEM",
        "thresholds": [("0", "1A9850"), ("75", "FFD54F"), ("85", "FB6A4A"), ("95", "E53935")],
    },
    {
        "name": "Honeycomb / SONIC — Disk",
        "widget_name": "SONIC — Filesystem space used",
        "item_pattern": "FS *: Space: Used, in %",   # one cell per filesystem
        "ref": "HCDSK",
        "thresholds": [("0", "1A9850"), ("80", "FFD54F"), ("90", "FB6A4A"), ("95", "E53935")],
    },
]

# ── Auth ──────────────────────────────────────────────────────────────────────

def _load_token() -> str:
    p = Path(ENV_FILE)
    if p.exists():
        for line in p.read_text().splitlines():
            if line.startswith("ZABBIX_API_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"')
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
    req = urllib.request.Request(ZABBIX_URL, data=json.dumps(payload).encode(), headers=headers)
    resp = urllib.request.urlopen(req, context=ctx)
    result = json.loads(resp.read().decode())
    if "error" in result:
        raise SystemExit(f"[{method}] {result['error']}")
    return result["result"]

# ── Widget field helpers (Zabbix widget field types) ──────────────────────────
# 0=INT32  1=STR  2=HOSTGROUP  3=HOST  4=ITEM
def f_int(name, value): return {"type": 0, "name": name, "value": int(value)}
def f_str(name, value): return {"type": 1, "name": name, "value": str(value)}
def f_grp(name, value): return {"type": 2, "name": name, "value": str(value)}

def build_honeycomb_fields(groupid: str, item_pattern: str, thresholds, reference: str):
    fields = [
        f_grp("groupids.0", groupid),
        f_str("items.0", item_pattern),
        f_int("show.0", 1),                  # primary label
        f_int("show.1", 2),                  # secondary label
        f_int("primary_label_type", 0),      # 0 = text
        f_str("primary_label", "{HOST.NAME}"),
        f_int("secondary_label_type", 1),    # 1 = value
        f_int("secondary_label_decimal_places", 0),
        f_int("interpolation", 1),           # smooth green->red gradient
        f_str("reference", reference),       # makes it a broadcaster (clickable)
    ]
    for i, (tag, op, val) in enumerate(HOST_TAGS):
        fields.append(f_str(f"host_tags.{i}.tag", tag))
        fields.append(f_int(f"host_tags.{i}.operator", op))
        fields.append(f_str(f"host_tags.{i}.value", val))
    for i, (thr, color) in enumerate(thresholds):
        fields.append(f_str(f"thresholds.{i}.threshold", thr))
        fields.append(f_str(f"thresholds.{i}.color", color))
    return fields

def build_itemvalue_fields(reference: str):
    # Item-value widget that listens to the honeycomb's broadcast item.
    return [
        f_str("itemid._reference", f"{reference}._itemid"),
        f_str("description", "{HOST.NAME}: {ITEM.NAME}"),  # shown as the description line
        f_int("show.0", 1),   # description
        f_int("show.1", 2),   # value
        f_int("show.2", 3),   # time
        f_int("show.3", 5),   # sparkline (mini trend)
    ]

def build_dashboard(spec, groupid):
    ref = spec["ref"]
    return {
        "name": spec["name"],
        "display_period": 30,
        "auto_start": 1,
        "pages": [{
            "name": "",
            "display_period": 0,
            "widgets": [
                {
                    # full width, short enough to fit one screen without scrolling
                    "type": "honeycomb",
                    "name": spec["widget_name"],
                    "x": 0, "y": 0, "width": 72, "height": 9,
                    "view_mode": 0,
                    "fields": build_honeycomb_fields(groupid, spec["item_pattern"],
                                                     spec["thresholds"], ref),
                },
                {
                    # thin drill-down strip below the honeycomb
                    "type": "item",
                    "name": "Selected item  (click a hexagon)",
                    "x": 0, "y": 9, "width": 72, "height": 3,
                    "view_mode": 0,
                    "fields": build_itemvalue_fields(ref),
                },
            ],
        }],
    }

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    groups = api_call("hostgroup.get", {"output": ["groupid"], "filter": {"name": [HOST_GROUP]}})
    if not groups:
        raise SystemExit(f"Host group '{HOST_GROUP}' not found")
    groupid = groups[0]["groupid"]

    for spec in DASHBOARDS:
        existing = api_call("dashboard.get", {
            "output": ["dashboardid"], "filter": {"name": [spec["name"]]},
        })
        if existing:
            api_call("dashboard.delete", [existing[0]["dashboardid"]])
        result = api_call("dashboard.create", build_dashboard(spec, groupid))
        print(f"  {'re-created' if existing else 'created':>10}: '{spec['name']}' (ID {result['dashboardids'][0]})")

    print("\nOpen: Monitoring → Dashboards → (Servers — CPU / Memory / Disk Honeycomb)")


if __name__ == "__main__":
    main()
