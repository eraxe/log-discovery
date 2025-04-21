"""
Module for discovering WordPress logs.
"""

import os
import re
import glob
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import the LogSource base class
from log_source import LogSource

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

# Required function to return the log source class
def get_log_source():
    return WordPressLogSource