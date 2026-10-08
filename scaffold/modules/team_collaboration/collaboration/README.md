# Team collaboration state

This directory is the canonical, laboratory-owned coordination record. It is
not a second mathematical truth ledger: consensus, meeting notes, and review
approval never promote a mathematical claim.

`team.json` is deterministically initialized from `LAB_PROFILE.json` during
generation. Every cycle then receives a fresh meeting authorization. Agendas,
minutes, decisions, amendments, handoffs, work-item events, contributions,
repository plans, disclosure reviews, and repository receipts are append-only.
Corrections are new amendments; do not edit a closed record in place.

Research branches should normally add owner-specific work-item artifacts and
events. A designated integration PR reconciles shared conclusions after review.
This keeps independent work separable and avoids multiple branches rewriting a
shared registry.

