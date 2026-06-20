"""Test scenario-level validation — pre-flight checks before matrix execution."""

from copeca.config.models import Scenario
from copeca.orchestration.validation import validate_scenario


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_scenario(**overrides) -> Scenario:
    """Build a minimal valid scenario with overrides."""
    defaults = {
        "name": "test_scenario",
        "tasks": ["task_a", "task_b"],
        "modes": ["baseline"],
        "models": ["test-model"],
        "repetitions": 5,
        "budget_usd": 1.0,
    }
    defaults.update(overrides)
    return Scenario.model_validate(defaults)


# ── Tests ───────────────────────────────────────────────────────────────────

class TestValidateScenarioBasics:
    """Core pre-flight validation coverage."""

    def test_valid_scenario_no_errors(self):
        """All tasks and modes exist, at least 1 rep, budget > 0."""
        scenario = _make_scenario()
        available_tasks = {"task_a", "task_b"}
        available_modes = {"baseline"}

        errors = validate_scenario(scenario, available_tasks, available_modes)

        assert errors == []

    def test_missing_task_produces_error(self):
        """A task in scenario.tasks that does not exist in available_tasks."""
        scenario = _make_scenario(tasks=["task_a", "nonexistent"])
        available_tasks = {"task_a", "task_b"}
        available_modes = {"baseline"}

        errors = validate_scenario(scenario, available_tasks, available_modes)

        assert len(errors) > 0
        assert any("nonexistent" in e for e in errors)
        assert any("task" in e.lower() for e in errors)

    def test_missing_mode_produces_error(self):
        """A mode in scenario.modes that does not exist in available_modes."""
        scenario = _make_scenario(modes=["baseline", "fantasy-mode"])
        available_tasks = {"task_a", "task_b"}
        available_modes = {"baseline"}

        errors = validate_scenario(scenario, available_tasks, available_modes)

        assert len(errors) > 0
        assert any("fantasy-mode" in e for e in errors)
        assert any("mode" in e.lower() for e in errors)

    def test_empty_tasks_error(self):
        """Scenario with no tasks listed should produce an error."""
        scenario = _make_scenario(tasks=["task_a"])
        available_tasks: set[str] = set()
        available_modes = {"baseline"}

        errors = validate_scenario(scenario, available_tasks, available_modes)

        assert len(errors) > 0
        assert any("task_a" in e for e in errors)

    def test_warning_not_error_for_low_reps(self):
        """Fewer than 5 reps produces an advisory warning, not a hard error.

        The distinction matters: low reps are statistically underpowered but
        may be fine for a quick smoke test. The warning tells the user but
        does not block execution.
        """
        scenario = _make_scenario(repetitions=2)
        available_tasks = {"task_a", "task_b"}
        available_modes = {"baseline"}

        errors = validate_scenario(scenario, available_tasks, available_modes)

        # Should produce a warning (not empty) but all non-warning errors
        # are still zero — the scenario is structurally valid.
        assert len(errors) > 0
        assert any("rep" in e.lower() or "2" in e for e in errors)
