# External Strong-Model Sprint Protocol

Status: standard workflow extension.

Purpose: preserve a repeatable workflow for short windows of access to a
strong external mathematics model, especially when the repository and source
organization live in Codex.

Use this together with `parallel_llm_research_protocol.md`. The difference is
urgency: this protocol is for a bounded access window where many independent
runs should be launched before there is time for full Codex intake.

## Core Principle

Separate the external model's roles into distinct chats.

Register every chat in the problem's proof-search state with its context mode,
approach assignment, visible prior artifacts, and independence lineage. A fresh
chat is not automatically an independent mathematical route.

Do not ask one chat to be simultaneously a blind proof generator, an auditor of
project work, a strategy generator, and a synthesis referee. Those roles
interfere with each other. The best sprint usually has:

1. a blind or nearly blind proof-generation run;
2. a project-aware proof-audit run;
3. one or more adjacent-domain idea runs;
4. a final cross-critique run after the first reports exist.

External output is always provisional. It becomes project mathematics only
after Codex intake, source checking, type checking, and status labeling.

## Chat Order

### Round 1: Independent Thought

Start with at least one chat that receives no project proof attempts and no
Codex-generated synthesis. Give it only:

- a precise problem statement;
- primary sources, if upload limits allow;
- a request for theorem, counterexample, obstruction, or conditional result.

This protects against anchoring on the project's current proof strategy.

### Round 2: Project-Aware Audit

Open a separate chat for the current project proof or theorem candidate. Attach
the proof attempt, source-fact file, proof-obligation file, and the most relevant
primary sources. Ask for adversarial verification, citation repair, and a
cleaned theorem statement.

### Round 3: Adjacent-Domain Mining

Use additional chats for structurally adjacent fields, examples, alternative
representations, and broad research directions. These chats may be speculative, but every idea
must be labeled as theorem, conjecture, heuristic, analogy, failed attempt,
counterexample, or unresolved question.

### Round 4: Cross-Critique

After receiving multiple reports, open a final chat. Attach the reports and ask
the model to identify disagreements, hidden assumptions, exact proof gaps,
missing examples, and the strongest defensible theorem statement.

Because this chat sees the parent reports, it is a synthesizer or entangled
critic, not an `I3` decisive verifier of the resulting synthesis.

## Source and Attachment Policy

If upload time or token budget is tight, attach files in this order:

1. the run-specific prompt;
2. exact theorem candidate or proof attempt;
3. primary source PDFs;
4. source digests;
5. proof obligations and source facts;
6. previous verifier reports;
7. conversation transcripts.

For a blind run, omit project proof attempts even if upload space remains.

For a project-aware audit, include the proof attempt and the files needed to
check it.

For a strategy run, the prompt and high-level project maps may be enough.

## Output Requirements

Ask the external model to return:

- one or more LaTeX files, or a single LaTeX report if that is simpler;
- explicit status labels for every mathematical claim;
- every type, parameter, degree, coefficient, operation, and domain-specific
  check relevant to the supplied target;
- a short citation list or citation-gap list, without spending the whole run on
  bibliography;
- an adversarial self-audit;
- an approach-registry delta: mechanism fingerprint, decisive lemma, strongest
  proved result, exact gap, `GS0`-`GS5` class, and route recommendation;
- a list of what Codex should verify first during intake.

It is acceptable for sprint prompts to de-emphasize perfect bibliography. The
external model should focus on mathematical substance, but it must mark
uncited imported theorems as citation gaps.

## Intake Rule

When the user brings reports back to Codex, Codex should store raw outputs or
digests under the relevant problem dossier when possible. Broad exploratory
reports may first live under `runs/external_llm/`.

During intake, Codex should:

- preserve provenance;
- extract theorem candidates, proof ideas, examples, warnings, and citations;
- run an adversarial type check before updating project claims;
- fingerprint reports by mathematical mechanism, merge semantic duplicates,
  and preserve shared load-bearing gaps instead of counting model agreement;
- update `approach_registry.md`, `attack_surface.md`, and
  `proof_search_state.yaml` after classification;
- update proof obligations, verifier reports, source facts, or research
  directions only after deciding the status of each imported idea.

## Reuse

Future strong-model access windows should start by asking Codex to create a
dated, versioned sprint folder under `workflows/external_model_sprints/` with
role-separated prompts and an upload plan. Raw returned reports can later be
stored under `runs/external_llm/` before Codex digests them into problem
dossiers or research notes.
