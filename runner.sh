#!/bin/bash
# =====================================================================
# OpenLiteSpeed/CyberPanel/WordPress Log Discovery Runner
# =====================================================================
#
# This enhanced script runs the log discovery system with improved
# error handling, performance monitoring, and notification support.
#
# Usage: ./run_log_discovery.sh [-h|--help] [-v|--verbose] [-o|--output FILE]
#                              [-f|--format FORMAT] [-c|--cron] [-t|--timeout SEC]
#                              [-i|--include TYPES] [-e|--exclude TYPES]
#                              [--cache FILE] [--notify EMAIL]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISCOVERY_SCRIPT="${SCRIPT_DIR}/log_discovery.py"
OUTPUT_DIR="${SCRIPT_DIR}/output"
CACHE_DIR="${SCRIPT_DIR}/cache"
DEFAULT_OUTPUT="${OUTPUT_DIR}/discovered_logs.json"
DEFAULT_CACHE="${CACHE_DIR}/discovery_cache.json"
LOG_FILE="${SCRIPT_DIR}/logs/discovery.log"
ERROR_LOG="${SCRIPT_DIR}/logs/error.log"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default options
VERBOSE=false
OUTPUT_FILE="${DEFAULT_OUTPUT}"
FORMAT="json"
CRON_MODE=false
CACHE_FILE="${DEFAULT_CACHE}"
TIMEOUT=300
INCLUDE_TYPES=""
EXCLUDE_TYPES=""
NOTIFY_EMAIL=""
VALIDATE=false

# ==============================
# Helper Functions
# ==============================

print_header() {
  echo -e "\n${BLUE}=== $1 ===${NC}\n"
}

log_info() {
  local timestamp=$(date +"%Y-%m-%d %H:%M:%S")
  if $CRON_MODE; then
    echo "[INFO] $timestamp - $1" >> "${LOG_FILE}"
  else
    echo -e "${GREEN}[INFO]${NC} $1"
    echo "[INFO] $timestamp - $1" >> "${LOG_FILE}"
  fi
}

log_warn() {
  local timestamp=$(date +"%Y-%m-%d %H:%M:%S")
  if $CRON_MODE; then
    echo "[WARN] $timestamp - $1" >> "${LOG_FILE}"
  else
    echo -e "${YELLOW}[WARN]${NC} $1"
    echo "[WARN] $timestamp - $1" >> "${LOG_FILE}"
  fi
}

log_error() {
  local timestamp=$(date +"%Y-%m-%d %H:%M:%S")
  if $CRON_MODE; then
    echo "[ERROR] $timestamp - $1" >> "${ERROR_LOG}"
  else
    echo -e "${RED}[ERROR]${NC} $1"
    echo "[ERROR] $timestamp - $1" >> "${ERROR_LOG}"
  fi
}

# Show help
show_help() {
  cat << EOF
Usage: $0 [options]

Options:
  -h, --help             Show this help message
  -v, --verbose          Enable verbose output
  -o, --output FILE      Output file path (default: ${DEFAULT_OUTPUT})
  -f, --format FORMAT    Output format: json or yaml (default: json)
  -c, --cron             Run in cron mode (minimal output, only errors to stderr)
  -t, --timeout SEC      Set timeout in seconds (default: 300)
  -i, --include TYPES    Include only specified log types (comma-separated)
  -e, --exclude TYPES    Exclude specified log types (comma-separated)
  --cache FILE           Cache file path (default: ${DEFAULT_CACHE})
  --validate             Validate log files (check permissions)
  --notify EMAIL         Send notification email on completion/failure

Description:
  This script runs the log discovery system to find logs from OpenLiteSpeed,
  CyberPanel, and WordPress installations by analyzing their configuration
  files rather than just searching for common patterns.

  The output is a structured JSON or YAML file that can be used as input
  for configuring Loki/Promtail or other log aggregation systems.

Supported log types:
  - openlitespeed: OpenLiteSpeed web server logs
  - cyberpanel: CyberPanel admin panel logs
  - wordpress: WordPress site logs
  - php: PHP configuration logs
  - mysql: MySQL/MariaDB database logs

Examples:
  # Basic usage
  $0 --verbose

  # Specify output format and file
  $0 --format yaml --output /tmp/my_logs.yaml

  # Only discover WordPress and PHP logs
  $0 --include wordpress,php

  # Run in cron mode with email notification
  $0 --cron --notify admin@example.com

  # Set custom timeout and use caching
  $0 --timeout 600 --cache /var/cache/log_discovery.json
EOF
}

# Send email notification
send_notification() {
  local status=$1
  local message=$2
  local attachment=$3

  if [ -z "$NOTIFY_EMAIL" ]; then
    return
  fi

  local hostname=$(hostname)
  local subject="Log Discovery Report from ${hostname}: ${status}"

  if [ -n "$attachment" ] && [ -f "$attachment" ]; then
    # Check if mail command supports attachments
    if command -v mailx &> /dev/null; then
      echo "$message" | mailx -s "$subject" -a "$attachment" "$NOTIFY_EMAIL"
    else
      # Fallback to basic mail
      {
        echo "$message"
        echo ""
        echo "Log discovery results available at: $attachment"
      } | mail -s "$subject" "$NOTIFY_EMAIL"
    fi
  else
    echo "$message" | mail -s "$subject" "$NOTIFY_EMAIL"
  fi
}

# Check dependencies
check_dependencies() {
  if ! $CRON_MODE; then
    print_header "Checking Dependencies"
  fi

  local missing=false

  if ! command -v python3 &> /dev/null; then
    log_error "Python 3 is not installed"
    missing=true
  else
    local python_version=$(python3 --version | cut -d' ' -f2)
    if ! $CRON_MODE; then
      log_info "Python ${python_version} found"
    fi

    # Check for required Python modules
    for module in yaml; do
      if ! python3 -c "import $module" &> /dev/null; then
        log_error "Python module '$module' is not installed"
        log_info "Install with: pip3 install pyyaml"
        missing=true
      fi
    done
  fi

  # Check for optional dependencies
  if [ -n "$NOTIFY_EMAIL" ]; then
    if ! command -v mail &> /dev/null && ! command -v mailx &> /dev/null; then
      log_warn "Mail command not found, email notifications will not work"
      log_info "Install with: apt-get install mailutils (Debian/Ubuntu) or yum install mailx (CentOS/RHEL)"
    fi
  fi

  if command -v jq &> /dev/null; then
    if ! $CRON_MODE; then
      log_info "jq found, will use for JSON processing"
    fi
  fi

  if $missing; then
    if [ -n "$NOTIFY_EMAIL" ]; then
      send_notification "ERROR" "Log discovery failed due to missing dependencies."
    fi

    echo -e "\nPlease install the missing dependencies and try again."
    exit 1
  fi
}

# Create required directories
create_directories() {
  mkdir -p "${OUTPUT_DIR}"
  mkdir -p "${CACHE_DIR}"
  mkdir -p "$(dirname "${LOG_FILE}")"
}

# Verify discovery script exists and is executable
verify_discovery_script() {
  if [ ! -f "${DISCOVERY_SCRIPT}" ]; then
    log_error "Discovery script not found: ${DISCOVERY_SCRIPT}"
    exit 1
  fi

  # Ensure the discovery script is executable
  chmod +x "${DISCOVERY_SCRIPT}" 2>/dev/null || true
}

# Run the log discovery script
run_discovery() {
  local options=""

  if $VERBOSE; then
    options="${options} --verbose"
  fi

  if [ -n "$INCLUDE_TYPES" ]; then
    options="${options} --include ${INCLUDE_TYPES}"
  fi

  if [ -n "$EXCLUDE_TYPES" ]; then
    options="${options} --exclude ${EXCLUDE_TYPES}"
  fi

  if [ -n "$CACHE_FILE" ]; then
    options="${options} --cache-file ${CACHE_FILE}"
  fi

  if [ "$TIMEOUT" -gt 0 ]; then
    options="${options} --timeout ${TIMEOUT}"
  fi

  if $VALIDATE; then
    options="${options} --validate"
  fi

  if ! $CRON_MODE; then
    print_header "Running Log Discovery"
    log_info "Output will be written to: ${OUTPUT_FILE}"
    log_info "Format: ${FORMAT}"

    if [ -n "$INCLUDE_TYPES" ]; then
      log_info "Including only: ${INCLUDE_TYPES}"
    fi

    if [ -n "$EXCLUDE_TYPES" ]; then
      log_info "Excluding: ${EXCLUDE_TYPES}"
    fi

    if [ -n "$CACHE_FILE" ]; then
      log_info "Using cache file: ${CACHE_FILE}"
    fi

    if [ "$TIMEOUT" -gt 0 ]; then
      log_info "Timeout: ${TIMEOUT} seconds"
    fi
  fi

  # Record start time
  local start_time=$(date +%s)

  # Run the discovery script with timeout
  local exit_code=0
  local temp_output=$(mktemp)

  # Use timeout command if available
  if command -v timeout &> /dev/null; then
    if $CRON_MODE; then
      timeout --kill-after=30 $((TIMEOUT + 30)) python3 "${DISCOVERY_SCRIPT}" ${options} --format "${FORMAT}" --output "${OUTPUT_FILE}" > "${temp_output}" 2>&1 || exit_code=$?
    else
      timeout --kill-after=30 $((TIMEOUT + 30)) python3 "${DISCOVERY_SCRIPT}" ${options} --format "${FORMAT}" --output "${OUTPUT_FILE}" || exit_code=$?
    fi
  else
    # Fallback to built-in timeout
    if $CRON_MODE; then
      python3 "${DISCOVERY_SCRIPT}" ${options} --format "${FORMAT}" --output "${OUTPUT_FILE}" > "${temp_output}" 2>&1 || exit_code=$?
    else
      python3 "${DISCOVERY_SCRIPT}" ${options} --format "${FORMAT}" --output "${OUTPUT_FILE}" || exit_code=$?
    fi
  fi

  # Record end time and calculate duration
  local end_time=$(date +%s)
  local duration=$((end_time - start_time))

  # Check exit code
  if [ $exit_code -ne 0 ]; then
    log_error "Log discovery failed with exit code ${exit_code}"
    if [ -f "${temp_output}" ]; then
      log_error "Error output: $(cat "${temp_output}")"
      rm -f "${temp_output}"
    fi

    if [ -n "$NOTIFY_EMAIL" ]; then
      send_notification "FAILED" "Log discovery failed with exit code ${exit_code}. Execution time: ${duration} seconds."
    fi

    exit $exit_code
  fi

  # Clean up temp file
  if [ -f "${temp_output}" ]; then
    rm -f "${temp_output}"
  fi

  if ! $CRON_MODE; then
    log_info "Log discovery completed successfully!"
    log_info "Execution time: ${duration} seconds"
    log_info "Results saved to: ${OUTPUT_FILE}"

    # Display summary of discovered logs
    if [ -f "${OUTPUT_FILE}" ]; then
      if [[ "$FORMAT" == "json" ]] && command -v jq &> /dev/null; then
        echo ""
        echo "Summary of discovered logs:"
        echo "============================"
        jq -r '.sources | group_by(.type) | map({type: .[0].type, count: length, existing: map(select(.exists == true)) | length}) | .[] | "\(.type): \(.count) found, \(.existing) accessible"' "${OUTPUT_FILE}" || true

        echo ""
        echo "Total counts:"
        echo "============="
        jq -r '.sources | length | "Total logs: \(.)"' "${OUTPUT_FILE}"
        jq -r '.sources | map(select(.exists == true)) | length | "Accessible logs: \(.)"' "${OUTPUT_FILE}"
      elif [[ "$FORMAT" == "yaml" ]] && command -v python3 &> /dev/null; then
        echo ""
        echo "Summary of discovered logs:"
        echo "============================"
        python3 -c "
import yaml, sys
try:
    with open('${OUTPUT_FILE}', 'r') as f:
        data = yaml.safe_load(f)
    counts = {}
    exists_counts = {}
    for source in data['sources']:
        t = source['type']
        counts[t] = counts.get(t, 0) + 1
        if source['exists']:
            exists_counts[t] = exists_counts.get(t, 0) + 1
    for t in sorted(counts.keys()):
        print(f\"{t}: {counts[t]} found, {exists_counts.get(t, 0)} accessible\")

    print(\"\\nTotal counts:\")
    print(\"=============\")
    print(f\"Total logs: {len(data['sources'])}\")
    print(f\"Accessible logs: {sum(1 for s in data['sources'] if s.get('exists', False))}\")
except Exception as e:
    print(f\"Error generating summary: {e}\")
" || true
      fi
    else
      log_warn "Output file not found: ${OUTPUT_FILE}"
    fi
  fi

  # Send email notification if enabled
  if [ -n "$NOTIFY_EMAIL" ]; then
    local total_count=0
    local accessible_count=0

    if [[ "$FORMAT" == "json" ]] && command -v jq &> /dev/null; then
      total_count=$(jq -r '.sources | length' "${OUTPUT_FILE}")
      accessible_count=$(jq -r '.sources | map(select(.exists == true)) | length' "${OUTPUT_FILE}")
    elif [[ "$FORMAT" == "yaml" ]] && command -v python3 &> /dev/null; then
      counts=$(python3 -c "
import yaml
with open('${OUTPUT_FILE}', 'r') as f:
    data = yaml.safe_load(f)
print(f\"{len(data['sources'])},{sum(1 for s in data['sources'] if s.get('exists', False))}\")
")
      total_count=$(echo "$counts" | cut -d',' -f1)
      accessible_count=$(echo "$counts" | cut -d',' -f2)
    fi

    local message="Log discovery completed successfully.

Execution time: ${duration} seconds
Total logs found: ${total_count}
Accessible logs: ${accessible_count}

This is an automated message from the log discovery system."

    send_notification "SUCCESS" "$message" "${OUTPUT_FILE}"
  fi
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
      -o|--output)
        OUTPUT_FILE="$2"
        shift 2
        ;;
      -f|--format)
        FORMAT="$2"
        if [[ "$FORMAT" != "json" && "$FORMAT" != "yaml" ]]; then
          log_error "Invalid format: $FORMAT. Must be 'json' or 'yaml'."
          exit 1
        fi
        shift 2
        ;;
      -c|--cron)
        CRON_MODE=true
        shift
        ;;
      -t|--timeout)
        TIMEOUT="$2"
        shift 2
        ;;
      -i|--include)
        INCLUDE_TYPES="$2"
        shift 2
        ;;
      -e|--exclude)
        EXCLUDE_TYPES="$2"
        shift 2
        ;;
      --cache)
        CACHE_FILE="$2"
        shift 2
        ;;
      --validate)
        VALIDATE=true
        shift
        ;;
      --notify)
        NOTIFY_EMAIL="$2"
        shift 2
        ;;
      *)
        log_error "Unknown option: $1"
        show_help
        exit 1
        ;;
    esac
  done
}

# Main function
main() {
  # Parse command-line arguments
  parse_args "$@"

  # Don't output headers in cron mode
  if ! $CRON_MODE; then
    print_header "OpenLiteSpeed/CyberPanel/WordPress Log Discovery"
  fi

  # Check dependencies
  check_dependencies

  # Create directories
  create_directories

  # Verify discovery script
  verify_discovery_script

  # Run discovery
  run_discovery
}

# Run the main function
main "$@"