# Local raw run archive

When repository-first policy is enabled, raw run bytes belong under
`research/raw_runs/archive/<problem-id>/`. That archive is local and untracked
by default. Never put it under `.git/`, include it in a reviewed export, or use
it to store credentials, hidden system/developer prompts, or private
chain-of-thought.

The tracked, bounded `raw_run_manifest` lives beside the existing problem
dossier. It binds the raw archive by SHA-256 and byte count, links an existing
Durable Research Memory checkpoint, and links the canonical claim dossier.
After deliberate local pruning, retain `HASH_ONLY_PRUNED` in the manifest; do
not invent replacement bytes.
