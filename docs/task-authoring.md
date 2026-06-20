# Task Authoring Guide

How to write copeca task YAML files. Tasks are data, not code — correctness is
always strings or exit codes.

---

## Task YAML structure

Every task has required and optional fields. Required fields: `name`, `source`,
`repo`, `type`, `language`, `difficulty`, `version`, `prompt`, `ground_truth`.

`source` is mandatory — it carries the license attribution for provenance
(`architecture.md` invariant 7). `repo` must be a key in `repos.yaml`.

### Comprehension task example

```yaml
name: t002_fastapi_routing
description: "Find the APIRouter class in FastAPI and describe how route handlers are registered."
source: "SWE-QA (Apache-2.0)"
repo: fastapi
type: comprehension
language: python
difficulty: medium
version: 1
prompt: |
  Find the `APIRouter` class in the FastAPI codebase and describe how route
  handlers are registered. Explain the relationship between `APIRouter`,
  `Route`, and the `add_api_route` method.
ground_truth:
  required_strings:
    - APIRouter
    - add_api_route
    - Route
    - get
    - post
  all_of:
    - APIRouter
    - add_api_route
    - Route
  forbidden_strings:
    - "I cannot"
    - "unable to"
```

### Edit task example

```yaml
name: t006_fastapi_fix_status
description: "Fix the response status code bug in the endpoint handler."
source: "SWE-QA (Apache-2.0)"
repo: fastapi
type: edit
language: python
difficulty: medium
version: 1
prompt: |
  The endpoint `/items/` in the FastAPI test application returns HTTP 201
  instead of the correct HTTP 200 status code. Find the endpoint handler
  and fix the status code to return 200 on successful creation.
ground_truth:
  required_strings:
    - status_code
    - "200"
  test_command:
    - python
    - -c
    - "from fastapi.testclient import TestClient; from main import app; client = TestClient(app); r = client.post('/items/', json={'name': 'test'}); assert r.status_code == 200"
  forbidden_strings:
    - "I cannot"
mutations:
  - file: main.py
    action: replace
    find: "status_code=200"
    replace: "status_code=201"
    occurrence: 1
```

---

## Field reference

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Unique identifier (snake_case, e.g. `t002_fastapi_routing`) |
| `source` | Yes | Provenance with license, e.g. `"SWE-QA (Apache-2.0)"` |
| `repo` | Yes | Key in `repos.yaml` for the target repository |
| `type` | Yes | `comprehension` or `edit` |
| `language` | Yes | `python`, `rust`, `go`, or `javascript` |
| `difficulty` | Yes | `easy`, `medium`, or `hard` |
| `version` | Yes | Integer, bump on semantic changes to the task |
| `prompt` | Yes | The natural-language question sent to the agent |
| `ground_truth` | Yes | Correctness criteria (see below) |
| `description` | No | Human-readable summary of what the task tests |
| `mutations` | Edit only | Code changes that introduce a bug (see below) |

---

## Comprehension tasks: ground_truth

Comprehension tasks are graded by string matching against the agent's output.
All checks are case-insensitive substring matches.

- **`required_strings`** — Every string must appear in the output.
- **`all_of`** — Canonical completeness check. Every entry must appear.
  Distinct from `required_strings`: this verifies the agent listed
  *everything*, not just *something*.
- **`forbidden_strings`** — None of these may appear. Used to catch refusals
  (`"I cannot"`, `"unable to"`).

A comprehension task passes when all `required_strings` and `all_of` entries
are present and no `forbidden_strings` match.

## Edit tasks: ground_truth + mutations

Edit tasks are graded by running a test command after mutations are applied.

- **`test_command`** — A shell command (list of argv). Exit code 0 means the
  agent fixed the bug correctly.
- **`mutations`** — List of code changes that introduce a bug into clean code.
  Each mutation has a `file`, `action`, and action-specific fields.

### Mutation actions

| Action | Fields | Description |
|---|---|---|
| `replace` | `find`, `replace`, `occurrence` (optional, default 1) | Replace Nth occurrence of `find` with `replace` |
| `delete` | `find` | Remove all lines containing `find` |
| `insert_after` | `find`, `content` | Insert `content` after the first line containing `find` |
| `create` | `content` | Create a new file with `content` |

Mutations are applied atomically: if any mutation's `find` does not match,
no changes are made to the repo (the run errors).

---

## Validation

Validate tasks against the schema and repo registry:

```bash
copeca validate tasks/
```

This checks JSON Schema compliance, cross-references `repos.yaml`, and
verifies the `source` field references an approved source family.

---

## References

- [architecture.md](architecture.md) §3 — domain model, task invariants
- [engineering.md](engineering.md) §5 — benchmark correctness rules
- [README.md](../README.md) — task corpus overview
