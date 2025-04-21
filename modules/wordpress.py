"""
Module for discovering WordPress logs.
"""

import os
import re
import glob
import subprocess
import threading  # Added for thread-safe operations
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import the LogSource base class
from log_source import LogSource, timeout_handler

class WordPressLogSource(LogSource):
    """Discovery for WordPress logs."""

    def discover(self):
        """Discover WordPress logs by examining wp-config.php files."""
        self.discoverer.log("Searching for WordPress logs...")

        # Find WordPress installations using multiple methods
        wp_config_paths = set()  # Use a set to avoid duplicates

        # Method 1: Standard search paths
        wp_search_paths = [
            "/var/www/html",
            "/var/www",
            "/home/*/public_html",
            "/home/*/www",
            "/var/www/vhosts/*",
            "/var/www/clients/client*/web*/web",  # ISPConfig style
            "/home/*/domains/*/public_html",      # cPanel style
            "/usr/local/lsws/DEFAULT/html",       # OpenLiteSpeed default
            "/usr/local/lsws/*/html"              # OpenLiteSpeed vhosts
        ]

        # Build list of wp-config.php files from search paths
        for search_path in wp_search_paths:
            if '*' in search_path:
                # Handle wildcard paths with safer recursive search
                for base_path in glob.glob(search_path.split('*')[0] + '*'):
                    # Use our safer method instead of subprocess
                    found_configs = self._find_wp_configs(base_path)
                    for config in found_configs:
                        if config and os.path.exists(config):
                            wp_config_paths.add(config)
                            self.discoverer.log(f"Found WordPress config: {config}")
            else:
                # Regular path
                if os.path.exists(search_path):
                    found_configs = self._find_wp_configs(search_path, max_depth=2)
                    for config in found_configs:
                        if config and os.path.exists(config):
                            wp_config_paths.add(config)
                            self.discoverer.log(f"Found WordPress config: {config}")

        # Method 2: Check web server config files for DocumentRoot paths
        web_configs = []
        web_config_patterns = [
            "/etc/apache2/sites-enabled/*.conf",
            "/etc/httpd/conf.d/*.conf",
            "/etc/httpd/vhosts.d/*.conf",
            "/usr/local/apache/conf/vhosts/*.conf",
            "/usr/local/lsws/conf/vhosts/*/vhconf.conf",
            "/etc/nginx/sites-enabled/*"
        ]

        for pattern in web_config_patterns:
            web_configs.extend(glob.glob(pattern))

        for config in web_configs:
            try:
                content = self._load_file_content(config)
                if content:
                    # Look for DocumentRoot or root directive (Apache/nginx)
                    doc_root_matches = re.findall(r'(?:DocumentRoot|root)\s+["\']?([^"\']+)["\']?', content)
                    for doc_root in doc_root_matches:
                        doc_root = doc_root.strip()
                        if doc_root and os.path.exists(doc_root):
                            # Check for WordPress in this document root
                            wp_config = os.path.join(doc_root, "wp-config.php")
                            if os.path.exists(wp_config):
                                wp_config_paths.add(wp_config)
                                self.discoverer.log(f"Found WordPress config from web server: {wp_config}")
            except Exception as e:
                self.discoverer.log(f"Error processing web config {config}: {str(e)}", "DEBUG")

        # Method 3: Look for WP-CLI configuration or usage
        wpcli_config_paths = [
            "/root/.wp-cli",
            "/home/*/.wp-cli"
        ]

        for path_pattern in wpcli_config_paths:
            if '*' in path_pattern:
                for path in glob.glob(path_pattern):
                    if os.path.exists(path):
                        # Check for WP-CLI YAML files that might contain paths
                        for yml_file in glob.glob(f"{path}/*.yml"):
                            try:
                                content = self._load_file_content(yml_file)
                                if content:
                                    # Look for path entries
                                    path_matches = re.findall(r'path:\s+["\']?([^"\']+)["\']?', content)
                                    for wp_path in path_matches:
                                        wp_path = wp_path.strip()
                                        if wp_path and os.path.exists(wp_path):
                                            # Check if this is a WordPress root
                                            wp_config = os.path.join(wp_path, "wp-config.php")
                                            if os.path.exists(wp_config):
                                                wp_config_paths.add(wp_config)
                                                self.discoverer.log(f"Found WordPress config from WP-CLI: {wp_config}")
                            except Exception as e:
                                self.discoverer.log(f"Error processing WP-CLI config {yml_file}: {str(e)}", "DEBUG")

        # Fall back to system-wide search if we haven't found any WordPress installations
        if not wp_config_paths:
            self.discoverer.log("No WordPress installations found with standard methods, trying system-wide search...", "WARN")
            try:
                # Use our safer recursive method instead of subprocess
                common_paths = ['/var/www', '/usr/local/lsws', '/home']
                for base_path in common_paths:
                    if os.path.exists(base_path):
                        configs = self._find_wp_configs(base_path, max_depth=5)
                        for config in configs:
                            if config and os.path.exists(config):
                                wp_config_paths.add(config)
                                self.discoverer.log(f"Found WordPress config in system-wide search: {config}")
            except Exception as e:
                self.discoverer.log(f"Error in system-wide WordPress search: {str(e)}", "WARN")

        # Process each WordPress installation with a reduced number of workers
        self.discoverer.log(f"Processing {len(wp_config_paths)} WordPress installations...")

        with ThreadPoolExecutor(max_workers=4) as executor:
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

    def _find_wp_configs(self, base_path, max_depth=4):
        """Find WordPress config files without using subprocess.

        Args:
            base_path: Base directory to search
            max_depth: Maximum directory depth to search

        Returns:
            list: List of wp-config.php paths found
        """
        configs = []

        # Skip paths that clearly aren't web directories
        if any(excluded in base_path for excluded in ['/tmp', '/dev', '/proc', '/sys', '/run']):
            return configs

        # Check if base path exists and is a directory
        if not os.path.exists(base_path) or not os.path.isdir(base_path):
            return configs

        # Function to recursively walk directories with depth control
        def walk_with_depth(current_path, current_depth):
            if current_depth > max_depth:
                return

            try:
                # First check if wp-config.php exists in current directory
                config_path = os.path.join(current_path, "wp-config.php")
                if os.path.isfile(config_path):
                    configs.append(config_path)

                # Then recursively check subdirectories
                for item in os.listdir(current_path):
                    item_path = os.path.join(current_path, item)
                    if os.path.isdir(item_path) and not item.startswith('.'):
                        walk_with_depth(item_path, current_depth + 1)
            except (PermissionError, OSError) as e:
                # Skip directories we can't access
                self.discoverer.log(f"Error accessing {current_path}: {str(e)}", "DEBUG")
                pass

        # Start the recursive search
        walk_with_depth(base_path, 1)
        return configs

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

        # Read wp-config.php using thread-safe method that doesn't use signals
        config_content = self._load_file_content(wp_config)
        if not config_content:
            return logs_found

        # Variables to track WP debug settings
        debug_enabled = False
        debug_log_path = None
        debug_display = False

        # Check if debug logging is enabled - using more comprehensive pattern matching
        debug_match = re.search(r'define\s*\(\s*[\'"]WP_DEBUG[\'"]\s*,\s*(true|TRUE|1|false|FALSE|0)[\'"]?\s*\)', config_content, re.IGNORECASE)
        if debug_match:
            debug_value = debug_match.group(1).lower()
            debug_enabled = debug_value in ('true', '1')

            # Also check for legacy format (older WordPress versions)
            if not debug_enabled:
                alt_debug_match = re.search(r'WP_DEBUG\s*,\s*(true|TRUE|1)', config_content, re.IGNORECASE)
                debug_enabled = alt_debug_match is not None

        # Check for debug log setting - multiple possible formats
        debug_log_match = re.search(r'define\s*\(\s*[\'"]WP_DEBUG_LOG[\'"]\s*,\s*(true|TRUE|1|[\'"].+?[\'"])\s*\)', config_content, re.IGNORECASE)
        if debug_log_match:
            debug_log_value = debug_log_match.group(1).lower()

            if debug_log_value in ('true', '1'):
                # Standard debug.log in wp-content
                debug_log_path = os.path.join(site_path, 'wp-content/debug.log')
            elif debug_log_value.startswith('"') or debug_log_value.startswith("'"):
                # Custom path specified
                debug_log_path = debug_log_value.strip('\'"')

                # Handle relative paths
                if not os.path.isabs(debug_log_path):
                    debug_log_path = os.path.join(site_path, debug_log_path)
        elif debug_enabled:
            # Default debug.log location when WP_DEBUG is true but WP_DEBUG_LOG isn't specified
            debug_log_path = os.path.join(site_path, 'wp-content/debug.log')

        # Check if debug display is enabled (affects where errors might be logged)
        debug_display_match = re.search(r'define\s*\(\s*[\'"]WP_DEBUG_DISPLAY[\'"]\s*,\s*(true|TRUE|1|false|FALSE|0)[\'"]?\s*\)', config_content, re.IGNORECASE)
        if debug_display_match:
            debug_display_value = debug_display_match.group(1).lower()
            debug_display = debug_display_value in ('true', '1')

        # If debug logging is enabled, find the log
        if debug_log_path:
            # Check if path exists or parent directory exists (log might be created later)
            exists = os.path.exists(debug_log_path)
            parent_dir = os.path.dirname(debug_log_path)
            parent_exists = os.path.exists(parent_dir) and os.path.isdir(parent_dir)

            self.add_log(
                f"wp_debug_{site_name}",
                debug_log_path,
                labels={
                    "level": "debug",
                    "service": "wordpress",
                    "site": site_name,
                    "domain": domain if domain else "",
                    "debug_display": str(debug_display).lower()
                },
                exists=exists or parent_exists  # Consider potential future log files
            )
            logs_found += 1

            # Look for rotated debug logs if the path exists
            if exists:
                logs_found += self._find_rotated_logs(debug_log_path, f"wp_debug_{site_name}", {
                    "level": "debug",
                    "service": "wordpress",
                    "site": site_name,
                    "domain": domain if domain else "",
                    "rotated": "true"
                })
        elif debug_enabled:
            # Debug is enabled but no log path - check PHP error log
            php_error_log = self._get_php_error_log_from_wp(site_path, config_content)
            if php_error_log:
                self.add_log(
                    f"wp_php_error_{site_name}",
                    php_error_log,
                    labels={
                        "level": "error",
                        "service": "wordpress",
                        "site": site_name,
                        "domain": domain if domain else "",
                        "source": "php_error_log"
                    }
                )
                logs_found += 1

        # Check for custom logging solutions
        logs_found += self._check_custom_wp_logging(site_path, site_name, domain)

        # Check for standard error logs in WordPress directory and subdirectories
        wp_error_logs = [
            os.path.join(site_path, 'error_log'),
            os.path.join(site_path, 'php_error.log'),
            os.path.join(site_path, 'wp-content/error.log'),
            os.path.join(site_path, 'wp-content/uploads/error.log'),
            os.path.join(site_path, 'wp-admin/error.log')
        ]

        # Also check for error logs in wp-content directory (common location) - more safely
        wp_content_dir = os.path.join(site_path, 'wp-content')
        if os.path.exists(wp_content_dir) and os.path.isdir(wp_content_dir):
            try:
                for root, dirs, files in os.walk(wp_content_dir, topdown=True):
                    # Skip very large directories like uploads with many files
                    if 'uploads' in dirs and os.path.exists(os.path.join(root, 'uploads')):
                        # Just check for log files directly rather than walking entire uploads dir
                        upload_logs = [
                            os.path.join(root, 'uploads', 'error_log'),
                            os.path.join(root, 'uploads', 'error.log'),
                            os.path.join(root, 'uploads', 'debug.log')
                        ]
                        for log_path in upload_logs:
                            if os.path.exists(log_path):
                                wp_error_logs.append(log_path)
                        # Skip deeper traversal of uploads
                        dirs.remove('uploads')

                    # Check for common log files in this directory
                    for file in files:
                        if file in ['error_log', 'error.log', 'debug.log', 'php_error.log']:
                            log_path = os.path.join(root, file)
                            wp_error_logs.append(log_path)
            except Exception as e:
                self.discoverer.log(f"Error searching for logs in {wp_content_dir}: {str(e)}", "DEBUG")

        # Process found error logs
        for log_path in wp_error_logs:
            if os.path.exists(log_path) and not self.discoverer.is_log_already_added(log_path):
                log_name = os.path.basename(log_path).replace('.log', '').replace('_', '')

                # Determine log level from filename
                level = "error"
                if "debug" in log_path.lower():
                    level = "debug"

                # Get relative path to give more context
                rel_path = os.path.relpath(log_path, site_path) if site_path in log_path else log_path

                self.add_log(
                    f"wp_{log_name}_{site_name}",
                    log_path,
                    labels={
                        "level": level,
                        "service": "wordpress",
                        "site": site_name,
                        "domain": domain if domain else "",
                        "path": rel_path
                    }
                )
                logs_found += 1

                # Look for rotated versions
                logs_found += self._find_rotated_logs(log_path, f"wp_{log_name}_{site_name}", {
                    "level": level,
                    "service": "wordpress",
                    "site": site_name,
                    "domain": domain if domain else "",
                    "rotated": "true",
                    "path": rel_path
                })

        # Look for WP-specific error logs that might be created by themes or plugins
        theme_plugin_logs = [
            os.path.join(site_path, 'wp-content/advanced-cache.log'),
            os.path.join(site_path, 'wp-content/object-cache.log'),
            os.path.join(site_path, 'wp-content/plugins/debug.log'),
            os.path.join(site_path, 'wp-content/uploads/wc-logs')  # WooCommerce logs directory
        ]

        for log_path in theme_plugin_logs:
            if os.path.exists(log_path):
                if os.path.isdir(log_path):
                    # For directories like wc-logs, find all log files
                    for log_file in glob.glob(f"{log_path}/*.log"):
                        if not self.discoverer.is_log_already_added(log_file):
                            component = os.path.basename(log_path)  # e.g., wc-logs
                            log_base = os.path.basename(log_file).replace('.log', '')

                            self.add_log(
                                f"wp_{component}_{log_base}_{site_name}",
                                log_file,
                                labels={
                                    "level": "debug",
                                    "service": "wordpress",
                                    "site": site_name,
                                    "domain": domain if domain else "",
                                    "component": component,
                                    "path": os.path.relpath(log_file, site_path)
                                }
                            )
                            logs_found += 1
                elif not self.discoverer.is_log_already_added(log_path):
                    component = os.path.basename(log_path).replace('.log', '')

                    self.add_log(
                        f"wp_{component}_{site_name}",
                        log_path,
                        labels={
                            "level": "debug",
                            "service": "wordpress",
                            "site": site_name,
                            "domain": domain if domain else "",
                            "path": os.path.relpath(log_path, site_path)
                        }
                    )
                    logs_found += 1

        return logs_found

    def _get_php_error_log_from_wp(self, site_path, config_content):
        """Try to determine the PHP error log path from WordPress context.

        Args:
            site_path: Path to the WordPress site
            config_content: Content of wp-config.php

        Returns:
            str: Path to PHP error log or None
        """
        # Method 1: Check for ini_set in wp-config.php
        ini_set_match = re.search(r'ini_set\s*\(\s*[\'"]error_log[\'"]\s*,\s*[\'"](.+?)[\'"]\s*\)', config_content)
        if ini_set_match:
            error_log = ini_set_match.group(1)

            # Handle relative paths
            if not os.path.isabs(error_log):
                error_log = os.path.join(site_path, error_log)

            if os.path.exists(error_log) or os.path.exists(os.path.dirname(error_log)):
                return error_log

        # Method 2: Check for .htaccess with php_value error_log setting
        htaccess_path = os.path.join(site_path, '.htaccess')
        if os.path.exists(htaccess_path):
            htaccess_content = self._load_file_content(htaccess_path)
            if htaccess_content:
                error_log_match = re.search(r'php_value\s+error_log\s+(.+)', htaccess_content, re.MULTILINE)
                if error_log_match:
                    error_log = error_log_match.group(1).strip()

                    # Handle relative paths
                    if not os.path.isabs(error_log):
                        error_log = os.path.join(site_path, error_log)

                    if os.path.exists(error_log) or os.path.exists(os.path.dirname(error_log)):
                        return error_log

        # Method 3: Check for a PHP-FPM pool configuration if this is a vhost
        if 'vhost' in site_path or 'html' in site_path:
            # Extract vhost name
            vhost_name = None
            if 'vhost' in site_path:
                vhost_match = re.search(r'/vhosts?/([^/]+)', site_path)
                if vhost_match:
                    vhost_name = vhost_match.group(1)
            elif 'html' in site_path:
                vhost_match = re.search(r'/([^/]+)/html', site_path)
                if vhost_match:
                    vhost_name = vhost_match.group(1)

            if vhost_name:
                # Look for PHP-FPM pool config - using glob to avoid spawning processes
                pool_patterns = [
                    f"/etc/php-fpm.d/{vhost_name}.conf",
                    f"/etc/php/*/fpm/pool.d/{vhost_name}.conf",
                    f"/usr/local/lsws/lsphp*/etc/php-fpm.d/{vhost_name}.conf"
                ]

                for pool_pattern in pool_patterns:
                    for pool_path in glob.glob(pool_pattern):
                        pool_content = self._load_file_content(pool_path)
                        if pool_content:
                            php_error_log_match = re.search(r'php_admin_value\[error_log\]\s*=\s*(.+)', pool_content, re.MULTILINE)
                            if php_error_log_match:
                                error_log = php_error_log_match.group(1).strip()

                                if os.path.exists(error_log) or os.path.exists(os.path.dirname(error_log)):
                                    return error_log

        # Method 4: Default fallback to common locations
        common_php_logs = [
            os.path.join(site_path, 'php_error.log'),
            os.path.join(site_path, 'php-errors.log'),
            os.path.join(site_path, 'error_log')
        ]

        for log in common_php_logs:
            if os.path.exists(log):
                return log

        return None

    def _check_custom_wp_logging(self, site_path, site_name, domain):
        """Check for custom logging solutions in WordPress.

        Args:
            site_path: Path to the WordPress site
            site_name: Site name identifier
            domain: Domain name

        Returns:
            int: Number of logs discovered
        """
        logs_found = 0

        # Check for common logging plugins
        plugin_logs = {
            "query-monitor": [
                "wp-content/plugins/query-monitor/debug.log"
            ],
            "wp-mail-logging": [
                "wp-content/uploads/wp-mail-logging"
            ],
            "simple-history": [
                "wp-content/uploads/simple-history"
            ],
            "error-log-monitor": [
                "wp-content/mu-plugins/error-log-monitor.log"
            ],
            "wp-security-audit-log": [
                "wp-content/uploads/wp-security-audit-log"
            ],
            "wp-crontrol": [
                "wp-content/debug-cron.log"
            ],
            "wordfence": [
                "wp-content/wflogs"
            ]
        }

        for plugin, log_paths in plugin_logs.items():
            for rel_path in log_paths:
                full_path = os.path.join(site_path, rel_path)

                if os.path.exists(full_path):
                    if os.path.isdir(full_path):
                        # Find all log files in the directory
                        for log_file in glob.glob(f"{full_path}/*.log"):
                            if not self.discoverer.is_log_already_added(log_file):
                                log_base = os.path.basename(log_file).replace('.log', '')

                                self.add_log(
                                    f"wp_{plugin}_{log_base}_{site_name}",
                                    log_file,
                                    labels={
                                        "level": "info",
                                        "service": "wordpress",
                                        "plugin": plugin,
                                        "site": site_name,
                                        "domain": domain if domain else "",
                                        "path": os.path.relpath(log_file, site_path)
                                    }
                                )
                                logs_found += 1
                    else:
                        # Single log file
                        if not self.discoverer.is_log_already_added(full_path):
                            self.add_log(
                                f"wp_{plugin}_log_{site_name}",
                                full_path,
                                labels={
                                    "level": "info",
                                    "service": "wordpress",
                                    "plugin": plugin,
                                    "site": site_name,
                                    "domain": domain if domain else "",
                                    "path": rel_path
                                }
                            )
                            logs_found += 1

                            # Look for rotated versions
                            logs_found += self._find_rotated_logs(full_path, f"wp_{plugin}_log_{site_name}", {
                                "level": "info",
                                "service": "wordpress",
                                "plugin": plugin,
                                "site": site_name,
                                "domain": domain if domain else "",
                                "rotated": "true",
                                "path": rel_path
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

        # Check for domain name in the path
        domain_pattern = re.compile(r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}')
        for part in parts:
            if domain_pattern.match(part):
                return self._sanitize_name(part)

        # Check for /var/www/html/sitename or /var/www/sitename
        if 'www' in parts:
            idx = parts.index('www')
            if idx + 1 < len(parts):
                if parts[idx + 1] == 'html' and idx + 2 < len(parts):
                    return self._sanitize_name(parts[idx + 2])
                return self._sanitize_name(parts[idx + 1])

        # Check for /var/www/vhosts/sitename
        if 'vhosts' in parts:
            idx = parts.index('vhosts')
            if idx + 1 < len(parts):
                return self._sanitize_name(parts[idx + 1])

        # Check for /home/user/public_html/sitename or /home/user/public_html
        if 'public_html' in parts:
            idx = parts.index('public_html')
            if idx + 1 < len(parts):
                return self._sanitize_name(parts[idx + 1])
            elif idx - 1 >= 0:
                return self._sanitize_name(parts[idx - 1])  # Use username

        # Fallback to last meaningful part of path
        site_name = parts[-1]
        if not site_name or site_name in ['wp-config.php', 'html', 'public_html', 'www']:
            # Handle trailing slash or wp-config.php filename
            for i in range(len(parts) - 1, -1, -1):
                if parts[i] and parts[i] not in ['wp-config.php', 'html', 'public_html', 'www']:
                    site_name = parts[i]
                    break

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
        # Method 1: Look for common domain patterns in the path
        domain_pattern = re.compile(r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}')
        path_str = path.replace('_', '.').replace('-', '.') # Convert common separators
        matches = domain_pattern.findall(path_str)

        if matches:
            # Filter out common false positives
            filtered = [m for m in matches if not re.match(r'^\d+\.\d+', m)]  # Fixed regex here
            if filtered:
                return filtered[0]

        # Method 2: Try to find domain from WordPress tables
        wp_config_path = os.path.join(path, 'wp-config.php')
        if os.path.exists(wp_config_path):
            config_content = self._load_file_content(wp_config_path)
            if config_content:
                # Look for home or siteurl in wp-config.php
                url_match = re.search(r'define\s*\(\s*[\'"](?:WP_HOME|WP_SITEURL)[\'"]\s*,\s*[\'"]https?://([^/\'"]+)', config_content)
                if url_match:
                    return url_match.group(1)

        # Method 3: Try to find domain from vhost configuration - safer version
        try:
            vhost_dirs = [
                "/usr/local/lsws/conf/vhosts",
                "/etc/openlitespeed/vhosts",
                "/etc/apache2/sites-available",
                "/etc/nginx/sites-available",
                "/etc/httpd/conf.d",
                "/etc/httpd/vhosts.d"
            ]

            site_name = self._extract_site_name(path)

            for vhost_dir in vhost_dirs:
                if os.path.exists(vhost_dir):
                    # Look for config files matching site name or containing the path
                    vhost_configs = glob.glob(f"{vhost_dir}/{site_name}*.conf")
                    if not vhost_configs:
                        # Check a subset of all configs as fallback (limited to avoid excessive file reading)
                        vhost_configs = glob.glob(f"{vhost_dir}/*.conf")[:10]  # Limit to first 10 configs

                    for config in vhost_configs:
                        content = self._load_file_content(config)
                        if not content:
                            continue

                        # Check if this config references our path
                        if path not in content and path.replace('//', '/') not in content:
                            continue

                        # Look for ServerName, domain, or vhDomain
                        domain_match = re.search(r'(?:ServerName|domain|vhDomain|server_name)\s+([a-zA-Z0-9.-]+)', content)
                        if domain_match:
                            return domain_match.group(1)
        except Exception as e:
            self.discoverer.log(f"Error extracting domain from vhost configs: {str(e)}", "DEBUG")

        return ""

# Required function to return the log source class
def get_log_source():
    return WordPressLogSource