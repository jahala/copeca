"""Test cost computation — pure function for tokens × pricing → USD."""

import pytest

from copeca.runners.cost import compute_cost


class TestComputeCost:
    """Test the pure cost computation function."""

    def test_computes_correct_cost(self):
        """Given known token counts and pricing, assert cost matches hand-calculated value."""
        tokens = {
            "input_tokens": 100_000,
            "output_tokens": 50_000,
            "cache_creation_tokens": 20_000,
            "cache_read_tokens": 30_000,
        }
        pricing = {
            "input": 3.00,
            "cache_creation": 3.75,
            "cache_read": 0.30,
            "output": 15.00,
        }
        # Hand-calculated:
        # input:      100_000 × 3.00  = 300_000   / 1_000_000 = 0.300
        # cache_cre:   20_000 × 3.75  =  75_000   / 1_000_000 = 0.075
        # cache_read:  30_000 × 0.30  =   9_000   / 1_000_000 = 0.009
        # output:      50_000 × 15.00 = 750_000   / 1_000_000 = 0.750
        # total = 1.134
        expected = 1.134
        assert compute_cost(tokens, pricing) == pytest.approx(expected, abs=1e-4)

    def test_zero_tokens_returns_zero(self):
        """All zero tokens should return $0.00."""
        tokens = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
        }
        pricing = {
            "input": 3.00,
            "cache_creation": 3.75,
            "cache_read": 0.30,
            "output": 15.00,
        }
        assert compute_cost(tokens, pricing) == 0.0

    def test_only_input_tokens(self):
        """Only input tokens — should compute correctly."""
        tokens = {
            "input_tokens": 500_000,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
        }
        pricing = {
            "input": 3.00,
            "cache_creation": 3.75,
            "cache_read": 0.30,
            "output": 15.00,
        }
        # 500_000 × 3.00 / 1_000_000 = 1.50
        expected = 1.50
        assert compute_cost(tokens, pricing) == pytest.approx(expected, abs=1e-4)

    def test_differential_cache_rates(self):
        """cache_read is cheaper than cache_creation — verify the math."""
        pricing = {
            "input": 3.00,
            "cache_creation": 3.75,
            "cache_read": 0.30,
            "output": 15.00,
        }
        # 1M cache_creation tokens vs 1M cache_read tokens
        tokens_create = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 1_000_000,
            "cache_read_tokens": 0,
        }
        tokens_read = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 1_000_000,
        }
        cost_create = compute_cost(tokens_create, pricing)
        cost_read = compute_cost(tokens_read, pricing)
        # 1M cache_creation @ 3.75 = 3.75
        # 1M cache_read @ 0.30 = 0.30
        assert cost_create == pytest.approx(3.75, abs=1e-4)
        assert cost_read == pytest.approx(0.30, abs=1e-4)
        assert cost_read < cost_create

    def test_floating_point_precision(self):
        """Result should be within 1e-4 tolerance for large token counts."""
        tokens = {
            "input_tokens": 1_234_567,
            "output_tokens": 987_654,
            "cache_creation_tokens": 345_678,
            "cache_read_tokens": 123_456,
        }
        pricing = {
            "input": 3.00,
            "cache_creation": 3.75,
            "cache_read": 0.30,
            "output": 15.00,
        }
        # input:      1_234_567 × 3.00  = 3_703_701.00
        # cache_cre:    345_678 × 3.75  = 1_296_292.50
        # cache_read:   123_456 × 0.30  =    37_036.80
        # output:       987_654 × 15.00 = 14_814_810.00
        # sum = 19_851_840.30 / 1_000_000 = 19.8518403
        expected = 19.8518403
        result = compute_cost(tokens, pricing)
        assert result == pytest.approx(expected, abs=1e-4)
        # Verify the raw type is float
        assert isinstance(result, float)
