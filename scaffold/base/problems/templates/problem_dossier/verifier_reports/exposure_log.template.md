# Verifier Exposure Log: {{TITLE}}

- Problem ID: `{{PROBLEM_ID}}`
- Stable target ID:
- Target artifact:
- Target SHA-256:
- Canonical candidate ID:
- Candidate artifact:
- Candidate SHA-256:
- Verifier run ID:
- Dependency-snapshot manifest and SHA-256:
- Audit-packet manifest and SHA-256:
- Assigned by root run ID:
- Assignment date/time:
- Exposure-log SHA-256 field: recorded externally in `proof_search_state.yaml`
- Exposure-manifest artifact and SHA-256: recorded externally in
  `proof_search_state.yaml`

## Packet shown

- Audit-packet manifest:
- `target` artifact and SHA-256:
- `candidate` artifact and SHA-256:
- `candidate_lineage` artifact and SHA-256:
- `proof_obligations` artifact and SHA-256:
- `proof_obligations_manifest` artifact and SHA-256:
- `source_audit` artifact and SHA-256:
- `source_audit_manifest` artifact and SHA-256:
- `attack_surface_exit` artifact and SHA-256:
- `attack_surface_exit_manifest` artifact and SHA-256:
- `dependency_snapshot` artifact and SHA-256:
- Other files/messages: `[NONE for a closed packet, otherwise enumerate]`

## Material deliberately withheld

- Generator optimism or instruction to assume truth:
- Intended repairs and favored-route discussion:
- Private generator/reviser conversation:

## Independence cross-check

- Originating run IDs:
- Material-repair run IDs:
- Verifier ID disjoint from both lists: `YES / NO`

This is an assignment-time information-boundary record, not proof evidence.
Instantiate `templates/verifier_exposure_manifest.yaml` to bind it, the exact
audit packet, and all ten packet-role paths/digests to the frozen target,
candidate, exact lineage sets, and verifier. The report and closure must bind
the same packet. These bindings do not authenticate the run, prove that no
other material was seen, or establish mathematical correctness.
