# Problems

A problem dossier is the default container for a serious claim, conjecture,
proof attempt, gap, counterexample search, or formal/computational obligation.

Create one with:

```bash
make new-problem TITLE="Exact target title" TRACK="track_id"
```

Valid tracks are read from `LAB_PROFILE.json`; they are not hard-coded by the
template. Every dossier includes an exact context envelope, approach registry,
problem-derived attack surface, machine-readable proof-search state, candidate
lineage, search-round records, attempts, counterexamples, and verifier area.

Use `LIGHT` or `FULL` according to `workflows/hard_math_search_orchestration.md`.
