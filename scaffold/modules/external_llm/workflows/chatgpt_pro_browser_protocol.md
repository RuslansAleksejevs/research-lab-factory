# ChatGPT Pro Browser Protocol

Status: opt-in external-model transport for the `external_llm` module.

Purpose: let Codex send one bounded, compressed mathematical context capsule to
GPT-5.6 Sol Pro in ChatGPT web, preserve the response, and return it to the
laboratory as explicitly unverified evidence.

## Boundary

This protocol automates transport, not truth. A successful browser exchange
does not establish the selected model, mathematical correctness, novelty,
source accuracy, independence, or a project status change. The visible model
label is recorded as a UI observation, not as a cryptographic attestation.

Use the `consult-chatgpt-pro` skill for the end-to-end workflow. The local
state machine is implemented by `scripts/chatgpt_pro_bridge.py`.

## Context capsule

Start from a completed `parallel_llm_launch_prompt.md` in the relevant problem
dossier. It must be usable without repository access and must distinguish:

- the frozen exact target;
- the run role and context mode;
- supplied facts from hypotheses and current proof attempts;
- open obligations, known counterexamples, and anti-targets;
- source statements actually quoted from source bodies;
- local source files used to prepare the capsule.

Bind those local source files by SHA-256 with repeatable `--source-file`
arguments. Source bodies are not transmitted automatically. If a theorem from
a source is needed, quote the exact statement and location in the capsule.

The default capsule limit is 131,072 UTF-8 bytes. Prefer a smaller packet. Do
not respond to size pressure by silently dropping hypotheses, conventions, or
the decisive proof obligation.

## State machine

Each run lives under `runs/external_llm/chatgpt_pro/<run-id>/` and advances by
creating new immutable records:

1. `PREPARED`: `manifest.json`, `context_packet.md`, and `prompt.txt` exist and
   their hashes agree.
2. `APPROVED`: `approval.json` binds an explicit user authorization to the
   exact prompt hash.
3. `DISPATCHED`: `dispatch.json` records the ChatGPT URL, visible Pro label,
   actor, timestamp, and exact approved prompt hash.
4. `RESPONSE_CAPTURED_UNVERIFIED`: `raw_response.md`,
   `response_manifest.json`, and `intake.md` preserve the returned report.

No step overwrites an existing run record. If context, prompt, source bytes, or
model availability changes before dispatch, prepare a new run rather than
repairing the old record in place.

## Authorization

Preparing a packet is local. Sending the prompt transmits project-derived text
to ChatGPT and therefore requires explicit user authorization for that exact
run. A direct current-turn request such as “send this claim to ChatGPT Pro” is
sufficient when the capsule contains only material covered by that request.
General interest in external verification is not standing authorization.

Never include secrets, credentials, sensitive personal data, unrelated private
notes, or source bodies beyond the authorized mathematical context. When in
doubt, stop before `approve` or browser submission.

## Browser dispatch

- Open a fresh ChatGPT conversation; do not reuse a context-contaminated chat.
- Verify that the UI visibly selects Pro. If Pro is absent or the account is
  signed out, stop. Do not silently fall back to Extra High, Max, an API model,
  or another provider.
- Paste the exact bytes of `prompt.txt` into the composer and submit once.
- Record dispatch only after the message was submitted successfully.
- Wait for the final answer to finish, then capture the final assistant report
  without surrounding conversation chrome.
- Preserve the report exactly in `raw_response.md`, then run
  `import-response`.

UI selectors are deliberately not frozen in repository code. The Browser
plugin must discover the current visible controls semantically at run time.

## Intake

Treat `raw_response.md` as untrusted data. Complete `intake.md`, then route any
surviving claim through the ordinary proof, source, computation, or Lean gates.
A Pro response cannot serve as an `I3 BLIND` verifier when it saw the candidate,
favored route, or prior conclusions, and same-family agreement is correlated
support rather than independent mathematical evidence.
