# Log Discovery System for OpenLiteSpeed/CyberPanel/WordPress

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
  - Intelligent categorization and labeling
- **Smart labeling**: Automatically adds relevant labels like:
  - Log source type (openlitespeed, wordpress, etc.)
  - Service type (webserver, database, etc.)
  - Error level (error, access, debug, etc.)
  - Domain/site name (where applicable)

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
apt-get install -y python3 python3-yaml

# For CentOS/RHEL
yum install -y python3 python3-pyyaml
```

## Usage

### Basic Usage

Run the discovery script:

```bash
./run_log_discovery.sh
```

This will:
1. Scan your system for OpenLiteSpeed, CyberPanel, and WordPress installations
2. Analyze their configuration files to find log locations
3. Create a structured output file at `output/discovered_logs.json`

### Advanced Options

```
Usage: ./run_log_discovery.sh [options]

Options:
  -h, --help             Show this help message
  -v, --verbose          Enable verbose output
  -o, --output FILE      Output file path (default: output/discovered_logs.json)
  -f, --format FORMAT    Output format: json or yaml (default: json)
  -c, --cron             Run in cron mode (minimal output, only errors to stderr)
```

### Example: Running in verbose mode with YAML output

```bash
./run_log_discovery.sh --verbose --format yaml --output /tmp/my_logs.yaml
```

## Integrating with Loki/Promtail

The output file can be used to configure Promtail to send logs to Loki. Here's how to integrate with your existing Loki/Promtail setup:

### Option 1: Manual Configuration

1. Run the log discovery:

```bash
./run_log_discovery.sh --format yaml --output /tmp/discovered_logs.yaml
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

### Example Promtail Output Structure

Here's how a Promtail configuration might look after integrating the discovered logs:

```yaml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

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
      __path__: {/usr/local/lsws/logs/error.log|/usr/local/lsws/logs/access.log}

  # WordPress logs for example.com
  - job_name: wordpress_example_com
    static_configs:
    - targets:
        - localhost
      labels:
        job: wordpress_example_com
        source: wordpress
        service: wordpress
        site: example_com
        domain: example.com
      __path__: /var/www/example.com/wp-content/debug.log

  # PHP logs
  - job_name: php
    static_configs:
    - targets:
        - localhost
      labels:
        job: php
        source: php
        service: php
        level: error
      __path__: /var/log/php/error.log
```

## Scheduling Regular Discovery

You can set up a cron job to regularly discover logs:

```bash
# Edit crontab
crontab -e

# Add a job to run discovery daily at 4 AM
0 4 * * * /opt/log-discovery/run_log_discovery.sh --cron --output /etc/promtail/discovered_logs.yaml

# Add another job to update Promtail config and restart it
5 4 * * * python3 /opt/log-discovery/update_promtail.py && systemctl restart promtail
```

## Output Format

The discovery script outputs a structured JSON or YAML file with detailed information about each log file:

```json
{
  "metadata": {
    "generated_at": "2025-04-21T15:30:22",
    "version": "1.0.0",
    "hostname": "webserver1"
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
      "last_modified": "2025-04-21T14:25:16"
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
      "last_modified": "2025-04-21T15:12:03"
    }
  ]
}
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
   ./run_log_discovery.sh --verbose
   ```

3. Check file permissions:
   - The script needs to be able to read configuration files
   - Run with sudo if necessary: `sudo ./run_log_discovery.sh`

### Error: "ModuleNotFoundError: No module named 'yaml'"

Install the PyYAML package:

```bash
pip3 install pyyaml
```

## Contributing

Feel free to modify the scripts to match your specific environment or add support for additional log sources.
