"""Test `copeca validate` CLI command end-to-end."""

import subprocess
import tempfile
from pathlib import Path

import yaml

from copeca.config.resources import data_path

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
VALID_DIR = FIXTURES / "valid_tasks"
INVALID_DIR = FIXTURES / "invalid"
FIXTURE_REPOS = FIXTURES / "repos.yaml"
INVALID_REPO_DIR = FIXTURES / "invalid_repo_only"
BLOCKED_SOURCE_DIR = FIXTURES / "blocked_source"


def copeca(*args):
    """Run copeca CLI via the installed entry point and return CompletedProcess."""
    return subprocess.run(
        ["copeca", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_default_pricing_yaml_parseable():
    """Bug 2: verify that defaults/runners/claude.yaml loads and has pricing models."""
    pricing_path = data_path("defaults", "runners", "claude.yaml")
    assert pricing_path.exists(), f"Missing pricing file: {pricing_path}"

    with open(pricing_path) as f:
        doc = yaml.safe_load(f)

    assert isinstance(doc, dict), "Expected YAML mapping"
    assert "pricing" in doc, "Missing 'pricing' key in claude.yaml"

    pricing = doc["pricing"]
    assert isinstance(pricing, dict), "'pricing' must be a mapping"

    # Verify at least one known model is present
    model_ids = list(pricing.keys())
    assert len(model_ids) > 0, "No models in pricing"

    # Verify each model has required pricing fields
    required_fields = {"input", "output", "cache_creation", "cache_read"}
    for model_id in model_ids:
        model_pricing = pricing[model_id]
        missing = required_fields - set(model_pricing.keys())
        assert not missing, f"Model '{model_id}' missing pricing fields: {missing}"


class TestValidateCommand:
    """copeca validate catches errors and passes valid tasks."""

    def test_valid_dir_exits_zero(self):
        result = copeca("validate", str(VALID_DIR))
        assert result.returncode == 0, f"stdout={result.stdout} stderr={result.stderr}"

    def test_invalid_dir_exits_nonzero(self):
        result = copeca("validate", str(INVALID_DIR))
        assert result.returncode != 0
        assert "source" in (result.stderr + result.stdout)

    def test_nonexistent_dir_exits_two(self):
        result = copeca("validate", "nonexistent_dir")
        assert result.returncode == 2, f"expected exit 2, got {result.returncode}"

    def test_validate_with_repos_passes_known_repo(self):
        """Bug 1: validate with --repos flag succeeds when task references known repo."""
        result = copeca("validate", str(VALID_DIR), "--repos", str(FIXTURE_REPOS))
        assert result.returncode == 0, f"stdout={result.stdout} stderr={result.stderr}"

    def test_validate_with_repos_catches_unknown_repo(self):
        """Bug 1: validate fails when a task references a repo not in repos.yaml."""
        result = copeca("validate", str(INVALID_REPO_DIR), "--repos", str(FIXTURE_REPOS))
        assert result.returncode != 0
        combined = result.stderr + result.stdout
        assert "nonexistent-repo-abc123" in combined, (
            f"Expected unknown repo error, got: {combined}"
        )

    def test_validate_flags_blocked_source_benchmark(self):
        """validate warns (or fails) when a task's source is a blocked benchmark."""
        result = copeca("validate", str(BLOCKED_SOURCE_DIR))
        combined = result.stdout + result.stderr
        # Must surface the contamination finding — either via a warning or non-zero exit
        assert result.returncode != 0 or "contamination" in combined.lower() or "blocked" in combined.lower(), (
            f"Expected contamination warning or non-zero exit for blocked source task, "
            f"got returncode={result.returncode}, output={combined!r}"
        )

    def test_validate_clean_dir_passes_provenance_check(self):
        """validate on a clean dir (no blocked sources) passes provenance check."""
        result = copeca("validate", str(VALID_DIR))
        assert result.returncode == 0, (
            f"Clean dir should pass provenance check: stdout={result.stdout} stderr={result.stderr}"
        )

    def test_validate_flags_blocked_source_from_arbitrary_cwd(self):
        """validate flags a blocked source task even when run from a tmp cwd with no local blocklist.

        This is the regression test for the silent no-op: the packaged blocklist
        (src/copeca/data/contamination_blocklist.txt) must be used when no local
        scripts/contamination_blocklist.txt is present.
        """
        with tempfile.TemporaryDirectory() as tmp_cwd:
            # Confirm there is no local blocklist in this tmp dir
            assert not (Path(tmp_cwd) / "scripts" / "contamination_blocklist.txt").exists()
            result = subprocess.run(
                ["copeca", "validate", str(BLOCKED_SOURCE_DIR)],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=tmp_cwd,
            )
        combined = result.stdout + result.stderr
        assert result.returncode != 0 or "contamination" in combined.lower() or "blocked" in combined.lower(), (
            f"Expected contamination rejection from packaged blocklist when run from tmp cwd "
            f"(no local blocklist), got returncode={result.returncode}, output={combined!r}"
        )


def test_packaged_blocklist_exists():
    """The contamination blocklist is bundled inside the package (ships in the wheel).

    This pins the fix: data_path('contamination_blocklist.txt') must resolve to a
    real file so validate always runs the provenance check regardless of cwd.
    """
    blocklist = data_path("contamination_blocklist.txt")
    assert blocklist.exists(), (
        f"Packaged contamination_blocklist.txt not found at {blocklist}. "
        "The file must be at src/copeca/data/contamination_blocklist.txt so it ships in the wheel."
    )
