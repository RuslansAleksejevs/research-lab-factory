# Explicit local Codex capture

`capture_codex.py` imports a bounded selection of original visible records from
one explicitly identified local Codex rollout into `research/archive`. It does
not record provider request envelopes, hidden reasoning, or every internal host
event. A filtered import must never be described as a complete provider trace.
The adapter starts no model, API request, background monitor, or other task.

The capture channel was probed against a real current desktop session during
an implementation probe: exact-ID SQLite metadata lookup located one rollout;
original `response_item` records carried user messages, visible assistant
messages, tool calls and tool results. The assistant marker observed there was
`phase: commentary`, and custom tool outputs used a list of text blocks. This is
an observed local format, not a promised stable public API. Tests use separately
identified synthetic data, and the scaffold contains no live session records.

## Selection and authorization

Give both the authorized session identity and the exact expected project root.
With `--source`, only that file is opened. Without it, the explicit `--session-id`
or `--current` option permits one read-only, bound-ID query of
`~/.codex/state_5.sqlite`: `SELECT id, rollout_path, cwd FROM threads WHERE id = ?`.
There is no task listing or session-directory scan. `--current` uses
`CODEX_THREAD_ID`; a subagent therefore selects itself, not its parent. Database
and first-record identities and cwd must match. Archive output must be exactly `TARGET/research/archive` in a target with a
valid philosophy profile and marker. Normally the target is the expected source
project. An explicitly bounded technical demonstration may additionally pass
`--target-lab /absolute/generated/lab --technical-transfer` to transfer selected
original records from the factory session into that exact laboratory. The source
session/cwd checks remain unchanged. Target profile and marker reads reject
symlinks. Article research belongs in its own laboratory; the transfer flag does
not authorize research in the factory or an additional source session.

The source is opened through no-follow directory descriptors, must be a regular
file, and is read only up to its initial size under a configured byte bound.
Parent traversal and symlinks are rejected. Only complete newline-terminated
JSONL records are candidates. A partial final line is withheld and reported.
The exact metadata query reads a live local SQLite database; it does not create
a database export or copy unrelated rows.

Example, with paths and line numbers replaced by the actual reviewed selection:

```sh
python3 -B scripts/capture_codex.py \
  --archive "$PWD/research/archive" \
  --expected-cwd "$PWD" \
  --session-id EXACT_AUTHORIZED_SESSION_ID \
  --source /absolute/path/to/exact-rollout.jsonl \
  --start-line 20 --end-line 23 \
  --reviewed-tool-lines 20,21,22,23 \
  --run-id LOCAL_ROUND_RUN_ID
```

Every tool record body must be reviewed before its exact line is included in
`--reviewed-tool-lines`. By default these bodies are withheld and the capture
is incomplete. Review must check the actual command arguments and returned
text, including any nested tool output. Original tool stdout can contain
sensitive material; schema checks cannot prove its absence. Conservative
runtime-store and hidden-content markers block records even if listed as
reviewed, and a blocked call also blocks its results. This marker check is an
additional safeguard, not a detector for every possible secret or obfuscation.
Never review an unbounded set of lines merely because the tool name looks safe.

## Original records and exclusions

The allowlist admits only structurally recognized `response_item` records:

- User text with `content_item_kinds: ["user.text"]`.
- Assistant text explicitly marked `commentary`, `final`, or `final_answer`.
- Reviewed function/custom tool calls and their reviewed text results.

Record bytes, including whitespace and the terminal newline, are stored without
rewriting. A `capture.raw_record` event links the SHA-256 object, source line,
session identity, basename, source timestamp and tool call ID. The original
record has no range-dependent parent. A separate `capture.tool_link` event
links an observed call/result pair, so later capture can repair a previously
missing pair without modifying originals. The delivery identity is the
session plus source line: an identical retry returns the original event; changed
bytes at that line conflict rather than silently replacing history. Source
absolute paths are absent from capture metadata; original authorized message
or tool text may itself contain a path and retains its original bytes.

System/developer messages, injected user environment/instruction blocks,
reasoning records, encrypted agent messages, session metadata, world state,
turn context, token records and duplicate UI events are excluded. Unknown
fields or record formats fail closed and appear as gaps. Their bodies never
become archive objects. The whole provider rollout is never copied into the
archive or an export.

## Coverage is explicit

A `capture.coverage` event links a machine-readable coverage report and carries:

- `status`: `BOUNDED_COMPLETE` or `INCOMPLETE`.
- `gaps`: missing required visible records, unknown schema, partial/live tail,
  unreviewed or blocked tool bodies, or incomplete selected call/result pairs.
- `exclusions`: reason/count entries for withheld records, including known
  internal surfaces that are outside the capture contract.

`BOUNDED_COMPLETE` means only that the explicitly closed selected line range
has no detected gap in this visible-record contract. An open-ended snapshot
always reports `INCOMPLETE`. Known internal exclusions and intentionally
unselected lines are not missing evidence within a closed selection. Reports
also record snapshot size/hash, complete-line range, partial-tail byte count,
raw-record object hashes, reviewed lines, event IDs and continuing limitations.
Future records and provider-level request envelopes remain outside this
capture even when the selected range is complete.

Use returned `raw_event_ids` as actual capture evidence and
`coverage_event_id` when recording the round checkpoint. The adapter projects
only the model label and effort from the nearest native turn-context record;
the rest of that record is not retained. This is an observed session configuration,
not proof of the actual server model or fallback routing. Missing model labels,
cost and internal thinking duration stay unknown. Native event timestamps and
archive recording timestamps are separate. An incomplete technical demonstration may be checkpointed as incomplete
with a reason; it must not be presented as a complete research round.
