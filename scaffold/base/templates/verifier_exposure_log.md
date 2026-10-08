# Verifier Exposure Log

Status: assignment-time information-boundary record.

- Problem/claim ID:
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
- Other files/messages: `[NONE for a closed packet, otherwise enumerate and downgrade independence as needed]`

## Material deliberately withheld

- Generator optimism or instruction to assume truth:
- Intended repairs and favored-route discussion:
- Private generator/reviser conversation:

## Independence cross-check

- Originating run IDs:
- Material-repair run IDs:
- Verifier ID disjoint from both lists: `YES / NO`
- If `NO`, maximum admissible level is `I0`-`I2`; do not mark `I3`.

This record documents the assigned information partition. It does not by itself
prove that the partition was respected; preserve platform run/thread evidence
where available. Instantiate `templates/verifier_exposure_manifest.yaml` to
bind this prose record, the audit-packet artifact/digest, and exactly the ten
packet roles above to the frozen target, candidate, lineage sets, and verifier.
The structured report and closure must bind the same audit packet.

Paths and hashes prove only which bytes were declared. They do not authenticate
the verifier, prove that no other material was seen, or establish the
mathematical correctness of the later verdict.
