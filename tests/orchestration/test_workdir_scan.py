"""Pre-run workdir ambient-file scan (Lock 2a, architecture §13.3).

Verifies that scan_worktree_for_ambient_files detects instruction files that
would contaminate the agent, and that run_single's preflight raises
CONTAMINATED_WORKDIR when the runner's isolation.ambient_files list matches.
"""

import subprocess
from pathlib import Path

import pytest

from copeca.config.models import (
    Category,
    ComprehensionGroundTruth,
    Difficulty,
    IsolationSpec,
    Language,
    Task,
    TaskType,
)
from copeca.orchestration.run import run_single
from copeca.orchestration.validation import scan_worktree_for_ambient_files
from copeca.runners.parsers.base import RunResult
from copeca.runners.subprocess import SubprocessRunner

# ── Pure function tests ────────────────────────────────────────────────────────


class TestScanWorktreeForAmbientFiles:
    def test_detects_files_at_root_and_nested(self, tmp_path: Path) -> None:
        """CLAUDE.md at root + nested sub/AGENTS.md → both relative paths returned."""
        (tmp_path / "CLAUDE.md").write_text("# instructions\n")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "AGENTS.md").write_text("# agents\n")

        findings = scan_worktree_for_ambient_files(tmp_path, ["CLAUDE.md", "AGENTS.md"])

        assert set(findings) == {"CLAUDE.md", "sub/AGENTS.md"}

    def test_clean_worktree_returns_empty(self, tmp_path: Path) -> None:
        """A worktree with no matching files returns []."""
        (tmp_path / "README.md").write_text("# readme\n")
        (tmp_path / "main.py").write_text("# code\n")

        findings = scan_worktree_for_ambient_files(
            tmp_path, ["CLAUDE.md", "AGENTS.md", "GEMINI.md"]
        )

        assert findings == []

    def test_empty_ambient_files_list_returns_empty(self, tmp_path: Path) -> None:
        """ambient_files=[] → [] regardless of what's in the tree."""
        (tmp_path / "CLAUDE.md").write_text("# instructions\n")

        findings = scan_worktree_for_ambient_files(tmp_path, [])

        assert findings == []

    def test_only_matching_basenames_are_returned(self, tmp_path: Path) -> None:
        """Non-listed files in the tree are ignored."""
        (tmp_path / "CLAUDE.md").write_text("# instructions\n")
        (tmp_path / "AGENTS.md").write_text("# agents\n")
        (tmp_path / "notes.md").write_text("# notes\n")

        findings = scan_worktree_for_ambient_files(tmp_path, ["CLAUDE.md"])

        assert findings == ["CLAUDE.md"]
        assert "AGENTS.md" not in findings
        assert "notes.md" not in findings

    def test_deeply_nested_file_is_found(self, tmp_path: Path) -> None:
        """A file buried several levels deep is still detected."""
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "GEMINI.md").write_text("# gemini\n")

        findings = scan_worktree_for_ambient_files(tmp_path, ["GEMINI.md"])

        assert findings == ["a/b/c/GEMINI.md"]


# ── Integration-light: run_single preflight raises ─────────────────────────────


class EchoParser:
    """Minimal parser returning stdout as result_text — enough for run_single."""

    def parse(self, stdout: str, supported_events: object = None) -> RunResult:
        return RunResult(result_text=stdout.strip(), total_cost_usd=0.0, duration_ms=0)


@pytest.fixture()
def test_repo(tmp_path: Path) -> Path:
    """Tiny local git repo with a AGENTS.md committed to it."""
    repo_dir = tmp_path / "contaminated-repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@copeca.dev"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Copeca Test"], cwd=repo_dir, check=True)
    (repo_dir / "README.md").write_text("# repo\n")
    (repo_dir / "AGENTS.md").write_text("# agent instructions\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, check=True)
    return repo_dir


class TestRunSingleContaminatedWorkdir:
    def test_contaminated_worktree_raises_before_agent(
        self, tmp_path: Path, test_repo: Path
    ) -> None:
        """run_single raises CONTAMINATED_WORKDIR when isolation.ambient_files matches."""
        isolation = IsolationSpec(ambient_files=["AGENTS.md"])
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
            isolation=isolation,
        )
        task = Task(
            name="contaminated_task",
            source="test",
            repo="contaminated-repo",
            type=TaskType.comprehension,
            category=Category.locate,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="find something",
            ground_truth=ComprehensionGroundTruth(required_strings=[]),
        )
        from copeca.repos.manager import GitWorktreeManager

        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        # Spy on create_worktree to capture the clone path so we can assert the
        # finally tore it down — the scan runs INSIDE run_single's try, so a
        # CONTAMINATED_WORKDIR refusal must not leak the clone.
        created: dict[str, object] = {}
        _real_create = repo_mgr.create_worktree

        def _spy_create(*args: object, **kwargs: object) -> object:
            path = _real_create(*args, **kwargs)  # type: ignore[arg-type]
            created["path"] = path
            return path

        repo_mgr.create_worktree = _spy_create  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="CONTAMINATED_WORKDIR"):
            run_single(
                task=task,
                mode_name="baseline",
                model="test-model",
                runner=runner,
                repo_mgr=repo_mgr,
                repo_uri=str(test_repo),
                repo_commit=None,
            )

        # No leak: the contaminated clone must be removed by the finally.
        assert created.get("path"), "create_worktree should have been called"
        assert not Path(str(created["path"])).exists(), (
            "contaminated clone must be torn down, not leaked"
        )

    def test_empty_ambient_files_no_raise(self, tmp_path: Path, test_repo: Path) -> None:
        """When isolation.ambient_files=[], the scan is skipped — no raise."""
        isolation = IsolationSpec(ambient_files=[])
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
            isolation=isolation,
        )
        task = Task(
            name="clean_task",
            source="test",
            repo="contaminated-repo",
            type=TaskType.comprehension,
            category=Category.locate,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="answer: README",
            ground_truth=ComprehensionGroundTruth(required_strings=["README"]),
        )
        from copeca.repos.manager import GitWorktreeManager

        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        # Should NOT raise even though AGENTS.md is present (scan is skipped).
        result = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
        )
        assert result["task"] == "clean_task"
