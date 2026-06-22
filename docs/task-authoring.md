# Task Authoring Guide

How to write copeca task YAML files. Tasks are data, not code — correctness is
always strings or exit codes.

---

## Quick start

```bash
# Scaffold a commented skeleton to get started
copeca new-task src/copeca/data/tasks/myrepo/my_task.yaml

# Validate schema + provenance + tool-agnosticism
copeca validate src/copeca/data/tasks/myrepo/

# For edit tasks: prove the mutation bites
copeca check-task src/copeca/data/tasks/myrepo/my_task.yaml
```

Both gates must pass before opening a PR. See [Validation](#validation) for details.

---

## Capability categories

Every task declares one `category` that describes the cognitive skill under test.
The category is orthogonal to `type` (which controls grading); together they
determine what a benchmark run reveals about a tool's capabilities.

| Category | Type(s) allowed | What it measures |
|---|---|---|
| `locate` | comprehension | Report one self-contained, named thing — a symbol, file, or value. The answer is either right or wrong; no navigation chain is required. |
| `trace` | comprehension | Map a relationship that spans files — callers, implementors, control-flow, data-flow. The agent must follow references across the codebase. |
| `fix` | edit | Change code until a stated test passes. The defect is introduced by the task's `mutations`; the agent must diagnose and undo it. |
| `debug` | comprehension or edit | Diagnose a defect via git history, then either explain it (comprehension) or resolve it (edit). The mutation may be committed in `mutation_sequence` to build real git history. |

### Planned: `reason` category (not yet active)

A `reason` task will ask the agent to comprehend a **self-contained code
fragment** with no repository navigation needed — e.g. "what does this
function return, given these inputs?". The answer can be derived by reading
the provided text alone. `reason` tasks use `type: comprehension`.

> `reason` is defined in the `Category` enum but not yet gated in validation.
> This section documents the intended semantics so authors can identify
> good candidates when it ships.

### The `control: true` flag (not yet active)

A task marked `control: true` is a **tool-neutral non-regression** task: one
where a codebase search tool should NOT provide an advantage over baseline
(e.g. answer-in-context, single-file, or pure-reasoning tasks). Control tasks
detect whether a tool *regresses* on simple work, not whether it helps on hard
work. They complement discriminating tasks: a tool that aces hard tasks but
regresses on controls is still broken.

> The `control` field is planned for an upcoming schema revision. Do not add
> it to task YAMLs yet; it will not validate. This section documents the
> design so authors can identify which tasks are good control candidates.

---

## Task YAML structure

Every task has required and optional fields. Required fields: `name`, `source`,
`repo`, `type`, `category`, `language`, `difficulty`, `version`, `prompt`,
`ground_truth`.

`source` is mandatory — it carries the license attribution for provenance
(`architecture.md` invariant 7). `repo` must be a key in `repos.yaml`.

`category` must be consistent with `type`:
- `comprehension` tasks: `locate`, `trace`, or `debug`
- `edit` tasks: `fix` or `debug`

### Comprehension task example — `locate`

```yaml
name: rg_find_matcher_trait
description: "Locate the Matcher trait definition in ripgrep."
source: "tilth-benchmark (MIT)"
repo: ripgrep
type: comprehension
category: locate
language: rust
difficulty: easy
version: 1
prompt: |
  Find the `Matcher` trait in the ripgrep codebase. Report the file path
  and the names of its required methods.
ground_truth:
  required_strings:
    - Matcher
    - find_at
  all_of:
    - Matcher
    - find_at
  forbidden_strings:
    - "I cannot"
    - "unable to"
```

### Comprehension task example — `reason` (future category)

```yaml
name: fastapi_decode_return
description: "Reason about a self-contained function's return value."
source: "tilth-benchmark (MIT)"
repo: fastapi
type: comprehension
category: reason        # planned — not yet active
language: python
difficulty: easy
version: 1
prompt: |
  Given the following function from fastapi/utils.py:

      def get_value_or_default(field_info, default):
          if field_info is not None:
              return field_info
          return default

  What does `get_value_or_default(None, 42)` return?
ground_truth:
  required_strings:
    - "42"
  all_of:
    - "42"
  forbidden_strings:
    - "I cannot"
```

### Edit task example — `fix`

```yaml
name: t006_fastapi_fix_status
description: "Fix the response status code bug in the endpoint handler."
source: "SWE-QA (Apache-2.0)"
repo: fastapi
type: edit
category: fix
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
| `name` | Yes | Unique identifier (snake_case, e.g. `t002_fastapi_routing`). Pattern: `^[a-z][a-z0-9_-]*$` |
| `source` | Yes | Provenance with license family, e.g. `"tilth-benchmark (MIT)"`. See [Provenance rules](#provenance-rules). |
| `repo` | Yes | Key in `repos.yaml` for the target repository |
| `type` | Yes | `comprehension` or `edit` |
| `category` | Yes | `locate`, `trace`, `fix`, or `debug` (see [Capability categories](#capability-categories)) |
| `language` | Yes | `python`, `rust`, `go`, or `javascript` |
| `difficulty` | Yes | `easy`, `medium`, or `hard` |
| `version` | Yes | Integer, start at 1; bump on semantic changes to the task |
| `prompt` | Yes | The natural-language question sent to the agent. Must be tool-agnostic (see [Tool-agnostic phrasing](#tool-agnostic-phrasing)). |
| `ground_truth` | Yes | Correctness criteria (see below) |
| `description` | No | Human-readable summary of what the task tests |
| `commit` | No | Per-task commit override (overrides `repos.yaml` default) |
| `mutations` | Edit only | Code changes that introduce a bug (see below) |
| `mutation_sequence` | Debug/edit | Committed mutation steps that build real git history for `debug` tasks |

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

## Provenance rules

Every task must carry an approved-license provenance. The `source` field must
reference a **real, permissively-licensed origin**.

### Approved source families

| Family | Example `source:` value |
|---|---|
| Apache-2.0 | `"SWE-QA (Apache-2.0)"` |
| MIT | `"tilth-benchmark (MIT)"` |
| CC-BY-4.0 | `"MyDataset (CC-BY-4.0)"` |

### Blocked / rejected sources

Tasks whose `source` field matches any entry in the contamination blocklist are
**rejected by `copeca validate`**. Blocked categories include:

- Benchmarks known to be in frontier-model training data (e.g. SWE-bench Verified, HumanEval)
- Benchmarks with NC (non-commercial) or ND (no-derivatives) licensing
- Deprecated or retracted benchmarks

See `src/copeca/data/contamination_blocklist.txt` for the full list.

### Repository pinning

The target repo must be a **real OSS repository** registered in `repos.yaml`
at a pinned commit. Add the repo entry before opening a PR:

```yaml
# repos.yaml
myrepo:
  url: https://github.com/owner/myrepo.git
  commit: <full 40-char SHA>
  language: python          # or rust / go / javascript
  toolchain:
    python: "3.11"
  setup_command:
    - python
    - -m
    - pip
    - install
    - -e
    - .
```

The commit must be publicly accessible and must match the code state the task
was authored against.

---

## Tool-agnostic phrasing

A task must name **the information it requires**, never **the method or tool**
used to retrieve it. The retrieval method is the variable under test — if the
prompt specifies it, the A/B comparison is invalidated.

**Good:** "Find the `Matcher` trait and list its required methods."
**Bad:** "Use grep to search for `trait Matcher`."
**Bad:** "Run `cargo doc` and describe the Matcher trait."
**Bad:** "Search for the Matcher trait. One structured answer beats several searches."

The agnosticism check in `copeca validate` catches common patterns (tool names,
"search for", single-shot-aggregator cues). Write for the *information*, not
the *navigation*.

---

## Validation

### Gate 1 — schema, provenance, tool-agnosticism

```bash
copeca validate src/copeca/data/tasks/myrepo/
```

Checks:
- JSON Schema compliance (all required fields present and typed correctly)
- `category` is consistent with `type`
- `repo` is a key in `repos.yaml` (if a `repos.yaml` is found)
- `source` does not match any blocked benchmark in the contamination blocklist
- `prompt` and `description` are tool-agnostic (no tool names, no retrieval prescriptions)

Exit 0 = all tasks valid. Exit 1 = at least one finding. Fix all findings before opening a PR.

### Gate 2 — mutation discrimination (edit tasks only)

```bash
copeca check-task src/copeca/data/tasks/myrepo/my_task.yaml
```

Checks:
- The `test_command` passes on clean code (before mutations)
- The `test_command` fails after `mutations` are applied (the mutation bites)

A task that fails this gate is **weak** — either the test is wrong or the
mutation does not introduce a real defect. Fix one or both until the gate
passes.

---

## References

- [architecture.md](architecture.md) §3 — domain model, task invariants
- [engineering.md](engineering.md) §5 — benchmark correctness rules
- [task-taxonomy.md](task-taxonomy.md) — category taxonomy and design rationale
- [README.md](../README.md) — task corpus overview
