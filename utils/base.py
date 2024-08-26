"""
Unified import and re-export of essential module parts.

Invoke with:
    from utils.base import *
in other scripts to access module parts with no prefix.
"""

# Import
import utils.errors as errors
import utils.comms as comms
from utils.settings import Settings
import utils.project as project

settings = Settings()

# Re-export
__all__ = ['errors', 'comms', 'settings','project']