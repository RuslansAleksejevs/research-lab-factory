# Research Lab Factory

This project creates standalone sibling research laboratories. Keep it free of
live proof attempts, article sources and research conclusions. Do substantive
research inside the generated laboratory after the user opens that project.

Read `overlays/user/AGENTS.user.md`. Use the `create-research-lab` skill for lab
creation. Interpret the user's request, prepare a neutral request profile, run
`validate-profile` and `plan`, then create the agreed laboratory. Routine profile
bookkeeping does not require repeated approval. Ask only when the intended
research scope or a consequential choice is unclear.

Do not overwrite an existing destination or follow symlinked inputs. Preserve
source materials and report validation results honestly. Generation starts no
model run, Git operation, remote service or publication. Claude integration is
optional and disabled by default.

The factory's kernel and generator are shared infrastructure; fix and check those
here. Existing laboratories are independent snapshots: do not silently modify
them. Before changing a laboratory, establish the exact target and intended
upgrade with the user.

Keep communication concise and plain. Organize work to make research useful and
recoverable. Preserve safeguards for data loss and false verification; repair
harmless formatting and naming issues without stopping unrelated work.
