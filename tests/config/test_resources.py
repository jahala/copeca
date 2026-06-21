"""Test the bundled-data resolver — resolves package data in source checkout
AND in an installed wheel (importlib.resources, not __file__ traversal)."""

from copeca.config.resources import data_path


def test_schema_resolves():
    """task.schema.json resolves under the bundled data tree."""
    assert data_path("schemas", "task.schema.json").exists()


def test_mode_yaml_resolves():
    """A default mode YAML resolves under the bundled data tree."""
    assert data_path("defaults", "modes", "baseline.yaml").exists()
