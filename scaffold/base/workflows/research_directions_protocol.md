# Research Directions Protocol

Return a small ranked set of precise directions. Each direction must include
project connection, nearest known result, smallest examples, first lemma, proof
or counterexample strategy, literature needs, difficulty, risk of being known,
payoff, and next action.

Also assess whether the direction is mainly an **assembly gap**—most ingredients
and local lemmas exist but the global proof has not been assembled—or requires
substantial new theory. Record existing-ingredient coverage, the exact global
bottleneck, cheapest falsifier, formal-library readiness, smallest formally
decisive obligation, expected proof/correspondence/refactor cost, and a pilot
stop rule. This is a planning heuristic, not evidence of tractability or truth.
These fields are advisory prompts, not a scoring function or route mandate.
`NOT_APPLICABLE` with a reason is valid, and human or domain judgment may
override their ranking.
Favor bold tests when they have discriminating feedback and rigorous
verification routes; do not let model confidence or available code replace
mathematical value, human judgment, or source audit.
Do not down-rank a direction merely because the target is famous or has been
open for a long time. Ask which mechanisms and witness spaces were actually
searched, and whether new models, computation, formalization, or a new
representation materially change the feasible frontier. The same reassessment
must not be inverted into an unsupported claim that the target is easy or true.
