# Enhanced Log Discovery System for OpenLiteSpeed/CyberPanel/WordPress

This system automatically discovers log files for OpenLiteSpeed, CyberPanel, and WordPress installations by examining their configuration files. Unlike simpler approaches that just search for common patterns, this system finds the actual configured log locations by parsing configuration files.

## Features

- **Configuration-based discovery**: Examines actual config files to find log locations
- **Multi-application support**: Discovers logs for:
  - OpenLiteSpeed web server
  - CyberPanel admin panel
  - WordPress sites
  - PHP configuration
  - MySQL/MariaDB database
- **Structured output**: Produces detailed JSON or YAML output with:
  - Log file path
  - File existence verification
  - Last modified timestamp
  - Size information
  - File checksum (for smaller files)
  - Intelligent categorization and labeling
- **Smart labeling**: Automatically adds relevant labels like:
  - Log source type (openlitespeed, wordpress, etc.)
  - Service type (webserver, database, etc.)
  - Error level (error, access, debug, etc.)
  - Domain/site name (where applicable)
- **Enhanced performance**:
  - Parallel processing for faster discovery
  - Caching to reduce redundant operations
  - Configurable timeout controls
- **Improved reliability**:
  - Robust error handling and reporting
  - Log rotation detection
  - Log validation capabilities
- **Notification support**:
  - Email notifications on completion/failure
  - Detailed summary reports

## Installation

1. Download the files to your server:

```bash
mkdir -p /opt/log-discovery
cd /opt/log-discovery
# Copy the scripts to this directory
chmod +x *.sh *.py
```

2. Ensure dependencies are installed:

```bash
# For Debian/Ubuntu
apt-get update
apt-get install -y python3 python3-yaml mailutils jq

# For CentOS/RHEL
yum install -y python3 python3-pyyaml mailx jq
```

3. Run the installer script:

```bash
./install.sh install
```

The installer will:
- Create necessary directories
- Set up configuration files
- Install a systemd service for scheduled discovery (optional)
- Configure log rotation (optional)

## Usage

### Basic Usage

Run the discovery script:

```bash
./runner.sh
```

This will:
1. Scan your system for OpenLiteSpeed, CyberPanel, and WordPress installations
2. Analyze their configuration files to find log locations
3. Create a structured output file at `output/discovered_logs.json`

### Advanced Options

```
Usage: ./runner.sh [options]

Options:
  -h, --help             Show this help message
  -v, --verbose          Enable verbose output
  -o, --output FILE      Output file path (default: output/discovered_logs.json)
  -f, --format FORMAT    Output format: json or yaml (default: json)
  -c, --cron             Run in cron mode (minimal output, only errors to stderr)
  -t, --timeout SEC      Set timeout in seconds (default: 300)
  -i, --include TYPES    Include only specified log types (comma-separated)
  -e, --exclude TYPES    Exclude specified log types (comma-separated)
  --cache FILE           Cache file path (default: cache/discovery_cache.json)
  --validate             Validate log files (check permissions)
  --notify EMAIL         Send notification email on completion/failure
```

### Example: Running in verbose mode with YAML output and notifications

```bash
./runner.sh --verbose --format yaml --output /tmp/my_logs.yaml --notify admin@example.com
```

### Example: Only discovering specific log types

```bash
./runner.sh --include wordpress,php --exclude mysql
```

## Integrating with Loki/Promtail

The output file can be used to configure Promtail to send logs to Loki. Here's how to integrate with your existing Loki/Promtail setup:

### Option 1: Manual Configuration

1. Run the log discovery:

```bash
./runner.sh --format yaml --output /tmp/discovered_logs.yaml
```

2. Use the output to manually update your Promtail configuration:

```yaml
# promtail-config.yaml
scrape_configs:
  # Your existing scrape configs...
  
  # OpenLiteSpeed logs
  - job_name: openlitespeed
    static_configs:
    - targets:
        - localhost
      labels:
        job: openlitespeed
        source: openlitespeed
        service: webserver
        level: error
        # Other labels from the discovery output
      __path__: /path/to/openlitespeed/error.log

  # WordPress logs (for each site)
  - job_name: wordpress_site1
    static_configs:
    - targets:
        - localhost
      labels:
        job: wordpress
        source: wordpress
        service: wordpress
        site: site1
        # Other labels from the discovery output
      __path__: /path/to/wordpress/site1/wp-content/debug.log
```

### Option 2: Automated Integration Script

Create a script to automatically update your Promtail configuration based on the discovery output:

```python
#!/usr/bin/env python3
import yaml
import os
import sys

# Load the discovery output
with open('/opt/log-discovery/output/discovered_logs.yaml', 'r') as f:
    discovery = yaml.safe_load(f)

# Load your existing Promtail config
with open('/etc/promtail/config.yaml', 'r') as f:
    promtail_config = yaml.safe_load(f)

# Make sure scrape_configs exists
if 'scrape_configs' not in promtail_config:
    promtail_config['scrape_configs'] = []

# Group logs by type
logs_by_type = {}
for source in discovery['sources']:
    if source['exists']:  # Only include existing logs
        if source['type'] not in logs_by_type:
            logs_by_type[source['type']] = []
        logs_by_type[source['type']].append(source)

# Create scrape configs for each log type
for log_type, logs in logs_by_type.items():
    # Group logs by additional criteria if needed
    # For WordPress, group by site
    if log_type == 'wordpress':
        logs_by_site = {}
        for log in logs:
            site = log['labels'].get('site', 'unknown')
            if site not in logs_by_site:
                logs_by_site[site] = []
            logs_by_site[site].append(log)
        
        for site, site_logs in logs_by_site.items():
            job_name = f"wordpress_{site}"
            paths = [log['path'] for log in site_logs]
            
            # Use first log's labels as base
            labels = {k: v for k, v in site_logs[0]['labels'].items()}
            labels['job'] = job_name
            
            # Create scrape config
            scrape_config = {
                'job_name': job_name,
                'static_configs': [{
                    'targets': ['localhost'],
                    'labels': labels,
                    '__path__': paths[0] if len(paths) == 1 else '{' + '|'.join(paths) + '}'
                }]
            }
            
            # Add to promtail config
            promtail_config['scrape_configs'].append(scrape_config)
    else:
        # For other log types, create a single scrape config
        job_name = log_type
        paths = [log['path'] for log in logs]
        
        # Use first log's labels as base
        labels = {k: v for k, v in logs[0]['labels'].items()}
        labels['job'] = job_name
        
        # Create scrape config
        scrape_config = {
            'job_name': job_name,
            'static_configs': [{
                'targets': ['localhost'],
                'labels': labels,
                '__path__': paths[0] if len(paths) == 1 else '{' + '|'.join(paths) + '}'
            }]
        }
        
        # Add to promtail config
        promtail_config['scrape_configs'].append(scrape_config)

# Save updated config
with open('/etc/promtail/config.yaml', 'w') as f:
    yaml.dump(promtail_config, f)

print("Promtail configuration updated successfully!")
```

## Scheduling Regular Discovery

You can set up a cron job to regularly discover logs, or use the systemd service installed by the installer script.

### Using Systemd Service (Recommended)

If you used the installer script, a systemd service is already configured. You can manage it with:

```bash
# Check service status
systemctl status log-discovery.timer

# Manually run discovery
systemctl start log-discovery.service

# Disable scheduled discovery
systemctl disable log-discovery.timer

# Change discovery interval (edit the timer file)
systemctl edit log-discovery.timer
```

### Using Cron (Alternative)

```bash
# Edit crontab
crontab -e

# Add a job to run discovery daily at 4 AM
0 4 * * * /opt/log-discovery/runner.sh --cron --output /etc/promtail/discovered_logs.yaml

# Add another job to update Promtail config and restart it
5 4 * * * python3 /opt/log-discovery/update_promtail.py && systemctl restart promtail
```

## Output Format

The discovery script outputs a structured JSON or YAML file with detailed information about each log file:

```json
{
  "metadata": {
    "generated_at": "2025-04-21T15:30:22",
    "version": "2.0.0",
    "hostname": "webserver1",
    "discovery_time_seconds": 12.5
  },
  "sources": [
    {
      "type": "openlitespeed",
      "name": "main_error",
      "path": "/usr/local/lsws/logs/error.log",
      "format": "text",
      "labels": {
        "source": "openlitespeed",
        "service": "webserver",
        "level": "error"
      },
      "exists": true,
      "last_modified": "2025-04-21T14:25:16",
      "size": 1245678,
      "checksum": "5a8e1fa25f58..."
    },
    {
      "type": "wordpress",
      "name": "wp_debug_example_com",
      "path": "/var/www/example.com/wp-content/debug.log",
      "format": "text",
      "labels": {
        "source": "wordpress",
        "service": "wordpress",
        "level": "debug",
        "site": "example_com",
        "domain": "example.com"
      },
      "exists": true,
      "last_modified": "2025-04-21T15:12:03",
      "size": 45678,
      "checksum": "f8a2b6d12e4c..."
    }
  ]
}
```

## Advanced Features

### Caching

The discovery system supports caching to improve performance on subsequent runs:

```bash
# Run with caching enabled
./runner.sh --cache /var/cache/log_discovery.json
```

This can significantly reduce discovery time on large systems with many logs.

### Log Validation

You can validate the discovered logs to ensure they are readable:

```bash
# Check if discovered logs are readable
./runner.sh --validate
```

This adds a "readable" field to each log entry.

### Notification Support

Get email notifications when discovery completes or fails:

```bash
# Send email notification
./runner.sh --notify admin@example.com
```

### Selective Discovery

Only discover specific types of logs:

```bash
# Only discover WordPress and PHP logs
./runner.sh --include wordpress,php

# Discover all except MySQL logs
./runner.sh --exclude mysql
```

## Troubleshooting

### No logs found

If the system doesn't find any logs:

1. Make sure you have the applications installed:
   - OpenLiteSpeed server
   - CyberPanel
   - WordPress sites

2. Run in verbose mode to see what's happening:
   ```bash
   ./runner.sh --verbose
   ```

3. Check file permissions:
   - The script needs to be able to read configuration files
   - Run with sudo if necessary: `sudo ./runner.sh`

4. Check the log files:
   ```bash
   cat /opt/log-discovery/logs/discovery.log
   cat /opt/log-discovery/logs/error.log
   ```

### Common errors

#### Error: "ModuleNotFoundError: No module named 'yaml'"

Install the PyYAML package:

```bash
pip3 install pyyaml
```

#### Error: "Timeout during discovery process"

Increase the timeout value:

```bash
./runner.sh --timeout 600
```

#### Error: "Permission denied" when accessing config files

Run the script with elevated privileges:

```bash
sudo ./runner.sh
```

## Contributing

Feel free to modify the scripts to match your specific environment or add support for additional log sources.

## License

This project is open source and available under the MIT License.
# Installation Guide for Log Discovery System

This guide explains how to install, update, or remove the Log Discovery System using the `install.sh` script.

## Overview

The `install.sh` script provides a simple way to set up the Log Discovery System on your server. It handles:

- Creating the necessary directories
- Setting up configuration files
- Installing systemd services for scheduled execution
- Configuring permissions
- Setting up log rotation

## Basic Usage

```bash
./install.sh [action] [options]
```

Where `[action]` is one of:
- `install`: Install the log discovery system
- `update`: Update an existing installation
- `remove`: Remove the log discovery system


# Modular Log Discovery System

The log discovery system has been enhanced with a modular architecture that makes it easy to extend with support for additional log sources.

## Module Architecture

The system now uses a plugin-based approach where each log source is implemented as a separate module in the `modules` directory. The main script automatically loads these modules at runtime, making it easy to add new log source types without modifying the core code.

### Module Structure

Each module follows this structure:

1. A Python file in the `modules` directory (e.g., `modules/nginx.py`)
2. A class that extends the `LogSource` base class
3. Implementation of the `discover()` method to find logs of that type
4. A `get_log_source()` function that returns the class

### Benefits of the Modular Approach

- **Extensibility**: Add new log sources without modifying the core code
- **Maintainability**: Each log source is isolated, making the code easier to maintain
- **Reusability**: Common functionality is in the base class, reducing duplication
- **Testability**: Test each module independently
- **Customizability**: Organizations can add their own modules for proprietary systems

## Existing Modules

The system comes with modules for:

- **OpenLiteSpeed**: Web server logs
- **CyberPanel**: Admin panel logs
- **WordPress**: WordPress site logs
- **PHP**: PHP configuration logs
- **MySQL/MariaDB**: Database logs

## Adding New Modules

To add support for a new log source:

1. Create a new Python file in the `modules` directory (e.g., `modules/nginx.py`)
2. Use the `example_template.py` as a starting point
3. Implement the `discover()` method to find logs of your type
4. Ensure that your module has a `get_log_source()` function

The module will be automatically loaded the next time you run the log discovery script.

### Example Module Template

A template is provided in `modules/example_template.py` that you can use as a starting point for your own modules.

### Example: Creating a Nginx Module

Here's a simplified example of how to create a module for Nginx logs:

```python
"""
Module for discovering Nginx logs.
"""

import os
import re
import glob

# Import the LogSource base class
from log_source import LogSource

class NginxLogSource(LogSource):
    """Discovery for Nginx logs."""

    def discover(self):
        """Discover Nginx logs by examining configuration files."""
        self.discoverer.log("Searching for Nginx logs...")

        # Find Nginx config file
        config_paths = [
            "/etc/nginx/nginx.conf",
            "/usr/local/nginx/conf/nginx.conf"
        ]

        config_file = next((path for path in config_paths if self._file_readable(path)), None)

        if not config_file:
            self.discoverer.log("Nginx config file not found", "WARN")
            return self.logs_found

        # Parse config file
        config_content = self._load_file_content(config_file)
        if not config_content:
            return self.logs_found

        # Extract log paths
        error_log_match = re.search(r'error_log\s+(.+?)[\s;]', config_content)
        if error_log_match:
            error_log_path = error_log_match.group(1)
            self.add_log(
                "nginx_error",
                error_log_path,
                labels={"level": "error", "service": "webserver"}
            )
            self.logs_found += 1

        # Check for vhost configs
        vhost_dirs = ["/etc/nginx/sites-enabled", "/etc/nginx/conf.d"]
        
        for vhost_dir in vhost_dirs:
            if os.path.exists(vhost_dir):
                vhost_configs = glob.glob(f"{vhost_dir}/*.conf")
                for vhost_config in vhost_configs:
                    # Process each vhost config
                    vhost_content = self._load_file_content(vhost_config)
                    if vhost_content:
                        # Extract vhost name
                        vhost_name = os.path.basename(vhost_config).replace('.conf', '')
                        
                        # Look for access logs
                        access_log_match = re.search(r'access_log\s+(.+?)[\s;]', vhost_content)
                        if access_log_match:
                            access_log_path = access_log_match.group(1)
                            self.add_log(
                                f"nginx_access_{vhost_name}",
                                access_log_path,
                                labels={"level": "access", "service": "webserver", "vhost": vhost_name}
                            )
                            self.logs_found += 1

        return self.logs_found

# Required function to return the log source class
def get_log_source():
    return NginxLogSource
```

## Module Best Practices

When creating modules, follow these best practices:

1. **Descriptive naming**: Use clear, descriptive names for your module and class
2. **Document your code**: Include docstrings and comments
3. **Handle errors gracefully**: Use try/except blocks and log warnings
4. **Be efficient**: Use parallel processing for performance-critical operations
5. **Check for existence**: Always verify that files/directories exist before accessing them
6. **Add meaningful labels**: Include useful metadata with each log
7. **Detect rotated logs**: Look for rotated log files (use `_find_rotated_logs()` helper)
8. **Follow conventions**: Use the same patterns as the existing modules

## Further Customization

If you need more advanced customization, you can:

1. Modify the `log_source.py` file to enhance the base class
2. Edit the main `log_discovery.py` script to change how modules are loaded
3. Create a module that extends another module's functionality

## Contributing Modules

If you create a module for a common system, consider contributing it back to the project by:

1. Testing thoroughly on different environments
2. Following the coding style of the existing modules
3. Including documentation in the module docstring
4. Submitting a pull request