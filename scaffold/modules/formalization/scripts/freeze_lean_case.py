#!/usr/bin/env python3
"""Append-only LR0/LR1 freeze gates for a Lean Room case."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from lean_room import (
    EXIT_OK,
    LEAN_ROOM_V1_ALLOWED_AXIOMS,
    LeanRoomError,
    ValidationError,
    atomic_write_bytes,
    atomic_write_json,
    canonical_json_bytes,
    case_path,
    discover_root,
    normalized_contract_sha256,
    project_tree_inventory,
    publish_directory_noreplace,
    require_room_enabled,
    require_same_room_binding,
    safe_append_container,
    safe_relative_file,
    sha256_bytes,
    sha256_file,
    state_lock,
    utc_now,
)
from validate_lean_case import validate_case


LR0_EXCLUDED_TOP_LEVEL_FIELDS = {"status", "environment", "freeze"}
LR0_READINESS_ATTESTATIONS = {
    "informal_target_complete",
    "formal_target_exact",
    "encoding_reviewed",
    "trust_boundary_reviewed",
    "lineage_and_exposure_recorded",
    "correspondence_plan_complete",
    "certificate_scope_and_nonclaims_complete",
    "stop_conditions_complete",
}


def lr0_payload(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Return every top-level field except the three post-LR0 mutable fields."""
    return {
        key: value
        for key, value in contract.items()
        if key not in LR0_EXCLUDED_TOP_LEVEL_FIELDS
    }


def lr0_payload_sha256(contract: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(lr0_payload(contract)))


def _timestamp_id(timestamp: str) -> str:
    return timestamp.replace("-", "").replace(":", "").replace(".", "")


def validate_lr0_readiness(contract: Mapping[str, Any]) -> list[str]:
    """Pure LR0 semantic/readiness validation, reusable by downstream gates."""
    errors: list[str] = []

    def complete_string_list(section: Any, field: str, label: str) -> bool:
        value = section.get(field) if isinstance(section, dict) else None
        if not isinstance(value, list) or not value or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            errors.append(f"LR0 semantic field {label}.{field} must be a nonempty string list")
            return False
        for item in value:
            stripped = item.strip()
            if stripped.casefold() in {"n/a", "none", "unknown", "open"}:
                errors.append(
                    f"LR0 semantic field {label}.{field} needs a reason, not a bare sentinel"
                )
                return False
        return True

    creation_binding = contract.get("room_state_binding_at_creation")
    if (
        not isinstance(creation_binding, dict)
        or not isinstance(creation_binding.get("sequence"), int)
        or isinstance(creation_binding.get("sequence"), bool)
        or creation_binding.get("sequence", -1) < 0
        or not isinstance(creation_binding.get("artifact_sha256"), str)
        or len(creation_binding.get("artifact_sha256", "")) != 64
        or any(
            character not in "0123456789abcdef"
            for character in creation_binding.get("artifact_sha256", "")
        )
    ):
        errors.append("LR0 requires the exact room state binding captured at case creation")

    target = contract.get("target_binding")
    if not isinstance(target, dict) or not all(
        isinstance(target.get(key), str) and bool(target[key].strip())
        for key in ("target_id", "artifact", "artifact_sha256")
    ):
        errors.append("LR0 requires complete target_binding")
    obligation = contract.get("obligation_binding")
    if not isinstance(obligation, dict) or not all(
        isinstance(obligation.get(key), str) and bool(obligation[key].strip())
        for key in ("artifact", "artifact_sha256")
    ):
        errors.append("LR0 requires complete obligation_binding")
    if not isinstance(obligation, dict) or not isinstance(
        obligation.get("obligation_ids"), list
    ) or not obligation["obligation_ids"]:
        errors.append("LR0 requires nonempty obligation_ids")
    formal = contract.get("formal_target")
    if not isinstance(formal, dict) or not all(
        isinstance(formal.get(key), str) and bool(formal[key].strip())
        for key in ("source_file", "declaration_name", "declaration_kind", "exact_type")
    ):
        errors.append("LR0 requires an exact formal target and exact_type")
    obligations = contract.get("correspondence_obligations")
    if not isinstance(obligations, list) or not obligations:
        errors.append("LR0 requires nonempty correspondence_obligations")
    acceptance = contract.get("acceptance_criterion")
    if not isinstance(acceptance, dict) or not isinstance(
        acceptance.get("required_gates"), list
    ) or not acceptance["required_gates"]:
        errors.append("LR0 requires acceptance_criterion.required_gates")
    informal = contract.get("informal_claim")
    if not isinstance(informal, dict) or not isinstance(
        informal.get("conclusion"), str
    ) or not informal["conclusion"].strip():
        errors.append("LR0 readiness requires informal_claim.conclusion")
    for field in (
        "quantifiers",
        "hypotheses",
        "ambient_objects_and_types",
        "parameters_and_domains",
        "conventions",
        "edge_cases",
        "anti_targets",
    ):
        complete_string_list(informal, field, "informal_claim")
    encoding = contract.get("encoding")
    for field in (
        "objects",
        "relations_and_predicates",
        "maps",
        "parameters",
        "normalizations",
        "bridge_lemmas",
        "known_loss_or_strengthening",
    ):
        complete_string_list(encoding, field, "encoding")
    trusted = contract.get("trusted_boundary")
    permitted_axioms = (
        trusted.get("permitted_axioms") if isinstance(trusted, dict) else None
    )
    if not isinstance(permitted_axioms, list) or not all(
        isinstance(item, str) and item.strip() for item in permitted_axioms
    ):
        errors.append("LR0 trusted_boundary.permitted_axioms must be a string list")
        permitted_set: set[str] = set()
    else:
        normalized_axioms = [item.strip() for item in permitted_axioms]
        permitted_set = set(normalized_axioms)
        if len(normalized_axioms) != len(permitted_set):
            errors.append("LR0 permitted_axioms must not contain duplicates")
        unsupported_axioms = sorted(permitted_set - LEAN_ROOM_V1_ALLOWED_AXIOMS)
        if unsupported_axioms:
            errors.append(
                "LR0 Lean Room v1 forbids axioms outside its hard allowlist: "
                + ", ".join(unsupported_axioms)
            )
    axiom_rationales = (
        trusted.get("permitted_axiom_rationales")
        if isinstance(trusted, dict)
        else None
    )
    if not isinstance(axiom_rationales, dict):
        errors.append("LR0 requires trusted_boundary.permitted_axiom_rationales")
    elif set(axiom_rationales) != permitted_set:
        errors.append(
            "LR0 permitted_axiom_rationales keys must exactly match permitted_axioms"
        )
    else:
        for axiom, rationale in axiom_rationales.items():
            if (
                not isinstance(rationale, str)
                or len(rationale.strip()) < 20
                or rationale.strip().casefold()
                in {"n/a", "none", "unknown", "open", "todo", "tbd"}
            ):
                errors.append(
                    f"LR0 permitted axiom {axiom} requires a substantive rationale"
                )
    for field in (
        "prohibited_constructs",
        "authorized_exceptions",
        "trusted_dependencies",
        "residual_risks",
    ):
        complete_string_list(trusted, field, "trusted_boundary")
    lineage = contract.get("lineage")
    lineage_fields = (
        "generator_run_ids",
        "material_repair_run_ids",
        "coordinator_run_ids",
    )
    lineage_sets: list[set[str]] = []
    for field in lineage_fields:
        value = lineage.get(field) if isinstance(lineage, dict) else None
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            errors.append(f"LR0 lineage.{field} must be a string list")
            lineage_sets.append(set())
        else:
            lineage_sets.append({item.strip() for item in value})
    source_lineage = set().union(*lineage_sets)
    if not source_lineage:
        errors.append("LR0 requires at least one generator, material-repair, or coordinator run ID")
    prohibited_auditors = (
        lineage.get("prohibited_decisive_auditor_run_ids")
        if isinstance(lineage, dict)
        else None
    )
    if not isinstance(prohibited_auditors, list) or not prohibited_auditors or not all(
        isinstance(item, str) and item.strip() for item in prohibited_auditors
    ):
        errors.append("LR0 requires nonempty prohibited_decisive_auditor_run_ids")
    elif not source_lineage.issubset({item.strip() for item in prohibited_auditors}):
        errors.append(
            "LR0 prohibited decisive auditor run IDs must include all source-lineage run IDs"
        )
    agent_lineage_fields = (
        "generator_agent_ids",
        "material_repair_agent_ids",
        "coordinator_agent_ids",
    )
    agent_lineage_sets: list[set[str]] = []
    for field in agent_lineage_fields:
        value = lineage.get(field) if isinstance(lineage, dict) else None
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            errors.append(f"LR0 lineage.{field} must be a string list")
            agent_lineage_sets.append(set())
        else:
            agent_lineage_sets.append({item.strip() for item in value})
    source_agents = set().union(*agent_lineage_sets)
    if not source_agents:
        errors.append("LR0 requires at least one generator, material-repair, or coordinator agent ID")
    prohibited_agents = (
        lineage.get("prohibited_decisive_auditor_agent_ids")
        if isinstance(lineage, dict)
        else None
    )
    if not isinstance(prohibited_agents, list) or not prohibited_agents or not all(
        isinstance(item, str) and item.strip() for item in prohibited_agents
    ):
        errors.append("LR0 requires nonempty prohibited_decisive_auditor_agent_ids")
    elif not source_agents.issubset({item.strip() for item in prohibited_agents}):
        errors.append(
            "LR0 prohibited decisive auditor agent IDs must include all source-lineage agent IDs"
        )
    exposure_summary = (
        lineage.get("information_exposure_summary")
        if isinstance(lineage, dict)
        else None
    )
    if not isinstance(exposure_summary, str) or not exposure_summary.strip():
        errors.append("LR0 requires a nonempty information_exposure_summary")
    if not isinstance(acceptance, dict) or not isinstance(
        acceptance.get("certificate_scope"), str
    ) or not acceptance["certificate_scope"].strip():
        errors.append("LR0 readiness requires acceptance_criterion.certificate_scope")
    if not isinstance(acceptance, dict) or not isinstance(
        acceptance.get("explicit_nonclaims"), list
    ) or not acceptance["explicit_nonclaims"]:
        errors.append("LR0 readiness requires explicit_nonclaims")
    attestations = (
        acceptance.get("lr0_readiness_attestations")
        if isinstance(acceptance, dict)
        else None
    )
    if not isinstance(attestations, dict) or any(
        attestations.get(key) is not True for key in LR0_READINESS_ATTESTATIONS
    ):
        errors.append("LR0 readiness attestations are incomplete")
    stop_conditions = contract.get("stop_conditions")
    if not isinstance(stop_conditions, list) or not stop_conditions or not all(
        isinstance(item, str) and item.strip() for item in stop_conditions
    ):
        errors.append("LR0 readiness requires nonempty stop_conditions")
    return errors


def _snapshot_stage(
    case: Path,
    gate: str,
    snapshot_id: str,
    contract_before_hash: str,
    prospective_contract: Mapping[str, Any],
    gate_bindings: Mapping[str, Any],
    inventory: list[dict[str, Any]] | None = None,
    project_source: Path | None = None,
    preserved_artifacts: Sequence[Mapping[str, Any]] = (),
) -> tuple[Path, Path]:
    freezes = safe_append_container(case, "evidence/freezes")
    target = freezes / snapshot_id
    stage = Path(tempfile.mkdtemp(prefix=f".{snapshot_id}.stage-", dir=str(freezes)))
    manifest = {
        "schema_version": 1,
        "record_type": "lean_freeze_snapshot",
        "gate": gate,
        "snapshot_id": snapshot_id,
        "case_id": prospective_contract.get("case_id"),
        "problem_id": prospective_contract.get("problem_id"),
        "recorded_at": gate_bindings.get("frozen_at"),
        "recorded_by": gate_bindings.get("frozen_by"),
        "contract_before_sha256": contract_before_hash,
        "contract_snapshot_artifact": "contract.snapshot.yaml",
        "contract_snapshot_sha256": sha256_bytes(pretty_contract_bytes(prospective_contract)),
        "gate_bindings": dict(gate_bindings),
        "preserved_artifacts": [],
        "navigation_only": False,
        "automatic_math_status_change": False,
    }
    for artifact in preserved_artifacts:
        source = artifact.get("source")
        snapshot_artifact = artifact.get("snapshot_artifact")
        expected_sha256 = artifact.get("sha256")
        if not isinstance(source, Path) or not isinstance(snapshot_artifact, str):
            raise ValidationError("invalid preserved LR0 artifact specification")
        if not isinstance(expected_sha256, str):
            raise ValidationError("invalid preserved LR0 artifact digest")
        content = source.read_bytes()
        if sha256_bytes(content) != expected_sha256:
            raise ValidationError(
                f"{artifact.get('kind', 'LR0 artifact')} changed while staging freeze"
            )
        destination = stage / snapshot_artifact
        atomic_write_bytes(destination, content)
        if sha256_file(destination) != expected_sha256:
            raise ValidationError("preserved LR0 artifact copy failed digest verification")
        manifest["preserved_artifacts"].append(
            {
                "kind": artifact.get("kind"),
                "source_artifact": artifact.get("source_artifact"),
                "snapshot_artifact": snapshot_artifact,
                "sha256": expected_sha256,
                "size": len(content),
            }
        )
    atomic_write_bytes(
        stage / "contract.snapshot.yaml", pretty_contract_bytes(prospective_contract)
    )
    if inventory is not None:
        atomic_write_json(stage / "source_tree_inventory.json", inventory)
        source_digest = gate_bindings.get("source_tree_sha256")
        atomic_write_bytes(
            stage / "source_tree.sha256", (str(source_digest) + "\n").encode("ascii")
        )
        manifest.update(
            {
                "source_tree_inventory_artifact": "source_tree_inventory.json",
                "source_tree_inventory_sha256": sha256_file(
                    stage / "source_tree_inventory.json"
                ),
                "source_tree_digest_artifact": "source_tree.sha256",
                "source_tree_digest_artifact_sha256": sha256_file(
                    stage / "source_tree.sha256"
                ),
            }
        )
        if project_source is None:
            raise ValidationError("LR1 source inventory requires a project snapshot source")
        project_snapshot = stage / "project.snapshot"
        project_snapshot.mkdir()
        for entry in inventory:
            relative = Path(str(entry.get("path", "")))
            source = project_source / relative
            expected_sha256 = entry.get("sha256")
            expected_size = entry.get("size")
            content = source.read_bytes()
            if (
                sha256_bytes(content) != expected_sha256
                or len(content) != expected_size
            ):
                raise ValidationError(
                    f"project/{relative.as_posix()} changed while staging LR1 snapshot"
                )
            destination = project_snapshot / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(destination, content)
        snapshot_inventory, snapshot_digest = project_tree_inventory(project_snapshot)
        if snapshot_inventory != inventory or snapshot_digest != gate_bindings.get(
            "source_tree_sha256"
        ):
            raise ValidationError("LR1 full project snapshot digest mismatch")
        manifest.update(
            {
                "project_snapshot_artifact": "project.snapshot",
                "project_snapshot_file_count": len(snapshot_inventory),
                "project_snapshot_tree_sha256": snapshot_digest,
            }
        )
    atomic_write_json(stage / "freeze_manifest.yaml", manifest)
    return stage, target


def pretty_contract_bytes(contract: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(contract, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _capture_contract_binding(
    case: Path, validated_contract: Mapping[str, Any]
) -> tuple[Path, str]:
    path = case / "formalization_contract.yaml"
    raw = path.read_bytes()
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"contract changed during freeze preflight: {exc}") from exc
    if parsed != validated_contract:
        raise ValidationError("contract changed between validation and freeze preflight")
    return path, sha256_bytes(raw)


def _validate_staged_lr1(
    stage: Path,
    prospective: Mapping[str, Any],
    inventory: list[dict[str, Any]],
    source_digest: str,
) -> None:
    freeze = prospective.get("freeze")
    environment = prospective.get("environment")
    if (
        prospective.get("status") != "FROZEN"
        or not isinstance(freeze, dict)
        or freeze.get("lr0_contract_frozen") is not True
        or freeze.get("lr1_sources_frozen") is not True
        or freeze.get("frozen_source_tree_sha256") != source_digest
        or freeze.get("frozen_contract_sha256")
        != normalized_contract_sha256(prospective)
    ):
        raise ValidationError("prospective LR1 contract bindings are inconsistent")
    if not isinstance(environment, dict) or (
        environment.get("source_tree_sha256") != source_digest
    ):
        raise ValidationError("prospective LR1 environment binding is inconsistent")
    snapshot_path = stage / "contract.snapshot.yaml"
    if snapshot_path.read_bytes() != pretty_contract_bytes(prospective):
        raise ValidationError("staged LR1 contract snapshot bytes are inconsistent")
    staged_inventory = json.loads(
        (stage / "source_tree_inventory.json").read_text(encoding="utf-8")
    )
    if staged_inventory != inventory:
        raise ValidationError("staged LR1 source inventory is inconsistent")
    if (stage / "source_tree.sha256").read_text(encoding="ascii").strip() != source_digest:
        raise ValidationError("staged LR1 source digest is inconsistent")
    staged_manifest = json.loads(
        (stage / "freeze_manifest.yaml").read_text(encoding="utf-8")
    )
    snapshot_inventory, snapshot_digest = project_tree_inventory(
        stage / "project.snapshot"
    )
    if (
        staged_manifest.get("contract_snapshot_sha256") != sha256_file(snapshot_path)
        or staged_manifest.get("source_tree_inventory_sha256")
        != sha256_file(stage / "source_tree_inventory.json")
        or staged_manifest.get("source_tree_digest_artifact_sha256")
        != sha256_file(stage / "source_tree.sha256")
        or staged_manifest.get("project_snapshot_artifact") != "project.snapshot"
        or staged_manifest.get("project_snapshot_file_count") != len(inventory)
        or staged_manifest.get("project_snapshot_tree_sha256") != source_digest
        or snapshot_inventory != inventory
        or snapshot_digest != source_digest
    ):
        raise ValidationError("staged LR1 freeze manifest bindings are inconsistent")


def freeze_lr0(root: Path, problem_id: str, case_id: str, actor: str) -> tuple[str, bool]:
    initial_status = require_room_enabled(root, "LR0 freeze")
    case = case_path(root, problem_id, case_id)
    report = validate_case(
        root,
        problem_id,
        case_id,
        verification_ready=False,
        allow_missing_declaration=True,
    )
    if not report.ok or report.contract is None:
        raise ValidationError("LR0 static validation failed: " + "; ".join(report.issues))
    contract = report.contract
    before_path, before_hash = _capture_contract_binding(case, contract)
    freeze = contract.get("freeze")
    if not isinstance(freeze, dict):
        raise ValidationError("LR0 requires contract.freeze object")
    payload_hash = lr0_payload_sha256(contract)
    if freeze.get("lr0_contract_frozen") is True:
        if freeze.get("lr0_payload_sha256") != payload_hash:
            raise ValidationError("LR0 frozen payload mutation detected")
        return str(freeze.get("lr0_snapshot_id") or "existing-LR0"), False
    required_errors = validate_lr0_readiness(contract)
    if required_errors:
        raise ValidationError("; ".join(required_errors))
    preserved_artifacts: list[dict[str, Any]] = []
    for kind, binding_key, snapshot_name in (
        ("informal_target", "target_binding", "target.artifact.snapshot"),
        ("proof_obligations", "obligation_binding", "obligations.artifact.snapshot"),
    ):
        artifact_binding = contract[binding_key]
        source_artifact = artifact_binding["artifact"]
        expected_sha256 = artifact_binding["artifact_sha256"]
        source = safe_relative_file(root, source_artifact, f"{kind} artifact")
        if sha256_file(source) != expected_sha256:
            raise ValidationError(f"{kind} artifact SHA-256 changed before LR0 freeze")
        preserved_artifacts.append(
            {
                "kind": kind,
                "source": source,
                "source_artifact": source_artifact,
                "snapshot_artifact": snapshot_name,
                "sha256": expected_sha256,
            }
        )
    timestamp = utc_now()
    snapshot_id = f"LR0-{_timestamp_id(timestamp)}-{payload_hash[:12]}"
    prospective = json.loads(json.dumps(contract, ensure_ascii=False))
    prospective_freeze = prospective["freeze"]
    prospective_freeze.update(
        {
            "lr0_contract_frozen": True,
            "lr0_frozen_at": timestamp,
            "lr0_frozen_by": actor,
            "lr0_payload_sha256": payload_hash,
            "lr0_snapshot_id": snapshot_id,
        }
    )
    stage, target = _snapshot_stage(
        case,
        "LR0",
        snapshot_id,
        before_hash,
        prospective,
        {
            "frozen_at": timestamp,
            "frozen_by": actor,
            "lr0_payload_sha256": payload_hash,
        },
        preserved_artifacts=preserved_artifacts,
    )
    try:
        with state_lock(root):
            require_same_room_binding(root, initial_status, "LR0 freeze")
            if sha256_file(before_path) != before_hash:
                raise ValidationError("contract changed concurrently before LR0 publication")
            for artifact in preserved_artifacts:
                if sha256_file(artifact["source"]) != artifact["sha256"]:
                    raise ValidationError(
                        f"{artifact['kind']} artifact changed before LR0 publication"
                    )
            publish_directory_noreplace(stage, target)
            atomic_write_bytes(before_path, pretty_contract_bytes(prospective))
        return snapshot_id, True
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def freeze_lr1(root: Path, problem_id: str, case_id: str, actor: str) -> tuple[str, bool]:
    initial_status = require_room_enabled(root, "LR1 freeze")
    case = case_path(root, problem_id, case_id)
    report = validate_case(root, problem_id, case_id, verification_ready=False)
    if not report.ok or report.contract is None:
        raise ValidationError("LR1 static validation failed: " + "; ".join(report.issues))
    contract = report.contract
    before_path, before_hash = _capture_contract_binding(case, contract)
    freeze = contract.get("freeze")
    if not isinstance(freeze, dict) or freeze.get("lr0_contract_frozen") is not True:
        raise ValidationError("LR1 requires a valid LR0 freeze first")
    payload_hash = lr0_payload_sha256(contract)
    if freeze.get("lr0_payload_sha256") != payload_hash:
        raise ValidationError("LR0 frozen payload mutation detected before LR1")
    if freeze.get("lr1_sources_frozen") is True:
        ready = validate_case(root, problem_id, case_id, verification_ready=True)
        if not ready.ok:
            raise ValidationError("existing LR1 freeze is invalid: " + "; ".join(ready.issues))
        return str(freeze.get("lr1_snapshot_id") or "existing-LR1"), False
    project = case / "project"
    inventory, source_digest = project_tree_inventory(project)
    timestamp = utc_now()
    snapshot_id = f"LR1-{_timestamp_id(timestamp)}-{source_digest[:12]}"
    prospective = json.loads(json.dumps(contract, ensure_ascii=False))
    environment = prospective.get("environment")
    if not isinstance(environment, dict):
        raise ValidationError("LR1 requires contract.environment object")
    toolchain = project / "lean-toolchain"
    lakefile = project / "lakefile.toml"
    manifest = project / "lake-manifest.json"
    for path in (toolchain, lakefile, manifest):
        if path.is_symlink() or not path.is_file():
            raise ValidationError(f"LR1 missing pinned project file: {path.name}")
    pinned_file_hashes = {
        path.name: sha256_file(path) for path in (toolchain, lakefile, manifest)
    }
    inventory_relative = f"evidence/freezes/{snapshot_id}/source_tree_inventory.json"
    environment.update(
        {
            "lean_toolchain_sha256": pinned_file_hashes["lean-toolchain"],
            "lakefile_sha256": pinned_file_hashes["lakefile.toml"],
            "lake_manifest_artifact": "project/lake-manifest.json",
            "lake_manifest_sha256": pinned_file_hashes["lake-manifest.json"],
            "source_tree_inventory": inventory_relative,
            "source_tree_sha256": source_digest,
        }
    )
    prospective["status"] = "FROZEN"
    prospective_freeze = prospective["freeze"]
    prospective_freeze.update(
        {
            "lr1_sources_frozen": True,
            "lr1_frozen_at": timestamp,
            "lr1_frozen_by": actor,
            "frozen_source_tree_sha256": source_digest,
            "lr1_snapshot_id": snapshot_id,
            "frozen_contract_sha256": None,
        }
    )
    prospective_freeze["frozen_contract_sha256"] = normalized_contract_sha256(prospective)
    stage, target = _snapshot_stage(
        case,
        "LR1",
        snapshot_id,
        before_hash,
        prospective,
        {
            "frozen_at": timestamp,
            "frozen_by": actor,
            "lr0_payload_sha256": payload_hash,
            "source_tree_sha256": source_digest,
            "frozen_contract_sha256": prospective_freeze["frozen_contract_sha256"],
        },
        inventory,
        project_source=project,
    )
    _validate_staged_lr1(stage, prospective, inventory, source_digest)
    try:
        with state_lock(root):
            require_same_room_binding(root, initial_status, "LR1 freeze")
            if sha256_file(before_path) != before_hash:
                raise ValidationError("contract changed concurrently before LR1 publication")
            final_inventory, final_source_digest = project_tree_inventory(project)
            if final_source_digest != source_digest or final_inventory != inventory:
                raise ValidationError("project source tree changed before LR1 publication")
            for path in (toolchain, lakefile, manifest):
                if sha256_file(path) != pinned_file_hashes[path.name]:
                    raise ValidationError(
                        f"{path.name} changed before LR1 publication"
                    )
            publish_directory_noreplace(stage, target)
            atomic_write_bytes(before_path, pretty_contract_bytes(prospective))
        ready = validate_case(root, problem_id, case_id, verification_ready=True)
        if not ready.ok:
            raise ValidationError(
                "LR1 was published but verification-ready validation failed: "
                + "; ".join(ready.issues)
            )
        return snapshot_id, True
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Freeze a Lean case at LR0 or LR1.")
    parser.add_argument("--root", help="laboratory root (normally auto-discovered)")
    parser.add_argument("problem_id")
    parser.add_argument("case_id")
    parser.add_argument("--gate", required=True, choices=("LR0", "LR1"))
    parser.add_argument("--actor", required=True)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = discover_root(args.root)
        require_room_enabled(root, f"{args.gate} freeze")
        actor = args.actor.strip()
        if not actor:
            raise ValidationError("freeze actor must be nonempty")
        if args.gate == "LR0":
            snapshot_id, changed = freeze_lr0(root, args.problem_id, args.case_id, actor)
        else:
            snapshot_id, changed = freeze_lr1(root, args.problem_id, args.case_id, actor)
        payload = {"gate": args.gate, "snapshot_id": snapshot_id, "changed": changed}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            print(f"{args.gate} freeze {'published' if changed else 'already valid'}: {snapshot_id}")
        return EXIT_OK
    except LeanRoomError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
