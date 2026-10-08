#!/usr/bin/env python3
"""Append-only coordination records for a small mathematical research team.

The module deliberately keeps research content below ``collaboration/`` and
publishes only a bounded, content-free summary for the local Control Room.
JSON is used for typed records (including files with a ``.yaml`` suffix in the
rest of the laboratory) so Python 3.9's standard library is sufficient.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
MEMBER_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
HANDLE_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")

WORK_ITEM_TYPES = {
    "LITERATURE",
    "PROOF",
    "COUNTEREXAMPLE",
    "COMPUTATION",
    "FORMALIZATION",
    "VERIFICATION",
    "SYNTHESIS",
    "INFRASTRUCTURE",
}
WORK_ITEM_STATUSES = {
    "ASSIGNED",
    "IN_PROGRESS",
    "BLOCKED",
    "READY_FOR_REVIEW",
    "ACCEPTED",
    "CANCELLED",
}
TERMINAL_WORK_ITEM_STATUSES = {"ACCEPTED", "CANCELLED"}
ALLOWED_TRANSITIONS = {
    "ASSIGNED": {"IN_PROGRESS", "BLOCKED", "CANCELLED"},
    "IN_PROGRESS": {"BLOCKED", "READY_FOR_REVIEW", "CANCELLED"},
    "BLOCKED": {"IN_PROGRESS", "CANCELLED"},
    "READY_FOR_REVIEW": {"IN_PROGRESS", "ACCEPTED", "CANCELLED"},
    "ACCEPTED": set(),
    "CANCELLED": set(),
}
DECISION_TYPES = {
    "RESEARCH",
    "CANDIDATE_LIFECYCLE",
    "SPIN_OUT",
    "PUBLICATION",
    "GOVERNANCE",
    "INFRASTRUCTURE",
}
CONTRIBUTOR_TYPES = {"HUMAN", "MODEL", "COMPUTATION", "EXTERNAL_SOURCE"}
CONTRIBUTION_KINDS = {
    "FORMULATION",
    "ORCHESTRATION",
    "KEY_MECHANISM",
    "VERIFICATION",
    "HUMAN_REDERIVATION",
    "FORMALIZATION",
    "EXPOSITION",
}
CAPTURE_MODES = {
    "MANUAL_SUMMARY",
    "IMPORT_NOTES_OR_TRANSCRIPT",
    "STRUCTURED_DURING_MEETING",
}
CAPTURE_REVIEW_DECISIONS = CAPTURE_MODES | {"DEFER"}
CANDIDATE_PHASES = (
    "LEAD",
    "QUALIFYING",
    "TRIAL_ACTIVE",
    "PARKED",
    "REJECTED",
    "SPINOUT_READY",
    "SPUN_OUT",
)
REPOSITORY_STATES = {"NOT_CONFIGURED", "LOCAL_ONLY", "PENDING", "CONNECTED", "ERROR"}
REPOSITORY_VISIBILITIES = {"UNDECIDED", "LOCAL_ONLY", "PRIVATE", "PUBLIC"}
LAB_KINDS = {"ARTICLE_OR_COHERENT_PROGRAM", "DISCOVERY_PORTFOLIO"}


class CollaborationError(RuntimeError):
    pass


class FileLock:
    """Persistent, crash-released advisory lock on one verified regular inode."""

    def __init__(self, path: Path, label: str) -> None:
        self.path = path
        self.label = label
        self.fd: Optional[int] = None
        self.identity: Optional[Tuple[int, int]] = None

    def __enter__(self) -> "FileLock":
        try:
            parent_mode = self.path.parent.lstat().st_mode
        except FileNotFoundError:
            try:
                self.path.parent.mkdir()
            except OSError as exc:
                raise CollaborationError(f"cannot create safe {self.label} lock directory") from exc
            parent_mode = self.path.parent.lstat().st_mode
        if stat.S_ISLNK(parent_mode) or not stat.S_ISDIR(parent_mode):
            raise CollaborationError(f"{self.label} lock parent must be a real directory")
        flags = (
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        descriptor: Optional[int] = None
        try:
            descriptor = os.open(str(self.path), flags, 0o600)
        except OSError as exc:
            raise CollaborationError(
                f"{self.label} lock path must be a safe regular file"
            ) from exc
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise CollaborationError(
                    f"{self.label} lock path must be a safe regular file"
                )
            self.identity = (info.st_dev, info.st_ino)
            try:
                path_info = self.path.lstat()
            except OSError as exc:
                raise CollaborationError(
                    f"{self.label} lock path changed during acquisition"
                ) from exc
            if (
                not stat.S_ISREG(path_info.st_mode)
                or self.identity != (path_info.st_dev, path_info.st_ino)
            ):
                raise CollaborationError(
                    f"{self.label} lock path changed during acquisition"
                )
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN):
                    raise CollaborationError(
                        f"another {self.label} operation is active"
                    ) from exc
                raise CollaborationError(
                    f"cannot acquire safe {self.label} lock"
                ) from exc
            try:
                path_info = self.path.lstat()
            except OSError as exc:
                raise CollaborationError(
                    f"{self.label} lock path changed during acquisition"
                ) from exc
            if (
                not stat.S_ISREG(path_info.st_mode)
                or self.identity != (path_info.st_dev, path_info.st_ino)
            ):
                raise CollaborationError(
                    f"{self.label} lock path changed during acquisition"
                )
            os.ftruncate(descriptor, 0)
            os.lseek(descriptor, 0, os.SEEK_SET)
            os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
            self.fd = descriptor
            descriptor = None
        finally:
            if descriptor is not None:
                os.close(descriptor)
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.fd is not None:
            descriptor = self.fd
            self.fd = None
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_timestamp(value: str, label: str) -> str:
    if not RFC3339_RE.fullmatch(value):
        raise CollaborationError(f"{label} must be UTC RFC3339 with whole seconds (YYYY-MM-DDTHH:MM:SSZ)")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise CollaborationError(f"{label} is not a real UTC timestamp") from exc
    return value


def validate_id(value: str, label: str) -> str:
    if not ID_RE.fullmatch(value):
        raise CollaborationError(f"{label} must match {ID_RE.pattern}")
    return value


def safe_line(value: str, label: str, *, maximum: int = 500) -> str:
    result = value.strip()
    if not result or len(result) > maximum or any(ord(ch) < 32 or ord(ch) == 127 for ch in result):
        raise CollaborationError(f"{label} must be a nonempty printable line of at most {maximum} characters")
    return result


def root_path(value: Optional[str]) -> Path:
    root = DEFAULT_ROOT if value is None else Path(value).expanduser()
    if not root.is_absolute():
        root = (Path.cwd() / root).absolute()
    try:
        mode = root.lstat().st_mode
    except OSError as exc:
        raise CollaborationError(f"cannot inspect laboratory root: {exc}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise CollaborationError("laboratory root must be a real directory, not a symlink")
    return root


def relative_path(value: str, label: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise CollaborationError(f"{label} must be a safe root-relative path")
    return path


def inspect_ancestors(root: Path, relative: Path, label: str, *, leaf_may_be_missing: bool = False) -> Path:
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        is_leaf = index == len(relative.parts) - 1
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            if is_leaf and leaf_may_be_missing:
                return current
            raise CollaborationError(f"missing {label}: {relative.as_posix()}")
        except OSError as exc:
            raise CollaborationError(f"cannot inspect {label}: {exc}") from exc
        if stat.S_ISLNK(mode):
            raise CollaborationError(f"{label} cannot contain a symlink: {relative.as_posix()}")
        if not is_leaf and not stat.S_ISDIR(mode):
            raise CollaborationError(f"{label} has a non-directory parent: {relative.as_posix()}")
    return current


def regular_file(root: Path, relative: Path, label: str) -> Path:
    path = inspect_ancestors(root, relative, label)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise CollaborationError(f"{label} must be a regular file: {relative.as_posix()}")
    return path


def real_directory(root: Path, relative: Path, label: str) -> Path:
    path = inspect_ancestors(root, relative, label)
    if not stat.S_ISDIR(path.lstat().st_mode):
        raise CollaborationError(f"{label} must be a real directory: {relative.as_posix()}")
    return path


def ensure_directory(root: Path, relative: Path, label: str) -> Path:
    current = root
    for part in relative.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            try:
                current.mkdir()
            except FileExistsError:
                mode = current.lstat().st_mode
                if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                    raise CollaborationError(f"unsafe raced {label}: {relative.as_posix()}")
            continue
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise CollaborationError(f"unsafe {label}: {relative.as_posix()}")
    return current


def json_bytes(value: Dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def load_json_file(root: Path, relative: Path, label: str) -> Dict[str, Any]:
    path = regular_file(root, relative, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CollaborationError(f"cannot parse {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise CollaborationError(f"{label} must contain a JSON object")
    return value


def write_new(root: Path, relative: Path, data: bytes, label: str) -> Path:
    parent = ensure_directory(root, relative.parent, f"{label} parent")
    target = parent / relative.name
    if target.exists() or target.is_symlink():
        raise CollaborationError(f"refusing to overwrite append-only {label}: {relative.as_posix()}")
    try:
        with target.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise CollaborationError(f"refusing to overwrite append-only {label}: {relative.as_posix()}") from exc
    return target


def atomic_replace(root: Path, relative: Path, data: bytes, label: str) -> Path:
    parent = ensure_directory(root, relative.parent, f"{label} parent")
    target = parent / relative.name
    if target.exists() or target.is_symlink():
        regular_file(root, relative, label)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{relative.name}.", dir=str(parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if target.exists() or target.is_symlink():
            regular_file(root, relative, label)
        os.replace(str(temporary), str(target))
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_text_source(root: Path, value: str, label: str, *, maximum: int = 262_144) -> Tuple[str, str]:
    relative = relative_path(value, label)
    path = regular_file(root, relative, label)
    data = path.read_bytes()
    if not data or len(data) > maximum or b"\x00" in data:
        raise CollaborationError(f"{label} must contain 1..{maximum} bytes of UTF-8 text")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CollaborationError(f"{label} must be UTF-8 text") from exc
    return text, sha256_bytes(data)


def canonical_summary_digest(summary: Dict[str, Any]) -> str:
    payload = {key: value for key, value in summary.items() if key not in {"generated_at", "source_digest_sha256"}}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return sha256_bytes(canonical)


def validate_summary(summary: Dict[str, Any]) -> None:
    expected_keys = {
        "schema_version",
        "generated_at",
        "lab_kind",
        "source_digest_sha256",
        "candidate_counts",
        "pending_cycle_decision",
        "model_recheck_count",
        "last_cycle_at",
        "next_cycle_at",
        "repository",
    }
    if set(summary) != expected_keys or summary.get("schema_version") != 1:
        raise CollaborationError("Control Room summary has an unsupported or over-broad shape")
    validate_timestamp(str(summary.get("generated_at", "")), "summary.generated_at")
    if summary.get("lab_kind") not in LAB_KINDS:
        raise CollaborationError("summary.lab_kind is invalid")
    counts = summary.get("candidate_counts")
    if not isinstance(counts, dict) or tuple(counts.keys()) != CANDIDATE_PHASES:
        # JSON parsers preserve order, but producer order is not a security property.
        if not isinstance(counts, dict) or set(counts) != set(CANDIDATE_PHASES):
            raise CollaborationError("summary.candidate_counts has an invalid phase set")
    if any(not isinstance(counts[phase], int) or isinstance(counts[phase], bool) or counts[phase] < 0 for phase in CANDIDATE_PHASES):
        raise CollaborationError("summary candidate counts must be nonnegative integers")
    if not isinstance(summary.get("pending_cycle_decision"), bool):
        raise CollaborationError("summary.pending_cycle_decision must be boolean")
    if not isinstance(summary.get("model_recheck_count"), int) or isinstance(summary.get("model_recheck_count"), bool) or summary["model_recheck_count"] < 0:
        raise CollaborationError("summary.model_recheck_count must be a nonnegative integer")
    for key in ("last_cycle_at", "next_cycle_at"):
        if summary.get(key) is not None:
            validate_timestamp(str(summary[key]), f"summary.{key}")
    repository = summary.get("repository")
    if not isinstance(repository, dict) or set(repository) != {"state", "visibility"}:
        raise CollaborationError("summary.repository must contain only state and visibility")
    if repository.get("state") not in REPOSITORY_STATES or repository.get("visibility") not in REPOSITORY_VISIBILITIES:
        raise CollaborationError("summary.repository values are invalid")
    digest = summary.get("source_digest_sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest) or digest != canonical_summary_digest(summary):
        raise CollaborationError("Control Room summary digest binding is invalid")


def profile_kind(root: Path) -> str:
    profile = load_json_file(root, Path("LAB_PROFILE.json"), "LAB_PROFILE")
    lab = profile.get("lab")
    kind = lab.get("kind") if isinstance(lab, dict) else None
    if kind not in LAB_KINDS:
        raise CollaborationError("LAB_PROFILE.lab.kind is not supported by team collaboration")
    return str(kind)


def initial_summary(root: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "lab_kind": profile_kind(root),
        "source_digest_sha256": "",
        "candidate_counts": {phase: 0 for phase in CANDIDATE_PHASES},
        "pending_cycle_decision": False,
        "model_recheck_count": 0,
        "last_cycle_at": None,
        "next_cycle_at": None,
        "repository": {"state": "NOT_CONFIGURED", "visibility": "UNDECIDED"},
    }
    result["source_digest_sha256"] = canonical_summary_digest(result)
    return result


def update_summary(root: Path, mutation: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
    relative = Path("knowledge/control_room_summary.json")
    path = root / relative
    lock = root / "knowledge/.control-room-summary.lock"
    with FileLock(lock, "Control Room summary"):
        # Re-read only after the shared lock is held. Discovery uses this exact
        # lock, so neither producer can silently restore an older safe subset.
        if path.exists() or path.is_symlink():
            summary = load_json_file(root, relative, "Control Room summary")
            validate_summary(summary)
        else:
            summary = initial_summary(root)
        mutation(summary)
        summary["generated_at"] = utc_now()
        summary["source_digest_sha256"] = canonical_summary_digest(summary)
        validate_summary(summary)
        atomic_replace(root, relative, json_bytes(summary), "Control Room summary")
    return summary


def validate_member(member: Any, label: str) -> Dict[str, Any]:
    if not isinstance(member, dict) or set(member) != {"id", "display_name", "role", "github_handle"}:
        raise CollaborationError(f"{label} must contain id, display_name, role, and github_handle")
    member_id = str(member.get("id", ""))
    if not MEMBER_ID_RE.fullmatch(member_id):
        raise CollaborationError(f"{label}.id is invalid")
    display_name = safe_line(str(member.get("display_name", "")), f"{label}.display_name", maximum=200)
    role = member.get("role")
    if role not in {"STEWARD", "CO_OWNER"}:
        raise CollaborationError(f"{label}.role is invalid")
    handle = member.get("github_handle")
    if handle is not None and (not isinstance(handle, str) or not HANDLE_RE.fullmatch(handle)):
        raise CollaborationError(f"{label}.github_handle is invalid")
    return {"id": member_id, "display_name": display_name, "role": role, "github_handle": handle}


def default_governance() -> Dict[str, Any]:
    return {
        "research_decisions": "CONSENSUS",
        "spinout_decisions": "CONSENSUS",
        "publication_decisions": "CONSENSUS",
        "process_decisions": "STEWARD",
    }


def validate_governance(value: Any) -> Dict[str, Any]:
    expected = set(default_governance())
    if not isinstance(value, dict) or set(value) != expected:
        raise CollaborationError("collaboration.governance has an unsupported shape")
    for key in ("research_decisions", "spinout_decisions", "publication_decisions"):
        if value.get(key) != "CONSENSUS":
            raise CollaborationError(f"v1 requires {key}=CONSENSUS")
    if value.get("process_decisions") != "STEWARD":
        raise CollaborationError("v1 requires process_decisions=STEWARD")
    return dict(value)


def configured_team_value(collaboration: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {
        "members", "steward_id", "governance", "authorship_policy",
        "integration_mode", "cycle_policy", "meeting_capture", "repository",
    }
    unknown = set(collaboration) - allowed
    if unknown:
        raise CollaborationError("LAB_PROFILE.collaboration has unsupported keys: " + ", ".join(sorted(unknown)))
    members_value = collaboration.get("members")
    if not isinstance(members_value, list) or len(members_value) < 2:
        raise CollaborationError("team collaboration requires at least two members")
    members = [validate_member(item, f"collaboration.members[{index}]") for index, item in enumerate(members_value)]
    ids = [item["id"] for item in members]
    if len(ids) != len(set(ids)):
        raise CollaborationError("collaboration member IDs must be unique")
    handles = [str(item["github_handle"]).casefold() for item in members if item["github_handle"]]
    if len(handles) != len(set(handles)):
        raise CollaborationError("non-null collaboration GitHub handles must be unique")
    steward = str(collaboration.get("steward_id", ""))
    if not MEMBER_ID_RE.fullmatch(steward):
        raise CollaborationError("steward_id is invalid")
    if steward not in ids:
        raise CollaborationError("steward_id must reference a declared member")
    steward_roles = [member["id"] for member in members if member["role"] == "STEWARD"]
    if steward_roles != [steward]:
        raise CollaborationError("exactly one STEWARD role must match steward_id")
    governance = validate_governance(collaboration.get("governance", default_governance()))
    if collaboration.get("authorship_policy") != "ALL_MEMBERS_EXPECTED_COAUTHORS":
        raise CollaborationError("authorship_policy must equal ALL_MEMBERS_EXPECTED_COAUTHORS")
    if collaboration.get("integration_mode") != "PULL_REQUEST":
        raise CollaborationError("integration_mode must equal PULL_REQUEST")
    if collaboration.get("cycle_policy") != "MEETING_REAUTHORIZED":
        raise CollaborationError("cycle_policy must equal MEETING_REAUTHORIZED")
    capture = collaboration.get("meeting_capture")
    if capture not in {
        "MANUAL_SUMMARY_REVISIT_AFTER_FIRST_CYCLE", "NOTES_OR_TRANSCRIPT", "LIVE_STRUCTURED_MINUTES"
    }:
        raise CollaborationError("meeting_capture is invalid")
    repository = collaboration.get("repository")
    if (
        not isinstance(repository, dict)
        or set(repository) != {"provider", "visibility", "setup_state"}
        or repository.get("provider") != "GITHUB"
        or repository.get("visibility") not in {"UNDECIDED", "PRIVATE", "PUBLIC"}
        or repository.get("setup_state") != "NOT_CONFIGURED"
    ):
        raise CollaborationError("collaboration.repository.visibility is invalid")
    return {
        "schema_version": 1,
        "record_type": "team_collaboration_configuration",
        "status": "ACTIVE",
        "members": members,
        "steward_id": steward,
        "governance": governance,
        "authorship_policy": "ALL_MEMBERS_EXPECTED_COAUTHORS",
        "integration_mode": "PULL_REQUEST",
        "cycle_policy": "MEETING_REAUTHORIZED",
        "meeting_capture": capture,
        "repository": dict(repository),
    }


def load_team(root: Path, *, require_active: bool = True) -> Dict[str, Any]:
    value = load_json_file(root, Path("collaboration/team.json"), "team configuration")
    if value.get("schema_version") != 1 or value.get("record_type") != "team_collaboration_configuration":
        raise CollaborationError("team configuration has an invalid schema")
    if require_active and value.get("status") != "ACTIVE":
        raise CollaborationError("team collaboration is not configured")
    if value.get("status") == "ACTIVE":
        normalized = configured_team_value(
            {
                "members": value.get("members"),
                "steward_id": value.get("steward_id"),
                "governance": value.get("governance"),
                "authorship_policy": value.get("authorship_policy"),
                "integration_mode": value.get("integration_mode"),
                "cycle_policy": value.get("cycle_policy"),
                "meeting_capture": value.get("meeting_capture"),
                "repository": value.get("repository"),
            }
        )
        if value != normalized:
            raise CollaborationError("team configuration contains unsupported fields or invalid values")
    return value


def member_ids(team: Dict[str, Any]) -> List[str]:
    return [str(member["id"]) for member in team["members"]]


def require_member(team: Dict[str, Any], value: str, label: str) -> str:
    member = validate_id(value, label)
    if member not in member_ids(team):
        raise CollaborationError(f"{label} does not reference a configured member")
    return member


def exact_consensus(team: Dict[str, Any], values: Iterable[str], label: str) -> List[str]:
    supplied = [require_member(team, item, label) for item in values]
    if len(supplied) != len(set(supplied)):
        raise CollaborationError(f"{label} contains duplicates")
    expected = member_ids(team)
    if set(supplied) != set(expected):
        raise CollaborationError(f"{label} must contain every configured member exactly once")
    return expected


def bootstrap_from_profile(root: Path) -> Dict[str, Any]:
    profile = load_json_file(root, Path("LAB_PROFILE.json"), "LAB_PROFILE")
    lab = profile.get("lab")
    collaboration = lab.get("collaboration") if isinstance(lab, dict) else None
    if not isinstance(collaboration, dict):
        raise CollaborationError("LAB_PROFILE.lab.collaboration must be an object for team_collaboration")
    configured = configured_team_value(collaboration)
    relative = Path("collaboration/team.json")
    existing = load_team(root, require_active=False)
    if existing.get("status") == "ACTIVE":
        if existing != configured:
            raise CollaborationError("configured team differs from LAB_PROFILE; refusing to rewrite governance")
    elif existing.get("status") == "UNCONFIGURED":
        atomic_replace(root, relative, json_bytes(configured), "team configuration")
    else:
        raise CollaborationError("team configuration has an invalid bootstrap status")

    visibility = configured["repository"]["visibility"]
    update_summary(root, lambda summary: summary.__setitem__("repository", {"state": "NOT_CONFIGURED", "visibility": visibility}))
    return configured


def cycle_relative(cycle_id: str) -> Path:
    return Path("collaboration/cycles") / validate_id(cycle_id, "cycle ID")


def cycle_dirs(root: Path) -> List[Path]:
    base = real_directory(root, Path("collaboration/cycles"), "cycles directory")
    result: List[Path] = []
    for path in sorted(base.iterdir()):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise CollaborationError(f"unsafe entry in cycles directory: {path.name}")
        if stat.S_ISDIR(mode):
            validate_id(path.name, "cycle directory name")
            result.append(path)
    return result


def cycle_phase(path: Path) -> str:
    if (path / "closure.json").is_file():
        return "CLOSED"
    if (path / "authorization.json").is_file():
        return "ACTIVE"
    return "PREPARED"


def active_cycle_ids(root: Path) -> List[str]:
    return [path.name for path in cycle_dirs(root) if cycle_phase(path) == "ACTIVE"]


def prepare_cycle(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    team = load_team(root)
    steward = require_member(team, args.prepared_by, "prepared-by member")
    if steward != team["steward_id"]:
        raise CollaborationError("only the configured steward may prepare a cycle")
    cycle_id = validate_id(args.cycle_id, "cycle ID")
    meeting_id = validate_id(args.meeting_id, "meeting ID")
    prepared_at = validate_timestamp(args.prepared_at or utc_now(), "prepared-at")
    starts_at = validate_timestamp(args.starts_at, "starts-at")
    ends_at = validate_timestamp(args.ends_at, "ends-at")
    if starts_at >= ends_at:
        raise CollaborationError("cycle starts-at must be earlier than ends-at")
    focuses = [safe_line(item, "focus") for item in args.focus]
    if not focuses:
        raise CollaborationError("at least one exact agenda focus is required")
    relative = cycle_relative(cycle_id)
    target = root / relative
    if target.exists() or target.is_symlink():
        raise CollaborationError(f"cycle already exists: {cycle_id}")
    parent = ensure_directory(root, relative.parent, "cycles directory")
    try:
        target.mkdir()
    except FileExistsError as exc:
        raise CollaborationError(f"cycle already exists: {cycle_id}") from exc
    agenda = (
        f"# Cycle agenda: {cycle_id}\n\n"
        f"- Meeting ID: `{meeting_id}`\n"
        f"- Prepared at: `{prepared_at}`\n"
        f"- Prepared by member: `{steward}`\n"
        f"- Proposed cycle window: `{starts_at}` — `{ends_at}`\n\n"
        "## Exact focuses\n\n"
        + "\n".join(f"- {item}" for item in focuses)
        + "\n\n## Meeting checklist\n\n"
        "- Review the previous cycle and unresolved handoffs.\n"
        "- Decide which work is worth doing during this cycle.\n"
        "- Authorize the cycle unanimously; preparation alone starts no work.\n"
        "- Assign bounded work items with success criteria and stop rules.\n"
        "- Record a concise manual summary after the meeting.\n"
    )
    try:
        write_new(root, relative / "agenda.md", agenda.encode("utf-8"), "cycle agenda")
        for directory in ("decisions", "amendments", "handoffs"):
            ensure_directory(root, relative / directory, f"cycle {directory}")
    except Exception:
        # A newly-created empty/partial target is ours. Preserve evidence rather
        # than risk recursively deleting a raced-in path; validation will flag it.
        raise
    return {"cycle_id": cycle_id, "phase": "PREPARED", "meeting_id": meeting_id}


def load_cycle_agenda(root: Path, cycle_id: str) -> Tuple[Path, str]:
    relative = cycle_relative(cycle_id) / "agenda.md"
    path = regular_file(root, relative, "cycle agenda")
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^- Meeting ID: `([^`]+)`$", text, flags=re.MULTILINE)
    if not match:
        raise CollaborationError("cycle agenda has no valid meeting ID binding")
    validate_id(match.group(1), "agenda meeting ID")
    return path, match.group(1)


def authorize_cycle(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    team = load_team(root)
    agreed = exact_consensus(team, args.authorized_by, "authorized-by")
    cycle_id = validate_id(args.cycle_id, "cycle ID")
    path, meeting_id = load_cycle_agenda(root, cycle_id)
    if args.meeting_id != meeting_id:
        raise CollaborationError("authorization meeting ID must match the prepared agenda")
    active = active_cycle_ids(root)
    if active:
        raise CollaborationError("another cycle remains active: " + ", ".join(active))
    timestamp = validate_timestamp(args.authorized_at or utc_now(), "authorized-at")
    value = {
        "schema_version": 1,
        "record_type": "team_cycle_authorization",
        "cycle_id": cycle_id,
        "meeting_id": meeting_id,
        "authorized_at": timestamp,
        "authorized_by_member_ids": agreed,
        "agenda_sha256": sha256_file(path),
        "governance_rule": "CONSENSUS_ALL_MEMBERS",
    }
    write_new(root, cycle_relative(cycle_id) / "authorization.json", json_bytes(value), "cycle authorization")
    update_summary(
        root,
        lambda summary: summary.update(
            {"pending_cycle_decision": True, "next_cycle_at": timestamp}
        ),
    )
    return value


def authorization(root: Path, cycle_id: str) -> Tuple[Dict[str, Any], Path]:
    relative = cycle_relative(cycle_id) / "authorization.json"
    value = load_json_file(root, relative, "cycle authorization")
    path = root / relative
    if value.get("record_type") != "team_cycle_authorization" or value.get("cycle_id") != cycle_id:
        raise CollaborationError("cycle authorization is invalid")
    validate_timestamp(str(value.get("authorized_at", "")), "cycle authorized_at")
    return value, path


def record_minutes(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    team = load_team(root)
    recorder = require_member(team, args.recorded_by, "recorded-by member")
    cycle_id = validate_id(args.cycle_id, "cycle ID")
    auth, auth_path = authorization(root, cycle_id)
    text, source_sha = read_text_source(root, args.summary_file, "manual summary file")
    if len(text.strip()) < 40:
        raise CollaborationError("manual meeting summary is too short")
    timestamp = validate_timestamp(args.recorded_at or utc_now(), "recorded-at")
    content = (
        f"# Meeting minutes: {auth['meeting_id']}\n\n"
        f"- Cycle ID: `{cycle_id}`\n"
        f"- Recorded at: `{timestamp}`\n"
        f"- Recorded by member: `{recorder}`\n"
        f"- Cycle authorization SHA-256: `{sha256_file(auth_path)}`\n"
        f"- Imported manual-summary SHA-256: `{source_sha}`\n"
        f"- Capture mode: `{team['meeting_capture']}`\n\n"
        "## Manual summary\n\n"
        + text.strip()
        + "\n\n## Capture-mode reminder\n\n"
        "After the first completed cycle, explicitly choose whether to keep manual summaries, import notes/transcripts, or structure notes during meetings. Until then, manual summary remains authoritative.\n"
    )
    write_new(root, cycle_relative(cycle_id) / "minutes.md", content.encode("utf-8"), "meeting minutes")
    return {"cycle_id": cycle_id, "meeting_id": auth["meeting_id"], "recorded_at": timestamp}


def work_item_relative(work_item_id: str) -> Path:
    return Path("collaboration/work_items") / validate_id(work_item_id, "work-item ID")


def create_work_item(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    team = load_team(root)
    owner = require_member(team, args.owner, "work-item owner")
    created_by = require_member(team, args.created_by, "work-item creator")
    cycle_id = validate_id(args.cycle_id, "cycle ID")
    auth, auth_path = authorization(root, cycle_id)
    if (root / cycle_relative(cycle_id) / "closure.json").exists():
        raise CollaborationError("cannot assign work to a closed cycle")
    item_id = validate_id(args.work_item_id, "work-item ID")
    item_type = args.type
    if item_type not in WORK_ITEM_TYPES:
        raise CollaborationError("unsupported work-item type")
    relative = work_item_relative(item_id)
    target = root / relative
    if target.exists() or target.is_symlink():
        raise CollaborationError(f"work item already exists: {item_id}")
    ensure_directory(root, relative, "work-item directory")
    ensure_directory(root, relative / "events", "work-item events")
    value = {
        "schema_version": 1,
        "record_type": "team_work_item",
        "work_item_id": item_id,
        "cycle_id": cycle_id,
        "cycle_authorization_sha256": sha256_file(auth_path),
        "type": item_type,
        "initial_status": "ASSIGNED",
        "owner_member_id": owner,
        "created_by_member_id": created_by,
        "created_at": validate_timestamp(args.created_at or utc_now(), "created-at"),
        "title": safe_line(args.title, "work-item title", maximum=300),
        "expected_artifact": safe_line(args.expected_artifact, "expected artifact"),
        "success_criterion": safe_line(args.success_criterion, "success criterion", maximum=1000),
        "stop_rule": safe_line(args.stop_rule, "stop rule", maximum=1000),
    }
    write_new(root, relative / "work_item.json", json_bytes(value), "work-item definition")
    return value


def load_work_item(root: Path, item_id: str) -> Dict[str, Any]:
    value = load_json_file(root, work_item_relative(item_id) / "work_item.json", "work-item definition")
    if value.get("record_type") != "team_work_item" or value.get("work_item_id") != item_id:
        raise CollaborationError("work-item definition is invalid")
    return value


def work_item_events(root: Path, item_id: str) -> List[Dict[str, Any]]:
    directory = real_directory(root, work_item_relative(item_id) / "events", "work-item events")
    values: List[Dict[str, Any]] = []
    for path in sorted(directory.iterdir()):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode) or not re.fullmatch(r"\d{6}-[a-z][a-z0-9_-]{0,63}\.json", path.name):
            raise CollaborationError(f"unsafe or invalid work-item event: {path.name}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise CollaborationError(f"work-item event is not an object: {path.name}")
        values.append(value)
    for index, event in enumerate(values, start=1):
        if event.get("sequence") != index:
            raise CollaborationError("work-item event sequence is not contiguous")
    return values


def current_work_item_status(root: Path, item_id: str) -> str:
    item = load_work_item(root, item_id)
    status = str(item.get("initial_status"))
    if status != "ASSIGNED":
        raise CollaborationError("work-item initial status must be ASSIGNED")
    for event in work_item_events(root, item_id):
        if event.get("from_status") != status or event.get("to_status") not in ALLOWED_TRANSITIONS[status]:
            raise CollaborationError("work-item event has an invalid transition chain")
        status = str(event["to_status"])
    return status


def transition_work_item(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    team = load_team(root)
    actor = require_member(team, args.actor, "transition actor")
    item_id = validate_id(args.work_item_id, "work-item ID")
    event_id = validate_id(args.event_id, "event ID")
    item = load_work_item(root, item_id)
    if (root / cycle_relative(str(item["cycle_id"])) / "closure.json").exists():
        raise CollaborationError("cannot transition a work item after its cycle is closed")
    before = current_work_item_status(root, item_id)
    after = args.to_status
    if after not in WORK_ITEM_STATUSES or after not in ALLOWED_TRANSITIONS[before]:
        raise CollaborationError(f"invalid work-item transition: {before} -> {after}")
    events = work_item_events(root, item_id)
    sequence = len(events) + 1
    value = {
        "schema_version": 1,
        "record_type": "team_work_item_transition",
        "work_item_id": item_id,
        "event_id": event_id,
        "sequence": sequence,
        "from_status": before,
        "to_status": after,
        "actor_member_id": actor,
        "recorded_at": validate_timestamp(args.recorded_at or utc_now(), "recorded-at"),
        "note": safe_line(args.note, "transition note", maximum=1000),
    }
    filename = f"{sequence:06d}-{event_id}.json"
    write_new(root, work_item_relative(item_id) / "events" / filename, json_bytes(value), "work-item transition")
    return value


def cycle_work_items(root: Path, cycle_id: str) -> List[Tuple[str, str]]:
    base = real_directory(root, Path("collaboration/work_items"), "work-items directory")
    result: List[Tuple[str, str]] = []
    for path in sorted(base.iterdir()):
        mode = path.lstat().st_mode
        if stat.S_ISREG(mode) and path.name == "README.md":
            continue
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise CollaborationError(f"unsafe work-items entry: {path.name}")
        item_id = validate_id(path.name, "work-item directory name")
        item = load_work_item(root, item_id)
        if item.get("cycle_id") == cycle_id:
            result.append((item_id, current_work_item_status(root, item_id)))
    return result


def record_decision(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    team = load_team(root)
    agreed = exact_consensus(team, args.agreed_by, "agreed-by")
    cycle_id = validate_id(args.cycle_id, "cycle ID")
    authorization(root, cycle_id)
    decision_id = validate_id(args.decision_id, "decision ID")
    if args.type not in DECISION_TYPES:
        raise CollaborationError("unsupported decision type")
    value = {
        "schema_version": 1,
        "record_type": "team_decision",
        "decision_id": decision_id,
        "cycle_id": cycle_id,
        "type": args.type,
        "recorded_at": validate_timestamp(args.recorded_at or utc_now(), "recorded-at"),
        "agreed_by_member_ids": agreed,
        "summary": safe_line(args.summary, "decision summary", maximum=1000),
        "rationale": safe_line(args.rationale, "decision rationale", maximum=2000),
        "mathematical_status_effect": "NONE",
    }
    write_new(root, cycle_relative(cycle_id) / "decisions" / f"{decision_id}.json", json_bytes(value), "team decision")
    return value


def artifact_bindings(root: Path, values: Sequence[str], label: str) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        relative = relative_path(value, label)
        key = relative.as_posix().casefold()
        if key in seen:
            raise CollaborationError(f"duplicate {label}: {relative.as_posix()}")
        seen.add(key)
        path = regular_file(root, relative, label)
        result.append({"path": relative.as_posix(), "sha256": sha256_file(path), "bytes": path.stat().st_size})
    return result


def record_handoff(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    team = load_team(root)
    source_member = require_member(team, args.from_member, "handoff source member")
    target_member = require_member(team, args.to_member, "handoff target member")
    if source_member == target_member:
        raise CollaborationError("handoff source and target must differ")
    cycle_id = validate_id(args.cycle_id, "cycle ID")
    authorization(root, cycle_id)
    item_id = validate_id(args.work_item_id, "work-item ID")
    item = load_work_item(root, item_id)
    if item.get("cycle_id") != cycle_id:
        raise CollaborationError("handoff work item belongs to a different cycle")
    handoff_id = validate_id(args.handoff_id, "handoff ID")
    value = {
        "schema_version": 1,
        "record_type": "team_handoff",
        "handoff_id": handoff_id,
        "cycle_id": cycle_id,
        "work_item_id": item_id,
        "recorded_at": validate_timestamp(args.recorded_at or utc_now(), "recorded-at"),
        "from_member_id": source_member,
        "to_member_id": target_member,
        "summary": safe_line(args.summary, "handoff summary", maximum=2000),
        "next_action": safe_line(args.next_action, "handoff next action", maximum=1000),
        "artifact_bindings": artifact_bindings(root, args.artifact, "handoff artifact"),
    }
    write_new(root, cycle_relative(cycle_id) / "handoffs" / f"{handoff_id}.json", json_bytes(value), "team handoff")
    return value


def record_contribution(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    team = load_team(root)
    recorded_by = require_member(team, args.recorded_by, "contribution recorder")
    contribution_id = validate_id(args.contribution_id, "contribution ID")
    item_id = validate_id(args.work_item_id, "work-item ID")
    item = load_work_item(root, item_id)
    contributor_type = args.contributor_type
    if contributor_type not in CONTRIBUTOR_TYPES:
        raise CollaborationError("unsupported contributor type")
    contributor_id = safe_line(args.contributor_id, "contributor ID", maximum=200)
    if contributor_type == "HUMAN":
        contributor_id = require_member(team, contributor_id, "human contributor")
    contribution_kind = args.contribution_kind
    if contribution_kind not in CONTRIBUTION_KINDS:
        raise CollaborationError("unsupported contribution kind")
    value = {
        "schema_version": 1,
        "record_type": "team_contribution_provenance",
        "contribution_id": contribution_id,
        "work_item_id": item_id,
        "cycle_id": item["cycle_id"],
        "recorded_at": validate_timestamp(args.recorded_at or utc_now(), "recorded-at"),
        "recorded_by_member_id": recorded_by,
        "contributor_type": contributor_type,
        "contributor_id": contributor_id,
        "contribution_kind": contribution_kind,
        "role": safe_line(args.role, "contribution role", maximum=500),
        "statement": safe_line(args.statement, "contribution statement", maximum=2000),
        "artifact_bindings": artifact_bindings(root, args.artifact, "contribution artifact"),
        "authorship_or_mathematical_status_effect": "NONE",
    }
    write_new(root, Path("collaboration/contributions") / f"{contribution_id}.json", json_bytes(value), "contribution record")
    return value


def validate_contributions(root: Path, team: Dict[str, Any]) -> int:
    """Validate the complete append-only contribution tree and every byte binding."""

    directory = real_directory(
        root, Path("collaboration/contributions"), "contributions directory"
    )
    expected_keys = {
        "schema_version",
        "record_type",
        "contribution_id",
        "work_item_id",
        "cycle_id",
        "recorded_at",
        "recorded_by_member_id",
        "contributor_type",
        "contributor_id",
        "contribution_kind",
        "role",
        "statement",
        "artifact_bindings",
        "authorship_or_mathematical_status_effect",
    }
    count = 0
    seen_ids: set[str] = set()
    for path in sorted(directory.iterdir()):
        mode = path.lstat().st_mode
        if stat.S_ISREG(mode) and path.name == "README.md":
            continue
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode) or not path.name.endswith(".json"):
            raise CollaborationError(f"unsafe contributions entry: {path.name}")
        contribution_id = validate_id(path.stem, "contribution filename ID")
        if contribution_id in seen_ids:
            raise CollaborationError(f"duplicate contribution ID: {contribution_id}")
        seen_ids.add(contribution_id)
        relative = Path("collaboration/contributions") / path.name
        value = load_json_file(root, relative, "contribution record")
        if set(value) != expected_keys:
            raise CollaborationError(
                f"contribution {contribution_id} has an unsupported or incomplete shape"
            )
        if value.get("schema_version") != 1 or value.get("record_type") != "team_contribution_provenance":
            raise CollaborationError(f"contribution {contribution_id} has an invalid version or type")
        if value.get("contribution_id") != contribution_id:
            raise CollaborationError(f"contribution {contribution_id} does not match its filename")
        item_id = validate_id(str(value.get("work_item_id", "")), "contribution work-item ID")
        item = load_work_item(root, item_id)
        cycle_id = validate_id(str(value.get("cycle_id", "")), "contribution cycle ID")
        if item.get("cycle_id") != cycle_id:
            raise CollaborationError(f"contribution {contribution_id} crosses a work-item cycle")
        authorization(root, cycle_id)
        validate_timestamp(str(value.get("recorded_at", "")), "contribution recorded_at")
        require_member(
            team,
            str(value.get("recorded_by_member_id", "")),
            "contribution recorder",
        )
        contributor_type = value.get("contributor_type")
        if contributor_type not in CONTRIBUTOR_TYPES:
            raise CollaborationError(f"contribution {contribution_id} has an invalid contributor type")
        contributor_id = safe_line(
            str(value.get("contributor_id", "")), "contribution contributor ID", maximum=200
        )
        if contributor_type == "HUMAN":
            require_member(team, contributor_id, "human contributor")
        if value.get("contribution_kind") not in CONTRIBUTION_KINDS:
            raise CollaborationError(f"contribution {contribution_id} has an invalid contribution kind")
        safe_line(str(value.get("role", "")), "contribution role", maximum=500)
        safe_line(str(value.get("statement", "")), "contribution statement", maximum=2000)
        bindings = value.get("artifact_bindings")
        if not isinstance(bindings, list):
            raise CollaborationError(f"contribution {contribution_id} artifact_bindings must be an array")
        seen_paths: set[str] = set()
        for index, binding in enumerate(bindings):
            label = f"contribution {contribution_id} artifact binding {index}"
            if not isinstance(binding, dict) or set(binding) != {"path", "sha256", "bytes"}:
                raise CollaborationError(f"{label} has an invalid shape")
            relative_artifact = relative_path(str(binding.get("path", "")), label)
            folded = relative_artifact.as_posix().casefold()
            if folded in seen_paths:
                raise CollaborationError(f"duplicate {label} path")
            seen_paths.add(folded)
            artifact = regular_file(root, relative_artifact, label)
            digest = binding.get("sha256")
            size = binding.get("bytes")
            if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                raise CollaborationError(f"{label} has an invalid SHA-256")
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                raise CollaborationError(f"{label} has an invalid byte count")
            if sha256_file(artifact) != digest or artifact.stat().st_size != size:
                raise CollaborationError(f"{label} no longer matches its exact bytes")
        if value.get("authorship_or_mathematical_status_effect") != "NONE":
            raise CollaborationError(
                f"contribution {contribution_id} cannot grant authorship or mathematical status"
            )
        count += 1
    return count


def record_amendment(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    team = load_team(root)
    author = require_member(team, args.author, "amendment author")
    cycle_id = validate_id(args.cycle_id, "cycle ID")
    authorization(root, cycle_id)
    amendment_id = validate_id(args.amendment_id, "amendment ID")
    target_relative = relative_path(args.target, "amendment target")
    allowed_root = cycle_relative(cycle_id)
    try:
        target_relative.relative_to(allowed_root)
    except ValueError as exc:
        raise CollaborationError("amendment target must belong to the same cycle") from exc
    if "amendments" in target_relative.parts:
        raise CollaborationError("an amendment cannot target another amendment")
    target = regular_file(root, target_relative, "amendment target")
    body, body_sha = read_text_source(root, args.body_file, "amendment body")
    value = {
        "schema_version": 1,
        "record_type": "team_artifact_amendment",
        "amendment_id": amendment_id,
        "cycle_id": cycle_id,
        "recorded_at": validate_timestamp(args.recorded_at or utc_now(), "recorded-at"),
        "author_member_id": author,
        "target": {"path": target_relative.as_posix(), "sha256": sha256_file(target)},
        "reason": safe_line(args.reason, "amendment reason", maximum=1000),
        "body": body.strip(),
        "imported_body_sha256": body_sha,
    }
    write_new(root, cycle_relative(cycle_id) / "amendments" / f"{amendment_id}.json", json_bytes(value), "artifact amendment")
    return value


def close_cycle(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    team = load_team(root)
    agreed = exact_consensus(team, args.closed_by, "closed-by")
    cycle_id = validate_id(args.cycle_id, "cycle ID")
    authorization(root, cycle_id)
    regular_file(root, cycle_relative(cycle_id) / "minutes.md", "meeting minutes")
    items = cycle_work_items(root, cycle_id)
    open_items = [f"{item_id}:{status}" for item_id, status in items if status not in TERMINAL_WORK_ITEM_STATUSES]
    if open_items:
        raise CollaborationError("cycle has nonterminal work items: " + ", ".join(open_items))
    decision = args.capture_mode_review
    if decision not in CAPTURE_REVIEW_DECISIONS:
        raise CollaborationError("capture-mode-review decision is invalid")
    closed_at = validate_timestamp(args.closed_at or utc_now(), "closed-at")
    next_cycle_at = None if args.next_cycle_at is None else validate_timestamp(args.next_cycle_at, "next-cycle-at")
    value = {
        "schema_version": 1,
        "record_type": "team_cycle_closure",
        "cycle_id": cycle_id,
        "meeting_id": validate_id(args.meeting_id, "closing meeting ID"),
        "closed_at": closed_at,
        "closed_by_member_ids": agreed,
        "verdict": args.verdict,
        "work_item_terminal_statuses": {item_id: status for item_id, status in items},
        "capture_mode_review": {
            "prompted": True,
            "decision": decision,
            "effective_mode": "MANUAL_SUMMARY" if decision == "DEFER" else decision,
        },
        "next_cycle_at": next_cycle_at,
        "next_cycle_requires_fresh_meeting_authorization": True,
    }
    write_new(root, cycle_relative(cycle_id) / "closure.json", json_bytes(value), "cycle closure")
    update_summary(
        root,
        lambda summary: summary.update(
            {
                "pending_cycle_decision": False,
                "last_cycle_at": closed_at,
                "next_cycle_at": next_cycle_at,
            }
        ),
    )
    return value


def validate_lab_state(root: Path) -> Dict[str, Any]:
    team = load_team(root)
    errors: List[str] = []
    active: List[str] = []
    meeting_ids: set[str] = set()
    for path in cycle_dirs(root):
        try:
            agenda_path, agenda_meeting = load_cycle_agenda(root, path.name)
            if agenda_meeting in meeting_ids:
                raise CollaborationError(f"meeting ID is reused: {agenda_meeting}")
            meeting_ids.add(agenda_meeting)
            phase = cycle_phase(path)
            if phase in {"ACTIVE", "CLOSED"}:
                auth, _ = authorization(root, path.name)
                exact_consensus(team, auth.get("authorized_by_member_ids", []), "stored authorization")
                if auth.get("agenda_sha256") != sha256_file(agenda_path):
                    raise CollaborationError("agenda drifted after authorization")
            if phase == "ACTIVE":
                active.append(path.name)
            if phase == "CLOSED":
                regular_file(root, cycle_relative(path.name) / "minutes.md", "closed-cycle minutes")
                for item_id, status in cycle_work_items(root, path.name):
                    if status not in TERMINAL_WORK_ITEM_STATUSES:
                        raise CollaborationError(f"closed cycle has nonterminal item {item_id}")
        except (CollaborationError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"cycle {path.name}: {exc}")
    if len(active) > 1:
        errors.append("more than one cycle is active")
    summary_path = root / "knowledge/control_room_summary.json"
    if summary_path.exists() or summary_path.is_symlink():
        try:
            validate_summary(load_json_file(root, Path("knowledge/control_room_summary.json"), "Control Room summary"))
        except CollaborationError as exc:
            errors.append(str(exc))
    # Force validation of every work-item chain, including orphaned items.
    try:
        base = real_directory(root, Path("collaboration/work_items"), "work-items directory")
        for path in sorted(base.iterdir()):
            if path.name == "README.md" and path.is_file():
                continue
            if path.is_dir() and not path.is_symlink():
                item_id = validate_id(path.name, "work-item directory name")
                item = load_work_item(root, item_id)
                authorization(root, str(item.get("cycle_id")))
                current_work_item_status(root, item_id)
            else:
                raise CollaborationError(f"unsafe work-items entry: {path.name}")
    except CollaborationError as exc:
        errors.append(str(exc))
    try:
        validate_contributions(root, team)
    except (CollaborationError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    if errors:
        raise CollaborationError("team collaboration validation failed:\n- " + "\n- ".join(errors))
    return {"status": "VALID", "member_count": len(member_ids(team)), "active_cycle_ids": active}


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", help="laboratory root (default: parent of this scripts directory)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("bootstrap-from-profile")
    sub.add_parser("validate")

    prepare = sub.add_parser("prepare-cycle")
    prepare.add_argument("--cycle-id", required=True)
    prepare.add_argument("--meeting-id", required=True)
    prepare.add_argument("--prepared-by", required=True)
    prepare.add_argument("--prepared-at")
    prepare.add_argument("--starts-at", required=True)
    prepare.add_argument("--ends-at", required=True)
    prepare.add_argument("--focus", action="append", default=[], required=True)

    authorize = sub.add_parser("authorize-cycle")
    authorize.add_argument("--cycle-id", required=True)
    authorize.add_argument("--meeting-id", required=True)
    authorize.add_argument("--authorized-by", action="append", default=[], required=True)
    authorize.add_argument("--authorized-at")

    minutes = sub.add_parser("record-minutes")
    minutes.add_argument("--cycle-id", required=True)
    minutes.add_argument("--recorded-by", required=True)
    minutes.add_argument("--summary-file", required=True)
    minutes.add_argument("--recorded-at")

    item = sub.add_parser("create-work-item")
    item.add_argument("--cycle-id", required=True)
    item.add_argument("--work-item-id", required=True)
    item.add_argument("--type", choices=sorted(WORK_ITEM_TYPES), required=True)
    item.add_argument("--owner", required=True)
    item.add_argument("--created-by", required=True)
    item.add_argument("--created-at")
    item.add_argument("--title", required=True)
    item.add_argument("--expected-artifact", required=True)
    item.add_argument("--success-criterion", required=True)
    item.add_argument("--stop-rule", required=True)

    transition = sub.add_parser("transition-work-item")
    transition.add_argument("--work-item-id", required=True)
    transition.add_argument("--event-id", required=True)
    transition.add_argument("--to-status", choices=sorted(WORK_ITEM_STATUSES), required=True)
    transition.add_argument("--actor", required=True)
    transition.add_argument("--note", required=True)
    transition.add_argument("--recorded-at")

    decision = sub.add_parser("record-decision")
    decision.add_argument("--cycle-id", required=True)
    decision.add_argument("--decision-id", required=True)
    decision.add_argument("--type", choices=sorted(DECISION_TYPES), required=True)
    decision.add_argument("--agreed-by", action="append", default=[], required=True)
    decision.add_argument("--summary", required=True)
    decision.add_argument("--rationale", required=True)
    decision.add_argument("--recorded-at")

    handoff = sub.add_parser("record-handoff")
    handoff.add_argument("--cycle-id", required=True)
    handoff.add_argument("--handoff-id", required=True)
    handoff.add_argument("--work-item-id", required=True)
    handoff.add_argument("--from-member", required=True)
    handoff.add_argument("--to-member", required=True)
    handoff.add_argument("--summary", required=True)
    handoff.add_argument("--next-action", required=True)
    handoff.add_argument("--artifact", action="append", default=[])
    handoff.add_argument("--recorded-at")

    contribution = sub.add_parser("record-contribution")
    contribution.add_argument("--contribution-id", required=True)
    contribution.add_argument("--work-item-id", required=True)
    contribution.add_argument("--recorded-by", required=True)
    contribution.add_argument("--contributor-type", choices=sorted(CONTRIBUTOR_TYPES), required=True)
    contribution.add_argument("--contributor-id", required=True)
    contribution.add_argument("--contribution-kind", choices=sorted(CONTRIBUTION_KINDS), required=True)
    contribution.add_argument("--role", required=True)
    contribution.add_argument("--statement", required=True)
    contribution.add_argument("--artifact", action="append", default=[])
    contribution.add_argument("--recorded-at")

    amendment = sub.add_parser("record-amendment")
    amendment.add_argument("--cycle-id", required=True)
    amendment.add_argument("--amendment-id", required=True)
    amendment.add_argument("--author", required=True)
    amendment.add_argument("--target", required=True)
    amendment.add_argument("--reason", required=True)
    amendment.add_argument("--body-file", required=True)
    amendment.add_argument("--recorded-at")

    close = sub.add_parser("close-cycle")
    close.add_argument("--cycle-id", required=True)
    close.add_argument("--meeting-id", required=True)
    close.add_argument("--closed-by", action="append", default=[], required=True)
    close.add_argument("--verdict", choices=("CONTINUE", "PAUSE", "STOP", "SPIN_OUT"), required=True)
    close.add_argument("--capture-mode-review", choices=sorted(CAPTURE_REVIEW_DECISIONS), required=True)
    close.add_argument("--closed-at")
    close.add_argument("--next-cycle-at")
    return parser


def execute(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    handlers: Dict[str, Callable[..., Dict[str, Any]]] = {
        "bootstrap-from-profile": lambda selected_root, _: bootstrap_from_profile(selected_root),
        "validate": lambda selected_root, _: validate_lab_state(selected_root),
        "prepare-cycle": prepare_cycle,
        "authorize-cycle": authorize_cycle,
        "record-minutes": record_minutes,
        "create-work-item": create_work_item,
        "transition-work-item": transition_work_item,
        "record-decision": record_decision,
        "record-handoff": record_handoff,
        "record-contribution": record_contribution,
        "record-amendment": record_amendment,
        "close-cycle": close_cycle,
    }
    return handlers[args.command](root, args)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        root = root_path(args.root)
        if args.command == "validate":
            result = execute(root, args)
        else:
            with FileLock(root / "collaboration/.team-collaboration.lock", "team collaboration"):
                result = execute(root, args)
    except CollaborationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(result.get("status", "OK"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
