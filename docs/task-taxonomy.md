# Task taxonomy

Every copeca task has two orthogonal classification axes — `type` and `category` —
plus an optional `control` flag (the non-regression marker, described below).
They answer different questions and must not be conflated with each other or with
`source` (which records provenance and contamination status, not capability).

---

## Axis 1 — `type` (grading axis)

`type` determines **how correctness is measured**.

| type | graded by |
|---|---|
| `comprehension` | `required_strings` / `forbidden_strings` / `all_of` — string matching on the agent's output |
| `edit` | `test_command` exit code — the task supplies a command that must exit 0 on corrected code |

No LLM judge, no embedded Python, no heuristics. Correctness is always strings
or exit codes.

---

## Axis 2 — `category` (capability axis)

`category` describes **what the task demands of the agent** — the cognitive or
retrieval challenge it poses. It is the dimension used to slice cost-per-correct
deltas in the report, revealing *where* a tool helps (or hurts) rather than just
by how much overall.

`category` is NOT the grading mechanism, and it is NOT `source`.

### The five categories

**`locate`** — Report one self-contained, named thing (a function, a constant, a
file, a configuration value). The answer is bounded and unambiguous.
Expected tool-delta: low. A single target is cheap to find by any retrieval
method; structured code-intelligence rarely has room to dominate.

**`trace`** — Map a relationship that spans files: callers of a function,
implementors of an interface, a control-flow path from entry to effect. The
answer requires synthesising multiple locations into a coherent picture.
Expected tool-delta: HIGH. Cross-file relationship mapping is exactly where
structured code-intelligence should outperform linear search most decisively.

**`fix`** — Change code until a stated test passes. The task provides both the
broken state and the objective success criterion.
Expected tool-delta: low. Once the defect is located the edit itself is
largely method-independent; the delta is dominated by the locate sub-problem.

**`debug`** — Diagnose a defect via git history (blame, bisect, commit diff),
then resolve or explain it. The evidence is distributed across commits, not
just across files.
Expected tool-delta: HIGH. Cross-commit diagnosis is painful without tooling;
an agent that can query history structurally has a real advantage.

**`reason`** — Comprehend code that is given *in full in the prompt* (a
self-contained snippet); the answer needs no navigation, search, or history.
Expected tool-delta: ~zero by design — these are the **non-regression controls**
(see below). A codebase tool that changes the outcome here is adding overhead,
not earning its cost.

### Boundary rule

When in doubt between `locate` and `trace`: **one self-contained thing →
`locate`; a relationship or multiple linked locations → `trace`.**

---

## type × category invariant

Not all combinations are valid. The following is enforced by a `model_validator`
in `src/copeca/config/models.py` and checked by `copeca validate`:

| type | allowed categories |
|---|---|
| `comprehension` | `locate`, `trace`, `debug`, `reason` |
| `edit` | `fix`, `debug` |

`debug` spans both types deliberately: explaining what a commit broke is
`comprehension + debug`; finding and correcting a regression so its test passes
is `edit + debug`.

---

## The `control` flag — the non-regression set

Orthogonal to both axes, a task may set **`control: true`**. This marks a
*tool-neutral* task — one where a codebase tool (search, context-compression,
memory, indexing) **should not** change the outcome, because the work needs no
codebase interaction. Controls are typically `reason` (answer-in-context) or a
single-file `fix`.

The report measures the tool's cost-per-correct delta **on the control tasks
only** and surfaces it as a separate *Control (Non-Regression)* section. Because
lower cost-per-correct is better, the reading is:

- **near-zero delta (CI includes 0)** — healthy: the tool is neutral where it
  should be.
- **significantly positive delta** — ⚠ regression: the tool made neutral work
  *cost more per correct answer* (latency, token tax, or distraction). The tool
  is not free.
- **significantly negative delta** — the tool also helped on supposedly neutral
  tasks; verify the controls are genuinely tool-neutral.

Controls are what let a headline gain be trusted: a tool that lifts `trace` (+)
while staying neutral on controls (~0) earned a real, non-specialised win.

---

## Description convention

Each task's `description` field follows the pattern:

> `<demand on the target>; tests <capability + the specific challenge>.`

One example per category:

- **locate** — `"Return the name of the middleware function that sets CORS headers in gin's default engine; tests symbol lookup in a mid-sized Go web framework."`
- **trace** — `"List every caller of fastapi's dependency-injection resolver across the test suite; tests cross-file call-graph traversal in a Python async codebase."`
- **fix** — `"Make the failing ripgrep Unicode boundary test pass by correcting the regex escape in the affected function; tests targeted code repair in a Rust CLI."`
- **debug** — `"Identify the commit that introduced the off-by-one in express's route-match loop and state why it breaks nested routes; tests cross-commit defect diagnosis in a Node.js framework."`

Descriptions are one line. They name the information or outcome required, not
the method used to reach it.

---

## Tool-agnosticism requirement

A task must name the **information or outcome** required, never the **method**.
This is enforced by `src/copeca/agnosticism.py`, flagged by `copeca validate`,
and verified by a test that scans every packaged task.

**Forbidden in any task field:**

- Tool or product names: `tilth`, `grok`, `ctags`, `LSP`, `ripgrep-mcp`, etc.
- Method-prescribing verbs: "search for", "grep", "use X tool", "run a query"
- Output-shape cues that reward one tool's form: "one structured answer",
  "consolidated view", "piecemeal", "single call", "several searches"

**Allowed:** repository names used as the task's *subject* (`ripgrep`, `gin`,
`express`, `fastapi`) — these identify the codebase under examination, not the
retrieval method.

**Rationale:** the retrieval method is the variable under test in the A/B.
Prescribing it pre-judges the experiment.
