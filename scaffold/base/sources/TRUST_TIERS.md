# Source Trust Tiers

Trust tier records what is known about a source's provenance and authority at
ingestion time. It is separate from relevance, extraction quality, and the
mathematical status of any claim in the source. No tier makes a theorem
verified automatically.

## Tiers

- `A` — provenance-checked primary or official artifact: for example, an
  author's or publisher's identified paper version, an official standard, or
  a checked formal/computational artifact. Record the exact version or edition.
- `B` — identified reputable reference or secondary source: for example, a
  monograph, survey, lecture notes with clear authorship, or a bibliographic
  record used to locate the primary source. Substantive claims still require
  comparison with the exact primary statement when available.
- `C` — internal or working project material: drafts, collaborator notes,
  working manuscripts, code, or data whose claims and provenance still need
  project review. This is the safe default when the source is known but its
  authority has not been established.
- `D` — unverified lead or derivative material: unknown-provenance files,
  conversations, transcripts, unsourced web summaries, LLM output, or
  extraction/OCR text considered apart from its original. Treat it only as a
  lead until the underlying source is found and checked.

## Operating rules

- Preserve the original file and SHA-256 regardless of tier.
- Record the reason before changing a tier; never upgrade it silently.
- Cite and verify the actual source, not an extraction, digest, transcript, or
  model response.
- Record exact theorem hypotheses, numbering, edition, and printed/PDF page
  conventions separately from the tier.
- A tier bound to a bootstrap material's stored path or SHA-256 in
  `LAB_PROFILE.json` always overrides `TRUST_TIER=X`; the Makefile value applies
  only to unprofiled files. Mixed bootstrap tiers are therefore safe in one
  batch. A path binding is accepted only while its current bytes still match
  the recorded SHA-256. For newly added unprofiled files, use a tier-homogeneous
  batch.
- A duplicate whose registry tier conflicts with its effective tier is an
  error, not a silent reclassification. Correct provenance explicitly before
  relying on that registry entry.

Example:

```bash
make ingest TRUST_TIER=B
make index
```
