#!/usr/bin/env python3
"""
Zabbix API Client for GLPI Integration
Handles event acknowledgment, host inventory retrieval, and tag management
"""

import logging
import requests
from typing import Optional, Dict, Any, List

from config import ZABBIX_URL, ZABBIX_USER, ZABBIX_PASSWORD, ZABBIX_API_TOKEN

logger = logging.getLogger(__name__)


class ZabbixClient:
    """Zabbix JSON-RPC API Client"""
    
    def __init__(self):
        self.url = ZABBIX_URL
        self.auth_token = None
        self._request_id = 1
        self._request_timeout = 30
        
    def _api_request(self, method: str, params: Dict[str, Any] = None) -> Optional[Any]:
        """
        Make a Zabbix API request
        
        Args:
            method: API method name (e.g., 'event.acknowledge')
            params: Method parameters
            
        Returns:
            API response result or None on error
        """
        try:
            payload = {
                'jsonrpc': '2.0',
                'method': method,
                'params': params or {},
                'id': self._request_id,
            }
            self._request_id += 1
            
            headers = {'Content-Type': 'application/json-rpc'}
            
            # Zabbix 7.x uses Authorization header instead of auth in payload
            if self.auth_token and method != 'user.login':
                headers['Authorization'] = f'Bearer {self.auth_token}'
            
            # Use API token in header if configured (preferred for Zabbix 7.x)
            if ZABBIX_API_TOKEN and method != 'user.login':
                headers['Authorization'] = f'Bearer {ZABBIX_API_TOKEN}'
            
            response = requests.post(
                self.url,
                json=payload,
                headers=headers,
                timeout=self._request_timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                if 'error' in data:
                    logger.error(f"Zabbix API error: {data['error']}")
                    return None
                return data.get('result')
            else:
                logger.error(f"Zabbix API HTTP error: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Zabbix API request failed: {e}")
            return None
    
    def login(self) -> bool:
        """
        Authenticate with Zabbix API
        
        Returns:
            True if successful
        """
        try:
            # If using API token, no login needed
            if ZABBIX_API_TOKEN:
                logger.info("Using Zabbix API token authentication")
                return True
            
            # Zabbix 7.x uses 'username', older versions use 'user'
            result = self._api_request('user.login', {
                'username': ZABBIX_USER,
                'password': ZABBIX_PASSWORD,
            })
            
            if result:
                self.auth_token = result
                logger.info("Zabbix login successful")
                return True
            return False
            
        except Exception as e:
            logger.error(f"Zabbix login failed: {e}")
            return False
    
    def logout(self):
        """Logout from Zabbix API"""
        if self.auth_token and not ZABBIX_API_TOKEN:
            try:
                self._api_request('user.logout', {})
            except Exception:
                pass
            self.auth_token = None
    
    def __enter__(self):
        """Context manager entry"""
        self.login()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.logout()
    
    # =========================================================================
    # Event Operations
    # =========================================================================
    
    def acknowledge_event(
        self,
        event_ids: List[str],
        message: str = "Acknowledged by GLPI Integration",
        action: int = 6,  # Default: Ack + Message
        severity: Optional[int] = None
    ) -> bool:
        """
        Acknowledge Zabbix event(s)
        
        Args:
            event_ids: List of event IDs to acknowledge
            message: Acknowledgment message
            action: Bitmask of actions:
                    1 = Close problem
                    2 = Acknowledge event
                    4 = Add message
                    8 = Change severity
                    16 = Unacknowledge event
                    32 = Suppress event
                    64 = Unsuppress event
                    128 = Change event rank to cause
                    256 = Change event rank to symptom
            severity: New severity (if action includes 8)
            
        Returns:
            True if successful
        """
        try:
            if not self.auth_token and not ZABBIX_API_TOKEN:
                if not self.login():
                    return False
            
            params = {
                'eventids': event_ids if isinstance(event_ids, list) else [event_ids],
                'message': message,
                'action': action,
            }
            
            if severity is not None and (action & 8):
                params['severity'] = severity
            
            result = self._api_request('event.acknowledge', params)
            
            if result:
                logger.info(f"Acknowledged events: {event_ids}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"Event acknowledge failed: {e}")
            return False
    
    def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Get event details by ID"""
        try:
            if not self.auth_token and not ZABBIX_API_TOKEN:
                if not self.login():
                    return None
            
            result = self._api_request('event.get', {
                'eventids': [event_id],
                'output': 'extend',
                'selectTags': 'extend',
                'selectHosts': ['hostid', 'name'],
            })
            
            if result:
                return result[0] if result else None
            return None
            
        except Exception as e:
            logger.error(f"Get event failed: {e}")
            return None
    
    def get_problem(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Get problem details by event ID"""
        try:
            if not self.auth_token and not ZABBIX_API_TOKEN:
                if not self.login():
                    return None
            
            result = self._api_request('problem.get', {
                'eventids': [event_id],
                'output': 'extend',
                'selectTags': 'extend',
            })
            
            if result:
                return result[0] if result else None
            return None
            
        except Exception as e:
            logger.error(f"Get problem failed: {e}")
            return None
    
    # =========================================================================
    # Host & Inventory Operations
    # =========================================================================
    
    def get_hosts(self, with_inventory: bool = True) -> List[Dict[str, Any]]:
        """
        Get all monitored hosts with optional inventory data
        
        Args:
            with_inventory: Include inventory data
            
        Returns:
            List of host objects
        """
        try:
            if not self.auth_token and not ZABBIX_API_TOKEN:
                if not self.login():
                    return []
            
            params = {
                'output': ['hostid', 'host', 'name', 'status'],
                'selectInterfaces': ['ip', 'dns', 'type'],
                'selectTags': ['tag', 'value'],
                'filter': {'status': 0},  # Only enabled hosts
            }

            if with_inventory:
                params['selectInventory'] = 'extend'
            
            result = self._api_request('host.get', params)
            return result or []
            
        except Exception as e:
            logger.error(f"Get hosts failed: {e}")
            return []
    
    def get_host_by_name(self, hostname: str, with_inventory: bool = True) -> Optional[Dict[str, Any]]:
        """
        Get host by hostname or visible name
        
        Args:
            hostname: The host's technical name or visible name
            with_inventory: Include inventory data
            
        Returns:
            Host object or None
        """
        try:
            if not self.auth_token and not ZABBIX_API_TOKEN:
                if not self.login():
                    return None
            
            params = {
                'output': ['hostid', 'host', 'name', 'status'],
                'selectInterfaces': ['ip', 'dns', 'type'],
                'filter': {'host': hostname},
            }
            
            if with_inventory:
                params['selectInventory'] = 'extend'
            
            result = self._api_request('host.get', params)
            
            if result:
                return result[0] if result else None
            
            # Try by visible name
            params['filter'] = {'name': hostname}
            result = self._api_request('host.get', params)
            
            return result[0] if result else None
            
        except Exception as e:
            logger.error(f"Get host by name failed: {e}")
            return None
    
    def get_host_by_id(self, host_id: str, with_inventory: bool = True) -> Optional[Dict[str, Any]]:
        """Get host by ID"""
        try:
            if not self.auth_token and not ZABBIX_API_TOKEN:
                if not self.login():
                    return None
            
            params = {
                'hostids': [host_id],
                'output': ['hostid', 'host', 'name', 'status'],
                'selectInterfaces': ['ip', 'dns', 'type'],
            }
            
            if with_inventory:
                params['selectInventory'] = 'extend'
            
            result = self._api_request('host.get', params)
            return result[0] if result else None
            
        except Exception as e:
            logger.error(f"Get host by ID failed: {e}")
            return None
    
    # =========================================================================
    # Tag Operations (for storing GLPI ticket ID)
    # =========================================================================
    
    def add_event_tag(self, event_id: str, tag: str, value: str) -> bool:
        """
        Add a tag to an event (via acknowledge with suppress action)
        Note: Zabbix 6.0+ supports event tags via acknowledge
        
        For older versions, store the mapping in the database instead.
        """
        try:
            # In Zabbix 6.0+, we can use event.acknowledge with a message
            # that includes the ticket info. The actual tag storage
            # is done via our local database.
            return True
        except Exception as e:
            logger.error(f"Add event tag failed: {e}")
            return False
    
    # =========================================================================
    # Trigger Operations
    # =========================================================================
    
    def get_trigger(self, trigger_id: str) -> Optional[Dict[str, Any]]:
        """Get trigger details by ID"""
        try:
            if not self.auth_token and not ZABBIX_API_TOKEN:
                if not self.login():
                    return None
            
            result = self._api_request('trigger.get', {
                'triggerids': [trigger_id],
                'output': 'extend',
                'selectHosts': ['hostid', 'name'],
            })
            
            return result[0] if result else None
            
        except Exception as e:
            logger.error(f"Get trigger failed: {e}")
            return None
    
    def get_network_interfaces(self, hostid: str) -> Dict[str, Any]:
        """
        Parse network interfaces for a host from Zabbix item names.

        Handles two naming conventions:
          SNMP / Windows agent:
            "Interface {desc}({alias}): {metric}"   ← alias is the short connection name
            The {desc} may itself contain (...) groups (Windows NIC descriptions),
            so we use a greedy match to capture the LAST (alias) group.
          Linux agent (no alias group):
            "Interface eth0: {metric}"

        Returns { port_name: {alias, oper_status, speed, duplex,
                              in_bytes, out_bytes, in_errors, out_errors} }
        where port_name is:
          - the short alias/connection name when one is present (Windows)
          - the interface name directly for Linux / SNMP ports with no alias
        """
        import re
        items = self._api_request('item.get', {
            'output': ['name', 'key_', 'lastvalue'],
            'hostids': [hostid],
            'search': {'name': 'Interface '},
            'limit': 500,
        })
        _METRIC = {
            'Operational status':           'oper_status',
            'Speed':                        'speed',
            'Duplex status':                'duplex',
            'Bits received':                'in_bytes',
            'Bits sent':                    'out_bytes',
            'Inbound packets with errors':  'in_errors',
            'Outbound packets with errors': 'out_errors',
        }
        # Greedy first group so the LAST (...) captures the alias even when the
        # NIC description contains its own parenthesised sub-strings.
        pat_alias    = re.compile(r'^Interface\s+(.+)\(([^\)]*)\):\s*(.+)$')
        # Linux / agent items with no alias group at all.
        pat_no_alias = re.compile(r'^Interface\s+([^:(]+):\s*(.+)$')

        by_iface: Dict[str, Any] = {}
        # Track whether any oper_status item came from Linux /sys/class/net/operstate.
        # Linux kernel IF_OPER_* : 2=DOWN, 6=UP — opposite of SNMP (1=up).
        linux_oper_keys: set = set()

        for item in (items or []):
            item_name = item.get('name', '')
            item_key  = item.get('key_', '')
            raw = item.get('lastvalue') or ''

            m = pat_alias.match(item_name)
            if m:
                full_desc = m.group(1).strip()
                alias     = m.group(2).strip()
                metric    = m.group(3).strip()
                port_name = alias if alias else full_desc
                iface_desc = full_desc if alias else ''
            else:
                m2 = pat_no_alias.match(item_name)
                if not m2:
                    continue
                port_name  = m2.group(1).strip()
                metric     = m2.group(2).strip()
                iface_desc = ''

            entry = by_iface.setdefault(port_name, {
                'alias': iface_desc, 'oper_status': 0, 'speed': 0,
                'duplex': 0, 'in_bytes': 0, 'out_bytes': 0,
                'in_errors': 0, 'out_errors': 0,
            })

            mapped_key = _METRIC.get(metric)
            if mapped_key:
                try:
                    val = int(float(raw))
                    entry[mapped_key] = val
                    # Mark Linux-style oper_status items for later normalisation.
                    if mapped_key == 'oper_status' and 'operstate' in item_key:
                        linux_oper_keys.add(port_name)
                except (ValueError, TypeError):
                    pass

        # Normalise Linux agent oper values to SNMP/GLPI convention (1=up, 2=down).
        # Linux kernel IF_OPER_UP=6, IF_OPER_DOWN=2 — we remap 6→1 for GLPI.
        for pname in linux_oper_keys:
            if pname in by_iface:
                raw_oper = by_iface[pname]['oper_status']
                by_iface[pname]['oper_status'] = 1 if raw_oper == 6 else 2

        return by_iface

    def get_disk_volumes(self, hostid: str) -> List[Dict[str, Any]]:
        """
        Return distinct disk volumes for a host from Zabbix filesystem items.

        Parses vfs.fs.dependent.* items.  Deduplicates by (totalsize, usedsize)
        so that container bind mounts sharing the same underlying filesystem
        only appear once.  Volumes with totalsize == 0 are skipped.

        Returns list of dicts:
            { name, mountpoint, fstype, totalsize_mb, freesize_mb }
        where sizes are in MiB (as GLPI Item_Disk expects).
        """
        import json as _json
        import re as _re

        items = self._api_request('item.get', {
            'output': ['key_', 'lastvalue'],
            'hostids': [hostid],
            'search': {'key_': 'vfs.fs.dependent'},
            'limit': 500,
        }) or []

        # Parse per-path metrics
        by_path: Dict[str, Dict[str, Any]] = {}
        for item in items:
            k   = item.get('key_', '')
            val = item.get('lastvalue') or ''

            # vfs.fs.dependent[path,subkey]  (data JSON, readonly)
            m = _re.match(r'^vfs\.fs\.dependent\[(.+),(data|readonly)\]$', k)
            if m:
                path, sub = m.group(1), m.group(2)
                entry = by_path.setdefault(path, {'total': 0, 'free': 0, 'fstype': ''})
                if sub == 'data' and val:
                    try:
                        d = _json.loads(val)
                        entry['fstype'] = d.get('fstype', '')
                        b = d.get('bytes', {})
                        if b.get('total'):
                            entry['total_json'] = int(b['total'])
                        if b.get('free') is not None:
                            entry['free_json'] = int(b['free'])
                    except Exception:
                        pass
                continue

            # vfs.fs.dependent.size[path,subkey]
            m2 = _re.match(r'^vfs\.fs\.dependent\.\w+\[(.+),(total|free|used|pused|pfree)\]$', k)
            if m2:
                path, sub = m2.group(1), m2.group(2)
                entry = by_path.setdefault(path, {'total': 0, 'free': 0, 'fstype': ''})
                try:
                    v = int(float(val))
                    if sub == 'total':
                        entry['total'] = v
                    elif sub == 'free':
                        entry['free'] = v
                except (ValueError, TypeError):
                    pass

        # Paths to skip: temp dirs, pseudo-filesystems, GUID-named error paths
        _SKIP = (
            r'\\Temp\\', r'/proc/', r'/sys/', r'/dev/', r'/run/',
            r'\{[0-9a-fA-F\-]{30,}\}',   # GUID-like Windows error-report paths
        )
        _skip_re = _re.compile('|'.join(_SKIP))

        # Deduplicate by (total, free) — same underlying filesystem
        seen: Dict[tuple, str] = {}
        result: List[Dict[str, Any]] = []
        for path in sorted(by_path, key=len):   # shorter paths first (canonical)
            if _skip_re.search(path):
                continue
            data = by_path[path]
            total = data.get('total_json') or data.get('total', 0)
            free  = data.get('free_json')  or data.get('free',  0)
            if total == 0:
                continue
            sig = (total, total - free)   # (total, used) as dedup key
            if sig in seen:
                continue
            seen[sig] = path
            result.append({
                'name':         path,
                'mountpoint':   path,
                'fstype':       data.get('fstype', ''),
                'totalsize_mb': total // (1024 * 1024),
                'freesize_mb':  free  // (1024 * 1024),
            })
        return result

    def get_device_firmware(self, hostid: str) -> Dict[str, str]:
        """
        Retrieve firmware/OS info for network devices (switches, firewalls) from
        SNMP items when the Zabbix inventory os/os_short fields are empty.

        Returns a dict with keys: os_name, version, company, model.
        'model' is a clean model string suitable for GLPI (extracted from
        sys_descr when inventory.model is blank).
        """
        import re
        keys = [
            'sysFirmwareVersion',
            'system.hw.firmware',
            'system.descr[sysDescr.0]',
            'system.sw.os[version]',
        ]
        items = self._api_request('item.get', {
            'output': ['key_', 'lastvalue'],
            'hostids': [hostid],
            'filter': {'key_': keys},
        }) or []
        by_key = {i['key_']: (i.get('lastvalue') or '').strip() for i in items}

        fw_ver    = by_key.get('sysFirmwareVersion') or by_key.get('system.hw.firmware') or ''
        sys_descr = by_key.get('system.descr[sysDescr.0]') or ''
        combined  = (sys_descr + ' ' + fw_ver).lower()

        model = ''

        if 'fortinet' in combined or 'fortigate' in combined or 'fortios' in combined:
            os_name = 'FortiOS'
            company = 'Fortinet'
            m = re.search(r'v?(\d+\.\d+\.\d+[\w.\-]*)', sys_descr or fw_ver)
            version = m.group(1) if m else fw_ver
            # "Fortinet Firewall FortiGate-60F v7.4.11,..." → model "FortiGate-60F"
            mm = re.search(r'(FortiGate[-\w]+)', sys_descr, re.IGNORECASE)
            if mm:
                model = mm.group(1)
        elif 'cisco' in combined or 'ios' in combined:
            os_name = 'Cisco IOS'
            company = 'Cisco'
            m = re.search(r'[Vv]ersion\s+([\w.\(\)\-]+)', sys_descr or fw_ver)
            version = m.group(1) if m else fw_ver
            mm = re.search(r'(C\d{4}\w*)', sys_descr)
            if mm:
                model = mm.group(1)
        elif any(k in combined for k in ('dgs-', 'dgs ', 'des-', 'dlink', 'd-link', 'ws6-dgs')):
            os_name = 'D-Link Firmware'
            company = 'D-Link'
            m = re.search(r'(\d+\.\d+[\.\w]*)\s*$', (sys_descr + ' ' + fw_ver).strip())
            version = m.group(1) if m else fw_ver
            # Extract model: "WS6-DGS-1210-28P/F1 6.32.B021" or "DGS-1210-12TS/ME/B1"
            mm = re.search(r'(?:WS\d+-)?([Dd][Gg][Ss]-[\w/]+|[Dd][Ee][Ss]-[\w/]+)', sys_descr)
            if mm:
                model = mm.group(1).upper()
            elif sys_descr and not fw_ver:
                model = re.sub(r'\s+\d+\.\d+.*$', '', sys_descr).strip()
        elif 'hpe' in combined or 'hp ' in combined or 'procurve' in combined or 'msa' in combined:
            os_name = 'HP ProCurve Firmware' if 'procurve' in combined else 'HPE Firmware'
            company = 'HPE'
            version = fw_ver
            model = re.sub(r'\s*\(.*', '', sys_descr).strip() if sys_descr else ''
        elif 'sophos' in combined:
            os_name = 'Sophos Firmware'
            company = 'Sophos'
            version = fw_ver
        elif sys_descr:
            os_name = sys_descr[:64]
            company = ''
            version = fw_ver
            model = sys_descr[:64]
        else:
            return {}

        return {
            'os_name': os_name,
            'version': version or '',
            'company': company,
            'model':   model or '',
        }

    def get_snmp_interface(self, hostid: str) -> Optional[Dict[str, Any]]:
        """
        Return the first SNMP interface details for a host, or None if the host
        has no SNMP interface.

        Returned dict keys: ip, port, version, community, securityname,
        contextname (and other details fields from Zabbix).
        """
        ifaces = self._api_request('host.get', {
            'output': ['hostid'],
            'hostids': [hostid],
            'selectInterfaces': ['type', 'ip', 'dns', 'port', 'details'],
        }) or []
        for host in ifaces:
            for iface in (host.get('interfaces') or []):
                if str(iface.get('type')) == '2':   # type 2 = SNMP
                    det = iface.get('details') or {}
                    return {
                        'ip':           iface.get('ip', ''),
                        'port':         iface.get('port', '161'),
                        'version':      str(det.get('version', '2')),
                        'community':    det.get('community', 'public'),
                        'securityname': det.get('securityname', ''),
                        'contextname':  det.get('contextname', ''),
                    }
        return None

    def get_sysObjectID(self, hostid: str) -> str:
        """
        Return the SNMP sysObjectID value for the host (used as UUID fallback
        for network equipment that has no hardware UUID).
        """
        items = self._api_request('item.get', {
            'output': ['lastvalue'],
            'hostids': [hostid],
            'filter': {'key_': 'system.objectid[sysObjectID.0]'},
        }) or []
        return (items[0].get('lastvalue') or '') if items else ''

    # =========================================================================
    # API Info
    # =========================================================================

    def get_api_version(self) -> Optional[str]:
        """Get Zabbix API version"""
        try:
            result = self._api_request('apiinfo.version', {})
            return result
        except Exception:
            return None
