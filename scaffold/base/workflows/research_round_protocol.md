# Control Room Research Round Protocol

This protocol connects a local Laboratory Control Room action to one autonomous
laboratory. The factory dispatches work, but the laboratory remains the sole
owner of its mathematical state. No proposal, scope, model log, or research
body becomes a factory-side research database.

## Three action modes

### `propose-rounds.v1`

This is read-only decision support. Reconstruct durable state with
`survey-laboratory-state`, use `explore-research-directions` when necessary,
and choose exactly one serious next round. Return one to three short sentences
covering its topic, exact objective, principal tasks, and expected value. Do
not save a survey, update a ledger, create a checkpoint, or begin research.

### `run-rounds.v1`

The user's click on the displayed selected laboratories and exact edited scopes
is sufficient authorization for those bounded research-state writes. Before
Codex begins, the deterministic helper must persist the immutable approved plan
and start an append-only attempt with an architecture baseline. The agent then
uses `run-research-round` and every applicable local research and integrity
protocol.

### `collect-rounds.v1`

This is read-only. Read the selected round's bounded
`control_room_status.json`, result, and checkpoint binding, or perform a bounded
local summary when required. Do not conduct new research, reconcile a status,
or modify the laboratory.

## Durable layout

The helper creates this live state only after `run-rounds.v1` is authorized:

```text
research/rounds/<round-id>/
  approved_plan.json
  control_room_status.json
  attempts/<attempt-id>/
    guard_start.json
    result.json
    guard_end.json
```

The plan, attempt guards, results, and checkpoints are append-only. The bounded
projection is derived navigation and may be atomically replaced. Canonical
mathematical evidence remains in dossiers, sources, ledgers, results, reports,
and `research/checkpoints/`.

Round IDs match `^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$`; attempt IDs use the same
alphabet with at most 64 characters. Reusing a round ID with a different
request, laboratory, or scope is a conflict. A retry keeps the immutable plan
and creates a new attempt ID.

## Deterministic helper boundary

`python3 -I -B scripts/research_round.py` exposes only fixed subcommands. Always
retain `-I -B` so project files cannot shadow Python's standard library and no
bytecode is written:

- `python3 -I -B scripts/research_round.py prepare --round-id ID --request-id
  ID`, reading `{"scope":"..."}` from stdin;
- `python3 -I -B scripts/research_round.py begin --round-id ID --attempt-id ID`,
  returning the exact
  `guard_start_sha256` binding retained by the dispatcher;
- `python3 -I -B scripts/research_round.py finalize --round-id ID --attempt-id ID
  --expected-guard-start-sha256 SHA256`, reading the strict result object from
  stdin and refusing a changed guard packet;
- `python3 -I -B scripts/research_round.py cancel --round-id ID
  [--expected-guard-start-sha256 SHA256]`; the digest is
  mandatory for an active attempt and omitted for a queued attempt;
- `python3 -I -B scripts/research_round.py recover --round-id ID`; this is a
  trusted dispatcher-only, write-capable crash transition with no stdin and no
  caller-supplied attempt, guard, result, or checkpoint;
- `python3 -I -B scripts/research_round.py status --round-id ID`;
- `python3 -I -B scripts/research_round.py validate [--round-id ID]`.

There is no command, executable, root, output-path, or arbitrary argv input.
The helper requires the exact `.lab/control_room_actions.json` compatibility
marker, pins the laboratory root identity, rejects duplicate-key or oversized
JSON, and performs no-follow directory-anchored writes.

`prepare` accepts at most 16 KiB of serialized input and a scope of at most
12,000 Unicode scalar values and 12,000 UTF-8 bytes. `finalize` accepts at most
32 KiB of serialized input and canonical normalized result. Summary, next-step,
blocker, and relative-path fields have independent encoded-byte limits. Lone
Unicode surrogates in any JSON key or value are rejected.

Every state transition and consistent status/validation read takes a bounded
lab-global kernel lock on that architecture-owned compatibility marker. The
kernel releases the lock on process exit, so there is no mutable research-side
lock file or stale-owner cleanup. A competing live helper waits at most 15
seconds and then fails visibly.

## State and checkpoint rules

The live dispatcher may show `QUEUED` and `RUNNING`. Durable projections use
only `CHECKPOINTED`, `COMPLETED`, `PARTIAL`, `BLOCKED`, `FAILED`, or
`CANCELLED`. `COMPLETED`, `PARTIAL`, `BLOCKED`, and `CHECKPOINTED` require a new
round-bound checkpoint. A retry is allowed from `FAILED`, `BLOCKED`, or
`CANCELLED` and never overwrites a plan, attempt, result, guard, or checkpoint.
The checkpoint must be a single-link regular file whose device/inode was absent
from the attempt baseline; renaming or hard-linking an old checkpoint does not
satisfy this gate.

The projection schema is closed and its pretty-printed file is at most 32 KiB.
It contains only identity, status, a concise summary, bounded changed paths,
checkpoint binding, blockers, next step, and a digest calculated without the
mutable generation timestamp or digest field and bound to the SHA-256 of the
exact canonical approved-plan bytes. It is navigation, not proof or authority
for a status promotion.

Registered round work may also create bounded local records under
`runs/reports/`, `runs/traces/`, and `runs/interaction_cards/`. Other `runs/`
namespaces—including saved surveys, stewardship transactions, and external-LLM
runs—remain outside this action. Lab-root `tmp/` is also outside the durable
allowlist; use the operating system's temporary directory for disposable build
scratch and copy only an auditable final artifact into an allowed research
location.

## Architecture and integrity guard

Normal research writes include dossiers, attempts, sources, calculations,
formalization state, papers and research reports, talks, decisions, results,
checkpoints, and evidence-gated research ledgers. Architecture/policy controls,
the laboratory mission, factory/migration state, Git, and external transports
remain outside the authorization.

Before each attempt the deterministic helper inventories every path outside
the explicit research-state allowlist by type, mode, size, and SHA-256, and
also inventories all pre-existing checkpoints. Finalization fails visibly if
the root, immutable plan, protected inventory, or any old checkpoint changed.
The model's changed-path list is untrusted until this comparison passes.

Finder may create an exact `.DS_Store` metadata file while a laboratory is
being viewed. That basename is excluded at any depth only after no-follow
validation proves a same-device, single-link regular file with stable identity.
The exclusion is not a wildcard and does not prune a subtree: `.DS_Store.keep`,
a directory or symlink named `.DS_Store`, a FIFO or other special file, a
hardlink, and a cross-device entry remain visible and fail closed.

The begin/finalize digest handoff prevents the writable agent from silently
replacing and rehashing its own starting guard. The server-owned Codex
permission profile keeps the laboratory read-only by default and grants only
the reviewed research-state allowlist; the browser, registry request, and model
cannot expand it. The independent hash guard remains fail-visible defense in
depth. Drift is never reported as success: retain the guard report, stop, and
reconcile from known preimages or version history without an automatic rollback
that could overwrite concurrent human work.

Guard policy v2 records filesystem identity for regular-file inventory entries,
requires canonical 0444 plan/guard/result artifacts, binds the exact reported
result into `guard_end.json`, and validates the terminal sequence and derived
0644 projection before either `status` or `validate` may surface it. A queued
cancel projection is likewise compared with one exact deterministic result.

`recover` is idempotent and derives repairs only from those canonical immutable
records while the same transition lock is held. It may recreate a result already
bound inside `guard_end`, remove a digest-bound stale retryable projection,
canonically close one unambiguous active attempt as `CANCELLED`, or republish the
latest terminal projection. Multiple active attempts, non-contiguous terminal
sequences, an unbound projection, or any other ambiguous/tampered chain fail
before a repair is attempted. Passive `status`, collection, and HTTP GET never
invoke this mutating transition.

## Network and external systems

`run-rounds.v1` permits public literature search, public-safe GET requests, and
downloads of open research sources under the local source policy. It does not
permit private disclosure, external ChatGPT or another model transport,
GitHub/remotes/push/PR, publishing, messaging, or any external write. Proposal
and collection modes do not enable network access merely because the runner is
capable of it.
