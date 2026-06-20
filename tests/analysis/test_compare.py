"""Test compare_runs — pairwise comparison of JSONL result sets."""

import pytest

from copeca.analysis.compare import compare_runs


def _make_record(
    task: str = "task_a",
    total_cost_usd: float = 0.10,
    correct: bool = True,
    input_tokens: int = 1000,
    output_tokens: int = 500,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> dict:
    """Helper to build a minimal JSONL record."""
    return {
        "task": task,
        "total_cost_usd": total_cost_usd,
        "correct": correct,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_tokens": cache_creation_tokens,
        "cache_read_tokens": cache_read_tokens,
    }


class TestCompareRuns:
    """Tests for compare_runs — compare two JSONL result sets."""

    def test_compare_shows_per_task_deltas(self):
        """Output should include per-task cost-per-correct comparisons."""
        before = [
            _make_record(task="task_a", total_cost_usd=0.10, correct=True),
            _make_record(task="task_a", total_cost_usd=0.10, correct=False),
            _make_record(task="task_b", total_cost_usd=0.20, correct=True),
            _make_record(task="task_b", total_cost_usd=0.20, correct=False),
        ]
        after = [
            _make_record(task="task_a", total_cost_usd=0.05, correct=True),
            _make_record(task="task_a", total_cost_usd=0.05, correct=False),
            _make_record(task="task_b", total_cost_usd=0.15, correct=True),
            _make_record(task="task_b", total_cost_usd=0.15, correct=False),
        ]
        result = compare_runs(before, after)

        # Should mention tasks
        assert "task_a" in result
        assert "task_b" in result
        # Should mention delta
        assert "delta" in result.lower()
        # Should have markdown structure
        assert "## " in result

    def test_compare_flags_large_changes(self):
        """Tasks where cost-per-correct changed by >10% should be flagged."""
        before = [
            # task_a: cost 0.10, 1 correct → CPC = 0.10
            _make_record(task="task_a", total_cost_usd=0.10, correct=True),
            _make_record(task="task_a", total_cost_usd=0.10, correct=False),
            # task_b: cost 0.20, 1 correct → CPC = 0.20
            _make_record(task="task_b", total_cost_usd=0.20, correct=True),
            _make_record(task="task_b", total_cost_usd=0.20, correct=False),
        ]
        after = [
            # task_a: cost 0.05, 1 correct → CPC = 0.05 (50% decrease)
            _make_record(task="task_a", total_cost_usd=0.05, correct=True),
            _make_record(task="task_a", total_cost_usd=0.05, correct=False),
            # task_b: cost 0.19, 1 correct → CPC = 0.19 (5% decrease)
            _make_record(task="task_b", total_cost_usd=0.19, correct=True),
            _make_record(task="task_b", total_cost_usd=0.19, correct=False),
        ]
        result = compare_runs(before, after)

        # task_a has >10% change, should be flagged
        # The flag should mention the task name and the magnitude
        assert "task_a" in result
        # Look for common flag indicators
        has_flag = ">" in result or "flag" in result.lower() or "!" in result or "**" in result
        assert has_flag, "Large changes should be visually flagged"

    def test_compare_handles_missing_tasks(self):
        """Tasks present in one set but not the other should be noted."""
        before = [
            _make_record(task="task_a", total_cost_usd=0.10, correct=True),
            _make_record(task="only_before", total_cost_usd=0.30, correct=True),
        ]
        after = [
            _make_record(task="task_a", total_cost_usd=0.05, correct=True),
            _make_record(task="only_after", total_cost_usd=0.15, correct=True),
        ]
        result = compare_runs(before, after)

        # Should mention missing tasks (in one set but not the other)
        assert "only_before" in result or "missing" in result.lower()
        assert "only_after" in result or "new" in result.lower()

    def test_compare_returns_markdown(self):
        """Result should be a valid-looking markdown string."""
        before = [_make_record(task="task_a")]
        after = [_make_record(task="task_a")]
        result = compare_runs(before, after)
        assert isinstance(result, str)
        assert len(result) > 0
        assert result.startswith("#")

    def test_compare_empty_sets(self):
        """Both sets empty should return a valid minimal markdown string."""
        result = compare_runs([], [])
        assert isinstance(result, str)
        assert len(result) > 0
