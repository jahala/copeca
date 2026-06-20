"""Decisive, network-free proof that a built wheel ships its runtime data.

Builds the wheel with ``--no-isolation`` (reuses the current env's setuptools, so
no PyPI download), then inspects the wheel ZIP directly: the ``copeca/data/`` tree
(schemas, default modes + runners, task corpus) must be inside the archive. This
is the assertion that F-H6c was about — a pip-installed copy must carry its data.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def wheel_members(tmp_path_factory) -> list[str]:
    """Build the wheel without network and return its archive member names."""
    pytest.importorskip("build", reason="`build` not installed; cannot build wheel")

    dist = tmp_path_factory.mktemp("dist")
    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(dist)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"wheel build failed (exit {result.returncode}):\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )

    wheels = list(dist.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, got {wheels}"

    with zipfile.ZipFile(wheels[0]) as zf:
        return zf.namelist()


def test_wheel_bundles_schema(wheel_members: list[str]) -> None:
    """The task JSON Schema is inside the wheel."""
    assert "copeca/data/schemas/task.schema.json" in wheel_members


def test_wheel_bundles_default_mode(wheel_members: list[str]) -> None:
    """A default mode YAML is inside the wheel."""
    assert "copeca/data/defaults/modes/baseline.yaml" in wheel_members


def test_wheel_bundles_runner_pricing(wheel_members: list[str]) -> None:
    """The runner pricing YAML is inside the wheel."""
    assert "copeca/data/defaults/runners/claude.yaml" in wheel_members


def test_wheel_bundles_task_corpus(wheel_members: list[str]) -> None:
    """At least one task YAML from the corpus is inside the wheel."""
    corpus = [
        m
        for m in wheel_members
        if m.startswith("copeca/data/tasks/") and m.endswith(".yaml")
    ]
    assert corpus, f"no task YAML found in wheel; members: {wheel_members}"
