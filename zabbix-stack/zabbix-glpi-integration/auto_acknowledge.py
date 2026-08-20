#!/usr/bin/env python3
"""
Universal auto-acknowledge for Zabbix problems (container-internal version).

The GLPI webhook already auto-acknowledges Average+ events when it raises a
ticket. Email-only events (< Average, e.g. Warnings) never traverse that path,
so they stay unacknowledged forever. This job acknowledges EVERY open,
unacknowledged problem. Idempotent: only touches problems where
acknowledged == "0".

Runs inside the glpi-webhook container on an internal schedule (entrypoint.sh) --
no host cron, no .env file, no localhost dependency. Reads ZABBIX_URL and
ZABBIX_API_TOKEN from the environment (already provided by docker-compose).
"""
import json
import os
import ssl
import sys
import time
import urllib.request

URL = os.environ.get("ZABBIX_URL", "http://zabbix-web:8080/api_jsonrpc.php")
TOKEN = os.environ.get("ZABBIX_API_TOKEN", "").strip()
ACK_MESSAGE = os.environ.get(
    "AUTO_ACK_MESSAGE",
    "Auto-acknowledged by system (alert dispatched / ticket handled).",
)
# event.acknowledge action bitmask: 2 = acknowledge, 4 = add message -> 6
ACK_ACTION = 6

# Tolerate https endpoints with self-signed certs (internal http needs no ctx).
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def call(method, params, token):
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    headers = {"Content-Type": "application/json-rpc",
               "Authorization": "Bearer " + token}
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(), headers=headers)
    resp = json.loads(urllib.request.urlopen(req, context=ctx, timeout=30).read().decode())
    if "error" in resp:
        raise RuntimeError(json.dumps(resp["error"]))
    return resp["result"]


def main():
    if not TOKEN:
        raise SystemExit("ZABBIX_API_TOKEN not set in environment")
    problems = call("problem.get", {"output": ["eventid", "acknowledged"]}, TOKEN)
    eventids = [p["eventid"] for p in problems if p.get("acknowledged") == "0"]
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    if not eventids:
        print(f"{ts} nothing to acknowledge (open={len(problems)})")
        return
    call("event.acknowledge", {
        "eventids": eventids,
        "action": ACK_ACTION,
        "message": ACK_MESSAGE,
    }, TOKEN)
    print(f"{ts} acknowledged {len(eventids)} problem(s) (open={len(problems)})")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(time.strftime("%Y-%m-%d %H:%M:%S"), "ERROR:", e, file=sys.stderr)
        sys.exit(1)
