#!/bin/bash

# Simplified setup script for Loki and Promtail with OpenLiteSpeed using Podman
# This script avoids using podman-compose and uses direct podman commands

set -e

# Text formatting
BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BOLD}Loki and Promtail Setup for OpenLiteSpeed (Simplified Podman Version)${NC}"
echo "This script will set up Loki and Promtail for log collection and storage using direct Podman commands."

# Check if Podman is installed
echo -e "\n${BOLD}Checking prerequisites...${NC}"
if ! command -v podman &> /dev/null; then
    echo -e "${RED}Podman is not installed. Please install Podman first.${NC}"
    exit 1
fi

# Create base directory
echo -e "\n${BOLD}Where would you like to install Loki and Promtail?${NC}"
echo -e "Default is the current directory: $(pwd)/loki-promtail"
read -p "Installation directory [$(pwd)/loki-promtail]: " INSTALL_DIR
INSTALL_DIR=${INSTALL_DIR:-$(pwd)/loki-promtail}

mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# Clean up any existing containers
echo -e "\n${BOLD}Cleaning up any existing containers...${NC}"
podman stop loki promtail 2>/dev/null || true
podman rm loki promtail 2>/dev/null || true

# Create directories
echo -e "\n${BOLD}Creating directory structure...${NC}"
mkdir -p loki-config loki-data promtail-config

# Generate a secure password
LOKI_PASSWORD=$(openssl rand -base64 12)

# Create .env file
echo -e "\n${BOLD}Setting up environment variables...${NC}"
cat > .env << EOF
# Environment variables for Loki and Promtail
LOKI_USERNAME=admin
LOKI_PASSWORD=$LOKI_PASSWORD
EOF

echo -e "${GREEN}Created .env file with random password${NC}"

# Create Loki configuration
echo -e "\n${BOLD}Creating Loki configuration...${NC}"
cat > loki-config/loki-config.yaml << 'EOF'
auth_enabled: true

server:
  http_listen_port: 3100
  grpc_listen_port: 9096
  http_server_read_timeout: 120s
  http_server_write_timeout: 120s

common:
  path_prefix: /var/loki
  storage:
    filesystem:
      chunks_directory: /var/loki/chunks
      rules_directory: /var/loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory

limits_config:
  retention_period: 7d
  enforce_metric_name: false
  reject_old_samples: true
  reject_old_samples_max_age: 168h
  max_query_length: 721h
  split_queries_by_interval: 24h
  per_stream_rate_limit: 5MB
  per_stream_rate_limit_burst: 10MB
  ingestion_rate_mb: 8
  ingestion_burst_size_mb: 16

schema_config:
  configs:
    - from: 2020-10-24
      store: boltdb-shipper
      object_store: filesystem
      schema: v11
      index:
        prefix: index_
        period: 24h

ruler:
  alertmanager_url: http://localhost:9093

analytics:
  reporting_enabled: false
EOF

# Create Promtail configuration
echo -e "\n${BOLD}Creating Promtail configuration...${NC}"
cat > promtail-config/promtail-config.yaml << 'EOF'
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /etc/promtail/positions.yaml

clients:
  - url: http://127.0.0.1:3100/loki/api/v1/push
    tenant_id: default
    basic_auth:
      username: ${LOKI_USERNAME:-admin}
      password: ${LOKI_PASSWORD:-changeme}

scrape_configs:
  # OpenLiteSpeed logs
  - job_name: openlitespeed
    static_configs:
      - targets:
          - localhost
        labels:
          job: openlitespeed
          __path__: /usr/local/lsws/logs/*.log

  # System logs
  - job_name: system
    static_configs:
      - targets:
          - localhost
        labels:
          job: syslog
          __path__: /var/log/syslog

  # Authentication logs
  - job_name: auth
    static_configs:
      - targets:
          - localhost
        labels:
          job: auth
          __path__: /var/log/auth.log

  # Web application logs (if your web apps write logs to a specific directory)
  - job_name: webapps
    static_configs:
      - targets:
          - localhost
        labels:
          job: webapps
          __path__: /var/www/*/logs/*.log
EOF

# Create service start script
echo -e "\n${BOLD}Creating service start script...${NC}"
cat > start-services.sh << 'EOF'
#!/bin/bash
# Start Loki and Promtail services using direct Podman commands

cd "$(dirname "$0")"
source ./.env

echo "Starting Loki..."
podman run -d \
  --name loki \
  --restart unless-stopped \
  -v ./loki-config:/etc/loki:Z \
  -v ./loki-data:/var/loki:Z \
  -p 127.0.0.1:3100:3100 \
  -e LOKI_AUTH_ENABLED=true \
  -e LOKI_ADMIN_USERNAME="${LOKI_USERNAME:-admin}" \
  -e LOKI_ADMIN_PASSWORD="${LOKI_PASSWORD:-changeme}" \
  docker.io/grafana/loki:2.9.2 -config.file=/etc/loki/loki-config.yaml

echo "Starting Promtail..."
podman run -d \
  --name promtail \
  --restart unless-stopped \
  -v ./promtail-config:/etc/promtail:Z \
  -v /var/log:/var/log:ro \
  -v /var/www:/var/www:ro \
  -v /usr/local/lsws/logs:/usr/local/lsws/logs:ro \
  docker.io/grafana/promtail:2.9.2 -config.file=/etc/promtail/promtail-config.yaml

echo "Services started. Check status with 'podman ps'"
EOF

chmod +x start-services.sh

# Create service stop script
echo -e "\n${BOLD}Creating service stop script...${NC}"
cat > stop-services.sh << 'EOF'
#!/bin/bash
# Stop Loki and Promtail services

podman stop promtail loki
podman rm promtail loki

echo "Services stopped."
EOF

chmod +x stop-services.sh

# Create a README file with instructions
echo -e "\n${BOLD}Creating README with instructions...${NC}"
cat > README.md << 'EOF'
# Loki and Promtail Setup for OpenLiteSpeed

This directory contains the configuration for running Loki and Promtail with Podman.

## Configuration Files

- `loki-config/loki-config.yaml`: Loki configuration
- `promtail-config/promtail-config.yaml`: Promtail configuration
- `.env`: Environment variables with authentication credentials

## Starting and Stopping

To start Loki and Promtail:

```bash
./start-services.sh
```

To stop Loki and Promtail:

```bash
./stop-services.sh
```

## Connecting to Grafana

To connect Loki to Grafana:

1. In Grafana, go to Configuration > Data Sources
2. Click "Add data source"
3. Select "Loki"
4. Set the URL to `http://your-server-ip:3100` or if you're running Grafana on the same server, use `http://localhost:3100`
5. Enable basic authentication
6. Enter the username and password from the `.env` file
7. Click "Save & Test"

## Logging

Logs are stored in the `loki-data` directory. The default retention period is 7 days.

## Troubleshooting

- Check logs: `podman logs loki` or `podman logs promtail`
- Check container status: `podman ps`
- Check Loki status: `curl -u admin:password http://localhost:3100/ready`

## Security

- Loki is only accessible from localhost (127.0.0.1)
- Basic authentication is enabled for the Loki API
- All configuration data is stored in this directory
EOF

# Create a service file for systemd (optional)
echo -e "\n${BOLD}Creating systemd service files...${NC}"
cat > loki.service << 'EOF'
[Unit]
Description=Loki log aggregation service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=INSTALL_DIR_PLACEHOLDER
ExecStart=/usr/bin/podman run --rm --name loki \
  -v ./loki-config:/etc/loki:Z \
  -v ./loki-data:/var/loki:Z \
  -p 127.0.0.1:3100:3100 \
  -e LOKI_AUTH_ENABLED=true \
  -e LOKI_ADMIN_USERNAME=admin \
  -e LOKI_ADMIN_PASSWORD=PASSWORD_PLACEHOLDER \
  docker.io/grafana/loki:2.9.2 -config.file=/etc/loki/loki-config.yaml
ExecStop=/usr/bin/podman stop loki
Restart=always
RestartSec=10s

[Install]
WantedBy=multi-user.target
EOF

cat > promtail.service << 'EOF'
[Unit]
Description=Promtail log collector service
After=network.target loki.service

[Service]
Type=simple
User=root
WorkingDirectory=INSTALL_DIR_PLACEHOLDER
ExecStart=/usr/bin/podman run --rm --name promtail \
  -v ./promtail-config:/etc/promtail:Z \
  -v /var/log:/var/log:ro \
  -v /var/www:/var/www:ro \
  -v /usr/local/lsws/logs:/usr/local/lsws/logs:ro \
  docker.io/grafana/promtail:2.9.2 -config.file=/etc/promtail/promtail-config.yaml
ExecStop=/usr/bin/podman stop promtail
Restart=always
RestartSec=10s

[Install]
WantedBy=multi-user.target
EOF

# Replace placeholders in service files
sed -i "s|INSTALL_DIR_PLACEHOLDER|$INSTALL_DIR|g" loki.service promtail.service
sed -i "s|PASSWORD_PLACEHOLDER|$LOKI_PASSWORD|g" loki.service

# Start services
echo -e "\n${BOLD}Would you like to start the services now? (y/n)${NC}"
read -p "Start services? " START_SERVICES

if [[ $START_SERVICES =~ ^[Yy] ]]; then
    echo -e "\n${BOLD}Starting services...${NC}"
    ./start-services.sh

    echo -e "\n${BOLD}Waiting for services to start...${NC}"
    sleep 5

    # Check if services are running
    if podman ps | grep -q "loki"; then
        echo -e "\n${GREEN}Services are running!${NC}"

        echo -e "\n${BOLD}Loki credentials:${NC}"
        echo "Username: admin"
        echo "Password: $LOKI_PASSWORD"

        echo -e "\n${BOLD}Grafana connection information:${NC}"
        echo "URL: http://localhost:3100"
        echo "Authentication: Basic Auth"
        echo "Username: admin"
        echo "Password: $LOKI_PASSWORD"
    else
        echo -e "\n${RED}Services failed to start. Check logs with 'podman logs loki' or 'podman logs promtail'${NC}"
    fi
else
    echo -e "\n${YELLOW}Services not started. You can start them later with './start-services.sh'${NC}"
fi

echo -e "\n${BOLD}Would you like to set up systemd services for automatic startup? (y/n)${NC}"
read -p "Setup systemd services? " SETUP_SYSTEMD

if [[ $SETUP_SYSTEMD =~ ^[Yy] ]]; then
    echo -e "\n${BOLD}Setting up systemd services...${NC}"
    sudo cp loki.service /etc/systemd/system/
    sudo cp promtail.service /etc/systemd/system/
    sudo systemctl daemon-reload

    echo -e "\n${YELLOW}To enable services to start at boot:${NC}"
    echo "sudo systemctl enable loki.service promtail.service"

    echo -e "\n${YELLOW}To start services with systemd:${NC}"
    echo "sudo systemctl start loki.service promtail.service"
else
    echo -e "\n${YELLOW}Systemd services not set up. You can use './start-services.sh' to start manually.${NC}"
fi

echo -e "\n${GREEN}Setup complete! Installation directory: $INSTALL_DIR${NC}"
echo -e "See the README.md file for more information on how to use Loki and Promtail."
