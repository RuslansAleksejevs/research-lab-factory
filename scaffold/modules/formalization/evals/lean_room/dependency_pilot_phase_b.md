---
eval_id: lean-room-dependency-pilot-phase-b
category: adversarial
target: lean-room-v2-dependency-pilot
fixture_version: 1
execution_mode: executable
executable_entrypoint: python3 -m unittest -v tests.test_lean_dependency_pilot
threshold: zero_skips_and_all_tests_pass
---

# Lean Room v2 dependency pilot Phase-B acceptance

## Capability under test

Phase B may execute one bounded Lean declaration only after the durable room,
immutable source snapshot, complete package-configuration review, canonical
pilot project, exact local toolchain, declaration type, and permitted axiom set
have all been bound. A success is `PILOT_VERIFIED_NOT_CERTIFIED`; no v1 LR gate
or automatic mathematical-status change follows.

## Required positive checks

1. A complete approved review binds the snapshot artifact, ID, graph, closure,
   and every package configuration, package toolchain, Gitlink omission digest,
   and root-toolchain compatibility decision in exact sorted order. A package
   pin different from the root pin remains explicit in residual risks and
   evidence; it is never normalized silently. Any indispensable source-
   adjacent Lake `.hash` sidecar is separately reviewed against one exact bound
   source and its tracked trace under controlled reason code
   `LAKE_REHASH_TRACKED_TRACE_CACHE`, a semantically checked justification, and
   an explicit residual-risk projection.
2. The canonical root project uses a TOML-only configuration, exact toolchain,
   a raw Lake manifest byte-identical to the snapshot, one `LeanRoomCase`
   library, exact pinned requirements, and one named declaration defined in
   the compiled canonical `LeanRoomCase.lean`, whose source is statically free
   of the forbidden v1 trust escapes. An out-of-glob root file cannot satisfy
   declaration admission.
3. Every dependency is copied from the validated source inventory into a new
   disposable tree. Bound materialized links and empty Gitlink omissions keep
   their reviewed Phase-A semantics. Generated path overrides cover the full
   transitive package graph.
4. The only build command is the pinned Lake binary with `--packages`,
   `--rehash`, `--reconfigure`, `--keep-toolchain`, `--no-cache`, and target
   `LeanRoomCase`, inside the deny-default Seatbelt profile with network denied.
5. Generated overrides and exact-type audit source remain outside every
   sandbox-writable path. Seatbelt permits writes only to enumerated disposable
   build outputs, home, and temporary paths, not the copied project, package
   sources, snapshot, review, or control inputs.
6. Tool bytes and versions, room-state sequence/hash, inputs, overrides,
   commands, logs, build artifacts, exact type, permitted and reported axioms,
   optional `leanchecker`, sandbox profile, and non-claims are recorded in one
   append-only run.
7. Input and disposable source mutations, including changes attempted by
   package configuration or elaboration code, prevent PASS publication.
8. After the single Lake build, every `.olean` and `.ilean` is inventory-bound;
   Lake output trees are read-only and cannot be executable-mapped during the
   pinned direct Lean and optional direct `leanchecker` audits. Required
   `leanchecker` also passes through the pinned Lake environment.
9. A reviewed source-adjacent `.hash` is precreated by the runner, writable only
   through Seatbelt `file-write-data` on one literal file (not metadata or
   parent-directory writes), required to retain its inode and become a lowercase
   16-hex Lake hash, then made read-only and recorded in a separate evidence
   inventory. Tracked source and trace bytes remain unchanged.

## Mandatory rejection checks

- disabled, malformed, or changed room state;
- missing, unsafe, mutated, or invalid Phase-A snapshot;
- unapproved, incomplete, stale, extra-field, open-issue, or certifying review;
- a package review that omits or misbinds any configuration;
- unsafe project path, `lakefile.lean`, executable hook, unsupported TOML,
  floating or mismatched requirement, manifest mismatch, toolchain mismatch,
  Git/Lake cache, precompiled input, noncanonical import, proof hole, custom
  axiom, unsafe declaration, native trust escape, or wrong declaration;
- missing mandatory isolation/tool binary, online/cache/update behavior, path
  override not covering the complete graph, timeout, or build failure;
- exact-type mismatch, unparseable axiom report, or an axiom outside the
  explicit per-pilot allowlist;
- a requested declaration present only in an out-of-glob root Lean file;
- a false/stale package-toolchain compatibility review, writable control or
  tracked-source input, root `lean_lib` source/glob substitution, or non-finite
  timeout;
- an unreviewed/wildcard source-tree write, a sidecar without a bound tracked
  source and trace, missing/unsupported reason code, filler justification or
  residual risk, a replaced/linked sidecar, metadata/directory write access, or
  a noncanonical sidecar value;
- existing run ID, evidence overwrite, source mutation, or a claim to any
  `LR2`–`LR6` gate, certificate, correspondence verdict, or math-status change.

## Gold disposition

A passing Phase-B run demonstrates only an offline rebuild and exact formal
type/axiom audit for the bound declaration under an expanded trusted boundary.
It does not authenticate upstream authorship, prove informal correspondence or
novelty, or certify a dependency-bearing case.
