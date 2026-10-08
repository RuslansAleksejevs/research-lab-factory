# Portable research archive format v1

This is a laboratory-owned append-only archive, implemented in Python 3.9+
using only its standard library on POSIX systems with `flock`, `O_NOFOLLOW`,
hard-link publication, and directory `fsync`. It stores supplied bytes and
observable events. It neither obtains hidden reasoning nor claims to capture
every interaction of the host application. Synthetic fixtures are tests, never
research evidence.

## Canonical data and exact bytes

`archive.json` binds format version, a stable origin archive ID, and creation
time. `objects/<sha256>` contains the exact supplied bytes, including whitespace,
encoding, binary data, and line endings. Each filename is its content's SHA-256.
`events/000000000001.json` and following files contain one canonical event each.
The JSON encoding is UTF-8, sorted keys, compact separators, unescaped Unicode,
finite numbers only, and a single trailing LF. Event `sha256` hashes these
canonical bytes after removing only the `sha256` field. `previous_sha256` is
the preceding event's digest, or null for sequence one.

The separate event schema ships in `schemas/archive_event.schema.json`.
The runtime checks both the schema's structural constraints and additional
causal, object-existence, operation-transition and integrity rules without
requiring a JSON Schema library. Event IDs, origin IDs and event bytes survive
export/import unchanged. Content hashes establish byte consistency, not
truth, novelty, authorship, independent verification, or external authenticity.
Deletion of a complete final suffix is detectable only with an independently
retained later event, export manifest, or expected head; the archive cannot
authenticate its own historical completeness against a same-account attacker.

Every event records its kind, event `timestamp` with timezone, separate
archive-write `recorded_at`, actor ID and role,
session, run, operation and attempt IDs, causal `parents`, exact object
`inputs`/`outputs`, and exact method/instruction/config/input version bindings.
An operation is a logical action; its attempts distinguish retries. A run
groups execution; a session groups related interactions. These identifiers
must not be conflated. `bindings` has exactly four arrays: `method`,
`instruction`, `config`, `input`. Each element is an object digest; an empty
array means no version of that class was declared, not proof of complete
capture. Capture adapters must snapshot the applicable bytes before execution
and disclose unavailable sources. `model` and `cost` each carry
`status: known` plus `value`, or `status: unknown` plus a reason. Missing model
or cost observations default to explicit unknown values and are never guessed.
Source-specific fields belong in `payload`; this archive does not scrape
application state or grant permission to capture external/private material.
`timestamp_source: supplied-event-time` means the adapter supplied the event
time (its source should be explained in payload). When absent, event time uses
the archive clock with `timestamp_source: archive-clock-event-time-unknown`;
this is explicitly not a recovered historical event time. `recorded_at` is
always set by the archive at append and is unchanged on idempotent replay.

## Append, concurrency, interruption and recovery

`Archive(root).init()` initializes an empty directory. `put(bytes)` returns a
digest; `get(digest)` verifies and returns its exact bytes. `append(request,
delivery_key)` returns the committed event. The request supplies kind, actor,
session/run/operation/attempt IDs and optional ID, timestamp, origin, parents,
objects, bindings, model, cost and payload. The runtime adds sequence, schema
version, request digest, delivery key and chain hashes. It rejects reserved or
unknown top-level fields. Supplying the same delivery key and exact canonical
request again returns the already committed event. Reusing a key for different
content fails. An event ID cannot be reused. In a scoped import, a key committed
to an omitted event cannot silently create a replacement event.

All cooperating reads and writes use an exclusive `flock` on `.lock`.
Canonical publication writes a uniquely owned temporary file, flushes and
`fsync`s it, sets read-only mode, then hard-links it exclusively to the final
filename and `fsync`s the containing directory. It never replaces a confirmed
file. The temporary name is removed after publication. A crash can leave a
temporary file or an unreferenced object, but cannot silently replace an event
or turn an unfinished operation into success. A link published before an
uncertain return is recovered by retrying the same delivery key. Durability
depends on the filesystem honoring the POSIX operations; a malicious process
with write access is outside the cooperative lock model. Symlinks and special
files are rejected, including existing path ancestors.

`operation.started` reserves an attempt. One matching `operation.completed`,
`operation.failed`, or `operation.interrupted` may close it; the terminal must
name the start in `parents` and retain session/run/operation and exact version
bindings. A completion without a start, a second terminal, or reuse of a
started attempt fails. A start with no terminal remains **unresolved** even
when its process no longer exists. Recovery may append an explicitly justified
interruption and then begin a new attempt; it never synthesizes success.

`validate()` and `recover()` produce read-only reports of damaged JSON/objects,
hash-chain failures, missing parents/objects, duplicate identities/keys,
unexplained sequence gaps, leftover temporary files, unreferenced objects and
unresolved attempts. `ok` means structural integrity, not absence of orphan
objects, temporaries or unfinished work. Damage prevents append/export; those
commands never overwrite corrupt confirmed records. Keep a damaged original
for inspection and recover exact known bytes into a separate archive. There is
no garbage collector, background daemon, silent repair or automatic pruning.

## Evolving candidates and methods

All causal parents must already exist, so history is a DAG. Ordinary kinds
such as `candidate.created` or `method.created` can introduce independent
roots. `candidate.branch`, `candidate.reject`, `candidate.reopen`,
`method.switch`, `correction` and `decision` require at least one causal
parent; `candidate.merge` requires at least two. Record exact new material in
objects and bind it in each event. A correction or rejection appends a new
record referring to earlier work; it never alters or erases it. Reopening
preserves the rejection and its rationale. Method changes preserve the prior
version and bind the new version. These are provenance relationships, not
automatic scientific judgments or a centrally imposed research process.

`view()` derives readable event, attempt and branch JSON; `markdown()` derives
a chronological Markdown view. Both can be rebuilt from canonical records.
Views do not determine research truth or overwrite historical interpretation.

## Portable packages and scoped exports

`export(destination, event_ids=None)` creates a **new directory** bundle;
an existing destination is always rejected. A complete export includes all
events and all objects referenced through inputs, outputs and bindings. A
scoped export includes requested events and their recursive causal parent
closure. Unselected events are explicitly listed in `scope.json` as ID,
sequence, event hash, previous hash and delivery-key-hash commitments; their
bodies are omitted. Related objects needed for included records are always
present. Unreferenced objects, temporary files, derived views and unrelated
objects are explicitly outside the bundle. Review parent closure before
sharing: causal ancestors may contain information beyond the selected leaf.
An export is a local operation and does not upload, publish or contact anyone.

The bundle includes the exact archive identity, scoped metadata, events and
objects, plus `format/archive_event.schema.json`, `format/ARCHIVE_FORMAT.md`,
and the interpreter `format/research_archive.py`. `manifest.json` lists exact
SHA-256 and byte size for every file and is published last as the bundle commit
point. An interrupted bundle without this manifest is not importable.
An export needs no old absolute path or original project to be read.

`Archive.import_bundle(bundle, destination)` checks a strict file/directory
allowlist, all manifest bytes, required interpretation materials, identity,
event semantics, references and chain integrity in owned staging before
touching an empty destination. It rejects symlinks, hard links, special files,
absolute or traversing names, extra/missing files and tampering. The destination
must be absent or empty; existing canonical data is never merged or overwritten.
The archive identity is published last. Interrupted destination publication
leaves an uncommitted directory for explicit inspection. A retry uses another
empty destination; the importer does not delete uncertain outputs.
The imported package manifest is retained as `bundle_manifest.json` and binds
the carried format material for later validation and re-export. Import only
validates data with the current runtime; it never executes a bundled script.

Scoped imports retain explicit sequence omissions and may continue with new
events after the original committed sequence frontier. A missing parent is
never explained away as an omission: parent closure is mandatory. A package
manifest is a consistency check, not a trusted signature; changes made together
with all corresponding hashes cannot be attributed or authenticated by it.

## Command line

Run `python3 scripts/research_archive.py --root archive init`, then use `put
FILE` (or `put -` for stdin), `append --event REQUEST.json --delivery-key KEY`,
`validate`, `recover`, `view --format markdown`, `view --format json`,
`export NEW_DIRECTORY [--event-id ID ...]`, or `import BUNDLE_DIRECTORY`.
The `--root` option selects the archive directory, including the import target.
Return code 1 indicates a failed command/integrity report; errors go to stderr.
Neither CLI nor Python API automatically watches user activity.
