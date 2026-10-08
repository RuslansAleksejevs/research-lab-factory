# Approach Registry

Use one registry per exact claim or tightly coupled problem dossier. The
registry tracks mathematical mechanisms, not the number of agents or drafts.
It is the auditable narrative and evidence view of the search. In `FULL`,
`proof_search_state.yaml` is the canonical mutable record for current route IDs,
statuses, mathematical gaps, closure gates, transition history, frozen
candidate binding, run lineage, round, and verifier assignment;
update this registry to agree with that state at every checkpoint.

## Registry Header

- Problem/claim ID: `[required]`
- Stable target ID: `[required after initialization]`
- Exact target artifact: `[path and section]`
- Exact target SHA-256: `[required after initialization]`
- Root coordinator: `[name/run ID]`
- Orchestration profile: `FULL`
- Current round: `[integer]`
- Current mode: `BLIND_GENERATION | PROJECT_AWARE | LITERATURE_AWARE |
  VERIFICATION | MIXED_WITH_PARTITIONS`
- Last updated: `[ISO date/time]`
- Anti-target artifact: `[path or section]`
- Attack-surface artifact: `[path]`
- Proof-obligation artifact: `[path]`
- Canonical candidate ID / SHA-256: `[null before freezing, otherwise both]`
- Candidate-lineage artifact / SHA-256: `[path and digest]`
- Proof-obligation/source-audit/attack-exit evidence and typed manifests:
  `[three pairwise-distinct role artifacts plus manifest paths/digests]`
- Dependency snapshot / audit packet: `[paths and digests]`
- Exposure/report/closure manifests: `[paths and digests, when applicable]`

## Claim Kinds And Project Statuses

Use `THEOREM_CANDIDATE`, `CONJECTURE`, `HEURISTIC`, `ANALOGY`,
`EXPERIMENTAL_EVIDENCE`, `CONDITIONAL_RESULT`, `FAILED_ATTEMPT`,
`COUNTEREXAMPLE`, or `UNRESOLVED_QUESTION` only as narrative claim kinds.

Record project status separately using the canonical values from
`knowledge/results_ledger.yaml`: `VERIFIED_INTERNAL`,
`VERIFIED_USING_CITED_RESULTS`, `COMPUTER_CHECKED`, `FORMALLY_VERIFIED`,
`CONDITIONAL`, `PLAUSIBLE_UNVERIFIED`, `GAP`, `REFUTED`, or `UNKNOWN`. A
`THEOREM_CANDIDATE` claim kind never implies a verified project status.

Use these separate workflow statuses for approaches:

`SEED`, `ACTIVE`, `CANDIDATE`, `UNDER_AUDIT`, `BLOCKED`, `REFUTED`, `MERGED`,
`PARKED`, `CLOSED_PROOF`, `CLOSED_COUNTEREXAMPLE`.

## Idea Fingerprint Rule

The canonical fingerprint is:

`<mechanism>::<principal objects>::<bridge/invariant>::<reduction target>::<decisive lemma>::<version>`

Record the following expanded fields for every family:

- Mechanism: the actual mathematical operation or construction.
- Principal objects: the structures on which the mechanism acts.
- Bridge/invariant: what is preserved, measured, or transported.
- Reduction target: the strictly stated problem produced by the route.
- Decisive lemma: the new statement on which success turns.
- Scope sensitivities: characteristic, coefficients, twists, finiteness,
  regularity, support, orientation, connectedness, or other fragile inputs.
- Known failure modes: the first places an adversary should attack.

Two approaches with the same mechanism and decisive lemma are one family even
if notation and exposition differ. A new version within the family is not a
new independent approach. A genuinely new invariant, construction, source
theorem, equivalence, or local-to-global mechanism receives a new family ID.

## Gap Classes

- `GS0 CLOSED`: proved, exactly sourced, or formally/computationally checked.
- `GS1 LOCAL`: bounded repair or omitted local case.
- `GS2 SOURCE`: exact theorem, compatibility, hypothesis, coefficient, twist,
  degree, or map still needs source verification.
- `GS3 SUBSTANTIVE`: new, strictly narrower, independently testable lemma.
- `GS4 TARGET_STRENGTH`: equivalent/comparable to the target or circular.
- `GS5 FATAL`: counterexample, type failure, false indispensable import, or
  contradiction. A replaceable citation defect is `GS2`.

The best-looking exposition does not affect the gap class.

## Closure Gates Separate From Mathematical Gaps

Do not encode a missing independent audit or novelty search as a mathematical
gap. Every family separately records:

- `source_gate`: `OPEN | CLOSED | NOT_APPLICABLE`; whether all load-bearing
  imports are checked in the exact form used; an open dependency normally
  corresponds to a specific `GS2` obligation;
- `verification_gate`: `NOT_READY | I3_REQUIRED | I3_ASSIGNED | I3_PASSED |
  NOT_REQUIRED`; required independence, assignment, verdict, and report;
- `novelty_gate`: `OPEN | CLOSED | NOT_REQUIRED`; literature/terminology status,
  relevant only to novelty or priority language.

A route may have highest mathematical gap `GS0` and still remain a `CANDIDATE`
because its verification gate is open.
An audit-ready candidate may instead retain explicitly named `GS1`/`GS2`
repair or source checks; `GS3`-`GS5` is not audit-ready, and only `GS0` can
close.

## Independence Lineage

For every generator, synthesizer, and verifier record:

- Run/agent ID;
- role;
- approach families authored or materially repaired;
- prior drafts, critiques, source packets, and favored-route summaries seen;
- whether an affirmative answer was suggested or assumed;
- parent approach IDs used in a synthesis;
- immutable target/candidate IDs/digests and the hash-bound exposure log plus
  typed exposure/report manifests, when auditing;
- independence level: `I0 SELF`, `I1 ENTANGLED`, `I2 SEPARATE`, or `I3 BLIND`.

An `I3` audit is mandatory for decisive proof certification. Its run ID must be
disjoint from every structured originating/material-repair run ID, and the
exposure log and final report must repeat the frozen target/candidate IDs and
digests, with typed manifests binding their roles and contents. The decisive
verifier cannot be a recycled historical `I0`-`I2` run for that candidate. A
source verifier must not be the person or run that invented the citation.
Independence is about information lineage, not different agent names.

For audit, bind the complete dependency snapshot and all three typed evidence
roles into one immutable audit packet. Exposure, the authoritative structured
verifier-report manifest, and closure must bind that same packet. The required
prose report repeats and agrees on the canonical verdict fields; it cannot
override the manifest.

## Portfolio Table

| Family ID | Short fingerprint | Mode | Origin/lineage | Workflow status | Strongest artifact | Highest mathematical gap | Source/verification/novelty gates | Next discriminating action |
|---|---|---|---|---|---|---|---|---|
| `[A-...]` | `[mechanism :: decisive lemma]` | `[context mode]` | `[run IDs; I-level]` | `[allowed status]` | `[path/claim ID]` | `[GS0-GS5; gap ID]` | `[gate summaries]` | `[concrete test or proof task]` |

Portfolio rule: before a family survives adversarial audit, it should not use
more than half of generator capacity without a recorded mathematical reason.
Superficial variants do not count as diversity.

## Portfolio Seeding Matrix

Use several applicable operators from the orchestration workflow. A seed is not
admitted merely because its title sounds different.

| Seed ID | Search operator | Proposed mechanism | Decisive first artifact | Cheapest falsifier | Burden reduction | Independence from favored lemma | Admit as family? |
|---|---|---|---|---|---|---|---|
| `[S-...]` | `[representation/decomposition/invariant/duality/gluing/extremal/computation/ablation/source/formalization/synthesis]` | `[mathematical content]` | `[lemma/construction/equation/witness/certificate]` | `[specific test]` | `[why strictly easier or differently structured]` | `[exact dependency comparison]` | `YES/NO/PENDING` |

Reject a seed that supplies only a slogan, restatement, or the favored route's
decisive lemma in new notation.

## Full Approach Card

Create one card for each family in the table.

### Identity

- Family ID: `[stable ID]`
- Short name: `[descriptive, not aspirational]`
- Full fingerprint: `[canonical fingerprint]`
- Created in round: `[integer]`
- Current version: `[vN; link superseded versions]`
- Canonical candidate ID and SHA-256: `[only after candidate freezing]`
- Workflow status: `[allowed approach status]`
- Claim kind of strongest result: `[narrative claim kind]`
- Project status of strongest result: `[canonical results-ledger status]`

### Exact mechanism

- Input objects and types: `[include coefficients/twists/degrees]`
- Construction or invariant: `[auditable description]`
- Intended output: `[exact typed statement]`
- Decisive lemma: `[quantified statement, not slogan]`
- Why it would imply the target: `[explicit implication chain]`
- Anti-target check: `[why this is not only a special case or equivalent restatement]`

### Provenance and independence

- Originating run(s): `[IDs]`
- Inputs visible at origin: `[files, sources, other approaches]`
- Parent approaches: `[none or IDs]`
- Reciprocal merge edge: `[merged route -> survivor; survivor parent entry]`
- Inherited gaps and per-gap discharge manifests:
  `[inherited-gap ID; source route/gap ID/class/statement digest; OPEN/CLOSED; manifest/digest]`
- Historical-backfill manifest / SHA-256: `[path/digest or NOT_APPLICABLE]`
- Descendant approaches: `[IDs]`
- Favored route disclosed: `YES | NO`
- Affirmative answer assumed: `YES | NO`
- Current verifier and independence level: `[ID; I0-I3]`
- Verifier exposure log and SHA-256: `[path/digest or not assigned]`
- Exposure/report manifests and SHA-256: `[paths/digests or not assigned]`
- Dependency snapshot / audit packet and SHA-256:
  `[paths/digests or not audit-ready]`
- Independence conflicts: `[none or exact conflict]`

### Evidence and obligations

- Source gate: `[OPEN/CLOSED; artifact]`
- Verification gate: `[required I-level; assignment/verdict/report]`
- Novelty gate: `[NOT_REQUIRED/OPEN/CLOSED; artifact]`
- Typed proof-obligation/source-audit/attack-exit manifests:
  `[paths/digests; underlying role artifacts must be pairwise distinct]`
- Structured report/prose agreement:
  `[target/candidate/verifier, independence, verdict, highest gap, objections, repairs]`

| Obligation ID | Exact statement | Status | Gap class | Evidence/source | Owner | Falsification test |
|---|---|---|---|---|---|---|
| `[O-...]` | `[quantified and typed]` | `[proved/conditional/open/failed]` | `[GS0-GS5]` | `[artifact or exact citation]` | `[run ID]` | `[counterexample or audit]` |

### Attack history

| Attack ID | Failure mode tested | Result | Evidence | Consequence |
|---|---|---|---|---|
| `[AT-...]` | `[from attack surface]` | `SURVIVED/FAILED/INCONCLUSIVE/NOT_APPLICABLE` | `[artifact]` | `[status/gap change]` |

### Root decision

- Decision: `CONTINUE | TARGET_GAP | AUDIT | BLOCK | REFUTE | MERGE | PARK | CLOSE`
- Concise mathematical reason: `[what changed and why]`
- Next action: `[one bounded task producing a checkable artifact]`
- Stop condition for that action: `[success/failure criterion]`

## Blocking and Reopening Log

| Event | Family ID | Blocker/gap | Status before -> after | Evidence | Authorized reopen mechanism |
|---|---|---|---|---|---|
| `[date/round]` | `[A-...]` | `[gap ID; GS class]` | `[transition]` | `[artifact/SHA-256; reopen manifest/SHA-256 if reopening]` | `[burden-reducing mechanism / exact source / narrower reformulation / direct checked closure / NONE]` |

Blocking rules:

- `GS4` blocks immediately.
- A `GS3` normally becomes a named active subproblem. After two targeted returns
  with the same fingerprint and no new checkable artifact, stop duplicate
  allocation and park or block the parent at that dependency.
- `GS5` refutes the recorded version.
- More agents, renamed notation, or another equivalent reduction do not
  authorize reopening.
- A reopen manifest must bind the same route, exact blocked gap ID/class/text
  digest, authorized basis, resulting status/candidate, and evidence digest.
- A materially changed target or hypothesis always creates a new claim and
  approach ID; it is never a reopening event for the old route.

## Historical Backfill Log

| Route | Initial status | Target ID / SHA-256 | Backfill manifest / SHA-256 | Source artifacts / SHA-256 | Recorded at |
|---|---|---|---|---|---|
| `[A-...]` | `SEED/CANDIDATE/BLOCKED/REFUTED/PARKED` | `[ID/digest]` | `[path/digest]` | `[nonempty list]` | `[ISO time]` |

`HISTORICAL_BACKFILL` is allowed only as a route's first transition. Its typed
manifest records target-bound provenance, and its source set must include the
transition evidence artifact/digest. It must not compress or replace known
transition history. A current snapshot cannot prove that older events were not
deleted, so repository review or an external append-only anchor remains
necessary for deletion detection.

## Merge and Cross-Pollination Log

| New/surviving family | Reciprocal merge edges | Components imported | Enumerated inherited gaps | Per-gap discharge manifests | Independence impact | Reason merge is nontrivial |
|---|---|---|---|---|---|---|
| `[A-...]` | `[P.merged_into=S; P in S.parent_route_ids]` | `[lemmas/constructions]` | `[inherited-gap ID; source route/gap ID/class/text digest]` | `[one path/digest per CLOSED gap]` | `[new I-levels]` | `[exact mechanism change]` |

A synthesis inherits each unresolved parent gap with the same source gap
ID/class/text digest. Every closed inherited gap has its own target-bound typed
discharge manifest using `DIRECT_PROOF`, `EXACT_SOURCE`, `FORMAL_CERTIFICATE`,
or `CHECKED_COMPUTATION`; its evidence must name the gap ID and statement
digest. A blanket note cannot discharge several gaps. Do not promote a route
because several agents repeated the same idea.

## Registry Exit Summary

- Exit status: `VERIFIED_PROOF | VERIFIED_COUNTEREXAMPLE | CONDITIONAL_RESULT | CHECKPOINT_INCOMPLETE | EXHAUSTED_CURRENT_MECHANISMS`
- Strongest rigorously established result: `[exact statement and artifact]`
- Remaining open gaps: `[IDs and GS classes]`
- Refuted families: `[IDs and fatal reasons]`
- Parked families worth revisiting: `[IDs and required new information]`
- Required independent audits still missing: `[roles and I-levels]`
- Literature/novelty status: `[checked/not checked; artifact]`
- Initial/redirected wave manifests and parent/failure/mechanism delta:
  `[paths/digests; redirected round later and every unique delta item new, or NOT_APPLICABLE]`
- Canonical-operator waiver assessment / SHA-256:
  `[path/digest; unavailable list derived from UNAVAILABLE/NOT_APPLICABLE, or NOT_APPLICABLE]`

This registry records declared structure and evidence links. Matching IDs,
paths, hashes, and manifests do not authenticate runs, prove historical
nondeletion, or establish the mathematical correctness of a claim.
