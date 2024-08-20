"""Everything related the project as a whole."""

def get_project_root():
    """
    Returns the root of the project as a string.
    """

    import os

    current_file_path = os.path.abspath(__file__)
    parent_directory_path = os.path.dirname(current_file_path)
    return os.path.dirname(parent_directory_path)

def get_rooms_info():
    import json

    project_root = project.get_project_root()

    with open(f'{project_root}/system_config/rooms.json', 'r') as file:
        rooms_dict = json.load(file)
        
    return rooms_dict