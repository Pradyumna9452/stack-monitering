#!/bin/bash
#
# Generate GLPI API Tokens and configure API access
#

set -e

echo "=============================================="
echo "GLPI API Token Generation"
echo "=============================================="

# Generate random tokens
APP_TOKEN=$(openssl rand -hex 32)
USER_TOKEN=$(openssl rand -hex 32)

echo ""
echo "Generated tokens:"
echo "  App Token:  $APP_TOKEN"
echo "  User Token: $USER_TOKEN"
echo ""

# Get GLPI user ID (usually 2 for 'glpi' user)
GLPI_USER_ID=2

# Enable API and create tokens in GLPI database
echo "Configuring GLPI database..."

docker exec -i glpi-mariadb sh -c 'mysql -u$MARIADB_USER -p"$MARIADB_PASSWORD" $MARIADB_DATABASE' << EOF

-- Enable the REST API
INSERT INTO glpi_configs (name, value) 
VALUES ('enable_api', '1')
ON DUPLICATE KEY UPDATE value = '1';

INSERT INTO glpi_configs (name, value) 
VALUES ('enable_api_login_credentials', '1')
ON DUPLICATE KEY UPDATE value = '1';

INSERT INTO glpi_configs (name, value) 
VALUES ('enable_api_login_external_token', '1')
ON DUPLICATE KEY UPDATE value = '1';

-- Create API Client (for App Token)
INSERT INTO glpi_apiclients (name, is_active, ipv4_range_start, ipv4_range_end, app_token, app_token_date, dolog_method, comment)
VALUES (
    'Zabbix-GLPI-Integration',
    1,
    INET_ATON('0.0.0.0'),
    INET_ATON('255.255.255.255'),
    '$APP_TOKEN',
    NOW(),
    0,
    'Auto-generated for Zabbix-GLPI Integration'
)
ON DUPLICATE KEY UPDATE 
    app_token = '$APP_TOKEN',
    app_token_date = NOW(),
    is_active = 1;

-- Create User API Token for glpi user
UPDATE glpi_users 
SET api_token = '$USER_TOKEN',
    api_token_date = NOW()
WHERE id = $GLPI_USER_ID;

-- Verify the configuration
SELECT 'API Clients:' as info;
SELECT id, name, is_active, LEFT(app_token, 20) as app_token_preview FROM glpi_apiclients WHERE name = 'Zabbix-GLPI-Integration';

SELECT 'User Token:' as info;
SELECT id, name, LEFT(api_token, 20) as user_token_preview FROM glpi_users WHERE id = $GLPI_USER_ID;

EOF

echo ""
echo "=============================================="
echo "API Configuration Complete!"
echo "=============================================="
echo ""
echo "Add these to your .env file:"
echo ""
echo "GLPI_APP_TOKEN=$APP_TOKEN"
echo "GLPI_USER_TOKEN=$USER_TOKEN"
echo ""

# Update .env file automatically
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if grep -q "^GLPI_APP_TOKEN=" "$ENV_FILE"; then
    sed -i "s/^GLPI_APP_TOKEN=.*/GLPI_APP_TOKEN=$APP_TOKEN/" "$ENV_FILE"
else
    echo "GLPI_APP_TOKEN=$APP_TOKEN" >> "$ENV_FILE"
fi

if grep -q "^GLPI_USER_TOKEN=" "$ENV_FILE"; then
    sed -i "s/^GLPI_USER_TOKEN=.*/GLPI_USER_TOKEN=$USER_TOKEN/" "$ENV_FILE"
else
    echo "GLPI_USER_TOKEN=$USER_TOKEN" >> "$ENV_FILE"
fi

echo ".env file updated automatically!"
echo ""
echo "Now restart the glpi-webhook service:"
echo "  docker-compose up -d --build glpi-webhook"
echo ""
