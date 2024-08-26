"""
Module-specific error hierarchy for well-aimed error detection and handling.
"""

import traceback
import utils.comms as comms

# Base Exception
class HeatingControlError(Exception):
    """Base exception for all heating system errors."""
    def __init__(self, message, original_exception=None, include_traceback=False):
        # Store the original exception, if provided
        self.original_exception = original_exception
        
        # Optionally include the traceback
        if include_traceback and original_exception is not None:
            message += f"\nTraceback:\n{traceback.format_exc()}"
        
        comms.report(message)

        # Initialize the base Exception with the final message
        super().__init__(message)

# Data Management Errors
class DataManagementError(HeatingControlError):
    """Base exception for data management-related errors."""
    pass

class GitOperationError(DataManagementError):
    """Raised when a Git operation fails."""
    pass

# DeCONZ Module Errors
class DeconzError(HeatingControlError):
    """Base exception for DeCONZ-related errors."""
    pass

class DeconzSetupError(DeconzError):
    """Raised for errors during Deconz setup (such as API key generation, URL read in, etc.)."""
    pass

class DeconzReadError(DeconzError):
    """Raised for errors while trying to get data from the ZigBee mesh."""
    pass

# I/O Errors
class ProjectIOError(HeatingControlError): #Named so it won't interfere with the native IOError class.
    """Base exception for I/O-related errors."""
    pass

# Project Errors
class ProjectError(HeatingControlError):
    """Base exception for project-wide errors."""
    pass

class ProjectConfigError(ProjectError):
    """Raised when configuration file operations fail (e.g., reading rooms.json)."""
    pass

class ProjectSettingError(ProjectError):
    """Raised when issues with settings arise."""
