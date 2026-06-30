#!/usr/bin/env python3
"""Import SWE-bench-Live instances as VERBATIM copeca edit tasks.

Each instance becomes a copeca edit task that checks out the repo at
``base_commit``, lets the agent fix it, then (hidden, at grade time) applies the
instance's ``test_patch`` and runs the exact ``FAIL_TO_PASS`` + ``PASS_TO_PASS``
node-ids in the repo's per-worktree venv. The ``test_command`` exit code is the
grade. No copeca code change is required — the run path already runs the repo
``setup_command`` per-worktree, runs ``test_command`` in the worktree with the
full host env, and grades on ``returncode == 0``.

The repo must already exist in ``repos.yaml`` with a per-worktree-venv
``setup_command`` (see the ``flask`` entry), and be mapped in ``REPO_KEY`` below.

Usage::

    python scripts/import_swebench.py --rows rows.json --ids id1,id2

``rows.json`` is either the HuggingFace datasets-server response
(``{"rows": [{"row": {...}}]}``) or a flat JSON list of instance dicts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

# SWE-bench repo (owner/name) -> copeca repos.yaml key. The repo MUST already be
# in repos.yaml with a per-worktree-venv setup_command. Extend as repos are
# validated on the host.
REPO_KEY = {
    "pallets/flask": "flask",
}

_DIFFICULTY_BY_FILES = {1: "easy", 2: "medium"}  # >=3 files touched -> hard


class _Dumper(yaml.SafeDumper):
    pass


def _str_representer(dumper: yaml.SafeDumper, data: str):
    # Multi-line strings (prompt, grading script) render as literal blocks when
    # possible; pyyaml falls back to a quoted style if a line has trailing
    # whitespace — either way the round-trip is exact.
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str_representer)


def _grading_command(test_patch: str, node_ids: list[str]) -> list[str]:
    """Self-contained grader run AFTER the agent, in the worktree.

    Heredocs the hidden test_patch + node-ids to temp files OUTSIDE the repo (so
    the agent, which only ever sees ``prompt``, never sees the test that defines
    correctness), applies the patch, and runs exactly the FAIL_TO_PASS +
    PASS_TO_PASS node-ids. Exit code is the grade.

    Node-ids are read one-per-line into a bash array so parametrized ids that
    contain spaces (pytest ``[...]`` params) are passed intact as single args.
    """
    patch = test_patch.rstrip("\n")
    ids = "\n".join(node_ids)
    # Files the test_patch touches — reset them to base before applying so the
    # agent's edits to test files cannot break (or game) the hidden test. Mirrors
    # the SWE-bench harness, which restores test files before applying test_patch.
    targets = sorted({line[6:].strip() for line in patch.splitlines() if line.startswith("+++ b/")})
    reset = " ".join(f'"{t}"' for t in targets)
    script = (
        "set -e\n"
        'TP="$(mktemp)"; IDS="$(mktemp)"\n'
        "cat > \"$TP\" <<'COPECA_TP_EOF'\n"
        f"{patch}\n"
        "COPECA_TP_EOF\n"
        "cat > \"$IDS\" <<'COPECA_IDS_EOF'\n"
        f"{ids}\n"
        "COPECA_IDS_EOF\n"
        f"git checkout HEAD -- {reset} 2>/dev/null || true\n"
        'git apply "$TP"\n'
        'args=(); while IFS= read -r line; do args+=("$line"); done < "$IDS"\n'
        '.venv/bin/python -m pytest -q -p no:cacheprovider "${args[@]}"\n'
    )
    return ["bash", "-lc", script]


def _difficulty(row: dict) -> str:
    files = (row.get("difficulty") or {}).get("files")
    if isinstance(files, int):
        return _DIFFICULTY_BY_FILES.get(files, "hard")
    return "hard"


def to_task(row: dict) -> dict:
    repo = row["repo"]
    if repo not in REPO_KEY:
        raise SystemExit(
            f"repo {repo!r} is not mapped — add it to REPO_KEY and to repos.yaml "
            "with a per-worktree-venv setup_command first."
        )
    key = REPO_KEY[repo]
    num = row["instance_id"].rsplit("-", 1)[-1]
    # Grade on FAIL_TO_PASS (the test the fix is *for*). PASS_TO_PASS is recorded
    # but NOT gated: faithful P2P regression-checking needs the instance's exact
    # dependency env (the SWE-bench Docker image); our per-worktree venv diverges
    # on a few version-sensitive tests, which would poison an all-P2P gate. Also
    # drop node-ids the SWE-bench-Live log parser split on spaces (unbalanced []).
    f2p = [n for n in row["FAIL_TO_PASS"] if n.count("[") == n.count("]")]
    if not f2p:
        raise SystemExit(f"{row['instance_id']}: no usable FAIL_TO_PASS node-id — skip")
    node_ids = f2p
    return {
        "name": f"swebl_{key}_{num}",
        "description": (
            f"SWE-bench-Live {row['instance_id']} (verbatim): real GitHub-issue fix, "
            f"graded on FAIL_TO_PASS ({len(f2p)}); {len(row['PASS_TO_PASS'])} PASS_TO_PASS "
            "recorded but not gated (needs full env reproduction)."
        ),
        "source": f"SWE-bench-Live ({row['instance_id']})",
        "repo": key,
        "commit": row["base_commit"],
        "type": "edit",
        "category": "fix",
        "language": "python",
        "difficulty": _difficulty(row),
        "version": 1,
        "prompt": row["problem_statement"].rstrip("\n") + "\n",
        "ground_truth": {
            "required_strings": [],
            "forbidden_strings": ["I cannot", "unable to"],
            "test_command": _grading_command(row["test_patch"], node_ids),
        },
        "mutations": [],
    }


def _load_rows(path: Path) -> dict:
    data = json.loads(path.read_text())
    if isinstance(data, dict) and "rows" in data:
        return {r["row"]["instance_id"]: r["row"] for r in data["rows"]}
    if isinstance(data, list):
        return {r["instance_id"]: r for r in data}
    raise SystemExit("unrecognized rows JSON shape (expected datasets-server rows or a list)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Import SWE-bench-Live instances as copeca tasks.")
    ap.add_argument("--rows", required=True, type=Path, help="SWE-bench-Live rows JSON")
    ap.add_argument("--ids", required=True, help="comma-separated instance_ids to import")
    ap.add_argument("--out", type=Path, default=Path("src/copeca/data/tasks"))
    args = ap.parse_args()

    rows = _load_rows(args.rows)
    for iid in (x.strip() for x in args.ids.split(",") if x.strip()):
        if iid not in rows:
            raise SystemExit(f"instance_id {iid!r} not found in {args.rows}")
        row = rows[iid]
        task = to_task(row)
        out_dir = args.out / task["repo"]
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{task['name']}.yaml"
        dest.write_text(
            yaml.dump(
                task,
                Dumper=_Dumper,
                sort_keys=False,
                default_flow_style=False,
                width=10**6,
                allow_unicode=True,
            )
        )
        print(f"wrote {dest}  (F2P={len(row['FAIL_TO_PASS'])}, P2P={len(row['PASS_TO_PASS'])})")


if __name__ == "__main__":
    main()
