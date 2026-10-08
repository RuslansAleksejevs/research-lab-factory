# Laboratory Survey Protocol

## Purpose

A laboratory survey is a deep, evidence-linked reconstruction of the whole
project after many, parallel, or widely separated research rounds. It is more
than `knowledge/resume.md`: it reconciles claims, failures, gaps, directions,
sources, and next choices across the laboratory.

The survey is derived navigation and strategy. It is not a proof, verifier
report, source audit, novelty certificate, or authority for changing a claim
status.

## Modes and authorization

- `LOCAL_FULL` is the default. Read the complete persisted local research state
  in scope and do not contact external systems.
- `LOCAL_WITH_EXPLICIT_LITERATURE_DELTA` is allowed only when the user explicitly
  asks to check current literature, prior art, or what others have done.
- A generic request to wake up, shake head, or survey the laboratory does not by
  itself authorize literature queries containing project material.

For a literature delta, use public terminology and the smallest nonprivate query.
Record exact queries, date, search surface, primary sources inspected, and limits.
Call an item "published or revised since the prior cutoff" only when its dated
version establishes that fact; otherwise call it "newly found in this search."
No finite negative search establishes novelty.

## Visibility boundary

The filesystem is the survey's observable state. Include a prominent limitation
when any of the following may exist:

- research results stated only in a previous chat;
- agents or external runs that have not written a checkpoint;
- unreadable, unparsed, or unregistered material;
- concurrent edits during the survey;
- project areas deliberately excluded from the inventory.

Do not reconstruct missing mathematical claims from memory. A chat-only result
is `NOT_PERSISTED`, not established project state.

## Stable survey packet

The default survey is read-only: inspect the laboratory and return the result in
chat without creating, updating, or deleting files. It may calculate a basis
digest in memory to detect concurrent changes, but it must not persist that
inventory unless requested.

Only when the user explicitly asks to save, persist, or checkpoint the survey,
use an ID such as `<UTC>-<short-label>` and create:

```text
runs/laboratory_surveys/<survey-id>/
  inventory.json
  start_seal.json
  report.md
  manifest.json
  literature_delta.md        # only in explicit literature mode
```

### Starting inventory for a persisted survey

Before synthesis, enumerate regular files in the declared scope, sort by portable
relative path, and record path, byte size, and SHA-256. Reject or report symlinks,
special files, unreadable files, and parse failures. Compute a basis digest from
the ordered `(path, sha256)` records, not from modification times.

The default scope includes:

- `LAB_PROFILE.json`, `PROJECT_CHARTER.md`, `BACKLOG.md`, bootstrap state, and
  origin provenance in `.lab/`;
- `knowledge/`, except derived survey and resume outputs;
- `decisions/`;
- `problems/active/`, `problems/backlog/`, and `problems/closed/`;
- `research/`, including the validated local checkpoint index and its bound
  canonical checkpoints;
- `results/`;
- `portfolio/`, `collaboration/`, and historically useful `archive/` state,
  while retaining the explicit `archive/migrations/**` exclusion;
- source registry, index, digests, bibliography, and cited source artifacts;
- enabled paper, research-report, talk, computation, and formalization state.

Record every exclusion. Normally exclude `.git/`, caches, build products,
`archive/migrations/**`, prior `runs/laboratory_surveys/**`,
`runs/laboratory_stewardship/**`,
`knowledge/resume.md`, `knowledge/laboratory_overview.md`, and
`knowledge/laboratory_survey_state.json`. Survey outputs must not make their own
basis stale.

Also exclude only the helper-owned direct children
`research/.research-memory-<32 lowercase hex>` and
`research/.checkpoint-index-<32 lowercase hex>`. They are transient
publication state, not research evidence, and may be visible while a record is
being committed or awaiting deterministic recovery. Similar-looking names are
not excluded: the entire pair of prefixes is reserved, so a near-match remains
visible as unexpected laboratory state and makes memory validation fail closed.
Recovery never deletes a near-match; write authority is limited to the two
exact lowercase-32-hex shapes. The survey must still validate Durable Research
Memory before interpreting the index; this snapshot exclusion does not certify
or repair an interrupted write.

When a final survey closes a validated stewardship run, bind its immutable
`completion_basis.json` explicitly at survey start and recheck the binding at
finalization and later freshness checks. Do not include the mutable stewardship
packet in the ordinary basis or bind its mutable manifest.

At start, write `start_seal.json` as a `0444` regular file. It binds the exact
inventory bytes and basis digest plus the manifest's immutable identity,
mode, starting digest, and external bindings. Finalization must reject a
changed inventory, removed binding, changed immutable manifest field, unsafe
path component, or changed seal mode.

Write-capable survey commands require an instantiated laboratory identity and
pin that root directory's device/inode for the process. Packet, overview, and
state publication use no-follow directory-anchored atomic create/replace; a
concurrent prior-state change or root substitution fails closed.

`inventory.json` should contain at least:

- schema version, survey ID, start time, and mode;
- included roots and explicit exclusions;
- ordered file records and starting basis digest;
- unreadable, unparsed, unregistered, and suspected unpersisted-state warnings.

### Finish and freshness for a persisted survey

After writing the report, recompute the same scoped inventory. Record starting
and finishing digests in `manifest.json` together with:

- `STABLE` or `DRIFT_DETECTED`;
- the report path and SHA-256;
- coverage status and omitted material;
- literature mode, cutoff, query log, and delta artifact when applicable;
- creation/completion times using UTC;
- a statement that hashes establish snapshot identity, not mathematical truth.
- every explicit excluded-artifact binding with path, size, and SHA-256.

If the digests differ, identify changed paths and rescan them. If stability
cannot be recovered, keep the packet as incomplete history but do not replace
the latest overview or mark it fresh. Never claim a coherent snapshot while
parallel work is changing its evidence base.

`knowledge/laboratory_survey_state.json` is only the latest-pointer and
freshness record. `knowledge/laboratory_overview.md` is a convenient copy or
summary of the latest stable persisted report. Update neither file during the
default chat-only survey. The immutable packet remains authoritative for what a
persisted survey actually read. The latest state binds and later rehashes the
authoritative report, manifest, inventory, and start seal (plus an optional
literature delta); editing any of them makes freshness `STALE`.
Republishing an already stable or previously drifted older packet may not roll
back a newer fresh latest pointer. Recovery of a newer stable packet is ordered
by its authoritative completion timestamp and survey ID, never by mutable state
metadata alone.

## Reconciliation procedure

1. Read the mission, tracks, conventions, current priorities, backlog, and
   decisions.
2. Inventory every active, backlog, and closed dossier. Read its exact target,
   status, proof-search state, approach registry, round reports, candidate
   lineage, counterexamples, and verifier reports.
3. Read global result, conjecture, example, question, and warning ledgers plus
   the status-partitioned `results/` tree.
4. Validate and query the local checkpoint index for orientation, then read the
   bound append-only checkpoints and referenced evidence. Read exploratory
   research as well. Flag stale index state and outputs not connected to a
   dossier, result, ledger entry, or next action.
5. Read source metadata and exact cited statements needed to understand current
   dependencies. Do not turn a source lead into a checked theorem.
6. Compare exact claim scope, hypotheses, coefficients, degrees, conventions,
   evidence, and verifier state across every location that mentions it.
7. Preserve conflicting labels side by side. Use `UNRECONCILED` when scope or
   status disagrees; do not invent a total order between incompatible status
   vocabularies.
8. Separate established results, conditional or candidate results, refutations,
   failed mechanisms, and open questions. Preserve useful residue from failed
   routes.
9. Map dependencies and identify the load-bearing blocker for each live route.
   Count semantic progress only when a named dependency closed or strictly
   reduced.
10. Assess generalization axes separately from proof status. A possible
    extension is `PROPOSED_DIRECTION` or `UNKNOWN` until supported by its own
    artifact.
11. Produce a small ranked next-round portfolio. Each round needs an exact
    question, connection to a gap or family, expected information gain,
    required artifact, cheapest falsifier, verification route, and stop
    condition.
12. For an explicit stronger-model or new-capability review, compare recorded
    obstruction tags, missing capabilities, and reopen conditions against the
    actual new capability. Treat a match as a reactivation lead, not evidence
    that the barrier is solved.

## Status safeguards

- A polished proof, checkpoint, survey, compilation, model consensus, or passing
  structural validator cannot promote a claim.
- Show ledger, dossier, round, result-artifact, and verifier statuses with their
  source paths. Do not silently normalize different vocabularies.
- A verified label without its required evidence is a reconciliation defect,
  not an established result.
- A refutation of one variant does not refute a stronger, weaker, or differently
  quantified variant without an exact implication.
- Never edit protected ledgers or dossier status during the survey. Put proposed
  repairs in the report for explicit review.
- Strategic ranking is advice, not evidence that a direction is true, new, or
  tractable.

## Handoff

Return the executive project map, strongest established results, decisive
uncertainties, important failures, and ranked next rounds in chat. State whether
the response is chat-only or links an explicitly persisted stable report, and
whether it is local-only or includes an explicit dated literature delta. Ask
only for decisions that materially select among the next rounds; do not launch
them automatically.
