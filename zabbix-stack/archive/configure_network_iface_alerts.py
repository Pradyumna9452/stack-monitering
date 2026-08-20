#!/usr/bin/env python3
"""
Configure per-interface ERROR% and PACKET-DROP% alerts (Warning >=1%, Critical
>=5%) on network-device (switch) templates in Zabbix.

The switch templates already collect per-interface errors/sec and discards/sec but
NO packet counts, so a true percentage has no denominator. This script, per
in-scope template:
  1. adds 2 packet-rate item prototypes (direct SNMP get of the 32-bit ifTable
     ifInUcastPkts/ifOutUcastPkts, change-per-second) to the 'Network interfaces
     discovery' LLD -- the 64-bit ifHC*UcastPkts counters are unimplemented (static
     0) on D-Link even where HC octet counters work;
  2. adds 4 trigger prototypes computing  100*err/(err+pkts)  for in OR out, two
     tiers (>=1% Warning, >=5% Critical), each guarded by avg(pkts,5m) >=
     {$IF.ERR.MIN.PPS} so idle ports don't false-alarm (also avoids /0);
  3. sets the Warning prototype to depend on its Critical counterpart;
  4. disables the stock absolute 'High error rate' trigger prototype(s);
  5. adds macro {$IF.ERR.MIN.PPS}=10.

Severities: Warning=2 (email only), Critical=4/High (email + GLPI ticket, >=Average).
Routing via existing actions (L1). Idempotent + reversible.

Usage: python3 configure_network_iface_alerts.py --dry-run | --apply | --rollback
"""
import json, os, ssl, sys, urllib.request

ZABBIX_URL = "https://localhost/zabbix/api_jsonrpc.php"
TEMPLATES = [
    "D-Link DES_DGS Switch by SNMP",
    "D-Link DGS_DXS Switch by SNMP",
    "Template Net D-Link DGS-1210 SNMP",
    "Cisco IOS by SNMP",
    "Cisco Catalyst 3750V2-24FS by SNMP",
    "Network Generic Device by SNMP",
]
LLD_NAME = "Network interfaces discovery"
SEV_WARNING, SEV_HIGH = 2, 4
MINPPS_MACRO, MINPPS_VALUE = "{$IF.ERR.MIN.PPS}", "10"
WARN_PCT, CRIT_PCT = "1", "5"

HC = "1.3.6.1.2.1.31.1.1.1."   # ifHCInOctets=.6  ifHCOutOctets=.10
NH = "1.3.6.1.2.1.2.2.1."      # ifInOctets=.10   ifOutOctets=.16
# Map an octets column -> the 32-bit ifTable unicast-packets OID. The 64-bit HC
# packet counters (ifHC*UcastPkts) are unimplemented on D-Link (return a static
# 0 even though HC octet counters work), so we always use the 32-bit ifTable
# counters ifInUcastPkts=.11 / ifOutUcastPkts=.17. A 32-bit packet counter
# cannot wrap within a 3-min poll even at line rate, and errors come from the
# same ifTable, so the err/pkts ratio stays consistent.
UCAST = {
    HC: {"6": NH + "11", "10": NH + "17"},
    NH: {"10": NH + "11", "16": NH + "17"},
}

STOCK_ERR_SUFFIXES = ("High error rate", "High input error rate", "High output error rate")

ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE


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


def octets_oid(item):
    """Extract the base SNMP OID (with .{#SNMPINDEX}) from an octets item proto,
    whether it's a direct get[...] or a walk 'SNMP value' (preproc type 28)."""
    raw = item.get("snmp_oid", "") or ""
    if raw.startswith("get["):
        return raw[4:-1]
    if raw:
        return raw
    for p in item.get("preprocessing", []):
        if p["type"] == "28":                      # SNMP walk value -> OID is first param line
            return p["params"].splitlines()[0].strip()
    return ""


def ucast_get_oid(oct_oid):
    """Map an octets OID to the matching unicast-packets OID, wrapped as get[...]."""
    if not oct_oid or not oct_oid.endswith(".{#SNMPINDEX}"):
        return None
    base = oct_oid[:-len(".{#SNMPINDEX}")]
    for tbl, cols in UCAST.items():
        if tbl in base:
            col = base.split(tbl, 1)[1]
            if col in cols:
                return f"get[{cols[col]}.{{#SNMPINDEX}}]"
    return None


def pkts_key(octets_key, direction):
    """Build a unique pkts item key analogous to the octets key style."""
    inner = octets_key[octets_key.index("[") + 1:-1] if "[" in octets_key else "{#SNMPINDEX}"
    repl = {"ifHCInOctets": "ifInUcastPkts", "ifHCOutOctets": "ifOutUcastPkts",
            "ifInOctets": "ifInUcastPkts", "ifOutOctets": "ifOutUcastPkts"}
    for a, b in repl.items():
        inner = inner.replace(a, b)
    return f"net.if.{direction}.pkts[{inner}]"


def pct_expr(T, m_in, m_out, p_in, p_out, thr):
    def side(m, p):
        return (f"(avg(/{T}/{p},5m)>={MINPPS_MACRO} and "
                f"100*avg(/{T}/{m},5m)/(avg(/{T}/{m},5m)+avg(/{T}/{p},5m))>={thr})")
    return side(m_in, p_in) + " or " + side(m_out, p_out)


def get_protos(tid, key_prefix):
    r = api("itemprototype.get", {"templateids": tid, "search": {"key_": key_prefix},
            "output": ["itemid", "name", "key_", "snmp_oid", "delay", "value_type"],
            "selectPreprocessing": "extend"})
    return r


def process_template(tname, dry):
    t = api("template.get", {"filter": {"host": [tname]}, "output": ["templateid", "host"],
                             "selectMacros": ["macro", "value"]})
    if not t:
        print(f"[{tname}] NOT FOUND - skip"); return
    tid, T = t[0]["templateid"], t[0]["host"]
    lld = [r for r in api("discoveryrule.get", {"templateids": tid, "output": ["itemid", "name"]})
           if r["name"] == LLD_NAME]
    if not lld:
        print(f"[{tname}] no '{LLD_NAME}' LLD - skip"); return
    ruleid = lld[0]["itemid"]

    # gather existing octets/errors/discards item prototypes
    def one(prefix):
        r = get_protos(tid, prefix)
        return r[0] if r else None
    oin, oout = one("net.if.in["), one("net.if.out[")
    ein, eout = one("net.if.in.errors["), one("net.if.out.errors[")
    din, dout = one("net.if.in.discards["), one("net.if.out.discards[")
    if not all([oin, oout, ein, eout, din, dout]):
        print(f"[{tname}] missing octets/errors/discards items - skip"); return

    oid_in = ucast_get_oid(octets_oid(oin))
    oid_out = ucast_get_oid(octets_oid(oout))
    if not oid_in or not oid_out:
        print(f"[{tname}] could not map unicast-packet OID (octets in={octets_oid(oin)!r}) - SKIP (no guess)")
        return
    delay = next((d for d in (oin.get("delay"), ein.get("delay")) if d and d != "0"), "3m")
    pin_key, pout_key = pkts_key(oin["key_"], "in"), pkts_key(oout["key_"], "out")

    print(f"[{tname}]  (T={T})")
    existing_items = {i["key_"] for i in api("itemprototype.get", {"discoveryids": ruleid, "output": ["key_"]})}
    existing_trigs = {x["description"]: x for x in api("triggerprototype.get",
                      {"discoveryids": ruleid, "output": ["triggerid", "description", "status"],
                       "selectDependencies": ["triggerid"]})}

    # 1. macro
    macros = {m["macro"]: m["value"] for m in t[0].get("macros", [])}
    if macros.get(MINPPS_MACRO) != MINPPS_VALUE:
        print(f"    = MACRO {MINPPS_MACRO} -> {MINPPS_VALUE}")
        if not dry:
            cur = [m for m in api("usermacro.get", {"hostids": tid, "filter": {"macro": MINPPS_MACRO}, "output": ["hostmacroid"]})]
            if cur:
                api("usermacro.update", {"hostmacroid": cur[0]["hostmacroid"], "value": MINPPS_VALUE})
            else:
                api("usermacro.create", {"hostid": tid, "macro": MINPPS_MACRO, "value": MINPPS_VALUE})

    # 2. packet-rate items
    for key, oid, dirn in [(pin_key, oid_in, "Inbound"), (pout_key, oid_out, "Outbound")]:
        if key in existing_items:
            continue
        print(f"    + ITEM {key}  oid={oid}")
        if not dry:
            api("itemprototype.create", {
                "hostid": tid, "ruleid": ruleid,
                "name": f"Interface {{#IFNAME}}({{#IFALIAS}}): {dirn} unicast packets per second",
                "key_": key, "type": 20, "snmp_oid": oid, "value_type": 3, "units": "pps",
                "delay": delay,
                "preprocessing": [{"type": "10", "params": "", "error_handler": "0", "error_handler_params": ""}],
            })

    # 3. trigger prototypes (errors + discards, two tiers each)
    triplets = [
        ("Interface {#IFNAME}({#IFALIAS}): High error rate (>=1%)",  ein["key_"], eout["key_"], WARN_PCT, SEV_WARNING),
        ("Interface {#IFNAME}({#IFALIAS}): High error rate (>=5%)",  ein["key_"], eout["key_"], CRIT_PCT, SEV_HIGH),
        ("Interface {#IFNAME}({#IFALIAS}): High packet drop rate (>=1%)", din["key_"], dout["key_"], WARN_PCT, SEV_WARNING),
        ("Interface {#IFNAME}({#IFALIAS}): High packet drop rate (>=5%)", din["key_"], dout["key_"], CRIT_PCT, SEV_HIGH),
    ]
    for desc, m_in, m_out, thr, sev in triplets:
        if desc in existing_trigs:
            continue
        expr = pct_expr(T, m_in, m_out, pin_key, pout_key, thr)
        print(f"    + TRIG [{sev}] {desc}")
        if not dry:
            api("triggerprototype.create", {"description": desc, "expression": expr,
                                            "priority": sev, "manual_close": 1})

    # 3b. dependencies (Warn -> Crit), idempotent
    if not dry:
        cur = {x["description"]: x for x in api("triggerprototype.get",
               {"discoveryids": ruleid, "output": ["triggerid", "description"],
                "selectDependencies": ["triggerid"]})}
        for warn, crit in [("High error rate (>=1%)", "High error rate (>=5%)"),
                           ("High packet drop rate (>=1%)", "High packet drop rate (>=5%)")]:
            w = next((v for k, v in cur.items() if k.endswith(warn)), None)
            c = next((v for k, v in cur.items() if k.endswith(crit)), None)
            if w and c and not w.get("dependencies"):
                api("triggerprototype.update", {"triggerid": w["triggerid"],
                                                "dependencies": [{"triggerid": c["triggerid"]}]})

    # 4. disable stock absolute error-rate trigger prototype(s)
    for desc, x in existing_trigs.items():
        if any(desc.endswith(s) for s in STOCK_ERR_SUFFIXES) and "%" not in desc and x["status"] == "0":
            print(f"    x DISABLE stock prototype: {desc}")
            if not dry:
                api("triggerprototype.update", {"triggerid": x["triggerid"], "status": 1})


def rollback_template(tname, dry):
    t = api("template.get", {"filter": {"host": [tname]}, "output": ["templateid"]})
    if not t:
        return
    tid = t[0]["templateid"]
    lld = [r for r in api("discoveryrule.get", {"templateids": tid, "output": ["itemid", "name"]})
           if r["name"] == LLD_NAME]
    if not lld:
        return
    ruleid = lld[0]["itemid"]
    print(f"[{tname}] rollback")
    # delete added trigger prototypes
    trigs = api("triggerprototype.get", {"discoveryids": ruleid, "output": ["triggerid", "description", "status"]})
    delt = [x["triggerid"] for x in trigs if "%" in x["description"] and ("error rate" in x["description"] or "packet drop" in x["description"])]
    if delt:
        print(f"    - DELETE {len(delt)} % trigger prototypes")
        if not dry: api("triggerprototype.delete", delt)
    # re-enable stock error-rate prototypes
    for x in trigs:
        if any(x["description"].endswith(s) for s in STOCK_ERR_SUFFIXES) and "%" not in x["description"] and x["status"] == "1":
            print(f"    o ENABLE stock {x['description']}")
            if not dry: api("triggerprototype.update", {"triggerid": x["triggerid"], "status": 0})
    # delete added pkts items
    items = api("itemprototype.get", {"discoveryids": ruleid, "output": ["itemid", "key_"]})
    deli = [i["itemid"] for i in items if i["key_"].startswith(("net.if.in.pkts[", "net.if.out.pkts["))]
    if deli:
        print(f"    - DELETE {len(deli)} pkts item prototypes")
        if not dry: api("itemprototype.delete", deli)
    # remove macro
    m = api("usermacro.get", {"hostids": tid, "filter": {"macro": MINPPS_MACRO}, "output": ["hostmacroid"]})
    if m:
        print(f"    - REMOVE macro {MINPPS_MACRO}")
        if not dry: api("usermacro.delete", [m[0]["hostmacroid"]])


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--dry-run"
    if mode not in ("--dry-run", "--apply", "--rollback"):
        sys.exit("usage: --dry-run | --apply | --rollback")
    dry = mode == "--dry-run"
    print(f"Mode: {mode}\n")
    for tn in TEMPLATES:
        (rollback_template if mode == "--rollback" else process_template)(tn, dry)
    print("\n(dry-run: nothing changed)" if dry else "\nDone.")


if __name__ == "__main__":
    main()
