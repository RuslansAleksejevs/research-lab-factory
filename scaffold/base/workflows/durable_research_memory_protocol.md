# Durable Research Memory Protocol

## Purpose

Every substantive research round leaves one compact, dated, machine-recoverable
outcome envelope. A future agent should be able to locate the record, identify
the exact target and reliable outcome, recover useful positive and negative
work, understand the remaining obstruction, follow the evidence, and begin the
best continuation without reconstructing the original chat.

This protocol extends the existing append-only research checkpoint. Detailed
proofs, attempts, computations, sources, search-round reports, and verifier
artifacts remain canonical in their existing locations. The checkpoint links
them; it does not copy them into a competing ledger.

## When to record

Create one checkpoint:

- after a substantive local or parallel research round;
- before pausing, closing, branching, or handing off substantive work;
- when a decisive proof candidate, refutation, counterexample, error, exact
  obstruction, partial result, inconclusive result, or abandonment decision is
  reached.

Do not create a separate permanent record for every prompt, tool call, agent
message, or minor observation. If several actions form one coherent research
episode, summarize their meaningful outcome in one checkpoint. If work spans
several calendar days, use an explicit research-date range or separate it into
honest dated rounds.

## Record contract

Use `templates/research_checkpoint.json` as input to
`scripts/research_memory.py record`. The helper validates the closed structured
record, embeds it in deterministic readable Markdown, publishes the checkpoint
without overwrite, and rebuilds the lab-local index.

`schemas/research_checkpoint.schema.json` defines the closed portable shape.
The helper remains authoritative for semantic and canonical constraints that
plain JSON Schema cannot fully express, including real calendar dates,
date-range ordering, normalized paths, history-link validity, and exact
rendering. Do not call an object publishable merely because a generic schema
validator accepts its shape.

The core record always identifies:

- a stable checkpoint ID and exact research date or date range;
- a separate UTC recording time and optional round/run/track/problem links;
- the exact question and assumptions/scope;
- one outcome status: `PROVED`, `REFUTED`, `PARTIAL`, `BLOCKED`,
  `INCONCLUSIVE`, `ABANDONED`, or `SUPERSEDED`;
- the strongest honest outcome and its limitations;
- what was verified, by what boundary, and what remains unchecked;
- the best continuation or an exact reason that none remains;
- discovery terms sufficient for local search and later reactivation.

Include applicable examples, counterexamples, successful mechanisms, failed
routes and exact failure reasons, obstructions, claim/source statuses, artifact
paths, future capability requirements, falsifiers, success criteria, and stop
conditions. Optional means semantically inapplicable content may be absent; it
does not mean relevant failures or gaps may be hidden. Never invent a failure,
verification, source check, or obstruction to make a record look complete.

Store auditable output and concise decision rationale, never private
chain-of-thought. Use portable laboratory-relative paths only.

## Status separation

The checkpoint outcome status classifies what this round produced. It is not a
universal truth vocabulary. Preserve every referenced claim's native dossier,
ledger, source, proof-search, formalization, and verifier status with its exact
artifact. In particular, `PROVED` means that the round reports a proof artifact;
it does not bypass the laboratory's independent-verification or promotion gate.

Control Room states (`COMPLETED`, `PARTIAL`, `BLOCKED`, `FAILED`, and related
operational values) describe attempt execution and remain separate.

## Immutability, corrections, and dates

Checkpoint files are append-only. Never edit an old record, including its
research date. Correct or supersede it with a new checkpoint that identifies
the local predecessors in `supersedes`, gives a `revision_reason`, and explains
the changed conclusion. Its required `revision_binding` preserves and verifies
the exact reviewer/finding evidence, old preimage, correcting revision, and the
SHA-256 of every superseded checkpoint. Those three artifact paths must remain
separate regular files, and the revised bytes must differ from the preimage.
The derived index retains the complete history.
`SUPERSEDED` is valid only on such a linked, reasoned record; a correction that
also reports a new proof, refutation, or partial result may instead keep that
more informative outcome status while still carrying `supersedes`.

Supersession also requires the predecessor's bound evidence to remain intact.
If historical bytes are missing or changed, restore the exact originally bound
version from a known preserved copy, keeping the current or damaged bytes as
evidence before restoration. Updating an old checkpoint or its hashes is not a
repair. If exact restoration is impossible, the current protocol cannot publish
that correction: save its unpublished input and recovery findings beside the
existing attempt evidence, and state `NOT_PERSISTED` and the verification gap
at handoff. Do not remove required `supersedes` or `related_checkpoints` links
to bypass the failure. Unaffected independent research can continue, and its
checkpoints can be recorded when the structural store and their own dependency
checks pass. No successful whole-memory validation is implied.

`research_date` is the local calendar date on which the recorded research was
performed. `recorded_at_utc` is the later act of writing the record. They may
differ legitimately.

## Local index and search

`research/checkpoint_index.json` is a deterministic projection. It contains
bounded discovery fields and binds every canonical checkpoint path and SHA-256.
It is lab-owned navigation, not authority. Validate it with:

```text
python3 -I -B scripts/research_memory.py validate
```

Rebuild an absent or stale projection from canonical records with:

```text
python3 -I -B scripts/research_memory.py rebuild-index
```

Query locally with `scripts/research_memory.py search`. Repeatable
`--obstruction`, `--future-capability`, and `--reopen-trigger` facets perform
case-insensitive exact matching against the corresponding complete normalized
values. A search result is a lead to the bound checkpoint and referenced
evidence, not proof that the recorded status is correct or current.

Search remains usable if only the saved index is missing, stale, malformed or
formatted differently. It derives results from validated canonical checkpoints,
returns a warning with `index_status: REBUILT_IN_MEMORY`, and changes no files.
Use `rebuild-index` to repair the disposable cache without repeating research.

If an individual checkpoint is malformed or its bound evidence is missing or
changed, search returns the unaffected records with
`index_status: PARTIAL_RECOVERY`. Warnings name every omitted checkpoint and the
reason, including records whose explicit history links depend on it. These
results are incomplete: omitted evidence is never silently accepted. Search
does not repair, delete or rewrite checkpoints, evidence or the saved index.
An ordinary `.DS_Store` is ignored; symlinks, special files, resource limits and
locking failures remain errors.

If strict `validate` reports only a field such as `artifacts[0]`, use `search`
warnings to locate the affected checkpoint and inspect its linked evidence.
A failed validation is not necessarily an index defect: rebuilding navigation
cannot restore missing evidence or correct changed bytes. Keep the failure and
the incomplete recovery status visible rather than repeatedly rebuilding.

Recording new work checks its evidence and the full explicit
`related_checkpoints`/`supersedes` dependency chain. Missing or changed evidence
in an unrelated older record produces a warning and does not prevent saving the
new checkpoint. The complete structural index retains every canonical record;
`rebuild-index` restores that complete navigation even when old evidence needs
review. Neither action certifies all historical evidence. Malformed canonical
records, ambiguous identities and invalid history links still prevent recording
or rebuilding, while read-only search can recover unaffected entries.

`validate` remains the strict whole-memory diagnostic. Control Room completion
requires the exact complete saved index, the authorized checkpoint's exact
round/run bindings, and unchanged bound evidence for that checkpoint and its
explicit dependency chain. An unrelated stale artifact does not certify or
invalidate the current round; a stale target or dependency still blocks success.

Exact-match reactivation fields (`future_capabilities`, `reopen_triggers`, and
obstruction descriptions) retain their complete normalized bounded strings in
the index; they are not summary-truncated or whitespace-collapsed. Human
orientation fields such as target and outcome remain explicitly labeled
summaries.

Checkpoint publication and index replacement use the reserved direct-child
names `.research-memory-<32 lowercase hex>` and
`.checkpoint-index-<32 lowercase hex>`. `validate` and `search` are strictly
read-only and fail visibly if an exact interrupted publication remains.
`record` and `rebuild-index`, under the exclusive memory lock, preflight every
residue before writing: they remove safe pre-commit/index staging files or
finish the exact canonical checkpoint hardlink commit. Malformed, ambiguous,
linked-outside, or reserved-prefix near-match state fails without deletion.
The destination hardlink is the append-only commit point and is never removed
because a later durability, staging-cleanup, verification, or index step
failed.

## Reactivation

When a materially stronger model, formal method, computation, source, or new
idea becomes available:

1. search for `PARTIAL`, `BLOCKED`, `INCONCLUSIVE`, and promising `ABANDONED`
   records;
2. compare the new capability with the exact recorded obstruction, missing
   dependency, and reopen condition;
3. inspect the bound canonical checkpoint and evidence;
4. obtain ordinary authorization for a new research round;
5. create a new dated checkpoint linked through `related_checkpoints` or
   `supersedes`, as appropriate;
6. record exactly what the new capability changed.

Cross-laboratory selection is ephemeral and explicitly scoped. The factory may
coordinate read-only lab-local proposals, but it never imports or persists the
detailed local index.

## Sufficiency test

Before handoff, ask whether a capable agent without the original chat can
answer: what was targeted, when the work occurred, what is reliably known,
which examples and counterexamples matter, what was attempted, what failed and
why, what exactly remains blocked, which artifacts are reusable, and what the
best continuation is. If not, the checkpoint is incomplete even when its JSON
shape validates.
