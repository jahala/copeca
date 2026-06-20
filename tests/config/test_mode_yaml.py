"""Tests for mode YAML files in defaults/modes/ — each file must load and
validate as a copeca.config.models.Mode."""

import yaml

from copeca.config.models import Mode
from copeca.config.resources import data_path

MODES_DIR = data_path("defaults", "modes")


def _load_mode(name: str) -> Mode:
    path = MODES_DIR / f"{name}.yaml"
    assert path.exists(), f"{path} does not exist"
    with open(path) as f:
        data = yaml.safe_load(f)
    return Mode(**data)


class TestBaselineYaml:
    def test_baseline_yaml_valid_mode(self) -> None:
        mode = _load_mode("baseline")
        assert mode.name == "baseline"
        assert len(mode.tools) > 0
        assert mode.mcp_config is None
        assert mode.env is None
        assert mode.agent_config is None
        assert mode.wrapper is None
        assert mode.setup is None


class TestRtkYaml:
    def test_rtk_yaml_valid_mode(self) -> None:
        mode = _load_mode("rtk")
        assert mode.name == "rtk"
        assert mode.agent_config is not None
        assert mode.agent_config == "path/to/rtk-settings.json"


class TestGatewayYaml:
    def test_gateway_yaml_valid_mode(self) -> None:
        mode = _load_mode("gateway")
        assert mode.name == "gateway"
        assert mode.env is not None
        assert mode.env["ANTHROPIC_BASE_URL"] == "http://localhost:8080/v1"


class TestHeadroomYaml:
    def test_headroom_yaml_valid_mode(self) -> None:
        mode = _load_mode("headroom")
        assert mode.name == "headroom"
        assert mode.wrapper is not None
        assert len(mode.wrapper) > 0
        assert "headroom" in mode.wrapper


class TestIndexedYaml:
    def test_indexed_yaml_valid_mode(self) -> None:
        mode = _load_mode("indexed")
        assert mode.name == "indexed"
        assert mode.setup is not None
        assert len(mode.setup) > 0


class TestAllModesExist:
    def test_all_five_modes_exist(self) -> None:
        expected = {"baseline", "rtk", "gateway", "headroom", "indexed"}
        actual = {p.stem for p in MODES_DIR.glob("*.yaml")}


# ── Helpers ────────────────────────────────────────────────────────────────────


def load_yaml_mode(filename: str) -> Mode:
    """Load a mode YAML from defaults/modes/ and return a Mode model."""
    import yaml as _yaml
    path = MODES_DIR / filename
    doc = _yaml.safe_load(path.read_text())
    return Mode.model_validate(doc)


# ── Content checks ─────────────────────────────────────────────────────────────


class TestModeContent:
    def test_baseline_has_tools_only_no_integration_paths(self):
        """Baseline mode is clean control -- tools only, zero integration paths."""
        mode = load_yaml_mode("baseline.yaml")
        assert mode.tools
        assert mode.mcp_config is None
        assert mode.env is None
        assert mode.agent_config is None
        assert mode.wrapper is None
        assert mode.setup is None

    def test_rtk_has_agent_config(self):
        mode = load_yaml_mode("rtk.yaml")
        assert mode.agent_config is not None

    def test_gateway_has_env_anthropic_base_url(self):
        mode = load_yaml_mode("gateway.yaml")
        assert mode.env is not None
        assert "ANTHROPIC_BASE_URL" in mode.env

    def test_headroom_has_wrapper(self):
        mode = load_yaml_mode("headroom.yaml")
        assert mode.wrapper is not None

    def test_indexed_has_setup(self):
        mode = load_yaml_mode("indexed.yaml")
        assert mode.setup is not None
