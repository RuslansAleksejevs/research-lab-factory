#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import importlib.util
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
BASE_SKILLS = {
    "cite-project-source",
    "explore-research-directions",
    "formulate-research-claim",
    "ingest-math-source",
    "literature-sweep",
    "propose-agent-improvement",
    "prove-or-refute",
    "record-research-checkpoint",
    "run-external-research-bridge",
    "run-research-round",
    "survey-laboratory-state",
    "steward-laboratory-state",
    "update-research-ledgers",
    "verify-proof",
}
BASE_AGENTS = {
    "source_librarian",
    "conjecture_designer",
    "proof_generator",
    "adversarial_verifier",
    "counterexample_hunter",
    "proof_reviser",
    "architecture_evaluator",
}
MODULE_REQUIREMENTS = {
    "paper": ({"draft-paper-section"}, {"exposition_editor"}, ["paper", "research_reports", "workflows/paper_protocol.md"]),
    "talks": ({"build-math-talk"}, {"talk_designer"}, ["talks", "workflows/talk_protocol.md"]),
    "computation": (set(), {"computation_formalization"}, ["research/computations"]),
    "formalization": (
        {"lean-room"},
        {"formalization_specialist", "formalization_auditor"},
        [
            "research/formalization",
            "research/formalization/lean_room_state.json",
            "workflows/lean_room_protocol.md",
            "templates/lean_room",
            "templates/lean_room/formalization_contract.yaml",
            "templates/lean_room/formal_correspondence.md",
            "templates/lean_room/correspondence_verdict.yaml",
            "templates/lean_room/formal_audit_manifest.yaml",
            "templates/lean_room/formal_certificate_manifest.yaml",
            "templates/lean_room/formalization_campaign.md",
            "templates/lean_room/formalization_checkpoint.md",
            "templates/lean_room/proof_blueprint.md",
            "templates/lean_room/refactor_audit.md",
            "templates/lean_room/dependency_snapshot_manifest.yaml",
            "templates/lean_room/dependency_snapshot_review.yaml",
            ".agents/skills/lean-room/references/operator_checklist.md",
            "scripts/lean_room.py",
            "scripts/new_lean_case.py",
            "scripts/freeze_lean_case.py",
            "scripts/validate_lean_case.py",
            "scripts/verify_lean_case.py",
            "scripts/record_lean_audit.py",
            "scripts/issue_lean_certificate.py",
            "scripts/import_lean_dependency_snapshot.py",
            "scripts/validate_lean_dependency_snapshot.py",
            "scripts/verify_lean_dependency_pilot.py",
            "tests/test_lean_room.py",
            "tests/test_lean_dependency_snapshot.py",
            "tests/test_lean_dependency_pilot.py",
            "evals/lean_room/dependency_snapshot_phase_a.md",
            "evals/lean_room/dependency_pilot_phase_b.md",
        ],
    ),
    "external_llm": (
        {"consult-chatgpt-pro"},
        set(),
        [
            "workflows/parallel_llm_research_protocol.md",
            "workflows/chatgpt_pro_browser_protocol.md",
            "templates/parallel_llm_launch_prompt.md",
            "templates/chatgpt_pro_browser_prompt.md",
            "templates/chatgpt_pro_response_intake.md",
            ".agents/skills/consult-chatgpt-pro/agents/openai.yaml",
            "scripts/chatgpt_pro_bridge.py",
            "tests/test_chatgpt_pro_bridge.py",
            "runs/external_llm/README.md",
        ],
    ),
    "deep_research_goal": (
        {"run-deep-research-goal"},
        set(),
        [
            "research/deep_goals/README.md",
            "workflows/deep_research_goal_protocol.md",
            "schemas/deep_research_goal.schema.json",
            "schemas/deep_research_outcome.schema.json",
            "schemas/deep_research_target.schema.json",
            "templates/deep_research_goal.json",
            "templates/deep_research_outcome.json",
            "templates/deep_research_target.json",
            ".agents/skills/run-deep-research-goal/agents/openai.yaml",
            "scripts/deep_research_goal.py",
            "tests/test_deep_research_goal.py",
            "evals/adversarial/deep_research_goal_scaling.md",
        ],
    ),
    "discovery_portfolio": (
        {
            "intake-discovery-candidate",
            "qualify-discovery-candidate",
            "recheck-parked-candidates",
            "prepare-discovery-spinout",
        },
        set(),
        [
            "portfolio/README.md",
            "portfolio/portfolio_state.json",
            "knowledge/control_room_summary.json",
            "workflows/discovery_portfolio_protocol.md",
            "templates/discovery_portfolio/candidate_intake.json",
            "templates/discovery_portfolio/qualification_input.json",
            "templates/discovery_portfolio/round_input.json",
            "templates/discovery_portfolio/decision_input.json",
            "templates/discovery_portfolio/dossier_link.json",
            "templates/discovery_portfolio/engagement_decision.json",
            "templates/discovery_portfolio/park_plan.json",
            "templates/discovery_portfolio/spinout_receipt.json",
            "templates/discovery_portfolio/spinout_request_draft.json",
            "scripts/discovery_portfolio_lib.py",
            "scripts/discovery_portfolio.py",
            "scripts/validate_discovery_portfolio.py",
            "tests/test_discovery_portfolio.py",
        ],
    ),
    "team_collaboration": (
        {"run-team-research-cycle", "bootstrap-team-repository"},
        set(),
        [
            "collaboration/README.md",
            "collaboration/team.json",
            "workflows/team_research_cycle_protocol.md",
            "workflows/team_repository_bootstrap_protocol.md",
            "scripts/team_collaboration.py",
            "scripts/team_repository_bootstrap.py",
            "tests/test_team_collaboration.py",
        ],
    ),
}


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def load_new_problem_module():
    path = ROOT / "scripts/new_problem.py"
    spec = importlib.util.spec_from_file_location("lab_new_problem", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load scripts/new_problem.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_script_module(filename: str, module_name: str):
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_architecture(profile: Dict[str, Any]) -> List[Tuple[bool, str]]:
    checks: List[Tuple[bool, str]] = []
    required_skills = set(BASE_SKILLS)
    required_agents = set(BASE_AGENTS)
    required_paths: List[str] = []
    modules = profile.get("lab", {}).get("modules", [])
    for module in modules:
        skills, agents, paths = MODULE_REQUIREMENTS.get(module, (set(), set(), []))
        required_skills.update(skills)
        required_agents.update(agents)
        required_paths.extend(paths)
    for role in profile.get("research", {}).get("specialist_roles", []):
        if isinstance(role, dict) and isinstance(role.get("id"), str):
            required_agents.add(role["id"])
    for skill in sorted(required_skills):
        checks.append(((ROOT / ".agents/skills" / skill / "SKILL.md").is_file(), f"skill {skill}"))
    for agent in sorted(required_agents):
        checks.append(((ROOT / ".codex/agents" / f"{agent}.toml").is_file(), f"agent {agent}"))
    for relative in required_paths:
        checks.append(((ROOT / relative).exists(), f"module path {relative}"))
    survey_paths = [
        "workflows/laboratory_survey_protocol.md",
        "templates/laboratory_survey.md",
        "templates/research_checkpoint.md",
        "research/checkpoints/README.md",
        "runs/laboratory_surveys/README.md",
        "knowledge/laboratory_overview.md",
        "knowledge/laboratory_survey_state.json",
        "scripts/laboratory_survey.py",
        "tests/test_laboratory_survey.py",
        "evals/adversarial/laboratory_survey_fragmented_state.md",
    ]
    for relative in survey_paths:
        checks.append(((ROOT / relative).exists(), f"laboratory survey path {relative}"))
    memory_paths = [
        ".lab/durable_research_memory.json",
        "workflows/durable_research_memory_protocol.md",
        "schemas/research_checkpoint.schema.json",
        "templates/research_checkpoint.json",
        "research/checkpoint_index.json",
        "scripts/research_memory.py",
        "tests/test_research_memory.py",
        "evals/adversarial/durable_research_memory_incomplete_handoff.md",
    ]
    for relative in memory_paths:
        checks.append(((ROOT / relative).is_file(), f"durable research-memory path {relative}"))
    repository_first_paths = [
        ".lab/user_policy.json",
        ".gitignore",
        "workflows/repository_first_protocol.md",
        "schemas/repository_first.schema.json",
        "schemas/research_release_request.schema.json",
        "schemas/research_release_package.schema.json",
        "templates/repository_first/README.md",
        "templates/repository_first/campaign.json",
        "templates/repository_first/phase_change.json",
        "templates/repository_first/raw_run_manifest.json",
        "templates/repository_first/adjacent_result.json",
        "templates/repository_first/failure_family.json",
        "templates/repository_first/claim_assessment.json",
        "templates/repository_first/source_use.json",
        "templates/repository_first/verification_coverage.json",
        "templates/repository_first/expert_feedback_plan.json",
        "templates/repository_first/expert_feedback_response.json",
        "templates/repository_first/export_request.json",
        "templates/repository_first/release_request.json",
        "research/raw_runs/README.md",
        "research/repository_first/README.md",
        "scripts/repository_first.py",
        "scripts/research_release.py",
        "tests/test_repository_first.py",
        "tests/test_research_release.py",
        "evals/adversarial/research_release_guarded_materialization.md",
    ]
    for relative in repository_first_paths:
        checks.append(((ROOT / relative).is_file(), f"repository-first path {relative}"))
    claude_terminal_paths = [
        ".agents/skills/run-external-research-bridge/SKILL.md",
        ".agents/skills/run-external-research-bridge/agents/openai.yaml",
        "scripts/claude_terminal/claude_runner.py",
        "scripts/claude_terminal/claude_cli_launch.py",
        "scripts/claude_terminal/claude_runner_support.py",
        "scripts/claude_terminal/claude_source_capture.py",
        "templates/claude_terminal/request.json",
        "workflows/claude_terminal_protocol.md",
        "tests/test_claude_terminal.py",
        "tests/test_claude_terminal_launch.py",
        "scripts/claude_terminal/claude_collection_intake.py",
        "tests/test_claude_terminal_timeout.py",
        "tests/test_claude_terminal_research.py",
        "tests/test_claude_collection_intake.py",
    ]
    for relative in claude_terminal_paths:
        checks.append(((ROOT / relative).is_file(), f"Claude terminal path {relative}"))
    research_round_paths = [
        ".lab/control_room_actions.json",
        ".agents/skills/run-research-round/SKILL.md",
        "workflows/research_round_protocol.md",
        "scripts/research_round.py",
        "schemas/research_round_plan.schema.json",
        "schemas/research_round_result.schema.json",
        "schemas/research_round_projection.schema.json",
        "templates/research_round_plan.json",
        "templates/research_round_result.json",
        "tests/test_research_round.py",
        "evals/adversarial/research_round_guarded_execution.md",
    ]
    for relative in research_round_paths:
        checks.append(((ROOT / relative).is_file(), f"research-round path {relative}"))
    stewardship_paths = [
        ".agents/skills/steward-laboratory-state/agents/openai.yaml",
        "workflows/laboratory_stewardship_protocol.md",
        "templates/laboratory_stewardship_plan.json",
        "templates/laboratory_stewardship_report.md",
        "runs/laboratory_stewardship/README.md",
        "scripts/laboratory_stewardship.py",
        "tests/test_laboratory_stewardship.py",
        "evals/adversarial/laboratory_stewardship_fragmented_repair.md",
    ]
    for relative in stewardship_paths:
        checks.append(((ROOT / relative).exists(), f"laboratory stewardship path {relative}"))
    fixtures = sorted((ROOT / "evals/adversarial").glob("proof_search_*.md"))
    checks.append((len(fixtures) >= 8, "adversarial proof-search rubric set"))
    survey_fixtures = sorted((ROOT / "evals/adversarial").glob("laboratory_survey_*.md"))
    checks.append((len(survey_fixtures) >= 1, "adversarial laboratory-survey rubric set"))
    round_fixtures = sorted((ROOT / "evals/adversarial").glob("research_round_*.md"))
    checks.append((len(round_fixtures) >= 1, "adversarial research-round rubric set"))
    memory_fixtures = sorted(
        (ROOT / "evals/adversarial").glob("durable_research_memory_*.md")
    )
    checks.append((len(memory_fixtures) >= 1, "adversarial durable-memory rubric set"))
    stewardship_fixtures = sorted(
        (ROOT / "evals/adversarial").glob("laboratory_stewardship_*.md")
    )
    checks.append((len(stewardship_fixtures) >= 1, "adversarial stewardship rubric set"))
    release_fixtures = sorted(
        (ROOT / "evals/adversarial").glob("research_release_*.md")
    )
    checks.append((len(release_fixtures) >= 1, "adversarial research-release rubric set"))
    if "formalization" in modules:
        lean_fixtures = sorted((ROOT / "evals/lean_room/fixtures").glob("*/Main.lean"))
        checks.append((len(lean_fixtures) >= 6, "Lean Room adversarial fixture set"))
        checks.append(
            ((ROOT / "tests/test_lean_room.py").is_file(), "Lean Room executable eval suite entrypoint")
        )
    return checks


def check_validator_fifo_race() -> List[Tuple[bool, str]]:
    checks: List[Tuple[bool, str]] = []
    validator = load_script_module("validate_lab.py", "lab_validator_fifo_eval")
    with tempfile.TemporaryDirectory(prefix="lab-validator-fifo-eval-") as temp_dir:
        target = Path(temp_dir) / "checkpoint_index.json"
        target.write_text('{"schema_version":1}\n', encoding="utf-8")
        real_open = validator.os.open
        nonblocking_open_seen: List[bool] = []

        def replace_regular_with_fifo(candidate, flags, *open_args, **open_kwargs):
            if Path(candidate) == target:
                target.unlink()
                os.mkfifo(target)
                nonblocking_open_seen.append(
                    bool(flags & getattr(os, "O_NONBLOCK", 0))
                )
                if not nonblocking_open_seen[-1]:
                    raise OSError(errno.EWOULDBLOCK, "blocking FIFO open refused by eval")
            return real_open(candidate, flags, *open_args, **open_kwargs)

        errors: List[str] = []
        original_root = validator.ROOT
        validator.os.open = replace_regular_with_fifo
        try:
            validator.ROOT = Path(temp_dir)
            result = validator.safe_regular_bytes(
                target,
                "durable research-memory eval file",
                errors,
            )
        finally:
            validator.ROOT = original_root
            validator.os.open = real_open
        checks.append(
            (
                result is None
                and nonblocking_open_seen == [True]
                and any("changed type" in error for error in errors),
                "durable-memory validator rejects regular-to-FIFO races without blocking",
            )
        )
    return checks


def check_problem_instantiation(profile: Dict[str, Any]) -> List[Tuple[bool, str]]:
    checks: List[Tuple[bool, str]] = []
    module = load_new_problem_module()
    default_track = profile["research"]["default_track"]
    checks.append((module.slugify("Generic Algebra Problem") == "generic-algebra-problem", "ASCII problem slug"))
    checks.append((module.slugify("Тестовая теорема").startswith("тестовая-теорема-"), "Unicode problem slug"))
    checks.append((module.slugify("∫∞").startswith("problem-"), "symbol-only hash fallback"))
    with tempfile.TemporaryDirectory(prefix="lab-problem-eval-") as temp_dir:
        root = Path(temp_dir)
        shutil.copytree(ROOT / "problems/templates/problem_dossier", root / "problems/templates/problem_dossier")
        (root / "problems/active").mkdir(parents=True)
        (root / "knowledge").mkdir(parents=True)
        test_profile = {
            "research": {
                "tracks": profile["research"]["tracks"],
                "default_track": default_track,
            }
        }
        (root / "LAB_PROFILE.json").write_text(json.dumps(test_profile), encoding="utf-8")
        (root / "knowledge/research_state.yaml").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "laboratory_status": "INITIALIZED",
                    "active_problem_ids": [],
                    "current_priorities": []
                }
            ),
            encoding="utf-8",
        )
        target = module.create_problem(
            root,
            "Temporary Generic Claim",
            default_track,
            "For every admissible object, determine whether the stated property holds.",
            "2000-01-01",
        )
        required = {
            "README.md",
            "problem.md",
            "status.yaml",
            "context_envelope.md",
            "approach_registry.md",
            "attack_surface.md",
            "proof_search_state.yaml",
            "candidate_lineage.md",
            "search_rounds/README.md",
        }
        files = {path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()}
        checks.append((required.issubset(files), "temporary dossier required files"))
        residue = []
        for path in target.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                if any(token in text for token in ["{{TITLE}}", "{{TRACK}}", "{{DATE}}", "{{PROBLEM_ID}}", "{{STATEMENT}}"]):
                    residue.append(path.name)
        checks.append((not residue, "temporary dossier token replacement"))
        try:
            json.loads((target / "status.yaml").read_text(encoding="utf-8"))
            json.loads((target / "proof_search_state.yaml").read_text(encoding="utf-8"))
            parsed = True
        except Exception:
            parsed = False
        checks.append((parsed, "temporary dossier structured files parse"))

        quoted_title = 'Quoted "Claim" with a \\ separator'
        multiline_statement = "First mathematical line.\n\nSecond mathematical line."
        quoted_target = module.create_problem(
            root,
            quoted_title,
            default_track,
            multiline_statement,
            "2000-01-02",
        )
        try:
            quoted_status = json.loads((quoted_target / "status.yaml").read_text(encoding="utf-8"))
            quoted_structured_ok = quoted_status.get("title") == quoted_title
        except Exception:
            quoted_structured_ok = False
        checks.append((quoted_structured_ok, "quoted title is escaped in structured templates"))
        checks.append(
            (
                multiline_statement in (quoted_target / "problem.md").read_text(encoding="utf-8"),
                "multiline statement is preserved in Markdown",
            )
        )
        updated_state = json.loads((root / "knowledge/research_state.yaml").read_text(encoding="utf-8"))
        checks.append(
            (
                sorted(updated_state.get("active_problem_ids", []))
                == sorted([target.name, quoted_target.name]),
                "created dossiers are registered in canonical research state",
            )
        )

        try:
            module.create_problem(
                root,
                "Unsafe title\n## injected heading",
                default_track,
                "Statement.",
                "2000-01-03",
            )
            unsafe_title_rejected = False
        except module.ProblemCreationError:
            unsafe_title_rejected = True
        checks.append((unsafe_title_rejected, "multiline problem title is rejected"))

        structured_statement = root / "structured-statement.json"
        structured_statement.write_text('{"statement": "{{STATEMENT}}"}\n', encoding="utf-8")
        try:
            module.render_file(
                structured_statement,
                {
                    "TITLE": "Title",
                    "TRACK": default_track,
                    "DATE": "2000-01-04",
                    "PROBLEM_ID": "20000104-title",
                    "STATEMENT": multiline_statement,
                },
            )
            structured_statement_rejected = False
        except module.ProblemCreationError:
            structured_statement_rejected = True
        checks.append(
            (structured_statement_rejected, "statement token is rejected in structured templates")
        )

        malformed_structured = root / "malformed.json"
        malformed_structured.write_text('{"title": "{{TITLE}}"\n', encoding="utf-8")
        try:
            module.render_file(
                malformed_structured,
                {
                    "TITLE": "Title",
                    "TRACK": default_track,
                    "DATE": "2000-01-04",
                    "PROBLEM_ID": "20000104-title",
                    "STATEMENT": "Statement.",
                },
            )
            malformed_rejected = False
        except module.ProblemCreationError:
            malformed_rejected = True
        checks.append((malformed_rejected, "malformed structured template is rejected"))

        no_clobber_stage = root / "no-clobber-stage"
        no_clobber_target = root / "no-clobber-target"
        no_clobber_stage.mkdir()
        no_clobber_target.mkdir()
        (no_clobber_stage / "payload.txt").write_text("new\n", encoding="utf-8")
        (no_clobber_target / "sentinel.txt").write_text("existing\n", encoding="utf-8")
        try:
            module.publish_directory_noreplace(no_clobber_stage, no_clobber_target)
            no_clobber_ok = False
        except module.ProblemCreationError:
            no_clobber_ok = (
                (no_clobber_stage / "payload.txt").read_text(encoding="utf-8") == "new\n"
                and (no_clobber_target / "sentinel.txt").read_text(encoding="utf-8")
                == "existing\n"
            )
        checks.append((no_clobber_ok, "atomic publication never replaces an existing target"))
    return checks


def check_source_ingestion() -> List[Tuple[bool, str]]:
    checks: List[Tuple[bool, str]] = []
    ingestion = load_script_module("ingest_sources.py", "lab_ingest_sources")
    ledger_validation = load_script_module("validate_ledgers.py", "lab_validate_ledgers")
    with tempfile.TemporaryDirectory(prefix="lab-source-eval-") as temp_dir:
        root = Path(temp_dir)
        registry_path = root / "sources/manifests/source_registry.yaml"
        log_path = root / "sources/manifests/ingestion_log.jsonl"
        registry_path.parent.mkdir(parents=True)
        (root / "sources/digests").mkdir(parents=True)
        registry_path.write_text('{"schema_version": 1, "sources": []}\n', encoding="utf-8")
        first = root / "inbox-a/shared-name.txt"
        second = root / "inbox-b/shared-name.txt"
        first.parent.mkdir()
        second.parent.mkdir()
        first.write_text("first source body\n", encoding="utf-8")
        second.write_text("second source body\n", encoding="utf-8")

        ingestion.ROOT = root
        ingestion.REGISTRY = registry_path
        ingestion.LOG = log_path
        (root / "LAB_PROFILE.json").write_text(
            json.dumps(
                {
                    "bootstrap_materials": [
                        {
                            "stored_name": first.relative_to(root).as_posix(),
                            "sha256": ingestion.sha256(first),
                            "trust_tier": "B",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        by_path, by_hash = ingestion.load_bootstrap_tier_maps()
        original_first_body = first.read_text(encoding="utf-8")
        first.write_text(second.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            ingestion.effective_trust_tier(first, "C", by_path, by_hash)
            swapped_bootstrap_rejected = False
        except RuntimeError:
            swapped_bootstrap_rejected = True
        first.write_text(original_first_body, encoding="utf-8")
        checks.append(
            (
                swapped_bootstrap_rejected,
                "bootstrap path tier is rejected when current bytes disagree with its bound SHA-256",
            )
        )
        first_tier, first_tier_source, first_digest = ingestion.effective_trust_tier(
            first, "C", by_path, by_hash
        )
        second_tier, _, second_digest = ingestion.effective_trust_tier(second, "C", by_path, by_hash)
        first.write_text(second.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            ingestion.ingest_file(
                first,
                "core",
                first_tier,
                False,
                expected_sha256=first_digest,
            )
            post_classification_swap_rejected = False
        except RuntimeError:
            post_classification_swap_rejected = True
        first.write_text(original_first_body, encoding="utf-8")
        checks.append(
            (
                post_classification_swap_rejected,
                "source swap after tier classification is rejected before ingestion",
            )
        )
        first_record = ingestion.ingest_file(
            first, "core", first_tier, False, expected_sha256=first_digest
        )
        second_record = ingestion.ingest_file(
            second, "core", second_tier, False, expected_sha256=second_digest
        )
        duplicate_record = ingestion.ingest_file(first, "core", first_tier, False)
        conflicting_duplicate = ingestion.ingest_file(first, "core", "C", False)
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        originals = [root / item["original_path"] for item in registry.get("sources", [])]
        checks.append(
            (
                len(registry.get("sources", [])) == 2
                and first_record.get("source_id") != second_record.get("source_id")
                and duplicate_record.get("status") == "duplicate"
                and first_record.get("trust_tier") == "B"
                and first_tier_source.startswith("LAB_PROFILE")
                and conflicting_duplicate.get("tier_conflict") is True
                and len({path.as_posix() for path in originals}) == 2
                and all(path.is_file() for path in originals),
                "same-name source originals are content-addressed and duplicate content is deduplicated",
            )
        )

        ledger_validation.ROOT = root
        provenance_errors: List[str] = []
        ledger_validation.validate_sources(registry, provenance_errors)
        ledger_validation.validate_bootstrap_tiers(registry, provenance_errors)
        checks.append((not provenance_errors, "source registry paths, hashes, and bootstrap tiers validate"))
        wrong_tier_registry = json.loads(json.dumps(registry))
        wrong_tier_registry["sources"][0]["trust_tier"] = "C"
        tier_errors: List[str] = []
        ledger_validation.validate_bootstrap_tiers(wrong_tier_registry, tier_errors)
        checks.append(
            (
                any("bootstrap tier mismatch" in error for error in tier_errors),
                "source validator detects bootstrap-tier replacement",
            )
        )
        wrong_path_registry = json.loads(json.dumps(registry))
        wrong_path_registry["sources"][0]["sha256"] = wrong_path_registry["sources"][1]["sha256"]
        path_binding_errors: List[str] = []
        ledger_validation.validate_bootstrap_tiers(wrong_path_registry, path_binding_errors)
        checks.append(
            (
                any("bootstrap path hash mismatch" in error for error in path_binding_errors),
                "source validator detects registry content swapped under a bootstrap path",
            )
        )
        originals[0].write_text("tampered source body\n", encoding="utf-8")
        tamper_errors: List[str] = []
        ledger_validation.validate_sources(registry, tamper_errors)
        checks.append(
            (
                any("source hash mismatch" in error for error in tamper_errors),
                "source provenance validator detects original-file tampering",
            )
        )
    return checks


def make_report(checks: List[Tuple[bool, str]]) -> str:
    lines = ["# Evaluation Report", "", "## Structural and executable checks", ""]
    for passed, label in checks:
        lines.append(f"- {'PASS' if passed else 'FAIL'} — {label}")
    lines.extend(
        [
            "",
            "## Behavioral rubrics",
            "",
            "- NOT RUN — adversarial Markdown scenarios remain rubrics for fresh-agent evaluation.",
            "",
            "Structural and fixture success does not verify mathematics, sources, novelty, authorship, or actual information independence.",
            "",
        ]
    )
    return "\n".join(lines)


def write_if_changed(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.write_text(text, encoding="utf-8")


def lean_room_control_status() -> Tuple[str, Optional[Tuple[int, str]], str]:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/lean_room.py"),
            "--root",
            str(ROOT),
            "status",
            "--json",
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=5,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return "invalid", None, "Lean Room control status is not parseable"
    if payload.get("valid") is not True:
        return "invalid", None, str(payload.get("diagnostic") or "invalid Lean Room state")
    state = payload.get("effective_state")
    expected_code = 0 if state == "enabled" else 3 if state == "disabled" else None
    if expected_code is None or result.returncode != expected_code:
        return "invalid", None, "Lean Room status and exit code disagree"
    if state == "disabled":
        return "disabled", None, str(payload.get("diagnostic") or "disabled")
    sequence = payload.get("sequence")
    digest = payload.get("artifact_sha256")
    if not isinstance(sequence, int) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        return "invalid", None, "enabled Lean Room lacks a stable state binding"
    return "enabled", (sequence, digest), "enabled"


def run_lean_suite_guarded(expected_binding: Tuple[int, str]) -> Tuple[int, str, str, bool]:
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "tests/test_lean_room.py")],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    aborted = False
    while True:
        try:
            stdout, stderr = process.communicate(timeout=0.20)
            return int(process.returncode or 0), stdout, stderr, aborted
        except subprocess.TimeoutExpired:
            state, binding, _ = lean_room_control_status()
            if state == "enabled" and binding == expected_binding:
                continue
            aborted = True
            try:
                stdout, stderr = process.communicate(timeout=1.0)
                return int(process.returncode or 1), stdout, stderr, aborted
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                stdout, stderr = process.communicate(timeout=1.0)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                stdout, stderr = process.communicate()
            return int(process.returncode or 1), stdout, stderr, aborted


def main() -> int:
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description="Run laboratory architecture and dossier evals.")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()
    profile = load_json(ROOT / "LAB_PROFILE.json")
    checks = check_architecture(profile)
    checks.extend(check_validator_fifo_race())
    checks.extend(check_problem_instantiation(profile))
    checks.extend(check_source_ingestion())
    selected = set(profile.get("lab", {}).get("modules", []))
    module_validators = [
        (
            "repository-first profile-policy state validator",
            [sys.executable, "-I", "-B", "scripts/repository_first.py", "validate", "--json"],
        ),
        (
            "research artifact release package validator",
            [sys.executable, "-I", "-B", "scripts/research_release.py", "validate", "--json"],
        ),
    ]
    if "deep_research_goal" in selected:
        module_validators.append(
            (
                "deep research goal state validator",
                [sys.executable, "-I", "-B", "scripts/deep_research_goal.py", "validate"],
            )
        )
    if "discovery_portfolio" in selected:
        module_validators.append(
            (
                "discovery portfolio state validator",
                [sys.executable, "scripts/validate_discovery_portfolio.py"],
            )
        )
    if "team_collaboration" in selected:
        module_validators.append(
            (
                "team collaboration state validator",
                [sys.executable, "scripts/team_collaboration.py", "validate"],
            )
        )
    for label, command in module_validators:
        result = subprocess.run(
            command,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=60,
        )
        if result.returncode != 0:
            print(result.stdout + "\n" + result.stderr, file=sys.stderr)
        checks.append((result.returncode == 0, label))
    if not args.smoke:
        survey_suite = subprocess.run(
            [sys.executable, "-m", "unittest", "-v", "tests.test_laboratory_survey"],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=60,
        )
        survey_output = survey_suite.stdout + "\n" + survey_suite.stderr
        if survey_suite.returncode != 0:
            print(survey_output, file=sys.stderr)
        checks.append(
            (survey_suite.returncode == 0, "hash-bound laboratory-survey executable suite")
        )
        memory_suite = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(ROOT / "tests/test_research_memory.py"),
                "-v",
            ],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=120,
        )
        memory_output = memory_suite.stdout + "\n" + memory_suite.stderr
        if memory_suite.returncode != 0:
            print(memory_output, file=sys.stderr)
        checks.append(
            (
                memory_suite.returncode == 0,
                "durable research-memory executable suite",
            )
        )
        research_round_suite = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(ROOT / "tests/test_research_round.py"),
                "-v",
            ],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=120,
        )
        research_round_output = research_round_suite.stdout + "\n" + research_round_suite.stderr
        if research_round_suite.returncode != 0:
            print(research_round_output, file=sys.stderr)
        checks.append(
            (
                research_round_suite.returncode == 0,
                "guarded laboratory research-round executable suite",
            )
        )
        repository_first_suite = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(ROOT / "tests/test_repository_first.py"),
                "-v",
            ],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=180,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        repository_first_output = (
            repository_first_suite.stdout + "\n" + repository_first_suite.stderr
        )
        if repository_first_suite.returncode != 0:
            print(repository_first_output, file=sys.stderr)
        checks.append(
            (
                repository_first_suite.returncode == 0,
                "repository-first profile-policy adversarial suite",
            )
        )
        research_release_suite = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(ROOT / "tests/test_research_release.py"),
                "-v",
            ],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=180,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        research_release_output = (
            research_release_suite.stdout + "\n" + research_release_suite.stderr
        )
        if research_release_suite.returncode != 0:
            print(research_release_output, file=sys.stderr)
        checks.append(
            (
                research_release_suite.returncode == 0,
                "research artifact release executable adversarial suite",
            )
        )
        stewardship_suite = subprocess.run(
            [sys.executable, "-m", "unittest", "-v", "tests.test_laboratory_stewardship"],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=90,
        )
        stewardship_output = stewardship_suite.stdout + "\n" + stewardship_suite.stderr
        if stewardship_suite.returncode != 0:
            print(stewardship_output, file=sys.stderr)
        checks.append(
            (
                stewardship_suite.returncode == 0,
                "guarded laboratory-stewardship executable suite",
            )
        )
        for module, test_name, label in [
            (
                "deep_research_goal",
                "tests.test_deep_research_goal",
                "deep research goal canonical no-overwrite executable suite",
            ),
            (
                "discovery_portfolio",
                "tests.test_discovery_portfolio",
                "discovery portfolio executable suite",
            ),
            (
                "team_collaboration",
                "tests.test_team_collaboration",
                "team collaboration and repository-bootstrap executable suite",
            ),
        ]:
            if module not in selected:
                continue
            module_suite = subprocess.run(
                [sys.executable, "-m", "unittest", "-v", test_name],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                timeout=120,
            )
            output = module_suite.stdout + "\n" + module_suite.stderr
            if module_suite.returncode != 0:
                print(output, file=sys.stderr)
            checks.append((module_suite.returncode == 0, label))
        if "external_llm" in profile.get("lab", {}).get("modules", []):
            external_suite = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "-v",
                    "tests.test_chatgpt_pro_bridge",
                ],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )
            external_output = external_suite.stdout + "\n" + external_suite.stderr
            external_no_skips = not re.search(
                r"(?:\bskipped\s*=|\.\.\.\s+skipped\s+)",
                external_output,
                re.IGNORECASE,
            )
            if external_suite.returncode != 0 or not external_no_skips:
                print(external_output, file=sys.stderr)
            checks.append(
                (
                    external_suite.returncode == 0 and external_no_skips,
                    "ChatGPT Pro bridge state-machine suite (zero skips)",
                )
            )
        if "formalization" in profile.get("lab", {}).get("modules", []):
            snapshot_suite = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "-v",
                    "tests.test_lean_dependency_snapshot",
                ],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                timeout=120,
            )
            snapshot_output = snapshot_suite.stdout + "\n" + snapshot_suite.stderr
            snapshot_no_skips = not re.search(
                r"(?:\bskipped\s*=|\.\.\.\s+skipped\s+)",
                snapshot_output,
                re.IGNORECASE,
            )
            if snapshot_suite.returncode != 0 or not snapshot_no_skips:
                print(snapshot_output, file=sys.stderr)
            checks.append(
                (
                    snapshot_suite.returncode == 0 and snapshot_no_skips,
                    "Lean Room v2 source-snapshot adversarial suite (zero skips)",
                )
            )
            pilot_suite = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "-v",
                    "tests.test_lean_dependency_pilot",
                ],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                timeout=180,
            )
            pilot_output = pilot_suite.stdout + "\n" + pilot_suite.stderr
            pilot_no_skips = not re.search(
                r"(?:\bskipped\s*=|\.\.\.\s+skipped\s+)",
                pilot_output,
                re.IGNORECASE,
            )
            if pilot_suite.returncode != 0 or not pilot_no_skips:
                print(pilot_output, file=sys.stderr)
            checks.append(
                (
                    pilot_suite.returncode == 0 and pilot_no_skips,
                    "Lean Room v2 dependency-pilot adversarial suite (zero skips)",
                )
            )
            state, binding_before, diagnostic = lean_room_control_status()
            if state == "enabled" and binding_before is not None:
                lean_returncode, lean_stdout, lean_stderr, lean_aborted = run_lean_suite_guarded(
                    binding_before
                )
                combined_output = lean_stdout + "\n" + lean_stderr
                state_after, binding_after, _ = lean_room_control_status()
                no_skips = not re.search(
                    r"(?:\bskipped\s*=|\.\.\.\s+skipped\s+)",
                    combined_output,
                    re.IGNORECASE,
                )
                outer_sandbox_skip = (
                    lean_returncode == 0
                    and "sandbox_apply: Operation not permitted" in combined_output
                )
                lean_passed = (
                    lean_returncode == 0
                    and not lean_aborted
                    and (no_skips or outer_sandbox_skip)
                    and state_after == "enabled"
                    and binding_after == binding_before
                )
                if not lean_passed:
                    print(lean_stdout, file=sys.stderr)
                    print(lean_stderr, file=sys.stderr)
                checks.append(
                    (
                        lean_passed,
                        (
                            "Lean Room executable adversarial suite (zero skips; stable control binding)"
                            if no_skips
                            else "Lean Room runnable adversarial checks pass with stable control binding; nested Seatbelt execution is blocked by the outer sandbox"
                        ),
                    )
                )
            elif state == "disabled":
                checks.append(
                    (
                        True,
                        "Lean Room is validly disabled and executable evals remain fail-closed",
                    )
                )
            else:
                checks.append((False, "Lean Room control state is valid: " + diagnostic))
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/validate_proof_search.py")],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
        )
        checks.append((result.returncode == 0, "full proof-search validator"))
    report = make_report(checks)
    if not args.no_report:
        write_if_changed(ROOT / "evals/reports/latest.md", report)
    print(report)
    return 0 if all(passed for passed, _ in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
