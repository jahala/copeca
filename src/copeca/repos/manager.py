"""Git clone manager — adapter for git operations on benchmark repos.

Creates bare clones (cached, one per repo) and per-worker independent clones
for isolated agent runs.  Follows S.U.P.E.R.: side effects at the edge,
pure config flows in.

Clone lifecycle
---------------
1. ``create_worktree`` — ensures the bare exists (locked on first use), then
   ``git clone --no-hardlinks <bare> <clone_dir>`` to produce a fully
   independent clone with its own object store, index, HEAD and refs.
   Optionally ``git checkout --detach <commit>`` if a commit is pinned.
2. The run executes in the clone directory.
3. ``remove_worktree`` — ``shutil.rmtree`` the clone directory; nothing is
   shared, so no git-level bookkeeping is needed.

Concurrency
-----------
Independent clones share no index.lock, so per-item clone + remove run
locklessly.  The ONLY serialised section is the "if bare missing: clone"
critical section; a ``threading.Lock`` guards just that check-and-create.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from copeca.config.models import MutationStep

logger = logging.getLogger(__name__)


class GitWorktreeManager:
    """Manage git repos via bare clones and per-worker independent clones.

    Each repo is cloned once as a bare repo (the bare cache).  For each
    work-item, ``create_worktree`` produces an **independent clone** (not a
    git worktree) so every task gets its own object store, index, and HEAD —
    total cross-task isolation and lockless concurrency.

    The domain term "worktree" is kept for the working directory a run
    executes in; the implementation detail (independent clone vs git worktree)
    is internal.

    Args:
        repos_dir: Directory for bare clones and the clone pool.
    """

    def __init__(self, repos_dir: Path) -> None:
        # Resolve to an absolute path so every derived path — the bare clone,
        # the clone dir, and the per-arm mcp.json / config-dir written under
        # the clone — is absolute.  The agent runs with cwd=clone, so a
        # relative --mcp-config or CLAUDE_CONFIG_DIR would resolve against the
        # wrong directory and silently fail (shakedown SD-A: tilth arm, 0 turns).
        self._repos_dir = Path(repos_dir).resolve()
        self._repos_dir.mkdir(parents=True, exist_ok=True)
        self._bare_dir = self._repos_dir / "_bare"
        self._worktree_pool = self._repos_dir / "_worktrees"
        # Serialises bare-clone creation ONLY.  Everything else (per-item clone
        # creation, removal, mutations) runs locklessly because each clone has
        # its own object store.
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public interface (called by orchestration.run)
    # ------------------------------------------------------------------

    def verify_toolchain(self, repo_key: str) -> None:
        """Check that git is available on PATH.

        Args:
            repo_key: The repo identifier (unused in verification, but
                part of the interface contract).

        Raises:
            RuntimeError: If git is not found on PATH.
        """
        if shutil.which("git") is None:
            raise RuntimeError("git is not available on PATH — required for repo management")

    def create_worktree(
        self,
        repo_key: str,
        commit: str | None = None,
        uri: str | None = None,
        worktree_id: str | None = None,
    ) -> Path:
        """Create an independent clone for a single work-item.

        On first use for a given repo_key, clones the repo as a bare clone
        (the bare cache).  Then ``git clone --no-hardlinks <bare> <clone_dir>``
        produces a fully independent clone with its own object store.  If
        ``commit`` is given, ``git checkout --detach <commit>`` pins the clone.

        Each call produces a path scoped to *worktree_id* so concurrent
        workers targeting the same repo never collide.  The lock is held
        ONLY around the bare-clone creation check-and-create; the per-item
        clone runs locklessly.

        Args:
            repo_key: Unique key for this repo.
            commit: Git ref to check out (None means HEAD).
            uri: URI to clone from (only used on first invocation for
                this repo_key — subsequent calls ignore it).
            worktree_id: Discriminator appended to the clone directory
                name.  When None a UUID is generated so the path is always
                unique per call (safe for callers that don't supply one).

        Returns:
            Path to the independent clone directory.

        Raises:
            RuntimeError: If the bare clone or clone creation fails.
        """
        import uuid as _uuid

        if worktree_id is None:
            worktree_id = _uuid.uuid4().hex

        # --- Critical section: bare-clone creation only ---
        with self._lock:
            self._bare_dir.mkdir(parents=True, exist_ok=True)
            bare_path = self._bare_dir / repo_key

            if not (bare_path / "HEAD").exists():
                if uri is None:
                    raise RuntimeError(f"No bare clone for {repo_key!r} and no uri provided")
                self._clone_bare(uri, bare_path)

        # --- Lockless: per-item independent clone ---
        self._worktree_pool.mkdir(parents=True, exist_ok=True)
        clone_path = self._worktree_pool / f"{repo_key}-{worktree_id}"

        # Remove any leftover clone at this exact path (stale from a prior run).
        if clone_path.exists():
            _rmtree_workaround(clone_path)

        self._clone_local(bare_path, clone_path)

        if commit is not None:
            self._checkout_detach(clone_path, commit)

        return clone_path

    def remove_worktree(self, clone_path: Path) -> None:
        """Delete an independent clone directory, reclaiming disk.

        This is the teardown complement to ``create_worktree``.  Because each
        clone has its own object store there is no git-level bookkeeping to
        update — a plain directory removal is sufficient and correct.

        Args:
            clone_path: Path returned by ``create_worktree``.
        """
        logger.info("Removing clone: %s", clone_path)
        _rmtree_workaround(clone_path)

    def setup(self, worktree: Path, setup_command: list[str] | None = None) -> None:
        """Run repo setup commands inside the clone.

        Args:
            worktree: Path to the clone directory.
            setup_command: Shell command to run (list of argv).
                None means no-op.

        Raises:
            RuntimeError: If the setup command fails.
        """
        if not setup_command:
            return

        logger.info("Running setup: %s", " ".join(setup_command))
        try:
            subprocess.run(
                setup_command,
                cwd=worktree,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"Setup command failed: {exc.stderr.strip()}") from exc

    def reset(self, worktree: Path) -> None:
        """Reset the clone to a clean state (git reset --hard + git clean -fd).

        Retained for callers that explicitly need working-tree cleanup without
        teardown.  ``run_single`` calls ``remove_worktree`` instead, which
        fully deletes the clone.

        Note: ``-fd`` NOT ``-fdx`` — this preserves ignored directories like
        ``node_modules/``, ``target/``, and ``vendor/``.

        Args:
            worktree: Path to the clone directory.

        Raises:
            RuntimeError: If either git command fails.
        """
        try:
            subprocess.run(
                ["git", "reset", "--hard", "HEAD"],
                cwd=worktree,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"git reset --hard failed: {exc.stderr.strip()}") from exc

        try:
            subprocess.run(
                ["git", "clean", "-fd"],
                cwd=worktree,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"git clean -fd failed: {exc.stderr.strip()}") from exc

    def build_mutation_history(
        self,
        worktree: Path,
        steps: list[MutationStep],
    ) -> None:
        """Apply each step's mutations and commit them into the clone.

        Builds real git history so debug-task agents can run git log / git diff
        to locate and diagnose the committed regression.  All commits use a
        fixed author identity so no local git config is required.

        This operates on the independent clone directory; git add/commit work
        identically in an independent clone as in any working repo.

        Args:
            worktree: Path to the clone directory (must already exist).
            steps: Ordered list of MutationStep; each is applied in sequence,
                   then committed with step.message.

        Raises:
            RuntimeError: If any mutation fails or git commit fails.
        """
        from copeca.tasks.mutations import apply_mutations

        _git_env = {
            "GIT_AUTHOR_NAME": "copeca-fixture",
            "GIT_AUTHOR_EMAIL": "fixture@copeca.dev",
            "GIT_COMMITTER_NAME": "copeca-fixture",
            "GIT_COMMITTER_EMAIL": "fixture@copeca.dev",
        }
        env = {**os.environ, **_git_env}

        for step in steps:
            apply_mutations(step.mutations, base_path=worktree)
            try:
                subprocess.run(
                    ["git", "add", "-A"],
                    cwd=worktree,
                    capture_output=True,
                    text=True,
                    check=True,
                    env=env,
                )
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(
                    f"git add -A failed during mutation_sequence: {exc.stderr.strip()}"
                ) from exc
            try:
                subprocess.run(
                    ["git", "commit", "-m", step.message],
                    cwd=worktree,
                    capture_output=True,
                    text=True,
                    check=True,
                    env=env,
                )
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(
                    f"git commit failed for step {step.message!r}: {exc.stderr.strip()}"
                ) from exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clone_bare(uri: str, path: Path) -> None:
        """Clone uri as a bare repo into path."""
        logger.info("Bare clone %s -> %s", uri, path)
        try:
            subprocess.run(
                ["git", "clone", "--bare", uri, str(path)],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"Bare clone of {uri!r} failed: {exc.stderr.strip()}") from exc

    @staticmethod
    def _clone_local(bare_path: Path, clone_path: Path) -> None:
        """Clone the bare cache into an independent working clone.

        ``--no-hardlinks`` ensures the object store is fully independent
        (copied, not hard-linked), so mutations in one clone's object store
        are invisible to any other clone.
        """
        logger.info("Local clone %s -> %s", bare_path, clone_path)
        try:
            subprocess.run(
                ["git", "clone", "--no-hardlinks", str(bare_path), str(clone_path)],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"Local clone of {bare_path!r} failed: {exc.stderr.strip()}"
            ) from exc

    @staticmethod
    def _checkout_detach(clone_path: Path, commit: str) -> None:
        """Detach HEAD at the given commit/ref inside a clone."""
        logger.info("Checkout --detach %s in %s", commit, clone_path)
        try:
            subprocess.run(
                ["git", "-C", str(clone_path), "checkout", "--detach", commit],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"git checkout --detach {commit!r} failed: {exc.stderr.strip()}"
            ) from exc


def _rmtree_workaround(path: Path) -> None:
    """Remove a directory tree, handling git's read-only files."""

    def _on_error(
        func: object,
        p: str,
        exc_info: object,  # noqa: ARG001
    ) -> None:
        os.chmod(p, 0o700)
        if path.exists():
            os.unlink(p)

    if path.exists():
        shutil.rmtree(path, onerror=_on_error)
