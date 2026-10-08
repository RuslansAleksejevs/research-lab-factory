#!/usr/bin/env python3
"""Guarded, auditable maintenance transactions for one research laboratory.

This script protects bytes and declared state transitions.  It does not decide
whether mathematics is true, novel, valuable, or independently verified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import laboratory_survey as survey


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ITEM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")

RUNS_PREFIX = "runs/laboratory_stewardship/"
ALLOWED_EXACT = {"BACKLOG.md", "problems/INDEX.md"}
ALLOWED_PREFIXES = (
    "knowledge/",
    "decisions/",
    "problems/active/",
    "problems/backlog/",
    "problems/closed/",
    "research/",
    "results/",
    "sources/manifests/",
    "sources/digests/",
    "sources/bibliography/",
    "paper/",
    "research_reports/",
    "talks/",
)
DERIVED_BLOCKED = {
    "knowledge/resume.md",
    "knowledge/laboratory_overview.md",
    "knowledge/laboratory_survey_state.json",
}
APPEND_ONLY_PREFIXES = (
    "research/checkpoints/",
    "results/",
    "sources/digests/",
)
APPEND_ONLY_PARTS = {
    "attempts",
    "counterexamples",
    "external_llm_responses",
    "search_rounds",
    "verifier_reports",
}
REPAIR_CLASSES = {
    "MECHANICAL_HYGIENE",
    "EVIDENCE_RECONCILIATION",
    "RESEARCH_ORGANIZATION",
    "NEW_UNVERIFIED_RESEARCH",
    "PROTECTED_STATUS_TRANSITION",
}
MATHEMATICAL_EFFECTS = {
    "NONE",
    "EXPOSITION_ONLY",
    "NEW_UNVERIFIED_RESEARCH",
    "RECORD_EXISTING_VERDICT",
    "SYNCHRONIZE_EXISTING_DOSSIER_STATUS",
}
MODES = {"DEEP_LOCAL", "STANDARD_LOCAL"}
LITERATURE_MODES = {"NOT_AUTHORIZED", "EXPLICIT_PUBLIC_SAFE_DELTA"}
STRONG_STATUSES = {
    "VERIFIED_INTERNAL",
    "VERIFIED_USING_CITED_RESULTS",
    "FORMALLY_VERIFIED",
    "VERIFIED_PROOF",
    "VERIFIED_COUNTEREXAMPLE",
    "PROVED",
    "PROVEN",
    "ESTABLISHED",
    "CERTIFIED",
    "REFUTED",
    "DISPROVED",
    "PASS",
}
AUTHORITATIVE_DOSSIER_STATUSES = {
    "VERIFIED_PROOF": "CLOSED_PROOF",
    "VERIFIED_COUNTEREXAMPLE": "CLOSED_COUNTEREXAMPLE",
}
INDEX_STATUS_PROJECTION_TARGETS = {
    "knowledge/research_state.yaml",
}
INDEX_DOSSIER_STATUS_FIELD = re.compile(r"^dossiers\[[0-9]+\]\.global_status$")
INDEX_TRACK_STATUS_FIELD = re.compile(r"^tracks\.[A-Za-z0-9._-]+\.status$")
SUPPLEMENTAL_TRANSACTION_PATHS = {
    "problems/INDEX.md",
}
PROOF_I3_ALLOWED_DESTINATIONS = {
    "VERIFIED_INTERNAL",
    "VERIFIED_USING_CITED_RESULTS",
    "VERIFIED_PROOF",
    "PROVED",
    "PROVEN",
    "ESTABLISHED",
    "CERTIFIED",
}
CONSERVATIVE_STATUS_DESTINATIONS = {
    "UNKNOWN",
    "PLAUSIBLE_UNVERIFIED",
    "CONDITIONAL",
    "FAILED_ATTEMPT",
    "UNRESOLVED",
    "UNRECONCILED",
    "NOT_ESTABLISHED",
    "CANDIDATE",
    "PROPOSED_DIRECTION",
    "UNVERIFIED",
    "UNVERIFIED_COMPUTATIONAL_CLAIM",
    "INCONCLUSIVE",
    "UNTESTED",
    "OPEN",
    "IN_PROGRESS",
    "ACTIVE",
    "INITIALIZED",
    "BLOCKED",
    "DEFERRED",
    "UNINITIALIZED",
    "SEARCHING",
    "UNDER_AUDIT",
    "AUDIT_CANDIDATE",
    "CHECKPOINT_INCOMPLETE",
    "CONTRACT_FROZEN",
}


class StewardshipError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode(
        "utf-8"
    ) + b"\n"


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def require_root(path: Path) -> Path:
    try:
        return survey.require_root(path)
    except survey.SurveyError as exc:
        raise StewardshipError(str(exc)) from exc


def require_lab_root(path: Path) -> Path:
    root = require_root(path)
    try:
        survey.require_lab_identity(root)
    except (AttributeError, survey.SurveyError) as exc:
        raise StewardshipError(f"write-capable stewardship requires a laboratory root: {exc}") from exc
    return root


def canonical_relative(raw: Any, label: str) -> str:
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        raise StewardshipError(f"{label} must be a non-empty portable relative path")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise StewardshipError(f"{label} is not canonical: {raw!r}")
    return path.as_posix()


def fs_path(root: Path, relative: str) -> Path:
    return root.joinpath(*PurePosixPath(relative).parts)


def run_relative(run_id: str) -> str:
    if not RUN_ID.fullmatch(run_id):
        raise StewardshipError(
            "run id must use 1-96 ASCII letters, digits, dots, underscores, or hyphens"
        )
    return f"{RUNS_PREFIX}{run_id}"


def run_root(root: Path, run_id: str) -> Path:
    return fs_path(root, run_relative(run_id))


def safe_read(path: Path, label: str) -> bytes:
    try:
        return survey.safe_read_bytes(path, label)
    except survey.SurveyError as exc:
        raise StewardshipError(str(exc)) from exc


def safe_read_within(root: Path, path: Path, label: str) -> bytes:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise StewardshipError(f"{label} escapes the laboratory root: {path}") from exc
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise StewardshipError(f"cannot inspect {label} component: {current}") from exc
        if stat.S_ISLNK(info.st_mode):
            raise StewardshipError(f"symlink component in {label}: {current}")
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise StewardshipError(f"non-directory component in {label}: {current}")
        if index == len(relative.parts) - 1 and not stat.S_ISREG(info.st_mode):
            raise StewardshipError(f"{label} is not a regular file: {current}")
    return safe_read(path, label)


def read_object(path: Path, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(safe_read(path, label).decode("utf-8"))
    except StewardshipError:
        raise
    except Exception as exc:
        raise StewardshipError(f"cannot parse {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StewardshipError(f"{label} must contain a JSON object: {path}")
    return value


def atomic_create(path: Path, data: bytes, root: Path, mode: int = 0o644) -> None:
    try:
        survey.atomic_create(path, data, root, mode)
    except survey.SurveyError as exc:
        raise StewardshipError(str(exc)) from exc


def atomic_replace(
    path: Path,
    data: bytes,
    root: Path,
    mode: int = 0o644,
    *,
    expected_before: Optional[bytes] = None,
) -> None:
    try:
        survey.atomic_replace(
            path, data, root, mode, expected_before=expected_before
        )
    except survey.SurveyError as exc:
        raise StewardshipError(str(exc)) from exc


def snapshot(root: Path) -> Dict[str, Any]:
    try:
        value = survey.build_snapshot(root)
        known = {item["path"] for item in value.get("files", [])}
        for relative in sorted(SUPPLEMENTAL_TRANSACTION_PATHS):
            path = fs_path(root, relative)
            info = lstat_optional(path)
            if info is None:
                continue
            if relative in known:
                continue
            data = safe_read_within(
                root, path, f"supplemental transaction path {relative}"
            )
            value["files"].append(
                {"path": relative, "size": len(data), "sha256": sha256_bytes(data)}
            )
        value["files"].sort(key=lambda item: item["path"])
        basis = {"files": value["files"], "skipped": value.get("skipped", [])}
        value["inventory_sha256"] = sha256_bytes(canonical_json(basis))
        return value
    except survey.SurveyError as exc:
        raise StewardshipError(str(exc)) from exc


def inventory_map(value: Mapping[str, Any]) -> Dict[str, str]:
    return {
        item["path"]: item["sha256"]
        for item in value.get("files", [])
        if isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and isinstance(item.get("sha256"), str)
    }


def ensure_allowed_target(relative: str) -> None:
    if relative in DERIVED_BLOCKED or relative.startswith(RUNS_PREFIX):
        raise StewardshipError(f"derived or transaction state is not stageable: {relative}")
    if relative in ALLOWED_EXACT or any(
        relative.startswith(prefix) for prefix in ALLOWED_PREFIXES
    ):
        return
    raise StewardshipError(f"target is outside the live-state repair boundary: {relative}")


def append_only_update(relative: str) -> bool:
    parts = set(PurePosixPath(relative).parts)
    return any(relative.startswith(prefix) for prefix in APPEND_ONLY_PREFIXES) or bool(
        parts & APPEND_ONLY_PARTS
    )


def lstat_optional(path: Path) -> Optional[os.stat_result]:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def require_regular_project_path(root: Path, raw: Any, label: str) -> str:
    relative = canonical_relative(raw, label)
    path = fs_path(root, relative)
    try:
        resolved = path.resolve(strict=True)
        root_resolved = root.resolve(strict=True)
        resolved.relative_to(root_resolved)
    except (OSError, RuntimeError, ValueError) as exc:
        raise StewardshipError(f"{label} is missing, unsafe, or outside the lab: {relative}") from exc
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        try:
            component = current.lstat()
        except OSError as exc:
            raise StewardshipError(f"cannot inspect {label} component: {relative}") from exc
        if stat.S_ISLNK(component.st_mode):
            raise StewardshipError(f"{label} may not use symlinked components: {relative}")
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise StewardshipError(f"{label} is not a regular file: {relative}")
    return relative


def structured_value(data: bytes, *, strict_status_format: bool = False) -> Optional[Any]:
    stripped = data.lstrip()
    if not stripped or stripped[:1] not in {b"{", b"["}:
        if strict_status_format and stripped:
            raise StewardshipError(
                "structured .json/.yaml/.yml artifacts must use the laboratory's JSON-compatible form"
            )
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise StewardshipError(f"cannot parse structured staged artifact: {exc}") from exc


def status_values(data: bytes, *, strict_status_format: bool = False) -> Dict[str, str]:
    value = structured_value(data, strict_status_format=strict_status_format)
    if value is None:
        return {}
    result: Dict[str, str] = {}

    def walk(item: Any, prefix: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                path = f"{prefix}.{key}" if prefix else str(key)
                lowered = str(key).casefold()
                if isinstance(child, str) and ("status" in lowered or "verdict" in lowered):
                    result[path] = child
                walk(child, path)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{prefix}[{index}]")

    walk(value, "")
    return result


def status_claim_bindings(
    data: bytes, *, strict_status_format: bool = False
) -> Dict[str, set[str]]:
    value = structured_value(data, strict_status_format=strict_status_format)
    result: Dict[str, set[str]] = {}
    if value is None:
        return result

    def walk(item: Any, prefix: str, inherited: set[str]) -> None:
        if isinstance(item, dict):
            claim_specific = {
                candidate
                for key in ("claim_id", "result_id", "target_id", "id")
                for candidate in (item.get(key),)
                if isinstance(candidate, str) and candidate
            }
            problem_id = item.get("problem_id")
            local = claim_specific or (
                {problem_id} if isinstance(problem_id, str) and problem_id else set()
            )
            effective = local or inherited
            for key, child in item.items():
                path = f"{prefix}.{key}" if prefix else str(key)
                lowered = str(key).casefold()
                if isinstance(child, str) and ("status" in lowered or "verdict" in lowered):
                    result[path] = set(effective)
                walk(child, path, effective)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{prefix}[{index}]", inherited)

    walk(value, "", set())
    return result


def stable_object_ids(
    data: bytes, *, strict_status_format: bool = False
) -> set[Tuple[str, str]]:
    value = structured_value(data, strict_status_format=strict_status_format)
    result: set[Tuple[str, str]] = set()
    if value is None:
        return result

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for key in ("claim_id", "result_id", "problem_id", "target_id", "id"):
                candidate = item.get(key)
                if isinstance(candidate, str) and candidate:
                    result.add((key, candidate))
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return result


def changed_status_pairs(
    before: Optional[bytes], after: bytes, *, strict_status_format: bool = False
) -> List[Tuple[str, Optional[str], Optional[str]]]:
    old = status_values(before or b"{}", strict_status_format=strict_status_format)
    new = status_values(after, strict_status_format=strict_status_format)
    pairs: List[Tuple[str, Optional[str], Optional[str]]] = []
    for key in sorted(set(old) | set(new)):
        if old.get(key) != new.get(key):
            pairs.append((key, old.get(key), new.get(key)))
    return pairs


def strong_status(value: str) -> bool:
    return value.strip().upper() in STRONG_STATUSES


def validate_status_transition(
    root: Path,
    transition: Any,
    pairs: Sequence[Tuple[str, Optional[str], Optional[str]]],
    planned_paths: set[str],
) -> Dict[str, Any]:
    if not isinstance(transition, dict):
        raise StewardshipError("a detected status change requires status_transition")
    kind = transition.get("kind")
    if kind not in {
        "CONSERVATIVE_RECONCILIATION",
        "EXISTING_DOSSIER_STATUS",
        "EXISTING_VERDICT",
    }:
        raise StewardshipError("status_transition.kind is invalid")
    for key in (
        "status_field",
        "claim_id",
        "from_status",
        "to_status",
        "exact_scope_artifact",
        "exact_scope_sha256",
    ):
        if not isinstance(transition.get(key), str) or not transition[key]:
            raise StewardshipError(f"status_transition.{key} is required")
    if not SHA256.fullmatch(transition["exact_scope_sha256"]):
        raise StewardshipError("status_transition.exact_scope_sha256 is invalid")
    declared_old = None if transition["from_status"] == "ABSENT" else transition["from_status"]
    declared = (transition["status_field"], declared_old, transition["to_status"])
    if declared not in pairs:
        raise StewardshipError("declared status transition does not match staged bytes")
    exact_scope = require_regular_project_path(
        root, transition["exact_scope_artifact"], "status exact-scope artifact"
    )
    if exact_scope in planned_paths:
        raise StewardshipError("status exact scope must pre-exist and remain immutable")
    if sha256_bytes(
        safe_read_within(root, fs_path(root, exact_scope), "status exact-scope artifact")
    ) != transition["exact_scope_sha256"]:
        raise StewardshipError("status exact-scope artifact digest mismatch")

    if kind == "CONSERVATIVE_RECONCILIATION":
        if transition["to_status"].strip().upper() not in CONSERVATIVE_STATUS_DESTINATIONS:
            raise StewardshipError(
                "destination is not in the explicit non-decisive reconciliation vocabulary"
            )
        history = require_regular_project_path(
            root, transition.get("history_artifact"), "status history artifact"
        )
        if history in planned_paths:
            raise StewardshipError("status history must pre-exist and remain immutable")
        return transition

    if kind == "EXISTING_DOSSIER_STATUS":
        if not isinstance(transition.get("problem_id"), str) or not transition["problem_id"]:
            raise StewardshipError(
                "dossier-status transition.problem_id is required"
            )
        if transition["to_status"] not in AUTHORITATIVE_DOSSIER_STATUSES:
            raise StewardshipError(
                "dossier-status synchronization supports only authoritative terminal statuses"
            )
        return transition

    for key in ("problem_id", "target_id"):
        if not isinstance(transition.get(key), str) or not transition[key]:
            raise StewardshipError(f"protected status_transition.{key} is required")
    if transition.get("gate") != "PROOF_I3":
        raise StewardshipError("v1 protected promotion supports only the complete PROOF_I3 gate")
    if transition.get("independence_level") != "I3" or transition.get("verdict") != "PASS":
        raise StewardshipError("protected promotion requires a decisive I3 PASS")
    if transition["to_status"].strip().upper() not in PROOF_I3_ALLOWED_DESTINATIONS:
        raise StewardshipError(
            "PROOF_I3 can authorize only proof-established destinations in v1"
        )
    return transition


def validate_protected_evidence(
    root: Path, value: Any, planned_paths: set[str]
) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise StewardshipError("RECORD_EXISTING_VERDICT requires protected_evidence")
    for key in ("claim_id", "problem_id", "target_id", "exact_scope_sha256"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise StewardshipError(f"protected_evidence.{key} is required")
    if not SHA256.fullmatch(value["exact_scope_sha256"]):
        raise StewardshipError("protected_evidence.exact_scope_sha256 is invalid")
    if value.get("gate") != "PROOF_I3":
        raise StewardshipError("v1 protected evidence supports only PROOF_I3")
    if value.get("independence_level") != "I3" or value.get("verdict") != "PASS":
        raise StewardshipError("protected evidence requires a decisive I3 PASS")
    bindings = (
        ("exact_scope_artifact", "exact_scope_sha256"),
        ("proof_search_state", "proof_search_state_sha256"),
        ("closure_manifest", "closure_manifest_sha256"),
        ("verifier_report", "verifier_report_sha256"),
    )
    resolved: Dict[str, str] = {}
    for key, digest_key in bindings:
        relative = require_regular_project_path(root, value.get(key), f"protected {key}")
        if relative in planned_paths:
            raise StewardshipError(f"protected evidence must pre-exist and remain immutable: {relative}")
        declared = value.get(digest_key)
        if not isinstance(declared, str) or not SHA256.fullmatch(declared):
            raise StewardshipError(f"protected_evidence.{digest_key} is invalid")
        if sha256_bytes(
            safe_read_within(root, fs_path(root, relative), f"protected {key}")
        ) != declared:
            raise StewardshipError(f"protected evidence digest mismatch: {relative}")
        resolved[key] = relative

    state = read_object(fs_path(root, resolved["proof_search_state"]), "protected proof-search state")
    target = state.get("target_binding")
    verifier = state.get("independent_verifier")
    closure = state.get("closure_evidence")
    if state.get("global_status") != "VERIFIED_PROOF":
        raise StewardshipError("protected proof-search state is not VERIFIED_PROOF")
    if (
        value["claim_id"] != value["target_id"]
        or state.get("problem_id") != value["problem_id"]
    ):
        raise StewardshipError("protected claim, problem, and target identities disagree")
    if not isinstance(target, dict) or (
        target.get("target_id") != value["target_id"]
        or target.get("artifact") != resolved["exact_scope_artifact"]
        or target.get("artifact_sha256") != value["exact_scope_sha256"]
    ):
        raise StewardshipError("protected exact scope disagrees with proof-search target binding")
    if not isinstance(verifier, dict) or (
        verifier.get("independence_level") != "I3"
        or verifier.get("verdict") != "PASS"
        or verifier.get("completed") is not True
        or verifier.get("report") != resolved["verifier_report"]
        or verifier.get("report_sha256") != value["verifier_report_sha256"]
    ):
        raise StewardshipError("protected verifier binding is not a completed decisive I3 PASS")
    if not isinstance(closure, dict) or (
        closure.get("closure_manifest") != resolved["closure_manifest"]
        or closure.get("closure_manifest_sha256") != value["closure_manifest_sha256"]
    ):
        raise StewardshipError("protected closure binding disagrees with proof-search state")
    closure_manifest = read_object(
        fs_path(root, resolved["closure_manifest"]), "protected closure manifest"
    )
    if (
        closure_manifest.get("problem_id") != value["problem_id"]
        or closure_manifest.get("target_id") != value["target_id"]
        or closure_manifest.get("global_status") != "VERIFIED_PROOF"
    ):
        raise StewardshipError("protected closure manifest has a cross-claim identity mismatch")
    return value


def validate_index_status_evidence(
    root: Path, value: Any, planned_paths: set[str]
) -> List[Dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise StewardshipError(
            "SYNCHRONIZE_EXISTING_DOSSIER_STATUS requires index_status_evidence"
        )
    result: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()
    for index, item in enumerate(value):
        label = f"index_status_evidence[{index}]"
        if not isinstance(item, dict):
            raise StewardshipError(f"{label} must be an object")
        for key in (
            "status_field",
            "claim_id",
            "problem_id",
            "authoritative_status",
            "proof_search_state",
            "proof_search_state_sha256",
            "target_id",
            "candidate_id",
            "candidate_artifact_sha256",
            "verifier_id",
            "verifier_report_sha256",
            "closure_manifest_sha256",
        ):
            if not isinstance(item.get(key), str) or not item[key]:
                raise StewardshipError(f"{label}.{key} is required")
        for key in (
            "proof_search_state_sha256",
            "candidate_artifact_sha256",
            "verifier_report_sha256",
            "closure_manifest_sha256",
        ):
            if not SHA256.fullmatch(item[key]):
                raise StewardshipError(f"{label}.{key} is invalid")
        identity = (item["status_field"], item["claim_id"])
        if identity in seen:
            raise StewardshipError(
                "index status evidence must bind each field/claim pair exactly once"
            )
        seen.add(identity)
        status = item["authoritative_status"]
        if status not in AUTHORITATIVE_DOSSIER_STATUSES:
            raise StewardshipError(
                f"{label}.authoritative_status is not a supported terminal status"
            )
        if item["claim_id"] != item["problem_id"]:
            raise StewardshipError(
                f"{label} claim_id must equal the canonical dossier problem_id"
            )
        relative = require_regular_project_path(
            root, item["proof_search_state"], f"{label} proof-search state"
        )
        parts = PurePosixPath(relative).parts
        if (
            len(parts) != 4
            or parts[0] != "problems"
            or parts[1] not in {"active", "backlog", "closed"}
            or parts[2] != item["problem_id"]
            or parts[3] != "proof_search_state.yaml"
        ):
            raise StewardshipError(
                f"{label} must bind an exact canonical dossier proof_search_state.yaml"
            )
        if relative in planned_paths:
            raise StewardshipError(
                "authoritative dossier proof-search state must pre-exist and remain immutable"
            )
        state_data = safe_read_within(
            root, fs_path(root, relative), f"{label} proof-search state"
        )
        if sha256_bytes(state_data) != item["proof_search_state_sha256"]:
            raise StewardshipError(
                f"{label} proof-search state digest mismatch"
            )
        try:
            state = json.loads(state_data.decode("utf-8"))
        except Exception as exc:
            raise StewardshipError(
                f"cannot parse {label} proof-search state: {exc}"
            ) from exc
        if not isinstance(state, dict):
            raise StewardshipError(f"{label} proof-search state must be an object")
        if (
            state.get("problem_id") != item["problem_id"]
            or state.get("global_status") != status
        ):
            raise StewardshipError(
                f"{label} problem/status binding disagrees with authoritative state"
            )
        target = state.get("target_binding")
        if not isinstance(target, dict) or target.get("target_id") != item["target_id"]:
            raise StewardshipError(
                f"{label} target binding disagrees with authoritative state"
            )
        if (
            state.get("candidate_proof_id") != item["candidate_id"]
            or state.get("candidate_artifact_sha256")
            != item["candidate_artifact_sha256"]
        ):
            raise StewardshipError(
                f"{label} candidate binding disagrees with authoritative state"
            )
        verifier = state.get("independent_verifier")
        if not isinstance(verifier, dict) or (
            verifier.get("id") != item["verifier_id"]
            or verifier.get("assigned") is not True
            or verifier.get("completed") is not True
            or verifier.get("independent_of_candidate") is not True
            or verifier.get("independence_level") != "I3"
            or verifier.get("verdict") not in {"PASS", "VERIFIED"}
            or verifier.get("report_sha256") != item["verifier_report_sha256"]
        ):
            raise StewardshipError(
                f"{label} does not bind a completed decisive I3 verifier"
            )
        closure = state.get("closure_evidence")
        if not isinstance(closure, dict) or (
            closure.get("closure_manifest_sha256")
            != item["closure_manifest_sha256"]
        ):
            raise StewardshipError(
                f"{label} closure-manifest binding disagrees with authoritative state"
            )
        route_id = state.get("candidate_route_id")
        routes = state.get("routes")
        route = next(
            (
                candidate
                for candidate in routes
                if isinstance(candidate, dict) and candidate.get("id") == route_id
            ),
            None,
        ) if isinstance(routes, list) else None
        if not isinstance(route, dict) or (
            route.get("status") != AUTHORITATIVE_DOSSIER_STATUSES[status]
            or route.get("verification_gate") != "I3_PASSED"
        ):
            raise StewardshipError(
                f"{label} terminal route disagrees with authoritative status"
            )
        result.append(dict(item, proof_search_state=relative))
    return result


def validate_index_status_bindings(
    transitions: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
) -> None:
    sync_transitions = [
        transition
        for transition in transitions
        if transition.get("kind") == "EXISTING_DOSSIER_STATUS"
    ]
    if len(sync_transitions) != len(evidence):
        raise StewardshipError(
            "each dossier-status transition requires one exact evidence binding"
        )
    evidence_by_identity = {
        (item["status_field"], item["claim_id"]): item for item in evidence
    }
    if len(evidence_by_identity) != len(evidence):
        raise StewardshipError(
            "index status evidence contains a duplicate field/claim binding"
        )
    for transition in sync_transitions:
        item = evidence_by_identity.get(
            (transition["status_field"], transition["claim_id"])
        )
        if item is None:
            raise StewardshipError(
                "dossier-status transition has no matching evidence binding"
            )
        expected = {
            "problem_id": transition["problem_id"],
            "authoritative_status": transition["to_status"],
            "proof_search_state": transition["exact_scope_artifact"],
            "proof_search_state_sha256": transition["exact_scope_sha256"],
        }
        for key, value in expected.items():
            if item.get(key) != value:
                raise StewardshipError(
                    f"dossier-status transition disagrees with evidence binding: {key}"
                )


def index_status_pairs(
    pairs: Sequence[Tuple[str, Optional[str], Optional[str]]],
) -> Tuple[List[Tuple[str, Optional[str], Optional[str]]], List[str]]:
    dossier_pairs: List[Tuple[str, Optional[str], Optional[str]]] = []
    aggregate_fields: List[str] = []
    for pair in pairs:
        field, old, new = pair
        if INDEX_DOSSIER_STATUS_FIELD.fullmatch(field):
            dossier_pairs.append(pair)
            continue
        if INDEX_TRACK_STATUS_FIELD.fullmatch(field) and old is not None and new is not None:
            if strong_status(old) or strong_status(new):
                raise StewardshipError(
                    "index synchronization may not promote an aggregate track to a strong status"
                )
            aggregate_fields.append(field)
            continue
        raise StewardshipError(
            "index synchronization may change only dossier global_status fields "
            "and existing track status projections"
        )
    return dossier_pairs, aggregate_fields


def format_hash_manifest(items: Iterable[Tuple[str, bytes]]) -> bytes:
    return "".join(
        f"{sha256_bytes(data)}  ./{relative}\n" for relative, data in sorted(items)
    ).encode("utf-8")


def format_added_paths(paths: Iterable[str]) -> bytes:
    return "".join(f"./{path}\n" for path in sorted(paths)).encode("utf-8")


def parse_hash_manifest(data: bytes, label: str) -> Dict[str, str]:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise StewardshipError(f"{label} is not UTF-8") from exc
    result: Dict[str, str] = {}
    for line in lines:
        if not line:
            continue
        pieces = line.split("  ./", 1)
        if len(pieces) != 2 or not SHA256.fullmatch(pieces[0]):
            raise StewardshipError(f"malformed hash line in {label}: {line!r}")
        relative = canonical_relative(pieces[1], label)
        if relative in result:
            raise StewardshipError(f"duplicate path in {label}: {relative}")
        result[relative] = pieces[0]
    return result


def parse_added_paths(data: bytes, label: str) -> set[str]:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise StewardshipError(f"{label} is not UTF-8") from exc
    result: set[str] = set()
    for line in lines:
        if not line:
            continue
        if not line.startswith("./"):
            raise StewardshipError(f"malformed added path in {label}: {line!r}")
        relative = canonical_relative(line[2:], label)
        if relative in result:
            raise StewardshipError(f"duplicate path in {label}: {relative}")
        result.add(relative)
    return result


def load_manifest(root: Path, run_id: str) -> Tuple[Path, Dict[str, Any]]:
    packet = run_root(root, run_id)
    info = lstat_optional(packet)
    if info is None or stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise StewardshipError(f"stewardship packet is absent or unsafe: {packet}")
    manifest = read_object(packet / "manifest.json", "stewardship manifest")
    if manifest.get("run_id") != run_id:
        raise StewardshipError("stewardship manifest run_id mismatch")
    return packet, manifest


def update_manifest(root: Path, packet: Path, manifest: Dict[str, Any], **values: Any) -> None:
    manifest.update(values)
    atomic_replace(packet / "manifest.json", json_bytes(manifest), root)


def start_run(root: Path, run_id: str, mode: str) -> Dict[str, Any]:
    root = require_lab_root(root)
    if mode not in MODES:
        raise StewardshipError(f"invalid stewardship mode: {mode}")
    relative = run_relative(run_id)
    before = snapshot(root)
    if before.get("coverage") != "COMPLETE_WITHIN_DECLARED_SCOPE":
        raise StewardshipError("stewardship requires complete declared-scope inventory coverage")
    packet = fs_path(root, relative)
    try:
        survey.atomic_mkdir(packet, root)
    except (OSError, survey.SurveyError) as exc:
        raise StewardshipError(f"cannot create stewardship packet {packet}: {exc}") from exc

    plan = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "literature_mode": "NOT_AUTHORIZED",
        "starting_inventory_sha256": before["inventory_sha256"],
        "changes": [],
        "deferred": [],
    }
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "status": "AUDIT_IN_PROGRESS",
        "started_at_utc": utc_now(),
        "updated_at_utc": utc_now(),
        "starting_inventory_sha256": before["inventory_sha256"],
        "frozen_plan_sha256": None,
        "finishing_inventory_sha256": None,
        "changed_paths": [],
        "validation": None,
        "completion_basis": None,
        "final_survey": None,
        "integrity_note": (
            "Transaction hashes protect declared bytes; they do not prove mathematics, "
            "source truth, novelty, value, or independence."
        ),
    }
    atomic_create(packet / "inventory_before.json", json_bytes(before), root)
    atomic_create(
        packet / "diagnosis.md",
        b"# Stewardship Diagnosis\n\nComplete the whole-laboratory audit before staging repairs.\n",
        root,
    )
    atomic_create(packet / "repair_plan.json", json_bytes(plan), root)
    atomic_create(packet / "manifest.json", json_bytes(manifest), root)
    return {
        "status": "AUDIT_IN_PROGRESS",
        "run_id": run_id,
        "packet": relative,
        "starting_inventory_sha256": before["inventory_sha256"],
        "next": "complete diagnosis.md, repair_plan.json, and staged/; then run prepare",
    }


def validate_deferred(root: Path, value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        raise StewardshipError("repair_plan.deferred must be an array")
    result: List[Dict[str, Any]] = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            raise StewardshipError("each deferred item must be an object")
        identifier = item.get("id")
        if not isinstance(identifier, str) or not ITEM_ID.fullmatch(identifier) or identifier in seen:
            raise StewardshipError(f"invalid or duplicate deferred id: {identifier!r}")
        seen.add(identifier)
        if item.get("repair_class") != "DEFER_USER_DECISION":
            raise StewardshipError(f"deferred item {identifier} has the wrong repair class")
        if not isinstance(item.get("reason"), str) or not item["reason"].strip():
            raise StewardshipError(f"deferred item {identifier} lacks a reason")
        if not isinstance(item.get("next_decision"), str) or not item["next_decision"].strip():
            raise StewardshipError(f"deferred item {identifier} lacks next_decision")
        evidence = item.get("evidence_paths", [])
        if not isinstance(evidence, list):
            raise StewardshipError(f"deferred item {identifier} evidence_paths must be an array")
        for raw in evidence:
            require_regular_project_path(root, raw, f"deferred {identifier} evidence")
        result.append(item)
    return result


def prepare_run(root: Path, run_id: str) -> Dict[str, Any]:
    root = require_lab_root(root)
    packet, manifest = load_manifest(root, run_id)
    if manifest.get("status") != "AUDIT_IN_PROGRESS":
        raise StewardshipError(f"prepare requires AUDIT_IN_PROGRESS, got {manifest.get('status')!r}")
    before = read_object(packet / "inventory_before.json", "starting inventory")
    current = snapshot(root)
    if current["inventory_sha256"] != before.get("inventory_sha256"):
        raise StewardshipError("laboratory state drifted during the read-only audit")
    diagnosis = safe_read_within(root, packet / "diagnosis.md", "stewardship diagnosis")
    if len(diagnosis.strip()) < 100 or b"Complete the whole-laboratory audit" in diagnosis:
        raise StewardshipError("diagnosis.md is still incomplete")

    plan = read_object(packet / "repair_plan.json", "repair plan")
    if plan.get("schema_version") != 1 or plan.get("run_id") != run_id:
        raise StewardshipError("repair plan identity or schema is invalid")
    if plan.get("mode") != manifest.get("mode") or plan.get("mode") not in MODES:
        raise StewardshipError("repair plan mode mismatch")
    if plan.get("literature_mode") not in LITERATURE_MODES:
        raise StewardshipError("repair plan literature_mode is invalid")
    if plan.get("starting_inventory_sha256") != before.get("inventory_sha256"):
        raise StewardshipError("repair plan starting inventory binding mismatch")
    changes = plan.get("changes")
    if not isinstance(changes, list):
        raise StewardshipError("repair_plan.changes must be an array")
    validate_deferred(root, plan.get("deferred", []))

    identifiers = set()
    planned_paths: set[str] = set()
    planned_casefold: set[str] = set()
    for item in changes:
        if not isinstance(item, dict):
            raise StewardshipError("each repair-plan change must be an object")
        identifier = item.get("id")
        if not isinstance(identifier, str) or not ITEM_ID.fullmatch(identifier) or identifier in identifiers:
            raise StewardshipError(f"invalid or duplicate repair id: {identifier!r}")
        identifiers.add(identifier)
        relative = canonical_relative(item.get("path"), f"repair {identifier} path")
        ensure_allowed_target(relative)
        if relative in planned_paths or relative.casefold() in planned_casefold:
            raise StewardshipError(f"duplicate planned target path: {relative}")
        planned_paths.add(relative)
        planned_casefold.add(relative.casefold())

    before_map = inventory_map(before)
    backups: List[Tuple[str, bytes]] = []
    additions: List[str] = []
    normalized: List[Dict[str, Any]] = []
    protected_change_count = 0
    for item in changes:
        identifier = item["id"]
        normalized_item = dict(item)
        relative = canonical_relative(item.get("path"), f"repair {identifier} path")
        action = item.get("action")
        if action not in {"ADD", "UPDATE"}:
            raise StewardshipError(f"repair {identifier} action must be ADD or UPDATE")
        repair_class = item.get("repair_class")
        if repair_class not in REPAIR_CLASSES:
            raise StewardshipError(f"repair {identifier} has invalid repair_class")
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise StewardshipError(f"repair {identifier} lacks a reason")
        effect = item.get("mathematical_effect")
        if effect not in MATHEMATICAL_EFFECTS:
            raise StewardshipError(f"repair {identifier} has invalid mathematical_effect")
        if effect == "RECORD_EXISTING_VERDICT" and repair_class != "PROTECTED_STATUS_TRANSITION":
            raise StewardshipError(f"repair {identifier} protected effect/class mismatch")
        protected_evidence = None
        index_status_evidence: List[Dict[str, Any]] = []
        if effect == "RECORD_EXISTING_VERDICT":
            protected_evidence = validate_protected_evidence(
                root, item.get("protected_evidence"), planned_paths
            )
            if item.get("claim_id") != protected_evidence["claim_id"]:
                raise StewardshipError(
                    f"repair {identifier} claim_id does not bind the protected target"
                )
            protected_change_count += 1
        elif effect == "SYNCHRONIZE_EXISTING_DOSSIER_STATUS":
            if repair_class != "EVIDENCE_RECONCILIATION":
                raise StewardshipError(
                    f"repair {identifier} index synchronization effect/class mismatch"
                )
            if relative not in INDEX_STATUS_PROJECTION_TARGETS:
                raise StewardshipError(
                    f"repair {identifier} index synchronization target is not canonical"
                )
            if action != "UPDATE":
                raise StewardshipError(
                    f"repair {identifier} may synchronize only an existing index projection"
                )
            index_status_evidence = validate_index_status_evidence(
                root, item.get("index_status_evidence"), planned_paths
            )
            if item.get("claim_id") is not None:
                raise StewardshipError(
                    f"repair {identifier} multi-dossier synchronization may not use one top-level claim_id"
                )
            protected_change_count += 1
        elif item.get("claim_id") is not None:
            raise StewardshipError(f"repair {identifier} has claim_id without a protected effect")
        elif item.get("protected_evidence") is not None:
            raise StewardshipError(f"repair {identifier} has protected evidence without a protected effect")
        elif item.get("index_status_evidence") is not None:
            raise StewardshipError(
                f"repair {identifier} has index status evidence without its guarded effect"
            )
        if (
            effect == "SYNCHRONIZE_EXISTING_DOSSIER_STATUS"
            and item.get("protected_evidence") is not None
        ):
            raise StewardshipError(
                f"repair {identifier} index synchronization may not use protected_evidence"
            )
        if (
            effect != "SYNCHRONIZE_EXISTING_DOSSIER_STATUS"
            and item.get("index_status_evidence") is not None
        ):
            raise StewardshipError(
                f"repair {identifier} has index status evidence without its guarded effect"
            )
        if repair_class == "NEW_UNVERIFIED_RESEARCH" and effect != "NEW_UNVERIFIED_RESEARCH":
            raise StewardshipError(f"repair {identifier} new research must remain explicitly unverified")

        evidence = item.get("evidence_paths", [])
        if not isinstance(evidence, list):
            raise StewardshipError(f"repair {identifier} evidence_paths must be an array")
        for raw in evidence:
            relative_evidence = canonical_relative(raw, f"repair {identifier} evidence")
            if relative_evidence not in planned_paths:
                require_regular_project_path(root, relative_evidence, f"repair {identifier} evidence")

        staged = packet / "staged" / Path(*PurePosixPath(relative).parts)
        staged_data = safe_read_within(
            root, staged, f"repair {identifier} staged after-image"
        )
        declared_after = item.get("after_sha256")
        if not isinstance(declared_after, str) or declared_after != sha256_bytes(staged_data):
            raise StewardshipError(f"repair {identifier} staged after-image hash mismatch")

        target = fs_path(root, relative)
        info = lstat_optional(target)
        before_data: Optional[bytes]
        if action == "ADD":
            if info is not None:
                raise StewardshipError(f"repair {identifier} ADD target already exists: {relative}")
            if item.get("before_sha256") is not None:
                raise StewardshipError(f"repair {identifier} ADD before_sha256 must be null")
            before_data = None
            if item.get("before_mode") is not None:
                raise StewardshipError(f"repair {identifier} ADD before_mode must be null")
            after_mode = item.get("after_mode", 0o644)
            if after_mode != 0o644:
                raise StewardshipError(f"repair {identifier} ADD mode must be 0644 in v1")
            normalized_item["before_mode"] = None
            normalized_item["after_mode"] = after_mode
            additions.append(relative)
        else:
            if append_only_update(relative):
                raise StewardshipError(f"repair {identifier} may not rewrite append-only evidence: {relative}")
            before_data = safe_read_within(
                root, target, f"repair {identifier} target preimage"
            )
            declared_before = item.get("before_sha256")
            actual_before = sha256_bytes(before_data)
            if not isinstance(declared_before, str) or declared_before != actual_before:
                raise StewardshipError(f"repair {identifier} target preimage hash mismatch")
            if before_map.get(relative) != actual_before:
                raise StewardshipError(f"repair {identifier} target was outside or changed from starting inventory")
            assert info is not None
            before_mode = stat.S_IMODE(info.st_mode)
            if item.get("before_mode") not in {None, before_mode}:
                raise StewardshipError(f"repair {identifier} target preimage mode mismatch")
            if item.get("after_mode") not in {None, before_mode}:
                raise StewardshipError(f"repair {identifier} may not change file mode in v1")
            normalized_item["before_mode"] = before_mode
            normalized_item["after_mode"] = before_mode
            backups.append((relative, before_data))

        structured_target = PurePosixPath(relative).suffix.lower() in {".json", ".yaml", ".yml"}
        removed_ids = stable_object_ids(
            before_data or b"{}", strict_status_format=structured_target
        ) - stable_object_ids(staged_data, strict_status_format=structured_target)
        if removed_ids:
            raise StewardshipError(
                f"repair {identifier} removes stable structured identities: {sorted(removed_ids)!r}"
            )
        pairs = changed_status_pairs(
            before_data, staged_data, strict_status_format=structured_target
        )
        removed_statuses = [field for field, _, new in pairs if new is None]
        if removed_statuses:
            raise StewardshipError(
                f"repair {identifier} removes status fields: {removed_statuses!r}"
            )
        if before_data is not None:
            before_bindings = status_claim_bindings(
                before_data, strict_status_format=structured_target
            )
            after_bindings = status_claim_bindings(
                staged_data, strict_status_format=structured_target
            )
            bindings_match = before_bindings == after_bindings
            if effect == "SYNCHRONIZE_EXISTING_DOSSIER_STATUS":
                bindings_match = all(
                    after_bindings.get(field) == owners
                    for field, owners in before_bindings.items()
                )
            if not bindings_match:
                raise StewardshipError(
                    f"repair {identifier} relocates a status field between stable owners"
                )
        if effect == "SYNCHRONIZE_EXISTING_DOSSIER_STATUS":
            required_pairs, aggregate_status_fields = index_status_pairs(pairs)
        else:
            aggregate_status_fields = []
            required_pairs = [
                pair
                for pair in pairs
                if pair[1] is not None
                or (
                    isinstance(pair[2], str)
                    and pair[2].strip().upper()
                    not in CONSERVATIVE_STATUS_DESTINATIONS
                )
            ]
        transitions = item.get("status_transitions", [])
        if not isinstance(transitions, list):
            raise StewardshipError(f"repair {identifier} status_transitions must be an array")
        validated_transitions = [
            validate_status_transition(root, transition, pairs, planned_paths)
            for transition in transitions
        ]
        claim_bindings = status_claim_bindings(
            staged_data, strict_status_format=structured_target
        )
        for transition in validated_transitions:
            owners = claim_bindings.get(transition["status_field"], set())
            if len(owners) > 1 or (owners and transition["claim_id"] not in owners) or (
                transition["kind"]
                in {"EXISTING_VERDICT", "EXISTING_DOSSIER_STATUS"}
                and not owners
            ):
                raise StewardshipError(
                    f"repair {identifier} status field is not owned by declared claim_id"
                )
        declared_fields = [transition["status_field"] for transition in validated_transitions]
        required_fields = [field for field, _, _ in required_pairs]
        if sorted(declared_fields) != sorted(required_fields):
            raise StewardshipError(
                f"repair {identifier} must bind every changed existing or strong status field exactly once"
            )
        kinds = {transition["kind"] for transition in validated_transitions}
        if "EXISTING_VERDICT" in kinds and (
            effect != "RECORD_EXISTING_VERDICT"
            or repair_class != "PROTECTED_STATUS_TRANSITION"
        ):
            raise StewardshipError(f"repair {identifier} strong transition effect/class mismatch")
        if "EXISTING_DOSSIER_STATUS" in kinds and (
            effect != "SYNCHRONIZE_EXISTING_DOSSIER_STATUS"
            or repair_class != "EVIDENCE_RECONCILIATION"
            or kinds != {"EXISTING_DOSSIER_STATUS"}
        ):
            raise StewardshipError(
                f"repair {identifier} dossier-status transition effect/class mismatch"
            )
        if effect == "SYNCHRONIZE_EXISTING_DOSSIER_STATUS":
            if kinds != {"EXISTING_DOSSIER_STATUS"}:
                raise StewardshipError(
                    f"repair {identifier} index synchronization requires only dossier-status transitions"
                )
            validate_index_status_bindings(
                validated_transitions, index_status_evidence
            )
            if not required_pairs:
                raise StewardshipError(
                    f"repair {identifier} index synchronization has no dossier status"
                )
            if aggregate_status_fields and not index_status_evidence:
                raise StewardshipError(
                    f"repair {identifier} aggregate status has no dossier evidence"
                )
        if kinds == {"CONSERVATIVE_RECONCILIATION"} and repair_class != "EVIDENCE_RECONCILIATION":
            raise StewardshipError(f"repair {identifier} conservative transition class mismatch")
        if protected_evidence is not None:
            for transition in validated_transitions:
                if transition["kind"] != "EXISTING_VERDICT":
                    continue
                for key in (
                    "claim_id",
                    "problem_id",
                    "target_id",
                    "exact_scope_artifact",
                    "exact_scope_sha256",
                    "gate",
                    "independence_level",
                    "verdict",
                ):
                    if transition.get(key) != protected_evidence.get(key):
                        raise StewardshipError(
                            f"repair {identifier} status transition disagrees with protected evidence: {key}"
                        )
        if relative.casefold().startswith("results/verified/"):
            raise StewardshipError(
                f"repair {identifier} cannot create or rewrite verified-result artifacts in v1"
            )
        normalized.append(normalized_item)

    protected_preflight_digest = None
    if protected_change_count:
        command = [sys.executable, "scripts/validate_proof_search.py"]
        try:
            process = subprocess.run(
                command,
                cwd=str(root),
                text=True,
                capture_output=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired as exc:
            raise StewardshipError("protected proof-search preflight timed out") from exc
        preflight = {
            "schema_version": 1,
            "command": command,
            "completed_at_utc": utc_now(),
            "returncode": process.returncode,
            "stdout": process.stdout,
            "stderr": process.stderr,
            "status": "PASS" if process.returncode == 0 else "FAIL",
        }
        if process.returncode != 0:
            raise StewardshipError("protected proof-search preflight failed")
        preflight_data = json_bytes(preflight)
        protected_preflight_digest = sha256_bytes(preflight_data)
        atomic_create(
            packet / "protected_preflight.json", preflight_data, root, mode=0o444
        )

    frozen = dict(plan)
    frozen["changes"] = normalized
    frozen_data = json_bytes(frozen)
    frozen_digest = sha256_bytes(frozen_data)
    atomic_create(packet / "frozen_plan.json", frozen_data, root, mode=0o444)
    for relative, data in backups:
        destination = packet / "before" / Path(*PurePosixPath(relative).parts)
        atomic_create(destination, data, root, mode=0o444)
    before_manifest_data = format_hash_manifest(backups)
    added_paths_data = format_added_paths(additions)
    atomic_create(packet / "before.sha256", before_manifest_data, root, mode=0o444)
    atomic_create(packet / "added_paths.txt", added_paths_data, root, mode=0o444)
    planned_after = []
    for item in normalized:
        relative = item["path"]
        data = safe_read_within(
            root,
            packet / "staged" / Path(*PurePosixPath(relative).parts),
            "frozen staged after-image",
        )
        planned_after.append((relative, data))
    planned_after_data = format_hash_manifest(planned_after)
    atomic_create(
        packet / "planned_after.sha256", planned_after_data, root, mode=0o444
    )
    attestation = {
        "schema_version": 1,
        "run_id": run_id,
        "prepared_at_utc": utc_now(),
        "starting_inventory_sha256": before["inventory_sha256"],
        "frozen_plan_sha256": frozen_digest,
        "before_manifest_sha256": sha256_bytes(before_manifest_data),
        "added_paths_sha256": sha256_bytes(added_paths_data),
        "planned_after_sha256": sha256_bytes(planned_after_data),
        "protected_preflight_sha256": protected_preflight_digest,
        "integrity_note": (
            "This seal detects accidental or concurrent packet drift; apply still "
            "revalidates every semantic and path-safety rule."
        ),
    }
    attestation_data = json_bytes(attestation)
    attestation_digest = sha256_bytes(attestation_data)
    atomic_create(
        packet / "prepared_attestation.json", attestation_data, root, mode=0o444
    )
    update_manifest(
        root,
        packet,
        manifest,
        status="PREPARED",
        updated_at_utc=utc_now(),
        frozen_plan_sha256=frozen_digest,
        prepared_attestation_sha256=attestation_digest,
        planned_change_count=len(normalized),
        deferred_count=len(frozen.get("deferred", [])),
    )
    return {
        "status": "PREPARED",
        "run_id": run_id,
        "frozen_plan_sha256": frozen_digest,
        "prepared_attestation_sha256": attestation_digest,
        "updates": len(backups),
        "additions": len(additions),
        "deferred": len(frozen.get("deferred", [])),
        "next": "run apply without manually editing live or staged paths",
    }


def load_frozen_plan(packet: Path, manifest: Mapping[str, Any]) -> Dict[str, Any]:
    root = packet.parents[2]
    data = safe_read_within(root, packet / "frozen_plan.json", "frozen repair plan")
    attestation_data = safe_read_within(
        root, packet / "prepared_attestation.json", "prepared attestation"
    )
    if sha256_bytes(attestation_data) != manifest.get("prepared_attestation_sha256"):
        raise StewardshipError("prepared attestation digest mismatch")
    try:
        attestation = json.loads(attestation_data.decode("utf-8"))
    except Exception as exc:
        raise StewardshipError(f"cannot parse prepared attestation: {exc}") from exc
    if not isinstance(attestation, dict) or attestation.get("run_id") != manifest.get("run_id"):
        raise StewardshipError("prepared attestation identity mismatch")
    bindings = {
        "frozen_plan_sha256": data,
        "before_manifest_sha256": safe_read_within(
            root, packet / "before.sha256", "before manifest"
        ),
        "added_paths_sha256": safe_read_within(
            root, packet / "added_paths.txt", "added-path manifest"
        ),
        "planned_after_sha256": safe_read_within(
            root, packet / "planned_after.sha256", "planned-after manifest"
        ),
    }
    for key, bound_data in bindings.items():
        if attestation.get(key) != sha256_bytes(bound_data):
            raise StewardshipError(f"prepared attestation binding mismatch: {key}")
    protected_digest = attestation.get("protected_preflight_sha256")
    if protected_digest is not None:
        preflight = safe_read_within(
            root, packet / "protected_preflight.json", "protected preflight"
        )
        if protected_digest != sha256_bytes(preflight):
            raise StewardshipError("prepared protected-preflight binding mismatch")
    if sha256_bytes(data) != manifest.get("frozen_plan_sha256"):
        raise StewardshipError("frozen repair plan digest mismatch")
    try:
        value = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise StewardshipError(f"cannot parse frozen repair plan: {exc}") from exc
    if not isinstance(value, dict):
        raise StewardshipError("frozen repair plan must contain an object")
    return value


def append_journal(root: Path, packet: Path, value: Dict[str, Any]) -> None:
    path = packet / "apply_journal.jsonl"
    try:
        survey.append_bytes(path, canonical_json(value) + b"\n", root)
    except survey.SurveyError as exc:
        raise StewardshipError(str(exc)) from exc


def create_or_verify(
    root: Path, path: Path, data: bytes, label: str, mode: int = 0o644
) -> None:
    try:
        atomic_create(path, data, root, mode=mode)
        return
    except StewardshipError:
        info = lstat_optional(path)
        if info is None:
            raise
    existing = safe_read_within(root, path, label)
    if existing != data:
        raise StewardshipError(f"existing {label} disagrees with the recoverable transaction")


def validate_frozen_preimages(
    root: Path,
    packet: Path,
    plan: Mapping[str, Any],
    *,
    allow_applied: bool = False,
) -> Dict[str, str]:
    before_inventory = read_object(packet / "inventory_before.json", "starting inventory")
    if (
        plan.get("schema_version") != 1
        or plan.get("run_id") != packet.name
        or plan.get("mode") not in MODES
        or plan.get("literature_mode") not in LITERATURE_MODES
        or plan.get("starting_inventory_sha256") != before_inventory.get("inventory_sha256")
    ):
        raise StewardshipError("frozen repair plan identity, mode, or inventory binding is invalid")
    changes = plan.get("changes")
    if not isinstance(changes, list):
        raise StewardshipError("frozen repair-plan changes must be an array")
    validate_deferred(root, plan.get("deferred", []))
    identifiers = set()
    planned_paths: set[str] = set()
    planned_casefold: set[str] = set()
    for item in changes:
        if not isinstance(item, dict):
            raise StewardshipError("frozen repair change must be an object")
        identifier = item.get("id")
        if (
            not isinstance(identifier, str)
            or not ITEM_ID.fullmatch(identifier)
            or identifier in identifiers
        ):
            raise StewardshipError(f"invalid or duplicate frozen repair id: {identifier!r}")
        identifiers.add(identifier)
        relative = canonical_relative(item.get("path"), f"frozen repair {identifier} path")
        ensure_allowed_target(relative)
        if relative in planned_paths or relative.casefold() in planned_casefold:
            raise StewardshipError(f"duplicate frozen target path: {relative}")
        planned_paths.add(relative)
        planned_casefold.add(relative.casefold())

    expected_before: Dict[str, str] = {}
    expected_added: set[str] = set()
    expected_after: Dict[str, str] = {}
    target_states: Dict[str, str] = {}
    protected_change_count = 0
    for item in changes:
        identifier = item["id"]
        relative = canonical_relative(item.get("path"), f"frozen repair {identifier} path")
        action = item.get("action")
        repair_class = item.get("repair_class")
        effect = item.get("mathematical_effect")
        if action not in {"ADD", "UPDATE"}:
            raise StewardshipError(f"frozen repair {identifier} action is invalid")
        if repair_class not in REPAIR_CLASSES or effect not in MATHEMATICAL_EFFECTS:
            raise StewardshipError(f"frozen repair {identifier} class or effect is invalid")
        if not isinstance(item.get("reason"), str) or not item["reason"].strip():
            raise StewardshipError(f"frozen repair {identifier} lacks a reason")
        evidence = item.get("evidence_paths", [])
        if not isinstance(evidence, list):
            raise StewardshipError(f"frozen repair {identifier} evidence_paths is invalid")
        for raw in evidence:
            evidence_relative = canonical_relative(raw, f"frozen repair {identifier} evidence")
            if evidence_relative not in planned_paths:
                require_regular_project_path(
                    root, evidence_relative, f"frozen repair {identifier} evidence"
                )
        if effect == "RECORD_EXISTING_VERDICT" and repair_class != "PROTECTED_STATUS_TRANSITION":
            raise StewardshipError(f"frozen repair {identifier} protected effect/class mismatch")
        if repair_class == "NEW_UNVERIFIED_RESEARCH" and effect != "NEW_UNVERIFIED_RESEARCH":
            raise StewardshipError(f"frozen repair {identifier} new research is not unverified")
        protected_evidence = None
        index_status_evidence: List[Dict[str, Any]] = []
        if effect == "RECORD_EXISTING_VERDICT":
            protected_evidence = validate_protected_evidence(
                root, item.get("protected_evidence"), planned_paths
            )
            if item.get("claim_id") != protected_evidence["claim_id"]:
                raise StewardshipError(
                    f"frozen repair {identifier} claim_id does not bind the protected target"
                )
            protected_change_count += 1
        elif effect == "SYNCHRONIZE_EXISTING_DOSSIER_STATUS":
            if repair_class != "EVIDENCE_RECONCILIATION":
                raise StewardshipError(
                    f"frozen repair {identifier} index synchronization effect/class mismatch"
                )
            if relative not in INDEX_STATUS_PROJECTION_TARGETS:
                raise StewardshipError(
                    f"frozen repair {identifier} index synchronization target is not canonical"
                )
            if action != "UPDATE":
                raise StewardshipError(
                    f"frozen repair {identifier} does not update an existing index projection"
                )
            index_status_evidence = validate_index_status_evidence(
                root, item.get("index_status_evidence"), planned_paths
            )
            if item.get("claim_id") is not None:
                raise StewardshipError(
                    f"frozen repair {identifier} multi-dossier synchronization has one top-level claim_id"
                )
            protected_change_count += 1
        elif item.get("claim_id") is not None:
            raise StewardshipError(
                f"frozen repair {identifier} has claim_id without a protected effect"
            )
        elif item.get("protected_evidence") is not None:
            raise StewardshipError(f"frozen repair {identifier} has extraneous protected evidence")
        elif item.get("index_status_evidence") is not None:
            raise StewardshipError(
                f"frozen repair {identifier} has extraneous index status evidence"
            )
        if (
            effect == "SYNCHRONIZE_EXISTING_DOSSIER_STATUS"
            and item.get("protected_evidence") is not None
        ):
            raise StewardshipError(
                f"frozen repair {identifier} index synchronization has protected evidence"
            )
        if (
            effect != "SYNCHRONIZE_EXISTING_DOSSIER_STATUS"
            and item.get("index_status_evidence") is not None
        ):
            raise StewardshipError(
                f"frozen repair {identifier} has extraneous index status evidence"
            )

        target = fs_path(root, relative)
        staged = packet / "staged" / Path(*PurePosixPath(relative).parts)
        after = safe_read_within(root, staged, "frozen staged after-image")
        if not isinstance(item.get("after_sha256"), str) or sha256_bytes(after) != item["after_sha256"]:
            raise StewardshipError(f"staged after-image drifted after prepare: {relative}")
        expected_after[relative] = item["after_sha256"]
        info = lstat_optional(target)
        before_data: Optional[bytes]
        if action == "ADD":
            if item.get("before_sha256") is not None:
                raise StewardshipError(f"frozen ADD has a before digest: {relative}")
            if item.get("before_mode") is not None or item.get("after_mode") != 0o644:
                raise StewardshipError(f"frozen ADD mode binding is invalid: {relative}")
            expected_added.add(relative)
            before_data = None
            if info is None:
                target_states[relative] = "PREIMAGE"
            else:
                current = safe_read_within(root, target, "possibly recovered ADD target")
                if (
                    allow_applied
                    and sha256_bytes(current) == item["after_sha256"]
                    and stat.S_IMODE(info.st_mode) == item["after_mode"]
                ):
                    target_states[relative] = "AFTER_IMAGE"
                else:
                    raise StewardshipError(f"ADD target appeared or drifted after prepare: {relative}")
        else:
            if append_only_update(relative):
                raise StewardshipError(f"frozen repair rewrites append-only evidence: {relative}")
            if (
                not isinstance(item.get("before_mode"), int)
                or item.get("after_mode") != item.get("before_mode")
            ):
                raise StewardshipError(f"frozen UPDATE mode binding is invalid: {relative}")
            backup = safe_read_within(
                root,
                packet / "before" / Path(*PurePosixPath(relative).parts),
                "preserved target preimage",
            )
            if not isinstance(item.get("before_sha256"), str) or sha256_bytes(backup) != item["before_sha256"]:
                raise StewardshipError(f"UPDATE backup drifted after prepare: {relative}")
            current = safe_read_within(root, target, "prepared or recovered target")
            current_digest = sha256_bytes(current)
            current_mode = stat.S_IMODE(target.lstat().st_mode)
            if (
                current_digest == item["before_sha256"]
                and current == backup
                and current_mode == item["before_mode"]
            ):
                target_states[relative] = "PREIMAGE"
            elif (
                allow_applied
                and current_digest == item["after_sha256"]
                and current_mode == item["after_mode"]
            ):
                target_states[relative] = "AFTER_IMAGE"
            else:
                raise StewardshipError(f"UPDATE target drifted outside the frozen transaction: {relative}")
            expected_before[relative] = item["before_sha256"]
            before_data = backup

        structured_target = PurePosixPath(relative).suffix.lower() in {".json", ".yaml", ".yml"}
        removed_ids = stable_object_ids(
            before_data or b"{}", strict_status_format=structured_target
        ) - stable_object_ids(after, strict_status_format=structured_target)
        if removed_ids:
            raise StewardshipError(
                f"frozen repair {identifier} removes stable structured identities: {sorted(removed_ids)!r}"
            )
        pairs = changed_status_pairs(
            before_data, after, strict_status_format=structured_target
        )
        removed_statuses = [field for field, _, new in pairs if new is None]
        if removed_statuses:
            raise StewardshipError(
                f"frozen repair {identifier} removes status fields: {removed_statuses!r}"
            )
        if before_data is not None:
            before_bindings = status_claim_bindings(
                before_data, strict_status_format=structured_target
            )
            after_bindings = status_claim_bindings(
                after, strict_status_format=structured_target
            )
            bindings_match = before_bindings == after_bindings
            if effect == "SYNCHRONIZE_EXISTING_DOSSIER_STATUS":
                bindings_match = all(
                    after_bindings.get(field) == owners
                    for field, owners in before_bindings.items()
                )
            if not bindings_match:
                raise StewardshipError(
                    f"frozen repair {identifier} relocates a status field between stable owners"
                )
        if effect == "SYNCHRONIZE_EXISTING_DOSSIER_STATUS":
            required_pairs, aggregate_status_fields = index_status_pairs(pairs)
        else:
            aggregate_status_fields = []
            required_pairs = [
                pair
                for pair in pairs
                if pair[1] is not None
                or (
                    isinstance(pair[2], str)
                    and pair[2].strip().upper()
                    not in CONSERVATIVE_STATUS_DESTINATIONS
                )
            ]
        transitions = item.get("status_transitions", [])
        if not isinstance(transitions, list):
            raise StewardshipError(f"frozen repair {identifier} status_transitions is invalid")
        validated = [
            validate_status_transition(root, transition, pairs, planned_paths)
            for transition in transitions
        ]
        claim_bindings = status_claim_bindings(
            after, strict_status_format=structured_target
        )
        for transition in validated:
            owners = claim_bindings.get(transition["status_field"], set())
            if len(owners) > 1 or (owners and transition["claim_id"] not in owners) or (
                transition["kind"]
                in {"EXISTING_VERDICT", "EXISTING_DOSSIER_STATUS"}
                and not owners
            ):
                raise StewardshipError(
                    f"frozen repair {identifier} status field is not owned by declared claim_id"
                )
        if sorted(transition["status_field"] for transition in validated) != sorted(
            field for field, _, _ in required_pairs
        ):
            raise StewardshipError(f"frozen repair {identifier} status bindings are incomplete")
        kinds = {transition["kind"] for transition in validated}
        if "EXISTING_VERDICT" in kinds and (
            effect != "RECORD_EXISTING_VERDICT"
            or repair_class != "PROTECTED_STATUS_TRANSITION"
        ):
            raise StewardshipError(f"frozen repair {identifier} strong transition mismatch")
        if "EXISTING_DOSSIER_STATUS" in kinds and (
            effect != "SYNCHRONIZE_EXISTING_DOSSIER_STATUS"
            or repair_class != "EVIDENCE_RECONCILIATION"
            or kinds != {"EXISTING_DOSSIER_STATUS"}
        ):
            raise StewardshipError(
                f"frozen repair {identifier} dossier-status transition mismatch"
            )
        if effect == "SYNCHRONIZE_EXISTING_DOSSIER_STATUS":
            if kinds != {"EXISTING_DOSSIER_STATUS"}:
                raise StewardshipError(
                    f"frozen repair {identifier} index synchronization has non-dossier transitions"
                )
            validate_index_status_bindings(validated, index_status_evidence)
            if not required_pairs:
                raise StewardshipError(
                    f"frozen repair {identifier} index synchronization has no dossier status"
                )
            if aggregate_status_fields and not index_status_evidence:
                raise StewardshipError(
                    f"frozen repair {identifier} aggregate status has no dossier evidence"
                )
        if kinds == {"CONSERVATIVE_RECONCILIATION"} and repair_class != "EVIDENCE_RECONCILIATION":
            raise StewardshipError(f"frozen repair {identifier} conservative transition mismatch")
        if protected_evidence is not None:
            for transition in validated:
                if transition["kind"] != "EXISTING_VERDICT":
                    continue
                for key in (
                    "claim_id",
                    "problem_id",
                    "target_id",
                    "exact_scope_artifact",
                    "exact_scope_sha256",
                    "gate",
                    "independence_level",
                    "verdict",
                ):
                    if transition.get(key) != protected_evidence.get(key):
                        raise StewardshipError(
                            f"frozen repair {identifier} protected binding mismatch: {key}"
                        )
        if relative.casefold().startswith("results/verified/"):
            raise StewardshipError(
                f"frozen repair {identifier} cannot create or rewrite verified-result artifacts in v1"
            )

    before_manifest = parse_hash_manifest(
        safe_read_within(root, packet / "before.sha256", "before manifest"),
        "before manifest",
    )
    added_manifest = parse_added_paths(
        safe_read_within(root, packet / "added_paths.txt", "added-path manifest"),
        "added-path manifest",
    )
    after_manifest = parse_hash_manifest(
        safe_read_within(root, packet / "planned_after.sha256", "planned-after manifest"),
        "planned-after manifest",
    )
    if before_manifest != expected_before:
        raise StewardshipError("frozen before manifest disagrees with the repair plan")
    if added_manifest != expected_added:
        raise StewardshipError("frozen added-path manifest disagrees with the repair plan")
    if after_manifest != expected_after:
        raise StewardshipError("frozen planned-after manifest disagrees with the repair plan")
    if protected_change_count:
        process = subprocess.run(
            [sys.executable, "scripts/validate_proof_search.py"],
            cwd=str(root),
            text=True,
            capture_output=True,
            timeout=300,
        )
        if process.returncode != 0:
            raise StewardshipError("protected proof-search preflight no longer passes")
    return target_states


def apply_run(root: Path, run_id: str) -> Dict[str, Any]:
    root = require_lab_root(root)
    packet, manifest = load_manifest(root, run_id)
    if manifest.get("status") not in {"PREPARED", "APPLYING", "PARTIAL_APPLY"}:
        raise StewardshipError(
            f"apply/resume requires PREPARED, APPLYING, or PARTIAL_APPLY; got {manifest.get('status')!r}"
        )
    plan = load_frozen_plan(packet, manifest)
    before = read_object(packet / "inventory_before.json", "starting inventory")
    target_states = validate_frozen_preimages(
        root, packet, plan, allow_applied=True
    )
    current = snapshot(root)
    recovered_paths = sorted(
        path for path, state in target_states.items() if state == "AFTER_IMAGE"
    )
    if survey.snapshot_changes(before, current) != recovered_paths:
        raise StewardshipError("laboratory state drifted outside recoverable planned after-images")

    applied: List[str] = list(recovered_paths)
    update_manifest(
        root,
        packet,
        manifest,
        status="APPLYING",
        updated_at_utc=utc_now(),
        applied_paths=applied,
        error=None,
    )
    failed_path: Optional[str] = None
    try:
        for item in plan.get("changes", []):
            relative = item["path"]
            failed_path = relative
            if target_states[relative] == "AFTER_IMAGE":
                append_journal(
                    root,
                    packet,
                    {"event": "RECOVERED", "id": item["id"], "path": relative, "at_utc": utc_now()},
                )
                continue
            staged = packet / "staged" / Path(*PurePosixPath(relative).parts)
            data = safe_read_within(root, staged, "frozen staged after-image")
            append_journal(
                root,
                packet,
                {"event": "INTENT", "id": item["id"], "path": relative, "at_utc": utc_now()},
            )
            target = fs_path(root, relative)
            if item["action"] == "ADD":
                atomic_create(target, data, root, mode=item["after_mode"])
            else:
                current_data = safe_read_within(
                    root, target, "target before atomic replace"
                )
                if sha256_bytes(current_data) != item["before_sha256"]:
                    raise StewardshipError(f"target changed during application: {relative}")
                atomic_replace(
                    target,
                    data,
                    root,
                    mode=item["after_mode"],
                    expected_before=current_data,
                )
            installed = safe_read_within(root, target, "installed repair")
            installed_mode = stat.S_IMODE(target.lstat().st_mode)
            if (
                sha256_bytes(installed) != item["after_sha256"]
                or installed_mode != item["after_mode"]
            ):
                raise StewardshipError(f"installed repair hash mismatch: {relative}")
            applied.append(relative)
            append_journal(
                root,
                packet,
                {"event": "APPLIED", "id": item["id"], "path": relative, "at_utc": utc_now()},
            )
        after = snapshot(root)
        changed = survey.snapshot_changes(before, after)
        expected = sorted(item["path"] for item in plan.get("changes", []))
        if changed != expected:
            raise StewardshipError("post-apply changed paths differ from the frozen plan")
        after_items = [
            (
                relative,
                safe_read_within(root, fs_path(root, relative), "post-apply target"),
            )
            for relative in expected
        ]
        create_or_verify(
            root,
            packet / "after.sha256",
            format_hash_manifest(after_items),
            "after manifest",
        )
        inventory_after_path = packet / "inventory_after_apply.json"
        if lstat_optional(inventory_after_path) is None:
            atomic_create(inventory_after_path, json_bytes(after), root)
        else:
            recorded_after = read_object(inventory_after_path, "post-apply inventory")
            if recorded_after.get("inventory_sha256") != after["inventory_sha256"]:
                raise StewardshipError("existing post-apply inventory disagrees with recovered state")
        update_manifest(
            root,
            packet,
            manifest,
            status="APPLIED",
            updated_at_utc=utc_now(),
            applied_paths=expected,
            changed_paths=changed,
            finishing_inventory_sha256=after["inventory_sha256"],
            failed_path=None,
            error=None,
        )
    except Exception as exc:
        update_manifest(
            root,
            packet,
            manifest,
            status="PARTIAL_APPLY",
            updated_at_utc=utc_now(),
            applied_paths=applied,
            failed_path=failed_path,
            error=str(exc),
        )
        if isinstance(exc, StewardshipError):
            raise
        raise StewardshipError(f"application failed after {len(applied)} paths: {exc}") from exc
    return {
        "status": "APPLIED",
        "run_id": run_id,
        "changed_paths": changed,
        "finishing_inventory_sha256": after["inventory_sha256"],
        "next": "complete report.md, then run finalize",
    }


def structural_validation_command(root: Path) -> Tuple[str, List[str]]:
    manifest = read_object(
        root / ".lab" / "manifest.json", "laboratory origin manifest"
    )
    origin_kind = manifest.get("origin_kind")
    if origin_kind == "LEGACY_ADOPTED":
        validator = require_regular_project_path(
            root,
            "scripts/lab_state.py",
            "legacy-adopted laboratory structural validator",
        )
        return ("lab-state", [sys.executable, validator, "check"])
    if origin_kind not in {None, "GENERATED"}:
        raise StewardshipError(
            f"unsupported laboratory origin_kind for validation: {origin_kind!r}"
        )
    validator = require_regular_project_path(
        root,
        "scripts/validate_lab.py",
        "generated laboratory structural validator",
    )
    return ("lab-structure", [sys.executable, validator])


def validation_commands(root: Path) -> List[Tuple[str, List[str]]]:
    structural = structural_validation_command(root)
    return [
        ("doctor", [sys.executable, "scripts/doctor.py"]),
        structural,
        ("ledgers", [sys.executable, "scripts/validate_ledgers.py"]),
        ("proof-search", [sys.executable, "scripts/validate_proof_search.py"]),
        ("full-eval-no-report", [sys.executable, "scripts/run_evals.py", "--no-report"]),
    ]


def normalized_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def run_validation(root: Path) -> Tuple[Dict[str, Any], bool]:
    records: List[Dict[str, Any]] = []
    passed = True
    for name, command in validation_commands(root):
        started = utc_now()
        try:
            process = subprocess.run(
                command,
                cwd=str(root),
                text=True,
                capture_output=True,
                timeout=600,
            )
            record = {
                "name": name,
                "command": command,
                "started_at_utc": started,
                "completed_at_utc": utc_now(),
                "returncode": process.returncode,
                "stdout": process.stdout,
                "stderr": process.stderr,
                "status": "PASS" if process.returncode == 0 else "FAIL",
            }
        except subprocess.TimeoutExpired as exc:
            record = {
                "name": name,
                "command": command,
                "started_at_utc": started,
                "completed_at_utc": utc_now(),
                "returncode": None,
                "stdout": normalized_output(exc.stdout),
                "stderr": normalized_output(exc.stderr),
                "status": "TIMEOUT",
            }
        except OSError as exc:
            record = {
                "name": name,
                "command": command,
                "started_at_utc": started,
                "completed_at_utc": utc_now(),
                "returncode": None,
                "stdout": "",
                "stderr": str(exc),
                "status": "ERROR",
            }
        records.append(record)
        passed = passed and record["status"] == "PASS"
    return {
        "schema_version": 1,
        "completed_at_utc": utc_now(),
        "status": "PASS" if passed else "FAIL",
        "checks": records,
        "integrity_note": "Passing checks establish declared structure, not mathematical truth.",
    }, passed


REPORT_SECTIONS = tuple(f"## {index}." for index in range(12))


def validate_completed_report(report: bytes) -> str:
    try:
        text = report.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StewardshipError("report.md must be UTF-8") from exc
    if (
        "stewardship-report:INCOMPLETE" in text
        or "Stewardship report status: COMPLETE" not in text
        or len(text.strip()) < 900
    ):
        raise StewardshipError("report.md is incomplete")
    positions: List[int] = []
    for heading in REPORT_SECTIONS:
        position = text.find(heading)
        if position < 0:
            raise StewardshipError(f"report.md lacks required section {heading}")
        positions.append(position)
    if positions != sorted(positions):
        raise StewardshipError("report.md required sections are out of order")
    positions.append(len(text))
    for index in range(len(REPORT_SECTIONS)):
        body = text[positions[index] : positions[index + 1]]
        substantive = [
            line.strip()
            for line in body.splitlines()[1:]
            if line.strip()
            and not line.lstrip().startswith("|")
            and not line.lstrip().startswith("<!--")
        ]
        if len(" ".join(substantive)) < 24:
            raise StewardshipError(
                f"report.md section {index} has no substantive completed content"
            )
    return text


def validate_completion_basis(
    root: Path,
    packet: Path,
    manifest: Mapping[str, Any],
    before: Mapping[str, Any],
    expected: Sequence[str],
    report: bytes,
) -> Dict[str, Any]:
    completion_path = packet / "completion_basis.json"
    completion = read_object(completion_path, "completion basis")
    expected_bindings = {
        "run_id": manifest.get("run_id"),
        "status": "VALIDATED_PENDING_SURVEY",
        "starting_inventory_sha256": before.get("inventory_sha256"),
        "frozen_plan_sha256": manifest.get("frozen_plan_sha256"),
        "before_manifest_sha256": sha256_bytes(
            safe_read_within(root, packet / "before.sha256", "before manifest")
        ),
        "after_manifest_sha256": sha256_bytes(
            safe_read_within(root, packet / "after.sha256", "after manifest")
        ),
        "validation_sha256": sha256_bytes(
            safe_read_within(root, packet / "validation.json", "validation record")
        ),
        "report_sha256": sha256_bytes(report),
        "changed_paths": list(expected),
    }
    for key, value in expected_bindings.items():
        if completion.get(key) != value:
            raise StewardshipError(f"completion basis binding mismatch: {key}")
    validation = read_object(packet / "validation.json", "validation record")
    if validation.get("status") != "PASS":
        raise StewardshipError("completion basis refers to non-passing validation")
    return completion


def require_installed_after_images(
    root: Path, plan: Mapping[str, Any], label: str
) -> None:
    for item in plan.get("changes", []):
        target = fs_path(root, item["path"])
        if (
            sha256_bytes(safe_read_within(root, target, label))
            != item["after_sha256"]
            or stat.S_IMODE(target.lstat().st_mode) != item["after_mode"]
        ):
            raise StewardshipError(f"{label} digest or mode mismatch: {item['path']}")


def finalize_run(root: Path, run_id: str) -> Tuple[Dict[str, Any], int]:
    root = require_lab_root(root)
    packet, manifest = load_manifest(root, run_id)
    if manifest.get("status") not in {
        "APPLIED",
        "FAILED_VALIDATION",
        "VALIDATED_PENDING_SURVEY",
    }:
        raise StewardshipError(
            "finalize/resume requires APPLIED, FAILED_VALIDATION, or "
            f"VALIDATED_PENDING_SURVEY; got {manifest.get('status')!r}"
        )
    plan = load_frozen_plan(packet, manifest)
    before = read_object(packet / "inventory_before.json", "starting inventory")
    current = snapshot(root)
    changed = survey.snapshot_changes(before, current)
    expected = sorted(item["path"] for item in plan.get("changes", []))
    if changed != expected:
        update_manifest(
            root,
            packet,
            manifest,
            status="DRIFT_DETECTED",
            updated_at_utc=utc_now(),
            changed_paths=changed,
            error="state drifted between apply and finalize",
        )
        return ({"status": "DRIFT_DETECTED", "changed_paths": changed}, 2)
    require_installed_after_images(root, plan, "final repair target")
    report = safe_read_within(root, packet / "report.md", "stewardship report")
    validate_completed_report(report)

    completion_path = packet / "completion_basis.json"
    if lstat_optional(completion_path) is None:
        validation, passed = run_validation(root)
        validation_path = packet / "validation.json"
        if lstat_optional(validation_path) is None:
            atomic_create(validation_path, json_bytes(validation), root)
        else:
            atomic_replace(validation_path, json_bytes(validation), root)
        if not passed:
            update_manifest(
                root,
                packet,
                manifest,
                status="FAILED_VALIDATION",
                updated_at_utc=utc_now(),
                validation=f"{run_relative(run_id)}/validation.json",
                error="one or more required checks failed",
            )
            return ({"status": "FAILED_VALIDATION", "validation": validation}, 2)

        after_validation = snapshot(root)
        validation_changed = survey.snapshot_changes(before, after_validation)
        if validation_changed != expected:
            update_manifest(
                root,
                packet,
                manifest,
                status="DRIFT_DETECTED",
                updated_at_utc=utc_now(),
                changed_paths=validation_changed,
                validation=f"{run_relative(run_id)}/validation.json",
                error="validation or concurrent work changed observable state",
            )
            return ({"status": "DRIFT_DETECTED", "changed_paths": validation_changed}, 2)
        try:
            require_installed_after_images(root, plan, "post-validation repair target")
        except StewardshipError as exc:
            update_manifest(
                root,
                packet,
                manifest,
                status="DRIFT_DETECTED",
                updated_at_utc=utc_now(),
                changed_paths=validation_changed,
                validation=f"{run_relative(run_id)}/validation.json",
                error=str(exc),
            )
            return ({"status": "DRIFT_DETECTED", "error": str(exc)}, 2)

        completion = {
            "schema_version": 1,
            "run_id": run_id,
            "status": "VALIDATED_PENDING_SURVEY",
            "created_at_utc": utc_now(),
            "starting_inventory_sha256": before["inventory_sha256"],
            "validated_inventory_sha256": after_validation["inventory_sha256"],
            "frozen_plan_sha256": manifest["frozen_plan_sha256"],
            "before_manifest_sha256": sha256_bytes(
                safe_read_within(root, packet / "before.sha256", "before manifest")
            ),
            "after_manifest_sha256": sha256_bytes(
                safe_read_within(root, packet / "after.sha256", "after manifest")
            ),
            "validation_sha256": sha256_bytes(
                safe_read_within(root, packet / "validation.json", "validation record")
            ),
            "report_sha256": sha256_bytes(report),
            "changed_paths": expected,
            "integrity_note": (
                "This binds a validated maintenance transaction; it does not prove mathematics, "
                "source truth, novelty, value, or independence."
            ),
        }
        atomic_create(completion_path, json_bytes(completion), root)
    else:
        completion = validate_completion_basis(
            root, packet, manifest, before, expected, report
        )
        if current["inventory_sha256"] != completion.get("validated_inventory_sha256"):
            raise StewardshipError("validated completion basis no longer matches laboratory state")

    completion_data = safe_read_within(root, completion_path, "completion basis")
    completion = validate_completion_basis(
        root, packet, manifest, before, expected, report
    )
    completion_relative = f"{run_relative(run_id)}/completion_basis.json"
    update_manifest(
        root,
        packet,
        manifest,
        status="VALIDATED_PENDING_SURVEY",
        updated_at_utc=utc_now(),
        validation=f"{run_relative(run_id)}/validation.json",
        completion_basis=completion_relative,
        completion_basis_sha256=sha256_bytes(completion_data),
        error=None,
    )

    survey_id = f"{run_id}-post-stewardship"
    literature_mode = plan.get("literature_mode")
    survey_mode = (
        "LOCAL_WITH_EXPLICIT_LITERATURE_DELTA"
        if literature_mode == "EXPLICIT_PUBLIC_SAFE_DELTA"
        else "LOCAL_FULL"
    )
    try:
        survey_packet = root / "runs" / "laboratory_surveys" / survey_id
        if lstat_optional(survey_packet) is None:
            survey.start_survey(root, survey_id, survey_mode, [completion_relative])
        create_or_verify(
            root, survey_packet / "report.md", report, "post-stewardship survey report"
        )
        if survey_mode == "LOCAL_WITH_EXPLICIT_LITERATURE_DELTA":
            delta = safe_read_within(
                root, packet / "literature_delta.md", "stewardship literature delta"
            )
            create_or_verify(
                root,
                survey_packet / "literature_delta.md",
                delta,
                "post-stewardship literature delta",
            )
        survey_result, survey_code = survey.finalize_survey(root, survey_id)
    except (survey.SurveyError, StewardshipError) as exc:
        raise StewardshipError(str(exc)) from exc
    if survey_code != 0:
        update_manifest(
            root,
            packet,
            manifest,
            status="DRIFT_DETECTED",
            updated_at_utc=utc_now(),
            final_survey=f"runs/laboratory_surveys/{survey_id}/manifest.json",
            error="final survey did not reach a stable finish",
        )
        return ({"status": "DRIFT_DETECTED", "final_survey": survey_result}, 2)

    resume_relative = require_regular_project_path(
        root, "scripts/snapshot_project_state.py", "resume refresh script"
    )
    resume_command = [sys.executable, resume_relative, "--resume-only"]
    try:
        process = subprocess.run(
            resume_command,
            cwd=str(root),
            text=True,
            capture_output=True,
            timeout=300,
        )
        resume_record = {
            "schema_version": 1,
            "command": resume_command,
            "completed_at_utc": utc_now(),
            "returncode": process.returncode,
            "stdout": process.stdout,
            "stderr": process.stderr,
            "status": "PASS" if process.returncode == 0 else "FAIL",
        }
    except subprocess.TimeoutExpired as exc:
        resume_record = {
            "schema_version": 1,
            "command": resume_command,
            "completed_at_utc": utc_now(),
            "returncode": None,
            "stdout": normalized_output(exc.stdout),
            "stderr": normalized_output(exc.stderr),
            "status": "TIMEOUT",
        }
    except OSError as exc:
        resume_record = {
            "schema_version": 1,
            "command": resume_command,
            "completed_at_utc": utc_now(),
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
            "status": "ERROR",
        }
    resume_path = packet / "post_survey_resume.json"
    if lstat_optional(resume_path) is None:
        atomic_create(resume_path, json_bytes(resume_record), root)
    else:
        atomic_replace(resume_path, json_bytes(resume_record), root)
    if resume_record["status"] != "PASS":
        update_manifest(
            root,
            packet,
            manifest,
            status="VALIDATED_PENDING_SURVEY",
            updated_at_utc=utc_now(),
            final_survey=f"runs/laboratory_surveys/{survey_id}/manifest.json",
            error="post-survey resume refresh failed",
        )
        return ({"status": "FAILED_POST_SURVEY_REFRESH", "resume": resume_record}, 2)

    try:
        require_installed_after_images(root, plan, "post-resume repair target")
    except StewardshipError as exc:
        update_manifest(
            root,
            packet,
            manifest,
            status="DRIFT_DETECTED",
            updated_at_utc=utc_now(),
            final_survey=f"runs/laboratory_surveys/{survey_id}/manifest.json",
            error=str(exc),
        )
        return ({"status": "DRIFT_DETECTED", "error": str(exc)}, 2)

    freshness_result, freshness_code = survey.check_freshness(root)
    if (
        freshness_code != 0
        or freshness_result.get("freshness") != "FRESH"
        or freshness_result.get("latest_survey_id") != survey_id
    ):
        update_manifest(
            root,
            packet,
            manifest,
            status="DRIFT_DETECTED",
            updated_at_utc=utc_now(),
            final_survey=f"runs/laboratory_surveys/{survey_id}/manifest.json",
            error="post-resume survey freshness check failed",
        )
        return ({"status": "DRIFT_DETECTED", "final_survey": freshness_result}, 2)

    update_manifest(
        root,
        packet,
        manifest,
        status="COMPLETED",
        updated_at_utc=utc_now(),
        completed_at_utc=utc_now(),
        final_survey=f"runs/laboratory_surveys/{survey_id}/report.md",
        final_survey_manifest=f"runs/laboratory_surveys/{survey_id}/manifest.json",
        post_survey_resume=f"{run_relative(run_id)}/post_survey_resume.json",
        error=None,
    )
    return (
        {
            "status": "COMPLETED",
            "run_id": run_id,
            "packet": run_relative(run_id),
            "changed_paths": expected,
            "deferred": plan.get("deferred", []),
            "validation": "PASS",
            "final_survey": f"runs/laboratory_surveys/{survey_id}/report.md",
            "final_survey_freshness": survey_result.get("status"),
        },
        0,
    )


def print_result(value: Dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        return
    for key, item in value.items():
        if isinstance(item, list):
            item = ", ".join(str(value) for value in item) if item else "none"
        print(f"{key}: {item}")


def resume_run(root: Path, run_id: str) -> Tuple[Dict[str, Any], int]:
    root = require_lab_root(root)
    _, manifest = load_manifest(root, run_id)
    status = manifest.get("status")
    if status in {"PREPARED", "APPLYING", "PARTIAL_APPLY"}:
        return apply_run(root, run_id), 0
    if status in {"APPLIED", "FAILED_VALIDATION", "VALIDATED_PENDING_SURVEY"}:
        return finalize_run(root, run_id)
    if status == "COMPLETED":
        freshness, code = survey.check_freshness(root)
        if code != 0 or freshness.get("freshness") != "FRESH":
            return {
                "status": "COMPLETED_BUT_SURVEY_STALE",
                "run_id": run_id,
                "freshness": freshness,
            }, 2
        return {
            "status": "COMPLETED",
            "run_id": run_id,
            "final_survey": manifest.get("final_survey"),
            "freshness": "FRESH",
        }, 0
    raise StewardshipError(
        f"run {run_id} cannot be automatically resumed from {status!r}; inspect its packet"
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Run guarded, hash-bound laboratory stewardship transactions."
    )
    result.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    commands = result.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="start a read-only stewardship audit")
    start.add_argument("--run-id", required=True)
    start.add_argument("--mode", choices=sorted(MODES), default="DEEP_LOCAL")
    start.add_argument("--json", action="store_true")
    for name in ("prepare", "apply", "finalize", "resume"):
        command = commands.add_parser(name)
        command.add_argument("--run-id", required=True)
        command.add_argument("--json", action="store_true")
    return result


def run(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    root = require_root(args.root)
    if args.command == "start":
        value = start_run(root, args.run_id, args.mode)
        code = 0
    elif args.command == "prepare":
        value = prepare_run(root, args.run_id)
        code = 0
    elif args.command == "apply":
        value = apply_run(root, args.run_id)
        code = 0
    elif args.command == "finalize":
        value, code = finalize_run(root, args.run_id)
    else:
        value, code = resume_run(root, args.run_id)
    print_result(value, args.json)
    return code


def main() -> int:
    try:
        return run()
    except StewardshipError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
