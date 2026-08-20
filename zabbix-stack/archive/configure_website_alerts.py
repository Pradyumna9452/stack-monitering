#!/usr/bin/env python3
"""
Configure two-tier Website monitoring (Response Time + SSL Certificate Expiry)
in Zabbix, agent-less for HTTP timing and via the local agent2 for the cert.

Per site in SITES (one host each, in the "Websites" host group):

  Response Time  (server-side web scenario, 1m poll):
    - web scenario "<host>" with one GET step "Homepage"
    - auto item web.test.time[<host>,Homepage,resp]  (seconds)
    - Website: Response time >3s (Warning)   min(/h/...,5m)>3   sev Warning(2)
    - Website: Response time >10s (Critical)  min(/h/...,5m)>10  sev High(4)

  SSL Certificate Expiry  (agent2 web.certificate.get on the zabbix-agent
  container, polled daily):
    - master item web.certificate.get[<fqdn>,443]  (text, 1d)
    - dependent ssl.cert.daysleft[<fqdn>]  = floor((not_after.ts - now)/86400)
    - dependent ssl.cert.result[<fqdn>]    = $.result.value   (data only)
    - Website: SSL certificate expires in <45 days (Warning)  last(...)<45  sev Warning(2)
    - Website: SSL certificate expires in <15 days (Critical) last(...)<15  sev High(4)

In both pairs the Warning trigger depends on the Critical trigger (suppresses
the duplicate Warning once Critical is active). 5-min hold for response time;
the SSL items use a daily poll so "hold" is one sample.

Email + GLPI ticket routing uses the EXISTING actions (verified unconditional
except severity): "sonic" / "Report problems to Zabbix administrators" email on
all problems; "GLPI Ticket Automation" tickets at severity >= Average. Only the
Critical (High) triggers cross that threshold => Warnings email-only, Criticals
email + ticket. No action changes required.

Idempotent and reversible. Usage:
    python3 configure_website_alerts.py --dry-run
    python3 configure_website_alerts.py --apply
    python3 configure_website_alerts.py --rollback
"""
import json, os, ssl, sys, urllib.request

ZABBIX_URL = "https://localhost/zabbix/api_jsonrpc.php"
GROUP_NAME = "Websites"
AGENT_DNS = "zabbix-agent"   # the agent2 container that runs web.certificate.get
AGENT_PORT = "10050"

# Zabbix severities
SEV_WARNING = 2
SEV_HIGH = 4

# Thresholds (per the device-type matrix)
RESP_WARN, RESP_CRIT = 3, 10            # seconds, sustained over 5m
RESP_HOLD = "5m"
SSL_WARN, SSL_CRIT = 45, 15             # days remaining
RESP_DELAY = "1m"
SSL_DELAY = "1d"

# Sites to monitor: (host display name, URL, cert FQDN, cert port)
SITES = [
    ("Website www.sonicbiochem.co.in", "https://www.sonicbiochem.co.in/", "www.sonicbiochem.co.in", "443"),
]

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


def ensure_group(dry):
    g = api("hostgroup.get", {"filter": {"name": GROUP_NAME}, "output": ["groupid"]})
    if g:
        return g[0]["groupid"]
    print(f"  + GROUP {GROUP_NAME}")
    if dry:
        return None
    return api("hostgroup.create", {"name": GROUP_NAME})["groupids"][0]


def ensure_host(name, groupid, dry):
    h = api("host.get", {"filter": {"host": name}, "output": ["hostid"],
                         "selectInterfaces": ["interfaceid", "type"]})
    if h:
        hid = h[0]["hostid"]
        if not any(i["type"] == "1" for i in h[0].get("interfaces", [])):
            print(f"    + agent interface on {name}")
            if not dry:
                api("hostinterface.create", {"hostid": hid, "type": 1, "main": 1,
                    "useip": 0, "ip": "", "dns": AGENT_DNS, "port": AGENT_PORT})
        return hid
    print(f"  + HOST {name}")
    if dry:
        return None
    return api("host.create", {
        "host": name, "groups": [{"groupid": groupid}],
        "interfaces": [{"type": 1, "main": 1, "useip": 0, "ip": "",
                        "dns": AGENT_DNS, "port": AGENT_PORT}],
    })["hostids"][0]


def ensure_item(hid, spec, existing, dry):
    if spec["key_"] in existing:
        return existing[spec["key_"]]
    print(f"    + ITEM {spec['key_']}")
    if dry:
        return None
    spec = dict(spec, hostid=hid)
    return api("item.create", spec)["itemids"][0]


def ensure_httptest(hid, name, url, dry):
    t = api("httptest.get", {"hostids": hid, "filter": {"name": name}, "output": ["httptestid"]})
    if t:
        return t[0]["httptestid"]
    print(f"    + WEB SCENARIO {name}")
    if dry:
        return None
    return api("httptest.create", {
        "name": name, "hostid": hid, "delay": RESP_DELAY, "retries": 2,
        "steps": [{"name": "Homepage", "url": url, "status_codes": "200",
                   "no": 1, "follow_redirects": 1, "retrieve_mode": 0}],
    })["httptestids"][0]


def ensure_trigger(desc, expr, sev, existing, dry):
    if desc in existing:
        return existing[desc]["triggerid"]
    print(f"    + TRIG [{sev}] {desc}")
    if dry:
        return None
    return api("trigger.create", {"description": desc, "expression": expr,
                                  "priority": sev, "manual_close": 1})["triggerids"][0]


def ensure_dep(warn_id, crit_id, dry):
    if dry or not warn_id or not crit_id:
        return
    cur = api("trigger.get", {"triggerids": warn_id, "selectDependencies": ["triggerid"],
                              "output": ["triggerid"]})
    if any(d["triggerid"] == crit_id for d in cur[0].get("dependencies", [])):
        return
    print(f"      dep: Warning -> Critical")
    api("trigger.update", {"triggerid": warn_id, "dependencies": [{"triggerid": crit_id}]})


def process(dry):
    gid = ensure_group(dry)
    for name, url, fqdn, port in SITES:
        print(f"[{name}]")
        hid = ensure_host(name, gid, dry)

        # web scenario (creates web.test.time[...] item)
        ensure_httptest(hid, name, url, dry)

        existing_items = {} if not hid else {
            i["key_"]: i["itemid"] for i in
            api("item.get", {"hostids": hid, "output": ["itemid", "key_"]})}

        # SSL items: master + dependents
        master_key = f"web.certificate.get[{fqdn},{port}]"
        master_id = ensure_item(hid, {
            "name": "SSL certificate: data", "key_": master_key,
            "type": 0, "value_type": 4, "delay": SSL_DELAY,
            "interfaceid": _agent_iface(hid, dry)}, existing_items, dry)

        days_key = f"ssl.cert.daysleft[{fqdn}]"
        ensure_item(hid, {
            "name": "SSL certificate: days until expiry", "key_": days_key,
            "type": 18, "value_type": 0, "units": "days",
            "master_itemid": master_id,
            "preprocessing": [
                {"type": 12, "params": "$.x509.not_after.timestamp", "error_handler": 0, "error_handler_params": ""},
                {"type": 21, "params": "return Math.floor((Number(value)-Date.now()/1000)/86400);",
                 "error_handler": 0, "error_handler_params": ""},
            ]}, existing_items, dry)

        ensure_item(hid, {
            "name": "SSL certificate: validation result", "key_": f"ssl.cert.result[{fqdn}]",
            "type": 18, "value_type": 4, "master_itemid": master_id,
            "preprocessing": [
                {"type": 12, "params": "$.result.value", "error_handler": 0, "error_handler_params": ""}]},
            existing_items, dry)

        # triggers
        existing_trigs = {} if not hid else {
            t["description"]: t for t in
            api("trigger.get", {"hostids": hid, "output": ["triggerid", "description"]})}

        resp_item = f"web.test.time[{name},Homepage,resp]"
        specs = [
            (f"Website: Response time >{RESP_WARN}s (Warning)",
             f"min(/{name}/{resp_item},{RESP_HOLD})>{RESP_WARN}", SEV_WARNING, "resp_w"),
            (f"Website: Response time >{RESP_CRIT}s (Critical)",
             f"min(/{name}/{resp_item},{RESP_HOLD})>{RESP_CRIT}", SEV_HIGH, "resp_c"),
            (f"Website: SSL certificate expires in <{SSL_WARN} days (Warning)",
             f"last(/{name}/{days_key})<{SSL_WARN}", SEV_WARNING, "ssl_w"),
            (f"Website: SSL certificate expires in <{SSL_CRIT} days (Critical)",
             f"last(/{name}/{days_key})<{SSL_CRIT}", SEV_HIGH, "ssl_c"),
        ]
        ids = {}
        for desc, expr, sev, tag in specs:
            ids[tag] = ensure_trigger(desc, expr, sev, existing_trigs, dry)
        ensure_dep(ids["resp_w"], ids["resp_c"], dry)
        ensure_dep(ids["ssl_w"], ids["ssl_c"], dry)


def _agent_iface(hid, dry):
    if not hid:
        return None
    ifs = api("hostinterface.get", {"hostids": hid, "output": ["interfaceid", "type"]})
    for i in ifs:
        if i["type"] == "1":
            return i["interfaceid"]
    return None


def rollback():
    g = api("hostgroup.get", {"filter": {"name": GROUP_NAME}, "output": ["groupid"]})
    if not g:
        print("no Websites group - nothing to roll back"); return
    gid = g[0]["groupid"]
    hosts = api("host.get", {"groupids": gid, "filter": {"host": [s[0] for s in SITES]},
                             "output": ["hostid", "host"]})
    for h in hosts:
        print(f"  - HOST {h['host']} (cascades items/triggers/web scenario)")
        api("host.delete", [h["hostid"]])
    remaining = api("host.get", {"groupids": gid, "output": ["hostid"]})
    if not remaining:
        print(f"  - GROUP {GROUP_NAME} (empty)")
        api("hostgroup.delete", [gid])


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--dry-run"
    if mode == "--rollback":
        rollback()
    elif mode == "--apply":
        process(dry=False)
    elif mode == "--dry-run":
        print("=== DRY RUN (no changes) ===")
        process(dry=True)
    else:
        sys.exit("usage: --dry-run | --apply | --rollback")


if __name__ == "__main__":
    main()
