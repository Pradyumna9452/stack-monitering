#!/usr/bin/env python3
"""
Zabbix to GLPI Webhook Server
Receives alerts from Zabbix and creates tickets in GLPI
"""

import os
import json
import logging
from datetime import datetime
from flask import Flask, request, jsonify
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration from environment variables
GLPI_URL = os.environ.get('GLPI_URL', 'http://glpi:80/apirest.php')
GLPI_USER = os.environ.get('GLPI_USER', 'glpi')
GLPI_PASSWORD = os.environ.get('GLPI_PASSWORD', 'glpi')
GLPI_APP_TOKEN = os.environ.get('GLPI_APP_TOKEN', '')
GLPI_USER_TOKEN = os.environ.get('GLPI_USER_TOKEN', '')
WEBHOOK_PORT = int(os.environ.get('WEBHOOK_PORT', 5002))


class GLPIClient:
    """GLPI API Client"""
    
    def __init__(self):
        self.base_url = GLPI_URL
        self.session_token = None
        self.app_token = GLPI_APP_TOKEN
        
    def _get_headers(self):
        headers = {
            'Content-Type': 'application/json',
        }
        if self.app_token:
            headers['App-Token'] = self.app_token
        if self.session_token:
            headers['Session-Token'] = self.session_token
        return headers
    
    def init_session(self):
        """Initialize GLPI session"""
        try:
            if GLPI_USER_TOKEN:
                # Use user token authentication
                headers = {
                    'Content-Type': 'application/json',
                    'Authorization': f'user_token {GLPI_USER_TOKEN}'
                }
                if self.app_token:
                    headers['App-Token'] = self.app_token
            else:
                # Use basic authentication
                import base64
                credentials = base64.b64encode(
                    f'{GLPI_USER}:{GLPI_PASSWORD}'.encode()
                ).decode()
                headers = {
                    'Content-Type': 'application/json',
                    'Authorization': f'Basic {credentials}'
                }
                if self.app_token:
                    headers['App-Token'] = self.app_token
            
            response = requests.get(
                f'{self.base_url}/initSession',
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                self.session_token = data.get('session_token')
                logger.info("GLPI session initialized successfully")
                return True
            else:
                logger.error(f"Failed to init GLPI session: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error initializing GLPI session: {e}")
            return False
    
    def kill_session(self):
        """Kill GLPI session"""
        try:
            if self.session_token:
                requests.get(
                    f'{self.base_url}/killSession',
                    headers=self._get_headers(),
                    timeout=10
                )
                self.session_token = None
        except Exception as e:
            logger.warning(f"Error killing session: {e}")
    
    def create_ticket(self, title, content, urgency=3, priority=3):
        """Create a ticket in GLPI"""
        try:
            if not self.session_token and not self.init_session():
                return None
            
            ticket_data = {
                'input': {
                    'name': title,
                    'content': content,
                    'urgency': urgency,
                    'priority': priority,
                    'type': 1,  # Incident
                    'status': 1  # New
                }
            }
            
            response = requests.post(
                f'{self.base_url}/Ticket',
                headers=self._get_headers(),
                json=ticket_data,
                timeout=30
            )
            
            if response.status_code in [200, 201]:
                data = response.json()
                ticket_id = data.get('id')
                logger.info(f"Created GLPI ticket #{ticket_id}")
                return ticket_id
            else:
                logger.error(f"Failed to create ticket: {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error creating GLPI ticket: {e}")
            return None
        finally:
            self.kill_session()


glpi_client = GLPIClient()


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.utcnow().isoformat()})


@app.route('/webhook', methods=['POST'])
def webhook():
    """
    Receive webhook from Zabbix and create GLPI ticket
    
    Expected Zabbix webhook payload:
    {
        "host": "hostname",
        "trigger": "trigger name",
        "severity": "High",
        "status": "PROBLEM",
        "event_id": "12345",
        "description": "Problem description"
    }
    """
    try:
        data = request.get_json() or {}
        logger.info(f"Received webhook: {json.dumps(data)}")
        
        # Extract Zabbix alert details
        host = data.get('host', 'Unknown Host')
        trigger = data.get('trigger', 'Unknown Trigger')
        severity = data.get('severity', 'Not classified')
        status = data.get('status', 'UNKNOWN')
        event_id = data.get('event_id', 'N/A')
        description = data.get('description', 'No description provided')
        
        # Only create tickets for PROBLEM status
        if status.upper() != 'PROBLEM':
            logger.info(f"Skipping ticket creation for status: {status}")
            return jsonify({
                'status': 'skipped',
                'message': f'Not creating ticket for status: {status}'
            })
        
        # Map severity to GLPI urgency (1-5, where 5 is most urgent)
        severity_map = {
            'Not classified': 3,
            'Information': 2,
            'Warning': 3,
            'Average': 3,
            'High': 4,
            'Disaster': 5
        }
        urgency = severity_map.get(severity, 3)
        
        # Create ticket title and content
        title = f"[Zabbix] {host}: {trigger}"
        content = f"""
<h3>Zabbix Alert</h3>
<table>
<tr><td><strong>Host:</strong></td><td>{host}</td></tr>
<tr><td><strong>Trigger:</strong></td><td>{trigger}</td></tr>
<tr><td><strong>Severity:</strong></td><td>{severity}</td></tr>
<tr><td><strong>Status:</strong></td><td>{status}</td></tr>
<tr><td><strong>Event ID:</strong></td><td>{event_id}</td></tr>
<tr><td><strong>Time:</strong></td><td>{datetime.utcnow().isoformat()}</td></tr>
</table>
<h4>Description</h4>
<p>{description}</p>
"""
        
        # Create GLPI ticket
        ticket_id = glpi_client.create_ticket(
            title=title,
            content=content,
            urgency=urgency,
            priority=urgency
        )
        
        if ticket_id:
            return jsonify({
                'status': 'success',
                'ticket_id': ticket_id,
                'message': f'Created GLPI ticket #{ticket_id}'
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to create GLPI ticket'
            }), 500
            
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/test', methods=['GET', 'POST'])
def test():
    """Test endpoint to verify connectivity"""
    return jsonify({
        'status': 'ok',
        'glpi_url': GLPI_URL,
        'timestamp': datetime.utcnow().isoformat()
    })


if __name__ == '__main__':
    logger.info(f"Starting GLPI Webhook Server on port {WEBHOOK_PORT}")
    logger.info(f"GLPI URL: {GLPI_URL}")
    app.run(host='0.0.0.0', port=WEBHOOK_PORT, debug=False)
