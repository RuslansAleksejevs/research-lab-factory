# Formalization Refactor Audit

Status: DRAFT

Separate correctness and maintainability passes are recommended for audit
clarity, not as a mandatory proof order. Regardless of order, this artifact
decides whether a refactor needs a successor case and fresh evidence.

## Identity

- Refactor audit ID:
- Campaign / problem IDs:
- Recorded at / by:

## Correctness baseline

- Predecessor case ID:
- Frozen contract SHA-256:
- Source-tree SHA-256:
- Correspondence verdict artifact / SHA-256:
- Certificate artifact / SHA-256, if any:
- Highest completed LR gate:

The predecessor certificate remains bound to these bytes and cannot transfer.

## Maintainability goal

- Motivation:
- Readability targets:
- Naming or API targets:
- Lemma-granularity targets:
- Dependency-hygiene targets:
- Explicit non-goals:

## Proposed change inventory

- Formal source changes:
- Helper-lemma or declaration-surface changes:
- Representation changes:
- Import or dependency changes:
- Trusted-boundary changes:
- Proof-blueprint changes:
- Correspondence-argument changes:
- Prose or navigation-only changes:

## Materiality decision

- Verdict: UNASSESSED
- Allowed verdicts: NONMATERIAL / MATERIAL / UNASSESSED
- Rationale:
- Independently reviewed by:

Any formal-source change after LR1, helper/declaration-surface change,
representation change, import/dependency change, trusted-boundary change, or
semantic-correspondence change is material.

## Successor case and required rechecks

- Successor case required: UNASSESSED
- Successor case ID:
- `supersedes_case_id`:
- New source-tree SHA-256:
- Fresh static validation complete:
- Fresh candidate build complete:
- Fresh independent build complete:
- Fresh trusted-boundary audit complete:
- Fresh correspondence audit complete:
- Fresh certification build complete, if a certificate is sought:
- Predecessor evidence inherited: NO

## Correspondence delta

- Quantifiers or hypotheses changed:
- Formal declaration type changed:
- Encoding map changed:
- Edge-case behavior changed:
- Direction back to the informal target re-established:
- Open obligations:

## Successor evidence bindings

- Candidate run:
- Independent run:
- Correspondence verdict:
- Independent audit:
- Certificate, if issued:

## Verdict and explicit non-claims

- Verdict: DRAFT
- Maintainability improvement alone does not establish correctness.
- A material refactor requires a successor case and fresh applicable LR gates.
- A predecessor PASS or certificate is context, never inherited evidence.
