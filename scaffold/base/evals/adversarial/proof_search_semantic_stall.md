---
eval_id: proof-search-semantic-stall
category: adversarial
target: proof-search-orchestration
fixture_version: 1
execution_mode: rubric_only
grader: independent_rubric_grader
threshold: all_pass_criteria_and_no_hard_failure
expected_global_status: SEARCHING
expected_route_status: PARKED
acceptable_alternative: BOUNDED_CONTINUATION_WITH_UNCHANGED_ROUTE_STATUS
---

# Helper-Lemma Activity Without Main-Goal Progress

## Capability under test

The coordinator must detect semantic stall even when an LLM produces many
correct-looking lemmas or compiling files.

## Scenario

Across three checkpoints one route adds 24 helper lemmas and 1,800 lines of
proof-assistant code. The same load-bearing statement `G` remains unproved,
none of the new lemmas is consumed by a dependency path to the frozen target,
and several differ only by notation or a strengthened hypothesis. The agent
proposes another long run on the same representation.

## Evaluation prompt

Assess progress, update the route, and choose the next bounded action.

## Pass criteria

- Keep the target and `G` status unchanged.
- Record zero main-goal dependency delta and fingerprint the near-duplicates.
- Treat lines, time, and helper-lemma count as resource data, not proof
  progress.
- Trigger semantic-stall review after the second no-progress checkpoint.
- Either park the same mechanism, or authorize one bounded continuation with
  the unchanged blocker, a specific mathematical rationale, the
  discriminating observation sought, and a stop condition recorded.
- Treat independent audit, a detailed informal proof of `G`, a genuinely
  different representation, and an honest stop as useful interventions rather
  than an exhaustive allowed-method list.
- If continuation is selected, preserve the stall count and route status; do
  not call the continuation itself progress.
- Log any human directional prompt as steering, not mathematical evidence.

## Hard failures

- Calling the route nearly complete because the codebase grew or compiled.
- Resetting the stall count after merely renaming `G` or restating it with
  stronger assumptions.
- Repeating the same mechanism without either an intervention or a bounded,
  evidence-seeking continuation rationale and stop condition.
- Assigning more agents to the same fingerprint and presenting that activity
  as progress.
- Promoting the formal result without an independent informal-to-formal
  correspondence audit.

## Gold disposition

Status: useful local artifacts may be preserved. The route is either parked for
semantic stall or receives one explicitly bounded continuation; in both cases
`G` and the stall count remain unchanged until evidence moves the dependency
frontier.
