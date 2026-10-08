PYTHON ?= python3
export PYTHONDONTWRITEBYTECODE := 1
.PHONY: doctor validate eval
doctor:
	$(PYTHON) -B scripts/doctor.py
validate:
	$(PYTHON) -B scripts/validate_lab.py
eval:
	$(PYTHON) -B scripts/run_evals.py --smoke --no-report


# claude-terminal-default:v1
validate: claude-terminal-test
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
