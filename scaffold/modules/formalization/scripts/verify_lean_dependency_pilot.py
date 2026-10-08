#!/usr/bin/env python3
"""Run an explicitly authorized, non-certifying Lean dependency pilot.

This verifier is deliberately separate from the Lean Room v1 certificate
pipeline.  It executes only a Phase-A-validated, root-local source snapshot,
inside the existing deny-default macOS Seatbelt boundary, and can report only
``PILOT_VERIFIED_NOT_CERTIFIED`` (or a non-certifying failure/abort status).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import pwd
import re
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from lean_room import (
    EXIT_BUILD,
    EXIT_DISABLED,
    EXIT_OK,
    EXIT_VALIDATION,
    IDENTIFIER_RE,
    LEAN_ROOM_V1_ALLOWED_AXIOMS,
    LeanRoomError,
    RoomDisabledError,
    ValidationError,
    atomic_write_bytes,
    atomic_write_json,
    declaration_audit_bytes,
    discover_root,
    ensure_within,
    pretty_json_bytes,
    publish_directory_noreplace,
    reject_symlink_components,
    require_room_enabled,
    safe_append_container,
    safe_relative_file,
    sha256_bytes,
    sha256_file,
    utc_now,
    validate_identifier,
    validate_lean_name,
    validate_toolchain,
)
from validate_lean_case import (
    FORBIDDEN_PATTERNS,
    LAKEFILE_ALLOWED_SECTION_KEYS,
    LAKEFILE_ALLOWED_TOP_KEYS,
    LAKEFILE_FORBIDDEN_RE,
    declared_theorems,
    strip_lean_comments_and_strings,
)
from validate_lean_dependency_snapshot import (
    SnapshotValidationError,
    TREE_PROFILE,
    dependency_tree_sha256,
    scan_source_tree,
    validate_lake_manifest,
    validate_snapshot,
)
from verify_lean_case import (
    CommandResult,
    StateGuard,
    _axioms_from_output,
    _binary_mutations,
    _locked_state_guard,
    _state_guard,
    _wrapped,
    run_guarded,
)


PILOT_PROTOCOL_VERSION = "lean-room-v2-dependency-pilot-phase-b"
PILOT_SANDBOX_PROFILE_ID = (
    "macos-seatbelt-deny-default-phase-b-reviewed-literal-sidecars-v2"
)
SUCCESS_STATUS = "PILOT_VERIFIED_NOT_CERTIFIED"
FAILURE_STATUS = "PILOT_FAILED_NOT_CERTIFIED"
ABORT_STATUS = "ABORTED_ROOM_DISABLED_NOT_CERTIFIED"
REVIEW_RECORD_TYPE = "lean_dependency_snapshot_review_v2"
REVIEW_VERDICT = "APPROVED_FOR_PILOT_EXECUTION"
RUNS_RELATIVE = Path("research/formalization/dependency_pilots")
ROOT_REQUIRED_FILES = frozenset(
    {"lean-toolchain", "lakefile.toml", "lake-manifest.json", "LeanRoomCase.lean"}
)
REVIEW_KEYS = frozenset(
    {
        "schema_version",
        "record_type",
        "protocol_version",
        "review_id",
        "reviewed_at",
        "reviewed_by",
        "snapshot_binding",
        "verdict",
        "checks",
        "package_configuration_reviews",
        "derived_source_hash_sidecars",
        "open_issues",
        "residual_risks",
        "phase_b_execution_authorized",
        "certificate_eligible",
        "automatic_math_status_change",
    }
)
REVIEW_BINDING_KEYS = frozenset(
    {
        "artifact",
        "sha256",
        "snapshot_id",
        "dependency_graph_sha256",
        "dependency_closure_sha256",
    }
)
REVIEW_CHECK_KEYS = frozenset(
    {
        "lake_manifest_schema_and_graph_checked",
        "every_resolved_git_revision_checked",
        "every_source_inventory_and_tree_digest_checked",
        "toolchain_compatibility_checked",
        "package_configuration_files_reviewed",
        "no_git_directory_or_lake_cache_metadata_in_snapshot",
        "no_unbound_symlink_special_or_hardlinked_input",
        "tracked_symlink_normalizations_reviewed_and_accepted_per_package",
        "no_precompiled_or_executable_binary_input",
        "no_lfs_pointer_or_populated_gitlink_input",
        "gitlink_omissions_reviewed_and_accepted_per_package",
        "network_free_build_plan_checked",
        "reviewed_source_adjacent_hash_sidecars",
        "expanded_trusted_boundary_accepted",
    }
)
PACKAGE_REVIEW_KEYS = frozenset(
    {
        "name",
        "config_file",
        "config_sha256",
        "executable_config",
        "gitlink_omissions_sha256",
        "gitlink_omissions_reviewed",
        "symlink_normalizations_sha256",
        "symlink_normalizations_reviewed",
        "toolchain",
        "root_toolchain_compatibility_reviewed",
        "reviewed",
        "verdict",
    }
)
DERIVED_SOURCE_HASH_SIDECAR_KEYS = frozenset(
    {
        "package",
        "source_artifact",
        "trace_artifact",
        "reason_code",
        "justification",
        "reviewed",
    }
)
DERIVED_SOURCE_HASH_SIDECAR_LIMIT = 32
DERIVED_SOURCE_HASH_SIDECAR_REASON = "LAKE_REHASH_TRACKED_TRACE_CACHE"
DERIVED_HASH_RE = re.compile(rb"[0-9a-f]{16}\Z")
CANONICAL_IMPORT_RE = re.compile(
    r"import\s+[A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*\Z"
)


class PilotBuildFailure(LeanRoomError):
    exit_code = EXIT_BUILD


@dataclass(frozen=True)
class TreeCapture:
    path: Path
    artifact: str
    inventory: tuple[dict[str, Any], ...]
    digest: str

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact,
            "tree_profile": TREE_PROFILE,
            "tree_sha256": self.digest,
            "file_count": len(self.inventory),
            "inventory_sha256": sha256_bytes(pretty_json_bytes(list(self.inventory))),
        }


@dataclass(frozen=True)
class BoundFile:
    artifact: str
    path: Path
    sha256: str
    size: int

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact,
            "sha256": self.sha256,
            "size": self.size,
        }


@dataclass(frozen=True)
class DerivedSourceHashSidecar:
    package: str
    source_artifact: str
    trace_artifact: str
    artifact: str
    path: Path
    precreated_device: int
    precreated_inode: int


@dataclass(frozen=True)
class ToolchainRuntime:
    toolchain: str
    toolchain_root: Path
    elan_home: Path
    lean: Path
    lake: Path
    sandbox: Path
    leanchecker: Path | None
    binary_bindings: Mapping[str, Mapping[str, Any]]


@dataclass(frozen=True)
class PilotOutcome:
    status: str
    exit_code: int
    evidence_path: Path | None


Runner = Callable[
    [StateGuard, list[str], list[str], Path, Mapping[str, str], float],
    CommandResult,
]
Resolver = Callable[[str], ToolchainRuntime]
Wrapper = Callable[[str, list[str]], list[str]]


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        raise ValidationError(
            f"{label} has noncanonical fields; "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _load_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValidationError(f"missing regular {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot parse {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object")
    return value


def _safe_root_directory(root: Path, relative: str, label: str) -> tuple[Path, str]:
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ValidationError(f"unsafe root-local {label}: {relative!r}")
    target = root / candidate
    ensure_within(target, root, label)
    reject_symlink_components(target, root)
    if target.is_symlink() or not target.is_dir():
        raise ValidationError(f"missing regular root-local {label}: {target}")
    return target, candidate.as_posix()


def _capture_tree(path: Path, artifact: str, label: str) -> TreeCapture:
    try:
        inventory = scan_source_tree(path)
        digest = dependency_tree_sha256(path, inventory)
    except SnapshotValidationError as exc:
        raise ValidationError(f"unsafe {label}: {exc}") from exc
    return TreeCapture(path, artifact, tuple(dict(item) for item in inventory), digest)


def _bound_file(root: Path, relative: str, label: str) -> BoundFile:
    path = safe_relative_file(root, relative, label)
    return BoundFile(relative, path, sha256_file(path), path.stat().st_size)


def _package_toolchain_mismatches(
    packages: Sequence[Mapping[str, Any]], root_toolchain: str
) -> list[dict[str, str]]:
    mismatches: list[dict[str, str]] = []
    for package in packages:
        binding = package.get("toolchain")
        if binding is None:
            continue
        if not isinstance(binding, Mapping) or not isinstance(binding.get("content"), str):
            raise ValidationError(
                f"validated dependency {package.get('name')} has malformed toolchain binding"
            )
        package_toolchain = str(binding["content"])
        if package_toolchain != root_toolchain:
            mismatches.append(
                {
                    "package": str(package.get("name")),
                    "package_toolchain": package_toolchain,
                    "root_toolchain": root_toolchain,
                }
            )
    return sorted(mismatches, key=lambda item: item["package"])


def _canonical_relative_artifact(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValidationError(f"{label} must be a canonical relative POSIX path")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != value
    ):
        raise ValidationError(f"{label} must be a canonical relative POSIX path")
    return value


def _review_snapshot(
    root: Path,
    review_relative: str,
    snapshot_relative: str,
    snapshot_path: Path,
    snapshot: Mapping[str, Any],
    snapshot_metadata: Mapping[str, Any],
    root_toolchain: str,
) -> tuple[dict[str, Any], BoundFile, bytes]:
    review_path = safe_relative_file(root, review_relative, "dependency execution review")
    try:
        review_bytes = review_path.read_bytes()
        review = json.loads(review_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot parse dependency execution review: {exc}") from exc
    if not isinstance(review, dict):
        raise ValidationError("dependency execution review must be a JSON object")
    binding = BoundFile(
        review_relative,
        review_path,
        sha256_bytes(review_bytes),
        len(review_bytes),
    )
    _exact_keys(review, REVIEW_KEYS, "dependency execution review")
    if review.get("schema_version") != 1 or review.get("record_type") != REVIEW_RECORD_TYPE:
        raise ValidationError("unsupported dependency execution review schema")
    if review.get("protocol_version") != snapshot["protocol_version"]:
        raise ValidationError("dependency execution review protocol mismatch")
    review_id = review.get("review_id")
    if not isinstance(review_id, str) or not IDENTIFIER_RE.fullmatch(review_id):
        raise ValidationError("dependency execution review_id is invalid")
    for field in ("reviewed_at", "reviewed_by"):
        if not isinstance(review.get(field), str) or not review[field].strip():
            raise ValidationError(f"dependency execution review {field} is required")
    if review.get("verdict") != REVIEW_VERDICT:
        raise ValidationError(f"dependency execution review verdict must be {REVIEW_VERDICT}")
    if review.get("phase_b_execution_authorized") is not True:
        raise ValidationError("Phase-B dependency execution is not explicitly authorized")
    if review.get("certificate_eligible") is not False:
        raise ValidationError("dependency pilot review must remain non-certifying")
    if review.get("automatic_math_status_change") is not False:
        raise ValidationError("dependency pilot review cannot authorize math-status changes")
    if review.get("open_issues") != []:
        raise ValidationError("dependency execution review has open issues")
    residual = review.get("residual_risks")
    if not isinstance(residual, list) or not residual or not all(
        isinstance(item, str) and item.strip() for item in residual
    ):
        raise ValidationError("dependency execution review must retain residual risks")

    snapshot_binding = review.get("snapshot_binding")
    if not isinstance(snapshot_binding, dict):
        raise ValidationError("dependency execution review lacks snapshot_binding")
    _exact_keys(snapshot_binding, REVIEW_BINDING_KEYS, "review snapshot_binding")
    expected_artifact = f"{snapshot_relative}/dependency-snapshot.json"
    expected_binding = {
        "artifact": expected_artifact,
        "sha256": sha256_file(root / expected_artifact),
        "snapshot_id": snapshot["snapshot_id"],
        "dependency_graph_sha256": snapshot["dependency_graph_sha256"],
        "dependency_closure_sha256": snapshot["dependency_closure_sha256"],
    }
    if snapshot_binding != expected_binding:
        raise ValidationError("dependency execution review snapshot binding mismatch")

    checks = review.get("checks")
    if not isinstance(checks, dict):
        raise ValidationError("dependency execution review lacks checks")
    _exact_keys(checks, REVIEW_CHECK_KEYS, "dependency execution review checks")
    failed_checks = sorted(name for name, passed in checks.items() if passed is not True)
    if failed_checks:
        raise ValidationError(
            "dependency execution review has unapproved checks: " + ", ".join(failed_checks)
        )

    package_bindings = snapshot_metadata.get("packages")
    if not isinstance(package_bindings, list):
        raise ValidationError("validated snapshot package metadata is unavailable")
    by_name = {
        item.get("name"): item for item in package_bindings if isinstance(item, dict)
    }
    sidecars = review.get("derived_source_hash_sidecars")
    if not isinstance(sidecars, list):
        raise ValidationError("derived_source_hash_sidecars must be a list")
    if len(sidecars) > DERIVED_SOURCE_HASH_SIDECAR_LIMIT:
        raise ValidationError(
            "derived_source_hash_sidecars exceeds the maximum of "
            f"{DERIVED_SOURCE_HASH_SIDECAR_LIMIT}"
        )
    sidecar_keys: list[tuple[str, str]] = []
    inventories: dict[str, dict[str, dict[str, Any]]] = {}
    residual_text = " ".join(residual).casefold()
    for item in sidecars:
        if not isinstance(item, dict):
            raise ValidationError("derived source hash sidecar review must be an object")
        _exact_keys(
            item,
            DERIVED_SOURCE_HASH_SIDECAR_KEYS,
            "derived source hash sidecar review",
        )
        package_name = item.get("package")
        if not isinstance(package_name, str) or package_name not in by_name:
            raise ValidationError(
                f"derived source hash sidecar names unknown dependency: {package_name!r}"
            )
        source_artifact = _canonical_relative_artifact(
            item.get("source_artifact"),
            "derived source hash sidecar source_artifact",
        )
        trace_artifact = _canonical_relative_artifact(
            item.get("trace_artifact"),
            "derived source hash sidecar trace_artifact",
        )
        if trace_artifact != source_artifact + ".trace":
            raise ValidationError(
                "derived source hash sidecar trace_artifact must exactly equal "
                "source_artifact + '.trace'"
            )
        if item.get("reviewed") is not True:
            raise ValidationError("derived source hash sidecar is not explicitly reviewed")
        if item.get("reason_code") != DERIVED_SOURCE_HASH_SIDECAR_REASON:
            raise ValidationError(
                "derived source hash sidecar reason_code must exactly equal "
                + DERIVED_SOURCE_HASH_SIDECAR_REASON
            )
        justification = item.get("justification")
        justification_text = (
            justification.casefold() if isinstance(justification, str) else ""
        )
        justification_tokens = (
            "lake",
            "rehash",
            "tracked",
            "trace",
            "derived",
            "sidecar",
        )
        if (
            not isinstance(justification, str)
            or len(justification.strip()) < 32
            or len(justification.split()) < 5
            or justification.strip().casefold() in {"none", "n/a", "tbd", "todo"}
            or not all(token in justification_text for token in justification_tokens)
        ):
            raise ValidationError(
                "derived source hash sidecar requires a substantive justification "
                "covering Lake rehash, tracked trace, and derived sidecar semantics"
            )
        if package_name not in inventories:
            inventory = _package_inventory(snapshot_path, by_name[package_name])
            inventories[package_name] = {
                str(entry.get("path")): entry for entry in inventory
            }
        inventory_by_path = inventories[package_name]
        if source_artifact not in inventory_by_path:
            raise ValidationError(
                f"derived source hash sidecar source is not snapshot-bound: "
                f"{package_name}:{source_artifact}"
            )
        if trace_artifact not in inventory_by_path:
            raise ValidationError(
                f"derived source hash sidecar trace is not snapshot-bound: "
                f"{package_name}:{trace_artifact}"
            )
        artifact = source_artifact + ".hash"
        if artifact in inventory_by_path:
            raise ValidationError(
                f"derived source hash sidecar already exists in snapshot: "
                f"{package_name}:{artifact}"
            )
        snapshot_sidecar = snapshot_path / "packages" / package_name
        snapshot_sidecar = snapshot_sidecar.joinpath(*PurePosixPath(artifact).parts)
        ensure_within(snapshot_sidecar, snapshot_path, "derived source hash sidecar")
        if snapshot_sidecar.exists() or snapshot_sidecar.is_symlink():
            raise ValidationError(
                f"derived source hash sidecar is unexpectedly materialized in snapshot: "
                f"{package_name}:{artifact}"
            )
        required_residual_fragments = (
            package_name.casefold(),
            artifact.casefold(),
            "derived",
            "literal",
            "writable",
            "tracked source",
            "read-only",
        )
        matching_residual = any(
            all(fragment in risk.casefold() for fragment in required_residual_fragments)
            and re.search(
                r"\bnot\s+(?:a\s+)?snapshot\s+input\b",
                risk.casefold(),
            )
            is not None
            for risk in residual
        )
        if not matching_residual:
            raise ValidationError(
                "one review residual risk must name each derived source hash sidecar "
                "and state its literal writable exception, tracked-source read-only "
                "boundary, and non-snapshot-input status: "
                f"{package_name}:{artifact}"
            )
        sidecar_keys.append((package_name, source_artifact))
    if sidecar_keys != sorted(sidecar_keys) or len(sidecar_keys) != len(set(sidecar_keys)):
        raise ValidationError(
            "derived_source_hash_sidecars must be unique and sorted by package/source_artifact"
        )
    if any(item.get("gitlink_omissions") for item in by_name.values()):
        if "gitlink" not in residual_text or "unavailable" not in residual_text:
            raise ValidationError(
                "review residual risks must explicitly retain unavailable gitlink risk"
            )
    normalized_packages = sorted(
        str(name)
        for name, item in by_name.items()
        if item.get("symlink_normalizations")
    )
    if normalized_packages:
        if (
            "symlink" not in residual_text
            or "normaliz" not in residual_text
            or not all(name.casefold() in residual_text for name in normalized_packages)
        ):
            raise ValidationError(
                "review residual risks must explicitly retain tracked symlink "
                "normalization semantics for: " + ", ".join(normalized_packages)
            )
    toolchain_mismatches = _package_toolchain_mismatches(
        list(by_name.values()), root_toolchain
    )
    for mismatch in toolchain_mismatches:
        required_fragments = (
            "toolchain",
            str(mismatch["package"]).casefold(),
            str(mismatch["package_toolchain"]).casefold(),
            root_toolchain.casefold(),
        )
        if not all(fragment in residual_text for fragment in required_fragments):
            raise ValidationError(
                "review residual risks must name every package/root toolchain mismatch "
                f"with both exact pins: {mismatch['package']}"
            )
    package_reviews = review.get("package_configuration_reviews")
    if not isinstance(package_reviews, list):
        raise ValidationError("package_configuration_reviews must be a list")
    review_names: list[str] = []
    for item in package_reviews:
        if not isinstance(item, dict):
            raise ValidationError("package configuration review must be an object")
        _exact_keys(item, PACKAGE_REVIEW_KEYS, "package configuration review")
        name = item.get("name")
        if name not in by_name:
            raise ValidationError(f"package review names unknown dependency: {name!r}")
        package = by_name[name]
        expected = {
            "name": name,
            "config_file": package.get("config_file"),
            "config_sha256": package.get("config_sha256"),
            "executable_config": package.get("executable_config"),
            "gitlink_omissions_sha256": package.get("gitlink_omissions_sha256"),
            "gitlink_omissions_reviewed": True,
            "symlink_normalizations_sha256": package.get(
                "symlink_normalizations_sha256"
            ),
            "symlink_normalizations_reviewed": True,
            "toolchain": package.get("toolchain"),
            "root_toolchain_compatibility_reviewed": True,
            "reviewed": True,
            "verdict": "APPROVED",
        }
        if item != expected:
            raise ValidationError(f"package configuration review binding mismatch for {name}")
        review_names.append(str(name))
    if review_names != sorted(by_name):
        raise ValidationError(
            "package configuration reviews must cover every package exactly once in sorted order"
        )
    return review, binding, review_bytes


def _parse_root_lakefile(raw: str) -> dict[str, Any]:
    """Parse the deliberately tiny JSON-compatible TOML subset we authorize."""
    parsed: dict[str, Any] = {}
    current: dict[str, Any] | None = None
    for line_number, raw_line in enumerate(raw.splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[["):
            match = re.fullmatch(r"\[\[(lean_lib|require)\]\]", line)
            if match is None:
                raise ValidationError(
                    f"unsupported root Lake section at line {line_number}: {line}"
                )
            section = match.group(1)
            sections = parsed.setdefault(section, [])
            if not isinstance(sections, list):
                raise ValidationError(f"duplicate incompatible Lake key: {section}")
            current = {}
            sections.append(current)
            continue
        if "=" not in line:
            raise ValidationError(f"invalid root Lake line {line_number}")
        key, encoded = (part.strip() for part in line.split("=", 1))
        destination = parsed if current is None else current
        if key in destination:
            raise ValidationError(f"duplicate root Lake key at line {line_number}: {key}")
        try:
            value = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise ValidationError(
                f"root Lake value must use the canonical string/array subset at line {line_number}"
            ) from exc
        if not isinstance(value, (str, list)) or (
            isinstance(value, list) and not all(isinstance(item, str) for item in value)
        ):
            raise ValidationError(f"unsupported root Lake value at line {line_number}")
        destination[key] = value
    return parsed


def _validate_root_lakefile(path: Path, lake_manifest: Mapping[str, Any]) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValidationError("root lakefile.toml is missing or unsafe")
    try:
        raw = path.read_text(encoding="utf-8")
        parsed = _parse_root_lakefile(raw)
    except (OSError, UnicodeDecodeError) as exc:
        raise ValidationError(f"cannot parse root lakefile.toml: {exc}") from exc
    if LAKEFILE_FORBIDDEN_RE.search(raw):
        raise ValidationError("root lakefile.toml contains a forbidden hook, script, or executable")
    if not isinstance(parsed, dict):
        raise ValidationError("root lakefile.toml must be a table")
    allowed_top = set(LAKEFILE_ALLOWED_TOP_KEYS) | {"lean_lib", "require"}
    unknown_top = sorted(set(parsed) - allowed_top)
    if unknown_top:
        raise ValidationError(f"root lakefile.toml has unsupported keys: {unknown_top}")
    if parsed.get("name") != lake_manifest.get("name"):
        raise ValidationError("root lakefile package name does not match Lake manifest")
    if not isinstance(parsed.get("version"), str) or not parsed["version"].strip():
        raise ValidationError("root lakefile version must be nonempty")
    if parsed.get("defaultTargets") != ["LeanRoomCase"]:
        raise ValidationError("root lakefile defaultTargets must be exactly [\"LeanRoomCase\"]")
    libraries = parsed.get("lean_lib")
    if not isinstance(libraries, list) or len(libraries) != 1:
        raise ValidationError("root lakefile must define exactly one [[lean_lib]]")
    library = libraries[0]
    if not isinstance(library, dict) or set(library) != {"name", "globs"}:
        raise ValidationError(
            "root [[lean_lib]] must contain exactly name and globs; srcDir is forbidden"
        )
    if library != {"name": "LeanRoomCase", "globs": ["LeanRoomCase"]}:
        raise ValidationError(
            "root Lean library must be canonical name=LeanRoomCase, globs=[LeanRoomCase]"
        )

    raw_packages = lake_manifest.get("packages")
    if not isinstance(raw_packages, list):
        raise ValidationError("Lake manifest package list is invalid")
    packages = {item.get("name"): item for item in raw_packages if isinstance(item, dict)}
    requirements = parsed.get("require")
    if not isinstance(requirements, list) or not requirements:
        raise ValidationError("dependency pilot root must declare at least one [[require]]")
    seen: set[str] = set()
    for requirement in requirements:
        if not isinstance(requirement, dict) or set(requirement) != LAKEFILE_ALLOWED_SECTION_KEYS["require"]:
            raise ValidationError("root [[require]] must contain exactly name, git, and rev")
        name = requirement.get("name")
        package = packages.get(name)
        if package is None or name in seen:
            raise ValidationError(f"root [[require]] has unknown or duplicate package {name!r}")
        if requirement.get("git") != package.get("url") or requirement.get("rev") != package.get("rev"):
            raise ValidationError(f"root [[require]] binding mismatch for {name}")
        seen.add(str(name))


def _validate_root_sources(project: Path, inventory: Sequence[Mapping[str, Any]], declaration: str) -> None:
    declared: set[str] = set()
    canonical_declared: set[str] = set()
    lean_files = 0
    for item in inventory:
        relative = item.get("path")
        if not isinstance(relative, str) or not relative.endswith(".lean"):
            continue
        lean_files += 1
        path = project.joinpath(*PurePosixPath(relative).parts)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ValidationError(f"cannot read root Lean source {relative}: {exc}") from exc
        stripped = strip_lean_comments_and_strings(text)
        for label, pattern in FORBIDDEN_PATTERNS:
            if pattern.search(stripped):
                raise ValidationError(f"root Lean source {relative} contains forbidden {label}")
        for line in stripped.splitlines():
            candidate = line.strip()
            if candidate.startswith("import ") and not CANONICAL_IMPORT_RE.fullmatch(candidate):
                raise ValidationError(f"root Lean source {relative} has noncanonical import")
        file_declarations = declared_theorems(text)
        declared.update(file_declarations)
        if relative == "LeanRoomCase.lean":
            canonical_declared.update(file_declarations)
    if lean_files == 0:
        raise ValidationError("dependency pilot root contains no Lean sources")
    if declaration not in canonical_declared:
        location = "another out-of-glob root file" if declaration in declared else "no root source"
        raise ValidationError(
            "requested declaration must be declared specifically in canonical "
            f"LeanRoomCase.lean (found in {location}): {declaration}"
        )


def _project_preflight(
    project: Path,
    project_capture: TreeCapture,
    snapshot: Path,
    snapshot_result: Mapping[str, Any],
    snapshot_metadata: Mapping[str, Any],
    declaration: str,
) -> tuple[dict[str, Any], str, list[dict[str, str]]]:
    file_paths = {str(item.get("path")) for item in project_capture.inventory}
    missing = sorted(ROOT_REQUIRED_FILES - file_paths)
    if missing:
        raise ValidationError(f"canonical dependency pilot project is missing: {missing}")
    if any(PurePosixPath(path).name == "lakefile.lean" for path in file_paths):
        raise ValidationError("root lakefile.lean is forbidden; root configuration must be TOML-only")
    project_manifest_path = project / "lake-manifest.json"
    snapshot_manifest_path = snapshot / "lake-manifest.json"
    if project_manifest_path.read_bytes() != snapshot_manifest_path.read_bytes():
        raise ValidationError("root Lake manifest bytes do not exactly equal snapshot Lake manifest")
    try:
        lake_manifest = validate_lake_manifest(project_manifest_path)
    except SnapshotValidationError as exc:
        raise ValidationError(f"root Lake manifest is invalid: {exc}") from exc
    if lake_manifest.get("name") != snapshot_metadata.get("lake_manifest", {}).get(
        "root_package_name"
    ):
        raise ValidationError("root package name does not match validated snapshot binding")
    _validate_root_lakefile(project / "lakefile.toml", lake_manifest)
    try:
        toolchain = validate_toolchain(
            (project / "lean-toolchain").read_text(encoding="utf-8").strip()
        )
    except (OSError, UnicodeDecodeError) as exc:
        raise ValidationError(f"cannot read root lean-toolchain: {exc}") from exc
    packages = snapshot_metadata.get("packages")
    if not isinstance(packages, list):
        raise ValidationError("validated snapshot package bindings are unavailable")
    if not all(isinstance(package, dict) for package in packages):
        raise ValidationError("validated snapshot package binding is malformed")
    if sorted(snapshot_result.get("packages", [])) != sorted(
        item.get("name") for item in packages
    ):
        raise ValidationError("validated snapshot package authority is internally inconsistent")
    _validate_root_sources(project, project_capture.inventory, declaration)
    return lake_manifest, toolchain, _package_toolchain_mismatches(packages, toolchain)


def _copy_inventory(
    source: Path,
    target: Path,
    inventory: Sequence[Mapping[str, Any]],
    gitlink_omissions: Sequence[Mapping[str, Any]] = (),
    expected_digest: str | None = None,
) -> None:
    if target.exists():
        raise ValidationError(f"disposable copy target already exists: {target}")
    target.mkdir(parents=True)
    for item in inventory:
        relative = item.get("path")
        mode_text = item.get("mode")
        if not isinstance(relative, str) or not isinstance(mode_text, str):
            raise ValidationError("invalid source inventory entry during disposable copy")
        pure = PurePosixPath(relative)
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            raise ValidationError(f"unsafe inventory path during disposable copy: {relative!r}")
        source_file = source.joinpath(*pure.parts)
        target_file = target.joinpath(*pure.parts)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        if source_file.is_symlink() or not source_file.is_file():
            raise ValidationError(f"source changed during disposable copy: {relative}")
        content = source_file.read_bytes()
        if sha256_bytes(content) != item.get("sha256") or len(content) != item.get("size"):
            raise ValidationError(f"source changed during disposable copy: {relative}")
        atomic_write_bytes(target_file, content, int(mode_text, 8))
    for omission in gitlink_omissions:
        relative = omission.get("path")
        if not isinstance(relative, str):
            raise ValidationError("invalid gitlink omission during disposable copy")
        pure = PurePosixPath(relative)
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            raise ValidationError(f"unsafe gitlink omission path: {relative!r}")
        omitted_source = source.joinpath(*pure.parts)
        if omitted_source.is_symlink() or not omitted_source.is_dir():
            raise ValidationError(f"gitlink omission source is not a real directory: {relative}")
        if any(omitted_source.iterdir()):
            raise ValidationError(f"gitlink omission source is not empty: {relative}")
        omitted_target = target.joinpath(*pure.parts)
        try:
            omitted_target.mkdir(parents=True)
        except FileExistsError as exc:
            raise ValidationError(f"gitlink omission collides in disposable copy: {relative}") from exc
    try:
        copied_inventory = scan_source_tree(target)
        copied_digest = dependency_tree_sha256(target, copied_inventory, gitlink_omissions)
        source_digest = dependency_tree_sha256(source, inventory, gitlink_omissions)
    except SnapshotValidationError as exc:
        raise ValidationError(f"disposable source copy is unsafe: {exc}") from exc
    if (
        copied_inventory != list(inventory)
        or copied_digest != source_digest
        or (expected_digest is not None and copied_digest != expected_digest)
    ):
        raise ValidationError("disposable source copy does not equal captured input")


def _package_inventory(snapshot: Path, package: Mapping[str, Any]) -> list[dict[str, Any]]:
    relative = package.get("source_inventory")
    if not isinstance(relative, str):
        raise ValidationError(f"dependency {package.get('name')} lacks source inventory binding")
    path = snapshot.joinpath(*PurePosixPath(relative).parts)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read dependency inventory {relative}: {exc}") from exc
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValidationError(f"dependency inventory {relative} is malformed")
    return [dict(item) for item in value]


def _copy_build_inputs(
    build_root: Path,
    control_root: Path,
    project_capture: TreeCapture,
    snapshot: Path,
    snapshot_metadata: Mapping[str, Any],
    lake_manifest: Mapping[str, Any],
) -> tuple[
    Path,
    Path,
    list[dict[str, Any]],
    dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]],
    dict[str, Path],
]:
    project_copy = build_root / "project"
    _copy_inventory(project_capture.path, project_copy, project_capture.inventory)
    packages_copy = build_root / "packages"
    packages_copy.mkdir()
    metadata_packages = snapshot_metadata.get("packages")
    if not isinstance(metadata_packages, list):
        raise ValidationError("snapshot package metadata is unavailable")
    metadata_by_name = {
        item.get("name"): item for item in metadata_packages if isinstance(item, dict)
    }
    package_captures: dict[
        str, tuple[list[dict[str, Any]], list[dict[str, Any]]]
    ] = {}
    package_build_roots: dict[str, Path] = {}
    overrides: list[dict[str, Any]] = []
    manifest_packages = lake_manifest.get("packages")
    if not isinstance(manifest_packages, list):
        raise ValidationError("root Lake manifest packages are invalid")
    for raw in sorted(manifest_packages, key=lambda item: str(item.get("name"))):
        name = raw.get("name")
        package = metadata_by_name.get(name)
        if not isinstance(name, str) or not isinstance(package, dict):
            raise ValidationError("snapshot and Lake package sets diverged during copy")
        inventory = _package_inventory(snapshot, package)
        omissions_value = package.get("gitlink_omissions")
        if not isinstance(omissions_value, list) or not all(
            isinstance(item, dict) for item in omissions_value
        ):
            raise ValidationError(f"dependency {name} gitlink omissions are malformed")
        omissions = [dict(item) for item in omissions_value]
        package_captures[name] = (inventory, omissions)
        source = snapshot / "packages" / name
        target = packages_copy / name
        _copy_inventory(
            source,
            target,
            inventory,
            omissions,
            str(package.get("source_tree_sha256")),
        )
        subdir = raw.get("subDir")
        package_root = target if subdir is None else target.joinpath(*PurePosixPath(subdir).parts)
        if package_root.is_symlink() or not package_root.is_dir():
            raise ValidationError(f"dependency subdirectory is missing in disposable copy: {name}")
        package_build_roots[name] = package_root
        relative_dir = os.path.relpath(package_root, project_copy).replace(os.sep, "/")
        overrides.append(
            {
                "name": name,
                "scope": raw.get("scope") or "",
                "configFile": raw.get("configFile"),
                "manifestFile": raw.get("manifestFile"),
                "inherited": raw.get("inherited"),
                "type": "path",
                "dir": relative_dir,
            }
        )
    if [item["name"] for item in overrides] != sorted(snapshot_result_name for snapshot_result_name in metadata_by_name):
        raise ValidationError("path overrides do not cover the complete transitive package closure")
    override_path = control_root / "package-overrides.json"
    atomic_write_bytes(
        override_path,
        pretty_json_bytes(
            {
                "schemaVersion": lake_manifest.get("version"),
                "packages": overrides,
            }
        ),
    )
    return (
        project_copy,
        override_path,
        overrides,
        package_captures,
        package_build_roots,
    )


def _precreate_derived_source_hash_sidecars(
    reviewed: Sequence[Mapping[str, Any]],
    package_copy_roots: Mapping[str, Path],
) -> list[DerivedSourceHashSidecar]:
    bindings: list[DerivedSourceHashSidecar] = []
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    for item in reviewed:
        package = str(item["package"])
        source_artifact = str(item["source_artifact"])
        trace_artifact = str(item["trace_artifact"])
        package_root = package_copy_roots.get(package)
        if package_root is None:
            raise ValidationError(
                f"reviewed derived source hash sidecar package was not copied: {package}"
            )
        source = package_root.joinpath(*PurePosixPath(source_artifact).parts)
        trace = package_root.joinpath(*PurePosixPath(trace_artifact).parts)
        for label, path in (("source", source), ("trace", trace)):
            try:
                metadata = path.lstat()
            except OSError as exc:
                raise ValidationError(
                    f"derived source hash sidecar {label} disappeared from copy: "
                    f"{package}:{path.relative_to(package_root).as_posix()}"
                ) from exc
            if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                raise ValidationError(
                    f"derived source hash sidecar {label} is unsafe in copy: "
                    f"{package}:{path.relative_to(package_root).as_posix()}"
                )
        artifact = source_artifact + ".hash"
        path = package_root.joinpath(*PurePosixPath(artifact).parts)
        ensure_within(path, package_root, "derived source hash sidecar copy")
        try:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
                0o600,
            )
        except OSError as exc:
            raise ValidationError(
                f"cannot exclusively precreate derived source hash sidecar: "
                f"{package}:{artifact}: {exc}"
            ) from exc
        try:
            os.fchmod(descriptor, 0o600)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_size != 0
            ):
                raise ValidationError(
                    f"precreated derived source hash sidecar is unsafe: {package}:{artifact}"
                )
        finally:
            os.close(descriptor)
        bindings.append(
            DerivedSourceHashSidecar(
                package,
                source_artifact,
                trace_artifact,
                artifact,
                path,
                metadata.st_dev,
                metadata.st_ino,
            )
        )
    return bindings


def _precreated_sidecar_mutations(
    bindings: Sequence[DerivedSourceHashSidecar],
) -> list[str]:
    mutations: list[str] = []
    for binding in bindings:
        try:
            metadata = binding.path.lstat()
        except OSError:
            mutations.append(
                f"derived-sidecar:{binding.package}:{binding.artifact}:unsafe-or-missing"
            )
            continue
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_dev != binding.precreated_device
            or metadata.st_ino != binding.precreated_inode
        ):
            mutations.append(
                f"derived-sidecar:{binding.package}:{binding.artifact}:identity-or-type-changed"
            )
    return mutations


def _inspect_derived_source_hash_sidecar(
    binding: DerivedSourceHashSidecar,
    *,
    make_read_only: bool,
) -> dict[str, Any]:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        path_metadata = binding.path.lstat()
        descriptor = os.open(binding.path, os.O_RDONLY | nofollow)
    except OSError as exc:
        raise ValidationError(
            f"cannot inspect derived source hash sidecar "
            f"{binding.package}:{binding.artifact}: {exc}"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(path_metadata.st_mode)
            or stat.S_ISLNK(path_metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or path_metadata.st_dev != metadata.st_dev
            or path_metadata.st_ino != metadata.st_ino
            or metadata.st_dev != binding.precreated_device
            or metadata.st_ino != binding.precreated_inode
            or metadata.st_nlink != 1
        ):
            raise ValidationError(
                f"derived source hash sidecar identity or type changed: "
                f"{binding.package}:{binding.artifact}"
            )
        if metadata.st_size != 16:
            raise ValidationError(
                "derived source hash sidecar must be exactly 16 bytes: "
                f"{binding.package}:{binding.artifact}"
            )
        content = os.read(descriptor, 17)
        trailing = os.read(descriptor, 1)
        if len(content) != 16 or trailing:
            raise ValidationError(
                "derived source hash sidecar must be exactly 16 bytes: "
                f"{binding.package}:{binding.artifact}"
            )
        if DERIVED_HASH_RE.fullmatch(content) is None:
            raise ValidationError(
                "derived source hash sidecar must contain exactly 16 lowercase "
                f"hex characters: {binding.package}:{binding.artifact}"
            )
        if make_read_only:
            os.fchmod(descriptor, 0o444)
        final_metadata = os.fstat(descriptor)
        if (
            stat.S_IMODE(final_metadata.st_mode) != 0o444
            or final_metadata.st_size != 16
        ):
            raise ValidationError(
                f"derived source hash sidecar is not read-only: "
                f"{binding.package}:{binding.artifact}"
            )
    finally:
        os.close(descriptor)
    try:
        final_path_metadata = binding.path.lstat()
    except OSError as exc:
        raise ValidationError(
            f"derived source hash sidecar disappeared after inspection: "
            f"{binding.package}:{binding.artifact}"
        ) from exc
    if (
        final_path_metadata.st_dev != binding.precreated_device
        or final_path_metadata.st_ino != binding.precreated_inode
        or final_path_metadata.st_nlink != 1
        or not stat.S_ISREG(final_path_metadata.st_mode)
        or stat.S_ISLNK(final_path_metadata.st_mode)
    ):
        raise ValidationError(
            f"derived source hash sidecar changed during inspection: "
            f"{binding.package}:{binding.artifact}"
        )
    return {
        "package": binding.package,
        "source_artifact": binding.source_artifact,
        "trace_artifact": binding.trace_artifact,
        "artifact": binding.artifact,
        "sha256": sha256_bytes(content),
        "size": len(content),
        "mode": format(stat.S_IMODE(final_path_metadata.st_mode), "04o"),
        "nlink": final_path_metadata.st_nlink,
        "precreated_device": binding.precreated_device,
        "precreated_inode": binding.precreated_inode,
        "final_device": final_path_metadata.st_dev,
        "final_inode": final_path_metadata.st_ino,
        "same_inode_as_precreated": True,
        "content_profile": "lowercase-16-hex-v1",
    }


def _finalize_derived_source_hash_sidecars(
    bindings: Sequence[DerivedSourceHashSidecar],
) -> list[dict[str, Any]]:
    return [
        _inspect_derived_source_hash_sidecar(binding, make_read_only=True)
        for binding in bindings
    ]


def _derived_source_hash_sidecar_mutations(
    bindings: Sequence[DerivedSourceHashSidecar],
    expected: Sequence[Mapping[str, Any]],
) -> list[str]:
    try:
        current = [
            _inspect_derived_source_hash_sidecar(binding, make_read_only=False)
            for binding in bindings
        ]
    except ValidationError:
        return ["derived-source-hash-sidecars:unsafe-or-changed"]
    return (
        []
        if current == list(expected)
        else ["derived-source-hash-sidecars:inventory-changed"]
    )


def _tree_mutations(capture: TreeCapture) -> list[str]:
    try:
        current = _capture_tree(capture.path, capture.artifact, "captured verifier input")
    except ValidationError:
        return [f"{capture.artifact}:unsafe-or-missing"]
    changes: list[str] = []
    if current.digest != capture.digest:
        changes.append(f"{capture.artifact}:tree-digest-changed")
    if current.inventory != capture.inventory:
        changes.append(f"{capture.artifact}:inventory-changed")
    return changes


def _file_mutations(binding: BoundFile) -> list[str]:
    try:
        current_sha = sha256_file(binding.path)
        current_size = binding.path.stat().st_size
    except (OSError, ValidationError):
        return [f"{binding.artifact}:unsafe-or-missing"]
    if current_sha != binding.sha256 or current_size != binding.size:
        return [f"{binding.artifact}:changed"]
    return []


def _snapshot_authority_mutations(
    snapshot: Path, expected: Mapping[str, Any]
) -> list[str]:
    try:
        current = validate_snapshot(snapshot)
    except SnapshotValidationError:
        return ["dependency-snapshot:Phase-A-authority-validation-changed"]
    return [] if current == dict(expected) else ["dependency-snapshot:authority-result-changed"]


def _copy_mutations(
    root: Path,
    inventory: Sequence[Mapping[str, Any]],
    label: str,
    required_empty_directories: Sequence[Mapping[str, Any]] = (),
    allowed_derived_files: Sequence[str] = (),
) -> list[str]:
    expected = {str(item.get("path")): item for item in inventory}
    allowed_derived = set(allowed_derived_files)
    mutations: list[str] = []
    if root.is_symlink() or not root.is_dir():
        return [f"{label}:unsafe-or-missing"]
    seen: set[str] = set()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root)
        if ".lake" in relative.parts:
            continue
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        rendered = relative.as_posix()
        item = expected.get(rendered)
        if item is None and rendered in allowed_derived:
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode) or path.lstat().st_nlink != 1:
                mutations.append(f"{label}:{rendered}:derived-extra-unsafe")
            continue
        if item is None or stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            mutations.append(f"{label}:{rendered}:extra-or-unsafe")
            continue
        seen.add(rendered)
        content = path.read_bytes()
        if (
            format(stat.S_IMODE(mode), "04o") != item.get("mode")
            or len(content) != item.get("size")
            or sha256_bytes(content) != item.get("sha256")
        ):
            mutations.append(f"{label}:{rendered}:changed")
    for missing in sorted(set(expected) - seen):
        mutations.append(f"{label}:{missing}:missing")
    for omission in required_empty_directories:
        relative = omission.get("path")
        if not isinstance(relative, str):
            mutations.append(f"{label}:gitlink-omission-binding-invalid")
            continue
        path = root.joinpath(*PurePosixPath(relative).parts)
        if path.is_symlink() or not path.is_dir():
            mutations.append(f"{label}:{relative}:gitlink-omission-missing-or-unsafe")
            continue
        try:
            entries = list(path.iterdir())
        except OSError:
            mutations.append(f"{label}:{relative}:gitlink-omission-unreadable")
        else:
            if entries:
                mutations.append(f"{label}:{relative}:gitlink-omission-populated")
    return mutations


def _binding(path: Path) -> dict[str, Any]:
    return {"artifact": str(path), "sha256": sha256_file(path), "size": path.stat().st_size}


def resolve_toolchain_runtime(toolchain: str) -> ToolchainRuntime:
    account_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    if not account_home.is_absolute() or account_home.is_symlink():
        raise ValidationError("OS account home is unsafe for pinned toolchain lookup")
    elan_home = account_home / ".elan"
    component = toolchain.replace("/", "--").replace(":", "---")
    toolchain_root = elan_home / "toolchains" / component
    lean = toolchain_root / "bin/lean"
    lake = toolchain_root / "bin/lake"
    sandbox = Path("/usr/bin/sandbox-exec")
    for path in (elan_home, toolchain_root, lean, lake):
        reject_symlink_components(path, account_home)
    if toolchain_root.is_symlink() or not toolchain_root.is_dir():
        raise ValidationError(f"pinned toolchain is not installed locally: {toolchain}")
    bindings: dict[str, dict[str, Any]] = {}
    for name, path in (("lean", lean), ("lake", lake), ("sandbox-exec", sandbox)):
        if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
            raise ValidationError(f"required pinned {name} executable is unavailable or unsafe")
        bindings[name] = _binding(path)
    leanchecker_candidate = toolchain_root / "bin/leanchecker"
    leanchecker: Path | None = None
    if (
        not leanchecker_candidate.is_symlink()
        and leanchecker_candidate.is_file()
        and os.access(leanchecker_candidate, os.X_OK)
    ):
        leanchecker = leanchecker_candidate
        bindings["leanchecker"] = _binding(leanchecker)
    return ToolchainRuntime(
        toolchain,
        toolchain_root,
        elan_home,
        lean,
        lake,
        sandbox,
        leanchecker,
        bindings,
    )


def _environment(build_root: Path, runtime: ToolchainRuntime) -> dict[str, str]:
    home = build_root / "home"
    temporary = build_root / "tmp"
    home.mkdir()
    temporary.mkdir()
    account = pwd.getpwuid(os.getuid())
    return {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(home),
        "USER": account.pw_name,
        "LOGNAME": account.pw_name,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TMPDIR": str(temporary),
        "ELAN_HOME": str(runtime.elan_home),
        "ELAN_TOOLCHAIN": runtime.toolchain,
        "ELAN_AUTO_INSTALL": "0",
        "ELAN_NO_UPDATE_CHECK": "1",
        "LEAN_SYSROOT": str(runtime.toolchain_root),
        "LEAN": str(runtime.lean),
        "LAKE": str(runtime.lake),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ALLOW_PROTOCOL": "file",
        "MATHLIB_NO_CACHE_ON_UPDATE": "1",
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "ALL_PROXY": "",
        "NO_PROXY": "",
    }


def _sandbox_literal(value: Path | str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _path_variants(path: Path) -> set[str]:
    return {str(path), str(path.resolve())}


def pilot_sandbox_profile(
    build_root: Path,
    control_root: Path,
    toolchain_root: Path,
    writable_paths: Sequence[Path],
    extra_read_paths: Sequence[Path] = (),
    *,
    writable_files: Sequence[Path] = (),
    allow_build_executable_mapping: bool = True,
) -> str:
    """Deny-default profile with immutable tracked sources and literal exceptions."""
    build_variants = _path_variants(build_root)
    control_variants = _path_variants(control_root)
    write_values: set[str] = set()
    for path in writable_paths:
        resolved = ensure_within(path, build_root, "pilot sandbox writable path")
        if str(path) in build_variants or str(resolved) in build_variants:
            raise ValidationError("the disposable build root itself cannot be writable")
        if path.is_symlink() or not path.is_dir():
            raise ValidationError(f"pilot writable path is not a real directory: {path}")
        write_values.update(_path_variants(path))
    if write_values & control_variants:
        raise ValidationError("generated pilot controls cannot be writable")
    writable_file_values: set[str] = set()
    for path in writable_files:
        ensure_within(path, build_root, "pilot sandbox writable file")
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise ValidationError(f"pilot writable file is missing: {path}") from exc
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
        ):
            raise ValidationError(f"pilot writable file is not a safe regular file: {path}")
        variants = _path_variants(path)
        if variants & control_variants:
            raise ValidationError("generated pilot controls cannot be writable")
        writable_file_values.update(variants)

    read_values = {
        "/System",
        "/usr",
        "/bin",
        "/sbin",
        "/Library/Apple",
        "/Library/Developer",
        "/private/etc",
        "/dev",
        str(toolchain_root),
        *build_variants,
        *control_variants,
        *(str(path) for path in extra_read_paths),
    }
    metadata_values: set[str] = set()
    for value in read_values:
        candidate = Path(value)
        for ancestor in (candidate, *candidate.parents):
            rendered = str(ancestor)
            if rendered != "/":
                metadata_values.add(rendered)
    executable_values = {
        str(toolchain_root),
        *(str(path) for path in extra_read_paths),
    }
    if allow_build_executable_mapping:
        executable_values.update(build_variants)
    read_rules = " ".join(
        f'(subpath "{_sandbox_literal(path)}")' for path in sorted(read_values)
    )
    metadata_rules = " ".join(
        f'(literal "{_sandbox_literal(path)}")'
        for path in sorted(metadata_values)
    )
    executable_rules = " ".join(
        f'(subpath "{_sandbox_literal(path)}")'
        for path in sorted(executable_values)
    )
    write_rules = " ".join(
        f'(subpath "{_sandbox_literal(path)}")' for path in sorted(write_values)
    )
    writable_file_rules = " ".join(
        f'(literal "{_sandbox_literal(path)}")'
        for path in sorted(writable_file_values)
    )
    writable_file_data_line = (
        f"(allow file-write-data {writable_file_rules})\n"
        if writable_file_rules
        else ""
    )
    return (
        "(version 1)\n"
        "(deny default)\n"
        '(import "system.sb")\n'
        "(allow process*)\n"
        "(allow sysctl-read)\n"
        f"(allow file-read-metadata file-test-existence {metadata_rules})\n"
        f"(allow file-read* file-test-existence {read_rules})\n"
        f"(allow file-map-executable {executable_rules})\n"
        f'(allow file-write* {write_rules} '
        '(literal "/dev/null") (literal "/dev/tty"))\n'
        f"{writable_file_data_line}"
        "(deny network*)\n"
    )


def _validate_output_tree(output_root: Path, owner: str) -> None:
    try:
        root_metadata = output_root.lstat()
    except OSError as exc:
        raise ValidationError(f"missing output tree for {owner}: {output_root}") from exc
    if not stat.S_ISDIR(root_metadata.st_mode) or stat.S_ISLNK(root_metadata.st_mode):
        raise ValidationError(f"unsafe output tree root for {owner}: {output_root}")
    stack = [output_root]
    while stack:
        directory = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise ValidationError(f"cannot inspect output tree for {owner}: {directory}") from exc
        for entry in entries:
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise ValidationError(
                    f"cannot inspect output node for {owner}: {entry.path}"
                ) from exc
            mode = metadata.st_mode
            if stat.S_ISLNK(mode):
                raise ValidationError(
                    f"symlink is forbidden in output tree for {owner}: {entry.path}"
                )
            if stat.S_ISDIR(mode):
                stack.append(Path(entry.path))
                continue
            if not stat.S_ISREG(mode):
                raise ValidationError(
                    f"special node is forbidden in output tree for {owner}: {entry.path}"
                )
            if metadata.st_nlink != 1:
                raise ValidationError(
                    f"hard-linked file is forbidden in output tree for {owner}: {entry.path}"
                )


def _build_artifact_inventory(
    build_project: Path, package_build_roots: Mapping[str, Path]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    roots = [("root", build_project), *sorted(package_build_roots.items())]
    for owner, package_root in roots:
        output_root = package_root / ".lake"
        _validate_output_tree(output_root, owner)
        build = output_root / "build"
        if not build.exists():
            continue
        if build.is_symlink() or not build.is_dir():
            raise ValidationError(f"unsafe build output directory for {owner}")
        for path in sorted(build.rglob("*"), key=lambda item: item.as_posix()):
            if path.suffix not in {".olean", ".ilean"}:
                continue
            if path.is_symlink() or not path.is_file():
                raise ValidationError(f"unsafe Lean build artifact for {owner}: {path}")
            result.append(
                {
                    "owner": owner,
                    "artifact": path.relative_to(package_root).as_posix(),
                    "sha256": sha256_file(path),
                    "size": path.stat().st_size,
                }
            )
    result.sort(key=lambda item: (item["owner"], item["artifact"]))
    return result


def _build_artifact_summary(inventory: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    target = [
        item
        for item in inventory
        if item.get("owner") == "root"
        and item.get("artifact") == ".lake/build/lib/lean/LeanRoomCase.olean"
    ]
    if len(target) != 1:
        raise ValidationError(
            "build did not produce exactly one canonical root LeanRoomCase.olean"
        )
    return {
        "profile": "all-olean-ilean-owner-path-size-sha256-v1",
        "artifact_count": len(inventory),
        "inventory_sha256": sha256_bytes(pretty_json_bytes(list(inventory))),
        "root_target": dict(target[0]),
    }


def _build_artifact_mutations(
    expected: Sequence[Mapping[str, Any]],
    build_project: Path,
    package_build_roots: Mapping[str, Path],
) -> list[str]:
    try:
        current = _build_artifact_inventory(build_project, package_build_roots)
    except ValidationError:
        return ["build-artifacts:unsafe-or-missing"]
    return [] if current == list(expected) else ["build-artifacts:inventory-changed"]


def _run_id(project_digest: str, requested: str | None) -> str:
    if requested is not None:
        return validate_identifier(requested, "pilot run id")
    timestamp = utc_now().replace("-", "").replace(":", "").replace(".", "")
    return validate_identifier(f"PILOT-{timestamp}-{project_digest[:12]}", "pilot run id")


def _validated_timeout(value: Any) -> float:
    if isinstance(value, bool):
        raise ValidationError("timeout must be a finite number in (0, 3600]")
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("timeout must be a finite number in (0, 3600]") from exc
    if not math.isfinite(timeout) or timeout <= 0 or timeout > 3600:
        raise ValidationError("timeout must be a finite number in (0, 3600]")
    return timeout


def _run_target(root: Path, pilot_id: str, run_id: str) -> Path:
    relative = RUNS_RELATIVE / pilot_id / "evidence/runs" / run_id
    target = ensure_within(root / relative, root, "dependency pilot evidence")
    reject_symlink_components(target, root)
    if target.exists() or target.is_symlink():
        raise ValidationError(f"dependency pilot run already exists: {target}")
    return target


def _publish_abort(
    root: Path,
    pilot_id: str,
    run_id: str,
    runner_id: str,
    started_at: str,
    guard: StateGuard,
    failure_summary: str,
) -> Path:
    runs = safe_append_container(root, str(RUNS_RELATIVE / pilot_id / "evidence/runs"))
    stage = Path(tempfile.mkdtemp(prefix=f".{run_id}.stage-", dir=str(runs)))
    target = runs / run_id
    try:
        tombstone = {
            "schema_version": 1,
            "record_type": "lean_dependency_pilot_tombstone",
            "protocol_version": PILOT_PROTOCOL_VERSION,
            "pilot_id": pilot_id,
            "run_id": run_id,
            "runner_id": runner_id,
            "started_at": started_at,
            "finished_at": utc_now(),
            "status": ABORT_STATUS,
            "failure_class": "ROOM_STATE_CHANGED",
            "failure_summary": failure_summary,
            "initial_room_state_bindings": [item.manifest_entry() for item in guard.controls],
            "artifact_policy": "minimal tombstone only; no build outputs retained",
            "certificate_eligible": False,
            "lr_gates_claimed": [],
            "automatic_math_status_change": False,
            "formal_correspondence_established": False,
        }
        atomic_write_json(stage / "pilot_manifest.json", tombstone)
        publish_directory_noreplace(stage, target)
        return target
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def _publish_evidence(
    root: Path,
    pilot_id: str,
    run_id: str,
    guard: StateGuard,
    manifest: dict[str, Any],
    command_results: Sequence[CommandResult],
    project_capture: TreeCapture,
    snapshot_capture: TreeCapture,
    snapshot_result: Mapping[str, Any],
    review_binding: BoundFile,
    review_bytes: bytes,
    control_bindings: Sequence[BoundFile],
    runtime: ToolchainRuntime,
    project_copy: Path,
    package_build_roots: Mapping[str, Path],
    build_artifact_inventory: Sequence[Mapping[str, Any]],
    derived_sidecar_bindings: Sequence[DerivedSourceHashSidecar],
    derived_sidecar_inventory: Sequence[Mapping[str, Any]],
    package_copies: Mapping[
        str,
        tuple[
            Path,
            Sequence[Mapping[str, Any]],
            Sequence[Mapping[str, Any]],
        ],
    ],
    override_bytes: bytes,
    audit_source: bytes,
    build_sandbox_bytes: bytes,
    post_build_sandbox_bytes: bytes,
    axiom_output: bytes,
) -> Path:
    runs = safe_append_container(root, str(RUNS_RELATIVE / pilot_id / "evidence/runs"))
    stage = Path(tempfile.mkdtemp(prefix=f".{run_id}.stage-", dir=str(runs)))
    target = runs / run_id
    try:
        atomic_write_bytes(stage / "package-overrides.json", override_bytes)
        atomic_write_bytes(stage / "declaration_audit.lean", audit_source)
        atomic_write_bytes(stage / "sandbox-build.sb", build_sandbox_bytes)
        atomic_write_bytes(
            stage / "sandbox-post-build.sb", post_build_sandbox_bytes
        )
        atomic_write_bytes(stage / "axioms.txt", axiom_output)
        atomic_write_bytes(stage / "dependency_snapshot_review.json", review_bytes)
        atomic_write_json(stage / "project_inventory.json", list(project_capture.inventory))
        atomic_write_json(stage / "snapshot_inventory.json", list(snapshot_capture.inventory))
        atomic_write_json(
            stage / "build_artifact_inventory.json",
            list(build_artifact_inventory),
        )
        atomic_write_json(
            stage / "derived_source_hash_sidecar_inventory.json",
            list(derived_sidecar_inventory),
        )
        outputs = stage / "command_outputs"
        outputs.mkdir()
        for index, command in enumerate(command_results, start=1):
            atomic_write_bytes(outputs / f"{index:03d}.log", command.output)
        manifest["evidence_artifacts"] = {
            "package_overrides": {
                "artifact": "package-overrides.json",
                "sha256": sha256_file(stage / "package-overrides.json"),
            },
            "declaration_audit": {
                "artifact": "declaration_audit.lean",
                "sha256": sha256_file(stage / "declaration_audit.lean"),
            },
            "build_sandbox_profile": {
                "artifact": "sandbox-build.sb",
                "sha256": sha256_file(stage / "sandbox-build.sb"),
            },
            "post_build_sandbox_profile": {
                "artifact": "sandbox-post-build.sb",
                "sha256": sha256_file(stage / "sandbox-post-build.sb"),
            },
            "axiom_output": {
                "artifact": "axioms.txt",
                "sha256": sha256_file(stage / "axioms.txt"),
            },
            "dependency_snapshot_review": {
                "artifact": "dependency_snapshot_review.json",
                "sha256": sha256_file(stage / "dependency_snapshot_review.json"),
            },
            "build_artifact_inventory": {
                "artifact": "build_artifact_inventory.json",
                "sha256": sha256_file(stage / "build_artifact_inventory.json"),
                "artifact_count": len(build_artifact_inventory),
            },
            "derived_source_hash_sidecar_inventory": {
                "artifact": "derived_source_hash_sidecar_inventory.json",
                "sha256": sha256_file(
                    stage / "derived_source_hash_sidecar_inventory.json"
                ),
                "artifact_count": len(derived_sidecar_inventory),
            },
        }
        atomic_write_json(stage / "pilot_manifest.json", manifest)
        with _locked_state_guard(guard):
            if not guard.matches():
                raise RoomDisabledError("Lean Room state changed before pilot evidence publication")
            mutations: list[str] = []
            mutations.extend(_tree_mutations(project_capture))
            mutations.extend(_tree_mutations(snapshot_capture))
            mutations.extend(
                _snapshot_authority_mutations(snapshot_capture.path, snapshot_result)
            )
            mutations.extend(_file_mutations(review_binding))
            for control in control_bindings:
                mutations.extend(_file_mutations(control))
            mutations.extend(_binary_mutations(runtime.binary_bindings))
            mutations.extend(_precreated_sidecar_mutations(derived_sidecar_bindings))
            if derived_sidecar_inventory:
                mutations.extend(
                    _derived_source_hash_sidecar_mutations(
                        derived_sidecar_bindings,
                        derived_sidecar_inventory,
                    )
                )
            mutations.extend(_copy_mutations(project_copy, project_capture.inventory, "project-copy"))
            if build_artifact_inventory:
                mutations.extend(
                    _build_artifact_mutations(
                        build_artifact_inventory,
                        project_copy,
                        package_build_roots,
                    )
                )
            for name, (path, inventory, omissions) in package_copies.items():
                allowed_sidecars = [
                    binding.artifact
                    for binding in derived_sidecar_bindings
                    if binding.package == name
                ]
                mutations.extend(
                    _copy_mutations(
                        path,
                        inventory,
                        f"package-copy:{name}",
                        omissions,
                        allowed_sidecars,
                    )
                )
            if mutations:
                raise ValidationError(
                    "pilot verifier inputs or disposable sources changed: " + "; ".join(mutations)
                )
            publish_directory_noreplace(stage, target)
        return target
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def verify_pilot(
    args: argparse.Namespace,
    *,
    runner: Runner = run_guarded,
    resolver: Resolver = resolve_toolchain_runtime,
    wrapper: Wrapper = _wrapped,
) -> PilotOutcome:
    timeout = _validated_timeout(args.timeout)
    root = discover_root(args.root)
    initial_status = require_room_enabled(root, "Lean dependency pilot")
    guard = _state_guard(root, initial_status)
    pilot_id = validate_identifier(args.pilot_id, "pilot id")
    runner_id = validate_identifier(args.runner_id, "pilot runner id")
    declaration = validate_lean_name(args.declaration)
    requested_axioms = list(args.permitted_axiom or [])
    if len(requested_axioms) != len(set(requested_axioms)):
        raise ValidationError("--permitted-axiom values must not contain duplicates")
    for axiom in requested_axioms:
        validate_lean_name(axiom, "permitted axiom name")
    permitted_axioms = set(requested_axioms)
    unsupported_axioms = permitted_axioms - set(LEAN_ROOM_V1_ALLOWED_AXIOMS)
    if unsupported_axioms:
        raise ValidationError(
            "permitted axioms exceed the hard standard ceiling: "
            + ", ".join(sorted(unsupported_axioms))
        )
    audit_source = declaration_audit_bytes(declaration, args.exact_type)
    project, project_relative = _safe_root_directory(root, args.project, "pilot project")
    snapshot, snapshot_relative = _safe_root_directory(root, args.snapshot, "dependency snapshot")
    try:
        snapshot_result = validate_snapshot(snapshot)
    except SnapshotValidationError as exc:
        raise ValidationError(f"Phase-A dependency snapshot validation failed: {exc}") from exc
    snapshot_metadata = _load_object(
        snapshot / "dependency-snapshot.json", "dependency snapshot manifest"
    )
    project_capture = _capture_tree(project, project_relative, "pilot project")
    snapshot_capture = _capture_tree(snapshot, snapshot_relative, "dependency snapshot")
    lake_manifest, toolchain, toolchain_mismatches = _project_preflight(
        project,
        project_capture,
        snapshot,
        snapshot_result,
        snapshot_metadata,
        declaration,
    )
    review, review_binding, review_bytes = _review_snapshot(
        root,
        args.review,
        snapshot_relative,
        snapshot,
        snapshot_result,
        snapshot_metadata,
        toolchain,
    )
    run_id = _run_id(project_capture.digest, args.run_id)
    _run_target(root, pilot_id, run_id)
    started_at = utc_now()
    runtime = resolver(toolchain)
    if args.require_leanchecker and runtime.leanchecker is None:
        raise ValidationError(
            "--require-leanchecker was requested but pinned toolchain has no regular executable leanchecker"
        )

    commands: list[CommandResult] = []
    axiom_output = b""
    reported_axioms: set[str] = set()
    status = FAILURE_STATUS
    failure_class: str | None = None
    failure_summary: str | None = None
    exit_code = EXIT_BUILD
    tool_versions: dict[str, str | None] = {"lean": None, "lake": None}
    overrides: list[dict[str, Any]] = []
    build_artifact_inventory: list[dict[str, Any]] = []
    build_artifact_summary: dict[str, Any] | None = None
    derived_sidecar_bindings: list[DerivedSourceHashSidecar] = []
    derived_sidecar_inventory: list[dict[str, Any]] = []
    build_profile = ""
    post_build_profile = ""
    project_copy: Path
    package_copies: dict[
        str,
        tuple[
            Path,
            Sequence[Mapping[str, Any]],
            Sequence[Mapping[str, Any]],
        ],
    ] = {}
    with contextlib.ExitStack() as temporary_stack:
        temporary = temporary_stack.enter_context(
            tempfile.TemporaryDirectory(prefix="lean-dependency-pilot-")
        )
        controls = temporary_stack.enter_context(
            tempfile.TemporaryDirectory(prefix="lean-dependency-pilot-controls-")
        )
        build_root = Path(temporary)
        control_root = Path(controls)
        (
            project_copy,
            override_path,
            overrides,
            package_captures,
            package_build_roots,
        ) = _copy_build_inputs(
            build_root,
            control_root,
            project_capture,
            snapshot,
            snapshot_metadata,
            lake_manifest,
        )
        package_copies = {
            name: (build_root / "packages" / name, inventory, omissions)
            for name, (inventory, omissions) in package_captures.items()
        }
        reviewed_sidecars = review["derived_source_hash_sidecars"]
        derived_sidecar_bindings = _precreate_derived_source_hash_sidecars(
            reviewed_sidecars,
            {name: value[0] for name, value in package_copies.items()},
        )
        audit_path = control_root / "declaration_audit.lean"
        atomic_write_bytes(audit_path, audit_source)
        override_bytes = override_path.read_bytes()
        control_bindings = (
            BoundFile(
                "generated-control:package-overrides.json",
                override_path,
                sha256_bytes(override_bytes),
                len(override_bytes),
            ),
            BoundFile(
                "generated-control:declaration_audit.lean",
                audit_path,
                sha256_bytes(audit_source),
                len(audit_source),
            ),
        )
        environment = _environment(build_root, runtime)
        project_output = project_copy / ".lake"
        project_output.mkdir()
        package_outputs: list[Path] = []
        for name in sorted(package_build_roots):
            output = package_build_roots[name] / ".lake"
            if output.exists() or output.is_symlink():
                raise ValidationError(
                    f"dependency output directory unexpectedly exists before build: {name}"
                )
            output.mkdir()
            package_outputs.append(output)
        extra_tools = [runtime.lean, runtime.lake, runtime.sandbox]
        if runtime.leanchecker is not None:
            extra_tools.append(runtime.leanchecker)
        build_profile = pilot_sandbox_profile(
            build_root,
            control_root,
            runtime.toolchain_root,
            [
                Path(environment["HOME"]),
                Path(environment["TMPDIR"]),
                project_output,
                *package_outputs,
            ],
            extra_tools,
            writable_files=[binding.path for binding in derived_sidecar_bindings],
        )
        post_build_profile = pilot_sandbox_profile(
            build_root,
            control_root,
            runtime.toolchain_root,
            [Path(environment["HOME"]), Path(environment["TMPDIR"])],
            extra_tools,
            allow_build_executable_mapping=False,
        )

        def invoke(
            logical: list[str],
            timeout: float,
            *,
            active_profile: str = build_profile,
            active_environment: Mapping[str, str] = environment,
        ) -> CommandResult:
            before = [
                mutation
                for binding in control_bindings
                for mutation in _file_mutations(binding)
            ]
            before.extend(_precreated_sidecar_mutations(derived_sidecar_bindings))
            if before:
                raise ValidationError(
                    "generated pilot control changed before command: " + "; ".join(before)
                )
            result = runner(
                guard,
                logical,
                wrapper(active_profile, logical),
                project_copy,
                active_environment,
                timeout,
            )
            commands.append(result)
            after = [
                mutation
                for binding in control_bindings
                for mutation in _file_mutations(binding)
            ]
            after.extend(_precreated_sidecar_mutations(derived_sidecar_bindings))
            if after:
                raise ValidationError(
                    "generated pilot control changed during command: " + "; ".join(after)
                )
            return result

        tools_ok = True
        for name, command in (
            ("lean", [str(runtime.lean), "--version"]),
            ("lake", [str(runtime.lake), "--version"]),
        ):
            result = invoke(command, min(timeout, 30.0))
            if result.aborted_room_state:
                return PilotOutcome(
                    ABORT_STATUS,
                    EXIT_DISABLED,
                    _publish_abort(
                        root,
                        pilot_id,
                        run_id,
                        runner_id,
                        started_at,
                        guard,
                        f"Lean Room state changed during {name} version check",
                    ),
                )
            rendered = result.output.decode("utf-8", errors="replace").strip()
            if result.exit_code != 0 or not rendered:
                tools_ok = False
                failure_class = "TOOLCHAIN_VERSION_CHECK_FAILED"
                failure_summary = f"pinned {name} version check failed"
                exit_code = EXIT_VALIDATION
                break
            tool_versions[name] = rendered
        expected_version = toolchain.rsplit("v", 1)[-1]
        if tools_ok and (
            expected_version not in (tool_versions["lean"] or "")
            or expected_version not in (tool_versions["lake"] or "")
        ):
            tools_ok = False
            failure_class = "TOOLCHAIN_VERSION_MISMATCH"
            failure_summary = "Lean/Lake output does not match the exact pinned toolchain"
            exit_code = EXIT_VALIDATION

        packages_option = f"--packages={override_path}"
        offline_flags = ["--rehash", "--reconfigure", "--keep-toolchain", "--no-cache"]
        if tools_ok:
            build_command = [
                str(runtime.lake),
                packages_option,
                *offline_flags,
                "build",
                "LeanRoomCase",
            ]
            result = invoke(build_command, timeout)
            if result.aborted_room_state:
                return PilotOutcome(
                    ABORT_STATUS,
                    EXIT_DISABLED,
                    _publish_abort(
                        root,
                        pilot_id,
                        run_id,
                        runner_id,
                        started_at,
                        guard,
                        "Lean Room state changed during dependency build",
                    ),
                )
            if result.exit_code != 0:
                failure_class = "DEPENDENCY_BUILD_FAILED"
                failure_summary = "pinned offline Lake dependency build failed"
            else:
                derived_sidecar_inventory = (
                    _finalize_derived_source_hash_sidecars(
                        derived_sidecar_bindings
                    )
                )
                build_artifact_inventory = _build_artifact_inventory(
                    project_copy, package_build_roots
                )
                build_artifact_summary = _build_artifact_summary(
                    build_artifact_inventory
                )
                lean_search_paths = [
                    project_copy / ".lake/build/lib/lean",
                    *(
                        package_build_roots[name] / ".lake/build/lib/lean"
                        for name in sorted(package_build_roots)
                    ),
                ]
                lean_search_paths = [
                    path
                    for path in lean_search_paths
                    if path.is_dir() and not path.is_symlink()
                ]
                if not lean_search_paths or lean_search_paths[0] != (
                    project_copy / ".lake/build/lib/lean"
                ):
                    raise ValidationError(
                        "canonical root Lean build search directory is missing"
                    )
                audit_environment = dict(environment)
                audit_environment["LEAN_PATH"] = os.pathsep.join(
                    str(path) for path in lean_search_paths
                )

                def post_build_invoke(logical: list[str]) -> CommandResult:
                    before = _build_artifact_mutations(
                        build_artifact_inventory,
                        project_copy,
                        package_build_roots,
                    )
                    if before:
                        raise ValidationError(
                            "Lean build artifacts changed before post-build audit: "
                            + "; ".join(before)
                        )
                    sidecar_before = _derived_source_hash_sidecar_mutations(
                        derived_sidecar_bindings,
                        derived_sidecar_inventory,
                    )
                    if sidecar_before:
                        raise ValidationError(
                            "derived source hash sidecars changed before post-build audit: "
                            + "; ".join(sidecar_before)
                        )
                    post_result = invoke(
                        logical,
                        timeout,
                        active_profile=post_build_profile,
                        active_environment=audit_environment,
                    )
                    after = _build_artifact_mutations(
                        build_artifact_inventory,
                        project_copy,
                        package_build_roots,
                    )
                    if after:
                        raise ValidationError(
                            "Lean build artifacts changed during post-build audit: "
                            + "; ".join(after)
                        )
                    sidecar_after = _derived_source_hash_sidecar_mutations(
                        derived_sidecar_bindings,
                        derived_sidecar_inventory,
                    )
                    if sidecar_after:
                        raise ValidationError(
                            "derived source hash sidecars changed during post-build audit: "
                            + "; ".join(sidecar_after)
                        )
                    return post_result

                if args.require_leanchecker:
                    assert runtime.leanchecker is not None
                    lake_checker_command = [
                        str(runtime.lake),
                        packages_option,
                        "env",
                        str(runtime.leanchecker),
                        "LeanRoomCase",
                    ]
                    lake_checker = post_build_invoke(lake_checker_command)
                    if lake_checker.aborted_room_state:
                        return PilotOutcome(
                            ABORT_STATUS,
                            EXIT_DISABLED,
                            _publish_abort(
                                root,
                                pilot_id,
                                run_id,
                                runner_id,
                                started_at,
                                guard,
                                "Lean Room state changed during leanchecker audit",
                            ),
                        )
                    if lake_checker.exit_code != 0:
                        failure_class = "LEANCHECKER_FAILED"
                        failure_summary = "required Lake-environment leanchecker audit failed"
                    else:
                        direct_checker_command = [
                            str(runtime.leanchecker),
                            "LeanRoomCase",
                        ]
                        direct_checker = post_build_invoke(direct_checker_command)
                        if direct_checker.aborted_room_state:
                            return PilotOutcome(
                                ABORT_STATUS,
                                EXIT_DISABLED,
                                _publish_abort(
                                    root,
                                    pilot_id,
                                    run_id,
                                    runner_id,
                                    started_at,
                                    guard,
                                    "Lean Room state changed during direct leanchecker audit",
                                ),
                            )
                        if direct_checker.exit_code != 0:
                            failure_class = "LEANCHECKER_FAILED"
                            failure_summary = (
                                "required deterministic-path direct leanchecker audit failed"
                            )
                if failure_class is None:
                    audit_command = [
                        str(runtime.lean),
                        str(audit_path),
                    ]
                    audit = post_build_invoke(audit_command)
                    axiom_output = audit.output
                    if audit.aborted_room_state:
                        return PilotOutcome(
                            ABORT_STATUS,
                            EXIT_DISABLED,
                            _publish_abort(
                                root,
                                pilot_id,
                                run_id,
                                runner_id,
                                started_at,
                                guard,
                                "Lean Room state changed during exact-type/axiom audit",
                            ),
                        )
                    if audit.exit_code != 0:
                        failure_class = "EXACT_TYPE_OR_AXIOM_AUDIT_FAILED"
                        failure_summary = "generated exact-type/axiom audit failed"
                    else:
                        try:
                            reported_axioms = _axioms_from_output(audit.output)
                        except ValidationError as exc:
                            failure_class = "AXIOM_OUTPUT_UNPARSABLE"
                            failure_summary = str(exc)
                        else:
                            unexpected = sorted(reported_axioms - permitted_axioms)
                            if unexpected:
                                failure_class = "UNPERMITTED_AXIOMS"
                                failure_summary = (
                                    "declaration depends on axioms outside the explicit per-run allowlist: "
                                    + ", ".join(unexpected)
                                )
                            else:
                                status = SUCCESS_STATUS
                                exit_code = EXIT_OK

        final_mutations: list[str] = []
        final_mutations.extend(_tree_mutations(project_capture))
        final_mutations.extend(_tree_mutations(snapshot_capture))
        final_mutations.extend(_snapshot_authority_mutations(snapshot, snapshot_result))
        final_mutations.extend(_file_mutations(review_binding))
        for control in control_bindings:
            final_mutations.extend(_file_mutations(control))
        final_mutations.extend(_binary_mutations(runtime.binary_bindings))
        final_mutations.extend(_precreated_sidecar_mutations(derived_sidecar_bindings))
        if derived_sidecar_inventory:
            final_mutations.extend(
                _derived_source_hash_sidecar_mutations(
                    derived_sidecar_bindings,
                    derived_sidecar_inventory,
                )
            )
        if build_artifact_inventory:
            final_mutations.extend(
                _build_artifact_mutations(
                    build_artifact_inventory,
                    project_copy,
                    package_build_roots,
                )
            )
        final_mutations.extend(_copy_mutations(project_copy, project_capture.inventory, "project-copy"))
        for name, (path, inventory, omissions) in package_copies.items():
            allowed_sidecars = [
                binding.artifact
                for binding in derived_sidecar_bindings
                if binding.package == name
            ]
            final_mutations.extend(
                _copy_mutations(
                    path,
                    inventory,
                    f"package-copy:{name}",
                    omissions,
                    allowed_sidecars,
                )
            )
        if final_mutations:
            raise ValidationError(
                "pilot verifier inputs or disposable sources changed: "
                + "; ".join(final_mutations)
            )

        manifest = {
            "schema_version": 1,
            "record_type": "lean_dependency_pilot_run",
            "protocol_version": PILOT_PROTOCOL_VERSION,
            "pilot_id": pilot_id,
            "run_id": run_id,
            "runner_id": runner_id,
            "started_at": started_at,
            "finished_at": utc_now(),
            "status": status,
            "result": "PASS" if status == SUCCESS_STATUS else "FAIL",
            "failure_class": failure_class,
            "failure_summary": failure_summary,
            "certificate_eligible": False,
            "lr_gates_claimed": [],
            "automatic_math_status_change": False,
            "formal_correspondence_established": False,
            "assurance_scope": "offline dependency build plus exact-type and axiom audit only",
            "assurance_limits": [
                "This is an opt-in Phase-B pilot, not a Lean Room certificate.",
                "No LR2, LR3, LR4, LR5, or LR6 gate is established.",
                "The pilot does not establish correspondence to an informal theorem.",
                "Dependency configuration and elaborator code expand the trusted execution boundary.",
                "Reviewed package configuration can still spawn subprocesses (including cache/npm helpers); Seatbelt, timeout, no-cache flags, and MATHLIB_NO_CACHE_ON_UPDATE constrain rather than certify that behavior.",
                "Tracked symlinks are hash-bound normalized regular-file copies, not preserved filesystem symlink semantics; inert binary assets are hash-bound inputs, not executable build products.",
                "Explicitly reviewed source-adjacent .hash sidecars are derived Lake state, not snapshot inputs or mathematical evidence; only their exact precreated files are writable during the build.",
            ],
            "room_state_bindings": [item.manifest_entry() for item in guard.controls],
            "inputs": {
                "project": project_capture.manifest_entry(),
                "snapshot": {
                    **snapshot_capture.manifest_entry(),
                    "snapshot_id": snapshot_result["snapshot_id"],
                    "protocol_version": snapshot_result["protocol_version"],
                    "dependency_graph_sha256": snapshot_result["dependency_graph_sha256"],
                    "dependency_closure_sha256": snapshot_result[
                        "dependency_closure_sha256"
                    ],
                    "packages": snapshot_result["packages"],
                    "gitlink_omissions": [
                        {
                            "package": package.get("name"),
                            "gitlink_omissions_sha256": package.get(
                                "gitlink_omissions_sha256"
                            ),
                            "omissions": package.get("gitlink_omissions"),
                        }
                        for package in snapshot_metadata.get("packages", [])
                        if isinstance(package, dict)
                    ],
                    "symlink_normalizations": [
                        {
                            "package": package.get("name"),
                            "symlink_normalizations_sha256": package.get(
                                "symlink_normalizations_sha256"
                            ),
                            "normalizations": package.get("symlink_normalizations"),
                        }
                        for package in snapshot_metadata.get("packages", [])
                        if isinstance(package, dict)
                    ],
                },
                "review": {
                    **review_binding.manifest_entry(),
                    "review_id": review["review_id"],
                    "verdict": review["verdict"],
                    "phase_b_execution_authorized": True,
                    "derived_source_hash_sidecar_count": len(
                        review["derived_source_hash_sidecars"]
                    ),
                },
                "project_lake_manifest": {
                    "artifact": f"{project_relative}/lake-manifest.json",
                    "sha256": sha256_file(project / "lake-manifest.json"),
                    "exact_bytes_equal_snapshot": True,
                },
                "lean_toolchain": toolchain,
                "package_toolchain_mismatches": toolchain_mismatches,
                "package_toolchain_mismatches_explicitly_reviewed": True,
                "generated_controls": [
                    control.manifest_entry() for control in control_bindings
                ],
                "generated_controls_read_only_under_seatbelt": True,
            },
            "path_overrides": {
                "mode": "generated_all-transitive-package-path-overrides",
                "package_count": len(overrides),
                "packages": [item["name"] for item in overrides],
                "sha256": sha256_bytes(override_bytes),
            },
            "derived_source_hash_sidecars": {
                "mode": "reviewed-precreated-source-adjacent-lake-rehash-sidecars",
                "reviewed_entries": review["derived_source_hash_sidecars"],
                "reviewed_count": len(review["derived_source_hash_sidecars"]),
                "artifact_count": len(derived_sidecar_inventory),
                "inventory_profile": (
                    "package-source-trace-artifact-size-sha256-mode-inode-v1"
                ),
                "inventory_sha256": sha256_bytes(
                    pretty_json_bytes(derived_sidecar_inventory)
                ),
                "same_precreated_inode_required": True,
                "lowercase_16_hex_content_required": True,
                "made_read_only_before_post_build_audits": (
                    len(derived_sidecar_inventory)
                    == len(derived_sidecar_bindings)
                ),
            },
            "sandbox": {
                "profile_id": PILOT_SANDBOX_PROFILE_ID,
                "deny_default": True,
                "network_denied": True,
                "writes_limited_to_output_lake_home_tmp_directories": not bool(
                    derived_sidecar_bindings
                ),
                "writes_limited_to_output_lake_home_tmp_and_reviewed_literal_sidecars": True,
                "copied_project_and_dependency_sources_read_only": not bool(
                    derived_sidecar_bindings
                ),
                "copied_tracked_project_and_dependency_sources_read_only": True,
                "reviewed_derived_source_sidecars_literal_write_only": True,
                "reviewed_literal_sidecar_write_operation": "file-write-data",
                "reviewed_literal_sidecars": [
                    {
                        "package": binding.package,
                        "artifact": binding.artifact,
                    }
                    for binding in derived_sidecar_bindings
                ],
                "generated_controls_read_only": True,
                "build_profile_sha256": sha256_bytes(
                    build_profile.encode("utf-8")
                ),
                "post_build_profile_sha256": sha256_bytes(
                    post_build_profile.encode("utf-8")
                ),
                "post_build_lake_outputs_read_only": True,
                "post_build_executable_mapping_restricted_to_pinned_tools": True,
                "post_build_lake_configuration_reexecuted_for_required_checker": bool(
                    args.require_leanchecker
                ),
                "kernel_exact_type_axiom_audit_reexecutes_lake_configuration": False,
                "post_build_lean_path_mode": "deterministic-copied-build-roots",
                "environment_controls": {
                    "elan_auto_install": False,
                    "elan_update_check": False,
                    "git_protocol_allowlist": ["file"],
                    "proxy_variables_cleared": True,
                    "mathlib_no_cache_on_update": True,
                },
            },
            "tool_binaries": dict(runtime.binary_bindings),
            "tool_versions": tool_versions,
            "leanchecker": {
                "required": bool(args.require_leanchecker),
                "available_and_bound": runtime.leanchecker is not None,
                "executed": bool(
                    args.require_leanchecker
                    and any(
                        any(Path(argument).name == "leanchecker" for argument in item.logical_argv)
                        for item in commands
                    )
                ),
                "lake_environment_command_executed": bool(
                    args.require_leanchecker
                    and any(
                        Path(item.logical_argv[0]).name == "lake"
                        and any(
                            Path(argument).name == "leanchecker"
                            for argument in item.logical_argv
                        )
                        for item in commands
                    )
                ),
                "deterministic_path_direct_command_executed": bool(
                    args.require_leanchecker
                    and any(
                        Path(item.logical_argv[0]).name == "leanchecker"
                        for item in commands
                    )
                ),
            },
            "commands": [item.manifest_entry() for item in commands],
            "reported_axioms": sorted(reported_axioms),
            "permitted_axioms": sorted(permitted_axioms),
            "hard_standard_axiom_ceiling": sorted(LEAN_ROOM_V1_ALLOWED_AXIOMS),
            "build_artifacts": build_artifact_summary,
            "input_mutations_detected": [],
            "evidence_artifacts": {},
        }
        try:
            evidence = _publish_evidence(
                root,
                pilot_id,
                run_id,
                guard,
                manifest,
                commands,
                project_capture,
                snapshot_capture,
                snapshot_result,
                review_binding,
                review_bytes,
                control_bindings,
                runtime,
                project_copy,
                package_build_roots,
                build_artifact_inventory,
                derived_sidecar_bindings,
                derived_sidecar_inventory,
                package_copies,
                override_bytes,
                audit_source,
                build_profile.encode("utf-8"),
                post_build_profile.encode("utf-8"),
                axiom_output,
            )
        except RoomDisabledError as exc:
            evidence = _publish_abort(
                root,
                pilot_id,
                run_id,
                runner_id,
                started_at,
                guard,
                str(exc),
            )
            return PilotOutcome(ABORT_STATUS, EXIT_DISABLED, evidence)
    return PilotOutcome(status, exit_code, evidence)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run an explicitly reviewed Lean dependency build pilot. "
            "Success is PILOT_VERIFIED_NOT_CERTIFIED and never a Lean Room certificate."
        )
    )
    parser.add_argument("--root", help="laboratory root")
    parser.add_argument("--pilot-id", required=True, help="append-only pilot identifier")
    parser.add_argument(
        "--runner-id",
        required=True,
        help="identity of the actor/operator authorizing this concrete run",
    )
    parser.add_argument("--project", required=True, help="root-relative canonical LeanRoomCase project")
    parser.add_argument("--snapshot", required=True, help="root-relative Phase-A source snapshot")
    parser.add_argument(
        "--review",
        required=True,
        help="root-relative approved dependency_snapshot_review artifact",
    )
    parser.add_argument("--declaration", required=True, help="qualified theorem/lemma name")
    parser.add_argument("--exact-type", required=True, help="exact expected Lean type")
    parser.add_argument(
        "--permitted-axiom",
        action="append",
        default=[],
        help=(
            "repeatable explicit per-run axiom allowance; each value must be one of "
            "propext, Classical.choice, Quot.sound (default: none)"
        ),
    )
    parser.add_argument("--run-id", help="optional append-only run identifier")
    parser.add_argument("--timeout", type=float, default=600.0, help="per-command timeout seconds")
    parser.add_argument(
        "--require-leanchecker",
        action="store_true",
        help="require and run pinned-toolchain bin/leanchecker after the Lake build",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON result")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        outcome = verify_pilot(args)
    except LeanRoomError as exc:
        failure_status = (
            ABORT_STATUS if isinstance(exc, RoomDisabledError) else FAILURE_STATUS
        )
        payload = {"ok": False, "error": str(exc), "status": failure_status}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code
    payload = {
        "ok": outcome.exit_code == EXIT_OK,
        "status": outcome.status,
        "certificate_eligible": False,
        "evidence": str(outcome.evidence_path) if outcome.evidence_path else None,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"{outcome.status}: {outcome.evidence_path}")
    return outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
