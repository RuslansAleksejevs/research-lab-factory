---
name: ingest-math-source
description: Preserve, hash, register, extract, and digest new mathematical source files placed in the laboratory inbox, including PDFs, notes, TeX, bibliography, or text, while keeping trust status and provenance explicit.
---

# Ingest Math Source

Read `sources/TRUST_TIERS.md`. Preserve the inbox copy, compute SHA-256, copy
to `sources/originals/`, extract page-aware text when available, create a
digest, and update the registry and index. Enforce a bootstrap tier already
recorded by stored path or SHA-256 in `LAB_PROFILE.json`; the command tier is
only a fallback for unprofiled files. Treat a duplicate tier conflict as an
error, never as an implicit reclassification. Otherwise classify provenance
and authority separately from relevance and claim status. Do not treat a draft,
note, transcript, extraction, or high-tier source as verified mathematics
without checking the exact claim.
