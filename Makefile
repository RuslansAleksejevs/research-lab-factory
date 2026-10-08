PYTHON ?= python3
REQUEST ?= profiles/examples/minimal_article.json
export PYTHONDONTWRITEBYTECODE := 1

.PHONY: validate verify plan-lab new-lab
validate:
	$(PYTHON) -B scripts/check_public_kit.py validate
verify:
	$(PYTHON) -B scripts/check_public_kit.py verify
plan-lab:
	$(PYTHON) -B scripts/new_lab.py plan --request "$(REQUEST)"
new-lab:
	$(PYTHON) -B scripts/new_lab.py create --request "$(REQUEST)"
