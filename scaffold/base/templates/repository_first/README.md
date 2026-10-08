# Repository-first record templates

Copy one JSON example to a temporary lab-local input, replace every example ID,
path, hash, timestamp, scope, budget, and rationale, then publish it with the
no-clobber helper. Examples are not live research records and establish no
mathematical status.

`export_request.json` starts as a pending selection. Run `prepare-export` to
fill exact SHA-256 and byte counts automatically, then review those versions and
set the review fields before `build-export`. The prepared request is version 2;
the resulting immutable manifest remains version 1. Changed source files cannot
inherit an old review. Repreparing clears approval. Feedback plans repeat the
manifest's bindings; response findings refer to those same exact preimages.

`release_request.json` is a separate Research Artifact Release v1 input. Copy
it to a temporary path, bind it to one exact reviewed export manifest, and bind
every selected regular source file by path and SHA-256. The release helper
materializes only those reviewed bytes as a deterministic local ZIP at
`research/repository_first/releases/<release-id>/<release-version>.zip`.
The ZIP has one canonical top-level prefix,
`research-artifact-release-<release_id>-<release_version>/`, containing
generated `README.md` navigation, a closed `manifest.json`, and the exact
requested member paths. File roles and closed component declarations describe
package navigation and honest omissions; audience labels
describe human review and are not access control. The helper does not compile,
execute, publish, invoke Git/GitHub, use the network, or create a site.

Raw-run examples must bind a strict canonical Durable Research Memory checkpoint
and one exact dossier anchor, not a plain Markdown note.
The effectiveness observation has no hand-authored template because `observe`
derives it from validated ordinary local records.
