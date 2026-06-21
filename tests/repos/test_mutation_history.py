"""Test committed mutation_sequence history building.

Verifies that build_mutation_history:
- creates the expected number of commits in the worktree's git log,
- leaves the worktree in the state of the last step's mutations,
- and that reset() restores cleanly back to the original state.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from copeca.config.models import Mutation, MutationStep
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


def _commit_count_since(worktree: Path, base_sha: str) -> int:
    """Count commits reachable from HEAD that are not reachable from base_sha."""
    result = _git(["rev-list", f"{base_sha}..HEAD", "--count"], worktree)
    return int(result.stdout.strip())


def _head_sha(worktree: Path) -> str:
    return _git(["rev-parse", "HEAD"], worktree).stdout.strip()


# ---------------------------------------------------------------------------
# Fixture: a minimal real git repo in tmp_path
# ---------------------------------------------------------------------------


@pytest.fixture()
def bare_repo(tmp_path: Path) -> Path:
    """Return a bare git repo containing one commit with two files."""
    src = tmp_path / "src"
    src.mkdir()

    _git(["init", "-b", "main"], src)
    _git(["config", "user.email", "test@test.com"], src)
    _git(["config", "user.name", "Test"], src)

    (src / "main.rs").write_text('fn main() { println!("hello"); }\n')
    (src / "lib.rs").write_text("pub fn add(a: i64, b: i64) -> i64 { a + b }\n")
    _git(["add", "."], src)
    _git(["commit", "-m", "initial"], src)

    bare = tmp_path / "bare.git"
    subprocess.run(
        ["git", "clone", "--bare", str(src), str(bare)],
        capture_output=True,
        text=True,
        check=True,
    )
    return bare


@pytest.fixture()
def mgr(tmp_path: Path, bare_repo: Path) -> GitWorktreeManager:
    """Return a GitWorktreeManager whose bare dir already contains our test repo."""
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    bare_dir = repos_dir / "_bare"
    bare_dir.mkdir()
    # Hard-link the bare repo into the expected location
    import shutil

    shutil.copytree(str(bare_repo), str(bare_dir / "testrepo"))
    return GitWorktreeManager(repos_dir)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBuildMutationHistory:
    def test_creates_expected_commit_count(self, mgr: GitWorktreeManager, tmp_path: Path) -> None:
        """Two-step sequence builds exactly 2 new commits on top of the base."""
        worktree = mgr.create_worktree("testrepo", worktree_id="wt-count")
        base_sha = _head_sha(worktree)

        steps = [
            MutationStep(
                message="step 1: off-by-one in add",
                mutations=[
                    Mutation(
                        file="lib.rs",
                        action="replace",
                        find="a + b",
                        replace="a + b + 1",
                    )
                ],
            ),
            MutationStep(
                message="step 2: rename main",
                mutations=[
                    Mutation(
                        file="main.rs",
                        action="replace",
                        find="hello",
                        replace="world",
                    )
                ],
            ),
        ]

        mgr.build_mutation_history(worktree, steps)

        new_commits = _commit_count_since(worktree, base_sha)
        assert new_commits == 2, f"Expected 2 new commits, got {new_commits}"

    def test_worktree_state_reflects_last_step(
        self, mgr: GitWorktreeManager, tmp_path: Path
    ) -> None:
        """After build_mutation_history the working tree matches the last step's mutations."""
        worktree = mgr.create_worktree("testrepo", worktree_id="wt-state")

        steps = [
            MutationStep(
                message="introduce off-by-one",
                mutations=[
                    Mutation(
                        file="lib.rs",
                        action="replace",
                        find="a + b",
                        replace="a + b + 1",
                    )
                ],
            ),
        ]

        mgr.build_mutation_history(worktree, steps)

        content = (worktree / "lib.rs").read_text()
        assert "a + b + 1" in content, "Last step mutation not reflected in worktree"
        # And HEAD commit message matches
        log = _git(["log", "-1", "--pretty=%s"], worktree).stdout.strip()
        assert log == "introduce off-by-one"

    def test_reset_restores_cleanly(self, mgr: GitWorktreeManager, tmp_path: Path) -> None:
        """reset() after build_mutation_history brings the worktree back to the last
        committed state.

        Note: reset() runs git reset --hard HEAD + git clean -fd, which resets to the
        tip of the mutation_sequence (the last committed step). The worktree's pinned
        SHA moved forward due to the new commits, so reset lands at the last step —
        not the original base. This is by design: reset() is for discarding *agent*
        edits, not rolling back fixture history.
        """
        worktree = mgr.create_worktree("testrepo", worktree_id="wt-reset")

        steps = [
            MutationStep(
                message="introduce regression",
                mutations=[
                    Mutation(
                        file="lib.rs",
                        action="replace",
                        find="a + b",
                        replace="a + b + 1",
                    )
                ],
            ),
        ]

        mgr.build_mutation_history(worktree, steps)

        # Simulate an agent making an additional uncommitted edit
        (worktree / "lib.rs").write_text("// agent edit\n")

        # reset() should discard the uncommitted agent edit
        mgr.reset(worktree)

        content = (worktree / "lib.rs").read_text()
        assert "agent edit" not in content, "reset() did not discard agent edits"
        # The regression commit is still in history (reset doesn't undo commits)
        log = _git(["log", "--oneline"], worktree).stdout
        assert "introduce regression" in log

    def test_three_step_sequence_builds_correct_history(
        self, mgr: GitWorktreeManager, tmp_path: Path
    ) -> None:
        """Three-step sequence (harmless, bug, harmless) builds 3 commits."""
        worktree = mgr.create_worktree("testrepo", worktree_id="wt-three")
        base_sha = _head_sha(worktree)

        steps = [
            MutationStep(
                message="docs: add module docstring",
                mutations=[
                    Mutation(
                        file="lib.rs",
                        action="insert_after",
                        find="pub fn add",
                        content="    // computes a + b",
                    )
                ],
            ),
            MutationStep(
                message="refactor: simplify condition (bug)",
                mutations=[
                    Mutation(
                        file="lib.rs",
                        action="replace",
                        find="a + b",
                        replace="a + b + 1",
                    )
                ],
            ),
            MutationStep(
                message="refactor: shorten variable name",
                mutations=[
                    Mutation(
                        file="main.rs",
                        action="replace",
                        find="hello",
                        replace="hi",
                    )
                ],
            ),
        ]

        mgr.build_mutation_history(worktree, steps)

        new_commits = _commit_count_since(worktree, base_sha)
        assert new_commits == 3, f"Expected 3 new commits, got {new_commits}"

        # The middle-commit message must be in the log
        log = _git(["log", "--oneline"], worktree).stdout
        assert "refactor: simplify condition (bug)" in log
