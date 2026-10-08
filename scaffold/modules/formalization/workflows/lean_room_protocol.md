# Lean Room Protocol

Status: approved operational workflow for dependency-free Lean 4 certification
in Lean Room v1 and guarded, noncertifying dependency pilots in Lean Room v2.

The Lean Room turns one frozen mathematical obligation into an auditable Lean
case. It is deliberately narrower than proof search: a successful Lean build
establishes only the exact formal declaration under the recorded trusted
boundary. It does not by itself establish that the declaration is the intended
informal theorem, that an imported result is correctly cited, that the result
is novel, or that a dossier or protected ledger may be promoted.

## 1. Emergency control

The canonical one-sentence shutdown command is:

> Отключи Lean-комнату.

The canonical one-sentence re-enable command is:

> Включи Lean-комнату.

Shutdown requires no confirmation. On receipt, the coordinator must stop
launching new Lean work, persist the room state as `disabled`, and interrupt
running room workers at the next safe tool boundary. Already written sources,
logs, manifests, audits, and certificates are preserved byte-for-byte.
Shutdown never changes a mathematical status, retracts a result silently, or
deletes a case.

The room is fail-closed:

- a missing, unreadable, malformed, or unknown state is treated as `disabled`;
- no subagent, retry, scheduled task, setup script, or dependency resolver may
  re-enable it;
- only the explicit re-enable sentence (or its documented local administrative
  command issued on the user's explicit instruction) changes it to `enabled`;
- while disabled, room status and existing artifacts may be read and static
  schema checks may run, but no Lean process, Lake process, dependency fetch,
  source generation, repair, rebuild, audit build, or certificate issuance may
  begin;
- all official room entry points must consult the persistent state before
  acting. A direct `lean`, `lake`, or unguarded substitute is outside protocol.

If shutdown races with a build, mark that run `ABORTED_ROOM_DISABLED`; do not
reuse its partial output as evidence. Re-enabling does not resume it
automatically: create a new run ID.

## 2. Scope and non-claims

Use the room for a bounded theorem, lemma, counterexample certificate,
calculation, or exact proof obligation whose informal target is already frozen.
For an open or main theorem, the enclosing dossier remains under `FULL`
orchestration even if the formal case is small.

The room may produce `FORMAL_CERTIFICATE` evidence for named obligation IDs.
It never automatically:

- marks a theorem, route, dossier, paper claim, or ledger entry proved;
- closes obligations not enumerated in the certificate;
- establishes informal-to-formal correspondence;
- validates novelty, priority, attribution, or open status;
- certifies imported literature beyond the declarations actually checked; or
- converts finite computation or a stronger-hypothesis theorem into the
  original target.

Those decisions remain with the ordinary proof, source, and ledger workflows.

## 2A. Campaign qualification and progress control

`F0`–`F4` are campaign-management defaults, not theorem or certificate gates.
They advise whether and how to spend formalization effort; they do not select a
mathematical target, representation, or proof route. A coordinator may skip,
reorder, or replace a planning step with recorded rationale, replacement
evidence where relevant, and a bounded stop condition. Such a choice never
relaxes Lean Room state, execution safety, the supported dependency boundary,
exact-target freezing, trusted-boundary and clean-build checks, independent
correspondence, certificate scope, or material-change revalidation.

Formalization effort often fails in the assembly layer rather than at the
mathematical idea: locating the right library declarations, reconciling
representations, making implicit parameters explicit, and supplying routine
bridge lemmas. The default is to qualify that risk before opening a full
campaign. The neutral planning layout is:

```text
problems/active/<problem-id>/formalization/planning/<campaign-id>/
  formalization_campaign.md
  proof_blueprint.md
  checkpoints/<checkpoint-id>.md
  refactor_audits/<refactor-id>.md
```

These are planning and process-control artifacts, not LR evidence and not
certificates. They do not enable the room or widen the v1 dependency boundary.
When the room is disabled they remain read-only.

### `F0` — suitability, assembly-gap, and library-readiness assessment

Render `templates/lean_room/formalization_campaign.md` and record:

- why formalization is valuable for this exact target;
- whether the mathematical statement and representation are stable enough;
- which work is genuinely mathematical and which is assembly/API work;
- the required definitions, namespaces, imports, theorem names, coercions, and
  bridge lemmas under the actual supported toolchain and dependency boundary;
- the estimated cost of correspondence, maintenance, and repeated clean
  rebuilds; and
- a `GO`, `PILOT_ONLY`, or `NO_GO` resource-allocation recommendation with
  evidence.

These recommendations do not prohibit ordinary mathematics, static design, or
a differently justified bounded formal experiment, and they do not assign
theorem status.

Library readiness passes only when the required surface has been located and a
representative path through it is plausible. A guess that "the library must
contain this" is a failed gate. Under Lean Room v1, external dependencies such
as Mathlib remain planning/static-audit only; a library-readiness `GO` cannot
override that execution boundary.

### `F1` — small vertical pilot

The default before full formalization is the smallest representative
end-to-end slice: one real object in the intended representation, one
load-bearing bridge, one
target-shaped declaration, a guarded clean build where v1 permits it, and an
explicit correspondence check. A qualifying pilot crosses the suspected
assembly gap; an unrelated toy theorem does not supply that evidence. A
coordinator may skip or replace the pilot when it records why the pilot would
be uninformative, what bounded evidence replaces it, and a stop condition.
Record elapsed human/API search time separately from kernel/build time.

### `F2` — detailed informal proof blueprint

Normally render `templates/lean_room/proof_blueprint.md` and decompose the
proof into named, typed obligations in dependency order. Expand every phrase
such as "standard", "routine", "clearly", or "similarly" into an explicit statement, hypotheses,
edge cases, and expected library counterpart. Record representations and
conversion lemmas before code generation. The blueprint may expose a genuine
mathematical gap; do not disguise it as a library-search task. The blueprint is
a revisable current plan, not a privileged mathematical route. A successor plan
may change the route but may not silently change a frozen target or encoding.

### `F3` — checkpointed implementation

After every meaningful generation, repair, or library-search attempt, append a
rendered `templates/lean_room/formalization_checkpoint.md`. Every checkpoint
must record:

- the main goal's unresolved dependency set before and after the attempt;
- the added, discharged, split, or reopened obligations;
- `semantic_progress`, justified by movement of that dependency frontier or a
  bound correspondence obligation rather than by line count or compilation;
- a redundant-lemma fingerprint containing the normalized proposed statement,
  hypotheses, namespace/import context, search queries, and candidate existing
  lemmas; and
- the exact next experiment.

After two consecutive checkpoints with no semantic progress, review the current
loop. Normally pause it. Bounded continuation is allowed when the unchanged
blocker, a specific mathematical rationale, the discriminating observation
sought, and a stop condition are recorded. Continuation neither resets the
stall count nor upgrades status. Useful interventions include:

1. an independent audit of the statement, representation, and current proof;
2. expansion of the informal blueprint into smaller explicit obligations; or
3. a representation pivot with a new encoding analysis.

Repeating or paraphrasing the same prompt is not an intervention and cannot be
presented as progress. A representation pivot that changes an LR0-frozen
encoding requires a successor case.

### `F4` — correctness and maintainability evidence

Separating correctness and maintainability is recommended for audit clarity.
Normally close the exact case through its applicable LR gates before assessing
readability, naming, API stability, lemma granularity, and dependency hygiene
with `templates/lean_room/refactor_audit.md`.

A material refactor changes any formal source after LR1, the helper-lemma or
declaration surface, representation, import/dependency surface, trusted
boundary, or semantic correspondence argument. It creates a new successor case
and requires fresh guarded candidate, independent, and (if certification is
sought) certification builds plus a fresh LR4/LR5 correspondence audit. The
old certificate remains bound to the old bytes and never transfers. Pure prose
or navigation changes outside the frozen case may be recorded as nonmaterial,
but they cannot change what the certificate claims.

## 3. Threat model

Lean's kernel is a strong proof checker, but a Lean project is executable
software during elaboration and build. Treat every external repository,
`lakefile`, dependency, plugin, macro, elaborator, tactic, executable, build
script, and generated file as untrusted code until reviewed and pinned.

The default threat controls are:

1. Pin an exact Lean toolchain and every dependency revision. Commit or
   preserve the resolved `lake-manifest.json`.
2. Build from a clean, hash-bound copy. Do not certify a dirty checkout.
3. Run without network access after dependency acquisition. Record any
   acquisition as a separate, non-certificate setup event.
4. Do not expose secrets or unrelated private project material to the build.
5. Reject unresolved template tokens, `sorry`, `admit`, `sorryAx`, unexpected
   project `axiom` declarations, and unauthorized trust escapes.
6. Treat `native_decide`, custom code generators, `unsafe`, foreign functions,
   custom kernels, and nonstandard proof-producing plugins as prohibited unless
   the contract names the exact use, extends the trusted boundary, and receives
   an independent audit. Merely compiling is not authorization.
7. Record the complete axiom report of every certified declaration with
   `#print axioms`. Any axiom outside the case allowlist fails the trust gate.
8. A generator or material repairer cannot be the decisive auditor of the same
   case.

### Current v1 execution and trust boundary

Certificate builds are deliberately narrower than the general threat model:

- v1 accepts only dependency-free cases whose `lake-manifest.json` has an empty
  `packages` array and whose contract records `dependency_free: true` with an
  empty dependency list;
- v1 accepts explicit imports only when a canonical ASCII module name resolves
  to a `.lean` file inside the frozen project. External, modified, quoted, or
  module-system imports are not executable v1 inputs;
- v1 rejects custom syntax/notation and unbound elaboration inputs, including
  embedded host files, compile-time search paths, external bit-vector
  certificates, and solver processes;
- v1 resolves the exact pin only under the OS account's canonical Elan
  directory, hashes the `elan`, `lean`, and `lake` binaries used by the run,
  and ignores caller-supplied `PATH` and `HOME` for toolchain selection;
- v1 requires macOS `/usr/bin/sandbox-exec` with the deny-default Seatbelt
  profile and no network; there is no unsupported-platform or weaker-isolation
  fallback;
- the trusted computing base includes the pinned Lean kernel/toolchain, host OS
  and filesystem, Python guard scripts, and Seatbelt enforcement;
- binary and artifact hashes bind local bytes but do not authenticate the
  upstream distribution, author, or agent;
- auditor identity and claimed separation from generation/material repair are
  local identifier, lineage, and attestation checks. They are not OS-sealed or
  cryptographically authenticated proof of identity or information
  independence.

Therefore a dependency-bearing or imported project cannot pass v1
`LR2`–`LR6`. Lean Room v2 may instead test it through the separate source-only
snapshot lane in Section 9. That lane has its own Phase-A/Phase-B evidence and
can end only as `PILOT_VERIFIED_NOT_CERTIFIED`; it never turns a dependency
project into a v1 case, supplies an LR gate, or issues a certificate.

No axiom is permitted by default. The hard executable-v1 ceiling is exactly
`propext`, `Classical.choice`, and `Quot.sound`; a case chooses a subset and
must give a substantive, exactly keyed rationale for every chosen name. A
locally edited contract cannot expand this hard set.

## 4. Roles and separation

### Coordinator

Freezes the informal target, obligation IDs, acceptance criterion, anti-targets,
contract, and information exposure. The coordinator may synthesize code, but a
coordinator who materially authors or repairs it is not the decisive auditor.

### Formalization specialist

Creates the encoding and Lean proof. It records all modeling choices, imports,
assumptions, and the exact formal declaration. It may repair build failures but
cannot issue the decisive audit of its own source.

### Deterministic builder

Performs a clean guarded build and captures commands, versions, hashes, logs,
exit codes, scans, and axiom reports. A passing build is mechanical evidence,
not a semantic verdict.

### Correspondence auditor

Checks that the formal objects, hypotheses, quantifiers, conventions, edge
cases, and conclusion match the frozen informal target, including the direction
of every reduction. This audit is mathematical and cannot be replaced by a
schema validator.

### Independent formal auditor

Did not generate or materially repair the candidate. It independently rebuilds
the frozen source, checks the trust boundary and axiom reports, attacks the
encoding, and records a verdict. For a decisive certificate, the auditor's run
ID must be disjoint from all generator and material-repair run IDs.

### Certificate issuer

Has an identifier distinct from both candidate and independent build runners.
Issuance triggers a third clean guarded `certification` run under this
identifier, verifies it against the frozen case and independent axiom result,
and binds it into LR6. The issuer role adds fresh mechanical evidence; it does
not replace the independent semantic correspondence audit, and its local
identity is not cryptographically authenticated.

### Source auditor

Checks load-bearing imported theorems against primary sources when the informal
argument depends on their interpretation. Lean declaration names alone are not
bibliographic verification.

One person or agent may occupy multiple non-conflicting roles. Generation or
material repair and decisive audit may not be combined for one case.

Instantiate `templates/lean_room/generator_prompt.md` for generation and
`templates/lean_room/auditor_prompt.md` for the decisive audit. Preserve the
instantiated prompts or their exact digests with the case exposure records.
Prompt provenance is part of the audit: a later summary of what an agent was
"roughly asked" cannot establish target identity or independence.

## 5. Canonical case layout

Each case lives inside its problem dossier:

```text
problems/active/<problem-id>/formalization/cases/<case-id>/
  README.md
  formalization_contract.yaml
  formal_correspondence.md
  correspondence_verdict.yaml
  project/
    lean-toolchain
    lakefile.toml
    lake-manifest.json
    <package sources>.lean
  evidence/
    index.yaml
    freezes/<gate>-<freeze-id>/
      freeze_manifest.yaml
      contract.snapshot.yaml
      target.artifact.snapshot                 # LR0
      obligations.artifact.snapshot            # LR0
      source_tree_inventory.json                # LR1
      source_tree.sha256                        # LR1
    runs/<run-id>/
      build_manifest.yaml
      build.log
      source_tree.sha256
      source_tree_inventory.json
      declaration_audit.lean
      axioms.txt
  audits/
    index.yaml
    <audit-id>/
      formal_audit_manifest.yaml
      formal_correspondence.snapshot.md
      correspondence_verdict.snapshot.yaml
  certificates/
    index.yaml
    <certificate-id>/
      formal_certificate_manifest.yaml
```

`lake-manifest.json` is required in every v1 case and its `packages` array must
be empty. A dependency-free case records that fact explicitly in the contract
and build manifest. A nonempty package list is a hard v1 validation failure,
not a request to fetch dependencies.

The same run layout is used for `candidate`, `independent`, and
`certification` runs. LR6 creates the certification run itself and binds all
three run trees; an operator-supplied older certification run cannot replace
that fresh issuance-time rebuild.

Case IDs, run IDs, audit IDs, and certificate IDs are immutable identifiers.
After gate `LR1`, the contract and project source tree are frozen. A substantive
change to the informal target, encoding, formal type, assumptions, imports,
toolchain, dependency revisions, or proof source creates a new case ID with a
`supersedes_case_id` link. Build evidence, audits, certificates, and retractions
are append-only.

An `index.yaml` may name the current or latest artifact ID, but it is mutable
navigation data, not evidence. Updating an index never overwrites an artifact
and never changes the status of an older run.

The in-file case lifecycle is `DRAFT -> FROZEN`; it does not encode gate
results. `DRAFT` cannot be built as certificate evidence.
The guarded command `scripts/freeze_lean_case.py --gate LR0` freezes the
semantic payload while status remains `DRAFT`; after its freeze flag is set,
only project source, environment bindings, and freeze metadata needed for
`LR1` may be completed. The command
`scripts/freeze_lean_case.py --gate LR1` first proves the `LR0` payload
unchanged, freezes the project, and atomically changes status to `FROZEN`.
Only `FROZEN` is valid verifier input, and only when both
`freeze.lr0_contract_frozen` and `freeze.lr1_sources_frozen` are true and their
digests recompute.
Supersession is append-only and external to the frozen contract: the new
contract names `supersedes_case_id` and an index records the predecessor as
superseded. The frozen predecessor contract itself remains byte-identical; its
in-file status remains `FROZEN`.

Every freeze writes an append-only directory under
`evidence/freezes/<gate>-<freeze-id>/`. It preserves a contract snapshot, the
freeze manifest with the canonical-payload hash, LR0 copies of the exact target
and obligation artifacts, and at `LR1` the sorted project inventory and tree
digest. A mutable index may point to these snapshots, but no freeze artifact is
overwritten.

Canonical JSON means UTF-8 serialization with object keys recursively sorted,
compact separators, Unicode preserved rather than ASCII-escaped, and exactly
one trailing newline. `LR0` projects every top-level contract field except
`status`, `environment`, and `freeze`. Thus it binds schema
and record identity, case and problem IDs, orchestration, creation and
supersession metadata, room state at creation, target and obligation bindings,
informal and formal claims, encoding, trust boundary, correspondence
obligations, lineage, acceptance criterion, and stop conditions. Its SHA-256
is stored as `freeze.lr0_payload_sha256` and in the `LR0` freeze snapshot.
After that snapshot, only project sources, `environment`, `freeze`, and the
eventual `status` transition may change.

At `LR1`, recompute the projection and require exact equality with the `LR0`
digest. Inventory every regular file under `project/` by sorted relative POSIX
path and file SHA-256, excluding only top-level `.lake/` build output. Reject
every `.git` entry, symbolic link, socket, device, and unresolved template
token. The v1 tree digest is SHA-256 of the byte prefix
`lean-room-project-tree-v1` followed by a zero byte and, for each file in that
order, the eight-byte big-endian UTF-8 path length, path bytes, eight-byte
big-endian content length, and exact content bytes. The inventory separately
records path, size, and file SHA-256. Store the resulting tree digest as
`freeze.frozen_source_tree_sha256`. Then set status and both freeze flags,
set `freeze.frozen_contract_sha256` to `null`, canonicalize the complete
contract, hash it, and store that digest in the field. Verification repeats the
same null-and-hash operation. This canonical digest is not the raw digest of the
stored YAML bytes.

## 5A. Canonical operator CLI

Direct project scripts are the canonical interface. Every mutating command
below requires an enabled room; recheck status at each source-edit or build
boundary.

```bash
python3 scripts/lean_room.py status --json

python3 scripts/new_lean_case.py <problem-id> <case-id> \
  --informal-statement "<exact informal statement>" \
  --theorem <Qualified.declarationName> \
  --exact-formal-type "<exact Lean type>" \
  --target-id <target-id> \
  --target-artifact <root-relative-target-artifact> \
  --obligation-artifact <root-relative-obligation-artifact> \
  --obligation-id <obligation-id> \
  --actor <coordinator-id>

python3 scripts/freeze_lean_case.py <problem-id> <case-id> \
  --gate LR0 --actor <coordinator-id> --json
# Complete the dependency-free Lean source only after LR0.
python3 scripts/freeze_lean_case.py <problem-id> <case-id> \
  --gate LR1 --actor <coordinator-id> --json
python3 scripts/validate_lean_case.py <problem-id> <case-id> \
  --verification-ready --json

python3 scripts/verify_lean_case.py <problem-id> <case-id> \
  --run-kind candidate --runner-id <candidate-runner-id> --json
python3 scripts/verify_lean_case.py <problem-id> <case-id> \
  --run-kind independent --runner-id <independent-auditor-id> --json

python3 scripts/record_lean_audit.py <problem-id> <case-id> \
  --auditor-id <independent-auditor-id> \
  --auditor-run-id <independent-run-id> \
  --candidate-run-id <candidate-run-id> \
  --independent-run-id <independent-run-id> \
  --verdict PASS --attest-exact-correspondence \
  --highest-gap-class GS0 --json

python3 scripts/issue_lean_certificate.py <problem-id> <case-id> \
  --audit-id <audit-id> --issued-by <certificate-issuer-id> \
  --rebuild-timeout 600 --json
```

Before the PASS audit command, complete and independently review both
`formal_correspondence.md` and `correspondence_verdict.yaml`. The auditor ID
must equal the independent build's `runner_id`; `--auditor-run-id` must equal
that independent build's run ID. The audit and certificate IDs are returned by
their JSON output when not supplied explicitly.

The certificate issuer ID must differ from the candidate and independent
runner IDs. Certificate issuance is not a manifest-only operation: it invokes
a third fresh guarded build with `run_kind=certification`, binds that run and
its axiom report, and publishes LR6 only if it passes and agrees with the
independent axiom set. A failed third run is preserved and blocks issuance.
`--rebuild-timeout` bounds this additional build/probe and defaults to 600
seconds.

The Make wrappers are `room-status`, `room-disable`, `room-enable`,
`lean-freeze`, `lean-validate`, `lean-verify`, `lean-audit`,
`lean-certificate`, `lean-test`, `lean-snapshot-import`,
`lean-snapshot-validate`, `lean-snapshot-test`, `lean-dependency-pilot`, and
`lean-dependency-pilot-test`. `room-enable` is administrative plumbing, not
permission to infer re-enabling: use it only on the user's explicit re-enable
instruction.

## 6. Gates `LR0` through `LR6`

Every gate is fail-closed. `PASS` means only that the named gate's evidence is
complete. A later failure does not erase earlier evidence.

### `LR0` — critical contract projection frozen

Required:

- room state is `enabled`;
- exact problem ID, target ID and SHA-256 binding;
- exact proof-obligation IDs and their artifact binding;
- typed informal statement, hypotheses, quantifiers, ambient objects,
  conventions, edge cases, and anti-targets;
- formal declaration name, file, and exact intended Lean type;
- encoding map and named correspondence obligations;
- intended trusted boundary, axiom allowlist, and prohibited constructs;
- generation, repair, build, audit, and exposure identities;
- acceptance criterion and stop conditions.

Unknown information is an explicit open field and prevents freezing. Changing
a field in the `LR0` projection after its snapshot creates a new case. The LR0
freeze command stores `lr0_payload_sha256` and sets its freeze flag while status
remains `DRAFT`; it does not yet make the case verifier-eligible.

### `LR1` — sources and environment pinned

Required:

- exact `lean-toolchain` content and digest;
- exact `lakefile.toml` and empty-package `lake-manifest.json` digests;
- explicit `dependency_free: true` and an empty contract dependency list;
- canonical project-local imports only, with no external or modified import
  surface;
- complete sorted source-tree digest with no unresolved template tokens;
- no symbolic links or non-regular files anywhere in `project/`;
- external source provenance and license recorded when imported;
- contract and source tree marked frozen.

A nonempty package list, branch name, floating tag, unpinned URL, package
registry latest version, or working-tree description is not v1-certifiable.
`LR1` must reproduce the `LR0` payload,
write its append-only freeze snapshot, compute the canonical frozen-contract
digest, and set lifecycle status `FROZEN`.

### `LR2` — clean deterministic build

Required:

- a new append-only run ID;
- build begins only after a successful room-state check;
- clean build directory with no unrecorded generated source;
- exact commands, environment allowlist, tool versions, start/end times, exit
  codes, and full log recorded;
- network disabled during the certificate build;
- source-tree digest before and after build is identical;
- all required targets and declarations elaborate successfully.

A cached interactive success, editor diagnostic, copied terminal fragment, or
build over a dirty tree does not pass `LR2`.

### `LR3` — trusted-boundary audit

Required:

- lexical and structural scans find no unresolved placeholders, `sorry`,
  `admit`, `sorryAx`, unexpected project axioms, or unauthorized escapes;
- scans reject custom parser/notation extensions and unbound elaboration-time
  file, certificate, search-path, or external-solver inputs;
- every certified declaration has a captured `#print axioms` report;
- the generated exact-type probe compares the raw constant type with the
  separately elaborated expected type using `Lean.Meta.isDefEq`, without
  assignment through a coercion, then constructs a private exact-target wrapper
  and captures `#print axioms` for both subjects;
- every reported axiom is in the explicit allowlist;
- imports and dependency pins agree with `LR1`;
- generated binaries or native shortcuts do not replace kernel checking unless
  explicitly authorized and audited;
- the audit records the exact trusted computing base and residual risks.

Do not hide forbidden tokens in generated source, macros, comments used as
code generation inputs, or dependencies controlled by the case author.

### `LR4` — semantic correspondence

Required:

- every informal object and predicate maps to a precise Lean object and type;
- quantifier order, hypotheses, domains, codomains, coefficients, orientations,
  signs, finiteness, nonemptiness, choice principles, and boundary cases are
  compared explicitly;
- every simplification or strengthening is classified;
- the report proves the exact direction needed from the certified declaration
  back to the frozen target;
- every anti-target is ruled out;
- all open correspondence obligations are empty.

Compilation cannot pass `LR4`. If the formal theorem is only a special case, a
stronger-assumption variant, or a model whose connection remains conjectural,
record that exact partial status and stop before certification.

### `LR5` — independent rebuild and adversarial audit

Required:

- an eligible auditor with disjoint generation/material-repair lineage;
- a new clean build run from the frozen source and pins;
- independent repetition of trust scans and axiom inspection;
- adversarial attempts against statement weakening, vacuous hypotheses,
  inconsistent assumptions, empty types, swapped quantifiers, wrong namespace
  or declaration, unused hypotheses, and accidental local instances;
- verification that source digests match the candidate audited at `LR4`;
- an audit manifest with verdict `PASS` and no unresolved high-strength issue.

The original builder rerunning the same command is useful reproducibility
evidence but not an independent audit.

### `LR6` — exact-scope certificate eligible

Required:

- `LR0`–`LR5` all pass for the same immutable case and source digest;
- the issuer identity differs from the candidate and independent runners, and
  a fresh guarded `run_kind=certification` build passes immediately before
  publication with the same source binding and axiom set;
- one certificate manifest binds the contract, target, obligation IDs,
  declaration, candidate run, independent run, certification run, independent
  audit, correspondence report/verdict, certification axiom report, and all
  SHA-256 digests;
- the manifest lists exact assumptions, trusted boundary, residual caveats, and
  explicit non-claims;
- issuance occurs while the room is `enabled`.

`LR6` means the certificate is eligible to be cited as `FORMAL_CERTIFICATE`
evidence for only the enumerated obligations. A separate dossier decision must
decide whether that evidence closes a gap. No protected ledger changes here.
Operationally, a successful LR6 path therefore pays for at least three clean
guarded builds/probes—candidate, independent, and certification—in addition to
human target specification and correspondence work. Record their durations
separately.

## 7. Build and evidence procedure

1. Check room state. Stop on anything except exact `enabled`.
2. Validate `LR0` and `LR1` fields without executing project code.
3. Copy or mount the frozen source into a fresh build location.
4. Recompute the deterministic v1 project-tree digest and its path/size/file-
   SHA-256 inventory exactly as defined above; exclude only top-level `.lake/`
   build output and reject every `.git` entry.
5. Require the v1 manifest to have no packages and the contract to declare an
   empty dependency set. Dependency acquisition and the v2 source-snapshot
   lane remain separate from every v1 certificate build.
6. Execute only the contract's allowlisted build commands with a minimal
   environment and no network.
7. Capture combined logs and each exit code without truncation.
8. Run the forbidden-construct scan and `#print axioms` checks against the exact
   declarations in the contract.
9. Recompute source digests. Any mutation fails the run.
10. Write one append-only build manifest. Never repair the source in place and
    relabel the same run.

Build runs do not bind the still-pending LR4 correspondence prose. The
independent PASS audit copies, hashes, and binds the completed
`formal_correspondence.md` and `correspondence_verdict.yaml`; LR6 then binds
that audit snapshot.

Timestamps aid provenance but do not establish identity or independence. Hashes
bind bytes but do not establish mathematical truth or authorship.

## 8. Correspondence standard

The correspondence artifact is a proof obligation, not documentation polish.
It must contain:

- the frozen informal statement verbatim or by hash-bound reference;
- the exact pretty-printed Lean declaration type from the audited environment;
- a table mapping every object, relation, map, parameter, and hypothesis;
- a quantifier and type audit;
- convention and normalization choices;
- edge, degenerate, empty, and boundary cases;
- a direction-of-implication argument;
- a list of imported bridge lemmas and their source status;
- explicit anti-target checks;
- independent objections, resolutions, and remaining gaps.

The human-readable report is paired with the machine-checkable
`correspondence_verdict.yaml`. A PASS report contains exact `Status: PASS` and
`- Verdict: PASS` lines and no `OPEN`, `UNCHECKED`, `DRAFT`, `TODO`, `TBD`,
`UNKNOWN`, or unresolved template marker. The machine verdict must bind the
case, auditor and independent run identity, contract, target, source tree,
candidate run, independent run, and exact certificate scope. It must set these
checks to `true`: `quantifier_order_checked`, `types_and_domains_checked`,
`hypotheses_checked`, `conclusion_checked`,
`conventions_and_normalizations_checked`, `edge_cases_checked`,
`direction_back_to_frozen_target_established`, and
`anti_targets_ruled_out`.

It must also record a PASS outcome with nonempty evidence for exactly the ten
mandatory attack classes `statement_weakening`,
`hidden_stronger_hypotheses`, `vacuity`, `inconsistent_assumptions`,
`swapped_quantifiers`, `wrong_domains`, `unused_hypotheses`,
`implicit_instances`, `empty_types`, and
`wrong_namespace_or_declaration`. PASS additionally requires empty open
obligations and unresolved objections, `highest_gap_class: GS0`, a matching
exact certificate scope, and explicit non-claims. A Markdown assertion without
this bound verdict cannot pass LR4/LR5.

If correspondence relies on an unproved bridge theorem, classify the result as
conditional or as a formalization of the encoded model only. Do not issue an
exact-target certificate.

## 9. External and dependency-bearing Lean projects

Lean Room v2 supplies a separate, opt-in pilot lane for a pinned Lake graph.
It is not an extension of the v1 certificate gates. The durable room must be
explicitly `enabled` for Phase B, and every official command must recheck the
state. Phase A is read-only with respect to the resolved input and performs no
Lean/Lake execution; while the room is disabled it may be used only where the
local room policy permits static snapshot inspection. No command here may
enable the room, fetch a package, update a pin, or silently patch a source.

### Phase A — immutable source-only dependency snapshot

Acquisition is an earlier, separately recorded activity. Start from an already
resolved workspace whose strict Lake manifest contains exact Git object IDs.
Then run the guarded importer and validator:

```sh
python3 scripts/import_lean_dependency_snapshot.py \
  <resolved-workspace> <new-snapshot-directory> \
  --snapshot-id <snapshot-id> --actor <importer-id> --json
python3 scripts/validate_lean_dependency_snapshot.py \
  <snapshot-directory> --json
```

The importer never invokes Lean, Lake, Elan, a package manager, or a network
helper. It requires each package checkout to be clean and at the manifest's
exact revision, verifies the Git tree and index, and binds the raw Lake
manifest, graph, closure, toolchain, configuration and nested manifests, file
paths, modes, sizes, bytes, and SHA-256 inventories. It publishes only tracked
source bytes into a new directory by atomic no-overwrite rename. Git metadata,
Lake caches, precompiled artifacts, floating revisions, LFS pointers, unsafe
links, and special files fail closed. A narrowly supported tracked internal
link is recorded and materialized as a regular exact copy. A recorded empty
uninitialized Gitlink contains no source and remains an explicit reviewed risk;
it is never treated as a fetched dependency or certificate evidence.

Phase A success freezes input; it does not execute or verify a theorem. Missing
or rejected input is a visible non-pass, never permission to acquire or repair
dependencies automatically.

### Phase B — reviewed offline pilot build

Before execution, instantiate `dependency_snapshot_review.yaml`. Bind it to the
snapshot artifact, snapshot ID, dependency graph and closure; review every
package configuration and executable build surface; resolve every open issue;
accept the expanded trusted boundary; and set
`phase_b_execution_authorized: true`. This review is authorization for one
bound pilot input, not a mathematical verdict.

Lake `--rehash` may need to cache a content hash beside a tracked build trace.
Such a source-adjacent `.hash` is not accepted implicitly. The review must name
the exact package, bound source artifact, matching tracked `.trace`, controlled
reason code `LAKE_REHASH_TRACKED_TRACE_CACHE`, and a substantive explanation of
why Lake `--rehash` needs this derived sidecar. Its residual-risk record must
state that the exact artifact is derived, not snapshot input, literally and
temporarily writable, and leaves tracked source and trace bytes read-only. The
runner precreates only that absent disposable sidecar, grants Seatbelt
`file-write-data` access to that literal file rather than metadata or parent-
directory write access, requires the same inode and Lake's lowercase 16-hex
format, then makes it read-only and hash-binds it as derived build metadata. No
tracked source or trace byte becomes writable, and no other source-tree
addition is allowed.

The pilot project must be a small, canonical source project with an exact
toolchain and a raw `lake-manifest.json` byte-identical to the snapshot's root
manifest. It may not supply `lakefile.lean`, local caches, Git metadata,
precompiled output, unresolved templates, or an unbound dependency. The Phase-B
runner must:

1. validate the room state, snapshot, review, project inventory, expected exact
   declaration type, permitted axiom set, toolchain, and local executables
   before executing package code;
2. copy the project and snapshot into a new disposable build tree and generate
   path overrides for every package, without invoking dependency resolution;
3. build only through the allowlisted Lake command with `--packages`,
   `--rehash`, `--reconfigure`, `--keep-toolchain`, and `--no-cache` under the
   macOS deny-default Seatbelt profile with network forbidden and a minimal
   environment;
4. admit the requested declaration only when it is declared in the canonical
   compiled root module `LeanRoomCase.lean`; declarations found only in an
   out-of-glob root file cannot authorize execution or satisfy the later audit;
5. run exactly one Lake `build` command, then inventory and hash-bind every
   resulting `.olean` and `.ilean`, make all Lake output trees read-only for
   post-build checks, and deny executable mapping from the build tree;
6. scan for forbidden trust escapes and audit the exact declaration type and
   complete `#print axioms` footprint with the pinned `lean` binary and a
   deterministic `LEAN_PATH` formed only from the copied build roots. When the
   recorded policy requires `leanchecker`, run the exact bound binary both via
   the pinned Lake environment and directly through that deterministic path;
7. prove that controls, build artifacts, and bound tracked source inputs did not
   change across the applicable commands; separately validate and bind every
   explicitly reviewed disposable `.hash` sidecar; and publish a fresh,
   append-only evidence record or a durable failure record.

Invoke Phase B only through the guarded runner; repeat `--permitted-axiom` for
the exact per-run subset of `propext`, `Classical.choice`, and `Quot.sound` that
the declaration may use:

```sh
python3 scripts/verify_lean_dependency_pilot.py \
  --pilot-id <pilot-id> --runner-id <runner-id> \
  --project <root-relative-project> \
  --snapshot <root-relative-snapshot> \
  --review <root-relative-review> \
  --declaration <qualified-name> --exact-type <exact-Lean-type> \
  [--permitted-axiom <name>]... [--require-leanchecker] --json
```

There is no weaker isolation, cache reuse, online resolver, or ad hoc direct
`lake` fallback. A passing Phase-B run has exactly the status
`PILOT_VERIFIED_NOT_CERTIFIED`. It says that the recorded declaration was
rebuilt from the recorded dependency bytes under the recorded expanded trusted
boundary. It does not establish informal-to-formal correspondence, upstream
authorship, novelty, or any broader theorem; it cannot satisfy `LR2`–`LR6`,
issue a certificate, or change a dossier/ledger status automatically.

The planning recommendation is to try the smallest target-shaped pilot before
a full dependency campaign, especially where the likely obstacle is assembly
rather than a missing idea. This is a heuristic, not a required research
route. A coordinator may try another bounded target, representation, order, or
method with a recorded rationale and stop condition. That freedom never
relaxes source identity, review, room state, network isolation, exact-type,
axiom, evidence, correspondence, or status-integrity requirements.

For imported work, preserve the original artifact or exact commit, provenance,
and any published agent/formalization prompt. Record compatibility patches as
distinct derived input. Audit the declaration actually built, not a README or
paper claim. A prompt is production provenance, not mathematical authority,
and cannot replace source, build, trust, or correspondence evidence.

## 10. Generated-proof pilot

The recommended first executable v1 vertical pilot is a dependency-free small
theorem with a known independent proof:

- freeze a statement not already present as Lean starter code;
- give the formalizer only the contract and approved libraries;
- record generation and material-repair attempts separately;
- measure time to first compiling candidate and time to `LR5`;
- compare the exact formal type and proof with the known mathematical proof;
- seed at least one negative sibling case with a weakened or vacuous statement
  that compiles, and require `LR4`/`LR5` to reject it.

This pilot measures workflow reliability. It is not evidence that arbitrary
research mathematics can be formalized automatically.

Preserve the fully rendered generator and auditor prompts for both pilots. The
generated-proof pilot must record whether the generator saw starter code,
another proof, or any intended repair; the imported pilot must distinguish the
source author's prompt from the laboratory's independent audit prompt.

## 11. Failure, supersession, and retraction

Failures are durable evidence. Preserve the run and record the first failing
gate, exact error, source digest, and whether the failure is syntactic, build,
trust, correspondence, independence, or scope related.

- A source or contract repair creates a successor case.
- A transient environment failure creates a new run in the same frozen case
  only if no frozen byte or pin changes.
- An audit cannot edit a prior build manifest.
- A certificate cannot be edited after issuance.
- If a certificate is later found unsound or mis-scoped, append a retraction
  record naming it, notify every local artifact that relied on it through the
  ordinary research-state workflow, and reassess those statuses explicitly.
  Never erase the original certificate.

Room shutdown is not a retraction. It stops new work while preserving the
current evidentiary state.

## 12. Rollback

The Lean Room is additive. Architectural rollback consists of disabling the
room, removing its routing and command integration after review, and retaining
all existing cases as read-only historical artifacts. Rollback must not delete
evidence or silently rewrite mathematical status. The one-sentence shutdown is
the immediate operational rollback and is always available.

## 13. Method provenance

The `F0`–`F4` campaign controls operationalize lessons from Guanyang Wang's
[LLMs for Proof Generation and Verification](https://guanyangwang.github.io/blog/llm-ktv-lean.html):
probe a small formalization before scaling, expect assembly and library friction,
expand omitted informal details, interrupt repetitive lemma loops with
independent or directional intervention, and audit correspondence again after
refactoring. This source motivates the workflow; it is not evidence that the
workflow will solve or formalize any particular theorem, and it is not a
prescription that overrides mathematical judgment, alternative research
directions, or a better bounded experiment. Only the claim-integrity and
execution-safety gates identified above are mandatory for the claims they
govern.
