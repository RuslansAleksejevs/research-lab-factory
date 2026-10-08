# Formalization Checkpoint

Status: DRAFT

Publish checkpoints append-only. Correct an error with a successor checkpoint,
never by overwriting the old one.

## Identity and bindings

- Checkpoint ID:
- Campaign / problem / case IDs:
- Recorded at / by:
- Lean Room state sequence / artifact SHA-256:
- Campaign artifact / SHA-256:
- Proof blueprint artifact / SHA-256:
- Previous checkpoint artifact / SHA-256:
- Source-tree SHA-256 before:

## Attempt

- Run and agent IDs:
- Mode:
- Exact experiment:
- Files, declarations, or library queries touched:
- Build or static result:
- Human or API-search time:
- Kernel or build time:

## Main-goal dependency delta

- Main goal ID:
- Unresolved dependencies before:
- Unresolved dependencies after:
- Added:
- Discharged:
- Split into smaller obligations:
- Reopened:
- Correspondence obligations advanced:
- Evidence bindings:

## Redundant-lemma fingerprint

- Normalized proposed statement:
- Normalized hypotheses:
- Namespace and import context:
- Typeclass and coercion context:
- Search queries:
- Candidate existing declarations:
- Comparison result: UNASSESSED
- Allowed results: NEW_LEMMA_JUSTIFIED / EXISTING_LEMMA_REUSED /
  POSSIBLE_DUPLICATE / NO_MATCH_FOUND / UNASSESSED
- Decision evidence:

## Semantic-progress verdict

- Semantic progress: NO
- Rationale tied to the dependency delta or correspondence obligations:
- Compilation-only progress: NO
- Consecutive semantic no-progress checkpoints before:
- Consecutive semantic no-progress checkpoints after:

Line-count growth, more helper code, or recompiling the unchanged dependency
frontier is not semantic progress.

## Two-checkpoint intervention gate

- Intervention required: UNASSESSED
- Choice:
- Allowed choices: INDEPENDENT_AUDIT / PROOF_BLUEPRINT_EXPANSION /
  REPRESENTATION_PIVOT / CONTINUE_BOUNDED_WITH_RATIONALE /
  OTHER_RECORDED_INTERVENTION
- Rationale:
- Unchanged blocker:
- Discriminating observation sought:
- Stop condition:
- Intervention artifact / SHA-256:

If this is the second consecutive semantic no-progress checkpoint, review the
loop and normally pause it. Bounded continuation is allowed only with the
unchanged blocker, rationale, discriminating observation, and stop condition
recorded. It does not reset the count or upgrade status. Rephrasing the same
attempt is not an intervention.

## Next experiment

- Exact next experiment:
- Expected observable dependency delta:
- Source-tree SHA-256 after:
