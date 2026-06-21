#!/usr/bin/env python3
"""Migrate tilth benchmark tasks to copeca YAML format.

Reads the tilth benchmark configuration (TASKS + REPOS dicts) and converts
each task to a copeca YAML file under `tasks/`.

Usage:
    python scripts/migrate_from_tilth.py
    python scripts/migrate_from_tilth.py --tilth-path ../tilth --output-dir tasks/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

# ── Constants ──────────────────────────────────────────────────────────────────

SOURCE_FIELD = "tilth-benchmark (MIT)"


# ── Mapping helpers ────────────────────────────────────────────────────────────


def _map_type(task: dict[str, Any]) -> str:
    raw: str = task.get("type", "comprehension")
    if raw not in ("comprehension", "edit"):
        raise ValueError(f"Unknown task type: {raw!r}")
    return raw


def _map_language(task: dict[str, Any]) -> str:
    raw: str = task.get("language", "python")
    valid = {"python", "rust", "go", "javascript"}
    if raw not in valid:
        raise ValueError(f"Unknown language: {raw!r}; valid: {sorted(valid)}")
    return raw


def _map_difficulty(task: dict[str, Any]) -> str:
    raw: str = task.get("difficulty", "medium")
    valid = {"easy", "medium", "hard"}
    if raw not in valid:
        raise ValueError(f"Unknown difficulty: {raw!r}; valid: {sorted(valid)}")
    return raw


def _map_category(task: dict[str, Any]) -> str:
    """Map to copeca's capability category (orthogonal to type).

    Prefer tilth's own finer classification when present (task_type: read/navigate/
    edit -> locate/trace/fix); otherwise derive from the copeca type. The derived
    comprehension default is ``trace``; whether a comprehension task is really
    ``locate`` (one self-contained target) vs ``trace`` (a cross-file relationship)
    should be reviewed during migration.
    """
    tilth_kind = str(task.get("task_type", "")).lower()
    if tilth_kind == "read":
        return "locate"
    if tilth_kind == "navigate":
        return "trace"
    if tilth_kind == "edit":
        return "fix"
    return "fix" if _map_type(task) == "edit" else "trace"


def _map_name(task: dict[str, Any]) -> str:
    """Ensure the task name matches copeca's naming pattern: ^[a-z][a-z0-9_]*$."""
    import re

    name: str = task.get("name", "") or str(task.get("prompt", "unnamed"))[:30]
    name = name.lower().replace(" ", "_").replace("-", "_")
    name = re.sub(r"[^a-z0-9_]", "", name)
    if not name:
        name = "unnamed_task"
    if not re.match(r"^[a-z]", name):
        name = "t_" + name
    return name


def _build_ground_truth(task: dict[str, Any]) -> dict[str, Any]:
    """Build the copeca ground_truth dict from a tilth task."""
    gt = task.get("ground_truth", {})
    required_strings = gt.get("required_strings", [])
    forbidden_strings = gt.get("forbidden_strings", [])
    all_of = gt.get("all_of", [])
    test_command = gt.get("test_command", []) or task.get("test_command", [])

    result: dict[str, Any] = {
        "required_strings": required_strings if isinstance(required_strings, list) else [],
        "forbidden_strings": forbidden_strings if isinstance(forbidden_strings, list) else [],
    }

    task_type = _map_type(task)
    if task_type == "comprehension":
        result["all_of"] = all_of if isinstance(all_of, list) else []
    elif task_type == "edit":
        result["test_command"] = test_command if isinstance(test_command, list) else []

    return result


def _build_mutations(task: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert tilth mutations to copeca-compatible mutation dicts."""
    raw_mutations = task.get("mutations", [])
    if not isinstance(raw_mutations, list):
        return []

    result: list[dict[str, Any]] = []
    for m in raw_mutations:
        if not isinstance(m, dict):
            continue
        entry: dict[str, Any] = {"file": str(m.get("file", ""))}
        if not entry["file"]:
            continue

        find_val: str = str(m.get("find", ""))
        replace_val: str = str(m.get("replace", ""))
        content_val: str = str(m.get("content", ""))
        action_val: str = str(m.get("action", "replace"))

        if action_val == "replace":
            if not find_val:
                continue
            entry["action"] = "replace"
            entry["find"] = find_val
            entry["replace"] = replace_val
        elif action_val == "delete":
            if not find_val:
                continue
            entry["action"] = "delete"
            entry["find"] = find_val
        elif action_val in ("insert_after", "create"):
            if not content_val:
                continue
            entry["action"] = action_val
            if find_val:
                entry["find"] = find_val
            entry["content"] = content_val
        else:
            # Unknown action, try to treat as replace with find
            if find_val:
                entry["action"] = "replace"
                entry["find"] = find_val
                entry["replace"] = replace_val
            else:
                continue

        occurrence = m.get("occurrence")
        if occurrence is not None and isinstance(occurrence, int) and occurrence >= 1:
            entry["occurrence"] = occurrence

        result.append(entry)
    return result


# ── Validation helpers ─────────────────────────────────────────────────────────


def _is_valid_copeca_task(task_dict: dict[str, Any]) -> bool:
    """Check if a task dict would pass copeca's minimal validation."""
    from pydantic import ValidationError

    from copeca.config.models import Task  # type: ignore[import-untyped]

    try:
        Task.model_validate(task_dict)
        return True
    except ValidationError:
        return False


def _emit_yaml(task_dict: dict[str, Any], output_path: Path) -> None:
    """Write a task dict to a YAML file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump(
            task_dict,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )


# ── Migration ──────────────────────────────────────────────────────────────────


def migrate(tilth_path: Path, output_dir: Path) -> dict[str, int]:
    """Convert tilth benchmark tasks to copeca YAML files.

    Returns a summary dict with keys: total, migrated, skipped.
    """
    sys.path.insert(0, str(tilth_path))
    try:
        from benchmark.config import REPOS, TASKS  # type: ignore[import-not-found]
    except ImportError as e:
        print(f"Error: Could not import tilth benchmark from {tilth_path}: {e}")
        print(
            "Ensure the tilth repository is at the specified path"
            " and has a benchmark/config.py module."
        )
        sys.exit(1)
    finally:
        if str(tilth_path) in sys.path[0]:
            sys.path.pop(0)

    if not isinstance(TASKS, dict) or not isinstance(REPOS, dict):
        print("Error: TASKS and REPOS must be dicts")
        sys.exit(1)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    total = len(TASKS)
    migrated = 0
    skipped = 0

    for task_key, task in TASKS.items():
        if not isinstance(task, dict):
            print(f"Skipping {task_key}: not a dict")
            skipped += 1
            continue

        try:
            name = _map_name(task)
            task_type = _map_type(task)
            language = _map_language(task)
            difficulty = _map_difficulty(task)
            prompt: str = str(task.get("prompt", ""))
            repo: str = str(task.get("repo", "unknown"))
            description: str = prompt[:200]

            ground_truth = _build_ground_truth(task)
            mutations = _build_mutations(task)

            copeca_task: dict[str, Any] = {
                "name": name,
                "description": description,
                "source": SOURCE_FIELD,
                "repo": repo,
                "type": task_type,
                "category": _map_category(task),
                "language": language,
                "difficulty": difficulty,
                "version": 1,
                "prompt": prompt,
                "ground_truth": ground_truth,
            }

            # Only include mutations field if there are mutations
            if mutations:
                copeca_task["mutations"] = mutations

            # Validate before writing
            if not _is_valid_copeca_task(copeca_task):
                print(f"Skipping {name}: failed copeca validation")
                skipped += 1
                continue

            output_path = output_dir / repo / f"{name}.yaml"
            _emit_yaml(copeca_task, output_path)
            print(f"  Wrote {output_path}")
            migrated += 1

        except Exception as e:
            print(f"Skipping {task_key}: {e}")
            skipped += 1

    return {"total": total, "migrated": migrated, "skipped": skipped}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate tilth benchmark tasks to copeca YAML format.",
    )
    parser.add_argument(
        "--tilth-path",
        type=Path,
        default=Path("../tilth"),
        help="Path to the tilth repository (default: ../tilth)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tasks/"),
        help="Output directory for copeca task YAML files (default: tasks/)",
    )
    args = parser.parse_args()

    print(f"Migrating from {args.tilth_path} -> {args.output_dir}")
    summary = migrate(args.tilth_path, args.output_dir)
    print(
        f"Done. Total: {summary['total']}, migrated: {summary['migrated']}, "
        f"skipped: {summary['skipped']}"
    )


if __name__ == "__main__":
    main()
