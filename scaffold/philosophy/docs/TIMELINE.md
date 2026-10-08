# Chronology, candidate birth and laboratory epochs

The private immutable archive is the source of chronology. The timeline is a
replaceable view of its events, with no separate canonical log. A candidate may
be an essay, a thesis, an idea, or another artifact. There is no fixed candidate
limit. Any eventual submission count belongs to the laboratory profile.

## What is recorded

- `lab.epoch`: a stable epoch ID, label, predecessor event, reason for change,
  comparability note, and exact archived method, available instructions and
  configuration bytes. Unavailable material is explicitly unknown. These are
  snapshots of material actually available to capture, never an assertion that
  hidden system instructions or a model's internal reasoning were captured.
- `candidate.created`: a stable candidate ID; original artifact SHA-256; AI or
  human origin; run-start event, project stage and selection-round IDs; epoch
  event and exact method/instruction/configuration bindings. Birth observation
  includes its timestamp and source, or an explicit reason it is unknown.
  The archive separately sets `recorded_at` when it commits the event.
- Genesis is `ORIGINAL`, `DERIVED`, `MERGED`, or `IMPORTED`. Derivation requires
  one candidate parent; a merge requires at least two. The archive retains all
  parents and the exact original bytes. A fresh original candidate has no
  declared candidate parents; that does **not** prove intellectual independence.
  Independence begins `UNASSESSED`. A later
  `candidate.independence_assessed` event records a rationale, sourced event and
  object evidence, and `SUPPORTED`, `NOT_SUPPORTED`, or `INCONCLUSIVE` assessment.
  Such an assessment is a review claim, not machine certification.
- `candidate.decision`: explicit rejection, reopening, shortlisting, selection,
  or setting aside, with a reason and selection-round ID. Old candidates and
  decisions remain present. The current status is derived in archive sequence
  order; the birth epoch and original artifact never change.
- `activity.observed`: a stable activity ID, task type, epoch/stage/selection
  context, optional run-start binding and exact evidence events. The model label,
  start and end each have independent known/unknown status and source. A later
  observation of the same activity causally references its previous observation
  and updates the derived view; earlier evidence remains in the archive. Context
  and task identity must stay consistent across these observations. Use distinct
  activity IDs for distinct prompt/run
  intervals, and avoid counting the same interval as both a run and each prompt.

`ORIGINAL` is a lineage declaration, not an independence score. An epoch change
also does not prove that an improvement caused later candidates' success.
Preserve comparability limitations, including changed prompts, selection
criteria, evaluator context and model availability, when interpreting outcomes.

## Time and completeness

Use source-observed timestamps with their actual precision. Do not invent a
second-accurate birth from file modification time, a date-only source, an import
time, or a later archive commit. A source's timestamp is a sourced observation,
not an independent time attestation. Unknown original birth remains unknown;
reports may place its recording in a week, explicitly marked as such.

A complete, observed start/end interval permits a wall-clock duration. It
includes all elapsed time in that interval (potentially queueing, tool calls,
network waits and generation). It does not reveal how long a model internally
reasoned. `internal_reasoning_time` therefore remains explicitly unknown.
Interrupted activities and open intervals have unknown/incomplete duration even
if an observation includes an interruption time. No success or complete capture
is inferred from an absent terminal, a return to the app, or a model label.

## Python API and round linkage

Run helpers with Python 3.9+ and `-B`; only the standard library is required.
`Timeline(archive)` offers `epoch`, `candidate`, `decision`, `assess`, `activity`,
`validate_epoch`, `validate` and `weekly`. Every write takes an explicit context:

```json
{
  "actor": {"id": "session-1", "role": "AI"},
  "session_id": "session-1",
  "run_id": "run-1",
  "operation_id": "round-run-1",
  "attempt_id": "attempt-1"
}
```

An epoch ID `epoch-1` produces event ID `epoch:epoch-1`; a candidate ID
`candidate-1` produces `candidate:candidate-1`. Deterministic event IDs and
archive delivery keys reject identity conflicts and make exact redelivery
idempotent. The archive validates typed timeline transitions under its exclusive
append lock before publishing an event, including calls made directly through
the generic archive API. Competing updates based on the same previous activity
observation cannot both commit: the stale update is rejected. Keep IDs short
enough that prefixed IDs remain within the archive's
200-character bound. Method, instruction and config lists contain the hashes
returned by `archive.put(exact_bytes)`.

The linked `operation.started` must have the epoch event as a parent and these
payload fields: `epoch_event_id`, `stage_id`, `selection_round_id`. Its
method/instruction/config bindings must match that epoch; run input bindings
may differ. Candidate creation must refer to that start and match its run,
operation and attempt, stage, selection round and epoch. Its actor/session may
be the actual participant who created the artifact. A later change of stage or
method uses a new explicitly linked run/epoch rather than silently rewriting
a birth context.

The command line accepts a JSON file containing the corresponding Python
method's keyword arguments, including context and exact object/event bindings:

```sh
python3 -B scripts/research_timeline.py epoch --request epoch-request.json
python3 -B scripts/research_timeline.py candidate --request birth-request.json
python3 -B scripts/research_timeline.py activity --request timing-request.json
python3 -B scripts/research_timeline.py validate
python3 -B scripts/research_timeline.py weekly --timezone UTC
```

The archive must already be initialized. Typed timeline validation is distinct
from byte/hash integrity validation. Untyped historical events remain historical
records; the helper does not silently upgrade them to complete birth provenance.

## Weekly views and eventual presentation

`weekly` writes `research/views/timeline.json` and `timeline.md` outside the
archive. Re-running replaces only those derived files. The JSON includes the
full candidate ancestry and decisions, exact epoch/method objects, model/timing
observations and chronological event references. Markdown presents a readable
weekly table and candidate/model summaries. Weeks begin Monday in an explicit
UTC or fixed-offset timezone such as `-07:00`; fixed offsets do not infer daylight
saving changes. Complete intervals crossing a week boundary are split at that
boundary. Activity counts are assigned to the observed start week, or explicitly
to the recording week when the start is unknown. Duration totals sum observations;
overlapping activities can exceed wall-clock time and are not person-hours.

Task types include infrastructure, planning, idea generation, essay generation,
source reading, critique, selection and methodology. Generic events remain
visible even without such classification. Unknown model labels, unavailable
births, incomplete intervals and uncategorized events remain visible gaps.
These reports reconstruct the recorded work, not an unobserved total schedule.

The final judges' presentation can later use these records for weekly tables,
interactive chronology or an ancestry visualization. This command neither
publishes nor exports a public repository. Any public package remains an
explicit reviewed export, with its own privacy and selection decisions.
