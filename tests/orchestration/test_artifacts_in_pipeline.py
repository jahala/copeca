"""Test that --artifacts flag produces .copeca zip from CLI, not orchestrator."""

import subprocess
import zipfile
from pathlib import Path

import pytest

from copeca.config.models import (
    Category,
    ComprehensionGroundTruth,
    Difficulty,
    Language,
    Repo,
    Task,
    TaskType,
)
from copeca.orchestration.run import run_single
from copeca.repos.manager import GitWorktreeManager
from copeca.results.artifact import build_artifact
from copeca.runners.parsers.base import RunResult
from copeca.runners.subprocess import SubprocessRunner


class EchoParser:
    """Parser that returns a RunResult with raw stdout as result_text."""

    def parse(self, stdout, supported_events=None):
        return RunResult(
            result_text=stdout.strip(),
            total_cost_usd=0.05,
            duration_ms=200,
        )


@pytest.fixture
def test_repo(tmp_path: Path) -> Path:
    """Create a local git repo for orchestration tests."""
    repo_dir = tmp_path / "test-repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@copeca.dev"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Copeca Test"], cwd=repo_dir, check=True)
    (repo_dir / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, check=True)
    return repo_dir


class TestArtifactsInPipeline:
    def test_artifact_created_by_caller_not_orchestrator(self, tmp_path, test_repo):
        """Architecture: orchestrator returns record; CLI creates artifact.

        Per architecture.md §2: orchestration imports ports only.
        build_artifact is in the results adapter layer; the CLI
        (boundary layer) calls it after receiving the record.
        """
        task = Task(
            name="artifact_test",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            category=Category.locate,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="answer: test",
            ground_truth=ComprehensionGroundTruth(required_strings=["test"]),
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
        )
        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        # 1. Orchestrator returns a record (no I/O)
        record = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
        )
        assert record["task"] == "artifact_test"

        # 2. CLI caller creates artifact from the record (I/O at boundary)
        worktree = repo_mgr.create_worktree("test-repo", uri=str(test_repo))
        try:
            output_dir = tmp_path / "artifacts"
            output_dir.mkdir()
            artifact_path = build_artifact(record, worktree, output_dir)

            assert artifact_path.exists()
            with zipfile.ZipFile(artifact_path, "r") as zf:
                names = zf.namelist()
                assert "result.json" in names
                assert "manifest.json" in names
        finally:
            repo_mgr.reset(worktree)

    def test_no_artifacts_flag_produces_no_zip(self, tmp_path, test_repo):
        """Orchestrator does not produce artifacts; caller decides."""
        task = Task(
            name="no_artifact_test",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            category=Category.locate,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="answer: test",
            ground_truth=ComprehensionGroundTruth(required_strings=["test"]),
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
        )
        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        record = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
        )

        assert record["task"] == "no_artifact_test"
        # Orchestrator never creates artifacts — that's the CLI's job
        assert "artifact_path" not in record


class _RecordingRepoMgr:
    """Stub repo manager that records create_worktree/reset calls.

    Returns one prepared (real git) worktree for every request so the helper's
    orchestration — grouping by repo, one create per repo, reset-unless-kept —
    can be asserted precisely. build_artifact's own packaging is covered by
    tests/results/test_artifact.py; here we only drive the CLI helper.
    """

    def __init__(self, worktree: Path) -> None:
        self.worktree = worktree
        self.created: list[tuple] = []
        self.resets = 0

    def create_worktree(self, repo, commit=None, uri=None):
        self.created.append((repo, commit, uri))
        return self.worktree

    def reset(self, worktree):
        self.resets += 1


class TestScenarioArtifacts:
    """SD-M: scenario (matrix) --artifacts must build one .copeca per record, not
    silently no-op. Correct AND incorrect runs are evidence (cost-per-correct
    depends on both), so every record gets an artifact; the worktree is re-created
    once per repo and reset unless the user keeps it.
    """

    def _records(self):
        return [
            {
                "task": "scn_task",
                "mode": "baseline",
                "model": "m",
                "correct": True,
                "repetition": 0,
            },
            {"task": "scn_task", "mode": "tilth", "model": "m", "correct": False, "repetition": 0},
        ]

    def _task(self):
        return Task(
            name="scn_task",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            category=Category.locate,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="answer: test",
            ground_truth=ComprehensionGroundTruth(required_strings=["test"]),
        )

    def _repos(self, test_repo):
        return {"test-repo": Repo(url=str(test_repo), commit="0" * 40, language=Language.python)}

    def test_builds_one_artifact_per_record_grouped_by_repo(self, tmp_path, test_repo):
        from copeca.cli import _build_artifacts_for_records

        mgr = _RecordingRepoMgr(test_repo)
        output_dir = tmp_path / "artifacts"
        output_dir.mkdir()

        paths = _build_artifacts_for_records(
            self._records(),
            {"scn_task": self._task()},
            self._repos(test_repo),
            mgr,
            output_dir,
            None,
            False,
        )

        # One artifact per record — incorrect runs are evidence too.
        assert len(paths) == 2
        zips = sorted(output_dir.glob("*.copeca.zip"))
        assert len(zips) == 2
        for z in zips:
            with zipfile.ZipFile(z) as zf:
                names = zf.namelist()
                assert "result.json" in names
                assert "manifest.json" in names
        # Grouped: a single worktree for the single repo, reset once.
        assert len(mgr.created) == 1
        assert mgr.resets == 1

    def test_keep_worktrees_skips_reset(self, tmp_path, test_repo):
        from copeca.cli import _build_artifacts_for_records

        mgr = _RecordingRepoMgr(test_repo)
        output_dir = tmp_path / "artifacts"
        output_dir.mkdir()

        _build_artifacts_for_records(
            self._records(),
            {"scn_task": self._task()},
            self._repos(test_repo),
            mgr,
            output_dir,
            None,
            True,  # keep_worktrees
        )

        assert mgr.resets == 0
