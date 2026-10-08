#!/usr/bin/env python3
"""Operate a local discovery portfolio without network access."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from discovery_portfolio_lib import (
    DECISIONS,
    OPEN_ASSESSMENTS,
    _refresh_summary_locked,
    PortfolioError,
    FileLock,
    append_event,
    artifact_bindings,
    canonical_bytes,
    candidate_root,
    cleanup_abandoned_stages,
    copy_safe_file,
    copy_safe_tree,
    create_staging_directory,
    derived_funnel_observation,
    derive_candidate,
    file_digest_and_size,
    load_json,
    package_file_entries,
    package_payload_digest,
    project_id,
    publish_directory_noreplace,
    preflight_summary_update,
    remove_staging_marker,
    refresh_summary,
    require_exact_keys,
    require_id,
    require_iso,
    require_problem_id,
    require_project_id,
    require_text,
    resolve_problem,
    safe_path,
    sha256_bytes,
    sha256_file,
    utc_now,
    validate_transfer_closure,
    verify_package,
    write_json_atomic,
    write_json_atomic_exclusive,
)


ROOT = Path(__file__).resolve().parents[1]


def root_from(args: argparse.Namespace) -> Path:
    supplied = Path(args.root) if args.root else ROOT
    if supplied.is_symlink():
        raise PortfolioError("root must be a real directory")
    root = supplied.resolve()
    if not root.is_dir():
        raise PortfolioError("root must be a real directory")
    safe_path(root, "portfolio/portfolio_state.json", kind="file")
    return root


def input_json(root: Path, relative: str, label: str) -> Dict[str, Any]:
    return load_json(safe_path(root, relative, kind="file"), label)


def cmd_intake(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    value = input_json(root, args.input, "candidate intake")
    common = (
        "schema_version",
        "candidate_id",
        "title",
        "track",
        "lead",
        "why_now",
        "created_by",
        "created_at",
        "problem_id",
    )
    if value.get("schema_version") == 1:
        require_exact_keys(value, common, (), "candidate intake")
    elif value.get("schema_version") == 2:
        require_exact_keys(
            value,
            (*common, "origin", "origin_artifact_paths", "cohort_id"),
            (),
            "candidate intake",
        )
        if value["origin"] not in ("USER_SUPPLIED", "LAB_SCOUTED"):
            raise PortfolioError("candidate origin is invalid")
        if value["cohort_id"] is not None:
            require_id(value["cohort_id"], "cohort_id")
        if not isinstance(value["origin_artifact_paths"], list):
            raise PortfolioError("origin_artifact_paths must be an array")
        if any(
            not isinstance(relative, str)
            for relative in value["origin_artifact_paths"]
        ) or len(set(value["origin_artifact_paths"])) != len(
            value["origin_artifact_paths"]
        ):
            raise PortfolioError(
                "origin_artifact_paths entries must be unique strings"
            )
        if value["origin"] == "LAB_SCOUTED" and not value["origin_artifact_paths"]:
            raise PortfolioError("LAB_SCOUTED candidates require at least one source artifact")
    else:
        raise PortfolioError("candidate intake schema_version must be 1 or 2")
    candidate_id = require_id(value["candidate_id"], "candidate_id")
    require_text(value["title"], "title", single_line=True)
    require_id(value["track"], "track")
    require_text(value["lead"], "lead")
    require_text(value["why_now"], "why_now")
    if not isinstance(value["created_by"], list) or not value["created_by"]:
        raise PortfolioError("created_by must be a non-empty array")
    for actor in value["created_by"]:
        require_id(actor, "created_by entry")
    require_iso(value["created_at"], "created_at")
    if value["problem_id"] is not None:
        resolve_problem(root, require_problem_id(value["problem_id"], "problem_id"))
    origin_source_bindings = (
        artifact_bindings(
            root, value["origin_artifact_paths"], "origin_artifact_paths"
        )
        if value["schema_version"] == 2
        else []
    )
    intake_identity_sha256 = (
        sha256_bytes(
            canonical_bytes(
                {
                    "intake": value,
                    "origin_sources": origin_source_bindings,
                }
            )
        )
        if value["schema_version"] == 2
        else None
    )
    target = candidate_root(root, candidate_id)
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_dir():
            raise PortfolioError(f"candidate already exists unsafely: {candidate_id}")
        state = derive_candidate(root, target)
        metadata = state["metadata"]
        expected_common = {key: value[key] for key in common}
        actual_common = {key: metadata[key] for key in common}
        matches = (
            expected_common == actual_common
            and metadata["workflow_status_policy"]
            == "NO_MATHEMATICAL_STATUS_PROMOTION"
        )
        if value["schema_version"] == 2:
            matches = matches and (
                metadata.get("origin") == value["origin"]
                and metadata.get("cohort_id") == value["cohort_id"]
                and metadata.get("intake_identity_sha256")
                == intake_identity_sha256
            )
        if not matches:
            raise PortfolioError(
                f"candidate already exists with different intake identity: {candidate_id}"
            )
        _refresh_summary_locked(root)
        return {
            "candidate_id": candidate_id,
            "status": state["status"],
            "path": target.relative_to(root).as_posix(),
            "already_committed": True,
        }
    stage = create_staging_directory(root, "CANDIDATE")
    try:
        if value["schema_version"] == 1:
            metadata = {**value, "workflow_status_policy": "NO_MATHEMATICAL_STATUS_PROMOTION"}
        else:
            origin_paths = value["origin_artifact_paths"]
            copied_bindings = []
            evidence_directory = stage / "origin_evidence"
            evidence_directory.mkdir()
            for index, (relative, source_binding) in enumerate(
                zip(origin_paths, origin_source_bindings), 1
            ):
                source = safe_path(root, relative, kind="file")
                name = f"{index:04d}"
                destination = evidence_directory / name
                copy_safe_file(source, destination)
                digest, size = file_digest_and_size(destination)
                if (
                    digest != source_binding["sha256"]
                    or size != source_binding["size"]
                ):
                    raise PortfolioError(
                        f"origin artifact changed during intake: {relative}"
                    )
                copied_bindings.append(
                    {
                        "path": (
                            f"portfolio/candidates/{candidate_id}/"
                            f"origin_evidence/{name}"
                        ),
                        "sha256": digest,
                        "size": size,
                    }
                )
            metadata = {
                key: item
                for key, item in value.items()
                if key != "origin_artifact_paths"
            }
            metadata["origin_artifacts"] = copied_bindings
            metadata["intake_identity_sha256"] = intake_identity_sha256
            metadata["workflow_status_policy"] = "NO_MATHEMATICAL_STATUS_PROMOTION"
        write_json_atomic(stage / "candidate.json", metadata)
        (stage / "events").mkdir()
        remove_staging_marker(stage, "CANDIDATE")
        publish_directory_noreplace(stage, target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    _refresh_summary_locked(root)
    return {"candidate_id": candidate_id, "status": "LEAD", "path": target.relative_to(root).as_posix()}


def cmd_promote_engagement(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    value = input_json(root, args.input, "engagement decision")
    require_exact_keys(
        value,
        (
            "schema_version",
            "promotion_id",
            "to_tier",
            "decided_at",
            "decided_by",
            "rationale",
            "supporting_artifact_paths",
            "funnel_observation",
        ),
        (),
        "engagement decision",
    )
    if value["schema_version"] != 1:
        raise PortfolioError("engagement decision schema_version must be 1")
    event_id = require_id(value["promotion_id"], "promotion_id")
    state = derive_candidate(root, candidate_root(root, args.candidate_id))
    existing = next(
        (event for event in state["events"] if event["event_id"] == event_id),
        None,
    )
    if existing is not None and existing["event_type"] != "ENGAGEMENT_DECISION":
        raise PortfolioError(f"event_id {event_id!r} is already used by another event type")
    from_tier = (
        existing["payload"]["from_tier"]
        if existing is not None
        else state["engagement_tier"]
    )
    funnel = (
        value["funnel_observation"]
        if existing is not None
        else derived_funnel_observation(
            root, args.candidate_id, value["to_tier"], value["funnel_observation"]
        )
    )
    payload = {
        "from_tier": from_tier,
        "to_tier": value["to_tier"],
        "decided_at": value["decided_at"],
        "decided_by": value["decided_by"],
        "rationale": value["rationale"],
        "supporting_artifacts": artifact_bindings(
            root,
            value["supporting_artifact_paths"],
            "supporting artifacts",
        ),
        "funnel_observation": funnel,
    }
    path = append_event(
        root,
        args.candidate_id,
        "ENGAGEMENT_DECISION",
        event_id,
        payload,
    )
    current = derive_candidate(root, candidate_root(root, args.candidate_id))
    _refresh_summary_locked(root)
    return {
        "candidate_id": args.candidate_id,
        "event": path.relative_to(root).as_posix(),
        "status": current["status"],
        "engagement_tier": current["engagement_tier"],
        "pending_round_decision": current["pending_round_decision"],
        "mathematical_status_effect": "NONE",
    }


def cmd_link_dossier(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    value = input_json(root, args.input, "dossier link")
    require_exact_keys(value, ("schema_version", "link_id", "problem_id", "reason", "linked_by"), (), "dossier link")
    if value["schema_version"] != 1:
        raise PortfolioError("dossier link schema_version must be 1")
    link_id = require_id(value["link_id"], "link_id")
    problem_id = require_problem_id(value["problem_id"], "problem_id")
    resolve_problem(root, problem_id)
    payload = {"problem_id": problem_id, "reason": require_text(value["reason"], "reason"), "linked_by": value["linked_by"]}
    path = append_event(root, args.candidate_id, "DOSSIER_LINK", link_id, payload)
    _refresh_summary_locked(root)
    return {"candidate_id": args.candidate_id, "event": path.relative_to(root).as_posix(), "problem_id": problem_id}


def cmd_record_qualification(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    value = input_json(root, args.input, "qualification input")
    require_exact_keys(value, ("schema_version", "qualification_id", "assessed_at", "assessed_by", "exact_statement", "open_assessment", "significance_rationale", "tractability_rationale", "verification_plan", "cheap_falsifiers", "artifact_paths"), (), "qualification input")
    if value["schema_version"] != 1 or value["open_assessment"] not in OPEN_ASSESSMENTS:
        raise PortfolioError("qualification schema/open_assessment invalid")
    event_id = require_id(value.pop("qualification_id"), "qualification_id")
    artifact_paths = value.pop("artifact_paths")
    value.pop("schema_version")
    payload = {**value, "artifacts": artifact_bindings(root, artifact_paths, "artifact_paths")}
    path = append_event(root, args.candidate_id, "QUALIFICATION", event_id, payload)
    _refresh_summary_locked(root)
    return {"candidate_id": args.candidate_id, "event": path.relative_to(root).as_posix()}


def cmd_record_round(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    value = input_json(root, args.input, "round input")
    require_exact_keys(value, ("schema_version", "round_id", "started_at", "completed_at", "conducted_by", "objective", "methods", "observations", "strongest_result", "remaining_gap", "semantic_progress", "proposed_decision", "artifact_paths"), (), "round input")
    if value["schema_version"] != 1 or value["proposed_decision"] not in DECISIONS:
        raise PortfolioError("round schema/proposed_decision invalid")
    event_id = require_id(value.pop("round_id"), "round_id")
    artifact_paths = value.pop("artifact_paths")
    value.pop("schema_version")
    payload = {**value, "artifacts": artifact_bindings(root, artifact_paths, "artifact_paths")}
    path = append_event(root, args.candidate_id, "ROUND", event_id, payload)
    _refresh_summary_locked(root)
    return {
        "candidate_id": args.candidate_id,
        "event": path.relative_to(root).as_posix(),
        "pending_round_decision": True,
    }


def cmd_decide(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    value = input_json(root, args.input, "decision input")
    require_exact_keys(value, ("schema_version", "decision_id", "decision", "to_status", "decided_at", "decided_by", "rationale", "supporting_artifact_paths", "park", "reopen", "spinout"), (), "decision input")
    if value["schema_version"] != 1 or value["decision"] not in DECISIONS:
        raise PortfolioError("decision schema/enum invalid")
    event_id = require_id(value["decision_id"], "decision_id")
    state = derive_candidate(root, candidate_root(root, args.candidate_id))
    existing = next(
        (event for event in state["events"] if event["event_id"] == event_id),
        None,
    )
    if existing is not None and existing["event_type"] != "DECISION":
        raise PortfolioError(f"event_id {event_id!r} is already used by another event type")
    reopen = value["reopen"]
    if isinstance(reopen, dict) and reopen.get("evidence_artifact_path") is not None:
        binding = artifact_bindings(root, [reopen.pop("evidence_artifact_path")], "reopen evidence")
        reopen["evidence_artifact"] = binding[0]
    elif isinstance(reopen, dict):
        reopen.pop("evidence_artifact_path", None)
        reopen["evidence_artifact"] = None
    spinout = value["spinout"]
    if isinstance(spinout, dict):
        require_exact_keys(spinout, ("seed_id", "receipt_artifact_path"), (), "spinout input")
        seed_id = require_id(spinout["seed_id"], "seed_id")
        manifest_path = f"portfolio/spinouts/{seed_id}/manifest.json"
        spinout = {
            "seed_id": seed_id,
            "seed_manifest": artifact_bindings(root, [manifest_path], "seed manifest")[0],
            "receipt_artifact": artifact_bindings(root, [spinout["receipt_artifact_path"]], "spinout receipt")[0],
        }
    payload = {
        "decision": value["decision"],
        "from_status": (
            existing["payload"]["from_status"]
            if existing is not None
            else state["status"]
        ),
        "to_status": value["to_status"],
        "decided_at": value["decided_at"],
        "decided_by": value["decided_by"],
        "rationale": value["rationale"],
        "supporting_artifacts": artifact_bindings(root, value["supporting_artifact_paths"], "supporting artifacts"),
        "park": value["park"],
        "reopen": reopen,
        "spinout": spinout,
    }
    path = append_event(root, args.candidate_id, "DECISION", event_id, payload)
    current = derive_candidate(root, candidate_root(root, args.candidate_id))
    _refresh_summary_locked(root)
    return {
        "candidate_id": args.candidate_id,
        "event": path.relative_to(root).as_posix(),
        "status": current["status"],
        "pending_round_decision": current["pending_round_decision"],
    }


def _make_package(root: Path, candidate_id: str, package_id: str, target_project_id: str, kind: str, destination_parent: Path, include_dossier: bool, request_file: Optional[str]) -> Path:
    require_id(package_id, "package_id")
    require_project_id(target_project_id, "target_project_id")
    state = derive_candidate(root, candidate_root(root, candidate_id))
    if kind == "DISCOVERY_CANDIDATE_TRANSFER_V1":
        validate_transfer_closure(state)
    target = destination_parent / package_id
    if target.exists() or target.is_symlink():
        raise PortfolioError(f"package already exists: {target}")
    stage = create_staging_directory(root, "PACKAGE")
    try:
        payload = stage / "payload"
        payload.mkdir()
        copy_safe_tree(candidate_root(root, candidate_id), payload / "candidate")
        if include_dossier:
            if state["problem_id"] is None:
                raise PortfolioError("spinout seed requires a linked problem dossier")
            copy_safe_tree(resolve_problem(root, state["problem_id"]), payload / "problem_dossier")
        if request_file is not None:
            request_path = safe_path(root, request_file, kind="file")
            (payload / "request").mkdir()
            copy_safe_file(request_path, payload / "request/request.json")
        entries = package_file_entries(payload)
        manifest = {
            "schema_version": 1,
            "package_kind": kind,
            "package_id": package_id,
            "created_at": utc_now(),
            "source_project_id": project_id(root),
            "target_project_id": target_project_id,
            "candidate_id": candidate_id,
            "candidate_status": state["status"],
            "payload_root": "payload",
            "files": entries,
            "payload_digest_sha256": package_payload_digest(entries),
            "source_retained": True,
            "mathematical_status_effect": "NONE",
            "requires_factory_generation": kind == "DISCOVERY_SPINOUT_SEED_V1",
        }
        write_json_atomic(stage / "manifest.json", manifest)
        remove_staging_marker(stage, "PACKAGE")
        publish_directory_noreplace(stage, target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return target


def cmd_export(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    target = _make_package(root, args.candidate_id, args.package_id, args.target_project_id, "DISCOVERY_CANDIDATE_TRANSFER_V1", safe_path(root, "portfolio/exports", kind="dir"), False, None)
    return {"package": target.relative_to(root).as_posix(), "source_retained": True}


def cmd_import(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    package = safe_path(root, args.package, kind="dir")
    stage_root = create_staging_directory(root, "IMPORT_PREFLIGHT")
    try:
        snapshot = stage_root / "package"
        copy_safe_tree(package, snapshot)
        manifest = verify_package(snapshot, "DISCOVERY_CANDIDATE_TRANSFER_V1")
        if manifest["target_project_id"] != project_id(root):
            raise PortfolioError("transfer target_project_id does not match this laboratory")
        candidate_id = manifest["candidate_id"]
        target = candidate_root(root, candidate_id)
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_dir():
                raise PortfolioError(
                    "import refuses to merge or overwrite an unsafe candidate"
                )
            state = derive_candidate(root, target)
            receipt_path = (
                target
                / "import_receipts"
                / f"{manifest['package_id']}.json"
            )
            if not receipt_path.is_file() or receipt_path.is_symlink():
                raise PortfolioError(
                    "import refuses to merge or overwrite an existing candidate"
                )
            receipt = load_json(receipt_path, "import receipt")
            expected_manifest_digest = sha256_file(snapshot / "manifest.json")
            if (
                receipt.get("package_id") != manifest["package_id"]
                or receipt.get("package_manifest_sha256")
                != expected_manifest_digest
                or receipt.get("candidate_id") != candidate_id
                or receipt.get("source_project_id")
                != manifest["source_project_id"]
                or receipt.get("target_project_id")
                != manifest["target_project_id"]
            ):
                raise PortfolioError(
                    "existing candidate import receipt does not match this package"
                )
            _refresh_summary_locked(root)
            return {
                "candidate_id": candidate_id,
                "status": state["status"],
                "source_package_retained": package.exists(),
                "already_committed": True,
            }

        preflight_root = stage_root / "lab-view"
        staged_candidate = preflight_root / "portfolio/candidates" / candidate_id
        staged_candidate.parent.mkdir(parents=True)
        for state_name in ("active", "backlog", "closed"):
            (preflight_root / "problems" / state_name).mkdir(parents=True)
        copy_safe_tree(snapshot / "payload/candidate", staged_candidate)
        receipt = {
            "schema_version": 1,
            "package_id": manifest["package_id"],
            "package_manifest_sha256": sha256_file(snapshot / "manifest.json"),
            "candidate_id": candidate_id,
            "source_project_id": manifest["source_project_id"],
            "target_project_id": manifest["target_project_id"],
            "imported_at": utc_now(),
            "source_package_retained": True,
            "mathematical_status_effect": "NONE",
        }
        write_json_atomic_exclusive(
            staged_candidate
            / "import_receipts"
            / f"{manifest['package_id']}.json",
            receipt,
            staging_directory=stage_root,
        )
        staged_state = derive_candidate(
            preflight_root, staged_candidate, verify_artifacts_now=True
        )
        validate_transfer_closure(staged_state)
        if staged_state["status"] != manifest["candidate_status"]:
            raise PortfolioError(
                "transfer manifest candidate_status does not match staged candidate history"
            )
        publish_directory_noreplace(staged_candidate, target)
    finally:
        if stage_root.exists():
            shutil.rmtree(stage_root)
    derive_candidate(root, target)
    _refresh_summary_locked(root)
    return {"candidate_id": candidate_id, "status": manifest["candidate_status"], "source_package_retained": package.exists()}


def cmd_prepare_spinout(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    state = derive_candidate(root, candidate_root(root, args.candidate_id))
    if state["status"] != "SPINOUT_READY":
        raise PortfolioError("spinout seed may be prepared only from SPINOUT_READY")
    request = input_json(root, args.request, "spinout request draft")
    require_exact_keys(request, ("schema_version", "target_lab_id", "directory_name", "title", "mission", "areas", "deliverables", "unresolved_questions"), (), "spinout request draft")
    if request["schema_version"] != 1 or request["target_lab_id"] != args.target_lab_id:
        raise PortfolioError("spinout request target identity mismatch")
    require_project_id(request["target_lab_id"], "target_lab_id")
    for field in ("directory_name", "title", "mission"):
        require_text(request[field], field)
    for field in ("areas", "deliverables", "unresolved_questions"):
        if not isinstance(request[field], list) or any(not isinstance(item, str) or not item.strip() for item in request[field]):
            raise PortfolioError(f"{field} must be an array of non-empty strings")
    target = _make_package(root, args.candidate_id, args.seed_id, args.target_lab_id, "DISCOVERY_SPINOUT_SEED_V1", safe_path(root, "portfolio/spinouts", kind="dir"), True, args.request)
    return {"seed": target.relative_to(root).as_posix(), "requires_factory_generation": True, "source_retained": True}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", help="laboratory root (tests and audited tooling only)")
    sub = result.add_subparsers(dest="command", required=True)
    intake = sub.add_parser("intake")
    intake.add_argument("--input", required=True)
    for name in (
        "link-dossier",
        "record-qualification",
        "record-round",
        "decide",
        "promote-engagement",
    ):
        command = sub.add_parser(name)
        command.add_argument("--candidate-id", required=True)
        command.add_argument("--input", required=True)
    export = sub.add_parser("export")
    export.add_argument("--candidate-id", required=True)
    export.add_argument("--package-id", required=True)
    export.add_argument("--target-project-id", required=True)
    import_parser = sub.add_parser("import")
    import_parser.add_argument("--package", required=True)
    spinout = sub.add_parser("prepare-spinout")
    spinout.add_argument("--candidate-id", required=True)
    spinout.add_argument("--seed-id", required=True)
    spinout.add_argument("--target-lab-id", required=True)
    spinout.add_argument("--request", required=True)
    sub.add_parser("refresh-summary")
    sub.add_parser("status")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        root = root_from(args)
        if args.command == "status":
            from discovery_portfolio_lib import list_candidates
            candidates = list_candidates(root)
            payload = {
                "candidates": [
                    {
                        "candidate_id": item["metadata"]["candidate_id"],
                        "status": item["status"],
                        "engagement_tier": item["engagement_tier"],
                        "origin": item["origin"],
                        "cohort_id": item["cohort_id"],
                        "problem_id": item["problem_id"],
                        "pending_round_decision": item["pending_round_decision"],
                    }
                    for item in candidates
                ]
            }
        elif args.command == "refresh-summary":
            payload = refresh_summary(root)
        else:
            handlers = {
                "intake": cmd_intake,
                "link-dossier": cmd_link_dossier,
                "record-qualification": cmd_record_qualification,
                "record-round": cmd_record_round,
                "decide": cmd_decide,
                "promote-engagement": cmd_promote_engagement,
                "export": cmd_export,
                "import": cmd_import,
                "prepare-spinout": cmd_prepare_spinout,
            }
            with FileLock(root / "portfolio/.discovery-portfolio.lock"):
                cleanup_abandoned_stages(root)
                if args.command in {
                    "intake",
                    "link-dossier",
                    "record-qualification",
                    "record-round",
                    "decide",
                    "promote-engagement",
                    "import",
                }:
                    with FileLock(root / "knowledge/.control-room-summary.lock"):
                        preflight_summary_update(root)
                        payload = handlers[args.command](root, args)
                else:
                    payload = handlers[args.command](root, args)
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    except PortfolioError as exc:
        print(f"discovery portfolio error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
