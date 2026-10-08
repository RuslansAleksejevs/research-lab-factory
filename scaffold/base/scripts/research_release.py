#!/usr/bin/env python3
"""Deterministic local materialization of one reviewed research export.

Research Artifact Release v1 is deliberately narrow.  It copies exact bytes
already selected by a human-reviewed repository-first export into an immutable
local ZIP.  It does not compile, execute, publish, contact a network, invoke
Git, or change mathematical status.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import io
import json
import os
import re
import secrets
import stat
import struct
import sys
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]

SCHEMA_VERSION = 1
POLICY_ID = "research-artifact-release-v1"
MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_PROFILE_BYTES = 512 * 1024
MAX_EXPORT_MANIFEST_BYTES = 512 * 1024
MAX_GITIGNORE_BYTES = 256 * 1024
MAX_GENERATED_MEMBER_BYTES = 8 * 1024 * 1024
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_BYTES = 640 * 1024 * 1024
MAX_FILES = 256
MAX_TEXT = 16_384
MAX_SHORT_TEXT = 1_024
MAX_PATH = 512
MAX_ZIP_MEMBER_PATH = 1_024
MAX_PORTABLE_COMPONENT_BYTES = 255
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
RELEASE_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,94}[a-z0-9])?$")
RELEASE_VERSION_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._]{0,94}[a-z0-9])?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

EVIDENCE_PREFIXES = (
    "problems/",
    "research/checkpoints/",
    "results/",
    "sources/",
    "formalization/",
    "runs/reports/",
    "decisions/",
    "paper/",
    "talks/",
    "knowledge/",
)
WINDOWS_INVALID_CHARACTERS = frozenset('<>:"|?*')
WINDOWS_RESERVED_BASENAMES = frozenset(
    {
        "aux",
        "clock$",
        "con",
        "conin$",
        "conout$",
        "nul",
        "prn",
        *(f"com{suffix}" for suffix in "123456789¹²³"),
        *(f"lpt{suffix}" for suffix in "123456789¹²³"),
    }
)

AUDIENCES = ("PRIVATE_REVIEW", "COAUTHOR", "SHAREABLE", "PUBLIC")
COMPONENTS = (
    "MANUSCRIPT",
    "CLAIMS",
    "VERIFICATION",
    "SOURCES",
    "REPRODUCIBILITY",
    "CODE",
    "COMPUTATIONS",
    "FORMALIZATION",
    "CONTRIBUTIONS",
    "REVISIONS",
)
COMPONENT_STATUSES = ("INCLUDED", "NOT_APPLICABLE", "OMITTED_REVIEWED")
ROLE_COMPONENT = {
    "MANUSCRIPT_SOURCE": "MANUSCRIPT",
    "COMPILED_MANUSCRIPT": "MANUSCRIPT",
    "CLAIM_STATEMENT": "CLAIMS",
    "CLAIM_MAP": "CLAIMS",
    "CHECKPOINT": "CLAIMS",
    "VERIFICATION_REPORT": "VERIFICATION",
    "SOURCE_RECORD": "SOURCES",
    "BIBLIOGRAPHY": "SOURCES",
    "REPRODUCIBILITY_GUIDE": "REPRODUCIBILITY",
    "ENVIRONMENT_LOCK": "REPRODUCIBILITY",
    "SOURCE_CODE": "CODE",
    "COMPUTATION_INPUT": "COMPUTATIONS",
    "COMPUTATION_OUTPUT": "COMPUTATIONS",
    "FORMALIZATION_SOURCE": "FORMALIZATION",
    "FORMALIZATION_ARTIFACT": "FORMALIZATION",
    "CONTRIBUTION_RECORD": "CONTRIBUTIONS",
    "REVISION_HISTORY": "REVISIONS",
}

REQUEST_KEYS = {
    "schema_version",
    "record_type",
    "release_id",
    "release_version",
    "title",
    "purpose",
    "audience",
    "source_export_manifest_path",
    "source_export_manifest_sha256",
    "disclosure_review",
    "file_mappings",
    "component_declarations",
    "no_outbound_action",
    "automatic_claim_promotion",
}
EXPORT_KEYS = {
    "schema_version",
    "record_type",
    "export_id",
    "created_at_utc",
    "package_root",
    "purpose",
    "claim_ids",
    "claim_bindings",
    "source_checkpoint_paths",
    "review",
    "included_files",
    "exclusions",
    "no_outbound_action",
    "automatic_claim_promotion",
    "manifest_payload_sha256",
}
PACKAGE_KEYS = {
    "schema_version",
    "record_type",
    "release_id",
    "release_version",
    "title",
    "purpose",
    "audience",
    "request_payload_sha256",
    "source_export",
    "disclosure_review",
    "claim_ids",
    "claim_bindings",
    "source_checkpoint_paths",
    "files",
    "components",
    "archive_contract",
    "exclusions",
    "no_outbound_action",
    "automatic_claim_promotion",
    "manifest_payload_sha256",
}


class ResearchReleaseError(RuntimeError):
    """A bounded release contract or filesystem invariant failed."""


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            separators=(",", ": "),
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def strict_json_loads(text: str, label: str = "JSON") -> Any:
    duplicates: list[str] = []

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                duplicates.append(key)
            result[key] = value
        return result

    try:
        value = json.loads(text, object_pairs_hook=pairs)
    except json.JSONDecodeError as exc:
        raise ResearchReleaseError(f"{label} is not valid JSON: {exc}") from exc
    if duplicates:
        raise ResearchReleaseError(
            f"{label} contains duplicate JSON keys: {', '.join(sorted(set(duplicates)))}"
        )
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ResearchReleaseError(f"{label} must be an object")
    return value


def _exact(value: Any, label: str, keys: Iterable[str]) -> dict[str, Any]:
    item = _object(value, label)
    expected = set(keys)
    missing = sorted(expected - set(item))
    extra = sorted(set(item) - expected)
    if missing:
        raise ResearchReleaseError(f"{label} is missing keys: {', '.join(missing)}")
    if extra:
        raise ResearchReleaseError(f"{label} has unknown keys: {', '.join(extra)}")
    return item


def _array(
    value: Any,
    label: str,
    maximum: int,
    *,
    minimum: int = 1,
) -> list[Any]:
    if not isinstance(value, list):
        raise ResearchReleaseError(f"{label} must be an array")
    if len(value) < minimum or len(value) > maximum:
        raise ResearchReleaseError(
            f"{label} must contain between {minimum} and {maximum} items"
        )
    return value


def _text(
    value: Any,
    label: str,
    maximum: int = MAX_TEXT,
    *,
    one_line: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ResearchReleaseError(f"{label} must be a string")
    if not value or value != value.strip():
        raise ResearchReleaseError(
            f"{label} must be non-empty without surrounding whitespace"
        )
    if unicodedata.normalize("NFC", value) != value:
        raise ResearchReleaseError(f"{label} must use NFC Unicode")
    if one_line and any(character in value for character in "\r\n\t"):
        raise ResearchReleaseError(f"{label} must be one line")
    for character in value:
        codepoint = ord(character)
        if (
            codepoint == 0x7F
            or 0xD800 <= codepoint <= 0xDFFF
            or (codepoint < 0x20 and character not in "\n\t")
        ):
            raise ResearchReleaseError(f"{label} contains a forbidden character")
    if len(value) > maximum or len(value.encode("utf-8")) > maximum * 4:
        raise ResearchReleaseError(f"{label} exceeds its size bound")
    return value


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or ID_RE.fullmatch(value) is None:
        raise ResearchReleaseError(f"{label} must be a safe identifier")
    return value


def _schema_version(value: Any, label: str) -> int:
    if type(value) is not int or value != SCHEMA_VERSION:
        raise ResearchReleaseError(f"{label} must be integer {SCHEMA_VERSION}")
    return value


def _portable_component(value: str, label: str) -> str:
    if not value or value in {".", ".."}:
        raise ResearchReleaseError(f"{label} contains an unsafe path component")
    if len(value.encode("utf-8")) > MAX_PORTABLE_COMPONENT_BYTES:
        raise ResearchReleaseError(
            f"{label} path component exceeds {MAX_PORTABLE_COMPONENT_BYTES} UTF-8 bytes"
        )
    if value.endswith((".", " ")):
        raise ResearchReleaseError(
            f"{label} path component must not end in a dot or space"
        )
    if any(
        character in WINDOWS_INVALID_CHARACTERS
        or character in {"/", "\\"}
        or unicodedata.category(character) in {"Cc", "Cs"}
        for character in value
    ):
        raise ResearchReleaseError(
            f"{label} path component contains a non-portable character"
        )
    device_stem = unicodedata.normalize(
        "NFC",
        unicodedata.normalize("NFKC", value).casefold(),
    ).split(".", 1)[0]
    if device_stem in WINDOWS_RESERVED_BASENAMES:
        raise ResearchReleaseError(
            f"{label} path component is a reserved DOS device name"
        )
    return value


def _release_id(value: Any, label: str = "release_id") -> str:
    if not isinstance(value, str) or RELEASE_ID_RE.fullmatch(value) is None:
        raise ResearchReleaseError(
            f"{label} must be a lowercase portable release identifier"
        )
    return _portable_component(value, label)


def _release_version(value: Any, label: str = "release_version") -> str:
    if not isinstance(value, str) or RELEASE_VERSION_RE.fullmatch(value) is None:
        raise ResearchReleaseError(
            f"{label} must be a lowercase portable version without hyphens"
        )
    return _portable_component(value, label)


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ResearchReleaseError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or TIMESTAMP_RE.fullmatch(value) is None:
        raise ResearchReleaseError(f"{label} must be an exact UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ResearchReleaseError(f"{label} is not a real UTC timestamp") from exc
    return value


def _enum(value: Any, label: str, choices: Sequence[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ResearchReleaseError(
            f"{label} must be one of: {', '.join(choices)}"
        )
    return value


def _bool(value: Any, label: str, expected: bool) -> bool:
    if not isinstance(value, bool) or value is not expected:
        raise ResearchReleaseError(f"{label} must be {str(expected).lower()}")
    return value


def _relpath(
    value: Any,
    label: str,
    *,
    maximum: int = MAX_PATH,
) -> str:
    if not isinstance(value, str):
        raise ResearchReleaseError(f"{label} must be a relative POSIX path")
    _text(value, label, maximum, one_line=True)
    if len(value.encode("utf-8")) > maximum:
        raise ResearchReleaseError(f"{label} exceeds {maximum} UTF-8 bytes")
    if value.startswith("/") or "\\" in value or "//" in value:
        raise ResearchReleaseError(f"{label} must be a normalized relative POSIX path")
    path = PurePosixPath(value)
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ResearchReleaseError(f"{label} is an unsafe relative path")
    if path.as_posix() != value:
        raise ResearchReleaseError(f"{label} is not a normalized relative path")
    if any(part.casefold() == ".git" for part in path.parts):
        raise ResearchReleaseError(f"{label} must not name Git metadata")
    return value


def _portable_relpath(
    value: Any,
    label: str,
    *,
    maximum: int,
) -> str:
    path = _relpath(value, label, maximum=maximum)
    for index, part in enumerate(PurePosixPath(path).parts):
        _portable_component(part, f"{label} component[{index}]")
    return path


def _portable_key(path: str) -> tuple[str, ...]:
    return tuple(
        unicodedata.normalize(
            "NFC",
            unicodedata.normalize("NFKC", part).casefold(),
        )
        for part in PurePosixPath(path).parts
    )


def _validate_portable_topology(paths: Sequence[str], label: str) -> None:
    keyed: dict[tuple[str, ...], str] = {}
    for path in paths:
        key = _portable_key(path)
        previous = keyed.get(key)
        if previous is not None:
            raise ResearchReleaseError(
                f"{label} contains a casefold/NFC collision: {previous} and {path}"
            )
        keyed[key] = path
    for key, path in keyed.items():
        for depth in range(1, len(key)):
            ancestor = keyed.get(key[:depth])
            if ancestor is not None:
                raise ResearchReleaseError(
                    f"{label} contains an ancestor/descendant conflict: "
                    f"{ancestor} and {path}"
                )


def _package_path(value: Any, label: str) -> str:
    path = _portable_relpath(value, label, maximum=MAX_PATH)
    if path.casefold() in {"readme.md", "manifest.json"}:
        raise ResearchReleaseError(f"{label} uses a reserved README or manifest path")
    return path


def _zip_member_path(value: Any, label: str) -> str:
    return _portable_relpath(value, label, maximum=MAX_ZIP_MEMBER_PATH)


def _export_manifest_path(value: Any, label: str) -> str:
    path = _relpath(value, label)
    parts = PurePosixPath(path).parts
    if (
        len(parts) != 5
        or parts[:3] != ("research", "repository_first", "exports")
        or not ID_RE.fullmatch(parts[3])
        or parts[4] != "manifest.json"
    ):
        raise ResearchReleaseError(
            f"{label} must name research/repository_first/exports/<id>/manifest.json"
        )
    return path


def _checkpoint_path(value: Any, label: str) -> str:
    path = _relpath(value, label)
    parts = PurePosixPath(path).parts
    if len(parts) != 3 or parts[:2] != ("research", "checkpoints"):
        raise ResearchReleaseError(f"{label} must name a canonical research checkpoint")
    return path


def _evidence_path(value: Any, label: str) -> str:
    path = _relpath(value, label)
    if not any(path.startswith(prefix) for prefix in EVIDENCE_PREFIXES):
        raise ResearchReleaseError(f"{label} is outside the canonical evidence roots")
    return path


def _forbid_source_path(path: str, label: str) -> None:
    folded = path.casefold()
    parts = tuple(part.casefold() for part in PurePosixPath(path).parts)
    if folded.startswith("research/raw_runs/archive/"):
        raise ResearchReleaseError(f"{label} names a forbidden raw-run archive")
    if folded.startswith("research/repository_first/releases/"):
        raise ResearchReleaseError(f"{label} names forbidden release self-input")
    if any(part == ".git" for part in parts):
        raise ResearchReleaseError(f"{label} names forbidden Git metadata")
    if parts and (
        parts[0] == "factory_memory"
        or parts[:3] == ("overlays", "user", "private")
    ):
        raise ResearchReleaseError(f"{label} names forbidden factory-private context")
    credential_markers = {
        ".env",
        ".netrc",
        "credential",
        "credentials",
        "credentials.json",
        "id_ed25519",
        "id_rsa",
        "netrc",
        "password",
        "secret",
        "secrets",
        "secrets.json",
        "token",
        "tokens",
        "tokens.json",
    }
    if any(part in credential_markers or part.startswith(".env.") for part in parts):
        raise ResearchReleaseError(f"{label} names forbidden credential or secret material")
    prompt_markers = (
        "system_prompt",
        "system-prompt",
        "developer_prompt",
        "developer-prompt",
        "hidden_prompt",
        "hidden-prompt",
        "chain_of_thought",
        "chain-of-thought",
        "private_chain",
    )
    if any(marker in folded for marker in prompt_markers):
        raise ResearchReleaseError(f"{label} names forbidden hidden prompt or chain-of-thought material")


def _review(value: Any, label: str) -> dict[str, Any]:
    item = _exact(
        value,
        label,
        {"status", "reviewed_at_utc", "reviewer_role_ids", "scope_note"},
    )
    if item["status"] != "REVIEWED":
        raise ResearchReleaseError(f"{label}.status must be REVIEWED")
    _timestamp(item["reviewed_at_utc"], f"{label}.reviewed_at_utc")
    reviewers = _array(item["reviewer_role_ids"], f"{label}.reviewer_role_ids", 32)
    parsed = [_identifier(value, f"{label}.reviewer_role_ids[{index}]") for index, value in enumerate(reviewers)]
    if len(parsed) != len(set(parsed)):
        raise ResearchReleaseError(f"{label}.reviewer_role_ids contains duplicates")
    _text(item["scope_note"], f"{label}.scope_note")
    return item


def _directory_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _open_root_directory(root: Path, label: str) -> int:
    try:
        descriptor = os.open(root, _directory_flags())
    except OSError as exc:
        raise ResearchReleaseError(f"cannot safely open {label} root: {exc}") from exc
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode):
        os.close(descriptor)
        raise ResearchReleaseError(f"{label} root is not a directory")
    return descriptor


def _open_directory_chain(
    root: Path,
    parts: Sequence[str],
    label: str,
    *,
    allow_missing_final: bool = False,
) -> Optional[int]:
    descriptor = _open_root_directory(root, label)
    try:
        for index, part in enumerate(parts):
            try:
                child = os.open(part, _directory_flags(), dir_fd=descriptor)
            except FileNotFoundError:
                if allow_missing_final and index == len(parts) - 1:
                    os.close(descriptor)
                    return None
                raise
            except OSError as exc:
                raise ResearchReleaseError(
                    f"{label} traverses a symlink or unsafe directory: {part}: {exc}"
                ) from exc
            info = os.fstat(child)
            if not stat.S_ISDIR(info.st_mode):
                os.close(child)
                raise ResearchReleaseError(f"{label} contains a non-directory parent")
            os.close(descriptor)
            descriptor = child
        return descriptor
    except FileNotFoundError as exc:
        os.close(descriptor)
        raise ResearchReleaseError(f"{label} directory does not exist safely") from exc
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _read_regular(
    root: Path,
    relative: str,
    label: str,
    maximum: int,
    *,
    required_mode: Optional[int] = None,
    single_link: bool = True,
) -> bytes:
    relative = _relpath(relative, label)
    parts = PurePosixPath(relative).parts
    parent = _open_directory_chain(root, parts[:-1], label)
    if parent is None:
        raise ResearchReleaseError(f"{label} parent does not exist")
    flags = os.O_RDONLY
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(parts[-1], flags, dir_fd=parent)
    except OSError as exc:
        os.close(parent)
        raise ResearchReleaseError(
            f"cannot safely open {label} as a regular non-symlink file: {exc}"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ResearchReleaseError(f"{label} must be a regular non-symlink file")
        if single_link and opened.st_nlink != 1:
            raise ResearchReleaseError(f"{label} must not be a hardlink")
        if required_mode is not None and stat.S_IMODE(opened.st_mode) != required_mode:
            raise ResearchReleaseError(f"{label} must retain immutable mode {required_mode:04o}")
        if opened.st_size > maximum:
            raise ResearchReleaseError(f"{label} exceeds {maximum} bytes")
        chunks: list[bytes] = []
        count = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - count))
            if not chunk:
                break
            chunks.append(chunk)
            count += len(chunk)
            if count > maximum:
                raise ResearchReleaseError(f"{label} exceeds {maximum} bytes")
        after_fd = os.fstat(descriptor)
        try:
            public = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        except OSError as exc:
            raise ResearchReleaseError(f"{label} disappeared after reading: {exc}") from exc
    finally:
        os.close(descriptor)
        os.close(parent)
    identity = (opened.st_dev, opened.st_ino)
    if (
        (after_fd.st_dev, after_fd.st_ino) != identity
        or (public.st_dev, public.st_ino) != identity
        or after_fd.st_size != count
        or public.st_size != count
    ):
        raise ResearchReleaseError(f"{label} changed while being read")
    if single_link and (after_fd.st_nlink != 1 or public.st_nlink != 1):
        raise ResearchReleaseError(f"{label} hardlink count changed while reading")
    verification_parent = _open_directory_chain(
        root,
        parts[:-1],
        f"{label} public-name verification",
    )
    if verification_parent is None:
        raise ResearchReleaseError(f"{label} public parent disappeared")
    verification_flags = os.O_RDONLY
    if hasattr(os, "O_NONBLOCK"):
        verification_flags |= os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        verification_flags |= os.O_NOFOLLOW
    try:
        try:
            verification_fd = os.open(
                parts[-1], verification_flags, dir_fd=verification_parent
            )
        except OSError as exc:
            raise ResearchReleaseError(
                f"{label} public path became a symlink or unsafe file: {exc}"
            ) from exc
        try:
            verified = os.fstat(verification_fd)
            if (verified.st_dev, verified.st_ino) != identity:
                raise ResearchReleaseError(f"{label} public identity changed after reading")
        finally:
            os.close(verification_fd)
    finally:
        os.close(verification_parent)
    return b"".join(chunks)


def _read_input(root: Path, argument: str) -> Any:
    if argument == "-":
        data = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(data) > MAX_INPUT_BYTES:
            raise ResearchReleaseError("stdin request exceeds its byte bound")
    else:
        data = _read_regular(root, _relpath(argument, "input path"), "input path", MAX_INPUT_BYTES)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResearchReleaseError("release request is not UTF-8") from exc
    return strict_json_loads(text, "release request")


def _safe_owner_id(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    pieces: list[str] = []
    separator = False
    for character in normalized:
        if character.isalnum():
            if separator and pieces:
                pieces.append("-")
            pieces.append(character)
            separator = False
        elif pieces:
            separator = True
    base = "".join(pieces).strip("-")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:10]
    if not base:
        return f"lab-{digest}"
    encoded = base.encode("utf-8")
    if len(encoded) <= 100 and all(ord(character) < 128 for character in base):
        return base
    shortened: list[str] = []
    used = 0
    for character in base:
        size = len(character.encode("utf-8"))
        if used + size > 100:
            break
        shortened.append(character)
        used += size
    return f"{''.join(shortened).rstrip('-') or 'lab'}-{digest}"


def _validate_process_steward(
    profile: dict[str, Any], policy: dict[str, Any]
) -> None:
    steward = _text(
        policy["process_steward"],
        "LAB_PROFILE.json.repository_first.process_steward",
        256,
        one_line=True,
    )
    if any(
        character in {"\u2028", "\u2029"}
        or unicodedata.category(character) == "Cc"
        for character in steward
    ):
        raise ResearchReleaseError("repository_first process_steward must be one line")
    lab = _object(profile.get("lab"), "LAB_PROFILE.json.lab")
    modules_value = lab.get("modules")
    modules = modules_value if isinstance(modules_value, list) else []
    collaboration = lab.get("collaboration")
    if "team_collaboration" in modules:
        collaboration = _object(
            collaboration,
            "LAB_PROFILE.json.lab.collaboration for a team repository-first policy",
        )
        if steward != collaboration.get("steward_id"):
            raise ResearchReleaseError(
                "repository_first process_steward must equal collaboration.steward_id"
            )
        repository = _object(
            collaboration.get("repository"),
            "LAB_PROFILE.json.lab.collaboration.repository",
        )
        if repository.get("visibility") != "PRIVATE":
            raise ResearchReleaseError(
                "repository-first team repository visibility must be PRIVATE"
            )
        return
    owners_value = lab.get("owners")
    owners = owners_value if isinstance(owners_value, list) else []
    allowed = {
        candidate
        for owner in owners
        if isinstance(owner, str)
        for candidate in (owner, _safe_owner_id(owner))
    }
    if steward not in allowed:
        raise ResearchReleaseError(
            "repository_first process_steward must match a solo owner name or normalized id"
        )


def _repository_enabled(root: Path) -> bool:
    data = _read_regular(
        root,
        "LAB_PROFILE.json",
        "LAB_PROFILE.json",
        MAX_PROFILE_BYTES,
    )
    try:
        profile = strict_json_loads(data.decode("utf-8"), "LAB_PROFILE.json")
    except UnicodeDecodeError as exc:
        raise ResearchReleaseError("LAB_PROFILE.json is not UTF-8") from exc
    item = _object(profile, "LAB_PROFILE.json")
    policy = item.get("repository_first")
    if policy is None:
        return False
    policy = _object(policy, "LAB_PROFILE.json.repository_first")
    allowed = {
        "enabled",
        "canonical_repository_visibility",
        "raw_material_policy",
        "export_policy",
        "process_steward",
    }
    unknown = sorted(set(policy) - allowed)
    if unknown:
        raise ResearchReleaseError(
            "LAB_PROFILE.json.repository_first has unknown keys: " + ", ".join(unknown)
        )
    if "enabled" not in policy:
        raise ResearchReleaseError("LAB_PROFILE.json is missing repository_first.enabled")
    enabled = policy["enabled"]
    if not isinstance(enabled, bool):
        raise ResearchReleaseError("LAB_PROFILE.json.repository_first.enabled must be boolean")
    governed = allowed - {"enabled"}
    present = governed & set(policy)
    if not enabled:
        if present:
            raise ResearchReleaseError(
                "disabled repository_first policy must contain only enabled=false"
            )
        return False
    missing = sorted(governed - set(policy))
    if missing:
        raise ResearchReleaseError(
            "enabled repository_first policy is missing: " + ", ".join(missing)
        )
    if policy["canonical_repository_visibility"] != "PRIVATE":
        raise ResearchReleaseError(
            "repository_first canonical_repository_visibility must be PRIVATE"
        )
    if policy["raw_material_policy"] != "LOCAL_UNTRACKED":
        raise ResearchReleaseError(
            "repository_first raw_material_policy must be LOCAL_UNTRACKED"
        )
    if policy["export_policy"] != "REVIEWED_ONLY":
        raise ResearchReleaseError(
            "repository_first export_policy must be REVIEWED_ONLY"
        )
    _validate_process_steward(item, policy)
    return enabled


def _require_raw_archive_ignored(root: Path) -> None:
    data = _read_regular(
        root,
        ".gitignore",
        ".gitignore",
        MAX_GITIGNORE_BYTES,
    )
    try:
        lines = [line.strip() for line in data.decode("utf-8").splitlines()]
    except UnicodeDecodeError as exc:
        raise ResearchReleaseError(".gitignore is not UTF-8") from exc
    if "research/raw_runs/archive/" not in lines or any(
        line.startswith("!research/raw_runs/archive") for line in lines
    ):
        raise ResearchReleaseError("research/raw_runs/archive/ must remain locally ignored")


def validate_request(value: Any) -> dict[str, Any]:
    item = _exact(value, "research release request", REQUEST_KEYS)
    _schema_version(item["schema_version"], "research release request schema_version")
    if item["record_type"] != "research_release_request":
        raise ResearchReleaseError("invalid research release request record_type")
    _release_id(item["release_id"], "release_id")
    _release_version(item["release_version"], "release_version")
    _text(item["title"], "title", MAX_SHORT_TEXT, one_line=True)
    _text(item["purpose"], "purpose")
    audience = _enum(item["audience"], "audience", AUDIENCES)
    _export_manifest_path(item["source_export_manifest_path"], "source_export_manifest_path")
    _sha256(item["source_export_manifest_sha256"], "source_export_manifest_sha256")
    _review(item["disclosure_review"], "disclosure_review")
    _bool(item["no_outbound_action"], "no_outbound_action", True)
    _bool(item["automatic_claim_promotion"], "automatic_claim_promotion", False)

    mappings = _array(item["file_mappings"], "file_mappings", MAX_FILES)
    sources: list[str] = []
    package_paths: list[str] = []
    roles: list[str] = []
    component_paths: dict[str, list[str]] = {component: [] for component in COMPONENTS}
    for index, value in enumerate(mappings):
        mapping = _exact(
            value,
            f"file_mappings[{index}]",
            {"source_path", "package_path", "role", "purpose"},
        )
        source = _relpath(mapping["source_path"], f"file_mappings[{index}].source_path")
        _forbid_source_path(source, f"file_mappings[{index}].source_path")
        package = _package_path(mapping["package_path"], f"file_mappings[{index}].package_path")
        role = _enum(mapping["role"], f"file_mappings[{index}].role", tuple(ROLE_COMPONENT))
        _text(mapping["purpose"], f"file_mappings[{index}].purpose", MAX_SHORT_TEXT, one_line=True)
        sources.append(source)
        package_paths.append(package)
        roles.append(role)
        component_paths[ROLE_COMPONENT[role]].append(package)
    if len(sources) != len(set(sources)):
        raise ResearchReleaseError("file_mappings source paths must be one-to-one and unique")
    if len(package_paths) != len(set(package_paths)) or len({path.casefold() for path in package_paths}) != len(package_paths):
        raise ResearchReleaseError("file_mappings package paths must be unique without case collisions")
    _validate_portable_topology(
        ["README.md", "manifest.json", *package_paths],
        "release package topology",
    )
    if "CLAIM_STATEMENT" not in roles:
        raise ResearchReleaseError("release requires an exact CLAIM_STATEMENT role")
    if "CHECKPOINT" not in roles:
        raise ResearchReleaseError("release requires an exact CHECKPOINT role")
    if audience == "PUBLIC":
        if "MANUSCRIPT_SOURCE" not in roles:
            raise ResearchReleaseError("PUBLIC release requires a reviewed MANUSCRIPT_SOURCE role")
        if "COMPILED_MANUSCRIPT" not in roles:
            raise ResearchReleaseError("PUBLIC release requires a reviewed COMPILED_MANUSCRIPT role")

    declarations = _array(
        item["component_declarations"],
        "component_declarations",
        len(COMPONENTS),
        minimum=len(COMPONENTS),
    )
    seen_components: list[str] = []
    for index, value in enumerate(declarations):
        declaration = _exact(
            value,
            f"component_declarations[{index}]",
            {"component", "status", "paths", "rationale"},
        )
        component = _enum(declaration["component"], f"component_declarations[{index}].component", COMPONENTS)
        status_value = _enum(declaration["status"], f"component_declarations[{index}].status", COMPONENT_STATUSES)
        paths = _array(
            declaration["paths"],
            f"component_declarations[{index}].paths",
            MAX_FILES,
            minimum=0,
        )
        parsed_paths = [_package_path(path, f"component_declarations[{index}].paths[{path_index}]") for path_index, path in enumerate(paths)]
        if len(parsed_paths) != len(set(parsed_paths)):
            raise ResearchReleaseError(f"component {component} paths contain duplicates")
        expected_paths = sorted(component_paths[component])
        if status_value == "INCLUDED":
            if not parsed_paths or declaration["rationale"] is not None:
                raise ResearchReleaseError(f"INCLUDED component {component} needs paths and null rationale")
            if sorted(parsed_paths) != expected_paths:
                raise ResearchReleaseError(f"INCLUDED component {component} paths do not exactly match mapped roles")
        else:
            if parsed_paths:
                raise ResearchReleaseError(f"{status_value} component {component} must have empty paths")
            _text(declaration["rationale"], f"component_declarations[{index}].rationale")
            if expected_paths:
                raise ResearchReleaseError(f"component {component} has mapped paths and must be INCLUDED")
        seen_components.append(component)
    if set(seen_components) != set(COMPONENTS) or len(seen_components) != len(COMPONENTS):
        raise ResearchReleaseError("component_declarations must contain every component exactly once")
    for required in ("MANUSCRIPT", "CLAIMS"):
        declaration = next(value for value in declarations if value["component"] == required)
        if declaration["status"] != "INCLUDED":
            raise ResearchReleaseError(f"required component {required} must be INCLUDED")
    return item


def _claim_binding(value: Any, label: str) -> dict[str, Any]:
    item = _exact(
        value,
        label,
        {
            "claim_id",
            "claim_statement_version",
            "claim_statement_path",
            "claim_statement_sha256",
        },
    )
    _identifier(item["claim_id"], f"{label}.claim_id")
    _text(
        item["claim_statement_version"],
        f"{label}.claim_statement_version",
        MAX_SHORT_TEXT,
        one_line=True,
    )
    path = _evidence_path(
        item["claim_statement_path"],
        f"{label}.claim_statement_path",
    )
    _forbid_source_path(path, f"{label}.claim_statement_path")
    _sha256(item["claim_statement_sha256"], f"{label}.claim_statement_sha256")
    return item


def _load_export(
    root: Path,
    relative: str,
    expected_sha256: str,
) -> tuple[dict[str, Any], dict[str, bytes], dict[str, dict[str, Any]]]:
    relative = _export_manifest_path(relative, "source export manifest path")
    expected_sha256 = _sha256(expected_sha256, "source export manifest SHA-256")
    raw = _read_regular(
        root,
        relative,
        "source export manifest",
        MAX_EXPORT_MANIFEST_BYTES,
        required_mode=0o444,
    )
    if sha256_bytes(raw) != expected_sha256:
        raise ResearchReleaseError("source export manifest SHA-256 does not match")
    try:
        text_value = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResearchReleaseError("source export manifest is not UTF-8") from exc
    manifest = _exact(
        strict_json_loads(text_value, "source export manifest"),
        "source export manifest",
        EXPORT_KEYS,
    )
    if canonical_json_bytes(manifest) != raw:
        raise ResearchReleaseError("source export manifest is not canonical JSON")
    _schema_version(
        manifest["schema_version"],
        "source export manifest schema_version",
    )
    if manifest["record_type"] != "export_package_manifest":
        raise ResearchReleaseError("invalid source export manifest record_type")
    export_id = _identifier(manifest["export_id"], "source export export_id")
    created_at = _timestamp(manifest["created_at_utc"], "source export created_at_utc")
    expected_root = f"research/repository_first/exports/{export_id}"
    if _relpath(manifest["package_root"], "source export package_root") != expected_root:
        raise ResearchReleaseError("source export package_root does not match export_id")
    if relative != f"{expected_root}/manifest.json":
        raise ResearchReleaseError("source export manifest path does not match its export_id")
    _text(manifest["purpose"], "source export purpose")

    claim_ids_value = _array(manifest["claim_ids"], "source export claim_ids", 128)
    claim_ids = [
        _identifier(value, f"source export claim_ids[{index}]")
        for index, value in enumerate(claim_ids_value)
    ]
    if len(claim_ids) != len(set(claim_ids)):
        raise ResearchReleaseError("source export claim_ids contain duplicates")
    bindings_value = _array(manifest["claim_bindings"], "source export claim_bindings", 128)
    bindings = [
        _claim_binding(value, f"source export claim_bindings[{index}]")
        for index, value in enumerate(bindings_value)
    ]
    if [binding["claim_id"] for binding in bindings] != claim_ids:
        raise ResearchReleaseError("source export claim bindings do not exactly match claim_ids")

    checkpoint_values = _array(
        manifest["source_checkpoint_paths"],
        "source export source_checkpoint_paths",
        128,
    )
    checkpoints = [
        _checkpoint_path(value, f"source export source_checkpoint_paths[{index}]")
        for index, value in enumerate(checkpoint_values)
    ]
    if len(checkpoints) != len(set(checkpoints)):
        raise ResearchReleaseError("source export checkpoints contain duplicates")

    review = _review(manifest["review"], "source export review")
    if review["reviewed_at_utc"] > created_at:
        raise ResearchReleaseError("source export review cannot postdate export creation")

    included_values = _array(
        manifest["included_files"], "source export included_files", MAX_FILES
    )
    entry_by_path: dict[str, dict[str, Any]] = {}
    data_by_path: dict[str, bytes] = {}
    total = 0
    for index, value in enumerate(included_values):
        entry = _exact(
            value,
            f"source export included_files[{index}]",
            {"path", "sha256", "bytes", "purpose"},
        )
        path = _relpath(entry["path"], f"source export included_files[{index}].path")
        _forbid_source_path(path, f"source export included_files[{index}].path")
        if path.startswith(expected_root + "/"):
            raise ResearchReleaseError(
                "source export included file names its own package output"
            )
        digest = _sha256(entry["sha256"], f"source export included_files[{index}].sha256")
        size = entry["bytes"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0 or size > MAX_MEMBER_BYTES:
            raise ResearchReleaseError(
                f"source export included_files[{index}].bytes is outside the release bound"
            )
        _text(
            entry["purpose"],
            f"source export included_files[{index}].purpose",
            MAX_SHORT_TEXT,
            one_line=True,
        )
        if path in entry_by_path:
            raise ResearchReleaseError("source export included file paths contain duplicates")
        source = _read_regular(root, path, f"reviewed source file {path}", MAX_MEMBER_BYTES)
        if len(source) != size or sha256_bytes(source) != digest:
            raise ResearchReleaseError(
                f"reviewed source file bytes or SHA-256 do not match export: {path}"
            )
        total += len(source)
        if total > MAX_TOTAL_BYTES:
            raise ResearchReleaseError("reviewed release source set exceeds its total byte bound")
        entry_by_path[path] = entry
        data_by_path[path] = source

    for binding in bindings:
        if entry_by_path.get(binding["claim_statement_path"], {}).get("sha256") != binding["claim_statement_sha256"]:
            raise ResearchReleaseError(
                f"source export claim statement is not exactly included: {binding['claim_id']}"
            )
    for checkpoint in checkpoints:
        # The reviewed-export contract requires existence; Research Artifact
        # Release additionally requires exact inclusion and CHECKPOINT mapping.
        _read_regular(root, checkpoint, f"source export checkpoint {checkpoint}", MAX_MEMBER_BYTES)

    exclusions = _exact(
        manifest["exclusions"],
        "source export exclusions",
        {"raw_archives", "credentials", "hidden_prompts", "chain_of_thought", "outbound_actions"},
    )
    for key, value in exclusions.items():
        _bool(value, f"source export exclusions.{key}", True)
    _bool(manifest["no_outbound_action"], "source export no_outbound_action", True)
    _bool(
        manifest["automatic_claim_promotion"],
        "source export automatic_claim_promotion",
        False,
    )
    payload_digest = _sha256(
        manifest["manifest_payload_sha256"],
        "source export manifest_payload_sha256",
    )
    body = dict(manifest)
    del body["manifest_payload_sha256"]
    if sha256_bytes(canonical_json_bytes(body)) != payload_digest:
        raise ResearchReleaseError("source export manifest payload digest does not match")
    return manifest, data_by_path, entry_by_path


def _release_root(release_id: str, release_version: str) -> str:
    release_id = _release_id(release_id)
    release_version = _release_version(release_version)
    component = f"research-artifact-release-{release_id}-{release_version}"
    _portable_component(component, "release archive root")
    return f"{component}/"


def _release_archive_path(release_id: str, release_version: str) -> str:
    release_id = _release_id(release_id)
    release_version = _release_version(release_version)
    _portable_component(f"{release_version}.zip", "release archive filename")
    return f"research/repository_first/releases/{release_id}/{release_version}.zip"


def _parse_release_archive_path(value: Any, label: str = "release archive path") -> tuple[str, str, str]:
    relative = _relpath(value, label)
    parts = PurePosixPath(relative).parts
    if len(parts) != 5 or parts[:3] != ("research", "repository_first", "releases"):
        raise ResearchReleaseError(
            f"{label} must name research/repository_first/releases/<id>/<version>.zip"
        )
    release_id = _release_id(parts[3], f"{label} release_id")
    if not parts[4].endswith(".zip"):
        raise ResearchReleaseError(f"{label} must end in .zip")
    _portable_component(parts[4], f"{label} filename")
    release_version = _release_version(
        parts[4][:-4],
        f"{label} release_version",
    )
    expected = _release_archive_path(release_id, release_version)
    if relative != expected:
        raise ResearchReleaseError(f"{label} is not canonical")
    return relative, release_id, release_version


def _readme(request: dict[str, Any], files: list[dict[str, Any]]) -> bytes:
    components = {
        declaration["component"]: declaration
        for declaration in request["component_declarations"]
    }
    lines = [
        f"# {request['title']}",
        "",
        f"- Release: `{request['release_id']}` / `{request['release_version']}`",
        f"- Intended audience review label: `{request['audience']}`",
        f"- Purpose: {request['purpose']}",
        "",
        "This is a deterministic local projection of one exact human-reviewed export.",
        "The audience label is not access control, authentication, encryption, hosting,",
        "publication, or evidence that disclosure occurred.",
        "",
        "A valid package does not prove mathematical correctness, novelty, significance,",
        "source accuracy, authorship, human understanding, or successful reproducibility.",
        "The private laboratory, its checkpoints, dossiers, ledgers, and sources remain",
        "canonical. This package cannot promote a mathematical claim.",
        "",
        "## Files",
        "",
        "| Package path | Role | Component | Purpose |",
        "|---|---|---|---|",
    ]
    for entry in files:
        purpose = entry["purpose"].replace("|", "\\|")
        lines.append(
            f"| `{entry['package_path']}` | `{entry['role']}` | `{entry['component']}` | {purpose} |"
        )
    lines.extend(["", "## Component completeness", ""])
    for component in COMPONENTS:
        declaration = components[component]
        suffix = ""
        if declaration["rationale"] is not None:
            suffix = f" — {declaration['rationale']}"
        lines.append(f"- `{component}`: `{declaration['status']}`{suffix}")
    lines.extend(
        [
            "",
            "## Machine verification",
            "",
            "`manifest.json` binds the exact request, reviewed export, claims, checkpoints,",
            "components, roles, source bytes, and archived bytes by SHA-256. The local",
            "validator also rechecks the current source/export preimages and therefore",
            "rejects later drift rather than silently updating this reviewed projection.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def _package_files(
    request: dict[str, Any],
    data_by_path: dict[str, bytes],
    export_entries: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    # Preserve request order so request_payload_sha256 is reconstructible from
    # the package manifest. ZIP member order is independently canonicalized.
    for mapping in request["file_mappings"]:
        source = data_by_path[mapping["source_path"]]
        export_entry = export_entries[mapping["source_path"]]
        digest = sha256_bytes(source)
        result.append(
            {
                "source_path": mapping["source_path"],
                "source_sha256": export_entry["sha256"],
                "source_bytes": export_entry["bytes"],
                "package_path": mapping["package_path"],
                "package_sha256": digest,
                "package_bytes": len(source),
                "role": mapping["role"],
                "component": ROLE_COMPONENT[mapping["role"]],
                "purpose": mapping["purpose"],
            }
        )
    return result


def _verify_request_against_export(
    request: dict[str, Any],
    export: dict[str, Any],
    export_entries: dict[str, dict[str, Any]],
) -> None:
    mapping_sources = [mapping["source_path"] for mapping in request["file_mappings"]]
    if len(mapping_sources) != len(export_entries) or set(mapping_sources) != set(export_entries):
        raise ResearchReleaseError(
            "release file mappings must map every reviewed export file exactly one-to-one"
        )
    mapping_by_source = {
        mapping["source_path"]: mapping for mapping in request["file_mappings"]
    }
    for binding in export["claim_bindings"]:
        mapping = mapping_by_source.get(binding["claim_statement_path"])
        if mapping is None or mapping["role"] != "CLAIM_STATEMENT":
            raise ResearchReleaseError(
                f"claim {binding['claim_id']} requires an exact CLAIM_STATEMENT role"
            )
    for checkpoint in export["source_checkpoint_paths"]:
        mapping = mapping_by_source.get(checkpoint)
        if mapping is None or mapping["role"] != "CHECKPOINT":
            raise ResearchReleaseError(
                f"reviewed checkpoint {checkpoint} must be included with CHECKPOINT role"
            )
    if request["disclosure_review"]["reviewed_at_utc"] < export["created_at_utc"]:
        raise ResearchReleaseError("release disclosure review cannot predate the reviewed export")


def _manifest_for_build(
    request: dict[str, Any],
    export: dict[str, Any],
    files: list[dict[str, Any]],
    readme: bytes,
) -> dict[str, Any]:
    root_prefix = _release_root(request["release_id"], request["release_version"])
    member_order = sorted(
        [
            f"{root_prefix}README.md",
            f"{root_prefix}manifest.json",
            *(f"{root_prefix}{entry['package_path']}" for entry in files),
        ]
    )
    for index, member_name in enumerate(member_order):
        _zip_member_path(member_name, f"release ZIP member plan[{index}]")
    _validate_portable_topology(member_order, "release ZIP member plan")
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "research_release_package",
        "release_id": request["release_id"],
        "release_version": request["release_version"],
        "title": request["title"],
        "purpose": request["purpose"],
        "audience": request["audience"],
        "request_payload_sha256": sha256_bytes(canonical_json_bytes(request)),
        "source_export": {
            "path": request["source_export_manifest_path"],
            "sha256": request["source_export_manifest_sha256"],
            "export_id": export["export_id"],
            "created_at_utc": export["created_at_utc"],
            "manifest_payload_sha256": export["manifest_payload_sha256"],
            "review": export["review"],
        },
        "disclosure_review": request["disclosure_review"],
        "claim_ids": export["claim_ids"],
        "claim_bindings": export["claim_bindings"],
        "source_checkpoint_paths": export["source_checkpoint_paths"],
        "files": files,
        "components": request["component_declarations"],
        "archive_contract": {
            "format": "ZIP",
            "compression": "STORED",
            "fixed_timestamp_utc": "1980-01-01T00:00:00Z",
            "member_mode": "0444",
            "root_prefix": root_prefix,
            "member_order": member_order,
            "readme_sha256": sha256_bytes(readme),
            "readme_bytes": len(readme),
        },
        "exclusions": {
            "raw_archives": True,
            "credentials": True,
            "hidden_prompts": True,
            "chain_of_thought": True,
            "git_metadata": True,
            "factory_private_context": True,
            "release_self_input": True,
            "builder_compilation_or_execution": True,
            "outbound_actions": True,
        },
        "no_outbound_action": True,
        "automatic_claim_promotion": False,
    }
    manifest["manifest_payload_sha256"] = sha256_bytes(canonical_json_bytes(manifest))
    return manifest


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = (stat.S_IFREG | 0o444) << 16
    info.extra = b""
    info.comment = b""
    return info


def _zip_bytes(
    manifest: dict[str, Any],
    readme: bytes,
    data_by_source: dict[str, bytes],
) -> bytes:
    prefix = manifest["archive_contract"]["root_prefix"]
    manifest_bytes = canonical_json_bytes(manifest)
    if len(readme) > MAX_GENERATED_MEMBER_BYTES:
        raise ResearchReleaseError("release README exceeds its byte bound")
    if len(manifest_bytes) > MAX_GENERATED_MEMBER_BYTES:
        raise ResearchReleaseError("release package manifest exceeds its byte bound")
    planned_members: list[tuple[str, bytes]] = [
        (f"{prefix}README.md", readme),
        (f"{prefix}manifest.json", manifest_bytes),
    ]
    for entry in manifest["files"]:
        planned_members.append(
            (
                f"{prefix}{entry['package_path']}",
                data_by_source[entry["source_path"]],
            )
        )
    names = [name for name, _data in planned_members]
    for index, name in enumerate(names):
        _zip_member_path(name, f"release ZIP member plan[{index}]")
    _validate_portable_topology(names, "release ZIP member plan")
    if len(names) < 3 or len(names) > MAX_FILES + 2:
        raise ResearchReleaseError("release ZIP member count is outside its bound")
    member_data = dict(planned_members)
    if len(member_data) != len(planned_members):
        raise ResearchReleaseError("release ZIP member plan contains duplicates")
    order = manifest["archive_contract"]["member_order"]
    if order != sorted(member_data) or set(order) != set(member_data):
        raise ResearchReleaseError("internal deterministic member order mismatch")
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_STORED,
        allowZip64=False,
    ) as archive:
        for name in order:
            archive.writestr(_zip_info(name), member_data[name])
    data = output.getvalue()
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ResearchReleaseError("release archive exceeds its byte bound")
    return data


def _validate_package_manifest(
    value: Any,
    release_id: str,
    release_version: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = _exact(value, "release package manifest", PACKAGE_KEYS)
    _schema_version(
        manifest["schema_version"],
        "release package manifest schema_version",
    )
    if manifest["record_type"] != "research_release_package":
        raise ResearchReleaseError("invalid release package manifest record_type")
    if _release_id(manifest["release_id"], "package release_id") != release_id:
        raise ResearchReleaseError("package release_id does not match archive path")
    if _release_version(
        manifest["release_version"],
        "package release_version",
    ) != release_version:
        raise ResearchReleaseError("package release_version does not match archive path")
    _text(manifest["title"], "package title", MAX_SHORT_TEXT, one_line=True)
    _text(manifest["purpose"], "package purpose")
    _enum(manifest["audience"], "package audience", AUDIENCES)
    _sha256(manifest["request_payload_sha256"], "package request_payload_sha256")
    disclosure_review = _review(manifest["disclosure_review"], "package disclosure_review")

    source_export = _exact(
        manifest["source_export"],
        "package source_export",
        {"path", "sha256", "export_id", "created_at_utc", "manifest_payload_sha256", "review"},
    )
    _export_manifest_path(source_export["path"], "package source_export.path")
    _sha256(source_export["sha256"], "package source_export.sha256")
    _identifier(source_export["export_id"], "package source_export.export_id")
    _timestamp(source_export["created_at_utc"], "package source_export.created_at_utc")
    _sha256(
        source_export["manifest_payload_sha256"],
        "package source_export.manifest_payload_sha256",
    )
    _review(source_export["review"], "package source_export.review")

    claim_ids_values = _array(manifest["claim_ids"], "package claim_ids", 128)
    claim_ids = [
        _identifier(value, f"package claim_ids[{index}]")
        for index, value in enumerate(claim_ids_values)
    ]
    if len(claim_ids) != len(set(claim_ids)):
        raise ResearchReleaseError("package claim_ids contain duplicates")
    binding_values = _array(manifest["claim_bindings"], "package claim_bindings", 128)
    bindings = [
        _claim_binding(value, f"package claim_bindings[{index}]")
        for index, value in enumerate(binding_values)
    ]
    if [binding["claim_id"] for binding in bindings] != claim_ids:
        raise ResearchReleaseError("package claim bindings do not exactly match claim_ids")
    checkpoint_values = _array(
        manifest["source_checkpoint_paths"], "package source_checkpoint_paths", 128
    )
    checkpoints = [
        _checkpoint_path(value, f"package source_checkpoint_paths[{index}]")
        for index, value in enumerate(checkpoint_values)
    ]
    if len(checkpoints) != len(set(checkpoints)):
        raise ResearchReleaseError("package checkpoint paths contain duplicates")

    file_values = _array(manifest["files"], "package files", MAX_FILES)
    files: list[dict[str, Any]] = []
    sources: list[str] = []
    packages: list[str] = []
    for index, value in enumerate(file_values):
        entry = _exact(
            value,
            f"package files[{index}]",
            {
                "source_path",
                "source_sha256",
                "source_bytes",
                "package_path",
                "package_sha256",
                "package_bytes",
                "role",
                "component",
                "purpose",
            },
        )
        source_path = _relpath(entry["source_path"], f"package files[{index}].source_path")
        _forbid_source_path(source_path, f"package files[{index}].source_path")
        package_path = _package_path(entry["package_path"], f"package files[{index}].package_path")
        source_digest = _sha256(entry["source_sha256"], f"package files[{index}].source_sha256")
        package_digest = _sha256(entry["package_sha256"], f"package files[{index}].package_sha256")
        source_size = entry["source_bytes"]
        package_size = entry["package_bytes"]
        for size, size_label in (
            (source_size, "source_bytes"),
            (package_size, "package_bytes"),
        ):
            if isinstance(size, bool) or not isinstance(size, int) or size < 0 or size > MAX_MEMBER_BYTES:
                raise ResearchReleaseError(f"package files[{index}].{size_label} is outside its bound")
        if source_digest != package_digest or source_size != package_size:
            raise ResearchReleaseError(
                f"package file {package_path} is not an exact source-byte copy"
            )
        role = _enum(entry["role"], f"package files[{index}].role", tuple(ROLE_COMPONENT))
        component = _enum(entry["component"], f"package files[{index}].component", COMPONENTS)
        if ROLE_COMPONENT[role] != component:
            raise ResearchReleaseError(f"package file {package_path} role/component mismatch")
        _text(entry["purpose"], f"package files[{index}].purpose", MAX_SHORT_TEXT, one_line=True)
        sources.append(source_path)
        packages.append(package_path)
        files.append(entry)
    if len(sources) != len(set(sources)):
        raise ResearchReleaseError("package source paths are not one-to-one")
    if len(packages) != len(set(packages)) or len({value.casefold() for value in packages}) != len(packages):
        raise ResearchReleaseError("package member paths contain duplicate or case-colliding names")
    _validate_portable_topology(
        ["README.md", "manifest.json", *packages],
        "release package topology",
    )

    component_values = _array(
        manifest["components"],
        "package components",
        len(COMPONENTS),
        minimum=len(COMPONENTS),
    )
    archive_contract = _exact(
        manifest["archive_contract"],
        "package archive_contract",
        {
            "format",
            "compression",
            "fixed_timestamp_utc",
            "member_mode",
            "root_prefix",
            "member_order",
            "readme_sha256",
            "readme_bytes",
        },
    )
    if (
        archive_contract["format"] != "ZIP"
        or archive_contract["compression"] != "STORED"
        or archive_contract["fixed_timestamp_utc"] != "1980-01-01T00:00:00Z"
        or archive_contract["member_mode"] != "0444"
    ):
        raise ResearchReleaseError("package deterministic archive contract is invalid")
    expected_prefix = _release_root(release_id, release_version)
    if archive_contract["root_prefix"] != expected_prefix:
        raise ResearchReleaseError("package archive root prefix is not canonical")
    order_values = _array(
        archive_contract["member_order"],
        "package archive member_order",
        MAX_FILES + 2,
        minimum=3,
    )
    order = [
        _zip_member_path(value, f"package archive member_order[{index}]")
        for index, value in enumerate(order_values)
    ]
    if order != sorted(order) or len(order) != len(set(order)):
        raise ResearchReleaseError("package archive member order is not sorted and unique")
    _validate_portable_topology(order, "package archive member order")
    if any(not value.startswith(expected_prefix) for value in order):
        raise ResearchReleaseError("package archive member escapes its canonical root prefix")
    _sha256(archive_contract["readme_sha256"], "package archive readme_sha256")
    readme_bytes = archive_contract["readme_bytes"]
    if isinstance(readme_bytes, bool) or not isinstance(readme_bytes, int) or readme_bytes < 1 or readme_bytes > MAX_GENERATED_MEMBER_BYTES:
        raise ResearchReleaseError("package archive readme_bytes is outside its bound")

    exclusions = _exact(
        manifest["exclusions"],
        "package exclusions",
        {
            "raw_archives",
            "credentials",
            "hidden_prompts",
            "chain_of_thought",
            "git_metadata",
            "factory_private_context",
            "release_self_input",
            "builder_compilation_or_execution",
            "outbound_actions",
        },
    )
    for key, value in exclusions.items():
        _bool(value, f"package exclusions.{key}", True)
    _bool(manifest["no_outbound_action"], "package no_outbound_action", True)
    _bool(
        manifest["automatic_claim_promotion"],
        "package automatic_claim_promotion",
        False,
    )
    payload_digest = _sha256(
        manifest["manifest_payload_sha256"],
        "package manifest_payload_sha256",
    )
    body = dict(manifest)
    del body["manifest_payload_sha256"]
    if sha256_bytes(canonical_json_bytes(body)) != payload_digest:
        raise ResearchReleaseError("package manifest payload digest does not match")

    reconstructed_request: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "research_release_request",
        "release_id": release_id,
        "release_version": release_version,
        "title": manifest["title"],
        "purpose": manifest["purpose"],
        "audience": manifest["audience"],
        "source_export_manifest_path": source_export["path"],
        "source_export_manifest_sha256": source_export["sha256"],
        "disclosure_review": disclosure_review,
        "file_mappings": [
            {
                "source_path": entry["source_path"],
                "package_path": entry["package_path"],
                "role": entry["role"],
                "purpose": entry["purpose"],
            }
            for entry in files
        ],
        "component_declarations": component_values,
        "no_outbound_action": True,
        "automatic_claim_promotion": False,
    }
    validate_request(reconstructed_request)
    if sha256_bytes(canonical_json_bytes(reconstructed_request)) != manifest["request_payload_sha256"]:
        raise ResearchReleaseError("package request payload SHA-256 does not match")
    return manifest, reconstructed_request


def _preflight_standard_zip(raw: bytes) -> int:
    """Bound a canonical standard ZIP before ``ZipFile`` parses its directory."""

    eocd_size = 22
    if len(raw) < eocd_size:
        raise ResearchReleaseError("release ZIP is missing a standard EOCD record")
    eocd_offset = len(raw) - eocd_size
    try:
        (
            signature,
            disk_number,
            directory_disk,
            entries_on_disk,
            entries_total,
            directory_size,
            directory_offset,
            comment_length,
        ) = struct.unpack_from("<4s4H2LH", raw, eocd_offset)
    except struct.error as exc:
        raise ResearchReleaseError("release ZIP EOCD record is truncated") from exc
    if signature != b"PK\x05\x06" or comment_length != 0:
        raise ResearchReleaseError(
            "release ZIP must end in an uncommented standard EOCD record"
        )
    if disk_number != 0 or directory_disk != 0 or entries_on_disk != entries_total:
        raise ResearchReleaseError("release ZIP must be a single-disk archive")
    if entries_total < 3 or entries_total > MAX_FILES + 2:
        raise ResearchReleaseError(
            "release ZIP EOCD member count is outside its bound"
        )
    if directory_size == 0xFFFFFFFF or directory_offset == 0xFFFFFFFF:
        raise ResearchReleaseError("release ZIP64 archives are forbidden")
    directory_end = directory_offset + directory_size
    if directory_end != eocd_offset or directory_offset > eocd_offset:
        raise ResearchReleaseError(
            "release ZIP central-directory extent is noncanonical"
        )

    cursor = directory_offset
    counted = 0
    while cursor < directory_end:
        if counted >= MAX_FILES + 2:
            raise ResearchReleaseError(
                "release ZIP central-directory count exceeds its bound"
            )
        if cursor + 46 > directory_end or raw[cursor : cursor + 4] != b"PK\x01\x02":
            raise ResearchReleaseError(
                "release ZIP central directory is malformed"
            )
        filename_length, extra_length, entry_comment_length = struct.unpack_from(
            "<3H",
            raw,
            cursor + 28,
        )
        entry_disk = struct.unpack_from("<H", raw, cursor + 34)[0]
        if entry_disk != 0:
            raise ResearchReleaseError("release ZIP central entry is multi-disk")
        if filename_length < 1 or filename_length > MAX_ZIP_MEMBER_PATH:
            raise ResearchReleaseError(
                "release ZIP central member name exceeds its byte bound"
            )
        if extra_length != 0 or entry_comment_length != 0:
            raise ResearchReleaseError(
                "release ZIP central entry has noncanonical extra metadata"
            )
        cursor += 46 + filename_length
        if cursor > directory_end:
            raise ResearchReleaseError(
                "release ZIP central entry extends beyond its directory"
            )
        counted += 1
    if cursor != directory_end or counted != entries_total:
        raise ResearchReleaseError(
            "release ZIP central-directory count does not match its EOCD"
        )
    return counted


def _read_zip_members(
    raw: bytes,
    generated_member_names: set[str],
) -> tuple[list[zipfile.ZipInfo], dict[str, bytes]]:
    preflight_count = _preflight_standard_zip(raw)
    try:
        with zipfile.ZipFile(io.BytesIO(raw), "r", allowZip64=False) as archive:
            if archive.comment:
                raise ResearchReleaseError("release ZIP archive comment must be empty")
            infos = archive.infolist()
            if len(infos) < 3 or len(infos) > MAX_FILES + 2:
                raise ResearchReleaseError("release ZIP member count is outside its bound")
            if len(infos) != preflight_count:
                raise ResearchReleaseError(
                    "release ZIP parsed member count disagrees with preflight"
                )
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise ResearchReleaseError("release ZIP contains duplicate members")
            if names != sorted(names):
                raise ResearchReleaseError("release ZIP member order is not canonical")
            members: dict[str, bytes] = {}
            total = 0
            for index, info in enumerate(infos):
                name = _zip_member_path(info.filename, f"release ZIP member[{index}]")
                if info.is_dir() or name.endswith("/"):
                    raise ResearchReleaseError("release ZIP must not contain directory members")
                archived_mode = info.external_attr >> 16
                if (
                    info.date_time != FIXED_ZIP_TIME
                    or info.compress_type != zipfile.ZIP_STORED
                    or info.create_system != 3
                    or not stat.S_ISREG(archived_mode)
                    or stat.S_IMODE(archived_mode) != 0o444
                    or info.extra != b""
                    or info.comment != b""
                ):
                    raise ResearchReleaseError(
                        f"release ZIP member metadata/mode/compression is noncanonical: {name}"
                    )
                if info.flag_bits & 0x1:
                    raise ResearchReleaseError("release ZIP must not contain encrypted members")
                member_limit = (
                    MAX_GENERATED_MEMBER_BYTES
                    if name in generated_member_names
                    else MAX_MEMBER_BYTES
                )
                if info.file_size > member_limit or info.compress_size > member_limit:
                    raise ResearchReleaseError(f"release ZIP member exceeds its bound: {name}")
                data = archive.read(info)
                if len(data) != info.file_size:
                    raise ResearchReleaseError(f"release ZIP member byte count changed: {name}")
                total += len(data)
                if total > MAX_TOTAL_BYTES + MAX_GENERATED_MEMBER_BYTES * 2:
                    raise ResearchReleaseError("release ZIP member set exceeds its total bound")
                members[name] = data
            return infos, members
    except ResearchReleaseError:
        raise
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        RuntimeError,
        NotImplementedError,
        OSError,
        EOFError,
    ) as exc:
        raise ResearchReleaseError(f"release ZIP archive is invalid: {exc}") from exc


def validate_archive(root: Path, relative: str) -> dict[str, Any]:
    relative, release_id, release_version = _parse_release_archive_path(relative)
    raw = _read_regular(
        root,
        relative,
        "release ZIP archive",
        MAX_ARCHIVE_BYTES,
        required_mode=0o444,
    )
    prefix = _release_root(release_id, release_version)
    manifest_name = f"{prefix}manifest.json"
    readme_name = f"{prefix}README.md"
    infos, members = _read_zip_members(raw, {manifest_name, readme_name})
    names = [info.filename for info in infos]
    _validate_portable_topology(names, "release ZIP member topology")
    if manifest_name not in members or readme_name not in members:
        raise ResearchReleaseError("release ZIP is missing README.md or manifest.json")
    try:
        manifest_text = members[manifest_name].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResearchReleaseError("release package manifest is not UTF-8") from exc
    parsed_manifest = strict_json_loads(manifest_text, "release package manifest")
    if canonical_json_bytes(parsed_manifest) != members[manifest_name]:
        raise ResearchReleaseError("release package manifest is not canonical JSON")
    manifest, request = _validate_package_manifest(
        parsed_manifest, release_id, release_version
    )
    if manifest["archive_contract"]["member_order"] != names:
        raise ResearchReleaseError("release ZIP member order does not match package manifest")
    expected_names = sorted(
        [
            readme_name,
            manifest_name,
            *(f"{prefix}{entry['package_path']}" for entry in manifest["files"]),
        ]
    )
    if names != expected_names:
        raise ResearchReleaseError("release ZIP member set does not exactly match package manifest")
    readme = members[readme_name]
    contract = manifest["archive_contract"]
    if len(readme) != contract["readme_bytes"] or sha256_bytes(readme) != contract["readme_sha256"]:
        raise ResearchReleaseError("release README bytes or digest do not match package manifest")

    export, data_by_source, export_entries = _load_export(
        root,
        request["source_export_manifest_path"],
        request["source_export_manifest_sha256"],
    )
    source_export = manifest["source_export"]
    expected_source_export = {
        "path": request["source_export_manifest_path"],
        "sha256": request["source_export_manifest_sha256"],
        "export_id": export["export_id"],
        "created_at_utc": export["created_at_utc"],
        "manifest_payload_sha256": export["manifest_payload_sha256"],
        "review": export["review"],
    }
    if source_export != expected_source_export:
        raise ResearchReleaseError("package source-export binding does not match current reviewed export")
    if (
        manifest["claim_ids"] != export["claim_ids"]
        or manifest["claim_bindings"] != export["claim_bindings"]
        or manifest["source_checkpoint_paths"] != export["source_checkpoint_paths"]
    ):
        raise ResearchReleaseError("package claim/checkpoint bindings do not match reviewed export")
    _verify_request_against_export(request, export, export_entries)

    files_by_source = {entry["source_path"]: entry for entry in manifest["files"]}
    total_bytes = 0
    for source_path, export_entry in export_entries.items():
        package_entry = files_by_source.get(source_path)
        if package_entry is None:
            raise ResearchReleaseError("package omits a reviewed export source")
        source = data_by_source[source_path]
        expected_binding = (export_entry["sha256"], export_entry["bytes"])
        if (
            package_entry["source_sha256"],
            package_entry["source_bytes"],
        ) != expected_binding:
            raise ResearchReleaseError(f"package source binding drifted: {source_path}")
        member = members[f"{prefix}{package_entry['package_path']}"]
        if (
            member != source
            or sha256_bytes(member) != package_entry["package_sha256"]
            or len(member) != package_entry["package_bytes"]
        ):
            raise ResearchReleaseError(
                f"release ZIP member bytes or digest do not match source: {package_entry['package_path']}"
            )
        total_bytes += len(member)

    expected_readme = _readme(request, manifest["files"])
    if readme != expected_readme:
        raise ResearchReleaseError("release README does not match its deterministic projection")
    rebuilt = _zip_bytes(manifest, readme, data_by_source)
    if rebuilt != raw:
        raise ResearchReleaseError("release ZIP bytes or metadata are not canonical deterministic output")
    return {
        "archive_path": relative,
        "archive_sha256": sha256_bytes(raw),
        "files_validated": len(manifest["files"]),
        "bytes_validated": total_bytes,
    }


def _ensure_output_parent_fd(root: Path, parts: Sequence[str]) -> int:
    descriptor = _open_root_directory(root, "release output")
    try:
        for part in parts:
            try:
                os.mkdir(part, 0o755, dir_fd=descriptor)
            except FileExistsError:
                pass
            except OSError as exc:
                raise ResearchReleaseError(
                    f"cannot create release output parent {part}: {exc}"
                ) from exc
            try:
                child = os.open(part, _directory_flags(), dir_fd=descriptor)
            except OSError as exc:
                raise ResearchReleaseError(
                    f"release output parent is a symlink or unsafe directory: {part}: {exc}"
                ) from exc
            info = os.fstat(child)
            if not stat.S_ISDIR(info.st_mode):
                os.close(child)
                raise ResearchReleaseError("release output parent is not a directory")
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _atomic_publish(root: Path, relative: str, data: bytes) -> Path:
    relative = _relpath(relative, "release output path")
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ResearchReleaseError("release output exceeds its archive byte bound")
    parts = PurePosixPath(relative).parts
    target = root.joinpath(*parts)
    parent_fd = _ensure_output_parent_fd(root, parts[:-1])
    target_name = parts[-1]
    temporary_name = f".research-release-{secrets.token_hex(16)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: Optional[int] = None
    temporary_exists = False
    published_created = False
    published_identity: Optional[tuple[int, int]] = None
    success = False
    try:
        descriptor = os.open(temporary_name, flags, 0o600, dir_fd=parent_fd)
        temporary_exists = True
        view = memoryview(data)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise ResearchReleaseError("short write while creating release archive")
            written += count
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o444)
        os.close(descriptor)
        descriptor = None
        try:
            os.link(
                temporary_name,
                target_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise ResearchReleaseError(
                f"refusing to overwrite existing release output: {relative}"
            ) from exc
        except OSError as exc:
            if exc.errno in {errno.EEXIST, errno.ENOTEMPTY}:
                raise ResearchReleaseError(
                    f"refusing to overwrite existing release output: {relative}"
                ) from exc
            raise ResearchReleaseError(f"atomic release publication failed: {exc}") from exc
        published_created = True
        os.unlink(temporary_name, dir_fd=parent_fd)
        temporary_exists = False
        os.fsync(parent_fd)
        published = os.stat(target_name, dir_fd=parent_fd, follow_symlinks=False)
        published_identity = (published.st_dev, published.st_ino)
        if (
            not stat.S_ISREG(published.st_mode)
            or stat.S_IMODE(published.st_mode) != 0o444
            or published.st_nlink != 1
            or published.st_size != len(data)
        ):
            raise ResearchReleaseError("published release output identity/mode is invalid")
        public_bytes = _read_regular(
            root,
            relative,
            "published release output",
            MAX_ARCHIVE_BYTES,
            required_mode=0o444,
        )
        if public_bytes != data:
            raise ResearchReleaseError(
                "published release output bytes changed at its public path"
            )
        success = True
        return target
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_exists:
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        if published_created and not success and published_identity is not None:
            try:
                current = os.stat(target_name, dir_fd=parent_fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) == published_identity:
                    os.unlink(target_name, dir_fd=parent_fd)
                    os.fsync(parent_fd)
            except OSError:
                # The original failure remains authoritative; never delete an
                # inode whose exact identity can no longer be established.
                pass
        os.close(parent_fd)


def build_release(root: Path, value: Any) -> Path:
    if not _repository_enabled(root):
        raise ResearchReleaseError("repository-first release policy is disabled and dormant")
    _require_raw_archive_ignored(root)
    request = validate_request(value)
    export, data_by_source, export_entries = _load_export(
        root,
        request["source_export_manifest_path"],
        request["source_export_manifest_sha256"],
    )
    _verify_request_against_export(request, export, export_entries)
    files = _package_files(request, data_by_source, export_entries)
    readme = _readme(request, files)
    manifest = _manifest_for_build(request, export, files, readme)
    archive = _zip_bytes(manifest, readme, data_by_source)
    final_export, final_data, final_entries = _load_export(
        root,
        request["source_export_manifest_path"],
        request["source_export_manifest_sha256"],
    )
    if (
        final_export != export
        or final_entries != export_entries
        or final_data != data_by_source
    ):
        raise ResearchReleaseError(
            "reviewed export or source bytes drifted during release construction"
        )
    del final_export, final_entries, final_data
    output = _release_archive_path(request["release_id"], request["release_version"])
    return _atomic_publish(root, output, archive)


def _scan_release_archives(root: Path) -> list[str]:
    releases_fd = _open_directory_chain(
        root,
        ("research", "repository_first", "releases"),
        "release tree",
        allow_missing_final=True,
    )
    if releases_fd is None:
        return []
    result: list[str] = []
    try:
        with os.scandir(releases_fd) as iterator:
            release_entries = sorted(list(iterator), key=lambda entry: entry.name)
        for release_entry in release_entries:
            release_id = _release_id(release_entry.name, "release directory name")
            entry_info = release_entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(entry_info.st_mode) or not stat.S_ISDIR(entry_info.st_mode):
                raise ResearchReleaseError("release tree contains an unsafe non-directory entry")
            try:
                release_fd = os.open(
                    release_entry.name,
                    _directory_flags(),
                    dir_fd=releases_fd,
                )
            except OSError as exc:
                raise ResearchReleaseError(
                    f"release directory changed or became unsafe: {exc}"
                ) from exc
            try:
                opened = os.fstat(release_fd)
                if (opened.st_dev, opened.st_ino) != (entry_info.st_dev, entry_info.st_ino):
                    raise ResearchReleaseError("release directory identity changed during scan")
                with os.scandir(release_fd) as iterator:
                    archive_entries = sorted(list(iterator), key=lambda entry: entry.name)
                for archive_entry in archive_entries:
                    archive_info = archive_entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(archive_info.st_mode) or not stat.S_ISREG(archive_info.st_mode):
                        raise ResearchReleaseError(
                            "release directory contains a symlink or special file"
                        )
                    if not archive_entry.name.endswith(".zip"):
                        raise ResearchReleaseError("release directory contains a non-ZIP file")
                    _portable_component(
                        archive_entry.name,
                        "release archive filename",
                    )
                    release_version = _release_version(
                        archive_entry.name[:-4], "release archive version"
                    )
                    result.append(_release_archive_path(release_id, release_version))
            finally:
                os.close(release_fd)
        return result
    finally:
        os.close(releases_fd)


def validate_releases(root: Path = ROOT, archive: Optional[str] = None) -> dict[str, Any]:
    if not _repository_enabled(root):
        return {
            "schema_version": SCHEMA_VERSION,
            "policy": POLICY_ID,
            "status": "DISABLED",
            "releases_validated": 0,
            "files_validated": 0,
            "bytes_validated": 0,
            "archives": [],
        }
    _require_raw_archive_ignored(root)
    archives = [_parse_release_archive_path(archive)[0]] if archive is not None else _scan_release_archives(root)
    files = 0
    byte_count = 0
    reports: list[dict[str, Any]] = []
    for relative in archives:
        report = validate_archive(root, relative)
        files += report["files_validated"]
        byte_count += report["bytes_validated"]
        reports.append(report)
    return {
        "schema_version": SCHEMA_VERSION,
        "policy": POLICY_ID,
        "status": "VALID",
        "releases_validated": len(archives),
        "files_validated": files,
        "bytes_validated": byte_count,
        "archives": reports,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or validate deterministic local Research Artifact Release v1 packages."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--input", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--archive")
    validate.add_argument("--json", action="store_true")
    return parser


def run(argv: Optional[Sequence[str]] = None) -> int:
    try:
        arguments = _parser().parse_args(list(argv) if argv is not None else None)
        if arguments.command == "build":
            value = _read_input(ROOT, arguments.input)
            output = build_release(ROOT, value)
            relative = output.relative_to(ROOT).as_posix()
            archive = _read_regular(
                ROOT,
                relative,
                "published release output",
                MAX_ARCHIVE_BYTES,
                required_mode=0o444,
            )
            print(
                json.dumps(
                    {
                        "archive_path": relative,
                        "archive_sha256": sha256_bytes(archive),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        report = validate_releases(ROOT, arguments.archive)
        if arguments.json:
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        else:
            print(
                f"{report['status']} research artifact releases: "
                f"{report['releases_validated']} package(s), "
                f"{report['files_validated']} reviewed file(s)"
            )
            for archive_report in report["archives"]:
                print(
                    f"{archive_report['archive_path']} "
                    f"{archive_report['archive_sha256']}"
                )
        return 0
    except ResearchReleaseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except SystemExit as exc:
        return int(exc.code or 0)


if __name__ == "__main__":
    raise SystemExit(run())
