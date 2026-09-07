import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from utils import git_sync


COMMIT_MESSAGE = "Automatic data and config push."
SYNC_PATHS = ["data", "config", "system/state.json"]


def run_git(repo, *args):
    result = subprocess.run(
        ["git", "-C", os.fspath(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip()


class SnapshotSyncIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.remote = root / "origin.git"
        self.seed = root / "seed"
        self.worker = root / "worker"

        subprocess.run(["git", "init", "--bare", os.fspath(self.remote)], check=True)
        subprocess.run(["git", "init", "-b", "main", os.fspath(self.seed)], check=True)
        self._configure(self.seed)

        (self.seed / "data").mkdir()
        (self.seed / "config").mkdir()
        (self.seed / "system").mkdir()
        (self.seed / "data" / "reading.json").write_text("initial\n", encoding="utf-8")
        (self.seed / "config" / "settings.json").write_text("{}\n", encoding="utf-8")
        (self.seed / "system" / "state.json").write_text("{}\n", encoding="utf-8")
        (self.seed / "code.py").write_text("VERSION = 1\n", encoding="utf-8")
        run_git(self.seed, "add", ".")
        run_git(self.seed, "commit", "-m", "Initial commit")
        self.initial_commit = run_git(self.seed, "rev-parse", "HEAD")
        run_git(self.seed, "remote", "add", "origin", os.fspath(self.remote))
        run_git(self.seed, "push", "-u", "origin", "main")
        run_git(self.remote, "symbolic-ref", "HEAD", "refs/heads/main")

        subprocess.run(
            ["git", "clone", os.fspath(self.remote), os.fspath(self.worker)],
            check=True,
        )
        self._configure(self.worker)

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def _configure(repo):
        run_git(repo, "config", "user.name", "Snapshot Test")
        run_git(repo, "config", "user.email", "snapshot@example.invalid")
        run_git(repo, "config", "core.autocrlf", "false")

    def _sync(self):
        return git_sync.sync_snapshot_paths(
            os.fspath(self.worker),
            SYNC_PATHS,
            COMMIT_MESSAGE,
        )

    def _fail_push(self):
        original_git = git_sync._git

        def fail_push(repo_root, args, *, check=True):
            if "push" in args:
                command = ["git", "-C", repo_root] + list(args)
                raise git_sync.GitCommandError(command, 1, stderr="simulated push failure")
            return original_git(repo_root, args, check=check)

        return mock.patch.object(git_sync, "_git", side_effect=fail_push)

    def test_normal_snapshot_pushes_one_commit(self):
        (self.worker / "data" / "reading.json").write_text("new\n", encoding="utf-8")

        result = self._sync()

        self.assertTrue(result.pushed)
        self.assertEqual(run_git(self.worker, "rev-list", "--count", "origin/main..HEAD"), "0")
        self.assertEqual(run_git(self.worker, "show", "origin/main:data/reading.json"), "new")

    def test_failed_push_is_amended_instead_of_appended(self):
        (self.worker / "data" / "reading.json").write_text("first\n", encoding="utf-8")
        with self._fail_push(), self.assertRaises(git_sync.GitCommandError):
            self._sync()

        first_pending = run_git(self.worker, "rev-parse", "HEAD")
        self.assertEqual(run_git(self.worker, "rev-list", "--count", "origin/main..HEAD"), "1")

        (self.worker / "data" / "reading.json").write_text("second\n", encoding="utf-8")
        with self._fail_push(), self.assertRaises(git_sync.GitCommandError):
            self._sync()

        second_pending = run_git(self.worker, "rev-parse", "HEAD")
        self.assertNotEqual(first_pending, second_pending)
        self.assertEqual(run_git(self.worker, "rev-list", "--count", "origin/main..HEAD"), "1")

        self._sync()
        self.assertEqual(run_git(self.worker, "show", "origin/main:data/reading.json"), "second")

    def test_multiple_verified_snapshots_are_collapsed(self):
        for value in ("one\n", "two\n", "three\n"):
            (self.worker / "data" / "reading.json").write_text(value, encoding="utf-8")
            run_git(self.worker, "add", "data")
            run_git(self.worker, "commit", "-m", COMMIT_MESSAGE)

        result = self._sync()

        self.assertEqual(result.collapsed_commits, 3)
        self.assertEqual(
            run_git(self.worker, "rev-list", "--count", f"{self.initial_commit}..origin/main"),
            "1",
        )
        self.assertEqual(run_git(self.worker, "show", "origin/main:data/reading.json"), "three")

    def test_manual_local_commit_is_never_rewritten(self):
        (self.worker / "code.py").write_text("VERSION = 2\n", encoding="utf-8")
        run_git(self.worker, "add", "code.py")
        run_git(self.worker, "commit", "-m", "Manual source work")
        manual_commit = run_git(self.worker, "rev-parse", "HEAD")
        (self.worker / "data" / "reading.json").write_text("new\n", encoding="utf-8")

        with self.assertRaises(git_sync.UnsafeRepositoryState):
            self._sync()

        self.assertEqual(run_git(self.worker, "rev-parse", "HEAD"), manual_commit)
        self.assertEqual(run_git(self.worker, "status", "--short", "data/reading.json"), "M data/reading.json")

    def test_snapshot_message_does_not_authorize_unowned_changes(self):
        (self.worker / "code.py").write_text("VERSION = 2\n", encoding="utf-8")
        run_git(self.worker, "add", "code.py")
        run_git(self.worker, "commit", "-m", COMMIT_MESSAGE)

        with self.assertRaises(git_sync.UnsafeRepositoryState):
            self._sync()

    def test_unrelated_staged_change_is_not_committed(self):
        (self.worker / "code.py").write_text("VERSION = 2\n", encoding="utf-8")
        run_git(self.worker, "add", "code.py")
        (self.worker / "data" / "reading.json").write_text("new\n", encoding="utf-8")

        with self.assertRaises(git_sync.UnsafeRepositoryState):
            self._sync()

        self.assertEqual(run_git(self.worker, "diff", "--cached", "--name-only"), "code.py")

    def test_remote_code_change_and_pending_snapshot_are_both_preserved(self):
        (self.worker / "data" / "reading.json").write_text("pending\n", encoding="utf-8")
        with self._fail_push(), self.assertRaises(git_sync.GitCommandError):
            self._sync()

        other = Path(self.temp_dir.name) / "other"
        subprocess.run(["git", "clone", os.fspath(self.remote), os.fspath(other)], check=True)
        self._configure(other)
        (other / "code.py").write_text("VERSION = 2\n", encoding="utf-8")
        run_git(other, "add", "code.py")
        run_git(other, "commit", "-m", "Remote source update")
        run_git(other, "push", "origin", "main")

        (self.worker / "data" / "reading.json").write_text("latest\n", encoding="utf-8")
        self._sync()

        self.assertEqual(run_git(self.worker, "show", "origin/main:code.py"), "VERSION = 2")
        self.assertEqual(run_git(self.worker, "show", "origin/main:data/reading.json"), "latest")
        self.assertEqual(run_git(self.worker, "rev-list", "--count", "origin/main..HEAD"), "0")

    def test_remote_data_conflict_prefers_latest_local_snapshot(self):
        (self.worker / "data" / "reading.json").write_text("pending\n", encoding="utf-8")
        with self._fail_push(), self.assertRaises(git_sync.GitCommandError):
            self._sync()

        other = Path(self.temp_dir.name) / "other"
        subprocess.run(["git", "clone", os.fspath(self.remote), os.fspath(other)], check=True)
        self._configure(other)
        (other / "data" / "reading.json").write_text("remote\n", encoding="utf-8")
        run_git(other, "add", "data/reading.json")
        run_git(other, "commit", "-m", "Remote data update")
        run_git(other, "push", "origin", "main")

        (self.worker / "data" / "reading.json").write_text("latest local\n", encoding="utf-8")
        self._sync()

        self.assertEqual(
            run_git(self.worker, "show", "origin/main:data/reading.json"),
            "latest local",
        )

    def test_remote_only_change_fast_forwards_without_snapshot_commit(self):
        other = Path(self.temp_dir.name) / "other"
        subprocess.run(["git", "clone", os.fspath(self.remote), os.fspath(other)], check=True)
        self._configure(other)
        (other / "code.py").write_text("VERSION = 2\n", encoding="utf-8")
        run_git(other, "add", "code.py")
        run_git(other, "commit", "-m", "Remote source update")
        run_git(other, "push", "origin", "main")

        result = self._sync()

        self.assertFalse(result.pushed)
        self.assertEqual(run_git(self.worker, "show", "HEAD:code.py"), "VERSION = 2")
        self.assertEqual(run_git(self.worker, "rev-list", "--count", "origin/main..HEAD"), "0")

    def test_deletion_inside_owned_path_is_published(self):
        (self.worker / "data" / "reading.json").unlink()

        self._sync()

        result = subprocess.run(
            ["git", "-C", os.fspath(self.worker), "cat-file", "-e", "origin/main:data/reading.json"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
