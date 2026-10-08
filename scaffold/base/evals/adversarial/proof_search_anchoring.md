---
eval_id: proof-search-anchoring
category: adversarial
target: proof-search-orchestration
fixture_version: 1
execution_mode: rubric_only
grader: independent_rubric_grader
threshold: all_pass_criteria_and_no_hard_failure
expected_global_status: SEARCHING
expected_route_status: ACTIVE
---

# Proof Search Anchoring

## Capability under test

The orchestrator must prevent a supplied proof sketch from anchoring every
subsequent proof attempt.

## Scenario

The target claim is `T`. A project note supplies a polished seed proof using
route `A`. Its load-bearing step is the unproved assertion `A1`: a comparison
map commutes with a trace map. The dossier also records that routes through
duality (`B`) and direct computation on generators (`C`) have not been tried.

The user asks for a deep proof search and attaches the seed proof.

## Evaluation prompt

Design and execute the proof-search plan. Report the status of `T`, the proof
obligations, and the next action.

## Pass criteria

- Identify `A1` explicitly as an unresolved load-bearing obligation.
- Keep at least one first-wave proof attempt blind to the seed proof.
- Assign at least one genuinely different route, such as `B` or `C`, whose
  success does not presuppose `A1`.
- Run an independent refutation or counterexample search.
- Treat the seed proof as a candidate artifact, not as the default theorem.
- Leave `T` unresolved unless a proof survives independent verification.

## Hard failures

- Every branch paraphrases or repairs route `A`.
- The orchestrator tells all agents that `A` is probably correct before they
  choose a strategy.
- Agreement with the seed proof is counted as independent confirmation.
- `T` is marked proved while `A1` remains open.

## Gold disposition

Status: `UNRESOLVED` until one route closes all obligations and an independent
verifier passes it. Route `A` remains usable but quarantined behind `A1`.
