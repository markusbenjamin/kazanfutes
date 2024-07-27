def get_project_root():
    """
    Returns the root of the project as a string.
    """

    import os

    current_file_path = os.path.abspath(__file__)
    parent_directory_path = os.path.dirname(current_file_path)
    return os.path.dirname(parent_directory_path)

def push_dir_to_repo(project_dir, commit_message):
    """
    Pushes a certain project directory to the GitHub repository.
    """

    import os
    import subprocess

    project_root = get_project_root()

    os.chdir(f'{project_root}/{project_dir}')
    subprocess.run(['git', 'add', '.'], check=True)
    subprocess.run(['git', 'commit', '-m', commit_message], check=True)
    subprocess.run(['git', 'push'], check=True)