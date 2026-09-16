"""Checks that GitHub upload alerts follow confirmed pushes and local data."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from services.service_data_watchdog import git_push_candidates


class GitPushMonitorTests(unittest.TestCase):
    def test_alerts_only_for_data_waiting_beyond_push_limit(self):
        now = datetime.now().astimezone().replace(microsecond=0)
        config = {
            "git_push_monitor": {"max_age_minutes": 30},
            "streams": {"system/state.json": {}},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "system/state.json"
            state.parent.mkdir()
            state.write_text("{}", encoding="utf-8")
            log = root / "data/logs/service_execution/data_and_config_uploader/data_and_config_uploader.json"
            log.parent.mkdir(parents=True)
            old_push = now - timedelta(minutes=40)
            log.write_text(json.dumps({
                "timestamp": old_push.strftime("%Y-%m-%d-%H-%M-%S"),
                "success": True, "push_confirmed": True,
            }) + "\n", encoding="utf-8")

            os.utime(state, ((now - timedelta(minutes=5)).timestamp(),) * 2)
            self.assertEqual(
                [item["kind"] for item in git_push_candidates(root, config, now)],
                ["git_push_stale"],
            )

            os.utime(state, ((now - timedelta(minutes=45)).timestamp(),) * 2)
            self.assertEqual(git_push_candidates(root, config, now), [])

            os.utime(state, ((now - timedelta(minutes=5)).timestamp(),) * 2)
            log.write_text(json.dumps({
                "timestamp": (now - timedelta(minutes=10)).strftime("%Y-%m-%d-%H-%M-%S"),
                "success": True, "push_confirmed": True,
            }) + "\n", encoding="utf-8")
            self.assertEqual(git_push_candidates(root, config, now), [])

            log.write_text(json.dumps({
                "timestamp": (now - timedelta(minutes=10)).strftime("%Y-%m-%d-%H-%M-%S"),
                "success": True,
            }) + "\n", encoding="utf-8")
            self.assertEqual(
                [item["kind"] for item in git_push_candidates(root, config, now)],
                ["git_push_stale"],
            )


if __name__ == "__main__":
    unittest.main()
