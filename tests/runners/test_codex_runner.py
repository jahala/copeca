"""Test the packaged codex runner YAML — config-driven command construction.

The codex runner must build a valid `codex exec --json` invocation for codex-cli
0.133.0, prepend the system prompt (codex has no --system-prompt flag), use the
codex_json parser, and carry pricing the cost model can consume.
"""

from copeca.cli import build_runner
from copeca.config.loader import load_runner
from copeca.config.resources import data_path
from copeca.runners.parsers.codex_json import CodexJsonParser

RUNNER_DIRS = [data_path("defaults", "runners")]


def _codex():
    return build_runner("codex", timeout=300, runner_dirs=RUNNER_DIRS)


class TestCodexRunnerCommand:
    def test_builds_baseline_command(self):
        cmd = _codex().build_command(model="gpt-5.5", prompt="find the bug")
        assert cmd[0] == "codex"
        assert "exec" in cmd
        assert "--json" in cmd
        # 0.133.0: --full-auto is deprecated; sandbox is selected explicitly.
        assert "--sandbox" in cmd
        sb_idx = cmd.index("--sandbox")
        assert cmd[sb_idx + 1] == "workspace-write"
        assert "--ephemeral" in cmd
        assert "-m" in cmd
        m_idx = cmd.index("-m")
        assert cmd[m_idx + 1] == "gpt-5.5"
        # prompt is positional, after the -- separator
        assert cmd[-1] == "find the bug"
        assert cmd[-2] == "--"

    def test_prepends_system_prompt(self):
        cmd = _codex().build_command(
            model="gpt-5.5", prompt="USER", system_prompt="SYS"
        )
        assert "--system-prompt" not in cmd  # codex has no such flag
        assert cmd[-1] == "SYS\n\nUSER"

    def test_uses_codex_json_parser(self):
        assert isinstance(_codex().parser, CodexJsonParser)


class TestCodexPricing:
    def test_pricing_has_cost_model_keys(self):
        """Every priced model must carry the four keys compute_cost reads, so a
        codex run yields a real (modeled) cost rather than a KeyError."""
        cfg = load_runner("codex", runner_dirs=RUNNER_DIRS)
        assert cfg.pricing is not None and cfg.pricing
        for model, rates in cfg.pricing.items():
            for key in ("input", "cache_creation", "cache_read", "output"):
                assert key in rates, f"{model} pricing missing '{key}'"
