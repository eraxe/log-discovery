# LogBuddy Integration Guide

This guide explains how all the components of LogBuddy work together to provide a seamless log discovery and monitoring experience.

## System Architecture

LogBuddy integrates several components to create a unified log management solution:

1. **Core Log Discovery Engine**
   - `log_discovery.py`: Main log discovery script that finds log files
   - `log_source.py`: Base class for log source modules
   - `modules/`: Pluggable modules for different log types (OpenLiteSpeed, WordPress, etc.)

2. **Runner and Command-Line Interface**
   - `runner.sh`: Script that runs the log discovery process
   - `logbuddy.py`: Main entry point with unified command structure

3. **Configuration Management**
   - `bridges/promtail-conf-gen.py`: Interactive TUI for configuring which logs to monitor
   - `bridges/promtail.py`: Generator for Promtail configuration

4. **Monitoring Integration**
   - `bridges/podman.sh`: Integration with Podman/Docker containers
   - `misc/podman-loki-promtail.sh`: Setup script for Loki and Promtail

5. **Support Components**
   - `install.sh`: Installation and management script
   - Systemd service and timer files
   - Bash completion script

## Data Flow

Here's how data flows through the system:

1. Log Discovery Process:
   ```
   logbuddy discover → runner.sh → log_discovery.py → modules/* → discovered_logs.json
   ```

2. Configuration Process:
   ```
   logbuddy config → promtail-conf-gen.py → promtail-config-settings.yaml
   logbuddy update → promtail.py → promtail-config.yaml
   ```

3. Monitoring Process:
   ```
   logbuddy install → podman-loki-promtail.sh → loki & promtail containers
   logbuddy start → podman.sh → updates running containers
   ```

## Component Interactions

### 1. Log Discovery

The log discovery process is the foundation of LogBuddy:

- `log_discovery.py` loads available modules from the `modules/` directory
- Each module scans for a specific type of log (OpenLiteSpeed, WordPress, etc.)
- Modules implement the `LogSource` base class defined in `log_source.py`
- Results are saved to a JSON file (`discovered_logs.json`)

### 2. Configuration

The configuration process allows the user to select which logs to monitor:

- `promtail-conf-gen.py` provides an interactive terminal UI
- It reads the `discovered_logs.json` file and presents logs in different views:
  - Directory tree view
  - By log type
  - By service
- User selections are saved to `promtail-config-settings.yaml`
- `promtail.py` uses these settings to generate Promtail configuration

### 3. Monitoring

The monitoring integration connects LogBuddy to Loki and Promtail:

- `podman-loki-promtail.sh` sets up the containers and initial configuration
- `podman.sh` updates the containers when configuration changes
- Promtail reads logs specified in `promtail-config.yaml`
- Logs are sent to Loki for storage and querying
- Grafana can be used to visualize logs from Loki

## Directory Structure and File Locations

- **Installation Directory** (`/opt/logbuddy/`):
  - Main executables and scripts
  - Module and bridge directories

- **Configuration Directory** (`/etc/logbuddy/`):
  - `config.json`: Main configuration
  - `promtail-config-settings.yaml`: User selections
  - `promtail-config.yaml`: Generated Promtail configuration
  - `loki-config.yaml`: Loki configuration

- **Data Directory** (`/var/lib/logbuddy/`):
  - `discovered_logs.json`: Log discovery results
  - `output/`: Output files
  - `loki/`: Loki data files
  - `positions.yaml`: Promtail positions file

- **Log Directory** (`/var/log/logbuddy/`):
  - Log files for LogBuddy itself

## Command Flow

The `logbuddy` command ties everything together:

1. `logbuddy discover`:
   - Calls `runner.sh` to run log discovery
   - Outputs results to `discovered_logs.json`

2. `logbuddy config`:
   - Launches `promtail-conf-gen.py` for interactive configuration
   - Saves settings to `promtail-config-settings.yaml`
   - Calls `promtail.py` to generate `promtail-config.yaml`

3. `logbuddy install`:
   - Runs `podman-loki-promtail.sh` to set up containers
   - Creates necessary directories and files

4. `logbuddy start`:
   - Calls `podman.sh` to update and start containers
   - Ensures configuration is applied

5. `logbuddy stop`:
   - Stops the monitoring containers

6. `logbuddy status`:
   - Checks the status of monitoring components

7. `logbuddy update`:
   - Updates Promtail configuration based on settings
   - Optionally updates the container

## Extending the System

### Adding New Log Sources

To add support for a new log source:

1. Create a new module in the `modules/` directory
2. Implement the `LogSource` base class
3. Add a `get_log_source()` function
4. The module will be automatically discovered and used

Example:
```python
from log_source import LogSource

class NginxLogSource(LogSource):
    def discover(self):
        # Implementation here
        return self.logs_found

def get_log_source():
    return NginxLogSource
```

### Customizing Promtail Configuration

The Promtail configuration can be extended by:

1. Modifying `promtail-conf-gen.py` to add new configuration options
2. Updating `promtail.py` to use these options in the generated configuration

### Adding New Commands

To add a new command to LogBuddy:

1. Add a new subparser in `logbuddy.py`
2. Implement a corresponding function
3. Update the bash completion script

## Troubleshooting the Integration

### Common Integration Issues

1. **Discovery not finding logs**:
   - Check module implementation
   - Verify file permissions
   - Run with `--verbose` flag

2. **Configuration not being applied**:
   - Check file paths in `promtail-config.yaml`
   - Verify Promtail container can access log files

3. **Container connectivity issues**:
   - Ensure Loki and Promtail containers can communicate
   - Check network configuration

### Log Sources

Look for issues in specific component logs:

- LogBuddy: `/var/log/logbuddy/*.log`
- Promtail: `podman logs promtail`
- Loki: `podman logs loki`

### Debugging Commands

```bash
# Check if log discovery is working
logbuddy discover --verbose

# Verify configuration generation
cat /etc/logbuddy/promtail-config.yaml

# Check container status
podman ps -a | grep 'loki\|promtail'

# Verify Loki is responding
curl -s http://localhost:3100/ready
```

## Conclusion

LogBuddy provides a unified experience for log discovery and monitoring by integrating multiple components that work together seamlessly. The modular design allows for easy extension and customization while maintaining a simple user interface through the unified `logbuddy` command.