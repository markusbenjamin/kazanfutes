"""Wrapper functions for data management operations."""

from utils.base import *

def push_dir_to_repo(project_dir_path, commit_message):
    """
    Pushes a project directory to the GitHub repository.
    """

    import os
    import subprocess

    try:
        project_root = project.get_project_root()

        # Handle changing directory
        os.chdir(os.path.join(project_root, project_dir_path))
    except (FileNotFoundError, PermissionError, OSError) as e:
        raise errors.GitOperationError(f"Failed to change directory to {project_dir_path}: {e}", original_exception = e, include_traceback = settings.get_detailed_error_reporting()) from e
    except Exception as e:
        raise errors.GitOperationError(f"Unexpected error while changing directory: {e}", original_exception = e, include_traceback = settings.get_detailed_error_reporting()) from e

    try:
        # Handle 'git add'
        subprocess.run(['git', 'add', '.'], check=True)

        # Check if there are changes staged for commit
        result = subprocess.run(['git', 'diff', '--cached', '--exit-code'], check=False)

        # Only commit and push if there are staged changes
        if result.returncode != 0:
            # Handle 'git commit'
            subprocess.run(['git', 'commit', '-m', commit_message], check=True)

            # Push the changes to the remote repository
            subprocess.run(['git', 'push'], check=True)
        else:
            comms.report("No changes staged for commit. Skipping commit and push.")
    except subprocess.CalledProcessError as e:
        raise errors.GitOperationError(f"Git command failed: {e}") from e
    except Exception as e:
        raise errors.GitOperationError(f"Unexpected error while pushing {project_dir_path} to repo: {e}", original_exception = e, include_traceback = settings.get_detailed_error_reporting()) from e