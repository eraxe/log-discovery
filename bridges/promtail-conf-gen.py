#!/usr/bin/env python3
"""
LogBuddy - CLI Promtail Configuration Generator

A command-line tool for generating Promtail configurations based on discovered logs.
Features a text-based tree navigation system for toggling directories and files on/off.

Usage:
    ./promtail-conf-gen.py [--input discovery.json] [--output config.yaml]
                         [--auto-select all|none|recommended]
                         [--include-types type1,type2,...]
                         [--include-services service1,service2,...]
                         [--include-paths path1,path2,...]
                         [--exclude-paths path1,path2,...]
                         [--loki-url URL] [--promtail-port PORT]
                         [--container-engine docker|podman]
                         [--no-interactive]
"""

import os
import re
import sys
import json
import yaml
import glob
import argparse
from typing import Dict, List, Set, Tuple, Optional, Any

# Default paths
DEFAULT_INPUT_PATH = "output/discovered_logs.json"
DEFAULT_OUTPUT_PATH = "config/promtail-config-settings.yaml"

# Default configuration values
DEFAULT_LOKI_URL = "http://loki:3100/loki/api/v1/push"
DEFAULT_PROMTAIL_PORT = 9080
DEFAULT_POSITIONS_FILE = "/var/lib/promtail/positions.yaml"
DEFAULT_CONTAINER_ENGINE = "podman"
DEFAULT_PROMTAIL_CONTAINER = "promtail"
DEFAULT_MAX_LOG_SIZE_MB = 100
DEFAULT_MAX_NAME_LENGTH = 40

# Recommended types and services
RECOMMENDED_TYPES = {"openlitespeed", "wordpress", "php", "mysql", "cyberpanel"}
RECOMMENDED_SERVICES = {"webserver", "wordpress", "database", "script_handler"}


class LogConfig:
    """Class to hold log configuration state."""

    def __init__(self):
        self.discovered_logs = []
        self.selected_logs = set()
        self.selected_types = set()
        self.selected_services = set()
        self.log_types = set()
        self.log_services = set()
        self.include_patterns = []
        self.exclude_patterns = []
        # Directory tree
        self.log_tree = {}
        self.expanded_nodes = set()
        # Configuration settings
        self.loki_url = DEFAULT_LOKI_URL
        self.promtail_port = DEFAULT_PROMTAIL_PORT
        self.positions_file = DEFAULT_POSITIONS_FILE
        self.container_engine = DEFAULT_CONTAINER_ENGINE
        self.promtail_container = DEFAULT_PROMTAIL_CONTAINER
        self.max_log_size_mb = DEFAULT_MAX_LOG_SIZE_MB
        self.shorten_names = True
        self.max_name_length = DEFAULT_MAX_NAME_LENGTH


def load_discovered_logs(file_path: str) -> List[Dict]:
    """Load discovered logs from JSON file."""
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        return data.get('sources', [])
    except Exception as e:
        print(f"Error loading discovered logs: {str(e)}", file=sys.stderr)
        sys.exit(1)


def extract_log_metadata(logs: List[Dict], config: LogConfig) -> None:
    """Extract metadata from logs for categorization."""
    for log in logs:
        # Extract log type
        log_type = log.get('type', '')
        if log_type:
            config.log_types.add(log_type)

        # Extract service
        service = log.get('labels', {}).get('service', '')
        if service:
            config.log_services.add(service)


def build_directory_tree(logs: List[Dict]) -> Dict:
    """Build a tree structure from log paths."""
    tree = {}
    for log in logs:
        path = log.get('path', '')
        if not path:
            continue

        # Skip if log doesn't exist
        if log.get('exists', True) is False:
            continue

        # Split path into components
        components = path.split('/')
        components = [c for c in components if c]  # Remove empty components

        # Build tree
        current = tree
        full_path = ""
        for i, component in enumerate(components):
            full_path = full_path + '/' + component if full_path else '/' + component

            if i == len(components) - 1:
                # This is a leaf (file)
                if '__files__' not in current:
                    current['__files__'] = []
                current['__files__'].append({
                    'path': path,
                    'name': component,
                    'full_path': full_path,
                    'log': log
                })
            else:
                # This is a directory
                if component not in current:
                    current[component] = {}
                current = current[component]

    return tree


def auto_select_logs(selection_type: str, config: LogConfig) -> None:
    """Auto-select logs based on selection type."""
    if selection_type == 'all':
        # Select all logs
        for log in config.discovered_logs:
            path = log.get('path', '')
            if path and log.get('exists', True) is not False:
                config.selected_logs.add(path)

        # Select all types and services
        config.selected_types = config.log_types.copy()
        config.selected_services = config.log_services.copy()

    elif selection_type == 'recommended':
        # Select recommended types
        config.selected_types = RECOMMENDED_TYPES.intersection(config.log_types)

        # Select recommended services
        config.selected_services = RECOMMENDED_SERVICES.intersection(config.log_services)

        # Select logs matching recommended types and services
        for log in config.discovered_logs:
            if log.get('exists', True) is False:
                continue

            path = log.get('path', '')
            if not path:
                continue

            log_type = log.get('type', '')
            service = log.get('labels', {}).get('service', '')

            if (log_type in config.selected_types or
                    service in config.selected_services):
                config.selected_logs.add(path)


def get_input_with_default(prompt: str, default: str = "") -> str:
    """Get user input with a default value."""
    if default:
        value = input(f"{prompt} [{default}]: ").strip()
        return value if value else default
    else:
        return input(f"{prompt}: ").strip()


def interactive_tree_selection(config: LogConfig) -> None:
    """Interactive tree-based selection interface."""
    print("\n==== LogBuddy Promtail Configuration Generator ====\n")

    # First, handle type and service selection
    handle_type_service_selection(config)

    # Then, handle tree-based log selection
    print("\n==== Log Directory Tree Navigation ====")
    print("Navigate the tree and select which logs to monitor\n")

    # Build tree structure if not done already
    if not config.log_tree:
        config.log_tree = build_directory_tree(config.discovered_logs)

    # Start with root node expanded
    config.expanded_nodes.add("/")

    # Run tree navigation
    tree_navigation(config)


def handle_type_service_selection(config: LogConfig) -> None:
    """Handle selection of log types and services."""
    # 1. Select log types
    print("\nAvailable log types:")
    types_list = sorted(config.log_types)
    for i, log_type in enumerate(types_list):
        print(f"  {i + 1}. {log_type}")

    print("\nEnter the numbers of log types to include (comma-separated, or 'all' or 'recommended'):")
    type_input = input("> ").strip()

    if type_input.lower() == 'all':
        config.selected_types = config.log_types.copy()
    elif type_input.lower() == 'recommended':
        config.selected_types = RECOMMENDED_TYPES.intersection(config.log_types)
    elif type_input:
        try:
            indices = [int(idx.strip()) - 1 for idx in type_input.split(',')]
            for idx in indices:
                if 0 <= idx < len(types_list):
                    config.selected_types.add(types_list[idx])
        except ValueError:
            print("Invalid input. Using recommended types.")
            config.selected_types = RECOMMENDED_TYPES.intersection(config.log_types)

    # 2. Select services
    print("\nAvailable services:")
    services_list = sorted(config.log_services)
    for i, service in enumerate(services_list):
        print(f"  {i + 1}. {service}")

    print("\nEnter the numbers of services to include (comma-separated, or 'all' or 'recommended'):")
    service_input = input("> ").strip()

    if service_input.lower() == 'all':
        config.selected_services = config.log_services.copy()
    elif service_input.lower() == 'recommended':
        config.selected_services = RECOMMENDED_SERVICES.intersection(config.log_services)
    elif service_input:
        try:
            indices = [int(idx.strip()) - 1 for idx in service_input.split(',')]
            for idx in indices:
                if 0 <= idx < len(services_list):
                    config.selected_services.add(services_list[idx])
        except ValueError:
            print("Invalid input. Using recommended services.")
            config.selected_services = RECOMMENDED_SERVICES.intersection(config.log_services)

    # 3. Configure additional settings
    print("\nAdditional Settings:")

    # Loki URL
    loki_url = get_input_with_default("Loki URL", config.loki_url)
    config.loki_url = loki_url

    # Promtail port
    port_input = get_input_with_default("Promtail port", str(config.promtail_port))
    try:
        config.promtail_port = int(port_input)
    except ValueError:
        print(f"Invalid port. Using default: {config.promtail_port}")

    # Container engine
    engine = get_input_with_default("Container engine (docker/podman)", config.container_engine).lower()
    if engine in ('docker', 'podman'):
        config.container_engine = engine


def tree_navigation(config: LogConfig) -> None:
    """Interactive tree navigation for log selection."""
    current_path = "/"
    show_path = True

    # Auto-select logs based on type and service
    for log in config.discovered_logs:
        if log.get('exists', True) is False:
            continue

        path = log.get('path', '')
        if not path:
            continue

        log_type = log.get('type', '')
        service = log.get('labels', {}).get('service', '')

        if (log_type in config.selected_types or
                service in config.selected_services):
            config.selected_logs.add(path)

    while True:
        if show_path:
            print_directory_tree(config, current_path)
            show_path = False

        print("\nCommands:")
        print("  e - Expand/collapse directory")
        print("  s - Select/deselect log")
        print("  c - Change directory")
        print("  u - Go up one directory")
        print("  a - Select all logs in current directory")
        print("  d - Deselect all logs in current directory")
        print("  r - Refresh tree view")
        print("  f - Done with selection")

        command = input("\nEnter command: ").strip().lower()

        if command == 'e':
            # Expand/collapse directory
            dir_number = input("Enter directory number to expand/collapse: ").strip()
            try:
                dir_number = int(dir_number)
                path = get_path_by_number(config, current_path, dir_number, is_dir=True)
                if path:
                    if path in config.expanded_nodes:
                        config.expanded_nodes.remove(path)
                    else:
                        config.expanded_nodes.add(path)
                    show_path = True
                else:
                    print("Invalid directory number")
            except ValueError:
                print("Invalid input. Please enter a number.")

        elif command == 's':
            # Select/deselect log
            log_number = input("Enter log number to select/deselect: ").strip()
            try:
                log_number = int(log_number)
                path = get_path_by_number(config, current_path, log_number, is_dir=False)
                if path:
                    if path in config.selected_logs:
                        config.selected_logs.remove(path)
                    else:
                        config.selected_logs.add(path)
                    show_path = True
                else:
                    print("Invalid log number")
            except ValueError:
                print("Invalid input. Please enter a number.")

        elif command == 'c':
            # Change directory
            dir_number = input("Enter directory number to navigate to: ").strip()
            try:
                dir_number = int(dir_number)
                path = get_path_by_number(config, current_path, dir_number, is_dir=True)
                if path:
                    current_path = path
                    config.expanded_nodes.add(path)
                    show_path = True
                else:
                    print("Invalid directory number")
            except ValueError:
                print("Invalid input. Please enter a number.")

        elif command == 'u':
            # Go up one directory
            if current_path == "/":
                print("Already at root directory")
            else:
                parent_path = os.path.dirname(current_path)
                current_path = parent_path if parent_path else "/"
                show_path = True

        elif command == 'a':
            # Select all logs in current directory
            select_all_in_directory(config, current_path)
            show_path = True

        elif command == 'd':
            # Deselect all logs in current directory
            deselect_all_in_directory(config, current_path)
            show_path = True

        elif command == 'r':
            # Refresh view
            show_path = True

        elif command == 'f':
            # Finished with selection
            break

        else:
            print("Unknown command")


def print_directory_tree(config: LogConfig, current_path: str) -> None:
    """Print the directory tree for the current path."""
    # Clear the screen
    os.system('clear' if os.name == 'posix' else 'cls')

    print(f"\nCurrent directory: {current_path}")
    print("=" * 50)

    # Get the subdirectory to render
    subdir = get_subdirectory(config.log_tree, current_path)
    if not subdir:
        print("Directory not found or empty")
        return

    # Print directories first
    dir_num = 1
    dirs = sorted(k for k in subdir.keys() if k != '__files__')
    for key in dirs:
        dir_path = os.path.join(current_path, key).replace("//", "/")
        is_expanded = dir_path in config.expanded_nodes

        # Count selected logs in this directory
        selected_count = count_selected_logs_in_dir(config, dir_path)
        total_count = count_total_logs_in_dir(config, dir_path)

        # Calculate selection ratio
        if total_count > 0:
            selection_indicator = f"[{selected_count}/{total_count}]"
        else:
            selection_indicator = "[empty]"

        # Expanded indicator
        expanded_indicator = "-" if is_expanded else "+"

        print(f"{dir_num}. [{expanded_indicator}] {key}/ {selection_indicator}")

        # If expanded, show subdirectories (only one level for clarity)
        if is_expanded:
            subsubdir = subdir[key]
            for subkey in sorted(k for k in subsubdir.keys() if k != '__files__'):
                subdir_path = os.path.join(dir_path, subkey).replace("//", "/")
                sub_selected = count_selected_logs_in_dir(config, subdir_path)
                sub_total = count_total_logs_in_dir(config, subdir_path)

                if sub_total > 0:
                    sub_indicator = f"[{sub_selected}/{sub_total}]"
                else:
                    sub_indicator = "[empty]"

                print(f"   - {subkey}/ {sub_indicator}")

        dir_num += 1

    # Print files
    if '__files__' in subdir:
        log_num = 1
        for file in sorted(subdir['__files__'], key=lambda x: x['name']):
            file_path = file['path']
            file_name = file['name']

            # Check if selected
            is_selected = file_path in config.selected_logs
            selected_indicator = "X" if is_selected else " "

            # Get log type and service if available
            log_type = file['log'].get('type', '')
            service = file['log'].get('labels', {}).get('service', '')

            info = ""
            if log_type:
                info += f"type={log_type}"
            if service:
                info += f" service={service}" if info else f"service={service}"

            if info:
                info = f" ({info})"

            print(f"{log_num}. [{selected_indicator}] {file_name}{info}")
            log_num += 1


def get_subdirectory(tree: Dict, path: str) -> Dict:
    """Get a subdirectory from the tree structure based on path."""
    if path == "/":
        return tree

    # Split path into components
    components = [c for c in path.strip('/').split('/') if c]

    # Traverse the tree
    current = tree
    for component in components:
        if component in current:
            current = current[component]
        else:
            return None

    return current


def get_path_by_number(config: LogConfig, current_path: str, number: int, is_dir: bool) -> Optional[str]:
    """Get path by its display number."""
    subdir = get_subdirectory(config.log_tree, current_path)
    if not subdir:
        return None

    if is_dir:
        # Get directories
        dirs = sorted(k for k in subdir.keys() if k != '__files__')
        if 1 <= number <= len(dirs):
            key = dirs[number - 1]
            return os.path.join(current_path, key).replace("//", "/")
    else:
        # Get files
        if '__files__' in subdir:
            files = sorted(subdir['__files__'], key=lambda x: x['name'])
            if 1 <= number <= len(files):
                return files[number - 1]['path']

    return None


def count_selected_logs_in_dir(config: LogConfig, dir_path: str) -> int:
    """Count selected logs in a directory and its subdirectories."""
    count = 0
    for log_path in config.selected_logs:
        if log_path.startswith(dir_path):
            count += 1
    return count


def count_total_logs_in_dir(config: LogConfig, dir_path: str) -> int:
    """Count total logs in a directory and its subdirectories."""
    count = 0
    for log in config.discovered_logs:
        if log.get('exists', True) is False:
            continue

        path = log.get('path', '')
        if path and path.startswith(dir_path):
            count += 1
    return count


def select_all_in_directory(config: LogConfig, dir_path: str) -> None:
    """Select all logs in a directory and its subdirectories."""
    for log in config.discovered_logs:
        if log.get('exists', True) is False:
            continue

        path = log.get('path', '')
        if path and path.startswith(dir_path):
            config.selected_logs.add(path)


def deselect_all_in_directory(config: LogConfig, dir_path: str) -> None:
    """Deselect all logs in a directory and its subdirectories."""
    to_remove = set()
    for log_path in config.selected_logs:
        if log_path.startswith(dir_path):
            to_remove.add(log_path)

    config.selected_logs -= to_remove


def generate_config(config: LogConfig) -> Dict:
    """Generate configuration based on selections."""
    # Basic configuration
    output_config = {
        'loki_url': config.loki_url,
        'promtail_port': config.promtail_port,
        'positions_file': config.positions_file,
        'promtail_container': config.promtail_container,
        'docker_command': config.container_engine,
        'max_log_size_mb': config.max_log_size_mb,
        'shorten_names': config.shorten_names,
        'max_name_length': config.max_name_length
    }

    # Include/exclude by type
    if config.selected_types:
        output_config['include_types'] = list(config.selected_types)

    # Include/exclude by service
    if config.selected_services:
        output_config['include_services'] = list(config.selected_services)

    # Add specifically selected log paths (patterns)
    selected_paths = list(config.selected_logs)
    if selected_paths:
        # Convert exact paths to patterns
        include_patterns = []
        for path in selected_paths:
            # If it's a directory, include all logs under it
            if not path.endswith('.log') and os.path.isdir(path):
                include_patterns.append(f'{path}/.*\\.log$')
            else:
                # Escape special regex characters
                escaped_path = re.escape(path)
                include_patterns.append(escaped_path)

        output_config['include_patterns'] = include_patterns

    # Add additional patterns from command line
    if config.include_patterns:
        if 'include_patterns' not in output_config:
            output_config['include_patterns'] = []
        output_config['include_patterns'].extend(config.include_patterns)

    # Default exclude patterns
    output_config['exclude_patterns'] = [
        '\\.cache$',
        '/tmp/',
        'debug_backup',
        '\\.(gz|zip|bz2)$'
    ]

    # Add additional exclude patterns
    if config.exclude_patterns:
        output_config['exclude_patterns'].extend(config.exclude_patterns)

    # Add log format configurations
    output_config['log_formats'] = {
        'openlitespeed': {
            'regex': '^(?P<timestamp>\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}.\\d+) \\[(?P<level>[^\\]]+)\\] (?P<message>.*)$',
            'timestamp_field': 'timestamp',
            'timestamp_format': '2006-01-02 15:04:05.000'
        },
        'wordpress': {
            'regex': '^\\[(?P<timestamp>[^\\]]+)\\] (?P<level>\\w+): (?P<message>.*)$',
            'timestamp_field': 'timestamp',
            'timestamp_format': '02-Jan-2006 15:04:05'
        },
        'php': {
            'regex': '^\\[(?P<timestamp>\\d{2}-[A-Z][a-z]{2}-\\d{4} \\d{2}:\\d{2}:\\d{2})\\] (?P<message>.*)$',
            'timestamp_field': 'timestamp',
            'timestamp_format': '02-Jan-2006 15:04:05'
        },
        'mysql': {
            'regex': '^(?P<timestamp>\\d{6} \\d{2}:\\d{2}:\\d{2}) (?P<message>.*)$',
            'timestamp_field': 'timestamp',
            'timestamp_format': '060102 15:04:05'
        }
    }

    # Add basic pipeline stages
    output_config['pipeline_stages'] = {
        'openlitespeed': [
            {
                'regex': {
                    'expression': '^(?P<timestamp>\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}.\\d+) \\[(?P<level>[^\\]]+)\\] (?P<message>.*)$'
                }
            },
            {
                'labels': {
                    'level': ''
                }
            },
            {
                'timestamp': {
                    'source': 'timestamp',
                    'format': '2006-01-02 15:04:05.000'
                }
            }
        ],
        'wordpress': [
            {
                'regex': {
                    'expression': '^\\[(?P<timestamp>[^\\]]+)\\] (?P<level>\\w+): (?P<message>.*)$'
                }
            },
            {
                'labels': {
                    'level': ''
                }
            },
            {
                'timestamp': {
                    'source': 'timestamp',
                    'format': '02-Jan-2006 15:04:05'
                }
            }
        ]
    }

    return output_config


def save_config(config: Dict, file_path: str) -> bool:
    """Save configuration to YAML file."""
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        with open(file_path, 'w') as f:
            yaml.safe_dump(config, f, default_flow_style=False)
        return True
    except Exception as e:
        print(f"Error saving configuration: {str(e)}", file=sys.stderr)
        return False


def print_config_summary(config_data: Dict, selected_logs: int, total_logs: int) -> None:
    """Print a summary of the generated configuration."""
    print("\n==== Configuration Summary ====")
    print(f"Selected logs: {selected_logs}/{total_logs}")

    if 'include_types' in config_data:
        print(f"Log types: {', '.join(config_data['include_types'])}")

    if 'include_services' in config_data:
        print(f"Services: {', '.join(config_data['include_services'])}")

    print(f"Loki URL: {config_data['loki_url']}")
    print(f"Promtail port: {config_data['promtail_port']}")
    print(f"Container engine: {config_data['docker_command']}")

    print(f"\nConfiguration saved to: {args.output}")
    print("Use 'logbuddy start' to apply this configuration and start monitoring.")


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="LogBuddy - CLI Promtail Configuration Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument("--input", "-i", default=DEFAULT_INPUT_PATH,
                        help=f"Input JSON file from log discovery (default: {DEFAULT_INPUT_PATH})")
    parser.add_argument("--output", "-o", default=DEFAULT_OUTPUT_PATH,
                        help=f"Output YAML file for configuration (default: {DEFAULT_OUTPUT_PATH})")
    parser.add_argument("--auto-select", "-a", choices=["all", "none", "recommended"],
                        help="Automatically select logs (all, none, or recommended)")
    parser.add_argument("--include-types", "-t",
                        help="Include specific log types (comma-separated)")
    parser.add_argument("--include-services", "-s",
                        help="Include specific services (comma-separated)")
    parser.add_argument("--include-paths", "-p",
                        help="Include specific path patterns (comma-separated)")
    parser.add_argument("--exclude-paths", "-e",
                        help="Exclude specific path patterns (comma-separated)")
    parser.add_argument("--loki-url", "-l", default=DEFAULT_LOKI_URL,
                        help=f"Loki URL (default: {DEFAULT_LOKI_URL})")
    parser.add_argument("--promtail-port", "-P", type=int, default=DEFAULT_PROMTAIL_PORT,
                        help=f"Promtail port (default: {DEFAULT_PROMTAIL_PORT})")
    parser.add_argument("--container-engine", "-c", choices=["docker", "podman"],
                        default=DEFAULT_CONTAINER_ENGINE,
                        help=f"Container engine (default: {DEFAULT_CONTAINER_ENGINE})")
    parser.add_argument("--no-interactive", "-n", action="store_true",
                        help="Disable interactive mode (use auto-select or manual options)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output")

    return parser.parse_args()


def main():
    """Main entry point."""
    global args
    args = parse_args()

    # Initialize configuration
    config = LogConfig()
    config.loki_url = args.loki_url
    config.promtail_port = args.promtail_port
    config.container_engine = args.container_engine

    # Parse include/exclude patterns
    if args.include_paths:
        config.include_patterns = [p.strip() for p in args.include_paths.split(',')]

    if args.exclude_paths:
        config.exclude_patterns = [p.strip() for p in args.exclude_paths.split(',')]

    # Check if input file exists
    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}")
        print("Please run 'logbuddy discover' first to generate log discovery output.")
        sys.exit(1)

    # Load logs
    print(f"Loading logs from {args.input}...")
    config.discovered_logs = load_discovered_logs(args.input)
    print(f"Loaded {len(config.discovered_logs)} logs")

    # Extract metadata
    extract_log_metadata(config.discovered_logs, config)

    # Build directory tree
    config.log_tree = build_directory_tree(config.discovered_logs)

    # Handle log selection
    if not args.no_interactive and not args.auto_select and not args.include_types and not args.include_services:
        # Interactive tree-based mode
        interactive_tree_selection(config)
    else:
        # Non-interactive mode
        # Parse type and service includes
        if args.include_types:
            config.selected_types = set(t.strip() for t in args.include_types.split(','))

        if args.include_services:
            config.selected_services = set(s.strip() for s in args.include_services.split(','))

        # Auto-select if specified
        if args.auto_select:
            auto_select_logs(args.auto_select, config)
        elif not config.selected_types and not config.selected_services and not config.include_patterns:
            # If nothing specified, use recommended settings
            print("No selection criteria specified. Using recommended settings.")
            auto_select_logs('recommended', config)

        # Select logs based on types and services if no specific paths were provided
        if not config.include_patterns:
            for log in config.discovered_logs:
                if log.get('exists', True) is False:
                    continue

                path = log.get('path', '')
                if not path:
                    continue

                log_type = log.get('type', '')
                service = log.get('labels', {}).get('service', '')

                if (log_type in config.selected_types or
                        service in config.selected_services):
                    config.selected_logs.add(path)

    # Generate and save configuration
    output_config = generate_config(config)

    if save_config(output_config, args.output):
        print(f"Configuration saved to {args.output}")

        # Print summary
        if args.verbose:
            print_config_summary(
                output_config,
                len(config.selected_logs),
                len(config.discovered_logs)
            )
    else:
        print("Failed to save configuration", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()