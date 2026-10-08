# One small complete cycle

This protocol launches no model, paid API, task or background process. The agent
performs ordinary explicit work inside this lab, captures original records at
each boundary, and uses the helper to save exact artifact versions.

1. Read START_HERE, current resume, active method and applicable profile. For a
   competition round, recheck official rules and use an appropriate fresh
   context. Keep the historical planning catalog outside default research input.
2. Probe only the current exact session using capture_codex.py; consult CAPTURE.
   A failing/unavailable collector must be resolved before dependent work, or the
   segment is explicitly incomplete. Never claim full Desktop recording.
3. Start with a unique run ID, actual session ID, purpose and explicit inputs:
   `python3 scripts/philosophy_round.py start --run R001 --session ACTUAL_ID --purpose research --input RELATIVE_SOURCE`
   Exact method/instructions/configuration/inputs become immutable object refs.
   Supply `--stage-id` and `--selection-round-id` for the actual project phase and
   selection cycle. A changed configuration creates a new linked lab epoch;
   `--epoch-event` may name a previously recorded matching epoch. Never reuse an
   epoch label to conceal a changed method or helper implementation.
4. AI selects or sharpens one question. Save its exact output artifact, capture
   its original message/tool event, then record it:
   `python3 scripts/philosophy_round.py record --run R001 --stage question --file notes/question.md --session ACTUAL_ID --evidence CAPTURE_EVENT_ID`
5. Read relevant primary sources. Preserve exact accessed text/files needed to
   reconstruct the argument, URL, access time, locators, quote limits and gaps.
   Record stage `sources` with `--source-note` describing actual retrieval.
   User-provided or unreachable content remains labelled accordingly.
6. Develop one AI contribution with explicit premises, conclusion, uncertainties
   and source dependencies. Save and capture before recording `contribution`.
7. Obtain actual AI critique in a separate context. Supply the exact question,
   source and contribution versions. Preserve the original answer and its
   session capture. Record `critique` with that distinct session ID. Do not
   invent critique, intellectual independence, model metadata or source checks.
8. AI records a decision and justification, including disagreement, failure and
   reopen triggers; a human selection is separately recorded as human input.
   Record `decision`. Supported stages stay in order; older attempts remain.
9. Capture the final bounded segment for each participant. Prepare one JSON
   checkpoint with nonempty fields: question, outcome (CONTINUE/REVISE/SET_ASIDE,
   or COMPLETE_TECHNICAL for a technical demo), contribution, criticism,
   limitations, next_step, method_change, comparability, coverage_boundary.
   `python3 scripts/philosophy_round.py checkpoint --run R001 --summary notes/checkpoint.json --coverage COVERAGE_ID --coverage CRITIC_COVERAGE_ID`
   This appends the canonical dated checkpoint and terminal. An explicit
   `--incomplete` checkpoint preserves an interrupted segment; it does not turn
   loss or an unknown outcome into success.

`pause --run R001 --reason TEXT` and `resume --run R001 --reason TEXT` record
stopping and continuation. After a crash, `research_archive.py recover` is an
audit; unresolved attempts remain unresolved. Do not rerun an external operation
just because its outcome is unknown. Examine exact history before retrying.

`refresh` rebuilds resume/checkpoint index/readable archive. Change a method by
writing a new immutable version and starting a new bound round; explain motive,
effective start, effect on comparison, and provenance link to the former round.
The five-stage engine accepts changed strategies within those stages. A new
stage topology requires a versioned protocol extension, without deleting history.

Register every new essay, thesis or idea with `research_timeline.py candidate`
before the next dependent step; see `docs/TIMELINE.md`. Bind its exact artifact,
run start, epoch, phase, selection cycle and origin/parent candidates. Preserve
birth-time uncertainty and distinguish independent ideas from merely parentless
records. Record rejection/reopening as new decisions. `research_timeline.py weekly`
builds the weekly schedule and candidate-origin table from the same archive.
Explicit activity observations preserve known model labels and wall intervals;
they never estimate hidden thinking time. These are private derived views, not
an authorized publication or a selected final exhibition design.

For a clean new lab, import the archive as historical evidence and explicitly
choose whether to link a new round to it. Scoped export includes causal closure
and exact object dependencies; review exclusions before any external release.
