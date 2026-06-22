## tend — Feature Map

tend tracks planned work across sessions. If it's not updated, the next session starts blind.

### Start here
**Existing codebase?** → restart session, then `/tend discover` to map code into features (requires MCP — restart first)
**Greenfield?** →
1. `/tend position` — define who you're building for (personas + jobs)
2. `/tend brainstorm` — shape your first feature into slots + checks
3. `/tend plan` — break it into testable steps
4. `/tend run` — build it
5. `/tend audit` — verify it with real evidence

When you need it: `/tend change` (requirement changes) · `/tend narrate` (write the article body)

### Daily loop
1. `/tend` — see status + what's unblocked
2. Pick the suggested feature or choose from the list
3. No plan? → `/tend plan` creates implementation steps
4. Implement steps — `tend_update_feature` with steps[] (by-id merge) as you complete each
5. All done? → `/tend audit` verifies code matches checks

### Before you build
When asked to implement multi-file changes, check tend first:
1. `ls docs/tend/features/` (or `tend_get_unblocked`) — does this work map to a feature?
2. No match → `/tend brainstorm` to create one (minimal draft is fine)
3. Match → `tend_update_feature` with the touched step's status as you complete each

### MCP tools
- `tend_get_context` — full feature context in one call
- `tend_get_unblocked` — what to work on next
- `tend_update_feature` — single write surface; step status is one of many fields
- `tend_get_gaps` — what needs attention; each gap names the closing skill
- `npx tend-cli ui` — generate web dashboard and open in browser

For reads of a single feature, use the polyglot: `bash docs/tend/<id>.tend.html data | jq`.

---

## Running a benchmark (copeca's core operation)

copeca A/B-compares a CLI agent **with a tool/mode** vs a **clean baseline**, holding
agent + model + corpus + baseline fixed and varying ONE thing. Output is
cost-per-correct + a delta report.

```bash
PATH="$PWD/.venv/bin:$PATH"                                  # or installed `copeca` / `python -m copeca`
copeca run --task scenarios/<name>.yaml --runner claude      # → results/<name>.jsonl  (gitignored)
copeca analyze results/<name>.jsonl                          # delta + per-task + per-capability + control + tool-validity
copeca analyze results/<name>.jsonl --format json
```

### Scenario file (`scenarios/*.yaml`)
```yaml
name: my-run               # ^[a-z][a-z0-9_-]*$ ; output goes to results/<name>.jsonl
tasks: [task_a, task_b]    # explicit list of task NAMEs — Scenario.tasks is list[str], NO glob.
                           #   "all tasks" = list every one; names via parsing src/copeca/data/tasks/**/*.yaml `name:`
modes: [baseline, tilth]   # the ONE variable; modes are YAML in src/copeca/data/defaults/modes/
models: [claude-haiku-4-5] # MUST equal a pricing key in the runner YAML
repetitions: 1             # 5+ for tight CIs (validate_scenario warns under 5)
budget_usd: 1.00           # per-run cap, passed to the agent CLI
timeout_seconds: 600       # per-run; raise it for edit tasks (Rust/Go/npm compiles)
max_workers: 1             # KEEP AT 1 — concurrency is unsafe (see below)
output_dir: results
```

### Knobs that bite
- **Model id = pricing key.** Claude models: `claude-sonnet-4-6`, `claude-haiku-4-5`,
  `claude-opus-4-8` (keys in `src/copeca/data/defaults/runners/claude.yaml`; the `claude`
  CLI accepts them as `--model`). No pricing entry → cost warnings/failure.
- **Modes** live in `src/copeca/data/defaults/modes/` (baseline, hook, indexed, proxy,
  wrapper, **tilth**). `tilth.yaml` is **local/untracked** (points at a local `tilth`
  binary via mcp_config) — recreate it if missing. Point the `tilth` mcp server command
  at the absolute `~/.cargo/bin/tilth` (1.0.0) path so PATH order cannot pick up
  homebrew 0.9.0 instead. copeca warns at run time when multiple versions are installed.
- **Repos auto-clone** into `repos/_bare/` + `repos/_worktrees/` (both gitignored).
  **Edit tasks run real `test_command`s** → need `cargo`/`go`/`node`/`npm`/`python3`
  on PATH; comprehension tasks only need the checkout.
- **`results/` is gitignored** — runs aren't committed; commit a small fixture (e.g.
  `tests/fixtures/sample_report_records.jsonl`) if you need a runnable artifact.
- **`max_workers` MUST be 1** for now: `run_matrix` uses ThreadPoolExecutor but the
  worktree manager only locks `create_worktree`, so concurrent git reset/mutation across
  worktrees of the *same* bare repo collide on `index.lock` and corrupt the run. (Tracked
  fix: per-repo lock.)
- **Editable-install hijack** (the `.venv` repoint gotcha): if `import copeca` resolves
  outside `cancun`, fix with `pip install -e . --no-deps` from cancun.
- **Controls** (`ctrl_*`, `control: true`) should show ~no tool effect — the report's
  Control + Tool Validity sections key off them.
