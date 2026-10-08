# Project Map

## Laboratory purpose

{{LAB_MISSION}}

## Components

- `LAB_PROFILE.json`: laboratory-wide mission, tracks, checks, and modules.
- `BOOTSTRAP_REPORT.md`: initial inputs, assumptions, unresolved questions, and
  validation status.
- `knowledge/resume.md`: active dossiers, current blockers, checkpoint, and next
  action after a pause.
<!-- laboratory-survey-protocol:v1 -->
- `knowledge/laboratory_overview.md`: latest explicitly saved whole-laboratory
  survey, with freshness metadata in `knowledge/laboratory_survey_state.json`.
- `research/checkpoints/`: append-only receipts that preserve substantive and
  parallel research-round deltas for later whole-project reconciliation.
- `research/checkpoint_index.json`: deterministic lab-local discovery
  projection over dated checkpoints; it is rebuildable navigation, not
  mathematical evidence or a factory registry.
- `runs/laboratory_surveys/`: hash-bound, append-only deep-survey packages.
<!-- /laboratory-survey-protocol:v1 -->
<!-- laboratory-stewardship-protocol:v1 -->
- `runs/laboratory_stewardship/`: staged, preimage-guarded maintenance runs
  whose validated completion basis is bound into the final saved survey.
- `workflows/laboratory_stewardship_protocol.md`: active whole-laboratory
  reconciliation and repair, distinct from the read-only wake-up survey.
<!-- /laboratory-stewardship-protocol:v1 -->
- `00_INBOX_TO_ANALYZE/`: new source and project material.
- `sources/`: preserved originals, extracted text, digests, bibliography, and
  provenance manifests.
- `knowledge/`: notation, conventions, warnings, questions, and status ledgers.
- `problems/`: exact-target dossiers, attempts, attacks, counterexamples,
  candidate lineage, and independent verifier reports.
- `research/`: track-organized exploratory work.
- `portfolio/`: optional bounded lead/qualification/trial/spin-out state.
- `collaboration/`: optional meeting cycles, assignments, and reviewed handoffs.
- `results/`: status-partitioned durable mathematical artifacts.
- `paper/` and `talks/`: optional human-facing outputs.
- `workflows/`, `templates/`, `.agents/skills/`, `.codex/agents/`: reusable
  research kernel.
- `evals/` and `scripts/`: structural and behavioral safeguards.

## Research tracks

{{LAB_TRACKS}}
