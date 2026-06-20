"""Test pricing staleness check — warnings when pricing data is >30 days old."""

from datetime import date, timedelta
from unittest import mock

import pytest

from copeca.orchestration.validation import check_pricing_staleness


class TestStaleness:
    def test_current_pricing_produces_no_warnings(self):
        pricing = {
            "claude-sonnet-4-6": {
                "input": 3.0, "output": 15.0, "cache_creation": 3.75,
                "cache_read": 0.30, "updated": "2026-06-19",
            },
        }
        with _freeze_date(2026, 6, 19):
            warnings = check_pricing_staleness(pricing)
        assert warnings == []

    def test_stale_pricing_produces_warning(self):
        pricing = {
            "claude-sonnet-4-6": {
                "input": 3.0, "output": 15.0, "cache_creation": 3.75,
                "cache_read": 0.30, "updated": "2026-05-10",
            },
        }
        with _freeze_date(2026, 6, 19):
            warnings = check_pricing_staleness(pricing)
        assert len(warnings) == 1
        assert "claude-sonnet-4-6" in warnings[0]
        assert "40 days" in warnings[0]

    def test_mixed_staleness(self):
        pricing = {
            "claude-sonnet-4-6": {
                "input": 3.0, "output": 15.0, "cache_creation": 3.75,
                "cache_read": 0.30, "updated": "2026-06-19",
            },
            "claude-opus-4-8": {
                "input": 15.0, "output": 75.0, "cache_creation": 18.75,
                "cache_read": 1.50, "updated": "2026-01-01",
            },
        }
        with _freeze_date(2026, 6, 19):
            warnings = check_pricing_staleness(pricing)
        assert len(warnings) == 1
        assert "claude-opus-4-8" in warnings[0]

    def test_missing_updated_field_warns(self):
        pricing = {
            "unknown-model": {
                "input": 1.0, "output": 5.0, "cache_creation": 1.25,
                "cache_read": 0.10,
            },
        }
        warnings = check_pricing_staleness(pricing)
        assert len(warnings) == 1
        assert "unknown-model" in warnings[0]
        assert "missing" in warnings[0].lower()

    def test_per_model_granularity(self):
        pricing = {
            "model-a": {"input": 1.0, "output": 1.0, "cache_creation": 1.0,
                        "cache_read": 1.0, "updated": "2026-06-19"},
            "model-b": {"input": 2.0, "output": 2.0, "cache_creation": 2.0,
                        "cache_read": 2.0, "updated": "2026-05-01"},
            "model-c": {"input": 3.0, "output": 3.0, "cache_creation": 3.0,
                        "cache_read": 3.0, "updated": "2026-06-18"},
        }
        with _freeze_date(2026, 6, 19):
            warnings = check_pricing_staleness(pricing)
        assert len(warnings) == 1
        assert "model-b" in warnings[0]

    def test_warning_does_not_block(self):
        pricing = {
            "claude-sonnet-4-6": {
                "input": 3.0, "output": 15.0, "cache_creation": 3.75,
                "cache_read": 0.30, "updated": "2020-01-01",
            },
        }
        with _freeze_date(2026, 6, 19):
            warnings = check_pricing_staleness(pricing)
        # Returns warnings, never raises
        assert isinstance(warnings, list)
        assert len(warnings) >= 1


def _freeze_date(year: int, month: int, day: int):
    """Context manager that freezes date.today() to a specific date."""
    frozen = date(year, month, day)
    return mock.patch("copeca.orchestration.validation._today", return_value=frozen)
