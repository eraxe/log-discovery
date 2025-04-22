#!/bin/bash
# =====================================================================
# Log Discovery to Promtail/Loki Updater
# =====================================================================
#
# This script automates the process of discovering logs, generating
# Promtail configuration, and updating Loki/Promtail containers.
#
# Usage: ./update_monitoring.sh [options]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISCOVERY_SCRIPT="${SCRIPT_DIR}/../log_discovery.py"
CONFIG_GENERATOR="${SCRIPT_DIR}/promtail_conf_gen.py"
OUTPUT_DIR="${SCRIPT_DIR}/output"
CONFIG_DIR="${SCRIPT_DIR}/config"
LOG_FILE="${SCRIPT_DIR}/logs/update-monitoring.log"
DISCOVERED_LOGS="${OUTPUT_DIR}/discovered_logs.json"
PROMTAIL_CONFIG="${OUTPUT_DIR}/promtail-config.yaml"
CONFIG_FILE="${CONFIG_DIR}/promtail-config-settings.yaml"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default options
VERBOSE=false
DOCKER_UPDATE=false
DISCOVERY_ONLY=false
CONTAINER_ENGINE="podman" # or "docker"
PROMTAIL_CONTAINER="promtail"
LOKI_CONTAINER="loki"
FORCE_UPDATE=false
DRY_RUN=false

# ==============================
# Helper Functions
# ==============================

print_header() {
  echo -e "\n${BLUE}=== $1 ===${NC}\n"
}

log_info() {
  local timestamp=$(date +"%Y-%m-%d %H:%M:%S")
  echo -e "${GREEN}[INFO]${NC} $1"
  echo "[INFO] $timestamp - $1" >> "${LOG_FILE}"
}

log_warn() {
  local timestamp=$(date +"%Y-%m-%d %H:%M:%S")
  echo -e "${YELLOW}[WARN]${NC} $1"
  echo "[WARN] $timestamp - $1" >> "${LOG_FILE}"
}

log_error() {
  local timestamp=$(date +"%Y-%m-%d %H:%M:%S")
  echo -e "${RED}[ERROR]${NC} $1"
  echo "[ERROR] $timestamp - $1" >> "${LOG_FILE}"
}

# Show help
show_help() {
  cat << EOF
Usage: $0 [options]

Options:
  -h, --help             Show this help message
  -v, --verbose          Enable verbose output
  -d, --discovery-only   Only run log discovery, don't update Promtail config
  -u, --update-container Update Promtail container with new configuration
  -e, --engine ENGINE    Container engine: docker or podman (default: ${CONTAINER_ENGINE})
  -p, --promtail NAME    Promtail container name (default: ${PROMTAIL_CONTAINER})
  -l, --loki NAME        Loki container name (default: ${LOKI_CONTAINER})
  -f, --force            Force update even if configuration hasn't changed
  --dry-run              Perform a dry run without updating containers

Description:
  This script automates the process of discovering logs, generating
  Promtail configuration, and updating Loki/Promtail containers.

  It uses log_discovery.py to find logs, promtail_conf_gen.py
  to create the appropriate Promtail configuration, and optionally updates
  the running containers.

Example:
  # Basic usage
  $0 --verbose

  # Run only log discovery
  $0 --discovery-only --verbose

  # Update containers after generating configuration
  $0 --update-container

  # Use Docker instead of Podman
  $0 --engine docker --update-container
EOF
}

# Create required directories
create_directories() {
  mkdir -p "${OUTPUT_DIR}"
  mkdir -p "${CONFIG_DIR}"
  mkdir -p "$(dirname "${LOG_FILE}")"
}

# Run log discovery
run_discovery() {
  print_header "Running Log Discovery"

  log_info "Running log discovery script..."

  if [ "$VERBOSE" = true ]; then
    python3 "${DISCOVERY_SCRIPT}" --verbose --output "${DISCOVERED_LOGS}"
  else
    python3 "${DISCOVERY_SCRIPT}" --output "${DISCOVERED_LOGS}"
  fi

  if [ $? -eq 0 ]; then
    log_info "Log discovery completed successfully"
  else
    log_error "Log discovery failed"
    exit 1
  fi
}

# Generate Promtail configuration
generate_promtail_config() {
  print_header "Generating Promtail Configuration"

  # Check if config file exists
  if [ ! -f "${CONFIG_FILE}" ]; then
    log_warn "Promtail config settings file not found: ${CONFIG_FILE}"
    log_info "Creating default config file..."

    # Create default config file
    cat > "${CONFIG_FILE}" << EOF
# Promtail Config Generator Settings

# Loki server URL
loki_url: http://loki:3100/loki/api/v1/push

# Promtail settings
promtail_port: 9080
positions_file: /var/lib/promtail/positions.yaml
promtail_container: ${PROMTAIL_CONTAINER}
docker_command: ${CONTAINER_ENGINE}

# Log filtering
include_types:
  - openlitespeed
  - wordpress
  - php
  - mysql
  - cyberpanel

include_services:
  - webserver
  - wordpress
  - database
  - script_handler

# Path patterns (regular expressions)
include_patterns:
  - '\.log$'
  - '/var/log/'
  - '/usr/local/lsws/'

exclude_patterns:
  - '\.cache$'
  - '/tmp/'
  - 'debug_backup'
  - '\.(gz|zip|bz2)$'

# Log size limits (MB, 0 to disable)
max_log_size_mb: 100

# Name shortening
shorten_names: true
max_name_length: 40
EOF
  fi

  log_info "Generating Promtail configuration..."

  # Build command
  CMD="python3 ${CONFIG_GENERATOR} --input ${DISCOVERED_LOGS} --output ${PROMTAIL_CONFIG} --config ${CONFIG_FILE}"

  if [ "$DOCKER_UPDATE" = true ]; then
    CMD="${CMD} --docker-update"
  fi

  if [ "$VERBOSE" = true ]; then
    $CMD
  else
    $CMD > /dev/null
  fi

  if [ $? -eq 0 ]; then
    log_info "Promtail configuration generated successfully"
  else
    log_error "Failed to generate Promtail configuration"
    exit 1
  fi
}

# Update containers
update_containers() {
  if [ "$DRY_RUN" = true ]; then
    print_header "Dry Run - Not Updating Containers"
    log_info "Would update Promtail container: ${PROMTAIL_CONTAINER}"
    log_info "Using container engine: ${CONTAINER_ENGINE}"
    return
  fi

  print_header "Updating Monitoring Containers"

  # Check if container exists
  ${CONTAINER_ENGINE} container inspect ${PROMTAIL_CONTAINER} &> /dev/null
  if [ $? -ne 0 ]; then
    log_error "Promtail container '${PROMTAIL_CONTAINER}' not found"
    return 1
  fi

  log_info "Copying Promtail configuration to container..."
  ${CONTAINER_ENGINE} cp "${PROMTAIL_CONFIG}" "${PROMTAIL_CONTAINER}:/etc/promtail/config.yml"

  if [ $? -ne 0 ]; then
    log_error "Failed to copy configuration to Promtail container"
    return 1
  fi

  log_info "Restarting Promtail container..."
  ${CONTAINER_ENGINE} restart "${PROMTAIL_CONTAINER}"

  if [ $? -ne 0 ]; then
    log_error "Failed to restart Promtail container"
    return 1
  fi

  log_info "Successfully updated Promtail container"

  # Check if Loki container exists and restart it if needed
  ${CONTAINER_ENGINE} container inspect ${LOKI_CONTAINER} &> /dev/null
  if [ $? -eq 0 ]; then
    log_info "Checking Loki container status..."
    LOKI_STATUS=$(${CONTAINER_ENGINE} inspect --format='{{.State.Status}}' ${LOKI_CONTAINER})

    if [ "$LOKI_STATUS" != "running" ]; then
      log_info "Starting Loki container..."
      ${CONTAINER_ENGINE} start "${LOKI_CONTAINER}"
    else
      log_info "Loki container is already running"
    fi
  else
    log_warn "Loki container '${LOKI_CONTAINER}' not found, skipping"
  fi

  return 0
}

# Parse command-line arguments
parse_args() {
  while [[ $# -gt 0 ]]; do
    case $1 in
      -h|--help)
        show_help
        exit 0
        ;;
      -v|--verbose)
        VERBOSE=true
        shift
        ;;
      -d|--discovery-only)
        DISCOVERY_ONLY=true
        shift
        ;;
      -u|--update-container)
        DOCKER_UPDATE=true
        shift
        ;;
      -e|--engine)
        CONTAINER_ENGINE="$2"
        shift 2
        ;;
      -p|--promtail)
        PROMTAIL_CONTAINER="$2"
        shift 2
        ;;
      -l|--loki)
        LOKI_CONTAINER="$2"
        shift 2
        ;;
      -f|--force)
        FORCE_UPDATE=true
        shift
        ;;
      --dry-run)
        DRY_RUN=true
        shift
        ;;
      *)
        log_error "Unknown option: $1"
        show_help
        exit 1
        ;;
    esac
  done
}

# Check if configuration has changed
config_changed() {
  # If force update is enabled, always return changed
  if [ "$FORCE_UPDATE" = true ]; then
    return 0
  fi

  # Check if previous config exists
  if [ ! -f "${PROMTAIL_CONFIG}.prev" ]; then
    return 0
  fi

  # Compare current and previous configs
  diff -q "${PROMTAIL_CONFIG}" "${PROMTAIL_CONFIG}.prev" &> /dev/null
  return $?
}

# Main function
main() {
  # Parse command-line arguments
  parse_args "$@"

  print_header "Log Discovery to Promtail/Loki Updater"

  # Create required directories
  create_directories

  # Run log discovery
  run_discovery

  # Stop here if discovery only
  if [ "$DISCOVERY_ONLY" = true ]; then
    log_info "Discovery completed. Skipping configuration update as requested."
    exit 0
  fi

  # Generate Promtail configuration
  generate_promtail_config

  # Make backup of current config
  if [ -f "${PROMTAIL_CONFIG}" ]; then
    cp "${PROMTAIL_CONFIG}" "${PROMTAIL_CONFIG}.prev"
  fi

  # Update containers if requested
  if [ "$DOCKER_UPDATE" = true ]; then
    # Check if config has changed
    if config_changed; then
      log_info "Configuration has changed, updating containers..."
      update_containers
    else
      log_info "Configuration hasn't changed, skipping container update"
      if [ "$FORCE_UPDATE" = true ]; then
        log_info "Force update enabled, updating containers anyway..."
        update_containers
      fi
    fi
  else
    log_info "Container update not requested. Use --update-container to update Promtail."
  fi

  log_info "Process completed successfully"
}

# Run the main function
main "$@"