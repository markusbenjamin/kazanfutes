"""
Everything related to error handling, including:
    - module-specific exception hierarchy for well-aimed error detection and handling,
    - error registration.
"""

import traceback
import utils.comms as comms

#region Exception hierarchy
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

#endregion

#region Error registration
def error_registrar(exception_type, severity, origin, origin_timestamp):
    """
    Registers a new error in error_registry.json if not already present and the file is not locked.
    If error_registry.json is locked, appends the error to error_buffer.json for later retry.
    Automatically sets default values for metadata (reported, timestamps, etc.).
    
    Parameters:
    exception_type (str): Type of the raised exception, preferably from the project-specific exception hierarchy.
    severity (str): Severity level of the error (1 := low, 2 := moderate, 3 :=high).
    origin (str): Where the error originated (e.g., file, function, line).
    origin_timestamp (str): Timestamp when the error occurred.
    """

    import json
    import os
    import time
    from filelock import FileLock
    from utils.project import get_project_root

    # Define the hardcoded paths to the error registry and buffer using the absolute project root
    ERROR_REGISTRY_PATH = f"{get_project_root()}/data/errors/error_registry.json"
    ERROR_BUFFER_PATH = f"{get_project_root()}/data/errors/error_buffer.json"

    
    error_entry = {
        "exception_type": exception_type, 
        "severity": severity,
        "origin": origin,
        "origin_timestamp": origin_timestamp,
        "registration_timestamp": time.strftime("%Y-%m-%d-%H-%M-%S"),
        "reported": False,
        "reported_timestamp": None,
        "system_admin_checked": False,
        "system_admin_checked_timestamp": None
    }
    
    # Step 1: Ensure error_registry.json exists, create if missing
    if not os.path.exists(ERROR_REGISTRY_PATH):
        with open(ERROR_REGISTRY_PATH, 'w') as f:
            json.dump([], f)
    
    try: # Step 2: Try to acquire a lock on the error_registry.json file
        with FileLock(ERROR_REGISTRY_PATH + ".lock"):
            # Step 2a: Open and read the current error registry
            with open(ERROR_REGISTRY_PATH, 'r') as f:
                error_registry = json.load(f)
            
            # Step 2b: Check if the error is already registered based on its identity
            already_registered = False
            for existing_error in error_registry:
                if (existing_error["exception_type"] == error_entry["exception_type"] and
                    existing_error["severity"] == error_entry["severity"] and
                    existing_error["origin"] == error_entry["origin"]):
                    already_registered = True
                    break

            # If the error is not already registered, append it
            if not already_registered:
                error_registry.append(error_entry)
                
                # Step 2c: Write the updated registry back to file
                with open(ERROR_REGISTRY_PATH, 'w') as f:
                    json.dump(error_registry, f, indent=4)
    except: # Step 3: Ensure error_buffer.json exists, create if missing
        if not os.path.exists(ERROR_BUFFER_PATH):
            with open(ERROR_BUFFER_PATH, 'w') as f:
                json.dump([], f)
        
        # Step 3a: If error_registry.json is locked, write to the error_buffer.json
        with FileLock(ERROR_BUFFER_PATH + ".lock"):
            with open(ERROR_BUFFER_PATH, 'r') as f:
                error_buffer = json.load(f)
                
            # Step 3b: Append the error to the buffer
            error_buffer.append(error_entry)
            
            # Step 3c: Write the buffer back to file
            with open(ERROR_BUFFER_PATH, 'w') as f:
                json.dump(error_buffer, f, indent=4)