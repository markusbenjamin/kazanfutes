import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from utils import project


COMMIT_MESSAGE = "Automatic data and config push."
SYNC_PATHS = ["data", "config", "system/state.json"]


def run_git(repo, *args, check=True):
    result = subprocess.run(
        ["git", "-C", os.fspath(repo), *args],
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip()


class MergeSyncIntegrationTests(unittest.TestCase):
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
        (self.seed / "local_notes.py").write_text("NOTE = 1\n", encoding="utf-8")
        run_git(self.seed, "add", ".")
        run_git(self.seed, "commit", "-m", "Initial commit")
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
        run_git(repo, "config", "user.name", "Sync Test")
        run_git(repo, "config", "user.email", "sync@example.invalid")
        run_git(repo, "config", "core.autocrlf", "false")

    def _clone_other(self):
        other = Path(self.temp_dir.name) / "other"
        subprocess.run(["git", "clone", os.fspath(self.remote), os.fspath(other)], check=True)
        self._configure(other)
        return other

    def _sync(self, **kwargs):
        return project._sync_paths_with_repo_unlocked(
            os.fspath(self.worker),
            SYNC_PATHS,
            COMMIT_MESSAGE,
            retry_delay_seconds=0,
            **kwargs,
        )

    def test_normal_sync_commits_and_pushes(self):
        (self.worker / "data" / "reading.json").write_text("new\n", encoding="utf-8")

        result = self._sync()

        self.assertTrue(result.committed)
        self.assertEqual(result.push_attempts, 1)
        self.assertEqual(run_git(self.worker, "rev-list", "--count", "origin/main..HEAD"), "0")
        self.assertEqual(run_git(self.worker, "show", "origin/main:data/reading.json"), "new")

    def test_remote_code_and_uncommitted_local_code_are_preserved(self):
        other = self._clone_other()
        (other / "code.py").write_text("VERSION = 2\n", encoding="utf-8")
        run_git(other, "add", "code.py")
        run_git(other, "commit", "-m", "Remote source update")
        run_git(other, "push", "origin", "main")

        (self.worker / "local_notes.py").write_text("NOTE = 2\n", encoding="utf-8")
        (self.worker / "data" / "reading.json").write_text("new\n", encoding="utf-8")

        self._sync()

        self.assertEqual(run_git(self.worker, "show", "HEAD:code.py"), "VERSION = 2")
        self.assertEqual((self.worker / "local_notes.py").read_text(encoding="utf-8"), "NOTE = 2\n")
        self.assertEqual(run_git(self.worker, "status", "--short", "local_notes.py"), "M local_notes.py")
        self.assertEqual(run_git(self.worker, "show", "origin/main:data/reading.json"), "new")

    def test_failed_merge_is_aborted_without_losing_local_commit(self):
        other = self._clone_other()
        (other / "data" / "reading.json").write_text("remote\n", encoding="utf-8")
        run_git(other, "add", "data/reading.json")
        run_git(other, "commit", "-m", "Remote data update")
        run_git(other, "push", "origin", "main")

        (self.worker / "data" / "reading.json").write_text("local\n", encoding="utf-8")

        with self.assertRaises(project.GitCommandError):
            self._sync()

        git_dir = Path(run_git(self.worker, "rev-parse", "--git-dir"))
        if not git_dir.is_absolute():
            git_dir = self.worker / git_dir
        self.assertFalse((git_dir / "MERGE_HEAD").exists())
        self.assertEqual(run_git(self.worker, "show", "HEAD:data/reading.json"), "local")
        self.assertEqual(run_git(self.worker, "show", "origin/main:data/reading.json"), "remote")

    def test_push_race_is_merge_pulled_and_retried_once(self):
        other = self._clone_other()
        (self.worker / "data" / "reading.json").write_text("new\n", encoding="utf-8")
        original_git = project._run_git_command
        raced = False

        def inject_remote_commit(repo_root, args, **kwargs):
            nonlocal raced
            if list(args[:3]) == ["push", "-u", "origin"] and not raced:
                raced = True
                (other / "code.py").write_text("VERSION = 2\n", encoding="utf-8")
                run_git(other, "add", "code.py")
                run_git(other, "commit", "-m", "Racing remote update")
                run_git(other, "push", "origin", "main")
            return original_git(repo_root, args, **kwargs)

        with mock.patch.object(project, "_run_git_command", side_effect=inject_remote_commit):
            result = self._sync()

        self.assertEqual(result.push_attempts, 2)
        self.assertEqual(run_git(self.worker, "show", "origin/main:code.py"), "VERSION = 2")
        self.assertEqual(run_git(self.worker, "show", "origin/main:data/reading.json"), "new")

    def test_orphaned_rebase_autostash_marker_is_quit(self):
        git_dir = Path(run_git(self.worker, "rev-parse", "--git-dir"))
        if not git_dir.is_absolute():
            git_dir = self.worker / git_dir
        marker_dir = git_dir / "rebase-merge"
        marker_dir.mkdir()
        (marker_dir / "autostash").write_text("0" * 40 + "\n", encoding="ascii")
        (self.worker / "data" / "reading.json").write_text("new\n", encoding="utf-8")

        self._sync()

        self.assertFalse(marker_dir.exists())
        self.assertEqual(run_git(self.worker, "show", "origin/main:data/reading.json"), "new")

    def test_timeout_reports_command_and_duration(self):
        timeout = subprocess.TimeoutExpired(
            ["git", "-C", os.fspath(self.worker), "status"],
            12,
            stderr=b"transport stopped responding",
        )
        with mock.patch("utils.project.subprocess.run", side_effect=timeout):
            with self.assertRaises(project.GitCommandError) as context:
                project._run_git_command(os.fspath(self.worker), ["status"], timeout=12)

        message = str(context.exception)
        self.assertIn("git -C", message)
        self.assertIn("timed out after 12 seconds", message)
        self.assertIn("transport stopped responding", message)


if __name__ == "__main__":
    unittest.main()
