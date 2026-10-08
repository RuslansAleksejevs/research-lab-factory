---
name: run-team-research-cycle
description: Prepare, meeting-authorize, divide, hand off, synthesize, and close an append-only team research cycle in a laboratory that has the team_collaboration module.
---

# Run Team Research Cycle

Read `workflows/team_research_cycle_protocol.md` before changing team state.

1. Run `python3 scripts/team_collaboration.py validate` and inspect the current
   cycle, relevant work items, and prior handoffs.
2. Prepare an agenda only from the team's stated aims. Preparation does not
   authorize a cycle.
3. Do not record authorization or a consensus decision unless every configured
   member actually agreed. Do not infer agreement from silence.
4. Use the CLI for every canonical record. Never rewrite an existing agenda,
   minutes, decision, amendment, handoff, contribution, closure, work-item
   definition, or transition.
5. Start with a manual summary. At first closure explicitly present and record
   the capture-mode reminder; `DEFER` is acceptable and preserves manual mode.
6. Keep mathematical validation in the laboratory's mathematical workflows.
   Meeting or PR approval has no mathematical-status effect.
7. Validate again and report exact new root-relative records and unresolved
   decisions.
8. If the cycle performed a coherent substantive research round, publish one
   dated Durable Research Memory checkpoint linking its work-item and handoff
   artifacts. Do not treat meeting consensus, contribution provenance, or PR
   state as mathematical verification.
