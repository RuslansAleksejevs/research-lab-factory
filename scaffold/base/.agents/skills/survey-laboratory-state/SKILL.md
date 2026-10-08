---
name: survey-laboratory-state
description: Survey and reconcile the whole mathematical laboratory when the user asks for a high-level state review, wants to recover the thread after many or parallel research rounds, asks what is proved or blocked and what to do next, or says "shake head", "wake up and survey the lab", "потряси головой", "давай проснемся и окинем взором лабораторию", "давай проснёмся и окинем взором лабораторию", or an equivalent phrase.
---

# Survey Laboratory State

1. Read `workflows/laboratory_survey_protocol.md` and follow its full local
   survey procedure. Do not substitute the shallow resume dashboard for this
   reconciliation.
2. Treat persisted project artifacts as the visibility boundary. State plainly
   that results left only in chats or still held by running agents are not
   recoverable from the laboratory until checkpointed.
3. Build a read-only starting inventory before synthesis. Validate and query
   `research/checkpoint_index.json` first for orientation, then read the bound
   canonical checkpoints and evidence rather than trusting index summaries.
   Read all relevant tracks, dossiers, round reports, results, ledgers,
   decisions, source metadata, warnings, portfolio/collaboration history,
   archives, and output reports, including inactive and failed work. Compute a
   basis digest in memory when practical; do not create files merely to support
   the default chat survey.
4. Reconcile exact scope and status across artifacts. Preserve conflicting
   labels side by side and mark them `UNRECONCILED`; never infer a promotion
   from polished prose, model agreement, a survey, or structural validation.
5. Use the local full-survey mode by default. Browse or run a literature delta
   only when the user explicitly requests current literature or what has been
   done by others. Never send private draft text or unpublished project results
   in a search query.
6. For a large laboratory, delegate bounded read-only scans by track, dossier,
   sources, and outputs. Require artifact paths and exact statuses from every
   scout; their summaries are navigation, not verification.
7. Return the default full local survey in chat without modifying the
   laboratory. Only when the user explicitly asks to save, persist, or
   checkpoint the survey, write it with `templates/laboratory_survey.md` under
   `runs/laboratory_surveys/<survey-id>/` and recompute the inventory after
   synthesis.
8. For an explicitly persisted survey, rescan changed inputs or mark the packet
   `DRIFT_DETECTED`; do not publish it as fresh. Only after a stable finish may
   you update `knowledge/laboratory_overview.md` and
   `knowledge/laboratory_survey_state.json` to point to the immutable packet.
   The overview is derived navigation and never mathematical evidence.
9. Return a concise whole-project picture, answer the user's state questions,
   and propose a small ranked portfolio of next rounds with exact artifacts,
   falsifiers, verification plans, and stop conditions. When the request is
   about a stronger model or tool, explicitly match its new capability to
   recorded obstructions and reopen conditions. Do not launch those rounds or
   edit protected ledgers unless separately authorized.
