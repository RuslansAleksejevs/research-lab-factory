# Parallel LLM Research Protocol

Status: standard workflow.

Purpose: make serious mathematical research attempts parallelizable across
Codex and external LLMs before Codex commits to one proof strategy.

Every use of this parallel protocol is `FULL` orchestration. Record
`orchestration_profile: FULL` in the launch packet and
`proof_search_state.yaml`; a `LIGHT` task upgrades before a second agent or
external-model run is launched.

## Trigger

Use this protocol when Codex is about to begin an intensive research pass, for
example:

- proving or refuting a new nontrivial claim;
- formulating a theorem candidate from analogies or partial evidence;
- repairing a proof with substantial unresolved obligations;
- choosing between incompatible mathematical formalisms.

Do not require it for small edits, formatting, citation cleanup, or local
checks of an already isolated obligation.

## Phase 0: Launch Packet Before Deep Work

Before the main proof attempt, Codex should create or update a Markdown file
named:

`parallel_llm_launch_prompt.md`

inside the relevant problem dossier.

If no problem dossier exists yet, create one first or use
`templates/parallel_llm_launch_prompt.md` as a temporary standalone launch
packet.

The launch packet must be usable by a strong external model without access to
the repository. It should include:

- the exact mathematical task and its current status;
- all hypotheses, coefficients, twists, degrees, pairings, and conventions that
  are already known;
- a prioritized list of files or source PDFs to upload;
- concise project context, including which sources are authoritative and which
  are only conversation history or heuristic leads;
- known proof obligations, risks, and possible counterexamples;
- strict instructions about honesty, status labels, citations, and adversarial
  verification;
- the desired output format for the external model;
- a request for both a formal artifact and a slow explanatory version when the
  topic is conceptually difficult.

After creating the launch packet, Codex should give the user the file path and
a short summary of what it contains. By default, Codex should wait before the
main proof attempt so the user can send the prompt to other models. If the user
has already explicitly asked Codex to continue immediately, Codex may proceed
after emitting the launch packet.

## Phase 0.5: Search State And Independence

For a serious run, freeze `context_envelope.md`, instantiate
`attack_surface.md`, and initialize or update `proof_search_state.yaml` plus
`approach_registry.md`. The YAML state is the canonical mutable record of route
IDs, statuses, mathematical gaps, closure gates, current round, and verifier
assignment. The Markdown registry is the auditable narrative/evidence view and
must agree with it at every checkpoint.

Each branch must receive an explicit:

- role;
- context mode: `BLIND_GENERATION`, `PROJECT_AWARE`, `LITERATURE_AWARE`, or
  `VERIFICATION`;
- approach ID or instruction to propose a genuinely new family;
- independence lineage and list of prior artifacts visible to it;
- bounded concrete artifact contract and falsification test.

A blind branch receives the common exact mathematical contract but not the
favored proof attempt, project synthesis, or prior verifier conclusion. A
project-aware or verification branch may receive them only when its exposure is
recorded. Blind generation cannot establish novelty or literature completeness.

## Phase 1: External Runs

The user may send the launch packet to one or more external models. Each run
should be labeled by:

- model or tool name;
- date;
- prompt file used;
- uploaded files, if any;
- intended role: proof generator, verifier, counterexample searcher,
  exposition writer, or strategy generator.
- context mode and prior attempts supplied;
- approach ID/family, if assigned;
- independence lineage and any affirmative-answer prior disclosed.

Raw external answers may be stored when useful. If an answer is too long,
record a structured digest instead.

For an explicitly authorized GPT-5.6 Sol Pro run in ChatGPT web, use
`workflows/chatgpt_pro_browser_protocol.md` and the `consult-chatgpt-pro` skill.
That route embeds the completed launch packet into one bounded browser prompt,
binds the local source bytes used to prepare it, and imports the exact response
as `UNVERIFIED_EXTERNAL_OUTPUT`. It does not upload source bodies, choose a
fallback model, or change mathematical status automatically.

## Phase 2: Intake

Store external outputs or digests under the problem dossier, preferably in:

`external_llm_responses/`

Use `templates/external_llm_response_digest.md` for a compact digest. Every
imported idea must preserve provenance and status. External model output is not
a source of mathematical authority by itself.

Codex must then perform an adversarial intake pass:

- separate theorem candidates, proof steps, citations, examples, and warnings;
- mark each item as proved, conditional, conjectural, heuristic, failed,
  counterexample, or unresolved;
- check degrees, coefficients, twists, domains, codomains, pairings, and
  duality maps before incorporating anything into project artifacts;
- record useful repairs in proof attempts, verifier reports, source facts,
  warning notes, or obligation tables.

After intake, update the approach registry with the mathematical family, full
idea fingerprint, load-bearing lemma, strongest result actually proved, exact
gap and `GS0`-`GS5` class, lineage, and route recommendation. Different wording,
fresh chats, or same-model agreement do not constitute a new family.

## Phase 3: Cross-Feeding

When several external answers exist, Codex may prepare a comparison prompt that
asks a model to critique another model's argument. This is useful only if the
input is structured enough to audit.

Cross-feeding rules:

- do not ask a model merely to agree or synthesize;
- ask it to identify exact gaps, missing hypotheses, broken degree checks,
  source mismatches, and counterexamples;
- keep analogies between mathematical settings separate from proofs;
- never promote a result because several models repeated it.

## Phase 4: Repeated Rounds And Termination

For multi-round work, follow `hard_math_search_orchestration.md`. At each
checkpoint the root agent should:

1. cluster outputs by mathematical mechanism and decisive lemma;
2. merge semantic duplicates and preserve inherited gaps;
3. adversarially test the load-bearing steps;
4. block target-strength or circular dead ends;
5. redirect effort toward underexplored families or discriminating tests;
6. reopen a blocked route only for a recorded burden-reducing mechanism, exact
   source/narrower reformulation, or direct checked closure of its blocker;
7. launch a new round only with a distinct information objective;
8. freeze the best surviving candidate by canonical ID and SHA-256, record
   originating/material-repair run IDs, and submit it to a disjoint `I3 BLIND`
   verifier with a hash-bound exposure log.

The run ends with either:

- a complete proof or refutation surviving independent audit; or
- the strongest rigorous residual result, exact gaps, and the preserved route
  registry.

The second outcome is valuable research state but not a solution of the target.
Wall-clock duration, agent count, eloquence, and repeated agreement are not
evidence of correctness.

## Acceptance Rule

A theorem becomes a project theorem only after the usual project standards are
met: every substantive step is proved here, reduced to a correctly stated cited
theorem, or checked by a clearly identified formal or computational method.

## Template-Lab Requirement

If this repository is later distilled into a reusable pure-mathematics research
lab template, this protocol should be preserved as a first-class workflow:
Codex emits a launch prompt before serious work, the user can run parallel
external models, and Codex later audits and integrates their outputs.
