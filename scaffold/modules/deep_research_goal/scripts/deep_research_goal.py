#!/usr/bin/env python3
"""Prepare and validate immutable deep-research campaign records.

This dependency-free helper manages workflow provenance only.  It does not run
models, judge mathematical truth, or promote theorem status.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


SCHEMA_VERSION = 1
PROTOCOL_VERSION = 1
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MODE_PRESETS = {
    "SCOUT": {
        "wall_time_cap_seconds": 1800,
        "target_cap": 12,
        "minimum_initial_routes": 1,
        "orchestration": "QUALIFICATION",
    },
    "TRIAL": {
        "wall_time_cap_seconds": 7200,
        "target_cap": 3,
        "minimum_initial_routes": 3,
        "orchestration": "FULL",
    },
    "DEEP": {
        "wall_time_cap_seconds": 21600,
        "target_cap": 1,
        "minimum_initial_routes": 5,
        "orchestration": "FULL",
    },
}
MARATHON_TOTALS = (43200, 86400, 115200)
MARATHON_STAGE_CAP = 21600
STRICT_OUTCOMES = (
    "VERIFIED_PROOF",
    "VERIFIED_REFUTATION",
    "EXACT_LEMMA",
    "CHECKED_COUNTEREXAMPLE",
    "DECISIVE_BARRIER",
)
OUTCOME_CLASSES = STRICT_OUTCOMES + ("NO_STRICT_REDUCTION",)
USAGE_SOURCES = ("OUTER_RUNNER_REPORTED", "USER_RECORDED", "UNAVAILABLE")
MECHANISM_FAMILIES = (
    "ALGEBRAIC",
    "ANALYTIC",
    "COMBINATORIAL",
    "COMPUTATIONAL_EXPERIMENTAL",
    "COUNTEREXAMPLE_SEARCH",
    "DYNAMICAL",
    "FORMAL_LOGICAL",
    "GEOMETRIC",
    "GRAPH_THEORETIC",
    "NUMBER_THEORETIC",
    "OPTIMIZATION_VARIATIONAL",
    "ORDER_LATTICE",
    "PROBABILISTIC",
    "REPRESENTATION_THEORETIC",
    "TOPOLOGICAL",
    "OTHER",
)


class DeepGoalError(RuntimeError):
    pass


class OperationLock:
    """Serialize state transitions with a crash-released advisory lock."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.descriptor: Optional[int] = None

    def __enter__(self) -> "OperationLock":
        flags = (
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            self.descriptor = os.open(str(self.path), flags, 0o600)
            if not stat.S_ISREG(os.fstat(self.descriptor).st_mode):
                fail(f"operation lock must be a regular file: {self.path}")
            fcntl.flock(
                self.descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB
            )
        except (BlockingIOError, PermissionError) as exc:
            if self.descriptor is not None:
                os.close(self.descriptor)
                self.descriptor = None
            raise DeepGoalError(
                f"another deep-goal state transition is active: {self.path}"
            ) from exc
        except Exception:
            if self.descriptor is not None:
                os.close(self.descriptor)
                self.descriptor = None
            raise
        os.ftruncate(self.descriptor, 0)
        os.write(
            self.descriptor,
            f"pid={os.getpid()}\n".encode("ascii"),
        )
        os.fsync(self.descriptor)
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.descriptor is not None:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
            os.close(self.descriptor)
            self.descriptor = None


def fail(message: str) -> None:
    raise DeepGoalError(message)


def no_duplicate_keys(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def record_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            fail(f"regular file required: {path}")
        digest = hashlib.sha256()
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                return digest.hexdigest()
            digest.update(block)
    finally:
        os.close(descriptor)


def bind_files(root: Path, paths: Sequence[str], label: str) -> List[Dict[str, Any]]:
    bindings: List[Dict[str, Any]] = []
    for index, relative in enumerate(paths):
        path = safe_existing_path(root, relative, f"{label}[{index}]", kind="file")
        bindings.append(
            {
                "path": relative,
                "size": path.lstat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return bindings


def hash_without(value: Dict[str, Any], key: str) -> str:
    payload = {name: item for name, item in value.items() if name != key}
    return sha256_bytes(canonical_bytes(payload))


def require_exact_keys(
    value: Any,
    required: Iterable[str],
    optional: Iterable[str],
    label: str,
) -> Dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{label} must be an object")
    required_set = set(required)
    allowed = required_set | set(optional)
    missing = sorted(required_set - set(value))
    extra = sorted(set(value) - allowed)
    if missing or extra:
        fail(f"{label} keys invalid; missing={missing}, extra={extra}")
    return value


def require_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        fail(f"{label} must match {ID_RE.pattern}")
    return value


def require_problem_id(value: Any, label: str) -> str:
    parts = relative_parts(value, label)
    if len(parts) != 1 or len(parts[0].encode("utf-8")) > 180:
        fail(f"{label} must be one safe path component of at most 180 UTF-8 bytes")
    return parts[0]


def require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        fail(f"{label} must be a lowercase SHA-256 digest")
    return value


def require_text(
    value: Any,
    label: str,
    *,
    single_line: bool = False,
    maximum_bytes: int = 12000,
) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{label} must be a non-empty string")
    text = value.strip()
    if len(text.encode("utf-8")) > maximum_bytes:
        fail(f"{label} exceeds {maximum_bytes} UTF-8 bytes")
    if single_line and (
        len(text.splitlines()) != 1
        or any(ord(character) < 32 or ord(character) == 127 for character in text)
    ):
        fail(f"{label} must be a safe single line")
    return text


def require_iso(value: Any, label: str) -> str:
    if not isinstance(value, str) or not ISO_RE.fullmatch(value):
        fail(f"{label} must use YYYY-MM-DDTHH:MM:SSZ")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise DeepGoalError(f"{label} is not a valid UTC timestamp") from exc
    return value


def require_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        fail(f"{label} must be a boolean")
    return value


def require_int(
    value: Any,
    label: str,
    *,
    minimum: int = 0,
    maximum: Optional[int] = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        fail(f"{label} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        fail(f"{label} is outside the allowed range")
    return value


def require_text_list(
    value: Any,
    label: str,
    *,
    minimum: int = 0,
    maximum: int = 64,
    single_line: bool = False,
) -> List[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        fail(f"{label} must contain between {minimum} and {maximum} items")
    result = [
        require_text(
            item,
            f"{label}[{index}]",
            single_line=single_line,
            maximum_bytes=256 if single_line else 12000,
        )
        for index, item in enumerate(value)
    ]
    folded = [item.casefold() for item in result]
    if len(set(folded)) != len(folded):
        fail(f"{label} must not contain duplicates")
    return result


def relative_parts(relative: Any, label: str) -> Tuple[str, ...]:
    if (
        not isinstance(relative, str)
        or not relative
        or len(relative.encode("utf-8")) > 512
        or relative.startswith("/")
        or "\\" in relative
        or any(ord(character) < 32 or ord(character) == 127 for character in relative)
    ):
        fail(f"{label} must be a safe POSIX root-relative path")
    parts = tuple(relative.split("/"))
    if any(part in ("", ".", "..") for part in parts):
        fail(f"{label} contains an unsafe path component")
    return parts


def safe_existing_path(
    root: Path,
    relative: Any,
    label: str,
    *,
    kind: str = "file",
) -> Path:
    parts = relative_parts(relative, label)
    current = root
    for index, part in enumerate(parts):
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError as exc:
            raise DeepGoalError(f"{label} does not exist: {relative}") from exc
        if stat.S_ISLNK(mode):
            fail(f"{label} must not traverse a symlink: {relative}")
        if index < len(parts) - 1 and not stat.S_ISDIR(mode):
            fail(f"{label} has a non-directory component: {relative}")
    final_mode = current.lstat().st_mode
    if kind == "file" and not stat.S_ISREG(final_mode):
        fail(f"{label} must name a regular file: {relative}")
    if kind == "dir" and not stat.S_ISDIR(final_mode):
        fail(f"{label} must name a directory: {relative}")
    return current


def ensure_root(root_arg: str) -> Path:
    root = Path(root_arg).absolute()
    try:
        mode = root.lstat().st_mode
    except FileNotFoundError as exc:
        raise DeepGoalError(f"laboratory root does not exist: {root}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        fail(f"laboratory root must be a real directory: {root}")
    return root


def read_json_file(path: Path, label: str) -> Tuple[Dict[str, Any], bytes]:
    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            fail(f"{label} must be a regular file")
        chunks: List[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > 2 * 1024 * 1024:
                fail(f"{label} exceeds 2 MiB")
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    raw = b"".join(chunks)
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeepGoalError(f"cannot parse {label}: {exc}") from exc
    if not isinstance(value, dict):
        fail(f"{label} must contain an object")
    return value, raw


def load_input(root: Path, relative: str, label: str) -> Dict[str, Any]:
    path = safe_existing_path(root, relative, label, kind="file")
    value, _ = read_json_file(path, label)
    return value


def require_read_only(path: Path, label: str) -> None:
    if path.lstat().st_mode & 0o222:
        fail(f"{label} must be read-only: {path}")


def write_immutable(path: Path, value: Dict[str, Any]) -> None:
    payload = record_bytes(value)
    path.parent.mkdir(parents=False, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.publish-", dir=str(path.parent)
    )
    temporary_path = Path(temporary_name)
    descriptor_open = True
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o444)
        os.close(descriptor)
        descriptor_open = False
        try:
            os.link(
                str(temporary_path),
                str(path),
                src_dir_fd=None,
                dst_dir_fd=None,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise DeepGoalError(
                f"refusing to overwrite existing record: {path}"
            ) from exc
        directory_descriptor = os.open(
            str(path.parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor_open:
            os.close(descriptor)
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def fsync_directory(path: Path) -> None:
    descriptor = os.open(
        str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def remove_abandoned_prepare_directory(path: Path) -> None:
    """Remove only a generator-owned, structurally bounded prepare staging tree."""

    if (
        not path.name.startswith(".prepare-")
        or path.is_symlink()
        or not stat.S_ISDIR(path.lstat().st_mode)
    ):
        fail(f"unsafe abandoned prepare entry: {path.name}")
    allowed_files = {"approved_goal.json"}
    for child in path.iterdir():
        mode = child.lstat().st_mode
        if child.name == "outcomes":
            if not stat.S_ISDIR(mode) or child.is_symlink() or any(child.iterdir()):
                fail(f"unsafe abandoned outcomes staging directory: {child}")
            child.rmdir()
        elif child.name in allowed_files or child.name.startswith(
            ".approved_goal.json.publish-"
        ):
            if not stat.S_ISREG(mode) or child.is_symlink():
                fail(f"unsafe abandoned prepare file: {child}")
            child.unlink()
        else:
            fail(f"unexpected abandoned prepare entry: {child}")
    path.rmdir()


def recover_abandoned_prepares(state_root: Path) -> None:
    """Recover exact factory-owned staging remnants while holding the lock."""

    for path in sorted(state_root.iterdir()):
        if path.name.startswith(".prepare-"):
            remove_abandoned_prepare_directory(path)


def load_record(path: Path, label: str) -> Dict[str, Any]:
    value, raw = read_json_file(path, label)
    if raw != record_bytes(value):
        fail(f"{label} is not in canonical record encoding")
    require_read_only(path, label)
    return value


def normalize_target(
    value: Any,
    mode: str,
    root: Path,
    *,
    check_paths: bool,
) -> Dict[str, Any]:
    target = require_exact_keys(
        value,
        (
            "kind",
            "problem_id",
            "target_id",
            "statement",
            "artifact_path",
            "acceptance_criteria",
            "anti_targets",
            "traps",
        ),
        (),
        "target",
    )
    kind = target["kind"]
    expected = "SELECTION_QUESTION" if mode == "SCOUT" else "EXACT_MATHEMATICAL_TARGET"
    if kind != expected:
        fail(f"{mode} requires target.kind={expected}")
    if mode == "SCOUT":
        if target["problem_id"] is not None or target["target_id"] is not None:
            fail("SCOUT requires target.problem_id and target.target_id to be null")
        problem_id = None
        target_id = None
    else:
        problem_id = require_problem_id(
            target["problem_id"], "target.problem_id"
        )
        target_id = require_text(
            target["target_id"],
            "target.target_id",
            single_line=True,
            maximum_bytes=256,
        )
    normalized_contract = {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "problem_id": problem_id,
        "target_id": target_id,
        "statement": require_text(target["statement"], "target.statement"),
        "acceptance_criteria": require_text_list(
            target["acceptance_criteria"],
            "target.acceptance_criteria",
            minimum=1,
            maximum=32,
        ),
        "anti_targets": require_text_list(
            target["anti_targets"], "target.anti_targets", minimum=1, maximum=32
        ),
        "traps": require_text_list(
            target["traps"], "target.traps", minimum=1, maximum=32
        ),
    }
    artifact_raw = target["artifact_path"]
    if mode == "SCOUT":
        if artifact_raw is not None:
            fail("SCOUT requires target.artifact_path=null")
        artifact_path = None
    else:
        artifact_parts = relative_parts(artifact_raw, "target.artifact_path")
        artifact_path = "/".join(artifact_parts)
        if (
            len(artifact_parts) < 4
            or artifact_parts[:2] != ("problems", "active")
            or artifact_parts[2] != problem_id
            or not any(
                marker in artifact_parts[-1].casefold()
                for marker in ("target", "problem", "context_envelope")
            )
        ):
            fail(
                "non-Scout target artifact must live under "
                "problems/active/<problem_id>/ and have a target/problem/"
                "context_envelope filename"
            )
        if check_paths:
            artifact = safe_existing_path(
                root, artifact_path, "target.artifact_path", kind="file"
            )
            artifact_value, artifact_raw_bytes = read_json_file(
                artifact, "target artifact"
            )
            require_exact_keys(
                artifact_value,
                (
                    "schema_version",
                    "kind",
                    "problem_id",
                    "target_id",
                    "statement",
                    "acceptance_criteria",
                    "anti_targets",
                    "traps",
                ),
                (),
                "target artifact",
            )
            if (
                artifact_value != normalized_contract
                or artifact_raw_bytes != record_bytes(normalized_contract)
            ):
                fail(
                    "target artifact must be the canonical serialization of the "
                    "full inline target contract"
                )
    return {
        "kind": normalized_contract["kind"],
        "problem_id": normalized_contract["problem_id"],
        "target_id": normalized_contract["target_id"],
        "statement": normalized_contract["statement"],
        "artifact_path": artifact_path,
        "acceptance_criteria": normalized_contract["acceptance_criteria"],
        "anti_targets": normalized_contract["anti_targets"],
        "traps": normalized_contract["traps"],
    }


def normalize_sources(
    value: Any,
    root: Path,
    mode: str,
    *,
    check_paths: bool,
) -> Dict[str, Any]:
    sources = require_exact_keys(
        value,
        (
            "human_leads_allowed",
            "public_web_search_allowed",
            "allowed_source_paths",
            "citation_required",
        ),
        (),
        "source_policy",
    )
    human = require_bool(sources["human_leads_allowed"], "source_policy.human_leads_allowed")
    web = require_bool(
        sources["public_web_search_allowed"], "source_policy.public_web_search_allowed"
    )
    citation = require_bool(sources["citation_required"], "source_policy.citation_required")
    if not citation:
        fail("source_policy.citation_required must be true")
    raw_paths = sources["allowed_source_paths"]
    if not isinstance(raw_paths, list) or len(raw_paths) > 128:
        fail("source_policy.allowed_source_paths must be an array of at most 128 paths")
    paths: List[str] = []
    for index, raw_path in enumerate(raw_paths):
        parts = relative_parts(raw_path, f"source_policy.allowed_source_paths[{index}]")
        path = "/".join(parts)
        if check_paths:
            safe_existing_path(
                root,
                path,
                f"source_policy.allowed_source_paths[{index}]",
                kind="file",
            )
        paths.append(path)
    if len(set(paths)) != len(paths):
        fail("source_policy.allowed_source_paths must not contain duplicates")
    if mode == "SCOUT" and (not human or not (web or paths)):
        fail("SCOUT requires hybrid sourcing: human leads plus a bound local or public source")
    return {
        "human_leads_allowed": human,
        "public_web_search_allowed": web,
        "allowed_source_paths": paths,
        "citation_required": True,
    }


def normalize_search(value: Any, mode: str) -> Dict[str, Any]:
    search = require_exact_keys(
        value,
        (
            "initial_routes",
            "stopping_conditions",
            "counterexample_search_required",
            "keep_incompatible_routes_alive",
        ),
        (),
        "search_policy",
    )
    routes = search["initial_routes"]
    minimum = (
        MODE_PRESETS[mode]["minimum_initial_routes"]
        if mode != "MARATHON"
        else 5
    )
    if not isinstance(routes, list) or not minimum <= len(routes) <= 16:
        fail(f"{mode} requires between {minimum} and 16 initial routes")
    normalized_routes: List[Dict[str, str]] = []
    route_ids: List[str] = []
    mechanism_families: List[str] = []
    for index, raw_route in enumerate(routes):
        route = require_exact_keys(
            raw_route,
            ("route_id", "mechanism_family", "mechanism"),
            (),
            f"search_policy.initial_routes[{index}]",
        )
        route_id = require_id(
            route["route_id"], f"search_policy.initial_routes[{index}].route_id"
        )
        mechanism_family = route["mechanism_family"]
        if mechanism_family not in MECHANISM_FAMILIES:
            fail(
                f"search_policy.initial_routes[{index}].mechanism_family "
                "is not an allowed structural family"
            )
        mechanism = require_text(
            route["mechanism"],
            f"search_policy.initial_routes[{index}].mechanism",
            single_line=True,
            maximum_bytes=256,
        )
        route_ids.append(route_id)
        mechanism_families.append(mechanism_family)
        normalized_routes.append(
            {
                "route_id": route_id,
                "mechanism_family": mechanism_family,
                "mechanism": mechanism,
            }
        )
    if len(set(route_ids)) != len(route_ids):
        fail("initial route IDs must be distinct")
    if len(set(mechanism_families)) != len(mechanism_families):
        fail("initial routes must declare distinct structural mechanism families")
    counterexample = require_bool(
        search["counterexample_search_required"],
        "search_policy.counterexample_search_required",
    )
    incompatible = require_bool(
        search["keep_incompatible_routes_alive"],
        "search_policy.keep_incompatible_routes_alive",
    )
    if not counterexample or not incompatible:
        fail("counterexample search and incompatible-route preservation are mandatory")
    return {
        "initial_routes": normalized_routes,
        "stopping_conditions": require_text_list(
            search["stopping_conditions"],
            "search_policy.stopping_conditions",
            minimum=1,
            maximum=32,
        ),
        "counterexample_search_required": True,
        "keep_incompatible_routes_alive": True,
    }


def load_plan(root: Path, goal_id: str) -> Dict[str, Any]:
    require_id(goal_id, "goal_id")
    path = safe_existing_path(
        root,
        f"research/deep_goals/{goal_id}/approved_goal.json",
        "approved goal",
        kind="file",
    )
    plan = load_record(path, "approved goal")
    validate_plan_object(root, plan)
    return plan


def normalize_authorization(value: Any, mode: str) -> Dict[str, Any]:
    authorization = require_exact_keys(
        value,
        ("kind", "approved_at", "approved_by", "approved_total_seconds"),
        (),
        "authorization",
    )
    kind = authorization["kind"]
    total = authorization["approved_total_seconds"]
    if mode == "MARATHON":
        if kind != "EXPLICIT_MARATHON" or total not in MARATHON_TOTALS:
            fail("MARATHON requires separate authorization for exactly 12, 24, or 32 hours")
    else:
        if kind != "CAMPAIGN_APPROVAL" or total is not None:
            fail(f"{mode} requires CAMPAIGN_APPROVAL with a null cumulative total")
    return {
        "kind": kind,
        "approved_at": require_iso(authorization["approved_at"], "authorization.approved_at"),
        "approved_by": require_text_list(
            authorization["approved_by"],
            "authorization.approved_by",
            minimum=1,
            maximum=16,
            single_line=True,
        ),
        "approved_total_seconds": total,
    }


def normalize_marathon(
    value: Any,
    root: Path,
    goal_id: str,
    mode: str,
    authorization: Dict[str, Any],
    target: Dict[str, Any],
    created_at: str,
    *,
    check_paths: bool,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    if mode != "MARATHON":
        if value is not None:
            fail(f"{mode} requires marathon=null")
        return None, {"parent_candidate_appeared": False}
    marathon = require_exact_keys(
        value,
        (
            "campaign_id",
            "stage_index",
            "parent_goal_id",
            "parent_plan_sha256",
            "parent_record_path",
            "parent_record_sha256",
        ),
        (),
        "marathon",
    )
    campaign_id = require_id(marathon["campaign_id"], "marathon.campaign_id")
    stage_index = require_int(marathon["stage_index"], "marathon.stage_index", minimum=1)
    total = authorization["approved_total_seconds"]
    stage_count = (total + MARATHON_STAGE_CAP - 1) // MARATHON_STAGE_CAP
    if stage_index > stage_count:
        fail("marathon.stage_index exceeds the duration-specific stage count")
    parent_goal_id = require_id(marathon["parent_goal_id"], "marathon.parent_goal_id")
    if parent_goal_id == goal_id:
        fail("a marathon stage cannot bind itself as parent")
    parent_plan_sha = require_sha(
        marathon["parent_plan_sha256"], "marathon.parent_plan_sha256"
    )
    parent_record_sha = require_sha(
        marathon["parent_record_sha256"], "marathon.parent_record_sha256"
    )
    parent_record_path = "/".join(
        relative_parts(marathon["parent_record_path"], "marathon.parent_record_path")
    )
    outcome_prefix = f"research/deep_goals/{parent_goal_id}/outcomes/"
    if not parent_record_path.startswith(outcome_prefix):
        fail("marathon parent record must be an immutable outcome of the bound parent")
    parent_candidate_appeared = False
    if check_paths:
        parent_plan = load_plan(root, parent_goal_id)
        if parent_plan["plan_sha256"] != parent_plan_sha:
            fail("marathon.parent_plan_sha256 does not match the parent plan")
        if parent_plan["target"] != target:
            fail(
                "MARATHON target, acceptance criteria, anti-targets, and traps "
                "must exactly match the parent plan"
            )
        parent_record = safe_existing_path(
            root, parent_record_path, "marathon.parent_record_path", kind="file"
        )
        if sha256_file(parent_record) != parent_record_sha:
            fail("marathon.parent_record_sha256 does not match the parent record")
        parent_outcome = load_record(parent_record, "marathon parent outcome")
        validate_outcome_object(root, parent_plan, parent_outcome)
        if (
            parent_record_path
            != f"{outcome_prefix}{parent_outcome['outcome_id']}.json"
        ):
            fail("marathon parent outcome path must be canonical")
        parent_summary = summarize_goal_outcomes(root, parent_plan)
        if (
            parent_summary["latest_outcome_id"] != parent_outcome["outcome_id"]
            or parent_summary["latest_outcome_sha256"]
            != parent_outcome["outcome_sha256"]
        ):
            fail("MARATHON must bind the latest immutable parent outcome")
        if created_at < parent_outcome["recorded_at"]:
            fail("MARATHON created_at must not precede its parent outcome")
        parent_candidate_appeared = parent_summary["candidate_appeared"]
        if stage_index == 1:
            if parent_plan["mode"] != "DEEP":
                fail("the first MARATHON stage must bind a DEEP parent")
        else:
            parent_marathon = parent_plan.get("marathon")
            if (
                parent_plan["mode"] != "MARATHON"
                or not isinstance(parent_marathon, dict)
                or parent_marathon["stage_index"] != stage_index - 1
                or parent_marathon["campaign_id"] != campaign_id
                or parent_plan["authorization"]["approved_total_seconds"] != total
            ):
                fail("later MARATHON stages must bind the immediately preceding stage")
    return (
        {
            "campaign_id": campaign_id,
            "stage_index": stage_index,
            "parent_goal_id": parent_goal_id,
            "parent_plan_sha256": parent_plan_sha,
            "parent_record_path": parent_record_path,
            "parent_record_sha256": parent_record_sha,
        },
        {"parent_candidate_appeared": parent_candidate_appeared},
    )


def normalize_goal_request(
    value: Any,
    root: Path,
    *,
    check_paths: bool = True,
) -> Dict[str, Any]:
    request = require_exact_keys(
        value,
        (
            "schema_version",
            "goal_id",
            "mode",
            "created_at",
            "target",
            "source_policy",
            "search_policy",
            "authorization",
            "marathon",
        ),
        (),
        "goal request",
    )
    if request["schema_version"] != SCHEMA_VERSION:
        fail("goal request schema_version must be 1")
    goal_id = require_id(request["goal_id"], "goal_id")
    mode = request["mode"]
    if mode not in (*MODE_PRESETS.keys(), "MARATHON"):
        fail("mode must be SCOUT, TRIAL, DEEP, or MARATHON")
    created_at = require_iso(request["created_at"], "created_at")
    authorization = normalize_authorization(request["authorization"], mode)
    if created_at < authorization["approved_at"]:
        fail("created_at must not precede authorization.approved_at")
    target = normalize_target(
        request["target"], mode, root, check_paths=check_paths
    )
    marathon, marathon_context = normalize_marathon(
        request["marathon"],
        root,
        goal_id,
        mode,
        authorization,
        target,
        created_at,
        check_paths=check_paths,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": goal_id,
        "mode": mode,
        "created_at": created_at,
        "target": target,
        "source_policy": normalize_sources(
            request["source_policy"], root, mode, check_paths=check_paths
        ),
        "search_policy": normalize_search(request["search_policy"], mode),
        "authorization": authorization,
        "marathon": marathon,
        "_marathon_context": marathon_context,
    }


def derived_budget(request: Dict[str, Any]) -> Dict[str, Any]:
    mode = request["mode"]
    if mode == "MARATHON":
        total = request["authorization"]["approved_total_seconds"]
        stage_index = request["marathon"]["stage_index"]
        cumulative_before = (stage_index - 1) * MARATHON_STAGE_CAP
        wall_cap = min(MARATHON_STAGE_CAP, total - cumulative_before)
        target_cap = 1
        minimum_routes = 5
        orchestration = "FULL"
    else:
        preset = MODE_PRESETS[mode]
        total = None
        cumulative_before = 0
        wall_cap = preset["wall_time_cap_seconds"]
        target_cap = preset["target_cap"]
        minimum_routes = preset["minimum_initial_routes"]
        orchestration = preset["orchestration"]
    return {
        "stage_wall_time_cap_seconds": wall_cap,
        "approved_cumulative_total_seconds": total,
        "cumulative_seconds_before_stage": cumulative_before,
        "target_cap": target_cap,
        "minimum_initial_routes": minimum_routes,
        "orchestration": orchestration,
        "outer_runner_required_for_hard_timeout": True,
        "verification_reserve": {
            "pre_candidate_percent_range": [15, 20],
            "post_candidate_percent_range": [30, 40],
            "switch_trigger": "AUDIT_WORTHY_MATHEMATICAL_CANDIDATE",
            "inherited_candidate_appeared": request["_marathon_context"][
                "parent_candidate_appeared"
            ],
        },
    }


def build_plan(request: Dict[str, Any], root: Path) -> Dict[str, Any]:
    request_payload = {
        key: request[key]
        for key in (
            "schema_version",
            "goal_id",
            "mode",
            "created_at",
            "target",
            "source_policy",
            "search_policy",
            "authorization",
            "marathon",
        )
    }
    plan = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "goal_id": request["goal_id"],
        "mode": request["mode"],
        "created_at": request["created_at"],
        "target": request["target"],
        "source_policy": request["source_policy"],
        "search_policy": request["search_policy"],
        "authorization": request["authorization"],
        "marathon": request["marathon"],
        "budget": derived_budget(request),
        "target_binding": (
            None
            if request["target"]["artifact_path"] is None
            else bind_files(
                root,
                [request["target"]["artifact_path"]],
                "target binding",
            )[0]
        ),
        "source_bindings": bind_files(
            root,
            request["source_policy"]["allowed_source_paths"],
            "source binding",
        ),
        "input_sha256": sha256_bytes(canonical_bytes(request_payload)),
    }
    plan["plan_sha256"] = sha256_bytes(canonical_bytes(plan))
    return plan


def validate_plan_object(root: Path, plan: Dict[str, Any]) -> None:
    require_exact_keys(
        plan,
        (
            "schema_version",
            "protocol_version",
            "goal_id",
            "mode",
            "created_at",
            "target",
            "source_policy",
            "search_policy",
            "authorization",
            "marathon",
            "budget",
            "target_binding",
            "source_bindings",
            "input_sha256",
            "plan_sha256",
        ),
        (),
        "approved goal",
    )
    if plan["protocol_version"] != PROTOCOL_VERSION:
        fail("approved goal protocol_version must be 1")
    require_sha(plan["input_sha256"], "input_sha256")
    require_sha(plan["plan_sha256"], "plan_sha256")
    request = {
        key: plan[key]
        for key in (
            "schema_version",
            "goal_id",
            "mode",
            "created_at",
            "target",
            "source_policy",
            "search_policy",
            "authorization",
            "marathon",
        )
    }
    normalized = normalize_goal_request(request, root, check_paths=True)
    expected = build_plan(normalized, root)
    if plan != expected:
        fail("approved goal has drifted from its canonical request, budget, or digest")


def prepare(root: Path, input_relative: str) -> Dict[str, Any]:
    raw_request = load_input(root, input_relative, "goal request")
    request = normalize_goal_request(raw_request, root)
    proposed = build_plan(request, root)
    state_root = safe_existing_path(
        root, "research/deep_goals", "deep goal state root", kind="dir"
    )
    with OperationLock(state_root / ".operation.lock"):
        recover_abandoned_prepares(state_root)
        locked_request = normalize_goal_request(raw_request, root)
        locked_proposed = build_plan(locked_request, root)
        if locked_proposed != proposed:
            fail(
                "goal dependencies drifted between preflight and the locked "
                "publication check"
            )
        request = locked_request
        proposed = locked_proposed
        ensure_unique_marathon_stage(root, proposed)
        goal_dir = state_root / request["goal_id"]
        plan_path = goal_dir / "approved_goal.json"
        if goal_dir.exists() or goal_dir.is_symlink():
            if goal_dir.is_symlink() or not stat.S_ISDIR(goal_dir.lstat().st_mode):
                fail(f"goal path is not a safe directory: {goal_dir}")
            existing = load_plan(root, request["goal_id"])
            if existing != proposed:
                fail(f"goal ID {request['goal_id']} already has a different immutable plan")
            return {
                "status": "EXISTS_IDENTICAL",
                "goal_id": request["goal_id"],
                "plan_path": f"research/deep_goals/{request['goal_id']}/approved_goal.json",
                "plan_sha256": existing["plan_sha256"],
            }
        staging_path = Path(
            tempfile.mkdtemp(prefix=".prepare-", dir=str(state_root))
        )
        try:
            (staging_path / "outcomes").mkdir(mode=0o755)
            write_immutable(staging_path / "approved_goal.json", proposed)
            os.chmod(staging_path, 0o755)
            fsync_directory(staging_path)
            os.rename(str(staging_path), str(goal_dir))
            fsync_directory(state_root)
        except Exception:
            if staging_path.exists():
                remove_abandoned_prepare_directory(staging_path)
            raise
        return {
            "status": "PREPARED",
            "goal_id": request["goal_id"],
            "plan_path": f"research/deep_goals/{request['goal_id']}/approved_goal.json",
            "plan_sha256": proposed["plan_sha256"],
        }


def normalize_nullable_tokens(value: Any, label: str) -> Optional[int]:
    if value is None:
        return None
    return require_int(value, label, minimum=0)


def normalize_outcome_request(
    value: Any,
    root: Path,
    plan: Dict[str, Any],
    *,
    check_paths: bool = True,
) -> Dict[str, Any]:
    outcome = require_exact_keys(
        value,
        (
            "schema_version",
            "goal_id",
            "plan_sha256",
            "outcome_id",
            "recorded_at",
            "outcome_class",
            "strict_uncertainty_reduction",
            "semantic_delta",
            "verification",
            "compute",
        ),
        (),
        "outcome input",
    )
    if outcome["schema_version"] != SCHEMA_VERSION:
        fail("outcome schema_version must be 1")
    goal_id = require_id(outcome["goal_id"], "outcome.goal_id")
    if goal_id != plan["goal_id"]:
        fail("outcome.goal_id does not match the approved plan")
    plan_sha = require_sha(outcome["plan_sha256"], "outcome.plan_sha256")
    if plan_sha != plan["plan_sha256"]:
        fail("outcome.plan_sha256 does not match the approved plan")
    outcome_id = require_id(outcome["outcome_id"], "outcome.outcome_id")
    recorded_at = require_iso(outcome["recorded_at"], "outcome.recorded_at")
    if recorded_at < plan["created_at"]:
        fail("outcome.recorded_at must not precede the plan")
    outcome_class = outcome["outcome_class"]
    if outcome_class not in OUTCOME_CLASSES:
        fail("outcome.outcome_class is invalid")
    if plan["mode"] == "SCOUT" and outcome_class not in (
        "CHECKED_COUNTEREXAMPLE",
        "DECISIVE_BARRIER",
        "NO_STRICT_REDUCTION",
    ):
        fail(
            "SCOUT is qualification-only and permits only a checked "
            "counterexample, decisive barrier, or no strict reduction"
        )
    strict = require_bool(
        outcome["strict_uncertainty_reduction"], "outcome.strict_uncertainty_reduction"
    )
    delta = require_exact_keys(
        outcome["semantic_delta"],
        ("discharged", "falsified", "narrowed", "left_open"),
        (),
        "outcome.semantic_delta",
    )
    normalized_delta = {
        key: require_text_list(
            delta[key], f"outcome.semantic_delta.{key}", minimum=0, maximum=64
        )
        for key in ("discharged", "falsified", "narrowed", "left_open")
    }
    verification = require_exact_keys(
        outcome["verification"],
        (
            "evidence_paths",
            "generator_ids",
            "material_reviser_ids",
            "verifier_ids",
            "decisive_verifier_independent",
            "independence_level",
            "kernel_state_path",
            "remaining_highest_gap",
        ),
        (),
        "outcome.verification",
    )
    raw_evidence = verification["evidence_paths"]
    if not isinstance(raw_evidence, list) or len(raw_evidence) > 128:
        fail("outcome.verification.evidence_paths must contain at most 128 paths")
    evidence: List[str] = []
    for index, raw_path in enumerate(raw_evidence):
        path = "/".join(
            relative_parts(raw_path, f"outcome.verification.evidence_paths[{index}]")
        )
        if check_paths:
            safe_existing_path(
                root,
                path,
                f"outcome.verification.evidence_paths[{index}]",
                kind="file",
            )
        evidence.append(path)
    if len(set(evidence)) != len(evidence):
        fail("outcome.verification.evidence_paths must not contain duplicates")
    generators = require_text_list(
        verification["generator_ids"],
        "outcome.verification.generator_ids",
        minimum=0,
        maximum=32,
        single_line=True,
    )
    revisers = require_text_list(
        verification["material_reviser_ids"],
        "outcome.verification.material_reviser_ids",
        minimum=0,
        maximum=32,
        single_line=True,
    )
    verifiers = require_text_list(
        verification["verifier_ids"],
        "outcome.verification.verifier_ids",
        minimum=0,
        maximum=32,
        single_line=True,
    )
    independent = require_bool(
        verification["decisive_verifier_independent"],
        "outcome.verification.decisive_verifier_independent",
    )
    independence_level = verification["independence_level"]
    if independence_level not in (None, "I2", "I3"):
        fail("outcome.verification.independence_level must be null, I2, or I3")
    kernel_state_raw = verification["kernel_state_path"]
    kernel_state_path = (
        None
        if kernel_state_raw is None
        else "/".join(
            relative_parts(
                kernel_state_raw, "outcome.verification.kernel_state_path"
            )
        )
    )
    remaining_gap_raw = verification["remaining_highest_gap"]
    remaining_gap = (
        None
        if remaining_gap_raw is None
        else require_text(
            remaining_gap_raw, "outcome.verification.remaining_highest_gap"
        )
    )
    if outcome_class in STRICT_OUTCOMES:
        strict_delta = (
            normalized_delta["discharged"]
            + normalized_delta["falsified"]
            + normalized_delta["narrowed"]
        )
        if (
            not strict
            or not strict_delta
            or not evidence
            or not generators
            or not verifiers
            or not independent
            or independence_level not in ("I2", "I3")
        ):
            fail(
                "a strict-reduction class requires an exact delta, evidence, "
                "generator lineage, and an I2/I3 independent decisive verifier"
            )
        lineage_ids = set(generators) | set(revisers)
        if lineage_ids & set(verifiers):
            fail(
                "decisive verifier IDs must be disjoint from generator and "
                "material-reviser IDs"
            )
        if outcome_class == "VERIFIED_PROOF":
            if (
                not normalized_delta["discharged"]
                or normalized_delta["falsified"]
                or normalized_delta["narrowed"]
                or remaining_gap is not None
            ):
                fail(
                    "VERIFIED_PROOF must discharge an exact obligation, must not "
                    "merely narrow it, and requires remaining_highest_gap=null"
                )
        elif outcome_class == "VERIFIED_REFUTATION":
            if (
                not normalized_delta["falsified"]
                or normalized_delta["discharged"]
                or normalized_delta["narrowed"]
                or remaining_gap is not None
            ):
                fail(
                    "VERIFIED_REFUTATION must falsify an exact obligation, must not "
                    "merely narrow it, and requires remaining_highest_gap=null"
                )
        elif outcome_class == "EXACT_LEMMA" and not normalized_delta["discharged"]:
            fail("EXACT_LEMMA must discharge at least one exact lemma obligation")
        elif (
            outcome_class == "CHECKED_COUNTEREXAMPLE"
            and not normalized_delta["falsified"]
        ):
            fail("CHECKED_COUNTEREXAMPLE must falsify at least one exact claim")
        elif outcome_class == "DECISIVE_BARRIER" and not (
            normalized_delta["narrowed"] or normalized_delta["falsified"]
        ):
            fail("DECISIVE_BARRIER must narrow or falsify an exact route or region")
        if outcome_class in ("VERIFIED_PROOF", "VERIFIED_REFUTATION"):
            if independence_level != "I3" or kernel_state_path is None:
                fail(
                    "VERIFIED_PROOF and VERIFIED_REFUTATION require an I3 "
                    "kernel_state_path validated by the laboratory kernel"
                )
            if kernel_state_path not in evidence:
                fail("kernel_state_path must also appear in evidence_paths")
            if check_paths:
                state_path = safe_existing_path(
                    root,
                    kernel_state_path,
                    "outcome.verification.kernel_state_path",
                    kind="file",
                )
                validator = safe_existing_path(
                    root,
                    "scripts/validate_proof_search.py",
                    "kernel proof-search validator",
                    kind="file",
                )
                try:
                    completed = subprocess.run(
                        [
                            sys.executable,
                            str(validator),
                            str(state_path),
                            "--quiet",
                        ],
                        cwd=str(root),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=120,
                        check=False,
                    )
                except subprocess.TimeoutExpired:
                    fail("kernel proof-search validation exceeded 120 seconds")
                if completed.returncode != 0:
                    fail(
                        "kernel_state_path did not pass the laboratory's "
                        "proof-search validator"
                    )
                kernel_state, _ = read_json_file(
                    state_path, "kernel proof-search state"
                )
                expected_status = (
                    "VERIFIED_PROOF"
                    if outcome_class == "VERIFIED_PROOF"
                    else "VERIFIED_COUNTEREXAMPLE"
                )
                if kernel_state.get("global_status") != expected_status:
                    fail(
                        f"{outcome_class} requires kernel global_status="
                        f"{expected_status}"
                    )
                kernel_target = kernel_state.get("target_binding")
                if (
                    not isinstance(plan.get("target_binding"), dict)
                    or
                    not isinstance(kernel_target, dict)
                    or kernel_state.get("problem_id")
                    != plan["target"]["problem_id"]
                    or kernel_target.get("target_id")
                    != plan["target"]["target_id"]
                    or kernel_target.get("artifact")
                    != plan["target_binding"]["path"]
                    or kernel_target.get("artifact_sha256")
                    != plan["target_binding"]["sha256"]
                ):
                    fail(
                        "kernel proof-search state must bind the same root-relative "
                        "target artifact and digest as the deep goal"
                    )
                kernel_lineage = kernel_state.get("candidate_lineage")
                kernel_verifier = kernel_state.get("independent_verifier")
                kernel_generators = (
                    kernel_lineage.get("originating_run_ids")
                    if isinstance(kernel_lineage, dict)
                    else None
                )
                kernel_revisers = (
                    kernel_lineage.get("material_repair_run_ids")
                    if isinstance(kernel_lineage, dict)
                    else None
                )
                if (
                    not isinstance(kernel_lineage, dict)
                    or not isinstance(kernel_verifier, dict)
                    or not isinstance(kernel_generators, list)
                    or not isinstance(kernel_revisers, list)
                    or set(kernel_generators)
                    != set(generators)
                    or set(kernel_revisers)
                    != set(revisers)
                    or verifiers != [kernel_verifier.get("id")]
                    or kernel_verifier.get("independence_level") != "I3"
                    or kernel_verifier.get("independent_of_candidate") is not True
                    or kernel_verifier.get("completed") is not True
                    or kernel_verifier.get("verdict") not in ("PASS", "VERIFIED")
                ):
                    fail(
                        "VERIFIED outcome lineage and decisive verifier must "
                        "exactly match the kernel I3 state"
                    )
    else:
        if (
            strict
            or any(normalized_delta.values())
            or generators
            or revisers
            or verifiers
            or independent
            or independence_level is not None
            or kernel_state_path is not None
        ):
            fail("NO_STRICT_REDUCTION requires false and an entirely empty semantic delta")
    compute = require_exact_keys(
        outcome["compute"],
        (
            "elapsed_wall_seconds",
            "verification_wall_seconds",
            "model_attempts",
            "route_attempts",
            "route_ids_attempted",
            "verifier_attempts",
            "candidate_appeared",
            "usage_source",
            "input_tokens",
            "output_tokens",
        ),
        (),
        "outcome.compute",
    )
    elapsed = require_int(
        compute["elapsed_wall_seconds"],
        "outcome.compute.elapsed_wall_seconds",
        minimum=1,
        maximum=plan["budget"]["stage_wall_time_cap_seconds"],
    )
    verification_seconds = require_int(
        compute["verification_wall_seconds"],
        "outcome.compute.verification_wall_seconds",
        minimum=0,
        maximum=elapsed,
    )
    candidate_appeared = require_bool(
        compute["candidate_appeared"], "outcome.compute.candidate_appeared"
    )
    inherited_candidate = plan["budget"]["verification_reserve"][
        "inherited_candidate_appeared"
    ]
    if inherited_candidate and not candidate_appeared:
        fail(
            "candidate_appeared cannot reset across a MARATHON continuation "
            "after an audit-worthy parent candidate"
        )
    if outcome_class in STRICT_OUTCOMES and not candidate_appeared:
        fail(
            "every strict-reduction outcome requires candidate_appeared=true; "
            "the field means any audit-worthy mathematical candidate"
        )
    lower, upper = (
        plan["budget"]["verification_reserve"]["post_candidate_percent_range"]
        if candidate_appeared
        else plan["budget"]["verification_reserve"]["pre_candidate_percent_range"]
    )
    if not lower * elapsed <= 100 * verification_seconds <= upper * elapsed:
        fail(
            f"verification time must be {lower}-{upper}% of elapsed time "
            f"for candidate_appeared={candidate_appeared}"
        )
    usage_source = compute["usage_source"]
    if usage_source not in USAGE_SOURCES:
        fail("outcome.compute.usage_source is invalid")
    input_tokens = normalize_nullable_tokens(
        compute["input_tokens"], "outcome.compute.input_tokens"
    )
    output_tokens = normalize_nullable_tokens(
        compute["output_tokens"], "outcome.compute.output_tokens"
    )
    if usage_source == "OUTER_RUNNER_REPORTED" and (
        input_tokens is None or output_tokens is None
    ):
        fail("OUTER_RUNNER_REPORTED usage requires both token counts")
    if usage_source == "UNAVAILABLE" and (
        input_tokens is not None or output_tokens is not None
    ):
        fail("UNAVAILABLE usage requires null token counts")
    if (input_tokens is None) != (output_tokens is None):
        fail("token counts must both be present or both be null")
    model_attempts = require_int(
        compute["model_attempts"], "outcome.compute.model_attempts"
    )
    route_attempts = require_int(
        compute["route_attempts"], "outcome.compute.route_attempts"
    )
    route_ids_attempted = require_text_list(
        compute["route_ids_attempted"],
        "outcome.compute.route_ids_attempted",
        minimum=0,
        maximum=16,
        single_line=True,
    )
    planned_route_ids = {
        route["route_id"] for route in plan["search_policy"]["initial_routes"]
    }
    if not set(route_ids_attempted) <= planned_route_ids:
        fail("outcome.compute.route_ids_attempted contains an unplanned route ID")
    if route_attempts < len(route_ids_attempted):
        fail("route_attempts cannot be smaller than the distinct attempted route IDs")
    verifier_attempts = require_int(
        compute["verifier_attempts"], "outcome.compute.verifier_attempts"
    )
    if outcome_class in STRICT_OUTCOMES and (
        model_attempts < 1
        or route_attempts < 1
        or not route_ids_attempted
        or verifier_attempts < 1
    ):
        fail(
            "a strict-reduction outcome requires at least one model, route, "
            "and verifier attempt"
        )
    normalized_compute = {
        "elapsed_wall_seconds": elapsed,
        "verification_wall_seconds": verification_seconds,
        "model_attempts": model_attempts,
        "route_attempts": route_attempts,
        "route_ids_attempted": route_ids_attempted,
        "verifier_attempts": verifier_attempts,
        "candidate_appeared": candidate_appeared,
        "usage_source": usage_source,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": goal_id,
        "plan_sha256": plan_sha,
        "outcome_id": outcome_id,
        "recorded_at": recorded_at,
        "outcome_class": outcome_class,
        "strict_uncertainty_reduction": strict,
        "semantic_delta": normalized_delta,
        "verification": {
            "evidence_paths": evidence,
            "generator_ids": generators,
            "material_reviser_ids": revisers,
            "verifier_ids": verifiers,
            "decisive_verifier_independent": independent,
            "independence_level": independence_level,
            "kernel_state_path": kernel_state_path,
            "remaining_highest_gap": remaining_gap,
        },
        "compute": normalized_compute,
    }


def usage_assessment(compute: Dict[str, Any]) -> str:
    if compute["input_tokens"] is None or compute["output_tokens"] is None:
        return "UNSCORED_MISSING_USAGE"
    if compute["usage_source"] == "OUTER_RUNNER_REPORTED":
        return "UNAUTHENTICATED_OUTER_RUNNER_REPORT"
    if compute["usage_source"] == "USER_RECORDED":
        return "UNTRUSTED_SELF_REPORT"
    return "UNSCORED_MISSING_USAGE"


def build_outcome_record(
    root: Path,
    plan: Dict[str, Any],
    request: Dict[str, Any],
    *,
    sequence_index: int,
    previous_outcome_sha256: str,
) -> Dict[str, Any]:
    if sequence_index < 0:
        fail("outcome sequence_index must be non-negative")
    require_sha(previous_outcome_sha256, "previous_outcome_sha256")
    record = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        **request,
        "mode": plan["mode"],
        "sequence_index": sequence_index,
        "previous_outcome_sha256": previous_outcome_sha256,
        "evidence_bindings": bind_files(
            root,
            request["verification"]["evidence_paths"],
            "outcome evidence binding",
        ),
        "usage_assessment": usage_assessment(request["compute"]),
        "input_sha256": sha256_bytes(canonical_bytes(request)),
    }
    record["outcome_sha256"] = sha256_bytes(canonical_bytes(record))
    return record


def validate_outcome_object(
    root: Path, plan: Dict[str, Any], record: Dict[str, Any]
) -> None:
    require_exact_keys(
        record,
        (
            "schema_version",
            "protocol_version",
            "goal_id",
            "plan_sha256",
            "outcome_id",
            "recorded_at",
            "outcome_class",
            "strict_uncertainty_reduction",
            "semantic_delta",
            "verification",
            "compute",
            "mode",
            "sequence_index",
            "previous_outcome_sha256",
            "evidence_bindings",
            "usage_assessment",
            "input_sha256",
            "outcome_sha256",
        ),
        (),
        "outcome record",
    )
    if record["protocol_version"] != PROTOCOL_VERSION or record["mode"] != plan["mode"]:
        fail("outcome record protocol or mode has drifted")
    require_sha(record["input_sha256"], "outcome.input_sha256")
    require_sha(record["outcome_sha256"], "outcome.outcome_sha256")
    sequence_index = require_int(
        record["sequence_index"], "outcome.sequence_index", minimum=1
    )
    previous_outcome_sha256 = require_sha(
        record["previous_outcome_sha256"],
        "outcome.previous_outcome_sha256",
    )
    request_keys = (
        "schema_version",
        "goal_id",
        "plan_sha256",
        "outcome_id",
        "recorded_at",
        "outcome_class",
        "strict_uncertainty_reduction",
        "semantic_delta",
        "verification",
        "compute",
    )
    request = {key: record[key] for key in request_keys}
    normalized = normalize_outcome_request(request, root, plan, check_paths=True)
    expected = build_outcome_record(
        root,
        plan,
        normalized,
        sequence_index=sequence_index,
        previous_outcome_sha256=previous_outcome_sha256,
    )
    if record != expected:
        fail("outcome record has drifted from its canonical input or digest")


def validate_outcome_sequence(
    records: Sequence[Dict[str, Any]],
    stage_cap_seconds: int,
    *,
    candidate_seen_initially: bool = False,
) -> Tuple[List[Dict[str, Any]], int, bool]:
    ordered = sorted(records, key=lambda record: record["sequence_index"])
    elapsed_total = 0
    candidate_seen = candidate_seen_initially
    previous_digest = "0" * 64
    previous_key: Optional[Tuple[str, str]] = None
    for expected_index, record in enumerate(ordered, 1):
        if (
            record["sequence_index"] != expected_index
            or record["previous_outcome_sha256"] != previous_digest
        ):
            fail(
                "outcome hash chain has a sequence gap, reordering, or "
                "previous-outcome mismatch"
            )
        current_key = (record["recorded_at"], record["outcome_id"])
        if previous_key is not None and current_key <= previous_key:
            fail(
                "outcome hash-chain order must strictly increase by "
                "(recorded_at, outcome_id)"
            )
        candidate_now = record["compute"]["candidate_appeared"]
        if candidate_seen and not candidate_now:
            fail(
                "candidate_appeared is monotone within a goal and cannot reset "
                "after an audit-worthy candidate"
            )
        candidate_seen = candidate_seen or candidate_now
        elapsed_total += record["compute"]["elapsed_wall_seconds"]
        previous_digest = record["outcome_sha256"]
        previous_key = current_key
    if elapsed_total > stage_cap_seconds:
        fail(
            "cumulative outcome time exceeds the immutable stage budget; "
            "canonical individual records cannot reset it"
        )
    return ordered, elapsed_total, candidate_seen


def summarize_goal_outcomes(
    root: Path, plan: Dict[str, Any]
) -> Dict[str, Any]:
    goal_id = plan["goal_id"]
    outcomes_dir = safe_existing_path(
        root,
        f"research/deep_goals/{goal_id}/outcomes",
        "outcomes directory",
        kind="dir",
    )
    outcome_records: List[Dict[str, Any]] = []
    for path in sorted(outcomes_dir.iterdir()):
        if not path.name.endswith(".json") or not ID_RE.fullmatch(path.stem):
            fail(f"invalid outcome filename: {path.name}")
        record = load_record(path, "outcome record")
        if record.get("outcome_id") != path.stem:
            fail(f"outcome filename does not match outcome_id: {path.name}")
        validate_outcome_object(root, plan, record)
        outcome_records.append(record)
    ordered, elapsed_total, candidate_seen = validate_outcome_sequence(
        outcome_records,
        plan["budget"]["stage_wall_time_cap_seconds"],
        candidate_seen_initially=plan["budget"]["verification_reserve"][
            "inherited_candidate_appeared"
        ],
    )
    return {
        "outcome_count": len(ordered),
        "elapsed_wall_seconds_total": elapsed_total,
        "candidate_appeared": candidate_seen,
        "latest_outcome_id": (
            None if not ordered else ordered[-1]["outcome_id"]
        ),
        "latest_outcome_sha256": (
            None if not ordered else ordered[-1]["outcome_sha256"]
        ),
        "latest_outcome_recorded_at": (
            None if not ordered else ordered[-1]["recorded_at"]
        ),
    }


def ensure_goal_accepts_new_outcome(root: Path, goal_id: str) -> None:
    state_root = safe_existing_path(
        root, "research/deep_goals", "deep goal state root", kind="dir"
    )
    for path in sorted(state_root.iterdir()):
        if path.name in ("README.md", ".operation.lock", goal_id):
            continue
        if not ID_RE.fullmatch(path.name) or not stat.S_ISDIR(path.lstat().st_mode):
            fail(f"unexpected entry in deep goal state: {path.name}")
        other = load_plan(root, path.name)
        marathon = other.get("marathon")
        if (
            other["mode"] == "MARATHON"
            and isinstance(marathon, dict)
            and marathon["parent_goal_id"] == goal_id
        ):
            fail(
                f"goal {goal_id} is sealed because MARATHON goal "
                f"{other['goal_id']} already binds its latest outcome"
            )


def record_outcome(
    root: Path, goal_id: str, input_relative: str
) -> Dict[str, Any]:
    plan = load_plan(root, goal_id)
    raw_outcome = load_input(root, input_relative, "outcome input")
    request = normalize_outcome_request(
        raw_outcome, root, plan
    )
    preflight_proposed = build_outcome_record(
        root,
        plan,
        request,
        sequence_index=0,
        previous_outcome_sha256="0" * 64,
    )
    state_root = safe_existing_path(
        root, "research/deep_goals", "deep goal state root", kind="dir"
    )
    outcomes_dir = safe_existing_path(
        root,
        f"research/deep_goals/{goal_id}/outcomes",
        "outcomes directory",
        kind="dir",
    )
    with OperationLock(state_root / ".operation.lock"):
        recover_abandoned_prepares(state_root)
        locked_plan = load_plan(root, goal_id)
        if locked_plan != plan:
            fail("approved goal drifted between preflight and locked publication")
        locked_request = normalize_outcome_request(
            raw_outcome, root, locked_plan
        )
        locked_preflight = build_outcome_record(
            root,
            locked_plan,
            locked_request,
            sequence_index=0,
            previous_outcome_sha256="0" * 64,
        )
        if (
            locked_request != request
            or locked_preflight != preflight_proposed
        ):
            fail(
                "outcome evidence or dependencies drifted between preflight "
                "and the locked publication check"
            )
        plan = locked_plan
        request = locked_request
        outcomes_dir = safe_existing_path(
            root,
            f"research/deep_goals/{goal_id}/outcomes",
            "outcomes directory",
            kind="dir",
        )
        outcome_path = outcomes_dir / f"{request['outcome_id']}.json"
        if outcome_path.exists() or outcome_path.is_symlink():
            if outcome_path.is_symlink():
                fail("outcome path must not be a symlink")
            existing = load_record(outcome_path, "outcome record")
            validate_outcome_object(root, plan, existing)
            proposed = build_outcome_record(
                root,
                plan,
                request,
                sequence_index=existing["sequence_index"],
                previous_outcome_sha256=existing[
                    "previous_outcome_sha256"
                ],
            )
            if existing != proposed:
                fail(
                    f"outcome ID {request['outcome_id']} already has a different immutable record"
                )
            status = "EXISTS_IDENTICAL"
        else:
            ensure_goal_accepts_new_outcome(root, goal_id)
            existing_records: List[Dict[str, Any]] = []
            for existing_path in sorted(outcomes_dir.iterdir()):
                if (
                    not stat.S_ISREG(existing_path.lstat().st_mode)
                    or not existing_path.name.endswith(".json")
                ):
                    fail(f"invalid existing outcome entry: {existing_path.name}")
                existing_record = load_record(existing_path, "outcome record")
                validate_outcome_object(root, plan, existing_record)
                existing_records.append(existing_record)
            ordered, elapsed_before, candidate_seen = validate_outcome_sequence(
                existing_records,
                plan["budget"]["stage_wall_time_cap_seconds"],
                candidate_seen_initially=plan["budget"]["verification_reserve"][
                    "inherited_candidate_appeared"
                ],
            )
            if ordered and (
                request["recorded_at"],
                request["outcome_id"],
            ) <= (
                ordered[-1]["recorded_at"],
                ordered[-1]["outcome_id"],
            ):
                fail(
                    "a new outcome's (recorded_at, outcome_id) key must be "
                    "strictly greater than the append-only sequence"
                )
            if candidate_seen and not request["compute"]["candidate_appeared"]:
                fail(
                    "candidate_appeared is monotone within a goal and cannot reset "
                    "after an audit-worthy candidate"
                )
            elapsed_after = elapsed_before + request["compute"]["elapsed_wall_seconds"]
            if elapsed_after > plan["budget"]["stage_wall_time_cap_seconds"]:
                fail(
                    "cumulative outcome time would exceed the immutable stage budget; "
                    "a retry cannot reset elapsed time"
                )
            proposed = build_outcome_record(
                root,
                plan,
                request,
                sequence_index=len(ordered) + 1,
                previous_outcome_sha256=(
                    "0" * 64
                    if not ordered
                    else ordered[-1]["outcome_sha256"]
                ),
            )
            write_immutable(outcome_path, proposed)
            status = "RECORDED"
    return {
        "status": status,
        "goal_id": goal_id,
        "outcome_id": request["outcome_id"],
        "outcome_path": f"research/deep_goals/{goal_id}/outcomes/{request['outcome_id']}.json",
        "outcome_sha256": proposed["outcome_sha256"],
    }


def scan_safe_tree(root: Path) -> None:
    stack = [root]
    while stack:
        current = stack.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                mode = entry.stat(follow_symlinks=False).st_mode
                path = Path(entry.path)
                if stat.S_ISLNK(mode):
                    fail(f"symlink is forbidden in deep goal state: {path}")
                if stat.S_ISDIR(mode):
                    stack.append(path)
                elif not stat.S_ISREG(mode):
                    fail(f"special file is forbidden in deep goal state: {path}")


def ensure_unique_marathon_stage(root: Path, plan: Dict[str, Any]) -> None:
    if plan["mode"] != "MARATHON":
        return
    state_root = safe_existing_path(
        root, "research/deep_goals", "deep goal state root", kind="dir"
    )
    campaign_id = plan["marathon"]["campaign_id"]
    stage_index = plan["marathon"]["stage_index"]
    for path in sorted(state_root.iterdir()):
        if path.name in ("README.md", ".operation.lock", plan["goal_id"]):
            continue
        if not ID_RE.fullmatch(path.name) or not stat.S_ISDIR(path.lstat().st_mode):
            fail(f"unexpected entry in deep goal state: {path.name}")
        other = load_plan(root, path.name)
        if (
            other["mode"] == "MARATHON"
            and other["marathon"]["campaign_id"] == campaign_id
            and other["marathon"]["stage_index"] == stage_index
        ):
            fail(
                f"MARATHON campaign {campaign_id} already consumed stage {stage_index}; "
                "a retry cannot reset cumulative budget"
            )
        if (
            other["mode"] == "MARATHON"
            and other["marathon"]["parent_goal_id"]
            == plan["marathon"]["parent_goal_id"]
            and other["marathon"]["parent_record_path"]
            == plan["marathon"]["parent_record_path"]
            and other["marathon"]["parent_record_sha256"]
            == plan["marathon"]["parent_record_sha256"]
        ):
            fail(
                "a parent outcome can authorize only one MARATHON child; "
                "changing campaign_id cannot fork or reset the budget"
            )


def validate_goal(root: Path, goal_id: str) -> Dict[str, Any]:
    require_id(goal_id, "goal_id")
    goal_dir = safe_existing_path(
        root, f"research/deep_goals/{goal_id}", "goal directory", kind="dir"
    )
    scan_safe_tree(goal_dir)
    allowed = {"approved_goal.json", "outcomes"}
    extras = sorted(path.name for path in goal_dir.iterdir() if path.name not in allowed)
    if extras:
        fail(f"unexpected entries in goal directory {goal_id}: {extras}")
    plan = load_plan(root, goal_id)
    ensure_unique_marathon_stage(root, plan)
    outcome_summary = summarize_goal_outcomes(root, plan)
    return {
        "goal_id": goal_id,
        "mode": plan["mode"],
        "plan_sha256": plan["plan_sha256"],
        **outcome_summary,
    }


def validate_all(root: Path, goal_id: Optional[str]) -> Dict[str, Any]:
    state_root = safe_existing_path(
        root, "research/deep_goals", "deep goal state root", kind="dir"
    )
    scan_safe_tree(state_root)
    if goal_id is not None:
        goals = [validate_goal(root, goal_id)]
    else:
        goals = []
        for path in sorted(state_root.iterdir()):
            if path.name in ("README.md", ".operation.lock"):
                if not stat.S_ISREG(path.lstat().st_mode):
                    fail(
                        f"research/deep_goals/{path.name} must be a regular file"
                    )
                continue
            if not stat.S_ISDIR(path.lstat().st_mode) or not ID_RE.fullmatch(path.name):
                fail(f"unexpected entry in deep goal state: {path.name}")
            goals.append(validate_goal(root, path.name))
    return {"status": "VALID", "goal_count": len(goals), "goals": goals}


def status(root: Path, goal_id: str) -> Dict[str, Any]:
    summary = validate_goal(root, goal_id)
    plan = load_plan(root, goal_id)
    outcomes_dir = safe_existing_path(
        root, f"research/deep_goals/{goal_id}/outcomes", "outcomes directory", kind="dir"
    )
    records = [
        load_record(path, "outcome record")
        for path in sorted(outcomes_dir.glob("*.json"))
    ]
    records.sort(key=lambda item: (item["recorded_at"], item["outcome_id"]))
    latest = None
    if records:
        record = records[-1]
        token_usage = None
        if record["compute"]["input_tokens"] is not None:
            token_usage = {
                "input_tokens": record["compute"]["input_tokens"],
                "output_tokens": record["compute"]["output_tokens"],
            }
        latest = {
            "outcome_id": record["outcome_id"],
            "outcome_class": record["outcome_class"],
            "strict_uncertainty_reduction": record["strict_uncertainty_reduction"],
            "elapsed_wall_seconds": record["compute"]["elapsed_wall_seconds"],
            "usage_source": record["compute"]["usage_source"],
            "usage_assessment": record["usage_assessment"],
            "token_usage": token_usage,
            "outcome_sha256": record["outcome_sha256"],
        }
    return {
        "status": "VALID",
        **summary,
        "stage_wall_time_cap_seconds": plan["budget"]["stage_wall_time_cap_seconds"],
        "latest_outcome": latest,
        "theorem_status_changed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="generated laboratory root")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare", help="freeze an immutable goal plan")
    prepare_parser.add_argument("--input", required=True, help="root-relative JSON request")
    outcome_parser = commands.add_parser(
        "record-outcome", help="append an immutable outcome vector"
    )
    outcome_parser.add_argument("--goal-id", required=True)
    outcome_parser.add_argument("--input", required=True, help="root-relative JSON input")
    status_parser = commands.add_parser("status", help="show a bounded goal summary")
    status_parser.add_argument("--goal-id", required=True)
    validate_parser = commands.add_parser("validate", help="validate immutable state")
    validate_parser.add_argument("--goal-id")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        root = ensure_root(arguments.root)
        if arguments.command == "prepare":
            result = prepare(root, arguments.input)
        elif arguments.command == "record-outcome":
            result = record_outcome(root, arguments.goal_id, arguments.input)
        elif arguments.command == "status":
            result = status(root, arguments.goal_id)
        else:
            result = validate_all(root, arguments.goal_id)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except (DeepGoalError, OSError) as exc:
        print(f"deep-research-goal: ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
