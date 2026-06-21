"""Verify that required documentation files exist and contain expected content."""

from __future__ import annotations

from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "docs"


class TestDocsExist:
    def test_readme_exists(self) -> None:
        readme = DOCS_DIR.parent / "README.md"
        assert readme.exists()

    def test_architecture_doc_exists(self) -> None:
        assert (DOCS_DIR / "architecture.md").exists()

    def test_engineering_doc_exists(self) -> None:
        assert (DOCS_DIR / "engineering.md").exists()

    def test_metrics_doc_exists(self) -> None:
        assert (DOCS_DIR / "metrics.md").exists()

    def test_methodology_doc_exists(self) -> None:
        assert (DOCS_DIR / "methodology.md").exists()

    def test_task_authoring_doc_exists(self) -> None:
        assert (DOCS_DIR / "task-authoring.md").exists()

    def test_runner_configuration_doc_exists(self) -> None:
        assert (DOCS_DIR / "runner-configuration.md").exists()

    def test_known_limitations_doc_exists(self) -> None:
        assert (DOCS_DIR / "known-limitations.md").exists()

    def test_readme_has_quick_start(self) -> None:
        readme = DOCS_DIR.parent / "README.md"
        content = readme.read_text()
        assert "copeca" in content
        assert "validate" in content or "run" in content

    def test_metrics_doc_defines_cost_per_correct(self) -> None:
        content = (DOCS_DIR / "metrics.md").read_text()
        assert "cost per correct" in content.lower() or "cost_per_correct" in content.lower()

    def test_methodology_mentions_delta(self) -> None:
        content = (DOCS_DIR / "methodology.md").read_text()
        assert "delta" in content.lower()

    def test_task_authoring_contains_required_strings(self) -> None:
        content = (DOCS_DIR / "task-authoring.md").read_text()
        assert "required_strings" in content

    def test_runner_config_contains_subprocess_runner(self) -> None:
        content = (DOCS_DIR / "runner-configuration.md").read_text()
        assert "SubprocessRunner" in content

    def test_known_limitations_contains_bootstrap(self) -> None:
        content = (DOCS_DIR / "known-limitations.md").read_text()
        assert "bootstrap" in content.lower()
