"""Test the bundled repos.yaml registry file."""

import yaml

from copeca.config.loader import load_repos
from copeca.config.models import Repo
from copeca.config.resources import data_path

REPOS_YAML = data_path("repos.yaml")

REQUIRED_FIELDS = ("url", "commit", "language")
EXPECTED_REPOS = ("ripgrep", "fastapi", "gin", "express")


class TestReposYamlFile:
    """Sanity checks on the root repos.yaml file."""

    def test_repos_yaml_exists_and_is_valid(self):
        assert REPOS_YAML.exists(), f"{REPOS_YAML} not found"
        with open(REPOS_YAML) as f:
            doc = yaml.safe_load(f)
        assert isinstance(doc, dict), f"Expected a YAML mapping, got {type(doc).__name__}"
        assert len(doc) >= 4, f"Expected at least 4 entries, got {len(doc)}"


class TestLoadReposFromRoot:
    """load_repos can load the root repos.yaml and validate every entry."""

    def test_load_repos_succeeds(self):
        repos = load_repos(REPOS_YAML)
        assert isinstance(repos, dict), f"Expected dict, got {type(repos).__name__}"
        for key, repo in repos.items():
            assert isinstance(repo, Repo), f"Entry '{key}' is not a Repo: {type(repo).__name__}"

    def test_at_least_four_repos(self):
        repos = load_repos(REPOS_YAML)
        for name in EXPECTED_REPOS:
            assert name in repos, f"Expected repo '{name}' not found in {sorted(repos.keys())}"


class TestReposHaveRequiredFields:
    """Every repo entry passes Pydantic validation which enforces url, commit, language."""

    def test_all_repos_have_required_fields(self):
        repos = load_repos(REPOS_YAML)
        for name, repo in repos.items():
            for field in REQUIRED_FIELDS:
                assert getattr(repo, field, None), (
                    f"Repo '{name}' has empty or missing field '{field}'"
                )

    def test_commits_are_not_empty(self):
        repos = load_repos(REPOS_YAML)
        for name, repo in repos.items():
            assert repo.commit.strip(), f"Repo '{name}' has empty commit"
            assert len(repo.commit) >= 40, (
                f"Repo '{name}' commit is too short for a full SHA ({len(repo.commit)} chars)"
            )
