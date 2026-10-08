#!/usr/bin/env python3
"""Local, dependency-free primitives for a discovery portfolio.

The module manages research *workflow* status only.  It never changes a
mathematical truth status and never edits a problem dossier.
"""

from __future__ import annotations

import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


SCHEMA_VERSION = 1
LATEST_CANDIDATE_SCHEMA_VERSION = 2
ZERO_HASH = "0" * 64
CANDIDATE_STATUSES = (
    "LEAD",
    "QUALIFYING",
    "TRIAL_ACTIVE",
    "PARKED",
    "REJECTED",
    "SPINOUT_READY",
    "SPUN_OUT",
)
DECISIONS = ("CONTINUE", "PARK", "REJECT", "SPIN_OUT")
LEAD_ORIGINS = ("USER_SUPPLIED", "LAB_SCOUTED")
ENGAGEMENT_TIERS = ("SCOUT", "TRIAL", "DEEP")
REOPEN_KINDS = (
    "MODEL_CAPABILITY_CHANGE",
    "NEW_SOURCE",
    "NEW_TECHNIQUE",
    "GAP_DISCHARGED",
    "REFORMULATION",
    "OTHER_SPECIFIED",
)
OPEN_ASSESSMENTS = (
    "UNASSESSED",
    "UNKNOWN",
    "LIKELY_OPEN",
    "SOURCE_CONFLICT",
    "CLOSED_REPORTED",
)
REPOSITORY_STATES = ("NOT_CONFIGURED", "LOCAL_ONLY", "PENDING", "CONNECTED", "ERROR")
REPOSITORY_VISIBILITIES = ("UNDECIDED", "LOCAL_ONLY", "PRIVATE", "PUBLIC")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
PROBLEM_ID_MAX_BYTES = 160


class PortfolioError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_bytes(value: Any, *, ensure_ascii: bool = False) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=ensure_ascii,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _open_nofollow(path: Path, *, directory: bool) -> int:
    """Open an absolute path one component at a time without following links."""
    absolute = Path(os.path.abspath(path))
    parts = absolute.parts
    if not absolute.is_absolute() or not parts:
        raise PortfolioError(f"absolute path required: {path}")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(parts[0], flags)
    try:
        for index, part in enumerate(parts[1:], 1):
            last = index == len(parts) - 1
            next_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            if not last or directory:
                next_flags |= getattr(os, "O_DIRECTORY", 0)
            next_descriptor = os.open(part, next_flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        info = os.fstat(descriptor)
        expected = stat.S_ISDIR if directory else stat.S_ISREG
        if not expected(info.st_mode):
            kind = "directory" if directory else "regular file"
            raise PortfolioError(f"{kind} required: {path}")
        return descriptor
    except OSError as exc:
        os.close(descriptor)
        raise PortfolioError(f"unsafe no-follow path: {path}") from exc
    except Exception:
        os.close(descriptor)
        raise


def _sha256_descriptor(descriptor: int) -> str:
    digest = hashlib.sha256()
    os.lseek(descriptor, 0, os.SEEK_SET)
    with os.fdopen(os.dup(descriptor), "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_digest_and_size(path: Path) -> Tuple[str, int]:
    descriptor = _open_nofollow(path, directory=False)
    try:
        info = os.fstat(descriptor)
        return _sha256_descriptor(descriptor), info.st_size
    finally:
        os.close(descriptor)


def sha256_file(path: Path) -> str:
    return file_digest_and_size(path)[0]


def require_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise PortfolioError(f"{label} must match {ID_RE.pattern}")
    return value


def require_problem_id(value: Any, label: str = "problem_id") -> str:
    """Accept the safe Unicode dossier IDs produced by ``new_problem.py``."""
    text = require_text(value, label, single_line=True)
    if (
        len(text.encode("utf-8")) > PROBLEM_ID_MAX_BYTES
        or text in (".", "..")
        or "/" in text
        or "\\" in text
        or text != unicodedata.normalize("NFKC", text)
        or not text[0].isalnum()
        or not text[-1].isalnum()
        or any(
            not (character.isalnum() or character == "-")
            for character in text
        )
    ):
        raise PortfolioError(f"{label} is not a safe portable dossier ID")
    return text


def require_project_id(value: Any, label: str) -> str:
    """Accept portable generator IDs, including Unicode safe slugs.

    Candidate/event IDs remain deliberately ASCII because they are path
    components created by this module.  Project IDs are generated elsewhere
    and may contain Unicode; they are data in manifests, never paths here.
    """
    text = require_text(value, label, single_line=True)
    if len(text.encode("utf-8")) > 240 or text in (".", "..") or "/" in text or "\\" in text:
        raise PortfolioError(f"{label} is not a safe portable project ID")
    return text


def require_text(value: Any, label: str, *, single_line: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PortfolioError(f"{label} must be a non-empty string")
    text = value.strip()
    if single_line and (len(text.splitlines()) != 1 or any(ord(c) < 32 for c in text)):
        raise PortfolioError(f"{label} must be a safe single line")
    return text


def require_iso(value: Any, label: str) -> str:
    if not isinstance(value, str) or not ISO_RE.fullmatch(value):
        raise PortfolioError(f"{label} must use YYYY-MM-DDTHH:MM:SSZ")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise PortfolioError(f"{label} is not a valid UTC timestamp") from exc
    return value


def require_exact_keys(value: Any, required: Iterable[str], optional: Iterable[str], label: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise PortfolioError(f"{label} must be an object")
    required_set = set(required)
    allowed = required_set | set(optional)
    missing = sorted(required_set - set(value))
    extra = sorted(set(value) - allowed)
    if missing or extra:
        raise PortfolioError(f"{label} keys invalid; missing={missing}, extra={extra}")
    return value


def load_json(path: Path, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PortfolioError(f"cannot parse {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PortfolioError(f"{label} must contain an object")
    return value


def _relative_parts(relative: str) -> Tuple[str, ...]:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise PortfolioError("path must be a non-empty POSIX root-relative path")
    path = Path(relative)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise PortfolioError(f"unsafe root-relative path: {relative!r}")
    return tuple(path.parts)


def safe_path(root: Path, relative: str, *, kind: Optional[str] = None) -> Path:
    parts = _relative_parts(relative)
    root = root.resolve()
    current = root
    for part in parts:
        current = current / part
        if current.exists() or current.is_symlink():
            mode = current.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise PortfolioError(f"symlink is forbidden: {current.relative_to(root)}")
            if current != root / Path(*parts) and not stat.S_ISDIR(mode):
                raise PortfolioError(f"non-directory path component: {current.relative_to(root)}")
    if kind == "file":
        if not current.exists() or not stat.S_ISREG(current.lstat().st_mode):
            raise PortfolioError(f"regular file required: {relative}")
    elif kind == "dir":
        if not current.exists() or not stat.S_ISDIR(current.lstat().st_mode):
            raise PortfolioError(f"directory required: {relative}")
    return current


def scan_tree(path: Path) -> List[Path]:
    if not path.exists() or path.is_symlink() or not stat.S_ISDIR(path.lstat().st_mode):
        raise PortfolioError(f"safe directory required: {path}")
    files: List[Path] = []
    for child in sorted(path.rglob("*")):
        mode = child.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise PortfolioError(f"symlink is forbidden: {child}")
        if stat.S_ISREG(mode):
            files.append(child)
        elif not stat.S_ISDIR(mode):
            raise PortfolioError(f"special file is forbidden: {child}")
    return files


def write_json_atomic(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(value, output, indent=2, ensure_ascii=False, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(str(temporary), str(path))
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json_exclusive(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as output:
            json.dump(value, output, indent=2, ensure_ascii=False, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as exc:
        raise PortfolioError(f"refusing to overwrite existing record: {path}") from exc


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(str(path), flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_json_atomic_exclusive(
    path: Path,
    value: Dict[str, Any],
    *,
    staging_directory: Optional[Path] = None,
) -> None:
    """Publish complete JSON bytes atomically without replacing any target.

    The temporary inode lives in a caller-selected harmless staging directory.
    Linking it into place is the commit point: before that point the target is
    absent, and afterward it contains only fully flushed bytes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = staging_directory or path.parent
    if staging.is_symlink() or not staging.is_dir():
        raise PortfolioError(f"safe staging directory required: {staging}")
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}-", dir=str(staging)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(value, output, indent=2, ensure_ascii=False, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(str(temporary), str(path), follow_symlinks=False)
        except FileExistsError as exc:
            raise PortfolioError(
                f"refusing to overwrite existing record: {path}"
            ) from exc
        _fsync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


class FileLock:
    """Persistent-path advisory lock released automatically on process exit."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.fd: Optional[int] = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        parent_mode = self.path.parent.lstat().st_mode
        if stat.S_ISLNK(parent_mode) or not stat.S_ISDIR(parent_mode):
            raise PortfolioError(
                f"portfolio lock parent must be a real directory: {self.path.parent}"
            )
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor: Optional[int] = None
        try:
            descriptor = os.open(str(self.path), flags, 0o600)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise PortfolioError(f"portfolio lock must be a regular file: {self.path}")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                raise PortfolioError(
                    f"another portfolio operation is active: {self.path}"
                ) from exc
            current = self.path.stat(follow_symlinks=False)
            opened = os.fstat(descriptor)
            if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                raise PortfolioError(f"portfolio lock path changed while opening: {self.path}")
            os.ftruncate(descriptor, 0)
            os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
            os.fsync(descriptor)
            self.fd = descriptor
            descriptor = None
        except OSError as exc:
            if descriptor is not None:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
                os.close(descriptor)
            raise PortfolioError(
                f"cannot acquire safe portfolio lock: {self.path}"
            ) from exc
        except Exception:
            if descriptor is not None:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
                os.close(descriptor)
            raise
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


def _fsync_tree(path: Path) -> None:
    """Flush every regular file and directory below a staged directory."""
    descriptor = _open_nofollow(path, directory=True)
    try:
        entries = sorted(os.scandir(descriptor), key=lambda entry: entry.name)
        for entry in entries:
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                raise PortfolioError(f"symlink is forbidden: {path / entry.name}")
            if stat.S_ISDIR(info.st_mode):
                _fsync_tree(path / entry.name)
            elif stat.S_ISREG(info.st_mode):
                file_descriptor = os.open(
                    entry.name,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
                try:
                    os.fsync(file_descriptor)
                finally:
                    os.close(file_descriptor)
            else:
                raise PortfolioError(f"special file is forbidden: {path / entry.name}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_directory_noreplace(stage: Path, target: Path) -> None:
    if target.exists() or target.is_symlink():
        raise PortfolioError(f"refusing to overwrite existing directory: {target}")
    _fsync_tree(stage)
    source_parent = stage.parent
    target_parent = target.parent
    if os.name == "nt":
        try:
            os.rename(stage, target)
        except OSError as exc:
            raise PortfolioError(f"atomic no-clobber publication failed: {exc}") from exc
        _fsync_directory(target_parent)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes, target_bytes = os.fsencode(stage), os.fsencode(target)
    if sys.platform == "darwin":
        function = getattr(libc, "renamex_np", None)
        if function is None:
            raise PortfolioError("atomic no-clobber publication is unavailable")
        function.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        function.restype = ctypes.c_int
        result = function(source_bytes, target_bytes, 0x00000004)
    elif sys.platform.startswith("linux"):
        function = getattr(libc, "renameat2", None)
        if function is None:
            raise PortfolioError("atomic no-clobber publication is unavailable")
        function.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        function.restype = ctypes.c_int
        result = function(-100, source_bytes, -100, target_bytes, 1)
    else:
        raise PortfolioError(f"atomic no-clobber publication unsupported on {sys.platform}")
    if result == 0:
        _fsync_directory(target_parent)
        if source_parent != target_parent:
            _fsync_directory(source_parent)
        return
    number = ctypes.get_errno()
    if number in (errno.EEXIST, errno.ENOTEMPTY):
        raise PortfolioError(f"refusing to overwrite existing directory: {target}")
    raise PortfolioError(f"atomic publication failed: {os.strerror(number)}")


def _copy_tree_descriptors(
    source_descriptor: int,
    target_descriptor: int,
    source_path: Path,
) -> None:
    for entry in sorted(os.scandir(source_descriptor), key=lambda item: item.name):
        info = entry.stat(follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode):
            raise PortfolioError(f"symlink is forbidden: {source_path / entry.name}")
        if stat.S_ISDIR(info.st_mode):
            child_source = os.open(
                entry.name,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=source_descriptor,
            )
            try:
                opened = os.fstat(child_source)
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    raise PortfolioError(
                        f"source directory changed while copying: {source_path / entry.name}"
                    )
                os.mkdir(entry.name, mode=0o777, dir_fd=target_descriptor)
                child_target = os.open(
                    entry.name,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=target_descriptor,
                )
                try:
                    _copy_tree_descriptors(
                        child_source, child_target, source_path / entry.name
                    )
                    os.fsync(child_target)
                finally:
                    os.close(child_target)
            finally:
                os.close(child_source)
        elif stat.S_ISREG(info.st_mode):
            source_file = os.open(
                entry.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=source_descriptor,
            )
            try:
                opened = os.fstat(source_file)
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    raise PortfolioError(
                        f"source file changed while copying: {source_path / entry.name}"
                    )
                target_file = os.open(
                    entry.name,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o666,
                    dir_fd=target_descriptor,
                )
                try:
                    with os.fdopen(os.dup(source_file), "rb") as input_stream:
                        with os.fdopen(os.dup(target_file), "wb") as output:
                            shutil.copyfileobj(input_stream, output)
                            output.flush()
                    os.fsync(target_file)
                finally:
                    os.close(target_file)
            finally:
                os.close(source_file)
        else:
            raise PortfolioError(f"special file is forbidden: {source_path / entry.name}")


def copy_safe_tree(source: Path, target: Path) -> None:
    source_descriptor = _open_nofollow(source, directory=True)
    target.mkdir(parents=True, exist_ok=False)
    target_descriptor = _open_nofollow(target, directory=True)
    try:
        _copy_tree_descriptors(source_descriptor, target_descriptor, source)
        os.fsync(target_descriptor)
    finally:
        os.close(target_descriptor)
        os.close(source_descriptor)


def copy_safe_file(source: Path, target: Path) -> None:
    """Copy one regular file without following final or ancestor links."""
    target.parent.mkdir(parents=True, exist_ok=True)
    source_descriptor = _open_nofollow(source, directory=False)
    parent_descriptor = _open_nofollow(target.parent, directory=True)
    try:
        target_descriptor = os.open(
            target.name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o666,
            dir_fd=parent_descriptor,
        )
        try:
            with os.fdopen(os.dup(source_descriptor), "rb") as input_stream:
                with os.fdopen(os.dup(target_descriptor), "wb") as output:
                    shutil.copyfileobj(input_stream, output)
                    output.flush()
            os.fsync(target_descriptor)
            os.fsync(parent_descriptor)
        finally:
            os.close(target_descriptor)
    finally:
        os.close(parent_descriptor)
        os.close(source_descriptor)


def project_id(root: Path) -> str:
    profile = load_json(safe_path(root, "LAB_PROFILE.json", kind="file"), "LAB_PROFILE")
    lab = profile.get("lab")
    if not isinstance(lab, dict):
        raise PortfolioError("LAB_PROFILE.json has no lab object")
    return require_project_id(lab.get("id"), "LAB_PROFILE.lab.id")


def resolve_problem(root: Path, problem_id: str) -> Path:
    require_problem_id(problem_id, "problem_id")
    matches = []
    for state in ("active", "backlog", "closed"):
        relative = f"problems/{state}/{problem_id}"
        path = safe_path(root, relative)
        if path.exists():
            if not stat.S_ISDIR(path.lstat().st_mode):
                raise PortfolioError(f"problem dossier is not a directory: {relative}")
            matches.append(path)
    if len(matches) != 1:
        raise PortfolioError(f"problem_id {problem_id!r} must resolve to exactly one dossier")
    scan_tree(matches[0])
    return matches[0]


def candidate_root(root: Path, candidate_id: str) -> Path:
    require_id(candidate_id, "candidate_id")
    return safe_path(root, f"portfolio/candidates/{candidate_id}")


def event_files(directory: Path) -> List[Path]:
    events = directory / "events"
    if not events.is_dir() or events.is_symlink():
        raise PortfolioError(f"candidate events directory is missing or unsafe: {events}")
    files = []
    for path in sorted(events.iterdir()):
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode) or path.suffix != ".json":
            raise PortfolioError(f"events may contain only regular .json files: {path}")
        files.append(path)
    return files


def validate_candidate_metadata(value: Dict[str, Any]) -> None:
    version = value.get("schema_version")
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
        "workflow_status_policy",
    )
    if version == 1:
        require_exact_keys(value, common, (), "candidate metadata")
    elif version == LATEST_CANDIDATE_SCHEMA_VERSION:
        require_exact_keys(
            value,
            (*common, "origin", "origin_artifacts", "cohort_id"),
            ("intake_identity_sha256",),
            "candidate metadata",
        )
        if value["origin"] not in LEAD_ORIGINS:
            raise PortfolioError("candidate origin is invalid")
        if value["cohort_id"] is not None:
            require_id(value["cohort_id"], "cohort_id")
        if not isinstance(value["origin_artifacts"], list):
            raise PortfolioError("origin_artifacts must be an array")
        identity = value.get("intake_identity_sha256")
        if identity is not None and (
            not isinstance(identity, str) or not SHA_RE.fullmatch(identity)
        ):
            raise PortfolioError("candidate intake_identity_sha256 is invalid")
        if value["origin"] == "LAB_SCOUTED" and not value["origin_artifacts"]:
            raise PortfolioError("LAB_SCOUTED candidates require source-bound origin evidence")
    else:
        raise PortfolioError("unsupported candidate schema_version")
    require_id(value["candidate_id"], "candidate_id")
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
        require_problem_id(value["problem_id"], "problem_id")
    if value["workflow_status_policy"] != "NO_MATHEMATICAL_STATUS_PROMOTION":
        raise PortfolioError("candidate workflow status policy is invalid")


def _validate_candidate_origin_evidence(
    root: Path,
    directory: Path,
    metadata: Dict[str, Any],
    verify: bool,
) -> None:
    if metadata["schema_version"] == 1:
        return
    expected_prefix = f"portfolio/candidates/{metadata['candidate_id']}/origin_evidence/"
    bindings = metadata["origin_artifacts"]
    for item in bindings:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise PortfolioError("origin_artifacts entries must be artifact bindings")
        if not item["path"].startswith(expected_prefix):
            raise PortfolioError("origin evidence must be copied into the candidate directory")
    evidence_directory = directory / "origin_evidence"
    if evidence_directory.is_symlink() or not evidence_directory.is_dir():
        raise PortfolioError("schema v2 candidate requires a safe origin_evidence directory")
    actual = {
        path.relative_to(evidence_directory).as_posix()
        for path in scan_tree(evidence_directory)
    }
    expected = {
        item["path"][len(expected_prefix):]
        for item in bindings
    }
    if actual != expected:
        raise PortfolioError("origin_evidence files must exactly match their bindings")
    if verify:
        verify_bindings(root, bindings, "candidate origin artifacts")


def artifact_bindings(root: Path, values: Any, label: str) -> List[Dict[str, Any]]:
    if not isinstance(values, list):
        raise PortfolioError(f"{label} must be an array of root-relative paths")
    result: List[Dict[str, Any]] = []
    seen = set()
    for relative in values:
        if not isinstance(relative, str) or relative in seen:
            raise PortfolioError(f"{label} entries must be unique strings")
        seen.add(relative)
        path = safe_path(root, relative, kind="file")
        digest, size = file_digest_and_size(path)
        result.append({"path": relative, "sha256": digest, "size": size})
    return result


def verify_bindings(root: Path, bindings: Any, label: str) -> None:
    if not isinstance(bindings, list):
        raise PortfolioError(f"{label} must be an array")
    seen = set()
    for item in bindings:
        require_exact_keys(item, ("path", "sha256", "size"), (), f"{label} entry")
        relative = item["path"]
        if not isinstance(relative, str) or relative in seen:
            raise PortfolioError(f"{label} paths must be unique")
        seen.add(relative)
        if not isinstance(item["sha256"], str) or not SHA_RE.fullmatch(item["sha256"]):
            raise PortfolioError(f"{label} has invalid sha256")
        if not isinstance(item["size"], int) or item["size"] < 0:
            raise PortfolioError(f"{label} has invalid size")
        path = safe_path(root, relative, kind="file")
        digest, size = file_digest_and_size(path)
        if size != item["size"] or digest != item["sha256"]:
            raise PortfolioError(f"bound artifact changed: {relative}")


def _validate_reopen_triggers(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise PortfolioError("PARK requires at least one exact reopen trigger")
    result = []
    ids = set()
    for trigger in value:
        require_exact_keys(trigger, ("trigger_id", "kind", "condition", "evidence_required", "baseline"), (), "reopen trigger")
        trigger_id = require_id(trigger["trigger_id"], "trigger_id")
        if trigger_id in ids:
            raise PortfolioError("reopen trigger IDs must be unique")
        ids.add(trigger_id)
        if trigger["kind"] not in REOPEN_KINDS:
            raise PortfolioError(f"unsupported reopen trigger kind: {trigger['kind']!r}")
        for field in ("condition", "evidence_required", "baseline"):
            require_text(trigger[field], f"reopen trigger {field}")
        result.append(dict(trigger))
    return result


def current_problem_id(metadata: Dict[str, Any], events: Sequence[Dict[str, Any]]) -> Optional[str]:
    result = metadata["problem_id"]
    for event in events:
        if event["event_type"] == "DOSSIER_LINK":
            result = event["problem_id"]
    return result


def derive_candidate(root: Path, directory: Path, *, verify_artifacts_now: bool = True) -> Dict[str, Any]:
    if directory.is_symlink() or not directory.is_dir():
        raise PortfolioError(f"unsafe candidate directory: {directory}")
    metadata = load_json(directory / "candidate.json", "candidate metadata")
    validate_candidate_metadata(metadata)
    _validate_candidate_origin_evidence(root, directory, metadata, verify_artifacts_now)
    if directory.name != metadata["candidate_id"]:
        raise PortfolioError("candidate directory name does not match candidate_id")
    allowed_top = {"candidate.json", "events", "import_receipts"}
    if metadata["schema_version"] >= 2:
        allowed_top.add("origin_evidence")
    for child in directory.iterdir():
        if child.name not in allowed_top:
            raise PortfolioError(f"unexpected candidate entry: {child}")
        if child.is_symlink():
            raise PortfolioError(f"symlink is forbidden: {child}")
    status = "LEAD"
    previous_hash = ZERO_HASH
    parsed_events: List[Dict[str, Any]] = []
    qualification_count = 0
    round_count = 0
    current_park: Optional[Dict[str, Any]] = None
    engagement_tier = "SCOUT"
    engagement_history: List[Dict[str, Any]] = []
    pending_round_decision = False
    event_ids = set()
    for expected_sequence, path in enumerate(event_files(directory), 1):
        expected_prefix = f"{expected_sequence:06d}-"
        if not path.name.startswith(expected_prefix):
            raise PortfolioError(f"event filename sequence gap: {path.name}")
        event = load_json(path, "event")
        require_exact_keys(
            event,
            ("schema_version", "event_type", "event_id", "candidate_id", "sequence", "recorded_at", "previous_event_sha256", "payload"),
            (),
            "event",
        )
        if event["schema_version"] != SCHEMA_VERSION or event["candidate_id"] != metadata["candidate_id"]:
            raise PortfolioError(f"event identity mismatch: {path}")
        event_id = require_id(event["event_id"], "event_id")
        if event_id in event_ids:
            raise PortfolioError(f"event_id is not unique within candidate: {event_id}")
        event_ids.add(event_id)
        require_iso(event["recorded_at"], "event.recorded_at")
        if event["sequence"] != expected_sequence or event["previous_event_sha256"] != previous_hash:
            raise PortfolioError(f"broken append-only event chain: {path}")
        event_type = event["event_type"]
        payload = event["payload"]
        if not isinstance(payload, dict):
            raise PortfolioError("event payload must be an object")
        if event_type == "QUALIFICATION":
            if status != "QUALIFYING":
                raise PortfolioError("qualification record requires QUALIFYING state")
            _validate_qualification_payload(root, payload, verify_artifacts_now)
            qualification_count += 1
        elif event_type == "ROUND":
            if status != "TRIAL_ACTIVE":
                raise PortfolioError("round record requires TRIAL_ACTIVE state")
            if pending_round_decision:
                raise PortfolioError(
                    "the previous round requires an explicit portfolio decision"
                )
            if metadata["schema_version"] >= 2 and engagement_tier not in ("TRIAL", "DEEP"):
                raise PortfolioError("schema v2 round record requires TRIAL or DEEP engagement")
            _validate_round_payload(root, payload, verify_artifacts_now)
            if current_problem_id(metadata, parsed_events) is None:
                raise PortfolioError("round record requires a linked problem dossier")
            round_count += 1
            pending_round_decision = True
        elif event_type == "DOSSIER_LINK":
            if round_count:
                raise PortfolioError(
                    "a candidate dossier cannot be relinked after its first round"
                )
            require_exact_keys(payload, ("problem_id", "reason", "linked_by"), (), "dossier link payload")
            require_problem_id(payload["problem_id"], "problem_id")
            require_text(payload["reason"], "dossier link reason")
            if not isinstance(payload["linked_by"], list) or not payload["linked_by"]:
                raise PortfolioError("linked_by must be non-empty")
            for actor in payload["linked_by"]:
                require_id(actor, "linked_by entry")
        elif event_type == "DECISION":
            status, current_park = _apply_decision_payload(
                root,
                metadata["candidate_id"],
                payload,
                status,
                current_park,
                qualification_count,
                round_count,
                verify_artifacts_now,
            )
            pending_round_decision = False
        elif event_type == "ENGAGEMENT_DECISION":
            engagement_tier = _apply_engagement_payload(
                root,
                payload,
                engagement_tier,
                status,
                qualification_count,
                round_count,
                current_problem_id(metadata, parsed_events),
                pending_round_decision,
                verify_artifacts_now,
            )
            engagement_history.append(dict(payload))
        else:
            raise PortfolioError(f"unsupported event_type: {event_type!r}")
        parsed_events.append({**event, "event_type": event_type, **({"problem_id": payload["problem_id"]} if event_type == "DOSSIER_LINK" else {})})
        previous_hash = sha256_file(path)
    if metadata["problem_id"] is not None:
        resolve_problem(root, metadata["problem_id"])
    linked = current_problem_id(metadata, parsed_events)
    if linked is not None:
        resolve_problem(root, linked)
    receipts = directory / "import_receipts"
    if receipts.exists():
        if receipts.is_symlink() or not stat.S_ISDIR(receipts.lstat().st_mode):
            raise PortfolioError("import_receipts must be a real directory")
        for receipt in sorted(receipts.iterdir()):
            if receipt.is_symlink() or not stat.S_ISREG(receipt.lstat().st_mode) or receipt.suffix != ".json":
                raise PortfolioError("import_receipts may contain only regular JSON files")
            _validate_import_receipt(load_json(receipt, "import receipt"), metadata["candidate_id"])
    return {
        "metadata": metadata,
        "events": parsed_events,
        "status": status,
        "qualification_count": qualification_count,
        "round_count": round_count,
        "current_park": current_park,
        "problem_id": linked,
        "event_count": len(parsed_events),
        "history_head_sha256": previous_hash,
        "origin": metadata.get("origin", "USER_SUPPLIED"),
        "cohort_id": metadata.get("cohort_id"),
        "engagement_tier": engagement_tier,
        "engagement_history": engagement_history,
        "pending_round_decision": pending_round_decision,
        "event_ids": event_ids,
    }


def _validate_qualification_payload(root: Path, payload: Dict[str, Any], verify: bool) -> None:
    require_exact_keys(payload, ("assessed_at", "assessed_by", "exact_statement", "open_assessment", "significance_rationale", "tractability_rationale", "verification_plan", "cheap_falsifiers", "artifacts"), (), "qualification payload")
    require_iso(payload["assessed_at"], "qualification assessed_at")
    if not isinstance(payload["assessed_by"], list) or not payload["assessed_by"]:
        raise PortfolioError("qualification assessed_by must be non-empty")
    for actor in payload["assessed_by"]:
        require_id(actor, "qualification actor")
    for field in ("exact_statement", "significance_rationale", "tractability_rationale", "verification_plan"):
        require_text(payload[field], field)
    if payload["open_assessment"] not in OPEN_ASSESSMENTS:
        raise PortfolioError("invalid open_assessment")
    if not isinstance(payload["cheap_falsifiers"], list) or not payload["cheap_falsifiers"]:
        raise PortfolioError("cheap_falsifiers must be a non-empty array")
    for item in payload["cheap_falsifiers"]:
        require_text(item, "cheap falsifier")
    if verify:
        verify_bindings(root, payload["artifacts"], "qualification artifacts")


def _validate_round_payload(root: Path, payload: Dict[str, Any], verify: bool) -> None:
    require_exact_keys(payload, ("started_at", "completed_at", "conducted_by", "objective", "methods", "observations", "strongest_result", "remaining_gap", "semantic_progress", "proposed_decision", "artifacts"), (), "round payload")
    require_iso(payload["started_at"], "round started_at")
    require_iso(payload["completed_at"], "round completed_at")
    if payload["completed_at"] < payload["started_at"]:
        raise PortfolioError("round completed_at precedes started_at")
    if not isinstance(payload["conducted_by"], list) or not payload["conducted_by"]:
        raise PortfolioError("conducted_by must be non-empty")
    for actor in payload["conducted_by"]:
        require_id(actor, "round actor")
    for field in ("objective", "methods", "observations", "strongest_result", "remaining_gap"):
        require_text(payload[field], field)
    if not isinstance(payload["semantic_progress"], bool):
        raise PortfolioError("semantic_progress must be boolean")
    if payload["proposed_decision"] not in DECISIONS:
        raise PortfolioError("invalid proposed_decision")
    if verify:
        verify_bindings(root, payload["artifacts"], "round artifacts")


def _apply_engagement_payload(
    root: Path,
    payload: Dict[str, Any],
    engagement_tier: str,
    status: str,
    qualification_count: int,
    round_count: int,
    problem_id: Optional[str],
    pending_round_decision: bool,
    verify: bool,
) -> str:
    require_exact_keys(
        payload,
        (
            "from_tier",
            "to_tier",
            "decided_at",
            "decided_by",
            "rationale",
            "supporting_artifacts",
            "funnel_observation",
        ),
        (),
        "engagement decision payload",
    )
    if payload["from_tier"] != engagement_tier:
        raise PortfolioError("engagement decision from_tier does not match current tier")
    target = payload["to_tier"]
    expected_target = {"SCOUT": "TRIAL", "TRIAL": "DEEP"}.get(engagement_tier)
    if target not in ENGAGEMENT_TIERS or target != expected_target:
        raise PortfolioError("engagement must advance exactly SCOUT -> TRIAL -> DEEP")
    require_iso(payload["decided_at"], "engagement decided_at")
    require_text(payload["rationale"], "engagement rationale")
    if not isinstance(payload["decided_by"], list) or not payload["decided_by"]:
        raise PortfolioError("engagement decided_by must be non-empty")
    for actor in payload["decided_by"]:
        require_id(actor, "engagement decision actor")
    if verify:
        verify_bindings(root, payload["supporting_artifacts"], "engagement artifacts")

    funnel = require_exact_keys(
        payload["funnel_observation"],
        ("observed_pool_size", "observed_selected_size", "deviation_rationale"),
        (),
        "funnel observation",
    )
    observed_pool = funnel["observed_pool_size"]
    observed_selected = funnel["observed_selected_size"]
    if (
        not isinstance(observed_pool, int)
        or isinstance(observed_pool, bool)
        or observed_pool < 1
        or not isinstance(observed_selected, int)
        or isinstance(observed_selected, bool)
        or observed_selected < 1
        or observed_selected > observed_pool
    ):
        raise PortfolioError("funnel observation counts must satisfy 1 <= selected <= pool")
    if target == "TRIAL":
        within_recommended_funnel = observed_pool <= 12 and observed_selected <= 3
    else:
        within_recommended_funnel = observed_pool <= 3 and observed_selected == 1
    deviated = not within_recommended_funnel
    if deviated:
        require_text(funnel["deviation_rationale"], "funnel deviation rationale")
    elif funnel["deviation_rationale"] is not None:
        require_text(funnel["deviation_rationale"], "funnel deviation rationale")

    if target == "TRIAL":
        if status != "TRIAL_ACTIVE" or qualification_count < 1 or problem_id is None:
            raise PortfolioError(
                "TRIAL engagement requires TRIAL_ACTIVE status, a qualification, and a linked dossier"
            )
    else:
        if pending_round_decision:
            raise PortfolioError(
                "DEEP engagement requires an explicit decision after the latest round"
            )
        if status != "TRIAL_ACTIVE" or round_count < 1:
            raise PortfolioError(
                "DEEP engagement requires TRIAL_ACTIVE status and at least one substantive trial round"
            )
    return target


def _validate_spinout_success_receipt(
    root: Path,
    candidate_id: str,
    seed_id: str,
    spinout: Dict[str, Any],
    verify: bool,
) -> None:
    seed_directory = safe_path(root, f"portfolio/spinouts/{seed_id}", kind="dir")
    manifest = verify_package(seed_directory, "DISCOVERY_SPINOUT_SEED_V1")
    if (
        manifest["package_id"] != seed_id
        or manifest["candidate_id"] != candidate_id
        or manifest["candidate_status"] != "SPINOUT_READY"
    ):
        raise PortfolioError("spinout seed identity/status does not match this candidate")
    expected_manifest = f"portfolio/spinouts/{seed_id}/manifest.json"
    if not isinstance(spinout["seed_manifest"], dict) or (
        spinout["seed_manifest"].get("path") != expected_manifest
    ):
        raise PortfolioError("spinout seed_manifest path mismatch")
    if verify:
        verify_bindings(root, [spinout["seed_manifest"]], "spinout manifest")
        verify_bindings(root, [spinout["receipt_artifact"]], "spinout receipt")
    receipt_binding = spinout["receipt_artifact"]
    if not isinstance(receipt_binding, dict) or not isinstance(
        receipt_binding.get("path"), str
    ):
        raise PortfolioError("spinout receipt binding is invalid")
    receipt = load_json(
        safe_path(root, receipt_binding["path"], kind="file"),
        "spinout success receipt",
    )
    require_exact_keys(
        receipt,
        (
            "schema_version",
            "seed_id",
            "target_lab_id",
            "seed_manifest_sha256",
            "doctor_passed",
            "validator_passed",
            "smoke_eval_passed",
            "recorded_at",
            "recorded_by",
        ),
        (),
        "spinout success receipt",
    )
    if receipt["schema_version"] != 1 or receipt["seed_id"] != seed_id:
        raise PortfolioError("spinout receipt seed identity mismatch")
    target_lab_id = require_project_id(receipt["target_lab_id"], "target_lab_id")
    if target_lab_id != manifest["target_project_id"]:
        raise PortfolioError("spinout receipt target laboratory mismatch")
    manifest_digest = sha256_file(seed_directory / "manifest.json")
    if receipt["seed_manifest_sha256"] != manifest_digest:
        raise PortfolioError("spinout receipt seed manifest digest mismatch")
    for field in ("doctor_passed", "validator_passed", "smoke_eval_passed"):
        if receipt[field] is not True:
            raise PortfolioError(f"spinout receipt requires {field}=true")
    require_iso(receipt["recorded_at"], "spinout receipt recorded_at")
    require_id(receipt["recorded_by"], "spinout receipt recorded_by")


def _apply_decision_payload(
    root: Path,
    candidate_id: str,
    payload: Dict[str, Any],
    status: str,
    current_park: Optional[Dict[str, Any]],
    qualification_count: int,
    round_count: int,
    verify: bool,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    require_exact_keys(payload, ("decision", "from_status", "to_status", "decided_at", "decided_by", "rationale", "supporting_artifacts", "park", "reopen", "spinout"), (), "decision payload")
    if payload["decision"] not in DECISIONS or payload["from_status"] != status or payload["to_status"] not in CANDIDATE_STATUSES:
        raise PortfolioError("decision state identity is invalid")
    require_iso(payload["decided_at"], "decision decided_at")
    require_text(payload["rationale"], "decision rationale")
    if not isinstance(payload["decided_by"], list) or not payload["decided_by"]:
        raise PortfolioError("decided_by must be non-empty")
    for actor in payload["decided_by"]:
        require_id(actor, "decision actor")
    if verify:
        verify_bindings(root, payload["supporting_artifacts"], "decision artifacts")
    decision, target = payload["decision"], payload["to_status"]
    next_park = current_park
    if decision == "PARK":
        if status in ("REJECTED", "SPUN_OUT") or target != "PARKED":
            raise PortfolioError("invalid PARK transition")
        park = require_exact_keys(payload["park"], ("exact_barrier", "resume_status", "reopen_triggers"), (), "park plan")
        require_text(park["exact_barrier"], "exact barrier")
        allowed_resume = "QUALIFYING" if status in ("LEAD", "QUALIFYING") else "TRIAL_ACTIVE"
        if park["resume_status"] != allowed_resume:
            raise PortfolioError(f"park resume_status must be {allowed_resume}")
        _validate_reopen_triggers(park["reopen_triggers"])
        if payload["reopen"] is not None or payload["spinout"] is not None:
            raise PortfolioError("PARK may not carry reopen or spinout data")
        next_park = park
    elif decision == "REJECT":
        if status in ("REJECTED", "SPUN_OUT") or target != "REJECTED":
            raise PortfolioError("invalid REJECT transition")
        if any(payload[key] is not None for key in ("park", "reopen", "spinout")):
            raise PortfolioError("REJECT may not carry park/reopen/spinout data")
        next_park = None
    elif decision == "CONTINUE":
        expected = {
            "LEAD": "QUALIFYING",
            "QUALIFYING": "TRIAL_ACTIVE",
            "TRIAL_ACTIVE": "TRIAL_ACTIVE",
            "SPINOUT_READY": "TRIAL_ACTIVE",
        }.get(status)
        if status == "QUALIFYING" and qualification_count < 1:
            raise PortfolioError("QUALIFYING requires a qualification record before trial")
        if status == "PARKED":
            if current_park is None or target != current_park["resume_status"]:
                raise PortfolioError("PARKED candidate must resume at its recorded resume_status")
            reopen = require_exact_keys(payload["reopen"], ("trigger_id", "evidence", "evidence_artifact"), (), "reopen evidence")
            matching = [item for item in current_park["reopen_triggers"] if item["trigger_id"] == reopen["trigger_id"]]
            if len(matching) != 1:
                raise PortfolioError("reopen trigger does not match the current park plan")
            require_text(reopen["evidence"], "reopen evidence")
            if reopen["evidence_artifact"] is not None:
                binding = reopen["evidence_artifact"]
                if verify:
                    verify_bindings(root, [binding], "reopen evidence artifact")
            expected = target
        elif payload["reopen"] is not None:
            raise PortfolioError("reopen evidence is allowed only from PARKED")
        if expected is None or target != expected:
            raise PortfolioError("invalid CONTINUE transition")
        if payload["park"] is not None or payload["spinout"] is not None:
            raise PortfolioError("CONTINUE may not carry park or spinout data")
        next_park = None
    else:  # SPIN_OUT
        if status == "TRIAL_ACTIVE":
            if target != "SPINOUT_READY" or round_count < 1 or payload["spinout"] is not None:
                raise PortfolioError("first SPIN_OUT requires a substantive round and SPINOUT_READY target")
        elif status == "SPINOUT_READY":
            if target != "SPUN_OUT":
                raise PortfolioError("final SPIN_OUT must target SPUN_OUT")
            spinout = require_exact_keys(payload["spinout"], ("seed_id", "seed_manifest", "receipt_artifact"), (), "spinout receipt binding")
            seed_id = require_id(spinout["seed_id"], "seed_id")
            _validate_spinout_success_receipt(
                root, candidate_id, seed_id, spinout, verify
            )
        else:
            raise PortfolioError("SPIN_OUT is allowed only from TRIAL_ACTIVE or SPINOUT_READY")
        if payload["park"] is not None or payload["reopen"] is not None:
            raise PortfolioError("SPIN_OUT may not carry park/reopen data")
        next_park = None
    return target, next_park


def list_candidates(root: Path, *, verify_artifacts_now: bool = True) -> List[Dict[str, Any]]:
    candidates = safe_path(root, "portfolio/candidates", kind="dir")
    result = []
    for directory in sorted(candidates.iterdir()):
        if directory.name == "README.md":
            continue
        if directory.is_symlink() or not directory.is_dir():
            raise PortfolioError(f"candidate root contains unsafe entry: {directory}")
        require_id(directory.name, "candidate directory")
        result.append(derive_candidate(root, directory, verify_artifacts_now=verify_artifacts_now))
    return result


def derived_funnel_observation(
    root: Path,
    candidate_id: str,
    target_tier: str,
    supplied: Any,
) -> Dict[str, Any]:
    """Bind a promotion to the actual current cohort, never caller-only counts."""
    observation = require_exact_keys(
        supplied,
        ("observed_pool_size", "observed_selected_size", "deviation_rationale"),
        (),
        "funnel observation",
    )
    states = list_candidates(root)
    matching = [
        state for state in states if state["metadata"]["candidate_id"] == candidate_id
    ]
    if len(matching) != 1:
        raise PortfolioError("promotion candidate does not resolve exactly once")
    current = matching[0]
    cohort_id = current["cohort_id"]
    cohort = (
        [state for state in states if state["cohort_id"] == cohort_id]
        if cohort_id is not None
        else [current]
    )
    if target_tier == "TRIAL":
        pool_size = len(cohort)
        selected_size = sum(
            state["engagement_tier"] in ("TRIAL", "DEEP") for state in cohort
        )
        if current["engagement_tier"] == "SCOUT":
            selected_size += 1
    elif target_tier == "DEEP":
        pool_size = sum(
            state["engagement_tier"] in ("TRIAL", "DEEP") for state in cohort
        )
        selected_size = sum(
            state["engagement_tier"] == "DEEP" for state in cohort
        )
        if current["engagement_tier"] == "TRIAL":
            selected_size += 1
    else:
        raise PortfolioError("unsupported funnel target tier")
    claimed = (
        observation["observed_pool_size"],
        observation["observed_selected_size"],
    )
    derived = (pool_size, selected_size)
    if claimed != derived:
        raise PortfolioError(
            "funnel observation must equal the current canonical cohort counts; "
            f"claimed={claimed}, derived={derived}"
        )
    return {
        "observed_pool_size": pool_size,
        "observed_selected_size": selected_size,
        "deviation_rationale": observation["deviation_rationale"],
    }


_STAGE_PREFIXES = {
    "CANDIDATE": ".candidate-stage-",
    "EVENT_PREFLIGHT": ".event-preflight-",
    "IMPORT_PREFLIGHT": ".import-preflight-",
    "PACKAGE": ".package-stage-",
}
_STAGE_MARKER = ".discovery-portfolio-stage.json"


def create_staging_directory(root: Path, kind: str) -> Path:
    if kind not in _STAGE_PREFIXES:
        raise PortfolioError(f"unsupported staging kind: {kind}")
    inbox = safe_path(root, "portfolio/inbox", kind="dir")
    stage = Path(tempfile.mkdtemp(prefix=_STAGE_PREFIXES[kind], dir=str(inbox)))
    try:
        write_json_exclusive(
            stage / _STAGE_MARKER,
            {
                "schema_version": 1,
                "owner": "discovery_portfolio",
                "kind": kind,
            },
        )
        _fsync_directory(stage)
        _fsync_directory(inbox)
        return stage
    except Exception:
        shutil.rmtree(stage)
        raise


def remove_staging_marker(stage: Path, kind: str) -> None:
    marker = stage / _STAGE_MARKER
    value = load_json(marker, "staging marker")
    expected = {
        "schema_version": 1,
        "owner": "discovery_portfolio",
        "kind": kind,
    }
    if value != expected or marker.is_symlink():
        raise PortfolioError(f"staging marker identity mismatch: {stage}")
    marker.unlink()
    _fsync_directory(stage)


def cleanup_abandoned_stages(root: Path) -> List[str]:
    """Remove only marker-bound staging directories after acquiring the lock."""
    removed: List[str] = []
    for relative in ("portfolio/inbox",):
        parent = safe_path(root, relative, kind="dir")
        changed = False
        for child in sorted(parent.iterdir()):
            matching = [
                kind
                for kind, prefix in _STAGE_PREFIXES.items()
                if re.fullmatch(re.escape(prefix) + r"[a-z0-9_]{8}", child.name)
            ]
            if len(matching) != 1 or child.is_symlink() or not child.is_dir():
                continue
            marker = child / _STAGE_MARKER
            if marker.is_symlink() or not marker.is_file():
                continue
            try:
                value = load_json(marker, "staging marker")
            except PortfolioError:
                continue
            if value != {
                "schema_version": 1,
                "owner": "discovery_portfolio",
                "kind": matching[0],
            }:
                continue
            shutil.rmtree(child)
            removed.append(child.relative_to(root).as_posix())
            changed = True
        if changed:
            _fsync_directory(parent)
    return removed


def _artifact_binding_paths(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        if set(value) == {"path", "sha256", "size"}:
            path = value.get("path")
            if isinstance(path, str):
                yield path
        for item in value.values():
            yield from _artifact_binding_paths(item)
    elif isinstance(value, list):
        for item in value:
            yield from _artifact_binding_paths(item)


def validate_transfer_closure(state: Dict[str, Any]) -> None:
    """Require candidate-only closure for a dossier-free transfer package."""
    candidate_id = state["metadata"]["candidate_id"]
    if state["problem_id"] is not None:
        raise PortfolioError(
            "candidate transfer is not closed: linked problem dossiers require spin-out"
        )
    prefix = f"portfolio/candidates/{candidate_id}/"
    external = sorted(
        {
            path
            for path in _artifact_binding_paths(
                {"metadata": state["metadata"], "events": state["events"]}
            )
            if not path.startswith(prefix)
        }
    )
    if external:
        raise PortfolioError(
            "candidate transfer is not closed over external artifact bindings: "
            + ", ".join(external)
        )


def append_event(root: Path, candidate_id: str, event_type: str, event_id: str, payload: Dict[str, Any]) -> Path:
    source = candidate_root(root, candidate_id)
    state = derive_candidate(root, source)
    event_id = require_id(event_id, "event_id")
    existing = [event for event in state["events"] if event["event_id"] == event_id]
    if existing:
        event = existing[0]
        if event["event_type"] != event_type or event["payload"] != payload:
            raise PortfolioError(
                f"event_id {event_id!r} is already bound to different event bytes"
            )
        return event_files(source)[event["sequence"] - 1]
    sequence = state["event_count"] + 1
    record = {
        "schema_version": SCHEMA_VERSION,
        "event_type": event_type,
        "event_id": event_id,
        "candidate_id": candidate_id,
        "sequence": sequence,
        "recorded_at": utc_now(),
        "previous_event_sha256": state["history_head_sha256"],
        "payload": payload,
    }
    filename = f"{sequence:06d}-{event_type.lower().replace('_', '-')}-{event_id}.json"
    path = source / "events" / filename
    # Validate the exact prospective bytes against a complete temporary copy.
    # An invalid transition therefore cannot append a record that bricks the
    # live candidate.  The caller holds the portfolio lock during publication.
    stage_root = create_staging_directory(root, "EVENT_PREFLIGHT")
    try:
        stage = stage_root / candidate_id
        copy_safe_tree(source, stage)
        write_json_exclusive(stage / "events" / filename, record)
        derive_candidate(root, stage)
        # Recheck both the live history head and all bound artifacts immediately
        # before publication. The portfolio lock serializes cooperating writers.
        latest = derive_candidate(root, source)
        if (
            latest["event_count"] != state["event_count"]
            or latest["history_head_sha256"] != state["history_head_sha256"]
        ):
            raise PortfolioError("candidate history changed during event preflight")
        derive_candidate(root, stage)
    finally:
        if stage_root.exists():
            shutil.rmtree(stage_root)
    write_json_atomic_exclusive(
        path,
        record,
        staging_directory=safe_path(root, "portfolio/inbox", kind="dir"),
    )
    return path


def summary_digest(summary: Dict[str, Any]) -> str:
    payload = {key: value for key, value in summary.items() if key not in ("generated_at", "source_digest_sha256")}
    return sha256_bytes(canonical_bytes(payload, ensure_ascii=True))


def validate_summary_shape(summary: Dict[str, Any], *, verify_digest: bool = True) -> None:
    require_exact_keys(summary, ("schema_version", "generated_at", "lab_kind", "source_digest_sha256", "candidate_counts", "pending_cycle_decision", "model_recheck_count", "last_cycle_at", "next_cycle_at", "repository"), (), "control-room summary")
    if summary["schema_version"] != 1 or summary["lab_kind"] != "DISCOVERY_PORTFOLIO":
        raise PortfolioError("control-room summary identity is invalid")
    if summary["generated_at"] is not None:
        require_iso(summary["generated_at"], "summary generated_at")
    counts = require_exact_keys(summary["candidate_counts"], CANDIDATE_STATUSES, (), "candidate_counts")
    if any(not isinstance(counts[key], int) or isinstance(counts[key], bool) or counts[key] < 0 for key in CANDIDATE_STATUSES):
        raise PortfolioError("candidate_counts values must be non-negative integers")
    if not isinstance(summary["pending_cycle_decision"], bool):
        raise PortfolioError("pending_cycle_decision must be boolean")
    if not isinstance(summary["model_recheck_count"], int) or isinstance(summary["model_recheck_count"], bool) or summary["model_recheck_count"] < 0:
        raise PortfolioError("model_recheck_count must be a non-negative integer")
    for key in ("last_cycle_at", "next_cycle_at"):
        if summary[key] is not None:
            require_iso(summary[key], key)
    repository = require_exact_keys(summary["repository"], ("state", "visibility"), (), "repository summary")
    if repository["state"] not in REPOSITORY_STATES or repository["visibility"] not in REPOSITORY_VISIBILITIES:
        raise PortfolioError("repository summary enum is invalid")
    digest = summary["source_digest_sha256"]
    if not isinstance(digest, str) or not SHA_RE.fullmatch(digest):
        raise PortfolioError("summary source_digest_sha256 is invalid")
    if verify_digest and digest != summary_digest(summary):
        raise PortfolioError("summary canonical digest mismatch")


def refresh_summary(
    root: Path,
    *,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    with FileLock(root / "portfolio/.discovery-portfolio.lock"):
        cleanup_abandoned_stages(root)
        with FileLock(root / "knowledge/.control-room-summary.lock"):
            preflight_summary_update(root)
            return _refresh_summary_locked(root, generated_at=generated_at)


def preflight_summary_update(root: Path) -> None:
    """Validate the projection before any primary mutation commits."""
    summary_path = root / "knowledge/control_room_summary.json"
    if summary_path.exists():
        validate_summary_shape(load_json(summary_path, "control-room summary"))


def _refresh_summary_locked(
    root: Path, *, generated_at: Optional[str] = None
) -> Dict[str, Any]:
    """Refresh while both portfolio and shared summary locks are already held."""
    states = list_candidates(root)
    counts = {status: 0 for status in CANDIDATE_STATUSES}
    model_recheck_count = 0
    for state in states:
        counts[state["status"]] += 1
        park = state["current_park"]
        if state["status"] == "PARKED" and park and any(item["kind"] == "MODEL_CAPABILITY_CHANGE" for item in park["reopen_triggers"]):
            model_recheck_count += 1
    summary_path = root / "knowledge/control_room_summary.json"
    preserved = {
        "pending_cycle_decision": False,
        "last_cycle_at": None,
        "next_cycle_at": None,
        "repository": {"state": "NOT_CONFIGURED", "visibility": "UNDECIDED"},
    }
    if summary_path.exists():
        previous = load_json(summary_path, "control-room summary")
        validate_summary_shape(previous)
        for key in preserved:
            preserved[key] = previous[key]
    summary: Dict[str, Any] = {
        "schema_version": 1,
        "generated_at": generated_at or utc_now(),
        "lab_kind": "DISCOVERY_PORTFOLIO",
        "source_digest_sha256": ZERO_HASH,
        "candidate_counts": counts,
        "pending_cycle_decision": preserved["pending_cycle_decision"],
        "model_recheck_count": model_recheck_count,
        "last_cycle_at": preserved["last_cycle_at"],
        "next_cycle_at": preserved["next_cycle_at"],
        "repository": preserved["repository"],
    }
    summary["source_digest_sha256"] = summary_digest(summary)
    # The shared lock was acquired before the primary mutation. Re-read while
    # still holding it so a team update is never silently reset.
    if summary_path.exists():
        latest = load_json(summary_path, "control-room summary")
        validate_summary_shape(latest)
        for key in ("pending_cycle_decision", "last_cycle_at", "next_cycle_at", "repository"):
            summary[key] = latest[key]
        summary["source_digest_sha256"] = summary_digest(summary)
    write_json_atomic(summary_path, summary)
    return summary


def package_file_entries(payload: Path) -> List[Dict[str, Any]]:
    entries = []
    for path in scan_tree(payload):
        relative = path.relative_to(payload).as_posix()
        digest, size = file_digest_and_size(path)
        entries.append({"path": relative, "sha256": digest, "size": size})
    return entries


def package_payload_digest(entries: Sequence[Dict[str, Any]]) -> str:
    return sha256_bytes(canonical_bytes(list(entries)))


def verify_package(package: Path, expected_kind: str) -> Dict[str, Any]:
    scan_tree(package)
    top_names = {path.name for path in package.iterdir()}
    if top_names != {"manifest.json", "payload"}:
        raise PortfolioError("package may contain only manifest.json and payload/")
    if (package / "manifest.json").is_symlink() or not (package / "payload").is_dir() or (package / "payload").is_symlink():
        raise PortfolioError("package top-level entries are unsafe")
    manifest = load_json(package / "manifest.json", "package manifest")
    require_exact_keys(manifest, ("schema_version", "package_kind", "package_id", "created_at", "source_project_id", "target_project_id", "candidate_id", "candidate_status", "payload_root", "files", "payload_digest_sha256", "source_retained", "mathematical_status_effect", "requires_factory_generation"), (), "package manifest")
    if manifest["schema_version"] != 1 or manifest["package_kind"] != expected_kind:
        raise PortfolioError("package kind/schema mismatch")
    for field in ("package_id", "candidate_id"):
        require_id(manifest[field], field)
    for field in ("source_project_id", "target_project_id"):
        require_project_id(manifest[field], field)
    require_iso(manifest["created_at"], "package created_at")
    if manifest["candidate_status"] not in CANDIDATE_STATUSES:
        raise PortfolioError("invalid package candidate_status")
    requires_factory = expected_kind == "DISCOVERY_SPINOUT_SEED_V1"
    if (
        manifest["payload_root"] != "payload"
        or manifest["source_retained"] is not True
        or manifest["mathematical_status_effect"] != "NONE"
        or manifest["requires_factory_generation"] is not requires_factory
    ):
        raise PortfolioError("package safety declarations are invalid")
    payload = package / "payload"
    actual_entries = package_file_entries(payload)
    if manifest["files"] != actual_entries or manifest["payload_digest_sha256"] != package_payload_digest(actual_entries):
        raise PortfolioError("package payload hash binding failed")
    return manifest


def _validate_import_receipt(receipt: Dict[str, Any], candidate_id: str) -> None:
    require_exact_keys(receipt, ("schema_version", "package_id", "package_manifest_sha256", "candidate_id", "source_project_id", "target_project_id", "imported_at", "source_package_retained", "mathematical_status_effect"), (), "import receipt")
    if receipt["schema_version"] != 1 or receipt["candidate_id"] != candidate_id:
        raise PortfolioError("import receipt identity mismatch")
    require_id(receipt["package_id"], "package_id")
    for field in ("source_project_id", "target_project_id"):
        require_project_id(receipt[field], field)
    if not isinstance(receipt["package_manifest_sha256"], str) or not SHA_RE.fullmatch(receipt["package_manifest_sha256"]):
        raise PortfolioError("invalid import package manifest digest")
    require_iso(receipt["imported_at"], "imported_at")
    if receipt["source_package_retained"] is not True or receipt["mathematical_status_effect"] != "NONE":
        raise PortfolioError("import receipt safety declaration invalid")
