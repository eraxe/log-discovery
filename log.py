#!/usr/bin/env python3
"""
Enhanced Smart Log Discovery System for OpenLiteSpeed/CyberPanel/WordPress

This script discovers log file locations by examining actual configuration files
rather than simply scanning for common patterns. It builds a structured output
that can be used to configure Loki/Promtail.

Key improvements:
- Class abstraction for different log sources
- Robust configuration parsing
- Parallel processing for performance
- Caching to reduce redundant operations
- Enhanced error handling and reporting
- Log rotation detection

Usage:
    python3 log_discovery.py [--output OUTPUT] [--format {json,yaml}] [--verbose]
    [--include TYPES] [--exclude TYPES] [--cache-file FILE] [--timeout SECONDS]

Author: Claude
Version: 2.0.0
Created: April 21, 2025
"""

import os
import re
import sys
import json
import yaml
import glob
import time
import fcntl
import hashlib
import signal
import logging
import argparse
import tempfile
import subprocess
import configparser
from pathlib import Path
from datetime import datetime
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('log_discovery')


class TimeoutError(Exception):
    """Exception raised when an operation times out."""
    pass


def timeout_handler(signum, frame):
    """Handler for timeout signal."""
    raise TimeoutError("Operation timed out")


class LogSource(ABC):
    """Base abstract class for all log source types."""

    def __init__(self, discoverer):
        """Initialize the log source.

        Args:
            discoverer: The parent LogDiscoverer instance
        """
        self.discoverer = discoverer
        self.logs_found = 0

    @abstractmethod
    def discover(self):
        """Discover logs for this source type.

        Returns:
            int: Number of logs discovered
        """
        pass

    def add_log(self, name, path, format="text", labels=None, exists=None):
        """Add a discovered log to the results.

        Args:
            name: Name identifier for the log
            path: Path to the log file
            format: Log file format (default: text)
            labels: Dictionary of labels for the log
            exists: Whether the file exists (will check if None)

        Returns:
            dict: The log entry that was added
        """
        return self.discoverer.add_log_source(
            self.__class__.__name__.lower().replace('logsource', ''),
            name, path, format, labels, exists
        )

    def _file_readable(self, path):
        """Check if a file exists and is readable.

        Args:
            path: Path to the file

        Returns:
            bool: True if file exists and is readable
        """
        try:
            return os.path.isfile(path) and os.access(path, os.R_OK)
        except Exception:
            return False

    def _load_file_content(self, path):
        """Safely load file content with timeout.

        Args:
            path: Path to the file

        Returns:
            str: File content or empty string on error
        """
        if not self._file_readable(path):
            return ""

        try:
            # Set timeout for file operations
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(5)  # 5 second timeout

            with open(path, 'r') as f:
                content = f.read()

            signal.alarm(0)  # Disable alarm
            return content
        except (TimeoutError, UnicodeDecodeError, PermissionError, FileNotFoundError) as e:
            logger.warning(f"Could not read file {path}: {str(e)}")
            return ""
        except Exception as e:
            logger.warning(f"Unexpected error reading {path}: {str(e)}")
            return ""
        finally:
            signal.alarm(0)  # Ensure alarm is disabled


class OpenLiteSpeedLogSource(LogSource):
    """Discovery for OpenLiteSpeed logs."""

    def discover(self):
        """Discover OpenLiteSpeed logs by examining configuration files."""
        self.discoverer.log("Searching for OpenLiteSpeed logs...")

        # Find OpenLiteSpeed config file
        config_paths = [
            "/usr/local/lsws/conf/httpd_config.conf",
            "/etc/openlitespeed/httpd_config.conf"
        ]

        config_file = next((path for path in config_paths if self._file_readable(path)), None)

        if not config_file:
            self.discoverer.log("OpenLiteSpeed config file not found", "WARN")
            return self.logs_found

        # Parse main config file
        config_content = self._load_file_content(config_file)
        if not config_content:
            return self.logs_found

        # Find main error log
        error_log_match = re.search(r'errorlog\s+(.+?)[\s\n]', config_content)
        if error_log_match:
            error_log_path = error_log_match.group(1)
            self.add_log(
                "main_error",
                error_log_path,
                labels={"level": "error", "service": "webserver"}
            )
            self.logs_found += 1

        # Find main access log
        access_log_match = re.search(r'accesslog\s+(.+?)[\s\n]', config_content)
        if access_log_match:
            access_log_path = access_log_match.group(1)
            self.add_log(
                "main_access",
                access_log_path,
                labels={"level": "access", "service": "webserver"}
            )
            self.logs_found += 1

        # Find virtual host configurations
        vhost_dir = None
        vhost_dir_match = re.search(r'configFile\s+(.+?)[\s\n]', config_content)
        if vhost_dir_match:
            config_file_path = vhost_dir_match.group(1)
            vhost_dir = os.path.dirname(config_file_path) if os.path.isabs(config_file_path) else os.path.dirname(
                os.path.join(os.path.dirname(config_file), config_file_path))

        if not vhost_dir or not os.path.exists(vhost_dir):
            # Try common locations
            vhost_dirs = [
                "/usr/local/lsws/conf/vhosts",
                "/etc/openlitespeed/vhosts"
            ]
            vhost_dir = next((dir_path for dir_path in vhost_dirs if os.path.exists(dir_path)), None)

        # Process virtual host configs
        if vhost_dir:
            self.discoverer.log(f"Looking for vhost configs in {vhost_dir}")

            # Use ThreadPoolExecutor for parallel processing of vhost configs
            with ThreadPoolExecutor(max_workers=min(10, os.cpu_count() * 2)) as executor:
                # Find all potential vhost config files
                vhost_configs = glob.glob(f"{vhost_dir}/*/*.conf") + glob.glob(f"{vhost_dir}/*.conf")

                # Process each vhost config in parallel
                future_to_config = {executor.submit(self._process_vhost_config, vhost_config): vhost_config for
                                    vhost_config in vhost_configs}

                for future in as_completed(future_to_config):
                    vhost_config = future_to_config[future]
                    try:
                        logs_found = future.result()
                        self.logs_found += logs_found
                    except Exception as e:
                        self.discoverer.log(f"Error processing vhost config {vhost_config}: {str(e)}", "ERROR")

        # Look for additional logs in standard locations
        log_dirs = [
            "/usr/local/lsws/logs",
            "/var/log/openlitespeed",
            "/var/log/lsws"
        ]

        # Extend search to include rotated logs
        for log_dir in log_dirs:
            if os.path.exists(log_dir):
                self.discoverer.log(f"Checking standard log directory: {log_dir}")

                # Look for all potential log files including rotated logs
                log_patterns = [
                    f"{log_dir}/error*.log*",
                    f"{log_dir}/access*.log*",
                    f"{log_dir}/stderr*.log*",
                    f"{log_dir}/lsphp*.log*",
                    f"{log_dir}/*.log*"
                ]

                all_logs = []
                for pattern in log_patterns:
                    all_logs.extend(glob.glob(pattern))

                # Process standard log files
                for log_file in set(all_logs):  # Use set to remove duplicates
                    # Skip if already processed
                    if self.discoverer.is_log_already_added(log_file):
                        continue

                    log_name = os.path.basename(log_file)
                    # Remove rotation suffix if present (e.g., .1, .gz)
                    base_name = re.sub(r'\.(?:gz|bz2|zip|\d+)$', '', log_name)

                    # Determine log type
                    if "error" in base_name:
                        self.add_log(
                            f"error_{base_name.replace('error', '').replace('.log', '')}".strip('_'),
                            log_file,
                            labels={"level": "error", "service": "webserver"}
                        )
                        self.logs_found += 1
                    elif "access" in base_name:
                        self.add_log(
                            f"access_{base_name.replace('access', '').replace('.log', '')}".strip('_'),
                            log_file,
                            labels={"level": "access", "service": "webserver"}
                        )
                        self.logs_found += 1
                    elif "stderr" in base_name or "lsphp" in base_name:
                        handler_name = base_name.replace('.log', '')
                        self.add_log(
                            f"script_{handler_name}",
                            log_file,
                            labels={"service": "script_handler", "handler": handler_name}
                        )
                        self.logs_found += 1

        return self.logs_found

    def _process_vhost_config(self, vhost_config):
        """Process a single vhost configuration file.

        Args:
            vhost_config: Path to the vhost config file

        Returns:
            int: Number of logs discovered in this config
        """
        logs_found = 0
        vhost_name = os.path.basename(os.path.dirname(vhost_config))
        if vhost_name == os.path.basename(os.path.dirname(os.path.dirname(vhost_config))):
            # Handle case where *.conf is directly in vhost_dir
            vhost_name = os.path.basename(vhost_config).replace('.conf', '')

        self.discoverer.log(f"Processing vhost: {vhost_name}")

        vhost_content = self._load_file_content(vhost_config)
        if not vhost_content:
            return logs_found

        # Get vhost domain
        vhost_domain = vhost_name
        domain_match = re.search(r'(?:vhDomain|domain)\s+([^\s]+)', vhost_content)
        if domain_match:
            vhost_domain = domain_match.group(1)

        # Get vhost error log
        vhost_error_match = re.search(r'errorlog\s+(.+?)[\s\n]', vhost_content)
        if vhost_error_match:
            error_log_path = vhost_error_match.group(1)
            # Handle relative paths
            if not os.path.isabs(error_log_path):
                error_log_path = os.path.normpath(os.path.join(os.path.dirname(vhost_config), error_log_path))

            self.add_log(
                f"vhost_{vhost_name}_error",
                error_log_path,
                labels={
                    "level": "error",
                    "service": "webserver",
                    "vhost": vhost_name,
                    "domain": vhost_domain
                }
            )
            logs_found += 1

            # Also look for rotated versions of this log
            self._find_rotated_logs(error_log_path, f"vhost_{vhost_name}_error", {
                "level": "error",
                "service": "webserver",
                "vhost": vhost_name,
                "domain": vhost_domain,
                "rotated": "true"
            })

        # Get vhost access log
        vhost_access_match = re.search(r'accesslog\s+(.+?)[\s\n]', vhost_content)
        if vhost_access_match:
            access_log_path = vhost_access_match.group(1)
            # Handle relative paths
            if not os.path.isabs(access_log_path):
                access_log_path = os.path.normpath(os.path.join(os.path.dirname(vhost_config), access_log_path))

            self.add_log(
                f"vhost_{vhost_name}_access",
                access_log_path,
                labels={
                    "level": "access",
                    "service": "webserver",
                    "vhost": vhost_name,
                    "domain": vhost_domain
                }
            )
            logs_found += 1

            # Also look for rotated versions of this log
            self._find_rotated_logs(access_log_path, f"vhost_{vhost_name}_access", {
                "level": "access",
                "service": "webserver",
                "vhost": vhost_name,
                "domain": vhost_domain,
                "rotated": "true"
            })

        return logs_found

    def _find_rotated_logs(self, log_path, base_name, labels):
        """Find rotated versions of a log file.

        Args:
            log_path: Path to the original log file
            base_name: Base name for the log entries
            labels: Labels to apply to the log entries

        Returns:
            int: Number of rotated logs found
        """
        # Skip if the original log path contains wildcards
        if "*" in log_path or "?" in log_path:
            return 0

        rotated_logs_found = 0
        log_dir = os.path.dirname(log_path)
        log_basename = os.path.basename(log_path)

        # Common rotation patterns
        rotation_patterns = [
            f"{log_basename}.*",  # Basic numbered rotation (.1, .2, etc.)
            f"{log_basename}.*.gz",  # Compressed with gzip
            f"{log_basename}.*.bz2",  # Compressed with bzip2
            f"{log_basename}.*.zip",  # Compressed with zip
            f"{log_basename}-*"  # Date-based rotation
        ]

        # Check for each rotation pattern
        if os.path.exists(log_dir):
            for pattern in rotation_patterns:
                rotated_logs = glob.glob(os.path.join(log_dir, pattern))
                for rotated_log in rotated_logs:
                    # Skip the original log
                    if rotated_log == log_path:
                        continue

                    # Skip if already added
                    if self.discoverer.is_log_already_added(rotated_log):
                        continue

                    # Add the rotated log
                    rotation_suffix = os.path.basename(rotated_log).replace(log_basename, '')
                    self.add_log(
                        f"{base_name}_rotated{rotation_suffix}",
                        rotated_log,
                        labels=labels
                    )
                    rotated_logs_found += 1

        return rotated_logs_found


class CyberPanelLogSource(LogSource):
    """Discovery for CyberPanel logs."""

    def discover(self):
        """Discover CyberPanel logs by examining configuration files and known locations."""
        self.discoverer.log("Searching for CyberPanel logs...")

        # Check if CyberPanel is installed
        cyberpanel_dirs = ["/usr/local/CyberCP", "/usr/local/CyberPanel"]
        cyberpanel_installed = any(os.path.exists(d) for d in cyberpanel_dirs)

        if not cyberpanel_installed:
            self.discoverer.log("CyberPanel installation not detected", "INFO")
            return self.logs_found

        # Standard CyberPanel logs
        cyberpanel_logs = [
            ("/var/log/cyberpanel_access_log", "access", "main_access"),
            ("/var/log/cyberpanel_error_log", "error", "main_error"),
            ("/usr/local/CyberCP/debug.log", "debug", "cybercp_debug"),
            ("/var/log/cyberpanel/emailDebug.log", "debug", "email_debug"),
            ("/var/log/cyberpanel/postfix_error.log", "error", "postfix_error"),
            ("/var/log/cyberpanel/install.log", "info", "install"),
            ("/var/log/cyberpanel/mailTransferUtilities.log", "info", "mail_transfer"),
            ("/var/log/pure-ftpd/pureftpd.log", "info", "ftp")
        ]

        # Process each standard log
        for log_path, level, name in cyberpanel_logs:
            if self._file_readable(log_path) or os.path.exists(log_path):
                self.add_log(
                    name,
                    log_path,
                    labels={"level": level, "service": "cyberpanel"}
                )
                self.logs_found += 1

                # Look for rotated logs
                self._find_rotated_logs(log_path, name, {
                    "level": level,
                    "service": "cyberpanel",
                    "rotated": "true"
                })

        # Look for additional logs in CyberPanel directories
        cyberpanel_log_dirs = [
            "/var/log/cyberpanel",
            "/usr/local/CyberCP/logs",
            "/usr/local/CyberCP/debug",
            "/usr/local/CyberPanel/logs",
            "/usr/local/CyberPanel/debug"
        ]

        # Create a set of already processed logs
        processed_logs = {log[0] for log in cyberpanel_logs}

        # Process each log directory
        for log_dir in cyberpanel_log_dirs:
            if os.path.exists(log_dir):
                self.discoverer.log(f"Checking CyberPanel log directory: {log_dir}")

                # Look for all log files and potential rotated logs
                log_patterns = [f"{log_dir}/*.log*"]

                all_logs = []
                for pattern in log_patterns:
                    all_logs.extend(glob.glob(pattern))

                # Process each log file
                for log_file in all_logs:
                    # Skip if already processed
                    if log_file in processed_logs or self.discoverer.is_log_already_added(log_file):
                        continue

                    # Add to processed logs
                    processed_logs.add(log_file)

                    # Extract log name and determine level
                    log_name = os.path.basename(log_file)
                    # Remove rotation suffix if present
                    base_name = re.sub(r'\.(?:gz|bz2|zip|\d+)$', '', log_name)

                    # Determine log level
                    level = "info"
                    if "error" in base_name.lower():
                        level = "error"
                    elif "debug" in base_name.lower():
                        level = "debug"
                    elif "warn" in base_name.lower():
                        level = "warning"

                    # Create sanitized name
                    safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', base_name.replace('.log', ''))

                    self.add_log(
                        f"cp_{safe_name}",
                        log_file,
                        labels={"level": level, "service": "cyberpanel"}
                    )
                    self.logs_found += 1

        return self.logs_found

    def _find_rotated_logs(self, log_path, base_name, labels):
        """Find rotated versions of a log file.

        Args:
            log_path: Path to the original log file
            base_name: Base name for the log entries
            labels: Labels to apply to the log entries

        Returns:
            int: Number of rotated logs found
        """
        # Skip if the original log path contains wildcards
        if "*" in log_path or "?" in log_path:
            return 0

        rotated_logs_found = 0
        log_dir = os.path.dirname(log_path)
        log_basename = os.path.basename(log_path)

        # Common rotation patterns
        rotation_patterns = [
            f"{log_basename}.*",  # Basic numbered rotation (.1, .2, etc.)
            f"{log_basename}.*.gz",  # Compressed with gzip
            f"{log_basename}.*.bz2",  # Compressed with bzip2
            f"{log_basename}.*.zip",  # Compressed with zip
            f"{log_basename}-*"  # Date-based rotation
        ]

        # Check for each rotation pattern
        if os.path.exists(log_dir):
            for pattern in rotation_patterns:
                rotated_logs = glob.glob(os.path.join(log_dir, pattern))
                for rotated_log in rotated_logs:
                    # Skip the original log
                    if rotated_log == log_path:
                        continue

                    # Skip if already added
                    if self.discoverer.is_log_already_added(rotated_log):
                        continue

                    # Add the rotated log
                    rotation_suffix = os.path.basename(rotated_log).replace(log_basename, '')
                    self.add_log(
                        f"{base_name}_rotated{rotation_suffix}",
                        rotated_log,
                        labels=labels
                    )
                    rotated_logs_found += 1

        return rotated_logs_found


class WordPressLogSource(LogSource):
    """Discovery for WordPress logs."""

    def discover(self):
        """Discover WordPress logs by examining wp-config.php files."""
        self.discoverer.log("Searching for WordPress logs...")

        # Find WordPress installations
        wp_config_paths = []

        # Possible WordPress installation paths
        wp_search_paths = [
            "/var/www/html",
            "/var/www",
            "/home/*/public_html",
            "/home/*/www"
        ]

        # Build list of wp-config.php files
        for search_path in wp_search_paths:
            if '*' in search_path:
                # Handle wildcard paths
                base_dir = search_path.split('*')[0]
                if os.path.exists(base_dir):
                    for subdir in os.listdir(base_dir):
                        full_path = search_path.replace('*', subdir)
                        if os.path.exists(full_path):
                            # Look for wp-config.php in this path
                            configs = glob.glob(f"{full_path}/wp-config.php")
                            configs += glob.glob(f"{full_path}/*/wp-config.php")
                            wp_config_paths.extend(configs)
            else:
                # Regular path
                configs = glob.glob(f"{search_path}/wp-config.php")
                configs += glob.glob(f"{search_path}/*/wp-config.php")
                wp_config_paths.extend(configs)

        # Process each WordPress installation in parallel
        with ThreadPoolExecutor(max_workers=min(10, os.cpu_count() * 2)) as executor:
            future_to_config = {executor.submit(self._process_wordpress_site, wp_config): wp_config for wp_config in
                                wp_config_paths}

            for future in as_completed(future_to_config):
                wp_config = future_to_config[future]
                try:
                    logs_found = future.result()
                    self.logs_found += logs_found
                except Exception as e:
                    self.discoverer.log(f"Error processing WordPress config {wp_config}: {str(e)}", "ERROR")

        return self.logs_found

    def _process_wordpress_site(self, wp_config):
        """Process a single WordPress site.

        Args:
            wp_config: Path to the wp-config.php file

        Returns:
            int: Number of logs discovered
        """
        logs_found = 0
        site_path = os.path.dirname(wp_config)
        site_name = self._extract_site_name(site_path)

        self.discoverer.log(f"Processing WordPress site: {site_name} at {site_path}")

        # Extract domain from path if possible
        domain = self._extract_domain_from_path(site_path)

        # Read wp-config.php
        config_content = self._load_file_content(wp_config)
        if not config_content:
            return logs_found

        # Check if debug logging is enabled
        debug_enabled = re.search(r'WP_DEBUG\s*,\s*true', config_content, re.IGNORECASE) is not None

        # Check for custom debug log path
        debug_log_path = None
        debug_log_match = re.search(r'WP_DEBUG_LOG\s*,\s*([\'"])(.*?)\1', config_content)

        if debug_log_match:
            debug_log_path = debug_log_match.group(2)

            # Handle relative paths
            if not os.path.isabs(debug_log_path):
                debug_log_path = os.path.join(site_path, debug_log_path)
        elif debug_enabled:
            # Default debug.log location
            debug_log_path = os.path.join(site_path, 'wp-content/debug.log')

        if debug_log_path:
            self.add_log(
                f"wp_debug_{site_name}",
                debug_log_path,
                labels={
                    "level": "debug",
                    "service": "wordpress",
                    "site": site_name,
                    "domain": domain if domain else ""
                }
            )
            logs_found += 1

            # Look for rotated debug logs
            self._find_rotated_logs(debug_log_path, f"wp_debug_{site_name}", {
                "level": "debug",
                "service": "wordpress",
                "site": site_name,
                "domain": domain if domain else "",
                "rotated": "true"
            })

        # Check for standard error logs in WordPress directory
        wp_error_logs = [
            os.path.join(site_path, 'error_log'),
            os.path.join(site_path, 'php_error.log'),
            os.path.join(site_path, 'wp-content/error.log'),
            # Also check common subdirectories
            os.path.join(site_path, 'wp-content/uploads/error.log'),
            os.path.join(site_path, 'wp-admin/error.log')
        ]

        for log_path in wp_error_logs:
            if os.path.exists(log_path) and not self.discoverer.is_log_already_added(log_path):
                log_name = os.path.basename(log_path).replace('.log', '').replace('_', '')
                self.add_log(
                    f"wp_{log_name}_{site_name}",
                    log_path,
                    labels={
                        "level": "error",
                        "service": "wordpress",
                        "site": site_name,
                        "domain": domain if domain else ""
                    }
                )
                logs_found += 1

                # Look for rotated versions
                self._find_rotated_logs(log_path, f"wp_{log_name}_{site_name}", {
                    "level": "error",
                    "service": "wordpress",
                    "site": site_name,
                    "domain": domain if domain else "",
                    "rotated": "true"
                })

        return logs_found

    def _extract_site_name(self, path):
        """Extract a site name from a path.

        Args:
            path: Site path

        Returns:
            str: Sanitized site name
        """
        # Try to extract meaningful site name from path
        parts = path.split('/')

        # Check for /var/www/html/sitename or /var/www/sitename
        if 'www' in parts:
            idx = parts.index('www')
            if idx + 1 < len(parts):
                if parts[idx + 1] == 'html' and idx + 2 < len(parts):
                    return self._sanitize_name(parts[idx + 2])
                return self._sanitize_name(parts[idx + 1])

        # Check for /home/user/public_html/sitename or /home/user/public_html
        if 'public_html' in parts:
            idx = parts.index('public_html')
            if idx + 1 < len(parts):
                return self._sanitize_name(parts[idx + 1])
            elif idx - 1 >= 0:
                return self._sanitize_name(parts[idx - 1])  # Use username

        # Fallback to last part of path
        site_name = parts[-1]
        if not site_name:  # Handle trailing slash
            site_name = parts[-2]

        return self._sanitize_name(site_name)

    def _sanitize_name(self, name):
        """Create a safe name for use in log identifiers.

        Args:
            name: Original name

        Returns:
            str: Sanitized name
        """
        # Remove special characters and replace with underscores
        return re.sub(r'[^a-zA-Z0-9_]', '_', name)

    def _extract_domain_from_path(self, path):
        """Try to extract a domain name from a path.

        Args:
            path: Site path

        Returns:
            str: Domain name or empty string
        """
        # Look for common domain patterns in the path
        domain_pattern = re.compile(r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}')
        matches = domain_pattern.findall(path)

        if matches:
            return matches[0]

        # Try to find domain from vhost configuration
        try:
            vhost_dirs = [
                "/usr/local/lsws/conf/vhosts",
                "/etc/openlitespeed/vhosts",
                "/etc/apache2/sites-available",
                "/etc/nginx/sites-available"
            ]

            site_name = self._extract_site_name(path)

            for vhost_dir in vhost_dirs:
                if os.path.exists(vhost_dir):
                    vhost_configs = glob.glob(f"{vhost_dir}/{site_name}*.conf")
                    vhost_configs += glob.glob(f"{vhost_dir}/{site_name}")

                    for config in vhost_configs:
                        with open(config, 'r') as f:
                            content = f.read()

                            # Look for ServerName or similar
                            domain_match = re.search(r'(ServerName|domain|vhDomain)\s+([a-zA-Z0-9.-]+)', content)
                            if domain_match:
                                return domain_match.group(2)
        except Exception:
            pass

        return ""

    def _find_rotated_logs(self, log_path, base_name, labels):
        """Find rotated versions of a log file.

        Args:
            log_path: Path to the original log file
            base_name: Base name for the log entries
            labels: Labels to apply to the log entries

        Returns:
            int: Number of rotated logs found
        """
        # Skip if the original log path contains wildcards
        if "*" in log_path or "?" in log_path:
            return 0

        rotated_logs_found = 0
        log_dir = os.path.dirname(log_path)
        log_basename = os.path.basename(log_path)

        # Common rotation patterns
        rotation_patterns = [
            f"{log_basename}.*",  # Basic numbered rotation (.1, .2, etc.)
            f"{log_basename}.*.gz",  # Compressed with gzip
            f"{log_basename}.*.bz2",  # Compressed with bzip2
            f"{log_basename}.*.zip",  # Compressed with zip
            f"{log_basename}-*"  # Date-based rotation
        ]

        # Check for each rotation pattern
        if os.path.exists(log_dir):
            for pattern in rotation_patterns:
                rotated_logs = glob.glob(os.path.join(log_dir, pattern))
                for rotated_log in rotated_logs:
                    # Skip the original log
                    if rotated_log == log_path:
                        continue

                    # Skip if already added
                    if self.discoverer.is_log_already_added(rotated_log):
                        continue

                    # Add the rotated log
                    rotation_suffix = os.path.basename(rotated_log).replace(log_basename, '')
                    self.add_log(
                        f"{base_name}_rotated{rotation_suffix}",
                        rotated_log,
                        labels=labels
                    )
                    rotated_logs_found += 1

        return rotated_logs_found


class PHPLogSource(LogSource):
    """Discovery for PHP logs."""

    def discover(self):
        """Discover PHP logs by examining php.ini files."""
        self.discoverer.log("Searching for PHP logs...")

        # Find PHP configuration
        php_config = None

        # Try to get PHP configuration with php -i
        try:
            # Set timeout for subprocess
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(10)  # 10 second timeout

            php_info = subprocess.check_output("php -i", shell=True).decode()
            signal.alarm(0)  # Disable alarm

            # Extract error_log path
            error_log_match = re.search(r'error_log\s*=>\s*(.+?)\s', php_info)
            if error_log_match:
                php_error_log = error_log_match.group(1)

                if php_error_log and php_error_log != '(None)' and php_error_log != 'no value':
                    self.add_log(
                        "php_error",
                        php_error_log,
                        labels={"level": "error", "service": "php"}
                    )
                    self.logs_found += 1

                    # Look for rotated logs
                    self._find_rotated_logs(php_error_log, "php_error", {
                        "level": "error",
                        "service": "php",
                        "rotated": "true"
                    })
        except Exception as e:
            self.discoverer.log(f"Could not execute 'php -i' to find PHP configuration: {str(e)}", "WARN")
        finally:
            signal.alarm(0)  # Ensure alarm is disabled

        # Look for php.ini files
        php_ini_paths = [
            "/etc/php.ini",
            "/etc/php/*/php.ini",
            "/etc/php/*/cli/php.ini",
            "/etc/php/*/fpm/php.ini",
            "/usr/local/lib/php.ini",
            "/usr/local/etc/php.ini",
            "/usr/local/lsws/lsphp*/etc/php.ini",
            "/opt/alt/php*/etc/php.ini"  # CloudLinux alt-php paths
        ]

        # Process each PHP ini file
        for ini_pattern in php_ini_paths:
            if '*' in ini_pattern:
                # Handle wildcard paths
                ini_files = glob.glob(ini_pattern)
                for ini_file in ini_files:
                    self._process_php_ini(ini_file)
            elif os.path.exists(ini_pattern):
                self._process_php_ini(ini_pattern)

        return self.logs_found

    def _process_php_ini(self, ini_path):
        """Process a PHP ini file to extract log paths.

        Args:
            ini_path: Path to php.ini file

        Returns:
            int: Number of logs discovered
        """
        logs_found = 0
        self.discoverer.log(f"Processing PHP configuration: {ini_path}")

        try:
            # Extract PHP version from path
            php_version = None
            version_match = re.search(r'php/(\d+\.\d+)', ini_path) or re.search(r'php(\d+)', ini_path)
            if version_match:
                php_version = version_match.group(1)

            # Read ini file
            ini_content = self._load_file_content(ini_path)
            if not ini_content:
                return logs_found

            # Extract error_log path
            error_log_match = re.search(r'error_log\s*=\s*(.+?)(?:\s|$)', ini_content)
            if error_log_match:
                error_log = error_log_match.group(1).strip('"\'')

                if error_log and error_log != '(None)' and error_log != 'no value':
                    # Handle syslog directive
                    if error_log.lower() in ('syslog', 'stderr'):
                        if error_log.lower() == 'syslog':
                            self.discoverer.log(f"PHP errors are logged to syslog from {ini_path}", "INFO")
                            # Check for common syslog locations
                            for syslog_path in ["/var/log/syslog", "/var/log/messages"]:
                                if os.path.exists(syslog_path):
                                    self.add_log(
                                        f"php{php_version}_syslog" if php_version else "php_syslog",
                                        syslog_path,
                                        labels={
                                            "level": "error",
                                            "service": "php",
                                            "version": php_version if php_version else "",
                                            "logging": "syslog"
                                        }
                                    )
                                    logs_found += 1
                    else:
                        self.add_log(
                            f"php{php_version}_error" if php_version else "php_error",
                            error_log,
                            labels={
                                "level": "error",
                                "service": "php",
                                "version": php_version if php_version else ""
                            }
                        )
                        logs_found += 1

                        # Look for rotated logs
                        self._find_rotated_logs(error_log, f"php{php_version}_error" if php_version else "php_error", {
                            "level": "error",
                            "service": "php",
                            "version": php_version if php_version else "",
                            "rotated": "true"
                        })

            # For PHP-FPM, also check for slow logs
            if 'fpm' in ini_path and os.path.exists(os.path.dirname(ini_path) + '/php-fpm.conf'):
                fpm_conf = os.path.dirname(ini_path) + '/php-fpm.conf'
                fpm_conf_content = self._load_file_content(fpm_conf)

                if fpm_conf_content:
                    slow_log_match = re.search(r'slowlog\s*=\s*(.+?)(?:\s|$)', fpm_conf_content)
                    if slow_log_match:
                        slow_log = slow_log_match.group(1).strip('"\'')

                        if slow_log and slow_log != '(None)' and slow_log != 'no value':
                            self.add_log(
                                f"php{php_version}_fpm_slow" if php_version else "php_fpm_slow",
                                slow_log,
                                labels={
                                    "level": "slow",
                                    "service": "php-fpm",
                                    "version": php_version if php_version else ""
                                }
                            )
                            logs_found += 1
        except Exception as e:
            self.discoverer.log(f"Error processing {ini_path}: {str(e)}", "ERROR")

        return logs_found

    def _find_rotated_logs(self, log_path, base_name, labels):
        """Find rotated versions of a log file.

        Args:
            log_path: Path to the original log file
            base_name: Base name for the log entries
            labels: Labels to apply to the log entries

        Returns:
            int: Number of rotated logs found
        """
        # Skip if the original log path contains wildcards
        if "*" in log_path or "?" in log_path:
            return 0

        rotated_logs_found = 0
        log_dir = os.path.dirname(log_path)
        log_basename = os.path.basename(log_path)

        # Common rotation patterns
        rotation_patterns = [
            f"{log_basename}.*",  # Basic numbered rotation (.1, .2, etc.)
            f"{log_basename}.*.gz",  # Compressed with gzip
            f"{log_basename}.*.bz2",  # Compressed with bzip2
            f"{log_basename}.*.zip",  # Compressed with zip
            f"{log_basename}-*"  # Date-based rotation
        ]

        # Check for each rotation pattern
        if os.path.exists(log_dir):
            for pattern in rotation_patterns:
                rotated_logs = glob.glob(os.path.join(log_dir, pattern))
                for rotated_log in rotated_logs:
                    # Skip the original log
                    if rotated_log == log_path:
                        continue

                    # Skip if already added
                    if self.discoverer.is_log_already_added(rotated_log):
                        continue

                    # Add the rotated log
                    rotation_suffix = os.path.basename(rotated_log).replace(log_basename, '')
                    self.add_log(
                        f"{base_name}_rotated{rotation_suffix}",
                        rotated_log,
                        labels=labels
                    )
                    rotated_logs_found += 1

        return rotated_logs_found


class MySQLLogSource(LogSource):
    """Discovery for MySQL/MariaDB logs."""

    def discover(self):
        """Discover MySQL/MariaDB logs."""
        self.discoverer.log("Searching for MySQL/MariaDB logs...")

        # First check if MySQL/MariaDB is installed
        mysql_installed = False
        for path in ["/etc/mysql", "/var/lib/mysql", "/etc/my.cnf", "/etc/my.cnf.d"]:
            if os.path.exists(path):
                mysql_installed = True
                break

        if not mysql_installed:
            self.discoverer.log("MySQL/MariaDB installation not detected", "INFO")
            return self.logs_found

        # MySQL config files to check
        mysql_configs = [
            "/etc/my.cnf",
            "/etc/mysql/my.cnf",
            "/usr/local/etc/my.cnf"
        ]

        # Also check for any .cnf files in conf.d directories
        conf_dirs = [
            "/etc/my.cnf.d",
            "/etc/mysql/conf.d",
            "/etc/mysql/mysql.conf.d",
            "/usr/local/etc/my.cnf.d"
        ]

        for conf_dir in conf_dirs:
            if os.path.exists(conf_dir):
                mysql_configs.extend(glob.glob(f"{conf_dir}/*.cnf"))

        # Standard log locations
        standard_logs = [
            "/var/log/mysql/error.log",
            "/var/log/mysql.log",
            "/var/log/mysql.err",
            "/var/log/mysql/mysql.log",
            "/var/log/mysql/mysql-error.log",
            "/var/log/mysqld.log",
            "/var/lib/mysql/*.err"
        ]

        # Check standard log locations first
        for log_pattern in standard_logs:
            if '*' in log_pattern:
                # Handle wildcard paths
                log_files = glob.glob(log_pattern)
                for log_path in log_files:
                    if not self.discoverer.is_log_already_added(log_path):
                        log_type = "error" if "error" in log_path or ".err" in log_path else "general"
                        self.add_log(
                            f"mysql_{log_type}",
                            log_path,
                            labels={"level": log_type, "service": "database"}
                        )
                        self.logs_found += 1

                        # Look for rotated logs
                        self._find_rotated_logs(log_path, f"mysql_{log_type}", {
                            "level": log_type,
                            "service": "database",
                            "rotated": "true"
                        })
            elif os.path.exists(log_pattern):
                log_type = "error" if "error" in log_pattern or ".err" in log_pattern else "general"
                self.add_log(
                    f"mysql_{log_type}",
                    log_pattern,
                    labels={"level": log_type, "service": "database"}
                )
                self.logs_found += 1

                # Look for rotated logs
                self._find_rotated_logs(log_pattern, f"mysql_{log_type}", {
                    "level": log_type,
                    "service": "database",
                    "rotated": "true"
                })

        # Extract log paths from configuration files
        # Use a set to track processed logs and avoid duplicates
        processed_logs = set()

        for config_path in mysql_configs:
            if os.path.exists(config_path):
                self.discoverer.log(f"Processing MySQL config: {config_path}")

                try:
                    # Read config file
                    config_content = self._load_file_content(config_path)
                    if not config_content:
                        continue

                    # Parse with configparser
                    config = configparser.ConfigParser(strict=False)
                    # Prepend a default section for INI files without sections
                    config.read_string('[mysqld]\n' + config_content)

                    # Extract error log path
                    error_log = config.get('mysqld', 'log-error', fallback=None)
                    if error_log and error_log not in processed_logs:
                        processed_logs.add(error_log)
                        self.add_log(
                            "mysql_error",
                            error_log,
                            labels={"level": "error", "service": "database"}
                        )
                        self.logs_found += 1

                        # Look for rotated logs
                        self._find_rotated_logs(error_log, "mysql_error", {
                            "level": "error",
                            "service": "database",
                            "rotated": "true"
                        })

                    # Extract general log path
                    general_log = config.get('mysqld', 'general_log_file', fallback=None)
                    if general_log and general_log not in processed_logs:
                        processed_logs.add(general_log)
                        self.add_log(
                            "mysql_general",
                            general_log,
                            labels={"level": "general", "service": "database"}
                        )
                        self.logs_found += 1

                        # Look for rotated logs
                        self._find_rotated_logs(general_log, "mysql_general", {
                            "level": "general",
                            "service": "database",
                            "rotated": "true"
                        })

                    # Extract slow query log path
                    slow_log = config.get('mysqld', 'slow_query_log_file', fallback=None)
                    if slow_log and slow_log not in processed_logs:
                        processed_logs.add(slow_log)
                        self.add_log(
                            "mysql_slow",
                            slow_log,
                            labels={"level": "slow", "service": "database"}
                        )
                        self.logs_found += 1

                        # Look for rotated logs
                        self._find_rotated_logs(slow_log, "mysql_slow", {
                            "level": "slow",
                            "service": "database",
                            "rotated": "true"
                        })
                except Exception as e:
                    # Fallback to regex parsing if configparser fails
                    try:
                        config_content = self._load_file_content(config_path)
                        if config_content:
                            # Extract error log path
                            error_log_match = re.search(r'log[-_]error\s*=\s*(.+?)(?:\s|$)', config_content)
                            if error_log_match:
                                error_log = error_log_match.group(1).strip('"\'')
                                if error_log and error_log not in processed_logs:
                                    processed_logs.add(error_log)
                                    self.add_log(
                                        "mysql_error",
                                        error_log,
                                        labels={"level": "error", "service": "database"}
                                    )
                                    self.logs_found += 1

                            # Extract general log path
                            general_log_match = re.search(r'general[-_]log[-_]file\s*=\s*(.+?)(?:\s|$)', config_content)
                            if general_log_match:
                                general_log = general_log_match.group(1).strip('"\'')
                                if general_log and general_log not in processed_logs:
                                    processed_logs.add(general_log)
                                    self.add_log(
                                        "mysql_general",
                                        general_log,
                                        labels={"level": "general", "service": "database"}
                                    )
                                    self.logs_found += 1

                            # Extract slow query log path
                            slow_log_match = re.search(r'slow[-_]query[-_]log[-_]file\s*=\s*(.+?)(?:\s|$)',
                                                       config_content)
                            if slow_log_match:
                                slow_log = slow_log_match.group(1).strip('"\'')
                                if slow_log and slow_log not in processed_logs:
                                    processed_logs.add(slow_log)
                                    self.add_log(
                                        "mysql_slow",
                                        slow_log,
                                        labels={"level": "slow", "service": "database"}
                                    )
                                    self.logs_found += 1
                    except Exception as nested_e:
                        self.discoverer.log(f"Error processing {config_path}: {str(nested_e)}", "ERROR")

        return self.logs_found

    def _find_rotated_logs(self, log_path, base_name, labels):
        """Find rotated versions of a log file.

        Args:
            log_path: Path to the original log file
            base_name: Base name for the log entries
            labels: Labels to apply to the log entries

        Returns:
            int: Number of rotated logs found
        """
        # Skip if the original log path contains wildcards
        if "*" in log_path or "?" in log_path:
            return 0

        rotated_logs_found = 0
        log_dir = os.path.dirname(log_path)
        log_basename = os.path.basename(log_path)

        # Common rotation patterns
        rotation_patterns = [
            f"{log_basename}.*",  # Basic numbered rotation (.1, .2, etc.)
            f"{log_basename}.*.gz",  # Compressed with gzip
            f"{log_basename}.*.bz2",  # Compressed with bzip2
            f"{log_basename}.*.zip",  # Compressed with zip
            f"{log_basename}-*"  # Date-based rotation
        ]

        # Check for each rotation pattern
        if os.path.exists(log_dir):
            for pattern in rotation_patterns:
                rotated_logs = glob.glob(os.path.join(log_dir, pattern))
                for rotated_log in rotated_logs:
                    # Skip the original log
                    if rotated_log == log_path:
                        continue

                    # Skip if already added
                    if self.discoverer.is_log_already_added(rotated_log):
                        continue

                    # Add the rotated log
                    rotation_suffix = os.path.basename(rotated_log).replace(log_basename, '')
                    self.add_log(
                        f"{base_name}_rotated{rotation_suffix}",
                        rotated_log,
                        labels=labels
                    )
                    rotated_logs_found += 1

        return rotated_logs_found


class LogDiscoverer:
    """Main class for discovering logs."""

    def __init__(self, verbose=False, include_types=None, exclude_types=None, cache_file=None, timeout=300):
        """Initialize the log discoverer.

        Args:
            verbose: Whether to print verbose logs
            include_types: List of log types to include (None for all)
            exclude_types: List of log types to exclude (None for none)
            cache_file: Path to cache file (None for no caching)
            timeout: Timeout in seconds for the discovery process
        """
        self.verbose = verbose

        # Set up logger
        self.logger = logging.getLogger('log_discovery')
        if verbose:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)

        # Initialize results
        self.discovered_logs = []
        self.log_paths_added = set()  # Track already added log paths

        # Set up cache
        self.cache_file = cache_file
        self.cache = self._load_cache() if cache_file else {}

        # Set up filtering
        self.include_types = include_types
        self.exclude_types = exclude_types

        # Set up timeout
        self.timeout = timeout

    def log(self, message, level="INFO"):
        """Print log messages when verbose is enabled.

        Args:
            message: Log message
            level: Log level (INFO, WARN, ERROR, DEBUG)
        """
        if level == "INFO":
            self.logger.info(message)
        elif level == "WARN":
            self.logger.warning(message)
        elif level == "ERROR":
            self.logger.error(message)
        elif level == "DEBUG":
            self.logger.debug(message)

    def discover_all(self):
        """Run all discovery methods and return results.

        Returns:
            dict: Discovery results
        """
        # Set up timeout
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(self.timeout)

        try:
            # Initialize source classes
            sources = {
                "openlitespeed": OpenLiteSpeedLogSource(self),
                "cyberpanel": CyberPanelLogSource(self),
                "wordpress": WordPressLogSource(self),
                "php": PHPLogSource(self),
                "mysql": MySQLLogSource(self)
            }

            # Filter sources based on include/exclude lists
            if self.include_types:
                sources = {k: v for k, v in sources.items() if k in self.include_types}
            if self.exclude_types:
                sources = {k: v for k, v in sources.items() if k not in self.exclude_types}

            # Run discovery for each source
            for source_name, source in sources.items():
                self.log(f"Starting discovery for {source_name}")
                try:
                    logs_found = source.discover()
                    self.log(f"Discovered {logs_found} logs for {source_name}")
                except Exception as e:
                    self.log(f"Error during {source_name} discovery: {str(e)}", "ERROR")
                    import traceback
                    self.log(traceback.format_exc(), "DEBUG")

            # Update cache
            if self.cache_file:
                self._save_cache()

            # Add metadata
            result = {
                "metadata": {
                    "generated_at": datetime.now().isoformat(),
                    "version": "2.0.0",
                    "hostname": self._get_hostname(),
                    "discovery_time": int(time.time())
                },
                "sources": self.discovered_logs
            }

            signal.alarm(0)  # Disable alarm
            return result

        except TimeoutError:
            self.log("Discovery process timed out", "ERROR")
            # Return partial results
            result = {
                "metadata": {
                    "generated_at": datetime.now().isoformat(),
                    "version": "2.0.0",
                    "hostname": self._get_hostname(),
                    "status": "incomplete",
                    "error": "Timeout during discovery process"
                },
                "sources": self.discovered_logs
            }
            return result
        finally:
            signal.alarm(0)  # Ensure alarm is disabled

    def _get_hostname(self):
        """Get system hostname.

        Returns:
            str: Hostname
        """
        try:
            return subprocess.check_output("hostname", shell=True).decode().strip()
        except:
            return "unknown"

    def _compute_checksum(self, path):
        """Compute checksum of a file.

        Args:
            path: Path to file

        Returns:
            str: SHA-256 checksum or None on error
        """
        if not os.path.exists(path):
            return None

        try:
            # Set timeout for file operations
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(3)  # 3 second timeout

            with open(path, 'rb') as f:
                checksum = hashlib.sha256(f.read()).hexdigest()

            signal.alarm(0)  # Disable alarm
            return checksum
        except (TimeoutError, PermissionError, FileNotFoundError) as e:
            self.log(f"Could not compute checksum for {path}: {str(e)}", "WARN")
            return None
        except Exception as e:
            self.log(f"Unexpected error computing checksum for {path}: {str(e)}", "WARN")
            return None
        finally:
            signal.alarm(0)  # Ensure alarm is disabled

    def _load_cache(self):
        """Load discovery cache from file.

        Returns:
            dict: Cache data or empty dict on error
        """
        if not self.cache_file or not os.path.exists(self.cache_file):
            return {}

        try:
            with open(self.cache_file, 'r') as f:
                cache_data = json.load(f)
                self.log(f"Loaded cache with {len(cache_data.get('sources', []))} entries", "DEBUG")
                return cache_data
        except Exception as e:
            self.log(f"Error loading cache: {str(e)}", "WARN")
            return {}

    def _save_cache(self):
        """Save discovery cache to file."""
        try:
            # Create directory if it doesn't exist
            cache_dir = os.path.dirname(self.cache_file)
            if cache_dir and not os.path.exists(cache_dir):
                os.makedirs(cache_dir)

            # Create a temporary file and use an exclusive lock
            with tempfile.NamedTemporaryFile(mode='w', dir=cache_dir, delete=False) as temp_file:
                fcntl.flock(temp_file.fileno(), fcntl.LOCK_EX)

                # Build cache data
                cache_data = {
                    "metadata": {
                        "generated_at": datetime.now().isoformat(),
                        "version": "2.0.0",
                        "hostname": self._get_hostname()
                    },
                    "sources": self.discovered_logs
                }

                # Write cache data
                json.dump(cache_data, temp_file, indent=2)
                temp_file.flush()
                os.fsync(temp_file.fileno())

                # Release lock
                fcntl.flock(temp_file.fileno(), fcntl.LOCK_UN)

            # Atomically replace the cache file
            os.rename(temp_file.name, self.cache_file)
            self.log(f"Saved cache with {len(self.discovered_logs)} entries", "DEBUG")
        except Exception as e:
            self.log(f"Error saving cache: {str(e)}", "WARN")
            # Clean up temporary file if it exists
            if 'temp_file' in locals():
                try:
                    os.unlink(temp_file.name)
                except:
                    pass

    def add_log_source(self, source_type, name, path, format="text", labels=None, exists=None):
        """Add a discovered log source to the results.

        Args:
            source_type: Type of log source
            name: Name identifier for the log
            path: Path to the log file
            format: Log file format (default: text)
            labels: Dictionary of labels for the log
            exists: Whether the file exists (will check if None)

        Returns:
            dict: The log entry that was added
        """
        if labels is None:
            labels = {}

        # Set default labels based on source type
        if "source" not in labels:
            labels["source"] = source_type

        # Check if path contains wildcards
        has_wildcards = "*" in path or "?" in path

        # Get canonical path if no wildcards
        if not has_wildcards:
            try:
                path = os.path.normpath(path)
            except:
                pass  # Keep the original path if normalization fails

        # Check if file exists if not already provided
        if exists is None and not has_wildcards:
            exists = os.path.exists(path)

        # Skip if already added (to avoid duplicates)
        if not has_wildcards and path in self.log_paths_added:
            self.log(f"Skipping duplicate log: {path}", "DEBUG")
            return None

        # Add to tracking set
        if not has_wildcards:
            self.log_paths_added.add(path)

        # Get last modified time and size if file exists
        last_modified = None
        size = None
        checksum = None

        if exists and not has_wildcards:
            try:
                last_modified = datetime.fromtimestamp(os.path.getmtime(path)).isoformat()
                size = os.path.getsize(path)
                if size < 10 * 1024 * 1024:  # Only compute checksum for files smaller than 10MB
                    checksum = self._compute_checksum(path)
            except Exception as e:
                self.log(f"Error getting file info for {path}: {str(e)}", "DEBUG")

        # Create log entry
        log_entry = {
            "type": source_type,
            "name": name,
            "path": path,
            "format": format,
            "labels": labels,
            "exists": exists
        }

        # Add additional metadata if available
        if last_modified:
            log_entry["last_modified"] = last_modified
        if size is not None:
            log_entry["size"] = size
        if checksum:
            log_entry["checksum"] = checksum

        self.discovered_logs.append(log_entry)

        self.log(f"Discovered {source_type} log: {path} (exists: {exists})")

        return log_entry

    def is_log_already_added(self, path):
        """Check if a log path has already been added.

        Args:
            path: Path to check

        Returns:
            bool: True if already added
        """
        return path in self.log_paths_added


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Enhanced Log Discovery for OpenLiteSpeed/CyberPanel/WordPress")
    parser.add_argument("--output", "-o", help="Output file path (default: stdout)")
    parser.add_argument("--format", "-f", choices=["json", "yaml"], default="json",
                        help="Output format (default: json)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    parser.add_argument("--include", "-i", help="Comma-separated list of log types to include")
    parser.add_argument("--exclude", "-e", help="Comma-separated list of log types to exclude")
    parser.add_argument("--cache-file", "-c", help="Path to cache file")
    parser.add_argument("--timeout", "-t", type=int, default=300, help="Timeout in seconds (default: 300)")
    parser.add_argument("--validate", action="store_true", help="Validate discovered logs by checking permissions")

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Parse include/exclude types
    include_types = None
    if args.include:
        include_types = [t.strip() for t in args.include.split(',')]

    exclude_types = None
    if args.exclude:
        exclude_types = [t.strip() for t in args.exclude.split(',')]

    # Initialize and run discovery
    start_time = time.time()
    discoverer = LogDiscoverer(
        verbose=args.verbose,
        include_types=include_types,
        exclude_types=exclude_types,
        cache_file=args.cache_file,
        timeout=args.timeout
    )

    results = discoverer.discover_all()

    # Add total discovery time to metadata
    results["metadata"]["discovery_time_seconds"] = round(time.time() - start_time, 2)

    # Validate logs if requested
    if args.validate:
        for source in results["sources"]:
            if source["exists"] and os.path.exists(source["path"]):
                source["readable"] = os.access(source["path"], os.R_OK)
            else:
                source["readable"] = False

    # Generate output
    if args.format == "json":
        output = json.dumps(results, indent=2)
    else:  # yaml
        output = yaml.dump(results, default_flow_style=False)

    # Write output
    if args.output:
        try:
            # Create output directory if it doesn't exist
            output_dir = os.path.dirname(args.output)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir)

            # Write to output file
            with open(args.output, 'w') as f:
                f.write(output)
            print(f"Results written to {args.output}")
        except Exception as e:
            print(f"Error writing to {args.output}: {str(e)}", file=sys.stderr)
            sys.exit(1)
    else:
        print(output)


if __name__ == "__main__":
    main()