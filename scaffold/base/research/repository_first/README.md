# Repository-first derived state

This directory holds only reviewed export manifests, derived immutable local
release ZIPs, and explicit passive local effectiveness observations.

Campaign, run, source-use, verification, assessment, and feedback records live
next to their existing problem dossier. Mathematical truth remains in ordinary
dossiers, sources, evidence, checkpoints, results, and ledgers; nothing here is
a second truth ledger or a claim-promotion surface.

Read `workflows/repository_first_protocol.md` before use. The helper is dormant
unless `LAB_PROFILE.json.repository_first.enabled` is exactly `true` with the
private/local-untracked/reviewed-only policy fields.

`scripts/repository_first.py build-export` selects exact reviewed disclosure
bytes. `scripts/research_release.py` separately materializes a closed request as
`releases/<release-id>/<release-version>.zip` and validates its manifest and
members. Each ZIP has one canonical top-level
`research-artifact-release-<release_id>-<release_version>/` prefix containing
generated `README.md`, closed `manifest.json`, and only exact reviewed member
paths. A release is a derived projection: it does
not become canonical, promote a claim, compile or execute content, publish,
invoke Git/GitHub, access the network, or create a site. Audience labels are
not access control.
