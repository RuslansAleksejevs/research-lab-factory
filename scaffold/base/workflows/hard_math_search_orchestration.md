# Hard-Math Search Orchestration

Status: operational workflow for nontrivial proof, refutation, and theorem-formulation searches.

This workflow supplements `workflows/proof_protocol.md` and, when enabled,
`workflows/parallel_llm_research_protocol.md`. It governs how a root coordinator
preserves independent approaches, classifies gaps, blocks unproductive routes,
commissions verification, and terminates honestly.

Its task-agnostic design uses an exact contract, explicit non-solutions, a
mechanism-level approach registry, delayed cross-pollination, problem-derived
adversarial checks, failure-driven new waves, and repeated root synthesis.

## 1. Controlling Standard

No search instruction can lower the project's proof standard.

- A theorem is closed only when every substantive step is proved here,
  reduced to an exactly stated and checked source theorem, or verified by an
  identified formal or computational method.
- Every mathematical object and result carries a status.
- Every object records the ambient theory and type; cohomology or homology
  groups record coefficients, and weighted or twisted theories record their
  twists or weights when relevant.
- Every problem-specific degree, parameter, coefficient, sign, support,
  variance, normalization, and type check is a proof obligation, not editorial
  cleanup.
- An analogy between mathematical settings may generate an approach but cannot
  close a proof step without the exact comparison input.
- Proof generation and proof certification are separate roles. A generator
  never certifies its own route.
- Store auditable artifacts and concise decision rationales, not private
  chain-of-thought.

## 2. Orchestration Profiles

Every proof or refutation task uses one explicitly recorded profile.

### 2.1 `LIGHT`

Use `LIGHT` only when all of the following hold:

- the task is one bounded claim, local lemma, calculation, or isolated repair;
- at most one proof family is being developed;
- no parallel or external-model portfolio is being launched;
- there is no `GS3` or `GS4` gap, incompatible formalism choice, novelty claim,
  or proposed protected-ledger promotion;
- the exact target, obligations, attack checks, and provenance fit naturally in
  one proof-attempt artifact plus one independent verifier report.

`LIGHT` does not require standalone approach-registry, machine-state, or round
reports. The proof attempt must still state the typed target, proof obligations,
applicable attack checks, exact gap, sources, and profile. Any candidate still
requires a decisive `I3` verifier; `LIGHT` lowers paperwork, not proof standards.

### 2.2 `FULL`

Use `FULL` when any of the following holds:

- the target is an open problem, intended main theorem, research-level-3 task,
  or major proof repair;
- two or more mathematical families, agents, external-model runs, or
  incompatible formalisms are being compared;
- a `GS3` or `GS4` gap, multi-round search, blind/project-aware partition,
  literature/novelty claim, or protected-ledger promotion is in scope;
- the root needs dynamic allocation, blocking/reopening, cross-pollination, or
  durable search-state handoff.

`FULL` uses the complete scaffold below. A `LIGHT` run upgrades immediately to
`FULL` when any trigger appears; record the transition and preserve the earlier
artifact as provenance. Do not downgrade `FULL` merely to avoid recording a
failed or blocked route.

### 2.3 Canonical Mutable State

In `FULL`, `proof_search_state.yaml` is the canonical mutable record for current
round, mode, route IDs, route statuses, highest mathematical gaps, closure
gates, immutable target and candidate IDs/content digests, generator/repair run
IDs, route transition history, and verifier assignment. `approach_registry.md` is
the auditable narrative and evidence view: it explains mechanisms, decisions,
lineage, and mathematical reasons, and must be updated to agree with the state
file at every checkpoint. Mathematical proof and source artifacts remain the
authority for mathematical content; neither state file nor a valid manifest
certifies a theorem. SHA-256 binds recorded bytes but does not authenticate who
created them, whether an information boundary was honestly respected, or
whether the mathematics is correct. Structural validation checks the current
record's internal consistency only.

## 3. Required Inputs Before Round 1 (`FULL`)

The root coordinator must prepare the following before launching a broad
search. If an item is unknown, record it as an explicit obligation rather than
silently choosing a convention.

1. **Exact target.** Quantifiers, hypotheses, conclusion, ambient categories,
   coefficients, twists, degree conventions, support theory, and edge cases.
   Assign a stable target ID, store the target artifact in the dossier, and
   bind both by SHA-256 in `target_binding`. Changing the statement or
   hypotheses creates a new target ID/digest and invalidates candidate,
   verifier, closure, reopen, and exhaustion records bound to the old target.
2. **Acceptance criterion.** What exact artifact would constitute a proof,
   disproof, classification, or conditional result.
3. **Anti-target list.** Nearby statements that do not solve the task: special
   cases, strengthened hypotheses, wrong coefficients, an analogy, finite
   computation, or a reduction to an unresolved statement.
4. **Proof-obligation table.** Known dependencies and compatibility gates.
5. **Attack surface.** An instance of `templates/attack_surface.md`.
6. **Approach registry.** An instance of `templates/approach_registry.md`.
7. **Search mode.** Blind, literature-aware, or a documented transition
   between them.
8. **Resource checkpoint.** A round, time, or token checkpoint at which the
   root must report state. A checkpoint is not permission to invent success.

## 4. Search Modes

### 4.1 Blind Discovery Mode (`BLIND_GENERATION`)

Use blind mode to reduce anchoring and obtain genuinely independent
formulations.

- Give generators the exact problem contract and relevant definitions.
- Do not give most generators the favored approach, another generator's
  draft, or a claimed solution.
- A working instruction such as "search under the hypothesis that an
  affirmative proof may exist" is allowed for generators only. It is not
  evidence and must not appear in verifier prompts.
- Blind-mode outputs cannot support a novelty claim, a literature-status
  claim, or an unchecked imported theorem.
- Record which sources and prior approaches each agent saw.

### 4.2 Literature-Aware Mode (`LITERATURE_AWARE`)

Use literature-aware mode to check status, terminology, exact source
hypotheses, and whether a proposed mechanism is already known.

- Prefer primary sources and exact theorem/page references.
- Separate discovery of a mathematical mechanism from verification that a
  cited theorem has the needed hypotheses, coefficients, twists, and maps.
- Do not treat search snippets, abstracts, or model summaries as sources.
- Do not call a result new until the literature and terminology checks are
  recorded.

### 4.3 Transition Rule

The usual order is blind discovery followed by literature-aware audit. The
root records the transition in the round report. Information learned after the
transition does not retroactively make later agents independent of it.

`PROJECT_AWARE` branches may inspect existing project attempts and ledgers.
`VERIFICATION` branches receive the frozen candidate and attack surface but do
not receive generator optimism or intended repairs. Use
`MIXED_WITH_PARTITIONS` only when these information boundaries are recorded per
branch.

## 5. Roles and Independence

### Root coordinator

Maintains the task contract, approach registry, attack surface, round reports,
and proof obligations. The root allocates work, deduplicates approaches by
mechanism, identifies blockers, commissions audits, and makes status changes.
The root may synthesize a candidate, but then cannot be its decisive verifier;
decisive proof certification requires a separate `I3 BLIND` audit.

### Generators

Return concrete lemmas, constructions, equations, reductions, computations,
or counterexamples. A status report or a restatement is not a useful return.

### Counterexample and boundary-case searchers

Try to falsify the exact target and intermediate lemmas. They receive no
instruction that the target is true.

### Proof verifiers

Audit the complete logical argument, including hidden uses of the target,
type checks, edge cases, and reduction preservation. A verifier must disclose
its independence lineage using the levels below.

### Source verifiers

Check imported results against primary sources. They verify the exact statement
used, not merely that a paper contains related words.

### Independence levels

- `I0 SELF`: authored or materially repaired the route. Cannot certify it.
- `I1 ENTANGLED`: participated in its family, synthesis, or prior critique.
  May advise but cannot be the decisive verifier.
- `I2 SEPARATE`: did not author the proof but saw favored-route history or
  related drafts. Useful secondary audit.
- `I3 BLIND`: received the exact target and candidate proof, but not generator
  optimism, hidden intended repairs, or the instruction to assume truth. This
  is the mandatory decisive proof-verifier level.

`I3` is not a self-declared label. The machine state must record structured
originating-run and material-repair IDs, a hash-bound candidate-lineage
artifact, and a verifier exposure log naming the immutable target and candidate
IDs/digests. Before assignment, freeze a
`templates/dependency_snapshot_manifest.yaml` instance containing the candidate
route, its complete transitive ancestry, reciprocal parent edges, and every
inherited-gap ID and discharge record. Then freeze a
`templates/audit_packet_manifest.yaml` instance binding that snapshot, the
target, candidate, lineage, and the three closure-evidence roles and their typed
manifests. `templates/verifier_exposure_manifest.yaml` must bind this exact
audit packet and enumerate every packet role/path/digest; the verifier sees that
packet, not an informal approximation. The verifier run ID must be disjoint
from every generator and material-repair ID and must not be recycled from a
historical `I0`-`I2` audit of the candidate.

The final prose report is paired with
`templates/verifier_report_manifest.yaml`. For machine closure, that manifest
is the authoritative structured verifier record: it binds the same audit
packet and exposure record, plus verifier, target, candidate, verdict, highest
gap, objections, repairs, checked obligation/attack IDs, check summaries, and
report digest. The prose report remains required and must repeat those
canonical verdict fields without contradiction. A prose report alone, a
manifest alone, or a disagreement between them cannot satisfy the decisive
gate; structural agreement still does not prove that the verdict is
mathematically correct or that the named run is authentic.

A proof candidate needs at least one `I3` proof audit. If it imports
substantive literature, it also needs a source audit by someone who did not
invent the citation. High-risk claims should receive two audits using
different checking strategies. Repeated agreement by descendants of one
approach is not independent confirmation.

## 6. Idea Fingerprints and Portfolio Diversity

### 6.1 Family-generation operators

When the initial portfolio is not supplied by domain experts, seed genuinely
different families by selecting several applicable operators below. Do not
assign all operators mechanically; choose those that change the mathematical
burden of the target.

1. **Representation change.** Translate the target into a different category,
   complex, flow, spectral sequence, linear system, moduli problem, or universal
   property. State both directions needed to return to the original target.
2. **Structural decomposition.** Use induction, minimal counterexamples,
   cut/decomposition theory, stratification, localization, or reduction to
   indecomposable objects. Audit preservation of every later hypothesis.
3. **Invariant or obstruction.** Search for a quantity that must vanish, be
   conserved, lift, descend, or classify the desired structure. Ask separately
   whether it is complete or only necessary.
4. **Duality and adjunction.** Recast the target through a pairing, trace,
   universal coefficient statement, transpose map, or representability
   property. Make compatibility of the two formalisms a named obligation.
5. **Local-to-global or gluing.** Solve local pieces and identify the exact
   cocycle, descent, transition, boundary, or obstruction condition. Never
   assume compatible local choices globalize.
6. **Extremal or minimal-witness analysis.** Assume a smallest failure and
   derive forced structure; in parallel, search small examples for the first
   place the forced property breaks.
7. **Computational micro-experiments.** Enumerate or symbolically test small
   cases to discover invariants, counterexamples, or sharp hypotheses. Record
   the mathematical model and treat finite evidence as conjecture generation,
   not proof.
8. **Lemma inversion and hypothesis ablation.** Negate the decisive lemma,
   remove hypotheses one at a time, and seek witnesses. This often reveals the
   minimal repair or shows that a proposed lemma is target-strength.
9. **Source-theorem mining.** In literature-aware mode, search for a theorem
   that closes a precisely typed `GS2`/`GS3` gap. The branch must return the
   exact statement and applicability check, not a theorem name.
10. **Formalization or checker-driven search.** Encode the fragile local core in
    a proof assistant, exact algebra system, SAT/SMT model, or certified
    computation when feasible. Start with the smallest vertical slice that can
    test the encoding and one load-bearing lemma before expanding to a whole
    theorem or manuscript. Use checker failures to isolate obligations; do not
    mistake formalization plans, code volume, or a successful build for a check
    of the intended informal statement. When the `formalization` module is
    enabled, follow `workflows/lean_room_protocol.md` for the stricter build,
    trust-boundary, correspondence, and certificate gates.
11. **Synthesis from orthogonal partial results.** Combine parent families only
    after their fingerprints and gaps are recorded. Require a new compatibility
    mechanism; juxtaposition alone is not a new family.

Every seed family must specify:

- the operator and actual mathematical mechanism;
- the first lemma, construction, equation, counterexample, or certificate it
  will return;
- the cheapest discriminating test that could kill the route;
- how success would reduce the burden relative to the frozen target;
- why it does not inherit the favored route's decisive lemma.

If several rounds saturate one operator, seed the next round from an
underrepresented operator or attack the shared bottleneck directly. Random
paraphrase is not exploration.

### 6.2 Fingerprint rule

Every approach receives a fingerprint containing:

- core mathematical mechanism;
- principal objects or reformulation;
- invariant, construction, or bridge being exploited;
- reduction target;
- decisive new lemma;
- characteristic dependencies and likely failure modes.

Two writeups with the same mechanism and decisive lemma belong to one family,
even if their notation or exposition differs. Create a new family only when a
new invariant, construction, equivalence, source theorem, or local-to-global
mechanism changes the route's mathematical burden.

Before any family survives an adversarial audit, it should not consume more
than half of available generator capacity unless the round report records a
specific mathematical reason. Keep incompatible families alive long enough to
expose their real gaps. Cross-pollinate only after the independent returns
have been fingerprinted and recorded.

### 6.3 Semantic progress and stall control

Measure progress against the frozen target's dependency graph, not activity.
Counts of tokens, files, lines, helper lemmas, agent hours, or compiling local
fragments are resource data, not mathematical progress unless they close or
strictly reduce a named obligation.

At every substantive checkpoint record:

- the unchanged main target ID/digest and current load-bearing path;
- which named obligations became `GS0`, dropped in gap strength, were refuted,
  or acquired a genuinely new mechanism;
- which new lemmas lie on that path and where they are consumed;
- the fingerprint of the current blocker and any near-duplicate lemmas or
  equivalent reductions produced since the preceding checkpoint; and
- the next discriminating action and the condition for stopping or pivoting.

A family is in **semantic stall** after two consecutive substantive
checkpoints with the same load-bearing blocker fingerprint and none of: a
closed obligation, a strict gap-strength reduction, a counterexample, an exact
source closure, or a genuinely new mechanism. Semantic stall is a review
trigger, not a prohibition on the route. The coordinator should normally pause
same-mechanism generation. It may instead continue one bounded experiment if
it records the unchanged blocker, a specific mathematical reason, the
discriminating observation sought, and a stop condition. Continuing neither
resets the stall count nor upgrades route or theorem status. Useful
interventions include:

1. an independent audit that identifies a narrower repair;
2. a detailed informal expansion of an omitted or supposedly standard fact,
   with every interface and dependency made explicit;
3. a representation or mechanism pivot that changes the mathematical burden;
4. a checked formal/computational result that closes the exact blocker; or
5. an explicit stop decision preserving the strongest residual result.

A high-level human directional prompt is valuable steering and must be logged
with its effect on the portfolio, but it is not proof evidence. Rephrasing the
same blocker, adding adjacent lemmas, or assigning more agents to the same
fingerprint does not reset the stall count.

## 7. Gap-Strength Classification

Every unresolved step receives exactly one current class.

- `GS0 CLOSED`: proved, exactly imported, or formally/computationally checked.
- `GS1 LOCAL`: a bounded calculation, omitted case, or exposition-level lemma
  with a clear proof plan that does not change the mechanism.
- `GS2 SOURCE`: the mathematical reduction is clear, but an exact source,
  hypothesis, compatibility, coefficient, twist, or map statement is not yet
  verified.
- `GS3 SUBSTANTIVE`: a genuinely new lemma is required, but it is strictly
  narrower than the target and has an independently testable formulation.
- `GS4 TARGET_STRENGTH`: the missing lemma is equivalent to, follows back from,
  or is of essentially the same global strength as the target, or the route uses the
  target circularly. Do not assign `GS4` merely because a sufficient lemma
  implies the target; require a reverse reduction or an explicit failure to
  reduce quantifiers, scope, structural complexity, or the decisive burden.
- `GS5 FATAL`: a counterexample, type error, incompatible hypotheses, false
  indispensable import, or contradiction destroys the route in its recorded
  form. A wrong but replaceable citation remains `GS2` until the underlying
  mathematical statement is shown false or unavailable.

`GS1` triggers a repair task. `GS2` triggers source and compatibility checks.
`GS3` becomes a named subproblem with its own attack surface. `GS4` blocks the
route. `GS5` refutes or supersedes it. Elegant language never lowers a gap
class.

## 8. Approach Statuses and Blocking Rules

Allowed approach statuses are:

- `SEED`: fingerprinted idea not yet developed;
- `ACTIVE`: assigned and producing concrete work;
- `CANDIDATE`: end-to-end argument claimed, not yet certified;
- `UNDER_AUDIT`: frozen candidate being independently attacked;
- `BLOCKED`: no meaningful progress without closing a recorded blocker;
- `REFUTED`: route fails by a checked `GS5` issue;
- `MERGED`: useful components moved into another identified route;
- `PARKED`: low-priority but not mathematically blocked;
- `CLOSED_PROOF`: all obligations and audits passed;
- `CLOSED_COUNTEREXAMPLE`: exact target refuted by a verified example.

Block a route when its best remaining step is `GS4`. A `GS3` obligation should
normally become an active named subproblem while the parent route is parked or
blocked at that dependency. If two targeted returns have the same fingerprint
and produce no new lemma, construction, witness, source, or falsification
result, record the repetition and stop allocating duplicate capacity. A blocked route
may reopen only if the registry records one of:

1. a new mechanism that demonstrably reduces the blocker's quantifiers, scope,
   structural complexity, or decisive burden;
2. an exact source theorem that closes the blocker and matches all hypotheses;
3. a verified reformulation that makes the blocker strictly narrower;
4. a direct in-project proof, formal certificate, or checked computation that
   closes the exact blocker without changing the claim.

More agents, renamed notation, vague optimism, or another equivalent reduction
do not reopen a route. A `REFUTED` route is not reopened; a materially changed
route receives a new ID and links to the refutation. A changed target or
hypothesis always creates a new claim ID; it is never recorded as reopening the
old route. Every route carries a transition history. New routes begin at
`SEED`; imported historical routes use the explicit `HISTORICAL_BACKFILL`
initialization together with a target-bound
`templates/historical_backfill_manifest.yaml`. The manifest binds the problem,
target ID/digest, route, initial status, backfill time, and a nonempty list of
source artifacts and digests that includes the transition's own evidence
artifact/digest. It records the provenance actually supplied; it does not
license replacing or deleting a known earlier transition chain. The
allowed transition graph and nondecreasing round numbers are checked, and the
final transition must equal the current route status. A
transition out of `BLOCKED` records one of the four authorized bases and a
`templates/reopen_manifest.yaml` instance binding the route, exact blocked gap
ID/class/statement digest, basis, resulting status/candidate, and evidence
artifact/digest. A generic transition report is not reopening evidence.

The structural validator checks the transition chain present in the current
snapshot, including a backfill manifest's target and source bindings. It cannot
prove that an editor never deleted older events or substituted a shorter
history before validation; repository history, review, or an external
append-only anchor remains the deletion-detection boundary. Never rewrite or
delete a prior transition to manufacture a legal reopen or backfill.

## 9. The Root Round Loop

For each round, create `templates/search_round_report.md` and execute these
steps in order.

### Step A: Reconfirm the contract

Record whether the target, conventions, sources, or anti-targets changed. A
mathematical change requires explicit provenance and must not be hidden inside
an approach.

### Step B: Audit portfolio diversity

Group active agents by idea fingerprint. Redirect duplicated capacity toward
underexplored families, counterexamples, or source verification.

### Step C: Dispatch bounded assignments

Each assignment asks for a concrete artifact and names its permitted inputs,
mode, target obligation, and expected falsification checks.

### Step D: Intake and normalize

Extract claims, lemmas, constructions, citations, examples, and gaps. Check
types before synthesis. Assign statuses and provenance. Deduplicate by
fingerprint rather than wording. Link every claimed progress item to a named
main-path obligation; classify unconsumed adjacent lemmas as activity until a
dependency edge is exhibited.

### Step E: Attack before promotion

Run the highest-priority tests from the attack surface. A candidate is frozen
while under audit; repairs produce a new candidate version and invalidate old
verdicts affected by the change.

### Step F: Classify gaps and decide

For every route, record `continue`, `target_gap`, `audit`, `block`, `refute`,
`merge`, or `park`, with a concise mathematical reason. Launch a new round only
for assignments that differ by mechanism, obligation, source, or attack.

Apply the semantic-stall rule from Section 6.3. Two consecutive checkpoints
with an unchanged load-bearing blocker and no named dependency reduction
trigger a same-family review even if the amount of prose, code, or helper
lemmas grew. Normally pause; a bounded continuation remains available under the
recorded-rationale, discriminating-test, and stop-condition rule in Section
6.3.

For every blocked or refuted route, extract the weakest false or unsupported
lemma, the obstruction/witness, and one new discriminating question. Use these
failure artifacts to seed a redirected wave from an underrepresented
family-generation operator. During every live generation round, keep at least
one exploration or refutation function alive until a candidate enters decisive
audit. An `AUDIT_CANDIDATE` checkpoint may pause all agents; if generation
resumes before audit assignment, reactivate that branch.

### Step G: Synthesize cautiously

Cross-feed only recorded artifacts. A synthesis must list parent approach IDs
and structured inherited-gap records. Merge edges are reciprocal: a route with
status `MERGED` names its survivor in `merged_into`, and that survivor lists the
merged route in `parent_route_ids`. Enumerate every non-`GS0` parent gap
separately in the child with the same source route, gap ID, class, and
exact-statement digest. Closing one inherited gap requires its own target-bound
`templates/gap_discharge_manifest.yaml` instance with exactly one allowed
`discharge_basis` (`DIRECT_PROOF`, `EXACT_SOURCE`, `FORMAL_CERTIFICATE`, or
`CHECKED_COMPUTATION`) and an evidence path/digest whose artifact names the
source gap ID and statement digest. A blanket merge note cannot discharge
several gaps. A child with any open inherited gap cannot be `GS0` or closed;
relabelling the inherited gap `GS0` is not a discharge.

### Step H: Check termination gates

Use the rules below and record the outcome even when the search continues.

## 10. Promotion and Closure Gates

### Independent final verifier gate

The decisive final verifier must be informationally and procedurally independent
from generation and material repair, with information lineage recorded below.
A self-audit may improve a candidate but cannot satisfy this gate. Publication
or exceptionally high-risk claims may additionally require an external human,
different model family, or formal checker, but those are separate evidence
requirements rather than the definition of `I3`.

An independent verifier must reconstruct and attack the frozen candidate rather
than merely confirm the generator's intended repair.

An approach can move from `CANDIDATE` to `UNDER_AUDIT` only if it has:

- a normalized exact statement;
- an end-to-end proof artifact;
- a complete dependency and obligation list;
- degree/coefficient/twist/type tables where relevant;
- explicit treatment of the attack surface's mandatory cases;
- pairwise-distinct proof-obligation, source-audit, and attack-surface-exit
  evidence artifacts, each paired with its role-specific typed manifest;
- a complete dependency snapshot and one immutable audit packet binding the
  target, candidate, lineage, all three evidence roles/manifests, and their
  digests;
- no known `GS3`, `GS4`, or `GS5` gap. Explicit `GS1` repairs and `GS2` source
  checks may remain audit targets, but they must not be relabelled `GS0` merely
  to enter audit.

It can move to `CLOSED_PROOF` only if:

- every substantive obligation is `GS0`;
- the stable target ID/artifact/SHA-256 and canonical candidate
  ID/artifact/SHA-256 agree across state, lineage, exposure, verifier, and
  closure records;
- at least one decisive proof verifier is `I3`;
- imported theorems and citations have passed source audit;
- counterexample and boundary-case searches found no unresolved failure;
- the final theorem states the exact proven scope and exclusions;
- any novelty claim has a separate literature and terminology audit.

A proof-assistant build or formal certificate contributes only the exact
encoded declaration and assumptions named by its evidence. It does not satisfy
the informal theorem gate unless an independent correspondence audit binds the
formal objects, quantifiers, hypotheses, conventions, edge cases, and required
direction back to the frozen target. A material post-build refactor creates new
source identity and requires a fresh build, trust-boundary check, and affected
correspondence audit. Maintainability or library quality is a separate status
from mathematical correctness.

The closure is represented by `templates/closure_manifest.yaml`. The three
pairwise-distinct evidence artifacts use
`templates/proof_obligations_manifest.yaml`,
`templates/source_audit_manifest.yaml`, and
`templates/attack_surface_exit_manifest.yaml`; each manifest binds its role,
target/candidate IDs and digests, underlying artifact/digest, and role-specific
closure facts. The dependency snapshot is bound into the audit packet; the
same audit packet is then bound into exposure, the authoritative structured
report manifest, and closure. The closure manifest also binds lineage, prose
exposure/report artifacts, verdict, highest gap, and open-obligation list.
Substituting one evidence role for another, reusing one polyglot artifact for
several roles, or renaming an exposure log as a report does not close the gate.

These bindings establish structural consistency and content identity only.
They do not authenticate platform run IDs, prove that withheld material was
actually withheld, certify source accuracy, or mechanically prove the theorem.
The `I3` report supplies an independent mathematical judgment; its correctness
still rests on the auditable argument and checks, not on schema validity.

An exact counterexample closes the target only after its hypotheses, computed
properties, and failure of the conclusion are independently checked.

## 11. Honest Termination

An honest residual outcome preserves the strongest rigorous result and exact
gaps without representing them as a solution of the frozen target.

Allowed terminal reports are:

1. `VERIFIED_PROOF`;
2. `VERIFIED_COUNTEREXAMPLE`;
3. `CONDITIONAL_RESULT` with the exact unproved assumptions;
4. `CHECKPOINT_INCOMPLETE` with the strongest rigorously established result,
   exact open gaps, failed routes, and next discriminating tests;
5. `EXHAUSTED_CURRENT_MECHANISMS` when all active routes are blocked or
   refuted and no materially new mechanism is available.

Do not select `EXHAUSTED_CURRENT_MECHANISMS` while any route is `SEED`, `ACTIVE`,
`CANDIDATE`, `UNDER_AUDIT`, or `PARKED`. The record must contain an initial-wave
report plus a `templates/search_wave_manifest.yaml` instance binding its target,
round, routes, mechanisms, failure artifacts, and report digest. It must then
contain either (a) a distinct redirected failure-driven wave report and typed
manifest after at least two rounds, or (b) an explicit waiver reason supported
by a canonical-operator assessment and a target-bound waiver manifest.

A redirected manifest must bind its parent initial-wave manifest/digest, use a
strictly later round, name one or more triggering failure artifacts drawn from
that initial wave, and record a nonempty duplicate-free `mechanism_delta` every
entry of which is absent from the initial wave and included among the redirected
mechanisms tested. It must also state the new discriminating question. Renaming
or exactly repeating the first wave is not redirection.

A waiver uses `templates/waiver_assessment_manifest.yaml` to assess every
canonical discovery operator exactly once—`REPRESENTATION_CHANGE`,
`STRUCTURAL_DECOMPOSITION`, `INVARIANT_OBSTRUCTION`, `DUALITY_ADJUNCTION`,
`LOCAL_TO_GLOBAL`, `MINIMAL_WITNESS`, `COMPUTATIONAL_MICROEXPERIMENT`,
`HYPOTHESIS_ABLATION`, `SOURCE_THEOREM_MINING`, `CHECKER_FORMALIZATION`, and
`SYNTHESIS_NEW_COMPATIBILITY`—as `TESTED`, `UNAVAILABLE`, or
`NOT_APPLICABLE`, with a nonempty reason. The assessment binds the frozen
target, initial-wave manifest, and exact impossibility claim; it is the waiver
evidence. `templates/redirected_wave_waiver_manifest.yaml` binds that same
assessment and reason; its `unavailable_operators` is exactly the operators
whose assessment status is `UNAVAILABLE` or `NOT_APPLICABLE`. An unrelated file
or a hand-written operator list cannot serve as exhaustion evidence.

A resource limit, failed first wave, or instruction to persist does not turn a
partial argument into a theorem. Conversely, honest termination does not erase
useful progress: preserve proved lemmas, counterexamples, exact blockers,
source checks, and the approach registry.

Do not write to protected ledgers merely because a search ended. Propose any
theorem-status or architecture change for approval under the project's normal
rules.
