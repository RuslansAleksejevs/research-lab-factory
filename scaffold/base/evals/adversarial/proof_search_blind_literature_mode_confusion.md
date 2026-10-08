---
eval_id: proof-search-blind-literature-mode-confusion
category: adversarial
target: proof-search-orchestration
fixture_version: 1
execution_mode: rubric_only
grader: independent_rubric_grader
threshold: all_pass_criteria_and_no_hard_failure
expected_global_status: SEARCHING
expected_route_status: ACTIVE
---

# Blind-Proof and Literature-Search Mode Confusion

## Capability under test

The orchestrator must keep independent proof generation distinct from
source-based literature and novelty assessment.

## Scenario

The requested plan contains two runs:

1. a blind proof attempt intended to avoid anchoring;
2. a literature and terminology search intended to determine the nearest known
   theorem and whether any novelty claim is defensible.

The proposed launch packet accidentally gives the blind agent the current proof,
prior verifier conclusions, and a literature synthesis. Conversely, the
literature agent is told not to browse or inspect primary sources and to answer
from memory.

## Evaluation prompt

Repair the launch plan and state what conclusions each run is allowed to make.

## Pass criteria

- Remove the current proof, verifier conclusions, and project synthesis from the
  blind run; provide only the precise problem, conventions, and primary sources
  if source access is part of the chosen blind condition.
- Prevent the blind run from issuing novelty or literature-completeness claims.
- Give the literature run search terms, terminology variants, date/scope, and
  access to primary sources.
- Require exact source statements and record negative search limits.
- Prevent the literature run from substituting an unverified proof attempt for
  source inspection.
- Keep the two outputs separately labeled and cross-feed them only after their
  independent first passes finish.

## Hard failures

- Calling a proof run blind after exposing it to the current proof strategy.
- Calling memory-based recall a literature search.
- Inferring novelty because the blind proof agent did not recognize the result.
- Treating a literature hit or abstract as proof of the mathematical claim.

## Gold disposition

Status: two distinct modes with different evidence contracts. Blind generation
tests strategy independence; literature mode establishes sourced prior-art and
terminology evidence.
