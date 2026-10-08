---
name: verify-proof
description: Adversarially verify one immutable mathematical proof, refutation, counterexample, or formal/computational certificate when exact candidate identity, information exposure, source dependencies, types, attacks, and surviving gaps must be audited independently.
---

# Verify Proof

## Procedure

1. Read `workflows/hard_math_search_orchestration.md`. Record the stable target
   ID/artifact/SHA-256, canonical candidate ID/artifact/SHA-256, verifier run
   ID, exact packet shown, and material withheld.
2. Refuse an `I3` label if this run generated, synthesized, materially repaired,
   or previously audited the candidate with project/favored-route context.
   Record the actual `I0`-`I3` level; do not assume the target is true.
3. Reconstruct the implication chain without relying on the generator's
   intended repair. Check every load-bearing lemma and hidden use of the target.
4. Check domains/codomains, degrees, coefficients, signs, twists/weights,
   supports, products, operations, Gysin/trace maps, duality, and edge cases
   whenever relevant.
5. Verify every substantive imported result against its exact primary-source
   statement and page. A related theorem or abstract is not sufficient.
6. Execute the problem-derived attack surface, search for counterexamples, and
   test whether any reduction merely restates a target-strength claim.
7. If formal evidence is supplied, distinguish compilation, trusted-boundary
   audit, informal-to-formal correspondence, and maintainability. Recompute the
   exact statement/assumption mapping; a build or formalizer self-audit cannot
   certify that the intended theorem was encoded.
8. Classify every surviving issue `GS0`-`GS5`; give exact objections and minimal
   repairs. Any material repair creates a new candidate version and requires a
   fresh decisive audit.
9. For decisive `I3`, complete the hash-bound exposure and report manifests.
   Return `PASS` only when every substantive obligation is `GS0`; otherwise
   return `FAIL` or `INCONCLUSIVE` with the exact gap.
10. Treat a substantive verification as a research outcome. Before handoff,
    use `record-research-checkpoint` to create one dated envelope linking the
    verifier report and exact candidate; if the verifier is read-only, return
    the schema-valid proposed input as `NOT_PERSISTED` for the coordinator.

## Output

Return a concise verifier report with target/candidate bindings, actual
independence level, sources, attack results, type table, surviving gaps,
verdict, required repairs, and registry recommendation. Do not hide gaps or
store private chain-of-thought.
