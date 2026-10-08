# Lean Room Templates

Copy these files through the guarded case-creation command; do not treat a
template as a certificate artifact. Values containing `{{...}}` are unresolved
and must fail validation.

Canonical case files:

- `formalization_contract.yaml`: critical projection immutable after `LR0`,
  entire contract immutable after `LR1`;
- `correspondence_verdict.yaml`: machine-checkable independent LR4 attestation;
- `freeze_manifest.yaml`: one append-only snapshot record for each freeze gate;
- `formal_correspondence.md`: mathematical informal-to-formal comparison;
- `project/`: inert Lean project skeletons that require explicit rendering;
- `build_manifest.yaml`: one copy per append-only build run;
- `formal_audit_manifest.yaml`: one copy per independent audit;
- `formal_certificate_manifest.yaml`: one copy per exact-scope certificate;
- `formal_certificate_retraction.yaml`: append-only response to a later defect;
- `dependency_snapshot_manifest.yaml`: immutable source/Lake graph bindings
  for the noncertifying v2 dependency pilot path;
- `dependency_snapshot_review.yaml`: explicit package-configuration review and
  Phase-B execution authorization bound to one snapshot closure, including any
  exact `LAKE_REHASH_TRACKED_TRACE_CACHE` sidecar exception;
- `generator_prompt.md`: frozen-target prompt for a formalization worker;
- `auditor_prompt.md`: disjoint adversarial prompt for the decisive audit.

Campaign-planning files, rendered before a full formalization effort:

- `formalization_campaign.md`: suitability, assembly-gap, library-
  readiness, and representative vertical-pilot decision;
- `proof_blueprint.md`: detailed informal proof with all omitted standard facts
  expanded into typed obligations;
- `formalization_checkpoint.md`: append-only semantic-progress record with
  dependency delta and redundant-lemma fingerprint;
- `refactor_audit.md`: separate correctness/maintainability assessment and
  successor-case/re-audit decision for a material refactor.

These planning templates are not case evidence, do not enable Lean Room, and do
not relax any LR gate. Render them into the problem dossier's formalization
planning area, never over a prior checkpoint or audit.

They provide campaign-management defaults, not an allowed-method list. A
coordinator may skip, reorder, or replace a planning step with recorded
rationale and a bounded stop condition. Exact-target, execution-safety,
trusted-boundary, clean-build, independent-correspondence, certificate-scope,
and material-change revalidation gates remain mandatory for the claims to which
they apply.

Use JSON-compatible YAML for machine-readable manifests. SHA-256 values are
lowercase hexadecimal digests of exact file bytes unless a field explicitly
describes a deterministic tree digest. A `null`, empty required list, unresolved
template token, missing path, or digest mismatch fails the relevant gate.
An artifact never stores its own digest inside its hashed bytes; the containing
index or the next binding manifest records that digest.

The dependency snapshot and review are v2 pilot inputs, not v1 case files.
Phase-B evidence is emitted append-only by
`scripts/verify_lean_dependency_pilot.py`; do not hand-author a PASS record or
place its outcome under `LR2`–`LR6`.

The one defined exception-like convention is
`freeze.frozen_contract_sha256`: compute it from canonical JSON of the complete
final contract with that field set to `null`, then store the resulting digest
in the field. Verification restores `null`, canonicalizes again, and compares.
This is not an ordinary SHA-256 of the stored file bytes; manifests must label
it as the frozen-contract canonical digest.

The in-file case lifecycle is `DRAFT -> FROZEN`. This lifecycle is not an
`LR0`–`LR6` gate summary. `LR0` leaves status `DRAFT` but sets
`freeze.lr0_contract_frozen`: the critical projection is then immutable while
the project source, environment bindings, and freeze metadata needed for `LR1`
may be completed. A verifier accepts only `FROZEN` with both freeze flags true.
Supersession is not an in-file status mutation: record it in the successor
contract and append-only case index.

`LR0` hashes every top-level contract field except `status`, `environment`, and
`freeze`. Equivalently, the projection
contains identity and creation metadata, target and obligation bindings,
informal and formal claims, encoding, trust boundary, correspondence,
lineage, acceptance criterion, and stop conditions. `LR1` must reproduce that
digest before it may set status `FROZEN`. After `LR0`, only project sources,
environment bindings, freeze metadata, and the eventual status transition may
change.

The project skeletons deliberately do not name a current Lean release. Each
case must pin its own exact toolchain and dependency revisions. Generated
`lake-manifest.json` is evidence and therefore has no generic template.
