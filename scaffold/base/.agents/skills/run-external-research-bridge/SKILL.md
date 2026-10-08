---
name: run-external-research-bridge
description: Run or collect a user-requested bounded Claude Code research or review session through the optional terminal adapter. Use for an explicit external-model round or returned output, not ordinary research that can proceed locally.
---

# Optional external research session

Read `workflows/claude_terminal_protocol.md`. Check the local switch in
`config/integrations.json`; a request to use Claude authorizes Codex to enable
it for that work. Being enabled does not itself authorize a run.

Codex handles preparation, exact-context review, launch, same-session resume
and collection. Keep scope and selected inputs small; preserve the user's
chosen model and effort. Do not ask the user to move folders, open a separate
chat or operate the former manual adapter. Never convert an existing bound
session to a different runner or rewrite its sealed inputs.

Treat collected output as unverified evidence. Preserve original bytes and
record useful results, failures, uncertainty and next steps in the existing
lab-owned dossier and checkpoint system. Follow the lab's ordinary independent
verification rules before promoting a mathematical claim. Collection is not
proof and does not require repeating the entire research campaign.

Report next steps with brief **Codex:** and **Claude:** lines. New laboratories
use the terminal adapter; an old laboratory's bound session and recovery tools
remain owned by that original laboratory.
