"""Sync data, config, and system state with the online repository."""

from utils.project import *
import sys


SYNC_PATHS = ['data/', 'config/', 'system/state.json']
COMMIT_MESSAGE = 'Automatic data and config push.'


def confirm_extra_changes(changes):
    """Only a person at a terminal can opt extra files into this upload."""
    if not sys.stdin.isatty():
        return False
    print("Git sync found changes outside the automatic data/config paths:", flush=True)
    print("Status: M=modified, A=added/staged, D=deleted, ??=untracked.")
    for status, path in changes:
        print(f"  {status} {path!r}")
    print("Yes will commit ALL listed changes (including deletions) and sync them to GitHub.")
    print("Check that these files contain no secrets or unfinished work before approving.")
    try:
        answer = input("Include these changes and continue syncing? [y/N] ")
    except (EOFError, KeyboardInterrupt):
        print("\nGit sync cancelled.", flush=True)
        return False
    return answer.strip().lower() in ("y", "yes")


success = False
try:
    check_index_lock()
    success = sync_paths_with_repo(
        SYNC_PATHS, COMMIT_MESSAGE, 30,
        confirm_extra_changes=confirm_extra_changes if sys.stdin.isatty() else None,
    )
    if not success:
        report("Data or config paths remained locked for 30 seconds; Git sync skipped.")
except ModuleException as error:
    report(f"Data and config Git sync failed: {error}")
    ServiceException(
        "Module error while trying to sync data and config with repo",
        original_exception=error,
        severity=2,
    )
except Exception as error:
    report(f"Unexpected data and config Git sync failure: {error!r}")
    ServiceException(
        "Unexpected error while trying to sync data and config with repo",
        severity=2,
    )

log({"success": success, "push_confirmed": success})

if not success:
    raise SystemExit(1)
