#!/usr/bin/env python3
"""
Configuration for Zabbix-GLPI Integration
All settings can be overridden via environment variables
"""

import os

# =============================================================================
# GLPI Configuration
# =============================================================================
GLPI_URL = os.environ.get('GLPI_URL', 'http://glpi:80/apirest.php')
GLPI_USER = os.environ.get('GLPI_USER', 'glpi')
GLPI_PASSWORD = os.environ.get('GLPI_PASSWORD', 'glpi')
GLPI_APP_TOKEN = os.environ.get('GLPI_APP_TOKEN', '')
GLPI_USER_TOKEN = os.environ.get('GLPI_USER_TOKEN', '')

# GLPI Entity (0 = Root entity)
GLPI_ENTITY_ID = int(os.environ.get('GLPI_ENTITY_ID', '0'))

# GLPI Default User/Group for ticket assignment
GLPI_DEFAULT_USER_ID = int(os.environ.get('GLPI_DEFAULT_USER_ID', '0'))
GLPI_DEFAULT_GROUP_ID = int(os.environ.get('GLPI_DEFAULT_GROUP_ID', '0'))

# =============================================================================
# Zabbix Configuration
# =============================================================================
ZABBIX_URL = os.environ.get('ZABBIX_URL', 'http://zabbix-web:8080/api_jsonrpc.php')
ZABBIX_USER = os.environ.get('ZABBIX_USER', 'Admin')
ZABBIX_PASSWORD = os.environ.get('ZABBIX_PASSWORD', 'zabbix')
ZABBIX_API_TOKEN = os.environ.get('ZABBIX_API_TOKEN', '')

# =============================================================================
# Webhook Server Configuration
# =============================================================================
WEBHOOK_PORT = int(os.environ.get('WEBHOOK_PORT', '5002'))
WEBHOOK_HOST = os.environ.get('WEBHOOK_HOST', '0.0.0.0')

# =============================================================================
# Database Configuration (for event-ticket mapping)
# =============================================================================
DATABASE_PATH = os.environ.get('DATABASE_PATH', '/data/zabbix_glpi.db')

# =============================================================================
# Inventory Sync Configuration
# =============================================================================
INVENTORY_SYNC_ENABLED = os.environ.get('INVENTORY_SYNC_ENABLED', 'true').lower() == 'true'
INVENTORY_SYNC_INTERVAL = int(os.environ.get('INVENTORY_SYNC_INTERVAL', '3600'))  # seconds

# Field mapping: Zabbix inventory field -> GLPI Computer field
# Available Zabbix fields: type, name, alias, os, os_full, os_short, serialno_a, 
# serialno_b, tag, asset_tag, macaddress_a, macaddress_b, hardware, hardware_full,
# software, software_app_a, software_app_b, software_app_c, software_app_d,
# software_app_e, contact, location, location_lat, location_lon, notes, chassis,
# model, hw_arch, vendor, contract_number, installer_name, deployment_status,
# url_a, url_b, url_c, host_networks, host_netmask, host_router, oob_ip, oob_netmask,
# oob_router, date_hw_purchase, date_hw_install, date_hw_expiry, date_hw_decomm,
# site_address_a, site_address_b, site_address_c, site_city, site_state, site_country,
# site_zip, site_rack, site_notes, poc_1_name, poc_1_email, poc_1_phone_a, poc_1_phone_b,
# poc_1_cell, poc_1_screen, poc_1_notes, poc_2_name, poc_2_email, poc_2_phone_a,
# poc_2_phone_b, poc_2_cell, poc_2_screen, poc_2_notes

ZABBIX_TO_GLPI_FIELD_MAP = {
    'name': 'name',                    # Computer name
    'serialno_a': 'serial',            # Serial number
    'asset_tag': 'otherserial',        # Inventory number
    'os': 'operatingsystems_id',       # Operating system (needs lookup)
    'model': 'computermodels_id',      # Model (needs lookup)
    'vendor': 'manufacturers_id',      # Manufacturer (needs lookup)
    'location': 'locations_id',        # Location (needs lookup)
    'contact': 'contact',              # Contact person
    'notes': 'comment',                # Notes/Comment
}

# =============================================================================
# Severity Mapping (Zabbix -> GLPI)
# =============================================================================
# Zabbix severities: 0=Not classified, 1=Information, 2=Warning, 3=Average, 4=High, 5=Disaster
# GLPI urgency/priority: 1=Very low, 2=Low, 3=Medium, 4=High, 5=Very high

SEVERITY_TO_URGENCY = {
    0: 2,  # Not classified -> Low
    1: 1,  # Information -> Very low
    2: 2,  # Warning -> Low
    3: 3,  # Average -> Medium
    4: 4,  # High -> High
    5: 5,  # Disaster -> Very high
}

SEVERITY_NAME_TO_URGENCY = {
    'Not classified': 2,
    'Information': 1,
    'Warning': 2,
    'Average': 3,
    'High': 4,
    'Disaster': 5,
}

# =============================================================================
# GLPI Ticket Status Codes
# =============================================================================
GLPI_STATUS = {
    'NEW': 1,
    'ASSIGNED': 2,
    'PLANNED': 3,
    'PENDING': 4,
    'SOLVED': 5,
    'CLOSED': 6,
}

# =============================================================================
# Deduplication settings
# =============================================================================
# Suppress creating a NEW ticket when a ticket for the same host+trigger was
# closed within this many seconds (collapses flapping triggers into one ticket).
# Set to 0 to disable cooldown-based suppression.
DEDUP_COOLDOWN_SECONDS = int(os.environ.get('DEDUP_COOLDOWN_SECONDS', '3600'))

# When a problem recurs within the cooldown window and the previous ticket is
# already closed, reopen that ticket instead of creating a new one.
REOPEN_ON_RECURRENCE = os.environ.get('REOPEN_ON_RECURRENCE', 'true').lower() == 'true'

# Add a follow-up note to the existing ticket each time a duplicate problem is
# suppressed. Off by default to avoid follow-up spam on heavily flapping hosts.
ADD_RECURRENCE_FOLLOWUP = os.environ.get('ADD_RECURRENCE_FOLLOWUP', 'true').lower() == 'true'

# Maximum number of followups a ticket may accumulate before the dedup/cooldown
# logic gives up and forces a brand-new ticket.  Prevents a single flapping
# trigger from making a ticket so large that GLPI crashes rendering it.
# Set to 0 to disable the cap.
MAX_TICKET_FOLLOWUPS = int(os.environ.get('MAX_TICKET_FOLLOWUPS', '50'))

# =============================================================================
# Automation Filtering
# =============================================================================
# Minimum Zabbix severity to create a ticket.
# 0=Not classified, 1=Information, 2=Warning, 3=Average, 4=High, 5=Disaster
# Setting this to 2 will ignore Information and Not classified alerts.
MIN_SEVERITY = int(os.environ.get('MIN_SEVERITY', '2'))

# =============================================================================
# Auto-acknowledge settings
# =============================================================================
AUTO_ACKNOWLEDGE_ENABLED = os.environ.get('AUTO_ACKNOWLEDGE_ENABLED', 'true').lower() == 'true'
AUTO_ACKNOWLEDGE_MESSAGE = os.environ.get('AUTO_ACKNOWLEDGE_MESSAGE', 
    'Automatically acknowledged by GLPI Integration. Ticket #{ticket_id} created.')

# =============================================================================
# Logging Configuration
# =============================================================================
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
