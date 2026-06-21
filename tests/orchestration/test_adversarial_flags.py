"""Tests for adversarial flag computation — RED-first, per engineering.md §6.

Covers all 5 flags:
  token_snowball   — fixed formula (num_turns × avg_first_3 × factor)
  talkative_failure — output_tokens > threshold AND correct == False
  tool_storm        — num_tool_calls > threshold
  budget_exhausted  — cost >= budget AND result_text empty/None
  timeout           — duration_ms >= timeout_seconds * 1000

Also covers:
  - null-not-false semantics when data is genuinely missing
  - configurable thresholds via AdversarialThresholds on Scenario
  - scenario.budget_usd is threaded into run_single via _run_one_work_item
"""

import pytest

from copeca.config.models import AdversarialThresholds, Scenario
from copeca.orchestration.run import _check_token_snowball, _compute_adversarial_flags
from copeca.runners.parsers.base import RunResult, ToolCall, Turn


# ── Helpers ────────────────────────────────────────────────────────────────────


def _parsed(
    *,
    turns: list[Turn] | None = None,
    result_text: str = "some result",
    total_cost_usd: float = 0.0,
    duration_ms: int = 1000,
    tool_calls: list[ToolCall] | None = None,
    error: str | None = None,
) -> RunResult:
    return RunResult(
        turns=turns or [],
        result_text=result_text,
        total_cost_usd=total_cost_usd,
        duration_ms=duration_ms,
        tool_calls=tool_calls or [],
        error=error,
    )


def _flags(
    parsed: RunResult,
    *,
    total_cost_usd: float = 0.0,
    budget_usd: float | None = None,
    timeout_seconds: int = 300,
    correct: bool | None = None,
    thresholds: AdversarialThresholds | None = None,
) -> dict:
    return _compute_adversarial_flags(
        parsed=parsed,
        total_cost_usd=total_cost_usd,
        budget_usd=budget_usd,
        timeout_seconds=timeout_seconds,
        correct=correct,
        thresholds=thresholds or AdversarialThresholds(),
    )


# ── token_snowball ─────────────────────────────────────────────────────────────


class TestTokenSnowball:
    """token_snowball: max(per-turn output) > num_turns × avg(first_3) × factor."""

    def test_fires_when_max_exceeds_formula(self) -> None:
        """max turn output > num_turns × avg_first_3 × 2.0 → True."""
        # 4 turns; avg_first_3 = 100; threshold = 4 × 100 × 2.0 = 800
        # last turn = 900 → fires
        parsed = _parsed(turns=[
            Turn(output_tokens=100),
            Turn(output_tokens=100),
            Turn(output_tokens=100),
            Turn(output_tokens=900),
        ])
        assert _flags(parsed)["token_snowball"] is True

    def test_does_not_fire_at_boundary(self) -> None:
        """max turn == threshold (=, not >) → False."""
        # 4 turns; avg_first_3 = 100; threshold = 800; last = 800 (not >)
        parsed = _parsed(turns=[
            Turn(output_tokens=100),
            Turn(output_tokens=100),
            Turn(output_tokens=100),
            Turn(output_tokens=800),
        ])
        assert _flags(parsed)["token_snowball"] is False

    def test_flat_turns_return_false(self) -> None:
        """Uniform output tokens across turns → False."""
        parsed = _parsed(turns=[
            Turn(output_tokens=200),
            Turn(output_tokens=200),
            Turn(output_tokens=200),
            Turn(output_tokens=200),
        ])
        assert _flags(parsed)["token_snowball"] is False

    def test_fewer_than_three_turns_returns_none(self) -> None:
        """< 3 turns → null (insufficient data)."""
        parsed = _parsed(turns=[Turn(output_tokens=100), Turn(output_tokens=1000)])
        assert _flags(parsed)["token_snowball"] is None

    def test_zero_turns_returns_none(self) -> None:
        """No turns at all → null."""
        assert _flags(_parsed(turns=[]))["token_snowball"] is None

    def test_zero_avg_first_three_returns_none(self) -> None:
        """avg(first 3) == 0 → null (division guard)."""
        parsed = _parsed(turns=[
            Turn(output_tokens=0),
            Turn(output_tokens=0),
            Turn(output_tokens=0),
            Turn(output_tokens=999),
        ])
        assert _flags(parsed)["token_snowball"] is None

    def test_configurable_factor_changes_outcome(self) -> None:
        """snowball_factor from thresholds alters the trip point."""
        # 4 turns; avg_first_3 = 100; last = 500
        # factor=2.0 → threshold=800 → 500 < 800 → False
        # factor=0.5 → threshold=200 → 500 > 200 → True
        parsed = _parsed(turns=[
            Turn(output_tokens=100),
            Turn(output_tokens=100),
            Turn(output_tokens=100),
            Turn(output_tokens=500),
        ])
        assert _flags(parsed, thresholds=AdversarialThresholds(snowball_factor=2.0))["token_snowball"] is False
        assert _flags(parsed, thresholds=AdversarialThresholds(snowball_factor=0.5))["token_snowball"] is True

    def test_uses_num_turns_not_three_in_formula(self) -> None:
        """Formula scales by num_turns, not a hardcoded 3.

        5 turns; avg_first_3 = 100; factor=2.0
        threshold = 5 × 100 × 2.0 = 1000
        max_turn = 950 < 1000 → False

        With the old '×3' formula:  3 × 100 × 2.0 = 600 → 950 > 600 → True
        This test confirms the new formula is in use.
        """
        parsed = _parsed(turns=[
            Turn(output_tokens=100),
            Turn(output_tokens=100),
            Turn(output_tokens=100),
            Turn(output_tokens=100),
            Turn(output_tokens=950),
        ])
        assert _flags(parsed)["token_snowball"] is False


# ── talkative_failure ──────────────────────────────────────────────────────────


class TestTalkativeFailure:
    """talkative_failure: output_tokens > threshold AND correct == False."""

    def test_fires_on_verbose_wrong_answer(self) -> None:
        """output > 1000 AND correct=False → True."""
        parsed = _parsed(turns=[Turn(output_tokens=1500)])
        assert _flags(parsed, correct=False)["talkative_failure"] is True

    def test_does_not_fire_when_correct(self) -> None:
        """Verbose output but correct=True → False."""
        parsed = _parsed(turns=[Turn(output_tokens=1500)])
        assert _flags(parsed, correct=True)["talkative_failure"] is False

    def test_does_not_fire_below_threshold(self) -> None:
        """output <= threshold AND correct=False → False."""
        parsed = _parsed(turns=[Turn(output_tokens=999)])
        assert _flags(parsed, correct=False)["talkative_failure"] is False

    def test_at_boundary_does_not_fire(self) -> None:
        """output == 1000 (not >) AND correct=False → False."""
        parsed = _parsed(turns=[Turn(output_tokens=1000)])
        assert _flags(parsed, correct=False)["talkative_failure"] is False

    def test_none_when_correctness_unknown(self) -> None:
        """correct=None → null (correctness unavailable)."""
        parsed = _parsed(turns=[Turn(output_tokens=1500)])
        assert _flags(parsed, correct=None)["talkative_failure"] is None

    def test_configurable_threshold(self) -> None:
        """talkative_tokens threshold from thresholds object is respected."""
        parsed = _parsed(turns=[Turn(output_tokens=500)])
        # default 1000 → doesn't fire
        assert _flags(parsed, correct=False)["talkative_failure"] is False
        # threshold=400 → 500 > 400 and wrong → fires
        assert _flags(
            parsed, correct=False,
            thresholds=AdversarialThresholds(talkative_tokens=400),
        )["talkative_failure"] is True

    def test_uses_total_output_tokens_across_turns(self) -> None:
        """output_tokens is the sum across all turns."""
        parsed = _parsed(turns=[
            Turn(output_tokens=600),
            Turn(output_tokens=600),  # total = 1200 > 1000
        ])
        assert _flags(parsed, correct=False)["talkative_failure"] is True


# ── tool_storm ─────────────────────────────────────────────────────────────────


class TestToolStorm:
    """tool_storm: num_tool_calls > threshold."""

    def test_fires_above_threshold(self) -> None:
        """51 tool calls with threshold=50 → True."""
        calls = [ToolCall(name="bash") for _ in range(51)]
        parsed = _parsed(tool_calls=calls)
        assert _flags(parsed)["tool_storm"] is True

    def test_does_not_fire_at_threshold(self) -> None:
        """Exactly 50 calls → False (not >)."""
        calls = [ToolCall(name="bash") for _ in range(50)]
        parsed = _parsed(tool_calls=calls)
        assert _flags(parsed)["tool_storm"] is False

    def test_does_not_fire_below_threshold(self) -> None:
        """10 tool calls → False."""
        calls = [ToolCall(name="bash") for _ in range(10)]
        parsed = _parsed(tool_calls=calls)
        assert _flags(parsed)["tool_storm"] is False

    def test_configurable_threshold(self) -> None:
        """tool_storm_calls threshold from thresholds object is respected."""
        calls = [ToolCall(name="bash") for _ in range(25)]
        parsed = _parsed(tool_calls=calls)
        # default 50 → doesn't fire
        assert _flags(parsed)["tool_storm"] is False
        # threshold=20 → 25 > 20 → fires
        assert _flags(
            parsed,
            thresholds=AdversarialThresholds(tool_storm_calls=20),
        )["tool_storm"] is True


# ── budget_exhausted ───────────────────────────────────────────────────────────


class TestBudgetExhausted:
    """budget_exhausted: cost >= budget AND result_text empty/None."""

    def test_fires_when_cost_at_budget_and_empty_result(self) -> None:
        """cost == budget AND result_text="" → True."""
        parsed = _parsed(result_text="")
        assert _flags(parsed, total_cost_usd=1.0, budget_usd=1.0)["budget_exhausted"] is True

    def test_fires_when_cost_exceeds_budget_and_empty_result(self) -> None:
        """cost > budget AND result_text="" → True."""
        parsed = _parsed(result_text="")
        assert _flags(parsed, total_cost_usd=1.5, budget_usd=1.0)["budget_exhausted"] is True

    def test_does_not_fire_when_result_present(self) -> None:
        """cost >= budget but result_text non-empty → False."""
        parsed = _parsed(result_text="here is the answer")
        assert _flags(parsed, total_cost_usd=1.0, budget_usd=1.0)["budget_exhausted"] is False

    def test_does_not_fire_when_cost_below_budget(self) -> None:
        """cost < budget AND empty result → False."""
        parsed = _parsed(result_text="")
        assert _flags(parsed, total_cost_usd=0.5, budget_usd=1.0)["budget_exhausted"] is False

    def test_none_when_budget_usd_is_none(self) -> None:
        """budget_usd=None → null (no cap configured)."""
        parsed = _parsed(result_text="")
        assert _flags(parsed, total_cost_usd=99.0, budget_usd=None)["budget_exhausted"] is None


# ── timeout ────────────────────────────────────────────────────────────────────


class TestTimeout:
    """timeout: duration_ms >= timeout_seconds * 1000 (existing, verify still works)."""

    def test_fires_when_duration_at_limit(self) -> None:
        """duration == timeout_seconds * 1000 → True."""
        parsed = _parsed(duration_ms=300_000)
        assert _flags(parsed, timeout_seconds=300)["timeout"] is True

    def test_fires_when_duration_exceeds_limit(self) -> None:
        """duration > timeout_seconds * 1000 → True."""
        parsed = _parsed(duration_ms=300_001)
        assert _flags(parsed, timeout_seconds=300)["timeout"] is True

    def test_does_not_fire_below_limit(self) -> None:
        parsed = _parsed(duration_ms=299_999)
        assert _flags(parsed, timeout_seconds=300)["timeout"] is False


# ── Scenario.adversarial_thresholds model ─────────────────────────────────────


class TestAdversarialThresholdsModel:
    """AdversarialThresholds pydantic sub-model has correct defaults and validates."""

    def test_defaults(self) -> None:
        t = AdversarialThresholds()
        assert t.snowball_factor == 2.0
        assert t.talkative_tokens == 1000
        assert t.tool_storm_calls == 50

    def test_scenario_carries_thresholds_with_defaults(self) -> None:
        s = Scenario(name="s", tasks=["t1"])
        assert s.adversarial_thresholds.snowball_factor == 2.0

    def test_scenario_accepts_custom_thresholds(self) -> None:
        s = Scenario(
            name="s",
            tasks=["t1"],
            adversarial_thresholds={"snowball_factor": 3.0, "talkative_tokens": 500},
        )
        assert s.adversarial_thresholds.snowball_factor == 3.0
        assert s.adversarial_thresholds.talkative_tokens == 500
        assert s.adversarial_thresholds.tool_storm_calls == 50  # default preserved


# ── Budget threading via run_single ───────────────────────────────────────────


class TestBudgetInRunSingle:
    """run_single(budget_usd=...) threads budget into adversarial_flags."""

    def test_budget_param_accepted(self) -> None:
        """run_single accepts budget_usd kwarg without error (signature check).

        We inspect the signature rather than running the full pipeline because
        the pipeline requires a real repo. The integration path is covered by
        TestBudgetExhausted above via _compute_adversarial_flags directly.
        """
        import inspect
        from copeca.orchestration.run import run_single

        sig = inspect.signature(run_single)
        assert "budget_usd" in sig.parameters
        param = sig.parameters["budget_usd"]
        assert param.default is None  # default is None (optional)
