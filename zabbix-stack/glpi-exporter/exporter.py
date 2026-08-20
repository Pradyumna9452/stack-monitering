#!/usr/bin/env python3
"""
GLPI to VictoriaMetrics Exporter
Fetches statistics from GLPI API and exports them to VictoriaMetrics for Grafana visualization
Includes full ticket details for dashboard display
"""

import os
import time
import re
import json
import logging
from datetime import datetime, timedelta
import requests
from prometheus_client import start_http_server, Counter, Gauge

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration from environment variables
GLPI_URL = os.environ.get('GLPI_URL', 'http://glpi:80/apirest.php')
GLPI_USER = os.environ.get('GLPI_USER', 'glpi')
GLPI_PASSWORD = os.environ.get('GLPI_PASSWORD', 'glpi')
GLPI_USER_TOKEN = os.environ.get('GLPI_USER_TOKEN', '')
VM_URL = os.environ.get('VM_URL', 'http://victoriametrics:8428')
EXPORT_INTERVAL = int(os.environ.get('EXPORT_INTERVAL', 30))


class GLPIClient:
    """GLPI API Client"""
    
    # Status mapping
    STATUS_NAMES = {
        1: 'new',
        2: 'processing_assigned',
        3: 'processing_planned',
        4: 'pending',
        5: 'solved',
        6: 'closed'
    }
    
    STATUS_DISPLAY = {
        1: 'New',
        2: 'Processing (Assigned)',
        3: 'Processing (Planned)',
        4: 'Pending',
        5: 'Solved',
        6: 'Closed'
    }
    
    # Priority mapping
    PRIORITY_NAMES = {
        1: 'very_low',
        2: 'low',
        3: 'medium',
        4: 'high',
        5: 'very_high',
        6: 'major'
    }
    
    PRIORITY_DISPLAY = {
        1: 'Very Low',
        2: 'Low',
        3: 'Medium',
        4: 'High',
        5: 'Very High',
        6: 'Major'
    }
    
    # Urgency mapping
    URGENCY_NAMES = {
        1: 'very_low',
        2: 'low',
        3: 'medium',
        4: 'high',
        5: 'very_high'
    }
    
    def __init__(self):
        self.url = GLPI_URL
        self.session_token = None
        
    def login(self):
        """Authenticate with GLPI"""
        try:
            headers = {'Content-Type': 'application/json'}
            
            if GLPI_USER_TOKEN:
                headers['Authorization'] = f'user_token {GLPI_USER_TOKEN}'
                response = requests.get(
                    f'{self.url}/initSession',
                    headers=headers,
                    timeout=30
                )
            else:
                response = requests.get(
                    f'{self.url}/initSession',
                    auth=(GLPI_USER, GLPI_PASSWORD),
                    headers=headers,
                    timeout=30
                )
            
            if response.status_code == 200:
                data = response.json()
                self.session_token = data.get('session_token')
                logger.info("Successfully authenticated with GLPI")
                return True
            else:
                logger.error(f"GLPI login failed: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error authenticating with GLPI: {e}")
            return False
    
    def logout(self):
        """Close GLPI session"""
        if self.session_token:
            try:
                requests.get(
                    f'{self.url}/killSession',
                    headers={'Session-Token': self.session_token},
                    timeout=10
                )
            except:
                pass
            self.session_token = None
    
    def _get(self, endpoint, params=None):
        """Make GET request to GLPI API"""
        if not self.session_token:
            return None
            
        try:
            response = requests.get(
                f'{self.url}/{endpoint}',
                headers={
                    'Session-Token': self.session_token,
                    'Content-Type': 'application/json'
                },
                params=params,
                timeout=30
            )
            return response
        except Exception as e:
            logger.error(f"Error calling GLPI API: {e}")
            return None
    
    def get_ticket_count_by_status(self):
        """Get ticket counts grouped by status"""
        counts = {}
        for status_id, status_name in self.STATUS_NAMES.items():
            response = self._get('search/Ticket', {
                'criteria[0][field]': 12,
                'criteria[0][searchtype]': 'equals',
                'criteria[0][value]': status_id,
                'range': '0-0'
            })
            if response and response.status_code in [200, 206]:
                content_range = response.headers.get('Content-Range', '0-0/0')
                total = int(content_range.split('/')[-1])
                counts[status_name] = total
            else:
                counts[status_name] = 0
        return counts
    
    def get_ticket_count_by_priority(self):
        """Get ticket counts grouped by priority (open tickets only)"""
        counts = {}
        for priority_id, priority_name in self.PRIORITY_NAMES.items():
            response = self._get('search/Ticket', {
                'criteria[0][field]': 3,
                'criteria[0][searchtype]': 'equals',
                'criteria[0][value]': priority_id,
                'criteria[1][link]': 'AND',
                'criteria[1][field]': 12,
                'criteria[1][searchtype]': 'notequals',
                'criteria[1][value]': 6,
                'range': '0-0'
            })
            if response and response.status_code in [200, 206]:
                content_range = response.headers.get('Content-Range', '0-0/0')
                total = int(content_range.split('/')[-1])
                counts[priority_name] = total
            else:
                counts[priority_name] = 0
        return counts
    
    def get_ticket_count_by_urgency(self):
        """Get ticket counts grouped by urgency (open tickets only)"""
        counts = {}
        for urgency_id, urgency_name in self.URGENCY_NAMES.items():
            response = self._get('search/Ticket', {
                'criteria[0][field]': 10,
                'criteria[0][searchtype]': 'equals',
                'criteria[0][value]': urgency_id,
                'criteria[1][link]': 'AND',
                'criteria[1][field]': 12,
                'criteria[1][searchtype]': 'notequals',
                'criteria[1][value]': 6,
                'range': '0-0'
            })
            if response and response.status_code in [200, 206]:
                content_range = response.headers.get('Content-Range', '0-0/0')
                total = int(content_range.split('/')[-1])
                counts[urgency_name] = total
            else:
                counts[urgency_name] = 0
        return counts
    
    def get_total_tickets(self):
        """Get total ticket count"""
        response = self._get('Ticket', {'range': '0-0', 'only_id': 'true'})
        if response and response.status_code in [200, 206]:
            content_range = response.headers.get('Content-Range', '0-0/0')
            return int(content_range.split('/')[-1])
        return 0
    
    def get_open_tickets(self):
        """Get count of open tickets (not closed/solved)"""
        response = self._get('search/Ticket', {
            'criteria[0][field]': 12,
            'criteria[0][searchtype]': 'notequals',
            'criteria[0][value]': 6,
            'criteria[1][link]': 'AND',
            'criteria[1][field]': 12,
            'criteria[1][searchtype]': 'notequals',
            'criteria[1][value]': 5,
            'range': '0-0'
        })
        if response and response.status_code in [200, 206]:
            content_range = response.headers.get('Content-Range', '0-0/0')
            return int(content_range.split('/')[-1])
        return 0
    
    def get_tickets_created_today(self):
        """Get count of tickets created today"""
        today = datetime.now().strftime('%Y-%m-%d')
        response = self._get('search/Ticket', {
            'criteria[0][field]': 15,
            'criteria[0][searchtype]': 'contains',
            'criteria[0][value]': today,
            'range': '0-0'
        })
        if response and response.status_code in [200, 206]:
            content_range = response.headers.get('Content-Range', '0-0/0')
            return int(content_range.split('/')[-1])
        return 0
    
    def get_tickets_closed_today(self):
        """Get count of tickets closed today"""
        today = datetime.now().strftime('%Y-%m-%d')
        response = self._get('search/Ticket', {
            'criteria[0][field]': 16,
            'criteria[0][searchtype]': 'contains',
            'criteria[0][value]': today,
            'range': '0-0'
        })
        if response and response.status_code in [200, 206]:
            content_range = response.headers.get('Content-Range', '0-0/0')
            return int(content_range.split('/')[-1])
        return 0
    
    def get_recent_tickets(self, limit=50):
        """Get recent tickets with full details"""
        response = self._get('Ticket', {
            'range': f'0-{limit-1}',
            'order': 'DESC',
            'sort': 'date_creation'
        })
        if response and response.status_code in [200, 206]:
            tickets = response.json()
            if isinstance(tickets, list):
                return tickets
        return []
    
    def get_open_tickets_details(self, limit=100):
        """Get open tickets with full details"""
        response = self._get('search/Ticket', {
            'criteria[0][field]': 12,
            'criteria[0][searchtype]': 'notequals',
            'criteria[0][value]': 6,  # not closed
            'criteria[1][link]': 'AND',
            'criteria[1][field]': 12,
            'criteria[1][searchtype]': 'notequals',
            'criteria[1][value]': 5,  # not solved
            'forcedisplay[0]': 2,  # ID
            'forcedisplay[1]': 1,  # Name
            'forcedisplay[2]': 12, # Status
            'forcedisplay[3]': 3,  # Priority
            'forcedisplay[4]': 10, # Urgency
            'forcedisplay[5]': 15, # Date creation
            'forcedisplay[6]': 4,  # Requester
            'range': f'0-{limit-1}'
        })
        if response and response.status_code in [200, 206]:
            data = response.json()
            if isinstance(data, dict) and 'data' in data:
                return data['data']
            elif isinstance(data, list):
                return data
        return []
    
    def get_computer_count(self):
        """Get total computer count"""
        response = self._get('Computer', {'range': '0-0', 'only_id': 'true'})
        if response and response.status_code in [200, 206]:
            content_range = response.headers.get('Content-Range', '0-0/0')
            return int(content_range.split('/')[-1])
        return 0
    
    def get_user_count(self):
        """Get total user count"""
        response = self._get('User', {'range': '0-0', 'only_id': 'true'})
        if response and response.status_code in [200, 206]:
            content_range = response.headers.get('Content-Range', '0-0/0')
            return int(content_range.split('/')[-1])
        return 0


class VictoriaMetricsClient:
    """VictoriaMetrics Client"""
    
    def __init__(self):
        self.url = VM_URL
        
    def write_metrics(self, metrics):
        """Write metrics to VictoriaMetrics using import endpoint"""
        if not metrics:
            return True
            
        try:
            lines = []
            timestamp = int(time.time() * 1000)
            
            for metric in metrics:
                name = metric['name']
                value = metric['value']
                labels = metric.get('labels', {})
                
                # Sanitize label values
                sanitized_labels = {}
                for k, v in labels.items():
                    # Escape quotes and backslashes in label values
                    v_str = str(v).replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')[:100]
                    sanitized_labels[k] = v_str
                
                if sanitized_labels:
                    label_str = ','.join([f'{k}="{v}"' for k, v in sanitized_labels.items()])
                    lines.append(f'{name}{{{label_str}}} {value} {timestamp}')
                else:
                    lines.append(f'{name} {value} {timestamp}')
            
            data = '\n'.join(lines)
            
            response = requests.post(
                f'{self.url}/api/v1/import/prometheus',
                headers={'Content-Type': 'text/plain'},
                data=data,
                timeout=30
            )
            
            if response.status_code in [200, 204]:
                logger.debug(f"Successfully wrote {len(metrics)} metrics to VictoriaMetrics")
                return True
            else:
                logger.error(f"Failed to write metrics: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error writing to VictoriaMetrics: {e}")
            return False
    
    def health_check(self):
        """Check VictoriaMetrics health"""
        try:
            response = requests.get(f'{self.url}/health', timeout=5)
            return response.status_code == 200
        except:
            return False


# Prometheus metrics
TICKETS_EXPORTED = Counter('glpi_exporter_tickets_exported_total', 'Total tickets exported')
METRICS_EXPORTED = Counter('glpi_exporter_metrics_exported_total', 'Total individual metrics exported')
LAST_EXPORT_TIME = Gauge('glpi_exporter_last_export_timestamp', 'Timestamp of last successful export')
EXPORT_ERRORS = Counter('glpi_exporter_errors_total', 'Total export errors')

def export_metrics(glpi, vm):
    """Export GLPI metrics to VictoriaMetrics"""
    metrics = []
    
    try:
        # Ticket counts by status
        status_counts = glpi.get_ticket_count_by_status()
        for status, count in status_counts.items():
            metrics.append({
                'name': 'glpi_tickets_by_status',
                'value': count,
                'labels': {'status': status, 'source': 'glpi'}
            })
        
        # Ticket counts by priority
        priority_counts = glpi.get_ticket_count_by_priority()
        for priority, count in priority_counts.items():
            metrics.append({
                'name': 'glpi_tickets_by_priority',
                'value': count,
                'labels': {'priority': priority, 'source': 'glpi'}
            })
        
        # Ticket counts by urgency
        urgency_counts = glpi.get_ticket_count_by_urgency()
        for urgency, count in urgency_counts.items():
            metrics.append({
                'name': 'glpi_tickets_by_urgency',
                'value': count,
                'labels': {'urgency': urgency, 'source': 'glpi'}
            })
        
        # Total tickets
        total_tickets = glpi.get_total_tickets()
        metrics.append({
            'name': 'glpi_tickets_total',
            'value': total_tickets,
            'labels': {'source': 'glpi'}
        })
        
        # Open tickets
        open_tickets = glpi.get_open_tickets()
        metrics.append({
            'name': 'glpi_tickets_open',
            'value': open_tickets,
            'labels': {'source': 'glpi'}
        })
        
        # Tickets created today
        created_today = glpi.get_tickets_created_today()
        metrics.append({
            'name': 'glpi_tickets_created_today',
            'value': created_today,
            'labels': {'source': 'glpi'}
        })
        
        # Tickets closed today
        closed_today = glpi.get_tickets_closed_today()
        metrics.append({
            'name': 'glpi_tickets_closed_today',
            'value': closed_today,
            'labels': {'source': 'glpi'}
        })
        
        # Asset counts
        computer_count = glpi.get_computer_count()
        metrics.append({
            'name': 'glpi_computers_total',
            'value': computer_count,
            'labels': {'source': 'glpi'}
        })
        
        user_count = glpi.get_user_count()
        metrics.append({
            'name': 'glpi_users_total',
            'value': user_count,
            'labels': {'source': 'glpi'}
        })
        
        # Get recent tickets with details
        recent_tickets = glpi.get_recent_tickets(limit=50)
        for ticket in recent_tickets:
            ticket_id = ticket.get('id', 0)
            name = ticket.get('name', 'Unknown')[:80]
            status_id = ticket.get('status', 1)
            priority_id = ticket.get('priority', 3)
            urgency_id = ticket.get('urgency', 3)
            date_creation = ticket.get('date_creation', '')[:19]
            
            status_name = glpi.STATUS_DISPLAY.get(status_id, f'Status {status_id}')
            priority_name = glpi.PRIORITY_DISPLAY.get(priority_id, f'Priority {priority_id}')
            
            # Export each ticket as a metric with labels
            metrics.append({
                'name': 'glpi_ticket_info',
                'value': 1,
                'labels': {
                    'ticket_id': str(ticket_id),
                    'name': name,
                    'status': status_name,
                    'priority': priority_name,
                    'date_creation': date_creation,
                    'source': 'glpi'
                }
            })
            
            # Also export ticket status as numeric for graphing
            metrics.append({
                'name': 'glpi_ticket_status',
                'value': status_id,
                'labels': {
                    'ticket_id': str(ticket_id),
                    'name': name,
                    'source': 'glpi'
                }
            })
            
            metrics.append({
                'name': 'glpi_ticket_priority',
                'value': priority_id,
                'labels': {
                    'ticket_id': str(ticket_id),
                    'name': name,
                    'source': 'glpi'
                }
            })
        
        # Write to VictoriaMetrics
        if metrics:
            vm.write_metrics(metrics)
            logger.info(f"Exported {len(metrics)} GLPI metrics to VictoriaMetrics (including {len(recent_tickets)} ticket details)")
            TICKETS_EXPORTED.inc(len(recent_tickets))
            METRICS_EXPORTED.inc(len(metrics))
            LAST_EXPORT_TIME.set_to_current_time()
        
    except Exception as e:
        logger.error(f"Error exporting GLPI metrics: {e}")
        EXPORT_ERRORS.inc()


def main():
    """Main export loop"""
    logger.info("Starting GLPI to VictoriaMetrics Exporter")
    
    # Start Prometheus metrics server
    start_http_server(8000)
    logger.info("Prometheus metrics server started on port 8000")
    
    logger.info(f"GLPI URL: {GLPI_URL}")
    logger.info(f"VictoriaMetrics URL: {VM_URL}")
    logger.info(f"Export interval: {EXPORT_INTERVAL}s")
    
    glpi = GLPIClient()
    vm = VictoriaMetricsClient()
    
    # Wait for services to be ready
    logger.info("Waiting for services to be ready...")
    time.sleep(10)
    
    while True:
        try:
            # Check VictoriaMetrics health
            if not vm.health_check():
                logger.warning("VictoriaMetrics not healthy, waiting...")
                time.sleep(10)
                continue
            
            # Authenticate with GLPI
            if not glpi.login():
                logger.warning("Failed to login to GLPI, retrying in 30s...")
                time.sleep(30)
                continue
            
            # Export metrics
            export_metrics(glpi, vm)
            
            # Logout
            glpi.logout()
            
        except Exception as e:
            logger.error(f"Error in export loop: {e}")
        
        time.sleep(EXPORT_INTERVAL)


if __name__ == '__main__':
    main()
