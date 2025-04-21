#!/usr/bin/env python3
"""
Smart Log Discovery System for OpenLiteSpeed/CyberPanel/WordPress

This script discovers log file locations by examining actual configuration files
rather than simply scanning for common patterns. It builds a structured output
that can be used to configure Loki/Promtail.

Usage:
    python3 log_discovery.py [--output OUTPUT] [--format {json,yaml}] [--verbose]

Output format:
    {
        "sources": [
            {
                "type": "openlitespeed",
                "name": "vhost_example_com_error",
                "path": "/usr/local/lsws/logs/vhosts/example.com/error.log",
                "format": "text",
                "labels": {
                    "source": "openlitespeed",
                    "service": "webserver",
                    "level": "error",
                    "vhost": "example.com"
                },
                "exists": true,
                "last_modified": "2025-04-12T14:30:22"
            },
            ...
        ]
    }
"""

import os
import re
import sys
import json
import yaml
import glob
import argparse
import subprocess
import configparser
from pathlib import Path
from datetime import datetime


class LogDiscoverer:
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.discovered_logs = []
        
        # Initialize source type counts for naming
        self.source_counts = {
            "openlitespeed": 0,
            "cyberpanel": 0,
            "wordpress": 0,
            "php": 0,
            "mysql": 0
        }
    
    def log(self, message, level="INFO"):
        """Print log messages when verbose is enabled"""
        if self.verbose:
            print(f"[{level}] {message}")
    
    def discover_all(self):
        """Run all discovery methods and return results"""
        self.discover_openlitespeed_logs()
        self.discover_cyberpanel_logs()
        self.discover_wordpress_logs()
        self.discover_php_logs()
        self.discover_mysql_logs()
        
        # Add metadata
        result = {
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "version": "1.0.0",
                "hostname": self.get_hostname()
            },
            "sources": self.discovered_logs
        }
        
        return result
    
    def get_hostname(self):
        """Get system hostname"""
        try:
            return subprocess.check_output("hostname", shell=True).decode().strip()
        except:
            return "unknown"
    
    def add_log_source(self, source_type, name, path, format="text", labels=None, exists=None):
        """Add a discovered log source to the results"""
        if labels is None:
            labels = {}
        
        # Set default labels based on source type
        if "source" not in labels:
            labels["source"] = source_type
        
        # Auto-increment count for this source type
        self.source_counts[source_type] = self.source_counts.get(source_type, 0) + 1
        
        # If no name provided, generate one
        if not name:
            name = f"{source_type}_{self.source_counts[source_type]}"
        
        # Check if file exists if not already provided
        if exists is None:
            exists = os.path.exists(path)
        
        # Get last modified time if file exists
        last_modified = None
        if exists:
            try:
                last_modified = datetime.fromtimestamp(os.path.getmtime(path)).isoformat()
            except:
                pass
        
        log_entry = {
            "type": source_type,
            "name": name,
            "path": path,
            "format": format,
            "labels": labels,
            "exists": exists,
            "last_modified": last_modified
        }
        
        self.discovered_logs.append(log_entry)
        
        self.log(f"Discovered {source_type} log: {path} (exists: {exists})")
        
        return log_entry
    
    def discover_openlitespeed_logs(self):
        """Discover OpenLiteSpeed logs by examining configuration files"""
        self.log("Searching for OpenLiteSpeed logs...")
        
        # Find OpenLiteSpeed config file
        config_paths = [
            "/usr/local/lsws/conf/httpd_config.conf",
            "/etc/openlitespeed/httpd_config.conf"
        ]
        
        config_file = None
        for path in config_paths:
            if os.path.exists(path):
                config_file = path
                break
        
        if not config_file:
            self.log("OpenLiteSpeed config file not found", "WARN")
            return
        
        # Parse main config file
        with open(config_file, 'r') as f:
            config_content = f.read()
        
        # Find main error log
        error_log_match = re.search(r'errorlog\s+(.+?)[\s\n]', config_content)
        if error_log_match:
            error_log_path = error_log_match.group(1)
            self.add_log_source(
                "openlitespeed", 
                "main_error", 
                error_log_path,
                labels={"level": "error", "service": "webserver"}
            )
        
        # Find main access log
        access_log_match = re.search(r'accesslog\s+(.+?)[\s\n]', config_content)
        if access_log_match:
            access_log_path = access_log_match.group(1)
            self.add_log_source(
                "openlitespeed", 
                "main_access", 
                access_log_path,
                labels={"level": "access", "service": "webserver"}
            )
        
        # Find virtual host configurations
        vhost_dir = None
        vhost_dir_match = re.search(r'configFile\s+(.+?)[\s\n]', config_content)
        if vhost_dir_match:
            vhost_dir = os.path.dirname(vhost_dir_match.group(1))
        else:
            # Try common locations
            vhost_dirs = [
                "/usr/local/lsws/conf/vhosts",
                "/etc/openlitespeed/vhosts"
            ]
            for dir_path in vhost_dirs:
                if os.path.exists(dir_path):
                    vhost_dir = dir_path
                    break
        
        # Process virtual host configs
        if vhost_dir:
            self.log(f"Looking for vhost configs in {vhost_dir}")
            vhost_configs = glob.glob(f"{vhost_dir}/*/*.conf") + glob.glob(f"{vhost_dir}/*.conf")
            
            for vhost_config in vhost_configs:
                vhost_name = os.path.basename(os.path.dirname(vhost_config))
                if vhost_name == vhost_dir:
                    # Handle case where *.conf is directly in vhost_dir
                    vhost_name = os.path.basename(vhost_config).replace('.conf', '')
                
                self.log(f"Processing vhost: {vhost_name}")
                
                with open(vhost_config, 'r') as f:
                    vhost_content = f.read()
                
                # Get vhost error log
                vhost_error_match = re.search(r'errorlog\s+(.+?)[\s\n]', vhost_content)
                if vhost_error_match:
                    error_log_path = vhost_error_match.group(1)
                    self.add_log_source(
                        "openlitespeed", 
                        f"vhost_{vhost_name}_error", 
                        error_log_path,
                        labels={"level": "error", "service": "webserver", "vhost": vhost_name}
                    )
                
                # Get vhost access log
                vhost_access_match = re.search(r'accesslog\s+(.+?)[\s\n]', vhost_content)
                if vhost_access_match:
                    access_log_path = vhost_access_match.group(1)
                    self.add_log_source(
                        "openlitespeed", 
                        f"vhost_{vhost_name}_access", 
                        access_log_path,
                        labels={"level": "access", "service": "webserver", "vhost": vhost_name}
                    )
        
        # Look for additional logs in standard locations
        log_dirs = [
            "/usr/local/lsws/logs",
            "/var/log/openlitespeed",
            "/var/log/lsws"
        ]
        
        for log_dir in log_dirs:
            if os.path.exists(log_dir):
                self.log(f"Checking standard log directory: {log_dir}")
                
                # Look for script handler logs
                script_logs = glob.glob(f"{log_dir}/stderr.log") + glob.glob(f"{log_dir}/lsphp*.log")
                for script_log in script_logs:
                    log_name = os.path.basename(script_log)
                    handler_name = log_name.replace('.log', '')
                    
                    self.add_log_source(
                        "openlitespeed", 
                        f"script_{handler_name}", 
                        script_log,
                        labels={"service": "script_handler", "handler": handler_name}
                    )

    def discover_cyberpanel_logs(self):
        """Discover CyberPanel logs by examining configuration files and known locations"""
        self.log("Searching for CyberPanel logs...")
        
        # Check if CyberPanel is installed
        cyberpanel_installed = os.path.exists("/usr/local/CyberCP") or os.path.exists("/usr/local/CyberPanel")
        
        if not cyberpanel_installed:
            self.log("CyberPanel installation not detected", "INFO")
            return
        
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
        
        for log_path, level, name in cyberpanel_logs:
            self.add_log_source(
                "cyberpanel", 
                name, 
                log_path,
                labels={"level": level, "service": "cyberpanel"}
            )
        
        # Look for additional logs in CyberPanel directories
        cyberpanel_log_dirs = [
            "/var/log/cyberpanel",
            "/usr/local/CyberCP/logs",
            "/usr/local/CyberPanel/debug"
        ]
        
        for log_dir in cyberpanel_log_dirs:
            if os.path.exists(log_dir):
                self.log(f"Checking CyberPanel log directory: {log_dir}")
                
                # Get all .log files in the directory
                log_files = glob.glob(f"{log_dir}/*.log")
                
                for log_file in log_files:
                    log_name = os.path.basename(log_file).replace('.log', '')
                    
                    # Skip logs we've already added
                    if any(log_file == l[0] for l in cyberpanel_logs):
                        continue
                    
                    level = "info"
                    if "error" in log_name.lower():
                        level = "error"
                    elif "debug" in log_name.lower():
                        level = "debug"
                    
                    self.add_log_source(
                        "cyberpanel", 
                        f"cp_{log_name}", 
                        log_file,
                        labels={"level": level, "service": "cyberpanel"}
                    )

    def discover_wordpress_logs(self):
        """Discover WordPress logs by examining wp-config.php files"""
        self.log("Searching for WordPress logs...")
        
        # Find WordPress installations
        wp_config_paths = []
        
        # Possible WordPress installation paths
        wp_search_paths = [
            "/var/www/html",
            "/var/www",
            "/home/*/public_html",
            "/home/*/www"
        ]
        
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
        
        # Process each WordPress installation
        for wp_config in wp_config_paths:
            site_path = os.path.dirname(wp_config)
            site_name = self._extract_site_name(site_path)
            
            self.log(f"Processing WordPress site: {site_name} at {site_path}")
            
            # Extract domain from path if possible
            domain = self._extract_domain_from_path(site_path)
            
            # Read wp-config.php
            with open(wp_config, 'r') as f:
                config_content = f.read()
            
            # Check if debug logging is enabled
            debug_enabled = re.search(r'WP_DEBUG\s*,\s*true', config_content, re.IGNORECASE) is not None
            
            # Check for custom debug log path
            debug_log_path = None
            debug_log_match = re.search(r'WP_DEBUG_LOG\s*,\s*([\'"])(.*?)\1', config_content)
            
            if debug_log_match:
                debug_log_path = debug_log_match.group(2)
                
                # Handle relative paths
                if not debug_log_path.startswith('/'):
                    debug_log_path = os.path.join(site_path, debug_log_path)
            elif debug_enabled:
                # Default debug.log location
                debug_log_path = os.path.join(site_path, 'wp-content/debug.log')
            
            if debug_log_path:
                self.add_log_source(
                    "wordpress", 
                    f"wp_debug_{site_name}", 
                    debug_log_path,
                    labels={
                        "level": "debug", 
                        "service": "wordpress", 
                        "site": site_name,
                        "domain": domain if domain else ""
                    }
                )
            
            # Check for standard error logs in WordPress directory
            wp_error_logs = [
                os.path.join(site_path, 'error_log'),
                os.path.join(site_path, 'php_error.log'),
                os.path.join(site_path, 'wp-content/error.log')
            ]
            
            for log_path in wp_error_logs:
                if os.path.exists(log_path):
                    log_name = os.path.basename(log_path).replace('.log', '').replace('_', '')
                    self.add_log_source(
                        "wordpress", 
                        f"wp_{log_name}_{site_name}", 
                        log_path,
                        labels={
                            "level": "error", 
                            "service": "wordpress", 
                            "site": site_name,
                            "domain": domain if domain else ""
                        }
                    )
    
    def discover_php_logs(self):
        """Discover PHP logs by examining php.ini files"""
        self.log("Searching for PHP logs...")
        
        # Find PHP configuration
        php_config = None
        
        # Try to get PHP configuration with php -i
        try:
            php_info = subprocess.check_output("php -i", shell=True).decode()
            
            # Extract error_log path
            error_log_match = re.search(r'error_log\s*=>\s*(.+?)\s', php_info)
            if error_log_match:
                php_error_log = error_log_match.group(1)
                
                if php_error_log and php_error_log != '(None)' and php_error_log != 'no value':
                    self.add_log_source(
                        "php", 
                        "php_error", 
                        php_error_log,
                        labels={"level": "error", "service": "php"}
                    )
        except:
            self.log("Could not execute 'php -i' to find PHP configuration", "WARN")
        
        # Look for php.ini files
        php_ini_paths = [
            "/etc/php.ini",
            "/etc/php/*/php.ini",
            "/usr/local/lib/php.ini",
            "/usr/local/lsws/lsphp*/etc/php.ini"
        ]
        
        for ini_pattern in php_ini_paths:
            if '*' in ini_pattern:
                # Handle wildcard paths
                ini_files = glob.glob(ini_pattern)
                for ini_file in ini_files:
                    self._process_php_ini(ini_file)
            elif os.path.exists(ini_pattern):
                self._process_php_ini(ini_pattern)
    
    def _process_php_ini(self, ini_path):
        """Process a PHP ini file to extract log paths"""
        self.log(f"Processing PHP configuration: {ini_path}")
        
        try:
            # Extract PHP version from path
            php_version = None
            version_match = re.search(r'php/(\d+\.\d+)', ini_path)
            if version_match:
                php_version = version_match.group(1)
            
            with open(ini_path, 'r') as f:
                ini_content = f.read()
            
            # Extract error_log path
            error_log_match = re.search(r'error_log\s*=\s*(.+?)(?:\s|$)', ini_content)
            if error_log_match:
                error_log = error_log_match.group(1).strip('"\'')
                
                if error_log and error_log != '(None)' and error_log != 'no value':
                    self.add_log_source(
                        "php", 
                        f"php{php_version}_error" if php_version else "php_error", 
                        error_log,
                        labels={
                            "level": "error", 
                            "service": "php",
                            "version": php_version if php_version else ""
                        }
                    )
        except Exception as e:
            self.log(f"Error processing {ini_path}: {str(e)}", "ERROR")

    def discover_mysql_logs(self):
        """Discover MySQL/MariaDB logs"""
        self.log("Searching for MySQL/MariaDB logs...")
        
        # First check if MySQL/MariaDB is installed
        mysql_installed = False
        for path in ["/etc/mysql", "/var/lib/mysql", "/etc/my.cnf", "/etc/my.cnf.d"]:
            if os.path.exists(path):
                mysql_installed = True
                break
        
        if not mysql_installed:
            self.log("MySQL/MariaDB installation not detected", "INFO")
            return
        
        # MySQL config files to check
        mysql_configs = [
            "/etc/my.cnf",
            "/etc/mysql/my.cnf"
        ]
        
        # Also check for any .cnf files in conf.d directories
        conf_dirs = [
            "/etc/my.cnf.d",
            "/etc/mysql/conf.d",
            "/etc/mysql/mysql.conf.d"
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
            "/var/log/mysqld.log"
        ]
        
        # Check standard log locations first
        for log_path in standard_logs:
            if os.path.exists(log_path):
                log_type = "error" if "error" in log_path or ".err" in log_path else "general"
                self.add_log_source(
                    "mysql", 
                    f"mysql_{log_type}", 
                    log_path,
                    labels={"level": log_type, "service": "database"}
                )
        
        # Extract log paths from configuration files
        for config_path in mysql_configs:
            if os.path.exists(config_path):
                self.log(f"Processing MySQL config: {config_path}")
                
                try:
                    with open(config_path, 'r') as f:
                        config_content = f.read()
                    
                    # Extract error log path
                    error_log_match = re.search(r'log[-_]error\s*=\s*(.+?)(?:\s|$)', config_content)
                    if error_log_match:
                        error_log = error_log_match.group(1).strip('"\'')
                        
                        self.add_log_source(
                            "mysql", 
                            "mysql_error", 
                            error_log,
                            labels={"level": "error", "service": "database"}
                        )
                    
                    # Extract general log path
                    general_log_match = re.search(r'general[-_]log[-_]file\s*=\s*(.+?)(?:\s|$)', config_content)
                    if general_log_match:
                        general_log = general_log_match.group(1).strip('"\'')
                        
                        self.add_log_source(
                            "mysql", 
                            "mysql_general", 
                            general_log,
                            labels={"level": "general", "service": "database"}
                        )
                    
                    # Extract slow query log path
                    slow_log_match = re.search(r'slow[-_]query[-_]log[-_]file\s*=\s*(.+?)(?:\s|$)', config_content)
                    if slow_log_match:
                        slow_log = slow_log_match.group(1).strip('"\'')
                        
                        self.add_log_source(
                            "mysql", 
                            "mysql_slow", 
                            slow_log,
                            labels={"level": "slow", "service": "database"}
                        )
                except Exception as e:
                    self.log(f"Error processing {config_path}: {str(e)}", "ERROR")

    def _extract_site_name(self, path):
        """Extract a site name from a path"""
        # Try to extract meaningful site name from path
        parts = path.split('/')
        
        # Check for /var/www/html/sitename or /var/www/sitename
        if 'www' in parts:
            idx = parts.index('www')
            if idx + 1 < len(parts):
                if parts[idx + 1] == 'html' and idx + 2 < len(parts):
                    return parts[idx + 2]
                return parts[idx + 1]
        
        # Check for /home/user/public_html/sitename or /home/user/public_html
        if 'public_html' in parts:
            idx = parts.index('public_html')
            if idx + 1 < len(parts):
                return parts[idx + 1]
            elif idx - 1 >= 0:
                return parts[idx - 1]  # Use username
        
        # Fallback to last part of path
        site_name = parts[-1]
        if not site_name:  # Handle trailing slash
            site_name = parts[-2]
        
        return site_name

    def _extract_domain_from_path(self, path):
        """Try to extract a domain name from a path"""
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
        except:
            pass
        
        return None


def main():
    parser = argparse.ArgumentParser(description="Smart Log Discovery for OpenLiteSpeed/CyberPanel/WordPress")
    parser.add_argument("--output", "-o", help="Output file path (default: stdout)")
    parser.add_argument("--format", "-f", choices=["json", "yaml"], default="json", help="Output format (default: json)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    
    args = parser.parse_args()
    
    # Initialize and run discovery
    discoverer = LogDiscoverer(verbose=args.verbose)
    results = discoverer.discover_all()
    
    # Generate output
    if args.format == "json":
        output = json.dumps(results, indent=2)
    else:  # yaml
        output = yaml.dump(results, default_flow_style=False)
    
    # Write output
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output)
        print(f"Results written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
