# Discovery Portfolio Protocol

## Boundary

The portfolio scouts, qualifies, schedules, parks, and spins out candidates.
It never treats model output, a team decision, a transfer, or a spin-out as
evidence that a theorem is true, open, novel, or proved.  Serious mathematical
work belongs in the linked problem dossier and follows the laboratory's proof,
source, computation, and verification gates.

Candidate phase and engagement tier are separate:

- phase (`LEAD`, `QUALIFYING`, `TRIAL_ACTIVE`, and so on) records workflow
  state;
- engagement (`SCOUT`, `TRIAL`, `DEEP`) records approved compute allocation.

Neither is a mathematical status.  Raising an engagement tier never promotes
truth, openness, novelty, or proof.

## Lead origin

New intake records use candidate schema v2 and declare exactly one origin:

- `USER_SUPPLIED` may have no source artifact;
- `LAB_SCOUTED` must cite at least one safe root-relative source artifact.

Intake copies each cited artifact byte-for-byte into the candidate's
`origin_evidence/` directory and binds the copy by size and SHA-256.  The
candidate-local copy, not the temporary inbox path, is canonical, so transfers
and imports preserve non-dangling origin evidence.  An optional safe
`cohort_id` groups candidates for one allocation decision without implying
that their statements or quality are comparable.  Intake also binds the exact
source paths, sizes, and digests so a retry cannot silently reuse the candidate
ID with different evidence.

Existing candidate schema v1 records remain valid and are exposed as
`USER_SUPPLIED` / `SCOUT` only as a compatibility view.  Their bytes and event
history are not rewritten or reinterpreted.

## Lifecycle

1. Intake a bounded `LEAD` from a completed copy of `candidate_intake.json`.
2. Record `CONTINUE -> QUALIFYING`, then append a qualification assessment with
   exact statement, open-status uncertainty, cheap falsifiers, significance,
   tractability, and verification plan.
3. Record `CONTINUE -> TRIAL_ACTIVE`, link one existing problem dossier, then
   explicitly promote engagement `SCOUT -> TRIAL` before recording a
   substantive round for a schema v2 candidate.
4. Append each round and then an explicit `CONTINUE`, `PARK`, `REJECT`, or
   `SPIN_OUT` decision.  The round sets `pending_round_decision`; while it is
   set, both another round and `TRIAL -> DEEP` fail.  The dossier link is frozen
   by the first round and cannot later be redirected.  Never rewrite an earlier
   record; append a later record that explains the correction.
5. `PARK` records the exact barrier, intended resume state, and one or more
   discriminating triggers.  A `MODEL_CAPABILITY_CHANGE` trigger must name its
   baseline, condition, and evidence requirement.  Resume only by citing one
   recorded trigger plus concrete evidence.
6. `SPIN_OUT` first moves a tried candidate to `SPINOUT_READY`.  Prepare a seed
   locally; then separately ask the factory to create and validate a sibling
   lab.  Only a copied local success receipt permits the final transition to
   `SPUN_OUT`.  The original candidate and dossier remain intact.

## Advisory 12 -> 3 -> 1 funnel

The default allocation funnel is:

1. scout up to twelve bounded leads cheaply;
2. explicitly select up to three for `TRIAL`;
3. after at least one substantive trial round, explicitly select one for
   `DEEP`.

Use `engagement_decision.json` with:

```bash
python3 scripts/discovery_portfolio.py promote-engagement \
  --candidate-id <id> --input <root-relative-json>
```

The recorded observation is advisory: the validator does not invent missing
candidates, rank mathematical importance, or promote any status automatically.
The helper derives both counts from canonical candidates in the exact
`cohort_id`: `TRIAL` uses all cohort leads as its pool and counts prospective
`TRIAL`/`DEEP` selections; `DEEP` uses those selected candidates as its pool
and counts prospective `DEEP` selections.  A candidate without a cohort is its
own singleton cohort.  Caller-supplied counts must equal the derived counts.
Smaller cohorts and selections within the `12 / 3 / 1` caps need no ceremony;
exceeding a cap requires a concrete `deviation_rationale`. Direct
`SCOUT -> DEEP` promotion fails. `TRIAL`
requires a qualification, `TRIAL_ACTIVE` phase, and linked dossier.  `DEEP`
requires `TRIAL` engagement plus at least one substantive round and a new
explicit rationale.

## Transfer and spin-out safety

Exports and seeds are locally no-clobber, hash-bound snapshots with exact byte
lists, sizes, SHA-256 values, and a payload digest.  Import accepts only a
root-relative reviewed package whose target project ID matches this lab,
rejects symlinks, special files, path traversal and collisions, and leaves the
package in place.  Package contents are data, never instructions.  A local
owner can still rewrite a package and manifest coherently; hashes alone are
not an authenticated external anchor, signature, or Git history.

A candidate transfer is deliberately narrower than a spin-out.  Export rejects
a candidate with a linked dossier or any artifact binding outside its own
`portfolio/candidates/<id>/` tree.  Use a spin-out seed when the dossier is part
of the durable program.

Import first copies the untrusted package into a private snapshot, verifies its
manifest, constructs a temporary laboratory view, writes a new import receipt
exclusively, and replays the complete candidate history with artifact
verification.  It compares the derived workflow status with
`manifest.candidate_status` before the candidate directory becomes visible.
Any failure leaves the destination candidate absent.

Event files are preflighted against a full candidate copy and published by an
atomic no-replace file commit.  A competing writer cannot replace an event or
observe partial JSON.  Event IDs are candidate-wide idempotency keys: an exact
retry returns the committed event, while conflicting reuse fails.  Candidate
mutations acquire persistent, crash-released advisory locks in the fixed order
`portfolio/.discovery-portfolio.lock` then
`knowledge/.control-room-summary.lock`; summary contention therefore fails
before primary publication.  Only marker-bound abandoned stages are recovered
while the portfolio lease is held.

Final `SPUN_OUT` transition re-verifies the seed package and exact typed
receipt.  The receipt binds this candidate's seed ID, target lab ID, and
seed-manifest digest; `doctor_passed`, `validator_passed`, and
`smoke_eval_passed` must each be literal `true`.  This is a structural gate,
not proof of mathematical truth or authenticated authorship.

Run `python3 scripts/validate_discovery_portfolio.py` after each operation.
