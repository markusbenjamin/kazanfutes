"""Isolated Git integration tests; never import hardware or run the real uploader.

Run with: python -m unittest utils.test_git_sync -v
"""

import ast
import contextlib
import io
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import unittest
from dataclasses import dataclass
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'utils/project.py').read_text(encoding='utf-8')
git_source = source.split('#region GitHub', 1)[1].split('def check_index_lock', 1)[0]
git_api = dict(os=os, subprocess=subprocess, shlex=shlex, time=time, dataclass=dataclass,
               report=lambda *a, **k: None)
exec(compile(git_source, str(ROOT / 'utils/project.py'), 'exec'), git_api)

uploader_tree = ast.parse((ROOT / 'services/data_and_config_uploader.py').read_text(encoding='utf-8'))
prompt_node = next(node for node in uploader_tree.body
                   if isinstance(node, ast.FunctionDef) and node.name == 'confirm_extra_changes')
prompt_api = {'sys': Mock()}
exec(compile(ast.Module(body=[prompt_node], type_ignores=[]), 'uploader-prompt', 'exec'), prompt_api)


class GitSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'work'
        self.remote = self.root / 'remote.git'
        self.repo.mkdir()
        self.git('init', '--bare', str(self.remote))
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Sync Test')
        self.git('config', 'user.email', 'sync@example.invalid')
        self.git('config', 'core.autocrlf', 'false')
        self.write('payload/current.json', 'initial\n')
        self.write('scripts/tracked.py', 'initial\n')
        self.write('.gitignore', '*.secret\n')
        self.git('add', '.')
        self.git('commit', '-m', 'initial')
        self.git('remote', 'add', 'origin', str(self.remote))
        self.git('push', '-u', 'origin', 'main')
        self.original_head = self.git('rev-parse', 'HEAD')
        self.write('payload/current.json', 'collected\n')

    def git(self, *args, check=True):
        result = subprocess.run(['git', '-C', str(self.repo), *args],
                                capture_output=True, text=True, encoding='utf-8', check=check)
        return result.stdout.strip()

    def write(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def sync(self, callback=None):
        return git_api['_sync_paths_with_repo_unlocked'](
            str(self.repo), ['payload'], 'upload', confirm_extra_changes=callback,
            retry_delay_seconds=0,
        )

    def assert_remote_matches(self):
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.git('rev-parse', 'origin/main'))

    def test_yes_commits_tracked_untracked_staged_and_deleted(self):
        self.write('scripts/tracked.py', 'approved\n')
        self.write('scripts/new file.py', 'new\n')
        self.write('scripts/staged.py', 'staged\n')
        self.git('add', 'scripts/staged.py')
        (self.repo / '.gitignore').unlink()
        approved = []
        result = self.sync(lambda changes: approved.extend(changes) or True)
        self.assertTrue(result.committed)
        self.assertEqual({path for _, path in approved},
                         {'scripts/tracked.py', 'scripts/new file.py', 'scripts/staged.py', '.gitignore'})
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assert_remote_matches()

    def test_no_preserves_head_index_and_worktree(self):
        self.write('scripts/tracked.py', 'keep\n')
        self.git('add', 'scripts/tracked.py')
        self.write('scripts/new.py', 'new\n')
        before = self.git('status', '--porcelain')
        index = self.git('write-tree')
        with self.assertRaises(git_api['GitSyncBlocked']):
            self.sync(lambda changes: False)
        self.assertEqual(self.git('status', '--porcelain'), before)
        self.assertEqual(self.git('write-tree'), index)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.original_head)
        self.assertEqual(self.git('rev-parse', 'origin/main'), self.original_head)

    def test_unattended_blocks_tracked_changes(self):
        self.write('scripts/tracked.py', 'keep\n')
        with self.assertRaisesRegex(git_api['GitSyncBlocked'], 'scripts/tracked.py'):
            self.sync()
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.original_head)

    def test_unattended_leaves_untracked_files_alone(self):
        self.write('scripts/new.py', 'keep\n')
        self.sync()
        self.assertEqual(self.git('status', '--porcelain'), '?? scripts/new.py')
        self.assert_remote_matches()

    def test_interactive_untracked_only_is_offered(self):
        self.write('scripts/new.py', 'new\n')
        callback = Mock(return_value=True)
        self.sync(callback)
        callback.assert_called_once_with((('??', 'scripts/new.py'),))
        self.assert_remote_matches()

    def test_clean_extra_paths_do_not_prompt_and_ignored_files_stay_ignored(self):
        self.write('scripts/private.secret', 'secret\n')
        callback = Mock(return_value=True)
        self.sync(callback)
        callback.assert_not_called()
        self.assertEqual(self.git('ls-files', 'scripts/private.secret'), '')

    def test_new_path_during_prompt_aborts(self):
        self.write('scripts/tracked.py', 'keep\n')
        def confirm(changes):
            self.write('scripts/surprise.py', 'not approved\n')
            return True
        with self.assertRaisesRegex(git_api['GitSyncBlocked'], 'changed during confirmation'):
            self.sync(confirm)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.original_head)
        self.assertEqual(self.git('diff', '--cached', '--name-only'), '')

    def test_literal_unicode_and_bracket_paths(self):
        self.write('scripts/[x] caf\u00e9.py', 'literal\n')
        callback = Mock(return_value=True)
        self.sync(callback)
        callback.assert_called_once_with((('??', 'scripts/[x] caf\u00e9.py'),))
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_staged_and_worktree_changes_that_cancel_still_block(self):
        self.write('scripts/tracked.py', 'staged\n')
        self.git('add', 'scripts/tracked.py')
        self.write('scripts/tracked.py', 'initial\n')
        with self.assertRaises(git_api['GitSyncBlocked']):
            self.sync()

    def test_merge_in_progress_is_not_auto_committed(self):
        self.git('update-ref', 'MERGE_HEAD', 'HEAD')
        callback = Mock(return_value=True)
        with self.assertRaisesRegex(git_api['GitSyncBlocked'], 'unfinished Git operation'):
            self.sync(callback)
        callback.assert_not_called()
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.original_head)

    def test_detached_head_is_blocked(self):
        self.git('checkout', '--detach')
        with self.assertRaisesRegex(git_api['GitSyncBlocked'], 'checkout must be on main'):
            self.sync()

    def test_remote_failure_preserves_local_commit(self):
        self.git('remote', 'set-url', '--push', 'origin', str(self.root / 'missing.git'))
        self.write('scripts/tracked.py', 'approved\n')
        with self.assertRaises(git_api['GitCommandError']):
            self.sync(lambda changes: True)
        self.assertNotEqual(self.git('rev-parse', 'HEAD'), self.original_head)
        self.assertEqual(self.git('show', 'HEAD:scripts/tracked.py'), 'approved')

    def test_incoming_conflict_preserves_approved_commit_and_aborts_merge(self):
        self.write('scripts/tracked.py', 'remote edit\n')
        self.git('add', 'scripts/tracked.py')
        self.git('commit', '-m', 'remote edit')
        self.git('push')
        # Reset only this disposable fixture to model a collector behind GitHub.
        self.git('reset', '--hard', self.original_head)
        self.write('scripts/tracked.py', 'approved local edit\n')
        with self.assertRaises(git_api['GitCommandError']):
            self.sync(lambda changes: True)
        self.assertEqual(self.git('show', 'HEAD:scripts/tracked.py'), 'approved local edit')
        self.assertFalse((self.repo / '.git/MERGE_HEAD').exists())
        self.assertEqual(self.git('status', '--porcelain'), '')


class UploaderTests(unittest.TestCase):
    def run_uploader(self, interactive, success=True):
        # Execute the real entry point with dependencies replaced; no project
        # import, hardware, logs or production Git repository are accessed.
        tree = ast.Module(body=[node for node in uploader_tree.body
                                if not isinstance(node, (ast.Import, ast.ImportFrom))], type_ignores=[])
        terminal = Mock()
        terminal.stdin.isatty.return_value = interactive
        namespace = dict(sys=terminal, check_index_lock=Mock(),
                         sync_paths_with_repo=Mock(return_value=success), report=Mock(),
                         ModuleException=RuntimeError, ServiceException=Mock(), log=Mock())
        try:
            exec(compile(tree, 'uploader-entry-point', 'exec'), namespace)
        except SystemExit as error:
            namespace['exit_status'] = error.code
        return namespace

    def test_cli_passes_confirmation_callback(self):
        result = self.run_uploader(True)
        self.assertIs(result['sync_paths_with_repo'].call_args.kwargs['confirm_extra_changes'],
                      result['confirm_extra_changes'])
        result['log'].assert_called_once_with({'success': True, 'push_confirmed': True})

    def test_service_has_no_callback(self):
        result = self.run_uploader(False)
        self.assertIsNone(result['sync_paths_with_repo'].call_args.kwargs['confirm_extra_changes'])

    def test_failed_sync_exits_nonzero_and_does_not_report_push(self):
        result = self.run_uploader(True, success=False)
        self.assertEqual(result['exit_status'], 1)
        result['log'].assert_called_once_with({'success': False, 'push_confirmed': False})


class PromptTests(unittest.TestCase):
    def test_explicit_yes_only(self):
        prompt_api['sys'].stdin.isatty.return_value = True
        for answer, expected in [('yes', True), (' Y ', True), ('no', False), ('', False), ('maybe', False)]:
            with self.subTest(answer=answer), patch('builtins.input', return_value=answer), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(prompt_api['confirm_extra_changes'](((' M', 'script.py'),)), expected)
                self.assertIn('script.py', output.getvalue())

    def test_eof_and_interrupt_decline(self):
        prompt_api['sys'].stdin.isatty.return_value = True
        for error in (EOFError, KeyboardInterrupt):
            with patch('builtins.input', side_effect=error), contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(prompt_api['confirm_extra_changes']((('??', 'new.py'),)))

    def test_noninteractive_never_reads_input(self):
        prompt_api['sys'].stdin.isatty.return_value = False
        with patch('builtins.input') as read:
            self.assertFalse(prompt_api['confirm_extra_changes'](((' M', 'script.py'),)))
            read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
