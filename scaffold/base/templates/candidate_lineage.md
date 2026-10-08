# Candidate Lineage

Status: provenance and information-exposure record; not a proof certificate.

- Claim/problem ID:
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

Include every generator, synthesizer, critic, or reviser whose mathematical
input changed the frozen candidate.

- `[RUN-ID]`: `[repair and evidence path]`

## Decisive-verifier exclusion set

- Excluded run IDs:
- Machine-state field holding this artifact's SHA-256:
- Required exposure-manifest fields: problem/target/candidate/verifier IDs and
  digests, exact originating/material-repair ID sets, exposure-log path/digest,
  audit-packet path/digest and all packet role entries, prior material withheld,
  date/time, and root assignment record.

## Backfill and snapshot limits

A backfill manifest records the provenance supplied for the first imported
transition; it must not replace or compress known route history. The validator
sees the current snapshot only and cannot prove that earlier events were never
deleted. Preserve repository history, review evidence, or an external
append-only anchor where historical nondeletion matters.

Any target or candidate content change creates a new ID/digest and invalidates
verdicts bound to the old version. Any change to route ancestry, inherited gaps,
their stable IDs, or discharge records creates a new dependency snapshot and
audit packet and
invalidates exposure/report/closure records bound to the old packet. These
bindings do not authenticate the named runs or prove their mathematical work.
