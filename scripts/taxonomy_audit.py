#!/usr/bin/env python3
"""Audit task corpus taxonomy — produce a summary of counts by type, language, source, and repo.

Usage:
    python scripts/taxonomy_audit.py tasks/

Architecture: pure data script — reads YAML, prints a summary. No I/O beyond filesystem.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import yaml


def audit_taxonomy(tasks_dir: Path) -> dict:
    """Audit task corpus taxonomy. Returns dict with counts by type, language, source."""
    stats: dict = {
        "total": 0,
        "by_type": Counter(),
        "by_language": Counter(),
        "by_source": Counter(),
        "by_repo": Counter(),
        "errors": [],
    }
    for yaml_file in sorted(tasks_dir.rglob("*.yaml")):
        try:
            with open(yaml_file) as f:
                task = yaml.safe_load(f)
            stats["total"] += 1
            stats["by_type"][task.get("type", "unknown")] += 1
            stats["by_language"][task.get("language", "unknown")] += 1
            stats["by_source"][task.get("source", "unknown")] += 1
            stats["by_repo"][task.get("repo", "unknown")] += 1
        except Exception as e:
            stats["errors"].append(f"{yaml_file}: {e}")
    return stats


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/taxonomy_audit.py <tasks_dir>", file=sys.stderr)
        sys.exit(1)

    tasks_dir = Path(sys.argv[1])
    if not tasks_dir.is_dir():
        print(f"Error: not a directory: {tasks_dir}", file=sys.stderr)
        sys.exit(1)

    stats = audit_taxonomy(tasks_dir)

    print(f"Total tasks: {stats['total']}")
    print(f"By type: {dict(stats['by_type'])}")
    print(f"By language: {dict(stats['by_language'])}")
    print(f"By source: {dict(stats['by_source'])}")
    print(f"By repo: {dict(stats['by_repo'])}")

    if stats["errors"]:
        print(f"\nErrors: {len(stats['errors'])}")
        for err in stats["errors"]:
            print(f"  {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
