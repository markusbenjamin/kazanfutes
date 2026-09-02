"""
Syncs data, config and system state to the online repo.
"""

import json
import os
try:
    import pwd
except ImportError:
    pwd = None
import time
from datetime import datetime

import filelock

from utils.project import *

SYNC_PATHS = ['data/', 'config/', 'system/state.json']


def _format_age(seconds):
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def _inspect_lock(lock_file):
    if not os.path.isfile(lock_file):
        return None

    stat = os.stat(lock_file)
    age_seconds = time.time() - stat.st_mtime
    info = {
        'path': lock_file,
        'age_seconds': age_seconds,
        'modified_at': datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec='seconds'),
        'owner': None,
        'metadata': {},
    }

    try:
        info['owner'] = pwd.getpwuid(stat.st_uid).pw_name if pwd else str(stat.st_uid)
    except KeyError:
        info['owner'] = str(stat.st_uid)

    try:
        with open(lock_file, 'r', encoding='utf-8') as file:
            content = file.read().strip()
        if content:
            metadata = json.loads(content)
            if isinstance(metadata, dict):
                info['metadata'] = metadata
    except (OSError, json.JSONDecodeError):
        pass

    return info


def _format_lock(info, *, lock_type='project marker'):
    metadata = info['metadata']
    parts = [
        info['path'],
        f"type={lock_type}",
        f"age={_format_age(info['age_seconds'])}",
        f"mtime={info['modified_at']}",
    ]

    creator_bits = []
    if metadata.get('script'):
        creator_bits.append(f"script={metadata['script']}")
    if metadata.get('pid') is not None:
        creator_bits.append(f"pid={metadata['pid']}")
    if metadata.get('hostname'):
        creator_bits.append(f"host={metadata['hostname']}")
    if metadata.get('user'):
        creator_bits.append(f"user={metadata['user']}")
    elif info.get('owner'):
        creator_bits.append(f"file_owner={info['owner']}")
    if metadata.get('created_at'):
        creator_bits.append(f"created={metadata['created_at']}")

    if creator_bits:
        parts.append("creator=" + ", ".join(creator_bits))
    else:
        parts.append("creator=unknown (legacy/empty lock)")

    return " - " + " | ".join(parts)


def report_blocking_locks():
    project_root = get_project_root()
    lock_infos = []

    for project_path in SYNC_PATHS:
        normalized_path = project_path.strip('/')
        lock_file = os.path.join(project_root, normalized_path) + '.lock'
        info = _inspect_lock(lock_file)
        if info:
            lock_infos.append(_format_lock(info))

    index_lock = _inspect_lock(os.path.join(project_root, '.git', 'index.lock'))
    if index_lock:
        lock_infos.append(_format_lock(index_lock, lock_type='git index'))

    repo_sync_lock_path = os.path.join(project_root, 'system', 'repo_sync.lock')
    repo_sync_active = False
    try:
        with filelock.FileLock(repo_sync_lock_path, timeout=0):
            pass
    except filelock.Timeout:
        repo_sync_active = True

    if repo_sync_active:
        repo_sync_lock = _inspect_lock(repo_sync_lock_path)
        if repo_sync_lock:
            lock_infos.append(_format_lock(repo_sync_lock, lock_type='repository sync'))
        else:
            lock_infos.append(f" - {repo_sync_lock_path} | type=repository sync | active")

    if lock_infos:
        report("Active lock details:\n" + "\n".join(lock_infos))
    else:
        report("No active lock file could be identified after the sync failure.")


success = False
try:
    check_index_lock()
    success = sync_paths_with_repo(SYNC_PATHS, 'Automatic data and config push.', 30)
    if not success:
        report("Data and config paths locked, couldn't push.")
        report_blocking_locks()
except ModuleException as e:
    report_blocking_locks()
    ServiceException("Module error while trying to sync data and config with repo", original_exception=e, severity=2)
except Exception:
    report_blocking_locks()
    ServiceException("Unexpected error while trying to sync data and config with repo", severity=2)

log({"success": success})
