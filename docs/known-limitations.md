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

`token_snowball`, `talkative_failure`, and `tool_storm` use hardcoded thresholds
(per-scenario configuration is planned). They catch obvious patterns (an agent
burning 10x more tokens on turn 5 than turn 1) but may miss subtle waste or flag
borderline cases. Flags that depend on data the runner does not provide are
`null`, not `false`.

## Pricing data goes stale

Token prices are YAML files with an `updated` field. Copeca warns when the
pricing table is older than 30 days but does not block runs. A pricing change
between two runs of the same scenario breaks comparability — use the same
pricing table version for all modes in a comparison.

## Seed corpus is 16 tasks, heavily skewed toward one source family

The current seed corpus contains 16 tasks spanning six source families, but
11 of 16 are from `SWE-QA (Apache-2.0)` and all target just four repositories
(express, fastapi, gin, ripgrep). The roadmap targets approximately 85 tasks
balanced across the six families (SWE-QA, SCBench, Long Code Arena,
CrossCodeEval, SWE-bench-Live, Terminal-Bench 2.0). A corpus this small and
this dominated by one source risks overfitting — a tool that performs well on
SWE-QA tasks may not generalize.

## Repo cross-validation is skipped when no repos.yaml is present

The `copeca validate` command checks task YAML against the JSON Schema and
auto-discovers a `repos.yaml` in the working directory to cross-reference repo
references. If no `repos.yaml` is present (and `--repos` is not passed), the
cross-reference is skipped: tasks referencing repos not in any registry pass
schema validation and only fail at runtime when the worktree manager cannot
find a bare clone.

## Correctness grading uses substring matching (gameable)

Comprehension task grading is case-insensitive substring matching on
`required_strings` and `forbidden_strings`. This is gameable: a wrong answer
that happens to contain the required keywords passes, and a correct paraphrase
that omits an exact token fails. Single-task verdicts are therefore noisy; the
intended signal is the aggregate delta across the corpus, where random noise
averages out. Semantic grading (embedding similarity, LLM judge) is planned but
is not in the scoring path (see `architecture.md` §8 — LLM judge is
deliberately excluded from scoring).

## Cost figures depend on the runner's self-report

The headline `total_cost_usd` is the vendor's billed cost when the runner reports
one (e.g. Claude Code's result-event cost). It is the real bill — it reflects cache
hits, cache TTL, service tier, and discounts — and it is frozen into the `.copeca`
artifact at run time, so later vendor price drift does not change a published
result. copeca also records `computed_cost_usd` (Σ tokens × a pinned price table)
as a reproducible, provider-neutral cross-check and as the fallback when no vendor
cost is reported.

Two honest caveats. (1) The computed figure is a **rough estimate** — it can differ
from the bill by ~30% because token counts cannot capture cache TTL (1h vs 5m
writes are priced differently), service tier, or discounts; copeca deliberately
does not model these, so a computed-vs-vendor divergence is informational, not
proof the vendor is wrong. (2) Both figures ultimately trace to the agent CLI's own
output (the billed dollar figure and the token counts are self-reported; copeca
does not independently re-tokenize the transcript). A runner that misreports both
consistently would mislead — the cross-check catches gross inconsistency between
the two, and artifact signing addresses provenance — but transcript re-tokenization
is planned. Token usage is now de-duplicated per message id; the parser previously
counted each assistant message's usage 2–3× because the stream emits it once per
content block.

## Edit task correctness is decided solely by test command exit code

For edit tasks, `check_correctness` treats the test command exit code as
authoritative (`validator.py:96-113`). Any `required_strings` or
`forbidden_strings` on an edit task are evaluated and stored in the result
record for diagnostics, but they do not affect the verdict. Only the test
command exit code determines whether an edit task run is counted as correct.

## Unsigned artifacts get corruption detection only, not tamper-evidence

The integrity manifest inside a `.copeca` zip (per-file SHA-256 + a content_hash
over them) catches accidental corruption, but an attacker who rewrites the zip
can recompute it — so an unsigned artifact is **not tamper-proof**. Real
tamper-evidence requires signing: `copeca run … --artifacts --sign-key
<private.pem>` writes a detached Ed25519 signature over the content_hash, and
`copeca verify ARTIFACT --pubkey <public.pem>` rejects any artifact a holder of
the private key did not sign. Two residual limitations: (1) verification trust
is only as good as the operator's out-of-band knowledge that a given public key
belongs to the claimed runner — copeca does not distribute or attest keys; and
(2) a signature proves *who produced* an artifact, not *when* — there is no
external append-only anchor, so a signer can still re-sign a later, cherry-picked
set under the same key. Batch completeness (`verify --batch --scenario`) is the
partial defence against selective publishing; external transparency-log anchoring
of content hashes is a planned further option.

---

## References

- [architecture.md](architecture.md) §1 — architectural invariants
- [methodology.md](methodology.md) — known limitations section with more detail on
  bootstrap CIs, adversarial flags, pricing staleness, string matching brittleness
- [metrics.md](metrics.md) — cost-per-correct math, delta formula, bootstrap CI
