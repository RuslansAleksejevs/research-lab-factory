# Lean Room evaluations

This directory records the executable and behavioral acceptance suite for the
laboratory's Lean Room.  The executable checks live in
`tests/test_lean_room.py`; every test constructs an isolated temporary
laboratory and copies only the Lean Room implementation and templates into it.
Mutations are confined to that temporary root.  The suite does read the
canonical room state as an outer kill-switch binding, and never writes it.

Run the suite from the laboratory root:

```sh
python3 -m unittest -v tests.test_lean_room
```

Static policy checks run without Lean.  Tests that actually invoke `lean` or
`lake` skip with an explicit reason when the exact pinned toolchain or mandatory
macOS `sandbox-exec` backend is unavailable.  No test is allowed to download a
toolchain or dependency.  A development run may report those explicit skips;
the laboratory's full acceptance runner treats every skip as a failure.

The canonical room must be enabled when the suite starts.  If its validated
sequence/hash binding changes while a guarded process is running, that process
group is terminated and the run cannot pass.

The v1 fixtures are intentionally tiny. They exercise trusted-boundary and
correspondence failures, not mathematical difficulty:

- `valid/Main.lean` is a kernel-checkable theorem with no extra axiom;
- `sorry/Main.lean` and `admit/Main.lean` contain forbidden proof holes;
- `custom_axiom/Main.lean` proves a theorem through a project-defined axiom;
- `native_decide/Main.lean` requests the disallowed native-code trust escape;
- `auto_implicit/Main.lean` requests an implicit type parameter outside the
  exact frozen signature;
- `wrong_theorem/Main.lean` uses the contracted declaration name and compiles,
  but has a different type from the contract.

Passing this suite establishes only that the room's controls reject the listed
regressions.  It does not establish informal-to-formal correspondence for a
real research theorem.

The separate Lean Room v2 dependency-pilot acceptance suites are:

```sh
python3 -m unittest -v tests.test_lean_dependency_snapshot
python3 -m unittest -v tests.test_lean_dependency_pilot
```

Phase A is fully static and must pass with zero skips. Phase B's static
adversarial checks must also pass with zero skips; an actual toolchain build is
reported explicitly when the exact local Lean/Lake/Seatbelt prerequisites are
available and may never download or resolve a dependency. A successful v2
pilot is `PILOT_VERIFIED_NOT_CERTIFIED`, not v1 LR evidence.
