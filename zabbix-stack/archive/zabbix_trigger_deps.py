#!/usr/bin/env python3
"""
Set up Zabbix trigger dependencies based on network topology.
If a parent device goes unreachable, all downstream device alerts are suppressed.

Network topology (parent → children):
  HO:    Firewall → Core Switches → Dept Switches / Servers / Storage
  SONIC:            Core Switch   → SAN Switches  / Servers / Storage
  SEZ:   Firewall → Core Switches → Dept Switches / Servers / Storage
  MSOUR: Firewall → Core Switch   → Dept Switches / Servers / Storage
  MDEEP: Firewall → Core Switch   → Dept Switches / Servers / Storage
"""
import json, urllib.request, ssl

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


# ── Network topology: parent hostid → [child hostids] ──────────────────────
TOPOLOGY = {
    # ── HO ──────────────────────────────────────────────────────────────────
    # Firewall is the site gateway
    "10955": [                           # HO_Primary_Firewall
        "10948",                         #   → Dept Core Switch Primary
        "10984",                         #   → Core HO VDI Switch Primary
        "10889",                         #   → HO_WiFi Uplink
        "10947",                         #   → HO_SOPHOS_INTERNET_PROXY_FW1
    ],
    "10948": [                           # Dept Core Switch Primary
        "10928",                         #   → Dept Core Switch Secondary
        "10929","10930","10931",         #   → Dept Switch 01-03
        "10932","10933","10934",         #   → Dept Switch 04-06
        "10935","10936","10937",         #   → Dept Switch 07-09
        "10938",                         #   → HO_WiFi Switch 10 standby
        "10909","10972","10899",         #   → HOVMHOST, VMT-2024, HO-VMS
        "10973",                         #   → SOPHOSVM
        "10888","11000",                 #   → HONAS, SONIC-SAN
    ],
    "10984": [                           # Core HO VDI Switch Primary
        "10939",                         #   → Core HO VDI Switch Secondary
        "10965","10966","10967","10891", #   → HOVDI01/02, DRHOVDI, TESTVDI
    ],
    "10889": [                           # HO_WiFi Uplink
        "10938",                         #   → HO_WiFi Switch 10 standby
    ],

    # ── SONIC (main DC, no on-site firewall in scope) ────────────────────────
    "10949": [                           # Core development Switch Primary
        "10940",                         #   → Core devlopment Switch Secondary
        "10950",                         #   → San Switch primary
        "10976","10908","10901","10921", #   → SONICAD, DRVDI, AIHOSTSERVER, SAP-DEVHOST1
        "10910","10978","10979","10922", #   → DEVSAPWINHOST, COPA, COPA-PRD, ARCBKP2
        "10912","10902","10900","10920", #   → Mailvault, HPHOST, ECMHOST, SQLDB
        "11004","10974","10975","10977", #   → SOCVM, RDG1, RGVPN2, RDG-POWERBI-DEV
        "10981","10982","10985","10986", #   → SBEL* servers
        "10987","10988","10989","10887", #   → sbels4* servers, DR-InternetVM
        "11002",                         #   → SONICBIOCHEM_MSA2
    ],
    "10950": [                           # San Switch primary
        "10941",                         #   → San Switch secondary
        "11001",                         #   → SONICBIOCHEM_MSA1
    ],

    # ── SEZ ─────────────────────────────────────────────────────────────────
    "10945": [                           # SEZ_Pithampur_Primary_FW
        "10951",                         #   → SEZ_Core_Primery1
        "10970","10980","10968","10927", #   → SEZ VDI/servers
        "10961",                         #   → SEZ_NAS
    ],
    "10951": [                           # SEZ_Core_Primery1
        "10898",                         #   → SEZ_Core_Secondary
        "10918",                         #   → SEZ_Department_Primery
        "10897",                         #   → SEZ_Department_Secondary
        "10970","10980","10968","10927", #   → SEZ servers
        "10961",                         #   → SEZ_NAS
    ],
    "10918": [                           # SEZ_Department_Primery
        "10970","10927",                 #   → SEZ-VDI01, Server-VMS-Sez
    ],
    "10897": [                           # SEZ_Department_Secondary
        "10968","10980",                 #   → SEZVDI2, SEZ-INTERNETVM
    ],

    # ── MSOUR ────────────────────────────────────────────────────────────────
    "10946": [                           # FGT-60F-MSour-Secondary_FW
        "10964",                         #   → Msour_core Primary
        "10942",                         #   → Msour_Fiber Primary
        "10895",                         #   → Msour_Fiber_Secondary
        "10971","10903","10911","10926", #   → MSOUR servers
        "10959",                         #   → Msour_NAS
    ],
    "10964": [                           # Msour_core Primary
        "10896",                         #   → Msour_core switch secondary
        "10924",                         #   → Msour standby Switch
        "10917",                         #   → Msour_Departmant Primary
        "10916",                         #   → Msour_CCTV
        "10971","10903","10911","10926", #   → MSOUR servers
        "10959",                         #   → Msour_NAS
    ],
    "10917": [                           # Msour_Departmant Primary
        "10971","10926",                 #   → MSOURVDI01, Server-VMS-Msour
    ],

    # ── MDEEP ────────────────────────────────────────────────────────────────
    "10956": [                           # FortiGate-60F-Mdeep_Primery
        "10952",                         #   → Mdeep_core_Primary1
        "10953",                         #   → Mdeep_Fiber Primary
        "10894",                         #   → Mdeep_Fiber-Secondary Switch
        "10990","10923","10969","10904", #   → MDEEP servers
        "10983","10960",                 #   → Pat_nas, Mdeep_NAS
    ],
    "10952": [                           # Mdeep_core_Primary1
        "10892",                         #   → Mdeep_Core Secondary switch
        "10954",                         #   → Mdeep_Department Primary
        "10893",                         #   → Mdeep_Department Secondary Switch
        "10919",                         #   → Dispatch Department
        "10990","10923","10969","10904", #   → MDEEP servers
        "10983","10960",                 #   → Pat_nas, Mdeep_NAS
    ],
    "10954": [                           # Mdeep_Department Primary
        "10893",                         #   → Mdeep_Department Secondary Switch
        "10969","10904",                 #   → MDEEPVDI01, MDEEPVDI2
    ],
    "10919": [                           # Dispatch Department switch
        "10990",                         #   → MDEEPINTERNET01
    ],
}

def get_unavail_trigger(hostid, triggers_by_host):
    """Return the best 'device unreachable' trigger for a host."""
    tlist = triggers_by_host.get(hostid, [])
    # Prefer ICMP ping unavailability
    for t in tlist:
        desc = t["description"].lower()
        if "unavailable by icmp" in desc:
            return t["triggerid"]
    # Fall back to Zabbix agent not available
    for t in tlist:
        desc = t["description"].lower()
        if "agent is not available" in desc and "active" not in desc:
            return t["triggerid"]
    # Fall back to any unavailability
    for t in tlist:
        desc = t["description"].lower()
        if "not available" in desc or "unreachable" in desc or "unavailable" in desc:
            return t["triggerid"]
    return None

def main():
    print("Connecting to Zabbix API...")

    # Collect all unique host IDs
    all_hosts = set()
    for parent, children in TOPOLOGY.items():
        all_hosts.add(parent)
        all_hosts.update(children)

    # Fetch unavailability triggers for all hosts
    triggers = api_call("trigger.get", {
        "output": ["triggerid", "description", "priority"],
        "hostids": list(all_hosts),
        "selectHosts": ["hostid"],
        "filter": {"status": 0},
        "search": {"description": "available"},
        "searchByAny": True,
        "startSearch": False,
    })

    # Also fetch ICMP ping triggers
    icmp_triggers = api_call("trigger.get", {
        "output": ["triggerid", "description"],
        "hostids": list(all_hosts),
        "selectHosts": ["hostid"],
        "filter": {"status": 0},
        "search": {"description": "Unavailable by ICMP ping"},
    })

    all_triggers = triggers + icmp_triggers

    # Group by hostid → list of triggers
    by_host = {}
    for t in all_triggers:
        for h in t["hosts"]:
            by_host.setdefault(h["hostid"], []).append(t)

    # ── Build dependency pairs ───────────────────────────────────────────────
    dep_pairs = []      # [(child_triggerid, parent_triggerid)]
    skipped_hosts = []

    for parent_hid, child_hids in TOPOLOGY.items():
        parent_tid = get_unavail_trigger(parent_hid, by_host)
        if not parent_tid:
            skipped_hosts.append(f"No trigger found for parent hostid={parent_hid}")
            continue

        for child_hid in child_hids:
            child_tid = get_unavail_trigger(child_hid, by_host)
            if not child_tid:
                skipped_hosts.append(f"  No trigger for child hostid={child_hid}")
                continue
            if child_tid == parent_tid:
                continue
            dep_pairs.append((child_tid, parent_tid))

    # Deduplicate
    dep_pairs = list(set(dep_pairs))
    print(f"Dependency pairs to create: {len(dep_pairs)}")

    # ── Fetch host names for reporting ──────────────────────────────────────
    hosts_info = api_call("host.get", {
        "output": ["hostid", "name"],
        "hostids": list(all_hosts)
    })
    hname = {h["hostid"]: h["name"] for h in hosts_info}
    tid_to_hid = {}
    for hid, tlist in by_host.items():
        for t in tlist:
            tid_to_hid[t["triggerid"]] = hid

    # ── Apply dependencies ───────────────────────────────────────────────────
    added = 0
    skipped_dup = 0

    # Fetch all existing dependencies for child triggers
    child_tids = list({p[0] for p in dep_pairs})
    existing_triggers = api_call("trigger.get", {
        "output": ["triggerid"],
        "triggerids": child_tids,
        "selectDependencies": ["triggerid"],
    })
    # child_tid → set of currently depended-on trigger IDs
    current_deps = {t["triggerid"]: {d["triggerid"] for d in t.get("dependencies", [])}
                    for t in existing_triggers}

    # Group new deps by child so we can do one update per child
    from collections import defaultdict
    new_deps_by_child = defaultdict(set)
    for child_tid, parent_tid in dep_pairs:
        new_deps_by_child[child_tid].add(parent_tid)

    for child_tid, parent_tids in sorted(new_deps_by_child.items()):
        child_hid = tid_to_hid.get(child_tid, "?")
        child_name = hname.get(child_hid, child_hid)
        existing = current_deps.get(child_tid, set())
        truly_new = parent_tids - existing

        if not truly_new:
            print(f"  SKIP (all exist): {child_name}")
            skipped_dup += 1
            continue

        # Merge existing + new into one update call
        merged = existing | truly_new
        dep_list = [{"triggerid": tid} for tid in merged]
        api_call("trigger.update", {"triggerid": child_tid, "dependencies": dep_list})

        for parent_tid in sorted(truly_new):
            parent_hid = tid_to_hid.get(parent_tid, "?")
            parent_name = hname.get(parent_hid, parent_hid)
            print(f"  SET: {child_name:<45} depends on  {parent_name}")
        added += len(truly_new)

    print(f"\nTrigger dependencies added: {added}")
    print(f"Already existed (skipped): {skipped_dup}")

    if skipped_hosts:
        print("\nHosts without unavailability triggers (no dependency set):")
        for s in skipped_hosts:
            print(f"  {s}")

    print("\nTopology summary:")
    for parent_hid, child_hids in TOPOLOGY.items():
        print(f"  {hname.get(parent_hid, parent_hid)}")
        for c in child_hids:
            tid = get_unavail_trigger(c, by_host)
            status = "OK" if tid else "NO TRIGGER"
            print(f"    └─ [{status}] {hname.get(c, c)}")

if __name__ == "__main__":
    main()
