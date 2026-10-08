---
eval_id: lean-room-dependency-snapshot-phase-a
category: adversarial
target: lean-room-v2-dependency-snapshot
fixture_version: 1
execution_mode: executable
executable_entrypoint: python3 -m unittest -v tests.test_lean_dependency_snapshot
threshold: zero_skips_and_all_tests_pass
---

# Lean Room v2 dependency snapshot Phase-A acceptance

## Capability under test

The Phase-A importer may preserve an already-resolved Lake dependency graph as
an immutable, source-only snapshot. It must never run Lean or Lake, perform a
network acquisition, accept floating revisions, or make the snapshot formal
certificate evidence.

## Required positive checks

1. Strict Lake manifest versions `1.1.0` and `1.2.0` import from clean local
   Git checkouts whose `HEAD` equals every resolved manifest revision.
2. `fixedToolchain`, when present in a `1.2.0` manifest, is Boolean and bound
   into both the snapshot manifest and dependency-graph digest.
3. File paths, POSIX modes, sizes, exact bytes, file SHA-256 values, package
   tree digests, the dependency graph, and the complete dependency closure are
   reproducibly bound.
4. Publication is atomic and refuses an existing destination.
5. The emitted snapshot contains neither an absolute source-workspace path nor
   any `.git`, `.lake`, build-cache, or precompiled artifact.
6. Git-tracked mode-`120000` links with UTF-8 relative targets and bounded
   chains terminating at tracked regular files inside the same package are
   recorded exactly and materialized as ordinary byte-for-byte file copies.
7. A canonical tracked mode-`160000` gitlink is accepted only when its working
   tree path is a real, completely empty directory. Its path and commit OID are
   bound as unavailable source, and the snapshot publishes exactly that empty
   real directory rather than fabricating submodule contents.
8. Inert tracked binary assets are accepted only as ordinary hash-bound source
   inputs; the binary ban is limited to precompiled or executable artifacts.

## Mandatory rejection checks

- unknown Lake manifest versions or fields;
- a non-Git dependency, floating/non-OID `rev`, duplicate or case/Unicode-
  colliding package names;
- checkout/manifest revision mismatch or a dirty/untracked source tree;
- nested `.git`, package-local `.lake`, untracked/absolute/escaping/dangling/
  cyclic symlink, hardlink, socket, device, FIFO, initialized/populated Git
  submodule, Git LFS pointer, or precompiled/executable binary artifact;
- a missing, symlinked, special, populated, or initialized gitlink directory,
  any unbound empty source directory, or any changed gitlink omission record;
- case-folded or Unicode-normalized source-path collision;
- any post-import change to bytes, mode, inventory, manifest, package config,
  package toolchain, symlink-normalization record/materialized copy, graph, or
  closure digest.

## Gold disposition

A passing Phase-A snapshot is only frozen dependency input for the separately
reviewed guarded Phase-B pilot. An omitted gitlink means its submodule source
was unavailable and could not be inspected or certified. Phase B may proceed
only after explicit package review and must fail closed if package
configuration or build resolution needs that path. A tracked symlink record
binds its original link text, but the published path is a target byte-and-mode
copy and does not retain symlink filesystem identity or resolution semantics.
Phase A is not an LR2 build, an LR3 trust audit, or an LR6 certificate.
