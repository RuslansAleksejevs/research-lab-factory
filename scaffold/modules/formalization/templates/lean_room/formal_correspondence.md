# Formal Correspondence: {{CASE_ID}}

Status: `DRAFT`

This artifact establishes whether the exact Lean declaration corresponds to the
frozen informal target. Compilation is not evidence for this correspondence.

## Bindings

- Problem ID: `{{PROBLEM_ID}}`
- Case ID: `{{CASE_ID}}`
- Target ID: `{{TARGET_ID}}`
- Target artifact: `{{TARGET_ARTIFACT}}`
- Target SHA-256: `{{TARGET_SHA256}}`
- Contract SHA-256: `{{CONTRACT_SHA256}}`
- Source-tree SHA-256: `{{SOURCE_TREE_SHA256}}`
- Obligation IDs: `{{OBLIGATION_IDS}}`

## Frozen informal target

Quote the exact statement or provide a hash-bound reference. State quantifiers,
hypotheses, conclusion, ambient objects and types, domains and codomains,
coefficients, degrees, signs, orientations, supports, finiteness conditions,
normalizations, and all material edge cases.

`{{EXACT_INFORMAL_TARGET}}`

## Exact formal declaration

- Source file: `{{SOURCE_FILE}}`
- Declaration: `{{DECLARATION_NAME}}`
- Pretty-print command: `{{PRETTY_PRINT_COMMAND}}`
- Axiom-print command: `{{AXIOM_PRINT_COMMAND}}`

Insert the exact pretty-printed type captured from the pinned audited build:

```lean
{{EXACT_PRETTY_PRINTED_TYPE}}
```

## Object and type map

| ID | Informal object or predicate | Lean term and full type | Encoding choice | Total/injective/surjective/faithful facts needed | Status |
|---|---|---|---|---|---|
| `MAP-001` | {{INFORMAL_OBJECT}} | `{{LEAN_TERM}} : {{LEAN_TYPE}}` | {{CHOICE}} | {{REQUIRED_FACTS}} | `OPEN` |

## Quantifier and hypothesis audit

| ID | Informal quantifier/hypothesis | Formal binder/hypothesis | Order/domain match | Used in proof? | Status and evidence |
|---|---|---|---|---|---|
| `HYP-001` | {{INFORMAL_HYPOTHESIS}} | `{{FORMAL_BINDER}}` | {{MATCH}} | {{USED}} | `OPEN` |

Explicitly inspect empty types, vacuous implications, implicit typeclass
assumptions, local instances, decidability, classical choice, finiteness,
nonemptiness, equality notions, and universe parameters.

## Conclusion audit

Explain why the formal conclusion is exactly the required conclusion. If it is
stronger, prove that it implies the frozen target under exactly the frozen
hypotheses. If it is weaker, stop: this case cannot certify the target.

`{{CONCLUSION_AUDIT}}`

## Conventions and normalizations

| ID | Convention | Informal choice | Lean choice | Bridge argument | Status |
|---|---|---|---|---|---|
| `CONV-001` | {{CONVENTION}} | {{INFORMAL_CHOICE}} | {{LEAN_CHOICE}} | {{BRIDGE}} | `OPEN` |

## Edge and degenerate cases

| ID | Case | Included by informal target? | Lean behavior | Test or proof | Status |
|---|---|---|---|---|---|
| `EDGE-001` | {{CASE}} | {{INCLUDED}} | {{LEAN_BEHAVIOR}} | {{EVIDENCE}} | `OPEN` |

## Direction back to the target

State the exact implication or equivalence required. Give a proof or bind every
bridge lemma needed to pass from the certified Lean declaration to the frozen
informal statement. An analogy or intended interpretation is not enough.

`{{DIRECTION_AND_PROOF}}`

## Imported bridge lemmas and source status

| Claim ID | Lean declaration | Mathematical statement used | Primary-source location | Source-audit status |
|---|---|---|---|---|
| `BRIDGE-001` | `{{LEAN_DECLARATION}}` | {{STATEMENT}} | {{SOURCE}} | `UNCHECKED` |

## Anti-target checks

| Anti-target ID | Nearby non-solution | Why this formal declaration is not it | Evidence | Status |
|---|---|---|---|---|
| `ANTI-001` | {{ANTI_TARGET}} | {{EXCLUSION}} | {{EVIDENCE}} | `OPEN` |

## Adversarial objections

Record objections without erasing failed attacks. At minimum test statement
weakening, stronger hidden hypotheses, vacuity, inconsistent assumptions,
swapped quantifiers, wrong domains, unused hypotheses, wrong declaration, and
accidental local instances.

| Objection ID | Attack | Outcome | Resolution artifact | Remaining gap |
|---|---|---|---|---|
| `OBJ-001` | {{ATTACK}} | {{OUTCOME}} | {{ARTIFACT}} | {{GAP}} |

## Correspondence verdict

- Auditor ID: `{{AUDITOR_ID}}`
- Auditor run ID: `{{AUDITOR_RUN_ID}}`
- Independent of generation/material repair: `{{INDEPENDENT}}`
- Open correspondence obligations: `{{OPEN_OBLIGATIONS}}`
- Verdict: `DRAFT | PASS | FAIL | CONDITIONAL | ENCODED_MODEL_ONLY`
- Exact certificate scope if `PASS`: `{{EXACT_SCOPE}}`
- Explicit non-claims: `{{NONCLAIMS}}`

`PASS` is permitted only when every material row above is closed and the exact
direction back to the frozen target is proved.

