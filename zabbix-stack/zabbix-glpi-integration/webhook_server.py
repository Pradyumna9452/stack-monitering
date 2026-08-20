#!/usr/bin/env python3
"""
Zabbix-GLPI Integration Webhook Server
Full automated ticket lifecycle management with no human intervention

Features:
- Creates GLPI tickets on Zabbix PROBLEM events
- Auto-acknowledges events in Zabbix when ticket is created
- Links tickets to pre-synced assets
- Closes tickets with solution on RECOVERY events
- Deduplication to prevent multiple tickets for same issue
"""

import os
import sys
import json
import logging
from datetime import datetime
from flask import Flask, request, jsonify

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    WEBHOOK_PORT, WEBHOOK_HOST, LOG_LEVEL, LOG_FORMAT,
    SEVERITY_TO_URGENCY, SEVERITY_NAME_TO_URGENCY, GLPI_STATUS,
    AUTO_ACKNOWLEDGE_ENABLED, AUTO_ACKNOWLEDGE_MESSAGE,
    DEDUP_COOLDOWN_SECONDS, REOPEN_ON_RECURRENCE, ADD_RECURRENCE_FOLLOWUP,
    MIN_SEVERITY, MAX_TICKET_FOLLOWUPS
)
from glpi_client import GLPIClient
from zabbix_client import ZabbixClient
from database import (
    init_database, get_ticket_by_event_id,
    get_open_ticket_by_host_trigger, close_ticket_mapping,
    get_glpi_asset_by_host_name, get_statistics,
    reserve_or_get_ticket, finalize_reserved_ticket, cancel_reservation,
    reopen_ticket_mapping, claim_ticket_for_closure, revert_closing,
    force_new_reservation,
)

# Configure logging
logging.basicConfig(level=getattr(logging, LOG_LEVEL), format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Initialize database
init_database()


def get_urgency(severity) -> int:
    """Map Zabbix severity to GLPI urgency"""
    if isinstance(severity, int):
        return SEVERITY_TO_URGENCY.get(severity, 3)
    elif isinstance(severity, str):
        # Try numeric string first
        try:
            return SEVERITY_TO_URGENCY.get(int(severity), 3)
        except ValueError:
            return SEVERITY_NAME_TO_URGENCY.get(severity, 3)
    return 3


def build_ticket_content(data: dict, event_type: str = 'problem') -> str:
    """Build HTML content for GLPI ticket"""
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
    
    if event_type == 'problem':
        return f"""
<h3>🚨 Zabbix Alert - Problem Detected</h3>
<table border="1" cellpadding="5" cellspacing="0">
    <tr><td><strong>Host</strong></td><td>{data.get('host', 'Unknown')}</td></tr>
    <tr><td><strong>Trigger</strong></td><td>{data.get('trigger', data.get('trigger_name', 'Unknown'))}</td></tr>
    <tr><td><strong>Severity</strong></td><td>{data.get('severity', 'Unknown')}</td></tr>
    <tr><td><strong>Event ID</strong></td><td>{data.get('event_id', 'N/A')}</td></tr>
    <tr><td><strong>Trigger ID</strong></td><td>{data.get('trigger_id', 'N/A')}</td></tr>
    <tr><td><strong>Host ID</strong></td><td>{data.get('host_id', 'N/A')}</td></tr>
    <tr><td><strong>Time</strong></td><td>{data.get('event_time', timestamp)}</td></tr>
    <tr><td><strong>IP Address</strong></td><td>{data.get('ip_address', 'N/A')}</td></tr>
</table>
<h4>Description</h4>
<p>{data.get('description', data.get('trigger_description', 'No description provided'))}</p>
<h4>Operational Data</h4>
<p>{data.get('operational_data', 'N/A')}</p>
<hr>
<p><em>This ticket was automatically created by Zabbix-GLPI Integration.</em></p>
"""
    else:
        return f"""
<h3>✅ Issue Resolved</h3>
<table border="1" cellpadding="5" cellspacing="0">
    <tr><td><strong>Host</strong></td><td>{data.get('host', 'Unknown')}</td></tr>
    <tr><td><strong>Trigger</strong></td><td>{data.get('trigger', data.get('trigger_name', 'Unknown'))}</td></tr>
    <tr><td><strong>Recovery Time</strong></td><td>{data.get('recovery_time', timestamp)}</td></tr>
    <tr><td><strong>Duration</strong></td><td>{data.get('duration', 'N/A')}</td></tr>
</table>
<p><em>This issue has been automatically resolved.</em></p>
"""


def handle_problem(data: dict) -> dict:
    """
    Handle PROBLEM event - Create ticket and auto-acknowledge
    
    Expected data fields:
    - event_id: Zabbix event ID
    - host: Host name
    - host_id: Host ID
    - trigger: Trigger name
    - trigger_id: Trigger ID
    - severity: Severity level (0-5 or name)
    - description: Trigger description
    - ip_address: Host IP (optional)
    - operational_data: Additional data (optional)
    """
    event_id = data.get('event_id')
    host_name = data.get('host', 'Unknown')
    trigger_name = data.get('trigger', data.get('trigger_name', 'Unknown'))
    severity = data.get('severity', 3)
    severity_int = int(severity) if str(severity).isdigit() else 3

    logger.info(f"Processing PROBLEM event {event_id} for {host_name}: {trigger_name}")

    if not event_id:
        return {'status': 'error', 'message': 'Missing event_id'}

    # -------------------------------------------------------------------------
    # Severity Filtering: Ignore "junk" tickets below the threshold
    # -------------------------------------------------------------------------
    if severity_int < MIN_SEVERITY:
        logger.info(f"Ignoring event {event_id} (severity {severity_int} is below MIN_SEVERITY {MIN_SEVERITY})")
        return {
            'status': 'ignored',
            'message': f'Severity {severity_int} is below threshold {MIN_SEVERITY}'
        }

    # Look up GLPI asset (read-only, safe to do before reserving)
    asset_info = get_glpi_asset_by_host_name(host_name)
    glpi_asset_id = asset_info['glpi_computer_id'] if asset_info else None
    glpi_asset_type = asset_info['glpi_itemtype'] if asset_info else None

    # -------------------------------------------------------------------------
    # Atomic deduplication: exactly one worker can win the right to create a
    # ticket for a given (host, trigger). Everyone else gets an existing one.
    # -------------------------------------------------------------------------
    action, payload = reserve_or_get_ticket(
        zabbix_event_id=event_id,
        host_name=host_name,
        trigger_name=trigger_name,
        severity=severity_int,
        glpi_asset_id=glpi_asset_id,
        glpi_asset_type=glpi_asset_type,
        cooldown_seconds=DEDUP_COOLDOWN_SECONDS,
    )

    if action == 'error':
        return {'status': 'error', 'message': 'Deduplication check failed'}

    # Same event already handled (e.g. Zabbix media-type retry)
    if action == 'exists':
        ticket_id = payload['glpi_ticket_id'] if payload else None
        logger.info(f"Ticket #{ticket_id} already exists for event {event_id}")
        return {'status': 'exists', 'ticket_id': ticket_id,
                'message': f"Ticket already exists for event {event_id}"}

    def _followup_cap_exceeded(ticket_id):
        """Return True if ticket has hit MAX_TICKET_FOLLOWUPS and a new ticket should be forced."""
        if not ticket_id or MAX_TICKET_FOLLOWUPS <= 0:
            return False
        try:
            with GLPIClient() as glpi:
                count = glpi.get_followup_count(ticket_id)
            if count >= MAX_TICKET_FOLLOWUPS:
                logger.warning(
                    f"Ticket #{ticket_id} has {count} followups (cap={MAX_TICKET_FOLLOWUPS}); "
                    f"forcing new ticket for {host_name}/{trigger_name}"
                )
                return True
        except Exception as e:
            logger.warning(f"Could not check followup count for ticket #{ticket_id}: {e}")
        return False

    # An active ticket already exists for this host/trigger -> suppress duplicate
    if action == 'duplicate':
        ticket_id = payload['glpi_ticket_id'] if payload else None
        logger.info(f"Duplicate suppressed: open ticket #{ticket_id} exists for {host_name}/{trigger_name}")
        if _followup_cap_exceeded(ticket_id):
            row_id = force_new_reservation(event_id, host_name, trigger_name,
                                           severity_int, glpi_asset_id, glpi_asset_type)
            if row_id:
                action = '_force_new'
        if action == 'duplicate':
            if ticket_id and ADD_RECURRENCE_FOLLOWUP:
                try:
                    with GLPIClient() as glpi:
                        glpi.add_followup(ticket_id,
                            f"<p>🔁 Problem recurred (event {event_id}) while this ticket was still open.</p>")
                except Exception as e:
                    logger.warning(f"Failed to add recurrence followup: {e}")
            _auto_acknowledge(event_id, ticket_id)
            return {'status': 'duplicate', 'ticket_id': ticket_id,
                    'message': 'Open ticket already exists for same host/trigger'}

    # A ticket for this host/trigger was closed within the cooldown -> reuse it
    if action == 'cooldown':
        ticket_id = payload['glpi_ticket_id'] if payload else None
        logger.info(f"Recurrence within cooldown: reusing ticket #{ticket_id} for {host_name}/{trigger_name}")
        if _followup_cap_exceeded(ticket_id):
            row_id = force_new_reservation(event_id, host_name, trigger_name,
                                           severity_int, glpi_asset_id, glpi_asset_type)
            if row_id:
                action = '_force_new'
        if action == 'cooldown':
            reopened = False
            if ticket_id and REOPEN_ON_RECURRENCE:
                try:
                    with GLPIClient() as glpi:
                        reopened = glpi.update_ticket(ticket_id, status=GLPI_STATUS['ASSIGNED'])
                        glpi.add_followup(ticket_id,
                            f"<p>🔁 Problem recurred (event {event_id}) within the dedup cooldown "
                            f"window; reopening this ticket instead of creating a new one.</p>")
                    if reopened:
                        reopen_ticket_mapping(payload['id'], event_id)
                except Exception as e:
                    logger.warning(f"Failed to reopen ticket #{ticket_id}: {e}")
            _auto_acknowledge(event_id, ticket_id)
            return {'status': 'reused', 'ticket_id': ticket_id, 'reopened': reopened,
                    'message': f'Reused recent ticket #{ticket_id} (cooldown)'}

    # action == 'reserved' or '_force_new': we own creation
    row_id = row_id if action == '_force_new' else payload
    ticket_title = f"[Zabbix] {host_name}: {trigger_name}"
    ticket_content = build_ticket_content(data, 'problem')
    urgency = get_urgency(severity)

    try:
        with GLPIClient() as glpi:
            ticket_id = glpi.create_ticket(
                name=ticket_title,
                content=ticket_content,
                urgency=urgency,
                priority=urgency,
                itemtype=glpi_asset_type,
                items_id=glpi_asset_id
            )
    except Exception as e:
        logger.error(f"Exception creating GLPI ticket for event {event_id}: {e}")
        ticket_id = None

    if not ticket_id:
        # Release the reservation so a later event can retry
        cancel_reservation(row_id)
        logger.error(f"Failed to create GLPI ticket for event {event_id}; reservation cancelled")
        return {'status': 'error', 'message': 'Failed to create GLPI ticket'}

    # Attach the real ticket id to the reserved row
    finalize_reserved_ticket(row_id, ticket_id)

    _auto_acknowledge(event_id, ticket_id)
    logger.info(f"Created GLPI ticket #{ticket_id} for event {event_id}")

    return {
        'status': 'created',
        'ticket_id': ticket_id,
        'event_id': event_id,
        'acknowledged': AUTO_ACKNOWLEDGE_ENABLED,
        'asset_linked': glpi_asset_id is not None,
        'message': f"Created ticket #{ticket_id}"
    }


def _auto_acknowledge(event_id, ticket_id):
    """Acknowledge a Zabbix event referencing its GLPI ticket (best-effort)."""
    if not (AUTO_ACKNOWLEDGE_ENABLED and event_id):
        return
    try:
        ack_message = AUTO_ACKNOWLEDGE_MESSAGE.format(ticket_id=ticket_id)
        with ZabbixClient() as zabbix:
            zabbix.acknowledge_event(
                event_ids=[event_id],
                message=ack_message,
                action=6  # Acknowledge + Add message
            )
        logger.info(f"Auto-acknowledged event {event_id} in Zabbix")
    except Exception as e:
        logger.warning(f"Failed to auto-acknowledge event {event_id}: {e}")


def handle_recovery(data: dict) -> dict:
    """
    Handle RECOVERY event - Close ticket with solution
    
    Expected data fields:
    - event_id: Original problem event ID
    - recovery_event_id: Recovery event ID
    - host: Host name
    - trigger: Trigger name
    - recovery_time: When the issue was resolved
    - duration: How long the issue lasted
    """
    event_id = data.get('event_id')
    recovery_event_id = data.get('recovery_event_id', event_id)
    host_name = data.get('host', 'Unknown')
    trigger_name = data.get('trigger', data.get('trigger_name', 'Unknown'))
    recovery_time = data.get('recovery_time', datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
    duration = data.get('duration', 'Unknown')
    
    logger.info(f"Processing RECOVERY for event {event_id}")

    # -------------------------------------------------------------------------
    # Atomically claim the open ticket for closure (open -> closing). Only ONE
    # recovery can win this, so duplicate/retried RECOVERY events become no-ops
    # and never re-close an already-closed ticket.
    # -------------------------------------------------------------------------
    mapping = claim_ticket_for_closure(
        zabbix_event_id=event_id,
        host_name=host_name,
        trigger_name=trigger_name,
    )

    if not mapping:
        # Either there was never a ticket, or it is already closed/closing.
        existing = get_ticket_by_event_id(event_id) or \
            get_open_ticket_by_host_trigger(host_name, trigger_name)
        if existing:
            logger.info(f"Ticket #{existing['glpi_ticket_id']} already closed/closing for event {event_id}")
            return {'status': 'already_closed', 'ticket_id': existing['glpi_ticket_id'],
                    'message': 'Ticket already closed; recovery ignored'}
        logger.warning(f"No open ticket found for event {event_id} or {host_name}/{trigger_name}")
        return {'status': 'not_found', 'message': 'No open ticket found for this event'}

    ticket_id = mapping['glpi_ticket_id']

    # Build solution text
    solution_content = f"""
<h3>✅ Issue Resolved Automatically</h3>
<table border="1" cellpadding="5" cellspacing="0">
    <tr><td><strong>Host</strong></td><td>{host_name}</td></tr>
    <tr><td><strong>Trigger</strong></td><td>{trigger_name}</td></tr>
    <tr><td><strong>Recovery Time</strong></td><td>{recovery_time}</td></tr>
    <tr><td><strong>Duration</strong></td><td>{duration}</td></tr>
    <tr><td><strong>Original Event ID</strong></td><td>{event_id}</td></tr>
    <tr><td><strong>Recovery Event ID</strong></td><td>{recovery_event_id}</td></tr>
</table>
<p>The monitored condition has returned to normal. This ticket has been automatically closed by the Zabbix-GLPI Integration.</p>
"""
    
    # Close the ticket in GLPI
    try:
        with GLPIClient() as glpi:
            # Add followup with recovery info
            glpi.add_followup(
                ticket_id=ticket_id,
                content=f"<p>🔔 <strong>Recovery notification received from Zabbix</strong></p>"
                        f"<p>The issue was resolved at {recovery_time}. Duration: {duration}</p>"
            )

            # Add solution and close
            success = glpi.close_ticket(ticket_id, solution_content)
    except Exception as e:
        logger.error(f"Exception closing GLPI ticket #{ticket_id}: {e}")
        success = False

    if success:
        # Mark our mapping closed (by the claimed row's own event id, so the
        # 'closing' -> 'closed' transition lands on exactly that row)
        close_ticket_mapping(
            zabbix_event_id=mapping['zabbix_event_id'],
            recovery_event_id=recovery_event_id
        )
        logger.info(f"Closed GLPI ticket #{ticket_id}")

        return {
            'status': 'closed',
            'ticket_id': ticket_id,
            'event_id': event_id,
            'message': f"Closed ticket #{ticket_id}"
        }
    else:
        # Roll the claim back to 'open' so a later recovery can retry the close
        revert_closing(mapping['id'])
        logger.error(f"Failed to close ticket #{ticket_id}; reverted to open for retry")
        return {
            'status': 'error',
            'ticket_id': ticket_id,
            'message': f"Failed to close ticket #{ticket_id}"
        }


def handle_update(data: dict) -> dict:
    """
    Handle UPDATE event - Add followup to existing ticket
    
    Used for:
    - Manual acknowledgments in Zabbix
    - Severity changes
    - Comments/messages
    """
    event_id = data.get('event_id')
    host_name = data.get('host', 'Unknown')
    trigger_name = data.get('trigger', data.get('trigger_name', 'Unknown'))
    message = data.get('message', data.get('ack_message', ''))
    user = data.get('user', data.get('ack_user', 'System'))
    
    logger.info(f"Processing UPDATE for event {event_id}")
    
    # Find the ticket
    mapping = get_ticket_by_event_id(event_id)
    if not mapping:
        mapping = get_open_ticket_by_host_trigger(host_name, trigger_name)
    
    if not mapping:
        logger.warning(f"No ticket found for event {event_id}")
        return {
            'status': 'not_found',
            'message': 'No ticket found for this event'
        }
    
    ticket_id = mapping['glpi_ticket_id']
    
    # Build followup content
    followup_content = f"""
<h4>🔄 Update from Zabbix</h4>
<table border="1" cellpadding="5" cellspacing="0">
    <tr><td><strong>User</strong></td><td>{user}</td></tr>
    <tr><td><strong>Event ID</strong></td><td>{event_id}</td></tr>
    <tr><td><strong>Time</strong></td><td>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</td></tr>
</table>
<p><strong>Message:</strong> {message if message else 'No message provided'}</p>
"""
    
    # Add followup to GLPI
    with GLPIClient() as glpi:
        followup_id = glpi.add_followup(ticket_id, followup_content)
    
    if followup_id:
        logger.info(f"Added followup to ticket #{ticket_id}")
        return {
            'status': 'updated',
            'ticket_id': ticket_id,
            'followup_id': followup_id,
            'message': f"Added followup to ticket #{ticket_id}"
        }
    else:
        return {
            'status': 'error',
            'ticket_id': ticket_id,
            'message': 'Failed to add followup'
        }


# =============================================================================
# Flask Routes
# =============================================================================

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'zabbix-glpi-integration',
        'timestamp': datetime.utcnow().isoformat()
    })


@app.route('/stats', methods=['GET'])
def stats():
    """Get integration statistics"""
    return jsonify(get_statistics())


@app.route('/webhook', methods=['POST'])
def webhook():
    """
    Main webhook endpoint for Zabbix alerts
    
    Expected payload:
    {
        "action": "problem" | "recovery" | "update",
        "event_id": "12345",
        "host": "server01",
        "host_id": "10001",
        "trigger": "CPU high",
        "trigger_id": "20001",
        "severity": "4" or "High",
        "status": "PROBLEM" | "OK",
        "description": "CPU usage > 90%",
        "ip_address": "192.168.1.100",
        "event_time": "2024-01-15 10:30:00",
        "recovery_time": "2024-01-15 11:00:00",  # for recovery
        "duration": "30m",  # for recovery
        "message": "...",  # for update
        "user": "Admin"  # for update
    }
    """
    try:
        data = request.get_json() or {}
        logger.info(f"Received webhook: {json.dumps(data, indent=2)}")
        
        # Determine action type
        action = data.get('action', '').lower()
        status = data.get('status', '').upper()
        
        # If no explicit action, derive from status
        if not action:
            if status == 'PROBLEM':
                action = 'problem'
            elif status in ['OK', 'RESOLVED', 'RECOVERY']:
                action = 'recovery'
            else:
                action = 'update'
        
        # Route to appropriate handler
        if action == 'problem':
            result = handle_problem(data)
        elif action == 'recovery':
            result = handle_recovery(data)
        elif action == 'update':
            result = handle_update(data)
        else:
            result = {
                'status': 'error',
                'message': f'Unknown action: {action}'
            }
        
        status_code = 200 if result.get('status') != 'error' else 500
        return jsonify(result), status_code
        
    except Exception as e:
        logger.exception(f"Error processing webhook: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/webhook/problem', methods=['POST'])
def webhook_problem():
    """Direct endpoint for PROBLEM events"""
    try:
        data = request.get_json() or {}
        data['action'] = 'problem'
        result = handle_problem(data)
        return jsonify(result), 200 if result.get('status') != 'error' else 500
    except Exception as e:
        logger.exception(f"Error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/webhook/recovery', methods=['POST'])
def webhook_recovery():
    """Direct endpoint for RECOVERY events"""
    try:
        data = request.get_json() or {}
        data['action'] = 'recovery'
        result = handle_recovery(data)
        return jsonify(result), 200 if result.get('status') != 'error' else 500
    except Exception as e:
        logger.exception(f"Error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/webhook/update', methods=['POST'])
def webhook_update():
    """Direct endpoint for UPDATE events"""
    try:
        data = request.get_json() or {}
        data['action'] = 'update'
        result = handle_update(data)
        return jsonify(result), 200 if result.get('status') != 'error' else 500
    except Exception as e:
        logger.exception(f"Error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/test', methods=['GET', 'POST'])
def test():
    """Test endpoint for connectivity verification"""
    return jsonify({
        'status': 'ok',
        'service': 'zabbix-glpi-integration',
        'endpoints': {
            '/webhook': 'Main webhook (auto-detect action)',
            '/webhook/problem': 'Create ticket',
            '/webhook/recovery': 'Close ticket',
            '/webhook/update': 'Add followup',
            '/health': 'Health check',
            '/stats': 'Statistics'
        },
        'timestamp': datetime.utcnow().isoformat()
    })


if __name__ == '__main__':
    logger.info(f"Starting Zabbix-GLPI Integration Webhook Server")
    logger.info(f"Listening on {WEBHOOK_HOST}:{WEBHOOK_PORT}")
    app.run(host=WEBHOOK_HOST, port=WEBHOOK_PORT, debug=False)
