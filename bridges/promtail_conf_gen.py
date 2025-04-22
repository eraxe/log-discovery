#!/usr/bin/env python3
"""
LogBuddy - Promtail Configuration Generator

A curses-based tool for generating Promtail configurations based on discovered logs.
Features a navigable tree interface for toggling directories and files on/off.

Navigation:
    ↑/↓               Move up/down in the tree
    →/←               Expand/collapse directory or move right/left
    SPACE             Expand/collapse directory
    ENTER             Toggle selection of current item
    a                 Toggle all items on
    A                 Toggle all items off
    s                 Save configuration and exit
    q                 Exit (prompts for save)
    h                 Show help
"""

import os
import re
import sys
import json
import yaml
import glob
import argparse
import curses
import signal
from typing import Dict, List, Set, Tuple, Optional, Any, Union
from functools import partial

# Default paths
DEFAULT_INPUT_PATH = "output/discovered_logs.json"
DEFAULT_OUTPUT_PATH = "config/promtail-config-settings.yaml"

# Default configuration values
DEFAULT_LOKI_URL = "http://loki:3100/loki/api/v1/push"
DEFAULT_PROMTAIL_PORT = 9080
DEFAULT_POSITIONS_FILE = "/var/lib/promtail/positions.yaml"
DEFAULT_CONTAINER_ENGINE = "podman"
DEFAULT_PROMTAIL_CONTAINER = "promtail"
DEFAULT_MAX_LOG_SIZE_MB = 100
DEFAULT_MAX_NAME_LENGTH = 40

# Recommended types and services
RECOMMENDED_TYPES = {"openlitespeed", "wordpress", "php", "mysql", "cyberpanel"}
RECOMMENDED_SERVICES = {"webserver", "wordpress", "database", "script_handler"}

# Visual indicators
INDICATOR_ENABLED = "●"  # Green dot for enabled items
INDICATOR_DISABLED = "●"  # Red dot for disabled items
INDICATOR_EXPANDED = "▼"  # Down triangle for expanded directories
INDICATOR_COLLAPSED = "▶"  # Right triangle for collapsed directories

# Tree node types
TYPE_DIR = "directory"
TYPE_FILE = "file"

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


class TreeNode:
    """Tree node representation for navigation."""

    def __init__(self, name: str, path: str, node_type: str, parent=None):
        self.name = name
        self.path = path
        self.type = node_type  # 'directory' or 'file'
        self.parent = parent
        self.children = []
        self.is_expanded = False
        self.is_selected = False
        self.log_data = None  # For storing log metadata

    def add_child(self, child):
        """Add a child node."""
        self.children.append(child)

    def toggle_expanded(self):
        """Toggle expanded state."""
        if self.type == TYPE_DIR:
            self.is_expanded = not self.is_expanded

    def toggle_selected(self):
        """Toggle selected state and propagate to children if this is a directory."""
        self.is_selected = not self.is_selected

        # If this is a directory, propagate the selection state to all children
        if self.type == TYPE_DIR:
            self.select_all(self.is_selected)

    def select_all(self, value: bool = True):
        """Select or deselect this node and all children."""
        self.is_selected = value
        for child in self.children:
            child.select_all(value)

    def get_selected_paths(self) -> List[str]:
        """Get all selected paths in this subtree."""
        paths = []
        if self.is_selected and self.type == TYPE_FILE:
            paths.append(self.path)

        for child in self.children:
            paths.extend(child.get_selected_paths())

        return paths

    def count_selected(self) -> int:
        """Count selected nodes in this subtree."""
        count = 1 if self.is_selected and self.type == TYPE_FILE else 0
        for child in self.children:
            count += child.count_selected()
        return count

    def count_total(self) -> int:
        """Count total file nodes in this subtree."""
        count = 1 if self.type == TYPE_FILE else 0
        for child in self.children:
            count += child.count_total()
        return count


class LogConfig:
    """Class to hold log configuration state."""

    def __init__(self):
        self.discovered_logs = []
        self.selected_logs = set()
        self.selected_types = set()
        self.selected_services = set()
        self.log_types = set()
        self.log_services = set()
        self.include_patterns = []
        self.exclude_patterns = []
        # Tree structure
        self.root_node = None
        # Configuration settings
        self.loki_url = DEFAULT_LOKI_URL
        self.promtail_port = DEFAULT_PROMTAIL_PORT
        self.positions_file = DEFAULT_POSITIONS_FILE
        self.container_engine = DEFAULT_CONTAINER_ENGINE
        self.promtail_container = DEFAULT_PROMTAIL_CONTAINER
        self.max_log_size_mb = DEFAULT_MAX_LOG_SIZE_MB
        self.shorten_names = True
        self.max_name_length = DEFAULT_MAX_NAME_LENGTH
        # UI state
        self.current_node = None
        self.top_node_idx = 0
        self.visible_nodes = []
        self.show_help = False
        self.status_message = ""
        self.exit_requested = False
        self.save_requested = False
        self.modified = False


def load_discovered_logs(file_path: str) -> List[Dict]:
    """Load discovered logs from JSON file."""
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        return data.get('sources', [])
    except Exception as e:
        print(f"Error loading discovered logs: {str(e)}", file=sys.stderr)
        sys.exit(1)


def extract_log_metadata(logs: List[Dict], config: LogConfig) -> None:
    """Extract metadata from logs for categorization."""
    for log in logs:
        # Extract log type
        log_type = log.get('type', '')
        if log_type:
            config.log_types.add(log_type)

        # Extract service
        service = log.get('labels', {}).get('service', '')
        if service:
            config.log_services.add(service)


def build_tree_structure(logs: List[Dict]) -> TreeNode:
    """Build a navigable tree structure from log paths."""
    root = TreeNode('/', '/', TYPE_DIR)

    for log in logs:
        path = log.get('path', '')
        if not path or log.get('exists', True) is False:
            continue

        # Split path into components
        components = path.split('/')
        components = [c for c in components if c]  # Remove empty components

        # Start from root
        current_node = root
        current_path = ''

        # Create directory nodes
        for i, component in enumerate(components):
            current_path = current_path + '/' + component if current_path else '/' + component

            # Check if this node already exists
            existing_node = None
            for child in current_node.children:
                if child.name == component:
                    existing_node = child
                    break

            if i == len(components) - 1:
                # This is a leaf (file)
                if not existing_node:
                    file_node = TreeNode(component, path, TYPE_FILE, current_node)
                    file_node.log_data = log
                    current_node.add_child(file_node)
            else:
                # This is a directory
                if not existing_node:
                    dir_node = TreeNode(component, current_path, TYPE_DIR, current_node)
                    current_node.add_child(dir_node)
                    current_node = dir_node
                else:
                    current_node = existing_node

    return root


def auto_select_logs(selection_type: str, config: LogConfig) -> None:
    """Auto-select logs based on selection type."""
    if selection_type == 'all':
        # Select all logs
        if config.root_node:
            config.root_node.select_all(True)

        # Select all types and services
        config.selected_types = config.log_types.copy()
        config.selected_services = config.log_services.copy()

    elif selection_type == 'none':
        # Deselect all logs
        if config.root_node:
            config.root_node.select_all(False)

        # Clear type and service selections
        config.selected_types.clear()
        config.selected_services.clear()

    elif selection_type == 'recommended':
        # Select recommended types
        config.selected_types = RECOMMENDED_TYPES.intersection(config.log_types)

        # Select recommended services
        config.selected_services = RECOMMENDED_SERVICES.intersection(config.log_services)

        # Select logs by type and service
        if config.root_node:
            mark_logs_by_type_service(config)


def mark_logs_by_type_service(config: LogConfig) -> None:
    """Mark logs as selected based on type and service."""

    def process_node(node: TreeNode):
        if node.type == TYPE_FILE and node.log_data:
            log_type = node.log_data.get('type', '')
            service = node.log_data.get('labels', {}).get('service', '')

            if (log_type in config.selected_types or
                    service in config.selected_services):
                node.is_selected = True

        for child in node.children:
            process_node(child)

    if config.root_node:
        process_node(config.root_node)


def generate_config(config: LogConfig) -> Dict:
    """Generate configuration based on selections."""
    # Get selected log paths from tree
    selected_paths = []
    if config.root_node:
        selected_paths = config.root_node.get_selected_paths()

    # Basic configuration
    output_config = {
        'loki_url': config.loki_url,
        'promtail_port': config.promtail_port,
        'positions_file': config.positions_file,
        'promtail_container': config.promtail_container,
        'docker_command': config.container_engine,
        'max_log_size_mb': config.max_log_size_mb,
        'shorten_names': config.shorten_names,
        'max_name_length': config.max_name_length
    }

    # Include/exclude by type
    if config.selected_types:
        output_config['include_types'] = list(config.selected_types)

    # Include/exclude by service
    if config.selected_services:
        output_config['include_services'] = list(config.selected_services)

    # Add specifically selected log paths (patterns)
    if selected_paths:
        # Convert exact paths to patterns
        include_patterns = []
        for path in selected_paths:
            # If it's a directory, include all logs under it
            if not path.endswith('.log') and os.path.isdir(path):
                include_patterns.append(f'{path}/.*\\.log$')
            else:
                # Escape special regex characters
                escaped_path = re.escape(path)
                include_patterns.append(escaped_path)

        output_config['include_patterns'] = include_patterns

    # Add additional patterns from command line
    if config.include_patterns:
        if 'include_patterns' not in output_config:
            output_config['include_patterns'] = []
        output_config['include_patterns'].extend(config.include_patterns)

    # Default exclude patterns
    output_config['exclude_patterns'] = [
        '\\.cache$',
        '/tmp/',
        'debug_backup',
        '\\.(gz|zip|bz2)$'
    ]

    # Add additional exclude patterns
    if config.exclude_patterns:
        output_config['exclude_patterns'].extend(config.exclude_patterns)

    # Add log format configurations
    output_config['log_formats'] = {
        'openlitespeed': {
            'regex': '^(?P<timestamp>\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}.\\d+) \\[(?P<level>[^\\]]+)\\] (?P<message>.*)$',
            'timestamp_field': 'timestamp',
            'timestamp_format': '2006-01-02 15:04:05.000'
        },
        'wordpress': {
            'regex': '^\\[(?P<timestamp>[^\\]]+)\\] (?P<level>\\w+): (?P<message>.*)$',
            'timestamp_field': 'timestamp',
            'timestamp_format': '02-Jan-2006 15:04:05'
        },
        'php': {
            'regex': '^\\[(?P<timestamp>\\d{2}-[A-Z][a-z]{2}-\\d{4} \\d{2}:\\d{2}:\\d{2})\\] (?P<message>.*)$',
            'timestamp_field': 'timestamp',
            'timestamp_format': '02-Jan-2006 15:04:05'
        },
        'mysql': {
            'regex': '^(?P<timestamp>\\d{6} \\d{2}:\\d{2}:\\d{2}) (?P<message>.*)$',
            'timestamp_field': 'timestamp',
            'timestamp_format': '060102 15:04:05'
        }
    }

    # Add basic pipeline stages
    output_config['pipeline_stages'] = {
        'openlitespeed': [
            {
                'regex': {
                    'expression': '^(?P<timestamp>\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}.\\d+) \\[(?P<level>[^\\]]+)\\] (?P<message>.*)$'
                }
            },
            {
                'labels': {
                    'level': ''
                }
            },
            {
                'timestamp': {
                    'source': 'timestamp',
                    'format': '2006-01-02 15:04:05.000'
                }
            }
        ],
        'wordpress': [
            {
                'regex': {
                    'expression': '^\\[(?P<timestamp>[^\\]]+)\\] (?P<level>\\w+): (?P<message>.*)$'
                }
            },
            {
                'labels': {
                    'level': ''
                }
            },
            {
                'timestamp': {
                    'source': 'timestamp',
                    'format': '02-Jan-2006 15:04:05'
                }
            }
        ]
    }

    return output_config


def save_config(config: Dict, file_path: str) -> bool:
    """Save configuration to YAML file."""
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        with open(file_path, 'w') as f:
            yaml.safe_dump(config, f, default_flow_style=False)
        return True
    except Exception as e:
        return False


def save_tree_state(root_node, file_path):
    """Save the expand/collapse and selection state of the tree to a file.

    Args:
        root_node: The root TreeNode
        file_path: Path to save the state

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Create a dictionary to hold the state
        state = {}

        # Recursive function to capture state
        def capture_state(node, path=""):
            # Skip the root node in the path
            node_path = path + "/" + node.name if path else node.name

            # Store state for this node
            state[node_path] = {
                "expanded": node.is_expanded,
                "selected": node.is_selected,
                "type": node.type
            }

            # Process children
            for child in node.children:
                capture_state(child, node_path)

        # Capture the state
        capture_state(root_node)

        # Save to file
        with open(file_path, 'w') as f:
            json.dump(state, f, indent=2)

        return True
    except Exception as e:
        print(f"Error saving tree state: {str(e)}")
        return False


def load_tree_state(root_node, file_path):
    """Load the expand/collapse and selection state of the tree from a file.

    Args:
        root_node: The root TreeNode
        file_path: Path to load the state from

    Returns:
        bool: True if successful, False otherwise
    """
    if not os.path.exists(file_path):
        return False

    try:
        # Load the state
        with open(file_path, 'r') as f:
            state = json.load(f)

        # Function to find a node by path
        def find_node(node, path_parts):
            if not path_parts:
                return node

            next_part = path_parts[0]
            rest_parts = path_parts[1:]

            for child in node.children:
                if child.name == next_part:
                    return find_node(child, rest_parts)

            return None

        # Apply state to nodes
        for node_path, node_state in state.items():
            path_parts = node_path.split("/")

            # Skip empty parts
            path_parts = [p for p in path_parts if p]

            # Find the node
            node = find_node(root_node, path_parts)

            # Apply state if node found
            if node:
                node.is_expanded = node_state.get("expanded", False)
                node.is_selected = node_state.get("selected", False)

        return True
    except Exception as e:
        print(f"Error loading tree state: {str(e)}")
        return False


def get_flat_tree(root: TreeNode) -> List[TreeNode]:
    """Get a flattened list of tree nodes for display."""
    nodes = []

    def traverse(node: TreeNode, level: int = 0):
        nodes.append((node, level))
        if node.type == TYPE_DIR and node.is_expanded:
            for child in sorted(node.children, key=lambda x: (x.type != TYPE_DIR, x.name)):
                traverse(child, level + 1)

    traverse(root)
    return nodes


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


def draw_screen(config: LogConfig):
    """Draw the main screen."""
    screen = curses_state['screen']
    max_y, max_x = screen.getmaxyx()
    curses_state['max_y'] = max_y
    curses_state['max_x'] = max_x

    # Clear screen
    screen.clear()

    # Draw title bar
    screen.attron(curses.color_pair(COLOR_TITLE) | curses.A_BOLD)
    title = "LogBuddy - Promtail Configuration Generator"
    screen.addstr(0, (max_x - len(title)) // 2, title)
    screen.attroff(curses.color_pair(COLOR_TITLE) | curses.A_BOLD)

    # Draw horizontal line
    screen.addstr(1, 0, "=" * max_x)

    # Calculate tree view area
    tree_start_y = 2
    tree_end_y = max_y - 3  # Leave space for status bar and help line
    tree_height = tree_end_y - tree_start_y

    # Get flattened tree
    if config.root_node:
        flat_tree = get_flat_tree(config.root_node)
        config.visible_nodes = flat_tree

        # Adjust view if current node is not visible
        current_idx = -1
        for i, (node, _) in enumerate(flat_tree):
            if node == config.current_node:
                current_idx = i
                break

        # If current node exists and is not in view, adjust top_node_idx
        if current_idx != -1:
            if current_idx < config.top_node_idx:
                config.top_node_idx = current_idx
            elif current_idx >= config.top_node_idx + tree_height:
                config.top_node_idx = max(0, current_idx - tree_height + 1)

        # Draw visible part of tree
        for i in range(tree_height):
            idx = config.top_node_idx + i
            if idx < len(flat_tree):
                node, level = flat_tree[idx]
                draw_tree_node(screen, tree_start_y + i, node, level, node == config.current_node)

    # Draw status bar
    draw_status_bar(screen, max_y - 2, config)

    # Draw help line
    help_text = "↑/↓: Navigate | →/←/SPACE: Expand/Collapse | ENTER: Toggle | a: Select All | A: Deselect All | s: Save | q: Exit | h: Help"
    screen.addstr(max_y - 1, 0, help_text[:max_x - 1], curses.color_pair(COLOR_HELP))

    # Show help if requested
    if config.show_help:
        draw_help_window(screen, config)

    # Refresh screen
    screen.refresh()


def draw_tree_node(screen, y: int, node: TreeNode, level: int, is_current: bool):
    """Draw a single tree node."""
    max_y, max_x = curses_state['max_y'], curses_state['max_x']
    if y < 0 or y >= max_y:
        return

    # Calculate indent based on level
    indent = level * 2
    max_text_width = max_x - indent - 10  # Leave space for indicators

    # Prepare indicators
    if node.type == TYPE_DIR:
        expand_indicator = INDICATOR_EXPANDED if node.is_expanded else INDICATOR_COLLAPSED
    else:
        expand_indicator = " "

    select_indicator = INDICATOR_ENABLED if node.is_selected else INDICATOR_DISABLED

    # Get node display name and info
    if node.type == TYPE_FILE and node.log_data:
        log_type = node.log_data.get('type', '')
        service = node.log_data.get('labels', {}).get('service', '')

        info = ""
        if log_type:
            info += f"type={log_type}"
        if service:
            info += f" service={service}" if info else f"service={service}"

        if info:
            info = f" ({info})"

        # Truncate if too long
        if len(node.name) + len(info) > max_text_width:
            name_length = max_text_width - len(info) - 3
            display_name = node.name[:name_length] + "..." + info
        else:
            display_name = node.name + info
    else:
        # For directories, add a count of selected/total
        if node.type == TYPE_DIR:
            selected = node.count_selected()
            total = node.count_total()
            ratio = f" [{selected}/{total}]"

            # Truncate if too long
            if len(node.name) + len(ratio) > max_text_width:
                name_length = max_text_width - len(ratio) - 3
                display_name = node.name[:name_length] + "..." + ratio
            else:
                display_name = node.name + ratio
        else:
            display_name = node.name

    # Add trailing slash for directories
    if node.type == TYPE_DIR:
        display_name += "/"

    # Construct the full line
    line = " " * indent + expand_indicator + " " + select_indicator + " " + display_name

    # Draw with appropriate attributes
    if is_current:
        attr = curses.color_pair(COLOR_SELECTED) | curses.A_BOLD
    else:
        attr = curses.color_pair(COLOR_NORMAL)

    screen.addstr(y, 0, " " * max_x)  # Clear line
    screen.addstr(y, 0, line[:max_x - 1], attr)

    # Draw selection indicator with color
    indicator_pos = indent + 2
    if indicator_pos < max_x:
        screen.addstr(y, indicator_pos, select_indicator,
                      curses.color_pair(COLOR_ENABLED if node.is_selected else COLOR_DISABLED) |
                      (curses.A_BOLD if is_current else 0))


def draw_status_bar(screen, y: int, config: LogConfig):
    """Draw the status bar."""
    max_y, max_x = curses_state['max_y'], curses_state['max_x']
    if y < 0 or y >= max_y:
        return

    # Calculate statistics
    if config.root_node:
        selected = config.root_node.count_selected()
        total = config.root_node.count_total()
        ratio = f"{selected}/{total}"
    else:
        ratio = "0/0"

    # Prepare status message
    status = f" Selected: {ratio} logs | Types: {len(config.selected_types)} | Services: {len(config.selected_services)}"

    # Add custom message if present
    if config.status_message:
        status += f" | {config.status_message}"

    # Draw status bar
    screen.addstr(y, 0, " " * max_x, curses.color_pair(COLOR_STATUS))
    screen.addstr(y, 0, status[:max_x - 1], curses.color_pair(COLOR_STATUS))


def draw_help_window(screen, config: LogConfig):
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
            "Arrow Keys: Navigate through the tree",
            "SPACE: Expand/collapse directory",
            "→/←: Expand/collapse or move right/left",
            "ENTER: Toggle current item selection",
            "a: Select all items",
            "A: Deselect all items",
            "s: Save configuration and exit",
            "q: Exit (will prompt to save changes)",
            "h: Toggle this help window",
            "",
            "Green ● indicates selected logs",
            "Red ● indicates unselected logs",
            ""
        ]

        for i, line in enumerate(help_lines, 1):
            if i < help_height - 1:
                help_win.addstr(i, 2, line[:help_width - 4])

        # Draw close instruction
        help_win.addstr(help_height - 2, 2, "Press any key to close this window", curses.A_BOLD)

        help_win.refresh()


def draw_confirmation_dialog(screen, message: str, yes_action, no_action):
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


def navigation_loop(config: LogConfig):
    """Main navigation loop."""
    screen = curses_state['screen']

    # Initialize navigation
    if config.root_node and not config.current_node:
        config.current_node = config.root_node

    # Draw initial screen
    draw_screen(config)

    # Main loop
    while not config.exit_requested:
        # Get user input
        key = screen.getch()

        # Process navigation or toggle
        if key == curses.KEY_UP:
            # Move up
            if config.visible_nodes:
                current_idx = -1
                for i, (node, _) in enumerate(config.visible_nodes):
                    if node == config.current_node:
                        current_idx = i
                        break

                if current_idx > 0:
                    config.current_node = config.visible_nodes[current_idx - 1][0]

        elif key == curses.KEY_DOWN:
            # Move down
            if config.visible_nodes:
                current_idx = -1
                for i, (node, _) in enumerate(config.visible_nodes):
                    if node == config.current_node:
                        current_idx = i
                        break

                if current_idx < len(config.visible_nodes) - 1:
                    config.current_node = config.visible_nodes[current_idx + 1][0]

        elif key == curses.KEY_RIGHT or key == ord(' '):
            # Expand directory or move right
            if config.current_node and config.current_node.type == TYPE_DIR:
                if not config.current_node.is_expanded:
                    config.current_node.is_expanded = True
                    config.modified = True
                elif config.current_node.children:
                    # Move to first child
                    config.current_node = config.current_node.children[0]

        elif key == curses.KEY_LEFT:
            # Collapse directory or move to parent
            if config.current_node:
                if config.current_node.type == TYPE_DIR and config.current_node.is_expanded:
                    config.current_node.is_expanded = False
                    config.modified = True
                elif config.current_node.parent:
                    config.current_node = config.current_node.parent

        elif key == curses.KEY_ENTER or key == 10 or key == 13:
            # Toggle selection
            if config.current_node:
                config.current_node.toggle_selected()
                config.modified = True

        elif key == ord('a'):
            # Toggle all on
            if config.root_node:
                config.root_node.select_all(True)
                config.modified = True
                config.status_message = "Selected all items"

        elif key == ord('A'):
            # Toggle all off
            if config.root_node:
                config.root_node.select_all(False)
                config.modified = True
                config.status_message = "Deselected all items"

        elif key == ord('s'):
            # Save and exit
            config.save_requested = True
            config.exit_requested = True
            config.status_message = "Saving configuration..."

        elif key == ord('q'):
            # Exit with confirmation if modified
            if config.modified:
                draw_confirmation_dialog(
                    screen,
                    "Save changes before exiting?",
                    lambda: setattr(config, 'save_requested', True) or setattr(config, 'exit_requested', True),
                    lambda: setattr(config, 'exit_requested', True)
                )
            else:
                config.exit_requested = True

        elif key == ord('h'):
            # Toggle help
            config.show_help = not config.show_help

        # Handle help window navigation
        elif config.show_help:
            # Any key closes help
            config.show_help = False

        # Redraw screen
        draw_screen(config)


def non_interactive_config(config: LogConfig, args):
    """Generate configuration without interactive UI."""
    # Parse type and service includes
    if args.include_types:
        config.selected_types = set(t.strip() for t in args.include_types.split(','))

    if args.include_services:
        config.selected_services = set(s.strip() for s in args.include_services.split(','))

    # Auto-select if specified
    if args.auto_select:
        auto_select_logs(args.auto_select, config)
    elif not config.selected_types and not config.selected_services and not config.include_patterns:
        # If nothing specified, use recommended settings
        print("No selection criteria specified. Using recommended settings.")
        auto_select_logs('recommended', config)

    # Mark logs based on types and services
    mark_logs_by_type_service(config)

    # Generate and save configuration
    output_config = generate_config(config)

    if save_config(output_config, args.output):
        print(f"Configuration saved to {args.output}")
        return True
    else:
        print("Failed to save configuration", file=sys.stderr)
        return False


def interactive_config(config: LogConfig, args):
    """Run interactive configuration with curses UI."""
    # Install signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Initialize curses
    screen = initialize_curses()

    try:
        # Run navigation loop
        navigation_loop(config)

        # Clean up curses
        cleanup_curses()

        # Save configuration if requested
        if config.save_requested:
            # Save the tree state
            state_file = os.path.join(os.path.dirname(args.output), "promtail_tree_state.json")
            if save_tree_state(config.root_node, state_file):
                print(f"Tree state saved to {state_file}")

            # Generate and save the configuration
            output_config = generate_config(config)
            if save_config(output_config, args.output):
                print(f"Configuration saved to {args.output}")
                return True
            else:
                print(f"Error: Failed to save configuration to {args.output}", file=sys.stderr)
                return False

        return True

    except Exception as e:
        # Clean up curses on exception
        cleanup_curses()
        print(f"Error: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="""LogBuddy - Promtail Configuration Generator

A curses-based tool for generating Promtail configurations based on discovered logs.
Features a navigable tree interface for toggling directories and files on/off.

This tool helps you configure which logs to monitor with Promtail/Loki by providing
an interactive tree-based interface where you can navigate through the log files
and select which ones to include in your monitoring configuration.

The configuration is saved to a YAML file that can be used by Promtail to set up
log scraping rules for your system.
""",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument("--input", "-i", default=DEFAULT_INPUT_PATH,
                        help=f"Input JSON file from log discovery (default: {DEFAULT_INPUT_PATH})")
    parser.add_argument("--output", "-o", default=DEFAULT_OUTPUT_PATH,
                        help=f"Output YAML file for configuration (default: {DEFAULT_OUTPUT_PATH})")
    parser.add_argument("--auto-select", "-a", choices=["all", "none", "recommended"],
                        help="Automatically select logs (all, none, or recommended)")
    parser.add_argument("--include-types", "-t",
                        help="Include specific log types (comma-separated)")
    parser.add_argument("--include-services", "-s",
                        help="Include specific services (comma-separated)")
    parser.add_argument("--include-paths", "-p",
                        help="Include specific path patterns (comma-separated)")
    parser.add_argument("--exclude-paths", "-e",
                        help="Exclude specific path patterns (comma-separated)")
    parser.add_argument("--non-interactive", "-n", action="store_true",
                        help="Run in non-interactive mode")

    # Parse known args to allow for logbuddy's additional args
    return parser.parse_known_args()[0]


def main():
    """Main entry point."""
    # Parse command line arguments
    args = parse_args()

    # Initialize configuration
    config = LogConfig()

    # Parse include/exclude patterns
    if args.include_paths:
        config.include_patterns = [p.strip() for p in args.include_paths.split(',')]

    if args.exclude_paths:
        config.exclude_patterns = [p.strip() for p in args.exclude_paths.split(',')]

    # Check if input file exists
    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}")
        print("Please run 'logbuddy discover' first to generate log discovery output.")
        sys.exit(1)

    # Load logs
    print(f"Loading logs from {args.input}...")
    config.discovered_logs = load_discovered_logs(args.input)
    print(f"Loaded {len(config.discovered_logs)} logs")

    # Extract metadata
    extract_log_metadata(config.discovered_logs, config)

    # Build tree structure
    config.root_node = build_tree_structure(config.discovered_logs)

    # Load saved tree state if available
    state_file = os.path.join(os.path.dirname(args.output), "promtail_tree_state.json")
    if os.path.exists(state_file):
        print(f"Loading saved tree state from {state_file}...")
        load_tree_state(config.root_node, state_file)

    # Run in requested mode
    success = False
    if args.non_interactive:
        success = non_interactive_config(config, args)
    else:
        success = interactive_config(config, args)

    # Exit with appropriate status
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()