# Discovery portfolio transaction and round-gate rubric

Reject or safely survive every case:

| Attack | Required result |
| --- | --- |
| Process fails before an event commit | No event path is visible and no candidate state is corrupted |
| Competing writer targets the same event path | Existing bytes remain unchanged |
| Transfer candidate links a problem dossier | Export fails; use spin-out |
| Transfer event binds an inbox or dossier artifact | Export fails as non-closed |
| Rehashed package contains semantically invalid candidate history | Import fails before destination publication |
| Manifest status differs from replayed history | Import fails before destination publication |
| Payload already contains the new receipt filename | Import refuses to overwrite it and publishes nothing |
| Candidate is relinked to another dossier after one round | Event preflight fails without append |
| Second round starts before deciding the previous round | Round preflight fails |
| `TRIAL -> DEEP` occurs while a round decision is pending | Promotion preflight fails |
| Caller understates a real cohort pool or prospective selection | Promotion fails; canonical cohort counts prevail |
| Live summary lock blocks a candidate mutation | Mutation fails before primary publication |
| Process dies while holding either lock | Advisory lease is released; persistent lock inode is reused |
| Exact event retry follows a summary-write failure | Existing event returns; no duplicate event is appended |
| Same event ID is reused with different bytes/type | Reuse fails without append |
| Crash leaves a marker-bound staging directory | Next locked operation removes only that exact owned stage |
| Spin-out receipt is text, cross-candidate, mismatched, or has a false gate | Final transition fails before append |
| Package kind disagrees with `requires_factory_generation` | Verification/import fails before publication |
| Bound artifact changes after event preflight | Publication-time recheck fails without append |
| Spin-out request becomes a symlink after validation | No-follow copy fails; no seed is published |

These checks protect workflow state and provenance.  They do not prove
mathematical truth, openness, novelty, or research quality.
