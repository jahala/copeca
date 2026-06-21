"""Tool-availability preflight (SD-I).

A mode can declare a tool the host doesn't have installed (an MCP server binary,
a wrapper command). If the agent launches anyway, the tool silently fails to
attach and the experimental arm runs as a tool-less baseline — a FALSE NULL. The
preflight catches this BEFORE spending. `which` is injected so the logic is
testable without touching the real PATH.
"""

from copeca.config.models import Mode
from copeca.orchestration.validation import check_tool_availability


def _tilth_mode() -> Mode:
    return Mode(
        name="tilth",
        description="tilth MCP arm",
        mcp_config={"mcpServers": {"tilth": {"command": "tilth", "args": ["--mcp"]}}},
    )


class TestToolAvailability:
    def test_missing_mcp_command_is_flagged(self):
        errors = check_tool_availability(_tilth_mode(), runner_cli="claude", which=lambda c: None)
        assert any("tilth" in e for e in errors), errors
        assert any("claude" in e for e in errors), errors

    def test_all_available_passes(self):
        errors = check_tool_availability(
            _tilth_mode(), runner_cli="claude", which=lambda c: f"/usr/bin/{c}"
        )
        assert errors == []

    def test_wrapper_command_checked(self):
        mode = Mode(name="wrap", description="x", wrapper=["nonesuch-wrapper", "--flag"])
        errors = check_tool_availability(mode, which=lambda c: None)
        assert any("nonesuch-wrapper" in e for e in errors), errors

    def test_baseline_mode_has_nothing_to_check(self):
        mode = Mode(name="baseline", description="x", tools=["Read"])
        errors = check_tool_availability(mode, runner_cli="claude", which=lambda c: f"/bin/{c}")
        assert errors == []

    def test_none_mode_only_checks_runner(self):
        errors = check_tool_availability(None, runner_cli="claude", which=lambda c: None)
        assert errors == ["runner CLI 'claude' not found on PATH"]
