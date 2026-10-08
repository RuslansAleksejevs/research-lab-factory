# Laboratory Stewardship Runs

Each subdirectory is one append-only, hash-bound maintenance transaction:

```text
<run-id>/
  inventory_before.json
  diagnosis.md
  repair_plan.json
  frozen_plan.json
  staged/
  before/
  before.sha256
  prepared_attestation.json
  added_paths.txt
  apply_journal.jsonl
  after.sha256
  validation.json
  post_survey_resume.json
  report.md
  completion_basis.json
  manifest.json
```

The run script freezes exact staged after-images, preserves every overwritten
preimage before application, rejects deletion and unplanned paths, and records
partial application precisely. Do not edit a frozen plan, backup, journal, or
completion basis. If a process stops during `APPLYING`, `PARTIAL_APPLY`,
validation, or survey publication, run `laboratory_stewardship.py resume`; it
reconstructs the phase only from sealed artifacts and exact live bytes.

Stewardship packets are excluded from the ordinary project-state survey basis
to prevent self-reference. A successful final survey explicitly binds and
rechecks the immutable `completion_basis.json` instead.

These records establish transaction provenance only. They do not prove
mathematics, source truth, novelty, value, or actual verifier independence.
