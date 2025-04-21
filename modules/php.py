"""
Module for discovering PHP logs.
"""

import os
import re
import glob
import subprocess
import signal

# Import the LogSource base class
from log_source import LogSource, timeout_handler

class PHPLogSource(LogSource):
    """Discovery for PHP logs."""

    def discover(self):
        """Discover PHP logs by examining php.ini files and phpinfo."""
        self.discoverer.log("Searching for PHP logs...")
        logs_found = 0

        # 1. Try to detect all PHP versions installed
        php_versions = self._detect_php_versions()
        self.discoverer.log(f"Detected PHP versions: {php_versions}")

        # 2. For each PHP version, try to find its logs
        for php_version in php_versions:
            logs_found += self._discover_logs_for_version(php_version)

        # 3. Look for PHP-FPM logs
        logs_found += self._discover_php_fpm_logs()

        # 4. Check common PHP log locations as fallback
        logs_found += self._check_common_log_locations()

        # 5. Check for logs from application servers that might run PHP
        logs_found += self._check_app_server_logs()

        return logs_found

    def _detect_php_versions(self):
        """Detect all installed PHP versions.

        Returns:
            list: List of installed PHP versions (e.g., ["7.4", "8.0", "8.1"])
        """
        versions = []

        # Method 1: Check standard PHP version directories
        version_dirs = [
            "/etc/php",
            "/opt/alt/php",  # CloudLinux alt-php paths
            "/opt/cpanel/ea-php",  # cPanel PHP paths
            "/usr/local/lsws/lsphp"  # OpenLiteSpeed PHP paths
        ]

        for base_dir in version_dirs:
            if os.path.exists(base_dir):
                # Look for version subdirectories
                for item in os.listdir(base_dir):
                    if re.match(r'^\d+\.\d+$', item):
                        versions.append(item)
                    elif re.match(r'^\d+$', item):
                        versions.append(f"{item[0]}.{item[1:]}" if len(item) > 1 else item)
                    elif item.startswith('php'):
                        version_match = re.search(r'php(\d+)(?:_(\d+))?', item)
                        if version_match:
                            major = version_match.group(1)
                            minor = version_match.group(2) or '0'
                            versions.append(f"{major}.{minor}")

        # Method 2: Check for PHP binaries in common locations
        php_binaries = []
        for i in range(5, 10):  # PHP 5.x to 9.x
            for j in range(0, 10):  # Minor versions
                php_binaries.append(f"php{i}.{j}")
                php_binaries.append(f"php{i}{j}")

        # Also check for generic php
        php_binaries.append("php")

        # Check if binaries exist in PATH
        paths = ['/usr/bin', '/usr/local/bin', '/opt/cpanel/ea-php*/root/usr/bin',
                 '/opt/alt/php*/usr/bin', '/usr/local/lsws/lsphp*/bin']

        for path_pattern in paths:
            if '*' in path_pattern:
                # Handle wildcard paths
                for path in glob.glob(path_pattern):
                    for binary in php_binaries:
                        if os.path.isfile(f"{path}/{binary}"):
                            try:
                                # Try to get version from binary
                                signal.signal(signal.SIGALRM, timeout_handler)
                                signal.alarm(5)  # 5 second timeout

                                output = subprocess.check_output(f"{path}/{binary} -v",
                                                                shell=True,
                                                                stderr=subprocess.STDOUT).decode()

                                signal.alarm(0)  # Disable alarm

                                version_match = re.search(r'PHP (\d+\.\d+)', output)
                                if version_match:
                                    versions.append(version_match.group(1))
                            except Exception:
                                pass  # Ignore errors
                            finally:
                                signal.alarm(0)  # Ensure alarm is disabled
            else:
                # Regular path
                for binary in php_binaries:
                    binary_path = f"{path_pattern}/{binary}"
                    if os.path.isfile(binary_path):
                        try:
                            # Try to get version from binary
                            signal.signal(signal.SIGALRM, timeout_handler)
                            signal.alarm(5)  # 5 second timeout

                            output = subprocess.check_output(f"{binary_path} -v",
                                                            shell=True,
                                                            stderr=subprocess.STDOUT).decode()

                            signal.alarm(0)  # Disable alarm

                            version_match = re.search(r'PHP (\d+\.\d+)', output)
                            if version_match:
                                versions.append(version_match.group(1))
                        except Exception:
                            pass  # Ignore errors
                        finally:
                            signal.alarm(0)  # Ensure alarm is disabled

        # Remove duplicates and sort
        unique_versions = sorted(list(set(versions)), key=lambda v: [int(x) for x in v.split('.')])

        # If no versions found, add a placeholder for the default PHP
        if not unique_versions:
            unique_versions.append("")

        return unique_versions

    def _discover_logs_for_version(self, version):
        """Discover logs for a specific PHP version.

        Args:
            version: PHP version string (e.g., "7.4")

        Returns:
            int: Number of logs discovered
        """
        logs_found = 0
        version_suffix = version.replace('.', '')

        # 1. Find php.ini files for this version
        ini_paths = []

        # Common PHP ini locations for various distributions and control panels
        ini_patterns = [
            f"/etc/php/{version}/*/php.ini",                  # Debian/Ubuntu style
            f"/etc/php{version}/*/php.ini",                   # Alternative style
            f"/opt/alt/php{version}/etc/php.ini",             # CloudLinux
            f"/opt/cpanel/ea-php{version}/root/etc/php.ini",  # cPanel
            f"/usr/local/lsws/lsphp{version}/etc/php.ini",    # OpenLiteSpeed
            f"/etc/opt/remi/php{version}/php.ini",            # RHEL/CentOS with Remi
            "/etc/php.ini",                                   # Default location
            "/usr/local/lib/php.ini",                         # Common alternative
            "/usr/local/etc/php.ini"                          # Common alternative
        ]

        for pattern in ini_patterns:
            if '*' in pattern:
                # Handle wildcard paths
                ini_paths.extend(glob.glob(pattern))
            elif os.path.exists(pattern):
                ini_paths.append(pattern)

        # 2. Process each php.ini file
        for ini_path in ini_paths:
            self.discoverer.log(f"Processing PHP{version} ini: {ini_path}")

            # Read ini file
            ini_content = self._load_file_content(ini_path)
            if not ini_content:
                continue

            # Look for error_log setting
            error_log_match = re.search(r'error_log\s*=\s*(.+?)(?:\s|$)', ini_content)
            if error_log_match:
                error_log = error_log_match.group(1).strip('"\'')

                if error_log and error_log not in ('no', 'syslog', 'stderr'):
                    # Add the log
                    name_prefix = f"php{version_suffix}_" if version else "php_"
                    self.add_log(
                        f"{name_prefix}error",
                        error_log,
                        labels={
                            "level": "error",
                            "service": "php",
                            "version": version if version else "",
                            "config_file": ini_path
                        }
                    )
                    logs_found += 1

                    # Look for rotated logs
                    self._find_rotated_logs(error_log, f"{name_prefix}error", {
                        "level": "error",
                        "service": "php",
                        "version": version if version else "",
                        "rotated": "true",
                        "config_file": ini_path
                    })
                elif error_log == 'syslog':
                    # Check for syslog
                    for syslog_path in ["/var/log/syslog", "/var/log/messages"]:
                        if os.path.exists(syslog_path):
                            self.add_log(
                                f"php{version_suffix}_syslog" if version else "php_syslog",
                                syslog_path,
                                labels={
                                    "level": "error",
                                    "service": "php",
                                    "version": version if version else "",
                                    "logging": "syslog",
                                    "config_file": ini_path
                                }
                            )
                            logs_found += 1

            # Also check for error_reporting and log_errors settings
            error_reporting_on = True
            log_errors_on = True

            error_reporting_match = re.search(r'error_reporting\s*=\s*(.+?)(?:\s|$)', ini_content)
            if error_reporting_match:
                # Check if errors are completely disabled (rarely the case)
                value = error_reporting_match.group(1).strip()
                if value == '0' or value == 'Off' or value == 'off' or value == 'none':
                    error_reporting_on = False

            log_errors_match = re.search(r'log_errors\s*=\s*(.+?)(?:\s|$)', ini_content)
            if log_errors_match:
                value = log_errors_match.group(1).strip().lower()
                if value in ('off', '0', 'false', 'no'):
                    log_errors_on = False

            # Log warning if error logging is disabled
            if not error_reporting_on or not log_errors_on:
                self.discoverer.log(f"Warning: PHP error logging may be disabled in {ini_path}", "WARN")

        return logs_found

    def _discover_php_fpm_logs(self):
        """Discover PHP-FPM logs.

        Returns:
            int: Number of logs discovered
        """
        logs_found = 0

        # 1. Find PHP-FPM configuration files
        fpm_configs = []
        fpm_config_patterns = [
            "/etc/php/*/fpm/php-fpm.conf",
            "/etc/php-fpm.conf",
            "/etc/php-fpm.d/*.conf",
            "/etc/php/*/fpm/pool.d/*.conf",
            "/opt/alt/php*/etc/php-fpm.conf",
            "/usr/local/etc/php-fpm.conf",
            "/etc/opt/remi/php*/php-fpm.conf"
        ]

        for pattern in fpm_config_patterns:
            fpm_configs.extend(glob.glob(pattern))

        # 2. Process each FPM config
        for config_path in fpm_configs:
            self.discoverer.log(f"Processing PHP-FPM config: {config_path}")

            # Extract version if possible
            version = ""
            version_match = re.search(r'php/(\d+\.\d+)', config_path) or re.search(r'php(\d+)', config_path)
            if version_match:
                version = version_match.group(1)

            version_suffix = version.replace('.', '') if version else ""

            # Read config file
            config_content = self._load_file_content(config_path)
            if not config_content:
                continue

            # Look for error_log setting
            error_log_match = re.search(r'error_log\s*=\s*(.+?)(?:\s|$)', config_content)
            if error_log_match:
                error_log = error_log_match.group(1).strip('"\'')

                if error_log and error_log not in ('no', 'syslog', 'stderr'):
                    # Add the log
                    name_prefix = f"php{version_suffix}_fpm_" if version else "php_fpm_"
                    self.add_log(
                        f"{name_prefix}error",
                        error_log,
                        labels={
                            "level": "error",
                            "service": "php-fpm",
                            "version": version if version else "",
                            "config_file": config_path
                        }
                    )
                    logs_found += 1

                    # Look for rotated logs
                    self._find_rotated_logs(error_log, f"{name_prefix}error", {
                        "level": "error",
                        "service": "php-fpm",
                        "version": version if version else "",
                        "rotated": "true",
                        "config_file": config_path
                    })

            # Look for slow_log setting
            slow_log_match = re.search(r'slowlog\s*=\s*(.+?)(?:\s|$)', config_content)
            if slow_log_match:
                slow_log = slow_log_match.group(1).strip('"\'')

                if slow_log and slow_log not in ('no', 'syslog', 'stderr'):
                    # Add the log
                    name_prefix = f"php{version_suffix}_fpm_" if version else "php_fpm_"
                    self.add_log(
                        f"{name_prefix}slow",
                        slow_log,
                        labels={
                            "level": "slow",
                            "service": "php-fpm",
                            "version": version if version else "",
                            "config_file": config_path
                        }
                    )
                    logs_found += 1

                    # Look for rotated logs
                    self._find_rotated_logs(slow_log, f"{name_prefix}slow", {
                        "level": "slow",
                        "service": "php-fpm",
                        "version": version if version else "",
                        "rotated": "true",
                        "config_file": config_path
                    })

            # Look for access_log setting (PHP-FPM 7.1+)
            access_log_match = re.search(r'access\.log\s*=\s*(.+?)(?:\s|$)', config_content)
            if access_log_match:
                access_log = access_log_match.group(1).strip('"\'')

                if access_log and access_log not in ('no', 'syslog', 'stderr'):
                    # Add the log
                    name_prefix = f"php{version_suffix}_fpm_" if version else "php_fpm_"
                    self.add_log(
                        f"{name_prefix}access",
                        access_log,
                        labels={
                            "level": "access",
                            "service": "php-fpm",
                            "version": version if version else "",
                            "config_file": config_path
                        }
                    )
                    logs_found += 1

                    # Look for rotated logs
                    self._find_rotated_logs(access_log, f"{name_prefix}access", {
                        "level": "access",
                        "service": "php-fpm",
                        "version": version if version else "",
                        "rotated": "true",
                        "config_file": config_path
                    })

        return logs_found

    def _check_common_log_locations(self):
        """Check common PHP log locations.

        Returns:
            int: Number of logs discovered
        """
        logs_found = 0

        # Common locations for PHP logs
        common_locations = [
            "/var/log/php_errors.log",
            "/var/log/php-fpm/error.log",
            "/var/log/php-fpm/www-error.log",
            "/var/log/php-fpm/www-slow.log",
            "/var/log/php*/error.log",
            "/var/log/php-fpm*/error.log",
            "/var/log/httpd/php_errors.log",
            "/var/log/nginx/php_errors.log",
            "/var/log/apache2/php_errors.log",
            "/var/log/php/error.log",
            "/var/log/php-fpm.log"
        ]

        for location in common_locations:
            if '*' in location:
                # Handle wildcard paths
                for log_path in glob.glob(location):
                    if not self.discoverer.is_log_already_added(log_path):
                        # Extract version if possible
                        version = ""
                        version_match = re.search(r'php(\d+(?:\.\d+)?)', log_path)
                        if version_match:
                            version = version_match.group(1)

                        # Determine log type
                        log_type = "error"
                        if "slow" in log_path:
                            log_type = "slow"
                        elif "access" in log_path:
                            log_type = "access"

                        # Determine service
                        service = "php"
                        if "fpm" in log_path:
                            service = "php-fpm"

                        # Add the log
                        version_suffix = version.replace('.', '') if version else ""
                        name_prefix = f"php{version_suffix}_" if version else "php_"

                        self.add_log(
                            f"{name_prefix}{log_type}",
                            log_path,
                            labels={
                                "level": log_type,
                                "service": service,
                                "version": version if version else "",
                                "source": "common_location"
                            }
                        )
                        logs_found += 1
            elif os.path.exists(location) and not self.discoverer.is_log_already_added(location):
                # Extract version if possible
                version = ""
                version_match = re.search(r'php(\d+(?:\.\d+)?)', location)
                if version_match:
                    version = version_match.group(1)

                # Determine log type
                log_type = "error"
                if "slow" in location:
                    log_type = "slow"
                elif "access" in location:
                    log_type = "access"

                # Determine service
                service = "php"
                if "fpm" in location:
                    service = "php-fpm"

                # Add the log
                version_suffix = version.replace('.', '') if version else ""
                name_prefix = f"php{version_suffix}_" if version else "php_"

                self.add_log(
                    f"{name_prefix}{log_type}",
                    location,
                    labels={
                        "level": log_type,
                        "service": service,
                        "version": version if version else "",
                        "source": "common_location"
                    }
                )
                logs_found += 1

        return logs_found

    def _check_app_server_logs(self):
        """Check for PHP logs in application server directories.

        Returns:
            int: Number of logs discovered
        """
        logs_found = 0

        # Common application server log paths that might contain PHP logs
        app_server_paths = [
            # OpenLiteSpeed
            "/usr/local/lsws/logs/php_error*",
            "/usr/local/lsws/logs/*php*.log",
            # Apache
            "/var/log/httpd/*php*.log",
            "/var/log/apache2/*php*.log",
            # Nginx
            "/var/log/nginx/*php*.log"
        ]

        for path_pattern in app_server_paths:
            for log_path in glob.glob(path_pattern):
                if not self.discoverer.is_log_already_added(log_path):
                    # Extract version if possible
                    version = ""
                    version_match = re.search(r'php(\d+(?:\.\d+)?)', log_path)
                    if version_match:
                        version = version_match.group(1)

                    # Determine log type
                    log_type = "error"
                    if "slow" in log_path:
                        log_type = "slow"
                    elif "access" in log_path:
                        log_type = "access"

                    # Add the log
                    version_suffix = version.replace('.', '') if version else ""
                    name_prefix = f"php{version_suffix}_" if version else "php_"

                    self.add_log(
                        f"{name_prefix}{log_type}_app_server",
                        log_path,
                        labels={
                            "level": log_type,
                            "service": "php",
                            "version": version if version else "",
                            "source": "app_server"
                        }
                    )
                    logs_found += 1

        return logs_found

# Required function to return the log source class
def get_log_source():
    return PHPLogSource