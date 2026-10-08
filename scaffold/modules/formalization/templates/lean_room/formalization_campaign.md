# Formalization Campaign Qualification

Status: DRAFT

This is a planning artifact, not Lean evidence or a certificate. It does not
enable Lean Room or widen the supported dependency boundary.

`F0`–`F4` are allocation defaults, not an allowed-method list. A coordinator
may skip, reorder, or replace a planning step with a recorded rationale,
replacement evidence where relevant, and a bounded stop condition. No planning
override relaxes any LR integrity, correspondence, or security gate.

## Identity and bindings

- Campaign ID:
- Problem ID:
- Created at / by:
- Exact target artifact / SHA-256:
- Target and obligation IDs:
- Intended certificate scope:

## F0A — suitability

- Decision: UNASSESSED
- Allowed decisions: SUITABLE / CONDITIONAL / NOT_SUITABLE
- Value supplied by formalization:
- Evidence that the mathematical statement is stable:
- Evidence that the intended representation is stable:
- Expected correspondence and maintenance cost:
- Mathematical uncertainties:
- Blocking uncertainties:

## F0B — assembly-gap assessment

- Classification: UNASSESSED
- Allowed classifications: LOW / MODERATE / HIGH / DOMINANT
- Library or API discovery work:
- Representation and coercion work:
- Notation or elaboration risks:
- Routine intermediate and bridge lemmas:
- Work that is genuinely new mathematics:
- Load-bearing correspondence work:

Do not label mathematical uncertainty as library friction. Conversely, do not
mistake a long declaration/API assembly task for a missing mathematical idea.

## F0C — library-readiness assessment

- Verdict: NOT_ASSESSED
- Allowed verdicts: PASS / FAIL / PLANNING_ONLY
- Proof assistant and exact toolchain:
- Actual supported dependency boundary:
- Required definitions and located declaration names:
- Required theorems and located declaration names:
- Required namespaces and imports:
- Required instances and coercions:
- Search queries and evidence:
- Unresolved library gaps:
- Executable under Lean Room v1: UNASSESSED
- Eligible for Lean Room v2 dependency pilot: UNASSESSED
- Snapshot/review bindings, if applicable:
- Verdict rationale:

"The library probably has it" is not PASS evidence. A PASS also cannot
override Lean Room v1's dependency-free certificate boundary. A reviewed v2
dependency pilot may test the encoded declaration, but its ceiling is
`PILOT_VERIFIED_NOT_CERTIFIED` and it does not establish correspondence.

## F1 — small vertical pilot

- Pilot case ID:
- Representative slice:
- Intended difficult representation exercised:
- Load-bearing bridge exercised:
- Target-shaped declaration exercised:
- Identified assembly gap crossed: UNASSESSED
- Guarded build artifact / SHA-256:
- Correspondence artifact / SHA-256:
- Human or API-search time:
- Kernel or build time:
- Verdict: NOT_RUN
- Allowed verdicts: PASS / FAIL / PILOT_ONLY / SKIPPED_WITH_RATIONALE
- Remaining untested risks:
- Planning override / replacement evidence / stop condition:

An unrelated toy theorem does not show that the relevant assembly gap was
crossed. A skipped or substituted pilot is a resource-allocation decision, not
proof evidence.

## F2 — proof-blueprint binding

- `proof_blueprint.md` artifact / SHA-256:
- Every omitted standard fact expanded: NO
- Blueprint review evidence:

## Full-campaign decision

- Verdict: NO_GO
- Allowed verdicts: GO / PILOT_ONLY / NO_GO
- Decided at / by:
- Evidence and rationale:
- Budget and stop conditions:

## Explicit non-claims

- This plan does not enable Lean Room.
- Suitability, library-readiness, and pilot decisions are not theorem status.
- A GO decision is not a formal certificate and does not relax any LR gate.
- `GO`, `PILOT_ONLY`, and `NO_GO` advise allocation only; they do not prohibit
  informal mathematics, static design, or a differently justified bounded
  experiment.
