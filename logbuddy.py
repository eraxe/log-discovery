#!/usr/bin/env python3
"""
LogBuddy - Unified Log Discovery and Monitoring Tool

A comprehensive tool for discovering, configuring, and monitoring logs using
Loki and Promtail.

Usage:
    logbuddy discover [options]    # Discover logs on the system
    logbuddy config [options]      # Configure which logs to monitor
    logbuddy install [options]     # Install Loki/Promtail with Podman
    logbuddy start [options]       # Start monitoring
    logbuddy stop [options]        # Stop monitoring
    logbuddy status [options]      # Check monitoring status
    logbuddy update [options]      # Update Promtail configuration

Author: LogBuddy
Version: 1.0.0
"""

import os
import sys
import argparse
import subprocess
import json
import yaml
from pathlib import Path
import shutil

# Constants
INSTALL_DIR = "/opt/logbuddy"
CONFIG_DIR = "/etc/logbuddy"
DATA_DIR = "/var/lib/logbuddy"
LOG_DIR = "/var/log/logbuddy"

# Default paths
DISCOVERY_OUTPUT = f"{DATA_DIR}/discovered_logs.json"
PROMTAIL_CONFIG = f"{CONFIG_DIR}/promtail-config.yaml"
PROMTAIL_SETTINGS = f"{CONFIG_DIR}/promtail-config-settings.yaml"
LOKI_CONFIG = f"{CONFIG_DIR}/loki-config.yaml"


def ensure_directories():
    """Ensure required directories exist."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)


def run_command(cmd, display=True):
    """Run a command and return its output."""
    try:
        if display:
            print(f"Running: {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")
        print(f"Command output: {e.stdout}")
        print(f"Command error: {e.stderr}")
        sys.exit(1)


def discover_logs(args):
    """Discover logs on the system."""
    ensure_directories()

    # Build command
    cmd = [f"{INSTALL_DIR}/runner.sh", "--output", DISCOVERY_OUTPUT]

    if args.verbose:
        cmd.append("--verbose")

    if args.format:
        cmd.extend(["--format", args.format])

    if args.include:
        cmd.extend(["--include", args.include])

    if args.exclude:
        cmd.extend(["--exclude", args.exclude])

    if args.validate:
        cmd.append("--validate")

    # Run the log discovery script
    run_command(cmd)

    print(f"Log discovery completed. Results saved to {DISCOVERY_OUTPUT}")

    # Summarize results
    if os.path.exists(DISCOVERY_OUTPUT):
        try:
            with open(DISCOVERY_OUTPUT, 'r') as f:
                data = json.load(f)
                total_logs = len(data.get('sources', []))
                existing_logs = len([src for src in data.get('sources', []) if src.get('exists', False)])
                print(f"Found {total_logs} logs, {existing_logs} accessible.")

                # Group by type
                log_types = {}
                for src in data.get('sources', []):
                    log_type = src.get('type', 'unknown')
                    if log_type not in log_types:
                        log_types[log_type] = 0
                    log_types[log_type] += 1

                print("\nLog types found:")
                for log_type, count in log_types.items():
                    print(f"  - {log_type}: {count}")

                print("\nUse 'logbuddy config' to configure which logs to monitor.")
        except Exception as e:
            print(f"Error reading discovery results: {e}")


def configure_logs(args):
    """Configure which logs to monitor."""
    ensure_directories()

    # Check if log discovery has been run
    if not os.path.exists(DISCOVERY_OUTPUT):
        print("No log discovery results found. Please run 'logbuddy discover' first.")
        sys.exit(1)

    # Build command
    cmd = [f"{INSTALL_DIR}/bridges/promtail_conf_gen.py", "--input", DISCOVERY_OUTPUT, "--output", PROMTAIL_SETTINGS]

    # Run the configuration generator
    try:
        subprocess.run(cmd)
    except Exception as e:
        print(f"Error configuring logs: {e}")
        sys.exit(1)

    # Generate Promtail configuration after interactive selection
    update_promtail_config(argparse.Namespace())

    print(f"Configuration saved to {PROMTAIL_SETTINGS}")
    print(f"Promtail configuration generated at {PROMTAIL_CONFIG}")
    print("\nUse 'logbuddy install' to install Loki/Promtail if not already installed.")
    print("Or use 'logbuddy start' to start monitoring if already installed.")


def update_promtail_config(args):
    """Update Promtail configuration based on settings."""
    ensure_directories()

    # Check if log discovery and configuration have been done
    if not os.path.exists(DISCOVERY_OUTPUT):
        print("No log discovery results found. Please run 'logbuddy discover' first.")
        sys.exit(1)

    if not os.path.exists(PROMTAIL_SETTINGS):
        print("No configuration settings found. Please run 'logbuddy config' first.")
        sys.exit(1)

    # Build command
    cmd = [
        f"{INSTALL_DIR}/bridges/promtail.py",
        "--input", DISCOVERY_OUTPUT,
        "--output", PROMTAIL_CONFIG,
        "--config", PROMTAIL_SETTINGS
    ]

    if hasattr(args, 'docker_update') and args.docker_update:
        cmd.append("--docker-update")

    # Run the Promtail configuration generator
    run_command(cmd)

    print(f"Promtail configuration updated at {PROMTAIL_CONFIG}")


def install_monitoring(args):
    """Install Loki/Promtail with Podman."""
    ensure_directories()

    # Copy the installation script to a temporary location
    temp_script = f"{DATA_DIR}/install_loki_promtail.sh"
    shutil.copy(f"{INSTALL_DIR}/misc/podman-loki-promtail.sh", temp_script)
    os.chmod(temp_script, 0o755)

    # Run the installation script
    print("Starting Loki/Promtail installation...")
    print("Please follow the on-screen instructions.")

    try:
        subprocess.run([temp_script], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Installation failed: {e}")
        sys.exit(1)

    print("Installation completed. Use 'logbuddy start' to start monitoring.")


def start_monitoring(args):
    """Start log monitoring."""
    ensure_directories()

    # Check if configuration is available
    if not os.path.exists(PROMTAIL_CONFIG):
        print("Promtail configuration not found. Please run 'logbuddy config' first.")
        sys.exit(1)

    # Use the podman bridge to update and start monitoring
    cmd = [
        f"{INSTALL_DIR}/bridges/podman.sh",
        "--update-container",
        "--engine", args.engine if hasattr(args, 'engine') and args.engine else "podman"
    ]

    if hasattr(args, 'promtail') and args.promtail:
        cmd.extend(["--promtail", args.promtail])

    if hasattr(args, 'loki') and args.loki:
        cmd.extend(["--loki", args.loki])

    if hasattr(args, 'force') and args.force:
        cmd.append("--force")

    if hasattr(args, 'verbose') and args.verbose:
        cmd.append("--verbose")

    # Run the start command
    run_command(cmd)

    print("Monitoring started. Use 'logbuddy status' to check status.")


def stop_monitoring(args):
    """Stop log monitoring."""
    # Use the container engine to stop containers
    engine = args.engine if hasattr(args, 'engine') and args.engine else "podman"
    promtail = args.promtail if hasattr(args, 'promtail') and args.promtail else "promtail"
    loki = args.loki if hasattr(args, 'loki') and args.loki else "loki"

    try:
        # First stop promtail
        print(f"Stopping {promtail} container...")
        subprocess.run([engine, "stop", promtail], check=False)

        # Then stop loki
        print(f"Stopping {loki} container...")
        subprocess.run([engine, "stop", loki], check=False)

        print(f"Monitoring containers stopped")
    except Exception as e:
        print(f"Error stopping monitoring: {e}")
        sys.exit(1)


def check_status(args):
    """Check monitoring status."""
    engine = args.engine if hasattr(args, 'engine') and args.engine else "podman"
    promtail = args.promtail if hasattr(args, 'promtail') and args.promtail else "promtail"
    loki = args.loki if hasattr(args, 'loki') and args.loki else "loki"

    # Check container status
    try:
        print(f"Checking {engine} container status...")

        # Check Promtail
        promtail_result = subprocess.run(
            [engine, "container", "inspect", "--format", "{{.State.Status}}", promtail],
            capture_output=True, text=True
        )

        if promtail_result.returncode == 0:
            print(f"Promtail container: {promtail_result.stdout.strip()}")
        else:
            print(f"Promtail container not found or not running")

        # Check Loki
        loki_result = subprocess.run(
            [engine, "container", "inspect", "--format", "{{.State.Status}}", loki],
            capture_output=True, text=True
        )

        if loki_result.returncode == 0:
            print(f"Loki container: {loki_result.stdout.strip()}")
        else:
            print(f"Loki container not found or not running")

        # If both are running, check Loki API
        if promtail_result.returncode == 0 and loki_result.returncode == 0:
            print("\nChecking Loki API...")
            try:
                # This is just a basic check, in a real implementation you'd want to use the credentials
                api_result = subprocess.run(
                    ["curl", "-s", "http://localhost:3100/ready"],
                    capture_output=True, text=True, timeout=5
                )
                if "ready" in api_result.stdout.lower():
                    print("Loki API is ready and responding")
                else:
                    print(f"Loki API responded but status is unclear: {api_result.stdout.strip()}")
            except Exception as e:
                print(f"Error checking Loki API: {e}")

        # Print some helpful commands
        print("\nUseful commands:")
        print(f"  - Check Promtail logs: {engine} logs {promtail}")
        print(f"  - Check Loki logs: {engine} logs {loki}")
        print(f"  - Restart monitoring: logbuddy start")
        print(f"  - Stop monitoring: logbuddy stop")

    except Exception as e:
        print(f"Error checking status: {e}")
        sys.exit(1)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="LogBuddy - Unified Log Discovery and Monitoring Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Discover command
    discover_parser = subparsers.add_parser("discover", help="Discover logs on the system")
    discover_parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    discover_parser.add_argument("--format", "-f", choices=["json", "yaml"], default="json", help="Output format")
    discover_parser.add_argument("--include", "-i", help="Include only specified log types (comma-separated)")
    discover_parser.add_argument("--exclude", "-e", help="Exclude specified log types (comma-separated)")
    discover_parser.add_argument("--validate", action="store_true", help="Validate log files")
    discover_parser.set_defaults(func=discover_logs)

    # Config command
    config_parser = subparsers.add_parser("config", help="Configure which logs to monitor")
    config_parser.set_defaults(func=configure_logs)

    # Update command
    update_parser = subparsers.add_parser("update", help="Update Promtail configuration")
    update_parser.add_argument("--docker-update", "-d", action="store_true",
                               help="Update Promtail container configuration")
    update_parser.set_defaults(func=update_promtail_config)

    # Install command
    install_parser = subparsers.add_parser("install", help="Install Loki/Promtail with Podman")
    install_parser.set_defaults(func=install_monitoring)

    # Start command
    start_parser = subparsers.add_parser("start", help="Start monitoring")
    start_parser.add_argument("--engine", "-e", help="Container engine (docker/podman)")
    start_parser.add_argument("--promtail", "-p", help="Promtail container name")
    start_parser.add_argument("--loki", "-l", help="Loki container name")
    start_parser.add_argument("--force", "-f", action="store_true", help="Force update")
    start_parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    start_parser.set_defaults(func=start_monitoring)

    # Stop command
    stop_parser = subparsers.add_parser("stop", help="Stop monitoring")
    stop_parser.add_argument("--engine", "-e", help="Container engine (docker/podman)")
    stop_parser.add_argument("--promtail", "-p", help="Promtail container name")
    stop_parser.add_argument("--loki", "-l", help="Loki container name")
    stop_parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    stop_parser.set_defaults(func=stop_monitoring)

    # Status command
    status_parser = subparsers.add_parser("status", help="Check monitoring status")
    status_parser.add_argument("--engine", "-e", help="Container engine (docker/podman)")
    status_parser.add_argument("--promtail", "-p", help="Promtail container name")
    status_parser.add_argument("--loki", "-l", help="Loki container name")
    status_parser.set_defaults(func=check_status)

    # Parse arguments
    args = parser.parse_args()

    # If no command is specified, print help
    if not hasattr(args, 'command') or not args.command:
        parser.print_help()
        sys.exit(1)

    # Run the specified function
    args.func(args)


if __name__ == "__main__":
    main()