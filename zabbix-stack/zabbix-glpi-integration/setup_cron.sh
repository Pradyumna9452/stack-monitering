#!/bin/bash
#
# Setup cron job for inventory synchronization
# Run this script on the Docker host to enable hourly inventory sync
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRON_LOG="/var/log/zabbix-glpi-inventory-sync.log"

echo "==================================================="
echo "Zabbix-GLPI Inventory Sync Cron Setup"
echo "==================================================="

# Create log file
sudo touch "$CRON_LOG"
sudo chmod 644 "$CRON_LOG"

# Create the cron job entry
CRON_ENTRY="0 * * * * docker exec glpi-webhook python /app/inventory_sync.py >> $CRON_LOG 2>&1"

# Check if cron entry already exists
if crontab -l 2>/dev/null | grep -q "glpi-webhook.*inventory_sync.py"; then
    echo "Cron job already exists. Updating..."
    # Remove existing entry
    crontab -l 2>/dev/null | grep -v "glpi-webhook.*inventory_sync.py" | crontab -
fi

# Add new cron entry
(crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -

echo ""
echo "Cron job installed successfully!"
echo ""
echo "Schedule: Every hour at minute 0"
echo "Command: docker exec glpi-webhook python /app/inventory_sync.py"
echo "Log file: $CRON_LOG"
echo ""
echo "To verify: crontab -l"
echo "To check logs: tail -f $CRON_LOG"
echo ""
echo "To run manually:"
echo "  docker exec glpi-webhook python /app/inventory_sync.py"
echo ""
echo "To run a dry-run:"
echo "  docker exec glpi-webhook python /app/inventory_sync.py --dry-run"
echo "==================================================="
