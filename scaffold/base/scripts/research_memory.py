#!/usr/bin/env python3
"""Durable, append-only research checkpoint memory.

The Markdown checkpoint is canonical.  Its hidden JSON envelope makes local
discovery deterministic without introducing a second research ledger.  The
index is disposable derived state and is always rebuilt from the checkpoints.
"""

from __future__ import annotations

import argparse
import contextlib
import contextvars
import fcntl
import hashlib
import html
import json
import os
import re
import secrets
import stat
import sys
import time
import unicodedata
from collections import deque
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional, Sequence, Union


ROOT = Path(__file__).resolve().parents[1]
_CONTROL_ROOM_ROOT_FD = globals().get("__control_room_root_fd__")
_CONTROL_ROOM_RESEARCH_FD = globals().get("__control_room_research_fd__")
_CONTROL_ROOM_CHECKPOINTS_FD = globals().get("__control_room_checkpoints_fd__")
CHECKPOINT_DIRECTORY = Path("research/checkpoints")
INDEX_RELATIVE = Path("research/checkpoint_index.json")

SCHEMA_VERSION = 1
OUTCOME_STATUSES = (
    "PROVED",
    "REFUTED",
    "PARTIAL",
    "BLOCKED",
    "INCONCLUSIVE",
    "ABANDONED",
    "SUPERSEDED",
)

MAX_INPUT_BYTES = 256 * 1024
MAX_CHECKPOINT_BYTES = 512 * 1024
MAX_INDEX_BYTES = 16 * 1024 * 1024
MAX_CHECKPOINTS = 4096
MAX_CHECKPOINT_TOTAL_BYTES = 64 * 1024 * 1024
MAX_BOUND_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_TEXT = 16_384
MAX_SHORT_TEXT = 1_024
MAX_ITEMS = 64
MAX_PATH = 512
MAX_SEARCH_LIMIT = 100
MAX_QUERY = 512
MAX_SEARCH_FILTERS = 16
LOCK_TIMEOUT_SECONDS = 5.0
LOCK_POLL_SECONDS = 0.025

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
CHECKPOINT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,190}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CHECKPOINT_STAGING_RE = re.compile(r"^\.research-memory-[0-9a-f]{32}$")
INDEX_STAGING_RE = re.compile(r"^\.checkpoint-index-[0-9a-f]{32}$")
CHECKPOINT_STAGING_PREFIX = ".research-memory-"
INDEX_STAGING_PREFIX = ".checkpoint-index-"

COMMENT_START = "<!-- research-checkpoint-record:v1"
COMMENT_END = "-->"

_ACTIVE_LAYOUT: contextvars.ContextVar[
    Optional[dict[str, int]]
] = contextvars.ContextVar("research_memory_active_layout", default=None)

TOP_LEVEL_REQUIRED = {
    "schema_version",
    "checkpoint_id",
    "research_date",
    "recorded_at_utc",
    "outcome_status",
    "target",
    "scope",
    "outcome",
    "verification",
    "continuation",
    "discovery",
}
TOP_LEVEL_OPTIONAL = {
    "round_id",
    "run_id",
    "track",
    "problem_ids",
    "claim_ids",
    "target_bindings",
    "related_checkpoints",
    "supersedes",
    "revision_reason",
    "revision_binding",
    "source_status",
    "semantic_delta",
    "examples",
    "counterexamples",
    "worked",
    "failed",
    "obstructions",
    "claims",
    "artifacts",
    "useful_residue",
    "visibility_limitations",
}


class ResearchMemoryError(ValueError):
    """A bounded validation or safe-publication failure."""


class CheckpointEvidenceError(ResearchMemoryError):
    """Missing or changed evidence; filesystem safety errors remain distinct."""


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ResearchMemoryError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ResearchMemoryError(f"non-finite JSON number is forbidden: {value}")


def strict_json_loads(text: str, label: str) -> Any:
    try:
        return json.loads(
            text,
            object_pairs_hook=_strict_pairs,
            parse_constant=_reject_constant,
        )
    except ResearchMemoryError:
        raise
    except (ValueError, RecursionError) as exc:
        raise ResearchMemoryError(f"{label} is not strict JSON: {exc}") from exc


def canonical_json_bytes(value: Any) -> bytes:
    text = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        separators=(",", ": "),
    )
    return (text + "\n").encode("utf-8")


def _comment_json(value: Any) -> str:
    # Escaping HTML-significant ASCII prevents user text from terminating the
    # designated comment while retaining ordinary JSON semantics.
    text = canonical_json_bytes(value).decode("utf-8").rstrip("\n")
    return text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def _ensure_scalar_text(value: str, label: str) -> None:
    for char in value:
        codepoint = ord(char)
        if 0xD800 <= codepoint <= 0xDFFF:
            raise ResearchMemoryError(f"{label} contains a non-scalar Unicode surrogate")
        if codepoint < 0x20 and char not in ("\n", "\t"):
            raise ResearchMemoryError(f"{label} contains a forbidden control character")
        if codepoint == 0x7F:
            raise ResearchMemoryError(f"{label} contains a forbidden control character")


def _text(value: Any, label: str, *, maximum: int = MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise ResearchMemoryError(f"{label} must be a string")
    _ensure_scalar_text(value, label)
    normalized = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n")).strip()
    _ensure_scalar_text(normalized, label)
    if not normalized:
        raise ResearchMemoryError(f"{label} must not be empty")
    if len(normalized) > maximum or len(normalized.encode("utf-8")) > maximum * 4:
        raise ResearchMemoryError(f"{label} exceeds its size bound")
    return normalized


def _single_line(value: Any, label: str, *, maximum: int = MAX_SHORT_TEXT) -> str:
    result = _text(value, label, maximum=maximum)
    if "\n" in result or "\t" in result:
        raise ResearchMemoryError(f"{label} must be one line")
    return result


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ResearchMemoryError(
            f"{label} must match {ID_RE.pattern}"
        )
    return value


def _checkpoint_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not CHECKPOINT_ID_RE.fullmatch(value):
        raise ResearchMemoryError(
            f"{label} must match {CHECKPOINT_ID_RE.pattern}"
        )
    return value


def _exact_keys(
    value: Any,
    label: str,
    required: Iterable[str],
    optional: Iterable[str] = (),
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ResearchMemoryError(f"{label} must be an object")
    required_set = set(required)
    allowed = required_set | set(optional)
    missing = sorted(required_set - set(value))
    unknown = sorted(set(value) - allowed)
    if missing:
        raise ResearchMemoryError(f"{label} is missing keys: {', '.join(missing)}")
    if unknown:
        raise ResearchMemoryError(f"{label} has unknown keys: {', '.join(unknown)}")
    return value


def _date(value: Any, label: str) -> str:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        raise ResearchMemoryError(f"{label} must be an exact YYYY-MM-DD date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ResearchMemoryError(f"{label} is not a real calendar date") from exc
    if parsed.isoformat() != value:
        raise ResearchMemoryError(f"{label} is not canonical")
    return value


def _research_date(value: Any) -> Union[str, dict[str, str]]:
    if isinstance(value, str):
        return _date(value, "research_date")
    item = _exact_keys(value, "research_date", {"start", "end"})
    start = _date(item["start"], "research_date.start")
    end = _date(item["end"], "research_date.end")
    if start > end:
        raise ResearchMemoryError("research_date.start must not be after research_date.end")
    return {"start": start, "end": end}


def _utc_timestamp(value: Any, label: str = "recorded_at_utc") -> str:
    if not isinstance(value, str) or not UTC_RE.fullmatch(value):
        raise ResearchMemoryError(f"{label} must be an exact UTC timestamp YYYY-MM-DDTHH:MM:SSZ")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ResearchMemoryError(f"{label} is not a real UTC timestamp") from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ResearchMemoryError(f"{label} is not canonical")
    return value


def _string_list(
    value: Any,
    label: str,
    *,
    maximum_items: int = MAX_ITEMS,
    item_maximum: int = MAX_SHORT_TEXT,
    sorted_set: bool = False,
    one_line: bool = False,
) -> list[str]:
    if not isinstance(value, list) or isinstance(value, tuple):
        raise ResearchMemoryError(f"{label} must be an array")
    if not value:
        raise ResearchMemoryError(f"{label} must not be empty when present")
    if len(value) > maximum_items:
        raise ResearchMemoryError(f"{label} has too many items")
    validator = _single_line if one_line else _text
    result = [
        validator(item, f"{label}[{index}]", maximum=item_maximum)
        for index, item in enumerate(value)
    ]
    folded: set[str] = set()
    for item in result:
        key = item.casefold()
        if key in folded:
            raise ResearchMemoryError(f"{label} contains a duplicate item: {item!r}")
        folded.add(key)
    if sorted_set:
        result.sort(key=lambda item: (item.casefold(), item))
    return result


def _id_list(value: Any, label: str, *, checkpoints: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise ResearchMemoryError(f"{label} must be an array")
    if not value:
        raise ResearchMemoryError(f"{label} must not be empty when present")
    if len(value) > MAX_ITEMS:
        raise ResearchMemoryError(f"{label} has too many items")
    validator = _checkpoint_identifier if checkpoints else _identifier
    result = [validator(item, f"{label}[{index}]") for index, item in enumerate(value)]
    if len(set(result)) != len(result):
        raise ResearchMemoryError(f"{label} contains duplicate IDs")
    return sorted(result)


def _relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ResearchMemoryError(f"{label} must be a string path")
    _ensure_scalar_text(value, label)
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ResearchMemoryError(f"{label} must not contain control characters")
    if not value or value != value.strip() or len(value) > MAX_PATH:
        raise ResearchMemoryError(f"{label} is empty, padded, or too long")
    if "\\" in value or value.startswith("/") or "//" in value:
        raise ResearchMemoryError(f"{label} must be a relative POSIX path")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ResearchMemoryError(f"{label} contains an unsafe path component")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value:
        raise ResearchMemoryError(f"{label} is not a canonical relative POSIX path")
    return value


def _optional_artifact_paths(value: dict[str, Any], label: str) -> Optional[list[str]]:
    if "artifact_paths" not in value:
        return None
    raw = value["artifact_paths"]
    if not isinstance(raw, list) or not raw or len(raw) > MAX_ITEMS:
        raise ResearchMemoryError(f"{label}.artifact_paths must be a non-empty bounded array")
    result = [_relative_path(item, f"{label}.artifact_paths[{index}]") for index, item in enumerate(raw)]
    if len(set(result)) != len(result):
        raise ResearchMemoryError(f"{label}.artifact_paths contains duplicates")
    return sorted(result)


def _normalize_outcome(value: Any) -> dict[str, Any]:
    item = _exact_keys(
        value,
        "outcome",
        {"summary"},
        {"generality", "remaining_unproved", "outcome_class"},
    )
    result: dict[str, Any] = {
        "summary": _text(item["summary"], "outcome.summary"),
    }
    for key in ("generality", "remaining_unproved"):
        if key in item:
            result[key] = _text(item[key], f"outcome.{key}")
    if "outcome_class" in item:
        result["outcome_class"] = _single_line(item["outcome_class"], "outcome.outcome_class", maximum=128)
    return result


def _normalize_verification(value: Any) -> dict[str, Any]:
    item = _exact_keys(
        value,
        "verification",
        {"state", "summary"},
        {"independence", "evidence", "limitations"},
    )
    result: dict[str, Any] = {
        "state": _single_line(item["state"], "verification.state", maximum=128),
        "summary": _text(item["summary"], "verification.summary"),
    }
    if "independence" in item:
        result["independence"] = _text(item["independence"], "verification.independence")
    for key in ("evidence", "limitations"):
        if key in item:
            result[key] = _string_list(item[key], f"verification.{key}")
    return result


def _normalize_continuation(value: Any) -> dict[str, Any]:
    item = _exact_keys(
        value,
        "continuation",
        {"next_action"},
        {"cheapest_falsifier", "success_criterion", "stop_condition", "reopen_condition"},
    )
    result = {"next_action": _text(item["next_action"], "continuation.next_action")}
    for key in ("cheapest_falsifier", "success_criterion", "stop_condition", "reopen_condition"):
        if key in item:
            result[key] = _text(item[key], f"continuation.{key}")
    return result


def _normalize_discovery(value: Any) -> dict[str, Any]:
    item = _exact_keys(
        value,
        "discovery",
        {"topics"},
        {"objects", "methods", "keywords", "future_capabilities"},
    )
    result = {
        "topics": _string_list(
            item["topics"], "discovery.topics", sorted_set=True, one_line=True
        )
    }
    for key in ("objects", "methods", "keywords", "future_capabilities"):
        if key in item:
            result[key] = _string_list(
                item[key], f"discovery.{key}", sorted_set=True, one_line=True
            )
    return result


def _normalize_target_bindings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > MAX_ITEMS:
        raise ResearchMemoryError("target_bindings must be a non-empty bounded array")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(value):
        label = f"target_bindings[{index}]"
        item = _exact_keys(raw, label, {"target_id"}, {"kind", "sha256"})
        target_id = _identifier(item["target_id"], f"{label}.target_id")
        kind = _single_line(item.get("kind", "TARGET"), f"{label}.kind", maximum=64)
        key = (kind.casefold(), target_id)
        if key in seen:
            raise ResearchMemoryError("target_bindings contains a duplicate binding")
        seen.add(key)
        normalized: dict[str, Any] = {"target_id": target_id}
        if "kind" in item:
            normalized["kind"] = kind
        if "sha256" in item:
            digest = item["sha256"]
            if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                raise ResearchMemoryError(f"{label}.sha256 must be a lowercase SHA-256 digest")
            normalized["sha256"] = digest
        result.append(normalized)
    result.sort(key=lambda item: (item.get("kind", "TARGET").casefold(), item["target_id"]))
    return result


def _normalize_exact_file_binding(value: Any, label: str) -> dict[str, str]:
    item = _exact_keys(value, label, {"path", "sha256"})
    digest = item["sha256"]
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise ResearchMemoryError(f"{label}.sha256 must be a lowercase SHA-256 digest")
    return {
        "path": _relative_path(item["path"], f"{label}.path"),
        "sha256": digest,
    }


def _normalize_revision_binding(value: Any) -> dict[str, Any]:
    item = _exact_keys(
        value,
        "revision_binding",
        {"finding", "preimage", "revision", "predecessor_checkpoints"},
    )
    result: dict[str, Any] = {
        key: _normalize_exact_file_binding(item[key], f"revision_binding.{key}")
        for key in ("finding", "preimage", "revision")
    }
    paths = [result[key]["path"] for key in ("finding", "preimage", "revision")]
    if len(set(paths)) != len(paths):
        raise ResearchMemoryError(
            "revision finding, preimage, and revision paths must be distinct"
        )
    if result["preimage"]["sha256"] == result["revision"]["sha256"]:
        raise ResearchMemoryError("revision bytes must differ from the preserved preimage")
    raw_predecessors = item["predecessor_checkpoints"]
    if (
        not isinstance(raw_predecessors, list)
        or not raw_predecessors
        or len(raw_predecessors) > MAX_ITEMS
    ):
        raise ResearchMemoryError(
            "revision_binding.predecessor_checkpoints must be a non-empty bounded array"
        )
    predecessors: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_predecessors):
        label = f"revision_binding.predecessor_checkpoints[{index}]"
        predecessor = _exact_keys(raw, label, {"checkpoint_id", "sha256"})
        checkpoint_id = _checkpoint_identifier(
            predecessor["checkpoint_id"], f"{label}.checkpoint_id"
        )
        digest = predecessor["sha256"]
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise ResearchMemoryError(f"{label}.sha256 must be a lowercase SHA-256 digest")
        if checkpoint_id in seen:
            raise ResearchMemoryError(
                "revision_binding.predecessor_checkpoints contains a duplicate checkpoint_id"
            )
        seen.add(checkpoint_id)
        predecessors.append({"checkpoint_id": checkpoint_id, "sha256": digest})
    predecessors.sort(key=lambda entry: entry["checkpoint_id"])
    result["predecessor_checkpoints"] = predecessors
    return result


def _normalize_semantic_delta(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value or len(value) > MAX_ITEMS:
        raise ResearchMemoryError("semantic_delta must be a non-empty bounded array")
    allowed_changes = {"CLOSED", "REDUCED", "REFUTED", "UNCHANGED", "NEW_BLOCKER"}
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        label = f"semantic_delta[{index}]"
        item = _exact_keys(raw, label, {"dependency", "before", "after", "change"})
        dependency = _single_line(item["dependency"], f"{label}.dependency")
        if dependency.casefold() in seen:
            raise ResearchMemoryError("semantic_delta contains a duplicate dependency")
        seen.add(dependency.casefold())
        change = item["change"]
        if change not in allowed_changes:
            raise ResearchMemoryError(f"{label}.change has an unsupported value")
        result.append(
            {
                "dependency": dependency,
                "before": _text(item["before"], f"{label}.before"),
                "after": _text(item["after"], f"{label}.after"),
                "change": change,
            }
        )
    return result


def _normalize_examples(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > MAX_ITEMS:
        raise ResearchMemoryError("examples must be a non-empty bounded array")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        label = f"examples[{index}]"
        item = _exact_keys(raw, label, {"summary"}, {"id", "purpose", "result", "artifact_paths"})
        normalized: dict[str, Any] = {"summary": _text(item["summary"], f"{label}.summary")}
        if "id" in item:
            normalized["id"] = _identifier(item["id"], f"{label}.id")
        for key in ("purpose", "result"):
            if key in item:
                normalized[key] = _text(item[key], f"{label}.{key}")
        paths = _optional_artifact_paths(item, label)
        if paths is not None:
            normalized["artifact_paths"] = paths
        result.append(normalized)
    return result


def _normalize_counterexamples(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > MAX_ITEMS:
        raise ResearchMemoryError("counterexamples must be a non-empty bounded array")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        label = f"counterexamples[{index}]"
        item = _exact_keys(raw, label, {"target", "example", "verification"}, {"id", "artifact_paths"})
        normalized: dict[str, Any] = {
            "target": _text(item["target"], f"{label}.target"),
            "example": _text(item["example"], f"{label}.example"),
            "verification": _text(item["verification"], f"{label}.verification"),
        }
        if "id" in item:
            normalized["id"] = _identifier(item["id"], f"{label}.id")
        paths = _optional_artifact_paths(item, label)
        if paths is not None:
            normalized["artifact_paths"] = paths
        result.append(normalized)
    return result


def _normalize_worked(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > MAX_ITEMS:
        raise ResearchMemoryError("worked must be a non-empty bounded array")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        label = f"worked[{index}]"
        item = _exact_keys(raw, label, {"task", "result"}, {"id", "verification", "artifact_paths"})
        normalized: dict[str, Any] = {
            "task": _text(item["task"], f"{label}.task"),
            "result": _text(item["result"], f"{label}.result"),
        }
        if "id" in item:
            normalized["id"] = _identifier(item["id"], f"{label}.id")
        if "verification" in item:
            normalized["verification"] = _text(item["verification"], f"{label}.verification")
        paths = _optional_artifact_paths(item, label)
        if paths is not None:
            normalized["artifact_paths"] = paths
        result.append(normalized)
    return result


def _normalize_failed(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > MAX_ITEMS:
        raise ResearchMemoryError("failed must be a non-empty bounded array")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        label = f"failed[{index}]"
        item = _exact_keys(
            raw,
            label,
            {"attempt", "exact_reason"},
            {"id", "useful_residue", "reopen_trigger", "artifact_paths"},
        )
        normalized: dict[str, Any] = {
            "attempt": _text(item["attempt"], f"{label}.attempt"),
            "exact_reason": _text(item["exact_reason"], f"{label}.exact_reason"),
        }
        if "id" in item:
            normalized["id"] = _identifier(item["id"], f"{label}.id")
        for key in ("useful_residue", "reopen_trigger"):
            if key in item:
                normalized[key] = _text(item[key], f"{label}.{key}")
        paths = _optional_artifact_paths(item, label)
        if paths is not None:
            normalized["artifact_paths"] = paths
        result.append(normalized)
    return result


def _normalize_obstructions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > MAX_ITEMS:
        raise ResearchMemoryError("obstructions must be a non-empty bounded array")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        label = f"obstructions[{index}]"
        item = _exact_keys(
            raw,
            label,
            {"description", "missing_capability", "reopen_trigger"},
            {"id", "evidence"},
        )
        normalized: dict[str, Any] = {
            "description": _text(item["description"], f"{label}.description"),
            "missing_capability": _text(item["missing_capability"], f"{label}.missing_capability"),
            "reopen_trigger": _text(item["reopen_trigger"], f"{label}.reopen_trigger"),
        }
        if "id" in item:
            normalized["id"] = _identifier(item["id"], f"{label}.id")
        if "evidence" in item:
            normalized["evidence"] = _text(item["evidence"], f"{label}.evidence")
        result.append(normalized)
    return result


def _normalize_claims(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > MAX_ITEMS:
        raise ResearchMemoryError("claims must be a non-empty bounded array")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        label = f"claims[{index}]"
        item = _exact_keys(
            raw,
            label,
            {"claim_id", "statement", "status"},
            {"source_status", "verification", "artifact_paths"},
        )
        claim_id = _identifier(item["claim_id"], f"{label}.claim_id")
        if claim_id in seen:
            raise ResearchMemoryError("claims contains a duplicate claim_id")
        seen.add(claim_id)
        normalized: dict[str, Any] = {
            "claim_id": claim_id,
            "statement": _text(item["statement"], f"{label}.statement"),
            "status": _single_line(item["status"], f"{label}.status", maximum=128),
        }
        for key in ("source_status", "verification"):
            if key in item:
                normalized[key] = _text(item[key], f"{label}.{key}")
        paths = _optional_artifact_paths(item, label)
        if paths is not None:
            normalized["artifact_paths"] = paths
        result.append(normalized)
    return result


def _normalize_artifacts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > MAX_ITEMS:
        raise ResearchMemoryError("artifacts must be a non-empty bounded array")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        label = f"artifacts[{index}]"
        item = _exact_keys(raw, label, {"path", "role"}, {"sha256", "status"})
        path = _relative_path(item["path"], f"{label}.path")
        if path in seen:
            raise ResearchMemoryError("artifacts contains a duplicate path")
        seen.add(path)
        normalized: dict[str, Any] = {
            "path": path,
            "role": _text(item["role"], f"{label}.role", maximum=MAX_SHORT_TEXT),
        }
        if "sha256" in item:
            digest = item["sha256"]
            if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                raise ResearchMemoryError(f"{label}.sha256 must be a lowercase SHA-256 digest")
            normalized["sha256"] = digest
        if "status" in item:
            normalized["status"] = _single_line(item["status"], f"{label}.status", maximum=128)
        result.append(normalized)
    result.sort(key=lambda item: item["path"])
    return result


def normalize_record(value: Any) -> dict[str, Any]:
    item = _exact_keys(value, "checkpoint record", TOP_LEVEL_REQUIRED, TOP_LEVEL_OPTIONAL)
    schema_version = item["schema_version"]
    if isinstance(schema_version, bool) or schema_version != SCHEMA_VERSION:
        raise ResearchMemoryError(f"schema_version must be the integer {SCHEMA_VERSION}")
    checkpoint_id = _checkpoint_identifier(item["checkpoint_id"], "checkpoint_id")
    status_value = item["outcome_status"]
    if status_value not in OUTCOME_STATUSES:
        raise ResearchMemoryError(f"outcome_status must be one of {', '.join(OUTCOME_STATUSES)}")

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "checkpoint_id": checkpoint_id,
        "research_date": _research_date(item["research_date"]),
        "recorded_at_utc": _utc_timestamp(item["recorded_at_utc"]),
        "outcome_status": status_value,
        "target": _text(item["target"], "target"),
        "scope": _text(item["scope"], "scope"),
        "outcome": _normalize_outcome(item["outcome"]),
        "verification": _normalize_verification(item["verification"]),
        "continuation": _normalize_continuation(item["continuation"]),
        "discovery": _normalize_discovery(item["discovery"]),
    }

    for key in ("round_id", "run_id"):
        if key in item:
            result[key] = _identifier(item[key], key)
    if "track" in item:
        result["track"] = _single_line(item["track"], "track", maximum=256)
    for key in ("problem_ids", "claim_ids"):
        if key in item:
            result[key] = _id_list(item[key], key)
    for key in ("related_checkpoints", "supersedes"):
        if key in item:
            result[key] = _id_list(item[key], key, checkpoints=True)
    if checkpoint_id in result.get("related_checkpoints", []):
        raise ResearchMemoryError("related_checkpoints must not contain the current checkpoint_id")
    if checkpoint_id in result.get("supersedes", []):
        raise ResearchMemoryError("supersedes must not contain the current checkpoint_id")

    if status_value == "SUPERSEDED" and "supersedes" not in result:
        raise ResearchMemoryError(
            "outcome_status SUPERSEDED requires supersedes and revision_reason"
        )

    if "supersedes" in result:
        if "revision_reason" not in item:
            raise ResearchMemoryError("revision_reason is required when supersedes is present")
        result["revision_reason"] = _text(item["revision_reason"], "revision_reason", maximum=4096)
        if "revision_binding" not in item:
            raise ResearchMemoryError("revision_binding is required when supersedes is present")
        result["revision_binding"] = _normalize_revision_binding(item["revision_binding"])
        bound_predecessors = {
            binding["checkpoint_id"]
            for binding in result["revision_binding"]["predecessor_checkpoints"]
        }
        if bound_predecessors != set(result["supersedes"]):
            raise ResearchMemoryError(
                "revision_binding predecessor IDs must exactly equal supersedes"
            )
    elif "revision_reason" in item:
        raise ResearchMemoryError("revision_reason is only valid with supersedes")
    elif "revision_binding" in item:
        raise ResearchMemoryError("revision_binding is only valid with supersedes")

    if "source_status" in item:
        result["source_status"] = _single_line(item["source_status"], "source_status", maximum=256)
    if "target_bindings" in item:
        result["target_bindings"] = _normalize_target_bindings(item["target_bindings"])
    if "semantic_delta" in item:
        result["semantic_delta"] = _normalize_semantic_delta(item["semantic_delta"])

    section_normalizers = {
        "examples": _normalize_examples,
        "counterexamples": _normalize_counterexamples,
        "worked": _normalize_worked,
        "failed": _normalize_failed,
        "obstructions": _normalize_obstructions,
        "claims": _normalize_claims,
        "artifacts": _normalize_artifacts,
    }
    for key, normalizer in section_normalizers.items():
        if key in item:
            result[key] = normalizer(item[key])
    for key in ("useful_residue", "visibility_limitations"):
        if key in item:
            result[key] = _string_list(item[key], key)

    encoded = canonical_json_bytes(result)
    if len(encoded) > MAX_INPUT_BYTES:
        raise ResearchMemoryError("normalized checkpoint record exceeds its size bound")
    return result


def _escaped(value: str) -> str:
    return html.escape(value, quote=False)


def _block(lines: list[str], label: str, value: str) -> None:
    lines.extend([f"**{label}**", ""])
    for line in value.split("\n"):
        lines.append("> " + _escaped(line) if line else ">")
    lines.append("")


def _plain_list(lines: list[str], label: str, values: Sequence[str]) -> None:
    lines.append(f"- **{label}:** " + ", ".join(_escaped(value) for value in values))


def _artifact_paths(lines: list[str], values: Sequence[str]) -> None:
    if values:
        _plain_list(lines, "Artifact paths", values)


def _item_heading(lines: list[str], noun: str, index: int, item: dict[str, Any]) -> None:
    suffix = f" — `{item['id']}`" if "id" in item else ""
    lines.extend([f"### {noun} {index}{suffix}", ""])


def render_checkpoint(record: dict[str, Any]) -> bytes:
    record = normalize_record(record)
    research_date = record["research_date"]
    if isinstance(research_date, str):
        date_display = research_date
    else:
        date_display = f"{research_date['start']} through {research_date['end']}"

    lines = [
        f"# Research checkpoint: `{record['checkpoint_id']}`",
        "",
        "> Durable outcome envelope and artifact pointers; not a proof body, source",
        "> authority, status promotion, or record of private chain-of-thought.",
        "",
        COMMENT_START,
        _comment_json(record),
        COMMENT_END,
        "",
        "## Identity and provenance",
        "",
        f"- **Checkpoint ID:** `{record['checkpoint_id']}`",
        f"- **Research date:** {date_display}",
        f"- **Recorded at UTC:** `{record['recorded_at_utc']}`",
        f"- **Outcome status:** `{record['outcome_status']}`",
    ]
    for key, label in (("round_id", "Round ID"), ("run_id", "Run ID"), ("track", "Track")):
        if key in record:
            value = record[key]
            lines.append(f"- **{label}:** {_escaped(value)}")
    for key, label in (("problem_ids", "Problem IDs"), ("claim_ids", "Claim IDs")):
        if key in record:
            _plain_list(lines, label, record[key])
    if "target_bindings" in record:
        bindings: list[str] = []
        for binding in record["target_bindings"]:
            text = f"{binding.get('kind', 'TARGET')}:{binding['target_id']}"
            if "sha256" in binding:
                text += f" (sha256:{binding['sha256']})"
            bindings.append(text)
        _plain_list(lines, "Target bindings", bindings)
    if "source_status" in record:
        lines.append(f"- **Source-status vocabulary:** {_escaped(record['source_status'])}")
    if "related_checkpoints" in record:
        _plain_list(lines, "Related checkpoints", record["related_checkpoints"])
    if "supersedes" in record:
        _plain_list(lines, "Supersedes", record["supersedes"])
        lines.append(f"- **Revision reason:** {_escaped(record['revision_reason'])}")
        revision_binding = record["revision_binding"]
        for key, label in (
            ("finding", "Reviewer/finding evidence"),
            ("preimage", "Preserved preimage"),
            ("revision", "Correcting revision"),
        ):
            binding = revision_binding[key]
            lines.append(
                f"- **{label}:** `{binding['path']}` (`sha256:{binding['sha256']}`)"
            )
        predecessor_lines = [
            f"{binding['checkpoint_id']} (sha256:{binding['sha256']})"
            for binding in revision_binding["predecessor_checkpoints"]
        ]
        _plain_list(lines, "Bound predecessor checkpoint bytes", predecessor_lines)
    lines.append("")

    lines.extend(["## Exact target and scope", ""])
    _block(lines, "Exact target", record["target"])
    _block(lines, "Exact scope", record["scope"])

    lines.extend(["## Outcome", "", f"- **Disposition:** `{record['outcome_status']}`"])
    if "outcome_class" in record["outcome"]:
        lines.append(f"- **Local outcome class:** {_escaped(record['outcome']['outcome_class'])}")
    lines.append("")
    _block(lines, "Strongest exact result", record["outcome"]["summary"])
    if "generality" in record["outcome"]:
        _block(lines, "Generality established", record["outcome"]["generality"])
    if "remaining_unproved" in record["outcome"]:
        _block(lines, "Remaining unproved or unaudited", record["outcome"]["remaining_unproved"])

    lines.extend(["## Verification and independence", ""])
    lines.append(f"- **Verification state:** {_escaped(record['verification']['state'])}")
    lines.append("")
    _block(lines, "Verification summary", record["verification"]["summary"])
    if "independence" in record["verification"]:
        _block(lines, "Independence state", record["verification"]["independence"])
    for key, label in (("evidence", "Evidence"), ("limitations", "Verification limitations")):
        if key in record["verification"]:
            _plain_list(lines, label, record["verification"][key])
    lines.append("")

    if "semantic_delta" in record:
        lines.extend(["## Semantic dependency delta", ""])
        for index, delta in enumerate(record["semantic_delta"], start=1):
            lines.extend(
                [
                    f"### Dependency {index} — {_escaped(delta['dependency'])}",
                    "",
                    f"- **Change:** `{delta['change']}`",
                    "",
                ]
            )
            _block(lines, "Before", delta["before"])
            _block(lines, "After", delta["after"])

    if "examples" in record:
        lines.extend(["## Examples", ""])
        for index, item in enumerate(record["examples"], start=1):
            _item_heading(lines, "Example", index, item)
            _block(lines, "Summary", item["summary"])
            for key, label in (("purpose", "Purpose"), ("result", "Result")):
                if key in item:
                    _block(lines, label, item[key])
            _artifact_paths(lines, item.get("artifact_paths", []))
            lines.append("")

    if "counterexamples" in record:
        lines.extend(["## Counterexamples", ""])
        for index, item in enumerate(record["counterexamples"], start=1):
            _item_heading(lines, "Counterexample", index, item)
            _block(lines, "Refuted target", item["target"])
            _block(lines, "Exact example", item["example"])
            _block(lines, "Verification", item["verification"])
            _artifact_paths(lines, item.get("artifact_paths", []))
            lines.append("")

    if "worked" in record:
        lines.extend(["## Worked computations or constructions", ""])
        for index, item in enumerate(record["worked"], start=1):
            _item_heading(lines, "Worked item", index, item)
            _block(lines, "Task", item["task"])
            _block(lines, "Result", item["result"])
            if "verification" in item:
                _block(lines, "Verification", item["verification"])
            _artifact_paths(lines, item.get("artifact_paths", []))
            lines.append("")

    if "failed" in record:
        lines.extend(["## Failed routes", ""])
        for index, item in enumerate(record["failed"], start=1):
            _item_heading(lines, "Failed route", index, item)
            _block(lines, "Attempt", item["attempt"])
            _block(lines, "Exact reason", item["exact_reason"])
            for key, label in (("useful_residue", "Useful residue"), ("reopen_trigger", "Reopen trigger")):
                if key in item:
                    _block(lines, label, item[key])
            _artifact_paths(lines, item.get("artifact_paths", []))
            lines.append("")

    if "obstructions" in record:
        lines.extend(["## Obstructions", ""])
        for index, item in enumerate(record["obstructions"], start=1):
            _item_heading(lines, "Obstruction", index, item)
            _block(lines, "Description", item["description"])
            _block(lines, "Missing capability", item["missing_capability"])
            _block(lines, "Reopen trigger", item["reopen_trigger"])
            if "evidence" in item:
                _block(lines, "Evidence", item["evidence"])

    if "claims" in record:
        lines.extend(["## Claims", ""])
        for index, item in enumerate(record["claims"], start=1):
            lines.extend([f"### Claim {index} — `{item['claim_id']}`", ""])
            lines.append(f"- **Status:** {_escaped(item['status'])}")
            if "source_status" in item:
                lines.append(f"- **Source status:** {_escaped(item['source_status'])}")
            lines.append("")
            _block(lines, "Statement", item["statement"])
            if "verification" in item:
                _block(lines, "Verification", item["verification"])
            _artifact_paths(lines, item.get("artifact_paths", []))
            lines.append("")

    if "artifacts" in record:
        lines.extend(["## Canonical artifact references", ""])
        for index, item in enumerate(record["artifacts"], start=1):
            lines.extend([f"### Artifact {index} — `{item['path']}`", ""])
            _block(lines, "Role", item["role"])
            if "sha256" in item:
                lines.append(f"- **SHA-256:** `{item['sha256']}`")
            if "status" in item:
                lines.append(f"- **Status:** {_escaped(item['status'])}")
            lines.append("")

    if "useful_residue" in record:
        lines.extend(["## Useful residue", ""])
        for item in record["useful_residue"]:
            lines.append(f"- {_escaped(item)}")
        lines.append("")

    lines.extend(["## Continuation", ""])
    continuation = record["continuation"]
    for key, label in (
        ("next_action", "Next discriminating action"),
        ("cheapest_falsifier", "Cheapest falsifier"),
        ("success_criterion", "Success criterion"),
        ("stop_condition", "Stop condition"),
        ("reopen_condition", "Reopen condition"),
    ):
        if key in continuation:
            _block(lines, label, continuation[key])

    lines.extend(["## Discovery metadata", ""])
    discovery = record["discovery"]
    for key, label in (
        ("topics", "Topics"),
        ("objects", "Objects"),
        ("methods", "Methods"),
        ("keywords", "Keywords"),
        ("future_capabilities", "Future capabilities"),
    ):
        if key in discovery:
            _plain_list(lines, label, discovery[key])
    lines.append("")

    if "visibility_limitations" in record:
        lines.extend(["## Visibility limitations", ""])
        for item in record["visibility_limitations"]:
            lines.append(f"- {_escaped(item)}")
        lines.append("")

    rendered = "\n".join(lines).rstrip() + "\n"
    data = rendered.encode("utf-8")
    if len(data) > MAX_CHECKPOINT_BYTES:
        raise ResearchMemoryError("rendered checkpoint exceeds its size bound")
    return data


def _lstat(path: Path, label: str) -> os.stat_result:
    try:
        return path.lstat()
    except FileNotFoundError as exc:
        raise ResearchMemoryError(f"missing {label}: {path}") from exc
    except OSError as exc:
        raise ResearchMemoryError(f"cannot inspect {label}: {path}: {exc}") from exc


def _real_directory(path: Path, label: str) -> os.stat_result:
    info = _lstat(path, label)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ResearchMemoryError(f"{label} must be a real directory: {path}")
    return info


def _layout() -> tuple[Path, Path, Path]:
    root = ROOT
    research = root / "research"
    checkpoints = root / CHECKPOINT_DIRECTORY
    index = root / INDEX_RELATIVE
    active = _ACTIVE_LAYOUT.get()
    if active is not None and _CONTROL_ROOM_ROOT_FD is not None:
        infos = {}
        for key in ("root", "research", "checkpoints"):
            try:
                info = os.fstat(active[key])
            except OSError as exc:
                raise ResearchMemoryError(
                    f"pinned {key} directory is unavailable during the memory operation"
                ) from exc
            if not stat.S_ISDIR(info.st_mode):
                raise ResearchMemoryError(f"pinned {key} object is not a directory")
            infos[key] = info
    else:
        infos = {
            "root": _real_directory(root, "laboratory root"),
            "research": _real_directory(research, "research directory"),
            "checkpoints": _real_directory(checkpoints, "checkpoint directory"),
        }
    devices = {info.st_dev for info in infos.values()}
    if len(devices) != 1:
        raise ResearchMemoryError(
            "laboratory root, research, and checkpoint directories must share one device"
        )
    if active is not None:
        for key, info in infos.items():
            try:
                pinned = os.fstat(active[key])
            except OSError as exc:
                raise ResearchMemoryError(
                    f"pinned {key} directory is unavailable during the memory operation"
                ) from exc
            if (
                not stat.S_ISDIR(pinned.st_mode)
                or (pinned.st_dev, pinned.st_ino) != (info.st_dev, info.st_ino)
            ):
                raise ResearchMemoryError(
                    f"pinned {key} directory identity changed during the memory operation"
                )
    return research, checkpoints, index


def _open_directory(path: Path, info: os.stat_result, label: str) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ResearchMemoryError(f"cannot pin {label}: {path}: {exc}") from exc
    opened = os.fstat(descriptor)
    if not stat.S_ISDIR(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
        info.st_dev,
        info.st_ino,
    ):
        os.close(descriptor)
        raise ResearchMemoryError(f"{label} changed while being pinned: {path}")
    return descriptor


def _stat_at(
    directory_descriptor: int,
    name: str,
    label: str,
    *,
    missing_ok: bool = False,
) -> Optional[os.stat_result]:
    if not name or "/" in name or name in {".", ".."}:
        raise ResearchMemoryError(f"{label} has an unsafe direct-child name")
    try:
        return os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        if missing_ok:
            return None
        raise ResearchMemoryError(f"missing {label}: {name}")
    except OSError as exc:
        raise ResearchMemoryError(f"cannot inspect {label}: {name}: {exc}") from exc


def _open_directory_at(
    parent_descriptor: int,
    name: str,
    label: str,
) -> int:
    before = _stat_at(parent_descriptor, name, label)
    assert before is not None
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
        raise ResearchMemoryError(f"{label} must be a real directory: {name}")
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(name, flags, dir_fd=parent_descriptor)
    except OSError as exc:
        raise ResearchMemoryError(f"cannot pin {label}: {name}: {exc}") from exc
    opened = os.fstat(descriptor)
    if not stat.S_ISDIR(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
        before.st_dev,
        before.st_ino,
    ):
        os.close(descriptor)
        raise ResearchMemoryError(f"{label} changed while being pinned: {name}")
    return descriptor


def _active_descriptor(name: str) -> int:
    active = _ACTIVE_LAYOUT.get()
    if active is None or name not in active:
        raise ResearchMemoryError("research-memory filesystem operation lacks a pinned layout")
    return active[name]


@contextlib.contextmanager
def _memory_operation(*, exclusive: bool):
    """Pin local state directories and take one bounded advisory operation lock.

    The existing ``research/`` directory inode is the lock object.  This avoids
    creating a lock file during the strictly read-only ``search`` command while
    giving all script writers and readers one stable cross-process boundary.
    """

    root = ROOT
    descriptors: dict[str, int] = {}
    token = None
    locked = False
    try:
        if _CONTROL_ROOM_ROOT_FD is not None:
            inherited = {
                "root": _CONTROL_ROOM_ROOT_FD,
                "research": _CONTROL_ROOM_RESEARCH_FD,
                "checkpoints": _CONTROL_ROOM_CHECKPOINTS_FD,
            }
            for key, descriptor in inherited.items():
                if (
                    isinstance(descriptor, bool)
                    or not isinstance(descriptor, int)
                    or descriptor < 0
                ):
                    raise ResearchMemoryError(
                        f"inherited Control Room {key} descriptor is invalid"
                    )
                descriptors[key] = os.dup(descriptor)
                if not stat.S_ISDIR(os.fstat(descriptors[key]).st_mode):
                    raise ResearchMemoryError(
                        f"inherited Control Room {key} descriptor is not a directory"
                    )
        else:
            root_info = _real_directory(root, "laboratory root")
            descriptors["root"] = _open_directory(
                root, root_info, "laboratory root"
            )
            descriptors["research"] = _open_directory_at(
                descriptors["root"], "research", "research directory"
            )
            descriptors["checkpoints"] = _open_directory_at(
                descriptors["research"], "checkpoints", "checkpoint directory"
            )
        if len(
            {os.fstat(descriptor).st_dev for descriptor in descriptors.values()}
        ) != 1:
            raise ResearchMemoryError(
                "laboratory root, research, and checkpoint directories must share one device"
            )
        token = _ACTIVE_LAYOUT.set(dict(descriptors))
        _layout()

        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(descriptors["research"], operation | fcntl.LOCK_NB)
                locked = True
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    mode = "exclusive" if exclusive else "shared"
                    raise ResearchMemoryError(
                        f"timed out acquiring {mode} research-memory operation lock"
                    ) from exc
                time.sleep(LOCK_POLL_SECONDS)

        # A rename could have occurred while the lock was being acquired; only
        # the originally pinned directory identities are authorized.
        _layout()
        _recover_interrupted_publications_unlocked(repair=exclusive)
        try:
            yield
        finally:
            _layout()
    finally:
        if locked and "research" in descriptors:
            try:
                fcntl.flock(descriptors["research"], fcntl.LOCK_UN)
            except OSError:
                pass
        if token is not None:
            _ACTIVE_LAYOUT.reset(token)
        for descriptor in descriptors.values():
            try:
                os.close(descriptor)
            except OSError:
                pass


def _safe_read_bytes(
    path: Path,
    label: str,
    maximum: int,
    *,
    single_link: bool,
) -> bytes:
    before = _lstat(path, label)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ResearchMemoryError(f"{label} must be a real regular file: {path}")
    if single_link and before.st_nlink != 1:
        raise ResearchMemoryError(f"{label} must have exactly one hard link: {path}")
    if before.st_size > maximum:
        raise ResearchMemoryError(f"{label} exceeds its size bound: {path}")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ResearchMemoryError(f"cannot safely open {label}: {path}: {exc}") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ResearchMemoryError(f"{label} changed type while opening: {path}")
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ResearchMemoryError(f"{label} changed while opening: {path}")
        if single_link and opened.st_nlink != 1:
            raise ResearchMemoryError(f"{label} must have exactly one hard link: {path}")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > maximum:
            raise ResearchMemoryError(f"{label} exceeds its size bound: {path}")
        after = os.fstat(descriptor)
        if (
            after.st_size != opened.st_size
            or after.st_mtime_ns != opened.st_mtime_ns
            or after.st_nlink != opened.st_nlink
        ):
            raise ResearchMemoryError(f"{label} changed while being read: {path}")
        if len(data) != after.st_size:
            raise ResearchMemoryError(f"short read from {label}: {path}")
        return data
    finally:
        os.close(descriptor)


def _safe_read_at(
    directory_descriptor: int,
    name: str,
    label: str,
    maximum: int,
    *,
    single_link: bool,
) -> bytes:
    before = _stat_at(directory_descriptor, name, label)
    assert before is not None
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ResearchMemoryError(f"{label} must be a real regular file: {name}")
    if single_link and before.st_nlink != 1:
        raise ResearchMemoryError(f"{label} must have exactly one hard link: {name}")
    if before.st_size > maximum:
        raise ResearchMemoryError(f"{label} exceeds its size bound: {name}")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        descriptor = os.open(name, flags, dir_fd=directory_descriptor)
    except OSError as exc:
        raise ResearchMemoryError(f"cannot safely open {label}: {name}: {exc}") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ResearchMemoryError(f"{label} changed type while opening: {name}")
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ResearchMemoryError(f"{label} changed while opening: {name}")
        if single_link and opened.st_nlink != 1:
            raise ResearchMemoryError(f"{label} must have exactly one hard link: {name}")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > maximum:
            raise ResearchMemoryError(f"{label} exceeds its size bound: {name}")
        after = os.fstat(descriptor)
        stable_before = (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            stat.S_IMODE(opened.st_mode),
            opened.st_mtime_ns,
            opened.st_ctime_ns,
            opened.st_nlink,
        )
        stable_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            stat.S_IMODE(after.st_mode),
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_nlink,
        )
        if stable_before != stable_after:
            raise ResearchMemoryError(f"{label} changed while being read: {name}")
        if len(data) != after.st_size:
            raise ResearchMemoryError(f"short read from {label}: {name}")
        current = _stat_at(directory_descriptor, name, label)
        assert current is not None
        if (
            stat.S_ISLNK(current.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or not _same_file_state(after, current)
            or (single_link and current.st_nlink != 1)
        ):
            raise ResearchMemoryError(f"{label} changed after being read: {name}")
        return data
    finally:
        os.close(descriptor)


def _decode_utf8(data: bytes, label: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResearchMemoryError(f"{label} is not valid UTF-8") from exc


def parse_checkpoint(data: bytes, relative: str) -> dict[str, Any]:
    text = _decode_utf8(data, relative)
    start_token = COMMENT_START + "\n"
    end_token = "\n" + COMMENT_END
    if text.count(start_token) != 1:
        raise ResearchMemoryError(f"{relative} lacks exactly one designated v1 JSON comment")
    start = text.index(start_token) + len(start_token)
    end = text.find(end_token, start)
    if end < 0 or text.find(end_token, end + len(end_token)) >= 0:
        raise ResearchMemoryError(f"{relative} has an invalid designated JSON comment boundary")
    embedded = strict_json_loads(text[start:end], f"embedded record in {relative}")
    record = normalize_record(embedded)
    canonical = render_checkpoint(record)
    if data != canonical:
        raise ResearchMemoryError(f"{relative} is not the strict canonical rendering of its embedded record")
    return record


def _checkpoint_relative(checkpoint_path: str, checkpoint_id: Optional[str] = None) -> str:
    relative = _relative_path(checkpoint_path, "checkpoint_path")
    parts = relative.split("/")
    if len(parts) != 3 or parts[:2] != ["research", "checkpoints"]:
        raise ResearchMemoryError("checkpoint_path must be research/checkpoints/<checkpoint_id>.md")
    leaf = parts[2]
    if not leaf.endswith(".md") or leaf == "README.md":
        raise ResearchMemoryError("checkpoint_path must name a non-README Markdown checkpoint")
    stem = leaf[:-3]
    _checkpoint_identifier(stem, "checkpoint filename ID")
    if checkpoint_id is not None and stem != checkpoint_id:
        raise ResearchMemoryError("checkpoint filename must exactly match checkpoint_id")
    return relative


def _read_checkpoint_records(*, recover: bool = False) -> tuple[list[dict[str, Any]], list[str]]:
    _layout()
    checkpoints_descriptor = _active_descriptor("checkpoints")
    try:
        entries = []
        with os.scandir(checkpoints_descriptor) as scan:
            for entry in scan:
                # Count malformed entries too; recovery must not bypass bounds.
                if len(entries) >= MAX_CHECKPOINTS + 2:  # README and .DS_Store
                    raise ResearchMemoryError("checkpoint inventory exceeds its record count bound")
                entries.append(entry)
        entries.sort(key=lambda item: item.name)
    except OSError as exc:
        raise ResearchMemoryError(f"cannot inventory checkpoint directory: {exc}") from exc
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    total = 0
    attempted = 0
    seen_ids: set[str] = set()
    for entry in entries:
        if entry.name == ".DS_Store":
            # Ignore only ordinary Finder metadata. A symlink or special file
            # with the same name is still unsafe, and no metadata is followed.
            _safe_read_at(checkpoints_descriptor, entry.name, "Finder metadata",
                          MAX_CHECKPOINT_BYTES, single_link=True)
            continue
        if entry.name == "README.md":
            _safe_read_at(
                checkpoints_descriptor,
                entry.name,
                "checkpoint README",
                MAX_CHECKPOINT_BYTES,
                single_link=True,
            )
            continue
        attempted += 1
        if attempted > MAX_CHECKPOINTS:
            raise ResearchMemoryError("checkpoint inventory exceeds its record count bound")
        relative = f"research/checkpoints/{entry.name}"
        data = _safe_read_at(
            checkpoints_descriptor,
            entry.name,
            f"checkpoint {relative}",
            MAX_CHECKPOINT_BYTES,
            single_link=True,
        )
        total += len(data)
        if total > MAX_CHECKPOINT_TOTAL_BYTES:
            raise ResearchMemoryError("checkpoint inventory exceeds its total byte bound")
        try:
            _checkpoint_relative(relative)
            record = parse_checkpoint(data, relative)
            if record["checkpoint_id"] != entry.name[:-3]:
                raise ResearchMemoryError(f"{relative} does not match its embedded checkpoint_id")
        except ResearchMemoryError as exc:
            if not recover:
                raise
            warnings.append(f"{relative}: omitted from search: {_summary(str(exc))}")
            continue
        if record["checkpoint_id"] in seen_ids:
            raise ResearchMemoryError(f"duplicate checkpoint_id: {record['checkpoint_id']}")
        seen_ids.add(record["checkpoint_id"])
        records.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": data,
                "record": record,
            }
        )
    return records, warnings


def _checkpoint_inventory(*, verify_artifacts: bool = True) -> list[dict[str, Any]]:
    records, _warnings = _read_checkpoint_records()
    _validate_links(records)
    if verify_artifacts:
        for item in records:
            _validate_record_file_bindings(item["record"])
    return records


def _validate_links(records: Sequence[dict[str, Any]]) -> None:
    by_id = {item["record"]["checkpoint_id"]: item for item in records}
    for checkpoint_id, stored in by_id.items():
        record = stored["record"]
        for key in ("related_checkpoints", "supersedes"):
            for linked in record.get(key, []):
                if linked not in by_id:
                    raise ResearchMemoryError(
                        f"checkpoint {checkpoint_id} has missing local {key} link: {linked}"
                    )

    # Use an explicit DFS stack: a valid laboratory may contain thousands of
    # linked checkpoints, which must not inherit Python's much smaller call-
    # stack limit. State 1 is active on the current path; state 2 is complete.
    state: dict[str, int] = {}
    for starting_id in sorted(by_id):
        if state.get(starting_id, 0) == 2:
            continue
        stack: list[tuple[str, int]] = [(starting_id, 0)]
        path: list[str] = []
        path_position: dict[str, int] = {}
        while stack:
            checkpoint_id, next_index = stack[-1]
            if state.get(checkpoint_id, 0) == 0:
                state[checkpoint_id] = 1
                path_position[checkpoint_id] = len(path)
                path.append(checkpoint_id)
            predecessors = by_id[checkpoint_id]["record"].get("supersedes", [])
            if next_index < len(predecessors):
                predecessor = predecessors[next_index]
                stack[-1] = (checkpoint_id, next_index + 1)
                predecessor_state = state.get(predecessor, 0)
                if predecessor_state == 0:
                    stack.append((predecessor, 0))
                    continue
                if predecessor_state == 1:
                    cycle_start = path_position[predecessor]
                    cycle = " -> ".join(path[cycle_start:] + [predecessor])
                    raise ResearchMemoryError(
                        f"supersession cycle detected: {cycle}"
                    )
                continue
            stack.pop()
            completed = path.pop()
            if completed != checkpoint_id:
                raise ResearchMemoryError("internal supersession traversal mismatch")
            path_position.pop(checkpoint_id, None)
            state[checkpoint_id] = 2

    for checkpoint_id, stored in by_id.items():
        record = stored["record"]
        revision_binding = record.get("revision_binding")
        if revision_binding is None:
            continue
        expected = {
            binding["checkpoint_id"]: binding["sha256"]
            for binding in revision_binding["predecessor_checkpoints"]
        }
        if set(expected) != set(record.get("supersedes", [])):
            raise ResearchMemoryError(
                f"checkpoint {checkpoint_id} revision predecessor bindings do not match supersedes"
            )
        for predecessor_id, digest in expected.items():
            actual_digest = by_id[predecessor_id].get("sha256")
            if actual_digest is not None and digest != actual_digest:
                raise ResearchMemoryError(
                    f"checkpoint {checkpoint_id} predecessor checkpoint SHA-256 does not match"
                )


def _dependencies(record: dict[str, Any]) -> set[str]:
    return set(record.get("related_checkpoints", [])) | set(record.get("supersedes", []))


def _required_checkpoint_ids(records: Sequence[dict[str, Any]], checkpoint_id: str) -> set[str]:
    """Return the explicit dependency closure of one structurally valid record."""
    by_id = {item["record"]["checkpoint_id"]: item["record"] for item in records}
    pending = [checkpoint_id]
    required: set[str] = set()
    while pending:
        current = pending.pop()
        if current in required:
            continue
        if current not in by_id:
            raise ResearchMemoryError(f"missing required checkpoint: {current}")
        required.add(current)
        pending.extend(_dependencies(by_id[current]) - required)
    return required


def _verify_required_evidence(records: Sequence[dict[str, Any]], checkpoint_id: str) -> None:
    required = _required_checkpoint_ids(records, checkpoint_id)
    for item in records:
        if item["record"]["checkpoint_id"] in required:
            _validate_record_file_bindings(item["record"])


def _unrelated_evidence_warnings(records: Sequence[dict[str, Any]], checkpoint_id: str) -> list[str]:
    required = _required_checkpoint_ids(records, checkpoint_id)
    warnings: list[str] = []
    for item in records:
        if item["record"]["checkpoint_id"] in required:
            continue
        try:
            _validate_record_file_bindings(item["record"])
        except CheckpointEvidenceError as exc:
            warnings.append(f"{item['path']}: evidence requires review: {_summary(str(exc))}")
    return warnings


def _recover_search_records() -> tuple[list[dict[str, Any]], list[str]]:
    records, warnings = _read_checkpoint_records(recover=True)
    by_id = {item["record"]["checkpoint_id"]: item for item in records}
    errors: dict[str, str] = {}
    dependents: dict[str, set[str]] = {key: set() for key in by_id}
    successors: dict[str, set[str]] = {key: set() for key in by_id}
    predecessor_counts: dict[str, int] = {}
    for checkpoint_id, item in by_id.items():
        record = item["record"]
        try:
            _validate_record_file_bindings(record)
        except CheckpointEvidenceError as exc:
            errors[checkpoint_id] = str(exc)
        for dependency in sorted(_dependencies(record)):
            if dependency not in by_id:
                errors.setdefault(checkpoint_id, f"missing or damaged linked checkpoint: {dependency}")
            else:
                dependents[dependency].add(checkpoint_id)
        predecessors = record.get("supersedes", [])
        predecessor_counts[checkpoint_id] = sum(value in by_id for value in predecessors)
        for predecessor in predecessors:
            if predecessor in by_id:
                successors[predecessor].add(checkpoint_id)
        revision = record.get("revision_binding")
        if revision is not None:
            expected = {value["checkpoint_id"]: value["sha256"]
                        for value in revision["predecessor_checkpoints"]}
            if set(expected) != set(predecessors):
                errors.setdefault(checkpoint_id, "revision predecessor bindings do not match supersedes")
            for predecessor, digest in expected.items():
                if predecessor in by_id and by_id[predecessor]["sha256"] != digest:
                    errors.setdefault(checkpoint_id, "predecessor checkpoint SHA-256 does not match")

    # Removing nodes with no predecessors detects cycles and their descendants
    # without recursion or repeatedly walking every record's full history.
    ready = deque(sorted(key for key, count in predecessor_counts.items() if not count))
    visited: set[str] = set()
    while ready:
        current = ready.popleft()
        visited.add(current)
        for successor in sorted(successors[current]):
            predecessor_counts[successor] -= 1
            if not predecessor_counts[successor]:
                ready.append(successor)
    for checkpoint_id in sorted(set(by_id) - visited):
        errors.setdefault(checkpoint_id, "supersession cycle or dependency on one")
    pending = deque(sorted(errors))
    while pending:
        unavailable = pending.popleft()
        for dependent in sorted(dependents[unavailable]):
            if dependent not in errors:
                errors[dependent] = f"depends on unavailable checkpoint: {unavailable}"
                pending.append(dependent)
    for checkpoint_id in sorted(errors):
        warnings.append(f"{by_id[checkpoint_id]['path']}: omitted from search: {_summary(errors[checkpoint_id])}")
    healthy = [item for item in records if item["record"]["checkpoint_id"] not in errors]
    _validate_links(healthy)
    return healthy, warnings


def _safe_read_bound_artifact(relative: str, label: str) -> bytes:
    parts = PurePosixPath(_relative_path(relative, label)).parts
    descriptor = os.dup(_active_descriptor("root"))
    opened: list[int] = [descriptor]
    try:
        for index, part in enumerate(parts[:-1]):
            if _stat_at(descriptor, part, label, missing_ok=True) is None:
                raise CheckpointEvidenceError(f"missing {label}: {relative}")
            descriptor = _open_directory_at(
                descriptor,
                part,
                f"{label} parent component {index}",
            )
            opened.append(descriptor)
        if _stat_at(descriptor, parts[-1], label, missing_ok=True) is None:
            raise CheckpointEvidenceError(f"missing {label}: {relative}")
        return _safe_read_at(
            descriptor,
            parts[-1],
            label,
            MAX_BOUND_ARTIFACT_BYTES,
            single_link=False,
        )
    finally:
        for opened_descriptor in reversed(opened):
            os.close(opened_descriptor)


def _verify_exact_file_binding(binding: dict[str, str], label: str) -> None:
    data = _safe_read_bound_artifact(binding["path"], label)
    if hashlib.sha256(data).hexdigest() != binding["sha256"]:
        raise CheckpointEvidenceError(f"{label} SHA-256 does not match the bound bytes")


def _validate_record_file_bindings(record: dict[str, Any]) -> None:
    bindings: list[tuple[dict[str, str], str]] = []
    for index, artifact in enumerate(record.get("artifacts", [])):
        if "sha256" in artifact:
            bindings.append((artifact, f"artifacts[{index}]"))
    revision_binding = record.get("revision_binding")
    if revision_binding is not None:
        for key in ("finding", "preimage", "revision"):
            bindings.append((revision_binding[key], f"revision_binding.{key}"))
    first_evidence_error: Optional[CheckpointEvidenceError] = None
    for binding, label in bindings:
        try:
            _verify_exact_file_binding(binding, label)
        except CheckpointEvidenceError as exc:
            # A recoverable first failure must not mask a later unsafe file.
            # Safety/resource errors propagate immediately; inspect all other
            # bindings before reporting missing or changed evidence.
            if first_evidence_error is None:
                first_evidence_error = exc
    if first_evidence_error is not None:
        raise first_evidence_error


def _summary(value: str, maximum: int = 512) -> str:
    compact = " ".join(value.split())
    if len(compact) <= maximum:
        return compact
    return compact[: maximum - 1].rstrip() + "…"


def _index_entry(item: dict[str, Any]) -> dict[str, Any]:
    record = item["record"]
    discovery = record["discovery"]
    entry: dict[str, Any] = {
        "checkpoint_id": record["checkpoint_id"],
        "path": item["path"],
        "sha256": item["sha256"],
        "research_date": record["research_date"],
        "recorded_at_utc": record["recorded_at_utc"],
        "outcome_status": record["outcome_status"],
        "target_summary": _summary(record["target"]),
        "outcome_summary": _summary(record["outcome"]["summary"]),
        "verification_state": record["verification"]["state"],
        "topics": discovery["topics"],
        "objects": discovery.get("objects", []),
        "methods": discovery.get("methods", []),
        "keywords": discovery.get("keywords", []),
        "obstructions": sorted(
            {value["description"] for value in record.get("obstructions", [])},
            key=lambda value: (value.casefold(), value),
        ),
        "future_capabilities": sorted(
            {
                *(value for value in discovery.get("future_capabilities", [])),
                *(
                    value["missing_capability"]
                    for value in record.get("obstructions", [])
                ),
            },
            key=lambda value: (value.casefold(), value),
        ),
        "reopen_triggers": sorted(
            {
                *(
                    [record["continuation"]["reopen_condition"]]
                    if "reopen_condition" in record["continuation"]
                    else []
                ),
                *(
                    value["reopen_trigger"]
                    for value in record.get("failed", [])
                    if "reopen_trigger" in value
                ),
                *(
                    value["reopen_trigger"]
                    for value in record.get("obstructions", [])
                ),
            },
            key=lambda value: (value.casefold(), value),
        ),
    }
    for key in (
        "round_id",
        "run_id",
        "track",
        "problem_ids",
        "claim_ids",
        "related_checkpoints",
        "supersedes",
        "source_status",
        "target_bindings",
    ):
        if key in record:
            entry[key] = record[key]
    if "revision_reason" in record:
        entry["revision_reason_summary"] = _summary(record["revision_reason"], 256)
    if "artifacts" in record:
        entry["artifact_paths"] = [value["path"] for value in record["artifacts"]]
    return entry


def build_index(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    entries = [_index_entry(item) for item in records]
    superseded_by: dict[str, list[str]] = {}
    for item in records:
        successor = item["record"]["checkpoint_id"]
        for predecessor in item["record"].get("supersedes", []):
            superseded_by.setdefault(predecessor, []).append(successor)
    for entry in entries:
        successors = superseded_by.get(entry["checkpoint_id"])
        if successors:
            entry["superseded_by"] = sorted(successors)
    entries.sort(key=lambda item: (item["recorded_at_utc"], item["checkpoint_id"], item["path"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "checkpoint_count": len(entries),
        "entries": entries,
    }


def _existing_safe_file_at(
    directory_descriptor: int,
    name: str,
    label: str,
) -> Optional[os.stat_result]:
    info = _stat_at(
        directory_descriptor,
        name,
        label,
        missing_ok=True,
    )
    if info is None:
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ResearchMemoryError(f"{label} must be a real regular file: {name}")
    if info.st_nlink != 1:
        raise ResearchMemoryError(f"{label} must have exactly one hard link: {name}")
    return info


def _same_file_state(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_size,
        stat.S_IMODE(left.st_mode),
        left.st_mtime_ns,
        left.st_ctime_ns,
        left.st_nlink,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_size,
        stat.S_IMODE(right.st_mode),
        right.st_mtime_ns,
        right.st_ctime_ns,
        right.st_nlink,
    )


def _temporary_file_at(directory_descriptor: int, prefix: str) -> tuple[int, str]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    for _attempt in range(128):
        name = prefix + secrets.token_hex(16)
        try:
            descriptor = os.open(
                name,
                flags,
                0o600,
                dir_fd=directory_descriptor,
            )
        except FileExistsError:
            continue
        except OSError as exc:
            raise ResearchMemoryError(
                f"cannot create a descriptor-rooted temporary file: {exc}"
            ) from exc
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            os.close(descriptor)
            try:
                os.unlink(name, dir_fd=directory_descriptor)
            except OSError:
                pass
            raise ResearchMemoryError("descriptor-rooted temporary file is unsafe")
        return descriptor, name
    raise ResearchMemoryError("cannot allocate a unique descriptor-rooted temporary file")


def _write_all(descriptor: int, data: bytes, label: str) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise ResearchMemoryError(f"short write while staging {label}")
        view = view[written:]


def _unlink_at(directory_descriptor: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=directory_descriptor)
    except FileNotFoundError:
        pass


def _verify_exact_file_at(
    directory_descriptor: int,
    name: str,
    label: str,
    expected: bytes,
    *,
    expected_identity: Optional[tuple[int, int]] = None,
) -> os.stat_result:
    data = _safe_read_at(
        directory_descriptor,
        name,
        label,
        len(expected),
        single_link=True,
    )
    if data != expected:
        raise ResearchMemoryError(f"{label} does not contain the exact staged bytes")
    info = _existing_safe_file_at(directory_descriptor, name, label)
    assert info is not None
    if expected_identity is not None and (info.st_dev, info.st_ino) != expected_identity:
        raise ResearchMemoryError(f"{label} is not the exact staged file")
    return info


def _staging_kind(name: str) -> Optional[str]:
    if name.startswith(CHECKPOINT_STAGING_PREFIX):
        if CHECKPOINT_STAGING_RE.fullmatch(name):
            return "checkpoint"
        raise ResearchMemoryError(
            f"invalid reserved checkpoint staging name: {name}"
        )
    if name.startswith(INDEX_STAGING_PREFIX):
        if INDEX_STAGING_RE.fullmatch(name):
            return "index"
        raise ResearchMemoryError(f"invalid reserved index staging name: {name}")
    return None


def _directory_child_names(directory_descriptor: int, label: str) -> list[str]:
    try:
        return sorted(entry.name for entry in os.scandir(directory_descriptor))
    except OSError as exc:
        raise ResearchMemoryError(f"cannot scan {label}: {exc}") from exc


def _classify_interrupted_publications() -> list[dict[str, Any]]:
    """Preflight every helper-owned residue before any recovery write."""

    _layout()
    research_descriptor = _active_descriptor("research")
    checkpoints_descriptor = _active_descriptor("checkpoints")
    research_names = _directory_child_names(
        research_descriptor,
        "research directory for interrupted publications",
    )
    checkpoint_names = _directory_child_names(
        checkpoints_descriptor,
        "checkpoint directory for interrupted publications",
    )
    plans: list[dict[str, Any]] = []
    for name in research_names:
        kind = _staging_kind(name)
        if kind is None:
            continue
        info = _stat_at(
            research_descriptor,
            name,
            f"interrupted {kind} staging file",
        )
        assert info is not None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ResearchMemoryError(
                f"interrupted {kind} staging object must be a regular file: {name}"
            )
        mode = stat.S_IMODE(info.st_mode)
        if mode not in {0o600, 0o644}:
            raise ResearchMemoryError(
                f"interrupted {kind} staging file has an unsafe mode: {name}"
            )
        if kind == "index":
            if info.st_nlink != 1:
                raise ResearchMemoryError(
                    f"interrupted index staging file has an unsafe link count: {name}"
                )
            plans.append(
                {"kind": kind, "name": name, "staging_info": info}
            )
            continue
        if info.st_nlink == 1:
            plans.append(
                {"kind": kind, "name": name, "staging_info": info}
            )
            continue
        if info.st_nlink != 2 or mode != 0o644:
            raise ResearchMemoryError(
                f"interrupted checkpoint staging file has an unsafe link count or mode: {name}"
            )

        identity = (info.st_dev, info.st_ino)
        matches: list[tuple[str, os.stat_result]] = []
        for checkpoint_name in checkpoint_names:
            target_info = _stat_at(
                checkpoints_descriptor,
                checkpoint_name,
                "checkpoint candidate during interrupted-publication recovery",
            )
            assert target_info is not None
            if (target_info.st_dev, target_info.st_ino) == identity:
                matches.append((checkpoint_name, target_info))
        if len(matches) != 1:
            raise ResearchMemoryError(
                f"interrupted checkpoint staging file does not have one exact checkpoint link: {name}"
            )
        target_name, target_info = matches[0]
        if (
            not stat.S_ISREG(target_info.st_mode)
            or target_info.st_nlink != 2
            or stat.S_IMODE(target_info.st_mode) != 0o644
        ):
            raise ResearchMemoryError(
                f"interrupted checkpoint target is unsafe: {target_name}"
            )
        relative = _checkpoint_relative(
            f"research/checkpoints/{target_name}"
        )
        data = _safe_read_at(
            checkpoints_descriptor,
            target_name,
            "interrupted checkpoint target",
            MAX_CHECKPOINT_BYTES,
            single_link=False,
        )
        record = parse_checkpoint(data, relative)
        if record["checkpoint_id"] != target_name[:-3]:
            raise ResearchMemoryError(
                f"interrupted checkpoint target filename does not bind its record: {target_name}"
            )
        current_staging = _stat_at(
            research_descriptor,
            name,
            "interrupted checkpoint staging file",
        )
        assert current_staging is not None
        if not _same_file_state(info, current_staging):
            raise ResearchMemoryError(
                f"interrupted checkpoint staging file changed during preflight: {name}"
            )
        plans.append(
            {
                "kind": kind,
                "name": name,
                "staging_info": current_staging,
                "target_name": target_name,
                "target_info": target_info,
                "data": data,
            }
        )
    return plans


def _revalidate_recovery_plan(plan: dict[str, Any]) -> None:
    research_descriptor = _active_descriptor("research")
    current = _stat_at(
        research_descriptor,
        plan["name"],
        "interrupted publication staging file",
    )
    assert current is not None
    if not _same_file_state(plan["staging_info"], current):
        raise ResearchMemoryError(
            f"interrupted publication changed after preflight: {plan['name']}"
        )
    if "target_name" in plan:
        target = _stat_at(
            _active_descriptor("checkpoints"),
            plan["target_name"],
            "interrupted checkpoint target",
        )
        assert target is not None
        if not _same_file_state(plan["target_info"], target):
            raise ResearchMemoryError(
                "interrupted checkpoint target changed after preflight: "
                + plan["target_name"]
            )


def _recover_interrupted_publications_unlocked(*, repair: bool) -> None:
    plans = _classify_interrupted_publications()
    if not plans:
        return
    if not repair:
        raise ResearchMemoryError(
            "interrupted research-memory publication requires an exclusive "
            "record or rebuild-index recovery"
        )

    research_descriptor = _active_descriptor("research")
    checkpoints_descriptor = _active_descriptor("checkpoints")
    for plan in plans:
        _revalidate_recovery_plan(plan)
        if "target_name" in plan:
            # The destination link is the commit point. Persist it again before
            # removing the staging link left by a process death.
            os.fsync(checkpoints_descriptor)
        try:
            os.unlink(plan["name"], dir_fd=research_descriptor)
        except OSError as exc:
            raise ResearchMemoryError(
                f"cannot recover interrupted publication {plan['name']}: {exc}"
            ) from exc
        os.fsync(research_descriptor)
        if "target_name" in plan:
            target = _stat_at(
                checkpoints_descriptor,
                plan["target_name"],
                "recovered checkpoint target",
            )
            assert target is not None
            expected = plan["target_info"]
            if (
                not stat.S_ISREG(target.st_mode)
                or (target.st_dev, target.st_ino)
                != (expected.st_dev, expected.st_ino)
                or target.st_nlink != 1
                or stat.S_IMODE(target.st_mode) != 0o644
            ):
                raise ResearchMemoryError(
                    "recovered checkpoint target did not become one exact single-link file"
                )
            recovered = _safe_read_at(
                checkpoints_descriptor,
                plan["target_name"],
                "recovered checkpoint target",
                MAX_CHECKPOINT_BYTES,
                single_link=True,
            )
            if recovered != plan["data"]:
                raise ResearchMemoryError(
                    "recovered checkpoint target bytes changed during recovery"
                )
        elif _stat_at(
            research_descriptor,
            plan["name"],
            "recovered staging name",
            missing_ok=True,
        ) is not None:
            raise ResearchMemoryError(
                f"interrupted staging name remained after recovery: {plan['name']}"
            )
    if _classify_interrupted_publications():
        raise ResearchMemoryError(
            "interrupted research-memory publication recovery did not converge"
        )


def _atomic_replace_index(data: bytes) -> None:
    _layout()
    research_descriptor = _active_descriptor("research")
    index_name = INDEX_RELATIVE.name
    if len(data) > MAX_INDEX_BYTES:
        raise ResearchMemoryError("derived index exceeds its size bound")
    before = _existing_safe_file_at(
        research_descriptor,
        index_name,
        "checkpoint index",
    )
    descriptor, temporary_name = _temporary_file_at(
        research_descriptor,
        ".checkpoint-index-",
    )
    try:
        os.fchmod(descriptor, 0o644)
        _write_all(descriptor, data, "checkpoint index")
        os.fsync(descriptor)
        staged = os.fstat(descriptor)
        if not stat.S_ISREG(staged.st_mode) or staged.st_nlink != 1:
            raise ResearchMemoryError("staged checkpoint index is unsafe")

        current = _existing_safe_file_at(
            research_descriptor,
            index_name,
            "checkpoint index",
        )
        if before is None and current is not None:
            raise ResearchMemoryError("checkpoint index appeared during rebuild")
        if before is not None and (current is None or not _same_file_state(before, current)):
            raise ResearchMemoryError("checkpoint index changed during rebuild")
        try:
            os.replace(
                temporary_name,
                index_name,
                src_dir_fd=research_descriptor,
                dst_dir_fd=research_descriptor,
            )
        except OSError as exc:
            raise ResearchMemoryError(
                f"cannot atomically publish the checkpoint index: {exc}"
            ) from exc
        _verify_exact_file_at(
            research_descriptor,
            index_name,
            "published checkpoint index",
            data,
            expected_identity=(staged.st_dev, staged.st_ino),
        )
        os.fsync(research_descriptor)
    finally:
        os.close(descriptor)
        _unlink_at(research_descriptor, temporary_name)


def _rebuild_index_unlocked() -> dict[str, Any]:
    # A complete structural index is navigation, not evidence certification.
    records = _checkpoint_inventory(verify_artifacts=False)
    index = build_index(records)
    _atomic_replace_index(canonical_json_bytes(index))
    return index


def rebuild_index() -> dict[str, Any]:
    with _memory_operation(exclusive=True):
        return _rebuild_index_unlocked()


def _validated_memory_state_unlocked(*, verify_artifacts: bool = True) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    records = _checkpoint_inventory(verify_artifacts=verify_artifacts)
    expected = build_index(records)
    _layout()
    actual_bytes = _safe_read_at(
        _active_descriptor("research"),
        INDEX_RELATIVE.name,
        "checkpoint index",
        MAX_INDEX_BYTES,
        single_link=True,
    )
    # Parse independently for clear duplicate-key/UTF-8 diagnostics, then bind
    # exact bytes so formatting and freshness are both deterministic.
    actual = strict_json_loads(_decode_utf8(actual_bytes, "checkpoint index"), "checkpoint index")
    if actual != expected or actual_bytes != canonical_json_bytes(expected):
        raise ResearchMemoryError("checkpoint index is stale or non-canonical; run rebuild-index")
    return expected, records


def _validate_memory_unlocked() -> dict[str, Any]:
    index, _records = _validated_memory_state_unlocked()
    return index


def validate_memory() -> dict[str, Any]:
    with _memory_operation(exclusive=False):
        return _validate_memory_unlocked()


def validate_control_room(
    checkpoint_path: str,
    checkpoint_id: str,
    round_id: str,
    run_id: str,
) -> dict[str, Any]:
    expected_checkpoint_id = _checkpoint_identifier(
        checkpoint_id,
        "checkpoint_id",
    )
    expected_round_id = _identifier(round_id, "round_id")
    expected_run_id = _identifier(run_id, "run_id")
    relative = _checkpoint_relative(checkpoint_path, expected_checkpoint_id)
    with _memory_operation(exclusive=False):
        index, records = _validated_memory_state_unlocked(verify_artifacts=False)
        matches = [
            item
            for item in records
            if item["path"] == relative
            and item["record"]["checkpoint_id"] == expected_checkpoint_id
        ]
        if len(matches) != 1:
            raise ResearchMemoryError(
                "the exact Control Room checkpoint is absent from canonical memory"
            )
        record = matches[0]["record"]
        if record.get("round_id") != expected_round_id:
            raise ResearchMemoryError(
                "the Control Room checkpoint does not bind the exact round_id"
            )
        if record.get("run_id") != expected_run_id:
            raise ResearchMemoryError(
                "the Control Room checkpoint does not bind the exact run_id"
            )
        _verify_required_evidence(records, expected_checkpoint_id)
        checkpoint_bytes = matches[0]["bytes"]
        index_bytes = canonical_json_bytes(index)
        return {
            "status": "VALID",
            "checkpoint_count": index["checkpoint_count"],
            "checkpoint_id": expected_checkpoint_id,
            "checkpoint_path": relative,
            "checkpoint_sha256": hashlib.sha256(checkpoint_bytes).hexdigest(),
            "checkpoint_size": len(checkpoint_bytes),
            "index_path": INDEX_RELATIVE.as_posix(),
            "index_sha256": hashlib.sha256(index_bytes).hexdigest(),
            "index_size": len(index_bytes),
            "round_id": expected_round_id,
            "run_id": expected_run_id,
        }


def inspect_control_room_checkpoint(
    checkpoint_path: str,
    checkpoint_id: str,
    round_id: str,
    run_id: str,
) -> dict[str, Any]:
    """Validate one canonical checkpoint independently of the derived index."""

    expected_checkpoint_id = _checkpoint_identifier(checkpoint_id, "checkpoint_id")
    expected_round_id = _identifier(round_id, "round_id")
    expected_run_id = _identifier(run_id, "run_id")
    relative = _checkpoint_relative(checkpoint_path, expected_checkpoint_id)
    with _memory_operation(exclusive=False):
        records = _checkpoint_inventory(verify_artifacts=False)
        matches = [
            item
            for item in records
            if item["path"] == relative
            and item["record"]["checkpoint_id"] == expected_checkpoint_id
        ]
        if len(matches) != 1:
            raise ResearchMemoryError(
                "the exact Control Room checkpoint is not one canonical checkpoint"
            )
        match = matches[0]
        _verify_required_evidence(records, expected_checkpoint_id)
        checkpoint_bytes = match["bytes"]
        record = match["record"]
        return {
            "status": "VALID_CHECKPOINT",
            "checkpoint_id": expected_checkpoint_id,
            "checkpoint_path": relative,
            "checkpoint_sha256": hashlib.sha256(checkpoint_bytes).hexdigest(),
            "checkpoint_size": len(checkpoint_bytes),
            "round_id_matches": record.get("round_id") == expected_round_id,
            "run_id_matches": record.get("run_id") == expected_run_id,
        }


def _read_input(path_value: str) -> dict[str, Any]:
    if path_value == "-":
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        raw = stream.read(MAX_INPUT_BYTES + 1)
        if isinstance(raw, str):
            data = raw.encode("utf-8")
        else:
            data = raw
        if len(data) > MAX_INPUT_BYTES:
            raise ResearchMemoryError("standard-input JSON exceeds its size bound")
    else:
        data = _safe_read_bytes(
            Path(path_value),
            "checkpoint input",
            MAX_INPUT_BYTES,
            single_link=False,
        )
    parsed = strict_json_loads(_decode_utf8(data, "checkpoint input"), "checkpoint input")
    return normalize_record(parsed)


def _prospective_records(
    existing: Sequence[dict[str, Any]],
    relative: str,
    record: dict[str, Any],
    rendered: bytes,
) -> list[dict[str, Any]]:
    result = list(existing)
    for item in result:
        if item["record"]["checkpoint_id"] == record["checkpoint_id"]:
            if item["path"] != relative or item["bytes"] != rendered:
                raise ResearchMemoryError(f"checkpoint_id already exists with different bytes: {record['checkpoint_id']}")
            _validate_links(result)
            return result
    if len(result) >= MAX_CHECKPOINTS:
        raise ResearchMemoryError(
            "prospective checkpoint inventory exceeds its count bound"
        )
    prospective_total = sum(len(item["bytes"]) for item in result) + len(rendered)
    if prospective_total > MAX_CHECKPOINT_TOTAL_BYTES:
        raise ResearchMemoryError(
            "prospective checkpoint inventory exceeds its total size bound"
        )
    result.append(
        {
            "path": relative,
            "sha256": hashlib.sha256(rendered).hexdigest(),
            "bytes": rendered,
            "record": record,
        }
    )
    _validate_links(result)
    return result


def _publish_checkpoint(relative: str, data: bytes) -> bool:
    _layout()
    research_descriptor = _active_descriptor("research")
    checkpoints_descriptor = _active_descriptor("checkpoints")
    target_name = PurePosixPath(relative).name
    current = _existing_safe_file_at(
        checkpoints_descriptor,
        target_name,
        "checkpoint target",
    )
    if current is not None:
        existing = _safe_read_at(
            checkpoints_descriptor,
            target_name,
            "checkpoint target",
            MAX_CHECKPOINT_BYTES,
            single_link=True,
        )
        if existing != data:
            raise ResearchMemoryError("checkpoint target already exists with different bytes; append a correction instead")
        return True

    descriptor, temporary_name = _temporary_file_at(
        research_descriptor,
        ".research-memory-",
    )
    published = False
    staged_identity: Optional[tuple[int, int]] = None
    try:
        os.fchmod(descriptor, 0o644)
        _write_all(descriptor, data, "checkpoint")
        os.fsync(descriptor)
        staged = os.fstat(descriptor)
        if not stat.S_ISREG(staged.st_mode) or staged.st_nlink != 1:
            raise ResearchMemoryError("staged checkpoint is unsafe")
        staged_identity = (staged.st_dev, staged.st_ino)
        # Reject namespace drift observed before the no-clobber commit. Even if
        # a name changes immediately afterward, both link endpoints below are
        # anchored to the already pinned directory descriptors.
        _layout()
        try:
            os.link(
                temporary_name,
                target_name,
                src_dir_fd=research_descriptor,
                dst_dir_fd=checkpoints_descriptor,
                follow_symlinks=False,
            )
            published = True
        except FileExistsError:
            existing = _safe_read_at(
                checkpoints_descriptor,
                target_name,
                "checkpoint target",
                MAX_CHECKPOINT_BYTES,
                single_link=True,
            )
            if existing != data:
                raise ResearchMemoryError("checkpoint target appeared with different bytes")
            return True
        except OSError as exc:
            raise ResearchMemoryError(f"cannot publish checkpoint without clobbering: {exc}") from exc
        linked = os.fstat(descriptor)
        if (
            not stat.S_ISREG(linked.st_mode)
            or (linked.st_dev, linked.st_ino) != staged_identity
            or linked.st_nlink != 2
        ):
            raise ResearchMemoryError("published checkpoint link is not the exact staged inode")
        # Persist the destination link before removing the staging name, then
        # persist that removal in its own directory. The two names live in
        # different directories, so both directory updates need an explicit
        # durability boundary before the operation may report success.
        os.fsync(checkpoints_descriptor)
        _unlink_at(research_descriptor, temporary_name)
        os.fsync(research_descriptor)
        linked = os.fstat(descriptor)
        if linked.st_nlink != 1:
            raise ResearchMemoryError("published checkpoint did not become a single-link file")
        _verify_exact_file_at(
            checkpoints_descriptor,
            target_name,
            "published checkpoint",
            data,
            expected_identity=staged_identity,
        )
        _layout()
        return False
    except BaseException:
        # The destination hardlink is the append-only commit point. Once it
        # exists, never roll it back merely because a later durability,
        # staging-cleanup, verification, or index step failed. A surviving
        # two-link state is classified and completed by the next exclusive
        # operation; a surviving single-link checkpoint remains canonical and
        # only its disposable index may need rebuilding.
        raise
    finally:
        os.close(descriptor)
        if not published:
            _unlink_at(research_descriptor, temporary_name)


def record_checkpoint(checkpoint_path: str, input_path: str) -> dict[str, Any]:
    record = _read_input(input_path)
    relative = _checkpoint_relative(checkpoint_path, record["checkpoint_id"])
    rendered = render_checkpoint(record)
    with _memory_operation(exclusive=True):
        _validate_record_file_bindings(record)
        existing = _checkpoint_inventory(verify_artifacts=False)
        prospective = _prospective_records(existing, relative, record, rendered)
        _verify_required_evidence(prospective, record["checkpoint_id"])
        warnings = _unrelated_evidence_warnings(prospective, record["checkpoint_id"])
        if len(canonical_json_bytes(build_index(prospective))) > MAX_INDEX_BYTES:
            raise ResearchMemoryError("prospective derived index exceeds its size bound")
        idempotent = _publish_checkpoint(relative, rendered)
        # Reload after publication so the index binds bytes actually present on
        # disk.  The exclusive operation lock prevents a lost index update.
        _rebuild_index_unlocked()
        index, records = _validated_memory_state_unlocked(verify_artifacts=False)
        _verify_required_evidence(records, record["checkpoint_id"])
        matches = [
            item
            for item in records
            if item["path"] == relative
            and item["record"]["checkpoint_id"] == record["checkpoint_id"]
            and item["bytes"] == rendered
        ]
        if len(matches) != 1:
            raise ResearchMemoryError(
                "recorded checkpoint was not recovered exactly from canonical memory"
            )
    return {
        "status": "RECORDED",
        "checkpoint_id": record["checkpoint_id"],
        "checkpoint_path": relative,
        "idempotent": idempotent,
        "checkpoint_count": index["checkpoint_count"],
        "warnings": warnings,
    }


def _date_bounds(value: Union[str, dict[str, str]]) -> tuple[str, str]:
    if isinstance(value, str):
        return value, value
    return value["start"], value["end"]


def _matches_exact(values: Sequence[str], filters: Optional[Sequence[str]]) -> bool:
    if not filters:
        return True
    haystack = {value.casefold() for value in values}
    return all(value.casefold() in haystack for value in filters)


def _search_filters(
    values: Optional[Sequence[str]],
    label: str,
    *,
    identifiers: bool = False,
    maximum: int = MAX_SHORT_TEXT,
    one_line: bool = True,
) -> Optional[list[str]]:
    if values is None:
        return None
    if not values or len(values) > MAX_SEARCH_FILTERS:
        raise ResearchMemoryError(
            f"{label} must contain between 1 and {MAX_SEARCH_FILTERS} filters"
        )
    result: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(values):
        normalized = (
            _identifier(value, f"{label}[{index}]")
            if identifiers
            else (
                _single_line(value, f"{label}[{index}]", maximum=maximum)
                if one_line
                else _text(value, f"{label}[{index}]", maximum=maximum)
            )
        )
        folded = normalized.casefold()
        if folded in seen:
            raise ResearchMemoryError(f"{label} contains duplicate filters")
        seen.add(folded)
        result.append(normalized)
    return result


def _searchable_index() -> tuple[dict[str, Any], str, list[str]]:
    """Search canonical records even when their disposable index needs repair.

    Remain read-only for fleet discovery. Strict validation and Control Room
    completion still require the exact on-disk index; retrieval does not.
    """
    with _memory_operation(exclusive=False):
        records, warnings = _recover_search_records()
        index = build_index(records)
        descriptor = _active_descriptor("research")
        info = _existing_safe_file_at(descriptor, INDEX_RELATIVE.name, "checkpoint index")
        if info is not None and info.st_size <= MAX_INDEX_BYTES:
            actual = _safe_read_at(
                descriptor, INDEX_RELATIVE.name, "checkpoint index",
                MAX_INDEX_BYTES, single_link=True,
            )
            if actual == canonical_json_bytes(index):
                return index, "PARTIAL_RECOVERY" if warnings else "CURRENT", warnings
        return index, "PARTIAL_RECOVERY" if warnings else "REBUILT_IN_MEMORY", warnings


def search_index(args: argparse.Namespace) -> dict[str, Any]:
    if args.limit < 1 or args.limit > MAX_SEARCH_LIMIT:
        raise ResearchMemoryError(f"search limit must be between 1 and {MAX_SEARCH_LIMIT}")
    query = None
    if args.query is not None:
        query = _single_line(args.query, "query", maximum=MAX_QUERY).casefold()
    track = _single_line(args.track, "track filter", maximum=256) if args.track else None
    problem_ids = _search_filters(args.problem_ids, "problem_id filters", identifiers=True)
    topics = _search_filters(args.topics, "topic filters")
    objects = _search_filters(args.objects, "object filters")
    methods = _search_filters(args.methods, "method filters")
    keywords = _search_filters(args.keywords, "keyword filters")
    obstructions = _search_filters(
        args.obstructions,
        "obstruction filters",
        maximum=MAX_TEXT,
        one_line=False,
    )
    future_capabilities = _search_filters(
        args.future_capabilities,
        "future_capability filters",
        maximum=MAX_TEXT,
        one_line=False,
    )
    reopen_triggers = _search_filters(
        args.reopen_triggers,
        "reopen_trigger filters",
        maximum=MAX_TEXT,
        one_line=False,
    )
    date_from = _date(args.date_from, "date_from") if args.date_from else None
    date_to = _date(args.date_to, "date_to") if args.date_to else None
    if date_from and date_to and date_from > date_to:
        raise ResearchMemoryError("date_from must not be after date_to")

    index, index_status, warnings = _searchable_index()
    matches: list[dict[str, Any]] = []
    for entry in reversed(index["entries"]):
        if args.status and entry["outcome_status"] not in args.status:
            continue
        if track and entry.get("track", "").casefold() != track.casefold():
            continue
        if not _matches_exact(entry.get("problem_ids", []), problem_ids):
            continue
        if not _matches_exact(entry.get("topics", []), topics):
            continue
        if not _matches_exact(entry.get("objects", []), objects):
            continue
        if not _matches_exact(entry.get("methods", []), methods):
            continue
        if not _matches_exact(entry.get("keywords", []), keywords):
            continue
        if not _matches_exact(entry.get("obstructions", []), obstructions):
            continue
        if not _matches_exact(entry.get("future_capabilities", []), future_capabilities):
            continue
        if not _matches_exact(entry.get("reopen_triggers", []), reopen_triggers):
            continue
        entry_start, entry_end = _date_bounds(entry["research_date"])
        if date_from and entry_end < date_from:
            continue
        if date_to and entry_start > date_to:
            continue
        if query is not None:
            searchable = json.dumps(entry, ensure_ascii=False, sort_keys=True).casefold()
            if query not in searchable:
                continue
        matches.append(entry)
        if len(matches) >= args.limit:
            break
    return {
        "schema_version": SCHEMA_VERSION,
        "index_status": index_status,
        "warnings": warnings + ([] if index_status != "REBUILT_IN_MEMORY" else [
            "Saved index needs rebuilding. Results come from validated canonical "
            "checkpoints; no files were changed. Run rebuild-index to repair the cache."
        ]),
        "count": len(matches),
        "limit": args.limit,
        "matches": matches,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record, validate, rebuild, and search local structured research checkpoints."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser("record", help="append one canonical Markdown checkpoint")
    record.add_argument("--checkpoint-path", required=True)
    record.add_argument("--input", required=True, help="strict JSON file path, or - for standard input")

    subparsers.add_parser("rebuild-index", help="atomically rebuild disposable local discovery state")
    subparsers.add_parser("validate", help="validate checkpoints, links, and exact index freshness")

    control_room = subparsers.add_parser(
        "validate-control-room",
        help="read-only validation of one exact Control Room checkpoint binding",
    )
    control_room.add_argument("--checkpoint-path", required=True)
    control_room.add_argument("--checkpoint-id", required=True)
    control_room.add_argument("--round-id", required=True)
    control_room.add_argument("--run-id", required=True)

    inspect_control_room = subparsers.add_parser(
        "inspect-control-room-checkpoint",
        help="read-only validation of one checkpoint independently of the derived index",
    )
    inspect_control_room.add_argument("--checkpoint-path", required=True)
    inspect_control_room.add_argument("--checkpoint-id", required=True)
    inspect_control_room.add_argument("--round-id", required=True)
    inspect_control_room.add_argument("--run-id", required=True)

    search = subparsers.add_parser("search", help="search validated local discovery metadata")
    search.add_argument("--query")
    search.add_argument("--status", action="append", choices=OUTCOME_STATUSES)
    search.add_argument("--track")
    search.add_argument("--problem-id", "--problem", dest="problem_ids", action="append")
    search.add_argument("--topic", dest="topics", action="append")
    search.add_argument("--object", dest="objects", action="append")
    search.add_argument("--method", dest="methods", action="append")
    search.add_argument("--keyword", dest="keywords", action="append")
    search.add_argument("--obstruction", dest="obstructions", action="append")
    search.add_argument("--future-capability", dest="future_capabilities", action="append")
    search.add_argument("--reopen-trigger", dest="reopen_triggers", action="append")
    search.add_argument("--date-from")
    search.add_argument("--date-to")
    search.add_argument("--limit", type=int, default=20)
    return parser


def run(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "record":
            output = record_checkpoint(args.checkpoint_path, args.input)
        elif args.command == "rebuild-index":
            index = rebuild_index()
            output = {"status": "REBUILT", "checkpoint_count": index["checkpoint_count"]}
        elif args.command == "validate":
            index = validate_memory()
            output = {"status": "VALID", "checkpoint_count": index["checkpoint_count"]}
        elif args.command == "validate-control-room":
            output = validate_control_room(
                args.checkpoint_path,
                args.checkpoint_id,
                args.round_id,
                args.run_id,
            )
        elif args.command == "inspect-control-room-checkpoint":
            output = inspect_control_room_checkpoint(
                args.checkpoint_path,
                args.checkpoint_id,
                args.round_id,
                args.run_id,
            )
        elif args.command == "search":
            output = search_index(args)
        else:  # pragma: no cover - argparse makes this unreachable.
            raise ResearchMemoryError(f"unsupported command: {args.command}")
    except (ResearchMemoryError, OSError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    print(canonical_json_bytes(output).decode("utf-8"), end="")
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
