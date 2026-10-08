# Team research cycle protocol

## Invariants

- The profile-defined steward coordinates process; research, spin-out, and
  publication decisions require consensus.
- Every cycle starts only after a fresh meeting authorization by every member.
- Team agreement never changes mathematical status. Use the laboratory's proof,
  source, computation, and formalization checks separately.
- Agendas, minutes, decisions, amendments, handoffs, contributions, closures,
  work-item definitions, and transitions are append-only.
- v1 begins with a concise manual meeting summary. The first closure must record
  an explicit capture-mode review, including a permitted `DEFER` decision.

## Cycle sequence

1. The steward runs `prepare-cycle` with an exact window and agenda focuses.
   This prepares work but authorizes nothing.
2. At the meeting, every member reviews the agenda. Run `authorize-cycle` with
   each member ID exactly once. Only one cycle may be active.
3. Complete a copy of `templates/team_collaboration/manual_meeting_summary.md`
   and import it with `record-minutes`. Never silently synthesize agreement.
4. Create typed work items. Each has one owner, an expected artifact, a success
   criterion, and a stop rule. Branch names use
   `work/<cycle-id>/<member-id>/<work-item-id>`.
5. Owners add artifacts and append their own work-item events. Handoffs bind
   exact artifact hashes. Contribution records distinguish human and machine
   work and separately classify formulation, orchestration, key mechanism,
   verification, human re-derivation, formalization, or exposition. They never
   decide authorship or correctness.
6. Use decision records for consensus conclusions. Correct an immutable record
   only with `record-amendment` bound to the earlier bytes.
7. Before closure, every work item must be `ACCEPTED` or `CANCELLED`. Close the
   cycle unanimously and record the next meeting time if one is known. A new
   cycle still requires a new authorization.

## Pull-request convention

- One bounded work-item branch and PR per owner/task; avoid editing another
  owner's event stream.
- Research PRs add artifacts and provenance. They do not directly rewrite a
  shared conclusion or another branch's work.
- A steward-owned integration PR records the reviewed synthesis, typed
  decisions, and any follow-up assignments after the component PRs are visible.
- PR review is a coordination gate, not proof verification.

Run `python3 scripts/team_collaboration.py validate` before merging an
integration PR or closing a cycle.
