# Archived provisioning scripts

One-shot scripts, already applied. **Nothing schedules or imports them** — no cron,
no systemd timer, no cross-imports. Their output is persisted Zabbix DB state.
Archived 2026-07-09; safe to keep here indefinitely.

Kept for reproducibility: this directory is not under version control, so these
files are the only written record of how the live config was built.

| Script | What it created (verified live in Zabbix) |
|---|---|
| `zabbix_parent_child.py` | 20 hierarchical `Site/Type` host groups |
| `zabbix_tag_devices.py` | site/type/role tags — superseded by `../zabbix_autotag.py` |
| `zabbix_trigger_deps.py` | 6772 trigger dependencies (topology alert suppression) |
| `create_sonic_dashboard.py` | dashboard "SONIC Site Overview" |
| `create_honeycomb_dashboard.py` | dashboards "Honeycomb / SONIC — CPU, Memory, Disk" |
| `create_bandwidth_dashboard.py` | dashboard "Honeycomb / Firewall — Bandwidth" |
| `create_combined_honeycomb_dashboard.py` | dashboard "Honeycomb / All" |
| `create_interface_graph_dashboard.py` | dashboard "Interface Traffic — HO Sophos lan" |
| `configure_server_threshold_alerts.py` | server CPU/mem/disk threshold triggers |
| `configure_hardware_sensor_alerts.py` | hardware sensor triggers |
| `configure_network_iface_alerts.py` | network interface triggers |
| `configure_storage_firewall_alerts.py` | storage + firewall triggers |
| `configure_website_alerts.py` | web-scenario triggers |

Re-running any of these is **not** idempotent in general — they were written to
apply once against a known host set. Read before executing.

All read `ZABBIX_API_TOKEN` from `/etc/zabbix-stack/stack.env` (some fall back to a
`./.env` that no longer exists), and target `https://localhost/zabbix/api_jsonrpc.php`.

## Still in the parent directory (do not archive)

- `zabbix_autotag.py` — **live**, run hourly by `zabbix-autotag.timer`
- `sonic_lockdown.sql` — **live**, source of 4 triggers on `usrgrp`/`role`/`proxy`/`proxy_group`
- `create_ill_triggers.py` — ILL/Msour trigger work still open
- `zabbix_audit.py`, `zabbix_actions_check.py`, `zabbix_items_check.py`,
  `zabbix_items_stats.py` — read-only diagnostics (`.get` calls only)

Full snapshot of all 20 scripts as of archiving:
`/root/zabbix-stack-scripts-20260709_224217.tar.gz` (mode 600)
