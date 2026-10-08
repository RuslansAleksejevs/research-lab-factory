# Deep Research Goal protocol

## Invariants

- Freeze one exact campaign contract before research.
- Treat `SCOUT → TRIAL → DEEP` as human-gated selection, not automatic
  escalation.
- Give `MARATHON` separate duration-specific authorization and execute it as
  fresh stages of at most six hours.
- Preserve `UNKNOWN` and all kernel verification gates. A deep-goal outcome is
  evidence, never a theorem-status transition.
- Compare outcomes as a vector, never as a universal quality score.

## Modes

| Mode | Cap | Target cap | Initial routes | Role |
| --- | ---: | ---: | ---: | --- |
| `SCOUT` | 1,800 s | 12 | at least 1 | source-bound qualification and cheap falsification |
| `TRIAL` | 7,200 s | 3 | at least 3 | bounded discriminating trials |
| `DEEP` | 21,600 s | 1 | at least 5 | autonomous serious search |
| `MARATHON` | ≤21,600 s per stage | 1 | at least 5 | separately approved resumable search |

A marathon's cumulative authorization is exactly 43,200, 86,400, or 115,200
seconds. Stage `n` has cumulative time before it of
`(n - 1) × 21,600` seconds and receives the smaller of 21,600 seconds or the
remaining authorized time. Stage one must bind an earlier `DEEP` plan and its
immutable outcome. Later stages must bind the immediately preceding
`MARATHON` plan and record under the same immutable campaign ID. A campaign
cannot publish two versions of the same stage, and one exact parent outcome
can authorize only one Marathon child even if a caller changes `campaign_id`.
A genuinely separate Marathon therefore needs a fresh Deep parent outcome.
Multiple outcomes in one stage share rather than reset its wall-time budget.
Every stage must preserve the parent's exact target, acceptance criteria,
anti-targets, and traps.

## Preparation

Fill `templates/deep_research_goal.json`. For every non-Scout goal, first
create a canonical target artifact from
`templates/deep_research_target.json`; its full contract must exactly equal
the inline target fields and use the same kernel `problem_id` and `target_id`.
Store it below `problems/active/<problem_id>/` with a target-bearing filename
so the ordinary proof-search validator can consume the same artifact. The CLI
rejects unknown keys,
duplicate JSON keys, unsafe IDs, unsafe or linked paths, duplicate structural
mechanism families, weak route counts, target drift, and invalid
authorizations.

```bash
python3 scripts/deep_research_goal.py --root . prepare \
  --input research/intake/my-goal.json
```

The command derives the budget and reserve policy, writes
`research/deep_goals/<goal-id>/approved_goal.json`, and makes it read-only.
Every listed local source is bound by path, byte size, and SHA-256. Every
non-Scout target also binds the canonical serialization of the full target
contract as one exact root-relative artifact by the same triple.
Repeating byte-equivalent canonical input is idempotent; reusing the goal ID
for a different plan is a conflict.

State transitions share a persistent `.operation.lock` inode and a
crash-released advisory kernel lock. Do not delete that file. Goal publication
uses a bounded hidden staging directory plus atomic rename; a later mutation
removes only an exact abandoned factory staging shape before retrying.

## Search loop

```text
mechanism-distinct routes
  → route-specific obligation/dependency decompositions
  → cheap falsifiers and counterexamples
  → failure diagnosis
  → evidence-based blocking or reallocation
  → frozen candidate
  → independent adversarial audit
  → repair or exact residual gap
```

Keep 15–20% of elapsed work for verification before any audit-worthy
mathematical candidate and 30–40% afterward. That switch is monotone within a
stage. Each route must decompose the exact target independently enough to expose
a different cheapest discriminating subproblem; several agents repeating one
dependency graph are one route, not several. Merge or stop routes that reach
the same load-bearing gap without a distinct mechanism. The decisive verifier
IDs must be disjoint from generator and material reviser IDs. A route is not
progress merely because it produces long text or replaces the target by an
unproved statement of comparable strength.

## Outcome

Fill `templates/deep_research_outcome.json` and record it through the
no-overwrite, hash-chained CLI:

```bash
python3 scripts/deep_research_goal.py --root . record-outcome \
  --goal-id <goal-id> --input research/intake/my-outcome.json
```

The result vector contains:

1. an outcome class;
2. exact semantic obligations discharged, falsified, narrowed, or left open;
3. evidence and decisive-verifier independence;
4. elapsed wall time and model, route, and verifier attempt counts.

Every strict result names at least one attempted route ID from the immutable
plan; counts alone cannot stand in for route provenance.

`OUTER_RUNNER_REPORTED` records where counts reportedly came from, but v1 has
no authenticated runner receipt and therefore labels them
`UNAUTHENTICATED_OUTER_RUNNER_REPORT`. User-entered counts remain marked
untrusted. Missing counts are `UNSCORED_MISSING_USAGE`, never zero cost.

The five strict-reduction classes require an exact nonempty delta, persistent
evidence bound by path, byte size, and SHA-256, and an independent decisive
verifier. `VERIFIED_PROOF` and `VERIFIED_REFUTATION` additionally require a
bound kernel proof-search state that passes the laboratory validator with an
`I3` closure. `NO_STRICT_REDUCTION` requires an empty delta and empty
verification lineage. The CLI intentionally writes no scalar score and no
theorem status.

Outcome records form an explicit sequence-numbered previous-hash chain. This
detects gaps, interior deletion, and reordering while later records remain.
Like every local owner-writable ledger, it cannot prove that the owner did not
delete an unanchored tail or the whole history. Tamper-evidence against that
threat requires an external trusted runner receipt, Git commit, or other
durable head anchor; v1 does not claim one.

For verified closures, generator IDs, material-reviser IDs, and the decisive
verifier ID must exactly match the validated kernel state. Merely declaring
disjoint aliases in the deep-goal outcome does not establish independence.

Run `status` for a bounded summary and `validate` to detect path hazards,
noncanonical bytes, writable records, digest mismatch, target drift, and
tampering.
