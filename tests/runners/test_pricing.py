"""Test pricing YAML — structure, field presence, and value correctness."""

import datetime

import pytest
import yaml

from copeca.config.resources import data_path

# Resolve the bundled defaults directory (works from a checkout or a wheel)
DEFAULTS_DIR = data_path("defaults")


@pytest.fixture
def claude_pricing():
    """Load the Claude pricing YAML file."""
    path = DEFAULTS_DIR / "runners" / "claude.yaml"
    if not path.exists():
        pytest.skip(f"Pricing file not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


class TestClaudePricing:
    """Tests for the Claude pricing YAML file."""

    def test_claude_yaml_loads(self, claude_pricing):
        """YAML file exists and is parseable."""
        assert claude_pricing is not None
        assert "pricing" in claude_pricing

    def test_pricing_has_required_fields(self, claude_pricing):
        """Each model has input, cache_creation, cache_read, output, updated."""
        required_fields = {"input", "cache_creation", "cache_read", "output", "updated"}
        for model_name, model_pricing in claude_pricing["pricing"].items():
            missing = required_fields - set(model_pricing.keys())
            assert not missing, f"Model '{model_name}' missing fields: {missing}"

    def test_pricing_values_are_positive(self, claude_pricing):
        """All rates should be > 0."""
        numeric_fields = {"input", "cache_creation", "cache_read", "output"}
        for model_name, model_pricing in claude_pricing["pricing"].items():
            for field in numeric_fields:
                value = model_pricing[field]
                assert isinstance(value, (int, float)), (
                    f"Model '{model_name}' field '{field}' is not numeric: {value!r}"
                )
                assert value > 0, f"Model '{model_name}' field '{field}' must be positive: {value}"

    def test_updated_date_is_parseable(self, claude_pricing):
        """updated field is a valid ISO date string (YYYY-MM-DD)."""
        for model_name, model_pricing in claude_pricing["pricing"].items():
            updated = model_pricing["updated"]
            assert isinstance(updated, str), (
                f"Model '{model_name}' 'updated' field must be a string: {updated!r}"
            )
            try:
                datetime.date.fromisoformat(updated)
            except ValueError:
                pytest.fail(f"Model '{model_name}' 'updated' is not a valid date: {updated!r}")


# ── Helpers ────────────────────────────────────────────────────────────────────


def load_pricing():
    """Yield (model_name, pricing_dict) tuples from all runner YAMLs."""
    runners_dir = DEFAULTS_DIR / "runners"
    for path in sorted(runners_dir.glob("*.yaml")):
        with open(path) as f:
            data = yaml.safe_load(f)
        if "pricing" in data:
            yield from data["pricing"].items()


# ── Content checks ─────────────────────────────────────────────────────────────


class TestPricingContent:
    def test_all_models_have_four_rate_fields(self):
        """Every model entry has the four rate keys, all numeric. input/output/
        cache_read are always billed (> 0); cache_creation may be 0 for providers
        that report no separate cache-write token count (e.g. codex), so the cost
        model never multiplies a nonzero rate against it — it need only be >= 0.
        """
        for model_name, entry in load_pricing():
            for field in ["input", "output", "cache_creation", "cache_read"]:
                assert field in entry, f"{model_name} missing {field}"
                assert isinstance(entry[field], (int, float)), (
                    f"{model_name} {field} is not numeric: {entry[field]!r}"
                )
            for field in ["input", "output", "cache_read"]:
                assert entry[field] > 0, f"{model_name} {field} is not positive"
            assert entry["cache_creation"] >= 0, f"{model_name} cache_creation must be >= 0"

    def test_all_models_have_updated_date(self):
        for model_name, entry in load_pricing():
            assert "updated" in entry, f"{model_name} missing updated"
            datetime.date.fromisoformat(entry["updated"])  # must parse
