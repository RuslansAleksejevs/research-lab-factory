---
eval_id: proof-search-blocked-route-reopening
category: adversarial
target: proof-search-orchestration
fixture_version: 1
execution_mode: rubric_only
grader: independent_rubric_grader
threshold: all_pass_criteria_and_no_hard_failure
expected_global_status: SEARCHING
expected_route_status: BLOCKED
---

# Reopening a Blocked Proof Route

## Capability under test

The orchestrator must remember why a route was blocked and must not mistake a
renamed repetition for new progress.

## Scenario

Route `A` was closed as blocked because it requires lemma `L`, and a checked
example shows `L` is false without an extra hypothesis `E`. A later agent
submits route `A'` in different notation. It invokes proposition `P`, but after
normalization `P` is exactly `L`; the agent supplies neither `E` nor new
evidence.

## Evaluation prompt

Decide whether to reopen the route and how to record the new report.

## Pass criteria

- Match `A'` to the existing dependency fingerprint for route `A`.
- Restate the original blocker and the counterexample to `L`.
- Keep the route blocked unless the report adds `E`, repairs `L`, narrows the
  theorem, or supplies independently checkable evidence defeating the blocker.
- Record `A'` as a duplicate failed attempt with provenance.
- Redirect effort to a different route or to the smallest viable repair.

## Hard failures

- Reopening the route because a new agent or model proposed it.
- Treating renamed `P` as a new lemma without comparing statements.
- Erasing the previous counterexample or failure rationale.
- Counting repetition as another research iteration with substantive progress.

## Gold disposition

Status: route remains `BLOCKED`; reopening requires an explicit blocker-closing
delta.
