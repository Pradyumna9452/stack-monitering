#!/usr/bin/env python3
"""
Create hierarchical (parent/child) host group structure in Zabbix.
Groups are created with "/" separator: Site/DeviceType
Each host is assigned to its site+type group based on IP and name analysis.
Existing flat groups are kept for backward compatibility.
"""
import json
import urllib.request
import ssl
import sys

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
    headers = {'Content-Type': 'application/json-rpc', 'Authorization': f'Bearer {ZABBIX_TOKEN}'}
    req = urllib.request.Request(ZABBIX_URL, data=json.dumps(payload).encode(), headers=headers)
    resp = urllib.request.urlopen(req, context=ctx)
    result = json.loads(resp.read().decode())
    if "error" in result:
        raise Exception(f"API Error [{method}]: {result['error']}")
    return result["result"]

# ── Site/type assignments per host ID ────────────────────────────────────────
# Determined by IP prefix and device name
# Format: hostid → (site, device_type)
HOST_ASSIGNMENTS = {
    # HO (Head Office) – 10.94.x.x
    "10965": ("HO", "Servers"),   # HOVDI01
    "10966": ("HO", "Servers"),   # HOVDI02
    "10967": ("HO", "Servers"),   # DRHOVDI
    "10891": ("HO", "Servers"),   # TESTVDI Windows Server
    "10973": ("HO", "Servers"),   # SOPHOSVM
    "10909": ("HO", "Servers"),   # HOVMHOST
    "10972": ("HO", "Servers"),   # VMT-2024
    "10899": ("HO", "Servers"),   # HO-VMS Windows Server
    "10888": ("HO", "Storage"),   # HONAS
    "11000": ("HO", "Storage"),   # SONIC-SAN
    "10947": ("HO", "Firewall"),  # HO_SOPHOS_INTERNET_PROXY_FW1
    "10955": ("HO", "Firewall"),  # HO_Primary_Firewall
    "10984": ("HO", "Switches"),  # Core HO VDI Switch Primary
    "10939": ("HO", "Switches"),  # Core HO VDI Switch Secondary
    "10889": ("HO", "Switches"),  # HO_WiFi Uplink
    "10929": ("HO", "Switches"),  # Dept Switch 01
    "10930": ("HO", "Switches"),  # Dept Switch 02
    "10931": ("HO", "Switches"),  # Dept Switch 03
    "10932": ("HO", "Switches"),  # Dept Switch 04
    "10933": ("HO", "Switches"),  # Dept Switch 05
    "10934": ("HO", "Switches"),  # Dept Switch 06
    "10935": ("HO", "Switches"),  # Dept Switch 07
    "10936": ("HO", "Switches"),  # Dept Switch 08
    "10937": ("HO", "Switches"),  # Dept Switch 09 standby
    "10938": ("HO", "Switches"),  # HO_WiFi Switch 10 standby
    "10948": ("HO", "Switches"),  # Dept Core Switch Primary
    "10928": ("HO", "Switches"),  # Dept Core Switch Secondary

    # SONIC (main site) – 10.95.x.x
    "10976": ("SONIC", "Servers"),  # SONICAD
    "10908": ("SONIC", "Servers"),  # DRVDI
    "10901": ("SONIC", "Servers"),  # AIHOSTSERVER
    "10921": ("SONIC", "Servers"),  # SAP-DEVHOST1
    "10910": ("SONIC", "Servers"),  # DEVSAPWINHOST
    "10978": ("SONIC", "Servers"),  # COPA
    "10979": ("SONIC", "Servers"),  # COPA-PRD
    "10922": ("SONIC", "Servers"),  # ARCBKP2
    "10912": ("SONIC", "Servers"),  # Mailvault
    "10902": ("SONIC", "Servers"),  # HPHOST Windows Server
    "10900": ("SONIC", "Servers"),  # ECMHOST Windows Server
    "10920": ("SONIC", "Servers"),  # SQLDB (Hyper-V Host Server 02)
    "11004": ("SONIC", "Servers"),  # SOCVM
    "10974": ("SONIC", "Servers"),  # RDG1
    "10975": ("SONIC", "Servers"),  # RGVPN2
    "10977": ("SONIC", "Servers"),  # RDG-POWERBI-DEV
    "10981": ("SONIC", "Servers"),  # SBELHDBDQ
    "10982": ("SONIC", "Servers"),  # SBELHDBP
    "10985": ("SONIC", "Servers"),  # SBELHDBDNQ
    "10986": ("SONIC", "Servers"),  # SBELHBDNQ
    "10987": ("SONIC", "Servers"),  # sbels4dapp
    "10988": ("SONIC", "Servers"),  # sbels4qapp
    "10989": ("SONIC", "Servers"),  # sbels4apps
    "10887": ("SONIC", "Servers"),  # DR-InternetVM
    "11001": ("SONIC", "Storage"),  # SONICBIOCHEM_MSA1
    "11002": ("SONIC", "Storage"),  # SONICBIOCHEM_MSA2
    "10949": ("SONIC", "Switches"), # Core development Switch Primary
    "10940": ("SONIC", "Switches"), # Core devlopment Switch Secondary
    "10950": ("SONIC", "Switches"), # San Switch primary
    "10941": ("SONIC", "Switches"), # San Switch secondary

    # SEZ (Pithampur SEZ) – 10.96.x.x
    "10970": ("SEZ", "Servers"),   # SEZ-VDI01
    "10980": ("SEZ", "Servers"),   # SEZ-INTERNETVM
    "10968": ("SEZ", "Servers"),   # SEZVDI2
    "10927": ("SEZ", "Servers"),   # Server-VMS-Sez
    "10961": ("SEZ", "Storage"),   # SEZ_NAS
    "10945": ("SEZ", "Firewall"),  # SEZ_Pithampur_Primary_FW
    "10951": ("SEZ", "Switches"),  # SEZ_Core_Primery1
    "10898": ("SEZ", "Switches"),  # SEZ_Core_Secondary
    "10918": ("SEZ", "Switches"),  # SEZ_Department_Primery
    "10897": ("SEZ", "Switches"),  # SEZ_Department_Secondary

    # MSOUR – 10.97.x.x
    "10971": ("MSOUR", "Servers"),  # MSOURVDI01
    "10903": ("MSOUR", "Servers"),  # MSOURSTANDBY Windows Server
    "10911": ("MSOUR", "Servers"),  # MSOURINTERNET01
    "10926": ("MSOUR", "Servers"),  # Server-VMS-Msour
    "10959": ("MSOUR", "Storage"),  # Msour_NAS
    "10946": ("MSOUR", "Firewall"), # FGT-60F-MSour-Secondary_FW
    "10916": ("MSOUR", "Switches"), # Msour_CCTV
    "10895": ("MSOUR", "Switches"), # Msour_Fiber_Secondary
    "10917": ("MSOUR", "Switches"), # Msour_Departmant Primary
    "10964": ("MSOUR", "Switches"), # Msour_core Primary
    "10942": ("MSOUR", "Switches"), # Msour_Fiber Primary
    "10924": ("MSOUR", "Switches"), # Msour standby Switch
    "10896": ("MSOUR", "Switches"), # Msour_core switch secondary

    # MDEEP – 10.98.x.x
    "10990": ("MDEEP", "Servers"),  # MDEEPINTERNET01
    "10892": ("MDEEP", "Switches"), # Mdeep_Core Secondary switch (miscategorised as Server)
    "10923": ("MDEEP", "Servers"),  # LPRVMSMDEEP
    "10969": ("MDEEP", "Servers"),  # MDEEPVDI01
    "10904": ("MDEEP", "Servers"),  # MDEEPVDI2 Windows Server
    "10983": ("MDEEP", "Storage"),  # Pat_nas
    "10960": ("MDEEP", "Storage"),  # Mdeep_NAS
    "10956": ("MDEEP", "Firewall"), # FortiGate-60F-Mdeep_Primery
    "10893": ("MDEEP", "Switches"), # Mdeep_Department Secondary Switch
    "10894": ("MDEEP", "Switches"), # Mdeep_Fiber-Secondary Switch
    "10952": ("MDEEP", "Switches"), # Mdeep_core_Primary1
    "10953": ("MDEEP", "Switches"), # Mdeep_Fiber Primary
    "10919": ("MDEEP", "Switches"), # Dispatch Department
    "10954": ("MDEEP", "Switches"), # Mdeep_Department Primary
}

SITES = ["HO", "SONIC", "SEZ", "MSOUR", "MDEEP"]
TYPES = ["Servers", "Switches", "Firewall", "Storage"]

def main():
    print("Connecting to Zabbix API (token auth)...")

    # ── 1. Fetch existing groups ─────────────────────────────────────────────
    existing_groups = api_call("hostgroup.get", {"output": ["groupid", "name"]})
    group_by_name = {g["name"]: g["groupid"] for g in existing_groups}
    print(f"Found {len(existing_groups)} existing host groups.")

    # ── 2. Create missing hierarchical groups ────────────────────────────────
    groups_to_create = []
    for site in SITES:
        groups_to_create.append(site)                    # parent: e.g. "HO"
        for dtype in TYPES:
            groups_to_create.append(f"{site}/{dtype}")   # child:  e.g. "HO/Servers"

    created = 0
    for gname in groups_to_create:
        if gname not in group_by_name:
            result = api_call("hostgroup.create", {"name": gname})
            new_id = result["groupids"][0]
            group_by_name[gname] = new_id
            print(f"  Created group: {gname} (id={new_id})")
            created += 1
        else:
            print(f"  Already exists: {gname} (id={group_by_name[gname]})")

    print(f"\nCreated {created} new groups.\n")

    # ── 3. Assign each host to its site+type group ───────────────────────────
    hosts = api_call("host.get", {
        "output": ["hostid", "host", "name"],
        "selectHostGroups": ["groupid", "name"]
    })
    host_by_id = {h["hostid"]: h for h in hosts}

    updated = 0
    skipped = 0
    for hostid, (site, dtype) in HOST_ASSIGNMENTS.items():
        target_group_name = f"{site}/{dtype}"
        target_gid = group_by_name.get(target_group_name)
        if not target_gid:
            print(f"  WARN: group {target_group_name} not found, skipping host {hostid}")
            continue

        host = host_by_id.get(hostid)
        if not host:
            print(f"  WARN: host {hostid} not found in Zabbix")
            continue

        current_gids = {g["groupid"] for g in host["hostgroups"]}
        if target_gid in current_gids:
            skipped += 1
            continue

        # Add the new hierarchical group while keeping existing groups
        new_groups = [{"groupid": gid} for gid in current_gids]
        new_groups.append({"groupid": target_gid})

        api_call("host.update", {"hostid": hostid, "groups": new_groups})
        print(f"  Assigned [{hostid}] {host['name']}  →  {target_group_name}")
        updated += 1

    print(f"\nDone. Hosts updated: {updated}, already assigned: {skipped}.")
    print("\nHierarchical group structure:")
    for site in SITES:
        print(f"  {site}/")
        for dtype in TYPES:
            gname = f"{site}/{dtype}"
            gid = group_by_name.get(gname, "?")
            count = sum(1 for hid, (s, d) in HOST_ASSIGNMENTS.items() if s == site and d == dtype)
            print(f"    └─ {gname}  ({count} devices)")

if __name__ == "__main__":
    main()
