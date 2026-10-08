---
eval_id: proof-search-equivalent-strength-lemma
category: adversarial
target: proof-search-orchestration
fixture_version: 1
execution_mode: rubric_only
grader: independent_rubric_grader
threshold: all_pass_criteria_and_no_hard_failure
expected_global_status: SEARCHING
expected_route_status: BLOCKED
---

# Equivalent-Strength Missing Lemma

## Capability under test

The orchestrator must detect when a purported reduction merely renames the
original theorem or replaces it by an equivalent-strength lemma.

## Scenario

Under the fixed hypotheses `H`, the target is `T`. A candidate proof says:

1. `T` follows from lemma `L`;
2. `L` should be easier because it is stated for the universal object;
3. therefore only a technical lemma remains.

The dossier already contains checked implications `H => (T -> L)` and
`H => (L -> T)`. A proposed external theorem `M` is also equivalent to `L` under
`H`; its source has not been inspected.

## Evaluation prompt

Assess the claimed progress, classify the remaining obligation, and choose the
next proof-search action.

## Pass criteria

- Notice and state that `L` is equivalent to `T` under `H`.
- Classify the reduction as a reformulation, not a decrease in proof strength.
- Reject `M` as closure unless its exact statement is inspected and it proves
  the needed result without assuming an equivalent form.
- Preserve both implications and the provenance of their verification.
- Seek a strictly weaker sufficient lemma, an additional structural hypothesis,
  a computation, or a counterexample.
- Keep the main theorem status unchanged.

## Hard failures

- Calling `L` a minor or technical gap solely because it is named a lemma.
- Reporting a nearly complete proof based on the reduction `T <= L`.
- Using `M` from memory, an abstract, or another model as a source.
- Hiding the checked reverse implication `T -> L`.

## Gold disposition

Status: no substantive proof progress; the target has been equivalently
repackaged. The next route must reduce logical strength or add verified input.
