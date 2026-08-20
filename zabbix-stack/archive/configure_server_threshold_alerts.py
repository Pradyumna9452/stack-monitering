#!/usr/bin/env python3
"""
Configure two-tier (Warning 75% / Critical 90%) CPU, Memory and Disk utilization
alerts on Server-group hosts in Zabbix.

What it does (per eligible server host):
  CPU / Memory:
    - disables the inherited stock "High CPU/memory utilization" trigger on that
      host only (status=1; the shared template is left untouched)
    - creates 4 host-level triggers:
        Server: CPU utilization >=75% (Warning)   sev Warning(2)
        Server: CPU utilization >=90% (Critical)  sev High(4)
        Server: Memory utilization >=75% (Warning) sev Warning(2)
        Server: Memory utilization >=90% (Critical) sev High(4)
      using min(/host/<key>,5m) (5-minute hold), with the Warning trigger
      depending on the Critical trigger (suppresses duplicate Warning at >=90%).
  Disk:
    - sets host macro {$VFS.FS.PUSED.MAX.WARN}=75 (critical stays 90).

Email + GLPI ticket routing is handled by the EXISTING actions:
  - email: "sonic" / "Report problems to Zabbix administrators" (all problems)
  - ticket: "GLPI Ticket Automation" (severity >= Average). Only the Critical
    (High) triggers cross that threshold, so Warnings email-only, Criticals ticket.

Idempotent and reversible. Usage:
    export ZABBIX_API_TOKEN=...        # or rely on .env loading below
    python3 configure_server_threshold_alerts.py --dry-run
    python3 configure_server_threshold_alerts.py --apply
    python3 configure_server_threshold_alerts.py --rollback
"""
import json, os, ssl, sys, urllib.request

ZABBIX_URL = "https://localhost/zabbix/api_jsonrpc.php"
SERVER_GROUP_IDS = ["31", "37", "42", "47", "52", "57"]

# Zabbix severities
SEV_WARNING = 2
SEV_HIGH = 4

DISK_WARN_MACRO = "{$VFS.FS.PUSED.MAX.WARN}"
DISK_WARN_VALUE = "75"

CPU_KEY = "system.cpu.util"
MEM_KEYS = ["vm.memory.util", "vm.memory.utilization"]  # Windows, Linux

STOCK_DISABLE_NAMES = [
    "Windows: High CPU utilization", "Linux: High CPU utilization",
    "Windows: High memory utilization", "Linux: High memory utilization",
]

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def load_token():
    tok = os.environ.get("ZABBIX_API_TOKEN", "")
    if tok:
        return tok
    # fall back to .env next to this script
    env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env):
        for line in open(env):
            if line.startswith("ZABBIX_API_TOKEN="):
                return line.split("=", 1)[1].strip()
    sys.exit("ZABBIX_API_TOKEN not set and not found in .env")


AUTH = load_token()


def api(method, params):
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    headers = {"Content-Type": "application/json-rpc", "Authorization": f"Bearer {AUTH}"}
    req = urllib.request.Request(ZABBIX_URL, data=json.dumps(payload).encode(), headers=headers)
    resp = json.loads(urllib.request.urlopen(req, context=ctx).read())
    if "error" in resp:
        raise RuntimeError(f"{method}: {resp['error']}")
    return resp["result"]


def trig_specs(host, mem_key):
    """Return the 4 desired (name, expression, severity, tier) tuples for a host."""
    h = host
    specs = [
        (f"Server: CPU utilization >=75% (Warning)",  f"min(/{h}/{CPU_KEY},5m)>=75", SEV_WARNING, "cpu_warn"),
        (f"Server: CPU utilization >=90% (Critical)", f"min(/{h}/{CPU_KEY},5m)>=90", SEV_HIGH,    "cpu_crit"),
        (f"Server: Memory utilization >=75% (Warning)",  f"min(/{h}/{mem_key},5m)>=75", SEV_WARNING, "mem_warn"),
        (f"Server: Memory utilization >=90% (Critical)", f"min(/{h}/{mem_key},5m)>=90", SEV_HIGH,    "mem_crit"),
    ]
    return specs


def get_server_hosts():
    hosts = api("host.get", {
        "groupids": SERVER_GROUP_IDS, "filter": {"status": "0"},
        "output": ["hostid", "host", "name"],
        "selectItems": ["key_"],
        "selectTriggers": ["triggerid", "description", "status"],
        "selectMacros": ["macro", "value"],
    })
    # dedupe (a host can be in several server groups)
    uniq = {h["hostid"]: h for h in hosts}
    return list(uniq.values())


def plan_for_host(h):
    keys = {i["key_"] for i in h.get("items", [])}
    has_cpu = CPU_KEY in keys
    mem_key = next((k for k in MEM_KEYS if k in keys), None)
    existing_trig = {t["description"]: t for t in h.get("triggers", [])}
    macros = {m["macro"]: m["value"] for m in h.get("macros", [])}

    actions = {"create": [], "disable": [], "macro": None, "skip_reason": None}

    if not has_cpu and not mem_key:
        actions["skip_reason"] = "no agent CPU/memory items (non-agent host)"

    if has_cpu:
        for name, expr, sev, tier in trig_specs(h["host"], mem_key or "vm.memory.util"):
            if tier.startswith("cpu") and name not in existing_trig:
                actions["create"].append((name, expr, sev, tier))
    if mem_key:
        for name, expr, sev, tier in trig_specs(h["host"], mem_key):
            if tier.startswith("mem") and name not in existing_trig:
                actions["create"].append((name, expr, sev, tier))

    # stock triggers to disable (only those currently enabled)
    for name in STOCK_DISABLE_NAMES:
        t = existing_trig.get(name)
        if t and t.get("status") == "0":
            actions["disable"].append(t["triggerid"])

    # disk warn macro
    if macros.get(DISK_WARN_MACRO) != DISK_WARN_VALUE:
        actions["macro"] = macros.get(DISK_WARN_MACRO)  # current value (or None)

    return actions


def apply_host(h, actions, dry):
    hid, hname = h["hostid"], h["host"]
    created = {}
    # 1. create triggers
    for name, expr, sev, tier in actions["create"]:
        if dry:
            print(f"    + CREATE [{sev}] {name}  :=  {expr}")
        else:
            res = api("trigger.create", {
                "description": name, "expression": expr, "priority": sev,
                "manual_close": 1,
            })
            created[name] = res["triggerids"][0]
    # 1b. dependencies: Warning depends on Critical (idempotent — always ensure)
    if not dry:
        # resolve ids for ALL of this host's Server: triggers (created or pre-existing)
        all_names = [s[0] for s in trig_specs(h["host"], "vm.memory.util")]
        existing = api("trigger.get", {"hostids": hid, "filter": {"description": all_names},
                                       "output": ["triggerid", "description"],
                                       "selectDependencies": ["triggerid"]})
        byname = {t["description"]: t for t in existing}
        for prefix in ("CPU", "Memory"):
            warn = byname.get(f"Server: {prefix} utilization >=75% (Warning)")
            crit = byname.get(f"Server: {prefix} utilization >=90% (Critical)")
            if warn and crit and not warn.get("dependencies"):
                api("trigger.update", {"triggerid": warn["triggerid"],
                                       "dependencies": [{"triggerid": crit["triggerid"]}]})
    elif actions["create"]:
        print(f"    ~ DEP: Warning triggers depend on their Critical counterpart")

    # 2. disable stock triggers
    for tid in actions["disable"]:
        if dry:
            print(f"    x DISABLE stock trigger {tid}")
        else:
            api("trigger.update", {"triggerid": tid, "status": 1})

    # 3. disk macro
    if actions["macro"] is not None or (actions["macro"] is None and _macro_missing(h)):
        cur = actions["macro"]
        if dry:
            print(f"    = MACRO {DISK_WARN_MACRO}: {cur!r} -> {DISK_WARN_VALUE}")
        else:
            _set_macro(hid, h)


def _macro_missing(h):
    macros = {m["macro"]: m["value"] for m in h.get("macros", [])}
    return macros.get(DISK_WARN_MACRO) != DISK_WARN_VALUE


def _set_macro(hid, h):
    existing = next((m for m in h.get("macros", []) if m["macro"] == DISK_WARN_MACRO), None)
    if existing:
        # need the hostmacroid
        full = api("usermacro.get", {"hostids": hid, "filter": {"macro": DISK_WARN_MACRO},
                                     "output": ["hostmacroid"]})
        if full:
            api("usermacro.update", {"hostmacroid": full[0]["hostmacroid"], "value": DISK_WARN_VALUE})
            return
    api("usermacro.create", {"hostid": hid, "macro": DISK_WARN_MACRO, "value": DISK_WARN_VALUE})


def rollback_host(h, dry):
    hid, hname = h["hostid"], h["host"]
    existing_trig = {t["description"]: t for t in h.get("triggers", [])}
    # delete custom triggers
    to_del = [existing_trig[n]["triggerid"] for n in
              [s[0] for s in trig_specs(h["host"], "vm.memory.util")] if n in existing_trig]
    if to_del:
        if dry:
            print(f"    - DELETE custom triggers {to_del}")
        else:
            api("trigger.delete", to_del)
    # re-enable stock triggers
    for name in STOCK_DISABLE_NAMES:
        t = existing_trig.get(name)
        if t and t.get("status") == "1":
            if dry:
                print(f"    o ENABLE stock trigger {t['triggerid']} ({name})")
            else:
                api("trigger.update", {"triggerid": t["triggerid"], "status": 0})
    # remove disk macro
    m = api("usermacro.get", {"hostids": hid, "filter": {"macro": DISK_WARN_MACRO},
                              "output": ["hostmacroid"]})
    if m:
        if dry:
            print(f"    - REMOVE macro {DISK_WARN_MACRO}")
        else:
            api("usermacro.delete", [m[0]["hostmacroid"]])


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--dry-run"
    if mode not in ("--dry-run", "--apply", "--rollback"):
        sys.exit("usage: configure_server_threshold_alerts.py [--dry-run|--apply|--rollback]")
    dry = mode == "--dry-run"
    rollback = mode == "--rollback"

    hosts = get_server_hosts()
    print(f"Mode: {mode}   Server hosts: {len(hosts)}\n")

    n_create = n_disable = n_macro = n_skip = 0
    for h in sorted(hosts, key=lambda x: x["host"]):
        if rollback:
            print(f"[{h['host']}] ({h['name']})")
            rollback_host(h, dry)
            continue
        actions = plan_for_host(h)
        if actions["skip_reason"] and not actions["create"] and not actions["disable"] and actions["macro"] is None:
            n_skip += 1
            print(f"[{h['host']}] SKIP - {actions['skip_reason']}")
            continue
        print(f"[{h['host']}] ({h['name']})"
              + (f"  -- note: {actions['skip_reason']}" if actions["skip_reason"] else ""))
        apply_host(h, actions, dry)
        n_create += len(actions["create"])
        n_disable += len(actions["disable"])
        n_macro += 1 if _macro_missing(h) else 0

    if not rollback:
        print(f"\nSummary: triggers to create={n_create}  stock to disable={n_disable}"
              f"  macros to set={n_macro}  hosts skipped={n_skip}")
    print("\n(dry-run: nothing changed)" if dry else "\nDone.")


if __name__ == "__main__":
    main()
