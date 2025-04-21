#!/usr/bin/env python3
"""
Interactive Log Configuration Terminal UI

A rich, interactive terminal UI for configuring which logs to monitor with
Promtail and Loki. Presents directories in a collapsible tree structure
with toggleable selection, and generates a configuration file based on
user selections.

Usage:
    ./log_config_tui.py [--input discovery.json] [--output config.yaml]
"""

import os
import re
import sys
import json
import yaml
import glob
import argparse
from typing import Dict, List, Set, Tuple, Optional, Any

try:
    from prompt_toolkit import Application
    from prompt_toolkit.layout import Layout, HSplit, VSplit, FormattedTextControl
    from prompt_toolkit.layout.containers import Window, WindowAlign, HorizontalAlign, VerticalAlign
    from prompt_toolkit.layout.controls import BufferControl
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.styles import Style
    from prompt_toolkit.widgets import Box, Frame, Label, Button, TextArea, RadioList, Dialog
    from prompt_toolkit.layout.dimension import D
    from prompt_toolkit.layout.margins import ScrollbarMargin
    from prompt_toolkit.filters import Condition
except ImportError:
    print("This script requires the 'prompt_toolkit' library.")
    print("Please install it with: pip install prompt-toolkit")
    sys.exit(1)

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from rich.tree import Tree
    from rich.console import RenderableType
    from rich.syntax import Syntax
    from rich import box

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("For better rendering, install the 'rich' library:")
    print("pip install rich")

# Default paths
DEFAULT_INPUT_PATH = "output/discovered_logs.json"
DEFAULT_OUTPUT_PATH = "config/promtail-config-settings.yaml"


# Global state
class AppState:
    def __init__(self):
        self.discovered_logs = []
        self.log_tree = {}
        self.selected_logs = set()
        self.expanded_nodes = set()
        self.input_file = DEFAULT_INPUT_PATH
        self.output_file = DEFAULT_OUTPUT_PATH
        self.filter_text = ""
        self.current_tab = "directory"  # 'directory', 'type', 'service'
        self.show_help = False
        self.show_preview = False
        self.show_confirmation = False
        self.confirmation_message = ""
        self.confirmation_callback = None
        self.log_types = set()
        self.log_services = set()
        self.selected_types = set()
        self.selected_services = set()
        # Additional settings
        self.loki_url = "http://loki:3100/loki/api/v1/push"
        self.promtail_port = 9080
        self.positions_file = "/var/lib/promtail/positions.yaml"
        self.container_engine = "podman"
        self.promtail_container = "promtail"
        self.max_log_size_mb = 100
        self.shorten_names = True
        self.max_name_length = 40


# Initialize app state
state = AppState()

# Style configuration
STYLE = Style.from_dict({
    'title': 'bold cyan',
    'label': 'white',
    'tab': '#aaaaaa',
    'tab.selected': 'bold white',
    'tree': '',
    'tree.expanded': 'bold',
    'tree.selected': 'reverse',
    'tree.toggle': 'green',
    'tree.toggle.off': 'red',
    'key': 'bold cyan',
    'status': 'bg:#333333 #ffffff',
    'help': 'white',
    'button': '#aaaaaa',
    'button.focused': 'bg:#777777 #ffffff',
    'frame.border': '#888888',
    'preview': '#aaaaaa',
    'dialog': 'bg:#222222',
    'dialog.border': '#888888',
})

# Key bindings
kb = KeyBindings()


def load_discovered_logs(file_path: str) -> List[Dict]:
    """Load discovered logs from JSON file."""
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        return data.get('sources', [])
    except Exception as e:
        show_error(f"Error loading discovered logs: {str(e)}")
        return []


def build_directory_tree(logs: List[Dict]) -> Dict:
    """Build a tree structure from log paths."""
    tree = {}
    for log in logs:
        path = log.get('path', '')
        if not path:
            continue

        # Skip if log doesn't exist
        if log.get('exists', True) is False:
            continue

        # Add log type and service to collections
        log_type = log.get('type', '')
        if log_type:
            state.log_types.add(log_type)

        service = log.get('labels', {}).get('service', '')
        if service:
            state.log_services.add(service)

        # Split path into components
        components = path.split('/')
        components = [c for c in components if c]  # Remove empty components

        # Build tree
        current = tree
        full_path = ""
        for i, component in enumerate(components):
            full_path = full_path + '/' + component if full_path else '/' + component

            if i == len(components) - 1:
                # This is a leaf (file)
                if '__files__' not in current:
                    current['__files__'] = []
                current['__files__'].append({
                    'path': path,
                    'name': component,
                    'full_path': full_path,
                    'log': log
                })
            else:
                # This is a directory
                if component not in current:
                    current[component] = {}
                current = current[component]

    return tree


def toggle_node(path: str) -> None:
    """Toggle a node's selection state."""
    if path in state.selected_logs:
        state.selected_logs.remove(path)
    else:
        state.selected_logs.add(path)


def toggle_type(log_type: str) -> None:
    """Toggle a log type's selection state."""
    if log_type in state.selected_types:
        state.selected_types.remove(log_type)
    else:
        state.selected_types.add(log_type)


def toggle_service(service: str) -> None:
    """Toggle a service's selection state."""
    if service in state.selected_services:
        state.selected_services.remove(service)
    else:
        state.selected_services.add(service)


def toggle_expansion(path: str) -> None:
    """Toggle a node's expansion state."""
    if path in state.expanded_nodes:
        state.expanded_nodes.remove(path)
    else:
        state.expanded_nodes.add(path)


def is_node_expanded(path: str) -> bool:
    """Check if a node is expanded."""
    return path in state.expanded_nodes


def filter_matches(text: str, filter_text: str) -> bool:
    """Check if text matches the current filter."""
    if not filter_text:
        return True
    return filter_text.lower() in text.lower()


def get_tree_node_html(path: str, name: str, is_dir: bool, indent: int, has_children: bool = False) -> HTML:
    """Get HTML representation of a tree node."""
    prefix = "    " * indent

    if is_dir:
        if path in state.expanded_nodes:
            toggle_icon = "[-]"
            toggle_class = "tree.expanded"
        else:
            toggle_icon = "[+]"
            toggle_class = "tree"

        if has_children:
            toggle = f'<{toggle_class}>{toggle_icon}</tree.expanded> '
        else:
            toggle = '    '

        if path in state.selected_logs:
            checkbox = '[class="tree.toggle"][x]'
        else:
            checkbox = '[class="tree.toggle.off"][ ]'

        node_class = "tree.selected" if path in state.selected_logs else "tree"
        return HTML(f"{prefix}{toggle}{checkbox} <{node_class}>{name}/</{node_class}>")
    else:
        if path in state.selected_logs:
            checkbox = '[class="tree.toggle"][x]'
        else:
            checkbox = '[class="tree.toggle.off"][ ]'

        node_class = "tree.selected" if path in state.selected_logs else "tree"
        return HTML(f"{prefix}    {checkbox} <{node_class}>{name}</{node_class}>")


def render_directory_tree() -> List[HTML]:
    """Render the directory tree with HTML formatting."""
    lines = []

    def render_subtree(tree: Dict, path: str = "", indent: int = 0, parent_visible: bool = True):
        # Sort keys to ensure directories come first, then files
        keys = sorted(k for k in tree.keys() if k != '__files__')

        # Render directories
        for key in keys:
            current_path = f"{path}/{key}" if path else f"/{key}"

            # Check if this node or any parent matches the filter
            visible = filter_matches(current_path, state.filter_text) if state.filter_text else True

            if visible or parent_visible:
                has_children = bool(tree[key]) and any(k != '__files__' for k in tree[key])
                lines.append(get_tree_node_html(current_path, key, True, indent, has_children))

                # Render children if expanded
                if is_node_expanded(current_path) and has_children:
                    render_subtree(tree[key], current_path, indent + 1, visible or parent_visible)

        # Render files
        if '__files__' in tree:
            for file in sorted(tree['__files__'], key=lambda x: x['name']):
                file_path = file['path']
                file_name = file['name']

                # Check if this file matches the filter
                visible = filter_matches(file_path, state.filter_text) if state.filter_text else True

                if visible or parent_visible:
                    lines.append(get_tree_node_html(file_path, file_name, False, indent))

    render_subtree(state.log_tree)
    return lines


def render_type_view() -> List[HTML]:
    """Render the type-based view with HTML formatting."""
    lines = []

    # Group logs by type
    logs_by_type = {}
    for log in state.discovered_logs:
        log_type = log.get('type', 'unknown')
        if log_type not in logs_by_type:
            logs_by_type[log_type] = []
        logs_by_type[log_type].append(log)

    # Render types
    for log_type in sorted(logs_by_type.keys()):
        # Check if this type matches the filter
        visible = filter_matches(log_type, state.filter_text) if state.filter_text else True

        if visible:
            # Checkbox for type
            if log_type in state.selected_types:
                checkbox = '[class="tree.toggle"][x]'
            else:
                checkbox = '[class="tree.toggle.off"][ ]'

            node_class = "tree.selected" if log_type in state.selected_types else "tree.expanded"
            count = len(logs_by_type[log_type])
            lines.append(HTML(f"{checkbox} <{node_class}>{log_type} ({count} logs)</{node_class}>"))

            # List logs of this type if expanded
            if log_type in state.expanded_nodes:
                for log in logs_by_type[log_type]:
                    path = log.get('path', '')
                    name = os.path.basename(path)

                    if state.filter_text and not filter_matches(path, state.filter_text):
                        continue

                    if path in state.selected_logs:
                        checkbox = '[class="tree.toggle"][x]'
                    else:
                        checkbox = '[class="tree.toggle.off"][ ]'

                    node_class = "tree.selected" if path in state.selected_logs else "tree"
                    lines.append(HTML(f"    {checkbox} <{node_class}>{name}</{node_class}> ({path})"))

    return lines


def render_service_view() -> List[HTML]:
    """Render the service-based view with HTML formatting."""
    lines = []

    # Group logs by service
    logs_by_service = {}
    for log in state.discovered_logs:
        service = log.get('labels', {}).get('service', 'unknown')
        if service not in logs_by_service:
            logs_by_service[service] = []
        logs_by_service[service].append(log)

    # Render services
    for service in sorted(logs_by_service.keys()):
        # Check if this service matches the filter
        visible = filter_matches(service, state.filter_text) if state.filter_text else True

        if visible:
            # Checkbox for service
            if service in state.selected_services:
                checkbox = '[class="tree.toggle"][x]'
            else:
                checkbox = '[class="tree.toggle.off"][ ]'

            node_class = "tree.selected" if service in state.selected_services else "tree.expanded"
            count = len(logs_by_service[service])
            lines.append(HTML(f"{checkbox} <{node_class}>{service} ({count} logs)</{node_class}>"))

            # List logs of this service if expanded
            if service in state.expanded_nodes:
                for log in logs_by_service[service]:
                    path = log.get('path', '')
                    name = os.path.basename(path)

                    if state.filter_text and not filter_matches(path, state.filter_text):
                        continue

                    if path in state.selected_logs:
                        checkbox = '[class="tree.toggle"][x]'
                    else:
                        checkbox = '[class="tree.toggle.off"][ ]'

                    node_class = "tree.selected" if path in state.selected_logs else "tree"
                    lines.append(HTML(f"    {checkbox} <{node_class}>{name}</{node_class}> ({path})"))

    return lines


def get_current_tree_view() -> List[HTML]:
    """Get the current tree view based on selected tab."""
    if state.current_tab == "directory":
        return render_directory_tree()
    elif state.current_tab == "type":
        return render_type_view()
    elif state.current_tab == "service":
        return render_service_view()
    return []


def get_selected_item(mouse_position: Tuple[int, int]) -> Optional[str]:
    """Get the item at the given mouse position."""
    if not (0 <= mouse_position[0] < len(get_current_tree_view())):
        return None

    line = get_current_tree_view()[mouse_position[0]]

    # Extract path from HTML
    if state.current_tab == "directory":
        # Parse tree view line to extract path
        text = line.value
        path_match = re.search(r'(\/[^<]+)', text)
        if path_match:
            return path_match.group(1)
    elif state.current_tab == "type":
        # Parse type view line to extract type
        text = line.value
        type_match = re.search(r'> ([^ (]+)', text)
        if type_match:
            return type_match.group(1)
    elif state.current_tab == "service":
        # Parse service view line to extract service
        text = line.value
        service_match = re.search(r'> ([^ (]+)', text)
        if service_match:
            return service_match.group(1)

    return None


def handle_tree_click(mouse_position: Tuple[int, int]) -> None:
    """Handle click in tree view."""
    if not (0 <= mouse_position[0] < len(get_current_tree_view())):
        return

    line = get_current_tree_view()[mouse_position[0]]
    line_text = line.value

    # Check if click was on toggle area (expansion)
    toggle_x = 0
    for i, char in enumerate(line_text):
        if char == '[' and i + 2 < len(line_text) and line_text[i + 1] in '+-' and line_text[i + 2] == ']':
            toggle_x = i
            break

    # Check if click was on checkbox
    checkbox_x = 0
    for i, char in enumerate(line_text):
        if char == '[' and i + 2 < len(line_text) and line_text[i + 1] == 'x' or line_text[i + 1] == ' ' and line_text[
            i + 2] == ']':
            checkbox_x = i
            break

    # If directory view, handle differently
    if state.current_tab == "directory":
        # Parse tree view line to extract path
        path_match = re.search(r'(\/[^<]+)', line_text)
        if path_match:
            path = path_match.group(1)

            # Check if click was on expansion toggle
            if checkbox_x > 0 and mouse_position[1] >= checkbox_x and mouse_position[1] <= checkbox_x + 3:
                toggle_node(path)
            elif toggle_x > 0 and mouse_position[1] >= toggle_x and mouse_position[1] <= toggle_x + 3:
                toggle_expansion(path)
            else:
                # Select on click anywhere else in the line
                toggle_node(path)
    elif state.current_tab == "type":
        # Handle type view clicks
        if mouse_position[1] <= 3 and ">" in line_text:
            # This is a type header
            type_match = re.search(r'> ([^ (]+)', line_text)
            if type_match:
                log_type = type_match.group(1)
                if checkbox_x > 0 and mouse_position[1] >= checkbox_x and mouse_position[1] <= checkbox_x + 3:
                    toggle_type(log_type)
                else:
                    toggle_expansion(log_type)
        else:
            # This is a log entry
            path_match = re.search(r'\(([^)]+)\)', line_text)
            if path_match:
                path = path_match.group(1)
                toggle_node(path)
    elif state.current_tab == "service":
        # Handle service view clicks
        if mouse_position[1] <= 3 and ">" in line_text:
            # This is a service header
            service_match = re.search(r'> ([^ (]+)', line_text)
            if service_match:
                service = service_match.group(1)
                if checkbox_x > 0 and mouse_position[1] >= checkbox_x and mouse_position[1] <= checkbox_x + 3:
                    toggle_service(service)
                else:
                    toggle_expansion(service)
        else:
            # This is a log entry
            path_match = re.search(r'\(([^)]+)\)', line_text)
            if path_match:
                path = path_match.group(1)
                toggle_node(path)


def generate_config() -> Dict:
    """Generate configuration based on selections."""
    # Basic configuration
    config = {
        'loki_url': state.loki_url,
        'promtail_port': state.promtail_port,
        'positions_file': state.positions_file,
        'promtail_container': state.promtail_container,
        'docker_command': state.container_engine,
        'max_log_size_mb': state.max_log_size_mb,
        'shorten_names': state.shorten_names,
        'max_name_length': state.max_name_length
    }

    # Include/exclude by type
    if state.selected_types:
        config['include_types'] = list(state.selected_types)

    # Include/exclude by service
    if state.selected_services:
        config['include_services'] = list(state.selected_services)

    # Selected log paths (patterns)
    selected_paths = list(state.selected_logs)
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

        config['include_patterns'] = include_patterns

    # Default exclude patterns
    config['exclude_patterns'] = [
        '\\.cache$',
        '/tmp/',
        'debug_backup',
        '\\.(gz|zip|bz2)$'
    ]

    # Add log format configurations
    config['log_formats'] = {
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
    config['pipeline_stages'] = {
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

    return config


def save_config(config: Dict, file_path: str) -> bool:
    """Save configuration to YAML file."""
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        with open(file_path, 'w') as f:
            yaml.safe_dump(config, f, default_flow_style=False)
        return True
    except Exception as e:
        show_error(f"Error saving configuration: {str(e)}")
        return False


def select_all() -> None:
    """Select all visible logs."""
    for line in get_current_tree_view():
        path_match = re.search(r'\(([^)]+)\)', line.value)
        if path_match:
            path = path_match.group(1)
            state.selected_logs.add(path)


def deselect_all() -> None:
    """Deselect all logs."""
    state.selected_logs.clear()
    state.selected_types.clear()
    state.selected_services.clear()


def expand_all() -> None:
    """Expand all tree nodes."""
    if state.current_tab == "directory":
        # Find all directories
        def add_all_dirs(tree, path=""):
            for key in tree:
                if key != "__files__":
                    current_path = f"{path}/{key}" if path else f"/{key}"
                    state.expanded_nodes.add(current_path)
                    add_all_dirs(tree[key], current_path)

        add_all_dirs(state.log_tree)
    elif state.current_tab == "type":
        # Expand all types
        state.expanded_nodes.update(state.log_types)
    elif state.current_tab == "service":
        # Expand all services
        state.expanded_nodes.update(state.log_services)


def collapse_all() -> None:
    """Collapse all tree nodes."""
    state.expanded_nodes.clear()


def show_error(message: str) -> None:
    """Show error message."""
    state.show_confirmation = True
    state.confirmation_message = f"Error: {message}"
    state.confirmation_callback = lambda: setattr(state, 'show_confirmation', False)


def get_config_preview() -> str:
    """Get a preview of the configuration YAML."""
    config = generate_config()
    return yaml.dump(config, default_flow_style=False)


def toggle_help() -> None:
    """Toggle help display."""
    state.show_help = not state.show_help


def toggle_preview() -> None:
    """Toggle configuration preview."""
    state.show_preview = not state.show_preview


def toggle_tab(tab: str) -> None:
    """Switch to a different tab view."""
    state.current_tab = tab


def get_stats() -> str:
    """Get statistics about selected logs."""
    total_logs = len(state.discovered_logs)
    selected_logs = len(state.selected_logs)
    percentage = (selected_logs / total_logs * 100) if total_logs > 0 else 0

    return f"Selected: {selected_logs}/{total_logs} logs ({percentage:.1f}%)"


def on_mouse_click(position: Tuple[int, int]):
    """Handle mouse click events."""
    # The position here will be the position of the cursor in the tree view
    handle_tree_click(position)
    app.invalidate()


# Define key bindings
@kb.add('q')
def _(event):
    """Quit the application."""
    event.app.exit()


@kb.add('s')
def _(event):
    """Save configuration."""
    config = generate_config()
    if save_config(config, state.output_file):
        state.show_confirmation = True
        state.confirmation_message = f"Configuration saved to {state.output_file}"
        state.confirmation_callback = lambda: setattr(state, 'show_confirmation', False)
    app.invalidate()


@kb.add('a')
def _(event):
    """Select all logs."""
    select_all()
    app.invalidate()


@kb.add('d')
def _(event):
    """Deselect all logs."""
    deselect_all()
    app.invalidate()


@kb.add('e')
def _(event):
    """Expand all nodes."""
    expand_all()
    app.invalidate()


@kb.add('c')
def _(event):
    """Collapse all nodes."""
    collapse_all()
    app.invalidate()


@kb.add('h')
def _(event):
    """Show/hide help."""
    toggle_help()
    app.invalidate()


@kb.add('p')
def _(event):
    """Show/hide configuration preview."""
    toggle_preview()
    app.invalidate()


@kb.add('1')
def _(event):
    """Switch to directory view."""
    toggle_tab("directory")
    app.invalidate()


@kb.add('2')
def _(event):
    """Switch to type view."""
    toggle_tab("type")
    app.invalidate()


@kb.add('3')
def _(event):
    """Switch to service view."""
    toggle_tab("service")
    app.invalidate()


@kb.add('/')
def _(event):
    """Focus filter input."""
    filter_buffer.focus()
    app.invalidate()


@kb.add('tab')
def _(event):
    """Cycle through tabs."""
    tabs = ["directory", "type", "service"]
    current_idx = tabs.index(state.current_tab)
    next_idx = (current_idx + 1) % len(tabs)
    state.current_tab = tabs[next_idx]
    app.invalidate()


# Create title bar
def get_title_bar():
    """Create the title bar."""
    return Window(
        FormattedTextControl(HTML('<title>Log Configuration ⚙️</title>')),
        height=1,
        align=WindowAlign.CENTER,
        style='title'
    )


# Create tab bar
def get_tab_bar():
    """Create the tab bar."""
    tabs = [
        ('directory', '1. Directory Tree'),
        ('type', '2. By Log Type'),
        ('service', '3. By Service')
    ]

    tab_items = []
    for tab_id, tab_name in tabs:
        style = 'tab.selected' if state.current_tab == tab_id else 'tab'
        tab_items.append(('', ' '))
        tab_items.append((style, tab_name))
        tab_items.append(('', ' | '))

    tab_items = tab_items[:-1]  # Remove trailing separator

    return Window(
        FormattedTextControl(tab_items),
        height=1,
        style='tab',
        align=WindowAlign.LEFT
    )


# Create filter input
filter_buffer = Buffer(
    name='filter',
    multiline=False,
    on_text_changed=lambda buffer: setattr(state, 'filter_text', buffer.text)
)


def get_filter_input():
    """Create the filter input field."""
    return VSplit([
        Label('Filter: ', style='label'),
        Window(BufferControl(filter_buffer), width=D(weight=1), style=''),
        Label(' (Press / to focus)', style='help')
    ], height=1)


# Create content area
def get_content():
    """Create the main content area."""
    visible_items = get_current_tree_view()

    return Window(
        FormattedTextControl(visible_items),
        wrap_lines=False,
        style='tree',
        right_margins=[ScrollbarMargin(display_arrows=True)],
        scroll_offsets=ScrollOffsets(top=2, bottom=2),
        dont_extend_height=False,
        on_cursor_position_changed=on_mouse_click
    )


# Create status bar
def get_status_bar():
    """Create the status bar."""
    return Window(
        FormattedTextControl(lambda: get_stats()),
        height=1,
        style='status'
    )


# Create help panel
def get_help_panel():
    """Create the help panel."""
    help_text = [
        ('key', 'Key Bindings'),
        ('', '\n'),
        ('key', 'q'), ('', ': Quit  '),
        ('key', 's'), ('', ': Save  '),
        ('key', 'h'), ('', ': Help  '),
        ('key', 'p'), ('', ': Preview'),
        ('', '\n'),
        ('key', 'a'), ('', ': Select All  '),
        ('key', 'd'), ('', ': Deselect All'),
        ('key', 'e'), ('', ': Expand All  '),
        ('key', 'c'), ('', ': Collapse All'),
        ('', '\n'),
        ('key', '1'), ('', ': Directory View  '),
        ('key', '2'), ('', ': Type View  '),
        ('key', '3'), ('', ': Service View'),
        ('key', 'Tab'), ('', ': Cycle Views'),
        ('', '\n'),
        ('key', '/'), ('', ': Filter  '),
        ('', '\n\n'),
        ('help', 'Mouse Actions'),
        ('', '\n'),
        ('help', '- Click on folder/type/service name to expand/collapse'),
        ('help', '\n- Click on checkbox to select/deselect'),
        ('help', '\n- Click on file name to select/deselect')
    ]

    return Frame(
        Window(FormattedTextControl(help_text)),
        title="Help (press h to close)",
        style='dialog',
        border_style='dialog.border'
    )


# Create preview panel
def get_preview_panel():
    """Create the configuration preview panel."""
    preview_text = get_config_preview()

    return Frame(
        Window(FormattedTextControl(preview_text)),
        title="Configuration Preview (press p to close)",
        style='preview',
        border_style='dialog.border'
    )


# Create confirmation dialog
def get_confirmation_dialog():
    """Create a confirmation dialog."""
    return Dialog(
        title="Message",
        body=Label(state.confirmation_message, dont_extend_width=True),
        buttons=[
            Button(
                text="OK",
                handler=state.confirmation_callback
            )
        ],
        style='dialog',
        border_style='dialog.border'
    )


# Create the main application layout
def get_layout():
    """Create the main application layout."""
    main_content = get_content()

    root_container = HSplit([
        get_title_bar(),
        get_tab_bar(),
        get_filter_input(),
        main_content,
        get_status_bar()
    ])

    # Add help panel if showing
    if state.show_help:
        root_container = HSplit([
            Box(
                root_container,
                padding=0,
                width=D(weight=1),
                height=D(weight=1)
            ),
            Box(
                get_help_panel(),
                padding=0,
                width=D(weight=1),
                height=D(preferred=15)
            )
        ])

    # Add preview panel if showing
    if state.show_preview:
        root_container = VSplit([
            Box(
                root_container,
                padding=0,
                width=D(weight=1),
                height=D(weight=1)
            ),
            Box(
                get_preview_panel(),
                padding=0,
                width=D(preferred=60),
                height=D(weight=1)
            )
        ])

    # Add confirmation dialog if showing
    if state.show_confirmation:
        root_container = Float(
            get_confirmation_dialog(),
            root_container
        )

    return Layout(root_container)


# Document title
class ScrollOffsets:
    def __init__(self, top=0, bottom=0):
        self.top = top
        self.bottom = bottom


class Float:
    def __init__(self, content, container):
        self.content = content
        self.container = container

    def __pt_container__(self):
        return FloatContainer(
            content=self.container,
            floats=[
                Float_(
                    content=self.content,
                    top=10,
                    left=10,
                )
            ]
        )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Interactive Log Configuration Terminal UI")
    parser.add_argument("--input", "-i", default=DEFAULT_INPUT_PATH, help="Input JSON file from log discovery")
    parser.add_argument("--output", "-o", default=DEFAULT_OUTPUT_PATH, help="Output YAML file for configuration")

    args = parser.parse_args()

    # Load discovered logs
    state.input_file = args.input
    state.output_file = args.output

    # Check if input file exists
    if not os.path.exists(state.input_file):
        print(f"Error: Input file not found: {state.input_file}")
        print("Please run log_discovery.py first to generate log discovery output.")
        sys.exit(1)

    # Load logs
    print(f"Loading logs from {state.input_file}...")
    state.discovered_logs = load_discovered_logs(state.input_file)
    print(f"Loaded {len(state.discovered_logs)} logs")

    # Build directory tree
    state.log_tree = build_directory_tree(state.discovered_logs)

    # Pre-select common log types
    state.selected_types = {'openlitespeed', 'wordpress', 'php', 'mysql', 'cyberpanel'}

    # Pre-select common services
    state.selected_services = {'webserver', 'wordpress', 'database', 'script_handler'}

    # Create and run the application
    global app
    app = Application(
        layout=Layout(get_layout()),  # Call the function to get a container
        key_bindings=kb,
        mouse_support=True,
        full_screen=True,
        style=STYLE
    )
    app.run()


if __name__ == "__main__":
    main()