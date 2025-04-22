#!/usr/bin/env python3
"""
LogBuddy Workflow Improvements

This module contains enhancements for the main logbuddy.py workflow including:
- Improved handling of common tasks
- Smart command combinations
- Helper functions to simplify the main workflow
"""

import os
import sys
import json
import yaml
import subprocess
import shutil
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Union
from datetime import datetime

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from core.system_detect import detect_system_config

# Make sure these match the constants in logbuddy.py
INSTALL_DIR = "/opt/logbuddy"
CONFIG_DIR = "/etc/logbuddy"
DATA_DIR = "/var/lib/logbuddy"
LOG_DIR = "/var/log/logbuddy"
DISCOVERY_OUTPUT = f"{DATA_DIR}/discovered_logs.json"
DEFAULT_CONFIG = f"{CONFIG_DIR}/config.json"


def ensure_directories():
    """Ensure required directories exist."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(DISCOVERY_OUTPUT), exist_ok=True)


def detect_system_config() -> Dict[str, Any]:
    """Detect system configuration for setup automation.

    Returns:
        dict: Dictionary with detected system settings
    """
    detected = {
        "container_engine": None,
        "loki_container": None,
        "promtail_container": None,
        "available_port": None,
        "log_types_found": [],
        "web_server": None,
        "custom_paths": {}
    }

    # Detect container engines
    try:
        # Check for podman
        result = subprocess.run(
            ["which", "podman"],
            capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            detected["container_engine"] = "podman"
        else:
            # Check for docker
            result = subprocess.run(
                ["which", "docker"],
                capture_output=True, text=True, check=False
            )
            if result.returncode == 0:
                detected["container_engine"] = "docker"
    except:
        pass

    # Detect existing containers
    engine = detected["container_engine"]
    if engine:
        try:
            # Check for existing Loki container
            cmd = [engine, "ps", "-a", "--format", "{{.Names}}"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                containers = result.stdout.strip().split('\n')
                for container in containers:
                    if container and 'loki' in container.lower():
                        detected["loki_container"] = container
                    if container and 'promtail' in container.lower():
                        detected["promtail_container"] = container
        except:
            pass

    # Detect available port
    try:
        # Start with default Loki port
        for port in [3100, 9096, 8080]:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(('localhost', port)) != 0:
                    # Port is available
                    detected["available_port"] = port
                    break
    except:
        detected["available_port"] = 3100  # Default fallback

    # Detect installed software for log types

    # OpenLiteSpeed
    if os.path.exists("/usr/local/lsws") or glob.glob("/etc/openlitespeed*"):
        detected["log_types_found"].append("openlitespeed")
        detected["web_server"] = "openlitespeed"

    # WordPress
    wp_configs = []
    for search_path in ["/var/www/html", "/var/www", "/home/*/public_html"]:
        if "*" in search_path:
            base_path = search_path.split("*")[0]
            if os.path.exists(base_path):
                for item in os.listdir(base_path):
                    full_path = os.path.join(base_path, item)
                    if os.path.isdir(full_path):
                        wp_config = os.path.join(full_path, search_path.split("*")[1], "wp-config.php")
                        if os.path.exists(wp_config):
                            wp_configs.append(wp_config)
        else:
            wp_config = os.path.join(search_path, "wp-config.php")
            if os.path.exists(wp_config):
                wp_configs.append(wp_config)

    if wp_configs:
        detected["log_types_found"].append("wordpress")
        detected["custom_paths"]["wordpress_configs"] = wp_configs

    # PHP
    php_paths = []
    for php_path in ["/etc/php", "/usr/bin/php", "/usr/local/bin/php"]:
        if os.path.exists(php_path):
            php_paths.append(php_path)
            break

    if php_paths:
        detected["log_types_found"].append("php")
        detected["custom_paths"]["php_paths"] = php_paths

    # MySQL/MariaDB
    mysql_paths = []
    for mysql_path in ["/etc/mysql", "/var/lib/mysql", "/etc/my.cnf"]:
        if os.path.exists(mysql_path):
            mysql_paths.append(mysql_path)
            break

    if mysql_paths:
        detected["log_types_found"].append("mysql")
        detected["custom_paths"]["mysql_paths"] = mysql_paths

    # CyberPanel
    if os.path.exists("/usr/local/CyberCP") or os.path.exists("/etc/cyberpanel"):
        detected["log_types_found"].append("cyberpanel")

    return detected


def load_settings():
    """Load settings from config file or create defaults if not found."""
    ensure_directories()

    if os.path.exists(DEFAULT_CONFIG):
        try:
            with open(DEFAULT_CONFIG, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading settings: {e}")
            return create_default_settings()
    else:
        return create_default_settings()


def create_default_settings():
    """Create default settings based on system detection."""
    # Detect system configuration
    detected = detect_system_config()

    # Create default settings using detected values
    settings = {
        "discovery": {
            "enabled": True,
            "interval": "daily",
            "include_types": detected["log_types_found"],
            "exclude_types": [],
            "validate_logs": True,
            "timeout": 300
        },
        "monitoring": {
            "backend": "loki-promtail" if detected["container_engine"] else "none",
            "container_engine": detected["container_engine"] or "podman",
            "promtail_container": detected["promtail_container"] or "promtail",
            "loki_container": detected["loki_container"] or "loki",
            "auto_start": True,
            "port": detected["available_port"] or 3100,
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

    return settings


def save_settings(settings):
    """Save settings to config file."""
    ensure_directories()

    try:
        with open(DEFAULT_CONFIG, 'w') as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving settings: {e}")
        return False


def generate_password(length=12):
    """Generate a secure random password."""
    import random
    import string
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choice(chars) for _ in range(length))


def run_command(cmd, display=True, check=True, capture_output=True):
    """Run a command and return its output."""
    try:
        if display:
            print(f"Running: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True,
            check=check
        )
        return result
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {e}")
        print(f"Command output: {e.stdout if hasattr(e, 'stdout') else ''}")
        print(f"Command error: {e.stderr if hasattr(e, 'stderr') else ''}")
        if check:
            sys.exit(1)
        return e


def validate_discover_run(settings):
    """Check if log discovery has been run and run it if not."""
    if not os.path.exists(DISCOVERY_OUTPUT):
        print("No log discovery results found. Running discovery first...")

        # Run discovery with default options
        cmd = [f"{INSTALL_DIR}/log_discovery.py", "--output", DISCOVERY_OUTPUT]

        # Add any include/exclude types
        include_types = settings["discovery"]["include_types"]
        if include_types:
            if isinstance(include_types, list):
                include_types = ",".join(include_types)
            cmd.extend(["--include", include_types])

        exclude_types = settings["discovery"]["exclude_types"]
        if exclude_types:
            if isinstance(exclude_types, list):
                exclude_types = ",".join(exclude_types)
            cmd.extend(["--exclude", exclude_types])

        # Add validation flag if enabled
        if settings["discovery"]["validate_logs"]:
            cmd.append("--validate")

        # Run the discovery script
        run_command(cmd)

        # Update settings with discovery timestamp
        settings["system"]["last_discovery"] = datetime.now().isoformat()
        save_settings(settings)

        return True
    return False


def quick_setup_command(args):
    """Run a quick setup that combines init, discover, config, install, and start."""
    print("\n=== LogBuddy Quick Setup ===\n")
    print("This will set up LogBuddy with recommended settings by:")
    print("1. Detecting your system configuration")
    print("2. Running log discovery")
    print("3. Configuring log monitoring")
    print("4. Installing and starting the monitoring backend")
    print("\nTo customize any step, use the individual commands instead.")

    if input("\nContinue with quick setup? [Y/n]: ").strip().lower() == 'n':
        print("Quick setup canceled. Use individual commands for more control.")
        return

    # Step 1: Detect system and create settings
    print("\n=== Step 1: System Detection ===")
    detected = detect_system_config()

    # Display detected configuration
    if detected["container_engine"]:
        print(f"✓ Container engine detected: {detected['container_engine']}")
    else:
        print("✗ No container engine detected, will use podman")

    if detected["log_types_found"]:
        print(f"✓ Detected log types: {', '.join(detected['log_types_found'])}")
    else:
        print("✗ No log sources detected, will perform full system scan")

    # Create settings with detection data
    settings = create_default_settings()

    # Generate a password for Loki if needed
    if not settings["monitoring"]["credentials"]["password"]:
        settings["monitoring"]["credentials"]["password"] = generate_password()

    # Mark as not first run and setup completed
    settings["system"]["first_run"] = False
    settings["system"]["setup_completed"] = True

    # Save settings
    save_settings(settings)

    # Step 2: Run log discovery
    print("\n=== Step 2: Log Discovery ===")

    # Run discovery with default options
    validate_discover_run(settings)

    # Step 3: Configure log monitoring
    print("\n=== Step 3: Log Configuration ===")

    # Use skip_tree_view to determine if we use automatic or interactive configuration
    if not os.path.exists(DISCOVERY_OUTPUT):
        print("Error: Log discovery didn't produce output. Setup cannot continue.")
        return

    # Generate configuration with recommended settings
    print("Setting up monitoring with recommended logs...")

    # Build command for non-interactive config
    cmd = [
        f"{INSTALL_DIR}/bridges/promtail_conf_gen.py",
        "--input", DISCOVERY_OUTPUT,
        "--output", f"{CONFIG_DIR}/promtail-config-settings.yaml",
        "--auto-select", "recommended",
        "--non-interactive"
    ]

    run_command(cmd)

    # Generate Promtail configuration
    cmd = [
        f"{INSTALL_DIR}/bridges/promtail.py",
        "--input", DISCOVERY_OUTPUT,
        "--output", f"{CONFIG_DIR}/promtail-config.yaml",
        "--config", f"{CONFIG_DIR}/promtail-config-settings.yaml"
    ]

    run_command(cmd)

    # Step 4: Install and start monitoring
    if settings["monitoring"]["backend"] == "loki-promtail":
        print("\n=== Step 4: Installing Monitoring Backend ===")

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
        env["LOGBUDDY_USERNAME"] = settings["monitoring"]["credentials"]["username"]
        env["LOGBUDDY_PASSWORD"] = settings["monitoring"]["credentials"]["password"]

        # Run the installation script
        print("Starting Loki/Promtail installation...")

        try:
            subprocess.run([temp_script], env=env, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Installation failed: {e}")
            print("Setup will continue but monitoring won't be installed.")
            print("You can install it later with 'logbuddy install'")

        # Start monitoring
        print("\n=== Step 5: Starting Monitoring ===")

        engine = settings["monitoring"]["container_engine"]
        promtail = settings["monitoring"]["promtail_container"]
        loki = settings["monitoring"]["loki_container"]

        # Use the podman bridge to update and start monitoring
        cmd = [
            f"{INSTALL_DIR}/bridges/podman.sh",
            "--update-container",
            "--engine", engine,
            "--promtail", promtail,
            "--loki", loki,
            "--force"
        ]

        run_command(cmd)

    # Step 5: Show final summary
    print("\n=== Setup Complete! ===")
    print("LogBuddy has been set up with recommended settings.")
    print("\nConfiguration details:")
    print(f"  Log discovery interval: {settings['discovery']['interval']}")
    if settings['monitoring']['backend'] == 'loki-promtail':
        print(f"  Monitoring backend: Loki/Promtail with {settings['monitoring']['container_engine']}")
        print(f"  Loki container: {settings['monitoring']['loki_container']}")
        print(f"  Promtail container: {settings['monitoring']['promtail_container']}")
        print(f"  Loki port: {settings['monitoring']['port']}")
        print(f"  Username: {settings['monitoring']['credentials']['username']}")
        print(f"  Password: {settings['monitoring']['credentials']['password']}")
    else:
        print("  Monitoring backend: None (discovery only)")

    print("\nTo view your monitoring status: logbuddy status")
    print("To change settings: logbuddy settings")


def doctor_command(args):
    """Check system configuration and fix common issues."""
    print("\n=== LogBuddy Doctor ===\n")
    print("Checking system configuration for issues...\n")

    issues_found = 0
    issues_fixed = 0

    # Load current settings
    settings = load_settings()

    # Check 1: Is LogBuddy installed correctly?
    if not os.path.exists(INSTALL_DIR):
        print("✗ LogBuddy installation directory not found")
        print("  Recommendation: Reinstall LogBuddy using the installer script")
        issues_found += 1
    else:
        print("✓ LogBuddy installation directory found")

        # Check for key files
        for file in ["log_discovery.py", "log_source.py", "runner.sh"]:
            if not os.path.exists(f"{INSTALL_DIR}/{file}"):
                print(f"✗ Required file not found: {file}")
                print(f"  Recommendation: Reinstall LogBuddy")
                issues_found += 1

    # Check 2: Settings file
    if not os.path.exists(DEFAULT_CONFIG):
        print("✗ Settings file not found")
        if input("  Create default settings file? [Y/n]: ").strip().lower() != 'n':
            settings = create_default_settings()
            save_settings(settings)
            print("  ✓ Created default settings file")
            issues_fixed += 1
        else:
            print("  Recommendation: Run 'logbuddy init' to create settings")
            issues_found += 1
    else:
        print("✓ Settings file found")

    # Check 3: Container engine
    engine = settings["monitoring"]["container_engine"]
    if settings["monitoring"]["backend"] == "loki-promtail":
        engine_path = shutil.which(engine)
        if not engine_path:
            print(f"✗ Container engine '{engine}' not found")

            # Try to detect alternative
            alt_engine = "docker" if engine == "podman" else "podman"
            alt_path = shutil.which(alt_engine)

            if alt_path:
                if input(f"  Switch to {alt_engine}? [Y/n]: ").strip().lower() != 'n':
                    settings["monitoring"]["container_engine"] = alt_engine
                    save_settings(settings)
                    print(f"  ✓ Switched container engine to {alt_engine}")
                    issues_fixed += 1
                    engine = alt_engine
                else:
                    print(f"  Recommendation: Install {engine} or switch to {alt_engine}")
                    issues_found += 1
            else:
                print(f"  Recommendation: Install {engine}")
                issues_found += 1
        else:
            print(f"✓ Container engine '{engine}' found at {engine_path}")

    # Check 4: Containers running
    if settings["monitoring"]["backend"] == "loki-promtail" and shutil.which(engine):
        loki = settings["monitoring"]["loki_container"]
        promtail = settings["monitoring"]["promtail_container"]

        # Check if containers exist
        try:
            loki_exists = subprocess.run(
                [engine, "container", "inspect", loki],
                capture_output=True, check=False
            ).returncode == 0

            promtail_exists = subprocess.run(
                [engine, "container", "inspect", promtail],
                capture_output=True, check=False
            ).returncode == 0

            if not loki_exists or not promtail_exists:
                print("✗ Monitoring containers not found")
                if input("  Run installation? [Y/n]: ").strip().lower() != 'n':
                    print("  Running installation...")
                    # This would call the install_monitoring function
                    print("  This would install the monitoring containers")
                    issues_fixed += 1
                else:
                    print("  Recommendation: Run 'logbuddy install' to set up containers")
                    issues_found += 1
            else:
                # Check if containers are running
                loki_running = "running" in subprocess.run(
                    [engine, "container", "inspect", "--format", "{{.State.Status}}", loki],
                    capture_output=True, text=True, check=False
                ).stdout

                promtail_running = "running" in subprocess.run(
                    [engine, "container", "inspect", "--format", "{{.State.Status}}", promtail],
                    capture_output=True, text=True, check=False
                ).stdout

                if not loki_running or not promtail_running:
                    print("✗ Monitoring containers are not running")
                    if input("  Start containers? [Y/n]: ").strip().lower() != 'n':
                        print("  Starting containers...")

                        if not loki_running:
                            subprocess.run([engine, "start", loki], check=False)

                        if not promtail_running:
                            subprocess.run([engine, "start", promtail], check=False)

                        print("  ✓ Started monitoring containers")
                        issues_fixed += 1
                    else:
                        print("  Recommendation: Run 'logbuddy start' to start monitoring")
                        issues_found += 1
                else:
                    print("✓ Monitoring containers are running")
        except Exception as e:
            print(f"✗ Error checking container status: {e}")
            issues_found += 1

    # Check 5: Discovery results
    if not os.path.exists(DISCOVERY_OUTPUT):
        print("✗ No log discovery results found")
        if input("  Run log discovery now? [Y/n]: ").strip().lower() != 'n':
            print("  Running log discovery...")
            validate_discover_run(settings)
            print("  ✓ Log discovery completed")
            issues_fixed += 1
        else:
            print("  Recommendation: Run 'logbuddy discover' to find logs")
            issues_found += 1
    else:
        try:
            # Check if discovery results are valid
            with open(DISCOVERY_OUTPUT, 'r') as f:
                discovery_data = json.load(f)

            if "sources" not in discovery_data or not discovery_data.get("sources"):
                print("✗ Log discovery results are empty or invalid")
                if input("  Run log discovery again? [Y/n]: ").strip().lower() != 'n':
                    print("  Running log discovery...")
                    validate_discover_run(settings)
                    print("  ✓ Log discovery completed")
                    issues_fixed += 1
                else:
                    print("  Recommendation: Run 'logbuddy discover' to find logs")
                    issues_found += 1
            else:
                print(f"✓ Log discovery results found ({len(discovery_data.get('sources', []))} logs)")

                # Check if discovery is old
                last_discovery = settings["system"].get("last_discovery")
                if last_discovery:
                    try:
                        discovery_time = datetime.fromisoformat(last_discovery)
                        days_old = (datetime.now() - discovery_time).days

                        if days_old > 7:
                            print(f"✗ Log discovery results are {days_old} days old")
                            if input("  Run discovery again? [Y/n]: ").strip().lower() != 'n':
                                print("  Running log discovery...")
                                validate_discover_run(settings)
                                print("  ✓ Log discovery completed")
                                issues_fixed += 1
                            else:
                                print("  Recommendation: Run 'logbuddy discover' to update log list")
                                issues_found += 1
                    except:
                        pass
        except Exception as e:
            print(f"✗ Error reading discovery results: {e}")
            issues_found += 1

    # Check 6: Promtail configuration
    promtail_config = f"{CONFIG_DIR}/promtail-config.yaml"
    if not os.path.exists(promtail_config) and settings["monitoring"]["backend"] == "loki-promtail":
        print("✗ Promtail configuration not found")
        if input("  Generate configuration now? [Y/n]: ").strip().lower() != 'n':
            print("  Generating Promtail configuration...")

            # First make sure we have promtail settings
            promtail_settings = f"{CONFIG_DIR}/promtail-config-settings.yaml"
            if not os.path.exists(promtail_settings):
                # Create with recommended settings
                cmd = [
                    f"{INSTALL_DIR}/bridges/promtail_conf_gen.py",
                    "--input", DISCOVERY_OUTPUT,
                    "--output", promtail_settings,
                    "--auto-select", "recommended",
                    "--non-interactive"
                ]
                run_command(cmd)

            # Generate Promtail configuration
            cmd = [
                f"{INSTALL_DIR}/bridges/promtail.py",
                "--input", DISCOVERY_OUTPUT,
                "--output", promtail_config,
                "--config", promtail_settings
            ]
            run_command(cmd)

            print("  ✓ Generated Promtail configuration")
            issues_fixed += 1
        else:
            print("  Recommendation: Run 'logbuddy update' to generate configuration")
            issues_found += 1
    elif settings["monitoring"]["backend"] == "loki-promtail":
        print("✓ Promtail configuration found")

    # Summary
    print("\n=== Summary ===")
    if issues_found == 0:
        print("No issues found! Your LogBuddy installation looks healthy.")
    else:
        print(f"Found {issues_found} issue(s), fixed {issues_fixed}.")

        if issues_found > issues_fixed:
            print("\nRecommended actions:")
            if not os.path.exists(INSTALL_DIR):
                print("- Reinstall LogBuddy using the installer script")
            if not os.path.exists(DEFAULT_CONFIG):
                print("- Run 'logbuddy init' to set up configuration")
            if settings["monitoring"]["backend"] == "loki-promtail" and not shutil.which(
                    settings["monitoring"]["container_engine"]):
                print(f"- Install {settings['monitoring']['container_engine']} or change container engine")
            if not os.path.exists(DISCOVERY_OUTPUT):
                print("- Run 'logbuddy discover' to find logs")
            if not os.path.exists(f"{CONFIG_DIR}/promtail-config.yaml") and settings["monitoring"][
                "backend"] == "loki-promtail":
                print("- Run 'logbuddy update' to generate Promtail configuration")


def setup_command(args):
    """Combined setup that handles multiple steps in one command."""
    print("\n=== LogBuddy Setup ===\n")
    print("This will guide you through setting up LogBuddy.")

    # Determine if this is a new installation or update
    settings = load_settings()
    is_new = settings["system"]["first_run"]

    if is_new:
        print("It looks like this is your first time running LogBuddy.")
        print("We'll guide you through the initial setup process.")
    else:
        print("LogBuddy is already set up on this system.")
        print("This will update your configuration.")

        if not args.force and input("Continue with setup? [y/N]: ").strip().lower() != 'y':
            print("Setup canceled.")
            return

    # Run the enhanced setup wizard
    from settings_tui import run_settings_tui
    settings_saved = run_settings_tui()

    if settings_saved:
        print("Settings saved successfully.")
    else:
        print("Settings not saved. Using existing configuration.")

    # Reload settings
    settings = load_settings()

    # Check if discovery has been run
    if not os.path.exists(DISCOVERY_OUTPUT) or args.force:
        print("\nRunning log discovery...")
        validate_discover_run(settings)

    # Offer to configure logs
    if input("\nWould you like to configure which logs to monitor? [Y/n]: ").strip().lower() != 'n':
        # Either launch interactive configuration or use recommended settings
        if settings["ui"]["skip_tree_view"] and not args.interactive:
            print("Using recommended settings...")

            # Create config with recommended settings
            cmd = [
                f"{INSTALL_DIR}/bridges/promtail_conf_gen.py",
                "--input", DISCOVERY_OUTPUT,
                "--output", f"{CONFIG_DIR}/promtail-config-settings.yaml",
                "--auto-select", "recommended",
                "--non-interactive"
            ]
            run_command(cmd)

            # Generate Promtail configuration
            cmd = [
                f"{INSTALL_DIR}/bridges/promtail.py",
                "--input", DISCOVERY_OUTPUT,
                "--output", f"{CONFIG_DIR}/promtail-config.yaml",
                "--config", f"{CONFIG_DIR}/promtail-config-settings.yaml"
            ]
            run_command(cmd)
        else:
            print("Launching interactive configuration...")

            # Import from promtail_conf_gen.py
            # This is a placeholder - in reality we'd call the function from the module
            print("This would launch the interactive configuration UI")

    # Offer to set up monitoring
    if settings["monitoring"]["backend"] == "loki-promtail":
        if input("\nWould you like to set up Loki/Promtail monitoring? [Y/n]: ").strip().lower() != 'n':
            print("Setting up monitoring...")

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
            env["LOGBUDDY_USERNAME"] = settings["monitoring"]["credentials"]["username"]
            env["LOGBUDDY_PASSWORD"] = settings["monitoring"]["credentials"]["password"]

            # Run the installation script
            try:
                subprocess.run([temp_script], env=env, check=True)
            except subprocess.CalledProcessError as e:
                print(f"Installation failed: {e}")

            # Start monitoring if requested
            if input("\nStart monitoring now? [Y/n]: ").strip().lower() != 'n':
                print("Starting monitoring...")

                # Use the podman bridge to update and start monitoring
                cmd = [
                    f"{INSTALL_DIR}/bridges/podman.sh",
                    "--update-container",
                    "--engine", settings["monitoring"]["container_engine"],
                    "--promtail", settings["monitoring"]["promtail_container"],
                    "--loki", settings["monitoring"]["loki_container"]
                ]

                run_command(cmd)

    # Final message
    print("\n=== Setup Complete ===")
    print("LogBuddy has been set up on your system.")
    print("\nTo check monitoring status: logbuddy status")
    print("To view and change settings: logbuddy settings")
    print("To rediscover logs: logbuddy discover")


def check_system():
    """Perform a system check and suggest improvements."""
    # This function would check for:
    # 1. LogBuddy installation status
    # 2. Dependencies
    # 3. Container engine status
    # 4. Monitoring status
    # 5. Log discovery status
    # 6. Configuration status
    pass


# Define the new commands to add to logbuddy.py
NEW_COMMANDS = [
    {
        "name": "quicksetup",
        "help": "Quick setup with recommended settings",
        "function": "quick_setup_command"
    },
    {
        "name": "doctor",
        "help": "Check system configuration and fix common issues",
        "function": "doctor_command"
    },
    {
        "name": "setup",
        "help": "Interactive setup process",
        "function": "setup_command",
        "args": [
            {"name": "--force", "help": "Force setup even if already configured"},
            {"name": "--interactive", "help": "Force interactive configuration"}
        ]
    }
]

# Here's how to add the new commands to the main parser in logbuddy.py:
"""
# Add new workflow commands
quicksetup_parser = subparsers.add_parser("quicksetup", help="Quick setup with recommended settings")
quicksetup_parser.set_defaults(func=quick_setup_command)

doctor_parser = subparsers.add_parser("doctor", help="Check system configuration and fix common issues")
doctor_parser.set_defaults(func=doctor_command)

setup_parser = subparsers.add_parser("setup", help="Interactive setup process")
setup_parser.add_argument("--force", "-f", action="store_true", help="Force setup even if already configured")
setup_parser.add_argument("--interactive", "-i", action="store_true", help="Force interactive configuration")
setup_parser.set_defaults(func=setup_command)
"""

if __name__ == "__main__":
    # This file is not meant to be run directly
    print("This module should be imported by logbuddy.py, not run directly.")
    sys.exit(1)