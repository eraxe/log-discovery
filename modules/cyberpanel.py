"""
Module for discovering CyberPanel logs.
"""

import os
import re
import glob
import json
import subprocess
import signal

# Import the LogSource base class
from log_source import LogSource, timeout_handler

class CyberPanelLogSource(LogSource):
    """Discovery for CyberPanel logs."""

    def discover(self):
        """Discover CyberPanel logs by examining configuration files and known locations."""
        self.discoverer.log("Searching for CyberPanel logs...")

        # Check if CyberPanel is installed using multiple methods
        cyberpanel_installed = self._is_cyberpanel_installed()

        if not cyberpanel_installed:
            self.discoverer.log("CyberPanel installation not detected", "INFO")
            return self.logs_found

        # Get CyberPanel installation details
        cyberpanel_info = self._get_cyberpanel_info()

        # Track logs by category
        cyberpanel_logs = []
        email_logs = []
        ftp_logs = []
        database_logs = []
        webserver_logs = []
        backup_logs = []
        ssl_logs = []
        general_logs = []

        # ===== 1. Standard CyberPanel logs =====
        cyberpanel_logs.extend([
            ("/var/log/cyberpanel_access_log", "access", "main_access"),
            ("/var/log/cyberpanel_error_log", "error", "main_error"),
            ("/usr/local/CyberCP/debug.log", "debug", "cybercp_debug"),
            ("/usr/local/CyberCP/logs/job_logs.txt", "info", "job_logs"),
            ("/var/log/cyberpanel.log", "info", "main"),
            ("/var/log/cyberpanel/install.log", "info", "install"),
        ])

        # ===== 2. Email related logs =====
        email_logs.extend([
            ("/var/log/cyberpanel/emailDebug.log", "debug", "email_debug"),
            ("/var/log/cyberpanel/postfix_error.log", "error", "postfix_error"),
            ("/var/log/cyberpanel/mailTransferUtilities.log", "info", "mail_transfer"),
            ("/var/log/maillog", "info", "mail"),
            ("/var/log/mail.log", "info", "mail"),
            ("/var/log/mail/mail.log", "info", "mail"),
            ("/var/log/dovecot.log", "info", "dovecot"),
            ("/var/log/mail.err", "error", "mail_error"),
            ("/var/log/dovecot-info.log", "info", "dovecot_info"),
            ("/var/log/mail.info", "info", "mail_info"),
            ("/var/log/mail.warn", "warning", "mail_warning"),
        ])

        # ===== 3. FTP logs =====
        ftp_logs.extend([
            ("/var/log/pure-ftpd/pure-ftpd.log", "info", "ftp"),
            ("/var/log/pureftpd.log", "info", "ftp"),
            ("/var/log/vsftpd.log", "info", "vsftpd"),
        ])

        # ===== 4. Database logs =====
        database_logs.extend([
            ("/var/log/mysql/error.log", "error", "mysql_error"),
            ("/var/log/mysql.err", "error", "mysql_error"),
            ("/var/log/mysql.log", "info", "mysql"),
            ("/var/log/mariadb/mariadb.log", "info", "mariadb"),
            ("/var/log/mariadb/mariadb.err", "error", "mariadb_error"),
        ])

        # ===== 5. Web server logs (OpenLiteSpeed/others) =====
        webserver_logs.extend([
            ("/usr/local/lsws/logs/error.log", "error", "litespeed_error"),
            ("/usr/local/lsws/logs/access.log", "access", "litespeed_access"),
            ("/usr/local/lsws/logs/stderr.log", "error", "litespeed_stderr"),
        ])

        # ===== 6. Backup logs =====
        backup_logs.extend([
            ("/var/log/cyberpanel/backup_log.txt", "info", "backup"),
            ("/var/log/cyberpanel/backups.log", "info", "backups"),
            ("/var/log/cyberpanel/jobLogs.txt", "info", "backup_jobs"),
            ("/var/log/cyberpanel/backup_cron.log", "info", "backup_cron"),
        ])

        # ===== 7. SSL logs =====
        ssl_logs.extend([
            ("/var/log/cyberpanel/acme.log", "info", "acme"),
            ("/var/log/cyberpanel/lets_encrypt.log", "info", "lets_encrypt"),
            ("/var/log/cyberpanel/ssl.log", "info", "ssl"),
        ])

        # ===== 8. General logs that might be useful =====
        general_logs.extend([
            ("/var/log/cyberpanel/firewall.log", "info", "firewall"),
            ("/var/log/cyberpanel/auth.log", "info", "auth"),
            ("/var/log/cyberpanel/access.log", "access", "access"),
            ("/var/log/cyberpanel/error.log", "error", "error"),
        ])

        # Process each log category
        all_logs = [
            (cyberpanel_logs, "cyberpanel"),
            (email_logs, "email"),
            (ftp_logs, "ftp"),
            (database_logs, "database"),
            (webserver_logs, "webserver"),
            (backup_logs, "backup"),
            (ssl_logs, "ssl"),
            (general_logs, "system")
        ]

        for logs, category in all_logs:
            self._process_log_group(logs, category)

        # Look for additional logs in CyberPanel directories
        self._scan_cyberpanel_directories()

        # Look for website specific logs managed by CyberPanel
        self._scan_websites_logs()

        # Look for custom log locations defined in CyberPanel configuration
        self._scan_custom_log_locations()

        return self.logs_found

    def _is_cyberpanel_installed(self):
        """Check if CyberPanel is installed using multiple methods.

        Returns:
            bool: True if CyberPanel is installed
        """
        # Method 1: Check common installation directories
        cyberpanel_dirs = [
            "/usr/local/CyberCP",
            "/usr/local/CyberPanel",
            "/etc/cyberpanel"
        ]

        if any(os.path.exists(d) for d in cyberpanel_dirs):
            return True

        # Method 2: Check for CyberPanel processes
        try:
            # Use timeout to avoid hanging
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(5)  # 5 second timeout

            output = subprocess.check_output("ps aux | grep -i cyberpanel | grep -v grep",
                                          shell=True, stderr=subprocess.STDOUT).decode()

            signal.alarm(0)  # Disable alarm

            if output and len(output.strip()) > 0:
                return True
        except Exception:
            pass  # Ignore errors
        finally:
            signal.alarm(0)  # Ensure alarm is disabled

        # Method 3: Check for CyberPanel service
        try:
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(5)  # 5 second timeout

            output = subprocess.check_output("systemctl list-units --type=service | grep -i cyberpanel",
                                          shell=True, stderr=subprocess.STDOUT).decode()

            signal.alarm(0)  # Disable alarm

            if output and len(output.strip()) > 0:
                return True
        except Exception:
            pass  # Ignore errors
        finally:
            signal.alarm(0)  # Ensure alarm is disabled

        # Method 4: Check for cyberpanel command
        try:
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(5)  # 5 second timeout

            output = subprocess.check_output("which cyberpanel",
                                          shell=True, stderr=subprocess.STDOUT).decode()

            signal.alarm(0)  # Disable alarm

            if "cyberpanel" in output:
                return True
        except Exception:
            pass  # Ignore errors
        finally:
            signal.alarm(0)  # Ensure alarm is disabled

        return False

    def _get_cyberpanel_info(self):
        """Get CyberPanel installation information.

        Returns:
            dict: Information about CyberPanel installation
        """
        info = {
            "version": "unknown",
            "install_path": "/usr/local/CyberCP",
            "config_path": "/etc/cyberpanel",
            "web_server": "openlitespeed",
            "paths": {
                "logs": "/var/log/cyberpanel",
                "websites": "/home",
                "backup": "/home/backup"
            }
        }

        # Try to get version info
        version_files = [
            "/usr/local/CyberCP/version.txt",
            "/usr/local/CyberPanel/version.txt",
            "/etc/cyberpanel/version"
        ]

        for file in version_files:
            if os.path.exists(file):
                try:
                    with open(file, 'r') as f:
                        content = f.read().strip()
                        if content:
                            info["version"] = content
                            break
                except Exception:
                    pass

        # Detect web server
        if os.path.exists("/usr/local/lsws"):
            info["web_server"] = "openlitespeed"
        elif os.path.exists("/etc/apache2"):
            info["web_server"] = "apache"
        elif os.path.exists("/etc/nginx"):
            info["web_server"] = "nginx"

        # Look for main configuration file
        config_files = [
            "/etc/cyberpanel/cyberpanel.conf",
            "/usr/local/CyberCP/CyberCP/settings.py",
            "/usr/local/CyberPanel/CyberCP/settings.py"
        ]

        for file in config_files:
            if os.path.exists(file):
                content = self._load_file_content(file)

                # Try to extract paths from config
                if file.endswith(".py"):
                    # For Django settings.py
                    log_path_match = re.search(r'LOG_DIR\s*=\s*[\'"]([^\'"]+)[\'"]', content)
                    if log_path_match:
                        info["paths"]["logs"] = log_path_match.group(1)

                    backup_path_match = re.search(r'BACKUP_DIR\s*=\s*[\'"]([^\'"]+)[\'"]', content)
                    if backup_path_match:
                        info["paths"]["backup"] = backup_path_match.group(1)
                else:
                    # For INI-style configs
                    log_path_match = re.search(r'log[_\s]dir\s*=\s*(.+)', content, re.MULTILINE | re.IGNORECASE)
                    if log_path_match:
                        info["paths"]["logs"] = log_path_match.group(1).strip()

                    backup_path_match = re.search(r'backup[_\s]dir\s*=\s*(.+)', content, re.MULTILINE | re.IGNORECASE)
                    if backup_path_match:
                        info["paths"]["backup"] = backup_path_match.group(1).strip()

        return info

    def _process_log_group(self, logs, category):
        """Process a group of logs.

        Args:
            logs: List of (path, level, name) tuples
            category: Category name for these logs
        """
        # Create a set of already processed logs
        processed_logs = set()

        # Process each log
        for log_path, level, name in logs:
            # Handle wildcard paths
            if '*' in log_path:
                for matched_path in glob.glob(log_path):
                    if matched_path not in processed_logs and not self.discoverer.is_log_already_added(matched_path):
                        processed_logs.add(matched_path)

                        # Create a unique name for this log
                        unique_name = f"{name}_{os.path.basename(matched_path)}"

                        self.add_log(
                            unique_name,
                            matched_path,
                            labels={"level": level, "service": "cyberpanel", "category": category}
                        )
                        self.logs_found += 1

                        # Look for rotated logs
                        self._find_rotated_logs(matched_path, unique_name, {
                            "level": level,
                            "service": "cyberpanel",
                            "category": category,
                            "rotated": "true"
                        })
            elif self._file_readable(log_path) or os.path.exists(log_path):
                if log_path not in processed_logs and not self.discoverer.is_log_already_added(log_path):
                    processed_logs.add(log_path)

                    self.add_log(
                        name,
                        log_path,
                        labels={"level": level, "service": "cyberpanel", "category": category}
                    )
                    self.logs_found += 1

                    # Look for rotated logs
                    self._find_rotated_logs(log_path, name, {
                        "level": level,
                        "service": "cyberpanel",
                        "category": category,
                        "rotated": "true"
                    })

    def _scan_cyberpanel_directories(self):
        """Scan CyberPanel directories for additional logs."""
        # Define directories to scan
        cyberpanel_log_dirs = [
            "/var/log/cyberpanel",
            "/usr/local/CyberCP/logs",
            "/usr/local/CyberCP/debug",
            "/usr/local/CyberPanel/logs",
            "/usr/local/CyberPanel/debug",
            "/var/log/cyberpanel_logs"
        ]

        # Create a set of already processed logs
        processed_logs = set()

        # Process each log directory
        for log_dir in cyberpanel_log_dirs:
            if os.path.exists(log_dir) and os.path.isdir(log_dir):
                self.discoverer.log(f"Checking CyberPanel log directory: {log_dir}")

                # Find all log files and potential rotated logs in the directory (recursive)
                try:
                    signal.signal(signal.SIGALRM, timeout_handler)
                    signal.alarm(15)  # 15 second timeout

                    # Find all *.log* and other common log file extensions
                    log_patterns = [
                        f"{log_dir}/**/*.log*",
                        f"{log_dir}/**/*.txt",
                        f"{log_dir}/**/*.err*",
                        f"{log_dir}/**/*.debug*",
                        f"{log_dir}/**/*.out*"
                    ]

                    all_logs = []
                    for pattern in log_patterns:
                        all_logs.extend(glob.glob(pattern, recursive=True))

                    signal.alarm(0)  # Disable alarm

                    # Process each log file
                    for log_file in set(all_logs):  # Use set to remove duplicates
                        # Skip if already processed
                        if log_file in processed_logs or self.discoverer.is_log_already_added(log_file):
                            continue

                        # Add to processed logs
                        processed_logs.add(log_file)

                        # Extract log name and determine level
                        log_name = os.path.basename(log_file)

                        # Remove rotation suffix if present
                        base_name = re.sub(r'\.(?:gz|bz2|zip|\d+)', '', log_name)

                        # Determine log level
                        level = "info"
                        if "error" in base_name.lower():
                            level = "error"
                        elif "debug" in base_name.lower():
                            level = "debug"
                        elif "warn" in base_name.lower():
                            level = "warning"
                        elif "access" in base_name.lower():
                            level = "access"

                        # Determine category based on path or filename
                        category = "general"
                        if "email" in log_file or "mail" in log_file:
                            category = "email"
                        elif "backup" in log_file:
                            category = "backup"
                        elif "ssl" in log_file or "lets" in log_file or "cert" in log_file:
                            category = "ssl"
                        elif "ftp" in log_file:
                            category = "ftp"
                        elif "database" in log_file or "mysql" in log_file or "sql" in log_file:
                            category = "database"

                        # Create sanitized name
                        safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', base_name.replace('.log', ''))

                        self.add_log(
                            f"cp_{safe_name}",
                            log_file,
                            labels={
                                "level": level,
                                "service": "cyberpanel",
                                "category": category,
                                "path": os.path.relpath(log_file, log_dir)
                            }
                        )
                        self.logs_found += 1
                except Exception as e:
                    self.discoverer.log(f"Error scanning directory {log_dir}: {str(e)}", "WARN")
                finally:
                    signal.alarm(0)  # Ensure alarm is disabled

    def _scan_websites_logs(self):
        """Scan CyberPanel managed websites for logs."""
        # Try to get list of websites from CyberPanel configuration
        websites = self._get_cyberpanel_websites()

        # If websites were found, process each one
        if websites:
            for website in websites:
                self._process_website_logs(website)
        else:
            # Fallback to scanning common website paths
            self._scan_common_website_paths()

    def _get_cyberpanel_websites(self):
        """Get list of websites managed by CyberPanel.

        Returns:
            list: List of website dictionaries with path, domain, etc.
        """
        websites = []

        # Method 1: Try to read CyberPanel's websites.json file
        websites_files = [
            "/etc/cyberpanel/websites.json",
            "/usr/local/CyberCP/websites.json",
            "/usr/local/CyberPanel/websites.json",
            "/home/cyberpanel/websites.json"
        ]

        for file in websites_files:
            if os.path.exists(file):
                try:
                    with open(file, 'r') as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            websites.extend(data)
                        elif isinstance(data, dict) and "websites" in data:
                            websites.extend(data["websites"])
                        break
                except Exception as e:
                    self.discoverer.log(f"Error reading websites file {file}: {str(e)}", "DEBUG")

        # Method 2: Try to get websites from OpenLiteSpeed config
        if not websites:
            vhost_dirs = [
                "/usr/local/lsws/conf/vhosts",
                "/etc/openlitespeed/vhosts"
            ]

            for vhost_dir in vhost_dirs:
                if os.path.exists(vhost_dir) and os.path.isdir(vhost_dir):
                    for vhost in os.listdir(vhost_dir):
                        vhost_path = os.path.join(vhost_dir, vhost)

                        if os.path.isdir(vhost_path):
                            # Read vhconf.conf to get docRoot
                            vhost_conf = os.path.join(vhost_path, "vhconf.conf")

                            if os.path.exists(vhost_conf):
                                content = self._load_file_content(vhost_conf)
                                if content:
                                    # Extract docRoot
                                    doc_root_match = re.search(r'docRoot\s+(.+)', content, re.MULTILINE)
                                    if doc_root_match:
                                        doc_root = doc_root_match.group(1).strip()

                                        websites.append({
                                            "domain": vhost,
                                            "path": doc_root
                                        })

        # Method 3: Try to get websites from home directories
        if not websites:
            home_dir = "/home"
            if os.path.exists(home_dir) and os.path.isdir(home_dir):
                for user in os.listdir(home_dir):
                    user_dir = os.path.join(home_dir, user)

                    if os.path.isdir(user_dir) and not user.startswith('.'):
                        # Check if this looks like a website
                        for web_dir in ["public_html", "public_html"]:
                            web_path = os.path.join(user_dir, web_dir)

                            if os.path.exists(web_path) and os.path.isdir(web_path):
                                websites.append({
                                    "domain": user,
                                    "path": web_path
                                })
                                break

        return websites

    def _process_website_logs(self, website):
        """Process logs for a specific website.

        Args:
            website: Dictionary with website information
        """
        domain = website.get("domain", "unknown")
        path = website.get("path", "")

        if not path or not os.path.exists(path):
            return

        self.discoverer.log(f"Processing website logs for {domain} at {path}")

        # Look for common log locations for this website
        log_paths = [
            # Web server logs
            f"/usr/local/lsws/logs/{domain}*.log",
            f"/usr/local/lsws/logs/vhosts/{domain}/*.log",
            f"/var/log/openlitespeed/{domain}*.log",
            f"/var/log/apache2/{domain}*.log",
            f"/var/log/nginx/{domain}*.log",

            # Website logs
            f"{path}/logs/*.log",
            f"{path}/log/*.log",
            f"{path}/error_log",
            f"{path}/access_log",

            # Application logs
            f"{path}/error.log",
            f"{path}/debug.log",
            f"{path}/application.log",

            # PHP logs
            f"{path}/php_error.log",
            f"{path}/php_errors.log",
            f"{path}/php.log"
        ]

        # Process each log pattern
        for log_pattern in log_paths:
            for log_path in glob.glob(log_pattern):
                if not self.discoverer.is_log_already_added(log_path):
                    # Determine log level
                    level = "info"
                    if "error" in log_path.lower():
                        level = "error"
                    elif "debug" in log_path.lower():
                        level = "debug"
                    elif "access" in log_path.lower():
                        level = "access"

                    # Create a unique name
                    log_name = os.path.basename(log_path)
                    safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', log_name.replace('.log', ''))

                    self.add_log(
                        f"website_{safe_name}_{domain}",
                        log_path,
                        labels={
                            "level": level,
                            "service": "cyberpanel",
                            "category": "website",
                            "domain": domain,
                            "website_path": path,
                            "source": "website"
                        }
                    )
                    self.logs_found += 1

                    # Look for rotated logs
                    self._find_rotated_logs(log_path, f"website_{safe_name}_{domain}", {
                        "level": level,
                        "service": "cyberpanel",
                        "category": "website",
                        "domain": domain,
                        "website_path": path,
                        "source": "website",
                        "rotated": "true"
                    })

    def _scan_common_website_paths(self):
        """Scan common website paths for logs when website list is unavailable."""
        # Common website paths
        website_paths = [
            "/home/*/public_html",
            "/var/www/vhosts/*",
            "/var/www/html/*"
        ]

        for path_pattern in website_paths:
            for website_path in glob.glob(path_pattern):
                # Skip paths that are clearly not websites
                if os.path.basename(website_path).startswith('.'):
                    continue

                # Try to determine domain name
                domain = os.path.basename(website_path)
                if domain == "public_html":
                    # Use parent directory name for cPanel-style domains
                    domain = os.path.basename(os.path.dirname(website_path))

                # Create a website object and process it
                website = {
                    "domain": domain,
                    "path": website_path
                }

                self._process_website_logs(website)

    def _scan_custom_log_locations(self):
        """Scan custom log locations defined in CyberPanel configuration."""
        # Try to find custom log locations from config files
        config_files = [
            "/etc/cyberpanel/cyberpanel.conf",
            "/usr/local/CyberCP/CyberCP/settings.py",
            "/usr/local/CyberPanel/CyberCP/settings.py"
        ]

        custom_log_dirs = set()

        for file in config_files:
            if os.path.exists(file):
                content = self._load_file_content(file)
                if not content:
                    continue

                # Look for log directory settings
                log_dir_matches = re.findall(r'(?:LOG_DIR|log_dir|log_path|LOG_PATH)\s*=\s*[\'"]([^\'"]+)[\'"]', content)
                for log_dir in log_dir_matches:
                    if log_dir and os.path.exists(log_dir):
                        custom_log_dirs.add(log_dir)

        # Process each custom log directory
        for log_dir in custom_log_dirs:
            if os.path.isdir(log_dir):
                self.discoverer.log(f"Processing custom log directory: {log_dir}")

                # Find all log files
                try:
                    signal.signal(signal.SIGALRM, timeout_handler)
                    signal.alarm(10)  # 10 second timeout

                    for log_file in glob.glob(f"{log_dir}/**/*.log*", recursive=True):
                        if not self.discoverer.is_log_already_added(log_file):
                            # Determine log level
                            level = "info"
                            if "error" in log_file.lower():
                                level = "error"
                            elif "debug" in log_file.lower():
                                level = "debug"
                            elif "access" in log_file.lower():
                                level = "access"

                            # Create a unique name
                            log_name = os.path.basename(log_file)
                            safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', log_name.replace('.log', ''))

                            self.add_log(
                                f"cp_custom_{safe_name}",
                                log_file,
                                labels={
                                    "level": level,
                                    "service": "cyberpanel",
                                    "category": "custom",
                                    "path": os.path.relpath(log_file, log_dir)
                                }
                            )
                            self.logs_found += 1

                    signal.alarm(0)  # Disable alarm
                except Exception as e:
                    self.discoverer.log(f"Error processing custom log directory {log_dir}: {str(e)}", "WARN")
                finally:
                    signal.alarm(0)  # Ensure alarm is disabled

    def _find_rotated_logs(self, log_path, name, labels):
        """Find rotated versions of a log file.

        Args:
            log_path: Original log file path
            name: Base name for the log
            labels: Dictionary of labels to apply
        """
        # Common rotation patterns
        rotation_patterns = [
            f"{log_path}.*",
            f"{log_path}-*",
            f"{log_path}_*",
            f"{os.path.dirname(log_path)}/{os.path.basename(log_path)}.*",
            f"{os.path.dirname(log_path)}/{os.path.basename(log_path)}-*",
            f"{os.path.dirname(log_path)}/{os.path.basename(log_path)}_*"
        ]

        processed_rotated = set()

        for pattern in rotation_patterns:
            for rotated_log in glob.glob(pattern):
                # Skip the original log
                if rotated_log == log_path or rotated_log in processed_rotated:
                    continue

                # Only consider files that look like rotated logs
                if re.search(r'\.\d+$|\.\d+\.gz$|\.\d+\.bz2$|\.gz$|\.bz2$|\.zip$|-\d+$|_\d+$', rotated_log):
                    processed_rotated.add(rotated_log)
                    # Create a unique name for the rotated log
                    rotated_name = f"{name}_rotated_{os.path.basename(rotated_log).replace('.', '_')}"

                    self.add_log(
                        rotated_name,
                        rotated_log,
                        labels=labels
                    )
                    self.logs_found += 1

    def _load_file_content(self, file_path):
        """Load the content of a file safely.

        Args:
            file_path: Path to the file

        Returns:
            str: Content of the file or empty string on error
        """
        try:
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(5)  # 5 second timeout

            with open(file_path, 'r') as f:
                content = f.read()

            signal.alarm(0)  # Disable alarm
            return content
        except Exception:
            return ""
        finally:
            signal.alarm(0)  # Ensure alarm is disabled

    def _file_readable(self, file_path):
        """Check if a file is readable.

        Args:
            file_path: Path to the file

        Returns:
            bool: True if file is readable
        """
        try:
            return os.path.isfile(file_path) and os.access(file_path, os.R_OK)
        except Exception:
            return False