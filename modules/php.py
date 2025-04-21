"""
Module for discovering PHP logs.
"""

import os
import re
import glob
import subprocess

# Import the LogSource base class
from log_source import LogSource, timeout_handler

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

# Import signal after timeout_handler is referenced
import signal

# Required function to return the log source class
def get_log_source():
    return PHPLogSource