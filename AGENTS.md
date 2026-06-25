# AGENTS.md — operating copeca

copeca is an **A/B benchmark for coding agents**. It holds agent + model + corpus + baseline
fixed, varies **exactly one thing** (a tool / MCP server / mode), and measures **cost per
correct answer**. A run reads a *scenario*, executes every (task × mode × model × rep) as an
isolated agent invocation, grades each, and writes `results/<scenario>.jsonl` + a delta report.

Everything is **data, not code**: you operate copeca by writing YAML (tasks, modes, scenarios,
repos) and running the CLI. There is no global config — a *scenario* names the pieces and is
the entry point.

---

## Two golden rules (read before authoring anything)

1. **Vary exactly ONE thing.** The two modes in a scenario must be identical in every respect —
   tools, prompt, env — except the single dimension under test (usually: one arm adds an MCP
   server). If two things differ, the delta is uninterpretable.

2. **Never drop Claude Code's default prompt.** Two flags, opposite effects:
   - `scenario.system_prompt` → emits `--system-prompt` (**replaces** the default). This strips
     the agent's built-in navigation scaffolding and **cripples the native baseline**, inflating any tool's apparent advantage. **Leave it unset.**
   - `mode.append_system_prompt` → emits `--append-system-prompt` (**keeps** the default, adds
     your text). Use this, **byte-identical on both arms**, to control the prompt fairly.

---

## Repo layout

```
scenarios/*.yaml                       # run specs — the entry point. results/<name>.jsonl
src/copeca/data/tasks/<repo>/*.yaml    # the corpus (one dir per source repo)
src/copeca/data/defaults/modes/*.yaml  # the A/B arms (tools, mcp_config, append_system_prompt)
src/copeca/data/defaults/runners/*.yaml# per-CLI command template + pricing keys + isolation
src/copeca/data/repos.yaml             # repo registry: url, commit, toolchain, setup
src/copeca/config/models.py            # ← authoritative schema (Pydantic). Trust this over any doc.
results/  repos/_bare/  repos/_worktrees/   # gitignored (run output + clones)
```

---

## 1. Repo (`src/copeca/data/repos.yaml`)

A task's `repo:` must be a key here.

```yaml
mylib:
  url: https://github.com/owner/mylib.git
  commit: <40-char sha>          # default checkout (a task may override per-task)
  language: go                   # python | rust | go | javascript  (closed enum)
  toolchain: {go: "1.23.0"}      # optional, informational
  setup_command: [go, mod, download]  # optional, run per worktree (deps for edit/test tasks)
```

First run needs a **bare clone**. copeca auto-clones from `url` only if it finds a `repos.yaml`
in the cwd or task-relative path; otherwise create it once:
`git clone --bare <url> repos/_bare/mylib`. Comprehension tasks only need the checkout; edit
tasks also need the toolchain (`go`/`cargo`/`node`/`python3`) on PATH.

---

## 2. Task (`src/copeca/data/tasks/<repo>/<name>.yaml`)

**Comprehension** (graded on the answer text):

```yaml
name: gin_servehttp_flow         # ^[a-z][a-z0-9_-]*$
description: "Trace Engine.ServeHTTP through Context acquisition, routing, dispatch."
source: "my-corpus-2026"         # required, free text (provenance)
repo: gin                        # key in repos.yaml
commit: d7776de7...              # optional: pin this task's checkout
type: comprehension              # comprehension | edit
category: trace                  # comprehension ⟹ locate | trace | debug | reason
language: go
difficulty: medium               # easy | medium | hard
version: 1
prompt: |                        # describe the GOAL, never a tool (no "grep"/"tilth"/"ast" — there's a lint)
  Find Engine.ServeHTTP in gin and trace what it calls to get a Context,
  match the route, and run the handlers. Name each function in the path.
ground_truth:                    # correct = ALL required_strings AND ALL all_of present, AND no forbidden_strings
  required_strings: [ServeHTTP, handleHTTPRequest, getValue, Next, handlers]
```

**Edit** (graded by running a command — `test_command` is authoritative):

```yaml
name: kong_rename_inferredtype
description: "Rename Token.InferredType to DeducedKind across the package."
source: "my-corpus-2026"
repo: kong
type: edit                       # edit ⟹ category fix | debug
category: fix
language: go
difficulty: medium
version: 1
prompt: |
  Rename the Token method `InferredType` to `DeducedKind` everywhere — definition,
  doc comment, and all call sites — so nothing references the old name and the
  project still builds and tests pass.
ground_truth:
  required_strings: []           # diagnostic only for edit tasks
  test_command:                  # argv; exit 0 = correct
    - bash
    - -c
    - "! grep -rqI 'InferredType' --include='*.go' . && go test ./... -count=1"
```

**Authoring traps:**
- **Verify ground truth at the pinned commit** with real tools (run the search/grep yourself on
  the checkout). A wrong caller list or chain = a silently broken task.
- **Comprehension graders: 3–5 distinctive, verified identifiers.** `required_strings`/`all_of`
  are *all-conjunctive* — over-specifying false-fails correct answers (e.g. requiring a function
  that isn't actually on the path).
- **Edit graders must fail at baseline.** A pure "rename X" graded by just `go test` passes on the
  untouched repo (it already compiles) → the agent does nothing and scores correct. Make the
  grader fail until the work is done (e.g. *old name is gone* `! grep <old>` **and** tests pass),
  and **prove it discriminates**: complete solution → exit 0; revert one site → non-zero.
- **Controls:** set `control: true` for tasks where the tool *shouldn't* help (single-file /
  answer-in-context). The report uses them to catch over-specialization.

Validate after authoring: `copeca validate src/copeca/data/tasks` (schema + repo refs).

---

## 3. Mode (`src/copeca/data/defaults/modes/<name>.yaml`)

A mode is one A/B arm — how the agent is equipped. The fair pattern is two modes that differ in
**one** field. At least one of `tools`/`mcp_config`/`env`/`agent_config`/`wrapper`/`setup` required.

```yaml
# baseline arm — native tools only
name: baseline_tappend
description: "Native tools + the shared prompt. Pairs with the experimental arm; only the MCP differs."
tools: [Read, Edit, Grep, Glob, Bash]      # the native-tool whitelist
append_system_prompt: "<identical text on both arms>"
```
```yaml
# experimental arm — adds ONLY the MCP server
name: tilth_tappend
description: "Same as baseline_tappend + the tool-under-test MCP. The MCP is the only variable."
tools: [Read, Edit, Grep, Glob, Bash]
append_system_prompt: "<identical text>"
mcp_config:
  mcpServers:
    tilth:
      command: /abs/path/to/tool-binary    # ⚠ machine-specific — keep local or parameterize before committing
      args: ["--mcp"]
```

- **Forcing adoption is a different experiment.** Removing native search tools (e.g.
  `tools: [Read, Edit]`) forces the agent onto the MCP. That answers "what does the tool cost when
  *always* used". Don't conflate it with the free-choice A/B; run it as its own scenario.
- `append_system_prompt` becomes `--append-system-prompt` for the claude runner; for CLIs without
  that flag (codex, gemini) it's prepended to the prompt. It's recorded as
  `mode_append_system_prompt` in every record for disclosure.

---

## 4. Scenario (`scenarios/<name>.yaml`) — the run spec

```yaml
name: my-run                     # → results/my-run.jsonl
description: "..."
tasks: [gin_servehttp_flow, kong_rename_inferredtype]   # explicit task NAMES — no glob
modes: [baseline_tappend, tilth_tappend]                # the A/B — vary ONE thing
models: [claude-haiku-4-5]       # MUST equal a pricing key in the runner YAML (else cost is wrong)
repetitions: 5                   # ≥5 for a verdict; 1 = smoke test only (1-rep deltas flip sign)
budget_usd: 1.50                 # per-run cap, passed to the agent CLI
timeout_seconds: 900             # per-run; raise for compiles
max_workers: 4                   # >1 is safe — each work item gets its own clone
output_dir: results
# system_prompt: "..."           # ⚠ OMIT — this REPLACES the default and cripples the baseline (golden rule 2)
```

Model ids (claude): `claude-haiku-4-5`, `claude-sonnet-4-6`, `claude-opus-4-8` — must match keys
in `src/copeca/data/defaults/runners/claude.yaml`.

---

## 5. Run & analyze

```bash
PATH="$PWD/.venv/bin:$PATH"          # or an installed `copeca`

copeca validate src/copeca/data/tasks    # schema-check tasks (scenarios/modes are checked at run time)

# Auth — SUBSCRIPTION is the default. Drop provider keys so a stale key can't hijack the login:
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN OPENAI_API_KEY GEMINI_API_KEY GOOGLE_API_KEY
copeca run --task scenarios/my-run.yaml --runner claude    # writes results/my-run.jsonl (streamed)

copeca analyze results/my-run.jsonl       # delta + per-task + per-capability + control + tool-validity
copeca analyze results/my-run.jsonl --format json
```

- **API-key auth instead:** `source ~/.copeca.env && copeca run ...` — scoped to that run only.
  **NEVER** set a provider key globally (it hijacks your interactive Claude Code: "credit balance
  too low"). copeca auto-selects: provider key present → metered API profile; else → subscription.
- Each record in the JSONL carries `correct`, `total_cost_usd`, `tool_sequence`, `tool_adopted`,
  `tool_version`, `mode_append_system_prompt`, tokens, `error`, `exit_code` — read these directly
  for custom analysis.

---

## Validity checklist (what makes a result trustworthy)

1. **One variable.** The two modes differ in exactly one dimension; everything else identical.
2. **Default prompt kept.** Use `mode.append_system_prompt` (identical both arms), never
   `scenario.system_prompt`.
3. **Adoption checked.** A delta where the experimental tool was barely used (`tool_adopted`
   false / ~0 tool-under-test calls in `tool_sequence`) is native-vs-native noise, *not* a tool
   effect. Report adoption alongside every delta.
4. **≥5 reps for any claim.** Single-rep per-task deltas flip sign between identical runs.
5. **Ground truth verified** at the pinned commit with real tools before trusting a grader.
6. **Edit graders fail at baseline and provably discriminate** (complete → exit 0; incomplete →
   non-zero). Comprehension graders: 3–5 distinctive, verified strings.
7. **Tool-agnostic prompts** — never name a tool in a task's name/prompt/description.
8. **model id = a pricing key** in the runner YAML.
9. **Machine-path modes stay out of commits** (or parameterize the binary path) — a mode pointing
   at `/Users/you/.cargo/bin/...` is useless to anyone else.
10. **Controls (`control: true`) show ~no tool effect** — if a control flips, the corpus or grader
    is leaking the tool's advantage.

---

## Source of truth

The Pydantic models in `src/copeca/config/models.py` are authoritative for every field and enum;
`copeca validate` enforces them. Treat **this file** as the workflow + the rules, and treat the
**code** as the schema — when they disagree, the code wins, and this file is stale and should be fixed.
