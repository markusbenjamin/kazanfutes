"""Everything related the project as a whole."""

from utils import errors
from utils import settings

def get_project_root():
    """
    Returns the root of the project as a string.
    """
    try:
        import os

        current_file_path = os.path.abspath(__file__)
        parent_directory_path = os.path.dirname(current_file_path)
        return os.path.dirname(parent_directory_path)
    except OSError as e:
        raise errors.ProjectError(f"Couldn't get project root due to: {e}", original_exception=e, include_traceback=settings.get_detailed_error_reporting()) from e
    except Exception as e:
        raise errors.ProjectError(f"Unexpected error when getting project root: {e}", original_exception=e, include_traceback=settings.get_detailed_error_reporting()) from e

def get_rooms_info():
    try:
        import os
        import json

        project_root = get_project_root()

        with open(os.path.join(project_root, 'system_config', 'rooms.json'), 'r') as file:
            rooms_dict = json.load(file)
            
        return rooms_dict
    except (
        FileNotFoundError,PermissionError,json.JSONDecodeError,OSError
    ) as e:
        raise errors.ProjectConfigError(f"Couldn't get rooms config due to: {e}", original_exception=e, include_traceback=settings.get_detailed_error_reporting()) from e
    except Exception as e:
        raise errors.ProjectConfigError(f"Unexpected error while reading rooms config: {e}", original_exception=e, include_traceback=settings.get_detailed_error_reporting()) from e
