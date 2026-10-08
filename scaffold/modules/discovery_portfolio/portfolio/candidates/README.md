# Candidates

Each non-README child is one candidate ID with canonical no-overwrite intake
metadata and a sequence-numbered, SHA-256-linked `events/` history.  These
local controls detect inconsistent edits while later records remain; without
an external anchor they do not prove that a filesystem owner never deleted or
coherently rewrote history.

Schema-v2 candidates also contain `origin_evidence/`.  Every file there is
listed in `candidate.json` by candidate-local root-relative path, byte size,
and SHA-256.  Do not edit those copies after intake.  Engagement promotions
are `ENGAGEMENT_DECISION` events; they allocate search depth but never alter
mathematical status.

The first `ROUND` freezes the dossier link.  Every `ROUND` leaves an explicit
portfolio decision pending; a second round or `DEEP` promotion is invalid until
that decision is appended.
