#!/usr/bin/env python3
"""
Grafana dashboard automation — CRUD over the HTTP API plus provisioning sync.

Dashboards here are FILE-PROVISIONED from:
    /root/zabbix-stack/grafana/provisioning/dashboards/json
That folder is the source of truth. The Grafana provider has allowUiUpdates=true,
so direct API writes work but get overwritten on the next file reload. Therefore:

  * Persistent changes  -> edit/add the JSON file, then `reload` (or use `provision`).
  * Throwaway/API edits  -> `create` / `update` (handy for testing).

Connection (env overrides, otherwise auto-detected):
  GRAFANA_URL    e.g. http://172.18.0.12:3000   (default: docker-inspect grafana IP, else localhost)
  GRAFANA_USER   default: admin
  GRAFANA_PASS   default: admin
  GRAFANA_TOKEN  optional Bearer token (takes precedence over user/pass)

Commands:
  list                         List all dashboards (title | uid | folder)
  get    <uid> [-o FILE]       GET one dashboard's model (to FILE or stdout)
  create <FILE>                POST a new dashboard from a JSON model
  update <FILE>                POST with overwrite=true (create-or-update)
  delete <uid>                 DELETE a dashboard
  reload                       Trigger provisioning reload from disk
  provision <FILE>             Copy FILE into the provisioning json dir, then reload (persistent)
  backup [-d DIR]              GET every dashboard model into DIR (default: ./backup-<ts>)

Examples:
  ./dashboard-manager.py list
  ./dashboard-manager.py get device-status -o /tmp/ds.json
  ./dashboard-manager.py update ./provisioning/dashboards/json/device-status.json
  ./dashboard-manager.py delete old-dashboard
  ./dashboard-manager.py reload
"""
import argparse, json, os, sys, time, subprocess, urllib.request, urllib.error, base64

PROVISION_DIR = "/root/zabbix-stack/grafana/provisioning/dashboards/json"


def grafana_base():
    if os.environ.get("GRAFANA_URL"):
        return os.environ["GRAFANA_URL"].rstrip("/")
    # try to resolve the grafana container IP (port 3000 is not published to host)
    try:
        ip = subprocess.check_output(
            ["docker", "inspect", "-f",
             "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", "grafana"],
            stderr=subprocess.DEVNULL, text=True).strip()
        if ip:
            return f"http://{ip}:3000"
    except Exception:
        pass
    return "http://localhost:3000"


def auth_header():
    tok = os.environ.get("GRAFANA_TOKEN")
    if tok:
        return f"Bearer {tok}"
    user = os.environ.get("GRAFANA_USER", "admin")
    pw = os.environ.get("GRAFANA_PASS", "admin")
    return "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()


def api(method, path, body=None):
    url = grafana_base() + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", auth_header())
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            raw = json.loads(raw)
        except Exception:
            pass
        return e.code, raw


def load_model(path):
    """Accept either a raw dashboard model or a {'dashboard': {...}} envelope."""
    with open(path) as f:
        obj = json.load(f)
    return obj["dashboard"] if isinstance(obj, dict) and "dashboard" in obj else obj


def cmd_list(_a):
    st, res = api("GET", "/api/search?type=dash-db&limit=5000")
    if st != 200:
        sys.exit(f"list failed ({st}): {res}")
    for d in sorted(res, key=lambda x: (x.get("folderTitle", ""), x.get("title", ""))):
        print(f"  {d.get('title',''):45} | {d.get('uid',''):24} | {d.get('folderTitle','General')}")
    print(f"\n  {len(res)} dashboard(s) at {grafana_base()}")


def cmd_get(a):
    st, res = api("GET", f"/api/dashboards/uid/{a.uid}")
    if st != 200:
        sys.exit(f"get failed ({st}): {res}")
    model = res["dashboard"]
    out = json.dumps(model, indent=2)
    if a.output:
        with open(a.output, "w") as f:
            f.write(out)
        print(f"  wrote {a.output} ({model.get('title')})")
    else:
        print(out)


def _save(model, overwrite, label):
    model.pop("id", None)          # let Grafana assign / match by uid
    body = {"dashboard": model, "overwrite": overwrite,
            "message": f"{label} via dashboard-manager"}
    st, res = api("POST", "/api/dashboards/db", body)
    if st == 200:
        print(f"  {label} OK: {res.get('uid')} (v{res.get('version')}) -> {res.get('url')}")
    else:
        sys.exit(f"  {label} failed ({st}): {res}")


def cmd_create(a):
    _save(load_model(a.file), overwrite=False, label="create")


def cmd_update(a):
    _save(load_model(a.file), overwrite=True, label="update")


def cmd_delete(a):
    st, res = api("DELETE", f"/api/dashboards/uid/{a.uid}")
    if st == 200:
        print(f"  deleted {a.uid}: {res.get('title','')}")
    else:
        sys.exit(f"  delete failed ({st}): {res}")


def cmd_reload(_a):
    st, res = api("POST", "/api/admin/provisioning/dashboards/reload")
    print(f"  reload ({st}): {res}")
    if st != 200:
        sys.exit(1)


def cmd_provision(a):
    model = load_model(a.file)
    uid = model.get("uid") or os.path.splitext(os.path.basename(a.file))[0]
    dst = os.path.join(PROVISION_DIR, f"{uid}.json")
    with open(dst, "w") as f:
        json.dump(model, f, indent=2)
    print(f"  wrote {dst}")
    cmd_reload(a)


def cmd_backup(a):
    dest = a.dir or f"backup-{int(time.time())}"
    os.makedirs(dest, exist_ok=True)
    st, res = api("GET", "/api/search?type=dash-db&limit=5000")
    if st != 200:
        sys.exit(f"backup list failed ({st}): {res}")
    n = 0
    for d in res:
        s2, r2 = api("GET", f"/api/dashboards/uid/{d['uid']}")
        if s2 == 200:
            with open(os.path.join(dest, f"{d['uid']}.json"), "w") as f:
                json.dump(r2["dashboard"], f, indent=2)
            n += 1
    print(f"  backed up {n} dashboard(s) -> {dest}/")


def main():
    p = argparse.ArgumentParser(description="Grafana dashboard automation",
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(func=cmd_list)
    g = sub.add_parser("get"); g.add_argument("uid"); g.add_argument("-o", "--output"); g.set_defaults(func=cmd_get)
    c = sub.add_parser("create"); c.add_argument("file"); c.set_defaults(func=cmd_create)
    u = sub.add_parser("update"); u.add_argument("file"); u.set_defaults(func=cmd_update)
    d = sub.add_parser("delete"); d.add_argument("uid"); d.set_defaults(func=cmd_delete)
    sub.add_parser("reload").set_defaults(func=cmd_reload)
    pr = sub.add_parser("provision"); pr.add_argument("file"); pr.set_defaults(func=cmd_provision)
    b = sub.add_parser("backup"); b.add_argument("-d", "--dir"); b.set_defaults(func=cmd_backup)
    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
