# Claude Code terminal workflow

This integration is optional. New labs start disabled unless their generation
request includes `"integrations": {"claude_terminal": {"enabled": true}}`.
The initial choice remains in `LAB_PROFILE.json`; the current switch lives in
`config/integrations.json`. Codex can change that boolean when the user requests
Claude work or asks to disable it. Do not edit the historical bootstrap digest.

With the switch off, ordinary research, memory and all offline checks still work.
The installed adapter stays available but local preparation and launch are
blocked. Status, collection and explicit stop remain available. Disabling does
not kill a running session or revoke an exported packet's separate authorization.
The installed adapter uses the laboratory's integration switch. An exported
packet's own bound runner uses its separately sealed release and ignores unrelated
configuration above the packet, such as `/Users/Shared/config/integrations.json`.
No provider, login or model call is needed to generate or validate a lab.

Codex prepares, reviews, launches, resumes and collects a finite Claude CLI
session. The user need not open another chat or transfer folders. The request
selects model, effort, public web access, outputs and exact input files; no
particular model or host direction is a universal research requirement.
The implemented adapter is Codex → Claude CLI. Claude → Codex is not implemented.

## Existing sessions and implementations

An existing authorized CLI session continues with its original recorded runner,
config and session ID. Do not overwrite bound scripts, active pointers, packets,
release reviews, partial files or native histories. Existing working CLI adapters
remain usable. Use the portable runner below for a new lab or when only the old
manual adapter was installed. Do not silently fall back to the manual bridge.
Historical manual records remain readable; do not create new manual exchanges
or relaunch an old job as if it were the same CLI session.

## New finite round

1. Agree on one exact task and necessary context. Author a local request from
   `templates/claude_terminal/request.json`. Fix explicit model/effort, required
   output names and selected files. Set `max_wall_seconds` (default 3600) and
   `max_output_bytes` (default 67108864, 64 MiB). The template is not authorization. One session
   is the default; additional sessions require a concrete research rationale.
   `public_web` starts false. Set it true only when public research reading is
   authorized for this exact round; enabling the integration alone does not
   enable web access. Self-contained work can keep it false.
2. Use a new private packet strictly below `/Users/Shared/math-research-cli/`
   and a neutral per-lab ID. This fixed path is part of the current macOS adapter.
   The neutral root and every directory below it through the packet must belong
   to the current user and must not be writable by group or others. The runner
   creates new intermediate and packet directories with mode `0700`.
   Do not expose personal home paths, full laboratories,
   conversations, settings or native session histories. Review PDF/binary contents
   and source provenance separately. Automated marker screening covers only
   `.txt`, `.md`, `.json` and `.html`; it does not screen `.tex`, `.yaml`,
   `.bib`, `.py` or other extensions. Review the actual bytes of every selected
   file regardless of extension. Screening is not anonymization, secret removal
   or permission to release a file.
3. Prepare locally:
   `python3 -B scripts/claude_terminal/claude_runner.py prepare REQUEST PACKET --research-draft`.
   Record exact target, inputs, hashes and privacy review in this laboratory.
4. On the user's instruction to run this agreed task, check CLI `preflight()` on
   the host, using the runner's sanitized environment. This checks flags and an
   existing first-party subscription; retain only sanitized observations.
   A sandbox login failure is not evidence that the user must log in again.
   Never use API keys, paid-overage activation or automatic model fallback.
5. Make an exact-byte local release review. `files` contains input_hashes,
   support_hashes, manifest.json SHA-256 and runner.py SHA-256. Record actual
   privacy_reviewed, reviewer, notes, live_test_approved, approval_source,
   subscription_auth_verified; research additionally requires research_approved,
   technical_acceptance, rules_checked and archive_approval_event. These attest
   completed checks and the existing user request, not a second approval ritual.
   Release with `python3 -B scripts/claude_terminal/claude_runner.py release PACKET REVIEW`.
6. Create a new local `runs/<round-id>/` record directory; write
   `runs/claude-terminal-active.json` with `packet` (absolute neutral path) and
   `record_directory` (lab-relative runs path). Never replace an active session
   without checking its completion/stop state and preserving the earlier pointer.
7. Start with `python3 -B scripts/claude_terminal/claude_cli_launch.py`.
   Check `--status` to confirm the real session and requested/observed model.
   No automatic background quota checking. Launching one finite process is not
   authorization to schedule further rounds.

## Interruption and collection

The wall-clock limit covers one explicit invocation, including its tasks and
automatic output repairs. At expiry the runner stops its process group, preserves
available partial output and records `paused/time_limit`. An explicit later run
gets a fresh time budget and resumes the same observed session. The time limit
is elapsed wall time, not a paid-token budget or active model-compute measure.

The output limit counts packet objects, visible records and current output,
including previous attempts. Resume does not reset that count. This is a
monitored ceiling, not an OS disk quota: files can grow between checks. If the
limit is reached, the runner stops with `paused/output_limit`. Oversized current
files remain in the packet; the bounded collection contains only preserved
snapshots and marks incomplete coverage. Do not delete evidence or silently
raise a bound. The exhausted packet keeps its cumulative ceiling; resuming it
may immediately hit the same limit again.

After an output-limit pause, collect the available snapshots and save a checkpoint
of useful progress, missing output and the next bounded task. If the user later
explicitly authorizes a new bounded round, Codex may prepare a new packet using
only selected saved artifacts needed for that task. Keep the original packet
intact. In the new local round record, link the predecessor packet ID, collection
digest and checkpoint; state in the new prompt that this is a continuation from
saved artifacts in a new session, not a resume of the old session. Review the
selected bytes and the new bounds, then use the ordinary preparation and release
workflow. This is a separate authorized round, never an automatic restart or a
way around a provider quota. No new packet is created merely because a limit was
reached, and the existing packet's cumulative ceiling remains unchanged.

A quota/provider interruption preserves the exact session and partial files.
Resume only on user request using the same launch command; never create another
session to evade a quota. Explicit stop: `claude_runner.py stop PACKET`.
A later user resume permits `claude_cli_launch.py --resume-stopped`; never clear
STOP.json by hand. Uncertain launch or duplicate process requires inspection.

After the runner exits, collect with
`python3 -B scripts/claude_terminal/claude_runner.py collect PACKET NEW_LOCAL_QUARANTINE`.
This copies selected visible output, sources, configuration observations and
versioned artifacts into an immutable hash-bound collection. Never execute
returned code during ordinary intake. Use the laboratory's existing intake and
checkpoint/archive protocol. In mathematical labs claims remain UNKNOWN and
UNVERIFIED_EXTERNAL_OUTPUT / MODEL_INFERENCE until independent verification;
in other labs preserve their own honest candidate/assessment vocabulary.
Preparation and mechanical acceptance are not proof, novelty or human review.

File tools and optional public WebSearch/WebFetch are exposed, without Bash,
agents, plugins or MCP. Proposed calculations require explicit execution support;
never invent a successful test. Public-source retrieval is separate from the
model's WebFetch summary; record unavailable sources honestly.

The runner records its capture authority under
`records/source-captures/<task>/<url-hash>.json`, outside the model's assigned
work directory. `output/sources/` is a readable mirror: its receipt alone never
skips retrieval or establishes provenance. Reuse requires the runner-owned
receipt and exact artifact hashes to match; changing both an output receipt and
its text still fails validation. The existing collection includes these records.
This assumes the runner-owned packet records remain outside the model's granted
write scope; it is not hostile-host isolation or proof of source accuracy.
A failed retrieval is recorded as unavailable, not as captured source evidence.
Only files enumerated by a matching runner capture authority are bound as bytes
from direct retrieval. Other files, including native-observation PDFs, remain
unverified attachments unless covered by that authority; placement in
`output/sources/` does not certify source capture or provenance.

Account identity
and native restricted mode are not a VM or anonymity guarantee. No credentials,
private reasoning or arbitrary native transcript scans enter collected evidence.

For mathematical `research_checks: true`, `source-status.json` describes what
was actually used. A self-contained task may use:

```json
{"sources": [], "no_external_sources_reason": "Self-contained argument using only the supplied definitions."}
```

The explanation must be nonblank (at most 4096 characters). Do not invent a
citation or enable web search to satisfy a form. When external sources were
used, keep `sources` rows with url, coverage (full/excerpt/summary/unavailable),
note, and an existing stage-relative artifact for full/excerpt. These coverage
rows are model declarations: an existing artifact alone does not establish that
a server supplied its contents or that Claude read it fully. Runner capture
authorities separately bind the bytes observed by direct retrieval; they do not
prove source accuracy, reading coverage or mathematical correctness. For unrelated work,
choose the actual task's acceptance criteria.

## Codex intake into existing laboratory memory

`collect` returns `collection_sha256`, the digest of the collected
`collection.json`. Codex uses that exact value, rather than trusting filenames
or executing the collected runner. For example, with a collection already
under `research/attempts/round/collected` (create its parent first):

```sh
python3 -B scripts/claude_terminal/claude_collection_intake.py inspect \
  --collection research/attempts/round/collected --collection-sha256 SHA256
python3 -B scripts/claude_terminal/claude_collection_intake.py materialize \
  --collection research/attempts/round/collected --collection-sha256 SHA256 \
  --output research/attempts/round/evidence
```

Replace `SHA256` with the returned digest. The new evidence directory must not
exist. The helper verifies receipt, file, snapshot, object and release bindings;
it works with old collected runners without importing or executing their code.
It reads at most 128 MiB, 32 MiB per file and 4096 files by default. A deliberately
larger local intake can set `--max-total-bytes`, `--max-file-bytes` and
`--max-files`; do not silently increase them after a failed read. Hashes show
byte consistency, not independent provenance or correctness.

Codex reads `evidence/intake.json` and the selected named artifacts. If output
changed after acceptance, the report distinguishes accepted and latest versions;
it never silently substitutes one for the other. A missing final report is not
a reason to discard useful progress. Partial, timed-out and quota-interrupted
attempts retain `UNVERIFIED_EXTERNAL_OUTPUT`. Checkpoint only the evidence
actually read and describe missing or incomplete output explicitly.


Use the philosophical laboratory's existing archive and round protocol.
Codex starts a local intake round with `philosophy_round.py start`, binding the
collection and selected artifacts as inputs. Capture Codex's actual reading and
intake segment with `capture_codex.py`, then write the ordinary semantic summary
and checkpoint with `--incomplete` and that run's real coverage IDs. Run the
existing refresh/validation commands. See `workflows/ROUND.md` and
`docs/CAPTURE.md` for their CLI arguments.

Do not manufacture a Claude-native capture record from collected files or label
an intake segment a completed five-stage round. The archive records the actual
scope and limitations; full philosophical assessment remains a separate round.

## Communication

Every proposed next action explicitly names Codex or Claude. End each workflow
status/result with very short `Codex: ...` and `Claude: ...` lines. State "no run
needed now" when appropriate. Distinguish process elapsed time from active
model computation and unverified findings from accepted results.

## Tests

`make claude-terminal-test` runs synthetic offline tests. No real model calls,
subscription changes or live-session migration occur during installation/tests.
