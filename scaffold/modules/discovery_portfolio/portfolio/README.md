# Discovery Portfolio

This directory is lab-owned live state for scouting and qualifying multiple
candidate problems.  It is not a proof container.  Once a candidate enters a
serious trial, link it to an ordinary dossier under `problems/`; keep proof
attempts, sources, computations, and mathematical status there.

Candidate workflow states are `LEAD`, `QUALIFYING`, `TRIAL_ACTIVE`, `PARKED`,
`REJECTED`, `SPINOUT_READY`, and `SPUN_OUT`.  The only cycle decisions are
`CONTINUE`, `PARK`, `REJECT`, and `SPIN_OUT`.  These labels express resource
allocation, never truth, novelty, or proof status.

The parallel engagement tiers are `SCOUT`, `TRIAL`, and `DEEP`.  New
schema-v2 candidates start at `SCOUT`; promotion is locally no-overwrite and
strictly sequential.  The default `12 -> 3 -> 1` funnel is advisory, with every
deviation recorded rather than hidden.  The helper derives pool and prospective
selection counts from the candidate's canonical cohort; supplied counts cannot
override them.  It never changes candidate phase or mathematical status.

Intake records distinguish `USER_SUPPLIED` from `LAB_SCOUTED` leads.
Laboratory-scouted leads require source evidence; intake copies and hash-binds
that evidence under the candidate so exports remain self-contained.

Use `scripts/discovery_portfolio.py` and do not edit event records after they
are appended.  Event publication is atomic and no-clobber.  The first round
freezes the dossier link and creates a pending decision that must be closed
before another round or `DEEP` promotion.  Run
`scripts/validate_discovery_portfolio.py` after every operation.  The complete protocol is in
`workflows/discovery_portfolio_protocol.md`.

Packages are local no-clobber, hash-bound snapshots, not externally
authenticated immutable objects.  Persistent lock files are ordinary runtime
coordination inodes; process exit releases their advisory leases.
