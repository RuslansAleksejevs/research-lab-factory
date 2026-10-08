#!/usr/bin/env python3
"""Strict, read-only validation for Lean Room v2 source snapshots.

This Phase-A validator does not execute Lean, Lake, package configuration, or
dependency code.  It accepts exactly the source-only snapshot format emitted
by ``import_lean_dependency_snapshot.py`` and fails closed on every unknown
manifest field or unsupported Lake manifest version.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_VALIDATION = 5

SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOT_RECORD_TYPE = "lean_dependency_snapshot_v2"
PROTOCOL_VERSION = "lean-room-v2-source-snapshot-phase-a"
TREE_PROFILE = "lean-room-dependency-tree-v2-files-gitlink-omissions-sha256"

IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
PACKAGE_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,119}\Z")
REVISION_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
TOOLCHAIN_RE = re.compile(
    r"(?:leanprover/lean4:)?v\d+\.\d+\.\d+(?:-(?:rc|beta)\d+)?\Z"
)

LAKE_BASE_TOP_LEVEL_KEYS = frozenset(
    {"version", "packagesDir", "packages", "name", "lakeDir"}
)
LAKE_PACKAGE_KEYS = frozenset(
    {
        "url",
        "type",
        "subDir",
        "scope",
        "rev",
        "name",
        "manifestFile",
        "inputRev",
        "inherited",
        "configFile",
    }
)
SNAPSHOT_KEYS = frozenset(
    {
        "schema_version",
        "record_type",
        "protocol_version",
        "snapshot_id",
        "created_at",
        "created_by",
        "source_workspace_recorded",
        "lake_manifest",
        "dependency_graph_sha256",
        "dependency_closure_sha256",
        "policies",
        "packages",
    }
)
SNAPSHOT_LAKE_KEYS = frozenset(
    {"artifact", "sha256", "version", "root_package_name", "fixed_toolchain"}
)
SNAPSHOT_PACKAGE_KEYS = frozenset(
    {
        "name",
        "safe_directory",
        "source_kind",
        "source_url",
        "resolved_revision",
        "git_tree_oid",
        "input_revision",
        "scope",
        "subdir",
        "config_file",
        "config_sha256",
        "manifest_file",
        "manifest_sha256",
        "source_inventory",
        "source_inventory_sha256",
        "source_tree_sha256",
        "source_tree_profile",
        "gitlink_omissions",
        "gitlink_omissions_sha256",
        "symlink_normalizations",
        "symlink_normalizations_sha256",
        "toolchain",
        "executable_config",
        "review_required",
    }
)
TOOLCHAIN_BINDING_KEYS = frozenset({"artifact", "content", "sha256"})

SOURCE_ONLY_POLICIES: dict[str, Any] = {
    "source_only": True,
    "git_metadata_present": False,
    "precompiled_artifacts_present": False,
    "cache_mode": "none",
    "network_allowed_during_certificate_build": False,
    "override_mode": "generated_path_overrides",
    "package_configuration_execution_review_required": True,
    "tracked_internal_symlinks_materialized_as_regular_files": True,
    "uninitialized_gitlinks_materialized_as_unavailable_empty_directories": True,
}

SYMLINK_NORMALIZATION_KEYS = frozenset(
    {
        "source_path",
        "link_text",
        "resolved_tracked_path",
        "target_sha256",
        "materialized_mode",
    }
)

GITLINK_OMISSION_KEYS = frozenset(
    {"path", "commit_oid", "materialized_as", "source_available"}
)

PRECOMPILED_SUFFIXES = frozenset(
    {
        ".olean",
        ".ilean",
        ".o",
        ".obj",
        ".a",
        ".so",
        ".dylib",
        ".dll",
        ".bc",
        ".pyc",
        ".class",
        ".jar",
        ".wasm",
    }
)
LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1\n"
EXECUTABLE_MAGICS = (
    b"\x7fELF",
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
)


class SnapshotValidationError(RuntimeError):
    """A stable fail-closed validation error."""


def _require_exact_keys(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise SnapshotValidationError(
            f"{label} has noncanonical fields; missing={missing}, extra={extra}"
        )


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise SnapshotValidationError(f"missing regular {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotValidationError(f"cannot parse {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise SnapshotValidationError(f"{label} must be a JSON object")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def pretty_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
    except OSError as exc:
        raise SnapshotValidationError(f"cannot hash regular file {path}: {exc}") from exc
    return digest.hexdigest()


def _safe_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value):
        raise SnapshotValidationError(f"invalid {label}: {value!r}")
    return value


def _safe_package_name(value: Any, label: str = "package name") -> str:
    if not isinstance(value, str) or not PACKAGE_NAME_RE.fullmatch(value):
        raise SnapshotValidationError(f"invalid {label}: {value!r}")
    return value


def _safe_relative(value: Any, label: str, allow_null: bool = False) -> str | None:
    if value is None and allow_null:
        return None
    if not isinstance(value, str) or not value:
        raise SnapshotValidationError(f"invalid {label}: {value!r}")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise SnapshotValidationError(f"control character is forbidden in {label}: {value!r}")
    if "\\" in value:
        raise SnapshotValidationError(f"backslash is forbidden in {label}: {value!r}")
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise SnapshotValidationError(f"noncanonical {label}: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise SnapshotValidationError(f"unsafe {label}: {value!r}")
    return path.as_posix()


def _collision_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _check_collision(seen: dict[str, str], value: str, label: str) -> None:
    key = _collision_key(value)
    prior = seen.get(key)
    if prior is not None and prior != value:
        raise SnapshotValidationError(
            f"case/Unicode-normalization collision in {label}: {prior!r} vs {value!r}"
        )
    seen[key] = value


def resolve_relative_symlink_target(source_path: str, link_text: str) -> str:
    """Resolve one UTF-8 POSIX link lexically, rejecting package escape."""

    source = _safe_relative(source_path, "symlink source path")
    if (
        not isinstance(link_text, str)
        or not link_text
        or link_text.startswith("/")
        or "\\" in link_text
        or any(ord(char) < 32 or ord(char) == 127 for char in link_text)
    ):
        raise SnapshotValidationError(
            f"symlink {source} has an unsafe non-relative target: {link_text!r}"
        )
    parts = list(PurePosixPath(source).parent.parts)
    raw_parts = link_text.split("/")
    if any(part == "" for part in raw_parts):
        raise SnapshotValidationError(
            f"symlink {source} has a noncanonical target: {link_text!r}"
        )
    for part in raw_parts:
        if part == ".":
            continue
        if part == "..":
            if not parts:
                raise SnapshotValidationError(
                    f"symlink target escapes dependency package: {source} -> {link_text}"
                )
            parts.pop()
            continue
        parts.append(part)
    if not parts:
        raise SnapshotValidationError(
            f"symlink target resolves to package root, not a tracked file: {source}"
        )
    resolved = PurePosixPath(*parts).as_posix()
    _safe_relative(resolved, "resolved symlink target")
    return resolved


def resolve_symlink_chain(
    source_path: str,
    link_text_by_source: Mapping[str, str],
    *,
    maximum_hops: int = 64,
) -> str:
    """Resolve a bounded internal link chain and reject cycles."""

    current = _safe_relative(source_path, "symlink chain source")
    visited: set[str] = set()
    for _hop in range(maximum_hops):
        if current in visited:
            raise SnapshotValidationError(f"symlink loop detected at {current}")
        visited.add(current)
        link_text = link_text_by_source.get(current)
        if link_text is None:
            return current
        current = resolve_relative_symlink_target(current, link_text)
    raise SnapshotValidationError(
        f"symlink chain exceeds the {maximum_hops}-hop safety bound: {source_path}"
    )


def _is_precompiled(path: Path) -> bool:
    if path.suffix.casefold() in PRECOMPILED_SUFFIXES:
        return True
    try:
        with path.open("rb") as stream:
            prefix = stream.read(64)
    except OSError as exc:
        raise SnapshotValidationError(f"cannot inspect source file {path}: {exc}") from exc
    if any(prefix.startswith(magic) for magic in EXECUTABLE_MAGICS):
        return True
    # A two-byte ``MZ`` prefix alone occurs in ordinary text. Only classify a
    # PE/COFF input when the DOS header contains a plausible PE offset and the
    # corresponding signature is present.
    if prefix.startswith(b"MZ") and len(prefix) >= 64:
        pe_offset = int.from_bytes(prefix[0x3C:0x40], "little")
        if 64 <= pe_offset <= 16 * 1024 * 1024:
            try:
                with path.open("rb") as stream:
                    stream.seek(pe_offset)
                    return stream.read(4) == b"PE\0\0"
            except OSError as exc:
                raise SnapshotValidationError(
                    f"cannot inspect PE signature in source file {path}: {exc}"
                ) from exc
    return False


def _is_lfs_pointer(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            first_line = stream.read(256).splitlines()[0]
            return first_line == LFS_POINTER_PREFIX.rstrip(b"\n")
    except IndexError:
        return False
    except OSError as exc:
        raise SnapshotValidationError(f"cannot inspect source file {path}: {exc}") from exc


def _scan_tree(
    root: Path,
    *,
    allow_root_git: bool = False,
    allow_root_lake: bool = False,
    collect_symlinks: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[str]]:
    """Inventory a source tree without following links.

    The import-only metadata exceptions are the source checkout's top-level
    regular ``.git`` and ``.lake`` directories. They are ignored only while
    importing and are never copied into a snapshot. Snapshot validation leaves
    both switches false. ``collect_symlinks`` is importer-only: published
    snapshots call the strict wrapper and therefore reject every link.
    """

    if root.is_symlink() or not root.is_dir():
        raise SnapshotValidationError(f"expected regular source directory: {root}")
    files: list[dict[str, Any]] = []
    symlinks: list[dict[str, str]] = []
    empty_directories: list[str] = []
    seen: dict[str, str] = {}
    pending: list[tuple[Path, PurePosixPath]] = [(root, PurePosixPath())]
    while pending:
        directory, relative_directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name.encode("utf-8"))
        except (OSError, UnicodeEncodeError) as exc:
            raise SnapshotValidationError(f"cannot scan source directory {directory}: {exc}") from exc
        if relative_directory.parts and not entries:
            empty_directories.append(relative_directory.as_posix())
        for entry in entries:
            try:
                entry.name.encode("utf-8", errors="strict")
            except UnicodeEncodeError as exc:
                raise SnapshotValidationError(f"non-UTF-8 source path: {entry.path!r}") from exc
            relative = relative_directory / entry.name
            rendered = relative.as_posix()
            _check_collision(seen, rendered, "source paths")
            if entry.name in {".git", ".lake"}:
                allowed_root_metadata = (
                    not relative_directory.parts
                    and (
                        (entry.name == ".git" and allow_root_git)
                        or (entry.name == ".lake" and allow_root_lake)
                    )
                )
                if allowed_root_metadata:
                    metadata = entry.stat(follow_symlinks=False)
                    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                        raise SnapshotValidationError(
                            f"source checkout {entry.name} must be a regular directory"
                        )
                    continue
                raise SnapshotValidationError(f"forbidden {entry.name} metadata/cache path: {rendered}")
            if entry.name == ".gitmodules":
                raise SnapshotValidationError(f"Git submodules are unsupported in Phase A: {rendered}")
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise SnapshotValidationError(f"cannot stat source path {entry.path}: {exc}") from exc
            mode = metadata.st_mode
            if stat.S_ISLNK(mode):
                if not collect_symlinks:
                    raise SnapshotValidationError(
                        f"symlink is forbidden in dependency snapshot: {rendered}"
                    )
                try:
                    link_text = os.readlink(entry.path)
                    link_text.encode("utf-8", errors="strict")
                except (OSError, UnicodeEncodeError) as exc:
                    raise SnapshotValidationError(
                        f"symlink target is not readable UTF-8: {rendered}"
                    ) from exc
                symlinks.append({"path": rendered, "link_text": link_text})
                continue
            if stat.S_ISDIR(mode):
                pending.append((Path(entry.path), relative))
                continue
            if not stat.S_ISREG(mode):
                raise SnapshotValidationError(f"special file is forbidden in dependency source: {rendered}")
            if metadata.st_nlink != 1:
                raise SnapshotValidationError(f"hard-linked file is forbidden in dependency source: {rendered}")
            path = Path(entry.path)
            if _is_precompiled(path):
                raise SnapshotValidationError(
                    f"precompiled/executable binary artifact is forbidden: {rendered}"
                )
            if _is_lfs_pointer(path):
                raise SnapshotValidationError(f"Git LFS pointer is unsupported in Phase A: {rendered}")
            files.append(
                {
                    "path": rendered,
                    "mode": format(stat.S_IMODE(mode), "04o"),
                    "size": metadata.st_size,
                    "sha256": sha256_file(path),
                }
            )
    files.sort(key=lambda item: item["path"].encode("utf-8"))
    symlinks.sort(key=lambda item: item["path"].encode("utf-8"))
    empty_directories.sort(key=lambda item: item.encode("utf-8"))
    return files, symlinks, empty_directories


def scan_source_tree(
    root: Path,
    *,
    allow_root_git: bool = False,
    allow_root_lake: bool = False,
) -> list[dict[str, Any]]:
    """Strict regular-file inventory used for every published snapshot."""

    files, symlinks, _empty_directories = _scan_tree(
        root,
        allow_root_git=allow_root_git,
        allow_root_lake=allow_root_lake,
        collect_symlinks=False,
    )
    if symlinks:  # pragma: no cover - strict scan raises before collecting
        raise SnapshotValidationError("published dependency snapshot contains a symlink")
    return files


def scan_import_source_tree(
    root: Path,
    *,
    allow_root_git: bool = True,
    allow_root_lake: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Importer-only inventory that records links for guarded normalization."""

    files, symlinks, _empty_directories = _scan_tree(
        root,
        allow_root_git=allow_root_git,
        allow_root_lake=allow_root_lake,
        collect_symlinks=True,
    )
    return files, symlinks


def scan_import_source_layout(
    root: Path,
    *,
    allow_root_git: bool = True,
    allow_root_lake: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[str]]:
    """Importer-only layout including candidate empty gitlink directories."""

    return _scan_tree(
        root,
        allow_root_git=allow_root_git,
        allow_root_lake=allow_root_lake,
        collect_symlinks=True,
    )


def scan_empty_directories(root: Path) -> list[str]:
    """Return every empty real directory in an otherwise strict source tree."""

    _files, _symlinks, empty_directories = _scan_tree(root, collect_symlinks=False)
    return empty_directories


def _require_empty_real_directory(root: Path, relative: str, label: str) -> Path:
    path = root.joinpath(*PurePosixPath(relative).parts)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SnapshotValidationError(f"missing {label}: {relative}") from exc
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise SnapshotValidationError(f"{label} is not a real directory: {relative}")
    try:
        entries = list(os.scandir(path))
    except OSError as exc:
        raise SnapshotValidationError(f"cannot inspect {label} {relative}: {exc}") from exc
    if entries:
        raise SnapshotValidationError(f"{label} is not empty: {relative}")
    return path


def dependency_tree_sha256(
    root: Path,
    inventory: Sequence[Mapping[str, Any]],
    gitlink_omissions: Sequence[Mapping[str, Any]] = (),
) -> str:
    """Hash source files plus explicit unavailable-gitlink directory markers."""

    digest = hashlib.sha256()
    digest.update(b"lean-room-dependency-tree-v2-files-gitlink-omissions\0")
    for entry in inventory:
        relative = _safe_relative(entry.get("path"), "inventory path")
        mode_text = entry.get("mode")
        if not isinstance(mode_text, str) or not re.fullmatch(r"0[0-7]{3}", mode_text):
            raise SnapshotValidationError(f"invalid inventory mode for {relative}: {mode_text!r}")
        path = root.joinpath(*PurePosixPath(relative).parts)
        if path.is_symlink() or not path.is_file():
            raise SnapshotValidationError(f"inventory path is not a regular file: {relative}")
        content = path.read_bytes()
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(int(mode_text, 8).to_bytes(4, "big"))
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    omission_paths: list[str] = []
    for omission in gitlink_omissions:
        if not isinstance(omission, Mapping):
            raise SnapshotValidationError("malformed gitlink omission in dependency tree")
        _require_exact_keys(omission, GITLINK_OMISSION_KEYS, "gitlink omission")
        relative = _safe_relative(omission.get("path"), "gitlink omission path")
        commit_oid = omission.get("commit_oid")
        if not isinstance(commit_oid, str) or not REVISION_RE.fullmatch(commit_oid):
            raise SnapshotValidationError(f"invalid gitlink commit OID for {relative}")
        if omission.get("materialized_as") != "empty_directory":
            raise SnapshotValidationError(f"invalid gitlink materialization for {relative}")
        if omission.get("source_available") is not False:
            raise SnapshotValidationError(f"gitlink source must remain unavailable: {relative}")
        _require_empty_real_directory(root, relative, "materialized gitlink omission")
        omission_paths.append(relative)
        encoded = canonical_json_bytes(dict(omission))
        digest.update(b"gitlink-omission\0")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    if omission_paths != sorted(omission_paths, key=lambda item: item.encode("utf-8")):
        raise SnapshotValidationError("gitlink omissions are not sorted for dependency tree")
    if len(omission_paths) != len(set(omission_paths)):
        raise SnapshotValidationError("duplicate gitlink omission in dependency tree")
    return digest.hexdigest()


def _normalized_lake_package(package: Mapping[str, Any]) -> dict[str, Any]:
    return {key: package[key] for key in sorted(LAKE_PACKAGE_KEYS)}


def dependency_graph_sha256(manifest: Mapping[str, Any]) -> str:
    packages = sorted(
        (_normalized_lake_package(item) for item in manifest["packages"]),
        key=lambda item: item["name"],
    )
    graph = {
        "version": manifest["version"],
        "packagesDir": manifest["packagesDir"],
        "lakeDir": manifest["lakeDir"],
        "name": manifest["name"],
        "fixedToolchain": manifest.get("fixedToolchain"),
        "packages": packages,
    }
    return sha256_bytes(canonical_json_bytes(graph))


def dependency_closure_sha256(
    graph_sha256: str, packages: Sequence[Mapping[str, Any]]
) -> str:
    closure_packages = []
    for package in sorted(packages, key=lambda item: str(item.get("name"))):
        toolchain = package.get("toolchain")
        closure_packages.append(
            {
                "name": package.get("name"),
                "resolved_revision": package.get("resolved_revision"),
                "git_tree_oid": package.get("git_tree_oid"),
                "source_tree_sha256": package.get("source_tree_sha256"),
                "source_inventory_sha256": package.get("source_inventory_sha256"),
                "config_sha256": package.get("config_sha256"),
                "manifest_sha256": package.get("manifest_sha256"),
                "gitlink_omissions_sha256": package.get(
                    "gitlink_omissions_sha256"
                ),
                "symlink_normalizations_sha256": package.get(
                    "symlink_normalizations_sha256"
                ),
                "toolchain_sha256": (
                    toolchain.get("sha256") if isinstance(toolchain, dict) else None
                ),
            }
        )
    return sha256_bytes(
        canonical_json_bytes(
            {
                "dependency_graph_sha256": graph_sha256,
                "packages": closure_packages,
            }
        )
    )


def validate_lake_manifest(path: Path) -> dict[str, Any]:
    manifest = _read_json_object(path, "Lake manifest")
    version = manifest.get("version")
    if version == "1.1.0":
        _require_exact_keys(manifest, LAKE_BASE_TOP_LEVEL_KEYS, "Lake 1.1.0 manifest")
    elif version == "1.2.0":
        actual = frozenset(manifest)
        allowed = {
            LAKE_BASE_TOP_LEVEL_KEYS,
            LAKE_BASE_TOP_LEVEL_KEYS | {"fixedToolchain"},
        }
        if actual not in allowed:
            raise SnapshotValidationError(
                "Lake 1.2.0 manifest has noncanonical fields; "
                f"actual={sorted(actual)}"
            )
        if "fixedToolchain" in manifest and not isinstance(
            manifest["fixedToolchain"], bool
        ):
            raise SnapshotValidationError(
                "Lake 1.2.0 fixedToolchain must be Boolean when present"
            )
    else:
        raise SnapshotValidationError(
            "only Lake manifest versions 1.1.0 and 1.2.0 are supported"
        )
    if manifest.get("packagesDir") != ".lake/packages":
        raise SnapshotValidationError("Lake packagesDir must be exactly .lake/packages")
    if manifest.get("lakeDir") != ".lake":
        raise SnapshotValidationError("Lake lakeDir must be exactly .lake")
    _safe_package_name(manifest.get("name"), "root package name")
    packages = manifest.get("packages")
    if not isinstance(packages, list) or not packages:
        raise SnapshotValidationError("dependency snapshot requires a nonempty Lake package list")
    seen_names: dict[str, str] = {}
    for index, package in enumerate(packages):
        if not isinstance(package, dict):
            raise SnapshotValidationError(f"Lake package[{index}] must be an object")
        _require_exact_keys(package, LAKE_PACKAGE_KEYS, f"Lake package[{index}]")
        name = _safe_package_name(package.get("name"), f"Lake package[{index}] name")
        _check_collision(seen_names, name, "Lake package names")
        if package.get("type") != "git":
            raise SnapshotValidationError(f"Lake package {name} must have type=git")
        url = package.get("url")
        if not isinstance(url, str) or not url.startswith("https://") or any(
            char in url for char in "\r\n\0"
        ):
            raise SnapshotValidationError(f"Lake package {name} requires a canonical HTTPS URL")
        revision = package.get("rev")
        if not isinstance(revision, str) or not REVISION_RE.fullmatch(revision):
            raise SnapshotValidationError(f"Lake package {name} revision must be an exact Git OID")
        _safe_relative(package.get("subDir"), f"Lake package {name} subDir", allow_null=True)
        scope = package.get("scope")
        # Lake serializes an unscoped direct dependency as the empty string.
        # Nonempty scopes must still use the portable package-name alphabet.
        if not isinstance(scope, str) or (
            scope != "" and not PACKAGE_NAME_RE.fullmatch(scope)
        ):
            raise SnapshotValidationError(f"invalid Lake package scope for {name}")
        input_revision = package.get("inputRev")
        if input_revision is not None and (
            not isinstance(input_revision, str)
            or not input_revision
            or any(char in input_revision for char in "\r\n\0")
        ):
            raise SnapshotValidationError(f"invalid inputRev for Lake package {name}")
        if not isinstance(package.get("inherited"), bool):
            raise SnapshotValidationError(f"Lake package {name} inherited must be Boolean")
        if package.get("manifestFile") != "lake-manifest.json":
            raise SnapshotValidationError(
                f"Lake package {name} manifestFile must be lake-manifest.json"
            )
        if package.get("configFile") not in {"lakefile.toml", "lakefile.lean"}:
            raise SnapshotValidationError(f"unsupported configFile for Lake package {name}")
    return manifest


def _regular_bound_file(root: Path, relative: Any, label: str) -> Path:
    rendered = _safe_relative(relative, label)
    path = root.joinpath(*PurePosixPath(rendered).parts)
    if path.is_symlink() or not path.is_file():
        raise SnapshotValidationError(f"missing regular {label}: {rendered}")
    return path


def _validate_toolchain_binding(
    package_root: Path, value: Any, package_name: str
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SnapshotValidationError(f"toolchain binding for {package_name} must be null or object")
    _require_exact_keys(value, TOOLCHAIN_BINDING_KEYS, f"toolchain binding for {package_name}")
    path = _regular_bound_file(package_root, value.get("artifact"), "package toolchain")
    try:
        content = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise SnapshotValidationError(f"invalid package toolchain file for {package_name}: {exc}") from exc
    if not TOOLCHAIN_RE.fullmatch(content):
        raise SnapshotValidationError(f"package {package_name} has an unpinned toolchain")
    if value.get("content") != content or value.get("sha256") != sha256_file(path):
        raise SnapshotValidationError(f"package {package_name} toolchain binding mismatch")
    return dict(value)


def _files_equal(left: Path, right: Path) -> bool:
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open("rb") as left_stream, right.open("rb") as right_stream:
        while True:
            left_block = left_stream.read(1024 * 1024)
            right_block = right_stream.read(1024 * 1024)
            if left_block != right_block:
                return False
            if not left_block:
                return True


def _validate_symlink_normalizations(
    package_root: Path,
    inventory: Sequence[Mapping[str, Any]],
    value: Any,
    expected_digest: Any,
    package_name: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise SnapshotValidationError(
            f"package {package_name} symlink_normalizations must be a list"
        )
    if not isinstance(expected_digest, str) or not SHA256_RE.fullmatch(expected_digest):
        raise SnapshotValidationError(
            f"package {package_name} symlink normalization digest is invalid"
        )
    if sha256_bytes(canonical_json_bytes(value)) != expected_digest:
        raise SnapshotValidationError(
            f"package {package_name} symlink normalization SHA-256 mismatch"
        )
    if any(not isinstance(item, dict) for item in value):
        raise SnapshotValidationError(
            f"package {package_name} has a malformed symlink normalization"
        )
    sources = [item.get("source_path") for item in value]
    if sources != sorted(sources, key=lambda item: str(item).encode("utf-8")):
        raise SnapshotValidationError(
            f"package {package_name} symlink normalizations are not sorted"
        )
    if len(sources) != len(set(sources)):
        raise SnapshotValidationError(
            f"package {package_name} has duplicate symlink normalizations"
        )
    inventory_by_path = {str(item.get("path")): item for item in inventory}
    link_text_by_source: dict[str, str] = {}
    for item in value:
        _require_exact_keys(
            item, SYMLINK_NORMALIZATION_KEYS, f"package {package_name} symlink normalization"
        )
        source = _safe_relative(
            item.get("source_path"), f"package {package_name} normalized symlink source"
        )
        resolved = _safe_relative(
            item.get("resolved_tracked_path"),
            f"package {package_name} normalized symlink target",
        )
        link_text = item.get("link_text")
        if not isinstance(link_text, str):
            raise SnapshotValidationError(
                f"package {package_name} symlink {source} lacks exact link text"
            )
        # Validate each first hop now; the full chain is checked below.
        resolve_relative_symlink_target(source, link_text)
        if source == resolved:
            raise SnapshotValidationError(
                f"package {package_name} symlink {source} resolves to itself"
            )
        target_sha = item.get("target_sha256")
        materialized_mode = item.get("materialized_mode")
        if not isinstance(target_sha, str) or not SHA256_RE.fullmatch(target_sha):
            raise SnapshotValidationError(
                f"package {package_name} symlink {source} target SHA-256 is invalid"
            )
        if not isinstance(materialized_mode, str) or not re.fullmatch(
            r"0[0-7]{3}", materialized_mode
        ):
            raise SnapshotValidationError(
                f"package {package_name} symlink {source} materialized mode is invalid"
            )
        source_inventory = inventory_by_path.get(source)
        target_inventory = inventory_by_path.get(resolved)
        if source_inventory is None or target_inventory is None:
            raise SnapshotValidationError(
                f"package {package_name} symlink {source} does not resolve to an inventory-bound regular file"
            )
        if (
            source_inventory.get("sha256") != target_sha
            or target_inventory.get("sha256") != target_sha
            or source_inventory.get("mode") != materialized_mode
            or target_inventory.get("mode") != materialized_mode
            or source_inventory.get("size") != target_inventory.get("size")
        ):
            raise SnapshotValidationError(
                f"package {package_name} symlink {source} materialized bytes/hash/mode mismatch"
            )
        source_file = _regular_bound_file(
            package_root, source, f"materialized symlink source for {package_name}"
        )
        target_file = _regular_bound_file(
            package_root, resolved, f"materialized symlink target for {package_name}"
        )
        if not _files_equal(source_file, target_file):
            raise SnapshotValidationError(
                f"package {package_name} symlink {source} is not an exact regular-file copy"
            )
        link_text_by_source[source] = link_text
    maximum_hops = max(1, len(value) + 1)
    for item in value:
        source = str(item["source_path"])
        actual_resolved = resolve_symlink_chain(
            source, link_text_by_source, maximum_hops=maximum_hops
        )
        if actual_resolved != item["resolved_tracked_path"]:
            raise SnapshotValidationError(
                f"package {package_name} symlink {source} resolved-path binding mismatch"
            )
        if actual_resolved in link_text_by_source:
            raise SnapshotValidationError(
                f"package {package_name} symlink {source} did not terminate at a regular file"
            )
    return [dict(item) for item in value]


def _validate_gitlink_omissions(
    package_root: Path,
    inventory: Sequence[Mapping[str, Any]],
    value: Any,
    expected_digest: Any,
    package_name: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise SnapshotValidationError(
            f"package {package_name} gitlink_omissions must be a list"
        )
    if not isinstance(expected_digest, str) or not SHA256_RE.fullmatch(expected_digest):
        raise SnapshotValidationError(
            f"package {package_name} gitlink omission digest is invalid"
        )
    if sha256_bytes(canonical_json_bytes(value)) != expected_digest:
        raise SnapshotValidationError(
            f"package {package_name} gitlink omission SHA-256 mismatch"
        )
    inventory_paths = {str(item.get("path")) for item in inventory}
    paths: list[str] = []
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise SnapshotValidationError(
                f"package {package_name} has a malformed gitlink omission"
            )
        _require_exact_keys(
            item, GITLINK_OMISSION_KEYS, f"package {package_name} gitlink omission"
        )
        relative = _safe_relative(
            item.get("path"), f"package {package_name} gitlink omission path"
        )
        commit_oid = item.get("commit_oid")
        if not isinstance(commit_oid, str) or not REVISION_RE.fullmatch(commit_oid):
            raise SnapshotValidationError(
                f"package {package_name} gitlink {relative} has invalid commit OID"
            )
        if item.get("materialized_as") != "empty_directory":
            raise SnapshotValidationError(
                f"package {package_name} gitlink {relative} has invalid materialization"
            )
        if item.get("source_available") is not False:
            raise SnapshotValidationError(
                f"package {package_name} gitlink {relative} must record unavailable source"
            )
        if relative in inventory_paths:
            raise SnapshotValidationError(
                f"package {package_name} gitlink {relative} collides with source inventory"
            )
        _require_empty_real_directory(
            package_root, relative, f"package {package_name} materialized gitlink"
        )
        paths.append(relative)
        normalized.append(dict(item))
    if paths != sorted(paths, key=lambda item: item.encode("utf-8")):
        raise SnapshotValidationError(
            f"package {package_name} gitlink omissions are not sorted"
        )
    if len(paths) != len(set(paths)):
        raise SnapshotValidationError(
            f"package {package_name} has duplicate gitlink omissions"
        )
    actual_empty_directories = scan_empty_directories(package_root)
    if actual_empty_directories != paths:
        raise SnapshotValidationError(
            f"package {package_name} empty-directory layout does not exactly match gitlink omissions; "
            f"recorded={paths}, actual={actual_empty_directories}"
        )
    return normalized


def validate_snapshot(snapshot: Path) -> dict[str, Any]:
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise SnapshotValidationError(f"snapshot must be a regular directory: {snapshot}")
    expected_top = {
        "dependency-snapshot.json",
        "lake-manifest.json",
        "inventories",
        "packages",
    }
    actual_top = {entry.name for entry in os.scandir(snapshot)}
    if actual_top != expected_top:
        raise SnapshotValidationError(
            f"snapshot top-level layout mismatch; missing={sorted(expected_top-actual_top)}, "
            f"extra={sorted(actual_top-expected_top)}"
        )
    # Whole-tree scan rejects links, special files, metadata, caches, binaries,
    # hardlinks, and path collisions before trusting any inner manifest.
    scan_source_tree(snapshot)

    metadata = _read_json_object(snapshot / "dependency-snapshot.json", "dependency snapshot manifest")
    _require_exact_keys(metadata, SNAPSHOT_KEYS, "dependency snapshot manifest")
    if metadata.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise SnapshotValidationError("unsupported dependency snapshot schema_version")
    if metadata.get("record_type") != SNAPSHOT_RECORD_TYPE:
        raise SnapshotValidationError("invalid dependency snapshot record_type")
    if metadata.get("protocol_version") != PROTOCOL_VERSION:
        raise SnapshotValidationError("unsupported dependency snapshot protocol_version")
    _safe_identifier(metadata.get("snapshot_id"), "snapshot id")
    _safe_identifier(metadata.get("created_by"), "snapshot actor")
    if not isinstance(metadata.get("created_at"), str) or not metadata["created_at"]:
        raise SnapshotValidationError("dependency snapshot created_at is required")
    if metadata.get("source_workspace_recorded") is not False:
        raise SnapshotValidationError("portable snapshots must not record the source workspace path")
    if metadata.get("policies") != SOURCE_ONLY_POLICIES:
        raise SnapshotValidationError("dependency snapshot source-only policy mismatch")

    lake_binding = metadata.get("lake_manifest")
    if not isinstance(lake_binding, dict):
        raise SnapshotValidationError("dependency snapshot lake_manifest binding is missing")
    _require_exact_keys(lake_binding, SNAPSHOT_LAKE_KEYS, "snapshot Lake binding")
    if lake_binding.get("artifact") != "lake-manifest.json":
        raise SnapshotValidationError("snapshot Lake artifact must be lake-manifest.json")
    lake_path = snapshot / "lake-manifest.json"
    if lake_binding.get("sha256") != sha256_file(lake_path):
        raise SnapshotValidationError("snapshot Lake manifest SHA-256 mismatch")
    lake_manifest = validate_lake_manifest(lake_path)
    if lake_binding.get("version") != lake_manifest["version"]:
        raise SnapshotValidationError("snapshot Lake manifest version binding mismatch")
    if lake_binding.get("root_package_name") != lake_manifest["name"]:
        raise SnapshotValidationError("snapshot root package name binding mismatch")
    if lake_binding.get("fixed_toolchain") != lake_manifest.get("fixedToolchain"):
        raise SnapshotValidationError("snapshot fixedToolchain binding mismatch")
    graph_digest = dependency_graph_sha256(lake_manifest)
    if metadata.get("dependency_graph_sha256") != graph_digest:
        raise SnapshotValidationError("dependency graph SHA-256 mismatch")

    packages = metadata.get("packages")
    if not isinstance(packages, list) or not packages:
        raise SnapshotValidationError("snapshot packages must be a nonempty list")
    package_names = [item.get("name") for item in packages if isinstance(item, dict)]
    if len(package_names) != len(packages) or package_names != sorted(package_names):
        raise SnapshotValidationError("snapshot package entries must be objects sorted by name")
    lake_by_name = {item["name"]: item for item in lake_manifest["packages"]}
    if set(package_names) != set(lake_by_name):
        raise SnapshotValidationError("snapshot package set does not equal the Lake dependency graph")

    packages_dir = snapshot / "packages"
    inventories_dir = snapshot / "inventories"
    if packages_dir.is_symlink() or not packages_dir.is_dir():
        raise SnapshotValidationError("snapshot packages directory is missing or unsafe")
    if inventories_dir.is_symlink() or not inventories_dir.is_dir():
        raise SnapshotValidationError("snapshot inventories directory is missing or unsafe")
    if {item.name for item in os.scandir(packages_dir)} != set(package_names):
        raise SnapshotValidationError("snapshot package directories do not match package bindings")
    if {item.name for item in os.scandir(inventories_dir)} != {
        f"{name}.json" for name in package_names
    }:
        raise SnapshotValidationError("snapshot inventory files do not match package bindings")

    seen_names: dict[str, str] = {}
    for package in packages:
        _require_exact_keys(package, SNAPSHOT_PACKAGE_KEYS, "snapshot package binding")
        name = _safe_package_name(package.get("name"), "snapshot package name")
        _check_collision(seen_names, name, "snapshot package names")
        lake_package = lake_by_name[name]
        if package.get("safe_directory") != name:
            raise SnapshotValidationError(f"snapshot package {name} safe_directory mismatch")
        if package.get("source_kind") != "git":
            raise SnapshotValidationError(f"snapshot package {name} source_kind must be git")
        expected_scalar_bindings = {
            "source_url": lake_package["url"],
            "resolved_revision": lake_package["rev"],
            "input_revision": lake_package["inputRev"],
            "scope": lake_package["scope"],
            "subdir": lake_package["subDir"],
        }
        for field, expected in expected_scalar_bindings.items():
            if package.get(field) != expected:
                raise SnapshotValidationError(f"snapshot package {name} {field} mismatch")
        if not isinstance(package.get("git_tree_oid"), str) or not REVISION_RE.fullmatch(
            package["git_tree_oid"]
        ):
            raise SnapshotValidationError(f"snapshot package {name} has invalid Git tree OID")
        if package.get("source_tree_profile") != TREE_PROFILE:
            raise SnapshotValidationError(f"snapshot package {name} tree profile mismatch")
        if package.get("review_required") is not True:
            raise SnapshotValidationError(f"snapshot package {name} must require executable-config review")
        expected_executable = lake_package["configFile"] == "lakefile.lean"
        if package.get("executable_config") is not expected_executable:
            raise SnapshotValidationError(f"snapshot package {name} executable_config mismatch")

        package_root = packages_dir / name
        inventory_path = _regular_bound_file(
            snapshot, package.get("source_inventory"), f"inventory for {name}"
        )
        if package.get("source_inventory") != f"inventories/{name}.json":
            raise SnapshotValidationError(f"snapshot package {name} inventory path mismatch")
        if package.get("source_inventory_sha256") != sha256_file(inventory_path):
            raise SnapshotValidationError(f"snapshot package {name} inventory SHA-256 mismatch")
        try:
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SnapshotValidationError(f"cannot parse inventory for {name}: {exc}") from exc
        if not isinstance(inventory, list):
            raise SnapshotValidationError(f"inventory for {name} must be a list")
        current_inventory = scan_source_tree(package_root)
        if inventory != current_inventory:
            raise SnapshotValidationError(f"snapshot package {name} source inventory mismatch")
        _validate_symlink_normalizations(
            package_root,
            current_inventory,
            package.get("symlink_normalizations"),
            package.get("symlink_normalizations_sha256"),
            name,
        )
        gitlink_omissions = _validate_gitlink_omissions(
            package_root,
            current_inventory,
            package.get("gitlink_omissions"),
            package.get("gitlink_omissions_sha256"),
            name,
        )
        tree_digest = dependency_tree_sha256(
            package_root, current_inventory, gitlink_omissions
        )
        if package.get("source_tree_sha256") != tree_digest:
            raise SnapshotValidationError(f"snapshot package {name} source tree SHA-256 mismatch")

        subdir = lake_package["subDir"]
        prefix = f"{subdir}/" if subdir else ""
        config_relative = prefix + lake_package["configFile"]
        manifest_relative = prefix + lake_package["manifestFile"]
        if package.get("config_file") != config_relative:
            raise SnapshotValidationError(f"snapshot package {name} config path mismatch")
        if package.get("manifest_file") != manifest_relative:
            raise SnapshotValidationError(f"snapshot package {name} manifest path mismatch")
        config_path = _regular_bound_file(package_root, config_relative, f"config for {name}")
        manifest_path = _regular_bound_file(package_root, manifest_relative, f"manifest for {name}")
        if package.get("config_sha256") != sha256_file(config_path):
            raise SnapshotValidationError(f"snapshot package {name} config SHA-256 mismatch")
        if package.get("manifest_sha256") != sha256_file(manifest_path):
            raise SnapshotValidationError(f"snapshot package {name} manifest SHA-256 mismatch")
        _validate_toolchain_binding(package_root, package.get("toolchain"), name)

    closure_digest = dependency_closure_sha256(graph_digest, packages)
    if metadata.get("dependency_closure_sha256") != closure_digest:
        raise SnapshotValidationError("dependency closure SHA-256 mismatch")
    return {
        "ok": True,
        "snapshot_id": metadata["snapshot_id"],
        "protocol_version": metadata["protocol_version"],
        "lake_manifest_version": lake_manifest["version"],
        "dependency_graph_sha256": graph_digest,
        "dependency_closure_sha256": closure_digest,
        "packages": package_names,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Strictly validate one offline Lean Room v2 source dependency snapshot."
    )
    parser.add_argument("snapshot", help="dependency snapshot directory")
    parser.add_argument("--json", action="store_true", help="emit JSON result")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = validate_snapshot(Path(args.snapshot))
    except SnapshotValidationError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_VALIDATION
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(
            "Lean dependency snapshot valid: "
            f"{result['snapshot_id']} ({len(result['packages'])} packages)"
        )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
