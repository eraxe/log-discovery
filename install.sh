#!/bin/bash
# ==============================================================================
# OpenLiteSpeed/CyberPanel/WordPress Log Discovery System Installer
# ==============================================================================
#
# This script installs, removes, or updates the log discovery system.
# Usage: ./installer.sh [install|remove|update] [--no-service]
#
# Options:
#   install     Install the log discovery system
#   remove      Remove the log discovery system
#   update      Update the log discovery system
#   --no-service  Don't install/remove the systemd service
#
# Author: Claude
# Created: April 21, 2025
# ==============================================================================

set -e

# Configuration
INSTALL_DIR="/opt/log-discovery"
SERVICE_NAME="log-discovery"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SERVICE_ENABLED=true
LOG_DIR="/var/log/log-discovery"
CONFIG_DIR="/etc/${SERVICE_NAME}"
DISCOVERY_INTERVAL="daily"  # daily, hourly, or a cron expression like "0 4 * * *"

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
        log_info "Python YAML module found"
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
    print_header "Installing Log Discovery System"
    
    # Create installation directory
    log_info "Creating installation directory: ${INSTALL_DIR}"
    mkdir -p "${INSTALL_DIR}"
    
    # Create log directory
    log_info "Creating log directory: ${LOG_DIR}"
    mkdir -p "${LOG_DIR}"
    
    # Create config directory
    log_info "Creating config directory: ${CONFIG_DIR}"
    mkdir -p "${CONFIG_DIR}"
    mkdir -p "${CONFIG_DIR}/output"
    
    # Copy files
    log_info "Copying files..."
    cp "${SCRIPT_DIR}/log_discovery.py" "${INSTALL_DIR}/"
    cp "${SCRIPT_DIR}/run_log_discovery.sh" "${INSTALL_DIR}/"
    cp "${SCRIPT_DIR}/README.md" "${INSTALL_DIR}/"
    
    # Make scripts executable
    chmod +x "${INSTALL_DIR}/log_discovery.py"
    chmod +x "${INSTALL_DIR}/run_log_discovery.sh"
    
    # Create default config
    if [ ! -f "${CONFIG_DIR}/config.json" ]; then
        log_info "Creating default configuration..."
        cat > "${CONFIG_DIR}/config.json" << EOF
{
    "interval": "${DISCOVERY_INTERVAL}",
    "output_dir": "${CONFIG_DIR}/output",
    "output_format": "json",
    "verbose": false
}
EOF
    fi
    
    # Create a symlink to the config directory
    ln -sf "${CONFIG_DIR}" "${INSTALL_DIR}/config"
    
    # Install service if enabled
    if $SERVICE_ENABLED; then
        install_service
    fi
    
    log_info "Installation completed successfully!"
    log_info "The log discovery system is installed in: ${INSTALL_DIR}"
    log_info "Configuration is stored in: ${CONFIG_DIR}"
    log_info "Logs are stored in: ${LOG_DIR}"
}

install_service() {
    print_header "Installing Systemd Service"
    
    # Create systemd service file
    log_info "Creating systemd service file: ${SERVICE_FILE}"
    
    cat > "${SERVICE_FILE}" << EOF
[Unit]
Description=Log Discovery System for OpenLiteSpeed/CyberPanel/WordPress
After=network.target

[Service]
Type=oneshot
ExecStart=${INSTALL_DIR}/run_log_discovery.sh --cron --output ${CONFIG_DIR}/output/discovered_logs.json
WorkingDirectory=${INSTALL_DIR}
StandardOutput=append:${LOG_DIR}/discovery.log
StandardError=append:${LOG_DIR}/discovery.error.log
User=root

[Install]
WantedBy=multi-user.target
EOF
    
    # Create timer for periodic execution
    log_info "Creating systemd timer"
    cat > "/etc/systemd/system/${SERVICE_NAME}.timer" << EOF
[Unit]
Description=Run Log Discovery System periodically
Requires=${SERVICE_NAME}.service

[Timer]
OnCalendar=${DISCOVERY_INTERVAL}
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

# ==============================================================================
# Removal Functions
# ==============================================================================

remove_system() {
    print_header "Removing Log Discovery System"
    
    # Prompt for confirmation
    if ! confirm "Are you sure you want to remove the log discovery system?"; then
        log_info "Removal cancelled."
        exit 0
    fi
    
    # Stop and remove service if enabled
    if $SERVICE_ENABLED; then
        remove_service
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
    else
        log_info "Keeping configuration and logs."
        log_info "  Configuration directory: ${CONFIG_DIR}"
        log_info "  Log directory: ${LOG_DIR}"
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
    
    if [ -f "/etc/systemd/system/${SERVICE_NAME}.timer" ]; then
        log_info "Removing timer file: /etc/systemd/system/${SERVICE_NAME}.timer"
        rm -f "/etc/systemd/system/${SERVICE_NAME}.timer"
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
    print_header "Updating Log Discovery System"
    
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
    
    # Copy new files
    log_info "Updating files..."
    cp "${SCRIPT_DIR}/log_discovery.py" "${INSTALL_DIR}/"
    cp "${SCRIPT_DIR}/run_log_discovery.sh" "${INSTALL_DIR}/"
    cp "${SCRIPT_DIR}/README.md" "${INSTALL_DIR}/"
    
    # Make scripts executable
    chmod +x "${INSTALL_DIR}/log_discovery.py"
    chmod +x "${INSTALL_DIR}/run_log_discovery.sh"
    
    # Update service if enabled
    if $SERVICE_ENABLED; then
        update_service
    fi
    
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
    
    cat > "${SERVICE_FILE}" << EOF
[Unit]
Description=Log Discovery System for OpenLiteSpeed/CyberPanel/WordPress
After=network.target

[Service]
Type=oneshot
ExecStart=${INSTALL_DIR}/run_log_discovery.sh --cron --output ${CONFIG_DIR}/output/discovered_logs.json
WorkingDirectory=${INSTALL_DIR}
StandardOutput=append:${LOG_DIR}/discovery.log
StandardError=append:${LOG_DIR}/discovery.error.log
User=root

[Install]
WantedBy=multi-user.target
EOF
    
    # Update timer file
    log_info "Updating systemd timer"
    cat > "/etc/systemd/system/${SERVICE_NAME}.timer" << EOF
[Unit]
Description=Run Log Discovery System periodically
Requires=${SERVICE_NAME}.service

[Timer]
OnCalendar=${DISCOVERY_INTERVAL}
Persistent=true

[Install]
WantedBy=timers.target
EOF
    
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
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Display script banner
echo -e "${BLUE}"
echo "===================================================="
echo "  OpenLiteSpeed/CyberPanel/WordPress Log Discovery  "
echo "  System Installer                                  "
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
        echo "Usage: $0 [install|remove|update] [--no-service]"
        echo ""
        echo "Options:"
        echo "  install       Install the log discovery system"
        echo "  remove        Remove the log discovery system"
        echo "  update        Update the log discovery system"
        echo "  --no-service  Don't install/remove the systemd service"
        exit 1
        ;;
esac

# Successful exit
exit 0
