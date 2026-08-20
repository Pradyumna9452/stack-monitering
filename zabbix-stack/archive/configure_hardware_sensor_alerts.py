#!/usr/bin/env python3
"""
Configure tiered Fan RPM, CPU Temperature and Disk Temperature alerts.

Target hosts (resolved dynamically by template, so new hosts on these
templates are picked up automatically):
  - Template "SNMP ReadyNas"     (HONAS, Msour_NAS, Mdeep_NAS, Pat_nas)
      fanRPM                       -> Fan RPM tiers
      temperatureValue.1           -> CPU Temperature tiers
      DiskTemperature[1..4]        -> Disk Temperature tiers (per disk)
  - Template "FortiGate by SNMP" (the 4 branch firewalls)
      hw.sensor.value[...] matching the "CPU ON-DIE Temperature" sensor
      (index differs per host, resolved by item name)      -> CPU Temperature tiers

Fan RPM is NOT applied to the firewalls: only HO_Primary_Firewall exposes a
fan-speed sensor and it idles at ~7000+ RPM (a different fan class), so the
requested 1200-2200 RPM "normal" band would never hold true there.

Thresholds (from requested spec):
  Fan RPM      (item: fanRPM, unitless RPM)
    Warning  : sustained <1000 RPM             (fan slow)
    Critical : sustained <800 RPM               (fan failure)
    High     : sustained >2500 RPM              (heavy load / high temp)
  CPU Temperature (NAS: temperatureValue.1 / FortiGate: CPU ON-DIE sensor, °C)
    Warning  : sustained 65-75C                 (high load)
    Critical : sustained >75C                   (overheat risk)
  Disk Temperature (item: DiskTemperature[N], °C)
    Warning  : sustained 40-50C                 (warm)
    Critical : sustained >=55C                  (risk / failure chance)

All thresholds use a 5-minute sustained hold (matches the pattern used by
configure_server_threshold_alerts.py) to avoid flapping on a single sample.
Each Warning trigger depends on its Critical counterpart so only the more
severe problem is shown once both are true.

Existing single-tier stock triggers that overlap with the new tiered ones
are disabled (status=1) on the host only; the shared templates are left
untouched:
  - "Fan is too slow on {HOST.NAME}"            (fanRPM<2000, NAS)
  - "Temperature CPU is High on {HOST.NAME}"     (temperatureValue.1>55, NAS)
  - "Temperature Disk [N] is High on {HOST.NAME}" (DiskTemperature[N]>45, NAS)

Email + GLPI ticket routing is handled by the EXISTING actions:
  - email: "sonic" / "Report problems to Zabbix administrators" (all problems)
  - ticket: "GLPI Ticket Automation" (severity >= Average). Only the Critical
    triggers (High/4) and the Fan "High" over-speed tier (Average/3) cross
    that threshold, so plain Warnings stay email-only.

Idempotent and reversible. Usage:
    export ZABBIX_API_TOKEN=...        # or rely on .env loading below
    python3 configure_hardware_sensor_alerts.py --dry-run
    python3 configure_hardware_sensor_alerts.py --apply
    python3 configure_hardware_sensor_alerts.py --rollback
"""
import json, os, re, ssl, sys, urllib.request

ZABBIX_URL = "https://localhost/zabbix/api_jsonrpc.php"

TPL_READYNAS = "SNMP ReadyNas"
TPL_FORTIGATE = "FortiGate by SNMP"

SEV_WARNING = 2
SEV_AVERAGE = 3
SEV_HIGH = 4

FAN_KEY = "fanRPM"
NAS_CPU_TEMP_KEY = "temperatureValue.1"

STOCK_DISABLE_NAS = [
    "Fan is too slow on {HOST.NAME}",
    "Temperature CPU is High on {HOST.NAME}",
]  # + "Temperature Disk [N] is High on {HOST.NAME}" per discovered disk index

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


def get_hosts(template_name):
    tpl = api("template.get", {"filter": {"host": [template_name]}, "output": ["templateid"]})
    if not tpl:
        return []
    return api("host.get", {
        "templateids": [tpl[0]["templateid"]], "filter": {"status": "0"},
        "output": ["hostid", "host", "name"],
        "selectItems": ["itemid", "key_", "name"],
        "selectTriggers": ["triggerid", "description", "status"],
    })


def fan_specs(host):
    h = host
    return [
        ("NAS: Fan RPM Warning (<1000 RPM, fan slow)",
         f"max(/{h}/{FAN_KEY},5m)<1000", SEV_WARNING, "fan_warn"),
        ("NAS: Fan RPM Critical (<800 RPM, fan failure)",
         f"max(/{h}/{FAN_KEY},5m)<800", SEV_HIGH, "fan_crit"),
        ("NAS: Fan RPM High (>2500 RPM, heavy load/high temp)",
         f"min(/{h}/{FAN_KEY},5m)>2500", SEV_AVERAGE, "fan_high"),
    ]


def nas_cpu_temp_specs(host):
    h = host
    return [
        ("NAS: CPU Temperature Warning (65-75C, high load)",
         f"min(/{h}/{NAS_CPU_TEMP_KEY},5m)>=65", SEV_WARNING, "cputemp_warn"),
        ("NAS: CPU Temperature Critical (>75C, overheat risk)",
         f"min(/{h}/{NAS_CPU_TEMP_KEY},5m)>75", SEV_HIGH, "cputemp_crit"),
    ]


def disk_temp_specs(host, idx):
    h = host
    key = f"DiskTemperature[{idx}]"
    return [
        (f"NAS: Disk [{idx}] Temperature Warning (40-50C, warm)",
         f"min(/{h}/{key},5m)>=40", SEV_WARNING, f"disk{idx}_warn"),
        (f"NAS: Disk [{idx}] Temperature Critical (>=55C, risk/failure)",
         f"min(/{h}/{key},5m)>=55", SEV_HIGH, f"disk{idx}_crit"),
    ]


def fw_cpu_temp_specs(host, key):
    # hw.sensor.value is a Character-type item on the FortiGate SNMP template
    # (numeric string), so windowed aggregates (min/max) are rejected by the
    # API -- only last() is valid; SNMP's own poll interval provides the debounce.
    h = host
    return [
        ("FortiGate: CPU Temperature Warning (65-75C, high load)",
         f"last(/{h}/{key})>=65", SEV_WARNING, "cputemp_warn"),
        ("FortiGate: CPU Temperature Critical (>75C, overheat risk)",
         f"last(/{h}/{key})>75", SEV_HIGH, "cputemp_crit"),
    ]


def all_nas_names(host):
    names = [s[0] for s in fan_specs(host)] + [s[0] for s in nas_cpu_temp_specs(host)]
    for idx in range(1, 9):
        names += [s[0] for s in disk_temp_specs(host, idx)]
    return names


def plan_nas_host(h):
    keys = {i["key_"] for i in h.get("items", [])}
    existing_trig = {t["description"]: t for t in h.get("triggers", [])}
    disk_idx = sorted(int(m.group(1)) for k in keys
                       for m in [re.match(r"DiskTemperature\[(\d+)\]", k)] if m)

    actions = {"create": [], "disable": []}

    if FAN_KEY in keys:
        for name, expr, sev, tier in fan_specs(h["host"]):
            if name not in existing_trig:
                actions["create"].append((name, expr, sev, tier))
    if NAS_CPU_TEMP_KEY in keys:
        for name, expr, sev, tier in nas_cpu_temp_specs(h["host"]):
            if name not in existing_trig:
                actions["create"].append((name, expr, sev, tier))
    for idx in disk_idx:
        for name, expr, sev, tier in disk_temp_specs(h["host"], idx):
            if name not in existing_trig:
                actions["create"].append((name, expr, sev, tier))

    disable_names = list(STOCK_DISABLE_NAS)
    disable_names += [f"Temperature Disk [{idx}] is High on {{HOST.NAME}}" for idx in disk_idx]
    for name in disable_names:
        t = existing_trig.get(name)
        if t and t.get("status") == "0":
            actions["disable"].append(t["triggerid"])

    return actions


def plan_fw_host(h):
    cpu_item = next((i for i in h.get("items", [])
                      if i["name"] == "Sensor CPU ON-DIE Temperature: Value"), None)
    existing_trig = {t["description"]: t for t in h.get("triggers", [])}
    actions = {"create": [], "disable": [], "skip_reason": None}

    if not cpu_item:
        actions["skip_reason"] = "no CPU ON-DIE temperature sensor item"
        return actions

    for name, expr, sev, tier in fw_cpu_temp_specs(h["host"], cpu_item["key_"]):
        if name not in existing_trig:
            actions["create"].append((name, expr, sev, tier))
    return actions


def apply_creates(h, creates, dep_pairs, dry):
    hid, hname = h["hostid"], h["host"]
    for name, expr, sev, tier in creates:
        if dry:
            print(f"    + CREATE [{sev}] {name}  :=  {expr}")
        else:
            api("trigger.create", {"description": name, "expression": expr,
                                    "priority": sev, "manual_close": 1})
    if not dry and dep_pairs:
        all_names = sorted({n for pair in dep_pairs for n in pair})
        existing = api("trigger.get", {"hostids": hid, "filter": {"description": all_names},
                                        "output": ["triggerid", "description"],
                                        "selectDependencies": ["triggerid"]})
        byname = {t["description"]: t for t in existing}
        for warn_name, crit_name in dep_pairs:
            warn, crit = byname.get(warn_name), byname.get(crit_name)
            if warn and crit and not warn.get("dependencies"):
                api("trigger.update", {"triggerid": warn["triggerid"],
                                        "dependencies": [{"triggerid": crit["triggerid"]}]})
    elif creates and dep_pairs:
        print("    ~ DEP: Warning triggers depend on their Critical counterpart")


def disable_triggers(disable_ids, dry):
    for tid in disable_ids:
        if dry:
            print(f"    x DISABLE stock trigger {tid}")
        else:
            api("trigger.update", {"triggerid": tid, "status": 1})


def rollback_nas_host(h, dry):
    existing_trig = {t["description"]: t for t in h.get("triggers", [])}
    names = all_nas_names(h["host"])
    to_del = [existing_trig[n]["triggerid"] for n in names if n in existing_trig]
    if to_del:
        if dry:
            print(f"    - DELETE custom triggers {to_del}")
        else:
            api("trigger.delete", to_del)
    keys = {i["key_"] for i in h.get("items", [])}
    disk_idx = sorted(int(m.group(1)) for k in keys
                       for m in [re.match(r"DiskTemperature\[(\d+)\]", k)] if m)
    disable_names = list(STOCK_DISABLE_NAS)
    disable_names += [f"Temperature Disk [{idx}] is High on {{HOST.NAME}}" for idx in disk_idx]
    for name in disable_names:
        t = existing_trig.get(name)
        if t and t.get("status") == "1":
            if dry:
                print(f"    o ENABLE stock trigger {t['triggerid']} ({name})")
            else:
                api("trigger.update", {"triggerid": t["triggerid"], "status": 0})


def rollback_fw_host(h, dry):
    existing_trig = {t["description"]: t for t in h.get("triggers", [])}
    names = [s[0] for s in fw_cpu_temp_specs(h["host"], "x")]
    to_del = [existing_trig[n]["triggerid"] for n in names if n in existing_trig]
    if to_del:
        if dry:
            print(f"    - DELETE custom triggers {to_del}")
        else:
            api("trigger.delete", to_del)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--dry-run"
    if mode not in ("--dry-run", "--apply", "--rollback"):
        sys.exit("usage: configure_hardware_sensor_alerts.py [--dry-run|--apply|--rollback]")
    dry = mode == "--dry-run"
    rollback = mode == "--rollback"

    nas_hosts = sorted(get_hosts(TPL_READYNAS), key=lambda x: x["host"])
    fw_hosts = sorted(get_hosts(TPL_FORTIGATE), key=lambda x: x["host"])
    print(f"Mode: {mode}   NAS hosts: {len(nas_hosts)}   FortiGate hosts: {len(fw_hosts)}\n")

    n_create = n_disable = n_skip = 0

    for h in nas_hosts:
        print(f"[{h['host']}] ({h['name']})")
        if rollback:
            rollback_nas_host(h, dry)
            continue
        actions = plan_nas_host(h)
        dep_pairs = []
        for base, warn_suffix, crit_suffix in [
            ("Fan", "NAS: Fan RPM Warning (<1000 RPM, fan slow)",
             "NAS: Fan RPM Critical (<800 RPM, fan failure)"),
            ("CPU", "NAS: CPU Temperature Warning (65-75C, high load)",
             "NAS: CPU Temperature Critical (>75C, overheat risk)"),
        ]:
            dep_pairs.append((warn_suffix, crit_suffix))
        keys = {i["key_"] for i in h.get("items", [])}
        disk_idx = sorted(int(m.group(1)) for k in keys
                           for m in [re.match(r"DiskTemperature\[(\d+)\]", k)] if m)
        for idx in disk_idx:
            dep_pairs.append((f"NAS: Disk [{idx}] Temperature Warning (40-50C, warm)",
                               f"NAS: Disk [{idx}] Temperature Critical (>=55C, risk/failure)"))
        apply_creates(h, actions["create"], dep_pairs, dry)
        disable_triggers(actions["disable"], dry)
        n_create += len(actions["create"])
        n_disable += len(actions["disable"])

    for h in fw_hosts:
        if rollback:
            print(f"[{h['host']}] ({h['name']})")
            rollback_fw_host(h, dry)
            continue
        actions = plan_fw_host(h)
        if actions["skip_reason"]:
            print(f"[{h['host']}] SKIP - {actions['skip_reason']}")
            n_skip += 1
            continue
        print(f"[{h['host']}] ({h['name']})")
        dep_pairs = [("FortiGate: CPU Temperature Warning (65-75C, high load)",
                      "FortiGate: CPU Temperature Critical (>75C, overheat risk)")]
        apply_creates(h, actions["create"], dep_pairs, dry)
        n_create += len(actions["create"])

    if not rollback:
        print(f"\nSummary: triggers to create={n_create}  stock to disable={n_disable}"
              f"  hosts skipped={n_skip}")
    print("\n(dry-run: nothing changed)" if dry else "\nDone.")


if __name__ == "__main__":
    main()
