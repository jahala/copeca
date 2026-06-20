"""Test cost computation wired into the single-run orchestrator pipeline."""

import subprocess
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
from copeca.runners.cost import compute_cost
from copeca.runners.parsers.base import RunResult, Turn
from copeca.runners.subprocess import SubprocessRunner


class TokenEchoParser:
    """Parser that returns a RunResult with specific token counts."""

    def __init__(self, turns: list[Turn] | None = None, vendor_cost: float = 0.05):
        self._turns = turns or [
            Turn(
                input_tokens=5000,
                output_tokens=200,
                cache_creation_tokens=0,
                cache_read_tokens=1000,
            )
        ]
        self._vendor_cost = vendor_cost

    def parse(self, stdout, supported_events=None):
        return RunResult(
            result_text=stdout.strip(),
            total_cost_usd=self._vendor_cost,
            duration_ms=200,
            turns=list(self._turns),
        )


SAMPLE_PRICING = {
    "input": 3.0,
    "cache_creation": 3.75,
    "cache_read": 0.30,
    "output": 15.0,
}


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


class TestCostInPipeline:
    def test_cost_computed_from_tokens_and_pricing(self, tmp_path, test_repo):
        """When pricing is provided, total_cost_usd is computed from tokens * rates."""
        parser = TokenEchoParser(
            turns=[
                Turn(
                    input_tokens=5000,
                    output_tokens=200,
                    cache_creation_tokens=0,
                    cache_read_tokens=1000,
                )
            ],
            vendor_cost=0.05,
        )

        task = Task(
            name="cost_test_1",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="cost test",
            ground_truth=ComprehensionGroundTruth(required_strings=["test"]),
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=parser,
        )
        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        result = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
            pricing=SAMPLE_PRICING,
        )

        # total_cost_usd should be computed from tokens * pricing, not the vendor's 0.05
        expected = compute_cost(
            tokens={
                "input_tokens": 5000,
                "output_tokens": 200,
                "cache_creation_tokens": 0,
                "cache_read_tokens": 1000,
            },
            pricing=SAMPLE_PRICING,
        )
        assert result["total_cost_usd"] == pytest.approx(expected)
        assert result["total_cost_usd"] != 0.05  # NOT the vendor cost

    def test_vendor_cost_usd_written(self, tmp_path, test_repo):
        """When pricing is provided, vendor_cost_usd records the parser's cost."""
        parser = TokenEchoParser(
            turns=[
                Turn(
                    input_tokens=1000,
                    output_tokens=100,
                    cache_creation_tokens=0,
                    cache_read_tokens=0,
                )
            ],
            vendor_cost=0.05,
        )

        task = Task(
            name="cost_test_2",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="vendor cost test",
            ground_truth=ComprehensionGroundTruth(required_strings=["test"]),
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=parser,
        )
        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        result = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
            pricing=SAMPLE_PRICING,
        )

        assert result["vendor_cost_usd"] == 0.05

    def test_pricing_none_falls_back_to_parser_cost(self, tmp_path, test_repo):
        """When pricing is None, total_cost_usd falls back to parser's cost."""
        parser = TokenEchoParser(
            turns=[
                Turn(
                    input_tokens=5000,
                    output_tokens=200,
                    cache_creation_tokens=0,
                    cache_read_tokens=1000,
                )
            ],
            vendor_cost=0.05,
        )

        task = Task(
            name="cost_test_3",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="fallback test",
            ground_truth=ComprehensionGroundTruth(required_strings=["test"]),
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=parser,
        )
        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        result = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
            pricing=None,
        )

        assert result["total_cost_usd"] == 0.05
        # vendor_cost_usd should not be present when pricing was None
        assert "vendor_cost_usd" not in result

    def test_computed_cost_matches_hand_calculation(self, tmp_path, test_repo):
        """Hand-calculate expected cost and assert match."""
        # 10000 input * $3/M = 0.03
        # 500 cache_creation * $3.75/M = 0.001875
        # 2000 cache_read * $0.30/M = 0.0006
        # 500 output * $15/M = 0.0075
        # Total ≈ 0.039975
        parser = TokenEchoParser(
            turns=[
                Turn(
                    input_tokens=10000,
                    output_tokens=500,
                    cache_creation_tokens=500,
                    cache_read_tokens=2000,
                )
            ],
            vendor_cost=0.10,
        )

        task = Task(
            name="cost_test_4",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="hand calc test",
            ground_truth=ComprehensionGroundTruth(required_strings=["test"]),
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=parser,
        )
        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        result = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
            pricing=SAMPLE_PRICING,
        )

        expected = (
            10000 * 3.0 + 500 * 3.75 + 2000 * 0.30 + 500 * 15.0
        ) / 1_000_000
        assert result["total_cost_usd"] == pytest.approx(expected)
        assert result["vendor_cost_usd"] == 0.10

    def test_zero_token_cost_is_zero(self, tmp_path, test_repo):
        """RunResult with all-zero tokens produces computed cost of 0.0."""
        parser = TokenEchoParser(
            turns=[
                Turn(
                    input_tokens=0,
                    output_tokens=0,
                    cache_creation_tokens=0,
                    cache_read_tokens=0,
                )
            ],
            vendor_cost=0.0,
        )

        task = Task(
            name="cost_test_5",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="zero tokens",
            ground_truth=ComprehensionGroundTruth(required_strings=["test"]),
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=parser,
        )
        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        result = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
            pricing=SAMPLE_PRICING,
        )

        assert result["total_cost_usd"] == 0.0
        assert result["vendor_cost_usd"] == 0.0


class TestCostDivergence:
    """Tests for the vendor cost divergence warning (>5%)."""

    def test_divergence_below_5_percent_no_warning(self, tmp_path, test_repo):
        """Cost within 5% of vendor → no divergence in metadata."""
        # computed: 5000*3.0 + 200*15.0 + 0*3.75 + 1000*0.30 = 15000+3000+0+300=18300 / 1e6 = 0.0183
        # Set vendor cost to 0.019, divergence = |0.0183 - 0.019| / 0.019 = 0.0368 (3.7%) → under 5%
        parser = TokenEchoParser(
            turns=[
                Turn(
                    input_tokens=5000,
                    output_tokens=200,
                    cache_creation_tokens=0,
                    cache_read_tokens=1000,
                )
            ],
            vendor_cost=0.019,
        )

        task = Task(
            name="divergence_below_5",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="divergence test",
            ground_truth=ComprehensionGroundTruth(required_strings=["test"]),
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=parser,
        )
        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        result = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
            pricing=SAMPLE_PRICING,
        )

        assert "vendor_cost_divergence" not in result["metadata"]
        assert "vendor_cost_divergence_warning" not in result["metadata"]

    def test_divergence_above_5_percent_warning(self, tmp_path, test_repo):
        """Cost >5% off from vendor → warning present, divergence recorded."""
        # computed: 5000*3.0 + 200*15.0 + 0*3.75 + 1000*0.30 = 0.0183
        # Set vendor cost to 0.03, divergence = |0.0183 - 0.03| / 0.03 = 0.39 (39%) → over 5%
        parser = TokenEchoParser(
            turns=[
                Turn(
                    input_tokens=5000,
                    output_tokens=200,
                    cache_creation_tokens=0,
                    cache_read_tokens=1000,
                )
            ],
            vendor_cost=0.03,
        )

        task = Task(
            name="divergence_above_5",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="divergence test",
            ground_truth=ComprehensionGroundTruth(required_strings=["test"]),
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=parser,
        )
        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        result = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
            pricing=SAMPLE_PRICING,
        )

        assert "vendor_cost_divergence" in result["metadata"]
        assert "vendor_cost_divergence_warning" in result["metadata"]
        assert result["metadata"]["vendor_cost_divergence"] == pytest.approx(
            abs(0.0183 - 0.03) / 0.03
        )
        assert "39.0%" in result["metadata"]["vendor_cost_divergence_warning"]

    def test_divergence_zero_vendor_cost_handled(self, tmp_path, test_repo):
        """vendor_cost_usd=0 → skip check (no division by zero)."""
        parser = TokenEchoParser(
            turns=[
                Turn(
                    input_tokens=1000,
                    output_tokens=100,
                    cache_creation_tokens=0,
                    cache_read_tokens=0,
                )
            ],
            vendor_cost=0.0,
        )

        task = Task(
            name="divergence_zero_vendor",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="zero vendor test",
            ground_truth=ComprehensionGroundTruth(required_strings=["test"]),
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=parser,
        )
        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        result = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
            pricing=SAMPLE_PRICING,
        )

        # Should not have divergence — vendor cost was 0, check is skipped
        assert "vendor_cost_divergence" not in result["metadata"]
        assert "vendor_cost_divergence_warning" not in result["metadata"]

    def test_divergence_no_pricing_no_divergence_check(self, tmp_path, test_repo):
        """When pricing is None, no divergence fields appear (no computed cost to compare)."""
        parser = TokenEchoParser(
            turns=[
                Turn(
                    input_tokens=1000,
                    output_tokens=100,
                    cache_creation_tokens=0,
                    cache_read_tokens=0,
                )
            ],
            vendor_cost=0.05,
        )

        task = Task(
            name="divergence_no_pricing",
            source="test",
            repo="test-repo",
            type=TaskType.comprehension,
            language=Language.python,
            difficulty=Difficulty.easy,
            version=1,
            prompt="no pricing test",
            ground_truth=ComprehensionGroundTruth(required_strings=["test"]),
        )
        runner = SubprocessRunner(
            name="echo-test",
            cli="echo",
            default_args=[],
            arg_map={"prompt_separator": ""},
            parser=parser,
        )
        repo_mgr = GitWorktreeManager(repos_dir=tmp_path / "repos")

        result = run_single(
            task=task,
            mode_name="baseline",
            model="test-model",
            runner=runner,
            repo_mgr=repo_mgr,
            repo_uri=str(test_repo),
            repo_commit=None,
            pricing=None,
        )

        assert "vendor_cost_divergence" not in result["metadata"]
        assert "vendor_cost_divergence_warning" not in result["metadata"]
