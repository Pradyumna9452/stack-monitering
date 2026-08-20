# Zabbix-GLPI Integration

**Fully Automated, Human-Intervention-Free Integration** between Zabbix monitoring and GLPI IT Service Management.

## Features

- **Automatic Ticket Creation**: Creates GLPI tickets when Zabbix detects problems
- **Auto-Acknowledge**: Automatically acknowledges Zabbix events when tickets are created
- **Asset Linking**: Links tickets to pre-synced GLPI assets (Computers, Network Equipment)
- **Automatic Ticket Closure**: Closes tickets with solution when Zabbix problems are resolved
- **Follow-up Sync**: Adds follow-ups when events are updated/acknowledged in Zabbix
- **Inventory Sync**: Synchronizes Zabbix host inventory to GLPI assets
- **Deduplication**: Prevents duplicate tickets for the same ongoing issue

## Architecture

```
┌─────────────┐     Webhook      ┌──────────────────────┐     REST API    ┌────────┐
│   Zabbix    │ ──────────────▶  │  Integration Service │ ─────────────▶  │  GLPI  │
│   Server    │                  │  (webhook_server.py) │                 │        │
└─────────────┘                  └──────────────────────┘                 └────────┘
      │                                    │
      │ Auto-Ack                           │
      ◀────────────────────────────────────┘
      
┌─────────────┐     Zabbix API   ┌──────────────────────┐     REST API    ┌────────┐
│   Zabbix    │ ◀────────────────│  Inventory Sync      │ ─────────────▶  │  GLPI  │
│   Server    │                  │  (inventory_sync.py) │                 │        │
└─────────────┘                  └──────────────────────┘                 └────────┘
```

## Quick Start

### 1. Configure Environment Variables

Add these to your `.env` file:

```bash
# GLPI API Tokens (get from GLPI > Setup > General > API)
GLPI_APP_TOKEN=your_app_token_here
GLPI_USER_TOKEN=your_user_token_here

# Zabbix API Token (optional, can use user/password instead)
ZABBIX_API_TOKEN=your_zabbix_api_token
ZABBIX_PASSWORD=zabbix
```

### 2. Start the Services

```bash
cd /root/zabbix-stack
docker-compose up -d --build glpi-webhook
```

### 3. Configure Zabbix Media Type

1. Go to **Administration > Media Types**
2. Click **Create media type**
3. Configure:
   - **Name**: `GLPI Integration`
   - **Type**: `Webhook`
   - **Script**: Copy contents from `zabbix_mediatype_glpi.js`
4. Add parameters from `zabbix_mediatype_params.json`
5. Click **Add**

### 4. Create Zabbix User for Automation

1. Go to **Users > Users**
2. Create user `GLPI_Robot`
3. Assign the `GLPI Integration` media type
4. Grant read permissions to hosts/host groups

### 5. Create Zabbix Action

1. Go to **Alerts > Actions > Trigger actions**
2. Create new action:
   - **Name**: `GLPI Ticket Automation`
   - **Conditions**: Trigger severity >= Warning
3. **Operations**:
   - Send message to `GLPI_Robot` using `GLPI Integration`
4. **Recovery operations**:
   - Send message to `GLPI_Robot` using `GLPI Integration`
5. **Update operations**:
   - Send message to `GLPI_Robot` using `GLPI Integration`

### 6. Enable GLPI API

1. Go to **Setup > General > API**
2. Enable **Rest API**
3. Create an API client and get the **App-Token**
4. Create a **User token** for the user to be used

### 7. Setup Inventory Sync Cron

```bash
chmod +x /root/zabbix-stack/zabbix-glpi-integration/setup_cron.sh
/root/zabbix-stack/zabbix-glpi-integration/setup_cron.sh
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/webhook` | POST | Main webhook (auto-detects action) |
| `/webhook/problem` | POST | Create ticket |
| `/webhook/recovery` | POST | Close ticket |
| `/webhook/update` | POST | Add follow-up |
| `/health` | GET | Health check |
| `/stats` | GET | Integration statistics |
| `/test` | GET/POST | Test connectivity |

## Webhook Payload Format

### Problem Event

```json
{
  "action": "problem",
  "event_id": "12345",
  "host": "server01",
  "host_id": "10001",
  "trigger": "CPU usage too high",
  "trigger_id": "20001",
  "severity": "4",
  "description": "CPU usage is above 90%",
  "ip_address": "192.168.1.100",
  "event_time": "2024-01-15 10:30:00"
}
```

### Recovery Event

```json
{
  "action": "recovery",
  "event_id": "12345",
  "host": "server01",
  "trigger": "CPU usage too high",
  "recovery_time": "2024-01-15 11:00:00",
  "duration": "30m"
}
```

### Update Event

```json
{
  "action": "update",
  "event_id": "12345",
  "host": "server01",
  "trigger": "CPU usage too high",
  "message": "Investigating the issue",
  "user": "Admin"
}
```

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GLPI_URL` | `http://glpi:80/apirest.php` | GLPI API endpoint |
| `GLPI_USER` | `glpi` | GLPI username (if not using token) |
| `GLPI_PASSWORD` | `glpi` | GLPI password (if not using token) |
| `GLPI_APP_TOKEN` | | GLPI Application Token |
| `GLPI_USER_TOKEN` | | GLPI User Token |
| `GLPI_ENTITY_ID` | `0` | Default GLPI entity |
| `GLPI_DEFAULT_USER_ID` | `0` | Auto-assign to user |
| `GLPI_DEFAULT_GROUP_ID` | `0` | Auto-assign to group |
| `ZABBIX_URL` | `http://zabbix-web:8080/api_jsonrpc.php` | Zabbix API endpoint |
| `ZABBIX_USER` | `Admin` | Zabbix username |
| `ZABBIX_PASSWORD` | `zabbix` | Zabbix password |
| `ZABBIX_API_TOKEN` | | Zabbix API token (preferred) |
| `WEBHOOK_PORT` | `5002` | Webhook server port |
| `DATABASE_PATH` | `/data/zabbix_glpi.db` | SQLite database path |
| `INVENTORY_SYNC_ENABLED` | `true` | Enable inventory sync |
| `AUTO_ACKNOWLEDGE_ENABLED` | `true` | Auto-ack Zabbix events |
| `LOG_LEVEL` | `INFO` | Logging level |

## Severity Mapping

| Zabbix Severity | GLPI Urgency |
|-----------------|--------------|
| Not classified | Low (2) |
| Information | Very Low (1) |
| Warning | Low (2) |
| Average | Medium (3) |
| High | High (4) |
| Disaster | Very High (5) |

## Manual Operations

### Run Inventory Sync

```bash
# Inside container
docker exec glpi-webhook python /app/inventory_sync.py

# Dry run (see what would be synced)
docker exec glpi-webhook python /app/inventory_sync.py --dry-run

# Sync specific host
docker exec glpi-webhook python /app/inventory_sync.py --host "server01"
```

### Check Statistics

```bash
curl http://localhost:5002/stats
```

### Test Webhook

```bash
curl -X POST http://localhost:5002/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "action": "problem",
    "event_id": "99999",
    "host": "test-server",
    "trigger": "Test Alert",
    "severity": "3",
    "description": "This is a test"
  }'
```

## Troubleshooting

### Check Logs

```bash
docker logs -f glpi-webhook
```

### Test GLPI Connection

```bash
docker exec glpi-webhook python -c "
from glpi_client import GLPIClient
with GLPIClient() as glpi:
    print('GLPI connection successful')
"
```

### Test Zabbix Connection

```bash
docker exec glpi-webhook python -c "
from zabbix_client import ZabbixClient
with ZabbixClient() as zabbix:
    print('Zabbix API version:', zabbix.get_api_version())
"
```

### Common Issues

1. **GLPI API returns 401**: Check App-Token and User-Token
2. **Tickets not created**: Check GLPI user has permission to create tickets
3. **Auto-ack fails**: Ensure Zabbix user has write permissions
4. **Inventory sync fails**: Check Zabbix host inventory is enabled

## Flow Diagram

```
                                    ┌─────────────────────────────────────────────────┐
                                    │            NO-INTERVENTION FLOW                  │
                                    └─────────────────────────────────────────────────┘
                                                          
  ┌──────────┐                                                            ┌──────────┐
  │  CRON    │ ─────── Every Hour ────────▶ Inventory Sync ─────────────▶ │  GLPI    │
  │  JOB     │                              (Zabbix Hosts → GLPI Assets)  │  ASSETS  │
  └──────────┘                                                            └──────────┘
                                                                               │
                                                                               │
  ┌──────────┐       Problem          ┌────────────┐       Create Ticket       │
  │  ZABBIX  │ ────────────────────▶  │  WEBHOOK   │ ─────────────────────────▶│
  │  SERVER  │       Detected         │  SERVER    │       + Link Asset        │
  └──────────┘                        └────────────┘                           │
       │                                    │                                  │
       │◀─── Auto-Acknowledge ──────────────┘                                  │
       │     "Ticket #123 Created"                                             │
       │                                                                       │
       │         Recovery             ┌────────────┐       Close Ticket        │
       │ ────────────────────────────▶│  WEBHOOK   │ ─────────────────────────▶│
       │         Detected             │  SERVER    │       + Add Solution      │
       │                              └────────────┘                           │
       │                                                                       │
       ▼                                                                       ▼
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │                         COMPLETE AUTOMATION ACHIEVED                          │
  │   • No manual ticket creation                                                 │
  │   • No manual ticket closure                                                  │
  │   • Assets automatically linked                                               │
  │   • Full audit trail maintained                                               │
  └──────────────────────────────────────────────────────────────────────────────┘
```

## License

MIT License
