"""
Module for discovering MySQL/MariaDB logs.
"""

import os
import re
import glob  # Explicitly import glob here as well
import configparser
import threading  # Added for thread-safe operations

# Import the LogSource base class
from log_source import LogSource

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
                        self.logs_found += self._find_rotated_logs(log_path, f"mysql_{log_type}", {
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
                self.logs_found += self._find_rotated_logs(log_pattern, f"mysql_{log_type}", {
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
                    # Read config file using thread-safe method
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
                        self.logs_found += self._find_rotated_logs(error_log, "mysql_error", {
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
                        self.logs_found += self._find_rotated_logs(general_log, "mysql_general", {
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
                        self.logs_found += self._find_rotated_logs(slow_log, "mysql_slow", {
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

                                    # Look for rotated logs
                                    self.logs_found += self._find_rotated_logs(error_log, "mysql_error", {
                                        "level": "error",
                                        "service": "database",
                                        "rotated": "true"
                                    })

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

                                    # Look for rotated logs
                                    self.logs_found += self._find_rotated_logs(general_log, "mysql_general", {
                                        "level": "general",
                                        "service": "database",
                                        "rotated": "true"
                                    })

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

                                    # Look for rotated logs
                                    self.logs_found += self._find_rotated_logs(slow_log, "mysql_slow", {
                                        "level": "slow",
                                        "service": "database",
                                        "rotated": "true"
                                    })
                    except Exception as nested_e:
                        self.discoverer.log(f"Error processing {config_path}: {str(nested_e)}", "ERROR")

        return self.logs_found

# Required function to return the log source class
def get_log_source():
    return MySQLLogSource