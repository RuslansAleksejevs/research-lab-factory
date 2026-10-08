# Lean Project Skeleton

These are inert templates, not a buildable certificate case. Render every
double-brace template token before a build. The guarded scaffold must create:

- `lean-toolchain` from `lean-toolchain.template` with an exact immutable Lean
  toolchain identifier;
- `lakefile.toml` from `lakefile.toml.template` with package names and exact
  dependency revisions;
- a `.lean` source from `Main.lean.template` containing the exact declaration;
- `lake-manifest.json` by resolving the pinned dependencies once, then freeze
  and hash it before a certificate build.

No template contains a supposedly universal Lean version. Do not replace an
old imported project's pin merely because a newer Lean version is installed.
Unresolved template tokens fail `LR1`.
