#!/usr/bin/env python3
"""Record an independent LR4/LR5 audit without editing frozen Lean sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from lean_room import (
    EXIT_OK,
    LEAN_ROOM_AUDIT_COMMAND_SCHEMA,
    LEAN_ROOM_BUILD_COMMAND_SCHEMA,
    LEAN_ROOM_V1_ALLOWED_AXIOMS,
    LEAN_ROOM_SANDBOX_PROFILE_ID,
    LeanRoomError,
    ValidationError,
    atomic_write_bytes,
    atomic_write_json,
    case_path,
    declaration_audit_bytes,
    discover_root,
    load_json_object,
    project_tree_inventory,
    publish_directory_noreplace,
    reject_symlink_components,
    require_room_enabled,
    safe_append_container,
    safe_relative_file,
    sha256_file,
    state_lock,
    utc_now,
    validate_identifier,
)
from validate_lean_case import validate_case


MANDATORY_ATTACK_CLASSES = {
    "statement_weakening",
    "hidden_stronger_hypotheses",
    "vacuity",
    "inconsistent_assumptions",
    "swapped_quantifiers",
    "wrong_domains",
    "unused_hypotheses",
    "implicit_instances",
    "empty_types",
    "wrong_namespace_or_declaration",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
AXIOM_BLOCK_RE = re.compile(r"depends on axioms:\s*\[([^\]]*)\]", re.DOTALL)


def _is_pass(value: Any) -> bool:
    return value is True or (
        isinstance(value, str) and value.upper() in {"PASS", "PASSED", "SUCCESS"}
    )


def _nonempty(value: str, label: str) -> str:
    result = value.strip()
    if not result:
        raise ValidationError(f"{label} must be nonempty")
    return result


def _regular_run_file(run_dir: Path, name: str) -> Path:
    path = run_dir / name
    reject_symlink_components(path, run_dir)
    if path.is_symlink() or not path.is_file():
        raise ValidationError(f"build evidence lacks regular {name}")
    return path


def _parse_axioms(raw: bytes) -> set[str]:
    text = raw.decode("utf-8", errors="replace")
    result: set[str] = set()
    for match in AXIOM_BLOCK_RE.finditer(text):
        result.update(value.strip() for value in match.group(1).split(",") if value.strip())
    if "does not depend on any axioms" in text:
        return result
    if not AXIOM_BLOCK_RE.search(text):
        raise ValidationError("unparseable #print axioms evidence")
    return result


def _canonical_binary_paths(toolchain: str) -> dict[str, str]:
    """Reconstruct the verifier's OS-account-bound toolchain paths.

    A build manifest may report hashes, but it may not choose an arbitrary
    executable and call it the pinned Lean toolchain.  The decisive audit
    therefore derives the same canonical Elan locations as the guarded
    verifier and requires exact byte/path agreement.
    """
    account_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    if not account_home.is_absolute() or account_home.is_symlink():
        raise ValidationError("OS account home is unsafe for pinned toolchain lookup")
    elan_home = account_home / ".elan"
    component = toolchain.replace("/", "--").replace(":", "---")
    toolchain_root = elan_home / "toolchains" / component
    expected = {
        "lean": toolchain_root / "bin/lean",
        "lake": toolchain_root / "bin/lake",
        "elan": elan_home / "bin/elan",
    }
    for name, path in expected.items():
        reject_symlink_components(path, account_home)
        if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
            raise ValidationError(f"canonical pinned {name} executable is unavailable")
    return {name: str(path) for name, path in expected.items()}


def validate_pass_build_evidence(
    case: Path,
    run_id: str,
    contract: Mapping[str, Any],
    expected_kind: str,
) -> tuple[Path, dict[str, Any], set[str]]:
    """Revalidate a complete guarded LR2/LR3 run; never trust PASS fields alone."""
    run_id = validate_identifier(run_id, "Lean build run id")
    run_dir = case / "evidence/runs" / run_id
    reject_symlink_components(run_dir, case)
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise ValidationError(f"missing regular Lean build run: {run_id}")
    path = _regular_run_file(run_dir, "build_manifest.yaml")
    manifest = load_json_object(path, f"Lean build manifest {run_id}")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("record_type") != "lean_build_run"
        or manifest.get("run_id") != run_id
        or manifest.get("problem_id") != contract.get("problem_id")
        or manifest.get("case_id") != contract.get("case_id")
    ):
        raise ValidationError(f"invalid Lean build manifest identity: {run_id}")
    if manifest.get("run_kind") != expected_kind:
        raise ValidationError(f"{run_id} must have run_kind={expected_kind}")
    if not isinstance(manifest.get("runner_id"), str) or not manifest["runner_id"].strip():
        raise ValidationError(f"{run_id} lacks runner_id")
    if (
        not _is_pass(manifest.get("result"))
        or not _is_pass(manifest.get("status"))
        or manifest.get("failure_class") is not None
        or manifest.get("failure_summary") is not None
    ):
        raise ValidationError(f"Lean build run is not PASS: {run_id}")
    gates = manifest.get("gates")
    if not isinstance(gates, dict) or not all(_is_pass(gates.get(gate)) for gate in ("LR2", "LR3")):
        raise ValidationError(f"Lean build run lacks PASS LR2/LR3 gates: {run_id}")
    contract_path = case / "formalization_contract.yaml"
    bound_contract = manifest.get("contract")
    if (
        not isinstance(bound_contract, dict)
        or bound_contract.get("sha256") != sha256_file(contract_path)
    ):
        raise ValidationError(f"{run_id} contract binding mismatch")
    target_contract = contract.get("target_binding")
    obligation_contract = contract.get("obligation_binding")
    target_run = manifest.get("target_binding")
    if (
        not isinstance(target_contract, dict)
        or not isinstance(obligation_contract, dict)
        or not isinstance(target_run, dict)
        or target_run.get("target_id") != target_contract.get("target_id")
        or target_run.get("target_sha256") != target_contract.get("artifact_sha256")
        or target_run.get("target_artifact") != target_contract.get("artifact")
        or target_run.get("obligation_ids") != obligation_contract.get("obligation_ids")
        or target_run.get("obligation_artifact") != obligation_contract.get("artifact")
        or target_run.get("obligation_sha256")
        != obligation_contract.get("artifact_sha256")
    ):
        raise ValidationError(f"{run_id} target/obligation binding mismatch")
    room = manifest.get("room_state_check")
    if (
        not isinstance(room, dict)
        or room.get("state") != "enabled"
        or not isinstance(room.get("state_sequence"), int)
        or not isinstance(room.get("state_artifact_sha256"), str)
        or not SHA256_RE.fullmatch(room["state_artifact_sha256"])
        or room.get("state_binding_still_current_at_finish") is not True
    ):
        raise ValidationError(f"{run_id} lacks a valid enabled-state binding")
    controls = room.get("control_bindings")
    if (
        not isinstance(controls, list)
        or not controls
        or not all(
            isinstance(item, dict)
            and isinstance(item.get("role"), str)
            and isinstance(item.get("state_sequence"), int)
            and isinstance(item.get("state_artifact"), str)
            and isinstance(item.get("state_artifact_sha256"), str)
            and SHA256_RE.fullmatch(item["state_artifact_sha256"])
            for item in controls
        )
        or controls[0].get("state_sequence") != room.get("state_sequence")
        or controls[0].get("state_artifact_sha256")
        != room.get("state_artifact_sha256")
    ):
        raise ValidationError(f"{run_id} room control bindings are malformed")
    clean = manifest.get("clean_build")
    if (
        not isinstance(clean, dict)
        or clean.get("network_disabled") is not True
        or clean.get("dependency_fetch_performed") is not False
        or clean.get("dirty_input_detected") is not False
        or clean.get("sandbox_backend") != LEAN_ROOM_SANDBOX_PROFILE_ID
        or clean.get("logical_command_schemas")
        != {
            "build": list(LEAN_ROOM_BUILD_COMMAND_SCHEMA),
            "declaration_audit": list(LEAN_ROOM_AUDIT_COMMAND_SCHEMA),
        }
    ):
        raise ValidationError(f"{run_id} lacks the mandatory clean sandbox binding")
    environment = manifest.get("environment")
    contract_environment = contract.get("environment")
    if not isinstance(environment, dict) or not isinstance(contract_environment, dict):
        raise ValidationError(f"{run_id} environment binding is missing")
    if environment.get("lean_toolchain") != contract_environment.get("lean_toolchain"):
        raise ValidationError(f"{run_id} toolchain mismatch")
    canonical_binary_paths = _canonical_binary_paths(
        str(contract_environment.get("lean_toolchain"))
    )
    for field in ("lean_version_output", "lake_version_output", "elan_version_output"):
        if not isinstance(environment.get(field), str) or not environment[field].strip():
            raise ValidationError(f"{run_id} lacks captured {field}")
    expected_version = str(contract_environment.get("lean_toolchain", "")).rsplit(
        ":v", 1
    )[-1].lstrip("v")
    if (
        expected_version not in environment["lean_version_output"]
        or expected_version not in environment["lake_version_output"]
    ):
        raise ValidationError(f"{run_id} captured tool versions do not match the pin")
    binaries = environment.get("binary_bindings")
    if not isinstance(binaries, dict):
        raise ValidationError(f"{run_id} lacks pinned binary bindings")
    binary_paths: dict[str, str] = {}
    for name in ("lean", "lake", "elan"):
        binding = binaries.get(name)
        if not isinstance(binding, dict):
            raise ValidationError(f"{run_id} lacks {name} binary binding")
        artifact = binding.get("artifact")
        expected_sha256 = binding.get("sha256")
        expected_size = binding.get("size")
        if (
            not isinstance(artifact, str)
            or not Path(artifact).is_absolute()
            or artifact != canonical_binary_paths[name]
            or not isinstance(expected_sha256, str)
            or not SHA256_RE.fullmatch(expected_sha256)
            or not isinstance(expected_size, int)
        ):
            raise ValidationError(f"{run_id} has malformed {name} binary binding")
        binary_path = Path(artifact)
        if sha256_file(binary_path) != expected_sha256 or binary_path.stat().st_size != expected_size:
            raise ValidationError(f"{run_id} pinned {name} binary changed")
        binary_paths[name] = artifact
    if contract_environment.get("dependency_free") is not True or contract_environment.get("dependencies") != []:
        raise ValidationError("v1 certificate evidence must be dependency-free")
    inputs = manifest.get("input_bindings")
    outputs = manifest.get("output_bindings")
    frozen_digest = contract.get("freeze", {}).get("frozen_source_tree_sha256")
    if not isinstance(inputs, dict) or not isinstance(outputs, dict):
        raise ValidationError(f"{run_id} source bindings are missing")
    expected_input_fields = {
        "source_tree_sha256_before": frozen_digest,
        "lean_toolchain_sha256": contract_environment.get("lean_toolchain_sha256"),
        "lakefile_sha256": contract_environment.get("lakefile_sha256"),
        "lake_manifest_sha256": contract_environment.get("lake_manifest_sha256"),
        "dependencies": [],
    }
    for field, expected in expected_input_fields.items():
        if inputs.get(field) != expected:
            raise ValidationError(f"{run_id} input binding mismatch: {field}")
    bound_files = inputs.get("bound_files")
    if not isinstance(bound_files, list) or not bound_files:
        raise ValidationError(f"{run_id} bound input files are missing")
    required_labels = {
        "contract",
        "informal_target",
        "proof_obligations",
        "freeze:LR0",
        "freeze:LR1",
    }
    labels: set[str] = set()
    artifacts: set[str] = set()
    lab_root = case.parents[5]
    for item in bound_files:
        if not isinstance(item, dict):
            raise ValidationError(f"{run_id} has a malformed bound input entry")
        label = item.get("label")
        artifact = item.get("artifact")
        expected_sha = item.get("sha256")
        expected_size = item.get("size")
        if (
            not isinstance(label, str)
            or not isinstance(artifact, str)
            or artifact in artifacts
            or not isinstance(expected_sha, str)
            or not SHA256_RE.fullmatch(expected_sha)
            or not isinstance(expected_size, int)
        ):
            raise ValidationError(f"{run_id} has a malformed/duplicate bound input")
        labels.add(label)
        artifacts.add(artifact)
        base = (
            lab_root
            if label in {"informal_target", "proof_obligations"}
            else case
        )
        current = safe_relative_file(base, artifact, f"{run_id} bound input")
        if sha256_file(current) != expected_sha or current.stat().st_size != expected_size:
            raise ValidationError(f"{run_id} bound input changed: {artifact}")
    if not required_labels.issubset(labels):
        raise ValidationError(f"{run_id} does not bind every required verifier input")
    if outputs.get("source_tree_sha256_after") != frozen_digest or outputs.get("source_tree_unchanged") is not True:
        raise ValidationError(f"{run_id} source output binding mismatch")
    digest_path = _regular_run_file(run_dir, "source_tree.sha256")
    if digest_path.read_text(encoding="ascii").strip() != frozen_digest:
        raise ValidationError(f"{run_id} source digest artifact mismatch")
    inventory_path = _regular_run_file(run_dir, "source_tree_inventory.json")
    if inputs.get("source_tree_inventory_sha256") != sha256_file(inventory_path):
        raise ValidationError(f"{run_id} source inventory artifact hash mismatch")
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{run_id} source inventory is invalid: {exc}") from exc
    if not isinstance(inventory, list):
        raise ValidationError(f"{run_id} source inventory is not a list")
    current_inventory, current_digest = project_tree_inventory(case / "project")
    if inventory != current_inventory or current_digest != frozen_digest:
        raise ValidationError(f"{run_id} inventory does not match the current frozen source")
    log = manifest.get("log")
    if not isinstance(log, dict) or log.get("complete_untruncated") is not True:
        raise ValidationError(f"{run_id} complete build log binding is missing")
    log_path = _regular_run_file(run_dir, "build.log")
    if log.get("artifact") != "build.log" or log.get("sha256") != sha256_file(log_path):
        raise ValidationError(f"{run_id} build log hash mismatch")
    command_results = manifest.get("command_results")
    if not isinstance(command_results, list) or not command_results:
        raise ValidationError(f"{run_id} command results are missing")
    logical_commands: list[list[str]] = []
    wrapped_commands: list[list[str]] = []
    command_outputs: list[bytes] = []
    for index, result in enumerate(command_results, start=1):
        if (
            not isinstance(result, dict)
            or result.get("exit_code") != 0
            or result.get("aborted_room_state") is not False
            or result.get("timed_out") is not False
            or not isinstance(result.get("logical_argv"), list)
            or not all(isinstance(item, str) for item in result["logical_argv"])
        ):
            raise ValidationError(f"{run_id} contains a non-PASS command result")
        expected_output_artifact = f"command_outputs/{index:03d}.log"
        if result.get("output_artifact") != expected_output_artifact:
            raise ValidationError(f"{run_id} command output artifact binding mismatch")
        output_path = _regular_run_file(run_dir, expected_output_artifact)
        output = output_path.read_bytes()
        if result.get("output_sha256") != hashlib.sha256(output).hexdigest():
            raise ValidationError(f"{run_id} command output digest mismatch")
        command_outputs.append(output)
        logical_commands.append(result["logical_argv"])
        wrapped = result.get("wrapped_argv")
        if (
            not isinstance(wrapped, list)
            or len(wrapped) < 4
            or wrapped[0] != "/usr/bin/sandbox-exec"
            or wrapped[1] != "-p"
            or not isinstance(wrapped[2], str)
            or "(deny default)" not in wrapped[2]
            or "(deny network*)" not in wrapped[2]
            or wrapped[3:] != result["logical_argv"]
        ):
            raise ValidationError(f"{run_id} command lacks the exact deny-default wrapper")
        wrapped_commands.append(wrapped)
    if manifest.get("commands") != wrapped_commands:
        raise ValidationError(f"{run_id} top-level command binding mismatch")
    reconstructed_log = b""
    for index, (wrapped, output) in enumerate(
        zip(wrapped_commands, command_outputs), start=1
    ):
        reconstructed_log += (
            f"===== command {index} =====\n"
            + json.dumps(wrapped, ensure_ascii=False)
            + "\n"
        ).encode("utf-8")
        reconstructed_log += output
        if not output.endswith(b"\n"):
            reconstructed_log += b"\n"
    if log_path.read_bytes() != reconstructed_log:
        raise ValidationError(f"{run_id} build log is not the exact command transcript")
    expected_prefix = [
        [binary_paths["elan"], "--version"],
        [binary_paths["lean"], "--version"],
        [binary_paths["lake"], "--version"],
        [binary_paths["lake"], *LEAN_ROOM_BUILD_COMMAND_SCHEMA[1:]],
    ]
    if len(logical_commands) != 5 or logical_commands[:4] != expected_prefix:
        raise ValidationError(
            f"{run_id} command sequence is not the canonical five-command v1 run"
        )
    declaration_command = logical_commands[4]
    if (
        len(declaration_command) != 4
        or declaration_command[:3]
        != [binary_paths["lake"], "env", binary_paths["lean"]]
        or Path(declaration_command[-1]).name != "declaration_audit.lean"
    ):
        raise ValidationError(f"{run_id} lacks the canonical declaration audit command")
    forbidden_argv = {"update", "fetch", "install", "try-cache"}
    if any(forbidden_argv.intersection(command) for command in logical_commands):
        raise ValidationError(f"{run_id} contains a forbidden acquisition command")
    formal = contract.get("formal_target")
    if not isinstance(formal, dict):
        raise ValidationError("contract formal target is missing")
    declarations = manifest.get("declaration_checks")
    if not isinstance(declarations, list) or len(declarations) != 1:
        raise ValidationError(f"{run_id} requires exactly one declaration check")
    declaration_check = declarations[0]
    if (
        not isinstance(declaration_check, dict)
        or declaration_check.get("declaration_name") != formal.get("declaration_name")
        or declaration_check.get("exact_type") != formal.get("exact_type")
        or declaration_check.get("kernel_check_passed") is not True
        or declaration_check.get("audit_artifact") != "declaration_audit.lean"
        or declaration_check.get("type_check_mode")
        != "kernel_definitional_equality_without_coercion"
        or declaration_check.get("axiom_check_subjects")
        != [
            formal.get("declaration_name"),
            "private generated exact-target wrapper",
        ]
    ):
        raise ValidationError(f"{run_id} exact declaration check mismatch")
    expected_audit_source = declaration_audit_bytes(
        formal.get("declaration_name"), formal.get("exact_type")
    )
    audit_source = _regular_run_file(run_dir, "declaration_audit.lean").read_bytes()
    if audit_source != expected_audit_source:
        raise ValidationError(f"{run_id} declaration audit source mismatch")
    scan = manifest.get("forbidden_construct_scan")
    if (
        not isinstance(scan, dict)
        or scan.get("passed") is not True
        or scan.get("findings") != []
    ):
        raise ValidationError(f"{run_id} forbidden-construct scan did not pass cleanly")
    axiom_path = _regular_run_file(run_dir, "axioms.txt")
    if len(command_outputs) != 5 or axiom_path.read_bytes() != command_outputs[4]:
        raise ValidationError(f"{run_id} axiom output is not the declaration command output")
    parsed_axioms = _parse_axioms(axiom_path.read_bytes())
    axiom_reports = manifest.get("axiom_reports")
    if not isinstance(axiom_reports, list) or len(axiom_reports) != 1:
        raise ValidationError(f"{run_id} axiom report binding is missing")
    axiom_report = axiom_reports[0]
    permitted = sorted(contract.get("trusted_boundary", {}).get("permitted_axioms", []))
    if not set(permitted).issubset(LEAN_ROOM_V1_ALLOWED_AXIOMS):
        raise ValidationError(
            f"{run_id} contract axiom allowlist exceeds Lean Room v1"
        )
    if not parsed_axioms.issubset(LEAN_ROOM_V1_ALLOWED_AXIOMS):
        raise ValidationError(
            f"{run_id} reported an axiom outside the Lean Room v1 hard allowlist"
        )
    if (
        not isinstance(axiom_report, dict)
        or axiom_report.get("declaration_name") != formal.get("declaration_name")
        or axiom_report.get("audit_subjects")
        != [
            formal.get("declaration_name"),
            "private generated exact-target wrapper",
        ]
        or axiom_report.get("artifact") != "axioms.txt"
        or axiom_report.get("artifact_sha256") != sha256_file(axiom_path)
        or sorted(axiom_report.get("reported_axioms", [])) != sorted(parsed_axioms)
        or sorted(axiom_report.get("permitted_axioms", [])) != permitted
        or sorted(parsed_axioms - set(permitted)) != []
    ):
        raise ValidationError(f"{run_id} axiom evidence mismatch")
    return path, manifest, parsed_axioms


def _load_template(root: Path) -> dict[str, Any]:
    path = root / "templates/lean_room/formal_audit_manifest.yaml"
    value = load_json_object(path, "formal audit template")
    if value.get("record_type") != "lean_formal_audit":
        raise ValidationError("invalid formal audit template")
    return value


def _reported_axioms(manifest: Mapping[str, Any]) -> list[str]:
    reports = manifest.get("axiom_reports")
    if not isinstance(reports, list):
        return []
    result: set[str] = set()
    for report in reports:
        if not isinstance(report, dict):
            continue
        values = report.get("reported_axioms")
        if isinstance(values, list):
            result.update(value for value in values if isinstance(value, str))
    return sorted(result)


def _require_complete_pass_report(text: str) -> None:
    if "{{" in text or re.search(
        r"\b(?:OPEN|UNCHECKED|DRAFT|TODO|TBD|UNKNOWN)\b", text, re.IGNORECASE
    ):
        raise ValidationError("PASS correspondence report still contains template/open markers")
    if not re.search(r"(?m)^Status:\s*`?PASS`?\s*$", text):
        raise ValidationError("PASS correspondence report requires top-level Status: PASS")
    if not re.search(r"(?m)^-\s*Verdict:\s*`?PASS`?\s*$", text):
        raise ValidationError("PASS correspondence report requires an exact Verdict: PASS line")
    required_sections = (
        "Frozen informal target",
        "Exact formal declaration",
        "Object and type map",
        "Quantifier and hypothesis audit",
        "Conclusion audit",
        "Direction back to the target",
        "Anti-target checks",
        "Adversarial objections",
        "Correspondence verdict",
    )
    missing = [
        heading
        for heading in required_sections
        if not re.search(rf"(?m)^##\s+{re.escape(heading)}\s*$", text)
    ]
    if missing:
        raise ValidationError(
            "PASS correspondence report lacks required sections: "
            + ", ".join(missing)
        )


def _validate_correspondence_verdict(
    verdict: dict[str, Any],
    *,
    problem_id: str,
    case_id: str,
    auditor_id: str,
    auditor_run_id: str,
    contract_sha: str,
    target_sha: str,
    source_digest: str,
    candidate_run_id: str,
    independent_run_id: str,
    certificate_scope: str,
) -> None:
    if verdict.get("schema_version") != 1 or verdict.get("record_type") != "lean_correspondence_verdict":
        raise ValidationError("invalid correspondence verdict schema")
    expected_identity = {
        "problem_id": problem_id,
        "case_id": case_id,
        "auditor_id": auditor_id,
        "auditor_run_id": auditor_run_id,
    }
    for key, expected in expected_identity.items():
        if verdict.get(key) != expected:
            raise ValidationError(f"correspondence verdict {key} mismatch")
    if not isinstance(verdict.get("attested_at"), str) or not verdict["attested_at"].strip():
        raise ValidationError("correspondence verdict lacks attested_at")
    bindings = verdict.get("bindings")
    expected_bindings = {
        "contract_sha256": contract_sha,
        "target_sha256": target_sha,
        "source_tree_sha256": source_digest,
        "candidate_run_id": candidate_run_id,
        "independent_run_id": independent_run_id,
    }
    if not isinstance(bindings, dict):
        raise ValidationError("correspondence verdict bindings are missing")
    for key, expected in expected_bindings.items():
        if bindings.get(key) != expected:
            raise ValidationError(f"correspondence verdict binding mismatch: {key}")
    checks = verdict.get("checks")
    required_checks = {
        "quantifier_order_checked",
        "types_and_domains_checked",
        "hypotheses_checked",
        "conclusion_checked",
        "conventions_and_normalizations_checked",
        "edge_cases_checked",
        "direction_back_to_frozen_target_established",
        "anti_targets_ruled_out",
    }
    if not isinstance(checks, dict) or any(checks.get(key) is not True for key in required_checks):
        raise ValidationError("every required semantic correspondence check must be true")
    required_attacks = verdict.get("required_attack_classes")
    if not isinstance(required_attacks, list) or set(required_attacks) != MANDATORY_ATTACK_CLASSES:
        raise ValidationError("correspondence verdict mandatory attack-class set was weakened")
    attacks = verdict.get("adversarial_checks")
    if not isinstance(attacks, list):
        raise ValidationError("correspondence verdict adversarial_checks must be a list")
    passed_classes: set[str] = set()
    for attack in attacks:
        if not isinstance(attack, dict):
            raise ValidationError("invalid adversarial correspondence check")
        attack_class = attack.get("attack_class")
        evidence = attack.get("evidence")
        if (
            not isinstance(attack_class, str)
            or attack.get("outcome") != "PASS"
            or not isinstance(evidence, str)
            or len(evidence.strip()) < 40
            or re.search(
                r"\b(?:OPEN|UNCHECKED|DRAFT|TODO|TBD|UNKNOWN)\b",
                evidence,
                re.IGNORECASE,
            )
        ):
            raise ValidationError("every adversarial check needs class, PASS outcome, and evidence")
        if attack_class in passed_classes:
            raise ValidationError("duplicate adversarial correspondence attack class")
        passed_classes.add(attack_class)
    if passed_classes != MANDATORY_ATTACK_CLASSES:
        missing = sorted(MANDATORY_ATTACK_CLASSES - passed_classes)
        extra = sorted(passed_classes - MANDATORY_ATTACK_CLASSES)
        raise ValidationError(
            "adversarial correspondence class mismatch; missing="
            + ",".join(missing)
            + "; extra="
            + ",".join(extra)
        )
    if verdict.get("open_correspondence_obligations") != []:
        raise ValidationError("PASS correspondence verdict has open obligations")
    if verdict.get("unresolved_objections") != []:
        raise ValidationError("PASS correspondence verdict has unresolved objections")
    if verdict.get("highest_gap_class") != "GS0":
        raise ValidationError("PASS correspondence verdict requires highest_gap_class GS0")
    if verdict.get("exact_certificate_scope") != certificate_scope:
        raise ValidationError("correspondence verdict certificate scope mismatch")
    nonclaims = verdict.get("explicit_nonclaims")
    if not isinstance(nonclaims, list) or not nonclaims or not all(
        isinstance(value, str) and value.strip() for value in nonclaims
    ):
        raise ValidationError("PASS correspondence verdict requires explicit nonclaims")
    if verdict.get("verdict") != "PASS":
        raise ValidationError("correspondence verdict is not PASS")


def record_audit(args: argparse.Namespace) -> Path:
    root = discover_root(args.root)
    initial = require_room_enabled(root, "Lean independent audit recording")
    problem_id = validate_identifier(args.problem_id, "problem id")
    case_id = validate_identifier(args.case_id, "case id")
    audit_id = validate_identifier(args.audit_id, "audit id") if args.audit_id else None
    auditor_id = _nonempty(args.auditor_id, "auditor id")
    auditor_run_id = validate_identifier(args.auditor_run_id, "auditor run id")
    case = case_path(root, problem_id, case_id)
    validation = validate_case(root, problem_id, case_id, verification_ready=True)
    if not validation.ok or validation.contract is None or validation.source_tree_sha256 is None:
        raise ValidationError("audit requires a valid frozen case: " + "; ".join(validation.issues))
    contract = validation.contract
    contract_path = case / "formalization_contract.yaml"
    contract_sha = sha256_file(contract_path)
    target_binding = contract.get("target_binding")
    obligation_binding = contract.get("obligation_binding")
    if not isinstance(target_binding, dict) or not isinstance(obligation_binding, dict):
        raise ValidationError("contract target/obligation bindings are missing")
    target_artifact = safe_relative_file(root, target_binding.get("artifact", ""), "target artifact")
    obligation_artifact = safe_relative_file(
        root, obligation_binding.get("artifact", ""), "proof-obligation artifact"
    )
    candidate_path, candidate, _ = validate_pass_build_evidence(
        case, args.candidate_run_id, contract, "candidate"
    )
    independent_path, independent, independent_axioms = validate_pass_build_evidence(
        case, args.independent_run_id, contract, "independent"
    )
    _, candidate_run_tree_sha = project_tree_inventory(candidate_path.parent)
    _, independent_run_tree_sha = project_tree_inventory(independent_path.parent)
    if candidate_path == independent_path:
        raise ValidationError("candidate and independent build must be distinct runs")
    candidate_runner = candidate.get("runner_id")
    independent_runner = independent.get("runner_id")
    if not isinstance(candidate_runner, str) or not isinstance(independent_runner, str):
        raise ValidationError("both build manifests require runner_id")
    if candidate_runner == independent_runner:
        raise ValidationError("independent build runner must differ from candidate runner")
    if auditor_id == candidate_runner:
        raise ValidationError("decisive auditor must differ from candidate runner")
    if independent_runner != auditor_id or args.independent_run_id != auditor_run_id:
        raise ValidationError(
            "auditor identity/run must equal the independent rebuild runner/run identity"
        )

    frozen_digest = contract.get("freeze", {}).get("frozen_source_tree_sha256")
    for label, manifest in (("candidate", candidate), ("independent", independent)):
        inputs = manifest.get("input_bindings")
        outputs = manifest.get("output_bindings")
        if not isinstance(inputs, dict) or not isinstance(outputs, dict):
            raise ValidationError(f"{label} build lacks source bindings")
        if inputs.get("source_tree_sha256_before") != frozen_digest:
            raise ValidationError(f"{label} build input is not the frozen source tree")
        if outputs.get("source_tree_sha256_after") != frozen_digest or outputs.get("source_tree_unchanged") is not True:
            raise ValidationError(f"{label} build did not preserve the frozen source tree")
        bound_contract = manifest.get("contract")
        if not isinstance(bound_contract, dict) or bound_contract.get("sha256") != contract_sha:
            raise ValidationError(f"{label} build is bound to a different contract")

    lineage = contract.get("lineage")
    lineage = lineage if isinstance(lineage, dict) else {}
    prohibited = {
        value
        for key in ("generator_run_ids", "material_repair_run_ids", "prohibited_decisive_auditor_run_ids")
        for value in lineage.get(key, [])
        if isinstance(value, str)
    }
    if auditor_run_id in prohibited or args.independent_run_id in prohibited:
        raise ValidationError("auditor or independent build overlaps prohibited generation/repair lineage")
    prohibited_agents = {
        value
        for key in (
            "generator_agent_ids",
            "material_repair_agent_ids",
            "prohibited_decisive_auditor_agent_ids",
        )
        for value in lineage.get(key, [])
        if isinstance(value, str)
    }
    if auditor_id in prohibited_agents or independent_runner in prohibited_agents:
        raise ValidationError(
            "auditor agent identity overlaps generation/material-repair lineage"
        )

    correspondence_path = case / "formal_correspondence.md"
    if correspondence_path.is_symlink() or not correspondence_path.is_file():
        raise ValidationError("missing regular formal_correspondence.md")
    correspondence_text = correspondence_path.read_text(encoding="utf-8")
    verdict_path = case / "correspondence_verdict.yaml"
    correspondence_verdict = load_json_object(
        verdict_path, "machine-checkable correspondence verdict"
    )
    verdict = args.verdict
    certificate_eligible = verdict == "PASS"
    if certificate_eligible:
        if not args.attest_exact_correspondence:
            raise ValidationError("PASS requires --attest-exact-correspondence")
        _require_complete_pass_report(correspondence_text)
        acceptance = contract.get("acceptance_criterion")
        scope = acceptance.get("certificate_scope") if isinstance(acceptance, dict) else None
        if not isinstance(scope, str) or not scope.strip():
            raise ValidationError("PASS audit requires acceptance_criterion.certificate_scope")
        if args.unresolved_objection:
            raise ValidationError("PASS audit cannot contain unresolved objections")
        if args.highest_gap_class not in (None, "GS0"):
            raise ValidationError("PASS audit requires highest_gap_class GS0")
        _validate_correspondence_verdict(
            correspondence_verdict,
            problem_id=problem_id,
            case_id=case_id,
            auditor_id=auditor_id,
            auditor_run_id=auditor_run_id,
            contract_sha=contract_sha,
            target_sha=target_binding.get("artifact_sha256"),
            source_digest=frozen_digest,
            candidate_run_id=args.candidate_run_id,
            independent_run_id=args.independent_run_id,
            certificate_scope=scope,
        )

    timestamp = utc_now()
    if audit_id is None:
        audit_id = "AUD-" + timestamp.replace("-", "").replace(":", "").replace(".", "")
    audit_id = validate_identifier(audit_id, "audit id")
    audits = safe_append_container(case, "audits")
    target = audits / audit_id
    if target.exists() or target.is_symlink():
        raise ValidationError(f"audit already exists: {audit_id}")
    stage = Path(tempfile.mkdtemp(prefix=f".{audit_id}.stage-", dir=str(audits)))
    try:
        correspondence_snapshot = stage / "formal_correspondence.snapshot.md"
        atomic_write_bytes(correspondence_snapshot, correspondence_text.encode("utf-8"))
        verdict_snapshot = stage / "correspondence_verdict.snapshot.yaml"
        atomic_write_bytes(verdict_snapshot, verdict_path.read_bytes())
        manifest = _load_template(root)
        manifest.update(
            {
                "case_id": case_id,
                "problem_id": problem_id,
                "audit_id": audit_id,
                "auditor_id": auditor_id,
                "auditor_run_id": auditor_run_id,
                "started_at": args.started_at or timestamp,
                "finished_at": timestamp,
                "verdict": verdict,
                "certificate_eligible": certificate_eligible,
                "highest_gap_class": (
                    correspondence_verdict.get("highest_gap_class")
                    if certificate_eligible
                    else args.highest_gap_class
                ),
                "unresolved_objections": (
                    correspondence_verdict.get("unresolved_objections", [])
                    if certificate_eligible
                    else list(args.unresolved_objection)
                ),
            }
        )
        manifest["independence"].update(
            {
                "generator_run_ids": lineage.get("generator_run_ids", []),
                "material_repair_run_ids": lineage.get("material_repair_run_ids", []),
                "generator_agent_ids": lineage.get("generator_agent_ids", []),
                "material_repair_agent_ids": lineage.get(
                    "material_repair_agent_ids", []
                ),
                "auditor_disjoint_from_generation_and_repair": True,
                "prior_exposure": list(args.prior_exposure),
                "withheld_material": list(args.withheld_material),
                "eligible_as_decisive_auditor": True,
            }
        )
        manifest["bindings"].update(
            {
                "contract": "../../formalization_contract.yaml",
                "contract_sha256": contract_sha,
                "target_id": contract["target_binding"].get("target_id"),
                "target_sha256": contract["target_binding"].get("artifact_sha256"),
                "obligation_ids": contract["obligation_binding"].get("obligation_ids", []),
                "source_tree_sha256": frozen_digest,
                "candidate_build_manifest": candidate_path.relative_to(case).as_posix(),
                "candidate_build_manifest_sha256": sha256_file(candidate_path),
                "candidate_build_run_tree_sha256": candidate_run_tree_sha,
                "independent_build_manifest": independent_path.relative_to(case).as_posix(),
                "independent_build_manifest_sha256": sha256_file(independent_path),
                "independent_build_run_tree_sha256": independent_run_tree_sha,
                "formal_correspondence": "formal_correspondence.snapshot.md",
                "formal_correspondence_sha256": sha256_file(correspondence_snapshot),
                "correspondence_report": "formal_correspondence.snapshot.md",
                "correspondence_report_sha256": sha256_file(correspondence_snapshot),
                "correspondence_verdict": "correspondence_verdict.snapshot.yaml",
                "correspondence_verdict_sha256": sha256_file(verdict_snapshot),
            }
        )
        formal = contract["formal_target"]
        type_output_path = independent_path.parent / "axioms.txt"
        audit_source_path = independent_path.parent / "declaration_audit.lean"
        manifest["formal_declaration"].update(
            {
                "source_file": formal.get("source_file"),
                "declaration_name": formal.get("declaration_name"),
                "contract_exact_type": formal.get("exact_type"),
                "type_equality_mode": "kernel_definitional_equality_without_coercion",
                "type_output_artifact": type_output_path.relative_to(case).as_posix(),
                "type_output_sha256": sha256_file(type_output_path),
                "audit_source_artifact": audit_source_path.relative_to(case).as_posix(),
                "audit_source_sha256": sha256_file(audit_source_path),
            }
        )
        reported_axioms = sorted(independent_axioms)
        trusted_boundary = contract.get("trusted_boundary", {})
        manifest["trust_audit"].update(
            {
                "forbidden_construct_scan_repeated": True,
                "unexpected_project_axioms": [],
                "reported_axioms": reported_axioms,
                "permitted_axioms": list(
                    trusted_boundary.get("permitted_axioms", [])
                ),
                "permitted_axiom_rationales": dict(
                    trusted_boundary.get("permitted_axiom_rationales", {})
                ),
                "unpermitted_axioms": [],
                "toolchain_and_dependency_pins_match": True,
                "source_unchanged_after_build": True,
                "trusted_boundary_accepted": True,
            }
        )
        correspondence_pass = verdict == "PASS"
        for key in (
            "quantifier_order_checked",
            "types_and_domains_checked",
            "hypotheses_checked",
            "conclusion_checked",
            "conventions_and_normalizations_checked",
            "edge_cases_checked",
            "direction_back_to_frozen_target_established",
            "anti_targets_ruled_out",
        ):
            manifest["correspondence_audit"][key] = correspondence_pass
        if correspondence_pass:
            manifest["correspondence_audit"].update(correspondence_verdict["checks"])
            manifest["correspondence_audit"]["open_correspondence_obligations"] = []
            manifest["adversarial_checks"] = correspondence_verdict["adversarial_checks"]
            manifest["explicit_nonclaims"] = correspondence_verdict["explicit_nonclaims"]
        else:
            manifest["correspondence_audit"]["open_correspondence_obligations"] = list(
                contract.get("correspondence_obligations", [])
            )
        for gate in ("LR0", "LR1", "LR2", "LR3"):
            manifest["gate_verdicts"][gate] = "PASS"
        manifest["gate_verdicts"]["LR4"] = "PASS" if correspondence_pass else "FAIL"
        manifest["gate_verdicts"]["LR5"] = "PASS" if correspondence_pass else "FAIL"
        manifest["explicit_nonclaims"] = list(
            dict.fromkeys(
                [
                    *manifest.get("explicit_nonclaims", []),
                    "No novelty, priority, attribution, or open-status conclusion.",
                    "No automatic theorem, dossier, obligation, or ledger status change.",
                ]
            )
        )
        atomic_write_json(stage / "formal_audit_manifest.yaml", manifest)
        with state_lock(root):
            current = require_room_enabled(root, "Lean audit publication")
            if current.sequence != initial.sequence or current.artifact_sha256 != initial.artifact_sha256:
                raise ValidationError("Lean Room state changed before audit publication")
            if sha256_file(contract_path) != contract_sha:
                raise ValidationError("contract changed before audit publication")
            if sha256_file(target_artifact) != target_binding.get("artifact_sha256"):
                raise ValidationError("target artifact changed before audit publication")
            if sha256_file(obligation_artifact) != obligation_binding.get("artifact_sha256"):
                raise ValidationError("proof-obligation artifact changed before audit publication")
            _, current_source_digest = project_tree_inventory(case / "project")
            if current_source_digest != frozen_digest:
                raise ValidationError("frozen source tree changed before audit publication")
            if sha256_file(candidate_path) != manifest["bindings"]["candidate_build_manifest_sha256"]:
                raise ValidationError("candidate evidence changed before audit publication")
            if sha256_file(independent_path) != manifest["bindings"]["independent_build_manifest_sha256"]:
                raise ValidationError("independent evidence changed before audit publication")
            if project_tree_inventory(candidate_path.parent)[1] != candidate_run_tree_sha:
                raise ValidationError("candidate run tree changed before audit publication")
            if project_tree_inventory(independent_path.parent)[1] != independent_run_tree_sha:
                raise ValidationError("independent run tree changed before audit publication")
            if sha256_file(correspondence_path) != manifest["bindings"]["formal_correspondence_sha256"]:
                raise ValidationError("correspondence report changed before audit publication")
            if sha256_file(verdict_path) != manifest["bindings"]["correspondence_verdict_sha256"]:
                raise ValidationError("correspondence verdict changed before audit publication")
            publish_directory_noreplace(stage, target)
        return target
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record an append-only independent Lean audit.")
    parser.add_argument("--root", help="laboratory root (normally auto-discovered)")
    parser.add_argument("problem_id")
    parser.add_argument("case_id")
    parser.add_argument("--audit-id")
    parser.add_argument("--auditor-id", required=True)
    parser.add_argument("--auditor-run-id", required=True)
    parser.add_argument("--candidate-run-id", required=True)
    parser.add_argument("--independent-run-id", required=True)
    parser.add_argument("--verdict", required=True, choices=("PASS", "FAIL", "CONDITIONAL", "ENCODED_MODEL_ONLY"))
    parser.add_argument("--attest-exact-correspondence", action="store_true")
    parser.add_argument("--unresolved-objection", action="append", default=[])
    parser.add_argument("--highest-gap-class", default=None)
    parser.add_argument("--prior-exposure", action="append", default=[])
    parser.add_argument("--withheld-material", action="append", default=[])
    parser.add_argument("--started-at")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        path = record_audit(args)
        payload = {"audit": str(path), "verdict": args.verdict}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            print(f"Lean audit recorded: {path}")
        return EXIT_OK
    except LeanRoomError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"ERROR: audit infrastructure failure: {exc}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
