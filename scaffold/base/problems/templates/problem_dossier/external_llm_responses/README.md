# External LLM Responses

Store compact digests and local assessment records here. Preserve original
collected bytes separately and link their exact paths and hashes from the
digest; avoid duplicating raw returns into the dossier.

A useful filename is `YYYYMMDD-model-role.md`; a clear existing name is fine.
Record the model or tool, date, selected prompt and inputs, intended role,
original evidence paths, and the local assessment of the result. Distinguish
raw output from a digest and mark unchecked material
`UNVERIFIED_EXTERNAL_OUTPUT`.

Use `templates/external_llm_response_digest.md` for compact digests. For a Claude
terminal collection, follow `workflows/claude_terminal_protocol.md`: inspect the
receipt, retain accepted and later versions separately when they differ, and
record useful outcomes, failures, uncertainty and next steps in the existing
research checkpoint. No external response automatically changes claim status.
