"""
Module for discovering OpenLiteSpeed logs.
"""

import os
import re
import glob
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import the LogSource base class
from log_source import LogSource

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

# Required function to return the log source class
def get_log_source():
    return OpenLiteSpeedLogSource