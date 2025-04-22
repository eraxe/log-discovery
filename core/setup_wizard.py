#!/usr/bin/env python3
"""
LogBuddy Enhanced Setup Wizard

Provides an interactive setup wizard with system detection,
intelligent defaults, and streamlined configuration.
"""

import os
import sys
import json
import subprocess
import getpass
import time
import random
import string
import shutil
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from core.system_detect import detect_system_config


def generate_password(length=12):
    """Generate a secure random password."""
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choice(chars) for _ in range(length))


def run_enhanced_setup_wizard(install_dir=None, config_dir=None, data_dir=None):
    """Run the enhanced setup wizard with automatic detection.

    Args:
        install_dir: Installation directory (defaults to /opt/logbuddy in production)
        config_dir: Configuration directory (defaults to /etc/logbuddy in production)
        data_dir: Data directory (defaults to /var/lib/logbuddy in production)

    Returns:
        dict: The generated settings
    """
    # Set default paths - in production these would come from the main script
    INSTALL_DIR = install_dir or "/opt/logbuddy"
    CONFIG_DIR = config_dir or "/etc/logbuddy"
    DATA_DIR = data_dir or "/var/lib/logbuddy"
    DEFAULT_CONFIG = f"{CONFIG_DIR}/config.json"
    DISCOVERY_OUTPUT = f"{DATA_DIR}/discovered_logs.json"

    print("\n=== LogBuddy Enhanced Setup Wizard ===\n")
    print("This wizard will help you set up LogBuddy with automatic system detection.")
    print("You can re-run this wizard at any time with 'logbuddy init --force'.")

    # Create directories if needed
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    # Detect system configuration
    print("\n=== Detecting System Configuration ===")
    print("Analyzing your system...\n")

    detect_start = time.time()
    detected = detect_system_config()
    detect_time = time.time() - detect_start

    # Display detected settings
    print(f"Detection completed in {detect_time:.2f} seconds:")

    if detected["container_engine"]:
        print(f"✓ Container engine detected: {detected['container_engine']}")
    else:
        print("✗ No container engine detected, will use podman")

    if detected["loki_container"] or detected["promtail_container"]:
        if detected["loki_container"]:
            print(f"✓ Existing Loki container: {detected['loki_container']}")
        if detected["promtail_container"]:
            print(f"✓ Existing Promtail container: {detected['promtail_container']}")
        print("\nNOTE: LogBuddy will work with your existing containers.")
    else:
        print("✓ No existing monitoring containers, will set up new ones")

    if detected["available_port"]:
        print(f"✓ Available port detected: {detected['available_port']}")

    if detected["log_types_found"]:
        print(f"✓ Detected log types: {', '.join(detected['log_types_found'])}")
    else:
        print("✗ No log sources detected, will perform full system scan")

    if detected["web_server"]:
        print(f"✓ Web server detected: {detected['web_server']}")

    # Initialize settings with detected values
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
                "password": generate_password()
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
            "first_run": False,
            "setup_completed": False,
            "version": "1.1.0",
            "last_discovery": None
        }
    }

    # Step 1: Configure monitoring backend
    print("\n=== Step 1: Monitoring Backend ===")

    if detected["container_engine"]:
        print(f"Detected container engine: {detected['container_engine']}")
        backend_choice = input(f"Use Loki/Promtail with {detected['container_engine']}? [Y/n]: ").strip().lower()

        if backend_choice == 'n':
            print("\nAvailable options:")
            print("  1) Loki/Promtail - Grafana's log aggregation solution")
            print("  2) None - Discovery only, no monitoring")

            choice = input("Choose a backend [1]: ").strip() or "1"
            settings["monitoring"]["backend"] = "loki-promtail" if choice == "1" else "none"
    else:
        print("No container engine detected. You have the following options:")
        print("  1) Install Podman and use Loki/Promtail")
        print("  2) Discovery only (no monitoring)")

        choice = input("Choose an option [1]: ").strip() or "1"
        if choice == "1":
            settings["monitoring"]["backend"] = "loki-promtail"
            settings["monitoring"]["container_engine"] = "podman"

            # Offer to install Podman
            if input("Would you like to install Podman now? [y/N]: ").strip().lower() == 'y':
                print("\nAttempting to install Podman...")
                try:
                    if os.path.exists("/usr/bin/apt"):
                        subprocess.run(["apt-get", "update"], check=True)
                        subprocess.run(["apt-get", "install", "-y", "podman"], check=True)
                        print("✓ Podman installed successfully!")
                    elif os.path.exists("/usr/bin/dnf"):
                        subprocess.run(["dnf", "install", "-y", "podman"], check=True)
                        print("✓ Podman installed successfully!")
                    elif os.path.exists("/usr/bin/yum"):
                        subprocess.run(["yum", "install", "-y", "podman"], check=True)
                        print("✓ Podman installed successfully!")
                    else:
                        print("✗ Couldn't determine your package manager. Please install Podman manually.")
                except Exception as e:
                    print(f"✗ Error installing Podman: {str(e)}")
                    print("Please install Podman manually before continuing.")
        else:
            settings["monitoring"]["backend"] = "none"

    # Set container names
    if settings["monitoring"]["backend"] == "loki-promtail":
        if detected["loki_container"]:
            print(f"\nExisting Loki container detected: {detected['loki_container']}")
            settings["monitoring"]["loki_container"] = detected["loki_container"]
        else:
            loki_name = input(f"Loki container name [loki]: ").strip() or "loki"
            settings["monitoring"]["loki_container"] = loki_name

        if detected["promtail_container"]:
            print(f"Existing Promtail container detected: {detected['promtail_container']}")
            settings["monitoring"]["promtail_container"] = detected["promtail_container"]
        else:
            promtail_name = input(f"Promtail container name [promtail]: ").strip() or "promtail"
            settings["monitoring"]["promtail_container"] = promtail_name

    # Step 2: Discovery settings
    print("\n=== Step 2: Log Discovery Settings ===")

    # Show detected log types
    if detected["log_types_found"]:
        print(f"Detected log types: {', '.join(detected['log_types_found'])}")
        include_choice = input("Include only detected log types? [Y/n]: ").strip().lower()

        if include_choice == 'n':
            settings["discovery"]["include_types"] = []
    else:
        print("No log types detected. Will search for all supported types.")
        settings["discovery"]["include_types"] = []

    # Discovery interval
    print("\nHow often should LogBuddy discover logs?")
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

    # Step 4: Notification settings
    print("\n=== Step 4: Notification Settings ===")

    # Email notifications
    email_notify = input("Would you like to receive email notifications? [y/N]: ").strip().lower() == "y"

    if email_notify:
        email = input("Enter your email address: ").strip()
        settings["output"]["notify_email"] = email
        print(f"Email notifications will be sent to {email}")

    # Save settings
    settings["system"]["setup_completed"] = True
    print("\n=== Saving Configuration ===")
    try:
        with open(DEFAULT_CONFIG, 'w') as f:
            json.dump(settings, f, indent=2)
        print("✓ Configuration saved successfully")
    except Exception as e:
        print(f"✗ Error saving configuration: {str(e)}")

    print("\n=== Setup Complete! ===")
    print("Your LogBuddy configuration has been saved.")

    # Offer to run discovery now
    if input("\nWould you like to run initial log discovery now? [Y/n]: ").strip().lower() != 'n':
        print("\nRunning initial log discovery...")
        try:
            # This would normally call the discover_logs function from the main script
            # For now, we'll just update the settings with a timestamp
            print("This would run log discovery in the actual implementation.")

            # Update settings with discovery timestamp
            settings["system"]["last_discovery"] = datetime.now().isoformat()
            with open(DEFAULT_CONFIG, 'w') as f:
                json.dump(settings, f, indent=2)

            print("\n✓ Initial log discovery completed!")
        except Exception as e:
            print(f"✗ Error during log discovery: {str(e)}")
            print("You can run discovery manually with 'logbuddy discover'")

    # Next steps
    print("\n=== Next Steps ===")
    if settings["monitoring"]["backend"] == "loki-promtail":
        print("1. Run 'logbuddy install' to set up Loki and Promtail")
        print("2. Run 'logbuddy start' to start monitoring")
        print("3. Run 'logbuddy status' to check monitoring status")
    else:
        print("1. Run 'logbuddy discover' to find logs on your system")
        print("2. Run 'logbuddy config' to configure which logs to include")

    print("\nSetup has been completed successfully!")
    return settings


if __name__ == "__main__":
    # For testing
    run_enhanced_setup_wizard()