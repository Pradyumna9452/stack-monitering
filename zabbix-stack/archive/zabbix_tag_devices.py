#!/usr/bin/env python3
"""
Apply site / type / role tags to every Zabbix host.
Tags:
  site  – HO | SONIC | SEZ | MSOUR | MDEEP
  type  – Server | Switch | Firewall | Storage
  role  – granular role (VDI, Hypervisor, App-Server, Core-Switch, NAS, etc.)
"""
import json, urllib.request, ssl, sys

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


# ── Tag map: hostid → {site, type, role} ─────────────────────────────────────
TAG_MAP = {
    # ── HO – Head Office (10.94.x.x) ────────────────────────────────────────
    "10965": {"site": "HO",    "type": "Server",   "role": "VDI"},
    "10966": {"site": "HO",    "type": "Server",   "role": "VDI"},
    "10967": {"site": "HO",    "type": "Server",   "role": "VDI"},           # DR VDI
    "10891": {"site": "HO",    "type": "Server",   "role": "VDI"},           # Test VDI
    "10973": {"site": "HO",    "type": "Server",   "role": "Security"},      # Sophos VM
    "10909": {"site": "HO",    "type": "Server",   "role": "Hypervisor"},
    "10972": {"site": "HO",    "type": "Server",   "role": "Hypervisor"},
    "10899": {"site": "HO",    "type": "Server",   "role": "VMS"},
    "10888": {"site": "HO",    "type": "Storage",  "role": "NAS"},
    "11000": {"site": "HO",    "type": "Storage",  "role": "SAN"},
    "10947": {"site": "HO",    "type": "Firewall",  "role": "Internet-Proxy"},
    "10955": {"site": "HO",    "type": "Firewall",  "role": "Primary-FW"},
    "10984": {"site": "HO",    "type": "Switch",   "role": "Core-Switch"},
    "10939": {"site": "HO",    "type": "Switch",   "role": "Core-Switch"},
    "10889": {"site": "HO",    "type": "Switch",   "role": "WiFi-Switch"},
    "10929": {"site": "HO",    "type": "Switch",   "role": "Dept-Switch"},
    "10930": {"site": "HO",    "type": "Switch",   "role": "Dept-Switch"},
    "10931": {"site": "HO",    "type": "Switch",   "role": "Dept-Switch"},
    "10932": {"site": "HO",    "type": "Switch",   "role": "Dept-Switch"},
    "10933": {"site": "HO",    "type": "Switch",   "role": "Dept-Switch"},
    "10934": {"site": "HO",    "type": "Switch",   "role": "Dept-Switch"},
    "10935": {"site": "HO",    "type": "Switch",   "role": "Dept-Switch"},
    "10936": {"site": "HO",    "type": "Switch",   "role": "Dept-Switch"},
    "10937": {"site": "HO",    "type": "Switch",   "role": "Dept-Switch"},
    "10938": {"site": "HO",    "type": "Switch",   "role": "WiFi-Switch"},
    "10948": {"site": "HO",    "type": "Switch",   "role": "Core-Switch"},
    "10928": {"site": "HO",    "type": "Switch",   "role": "Core-Switch"},

    # ── SONIC – Main site / data centre (10.95.x.x) ─────────────────────────
    "10976": {"site": "SONIC", "type": "Server",   "role": "AD-DNS"},        # SONICAD
    "10908": {"site": "SONIC", "type": "Server",   "role": "VDI"},           # DRVDI
    "10901": {"site": "SONIC", "type": "Server",   "role": "Hypervisor"},    # AIHOSTSERVER
    "10921": {"site": "SONIC", "type": "Server",   "role": "Hypervisor"},    # SAP-DEVHOST1
    "10910": {"site": "SONIC", "type": "Server",   "role": "Hypervisor"},    # DEVSAPWINHOST
    "10978": {"site": "SONIC", "type": "Server",   "role": "App-Server"},    # COPA
    "10979": {"site": "SONIC", "type": "Server",   "role": "App-Server"},    # COPA-PRD
    "10922": {"site": "SONIC", "type": "Server",   "role": "Backup"},        # ARCBKP2
    "10912": {"site": "SONIC", "type": "Server",   "role": "Mail"},          # Mailvault
    "10902": {"site": "SONIC", "type": "Server",   "role": "Hypervisor"},    # HPHOST
    "10900": {"site": "SONIC", "type": "Server",   "role": "App-Server"},    # ECMHOST
    "10920": {"site": "SONIC", "type": "Server",   "role": "DB-Server"},     # SQLDB Hyper-V
    "11004": {"site": "SONIC", "type": "Server",   "role": "Security"},      # SOCVM
    "10974": {"site": "SONIC", "type": "Server",   "role": "RDS"},           # RDG1
    "10975": {"site": "SONIC", "type": "Server",   "role": "VPN"},           # RGVPN2
    "10977": {"site": "SONIC", "type": "Server",   "role": "RDS"},           # RDG-POWERBI-DEV
    "10981": {"site": "SONIC", "type": "Server",   "role": "App-Server"},    # SBELHDBDQ
    "10982": {"site": "SONIC", "type": "Server",   "role": "App-Server"},    # SBELHDBP
    "10985": {"site": "SONIC", "type": "Server",   "role": "App-Server"},    # SBELHDBDNQ
    "10986": {"site": "SONIC", "type": "Server",   "role": "App-Server"},    # SBELHBDNQ
    "10987": {"site": "SONIC", "type": "Server",   "role": "App-Server"},    # sbels4dapp
    "10988": {"site": "SONIC", "type": "Server",   "role": "App-Server"},    # sbels4qapp
    "10989": {"site": "SONIC", "type": "Server",   "role": "App-Server"},    # sbels4apps
    "10887": {"site": "SONIC", "type": "Server",   "role": "Internet-VM"},   # DR-InternetVM
    "11001": {"site": "SONIC", "type": "Storage",  "role": "SAN"},           # SONICBIOCHEM_MSA1
    "11002": {"site": "SONIC", "type": "Storage",  "role": "SAN"},           # SONICBIOCHEM_MSA2
    "10949": {"site": "SONIC", "type": "Switch",   "role": "Core-Switch"},
    "10940": {"site": "SONIC", "type": "Switch",   "role": "Core-Switch"},
    "10950": {"site": "SONIC", "type": "Switch",   "role": "SAN-Switch"},
    "10941": {"site": "SONIC", "type": "Switch",   "role": "SAN-Switch"},

    # ── SEZ – Pithampur SEZ (10.96.x.x) ──────────────────────────────────────
    "10970": {"site": "SEZ",   "type": "Server",   "role": "VDI"},
    "10980": {"site": "SEZ",   "type": "Server",   "role": "Internet-VM"},
    "10968": {"site": "SEZ",   "type": "Server",   "role": "VDI"},
    "10927": {"site": "SEZ",   "type": "Server",   "role": "VMS"},
    "10961": {"site": "SEZ",   "type": "Storage",  "role": "NAS"},
    "10945": {"site": "SEZ",   "type": "Firewall",  "role": "Primary-FW"},
    "10951": {"site": "SEZ",   "type": "Switch",   "role": "Core-Switch"},
    "10898": {"site": "SEZ",   "type": "Switch",   "role": "Core-Switch"},
    "10918": {"site": "SEZ",   "type": "Switch",   "role": "Dept-Switch"},
    "10897": {"site": "SEZ",   "type": "Switch",   "role": "Dept-Switch"},

    # ── MSOUR (10.97.x.x) ────────────────────────────────────────────────────
    "10971": {"site": "MSOUR", "type": "Server",   "role": "VDI"},
    "10903": {"site": "MSOUR", "type": "Server",   "role": "Standby-Server"},
    "10911": {"site": "MSOUR", "type": "Server",   "role": "Internet-VM"},
    "10926": {"site": "MSOUR", "type": "Server",   "role": "VMS"},
    "10959": {"site": "MSOUR", "type": "Storage",  "role": "NAS"},
    "10946": {"site": "MSOUR", "type": "Firewall",  "role": "Secondary-FW"},
    "10916": {"site": "MSOUR", "type": "Switch",   "role": "CCTV-Switch"},
    "10895": {"site": "MSOUR", "type": "Switch",   "role": "Fiber-Switch"},
    "10917": {"site": "MSOUR", "type": "Switch",   "role": "Dept-Switch"},
    "10964": {"site": "MSOUR", "type": "Switch",   "role": "Core-Switch"},
    "10942": {"site": "MSOUR", "type": "Switch",   "role": "Fiber-Switch"},
    "10924": {"site": "MSOUR", "type": "Switch",   "role": "Core-Switch"},   # standby
    "10896": {"site": "MSOUR", "type": "Switch",   "role": "Core-Switch"},

    # ── MDEEP (10.98.x.x) ────────────────────────────────────────────────────
    "10990": {"site": "MDEEP", "type": "Server",   "role": "Internet-VM"},
    "10892": {"site": "MDEEP", "type": "Switch",   "role": "Core-Switch"},
    "10923": {"site": "MDEEP", "type": "Server",   "role": "Hypervisor"},    # LPRVMSMDEEP
    "10969": {"site": "MDEEP", "type": "Server",   "role": "VDI"},
    "10904": {"site": "MDEEP", "type": "Server",   "role": "VDI"},
    "10983": {"site": "MDEEP", "type": "Storage",  "role": "NAS"},           # Pat_nas
    "10960": {"site": "MDEEP", "type": "Storage",  "role": "NAS"},
    "10956": {"site": "MDEEP", "type": "Firewall",  "role": "Primary-FW"},
    "10893": {"site": "MDEEP", "type": "Switch",   "role": "Dept-Switch"},
    "10894": {"site": "MDEEP", "type": "Switch",   "role": "Fiber-Switch"},
    "10952": {"site": "MDEEP", "type": "Switch",   "role": "Core-Switch"},
    "10953": {"site": "MDEEP", "type": "Switch",   "role": "Fiber-Switch"},
    "10919": {"site": "MDEEP", "type": "Switch",   "role": "Dept-Switch"},
    "10954": {"site": "MDEEP", "type": "Switch",   "role": "Dept-Switch"},

    # ── Zabbix server ────────────────────────────────────────────────────────
    "10084": {"site": "HO",    "type": "Server",   "role": "Monitoring"},
}

def main():
    print("Connecting to Zabbix API...")

    hosts = api_call("host.get", {
        "output": ["hostid", "name"],
        "selectTags": "extend"
    })
    host_by_id = {h["hostid"]: h for h in hosts}

    updated = 0
    not_found = []

    for hostid, t in TAG_MAP.items():
        host = host_by_id.get(hostid)
        if not host:
            not_found.append(hostid)
            continue

        new_tags = [
            {"tag": "site", "value": t["site"]},
            {"tag": "type", "value": t["type"]},
            {"tag": "role", "value": t["role"]},
        ]

        # Preserve any existing tags that are NOT site/type/role
        preserved = [
            tg for tg in host.get("tags", [])
            if tg["tag"] not in ("site", "type", "role")
        ]
        final_tags = preserved + new_tags

        api_call("host.update", {"hostid": hostid, "tags": final_tags})
        print(f"  [{hostid}] {host['name']:<45} site={t['site']:<6} type={t['type']:<9} role={t['role']}")
        updated += 1

    print(f"\nTagged {updated} hosts.")
    if not_found:
        print(f"Host IDs not found in Zabbix: {not_found}")

    # ── Summary by role ──────────────────────────────────────────────────────
    from collections import Counter
    role_counts = Counter(v["role"] for v in TAG_MAP.values())
    type_counts = Counter(v["type"] for v in TAG_MAP.values())
    site_counts = Counter(v["site"] for v in TAG_MAP.values())

    print("\nBy site :", dict(sorted(site_counts.items())))
    print("By type :", dict(sorted(type_counts.items())))
    print("By role :", dict(sorted(role_counts.items())))

if __name__ == "__main__":
    main()
