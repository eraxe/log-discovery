"""
Module for discovering CyberPanel logs.
"""

import os
import re
import glob

# Import the LogSource base class
from log_source import LogSource

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

# Required function to return the log source class
def get_log_source():
    return CyberPanelLogSource