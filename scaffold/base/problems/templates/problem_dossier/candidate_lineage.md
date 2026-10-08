# Candidate Lineage: {{TITLE}}

Status: uninitialized until a candidate is frozen; not a proof certificate.

- Problem ID: `{{PROBLEM_ID}}`
- Stable target ID:
- Target artifact:
- Target SHA-256:
- Canonical candidate ID:
- Candidate artifact:
- Candidate SHA-256:
- Approach family:
- Date frozen:
- Dependency-snapshot manifest and SHA-256:
- Audit-packet manifest and SHA-256:

## Originating run IDs

Use exact platform thread/task/run IDs. For imported historical work, record a
stable backfill ID plus a target-bound `historical_backfill_manifest.yaml`
path/digest binding the route, initial status, time, and nonempty source
artifacts/digests including the transition evidence itself.

- `[RUN-ID]`: `[role and evidence path]`

## Material-repair run IDs

Include every run whose mathematical input changed the frozen candidate.

- `[RUN-ID]`: `[repair and evidence path]`

## Decisive-verifier exclusion set

- Excluded run IDs:
- Machine-state field holding this artifact's SHA-256:
- Required exposure-manifest fields: problem/target/candidate/verifier IDs and
  digests, exact originating/material-repair ID sets, exposure-log path/digest,
  audit-packet path/digest and all packet role entries, prior material withheld,
  date/time, and root assignment record.

## Backfill and snapshot limits

A backfill manifest is a target-bound provenance record for the first imported
transition; it must not replace or compress known history. Current-snapshot
validation cannot prove that earlier events were never deleted, so preserve
repository history, review evidence, or an external append-only anchor.

Any target or candidate content change creates a new ID/digest and invalidates
verdicts bound to the old version. Any route-ancestry, inherited-gap ID, or
discharge change creates a new dependency snapshot and audit packet and
invalidates records bound to the old packet. These bindings do not authenticate
the named runs or prove their mathematical work.
