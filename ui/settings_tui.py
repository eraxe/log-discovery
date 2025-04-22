#!/usr/bin/env python3
"""
LogBuddy Settings TUI

A text-based user interface for managing LogBuddy settings with:
- Navigable categories
- Visual toggles, selectors, and input fields
- Help text and tooltips
- System detection

This file should be placed in the ui/ directory of the LogBuddy project.
"""

import os
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from core.system_detect import detect_system_config

import os
import sys
import json
import curses
import signal
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Union, Tuple, Optional, Set

# Configuration constants
CONFIG_DIR = "/etc/logbuddy"
DEFAULT_CONFIG = f"{CONFIG_DIR}/config.json"

# Color pairs
COLOR_NORMAL = 1
COLOR_SELECTED = 2
COLOR_ENABLED = 3
COLOR_DISABLED = 4
COLOR_TITLE = 5
COLOR_STATUS = 6
COLOR_HELP = 7

# Global state to store curses objects
curses_state = {
    'screen': None,
    'max_y': 0,
    'max_x': 0
}

# Settings metadata and help text
SETTINGS_METADATA = {
    "discovery": {
        "title": "Log Discovery Settings",
        "help": "Configure how LogBuddy finds logs on your system",
        "settings": {
            "enabled": {
                "type": "boolean",
                "help": "Enable automatic log discovery",
                "options": [True, False]
            },
            "interval": {
                "type": "choice",
                "help": "How often to run log discovery",
                "options": ["hourly", "daily", "weekly", "monthly", "manual"]
            },
            "include_types": {
                "type": "multiselect",
                "help": "Only include these log types (empty = all)",
                "options": ["openlitespeed", "wordpress", "php", "mysql", "cyberpanel"]
            },
            "exclude_types": {
                "type": "multiselect",
                "help": "Exclude these log types from discovery",
                "options": ["openlitespeed", "wordpress", "php", "mysql", "cyberpanel"]
            },
            "validate_logs": {
                "type": "boolean",
                "help": "Check if discovered logs exist and are readable",
                "options": [True, False]
            },
            "timeout": {
                "type": "number",
                "help": "Maximum time in seconds for discovery to run",
                "min": 30,
                "max": 3600,
                "step": 30,
                "recommended": [300, 600, 1200]
            }
        }
    },
    "monitoring": {
        "title": "Monitoring Settings",
        "help": "Configure how LogBuddy monitors logs",
        "settings": {
            "backend": {
                "type": "choice",
                "help": "Monitoring backend to use",
                "options": ["loki-promtail", "none"]
            },
            "container_engine": {
                "type": "choice",
                "help": "Container engine for Loki/Promtail",
                "options": ["podman", "docker"],
                "detect": "detect_container_engine"
            },
            "promtail_container": {
                "type": "text",
                "help": "Name for the Promtail container",
                "default": "promtail"
            },
            "loki_container": {
                "type": "text",
                "help": "Name for the Loki container",
                "default": "loki"
            },
            "auto_start": {
                "type": "boolean",
                "help": "Start monitoring automatically after setup",
                "options": [True, False]
            },
            "port": {
                "type": "number",
                "help": "Port for Loki API",
                "min": 1024,
                "max": 65535,
                "recommended": [3100, 9096, 8080],
                "detect": "detect_available_port"
            },
            "credentials": {
                "type": "section",
                "help": "Authentication credentials for Loki",
                "settings": {
                    "username": {
                        "type": "text",
                        "help": "Username for Loki authentication",
                        "default": "admin"
                    },
                    "password": {
                        "type": "password",
                        "help": "Password for Loki authentication",
                        "default": "",
                        "generate": True
                    }
                }
            }
        }
    },
    "output": {
        "title": "Output Settings",
        "help": "Configure how LogBuddy generates output",
        "settings": {
            "format": {
                "type": "choice",
                "help": "Output format for discovery results",
                "options": ["json", "yaml"]
            },
            "path": {
                "type": "path",
                "help": "Path to output discovery results",
                "default": "/var/lib/logbuddy/discovered_logs.json"
            },
            "notify_email": {
                "type": "text",
                "help": "Email address for notifications (empty = no emails)",
                "default": ""
            }
        }
    },
    "ui": {
        "title": "User Interface Settings",
        "help": "Configure the LogBuddy user interface",
        "settings": {
            "skip_tree_view": {
                "type": "boolean",
                "help": "Skip tree view and use recommended settings",
                "options": [True, False]
            },
            "auto_select_recommended": {
                "type": "boolean",
                "help": "Automatically select recommended logs",
                "options": [True, False]
            },
            "theme": {
                "type": "choice",
                "help": "UI theme for LogBuddy",
                "options": ["default", "dark", "light", "simple"]
            }
        }
    },
    "system": {
        "title": "System Settings",
        "help": "System-related settings (usually handled automatically)",
        "settings": {
            "first_run": {
                "type": "boolean",
                "help": "Is this the first run of LogBuddy?",
                "options": [True, False],
                "readonly": True
            },
            "setup_completed": {
                "type": "boolean",
                "help": "Has setup been completed?",
                "options": [True, False],
                "readonly": True
            },
            "version": {
                "type": "text",
                "help": "LogBuddy version",
                "readonly": True
            },
            "last_discovery": {
                "type": "text",
                "help": "Timestamp of last log discovery",
                "readonly": True
            }
        }
    }
}


class SettingsNode:
    """Node in settings hierarchy."""

    def __init__(self, name: str, path: str, node_type: str, parent=None,
                 value=None, metadata=None):
        self.name = name  # Display name
        self.path = path  # Full path to setting (e.g., "discovery.interval")
        self.type = node_type  # "section", "setting", "category"
        self.parent = parent  # Parent node
        self.children = []  # Child nodes
        self.value = value  # Current value
        self.metadata = metadata or {}  # Setting metadata
        self.is_expanded = False
        self.is_editing = False
        self.edit_value = None  # Temporary value during editing
        self.is_selected = False

    def add_child(self, child):
        """Add a child node."""
        self.children.append(child)

    def toggle_expanded(self):
        """Toggle expanded state."""
        if self.children:
            self.is_expanded = not self.is_expanded

    def start_editing(self):
        """Start editing this node's value."""
        if self.metadata.get("readonly", False):
            return False

        self.is_editing = True
        self.edit_value = self.value
        return True

    def stop_editing(self, save=True):
        """Stop editing this node's value."""
        self.is_editing = False
        if save and self.edit_value != self.value:
            self.value = self.edit_value
            return True
        self.edit_value = None
        return False

    def toggle_bool(self):
        """Toggle boolean value."""
        if self.type == "setting" and self.metadata.get("type") == "boolean":
            if not self.metadata.get("readonly", False):
                self.value = not self.value
                return True
        return False

    def cycle_choice(self):
        """Cycle through available choices."""
        if self.type == "setting" and self.metadata.get("type") == "choice":
            if not self.metadata.get("readonly", False):
                options = self.metadata.get("options", [])
                if options:
                    current_index = options.index(self.value) if self.value in options else -1
                    next_index = (current_index + 1) % len(options)
                    self.value = options[next_index]
                    return True
        return False


class SettingsManager:
    """Manager for settings hierarchy and values."""

    def __init__(self, config_path=DEFAULT_CONFIG):
        self.config_path = config_path
        self.settings = {}
        self.root_node = None
        self.current_node = None
        self.visible_nodes = []
        self.status_message = ""
        self.show_help = False
        self.exit_requested = False
        self.save_requested = False
        self.modified = False
        self.load_settings()
        self.build_tree()

    def load_settings(self):
        """Load settings from config file."""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    self.settings = json.load(f)
            else:
                # Create a default settings structure based on metadata
                self.settings = {}
                for category, category_meta in SETTINGS_METADATA.items():
                    self.settings[category] = {}
                    for setting, setting_meta in category_meta.get("settings", {}).items():
                        if setting_meta["type"] == "section":
                            self.settings[category][setting] = {}
                            for subsetting, subsetting_meta in setting_meta.get("settings", {}).items():
                                self.settings[category][setting][subsetting] = subsetting_meta.get("default", "")
                        else:
                            self.settings[category][setting] = setting_meta.get("default", "")
        except Exception as e:
            self.status_message = f"Error loading settings: {str(e)}"
            self.settings = {}

    def save_settings(self):
        """Save settings to config file."""
        try:
            # Create config directory if it doesn't exist
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)

            # Update settings from tree
            self.update_settings_from_tree()

            # Save to file
            with open(self.config_path, 'w') as f:
                json.dump(self.settings, f, indent=2)

            self.status_message = "Settings saved successfully"
            self.modified = False
            return True
        except Exception as e:
            self.status_message = f"Error saving settings: {str(e)}"
            return False

    def update_settings_from_tree(self):
        """Update settings dictionary from tree values."""

        def update_from_node(node):
            if node.type == "setting":
                # Parse the path to navigate the settings dictionary
                path_parts = node.path.split(".")
                target = self.settings
                for i, part in enumerate(path_parts[:-1]):
                    if part not in target:
                        target[part] = {}
                    target = target[part]
                target[path_parts[-1]] = node.value

            # Process children
            for child in node.children:
                update_from_node(child)

        # Start from root
        if self.root_node:
            for child in self.root_node.children:
                update_from_node(child)

    def build_tree(self):
        """Build tree structure from settings."""
        # Create root node
        self.root_node = SettingsNode("Settings", "", "root")

        # Add categories
        for category, category_meta in SETTINGS_METADATA.items():
            category_node = SettingsNode(
                category_meta.get("title", category),
                category,
                "category",
                self.root_node,
                metadata=category_meta
            )
            self.root_node.add_child(category_node)

            # Add settings
            for setting, setting_meta in category_meta.get("settings", {}).items():
                if setting_meta["type"] == "section":
                    # This is a nested section
                    section_node = SettingsNode(
                        setting.replace("_", " ").title(),
                        f"{category}.{setting}",
                        "section",
                        category_node,
                        metadata=setting_meta
                    )
                    category_node.add_child(section_node)

                    # Get the section value from settings
                    section_value = self.settings.get(category, {}).get(setting, {})

                    # Add subsettings
                    for subsetting, subsetting_meta in setting_meta.get("settings", {}).items():
                        subsetting_node = SettingsNode(
                            subsetting.replace("_", " ").title(),
                            f"{category}.{setting}.{subsetting}",
                            "setting",
                            section_node,
                            value=section_value.get(subsetting, subsetting_meta.get("default", "")),
                            metadata=subsetting_meta
                        )
                        section_node.add_child(subsetting_node)
                else:
                    # This is a regular setting
                    setting_node = SettingsNode(
                        setting.replace("_", " ").title(),
                        f"{category}.{setting}",
                        "setting",
                        category_node,
                        value=self.settings.get(category, {}).get(setting, setting_meta.get("default", "")),
                        metadata=setting_meta
                    )
                    category_node.add_child(setting_node)

        # Set initial expanded state
        self.root_node.is_expanded = True
        if self.root_node.children:
            self.current_node = self.root_node.children[0]
            self.current_node.is_expanded = True

    def detect_container_engine(self):
        """Detect available container engine."""
        engines = []

        # Check for podman
        try:
            result = subprocess.run(
                ["which", "podman"],
                capture_output=True, text=True, check=False
            )
            if result.returncode == 0:
                engines.append("podman")
        except:
            pass

        # Check for docker
        try:
            result = subprocess.run(
                ["which", "docker"],
                capture_output=True, text=True, check=False
            )
            if result.returncode == 0:
                engines.append("docker")
        except:
            pass

        return engines[0] if engines else "podman"

    def detect_available_port(self, start_port=3100):
        """Detect an available port starting from start_port."""
        import socket

        port = start_port
        while port < 65535:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(('localhost', port)) != 0:
                    # Port is available
                    return port
            port += 1

        # If no port found, return the starting port
        return start_port

    def get_flat_tree(self):
        """Get a flattened list of tree nodes for display."""
        nodes = []

        def traverse(node, level=0):
            nodes.append((node, level))
            if node.is_expanded:
                for child in node.children:
                    traverse(child, level + 1)

        if self.root_node:
            traverse(self.root_node)

        return nodes

    def run_detection(self, node):
        """Run detection for a setting if applicable."""
        if node.type != "setting":
            return False

        detect_method = node.metadata.get("detect")
        if not detect_method:
            return False

        if detect_method == "detect_container_engine":
            node.value = self.detect_container_engine()
            return True
        elif detect_method == "detect_available_port":
            node.value = self.detect_available_port()
            return True

        return False

    def run_all_detections(self):
        """Run all available detections throughout the tree."""
        detections_run = 0

        def traverse(node):
            nonlocal detections_run
            if self.run_detection(node):
                detections_run += 1

            for child in node.children:
                traverse(child)

        if self.root_node:
            traverse(self.root_node)

        if detections_run > 0:
            self.status_message = f"Detected {detections_run} setting(s) automatically"
            self.modified = True

        return detections_run


def initialize_curses():
    """Initialize curses environment."""
    # Set up terminal
    screen = curses.initscr()
    curses.start_color()
    curses.use_default_colors()
    curses.cbreak()
    curses.noecho()
    screen.keypad(True)
    curses.curs_set(0)  # Hide cursor

    # Initialize color pairs
    curses.init_pair(COLOR_NORMAL, curses.COLOR_WHITE, -1)
    curses.init_pair(COLOR_SELECTED, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(COLOR_ENABLED, curses.COLOR_GREEN, -1)
    curses.init_pair(COLOR_DISABLED, curses.COLOR_RED, -1)
    curses.init_pair(COLOR_TITLE, curses.COLOR_CYAN, -1)
    curses.init_pair(COLOR_STATUS, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(COLOR_HELP, curses.COLOR_YELLOW, -1)

    # Store screen dimensions
    max_y, max_x = screen.getmaxyx()
    curses_state['screen'] = screen
    curses_state['max_y'] = max_y
    curses_state['max_x'] = max_x

    return screen


def cleanup_curses():
    """Clean up curses environment."""
    if curses_state['screen']:
        curses_state['screen'].keypad(False)
        curses.nocbreak()
        curses.echo()
        curses.endwin()


def signal_handler(sig, frame):
    """Handle signals to clean up curses before exiting."""
    cleanup_curses()
    sys.exit(0)


def draw_screen(settings_manager):
    """Draw the main screen."""
    screen = curses_state['screen']
    max_y, max_x = screen.getmaxyx()
    curses_state['max_y'] = max_y
    curses_state['max_x'] = max_x

    # Clear screen
    screen.clear()

    # Draw title bar
    screen.attron(curses.color_pair(COLOR_TITLE) | curses.A_BOLD)
    title = "LogBuddy Settings Manager"
    screen.addstr(0, (max_x - len(title)) // 2, title)
    screen.attroff(curses.color_pair(COLOR_TITLE) | curses.A_BOLD)

    # Draw horizontal line
    screen.addstr(1, 0, "=" * max_x)

    # Calculate tree view area
    tree_start_y = 2
    tree_end_y = max_y - 3  # Leave space for status bar and help line
    tree_height = tree_end_y - tree_start_y

    # Get flattened tree
    flat_tree = settings_manager.get_flat_tree()
    settings_manager.visible_nodes = flat_tree

    # Draw visible part of tree
    for i in range(tree_height):
        if i < len(flat_tree):
            node, level = flat_tree[i]
            draw_tree_node(screen, tree_start_y + i, node, level, node == settings_manager.current_node)

    # Draw status bar
    draw_status_bar(screen, max_y - 2, settings_manager)

    # Draw help line
    help_text = "↑/↓: Navigate | →/←/SPACE: Expand/Collapse | ENTER: Edit | d: Detect | s: Save | q: Exit | h: Help"
    screen.addstr(max_y - 1, 0, help_text[:max_x - 1], curses.color_pair(COLOR_HELP))

    # Show help if requested
    if settings_manager.show_help:
        draw_help_window(screen, settings_manager)

    # Refresh screen
    screen.refresh()


def draw_tree_node(screen, y, node, level, is_current):
    """Draw a single tree node."""
    max_y, max_x = curses_state['max_y'], curses_state['max_x']
    if y < 0 or y >= max_y:
        return

    # Calculate indent based on level
    indent = level * 2
    max_text_width = max_x - indent - 10  # Leave space for indicators

    # Prepare indicators
    if node.children:
        expand_indicator = "▼" if node.is_expanded else "▶"
    else:
        expand_indicator = " "

    # Get node display name and value
    display_name = node.name

    # Format value based on type
    if node.type == "setting":
        setting_type = node.metadata.get("type", "text")

        if setting_type == "boolean":
            value_display = "ON" if node.value else "OFF"
            value_color = COLOR_ENABLED if node.value else COLOR_DISABLED
        elif setting_type == "password" and node.value:
            value_display = "********"
            value_color = COLOR_NORMAL
        elif setting_type == "multiselect" and isinstance(node.value, list):
            value_display = ", ".join(node.value) if node.value else "(none)"
            value_color = COLOR_NORMAL
        else:
            value_display = str(node.value) if node.value is not None else ""
            value_color = COLOR_NORMAL

        # Truncate if too long
        if len(value_display) > max_text_width - len(display_name) - 5:
            value_display = value_display[:max_text_width - len(display_name) - 8] + "..."
    else:
        value_display = ""
        value_color = COLOR_NORMAL

    # Construct the full line
    line = " " * indent + expand_indicator + " " + display_name

    # Draw with appropriate attributes
    if is_current:
        attr = curses.color_pair(COLOR_SELECTED) | curses.A_BOLD
    else:
        attr = curses.color_pair(COLOR_NORMAL)

    screen.addstr(y, 0, " " * max_x)  # Clear line
    screen.addstr(y, 0, line[:max_x - len(value_display) - 5], attr)

    # Draw value with appropriate color
    if value_display:
        value_x = max_x - len(value_display) - 2
        if value_x > len(line) + 1:  # Ensure there's space between name and value
            screen.addstr(y, value_x, value_display,
                          curses.color_pair(value_color) |
                          (curses.A_BOLD if is_current else 0))


def draw_status_bar(screen, y, settings_manager):
    """Draw the status bar."""
    max_y, max_x = curses_state['max_y'], curses_state['max_x']
    if y < 0 or y >= max_y:
        return

    # Prepare status message
    status = " "

    # Add help text for current node
    if settings_manager.current_node:
        if settings_manager.current_node.type == "setting":
            help_text = settings_manager.current_node.metadata.get("help", "")
            if help_text:
                status = f" {help_text}"
        elif settings_manager.current_node.metadata:
            help_text = settings_manager.current_node.metadata.get("help", "")
            if help_text:
                status = f" {help_text}"

    # Add custom message if present
    if settings_manager.status_message:
        status = f" {settings_manager.status_message}"

    # Add modified indicator
    if settings_manager.modified:
        status += " [Modified]"

    # Draw status bar
    screen.addstr(y, 0, " " * max_x, curses.color_pair(COLOR_STATUS))
    screen.addstr(y, 0, status[:max_x - 1], curses.color_pair(COLOR_STATUS))


def draw_help_window(screen, settings_manager):
    """Draw a help window overlay."""
    max_y, max_x = curses_state['max_y'], curses_state['max_x']

    # Calculate window dimensions
    help_height = 14
    help_width = 60
    help_y = (max_y - help_height) // 2
    help_x = (max_x - help_width) // 2

    # Create a sub-window
    if help_y > 0 and help_x > 0 and help_y + help_height < max_y and help_x + help_width < max_x:
        help_win = curses.newwin(help_height, help_width, help_y, help_x)
        help_win.box()

        # Draw title
        help_win.addstr(0, (help_width - 4) // 2, "HELP", curses.A_BOLD)

        # Draw help content
        help_lines = [
            "Arrow Keys: Navigate through settings",
            "SPACE: Expand/collapse categories",
            "ENTER: Edit selected setting",
            "→/←: Expand/collapse or navigate",
            "Tab: Cycle through setting values",
            "d: Detect settings automatically",
            "s: Save settings and exit",
            "q: Exit (will prompt to save changes)",
            "h: Toggle this help window",
            "",
            "ON/OFF indicates boolean settings",
            "Settings with detection will show (Auto)",
            ""
        ]

        for i, line in enumerate(help_lines, 1):
            if i < help_height - 1:
                help_win.addstr(i, 2, line[:help_width - 4])

        # Draw close instruction
        help_win.addstr(help_height - 2, 2, "Press any key to close this window", curses.A_BOLD)

        help_win.refresh()


def draw_edit_dialog(screen, node):
    """Draw an editor dialog for the node value."""
    max_y, max_x = curses_state['max_y'], curses_state['max_x']

    setting_type = node.metadata.get("type", "text")

    if setting_type == "boolean":
        # Just toggle the value
        node.value = not node.value
        node.is_editing = False
        return True
    elif setting_type == "choice":
        # Cycle through options
        options = node.metadata.get("options", [])
        if options:
            current_index = options.index(node.value) if node.value in options else -1
            next_index = (current_index + 1) % len(options)
            node.value = options[next_index]
            node.is_editing = False
            return True

    # For other types, show an editor dialog
    editor_height = 5

    # Calculate width based on value length
    value_str = str(node.value) if node.value is not None else ""
    editor_width = max(40, min(len(value_str) + 10, max_x - 10))

    editor_y = (max_y - editor_height) // 2
    editor_x = (max_x - editor_width) // 2

    # Create editor window
    editor_win = curses.newwin(editor_height, editor_width, editor_y, editor_x)
    editor_win.box()

    # Draw title
    title = f"Edit {node.name}"
    editor_win.addstr(0, (editor_width - len(title)) // 2, title, curses.A_BOLD)

    # Draw input field
    input_width = editor_width - 4
    editor_win.addstr(2, 2, " " * input_width)

    # Enable cursor
    curses.curs_set(1)

    # Get current value
    current = str(node.value) if node.value is not None else ""

    # Draw initial value
    editor_win.addstr(2, 2, current[:input_width])
    editor_win.move(2, 2 + min(len(current), input_width))

    # Refresh window
    editor_win.refresh()

    # Input loop
    result = current
    pos = len(current)

    while True:
        key = editor_win.getch()

        if key == 10 or key == 13:  # Enter
            break
        elif key == 27:  # Escape
            result = current  # Restore original value
            break
        elif key == curses.KEY_BACKSPACE or key == 127:  # Backspace
            if pos > 0:
                result = result[:pos - 1] + result[pos:]
                pos -= 1
        elif key == curses.KEY_LEFT:
            pos = max(0, pos - 1)
        elif key == curses.KEY_RIGHT:
            pos = min(len(result), pos + 1)
        elif key == curses.KEY_HOME:
            pos = 0
        elif key == curses.KEY_END:
            pos = len(result)
        elif 32 <= key <= 126:  # Printable ASCII
            result = result[:pos] + chr(key) + result[pos:]
            pos += 1

        # Update display
        editor_win.addstr(2, 2, " " * input_width)

        # Show appropriate part of string if it's longer than the input field
        display_start = max(0, pos - input_width + 10)
        display_str = result[display_start:display_start + input_width]

        editor_win.addstr(2, 2, display_str)
        editor_win.move(2, 2 + pos - display_start)
        editor_win.refresh()

    # Hide cursor again
    curses.curs_set(0)

    # Process result
    if setting_type == "number":
        try:
            result = int(result)
        except ValueError:
            try:
                result = float(result)
            except ValueError:
                result = node.value  # Keep original value on error
    elif setting_type == "multiselect":
        if result:
            result = [item.strip() for item in result.split(",")]
        else:
            result = []

    # Update node value
    node.value = result
    node.is_editing = False

    return True


def draw_confirmation_dialog(screen, message, yes_action, no_action):
    """Draw a confirmation dialog."""
    max_y, max_x = curses_state['max_y'], curses_state['max_x']

    # Calculate window dimensions
    dialog_height = 5
    dialog_width = len(message) + 10
    dialog_y = (max_y - dialog_height) // 2
    dialog_x = (max_x - dialog_width) // 2

    # Create a sub-window
    if dialog_y > 0 and dialog_x > 0 and dialog_width > 20:
        dialog_win = curses.newwin(dialog_height, dialog_width, dialog_y, dialog_x)
        dialog_win.box()

        # Draw title
        dialog_win.addstr(0, (dialog_width - 12) // 2, "Confirmation", curses.A_BOLD)

        # Draw message
        dialog_win.addstr(2, 5, message[:dialog_width - 10])

        # Draw buttons
        dialog_win.addstr(3, 5, "[Y]es", curses.A_BOLD)
        dialog_win.addstr(3, dialog_width - 10, "[N]o", curses.A_BOLD)

        dialog_win.refresh()

        # Wait for response
        while True:
            key = screen.getch()
            if key in [ord('y'), ord('Y')]:
                yes_action()
                break
            elif key in [ord('n'), ord('N')]:
                no_action()
                break


def navigation_loop(settings_manager):
    """Main navigation loop."""
    screen = curses_state['screen']

    # Draw initial screen
    draw_screen(settings_manager)

    # Main loop
    while not settings_manager.exit_requested:
        # Get user input
        key = screen.getch()

        # Process navigation or toggle
        if key == curses.KEY_UP:
            # Move up
            if settings_manager.visible_nodes:
                current_idx = -1
                for i, (node, _) in enumerate(settings_manager.visible_nodes):
                    if node == settings_manager.current_node:
                        current_idx = i
                        break

                if current_idx > 0:
                    settings_manager.current_node = settings_manager.visible_nodes[current_idx - 1][0]

        elif key == curses.KEY_DOWN:
            # Move down
            if settings_manager.visible_nodes:
                current_idx = -1
                for i, (node, _) in enumerate(settings_manager.visible_nodes):
                    if node == settings_manager.current_node:
                        current_idx = i
                        break

                if current_idx < len(settings_manager.visible_nodes) - 1:
                    settings_manager.current_node = settings_manager.visible_nodes[current_idx + 1][0]

        elif key == curses.KEY_RIGHT or key == ord(' '):
            # Expand or edit
            if settings_manager.current_node:
                if settings_manager.current_node.children:
                    settings_manager.current_node.is_expanded = True
                elif settings_manager.current_node.type == "setting":
                    # For boolean settings, just toggle
                    setting_type = settings_manager.current_node.metadata.get("type", "text")
                    if setting_type == "boolean":
                        if not settings_manager.current_node.metadata.get("readonly", False):
                            settings_manager.current_node.value = not settings_manager.current_node.value
                            settings_manager.modified = True
                    else:
                        # Otherwise start editing
                        settings_manager.current_node.start_editing()
                        draw_edit_dialog(screen, settings_manager.current_node)
                        settings_manager.modified = True

        elif key == curses.KEY_LEFT:
            # Collapse or move to parent
            if settings_manager.current_node:
                if settings_manager.current_node.is_expanded and settings_manager.current_node.children:
                    settings_manager.current_node.is_expanded = False
                elif settings_manager.current_node.parent:
                    settings_manager.current_node = settings_manager.current_node.parent

        elif key == curses.KEY_ENTER or key == 10 or key == 13:
            # Edit setting
            if settings_manager.current_node and settings_manager.current_node.type == "setting":
                if settings_manager.current_node.start_editing():
                    draw_edit_dialog(screen, settings_manager.current_node)
                    settings_manager.modified = True

        elif key == ord('\t'):
            # Cycle through choices for choice settings
            if settings_manager.current_node and settings_manager.current_node.type == "setting":
                setting_type = settings_manager.current_node.metadata.get("type", "text")
                if setting_type == "choice" and not settings_manager.current_node.metadata.get("readonly", False):
                    options = settings_manager.current_node.metadata.get("options", [])
                    if options:
                        current_index = options.index(
                            settings_manager.current_node.value) if settings_manager.current_node.value in options else -1
                        next_index = (current_index + 1) % len(options)
                        settings_manager.current_node.value = options[next_index]
                        settings_manager.modified = True

        elif key == ord('d'):
            # Run detections
            detections_run = settings_manager.run_all_detections()
            if detections_run == 0:
                settings_manager.status_message = "No automatic detection available"

        elif key == ord('s'):
            # Save and exit
            settings_manager.save_settings()
            settings_manager.exit_requested = True

        elif key == ord('q'):
            # Exit with confirmation if modified
            if settings_manager.modified:
                draw_confirmation_dialog(
                    screen,
                    "Save changes before exiting?",
                    lambda: settings_manager.save_settings() or setattr(settings_manager, 'exit_requested', True),
                    lambda: setattr(settings_manager, 'exit_requested', True)
                )
            else:
                settings_manager.exit_requested = True

        elif key == ord('h'):
            # Toggle help
            settings_manager.show_help = not settings_manager.show_help

        # Handle help window navigation
        elif settings_manager.show_help:
            # Any key closes help
            settings_manager.show_help = False

        # Redraw screen
        draw_screen(settings_manager)


def run_settings_tui():
    """Run the settings TUI."""
    # Install signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Initialize settings manager
    settings_manager = SettingsManager()

    try:
        # Initialize curses
        screen = initialize_curses()

        # Run navigation loop
        navigation_loop(settings_manager)

        # Clean up curses
        cleanup_curses()

        # Return whether settings were saved
        return settings_manager.save_requested

    except Exception as e:
        # Clean up curses on exception
        cleanup_curses()
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    run_settings_tui()