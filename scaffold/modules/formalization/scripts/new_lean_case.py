#!/usr/bin/env python3
"""Create a no-clobber DRAFT case in the guarded Lean Room."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Sequence

from lean_room import (
    EXIT_OK,
    LEAN_ROOM_AUDIT_COMMAND_SCHEMA,
    LEAN_ROOM_BUILD_COMMAND_SCHEMA,
    LeanRoomError,
    ValidationError,
    atomic_write_bytes,
    atomic_write_json,
    case_path,
    discover_root,
    project_tree_inventory,
    publish_directory_noreplace,
    require_room_enabled,
    require_same_room_binding,
    safe_relative_file,
    sha256_file,
    state_lock,
    utc_now,
    validate_lean_name,
    validate_toolchain,
)


TOKEN_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


def _nonempty(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        raise ValidationError(f"{label} must be nonempty")
    return value


def _artifact_binding(
    root: Path, problem: Path, relative: str | None, label: str
) -> tuple[str | None, str | None]:
    if relative is None:
        return None, None
    path = safe_relative_file(root, relative, label)
    try:
        path.relative_to(problem)
    except ValueError as exc:
        raise ValidationError(f"{label} must be inside the same problem dossier") from exc
    cases_root = problem / "formalization/cases"
    try:
        path.relative_to(cases_root)
    except ValueError:
        pass
    else:
        raise ValidationError(f"{label} cannot bind a Lean case artifact")
    return path.relative_to(root).as_posix(), sha256_file(path)


def _load_contract_template(root: Path) -> dict[str, Any]:
    path = root / "templates/lean_room/formalization_contract.yaml"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Cannot read canonical Lean contract template: {exc}") from exc
    if not isinstance(value, dict) or value.get("record_type") != "lean_formalization_contract":
        raise ValidationError("Canonical Lean contract template has an invalid schema")
    return value


def _load_json_template(path: Path, record_type: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Cannot read {label}: {exc}") from exc
    if not isinstance(value, dict) or value.get("record_type") != record_type:
        raise ValidationError(f"{label} has an invalid schema")
    return value


def _render_correspondence(root: Path, values: dict[str, str]) -> str:
    template_path = root / "templates/lean_room/formal_correspondence.md"
    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationError(f"Cannot read formal correspondence template: {exc}") from exc

    def replace(match: re.Match[str]) -> str:
        return values.get(match.group(1), "OPEN — complete before independent LR4 audit")

    return TOKEN_RE.sub(replace, template)


def _package_name(problem_id: str, case_id: str) -> str:
    raw = f"LeanRoom_{problem_id}_{case_id}"
    value = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    value = re.sub(r"_+", "_", value)
    if value[0].isdigit():
        value = "LeanRoom_" + value
    return value[:120]


def _write_project(
    project: Path,
    package_name: str,
    toolchain: str,
    theorem_name: str,
    exact_type: str | None,
) -> None:
    project.mkdir(parents=True)
    namespace, _, short_name = theorem_name.rpartition(".")
    declaration_hint = (
        f"theorem {short_name} : {exact_type} := by\n"
        "  -- Supply a kernel-checked proof without admissions.\n"
        if exact_type
        else f"theorem {short_name} : <exact type from contract> := by ...\n"
    )
    main = (
        "/-!\n"
        "Lean Room DRAFT. This file intentionally contains no declaration yet.\n"
        "A generator must implement exactly the frozen declaration without proof\n"
        "admissions, new assumptions, trust escapes, or a nearby/weaker theorem.\n\n"
        f"Required declaration sketch:\n{declaration_hint}"
        "-/\n"
    )
    if namespace:
        main += f"\nnamespace {namespace}\n\nend {namespace}\n"
    lakefile = (
        f'name = "{package_name}"\n'
        'version = "0.1.0"\n'
        'defaultTargets = ["LeanRoomCase"]\n\n'
        "[[lean_lib]]\n"
        'name = "LeanRoomCase"\n'
        'globs = ["Main", "LeanRoomCase"]\n'
    )
    manifest = {
        "version": "1.1.0",
        "packagesDir": ".lake/packages",
        "packages": [],
        "name": package_name,
        "lakeDir": ".lake",
    }
    atomic_write_bytes(project / "lean-toolchain", (toolchain + "\n").encode("utf-8"))
    atomic_write_bytes(project / "lakefile.toml", lakefile.encode("utf-8"))
    atomic_write_json(project / "lake-manifest.json", manifest)
    atomic_write_bytes(project / "LeanRoomCase.lean", b"import Main\n")
    atomic_write_bytes(project / "Main.lean", main.encode("utf-8"))


def create_case(args: argparse.Namespace) -> Path:
    root = discover_root(args.root)
    status = require_room_enabled(root, "Lean case creation")
    theorem_name = validate_lean_name(args.theorem)
    toolchain = validate_toolchain(args.toolchain)
    statement = _nonempty(args.informal_statement, "Informal statement")
    exact_type = args.exact_formal_type.strip() if args.exact_formal_type else None
    if exact_type == "":
        exact_type = None
    target = case_path(root, args.problem_id, args.case_id, must_exist=False)
    problem = target.parents[2]
    target_artifact, target_sha = _artifact_binding(
        root, problem, args.target_artifact, "target artifact"
    )
    obligation_artifact, obligation_sha = _artifact_binding(
        root, problem, args.obligation_artifact, "proof-obligation artifact"
    )
    if target.exists() or target.is_symlink():
        raise ValidationError(f"Lean case already exists: {target}")
    cases = target.parent
    cases.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{args.case_id}.stage-", dir=str(cases)))
    try:
        project = stage / "project"
        package_name = _package_name(args.problem_id, args.case_id)
        _write_project(project, package_name, toolchain, theorem_name, exact_type)
        for relative in (
            "evidence/runs",
            "evidence/freezes",
            "audits",
            "certificates",
        ):
            (stage / relative).mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            stage / "evidence/index.yaml",
            {"schema_version": 1, "record_type": "lean_evidence_index", "runs": [], "freezes": [], "current": None},
        )
        atomic_write_json(
            stage / "audits/index.yaml",
            {"schema_version": 1, "record_type": "lean_audit_index", "audits": [], "current": None},
        )
        atomic_write_json(
            stage / "certificates/index.yaml",
            {"schema_version": 1, "record_type": "lean_certificate_index", "certificates": [], "current": None},
        )
        atomic_write_bytes(
            stage / "README.md",
            (
                f"# Lean Room case: {args.case_id}\n\n"
                f"Problem: `{args.problem_id}`. Lifecycle begins at `DRAFT`.\n"
                "Evidence, audits, and certificates are append-only. Navigation indexes do not confer status.\n"
            ).encode("utf-8"),
        )

        contract = _load_contract_template(root)
        timestamp = utc_now()
        namespace, _, short_name = theorem_name.rpartition(".")
        environment = contract.setdefault("environment", {})
        trusted_boundary = contract.setdefault("trusted_boundary", {})
        lineage = contract.setdefault("lineage", {})
        freeze = contract.setdefault("freeze", {})
        contract.update(
            {
                "case_id": args.case_id,
                "problem_id": args.problem_id,
                "orchestration_profile": args.orchestration_profile,
                "created_at": timestamp,
                "created_by": args.actor,
                "room_state_at_creation": status.effective_state,
                "room_state_binding_at_creation": {
                    "sequence": status.sequence,
                    "artifact_sha256": status.artifact_sha256,
                },
                "status": "DRAFT",
            }
        )
        contract["target_binding"].update(
            {
                "target_id": args.target_id,
                "artifact": target_artifact,
                "artifact_sha256": target_sha,
                "statement_date": args.statement_date,
            }
        )
        contract["obligation_binding"].update(
            {
                "artifact": obligation_artifact,
                "artifact_sha256": obligation_sha,
                "obligation_ids": list(dict.fromkeys(args.obligation_id)),
            }
        )
        contract["informal_claim"]["statement"] = statement
        contract["formal_target"].update(
            {
                "source_file": "Main.lean",
                "namespace": namespace or None,
                "declaration_name": theorem_name,
                "declaration_kind": "theorem",
                "exact_type": exact_type,
                "pretty_print_command": f"#print {theorem_name}",
                "axiom_print_command": f"#print axioms {theorem_name}",
            }
        )
        environment.update(
            {
                "lean_toolchain": toolchain,
                "lean_toolchain_sha256": sha256_file(project / "lean-toolchain"),
                "lakefile_sha256": sha256_file(project / "lakefile.toml"),
                "lake_manifest_artifact": "project/lake-manifest.json",
                "lake_manifest_sha256": sha256_file(project / "lake-manifest.json"),
                "dependency_free": True,
                "dependencies": [],
                "source_tree_inventory": None,
                "source_tree_sha256": None,
                "allowed_build_commands": [
                    list(LEAN_ROOM_BUILD_COMMAND_SCHEMA),
                    list(LEAN_ROOM_AUDIT_COMMAND_SCHEMA),
                ],
                "network_allowed_during_certificate_build": False,
            }
        )
        trusted_boundary["permitted_axioms"] = list(dict.fromkeys(args.permit_axiom))
        creation_run_id = "CREATE-" + timestamp.replace("-", "").replace(
            ":", ""
        ).replace(".", "")
        lineage.update(
            {
                "coordinator_run_ids": [creation_run_id],
                "prohibited_decisive_auditor_run_ids": [creation_run_id],
                "coordinator_agent_ids": [args.actor],
                "prohibited_decisive_auditor_agent_ids": [args.actor],
                "information_exposure_summary": (
                    "At creation only the coordinator is recorded as exposed; "
                    "update this frozen lineage with every generator, material "
                    "reviser, and proposed decisive auditor before LR0."
                ),
            }
        )
        contract["correspondence_obligations"] = list(
            dict.fromkeys(
                args.correspondence_obligation
                or [
                    "CORR-001: independently establish that the exact formal declaration implies the exact frozen informal target"
                ]
            )
        )
        contract["acceptance_criterion"].update(
            {
                "certificate_scope": statement,
                "explicit_nonclaims": [
                    "No claim beyond the exact frozen informal target and named obligation IDs.",
                    "No novelty, priority, attribution, theorem-status, or ledger-status conclusion.",
                ],
            }
        )
        contract["stop_conditions"] = [
            "Stop if the formal declaration changes the frozen hypotheses, domains, quantifiers, or conclusion.",
            "Stop if the pinned toolchain is unavailable or any unapproved trust assumption is required.",
            "Stop if exact informal-to-formal correspondence remains unresolved.",
        ]
        freeze.update(
            {
                "lr0_contract_frozen": False,
                "lr0_frozen_at": None,
                "lr0_frozen_by": None,
                "lr0_payload_sha256": None,
                "lr1_sources_frozen": False,
                "lr1_frozen_at": None,
                "lr1_frozen_by": None,
                "frozen_source_tree_sha256": None,
                "frozen_contract_sha256": None,
            }
        )
        atomic_write_json(stage / "formalization_contract.yaml", contract)
        _, draft_source_digest = project_tree_inventory(project)
        correspondence_values = {
            "CASE_ID": args.case_id,
            "PROBLEM_ID": args.problem_id,
            "TARGET_ID": args.target_id or "UNBOUND",
            "TARGET_ARTIFACT": target_artifact or "UNBOUND",
            "TARGET_SHA256": target_sha or "UNBOUND",
            "CONTRACT_SHA256": "UNFROZEN",
            "SOURCE_TREE_SHA256": draft_source_digest,
            "OBLIGATION_IDS": ", ".join(args.obligation_id) or "UNBOUND",
            "EXACT_INFORMAL_TARGET": statement,
            "SOURCE_FILE": "Main.lean",
            "DECLARATION_NAME": theorem_name,
            "PRETTY_PRINT_COMMAND": f"#print {theorem_name}",
            "AXIOM_PRINT_COMMAND": f"#print axioms {theorem_name}",
            "EXACT_PRETTY_PRINTED_TYPE": exact_type or "OPEN — capture after build",
        }
        atomic_write_bytes(
            stage / "formal_correspondence.md",
            _render_correspondence(root, correspondence_values).encode("utf-8"),
        )
        verdict_template = _load_json_template(
            root / "templates/lean_room/correspondence_verdict.yaml",
            "lean_correspondence_verdict",
            "correspondence verdict template",
        )
        verdict_template.update({"problem_id": args.problem_id, "case_id": args.case_id})
        atomic_write_json(stage / "correspondence_verdict.yaml", verdict_template)
        with state_lock(root):
            require_same_room_binding(root, status, "Lean case creation")
            if target_artifact and sha256_file(
                safe_relative_file(root, target_artifact, "target artifact")
            ) != target_sha:
                raise ValidationError("target artifact changed before case publication")
            if obligation_artifact and sha256_file(
                safe_relative_file(
                    root, obligation_artifact, "proof-obligation artifact"
                )
            ) != obligation_sha:
                raise ValidationError(
                    "proof-obligation artifact changed before case publication"
                )
            publish_directory_noreplace(stage, target)
        return target
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a guarded DRAFT Lean case.")
    parser.add_argument("--root", help="laboratory root (normally auto-discovered)")
    parser.add_argument("problem_id")
    parser.add_argument("case_id")
    parser.add_argument("--informal-statement", required=True)
    parser.add_argument("--theorem", required=True, help="exact qualified Lean name")
    parser.add_argument("--exact-formal-type")
    parser.add_argument("--toolchain", default="leanprover/lean4:v4.31.0")
    parser.add_argument("--actor", default="lean-room-coordinator")
    parser.add_argument(
        "--orchestration-profile", choices=("LIGHT", "FULL"), default="LIGHT"
    )
    parser.add_argument("--target-id")
    parser.add_argument("--target-artifact", help="root-relative exact target artifact")
    parser.add_argument("--statement-date", default=date.today().isoformat())
    parser.add_argument(
        "--obligation-artifact", help="root-relative proof-obligation artifact"
    )
    parser.add_argument("--obligation-id", action="append", default=[])
    parser.add_argument("--correspondence-obligation", action="append", default=[])
    parser.add_argument(
        "--permit-axiom",
        action="append",
        default=[],
        help=(
            "explicitly allow one standard v1 axiom; before LR0 add a substantive "
            "matching permitted_axiom_rationales entry to the contract"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        target = create_case(args)
        print(f"Created Lean Room DRAFT case: {target}")
        print("No build was run; freeze LR0 and LR1 before verification.")
        return EXIT_OK
    except LeanRoomError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
