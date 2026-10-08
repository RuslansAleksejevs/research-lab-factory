# Mathematical Attack Surface

Create this artifact before broad proof search and update it whenever the
target, route, or imported machinery changes. Its purpose is to turn likely
failure modes into assigned tests rather than retrospective warnings.

## 1. Exact Target Contract

- Claim ID: `[required]`
- Stable target ID / SHA-256: `[required after freezing]`
- Mathematical status: `[project status]`
- Exact statement artifact: `[path and section]`
- Quantifiers: `[all existential/universal dependencies]`
- Ambient categories: `[topological/algebraic/arithmetic/etc.]`
- Hypotheses: `[complete list]`
- Conclusion: `[typed conclusion]`
- Coefficients: `[for every homology/cohomology theory]`
- Tate twists/weights: `[where relevant]`
- Degree conventions: `[cohomological/homological/bigraded]`
- Support theory: `[ordinary/compact/proper/local/etc.]`
- Boundary and degenerate cases: `[empty, disconnected, singular, low-degree, characteristic cases]`
- Explicit anti-targets: `[nearby statements that do not solve the task]`

Any change to this contract requires a new version and an entry in the round
report. A route may not repair itself by silently weakening the target.

## 2. Object and Map Type Table

Record every nontrivial map used by a candidate. For composition, the target
of one row must literally match the source of the next after all shifts.

| ID | Object/map | Source | Target | Coefficients | Twist/weight | Degree shift | Variance/support | Construction/source | Status |
|---|---|---|---|---|---|---|---|---|---|
| `[T-...]` | `[symbol]` | `[typed source]` | `[typed target]` | `[ring/module]` | `[integer/explanation]` | `[shift]` | `[covariant/etc.]` | `[proof or exact citation]` | `CHECKED/OPEN/FAILED` |

Mandatory rule: phrases such as "by functoriality", "projection formula",
"trace compatibility", or "twists are harmless" do not mark a row checked.
Name the exact map and theorem.

## 3. Hypothesis-Preservation Table

Every reduction, base change, compactification, normalization, passage to a
minimal counterexample, or replacement of a theory must preserve the inputs
needed later.

| Reduction ID | Before | Operation | After | Hypotheses needed later | Preservation proof/source | Failure witness | Status |
|---|---|---|---|---|---|---|---|
| `[R-...]` | `[objects/hypotheses]` | `[exact operation]` | `[objects/hypotheses]` | `[list]` | `[artifact/citation]` | `[test case]` | `CHECKED/OPEN/FAILED` |

## 4. Attack Inventory

Each applicable item must become a prioritized attack in Section 5.

### A. Statement and definition attacks

- Are all objects defined in the claimed generality?
- Do connected/disconnected, empty, singular, reducible, nonorientable, or
  low-dimensional cases change the definition?
- Are multisets, multiplicities, repeated components, signs, and equivalence
  relations handled exactly?
- Does the proof establish the requested statement rather than a nearby
  special case or convention-dependent variant?

### B. Type, parameter, and convention attacks

- Check the source, target, ambient category, and well-definedness of every map,
  operation, relation, and composite.
- Check every degree, grading, filtration, coefficient, sign, variance, support,
  normalization, and parameter range that the problem uses.
- Check changes of scalars, coefficients, base, topology, regularity class, or
  characteristic against the exact comparison theorem required.
- Check that pairings, traces, invariants, and optimization objectives land in
  the stated target and satisfy the claimed nondegeneracy or extremality under
  the actual hypotheses.
- Check every identification valid only after a quotient, completion,
  localization, limit, reduction, or asymptotic passage.

### C. Imported theorem and citation attacks

- Does the primary source state the exact result used?
- Do regularity, properness, smoothness, finiteness, characteristic,
  invertibility, orientation, and support hypotheses match?
- Is a compatibility being used where the source proves only existence?
- Are theorem number, printed/PDF page, coefficients, twists, and normalization
  recorded?
- Is the alleged source only a search result, abstract, secondary summary, or
  model assertion?

### D. Reduction and circularity attacks

- Is the missing lemma equivalent to or as strong as the target?
- Is the target hidden in a "standard" construction, extension theorem, or
  global compatibility claim?
- Does the implication reverse correctly?
- Does the reduction preserve all hypotheses and edge cases?
- Is a known conjecture being imported as though it were a theorem?

### E. Local-to-global and compatibility attacks

- Do independently valid local choices glue globally?
- Is independence of choices proved, not asserted?
- Are cocycle, descent, transition, boundary, and obstruction conditions
  checked?
- Does a decomposition produce objects of the required connectedness and
  multiplicity?
- Are two traces, pairings, Gysin maps, or normalizations actually the same?

### F. Counterexample and sanity-check attacks

- Test the smallest nontrivial examples and all degenerate boundary cases.
- Search for examples at every dropped or weakened hypothesis.
- Test characteristic (2), odd characteristic, torsion, and ramified cases
  separately when relevant.
- Use computation only with a documented model, range, exact arithmetic, and
  certificate. Finite testing is evidence, not a universal proof.
- Try to falsify each `GS3` lemma independently of the main theorem.

### G. Analogy and generalization attacks

- Has an analogy between settings been substituted for an actual proof or
  comparison theorem?
- Does the proposed analogue preserve the relevant structures, operations,
  parameters, types, and target objects?
- Is a generalization being claimed beyond the verified source scope?
- Has novelty been claimed without terminology and literature searches?

### H. Multi-agent process attacks

- Are purportedly independent approaches actually descendants of one draft?
- Was the verifier told the target is true or shown intended repairs?
- Did the verifier author or materially revise the candidate?
- Are repeated answers being mistaken for independent evidence?
- Were failed attempts and inherited gaps lost during synthesis?

## 5. Prioritized Attack Matrix

Attack statuses are `UNTESTED`, `SURVIVED`, `FAILED`, `INCONCLUSIVE`, and
`NOT_APPLICABLE`.

| Attack ID | Priority | Target claim/step | Failure mode | Minimal witness or discriminating test | Assigned verifier | Independence level | Evidence required | Status | Consequence if failed |
|---|---|---|---|---|---|---|---|---|---|
| `[AT-...]` | `P0/P1/P2` | `[claim/obligation ID]` | `[specific failure]` | `[example/calculation/source check]` | `[run ID]` | `[I0-I3]` | `[artifact/certificate]` | `[allowed status]` | `[GS class and route action]` |

Priority meanings:

- `P0`: can refute the route or expose circularity/type failure cheaply;
- `P1`: substantive compatibility, source, or boundary test required before
  candidate promotion;
- `P2`: robustness, exposition, or generalization test after core validity.

## 6. Mandatory Candidate Gate

Before an approach becomes `UNDER_AUDIT`, the matrix must include results for:

1. one exact statement/anti-target check;
2. the complete type/degree/coefficient/twist audit where applicable;
3. every reduction's hypothesis-preservation audit;
4. circularity and target-strength-gap audit;
5. at least one smallest example and one degenerate/boundary case;
6. a counterexample search for each decisive new lemma;
7. exact source checks for all substantive imports;
8. verifier-lineage and self-certification check.

An `INCONCLUSIVE` mandatory attack remains an open proof obligation. It cannot
be converted to `SURVIVED` by consensus or by polished exposition.

## 7. Failure-to-Gap Mapping

- A bounded omitted calculation normally creates `GS1`.
- An unverified source, normalization, or compatibility creates `GS2`.
- A new strictly narrower mathematical obligation creates `GS3`.
- Circularity or an equivalent-strength missing lemma creates `GS4` and blocks
  the route.
- A checked counterexample, type contradiction, incompatible hypothesis, or
  false indispensable import creates `GS5` and refutes the recorded route.

## 8. Attack-Surface Exit Summary

- Candidate version audited: `[version/path]`
- Candidate ID / SHA-256: `[required for an audited candidate]`
- `attack_surface_exit_manifest.yaml` artifact / SHA-256: `[path/digest]`
- Decisive verifier(s) and independence: `[IDs; I-levels]`
- `P0` attacks remaining: `[IDs or NONE]`
- `P1` attacks remaining: `[IDs or NONE]`
- Failed attacks and consequences: `[IDs; gap/status changes]`
- Surviving exact scope: `[statement with exclusions]`
- Source audit status: `[complete/incomplete; artifact]`
- Recommended root decision: `REPAIR | TARGET_GAP | BLOCK | REFUTE | SECOND_AUDIT | CLOSE`
