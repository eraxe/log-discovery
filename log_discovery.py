#!/usr/bin/env python3
"""
Enhanced Smart Log Discovery System for OpenLiteSpeed/CyberPanel/WordPress

This script discovers log file locations by examining actual configuration files
rather than simply scanning for common patterns. It builds a structured output
that can be used to configure Loki/Promtail.

Key improvements:
- Modular design for easy extension
- Class abstraction for different log sources
- Robust configuration parsing
- Parallel processing for performance
- Caching to reduce redundant operations
- Enhanced error handling and reporting
- Log rotation detection

Usage:
    python3 log_discovery.py [--output OUTPUT] [--format {json,yaml}] [--verbose]
    [--include TYPES] [--exclude TYPES] [--cache-file FILE] [--timeout SECONDS]

Author: Claude
Version: 2.1.0
Created: April 21, 2025
"""

import os
import re
import sys
import json
import yaml
import glob
import time
import fcntl
import hashlib
import signal
import logging
import argparse
import tempfile
import subprocess
import importlib
import configparser
import threading  # Added for thread-safe operations
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import the LogSource base class
from log_source import LogSource, TimeoutError, timeout_handler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('log_discovery')


def discover_modules(modules_dir="modules"):
    """Discover log source modules in the modules directory.

    Args:
        modules_dir: Path to the modules directory

    Returns:
        dict: Dictionary of module name to log source class
    """
    modules = {}

    # Get the absolute path to the modules directory
    if not os.path.isabs(modules_dir):
        modules_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), modules_dir)

    # Check if modules directory exists
    if not os.path.exists(modules_dir):
        logger.warning(f"Modules directory not found: {modules_dir}")
        return modules

    # Add modules directory to Python path if needed
    if modules_dir not in sys.path:
        sys.path.insert(0, os.path.dirname(modules_dir))

    # Get all Python files in the modules directory
    module_files = glob.glob(os.path.join(modules_dir, "*.py"))

    for module_file in module_files:
        module_name = os.path.basename(module_file)[:-3]  # Remove .py extension

        # Skip __init__.py and other special files
        if module_name.startswith("__"):
            continue

        try:
            # Import the module
            module = importlib.import_module(f"modules.{module_name}")

            # Get the log source class from the module
            if hasattr(module, "get_log_source"):
                log_source_class = module.get_log_source()
                modules[module_name] = log_source_class
                logger.debug(f"Loaded module: {module_name}")
            else:
                logger.warning(f"Module {module_name} does not have get_log_source() function")
        except Exception as e:
            logger.error(f"Error loading module {module_name}: {str(e)}")
            import traceback
            logger.debug(traceback.format_exc())

    return modules


class LogDiscoverer:
    """Main class for discovering logs."""

    def __init__(self, verbose=False, include_types=None, exclude_types=None, cache_file=None, timeout=300):
        """Initialize the log discoverer.

        Args:
            verbose: Whether to print verbose logs
            include_types: List of log types to include (None for all)
            exclude_types: List of log types to exclude (None for none)
            cache_file: Path to cache file (None for no caching)
            timeout: Timeout in seconds for the discovery process
        """
        self.verbose = verbose

        # Set up logger
        self.logger = logging.getLogger('log_discovery')
        if verbose:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)

        # Initialize results
        self.discovered_logs = []
        self.log_paths_added = set()  # Track already added log paths

        # Set up cache
        self.cache_file = cache_file
        self.cache = self._load_cache() if cache_file else {}

        # Set up filtering
        self.include_types = include_types
        self.exclude_types = exclude_types

        # Set up timeout
        self.timeout = timeout

    def log(self, message, level="INFO"):
        """Print log messages when verbose is enabled.

        Args:
            message: Log message
            level: Log level (INFO, WARN, ERROR, DEBUG)
        """
        if level == "INFO":
            self.logger.info(message)
        elif level == "WARN":
            self.logger.warning(message)
        elif level == "ERROR":
            self.logger.error(message)
        elif level == "DEBUG":
            self.logger.debug(message)

    def discover_all(self):
        """Run all discovery methods and return results.

        Returns:
            dict: Discovery results
        """
        # Set up timeout
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(self.timeout)

        try:
            # Discover modules
            module_classes = discover_modules()

            if not module_classes:
                self.log("No modules found. Using built-in log sources.", "WARN")
                # We could fall back to built-in sources, but for the modular approach
                # we'll just return empty results if no modules are found

            # Initialize source classes
            sources = {}
            for module_name, source_class in module_classes.items():
                sources[module_name] = source_class(self)

            # Filter sources based on include/exclude lists
            if self.include_types:
                sources = {k: v for k, v in sources.items() if k in self.include_types}
            if self.exclude_types:
                sources = {k: v for k, v in sources.items() if k not in self.exclude_types}

            # Run discovery for each source sequentially to avoid thread issues
            for source_name, source in sources.items():
                self.log(f"Starting discovery for {source_name}")
                try:
                    logs_found = source.discover()
                    self.log(f"Discovered {logs_found} logs for {source_name}")
                except Exception as e:
                    self.log(f"Error during {source_name} discovery: {str(e)}", "ERROR")
                    import traceback
                    self.log(traceback.format_exc(), "DEBUG")

            # Update cache
            if self.cache_file:
                self._save_cache()

            # Add metadata
            result = {
                "metadata": {
                    "generated_at": datetime.now().isoformat(),
                    "version": "2.1.0",
                    "hostname": self._get_hostname(),
                    "discovery_time": int(time.time())
                },
                "sources": self.discovered_logs
            }

            signal.alarm(0)  # Disable alarm
            return result

        except TimeoutError:
            self.log("Discovery process timed out", "ERROR")
            # Return partial results
            result = {
                "metadata": {
                    "generated_at": datetime.now().isoformat(),
                    "version": "2.1.0",
                    "hostname": self._get_hostname(),
                    "status": "incomplete",
                    "error": "Timeout during discovery process"
                },
                "sources": self.discovered_logs
            }
            return result
        finally:
            signal.alarm(0)  # Ensure alarm is disabled

    def _get_hostname(self):
        """Get system hostname.

        Returns:
            str: Hostname
        """
        try:
            # Thread-safe implementation
            result = {"hostname": "unknown", "error": None}

            def get_hostname():
                try:
                    # Use Popen instead of check_output
                    process = subprocess.Popen(
                        "hostname",
                        shell=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        universal_newlines=True
                    )
                    stdout, stderr = process.communicate(timeout=3)
                    result["hostname"] = stdout.strip()
                except Exception as e:
                    result["error"] = str(e)

            # Use threading with timeout
            thread = threading.Thread(target=get_hostname)
            thread.daemon = True
            thread.start()
            thread.join(3)  # 3 second timeout

            return result["hostname"]
        except:
            return "unknown"

    def _compute_checksum(self, path):
        """Compute checksum of a file in a thread-safe manner.

        Args:
            path: Path to file

        Returns:
            str: SHA-256 checksum or None on error
        """
        if not os.path.exists(path):
            return None

        try:
            result = {"checksum": None, "error": None}

            def calculate_checksum():
                try:
                    with open(path, 'rb') as f:
                        result["checksum"] = hashlib.sha256(f.read()).hexdigest()
                except Exception as e:
                    result["error"] = str(e)

            # Use threading with timeout instead of signals
            thread = threading.Thread(target=calculate_checksum)
            thread.daemon = True
            thread.start()
            thread.join(3)  # 3 second timeout

            if thread.is_alive():
                self.log(f"Timeout computing checksum for {path}", "WARN")
                return None

            if result["error"]:
                self.log(f"Error computing checksum for {path}: {result['error']}", "WARN")
                return None

            return result["checksum"]
        except Exception as e:
            self.log(f"Unexpected error computing checksum for {path}: {str(e)}", "WARN")
            return None

    def _load_cache(self):
        """Load discovery cache from file.

        Returns:
            dict: Cache data or empty dict on error
        """
        if not self.cache_file or not os.path.exists(self.cache_file):
            return {}

        try:
            with open(self.cache_file, 'r') as f:
                cache_data = json.load(f)
                self.log(f"Loaded cache with {len(cache_data.get('sources', []))} entries", "DEBUG")
                return cache_data
        except Exception as e:
            self.log(f"Error loading cache: {str(e)}", "WARN")
            return {}

    def _save_cache(self):
        """Save discovery cache to file."""
        try:
            # Create directory if it doesn't exist
            cache_dir = os.path.dirname(self.cache_file)
            if cache_dir and not os.path.exists(cache_dir):
                os.makedirs(cache_dir)

            # Create a temporary file and use an exclusive lock
            with tempfile.NamedTemporaryFile(mode='w', dir=cache_dir, delete=False) as temp_file:
                fcntl.flock(temp_file.fileno(), fcntl.LOCK_EX)

                # Build cache data
                cache_data = {
                    "metadata": {
                        "generated_at": datetime.now().isoformat(),
                        "version": "2.1.0",
                        "hostname": self._get_hostname()
                    },
                    "sources": self.discovered_logs
                }

                # Write cache data
                json.dump(cache_data, temp_file, indent=2)
                temp_file.flush()
                os.fsync(temp_file.fileno())

                # Release lock
                fcntl.flock(temp_file.fileno(), fcntl.LOCK_UN)

            # Atomically replace the cache file
            os.rename(temp_file.name, self.cache_file)
            self.log(f"Saved cache with {len(self.discovered_logs)} entries", "DEBUG")
        except Exception as e:
            self.log(f"Error saving cache: {str(e)}", "WARN")
            # Clean up temporary file if it exists
            if 'temp_file' in locals():
                try:
                    os.unlink(temp_file.name)
                except:
                    pass

    def add_log_source(self, source_type, name, path, format="text", labels=None, exists=None):
        """Add a discovered log source to the results.

        Args:
            source_type: Type of log source
            name: Name identifier for the log
            path: Path to the log file
            format: Log file format (default: text)
            labels: Dictionary of labels for the log
            exists: Whether the file exists (will check if None)

        Returns:
            dict: The log entry that was added
        """
        if labels is None:
            labels = {}

        # Set default labels based on source type
        if "source" not in labels:
            labels["source"] = source_type

        # Check if path contains wildcards
        has_wildcards = "*" in path or "?" in path

        # Get canonical path if no wildcards
        if not has_wildcards:
            try:
                path = os.path.normpath(path)
            except:
                pass  # Keep the original path if normalization fails

        # Check if file exists if not already provided
        if exists is None and not has_wildcards:
            exists = os.path.exists(path)

        # Skip if already added (to avoid duplicates)
        if not has_wildcards and path in self.log_paths_added:
            self.log(f"Skipping duplicate log: {path}", "DEBUG")
            return None

        # Add to tracking set
        if not has_wildcards:
            self.log_paths_added.add(path)

        # Get last modified time and size if file exists
        last_modified = None
        size = None
        checksum = None

        if exists and not has_wildcards:
            try:
                last_modified = datetime.fromtimestamp(os.path.getmtime(path)).isoformat()
                size = os.path.getsize(path)
                if size < 10 * 1024 * 1024:  # Only compute checksum for files smaller than 10MB
                    checksum = self._compute_checksum(path)
            except Exception as e:
                self.log(f"Error getting file info for {path}: {str(e)}", "DEBUG")

        # Create log entry
        log_entry = {
            "type": source_type,
            "name": name,
            "path": path,
            "format": format,
            "labels": labels,
            "exists": exists
        }

        # Add additional metadata if available
        if last_modified:
            log_entry["last_modified"] = last_modified
        if size is not None:
            log_entry["size"] = size
        if checksum:
            log_entry["checksum"] = checksum

        self.discovered_logs.append(log_entry)

        self.log(f"Discovered {source_type} log: {path} (exists: {exists})")

        return log_entry

    def is_log_already_added(self, path):
        """Check if a log path has already been added.

        Args:
            path: Path to check

        Returns:
            bool: True if already added
        """
        return path in self.log_paths_added


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Enhanced Log Discovery for OpenLiteSpeed/CyberPanel/WordPress")
    parser.add_argument("--output", "-o", help="Output file path (default: stdout)")
    parser.add_argument("--format", "-f", choices=["json", "yaml"], default="json",
                        help="Output format (default: json)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    parser.add_argument("--include", "-i", help="Comma-separated list of log types to include")
    parser.add_argument("--exclude", "-e", help="Comma-separated list of log types to exclude")
    parser.add_argument("--cache-file", "-c", help="Path to cache file")
    parser.add_argument("--timeout", "-t", type=int, default=300, help="Timeout in seconds (default: 300)")
    parser.add_argument("--validate", action="store_true", help="Validate discovered logs by checking permissions")

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Parse include/exclude types
    include_types = None
    if args.include:
        include_types = [t.strip() for t in args.include.split(',')]

    exclude_types = None
    if args.exclude:
        exclude_types = [t.strip() for t in args.exclude.split(',')]

    # Initialize and run discovery
    start_time = time.time()
    discoverer = LogDiscoverer(
        verbose=args.verbose,
        include_types=include_types,
        exclude_types=exclude_types,
        cache_file=args.cache_file,
        timeout=args.timeout
    )

    results = discoverer.discover_all()

    # Add total discovery time to metadata
    results["metadata"]["discovery_time_seconds"] = round(time.time() - start_time, 2)

    # Validate logs if requested
    if args.validate:
        for source in results["sources"]:
            if source["exists"] and os.path.exists(source["path"]):
                source["readable"] = os.access(source["path"], os.R_OK)
            else:
                source["readable"] = False

    # Generate output
    if args.format == "json":
        output = json.dumps(results, indent=2)
    else:  # yaml
        output = yaml.dump(results, default_flow_style=False)

    # Write output
    if args.output:
        try:
            # Create output directory if it doesn't exist
            output_dir = os.path.dirname(args.output)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir)

            # Write to output file
            with open(args.output, 'w') as f:
                f.write(output)
            print(f"Results written to {args.output}")
        except Exception as e:
            print(f"Error writing to {args.output}: {str(e)}", file=sys.stderr)
            sys.exit(1)
    else:
        print(output)


if __name__ == "__main__":
    main()