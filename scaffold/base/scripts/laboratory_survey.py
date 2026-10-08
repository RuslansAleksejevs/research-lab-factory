#!/usr/bin/env python3
"""Build and freshness-check hash-bound whole-laboratory survey packets.

`snapshot` and `check` are read-only. `start` and `finalize` are used only when
the user explicitly asks to persist a survey. Hashes identify the evidence
snapshot; they do not verify mathematics, sources, novelty, or independence.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
SURVEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
RESEARCH_MEMORY_STAGING_NAME = re.compile(
    r"^\.(?:research-memory|checkpoint-index)-[0-9a-f]{32}$"
)

TOP_LEVEL_FILES = (
    "LAB_PROFILE.json",
    "PROJECT_CHARTER.md",
    "BOOTSTRAP_REPORT.md",
    "USER_PREFERENCES.md",
    "BACKLOG.md",
    "CHANGELOG.md",
    ".lab/manifest.json",
    ".lab/bootstrap_inputs.json",
    "problems/INDEX.md",
)

SCAN_ROOTS = (
    "knowledge",
    "decisions",
    "problems/active",
    "problems/backlog",
    "problems/closed",
    "research",
    "results",
    "research_reports",
    "runs",
    "paper",
    "talks",
    "portfolio",
    "collaboration",
    "archive",
    "sources/manifests",
    "sources/digests",
    "sources/bibliography",
    "00_INBOX_TO_ANALYZE",
)

EXCLUDED_PATHS = {
    "knowledge/resume.md",
    "knowledge/laboratory_overview.md",
    "knowledge/laboratory_survey_state.json",
}

EXCLUDED_PREFIXES = (
    "runs/laboratory_surveys/",
    "runs/laboratory_stewardship/",
    "archive/migrations/",
)

EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".lake",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "output",
    "tmp",
}

EXCLUSION_NOTES = (
    ".git and cache/build directories",
    "archive/migrations/**",
    "prior runs/laboratory_surveys/**",
    "runs/laboratory_stewardship/** (bound explicitly when relevant)",
    "knowledge/resume.md",
    "knowledge/laboratory_overview.md",
    "knowledge/laboratory_survey_state.json",
    "source originals/extracted bodies unless represented by current digests or manifests",
    "reserved interrupted-write temporary names containing .survey-",
    "exact research-memory staging names directly under research/",
)


class SurveyError(RuntimeError):
    pass


TEMPLATE_ID = "math-research-lab-template"
START_IMMUTABLE_FIELDS = (
    "schema_version",
    "survey_id",
    "mode",
    "started_at_utc",
    "starting_basis_sha256",
    "external_bindings",
    "integrity_note",
)
_ROOT_PINS: Dict[str, Tuple[int, int]] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_root(path: Path) -> Path:
    if not path.is_absolute():
        path = Path.cwd() / path
    path = Path(os.path.normpath(str(path)))
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SurveyError(f"cannot inspect laboratory root {path}: {exc}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode):
            raise SurveyError(f"laboratory root must be a real directory: {path}")
        key = (info.st_dev, info.st_ino)
    finally:
        os.close(descriptor)
    label = str(path)
    pinned = _ROOT_PINS.get(label)
    if pinned is not None and pinned != key:
        raise SurveyError(f"laboratory root identity changed during this process: {path}")
    _ROOT_PINS[label] = key
    return path


def relative_name(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise SurveyError(f"path escaped laboratory root: {path}") from exc


def excluded(relative: str) -> bool:
    if relative in EXCLUDED_PATHS:
        return True
    return any(relative.startswith(prefix) for prefix in EXCLUDED_PREFIXES)


def safe_hash_file(root: Path, path: Path) -> Dict[str, Any]:
    relative = relative_name(root, path)
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SurveyError(f"cannot safely read {relative}: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise SurveyError(f"not a regular file: {relative}")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(descriptor)
        before_key = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            getattr(before, "st_mtime_ns", int(before.st_mtime * 1_000_000_000)),
        )
        after_key = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            getattr(after, "st_mtime_ns", int(after.st_mtime * 1_000_000_000)),
        )
        if before_key != after_key:
            raise SurveyError(f"file changed while hashing: {relative}")
        return {
            "path": relative,
            "size": after.st_size,
            "sha256": digest.hexdigest(),
        }
    finally:
        os.close(descriptor)


def inspect_candidate(
    root: Path,
    path: Path,
    files: List[Dict[str, Any]],
    skipped: List[Dict[str, str]],
) -> None:
    relative = relative_name(root, path)
    if excluded(relative):
        return
    if ".survey-" in path.name:
        return
    if (
        path.parent == root / "research"
        and RESEARCH_MEMORY_STAGING_NAME.fullmatch(path.name)
    ):
        return
    try:
        info = path.lstat()
    except OSError as exc:
        skipped.append({"path": relative, "reason": f"unreadable metadata: {exc}"})
        return
    if stat.S_ISLNK(info.st_mode):
        skipped.append({"path": relative, "reason": "symlink not followed"})
        return
    if not stat.S_ISREG(info.st_mode):
        skipped.append({"path": relative, "reason": "special file not read"})
        return
    try:
        files.append(safe_hash_file(root, path))
    except SurveyError as exc:
        skipped.append({"path": relative, "reason": str(exc)})


def scan_directory(
    root: Path,
    start: Path,
    files: List[Dict[str, Any]],
    skipped: List[Dict[str, str]],
) -> None:
    for current_text, directories, filenames in os.walk(start, topdown=True, followlinks=False):
        current = Path(current_text)
        kept: List[str] = []
        for name in sorted(directories):
            child = current / name
            relative = relative_name(root, child)
            if name in EXCLUDED_DIRECTORY_NAMES or excluded(relative + "/"):
                continue
            try:
                info = child.lstat()
            except OSError as exc:
                skipped.append(
                    {"path": relative, "reason": f"unreadable directory metadata: {exc}"}
                )
                continue
            if stat.S_ISLNK(info.st_mode):
                skipped.append({"path": relative, "reason": "directory symlink not followed"})
                continue
            if not stat.S_ISDIR(info.st_mode):
                skipped.append({"path": relative, "reason": "non-directory tree entry"})
                continue
            kept.append(name)
        directories[:] = kept
        for name in sorted(filenames):
            inspect_candidate(root, current / name, files, skipped)


def build_snapshot(root: Path) -> Dict[str, Any]:
    root = require_root(root)
    files: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []
    included_roots: List[str] = []
    absent_roots: List[str] = []

    for relative in TOP_LEVEL_FILES:
        path = root / relative
        if path.exists() or path.is_symlink():
            included_roots.append(relative)
            inspect_candidate(root, path, files, skipped)
        else:
            absent_roots.append(relative)

    for relative in SCAN_ROOTS:
        path = root / relative
        try:
            info = path.lstat()
        except FileNotFoundError:
            absent_roots.append(relative + "/")
            continue
        except OSError as exc:
            skipped.append({"path": relative, "reason": f"cannot inspect root: {exc}"})
            continue
        if stat.S_ISLNK(info.st_mode):
            skipped.append({"path": relative, "reason": "scan-root symlink not followed"})
            continue
        if not stat.S_ISDIR(info.st_mode):
            skipped.append({"path": relative, "reason": "scan root is not a directory"})
            continue
        included_roots.append(relative + "/")
        scan_directory(root, path, files, skipped)

    files.sort(key=lambda item: item["path"])
    skipped.sort(key=lambda item: (item["path"], item["reason"]))
    basis = {"files": files, "skipped": skipped}
    return {
        "schema_version": 1,
        "generated_at_utc": utc_now(),
        "inventory_sha256": sha256_bytes(canonical_json(basis)),
        "coverage": "COMPLETE_WITHIN_DECLARED_SCOPE" if not skipped else "PARTIAL",
        "included_roots": sorted(included_roots),
        "absent_optional_roots": sorted(absent_roots),
        "exclusions": list(EXCLUSION_NOTES),
        "files": files,
        "skipped": skipped,
        "visibility_warning": (
            "Chat-only results and unfinished agent outputs are not observable until checkpointed."
        ),
        "integrity_note": (
            "The digest identifies a filesystem evidence snapshot; it does not prove mathematics, "
            "source truth, novelty, or agent independence."
        ),
    }


def snapshot_changes(before: Dict[str, Any], after: Dict[str, Any]) -> List[str]:
    before_map = {item["path"]: item["sha256"] for item in before.get("files", [])}
    after_map = {item["path"]: item["sha256"] for item in after.get("files", [])}
    paths = sorted(set(before_map) | set(after_map))
    changed = [path for path in paths if before_map.get(path) != after_map.get(path)]
    if before.get("skipped") != after.get("skipped"):
        changed.append("<coverage-or-skipped-set-changed>")
    return changed


def safe_read_bytes(path: Path, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SurveyError(f"cannot safely open {label} {path}: {exc}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise SurveyError(f"{label} is not a regular file: {path}")
        chunks: List[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def safe_read_object(path: Path, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(safe_read_bytes(path, label).decode("utf-8"))
    except SurveyError:
        raise
    except Exception as exc:
        raise SurveyError(f"cannot parse {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SurveyError(f"{label} must contain a JSON object: {path}")
    return value


def require_lab_identity(root: Path) -> str:
    """Require an instantiated generated lab or an explicit legacy lab.

    The base scaffold intentionally contains much of the laboratory kernel, so
    the legacy test also requires instantiated bootstrap files. This prevents a
    write-capable survey command from treating the factory scaffold as live
    research state.
    """

    root = require_root(root)
    profile_path = root / "LAB_PROFILE.json"
    manifest_path = root / ".lab" / "manifest.json"
    profile_present = profile_path.exists() or profile_path.is_symlink()
    manifest_present = manifest_path.exists() or manifest_path.is_symlink()

    if manifest_present:
        if not profile_present:
            raise SurveyError("generated laboratory identity is missing LAB_PROFILE.json")
        _profile_relative, checked_profile = canonical_binding_path(root, "LAB_PROFILE.json")
        _manifest_relative, checked_manifest = canonical_binding_path(
            root, ".lab/manifest.json"
        )
        profile = safe_read_object(checked_profile, "laboratory profile")
        manifest = safe_read_object(checked_manifest, "laboratory manifest")
        profile_template = profile.get("template")
        profile_template_id = (
            profile_template.get("id") if isinstance(profile_template, dict) else None
        )
        if (
            manifest.get("template_id") != TEMPLATE_ID
            or profile_template_id != TEMPLATE_ID
            or manifest.get("template_id") != profile_template_id
        ):
            raise SurveyError("generated laboratory template identity does not match")
        return "GENERATED"

    if profile_present:
        _profile_relative, checked_profile = canonical_binding_path(root, "LAB_PROFILE.json")
        profile = safe_read_object(checked_profile, "laboratory profile")
        profile_template = profile.get("template")
        if (
            isinstance(profile_template, dict)
            and profile_template.get("id") == TEMPLATE_ID
        ):
            raise SurveyError("generated laboratory identity is missing .lab/manifest.json")

    required_legacy_files = (
        "AGENTS.md",
        "BOOTSTRAP_REPORT.md",
        "USER_PREFERENCES.md",
        "scripts/doctor.py",
        "scripts/run_evals.py",
    )
    legacy_bytes: Dict[str, bytes] = {}
    for relative in required_legacy_files:
        try:
            _canonical, path = canonical_binding_path(root, relative)
            legacy_bytes[relative] = safe_read_bytes(path, "legacy laboratory marker")
        except SurveyError as exc:
            raise SurveyError(
                "root is neither a generated laboratory nor a complete legacy laboratory: "
                f"{relative} is unavailable"
            ) from exc
    try:
        instructions = legacy_bytes["AGENTS.md"].decode("utf-8").casefold()
    except UnicodeDecodeError as exc:
        raise SurveyError("legacy laboratory AGENTS.md is not UTF-8") from exc
    if "long-lived mathematical research laboratory" not in instructions:
        raise SurveyError("legacy laboratory identity marker is absent from AGENTS.md")
    return "LEGACY"


def canonical_binding_path(root: Path, raw: str) -> Tuple[str, Path]:
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        raise SurveyError(f"invalid external binding path: {raw!r}")
    candidate = Path(raw)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise SurveyError(f"external binding must be a canonical relative path: {raw!r}")
    relative = candidate.as_posix()
    path = root.joinpath(*candidate.parts)
    try:
        resolved = path.resolve(strict=True)
        root_resolved = root.resolve(strict=True)
        resolved.relative_to(root_resolved)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SurveyError(f"external binding escapes or is unreadable: {raw!r}") from exc
    current = root
    for part in candidate.parts:
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise SurveyError(f"cannot inspect external binding component: {raw!r}") from exc
        if stat.S_ISLNK(info.st_mode):
            raise SurveyError(f"external binding may not use symlinked components: {raw!r}")
    return relative, path


def collect_bindings(root: Path, paths: Sequence[str]) -> List[Dict[str, Any]]:
    bindings: List[Dict[str, Any]] = []
    seen = set()
    for raw in paths:
        relative, path = canonical_binding_path(root, raw)
        if relative in seen:
            raise SurveyError(f"duplicate external binding: {relative}")
        seen.add(relative)
        data = safe_read_bytes(path, "external binding")
        bindings.append(
            {"path": relative, "size": len(data), "sha256": sha256_bytes(data)}
        )
    return sorted(bindings, key=lambda item: item["path"])


def binding_changes(root: Path, bindings: Any) -> List[str]:
    if not isinstance(bindings, list):
        raise SurveyError("survey manifest external_bindings must be an array")
    changed: List[str] = []
    seen = set()
    for item in bindings:
        if not isinstance(item, dict):
            raise SurveyError("survey manifest contains a malformed external binding")
        raw = item.get("path")
        if not isinstance(raw, str) or raw in seen:
            raise SurveyError("survey manifest contains a duplicate or invalid binding path")
        seen.add(raw)
        try:
            relative, path = canonical_binding_path(root, raw)
            data = safe_read_bytes(path, "external binding")
        except SurveyError:
            changed.append(f"<external-binding:{raw}>")
            continue
        if item.get("sha256") != sha256_bytes(data) or item.get("size") != len(data):
            changed.append(f"<external-binding:{relative}>")
    return changed


def _write_parts(path: Path, root: Path) -> Tuple[Tuple[str, ...], str]:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise SurveyError(f"write path escapes laboratory root: {path}") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise SurveyError(f"write path is not canonical inside the laboratory: {path}")
    return tuple(relative.parts[:-1]), relative.parts[-1]


def _directory_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _open_parent_fd(path: Path, root: Path, create: bool = True) -> Tuple[int, str]:
    parents, leaf = _write_parts(path, root)
    root = require_root(root)
    try:
        descriptor = os.open(root, _directory_flags())
    except OSError as exc:
        raise SurveyError(f"cannot safely open laboratory root {root}: {exc}") from exc
    try:
        info = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) != _ROOT_PINS[str(root)]:
            raise SurveyError(f"laboratory root identity changed before write: {root}")
        for part in parents:
            try:
                child = os.open(part, _directory_flags(), dir_fd=descriptor)
            except OSError as exc:
                if exc.errno != errno.ENOENT or not create:
                    raise SurveyError(
                        f"unsafe or unavailable write-path parent for {path}: {part}: {exc}"
                    ) from exc
                try:
                    os.mkdir(part, mode=0o755, dir_fd=descriptor)
                    os.fsync(descriptor)
                except FileExistsError:
                    pass
                except OSError as mkdir_exc:
                    raise SurveyError(
                        f"cannot create write-path parent for {path}: {part}: {mkdir_exc}"
                    ) from mkdir_exc
                try:
                    child = os.open(part, _directory_flags(), dir_fd=descriptor)
                except OSError as open_exc:
                    raise SurveyError(
                        f"created write-path parent is unsafe for {path}: {part}: {open_exc}"
                    ) from open_exc
            os.close(descriptor)
            descriptor = child
        return descriptor, leaf
    except Exception:
        os.close(descriptor)
        raise


def ensure_real_parent(path: Path, root: Path) -> None:
    descriptor, _leaf = _open_parent_fd(path, root, create=True)
    os.close(descriptor)


def atomic_mkdir(path: Path, root: Path, mode: int = 0o755) -> None:
    parent, leaf = _open_parent_fd(path, root, create=True)
    try:
        try:
            os.mkdir(leaf, mode=mode, dir_fd=parent)
            os.fsync(parent)
        except OSError as exc:
            raise SurveyError(f"cannot create directory {path}: {exc}") from exc
        child = os.open(leaf, _directory_flags(), dir_fd=parent)
        try:
            os.fsync(child)
        finally:
            os.close(child)
    finally:
        os.close(parent)


def _write_all(descriptor: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written <= 0:
            raise SurveyError("short write while persisting survey artifact")
        offset += written


def atomic_create(path: Path, data: bytes, root: Path, mode: int = 0o644) -> None:
    parent, leaf = _open_parent_fd(path, root, create=True)
    descriptor = -1
    temporary = ""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        for _attempt in range(128):
            temporary = f".{leaf}.survey-create-{os.getpid()}-{secrets.token_hex(8)}"
            try:
                descriptor = os.open(temporary, flags, mode, dir_fd=parent)
                break
            except FileExistsError:
                continue
            except OSError as exc:
                raise SurveyError(f"cannot stage creation for {path}: {exc}") from exc
        if descriptor < 0:
            raise SurveyError(f"cannot allocate a unique creation for {path}")
        try:
            os.fchmod(descriptor, mode)
            _write_all(descriptor, data)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            staged = os.stat(temporary, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(staged.st_mode) or stat.S_IMODE(staged.st_mode) != mode:
                raise SurveyError(f"staged creation changed before publication: {path}")
            try:
                os.link(
                    temporary,
                    leaf,
                    src_dir_fd=parent,
                    dst_dir_fd=parent,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise SurveyError(f"cannot create {path}: target already exists") from exc
            os.unlink(temporary, dir_fd=parent)
            temporary = ""
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        os.fsync(parent)
    finally:
        if temporary:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
        os.close(parent)


def append_bytes(path: Path, data: bytes, root: Path, mode: int = 0o644) -> None:
    parent, leaf = _open_parent_fd(path, root, create=True)
    try:
        try:
            info = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            info = None
        if info is None:
            existing = None
            existing_mode = mode
        else:
            flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(leaf, flags, dir_fd=parent)
            except OSError as exc:
                raise SurveyError(f"cannot read append target {path}: {exc}") from exc
            try:
                checked = os.fstat(descriptor)
                if not stat.S_ISREG(checked.st_mode) or checked.st_nlink != 1:
                    raise SurveyError(
                        f"append target must be a single-link regular file: {path}"
                    )
                chunks: List[bytes] = []
                while True:
                    chunk = os.read(descriptor, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                existing = b"".join(chunks)
                existing_mode = stat.S_IMODE(checked.st_mode)
            finally:
                os.close(descriptor)
    finally:
        os.close(parent)
    if existing is None:
        atomic_create(path, data, root, mode=existing_mode)
    else:
        atomic_replace(
            path,
            existing + data,
            root,
            mode=existing_mode,
            expected_before=existing,
        )


def _mutation_key(info: os.stat_result) -> Tuple[int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000)),
    )


def atomic_replace(
    path: Path,
    data: bytes,
    root: Path,
    mode: int = 0o644,
    *,
    expected_before: Optional[bytes] = None,
) -> None:
    parent, leaf = _open_parent_fd(path, root, create=True)
    try:
        info = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
    except OSError as exc:
        if exc.errno != errno.ENOENT:
            os.close(parent)
            raise SurveyError(f"cannot inspect replace target {path}: {exc}") from exc
        info = None
    if info is not None and (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISREG(info.st_mode)
        or (expected_before is not None and info.st_nlink != 1)
    ):
        os.close(parent)
        raise SurveyError(f"refusing to replace non-regular path: {path}")
    before_key = None if info is None else _mutation_key(info)
    descriptor = -1
    temporary = ""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    for _attempt in range(128):
        temporary = f".{leaf}.survey-{os.getpid()}-{secrets.token_hex(8)}"
        try:
            descriptor = os.open(temporary, flags, mode, dir_fd=parent)
            break
        except FileExistsError:
            continue
        except OSError as exc:
            os.close(parent)
            raise SurveyError(f"cannot stage replacement for {path}: {exc}") from exc
    if descriptor < 0:
        os.close(parent)
        raise SurveyError(f"cannot allocate a unique replacement for {path}")
    try:
        os.fchmod(descriptor, mode)
        _write_all(descriptor, data)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        try:
            current = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            current_key = _mutation_key(current)
        except OSError as exc:
            if exc.errno != errno.ENOENT:
                raise SurveyError(f"cannot revalidate replace target {path}: {exc}") from exc
            current_key = None
        if current_key != before_key:
            raise SurveyError(f"replace target changed during write: {path}")
        if expected_before is not None:
            read_flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                read_flags |= os.O_NOFOLLOW
            try:
                current_fd = os.open(leaf, read_flags, dir_fd=parent)
            except OSError as exc:
                raise SurveyError(f"cannot re-read replace target {path}: {exc}") from exc
            try:
                current_bytes = bytearray()
                while True:
                    chunk = os.read(current_fd, 1024 * 1024)
                    if not chunk:
                        break
                    current_bytes.extend(chunk)
                final_info = os.fstat(current_fd)
                final_key = _mutation_key(final_info)
            finally:
                os.close(current_fd)
            if final_key != before_key or bytes(current_bytes) != expected_before:
                raise SurveyError(f"replace target bytes changed during write: {path}")
        os.replace(temporary, leaf, src_dir_fd=parent, dst_dir_fd=parent)
        temporary = ""
        os.fsync(parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
        os.close(parent)


def package_path(root: Path, survey_id: str) -> Path:
    if not SURVEY_ID.fullmatch(survey_id):
        raise SurveyError(
            "survey id must be 1-128 ASCII letters, digits, dots, underscores, or hyphens"
        )
    return root / "runs" / "laboratory_surveys" / survey_id


def immutable_manifest_fields(manifest: Dict[str, Any]) -> Dict[str, Any]:
    return {field: manifest.get(field) for field in START_IMMUTABLE_FIELDS}


def parse_object_bytes(data: bytes, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise SurveyError(f"cannot parse {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise SurveyError(f"{label} must contain a JSON object")
    return value


def validate_start_seal(
    root: Path,
    survey_id: str,
    seal_path: Path,
    seal: Dict[str, Any],
    inventory_path: Path,
    inventory_bytes: bytes,
    inventory: Dict[str, Any],
    manifest: Dict[str, Any],
) -> None:
    try:
        _relative, checked_seal_path = canonical_binding_path(
            root, relative_name(root, seal_path)
        )
        seal_info = checked_seal_path.lstat()
    except OSError as exc:
        raise SurveyError(f"cannot inspect start seal mode: {exc}") from exc
    if not stat.S_ISREG(seal_info.st_mode) or stat.S_IMODE(seal_info.st_mode) != 0o444:
        raise SurveyError("start seal must be an immutable-mode 0444 regular file")
    if seal.get("schema_version") != 1 or seal.get("survey_id") != survey_id:
        raise SurveyError("start seal identity is invalid")
    sealed_inventory = seal.get("inventory")
    if not isinstance(sealed_inventory, dict):
        raise SurveyError("start seal inventory binding is malformed")
    expected_inventory_path = relative_name(root, inventory_path)
    if (
        sealed_inventory.get("path") != expected_inventory_path
        or sealed_inventory.get("size") != len(inventory_bytes)
        or sealed_inventory.get("sha256") != sha256_bytes(inventory_bytes)
        or sealed_inventory.get("basis_sha256") != inventory.get("inventory_sha256")
    ):
        raise SurveyError("starting inventory no longer matches its start seal")
    sealed_manifest = seal.get("manifest_immutable")
    if not isinstance(sealed_manifest, dict):
        raise SurveyError("start seal manifest binding is malformed")
    if set(sealed_manifest) != set(START_IMMUTABLE_FIELDS):
        raise SurveyError("start seal manifest field set is invalid")
    if sealed_manifest != immutable_manifest_fields(manifest):
        raise SurveyError("survey manifest immutable fields no longer match the start seal")
    if manifest.get("starting_basis_sha256") != inventory.get("inventory_sha256"):
        raise SurveyError("survey manifest starting basis disagrees with its inventory")


def authoritative_entry(root: Path, path: Path, data: bytes) -> Dict[str, Any]:
    return {
        "path": relative_name(root, path),
        "size": len(data),
        "sha256": sha256_bytes(data),
    }


def start_survey(
    root: Path,
    survey_id: str,
    mode: str,
    binding_paths: Sequence[str] = (),
) -> Dict[str, Any]:
    root = require_root(root)
    require_lab_identity(root)
    snapshot = build_snapshot(root)
    bindings = collect_bindings(root, binding_paths)
    package = package_path(root, survey_id)
    try:
        package_info = package.lstat()
    except FileNotFoundError:
        package_info = None
    except OSError as exc:
        raise SurveyError(f"cannot inspect survey packet {package}: {exc}") from exc
    recovering = package_info is not None
    if package_info is None:
        atomic_mkdir(package, root)
    elif stat.S_ISLNK(package_info.st_mode) or not stat.S_ISDIR(package_info.st_mode):
        raise SurveyError(f"survey packet path is unsafe: {package}")
    inventory_path = package / "inventory.json"
    manifest_path = package / "manifest.json"
    seal_path = package / "start_seal.json"
    if inventory_path.exists() or inventory_path.is_symlink():
        inventory_bytes = safe_read_bytes(inventory_path, "recoverable starting inventory")
        starting_snapshot = parse_object_bytes(inventory_bytes, "recoverable starting inventory")
        if (
            starting_snapshot.get("inventory_sha256") != snapshot["inventory_sha256"]
            or starting_snapshot.get("coverage") != snapshot["coverage"]
        ):
            raise SurveyError("existing partial survey inventory no longer matches current state")
    else:
        starting_snapshot = snapshot
        inventory_bytes = json_bytes(starting_snapshot)
        atomic_create(inventory_path, inventory_bytes, root)

    if manifest_path.exists() or manifest_path.is_symlink():
        manifest_bytes = safe_read_bytes(manifest_path, "recoverable survey manifest")
        manifest = parse_object_bytes(manifest_bytes, "recoverable survey manifest")
        if (
            manifest.get("schema_version") != 1
            or manifest.get("survey_id") != survey_id
            or manifest.get("mode") != mode
            or manifest.get("status") != "IN_PROGRESS"
            or manifest.get("starting_basis_sha256")
            != starting_snapshot.get("inventory_sha256")
            or manifest.get("external_bindings") != bindings
        ):
            raise SurveyError("existing survey packet is not the same recoverable start")
    else:
        manifest = {
            "schema_version": 1,
            "survey_id": survey_id,
            "mode": mode,
            "status": "IN_PROGRESS",
            "started_at_utc": utc_now(),
            "completed_at_utc": None,
            "starting_basis_sha256": starting_snapshot["inventory_sha256"],
            "finishing_basis_sha256": None,
            "coverage": starting_snapshot["coverage"],
            "changed_paths": [],
            "report": None,
            "report_sha256": None,
            "literature_delta": None,
            "literature_delta_sha256": None,
            "external_bindings": bindings,
            "integrity_note": starting_snapshot["integrity_note"],
        }
        manifest_bytes = json_bytes(manifest)
        atomic_create(manifest_path, manifest_bytes, root)
    seal = {
        "schema_version": 1,
        "survey_id": survey_id,
        "inventory": authoritative_entry(root, inventory_path, inventory_bytes),
        "manifest_immutable": immutable_manifest_fields(manifest),
    }
    seal["inventory"]["basis_sha256"] = starting_snapshot["inventory_sha256"]
    if seal_path.exists() or seal_path.is_symlink():
        existing_seal = safe_read_object(seal_path, "existing survey start seal")
        validate_start_seal(
            root,
            survey_id,
            seal_path,
            existing_seal,
            inventory_path,
            inventory_bytes,
            starting_snapshot,
            manifest,
        )
        if existing_seal != seal:
            raise SurveyError("existing survey start seal is not the same recoverable start")
    else:
        if recovering and (
            (package / "report.md").exists()
            or (package / "literature_delta.md").exists()
        ):
            raise SurveyError("unsealed partial survey unexpectedly contains synthesized output")
        atomic_create(seal_path, json_bytes(seal), root, mode=0o444)
    return {
        "status": "IN_PROGRESS",
        "survey_id": survey_id,
        "packet": relative_name(root, package),
        "inventory_sha256": starting_snapshot["inventory_sha256"],
        "next": f"write {relative_name(root, package / 'report.md')} and run finalize",
    }


def finalize_survey(root: Path, survey_id: str) -> Tuple[Dict[str, Any], int]:
    root = require_root(root)
    require_lab_identity(root)
    package = package_path(root, survey_id)
    try:
        info = package.lstat()
    except OSError as exc:
        raise SurveyError(f"cannot inspect survey packet {package}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise SurveyError(f"survey packet is not a real directory: {package}")
    inventory_path = package / "inventory.json"
    manifest_path = package / "manifest.json"
    seal_path = package / "start_seal.json"
    report_path = package / "report.md"
    inventory_bytes = safe_read_bytes(inventory_path, "starting inventory")
    inventory = parse_object_bytes(inventory_bytes, "starting inventory")
    original_manifest_bytes = safe_read_bytes(manifest_path, "survey manifest")
    manifest = parse_object_bytes(original_manifest_bytes, "survey manifest")
    seal = safe_read_object(seal_path, "survey start seal")
    if manifest.get("survey_id") != survey_id:
        raise SurveyError("survey manifest id mismatch")
    manifest_status = manifest.get("status")
    if manifest_status not in {"IN_PROGRESS", "DRIFT_DETECTED", "STABLE"}:
        raise SurveyError(f"survey is not finalizable from status {manifest.get('status')!r}")
    validate_start_seal(
        root,
        survey_id,
        seal_path,
        seal,
        inventory_path,
        inventory_bytes,
        inventory,
        manifest,
    )
    report = safe_read_bytes(report_path, "survey report")
    current = build_snapshot(root)
    starting_digest = inventory.get("inventory_sha256")
    changed = snapshot_changes(inventory, current)
    changed.extend(binding_changes(root, manifest.get("external_bindings", [])))
    stable = (
        isinstance(starting_digest, str)
        and starting_digest == current["inventory_sha256"]
        and not changed
    )
    literature_path = package / "literature_delta.md"
    literature_present = literature_path.exists() or literature_path.is_symlink()
    if manifest.get("mode") == "LOCAL_WITH_EXPLICIT_LITERATURE_DELTA" and not literature_present:
        raise SurveyError("explicit literature-delta mode requires literature_delta.md")
    if manifest.get("mode") == "LOCAL_FULL" and literature_present:
        raise SurveyError("LOCAL_FULL survey may not contain a literature delta")
    if manifest_status == "DRIFT_DETECTED" and stable:
        latest_state_path = root / "knowledge/laboratory_survey_state.json"
        if latest_state_path.exists() or latest_state_path.is_symlink():
            latest_state = safe_read_object(
                latest_state_path, "existing latest survey state"
            )
            latest_id = latest_state.get("latest_survey_id")
            if isinstance(latest_id, str) and latest_id and latest_id != survey_id:
                latest_freshness, latest_code = check_freshness(root)
                if (
                    latest_code != 0
                    or latest_freshness.get("freshness") != "FRESH"
                    or latest_freshness.get("latest_survey_id") != latest_id
                ):
                    raise SurveyError(
                        "existing latest survey state is inconsistent; refusing publication"
                    )
                raise SurveyError(
                    "refusing to replace a newer latest survey with an older drifted packet"
                )
    if manifest_status == "STABLE":
        completed = manifest.get("completed_at_utc")
        stable_manifest_errors: List[str] = []
        if not isinstance(completed, str) or not completed:
            stable_manifest_errors.append("completed timestamp")
        if manifest.get("finishing_basis_sha256") != current["inventory_sha256"]:
            stable_manifest_errors.append("finishing basis")
        if manifest.get("coverage") != current["coverage"]:
            stable_manifest_errors.append("coverage")
        if manifest.get("changed_paths") != []:
            stable_manifest_errors.append("changed path set")
        if manifest.get("report") != relative_name(root, report_path):
            stable_manifest_errors.append("report path")
        if manifest.get("report_sha256") != sha256_bytes(report):
            stable_manifest_errors.append("report digest")
        if literature_present:
            literature = safe_read_bytes(literature_path, "literature delta")
            if (
                manifest.get("literature_delta") != relative_name(root, literature_path)
                or manifest.get("literature_delta_sha256") != sha256_bytes(literature)
            ):
                stable_manifest_errors.append("literature delta binding")
        elif (
            manifest.get("literature_delta") is not None
            or manifest.get("literature_delta_sha256") is not None
        ):
            stable_manifest_errors.append("missing literature delta")
        if stable_manifest_errors:
            changed.append("<sealed-manifest:" + ",".join(stable_manifest_errors) + ">")
            stable = False
        manifest_bytes = original_manifest_bytes
    else:
        completed = utc_now()
        manifest.update(
            {
                "status": "STABLE" if stable else "DRIFT_DETECTED",
                "completed_at_utc": completed,
                "finishing_basis_sha256": current["inventory_sha256"],
                "coverage": current["coverage"],
                "changed_paths": changed,
                "report": relative_name(root, report_path),
                "report_sha256": sha256_bytes(report),
            }
        )
        if literature_present:
            literature = safe_read_bytes(literature_path, "literature delta")
            manifest["literature_delta"] = relative_name(root, literature_path)
            manifest["literature_delta_sha256"] = sha256_bytes(literature)
        else:
            manifest["literature_delta"] = None
            manifest["literature_delta_sha256"] = None
        manifest_bytes = json_bytes(manifest)
        atomic_replace(manifest_path, manifest_bytes, root)
    if not stable:
        return (
            {
                "status": "DRIFT_DETECTED",
                "survey_id": survey_id,
                "starting_basis_sha256": starting_digest,
                "finishing_basis_sha256": current["inventory_sha256"],
                "changed_paths": changed,
                "latest_overview_updated": False,
            },
            2,
        )

    overview_path = root / "knowledge" / "laboratory_overview.md"
    state_path = root / "knowledge" / "laboratory_survey_state.json"
    existing_state_bytes: Optional[bytes] = None
    if state_path.exists() or state_path.is_symlink():
        existing_state_bytes = safe_read_bytes(state_path, "existing latest survey state")
        existing_state = parse_object_bytes(
            existing_state_bytes, "existing latest survey state"
        )
        existing_id = existing_state.get("latest_survey_id")
        this_completed = manifest.get("completed_at_utc")
        existing_completed: Any = None
        if isinstance(existing_id, str) and existing_id and existing_id != survey_id:
            existing_freshness, existing_code = check_freshness(root)
            if (
                existing_freshness.get("latest_survey_id") != existing_id
                or existing_freshness.get("freshness") not in {"FRESH", "STALE"}
                or (
                    existing_code != 0
                    and existing_freshness.get("freshness") != "STALE"
                )
                or existing_freshness.get("artifact_errors")
                or existing_freshness.get("changed_authoritative_artifacts")
                or existing_freshness.get("changed_external_bindings")
            ):
                raise SurveyError(
                    "existing latest survey state is inconsistent; refusing publication"
                )
            latest_manifest = existing_state.get("latest_manifest")
            if not isinstance(latest_manifest, str):
                raise SurveyError("existing latest survey manifest path is invalid")
            _existing_relative, existing_manifest_path = canonical_binding_path(
                root, latest_manifest
            )
            existing_manifest = safe_read_object(
                existing_manifest_path, "existing latest survey manifest"
            )
            existing_completed = existing_manifest.get("completed_at_utc")
        if (
            manifest_status == "STABLE"
            and isinstance(existing_id, str)
            and existing_id
            and existing_id != survey_id
            and (
                not isinstance(existing_completed, str)
                or not isinstance(this_completed, str)
                or (this_completed, survey_id) <= (existing_completed, existing_id)
            )
        ):
            raise SurveyError(
                "refusing to replace a newer latest survey with an older stable packet"
            )
    seal_bytes = safe_read_bytes(seal_path, "survey start seal")
    artifacts = {
        "report": authoritative_entry(root, report_path, report),
        "manifest": authoritative_entry(root, manifest_path, manifest_bytes),
        "inventory": authoritative_entry(root, inventory_path, inventory_bytes),
        "start_seal": authoritative_entry(root, seal_path, seal_bytes),
    }
    if manifest.get("literature_delta"):
        literature_path = root / manifest["literature_delta"]
        literature = safe_read_bytes(literature_path, "literature delta")
        artifacts["literature_delta"] = authoritative_entry(
            root, literature_path, literature
        )
    state = {
        "schema_version": 1,
        "latest_survey_id": survey_id,
        "latest_report": relative_name(root, report_path),
        "latest_manifest": relative_name(root, manifest_path),
        "latest_inventory": relative_name(root, inventory_path),
        "latest_start_seal": relative_name(root, seal_path),
        "basis_sha256": current["inventory_sha256"],
        "report_sha256": sha256_bytes(report),
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "inventory_sha256": sha256_bytes(inventory_bytes),
        "start_seal_sha256": sha256_bytes(seal_bytes),
        "completed_at_utc": completed,
        "mode": manifest.get("mode"),
        "freshness": "FRESH",
        "coverage": current["coverage"],
        "external_bindings": manifest.get("external_bindings", []),
        "authoritative_artifacts": artifacts,
    }
    overview_before = (
        safe_read_bytes(overview_path, "existing laboratory overview")
        if overview_path.exists() or overview_path.is_symlink()
        else None
    )
    atomic_replace(
        overview_path, report, root, expected_before=overview_before
    )
    atomic_replace(
        state_path,
        json_bytes(state),
        root,
        expected_before=existing_state_bytes,
    )
    post_publication, post_code = check_freshness(root)
    if (
        post_code != 0
        or post_publication.get("freshness") != "FRESH"
        or post_publication.get("latest_survey_id") != survey_id
    ):
        return (
            {
                "status": "STALE_AFTER_PUBLICATION",
                "survey_id": survey_id,
                "freshness": post_publication,
                "latest_overview_updated": True,
            },
            2,
        )
    return (
        {
            "status": "FRESH",
            "survey_id": survey_id,
            "basis_sha256": current["inventory_sha256"],
            "report_sha256": sha256_bytes(report),
            "latest_overview_updated": True,
        },
        0,
    )


def check_freshness(root: Path) -> Tuple[Dict[str, Any], int]:
    root = require_root(root)
    state_path = root / "knowledge" / "laboratory_survey_state.json"
    try:
        state = safe_read_object(state_path, "survey state")
    except SurveyError as exc:
        if not state_path.exists():
            return ({"freshness": "NONE", "reason": "survey state is absent"}, 3)
        raise exc
    basis = state.get("basis_sha256")
    if not isinstance(basis, str) or not basis:
        return ({"freshness": "NONE", "reason": "no stable survey has been saved"}, 3)

    artifact_errors: List[str] = []
    changed_artifacts: List[str] = []
    artifact_bytes: Dict[str, bytes] = {}
    if state.get("schema_version") != 1:
        artifact_errors.append("saved survey state schema is invalid")
    if state.get("mode") not in {
        "LOCAL_FULL",
        "LOCAL_WITH_EXPLICIT_LITERATURE_DELTA",
    }:
        artifact_errors.append("saved survey state mode is invalid")
    if not isinstance(state.get("completed_at_utc"), str) or not state["completed_at_utc"]:
        artifact_errors.append("saved survey completion timestamp is invalid")
    if state.get("coverage") not in {"COMPLETE_WITHIN_DECLARED_SCOPE", "PARTIAL"}:
        artifact_errors.append("saved survey coverage is invalid")
    survey_id = state.get("latest_survey_id")
    if not isinstance(survey_id, str) or not SURVEY_ID.fullmatch(survey_id):
        artifact_errors.append("latest survey id is invalid")
        expected_paths: Dict[str, str] = {}
    else:
        packet = package_path(root, survey_id)
        expected_paths = {
            "report": relative_name(root, packet / "report.md"),
            "manifest": relative_name(root, packet / "manifest.json"),
            "inventory": relative_name(root, packet / "inventory.json"),
            "start_seal": relative_name(root, packet / "start_seal.json"),
        }
    artifacts = state.get("authoritative_artifacts")
    if not isinstance(artifacts, dict):
        artifact_errors.append("saved survey state has no sealed authoritative artifacts")
        artifacts = {}
    for name in ("report", "manifest", "inventory", "start_seal"):
        entry = artifacts.get(name)
        if not isinstance(entry, dict):
            artifact_errors.append(f"authoritative artifact {name} is absent or malformed")
            continue
        raw_path = entry.get("path")
        expected = expected_paths.get(name)
        if not isinstance(raw_path, str) or raw_path != expected:
            artifact_errors.append(f"authoritative artifact {name} path is invalid")
            continue
        try:
            _relative, path = canonical_binding_path(root, raw_path)
            data = safe_read_bytes(path, f"authoritative {name}")
        except SurveyError:
            changed_artifacts.append(name)
            continue
        artifact_bytes[name] = data
        if entry.get("size") != len(data) or entry.get("sha256") != sha256_bytes(data):
            changed_artifacts.append(name)

    literature_entry = artifacts.get("literature_delta")
    if literature_entry is not None:
        if not isinstance(literature_entry, dict):
            artifact_errors.append("authoritative literature delta is malformed")
        else:
            raw_path = literature_entry.get("path")
            expected_literature = (
                relative_name(root, package_path(root, survey_id) / "literature_delta.md")
                if isinstance(survey_id, str) and SURVEY_ID.fullmatch(survey_id)
                else None
            )
            if not isinstance(raw_path, str) or raw_path != expected_literature:
                artifact_errors.append("authoritative literature delta path is invalid")
            else:
                try:
                    _relative, path = canonical_binding_path(root, raw_path)
                    data = safe_read_bytes(path, "authoritative literature delta")
                except SurveyError:
                    changed_artifacts.append("literature_delta")
                else:
                    artifact_bytes["literature_delta"] = data
                    if (
                        literature_entry.get("size") != len(data)
                        or literature_entry.get("sha256") != sha256_bytes(data)
                    ):
                        changed_artifacts.append("literature_delta")

    manifest: Optional[Dict[str, Any]] = None
    inventory: Optional[Dict[str, Any]] = None
    seal: Optional[Dict[str, Any]] = None
    for name, label in (
        ("manifest", "saved survey manifest"),
        ("inventory", "saved survey inventory"),
        ("start_seal", "saved survey start seal"),
    ):
        data = artifact_bytes.get(name)
        if data is None:
            continue
        try:
            parsed = parse_object_bytes(data, label)
        except SurveyError as exc:
            artifact_errors.append(str(exc))
            continue
        if name == "manifest":
            manifest = parsed
        elif name == "inventory":
            inventory = parsed
        else:
            seal = parsed

    if state.get("freshness") != "FRESH":
        artifact_errors.append("saved survey state is not marked FRESH")
    if manifest is not None:
        report_data = artifact_bytes.get("report")
        if manifest.get("schema_version") != 1:
            artifact_errors.append("saved survey manifest schema is invalid")
        if manifest.get("status") != "STABLE":
            artifact_errors.append("saved survey manifest is not STABLE")
        if manifest.get("survey_id") != survey_id:
            artifact_errors.append("saved survey manifest id mismatch")
        if manifest.get("finishing_basis_sha256") != basis:
            artifact_errors.append("saved survey finishing basis mismatch")
        if manifest.get("report") != expected_paths.get("report"):
            artifact_errors.append("saved survey report path mismatch")
        if report_data is None or manifest.get("report_sha256") != sha256_bytes(report_data):
            artifact_errors.append("saved survey report digest mismatch")
        if manifest.get("external_bindings") != state.get("external_bindings"):
            artifact_errors.append("saved external bindings disagree with the manifest")
        if manifest.get("mode") != state.get("mode"):
            artifact_errors.append("saved survey mode disagrees with the manifest")
        if manifest.get("completed_at_utc") != state.get("completed_at_utc"):
            artifact_errors.append("saved survey completion time disagrees with the manifest")
        if manifest.get("coverage") != state.get("coverage"):
            artifact_errors.append("saved survey coverage disagrees with the manifest")
        manifest_literature = manifest.get("literature_delta")
        if manifest_literature is None:
            if literature_entry is not None:
                artifact_errors.append("state records an unexpected literature delta")
        else:
            literature_data = artifact_bytes.get("literature_delta")
            if (
                manifest_literature
                != (
                    literature_entry.get("path")
                    if isinstance(literature_entry, dict)
                    else None
                )
                or literature_data is None
                or manifest.get("literature_delta_sha256")
                != sha256_bytes(literature_data)
            ):
                artifact_errors.append("saved literature delta binding mismatch")
    if inventory is not None:
        if inventory.get("schema_version") != 1:
            artifact_errors.append("saved inventory schema is invalid")
        if inventory.get("inventory_sha256") != basis:
            artifact_errors.append("saved inventory basis mismatch")
        if manifest is not None and manifest.get("starting_basis_sha256") != basis:
            artifact_errors.append("saved manifest starting basis mismatch")
    if seal is not None and inventory is not None and manifest is not None:
        try:
            validate_start_seal(
                root,
                survey_id,
                root / expected_paths["start_seal"],
                seal,
                root / expected_paths["inventory"],
                artifact_bytes["inventory"],
                inventory,
                manifest,
            )
        except (KeyError, SurveyError) as exc:
            artifact_errors.append(f"start seal validation failed: {exc}")

    top_level_bindings = (
        ("latest_report", "report", "report_sha256"),
        ("latest_manifest", "manifest", "manifest_sha256"),
        ("latest_inventory", "inventory", "inventory_sha256"),
        ("latest_start_seal", "start_seal", "start_seal_sha256"),
    )
    for path_key, artifact_name, digest_key in top_level_bindings:
        entry = artifacts.get(artifact_name)
        if not isinstance(entry, dict):
            continue
        if state.get(path_key) != entry.get("path"):
            artifact_errors.append(f"state {path_key} disagrees with sealed artifact")
        if state.get(digest_key) != entry.get("sha256"):
            artifact_errors.append(f"state {digest_key} disagrees with sealed artifact")

    current = build_snapshot(root)
    if state.get("coverage") != current.get("coverage"):
        artifact_errors.append("saved survey coverage disagrees with current coverage")
    report_data = artifact_bytes.get("report")
    try:
        overview_data = safe_read_bytes(
            root / "knowledge/laboratory_overview.md", "latest laboratory overview"
        )
    except SurveyError:
        changed_artifacts.append("overview")
    else:
        if report_data is None or overview_data != report_data:
            changed_artifacts.append("overview")
    binding_source: Any = (
        manifest.get("external_bindings", []) if manifest is not None else []
    )
    try:
        changed_bindings = binding_changes(root, binding_source)
    except SurveyError as exc:
        changed_bindings = []
        artifact_errors.append(f"external binding validation failed: {exc}")
    freshness = (
        "FRESH"
        if (
            current["inventory_sha256"] == basis
            and not changed_bindings
            and not changed_artifacts
            and not artifact_errors
        )
        else "STALE"
    )
    result = {
        "freshness": freshness,
        "latest_survey_id": state.get("latest_survey_id"),
        "saved_basis_sha256": basis,
        "current_basis_sha256": current["inventory_sha256"],
        "coverage": current["coverage"],
        "changed_external_bindings": changed_bindings,
        "changed_authoritative_artifacts": sorted(set(changed_artifacts)),
        "artifact_errors": sorted(set(artifact_errors)),
    }
    return result, 0 if freshness == "FRESH" else 2


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def print_result(result: Dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if "inventory_sha256" in result and "files" in result:
        print("Laboratory survey snapshot")
        print(f"Status: {result['coverage']}")
        print(f"Files: {len(result['files'])}")
        print(f"Skipped: {len(result['skipped'])}")
        print(f"Basis SHA-256: {result['inventory_sha256']}")
        print(result["integrity_note"])
        return
    for key, value in result.items():
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value) if value else "none"
        print(f"{key}: {value}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Build and freshness-check whole-laboratory survey snapshots."
    )
    result.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    commands = result.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser("snapshot", help="build a read-only evidence inventory")
    snapshot.add_argument("--json", action="store_true")
    start = commands.add_parser("start", help="start an explicitly persisted survey packet")
    start.add_argument("--survey-id", required=True)
    start.add_argument(
        "--mode",
        choices=("LOCAL_FULL", "LOCAL_WITH_EXPLICIT_LITERATURE_DELTA"),
        default="LOCAL_FULL",
    )
    start.add_argument(
        "--bind",
        action="append",
        default=[],
        metavar="RELATIVE_PATH",
        help="bind an excluded immutable local artifact; repeat as needed",
    )
    start.add_argument("--json", action="store_true")
    finalize = commands.add_parser("finalize", help="freshness-check and finalize a survey")
    finalize.add_argument("--survey-id", required=True)
    finalize.add_argument("--json", action="store_true")
    check = commands.add_parser("check", help="check the latest saved survey freshness")
    check.add_argument("--json", action="store_true")
    return result


def run(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    root = require_root(args.root)
    if args.command == "snapshot":
        value = build_snapshot(root)
        print_result(value, args.json)
        return 0
    if args.command == "start":
        value = start_survey(root, args.survey_id, args.mode, args.bind)
        print_result(value, args.json)
        return 0
    if args.command == "finalize":
        value, code = finalize_survey(root, args.survey_id)
        print_result(value, args.json)
        return code
    value, code = check_freshness(root)
    print_result(value, args.json)
    return code


def main() -> int:
    try:
        return run()
    except SurveyError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
