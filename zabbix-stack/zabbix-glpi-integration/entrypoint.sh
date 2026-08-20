#!/bin/bash
#
# Entrypoint script for Zabbix-GLPI Integration container
#

set -e

echo "=============================================="
echo "Zabbix-GLPI Integration Service"
echo "=============================================="
echo "Starting at: $(date)"
echo ""

# Initialize database
echo "Initializing database..."
python -c "from database import init_database; init_database()"
echo "Database initialized at: ${DATABASE_PATH:-/data/zabbix_glpi.db}"
echo ""

# Run initial inventory sync if enabled
if [ "${RUN_INITIAL_SYNC:-false}" = "true" ]; then
    echo "Running initial inventory sync..."
    python inventory_sync.py || echo "Initial sync completed with warnings"
    echo ""
fi

# ---------------------------------------------------------------------------
# Internal inventory-sync scheduler.
#
# The CMDB sync is driven from *inside* this container (not a host crontab), so
# scheduling ships with the stack and starts automatically with the service.
# Runs inventory_sync.py every INVENTORY_SYNC_INTERVAL seconds. The sync is
# idempotent (updates assets in place by stored id), so repeated runs never
# create duplicate rows.
# ---------------------------------------------------------------------------
if [ "${INVENTORY_SYNC_ENABLED:-true}" = "true" ]; then
    (
        sleep "${INVENTORY_SYNC_INITIAL_DELAY:-30}"
        while true; do
            echo "[sync-scheduler] $(date '+%Y-%m-%d %H:%M:%S') running inventory_sync"
            python inventory_sync.py || echo "[sync-scheduler] sync exited with warnings"
            sleep "${INVENTORY_SYNC_INTERVAL:-3600}"
        done
    ) &
    echo "Internal inventory-sync scheduler started (interval=${INVENTORY_SYNC_INTERVAL:-3600}s)"
    echo ""
fi

# ---------------------------------------------------------------------------
# Internal auto-acknowledge scheduler.
#
# Acknowledges every open, unacknowledged Zabbix problem (covers sub-Average
# email-only events the webhook never sees). Runs inside this container instead
# of a host crontab. Idempotent: only touches acknowledged == "0".
# ---------------------------------------------------------------------------
if [ "${AUTO_ACK_ENABLED:-true}" = "true" ]; then
    (
        sleep "${AUTO_ACK_INITIAL_DELAY:-20}"
        while true; do
            python auto_acknowledge.py || echo "[auto-ack] exited with warnings"
            sleep "${AUTO_ACK_INTERVAL:-60}"
        done
    ) &
    echo "Internal auto-acknowledge scheduler started (interval=${AUTO_ACK_INTERVAL:-60}s)"
    echo ""
fi

# Start the webhook server
echo "Starting webhook server on port ${WEBHOOK_PORT:-5002}..."
echo ""

# Use gunicorn for production, flask dev server for debug
if [ "${DEBUG:-false}" = "true" ]; then
    echo "Running in DEBUG mode"
    exec python webhook_server.py
else
    exec gunicorn \
        --bind "0.0.0.0:${WEBHOOK_PORT:-5002}" \
        --workers "${GUNICORN_WORKERS:-2}" \
        --threads "${GUNICORN_THREADS:-4}" \
        --timeout 30 \
        --access-logfile - \
        --error-logfile - \
        --capture-output \
        webhook_server:app
fi
