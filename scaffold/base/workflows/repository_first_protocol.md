# Repository-first research protocol

This base-installed policy is dormant unless the portable profile contains the
following exact enabled contract:

```json
{
  "repository_first": {
    "enabled": true,
    "canonical_repository_visibility": "PRIVATE",
    "raw_material_policy": "LOCAL_UNTRACKED",
    "export_policy": "REVIEWED_ONLY",
    "process_steward": "<human owner or team steward>"
  }
}
```

It works in a solo laboratory and with `team_collaboration`; it is not an
optional module and it never starts work. The process steward owns workflow
coordination only. `human_owned` appears only in campaign governance and never
certifies correctness, novelty, significance, verification, comprehension,
formalization, or release readiness.

## Canonical boundary

The repository is the private, local coordination surface. Mathematical truth
still lives in the existing claim dossier, source records, evidence artifacts,
and ledgers under their ordinary promotion rules. Repository-first JSON packets
are append-only provenance and navigation next to one dossier:

```text
problems/{active,backlog,closed}/<problem-id>/repository_first/
  prompts/                         # lab-authored action prompts only
  feedback_imports/                # user-provided local expert material
  records/<record-type>/<id>.json  # no-clobber workflow/provenance packets
```

There is no second claim-status or truth ledger. A campaign phase, run outcome,
assessment axis, source relation, expert recommendation, export review, or
effectiveness count cannot promote a claim. Existing dossier and ledger gates
remain controlling.

## Campaigns, phases, roles, and failures

A campaign freezes its target claim IDs, objective, stop conditions, roles,
and human governance. Phase changes form one sequence through
`BREADTH_SEARCH`, `MECHANISM_DEVELOPMENT`, `CONSOLIDATION`,
`ADVERSARIAL_VALIDATION`, `HUMAN_REDERIVATION`, `FORMALIZATION`, and
`EXPOSITION`, with `PAUSED` and `CLOSED` available. Every transition records
input artifacts, active roles, a bounded or honestly unknown budget, an exit
condition, reason, and an existing Durable Research Memory checkpoint.

A retry after failure must cite a compressed failure family and record a
changed search policy. Repeating the same search under a new label is invalid.
Each failure family preserves every member run pointer, an exact failure
reason, evidence paths, reactivation conditions, and the aggregate actual
denominator. Where member counts are known, their sums must match; an unknown
member counter remains unknown in the aggregate. The required denominator
notes separately preserve what is known or unknown about the vector, model,
and harness.

An adjacent result always receives a new claim ID, explicit parent lineage, a
statement artifact, `NEW_UNVERIFIED_CLAIM`, and a checkpoint. It is then
handled by the ordinary dossier and claim-status rules.

## Three-layer run memory

Every substantive raw run uses exactly this memory chain:

1. A `raw_run_manifest` binds the local raw archive, lab-authored action-prompt
   hashes, exact-or-honestly-unknown model and harness versions, effort,
   planned inference budget, actual token/time/tool/model/harness denominator,
   tool-command manifests, output artifacts, and verification boundary.
2. The manifest binds the exact checkpoint ID and SHA-256. The target must be
   the strict canonical Durable Research Memory envelope, its filename and
   embedded ID must agree, and its `run_id`, sole `problem_ids` entry, and
   `claim_ids` must exactly match the raw run.
3. The manifest binds a regular anchor file by path and SHA-256 inside the exact
   claim dossier. The checkpoint and anchor return to that dossier, where the
   detailed mathematical state remains canonical.

Raw bytes live only under
`research/raw_runs/archive/<problem-id>/...`, which is ignored by default. A
manifest may retain only `HASH_ONLY_PRUNED` provenance after local pruning.
Neither raw material nor a repository-first record may use `.git/`, a symlink,
credentials, hidden prompts, developer/system prompts, or private
chain-of-thought. A “significant prompt” means only a laboratory-authored
action prompt deliberately saved under the dossier `prompts/` directory.

## Independent assessment axes

`claim_assessment` records seven separate vocabularies and evidence bases:

- correctness;
- novelty;
- significance;
- independent verification;
- human re-derivation and comprehension;
- formalization coverage;
- release readiness.

The axis name is repeated inside every row and must match its container. There
is no overall status. A passing correctness check says nothing by itself about
novelty or significance; formal coverage says only what was encoded; release
readiness ends at `READY_FOR_HUMAN_DECISION`. Independent-verification `PASS`
requires a declared independent-verifier role and a real evidence file. Every
named assessor must have a different `actor_id` from every campaign
`CLAIM_GENERATOR` or `FORMALIZER`. Reusing an actor under another role, class or
capitalization does not establish independence. Use one stable actor ID for each
person or agent context; record self-checks without independent `PASS`.

This detects declared conflicts, not hidden aliases or context leakage. Different
IDs do not prove independent reasoning. The ordinary proof/I3 gates remain
required before a claim is promoted. Human re-derivation `PASS` requires a
declared human role.

## Sources and verification coverage

`source_use` binds the preserved original SHA-256, bibliographic identity and
version, exact claim statement and hypotheses, page/theorem-style anchors, and
source/claim scopes. Its structured interface search records source-side
hypotheses, outputs, invariants, representations, known bottlenecks, and exact
candidate bridge obligations. Empty invariant, bottleneck, or bridge lists are
honest; hypotheses, outputs, and representations must be explicit. Relations
distinguish `EQUIVALENT`, `SPECIALIZATION`,
`GENERALIZATION`, `STRENGTHENING`, `IMPLIES`, `ANALOGY`,
`LANGUAGE_TRANSLATION`, `NAVIGATION_CITATION`, `PRIMARY_SOURCE`, and
`UNRESOLVED`. Exact logical relations require a relation-matching audit of
hypothesis and conclusion deltas. Language translation additionally requires a
translation map and cannot masquerade as strengthening. Changing a narrower
relation to a broader one requires a new matching audit; editing the label is
invalid.

`verification_coverage` is a matrix of informal obligations and actual
coverage. It separately records formal theorem scope and correspondence,
tool/library versions, declared/imported/unknown axioms, external certificate
scope and hashes, and a replay manifest with bound inputs and outputs. A
successful replay or formal build covers only the recorded scope.

## Reviewed disclosure, release materialization, and expert feedback

First run `prepare-export` on a file selection. It fills SHA-256 and byte counts
for **every** selected file, updates statement hashes, and returns a version-2
request with review `PENDING`. Review that exact selection and its claim-version
labels, then record `REVIEWED`, reviewer, review time and intended manifest
creation time. Existing user authorization can cover this review; do not ask
again merely to confirm hashes. Repreparing always clears the previous approval.
Legacy version-1 selections can be prepared, but cannot be built as reviewed.

`build-export` checks those pre-recorded hashes and sizes; drift blocks only the
export and needs a fresh review of the changed version. It creates a local,
hash-bound, read-only, no-clobber manifest at
`research/repository_first/exports/<export-id>/manifest.json`. Its input must
already say `REVIEWED`; raw archives, credentials, hidden prompts,
chain-of-thought, and outbound actions are excluded. The helper does not copy,
send, publish, push, message, open a network connection, or invoke Git.

That reviewed export is the disclosure-selection layer. It records which exact
lab-local versions a human has allowed into one audience-scoped view, but it is
not yet a standalone file package. Research Artifact Release v1 adds a separate
materialization layer: `scripts/research_release.py` consumes a closed release
request whose source paths and SHA-256 digests are already present in the exact
reviewed export. The release request, reviewed-export manifest and package remain version `1`;
the prepared export request is version `2`. Versions must be exact JSON integers, not a boolean or floating-point lookalike. The
helper creates one deterministic, mode-`0444`, no-clobber ZIP at
`research/repository_first/releases/<release-id>/<release-version>.zip` and can
later validate that ZIP's closed manifest, every archived member, and the
current exact reviewed-export/source bindings. Later source or export drift is
reported; the validator never silently blesses a stale projection.

The two output identifiers are deliberately portable and structurally
distinct. `release-id` is 1–96 lowercase ASCII characters, begins and ends in
an alphanumeric character, and may contain `.`, `_`, and `-` internally.
`release-version` has the same bound but does not permit `-`; this keeps the
single internal root name unambiguous. Windows reserved device names are not
valid identifiers.

Each reviewed source maps one-to-one to a requested package path and one role
from the closed vocabulary: `MANUSCRIPT_SOURCE`, `COMPILED_MANUSCRIPT`,
`CLAIM_STATEMENT`, `CLAIM_MAP`, `CHECKPOINT`, `VERIFICATION_REPORT`,
`SOURCE_RECORD`, `BIBLIOGRAPHY`, `REPRODUCIBILITY_GUIDE`, `ENVIRONMENT_LOCK`,
`SOURCE_CODE`, `COMPUTATION_INPUT`, `COMPUTATION_OUTPUT`,
`FORMALIZATION_SOURCE`, `FORMALIZATION_ARTIFACT`, `CONTRIBUTION_RECORD`, or
`REVISION_HISTORY`. The closed component declarations cover
`MANUSCRIPT`, `CLAIMS`, `VERIFICATION`, `SOURCES`, `REPRODUCIBILITY`, `CODE`,
`COMPUTATIONS`, `FORMALIZATION`, `CONTRIBUTIONS`, and `REVISIONS`; every
component is `INCLUDED` with its member paths, `OMITTED_REVIEWED` with the human
omission rationale, or honestly `NOT_APPLICABLE` with a rationale. Every
release retains an exact claim statement and checkpoint; a `PUBLIC` release
additionally retains both the reviewed manuscript source and already compiled
manuscript bytes. The builder does not create those bytes. Roles and components
organize the package and do not certify its content. The audience labels
`PRIVATE_REVIEW`, `COAUTHOR`, `SHAREABLE`, and `PUBLIC` express the completed
human review decision only. They are not authentication, encryption,
authorization, hosting, or evidence that disclosure or publication occurred.

The ZIP has exactly one canonical top-level prefix,
`research-artifact-release-<release_id>-<release_version>/`. Inside it are
generated `README.md` navigation, the closed machine-readable `manifest.json`,
and the exact requested member paths; `archive_contract.root_prefix` repeats
that exact prefix. The two generated names are reserved and cannot be replaced
by a requested member or used as an ancestor. Requested package paths are
NFC-normalized relative POSIX paths of at most 512 UTF-8 bytes; every component
is at most 255 UTF-8 bytes and excludes empty, dot, dot-dot, Windows-invalid,
trailing-dot/space, device-name, and `.git` components. Two requested paths may
not be equal or stand in an ancestor/descendant relationship. Whole-path
NFKC-then-casefold-then-NFC portable identity closes case and Unicode-
compatibility variants of these topology conflicts. A fully prefixed member name is bounded
independently at 1024 UTF-8 bytes. Members are sorted,
stored without compression, use the fixed `1980-01-01T00:00:00Z` ZIP timestamp,
and carry regular-file mode `0444`;
the outer ZIP is also mode `0444`.
The helper reads the release request with a 4 MiB bound,
`LAB_PROFILE.json` and the reviewed export manifest with a 512 KiB bound, and
`.gitignore` with a 256 KiB bound. The bounded v1 package accepts at most 256
reviewed files, 128 MiB per member, 512 MiB of reviewed payload bytes in total,
and a 640 MiB ZIP; each generated manifest and navigation file is bounded at 8
MiB.

The release ZIP is a derived immutable projection, not a truth store. The
private laboratory, ordinary dossiers, sources, checkpoints, ledgers, and the
reviewed export remain canonical. A structurally complete and hash-valid ZIP
does not prove correctness, novelty, significance, source accuracy, authorship,
human understanding, reproducibility, or release readiness, and it cannot
promote any claim.

The materializer only reads declared single-link regular files and writes the
local ZIP. It never compiles a manuscript, executes code or replay instructions, invokes
Git or GitHub, accesses a network, creates a site, publishes, uploads, messages,
or changes canonical research state. Raw-run archives, credentials, hidden or
system/developer prompts, private chain-of-thought, factory-private context,
`.git`, symlinks, hard links, special files, unreviewed material, and path/hash
drift are rejected rather than packaged.

This mechanical privacy guard is path/basename based and bound to the reviewed
export's explicit exclusions. It rejects the closed known secret and hidden-
prompt classes; it does not content-scan an innocuously named file or infer
that such contents are safe. Human disclosure review remains the controlling
gate.

An `expert_feedback_plan` binds the exact reviewed manifest SHA-256 and each
planned claim's exact statement version, dossier path, and SHA-256. The claim
bindings must already occur verbatim in that same reviewed export. The export
review, export construction, plan construction, plan review, and imported
response time must form one nondecreasing timeline. The plan also records the human trigger,
the reviewed disclosure scope, and a declared human follow-up owner, while
remaining `LOCAL_ONLY_NOT_SENT`. Any actual outreach requires a separate
explicit action outside this helper.

An `expert_feedback_response` can only import material the user has already
supplied locally. Every finding has a unique ID and repeats an exact planned
claim preimage; a response cannot introduce another claim or another statement
version. Recommendations are `NO_CHANGE`, `RECHECK`, `CHALLENGE`, or `SUPPORT`,
and `automatic_claim_promotion` must remain false.

If a finding changes the research state, do not edit either append-only packet
and do not create a repository-first truth ledger. The follow-up owner creates
a new canonical Durable Research Memory checkpoint that `supersedes` the prior
checkpoint and supplies `revision_reason` plus the required exact
`revision_binding`. That binding must include
the exact feedback-response record/finding evidence and every corrected claim,
proof, computation, or source artifact preimage/postimage needed to audit the
revision. Ordinary claim-status and verification gates remain controlling.

## Passive effectiveness observation

`observe` is an explicit one-shot local read of ordinary repository-first
records. It writes bounded counts and hash bindings for future new-lab soak
review. It has no telemetry, timer, background process, fleet discovery, other
laboratory access, network use, or claim-content inference. Counts are workflow
observations, not evidence of mathematical truth or causal effectiveness.

## Helper commands

Always run the isolated standard-library helper from the laboratory root:

```bash
python3 -I -B scripts/repository_first.py validate --json
python3 -I -B scripts/repository_first.py record \
  --input tmp/repository-first-record.json \
  --output problems/active/<problem-id>/repository_first/records/<type>/<id>.json
python3 -I -B scripts/repository_first.py prepare-export \
  --input tmp/repository-first-selection.json --output tmp/repository-first-export-request.json
# Review the prepared selection before building.
python3 -I -B scripts/repository_first.py build-export \
  --input tmp/repository-first-export-request.json
python3 -I -B scripts/research_release.py build \
  --input tmp/research-release-request.json
python3 -I -B scripts/research_release.py validate \
  --archive research/repository_first/releases/<release-id>/<release-version>.zip \
  --json
python3 -I -B scripts/repository_first.py observe \
  --observation-id <id> --recorded-at-utc <YYYY-MM-DDTHH:MM:SSZ> \
  --period-start <YYYY-MM-DD> --period-end <YYYY-MM-DD>
```

The corresponding release shortcuts are:

```bash
make research-release-build \
  RESEARCH_RELEASE_REQUEST=tmp/research-release-request.json
make research-release-validate
make research-release-validate \
  RESEARCH_RELEASE_ARCHIVE=research/repository_first/releases/<release-id>/<release-version>.zip
make research-release-test
```

`build` prints a sorted-key JSON receipt with the canonical lab-relative
`archive_path` and exact ZIP `archive_sha256`. `validate --json` scans every
canonical release ZIP; add `--archive <canonical-release-zip>` to check exactly
one. Its aggregate report keeps `schema_version`, `policy`, `status`,
`releases_validated`, `files_validated`, and `bytes_validated`, and adds an
ordered `archives` array whose entries contain `archive_path`,
`archive_sha256`, `files_validated`, and `bytes_validated`. Plain validation
prints the stable path/digest lines after its summary. Disabled validation
returns `archives: []` without scanning release state.

All writes are atomic, append-only, and no-clobber. Corrections are new records.
If the policy is absent or disabled, `validate` reports `DISABLED` without
scanning repository-first state and every write command fails closed.
