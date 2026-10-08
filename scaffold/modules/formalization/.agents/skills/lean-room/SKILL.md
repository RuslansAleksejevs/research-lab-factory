---
name: lean-room
description: Operate the laboratory's fail-closed Lean formalization room. Use when a user asks to formalize, compile, rebuild, audit, or certify a mathematical claim in Lean; when importing an external Lean project; when checking the correspondence between an informal theorem and compiled code; or when enabling, disabling, or querying Lean Room. The canonical phrase «Отключи Lean-комнату.» must immediately disable all new Lean work without deleting existing artifacts.
---

# Lean Room

## Purpose

Turn one frozen mathematical obligation into a reproducible Lean artifact and,
only after independent checks, a narrowly scoped formal certificate. Treat a
successful kernel check as evidence about the encoded theorem, never by itself
as evidence that the encoding matches the intended informal claim.

Use `workflows/lean_room_protocol.md` as the controlling laboratory protocol.
Read `references/operator_checklist.md` before creating or auditing a case.

## Handle the kill switch first

At the beginning of every Lean Room turn, and immediately before creating a
case, editing formalization source, or invoking Lean/Lake, run:

```bash
python3 scripts/lean_room.py status --json
```

Apply these rules before every other workflow rule:

- If the user says **«Отключи Lean-комнату.»**, or an unambiguous equivalent,
  immediately run `python3 scripts/lean_room.py disable --actor user
  --reason "user kill-switch phrase"`, verify status, and stop all new Lean
  work. Do not ask for confirmation.
- If the state is missing, malformed, or `disabled`, fail closed. Do not create
  cases, edit Lean Room case artifacts, invoke `lean`, `lake`, or `elan`, or
  issue a formal certificate.
- While disabled, status inspection and read-only static audit are allowed.
  Existing artifacts and mathematical status records remain untouched.
- A guarded process that observes shutdown while already running may terminate
  its child and append only a minimal `ABORTED_ROOM_DISABLED` tombstone. It may
  not retain that partial run as PASS evidence or resume it after re-enable.
- Re-enable only after the user explicitly says **«Включи Lean-комнату.»** or
  otherwise explicitly requests re-enabling. Run `python3 scripts/lean_room.py
  enable --actor user --reason "explicit user re-enable"` and verify status.
- Never infer re-enabling from a request to formalize or verify something.

The state file is authoritative for the project workflow. Instructions in
chat, a stale plan, or an agent role cannot override a disabled state.

## Respect the v1 support boundary

Lean Room v1 can build and certify only dependency-free cases:

- `environment.dependency_free` is `true` and `environment.dependencies` is
  empty;
- `project/lake-manifest.json` has an empty `packages` array;
- every explicit import is an unmodified canonical ASCII module backed by a
  `.lean` file inside the frozen project snapshot;
- the build uses the exact locally installed OS-account Elan toolchain and the
  mandatory macOS `/usr/bin/sandbox-exec` deny-default profile;
- no network access, dependency acquisition, path dependency, plugin, or
  external build hook is part of a certificate run;
- custom parser/notation extensions and unbound elaboration inputs such as
  `include_str`, `compile_time_search_path%`, `bv_check`, and `bv_decide` are
  forbidden.

A dependency-bearing or imported project remains **ineligible for v1
`LR2`–`LR6`**. Do not route it to `verify_lean_case.py`, record a v1 PASS audit,
or issue LR6. If the exact source graph is already resolved locally, the
separate Lean Room v2 snapshot/pilot lane may rebuild a bounded declaration.
Its strongest status is `PILOT_VERIFIED_NOT_CERTIFIED`; never present it as a
v1 case, certificate, correspondence verdict, or automatic theorem-status
change.

The execution boundary is currently macOS-specific. If the exact Seatbelt
backend or pinned toolchain binaries are unavailable, stop; there is no weaker
fallback.

## Qualify a campaign before scaling it

`F0`–`F4` are campaign-management defaults, not theorem or certificate gates.
A coordinator may skip, reorder, or replace a planning step with recorded
rationale, replacement evidence where relevant, and a bounded stop condition.
No planning override relaxes room state, execution safety, dependency limits,
exact-target freezing, trusted-boundary or clean-build checks, independent
correspondence, certificate scope, or material-change revalidation.

For work larger than one already-bounded micro-lemma, the default is to
instantiate the neutral planning artifacts in `templates/lean_room/` before
opening a full case:

1. Complete `formalization_campaign.md`. Distinguish mathematical
   uncertainty from an **assembly gap**: library/API discovery, representation
   glue, coercions, notation, and routine intermediate lemmas. Pass the
   library-readiness gate only when the required definitions and lemma surface
   are identified under the actual supported dependency boundary.
2. Normally run one small vertical pilot end to end before approving a full
   campaign. A qualifying pilot exercises a representative object, bridge
   lemma, target declaration, guarded build, and correspondence check. A toy
   statement that avoids the difficult representation does not provide that
   evidence. A recorded override states why the pilot is uninformative, what
   bounded evidence replaces it, and the stop condition.
3. Normally complete `proof_blueprint.md`. Expand the informal proof down to
   named, typed steps; spell out every fact previously dismissed as standard,
   immediate, or routine; record edge cases and likely library counterparts.
4. After each meaningful attempt, append a rendered
   `formalization_checkpoint.md`. Record the before/after main-goal dependency
   set and a redundant-lemma fingerprint (normalized statement, hypotheses,
   namespace/import context, search terms, and candidate library matches).
   Compiling more helper code or changing line count is not semantic progress
   unless the dependency frontier or a bound correspondence obligation moves.
5. After two consecutive checkpoints with `semantic_progress: false`, review
   the current loop and normally pause it. Bounded continuation is allowed with
   the unchanged blocker, mathematical rationale, discriminating observation,
   and stop condition recorded; it does not reset the count or upgrade status.
   Independent audit, proof expansion, and representation pivot are useful but
   not exhaustive interventions. A paraphrase alone is not an intervention.
6. Normally close correctness before maintainability work. A material refactor
   of a correct or frozen formalization uses `refactor_audit.md`, creates a
   successor case, and repeats the guarded rebuild and correspondence audit.
   No predecessor certificate or PASS verdict transfers automatically.

Planning gates do not enable the room, expand Lean Room v1, turn the v2 pilot
lane into certification, or certify a theorem. If the room is disabled, do not
instantiate or edit campaign or case artifacts or execute Phase B; restrict
work to read-only review until explicit re-enabling.

## Select the operation

### Create and formalize a case

1. Confirm the applicable campaign plan, pilot evidence, and proof blueprint,
   or record the bounded planning override and replacement evidence. For a
   deliberately tiny one-off obligation, record why a separate campaign is
   unnecessary. No planning override waives LR0 or any later integrity gate.
2. Freeze one exact obligation in the problem dossier. Record quantifiers,
   hypotheses, ambient types, domains/codomains, coefficients, degrees, signs,
   normalizations, and the exact informal source artifact.
3. Create the DRAFT case with the exact CLI shape below. Target and obligation
   artifacts must be regular root-relative files in the same problem dossier.

   ```bash
   python3 scripts/new_lean_case.py <problem-id> <case-id> \
     --informal-statement "<exact informal statement>" \
     --theorem <Qualified.declarationName> \
     --exact-formal-type "<exact Lean type>" \
     --target-id <target-id> \
     --target-artifact <root-relative-target-artifact> \
     --obligation-artifact <root-relative-obligation-artifact> \
     --obligation-id <obligation-id> \
     --actor <coordinator-id>
   ```

   The case is created at
   `problems/active/<problem-id>/formalization/cases/<case-id>/`.
4. Complete `formalization_contract.yaml` before writing proof code. Bind the
   contract to the immutable informal target and obligation artifact by
   SHA-256. Complete every LR0 readiness attestation, semantic list, encoding
   choice, lineage field, trust-boundary field, acceptance criterion, and stop
   condition. New cases permit no axioms by default. If the declaration truly
   needs one, v1 accepts only `propext`, `Classical.choice`, or `Quot.sound`;
   add only the needed names and a substantive, exactly keyed
   `permitted_axiom_rationales` entry before LR0.
5. Freeze the semantic contract:

   ```bash
   python3 scripts/freeze_lean_case.py <problem-id> <case-id> \
     --gate LR0 --actor <coordinator-id> --json
   ```

6. Write the smallest dependency-free formalization that tests the stated
   obligation. Keep bridge assumptions explicit; never hide an informal gap as a Lean axiom,
   stronger hypothesis, changed definition, or weaker conclusion.
   In executable v1, imports must be canonical project-local modules. Do not
   use modified/quoted external imports, custom syntax/notation, embedded file
   reads, external certificates, or solver-backed elaboration.
7. Freeze the environment and source tree, then statically validate the exact
   frozen case:

   ```bash
   python3 scripts/freeze_lean_case.py <problem-id> <case-id> \
     --gate LR1 --actor <coordinator-id> --json
   python3 scripts/validate_lean_case.py <problem-id> <case-id> \
     --verification-ready --json
   ```

8. Produce candidate and independent guarded runs. The independent runner ID
   must differ from all generator/material-repair identities recorded in the
   contract:

   ```bash
   python3 scripts/verify_lean_case.py <problem-id> <case-id> \
     --run-kind candidate --runner-id <candidate-runner-id> --json
   python3 scripts/verify_lean_case.py <problem-id> <case-id> \
     --run-kind independent --runner-id <independent-auditor-id> --json
   ```

   Preserve the run IDs returned in the evidence paths. Do not bypass these
   scripts with direct Lean/Lake commands.
9. Complete both `formal_correspondence.md` and
   `correspondence_verdict.yaml`. A PASS report needs exact top-level
   `Status: PASS` and `- Verdict: PASS` lines and no open/template marker. The
   machine verdict must bind the contract, target, source tree, candidate run,
   independent run, auditor identity, and exact certificate scope; set all
   eight semantic checks from the canonical verdict template to `true`; record
   no open obligation or unresolved objection; use `highest_gap_class: GS0`;
   and give PASS evidence for exactly these mandatory attack classes:

   - `statement_weakening`;
   - `hidden_stronger_hypotheses`;
   - `vacuity`;
   - `inconsistent_assumptions`;
   - `swapped_quantifiers`;
   - `wrong_domains`;
   - `unused_hypotheses`;
   - `implicit_instances`;
   - `empty_types`;
   - `wrong_namespace_or_declaration`.

10. Record the decisive audit. `<independent-run-id>` is both the independent
   build ID and `--auditor-run-id`; `<independent-auditor-id>` must equal that
   run's `runner_id`:

   ```bash
   python3 scripts/record_lean_audit.py <problem-id> <case-id> \
     --auditor-id <independent-auditor-id> \
     --auditor-run-id <independent-run-id> \
     --candidate-run-id <candidate-run-id> \
     --independent-run-id <independent-run-id> \
     --verdict PASS --attest-exact-correspondence \
     --highest-gap-class GS0 --json
   ```

11. Only from the returned PASS audit ID, issue the exact-scope certificate:

    ```bash
    python3 scripts/issue_lean_certificate.py <problem-id> <case-id> \
      --audit-id <audit-id> --issued-by <certificate-issuer-id> \
      --rebuild-timeout 600 --json
    ```

    The certificate issuer ID must differ from both candidate and independent
    runner IDs. Issuance itself performs a third fresh guarded run with
    `run_kind=certification` and `runner_id=<certificate-issuer-id>`. It does
    not trust only the two writable prior run records. LR6 is published only if
    that run passes, reproduces the independent axiom set, and is bound beside
    the candidate and independent runs. A failed certification rebuild is
    preserved as failure evidence and blocks the certificate. Budget at least
    one additional full clean build/probe duration for this command; the
    timeout defaults to 600 seconds.

The Make wrappers are `room-status`, `room-disable`, `room-enable`,
`lean-freeze`, `lean-validate`, `lean-verify`, `lean-audit`,
`lean-certificate`, `lean-test`, `lean-snapshot-import`,
`lean-snapshot-validate`, `lean-snapshot-test`, `lean-dependency-pilot`, and
`lean-dependency-pilot-test`. Direct script commands above remain the canonical
interface. Never use `room-enable` unless the user explicitly re-enabled the
room.

### Rebuild imported Lean code

This route uses the separate Lean Room v2 dependency pilot and cannot produce
v1 `LR2`–`LR6`.

1. Preserve the original archive/repository snapshot, provenance, raw Lake
   manifest, exact commits, and any production prompt before modifying a
   working copy. Acquisition and resolution are separate from every pilot run.
2. From an already-resolved, clean workspace, create a new immutable source-
   only snapshot with `import_lean_dependency_snapshot.py`, then independently
   check it with `validate_lean_dependency_snapshot.py`. Never ask either
   command to fetch, update, or repair a dependency.
3. Instantiate `dependency_snapshot_review.yaml`; bind the exact snapshot,
   graph, and closure; review every package configuration/executable surface;
   leave no open issue; explicitly authorize Phase B. Source hashes do not
   authenticate upstream authorship, and any recorded empty Gitlink contains no
   source. If `--rehash` requires a source-adjacent cache sidecar for a tracked
   build trace, enumerate its exact package, source, trace, controlled reason
   code `LAKE_REHASH_TRACKED_TRACE_CACHE`, justification, and explicit residual
   risk; never authorize a directory, wildcard, metadata write, or arbitrary
   source-tree output.
4. Make the bounded pilot project byte-bind the snapshot's raw manifest and
   exact toolchain. Do not use `lakefile.lean`, local caches, Git metadata,
   precompiled output, unresolved templates, or compatibility patches hidden
   in the original snapshot.
5. Run only `verify_lean_dependency_pilot.py`. It must copy inputs to a
   disposable tree, generate path overrides for every package, deny network
   through Seatbelt, disable caches/resolution, require the declaration in the
   canonical compiled `LeanRoomCase.lean`, and perform exactly one Lake build.
   It must then hash-bind all `.olean`/`.ilean` outputs and every explicitly
   reviewed derived `.hash` sidecar, make every Lake output
   tree read-only, deny executable mapping from the build tree, and audit the
   exact declaration type and axioms with the pinned Lean binary under the
   deterministic copied-build `LEAN_PATH`. When `leanchecker` is required, the
   exact bound binary must pass both the pinned-Lake-environment invocation and
   the direct deterministic-path invocation. Never substitute an ad hoc direct
   `lake`, `lean`, or online resolver invocation. Supply a required runner ID
   and repeat `--permitted-axiom` for the explicit per-run subset of the hard
   three-name ceiling; the default allowance is empty.
6. Report success only as `PILOT_VERIFIED_NOT_CERTIFIED`, together with the
   exact source/graph/tool/state bindings, declaration type, axiom footprint,
   expanded trusted boundary, residual correspondence gap, and non-claims.
   Perform a separate mathematical correspondence audit before using the pilot
   to update ordinary research planning. It still cannot issue LR6 or change a
   theorem/ledger status automatically.

### Audit an existing case

1. Treat the case sources and build evidence as immutable inputs. Recompute all
   digests before trusting prior logs.
2. Scan for `sorry`, `admit`, custom axioms, unsafe declarations, unauthorized
   `native_decide`, custom parser/notation extensions, non-project imports,
   unbound file/certificate/solver inputs, code-generation escape hatches,
   unpinned dependencies, and source changes after build.
3. Inspect the transitive trusted boundary with `#print axioms` for every
   certificate theorem. Record the exact output, including any accepted
   classical or quotient axioms.
4. Audit semantic correspondence independently of compilation. Check both
   directions: every informal hypothesis appears with the intended meaning,
   and the formal conclusion has exactly the intended strength.
5. An agent that generated or materially repaired the code cannot perform the
   decisive independent rebuild/correspondence certification.

## Enforce the LR gates

Advance only in order:

- **LR0 — Contract frozen:** exact informal and formal targets, source digests,
  and correspondence obligations are complete.
- **LR1 — Environment pinned:** toolchain, explicit empty dependency set,
  canonical project-local import surface, project source tree, and allowed
  trust boundary are frozen.
- **LR2 — Clean build:** the guarded, network-free build succeeds from the
  frozen tree and produces append-only evidence.
- **LR3 — Trust audit:** forbidden constructs are absent and actual axioms agree
  with the case-selected subset of the hard v1 set `propext`,
  `Classical.choice`, and `Quot.sound`; every selected axiom has a recorded
  rationale. The generated probe compares the raw declaration type
  with the separately elaborated expected type by `Lean.Meta.isDefEq`, so a
  user-defined coercion cannot make a different type pass; it also prints
  axioms for both the declaration and a private exact-target wrapper.
- **LR4 — Correspondence audit:** an independent report establishes that the
  compiled declaration encodes the exact informal obligation, or records the
  remaining gap.
- **LR5 — Independent rebuild:** a verifier disjoint from generation/material
  repair reproduces LR2 and checks that the source digest is unchanged.
- **LR6 — Scoped certificate:** a fresh third certification rebuild passes and
  a manifest binds it together with LR0–LR5, candidate, independent, audit,
  scope, and axiom artifacts. It may discharge only the named proof
  obligation.

Any failed or missing gate blocks later gates. Never transform structural
success into `VERIFIED_PROOF`, theorem status, novelty, or ledger promotion.
Those remain governed by the problem dossier and adversarial proof workflow.

## Preserve evidence and failures

- Never overwrite a prior build, audit, or certificate. Use append-only run,
  audit, and certificate identifiers.
- A material change to the target, encoding, hypotheses, dependencies, source
  tree, or trust policy creates a new case ID or explicitly superseding version;
  it does not rewrite the certified case.
- A maintainability refactor is evaluated separately from correctness. If it
  changes formal source, helper-lemma architecture, representation, imports,
  declaration surface, or trusted boundary after LR1, render a refactor audit,
  create a successor case, and repeat build and correspondence gates.
- Preserve failed builds and correspondence failures when they are research
  evidence. Label them as failures, not certificates.
- Report the highest completed LR gate, exact blockers, source/tree hashes,
  build duration, and whether the run was generated, rebuilt, or independently
  audited.
- At the end of a substantive formalization round, use
  `record-research-checkpoint` for one dated outcome envelope linking the
  detailed case/build/audit/certificate artifacts. This does not replace Lean
  Room's gate-specific checkpoints or turn compilation into mathematical
  promotion.

## Stop conditions

Stop and report without improvising when:

- Lean Room is disabled or its state is unreadable;
- the informal target is not frozen precisely enough to encode;
- a nonempty dependency set is requested for v1 certification, or a v2 pilot
  lacks an already-resolved validated snapshot, complete review authorization,
  exact local toolchain, or supported isolation backend;
- executable source needs an external/modified import, custom parser/notation,
  embedded host input, external certificate, or solver process;
- an external project would require network access or unreviewed executable
  build steps beyond the user's authorization;
- the code compiles only after weakening the theorem or adding an unapproved
  trust assumption;
- two consecutive semantic no-progress checkpoints have occurred and neither
  an intervention nor a bounded continuation rationale, discriminating
  observation, and stop condition has been recorded;
- independent correspondence or rebuild evidence is unavailable.

Compilation is fast for small local cases, but human mathematical work usually
concentrates in target specification, library/API discovery, and semantic
correspondence. Report those costs separately from kernel/build time. Report
candidate, independent, and certification rebuild durations separately; LR6
always incurs that third guarded build rather than merely signing old files.

## State the trust limits

Every report must say that:

- local hashes bind the bytes observed in that run but do not authenticate the
  upstream Lean distribution, author, or agent;
- auditor identity and generator/auditor disjointness are enforced from local
  identifiers, lineage records, and attestations, not an OS-sealed or
  cryptographically authenticated identity;
- the trusted computing base includes the pinned Lean kernel/toolchain, the
  host OS and filesystem, the Python guard scripts, and macOS Seatbelt;
- a kernel PASS establishes only the encoded declaration under that boundary;
  semantic correspondence remains an independently audited mathematical claim.
