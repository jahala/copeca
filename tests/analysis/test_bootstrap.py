"""Test bootstrap confidence interval — pure computation, no external deps."""

import pytest

from copeca.analysis.stats import bootstrap_ci


class TestBootstrapCI:
    """Tests for bootstrap_ci — bootstrapped 95% confidence interval."""

    def test_bootstrap_ci_contains_mean(self):
        """CI bounds should surround the true mean of the sample."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        lower, upper, median, mean = bootstrap_ci(values, n_resamples=5000, alpha=0.05)

        true_mean = sum(values) / len(values)
        # With 5000 resamples, the CI should contain the mean
        assert lower <= true_mean <= upper, f"CI [{lower}, {upper}] should contain {true_mean}"
        # Median should be between min and max
        assert min(values) <= median <= max(values)
        # Mean should be reasonable
        assert median == pytest.approx(mean, rel=0.5)

    def test_bootstrap_single_value(self):
        """Single value: CI should be tight around that value."""
        values = [5.0]
        lower, upper, median, mean = bootstrap_ci(values, n_resamples=100, alpha=0.05)

        assert lower == pytest.approx(5.0)
        assert upper == pytest.approx(5.0)
        assert median == pytest.approx(5.0)
        assert mean == pytest.approx(5.0)

    def test_bootstrap_empty_returns_zeros(self):
        """Empty list returns zeros for all values."""
        lower, upper, median, mean = bootstrap_ci([])
        assert lower == 0.0
        assert upper == 0.0
        assert median == 0.0
        assert mean == 0.0

    def test_bootstrap_reproducible_with_seed(self):
        """Same seed produces the same result."""
        import random

        values = [1.0, 3.0, 5.0, 7.0, 9.0, 2.0, 4.0, 6.0, 8.0, 10.0]

        random.seed(42)
        result1 = bootstrap_ci(values, n_resamples=2000, alpha=0.05)

        random.seed(42)
        result2 = bootstrap_ci(values, n_resamples=2000, alpha=0.05)

        assert result1 == result2

    def test_bootstrap_ci_narrower_with_more_resamples(self):
        """More resamples should not wildly change the CI — it should stabilize."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]

        lower_1k, upper_1k, _, _ = bootstrap_ci(values, n_resamples=1000, alpha=0.05)
        lower_5k, upper_5k, _, _ = bootstrap_ci(values, n_resamples=5000, alpha=0.05)

        # The CI widths should be within reasonable range of each other
        width_1k = upper_1k - lower_1k
        width_5k = upper_5k - lower_5k
        # Both should be positive and reasonable
        assert width_1k > 0
        assert width_5k > 0
        # The ratio shouldn't be extreme (stability check)
        assert 0.3 < width_1k / width_5k < 3.0
