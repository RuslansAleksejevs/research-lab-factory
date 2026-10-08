# Research Checkpoint — Rendered-Artifact Reference

Do not copy or fill this Markdown file by hand. The canonical checkpoint is a
deterministic readable rendering of the strict structured input in
`templates/research_checkpoint.json`.

Publish one checkpoint with:

```text
python3 -I -B scripts/research_memory.py record \
  --checkpoint-path research/checkpoints/<checkpoint-id>.md \
  --input <input-json-path-or->
```

The generated Markdown contains exactly one embedded
`research-checkpoint-record:v1` JSON envelope and readable sections for:

- checkpoint identity, exact research date or date range, recording time, and
  optional round/run/track/problem/claim links;
- exact target and scope;
- round outcome status, strongest result, actual generality, and what remains
  unproved or unaudited;
- verification state, evidence boundary, independence, and limitations;
- optional semantic dependency changes, examples, counterexamples, worked
  items, failed routes, obstructions, claims, artifacts, and useful residue;
- the next discriminating action, cheapest falsifier, success criterion, stop
  condition, and optional reopen condition;
- local discovery terms and future capability requirements.

Inapplicable optional sections are omitted. Relevant negative results and
gaps must not be omitted, and missing information must not be invented. When
another canonical artifact already contains the detail, use a compact exact
pointer rather than duplicating its narrative.

Checkpoint files are append-only. Corrections and supersessions use a new
checkpoint ID, link the prior IDs in `supersedes`, and include a non-empty
`revision_reason`. They also include `revision_binding`: exact hash-bound files
for the finding, preserved preimage, correcting revision, plus the exact hashes
of every predecessor checkpoint. The helper rechecks all named bytes and
rebuilds `research/checkpoint_index.json`; that index is derived navigation and
never mathematical evidence.
