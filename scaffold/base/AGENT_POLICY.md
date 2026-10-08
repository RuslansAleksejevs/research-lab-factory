# Agent Policy

This file records project-level policy for Codex agents. It is intentionally
separate from `.codex/config.toml`, because `agents` is a Codex-reserved
configuration area and project-only keys can break task creation.

## Global Limits

- Default maximum concurrent agent threads: 6.
- Default maximum delegation depth: 1.
- Recursive agent swarms are not allowed.

## Sandbox Defaults

- Default sandbox mode: `read-only`.
- Agents that generate proofs, search for counterexamples, verify arguments,
  inspect sources, or evaluate architecture should use `read-only`.
- Agents that revise approved artifacts, edit exposition, prepare talks, or
  record scoped computational/formalization outputs may use `workspace-write`.
- Write-capable agents must not silently change shared mathematical claims,
  hypotheses, notation, or status labels.

<!-- fleet-research-round-protocol:v1 -->
## Fleet research-round authorization

- Control Room `propose-rounds.v1` and `collect-rounds.v1` tasks use `read-only` and
  may not persist project state.
- A displayed-and-clicked `run-rounds.v1` task may use `workspace-write` for the
  exact immutable scope recorded under `research/rounds/<round-id>/`. That click
  is sufficient authorization for ordinary research-state writes and public
  research reads; no second per-laboratory confirmation is required.
- Architecture/policy and mission files remain forbidden to the round. Private
  disclosure, external ChatGPT or another external-model transport, Git or
  remote mutation, publishing, messaging, and other external writes require
  separate authorization.
- Research-integrity state—including dossiers and ledgers—may change only
  through its normal evidence, provenance, verification, append-only, and
  status-transition gates. Every substantive attempt must leave a new
  round-bound Durable Research Memory checkpoint with the exact research date
  and refreshed lab-local index even when its outcome is partial, negative, or
  blocked. The checkpoint outcome vocabulary remains separate from Control
  Room and mathematical claim statuses.
- The deterministic pre/post guard is authoritative for architecture drift;
  an agent cannot certify its own compliance from its response text.
<!-- /fleet-research-round-protocol:v1 -->

## Role File Format

Project agent role files live under `.codex/agents/`.

Each role file should use only fields accepted by the current Codex role parser:

```toml
name = "role_name"
sandbox_mode = "read-only"
description = "Short role summary."

developer_instructions = """
Follow the role described above. Use AGENTS.md as the controlling project
policy. State assumptions explicitly, preserve coefficient and degree
discipline, cite exact project sources, separate verified claims from
conjectures or analogies, and return concise auditable artifacts.
"""
```

Do not put project-only keys such as `can_edit_shared_files`,
`responsibilities`, `max_threads`, `max_depth`, or `default_sandbox_mode` in
`.codex/agents/*.toml` or `.codex/config.toml`.

## Shared Rules

- Follow `AGENTS.md` as the controlling project policy.
- Label mathematical objects by status.
- State coefficients, twists, degrees, and type checks where relevant.
- Cite exact project sources by filename and page.
- Keep proof generation separate from adversarial verification.
- Treat proof-assistant compilation, trusted-boundary audit,
  informal-to-formal correspondence, and post-proof maintainability as
  distinct gates. A formalizer cannot decisively certify its own statement
  correspondence.
- Treat assembly-gap scores, pilot-first plans, proof blueprints, portfolio
  allocation, and stall interventions as planning defaults rather than allowed-
  method lists. A coordinator may deviate with a recorded mathematical reason,
  bounded discriminating test, and stop condition. This discretion never
  relaxes target/status, provenance, execution-safety, build, trust-boundary,
  independent-correspondence, certificate-scope, or material-change gates.
- Store auditable artifacts, not private chain-of-thought.
- Ask for explicit user approval before modifying protected files unless the
  user has already requested the relevant bootstrap or architecture update.

## Hard-Math Search Orchestration

Every proof, refutation, or proof-repair task must select and record an
orchestration profile from `workflows/hard_math_search_orchestration.md`, within
the concurrency and depth limits above.

- If `deep_research_goal` is selected, a `Scout`, `Trial`, `Deep`, or
  `Marathon` request must first freeze the module's exact goal, budget,
  verification reserve, and stopping contract. `Marathon` requires separate
  duration-specific authorization and fresh continuation stages of at most six
  hours. Budget metadata never relaxes `FULL`, source, computation,
  formalization, independent-verification, or status-promotion gates.
- Use `LIGHT` only for one bounded claim or local repair with one proof family,
  no parallel/external-model portfolio, no `GS3`/`GS4` gap, and no novelty or
  protected-ledger promotion. Record the typed target, obligations, attack
  checks, provenance, and exact gap in the proof-attempt artifact.
- Use `FULL` for an open problem, intended main theorem, research-level-3 task,
  major repair, multiple agents or approach families, incompatible formalisms,
  multi-round or partitioned search, `GS3`/`GS4` gap, novelty claim, or proposed
  protected-ledger promotion. Upgrade `LIGHT` to `FULL` as soon as any trigger
  appears.

- In `FULL`, the root coordinator freezes the exact context envelope under a
  stable target ID and SHA-256, maintains the attack surface, and records round
  decisions. A changed statement or hypothesis receives a new target ID and
  invalidates records bound to the previous target. `proof_search_state.yaml`
  is the canonical mutable route/state record; `approach_registry.md` is its
  auditable narrative and evidence view and must agree with it at checkpoints.
- Early branches should be independent by design. Do not expose every generator
  to the favored route when a blind alternative can produce useful evidence.
- Allocate agents by mathematical mechanism, decisive lemma, or adversarial
  obligation. Multiple paraphrases of one dependency chain are one approach
  family, not independent confirmation.
- At each checkpoint record a main-goal dependency delta. Two consecutive
  checkpoints with the same load-bearing blocker and no closed/reduced
  obligation constitute semantic stall; more adjacent lemmas or more agents do
  not reset it. Stall triggers review, not compulsory abandonment. Bounded
  continuation is permitted with the unchanged blocker, a specific
  mathematical rationale, a discriminating experiment, and its stop condition
  recorded; it does not reset the stall count or upgrade route status.
- Keep at least one refutation or boundary-case function independent of any
  affirmative-answer prior.
- A route blocked by a target-strength or circular gap may reopen only when a
  recorded new mechanism, exact source closure, or strictly narrower
  reformulation changes the burden, or a direct checked proof/formal/computational
  artifact closes the exact blocker. Preserve the transition and evidence.
- The root may synthesize a candidate but may not be its decisive verifier. A
  proof generator or material reviser cannot certify that candidate. Decisive
  proof certification requires an `I3 BLIND` verifier under the workflow's
  information-lineage definition, in both `LIGHT` and `FULL`.
- Record information lineage for generators, synthesizers, and verifiers.
  Same-model or same-context agreement is correlated support, not a vote that
  establishes truth.
- Freeze every audited candidate by one canonical ID and SHA-256. Record
  structured originating/material-repair run IDs. Freeze the complete candidate
  dependency ancestry, including stable inherited-gap IDs, in a target-bound
  dependency snapshot, then bind the
  target, candidate, lineage, three role-specific closure-evidence manifests,
  and that snapshot into one audit packet. Typed exposure, structured report,
  and closure manifests must bind the exact same audit-packet artifact/digest.
  For machine closure the report manifest is authoritative; its prose report
  must repeat and agree on target/candidate/verifier identity, independence,
  verdict, highest gap, unresolved objections, and required repairs.
  An `I3` verifier ID must be disjoint from generator/repair runs and must not be
  recycled from a historical `I0`-`I2` audit of that candidate.
- A synthesis uses reciprocal merge edges: every `MERGED` route names its
  survivor, and the survivor lists it as a parent. Enumerate every non-`GS0`
  parent gap separately. Closing one inherited gap requires its own
  target-bound discharge manifest, exact source gap ID/class/statement digest,
  one of `DIRECT_PROOF`, `EXACT_SOURCE`, `FORMAL_CERTIFICATE`, or
  `CHECKED_COMPUTATION`, and evidence naming that gap and digest. Reopening a
  blocked route requires a typed manifest binding the exact blocker,
  authorized basis, result, and evidence.
- Current route status must follow the allowed, round-monotone transition
  history. `HISTORICAL_BACKFILL` is a first-transition initializer only and
  requires a target-bound manifest with route, initial status, timestamp, and
  source artifacts/digests including the transition evidence itself. It must
  not replace or erase genuine history.
- `VERIFIED_PROOF` requires a typed closure manifest binding the frozen target,
  candidate, pairwise-distinct proof-obligation/source-audit/attack-exit
  evidence and their role manifests, dependency snapshot, audit packet,
  lineage, exposure, decisive report, verdict, and hashes.
- `EXHAUSTED_CURRENT_MECHANISMS` requires a redirected wave bound to its initial
  parent wave in a strictly later round, triggering failures, an entirely new
  duplicate-free mechanism delta, and a discriminating question, or a
  target-bound waiver assessment covering every canonical discovery operator
  exactly once with a reason and allowed status. The waiver's unavailable list
  is derived exactly from `UNAVAILABLE` and `NOT_APPLICABLE` assessments.
- Structural validation establishes current-snapshot consistency of declared
  roles, paths, hashes, and IDs only. It does not authenticate runs or
  authorship, prove actual exposure/independence, establish source truth or
  mathematical correctness, or detect history deleted before the snapshot.
