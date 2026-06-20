# Known Limitations

Copeca's methodology has constraints worth understanding before relying on
its numbers. Each limitation is tracked against the architectural invariants
(`architecture.md` §1).

---

## Bootstrap CI assumes task independence

The 95% bootstrap confidence interval treats each run as independent and
identically distributed. When tasks are correlated (e.g., several target the
same repo with the same tool), the independence assumption is imperfect.
The bootstrap is still more honest than parametric CIs on ratio statistics,
and the per-task breakdown in the report lets you spot correlated failures.

## Adversarial flags are heuristics, not proofs

`token_snowball`, `talkative_failure`, and `tool_storm` use configurable
thresholds. They catch obvious patterns (an agent burning 10x more tokens on
turn 5 than turn 1) but may miss subtle waste or flag borderline cases.
Threshold tuning is task-corpus-dependent. Flags that depend on data the
runner does not provide are `null`, not `false`.

## Pricing data goes stale

Token prices are YAML files with an `updated` field. Copeca warns when the
pricing table is older than 30 days but does not block runs. A pricing change
between two runs of the same scenario breaks comparability — use the same
pricing table version for all modes in a comparison.

## Seed corpus is 16 tasks from 1 source family (planned: 5 more)

The current seed corpus contains 16 tasks, all from the `SWE-QA (Apache-2.0)`
source family. The roadmap targets approximately 85 tasks drawn from 6 independent
source families (SWE-QA, SCBench, Long Code Arena, CrossCodeEval,
SWE-bench-Live, Terminal-Bench 2.0). A corpus dominated by one source risks
overfitting — a tool that performs well on SWE-QA tasks may not generalize.

## check-task mutation validity CLI not yet built

The `check-task` subcommand that pre-verifies edit task mutations (test passes
on clean code, fails on mutated code) is not yet implemented as a CLI command.
The mutation engine itself (`src/copeca/tasks/mutations.py`) is complete and
tested. Until the CLI wrapper is built, mutation validity must be verified
manually or via the orchestrator's edit-task pipeline.

## Matrix runner is sequential

The `max_workers` field in scenario YAML is acknowledged but deferred.
`orchestration/run.py:run_matrix()` iterates tasks x modes x reps sequentially
in nested loops. Parallel workers would reduce wall-clock time for large
scenarios (~200+ runs) but are not yet wired.

## test_command_passed always None in orchestrator

In `orchestration/run.py:run_single()`, the call to `check_correctness` passes
`test_command_passed=None` with a comment: `# mode-mechanism will wire this
from subprocess`. The mode mechanism that would run the test command as a
subprocess and pass the exit code is deferred. In practice this means edit
tasks are currently graded only by `required_strings`, not by the test
command exit code.

## Layer 3 repo validation requires --repos flag on validate

The `copeca validate` command checks task YAML against the JSON Schema but
does not automatically cross-reference the `repos.yaml` registry unless the
`--repos` flag is provided. Tasks referencing repos not in `repos.yaml` will
pass schema validation and only fail at runtime when the worktree manager
cannot find a bare clone.

---

## References

- [architecture.md](architecture.md) §1 — architectural invariants
- [methodology.md](methodology.md) — known limitations section with more detail on
  bootstrap CIs, adversarial flags, pricing staleness, string matching brittleness
- [metrics.md](metrics.md) — cost-per-correct math, delta formula, bootstrap CI
