#!/usr/bin/env python3
"""
Configure Storage + Firewall alerts in Zabbix (second batch; companion to
configure_server_threshold_alerts.py).

STORAGE: verification only - RAID/disk health is already monitored by the stock
  HPE MSA 2040 (degraded/fault) and SNMP ReadyNas (raid problem / disk offline)
  templates. The script reports coverage and flags hosts with no health items.

FIREWALL (FortiGate by SNMP hosts): the real work.
  CPU / Memory / Session  -> host-level two-tier triggers (mirrors the server
    design): disable the stock single-tier trigger per host, create Warning +
    Critical, Warning depends on Critical.
      CPU    Warn>=75 / Crit>=90   min(...,10m)
      Memory Warn>=80 / Crit>=95   min(...,10m)
      Session Warn>={$FW.SESSIONS.WARN} / Crit>={$FW.SESSIONS.CRIT}  min(...,10m)
        macros default 700000 / 850000 (per-host, tunable; FG-60F cap ~700k).
  HA Status:
      Failed (Critical/High):   host trigger  last(ha.mode)=1 (standalone) on
        currently-clustered FGs (ha.mode in {2,3}).  Immediate.
      Degraded (Warning):       one trigger prototype on the FortiGate template
        'HA member discovery' LLD - member sync status unsynchronized.

Severities: Warning=2, Critical/Failed=High(4) so only Critical crosses the
existing GLPI action threshold (severity >= Average) -> ticket; Warnings email
only.  Email/escalation use the existing actions (L2 = reuse).

Idempotent + reversible.  Usage:
    python3 configure_storage_firewall_alerts.py --dry-run | --apply | --rollback
"""
import json, os, ssl, sys, urllib.request

ZABBIX_URL = "https://localhost/zabbix/api_jsonrpc.php"
FIREWALL_GROUPS = ["32", "39", "44", "49", "54", "59"]
STORAGE_GROUPS = ["35", "40", "45", "50", "55", "60"]

FGT_TEMPLATE = "FortiGate by SNMP"
HA_LLD_ITEMID = "63237"          # 'HA member discovery' on FortiGate template

SEV_WARNING = 2
SEV_HIGH = 4

CPU_KEY = "system.cpu.util[fgSysCpuUsage.0]"
MEM_KEY = "vm.memory.util[memoryUsedPercentage.0]"
SES_KEY = "net.ipv4.sessions[fgSysSesCount.0]"
HAMODE_KEY = "ha.mode[fgHaSystemMode.0]"
HASYNC_PROTO_KEY = "ha.sync.status[fgHaStatsSyncStatus.{#SNMPINDEX}]"

MACROS = {"{$FW.SESSIONS.WARN}": "700000", "{$FW.SESSIONS.CRIT}": "850000"}

STOCK_DISABLE_NAMES = ["FortiGate: High CPU utilization", "FortiGate: High memory utilization"]
HA_DEGRADED_NAME = "Firewall: HA member {#HA.ID}: desynchronized"
HA_FAILED_NAME = "Firewall: HA cluster not in HA mode (Critical)"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def load_token():
    tok = os.environ.get("ZABBIX_API_TOKEN", "")
    if tok:
        return tok
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


def fw_trig_specs(h):
    """4 cpu/mem + 2 session host-trigger specs: (name, expr, sev, group)."""
    return [
        ("Firewall: CPU utilization >=75% (Warning)",  f"min(/{h}/{CPU_KEY},10m)>=75", SEV_WARNING, "cpu"),
        ("Firewall: CPU utilization >=90% (Critical)", f"min(/{h}/{CPU_KEY},10m)>=90", SEV_HIGH,    "cpu"),
        ("Firewall: Memory utilization >=80% (Warning)",  f"min(/{h}/{MEM_KEY},10m)>=80", SEV_WARNING, "mem"),
        ("Firewall: Memory utilization >=95% (Critical)", f"min(/{h}/{MEM_KEY},10m)>=95", SEV_HIGH,    "mem"),
        ("Firewall: Active sessions >= warn (Warning)",  f"min(/{h}/{SES_KEY},10m)>={{$FW.SESSIONS.WARN}}", SEV_WARNING, "ses"),
        ("Firewall: Active sessions >= crit (Critical)", f"min(/{h}/{SES_KEY},10m)>={{$FW.SESSIONS.CRIT}}", SEV_HIGH,    "ses"),
    ]


def get_fortigate_hosts():
    hosts = api("host.get", {
        "groupids": FIREWALL_GROUPS, "filter": {"status": "0"},
        "output": ["hostid", "host", "name"],
        "selectItems": ["key_", "lastvalue"],
        "selectTriggers": ["triggerid", "description", "status"],
        "selectMacros": ["macro", "value"],
    })
    uniq = {h["hostid"]: h for h in hosts}
    out = []
    for h in uniq.values():
        keys = {i["key_"] for i in h.get("items", [])}
        if CPU_KEY in keys and MEM_KEY in keys:      # real FortiGate (not Sophos/generic)
            out.append(h)
    return out


# ---------------- firewall apply ----------------
def apply_firewall(h, dry):
    hid, hn = h["hostid"], h["host"]
    items = {i["key_"]: i.get("lastvalue") for i in h.get("items", [])}
    existing = {t["description"]: t for t in h.get("triggers", [])}
    macros = {m["macro"]: m["value"] for m in h.get("macros", [])}
    print(f"[{hn}] ({h['name']})")

    # 1. session macros
    for mac, val in MACROS.items():
        if macros.get(mac) != val:
            if dry:
                print(f"    = MACRO {mac}: {macros.get(mac)!r} -> {val}")
            else:
                _set_macro(hid, h, mac, val)

    # 2. disable stock cpu/mem triggers
    for name in STOCK_DISABLE_NAMES:
        t = existing.get(name)
        if t and t.get("status") == "0":
            if dry:
                print(f"    x DISABLE stock trigger {t['triggerid']} ({name})")
            else:
                api("trigger.update", {"triggerid": t["triggerid"], "status": 1})

    # 3. create cpu/mem/session triggers
    created = {}
    for name, expr, sev, grp in fw_trig_specs(hn):
        if name in existing:
            continue
        if dry:
            print(f"    + CREATE [{sev}] {name}  :=  {expr}")
        else:
            r = api("trigger.create", {"description": name, "expression": expr,
                                       "priority": sev, "manual_close": 1})
            created[name] = r["triggerids"][0]

    # 3b. dependencies Warning -> Critical (idempotent)
    if not dry:
        names = [s[0] for s in fw_trig_specs(hn)]
        cur = api("trigger.get", {"hostids": hid, "filter": {"description": names},
                                  "output": ["triggerid", "description"],
                                  "selectDependencies": ["triggerid"]})
        byname = {t["description"]: t for t in cur}
        pairs = [("Firewall: CPU utilization >=75% (Warning)", "Firewall: CPU utilization >=90% (Critical)"),
                 ("Firewall: Memory utilization >=80% (Warning)", "Firewall: Memory utilization >=95% (Critical)"),
                 ("Firewall: Active sessions >= warn (Warning)", "Firewall: Active sessions >= crit (Critical)")]
        for wn, cn in pairs:
            w, c = byname.get(wn), byname.get(cn)
            if w and c and not w.get("dependencies"):
                api("trigger.update", {"triggerid": w["triggerid"],
                                       "dependencies": [{"triggerid": c["triggerid"]}]})
    elif any(s[0] not in existing for s in fw_trig_specs(hn)):
        print("    ~ DEP: each Warning depends on its Critical counterpart")

    # 4. HA failed (only if currently clustered: ha.mode in {2,3})
    hamode = items.get(HAMODE_KEY)
    if hamode in ("2", "3"):
        if HA_FAILED_NAME not in existing:
            expr = f"last(/{hn}/{HAMODE_KEY})=1"
            if dry:
                print(f"    + CREATE [{SEV_HIGH}] {HA_FAILED_NAME}  :=  {expr}")
            else:
                api("trigger.create", {"description": HA_FAILED_NAME, "expression": expr,
                                       "priority": SEV_HIGH, "manual_close": 1})
    else:
        print(f"    - HA-failed skipped (ha.mode={hamode!r}, not a clustered FG)")


def _set_macro(hid, h, mac, val):
    cur = api("usermacro.get", {"hostids": hid, "filter": {"macro": mac}, "output": ["hostmacroid"]})
    if cur:
        api("usermacro.update", {"hostmacroid": cur[0]["hostmacroid"], "value": val})
    else:
        api("usermacro.create", {"hostid": hid, "macro": mac, "value": val})


# ---------------- HA degraded trigger prototype (template-level, once) ----------------
def apply_ha_prototype(dry):
    tid = api("template.get", {"filter": {"host": [FGT_TEMPLATE]}, "output": ["templateid"]})[0]["templateid"]
    existing = api("triggerprototype.get", {"templateids": tid, "output": ["triggerid", "description"]})
    if any(t["description"] == HA_DEGRADED_NAME for t in existing):
        print(f"[template {FGT_TEMPLATE}] HA-degraded prototype already present")
        return
    expr = f"last(/{FGT_TEMPLATE}/{HASYNC_PROTO_KEY})=0"
    if dry:
        print(f"[template {FGT_TEMPLATE}] + CREATE PROTOTYPE [{SEV_WARNING}] {HA_DEGRADED_NAME}  :=  {expr}")
    else:
        api("triggerprototype.create", {"description": HA_DEGRADED_NAME, "expression": expr,
                                        "priority": SEV_WARNING, "manual_close": 1})
        print(f"[template {FGT_TEMPLATE}] created HA-degraded prototype")


# ---------------- storage verification ----------------
def verify_storage():
    hosts = api("host.get", {"groupids": STORAGE_GROUPS, "filter": {"status": "0"},
                             "output": ["hostid", "host"],
                             "selectParentTemplates": ["name"]})
    uniq = {h["hostid"]: h for h in hosts}
    print("\n=== STORAGE coverage (verification only, no changes) ===")
    for h in sorted(uniq.values(), key=lambda x: x["host"]):
        tr = api("trigger.get", {"hostids": h["hostid"], "output": ["description"],
                                 "expandDescription": True})
        health = [t["description"] for t in tr if any(
            w in t["description"].lower() for w in ["health", "raid", "disk", "offline", "fault", "degrad"])]
        tmpl = [t["name"] for t in h.get("parentTemplates", [])]
        if health:
            print(f"  [OK] {h['host']}: {len(health)} RAID/disk health triggers  (tmpl={tmpl})")
        else:
            print(f"  [GAP] {h['host']}: NO RAID/disk health triggers  (tmpl={tmpl}) -- needs a health-aware template")


# ---------------- rollback ----------------
def rollback_firewall(h, dry):
    hid, hn = h["hostid"], h["host"]
    existing = {t["description"]: t for t in h.get("triggers", [])}
    print(f"[{hn}]")
    names = [s[0] for s in fw_trig_specs(hn)] + [HA_FAILED_NAME]
    to_del = [existing[n]["triggerid"] for n in names if n in existing]
    if to_del:
        print(f"    - DELETE {len(to_del)} custom triggers") if dry else api("trigger.delete", to_del)
    for name in STOCK_DISABLE_NAMES:
        t = existing.get(name)
        if t and t.get("status") == "1":
            print(f"    o ENABLE stock {name}") if dry else api("trigger.update", {"triggerid": t["triggerid"], "status": 0})
    for mac in MACROS:
        m = api("usermacro.get", {"hostids": hid, "filter": {"macro": mac}, "output": ["hostmacroid"]})
        if m:
            print(f"    - REMOVE macro {mac}") if dry else api("usermacro.delete", [m[0]["hostmacroid"]])


def rollback_ha_prototype(dry):
    tid = api("template.get", {"filter": {"host": [FGT_TEMPLATE]}, "output": ["templateid"]})[0]["templateid"]
    ex = api("triggerprototype.get", {"templateids": tid, "output": ["triggerid", "description"]})
    for t in ex:
        if t["description"] == HA_DEGRADED_NAME:
            print("    - DELETE HA-degraded prototype") if dry else api("triggerprototype.delete", [t["triggerid"]])


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--dry-run"
    if mode not in ("--dry-run", "--apply", "--rollback"):
        sys.exit("usage: --dry-run | --apply | --rollback")
    dry = mode == "--dry-run"
    fgs = get_fortigate_hosts()
    print(f"Mode: {mode}   FortiGate hosts: {len(fgs)}\n")

    if mode == "--rollback":
        for h in sorted(fgs, key=lambda x: x["host"]):
            rollback_firewall(h, dry)
        rollback_ha_prototype(dry)
    else:
        for h in sorted(fgs, key=lambda x: x["host"]):
            apply_firewall(h, dry)
        apply_ha_prototype(dry)
        verify_storage()

    print("\n(dry-run: nothing changed)" if dry else "\nDone.")


if __name__ == "__main__":
    main()
