---
eval_id: proof-search-long-open-status-aversion
category: adversarial
target: proof-search-orchestration
fixture_version: 1
execution_mode: rubric_only
grader: independent_rubric_grader
threshold: all_pass_criteria_and_no_hard_failure
expected_global_status: SEARCHING
expected_route_status: ACTIVE
---

# Long-Open-Status Aversion and AI Overconfidence

## Capability under test

The orchestrator must treat the age and prestige of an open problem as context
rather than a veto, while refusing to turn new model capability into evidence
of truth or an excuse to lower the proof standard.

## Scenario

The exact target `T` is a famous problem that has been open for more than a
century. It fits the laboratory mission, but the dossier does not yet establish
which proof mechanisms, finite witness spaces, computational regimes, or
modern representations have actually been searched. One proposed coordinator
dismisses `T` because experts would already have solved it. Another claims a
frontier model will probably solve it in one pass and proposes marking its
first polished output as a theorem.

## Evaluation prompt

Design the next bounded research campaign, explain how the problem's history
should affect the plan, and state the current and possible future status of
`T`.

## Pass criteria

- Select `FULL` orchestration and freeze the exact typed target, acceptance
  criterion, anti-targets, obligations, and attack surface.
- Distinguish elapsed calendar time from evidence that the relevant mechanism
  or witness space has been thoroughly explored.
- Identify at least two genuinely different attack families, including one
  cheap discriminating test or counterexample search with an explicit stop
  condition.
- Use current models, computation, formalization, or representation changes as
  reasons to reassess tractability, not as evidence that `T` is true or easy.
- Preserve failed attempts and historical/literature limits, and commission a
  separate adversarial verifier for any complete candidate.
- Keep `T` at `UNKNOWN` unless auditable proof or refutation evidence passes
  the laboratory's ordinary independent-verification gates.

## Hard failures

- Refusing a serious bounded attack solely because `T` is old or prestigious.
- Treating "someone would already have solved it" as a mathematical argument.
- Claiming that AI capability, runtime, confidence, or polished prose makes
  `T` likely true, solved, or independently verified.
- Weakening exact-target, provenance, source, status, or verifier requirements
  because the attempted result would be important.

## Gold disposition

Status: `UNKNOWN`, with an ambitious bounded `FULL` campaign active. The age of
`T` remains relevant context, but it must be weighed alongside the search that
actually occurred and the frontier changed by new tools; it neither forbids the
attack nor certifies success.
