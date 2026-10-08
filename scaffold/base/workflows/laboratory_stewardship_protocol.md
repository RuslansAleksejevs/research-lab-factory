# Laboratory Stewardship Protocol

## Purpose

Stewardship is a deep, write-capable maintenance pass over one autonomous
mathematical laboratory. It reconstructs the whole durable state, makes every
safe and evidence-supported repair that fits a finite maintenance round,
validates the result, and closes with a stable whole-laboratory survey.

It is not a promise to solve every open problem. A laboratory is in order when
its claims and limitations are represented honestly, its evidence is linked,
cheap defects are repaired, unresolved issues are classified, and its next
research choices are concrete.

## Modes and authorization

- `DEEP_LOCAL` is the default for «приведи лабораторию в порядок» and
  equivalent requests. Use the strongest available reasoning and bounded
  independent roles, but keep the operation finite.
- `STANDARD_LOCAL` performs the same integrity procedure with fewer parallel
  assessments and no discretionary proof-repair wave.
- A generic stewardship request authorizes local additive and guarded update
  writes inside this laboratory. It does not authorize deletion, changing the
  laboratory mission or target, external browsing or transmission, a new
  research-scale campaign, architecture edits, or work on another laboratory.
- Current-literature work requires a separate explicit request. Use public-safe
  terminology and the existing literature protocol; no finite search certifies
  novelty.
- A factory may install this capability, but substantive stewardship runs only
  inside the selected laboratory's own project context.

## Non-negotiable boundaries

- Treat persisted files as the visibility boundary. Do not reconstruct a
  chat-only result; label it `NOT_PERSISTED` and request or prepare a future
  checkpoint.
- Preserve source originals, checkpoints, attempts, counterexamples, search
  rounds, verifier reports, prior surveys, migration records, and candidate
  evidence. Existing append-only evidence is never rewritten by maintenance.
- Do not delete or silently archive anything. Put proposed deletions, scope
  changes, target changes, and ambiguous merges in `deferred`.
- Do not edit kernel skills, workflows, scripts, schemas, templates, or agent
  roles inside a live laboratory. Record a factory improvement proposal.
- Hashes identify bytes and transaction state. Validators check declared
  structure. Neither proves mathematics, source truth, novelty, importance, or
  actual agent independence.

## Finding and repair classes

Classify every finding before staging a write.

1. `MECHANICAL_HYGIENE`: deterministic indexes, internal links, duplicate
   navigation, stale derived state, missing nonsemantic registration, or
   formatting that cannot change mathematical meaning.
2. `EVIDENCE_RECONCILIATION`: the same exact claim and scope have inconsistent
   metadata, while named local evidence determines a conservative repair.
3. `RESEARCH_ORGANIZATION`: backlog, dossier, checkpoint, source, or output
   organization that improves recoverability without changing truth status.
4. `NEW_UNVERIFIED_RESEARCH`: a new direction, example, computation, lemma
   candidate, or bounded repair artifact. Store it in the normal research tree
   and label it unverified.
5. `PROTECTED_STATUS_TRANSITION`: record an already-established transition only
   after its complete existing evidence and independent verification gates are
   checked against the exact claim scope.
6. `DEFER_USER_DECISION`: a useful action that changes identity, scope,
   priorities, public disclosure, resources, or another material preference.

`DEFER_USER_DECISION` never appears in the executable change list.

## Phase A: stable preflight and whole-state audit

Choose a run ID such as `<UTC>-<short-label>` and run:

```text
python3 scripts/laboratory_stewardship.py start \
  --run-id <id> --mode DEEP_LOCAL --json
```

The command refuses partial inventory coverage and creates only the excluded
run packet. Until `prepare`, do not modify observable laboratory state.

Audit at least:

- mission, tracks, backlog, decisions, warnings, conventions, and outputs;
- all active, backlog, and closed dossiers, including route state, failures,
  candidate lineage, attacks, computations, and verifier reports;
- result, conjecture, example, question, warning, and research-state ledgers;
- research notes and checkpoints, including orphans and chat-only blind spots;
- source registry, digests, bibliography, exact imported dependencies, and
  unprocessed intake;
- status, scope, hypothesis, coefficient, grading, and convention agreement at
  every cross-reference;
- semantic progress, stalled routes, useful negative knowledge, strength and
  weakness of established material, generalization frontiers, and output value.

For a nontrivial laboratory, delegate bounded read-only scans by track or
evidence function. An independent proof/status assessment must not inherit a
favored conclusion merely to agree with the coordinator. Scout reports are
navigation until checked against their cited artifacts.

Write `diagnosis.md`. Rank findings by mathematical consequence and repair
value, not by file count. A polished candidate without decisive verification is
not stronger than its evidence status.

## Phase B: finite repair plan and staging

Complete `repair_plan.json` and place every proposed after-image at
`staged/<target-relative-path>`. Follow
`templates/laboratory_stewardship_plan.json`.

Each executable change binds:

- a unique ID, `ADD` or `UPDATE`, canonical target path, repair class, and
  concise reason;
- exact evidence paths;
- the expected preimage SHA-256 (`null` for `ADD`) and staged after-image
  SHA-256;
- mathematical effect: `NONE`, `EXPOSITION_ONLY`,
  `NEW_UNVERIFIED_RESEARCH`, or `RECORD_EXISTING_VERDICT`;
- for every status reconciliation, an immutable exact-scope path and digest;
  for `RECORD_EXISTING_VERDICT`, complete claim/problem/target identity and status
  transition binding.

`protected_evidence` must bind the exact scope artifact, proof-search state,
closure manifest, and decisive verifier report by project-relative path and
SHA-256. The proof-search state must itself say `VERIFIED_PROOF`, bind that exact
scope and closure, and name a completed `I3 PASS` report with the same digest.
The change, transition, proof-search state, and closure manifest must agree on
the same `claim_id`/`target_id` and `problem_id`; cross-claim evidence is never
reusable. Stewardship v1 does not create or rewrite files under
`results/verified/`; it may only reconcile an existing claim's structured
ledger or dossier status through the complete protected gate.
`prepare` reruns `validate_proof_search.py` before such a transition can be
frozen.

The plan must be finite. In `DEEP_LOCAL`, one bounded repair wave may address a
high-value existing `GS1`/`GS2` issue when its target is already frozen and the
normal proof workflow applies. A material repair receives a new candidate ID
and invalidates affected old verdicts. `GS3`-`GS5`, new main theorems, or
multi-round campaigns become ranked next rounds rather than unbounded cleanup.

Run:

```text
python3 scripts/laboratory_stewardship.py prepare --run-id <id> --json
```

Preparation fails on drift, traversal, links, special files, no-clobber
collisions, mutable-evidence rewrites, missing evidence, hash mismatch, an
unsupported path, or an insufficient protected-status binding. It freezes the
plan and preserves all update preimages before any live repair.

## Protected mathematical reconciliation

Status vocabularies are not interchangeable. Keep ledger, dossier, route,
result, formalization, and verifier labels side by side. If statement or scope
differs, use `UNRECONCILED` and defer the transition.

- Never promote from exposition quality, model consensus, a survey, a
  compilation, a structural hash, or `validate_ledgers.py` alone.
- A proof candidate changed during stewardship needs a new canonical identity,
  SHA-256, lineage, and fresh decisive audit.
- `RECORD_EXISTING_VERDICT` requires the exact frozen scope, the relevant
  proof-search state, closure manifest, and decisive disjoint `I3` verifier
  report. In v1 this positive proof gate authorizes only proof-established
  destinations; refutation, computer-checked, and formal-verification labels
  require their own unsupported gates and are therefore deferred. Run the full
  proof-search validator and independently confirm scope.
- Formal compilation without trusted-boundary and exact statement-
  correspondence evidence cannot authorize an informal claim transition.
- A conservative status correction that is not an upgrade still preserves the
  prior label and evidence history. When scope is ambiguous, do not guess.
- Structured status artifacts must remain in the laboratory's JSON-compatible
  YAML form. Their stable owner-to-status mapping may not be reordered or
  transferred between claim IDs. Conservative reconciliation is limited to the
  script's explicit non-decisive vocabulary; an unfamiliar destination fails
  closed rather than becoming safe by omission from a strong-status list.

## Phase C: guarded application

Run:

```text
python3 scripts/laboratory_stewardship.py apply --run-id <id> --json
```

Application revalidates every preimage, writes an fsynced intent/applied
journal, and atomically publishes only the frozen staged bytes. It never
deletes. During publication the manifest is `APPLYING`. A partial failure
remains `PARTIAL_APPLY` with exact per-path journal state and byte-for-byte
backups. After the cause is understood, use the hash-reconstructing recovery
command rather than manually editing the packet:

```text
python3 scripts/laboratory_stewardship.py resume --run-id <id> --json
```

`resume` accepts only exact frozen preimages or already-installed after-images;
any third state is drift.

Do not make manual edits between `prepare`, `apply`, and `finalize`. A newly
needed repair gets another run rather than an invisible expansion of scope.

## Phase D: validation, final survey, and handoff

Complete `report.md` from `templates/laboratory_stewardship_report.md`. It must
contain a full post-repair project picture, not merely a list of edited files.
Remove the incomplete marker, set `Stewardship report status: COMPLETE`, and
populate every numbered section.
Then run:

```text
python3 scripts/laboratory_stewardship.py finalize --run-id <id> --json
```

Finalization requires:

1. exact agreement between the frozen plan and all changed observable paths;
2. doctor, laboratory validator, ledger validator, proof-search validator, and
   full eval with report output disabled;
3. a stable sealed survey that rechecks its inventory, bindings, report,
   manifest, and start seal;
4. refresh of `knowledge/resume.md` after that survey, so resume points to the
   final state, followed by a fresh-survey recheck;
5. an immutable completion-basis artifact binding the plan, before/after
   images, validation, and stewardship report;
6. a persisted whole-laboratory survey whose starting and finishing inventories
   are stable and whose manifest binds that completion basis.

The stewardship packet is excluded from the survey basis to avoid recursive
staleness; its immutable completion basis is included as an explicit external
binding and rechecked at survey finalization. If either project state or the
binding drifts, do not publish a fresh overview.

Finalization is resumable after a validation record, completion basis, or
stable-survey publication crash. Re-run `resume`; it verifies existing phase
artifacts before continuing and never silently widens the repair plan.

Return:

- `COMPLETED`, `DRIFT_DETECTED`, `FAILED_VALIDATION`, or `PARTIAL_APPLY`;
- the run packet and final survey paths;
- exact applied and deferred repairs;
- the strongest established results and what they do not establish;
- remaining weak points, conflicts, failures, and unprocessed material;
- a small ranked portfolio of next rounds with artifacts, falsifiers,
  verification routes, and stop conditions;
- only the user decisions that materially change the next course.

Completion says the laboratory is coherently maintained, not that its open
mathematics is true, novel, important, or solved.
