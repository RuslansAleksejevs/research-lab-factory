---
name: qualify-discovery-candidate
description: Qualify or run a bounded trial on an existing discovery candidate, including exact statement, open-status uncertainty, cheap falsifiers, dossier linkage, round record, and an explicit portfolio decision.
---

# Qualify Discovery Candidate

Read `workflows/discovery_portfolio_protocol.md`.  Inspect the candidate's
append-only history before acting.  Move `LEAD -> QUALIFYING` with a completed
decision input; append a qualification record that separates source evidence
from inference; then decide whether to reject, park, or continue.

Before a `TRIAL_ACTIVE` round, create or identify one ordinary problem dossier
and link it with `link-dossier`.  For a schema-v2 candidate, then use
`engagement_decision.json` and `promote-engagement` to record the explicit
`SCOUT -> TRIAL` allocation.  The default funnel observation is `12 -> 3`;
smaller pools within those caps need no explanation, while exceeding either cap
requires a concrete deviation rationale. Put all proof attempts and
mathematical status in the dossier. Append the round with `record-round`, then
append exactly one cycle decision.  The first round permanently freezes the
dossier link.  Until its decision is appended, do not run another round or
promote the candidate to `DEEP`; the CLI enforces both barriers.

Promote `TRIAL -> DEEP` only after at least one substantive trial round and a
new explicit post-round decision selecting one from a pool of at most three (or an
explained cap deviation).
Never jump directly from `SCOUT` to `DEEP`.  Run
`scripts/validate_discovery_portfolio.py` after every command.

After a substantive trial round, also use `record-research-checkpoint` to
publish one dated outcome envelope linking the candidate round and ordinary
dossier artifacts. Portfolio phase and engagement tier remain allocation
metadata and must not be copied into the checkpoint as mathematical truth.

Never infer truth or novelty from a successful model response or from the
portfolio transition.
