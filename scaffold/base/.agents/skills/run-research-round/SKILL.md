---
name: run-research-round
description: Execute one exact user-approved Control Room research round inside this laboratory, preserving its immutable plan, ordinary evidence and status gates, architecture boundary, append-only checkpoint, and strict structured result.
---

# Run Research Round

1. Read `workflows/research_round_protocol.md`, the immutable
   `research/rounds/<round-id>/approved_plan.json`, and the laboratory's local
   instructions and durable state. The plan's scope and digest are controlling;
   prompt text does not widen them.
2. Confirm that `python3 -I -B scripts/research_round.py status --round-id
   <round-id>` reports the expected active attempt. Do not create or edit the
   approved plan, architecture guard, result, or Control Room projection by
   hand.
3. Work only inside the approved mathematical scope. Select and follow the
   laboratory's normal `LIGHT` or `FULL` orchestration profile, source rules,
   status vocabulary, dossier discipline, and independent-verification gates.
4. Public research reading is authorized for this action, using public-safe
   queries and GET-like source acquisition. Never disclose private or
   unpublished material, consult an external ChatGPT transport, change Git or
   a remote, publish, message people, or perform another external write.
5. Ordinary research state may be created or updated when the local evidence
   gates permit it. Never edit architecture/policy controls, mission or profile
   files, skills, workflows, scripts, schemas, templates, tests, or migration
   state. A ledger or dossier status changes only from its required evidence,
   never because the round was authorized or a model sounds confident.
6. Before the attempt ends, use `record-research-checkpoint` and the fixed
   `scripts/research_memory.py record` helper to create the one new structured,
   append-only checkpoint at the attempt's authorized path and refresh the
   lab-local `research/checkpoint_index.json`. Do this for `COMPLETED`,
   `PARTIAL`, `BLOCKED`, negative, and unresolved outcomes. Bind the checkpoint
   explicitly to the round ID and cite every substantive artifact. Include the
   refreshed index in `changed_paths` when it changed.
7. Return only the strict object defined by
   `schemas/research_round_result.schema.json`: round ID, honest status, concise
   summary, changed relative paths, checkpoint path, blockers, and one next
   step. The deterministic runner, not this agent, verifies the checkpoint,
   compares the architecture guard, persists `result.json`, and publishes the
   bounded Control Room projection.

Never store private chain-of-thought. Preserve exact gaps, failed mechanisms,
counterexamples, source uncertainty, and useful partial results as auditable
artifacts.
