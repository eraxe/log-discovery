#!/usr/bin/env python3
"""
Promtail Configuration Generator

This script processes the output from log_discovery.py and generates Promtail
configuration for Loki log aggregation. It provides filtering capabilities
based on a configuration file to include/exclude specific log types.

Usage:
    ./promtail_conf_gen.py --input /path/to/discovered_logs.json
                                   --output /path/to/promtail-config.yaml
                                   --config /path/to/config.yaml
                                   [--docker-update]

Author: Claude
Version: 1.0.0
Created: April 21, 2025
"""

import os
import re
import sys
import json
import yaml
import uuid
import hashlib
import argparse
import subprocess
from pathlib import Path
from datetime import datetime


def sanitize_name(name, max_length=50):
    """Create a sanitized, shortened name for log job identifiers.

    Args:
        name: Original name
        max_length: Maximum length for the name

    Returns:
        str: Sanitized name
    """
    # Remove special characters
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name)

    # If name is too long, truncate it and add a hash suffix
    if len(sanitized) > max_length:
        # Keep the first part and add a hash of the full name to ensure uniqueness
        hash_suffix = hashlib.md5(name.encode()).hexdigest()[:8]
        prefix_length = max_length - 9  # 8 for hash, 1 for underscore
        sanitized = f"{sanitized[:prefix_length]}_{hash_suffix}"

    return sanitized


def load_json_file(file_path):
    """Load a JSON file and return its content.

    Args:
        file_path: Path to the JSON file

    Returns:
        dict: JSON content
    """
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading JSON file: {str(e)}", file=sys.stderr)
        sys.exit(1)


def load_config_file(file_path):
    """Load a YAML configuration file.

    Args:
        file_path: Path to the YAML file

    Returns:
        dict: Configuration
    """
    try:
        with open(file_path, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading config file: {str(e)}", file=sys.stderr)
        sys.exit(1)


def filter_logs(discovered_logs, config):
    """Filter logs based on configuration.

    Args:
        discovered_logs: List of discovered log sources
        config: Configuration dictionary

    Returns:
        list: Filtered logs
    """
    filtered_logs = []

    # Get filter parameters from config
    include_types = config.get('include_types', [])
    exclude_types = config.get('exclude_types', [])
    include_services = config.get('include_services', [])
    exclude_services = config.get('exclude_services', [])
    include_patterns = config.get('include_patterns', [])
    exclude_patterns = config.get('exclude_patterns', [])

    # Convert string patterns to compiled regex patterns
    include_regex = [re.compile(pattern) for pattern in include_patterns]
    exclude_regex = [re.compile(pattern) for pattern in exclude_patterns]

    for log in discovered_logs:
        # Skip if log doesn't exist
        if 'exists' in log and not log['exists']:
            continue

        # Check type filters
        log_type = log.get('type', '')
        if include_types and log_type not in include_types:
            continue
        if exclude_types and log_type in exclude_types:
            continue

        # Check service filters
        log_service = log.get('labels', {}).get('service', '')
        if include_services and log_service not in include_services:
            continue
        if exclude_services and log_service in exclude_services:
            continue

        # Check path pattern filters
        log_path = log.get('path', '')

        # Skip if exclude pattern matches
        if any(pattern.search(log_path) for pattern in exclude_regex):
            continue

        # Skip if include patterns exist and none match
        if include_regex and not any(pattern.search(log_path) for pattern in include_regex):
            continue

        # Check size limits if configured
        max_size = config.get('max_log_size_mb', 0)
        if max_size > 0 and log.get('size', 0) > max_size * 1024 * 1024:
            continue

        # Apply name shortening if configured
        if config.get('shorten_names', True) and 'name' in log:
            log['original_name'] = log['name']
            log['name'] = sanitize_name(log['name'], config.get('max_name_length', 50))

        filtered_logs.append(log)

    return filtered_logs


def generate_promtail_config(filtered_logs, config):
    """Generate Promtail configuration YAML.

    Args:
        filtered_logs: List of filtered log sources
        config: Configuration dictionary

    Returns:
        dict: Promtail configuration
    """
    # Base Promtail configuration
    promtail_config = {
        'server': {
            'http_listen_port': config.get('promtail_port', 9080),
            'grpc_listen_port': 0
        },
        'positions': {
            'filename': config.get('positions_file', '/var/lib/promtail/positions.yaml')
        },
        'clients': [{
            'url': config.get('loki_url', 'http://loki:3100/loki/api/v1/push')
        }],
        'scrape_configs': []
    }

    # Group logs by type for more organized scrape configs
    logs_by_type = {}
    for log in filtered_logs:
        log_type = log.get('type', 'unknown')
        if log_type not in logs_by_type:
            logs_by_type[log_type] = []
        logs_by_type[log_type].append(log)

    # Add job scrape configs for each log type
    for log_type, logs in logs_by_type.items():
        scrape_config = {
            'job_name': f'{log_type}_logs',
            'static_configs': [],
            'pipeline_stages': config.get('pipeline_stages', {}).get(log_type, [])
        }

        # Add logging format stage if configured
        log_format = config.get('log_formats', {}).get(log_type)
        if log_format:
            if 'regex' in log_format:
                scrape_config['pipeline_stages'].insert(0, {
                    'regex': {
                        'expression': log_format['regex']
                    }
                })
            if 'timestamp' in log_format:
                scrape_config['pipeline_stages'].insert(1, {
                    'timestamp': {
                        'source': log_format.get('timestamp_field', 'timestamp'),
                        'format': log_format.get('timestamp_format', 'RFC3339')
                    }
                })

        # Group logs by similar labels to reduce static_configs
        label_groups = {}
        for log in logs:
            # Create a label set key (frozen set of label tuples)
            label_set = frozenset(sorted(log.get('labels', {}).items()))

            # Group logs by label set
            if label_set not in label_groups:
                label_groups[label_set] = []
            label_groups[label_set].append(log)

        # Add static config for each label group
        for label_set, group_logs in label_groups.items():
            # Convert to dict for the static config
            labels = dict(label_set)

            # Add job and type labels
            labels['job'] = f'{log_type}_logs'
            labels['type'] = log_type

            # Add log paths
            targets = []
            for log in group_logs:
                target_labels = {'__path__': log['path']}

                # Add instance-specific labels
                for label_key, label_value in labels.items():
                    target_labels[f'__meta_{label_key}'] = label_value

                if 'name' in log:
                    target_labels['name'] = log['name']

                targets.append(target_labels)

            static_config = {
                'labels': labels,
                'targets': targets
            }

            scrape_config['static_configs'].append(static_config)

        # Add scrape config to main configuration
        promtail_config['scrape_configs'].append(scrape_config)

    return promtail_config


def update_docker_config(output_file, config):
    """Update Promtail configuration in Docker container.

    Args:
        output_file: Path to generated Promtail config
        config: Configuration dictionary

    Returns:
        bool: Success status
    """
    container_name = config.get('promtail_container', 'promtail')
    docker_command = config.get('docker_command', 'docker')

    print(f"Updating Promtail configuration in container '{container_name}'...")

    try:
        # Check if container exists
        check_cmd = [docker_command, "container", "inspect", container_name]
        result = subprocess.run(check_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if result.returncode != 0:
            print(f"Container '{container_name}' not found", file=sys.stderr)
            return False

        # Copy config file to container
        copy_cmd = [docker_command, "cp", output_file, f"{container_name}:/etc/promtail/config.yml"]
        copy_result = subprocess.run(copy_cmd)

        if copy_result.returncode != 0:
            print(f"Failed to copy config to container", file=sys.stderr)
            return False

        # Restart container
        restart_cmd = [docker_command, "restart", container_name]
        restart_result = subprocess.run(restart_cmd)

        if restart_result.returncode != 0:
            print(f"Failed to restart container", file=sys.stderr)
            return False

        print(f"Successfully updated Promtail configuration in container '{container_name}'")
        return True

    except Exception as e:
        print(f"Error updating Docker configuration: {str(e)}", file=sys.stderr)
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Generate Promtail configuration from log discovery output")
    parser.add_argument("--input", "-i", required=True, help="Input JSON file from log discovery")
    parser.add_argument("--output", "-o", required=True, help="Output YAML file for Promtail config")
    parser.add_argument("--config", "-c", required=True, help="Configuration YAML file")
    parser.add_argument("--docker-update", "-d", action="store_true",
                        help="Update Promtail container configuration")

    args = parser.parse_args()

    print(f"Loading input file: {args.input}")
    discovery_data = load_json_file(args.input)

    print(f"Loading configuration file: {args.config}")
    config = load_config_file(args.config)

    # Extract log sources from discovery data
    logs = discovery_data.get('sources', [])
    print(f"Found {len(logs)} log sources in discovery data")

    # Filter logs based on configuration
    filtered_logs = filter_logs(logs, config)
    print(f"Filtered to {len(filtered_logs)} log sources")

    # Generate Promtail configuration
    promtail_config = generate_promtail_config(filtered_logs, config)

    # Add metadata
    promtail_config['metadata'] = {
        'generated_at': datetime.now().isoformat(),
        'source': args.input,
        'filtered_logs': len(filtered_logs),
        'total_logs': len(logs)
    }

    # Write Promtail configuration
    print(f"Writing Promtail configuration to: {args.output}")
    try:
        # Create output directory if it doesn't exist
        output_dir = os.path.dirname(args.output)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        with open(args.output, 'w') as f:
            yaml.safe_dump(promtail_config, f, default_flow_style=False)

        print(f"Successfully wrote Promtail configuration")

        # Update Docker container if requested
        if args.docker_update:
            update_docker_config(args.output, config)

    except Exception as e:
        print(f"Error writing output file: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()