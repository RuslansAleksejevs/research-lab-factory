# Hard-Math Search Round Report

Create one report per orchestration round. Record auditable mathematical
outputs and concise root decisions; do not store private chain-of-thought.

## 1. Round Metadata

- Problem/claim ID: `[required]`
- Round ID: `[stable ID]`
- Date/time: `[ISO]`
- Root coordinator: `[run ID]`
- Orchestration profile: `FULL`
- Search mode: `BLIND_GENERATION | PROJECT_AWARE | LITERATURE_AWARE |
  VERIFICATION | MIXED_WITH_PARTITIONS`
- Resource checkpoint: `[round/time/token condition]`
- Approach registry: `[path/version]`
- Attack surface: `[path/version]`
- Proof obligations: `[path/version]`
- Prior round: `[path or NONE]`
- Wave type: `INITIAL | REDIRECTED | OTHER`
- Wave manifest / SHA-256: `[path/digest or NOT_APPLICABLE]`
- Parent initial-wave manifest / SHA-256 and earlier round:
  `[required for REDIRECTED; parent round < redirected round]`
- Triggering failure artifacts: `[nonempty parent-wave subset for REDIRECTED]`
- Mechanisms tested / new mechanism delta:
  `[lists; delta is duplicate-free and every item is absent from parent]`
- Redirected discriminating question: `[required for REDIRECTED]`

## 2. Contract Check

- Stable target ID: `[required]`
- Exact target version: `[path/section/version]`
- Exact target SHA-256: `[required]`
- Mathematical status at round start: `[project status]`
- Coefficients, twists, degrees, support: `[concise normalized record]`
- Anti-targets enforced this round: `[list]`
- Changes since prior round: `[NONE or exact changes with provenance]`
- User-approved scope change required: `YES | NO`

If the target or hypotheses changed, do not compare success rates across the
change as though the same claim were being searched.

## 3. Starting Portfolio and Diversity Audit

| Family ID | Search operator | Fingerprint summary | Start status | Agents/capacity | Mode | Why retained this round |
|---|---|---|---|---|---|---|
| `[A-...]` | `[representation/invariant/etc.]` | `[mechanism :: decisive lemma]` | `[allowed status]` | `[count/IDs]` | `[context mode]` | `[specific mathematical reason]` |

- Fraction of generator capacity in largest family: `[value]`
- More than half in one unaudited family: `YES | NO`
- If yes, recorded justification: `[required]`
- Underexplored families or formulations: `[IDs/descriptions]`
- Underrepresented family-generation operators: `[operators/descriptions]`
- Independence risks at launch: `[none or exact risks]`

## 4. Dispatch Ledger

Every assignment must request a bounded, checkable artifact.

| Task ID | Run/agent ID | Role | Family/obligation | Inputs visible | Favored route disclosed | Truth assumed | Required artifact | Required falsification test |
|---|---|---|---|---|---|---|---|---|
| `[D-...]` | `[ID]` | `GENERATOR/COUNTEREXAMPLE/PROOF_VERIFIER/SOURCE_VERIFIER/SYNTHESIZER` | `[A-/O- ID]` | `[files/families]` | `YES/NO` | `YES/NO` | `[lemma/proof/certificate/report]` | `[specific attack]` |

## 5. Concrete Returns

Do not record "promising" without the artifact that makes it promising.

| Return ID | Task/run | Artifact path | Concrete claim/construction/result | Mathematical status | Family fingerprint | New dependencies | Self-reported gaps |
|---|---|---|---|---|---|---|---|---|
| `[RET-...]` | `[D-/run ID]` | `[path]` | `[exact statement]` | `[project status]` | `[existing/new family]` | `[claims/sources]` | `[gap statements]` |

### Rejected or nonresponsive returns

| Return ID | Reason rejected | Useful residue preserved | Registry consequence |
|---|---|---|---|
| `[RET-...]` | `STATUS_ONLY/DUPLICATE_MECHANISM/ANTI_TARGET/UNTYPED/UNSOURCED_GLOBAL_CLAIM/OTHER` | `[lemma/example/warning or NONE]` | `[none/block/merge/etc.]` |

## 6. Fingerprint and Lineage Update

| Family/version | Origin and parents | New information seen | Independence level | Duplicate of | Cross-pollination effect |
|---|---|---|---|---|---|---|
| `[A-... vN]` | `[run and parent IDs]` | `[drafts/sources/critiques]` | `[I0-I3]` | `[family or NONE]` | `[gaps inherited/new mechanism]` |

Root checks:

- Were differently worded versions correctly deduplicated? `YES | NO`
- Did any synthesis lose a parent gap? `YES | NO`; if yes, restore `[IDs]`.
- Does any claimed verifier have an undisclosed authorship conflict? `YES | NO`.
- Structured originating/material-repair run IDs: `[IDs]`
- Candidate-lineage artifact and SHA-256: `[path/digest or NONE]`
- Historical-backfill routes and target-bound manifests:
  `[route/initial status/manifest digest/source artifacts including transition evidence, or NONE]`
- Are any apparently independent returns descendants of one favored draft?
  `YES | NO`; if yes, downgrade lineage `[IDs]`.

## 7. Proof-Obligation and Gap Update

| Gap/obligation ID | Family | Exact unresolved statement | Prior class | New evidence | Current class | Owner | Next discriminating action |
|---|---|---|---|---|---|---|---|
| `[G-/O-...]` | `[A-...]` | `[quantified, typed statement]` | `[GS0-GS5]` | `[artifact/source/test]` | `[GS0-GS5]` | `[run ID]` | `[bounded task]` |

Required root action by class:

- `GS1`: commission a local repair and regression audit.
- `GS2`: commission exact source/compatibility verification.
- `GS3`: isolate a named subproblem and attack it independently.
- `GS4`: block the route unless a recorded reopening condition is met.
- `GS5`: refute or supersede the route; preserve the witness.

### Semantic-progress watchdog

| Family | Main-path obligations before -> after | Highest gap before -> after | New path lemma actually consumed | Repeated blocker / duplicate fingerprint | No-progress checkpoint count | Decision |
|---|---|---|---|---|---|---|
| `[A-...]` | `[IDs] -> [IDs]` | `[GSx] -> [GSy]` | `[lemma/edge or NONE]` | `[fingerprint or NONE]` | `[0, 1, 2+]` | `CONTINUE / WATCH / PAUSE_AND_AUDIT / EXPAND_PROOF / PIVOT / CONTINUE_BOUNDED_WITH_RATIONALE / STOP` |

- Resource growth not counted as mathematical progress:
  `[lines/files/helper lemmas/time/tokens or NONE]`
- Omitted or supposedly standard fact requiring a detailed informal proof:
  `[exact statement and blueprint path or NONE]`
- Independent code/proof audit commissioned after stall:
  `[run/artifact or NONE]`
- Human high-level directional prompt and portfolio effect:
  `[prompt summary and changed mechanism IDs or NONE; steering only, not evidence]`
- If any family reached two consecutive no-progress checkpoints, was
  same-mechanism generation paused or bounded continuation justified?
  `PAUSED | BOUNDED_CONTINUATION | NOT_APPLICABLE`
- If bounded continuation: unchanged blocker, mathematical rationale,
  discriminating experiment, and stop condition:
  `[exact record or NOT_APPLICABLE]`

Bounded continuation does not reset the stall count, close the blocker, or
upgrade route or theorem status.

Merge/discharge checks:

- Every `MERGED` route names its survivor, and the survivor reciprocally lists
  it in `parent_route_ids`: `YES | NO | NOT_APPLICABLE`.
- Every non-`GS0` parent gap is separately inherited with matching inherited-gap
  ID, source route, source gap ID/class/statement digest:
  `YES | NO | NOT_APPLICABLE`.
- Every closed inherited gap has its own target-bound discharge manifest, one
  allowed basis, and evidence naming its gap ID and statement digest:
  `YES | NO | NOT_APPLICABLE`.

## 8. Attack and Verification Results

| Audit ID | Target ID / SHA-256 | Candidate ID / SHA-256 | Attack IDs | Verifier run ID | Exposure log + manifest / SHA-256 | Independence | Verdict | Failed/inconclusive points | Report + manifest / SHA-256 |
|---|---|---|---|---|---|---|---|---|---|
| `[AUD-...]` | `[ID/digest]` | `[ID/digest]` | `[AT- IDs]` | `[run ID]` | `[paths/digests]` | `[I0-I3]` | `PASS/FAIL/INCONCLUSIVE` | `[gap IDs or NONE]` | `[paths/digests]` |

- Pairwise-distinct proof-obligation/source-audit/attack-exit evidence and
  typed manifests: `[paths/digests]`
- Dependency snapshot / SHA-256: `[path/digest]`
- Audit packet / SHA-256: `[path/digest]`
- Same audit packet bound by exposure, structured report, and closure:
  `YES | NO | NOT_APPLICABLE`
- Authoritative report manifest and prose agree on target/candidate/verifier,
  independence, verdict, highest gap, unresolved objections, and repairs:
  `YES | NO | NOT_APPLICABLE`

### Source audit

- Imported results checked this round: `[claim IDs and exact sources]`
- Citation statements matched exactly: `[IDs]`
- Source mismatches or missing compatibilities: `[IDs; GS2/GS5]`
- Search snippets/abstracts excluded as authority: `YES | NO`

### Type and scope audit

- Degree checks completed: `[IDs or NOT_APPLICABLE]`
- Coefficient checks completed: `[IDs or NOT_APPLICABLE]`
- Tate twist/weight checks completed: `[IDs or NOT_APPLICABLE]`
- Domain/codomain and support checks completed: `[IDs]`
- Boundary/degenerate cases completed: `[AT- IDs]`
- Circularity check completed: `[AT- ID and verdict]`

## 9. Root Decisions by Family

| Family ID | Decision | Status before -> after | Transition evidence | Concise mathematical reason | Reopen basis/condition if blocked | Next task or terminal artifact |
|---|---|---|---|---|---|
| `[A-...]` | `CONTINUE/TARGET_GAP/AUDIT/BLOCK/REFUTE/MERGE/PARK/CLOSE` | `[transition]` | `[artifact/SHA-256]` | `[evidence-based reason]` | `[mechanism/source/reformulation/direct checked closure or NONE]` | `[task/path]` |

Decision rules:

- Do not continue a route merely because it is elegant or popular.
- Do not block a route merely because it is difficult; name the exact blocker.
- Do not reopen a blocked route with only more agents or new notation.
- A reopen decision names a typed reopen manifest bound to the exact blocker;
  a merge discharge names a typed gap-discharge manifest bound to the parent
  gap ID/class/statement digest.
- A merge is reciprocal: the merged route names the survivor and the survivor
  names the merged route as a parent; discharge is enumerated one gap at a time.
- A repaired candidate receives a new version and fresh audits for affected
  steps.
- A merged route records parent IDs and inherits all unresolved gaps and
  lineage until named discharge artifacts close them.

## 10. Cross-Pollination Record

- Independent development completed before cross-feeding: `YES | NO`
- Families cross-fed: `[IDs or NONE]`
- Exact artifacts exchanged: `[paths]`
- New mechanism produced: `[description or NONE]`
- Gaps inherited: `[IDs]`
- Independence levels changed: `[runs and new levels]`

Cross-pollination that produces only a reformulation stays in the same family.

## 11. Strongest Result at Round End

- Exact statement: `[quantified statement]`
- Claim kind: `THEOREM_CANDIDATE | CONDITIONAL_RESULT | EXPERIMENTAL_EVIDENCE | COUNTEREXAMPLE | FAILED_ATTEMPT | UNRESOLVED_QUESTION`
- Project status: `VERIFIED_INTERNAL | VERIFIED_USING_CITED_RESULTS | COMPUTER_CHECKED | FORMALLY_VERIFIED | CONDITIONAL | PLAUSIBLE_UNVERIFIED | GAP | REFUTED | UNKNOWN`
- Proof/evidence artifact: `[path]`
- Scope exclusions: `[what is not established]`
- Dependencies still open: `[gap IDs or NONE]`
- Independent verification obtained: `[verifier IDs/I-levels or NONE]`
- Literature/novelty audit: `[complete/incomplete/not applicable]`

## 12. Termination Gate

Choose exactly one round outcome:

- `CONTINUE_DIVERSE`: materially distinct routes remain active.
- `TARGET_NAMED_GAP`: the next round centers on one or more `GS1`-`GS3` gaps.
- `AUDIT_CANDIDATE`: an end-to-end candidate meets the promotion gate.
- `SWITCH_MODE`: blind discovery transitions to literature-aware work, or the
  reverse with documented information partitions.
- `VERIFIED_PROOF`: every substantive obligation is `GS0`, an `I3` proof audit
  passed, and source audits passed.
- `VERIFIED_COUNTEREXAMPLE`: the exact target and witness were independently
  checked.
- `CONDITIONAL_RESULT`: exact unproved assumptions are stated and preserved.
- `CHECKPOINT_INCOMPLETE`: resources reached a checkpoint; exact gaps and next
  tests are reported.
- `EXHAUSTED_CURRENT_MECHANISMS`: all current families are blocked, refuted, or
  merged, with no `PARKED` or other live route remaining, and either a distinct
  redirected-wave report or a precise evidence-backed waiver.

- Selected outcome: `[one allowed value]`
- Gate evidence: `[artifacts and audits]`
- Closure manifest / SHA-256: `[path/digest or NOT_APPLICABLE]`
- Initial-wave report + typed manifest: `[paths/digests or NOT_APPLICABLE]`
- Redirected-wave report + typed manifest, or target-bound waiver manifest:
  `[paths/digests and reason]`
- Redirected-wave parent manifest, triggering failures, mechanism delta, and
  discriminating question:
  `[later round; every unique delta item new; exact values or NOT_APPLICABLE]`
- Canonical-operator waiver assessment / SHA-256:
  `[all operators exactly once with status/reason; unavailable list derived from UNAVAILABLE/NOT_APPLICABLE, or NOT_APPLICABLE]`
- Why stronger status is not justified: `[required unless verified closure]`

Structural validation of this report checks the consistency of declared
roles, IDs, paths, hashes, and manifests in the current snapshot. It does not
authenticate runs, prove exposure or independence, establish source truth or
mathematical correctness, or detect history deleted before the snapshot.

## 13. Next-Round Launch Plan or Handoff

If continuing:

| Priority | Family/gap | New mechanism or discriminating question | Role | Required independence | Required artifact | Stop condition |
|---|---|---|---|---|---|---|
| `[1..N]` | `[A-/G- ID]` | `[specific question]` | `[role]` | `[I-level]` | `[artifact]` | `[success/failure criterion]` |

If terminating without a verified proof:

- strongest rigorously established derivation;
- exact remaining gap classes;
- checked counterexamples and failed routes;
- sources verified and sources still missing;
- what genuinely new information would justify reopening;
- explicit statement that the original theorem remains unproved here.

If terminating with a verified result, propose—but do not silently perform—any
protected ledger or architecture updates required by project policy.
