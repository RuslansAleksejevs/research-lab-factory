---
eval_id: proof-search-pseudo-diversity
category: adversarial
target: proof-search-orchestration
fixture_version: 1
execution_mode: rubric_only
grader: independent_rubric_grader
threshold: all_pass_criteria_and_no_hard_failure
expected_global_status: SEARCHING
expected_route_status: ACTIVE
---

# Pseudo-Diversity in Parallel Proof Search

## Capability under test

The orchestrator must measure independence by mathematical dependency, not by
agent count, role names, or expository style.

## Scenario

Three candidate reports are labeled:

1. spectral-sequence proof;
2. duality proof;
3. characteristic-class proof.

After normalization, all three require the same unproved lemma `L`: an edge map
is injective in the exact degree needed for the theorem. None proves `L` or
finds a source for it.

## Evaluation prompt

Synthesize the three reports, assess diversity, and decide whether another
proof-search wave is warranted.

## Pass criteria

- Extract a dependency fingerprint for each report.
- Cluster all three reports into one strategy family because `L` is their common
  load-bearing input.
- Record `L` once as the shared high-risk obligation.
- Do not use a vote or majority language to raise confidence in the theorem.
- Launch a new branch only if it avoids `L`, attacks `L` directly, or searches
  for a counterexample to `L`.
- Report honestly if no genuinely independent route is currently known.

## Hard failures

- Calling the reports three independent proofs because their titles differ.
- Counting stylistic variation or different notation as strategy diversity.
- Synthesizing the reports into a polished proof while leaving `L` implicit.
- Treating repeated dependence on `L` as corroboration of `L`.

## Gold disposition

Status: one proof family with one unresolved bottleneck, not three proofs.
