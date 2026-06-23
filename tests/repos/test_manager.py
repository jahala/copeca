"""Test GitWorktreeManager with real local git repos."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from copeca.repos.manager import GitWorktreeManager


@pytest.fixture
def test_repo(tmp_path: Path) -> Path:
    """Create a local git repo with known content, a tag, and a .gitignore."""
    repo_dir = tmp_path / "test-repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@copeca.dev"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Copeca Test"], cwd=repo_dir, check=True)
    (repo_dir / "README.md").write_text("# Test Repo\n")
    # Add .gitignore so we can test that clean -fd preserves ignored dirs
    (repo_dir / ".gitignore").write_text("node_modules/\ntarget/\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, check=True)
    subprocess.run(["git", "tag", "v1.0"], cwd=repo_dir, check=True)
    return repo_dir


class TestGitWorktreeManager:
    def test_bare_clone_created(self, tmp_path: Path, test_repo: Path) -> None:
        """First use clones a bare repo under _bare_dir."""
        mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")
        mgr.verify_toolchain("test-repo")
        worktree = mgr.create_worktree("test-repo", commit=None, uri=str(test_repo))

        bare_dir = mgr._bare_dir
        assert bare_dir.exists()
        assert (bare_dir / "test-repo" / "HEAD").exists()

        _rmtree_workaround(worktree)

    def test_create_worktree_checks_out_content(self, tmp_path: Path, test_repo: Path) -> None:
        """Worktree has README.md with expected content."""
        mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")
        worktree = mgr.create_worktree("test-repo", commit=None, uri=str(test_repo))

        readme = worktree / "README.md"
        assert readme.exists()
        assert readme.read_text() == "# Test Repo\n"

        _rmtree_workaround(worktree)

    def test_create_worktree_at_tag(self, tmp_path: Path, test_repo: Path) -> None:
        """commit='v1.0' checks out the tagged commit."""
        mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")
        worktree = mgr.create_worktree("test-repo", commit="v1.0", uri=str(test_repo))

        readme = worktree / "README.md"
        assert readme.exists()

        # Verify we're at the tag
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=True,
        )
        head_sha = result.stdout.strip()
        tag_result = subprocess.run(
            ["git", "rev-parse", "v1.0^{commit}"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=True,
        )
        tag_sha = tag_result.stdout.strip()
        assert head_sha == tag_sha

        _rmtree_workaround(worktree)

    def test_reset_removes_uncommitted_changes(self, tmp_path: Path, test_repo: Path) -> None:
        """Dirty the worktree, reset, verify clean."""
        mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")
        worktree = mgr.create_worktree("test-repo", commit=None, uri=str(test_repo))

        # Dirty tracked file
        readme = worktree / "README.md"
        readme.write_text("# Dirty\n")

        # Stage a change
        subprocess.run(["git", "add", "README.md"], cwd=worktree, check=True)

        mgr.reset(worktree)

        # After reset, the file should be back to original
        assert readme.read_text() == "# Test Repo\n"

        # Working tree should be clean
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == ""

        _rmtree_workaround(worktree)

    def test_reset_preserves_untracked_dirs(self, tmp_path: Path, test_repo: Path) -> None:
        """reset with clean -fd preserves node_modules/ and target/ dirs."""
        mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")
        worktree = mgr.create_worktree("test-repo", commit=None, uri=str(test_repo))

        # Create untracked directories that match .gitignore patterns
        node_modules = worktree / "node_modules"
        node_modules.mkdir()
        (node_modules / "pkg.json").write_text("{}")

        target_dir = worktree / "target"
        target_dir.mkdir()
        (target_dir / "build.o").write_text("obj")

        mgr.reset(worktree)

        # These directories should still exist (clean -fd, not -fdx)
        assert node_modules.exists()
        assert (node_modules / "pkg.json").exists()
        assert target_dir.exists()
        assert (target_dir / "build.o").exists()

        _rmtree_workaround(worktree)

    def test_setup_runs_command(self, tmp_path: Path, test_repo: Path) -> None:
        """setup with ['touch', 'setup-ran'] creates the file."""
        mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")
        worktree = mgr.create_worktree("test-repo", commit=None, uri=str(test_repo))

        mgr.setup(worktree, setup_command=["touch", "setup-ran"])

        marker = worktree / "setup-ran"
        assert marker.exists()

        _rmtree_workaround(worktree)

    def test_setup_no_command_is_noop(self, tmp_path: Path, test_repo: Path) -> None:
        """setup with no command is a no-op."""
        mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")
        worktree = mgr.create_worktree("test-repo", commit=None, uri=str(test_repo))

        # Should not raise
        mgr.setup(worktree)

        _rmtree_workaround(worktree)

    def test_verify_toolchain_raises_if_no_git(self, tmp_path: Path, test_repo: Path) -> None:
        """Mock PATH to exclude git, verify RuntimeError."""
        mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        # Create PATH that excludes git
        empty_bin = tmp_path / "empty-bin"
        empty_bin.mkdir()

        with (
            mock.patch.dict(os.environ, {"PATH": str(empty_bin)}, clear=True),
            pytest.raises(RuntimeError, match="git"),
        ):
            mgr.verify_toolchain("test-repo")


class TestWorktreeConcurrency:
    """Concurrent create_worktree calls for the same repo must yield distinct paths."""

    def test_concurrent_same_repo_distinct_paths(self, tmp_path: Path, test_repo: Path) -> None:
        """N threads calling create_worktree for the same repo get N distinct paths.

        Pins the TOCTOU bug: without per-item worktree IDs, all threads would
        compute the same path (``{repo_key}-worktree``) and collide.  With the
        fix every caller receives a unique path even under high concurrency.
        """
        import threading

        mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")
        n_threads = 4
        results: list[Path | Exception] = [Exception("not set")] * n_threads
        lock = threading.Lock()

        def worker(idx: int, worktree_id: str) -> None:
            try:
                wt = mgr.create_worktree(
                    "test-repo",
                    commit=None,
                    uri=str(test_repo),
                    worktree_id=worktree_id,
                )
                with lock:
                    results[idx] = wt
            except Exception as exc:  # noqa: BLE001
                with lock:
                    results[idx] = exc

        ids = [f"mode-a_model-x_rep{i}" for i in range(n_threads)]
        threads = [threading.Thread(target=worker, args=(i, ids[i])) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Every slot must hold a Path, not an exception.
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert not exceptions, f"Threads raised exceptions: {exceptions}"

        paths = [r for r in results if isinstance(r, Path)]
        assert len(paths) == n_threads

        # All paths must be distinct — no two workers share a worktree.
        assert len(set(paths)) == n_threads, f"Worktree path collision detected: {paths}"

        # Each path must actually exist on disk.
        for p in paths:
            assert p.exists(), f"Worktree path does not exist: {p}"

        # Cleanup
        for p in paths:
            _rmtree_workaround(p)

    def test_worktree_path_keyed_per_work_item(self, tmp_path: Path, test_repo: Path) -> None:
        """Clone path embeds the worktree_id discriminator, not just the repo key.

        Two calls with different IDs must produce different paths; the
        discriminator must appear in the path so the caller can predict it.
        With independent clones, the two calls are fully independent — no
        reset or serialisation is required between them.
        """
        mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        wt_a = mgr.create_worktree(
            "test-repo", commit=None, uri=str(test_repo), worktree_id="mode-a_rep0"
        )
        wt_b = mgr.create_worktree(
            "test-repo", commit=None, uri=str(test_repo), worktree_id="mode-b_rep0"
        )

        assert wt_a != wt_b, "Different worktree_ids must produce different paths"
        assert "mode-a_rep0" in str(wt_a), f"worktree_id discriminator must appear in path: {wt_a}"
        assert "mode-b_rep0" in str(wt_b), f"worktree_id discriminator must appear in path: {wt_b}"

        _rmtree_workaround(wt_a)
        _rmtree_workaround(wt_b)


def _rmtree_workaround(path: Path) -> None:
    """Remove a directory tree, handling git's read-only files."""
    import shutil

    def _on_error(func, p, exc_info):
        os.chmod(p, 0o700)
        func(p)

    if path.exists():
        shutil.rmtree(path, onerror=_on_error)


class TestWorktreePathsAreAbsolute:
    """A relative repos_dir must still yield absolute worktree paths.

    Regression (live shakedown SD-A): ``copeca run`` builds
    ``GitWorktreeManager(repos_dir=Path("repos"))`` — a RELATIVE path — so the
    worktree, and the per-arm mcp.json / config-dir paths derived from it, were
    relative. claude runs with ``cwd=worktree``, so a relative
    ``--mcp-config <path>`` resolved against the wrong directory and claude
    exited with "MCP config file not found" — the tilth arm silently produced
    nothing (0 turns, empty output, $0).
    """

    def test_relative_repos_dir_yields_absolute_worktree(
        self,
        tmp_path: Path,
        test_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # chdir into tmp so the relative "repos" dir is created under tmp,
        # never the real project tree.
        monkeypatch.chdir(tmp_path)

        mgr = GitWorktreeManager(repos_dir=Path("repos"))  # RELATIVE on purpose
        worktree = mgr.create_worktree(
            "test-repo", commit=None, uri=str(test_repo), worktree_id="abs-check"
        )

        assert worktree.is_absolute(), (
            "worktree path must be absolute even when repos_dir is relative "
            "(so a cwd=worktree --mcp-config path resolves); got: "
            f"{worktree}"
        )

        _rmtree_workaround(worktree)
