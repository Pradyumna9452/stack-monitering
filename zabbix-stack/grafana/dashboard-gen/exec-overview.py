#!/usr/bin/env python3
"""Executive / NOC Health Overview  (built on this stack's real metrics).
Layout (per user spec, section by section):
  GAUGES : Overall Health | Infrastructure Health | Active Alerts
  BOXES  : Server | Virtual Machine | Network | Storage Summary | Uptime | Top Critical Alerts
  GRAPHS : Availability Trend (7d) | Bandwidth Utilization (All Links)
  BARS   : Top 5 CPU (Server) | Top Memory (Server) | Top Storage Usage
  + SLA Availability by Site (7d) bar chart + Recent Events (Last 10) table
VM split = physical vs guests: Server=role "Hypervisor"; VM=host_type Server & role!=Hypervisor.
Sources: VictoriaMetrics (uid victoriametrics) + native Zabbix problems (uid zabbix).
"""
import json

VM = {"type": "prometheus", "uid": "victoriametrics"}
ZBX = {"type": "alexanderzobnin-zabbix-datasource", "uid": "zabbix"}  # native plugin (unused: unreliable)
# Infinity -> Zabbix JSON-RPC API. Proven path (sla-report.json uses it); bearer token + host allow-list
# are provisioned on this datasource. The native alexanderzobnin "problems" query errors server-side
# ("non-metrics queries are not supported"), so all alert panels go through Infinity + problem.get instead.
INF = {"type": "yesoreyeram-infinity-datasource", "uid": "zabbix-sla-infinity"}
ZBX_URL = "http://zabbix-web:8080/api_jsonrpc.php"
UPSET = 'ICMP ping|Zabbix agent availability|Zabbix agent ping'
UPTIME = 'System uptime|Uptime|Uptime \\\\(network\\\\)'

_id = [0]
def nid():
    _id[0] += 1
    return _id[0]

def gp(x, y, w, h):
    return {"h": h, "w": w, "x": x, "y": y}

def vmt(expr, legend="", instant=False):
    t = {"datasource": VM, "editorMode": "code", "expr": expr, "refId": "A",
         "range": not instant, "instant": instant}
    if legend:
        t["legendFormat"] = legend
    return t

def _rpc(method, params):
    return json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1})

def inf_target(params, root_selector, columns, method="problem.get"):
    """Infinity target: POST a Zabbix JSON-RPC method, shape the result with jq."""
    return {"datasource": INF, "refId": "A", "type": "json", "source": "url",
            "format": "table", "parser": "jq-backend", "url": ZBX_URL,
            "url_options": {"method": "POST", "body_type": "raw",
                            "body_content_type": "application/json",
                            "data": _rpc(method, params)},
            "root_selector": root_selector, "columns": columns}

def inf_count(params, text="count"):
    """Single-number count of active problems matching params."""
    return inf_target({**params, "output": ["eventid"]},
                      '[{"count": (.result | length)}]',
                      [{"selector": "count", "text": text, "type": "number"}])

def thr(steps):
    return {"mode": "absolute", "steps": steps}

HEALTH = [{"color": "red", "value": None}, {"color": "orange", "value": 90},
          {"color": "yellow", "value": 98}, {"color": "green", "value": 99.5}]
UTIL = [{"color": "green", "value": None}, {"color": "yellow", "value": 70},
        {"color": "orange", "value": 85}, {"color": "red", "value": 95}]
ALERTS = [{"color": "green", "value": None}, {"color": "yellow", "value": 100},
          {"color": "orange", "value": 300}, {"color": "red", "value": 500}]      # total active
CRIT = [{"color": "green", "value": None}, {"color": "yellow", "value": 10},
        {"color": "orange", "value": 50}, {"color": "red", "value": 100}]         # Disaster+High
UP = [{"color": "red", "value": None}, {"color": "yellow", "value": 604800},
      {"color": "green", "value": 2592000}]  # 7d / 30d in seconds
# composite health score (availability + CPU/mem headroom) — own scale, not raw availability %
INFRA = [{"color": "red", "value": None}, {"color": "orange", "value": 70},
         {"color": "yellow", "value": 85}, {"color": "green", "value": 95}]

def avail(sel):
    return 'avg(max by(host)(avg_over_time({__name__=~"%s"%s}[$__range]))) * 100' % (UPSET, sel)

panels = []

# ===== GAUGES =============================================================
def gauge(title, ds, target, x, y, w, h, steps, unit="percent", maxv=100, dec=1,
          calc="lastNotNull", noval=None):
    p = {"id": nid(), "type": "gauge", "title": title, "datasource": ds,
         "gridPos": gp(x, y, w, h), "targets": [target],
         "options": {"reduceOptions": {"calcs": [calc], "fields": "", "values": False},
                     "orientation": "auto", "showThresholdLabels": False, "showThresholdMarkers": True},
         "fieldConfig": {"defaults": {"unit": unit, "min": 0, "max": maxv, "decimals": dec,
                                      "thresholds": thr(steps), "color": {"mode": "thresholds"}},
                         "overrides": []}}
    if noval is not None:
        p["fieldConfig"]["defaults"]["noValue"] = noval
    return p

panels.append(gauge("Overall Health", VM, vmt(avail(', site=~"$site"'), instant=True),
                    0, 0, 6, 6, HEALTH))

infra_expr = ('0.6 * (%s) '
              '+ 0.2 * (100 - avg(last_over_time({__name__="CPU utilization", site=~"$site"}[10m]))) '
              '+ 0.2 * (100 - avg(last_over_time({__name__="Memory utilization", site=~"$site"}[10m])))'
              % avail(', site=~"$site"'))
panels.append(gauge("Infrastructure Health", VM, vmt(infra_expr, instant=True),
                    6, 0, 6, 6, INFRA))

panels.append(gauge("Active Alerts (Total)", INF, inf_count({}, "Active Alerts"),
                    12, 0, 6, 6, ALERTS, unit="short", maxv=800, dec=0, calc="lastNotNull", noval="0"))

# ===== BOXES ==============================================================
def box(title, ds, target, x, w, steps, unit="percent", dec=1, noval=None, y=6, h=5, calc="lastNotNull"):
    p = {"id": nid(), "type": "stat", "title": title, "datasource": ds,
         "gridPos": gp(x, y, w, h), "targets": [target],
         "options": {"reduceOptions": {"calcs": [calc], "fields": "", "values": False},
                     "orientation": "auto", "textMode": "value_and_name",
                     "colorMode": "background_solid", "graphMode": "none",
                     "justifyMode": "center", "showPercentChange": False, "wideLayout": True},
         "fieldConfig": {"defaults": {"unit": unit, "decimals": dec, "thresholds": thr(steps),
                                      "color": {"mode": "thresholds"}}, "overrides": []}}
    if noval is not None:
        p["fieldConfig"]["defaults"]["noValue"] = noval
    return p

# Row B — four subsystem summaries in one clean row (w6 each)
panels.append(box("Server Summary", VM,
                  vmt(avail(', host_type="Server", role="Hypervisor", site=~"$site"'), instant=True), 0, 6, HEALTH))
panels.append(box("Virtual Machine Summary", VM,
                  vmt(avail(', host_type="Server", role!="Hypervisor", site=~"$site"'), instant=True), 6, 6, HEALTH))
panels.append(box("Network Summary", VM,
                  vmt(avail(', host_type=~"Switch|Firewall", site=~"$site"'), instant=True), 12, 6, HEALTH))
panels.append(box("Storage Summary", VM,
                  vmt(avail(', host_type="Storage", site=~"$site"'), instant=True), 18, 6, HEALTH))
# Top Critical Alerts — 4th tile in the gauge row (Row A)
panels.append(box("Top Critical Alerts", INF, inf_count({"severities": [4, 5]}, "Top Critical"),
                  18, 6, CRIT, unit="short", dec=0, noval="0", calc="lastNotNull", y=0, h=6))
# Uptime Summary lives in the bottom group row (Row E) — defined here, positioned at y=27.
# unit "s" auto-scales seconds -> compact "67.3 day" (dtdurations renders a long verbose string).
panels.append(box("Uptime Summary", VM,
                  vmt('avg(last_over_time({__name__=~"%s", site=~"$site"}[10m]))' % UPTIME, instant=True),
                  18, 6, UP, unit="s", dec=1, y=27, h=9))

# ===== GRAPHS =============================================================
panels.append({
    "id": nid(), "type": "timeseries", "title": "Availability Trend (Last 7 Days)",
    "datasource": VM, "gridPos": gp(0, 11, 12, 8), "timeFrom": "7d",
    "targets": [vmt('avg(avg_over_time({__name__=~"%s", site=~"$site"}[10m])) * 100' % UPSET,
                    legend="Fleet availability")],
    "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    "fieldConfig": {"defaults": {"unit": "percent", "min": 90, "max": 100, "decimals": 2,
                                 "color": {"mode": "thresholds"}, "thresholds": thr(HEALTH),
                                 "custom": {"drawStyle": "line", "fillOpacity": 15, "lineWidth": 2,
                                            "gradientMode": "opacity", "spanNulls": True,
                                            "thresholdsStyle": {"mode": "line"}}}, "overrides": []},
})

bw_in = {"datasource": VM, "editorMode": "code", "refId": "A", "range": True,
         "expr": 'sum(last_over_time({__name__=~"Interface.*: Bits received", site=~"$site"}[5m]))',
         "legendFormat": "Inbound"}
bw_out = {"datasource": VM, "editorMode": "code", "refId": "B", "range": True,
          "expr": '- sum(last_over_time({__name__=~"Interface.*: Bits sent", site=~"$site"}[5m]))',
          "legendFormat": "Outbound"}
panels.append({
    "id": nid(), "type": "timeseries", "title": "Bandwidth Utilization (All Links)",
    "datasource": VM, "gridPos": gp(12, 11, 12, 8), "targets": [bw_in, bw_out],
    "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    "fieldConfig": {"defaults": {"unit": "bps", "color": {"mode": "palette-classic"},
                                 "custom": {"drawStyle": "line", "fillOpacity": 20, "lineWidth": 1,
                                            "gradientMode": "opacity", "spanNulls": True}}, "overrides": []},
})

# ===== BAR GAUGES =========================================================
def bargauge(title, expr, x, w, y=19, h=8):
    return {"id": nid(), "type": "bargauge", "title": title, "datasource": VM,
            "gridPos": gp(x, y, w, h), "targets": [vmt(expr, legend="{{host}}", instant=True)],
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "displayMode": "gradient", "orientation": "horizontal",
                        "showUnfilled": True, "valueMode": "color"},
            "fieldConfig": {"defaults": {"unit": "percent", "min": 0, "max": 100, "decimals": 1,
                                         "color": {"mode": "thresholds"}, "thresholds": thr(UTIL)},
                            "overrides": []}}

panels.append(bargauge("Top 5 CPU Utilization (Server)",
    'topk(5, max by(host)(max_over_time({__name__=~"CPU [Uu]tilization", host_type="Server", site=~"$site"}[$__range])))', 0, 8))
panels.append(bargauge("Top 5 Memory Utilization (Server)",
    'topk(5, max by(host)(max_over_time({__name__=~"Memory [Uu]tilization", host_type="Server", site=~"$site"}[$__range])))', 8, 8))
panels.append(bargauge("Top Storage Usage",
    'topk(5, max by(host)(max_over_time({__name__=~"FS \\\\[.*\\\\]: Space: Used, in %", site=~"$site"}[$__range])))', 16, 8))

# ===== SLA by site + Recent events =======================================
# SLA by site as a BAR GAUGE: an instant vector returns one series per site (legend = site),
# which bar gauges render as one labeled bar each — reliable, unlike barchart which needs a
# string category field that VictoriaMetrics' instant+table format doesn't produce.
sla_expr = ('avg by(site)(max by(host, site)('
            'avg_over_time({__name__=~"%s", site=~"$site", site!=""}[7d]))) * 100' % UPSET)
panels.append({
    "id": nid(), "type": "bargauge", "title": "SLA Availability by Site (Last 7 Days)",
    "datasource": VM, "gridPos": gp(12, 27, 6, 9),
    "targets": [vmt(sla_expr, legend="{{site}}", instant=True)],
    "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                "displayMode": "gradient", "orientation": "horizontal",
                "showUnfilled": True, "valueMode": "color"},
    "fieldConfig": {"defaults": {"unit": "percent", "min": 85, "max": 100, "decimals": 2,
                                 "color": {"mode": "thresholds"}, "thresholds": thr(HEALTH)}, "overrides": []},
})
# ---- Alert bar graphs: Infinity + jq aggregation over trigger.get (value=1 => active problem) ----
COUNTS = [{"color": "green", "value": None}, {"color": "yellow", "value": 10},
          {"color": "orange", "value": 25}, {"color": "red", "value": 40}]

def inf_bargauge(title, params, root, cols, x, w, steps, y=27, h=9, method="trigger.get"):
    return {"id": nid(), "type": "bargauge", "title": title, "datasource": INF,
            "gridPos": gp(x, y, w, h), "targets": [inf_target(params, root, cols, method=method)],
            "options": {"reduceOptions": {"values": True, "calcs": [], "fields": ""},
                        "displayMode": "gradient", "orientation": "horizontal",
                        "showUnfilled": True, "valueMode": "color"},
            "fieldConfig": {"defaults": {"unit": "short", "decimals": 0,
                                         "color": {"mode": "thresholds"}, "thresholds": thr(steps)},
                            "overrides": []}}

# Top 10 Alerts — the 10 hosts with the most active alerts (bar per host)
panels.append(inf_bargauge("Top 10 Alerts (by host)",
    {"output": ["priority", "value"], "selectHosts": ["name"], "filter": {"value": 1},
     "monitored": True, "skipDependent": True},
    '.result | group_by(.hosts[0].name) | map({Host:(.[0].hosts[0].name // "-"), Count: length}) '
    '| sort_by(.Count) | reverse | .[0:10]',
    [{"selector": "Host", "text": "Host", "type": "string"},
     {"selector": "Count", "text": "Count", "type": "number"}],
    0, 6, COUNTS))

# Alerts by Severity — active alert counts per severity level (Recent Events shown as bars)
panels.append(inf_bargauge("Alerts by Severity",
    {"output": ["priority", "value"], "filter": {"value": 1}, "monitored": True, "skipDependent": True},
    '.result | group_by(.priority) '
    '| map({Severity:(["Not classified","Info","Warning","Average","High","Disaster"][.[0].priority|tonumber]), '
    'Count: length, _p:(.[0].priority|tonumber)}) | sort_by(._p) | reverse',
    [{"selector": "Severity", "text": "Severity", "type": "string"},
     {"selector": "Count", "text": "Count", "type": "number"}],
    6, 6, COUNTS))

templating = {"list": [{
    "name": "site", "label": "Site", "type": "query", "datasource": VM,
    "definition": "label_values(site)", "query": {"query": "label_values(site)", "refId": "vm-site"},
    "includeAll": True, "allValue": ".*", "multi": True,
    # default to All so $site resolves to ".*" on first load (empty $site => site=~"" => blank panels)
    "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
    "refresh": 2, "sort": 1, "hide": 0,
}]}

dashboard = {
    "uid": "executive-overview", "title": "Executive Health Overview",
    "tags": ["executive", "noc", "overview"], "schemaVersion": 39, "version": 1,
    "editable": True, "graphTooltip": 0, "refresh": "1m",
    "time": {"from": "now-24h", "to": "now"}, "timezone": "",
    "templating": templating, "panels": panels,
}

out = "/root/zabbix-stack/grafana/provisioning/dashboards/json/executive-overview.json"
with open(out, "w") as f:
    json.dump(dashboard, f, indent=2)
print("wrote", out, "| panels:", len(panels))
