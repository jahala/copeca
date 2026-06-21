"""Git worktree manager — adapter for git operations on benchmark repos.

Creates bare clones and ephemeral worktrees for isolated agent runs.
Follows S.U.P.E.R.: side effects at the edge, pure config flows in.
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
    """Manage git repos via bare clones and ephemeral worktrees.

    Each repo is cloned once as a bare repo. Worktrees are created from
    that bare clone, used for a single run, then reset for reuse.

    Args:
        repos_dir: Directory for bare clones and worktree pool.
    """

    def __init__(self, repos_dir: Path) -> None:
        # Resolve to an absolute path so every derived path — the bare clone,
        # the worktree, and the per-arm mcp.json / config-dir written under the
        # worktree — is absolute. The agent runs with cwd=worktree, so a relative
        # --mcp-config or CLAUDE_CONFIG_DIR would resolve against the wrong
        # directory and silently fail (shakedown SD-A: tilth arm, 0 turns).
        self._repos_dir = Path(repos_dir).resolve()
        self._repos_dir.mkdir(parents=True, exist_ok=True)
        self._bare_dir = self._repos_dir / "_bare"
        self._worktree_pool = self._repos_dir / "_worktrees"
        # Serialises bare-clone creation and per-worktree prune→add so that
        # concurrent workers for the same repo never race on the same path.
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
        """Create an ephemeral worktree from a bare clone.

        On first use for a given repo_key, clones the repo as a bare
        clone.  Then adds a worktree at the requested commit (or HEAD).

        Each call produces a path scoped to *worktree_id* so concurrent
        workers targeting the same repo never collide.  The bare clone is
        shared across workers; the lock serialises bare-clone creation and
        the prune→add sequence so no two callers race on the same path.

        Args:
            repo_key: Unique key for this repo.
            commit: Git ref to check out (None means HEAD).
            uri: URI to clone from (only used on first invocation for
                this repo_key — subsequent calls ignore it).
            worktree_id: Discriminator appended to the worktree directory
                name.  When None a UUID is generated so the path is always
                unique per call (safe for callers that don't supply one).

        Returns:
            Path to the worktree directory.

        Raises:
            RuntimeError: If the bare clone or worktree creation fails.
        """
        import uuid as _uuid

        if worktree_id is None:
            worktree_id = _uuid.uuid4().hex

        with self._lock:
            self._bare_dir.mkdir(parents=True, exist_ok=True)
            bare_path = self._bare_dir / repo_key

            if not (bare_path / "HEAD").exists():
                if uri is None:
                    raise RuntimeError(f"No bare clone for {repo_key!r} and no uri provided")
                self._clone_bare(uri, bare_path)

            self._worktree_pool.mkdir(parents=True, exist_ok=True)
            worktree_path = self._worktree_pool / f"{repo_key}-{worktree_id}"

            # If a leftover worktree exists at this exact path, prune it first.
            if worktree_path.exists():
                self._prune_worktree(worktree_path, bare_path)

            self._add_worktree(bare_path, worktree_path, commit)

        return worktree_path

    def setup(self, worktree: Path, setup_command: list[str] | None = None) -> None:
        """Run repo setup commands inside the worktree.

        Args:
            worktree: Path to the worktree.
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
        """Reset the worktree to a clean state.

        Runs ``git reset --hard HEAD`` to discard staged and unstaged
        changes, followed by ``git clean -fd`` to remove untracked files
        and directories.  Note: ``-fd`` NOT ``-fdx`` — this preserves
        ignored directories like ``node_modules/``, ``target/``, and
        ``vendor/``.

        Args:
            worktree: Path to the worktree.

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
        """Apply each step's mutations and commit them into the worktree.

        Builds real git history so debug-task agents can run git log / git diff
        to locate and diagnose the committed regression.  All commits use a
        fixed author identity so no local git config is required.

        Args:
            worktree: Path to the worktree (must already exist).
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
    def _add_worktree(bare_path: Path, worktree_path: Path, commit: str | None) -> None:
        """Add a worktree from a bare clone at the given commit."""
        cmd = [
            "git",
            "-C",
            str(bare_path),
            "worktree",
            "add",
            "--detach",
            str(worktree_path.resolve()),
        ]
        if commit is not None:
            cmd.append(commit)

        logger.info("Adding worktree: %s", " ".join(cmd))
        try:
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"git worktree add failed: {exc.stderr.strip()}") from exc

    @staticmethod
    def _prune_worktree(worktree_path: Path, bare_path: Path) -> None:
        """Remove a stale worktree and prune its metadata from the bare repo."""
        # First try to remove the worktree via git
        try:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(bare_path),
                    "worktree",
                    "remove",
                    "--force",
                    str(worktree_path),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError:
            # If git worktree remove fails (corrupt state),
            # manually clean up and prune
            _rmtree_workaround(worktree_path)
            GitWorktreeManager._prune_bare(bare_path)

    @staticmethod
    def _prune_bare(bare_path: Path) -> None:
        """Prune stale worktree metadata from a bare repo."""
        import contextlib

        with contextlib.suppress(subprocess.CalledProcessError):
            subprocess.run(
                ["git", "-C", str(bare_path), "worktree", "prune"],
                capture_output=True,
                text=True,
                check=True,
            )


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
