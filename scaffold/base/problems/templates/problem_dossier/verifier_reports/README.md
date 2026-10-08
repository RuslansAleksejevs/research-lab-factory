# Verifier Reports

Store independent proof, source, type, and computational audits here.

Every decisive report must record:

- stable target ID/artifact/SHA-256 and canonical candidate ID/artifact/SHA-256;
- originating/material-repair run IDs and a disjoint verifier run ID;
- hash-bound candidate-lineage and verifier-exposure artifacts;
- pairwise-distinct proof-obligation, source-audit, and attack-exit evidence,
  each with its target/candidate-bound role manifest;
- a complete dependency snapshot and audit packet binding those roles, lineage,
  target, and candidate;
- typed exposure and report manifests binding that same audit packet, exact
  lineage sets, verifier, verdict, objections, and report digest;
- verifier independence level;
- exact attack-surface IDs checked;
- load-bearing lemma and circularity audit;
- source, coefficient, degree, twist, support, and map checks;
- verdict, surviving gaps, and registry recommendation.

For machine closure, `templates/verifier_report_manifest.yaml` is the
authoritative structured verifier record. The prose report is still required
and must agree on target/candidate/verifier identity, independence, verdict,
highest gap, unresolved objections, required repairs, and checked obligation
and attack IDs. The closure manifest must bind the same audit packet as the
exposure and report manifests.

Self-audits and `I0`-`I2` reports belong in the record but do not satisfy the
decisive-verifier gate and their run IDs cannot later be recycled as the
decisive verifier for the same candidate. Decisive proof certification requires
`I3 BLIND`. Structural consistency and matching hashes do not authenticate the
run or exposure boundary and do not prove that the mathematical verdict is
correct.
