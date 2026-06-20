# Methodology: how copeca works

Copeca is a measurement instrument for CLI coding agents. Its design follows
from five architectural invariants: reproducible, verifiable, isolated,
comparable, and extensible.

---

## Delta, not absolute

The headline metric is always the **delta** between two modes — an
experimental tool against a clean baseline, run against the same tasks, same
model, same repetitions. Absolute cost-per-correct values are shown for each
mode, but the delta is what the report leads with.

This is deliberate: tools report savings in incomparable ways ("-90% tokens!"
on their own methodology). Copeca standardizes the measurement so two tools
can be compared against the same baseline and the numbers mean the same
thing.

---

## Per-task transparency

Every task's individual cost and correctness is shown in the report, not just
the aggregate. A tool that performs brilliantly on 8 tasks and catastrophically
on 2 is distinguishable from one that performs adequately on all 10. The
aggregate alone hides failure modes; the per-task breakdown surfaces them.

Copeca reports:
- Cost and correctness per task per mode
- Per-mode aggregates with bootstrap CIs
- Per-task delta (experimental vs baseline cost-per-correct)
- Adversarial flag counts per mode

---

## Independent governance

The task corpus draws from six independent source families, chosen to avoid
the contamination and provenance problems that forced the deprecation of
other benchmarks:

| Source family | Task type | License |
|---|---|---|
| SWE-QA | Comprehension | Apache-2.0 |
| Long Code Arena | Comprehension | MIT |
| CrossCodeEval | Comprehension, Edit | MIT |
| SWE-bench-Live | Edit | MIT |
| SCBench | Comprehension | CC BY 4.0 |
| Terminal-Bench 2.0 | Edit | MIT |

No source family dominates. If one source's tasks systematically favor a
particular tool, the other five dilute the effect.

---

## Provenance

Every task carries a `source:` field with:
- Source benchmark name
- License
- Original commit or release tag
- Any transformation applied (e.g., "comprehension → edit", "language port")

Tasks from blocked sources — NonCommercial, ShareAlike, no-license, or
confirmed-contaminated — are rejected at validation time. The full provenance
chain is recorded in every `.copeca` artifact zip.

---

## Mode isolation

Each mode (baseline and experimental) runs with its own:
- Agent config directory (no inherited hooks or settings)
- Environment variables (no ambient API keys or proxy URLs)
- Git worktree (no shared mutation state)

The baseline is provably clean: it gets an empty config directory and no mode
provisioning. If the experimental mode's tool leaks into the baseline, the
measurement is contaminated and the delta is meaningless.

---

## Correctness model

Tasks are graded objectively, without an LLM judge:

**Comprehension tasks** — string matching. The answer must contain all
`required_strings`, none of the `forbidden_strings`, and match all `all_of`
entries (the agent listed every item, not just one).

**Edit tasks** — test-command exit codes. The task specifies a command that
must exit 0 on corrected code. `copeca check-task` pre-verifies that the test
passes on clean code and fails on mutated code, proving the mutation bites.

No embedded Python. No eval. No LLM judge. Correctness is always strings or
exit codes.

---

## Known limitations

Copeca's methodology has constraints worth understanding:

1. **Bootstrap CI assumes i.i.d.** — The 95% bootstrap confidence interval
treats each run as independent and identically distributed. If tasks are
correlated (e.g., several target the same repo with the same tool), the
independence assumption is imperfect. The bootstrap is still more honest
than parametric CIs on ratio statistics.

2. **Adversarial flags are heuristics.** — `token_snowball`, `talkative_failure`,
and `tool_storm` use configurable thresholds. They catch obvious patterns
but may miss subtle waste or flag borderline cases. Threshold tuning is
task-corpus-dependent.

3. **Pricing data goes stale.** — Token prices are YAML files with an `updated`
field. Copeca warns at >30 days but does not block runs. A pricing change
between two runs of the same scenario breaks comparability — use the same
pricing table version for all modes in a comparison.

4. **String matching for comprehension tasks is brittle.** — A correct answer
with slightly different phrasing fails `required_strings`. A wrong answer
that happens to contain the right keywords passes. The `all_of` field
mitigates this by requiring all canonical entries, but comprehension
tasks are inherently coarser than edit tasks.

5. **Single-provider per scenario.** — All modes in a scenario must use the
same model from the same runner. Cross-provider comparison (Claude vs
Codex) requires separate scenarios with identical task sets. Cost
normalization uses one pricing table per runner.

6. **Task corpus is a sample.** — ~85 tasks cannot represent every coding
domain. Results may not generalize to tasks unlike those in the corpus.
This is inherent to all benchmarks and not a copeca-specific limitation,
but it is worth stating.

---

## References

- [architecture.md](architecture.md) — full architecture, data flow, invariants
- [engineering.md](engineering.md) — coding rules, testing, correctness invariants
- [metrics.md](metrics.md) — cost-per-correct math, delta formula, bootstrap CI
- [README.md](../README.md) — quick-start and scenario format
