---
name: intake-discovery-candidate
description: Add a bounded unverified lead to this discovery portfolio when the user wants to capture, scout, or triage a possible mathematical problem without beginning a serious proof campaign.
---

# Intake Discovery Candidate

Read `workflows/discovery_portfolio_protocol.md` and inspect
`templates/discovery_portfolio/candidate_intake.json`.  Clarify the lead enough
to distinguish it from existing candidates, but do not claim it is open,
important, novel, or true.  Mark human-provided ideas `USER_SUPPLIED`.  Mark
leads found by the laboratory `LAB_SCOUTED` and include at least one
root-relative source artifact; intake will copy and hash-bind it inside the
candidate.  Use an optional `cohort_id` only for one reviewed allocation pool.
Fill a lab-owned copy of the template and run:

```bash
python3 scripts/discovery_portfolio.py intake --input <root-relative-json>
python3 scripts/validate_discovery_portfolio.py
```

Leave the candidate at phase `LEAD` and engagement `SCOUT`.  Do not open a
problem dossier or start proving it unless the user separately chooses to
qualify or trial it.
