# Lean Room operator checklist

Use this checklist together with `workflows/lean_room_protocol.md`. It is a
memory aid, not a substitute for the case contract or an independent audit.

## Before source editing

- Confirm `scripts/lean_room.py status --json` reports `enabled`.
- For a campaign-sized target, review the suitability/assembly-gap assessment,
  library-readiness evidence, representative vertical pilot, and detailed
  informal proof blueprint as useful defaults. If another target, sequence,
  representation, or method is more informative, record the rationale,
  discriminating experiment, and bounded stop condition instead.
- Expand every omitted "standard" or "routine" fact into a typed blueprint
  step with its intended library lemma or an explicit new local obligation.
- Identify one problem dossier, one obligation ID, and one case ID.
- Hash the exact informal target artifact.
- State the formal declaration name and complete type.
- List encoding choices and every bridge lemma needed for correspondence.
- Pin Lean, Lake, the dependency-free manifest, and the build command.
- Start with no allowed axioms. If required, choose only from the hard v1 set
  `propext`, `Classical.choice`, `Quot.sound`, and write a substantive rationale
  for every selected name.
- For v1, require `dependency_free: true`, an empty dependency list, and an
  empty Lake `packages` array. Dependency-bearing/imported work is ineligible
  for v1 LR2–LR6; route only a bounded, reviewed input through the separate v2
  dependency-pilot checklist below.

## Before a build

- Recheck room state.
- Record a checkpoint with the main-goal dependency delta and redundant-lemma
  fingerprint. If this would be the second consecutive semantic no-progress
  checkpoint, review the loop and normally pause. A bounded continuation may
  seek one named discriminating observation when the unchanged blocker,
  mathematical rationale, and stop condition are recorded; it does not reset
  the stall count or upgrade status. Independent audit, proof expansion, and a
  representation pivot are useful interventions, not an exhaustive list.
- Confirm there is no path traversal or symlink escape from the case.
- Confirm the v1 dependency set and Lake package list are both empty.
- Confirm every explicit Lean import is a canonical ASCII project-local module;
  reject external, modified, or quoted imports.
- Scan all project and configuration sources, not only the theorem file.
- Reject custom syntax/notation and elaboration-time file, certificate, or
  solver inputs (`include_str`, `compile_time_search_path%`, `bv_check`,
  `bv_decide`).
- Never run external post-update hooks, arbitrary shell scripts, or network
  fetches as part of a certificate build.

## Before a v2 dependency pilot

- Confirm the durable room is explicitly `enabled`; the snapshot importer and
  pilot runner may never enable it.
- Separate acquisition from evidence. Require an already-resolved clean Lake
  workspace whose strict raw manifest pins every package by exact Git object
  ID; never let the importer call Lake, Lean, Elan, Git fetch, or a network
  helper.
- Import into a new source-only snapshot, validate it independently, and bind
  the raw manifest, graph, closure, exact revisions/trees, source inventories,
  toolchains, configurations, and every normalization/omission record.
- Treat a materialized tracked link as an explicit normalization. Treat an
  empty Gitlink record as absent source, not a vendored dependency; the review
  and build must fail if the pilot needs its contents.
- Complete `dependency_snapshot_review.yaml`: review every package's executable
  configuration surface, accept the expanded trusted boundary, resolve all
  open issues, bind the snapshot artifact/graph/closure, and explicitly
  authorize Phase B. Enumerate any indispensable source-adjacent Lake `.hash`
  sidecar by exact package, source, matching tracked trace, controlled reason
  code `LAKE_REHASH_TRACKED_TRACE_CACHE`, justification, and explicit residual
  risk. Require literal `file-write-data` only; never approve a parent
  directory, wildcard, metadata write, untracked source, or arbitrary generated
  file.
- Require a canonical small pilot project, exact toolchain, exact raw manifest
  bytes, no `lakefile.lean`, no Git/cache/precompiled artifacts, one named
  declaration defined in the compiled canonical `LeanRoomCase.lean`, one exact
  expected type, and an explicit permitted-axiom set. A same-named declaration
  in an out-of-glob root file is not admissible.
- Use only `verify_lean_dependency_pilot.py`. Require a disposable source copy,
  generated path overrides for all packages, `--rehash --reconfigure
  --keep-toolchain --no-cache`, deny-network Seatbelt, minimal environment,
  exactly one Lake build, immutable controls and tracked source inputs, a hash-
  bound `.olean`/`.ilean` inventory, separately bound reviewed `.hash`
  sidecars with literal-file-only write permission, and read-only non-
  executable Lake output trees
  during post-build checks. Require pinned direct Lean exact-type/axiom probes
  under a deterministic copied-build `LEAN_PATH`; when `leanchecker` is
  required, require both the pinned-Lake-environment and direct deterministic-
  path checks. Preserve append-only evidence.
- Report a pass only as `PILOT_VERIFIED_NOT_CERTIFIED`. It is not LR evidence,
  a statement-correspondence verdict, upstream authentication, or permission
  to change a theorem/dossier/ledger status.

## Before a certificate

- Match the source-tree digest to the successful build run.
- Preserve the exact build command, exit code, duration, stdout/stderr, and
  `lean --version`/`lake --version` output.
- Preserve `#print axioms` output for every claimed declaration.
- Confirm the generated probe used raw-type `Lean.Meta.isDefEq` and audited
  axioms for both the declaration and private exact-target wrapper.
- Require a separate correspondence report and independent rebuild.
- Treat correspondence as an LR4 audit artifact: builds bind the frozen case,
  while the PASS audit snapshots and hashes the completed report and verdict.
- Complete the bound `correspondence_verdict.yaml`: all eight semantic checks,
  all ten mandatory attack classes with PASS evidence, no open obligations or
  objections, exact scope, explicit non-claims, and `highest_gap_class: GS0`.
- Bind all artifacts by path and SHA-256 in an append-only certificate
  manifest.
- Use an issuer ID distinct from candidate and independent runners; allow the
  issuer to create the mandatory fresh `run_kind=certification` rebuild and
  bind its complete run tree and axiom report. Do not substitute an older run.
- Scope the certificate to exactly one frozen obligation.
- If the candidate is a maintainability refactor, confirm it has a successor
  case ID, fresh source binding, fresh rebuilds, and a fresh correspondence
  audit; do not inherit the predecessor certificate.
- State that auditor identity/independence is locally attested rather than
  OS-sealed or cryptographically authenticated, and that the v1 TCB includes
  the host OS/filesystem, guard scripts, pinned Lean binaries, and Seatbelt.

## Mandatory negative checks

- `sorry` or `admit` appears anywhere in scanned Lean/config sources.
- A project-defined `axiom` or `constant` evades the allowed trusted boundary.
- `unsafe`, unauthorized `native_decide`, foreign code, plugin, or generated
  object code enters the proof path.
- A modified/external import, custom notation/parser, embedded host file,
  external certificate, or solver process enters elaboration.
- A dependency floats by branch/tag/range or `lake-manifest.json` is absent.
- A v2 dependency pilot lacks a validated source snapshot, complete package
  review, exact graph/closure/project binding, supported isolation, or full
  offline rebuild.
- The successful log belongs to an older source-tree digest.
- The theorem compiles but has fewer hypotheses, stronger assumptions, a
  different domain, or a weaker conclusion than the frozen informal target.
- The decisive auditor generated or materially repaired the same case.

Any one of these blocks LR6 until resolved in a new immutable run or case.
