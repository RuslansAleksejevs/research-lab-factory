---
name: explore-research-directions
description: Propose a small ranked portfolio of genuinely distinct mathematical research directions or a new proof-search wave when current routes stall, fail, duplicate one mechanism, or leave a high-strength gap.
---

# Explore Research Directions

## Procedure

1. Read `workflows/research_directions_protocol.md`, the frozen target, attack
   surface, approach registry, current search state, and recorded failure
   artifacts.
2. Deduplicate by mechanism and decisive lemma. Do not present a renamed route
   or equivalent-strength dependency as a new direction.
3. Use applicable family-generation operators from
   `workflows/hard_math_search_orchestration.md`, prioritizing mechanisms
   absent from the current portfolio and questions discriminating between live
   and failed routes.
4. For each direction give an exact first lemma/construction/computation/source
   target, cheapest falsifier, expected burden reduction, coefficients/types,
   literature needs, risk, payoff, and stop condition. Assess existing-
   ingredient coverage versus genuinely new-theory burden, the global assembly
   bottleneck, formal-library readiness, the smallest formally decisive
   obligation, and the expected correspondence/refactor cost. These are
   advisory prompts rather than a scoring function or route mandate;
   `NOT_APPLICABLE` with a reason is valid, and human or domain judgment may
   override their ranking.
5. Rank a small portfolio by information gain and independence from the favored
   route. If all canonical operators are unavailable, record a typed waiver
   assessment rather than claiming exhaustion informally.
6. Treat bold LLM attempts as capability probes with explicit falsifiers and
   verification budgets. Model confidence, a long run, or a compiling encoding
   is not evidence that the direction is true or worth pursuing.
7. When this is a substantive direction-finding round, finish with one Durable
   Research Memory checkpoint linking the ranked direction artifact and
   preserving rejected families, decisive tests, barriers, and reactivation
   conditions. In read-only mode, return its schema-valid input as
   `NOT_PERSISTED` for an authorized coordinator.

## Output

Return concise, auditable approach seeds with fingerprints, statuses, sources,
assumptions, first artifacts, falsifiers, and next actions. Do not hide gaps or
store private chain-of-thought.
