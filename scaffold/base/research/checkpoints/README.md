# Research Checkpoints

Store one append-only checkpoint after every substantive research round. If a
dossier round report, proof attempt, computation, deep-goal outcome, or other
canonical artifact already captures the details, write a compact checkpoint
that links those artifacts rather than duplicating them. Use
`templates/research_checkpoint.json`,
`workflows/durable_research_memory_protocol.md`, and the
`record-research-checkpoint` skill.

Publish with `scripts/research_memory.py record`; the checkpoint ID must match
the direct-child filename `<checkpoint-id>.md`. Never overwrite an earlier
checkpoint. Corrections and supersessions are new records linked to existing
IDs with an explicit revision reason. Link each claim to its exact artifact and
preserve its source status vocabulary. A checkpoint is a durable handoff, not
proof, verification, novelty evidence, or authority for a ledger promotion.

`research/checkpoint_index.json` is a deterministic derived projection bound to
the SHA-256 of every checkpoint. Rebuild and validate it with
`scripts/research_memory.py`; never treat it as a second source of truth.

Small conversational observations do not require checkpoints. Results that
would matter to a future whole-lab survey or stronger-model reactivation do.
