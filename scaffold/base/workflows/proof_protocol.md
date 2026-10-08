# Proof Protocol

1. Normalize the statement with quantifiers, hypotheses, ambient objects,
   maps, types, parameters, conventions, and boundary cases. Include degrees,
   coefficients, signs, twists, weights, supports, and normalizations whenever
   the problem uses them.
2. Select and record `LIGHT` or `FULL` using
   `hard_math_search_orchestration.md`. In `LIGHT`, record the exact target,
   obligations, attack checks, provenance, and gap in the proof-attempt artifact.
   In `FULL`, freeze `context_envelope.md`: exact target, completion contract,
   anti-goals, allowed source modes, and statement-change authority. Run initial
   dimension, parity, type, edge-case, and source-conflict checks in either
   profile.
3. When the `external_llm` module is enabled and external work is actually
   requested, create or update `parallel_llm_launch_prompt.md` before deep work,
   following `parallel_llm_research_protocol.md`. External use is optional and
   never sends material automatically. Without that module, keep all portfolio
   work inside the laboratory.
4. Decompose the target into proof obligations and derive attacks from the
   definitions, maps, reductions, sources, and likely degeneracies. A `LIGHT`
   attempt may keep these checks inline; `FULL` instantiates
   `attack_surface.md`. Before substantial formalization, normally write a
   detailed informal proof blueprint: expose omitted "standard" facts, give the
   dependency graph and exact lemma interfaces, and separate library lookup
   obligations from mathematical gaps. This is a revisable planning default,
   not a privileged proof route; a recorded alternative may replace it without
   relaxing the exact-target or correspondence gates.
5. In `FULL`, initialize or update `proof_search_state.yaml` as the canonical
   mutable route/state record and `approach_registry.md` as its auditable
   narrative and evidence view. Group routes by mathematical mechanism and
   decisive lemma, not wording, model, or agent name. Record each route's mode,
   lineage, strongest proved result, highest mathematical gap, closure gates,
   parent/inherited gaps, transition history, status, and reopen condition in
   both views without divergence.
6. In `FULL`, launch a genuinely diverse initial portfolio using several
   applicable family-generation operators, keep designated early branches
   independent of the favored project approach, and reserve an independent
   refutation or counterexample branch. A `LIGHT` attempt remains one family and
   upgrades to `FULL` if a second family or any other `FULL` trigger appears.
7. In `FULL`, work in rounds. After each round, collect concrete artifacts, fingerprint
   and merge semantic duplicates, attack load-bearing steps, classify every gap
   `GS0`-`GS5`, and redirect effort toward underexplored families or
   discriminating tests. Record main-goal dependency delta: helper-lemma count,
   line count, or a compiling side result is not progress without a named edge
   to the frozen target. Two consecutive checkpoints with the same blocker and
   no closed/reduced obligation trigger the semantic-stall review in the
   orchestration workflow. Normally pause or pivot; bounded continuation is
   allowed with a recorded mathematical reason, discriminating test, and stop
   condition, without resetting the stall count or relabelling activity as
   progress.
8. Block a route whose remaining burden is target-strength/circular (`GS4`) or
   repeatedly asserts the same substantive gap without a new mechanism. Reopen
   it only for a recorded new mechanism, exact source closure, strictly narrower
   reformulation, direct checked proof/formal/computational closure, or
   authorized new claim.
9. Promote an end-to-end argument only to `CANDIDATE`; freeze one canonical ID,
   exact artifact, and SHA-256. Record structured originating/material-repair
   run IDs in `candidate_lineage.md`, then assign a decisive `I3 BLIND` verifier
   with a disjoint run ID and hash-bound exposure log. The verifier must not have
   generated or materially repaired the candidate or received generator
   optimism or intended repairs. A
   generator's self-audit, an `I0`-`I2` audit, and same-context model agreement
   are not decisive verification.
   If a proof assistant is useful, a small vertical pilot that checks the
   encoding and one fragile load-bearing obligation is the default before
   expansion. It may be skipped or replaced with recorded rationale,
   replacement evidence, and a bounded stop condition. A build pass is not a
   correspondence pass.
10. When external verification is requested, produce a standalone proof plus a
    separate adversarial verifier prompt covering hypotheses, types, parameters,
    source dependencies, the attack surface, equivalent-strength gaps,
    circularity, and possible counterexamples.
11. Adversarially intake external proofs, critiques, and alternate ideas;
    preserve provenance and update the registry only after classification.
    Never count repeated wording or shared-context agreement as an independent
    family or certification.
12. Revise only in response to verifier objections, exact source repair, or a
    genuinely new proof mechanism. A repaired candidate receives a new
    ID/digest and fresh audits for every affected step. Normally separate
    correctness closure from refactoring for deduplication, API quality, or
    maintainability. Regardless of order, any material source change receives
    a fresh build/trust audit and a renewed statement-correspondence check
    before evidence or status is reused.
13. Finish with either a complete independently audited proof/refutation or the
    strongest rigorously proved residual result, exact unresolved gaps, and the
    preserved registry of blocked/refuted routes. The residual outcome is
    valuable research state but is not a solution of the original problem.
