#!/usr/bin/env python3
"""
LogBuddy - Unified Log Discovery and Monitoring Tool

A comprehensive tool for discovering, configuring, and monitoring logs using
various backends like Loki/Promtail, Elasticsearch, and more.

Usage:
    logbuddy init [options]        # Run first-time setup wizard
    logbuddy discover [options]    # Discover logs on the system
    logbuddy config [options]      # Configure which logs to monitor
    logbuddy install [options]     # Install monitoring backend
    logbuddy start [options]       # Start monitoring
    logbuddy stop [options]        # Stop monitoring
    logbuddy status [options]      # Check monitoring status
    logbuddy update [options]      # Update monitoring configuration
    logbuddy settings [options]    # View or modify settings

Author: LogBuddy
Version: 1.1.0
"""

import os
import sys
import argparse
import subprocess
import json
import yaml
import shutil
import time
import re
import curses
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
import logging
import configparser
import getpass
from datetime import datetime

# Constants
INSTALL_DIR = "/opt/logbuddy"
CONFIG_DIR = "/etc/logbuddy"
DATA_DIR = "/var/lib/logbuddy"
LOG_DIR = "/var/log/logbuddy"

# Default paths
DISCOVERY_OUTPUT = f"{DATA_DIR}/discovered_logs.json"
DEFAULT_CONFIG = f"{CONFIG_DIR}/config.json"
PROMTAIL_CONFIG = f"{CONFIG_DIR}/promtail-config.yaml"
PROMTAIL_SETTINGS = f"{CONFIG_DIR}/promtail-config-settings.yaml"
LOKI_CONFIG = f"{CONFIG_DIR}/loki-config.yaml"

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f"{LOG_DIR}/logbuddy.log", mode='a'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('logbuddy')

# Default configuration
DEFAULT_SETTINGS = {
    "discovery": {
        "enabled": True,
        "interval": "daily",
        "include_types": [],
        "exclude_types": [],
        "validate_logs": True,
        "timeout": 300
    },
    "monitoring": {
        "backend": "loki-promtail",  # Can be loki-promtail, elasticsearch, etc.
        "container_engine": "podman",  # or docker
        "promtail_container": "promtail",
        "loki_container": "loki",
        "auto_start": True,
        "port": 3100,
        "credentials": {
            "username": "admin",
            "password": ""  # Will be generated during setup
        }
    },
    "output": {
        "format": "json",
        "path": DISCOVERY_OUTPUT,
        "notify_email": ""
    },
    "ui": {
        "skip_tree_view": False,
        "auto_select_recommended": True,
        "theme": "default"
    },
    "system": {
        "first_run": True,
        "setup_completed": False,
        "version": "1.1.0",
        "last_discovery": None
    }
}


def ensure_directories():
    """Ensure required directories exist."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(DISCOVERY_OUTPUT), exist_ok=True)


def load_settings():
    """Load settings from config file or return defaults if not found."""
    ensure_directories()

    if os.path.exists(DEFAULT_CONFIG):
        try:
            with open(DEFAULT_CONFIG, 'r') as f:
                settings = json.load(f)
                # Merge with defaults to ensure all keys exist
                merged_settings = DEFAULT_SETTINGS.copy()
                deep_update(merged_settings, settings)
                return merged_settings
        except Exception as e:
            logger.error(f"Error loading settings: {e}")
            return DEFAULT_SETTINGS
    else:
        return DEFAULT_SETTINGS


def save_settings(settings):
    """Save settings to config file."""
    ensure_directories()

    try:
        with open(DEFAULT_CONFIG, 'w') as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        return False


def deep_update(d, u):
    """Recursively update nested dictionary."""
    for k, v in u.items():
        if isinstance(v, dict) and k in d and isinstance(d[k], dict):
            deep_update(d[k], v)
        else:
            d[k] = v


def run_command(cmd, display=True, check=True, capture_output=True):
    """Run a command and return its output."""
    try:
        if display:
            logger.info(f"Running: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True,
            check=check
        )
        return result
    except subprocess.CalledProcessError as e:
        logger.error(f"Error executing command: {e}")
        logger.error(f"Command output: {e.stdout if hasattr(e, 'stdout') else ''}")
        logger.error(f"Command error: {e.stderr if hasattr(e, 'stderr') else ''}")
        if check:
            sys.exit(1)
        return e


def generate_password(length=12):
    """Generate a secure random password."""
    import random
    import string
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choice(chars) for _ in range(length))


def run_log_discovery(args, settings):
    """Run log discovery directly without using runner.sh."""
    from log_discovery import LogDiscoverer, timeout_handler

    try:
        # Get discovery settings
        include_types = args.include or settings["discovery"]["include_types"]
        exclude_types = args.exclude or settings["discovery"]["exclude_types"]
        timeout = args.timeout or settings["discovery"]["timeout"]
        validate = args.validate or settings["discovery"]["validate_logs"]
        output_format = args.format or settings["output"]["format"]
        output_file = args.output or settings["output"]["path"]

        include_types = include_types if isinstance(include_types, list) else include_types.split(
            ',') if include_types else None
        exclude_types = exclude_types if isinstance(exclude_types, list) else exclude_types.split(
            ',') if exclude_types else None

        # Create discoverer instance
        discoverer = LogDiscoverer(
            verbose=args.verbose,
            include_types=include_types,
            exclude_types=exclude_types,
            cache_file=f"{DATA_DIR}/cache/discovery_cache.json",
            timeout=timeout
        )

        # Run discovery
        logger.info("Starting log discovery...")
        start_time = time.time()
        results = discoverer.discover_all()

        # Add runtime info
        results["metadata"]["discovery_time_seconds"] = round(time.time() - start_time, 2)

        # Validate logs if requested
        if validate:
            logger.info("Validating log files...")
            for source in results["sources"]:
                if source["exists"] and os.path.exists(source["path"]):
                    source["readable"] = os.access(source["path"], os.R_OK)
                else:
                    source["readable"] = False

        # Save results
        os.makedirs(os.path.dirname(output_file), exist_ok=True)

        if output_format == "json":
            with open(output_file, 'w') as f:
                json.dump(results, f, indent=2)
        elif output_format == "yaml":
            with open(output_file, 'w') as f:
                yaml.dump(results, f, default_flow_style=False)

        # Update settings with discovery info
        settings["system"]["last_discovery"] = datetime.now().isoformat()
        save_settings(settings)

        logger.info(f"Log discovery completed in {results['metadata']['discovery_time_seconds']} seconds")
        return results

    except Exception as e:
        logger.error(f"Error during log discovery: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)


def discover_logs(args):
    """Discover logs on the system."""
    ensure_directories()
    settings = load_settings()

    # Legacy mode: use runner.sh if needed
    if args.legacy:
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
    else:
        # Run discovery directly
        results = run_log_discovery(args, settings)

    print(f"Log discovery completed. Results saved to {DISCOVERY_OUTPUT}")

    # Summarize results
    if os.path.exists(DISCOVERY_OUTPUT):
        try:
            with open(DISCOVERY_OUTPUT, 'r') as f:
                data = json.load(f)
                total_logs = len(data.get('sources', []))
                existing_logs = len([src for src in data.get('sources', []) if src.get('exists', False)])

                if args.validate:
                    readable_logs = len([src for src in data.get('sources', []) if src.get('readable', False)])
                    print(f"Found {total_logs} logs, {existing_logs} accessible, {readable_logs} readable.")
                else:
                    print(f"Found {total_logs} logs, {existing_logs} accessible.")

                # Group by type
                log_types = {}
                for src in data.get('sources', []):
                    if src.get('exists', False):
                        log_type = src.get('type', 'unknown')
                        if log_type not in log_types:
                            log_types[log_type] = 0
                        log_types[log_type] += 1

                print("\nLog types found:")
                for log_type, count in log_types.items():
                    print(f"  - {log_type}: {count}")

                # If this is the first run after setup, offer to go to configuration
                if settings["system"]["setup_completed"] and settings["system"]["first_run"]:
                    settings["system"]["first_run"] = False
                    save_settings(settings)

                    print("\nThis is your first log discovery after setup.")
                    if input("Would you like to configure which logs to monitor? [y/N] ").lower() == 'y':
                        configure_logs(args)
                        return

                print("\nUse 'logbuddy config' to configure which logs to monitor.")
        except Exception as e:
            print(f"Error reading discovery results: {e}")


def configure_logs(args):
    """Configure which logs to monitor."""
    ensure_directories()
    settings = load_settings()

    # Check if log discovery has been run
    if not os.path.exists(DISCOVERY_OUTPUT):
        print("No log discovery results found. Running discovery first...")
        discover_logs(argparse.Namespace(
            verbose=args.verbose if hasattr(args, 'verbose') else False,
            format="json",
            include=None,
            exclude=None,
            validate=True,
            legacy=False,
            output=DISCOVERY_OUTPUT,
            timeout=None
        ))

    # Check if we should skip tree view
    if settings["ui"]["skip_tree_view"] and not args.force_tree_view:
        print("Skipping tree view and using recommended settings.")

        # Build command for non-interactive mode
        cmd = [
            f"{INSTALL_DIR}/bridges/promtail_conf_gen.py",
            "--input", DISCOVERY_OUTPUT,
            "--output", PROMTAIL_SETTINGS,
            "--auto-select", "recommended",
            "--non-interactive"
        ]

        run_command(cmd)

        # Generate Promtail configuration
        update_monitoring_config(argparse.Namespace(docker_update=False))

        print(f"Configuration saved with recommended settings to {PROMTAIL_SETTINGS}")
        print(f"Monitoring configuration generated at {PROMTAIL_CONFIG}")

        if not settings["system"]["setup_completed"]:
            print("\nSetup is almost complete!")
            print("Use 'logbuddy install' to install the monitoring backend.")
            print("Or use 'logbuddy start' to start monitoring if already installed.")

        return

    # Build command for interactive tree view
    cmd = [
        f"{INSTALL_DIR}/bridges/promtail_conf_gen.py",
        "--input", DISCOVERY_OUTPUT,
        "--output", PROMTAIL_SETTINGS
    ]

    if hasattr(args, 'auto_select') and args.auto_select:
        cmd.extend(["--auto-select", args.auto_select])

    # Run the configuration generator
    try:
        subprocess.run(cmd)
    except Exception as e:
        print(f"Error configuring logs: {e}")
        sys.exit(1)

    # Generate Promtail configuration after interactive selection
    update_monitoring_config(argparse.Namespace(docker_update=False))

    print(f"Configuration saved to {PROMTAIL_SETTINGS}")
    print(f"Monitoring configuration generated at {PROMTAIL_CONFIG}")

    if not settings["system"]["setup_completed"]:
        print("\nSetup is almost complete!")
        print("Use 'logbuddy install' to install the monitoring backend.")
        print("Or use 'logbuddy start' to start monitoring if already installed.")
    else:
        print("\nUse 'logbuddy start' to start monitoring with your new configuration.")


def update_monitoring_config(args):
    """Update monitoring configuration based on settings."""
    ensure_directories()
    settings = load_settings()

    # Check if log discovery and configuration have been done
    if not os.path.exists(DISCOVERY_OUTPUT):
        print("No log discovery results found. Please run 'logbuddy discover' first.")
        sys.exit(1)

    if not os.path.exists(PROMTAIL_SETTINGS):
        print("No configuration settings found. Please run 'logbuddy config' first.")
        sys.exit(1)

    # Pick appropriate bridge based on monitoring backend
    if settings["monitoring"]["backend"] == "loki-promtail":
        # Build command
        cmd = [
            f"{INSTALL_DIR}/bridges/promtail.py",
            "--input", DISCOVERY_OUTPUT,
            "--output", PROMTAIL_CONFIG,
            "--config", PROMTAIL_SETTINGS
        ]

        if args.docker_update:
            cmd.append("--docker-update")

        # Run the configuration generator
        run_command(cmd)

        print(f"Promtail configuration updated at {PROMTAIL_CONFIG}")
    else:
        print(f"Configuration update for backend '{settings['monitoring']['backend']}' not yet implemented")
        # Future: Add support for other backends


def install_monitoring(args):
    """Install monitoring backend based on settings."""
    ensure_directories()
    settings = load_settings()

    backend = args.backend if hasattr(args, 'backend') and args.backend else settings["monitoring"]["backend"]

    if backend == "loki-promtail":
        # Copy the installation script to a temporary location
        temp_script = f"{DATA_DIR}/install_loki_promtail.sh"
        shutil.copy(f"{INSTALL_DIR}/misc/podman-loki-promtail.sh", temp_script)
        os.chmod(temp_script, 0o755)

        # Generate environment variables for the script
        env = os.environ.copy()
        env["LOGBUDDY_ENGINE"] = settings["monitoring"]["container_engine"]
        env["LOGBUDDY_PROMTAIL"] = settings["monitoring"]["promtail_container"]
        env["LOGBUDDY_LOKI"] = settings["monitoring"]["loki_container"]
        env["LOGBUDDY_PORT"] = str(settings["monitoring"]["port"])

        # Generate credentials if not present
        if not settings["monitoring"]["credentials"]["password"]:
            settings["monitoring"]["credentials"]["password"] = generate_password()
            save_settings(settings)

        env["LOGBUDDY_USERNAME"] = settings["monitoring"]["credentials"]["username"]
        env["LOGBUDDY_PASSWORD"] = settings["monitoring"]["credentials"]["password"]

        # Run the installation script
        print("Starting Loki/Promtail installation...")
        print("Please follow the on-screen instructions.")

        try:
            subprocess.run([temp_script], env=env, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Installation failed: {e}")
            sys.exit(1)

        print("Installation completed. Use 'logbuddy start' to start monitoring.")
    else:
        print(f"Installation of backend '{backend}' not yet implemented")
        # Future: Add support for other backends


def start_monitoring(args):
    """Start log monitoring using the selected backend."""
    ensure_directories()
    settings = load_settings()

    # Check if configuration is available
    if not os.path.exists(PROMTAIL_CONFIG) and settings["monitoring"]["backend"] == "loki-promtail":
        print("Monitoring configuration not found. Running auto-configuration...")
        update_monitoring_config(argparse.Namespace(docker_update=False))

    # Get backend settings
    backend = settings["monitoring"]["backend"]

    if backend == "loki-promtail":
        # Get container settings
        engine = args.engine if hasattr(args, 'engine') and args.engine else settings["monitoring"]["container_engine"]
        promtail = args.promtail if hasattr(args, 'promtail') and args.promtail else settings["monitoring"][
            "promtail_container"]
        loki = args.loki if hasattr(args, 'loki') and args.loki else settings["monitoring"]["loki_container"]

        # Use the podman bridge to update and start monitoring
        cmd = [
            f"{INSTALL_DIR}/bridges/podman.sh",
            "--update-container",
            "--engine", engine,
            "--promtail", promtail,
            "--loki", loki
        ]

        if hasattr(args, 'force') and args.force:
            cmd.append("--force")

        if hasattr(args, 'verbose') and args.verbose:
            cmd.append("--verbose")

        # Run the start command
        run_command(cmd)

        print("Monitoring started. Use 'logbuddy status' to check status.")
    else:
        print(f"Starting monitoring with backend '{backend}' not yet implemented")
        # Future: Add support for other backends


def stop_monitoring(args):
    """Stop log monitoring."""
    settings = load_settings()

    # Get backend settings
    backend = settings["monitoring"]["backend"]

    if backend == "loki-promtail":
        # Get container settings
        engine = args.engine if hasattr(args, 'engine') and args.engine else settings["monitoring"]["container_engine"]
        promtail = args.promtail if hasattr(args, 'promtail') and args.promtail else settings["monitoring"][
            "promtail_container"]
        loki = args.loki if hasattr(args, 'loki') and args.loki else settings["monitoring"]["loki_container"]

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
    else:
        print(f"Stopping monitoring with backend '{backend}' not yet implemented")
        # Future: Add support for other backends


def check_status(args):
    """Check monitoring status."""
    settings = load_settings()

    # Get backend settings
    backend = settings["monitoring"]["backend"]

    if backend == "loki-promtail":
        # Get container settings
        engine = args.engine if hasattr(args, 'engine') and args.engine else settings["monitoring"]["container_engine"]
        promtail = args.promtail if hasattr(args, 'promtail') and args.promtail else settings["monitoring"][
            "promtail_container"]
        loki = args.loki if hasattr(args, 'loki') and args.loki else settings["monitoring"]["loki_container"]

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
                port = settings["monitoring"]["port"]
                print(f"\nChecking Loki API on port {port}...")
                try:
                    # This is just a basic check
                    api_result = subprocess.run(
                        ["curl", "-s", f"http://localhost:{port}/ready"],
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

            # Print Grafana connection info
            username = settings["monitoring"]["credentials"]["username"]
            password = settings["monitoring"]["credentials"]["password"]
            port = settings["monitoring"]["port"]

            print("\nGrafana Connection Information:")
            print(f"  URL: http://localhost:{port}")
            print(f"  Username: {username}")
            if password:
                print(f"  Password: {password}")
            else:
                print("  Password: Not set (check installation logs)")

        except Exception as e:
            print(f"Error checking status: {e}")
            sys.exit(1)
    else:
        print(f"Status check for backend '{backend}' not yet implemented")
        # Future: Add support for other backends


def handle_settings(args):
    """View or modify settings."""
    settings = load_settings()

    # Print current settings
    if not hasattr(args, 'action') or not args.action:
        print("Current settings:")
        print(json.dumps(settings, indent=2))
        print("\nUse 'logbuddy settings set <section> <key> <value>' to modify a setting")
        print("Use 'logbuddy settings reset' to reset to defaults")
        return

    # Handle settings actions
    if args.action == "set":
        if not all([args.section, args.key, args.value]):
            print("Error: section, key, and value are required")
            print("Usage: logbuddy settings set <section> <key> <value>")
            return

        # Parse the value
        try:
            if args.value.lower() == "true":
                value = True
            elif args.value.lower() == "false":
                value = False
            elif args.value.isdigit():
                value = int(args.value)
            elif args.value.replace('.', '', 1).isdigit():
                value = float(args.value)
            else:
                value = args.value
        except:
            value = args.value

        # Update the setting
        if args.section in settings:
            if args.key in settings[args.section]:
                old_value = settings[args.section][args.key]
                settings[args.section][args.key] = value
                save_settings(settings)
                print(f"Updated setting {args.section}.{args.key}: {old_value} -> {value}")
            else:
                print(f"Warning: Key '{args.key}' not found in section '{args.section}'")
                if input("Create this setting? [y/N] ").lower() == 'y':
                    settings[args.section][args.key] = value
                    save_settings(settings)
                    print(f"Created setting {args.section}.{args.key} = {value}")
        else:
            print(f"Error: Section '{args.section}' not found")
            print(f"Available sections: {', '.join(settings.keys())}")

    elif args.action == "reset":
        if input("Are you sure you want to reset all settings to defaults? [y/N] ").lower() == 'y':
            # Preserve some system settings
            old_first_run = settings["system"]["first_run"]
            old_setup_completed = settings["system"]["setup_completed"]
            old_last_discovery = settings["system"]["last_discovery"]
            old_password = settings["monitoring"]["credentials"][
                "password"] if "monitoring" in settings and "credentials" in settings["monitoring"] else ""

            # Reset to defaults
            settings = DEFAULT_SETTINGS.copy()

            # Restore preserved settings
            settings["system"]["first_run"] = old_first_run
            settings["system"]["setup_completed"] = old_setup_completed
            settings["system"]["last_discovery"] = old_last_discovery
            settings["monitoring"]["credentials"]["password"] = old_password

            save_settings(settings)
            print("Settings reset to defaults")

    elif args.action == "import":
        if not args.file:
            print("Error: file is required")
            print("Usage: logbuddy settings import <file>")
            return

        if not os.path.exists(args.file):
            print(f"Error: File not found: {args.file}")
            return

        try:
            with open(args.file, 'r') as f:
                if args.file.endswith('.json'):
                    new_settings = json.load(f)
                elif args.file.endswith('.yaml') or args.file.endswith('.yml'):
                    new_settings = yaml.safe_load(f)
                else:
                    print("Error: File must be JSON or YAML")
                    return

                # Merge with current settings
                deep_update(settings, new_settings)
                save_settings(settings)
                print(f"Imported settings from {args.file}")
        except Exception as e:
            print(f"Error importing settings: {e}")

    elif args.action == "export":
        file_path = args.file or "logbuddy_settings.json"

        try:
            with open(file_path, 'w') as f:
                if file_path.endswith('.yaml') or file_path.endswith('.yml'):
                    yaml.dump(settings, f, default_flow_style=False)
                else:
                    json.dump(settings, f, indent=2)
                print(f"Settings exported to {file_path}")
        except Exception as e:
            print(f"Error exporting settings: {e}")


def run_setup_wizard():
    """Run the interactive setup wizard."""
    settings = load_settings()

    print("\n=== LogBuddy Setup Wizard ===\n")
    print("This wizard will help you set up LogBuddy for your system.")
    print("You can re-run this wizard at any time with 'logbuddy init'.")

    # Step 1: Configure monitoring backend
    print("\n=== Step 1: Monitoring Backend ===")
    print("LogBuddy can use different backends for log monitoring.")
    print("Currently available:")
    print("  1) Loki/Promtail - Grafana's log aggregation solution")
    print("  2) None - Discovery only, no monitoring")

    backend_choice = input("Choose a backend [1]: ").strip() or "1"

    if backend_choice == "1":
        settings["monitoring"]["backend"] = "loki-promtail"

        # Container engine
        print("\nWhich container engine would you like to use?")
        print("  1) Podman (default, more secure)")
        print("  2) Docker")

        engine_choice = input("Choose a container engine [1]: ").strip() or "1"
        settings["monitoring"]["container_engine"] = "podman" if engine_choice == "1" else "docker"

        # Container names
        default_promtail = settings["monitoring"]["promtail_container"]
        default_loki = settings["monitoring"]["loki_container"]

        settings["monitoring"]["promtail_container"] = input(
            f"Promtail container name [{default_promtail}]: ").strip() or default_promtail
        settings["monitoring"]["loki_container"] = input(
            f"Loki container name [{default_loki}]: ").strip() or default_loki

        # Port
        default_port = settings["monitoring"]["port"]
        port_input = input(f"Loki port [{default_port}]: ").strip() or str(default_port)
        settings["monitoring"]["port"] = int(port_input)

        # Credentials
        default_username = settings["monitoring"]["credentials"]["username"]
        settings["monitoring"]["credentials"]["username"] = input(
            f"Admin username [{default_username}]: ").strip() or default_username

        if not settings["monitoring"]["credentials"]["password"]:
            settings["monitoring"]["credentials"]["password"] = generate_password()
            print(f"Generated password: {settings['monitoring']['credentials']['password']}")
            print("You can change this later if needed.")

        # Auto-start
        auto_start = input("Automatically start monitoring after setup? [Y/n]: ").strip().lower() != "n"
        settings["monitoring"]["auto_start"] = auto_start

    elif backend_choice == "2":
        settings["monitoring"]["backend"] = "none"
        print("No monitoring backend selected. LogBuddy will only perform log discovery.")

    # Step 2: Discovery settings
    print("\n=== Step 2: Log Discovery Settings ===")

    # Discovery interval
    print("How often should LogBuddy discover logs?")
    print("  1) Daily (default)")
    print("  2) Hourly")
    print("  3) Weekly")
    print("  4) Manual only")

    interval_choice = input("Choose an interval [1]: ").strip() or "1"

    if interval_choice == "1":
        settings["discovery"]["interval"] = "daily"
    elif interval_choice == "2":
        settings["discovery"]["interval"] = "hourly"
    elif interval_choice == "3":
        settings["discovery"]["interval"] = "weekly"
    elif interval_choice == "4":
        settings["discovery"]["interval"] = "manual"

    # Step 3: User interface preferences
    print("\n=== Step 3: User Interface Preferences ===")

    # Tree view
    print("The log selection tree view allows you to manually select which logs to monitor.")
    print("Would you like to:")
    print("  1) Use the tree view for initial configuration (recommended)")
    print("  2) Skip the tree view and use recommended settings")

    tree_choice = input("Choose an option [1]: ").strip() or "1"
    settings["ui"]["skip_tree_view"] = tree_choice == "2"

    if tree_choice == "2":
        settings["ui"]["auto_select_recommended"] = True
        print("LogBuddy will automatically select recommended logs for monitoring.")

    # Step 4: Notification settings
    print("\n=== Step 4: Notification Settings ===")

    # Email notifications
    email_notify = input("Would you like to receive email notifications? [y/N]: ").strip().lower() == "y"

    if email_notify:
        email = input("Enter your email address: ").strip()
        settings["output"]["notify_email"] = email
        print(f"Email notifications will be sent to {email}")

    # Save settings
    settings["system"]["first_run"] = False
    settings["system"]["setup_completed"] = True
    save_settings(settings)

    print("\n=== Setup Complete! ===")
    print("Your LogBuddy configuration has been saved.")

    # Run discovery
    print("\nRunning initial log discovery...")
    try:
        discover_logs(argparse.Namespace(
            verbose=True,
            format="json",
            include=None,
            exclude=None,
            validate=True,
            legacy=False,
            output=DISCOVERY_OUTPUT,
            timeout=None
        ))
    except:
        print("Warning: Initial log discovery failed. You can run it manually with 'logbuddy discover'.")

    # Configure logs
    if not settings["ui"]["skip_tree_view"]:
        print("\nNow let's configure which logs to monitor.")
        input("Press Enter to continue to the configuration screen...")

        try:
            configure_logs(argparse.Namespace(force_tree_view=True))
        except:
            print("Warning: Log configuration failed. You can run it manually with 'logbuddy config'.")
    else:
        # Auto-configure
        configure_logs(argparse.Namespace(force_tree_view=False))

    # Install and start monitoring
    if settings["monitoring"]["backend"] != "none":
        print("\nWould you like to install the monitoring backend now?")
        install_now = input("Install now? [Y/n]: ").strip().lower() != "n"

        if install_now:
            try:
                install_monitoring(argparse.Namespace(backend=settings["monitoring"]["backend"]))

                if settings["monitoring"]["auto_start"]:
                    print("\nStarting monitoring...")
                    start_monitoring(argparse.Namespace())
            except:
                print("Warning: Monitoring installation failed. You can install it manually with 'logbuddy install'.")

    print("\nSetup is complete! You can now use LogBuddy with the following commands:")
    print("  logbuddy discover     # Discover logs on the system")
    print("  logbuddy config       # Configure which logs to monitor")
    print("  logbuddy start        # Start monitoring")
    print("  logbuddy status       # Check monitoring status")
    print("  logbuddy settings     # View or modify settings")


def init_command(args):
    """Run the initial setup wizard."""
    # Check if setup has already been completed
    settings = load_settings()

    if settings["system"]["setup_completed"] and not args.force:
        print("LogBuddy has already been set up.")
        print("Use 'logbuddy init --force' to run the setup wizard again.")
        return

    # Run the setup wizard
    run_setup_wizard()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="LogBuddy - Unified Log Discovery and Monitoring Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Init command (new)
    init_parser = subparsers.add_parser("init", help="Run first-time setup wizard")
    init_parser.add_argument("--force", "-f", action="store_true", help="Force re-running the setup wizard")
    init_parser.set_defaults(func=init_command)

    # Discover command
    discover_parser = subparsers.add_parser("discover", help="Discover logs on the system")
    discover_parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    discover_parser.add_argument("--format", "-f", choices=["json", "yaml"], help="Output format")
    discover_parser.add_argument("--include", "-i", help="Include only specified log types (comma-separated)")
    discover_parser.add_argument("--exclude", "-e", help="Exclude specified log types (comma-separated)")
    discover_parser.add_argument("--validate", action="store_true", help="Validate log files")
    discover_parser.add_argument("--legacy", action="store_true", help="Use legacy discovery mode (runner.sh)")
    discover_parser.add_argument("--output", "-o", help="Output file path")
    discover_parser.add_argument("--timeout", "-t", type=int, help="Timeout in seconds")
    discover_parser.set_defaults(func=discover_logs)

    # Config command
    config_parser = subparsers.add_parser("config", help="Configure which logs to monitor")
    config_parser.add_argument("--auto-select", "-a", choices=["all", "none", "recommended"],
                               help="Automatically select logs")
    config_parser.add_argument("--force-tree-view", "-f", action="store_true",
                               help="Force using the tree view even if skip_tree_view is enabled")
    config_parser.set_defaults(func=configure_logs)

    # Update command
    update_parser = subparsers.add_parser("update", help="Update monitoring configuration")
    update_parser.add_argument("--docker-update", "-d", action="store_true",
                               help="Update container configuration")
    update_parser.set_defaults(func=update_monitoring_config)

    # Install command
    install_parser = subparsers.add_parser("install", help="Install monitoring backend")
    install_parser.add_argument("--backend", "-b", help="Monitoring backend to install")
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

    # Settings command (new)
    settings_parser = subparsers.add_parser("settings", help="View or modify settings")
    settings_parser.add_argument("action", nargs="?", choices=["set", "reset", "import", "export"],
                                 help="Action to perform")
    settings_parser.add_argument("section", nargs="?", help="Settings section (for set)")
    settings_parser.add_argument("key", nargs="?", help="Settings key (for set)")
    settings_parser.add_argument("value", nargs="?", help="New value (for set)")
    settings_parser.add_argument("--file", "-f", help="File path (for import/export)")
    settings_parser.set_defaults(func=handle_settings)

    # Parse arguments
    args = parser.parse_args()

    # Create necessary directories
    ensure_directories()

    # If no command is specified, print help
    if not hasattr(args, 'command') or not args.command:
        parser.print_help()
        sys.exit(1)

    # Check if this is the first run and no command is specified
    settings = load_settings()
    if settings["system"]["first_run"] and args.command not in ["init", "settings"]:
        print("This appears to be your first time running LogBuddy.")
        if input("Would you like to run the setup wizard? [Y/n]: ").strip().lower() != "n":
            init_command(argparse.Namespace(force=False))
            return

    # Run the specified function
    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()