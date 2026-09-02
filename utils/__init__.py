"""Utilities package initialization."""

import getpass
import json
import os
import socket
import sys
from datetime import datetime

from . import project as _project


def _lock_project_dir_with_metadata(relative_path: str, stale_threshold: int = 300) -> bool:
    """Create a project marker lock containing creator metadata."""
    lock_file = os.path.join(_project.get_project_root(), relative_path) + ".lock"

    # check_lock removes stale locks and returns True for a still-active lock.
    if _project.check_lock(relative_path, stale_threshold):
        age = max(0.0, _project.time.time() - os.path.getmtime(lock_file))
        raise _project.ModuleException(
            f"lock already active at {lock_file} ({age:.1f}s old)",
            severity=1,
        )

    metadata = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "script": os.path.abspath(sys.argv[0]) if sys.argv else None,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "user": getpass.getuser(),
    }

    try:
        with open(lock_file, "x", encoding="utf-8") as file:
            json.dump(metadata, file, indent=2)
            file.write("\n")
        _project.report(f"Locked {relative_path}", verbose=True)
        return True
    except Exception as exc:
        raise _project.ModuleException(
            f"couldn't create lock file at {lock_file}: {exc}",
            severity=2,
        )


# Keep all existing call sites working while making newly-created marker locks
# self-describing. Direct imports from utils.project receive this replacement.
_project.lock_project_dir = _lock_project_dir_with_metadata
