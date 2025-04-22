# LogBuddy Workflow Guide

This guide explains the improved LogBuddy workflow and how it simplifies your log discovery and monitoring experience.

## New User Workflow

### First Time Setup (New!)

When you first run LogBuddy, the system will offer to run the setup wizard:

```bash
logbuddy init
```

The setup wizard walks you through:

1. **Choosing a monitoring backend** (Loki/Promtail or discovery-only mode)
2. **Configuring discovery settings** (how often to scan for logs)
3. **Setting user interface preferences** (whether to use the tree view or auto-select logs)
4. **Configuring notification settings** (email notifications)

After completing the wizard, LogBuddy automatically:
- Runs an initial log discovery
- Configures which logs to monitor (with or without manual selection)
- Offers to install and start the monitoring backend

### Quick Start

If you just want to get up and running with minimal interaction:

```bash
# Run the setup wizard
logbuddy init

# Choose automatic configuration during the wizard
# Select "Skip the tree view and use recommended settings"

# Install and start monitoring when prompted
```

This provides a nearly one-command setup process!

## Regular User Workflow

Once LogBuddy is set up, the common workflow is:

1. **Discover logs** (automatically scheduled or manually):
   ```bash
   logbuddy discover
   ```

2. **Check monitoring status**:
   ```bash
   logbuddy status
   ```

3. **If needed, reconfigure logs**:
   ```bash
   logbuddy config
   ```

## Advanced Features

### Settings Management

LogBuddy now includes a dedicated settings command:

```bash
# View all settings
logbuddy settings

# Change a specific setting
logbuddy settings set discovery interval hourly

# Reset to defaults
logbuddy settings reset

# Export settings to file
logbuddy settings export --file my-settings.json

# Import settings from file
logbuddy settings import --file my-settings.json
```

### Non-Interactive Mode

For automated deployments or scripting:

```bash
# Discover logs non-interactively
logbuddy discover --verbose

# Configure with recommended settings (no tree view)
logbuddy config --auto-select recommended

# Install and start monitoring
logbuddy install
logbuddy start
```

## Configuration Flexibility

### Tree View Configuration (Optional)

The tree view for selecting logs is now optional:

- **Skip tree view**: LogBuddy can automatically select recommended logs
- **Use tree view**: When you want granular control over which logs to monitor

This preference is set during initial setup and can be changed via:

```bash
logbuddy settings set ui skip_tree_view false
```

### Multiple Backend Support

LogBuddy now supports multiple monitoring backends (currently Loki/Promtail with more planned):

```bash
# Change monitoring backend
logbuddy settings set monitoring backend loki-promtail

# Install specific backend
logbuddy install --backend loki-promtail
```

## Comparison with Old Workflow

| Task | Old Workflow | New Workflow |
|------|-------------|-------------|
| Initial Setup | Multiple manual commands | `logbuddy init` |
| Log Discovery | `logbuddy discover` | `logbuddy discover` (automatic after setup) |
| Configure Logs | Always manual tree view | Optional: automatic or tree view |
| Start Monitoring | Multiple steps | `logbuddy start` (automatic after setup) |
| Change Settings | Edit config files manually | `logbuddy settings set section key value` |
| Full System Check | Multiple commands | `logbuddy status` |

The new workflow significantly reduces the number of commands needed for common tasks and provides a smoother user experience.