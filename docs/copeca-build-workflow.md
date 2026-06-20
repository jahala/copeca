# How Copeca Is Built — tend workflow field notes

For the next agent (or you, next session). This documents the exact workflow used to build copeca from tend polyglots, step by step, with all the friction points and conventions discovered.

## The camp

- **Language:** Python ≥3.11 (3.11.9 via pyenv, `.venv/`)
- **Package:** `copeca` on PyPI (not yet published). Editable install: `pip install -e .`
- **Entry point:** `copeca` CLI, registered via `[project.scripts] copeca = "copeca.cli:app"`
- **Deps:** typer, pyyaml, jsonschema, pydantic. Dev: pytest, ruff, mypy
- **Repo root:** `src/copeca/` is the python package. `tests/` mirrors `src/copeca/` structure.

## Tend polyglot structure

Every feature lives in `docs/tend/features/<id>.tend.html`. The garden (project bet) is `docs/tend/overview.html`. Read state via:

```bash
bash docs/tend/features/<id>.tend.html data | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin), indent=2))"
```

Or via MCP: `mcp__tend__tend_get_context({ id: "<id>" })`

## The build loop

### 1. Read the feature plan

Call `tend_get_context({ id: "<feature-id>" })`. It returns the feature's slots, checks (with `validates_job` pointers to persona-jobs), steps (with `traces_to`, `dependencies`, `description` containing `Test:`/`Implement:` blocks), and resolved personas with their Job Stories. This is your source of truth for *what* to build and *how* to test it.

### 2. Find the next unblocked step

Each step has `status`: `pending` | `in-progress` | `done`. Steps with all `dependencies` satisfied are unblocked. Run through them in `id` order (i001 → i002 → ...). Mark the step `in-progress` before you start:

```javascript
tend_update_feature({ id: "<feature-id>", changes: { steps: [{ id: "i001", status: "in-progress" }] } })
```

### 3. RED — write the failing test first

Read the step's `description`, which contains a `Test:` block specifying:
- test file path
- what to assert
- boundary (pure function / real subprocess / real git)
- setup (fixtures needed)
- run command

Write the test file. Run it. It MUST fail — if it passes, the check is already implemented or the test is wrong. Stop and investigate.

### 4. IMPL — make it pass

Write the implementation. The constraint: **never modify the test file once written.** If the test is wrong, stop and fix the test as a separate concern — but this is rare; the test format is designed to be correct when written from the step description.

### 5. GREEN — run tests, confirm pass

```bash
source .venv/bin/activate && python3 -m pytest tests/ -v
```

Must be pristine: zero warnings, zero skips, all passing. Wait for green before marking the step done.

### 6. POST — record what was touched

Mark the step `done` and update `coverage_files` with all source and test files created/modified. Log discoveries and decisions in the step's `log[]` journal:

```javascript
tend_update_feature({
  id: "<feature-id>",
  changes: {
    coverage_files: ["src/copeca/new_file.py", "tests/test_new.py"],
    steps: [{
      id: "i001",
      status: "done",
      log: [
        { at: "2026-06-19T15:00:00Z", type: "note", text: "What was built" },
        { at: "2026-06-19T15:02:00Z", type: "discovery", text: "What was surprising" },
        { at: "2026-06-19T15:04:00Z", type: "decision", text: "What was chosen and why" }
      ]
    }]
  }
})
```

Log types: `note`, `discovery`, `decision`, `blocker`, `error`. Entries append across calls — you don't need to resend the full history.

### 7. Verify the tests run clean

After every step, run the full suite: `python3 -m pytest tests/ -v`. All tests must pass before proceeding. If you accumulated issues (broken imports, stale fixtures), fix them before moving on.

### 8. Also run mypy

```bash
source .venv/bin/activate && python3 -m mypy src/copeca/ --strict
```

Architecture invariant: domain layer files (`config/`, `tasks/`, `analysis/`) must never import from `runners/`, `repos/`, `results/`, `orchestration/`. Mypy catches type errors; this audit catches layer violations.

### 9. Repeat until all steps are done

When `progress.implementation === 100`, the feature is ready for audit.

### 10. AUDIT — verify against checks

Run `/tend audit <feature-id>`. This verifies every check:
- **Built?** No TODOs, stubs, or placeholders. All code is real.
- **Proven?** Every check has a test that exercises the real unit (not mocks), passes, and discriminates (the test fails when you break the code).
- **Built well?** Architecture invariants hold. Mypy strict clean. Engineering standards met.

If all checks pass: `audit.result = "pass"` → `status = "verified"`. The feature is done. Dependents become unblocked.

## Architecture invariants

Enforced during audit, checked after every step:

1. **Domain layer has no I/O.** `config/`, `tasks/`, `analysis/` never import from `runners/`, `repos/`, `results/`, `orchestration/`. Mechanically verifiable in CI:
   ```bash
   ! grep -r "from copeca.runners" src/copeca/config/ src/copeca/tasks/ src/copeca/analysis/
   ! grep -r "from copeca.repos"   src/copeca/config/ src/copeca/tasks/ src/copeca/analysis/
   ! grep -r "from copeca.results" src/copeca/config/ src/copeca/tasks/ src/copeca/analysis/
   ```

2. **Two-layer validation.** JSON Schema validates structure (human-readable errors). Pydantic validates type safety (internal contracts). The split is deliberate — schema changes don't touch Python, model changes don't break user-facing errors.

3. **Cost is computed, never trusted.** (Not yet in the codebase — this is a Phase 1b invariant. When writing `runners/`, compute cost from `Σ tokens × pricing`; vendor cost goes to `vendor_cost_usd` as a cross-check only.)

4. **One execution path.** No `if docker:`. No `if sandbox:`. Environment is declared and verified; provisioning is the operator's choice.

5. **Tasks are data, never code.** No embedded Python in task YAML. Correctness is always strings + test_command. If something needs custom code to grade, it isn't a copeca task.

## The two layers (schema vs Pydantic)

Schema catches YAML structure problems:
```yaml
name: ""        # minLength: 1 → caught by jsonschema
source: "test"
repo: ripgrep
type: comprehension
language: rust
difficulty: hard
version: 1
prompt: "test"
ground_truth:
  required_strings: ["test"]
```

Pydantic catches semantic/conditional problems:
- `type: edit` requires `ground_truth.test_command` (Pydantic discriminated union)
- `mutations[].action: delete` requires `find` (field_validator)
- `mutations[].action: create` requires `content` (field_validator)

The loader applies schema first, then Pydantic, then cross-document repo validation. Three layers, in order. Schema failures produce user-facing field-name errors. Pydantic failures produce Python tracebacks (should be caught and wrapped — not yet done in the loader, note for improvement). Repo failures name the missing key and list available repos.

## Known friction points

1. **Python 3.9 is macOS default.** Copeca requires ≥3.11. Install via `pyenv`:
   ```bash
   pyenv install 3.11.9
   pyenv local 3.11.9
   eval "$(pyenv init -)"
   python3 -m venv .venv && source .venv/bin/activate
   pip install -e .
   ```

2. **Typer single-command app flattens.** When there's only one command registered on a Typer app, it renders as `copeca /path` not `copeca validate /path`. Must have at least two commands for proper subcommand dispatch. `list` was added alongside `validate` to force this.

3. **`MutationAction(str, Enum)` is buggy.** Using `str` as a base for an Enum causes silent member shadowing — `MutationAction.replace` inherits `str.replace()`. Use plain `Enum` instead. The test must compare to `MutationAction.replace`, not `"replace"`.

4. **Schema path resolution needs `.resolve()`.** `Path(__file__).parent.parent.parent` works when tests are run from the project root but breaks when run from elsewhere. Always use `Path(__file__).resolve().parent...` for schema/fixture paths in test utilities. (The `loader.py` uses `__file__.resolve()`; fixtures use `Path(__file__).resolve().parent.parent`.)

5. **negctrl can't run on Python projects.** `npx tend-cli negctrl` creates a bare git worktree and runs the test there. Python projects need venv + pip install, which the bare worktree won't have. For behavior checks, use structural discrimination analysis: explain what removing the key line would do to the test (e.g., "removing `validate()` makes invalid YAML pass validation → test_invalid_dir_exits_nonzero would fail because it expects exit ≠ 0"). The audit verdict must note that negctrl was mechanically unrunable.

6. **`coverage_files` paths must be under a configured `source_dirs`.** The garden's `source_dirs` defaults to `["src"]`. If a feature claims `schemas/task.schema.json` or `tests/` or `repos.yaml`, those paths won't resolve. Expand `source_dirs` on the garden: `tend_update_feature({ id: "garden", changes: { source_dirs: ["src", "schemas", "tasks", "docs", "defaults", "scripts", "tests", "."] } })`.

7. **MCP `tend_update_feature` modifies steps by merging on `id`.** When updating multiple steps in one call, pass an array of `{ id, ... }` objects. Fields you omit are preserved. Fields you pass are merged. `log[]` entries append — you don't need to resend the full journal for a step you've already logged.

## Current state

| Feature | Status | Steps | Tests |
|---|---|---|---|
| copeca-validate-tasks | **verified** | 8/8 | 35/35 |
| copeca-single-run | **planned** (unblocked) | 0/9 | — |
| copeca-task-corpus | **planned** (unblocked) | 0/6 | — |
| copeca-mode-mechanism | **planned** (blocked: single-run) | 0/5 | — |
| copeca-cost-model | **planned** (blocked: single-run) | 0/5 | — |
| copeca-artifact-integrity | **planned** (blocked: single-run) | 0/5 | — |
| copeca-scenario-matrix | **planned** (blocked: single-run, mode-mechanism, cost-model) | 0/5 | — |
| copeca-analysis-reporting | **planned** (blocked: scenario-matrix, cost-model, artifact-integrity) | 0/6 | — |
| copeca-docs-and-init | **planned** (blocked: all 8 above) | 0/5 | — |

**Next to build:** `copeca-single-run.i001` — ADAPT parser dataclasses (`Turn`, `ToolCall`, `RunResult`) from tilth's `benchmark/parse.py`. Pure domain layer, no I/O. The step description has a complete `Test:` block — write the failing test in `tests/runners/test_parsers_base.py`, then COPY from tilth.
