"""
Example template module for discovering custom logs.

This file serves as a template for creating your own log discovery modules.
To create a new module:
1. Copy this file to a new file in the 'modules' directory
2. Rename the class and implement the discover() method
3. Modify the get_log_source() function to return your class
4. The module will be automatically loaded and used

For example: nginx.py, apache.py, etc.
"""

import os
import re
import glob

# Import the LogSource base class
from log_source import LogSource


class ExampleLogSource(LogSource):
    """
    Example log source discovery class.

    Replace 'Example' with your log source name, e.g., NginxLogSource, ApacheLogSource, etc.
    """

    def discover(self):
        """
        Discover logs for this source type.

        This method should:
        1. Look for log files by examining configuration files or known locations
        2. Add found logs using self.add_log()
        3. Return the total number of logs found

        Returns:
            int: Number of logs discovered
        """
        self.discoverer.log("Searching for Example logs...")

        # Check if the service is installed
        if not os.path.exists("/etc/example"):
            self.discoverer.log("Example service not installed", "INFO")
            return self.logs_found

        # Example: Look for configuration files
        config_paths = [
            "/etc/example/example.conf",
            "/usr/local/example/conf/example.conf"
        ]

        config_file = next((path for path in config_paths if self._file_readable(path)), None)

        if config_file:
            # Parse configuration file
            config_content = self._load_file_content(config_file)
            if config_content:
                # Extract log paths using regular expressions
                error_log_match = re.search(r'error_log\s+(.+?)[\s\n]', config_content)
                if error_log_match:
                    error_log_path = error_log_match.group(1)

                    # Add the log to the discovered logs
                    self.add_log(
                        "example_error",  # name
                        error_log_path,  # path
                        labels={  # metadata labels
                            "level": "error",
                            "service": "example"
                        }
                    )
                    self.logs_found += 1

                    # Also look for rotated versions of this log
                    self._find_rotated_logs(error_log_path, "example_error", {
                        "level": "error",
                        "service": "example",
                        "rotated": "true"
                    })

        # Example: Look for logs in standard locations
        log_dirs = [
            "/var/log/example",
            "/usr/local/example/logs"
        ]

        for log_dir in log_dirs:
            if os.path.exists(log_dir):
                self.discoverer.log(f"Checking log directory: {log_dir}")

                # Look for log files
                log_files = glob.glob(f"{log_dir}/*.log")

                for log_file in log_files:
                    # Skip if already processed
                    if self.discoverer.is_log_already_added(log_file):
                        continue

                    # Determine log type
                    log_name = os.path.basename(log_file)
                    if "error" in log_name:
                        log_type = "error"
                    elif "access" in log_name:
                        log_type = "access"
                    else:
                        log_type = "general"

                    # Add the log
                    self.add_log(
                        f"example_{log_type}_{log_name.replace('.log', '')}",
                        log_file,
                        labels={
                            "level": log_type,
                            "service": "example"
                        }
                    )
                    self.logs_found += 1

        return self.logs_found


# Required function to return the log source class
def get_log_source():
    return ExampleLogSource