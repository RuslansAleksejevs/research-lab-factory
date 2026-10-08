# Adversarial Evaluations

The `proof_search_*.md` fixtures test the proof-search orchestrator against:

- anchoring on a polished favored route;
- pseudo-diversity among same-mechanism attempts;
- reductions to equivalent-strength lemmas;
- premature success before independent audit;
- reopening a blocked route without a blocker-closing delta;
- same-model and shared-context self-certification;
- confusion between blind generation and literature-aware research;
- defeatism or overconfidence caused by the age and prestige of an open
  problem in the AI-assisted setting.

Each fixture supplies a scenario, evaluation prompt, pass criteria, hard
failures, and gold disposition. The current local validator checks fixture
integrity. A future sampled regression runner may execute the prompts and grade
responses against these rubrics, but its model verdict must never be treated as
mathematical proof.

`durable_research_memory_incomplete_handoff.md` additionally tests exact
research dates, compact pointer-envelopes, honest omission of inapplicable
sections, negative-result preservation, append-only supersession, and the
lab-local-only index boundary.

`research_release_guarded_materialization.md` tests the boundary between human-
reviewed disclosure selection and deterministic local packaging: exact source
bindings, drift and private/raw exclusions, bounded completeness language,
canonical-lab authority, audience labels without access control, and zero
compilation, execution, Git/GitHub, network, site, or publication action.
