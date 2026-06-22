"""RUN-CLONE: test per-worker independent clone isolation, removal, and lockless concurrency.

Three discriminating tests (RED before implementation, GREEN after):

(a) ISOLATION — two clones of the same repo_key have independent object stores;
    a commit landed in clone A is invisible to clone B.
(b) REMOVAL — remove_worktree deletes the clone directory.
(c) LOCKLESS CONCURRENCY — 4 parallel workers cloning the same repo produce 4
    valid records with zero git/index.lock errors.
"""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from copeca.repos.manager import GitWorktreeManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


# Fixed author env so no local git config is needed.
_GIT_ENV_BASE = {
    "GIT_AUTHOR_NAME": "copeca-test",
    "GIT_AUTHOR_EMAIL": "test@copeca.dev",
    "GIT_COMMITTER_NAME": "copeca-test",
    "GIT_COMMITTER_EMAIL": "test@copeca.dev",
}


@pytest.fixture()
def local_bare(tmp_path: Path) -> Path:
    """Return a local bare repo built from a tiny working repo."""
    src = tmp_path / "src"
    src.mkdir()
    _git(["init", "-b", "main"], src)
    _git(["config", "user.email", "test@copeca.dev"], src)
    _git(["config", "user.name", "Copeca Test"], src)
    (src / "README.md").write_text("# RUN-CLONE test\n")
    _git(["add", "."], src)

    import os

    env = {**os.environ, **_GIT_ENV_BASE}
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=src,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    bare = tmp_path / "bare.git"
    subprocess.run(
        ["git", "clone", "--bare", str(src), str(bare)],
        capture_output=True,
        text=True,
        check=True,
    )
    return bare


@pytest.fixture()
def mgr(tmp_path: Path, local_bare: Path) -> GitWorktreeManager:
    """Return a GitWorktreeManager pre-seeded with our local bare repo."""
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    bare_dir = repos_dir / "_bare"
    bare_dir.mkdir()
    import shutil

    shutil.copytree(str(local_bare), str(bare_dir / "testrepo"))
    return GitWorktreeManager(repos_dir)


# ---------------------------------------------------------------------------
# (a) ISOLATION: commit in clone A must not appear in clone B
# ---------------------------------------------------------------------------


class TestCloneIsolation:
    """Each clone has an independent object store — cross-task git leak guard."""

    def test_commit_in_clone_a_invisible_to_clone_b(self, mgr: GitWorktreeManager) -> None:
        """A commit authored in clone A must NOT appear in clone B's --all log.

        This is the critical cross-task-leak guard for debug tasks: an agent
        running in clone B must not see mutation commits planted for another
        task in clone A.

        DISCRIMINATES: would FAIL if the two clones shared an object store
        (e.g. hardlinks or git-worktrees off a common bare).
        """
        import os

        clone_a = mgr.create_worktree("testrepo", worktree_id="task-a")
        clone_b = mgr.create_worktree("testrepo", worktree_id="task-b")

        # In clone A: write a file and commit it.
        (clone_a / "secret.txt").write_text("clone-A-only\n")
        env = {**os.environ, **_GIT_ENV_BASE}
        subprocess.run(["git", "add", "secret.txt"], cwd=clone_a, env=env, check=True)
        subprocess.run(
            ["git", "commit", "-m", "clone-A-commit"],
            cwd=clone_a,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        # Extract the SHA of the new commit.
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=clone_a,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        # Clone B must NOT contain that SHA in any reachable ref.
        b_log = subprocess.run(
            ["git", "log", "--all", "--format=%H"],
            cwd=clone_b,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert sha not in b_log, (
            f"Cross-task git leak: clone-A's commit {sha[:12]} is visible in clone B. "
            "Clones must have independent object stores."
        )

        mgr.remove_worktree(clone_a)
        mgr.remove_worktree(clone_b)


# ---------------------------------------------------------------------------
# (b) REMOVAL: remove_worktree deletes the clone directory
# ---------------------------------------------------------------------------


class TestCloneRemoval:
    """remove_worktree must delete the clone directory completely."""

    def test_remove_worktree_deletes_directory(self, mgr: GitWorktreeManager) -> None:
        """After remove_worktree the path no longer exists on disk.

        DISCRIMINATES: would FAIL if remove_worktree didn't delete the dir
        (old reset() model only cleaned working-tree state, never deleted).
        """
        clone = mgr.create_worktree("testrepo", worktree_id="removal-test")
        assert clone.exists(), "Clone must exist before removal"

        mgr.remove_worktree(clone)

        assert not clone.exists(), (
            f"remove_worktree must delete the clone directory; {clone} still exists"
        )


# ---------------------------------------------------------------------------
# (c) LOCKLESS CONCURRENCY: 4 parallel clones of same repo, zero collisions
# ---------------------------------------------------------------------------


class TestLocklessConcurrency:
    """Independent clones share no index.lock → safe at max_workers > 1."""

    def test_four_parallel_clones_complete_without_git_errors(
        self, mgr: GitWorktreeManager
    ) -> None:
        """4 concurrent workers cloning the same repo_key all succeed.

        Pinned failure mode (P3): under the old git-worktree model, concurrent
        workers racing on a shared bare repo collide on index.lock, causing
        CalledProcessError with "Another git process seems to be running".
        With independent clones there is no shared index → lockless.

        DISCRIMINATES: run with the old shared-worktree manager and this test
        fails (or flakes) due to index.lock contention.
        """
        n_workers = 4
        results: dict[int, Path | Exception] = {}

        def worker(idx: int) -> None:
            try:
                path = mgr.create_worktree("testrepo", worktree_id=f"concurrent-{idx}")
                results[idx] = path
            except Exception as exc:  # noqa: BLE001
                results[idx] = exc

        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = [pool.submit(worker, i) for i in range(n_workers)]
            for f in as_completed(futures):
                f.result()  # propagate thread exceptions

        # No worker must have raised.
        errors = {k: v for k, v in results.items() if isinstance(v, Exception)}
        assert not errors, (
            f"Concurrent clone workers raised exceptions (likely index.lock): {errors}"
        )

        # All n paths must exist and be distinct.
        paths = [v for v in results.values() if isinstance(v, Path)]
        assert len(paths) == n_workers
        assert len(set(paths)) == n_workers, f"Path collision detected: {paths}"
        for p in paths:
            assert p.exists(), f"Clone path does not exist: {p}"
            assert (p / "README.md").exists(), f"Clone missing expected file: {p}"
            # No index.lock must be present (a leftover lock = aborted git op).
            assert not (p / ".git" / "index.lock").exists(), (
                f"Stale index.lock found in {p} — git operation was interrupted"
            )

        # Cleanup.
        for p in paths:
            mgr.remove_worktree(p)
