import utils.project as project

def get_rooms_info():
    import json

    project_root = project.get_project_root()

    with open(f'{project_root}/system_config/rooms.json', 'r') as file:
        rooms_dict = json.load(file)
        
    return rooms_dict