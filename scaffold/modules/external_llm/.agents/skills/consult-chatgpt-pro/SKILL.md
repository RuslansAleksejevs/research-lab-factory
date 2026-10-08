---
name: consult-chatgpt-pro
description: Prepare a bounded hash-bound mathematical context capsule, send its exact prompt to GPT-5.6 Sol Pro in a fresh ChatGPT browser conversation, capture the final response, and import it as unverified external evidence. Use when the user explicitly asks Codex to consult, challenge, verify, prove, refute, or get a second opinion from ChatGPT Pro through the browser for a claim in this laboratory.
---

# Consult ChatGPT Pro

Read `workflows/chatgpt_pro_browser_protocol.md` and
`workflows/parallel_llm_research_protocol.md` before dispatch.

## Prepare

1. Freeze or identify the exact target and choose one role plus context mode.
2. Complete a standalone `parallel_llm_launch_prompt.md`. Keep blind generation
   free of current proof attempts and favored conclusions.
3. Bind only the local files actually used to synthesize the capsule:

   ```bash
   python3 scripts/chatgpt_pro_bridge.py --json prepare \
     --run-id <YYYYMMDDTHHMMSSZ-label> \
     --problem-id <problem-id> \
     --role <PROOF_GENERATOR|ADVERSARIAL_VERIFIER|COUNTEREXAMPLE_HUNTER|STRATEGY_CRITIC> \
     --context-mode <BLIND_GENERATION|PROJECT_AWARE|LITERATURE_AWARE|VERIFICATION> \
     --launch-prompt <root-relative-parallel_llm_launch_prompt.md> \
     --source-file <root-relative-source-or-project-artifact>
   ```

Inspect the returned run status and exact prompt path. Preparation is local and
does not authorize transmission.

## Approve

Approve only when the user explicitly authorized sending this exact
project-derived capsule to ChatGPT Pro in the current turn. If the request did
not authorize external transmission, ask immediately before this step.

```bash
python3 scripts/chatgpt_pro_bridge.py --json approve \
  --run-id <run-id> --actor user \
  --reason "explicit user request in the current turn"
```

Do not approve a capsule containing secrets, credentials, sensitive personal
data, unrelated private material, or source bodies outside the authorized
scope.

## Dispatch with Browser

Use the installed Browser skill and its required setup. Do not implement the
web interaction with shell HTTP, Playwright outside that skill, an API key, or
stored browser credentials.

1. Open `https://chatgpt.com/` in a fresh conversation.
2. If authentication is required, ask the user to sign in in that browser and
   tell you when it is ready.
3. Inspect the current UI and select the visible Pro option. If Pro cannot be
   verified, stop without submitting and never fall back silently.
4. Read the exact local `prompt.txt`, fill the composer with those bytes, and
   submit once. A current-turn explicit send request covers this message only;
   otherwise follow browser confirmation rules at action time.
5. After successful submission, record what the UI showed:

   ```bash
   python3 scripts/chatgpt_pro_bridge.py --json record-dispatch \
     --run-id <run-id> --actor codex-browser \
     --confirmed-model gpt-5.6-sol-pro \
     --visible-model-label "<exact visible Pro label>" \
     --chat-url "<current chatgpt.com conversation URL>"
   ```

6. Wait for generation to finish. Extract only the final assistant response,
   preserving its visible Markdown content. Write it exactly to
   `runs/external_llm/chatgpt_pro/<run-id>/raw_response.md` with the ordinary
   file-editing tool; do not synthesize a cleaner replacement.
7. Import and validate it:

   ```bash
   python3 scripts/chatgpt_pro_bridge.py --json import-response \
     --run-id <run-id>
   python3 scripts/chatgpt_pro_bridge.py --json status \
     --run-id <run-id> --verify
   ```

## Intake

Complete the generated `intake.md`. Treat the response as a lead. Check target
identity, types, sources, calculations, counterexamples, and load-bearing steps
before updating dossier artifacts. Never promote a claim, close a gap, or mark
an `I3` verdict merely because ChatGPT Pro said the argument works.

If the consultation and its local audit constitute a substantive research
round, finish with one `record-research-checkpoint` envelope linking the exact
external-response packet, intake, and independent checks. Preserve the external
answer's unverified source status and record the strongest honest local outcome,
including a failed or inconclusive audit. If this invocation is read-only,
return a schema-valid proposed checkpoint input as `NOT_PERSISTED` for an
authorized coordinator.

If Browser, authentication, Pro access, or response capture is unavailable,
leave the packet in its last valid state and report the exact blocker. Do not
substitute another model or transport.
