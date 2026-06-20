"""Test copeca domain models — Pydantic dataclasses for Task, Repo, Mode, etc.

These are pure unit tests: no I/O, no subprocess, no filesystem.
"""

import pytest
from pydantic import ValidationError

from copeca.config.models import (
    ComprehensionGroundTruth,
    Difficulty,
    EditGroundTruth,
    Language,
    Mutation,
    MutationAction,
    Repo,
    Task,
    TaskType,
)


class TestTaskConstruction:
    """Task(name, description, source, repo, ...) constructs with all fields."""

    def test_valid_comprehension_task(self):
        task = Task(
            name="rg_trait_implementors",
            description="Find all implementors of the Matcher trait",
            source="SWE-QA (Apache-2.0)",
            repo="ripgrep",
            type=TaskType.comprehension,
            language=Language.rust,
            difficulty=Difficulty.hard,
            version=1,
            prompt="Find the Matcher trait...",
            ground_truth=ComprehensionGroundTruth(
                required_strings=["Matcher", "find_at"],
                all_of=["RegexMatcher", "GlobMatcher", "MultiMatcher"],
                forbidden_strings=["I cannot"],
            ),
        )
        assert task.name == "rg_trait_implementors"
        assert task.type == TaskType.comprehension
        assert isinstance(task.ground_truth, ComprehensionGroundTruth)
        assert task.ground_truth.required_strings == ["Matcher", "find_at"]

    def test_valid_edit_task(self):
        task = Task(
            name="rg_edit_line_count",
            description="Fix off-by-one in line counting",
            source="tilth-benchmark (MIT)",
            repo="ripgrep",
            type=TaskType.edit,
            language=Language.rust,
            difficulty=Difficulty.medium,
            version=1,
            prompt="There is a bug in ripgrep's line counting...",
            ground_truth=EditGroundTruth(
                required_strings=[],
                forbidden_strings=[],
                test_command=["cargo", "test", "-p", "grep-searcher", "line_count"],
            ),
            mutations=[
                Mutation(
                    file="crates/searcher/src/lines.rs",
                    find="memchr::memchr_iter(line_term, bytes).count() as u64",
                    replace="memchr::memchr_iter(line_term, bytes).count() as u64 + 1",
                )
            ],
        )
        assert task.type == TaskType.edit
        assert isinstance(task.ground_truth, EditGroundTruth)
        assert task.ground_truth.test_command[-1] == "line_count"
        assert len(task.mutations) == 1

    def test_name_must_be_non_empty(self):
        with pytest.raises(ValidationError, match="name"):
            Task(
                name="",
                description="test",
                source="test",
                repo="test",
                type=TaskType.comprehension,
                language=Language.python,
                difficulty=Difficulty.easy,
                version=1,
                prompt="test",
                ground_truth=ComprehensionGroundTruth(required_strings=["test"]),
            )

    def test_name_must_match_pattern(self):
        with pytest.raises(ValidationError, match="name"):
            Task(
                name="Invalid Name!",
                description="test",
                source="test",
                repo="test",
                type=TaskType.comprehension,
                language=Language.python,
                difficulty=Difficulty.easy,
                version=1,
                prompt="test",
                ground_truth=ComprehensionGroundTruth(required_strings=["test"]),
            )

    def test_source_must_be_non_empty(self):
        with pytest.raises(ValidationError, match="source"):
            Task(
                name="valid_name",
                description="test",
                source="",
                repo="test",
                type=TaskType.comprehension,
                language=Language.python,
                difficulty=Difficulty.easy,
                version=1,
                prompt="test",
                ground_truth=ComprehensionGroundTruth(required_strings=["test"]),
            )


class TestRepoConstruction:
    """Repo(url, commit, language, toolchain, setup_command) constructs."""

    def test_valid_repo(self):
        repo = Repo(
            url="https://github.com/BurntSushi/ripgrep.git",
            commit="0a88cccd5188074de96f54a4b6b44a63971ac157",
            language=Language.rust,
            toolchain={"rust": "1.80.0"},
            setup_command=["cargo", "fetch"],
        )
        assert repo.url == "https://github.com/BurntSushi/ripgrep.git"
        assert repo.toolchain == {"rust": "1.80.0"}

    def test_url_must_be_non_empty(self):
        with pytest.raises(ValidationError, match="url"):
            Repo(url="", commit="abc123", language=Language.rust)

    def test_commit_must_be_non_empty(self):
        with pytest.raises(ValidationError, match="commit"):
            Repo(url="https://example.com/repo.git", commit="", language=Language.rust)


class TestMutation:
    """Mutation covers all action types."""

    def test_replace_action(self):
        m = Mutation(
            file="src/lib.rs",
            find="old_code",
            replace="new_code",
        )
        assert m.action == MutationAction.replace
        assert m.find == "old_code"

    def test_delete_action(self):
        m = Mutation(
            file="src/lib.rs",
            action="delete",
            find="remove this line",
        )
        assert m.action == MutationAction.delete

    def test_insert_after_action(self):
        m = Mutation(
            file="src/lib.rs",
            action="insert_after",
            find="existing line",
            content="new line to insert",
        )
        assert m.action == MutationAction.insert_after

    def test_create_action(self):
        m = Mutation(
            file="src/new_test.rs",
            action="create",
            content="#[test]\nfn new_test() {}",
        )
        assert m.action == MutationAction.create
        assert m.content == "#[test]\nfn new_test() {}"
