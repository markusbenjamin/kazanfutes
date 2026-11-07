"""Candidate scheduler integrations, imported only by the assembled v2 release."""
import hashlib
import json
from pathlib import Path

from utils.weekly_cycle_config import load_weekly_cycle
from utils.room_registry import registry_from_rows


class LocalWeeklyBaseline:
    def __init__(self, path, controlled_ids):
        self.path = Path(path)
        self.controlled_ids = set(controlled_ids)
        self.config = None
        self.digest = None

    def refresh(self):
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        if digest == self.digest:
            return False
        candidate = load_weekly_cycle(self.path)
        if not self.controlled_ids <= set(candidate['rooms']):
            raise ValueError('Weekly baseline is missing controlled room IDs')
        # Commit only a complete valid snapshot; invalid edits keep the old copy.
        self.config, self.digest = candidate, digest
        return True


def refresh_registry(download, spreadsheet_id, expected_ids, cache_path, publish):
    registry = registry_from_rows(download(spreadsheet_id, 'rooms'), expected_ids)
    path = Path(cache_path)
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)
    publish(registry)
    return registry
