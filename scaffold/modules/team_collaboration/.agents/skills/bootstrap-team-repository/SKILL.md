---
name: bootstrap-team-repository
description: Safely dry-run or explicitly apply local Git and GitHub repository setup for a configured team laboratory, with exact inputs, public-disclosure review, drift rejection, and append-only receipts.
---

# Bootstrap Team Repository

Read `workflows/team_repository_bootstrap_protocol.md` before acting.

1. Confirm that `collaboration/team.json` is active and validate team state.
2. If visibility remains `UNDECIDED`, stop and ask the team to choose. Never
   assume public or private visibility.
3. Run only `team_repository_bootstrap.py plan` first. Inspect the exact file
   inventory and returned plan SHA-256. Planning performs no Git/network action.
4. For `PUBLIC`, require a complete unanimous disclosure review bound to that
   SHA-256. Do not approve it for the users.
5. Treat `apply` as an external side effect: run it only after the user has
   explicitly authorized this exact plan in the current task. Never pass or
   persist credentials; the `gh` CLI uses its existing authentication context.
6. Inspect the append-only receipt. On partial failure, do not delete `.git`, a
   remote, commits, or invitations. Report exact completed and failed steps.

