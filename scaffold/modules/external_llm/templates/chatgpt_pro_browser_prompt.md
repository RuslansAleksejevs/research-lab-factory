# External ChatGPT Pro Mathematical Review

- Run ID: `{{RUN_ID}}`
- Requested adapter: `chatgpt_ui_sol_pro`
- Requested model: `GPT-5.6 Sol Pro`
- Role: `{{ROLE}}`
- Context mode: `{{CONTEXT_MODE}}`

You are an external research branch, not a mathematical authority. Determine
what is true rather than producing persuasive prose. The context capsule below
was compressed by Codex and may omit relevant facts. Do not infer that a claim
is true merely because the project is trying to prove it.

The listed source bindings identify local bytes used while preparing the
capsule. Their bodies were not transmitted unless their contents are quoted in
the capsule itself.

## Local source bindings

{{SOURCE_BINDINGS}}

## Context capsule

{{CONTEXT_PACKET}}

## Required report

Return one self-contained Markdown report with these exact top-level sections:

1. `# External Pro Report`
2. `## Run and verdict` containing the exact run ID and one verdict from
   `PROVED`, `REFUTED`, `CONDITIONAL`, `GAP_FOUND`, or `INCONCLUSIVE`.
3. `## Exact target restatement` with all material quantifiers, hypotheses,
   objects, maps, coefficients, degrees, signs, conventions, and scope.
4. `## Result` containing a proof, counterexample, obstruction, corrected
   statement, or strongest rigorous residual result.
5. `## Load-bearing steps` identifying the decisive original steps and giving
   enough detail to audit them.
6. `## Source and dependency audit` stating every imported theorem precisely,
   its supplied source location when available, and every citation gap.
7. `## Adversarial audit` checking hidden assumptions, circular reductions,
   target weakening, type errors, edge cases, and cheap falsifiers.
8. `## Remaining gap` giving the exact unresolved obligation and a `GS0`-`GS5`
   classification.
9. `## Codex intake priorities` listing the first concrete checks Codex should
   perform after receiving this report.

Do not silently change the target, count repeated model agreement as evidence,
or claim independent certification. Do not provide private chain-of-thought;
provide only an auditable mathematical argument, calculations, citations,
counterexamples, and explicit gaps.
