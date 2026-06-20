"""Test mutation engine — apply/revert with all action types."""

import pytest

from copeca.config.models import Mutation
from copeca.tasks.mutations import MutationError, apply_mutations


class TestApplyReplace:
    def test_find_and_replace(self, tmp_path):
        f = tmp_path / "test.rs"
        f.write_text("fn foo() { return 1; }")
        m = Mutation(file=str(f), find="return 1", replace="return 2")
        apply_mutations([m])
        assert "return 2" in f.read_text()

    def test_unmatched_find_raises(self, tmp_path):
        f = tmp_path / "test.rs"
        f.write_text("fn foo() { return 1; }")
        m = Mutation(file=str(f), find="not here")
        with pytest.raises(MutationError):
            apply_mutations([m])

    def test_occurrence_selects_correct_match(self, tmp_path):
        f = tmp_path / "test.rs"
        f.write_text("x = 1\ny = 1\nz = 1")
        m = Mutation(file=str(f), find="= 1", replace="= 2", occurrence=2)
        apply_mutations([m])
        lines = f.read_text().split("\n")
        assert "x = 1" in lines[0]
        assert "y = 2" in lines[1]


class TestApplyDelete:
    def test_deletes_line(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("keep\nremove\nkeep")
        m = Mutation(file=str(f), action="delete", find="remove")
        apply_mutations([m])
        result = f.read_text()
        assert "remove" not in result
        assert "keep" in result

    def test_unmatched_delete_raises(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("keep\nkeep\nkeep")
        m = Mutation(file=str(f), action="delete", find="remove")
        with pytest.raises(MutationError, match="Delete target not found"):
            apply_mutations([m])


class TestApplyInsertAfter:
    def test_inserts_after_found_line(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line one\nline two")
        m = Mutation(file=str(f), action="insert_after", find="line one", content="inserted")
        apply_mutations([m])
        lines = f.read_text().split("\n")
        assert lines[0] == "line one"
        assert lines[1] == "inserted"

    def test_unmatched_insert_raises(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line one\nline two")
        m = Mutation(file=str(f), action="insert_after", find="not here", content="nope")
        with pytest.raises(MutationError, match="Insert target not found"):
            apply_mutations([m])


class TestApplyCreate:
    def test_creates_new_file(self, tmp_path):
        new_file = tmp_path / "new.rs"
        m = Mutation(file=str(new_file), action="create", content="#[test]\nfn test() {}")
        apply_mutations([m])
        assert new_file.exists()
        assert "fn test" in new_file.read_text()
