# Approach Registry: {{TITLE}}

Status: initialized, not yet populated.

This Markdown registry is the auditable narrative and evidence view. In `FULL`,
`proof_search_state.yaml` is the canonical mutable record for current route IDs,
statuses, mathematical gaps, closure gates, transition history, frozen
candidate binding, run lineage, round, and verifier assignment;
update this file to agree with that state at every checkpoint.

## Registry Header

- Problem ID: `{{PROBLEM_ID}}`
- Stable target ID: `null` until initialization
- Exact target: `context_envelope.md`
- Exact target SHA-256: `null` until initialization
- Orchestration profile: `UNSET` until `LIGHT` or `FULL` is selected
- Current round: `0`
- Current mode: `UNSET` until context exposure is recorded
- Created: `{{DATE}}`
- Last updated: `{{DATE}}`
- Attack surface: `attack_surface.md`
- Proof obligations: `proof_obligations.md`
- Machine state: `proof_search_state.yaml`
- Canonical candidate ID / SHA-256: `null` until freezing
- Candidate-lineage artifact / SHA-256: `null` until freezing
- Proof-obligation/source-audit/attack-exit evidence and typed manifests:
  `null` until audit-ready; role artifacts must be pairwise distinct
- Dependency snapshot / audit packet: `null` until audit-ready
- Exposure/report/closure manifests: `null` until applicable

Canonical approach statuses:

`SEED`, `ACTIVE`, `CANDIDATE`, `UNDER_AUDIT`, `BLOCKED`, `REFUTED`, `MERGED`,
`PARKED`, `CLOSED_PROOF`, `CLOSED_COUNTEREXAMPLE`.

Canonical gap classes:

- `GS0 CLOSED`: proved, exactly imported, or formally/computationally checked.
- `GS1 LOCAL`: bounded repair with a clear plan.
- `GS2 SOURCE`: exact source, typing, or compatibility check missing.
- `GS3 SUBSTANTIVE`: genuinely new but strictly narrower lemma.
- `GS4 TARGET_STRENGTH`: comparable/equivalent to the target or circular.
- `GS5 FATAL`: checked counterexample, type error, false indispensable import, or
  incompatible hypothesis.

Keep closure gates separate from mathematical gaps:

- source gate: `OPEN | CLOSED | NOT_APPLICABLE`;
- verification gate: `NOT_READY | I3_REQUIRED | I3_ASSIGNED | I3_PASSED |
  NOT_REQUIRED`;
- novelty gate: `OPEN | CLOSED | NOT_REQUIRED`.

A candidate may have `GS0` and remain unclosed because its verification gate is
open.
An audit-ready candidate may retain explicit `GS1`/`GS2` repair or source
checks; `GS3`-`GS5` is not audit-ready, and only `GS0` can close.

Independence levels:

- `I0 SELF`: authored or materially repaired the route;
- `I1 ENTANGLED`: participated in the family or synthesis;
- `I2 SEPARATE`: did not author it but saw favored-route history;
- `I3 BLIND`: saw the exact target and candidate, but not generator optimism or
  intended repairs. A decisive proof audit must be `I3`.

For `I3`, record structured originating/material-repair run IDs, a disjoint
verifier run ID, and hash-bound candidate-lineage, exposure, and report
artifacts. Typed manifests bind the stable target and canonical candidate
IDs/digests, exact lineage sets, assignment packet, verdict, objections, and
report. Do not recycle a historical `I0`-`I2` verifier as the decisive run.

Freeze the dependency snapshot and three typed evidence roles into one audit
packet. Exposure, the authoritative structured verifier-report manifest, and
closure bind that exact packet. The required prose report repeats and agrees on
the canonical verdict fields; it cannot override the manifest.

## Portfolio Index

| Family ID | Idea fingerprint | Mode | Origin/lineage | Status | Strongest artifact | Highest mathematical gap | Source/verification/novelty gates | Next discriminating action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

Fingerprint shape:

`mechanism :: principal objects :: invariant/bridge :: reduction target :: decisive lemma :: version`

Two routes sharing the mechanism and decisive lemma are one family even when
their notation, agent, or exposition differs.

## Portfolio Seeding Matrix

| Seed ID | Search operator | Proposed mechanism | First checkable artifact | Cheapest falsifier | Burden reduction | Independence from favored lemma | Admit? |
| --- | --- | --- | --- | --- | --- | --- | --- |

Choose applicable operators from representation change, structural
decomposition, invariant/obstruction, duality, local-to-global gluing,
minimal-witness analysis, computational micro-experiments, hypothesis ablation,
exact source-theorem mining, checker-driven formalization, and synthesis with a
new compatibility mechanism. Reject slogans and renamed dependencies.

## Approach Cards

Copy this card once per family.

### `[FAMILY-ID] Short descriptive name`

- Full fingerprint:
- Created in round:
- Current version:
- Canonical candidate ID and SHA-256:
- Workflow status:
- Claim kind of strongest result:
- Project status of strongest result (canonical results-ledger value):
- Mechanism/construction:
- Principal objects and exact types:
- Decisive lemma:
- Explicit implication to the target:
- Why this is not a special case or equivalent restatement:
- Scope sensitivities:
- Known failure modes:
- Originating run(s):
- Inputs and prior attempts visible at origin:
- Parent/descendant families:
- Reciprocal merge edge, if applicable:
- Inherited gaps and per-gap discharge manifests:
  `[inherited-gap ID; source route/gap ID/class/statement digest; status; manifest/digest]`
- Historical-backfill manifest and SHA-256, if applicable:
- Independence lineage and current level:
- Strongest result actually proved:
- Strongest artifact path:
- Highest open gap and class:
- Source gate:
- Verification gate:
- Novelty gate:
- Counterexamples/edge cases tested:
- Current verifier and independence level:
- Verifier exposure log and SHA-256:
- Exposure/report manifests and SHA-256:
- Dependency snapshot / audit packet and SHA-256:
- Typed proof-obligation/source-audit/attack-exit manifests and SHA-256:
- Structured report/prose canonical-field agreement:
- Root decision: `CONTINUE / TARGET_GAP / AUDIT / BLOCK / REFUTE / MERGE / PARK / CLOSE`
- Concise decision reason:
- Next bounded action and stop condition:
- Blocked reason, if applicable:
- Reopen condition, if applicable:

## Blocking and Reopening Log

| Round/date | Family | Gap/blocker | Status transition | Evidence | Authorized reopen mechanism |
| --- | --- | --- | --- | --- | --- |

`GS4` blocks a route. A `GS3` normally becomes a named active subproblem; after
two targeted same-fingerprint returns without a new artifact, stop duplicate
allocation and park or block the parent. More agents, new notation, or another
equivalent reduction do not justify reopening. A `GS5` route is refuted. A
changed target always receives a new claim and route ID. Reopening requires a
typed manifest binding the exact route, blocker ID/class/text digest,
authorized basis, resulting status/candidate, and evidence digest.

## Historical Backfill Log

| Route | Initial status | Target ID / SHA-256 | Backfill manifest / SHA-256 | Source artifacts / SHA-256 | Recorded at |
| --- | --- | --- | --- | --- | --- |

`HISTORICAL_BACKFILL` is a first-transition initializer only. Its typed
manifest binds the route and initial status to this target and to nonempty
source artifacts including the transition evidence itself. It must not replace
known transition history. Structural
validation sees only the current snapshot; repository review or an external
append-only anchor is still needed to detect earlier deletion.

## Merge and Cross-Pollination Log

| Surviving family | Reciprocal merge edges | Components imported | Enumerated inherited gaps | Per-gap discharge manifests | Independence impact | New mechanism produced |
| --- | --- | --- | --- | --- | --- | --- |

A `MERGED` route names its survivor, and the survivor reciprocally lists it in
`parent_route_ids`. Enumerate every non-`GS0` parent gap with its source route,
inherited-gap ID, source gap ID, class, and statement digest. Each closed
inherited gap requires its own target-bound discharge manifest using
`DIRECT_PROOF`, `EXACT_SOURCE`,
`FORMAL_CERTIFICATE`, or `CHECKED_COMPUTATION`; the bound evidence must name the
gap ID and statement digest.

## Registry Checkpoint Summary

- Round outcome:
- Strongest rigorous result:
- Exact remaining gaps:
- Active families:
- Blocked/refuted families and reasons:
- Missing independent audits:
- Literature/novelty status:
- Initial/redirected wave manifests and parent/failure/mechanism delta:
  `[later round; every unique delta item absent from parent]`
- Canonical-operator waiver assessment and SHA-256:
  `[unavailable list derived from UNAVAILABLE/NOT_APPLICABLE statuses]`
- Why a stronger mathematical status is not justified:

Matching structure and hashes do not prove the mathematics, authenticate run
IDs or authorship, establish actual information exposure, or prove that older
history was not deleted.
