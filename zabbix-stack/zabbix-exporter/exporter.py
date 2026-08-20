#!/usr/bin/env python3
"""
Zabbix to VictoriaMetrics Exporter
Fetches metrics from Zabbix API and exports them to VictoriaMetrics.

Key labels exported so Grafana dashboards work without manual updates:
  host          - Zabbix technical host name
  host_name     - Zabbix visible display name
  host_groups   - comma-joined group names (e.g. "Switches,HO/Switches")
  site          - site tag  (HO / SONIC / SEZ / MSOUR / MDEEP)
  host_type     - type tag  (Server / Switch / Firewall / Storage)
  role          - role tag  (Core-Switch / NAS / VDI / etc.)
  item          - Zabbix item display name
  tag_interface - interface name for net.if.* items (enables IF drilldown)
"""

import os
import re
import time
import logging
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ZABBIX_URL       = os.environ.get('ZABBIX_URL',        'http://zabbix-web:8080/api_jsonrpc.php')
ZABBIX_API_TOKEN = os.environ.get('ZABBIX_API_TOKEN', '')
VM_URL           = os.environ.get('VM_URL',            'http://victoriametrics:8428')
EXPORT_INTERVAL  = int(os.environ.get('EXPORT_INTERVAL', 60))

# Regex to extract interface name from Zabbix LLD item names:
#   "Interface GigabitEthernet1/0/1: Bits received"  →  GigabitEthernet1/0/1
#   "Interface eth0(): Bits received"                 →  eth0
_IF_RE = re.compile(r'^Interface\s+([^:()]+?)(?:\(\))?\s*:', re.IGNORECASE)


class ZabbixClient:
    def __init__(self):
        self.url = ZABBIX_URL
        self.auth_token = ZABBIX_API_TOKEN
        self._req_id = 0

    def _call(self, method, params=None):
        self._req_id += 1
        payload = {'jsonrpc': '2.0', 'method': method, 'params': params or {}, 'id': self._req_id}
        headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {self.auth_token}'}
        try:
            r = requests.post(self.url, headers=headers, json=payload, timeout=30)
            data = r.json()
            if 'error' in data:
                logger.error(f"Zabbix API error [{method}]: {data['error']}")
                return None
            return data.get('result')
        except Exception as e:
            logger.error(f"Zabbix API call failed [{method}]: {e}")
            return None

    def login(self):
        if self.auth_token:
            logger.info("Using API token authentication")
            return True
        logger.error("ZABBIX_API_TOKEN not set")
        return False

    def get_hosts(self):
        """Return hosts enriched with groups and tags for label building."""
        return self._call('host.get', {
            'output': ['hostid', 'host', 'name'],
            'selectInterfaces': ['ip'],
            'selectGroups':     ['name'],   # host groups → host_groups label
            'selectTags':       'extend',   # site / type / role tags
            'filter': {'status': 0},
        }) or []

    def get_items(self, hostids):
        """Fetch all enabled items for the given hosts.

        We no longer pre-filter by value_type: besides float(0)/uint(3), some
        SNMP/agent values (e.g. FortiGate hw sensor temperatures) are stored as
        char/text(1,2,4) yet are genuinely numeric. The export loop parses every
        lastvalue with float() and silently skips the ones that aren't numeric
        (versions, serials, status text), so every numeric series reaches VM.
        """
        return self._call('item.get', {
            'output': ['itemid', 'name', 'key_', 'lastvalue', 'lastclock', 'value_type'],
            'filter': {'status': 0},  # all enabled items; float() parse below decides
            'selectHosts': ['host', 'name'],
            'hostids': hostids,
        }) or []

    def get_triggers(self):
        return self._call('trigger.get', {
            'output': ['triggerid', 'description', 'priority', 'value', 'lastchange'],
            'selectHosts': ['host', 'name'],
            'filter': {'value': 1},
            'only_true': 1,
            'active': 1,
        }) or []


class VictoriaMetricsClient:
    def __init__(self):
        self.url = VM_URL

    def write_metrics(self, metrics):
        if not metrics:
            return True
        lines = []
        for m in metrics:
            name  = m['name']
            value = m['value']
            ts    = m.get('timestamp', int(time.time() * 1000))
            lbls  = m.get('labels', {})
            if lbls:
                lbl_str = ','.join(f'{k}="{_escape(v)}"' for k, v in lbls.items())
                lines.append(f'{name}{{{lbl_str}}} {value} {ts}')
            else:
                lines.append(f'{name} {value} {ts}')
        try:
            r = requests.post(
                f'{self.url}/api/v1/import/prometheus',
                headers={'Content-Type': 'text/plain'},
                data='\n'.join(lines),
                timeout=30,
            )
            if r.status_code in (200, 204):
                logger.debug(f"Wrote {len(metrics)} metrics to VM")
                return True
            logger.error(f"VM write failed {r.status_code}: {r.text[:200]}")
            return False
        except Exception as e:
            logger.error(f"VM write error: {e}")
            return False

    def health_check(self):
        try:
            return requests.get(f'{self.url}/health', timeout=5).status_code == 200
        except Exception:
            return False


def _escape(v):
    """Escape backslash and double-quote in label values."""
    return str(v).replace('\\', '\\\\').replace('"', '\\"')


def _sanitize(name):
    """Convert arbitrary string to a valid Prometheus metric name component."""
    s = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    if s and s[0].isdigit():
        s = '_' + s
    return re.sub(r'_+', '_', s).lower().strip('_')


def _extract_interface(item_name):
    """Return interface name from an LLD interface item name, or '' if not an IF item."""
    m = _IF_RE.match(item_name)
    return m.group(1).strip() if m else ''


def export_metrics(zabbix, vm):
    hosts = zabbix.get_hosts()
    if not hosts:
        logger.warning("No hosts returned from Zabbix")
        return

    # Build per-host metadata map
    host_meta = {}  # hostid → dict
    for h in hosts:
        groups = ','.join(g['name'] for g in (h.get('groups') or []))
        tags   = {t['tag']: t['value'] for t in (h.get('tags') or [])}
        iface  = (h.get('interfaces') or [{'ip': ''}])[0]
        host_meta[h['hostid']] = {
            'host':       h.get('host', ''),
            'host_name':  h.get('name', '')[:60],
            'host_ip':    iface.get('ip', ''),
            'host_groups': groups,
            'site':       tags.get('site', ''),
            'host_type':  tags.get('type', ''),
            'role':       tags.get('role', ''),
        }

    now_ms   = int(time.time() * 1000)
    metrics  = []

    # ── host_alive heartbeat ─────────────────────────────────────────────────
    # One metric per host with all metadata labels so label_values() queries
    # work across every host-based dashboard variable without any manual config.
    for h in hosts:
        m = host_meta[h['hostid']]
        metrics.append({
            'name': 'zabbix_host_alive',
            'value': 1,
            'timestamp': now_ms,
            'labels': {
                'host':        m['host'],
                'host_name':   m['host_name'],
                'host_ip':     m['host_ip'],
                'host_groups': m['host_groups'],
                'site':        m['site'],
                'host_type':   m['host_type'],
                'role':        m['role'],
                'source':      'zabbix',
            },
        })

    logger.info(f"Built host_alive metrics for {len(hosts)} hosts")

    # ── item metrics ─────────────────────────────────────────────────────────
    host_ids = [h['hostid'] for h in hosts]
    items    = zabbix.get_items(host_ids)
    logger.info(f"Retrieved {len(items)} items (all value types; non-numeric skipped on parse)")

    skipped = 0
    for item in items:
        try:
            last = item.get('lastvalue', '')
            if not last:
                skipped += 1
                continue
            value = float(last)
        except (ValueError, TypeError):
            skipped += 1
            continue

        item_hosts = item.get('hosts') or []
        if not item_hosts:
            skipped += 1
            continue

        # Match item back to host metadata
        hostname = item_hosts[0].get('host', 'unknown')
        # Find hostid for this item (needed to look up meta)
        meta = next(
            (host_meta[hid] for hid, m in host_meta.items() if m['host'] == hostname),
            {'host': hostname, 'host_name': hostname, 'host_ip': '',
             'host_groups': '', 'site': '', 'host_type': '', 'role': ''}
        )

        iface_label = _extract_interface(item.get('name', ''))
        metric_name = f"zabbix_{_sanitize(item.get('key_', item.get('name', 'unknown')))}"

        labels = {
            'host':        meta['host'],
            'host_name':   meta['host_name'],
            'host_groups': meta['host_groups'],
            'site':        meta['site'],
            'host_type':   meta['host_type'],
            'role':        meta['role'],
            'item':        item.get('name', '')[:60],
            'source':      'zabbix',
        }
        if iface_label:
            labels['tag_interface'] = iface_label

        metrics.append({
            'name':      metric_name,
            'value':     value,
            'timestamp': int(item.get('lastclock', time.time())) * 1000,
            'labels':    labels,
        })

    logger.info(f"Built {len(metrics) - len(hosts)} item metrics ({skipped} skipped)")

    # ── trigger metrics ───────────────────────────────────────────────────────
    triggers = zabbix.get_triggers()
    priority_names = {0:'not_classified',1:'information',2:'warning',
                      3:'average',4:'high',5:'disaster'}
    counts = {p: 0 for p in priority_names}
    for t in triggers:
        p = int(t.get('priority', 0))
        counts[p] = counts.get(p, 0) + 1

    for p, cnt in counts.items():
        metrics.append({
            'name':   'zabbix_active_triggers',
            'value':  cnt,
            'labels': {'priority': priority_names[p], 'source': 'zabbix'},
        })
    metrics.append({
        'name':   'zabbix_total_problems',
        'value':  len(triggers),
        'labels': {'source': 'zabbix'},
    })

    # ── write all metrics ─────────────────────────────────────────────────────
    if metrics:
        vm.write_metrics(metrics)
        logger.info(f"Exported {len(metrics)} total metrics to VictoriaMetrics")
    else:
        logger.warning("No metrics to export")


def main():
    logger.info(f"Starting Zabbix→VictoriaMetrics exporter  interval={EXPORT_INTERVAL}s")
    logger.info(f"Zabbix: {ZABBIX_URL}   VM: {VM_URL}")

    zabbix = ZabbixClient()
    vm     = VictoriaMetricsClient()

    logger.info("Waiting 30s for services to start...")
    time.sleep(30)

    while True:
        try:
            if not vm.health_check():
                logger.warning("VictoriaMetrics not healthy, retrying in 10s...")
                time.sleep(10)
                continue
            if not zabbix.auth_token:
                if not zabbix.login():
                    logger.warning("No API token configured, retrying in 30s...")
                    time.sleep(30)
                    continue
            export_metrics(zabbix, vm)
        except Exception as e:
            logger.error(f"Export loop error: {e}", exc_info=True)
        time.sleep(EXPORT_INTERVAL)


if __name__ == '__main__':
    main()
