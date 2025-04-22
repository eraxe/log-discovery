#!/usr/bin/env python3
"""
LogBuddy System Detection Module
"""

import os
import subprocess
import socket
import glob
import re
import json
from typing import Dict, Any, List, Optional


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


def get_existing_config(config_path: str) -> Dict[str, Any]:
    """Get existing configuration if available.

    Args:
        config_path: Path to config file

    Returns:
        dict: Configuration dictionary or empty dict if not found
    """
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except:
            pass

    return {}


def detect_promtail_config(config_dir: str) -> Dict[str, Any]:
    """Detect existing Promtail configuration.

    Args:
        config_dir: Configuration directory

    Returns:
        dict: Information about Promtail configuration
    """
    config_info = {
        "exists": False,
        "path": None,
        "settings_path": None,
        "monitored_logs": 0,
        "needs_update": False
    }

    # Check for config files
    promtail_config = os.path.join(config_dir, "promtail-config.yaml")
    promtail_settings = os.path.join(config_dir, "promtail-config-settings.yaml")

    if os.path.exists(promtail_config):
        config_info["exists"] = True
        config_info["path"] = promtail_config

        # Check settings file
        if os.path.exists(promtail_settings):
            config_info["settings_path"] = promtail_settings

            # Try to determine if update is needed
            discovery_output = os.path.join(os.path.dirname(config_dir), "var/lib/logbuddy/discovered_logs.json")
            if os.path.exists(discovery_output):
                try:
                    # Check if discovery is newer than config
                    discovery_time = os.path.getmtime(discovery_output)
                    config_time = os.path.getmtime(promtail_config)

                    if discovery_time > config_time:
                        config_info["needs_update"] = True
                except:
                    pass

            # Try to count monitored logs
            try:
                # This is simplified - in real implementation we'd parse YAML
                with open(promtail_config, 'r') as f:
                    content = f.read()
                    # Count path entries as a rough estimate
                    config_info["monitored_logs"] = content.count("__path__")
            except:
                pass

    return config_info


if __name__ == "__main__":
    # For testing
    result = detect_system_config()
    print(json.dumps(result, indent=2))