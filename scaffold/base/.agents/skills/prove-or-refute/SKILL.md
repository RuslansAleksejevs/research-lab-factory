---
name: prove-or-refute
description: Attempt, refute, repair, or isolate the exact gap in a nontrivial mathematical theorem or conjecture using typed targets, distinct mechanism families, counterexample attacks, source checks, and independent final verification.
---

# Prove or Refute

## Procedure

1. Read `workflows/hard_math_search_orchestration.md` and select `LIGHT` or
   `FULL`. Upgrade to `FULL` immediately when any trigger in that workflow
   appears.
2. Freeze the exact target, coefficients, twists, degrees, types, anti-targets,
   and acceptance criterion. In `FULL`, bind its stable target ID and SHA-256 in
   `proof_search_state.yaml` before launching generators.
3. Decompose proof obligations and derive a problem-specific attack surface.
4. Run at least one proof branch and one independent refutation/boundary branch.
   In `FULL`, seed genuinely different mechanism families using the workflow's
   discovery operators; do not count paraphrases or shared decisive lemmas as
   independent approaches.
5. Require each return to contain a concrete lemma, construction, equation,
   source theorem, computation, certificate, or counterexample. Record its
   inputs, run ID, idea fingerprint, and exact gap.
6. At each checkpoint record the main-goal dependency delta. New prose, code,
   lines, or adjacent lemmas are not progress unless they close or strictly
   reduce a named obligation. After two consecutive checkpoints with the same
   blocker and no semantic delta, review that family. Normally pause for an
   independent audit, detailed informal expansion, representation pivot, or
   honest stop. Bounded continuation is allowed when the unchanged blocker,
   mathematical reason, discriminating experiment, and stop condition are
   recorded; it neither resets the stall count nor upgrades status.
7. Classify gaps `GS0`-`GS5`. Block target-strength/circular routes, extract the
   weakest failed dependency, and use that failure to redirect the next wave
   toward a different mechanism. Reopen only through a blocker-bound manifest.
8. Synthesis inherits parent gap IDs/classes/statement digests until typed
   discharge manifests bind exact closure evidence.
9. Freeze an end-to-end candidate by canonical ID and SHA-256. Material repair
   creates a new version and invalidates affected audits.
10. Require a decisive `I3 BLIND` verifier with typed exposure/report manifests.
   A generator, material reviser, or historical `I0`-`I2` verifier cannot
   certify the candidate.
11. Return only an allowed honest terminal status. `VERIFIED_PROOF` and
    exhaustion require their typed closure or wave/waiver manifests; structural
    validity is not itself mathematical verification.
12. Before a substantive round ends, use `record-research-checkpoint` to leave
    one compact dated outcome envelope linking the detailed proof-search,
    counterexample, source, and verifier artifacts. If this invocation is
    strictly read-only, return the schema-valid proposed checkpoint input as
    `NOT_PERSISTED` for the authorized coordinator instead of writing it.

## Output

Return a concise, auditable artifact with exact status, target/candidate IDs,
sources, assumptions, route families, gap table, attacks, verifier lineage,
strongest rigorous result, and next discriminating actions. Do not hide gaps or
store private chain-of-thought.
