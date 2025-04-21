#!/bin/bash
# =====================================================================
# OpenLiteSpeed/CyberPanel/WordPress Log Discovery Runner
# =====================================================================
#
# This script runs the log discovery system and can be used in cron jobs
# or manual invocation.
#
# Usage: ./run_log_discovery.sh [-h|--help] [-v|--verbose] [-o|--output FILE]
#                              [-f|--format FORMAT] [-c|--cron]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISCOVERY_SCRIPT="${SCRIPT_DIR}/log_discovery.py"
OUTPUT_DIR="${SCRIPT_DIR}/output"
DEFAULT_OUTPUT="${OUTPUT_DIR}/discovered_logs.json"

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

# ==============================
# Helper Functions
# ==============================

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

Description:
  This script runs the log discovery system to find logs from OpenLiteSpeed,
  CyberPanel, and WordPress installations by analyzing their configuration
  files rather than just searching for common patterns.
  
  The output is a structured JSON or YAML file that can be used as input
  for configuring Loki/Promtail.
EOF
}

#
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
      *)
        log_error "Unknown option: $1"
        show_help
        exit 1
        ;;
    esac
  done
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
        missing=true
      fi
    done
  fi
  
  if $missing; then
    echo -e "\nPlease install the missing dependencies and try again."
    exit 1
  fi
}

# Create output directory if it doesn't exist
create_directories() {
  mkdir -p "${OUTPUT_DIR}"
}

# Run the log discovery script
run_discovery() {
  local verbose_flag=""
  if $VERBOSE; then
    verbose_flag="--verbose"
  fi
  
  if ! $CRON_MODE; then
    print_header "Running Log Discovery"
    log_info "Output will be written to: ${OUTPUT_FILE}"
    log_info "Format: ${FORMAT}"
  fi
  
  # Ensure the discovery script is executable
  chmod +x "${DISCOVERY_SCRIPT}" 2>/dev/null || true
  
  # Run the discovery script
  python3 "${DISCOVERY_SCRIPT}" ${verbose_flag} --format "${FORMAT}" --output "${OUTPUT_FILE}"
  
  if ! $CRON_MODE; then
    log_info "Log discovery completed successfully!"
    log_info "Results saved to: ${OUTPUT_FILE}"
    
    # Display summary of discovered logs
    if [[ "$FORMAT" == "json" ]]; then
      if command -v jq &> /dev/null; then
        echo ""
        echo "Summary of discovered logs:"
        echo "============================"
        jq '.sources | group_by(.type) | map({type: .[0].type, count: length, existing: map(select(.exists == true)) | length})' "${OUTPUT_FILE}"
      fi
    elif [[ "$FORMAT" == "yaml" ]] && command -v python3 &> /dev/null; then
      echo ""
      echo "Summary of discovered logs:"
      echo "============================"
      python3 -c "
import yaml, sys
with open('${OUTPUT_FILE}', 'r') as f:
    data = yaml.safe_load(f)
counts = {}
exists_counts = {}
for source in data['sources']:
    t = source['type']
    counts[t] = counts.get(t, 0) + 1
    if source['exists']:
        exists_counts[t] = exists_counts.get(t, 0) + 1
for t in counts:
    print(f\"{t}: {counts[t]} found, {exists_counts.get(t, 0)} existing\")
"
    fi
  fi
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
  
  # Run discovery
  run_discovery
}

# Run the main function
main "$@"!/bin/bash
# =====================================================================
# OpenLiteSpeed/CyberPanel/WordPress Log Discovery Runner
# =====================================================================
#
# This script runs the log discovery system and can be used in cron jobs
# or manual invocation.
#
# Usage: ./run_log_discovery.sh [-h|--help] [-v|--verbose] [-o|--output FILE]
#                              [-f|--format FORMAT] [-c|--cron]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISCOVERY_SCRIPT="${SCRIPT_DIR}/log_discovery.py"
OUTPUT_DIR="${SCRIPT_DIR}/output"
DEFAULT_OUTPUT="${OUTPUT_DIR}/discovered_logs.json"

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

# ==============================
# Helper Functions
# ==============================

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

Description:
  This script runs the log discovery system to find logs from OpenLiteSpeed,
  CyberPanel, and WordPress installations by analyzing their configuration
  files rather than just searching for common patterns.
  
  The output is a structured JSON or YAML file that can be used as input
  for configuring Loki/Promtail.
EOF
}

#
