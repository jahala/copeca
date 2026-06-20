"""Test that --artifacts flag produces .copeca zip from CLI, not orchestrator."""

import subprocess
import zipfile
from pathlib import Path

import pytest

from copeca.config.models import (
    ComprehensionGroundTruth,
    Difficulty,
    Language,
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
    subprocess.run(
        ["git", "config", "user.email", "test@copeca.dev"], cwd=repo_dir, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Copeca Test"], cwd=repo_dir, check=True
    )
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
