# Verifier Report

- Claim ID:
- Stable target ID:
- Target artifact and SHA-256:
- Canonical candidate ID:
- Candidate SHA-256:
- Candidate approach family and version:
- Candidate artifact:
- Originating run IDs:
- Material-repair run IDs:
- Candidate-lineage artifact and SHA-256:
- Dependency-snapshot manifest and SHA-256:
- Audit-packet manifest and SHA-256:
- Typed proof-obligation/source-audit/attack-exit manifests and SHA-256:
- Verifier run ID:
- Exposure-log artifact and SHA-256:
- Exposure-manifest artifact and SHA-256:
- Verifier-report manifest artifact and SHA-256:
- Verifier independence: `I0 SELF / I1 ENTANGLED / I2 SEPARATE / I3 BLIND`
- Prior context, intended repairs, and favored-route history seen:
- Verdict: `PASS / FAIL / INCONCLUSIVE / VERIFIED`
- Highest surviving gap class: `GS0 / GS1 / GS2 / GS3 / GS4 / GS5`
- Unresolved objections: `[IDs or empty]`
- Required repairs: `[IDs or empty]`
- Checked obligation IDs:
- Checked attack IDs:
- Type checks, including degree/coefficient/twist/support:
- Source checks:
- Counterexample checks:
- Decisive/load-bearing lemma check:
- Circularity check:
- Missing hypotheses:
- Equivalent-strength and circularity checks:
- Registry recommendation:

A generator's self-audit and any `I0`-`I2` report are useful evidence but cannot
be the decisive proof verification. Decisive proof certification requires an
`I3 BLIND` verifier whose run ID is disjoint from every originating and
material-repair run ID and was not reused from a historical `I0`-`I2` audit of
this candidate. The exposure manifest, report manifest, and closure manifest
must bind the exact same immutable audit-packet artifact/SHA-256; that packet
binds the complete dependency snapshot and all three role-specific closure
evidence manifests.

For machine closure, `templates/verifier_report_manifest.yaml` is the
authoritative structured verifier record. This prose report remains required
and must repeat and agree on target/candidate/verifier identity, independence,
verdict, highest gap, unresolved objections, and required repairs; it should
also explain the manifest's checked obligation/attack IDs and check summaries.
The prose cannot override the manifest. Any disagreement detected in the
canonical fields fails closure; broader semantic agreement remains a human or
verifier-review obligation. A repaired candidate or changed dependency
snapshot receives a new audit packet and fresh affected audits.

Manifest validity proves only structural consistency and content identity. It
does not authenticate the verifier or run ID, prove the exposure boundary, or
mechanically establish that the verdict is mathematically correct.
