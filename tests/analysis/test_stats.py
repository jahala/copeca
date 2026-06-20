"""Test statistical functions — pure computation on lists of dicts."""

import math

import pytest

from copeca.analysis.stats import ascii_sparkline, compute_stats, cost_per_correct, group_by


class TestComputeStats:
    """Tests for compute_stats — median, mean, stdev, min, max on a numeric field."""

    def test_compute_stats_returns_correct_values(self):
        """Given a known list of records, verify median, mean, stdev, min, max."""
        records = [
            {"total_cost_usd": 1.0},
            {"total_cost_usd": 2.0},
            {"total_cost_usd": 3.0},
            {"total_cost_usd": 4.0},
            {"total_cost_usd": 5.0},
        ]
        result = compute_stats(records, field="total_cost_usd")

        assert result["median"] == pytest.approx(3.0)
        assert result["mean"] == pytest.approx(3.0)
        # Population stdev: mean=3, squared diffs: 4+1+0+1+4=10, var=10/5=2, stdev=√2
        assert result["stdev"] == pytest.approx(math.sqrt(2.0))
        assert result["min"] == pytest.approx(1.0)
        assert result["max"] == pytest.approx(5.0)
        assert result["count"] == 5

    def test_compute_stats_even_count_median(self):
        """Median of an even number of values averages the two middle values."""
        records = [
            {"total_cost_usd": 1.0},
            {"total_cost_usd": 3.0},
            {"total_cost_usd": 5.0},
            {"total_cost_usd": 7.0},
        ]
        result = compute_stats(records, field="total_cost_usd")
        assert result["median"] == pytest.approx(4.0)  # (3+5)/2

    def test_compute_stats_empty_returns_zeros(self):
        """Empty records list returns zeros for all stats."""
        result = compute_stats([], field="total_cost_usd")
        assert result["median"] == 0.0
        assert result["mean"] == 0.0
        assert result["stdev"] == 0.0
        assert result["min"] == 0.0
        assert result["max"] == 0.0
        assert result["count"] == 0

    def test_compute_stats_single_record(self):
        """Single record — median/mean = the value, stdev = 0."""
        records = [{"total_cost_usd": 4.2}]
        result = compute_stats(records, field="total_cost_usd")
        assert result["median"] == pytest.approx(4.2)
        assert result["mean"] == pytest.approx(4.2)
        assert result["stdev"] == 0.0
        assert result["min"] == pytest.approx(4.2)
        assert result["max"] == pytest.approx(4.2)
        assert result["count"] == 1

    def test_compute_stats_missing_field_skipped(self):
        """Records missing the field are skipped gracefully."""
        records = [
            {"total_cost_usd": 1.0},
            {"other_field": 99.0},
            {"total_cost_usd": 5.0},
        ]
        result = compute_stats(records, field="total_cost_usd")
        assert result["count"] == 2
        assert result["mean"] == pytest.approx(3.0)

    def test_compute_stats_with_none_values_skipped(self):
        """Records with None for the field are skipped."""
        records = [
            {"total_cost_usd": 1.0},
            {"total_cost_usd": None},
            {"total_cost_usd": 5.0},
        ]
        result = compute_stats(records, field="total_cost_usd")
        assert result["count"] == 2
        assert result["min"] == pytest.approx(1.0)
        assert result["max"] == pytest.approx(5.0)


class TestCostPerCorrect:
    """Tests for cost_per_correct — total cost divided by number correct."""

    def test_cost_per_correct_computed_correctly(self):
        """3 records, 2 correct, sum=$0.30 → cost_per_correct=$0.15."""
        records = [
            {"total_cost_usd": 0.10, "correct": True},
            {"total_cost_usd": 0.10, "correct": True},
            {"total_cost_usd": 0.10, "correct": False},
        ]
        result = cost_per_correct(records)
        assert result == pytest.approx(0.15)

    def test_cost_per_correct_zero_correct_returns_none(self):
        """When no records are correct, return None (undefined — cost per correct is meaningless)."""
        records = [
            {"total_cost_usd": 0.10, "correct": False},
            {"total_cost_usd": 0.20, "correct": False},
        ]
        result = cost_per_correct(records)
        assert result is None

    def test_cost_per_correct_empty_records_returns_none(self):
        """Empty records list returns None (no correct answers, metric is undefined)."""
        result = cost_per_correct([])
        assert result is None


class TestGroupBy:
    """Tests for group_by — group records by a key field."""

    def test_group_by_groups_correctly(self):
        """Records with same key value end up in the same group."""
        records = [
            {"task": "task_a", "value": 1},
            {"task": "task_b", "value": 2},
            {"task": "task_a", "value": 3},
        ]
        result = group_by(records, key="task")
        assert set(result.keys()) == {"task_a", "task_b"}
        assert len(result["task_a"]) == 2
        assert len(result["task_b"]) == 1
        assert result["task_a"][0]["value"] == 1
        assert result["task_a"][1]["value"] == 3

    def test_group_by_empty_records(self):
        """Empty list returns empty dict."""
        result = group_by([], key="task")
        assert result == {}

    def test_group_by_missing_key(self):
        """Records missing the group key are placed under None."""
        records = [
            {"task": "task_a", "value": 1},
            {"value": 99},
        ]
        result = group_by(records, key="task")
        assert "task_a" in result
        assert None in result
        assert len(result[None]) == 1


class TestAsciiSparkline:
    """Tests for ascii_sparkline — render a sequence of values as ASCII."""

    def test_ascii_sparkline_renders(self):
        """Sparkline returns a string of the correct width."""
        values = [1.0, 2.0, 3.0, 2.0, 1.0]
        result = ascii_sparkline(values, width=10)
        assert isinstance(result, str)
        assert len(result) == 10

    def test_ascii_sparkline_empty(self):
        """Empty values return empty string."""
        result = ascii_sparkline([])
        assert result == ""

    def test_ascii_sparkline_constant_values(self):
        """All values equal — all chars should be the middle bar."""
        values = [5.0, 5.0, 5.0, 5.0]
        result = ascii_sparkline(values, width=8)
        assert len(result) == 8
        # All constant values map to the same character (bar at position 4)
        assert len(set(result)) == 1
