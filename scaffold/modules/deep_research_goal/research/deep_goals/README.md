# Deep research goals

This directory is empty live research state in a newly generated laboratory.

`scripts/deep_research_goal.py prepare` creates one canonical no-overwrite
directory per approved goal. `record-outcome` adds sequence-numbered,
previous-hash result vectors without replacing an existing ID. Do not edit
generated records by hand, place article-specific material in the factory, or
interpret these records as theorem-status promotions. A local filesystem owner
can remove an unanchored tail or all records; v1 has no external head anchor.

`.operation.lock` is a persistent infrastructure inode whose advisory lock is
released automatically when its process exits or is killed. Do not remove it
as a stale-lock workaround. A later state transition safely recovers only
factory-shaped abandoned `.prepare-*` staging directories.
