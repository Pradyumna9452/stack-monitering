#!/usr/bin/env python3
"""
Database module for Zabbix-GLPI Integration
Stores event-to-ticket mappings for lifecycle management
"""

import os
import sqlite3
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

from config import DATABASE_PATH

logger = logging.getLogger(__name__)


def init_database():
    """Initialize the SQLite database with required tables"""
    try:
        # Ensure directory exists
        db_dir = os.path.dirname(DATABASE_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Event-Ticket mapping table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS event_ticket_map (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    zabbix_event_id TEXT UNIQUE NOT NULL,
                    glpi_ticket_id INTEGER NOT NULL,
                    host_name TEXT,
                    trigger_name TEXT,
                    severity INTEGER,
                    status TEXT DEFAULT 'open',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    closed_at TIMESTAMP,
                    recovery_event_id TEXT,
                    glpi_asset_id INTEGER,
                    glpi_asset_type TEXT
                )
            ''')
            
            # Asset sync tracking table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS asset_sync (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    zabbix_host_id TEXT UNIQUE NOT NULL,
                    zabbix_host_name TEXT NOT NULL,
                    glpi_computer_id INTEGER,
                    glpi_itemtype TEXT DEFAULT 'Computer',
                    last_synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    sync_status TEXT DEFAULT 'synced',
                    sync_error TEXT
                )
            ''')
            
            # Sync history table for auditing
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sync_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sync_type TEXT NOT NULL,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    hosts_processed INTEGER DEFAULT 0,
                    hosts_created INTEGER DEFAULT 0,
                    hosts_updated INTEGER DEFAULT 0,
                    errors INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'running',
                    details TEXT
                )
            ''')
            
            # Create indexes for faster lookups
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_event_id ON event_ticket_map(zabbix_event_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_ticket_id ON event_ticket_map(glpi_ticket_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_status ON event_ticket_map(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_host_id ON asset_sync(zabbix_host_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_glpi_id ON asset_sync(glpi_computer_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_host_trigger ON event_ticket_map(host_name, trigger_name, created_at)')

            # One-time cleanup: collapse any pre-existing duplicate ACTIVE tickets
            # (legacy data created before atomic dedup) down to the newest one per
            # (host, trigger) so the unique index below can be built.
            cursor.execute('''
                UPDATE event_ticket_map
                SET status = 'closed',
                    closed_at = COALESCE(closed_at, CURRENT_TIMESTAMP),
                    updated_at = CURRENT_TIMESTAMP
                WHERE status IN ('open', 'reserving', 'closing')
                  AND id NOT IN (
                    SELECT MAX(id) FROM event_ticket_map
                    WHERE status IN ('open', 'reserving', 'closing')
                    GROUP BY host_name, trigger_name
                  )
            ''')
            if cursor.rowcount:
                logger.warning(f"Closed {cursor.rowcount} legacy duplicate active ticket mappings")

            # Enforce, at the database level, that only ONE active ticket can exist
            # per (host, trigger) at a time. 'reserving'/'closing' are transient
            # states held while a worker creates/closes a ticket; together with the
            # BEGIN IMMEDIATE transaction in reserve_or_get_ticket() this makes
            # ticket creation atomic and race-free across gunicorn workers.
            try:
                cursor.execute('''
                    CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_host_trigger
                    ON event_ticket_map(host_name, trigger_name)
                    WHERE status IN ('open', 'reserving', 'closing')
                ''')
            except sqlite3.Error as e:
                # Partial index unsupported, or a residual conflict: dedup still
                # works via the BEGIN IMMEDIATE transaction, so don't crash init.
                logger.warning(f"Could not create partial unique index: {e}")

            conn.commit()
            logger.info(f"Database initialized at {DATABASE_PATH}")
            
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise


@contextmanager
def get_db():
    """Get database connection context manager"""
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# =============================================================================
# Event-Ticket Mapping Functions
# =============================================================================

def save_event_ticket_mapping(
    zabbix_event_id: str,
    glpi_ticket_id: int,
    host_name: str = None,
    trigger_name: str = None,
    severity: int = None,
    glpi_asset_id: int = None,
    glpi_asset_type: str = None
) -> bool:
    """
    Save a mapping between a Zabbix event and GLPI ticket
    
    Args:
        zabbix_event_id: Zabbix event ID
        glpi_ticket_id: GLPI ticket ID
        host_name: Host name (optional, for reference)
        trigger_name: Trigger name (optional, for reference)
        severity: Zabbix severity level (optional)
        glpi_asset_id: GLPI asset ID if linked
        glpi_asset_type: GLPI asset type (e.g., 'Computer')
        
    Returns:
        True if saved successfully
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO event_ticket_map 
                (zabbix_event_id, glpi_ticket_id, host_name, trigger_name, severity, 
                 glpi_asset_id, glpi_asset_type, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'open')
                ON CONFLICT(zabbix_event_id) DO UPDATE SET
                    glpi_ticket_id = excluded.glpi_ticket_id,
                    updated_at = CURRENT_TIMESTAMP
            ''', (zabbix_event_id, glpi_ticket_id, host_name, trigger_name, severity,
                  glpi_asset_id, glpi_asset_type))
            conn.commit()
            logger.debug(f"Saved mapping: Event {zabbix_event_id} -> Ticket {glpi_ticket_id}")
            return True
    except Exception as e:
        logger.error(f"Failed to save event-ticket mapping: {e}")
        return False


def get_ticket_by_event_id(zabbix_event_id: str) -> Optional[Dict[str, Any]]:
    """
    Get GLPI ticket info by Zabbix event ID
    
    Args:
        zabbix_event_id: Zabbix event ID
        
    Returns:
        Mapping record or None
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM event_ticket_map WHERE zabbix_event_id = ?
            ''', (zabbix_event_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get ticket by event ID: {e}")
        return None


def get_open_ticket_by_host_trigger(host_name: str, trigger_name: str) -> Optional[Dict[str, Any]]:
    """
    Get an open ticket for a specific host and trigger combination
    Used to prevent duplicate tickets for the same ongoing issue
    
    Args:
        host_name: Zabbix host name
        trigger_name: Zabbix trigger name
        
    Returns:
        Mapping record or None
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM event_ticket_map 
                WHERE host_name = ? AND trigger_name = ? AND status = 'open'
                ORDER BY created_at DESC LIMIT 1
            ''', (host_name, trigger_name))
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get open ticket: {e}")
        return None


def reserve_or_get_ticket(
    zabbix_event_id: str,
    host_name: str,
    trigger_name: str,
    severity: int = None,
    glpi_asset_id: int = None,
    glpi_asset_type: str = None,
    cooldown_seconds: int = 0,
) -> tuple:
    """
    Atomically decide what to do for an incoming PROBLEM event.

    Runs inside a single BEGIN IMMEDIATE transaction so it is safe across
    concurrent gunicorn workers/threads (only one writer proceeds at a time).

    Returns a tuple (action, payload):
      ('exists',    mapping)  -> this exact event already has a ticket; do nothing
      ('duplicate', mapping)  -> an active ticket already exists for host/trigger; reuse it
      ('cooldown',  mapping)  -> a ticket for host/trigger was closed within the
                                 cooldown window; reuse (caller may reopen it)
      ('reserved',  row_id)   -> caller WON the race and must now create the GLPI
                                 ticket, then call finalize_reserved_ticket(row_id, ...)
                                 (or cancel_reservation(row_id) on failure)
    """
    conn = sqlite3.connect(DATABASE_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute('BEGIN IMMEDIATE')

        # 1) Exact same event already processed (e.g. Zabbix media-type retry)
        cur.execute('SELECT * FROM event_ticket_map WHERE zabbix_event_id = ?', (zabbix_event_id,))
        row = cur.fetchone()
        if row:
            cur.execute('COMMIT')
            return ('exists', dict(row))

        # 2) An active ticket already exists for this host/trigger
        cur.execute('''
            SELECT * FROM event_ticket_map
            WHERE host_name = ? AND trigger_name = ?
              AND status IN ('open', 'reserving', 'closing')
            ORDER BY created_at DESC LIMIT 1
        ''', (host_name, trigger_name))
        active = cur.fetchone()
        if active:
            cur.execute('COMMIT')
            return ('duplicate', dict(active))

        # 3) A ticket for this host/trigger was closed very recently -> reuse it
        if cooldown_seconds and cooldown_seconds > 0:
            cur.execute('''
                SELECT * FROM event_ticket_map
                WHERE host_name = ? AND trigger_name = ? AND status = 'closed'
                  AND (julianday('now') - julianday(COALESCE(closed_at, updated_at))) * 86400.0 <= ?
                ORDER BY COALESCE(closed_at, updated_at) DESC LIMIT 1
            ''', (host_name, trigger_name, cooldown_seconds))
            recent = cur.fetchone()
            if recent:
                cur.execute('COMMIT')
                return ('cooldown', dict(recent))

        # 4) Nothing exists -> reserve a slot (placeholder ticket id 0)
        cur.execute('''
            INSERT INTO event_ticket_map
                (zabbix_event_id, glpi_ticket_id, host_name, trigger_name, severity,
                 glpi_asset_id, glpi_asset_type, status)
            VALUES (?, 0, ?, ?, ?, ?, ?, 'reserving')
        ''', (zabbix_event_id, host_name, trigger_name, severity, glpi_asset_id, glpi_asset_type))
        row_id = cur.lastrowid
        cur.execute('COMMIT')
        return ('reserved', row_id)

    except sqlite3.IntegrityError:
        # Lost the race to a concurrent worker (unique index violation).
        try:
            conn.execute('ROLLBACK')
        except Exception:
            pass
        existing = get_ticket_by_event_id(zabbix_event_id) or \
            get_open_ticket_by_host_trigger(host_name, trigger_name)
        return ('duplicate', existing)
    except Exception as e:
        try:
            conn.execute('ROLLBACK')
        except Exception:
            pass
        logger.error(f"reserve_or_get_ticket failed: {e}")
        return ('error', None)
    finally:
        conn.close()


def finalize_reserved_ticket(row_id: int, glpi_ticket_id: int) -> bool:
    """Attach the real GLPI ticket id to a reserved row and mark it open."""
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute('''
                UPDATE event_ticket_map
                SET glpi_ticket_id = ?, status = 'open', updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'reserving'
            ''', (glpi_ticket_id, row_id))
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to finalize reserved ticket: {e}")
        return False


def cancel_reservation(row_id: int) -> bool:
    """Remove a reservation row if GLPI ticket creation failed (frees the slot)."""
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM event_ticket_map WHERE id = ? AND status = 'reserving'", (row_id,))
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to cancel reservation: {e}")
        return False


def reopen_ticket_mapping(row_id: int, zabbix_event_id: str = None) -> bool:
    """Mark a previously closed mapping as open again (recurrence within cooldown)."""
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute('''
                UPDATE event_ticket_map
                SET status = 'open', closed_at = NULL, recovery_event_id = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (row_id,))
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to reopen ticket mapping: {e}")
        return False


def force_new_reservation(
    zabbix_event_id: str,
    host_name: str,
    trigger_name: str,
    severity: int = None,
    glpi_asset_id: int = None,
    glpi_asset_type: str = None,
) -> Optional[int]:
    """
    Insert a new reservation row bypassing all dedup checks.
    Used when an existing ticket has exceeded the followup cap.
    Returns the new row_id, or None on failure.
    """
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO event_ticket_map
                    (zabbix_event_id, glpi_ticket_id, host_name, trigger_name, severity,
                     glpi_asset_id, glpi_asset_type, status)
                VALUES (?, 0, ?, ?, ?, ?, ?, 'reserving')
            ''', (zabbix_event_id, host_name, trigger_name, severity,
                  glpi_asset_id, glpi_asset_type))
            conn.commit()
            return cur.lastrowid
    except sqlite3.IntegrityError:
        logger.warning(f"force_new_reservation: event {zabbix_event_id} already in db")
        return None
    except Exception as e:
        logger.error(f"force_new_reservation failed: {e}")
        return None


def claim_ticket_for_closure(
    zabbix_event_id: str = None,
    host_name: str = None,
    trigger_name: str = None,
) -> Optional[Dict[str, Any]]:
    """
    Atomically claim an OPEN ticket for closure (open -> closing).

    Guarantees that only ONE recovery event ever closes a given ticket, so a
    duplicate/retried RECOVERY will get None and skip the GLPI close call.

    Returns the claimed mapping (with its prior 'open' state) or None if there is
    no open ticket to close.
    """
    conn = sqlite3.connect(DATABASE_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute('BEGIN IMMEDIATE')

        row = None
        if zabbix_event_id:
            cur.execute(
                "SELECT * FROM event_ticket_map WHERE zabbix_event_id = ? AND status = 'open'",
                (zabbix_event_id,),
            )
            row = cur.fetchone()
        if not row and host_name and trigger_name:
            cur.execute('''
                SELECT * FROM event_ticket_map
                WHERE host_name = ? AND trigger_name = ? AND status = 'open'
                ORDER BY created_at DESC LIMIT 1
            ''', (host_name, trigger_name))
            row = cur.fetchone()

        if not row:
            cur.execute('COMMIT')
            return None

        cur.execute(
            "UPDATE event_ticket_map SET status = 'closing', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (row['id'],),
        )
        cur.execute('COMMIT')
        return dict(row)
    except Exception as e:
        try:
            conn.execute('ROLLBACK')
        except Exception:
            pass
        logger.error(f"claim_ticket_for_closure failed: {e}")
        return None
    finally:
        conn.close()


def revert_closing(row_id: int) -> bool:
    """Put a ticket back to 'open' if the GLPI close call failed (allow retry)."""
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE event_ticket_map SET status = 'open', updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'closing'",
                (row_id,),
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to revert closing state: {e}")
        return False


def close_ticket_mapping(
    zabbix_event_id: str = None,
    glpi_ticket_id: int = None,
    recovery_event_id: str = None
) -> bool:
    """
    Mark a ticket mapping as closed
    
    Args:
        zabbix_event_id: Original Zabbix event ID (optional)
        glpi_ticket_id: GLPI ticket ID (optional)
        recovery_event_id: Zabbix recovery event ID (optional)
        
    Returns:
        True if successful
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            
            if zabbix_event_id:
                cursor.execute('''
                    UPDATE event_ticket_map 
                    SET status = 'closed', 
                        closed_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP,
                        recovery_event_id = ?
                    WHERE zabbix_event_id = ?
                ''', (recovery_event_id, zabbix_event_id))
            elif glpi_ticket_id:
                cursor.execute('''
                    UPDATE event_ticket_map 
                    SET status = 'closed', 
                        closed_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP,
                        recovery_event_id = ?
                    WHERE glpi_ticket_id = ?
                ''', (recovery_event_id, glpi_ticket_id))
            
            conn.commit()
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to close ticket mapping: {e}")
        return False


def get_open_tickets() -> List[Dict[str, Any]]:
    """Get all open ticket mappings"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM event_ticket_map WHERE status = 'open'
            ''')
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get open tickets: {e}")
        return []


# =============================================================================
# Asset Sync Functions
# =============================================================================

def save_asset_mapping(
    zabbix_host_id: str,
    zabbix_host_name: str,
    glpi_computer_id: int,
    glpi_itemtype: str = 'Computer'
) -> bool:
    """Save asset mapping between Zabbix host and GLPI computer"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO asset_sync 
                (zabbix_host_id, zabbix_host_name, glpi_computer_id, glpi_itemtype, 
                 last_synced_at, sync_status)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, 'synced')
                ON CONFLICT(zabbix_host_id) DO UPDATE SET
                    zabbix_host_name = excluded.zabbix_host_name,
                    glpi_computer_id = excluded.glpi_computer_id,
                    glpi_itemtype = excluded.glpi_itemtype,
                    last_synced_at = CURRENT_TIMESTAMP,
                    sync_status = 'synced',
                    sync_error = NULL
            ''', (zabbix_host_id, zabbix_host_name, glpi_computer_id, glpi_itemtype))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Failed to save asset mapping: {e}")
        return False


def get_glpi_asset_by_host_name(host_name: str) -> Optional[Dict[str, Any]]:
    """Get GLPI asset info by Zabbix host name"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM asset_sync WHERE zabbix_host_name = ?
            ''', (host_name,))
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get asset by host name: {e}")
        return None


def get_glpi_asset_by_host_id(host_id: str) -> Optional[Dict[str, Any]]:
    """Get GLPI asset info by Zabbix host ID"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM asset_sync WHERE zabbix_host_id = ?
            ''', (host_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get asset by host ID: {e}")
        return None


def get_all_asset_mappings() -> List[Dict[str, Any]]:
    """Get all asset mappings"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM asset_sync')
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get asset mappings: {e}")
        return []


# =============================================================================
# Sync History Functions
# =============================================================================

def start_sync_session(sync_type: str) -> int:
    """Start a new sync session and return its ID"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO sync_history (sync_type, status)
                VALUES (?, 'running')
            ''', (sync_type,))
            conn.commit()
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"Failed to start sync session: {e}")
        return 0


def complete_sync_session(
    session_id: int,
    hosts_processed: int = 0,
    hosts_created: int = 0,
    hosts_updated: int = 0,
    errors: int = 0,
    status: str = 'completed',
    details: str = None
):
    """Complete a sync session with results"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE sync_history 
                SET completed_at = CURRENT_TIMESTAMP,
                    hosts_processed = ?,
                    hosts_created = ?,
                    hosts_updated = ?,
                    errors = ?,
                    status = ?,
                    details = ?
                WHERE id = ?
            ''', (hosts_processed, hosts_created, hosts_updated, errors, status, details, session_id))
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to complete sync session: {e}")


def get_last_sync(sync_type: str) -> Optional[Dict[str, Any]]:
    """Get the last sync session of a given type"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM sync_history 
                WHERE sync_type = ? 
                ORDER BY started_at DESC LIMIT 1
            ''', (sync_type,))
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get last sync: {e}")
        return None


# =============================================================================
# Statistics Functions
# =============================================================================

def get_statistics() -> Dict[str, Any]:
    """Get integration statistics"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Total tickets created
            cursor.execute('SELECT COUNT(*) FROM event_ticket_map')
            total_tickets = cursor.fetchone()[0]
            
            # Open tickets
            cursor.execute("SELECT COUNT(*) FROM event_ticket_map WHERE status = 'open'")
            open_tickets = cursor.fetchone()[0]
            
            # Closed tickets
            cursor.execute("SELECT COUNT(*) FROM event_ticket_map WHERE status = 'closed'")
            closed_tickets = cursor.fetchone()[0]
            
            # Total synced assets
            cursor.execute('SELECT COUNT(*) FROM asset_sync')
            total_assets = cursor.fetchone()[0]
            
            # Last sync
            last_sync = get_last_sync('inventory')
            
            return {
                'total_tickets_created': total_tickets,
                'open_tickets': open_tickets,
                'closed_tickets': closed_tickets,
                'synced_assets': total_assets,
                'last_inventory_sync': last_sync['completed_at'] if last_sync else None,
            }
    except Exception as e:
        logger.error(f"Failed to get statistics: {e}")
        return {}
