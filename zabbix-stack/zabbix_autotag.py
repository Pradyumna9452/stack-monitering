#!/usr/bin/env python3
"""
Auto-assign site / type / role tags to Zabbix hosts that are MISSING them.

Design (see also legacy zabbix_tag_devices.py, which used a hardcoded hostid map):
  * Existing Zabbix tags are AUTHORITATIVE. A host that already has all three of
    site/type/role is left untouched — this preserves the hand-curated tags.
  * A host missing any of the three gets the missing ones DERIVED:
      - site  ← IP /16 prefix        (10.94=HO 10.95=SONIC 10.96=SEZ 10.97=MSOUR 10.98=MDEEP)
      - type  ← attached template     (agent=Server, FortiGate=Firewall, MSA/ReadyNAS/Fastpath=Storage,
                                       D-Link/Cisco=Switch, web-scenario host=Web)
      - role  ← host-name heuristics  (VMHOST=Hypervisor, ADC=AD-DNS, *BKP=Backup, ... else Unknown)
  * Non site/type/role tags are always preserved.
  * Idempotent: after a host is fully tagged it is skipped on later runs, so this is
    safe to run on a schedule (systemd timer) to auto-tag newly added hosts.

Run:  python3 zabbix_autotag.py [--dry-run] [--verbose] [--retag-unknown]
"""
import argparse
import json
import os
import pathlib
import ssl
import sys
import urllib.request

ZABBIX_URL = "https://localhost/zabbix/api_jsonrpc.php"

# ── site: first two octets of the main-interface IP ──────────────────────────
SITE_BY_PREFIX = {
    "10.94": "HO", "10.95": "SONIC", "10.96": "SEZ",
    "10.97": "MSOUR", "10.98": "MDEEP",
}

# ── type: keyword-in-template-name → device type (checked in this order) ─────
TYPE_RULES = [
    ("Firewall", ("fortigate", "firewall", "palo alto", "sophos xg")),
    ("Storage",  ("readynas", "fastpath", "msa", "storage", "netgear", "synology")),
    ("Switch",   ("switch", "d-link", "dgs", "des", "dxs", "cisco", "catalyst", "ios", "juniper")),
    ("Server",   ("windows", "linux", "iis", "zabbix server", "zabbix agent", "vmware")),
]

# ── role: keyword-in-hostname → role (checked in this order) ─────────────────
ROLE_RULES = [
    ("Hypervisor", ("vmhost", "hyperv", "hyper-v", "esxi", "esx", "vhost")),
    ("AD-DNS",     ("adc", "ad-dns", "addns", "domaincontroller")),
    ("Backup",     ("bkp", "backup", "veeam", "arcserve")),
    ("DB-Server",  ("sqldb", "-sql", "sqlserver", "dbserver", "-db")),
    ("Mail",       ("mail", "exchange", "smtp")),
    ("VPN",        ("vpn",)),
    ("RDS",        ("rdg", "rds", "rdsh", "remoteapp")),
    ("SAN",        ("-san", "msa")),
    ("NAS",        ("-nas", "nas0", "readynas")),
]


def _load_token() -> str:
    """Token precedence: env var → /etc/zabbix-stack/stack.env → script-dir .env."""
    tok = os.environ.get("ZABBIX_API_TOKEN", "")
    if tok:
        return tok
    for p in ("/etc/zabbix-stack/stack.env",
              str(pathlib.Path(__file__).resolve().parent / ".env")):
        try:
            for line in pathlib.Path(p).read_text().splitlines():
                if line.startswith("ZABBIX_API_TOKEN="):
                    v = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if v:
                        return v
        except (FileNotFoundError, OSError):
            continue
    return ""


_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE
_TOKEN = _load_token()
if not _TOKEN:
    raise SystemExit("ZABBIX_API_TOKEN not found (env or /etc/zabbix-stack/stack.env)")


def api(method: str, params) -> object:
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    req = urllib.request.Request(
        ZABBIX_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json-rpc",
                 "Authorization": f"Bearer {_TOKEN}"})
    with urllib.request.urlopen(req, context=_CTX, timeout=30) as r:
        res = json.loads(r.read().decode())
    if "error" in res:
        raise RuntimeError(f"{method}: {res['error']}")
    return res["result"]


def main_ip(host) -> str:
    for i in host.get("interfaces", []):
        if i.get("main") == "1" and i.get("ip"):
            return i["ip"]
    for i in host.get("interfaces", []):
        if i.get("ip"):
            return i["ip"]
    return ""


def is_web(host, ip: str) -> bool:
    name = (host.get("name") or host.get("host") or "").lower()
    if name.startswith(("website", "http://", "https://")):
        return True
    # web-scenario monitor: no IP and no attached device template
    return not ip and not host.get("parentTemplates")


def derive_type(host, ip: str) -> str:
    if is_web(host, ip):
        return "Web"
    tpls = " ".join(t.get("name", "") for t in host.get("parentTemplates", [])).lower()
    for typ, keys in TYPE_RULES:
        if any(k in tpls for k in keys):
            return typ
    return ""  # unknown -> leave type unset rather than guess wrong


def derive_site(ip: str, typ: str) -> str:
    site = SITE_BY_PREFIX.get(".".join(ip.split(".")[:2])) if ip else ""
    if not site and typ == "Web":
        return "HO"  # web-scenario monitors are HO-hosted (per operator decision)
    return site or ""


def derive_role(host, typ: str) -> str:
    # web-scenario monitors are role=Web by operator decision, regardless of name
    # (e.g. a ".../webmail" URL check is a Web role, not a Mail server).
    if typ == "Web":
        return "Web"
    name = (host.get("name") or host.get("host") or "").lower()
    for role, keys in ROLE_RULES:
        if any(k in name for k in keys):
            return role
    return "Unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="preview, do not write")
    ap.add_argument("--verbose", action="store_true", help="list skipped hosts too")
    ap.add_argument("--retag-unknown", action="store_true",
                    help="also re-derive hosts whose role is 'Unknown'")
    args = ap.parse_args()

    hosts = api("host.get", {
        "output": ["hostid", "host", "name", "status", "flags"],
        "selectTags": "extend",
        "selectInterfaces": ["ip", "main", "type"],
        "selectParentTemplates": ["name"],
        "filter": {"status": 0, "flags": 0},
    })

    changed = skipped = 0
    for h in sorted(hosts, key=lambda x: x.get("name", "")):
        cur = {t["tag"]: t.get("value", "") for t in h.get("tags", [])}
        have = {k: cur.get(k, "") for k in ("site", "type", "role")}
        need_role = args.retag_unknown and have["role"] == "Unknown"
        if all(have.values()) and not need_role:
            skipped += 1
            if args.verbose:
                print(f"  skip  {h['name'][:45]:<45} "
                      f"site={have['site']} type={have['type']} role={have['role']}")
            continue

        ip = main_ip(h)
        typ = have["type"] or derive_type(h, ip)
        site = have["site"] or derive_site(ip, typ)
        role = (derive_role(h, typ) if need_role else have["role"]) or derive_role(h, typ)

        # rebuild tag list: preserve non-managed tags, set the three managed ones
        new_tags = [t for t in h.get("tags", [])
                    if t["tag"] not in ("site", "type", "role")]
        for k, v in (("site", site), ("type", typ), ("role", role)):
            if v:
                new_tags.append({"tag": k, "value": v})

        added = {k: v for k, v in (("site", site), ("type", typ), ("role", role))
                 if v and v != have[k]}
        if not added:
            skipped += 1
            continue

        flag = " [DRY]" if args.dry_run else ""
        print(f"  tag   {h['name'][:45]:<45} ip={ip or '-':<12} "
              f"=> {added}{flag}")
        if not args.dry_run:
            api("host.update", {"hostid": h["hostid"], "tags": new_tags})
        changed += 1

    print(f"\n{'Would tag' if args.dry_run else 'Tagged'} {changed} host(s); "
          f"skipped {skipped} already-tagged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
