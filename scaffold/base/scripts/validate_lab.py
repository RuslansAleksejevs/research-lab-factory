#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
TRACK_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
LAB_TOKEN = re.compile(r"\{\{LAB_[A-Z0-9_]+\}\}")
LAB_KINDS = {"ARTICLE_OR_COHERENT_PROGRAM", "DISCOVERY_PORTFOLIO"}
REQUIRED = [
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
    "README.md",
    "PROJECT_CHARTER.md",
    "USER_PREFERENCES.md",
    "LAB_PROFILE.json",
    "BOOTSTRAP_REPORT.md",
    ".lab/manifest.json",
    ".lab/bootstrap_inputs.json",
    ".lab/user_policy.json",
    ".codex/config.toml",
    ".codex/agents/proof_generator.toml",
    ".codex/agents/adversarial_verifier.toml",
    ".agents/skills/prove-or-refute/SKILL.md",
    ".agents/skills/verify-proof/SKILL.md",
    ".agents/skills/survey-laboratory-state/SKILL.md",
    ".agents/skills/run-research-round/SKILL.md",
    ".agents/skills/steward-laboratory-state/SKILL.md",
    ".agents/skills/steward-laboratory-state/agents/openai.yaml",
    ".agents/skills/record-research-checkpoint/SKILL.md",
    ".agents/skills/run-external-research-bridge/SKILL.md",
    ".agents/skills/run-external-research-bridge/agents/openai.yaml",
    ".lab/control_room_actions.json",
    ".lab/durable_research_memory.json",
    "knowledge/results_ledger.yaml",
    "knowledge/research_state.yaml",
    "knowledge/resume.md",
    "knowledge/laboratory_overview.md",
    "knowledge/laboratory_survey_state.json",
    "sources/manifests/source_registry.yaml",
    "problems/templates/problem_dossier/context_envelope.md",
    "problems/templates/problem_dossier/proof_search_state.yaml",
    "scripts/new_problem.py",
    "scripts/laboratory_survey.py",
    "scripts/research_round.py",
    "scripts/research_memory.py",
    "scripts/laboratory_stewardship.py",
    "scripts/repository_first.py",
    "scripts/research_release.py",
    "scripts/validate_proof_search.py",
    "templates/attack_surface.md",
    "workflows/hard_math_search_orchestration.md",
    "workflows/proof_protocol.md",
    "workflows/research_directions_protocol.md",
    "templates/proof_attempt.md",
    "templates/search_round_report.md",
    "templates/research_direction.md",
    "templates/research_round_plan.json",
    "templates/research_round_result.json",
    "templates/laboratory_survey.md",
    "templates/laboratory_stewardship_plan.json",
    "templates/laboratory_stewardship_report.md",
    "templates/research_checkpoint.md",
    "templates/research_checkpoint.json",
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
    "workflows/laboratory_survey_protocol.md",
    "workflows/research_round_protocol.md",
    "workflows/laboratory_stewardship_protocol.md",
    "workflows/repository_first_protocol.md",
    "research/checkpoints/README.md",
    "research/checkpoint_index.json",
    "research/raw_runs/README.md",
    "research/repository_first/README.md",
    "runs/laboratory_surveys/README.md",
    "runs/laboratory_stewardship/README.md",
    "evals/adversarial/laboratory_survey_fragmented_state.md",
    "evals/adversarial/research_round_guarded_execution.md",
    "evals/adversarial/durable_research_memory_incomplete_handoff.md",
    "evals/adversarial/laboratory_stewardship_fragmented_repair.md",
    "evals/adversarial/research_release_guarded_materialization.md",
    "tests/test_laboratory_survey.py",
    "tests/test_research_round.py",
    "tests/test_research_memory.py",
    "tests/test_laboratory_stewardship.py",
    "tests/test_repository_first.py",
    "tests/test_research_release.py",
    "schemas/research_round_plan.schema.json",
    "schemas/research_round_result.schema.json",
    "schemas/research_round_projection.schema.json",
    "schemas/research_checkpoint.schema.json",
    "schemas/repository_first.schema.json",
    "schemas/research_release_request.schema.json",
    "schemas/research_release_package.schema.json",
    "workflows/durable_research_memory_protocol.md",
]

CONTROL_ROOM_ACTIONS_MARKER = {
    "schema_version": 1,
    "protocol_version": 1,
    "actions": ["propose-rounds", "run-rounds", "collect-rounds"],
    "projection_path_template": "research/rounds/{round_id}/control_room_status.json",
}

DURABLE_RESEARCH_MEMORY_MARKER = {
    "schema_version": 1,
    "protocol_version": 1,
    "capability": "durable-research-memory",
    "helper_path": "scripts/research_memory.py",
    "checkpoint_path_prefix": "research/checkpoints/",
    "index_path": "research/checkpoint_index.json",
}
MAX_DURABLE_JSON_BYTES = 16 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
POLICY_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,127}$")
POLICY_MARKER_RE = re.compile(r"^[a-z][a-z0-9-]*:v[1-9][0-9]*$")


def safe_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    pieces: List[str] = []
    separator = False
    for character in normalized:
        if character.isalnum():
            if separator and pieces:
                pieces.append("-")
            pieces.append(character)
            separator = False
        elif pieces:
            separator = True
    base = "".join(pieces).strip("-")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:10]
    if not base:
        return f"lab-{digest}"
    encoded = base.encode("utf-8")
    if len(encoded) <= 100 and all(ord(character) < 128 for character in base):
        return base
    shortened: List[str] = []
    used = 0
    for character in base:
        size = len(character.encode("utf-8"))
        if used + size > 100:
            break
        shortened.append(character)
        used += size
    return f"{''.join(shortened).rstrip('-') or 'lab'}-{digest}"


def valid_process_steward_text(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= 256
        and unicodedata.normalize("NFC", value) == value
        and len(value.splitlines()) == 1
        and not any(
            character in {"\u2028", "\u2029"}
            or unicodedata.category(character) == "Cc"
            for character in value
        )
    )


def load_json(path: Path, errors: List[str]) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"cannot parse {path.relative_to(ROOT)}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path.relative_to(ROOT)} must contain an object")
        return {}
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_regular_bytes(
    path: Path,
    label: str,
    errors: List[str],
    *,
    maximum: int = MAX_DURABLE_JSON_BYTES,
    expected_mode: Optional[int] = None,
) -> Optional[bytes]:
    """Read one bounded regular file without a blocking regular-to-FIFO race."""

    try:
        before = path.lstat()
    except FileNotFoundError:
        errors.append(f"missing {label}: {path.relative_to(ROOT)}")
        return None
    except OSError as exc:
        errors.append(f"cannot inspect {label} {path.relative_to(ROOT)}: {exc}")
        return None
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        errors.append(f"{label} must be a regular file: {path.relative_to(ROOT)}")
        return None
    if before.st_size > maximum:
        errors.append(f"{label} exceeds {maximum} bytes: {path.relative_to(ROOT)}")
        return None

    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        errors.append(f"cannot safely open {label} {path.relative_to(ROOT)}: {exc}")
        return None
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            errors.append(f"{label} changed type while opening: {path.relative_to(ROOT)}")
            return None
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            errors.append(f"{label} changed identity while opening: {path.relative_to(ROOT)}")
            return None
        if expected_mode is not None and stat.S_IMODE(opened.st_mode) != expected_mode:
            errors.append(
                f"{label} must have mode {expected_mode:04o}: {path.relative_to(ROOT)}"
            )
            return None
        chunks: List[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
    except OSError as exc:
        errors.append(f"cannot safely read {label} {path.relative_to(ROOT)}: {exc}")
        return None
    finally:
        os.close(descriptor)

    if len(data) > maximum:
        errors.append(f"{label} exceeds {maximum} bytes: {path.relative_to(ROOT)}")
        return None
    stable_before = (
        opened.st_dev,
        opened.st_ino,
        opened.st_size,
        stat.S_IMODE(opened.st_mode),
        opened.st_mtime_ns,
        opened.st_ctime_ns,
        opened.st_nlink,
    )
    stable_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        stat.S_IMODE(after.st_mode),
        after.st_mtime_ns,
        after.st_ctime_ns,
        after.st_nlink,
    )
    if stable_before != stable_after or len(data) != after.st_size:
        errors.append(f"{label} changed while being read: {path.relative_to(ROOT)}")
        return None
    try:
        current = path.lstat()
    except OSError as exc:
        errors.append(f"{label} changed after being read: {path.relative_to(ROOT)}: {exc}")
        return None
    if (
        stat.S_ISLNK(current.st_mode)
        or not stat.S_ISREG(current.st_mode)
        or (
            current.st_dev,
            current.st_ino,
            current.st_size,
            stat.S_IMODE(current.st_mode),
            current.st_mtime_ns,
            current.st_ctime_ns,
            current.st_nlink,
        )
        != stable_after
    ):
        errors.append(f"{label} changed after being read: {path.relative_to(ROOT)}")
        return None
    return data


def load_json_bytes(path: Path, data: bytes, errors: List[str]) -> Dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except Exception as exc:
        errors.append(f"cannot parse {path.relative_to(ROOT)}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path.relative_to(ROOT)} must contain an object")
        return {}
    return value


def check_tree(errors: List[str]) -> None:
    for path in ROOT.rglob("*"):
        mode = path.lstat().st_mode
        relative = path.relative_to(ROOT)
        if stat.S_ISLNK(mode):
            errors.append(f"symlink is forbidden: {relative}")
        elif not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            errors.append(f"special file is forbidden: {relative}")
        if path.name == "__pycache__" or (
            stat.S_ISREG(mode) and path.suffix in {".pyc", ".pyo"}
        ):
            errors.append(f"interpreter cache is forbidden: {relative}")


def check_skill_frontmatter(errors: List[str]) -> None:
    for path in sorted((ROOT / ".agents/skills").glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            errors.append(f"skill lacks YAML frontmatter: {path.relative_to(ROOT)}")
            continue
        try:
            end = lines[1:].index("---") + 1
        except ValueError:
            errors.append(f"skill frontmatter is not closed: {path.relative_to(ROOT)}")
            continue
        header = "\n".join(lines[1:end])
        if not re.search(r"^name:\s*[a-z0-9-]+\s*$", header, flags=re.MULTILINE):
            errors.append(f"skill name is missing or invalid: {path.relative_to(ROOT)}")
        if not re.search(r"^description:\s*\S", header, flags=re.MULTILINE):
            errors.append(f"skill description is missing: {path.relative_to(ROOT)}")


def check_profile(profile: Dict[str, Any], errors: List[str]) -> None:
    if profile.get("schema_version") != 1:
        errors.append("LAB_PROFILE schema_version must equal 1")
    if profile.get("profile_status") not in {"READY", "PROVISIONAL"}:
        errors.append("LAB_PROFILE profile_status is invalid")
    decisions = profile.get("profile_decisions")
    if not isinstance(decisions, list) or not decisions:
        errors.append("LAB_PROFILE profile_decisions must be a non-empty array")
    else:
        allowed_decisions = {
            "user_confirmed",
            "evidence_backed_inference",
            "factory_default",
            "assumption",
        }
        for index, decision in enumerate(decisions):
            if not isinstance(decision, dict):
                errors.append(f"profile_decisions[{index}] must be an object")
                continue
            if not isinstance(decision.get("field"), str) or not decision.get("field"):
                errors.append(f"profile_decisions[{index}] has no field")
            if decision.get("classification") not in allowed_decisions:
                errors.append(f"profile_decisions[{index}] has invalid classification")
            if not isinstance(decision.get("basis"), str) or not decision.get("basis"):
                errors.append(f"profile_decisions[{index}] has no basis")
            if decision.get("confidence") not in {"low", "medium", "high"}:
                errors.append(f"profile_decisions[{index}] has invalid confidence")
    intake_report = profile.get("bootstrap_intake_report")
    if not isinstance(intake_report, dict):
        errors.append("LAB_PROFILE bootstrap_intake_report must be an object")
    else:
        for category in ["unreadable_items", "unclassified_items", "ignored_items"]:
            items = intake_report.get(category)
            if not isinstance(items, list):
                errors.append(f"bootstrap_intake_report.{category} must be an array")
                continue
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    errors.append(f"bootstrap_intake_report.{category}[{index}] must be an object")
                    continue
                name = item.get("name")
                if not isinstance(name, str) or not name:
                    errors.append(f"bootstrap_intake_report.{category}[{index}] has no name")
                elif Path(name).is_absolute() or "/" in name or "\\" in name:
                    errors.append(f"bootstrap_intake_report.{category}[{index}] name is not portable")
                if not isinstance(item.get("reason"), str) or not item.get("reason"):
                    errors.append(f"bootstrap_intake_report.{category}[{index}] has no reason")
    lab = profile.get("lab")
    research = profile.get("research")
    if not isinstance(lab, dict):
        errors.append("LAB_PROFILE.lab must be an object")
        return
    if not isinstance(research, dict):
        errors.append("LAB_PROFILE.research must be an object")
        return
    kind = lab.get("kind")
    if kind not in LAB_KINDS:
        errors.append("LAB_PROFILE lab.kind is invalid")
    modules = lab.get("modules")
    if not isinstance(modules, list) or not all(isinstance(item, str) for item in modules):
        errors.append("LAB_PROFILE lab.modules must be an array of strings")
        modules = []
    if kind == "DISCOVERY_PORTFOLIO" and "discovery_portfolio" not in modules:
        errors.append("DISCOVERY_PORTFOLIO profile lacks discovery_portfolio module")
    if "discovery_portfolio" in modules and kind != "DISCOVERY_PORTFOLIO":
        errors.append("discovery_portfolio module requires DISCOVERY_PORTFOLIO kind")
    collaboration = lab.get("collaboration")
    if "team_collaboration" in modules:
        if not isinstance(collaboration, dict):
            errors.append("team_collaboration module requires lab.collaboration")
        else:
            members = collaboration.get("members")
            if not isinstance(members, list) or len(members) < 2:
                errors.append("lab.collaboration must contain at least two members")
            member_ids = {
                item.get("id")
                for item in members or []
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            if collaboration.get("steward_id") not in member_ids:
                errors.append("lab.collaboration.steward_id is not a declared member")
            governance = collaboration.get("governance")
            if not isinstance(governance, dict) or any(
                governance.get(key) != "CONSENSUS"
                for key in ["research_decisions", "spinout_decisions", "publication_decisions"]
            ):
                errors.append("team research/spinout/publication governance must require CONSENSUS")
    elif collaboration is not None:
        errors.append("lab.collaboration exists without team_collaboration module")
    tracks = research.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        errors.append("LAB_PROFILE research.tracks must be non-empty")
        return
    track_ids: List[str] = []
    for item in tracks:
        track_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(track_id, str) or not TRACK_ID.fullmatch(track_id):
            errors.append(f"invalid track id: {track_id!r}")
        else:
            track_ids.append(track_id)
            if not (ROOT / "research/tracks" / track_id / "README.md").is_file():
                errors.append(f"missing research track directory for {track_id}")
    if len(track_ids) != len(set(track_ids)):
        errors.append("track ids are not unique")
    if research.get("default_track") not in track_ids:
        errors.append("default_track does not reference a declared track")
    problem = research.get("initial_problem")
    if problem is not None and (not isinstance(problem, dict) or problem.get("track") not in track_ids):
        errors.append("initial_problem is invalid or references an undeclared track")
    materials = profile.get("bootstrap_materials", [])
    if not isinstance(materials, list):
        errors.append("bootstrap_materials must be an array")
    else:
        for item in materials:
            if not isinstance(item, dict):
                errors.append("bootstrap material must be an object")
                continue
            stored = item.get("stored_name")
            if not isinstance(stored, str) or Path(stored).is_absolute() or ".." in Path(stored).parts:
                errors.append(f"unsafe bootstrap stored_name: {stored!r}")


def check_manifest(manifest: Dict[str, Any], profile: Dict[str, Any], errors: List[str], warnings: List[str]) -> None:
    if manifest.get("schema_version") != 1:
        errors.append("manifest schema_version must equal 1")
    if manifest.get("template_id") != "math-research-lab-template":
        errors.append("manifest template_id is invalid")
    if manifest.get("directory_name") != profile.get("lab", {}).get("directory_name"):
        errors.append("manifest directory_name disagrees with LAB_PROFILE")
    if manifest.get("lab_kind") != profile.get("lab", {}).get("kind"):
        errors.append("manifest lab_kind disagrees with LAB_PROFILE")
    if not isinstance(manifest.get("template_version"), str) or not manifest.get("template_version"):
        errors.append("manifest template_version is missing")
    scaffold_digest = manifest.get("scaffold_sha256")
    if not isinstance(scaffold_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", scaffold_digest):
        errors.append("manifest scaffold_sha256 is invalid")
    profile_digest = manifest.get("profile_sha256")
    current_profile_digest = sha256(ROOT / "LAB_PROFILE.json")
    if profile_digest != current_profile_digest:
        warnings.append("LAB_PROFILE differs from its bootstrap digest; review the recorded change")
    inputs = manifest.get("bootstrap_inputs")
    if not isinstance(inputs, list):
        errors.append("manifest bootstrap_inputs must be an array")
    else:
        for item in inputs:
            if not isinstance(item, dict):
                errors.append("manifest bootstrap input must be an object")
                continue
            relative = item.get("stored_name")
            expected = item.get("sha256")
            if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
                errors.append(f"unsafe manifest stored_name: {relative!r}")
                continue
            path = ROOT / relative
            if not path.is_file() or path.is_symlink():
                errors.append(f"missing immutable bootstrap input: {relative}")
            elif sha256(path) != expected:
                errors.append(f"bootstrap input digest mismatch: {relative}")
    dossier = manifest.get("initial_dossier")
    if dossier is not None:
        if not isinstance(dossier, str) or Path(dossier).is_absolute() or ".." in Path(dossier).parts:
            errors.append("manifest initial_dossier is unsafe")
        elif not (ROOT / dossier).is_dir():
            errors.append(f"manifest initial_dossier is missing: {dossier}")
    inventory = manifest.get("initial_inventory")
    if not isinstance(inventory, list):
        errors.append("manifest initial_inventory must be an array")
    validation = manifest.get("validation")
    expected_gates = {"doctor", "lab-structure", "ledgers", "proof-search", "smoke-eval"}
    if not isinstance(validation, list):
        errors.append("manifest validation must be an array")
    else:
        passed_gates = {
            item.get("name")
            for item in validation
            if isinstance(item, dict) and item.get("status") == "PASS"
        }
        missing_gates = sorted(expected_gates - passed_gates)
        bootstrap_report = ROOT / "BOOTSTRAP_REPORT.md"
        bootstrap_pending = (
            bootstrap_report.is_file()
            and "Status: `PENDING`." in bootstrap_report.read_text(encoding="utf-8")
        )
        if missing_gates and not bootstrap_pending:
            errors.append("manifest lacks passing generation gates: " + ", ".join(missing_gates))
    bootstrap_file = ROOT / ".lab/bootstrap_inputs.json"
    try:
        bootstrap_inputs = json.loads(bootstrap_file.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"cannot parse .lab/bootstrap_inputs.json: {exc}")
    else:
        if bootstrap_inputs != inputs:
            errors.append("bootstrap_inputs.json disagrees with manifest")


def valid_repository_first(value: Any) -> bool:
    if not isinstance(value, dict) or type(value.get("enabled")) is not bool:
        return False
    if value["enabled"] is False:
        return set(value) == {"enabled"}
    return (
        set(value)
        == {
            "enabled",
            "canonical_repository_visibility",
            "raw_material_policy",
            "export_policy",
            "process_steward",
        }
        and value.get("canonical_repository_visibility") == "PRIVATE"
        and value.get("raw_material_policy") == "LOCAL_UNTRACKED"
        and value.get("export_policy") == "REVIEWED_ONLY"
        and valid_process_steward_text(value.get("process_steward"))
    )


def valid_user_policy_binding(value: Any, *, manifest_view: bool) -> bool:
    if not isinstance(value, dict):
        return False
    base_keys = {
        "schema_version",
        "profile_id",
        "revision",
        "portable_view",
        "portable_sections",
        "private_exclusions",
    }
    expected = base_keys | ({"sidecar_path", "sidecar_sha256"} if manifest_view else set())
    if set(value) != expected:
        return False
    if (
        value.get("schema_version") != 1
        or not isinstance(value.get("profile_id"), str)
        or POLICY_ID_RE.fullmatch(value["profile_id"]) is None
        or type(value.get("revision")) is not int
        or value["revision"] < 1
    ):
        return False
    portable = value.get("portable_view")
    if (
        not isinstance(portable, dict)
        or set(portable) != {"path", "sha256"}
        or portable.get("path") != "USER_PREFERENCES.md"
        or not isinstance(portable.get("sha256"), str)
        or SHA256_RE.fullmatch(portable["sha256"]) is None
    ):
        return False
    sections = value.get("portable_sections")
    if not isinstance(sections, list) or not sections or len(sections) > 128:
        return False
    seen_sections = set()
    seen_markers = set()
    for section in sections:
        if (
            not isinstance(section, dict)
            or set(section) != {"id", "revision", "marker"}
            or not isinstance(section.get("id"), str)
            or POLICY_ID_RE.fullmatch(section["id"]) is None
            or type(section.get("revision")) is not int
            or section["revision"] < 1
            or not isinstance(section.get("marker"), str)
            or POLICY_MARKER_RE.fullmatch(section["marker"]) is None
            or section["id"] in seen_sections
            or section["marker"] in seen_markers
        ):
            return False
        seen_sections.add(section["id"])
        seen_markers.add(section["marker"])
    exclusions = value.get("private_exclusions")
    if not isinstance(exclusions, list) or len(exclusions) > 128:
        return False
    seen_exclusions = set()
    for exclusion in exclusions:
        if (
            not isinstance(exclusion, dict)
            or set(exclusion) != {"id", "revision", "copy_policy"}
            or not isinstance(exclusion.get("id"), str)
            or POLICY_ID_RE.fullmatch(exclusion["id"]) is None
            or type(exclusion.get("revision")) is not int
            or exclusion["revision"] < 1
            or exclusion.get("copy_policy") != "NEVER_COPY_TO_LABS_OR_CORE_BUNDLES"
            or exclusion["id"] in seen_exclusions
        ):
            return False
        seen_exclusions.add(exclusion["id"])
    if manifest_view and (
        value.get("sidecar_path") != ".lab/user_policy.json"
        or not isinstance(value.get("sidecar_sha256"), str)
        or SHA256_RE.fullmatch(value["sidecar_sha256"]) is None
    ):
        return False
    return True


def check_user_and_repository_policy(
    profile: Dict[str, Any], manifest: Dict[str, Any], errors: List[str]
) -> None:
    profile_policy = profile.get("user_policy")
    manifest_policy = manifest.get("user_policy")
    if not valid_user_policy_binding(profile_policy, manifest_view=False):
        errors.append("LAB_PROFILE user_policy binding is invalid")
        return
    if not valid_user_policy_binding(manifest_policy, manifest_view=True):
        errors.append("origin manifest user_policy binding is invalid")
        return
    manifest_profile_view = {
        key: value
        for key, value in manifest_policy.items()
        if key not in {"sidecar_path", "sidecar_sha256"}
    }
    if manifest_profile_view != profile_policy:
        errors.append("origin manifest user_policy disagrees with LAB_PROFILE")

    sidecar_path = ROOT / ".lab/user_policy.json"
    preferences_path = ROOT / "USER_PREFERENCES.md"
    sidecar = load_json(sidecar_path, errors) if sidecar_path.is_file() else {}
    if sidecar != profile_policy:
        errors.append(".lab/user_policy.json disagrees with LAB_PROFILE")
    if sidecar_path.is_file() and sha256(sidecar_path) != manifest_policy.get("sidecar_sha256"):
        errors.append("user-policy sidecar SHA-256 disagrees with origin manifest")
    if preferences_path.is_file() and sha256(preferences_path) != profile_policy["portable_view"]["sha256"]:
        errors.append("USER_PREFERENCES.md SHA-256 disagrees with user-policy binding")
    try:
        preferences_text = preferences_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"cannot read USER_PREFERENCES.md as UTF-8: {exc}")
    else:
        for section in profile_policy["portable_sections"]:
            opening = f"<!-- {section['marker']} -->"
            closing = f"<!-- /{section['marker']} -->"
            if preferences_text.count(opening) != 1 or preferences_text.count(closing) != 1:
                errors.append(f"portable user-policy marker is missing or duplicated: {section['marker']}")
            elif preferences_text.index(opening) >= preferences_text.index(closing):
                errors.append(f"portable user-policy marker order is invalid: {section['marker']}")

    profile_repository = profile.get("repository_first")
    manifest_repository = manifest.get("repository_first")
    if not valid_repository_first(profile_repository):
        errors.append("LAB_PROFILE repository_first policy is invalid")
    if not valid_repository_first(manifest_repository):
        errors.append("origin manifest repository_first policy is invalid")
    if profile_repository != manifest_repository:
        errors.append("origin manifest repository_first disagrees with LAB_PROFILE")
    if isinstance(profile_repository, dict) and profile_repository.get("enabled") is True:
        lab = profile.get("lab") if isinstance(profile.get("lab"), dict) else {}
        modules = lab.get("modules") if isinstance(lab.get("modules"), list) else []
        collaboration = lab.get("collaboration")
        process_steward = profile_repository.get("process_steward")
        if "team_collaboration" in modules:
            if not isinstance(collaboration, dict):
                errors.append("repository_first team policy requires lab.collaboration")
            else:
                if process_steward != collaboration.get("steward_id"):
                    errors.append("repository_first process steward disagrees with team steward")
                repository = collaboration.get("repository")
                if not isinstance(repository, dict) or repository.get("visibility") != "PRIVATE":
                    errors.append("repository_first team policy requires PRIVATE repository visibility")
        else:
            owners = lab.get("owners") if isinstance(lab.get("owners"), list) else []
            allowed = {
                candidate
                for owner in owners
                if isinstance(owner, str)
                for candidate in (owner, safe_slug(owner))
            }
            if process_steward not in allowed:
                errors.append(
                    "repository_first process steward must match a solo owner name or normalized owner id"
                )

    inventory = manifest.get("initial_inventory")
    if isinstance(inventory, list):
        by_path = {
            item.get("path"): item
            for item in inventory
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        expected = {
            "USER_PREFERENCES.md": profile_policy["portable_view"]["sha256"],
            ".lab/user_policy.json": manifest_policy["sidecar_sha256"],
        }
        for relative, digest in expected.items():
            item = by_path.get(relative)
            if (
                not isinstance(item, dict)
                or item.get("ownership") != "generated-once"
                or item.get("sha256") != digest
            ):
                errors.append(f"origin inventory does not bind generated-once {relative}")


def check_tokens(manifest: Dict[str, Any], errors: List[str]) -> None:
    inventory = manifest.get("initial_inventory", [])
    if not isinstance(inventory, list):
        return
    for item in inventory:
        if not isinstance(item, dict) or item.get("ownership") == "lab-owned":
            continue
        relative = item.get("path")
        if not isinstance(relative, str):
            continue
        path = ROOT / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if LAB_TOKEN.search(text):
            errors.append(f"unresolved LAB token in {relative}")


def check_research_round(errors: List[str]) -> None:
    marker_path = ROOT / ".lab/control_room_actions.json"
    if marker_path.is_file():
        marker = load_json(marker_path, errors)
        if marker != CONTROL_ROOM_ACTIONS_MARKER:
            errors.append(".lab/control_room_actions.json is incompatible")
        elif stat.S_IMODE(marker_path.lstat().st_mode) != 0o644:
            errors.append(".lab/control_room_actions.json must have mode 0644")
    for relative in [
        "schemas/research_round_plan.schema.json",
        "schemas/research_round_result.schema.json",
        "schemas/research_round_projection.schema.json",
        "templates/research_round_plan.json",
        "templates/research_round_result.json",
    ]:
        path = ROOT / relative
        if path.is_file():
            load_json(path, errors)
    helper = ROOT / "scripts/research_round.py"
    if not helper.is_file() or not marker_path.is_file():
        return
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(helper), "validate"],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=60,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode != 0:
        output = (result.stdout + "\n" + result.stderr).strip()
        errors.append("research-round state validation failed: " + output[-4000:])


def check_research_memory(errors: List[str]) -> None:
    marker_path = ROOT / ".lab/durable_research_memory.json"
    try:
        marker_exists = marker_path.lstat() is not None
    except FileNotFoundError:
        marker_exists = False
    except OSError as exc:
        errors.append(f"cannot inspect .lab/durable_research_memory.json: {exc}")
        marker_exists = False
    if marker_exists:
        marker_bytes = safe_regular_bytes(
            marker_path,
            "durable research-memory marker",
            errors,
            expected_mode=0o644,
        )
        expected_marker_bytes = (
            json.dumps(
                DURABLE_RESEARCH_MEMORY_MARKER,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        if marker_bytes is not None:
            marker = load_json_bytes(marker_path, marker_bytes, errors)
            if (
                marker != DURABLE_RESEARCH_MEMORY_MARKER
                or marker_bytes != expected_marker_bytes
            ):
                errors.append(".lab/durable_research_memory.json is incompatible")
    for relative in [
        "schemas/research_checkpoint.schema.json",
        "templates/research_checkpoint.json",
        "research/checkpoint_index.json",
    ]:
        path = ROOT / relative
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            errors.append(f"cannot inspect {relative}: {exc}")
            continue
        data = safe_regular_bytes(path, relative, errors)
        if data is not None:
            load_json_bytes(path, data, errors)
    helper = ROOT / "scripts/research_memory.py"
    if not helper.is_file():
        return
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(helper), "validate"],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=60,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode != 0:
        output = (result.stdout + "\n" + result.stderr).strip()
        errors.append("durable research-memory validation failed: " + output[-4000:])


def check_terminal_setting(errors: List[str]) -> None:
    helper = ROOT / "scripts/claude_terminal/claude_runner.py"
    if not helper.is_file():
        return
    result = subprocess.run(
        [sys.executable, "-B", str(helper), "integration-status"],
        cwd=str(ROOT), text=True, capture_output=True, timeout=30,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode != 0:
        errors.append("terminal integration setting: " + (result.stdout + result.stderr)[-2000:])


def check_repository_first(errors: List[str]) -> None:
    helper = ROOT / "scripts/repository_first.py"
    if not helper.is_file():
        return
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(helper), "validate"],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=60,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode != 0:
        output = (result.stdout + "\n" + result.stderr).strip()
        errors.append("repository-first validation failed: " + output[-4000:])


def check_research_release(errors: List[str]) -> None:
    helper = ROOT / "scripts/research_release.py"
    if not helper.is_file():
        return
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(helper), "validate", "--json"],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=60,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode != 0:
        output = (result.stdout + "\n" + result.stderr).strip()
        errors.append("research artifact release validation failed: " + output[-4000:])


def main() -> int:
    errors: List[str] = []
    warnings: List[str] = []
    for relative in REQUIRED:
        if not (ROOT / relative).exists():
            errors.append(f"missing required path: {relative}")
    check_tree(errors)
    profile = load_json(ROOT / "LAB_PROFILE.json", errors) if (ROOT / "LAB_PROFILE.json").is_file() else {}
    manifest = load_json(ROOT / ".lab/manifest.json", errors) if (ROOT / ".lab/manifest.json").is_file() else {}
    if profile:
        check_profile(profile, errors)
    if manifest and profile:
        check_manifest(manifest, profile, errors, warnings)
        check_user_and_repository_policy(profile, manifest, errors)
        check_tokens(manifest, errors)
    check_skill_frontmatter(errors)
    check_research_round(errors)
    check_research_memory(errors)
    check_terminal_setting(errors)
    check_repository_first(errors)
    check_research_release(errors)

    for warning in warnings:
        print(f"WARN {warning}")
    for error in errors:
        print(f"FAIL {error}")
    if errors:
        return 1
    print("OK laboratory structure and bootstrap provenance")
    print("NOTE structural validation does not verify mathematics, sources, novelty, or run independence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
