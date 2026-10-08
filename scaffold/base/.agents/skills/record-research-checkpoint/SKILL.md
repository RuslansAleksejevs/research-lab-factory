---
name: record-research-checkpoint
description: Record one dated, append-only, machine-recoverable outcome checkpoint after substantive mathematical research, proof, refutation, literature, computation, formalization, or direction-finding work, including negative and blocked outcomes, especially before a pause, branch, parallel-run end, or handoff.
---

# Record Research Checkpoint

1. Read `workflows/durable_research_memory_protocol.md`, the relevant target,
   dossier state, canonical artifacts, and
   `templates/research_checkpoint.json`. Do not reconstruct missing results
   from chat memory when the auditable artifact is unavailable.
2. Prepare one strict input object accepted by
   `schemas/research_checkpoint.schema.json`. `research_date` records when the
   research happened, not when this report is being written; use an explicit
   `{start, end}` range for multi-day work. Keep `recorded_at_utc` separate.
3. Record the exact target and scope, honest round-outcome status, strongest
   outcome and limitations, verification boundary, best continuation, and
   local discovery metadata. Include examples, counterexamples, what worked,
   failed routes with exact reasons, obstructions/reopen conditions, claims,
   and artifacts when applicable. Omit genuinely inapplicable optional
   sections instead of inserting boilerplate or invented negative results.
4. When a dossier round report, proof attempt, deep-goal outcome, computation,
   or source artifact already contains the detail, make this checkpoint a
   compact outcome envelope with exact relative links. Do not create a second
   narrative copy and do not store private chain-of-thought.
5. Choose a unique checkpoint ID and matching direct-child path
   `research/checkpoints/<checkpoint-id>.md`. Publish only through:

   ```text
   python3 -I -B scripts/research_memory.py record \
     --checkpoint-path research/checkpoints/<checkpoint-id>.md \
     --input <input-json-path-or->
   ```

   The helper validates, renders, and no-clobber publishes the canonical
   checkpoint, then atomically rebuilds `research/checkpoint_index.json`. Run
   `python3 -I -B scripts/research_memory.py validate` before handoff and report
   its scope honestly. A stale artifact belonging only to an unrelated older
   checkpoint does not undo a safely saved new result. Report that older defect,
   use recovery search for unaffected records, and block only work that depends
   on the damaged evidence. The active checkpoint and its explicit dependencies
   must still pass their own evidence and round/attempt checks.
6. Never edit or replace an earlier checkpoint. A correction or supersession
   is a new record with local predecessor IDs in `supersedes` and a non-empty
   `revision_reason`, plus the required `revision_binding` that exactly
   hash-binds the finding, its preimage, the changed revision, and every
   predecessor checkpoint. Preserve the original `research_date` of each
   record.
7. Distinguish the checkpoint's outcome status from claim, dossier, source,
   proof-search, and verifier vocabularies. A checkpoint or derived index does
   not promote a ledger, close a dossier, establish novelty, or verify a
   theorem. List any proposed protected reconciliation separately.
8. If the task is strictly read-only or write access is unavailable, return the
   complete schema-valid structured input object and label it `NOT_PERSISTED`
   outside that object in the surrounding response. State that the checkpoint
   and future local index cannot recover it until an authorized coordinator
   publishes it.
