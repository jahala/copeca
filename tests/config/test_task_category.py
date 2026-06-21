"""Category taxonomy — the capability axis (locate/trace/fix/debug).

`category` is orthogonal to `type`: `type` decides grading (comprehension→strings,
edit→test exit); `category` is the analysis lens for the per-capability cost-per-correct
delta. A consistency invariant ties them: comprehension⟹{locate,trace,debug},
edit⟹{fix,debug} (debug spans both: explain-a-diff is comprehension+debug, find+fix
a regression is edit+debug).
"""

import pytest
from pydantic import ValidationError

from copeca.config.loader import load_tasks_from_dir
from copeca.config.models import (
    Category,
    ComprehensionGroundTruth,
    Difficulty,
    EditGroundTruth,
    Language,
    Task,
    TaskType,
)
from copeca.config.resources import data_path


def _task(**over):
    base = dict(
        name="t",
        source="s",
        repo="r",
        type=TaskType.comprehension,
        language=Language.python,
        difficulty=Difficulty.easy,
        version=1,
        prompt="p",
        ground_truth=ComprehensionGroundTruth(required_strings=["x"]),
        category=Category.locate,
    )
    base.update(over)
    return Task(**base)


class TestCategoryEnum:
    def test_has_exactly_four_values(self):
        assert {c.value for c in Category} == {"locate", "trace", "fix", "debug"}


class TestCategoryRequired:
    def test_category_is_required(self):
        with pytest.raises(ValidationError):
            Task(
                name="t",
                source="s",
                repo="r",
                type=TaskType.comprehension,
                language=Language.python,
                difficulty=Difficulty.easy,
                version=1,
                prompt="p",
                ground_truth=ComprehensionGroundTruth(required_strings=["x"]),
            )


class TestTypeCategoryInvariant:
    def test_comprehension_allows_locate_trace_debug(self):
        for c in (Category.locate, Category.trace, Category.debug):
            _task(
                type=TaskType.comprehension,
                category=c,
                ground_truth=ComprehensionGroundTruth(required_strings=["x"]),
            )

    def test_comprehension_rejects_fix(self):
        with pytest.raises(ValidationError):
            _task(
                type=TaskType.comprehension,
                category=Category.fix,
                ground_truth=ComprehensionGroundTruth(required_strings=["x"]),
            )

    def test_edit_allows_fix_and_debug(self):
        for c in (Category.fix, Category.debug):
            _task(
                type=TaskType.edit,
                category=c,
                ground_truth=EditGroundTruth(test_command=["true"]),
            )

    def test_edit_rejects_locate(self):
        with pytest.raises(ValidationError):
            _task(
                type=TaskType.edit,
                category=Category.locate,
                ground_truth=EditGroundTruth(test_command=["true"]),
            )


class TestPackagedTasksCategorized:
    def test_all_packaged_tasks_carry_a_valid_category(self):
        """Every shipped task validates (schema + model) with a Category — so the
        per-category report never sees an untagged record."""
        tasks = load_tasks_from_dir(data_path("tasks"))
        assert len(tasks) >= 16
        for t in tasks:
            assert isinstance(t.category, Category), f"{t.name} missing category"
