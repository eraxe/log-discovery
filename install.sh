#!/bin/bash
# ==============================================================================
# LogBuddy - Unified Log Discovery and Monitoring Tool Installer
# ==============================================================================
#
# This script installs, removes, or updates the LogBuddy system.
# Usage: ./installer.sh [install|remove|update] [--no-service] [--no-deps]
#        [--interval daily|hourly|custom] [--email admin@example.com]
#
# Options:
#   install     Install the LogBuddy system
#   remove      Remove the LogBuddy system
#   update      Update the LogBuddy system
#   --no-service  Don't install/remove the systemd service
#   --no-deps     Skip dependency installation
#   --interval    Set discovery interval (daily, hourly, or cron expression)
#   --email       Set notification email for automated reports
#
# ==============================================================================

set -e

# Configuration
INSTALL_DIR="/opt/logbuddy"
BIN_DIR="/usr/local/bin"
SERVICE_NAME="logbuddy"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
TIMER_FILE="/etc/systemd/system/${SERVICE_NAME}.timer"
SERVICE_ENABLED=true
LOG_DIR="/var/log/logbuddy"
CONFIG_DIR="/etc/logbuddy"
CACHE_DIR="${CONFIG_DIR}/cache"
DATA_DIR="/var/lib/logbuddy"
OUTPUT_DIR="${DATA_DIR}/output"
DISCOVERY_INTERVAL="daily"  # daily, hourly, or a cron expression like "0 4 * * *"
INSTALL_DEPS=true
NOTIFY_EMAIL=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get current script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ==============================================================================
# Helper Functions
# ==============================================================================

print_header() {
    echo -e "\n${BLUE}=== $1 ===${NC}\n"
}

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

confirm() {
    # Ask for confirmation
    read -p "$1 [y/N] " response
    case "$response" in
        [yY][eE][sS]|[yY])
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        log_error "This script must be run as root."
        log_info "Please run: sudo $0 $*"
        exit 1
    fi
}

check_dependencies() {
    print_header "Checking Dependencies"

    local missing=false

    # Check for Python 3
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is not installed"
        missing=true
    else
        local python_version=$(python3 --version | cut -d' ' -f2)
        log_info "Python ${python_version} found"
    fi

    # Check for PyYAML
    if ! python3 -c "import yaml" &> /dev/null; then
        log_warn "Python YAML module is not installed"
        if $INSTALL_DEPS; then
            log_info "Installing PyYAML..."

            # Try to install PyYAML
            if command -v apt-get &> /dev/null; then
                apt-get update -qq && apt-get install -y python3-yaml
            elif command -v yum &> /dev/null; then
                yum install -y python3-pyyaml
            elif command -v pip3 &> /dev/null; then
                pip3 install pyyaml
            else
                log_error "Could not install PyYAML. Please install it manually."
                missing=true
            fi
        else
            log_warn "Skipping PyYAML installation. The system may not work correctly."
        fi
    else
        log_info "Python YAML module found"
    fi

    # Check for Python prompt_toolkit (needed for the config TUI)
    if ! python3 -c "import prompt_toolkit" &> /dev/null; then
        log_warn "Python prompt_toolkit module is not installed"
        if $INSTALL_DEPS; then
            log_info "Installing prompt_toolkit..."
            pip3 install prompt-toolkit
        else
            log_warn "Skipping prompt_toolkit installation. The configuration UI may not work correctly."
        fi
    else
        log_info "Python prompt_toolkit module found"
    fi

    # Check for email utilities (if notification is enabled)
    if [ -n "$NOTIFY_EMAIL" ]; then
        if ! command -v mail &> /dev/null && ! command -v mailx &> /dev/null; then
            log_warn "Mail command not found, email notifications won't work"
            if $INSTALL_DEPS; then
                log_info "Installing mail utilities..."
                if command -v apt-get &> /dev/null; then
                    apt-get update -qq && apt-get install -y mailutils
                elif command -v yum &> /dev/null; then
                    yum install -y mailx
                else
                    log_warn "Could not install mail utilities. Please install manually for notifications to work."
                fi
            fi
        else
            log_info "Mail utilities found"
        fi
    fi

    # Check for jq (for JSON processing)
    if ! command -v jq &> /dev/null; then
        log_warn "jq is not installed (needed for better JSON processing)"
        if $INSTALL_DEPS; then
            log_info "Installing jq..."
            if command -v apt-get &> /dev/null; then
                apt-get update -qq && apt-get install -y jq
            elif command -v yum &> /dev/null; then
                yum install -y jq
            else
                log_warn "Could not install jq. JSON summary reports may not be available."
            fi
        fi
    else
        log_info "jq found"
    fi

    # Check for container engine (podman or docker)
    if ! command -v podman &> /dev/null && ! command -v docker &> /dev/null; then
        log_warn "Neither Podman nor Docker is installed. Container monitoring will not work."
        if $INSTALL_DEPS; then
            log_info "Attempting to install Podman..."
            if command -v apt-get &> /dev/null; then
                apt-get update -qq && apt-get install -y podman
            elif command -v yum &> /dev/null; then
                yum install -y podman
            else
                log_warn "Could not install Podman. Please install Podman or Docker manually."
            fi
        fi
    elif command -v podman &> /dev/null; then
        log_info "Podman found"
    elif command -v docker &> /dev/null; then
        log_info "Docker found"
    fi

    if $missing; then
        log_error "Please install the missing dependencies and try again."
        exit 1
    fi
}

# ==============================================================================
# Installation Functions
# ==============================================================================

install_system() {
    print_header "Installing LogBuddy System"

    # Create installation directory
    log_info "Creating installation directory: ${INSTALL_DIR}"
    mkdir -p "${INSTALL_DIR}"

    # Create log directory
    log_info "Creating log directory: ${LOG_DIR}"
    mkdir -p "${LOG_DIR}"

    # Create config directory
    log_info "Creating config directory: ${CONFIG_DIR}"
    mkdir -p "${CONFIG_DIR}"
    mkdir -p "${OUTPUT_DIR}"
    mkdir -p "${CACHE_DIR}"
    mkdir -p "${DATA_DIR}"

    # Create logs directory for script logs
    mkdir -p "${INSTALL_DIR}/logs"

    # Create modules directory
    log_info "Creating modules directory: ${INSTALL_DIR}/modules"
    mkdir -p "${INSTALL_DIR}/modules"

    # Create bridges directory
    log_info "Creating bridges directory: ${INSTALL_DIR}/bridges"
    mkdir -p "${INSTALL_DIR}/bridges"

    # Create misc directory
    log_info "Creating misc directory: ${INSTALL_DIR}/misc"
    mkdir -p "${INSTALL_DIR}/misc"

    # Create core directory
    log_info "Creating core directory: ${INSTALL_DIR}/core"
    mkdir -p "${INSTALL_DIR}/core"

    # Create ui directory
    log_info "Creating ui directory: ${INSTALL_DIR}/ui"
    mkdir -p "${INSTALL_DIR}/ui"

    # Copy main files
    log_info "Copying files..."
    cp "${SCRIPT_DIR}/log_discovery.py" "${INSTALL_DIR}/"
    cp "${SCRIPT_DIR}/log_source.py" "${INSTALL_DIR}/"
    cp "${SCRIPT_DIR}/runner.sh" "${INSTALL_DIR}/"
    cp "${SCRIPT_DIR}/README.md" "${INSTALL_DIR}/"
    cp "${SCRIPT_DIR}/install.sh" "${INSTALL_DIR}/"

    # Copy or create the logbuddy.py script
    if [ -f "${SCRIPT_DIR}/logbuddy.py" ]; then
        cp "${SCRIPT_DIR}/logbuddy.py" "${INSTALL_DIR}/"
    else
        # Create logbuddy.py if not exists - this would be filled with proper content
        log_info "Creating logbuddy.py main script"
        cp "${SCRIPT_DIR}/logbuddy.py" "${INSTALL_DIR}/" || true
    fi

    # Copy module files
    log_info "Copying module files..."
    cp "${SCRIPT_DIR}/modules/__init__.py" "${INSTALL_DIR}/modules/"

    # Copy all Python files in the modules directory
    for module_file in "${SCRIPT_DIR}/modules"/*.py; do
        if [ -f "$module_file" ]; then
            cp "$module_file" "${INSTALL_DIR}/modules/"
            log_info "Copied module: $(basename "$module_file")"
        fi
    done

    # Copy core files
    log_info "Copying core files..."
    cp "${SCRIPT_DIR}/core/__init__.py" "${INSTALL_DIR}/core/" 2>/dev/null || touch "${INSTALL_DIR}/core/__init__.py"

    # Copy all Python files in the core directory
    for core_file in "${SCRIPT_DIR}/core"/*.py; do
        if [ -f "$core_file" ]; then
            cp "$core_file" "${INSTALL_DIR}/core/"
            log_info "Copied core module: $(basename "$core_file")"
        fi
    done

    # Copy ui files
    log_info "Copying ui files..."
    cp "${SCRIPT_DIR}/ui/__init__.py" "${INSTALL_DIR}/ui/" 2>/dev/null || touch "${INSTALL_DIR}/ui/__init__.py"

    # Copy all Python files in the ui directory
    for ui_file in "${SCRIPT_DIR}/ui"/*.py; do
        if [ -f "$ui_file" ]; then
            cp "$ui_file" "${INSTALL_DIR}/ui/"
            log_info "Copied UI module: $(basename "$ui_file")"
        fi
    done

    # Copy bridge files
    log_info "Copying bridge files..."
    for bridge_file in "${SCRIPT_DIR}/bridges"/*; do
        if [ -f "$bridge_file" ]; then
            cp "$bridge_file" "${INSTALL_DIR}/bridges/"
            chmod +x "${INSTALL_DIR}/bridges/$(basename "$bridge_file")"
            log_info "Copied bridge: $(basename "$bridge_file")"
        fi
    done

    # Copy misc files
    log_info "Copying misc files..."
    for misc_file in "${SCRIPT_DIR}/misc"/*; do
        if [ -f "$misc_file" ]; then
            cp "$misc_file" "${INSTALL_DIR}/misc/"
            chmod +x "${INSTALL_DIR}/misc/$(basename "$misc_file")"
            log_info "Copied misc file: $(basename "$misc_file")"
        fi
    done

    # Make scripts executable
    chmod +x "${INSTALL_DIR}/log_discovery.py"
    chmod +x "${INSTALL_DIR}/runner.sh"
    chmod +x "${INSTALL_DIR}/install.sh"
    chmod +x "${INSTALL_DIR}/logbuddy.py"

    # Create symlink to executable
    log_info "Creating logbuddy command in ${BIN_DIR}"
    ln -sf "${INSTALL_DIR}/logbuddy.py" "${BIN_DIR}/logbuddy"

    # Create default config
    if [ ! -f "${CONFIG_DIR}/config.json" ]; then
        log_info "Creating default configuration..."
        cat > "${CONFIG_DIR}/config.json" << EOF
{
    "interval": "${DISCOVERY_INTERVAL}",
    "output_dir": "${OUTPUT_DIR}",
    "cache_dir": "${CACHE_DIR}",
    "log_dir": "${LOG_DIR}",
    "data_dir": "${DATA_DIR}",
    "output_format": "json",
    "verbose": false,
    "timeout": 300,
    "notify_email": "${NOTIFY_EMAIL}",
    "container_engine": "podman",
    "promtail_container": "promtail",
    "loki_container": "loki"
}
EOF
    fi

    # Create a symlink to the config directory
    ln -sf "${CONFIG_DIR}" "${INSTALL_DIR}/config"

    # Install service if enabled
    if $SERVICE_ENABLED; then
        install_service
    fi

    # Set up log rotation
    install_logrotate

    log_info "Installation completed successfully!"
    log_info "The LogBuddy system is installed in: ${INSTALL_DIR}"
    log_info "Configuration is stored in: ${CONFIG_DIR}"
    log_info "Logs are stored in: ${LOG_DIR}"

    # Show usage examples
    echo ""
    log_info "You can now use LogBuddy with the following commands:"
    echo "  logbuddy discover     # Discover logs on the system"
    echo "  logbuddy config       # Configure which logs to monitor"
    echo "  logbuddy install      # Install Loki/Promtail with Podman"
    echo "  logbuddy start        # Start monitoring"
    echo "  logbuddy stop         # Stop monitoring"
    echo "  logbuddy status       # Check monitoring status"
    echo "  logbuddy quicksetup   # Perform a quick setup with automatic detection"
    echo "  logbuddy doctor       # Check system health and fix common issues"
    echo "  logbuddy setup        # Interactive setup wizard"
    echo ""
    if $SERVICE_ENABLED; then
        log_info "Or use the systemd service:"
        echo "  systemctl start ${SERVICE_NAME}.service"
        echo "  systemctl status ${SERVICE_NAME}.timer"
    fi

    log_info "To add new log source modules, place Python files in: ${INSTALL_DIR}/modules/"
}

install_service() {
    print_header "Installing Systemd Service"

    # Create systemd service file
    log_info "Creating systemd service file: ${SERVICE_FILE}"

    # Get logbuddy script path with proper escaping
    local logbuddy_path="${INSTALL_DIR}/logbuddy.py"

    cat > "${SERVICE_FILE}" << EOF
[Unit]
Description=LogBuddy Log Discovery and Monitoring System
After=network.target

[Service]
Type=oneshot
ExecStart=${logbuddy_path} discover --output ${OUTPUT_DIR}/discovered_logs.json
WorkingDirectory=${INSTALL_DIR}
StandardOutput=append:${LOG_DIR}/discovery.log
StandardError=append:${LOG_DIR}/discovery.error.log
User=root

[Install]
WantedBy=multi-user.target
EOF

    # Create timer for periodic execution
    log_info "Creating systemd timer: ${TIMER_FILE}"

    # Handle different interval formats
    local on_calendar="${DISCOVERY_INTERVAL}"
    if [[ "${DISCOVERY_INTERVAL}" == "hourly" || "${DISCOVERY_INTERVAL}" == "daily" ||
          "${DISCOVERY_INTERVAL}" == "weekly" || "${DISCOVERY_INTERVAL}" == "monthly" ]]; then
        on_calendar="${DISCOVERY_INTERVAL}"
    elif [[ "${DISCOVERY_INTERVAL}" =~ ^[0-9]+\ [0-9]+\ [*0-9]+\ [*0-9]+\ [*0-9]+$ ]]; then
        # Convert cron expression to systemd format
        # This is a simplified conversion and may not handle all cases
        local min=$(echo "${DISCOVERY_INTERVAL}" | awk '{print $1}')
        local hour=$(echo "${DISCOVERY_INTERVAL}" | awk '{print $2}')
        local day=$(echo "${DISCOVERY_INTERVAL}" | awk '{print $3}')
        local month=$(echo "${DISCOVERY_INTERVAL}" | awk '{print $4}')
        local dow=$(echo "${DISCOVERY_INTERVAL}" | awk '{print $5}')

        on_calendar="*-*-* ${hour}:${min}:00"
    fi

    cat > "${TIMER_FILE}" << EOF
[Unit]
Description=Run LogBuddy periodically
Requires=${SERVICE_NAME}.service

[Timer]
OnCalendar=${on_calendar}
Persistent=true

[Install]
WantedBy=timers.target
EOF

    # Reload systemd
    log_info "Reloading systemd"
    systemctl daemon-reload

    # Enable and start the timer
    log_info "Enabling and starting the timer"
    systemctl enable "${SERVICE_NAME}.timer"
    systemctl start "${SERVICE_NAME}.timer"

    log_info "Systemd service installed successfully!"
    log_info "Service status: systemctl status ${SERVICE_NAME}.timer"
    log_info "Manual execution: systemctl start ${SERVICE_NAME}.service"
    log_info "View logs: journalctl -u ${SERVICE_NAME}"
}

install_logrotate() {
    # Set up log rotation for log files
    if command -v logrotate &> /dev/null; then
        log_info "Setting up log rotation..."

        cat > "/etc/logrotate.d/${SERVICE_NAME}" << EOF
${LOG_DIR}/*.log {
    weekly
    rotate 4
    compress
    delaycompress
    missingok
    notifempty
    create 0640 root root
}
EOF
        log_info "Log rotation configured"
    else
        log_warn "logrotate not found, skipping log rotation setup"
    fi
}

# ==============================================================================
# Removal Functions
# ==============================================================================

remove_system() {
    print_header "Removing LogBuddy System"

    # Prompt for confirmation
    if ! confirm "Are you sure you want to remove the LogBuddy system?"; then
        log_info "Removal cancelled."
        exit 0
    fi

    # Stop and remove service if enabled
    if $SERVICE_ENABLED; then
        remove_service
    fi

    # Remove logrotate configuration
    if [ -f "/etc/logrotate.d/${SERVICE_NAME}" ]; then
        log_info "Removing logrotate configuration"
        rm -f "/etc/logrotate.d/${SERVICE_NAME}"
    fi

    # Remove symlink to executable
    if [ -L "${BIN_DIR}/logbuddy" ]; then
        log_info "Removing logbuddy command from ${BIN_DIR}"
        rm -f "${BIN_DIR}/logbuddy"
    fi

    # Check if installation directory exists
    if [ -d "${INSTALL_DIR}" ]; then
        log_info "Removing installation directory: ${INSTALL_DIR}"
        rm -rf "${INSTALL_DIR}"
    else
        log_warn "Installation directory not found: ${INSTALL_DIR}"
    fi

    # Ask about removing config and logs
    if confirm "Do you want to remove configuration files and logs as well?"; then
        if [ -d "${CONFIG_DIR}" ]; then
            log_info "Removing configuration directory: ${CONFIG_DIR}"
            rm -rf "${CONFIG_DIR}"
        fi

        if [ -d "${LOG_DIR}" ]; then
            log_info "Removing log directory: ${LOG_DIR}"
            rm -rf "${LOG_DIR}"
        fi

        if [ -d "${DATA_DIR}" ]; then
            log_info "Removing data directory: ${DATA_DIR}"
            rm -rf "${DATA_DIR}"
        fi
    else
        log_info "Keeping configuration and logs."
        log_info "  Configuration directory: ${CONFIG_DIR}"
        log_info "  Log directory: ${LOG_DIR}"
        log_info "  Data directory: ${DATA_DIR}"
    fi

    log_info "Removal completed successfully!"
}

remove_service() {
    print_header "Removing Systemd Service"

    # Stop and disable the timer
    if systemctl list-unit-files | grep -q "${SERVICE_NAME}.timer"; then
        log_info "Stopping and disabling timer: ${SERVICE_NAME}.timer"
        systemctl stop "${SERVICE_NAME}.timer" 2>/dev/null || true
        systemctl disable "${SERVICE_NAME}.timer" 2>/dev/null || true
    fi

    # Stop the service
    if systemctl list-unit-files | grep -q "${SERVICE_NAME}.service"; then
        log_info "Stopping service: ${SERVICE_NAME}.service"
        systemctl stop "${SERVICE_NAME}.service" 2>/dev/null || true
        systemctl disable "${SERVICE_NAME}.service" 2>/dev/null || true
    fi

    # Remove service files
    if [ -f "${SERVICE_FILE}" ]; then
        log_info "Removing service file: ${SERVICE_FILE}"
        rm -f "${SERVICE_FILE}"
    fi

    if [ -f "${TIMER_FILE}" ]; then
        log_info "Removing timer file: ${TIMER_FILE}"
        rm -f "${TIMER_FILE}"
    fi

    # Reload systemd
    log_info "Reloading systemd"
    systemctl daemon-reload

    log_info "Systemd service removed successfully!"
}

# ==============================================================================
# Update Functions
# ==============================================================================

update_system() {
    print_header "Updating LogBuddy System"

    # Check if installation directory exists
    if [ ! -d "${INSTALL_DIR}" ]; then
        log_error "Installation directory not found: ${INSTALL_DIR}"
        log_info "Please run the installer with 'install' option first."
        exit 1
    fi

    # Backup existing files
    log_info "Backing up existing files..."
    BACKUP_DIR="${INSTALL_DIR}.backup.$(date +%Y%m%d%H%M%S)"
    mkdir -p "${BACKUP_DIR}"
    cp -r "${INSTALL_DIR}"/* "${BACKUP_DIR}/"

    # Copy main files
    log_info "Updating files..."
    cp "${SCRIPT_DIR}/log_discovery.py" "${INSTALL_DIR}/"
    cp "${SCRIPT_DIR}/log_source.py" "${INSTALL_DIR}/"
    cp "${SCRIPT_DIR}/runner.sh" "${INSTALL_DIR}/"
    cp "${SCRIPT_DIR}/README.md" "${INSTALL_DIR}/"
    cp "${SCRIPT_DIR}/install.sh" "${INSTALL_DIR}/"

    # Copy the logbuddy.py script
    if [ -f "${SCRIPT_DIR}/logbuddy.py" ]; then
        cp "${SCRIPT_DIR}/logbuddy.py" "${INSTALL_DIR}/"
    fi

    # Create modules directory if it doesn't exist
    log_info "Updating modules directory..."
    mkdir -p "${INSTALL_DIR}/modules"

    # Copy module initialization file
    cp "${SCRIPT_DIR}/modules/__init__.py" "${INSTALL_DIR}/modules/"

    # Copy all Python files in the modules directory
    for module_file in "${SCRIPT_DIR}/modules"/*.py; do
        if [ -f "$module_file" ]; then
            cp "$module_file" "${INSTALL_DIR}/modules/"
            log_info "Updated module: $(basename "$module_file")"
        fi
    done

    # Create core directory if it doesn't exist
    log_info "Updating core directory..."
    mkdir -p "${INSTALL_DIR}/core"

    # Copy core init file or create if missing
    cp "${SCRIPT_DIR}/core/__init__.py" "${INSTALL_DIR}/core/" 2>/dev/null || touch "${INSTALL_DIR}/core/__init__.py"

    # Copy all Python files in the core directory
    for core_file in "${SCRIPT_DIR}/core"/*.py; do
        if [ -f "$core_file" ]; then
            cp "$core_file" "${INSTALL_DIR}/core/"
            log_info "Updated core module: $(basename "$core_file")"
        fi
    done

    # Create ui directory if it doesn't exist
    log_info "Updating ui directory..."
    mkdir -p "${INSTALL_DIR}/ui"

    # Copy ui init file or create if missing
    cp "${SCRIPT_DIR}/ui/__init__.py" "${INSTALL_DIR}/ui/" 2>/dev/null || touch "${INSTALL_DIR}/ui/__init__.py"

    # Copy all Python files in the ui directory
    for ui_file in "${SCRIPT_DIR}/ui"/*.py; do
        if [ -f "$ui_file" ]; then
            cp "$ui_file" "${INSTALL_DIR}/ui/"
            log_info "Updated UI module: $(basename "$ui_file")"
        fi
    done

    # Create bridges directory if it doesn't exist
    log_info "Updating bridges directory..."
    mkdir -p "${INSTALL_DIR}/bridges"

    # Copy bridge files
    for bridge_file in "${SCRIPT_DIR}/bridges"/*; do
        if [ -f "$bridge_file" ]; then
            cp "$bridge_file" "${INSTALL_DIR}/bridges/"
            chmod +x "${INSTALL_DIR}/bridges/$(basename "$bridge_file")"
            log_info "Updated bridge: $(basename "$bridge_file")"
        fi
    done

    # Create misc directory if it doesn't exist
    log_info "Updating misc directory..."
    mkdir -p "${INSTALL_DIR}/misc"

    # Copy misc files
    for misc_file in "${SCRIPT_DIR}/misc"/*; do
        if [ -f "$misc_file" ]; then
            cp "$misc_file" "${INSTALL_DIR}/misc/"
            chmod +x "${INSTALL_DIR}/misc/$(basename "$misc_file")"
            log_info "Updated misc file: $(basename "$misc_file")"
        fi
    done

    # Make scripts executable
    chmod +x "${INSTALL_DIR}/log_discovery.py"
    chmod +x "${INSTALL_DIR}/runner.sh"
    chmod +x "${INSTALL_DIR}/install.sh"
    chmod +x "${INSTALL_DIR}/logbuddy.py"

    # Update symlink to executable
    log_info "Updating logbuddy command in ${BIN_DIR}"
    ln -sf "${INSTALL_DIR}/logbuddy.py" "${BIN_DIR}/logbuddy"

    # Create config directories if they don't exist
    mkdir -p "${OUTPUT_DIR}"
    mkdir -p "${CACHE_DIR}"
    mkdir -p "${DATA_DIR}"
    mkdir -p "${INSTALL_DIR}/logs"

    # Update the config if notify_email has been set
    if [ -n "$NOTIFY_EMAIL" ] && [ -f "${CONFIG_DIR}/config.json" ]; then
        log_info "Updating email notification setting..."
        # Use sed to update the notify_email field, or jq if available
        if command -v jq &> /dev/null; then
            jq --arg email "$NOTIFY_EMAIL" '.notify_email = $email' "${CONFIG_DIR}/config.json" > "${CONFIG_DIR}/config.json.tmp"
            mv "${CONFIG_DIR}/config.json.tmp" "${CONFIG_DIR}/config.json"
        else
            # Simple sed replacement (not as robust as jq)
            sed -i "s/\"notify_email\": \".*\"/\"notify_email\": \"${NOTIFY_EMAIL}\"/" "${CONFIG_DIR}/config.json" || true
        fi
    fi

    # Update service if enabled
    if $SERVICE_ENABLED; then
        update_service
    fi

    # Update logrotate config
    install_logrotate

    log_info "Update completed successfully!"
    log_info "A backup of the previous installation is stored in: ${BACKUP_DIR}"
}

update_service() {
    print_header "Updating Systemd Service"

    # Check if service exists
    if [ ! -f "${SERVICE_FILE}" ]; then
        log_info "Service file not found, installing new service..."
        install_service
        return
    fi

    # Update service file
    log_info "Updating systemd service file: ${SERVICE_FILE}"

    # Get logbuddy script path
    local logbuddy_path="${INSTALL_DIR}/logbuddy.py"

    cat > "${SERVICE_FILE}" << EOF
[Unit]
Description=LogBuddy Log Discovery and Monitoring System
After=network.target

[Service]
Type=oneshot
ExecStart=${logbuddy_path} discover --output ${OUTPUT_DIR}/discovered_logs.json
WorkingDirectory=${INSTALL_DIR}
StandardOutput=append:${LOG_DIR}/discovery.log
StandardError=append:${LOG_DIR}/discovery.error.log
User=root

[Install]
WantedBy=multi-user.target
EOF

    # Update timer file only if interval has changed
    if [ -n "$DISCOVERY_INTERVAL" ]; then
        log_info "Updating systemd timer with interval: ${DISCOVERY_INTERVAL}"

        # Handle different interval formats
        local on_calendar="${DISCOVERY_INTERVAL}"
        if [[ "${DISCOVERY_INTERVAL}" == "hourly" || "${DISCOVERY_INTERVAL}" == "daily" ||
              "${DISCOVERY_INTERVAL}" == "weekly" || "${DISCOVERY_INTERVAL}" == "monthly" ]]; then
            on_calendar="${DISCOVERY_INTERVAL}"
        elif [[ "${DISCOVERY_INTERVAL}" =~ ^[0-9]+\ [0-9]+\ [*0-9]+\ [*0-9]+\ [*0-9]+$ ]]; then
            # Convert cron expression to systemd format
            local min=$(echo "${DISCOVERY_INTERVAL}" | awk '{print $1}')
            local hour=$(echo "${DISCOVERY_INTERVAL}" | awk '{print $2}')
            local day=$(echo "${DISCOVERY_INTERVAL}" | awk '{print $3}')
            local month=$(echo "${DISCOVERY_INTERVAL}" | awk '{print $4}')
            local dow=$(echo "${DISCOVERY_INTERVAL}" | awk '{print $5}')

            on_calendar="*-*-* ${hour}:${min}:00"
        fi

        cat > "${TIMER_FILE}" << EOF
[Unit]
Description=Run LogBuddy periodically
Requires=${SERVICE_NAME}.service

[Timer]
OnCalendar=${on_calendar}
Persistent=true

[Install]
WantedBy=timers.target
EOF
    fi

    # Reload systemd
    log_info "Reloading systemd"
    systemctl daemon-reload

    # Restart the timer if it was active
    if systemctl is-active --quiet "${SERVICE_NAME}.timer"; then
        log_info "Restarting timer"
        systemctl restart "${SERVICE_NAME}.timer"
    fi

    log_info "Systemd service updated successfully!"
}

# ==============================================================================
# Main Script
# ==============================================================================

# Parse command line arguments
ACTION=${1:-help}
shift || true

# Check additional options
while [[ $# -gt 0 ]]; do
    case $1 in
        --no-service)
            SERVICE_ENABLED=false
            shift
            ;;
        --no-deps)
            INSTALL_DEPS=false
            shift
            ;;
        --interval)
            DISCOVERY_INTERVAL="$2"
            shift 2
            ;;
        --email)
            NOTIFY_EMAIL="$2"
            shift 2
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Display script banner
echo -e "${BLUE}"
echo "===================================================="
echo "  LogBuddy - Log Discovery and Monitoring System    "
echo "  Installer v1.0.0                                  "
echo "===================================================="
echo -e "${NC}"

# Check if running as root
check_root "$@"

# Execute the appropriate action
case ${ACTION} in
    install)
        check_dependencies
        install_system
        ;;
    remove)
        remove_system
        ;;
    update)
        check_dependencies
        update_system
        ;;
    help|*)
        echo "Usage: $0 [install|remove|update] [options]"
        echo ""
        echo "Actions:"
        echo "  install       Install the LogBuddy system"
        echo "  remove        Remove the LogBuddy system"
        echo "  update        Update the LogBuddy system"
        echo ""
        echo "Options:"
        echo "  --no-service  Don't install/remove the systemd service"
        echo "  --no-deps     Skip dependency installation"
        echo "  --interval    Set discovery interval (daily, hourly, or cron expression)"
        echo "                Example: --interval \"0 4 * * *\" (run at 4 AM daily)"
        echo "  --email       Set notification email for automated reports"
        echo "                Example: --email admin@example.com"
        exit 1
        ;;
esac

# Successful exit
exit 0