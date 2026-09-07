"""Small, testable Git primitives used by the automated repository sync jobs.

The snapshot publisher in this module is intentionally conservative.  It may
rewrite unpublished commits only when every such commit has the expected
message, has one parent, and changes only paths owned by the caller.
"""

from dataclasses import dataclass
import os
import shlex
import subprocess
from typing import Callable, Iterable, Optional


GIT_COMMAND_TIMEOUT_SECONDS = 15 * 60


def _output_text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


class GitSyncError(RuntimeError):
    """Base class for repository-sync failures."""


class UnsafeRepositoryState(GitSyncError):
    """Raised when automatic history rewriting would be unsafe."""


class GitCommandError(GitSyncError):
    """Raised with useful command output when Git exits unsuccessfully."""

    def __init__(self, command, returncode, stdout="", stderr=""):
        details = (stderr or stdout or "").strip()
        message = f"Git command failed with exit code {returncode}: {shlex.join(command)}"
        if details:
            message += f"\n{details}"
        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@dataclass(frozen=True)
class SnapshotSyncResult:
    remote_commit: str
    local_commit: str
    changed: bool
    pushed: bool
    collapsed_commits: int = 0


def _git(repo_root, args, *, check=True):
    command = ["git", "-C", repo_root] + list(args)
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        stdout = _output_text(error.stdout)
        stderr = _output_text(error.stderr)
        if stderr:
            stderr = stderr.rstrip() + "\n"
        stderr += f"Git command timed out after {GIT_COMMAND_TIMEOUT_SECONDS} seconds."
        raise GitCommandError(
            command,
            -1,
            stdout=stdout,
            stderr=stderr,
        ) from error
    if check and result.returncode != 0:
        raise GitCommandError(
            command,
            result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return result


def _git_output(repo_root, args):
    return _git(repo_root, args).stdout.strip()


def _normalize_paths(project_paths: Iterable[os.PathLike | str]):
    if isinstance(project_paths, (str, os.PathLike)):
        project_paths = [project_paths]

    normalized = []
    for project_path in project_paths:
        path = os.fspath(project_path).replace("\\", "/").strip()
        path = "." if path in ("", ".") else path.strip("/")
        if os.path.isabs(path) or path == ".." or path.startswith("../") or "/../" in f"/{path}/":
            raise UnsafeRepositoryState(f"unsafe path for repository sync: {project_path}")
        normalized.append(path)

    if not normalized:
        raise UnsafeRepositoryState("no paths were provided for repository sync")
    return normalized


def _changed_paths(repo_root, args):
    output = _git(repo_root, list(args) + ["-z"]).stdout
    return [path for path in output.split("\0") if path]


def _path_is_owned(path, owned_paths):
    path = path.replace("\\", "/").strip("/")
    for owned_path in owned_paths:
        if owned_path == "." or path == owned_path or path.startswith(owned_path + "/"):
            return True
    return False


def _assert_no_operation_in_progress(repo_root):
    markers = (
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "rebase-apply",
        "rebase-merge",
    )
    active = []
    for marker in markers:
        marker_path = _git_output(repo_root, ["rev-parse", "--git-path", marker])
        if not os.path.isabs(marker_path):
            marker_path = os.path.join(repo_root, marker_path)
        if os.path.exists(marker_path):
            active.append(marker)
    if active:
        raise UnsafeRepositoryState(
            "repository has an unfinished Git operation: " + ", ".join(active)
        )


def _assert_expected_branch(repo_root, branch):
    result = _git(
        repo_root,
        ["symbolic-ref", "--quiet", "--short", "HEAD"],
        check=False,
    )
    current_branch = result.stdout.strip()
    if result.returncode != 0 or current_branch != branch:
        displayed = current_branch or "detached HEAD"
        raise UnsafeRepositoryState(
            f"snapshot sync requires branch {branch!r}, but the checkout is on {displayed!r}"
        )


def _assert_no_unrelated_staged_paths(repo_root, owned_paths):
    staged_paths = _changed_paths(repo_root, ["diff", "--cached", "--name-only"])
    unrelated = [path for path in staged_paths if not _path_is_owned(path, owned_paths)]
    if unrelated:
        raise UnsafeRepositoryState(
            "refusing to include unrelated staged changes in an automatic snapshot: "
            + ", ".join(unrelated)
        )


def _unpublished_commits(repo_root, remote_commit):
    output = _git_output(repo_root, ["rev-list", "--reverse", f"{remote_commit}..HEAD"])
    return output.splitlines() if output else []


def _validate_unpublished_commits(repo_root, commits, commit_message, owned_paths):
    problems = []
    for commit in commits:
        revision = _git_output(repo_root, ["rev-list", "--parents", "-n", "1", commit]).split()
        subject = _git_output(repo_root, ["show", "-s", "--format=%s", commit])
        changed_paths = _changed_paths(
            repo_root,
            ["diff-tree", "--root", "--no-commit-id", "--name-only", "-r", commit],
        )
        unrelated = [path for path in changed_paths if not _path_is_owned(path, owned_paths)]

        reasons = []
        if len(revision) != 2:
            reasons.append("is a merge or has an unexpected parent count")
        if subject != commit_message:
            reasons.append(f"has subject {subject!r}")
        if unrelated:
            reasons.append("changes unowned paths: " + ", ".join(unrelated))
        if reasons:
            problems.append(f"{commit[:12]} " + "; ".join(reasons))

    if problems:
        raise UnsafeRepositoryState(
            "refusing to rewrite unpublished commits that are not verified snapshots:\n"
            + "\n".join(problems)
        )


def _has_cached_changes(repo_root):
    result = _git(repo_root, ["diff", "--cached", "--quiet"], check=False)
    if result.returncode not in (0, 1):
        raise GitCommandError(
            result.args,
            result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return result.returncode == 1


def _is_ancestor(repo_root, ancestor, descendant):
    result = _git(
        repo_root,
        ["merge-base", "--is-ancestor", ancestor, descendant],
        check=False,
    )
    if result.returncode not in (0, 1):
        raise GitCommandError(
            result.args,
            result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return result.returncode == 0


def _commit_snapshot(repo_root, commit_message, *, amend=False):
    if amend:
        _git(repo_root, ["commit", "--amend", "--no-edit", "--no-gpg-sign"])
    else:
        _git(
            repo_root,
            [
                "commit",
                "--no-gpg-sign",
                "-m",
                commit_message,
                "-m",
                "Kazanfutes-Sync: snapshot-v1",
            ],
        )


def sync_snapshot_paths(
    repo_root,
    project_paths,
    commit_message,
    *,
    remote="origin",
    branch="main",
    reporter: Optional[Callable[[str], None]] = None,
):
    """Publish one effective snapshot while preserving non-snapshot history.

    If a previous push failed, its unpublished snapshot is amended or multiple
    verified snapshots are collapsed.  Any unpublished manual commit, merge, or
    change outside ``project_paths`` causes a safe failure instead of a reset.
    """

    repo_root = os.path.abspath(repo_root)
    owned_paths = _normalize_paths(project_paths)
    report = reporter or (lambda _message: None)

    _assert_no_operation_in_progress(repo_root)
    _assert_expected_branch(repo_root, branch)
    _git(repo_root, ["fetch", "--no-tags", remote, branch])
    remote_commit = _git_output(repo_root, ["rev-parse", "FETCH_HEAD"])

    _assert_no_unrelated_staged_paths(repo_root, owned_paths)
    pending = _unpublished_commits(repo_root, remote_commit)
    _validate_unpublished_commits(
        repo_root,
        pending,
        commit_message,
        owned_paths,
    )
    report(
        f"Git snapshot preflight: remote={remote_commit[:12]}, "
        f"verified_pending={len(pending)}."
    )

    _git(repo_root, ["add", "-A", "--"] + owned_paths)
    if _has_cached_changes(repo_root):
        _commit_snapshot(repo_root, commit_message, amend=bool(pending))
        report("Captured the current files in the pending automatic snapshot.")

    head = _git_output(repo_root, ["rev-parse", "HEAD"])
    if not _is_ancestor(repo_root, remote_commit, head):
        if _is_ancestor(repo_root, head, remote_commit):
            report("Fast-forwarding the checkout to the fetched remote commit.")
            _git(repo_root, ["merge", "--ff-only", remote_commit])
        else:
            report("Rebasing verified automatic snapshots onto the fetched remote commit.")
            try:
                # During a rebase Git's 'theirs' side is the commit being replayed.
                # The Pi is authoritative for conflicts inside the owned snapshot paths.
                _git(
                    repo_root,
                    [
                        "-c",
                        "rebase.autoStash=false",
                        "rebase",
                        "-X",
                        "theirs",
                        remote_commit,
                    ],
                )
            except GitCommandError:
                _git(repo_root, ["rebase", "--abort"], check=False)
                raise

    # Pick up writes that landed while the remote history was being synchronized.
    pending = _unpublished_commits(repo_root, remote_commit)
    _validate_unpublished_commits(
        repo_root,
        pending,
        commit_message,
        owned_paths,
    )
    _git(repo_root, ["add", "-A", "--"] + owned_paths)
    if _has_cached_changes(repo_root):
        _commit_snapshot(repo_root, commit_message, amend=bool(pending))

    pending = _unpublished_commits(repo_root, remote_commit)
    _validate_unpublished_commits(
        repo_root,
        pending,
        commit_message,
        owned_paths,
    )

    collapsed_commits = 0
    if len(pending) > 1:
        collapsed_commits = len(pending)
        report(f"Collapsing {len(pending)} verified automatic snapshots into one.")
        _git(repo_root, ["reset", "--soft", remote_commit])
        _git(repo_root, ["reset", "--mixed", remote_commit])
        _git(repo_root, ["add", "-A", "--"] + owned_paths)
        if _has_cached_changes(repo_root):
            _commit_snapshot(repo_root, commit_message)

        pending = _unpublished_commits(repo_root, remote_commit)
        _validate_unpublished_commits(
            repo_root,
            pending,
            commit_message,
            owned_paths,
        )

    if len(pending) > 1:
        raise UnsafeRepositoryState(
            f"snapshot compaction left {len(pending)} unpublished commits; refusing to push"
        )

    local_commit = _git_output(repo_root, ["rev-parse", "HEAD"])
    if not pending:
        report("No snapshot changes need to be pushed.")
        return SnapshotSyncResult(
            remote_commit=remote_commit,
            local_commit=local_commit,
            changed=False,
            pushed=False,
            collapsed_commits=collapsed_commits,
        )

    report(f"Pushing one automatic snapshot {local_commit[:12]} to {remote}/{branch}.")
    _git(repo_root, ["push", "--porcelain", remote, f"HEAD:refs/heads/{branch}"])
    return SnapshotSyncResult(
        remote_commit=remote_commit,
        local_commit=local_commit,
        changed=True,
        pushed=True,
        collapsed_commits=collapsed_commits,
    )
