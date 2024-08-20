"""Wrapper functions for data management operations."""

import utils.project as project

def push_dir_to_repo(project_dir, commit_message):
    """
    Pushes a certain project directory to the GitHub repository.
    """

    import os
    import subprocess

    project_root = project.get_project_root()

    os.chdir(f'{project_root}/{project_dir}')
    subprocess.run(['git', 'add', '.'], check=True)
    result = subprocess.run(['git', 'status', '--porcelain'], capture_output=True, text=True)
    
    if not result.stdout.strip():
        print("Nothing to commit, working tree clean.")
    else:
        try:
            subprocess.run(['git', 'commit', '-m', commit_message])
            subprocess.run(['git', 'push'])
        except subprocess.CalledProcessError as e:
            pass