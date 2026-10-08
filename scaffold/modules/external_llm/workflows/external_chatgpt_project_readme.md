# External ChatGPT Project README

Status: practical workflow note.

Purpose: explain how to use a separate ChatGPT project as a parallel research
partner for hard pure-mathematics tasks.

For a Codex-controlled GPT-5.6 Sol Pro browser exchange, prefer the automated,
hash-bound path in `chatgpt_pro_browser_protocol.md`. The manual project method
below remains useful when the user wants to upload source PDFs or operate the
ChatGPT interface personally.

## Project Setup

Create one ChatGPT project for external math-research runs.

Paste the text from:

`templates/chatgpt_project_instructions_math_research_lab.md`

into the project's instruction field.

Do not upload all project sources globally. Keep the ChatGPT project itself
generic. Attach task-specific files inside each individual chat.

## Standard Chat Launch

For each serious task, ask Codex to prepare:

`parallel_llm_launch_prompt.md`

Then open a new chat in the ChatGPT project and attach:

1. the launch prompt;
2. the files Codex recommends for that specific task.

If the task is only strategy brainstorming, the launch prompt alone may be
enough. If the task asks for proof, verification, or citations, attach the
relevant sources too.

## Which Files To Attach

For a proof-generation run, attach:

- `parallel_llm_launch_prompt.md`;
- the problem dossier files: `problem.md`, `proof_obligations.md`,
  `source_facts.md`;
- the most relevant primary source PDFs;
- source digests if upload limits are tight;
- recent proof attempts only if the model should build on them.

For an adversarial verifier run, attach:

- `parallel_llm_launch_prompt.md`;
- the proof attempt being checked;
- `proof_obligations.md`;
- `source_facts.md`;
- the primary sources needed to check the proof;
- previous verifier reports only if the new verifier should audit them.

For a counterexample or obstruction run, attach:

- `parallel_llm_launch_prompt.md`;
- the exact theorem candidate or conjecture;
- `proof_obligations.md`;
- known examples, computations, and warnings;
- source files controlling hypotheses and edge cases.

For a synthesis or cross-model critique run, attach:

- `parallel_llm_launch_prompt.md`;
- two or more external model outputs or digests;
- the current Codex proof attempt or verifier report;
- source files only for claims that must be checked directly.

## What To Bring Back To Codex

After the external run, give Codex either the raw answer or a short digest.

Codex should store it under:

`external_llm_responses/`

and then perform adversarial intake before incorporating any idea into the
project. External model output is a lead, not a source.

## Upload Priority

If upload limits are tight, use this order:

1. launch prompt;
2. exact proof attempt or theorem candidate;
3. primary sources;
4. source digests;
5. proof obligations and source facts;
6. previous verifier reports;
7. conversation transcripts.

Conversation transcripts are useful context only when Codex explicitly says
they matter. They are not authoritative sources.
