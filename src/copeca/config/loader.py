"""Config loader — YAML deserialization + jsonschema validation + Pydantic coercion.

Architecture: domain layer. This file must never import from runners/, repos/,
results/, or orchestration/.
"""

import json
from pathlib import Path

import yaml
from jsonschema import ValidationError as JsonschemaValidationError
from jsonschema import validate

from copeca.config.models import Mode, Repo, Scenario, Task


class LoadError(Exception):
    """Raised when a task file cannot be loaded — malformed YAML, I/O error."""

    def __init__(self, path: Path, message: str):
        self.path = path
        super().__init__(f"{path}: {message}")


class SchemaValidationError(LoadError):
    """Raised when a task YAML fails jsonschema validation."""

    def __init__(self, path: Path, message: str):
        super().__init__(path, message)


_SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent.parent / "schemas" / "task.schema.json"

# Load schema once at module level
with open(_SCHEMA_PATH) as f:
    TASK_SCHEMA = json.load(f)


def load_task(path: Path, repos: dict[str, Repo] | None = None) -> Task:
    """Load a single task YAML file, validate against JSON Schema, and
    construct a Pydantic Task model.

    Args:
        path: Path to a .yaml file containing a copeca task definition.

    Returns:
        A validated Task model instance.

    Raises:
        FileNotFoundError: If the path does not exist.
        LoadError: If the YAML is malformed or unparseable.
        SchemaValidationError: If the YAML fails JSON Schema validation.
        pydantic.ValidationError: If the YAML passes schema but fails Pydantic
            model validation (e.g., conditional constraints like 'edit requires
            test_command').
    """
    if not path.exists():
        raise FileNotFoundError(f"Task file not found: {path}")

    try:
        with open(path) as f:
            doc = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise LoadError(path, f"YAML parse error: {e}") from e

    if not isinstance(doc, dict):
        raise LoadError(path, f"Expected a YAML mapping, got {type(doc).__name__}")

    # Layer 1: JSON Schema structural validation
    try:
        validate(doc, TASK_SCHEMA)
    except JsonschemaValidationError as e:
        raise SchemaValidationError(path, e.message) from e

    # Layer 2: Pydantic type safety + conditional constraints
    task = Task.model_validate(doc)

    # Layer 3: Cross-document repo reference validation (only when repos provided)
    if repos is not None and task.repo not in repos:
        raise SchemaValidationError(
            path,
            f"repo '{task.repo}' not found in repos.yaml. Available repos: {', '.join(sorted(repos.keys()))}",
        )

    return task


def load_tasks_from_dir(dir_path: Path, repos: dict[str, Repo] | None = None) -> list[Task]:
    """Discover and load all .yaml task files from a directory.

    Args:
        dir_path: Directory containing .yaml task definition files.
        repos: Optional dict mapping repo keys to Repo models. When provided,
               Layer 3 cross-document repo reference validation is performed.

    Returns:
        List of validated Task model instances. Non-.yaml files are skipped.
        Tasks that fail validation raise — partial loading is not supported.
    """
    if not dir_path.is_dir():
        raise FileNotFoundError(f"Not a directory: {dir_path}")

    tasks: list[Task] = []
    for file_path in sorted(dir_path.rglob("*.yaml")):
        tasks.append(load_task(file_path, repos=repos))
    return tasks


def load_repos(path: Path) -> dict[str, Repo]:
    """Load the repository registry from a YAML file.

    Args:
        path: Path to repos.yaml.

    Returns:
        Dict mapping repo keys (str) to Repo model instances.
    """
    if not path.exists():
        raise FileNotFoundError(f"Repo registry not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise LoadError(path, f"Expected a YAML mapping, got {type(raw).__name__}")

    repos: dict[str, Repo] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        repos[key] = Repo.model_validate(value)

    return repos


def load_scenario(path: Path) -> Scenario:
    """Load a scenario YAML file and validate via Pydantic.

    Args:
        path: Path to a .yaml file containing a copeca scenario definition.

    Returns:
        A validated Scenario model instance.

    Raises:
        FileNotFoundError: If the path does not exist.
        LoadError: If the YAML is malformed or unparseable.
        pydantic.ValidationError: If the YAML fails Pydantic model validation.
    """
    if not path.exists():
        raise FileNotFoundError(f"Scenario file not found: {path}")

    try:
        with open(path) as f:
            doc = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise LoadError(path, f"YAML parse error: {e}") from e

    if not isinstance(doc, dict):
        raise LoadError(path, f"Expected a YAML mapping, got {type(doc).__name__}")

    return Scenario.model_validate(doc)


def load_mode(name: str, modes_dirs: list[Path] | None = None) -> Mode:
    """Load a single mode definition by name, resolving across mode dirs.

    Args:
        name: Mode name (e.g. "baseline"). Resolved to ``<dir>/<name>.yaml``
              by searching ``modes_dirs`` in order; the first existing file wins.
        modes_dirs: Directories to search. Defaults to ``[Path("defaults/modes")]``.

    Returns:
        A validated Mode model instance.

    Raises:
        FileNotFoundError: If no ``<dir>/<name>.yaml`` exists in any modes_dir.
        LoadError: If the YAML is malformed or not a mapping.
        pydantic.ValidationError: If the YAML fails Mode model validation.
    """
    if modes_dirs is None:
        modes_dirs = [Path("defaults/modes")]

    for modes_dir in modes_dirs:
        candidate = modes_dir / f"{name}.yaml"
        if candidate.exists():
            try:
                with open(candidate) as f:
                    doc = yaml.safe_load(f)
            except yaml.YAMLError as e:
                raise LoadError(candidate, f"YAML parse error: {e}") from e

            if not isinstance(doc, dict):
                raise LoadError(
                    candidate, f"Expected a YAML mapping, got {type(doc).__name__}"
                )

            return Mode.model_validate(doc)

    searched = ", ".join(str(d / f"{name}.yaml") for d in modes_dirs)
    raise FileNotFoundError(f"Mode '{name}' not found. Searched: {searched}")


def load_modes(
    names: list[str], modes_dirs: list[Path] | None = None
) -> dict[str, Mode]:
    """Load multiple modes by name into a name -> Mode dict.

    Args:
        names: Mode names to load.
        modes_dirs: Directories to search (passed through to load_mode).

    Returns:
        Dict mapping each name to its validated Mode model.

    Raises:
        FileNotFoundError: If any name has no resolvable YAML (via load_mode).
    """
    return {name: load_mode(name, modes_dirs=modes_dirs) for name in names}
