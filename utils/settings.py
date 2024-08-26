"""
Settings for the project.

This module contains the `Settings` class, which centralizes the management of configuration options.
Settings are encapsulated within the class, and methods are provided to get and set configuration values.

Usage Example:

    # Accessing settings:
    import utils.settings as settings

    if settings.get_detailed_error_reporting():
        # Perform detailed error reporting
        ...

    # Modifying settings at runtime:
    settings.set_detailed_error_reporting(False)

    # Display current settings:
    settings.show_settings()

Dynamic Usage Example:

    # Adding or modifying settings dynamically during runtime:
    settings.add_dynamic_setting('NEW_FEATURE_ENABLED', True)

    # Accessing dynamic settings:
    feature_enabled = settings.get_dynamic_setting('NEW_FEATURE_ENABLED')
    if feature_enabled:
        # Enable the new feature
        ...

Extending the `Settings` class:

The `Settings` class can be easily extended to accommodate specific configurations
for different environments, services, or scripts. This allows for a layered configuration
structure where you can inherit and override settings based on context.

Example:

    class ProductionSettings(Settings):
        def __init__(self):
            super().__init__()
            # Override default settings for production environment
            self.set_detailed_error_reporting(False)
            self.add_dynamic_setting('LOG_LEVEL', 'ERROR')

    class DevelopmentSettings(Settings):
        def __init__(self):
            super().__init__()
            # Override default settings for development environment
            self.set_detailed_error_reporting(True)
            self.add_dynamic_setting('LOG_LEVEL', 'DEBUG')

Usage Example:

    production_settings = ProductionSettings()
    dev_settings = DevelopmentSettings()

    # Access and use settings based on the environment
    if production_settings.get_detailed_error_reporting():
        # Production-specific logic
        ...

    if dev_settings.get_dynamic_setting('LOG_LEVEL') == 'DEBUG':
        # Development-specific logic
        ...
"""

import utils.errors as errors

class Settings:
    def __init__(self):
        # Initialize default settings
        self._detailed_error_reporting = True
        self._dynamic_settings = {}

    # Getter and setter for detailed error reporting
    def set_detailed_error_reporting(self, value):
        if not isinstance(value, bool):
            raise errors.ProjectSettingError("DETAILED_ERROR_REPORTING must be a boolean.",original_exception=None, include_traceback=False)
        self._detailed_error_reporting = value

    def get_detailed_error_reporting(self):
        return self._detailed_error_reporting

    # Dynamic settings handling
    def add_dynamic_setting(self, key: str, value):
        """Add or modify a dynamic setting."""
        self._dynamic_settings[key] = value

    def get_dynamic_setting(self, key: str):
        """Retrieve a dynamic setting value, or None if the key does not exist."""
        return self._dynamic_settings.get(key)

    # Utility method to display current settings
    def show_settings(self):
        print("DETAILED_ERROR_REPORTING:", self._detailed_error_reporting)
        print("Dynamic Settings:", self._dynamic_settings)