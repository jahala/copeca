"""Tests for the Gemini CLI ``--output-format json`` parser (ISO-5).

Fixture: tests/fixtures/sample_gemini_json.json — a realistic single-object JSON
blob matching the real ``gemini --output-format json`` output shape.

Coverage:
- Parser extracts correct token counts, result_text, and tool calls from fixture.
- Empty stats / missing models key → zero tokens, no crash.
- Missing stats key altogether → zero tokens, no crash.
- Malformed JSON (not valid JSON) → RunResult.error set, no exception raised.
- load_runner("gemini") loads with the isolation block + parser="gemini_json".
- GeminiJsonParser is registered in the parser registry under "gemini_json".
- provision_arm(baseline, worktree, isolation=cfg.isolation) with GEMINI_API_KEY set
  → arm env contains GEMINI_CLI_HOME + HOME pointing at the private dir, and
  GEMINI_CLI_TRUST_WORKSPACE=true from disable_ambient_env.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from copeca.config.loader import load_runner
from copeca.config.models import IsolationSpec
from copeca.config.resources import data_path
from copeca.orchestration.state import provision_arm
from copeca.runners.parsers import ParserNotFoundError, get_parser
from copeca.runners.parsers.gemini_json import (
    GeminiJsonParser,
    parse_gemini_json,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE = FIXTURES / "sample_gemini_json.json"
DEFAULT_RUNNERS_DIR = data_path("defaults", "runners")


# ---------------------------------------------------------------------------
# Fixture loading helpers
# ---------------------------------------------------------------------------


def _raw() -> str:
    return SAMPLE.read_text()


def _obj() -> dict:  # type: ignore[type-arg]
    return json.loads(_raw())


# ---------------------------------------------------------------------------
# Token extraction from fixture
# ---------------------------------------------------------------------------


class TestGeminiJsonTokens:
    def test_input_tokens(self) -> None:
        result = parse_gemini_json(_raw())
        # fixture: tokens.prompt = 4210
        assert result.total_input_tokens == 4210

    def test_output_tokens_includes_thoughts(self) -> None:
        # output_tokens = candidates (87) + thoughts (32) = 119
        result = parse_gemini_json(_raw())
        assert result.total_output_tokens == 87 + 32

    def test_cache_read_tokens(self) -> None:
        result = parse_gemini_json(_raw())
        assert result.total_cache_read_tokens == 1024

    def test_cache_creation_tokens_is_zero(self) -> None:
        # gemini reports no cache-write count
        result = parse_gemini_json(_raw())
        assert result.total_cache_creation_tokens == 0

    def test_no_vendor_cost(self) -> None:
        # gemini emits no total_cost_usd — cost is computed downstream (modeled)
        assert parse_gemini_json(_raw()).total_cost_usd == 0.0

    def test_one_turn(self) -> None:
        result = parse_gemini_json(_raw())
        assert result.num_turns == 1


# ---------------------------------------------------------------------------
# Result text extraction
# ---------------------------------------------------------------------------


class TestGeminiJsonResultText:
    def test_result_text_from_fixture(self) -> None:
        result = parse_gemini_json(_raw())
        assert "add" in result.result_text
        assert "src/utils.py" in result.result_text


# ---------------------------------------------------------------------------
# Tool call extraction
# ---------------------------------------------------------------------------


class TestGeminiJsonToolCalls:
    def test_tool_call_count(self) -> None:
        # byName: {"read_file": 1, "search_code": 1} → 2 tool calls
        result = parse_gemini_json(_raw())
        assert result.num_tool_calls == 2

    def test_tool_names_present(self) -> None:
        result = parse_gemini_json(_raw())
        names = {tc.name for tc in result.tool_calls}
        assert "read_file" in names
        assert "search_code" in names


# ---------------------------------------------------------------------------
# Robustness: empty / missing stats
# ---------------------------------------------------------------------------


class TestGeminiJsonEmptyStats:
    def test_empty_string_input(self) -> None:
        result = parse_gemini_json("")
        assert result.num_turns == 0
        assert result.result_text == ""
        assert result.error is None

    def test_missing_stats_key(self) -> None:
        raw = json.dumps({"response": "hi", "error": {}})
        result = parse_gemini_json(raw)
        assert result.num_turns == 0
        assert result.result_text == "hi"
        assert result.error is None

    def test_empty_stats_dict(self) -> None:
        raw = json.dumps({"response": "hi", "stats": {}, "error": {}})
        result = parse_gemini_json(raw)
        assert result.num_turns == 0
        assert result.num_tool_calls == 0

    def test_missing_models_key(self) -> None:
        raw = json.dumps({"response": "hi", "stats": {"tools": {}}, "error": {}})
        result = parse_gemini_json(raw)
        assert result.num_turns == 0

    def test_all_zero_tokens_produces_no_turn(self) -> None:
        raw = json.dumps(
            {
                "response": "hi",
                "stats": {
                    "models": {
                        "gemini-2.5-flash": {
                            "tokens": {
                                "prompt": 0,
                                "candidates": 0,
                                "cached": 0,
                                "thoughts": 0,
                                "tool": 0,
                                "total": 0,
                            }
                        }
                    }
                },
                "error": {},
            }
        )
        result = parse_gemini_json(raw)
        # all-zero tokens → no turn appended (nothing meaningful to record)
        assert result.num_turns == 0

    def test_empty_by_name_produces_no_tool_calls(self) -> None:
        raw = json.dumps(
            {
                "response": "hi",
                "stats": {"tools": {"totalCalls": 0, "byName": {}}},
                "error": {},
            }
        )
        result = parse_gemini_json(raw)
        assert result.num_tool_calls == 0


# ---------------------------------------------------------------------------
# Error handling: malformed JSON
# ---------------------------------------------------------------------------


class TestGeminiJsonMalformed:
    def test_malformed_json_sets_error(self) -> None:
        result = parse_gemini_json("not valid json {{{")
        assert result.error is not None
        assert "malformed JSON" in result.error

    def test_malformed_json_does_not_raise(self) -> None:
        # must not propagate a ParseError or any exception
        result = parse_gemini_json("}{")
        assert result.error is not None

    def test_non_object_json_sets_error(self) -> None:
        result = parse_gemini_json("[1, 2, 3]")
        assert result.error is not None

    def test_error_field_populated(self) -> None:
        # a non-empty error dict in the gemini output should surface as error
        raw = json.dumps(
            {"response": "", "stats": {}, "error": {"code": 500, "message": "timeout"}}
        )
        result = parse_gemini_json(raw)
        assert result.error is not None
        assert "timeout" in result.error


# ---------------------------------------------------------------------------
# Parser adapter (GeminiJsonParser)
# ---------------------------------------------------------------------------


class TestGeminiJsonParserAdapter:
    def test_parse_delegates_to_parse_fn(self) -> None:
        result = GeminiJsonParser().parse(_raw())
        assert result.num_turns == 1
        assert result.total_input_tokens == 4210

    def test_parse_empty(self) -> None:
        result = GeminiJsonParser().parse("")
        assert result.num_turns == 0

    def test_parse_signature_accepts_supported_events(self) -> None:
        # supported_events is ignored by gemini parser (protocol compat)
        result = GeminiJsonParser().parse(_raw(), supported_events=["some_event"])
        assert result.num_turns == 1


# ---------------------------------------------------------------------------
# Parser registry
# ---------------------------------------------------------------------------


class TestGeminiJsonRegistry:
    def test_gemini_json_registered(self) -> None:
        parser = get_parser("gemini_json")
        assert isinstance(parser, GeminiJsonParser)

    def test_unknown_parser_still_raises(self) -> None:
        with pytest.raises(ParserNotFoundError):
            get_parser("nonexistent_parser_xyz")


# ---------------------------------------------------------------------------
# load_runner("gemini") — isolation block + parser resolution
# ---------------------------------------------------------------------------


class TestLoadRunnerGemini:
    def test_load_runner_gemini_succeeds(self) -> None:
        rc = load_runner("gemini", runner_dirs=[DEFAULT_RUNNERS_DIR])
        assert rc.cli == "gemini"

    def test_parser_name_is_gemini_json(self) -> None:
        rc = load_runner("gemini", runner_dirs=[DEFAULT_RUNNERS_DIR])
        assert rc.parser == "gemini_json"

    def test_isolation_block_present(self) -> None:
        rc = load_runner("gemini", runner_dirs=[DEFAULT_RUNNERS_DIR])
        assert isinstance(rc.isolation, IsolationSpec)

    def test_config_home_env_is_gemini_cli_home(self) -> None:
        rc = load_runner("gemini", runner_dirs=[DEFAULT_RUNNERS_DIR])
        assert rc.isolation.config_home_env == "GEMINI_CLI_HOME"

    def test_strict_mcp_flags_is_empty(self) -> None:
        # Baseline isolation via fresh home — no flag needed (see YAML comment)
        rc = load_runner("gemini", runner_dirs=[DEFAULT_RUNNERS_DIR])
        assert rc.isolation.strict_mcp_flags == []

    def test_disable_ambient_env_contains_trust_workspace(self) -> None:
        rc = load_runner("gemini", runner_dirs=[DEFAULT_RUNNERS_DIR])
        assert rc.isolation.disable_ambient_env.get("GEMINI_CLI_TRUST_WORKSPACE") == "true"

    def test_ambient_files_contains_gemini_md(self) -> None:
        rc = load_runner("gemini", runner_dirs=[DEFAULT_RUNNERS_DIR])
        assert "GEMINI.md" in rc.isolation.ambient_files

    def test_api_key_env_is_gemini_api_key(self) -> None:
        rc = load_runner("gemini", runner_dirs=[DEFAULT_RUNNERS_DIR])
        assert rc.isolation.api_key_env == "GEMINI_API_KEY"

    def test_version_cmd(self) -> None:
        rc = load_runner("gemini", runner_dirs=[DEFAULT_RUNNERS_DIR])
        assert rc.isolation.version_cmd == ["gemini", "--version"]

    def test_pricing_keys_present(self) -> None:
        rc = load_runner("gemini", runner_dirs=[DEFAULT_RUNNERS_DIR])
        assert rc.pricing is not None
        assert "gemini-2.5-pro" in rc.pricing
        assert "gemini-2.5-flash" in rc.pricing

    def test_pricing_fields(self) -> None:
        rc = load_runner("gemini", runner_dirs=[DEFAULT_RUNNERS_DIR])
        assert rc.pricing is not None
        for model, rates in rc.pricing.items():
            assert "input" in rates, f"{model} missing 'input' rate"
            assert "output" in rates, f"{model} missing 'output' rate"
            assert "cache_creation" in rates, f"{model} missing 'cache_creation' rate"
            assert "cache_read" in rates, f"{model} missing 'cache_read' rate"
            assert "updated" in rates, f"{model} missing 'updated' field"


# ---------------------------------------------------------------------------
# provision_arm: baseline clean-room env wiring
# ---------------------------------------------------------------------------


class TestGeminiProvisionArm:
    def test_arm_env_sets_gemini_cli_home_and_home(self, tmp_path: Path) -> None:
        """ISO-2: private home is set as both HOME and GEMINI_CLI_HOME."""
        rc = load_runner("gemini", runner_dirs=[DEFAULT_RUNNERS_DIR])
        fake_env = {
            "GEMINI_API_KEY": "AIza-test-key",
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
        }
        with patch.dict(os.environ, fake_env, clear=True):
            harness = provision_arm(
                mode=None,
                worktree=tmp_path,
                arm_name="baseline",
                isolation=rc.isolation,
            )

        try:
            private = harness.private_home
            assert harness.env.get("HOME") == private
            assert harness.env.get("GEMINI_CLI_HOME") == private
        finally:
            # clean up the temp dir provision_arm created
            import shutil

            if harness.private_home and Path(harness.private_home).exists():
                shutil.rmtree(harness.private_home, ignore_errors=True)

    def test_arm_env_sets_trust_workspace(self, tmp_path: Path) -> None:
        """disable_ambient_env {GEMINI_CLI_TRUST_WORKSPACE: true} reaches the arm env."""
        rc = load_runner("gemini", runner_dirs=[DEFAULT_RUNNERS_DIR])
        fake_env = {
            "GEMINI_API_KEY": "AIza-test-key",
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
        }
        with patch.dict(os.environ, fake_env, clear=True):
            harness = provision_arm(
                mode=None,
                worktree=tmp_path,
                arm_name="baseline",
                isolation=rc.isolation,
            )

        try:
            assert harness.env.get("GEMINI_CLI_TRUST_WORKSPACE") == "true"
        finally:
            import shutil

            if harness.private_home and Path(harness.private_home).exists():
                shutil.rmtree(harness.private_home, ignore_errors=True)

    def test_subscription_profile_when_api_key_absent(self, tmp_path: Path) -> None:
        """When GEMINI_API_KEY is absent provision_arm selects the SUBSCRIPTION profile:
        no private home, exclude_keys contains provider keys."""
        rc = load_runner("gemini", runner_dirs=[DEFAULT_RUNNERS_DIR])
        fake_env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
        with patch.dict(os.environ, fake_env, clear=True):
            harness = provision_arm(
                mode=None,
                worktree=tmp_path,
                arm_name="baseline",
                isolation=rc.isolation,
            )
        assert harness.private_home is None
        assert "GEMINI_API_KEY" in harness.exclude_keys
