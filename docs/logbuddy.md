# LogBuddy - Unified Log Discovery and Monitoring System

LogBuddy is a comprehensive tool for discovering, configuring, and monitoring logs on Linux servers. It integrates several components to provide a seamless experience from log discovery to visualization with Grafana Loki.

## Features

- **Smart Log Discovery**: Finds log files by examining actual configuration files rather than just scanning for common patterns
- **Multi-application support**: Discovers logs for:
  - OpenLiteSpeed web server
  - CyberPanel admin panel
  - WordPress sites
  - PHP configuration
  - MySQL/MariaDB database
- **Interactive Configuration**: User-friendly terminal UI for selecting which logs to monitor
- **Integrated Monitoring**: Easy setup of Loki and Promtail with sensible defaults
- **Unified Command Line**: Single `logbuddy` command for all operations
- **Modular Design**: Easy to extend with support for additional log types
- **Container Integration**: Works with both Podman and Docker

## Installation

### Quick Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/logbuddy.git
cd logbuddy

# Run the installer as root
sudo ./install.sh install
```

### Advanced Installation Options

```bash
# Install without systemd service
sudo ./install.sh install --no-service

# Install with custom discovery interval (cron syntax)
sudo ./install.sh install --interval "0 */4 * * *"

# Install with email notifications
sudo ./install.sh install --email admin@example.com

# Skip dependency installation
sudo ./install.sh install --no-deps
```

## Usage

LogBuddy provides a unified command-line interface with several subcommands:

### Discovering Logs

```bash
# Basic log discovery
logbuddy discover

# With verbose output
logbuddy discover --verbose

# Filter by log types
logbuddy discover --include openlitespeed,wordpress,php

# Exclude specific log types
logbuddy discover --exclude mysql

# Validate log permissions
logbuddy discover --validate
```

### Configuring Monitored Logs

```bash
# Launch interactive configuration UI
logbuddy config
```

This will open a terminal-based UI where you can:
- Navigate through a directory tree of discovered logs
- View logs by type or service
- Select/deselect logs to monitor
- Preview the generated configuration
- Save your configuration

### Installing Loki and Promtail

```bash
# Install Loki and Promtail with Podman (default)
logbuddy install
```

This will guide you through setting up Loki and Promtail containers with the proper configuration.

### Starting and Stopping Monitoring

```bash
# Start monitoring with default options
logbuddy start

# Start with Docker instead of Podman
logbuddy start --engine docker

# Start with custom container names
logbuddy start --promtail my-promtail --loki my-loki

# Force update even if configuration hasn't changed
logbuddy start --force

# Stop monitoring
logbuddy stop
```

### Checking Monitoring Status

```bash
# Check status of monitoring components
logbuddy status

# With custom container engine or names
logbuddy status --engine docker --promtail my-promtail --loki my-loki
```

### Updating Promtail Configuration

```bash
# Update Promtail configuration after changing settings
logbuddy update

# Update and immediately update the container
logbuddy update --docker-update
```

## Viewing Logs in Grafana

After setting up LogBuddy, you can configure Grafana to use Loki as a data source:

1. In Grafana, go to Configuration > Data Sources
2. Click "Add data source" and select "Loki"
3. Set the URL to `http://localhost:3100` (or your server's IP)
4. Enable basic authentication and enter the credentials from your installation
5. Click "Save & Test"

Once connected, you can create dashboards to visualize your logs.

## Directory Structure

```
/opt/logbuddy             # Main installation directory
├── logbuddy.py           # Main executable
├── runner.sh             # Log discovery runner
├── log_discovery.py      # Log discovery script
├── log_source.py         # Base class for log sources
├── modules/              # Log source modules
│   ├── openlitespeed.py  # OpenLiteSpeed log discovery
│   ├── wordpress.py      # WordPress log discovery
│   ├── php.py            # PHP log discovery
│   ├── mysql.py          # MySQL log discovery
│   ├── cyberpanel.py     # CyberPanel log discovery
│   └── ...
├── bridges/              # Integration bridges
│   ├── podman.sh         # Podman integration
│   ├── promtail.py       # Promtail config generator
│   └── promtail-conf-gen.py # Interactive config UI
└── misc/                 # Miscellaneous utilities
    └── podman-loki-promtail.sh # Loki/Promtail setup

/etc/logbuddy             # Configuration files
├── config.json           # Main configuration
├── promtail-config.yaml  # Generated Promtail config
└── promtail-config-settings.yaml # User selections

/var/lib/logbuddy         # Data files
├── discovered_logs.json  # Discovery results
└── output/               # Output files

/var/log/logbuddy         # Log files
```

## Extending LogBuddy

### Adding New Log Sources

To add support for a new log source:

1. Create a new Python file in the `modules` directory (e.g., `nginx.py`)
2. Use the template in `modules/example_template.py` as a starting point
3. Implement the `discover()` method to find logs of your type
4. Ensure your module has a `get_log_source()` function

The module will be automatically loaded and used during log discovery.

### Customizing Promtail Configuration

The Promtail configuration can be customized by editing:

```bash
/etc/logbuddy/promtail-config-settings.yaml
```

After making changes, run:

```bash
logbuddy update
```

## Troubleshooting

### Common Issues

#### No logs found

If LogBuddy doesn't find any logs:

1. Make sure you have the applications installed
2. Run with verbose mode: `logbuddy discover --verbose`
3. Check the log files: `cat /var/log/logbuddy/discovery.log`

#### Monitoring not working

If monitoring isn't working:

1. Check the status: `logbuddy status`
2. Verify the container logs: `podman logs promtail` or `docker logs promtail`
3. Ensure Promtail can access your log files
4. Check Loki API: `curl -s http://localhost:3100/ready`

### Log Locations

- LogBuddy logs: `/var/log/logbuddy/*.log`
- Promtail logs: Inside the container, check with `podman logs promtail`
- Loki logs: Inside the container, check with `podman logs loki`

## Uninstalling

To remove LogBuddy:

```bash
sudo ./install.sh remove
```

To remove everything including configuration and logs:

```bash
sudo ./install.sh remove
# Answer 'y' when asked about removing configuration files and logs
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.