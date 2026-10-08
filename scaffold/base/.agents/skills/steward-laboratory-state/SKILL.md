---
name: steward-laboratory-state
description: Deeply audit, repair, validate, and re-survey one mathematical research laboratory when the user says "put/bring the laboratory in order", "clean up the lab", «приведи лабораторию в порядок», «наведи порядок в лаборатории», asks for a serious maintenance pass with strong reasoning, or wants accumulated research, statuses, bookkeeping, failures, and future directions reconciled rather than merely reported. Use survey-laboratory-state instead for a read-only overview.
---

# Steward Laboratory State

Treat stewardship as a bounded, evidence-conservative maintenance transaction,
not as permission to declare the mathematics solved. Read and follow
`workflows/laboratory_stewardship_protocol.md` completely.

1. Confirm that the current project is one laboratory, not the factory. Default
   to `DEEP_LOCAL`; use `STANDARD_LOCAL` only when the user requests a lighter
   pass. Do not browse, transmit project material, alter architecture, delete
   evidence, or widen the task to other laboratories without separate explicit
   authorization.
2. Start a hash-bound run with `scripts/laboratory_stewardship.py start`. Audit
   every track, dossier, result, ledger, checkpoint, source dependency,
   failure, output, warning, backlog item, and pending decision before staging
   any repair.
3. Use bounded read-only scouts for independent track, source, proof/status,
   output, and direction assessments when the laboratory is nontrivial. Keep
   exact artifact paths and source vocabularies. Model agreement, polish, and
   structural checks are never mathematical evidence.
4. Write a finite `repair_plan.json` and stage exact proposed after-images under
   the run packet. Classify each change. Defer deletions, mission/scope changes,
   ambiguous status changes, external searches, expensive new campaigns, and
   choices that materially depend on the user.
5. Freeze the plan with `prepare`, then apply it only through the stewardship
   script. Never edit a planned live path before its preimage has been backed up
   and hash-bound. Stop on drift, path collision, validation failure, or an
   unplanned change.
6. Route substantive work through the existing proof, verification, source,
   and ledger skills. A material proof repair creates a new candidate identity
   and needs a fresh decisive audit. Record an existing promotion only when the
   exact claim scope and complete independent `I3` closure already agree and
   `validate_proof_search.py` passes; `validate_ledgers.py` alone is
   insufficient. Require identical claim/target/problem identities across the
   plan and evidence. Do not create or rewrite `results/verified/**` in v1.
7. Apply cheap nonsemantic repairs and useful evidence-backed reconciliation.
   New mathematical ideas remain explicitly unverified and live in normal
   dossiers, results, or checkpoints, not only in the maintenance report.
8. Write the final report with
   `templates/laboratory_stewardship_report.md`, then run `finalize`. Completion
   requires doctor, all validators, the full eval without report mutation, a
   refreshed resume, and a stable persisted final survey bound to the immutable
   stewardship completion basis.
9. If application or finalization is interrupted, inspect the recorded phase
   and use `scripts/laboratory_stewardship.py resume`. Never repair a transaction
   packet by hand; recovery accepts only frozen preimages and exact after-images.
10. Return the post-repair whole-project picture: exact repairs, strongest
   established results, remaining weaknesses and conflicts, preserved failed
   routes, ranked next rounds, deferred user decisions, validation results, and
   the final survey path. A run may complete while deep mathematics remains
   open; "in order" means the state is honest, auditable, and ready for the next
   effective round.
