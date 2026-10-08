PYTHON ?= python3
export PYTHONDONTWRITEBYTECODE := 1
TRUST_TIER ?= C
PROBLEM_ID ?=
CASE_ID ?=
ACTOR ?= lean-room-operator
GATE ?= LR0
RUNNER_ID ?= lean-room-builder
RUN_KIND ?= candidate
TIMEOUT ?= 600
REBUILD_TIMEOUT ?= 600
AUDIT_ID ?=
AUDITOR_ID ?=
AUDITOR_RUN_ID ?=
CANDIDATE_RUN_ID ?=
INDEPENDENT_RUN_ID ?=
VERDICT ?= PASS
HIGHEST_GAP_CLASS ?= GS0
ISSUED_BY ?= lean-room-coordinator
CERTIFICATE_ID ?=
ATTEST_EXACT_CORRESPONDENCE ?= --attest-exact-correspondence
LEAN_WORKSPACE ?=
DEPENDENCY_SNAPSHOT ?=
SNAPSHOT_ID ?=
SNAPSHOT_ACTOR ?= lean-room-snapshot-importer
DEPENDENCY_PROJECT ?=
DEPENDENCY_REVIEW ?=
PILOT_ID ?=
PILOT_RUNNER_ID ?= lean-room-dependency-pilot-runner
DECLARATION ?=
EXACT_FORMAL_TYPE ?=
PERMITTED_AXIOM_ARGS ?=
REQUIRE_LEANCHECKER ?=

.PHONY: doctor doctor-strict ingest index validate validate-proof-search proof-search-test eval resume snapshot new-problem improvement-proposal memory-record memory-index memory-validate memory-search memory-test room-status room-enable room-disable lean-freeze lean-validate lean-verify lean-audit lean-certificate lean-test lean-snapshot-import lean-snapshot-validate lean-snapshot-test lean-dependency-pilot lean-dependency-pilot-test

doctor:
	$(PYTHON) scripts/doctor.py

doctor-strict:
	$(PYTHON) scripts/doctor.py --strict-capabilities

ingest:
	$(PYTHON) scripts/ingest_sources.py 00_INBOX_TO_ANALYZE/priority --scope core --trust-tier "$(TRUST_TIER)"

index:
	$(PYTHON) scripts/build_source_index.py

validate: proof-search-test
	$(PYTHON) scripts/validate_lab.py
	$(PYTHON) scripts/validate_ledgers.py
	$(PYTHON) scripts/validate_proof_search.py

# durable-research-memory:v1
MEMORY_INPUT ?=
MEMORY_CHECKPOINT_PATH ?=
MEMORY_QUERY ?=

validate: memory-validate memory-test
eval: memory-test

memory-record:
	@test -n "$(MEMORY_INPUT)" || { echo "Set MEMORY_INPUT=<input-json-path-or->"; exit 2; }
	@test -n "$(MEMORY_CHECKPOINT_PATH)" || { echo "Set MEMORY_CHECKPOINT_PATH=research/checkpoints/<checkpoint-id>.md"; exit 2; }
	$(PYTHON) -I -B scripts/research_memory.py record --checkpoint-path "$(MEMORY_CHECKPOINT_PATH)" --input "$(MEMORY_INPUT)"

memory-index:
	$(PYTHON) -I -B scripts/research_memory.py rebuild-index

memory-validate:
	$(PYTHON) -I -B scripts/research_memory.py validate

memory-search:
	$(PYTHON) -I -B scripts/research_memory.py search $(if $(MEMORY_QUERY),--query "$(MEMORY_QUERY)",)

memory-test:
	$(PYTHON) -I -B tests/test_research_memory.py -v
# /durable-research-memory:v1

# repository-first-protocol:v1
REPOSITORY_OBSERVATION_ID ?=
REPOSITORY_RECORDED_AT_UTC ?=
REPOSITORY_PERIOD_START ?=
REPOSITORY_PERIOD_END ?=

.PHONY: repository-first-status repository-first-validate repository-first-test repository-first-observe

validate: repository-first-validate repository-first-test
eval: repository-first-test

repository-first-status:
	$(PYTHON) -I -B scripts/repository_first.py validate --json

repository-first-validate:
	$(PYTHON) -I -B scripts/repository_first.py validate

repository-first-test:
	$(PYTHON) -I -B tests/test_repository_first.py -v

repository-first-observe:
	@test -n "$(REPOSITORY_OBSERVATION_ID)" || { echo "Set REPOSITORY_OBSERVATION_ID=<id>"; exit 2; }
	@test -n "$(REPOSITORY_RECORDED_AT_UTC)" || { echo "Set REPOSITORY_RECORDED_AT_UTC=<YYYY-MM-DDTHH:MM:SSZ>"; exit 2; }
	@test -n "$(REPOSITORY_PERIOD_START)" || { echo "Set REPOSITORY_PERIOD_START=<YYYY-MM-DD>"; exit 2; }
	@test -n "$(REPOSITORY_PERIOD_END)" || { echo "Set REPOSITORY_PERIOD_END=<YYYY-MM-DD>"; exit 2; }
	$(PYTHON) -I -B scripts/repository_first.py observe --observation-id "$(REPOSITORY_OBSERVATION_ID)" --recorded-at-utc "$(REPOSITORY_RECORDED_AT_UTC)" --period-start "$(REPOSITORY_PERIOD_START)" --period-end "$(REPOSITORY_PERIOD_END)"
# /repository-first-protocol:v1

# research-artifact-release:v1
RESEARCH_RELEASE_REQUEST ?=
RESEARCH_RELEASE_ARCHIVE ?=

.PHONY: research-release-build research-release-validate research-release-test

validate: research-release-validate research-release-test
eval: research-release-test

research-release-build:
	@test -n "$(RESEARCH_RELEASE_REQUEST)" || { echo "Set RESEARCH_RELEASE_REQUEST=<release-request-json>"; exit 2; }
	$(PYTHON) -I -B scripts/research_release.py build --input "$(RESEARCH_RELEASE_REQUEST)"

research-release-validate:
	$(PYTHON) -I -B scripts/research_release.py validate $(if $(RESEARCH_RELEASE_ARCHIVE),--archive "$(RESEARCH_RELEASE_ARCHIVE)",) --json

research-release-test:
	$(PYTHON) -I -B tests/test_research_release.py -v
# /research-artifact-release:v1


validate-proof-search:
	$(PYTHON) scripts/validate_proof_search.py

proof-search-test:
	$(PYTHON) -m unittest -v tests.test_validate_proof_search_artifact_roots

eval: proof-search-test
	$(PYTHON) scripts/run_evals.py

resume:
	$(PYTHON) scripts/snapshot_project_state.py --resume-only

snapshot:
	$(PYTHON) scripts/snapshot_project_state.py

new-problem:
	$(PYTHON) scripts/new_problem.py --title "$(TITLE)" --track "$(TRACK)" $(DRY_RUN)

improvement-proposal:
	$(PYTHON) scripts/snapshot_project_state.py --improvement-proposal

# fleet-research-round-protocol:v1
ROUND_ID ?=

.PHONY: round-status round-validate round-test

validate: round-validate
eval: round-test

round-status:
	@test -n "$(ROUND_ID)" || { echo "Set ROUND_ID=<round-id>"; exit 2; }
	$(PYTHON) -I -B scripts/research_round.py status --round-id "$(ROUND_ID)"

round-validate:
	$(PYTHON) -I -B scripts/research_round.py validate $(if $(ROUND_ID),--round-id "$(ROUND_ID)",)

round-test:
	$(PYTHON) -I -B tests/test_research_round.py -v
# /fleet-research-round-protocol:v1

room-status:
	$(PYTHON) scripts/lean_room.py status --json

# Use only after the user's explicit enable or re-enable instruction.
room-enable:
	$(PYTHON) scripts/lean_room.py enable --actor user --reason "explicit user enable" --json

# This is the CLI equivalent of the canonical phrase «Отключи Lean-комнату.»
room-disable:
	$(PYTHON) scripts/lean_room.py disable --actor user --reason "user kill-switch phrase" --json

lean-freeze:
	$(PYTHON) scripts/freeze_lean_case.py "$(PROBLEM_ID)" "$(CASE_ID)" --gate "$(GATE)" --actor "$(ACTOR)" --json

lean-validate:
	$(PYTHON) scripts/validate_lean_case.py "$(PROBLEM_ID)" "$(CASE_ID)" --verification-ready --json

lean-verify:
	$(PYTHON) scripts/verify_lean_case.py "$(PROBLEM_ID)" "$(CASE_ID)" --runner-id "$(RUNNER_ID)" --run-kind "$(RUN_KIND)" --timeout "$(TIMEOUT)" --json

lean-audit:
	$(PYTHON) scripts/record_lean_audit.py "$(PROBLEM_ID)" "$(CASE_ID)" --audit-id "$(AUDIT_ID)" --auditor-id "$(AUDITOR_ID)" --auditor-run-id "$(AUDITOR_RUN_ID)" --candidate-run-id "$(CANDIDATE_RUN_ID)" --independent-run-id "$(INDEPENDENT_RUN_ID)" --verdict "$(VERDICT)" --highest-gap-class "$(HIGHEST_GAP_CLASS)" $(ATTEST_EXACT_CORRESPONDENCE) --json

lean-certificate:
	$(PYTHON) scripts/issue_lean_certificate.py "$(PROBLEM_ID)" "$(CASE_ID)" --audit-id "$(AUDIT_ID)" --issued-by "$(ISSUED_BY)" --rebuild-timeout "$(REBUILD_TIMEOUT)" $(if $(CERTIFICATE_ID),--certificate-id "$(CERTIFICATE_ID)",) --json

lean-test:
	$(PYTHON) tests/test_lean_room.py

# Acquisition is deliberately separate from proof/certificate execution. The
# importer reads an already-resolved workspace and never invokes Lean, Lake, or
# a network helper.
lean-snapshot-import:
	$(PYTHON) scripts/import_lean_dependency_snapshot.py "$(LEAN_WORKSPACE)" "$(DEPENDENCY_SNAPSHOT)" --snapshot-id "$(SNAPSHOT_ID)" --actor "$(SNAPSHOT_ACTOR)" --json

lean-snapshot-validate:
	$(PYTHON) scripts/validate_lean_dependency_snapshot.py "$(DEPENDENCY_SNAPSHOT)" --json

lean-snapshot-test:
	$(PYTHON) -m unittest -v tests.test_lean_dependency_snapshot

# This opt-in lane never enters v1 LR2-LR6. The room must already be enabled,
# and PERMITTED_AXIOM_ARGS contains repeatable `--permitted-axiom NAME` flags.
lean-dependency-pilot:
	$(PYTHON) scripts/verify_lean_dependency_pilot.py --pilot-id "$(PILOT_ID)" --runner-id "$(PILOT_RUNNER_ID)" --project "$(DEPENDENCY_PROJECT)" --snapshot "$(DEPENDENCY_SNAPSHOT)" --review "$(DEPENDENCY_REVIEW)" --declaration "$(DECLARATION)" --exact-type "$(EXACT_FORMAL_TYPE)" $(PERMITTED_AXIOM_ARGS) $(REQUIRE_LEANCHECKER) --timeout "$(TIMEOUT)" --json

lean-dependency-pilot-test:
	$(PYTHON) -m unittest -v tests.test_lean_dependency_pilot

# laboratory-survey-protocol:v1
SURVEY_ID ?=

.PHONY: survey-snapshot survey-snapshot-json survey-start survey-finalize survey-check survey-test

survey-snapshot:
	$(PYTHON) scripts/laboratory_survey.py snapshot

survey-snapshot-json:
	$(PYTHON) scripts/laboratory_survey.py snapshot --json

survey-start:
	@test -n "$(SURVEY_ID)" || { echo "Set SURVEY_ID=<UTC>-<short-label>"; exit 2; }
	$(PYTHON) scripts/laboratory_survey.py start --survey-id "$(SURVEY_ID)"

survey-finalize:
	@test -n "$(SURVEY_ID)" || { echo "Set SURVEY_ID=<UTC>-<short-label>"; exit 2; }
	$(PYTHON) scripts/laboratory_survey.py finalize --survey-id "$(SURVEY_ID)"

survey-check:
	$(PYTHON) scripts/laboratory_survey.py check

survey-test:
	$(PYTHON) -m unittest -v tests.test_laboratory_survey
# /laboratory-survey-protocol:v1

# laboratory-stewardship-protocol:v1
STEWARDSHIP_ID ?=
STEWARDSHIP_MODE ?= DEEP_LOCAL

.PHONY: stewardship-start stewardship-prepare stewardship-apply stewardship-finalize stewardship-resume stewardship-test

stewardship-start:
	@test -n "$(STEWARDSHIP_ID)" || { echo "Set STEWARDSHIP_ID=<UTC>-<short-label>"; exit 2; }
	$(PYTHON) scripts/laboratory_stewardship.py start --run-id "$(STEWARDSHIP_ID)" --mode "$(STEWARDSHIP_MODE)"

stewardship-prepare:
	@test -n "$(STEWARDSHIP_ID)" || { echo "Set STEWARDSHIP_ID=<UTC>-<short-label>"; exit 2; }
	$(PYTHON) scripts/laboratory_stewardship.py prepare --run-id "$(STEWARDSHIP_ID)"

stewardship-apply:
	@test -n "$(STEWARDSHIP_ID)" || { echo "Set STEWARDSHIP_ID=<UTC>-<short-label>"; exit 2; }
	$(PYTHON) scripts/laboratory_stewardship.py apply --run-id "$(STEWARDSHIP_ID)"

stewardship-finalize:
	@test -n "$(STEWARDSHIP_ID)" || { echo "Set STEWARDSHIP_ID=<UTC>-<short-label>"; exit 2; }
	$(PYTHON) scripts/laboratory_stewardship.py finalize --run-id "$(STEWARDSHIP_ID)"

stewardship-resume:
	@test -n "$(STEWARDSHIP_ID)" || { echo "Set STEWARDSHIP_ID=<UTC>-<short-label>"; exit 2; }
	$(PYTHON) scripts/laboratory_stewardship.py resume --run-id "$(STEWARDSHIP_ID)"

stewardship-test:
	$(PYTHON) -m unittest -v tests.test_laboratory_stewardship
# /laboratory-stewardship-protocol:v1

# discovery-and-team-protocols:v1
.PHONY: portfolio-status portfolio-refresh portfolio-validate portfolio-test team-validate team-test repository-status

portfolio-status:
	$(PYTHON) scripts/discovery_portfolio.py status

portfolio-refresh:
	$(PYTHON) scripts/discovery_portfolio.py refresh-summary

portfolio-validate:
	$(PYTHON) scripts/validate_discovery_portfolio.py

portfolio-test:
	$(PYTHON) -m unittest -v tests.test_discovery_portfolio

team-validate:
	$(PYTHON) scripts/team_collaboration.py validate

team-test:
	$(PYTHON) -m unittest -v tests.test_team_collaboration

repository-status:
	$(PYTHON) scripts/team_repository_bootstrap.py --json status
# /discovery-and-team-protocols:v1

# deep-research-goal-protocol:v1
DEEP_GOAL_ID ?=
DEEP_GOAL_INPUT ?=
DEEP_OUTCOME_INPUT ?=

.PHONY: deep-goal-prepare deep-goal-record deep-goal-status deep-goal-validate deep-goal-test

deep-goal-prepare:
	@test -n "$(DEEP_GOAL_INPUT)" || { echo "Set DEEP_GOAL_INPUT=<root-relative-json>"; exit 2; }
	$(PYTHON) -I -B scripts/deep_research_goal.py prepare --input "$(DEEP_GOAL_INPUT)"

deep-goal-record:
	@test -n "$(DEEP_GOAL_ID)" || { echo "Set DEEP_GOAL_ID=<goal-id>"; exit 2; }
	@test -n "$(DEEP_OUTCOME_INPUT)" || { echo "Set DEEP_OUTCOME_INPUT=<root-relative-json>"; exit 2; }
	$(PYTHON) -I -B scripts/deep_research_goal.py record-outcome --goal-id "$(DEEP_GOAL_ID)" --input "$(DEEP_OUTCOME_INPUT)"

deep-goal-status:
	@test -n "$(DEEP_GOAL_ID)" || { echo "Set DEEP_GOAL_ID=<goal-id>"; exit 2; }
	$(PYTHON) -I -B scripts/deep_research_goal.py status --goal-id "$(DEEP_GOAL_ID)"

deep-goal-validate:
	$(PYTHON) -I -B scripts/deep_research_goal.py validate $(if $(DEEP_GOAL_ID),--goal-id "$(DEEP_GOAL_ID)",)

deep-goal-test:
	$(PYTHON) -I -B tests/test_deep_research_goal.py -v
# /deep-research-goal-protocol:v1


# claude-terminal-default:v1
validate eval: claude-terminal-test
.PHONY: claude-terminal-test claude-terminal-status
claude-terminal-test:
	$(PYTHON) -B tests/test_claude_terminal.py -v
	$(PYTHON) -B tests/test_claude_terminal_launch.py -v
	$(PYTHON) -B tests/test_claude_terminal_timeout.py -v
	$(PYTHON) -B tests/test_claude_terminal_research.py -v
	$(PYTHON) -B tests/test_claude_collection_intake.py -v
claude-terminal-status:
	$(PYTHON) -B scripts/claude_terminal/claude_cli_launch.py --status
# /claude-terminal-default:v1
