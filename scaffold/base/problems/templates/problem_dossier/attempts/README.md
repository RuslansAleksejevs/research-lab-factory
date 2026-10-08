# Proof Attempts

Store one auditable file per materially distinct route or candidate version.
Use `templates/proof_attempt.md`.

Every attempt must record:

- approach family ID and idea fingerprint;
- round, role, context mode, and independence lineage;
- concrete mathematical mechanism or construction;
- decisive/load-bearing lemma;
- strongest result actually proved;
- exact gap and `GS0`-`GS5` class;
- counterexamples and edge cases tested;
- recommended registry status and reopening condition if blocked.

Recommended filename:

`YYYYMMDD-<approach-id>-<short-description>.md`

Every material `FULL` attempt must be indexed canonically in
`proof_search_state.yaml` and explained in `approach_registry.md`. A `LIGHT`
attempt may remain self-contained in its proof-attempt and verifier artifacts.
A renamed repetition of a blocked route remains in the same family.
