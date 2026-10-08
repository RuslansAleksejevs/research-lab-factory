# Formalization

The optional Lean Room module is installed, but its durable default is
`disabled`. It may be enabled only on an explicit user instruction; installing
the module, choosing a formalization deliverable, or asking about Lean does not
enable it. While disabled, only status inspection and read-only static review
are permitted.

The authoritative state is `lean_room_state.json`. Operational rules live in
`workflows/lean_room_protocol.md`, and neutral planning artifacts live under
`templates/lean_room/`. Once explicitly enabled, the default campaign sequence
is a suitability/library-readiness assessment, a small vertical pilot, and a
detailed informal proof blueprint before expansion. These are non-binding
planning heuristics: a coordinator may record a different sequence, replacement
evidence, and a bounded stop condition. No such choice relaxes room-state,
security, target, build/trust, correspondence, or certificate gates.

Lean Room v2 also provides a separate dependency-pilot lane. It imports only
already-resolved Git packages into an immutable source-only snapshot, requires
an explicit snapshot review, and rebuilds disposable copies with network and
precompiled caches disabled. A passing run is
`PILOT_VERIFIED_NOT_CERTIFIED`: it does not enter or weaken the v1
`LR2`–`LR6` certificate path.

Record the proof-assistant version, imported libraries, theorem statement,
encoding choices, trusted kernel boundary, guarded build command, artifact
digests, and the exact relationship to the informal target. A successful kernel
check establishes only the encoded declaration under its recorded boundary.
