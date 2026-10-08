#!/usr/bin/env python3
"""Offline importer for Lean Room v2 source-only dependency snapshots.

The input is an already-resolved Lake workspace.  This command never invokes
Lean or Lake and never fetches, clones, updates, or otherwise contacts a
network service.  It verifies local Git checkout identities, copies only
tracked source bytes into a generator-owned staging directory, validates the
complete staged snapshot, and publishes it by an atomic no-overwrite rename.

Expected input layout::

    <workspace>/lake-manifest.json
    <workspace>/.lake/packages/<manifest package name>/

The checkout's top-level ``.git`` directory is used only for local identity
verification. An official resolver may also leave a top-level ``.lake`` build
directory in a package checkout. Those two regular metadata/cache directories
are ignored and never copied; nested metadata/cache paths elsewhere are
rejected.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from lean_room import ValidationError as LeanRoomValidationError
from lean_room import publish_directory_noreplace, utc_now
from validate_lean_dependency_snapshot import (
    EXIT_OK,
    EXIT_VALIDATION,
    PROTOCOL_VERSION,
    REVISION_RE,
    SNAPSHOT_RECORD_TYPE,
    SNAPSHOT_SCHEMA_VERSION,
    SOURCE_ONLY_POLICIES,
    TOOLCHAIN_RE,
    TREE_PROFILE,
    SnapshotValidationError,
    canonical_json_bytes,
    dependency_closure_sha256,
    dependency_graph_sha256,
    dependency_tree_sha256,
    pretty_json_bytes,
    resolve_symlink_chain,
    scan_empty_directories,
    scan_import_source_layout,
    scan_source_tree,
    sha256_bytes,
    sha256_file,
    validate_lake_manifest,
    validate_snapshot,
)


IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


@dataclass(frozen=True)
class SourcePackage:
    manifest_entry: Mapping[str, Any]
    source: Path
    inventory: tuple[dict[str, Any], ...]
    symlink_normalizations: tuple[dict[str, Any], ...]
    gitlink_omissions: tuple[dict[str, Any], ...]
    head_oid: str
    tree_oid: str


def _git_executable() -> Path:
    candidate = shutil.which("git", path="/usr/bin:/bin:/usr/local/bin")
    if candidate is None:
        raise SnapshotValidationError("local Git is required to verify resolved checkouts")
    path = Path(candidate)
    if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
        raise SnapshotValidationError("local Git executable is missing or unsafe")
    return path


def _git_environment(git: Path) -> dict[str, str]:
    return {
        "PATH": str(git.parent) + ":/usr/bin:/bin",
        "HOME": "/nonexistent-lean-room-import-home",
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_ALLOW_PROTOCOL": "file",
    }


def _run_git(git: Path, checkout: Path, arguments: Sequence[str]) -> bytes:
    """Run one local, read-only Git query from a fixed command allowlist."""

    if not arguments or arguments[0] not in {
        "rev-parse",
        "status",
        "ls-files",
        "diff",
        "cat-file",
    }:
        raise SnapshotValidationError("internal importer attempted a non-read-only Git command")
    command = [
        str(git),
        "-c",
        "core.hooksPath=/dev/null",
        "-C",
        str(checkout),
        *arguments,
    ]
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=_git_environment(git),
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SnapshotValidationError(f"local Git verification failed to run: {exc}") from exc
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise SnapshotValidationError(
            f"local Git verification failed ({arguments[0]}): {message or result.returncode}"
        )
    return result.stdout


def _decode_oid(value: bytes, label: str) -> str:
    try:
        rendered = value.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise SnapshotValidationError(f"non-ASCII {label}") from exc
    if not REVISION_RE.fullmatch(rendered):
        raise SnapshotValidationError(f"invalid exact {label}: {rendered!r}")
    return rendered


def _canonical_git_index_path(value: str) -> str:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise SnapshotValidationError("Git index path is not UTF-8") from exc
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise SnapshotValidationError(f"noncanonical Git index path: {value!r}")
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise SnapshotValidationError(f"noncanonical Git index path: {value!r}")
    rendered = PurePosixPath(value).as_posix()
    if rendered != value:
        raise SnapshotValidationError(f"noncanonical Git index path: {value!r}")
    return rendered


def _tracked_index(git: Path, source: Path) -> dict[str, dict[str, str]]:
    raw = _run_git(git, source, ["ls-files", "--stage", "-z"])
    tracked: dict[str, dict[str, str]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, encoded_path = record.split(b"\t", 1)
            mode, object_oid, stage = metadata.decode("ascii").split(" ")
            relative = _canonical_git_index_path(
                encoded_path.decode("utf-8", errors="strict")
            )
        except (ValueError, UnicodeDecodeError) as exc:
            raise SnapshotValidationError("cannot parse UTF-8 Git index entry") from exc
        if stage != "0":
            raise SnapshotValidationError(f"unmerged Git index entry is forbidden: {relative}")
        if mode not in {"100644", "100755", "120000", "160000"}:
            raise SnapshotValidationError(f"unsupported Git file mode {mode}: {relative}")
        if not REVISION_RE.fullmatch(object_oid):
            raise SnapshotValidationError(f"invalid Git object OID for tracked path: {relative}")
        if relative in tracked:
            raise SnapshotValidationError(f"duplicate Git index path: {relative}")
        tracked[relative] = {"mode": mode, "oid": object_oid}
    return tracked


def _inspect_package(git: Path, workspace: Path, package: Mapping[str, Any]) -> SourcePackage:
    name = str(package["name"])
    source = workspace / ".lake" / "packages" / name
    if source.is_symlink() or not source.is_dir():
        raise SnapshotValidationError(f"resolved package checkout is missing or unsafe: {name}")
    git_dir = source / ".git"
    if git_dir.is_symlink() or not git_dir.is_dir():
        raise SnapshotValidationError(
            f"resolved Git package {name} must have a regular top-level .git directory"
        )

    # Scan before Git status so a forbidden ignored cache/metadata path cannot
    # be hidden by repository ignore rules.
    regular_inventory, observed_symlinks, observed_empty_directories = scan_import_source_layout(
        source, allow_root_git=True, allow_root_lake=True
    )
    head_oid = _decode_oid(
        _run_git(git, source, ["rev-parse", "--verify", "HEAD^{commit}"]),
        f"HEAD commit for {name}",
    )
    if head_oid != package["rev"]:
        raise SnapshotValidationError(
            f"resolved package {name} HEAD {head_oid} does not equal manifest rev {package['rev']}"
        )
    tree_oid = _decode_oid(
        _run_git(git, source, ["rev-parse", "--verify", "HEAD^{tree}"]),
        f"Git tree for {name}",
    )
    status = _run_git(
        git,
        source,
        ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none"],
    )
    if status:
        raise SnapshotValidationError(f"resolved package checkout is dirty: {name}")
    _run_git(git, source, ["diff", "--quiet", "--no-ext-diff", "HEAD", "--"])
    tracked = _tracked_index(git, source)
    observed = {entry["path"]: entry for entry in regular_inventory}
    observed_links = {entry["path"]: entry["link_text"] for entry in observed_symlinks}
    observed_paths = set(observed) | set(observed_links)
    tracked_gitlinks = {
        relative for relative, entry in tracked.items() if entry["mode"] == "160000"
    }
    tracked_materialized_paths = set(tracked) - tracked_gitlinks
    if tracked_materialized_paths != observed_paths:
        extra = sorted(observed_paths - tracked_materialized_paths)
        missing = sorted(tracked_materialized_paths - observed_paths)
        raise SnapshotValidationError(
            f"package {name} working tree is not exactly the tracked Git tree; "
            f"untracked_or_ignored={extra}, missing={missing}"
        )
    observed_empty_set = set(observed_empty_directories)
    if observed_empty_set != tracked_gitlinks:
        extra = sorted(observed_empty_set - tracked_gitlinks)
        missing = sorted(tracked_gitlinks - observed_empty_set)
        raise SnapshotValidationError(
            f"package {name} uninitialized gitlinks must be exact empty real directories; "
            f"untracked_empty={extra}, missing_or_populated_gitlinks={missing}"
        )
    for relative, git_entry in tracked.items():
        git_mode = git_entry["mode"]
        if git_mode == "160000":
            if relative not in observed_empty_set:
                raise SnapshotValidationError(
                    f"package {name} gitlink is not an empty real directory: {relative}"
                )
            continue
        if relative in observed_links:
            if git_mode != "120000":
                raise SnapshotValidationError(
                    f"package {name} working-tree symlink is not a tracked Git symlink: {relative}"
                )
            try:
                git_link_text = _run_git(
                    git, source, ["cat-file", "blob", git_entry["oid"]]
                ).decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise SnapshotValidationError(
                    f"package {name} tracked symlink target is not UTF-8: {relative}"
                ) from exc
            if observed_links[relative] != git_link_text:
                raise SnapshotValidationError(
                    f"package {name} working-tree symlink text disagrees with Git: {relative}"
                )
            continue
        if git_mode not in {"100644", "100755"}:
            raise SnapshotValidationError(
                f"package {name} tracked symlink is missing from working tree: {relative}"
            )
        observed_mode = int(observed[relative]["mode"], 8)
        executable = bool(observed_mode & 0o111)
        if executable != (git_mode == "100755"):
            raise SnapshotValidationError(
                f"package {name} working-tree executable mode disagrees with Git: {relative}"
            )
    normalizations: list[dict[str, Any]] = []
    for relative in sorted(observed_links, key=lambda item: item.encode("utf-8")):
        resolved = resolve_symlink_chain(
            relative,
            observed_links,
            maximum_hops=max(1, len(observed_links) + 1),
        )
        resolved_git = tracked.get(resolved)
        target = observed.get(resolved)
        if (
            resolved_git is None
            or resolved_git["mode"] not in {"100644", "100755"}
            or target is None
        ):
            raise SnapshotValidationError(
                f"package {name} tracked symlink {relative} does not resolve to a tracked regular file"
            )
        normalizations.append(
            {
                "source_path": relative,
                "link_text": observed_links[relative],
                "resolved_tracked_path": resolved,
                "target_sha256": target["sha256"],
                "materialized_mode": target["mode"],
            }
        )

    materialized_inventory = list(regular_inventory)
    for normalization in normalizations:
        target = observed[str(normalization["resolved_tracked_path"])]
        materialized_inventory.append(
            {
                "path": normalization["source_path"],
                "mode": target["mode"],
                "size": target["size"],
                "sha256": target["sha256"],
            }
        )
    materialized_inventory.sort(key=lambda item: str(item["path"]).encode("utf-8"))
    gitlink_omissions = tuple(
        {
            "path": relative,
            "commit_oid": tracked[relative]["oid"],
            "materialized_as": "empty_directory",
            "source_available": False,
        }
        for relative in sorted(tracked_gitlinks, key=lambda item: item.encode("utf-8"))
    )
    return SourcePackage(
        package,
        source,
        tuple(materialized_inventory),
        tuple(normalizations),
        gitlink_omissions,
        head_oid,
        tree_oid,
    )


def _copy_package(binding: SourcePackage, destination: Path) -> list[dict[str, Any]]:
    destination.mkdir(mode=0o755)
    normalized_targets = {
        str(item["source_path"]): str(item["resolved_tracked_path"])
        for item in binding.symlink_normalizations
    }
    for entry in binding.inventory:
        relative = PurePosixPath(entry["path"])
        source_relative = PurePosixPath(
            normalized_targets.get(relative.as_posix(), relative.as_posix())
        )
        source = binding.source.joinpath(*source_relative.parts)
        target = destination.joinpath(*relative.parts)
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        try:
            shutil.copyfile(source, target, follow_symlinks=False)
            os.chmod(target, int(entry["mode"], 8), follow_symlinks=False)
        except OSError as exc:
            raise SnapshotValidationError(f"cannot copy dependency source {relative}: {exc}") from exc
    for omission in binding.gitlink_omissions:
        relative = PurePosixPath(str(omission["path"]))
        target = destination.joinpath(*relative.parts)
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        try:
            target.mkdir(mode=0o755)
            os.chmod(target, 0o755, follow_symlinks=False)
        except OSError as exc:
            raise SnapshotValidationError(
                f"cannot materialize unavailable gitlink {relative} as empty directory: {exc}"
            ) from exc
    copied = scan_source_tree(destination)
    if copied != list(binding.inventory):
        raise SnapshotValidationError(
            f"copied package {binding.manifest_entry['name']} differs from observed source bytes/modes"
        )
    copied_empty_directories = scan_empty_directories(destination)
    expected_empty_directories = [
        str(item["path"]) for item in binding.gitlink_omissions
    ]
    if copied_empty_directories != expected_empty_directories:
        raise SnapshotValidationError(
            f"copied package {binding.manifest_entry['name']} gitlink omission layout differs"
        )
    return copied


def _bound_package_file(package_root: Path, relative: str, label: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise SnapshotValidationError(f"unsafe {label}: {relative!r}")
    path = package_root.joinpath(*pure.parts)
    if path.is_symlink() or not path.is_file():
        raise SnapshotValidationError(f"missing regular {label}: {relative}")
    return path


def _package_snapshot_entry(
    package: Mapping[str, Any],
    binding: SourcePackage,
    package_root: Path,
    inventory_relative: str,
    inventory_path: Path,
    inventory: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    name = str(package["name"])
    subdir = package["subDir"]
    prefix = f"{subdir}/" if subdir else ""
    config_relative = prefix + package["configFile"]
    manifest_relative = prefix + package["manifestFile"]
    config = _bound_package_file(package_root, config_relative, f"package {name} config")
    package_manifest = _bound_package_file(
        package_root, manifest_relative, f"package {name} manifest"
    )
    toolchain_relative = prefix + "lean-toolchain"
    toolchain_path = package_root.joinpath(*PurePosixPath(toolchain_relative).parts)
    toolchain: dict[str, Any] | None = None
    if toolchain_path.exists() or toolchain_path.is_symlink():
        if toolchain_path.is_symlink() or not toolchain_path.is_file():
            raise SnapshotValidationError(f"package {name} toolchain path is unsafe")
        try:
            content = toolchain_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise SnapshotValidationError(f"cannot read package {name} toolchain: {exc}") from exc
        if not TOOLCHAIN_RE.fullmatch(content):
            raise SnapshotValidationError(f"package {name} toolchain is not an exact Lean pin")
        toolchain = {
            "artifact": toolchain_relative,
            "content": content,
            "sha256": sha256_file(toolchain_path),
        }
    return {
        "name": name,
        "safe_directory": name,
        "source_kind": "git",
        "source_url": package["url"],
        "resolved_revision": package["rev"],
        "git_tree_oid": binding.tree_oid,
        "input_revision": package["inputRev"],
        "scope": package["scope"],
        "subdir": subdir,
        "config_file": config_relative,
        "config_sha256": sha256_file(config),
        "manifest_file": manifest_relative,
        "manifest_sha256": sha256_file(package_manifest),
        "source_inventory": inventory_relative,
        "source_inventory_sha256": sha256_file(inventory_path),
        "source_tree_sha256": dependency_tree_sha256(
            package_root, inventory, binding.gitlink_omissions
        ),
        "source_tree_profile": TREE_PROFILE,
        "gitlink_omissions": [dict(item) for item in binding.gitlink_omissions],
        "gitlink_omissions_sha256": sha256_bytes(
            canonical_json_bytes([dict(item) for item in binding.gitlink_omissions])
        ),
        "symlink_normalizations": [dict(item) for item in binding.symlink_normalizations],
        "symlink_normalizations_sha256": sha256_bytes(
            canonical_json_bytes([dict(item) for item in binding.symlink_normalizations])
        ),
        "toolchain": toolchain,
        "executable_config": package["configFile"] == "lakefile.lean",
        "review_required": True,
    }


def _safe_actor(value: str, label: str) -> str:
    if not IDENTIFIER_RE.fullmatch(value):
        raise SnapshotValidationError(f"invalid {label}: {value!r}")
    return value


def import_snapshot(
    workspace: Path,
    destination: Path,
    snapshot_id: str,
    actor: str,
) -> dict[str, Any]:
    snapshot_id = _safe_actor(snapshot_id, "snapshot id")
    actor = _safe_actor(actor, "actor id")
    if workspace.is_symlink() or not workspace.is_dir():
        raise SnapshotValidationError(f"resolved workspace must be a regular directory: {workspace}")
    destination_parent = destination.parent
    if destination_parent.is_symlink() or not destination_parent.is_dir():
        raise SnapshotValidationError(
            f"snapshot destination parent must be an existing regular directory: {destination_parent}"
        )
    if destination.exists() or destination.is_symlink():
        raise SnapshotValidationError(f"snapshot destination already exists: {destination}")

    manifest_path = workspace / "lake-manifest.json"
    lake_manifest = validate_lake_manifest(manifest_path)
    manifest_sha = sha256_file(manifest_path)
    graph_sha = dependency_graph_sha256(lake_manifest)
    git = _git_executable()
    source_bindings = [
        _inspect_package(git, workspace, package)
        for package in lake_manifest["packages"]
    ]

    stage = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.stage-", dir=str(destination_parent))
    )
    published = False
    try:
        packages_dir = stage / "packages"
        inventories_dir = stage / "inventories"
        packages_dir.mkdir()
        inventories_dir.mkdir()
        shutil.copyfile(manifest_path, stage / "lake-manifest.json", follow_symlinks=False)

        package_entries: list[dict[str, Any]] = []
        for binding in sorted(source_bindings, key=lambda item: str(item.manifest_entry["name"])):
            name = str(binding.manifest_entry["name"])
            package_root = packages_dir / name
            copied_inventory = _copy_package(binding, package_root)
            inventory_path = inventories_dir / f"{name}.json"
            inventory_path.write_bytes(pretty_json_bytes(copied_inventory))
            package_entries.append(
                _package_snapshot_entry(
                    binding.manifest_entry,
                    binding,
                    package_root,
                    f"inventories/{name}.json",
                    inventory_path,
                    copied_inventory,
                )
            )

        closure_sha = dependency_closure_sha256(graph_sha, package_entries)
        snapshot_manifest = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "record_type": SNAPSHOT_RECORD_TYPE,
            "protocol_version": PROTOCOL_VERSION,
            "snapshot_id": snapshot_id,
            "created_at": utc_now(),
            "created_by": actor,
            "source_workspace_recorded": False,
            "lake_manifest": {
                "artifact": "lake-manifest.json",
                "sha256": manifest_sha,
                "version": lake_manifest["version"],
                "root_package_name": lake_manifest["name"],
                "fixed_toolchain": lake_manifest.get("fixedToolchain"),
            },
            "dependency_graph_sha256": graph_sha,
            "dependency_closure_sha256": closure_sha,
            "policies": dict(SOURCE_ONLY_POLICIES),
            "packages": package_entries,
        }
        (stage / "dependency-snapshot.json").write_bytes(
            pretty_json_bytes(snapshot_manifest)
        )
        staged_result = validate_snapshot(stage)

        # Close the source-side TOCTOU window before the atomic publication.
        if sha256_file(manifest_path) != manifest_sha:
            raise SnapshotValidationError("root Lake manifest changed during snapshot import")
        for initial in source_bindings:
            current = _inspect_package(git, workspace, initial.manifest_entry)
            if (
                current.head_oid != initial.head_oid
                or current.tree_oid != initial.tree_oid
                or current.inventory != initial.inventory
                or current.symlink_normalizations != initial.symlink_normalizations
                or current.gitlink_omissions != initial.gitlink_omissions
            ):
                raise SnapshotValidationError(
                    f"source package changed during snapshot import: {initial.manifest_entry['name']}"
                )
        publish_directory_noreplace(stage, destination)
        published = True
        result = dict(staged_result)
        result["snapshot"] = str(destination)
        result["published"] = True
        result["network_used"] = False
        return result
    finally:
        if not published and stage.exists():
            shutil.rmtree(stage)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Import already-resolved local Git packages into an atomic, "
            "source-only Lean Room v2 snapshot without network access."
        )
    )
    parser.add_argument("workspace", help="already-resolved Lake workspace")
    parser.add_argument("destination", help="new snapshot directory; must not exist")
    parser.add_argument("--snapshot-id", required=True, help="immutable snapshot identifier")
    parser.add_argument("--actor", required=True, help="local importer actor identifier")
    parser.add_argument("--json", action="store_true", help="emit JSON result")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = import_snapshot(
            Path(args.workspace),
            Path(args.destination),
            args.snapshot_id,
            args.actor,
        )
    except (SnapshotValidationError, LeanRoomValidationError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_VALIDATION
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(
            "Lean dependency snapshot published: "
            f"{result['snapshot_id']} ({len(result['packages'])} packages)"
        )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
