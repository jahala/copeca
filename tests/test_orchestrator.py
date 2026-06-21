"""Full pipeline integration test — scenario matrix end-to-end."""

import subprocess
from pathlib import Path

import pytest

from copeca.config.models import (
    ComprehensionGroundTruth,
    Difficulty,
    Language,
    Scenario,
    Task,
    TaskType,
)
from copeca.orchestration.run import run_matrix, run_single
from copeca.runners.parsers.base import RunResult
from copeca.runners.subprocess import SubprocessRunner

# ── EchoParser — deterministic parser returning stdout as result_text ──────────

class EchoParser:
    """Parser that returns a RunResult with raw stdout as result_text."""

    def parse(self, stdout, supported_events=None):
        return RunResult(
            result_text=stdout.strip(),
            total_cost_usd=0.05,
            duration_ms=200,
        )


# ── StubRepoManager — no real git clone needed ─────────────────────────────────

class StubRepoManager:
    """Stub repo manager that fakes worktree operations.

    Each call creates a unique path under a temp directory so runs do not collide.
    """

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self._counter = 0
        self.worktrees_created: list[Path] = []
        self.setups_called = 0
        self.resets_called = 0

    def verify_toolchain(self, repo_key: str) -> None:
        pass

    def create_worktree(self, repo_key: str, commit=None, uri=None, worktree_id=None) -> Path:
        self._counter += 1
        wt = self.base_dir / f"worktree-{self._counter}"
        wt.mkdir(parents=True, exist_ok=True)
        self.worktrees_created.append(wt)
        return wt

    def setup(self, worktree: Path) -> None:
        self.setups_called += 1

    def reset(self, worktree: Path) -> None:
        self.resets_called += 1


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_task(name: str, repo: str = "test-repo") -> Task:
    """Build a minimal comprehension task."""
    return Task(
        name=name,
        source="test",
        repo=repo,
        type=TaskType.comprehension,
        language=Language.python,
        difficulty=Difficulty.easy,
        version=1,
        prompt=f"answer: {name} Matcher find_at",
        ground_truth=ComprehensionGroundTruth(required_strings=["Matcher", "find_at"]),
    )


def _make_runner() -> SubprocessRunner:
    """Build an echo runner with EchoParser."""
    return SubprocessRunner(
        name="echo-test",
        cli="echo",
        default_args=[],
        arg_map={"prompt_separator": ""},
        parser=EchoParser(),
    )


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def test_repo(tmp_path: Path) -> Path:
    """Create a local git repo for pipeline integration tests."""
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


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestFullPipeline:
    """End-to-end integration tests for the complete copeca pipeline."""

    def test_scenario_matrix_end_to_end(self, tmp_path, test_repo):
        """2 tasks x 1 mode x 1 rep = 2 records, all correct, JSONL written."""
        tasks = {
            "test_1": _make_task("test_1"),
            "test_2": _make_task("test_2"),
        }

        scenario = Scenario.model_validate({
            "name": "integration_test",
            "tasks": ["test_1", "test_2"],
            "modes": ["baseline"],
            "models": ["test-model"],
            "repetitions": 1,
            "budget_usd": 2.0,
        })

        def _runner_factory(mode, model):
            return _make_runner()

        runner_factory = _runner_factory
        repo_mgr = StubRepoManager(tmp_path / "worktrees")

        results_path = tmp_path / "results.jsonl"
        records = run_matrix(
            scenario=scenario,
            tasks=list(tasks.values()),
            modes=scenario.modes,
            runner_factory=runner_factory,
            repo_mgr=repo_mgr,
            results_path=results_path,
            max_workers=1,
        )

        assert len(records) == 2
        task_names = sorted(r["task"] for r in records)
        assert task_names == ["test_1", "test_2"]
        for r in records:
            assert r["correct"] is True
            assert "task" in r
            assert "total_cost_usd" in r
            assert "mode" in r
            assert "model" in r
            assert "repetition" in r

        # Verify JSONL was NOT written by run_matrix — the orchestrator returns
        # records but the CLI caller persists them (arch §5: "The orchestrator
        # returns a record dict; the CLI caller persists it.")
        assert not results_path.exists()

    def test_single_run_pipeline_integration(self, tmp_path, test_repo):
        """run_single produces correct record with all required fields."""
        task = Task(
            name="integration_pipeline",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="answer: Matcher find_at RegexMatcher",
            ground_truth=ComprehensionGroundTruth(
                required_strings=["Matcher", "find_at"],
            ),
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
        )
        repo_mgr = StubRepoManager(tmp_path / "worktrees")

        result = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
        )

        assert result["correct"] is True
        assert result["task"] == "integration_pipeline"
        assert result["mode"] == "baseline"
        assert result["model"] == "test-model"
        assert result["total_cost_usd"] == 0.05
        assert result["duration_ms"] >= 0  # actual subprocess timing overwrites parser value

    def test_jsonl_record_has_all_required_fields(self, tmp_path, test_repo):
        """Verify all required JSONL record fields are present."""
        task = Task(
            name="fields_test",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="answer: Matcher",
            ground_truth=ComprehensionGroundTruth(required_strings=["Matcher"]),
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=EchoParser(),
        )
        repo_mgr = StubRepoManager(tmp_path / "worktrees")

        result = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
        )

        # All fields from the JSONL record contract (run_single lines 105-145)
        required_fields = [
            "task",
            "repo",
            "mode",
            "model",
            "runner",
            "repetition",
            "timestamp",
            "correct",
            "correctness_detail",
            "num_turns",
            "num_tool_calls",
            "total_cost_usd",
            "duration_ms",
            "context_tokens",
            "output_tokens",
            "input_tokens",
            "cache_creation_tokens",
            "cache_read_tokens",
            "result_text",
            "tool_sequence",
            "error",
            "adversarial_flags",
            "metadata",
        ]

        for field in required_fields:
            assert field in result, f"Missing required field: {field}"

        # Verify nested structures
        assert isinstance(result["correctness_detail"], dict)
        detail = result["correctness_detail"]
        assert "required_strings_passed" in detail
        assert "all_of_passed" in detail
        assert "forbidden_strings_passed" in detail
        assert "test_command_passed" in detail

        assert isinstance(result["adversarial_flags"], dict)
        flags = result["adversarial_flags"]
        assert "token_snowball" in flags
        assert "talkative_failure" in flags
        assert "tool_storm" in flags
        assert "budget_exhausted" in flags
        assert "timeout" in flags

        assert isinstance(result["metadata"], dict)
        assert "copeca_version" in result["metadata"]
        assert "task_version" in result["metadata"]


class TestKeepWorktrees:
    """--keep-worktrees must skip the worktree reset so per-arm state (mcp.json,
    config dir, the agent's repo edits) survives for debugging. Shakedown SD-C:
    debugging the tilth-arm failure required hand-recreating a worktree because
    run_single reset unconditionally.
    """

    def test_keep_worktree_skips_reset(self, tmp_path, test_repo):
        repo_mgr = StubRepoManager(tmp_path / "worktrees")
        run_single(
            task=_make_task("keep_test"),
            mode_name="baseline",
            model="test-model",
            runner=_make_runner(),
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
            keep_worktree=True,
        )
        assert repo_mgr.resets_called == 0

    def test_default_resets_worktree(self, tmp_path, test_repo):
        repo_mgr = StubRepoManager(tmp_path / "worktrees")
        run_single(
            task=_make_task("reset_test"),
            mode_name="baseline",
            model="test-model",
            runner=_make_runner(),
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
        )
        assert repo_mgr.resets_called == 1
