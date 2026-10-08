#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
ROUND_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
ATTEMPT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

PROTOCOL_VERSION = 1
ACTION_ID = "run-rounds.v1"
ACTION_VERSION = "1.0.0"
MODEL = "gpt-5.6-sol"
REASONING_EFFORT = "ultra"
GUARD_POLICY_VERSION = 2
IGNORED_MACOS_METADATA_BASENAME = ".DS_Store"

MAX_SCOPE_INPUT_BYTES = 16 * 1024
MAX_RESULT_INPUT_BYTES = 32 * 1024
MAX_PROJECTION_BYTES = 32 * 1024
MAX_GUARD_START_BYTES = 16 * 1024 * 1024
MAX_SCOPE_CHARS = 12_000
MAX_SCOPE_UTF8_BYTES = 12_000
MAX_SUMMARY_CHARS = 4_096
MAX_SUMMARY_UTF8_BYTES = 4_096
MAX_NEXT_STEP_CHARS = 2_048
MAX_NEXT_STEP_UTF8_BYTES = 2_048
MAX_BLOCKER_CHARS = 1_024
MAX_BLOCKER_UTF8_BYTES = 1_024
MAX_RELATIVE_PATH_UTF8_BYTES = 4_096
MAX_CHANGED_PATHS = 128
MAX_BLOCKERS = 16
MAX_GUARD_RECORDS = 10_000
MAX_GUARD_FILE_BYTES = 64 * 1024 * 1024
MAX_GUARD_TOTAL_BYTES = 512 * 1024 * 1024
TRANSITION_LOCK_TIMEOUT_SECONDS = 15.0
TRANSITION_LOCK_POLL_SECONDS = 0.025

COMPATIBILITY_MARKER = {
    "schema_version": 1,
    "protocol_version": 1,
    "actions": ["propose-rounds", "run-rounds", "collect-rounds"],
    "projection_path_template": "research/rounds/{round_id}/control_room_status.json",
}

PROJECTION_STATUSES = {
    "CHECKPOINTED",
    "COMPLETED",
    "PARTIAL",
    "BLOCKED",
    "FAILED",
    "CANCELLED",
}
CHECKPOINT_REQUIRED_STATUSES = {"CHECKPOINTED", "COMPLETED", "PARTIAL", "BLOCKED"}
RETRYABLE_STATUSES = {"FAILED", "BLOCKED", "CANCELLED"}

# A research round may change ordinary live research state. Everything else is
# protected by the complement of this allowlist. Narrow explicit denials take
# precedence over broad live-state prefixes.
LIVE_PREFIXES = (
    "00_INBOX_TO_ANALYZE/",
    "sources/",
    "paper/",
    "research_reports/",
    "talks/",
    "research/",
    "results/",
    "problems/active/",
    "problems/backlog/",
    "problems/closed/",
    "decisions/",
    "portfolio/",
    "collaboration/",
    "runs/reports/",
    "runs/traces/",
    "runs/interaction_cards/",
)
LIVE_EXACT = {
    "knowledge/control_room_summary.json",
    "knowledge/results_ledger.yaml",
    "knowledge/conjectures_ledger.yaml",
    "knowledge/examples_ledger.yaml",
    "knowledge/open_questions.yaml",
    "knowledge/research_state.yaml",
    "knowledge/resume.md",
    "knowledge/laboratory_overview.md",
    "knowledge/laboratory_survey_state.json",
    "knowledge/source_map.md",
    "knowledge/notation.md",
    "knowledge/glossary.md",
    "knowledge/known_warnings.md",
    "knowledge/assumptions_and_conventions.md",
}
PROTECTED_EXACT = {
    "sources/TRUST_TIERS.md",
}
ROUND_CONTROL_PREFIX = "research/rounds/"


class ResearchRoundError(RuntimeError):
    pass


class ExistingTargetError(ResearchRoundError):
    """An immutable create lost a no-replace publication race."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def pretty_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def is_exact_int(value: Any) -> bool:
    return type(value) is int


def _truncate_utf8(value: str, maximum_chars: int, maximum_bytes: int) -> str:
    bounded = value[:maximum_chars]
    encoded = bounded.encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return bounded
    encoded = encoded[:maximum_bytes]
    while True:
        try:
            return encoded.decode("utf-8")
        except UnicodeDecodeError as exc:
            encoded = encoded[:exc.start]


def _reject_duplicate_keys(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        _require_unicode_scalars(key, "JSON object key")
        if key in result:
            raise ResearchRoundError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _require_unicode_scalars(value: Any, label: str) -> None:
    """Reject JSON strings that contain unpaired UTF-16 surrogate code points.

    Python's JSON decoder accepts escaped lone surrogates even though they
    cannot be encoded as canonical UTF-8.  Walk keys as well as values at the
    parse boundary so every later digest and durable serialization operates on
    Unicode scalar values only.
    """

    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ResearchRoundError(f"{label} contains a lone Unicode surrogate")
        return
    if isinstance(value, list):
        for item in value:
            _require_unicode_scalars(item, label)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _require_unicode_scalars(key, label)
            _require_unicode_scalars(item, label)


def parse_json_bytes(value: bytes, label: str, maximum: int) -> Dict[str, Any]:
    if len(value) > maximum:
        raise ResearchRoundError(f"{label} exceeds {maximum} bytes")
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResearchRoundError(f"{label} is not UTF-8: {exc}") from exc
    try:
        parsed = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except ResearchRoundError:
        raise
    except Exception as exc:
        raise ResearchRoundError(f"cannot parse {label}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ResearchRoundError(f"{label} must contain a JSON object")
    _require_unicode_scalars(parsed, label)
    return parsed


def require_exact_keys(
    value: Mapping[str, Any],
    label: str,
    required: Iterable[str],
    optional: Iterable[str] = (),
) -> None:
    required_set = set(required)
    allowed = required_set | set(optional)
    missing = sorted(required_set - set(value))
    unknown = sorted(set(value) - allowed)
    if missing:
        raise ResearchRoundError(f"{label} is missing keys: {', '.join(missing)}")
    if unknown:
        raise ResearchRoundError(f"{label} has unknown keys: {', '.join(unknown)}")


def require_string(
    value: Any,
    label: str,
    maximum: int,
    *,
    maximum_utf8_bytes: Optional[int] = None,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ResearchRoundError(f"{label} must be a string")
    if not allow_empty and not value.strip():
        raise ResearchRoundError(f"{label} must not be empty")
    if len(value) > maximum:
        raise ResearchRoundError(f"{label} exceeds {maximum} characters")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ResearchRoundError(f"{label} contains a lone Unicode surrogate")
    if maximum_utf8_bytes is not None and len(value.encode("utf-8")) > maximum_utf8_bytes:
        raise ResearchRoundError(
            f"{label} exceeds {maximum_utf8_bytes} UTF-8 bytes"
        )
    if "\x00" in value:
        raise ResearchRoundError(f"{label} contains NUL")
    return value


def validate_id(value: Any, label: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ResearchRoundError(f"invalid {label}: {value!r}")
    return value


def validate_relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ResearchRoundError(f"{label} must be a non-empty relative path")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ResearchRoundError(f"{label} contains a lone Unicode surrogate")
    if len(value.encode("utf-8")) > MAX_RELATIVE_PATH_UTF8_BYTES:
        raise ResearchRoundError(
            f"{label} exceeds {MAX_RELATIVE_PATH_UTF8_BYTES} UTF-8 bytes"
        )
    if CONTROL_RE.search(value) or "\\" in value:
        raise ResearchRoundError(f"{label} is not a portable relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ResearchRoundError(f"{label} is not a canonical relative path")
    normalized = "/".join(path.parts)
    if normalized != value:
        raise ResearchRoundError(f"{label} is not normalized")
    return normalized


def _inventory_path_order_key(relative: str) -> Tuple[str, ...]:
    """Match the component-wise ordering used by Path traversal."""
    return PurePosixPath(relative).parts


def root_identity() -> Dict[str, int]:
    try:
        info = ROOT.lstat()
    except OSError as exc:
        raise ResearchRoundError(f"cannot inspect laboratory root: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ResearchRoundError("laboratory root must be a real directory")
    return {"device": int(info.st_dev), "inode": int(info.st_ino)}


def require_same_root(expected: Mapping[str, Any]) -> None:
    current = root_identity()
    if current != dict(expected):
        raise ResearchRoundError("laboratory root identity changed during the research round")


def _directory_flags() -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


def _open_directory(parts: Sequence[str], *, create: bool = False) -> int:
    descriptor = os.open(str(ROOT), _directory_flags())
    try:
        for part in parts:
            try:
                child = os.open(part, _directory_flags(), dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, 0o755, dir_fd=descriptor)
                except FileExistsError:
                    # A concurrent helper may have created the same directory.
                    # Re-open it with O_NOFOLLOW and validate its type below.
                    pass
                child = os.open(part, _directory_flags(), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def ensure_directory(relative: str) -> Path:
    normalized = validate_relative_path(relative, "directory")
    descriptor = _open_directory(PurePosixPath(normalized).parts, create=True)
    os.close(descriptor)
    return ROOT / normalized


def safe_read_bytes(
    relative: str,
    label: str,
    *,
    maximum: Optional[int] = None,
    optional: bool = False,
) -> Optional[bytes]:
    normalized = validate_relative_path(relative, label)
    path = PurePosixPath(normalized)
    try:
        parent = _open_directory(path.parts[:-1])
    except FileNotFoundError:
        if optional:
            return None
        raise ResearchRoundError(f"missing {label}: {relative}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        try:
            descriptor = os.open(path.name, flags, dir_fd=parent)
        except FileNotFoundError:
            if optional:
                return None
            raise ResearchRoundError(f"missing {label}: {relative}")
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise ResearchRoundError(f"{label} must be a regular file")
            if maximum is not None and before.st_size > maximum:
                raise ResearchRoundError(f"{label} exceeds {maximum} bytes")
            chunks: List[bytes] = []
            total = 0
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if maximum is not None and total > maximum:
                    raise ResearchRoundError(f"{label} exceeds {maximum} bytes")
                chunks.append(chunk)
            after = os.fstat(descriptor)
            if (
                before.st_dev != after.st_dev
                or before.st_ino != after.st_ino
                or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_ctime_ns != after.st_ctime_ns
            ):
                raise ResearchRoundError(f"{label} changed while being read")
            return b"".join(chunks)
        finally:
            os.close(descriptor)
    finally:
        os.close(parent)


def safe_read_file_record(
    relative: str,
    label: str,
    *,
    maximum: int,
) -> Tuple[bytes, Dict[str, Any]]:
    """Read and hash one regular file through a no-follow parent descriptor."""

    normalized = validate_relative_path(relative, label)
    path = PurePosixPath(normalized)
    try:
        parent = _open_directory(path.parts[:-1])
    except OSError as exc:
        raise ResearchRoundError(f"cannot open parent for {label}: {exc}") from exc
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(path.name, flags, dir_fd=parent)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ResearchRoundError(f"{label} must be a regular file")
        if before.st_size > maximum:
            raise ResearchRoundError(f"{label} exceeds {maximum} bytes")
        chunks: List[bytes] = []
        total = 0
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise ResearchRoundError(f"{label} exceeds {maximum} bytes")
            chunks.append(chunk)
            digest.update(chunk)
        after = os.fstat(descriptor)
        path_after = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or before.st_dev != path_after.st_dev
            or before.st_ino != path_after.st_ino
        ):
            raise ResearchRoundError(f"{label} changed while being read")
        return b"".join(chunks), {
            "path": normalized,
            "type": "file",
            "mode": stat.S_IMODE(before.st_mode),
            "size": int(before.st_size),
            "sha256": digest.hexdigest(),
            "device": int(before.st_dev),
            "inode": int(before.st_ino),
            "nlink": int(before.st_nlink),
        }
    except OSError as exc:
        raise ResearchRoundError(f"cannot read {label}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent)


def safe_read_object(
    relative: str,
    label: str,
    *,
    maximum: int = 1024 * 1024,
    optional: bool = False,
) -> Optional[Dict[str, Any]]:
    data = safe_read_bytes(relative, label, maximum=maximum, optional=optional)
    if data is None:
        return None
    return parse_json_bytes(data, label, maximum)


def safe_regular_mode(relative: str, label: str) -> int:
    normalized = validate_relative_path(relative, label)
    path = PurePosixPath(normalized)
    try:
        parent = _open_directory(path.parts[:-1])
    except OSError as exc:
        raise ResearchRoundError(f"cannot open parent for {label}: {exc}") from exc
    try:
        try:
            info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        except OSError as exc:
            raise ResearchRoundError(f"cannot inspect {label}: {exc}") from exc
        if not stat.S_ISREG(info.st_mode):
            raise ResearchRoundError(f"{label} must be a regular file")
        return stat.S_IMODE(info.st_mode)
    finally:
        os.close(parent)


def atomic_create(relative: str, data: bytes, *, mode: int = 0o444) -> None:
    normalized = validate_relative_path(relative, "create target")
    path = PurePosixPath(normalized)
    parent = _open_directory(path.parts[:-1], create=True)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor: Optional[int] = None
    temporary = f".{path.name}.create-{uuid.uuid4().hex}"
    try:
        descriptor = os.open(temporary, flags, mode, dir_fd=parent)
        offset = 0
        while offset < len(data):
            offset += os.write(descriptor, data[offset:])
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        try:
            os.link(
                temporary,
                path.name,
                src_dir_fd=parent,
                dst_dir_fd=parent,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise ExistingTargetError(
                f"refusing to overwrite existing file: {relative}"
            ) from exc
        os.fsync(parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass
        else:
            os.fsync(parent)
        os.close(parent)


def atomic_replace(
    relative: str,
    data: bytes,
    *,
    expected_sha256: Optional[str],
    mode: int = 0o644,
) -> None:
    normalized = validate_relative_path(relative, "replace target")
    current = safe_read_bytes(relative, "replace target", optional=True)
    current_sha = sha256_bytes(current) if current is not None else None
    if current_sha != expected_sha256:
        raise ResearchRoundError(f"replace target changed before write: {relative}")
    path = PurePosixPath(normalized)
    parent = _open_directory(path.parts[:-1], create=True)
    temporary = f".{path.name}.tmp-{uuid.uuid4().hex}"
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(temporary, flags, mode, dir_fd=parent)
        offset = 0
        while offset < len(data):
            offset += os.write(descriptor, data[offset:])
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None

        current_again = safe_read_bytes(relative, "replace target", optional=True)
        current_again_sha = sha256_bytes(current_again) if current_again is not None else None
        if current_again_sha != expected_sha256:
            raise ResearchRoundError(f"replace target changed during write: {relative}")
        os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass
        os.close(parent)


def safe_unlink(relative: str, *, expected_sha256: str) -> None:
    current = safe_read_bytes(relative, "unlink target", optional=False)
    assert current is not None
    if sha256_bytes(current) != expected_sha256:
        raise ResearchRoundError(f"unlink target changed before removal: {relative}")
    path = PurePosixPath(validate_relative_path(relative, "unlink target"))
    parent = _open_directory(path.parts[:-1])
    try:
        info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise ResearchRoundError(f"unlink target is not a regular file: {relative}")
        os.unlink(path.name, dir_fd=parent)
    finally:
        os.close(parent)


def validate_compatibility_marker() -> None:
    marker = safe_read_object(
        ".lab/control_room_actions.json",
        "Control Room compatibility marker",
        maximum=8 * 1024,
    )
    if (
        marker != COMPATIBILITY_MARKER
        or not is_exact_int(marker.get("schema_version"))
        or not is_exact_int(marker.get("protocol_version"))
    ):
        raise ResearchRoundError("incompatible .lab/control_room_actions.json")
    if safe_regular_mode(
        ".lab/control_room_actions.json",
        "Control Room compatibility marker",
    ) != 0o644:
        raise ResearchRoundError("Control Room compatibility marker must have mode 0644")


def lab_id() -> str:
    profile = safe_read_object("LAB_PROFILE.json", "LAB_PROFILE.json", maximum=1024 * 1024)
    assert profile is not None
    value = profile.get("lab")
    if not isinstance(value, dict):
        raise ResearchRoundError("LAB_PROFILE.lab must be an object")
    identifier = value.get("id")
    return require_string(identifier, "LAB_PROFILE.lab.id", 256)


def round_root(round_id: str) -> str:
    return f"research/rounds/{round_id}"


def plan_path(round_id: str) -> str:
    return f"{round_root(round_id)}/approved_plan.json"


def projection_path(round_id: str) -> str:
    return f"{round_root(round_id)}/control_room_status.json"


def attempt_root(round_id: str, attempt_id: str) -> str:
    return f"{round_root(round_id)}/attempts/{attempt_id}"


def guard_start_path(round_id: str, attempt_id: str) -> str:
    return f"{attempt_root(round_id, attempt_id)}/guard_start.json"


def result_path(round_id: str, attempt_id: str) -> str:
    return f"{attempt_root(round_id, attempt_id)}/result.json"


def guard_end_path(round_id: str, attempt_id: str) -> str:
    return f"{attempt_root(round_id, attempt_id)}/guard_end.json"


@contextmanager
def laboratory_transition_lock() -> Iterator[None]:
    """Serialize helper state transitions on an architecture-owned anchor.

    The compatibility marker is outside the research-write authorization. The
    kernel releases its flock on process exit, so there is no persistent or
    stale lock state to clean up. Acquisition is bounded so a wedged live helper
    fails visibly rather than blocking the Control Room forever.
    """

    try:
        parent = _open_directory((".lab",))
    except OSError as exc:
        raise ResearchRoundError(f"cannot open transition-lock anchor directory: {exc}") from exc
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    descriptor: Optional[int] = None
    acquired = False
    try:
        descriptor = os.open("control_room_actions.json", flags, dir_fd=parent)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ResearchRoundError("transition-lock marker must be a regular file")
        if (
            stat.S_IMODE(opened.st_mode) != 0o644
            or opened.st_size > 8 * 1024
            or opened.st_nlink != 1
        ):
            raise ResearchRoundError("transition-lock marker has unsafe mode, size, or link count")

        deadline = time.monotonic() + TRANSITION_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise ResearchRoundError(
                        f"timed out acquiring laboratory transition lock after "
                        f"{TRANSITION_LOCK_TIMEOUT_SECONDS:g} seconds"
                    ) from exc
                time.sleep(TRANSITION_LOCK_POLL_SECONDS)

        os.lseek(descriptor, 0, os.SEEK_SET)
        marker_chunks: List[bytes] = []
        marker_size = 0
        while True:
            chunk = os.read(descriptor, min(4096, 8 * 1024 + 1 - marker_size))
            if not chunk:
                break
            marker_chunks.append(chunk)
            marker_size += len(chunk)
            if marker_size > 8 * 1024:
                raise ResearchRoundError("transition-lock marker exceeds 8192 bytes")
        marker_raw = b"".join(marker_chunks)
        closed = os.fstat(descriptor)
        current = os.stat("control_room_actions.json", dir_fd=parent, follow_symlinks=False)
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_dev != opened.st_dev
            or current.st_ino != opened.st_ino
            or current.st_nlink != 1
            or stat.S_IMODE(current.st_mode) != 0o644
            or current.st_size != opened.st_size
            or opened.st_size != closed.st_size
            or opened.st_mtime_ns != closed.st_mtime_ns
            or opened.st_ctime_ns != closed.st_ctime_ns
        ):
            raise ResearchRoundError("transition-lock marker changed during acquisition")
        marker = parse_json_bytes(
            marker_raw,
            "Control Room compatibility marker",
            8 * 1024,
        )
        if (
            marker != COMPATIBILITY_MARKER
            or not is_exact_int(marker.get("schema_version"))
            or not is_exact_int(marker.get("protocol_version"))
        ):
            raise ResearchRoundError("incompatible transition-lock marker")
        yield
    except OSError as exc:
        raise ResearchRoundError(f"cannot use safe laboratory transition lock: {exc}") from exc
    finally:
        if descriptor is not None:
            if acquired:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
        os.close(parent)


def is_research_writable(relative: str) -> bool:
    relative = validate_relative_path(relative, "research path")
    if relative == ROUND_CONTROL_PREFIX.rstrip("/") or relative.startswith(ROUND_CONTROL_PREFIX):
        return False
    if relative in PROTECTED_EXACT:
        return False
    if relative in LIVE_EXACT:
        return True
    return any(relative == prefix.rstrip("/") or relative.startswith(prefix) for prefix in LIVE_PREFIXES)


def is_architecture_inventory_excluded(relative: str) -> bool:
    if relative == ROUND_CONTROL_PREFIX.rstrip("/") or relative.startswith(ROUND_CONTROL_PREFIX):
        return True
    return is_research_writable(relative)


def is_unhashed_bulk_subtree_root(relative: str) -> bool:
    """Identify exact bulk stores whose root remains protected but contents do not."""

    relative = validate_relative_path(relative, "architecture bulk path")
    if relative == ".git/objects":
        return True
    parts = PurePosixPath(relative).parts
    return bool(parts) and parts[-1] == ".lake"


def _ignore_safe_macos_metadata(
    path: Path,
    relative: str,
    info: os.stat_result,
    root_device: int,
) -> bool:
    """Ignore only Finder's exact, safely pinned single-link regular file."""

    if path.name != IGNORED_MACOS_METADATA_BASENAME:
        return False
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(str(path), flags)
        opened = os.fstat(descriptor)
        closed = os.fstat(descriptor)
        current = path.lstat()
    except OSError as exc:
        raise ResearchRoundError(
            f"unsafe {IGNORED_MACOS_METADATA_BASENAME} path: {relative}"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    identities = (
        (info.st_dev, info.st_ino),
        (opened.st_dev, opened.st_ino),
        (closed.st_dev, closed.st_ino),
        (current.st_dev, current.st_ino),
    )
    if (
        any(identity != identities[0] for identity in identities[1:])
        or any(
            not stat.S_ISREG(candidate.st_mode)
            or candidate.st_dev != root_device
            or candidate.st_nlink != 1
            for candidate in (info, opened, closed, current)
        )
    ):
        raise ResearchRoundError(
            f"unsafe {IGNORED_MACOS_METADATA_BASENAME} path: {relative}"
        )
    return True


def _hash_regular_file(path: Path, relative: str, info: os.stat_result) -> Dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(str(path), flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ResearchRoundError(f"protected path is not a regular file: {relative}")
        if opened.st_dev != info.st_dev or opened.st_ino != info.st_ino:
            raise ResearchRoundError(f"protected file changed before inventory: {relative}")
        if opened.st_size > MAX_GUARD_FILE_BYTES:
            raise ResearchRoundError(
                f"guard file exceeds {MAX_GUARD_FILE_BYTES} bytes: {relative}"
            )
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        closed = os.fstat(descriptor)
        try:
            path_after = path.lstat()
        except OSError as exc:
            raise ResearchRoundError(f"protected file disappeared during inventory: {relative}") from exc
        if (
            opened.st_dev != closed.st_dev
            or opened.st_ino != closed.st_ino
            or opened.st_size != closed.st_size
            or opened.st_mtime_ns != closed.st_mtime_ns
            or opened.st_ctime_ns != closed.st_ctime_ns
            or opened.st_dev != path_after.st_dev
            or opened.st_ino != path_after.st_ino
        ):
            raise ResearchRoundError(f"protected file changed during inventory: {relative}")
        return {
            "path": relative,
            "type": "file",
            "mode": stat.S_IMODE(opened.st_mode),
            "size": int(opened.st_size),
            "sha256": digest.hexdigest(),
            "device": int(opened.st_dev),
            "inode": int(opened.st_ino),
            "nlink": int(opened.st_nlink),
        }
    finally:
        os.close(descriptor)


def protected_inventory() -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    total_bytes = 0
    root_device = int(root_identity()["device"])

    def add_record(record: Dict[str, Any]) -> None:
        nonlocal total_bytes
        if len(records) >= MAX_GUARD_RECORDS:
            raise ResearchRoundError(
                f"guard inventory exceeds {MAX_GUARD_RECORDS} records"
            )
        size = record.get("size", 0)
        if not is_exact_int(size) or size < 0:
            raise ResearchRoundError("guard inventory produced an invalid size")
        if total_bytes + size > MAX_GUARD_TOTAL_BYTES:
            raise ResearchRoundError(
                f"guard inventory exceeds {MAX_GUARD_TOTAL_BYTES} total bytes"
            )
        total_bytes += size
        records.append(record)

    def visit(directory: Path, prefix: str) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise ResearchRoundError(f"cannot scan laboratory path {prefix or '.'}: {exc}") from exc
        for entry in entries:
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            if CONTROL_RE.search(relative) or "\\" in relative:
                raise ResearchRoundError(f"unsafe filesystem path: {relative!r}")
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise ResearchRoundError(f"cannot inspect {relative}: {exc}") from exc
            if _ignore_safe_macos_metadata(
                Path(entry.path), relative, info, root_device
            ):
                continue
            if stat.S_ISLNK(info.st_mode):
                raise ResearchRoundError(f"symlink is forbidden in laboratory: {relative}")
            if stat.S_ISDIR(info.st_mode):
                if not is_architecture_inventory_excluded(relative):
                    add_record(
                        {
                            "path": relative,
                            "type": "directory",
                            "mode": stat.S_IMODE(info.st_mode),
                            "size": 0,
                            "sha256": None,
                        }
                    )
                if is_unhashed_bulk_subtree_root(relative):
                    continue
                visit(Path(entry.path), relative)
                continue
            if not stat.S_ISREG(info.st_mode):
                raise ResearchRoundError(f"special file is forbidden in laboratory: {relative}")
            if not is_architecture_inventory_excluded(relative):
                add_record(_hash_regular_file(Path(entry.path), relative, info))

    visit(ROOT, "")
    return records


def checkpoint_inventory() -> List[Dict[str, Any]]:
    root = ROOT / "research/checkpoints"
    if not root.exists():
        return []
    if root.is_symlink() or not root.is_dir():
        raise ResearchRoundError("research/checkpoints must be a real directory")
    records: List[Dict[str, Any]] = []
    total_bytes = 0
    root_device = int(root_identity()["device"])
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(ROOT).as_posix()
        info = path.lstat()
        if _ignore_safe_macos_metadata(path, relative, info, root_device):
            continue
        if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise ResearchRoundError(f"unsafe checkpoint path: {relative}")
        if stat.S_ISREG(info.st_mode):
            if len(records) >= MAX_GUARD_RECORDS:
                raise ResearchRoundError(
                    f"checkpoint guard inventory exceeds {MAX_GUARD_RECORDS} records"
                )
            record = _hash_regular_file(path, relative, info)
            size = int(record["size"])
            if total_bytes + size > MAX_GUARD_TOTAL_BYTES:
                raise ResearchRoundError(
                    f"checkpoint guard inventory exceeds {MAX_GUARD_TOTAL_BYTES} total bytes"
                )
            total_bytes += size
            records.append(record)
    return records


def round_control_inventory(round_id: str, attempt_id: str) -> List[Dict[str, Any]]:
    base = ROOT / "research/rounds"
    if not base.exists():
        return []
    if base.is_symlink() or not base.is_dir():
        raise ResearchRoundError("research/rounds must be a real directory")
    excluded_exact = {
        plan_path(round_id),
        projection_path(round_id),
    }
    excluded_attempt = attempt_root(round_id, attempt_id)
    records: List[Dict[str, Any]] = []
    total_bytes = 0
    root_device = int(root_identity()["device"])
    for path in sorted(base.rglob("*")):
        relative = path.relative_to(ROOT).as_posix()
        if (
            relative in excluded_exact
            or relative == excluded_attempt
            or relative.startswith(excluded_attempt + "/")
        ):
            continue
        info = path.lstat()
        if _ignore_safe_macos_metadata(path, relative, info, root_device):
            continue
        if stat.S_ISLNK(info.st_mode):
            raise ResearchRoundError(f"symlink is forbidden in round control state: {relative}")
        if stat.S_ISDIR(info.st_mode):
            record = {
                "path": relative,
                "type": "directory",
                "mode": stat.S_IMODE(info.st_mode),
                "size": 0,
                "sha256": None,
            }
        elif stat.S_ISREG(info.st_mode):
            record = _hash_regular_file(path, relative, info)
        else:
            raise ResearchRoundError(f"special file is forbidden in round control state: {relative}")
        if len(records) >= MAX_GUARD_RECORDS:
            raise ResearchRoundError(
                f"round-control inventory exceeds {MAX_GUARD_RECORDS} records"
            )
        size = int(record["size"])
        if total_bytes + size > MAX_GUARD_TOTAL_BYTES:
            raise ResearchRoundError(
                f"round-control inventory exceeds {MAX_GUARD_TOTAL_BYTES} total bytes"
            )
        total_bytes += size
        records.append(record)
    return records


def inventory_digest(records: Sequence[Mapping[str, Any]]) -> str:
    return sha256_bytes(canonical_json(list(records)))


def inventory_changes(
    before: Sequence[Mapping[str, Any]],
    after: Sequence[Mapping[str, Any]],
) -> List[Dict[str, str]]:
    before_map = {str(item.get("path")): dict(item) for item in before}
    after_map = {str(item.get("path")): dict(item) for item in after}
    changes: List[Dict[str, str]] = []
    for relative in sorted(set(before_map) | set(after_map)):
        if relative not in before_map:
            changes.append({"path": relative, "change": "ADDED"})
        elif relative not in after_map:
            changes.append({"path": relative, "change": "REMOVED"})
        elif before_map[relative] != after_map[relative]:
            changes.append({"path": relative, "change": "CHANGED"})
    return changes


def validate_plan(value: Mapping[str, Any], round_id: Optional[str] = None) -> Dict[str, Any]:
    required = {
        "schema_version",
        "protocol_version",
        "round_id",
        "request_id",
        "lab_id",
        "action_id",
        "action_version",
        "model",
        "reasoning_effort",
        "authorization",
        "scope",
        "scope_sha256",
        "created_at",
        "checkpoint_required",
        "architecture_guard_policy_version",
    }
    require_exact_keys(value, "approved plan", required)
    if (
        not is_exact_int(value.get("schema_version"))
        or value.get("schema_version") != 1
        or not is_exact_int(value.get("protocol_version"))
        or value.get("protocol_version") != PROTOCOL_VERSION
    ):
        raise ResearchRoundError("approved plan schema/protocol version is invalid")
    identifier = validate_id(value.get("round_id"), "round_id", ROUND_ID_RE)
    if round_id is not None and identifier != round_id:
        raise ResearchRoundError("approved plan round_id disagrees with its directory")
    validate_id(value.get("request_id"), "request_id", ROUND_ID_RE)
    require_string(value.get("lab_id"), "approved plan lab_id", 256)
    if value.get("action_id") != ACTION_ID or value.get("action_version") != ACTION_VERSION:
        raise ResearchRoundError("approved plan action identity is invalid")
    if value.get("model") != MODEL or value.get("reasoning_effort") != REASONING_EFFORT:
        raise ResearchRoundError("approved plan model/effort is invalid")
    authorization = value.get("authorization")
    if not isinstance(authorization, dict):
        raise ResearchRoundError("approved plan authorization must be an object")
    require_exact_keys(authorization, "approved plan authorization", {"source", "approved_at"})
    if authorization.get("source") != "control-room-button":
        raise ResearchRoundError("approved plan authorization source is invalid")
    require_string(authorization.get("approved_at"), "approved_at", 64)
    scope = require_string(
        value.get("scope"),
        "approved plan scope",
        MAX_SCOPE_CHARS,
        maximum_utf8_bytes=MAX_SCOPE_UTF8_BYTES,
    )
    expected_scope_digest = sha256_bytes(scope.encode("utf-8"))
    if value.get("scope_sha256") != expected_scope_digest:
        raise ResearchRoundError("approved plan scope digest mismatch")
    require_string(value.get("created_at"), "approved plan created_at", 64)
    if value.get("checkpoint_required") is not True:
        raise ResearchRoundError("approved plan must require a checkpoint")
    if (
        not is_exact_int(value.get("architecture_guard_policy_version"))
        or value.get("architecture_guard_policy_version") != GUARD_POLICY_VERSION
    ):
        raise ResearchRoundError("approved plan guard policy version is invalid")
    return dict(value)


def read_plan(round_id: str) -> Dict[str, Any]:
    raw = safe_read_bytes(
        plan_path(round_id), "approved plan", maximum=MAX_SCOPE_INPUT_BYTES * 2
    )
    assert raw is not None
    if safe_regular_mode(plan_path(round_id), "approved plan") != 0o444:
        raise ResearchRoundError("approved plan must have immutable mode 0444")
    plan = validate_plan(
        parse_json_bytes(raw, "approved plan", MAX_SCOPE_INPUT_BYTES * 2),
        round_id,
    )
    if raw != pretty_json(plan):
        raise ResearchRoundError("approved plan is not canonical JSON")
    return plan


def validate_result_input(value: Mapping[str, Any], round_id: str) -> Dict[str, Any]:
    required = {
        "schema_version",
        "round_id",
        "status",
        "summary",
        "changed_paths",
        "checkpoint_path",
        "blockers",
        "next_step",
    }
    require_exact_keys(value, "research-round result", required)
    if not is_exact_int(value.get("schema_version")) or value.get("schema_version") != 1:
        raise ResearchRoundError("research-round result schema_version must equal 1")
    if validate_id(value.get("round_id"), "round_id", ROUND_ID_RE) != round_id:
        raise ResearchRoundError("result round_id disagrees with requested round")
    status_value = value.get("status")
    if status_value not in PROJECTION_STATUSES:
        raise ResearchRoundError(f"invalid result status: {status_value!r}")
    summary = require_string(
        value.get("summary"),
        "result summary",
        MAX_SUMMARY_CHARS,
        maximum_utf8_bytes=MAX_SUMMARY_UTF8_BYTES,
    )
    changed = value.get("changed_paths")
    if not isinstance(changed, list) or len(changed) > MAX_CHANGED_PATHS:
        raise ResearchRoundError("changed_paths must be a bounded array")
    changed_paths: List[str] = []
    for index, item in enumerate(changed):
        relative = validate_relative_path(item, f"changed_paths[{index}]")
        if not is_research_writable(relative):
            raise ResearchRoundError(f"reported changed path is architecture/policy protected: {relative}")
        changed_paths.append(relative)
    if len(set(changed_paths)) != len(changed_paths):
        raise ResearchRoundError("changed_paths must be unique")
    checkpoint = value.get("checkpoint_path")
    if checkpoint is not None:
        checkpoint = validate_relative_path(checkpoint, "checkpoint_path")
        if not checkpoint.startswith("research/checkpoints/"):
            raise ResearchRoundError("checkpoint_path must be under research/checkpoints/")
        if changed_paths.count(checkpoint) != 1:
            raise ResearchRoundError(
                "checkpoint_path must appear exactly once in changed_paths"
            )
    blockers_value = value.get("blockers")
    if not isinstance(blockers_value, list) or len(blockers_value) > MAX_BLOCKERS:
        raise ResearchRoundError("blockers must be a bounded array")
    blockers = [
        require_string(
            item,
            f"blockers[{index}]",
            MAX_BLOCKER_CHARS,
            maximum_utf8_bytes=MAX_BLOCKER_UTF8_BYTES,
        )
        for index, item in enumerate(blockers_value)
    ]
    next_step = require_string(
        value.get("next_step"),
        "next_step",
        MAX_NEXT_STEP_CHARS,
        maximum_utf8_bytes=MAX_NEXT_STEP_UTF8_BYTES,
        allow_empty=status_value in {"FAILED", "CANCELLED"},
    )
    normalized = {
        "schema_version": 1,
        "round_id": round_id,
        "status": status_value,
        "summary": summary,
        "changed_paths": changed_paths,
        "checkpoint_path": checkpoint,
        "blockers": blockers,
        "next_step": next_step,
    }
    if len(canonical_json(normalized)) > MAX_RESULT_INPUT_BYTES:
        raise ResearchRoundError(
            f"research-round result exceeds {MAX_RESULT_INPUT_BYTES} canonical UTF-8 bytes"
        )
    return normalized


def projection_digest(value: Mapping[str, Any], approved_plan_sha256: str) -> str:
    if not isinstance(approved_plan_sha256, str) or not SHA256_RE.fullmatch(
        approved_plan_sha256
    ):
        raise ResearchRoundError("approved plan SHA-256 is invalid")
    payload = {
        key: item
        for key, item in value.items()
        if key not in {"generated_at", "source_digest_sha256"}
    }
    return sha256_bytes(
        canonical_json(
            {
                "approved_plan_sha256": approved_plan_sha256,
                "projection": payload,
            }
        )
    )


def make_projection(
    result: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    plan_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    bound_plan_sha256 = plan_sha256 or sha256_bytes(pretty_json(dict(plan)))
    projection = {
        "schema_version": 1,
        "round_id": result["round_id"],
        "lab_id": plan["lab_id"],
        "action_id": ACTION_ID,
        "action_version": ACTION_VERSION,
        "generated_at": utc_now(),
        "status": result["status"],
        "summary": result["summary"],
        "changed_paths": result["changed_paths"],
        "checkpoint_path": result["checkpoint_path"],
        "blockers": result["blockers"],
        "next_step": result["next_step"],
        "source_digest_sha256": "",
    }
    projection["source_digest_sha256"] = projection_digest(
        projection, bound_plan_sha256
    )
    validate_projection(
        projection,
        str(result["round_id"]),
        plan_sha256=bound_plan_sha256,
    )
    encoded = pretty_json(projection)
    if len(encoded) > MAX_PROJECTION_BYTES:
        raise ResearchRoundError("control_room_status.json exceeds 32768 bytes")
    return projection


def validate_projection(
    value: Mapping[str, Any],
    round_id: Optional[str] = None,
    *,
    plan_sha256: str,
) -> Dict[str, Any]:
    required = {
        "schema_version",
        "round_id",
        "lab_id",
        "action_id",
        "action_version",
        "generated_at",
        "status",
        "summary",
        "changed_paths",
        "checkpoint_path",
        "blockers",
        "next_step",
        "source_digest_sha256",
    }
    require_exact_keys(value, "Control Room projection", required)
    if not is_exact_int(value.get("schema_version")) or value.get("schema_version") != 1:
        raise ResearchRoundError("projection schema_version must equal 1")
    identifier = validate_id(value.get("round_id"), "round_id", ROUND_ID_RE)
    if round_id is not None and identifier != round_id:
        raise ResearchRoundError("projection round_id disagrees with its directory")
    require_string(value.get("lab_id"), "projection lab_id", 256)
    if value.get("action_id") != ACTION_ID or value.get("action_version") != ACTION_VERSION:
        raise ResearchRoundError("projection action identity is invalid")
    require_string(value.get("generated_at"), "projection generated_at", 64)
    result_shape = {
        "schema_version": 1,
        "round_id": identifier,
        "status": value.get("status"),
        "summary": value.get("summary"),
        "changed_paths": value.get("changed_paths"),
        "checkpoint_path": value.get("checkpoint_path"),
        "blockers": value.get("blockers"),
        "next_step": value.get("next_step"),
    }
    validate_result_input(result_shape, identifier)
    digest = value.get("source_digest_sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise ResearchRoundError("projection source_digest_sha256 is invalid")
    if digest != projection_digest(value, plan_sha256):
        raise ResearchRoundError("projection source digest mismatch")
    if len(pretty_json(dict(value))) > MAX_PROJECTION_BYTES:
        raise ResearchRoundError("projection exceeds 32768 bytes")
    return dict(value)


def read_projection(
    round_id: str,
    *,
    optional: bool = True,
    plan_sha256: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    raw = safe_read_bytes(
        projection_path(round_id),
        "Control Room projection",
        maximum=MAX_PROJECTION_BYTES,
        optional=optional,
    )
    if raw is None:
        return None
    if plan_sha256 is None:
        plan = read_plan(round_id)
        plan_sha256 = sha256_bytes(pretty_json(plan))
    if safe_regular_mode(projection_path(round_id), "Control Room projection") != 0o644:
        raise ResearchRoundError("Control Room projection must have mode 0644")
    projection = validate_projection(
        parse_json_bytes(raw, "Control Room projection", MAX_PROJECTION_BYTES),
        round_id,
        plan_sha256=plan_sha256,
    )
    if raw != pretty_json(projection):
        raise ResearchRoundError("Control Room projection is not canonical JSON")
    return projection


def validate_checkpoint(
    result: Mapping[str, Any],
    guard_start: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    status_value = str(result["status"])
    relative = result.get("checkpoint_path")
    if status_value in CHECKPOINT_REQUIRED_STATUSES and relative is None:
        raise ResearchRoundError(f"status {status_value} requires an append-only checkpoint")
    if relative is None:
        return None
    checkpoint = validate_relative_path(relative, "checkpoint_path")
    if not checkpoint.startswith("research/checkpoints/"):
        raise ResearchRoundError("checkpoint_path must be under research/checkpoints/")
    current_root_before = root_identity()
    raw, current_record = safe_read_file_record(
        checkpoint,
        "research checkpoint",
        maximum=2 * 1024 * 1024,
    )
    current_root_after = root_identity()
    if current_root_after != current_root_before:
        raise ResearchRoundError(
            "laboratory root identity changed while validating the checkpoint"
        )
    if current_record["device"] != current_root_before["device"]:
        raise ResearchRoundError("checkpoint must remain on the laboratory root device")
    if result["round_id"].encode("utf-8") not in raw:
        raise ResearchRoundError("checkpoint does not bind the round_id")
    old_records = validate_inventory_records(
        guard_start.get("checkpoint_inventory", []),
        "guard_start checkpoint_inventory",
        files_only=True,
    )
    old_paths = {item["path"] for item in old_records}
    if checkpoint in old_paths:
        raise ResearchRoundError("checkpoint_path existed before this attempt; checkpoints are append-only")
    if current_record["nlink"] != 1:
        raise ResearchRoundError("checkpoint must be a new single-link regular file")
    old_inodes = {(item["device"], item["inode"]) for item in old_records}
    if (current_record["device"], current_record["inode"]) in old_inodes:
        raise ResearchRoundError("checkpoint inode existed before this attempt")
    return current_record


def terminal_checkpoint_record_matches(
    current_record: Mapping[str, Any],
    recorded_record: Mapping[str, Any],
    historical_root: Mapping[str, Any],
) -> bool:
    """Accept one coherent APFS device-number rebinding and nothing broader.

    A mounted APFS project can retain every inode and byte while ``st_dev`` is
    renumbered.  Historical terminal evidence remains valid in that narrow
    case: the root inode is unchanged, the recorded checkpoint was on the old
    root device, the live checkpoint is on the current root device, and every
    other bound field is exact.  Copies, inode substitutions, hardlinks,
    content changes, and mixed-device trees still fail closed.
    """

    current = dict(current_record)
    recorded = dict(recorded_record)
    current_root = root_identity()
    if (
        set(historical_root) != {"device", "inode"}
        or not all(
            is_exact_int(historical_root.get(field))
            for field in ("device", "inode")
        )
        or historical_root["device"] < 0
        or historical_root["inode"] < 1
        or historical_root["inode"] != current_root["inode"]
    ):
        return False
    if current == recorded:
        return (
            historical_root["device"] == current_root["device"]
            and current.get("device") == current_root["device"]
        )
    if (
        historical_root["device"] == current_root["device"]
        or recorded.get("device") != historical_root["device"]
        or current.get("device") != current_root["device"]
    ):
        return False
    return all(
        current.get(field) == recorded.get(field)
        for field in ("path", "type", "mode", "size", "sha256", "inode", "nlink")
    )


def validate_inventory_records(
    value: Any,
    label: str,
    *,
    files_only: bool = False,
) -> List[Dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_GUARD_RECORDS:
        raise ResearchRoundError(f"{label} must be a bounded array")
    records: List[Dict[str, Any]] = []
    paths: List[str] = []
    total_bytes = 0
    base_required = {"path", "type", "mode", "size", "sha256"}
    file_identity = {"device", "inode", "nlink"}
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ResearchRoundError(f"{label}[{index}] must be an object")
        kind = item.get("type")
        required = base_required | (file_identity if kind == "file" else set())
        require_exact_keys(item, f"{label}[{index}]", required)
        relative = validate_relative_path(item.get("path"), f"{label}[{index}].path")
        if kind not in ({"file"} if files_only else {"file", "directory"}):
            raise ResearchRoundError(f"{label}[{index}].type is invalid")
        integers: Dict[str, int] = {}
        integer_fields = ("mode", "size", "device", "inode", "nlink") if kind == "file" else ("mode", "size")
        for field in integer_fields:
            field_value = item.get(field)
            if not is_exact_int(field_value):
                raise ResearchRoundError(f"{label}[{index}].{field} must be an integer")
            integers[field] = field_value
        if not 0 <= integers["mode"] <= 0o7777:
            raise ResearchRoundError(f"{label}[{index}].mode is invalid")
        if integers["size"] < 0 or integers["size"] > MAX_GUARD_FILE_BYTES:
            raise ResearchRoundError(f"{label}[{index}].size is invalid")
        if kind == "file" and (
            integers["device"] < 0 or integers["inode"] < 0 or integers["nlink"] < 1
        ):
            raise ResearchRoundError(f"{label}[{index}] has invalid filesystem identity")
        digest = item.get("sha256")
        if kind == "file":
            if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                raise ResearchRoundError(f"{label}[{index}].sha256 is invalid")
        elif integers["size"] != 0 or digest is not None:
            raise ResearchRoundError(f"{label}[{index}] directory record is invalid")
        total_bytes += integers["size"]
        if total_bytes > MAX_GUARD_TOTAL_BYTES:
            raise ResearchRoundError(f"{label} exceeds the total-byte bound")
        paths.append(relative)
        records.append(dict(item))
    if (
        paths != sorted(paths, key=_inventory_path_order_key)
        or len(paths) != len(set(paths))
    ):
        raise ResearchRoundError(f"{label} paths must be unique and sorted")
    return records


def validate_change_records(value: Any, label: str) -> List[Dict[str, str]]:
    if not isinstance(value, list) or len(value) > MAX_GUARD_RECORDS:
        raise ResearchRoundError(f"{label} must be a bounded array")
    records: List[Dict[str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ResearchRoundError(f"{label}[{index}] must be an object")
        require_exact_keys(item, f"{label}[{index}]", {"path", "change"})
        path = require_string(
            item.get("path"),
            f"{label}[{index}].path",
            4096,
            maximum_utf8_bytes=MAX_RELATIVE_PATH_UTF8_BYTES,
        )
        change = item.get("change")
        if change not in {"ADDED", "REMOVED", "CHANGED", "UNSAFE"}:
            raise ResearchRoundError(f"{label}[{index}].change is invalid")
        records.append({"path": path, "change": str(change)})
    return records


def validate_guard_start(value: Mapping[str, Any], round_id: str, attempt_id: str) -> Dict[str, Any]:
    required = {
        "schema_version",
        "guard_policy_version",
        "round_id",
        "attempt_id",
        "created_at",
        "root_identity",
        "plan_sha256",
        "plan_mode",
        "plan_lab_id",
        "protected_inventory",
        "protected_inventory_sha256",
        "checkpoint_inventory",
        "checkpoint_inventory_sha256",
        "round_control_inventory",
        "round_control_inventory_sha256",
    }
    require_exact_keys(value, "guard_start", required)
    if (
        not is_exact_int(value.get("schema_version"))
        or value.get("schema_version") != 1
        or not is_exact_int(value.get("guard_policy_version"))
        or value.get("guard_policy_version") != GUARD_POLICY_VERSION
    ):
        raise ResearchRoundError("guard_start version is invalid")
    if value.get("round_id") != round_id or value.get("attempt_id") != attempt_id:
        raise ResearchRoundError("guard_start identity mismatch")
    root_value = value.get("root_identity")
    if not isinstance(root_value, dict) or set(root_value) != {"device", "inode"}:
        raise ResearchRoundError("guard_start root_identity is invalid")
    if not all(is_exact_int(root_value.get(key)) for key in ("device", "inode")):
        raise ResearchRoundError("guard_start root identity fields must be integers")
    if not isinstance(value.get("plan_sha256"), str) or not SHA256_RE.fullmatch(value["plan_sha256"]):
        raise ResearchRoundError("guard_start plan_sha256 is invalid")
    if not is_exact_int(value.get("plan_mode")) or value.get("plan_mode") != 0o444:
        raise ResearchRoundError("guard_start plan_mode is invalid")
    require_string(value.get("plan_lab_id"), "guard_start plan_lab_id", 256)
    for prefix in ("protected", "checkpoint", "round_control"):
        records = validate_inventory_records(
            value.get(f"{prefix}_inventory"),
            f"guard_start {prefix}_inventory",
            files_only=prefix == "checkpoint",
        )
        digest = value.get(f"{prefix}_inventory_sha256")
        if digest != inventory_digest(records):
            raise ResearchRoundError(f"guard_start {prefix} inventory digest mismatch")
    require_string(value.get("created_at"), "guard_start created_at", 64)
    return dict(value)


def read_guard_start(round_id: str, attempt_id: str) -> Dict[str, Any]:
    raw = safe_read_bytes(
        guard_start_path(round_id, attempt_id),
        "guard_start",
        maximum=MAX_GUARD_START_BYTES,
    )
    assert raw is not None
    if safe_regular_mode(guard_start_path(round_id, attempt_id), "guard_start") != 0o444:
        raise ResearchRoundError("guard_start must have immutable mode 0444")
    guard_start = validate_guard_start(
        parse_json_bytes(raw, "guard_start", MAX_GUARD_START_BYTES),
        round_id,
        attempt_id,
    )
    if raw != pretty_json(guard_start):
        raise ResearchRoundError("guard_start is not canonical JSON")
    return guard_start


def validate_guard_end(
    value: Mapping[str, Any],
    guard_start: Mapping[str, Any],
    guard_start_raw: bytes,
    round_id: str,
    attempt_id: str,
) -> Dict[str, Any]:
    required = {
        "schema_version",
        "guard_policy_version",
        "round_id",
        "attempt_id",
        "terminal_sequence",
        "completed_at",
        "root_identity",
        "guard_status",
        "guard_start_sha256",
        "plan_unchanged",
        "protected_inventory_sha256",
        "architecture_changes",
        "checkpoint_integrity_changes",
        "round_control_inventory_sha256",
        "round_control_changes",
        "reported_result",
        "reported_result_sha256",
        "effective_result",
        "effective_result_sha256",
        "checkpoint_record",
    }
    require_exact_keys(value, "guard_end", required)
    if (
        not is_exact_int(value.get("schema_version"))
        or value.get("schema_version") != 1
        or not is_exact_int(value.get("guard_policy_version"))
        or value.get("guard_policy_version") != GUARD_POLICY_VERSION
    ):
        raise ResearchRoundError("guard_end version is invalid")
    if value.get("round_id") != round_id or value.get("attempt_id") != attempt_id:
        raise ResearchRoundError("guard_end identity mismatch")
    sequence = value.get("terminal_sequence")
    if not is_exact_int(sequence) or sequence < 1:
        raise ResearchRoundError("guard_end terminal_sequence is invalid")
    require_string(value.get("completed_at"), "guard_end completed_at", 64)
    root_value = value.get("root_identity")
    if root_value != guard_start.get("root_identity"):
        raise ResearchRoundError("guard_end root identity disagrees with guard_start")
    guard_status = value.get("guard_status")
    if guard_status not in {"PASS", "DRIFT_DETECTED"}:
        raise ResearchRoundError("guard_end guard_status is invalid")
    expected_start_sha = sha256_bytes(guard_start_raw)
    if value.get("guard_start_sha256") != expected_start_sha:
        raise ResearchRoundError("guard_end guard_start digest mismatch")
    if not isinstance(value.get("plan_unchanged"), bool):
        raise ResearchRoundError("guard_end plan_unchanged must be boolean")
    for field in ("protected_inventory_sha256", "round_control_inventory_sha256"):
        digest = value.get(field)
        if digest is not None and (not isinstance(digest, str) or not SHA256_RE.fullmatch(digest)):
            raise ResearchRoundError(f"guard_end {field} is invalid")
    architecture_changes = validate_change_records(
        value.get("architecture_changes"), "guard_end architecture_changes"
    )
    checkpoint_changes = validate_change_records(
        value.get("checkpoint_integrity_changes"),
        "guard_end checkpoint_integrity_changes",
    )
    round_control_changes = validate_change_records(
        value.get("round_control_changes"), "guard_end round_control_changes"
    )
    reported_value = value.get("reported_result")
    if not isinstance(reported_value, dict):
        raise ResearchRoundError("guard_end reported_result must be an object")
    reported = validate_result_input(reported_value, round_id)
    if value.get("reported_result_sha256") != sha256_bytes(canonical_json(reported)):
        raise ResearchRoundError("guard_end reported result digest mismatch")
    effective_value = value.get("effective_result")
    if not isinstance(effective_value, dict):
        raise ResearchRoundError("guard_end effective_result must be an object")
    effective = validate_result_input(effective_value, round_id)
    if value.get("effective_result_sha256") != sha256_bytes(canonical_json(effective)):
        raise ResearchRoundError("guard_end effective result digest mismatch")
    checkpoint_record_value = value.get("checkpoint_record")
    current_checkpoint_record = validate_checkpoint(reported, guard_start)
    if checkpoint_record_value is None:
        if current_checkpoint_record is not None:
            raise ResearchRoundError("guard_end lacks its checkpoint record")
    else:
        checkpoint_records = validate_inventory_records(
            [checkpoint_record_value],
            "guard_end checkpoint_record",
            files_only=True,
        )
        checkpoint_record = checkpoint_records[0]
        if checkpoint_record["path"] != reported.get("checkpoint_path"):
            raise ResearchRoundError("guard_end checkpoint record path mismatch")
        if current_checkpoint_record is None or not terminal_checkpoint_record_matches(
            current_checkpoint_record,
            checkpoint_record,
            guard_start["root_identity"],
        ):
            raise ResearchRoundError("terminal checkpoint changed after finalization")

    if guard_status == "PASS":
        if effective != reported:
            raise ResearchRoundError("PASS guard_end changed the reported result")
        if not value["plan_unchanged"]:
            raise ResearchRoundError("PASS guard_end reports plan drift")
        if architecture_changes or checkpoint_changes or round_control_changes:
            raise ResearchRoundError("PASS guard_end contains drift records")
        if value.get("protected_inventory_sha256") != guard_start.get(
            "protected_inventory_sha256"
        ):
            raise ResearchRoundError("PASS guard_end protected digest changed")
        if value.get("round_control_inventory_sha256") != guard_start.get(
            "round_control_inventory_sha256"
        ):
            raise ResearchRoundError("PASS guard_end round-control digest changed")
    else:
        if effective.get("status") != "FAILED":
            raise ResearchRoundError("DRIFT_DETECTED guard_end must produce FAILED")
        if not (
            not value["plan_unchanged"]
            or architecture_changes
            or checkpoint_changes
            or round_control_changes
            or value.get("protected_inventory_sha256") is None
            or value.get("round_control_inventory_sha256") is None
        ):
            raise ResearchRoundError("DRIFT_DETECTED guard_end lacks a concrete drift signal")
    return dict(value)


def next_terminal_sequence(round_id: str, current_attempt_id: str) -> int:
    sequences: List[int] = []
    for candidate in _attempt_ids(round_id):
        if candidate == current_attempt_id:
            continue
        end_raw = safe_read_bytes(
            guard_end_path(round_id, candidate),
            "guard_end",
            maximum=16 * 1024 * 1024,
            optional=True,
        )
        if end_raw is None:
            continue
        if safe_regular_mode(guard_end_path(round_id, candidate), "guard_end") != 0o444:
            raise ResearchRoundError("prior guard_end must have immutable mode 0444")
        start_raw = safe_read_bytes(
            guard_start_path(round_id, candidate),
            "guard_start",
            maximum=MAX_GUARD_START_BYTES,
        )
        assert start_raw is not None
        if safe_regular_mode(guard_start_path(round_id, candidate), "guard_start") != 0o444:
            raise ResearchRoundError("prior guard_start must have immutable mode 0444")
        start = validate_guard_start(
            parse_json_bytes(start_raw, "guard_start", MAX_GUARD_START_BYTES),
            round_id,
            candidate,
        )
        if start_raw != pretty_json(start):
            raise ResearchRoundError("prior guard_start is not canonical JSON")
        end = validate_guard_end(
            parse_json_bytes(end_raw, "guard_end", 16 * 1024 * 1024),
            start,
            start_raw,
            round_id,
            candidate,
        )
        if end_raw != pretty_json(end):
            raise ResearchRoundError("prior guard_end is not canonical JSON")
        sequences.append(int(end["terminal_sequence"]))
    if sorted(sequences) != list(range(1, len(sequences) + 1)):
        raise ResearchRoundError("prior terminal sequences are not unique and contiguous")
    return len(sequences) + 1


def _attempt_ids(round_id: str) -> List[str]:
    relative = f"{round_root(round_id)}/attempts"
    path = ROOT / relative
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_dir():
        raise ResearchRoundError("attempts path must be a real directory")
    identifiers: List[str] = []
    root_device = int(root_identity()["device"])
    for child in sorted(path.iterdir()):
        info = child.lstat()
        if _ignore_safe_macos_metadata(
            child,
            child.relative_to(ROOT).as_posix(),
            info,
            root_device,
        ):
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ResearchRoundError(f"unsafe attempt entry: {child.name}")
        identifiers.append(validate_id(child.name, "attempt_id", ATTEMPT_ID_RE))
    return identifiers


def active_attempt(round_id: str) -> Optional[str]:
    active: List[str] = []
    for attempt_id in _attempt_ids(round_id):
        start = safe_read_bytes(
            guard_start_path(round_id, attempt_id),
            "guard_start",
            maximum=MAX_GUARD_START_BYTES,
            optional=True,
        )
        end = safe_read_bytes(
            guard_end_path(round_id, attempt_id),
            "guard_end",
            maximum=16 * 1024 * 1024,
            optional=True,
        )
        if start is not None and end is None:
            active.append(attempt_id)
    if len(active) > 1:
        raise ResearchRoundError("multiple active attempts detected")
    return active[0] if active else None


PREPARE_COMPARABLE_KEYS = {
    "schema_version",
    "protocol_version",
    "round_id",
    "request_id",
    "lab_id",
    "action_id",
    "action_version",
    "model",
    "reasoning_effort",
    "scope",
    "scope_sha256",
    "checkpoint_required",
    "architecture_guard_policy_version",
}


def unchanged_prepare_response(
    round_id: str,
    immutable: Mapping[str, Any],
    existing_raw: bytes,
) -> Dict[str, Any]:
    existing_plan = validate_plan(
        parse_json_bytes(
            existing_raw,
            "approved plan",
            MAX_SCOPE_INPUT_BYTES * 2,
        ),
        round_id,
    )
    if safe_regular_mode(plan_path(round_id), "approved plan") != 0o444:
        raise ResearchRoundError("approved plan must have immutable mode 0444")
    if existing_raw != pretty_json(existing_plan):
        raise ResearchRoundError("approved plan is not canonical JSON")
    if any(existing_plan[key] != immutable[key] for key in PREPARE_COMPARABLE_KEYS):
        raise ResearchRoundError("round_id already has a different immutable approved plan")
    return {
        "status": "UNCHANGED",
        "round_id": round_id,
        "plan_path": plan_path(round_id),
        "plan_sha256": sha256_bytes(existing_raw),
    }


def _command_prepare_locked(round_id: str, request_id: str, scope: str) -> Dict[str, Any]:
    identity_before = root_identity()
    laboratory_id = lab_id()
    immutable = {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "round_id": round_id,
        "request_id": request_id,
        "lab_id": laboratory_id,
        "action_id": ACTION_ID,
        "action_version": ACTION_VERSION,
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "authorization": {
            "source": "control-room-button",
            "approved_at": utc_now(),
        },
        "scope": scope,
        "scope_sha256": sha256_bytes(scope.encode("utf-8")),
        "created_at": utc_now(),
        "checkpoint_required": True,
        "architecture_guard_policy_version": GUARD_POLICY_VERSION,
    }
    existing_raw = safe_read_bytes(
        plan_path(round_id),
        "approved plan",
        maximum=MAX_SCOPE_INPUT_BYTES * 2,
        optional=True,
    )
    if existing_raw is not None:
        return unchanged_prepare_response(round_id, immutable, existing_raw)
    ensure_directory(round_root(round_id))
    ensure_directory(f"{round_root(round_id)}/attempts")
    require_same_root(identity_before)
    validate_plan(immutable, round_id)
    encoded = pretty_json(immutable)
    try:
        atomic_create(plan_path(round_id), encoded, mode=0o444)
    except ExistingTargetError:
        # A simultaneous prepare may have published the same complete plan
        # after our initial absence check. It is idempotent only when every
        # stable authorization field agrees; otherwise preserve the winner and
        # report an immutable-plan conflict.
        raced_raw = safe_read_bytes(
            plan_path(round_id),
            "approved plan",
            maximum=MAX_SCOPE_INPUT_BYTES * 2,
        )
        assert raced_raw is not None
        return unchanged_prepare_response(round_id, immutable, raced_raw)
    return {
        "status": "PREPARED",
        "round_id": round_id,
        "plan_path": plan_path(round_id),
        "plan_sha256": sha256_bytes(encoded),
    }


def _command_begin_locked(args: argparse.Namespace) -> Dict[str, Any]:
    round_id = validate_id(args.round_id, "round_id", ROUND_ID_RE)
    attempt_id = validate_id(args.attempt_id, "attempt_id", ATTEMPT_ID_RE)
    state_errors = validate_round(round_id)
    if state_errors:
        raise ResearchRoundError(
            "round state failed validation: " + "; ".join(state_errors[:8])
        )
    plan = read_plan(round_id)
    plan_bytes = safe_read_bytes(plan_path(round_id), "approved plan")
    assert plan_bytes is not None
    projection_raw = safe_read_bytes(
        projection_path(round_id),
        "Control Room projection",
        maximum=MAX_PROJECTION_BYTES,
        optional=True,
    )
    projection = None
    if projection_raw is not None:
        projection = validate_projection(
            parse_json_bytes(projection_raw, "Control Room projection", MAX_PROJECTION_BYTES),
            round_id,
            plan_sha256=sha256_bytes(plan_bytes),
        )
        if safe_regular_mode(projection_path(round_id), "Control Room projection") != 0o644:
            raise ResearchRoundError("Control Room projection must have mode 0644")
        if projection_raw != pretty_json(projection):
            raise ResearchRoundError("Control Room projection is not canonical JSON")
        if projection["status"] not in RETRYABLE_STATUSES:
            raise ResearchRoundError(f"cannot begin after status {projection['status']}")
    current_active = active_attempt(round_id)
    existing_raw = safe_read_bytes(
        guard_start_path(round_id, attempt_id),
        "guard_start",
        maximum=MAX_GUARD_START_BYTES,
        optional=True,
    )
    if existing_raw is not None:
        existing_start = validate_guard_start(
            parse_json_bytes(existing_raw, "guard_start", MAX_GUARD_START_BYTES),
            round_id,
            attempt_id,
        )
        if safe_regular_mode(guard_start_path(round_id, attempt_id), "guard_start") != 0o444:
            raise ResearchRoundError("guard_start must have immutable mode 0444")
        if existing_raw != pretty_json(existing_start):
            raise ResearchRoundError("guard_start is not canonical JSON")
        if current_active != attempt_id:
            raise ResearchRoundError("attempt_id already belongs to a finished attempt")
        if projection_raw is not None:
            safe_unlink(
                projection_path(round_id),
                expected_sha256=sha256_bytes(projection_raw),
            )
        return {
            "status": "RUNNING",
            "round_id": round_id,
            "attempt_id": attempt_id,
            "guard_start_path": guard_start_path(round_id, attempt_id),
            "guard_start_sha256": sha256_bytes(existing_raw),
        }
    if current_active is not None:
        raise ResearchRoundError(f"another attempt is already running: {current_active}")
    if _attempt_ids(round_id) and projection is None:
        raise ResearchRoundError("prior attempt lacks a valid terminal projection")
    identity = root_identity()
    protected = protected_inventory()
    checkpoints = checkpoint_inventory()
    round_controls = round_control_inventory(round_id, attempt_id)
    guard_start = {
        "schema_version": 1,
        "guard_policy_version": GUARD_POLICY_VERSION,
        "round_id": round_id,
        "attempt_id": attempt_id,
        "created_at": utc_now(),
        "root_identity": identity,
        "plan_sha256": sha256_bytes(plan_bytes),
        "plan_mode": safe_regular_mode(plan_path(round_id), "approved plan"),
        "plan_lab_id": plan["lab_id"],
        "protected_inventory": protected,
        "protected_inventory_sha256": inventory_digest(protected),
        "checkpoint_inventory": checkpoints,
        "checkpoint_inventory_sha256": inventory_digest(checkpoints),
        "round_control_inventory": round_controls,
        "round_control_inventory_sha256": inventory_digest(round_controls),
    }
    guard_start_encoded = pretty_json(guard_start)
    if len(guard_start_encoded) > MAX_GUARD_START_BYTES:
        raise ResearchRoundError(
            f"guard_start exceeds {MAX_GUARD_START_BYTES} bytes"
        )
    require_same_root(identity)
    ensure_directory(attempt_root(round_id, attempt_id))
    atomic_create(
        guard_start_path(round_id, attempt_id),
        guard_start_encoded,
        mode=0o444,
    )
    if projection_raw is not None:
        safe_unlink(
            projection_path(round_id),
            expected_sha256=sha256_bytes(projection_raw),
        )
    return {
        "status": "RUNNING",
        "round_id": round_id,
        "attempt_id": attempt_id,
        "guard_start_path": guard_start_path(round_id, attempt_id),
        "guard_start_sha256": sha256_bytes(guard_start_encoded),
        "plan_sha256": sha256_bytes(plan_bytes),
    }


def _effective_result_and_guard(
    plan: Mapping[str, Any],
    guard_start: Mapping[str, Any],
    reported_result: Mapping[str, Any],
    guard_start_sha256: str,
    terminal_sequence: int,
    plan_read_error: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    require_same_root(guard_start["root_identity"])
    plan_issue = plan_read_error
    try:
        plan_raw = safe_read_bytes(plan_path(str(plan["round_id"])), "approved plan")
        assert plan_raw is not None
        current_plan_mode = safe_regular_mode(
            plan_path(str(plan["round_id"])), "approved plan"
        )
        plan_changed = (
            sha256_bytes(plan_raw) != guard_start["plan_sha256"]
            or current_plan_mode != guard_start["plan_mode"]
            or plan_issue is not None
        )
    except (ResearchRoundError, OSError) as exc:
        plan_changed = True
        plan_issue = str(exc)
    inventory_issue: Optional[str] = None
    try:
        current_protected = protected_inventory()
        architecture_changes = inventory_changes(
            guard_start["protected_inventory"],
            current_protected,
        )
        current_protected_digest: Optional[str] = inventory_digest(current_protected)
    except (ResearchRoundError, OSError) as exc:
        current_protected = []
        current_protected_digest = None
        inventory_issue = str(exc)
        architecture_changes = [{"path": "<protected-inventory>", "change": "UNSAFE"}]
    current_checkpoints = checkpoint_inventory()
    round_control_issue: Optional[str] = None
    try:
        current_round_controls = round_control_inventory(
            str(reported_result["round_id"]),
            str(guard_start["attempt_id"]),
        )
        round_control_changes = inventory_changes(
            guard_start["round_control_inventory"],
            current_round_controls,
        )
        current_round_control_digest: Optional[str] = inventory_digest(current_round_controls)
    except (ResearchRoundError, OSError) as exc:
        current_round_control_digest = None
        round_control_issue = str(exc)
        round_control_changes = [{"path": "<round-control-inventory>", "change": "UNSAFE"}]
    before_checkpoint_map = {
        item["path"]: item for item in guard_start["checkpoint_inventory"]
    }
    current_checkpoint_map = {item["path"]: item for item in current_checkpoints}
    checkpoint_integrity_changes: List[Dict[str, str]] = []
    for relative, before in sorted(before_checkpoint_map.items()):
        after = current_checkpoint_map.get(relative)
        if after is None:
            checkpoint_integrity_changes.append({"path": relative, "change": "REMOVED"})
        elif before != after:
            checkpoint_integrity_changes.append({"path": relative, "change": "CHANGED"})
    checkpoint_record = validate_checkpoint(reported_result, guard_start)
    effective = dict(reported_result)
    guard_status = "PASS"
    diagnostics: List[str] = []
    if plan_changed:
        suffix = f": {plan_issue}" if plan_issue else ""
        diagnostics.append("immutable approved plan changed" + suffix)
    if inventory_issue:
        diagnostics.append("protected inventory could not be completed: " + inventory_issue)
    if architecture_changes:
        preview = ", ".join(
            f"{item['change']}:{item['path']}" for item in architecture_changes[:12]
        )
        diagnostics.append(f"architecture/policy drift: {preview}")
    if checkpoint_integrity_changes:
        preview = ", ".join(
            f"{item['change']}:{item['path']}" for item in checkpoint_integrity_changes[:12]
        )
        diagnostics.append(f"pre-existing checkpoint drift: {preview}")
    if round_control_issue:
        diagnostics.append("round-control inventory could not be completed: " + round_control_issue)
    if round_control_changes:
        preview = ", ".join(
            f"{item['change']}:{item['path']}" for item in round_control_changes[:12]
        )
        diagnostics.append(f"prior round-control drift: {preview}")
    if diagnostics:
        guard_status = "DRIFT_DETECTED"
        effective["status"] = "FAILED"
        effective["summary"] = "Research round failed its architecture/integrity guard."
        bounded_diagnostics = [
            _truncate_utf8(item, MAX_BLOCKER_CHARS, MAX_BLOCKER_UTF8_BYTES)
            for item in diagnostics
        ]
        effective["blockers"] = (
            bounded_diagnostics + list(effective["blockers"])
        )[:MAX_BLOCKERS]
        if not effective["next_step"]:
            effective["next_step"] = "Inspect the guard report and restore or reconcile protected state."
    effective = validate_result_input(
        effective,
        str(reported_result["round_id"]),
    )
    guard_end = {
        "schema_version": 1,
        "guard_policy_version": GUARD_POLICY_VERSION,
        "round_id": reported_result["round_id"],
        "attempt_id": guard_start["attempt_id"],
        "terminal_sequence": terminal_sequence,
        "completed_at": utc_now(),
        "root_identity": root_identity(),
        "guard_status": guard_status,
        "guard_start_sha256": guard_start_sha256,
        "plan_unchanged": not plan_changed,
        "protected_inventory_sha256": current_protected_digest,
        "architecture_changes": architecture_changes,
        "checkpoint_integrity_changes": checkpoint_integrity_changes,
        "round_control_inventory_sha256": current_round_control_digest,
        "round_control_changes": round_control_changes,
        "reported_result": dict(reported_result),
        "reported_result_sha256": sha256_bytes(canonical_json(reported_result)),
        "effective_result": effective,
        "effective_result_sha256": sha256_bytes(canonical_json(effective)),
        "checkpoint_record": checkpoint_record,
    }
    return effective, guard_end


def _finish_attempt(
    round_id: str,
    attempt_id: str,
    reported_result: Mapping[str, Any],
    expected_guard_start_sha256: str,
) -> Dict[str, Any]:
    if not SHA256_RE.fullmatch(expected_guard_start_sha256):
        raise ResearchRoundError("expected guard_start SHA-256 is invalid")
    guard_start_raw = safe_read_bytes(
        guard_start_path(round_id, attempt_id),
        "guard_start",
        maximum=MAX_GUARD_START_BYTES,
    )
    assert guard_start_raw is not None
    if safe_regular_mode(guard_start_path(round_id, attempt_id), "guard_start") != 0o444:
        raise ResearchRoundError("guard_start must have immutable mode 0444")
    if sha256_bytes(guard_start_raw) != expected_guard_start_sha256:
        raise ResearchRoundError("guard_start external digest mismatch")
    guard_start = validate_guard_start(
        parse_json_bytes(guard_start_raw, "guard_start", MAX_GUARD_START_BYTES),
        round_id,
        attempt_id,
    )
    if guard_start_raw != pretty_json(guard_start):
        raise ResearchRoundError("guard_start is not canonical JSON")
    plan_read_error: Optional[str] = None
    try:
        plan = read_plan(round_id)
    except (ResearchRoundError, OSError) as exc:
        plan_read_error = str(exc)
        plan = {
            "round_id": round_id,
            "lab_id": guard_start["plan_lab_id"],
        }
    if active_attempt(round_id) not in {attempt_id, None}:
        raise ResearchRoundError("a different attempt is active")
    reported_sha = sha256_bytes(canonical_json(reported_result))
    existing_guard_raw = safe_read_bytes(
        guard_end_path(round_id, attempt_id),
        "guard_end",
        maximum=16 * 1024 * 1024,
        optional=True,
    )
    if existing_guard_raw is not None:
        if safe_regular_mode(guard_end_path(round_id, attempt_id), "guard_end") != 0o444:
            raise ResearchRoundError("guard_end must have immutable mode 0444")
        existing_guard = validate_guard_end(
            parse_json_bytes(existing_guard_raw, "guard_end", 16 * 1024 * 1024),
            guard_start,
            guard_start_raw,
            round_id,
            attempt_id,
        )
        if existing_guard.get("reported_result_sha256") != reported_sha:
            raise ResearchRoundError("attempt was already finalized with a different result")
        if existing_guard.get("reported_result") != dict(reported_result):
            raise ResearchRoundError("attempt reported result disagrees with guard_end")
        effective = existing_guard.get("effective_result")
        assert isinstance(effective, dict)
    else:
        terminal_sequence = next_terminal_sequence(round_id, attempt_id)
        effective, guard_end = _effective_result_and_guard(
            plan,
            guard_start,
            reported_result,
            expected_guard_start_sha256,
            terminal_sequence,
            plan_read_error=plan_read_error,
        )
        atomic_create(
            guard_end_path(round_id, attempt_id),
            pretty_json(guard_end),
            mode=0o444,
        )
    result_encoded = pretty_json(effective)
    existing_result = safe_read_bytes(
        result_path(round_id, attempt_id),
        "research-round result",
        maximum=MAX_RESULT_INPUT_BYTES * 2,
        optional=True,
    )
    if existing_result is None:
        atomic_create(result_path(round_id, attempt_id), result_encoded, mode=0o444)
    else:
        if safe_regular_mode(result_path(round_id, attempt_id), "research-round result") != 0o444:
            raise ResearchRoundError("research-round result must have immutable mode 0444")
        if existing_result != result_encoded:
            raise ResearchRoundError("persisted result disagrees with guard_end")
    projection = make_projection(
        effective,
        plan,
        plan_sha256=str(guard_start["plan_sha256"]),
    )
    projection_encoded = pretty_json(projection)
    prior_projection = safe_read_bytes(
        projection_path(round_id),
        "Control Room projection",
        maximum=MAX_PROJECTION_BYTES,
        optional=True,
    )
    if prior_projection is not None:
        prior_value = validate_projection(
            parse_json_bytes(prior_projection, "Control Room projection", MAX_PROJECTION_BYTES),
            round_id,
            plan_sha256=str(guard_start["plan_sha256"]),
        )
        if safe_regular_mode(projection_path(round_id), "Control Room projection") != 0o644:
            raise ResearchRoundError("Control Room projection must have mode 0644")
        if prior_projection != pretty_json(prior_value):
            raise ResearchRoundError("Control Room projection is not canonical JSON")
        stable_prior = dict(prior_value)
        stable_prior.pop("generated_at", None)
        stable_new = dict(projection)
        stable_new.pop("generated_at", None)
        if stable_prior == stable_new:
            return prior_value
    atomic_replace(
        projection_path(round_id),
        projection_encoded,
        expected_sha256=sha256_bytes(prior_projection) if prior_projection is not None else None,
        mode=0o644,
    )
    return projection


def _command_finalize_locked(
    round_id: str,
    attempt_id: str,
    reported: Mapping[str, Any],
    expected_guard_start_sha256: str,
) -> Dict[str, Any]:
    projection = _finish_attempt(
        round_id,
        attempt_id,
        reported,
        expected_guard_start_sha256,
    )
    return {
        "status": projection["status"],
        "round_id": round_id,
        "attempt_id": attempt_id,
        "projection_path": projection_path(round_id),
        "projection": projection,
    }


def cancelled_result(round_id: str) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "round_id": round_id,
        "status": "CANCELLED",
        "summary": "Research round was cancelled.",
        "changed_paths": [],
        "checkpoint_path": None,
        "blockers": ["Cancelled by the Control Room user action."],
        "next_step": "",
    }


def _command_cancel_locked(args: argparse.Namespace) -> Dict[str, Any]:
    round_id = validate_id(args.round_id, "round_id", ROUND_ID_RE)
    state_errors = validate_round(round_id)
    if state_errors:
        raise ResearchRoundError(
            "round state failed validation: " + "; ".join(state_errors[:8])
        )
    projection = read_projection(round_id, optional=True)
    if projection is not None:
        if projection["status"] == "CANCELLED":
            return {
                "status": "CANCELLED",
                "round_id": round_id,
                "projection_path": projection_path(round_id),
                "projection": projection,
            }
        raise ResearchRoundError(f"cannot cancel terminal status {projection['status']}")
    attempt_id = active_attempt(round_id)
    cancelled = cancelled_result(round_id)
    if attempt_id is not None:
        if args.expected_guard_start_sha256 is None:
            raise ResearchRoundError(
                "active-attempt cancellation requires --expected-guard-start-sha256"
            )
        final_projection = _finish_attempt(
            round_id,
            attempt_id,
            cancelled,
            args.expected_guard_start_sha256,
        )
    elif args.expected_guard_start_sha256 is not None:
        raise ResearchRoundError(
            "queued cancellation must not supply --expected-guard-start-sha256"
        )
    else:
        plan = read_plan(round_id)
        final_projection = make_projection(cancelled, plan)
        atomic_replace(
            projection_path(round_id),
            pretty_json(final_projection),
            expected_sha256=None,
            mode=0o644,
        )
    return {
        "status": final_projection["status"],
        "round_id": round_id,
        "attempt_id": attempt_id,
        "projection_path": projection_path(round_id),
        "projection": final_projection,
    }


def _stable_projection(value: Mapping[str, Any]) -> Dict[str, Any]:
    stable = dict(value)
    stable.pop("generated_at", None)
    return stable


def _command_recover_locked(args: argparse.Namespace) -> Dict[str, Any]:
    """Repair only deterministic, append-only crash boundaries.

    Recovery receives no attempt id, guard digest, result, or checkpoint from
    its caller.  It derives all of them from canonical immutable local records,
    rejects ambiguous state before writing, and only then completes the
    interrupted publication chain.
    """

    round_id = validate_id(args.round_id, "round_id", ROUND_ID_RE)
    plan = read_plan(round_id)
    plan_raw = safe_read_bytes(plan_path(round_id), "approved plan")
    assert plan_raw is not None
    bound_plan_sha256 = sha256_bytes(plan_raw)
    attempts: List[Dict[str, Any]] = []
    active_records: List[Dict[str, Any]] = []
    terminal_records: List[Dict[str, Any]] = []
    missing_results: List[Dict[str, Any]] = []

    # Strict read-only preflight.  In particular, do not create a missing
    # result until every attempt and every terminal sequence is unambiguous.
    for attempt_id in _attempt_ids(round_id):
        start_raw = safe_read_bytes(
            guard_start_path(round_id, attempt_id),
            "guard_start",
            maximum=MAX_GUARD_START_BYTES,
        )
        assert start_raw is not None
        if safe_regular_mode(
            guard_start_path(round_id, attempt_id), "guard_start"
        ) != 0o444:
            raise ResearchRoundError("guard_start must have immutable mode 0444")
        start = validate_guard_start(
            parse_json_bytes(start_raw, "guard_start", MAX_GUARD_START_BYTES),
            round_id,
            attempt_id,
        )
        if start_raw != pretty_json(start):
            raise ResearchRoundError("guard_start is not canonical JSON")
        if start.get("plan_sha256") != bound_plan_sha256:
            raise ResearchRoundError(
                "guard_start plan binding disagrees with approved plan"
            )

        end_raw = safe_read_bytes(
            guard_end_path(round_id, attempt_id),
            "guard_end",
            maximum=16 * 1024 * 1024,
            optional=True,
        )
        result_raw = safe_read_bytes(
            result_path(round_id, attempt_id),
            "research-round result",
            maximum=MAX_RESULT_INPUT_BYTES * 2,
            optional=True,
        )
        record: Dict[str, Any] = {
            "attempt_id": attempt_id,
            "guard_start": start,
            "guard_start_raw": start_raw,
            "guard_end": None,
            "result": None,
            "result_raw": result_raw,
        }
        attempts.append(record)

        if end_raw is None:
            if result_raw is not None:
                raise ResearchRoundError(
                    f"{round_id}/{attempt_id}: result exists without immutable guard_end"
                )
            active_records.append(record)
            continue

        if safe_regular_mode(guard_end_path(round_id, attempt_id), "guard_end") != 0o444:
            raise ResearchRoundError("guard_end must have immutable mode 0444")
        end = validate_guard_end(
            parse_json_bytes(end_raw, "guard_end", 16 * 1024 * 1024),
            start,
            start_raw,
            round_id,
            attempt_id,
        )
        if end_raw != pretty_json(end):
            raise ResearchRoundError("guard_end is not canonical JSON")
        effective_value = end.get("effective_result")
        if not isinstance(effective_value, dict):
            raise ResearchRoundError("guard_end effective_result must be an object")
        effective = validate_result_input(effective_value, round_id)
        record["guard_end"] = end
        record["result"] = effective
        record["terminal_sequence"] = int(end["terminal_sequence"])
        terminal_records.append(record)

        if result_raw is None:
            missing_results.append(record)
            continue
        if safe_regular_mode(
            result_path(round_id, attempt_id), "research-round result"
        ) != 0o444:
            raise ResearchRoundError("research-round result must have immutable mode 0444")
        result = validate_result_input(
            parse_json_bytes(
                result_raw,
                "research-round result",
                MAX_RESULT_INPUT_BYTES * 2,
            ),
            round_id,
        )
        if result_raw != pretty_json(result):
            raise ResearchRoundError("research-round result is not canonical JSON")
        if result != effective:
            raise ResearchRoundError("persisted result disagrees with guard_end")

    if len(active_records) > 1:
        raise ResearchRoundError("recovery refuses ambiguous multiple active attempts")
    sequences = sorted(int(item["terminal_sequence"]) for item in terminal_records)
    if sequences != list(range(1, len(sequences) + 1)):
        raise ResearchRoundError(
            "recovery refuses non-unique or non-contiguous terminal sequences"
        )
    if len(missing_results) > 1:
        raise ResearchRoundError(
            "recovery refuses multiple incomplete terminal chains"
        )
    if missing_results and int(missing_results[0]["terminal_sequence"]) != len(sequences):
        raise ResearchRoundError(
            "recovery refuses an incomplete non-latest terminal chain"
        )
    if active_records and missing_results:
        raise ResearchRoundError(
            "recovery refuses an active attempt beside an incomplete terminal chain"
        )

    projection_raw = safe_read_bytes(
        projection_path(round_id),
        "Control Room projection",
        maximum=MAX_PROJECTION_BYTES,
        optional=True,
    )
    projection: Optional[Dict[str, Any]] = None
    if projection_raw is not None:
        if safe_regular_mode(
            projection_path(round_id), "Control Room projection"
        ) != 0o644:
            raise ResearchRoundError("Control Room projection must have mode 0644")
        projection = validate_projection(
            parse_json_bytes(
                projection_raw,
                "Control Room projection",
                MAX_PROJECTION_BYTES,
            ),
            round_id,
            plan_sha256=bound_plan_sha256,
        )
        if projection_raw != pretty_json(projection):
            raise ResearchRoundError("Control Room projection is not canonical JSON")

    ordered_terminals = sorted(
        terminal_records,
        key=lambda item: int(item["terminal_sequence"]),
    )
    expected_terminals = [
        make_projection(item["result"], plan) for item in ordered_terminals
    ]
    latest_record = ordered_terminals[-1] if ordered_terminals else None
    latest_expected = expected_terminals[-1] if expected_terminals else None

    # A browser-visible projection is trusted only when its complete stable
    # shape is derived from an immutable terminal record (or the canonical
    # queued cancellation when no attempt exists).  An unrelated or tampered
    # projection is not a recoverable crash boundary.
    projection_matches_latest = False
    projection_matches_prior = False
    if projection is not None:
        stable_projection = _stable_projection(projection)
        if latest_expected is not None:
            projection_matches_latest = (
                stable_projection == _stable_projection(latest_expected)
            )
            projection_matches_prior = any(
                stable_projection == _stable_projection(expected)
                for expected in expected_terminals[:-1]
            )
            if not projection_matches_latest and not projection_matches_prior:
                raise ResearchRoundError(
                    "recovery refuses a projection not bound to an immutable terminal attempt"
                )
        elif attempts:
            # With an active first attempt, the only possible pre-attempt
            # projection is the canonical retryable queued cancellation.
            queued_expected = make_projection(cancelled_result(round_id), plan)
            if stable_projection != _stable_projection(queued_expected):
                raise ResearchRoundError(
                    "recovery refuses an unbound projection beside an active attempt"
                )
            projection_matches_prior = True
        else:
            queued_expected = make_projection(cancelled_result(round_id), plan)
            if stable_projection != _stable_projection(queued_expected):
                raise ResearchRoundError(
                    "recovery refuses a non-canonical queued projection"
                )
            projection_matches_latest = True

    repairs: List[str] = []
    final_attempt_id: Optional[str] = (
        str(latest_record["attempt_id"]) if latest_record is not None else None
    )

    for record in missing_results:
        attempt_id = str(record["attempt_id"])
        atomic_create(
            result_path(round_id, attempt_id),
            pretty_json(record["result"]),
            mode=0o444,
        )
        repairs.append(f"CREATED_RESULT:{attempt_id}")

    if active_records:
        active_record = active_records[0]
        active_id = str(active_record["attempt_id"])
        if projection is not None:
            if projection["status"] not in RETRYABLE_STATUSES:
                raise ResearchRoundError(
                    "recovery refuses a non-retryable projection beside an active attempt"
                )
            assert projection_raw is not None
            safe_unlink(
                projection_path(round_id),
                expected_sha256=sha256_bytes(projection_raw),
            )
            repairs.append("REMOVED_STALE_PROJECTION")
        final_projection = _finish_attempt(
            round_id,
            active_id,
            cancelled_result(round_id),
            sha256_bytes(active_record["guard_start_raw"]),
        )
        final_attempt_id = active_id
        repairs.append(f"FINALIZED_ACTIVE_ATTEMPT:{active_id}")
    elif latest_expected is not None:
        if projection is not None and projection_matches_latest:
            final_projection = projection
        else:
            final_projection = latest_expected
            atomic_replace(
                projection_path(round_id),
                pretty_json(final_projection),
                expected_sha256=(
                    sha256_bytes(projection_raw) if projection_raw is not None else None
                ),
                mode=0o644,
            )
            repairs.append("PUBLISHED_TERMINAL_PROJECTION")
    else:
        final_projection = projection

    validation_errors = validate_round(round_id)
    if validation_errors:
        raise ResearchRoundError(
            "recovery did not produce a valid round: "
            + "; ".join(validation_errors[:8])
        )

    status_value = final_projection["status"] if final_projection is not None else "QUEUED"
    return {
        "status": status_value,
        "round_id": round_id,
        "recovery": "RECOVERED" if repairs else "UNCHANGED",
        "repairs": repairs,
        "attempt_id": final_attempt_id,
        "projection_path": (
            projection_path(round_id) if final_projection is not None else None
        ),
        "projection": final_projection,
    }


def _command_status_locked(args: argparse.Namespace) -> Dict[str, Any]:
    round_id = validate_id(args.round_id, "round_id", ROUND_ID_RE)
    validation_errors = validate_round(round_id)
    if validation_errors:
        raise ResearchRoundError(
            "round state failed validation: " + "; ".join(validation_errors[:8])
        )
    plan = read_plan(round_id)
    projection = read_projection(round_id, optional=True)
    if projection is not None:
        state = projection["status"]
        current_attempt = None
    else:
        current_attempt = active_attempt(round_id)
        state = "RUNNING" if current_attempt is not None else "QUEUED"
    return {
        "schema_version": 1,
        "round_id": round_id,
        "lab_id": plan["lab_id"],
        "status": state,
        "current_attempt_id": current_attempt,
        "plan_path": plan_path(round_id),
        "projection_path": projection_path(round_id) if projection is not None else None,
        "projection": projection,
    }


def validate_round(round_id: str) -> List[str]:
    errors: List[str] = []
    try:
        plan = read_plan(round_id)
        plan_raw = safe_read_bytes(plan_path(round_id), "approved plan")
        assert plan_raw is not None
        bound_plan_sha256 = sha256_bytes(plan_raw)
        projection = read_projection(
            round_id,
            optional=True,
            plan_sha256=bound_plan_sha256,
        )
        active = active_attempt(round_id)
        if active is not None and projection is not None:
            errors.append(f"{round_id}: active attempt coexists with terminal projection")
        attempt_ids = _attempt_ids(round_id)
        terminals: List[Tuple[int, str, Dict[str, Any]]] = []
        for attempt_id in attempt_ids:
            try:
                guard_start_raw = safe_read_bytes(
                    guard_start_path(round_id, attempt_id),
                    "guard_start",
                    maximum=MAX_GUARD_START_BYTES,
                )
                assert guard_start_raw is not None
                if safe_regular_mode(guard_start_path(round_id, attempt_id), "guard_start") != 0o444:
                    raise ResearchRoundError("guard_start must have immutable mode 0444")
                guard_start_value = parse_json_bytes(
                    guard_start_raw, "guard_start", MAX_GUARD_START_BYTES
                )
                guard_start = validate_guard_start(
                    guard_start_value, round_id, attempt_id
                )
                if guard_start_raw != pretty_json(guard_start):
                    raise ResearchRoundError("guard_start is not canonical JSON")
                if guard_start.get("plan_sha256") != bound_plan_sha256:
                    raise ResearchRoundError(
                        "guard_start plan binding disagrees with approved plan"
                    )
                guard_end_raw = safe_read_bytes(
                    guard_end_path(round_id, attempt_id),
                    "guard_end",
                    maximum=16 * 1024 * 1024,
                    optional=True,
                )
                result_raw = safe_read_bytes(
                    result_path(round_id, attempt_id),
                    "research-round result",
                    maximum=MAX_RESULT_INPUT_BYTES * 2,
                    optional=True,
                )
                if (guard_end_raw is None) != (result_raw is None):
                    errors.append(f"{round_id}/{attempt_id}: guard_end/result completeness mismatch")
                if guard_end_raw is not None and result_raw is not None:
                    if safe_regular_mode(guard_end_path(round_id, attempt_id), "guard_end") != 0o444:
                        raise ResearchRoundError("guard_end must have immutable mode 0444")
                    if safe_regular_mode(
                        result_path(round_id, attempt_id), "research-round result"
                    ) != 0o444:
                        raise ResearchRoundError("research-round result must have immutable mode 0444")
                    guard_end_value = parse_json_bytes(
                        guard_end_raw, "guard_end", 16 * 1024 * 1024
                    )
                    guard_end = validate_guard_end(
                        guard_end_value,
                        guard_start,
                        guard_start_raw,
                        round_id,
                        attempt_id,
                    )
                    if guard_end_raw != pretty_json(guard_end):
                        raise ResearchRoundError("guard_end is not canonical JSON")
                    result_value = parse_json_bytes(
                        result_raw,
                        "research-round result",
                        MAX_RESULT_INPUT_BYTES * 2,
                    )
                    result = validate_result_input(result_value, round_id)
                    if result_raw != pretty_json(result):
                        raise ResearchRoundError("research-round result is not canonical JSON")
                    if result != guard_end["effective_result"]:
                        raise ResearchRoundError("result disagrees with guard_end")
                    terminals.append(
                        (int(guard_end["terminal_sequence"]), attempt_id, result)
                    )
            except ResearchRoundError as exc:
                errors.append(f"{round_id}/{attempt_id}: {exc}")
        sequences = sorted(item[0] for item in terminals)
        if sequences != list(range(1, len(sequences) + 1)):
            errors.append(f"{round_id}: terminal sequences are not unique and contiguous")
        if projection is not None and not attempt_ids:
            expected_cancel = make_projection(cancelled_result(round_id), plan)
            stable_projection = dict(projection)
            stable_projection.pop("generated_at", None)
            stable_expected_cancel = dict(expected_cancel)
            stable_expected_cancel.pop("generated_at", None)
            if stable_projection != stable_expected_cancel:
                errors.append(f"{round_id}: queued-cancel projection is not canonical")
        if active is None and terminals:
            if projection is None:
                errors.append(f"{round_id}: terminal attempt lacks a projection")
            elif sequences == list(range(1, len(sequences) + 1)):
                latest = max(terminals, key=lambda item: item[0])
                expected = make_projection(latest[2], plan)
                stable_projection = dict(projection)
                stable_projection.pop("generated_at", None)
                stable_expected = dict(expected)
                stable_expected.pop("generated_at", None)
                if stable_projection != stable_expected:
                    errors.append(
                        f"{round_id}: projection disagrees with terminal attempt {latest[1]}"
                    )
        elif active is None and attempt_ids and not terminals:
            errors.append(f"{round_id}: attempts exist without an active or terminal attempt")
    except (ResearchRoundError, OSError) as exc:
        errors.append(f"{round_id}: {exc}")
    return errors


def _command_validate_locked(args: argparse.Namespace) -> Dict[str, Any]:
    rounds_root = ROOT / "research/rounds"
    if not rounds_root.exists():
        return {"status": "PASS", "rounds": 0, "errors": []}
    if rounds_root.is_symlink() or not rounds_root.is_dir():
        raise ResearchRoundError("research/rounds must be a real directory")
    if args.round_id is not None:
        identifiers = [validate_id(args.round_id, "round_id", ROUND_ID_RE)]
    else:
        identifiers = []
        root_device = int(root_identity()["device"])
        for child in sorted(rounds_root.iterdir()):
            info = child.lstat()
            if _ignore_safe_macos_metadata(
                child,
                child.relative_to(ROOT).as_posix(),
                info,
                root_device,
            ):
                continue
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise ResearchRoundError(f"unsafe research/rounds entry: {child.name}")
            identifiers.append(validate_id(child.name, "round_id", ROUND_ID_RE))
    errors: List[str] = []
    for identifier in identifiers:
        errors.extend(validate_round(identifier))
    return {
        "status": "PASS" if not errors else "FAIL",
        "rounds": len(identifiers),
        "errors": errors,
    }


def command_prepare(args: argparse.Namespace) -> Dict[str, Any]:
    round_id = validate_id(args.round_id, "round_id", ROUND_ID_RE)
    request_id = validate_id(args.request_id, "request_id", ROUND_ID_RE)
    raw = sys.stdin.buffer.read(MAX_SCOPE_INPUT_BYTES + 1)
    payload = parse_json_bytes(raw, "prepare input", MAX_SCOPE_INPUT_BYTES)
    require_exact_keys(payload, "prepare input", {"scope"})
    scope = require_string(
        payload.get("scope"),
        "scope",
        MAX_SCOPE_CHARS,
        maximum_utf8_bytes=MAX_SCOPE_UTF8_BYTES,
    )
    with laboratory_transition_lock():
        return _command_prepare_locked(round_id, request_id, scope)


def command_begin(args: argparse.Namespace) -> Dict[str, Any]:
    with laboratory_transition_lock():
        return _command_begin_locked(args)


def command_finalize(args: argparse.Namespace) -> Dict[str, Any]:
    round_id = validate_id(args.round_id, "round_id", ROUND_ID_RE)
    attempt_id = validate_id(args.attempt_id, "attempt_id", ATTEMPT_ID_RE)
    raw = sys.stdin.buffer.read(MAX_RESULT_INPUT_BYTES + 1)
    reported = validate_result_input(
        parse_json_bytes(raw, "finalize input", MAX_RESULT_INPUT_BYTES),
        round_id,
    )
    with laboratory_transition_lock():
        return _command_finalize_locked(
            round_id,
            attempt_id,
            reported,
            args.expected_guard_start_sha256,
        )


def command_cancel(args: argparse.Namespace) -> Dict[str, Any]:
    with laboratory_transition_lock():
        return _command_cancel_locked(args)


def command_recover(args: argparse.Namespace) -> Dict[str, Any]:
    with laboratory_transition_lock():
        return _command_recover_locked(args)


def command_status(args: argparse.Namespace) -> Dict[str, Any]:
    with laboratory_transition_lock():
        return _command_status_locked(args)


def command_validate(args: argparse.Namespace) -> Dict[str, Any]:
    with laboratory_transition_lock():
        return _command_validate_locked(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Guarded lab-local research-round state helper."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="persist an immutable approved plan")
    prepare.add_argument("--round-id", required=True)
    prepare.add_argument("--request-id", required=True)
    prepare.set_defaults(handler=command_prepare)

    begin = subparsers.add_parser("begin", help="start one append-only attempt")
    begin.add_argument("--round-id", required=True)
    begin.add_argument("--attempt-id", required=True)
    begin.set_defaults(handler=command_begin)

    finalize = subparsers.add_parser("finalize", help="finalize one guarded attempt")
    finalize.add_argument("--round-id", required=True)
    finalize.add_argument("--attempt-id", required=True)
    finalize.add_argument("--expected-guard-start-sha256", required=True)
    finalize.set_defaults(handler=command_finalize)

    cancel = subparsers.add_parser("cancel", help="cancel a queued or active round")
    cancel.add_argument("--round-id", required=True)
    cancel.add_argument("--expected-guard-start-sha256")
    cancel.set_defaults(handler=command_cancel)

    recover = subparsers.add_parser(
        "recover",
        help="repair deterministic torn transitions from immutable local records",
    )
    recover.add_argument("--round-id", required=True)
    recover.set_defaults(handler=command_recover)

    status_parser = subparsers.add_parser("status", help="read one round status")
    status_parser.add_argument("--round-id", required=True)
    status_parser.set_defaults(handler=command_status)

    validate_parser = subparsers.add_parser("validate", help="validate persisted round state")
    validate_parser.add_argument("--round-id")
    validate_parser.set_defaults(handler=command_validate)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = args.handler(args)
    except ResearchRoundError as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.command == "validate" and result.get("status") != "PASS":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
