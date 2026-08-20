#!/usr/bin/env python3
"""
Zabbix to GLPI Inventory Synchronization
Pulls host inventory from Zabbix and syncs to GLPI as Computer assets

Run via cron or as a scheduled task:
    */60 * * * * /usr/bin/python3 /app/inventory_sync.py >> /var/log/inventory_sync.log 2>&1
"""

import os
import re
import sys
import logging
import argparse
from datetime import datetime
from typing import Dict, Any, List, Optional

# Zabbix host status → GLPI State name
_ZABBIX_STATUS_TO_GLPI_STATE = {
    '0': 'Production',
    '1': 'Retired',
}

# Zabbix site tag value → GLPI Location name (must match existing GLPI locations)
_SITE_TAG_TO_LOCATION = {
    'SEZ': 'SEZ_Pithampur',
    'MDEEP': 'Mdeep',
    'MSOUR': 'Msour',
    'HO': 'Head Office',
    'SONIC': 'Sonic Biochem',
    'PAT': 'Patalganga',
}

# Lowercase keyword → canonical vendor name
# Order matters: longer/more-specific strings first to avoid false matches.
_VENDOR_KEYWORDS = {
    'fortinet': 'Fortinet',
    'fortigate': 'Fortinet',
    'fortiswitch': 'Fortinet',
    'fortiwifi': 'Fortinet',
    'cisco': 'Cisco',
    'nxos': 'Cisco',
    'nx-os': 'Cisco',
    'mikrotik': 'MikroTik',
    'sophos': 'Sophos',
    'sonicwall': 'SonicWall',
    'palo alto': 'Palo Alto Networks',
    'juniper': 'Juniper Networks',
    'hewlett': 'HP',
    'hp ': 'HP',
    'hpe ': 'HPE',
    'dell': 'Dell',
    'lenovo': 'Lenovo',
    'microsoft': 'Microsoft',
    'vmware': 'VMware',
    'd-link': 'D-Link',
    'dlink': 'D-Link',
    # D-Link model-number prefixes (DGS = D-Link Gigabit Switch,
    # DES = D-Link Ethernet Switch, DSS = D-Link Smart Switch)
    'dgs-': 'D-Link',
    'des-': 'D-Link',
    'dss-': 'D-Link',
    'ws6-dgs': 'D-Link',
    'readynas': 'NETGEAR',
    'netgear': 'NETGEAR',
    'ubiquiti': 'Ubiquiti',
    'aruba': 'Aruba',
    'extreme': 'Extreme Networks',
    'ruckus': 'Ruckus',
    'windows': 'Microsoft',
    'ubuntu': 'Canonical',
    'debian': 'Debian',
    'oracle linux': 'Oracle',
    'oracle': 'Oracle',
    'red hat': 'Red Hat',
}

# Zabbix type/role tag → GLPI asset type dropdown name, keyed by GLPI itemtype
_DEVICE_TYPE_MAP = {
    'Computer': {
        'server': 'Server',
        'hypervisor': 'Server',
        'workstation': 'Desktop',
        'desktop': 'Desktop',
        'laptop': 'Laptop',
        'vdi': 'Virtual Machine',
        'vm': 'Virtual Machine',
        'internet-vm': 'Virtual Machine',
        'standby-server': 'Server',
        'app-server': 'Server',
        'db-server': 'Server',
        'rds': 'Server',
        'vpn': 'Server',
        'mail': 'Server',
        'vms': 'Server',
        'security': 'Server',
        'monitoring': 'Server',
        'backup': 'Server',
        'ad-dns': 'Server',
    },
    'NetworkEquipment': {
        'switch': 'Switch',
        'core-switch': 'Switch',
        'dept-switch': 'Switch',
        'san-switch': 'Switch',
        'cctv-switch': 'Switch',
        'router': 'Router',
        'firewall': 'Firewall',
        'primary-fw': 'Firewall',
        'secondary-fw': 'Firewall',
        'internet-proxy': 'Firewall',
        'ap': 'Wifi Access Point',
        'wifi': 'Wifi Access Point',
        'nas': 'Storage',
        'san': 'Storage',
        'storage': 'Storage',
    },
    'Printer': {
        'printer': 'Printer',
        'mfp': 'Multi-Function Printer',
    },
}

# GLPI type dropdown itemtype per asset itemtype
TYPE_FIELD = {
    'Computer': ('computertypes_id', 'ComputerType'),
    'NetworkEquipment': ('networkequipmenttypes_id', 'NetworkEquipmentType'),
    'Printer': ('printertypes_id', 'PrinterType'),
}


def _get_tags(zabbix_host: Dict[str, Any]) -> Dict[str, str]:
    """Convert Zabbix tags list to {tag_name: value} dict (lowercased names)."""
    return {t['tag'].lower(): t.get('value', '') for t in (zabbix_host.get('tags') or [])}


def _extract_vendor_from_model(model_str: str) -> str:
    """Extract manufacturer from a verbose model string when the vendor field is blank."""
    low = (model_str or '').lower()
    for keyword, name in _VENDOR_KEYWORDS.items():
        if keyword in low:
            return name
    return ''


def _extract_vendor_from_os(os_str: str) -> str:
    """Infer manufacturer from OS string (for computers with no vendor in inventory)."""
    low = (os_str or '').lower()
    for keyword, name in _VENDOR_KEYWORDS.items():
        if keyword in low:
            return name
    return ''


def _clean_model_name(model_str: str) -> str:
    """Strip firmware/version noise from verbose model strings for a clean GLPI model name."""
    s = (model_str or '').strip()
    if not s:
        return ''
    # Strip trailing "(GA.M)" style qualifiers and build metadata
    s = re.sub(r'\s*\([^)]*\)\s*$', '', s)
    # Strip trailing "vX.Y.Z,...build..." version strings (with "v" prefix)
    s = re.sub(r'\s+v\d+\.\d+[\S,]*.*$', '', s)
    # Strip trailing version strings without "v" prefix (e.g. "6.32.B021")
    s = re.sub(r'\s+\d+\.\d+[\w.\-]*$', '', s)
    # Strip verbose vendor+category prefix (e.g. "Fortinet Firewall FortiGate-60F" → "FortiGate-60F")
    s = re.sub(
        r'^(?:Fortinet|Cisco|MikroTik|Sophos|SonicWall|Juniper|Aruba|Ruckus|Ubiquiti|D-Link|Netgear)\s+'
        r'(?:Firewall|Switch|Router|Wireless|AP|Controller|Server|Appliance|Hardware|Fast Ethernet Switch'
        r'|Gigabit Switch|Ethernet Switch)\s+',
        '', s, flags=re.IGNORECASE,
    )
    # Strip D-Link "WS6-" hardware-revision prefix (leaves the real model "DGS-...")
    s = re.sub(r'^WS\d+-', '', s, flags=re.IGNORECASE)
    # Strip trailing description words from D-Link / generic strings
    # e.g. "D-Link DES-3026 Fast Ethernet Switch" → "DES-3026"
    # e.g. "Dlink DES-3026 Fast Ethernet Switch" → "DES-3026"
    m_dlink = re.search(r'\b([Dd][GgEeSs]{2}[-\w/]+)', s)
    if m_dlink:
        return m_dlink.group(1).upper()
    # Strip "OS" suffix for NAS OS strings ("ReadyNAS OS" → "ReadyNAS")
    s = re.sub(r'\s+OS$', '', s, flags=re.IGNORECASE)
    # Collapse redundant spaces
    s = re.sub(r'\s{2,}', ' ', s).strip()
    return s[:120] or model_str[:120]


def _parse_os_details(os_str: str) -> Dict[str, str]:
    """
    Extract version, architecture, kernel, edition, and company from a raw OS string.
    Returns keys: arch, version, kernel, edition, company.
    """
    result: Dict[str, str] = {}
    s = (os_str or '').strip()
    if not s:
        return result
    low = s.lower()

    # Architecture
    for pattern, arch in [('x86_64', 'x86_64'), ('amd64', 'x86_64'),
                           ('i386', 'i386'), ('i686', 'i386'),
                           ('arm64', 'ARM64'), ('aarch64', 'ARM64')]:
        if pattern in low:
            result['arch'] = arch
            break

    if 'windows' in low:
        result['company'] = 'Microsoft'
        # Edition
        for ed in ('Datacenter', 'Standard', 'Enterprise', 'Professional', 'Pro',
                   'Home', 'Education', 'Ultimate'):
            if ed.lower() in low:
                result['edition'] = ed if ed != 'Professional' else 'Pro'
                break
        # Build version (e.g. "Build 17763.8880")
        m = re.search(r'Build\s+(\d+\.\d+)', s, re.IGNORECASE)
        if m:
            result['version'] = m.group(1)
            result['kernel'] = 'NT 10.0.' + m.group(1)
        else:
            m = re.search(r'(\d{5}\.\d+)', s)
            if m:
                result['version'] = m.group(1)
                result['kernel'] = 'NT 10.0.' + m.group(1)

    elif 'linux' in low:
        # Kernel string (e.g. "6.17.0-1016-oracle")
        m = re.search(r'[Ll]inux(?:\s+version)?\s+([\d][\w.\-]+)', s)
        if m:
            kernel = m.group(1)[:80]
            result['version'] = kernel
            result['kernel'] = kernel
        # Distribution → company
        dist_company = [
            ('ubuntu', 'Canonical'), ('debian', 'Debian'), ('centos', 'CentOS'),
            ('red hat', 'Red Hat'), ('rhel', 'Red Hat'), ('fedora', 'Fedora'),
            ('suse', 'SUSE'), ('rocky', 'Rocky Linux'), ('alma', 'AlmaLinux'),
            ('oracle', 'Oracle'), ('freebsd', 'FreeBSD Foundation'),
        ]
        for kw, co in dist_company:
            if kw in low:
                result['company'] = co
                break
        else:
            result['company'] = 'Linux'

    elif any(k in low for k in ('cisco', 'nx-os', 'nxos', 'ios')):
        result['company'] = 'Cisco'
        m = re.search(r'[Vv]ersion\s+([\w.\(\)\-]+)', s)
        if m:
            result['version'] = m.group(1)
            result['kernel'] = m.group(1)

    elif 'fortigate' in low or 'fortios' in low or 'fortigate' in low:
        result['company'] = 'Fortinet'
        m = re.search(r'v?([\d]+\.[\d]+\.[\d]+[\w\-]*)', s)
        if m:
            result['version'] = m.group(1)

    return result

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    LOG_LEVEL, LOG_FORMAT, ZABBIX_TO_GLPI_FIELD_MAP,
    INVENTORY_SYNC_ENABLED
)
from glpi_client import GLPIClient
from zabbix_client import ZabbixClient
from database import (
    init_database, save_asset_mapping, get_glpi_asset_by_host_id,
    start_sync_session, complete_sync_session
)

# Configure logging
logging.basicConfig(level=getattr(logging, LOG_LEVEL), format=LOG_FORMAT)
logger = logging.getLogger(__name__)


# Per-itemtype name of the GLPI "model" foreign key + its dropdown itemtype.
MODEL_FIELD = {
    'Computer': ('computermodels_id', 'ComputerModel'),
    'NetworkEquipment': ('networkequipmentmodels_id', 'NetworkEquipmentModel'),
    'Printer': ('printermodels_id', 'PrinterModel'),
}


def map_inventory_fields(zabbix_host: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map Zabbix host inventory to direct GLPI asset fields (name, serial,
    otherserial, contact, contact_num) plus a rich provenance comment.
    Structured dropdowns (model / manufacturer / location / status / type)
    are resolved separately in sync_host_to_glpi() via resolve_structured_fields().
    """
    glpi_data: Dict[str, Any] = {}
    host_name = zabbix_host.get('name') or zabbix_host.get('host', '')
    glpi_data['name'] = host_name

    inventory = zabbix_host.get('inventory', {}) or {}
    tags = _get_tags(zabbix_host)

    if isinstance(inventory, dict) and inventory:
        for zfield, gfield in ZABBIX_TO_GLPI_FIELD_MAP.items():
            value = inventory.get(zfield, '')
            if value and gfield in ('serial', 'otherserial', 'contact'):
                glpi_data[gfield] = value

        # Point-of-contact fields
        poc_name = inventory.get('poc_1_name', '').strip()
        poc_phone = inventory.get('poc_1_phone_a', '').strip()
        if poc_name and not glpi_data.get('contact'):
            glpi_data['contact'] = poc_name
        if poc_phone:
            glpi_data['contact_num'] = poc_phone

        # Asset URL
        if inventory.get('url_a'):
            glpi_data['otherserial'] = glpi_data.get('otherserial') or inventory['url_a']

    # Build comment: hardware detail + tag metadata + sync provenance
    comment_parts = []
    inv = inventory if isinstance(inventory, dict) else {}
    for zfield in ('hardware_full', 'hardware', 'software'):
        if inv.get(zfield):
            comment_parts.append(f"{zfield}: {inv[zfield]}")

    # Embed Zabbix tag metadata for reference
    tag_info = []
    if tags.get('site'):
        tag_info.append(f"Site: {tags['site']}")
    if tags.get('type'):
        tag_info.append(f"Type: {tags['type']}")
    if tags.get('role'):
        tag_info.append(f"Role: {tags['role']}")
    if tag_info:
        comment_parts.append(' | '.join(tag_info))

    comment_parts.append(
        f"Synced from Zabbix at {datetime.utcnow().isoformat()}"
        f"\nZabbix Host ID: {zabbix_host.get('hostid')}"
    )
    glpi_data['comment'] = '\n'.join(comment_parts)
    return glpi_data


def normalize_os(os_str: str) -> str:
    """Reduce a verbose Zabbix OS string to a clean GLPI OperatingSystem name."""
    s = (os_str or '').strip()
    if not s:
        return ''
    low = s.lower()
    if 'windows' in low:
        m = (re.search(r'windows server\s+\d{4}( r2)?', low)
             or re.search(r'windows\s+(11|10|8\.1|8|7|xp|vista)', low))
        return m.group(0).title() if m else 'Windows'
    for tag in ('ubuntu', 'debian', 'centos', 'red hat', 'rhel', 'fedora',
                'suse', 'rocky', 'alma', 'oracle linux', 'freebsd', 'vmware esxi'):
        if tag in low:
            return tag.title()
    if 'linux' in low:
        return 'Linux'
    return s[:120]


def resolve_structured_fields(zabbix_host: Dict[str, Any], itemtype: str,
                              glpi_client: 'GLPIClient') -> Dict[str, Any]:
    """Resolve model / manufacturer / location / status / type to GLPI dropdown ids.

    OS is handled separately via set_operating_system(), not here.
    Falls back to Zabbix host tags when inventory fields are blank.
    """
    inventory = zabbix_host.get('inventory', {}) or {}
    if not isinstance(inventory, dict):
        inventory = {}
    tags = _get_tags(zabbix_host)
    out: Dict[str, Any] = {}

    # ── Status ────────────────────────────────────────────────────────────────
    host_status = str(zabbix_host.get('status', '0'))
    state_name = _ZABBIX_STATUS_TO_GLPI_STATE.get(host_status, 'Production')
    sid = glpi_client.get_or_create_dropdown('State', state_name)
    if sid:
        out['states_id'] = sid

    # ── Manufacturer ──────────────────────────────────────────────────────────
    # Priority: inventory.vendor → extracted from model string → inferred from OS
    vendor = (inventory.get('vendor') or '').strip()
    if not vendor and inventory.get('model'):
        vendor = _extract_vendor_from_model(inventory['model'])
    if not vendor:
        os_str = inventory.get('os') or inventory.get('os_short') or ''
        vendor = _extract_vendor_from_os(os_str)
    if vendor:
        mid = glpi_client.get_or_create_dropdown('Manufacturer', vendor)
        if mid:
            out['manufacturers_id'] = mid

    # ── Model ─────────────────────────────────────────────────────────────────
    if inventory.get('model') and itemtype in MODEL_FIELD:
        field, ddtype = MODEL_FIELD[itemtype]
        clean_model = _clean_model_name(inventory['model'])
        mid = glpi_client.get_or_create_dropdown(ddtype, clean_model)
        if mid:
            out[field] = mid

    # ── Asset type (Switch / Firewall / Server / Virtual Machine …) ───────────
    if itemtype in TYPE_FIELD:
        type_field, type_ddtype = TYPE_FIELD[itemtype]
        type_map = _DEVICE_TYPE_MAP.get(itemtype, {})
        # Check role tag first (more specific), then type tag
        for tag_key in ('role', 'type'):
            raw = tags.get(tag_key, '').lower().strip()
            if raw and raw in type_map:
                tid = glpi_client.get_or_create_dropdown(type_ddtype, type_map[raw])
                if tid:
                    out[type_field] = tid
                break

    # ── Location ──────────────────────────────────────────────────────────────
    # Priority: inventory.location → site tag lookup → site tag raw value
    location = (inventory.get('location') or '').strip()
    if not location:
        site_tag = tags.get('site', '').upper()
        location = _SITE_TAG_TO_LOCATION.get(site_tag, '') or tags.get('site', '')
    if location:
        lid = glpi_client.get_or_create_dropdown('Location', location)
        if lid:
            out['locations_id'] = lid

    return out


def primary_ip(zabbix_host: Dict[str, Any]) -> Optional[str]:
    """Best management IP for the host: first non-loopback interface IP."""
    ips = [i.get('ip', '').strip() for i in (zabbix_host.get('interfaces') or [])
           if i.get('ip')]
    for ip in ips:
        if ip and ip not in ('127.0.0.1', '::1'):
            return ip
    return ips[0] if ips else None


NETWORK_KEYWORDS = ['switch', 'router', 'firewall', 'access point', 'access-point',
                    'accesspoint', ' ap ', 'sophos', 'fortigate', 'mikrotik',
                    'cisco', 'juniper', 'gateway', 'wlc', 'wifi', 'wi-fi', 'sonicwall',
                    'palo alto', 'paloalto', 'network', 'nic ', 'vlan', 'l3', 'l2']
PRINTER_KEYWORDS = ['printer', 'mfp', 'multifunction', 'multi-function', 'laserjet',
                    'officejet', 'kyocera', 'ricoh', 'xerox', 'canon imagerunner',
                    'konica', 'toner', 'copier']


def determine_itemtype(zabbix_host: Dict[str, Any]) -> str:
    """
    Determine GLPI item type based on Zabbix host properties.

    Zabbix's structured inventory `type` field is frequently empty, so we also
    fall back to keyword heuristics on the host/visible name. This is what lets
    switches, firewalls and printers land in the right CMDB itemtype instead of
    all being dumped as Computers.

    Returns a GLPI itemtype: 'Computer', 'NetworkEquipment' or 'Printer'.
    """
    inventory = zabbix_host.get('inventory', {}) or {}

    # 1. Trust explicit Zabbix inventory type when present.
    host_type = (inventory.get('type', '') or '').lower()
    if any(nt.strip() in host_type for nt in NETWORK_KEYWORDS if nt.strip()):
        return 'NetworkEquipment'
    if any(pt in host_type for pt in PRINTER_KEYWORDS):
        return 'Printer'

    # 2. Fall back to name-based heuristics across name + visible fields.
    haystack = ' '.join([
        (zabbix_host.get('name') or ''),
        (zabbix_host.get('host') or ''),
        (inventory.get('hardware') or ''),
        (inventory.get('model') or ''),
        (inventory.get('chassis') or ''),
    ]).lower()
    if any(pt in haystack for pt in PRINTER_KEYWORDS):
        return 'Printer'
    if any(nt.strip() in haystack for nt in NETWORK_KEYWORDS if nt.strip()):
        return 'NetworkEquipment'

    # 3. Default to Computer.
    return 'Computer'


_AUTO_UPDATE_SYSTEM_ID: Optional[int] = None  # cached once per process


def _enrich_snmp_fields(
    zabbix_host: Dict[str, Any],
    host_id: str,
    itemtype: str,
    asset_id: int,
    glpi_client: 'GLPIClient',
    zabbix_client: 'ZabbixClient',
) -> None:
    """
    Populate SNMP-sourced GLPI fields that don't come from Zabbix inventory:

      - snmpcredentials_id  (NetworkEquipment only)
      - uuid                from sysObjectID or Zabbix inventory uuid
      - sysdescr            from system.descr[sysDescr.0]
      - autoupdatesystems_id  "Zabbix" as the inventory source
      - last_inventory_update current timestamp

    Runs for every asset type; SNMP fields only apply when the host has an
    SNMP interface; uuid / autoupdatesystem apply to all.
    """
    global _AUTO_UPDATE_SYSTEM_ID
    from datetime import datetime

    patch: Dict[str, Any] = {}

    # ── autoupdatesystems_id ──────────────────────────────────────────────────
    if _AUTO_UPDATE_SYSTEM_ID is None:
        _AUTO_UPDATE_SYSTEM_ID = glpi_client.get_or_create_auto_update_system('Zabbix')
    if _AUTO_UPDATE_SYSTEM_ID:
        patch['autoupdatesystems_id'] = _AUTO_UPDATE_SYSTEM_ID

    # ── last_inventory_update ─────────────────────────────────────────────────
    patch['last_inventory_update'] = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

    # ── UUID ─────────────────────────────────────────────────────────────────
    # Prefer Zabbix inventory uuid; fall back to SNMP sysObjectID for NE
    inv_uuid = ((zabbix_host.get('inventory') or {}).get('uuid') or '').strip()
    if inv_uuid:
        patch['uuid'] = inv_uuid

    # ── SNMP-specific fields ──────────────────────────────────────────────────
    snmp_iface = zabbix_client.get_snmp_interface(host_id)
    if snmp_iface:
        version  = snmp_iface.get('version', '2')
        community = snmp_iface.get('community', 'public')

        # snmpcredentials_id (NetworkEquipment only — field doesn't exist on Computer)
        if itemtype == 'NetworkEquipment':
            cred_id = glpi_client.get_or_create_snmp_credential(version, community)
            if cred_id:
                patch['snmpcredentials_id'] = cred_id

        # sysdescr from SNMP sysDescr item
        fw = zabbix_client.get_device_firmware(host_id)
        sys_descr = ''
        if fw:
            # get_device_firmware already fetches system.descr internally; reuse it
            items = zabbix_client._api_request('item.get', {
                'output': ['lastvalue'],
                'hostids': [host_id],
                'filter': {'key_': 'system.descr[sysDescr.0]'},
            }) or []
            sys_descr = (items[0].get('lastvalue') or '').strip() if items else ''
        if sys_descr and itemtype == 'NetworkEquipment':
            patch['sysdescr'] = sys_descr[:255]

        # UUID fallback for NE: sysObjectID (e.g. ".1.3.6.1.4.1.171.10.63.3")
        if not inv_uuid and itemtype == 'NetworkEquipment':
            oid = zabbix_client.get_sysObjectID(host_id)
            if oid:
                patch['uuid'] = oid

    if patch:
        glpi_client.update_asset(itemtype, asset_id, patch)


def sync_host_to_glpi(
    zabbix_host: Dict[str, Any],
    glpi_client: GLPIClient,
    zabbix_client: Optional['ZabbixClient'] = None,
) -> Dict[str, Any]:
    """
    Sync a single Zabbix host to GLPI
    
    Args:
        zabbix_host: Zabbix host object
        glpi_client: GLPI API client
        
    Returns:
        Result dictionary with status
    """
    host_id = zabbix_host.get('hostid')
    host_name = zabbix_host.get('name') or zabbix_host.get('host', 'Unknown')

    try:
        # Map inventory fields and classify the device.
        glpi_data = map_inventory_fields(zabbix_host)
        itemtype = determine_itemtype(zabbix_host)

        # SACM enrichment: resolve structured dropdowns (OS/model/vendor/location)
        glpi_data.update(resolve_structured_fields(zabbix_host, itemtype, glpi_client))

        # Reuse the GLPI id we previously recorded for this host, but only when
        # the itemtype still matches (a host reclassified from Computer to
        # NetworkEquipment must move to a new row, not update the old one).
        existing = get_glpi_asset_by_host_id(host_id)
        known_id = None
        if existing and existing.get('glpi_computer_id'):
            if (existing.get('glpi_itemtype') or 'Computer') == itemtype:
                known_id = existing['glpi_computer_id']

        result = glpi_client.upsert_asset(itemtype, glpi_data, known_id=known_id)
        if result and result.get('id'):
            # SACM enrichment (post-upsert relations):
            inv = zabbix_host.get('inventory', {}) or {}
            #  - operating system: all available fields
            raw_os = (inv.get('os_short') or inv.get('os') or '') if isinstance(inv, dict) else ''
            os_name = normalize_os(raw_os)
            if os_name:
                full_os = inv.get('os') or raw_os if isinstance(inv, dict) else raw_os
                os_details = _parse_os_details(full_os)
                glpi_client.set_operating_system(
                    itemtype, result['id'], os_name,
                    os_version=os_details.get('version'),
                    os_arch=os_details.get('arch'),
                    os_kernel=os_details.get('kernel'),
                    os_edition=os_details.get('edition'),
                    hostname=host_name,
                    company=os_details.get('company'),
                )
            elif itemtype == 'NetworkEquipment' and zabbix_client:
                # Zabbix inventory os/os_short is empty for most SNMP network
                # devices — fall back to firmware items (sysFirmwareVersion etc.)
                fw = zabbix_client.get_device_firmware(host_id)
                if fw.get('os_name'):
                    glpi_client.set_operating_system(
                        itemtype, result['id'], fw['os_name'],
                        os_version=fw.get('version') or None,
                        hostname=host_name,
                        company=fw.get('company') or None,
                    )
                # Backfill manufacturer and model from firmware data when Zabbix
                # inventory.vendor / inventory.model are blank.
                if fw:
                    patch: Dict[str, Any] = {}
                    inv = zabbix_host.get('inventory', {}) or {}
                    if fw.get('company') and not glpi_data.get('manufacturers_id'):
                        mid = glpi_client.get_or_create_dropdown('Manufacturer', fw['company'])
                        if mid:
                            patch['manufacturers_id'] = mid
                    if fw.get('model') and not glpi_data.get('networkequipmentmodels_id'):
                        clean = _clean_model_name(fw['model'])
                        if clean:
                            dmid = glpi_client.get_or_create_dropdown(
                                'NetworkEquipmentModel', clean)
                            if dmid:
                                patch['networkequipmentmodels_id'] = dmid
                    if patch:
                        glpi_client.update_asset(itemtype, result['id'], patch)
            #  - management IP (idempotent network port chain)
            ip = primary_ip(zabbix_host)
            if ip:
                glpi_client.set_asset_ip(itemtype, result['id'], ip)
            #  - network interfaces: switches/firewalls AND computers/servers
            if zabbix_client:
                ifaces = zabbix_client.get_network_interfaces(host_id)
                if ifaces:
                    glpi_client.sync_network_ports(itemtype, result['id'], ifaces)
            #  - disk volumes (Volumes tab): computers and any asset with vfs items
            if zabbix_client:
                vols = zabbix_client.get_disk_volumes(host_id)
                if vols:
                    glpi_client.sync_volumes(itemtype, result['id'], vols)
            #  - SNMP credential, UUID, sysdescr, autoupdatesystem, last_inventory_update
            if zabbix_client:
                _enrich_snmp_fields(
                    zabbix_host, host_id, itemtype, result['id'],
                    glpi_client, zabbix_client,
                )
            save_asset_mapping(host_id, host_name, result['id'], itemtype)
            return {'status': result['action'], 'glpi_id': result['id'],
                    'itemtype': itemtype}

        return {'status': 'error', 'error': f'upsert failed for {itemtype}'}

    except Exception as e:
        logger.error(f"Error syncing host {host_name}: {e}")
        return {'status': 'error', 'error': str(e)}


def run_sync(dry_run: bool = False, host_filter: str = None) -> Dict[str, Any]:
    """
    Run full inventory synchronization
    
    Args:
        dry_run: If True, only report what would be done
        host_filter: Optional hostname filter (substring match)
        
    Returns:
        Sync results summary
    """
    if not INVENTORY_SYNC_ENABLED and not dry_run:
        logger.warning("Inventory sync is disabled in configuration")
        return {'status': 'disabled'}
    
    logger.info("Starting inventory sync from Zabbix to GLPI")
    
    # Start sync session
    session_id = start_sync_session('inventory')
    
    results = {
        'processed': 0,
        'created': 0,
        'updated': 0,
        'skipped': 0,
        'errors': 0,
        'hosts': []
    }
    
    try:
        # Get hosts from Zabbix (keep session open for interface queries)
        with ZabbixClient() as zabbix:
            hosts = zabbix.get_hosts(with_inventory=True)
            logger.info(f"Retrieved {len(hosts)} hosts from Zabbix")

            # Filter if specified
            if host_filter:
                hosts = [h for h in hosts if host_filter.lower() in
                         (h.get('name', '') + h.get('host', '')).lower()]
                logger.info(f"Filtered to {len(hosts)} hosts matching '{host_filter}'")

            if dry_run:
                logger.info("DRY RUN - No changes will be made")
                for host in hosts:
                    host_name = host.get('name') or host.get('host', 'Unknown')
                    itemtype = determine_itemtype(host)
                    existing = get_glpi_asset_by_host_id(host.get('hostid'))
                    action = 'UPDATE' if existing else 'CREATE'
                    logger.info(f"  [{action}] {host_name} -> {itemtype}")
                    results['hosts'].append({
                        'name': host_name,
                        'action': action,
                        'itemtype': itemtype
                    })
                results['processed'] = len(hosts)
                return results

            # Sync to GLPI (pass zabbix client so interfaces can be fetched per host)
            with GLPIClient() as glpi:
                for host in hosts:
                    host_name = host.get('name') or host.get('host', 'Unknown')

                    result = sync_host_to_glpi(host, glpi, zabbix_client=zabbix)
                    results['processed'] += 1

                    if result['status'] == 'created':
                        results['created'] += 1
                        logger.info(f"Created: {host_name} -> GLPI #{result.get('glpi_id')}")
                    elif result['status'] == 'updated':
                        results['updated'] += 1
                        logger.info(f"Updated: {host_name} -> GLPI #{result.get('glpi_id')}")
                    elif result['status'] == 'skipped':
                        results['skipped'] += 1
                        logger.debug(f"Skipped: {host_name} - {result.get('reason')}")
                    elif result['status'] == 'error':
                        results['errors'] += 1
                        logger.error(f"Error: {host_name} - {result.get('error')}")

                    results['hosts'].append({
                        'name': host_name,
                        'status': result['status'],
                        'glpi_id': result.get('glpi_id')
                    })
        
        # Complete sync session
        complete_sync_session(
            session_id,
            hosts_processed=results['processed'],
            hosts_created=results['created'],
            hosts_updated=results['updated'],
            errors=results['errors'],
            status='completed' if results['errors'] == 0 else 'completed_with_errors'
        )
        
        logger.info(f"Sync completed: {results['processed']} processed, "
                   f"{results['created']} created, {results['updated']} updated, "
                   f"{results['errors']} errors")
        
        return results
        
    except Exception as e:
        logger.exception(f"Sync failed: {e}")
        complete_sync_session(session_id, status='failed', details=str(e))
        return {'status': 'error', 'error': str(e)}


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description='Sync Zabbix host inventory to GLPI assets'
    )
    parser.add_argument(
        '--dry-run', '-n',
        action='store_true',
        help='Show what would be synced without making changes'
    )
    parser.add_argument(
        '--host', '-H',
        type=str,
        help='Filter to hosts matching this substring'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose output'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Initialize database
    init_database()
    
    # Run sync
    results = run_sync(dry_run=args.dry_run, host_filter=args.host)
    
    # Print summary
    print("\n" + "=" * 50)
    print("SYNC SUMMARY")
    print("=" * 50)
    
    if 'error' in results:
        print(f"Status: FAILED - {results['error']}")
        sys.exit(1)
    elif results.get('status') == 'disabled':
        print("Status: DISABLED (set INVENTORY_SYNC_ENABLED=true to enable)")
        sys.exit(0)
    else:
        print(f"Processed: {results.get('processed', 0)}")
        print(f"Created:   {results.get('created', 0)}")
        print(f"Updated:   {results.get('updated', 0)}")
        print(f"Skipped:   {results.get('skipped', 0)}")
        print(f"Errors:    {results.get('errors', 0)}")
        
        if args.dry_run:
            print("\n[DRY RUN - No changes were made]")
        
        sys.exit(0 if results.get('errors', 0) == 0 else 1)


if __name__ == '__main__':
    main()
