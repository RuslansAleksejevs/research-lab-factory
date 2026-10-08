#!/usr/bin/env python3
"""Issue an exact-scope LR6 certificate from a bound PASS audit."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from lean_room import (
    EXIT_OK,
    LeanRoomError,
    ValidationError,
    atomic_write_json,
    case_path,
    discover_root,
    ensure_within,
    load_json_object,
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
from record_lean_audit import (
    _require_complete_pass_report,
    _validate_correspondence_verdict,
    validate_pass_build_evidence,
)
from verify_lean_case import verify as execute_guarded_verification


def _is_pass(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.upper() in {"PASS", "PASSED", "SUCCESS"})


def _case_file(case: Path, relative: str, label: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValidationError(f"unsafe {label} path: {relative!r}")
    target = case / candidate
    ensure_within(target, case, label)
    reject_symlink_components(target, case)
    if target.is_symlink() or not target.is_file():
        raise ValidationError(f"missing regular {label}: {target}")
    return target


def _audit_bound_file(case: Path, audit_dir: Path, value: Any, expected: Any, label: str) -> Path:
    if not isinstance(value, str) or not isinstance(expected, str):
        raise ValidationError(f"audit lacks {label} binding")
    candidate = Path(value)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValidationError(f"unsafe {label} binding is forbidden")
    # Correspondence snapshots are audit-relative; build and contract bindings
    # are case-relative. Resolve both explicitly and accept only one existing file.
    options = [audit_dir / candidate, case / candidate]
    matches: list[Path] = []
    for option in options:
        try:
            ensure_within(option, case, label)
            reject_symlink_components(option, case)
        except ValidationError:
            continue
        if option.is_file() and not option.is_symlink():
            matches.append(option)
    unique = list(dict.fromkeys(matches))
    if len(unique) != 1:
        raise ValidationError(f"{label} binding is ambiguous or missing: {value!r}")
    if sha256_file(unique[0]) != expected:
        raise ValidationError(f"{label} SHA-256 mismatch")
    return unique[0]


def _load_template(root: Path) -> dict[str, Any]:
    value = load_json_object(
        root / "templates/lean_room/formal_certificate_manifest.yaml",
        "formal certificate template",
    )
    if value.get("record_type") != "lean_formal_certificate":
        raise ValidationError("invalid formal certificate template")
    return value


def _lr0_preserved_artifact(
    case: Path, contract: dict[str, Any], kind: str, expected_sha256: str
) -> Path:
    freeze = contract.get("freeze")
    snapshot_id = freeze.get("lr0_snapshot_id") if isinstance(freeze, dict) else None
    if not isinstance(snapshot_id, str):
        raise ValidationError("contract lacks LR0 snapshot identity")
    snapshot_dir = case / "evidence/freezes" / snapshot_id
    reject_symlink_components(snapshot_dir, case)
    manifest = load_json_object(snapshot_dir / "freeze_manifest.yaml", "LR0 freeze manifest")
    preserved = manifest.get("preserved_artifacts")
    if not isinstance(preserved, list):
        raise ValidationError("LR0 freeze lacks preserved target artifacts")
    matches = [item for item in preserved if isinstance(item, dict) and item.get("kind") == kind]
    if len(matches) != 1 or matches[0].get("sha256") != expected_sha256:
        raise ValidationError(f"LR0 preserved {kind} binding mismatch")
    path = _case_file(
        case,
        (snapshot_dir / str(matches[0].get("snapshot_artifact"))).relative_to(case).as_posix(),
        f"LR0 preserved {kind}",
    )
    if sha256_file(path) != expected_sha256:
        raise ValidationError(f"LR0 preserved {kind} digest mismatch")
    return path


def issue_certificate(args: argparse.Namespace) -> Path:
    root = discover_root(args.root)
    initial = require_room_enabled(root, "Lean LR6 certificate issuance")
    problem_id = validate_identifier(args.problem_id, "problem id")
    case_id = validate_identifier(args.case_id, "case id")
    audit_id = validate_identifier(args.audit_id, "audit id")
    issued_by = validate_identifier(args.issued_by, "certificate issuer")
    case = case_path(root, problem_id, case_id)
    validation = validate_case(root, problem_id, case_id, verification_ready=True)
    if not validation.ok or validation.contract is None or validation.source_tree_sha256 is None:
        raise ValidationError("certificate requires a valid frozen case: " + "; ".join(validation.issues))
    contract = validation.contract
    contract_path = case / "formalization_contract.yaml"
    contract_sha = sha256_file(contract_path)
    audit_dir = case / "audits" / audit_id
    reject_symlink_components(audit_dir, case)
    audit_path = audit_dir / "formal_audit_manifest.yaml"
    audit = load_json_object(audit_path, "formal audit manifest")
    if (
        audit.get("schema_version") != 1
        or audit.get("record_type") != "lean_formal_audit"
        or audit.get("audit_id") != audit_id
        or audit.get("problem_id") != problem_id
        or audit.get("case_id") != case_id
    ):
        raise ValidationError("formal audit identity mismatch")
    if audit.get("verdict") != "PASS" or audit.get("certificate_eligible") is not True:
        raise ValidationError("LR6 requires a certificate-eligible PASS audit")
    independence = audit.get("independence")
    if not isinstance(independence, dict) or independence.get("eligible_as_decisive_auditor") is not True:
        raise ValidationError("LR6 requires a decisive independent auditor")
    gate_verdicts = audit.get("gate_verdicts")
    if not isinstance(gate_verdicts, dict) or not all(
        _is_pass(gate_verdicts.get(gate)) for gate in ("LR0", "LR1", "LR2", "LR3", "LR4", "LR5")
    ):
        raise ValidationError("LR6 requires PASS LR0-LR5 verdicts")
    if audit.get("unresolved_objections"):
        raise ValidationError("LR6 cannot issue with unresolved audit objections")
    bindings = audit.get("bindings")
    if not isinstance(bindings, dict):
        raise ValidationError("audit bindings are missing")
    if bindings.get("contract_sha256") != contract_sha:
        raise ValidationError("audit is bound to a different contract")
    if (
        bindings.get("target_id") != contract.get("target_binding", {}).get("target_id")
        or bindings.get("target_sha256")
        != contract.get("target_binding", {}).get("artifact_sha256")
        or bindings.get("obligation_ids")
        != contract.get("obligation_binding", {}).get("obligation_ids")
    ):
        raise ValidationError("audit target/obligation binding mismatch")
    frozen_digest = contract.get("freeze", {}).get("frozen_source_tree_sha256")
    if bindings.get("source_tree_sha256") != frozen_digest or validation.source_tree_sha256 != frozen_digest:
        raise ValidationError("audit/case source-tree binding mismatch")

    candidate_path = _audit_bound_file(
        case,
        audit_dir,
        bindings.get("candidate_build_manifest"),
        bindings.get("candidate_build_manifest_sha256"),
        "candidate build manifest",
    )
    independent_path = _audit_bound_file(
        case,
        audit_dir,
        bindings.get("independent_build_manifest"),
        bindings.get("independent_build_manifest_sha256"),
        "independent build manifest",
    )
    correspondence_path = _audit_bound_file(
        case,
        audit_dir,
        bindings.get("correspondence_report"),
        bindings.get("correspondence_report_sha256"),
        "correspondence report",
    )
    verdict_path = _audit_bound_file(
        case,
        audit_dir,
        bindings.get("correspondence_verdict"),
        bindings.get("correspondence_verdict_sha256"),
        "correspondence verdict",
    )
    candidate_checked_path, candidate, _ = validate_pass_build_evidence(
        case, candidate_path.parent.name, contract, "candidate"
    )
    independent_checked_path, independent, independent_axioms = validate_pass_build_evidence(
        case, independent_path.parent.name, contract, "independent"
    )
    if candidate_checked_path != candidate_path or independent_checked_path != independent_path:
        raise ValidationError("audit build bindings do not resolve to their canonical run artifacts")
    from lean_room import project_tree_inventory

    candidate_run_tree_sha = project_tree_inventory(candidate_path.parent)[1]
    independent_run_tree_sha = project_tree_inventory(independent_path.parent)[1]
    if (
        bindings.get("candidate_build_run_tree_sha256") != candidate_run_tree_sha
        or bindings.get("independent_build_run_tree_sha256") != independent_run_tree_sha
    ):
        raise ValidationError("audit build-run tree binding mismatch")
    if candidate_path == independent_path:
        raise ValidationError("LR6 requires a distinct independent rebuild")
    if candidate.get("runner_id") == independent.get("runner_id"):
        raise ValidationError("candidate and independent rebuild runners must differ")
    if issued_by in {candidate.get("runner_id"), independent.get("runner_id")}:
        raise ValidationError(
            "certificate issuer must differ from candidate and independent build runners"
        )
    acceptance = contract.get("acceptance_criterion")
    certificate_scope = acceptance.get("certificate_scope") if isinstance(acceptance, dict) else None
    if not isinstance(certificate_scope, str) or not certificate_scope.strip():
        raise ValidationError("LR6 requires an exact nonempty certificate_scope")
    correspondence_text = correspondence_path.read_text(encoding="utf-8")
    _require_complete_pass_report(correspondence_text)
    correspondence_verdict = load_json_object(
        verdict_path, "machine-checkable correspondence verdict snapshot"
    )
    auditor_id = audit.get("auditor_id")
    auditor_run_id = audit.get("auditor_run_id")
    if (
        not isinstance(auditor_id, str)
        or independent.get("runner_id") != auditor_id
        or independent.get("run_id") != auditor_run_id
    ):
        raise ValidationError("audit identity is not bound to the independent rebuild")
    lineage = contract.get("lineage")
    lineage = lineage if isinstance(lineage, dict) else {}
    if (
        independence.get("auditor_disjoint_from_generation_and_repair") is not True
        or independence.get("generator_run_ids") != lineage.get("generator_run_ids", [])
        or independence.get("material_repair_run_ids")
        != lineage.get("material_repair_run_ids", [])
        or independence.get("generator_agent_ids")
        != lineage.get("generator_agent_ids", [])
        or independence.get("material_repair_agent_ids")
        != lineage.get("material_repair_agent_ids", [])
        or auditor_run_id
        in {
            value
            for key in (
                "generator_run_ids",
                "material_repair_run_ids",
                "prohibited_decisive_auditor_run_ids",
            )
            for value in lineage.get(key, [])
            if isinstance(value, str)
        }
    ):
        raise ValidationError("audit independence/lineage binding mismatch")
    prohibited_agent_ids = {
        value
        for key in (
            "generator_agent_ids",
            "material_repair_agent_ids",
            "prohibited_decisive_auditor_agent_ids",
        )
        for value in lineage.get(key, [])
        if isinstance(value, str)
    }
    if auditor_id in prohibited_agent_ids or issued_by in prohibited_agent_ids:
        raise ValidationError(
            "auditor or certificate issuer overlaps prohibited source-agent lineage"
        )
    _validate_correspondence_verdict(
        correspondence_verdict,
        problem_id=problem_id,
        case_id=case_id,
        auditor_id=auditor_id,
        auditor_run_id=auditor_run_id,
        contract_sha=contract_sha,
        target_sha=contract["target_binding"].get("artifact_sha256"),
        source_digest=frozen_digest,
        candidate_run_id=candidate.get("run_id"),
        independent_run_id=independent.get("run_id"),
        certificate_scope=certificate_scope,
    )
    correspondence_checks = audit.get("correspondence_audit")
    if not isinstance(correspondence_checks, dict) or any(
        correspondence_checks.get(key) is not True
        for key in correspondence_verdict["checks"]
    ):
        raise ValidationError("audit manifest does not reproduce the PASS correspondence checks")
    if audit.get("highest_gap_class") != "GS0" or audit.get("unresolved_objections") != []:
        raise ValidationError("LR6 requires a GS0 audit with no unresolved objections")
    if audit.get("adversarial_checks") != correspondence_verdict.get("adversarial_checks"):
        raise ValidationError("audit adversarial checks differ from the bound verdict")
    formal_audit = audit.get("formal_declaration")
    formal_contract = contract.get("formal_target")
    if not isinstance(formal_audit, dict) or not isinstance(formal_contract, dict) or (
        formal_audit.get("source_file") != formal_contract.get("source_file")
        or formal_audit.get("declaration_name") != formal_contract.get("declaration_name")
        or formal_audit.get("contract_exact_type") != formal_contract.get("exact_type")
        or formal_audit.get("type_equality_mode")
        != "kernel_definitional_equality_without_coercion"
    ):
        raise ValidationError("audit formal declaration differs from frozen contract")
    type_output_path = _audit_bound_file(
        case,
        audit_dir,
        formal_audit.get("type_output_artifact"),
        formal_audit.get("type_output_sha256"),
        "formal declaration command output",
    )
    audit_source_path = _audit_bound_file(
        case,
        audit_dir,
        formal_audit.get("audit_source_artifact"),
        formal_audit.get("audit_source_sha256"),
        "exact-type audit source",
    )
    if (
        type_output_path != independent_path.parent / "axioms.txt"
        or audit_source_path != independent_path.parent / "declaration_audit.lean"
    ):
        raise ValidationError("audit type evidence is not bound to the independent rebuild")
    trust_audit = audit.get("trust_audit")
    trusted_boundary = contract.get("trusted_boundary", {})
    if (
        not isinstance(trust_audit, dict)
        or trust_audit.get("trusted_boundary_accepted") is not True
        or sorted(trust_audit.get("reported_axioms", [])) != sorted(independent_axioms)
        or trust_audit.get("permitted_axioms")
        != trusted_boundary.get("permitted_axioms", [])
        or trust_audit.get("permitted_axiom_rationales")
        != trusted_boundary.get("permitted_axiom_rationales", {})
        or trust_audit.get("unpermitted_axioms") != []
    ):
        raise ValidationError("audit trust-boundary result does not match independent evidence")
    target_binding = contract.get("target_binding")
    obligation_binding = contract.get("obligation_binding")
    if not isinstance(target_binding, dict) or not isinstance(obligation_binding, dict):
        raise ValidationError("contract target/obligation bindings are missing")
    target_artifact = safe_relative_file(root, target_binding["artifact"], "target artifact")
    obligation_artifact = safe_relative_file(root, obligation_binding["artifact"], "proof-obligation artifact")
    if sha256_file(target_artifact) != target_binding.get("artifact_sha256"):
        raise ValidationError("target artifact changed before LR6")
    if sha256_file(obligation_artifact) != obligation_binding.get("artifact_sha256"):
        raise ValidationError("proof-obligation artifact changed before LR6")
    preserved_target = _lr0_preserved_artifact(
        case, contract, "informal_target", target_binding["artifact_sha256"]
    )
    preserved_obligation = _lr0_preserved_artifact(
        case, contract, "proof_obligations", obligation_binding["artifact_sha256"]
    )

    independent_axiom_path = type_output_path
    if independent_axiom_path.is_symlink() or not independent_axiom_path.is_file():
        raise ValidationError("independent rebuild lacks axioms.txt")
    timestamp = utc_now()
    certificate_id = args.certificate_id or (
        "CERT-" + timestamp.replace("-", "").replace(":", "").replace(".", "") + "-" + frozen_digest[:12]
    )
    certificate_id = validate_identifier(certificate_id, "certificate id")
    target = case / "certificates" / certificate_id
    if target.exists() or target.is_symlink():
        raise ValidationError(f"certificate already exists: {certificate_id}")

    # LR6 does not rely solely on writable, caller-supplied prior run records.
    # Immediately before issuance, perform a third clean guarded build under a
    # distinct issuer identity and bind that new run into the certificate.
    certification_run_dir, certification_result, certification_exit = (
        execute_guarded_verification(
            argparse.Namespace(
                root=str(root),
                problem_id=problem_id,
                case_id=case_id,
                runner_id=issued_by,
                run_kind="certification",
                timeout=args.rebuild_timeout,
                json=False,
            )
        )
    )
    if certification_exit != EXIT_OK or certification_result != "PASS":
        raise ValidationError(
            "fresh LR6 certification rebuild did not PASS; its failure evidence was preserved"
        )
    certification_checked_path, certification, certification_axioms = (
        validate_pass_build_evidence(
            case,
            certification_run_dir.name,
            contract,
            "certification",
        )
    )
    if certification_checked_path != certification_run_dir / "build_manifest.yaml":
        raise ValidationError("fresh certification build path is non-canonical")
    if certification.get("runner_id") != issued_by:
        raise ValidationError("fresh certification build issuer identity mismatch")
    if certification_axioms != independent_axioms:
        raise ValidationError(
            "fresh certification build axiom report differs from independent rebuild"
        )
    certification_run_tree_sha = project_tree_inventory(certification_run_dir)[1]
    axiom_path = certification_run_dir / "axioms.txt"
    if axiom_path.is_symlink() or not axiom_path.is_file():
        raise ValidationError("fresh certification rebuild lacks axioms.txt")
    certificates = safe_append_container(case, "certificates")
    stage = Path(tempfile.mkdtemp(prefix=f".{certificate_id}.stage-", dir=str(certificates)))
    try:
        manifest = _load_template(root)
        manifest.update(
            {
                "certificate_id": certificate_id,
                "case_id": case_id,
                "problem_id": problem_id,
                "issued_at": timestamp,
                "issued_by": issued_by,
                "room_state_at_issuance": initial.effective_state,
                "status": "ISSUED",
            }
        )
        manifest["bindings"].update(
            {
                "contract": "../../formalization_contract.yaml",
                "contract_sha256": contract_sha,
                "target_id": target_binding.get("target_id"),
                "target_artifact": preserved_target.relative_to(root).as_posix(),
                "target_sha256": target_binding.get("artifact_sha256"),
                "proof_obligations_artifact": preserved_obligation.relative_to(root).as_posix(),
                "proof_obligations_sha256": obligation_binding.get("artifact_sha256"),
                "obligation_ids": obligation_binding.get("obligation_ids", []),
                "source_tree_sha256": frozen_digest,
                "formal_correspondence": correspondence_path.relative_to(case).as_posix(),
                "formal_correspondence_sha256": sha256_file(correspondence_path),
                "correspondence_report": correspondence_path.relative_to(case).as_posix(),
                "correspondence_report_sha256": sha256_file(correspondence_path),
                "correspondence_verdict": verdict_path.relative_to(case).as_posix(),
                "correspondence_verdict_sha256": sha256_file(verdict_path),
                "candidate_build_manifest": candidate_path.relative_to(case).as_posix(),
                "candidate_build_manifest_sha256": sha256_file(candidate_path),
                "candidate_build_run_tree_sha256": candidate_run_tree_sha,
                "independent_build_manifest": independent_path.relative_to(case).as_posix(),
                "independent_build_manifest_sha256": sha256_file(independent_path),
                "independent_build_run_tree_sha256": independent_run_tree_sha,
                "certification_build_manifest": certification_checked_path.relative_to(case).as_posix(),
                "certification_build_manifest_sha256": sha256_file(certification_checked_path),
                "certification_build_run_tree_sha256": certification_run_tree_sha,
                "formal_audit_manifest": audit_path.relative_to(case).as_posix(),
                "formal_audit_manifest_sha256": sha256_file(audit_path),
                "axiom_report": axiom_path.relative_to(case).as_posix(),
                "axiom_report_sha256": sha256_file(axiom_path),
            }
        )
        formal = contract["formal_target"]
        manifest["formal_declaration"].update(
            {
                "source_file": formal.get("source_file"),
                "namespace": formal.get("namespace"),
                "declaration_name": formal.get("declaration_name"),
                "exact_type": formal.get("exact_type"),
            }
        )
        for gate in ("LR0", "LR1", "LR2", "LR3", "LR4", "LR5", "LR6"):
            manifest["gate_verdicts"][gate] = "PASS"
        informal = contract.get("informal_claim")
        informal = informal if isinstance(informal, dict) else {}
        trusted = contract.get("trusted_boundary")
        trusted = trusted if isinstance(trusted, dict) else {}
        encoding = contract.get("encoding")
        encoding = encoding if isinstance(encoding, dict) else {}
        explicit_nonclaims = list(acceptance.get("explicit_nonclaims", [])) if isinstance(acceptance, dict) else []
        explicit_nonclaims.extend(
            [
                "No automatic theorem, dossier, obligation, or ledger status change.",
                "No novelty, priority, attribution, authorship, or open-status conclusion.",
            ]
        )
        manifest["exact_scope"].update(
            {
                "certified_claim": certificate_scope,
                "exact_assumptions": list(informal.get("hypotheses", [])),
                "quantifiers": list(informal.get("quantifiers", [])),
                "ambient_objects_and_types": list(
                    informal.get("ambient_objects_and_types", [])
                ),
                "parameters_and_domains": list(
                    informal.get("parameters_and_domains", [])
                ),
                "conventions": list(informal.get("conventions", [])),
                "edge_cases": list(informal.get("edge_cases", [])),
                "encoding_objects": list(encoding.get("objects", [])),
                "encoding_relations_and_predicates": list(
                    encoding.get("relations_and_predicates", [])
                ),
                "encoding_maps": list(encoding.get("maps", [])),
                "encoding_parameters": list(encoding.get("parameters", [])),
                "encoding_normalizations": list(
                    encoding.get("normalizations", [])
                ),
                "encoding_bridge_lemmas": list(encoding.get("bridge_lemmas", [])),
                "known_loss_or_strengthening": list(
                    encoding.get("known_loss_or_strengthening", [])
                ),
                "permitted_axioms": list(trusted.get("permitted_axioms", [])),
                "permitted_axiom_rationales": dict(
                    trusted.get("permitted_axiom_rationales", {})
                ),
                "trusted_computing_base": [
                    "Pinned Lean 4 kernel/toolchain",
                    "Guarded dependency-free Lake build",
                    "macOS deny-default Seatbelt execution boundary",
                    "Explicit auditor identity/lineage attestation; local identity is not OS-sealed or cryptographically authenticated",
                    "Integrity of the complete local Lean toolchain installation, laboratory scripts, workspace, and writable evidence store",
                ],
                "residual_caveats": list(trusted.get("residual_risks", [])),
                "explicit_nonclaims": list(dict.fromkeys(explicit_nonclaims)),
            }
        )
        manifest["research_integration"].update(
            {
                "eligible_obligation_ids": obligation_binding.get("obligation_ids", []),
                "automatic_obligation_closure": False,
                "automatic_theorem_status_promotion": False,
                "automatic_ledger_promotion": False,
                "required_follow_up_decision_artifact": "problem dossier decision or ledger update under its own workflow",
            }
        )
        atomic_write_json(stage / "formal_certificate_manifest.yaml", manifest)
        with state_lock(root):
            current = require_room_enabled(root, "Lean LR6 certificate publication")
            if current.sequence != initial.sequence or current.artifact_sha256 != initial.artifact_sha256:
                raise ValidationError("Lean Room state changed before certificate publication")
            if sha256_file(contract_path) != contract_sha or sha256_file(audit_path) != manifest["bindings"]["formal_audit_manifest_sha256"]:
                raise ValidationError("bound contract or audit changed before certificate publication")
            if project_tree_inventory(case / "project")[1] != frozen_digest:
                raise ValidationError("frozen Lean source tree changed before certificate publication")
            if sha256_file(candidate_path) != manifest["bindings"]["candidate_build_manifest_sha256"]:
                raise ValidationError("candidate build evidence changed before certificate publication")
            if sha256_file(independent_path) != manifest["bindings"]["independent_build_manifest_sha256"]:
                raise ValidationError("independent build evidence changed before certificate publication")
            if sha256_file(certification_checked_path) != manifest["bindings"]["certification_build_manifest_sha256"]:
                raise ValidationError("fresh certification build evidence changed before certificate publication")
            if project_tree_inventory(candidate_path.parent)[1] != manifest["bindings"]["candidate_build_run_tree_sha256"]:
                raise ValidationError("candidate build run changed before certificate publication")
            if project_tree_inventory(independent_path.parent)[1] != manifest["bindings"]["independent_build_run_tree_sha256"]:
                raise ValidationError("independent build run changed before certificate publication")
            if project_tree_inventory(certification_run_dir)[1] != manifest["bindings"]["certification_build_run_tree_sha256"]:
                raise ValidationError("fresh certification build run changed before certificate publication")
            if sha256_file(correspondence_path) != manifest["bindings"]["correspondence_report_sha256"]:
                raise ValidationError("correspondence report changed before certificate publication")
            if sha256_file(verdict_path) != manifest["bindings"]["correspondence_verdict_sha256"]:
                raise ValidationError("correspondence verdict changed before certificate publication")
            if sha256_file(target_artifact) != manifest["bindings"]["target_sha256"]:
                raise ValidationError("target artifact changed before certificate publication")
            if sha256_file(obligation_artifact) != manifest["bindings"]["proof_obligations_sha256"]:
                raise ValidationError("proof-obligation artifact changed before certificate publication")
            if sha256_file(preserved_target) != manifest["bindings"]["target_sha256"]:
                raise ValidationError("preserved LR0 target changed before certificate publication")
            if sha256_file(preserved_obligation) != manifest["bindings"]["proof_obligations_sha256"]:
                raise ValidationError("preserved LR0 obligations changed before certificate publication")
            if sha256_file(axiom_path) != manifest["bindings"]["axiom_report_sha256"]:
                raise ValidationError("axiom report changed before certificate publication")
            publish_directory_noreplace(stage, target)
        return target
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Issue a bound LR6 Lean formal certificate.")
    parser.add_argument("--root", help="laboratory root (normally auto-discovered)")
    parser.add_argument("problem_id")
    parser.add_argument("case_id")
    parser.add_argument("--audit-id", required=True)
    parser.add_argument("--issued-by", required=True)
    parser.add_argument("--certificate-id")
    parser.add_argument(
        "--rebuild-timeout",
        type=float,
        default=600.0,
        help="timeout in seconds for the mandatory fresh LR6 guarded rebuild",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.rebuild_timeout <= 0:
        print("ERROR: rebuild timeout must be positive", file=sys.stderr)
        return ValidationError.exit_code
    try:
        path = issue_certificate(args)
        payload = {"certificate": str(path), "status": "ISSUED"}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            print(f"Lean LR6 certificate issued: {path}")
        return EXIT_OK
    except LeanRoomError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR: certificate infrastructure failure: {exc}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
