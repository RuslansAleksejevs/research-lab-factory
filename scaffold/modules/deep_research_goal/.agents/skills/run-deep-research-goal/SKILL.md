---
name: run-deep-research-goal
description: Prepare, execute, checkpoint, and evaluate a budgeted inference-time-scaled mathematical research campaign in a generated laboratory. Use when the user asks for Scout, Trial, Deep, or explicitly authorized Marathon research; asks to try many independent approaches, run a long proof search, attack a treasure-hunt candidate, or measure verified mathematical information gained per compute.
---

# Run Deep Research Goal

Use the laboratory root as the working directory. Read
`workflows/deep_research_goal_protocol.md` before preparing or running a
campaign.

## Freeze the goal

1. Select the smallest mode that fits the authorized work:
   `SCOUT` (30 minutes), `TRIAL` (2 hours), `DEEP` (6 hours), or separately
   confirmed `MARATHON` (12, 24, or 32 cumulative hours).
2. Start from `templates/deep_research_goal.json`. For `TRIAL`, `DEEP`, and
   `MARATHON`, first create the canonical full target artifact from
   `templates/deep_research_target.json`, then repeat exactly the same
   statement, acceptance criteria, anti-targets, and traps in the goal request.
   Store it under `problems/active/<problem_id>/` with a target-bearing
   filename, and bind the same `problem_id` and `target_id` used by the kernel.
   Preserve sources, stopping rules, and structurally distinct mechanism
   families.
3. Run:

```bash
python3 scripts/deep_research_goal.py --root . prepare \
  --input path/to/goal-request.json
```

4. Read the resulting `approved_goal.json`; bind every run or Control Room
   scope to its `goal_id` and `plan_sha256`. Never silently edit the plan.
   Leave `research/deep_goals/.operation.lock` in place: its kernel lock is
   crash-released, and the file is deliberately persistent.

`SCOUT` may qualify up to twelve source-bound leads but may not start proof
campaigns. Inspect `LAB_PROFILE.json` before applying the funnel:

- If `discovery_portfolio` is installed, require its human stage gates before
  up to three `TRIAL` candidates and again before one `DEEP` target.
- If it is not installed, do not invent portfolio state or portfolio gates.
  Require the goal's `authorization` block to record the explicit user
  authorization for the selected mode and exact target. `MARATHON` still
  requires its separate duration-specific confirmation.

## Run the search

- Keep multiple mechanism-distinct routes alive.
- Give each route its own obligation/dependency decomposition of the frozen
  target. Do not merely assign several agents the same breakdown. Compare the
  decompositions by their cheapest discriminating subproblem; if two routes
  collapse to the same load-bearing gap, merge or stop one rather than paying
  twice for duplicate search.
- Search for cheap counterexamples and edge cases before elaborating a route.
- Mark a route blocked when it only reduces the target to an unproved claim of
  comparable strength.
- Diagnose failures and reallocate compute to distinct mechanisms.
- Reserve 15–20% for checking before any audit-worthy mathematical candidate
  appears. Switch monotonically to 30–40% after one appears.
- Use a decisive verifier that is independent of the generator or material
  reviser. Preserve the kernel's source, exposure, lineage, computation, and
  `I3` gates.
- Stop at the plan's wall-time cap even when the mathematical target remains
  open. A caller needs a bounded outer runner for a hard process timeout.

For `DEEP` through Control Room, place the exact goal ID and plan digest in the
existing reviewed `run-rounds.v1` scope. Do not add or infer a Control Room
action. Run `MARATHON` only after a separate duration-specific confirmation;
prepare each stage as a fresh goal of at most six hours and bind it to the
previous plan and immutable outcome under one campaign ID. Preserve the exact
target contract. Never use a
retry or second outcome to reset cumulative elapsed time.

## Record the outcome

Start from `templates/deep_research_outcome.json`, then run:

```bash
python3 scripts/deep_research_goal.py --root . record-outcome \
  --goal-id <goal-id> --input path/to/outcome.json
python3 scripts/deep_research_goal.py --root . status --goal-id <goal-id>
python3 scripts/deep_research_goal.py --root . validate --goal-id <goal-id>
```

Record exact discharged, falsified, narrowed, and open obligations, evidence
paths, generator/material-reviser/verifier run IDs, elapsed time, and attempt
counts. For a verified closure those IDs must exactly match the kernel state;
the CLI derives no independence from self-chosen aliases. Proof,
refutation, an exact proved lemma, a checked counterexample, or a decisive
barrier counts only with evidence and a strict semantic reduction. Activity,
prose, agent count, and confidence are `NO_STRICT_REDUCTION`.

Mark outer-runner token counts as reported but unauthenticated until a
runner-bound receipt exists. Mark user-entered usage untrusted and missing
usage unscored, never zero cost. A `VERIFIED_PROOF` or
`VERIFIED_REFUTATION` outcome also needs a bound kernel proof-search state that
passes the ordinary `I3` validator.

The outcome record never promotes a theorem status. Use the normal dossier and
ledger verification gates for any status change.

After the immutable deep-goal outcome validates, use
`record-research-checkpoint` to publish one compact dated Durable Research
Memory envelope that links that outcome and its evidence. Do not reproduce the
campaign narrative in a second log. If the execution context is read-only,
return the schema-valid proposed checkpoint input as `NOT_PERSISTED` for the
authorized coordinator.
