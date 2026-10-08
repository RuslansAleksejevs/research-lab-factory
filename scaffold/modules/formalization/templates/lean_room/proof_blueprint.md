# Detailed Informal Proof Blueprint

Status: DRAFT

This artifact is the mathematical specification for a formalization campaign.
It is not Lean source and not proof evidence. Replace every prompt below with a
precise answer and bind the rendered bytes from the campaign plan.

This is a revisable current plan, not a privileged mathematical route. A
different route may be recorded in a successor blueprint, but no revision may
silently change the frozen target, encoding, or claimed correspondence.

## Identity and bindings

- Campaign ID:
- Problem ID:
- Exact target artifact and SHA-256:
- Target and obligation IDs:
- Intended formal declaration and exact type:
- Exact toolchain and supported dependency boundary:

## Statement audit

Write the informal statement with all quantifiers, hypotheses, ambient types,
domains, codomains, coefficients, orientations, signs, finiteness assumptions,
normalizations, and edge cases explicit. List nearby statements that must not
be formalized in its place.

## Representation plan

For each informal object, predicate, relation, map, and parameter, record:

| Informal item | Formal type or declaration | Namespace/import | Instances or coercions | Correspondence obligation |
|---|---|---|---|---|
| | | | | |

Explain why this representation is suitable. Record competing representations,
conversion costs, and the observation that would trigger a pivot.

## Proof dependency graph

List proof steps in dependency order. Each step must have a stable ID.

### Step BP-001

- Exact informal proposition:
- Inputs and hypotheses with types:
- Output:
- Depends on:
- Intended existing declaration or new local lemma:
- Search terms and plausible namespaces:
- Edge and degenerate cases:
- Direction needed by the main theorem:
- Current status: OPEN

Duplicate the block for every step. The final step must name every direct
dependency of the main goal.

## Expanded standard facts

Search the draft for words such as *standard*, *routine*, *clear*, *obvious*,
*immediate*, and *similarly*. For every occurrence, replace the omitted move by
an exact proposition and either a located declaration or a new blueprint step.

| Original phrase/location | Exact fact with hypotheses | Existing declaration or new step ID | Verification evidence |
|---|---|---|---|
| | | | |

An empty table is valid only with a sentence explaining how the search was
performed and why no omitted fact remains.

## Library and assembly plan

- Required definitions and located declaration names:
- Required theorems and located declaration names:
- Required imports and instances:
- Expected coercion, rewriting, and normalization friction:
- Routine bridges that still require explicit proofs:
- Unresolved library/API questions:
- Redundant-lemma search strategy:

## Correspondence plan

For each proof step, explain why the proposed formal statement has exactly the
needed strength and how it maps back to the informal argument. Include
quantifier order, empty or degenerate types, implicit instances, and every
anti-target.

## Vertical-pilot cut

- Representative object:
- Load-bearing bridge:
- Target-shaped declaration:
- Assembly gap crossed:
- What the pilot deliberately does not test:
- Pilot PASS evidence binding:

## Stop and pivot conditions

- Mathematical-gap stop conditions:
- Library-readiness stop conditions:
- Two-checkpoint semantic no-progress rule:
- Representation-pivot trigger:
- Success criterion for handing the blueprint to a formalization generator:
