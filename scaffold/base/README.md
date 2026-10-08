# {{LAB_TITLE}}

This is a standalone Codex mathematical research laboratory. Its profile
declares either one article/coherent program or a bounded discovery portfolio
whose mature programs must spin out.

Mission: {{LAB_MISSION}}

Areas: {{LAB_AREAS}}

## Start here

1. Read `BOOTSTRAP_REPORT.md`, `LAB_PROFILE.json`, and
   `knowledge/resume.md`; correct any provisional assumptions before they affect research.
2. Run `make doctor` for structural readiness. Run `make doctor-strict` when
   you also want missing capabilities required by the selected modules or
   staged source types to fail the check.
3. Review imported materials in `00_INBOX_TO_ANALYZE/`.
4. Read `sources/TRUST_TIERS.md`, then run `make ingest TRUST_TIER=C` and
   `make index`. A tier already bound to a bootstrap file in `LAB_PROFILE.json`
   overrides the command fallback; `TRUST_TIER` applies only to unprofiled files.
5. If `deep_research_goal` is selected, read
   `workflows/deep_research_goal_protocol.md`; if `discovery_portfolio` is
   selected, read `portfolio/README.md`; if
   `team_collaboration` is also selected, read `collaboration/README.md` and
   prepare the first meeting-authorized cycle before assigning substantive work.
6. Open the initial problem dossier if one exists. Replace provisional wording,
   freeze the exact target and anti-goals, and select `LIGHT` or `FULL`.
7. Run `make validate` and `make eval` after architecture or structured-state
   changes.

## Natural-language requests

You can ask Codex to:

- ingest and digest these sources;
- formulate the exact claim and list hidden hypotheses;
- prove or refute it, preserving the exact gap;
- search for boundary cases or counterexamples;
- audit this candidate independently;
- send a bounded claim packet to ChatGPT Pro in a fresh browser chat and import
  its report as unverified evidence;
- assess whether a small proof-assistant pilot is worthwhile, expand omitted
  proof details, and audit the formal statement against the informal target;
- find and verify the exact literature dependency;
- turn verified material into a paper section or report;
- intake a user-supplied or source-bound lab-scouted candidate lead without
  claiming that it is open, and keep `Scout → Trial → Deep` allocation separate
  from mathematical status;
- qualify a candidate, record a substantial trial, or prepare a copy-only
  spin-out seed for a dedicated sibling laboratory;
- prepare and, after unanimous human authorization, run a team research cycle
  with explicit assignments and handoffs;
- propose a small ranked portfolio of new research directions;
- explain the current project map after a long pause;
- propose, run, and collect one bounded research round per selected laboratory
  through a separately installed local Laboratory Control Room;
- prepare a budgeted `Scout`, `Trial`, or six-hour `Deep` goal, or a separately
  confirmed resumable `Marathon`, without treating activity as progress;
- deeply put the laboratory in order, applying guarded repairs and ending with
  a fresh whole-project survey.

<!-- laboratory-survey-protocol:v1 -->
### Wake up and survey the laboratory

Say «давай проснёмся и окинем взором лабораторию», `shake head`, or
ask where the whole project stands. Codex will reconcile the durable research
state, distinguish proved scope from candidates and failures, expose missing or
conflicting records, map the generalization frontier, and propose a small set of
concrete next rounds. Add «и проверь, что нового в литературе» to
explicitly enable a dated external horizon check. The default survey is local
and read-only; ask to save it when you want an append-only survey package and a
fresh rolling overview.
<!-- /laboratory-survey-protocol:v1 -->

<!-- durable-research-memory:v1 -->
### Preserve and reactivate research rounds

Every substantive round leaves one compact structured checkpoint with its
actual research date, strongest honest outcome, applicable positive and
negative results, exact obstruction, evidence paths, and best continuation.
Detailed proofs and computations stay in their canonical dossier or artifact;
the checkpoint links them rather than duplicating them. Corrections create new
linked records and never rewrite history.

`research/checkpoint_index.json` is a deterministic local projection bound to
checkpoint SHA-256 values. Use `make memory-validate`, `make memory-index`, and
`scripts/research_memory.py search` to inspect it. The index is navigation, not
mathematical verification, and remains inside this laboratory.
<!-- /durable-research-memory:v1 -->

<!-- repository-first-protocol:v1 -->
### Repository-first research provenance

When `LAB_PROFILE.json.repository_first.enabled` is exactly `true`, this lab
can keep compact typed records for campaigns, phase changes, selected raw-run
provenance, failure families, adjacent results, source use, independent claim
axes, verification coverage, reviewed exports, and expert-feedback intake.
Raw-run records bind canonical Durable Research Memory checkpoint bytes and a
dossier anchor; expert-feedback findings bind exact reviewed claim preimages.
The policy is dormant when disabled: validation does not scan research records
and every write command fails closed.

Use `make repository-first-status`, `make repository-first-validate`, and
`make repository-first-test`. `make repository-first-observe ...` creates only
an explicit local snapshot from already recorded metadata; there is no
telemetry or background monitor. Raw execution bodies remain local and ignored
by default. Export building creates a reviewed local package manifest but never
sends it, initializes Git, contacts an expert, or changes a mathematical claim
status. Research Artifact Release v1 separately materializes that exact reviewed
selection as a deterministic local ZIP:

```bash
make research-release-build \
  RESEARCH_RELEASE_REQUEST=tmp/research-release-request.json
make research-release-validate
make research-release-validate \
  RESEARCH_RELEASE_ARCHIVE=research/repository_first/releases/<release-id>/<release-version>.zip
make research-release-test
```

The builder prints a JSON receipt containing the canonical ZIP `archive_path`
and exact-byte `archive_sha256`; JSON validation returns the same identity for
each archive plus bounded file/byte totals. It never compiles, executes, invokes
Git/GitHub, uses a network, creates a site, publishes, or promotes a claim.
Inside the ZIP, `research-artifact-release-<release_id>-<release_version>/` is
the sole top-level prefix. Audience labels are human-review metadata, not access
control. Release IDs are lowercase portable 1–96 character identifiers;
versions additionally forbid hyphens. Requested paths are portable
NFC-normalized relative POSIX paths (512 UTF-8 bytes overall, 255 UTF-8 bytes
per component), cannot collide topologically with each other or the generated
`README.md`/`manifest.json`, and become fully prefixed member names bounded at
1024 UTF-8 bytes. Topology comparisons use whole-path
NFKC-then-casefold-then-NFC portable identity. See
`workflows/repository_first_protocol.md` for the complete size and topology
contract.

`USER_PREFERENCES.md` is the portable, hash-bound user-policy view recorded in
the profile and origin manifest. It guides research taste but is not evidence
for correctness, novelty, significance, or attribution.
<!-- /repository-first-protocol:v1 -->

<!-- fleet-research-round-protocol:v1 -->
### Fleet research rounds from the Control Room

This laboratory includes local round helpers and compatibility markers. The
Laboratory Control Room dashboard and server are a separate optional installation;
they are not included in the public factory kit. Ordinary local research and
checkpoints work without them. Nothing connects or launches automatically.

When separately installed, the local Laboratory Control Room can ask this
laboratory for one read-only proposal, run an exact displayed and user-approved
scope, and later collect a
bounded result. Proposal and collection do not write. The run click creates an
immutable plan before work, permits normal evidence-gated research-state writes
and public research reading, preserves architecture and external-system
boundaries, and requires a new checkpoint even for partial or blocked work.

Durable orchestration lives under `research/rounds/<round-id>/`; the small
`control_room_status.json` there is derived navigation, while the mathematical
artifacts and checkpoint remain canonical. Use `make round-status
ROUND_ID=<round-id>`, `make round-validate`, and `make round-test` for local
inspection. The deterministic guard can detect and fail on protected-path
drift; guard policy v2 also serializes transitions on the architecture-owned
compatibility marker, rejects checkpoint hard links, and validates the full
terminal result/projection chain. It is not evidence that the mathematics is
correct.
<!-- /fleet-research-round-protocol:v1 -->

<!-- laboratory-stewardship-protocol:v1 -->
### Put the laboratory in order

Say «приведи лабораторию в порядок как следует», `put the laboratory in
order`, or ask for a deep active maintenance pass. Codex will audit the whole
durable state, freeze a finite repair plan, preserve every overwritten byte,
apply only staged evidence-conservative repairs, validate the laboratory, and
finish with a stable saved whole-project survey. The command is local-only by
default and never turns model confidence, polished prose, compilation, or
structural validation into mathematical verification. Interrupted application
or finalization can be resumed from its hash-bound phase without widening the
reviewed repair plan.
<!-- /laboratory-stewardship-protocol:v1 -->

## Main structure

- `00_INBOX_TO_ANALYZE/`: unprocessed project materials;
- `sources/`: preserved originals, extraction, digests, bibliography, registry;
- `knowledge/`: profile-level state, notation, warnings, and ledgers;
- `knowledge/laboratory_overview.md`: latest explicitly saved deep survey;
- `runs/laboratory_stewardship/`: guarded repair plans, preimages, journals,
  validation records, and immutable completion bindings;
- `problems/`: auditable dossiers for exact targets and gaps;
- `portfolio/`: optional discovery-candidate funnel, trials, parked blockers,
  transfers, and spin-out handoffs;
- `collaboration/`: optional team cycles, assignments, handoffs, contribution
  records, and repository setup state;
- `research/`: track work and append-only cross-round checkpoints not yet
  promoted to a dossier or paper;
- `research/checkpoint_index.json`: rebuildable local discovery map over dated
  research checkpoints, including dormant barriers and reactivation metadata;
- `research/rounds/`: immutable approved plans, append-only attempt guards and
  results, and bounded Control Room projections created only after an approved
  run click;
- `research/repository_first/`: opt-in typed provenance, reviewed local export
  manifests, derived immutable release ZIPs under `releases/<release-id>/`, and
  explicit passive observations; raw bodies remain under the ignored
  `research/raw_runs/archive/` boundary;
- `research/deep_goals/`: optional canonical no-overwrite goal contracts and
  sequence-numbered, previous-hash outcome-per-compute records; these are
  locally checkable provenance and scheduling state, not proof certificates or
  externally anchored deletion evidence;
- `results/`: verified, conditional, refuted, and unresolved artifacts;
- `paper/`, `talks/`: optional output modules when enabled;
- `templates/`, `workflows/`, `.agents/skills/`, `.codex/agents/`: laboratory
  kernel;
- `evals/`, `scripts/`: structural and behavioral safeguards;
- `.lab/manifest.json`: template version, bootstrap inputs, initial file hashes,
  and ownership classes.

When the optional `formalization` module is selected, Lean Room starts
fail-closed and must be explicitly enabled before executable Lean work. Its
build, trusted-boundary, statement-correspondence, and exact-scope certificate
gates remain distinct from ordinary proof and ledger promotion.
Dependency-bearing experiments use a separate source-only snapshot and
deny-network pilot path. A successful dependency pilot is recorded as pilot
evidence, not promoted into an `LR2`–`LR6` case or certificate.
Assembly-gap assessments, pilot-first sequencing, proof blueprints, and stall
interventions are planning defaults rather than restrictions on mathematical
target or proof-route choice. Recorded deviations do not relax those integrity
gates.

When the `external_llm` module is selected, `consult-chatgpt-pro` can prepare a
compressed SHA-256-bound capsule, send it through an explicitly authorized
ChatGPT browser interaction, and preserve the returned report. The browser's
visible Pro label is only an observation, and the report cannot change a claim
status without the normal source, proof, computation, or formal verification
gates.

The optional Claude terminal adapter is included and disabled by default.
When requested, Codex prepares the selected context, runs the bounded session,
and collects its output. The local intake helper checks the collected bytes and
can preserve readable copies, including useful partial work. Results remain
`UNVERIFIED_EXTERNAL_OUTPUT` until checked through the usual research workflow.
Record conclusions, uncertainty and next steps in the existing checkpoint
system. See `workflows/claude_terminal_protocol.md`.

## Important limitation

The default doctor reports structural readiness; it lists capability gaps but
does not fail on them. `doctor-strict` makes profile-relevant capability gaps
fatal. Neither mode, nor a passing validator, proves a theorem, authenticates a
run, verifies a source, establishes novelty, or proves that an information
boundary was actually respected.

<!-- claude-terminal-default:v1 -->
## Optional Claude workflow

The local switch is `config/integrations.json`; Claude is disabled by default.
An explicit request to use Claude lets Codex configure the adapter and prepare
that work. Follow `workflows/claude_terminal_protocol.md` for launch, resume and
collection. Preserve a bound session's original runner and sealed inputs.
Installation alone starts no research, retries no quota and authorizes no
private disclosure or paid usage change.

When discussing this workflow, name the executor of the next step: **Codex** or
**Claude**. Keep the two closing status lines short; say that no run is needed
when appropriate.
<!-- /claude-terminal-default:v1 -->
