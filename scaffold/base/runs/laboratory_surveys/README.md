# Laboratory Survey Packets

Each subdirectory is one immutable whole-laboratory survey packet and contains
`inventory.json`, `start_seal.json`, `report.md`, and `manifest.json`. An explicit current-
literature run may also contain `literature_delta.md`.

The inventory binds the declared local evidence scope before synthesis. The
read-only-mode start seal binds the inventory and immutable starting manifest
fields, including external bindings. The
manifest records starting and finishing basis digests, coverage, drift, report
hash, any literature cutoff, and any explicit immutable artifact outside the
ordinary basis. A stewardship-closing survey binds its excluded
`completion_basis.json` and rechecks that digest at finalization and on later
freshness checks. Keep incomplete or drifted packets as history, but do not
publish them as the latest fresh overview.

Freshness rehashes the authoritative packet report, manifest, inventory, and
start seal. A later edit to any of them is `STALE`, even though survey packets
are excluded from the ordinary project basis.

`knowledge/laboratory_overview.md` and
`knowledge/laboratory_survey_state.json` point to the latest stable packet.
Survey packets are navigation and provenance records, not mathematical
evidence.
