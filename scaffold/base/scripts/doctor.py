#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]

BASE_REQUIRED = [
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
    "AGENTS.md",
    "AGENT_POLICY.md",
    "Makefile",
    "README.md",
    "LAB_PROFILE.json",
    "BOOTSTRAP_REPORT.md",
    "USER_PREFERENCES.md",
    ".lab/user_policy.json",
    ".codex/config.toml",
    ".lab/durable_research_memory.json",
    "knowledge/resume.md",
    "knowledge/results_ledger.yaml",
    "knowledge/research_state.yaml",
    "knowledge/laboratory_overview.md",
    "knowledge/laboratory_survey_state.json",
    "sources/TRUST_TIERS.md",
    "sources/manifests/source_registry.yaml",
    "00_INBOX_TO_ANALYZE/priority",
    ".agents/skills/prove-or-refute/SKILL.md",
    ".agents/skills/survey-laboratory-state/SKILL.md",
    ".agents/skills/steward-laboratory-state/SKILL.md",
    ".agents/skills/steward-laboratory-state/agents/openai.yaml",
    ".agents/skills/record-research-checkpoint/SKILL.md",
    ".agents/skills/run-external-research-bridge/SKILL.md",
    ".agents/skills/run-external-research-bridge/agents/openai.yaml",
    "workflows/laboratory_survey_protocol.md",
    "workflows/laboratory_stewardship_protocol.md",
    "templates/laboratory_survey.md",
    "templates/laboratory_stewardship_plan.json",
    "templates/laboratory_stewardship_report.md",
    "templates/research_checkpoint.md",
    "templates/research_checkpoint.json",
    "schemas/research_checkpoint.schema.json",
    "research/checkpoints/README.md",
    "research/checkpoint_index.json",
    "scripts/research_memory.py",
    "tests/test_research_memory.py",
    "workflows/durable_research_memory_protocol.md",
    "evals/adversarial/durable_research_memory_incomplete_handoff.md",
    "runs/laboratory_surveys/README.md",
    "runs/laboratory_stewardship/README.md",
    "scripts/laboratory_survey.py",
    "scripts/laboratory_stewardship.py",
    "scripts/repository_first.py",
    "scripts/research_release.py",
    "schemas/repository_first.schema.json",
    "schemas/research_release_request.schema.json",
    "schemas/research_release_package.schema.json",
    "workflows/repository_first_protocol.md",
    "templates/repository_first",
    "templates/repository_first/release_request.json",
    "research/raw_runs/README.md",
    "research/repository_first/README.md",
    "tests/test_repository_first.py",
    "tests/test_research_release.py",
    "evals/adversarial/research_release_guarded_materialization.md",
]

MODULE_REQUIRED = {
    "paper": [
        "paper",
        "research_reports",
        "workflows/paper_protocol.md",
        ".agents/skills/draft-paper-section/SKILL.md",
    ],
    "talks": [
        "talks",
        "workflows/talk_protocol.md",
        ".agents/skills/build-math-talk/SKILL.md",
    ],
    "computation": [
        "research/computations",
        ".codex/agents/computation_formalization.toml",
    ],
    "formalization": [
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
        ".agents/skills/lean-room/SKILL.md",
        ".agents/skills/lean-room/references/operator_checklist.md",
        ".codex/agents/formalization_specialist.toml",
        ".codex/agents/formalization_auditor.toml",
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
    "external_llm": [
        "workflows/parallel_llm_research_protocol.md",
        "templates/parallel_llm_launch_prompt.md",
        "runs/external_llm",
    ],
    "deep_research_goal": [
        "research/deep_goals/README.md",
        "workflows/deep_research_goal_protocol.md",
        "schemas/deep_research_goal.schema.json",
        "schemas/deep_research_outcome.schema.json",
        "schemas/deep_research_target.schema.json",
        "templates/deep_research_goal.json",
        "templates/deep_research_outcome.json",
        "templates/deep_research_target.json",
        ".agents/skills/run-deep-research-goal/SKILL.md",
        ".agents/skills/run-deep-research-goal/agents/openai.yaml",
        "scripts/deep_research_goal.py",
        "tests/test_deep_research_goal.py",
        "evals/adversarial/deep_research_goal_scaling.md",
    ],
    "discovery_portfolio": [
        "portfolio/README.md",
        "portfolio/portfolio_state.json",
        "knowledge/control_room_summary.json",
        "workflows/discovery_portfolio_protocol.md",
        ".agents/skills/intake-discovery-candidate/SKILL.md",
        ".agents/skills/qualify-discovery-candidate/SKILL.md",
        ".agents/skills/recheck-parked-candidates/SKILL.md",
        ".agents/skills/prepare-discovery-spinout/SKILL.md",
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
    "team_collaboration": [
        "collaboration/README.md",
        "collaboration/team.json",
        "workflows/team_research_cycle_protocol.md",
        "workflows/team_repository_bootstrap_protocol.md",
        ".agents/skills/run-team-research-cycle/SKILL.md",
        ".agents/skills/bootstrap-team-repository/SKILL.md",
        "scripts/team_collaboration.py",
        "scripts/team_repository_bootstrap.py",
        "tests/test_team_collaboration.py",
    ],
}

OPTIONAL_TOOLS = {
    "git": "local version history (the scaffold does not initialize it)",
    "gh": "explicit post-generation GitHub bootstrap for team laboratories",
    "pdfinfo": "PDF metadata inspection",
    "tesseract": "OCR for scanned sources; ingestion does not invoke it automatically",
    "pandoc": "optional document conversion",
    "dot": "optional graph rendering",
    "sage": "optional computer algebra",
    "gap": "optional computational group theory",
}


def load_profile(path: Path) -> Tuple[Dict[str, Any], List[str]]:
    errors: List[str] = []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, [f"cannot parse LAB_PROFILE.json: {exc}"]
    if not isinstance(value, dict):
        return {}, ["LAB_PROFILE.json must contain an object"]
    if value.get("profile_status") not in {"READY", "PROVISIONAL"}:
        errors.append("LAB_PROFILE.json has an invalid profile_status")
    lab = value.get("lab")
    if not isinstance(lab, dict):
        errors.append("LAB_PROFILE.json has no lab object")
    else:
        modules = lab.get("modules")
        if not isinstance(modules, list) or not all(isinstance(item, str) for item in modules):
            errors.append("LAB_PROFILE.json lab.modules must be an array of strings")
        else:
            unknown = sorted(set(modules) - set(MODULE_REQUIRED))
            if unknown:
                errors.append(f"LAB_PROFILE.json declares unknown modules: {', '.join(unknown)}")
    materials = value.get("bootstrap_materials")
    if not isinstance(materials, list):
        errors.append("LAB_PROFILE.json bootstrap_materials must be an array")
    return value, errors


def selected_modules(profile: Dict[str, Any]) -> List[str]:
    lab = profile.get("lab", {})
    modules = lab.get("modules", []) if isinstance(lab, dict) else []
    if not isinstance(modules, list):
        return []
    return sorted({item for item in modules if isinstance(item, str)})


def staged_pdf_present(profile: Dict[str, Any]) -> bool:
    materials = profile.get("bootstrap_materials", [])
    if isinstance(materials, list):
        for item in materials:
            if isinstance(item, dict):
                stored = item.get("stored_name")
                if isinstance(stored, str) and Path(stored).suffix.casefold() == ".pdf":
                    return True
    inbox = ROOT / "00_INBOX_TO_ANALYZE"
    if inbox.is_dir():
        for path in inbox.rglob("*"):
            if path.is_file() and not path.is_symlink() and path.suffix.casefold() == ".pdf":
                return True
    return False


def capability_requirements(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    modules = set(selected_modules(profile))
    requirements: List[Dict[str, Any]] = [
        {
            "name": "generated-lab command interface",
            "alternatives": [("python3", "make")],
            "reason": "the documented Makefile workflow",
        }
    ]
    if "paper" in modules:
        requirements.append(
            {
                "name": "LaTeX compilation",
                "alternatives": [("latexmk",), ("pdflatex",)],
                "reason": "selected paper module",
            }
        )
    if "formalization" in modules:
        requirements.append(
            {
                "name": "Lean tool discovery shims",
                "alternatives": [("lean", "lake", "elan")],
                "reason": "tool discovery only; each case verifier checks its exact OS-account Elan pin",
            }
        )
        requirements.append(
            {
                "name": "Lean Room isolation backend",
                "alternatives": [("sandbox-exec",)],
                "reason": "certificate builds require the exact macOS /usr/bin/sandbox-exec backend",
                "check": "macos-seatbelt",
            }
        )
    if staged_pdf_present(profile):
        requirements.append(
            {
                "name": "PDF text extraction",
                "alternatives": [("pdftotext",)],
                "reason": "a PDF is staged and the current ingestion script uses pdftotext",
            }
        )
    return requirements


def alternatives_text(alternatives: Sequence[Sequence[str]]) -> str:
    return " or ".join(" + ".join(group) for group in alternatives)


def capability_available(alternatives: Sequence[Sequence[str]]) -> Tuple[bool, List[str]]:
    detected = sorted({tool for group in alternatives for tool in group if shutil.which(tool)})
    available = any(all(shutil.which(tool) for tool in group) for group in alternatives)
    return available, detected


def macos_seatbelt_available() -> Tuple[bool, List[str]]:
    backend = Path("/usr/bin/sandbox-exec")
    available = (
        sys.platform == "darwin"
        and backend.is_file()
        and not backend.is_symlink()
        and os.access(backend, os.X_OK)
    )
    return available, [str(backend)] if available else []


def basic_toml_check(path: Path) -> tuple[bool, str]:
    in_multiline_array = False
    for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if in_multiline_array:
            if "]" in stripped:
                in_multiline_array = False
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            continue
        if "=" not in stripped:
            return False, f"line {idx}: expected key = value"
        if stripped.count('"') % 2:
            return False, f"line {idx}: unbalanced quotes"
        if stripped.endswith("["):
            in_multiline_array = True
    if in_multiline_array:
        return False, "unterminated multiline array"
    return True, "basic syntax ok"


def lean_room_state_check() -> tuple[bool, str]:
    script = ROOT / "scripts/lean_room.py"
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(script),
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
        value = json.loads(result.stdout)
    except Exception as exc:
        return False, f"official status command failed (fail-closed): {exc}"
    if not isinstance(value, dict) or value.get("valid") is not True:
        diagnostic = value.get("diagnostic") if isinstance(value, dict) else None
        return False, str(diagnostic or "invalid official status payload (fail-closed)")
    status = value.get("effective_state")
    if status not in {"enabled", "disabled"}:
        return False, "official status has an unknown effective state (fail-closed)"
    expected_code = 0 if status == "enabled" else 3
    if result.returncode != expected_code:
        return False, "official state status exit code is inconsistent (fail-closed)"
    return True, status


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check generated-laboratory structure and profile-relevant local capabilities."
    )
    parser.add_argument(
        "--strict-capabilities",
        action="store_true",
        help="fail when a capability required by the selected modules or staged source types is missing",
    )
    args = parser.parse_args()

    print("Project doctor")
    print(f"Root: {ROOT}")
    print(f"Python: {sys.version.split()[0]}")
    print("")

    structural_ok = True
    profile_path = ROOT / "LAB_PROFILE.json"
    profile: Dict[str, Any] = {}
    profile_errors: List[str] = []
    if profile_path.is_file():
        profile, profile_errors = load_profile(profile_path)
    else:
        profile_errors = ["LAB_PROFILE.json is missing"]
    if profile_errors:
        structural_ok = False

    modules = selected_modules(profile)
    required = list(BASE_REQUIRED)
    for module in modules:
        required.extend(MODULE_REQUIRED.get(module, []))

    print("Profile:")
    print(f"  status              {profile.get('profile_status', 'INVALID')}")
    print(f"  selected modules    {', '.join(modules) if modules else 'none'}")
    unresolved = profile.get("unresolved_profile_questions", [])
    unresolved_count = len(unresolved) if isinstance(unresolved, list) else "invalid"
    print(f"  unresolved questions {unresolved_count}")
    for error in profile_errors:
        print(f"  FAIL                {error}")
    if profile.get("profile_status") == "PROVISIONAL":
        print("  NOTE                profile review is still required before research assumptions are treated as settled")
    print("  NOTE                exact-target freezing and mathematical verification remain separate dossier gates")
    print("")

    print("Required structural paths:")
    for rel in dict.fromkeys(required):
        exists = (ROOT / rel).exists()
        print(f"  {rel:45} {'OK' if exists else 'missing'}")
        structural_ok = structural_ok and exists
    print("")

    config = ROOT / ".codex/config.toml"
    if config.exists():
        toml_ok, message = basic_toml_check(config)
        print(f"Codex config: {'OK' if toml_ok else 'FAIL'} - {message}")
        structural_ok = structural_ok and toml_ok

    repository_helper = ROOT / "scripts/repository_first.py"
    repository_result = subprocess.run(
        [sys.executable, "-I", "-B", str(repository_helper), "validate", "--json"],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=60,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    repository_message = (
        repository_result.stdout.strip()
        if repository_result.returncode == 0
        else (repository_result.stdout + " " + repository_result.stderr).strip()
    )
    print(
        f"Repository-first policy: {'OK' if repository_result.returncode == 0 else 'FAIL'}"
        f" - {repository_message[-1000:]}"
    )
    structural_ok = structural_ok and repository_result.returncode == 0

    release_helper = ROOT / "scripts/research_release.py"
    release_result = subprocess.run(
        [sys.executable, "-I", "-B", str(release_helper), "validate", "--json"],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=60,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    release_message = (
        release_result.stdout.strip()
        if release_result.returncode == 0
        else (release_result.stdout + " " + release_result.stderr).strip()
    )
    print(
        f"Research artifact releases: {'OK' if release_result.returncode == 0 else 'FAIL'}"
        f" - {release_message[-1000:]}"
    )
    structural_ok = structural_ok and release_result.returncode == 0

    if "formalization" in modules:
        state_ok, state_message = lean_room_state_check()
        print(f"Lean Room state: {'OK' if state_ok else 'FAIL'} - {state_message}")
        print("Lean Room kill switch: «Отключи Lean-комнату.»")
        structural_ok = structural_ok and state_ok

    print("")
    print("Profile-relevant capabilities:")
    capabilities_ok = True
    relevant_tools = set()
    for requirement in capability_requirements(profile):
        alternatives = requirement["alternatives"]
        if requirement.get("check") == "macos-seatbelt":
            available, detected = macos_seatbelt_available()
        else:
            available, detected = capability_available(alternatives)
        relevant_tools.update(tool for group in alternatives for tool in group)
        capabilities_ok = capabilities_ok and available
        detail = ", ".join(detected) if detected else "none detected"
        print(
            f"  {'OK' if available else 'MISSING':7} {requirement['name']} "
            f"[{alternatives_text(alternatives)}] — {requirement['reason']}; {detail}"
        )

    print("")
    print("Optional helpers (never fatal by themselves):")
    for tool, reason in OPTIONAL_TOOLS.items():
        if tool in relevant_tools:
            continue
        found = shutil.which(tool)
        print(f"  {tool:10} {'available' if found else 'missing':9} — {reason}")

    if "computation" in modules:
        print("  NOTE       the computation module is backend-neutral; record and check the exact software per computation")
    if "external_llm" in modules:
        print("  NOTE       the external_llm module requires explicit user-directed external use, not a local CLI")
    if "deep_research_goal" in modules:
        print("  NOTE       deep-goal budgets start no work and never promote mathematical status")
    if "discovery_portfolio" in modules:
        print("  NOTE       discovery phases are workflow state, never mathematical or novelty status")
    if "team_collaboration" in modules:
        print("  NOTE       Git/GitHub bootstrap is a separate explicit post-generation action")
    if "formalization" in modules:
        print("  NOTE       capability discovery does not prove that a case's exact pinned toolchain is installed; the guarded verifier checks that pin and hashes its binaries")
    if staged_pdf_present(profile):
        print("  NOTE       scanned PDFs may still require OCR and a manual extraction-quality check")

    print("")
    writable = os.access(ROOT, os.W_OK)
    print(f"Workspace writable: {'OK' if writable else 'NO'}")
    print("External monitoring: disabled by default")
    print("GitHub remote: not configured by this scaffold")
    print("")
    print(f"Structural readiness: {'PASS' if structural_ok else 'FAIL'}")
    print(f"Profile-relevant capabilities: {'PASS' if capabilities_ok else 'INCOMPLETE'}")
    if not args.strict_capabilities and not capabilities_ok:
        print("NOTE missing capabilities are informational in default mode; rerun with --strict-capabilities to make them fatal")
    if args.strict_capabilities:
        print("Strict capability mode: enabled")
    return 0 if structural_ok and (capabilities_ok or not args.strict_capabilities) else 1

if __name__ == "__main__":
    raise SystemExit(main())
