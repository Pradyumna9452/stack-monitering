#!/usr/bin/env python3
"""
GLPI API Client for Zabbix Integration
Handles all GLPI operations: sessions, tickets, assets, followups
"""

import logging
import base64
import requests
from typing import Optional, Dict, Any, List

from config import (
    GLPI_URL, GLPI_USER, GLPI_PASSWORD, GLPI_APP_TOKEN, GLPI_USER_TOKEN,
    GLPI_ENTITY_ID, GLPI_DEFAULT_USER_ID, GLPI_DEFAULT_GROUP_ID, GLPI_STATUS
)

logger = logging.getLogger(__name__)


class GLPIClient:
    """GLPI REST API Client with full ticket lifecycle support"""
    
    def __init__(self):
        self.base_url = GLPI_URL.rstrip('/')
        self.session_token = None
        self.app_token = GLPI_APP_TOKEN
        self._request_timeout = 30
        self._dropdown_cache = {}   # (itemtype, name.lower()) -> id
        
    def _get_headers(self) -> Dict[str, str]:
        """Build headers for API requests"""
        headers = {'Content-Type': 'application/json'}
        # Only add App-Token if it's actually set (non-empty)
        if self.app_token:
            headers['App-Token'] = self.app_token
        if self.session_token:
            headers['Session-Token'] = self.session_token
        return headers
    
    def init_session(self) -> bool:
        """Initialize GLPI session using user token or basic auth"""
        try:
            if GLPI_USER_TOKEN:
                headers = {
                    'Content-Type': 'application/json',
                    'Authorization': f'user_token {GLPI_USER_TOKEN}'
                }
            else:
                credentials = base64.b64encode(f'{GLPI_USER}:{GLPI_PASSWORD}'.encode()).decode()
                headers = {
                    'Content-Type': 'application/json',
                    'Authorization': f'Basic {credentials}'
                }
            
            if self.app_token:
                headers['App-Token'] = self.app_token
            
            response = requests.get(
                f'{self.base_url}/initSession',
                headers=headers,
                timeout=self._request_timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                self.session_token = data.get('session_token')
                logger.info("GLPI session initialized successfully")
                return True
            else:
                logger.error(f"Failed to init GLPI session: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error initializing GLPI session: {e}")
            return False
    
    def kill_session(self):
        """Terminate GLPI session"""
        try:
            if self.session_token:
                requests.get(
                    f'{self.base_url}/killSession',
                    headers=self._get_headers(),
                    timeout=10
                )
                logger.debug("GLPI session terminated")
        except Exception as e:
            logger.warning(f"Error killing GLPI session: {e}")
        finally:
            self.session_token = None
    
    def __enter__(self):
        """Context manager entry - auto init session"""
        self.init_session()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - auto kill session"""
        self.kill_session()
    
    # =========================================================================
    # Ticket Operations
    # =========================================================================
    
    def create_ticket(
        self,
        name: str,
        content: str,
        urgency: int = 3,
        priority: int = 3,
        itemtype: Optional[str] = None,
        items_id: Optional[int] = None,
        external_id: Optional[str] = None,
        **kwargs
    ) -> Optional[int]:
        """
        Create a new GLPI ticket
        
        Args:
            name: Ticket title
            content: Ticket description (HTML supported)
            urgency: 1-5 (5 = most urgent)
            priority: 1-5 (5 = highest priority)
            itemtype: Asset type (e.g., 'Computer', 'NetworkEquipment')
            items_id: Asset ID in GLPI
            external_id: External reference (stored in ticket for deduplication)
            
        Returns:
            Ticket ID if created, None otherwise
        """
        try:
            if not self.session_token and not self.init_session():
                return None
            
            ticket_data = {
                'input': {
                    'name': name,
                    'content': content,
                    'urgency': urgency,
                    'priority': priority,
                    'type': 1,  # Incident
                    'status': GLPI_STATUS['NEW'],
                    'entities_id': GLPI_ENTITY_ID,
                }
            }
            
            # Add optional fields
            if GLPI_DEFAULT_USER_ID:
                ticket_data['input']['_users_id_assign'] = GLPI_DEFAULT_USER_ID
                ticket_data['input']['status'] = GLPI_STATUS['ASSIGNED']
            
            if GLPI_DEFAULT_GROUP_ID:
                ticket_data['input']['_groups_id_assign'] = GLPI_DEFAULT_GROUP_ID
                ticket_data['input']['status'] = GLPI_STATUS['ASSIGNED']
            
            # Add any additional fields
            ticket_data['input'].update(kwargs)
            
            response = requests.post(
                f'{self.base_url}/Ticket',
                headers=self._get_headers(),
                json=ticket_data,
                timeout=self._request_timeout
            )
            
            if response.status_code in [200, 201]:
                data = response.json()
                ticket_id = data.get('id')
                logger.info(f"Created GLPI ticket #{ticket_id}: {name}")
                
                # Link asset if provided
                if itemtype and items_id:
                    self.link_asset_to_ticket(ticket_id, itemtype, items_id)
                
                return ticket_id
            else:
                logger.error(f"Failed to create ticket: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error creating GLPI ticket: {e}")
            return None
    
    def update_ticket(
        self,
        ticket_id: int,
        status: Optional[int] = None,
        solution: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        Update an existing GLPI ticket
        
        Args:
            ticket_id: The GLPI ticket ID
            status: New status code (use GLPI_STATUS constants)
            solution: Solution text (for closing tickets)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.session_token and not self.init_session():
                return False
            
            update_data = {'input': {'id': ticket_id}}
            
            if status is not None:
                update_data['input']['status'] = status
            
            update_data['input'].update(kwargs)
            
            response = requests.put(
                f'{self.base_url}/Ticket/{ticket_id}',
                headers=self._get_headers(),
                json=update_data,
                timeout=self._request_timeout
            )
            
            if response.status_code == 200:
                logger.info(f"Updated GLPI ticket #{ticket_id}")
                
                # Add solution if provided (for closing)
                if solution and status in [GLPI_STATUS['SOLVED'], GLPI_STATUS['CLOSED']]:
                    self.add_solution(ticket_id, solution)
                
                return True
            else:
                logger.error(f"Failed to update ticket: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error updating GLPI ticket: {e}")
            return False
    
    def close_ticket(self, ticket_id: int, solution: str) -> bool:
        """
        Close a ticket with solution
        
        Args:
            ticket_id: The GLPI ticket ID
            solution: Solution/resolution text
            
        Returns:
            True if successful
        """
        # First add solution
        self.add_solution(ticket_id, solution)
        # Then close
        return self.update_ticket(ticket_id, status=GLPI_STATUS['CLOSED'])
    
    def add_followup(self, ticket_id: int, content: str, is_private: bool = False) -> Optional[int]:
        """
        Add a follow-up comment to a ticket
        
        Args:
            ticket_id: The GLPI ticket ID
            content: Comment content (HTML supported)
            is_private: Whether the comment is private
            
        Returns:
            Followup ID if created, None otherwise
        """
        try:
            if not self.session_token and not self.init_session():
                return None
            
            followup_data = {
                'input': {
                    'items_id': ticket_id,
                    'itemtype': 'Ticket',
                    'content': content,
                    'is_private': 1 if is_private else 0,
                }
            }
            
            response = requests.post(
                f'{self.base_url}/ITILFollowup',
                headers=self._get_headers(),
                json=followup_data,
                timeout=self._request_timeout
            )
            
            if response.status_code in [200, 201]:
                data = response.json()
                followup_id = data.get('id')
                logger.info(f"Added followup #{followup_id} to ticket #{ticket_id}")
                return followup_id
            else:
                logger.error(f"Failed to add followup: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error adding followup: {e}")
            return None
    
    def get_followup_count(self, ticket_id: int) -> int:
        """Return the number of followups on a ticket, or 0 on error."""
        try:
            if not self.session_token and not self.init_session():
                return 0
            response = requests.get(
                f'{self.base_url}/Ticket/{ticket_id}/ITILFollowup',
                headers=self._get_headers(),
                params={'range': '0-0', 'only_id': 1},
                timeout=self._request_timeout
            )
            if response.status_code == 200:
                content_range = response.headers.get('Content-Range', '')
                # Content-Range: 0-0/TOTAL
                if '/' in content_range:
                    return int(content_range.split('/')[-1])
                return len(response.json())
            if response.status_code == 206:
                content_range = response.headers.get('Content-Range', '0-0/0')
                return int(content_range.split('/')[-1]) if '/' in content_range else 0
            return 0
        except Exception as e:
            logger.error(f"Error counting followups for ticket #{ticket_id}: {e}")
            return 0

    def add_solution(self, ticket_id: int, content: str) -> Optional[int]:
        """
        Add a solution to a ticket

        Args:
            ticket_id: The GLPI ticket ID
            content: Solution content
            
        Returns:
            Solution ID if created, None otherwise
        """
        try:
            if not self.session_token and not self.init_session():
                return None
            
            solution_data = {
                'input': {
                    'items_id': ticket_id,
                    'itemtype': 'Ticket',
                    'content': content,
                }
            }
            
            response = requests.post(
                f'{self.base_url}/ITILSolution',
                headers=self._get_headers(),
                json=solution_data,
                timeout=self._request_timeout
            )
            
            if response.status_code in [200, 201]:
                data = response.json()
                solution_id = data.get('id')
                logger.info(f"Added solution #{solution_id} to ticket #{ticket_id}")
                return solution_id
            else:
                logger.error(f"Failed to add solution: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error adding solution: {e}")
            return None
    
    def get_ticket(self, ticket_id: int) -> Optional[Dict[str, Any]]:
        """Get ticket details by ID"""
        try:
            if not self.session_token and not self.init_session():
                return None
            
            response = requests.get(
                f'{self.base_url}/Ticket/{ticket_id}',
                headers=self._get_headers(),
                timeout=self._request_timeout
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get ticket: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting ticket: {e}")
            return None
    
    def link_asset_to_ticket(self, ticket_id: int, itemtype: str, items_id: int) -> bool:
        """
        Link an asset to a ticket
        
        Args:
            ticket_id: The GLPI ticket ID
            itemtype: Asset type (e.g., 'Computer')
            items_id: Asset ID
            
        Returns:
            True if successful
        """
        try:
            if not self.session_token and not self.init_session():
                return False
            
            link_data = {
                'input': {
                    'tickets_id': ticket_id,
                    'itemtype': itemtype,
                    'items_id': items_id,
                }
            }
            
            response = requests.post(
                f'{self.base_url}/Item_Ticket',
                headers=self._get_headers(),
                json=link_data,
                timeout=self._request_timeout
            )
            
            if response.status_code in [200, 201]:
                logger.info(f"Linked {itemtype}#{items_id} to ticket #{ticket_id}")
                return True
            else:
                logger.warning(f"Failed to link asset: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error linking asset: {e}")
            return False
    
    # =========================================================================
    # Asset Operations
    # =========================================================================
    
    def search_computer_by_serial(self, serial: str) -> Optional[Dict[str, Any]]:
        """Search for a computer by serial number"""
        return self._search_item('Computer', 'serial', serial)
    
    def search_computer_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Search for a computer by name"""
        return self._search_item('Computer', 'name', name)
    
    def search_network_equipment_by_serial(self, serial: str) -> Optional[Dict[str, Any]]:
        """Search for network equipment by serial number"""
        return self._search_item('NetworkEquipment', 'serial', serial)
    
    def search_network_equipment_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Search for network equipment by name"""
        return self._search_item('NetworkEquipment', 'name', name)
    
    def _search_item(self, itemtype: str, field: str, value: str) -> Optional[Dict[str, Any]]:
        """Generic item search"""
        try:
            if not self.session_token and not self.init_session():
                return None
            
            # Use 'contains' for name search as 'equals' can be finicky in GLPI API
            # for names with spaces or special characters.
            search_type = 'equals' if field == 'serial' else 'contains'
            
            # Search criteria
            params = {
                'criteria[0][field]': self._get_search_field_id(itemtype, field),
                'criteria[0][searchtype]': search_type,
                'criteria[0][value]': value,
                'forcedisplay[0]': 1,  # ID
                'forcedisplay[1]': 2,  # Name
                'forcedisplay[2]': 5,  # Serial
            }
            
            response = requests.get(
                f'{self.base_url}/search/{itemtype}',
                headers=self._get_headers(),
                params=params,
                timeout=self._request_timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('data'):
                    # If using 'contains', verify name matches exactly
                    if search_type == 'contains':
                        for item in data['data']:
                            if item.get('1') == value:
                                return item
                    else:
                        return data['data'][0]
            return None
                
        except Exception as e:
            logger.error(f"Error searching {itemtype}: {e}")
            return None
    
    def _get_search_field_id(self, itemtype: str, field: str) -> int:
        """Map field names to GLPI search option IDs"""
        # name/serial/otherserial share the same search-option ids across the
        # standard asset itemtypes in GLPI.
        field_map = {
            'Computer': {'name': 1, 'serial': 5, 'otherserial': 6},
            'NetworkEquipment': {'name': 1, 'serial': 5, 'otherserial': 6},
            'Printer': {'name': 1, 'serial': 5, 'otherserial': 6},
        }
        return field_map.get(itemtype, {'name': 1, 'serial': 5, 'otherserial': 6}).get(field, 1)

    # =========================================================================
    # Generic idempotent asset upsert (Computer / NetworkEquipment / Printer)
    #
    # Why this exists: the legacy create_or_update_computer() re-searched GLPI
    # on every run and POST-created a fresh row whenever the name search missed
    # among bloated duplicates. That produced ~35 junk rows per run (often born
    # is_deleted=1) and a CMDB that churned 136k trashed computers. The methods
    # below make sync idempotent: prefer a direct PUT to the GLPI id we already
    # recorded, only ever create when an asset is genuinely new, and never leave
    # a freshly-created asset in the trash.
    # =========================================================================

    SUPPORTED_ASSET_TYPES = ('Computer', 'NetworkEquipment', 'Printer')

    def get_asset(self, itemtype: str, asset_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single asset by id. Returns the row dict or None if absent."""
        try:
            if not self.session_token and not self.init_session():
                return None
            response = requests.get(
                f'{self.base_url}/{itemtype}/{asset_id}',
                headers=self._get_headers(),
                timeout=self._request_timeout,
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Error fetching {itemtype}#{asset_id}: {e}")
            return None

    def find_active_asset_id_by_name(self, itemtype: str, name: str) -> Optional[int]:
        """
        Find a single non-deleted asset id by exact name.

        GLPI's search excludes trashed items by default, so this only matches
        live rows. Returns the id of the first exact name match, else None.
        """
        try:
            if not self.session_token and not self.init_session():
                return None
            params = {
                'criteria[0][field]': self._get_search_field_id(itemtype, 'name'),
                'criteria[0][searchtype]': 'contains',
                'criteria[0][value]': name,
                'forcedisplay[0]': 1,   # name
                'forcedisplay[1]': 2,   # id
                'range': '0-199',
            }
            response = requests.get(
                f'{self.base_url}/search/{itemtype}',
                headers=self._get_headers(),
                params=params,
                timeout=self._request_timeout,
            )
            if response.status_code in (200, 206):
                data = response.json()
                for item in data.get('data', []) or []:
                    # field '1' == name, field '2' == id (forced above)
                    if str(item.get('1', '')).strip() == str(name).strip():
                        aid = item.get('2')
                        return int(aid) if aid else None
            return None
        except Exception as e:
            logger.error(f"Error searching {itemtype} by name '{name}': {e}")
            return None

    # Fields where an empty/zero value from Zabbix must NOT overwrite a value
    # that was manually entered in GLPI.  These are omitted from the PUT payload
    # when the incoming value is falsy (None, '', 0).
    _PRESERVE_IF_EMPTY = frozenset({
        'serial', 'otherserial',   # serial number & inventory/asset tag
    })

    @staticmethod
    def _clean_asset_input(fields: Dict[str, Any]) -> Dict[str, Any]:
        """
        Strip control keys that must never be sent in an asset create/update body.
        Also omit identity fields (serial, otherserial) when the incoming value
        is empty so manually entered GLPI data is never overwritten with blanks.
        """
        out = {}
        for k, v in fields.items():
            if k in ('id', 'is_deleted', 'entities_id'):
                continue
            if v is None:
                continue
            if k in GLPIClient._PRESERVE_IF_EMPTY and not v:
                continue
            out[k] = v
        return out

    def update_asset(self, itemtype: str, asset_id: int, fields: Dict[str, Any],
                     restore_if_trashed: bool = True) -> Optional[int]:
        """PUT-update an existing asset by id. Optionally un-trash it."""
        try:
            if not self.session_token and not self.init_session():
                return None
            payload = self._clean_asset_input(fields)
            payload['id'] = asset_id
            if restore_if_trashed:
                payload['is_deleted'] = 0
            response = requests.put(
                f'{self.base_url}/{itemtype}/{asset_id}',
                headers=self._get_headers(),
                json={'input': payload},
                timeout=self._request_timeout,
            )
            if response.status_code == 200:
                return int(asset_id)
            logger.error(f"Failed to update {itemtype}#{asset_id}: "
                         f"{response.status_code} - {response.text[:200]}")
            return None
        except Exception as e:
            logger.error(f"Error updating {itemtype}#{asset_id}: {e}")
            return None

    def create_asset(self, itemtype: str, fields: Dict[str, Any]) -> Optional[int]:
        """
        Create a new asset, then guarantee it is not left in the trash.

        GLPI occasionally inserts is_deleted=1 during rapid batch creates; we
        verify and restore so a brand-new asset is always live.
        """
        try:
            if not self.session_token and not self.init_session():
                return None
            payload = self._clean_asset_input(fields)
            payload['entities_id'] = GLPI_ENTITY_ID
            response = requests.post(
                f'{self.base_url}/{itemtype}',
                headers=self._get_headers(),
                json={'input': payload},
                timeout=self._request_timeout,
            )
            if response.status_code not in (200, 201):
                logger.error(f"Failed to create {itemtype}: "
                             f"{response.status_code} - {response.text[:200]}")
                return None
            new_id = response.json().get('id')
            if not new_id:
                return None
            # Safety net: ensure the new row is live.
            row = self.get_asset(itemtype, new_id)
            if row and str(row.get('is_deleted', 0)) in ('1', 'true', 'True'):
                logger.warning(f"{itemtype}#{new_id} was created trashed; restoring")
                self.update_asset(itemtype, new_id, {}, restore_if_trashed=True)
            logger.info(f"Created {itemtype}#{new_id}")
            return int(new_id)
        except Exception as e:
            logger.error(f"Error creating {itemtype}: {e}")
            return None

    def upsert_asset(self, itemtype: str, fields: Dict[str, Any],
                     known_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Idempotently create-or-update an asset.

        Resolution order:
          1. known_id (from our local mapping) -> direct PUT update, restoring
             from trash if needed. This is the path taken on every routine run
             and is what stops the duplicate-row churn.
          2. exact non-deleted name match -> adopt and PUT update.
          3. otherwise create exactly one new asset.

        Returns {'id': int, 'action': 'updated'|'created'} or None on failure.
        """
        if itemtype not in self.SUPPORTED_ASSET_TYPES:
            logger.warning(f"Unsupported asset itemtype: {itemtype}")
            return None

        # 1. Trust the id we already recorded for this host.
        if known_id:
            if self.get_asset(itemtype, known_id) is not None:
                if self.update_asset(itemtype, known_id, fields) is not None:
                    return {'id': int(known_id), 'action': 'updated'}
            # id no longer resolvable (purged/renamed type) -> fall through.

        # 2. Adopt an existing live asset with the same name.
        name = fields.get('name')
        if name:
            found = self.find_active_asset_id_by_name(itemtype, name)
            if found:
                if self.update_asset(itemtype, found, fields) is not None:
                    return {'id': int(found), 'action': 'updated'}

        # 3. Create new.
        new_id = self.create_asset(itemtype, fields)
        if new_id:
            return {'id': int(new_id), 'action': 'created'}
        return None
    
    def create_or_update_computer(self, data: Dict[str, Any]) -> Optional[int]:
        """
        Create or update a computer in GLPI
        
        Args:
            data: Computer data including 'name', 'serial', etc.
            
        Returns:
            Computer ID
        """
        try:
            if not self.session_token and not self.init_session():
                return None
            
            # Check if exists by serial
            existing = None
            if data.get('serial'):
                existing = self.search_computer_by_serial(data['serial'])
            elif data.get('name'):
                existing = self.search_computer_by_name(data['name'])
            
            if existing:
                # Update existing
                computer_id = existing.get('2') or existing.get('id')
                if computer_id:
                    data['id'] = computer_id
                    response = requests.put(
                        f'{self.base_url}/Computer/{computer_id}',
                        headers=self._get_headers(),
                        json={'input': data},
                        timeout=self._request_timeout
                    )
                    if response.status_code == 200:
                        logger.info(f"Updated computer #{computer_id}")
                        return int(computer_id)
            else:
                # Create new
                data['entities_id'] = GLPI_ENTITY_ID
                response = requests.post(
                    f'{self.base_url}/Computer',
                    headers=self._get_headers(),
                    json={'input': data},
                    timeout=self._request_timeout
                )
                if response.status_code in [200, 201]:
                    result = response.json()
                    computer_id = result.get('id')
                    logger.info(f"Created computer #{computer_id}")
                    return computer_id
            
            return None
                
        except Exception as e:
            logger.error(f"Error creating/updating computer: {e}")
            return None
    
    # =========================================================================
    # SACM enrichment: structured dropdowns + network/IP
    # =========================================================================

    def get_or_create_dropdown(self, itemtype: str, name: str) -> Optional[int]:
        """
        Resolve a GLPI dropdown value (Manufacturer, OperatingSystem, Location,
        ComputerModel, ...) to an id, creating it if absent. Cached per session.

        Uses 'contains' search (not 'equals') because GLPI returns the completename
        for hierarchical types (Location, etc.) when using the search API, making
        'equals' silently return 0 results even when the entry exists.
        """
        name = (name or '').strip()
        if not name:
            return None
        ck = (itemtype, name.lower())
        if ck in self._dropdown_cache:
            return self._dropdown_cache[ck]
        rid = None
        try:
            if not self.session_token and not self.init_session():
                return None
            # Search with 'contains' then verify exact name match in results
            params = {
                'criteria[0][field]': 1, 'criteria[0][searchtype]': 'contains',
                'criteria[0][value]': name, 'forcedisplay[0]': 1, 'forcedisplay[1]': 2,
                'range': '0-19',
            }
            r = requests.get(f'{self.base_url}/search/{itemtype}', headers=self._get_headers(),
                             params=params, timeout=self._request_timeout)
            if r.status_code in (200, 206):
                for row in (r.json().get('data') or []):
                    if str(row.get('1', '')).strip().lower() == name.lower() and row.get('2'):
                        rid = int(row['2'])
                        break
            if rid is None:
                rr = requests.post(f'{self.base_url}/{itemtype}', headers=self._get_headers(),
                                   json={'input': {'name': name, 'entities_id': 0}},
                                   timeout=self._request_timeout)
                if rr.status_code in (200, 201):
                    rid = int(rr.json().get('id', 0)) or None
                elif rr.status_code == 400:
                    # Already exists (duplicate key); re-fetch via direct list
                    rl = requests.get(f'{self.base_url}/{itemtype}', headers=self._get_headers(),
                                      params={'searchText[name]': name, 'range': '0-20'},
                                      timeout=self._request_timeout)
                    if rl.status_code == 200:
                        for row in (rl.json() if isinstance(rl.json(), list) else []):
                            if row.get('name', '').lower() == name.lower():
                                rid = int(row['id'])
                                break
        except Exception as e:
            logger.warning(f"dropdown resolve {itemtype}='{name}' failed: {e}")
        self._dropdown_cache[ck] = rid
        return rid

    def _children(self, parent_type: str, parent_id: int, child_type: str) -> List[Dict[str, Any]]:
        """List sub-items (e.g. NetworkName under a NetworkPort), paginating to get all."""
        results: List[Dict[str, Any]] = []
        start = 0
        limit = 100
        try:
            while True:
                r = requests.get(
                    f'{self.base_url}/{parent_type}/{parent_id}/{child_type}',
                    headers=self._get_headers(),
                    params={'range': f'{start}-{start + limit - 1}'},
                    timeout=self._request_timeout,
                )
                if r.status_code not in (200, 206):
                    break
                batch = r.json()
                if not isinstance(batch, list):
                    break
                results.extend(batch)
                if len(batch) < limit:
                    break
                start += limit
        except Exception:
            pass
        return results

    def set_asset_ip(self, itemtype: str, asset_id: int, ip: str,
                     port_name: str = 'Zabbix-managed') -> bool:
        """
        Idempotently record an asset's management IP as the standard GLPI chain
        NetworkPort -> NetworkName -> IPAddress. Re-running reuses the single
        port named `port_name` (and its name/IP), so no duplicate ports or IP
        rows accumulate.
        """
        ip = (ip or '').strip()
        if not ip or not asset_id:
            return False
        try:
            if not self.session_token and not self.init_session():
                return False

            # 1. NetworkPort (reuse our marker port if present)
            port_id = next((p['id'] for p in self._children(itemtype, asset_id, 'NetworkPort')
                            if p.get('name') == port_name), None)
            if port_id is None:
                pr = requests.post(f'{self.base_url}/NetworkPort', headers=self._get_headers(),
                                   json={'input': {
                                       'items_id': asset_id, 'itemtype': itemtype,
                                       'name': port_name, 'logical_number': 1,
                                       'instantiation_type': 'NetworkPortEthernet',
                                   }}, timeout=self._request_timeout)
                if pr.status_code not in (200, 201):
                    return False
                port_id = pr.json().get('id')

            # 2. NetworkName under the port
            name_id = next((n['id'] for n in self._children('NetworkPort', port_id, 'NetworkName')), None)
            if name_id is None:
                nr = requests.post(f'{self.base_url}/NetworkName', headers=self._get_headers(),
                                   json={'input': {
                                       'items_id': port_id, 'itemtype': 'NetworkPort',
                                       'name': port_name,
                                   }}, timeout=self._request_timeout)
                if nr.status_code not in (200, 201):
                    return False
                name_id = nr.json().get('id')

            # 3. IPAddress under the name (skip if this IP is already present)
            existing_ips = {i.get('name') for i in self._children('NetworkName', name_id, 'IPAddress')}
            if ip in existing_ips:
                return True
            ir = requests.post(f'{self.base_url}/IPAddress', headers=self._get_headers(),
                               json={'input': {
                                   'items_id': name_id, 'itemtype': 'NetworkName', 'name': ip,
                               }}, timeout=self._request_timeout)
            return ir.status_code in (200, 201)
        except Exception as e:
            logger.warning(f"set_asset_ip {itemtype}#{asset_id} {ip} failed: {e}")
            return False

    def sync_network_ports(self, itemtype: str, asset_id: int,
                           interfaces: Dict[str, Any]) -> None:
        """
        Idempotently sync discovered network interfaces as GLPI NetworkPort records.

        Existing ports are matched by name and updated in place; missing ones are
        created. The management port ('Zabbix-managed') is always left untouched.

        Each port receives: speed, duplex, in/out bytes, in/out errors, oper status.

        Args:
            itemtype:   'NetworkEquipment' (or 'Computer' for server NICs)
            asset_id:   GLPI asset id
            interfaces: dict from ZabbixClient.get_network_interfaces()
        """
        # Zabbix dot3StatsDuplexStatus and GLPI portduplex use the SAME numeric scale:
        #   0/1 = unknown (not shown), 2 = Half (orange), 3 = Full
        # Pass the Zabbix value through unchanged; unknown/missing → 0 (no badge)
        _DUPLEX = {0: 0, 1: 0, 2: 2, 3: 3}

        if not interfaces or not asset_id:
            return
        try:
            if not self.session_token and not self.init_session():
                return

            existing = self._children(itemtype, asset_id, 'NetworkPort')
            existing_by_name = {p['name']: p['id'] for p in existing
                                if p.get('name') and p['name'] != 'Zabbix-managed'}

            created = updated = 0
            for idx, (iface_name, idata) in enumerate(sorted(interfaces.items())):
                oper  = idata.get('oper_status', 0)
                alias = (idata.get('alias') or '').strip()

                payload = {
                    'items_id': asset_id,
                    'itemtype': itemtype,
                    'logical_number': idx + 2,  # port 1 = Zabbix-managed mgmt
                    'name': iface_name,
                    'instantiation_type': 'NetworkPortEthernet',
                    'ifdescr': iface_name,
                    'ifalias': alias,
                    'comment': alias or None,
                    # Operational / internal status (1=up, 2=down)
                    'ifstatus': oper,
                    'ifinternalstatus': oper,
                    # Physical connection badge: 1=green "Connected", 0=red "Not Connected"
                    'ifconnectionstatus': 1 if oper == 1 else 0,
                    # Performance counters
                    'ifspeed': idata.get('speed', 0),
                    'portduplex': _DUPLEX.get(idata.get('duplex', 0), 0),
                    'ifinbytes': idata.get('in_bytes', 0),
                    'ifoutbytes': idata.get('out_bytes', 0),
                    'ifinerrors': idata.get('in_errors', 0),
                    'ifouterrors': idata.get('out_errors', 0),
                }

                if iface_name in existing_by_name:
                    port_id = existing_by_name[iface_name]
                    payload['id'] = port_id
                    r = requests.put(f'{self.base_url}/NetworkPort/{port_id}',
                                     headers=self._get_headers(),
                                     json={'input': payload},
                                     timeout=self._request_timeout)
                    if r.status_code == 200:
                        updated += 1
                else:
                    r = requests.post(f'{self.base_url}/NetworkPort',
                                      headers=self._get_headers(),
                                      json={'input': payload},
                                      timeout=self._request_timeout)
                    if r.status_code in (200, 201):
                        created += 1

            logger.info(f"NetworkPorts {itemtype}#{asset_id}: "
                        f"created={created} updated={updated} total={len(interfaces)}")
        except Exception as e:
            logger.warning(f"sync_network_ports {itemtype}#{asset_id} failed: {e}")

    def sync_volumes(self, itemtype: str, asset_id: int,
                     volumes: List[Dict[str, Any]]) -> None:
        """
        Idempotently sync disk volumes to GLPI Item_Disk (Volumes tab).

        volumes: list of {name, mountpoint, fstype, totalsize_mb, freesize_mb}
        Matches existing records by mountpoint name; PUTs if found, POSTs if new.
        """
        if not volumes or not asset_id:
            return
        try:
            if not self.session_token and not self.init_session():
                return

            # Fetch existing disk records for this asset
            existing = self._children(itemtype, asset_id, 'Item_Disk')
            existing_by_mp = {
                d['mountpoint']: d['id']
                for d in existing
                if d and d.get('mountpoint')
            }

            created = updated = 0
            for vol in volumes:
                mp   = (vol.get('mountpoint') or vol.get('name') or '').strip()
                name = (vol.get('name') or mp).strip()
                if not mp:
                    continue

                fstype = (vol.get('fstype') or '').strip()
                fs_id  = 0
                if fstype:
                    fs_id = self.get_or_create_dropdown('Filesystem', fstype) or 0

                payload = {
                    'itemtype':       itemtype,
                    'items_id':       asset_id,
                    'name':           name,
                    'device':         name,
                    'mountpoint':     mp,
                    'filesystems_id': fs_id,
                    'totalsize':      vol.get('totalsize_mb', 0),
                    'freesize':       vol.get('freesize_mb', 0),
                    'is_dynamic':     1,
                }

                if mp in existing_by_mp:
                    disk_id = existing_by_mp[mp]
                    payload['id'] = disk_id
                    r = requests.put(f'{self.base_url}/Item_Disk/{disk_id}',
                                     headers=self._get_headers(),
                                     json={'input': payload},
                                     timeout=self._request_timeout)
                    if r.status_code == 200:
                        updated += 1
                else:
                    r = requests.post(f'{self.base_url}/Item_Disk',
                                      headers=self._get_headers(),
                                      json={'input': payload},
                                      timeout=self._request_timeout)
                    if r.status_code in (200, 201):
                        created += 1

            logger.info(f"Volumes {itemtype}#{asset_id}: "
                        f"created={created} updated={updated} total={len(volumes)}")
        except Exception as e:
            logger.warning(f"sync_volumes {itemtype}#{asset_id} failed: {e}")

    def set_operating_system(self, itemtype: str, asset_id: int, os_name: str,
                             os_version: Optional[str] = None,
                             os_arch: Optional[str] = None,
                             os_kernel: Optional[str] = None,
                             os_edition: Optional[str] = None,
                             hostname: Optional[str] = None,
                             company: Optional[str] = None) -> bool:
        """
        Idempotently link an OperatingSystem (+ all details) to an asset via
        GLPI 10+ relation table (glpi_items_operatingsystems).

        Fills: name, version, architecture, kernel version, edition, hostname,
        company — covering every visible field on the GLPI OS tab.
        """
        os_name = (os_name or '').strip()
        if not os_name or not asset_id:
            return False
        try:
            if not self.session_token and not self.init_session():
                return False
            os_id = self.get_or_create_dropdown('OperatingSystem', os_name)
            if not os_id:
                return False

            payload: Dict[str, Any] = {
                'items_id': asset_id,
                'itemtype': itemtype,
                'operatingsystems_id': os_id,
            }
            if os_version:
                vid = self.get_or_create_dropdown('OperatingSystemVersion', os_version)
                if vid:
                    payload['operatingsystemversions_id'] = vid
            if os_arch:
                aid = self.get_or_create_dropdown('OperatingSystemArchitecture', os_arch)
                if aid:
                    payload['operatingsystemarchitectures_id'] = aid
            if os_kernel:
                kid = self.get_or_create_dropdown('OperatingSystemKernelVersion', os_kernel)
                if kid:
                    payload['operatingsystemkernelversions_id'] = kid
            if os_edition:
                eid = self.get_or_create_dropdown('OperatingSystemEdition', os_edition)
                if eid:
                    payload['operatingsystemeditions_id'] = eid
            if hostname:
                payload['hostid'] = hostname
            if company:
                payload['company'] = company

            existing = self._children(itemtype, asset_id, 'Item_OperatingSystem')
            if existing:
                rid = existing[0].get('id')
                payload['id'] = rid
                r = requests.put(f'{self.base_url}/Item_OperatingSystem/{rid}',
                                 headers=self._get_headers(), json={'input': payload},
                                 timeout=self._request_timeout)
                return r.status_code == 200
            r = requests.post(f'{self.base_url}/Item_OperatingSystem',
                              headers=self._get_headers(), json={'input': payload},
                              timeout=self._request_timeout)
            return r.status_code in (200, 201)
        except Exception as e:
            logger.warning(f"set_operating_system {itemtype}#{asset_id} '{os_name}' failed: {e}")
            return False

    def get_all_computers(self, fields: List[str] = None) -> List[Dict[str, Any]]:
        """Get all computers from GLPI"""
        try:
            if not self.session_token and not self.init_session():
                return []
            
            computers = []
            start = 0
            limit = 100
            
            while True:
                params = {
                    'range': f'{start}-{start + limit - 1}',
                    'expand_dropdowns': 'false',
                }
                
                response = requests.get(
                    f'{self.base_url}/Computer',
                    headers=self._get_headers(),
                    params=params,
                    timeout=self._request_timeout
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list):
                        computers.extend(data)
                        if len(data) < limit:
                            break
                        start += limit
                    else:
                        break
                else:
                    break
            
            return computers
                
        except Exception as e:
            logger.error(f"Error getting computers: {e}")
            return []

    # -------------------------------------------------------------------------
    # SNMP Credential helpers
    # -------------------------------------------------------------------------

    _SNMP_CRED_CACHE: Dict[str, int] = {}  # "v{version}:{community}" → id

    def get_or_create_snmp_credential(self, version: str, community: str) -> Optional[int]:
        """
        Resolve or create an SNMP credential in GLPI.

        version  — '1', '2' (v2c), or '3'
        community — e.g. 'public'

        GLPI SNMPCredential uses snmpversion '1', '2', '3'.  v2c is stored as '2'.
        """
        community = (community or 'public').strip()
        cache_key = f'v{version}:{community}'
        if cache_key in self._SNMP_CRED_CACHE:
            return self._SNMP_CRED_CACHE[cache_key]
        try:
            if not self.session_token and not self.init_session():
                return None
            # List all credentials and find exact match
            r = requests.get(f'{self.base_url}/SNMPCredential', headers=self._get_headers(),
                             params={'range': '0-100'}, timeout=self._request_timeout)
            if r.status_code == 200:
                for cred in (r.json() if isinstance(r.json(), list) else []):
                    if (str(cred.get('snmpversion', '')) == str(version) and
                            (cred.get('community') or '').lower() == community.lower()):
                        cid = int(cred['id'])
                        self._SNMP_CRED_CACHE[cache_key] = cid
                        return cid
            # Create if not found
            payload = {
                'name': f'Public community v{version}c' if version != '1' else 'Public community v1',
                'snmpversion': str(version),
                'community': community,
            }
            rr = requests.post(f'{self.base_url}/SNMPCredential', headers=self._get_headers(),
                               json={'input': payload}, timeout=self._request_timeout)
            if rr.status_code in (200, 201):
                cid = int(rr.json().get('id', 0)) or None
                if cid:
                    self._SNMP_CRED_CACHE[cache_key] = cid
                return cid
        except Exception as e:
            logger.warning(f"SNMP credential resolve v{version}/{community} failed: {e}")
        return None

    _AUTO_UPDATE_SYS_CACHE: Dict[str, int] = {}

    def get_or_create_auto_update_system(self, name: str) -> Optional[int]:
        """Resolve or create an AutoUpdateSystem entry (inventory source label)."""
        name = (name or '').strip()
        if not name:
            return None
        if name in self._AUTO_UPDATE_SYS_CACHE:
            return self._AUTO_UPDATE_SYS_CACHE[name]
        try:
            if not self.session_token and not self.init_session():
                return None
            r = requests.get(f'{self.base_url}/AutoUpdateSystem', headers=self._get_headers(),
                             params={'range': '0-50'}, timeout=self._request_timeout)
            if r.status_code == 200:
                for sys_item in (r.json() if isinstance(r.json(), list) else []):
                    if sys_item.get('name', '').lower() == name.lower():
                        sid = int(sys_item['id'])
                        self._AUTO_UPDATE_SYS_CACHE[name] = sid
                        return sid
            rr = requests.post(f'{self.base_url}/AutoUpdateSystem', headers=self._get_headers(),
                               json={'input': {'name': name}}, timeout=self._request_timeout)
            if rr.status_code in (200, 201):
                sid = int(rr.json().get('id', 0)) or None
                if sid:
                    self._AUTO_UPDATE_SYS_CACHE[name] = sid
                return sid
        except Exception as e:
            logger.warning(f"AutoUpdateSystem resolve '{name}' failed: {e}")
        return None
