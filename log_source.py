#!/usr/bin/env python3
"""Base class for log source discovery modules."""

import os
import re
import signal
import logging
from abc import ABC, abstractmethod

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('log_discovery')


class TimeoutError(Exception):
    """Exception raised when an operation times out."""
    pass


def timeout_handler(signum, frame):
    """Handler for timeout signal."""
    raise TimeoutError("Operation timed out")


class LogSource(ABC):
    """Base abstract class for all log source types."""

    def __init__(self, discoverer):
        """Initialize the log source.

        Args:
            discoverer: The parent LogDiscoverer instance
        """
        self.discoverer = discoverer
        self.logs_found = 0

    @abstractmethod
    def discover(self):
        """Discover logs for this source type.

        Returns:
            int: Number of logs discovered
        """
        pass

    def add_log(self, name, path, format="text", labels=None, exists=None):
        """Add a discovered log to the results.

        Args:
            name: Name identifier for the log
            path: Path to the log file
            format: Log file format (default: text)
            labels: Dictionary of labels for the log
            exists: Whether the file exists (will check if None)

        Returns:
            dict: The log entry that was added
        """
        return self.discoverer.add_log_source(
            self.__class__.__name__.lower().replace('logsource', ''),
            name, path, format, labels, exists
        )

    def _file_readable(self, path):
        """Check if a file exists and is readable.

        Args:
            path: Path to the file

        Returns:
            bool: True if file exists and is readable
        """
        try:
            return os.path.isfile(path) and os.access(path, os.R_OK)
        except Exception:
            return False

    def _load_file_content(self, path):
        """Safely load file content with timeout.

        Args:
            path: Path to the file

        Returns:
            str: File content or empty string on error
        """
        if not self._file_readable(path):
            return ""

        try:
            # Set timeout for file operations
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(5)  # 5 second timeout

            with open(path, 'r') as f:
                content = f.read()

            signal.alarm(0)  # Disable alarm
            return content
        except (TimeoutError, UnicodeDecodeError, PermissionError, FileNotFoundError) as e:
            logger.warning(f"Could not read file {path}: {str(e)}")
            return ""
        except Exception as e:
            logger.warning(f"Unexpected error reading {path}: {str(e)}")
            return ""
        finally:
            signal.alarm(0)  # Ensure alarm is disabled

    def _find_rotated_logs(self, log_path, base_name, labels):
        """Find rotated versions of a log file.

        Args:
            log_path: Path to the original log file
            base_name: Base name for the log entries
            labels: Labels to apply to the log entries

        Returns:
            int: Number of rotated logs found
        """
        # Skip if the original log path contains wildcards
        if "*" in log_path or "?" in log_path:
            return 0

        rotated_logs_found = 0
        log_dir = os.path.dirname(log_path)
        log_basename = os.path.basename(log_path)

        # Common rotation patterns
        rotation_patterns = [
            f"{log_basename}.*",  # Basic numbered rotation (.1, .2, etc.)
            f"{log_basename}.*.gz",  # Compressed with gzip
            f"{log_basename}.*.bz2",  # Compressed with bzip2
            f"{log_basename}.*.zip",  # Compressed with zip
            f"{log_basename}-*"  # Date-based rotation
        ]

        # Check for each rotation pattern
        if os.path.exists(log_dir):
            for pattern in rotation_patterns:
                rotated_logs = glob.glob(os.path.join(log_dir, pattern))
                for rotated_log in rotated_logs:
                    # Skip the original log
                    if rotated_log == log_path:
                        continue

                    # Skip if already added
                    if self.discoverer.is_log_already_added(rotated_log):
                        continue

                    # Add the rotated log
                    rotation_suffix = os.path.basename(rotated_log).replace(log_basename, '')
                    self.add_log(
                        f"{base_name}_rotated{rotation_suffix}",
                        rotated_log,
                        labels=labels
                    )
                    rotated_logs_found += 1

        return rotated_logs_found