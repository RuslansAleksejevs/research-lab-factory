# {{TITLE}}: Problem Dossier

Problem ID: `{{PROBLEM_ID}}`

This dossier is the auditable state container for the problem.

- `problem.md`: statement and motivation.
- `context_envelope.md`: frozen exact target, stable target ID/SHA-256, types,
  completion contract, anti-goals, and context-exposure policy.
- `status.yaml`: high-level mathematical and project status.
- `proof_obligations.md`: claim-level obligations.
- `approach_registry.md`: auditable narrative/evidence view of families,
  fingerprints, gaps, lineage, blocking, and reopening decisions.
- `proof_search_state.yaml`: canonical mutable route/status/gate state in
  `FULL` orchestration.
- `candidate_lineage.md`: immutable candidate ID/digest and structured
  originating/material-repair run provenance.
- `attack_surface.md`: problem-derived adversarial tests.
- `search_rounds/`: one auditable report per substantive search round.
- `attempts/`: concrete route artifacts.
- `counterexamples/`: refutation and boundary-case artifacts.
- `verifier_reports/`: exposure logs plus independent proof and source audits;
  pair decisive records with the typed manifests in `templates/`, including the
  frozen dependency snapshot and audit packet.
- `parallel_llm_launch_prompt.md`: portable external-model context packet.

Select a profile before proof search:

- `LIGHT`: one bounded claim or local repair, one family, no parallel/external
  runs, no `GS3`/`GS4`, novelty, or protected-ledger promotion. Keep the typed
  target, obligations, attacks, and gap in one proof-attempt artifact.
- `FULL`: any open/main theorem, research-level-3 task, major repair, multiple
  families or agents, incompatible formalisms, multi-round/partitioned search,
  `GS3`/`GS4`, novelty claim, or proposed ledger promotion.

For `FULL`:

1. freeze `context_envelope.md` under a stable target ID and SHA-256;
2. derive and prioritize `attack_surface.md`;
3. initialize `approach_registry.md` and `proof_search_state.yaml`;
4. launch genuinely different early routes with recorded context exposure;
5. update the registry and a round report after every material wave;
6. block target-strength gaps until a genuinely new mechanism appears;
7. require a decisive `I3 BLIND` verifier independent of the candidate's
   generation and repair lineage, with a disjoint run ID and typed,
   target/candidate-bound exposure and report manifests;
8. use pairwise-distinct proof-obligation, source-audit, and attack-exit
   evidence artifacts with their role-specific typed manifests; bind them and
   complete route ancestry into one dependency snapshot and audit packet;
9. bind the same audit packet through exposure, the authoritative structured
   verifier-report manifest, and closure, while keeping canonical verdict fields
   consistent in the prose report;
10. make merge edges reciprocal and enumerate one target-bound discharge
    manifest per closed inherited gap; use target-bound backfill manifests only
    for first imported transitions, include their transition evidence, and
    never replace known history;
11. for exhaustion, bind a redirected wave to a strictly earlier parent, its
    failures, and an entirely new duplicate-free mechanism delta, or supply a
    target-bound assessment covering every canonical discovery operator exactly
    once and derive the waiver's unavailable list from its statuses.

The machine-readable state is canonical for mutable route/status/gate data. The
Markdown registry explains the evidence and decisions and must agree with that
state. Mathematical artifacts contain the proof and source evidence; neither
state view validates a proof by itself. Structural validation establishes only
current-snapshot consistency of declared roles, IDs, paths, and hashes. It does
not authenticate runs or authorship, prove exposure/independence or source
truth, establish the mathematics, or detect history deleted before the
snapshot.
