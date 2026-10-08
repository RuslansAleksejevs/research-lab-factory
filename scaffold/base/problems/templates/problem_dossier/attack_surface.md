# Mathematical Attack Surface: {{TITLE}}

Status: `UNINITIALIZED`.

## Target Contract

- Problem ID: `{{PROBLEM_ID}}`
- Stable target ID / SHA-256:
- Exact statement/version: `context_envelope.md`
- Mathematical status: `UNKNOWN`
- Coefficients:
- Tate twists/weights:
- Degree conventions:
- Support theory:
- Boundary and degenerate cases:
- Explicit anti-targets:

Changing the target requires a new context-envelope version and a recorded
round decision. A route may not repair itself by silently weakening the claim.

## Object and Map Type Table

| ID | Object/map | Source | Target | Coefficients | Twist/weight | Degree shift | Support/variance | Construction/source | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

"By functoriality", "projection formula", "trace compatibility", and "twists
are harmless" do not close a row. Name the exact map and theorem.

## Hypothesis-Preservation Table

| Reduction ID | Before | Operation | After | Later hypotheses | Preservation evidence | Failure witness | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |

## Prioritized Attack Matrix

Statuses: `UNTESTED`, `SURVIVED`, `FAILED`, `INCONCLUSIVE`,
`NOT_APPLICABLE`.

Priorities:

- `P0`: cheap test that can expose a type failure, counterexample, or
  circularity;
- `P1`: substantive source, compatibility, or boundary gate before promotion;
- `P2`: robustness or generalization test after core validity.

| Attack ID | Priority | Target step | Failure mode | Minimal witness/test | Verifier | Independence | Evidence required | Status | Route consequence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

At minimum instantiate attacks for:

1. exact statement and anti-target compliance;
2. every degree, coefficient, twist, domain/codomain, and support transition;
3. preservation of hypotheses under each reduction;
4. circularity and equivalent-strength missing lemmas;
5. smallest examples and degenerate/boundary cases;
6. counterexample search for each decisive `GS3` lemma;
7. exact primary-source checks for substantive imports;
8. local-to-global gluing, choice-independence, and compatibility claims;
9. analogy leakage and unsupported generalization;
10. verifier lineage, shared-context correlation, and self-certification.

## Candidate Gate

An approach cannot become `UNDER_AUDIT` until all applicable mandatory attacks
have evidence. `INCONCLUSIVE` remains an open obligation. Consensus, eloquence,
agent count, and wall-clock time never change it to `SURVIVED`.

Failure mapping:

- bounded omission → `GS1`;
- unverified source/type/compatibility → `GS2`;
- strictly narrower new lemma → `GS3`;
- circular/equivalent-strength gap → `GS4` and `BLOCKED`;
- checked counterexample/type contradiction/false indispensable import → `GS5`
  and `REFUTED`.

## Exit Summary

- Candidate version audited:
- Candidate ID / SHA-256:
- `attack_surface_exit_manifest.yaml` artifact / SHA-256:
- Decisive verifier(s) and independence:
- P0 attacks remaining:
- P1 attacks remaining:
- Failed/inconclusive attacks and consequences:
- Surviving exact scope:
- Source audit status:
- Recommended root decision: `REPAIR / TARGET_GAP / BLOCK / REFUTE / SECOND_AUDIT / CLOSE`
