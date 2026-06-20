"""Test cross-document repo reference validation."""

from pathlib import Path

import pytest

from copeca.config.loader import SchemaValidationError, load_repos, load_task
from copeca.config.models import Repo

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
REPOS_YAML = FIXTURES / "repos.yaml"


class TestLoadRepos:
    """load_repos reads repos.yaml and returns Repo dict."""

    def test_loads_repos(self):
        repos = load_repos(REPOS_YAML)
        assert "ripgrep" in repos
        assert isinstance(repos["ripgrep"], Repo)
        assert repos["ripgrep"].url.startswith("https://github.com")

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_repos(Path("nonexistent.yaml"))


class TestRepoValidation:
    """load_task validates repo references against loaded repos."""

    def test_known_repo_validates(self):
        repos = load_repos(REPOS_YAML)
        task = load_task(
            FIXTURES / "tasks" / "task_with_known_repo.yaml",
            repos=repos,
        )
        assert task.name == "rg_trait_implementors"

    def test_missing_repo_raises(self):
        repos = load_repos(REPOS_YAML)
        with pytest.raises(SchemaValidationError, match="nonexistent_repo"):
            load_task(
                FIXTURES / "tasks" / "task_with_missing_repo.yaml",
                repos=repos,
            )
