#!/usr/bin/env python3
"""Local, profile-gated repository-first research provenance.

This helper deliberately has no Git, network, process-launch, credential, or
outbound-message capability.  It records bounded append-only workflow and
provenance packets next to an existing problem dossier; the dossier, ordinary
source records, and Durable Research Memory checkpoints remain the truth
surfaces.  Unless ``LAB_PROFILE.json.repository_first.enabled`` is exactly
``true``, the validator is a passive no-op and every write command fails closed.
"""

from __future__ import annotations

import argparse
import copy
import errno
import hashlib
import importlib.util
import json
import os
import re
import secrets
import stat
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
POLICY_ID = "repository_first"
SCHEMA_VERSION = 1
EXPORT_REQUEST_VERSION = 2

MAX_INPUT_BYTES = 512 * 1024
MAX_RECORD_BYTES = 512 * 1024
MAX_EXPORT_FILES = 256
MAX_RECORDS = 4096
MAX_TEXT = 16_384
MAX_SHORT_TEXT = 1_024
MAX_PATH = 512
MAX_ITEMS = 256

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
CHECKPOINT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,190}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

PHASES = {
    "BREADTH_SEARCH",
    "MECHANISM_DEVELOPMENT",
    "CONSOLIDATION",
    "ADVERSARIAL_VALIDATION",
    "HUMAN_REDERIVATION",
    "FORMALIZATION",
    "EXPOSITION",
    "PAUSED",
    "CLOSED",
}
DENOMINATOR_FIELDS = (
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "wall_time_seconds",
    "tool_calls",
    "model_invocations",
    "harness_runs",
)
ROLE_KINDS = {
    "COORDINATOR",
    "CLAIM_GENERATOR",
    "COUNTEREXAMPLE_HUNTER",
    "SOURCE_AUDITOR",
    "INDEPENDENT_VERIFIER",
    "FORMALIZER",
    "HUMAN_REVIEWER",
    "COMPUTATION_OPERATOR",
}
ACTOR_CLASSES = {"HUMAN", "CODEX_AGENT", "LOCAL_TOOL"}
RECORD_TYPES = {
    "campaign",
    "phase_change",
    "adjacent_result",
    "failure_family",
    "raw_run_manifest",
    "claim_assessment",
    "source_use",
    "verification_coverage",
    "expert_feedback_plan",
    "expert_feedback_response",
}
RECORD_ID_FIELDS = {
    "campaign": "campaign_id",
    "phase_change": "change_id",
    "adjacent_result": "result_id",
    "failure_family": "family_id",
    "raw_run_manifest": "run_id",
    "claim_assessment": "assessment_id",
    "source_use": "use_id",
    "verification_coverage": "coverage_id",
    "expert_feedback_plan": "plan_id",
    "expert_feedback_response": "response_id",
}

AXIS_STATUSES = {
    "correctness": {"UNKNOWN", "FAIL", "PARTIAL", "PASS"},
    "novelty": {
        "NOT_ASSESSED",
        "UNKNOWN",
        "OVERLAPS_KNOWN",
        "DISTINCT_WITHIN_SEARCH_SCOPE",
    },
    "significance": {"NOT_ASSESSED", "UNKNOWN", "LIMITED", "MATERIAL", "HIGH"},
    "independent_verification": {"NOT_RUN", "INCONCLUSIVE", "FAIL", "PASS"},
    "human_rederivation_comprehension": {"NOT_RUN", "PARTIAL", "FAIL", "PASS"},
    "formalization_coverage": {"NONE", "PILOT", "PARTIAL", "COMPLETE", "NOT_APPLICABLE"},
    "release_readiness": {"NOT_READY", "CONDITIONAL", "READY_FOR_HUMAN_DECISION"},
}

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
FORBIDDEN_KEYS = {
    "api_key",
    "chain_of_thought",
    "claim_promotion",
    "claim_status",
    "cot",
    "credential",
    "credentials",
    "developer_prompt",
    "email",
    "endpoint",
    "hidden_prompt",
    "overall_status",
    "outbound",
    "outbound_action",
    "password",
    "promote",
    "promote_to",
    "recipient",
    "recipient_address",
    "recipient_email",
    "secret",
    "send_to",
    "system_prompt",
    "token",
    "truth_status",
    "webhook",
}
SECRET_BASENAMES = {
    ".env",
    ".netrc",
    "credentials",
    "credentials.json",
    "id_ed25519",
    "id_rsa",
    "netrc",
    "password",
    "secrets",
    "secrets.json",
    "token",
    "tokens.json",
}
HIDDEN_PROMPT_FRAGMENTS = (
    "chain_of_thought",
    "developer_prompt",
    "hidden_prompt",
    "system_prompt",
)


class RepositoryFirstError(ValueError):
    """A closed-schema, provenance, or safe-publication failure."""


_RESEARCH_MEMORY_MODULE: Any = None


def _research_memory_module() -> Any:
    """Load the exact sibling parser without a subprocess or external import."""

    global _RESEARCH_MEMORY_MODULE
    if _RESEARCH_MEMORY_MODULE is not None:
        return _RESEARCH_MEMORY_MODULE
    path = Path(__file__).resolve().with_name("research_memory.py")
    try:
        info = path.lstat()
    except OSError as exc:
        raise RepositoryFirstError(f"cannot inspect sibling research_memory.py: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RepositoryFirstError("sibling research_memory.py must be a regular non-symlink file")
    spec = importlib.util.spec_from_file_location(
        "_repository_first_research_memory_v1",
        path,
    )
    if spec is None or spec.loader is None:
        raise RepositoryFirstError("cannot load sibling research_memory.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _RESEARCH_MEMORY_MODULE = module
    return module


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RepositoryFirstError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise RepositoryFirstError(f"non-finite JSON number is forbidden: {value}")


def strict_json_loads(text: str, label: str = "input") -> Any:
    try:
        return json.loads(
            text,
            object_pairs_hook=_strict_pairs,
            parse_constant=_reject_constant,
        )
    except RepositoryFirstError:
        raise
    except (ValueError, RecursionError) as exc:
        raise RepositoryFirstError(f"{label} is not strict JSON: {exc}") from exc


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


def _read_bounded_regular(path: Path, label: str, maximum: int) -> bytes:
    try:
        info = path.lstat()
    except OSError as exc:
        raise RepositoryFirstError(f"cannot inspect {label}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RepositoryFirstError(f"{label} must be a regular non-symlink file")
    if info.st_size > maximum:
        raise RepositoryFirstError(f"{label} exceeds {maximum} bytes")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise RepositoryFirstError(f"cannot read {label}: {exc}") from exc
    if len(data) > maximum:
        raise RepositoryFirstError(f"{label} exceeds {maximum} bytes")
    return data


def _input_json(root: Path, argument: str) -> Any:
    if argument == "-":
        data = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(data) > MAX_INPUT_BYTES:
            raise RepositoryFirstError("stdin exceeds the input bound")
    else:
        relative = _relpath(argument, "input path")
        path = _existing_regular(root, relative, "input path")
        data = _read_bounded_regular(path, "input path", MAX_INPUT_BYTES)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RepositoryFirstError("input is not UTF-8") from exc
    return strict_json_loads(text)


def _scalar_text(value: Any, label: str, maximum: int = MAX_TEXT, *, one_line: bool = False) -> str:
    if not isinstance(value, str):
        raise RepositoryFirstError(f"{label} must be a string")
    if unicodedata.normalize("NFC", value) != value:
        raise RepositoryFirstError(f"{label} must use NFC Unicode")
    if not value or value != value.strip():
        raise RepositoryFirstError(f"{label} must be non-empty without surrounding whitespace")
    if one_line and any(character in value for character in ("\r", "\n", "\t")):
        raise RepositoryFirstError(f"{label} must be one line")
    for character in value:
        codepoint = ord(character)
        if 0xD800 <= codepoint <= 0xDFFF:
            raise RepositoryFirstError(f"{label} contains a Unicode surrogate")
        if codepoint < 0x20 and character not in ("\n", "\t"):
            raise RepositoryFirstError(f"{label} contains a forbidden control character")
        if codepoint == 0x7F:
            raise RepositoryFirstError(f"{label} contains a forbidden control character")
    if len(value) > maximum or len(value.encode("utf-8")) > maximum * 4:
        raise RepositoryFirstError(f"{label} exceeds its size bound")
    return value


def _optional_text(value: Any, label: str, maximum: int = MAX_SHORT_TEXT) -> None:
    if value is not None:
        _scalar_text(value, label, maximum, one_line=True)


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise RepositoryFirstError(f"{label} must match {ID_RE.pattern}")
    return value


def _checkpoint_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not CHECKPOINT_ID_RE.fullmatch(value):
        raise RepositoryFirstError(f"{label} must be a safe checkpoint identifier")
    return value


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise RepositoryFirstError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or not UTC_RE.fullmatch(value):
        raise RepositoryFirstError(f"{label} must be YYYY-MM-DDTHH:MM:SSZ")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise RepositoryFirstError(f"{label} is not a real UTC timestamp") from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise RepositoryFirstError(f"{label} is not canonical")
    return value


def _date(value: Any, label: str) -> str:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        raise RepositoryFirstError(f"{label} must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise RepositoryFirstError(f"{label} is not a real date") from exc
    if parsed.isoformat() != value:
        raise RepositoryFirstError(f"{label} is not canonical")
    return value


def _integer(value: Any, label: str, minimum: int = 0, maximum: int = 10**12) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RepositoryFirstError(f"{label} must be an integer")
    if value < minimum or value > maximum:
        raise RepositoryFirstError(f"{label} is outside its bound")
    return value


def _boolean(value: Any, label: str, expected: Optional[bool] = None) -> bool:
    if not isinstance(value, bool):
        raise RepositoryFirstError(f"{label} must be a boolean")
    if expected is not None and value is not expected:
        raise RepositoryFirstError(f"{label} must be {str(expected).lower()}")
    return value


def _enum(value: Any, label: str, choices: Iterable[str]) -> str:
    allowed = set(choices)
    if not isinstance(value, str) or value not in allowed:
        raise RepositoryFirstError(f"{label} must be one of: {', '.join(sorted(allowed))}")
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RepositoryFirstError(f"{label} must be an object")
    return value


def _exact(
    value: Any,
    label: str,
    required: Iterable[str],
    optional: Iterable[str] = (),
) -> dict[str, Any]:
    item = _object(value, label)
    required_set = set(required)
    allowed = required_set | set(optional)
    missing = sorted(required_set - set(item))
    unknown = sorted(set(item) - allowed)
    if missing:
        raise RepositoryFirstError(f"{label} is missing keys: {', '.join(missing)}")
    if unknown:
        raise RepositoryFirstError(f"{label} has unknown keys: {', '.join(unknown)}")
    return item


def _array(value: Any, label: str, maximum: int = MAX_ITEMS, *, allow_empty: bool = False) -> list[Any]:
    if not isinstance(value, list):
        raise RepositoryFirstError(f"{label} must be an array")
    if not value and not allow_empty:
        raise RepositoryFirstError(f"{label} must not be empty")
    if len(value) > maximum:
        raise RepositoryFirstError(f"{label} has too many items")
    return value


def _string_list(
    value: Any,
    label: str,
    *,
    maximum: int = MAX_ITEMS,
    allow_empty: bool = False,
    identifiers: bool = False,
) -> list[str]:
    result: list[str] = []
    for index, item in enumerate(_array(value, label, maximum, allow_empty=allow_empty)):
        if identifiers:
            result.append(_identifier(item, f"{label}[{index}]"))
        else:
            result.append(_scalar_text(item, f"{label}[{index}]", MAX_SHORT_TEXT, one_line=True))
    if len(result) != len(set(result)):
        raise RepositoryFirstError(f"{label} must not contain duplicates")
    return result


def _relpath(value: Any, label: str, prefixes: Sequence[str] = ()) -> str:
    if not isinstance(value, str):
        raise RepositoryFirstError(f"{label} must be a relative POSIX path")
    _scalar_text(value, label, MAX_PATH, one_line=True)
    if "\\" in value or value.startswith("/") or "//" in value:
        raise RepositoryFirstError(f"{label} must be a normalized relative POSIX path")
    path = PurePosixPath(value)
    parts = path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise RepositoryFirstError(f"{label} is not a safe relative path")
    if any(part.casefold() == ".git" for part in parts):
        raise RepositoryFirstError(f"{label} must not name Git metadata")
    if path.as_posix() != value:
        raise RepositoryFirstError(f"{label} is not normalized")
    if prefixes and not any(value.startswith(prefix) for prefix in prefixes):
        raise RepositoryFirstError(f"{label} is outside its allowed roots")
    return value


def _evidence_path(value: Any, label: str) -> str:
    return _relpath(value, label, EVIDENCE_PREFIXES)


def _path_list(
    value: Any,
    label: str,
    *,
    evidence: bool = True,
    allow_empty: bool = True,
    maximum: int = MAX_ITEMS,
) -> list[str]:
    result: list[str] = []
    for index, item in enumerate(_array(value, label, maximum, allow_empty=allow_empty)):
        parser = _evidence_path if evidence else _relpath
        result.append(parser(item, f"{label}[{index}]"))
    if len(result) != len(set(result)):
        raise RepositoryFirstError(f"{label} must not contain duplicates")
    return result


def _claim_statement_bindings(
    value: Any,
    label: str,
) -> list[tuple[str, str, str, str]]:
    bindings = _array(value, label, 128)
    normalized: list[tuple[str, str, str, str]] = []
    for index, binding_value in enumerate(bindings):
        binding = _exact(
            binding_value,
            f"{label}[{index}]",
            {
                "claim_id",
                "claim_statement_version",
                "claim_statement_path",
                "claim_statement_sha256",
            },
        )
        normalized.append(
            (
                _identifier(binding["claim_id"], f"{label}[{index}].claim_id"),
                _scalar_text(
                    binding["claim_statement_version"],
                    f"{label}[{index}].claim_statement_version",
                    MAX_SHORT_TEXT,
                    one_line=True,
                ),
                _evidence_path(
                    binding["claim_statement_path"],
                    f"{label}[{index}].claim_statement_path",
                ),
                _sha256(
                    binding["claim_statement_sha256"],
                    f"{label}[{index}].claim_statement_sha256",
                ),
            )
        )
    claim_ids = [binding[0] for binding in normalized]
    if len(claim_ids) != len(set(claim_ids)):
        raise RepositoryFirstError(f"{label} must not bind a claim more than once")
    return normalized


def _checkpoint_path(value: Any, label: str = "checkpoint_path") -> str:
    path = _relpath(value, label, ("research/checkpoints/",))
    if len(PurePosixPath(path).parts) != 3:
        raise RepositoryFirstError(f"{label} must directly name one checkpoint file")
    return path


def _dossier_path(value: Any, problem_id: str, label: str = "claim_dossier_path") -> str:
    path = _relpath(value, label, ("problems/active/", "problems/backlog/", "problems/closed/"))
    parts = PurePosixPath(path).parts
    if len(parts) != 3 or parts[2] != problem_id:
        raise RepositoryFirstError(f"{label} must name the dossier for problem_id")
    return path


def _secret_or_hidden_path(path: str) -> bool:
    for part in PurePosixPath(path).parts:
        folded = part.casefold()
        if folded in SECRET_BASENAMES:
            return True
        if any(fragment in folded for fragment in HIDDEN_PROMPT_FRAGMENTS):
            return True
    return False


def _walk_key_policy(value: Any, record_type: str, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _scalar_text(key, "JSON key", 128, one_line=True)
            folded = key.casefold()
            export_exclusion_key = (
                record_type == "export_package_manifest"
                and path == ("exclusions",)
                and folded in {"credentials", "chain_of_thought"}
            )
            if folded in FORBIDDEN_KEYS and not export_exclusion_key:
                raise RepositoryFirstError(f"forbidden field {'.'.join(path + (key,))}")
            if folded == "automatic_promotion":
                raise RepositoryFirstError("automatic claim promotion fields are forbidden")
            if folded == "human_owned" and not (
                record_type == "campaign" and path == ("governance",)
            ):
                raise RepositoryFirstError("human_owned is permitted only in campaign governance")
            _walk_key_policy(child, record_type, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_key_policy(child, record_type, path + (str(index),))
    elif isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise RepositoryFirstError("non-finite numbers are forbidden")


def _existing_path(root: Path, relative: str, label: str, *, regular: Optional[bool] = None) -> Path:
    current = root
    parts = PurePosixPath(relative).parts
    for index, part in enumerate(parts):
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise RepositoryFirstError(f"{label} does not exist safely: {relative}: {exc}") from exc
        if stat.S_ISLNK(info.st_mode):
            raise RepositoryFirstError(f"{label} traverses a symlink: {relative}")
        final = index == len(parts) - 1
        if not final and not stat.S_ISDIR(info.st_mode):
            raise RepositoryFirstError(f"{label} has a non-directory parent: {relative}")
        if final and regular is True and not stat.S_ISREG(info.st_mode):
            raise RepositoryFirstError(f"{label} must be a regular file: {relative}")
        if final and regular is False and not stat.S_ISDIR(info.st_mode):
            raise RepositoryFirstError(f"{label} must be a directory: {relative}")
    return current


def _existing_regular(root: Path, relative: str, label: str) -> Path:
    return _existing_path(root, relative, label, regular=True)


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                count += len(chunk)
    except OSError as exc:
        raise RepositoryFirstError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest(), count


def _require_immutable_record_mode(path: Path, label: str) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise RepositoryFirstError(f"cannot inspect {label}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RepositoryFirstError(f"{label} must be a regular non-symlink file")
    if stat.S_IMODE(info.st_mode) != 0o444:
        raise RepositoryFirstError(f"{label} must retain immutable mode 0444")
    if info.st_nlink != 1:
        raise RepositoryFirstError(f"{label} must not be hard-linked")


def _require_bound_file(root: Path, path: str, digest: str, label: str, size: Optional[int] = None) -> None:
    target = _existing_regular(root, path, label)
    actual_digest, actual_size = _hash_file(target)
    if actual_digest != digest:
        raise RepositoryFirstError(f"{label} SHA-256 does not match: {path}")
    if size is not None and actual_size != size:
        raise RepositoryFirstError(f"{label} byte count does not match: {path}")


def _common_record(record: Any, record_type: str, required: Iterable[str]) -> dict[str, Any]:
    keys = {"schema_version", "record_type", "problem_id"} | set(required)
    item = _exact(record, record_type, keys)
    if item["schema_version"] != SCHEMA_VERSION:
        raise RepositoryFirstError(f"{record_type}.schema_version must be {SCHEMA_VERSION}")
    if item["record_type"] != record_type:
        raise RepositoryFirstError(f"record_type must be {record_type}")
    _identifier(item["problem_id"], f"{record_type}.problem_id")
    return item


def _validate_campaign(record: Any, root: Path, require_files: bool) -> None:
    item = _common_record(
        record,
        "campaign",
        {
            "campaign_id",
            "title",
            "created_at_utc",
            "target_claim_ids",
            "initial_phase",
            "roles",
            "governance",
            "objective",
            "stop_conditions",
        },
    )
    _identifier(item["campaign_id"], "campaign.campaign_id")
    _scalar_text(item["title"], "campaign.title", MAX_SHORT_TEXT, one_line=True)
    _timestamp(item["created_at_utc"], "campaign.created_at_utc")
    _string_list(item["target_claim_ids"], "campaign.target_claim_ids", identifiers=True)
    _enum(item["initial_phase"], "campaign.initial_phase", PHASES)
    roles = _array(item["roles"], "campaign.roles", 32)
    role_ids: list[str] = []
    human_roles: set[str] = set()
    for index, role_value in enumerate(roles):
        role = _exact(
            role_value,
            f"campaign.roles[{index}]",
            {"role_id", "role_kind", "actor_class", "actor_id", "responsibilities"},
        )
        role_id = _identifier(role["role_id"], f"campaign.roles[{index}].role_id")
        role_ids.append(role_id)
        _enum(role["role_kind"], f"campaign.roles[{index}].role_kind", ROLE_KINDS)
        actor_class = _enum(
            role["actor_class"], f"campaign.roles[{index}].actor_class", ACTOR_CLASSES
        )
        if actor_class == "HUMAN":
            human_roles.add(role_id)
        _identifier(role["actor_id"], f"campaign.roles[{index}].actor_id")
        _string_list(role["responsibilities"], f"campaign.roles[{index}].responsibilities")
    if len(role_ids) != len(set(role_ids)):
        raise RepositoryFirstError("campaign.roles contains duplicate role_id values")
    governance = _exact(
        item["governance"],
        "campaign.governance",
        {"human_owned", "human_owner_role_ids", "decision_scope"},
    )
    _boolean(governance["human_owned"], "campaign.governance.human_owned", True)
    owners = _string_list(
        governance["human_owner_role_ids"],
        "campaign.governance.human_owner_role_ids",
        identifiers=True,
    )
    if not set(owners) <= human_roles:
        raise RepositoryFirstError("campaign governance owners must be declared HUMAN roles")
    if governance["decision_scope"] != "GOVERNANCE_ONLY":
        raise RepositoryFirstError("campaign.governance.decision_scope must be GOVERNANCE_ONLY")
    _scalar_text(item["objective"], "campaign.objective")
    _string_list(item["stop_conditions"], "campaign.stop_conditions")


def _validate_phase_change(record: Any, root: Path, require_files: bool) -> None:
    item = _common_record(
        record,
        "phase_change",
        {
            "change_id",
            "campaign_id",
            "sequence",
            "previous_change_id",
            "from_phase",
            "to_phase",
            "changed_at_utc",
            "changed_by_role_id",
            "transition_kind",
            "input_artifact_paths",
            "active_role_ids",
            "budget",
            "exit_condition",
            "prior_failure_family_ids",
            "search_policy_delta",
            "reason",
            "checkpoint_path",
        },
    )
    _identifier(item["change_id"], "phase_change.change_id")
    _identifier(item["campaign_id"], "phase_change.campaign_id")
    _integer(item["sequence"], "phase_change.sequence", 1, 10_000)
    if item["previous_change_id"] is not None:
        _identifier(item["previous_change_id"], "phase_change.previous_change_id")
    _enum(item["from_phase"], "phase_change.from_phase", PHASES)
    _enum(item["to_phase"], "phase_change.to_phase", PHASES)
    if item["from_phase"] == item["to_phase"]:
        raise RepositoryFirstError("phase_change must change phase")
    _timestamp(item["changed_at_utc"], "phase_change.changed_at_utc")
    _identifier(item["changed_by_role_id"], "phase_change.changed_by_role_id")
    transition_kind = _enum(
        item["transition_kind"],
        "phase_change.transition_kind",
        {"PROGRESS", "PIVOT", "RETRY_AFTER_FAILURE", "PAUSE", "RESUME", "CLOSE"},
    )
    _path_list(
        item["input_artifact_paths"],
        "phase_change.input_artifact_paths",
        allow_empty=False,
    )
    _string_list(
        item["active_role_ids"], "phase_change.active_role_ids", identifiers=True
    )
    _validate_budget(item["budget"], "phase_change.budget")
    _scalar_text(item["exit_condition"], "phase_change.exit_condition")
    prior_failures = _string_list(
        item["prior_failure_family_ids"],
        "phase_change.prior_failure_family_ids",
        identifiers=True,
        allow_empty=True,
    )
    _optional_text(
        item["search_policy_delta"],
        "phase_change.search_policy_delta",
        MAX_TEXT,
    )
    if transition_kind == "RETRY_AFTER_FAILURE":
        if not prior_failures:
            raise RepositoryFirstError(
                "RETRY_AFTER_FAILURE requires prior_failure_family_ids"
            )
        if item["search_policy_delta"] is None:
            raise RepositoryFirstError(
                "RETRY_AFTER_FAILURE requires a changed search_policy_delta"
            )
    _scalar_text(item["reason"], "phase_change.reason")
    checkpoint = _checkpoint_path(item["checkpoint_path"])
    if require_files:
        for index, path in enumerate(item["input_artifact_paths"]):
            _existing_regular(root, path, f"phase_change input artifact {index}")
        _existing_regular(root, checkpoint, "phase_change checkpoint")


def _validate_adjacent_result(record: Any, root: Path, require_files: bool) -> None:
    item = _common_record(
        record,
        "adjacent_result",
        {
            "result_id",
            "campaign_id",
            "recorded_at_utc",
            "new_claim_id",
            "parent_claim_ids",
            "lineage_relation",
            "registration_status",
            "statement_path",
            "checkpoint_path",
        },
    )
    _identifier(item["result_id"], "adjacent_result.result_id")
    _identifier(item["campaign_id"], "adjacent_result.campaign_id")
    _timestamp(item["recorded_at_utc"], "adjacent_result.recorded_at_utc")
    claim_id = _identifier(item["new_claim_id"], "adjacent_result.new_claim_id")
    parents = _string_list(
        item["parent_claim_ids"], "adjacent_result.parent_claim_ids", identifiers=True
    )
    if claim_id in parents:
        raise RepositoryFirstError("adjacent_result new claim cannot be its own parent")
    _enum(
        item["lineage_relation"],
        "adjacent_result.lineage_relation",
        {"COROLLARY", "SPECIAL_CASE", "GENERALIZATION", "COUNTEREXAMPLE", "OBSTRUCTION", "METHOD", "TRANSLATION", "OTHER"},
    )
    if item["registration_status"] != "NEW_UNVERIFIED_CLAIM":
        raise RepositoryFirstError("adjacent_result must register a new unverified claim")
    statement = _evidence_path(item["statement_path"], "adjacent_result.statement_path")
    checkpoint = _checkpoint_path(item["checkpoint_path"])
    if require_files:
        _existing_regular(root, statement, "adjacent_result statement")
        _existing_regular(root, checkpoint, "adjacent_result checkpoint")


def _denominator_component(value: Any, label: str) -> None:
    item = _exact(value, label, {"status", "value", "unknown_reason", "evidence_paths"})
    status_value = _enum(item["status"], f"{label}.status", {"KNOWN", "UNKNOWN"})
    _path_list(item["evidence_paths"], f"{label}.evidence_paths", allow_empty=True)
    if status_value == "KNOWN":
        _scalar_text(item["value"], f"{label}.value", MAX_SHORT_TEXT, one_line=True)
        if item["unknown_reason"] is not None:
            raise RepositoryFirstError(f"{label}.unknown_reason must be null when KNOWN")
    else:
        if item["value"] is not None:
            raise RepositoryFirstError(f"{label}.value must be null when UNKNOWN")
        _scalar_text(
            item["unknown_reason"], f"{label}.unknown_reason", MAX_SHORT_TEXT, one_line=True
        )


def _validate_budget(value: Any, label: str) -> None:
    item = _exact(
        value,
        label,
        {
            "input_token_budget",
            "output_token_budget",
            "reasoning_token_budget",
            "wall_time_seconds",
            "tool_call_budget",
            "unknown_reason",
        },
    )
    unknown = False
    for key in (
        "input_token_budget",
        "output_token_budget",
        "reasoning_token_budget",
        "wall_time_seconds",
        "tool_call_budget",
    ):
        if item[key] is None:
            unknown = True
        else:
            _integer(item[key], f"{label}.{key}", 0, 2**60)
    if unknown:
        _scalar_text(item["unknown_reason"], f"{label}.unknown_reason", MAX_SHORT_TEXT, one_line=True)
    elif item["unknown_reason"] is not None:
        raise RepositoryFirstError(f"{label}.unknown_reason must be null when the budget is exact")


def _validate_versioned_identity(value: Any, label: str, id_field: str) -> None:
    item = _exact(
        value,
        label,
        {id_field, "version_status", "exact_version", "unknown_reason"},
    )
    _scalar_text(item[id_field], f"{label}.{id_field}", MAX_SHORT_TEXT, one_line=True)
    version_status = _enum(
        item["version_status"], f"{label}.version_status", {"EXACT", "UNKNOWN"}
    )
    if version_status == "EXACT":
        _scalar_text(
            item["exact_version"], f"{label}.exact_version", MAX_SHORT_TEXT, one_line=True
        )
        if item["unknown_reason"] is not None:
            raise RepositoryFirstError(f"{label}.unknown_reason must be null for an exact version")
    else:
        if item["exact_version"] is not None:
            raise RepositoryFirstError(f"{label}.exact_version must be null when UNKNOWN")
        _scalar_text(
            item["unknown_reason"], f"{label}.unknown_reason", MAX_SHORT_TEXT, one_line=True
        )


def _validate_actual_denominator(value: Any, label: str) -> dict[str, Any]:
    item = _exact(value, label, {*DENOMINATOR_FIELDS, "unknown_fields"})
    unknown_fields = _string_list(
        item["unknown_fields"],
        f"{label}.unknown_fields",
        allow_empty=True,
    )
    unknown_set = set(unknown_fields)
    if not unknown_set <= set(DENOMINATOR_FIELDS):
        raise RepositoryFirstError(f"{label}.unknown_fields names an unsupported counter")
    for field in DENOMINATOR_FIELDS:
        if field in unknown_set:
            if item[field] is not None:
                raise RepositoryFirstError(f"{label}.{field} must be null when declared unknown")
        else:
            _integer(item[field], f"{label}.{field}", 0, 2**60)
    return item


def _validate_failure_family(record: Any, root: Path, require_files: bool) -> None:
    item = _common_record(
        record,
        "failure_family",
        {
            "family_id",
            "campaign_id",
            "recorded_at_utc",
            "compressed_from_count",
            "member_run_ids",
            "mechanism_summary",
            "distinguishing_observation",
            "exact_failure_reason",
            "evidence_paths",
            "reactivation_conditions",
            "denominator",
            "aggregate_actual_denominator",
            "checkpoint_path",
        },
    )
    _identifier(item["family_id"], "failure_family.family_id")
    _identifier(item["campaign_id"], "failure_family.campaign_id")
    _timestamp(item["recorded_at_utc"], "failure_family.recorded_at_utc")
    members = _string_list(item["member_run_ids"], "failure_family.member_run_ids", identifiers=True)
    count = _integer(item["compressed_from_count"], "failure_family.compressed_from_count", 1)
    if count != len(members):
        raise RepositoryFirstError(
            "compressed_from_count must exactly match the preserved member_run_ids"
        )
    _scalar_text(item["mechanism_summary"], "failure_family.mechanism_summary")
    _scalar_text(item["distinguishing_observation"], "failure_family.distinguishing_observation")
    _scalar_text(item["exact_failure_reason"], "failure_family.exact_failure_reason")
    _path_list(
        item["evidence_paths"], "failure_family.evidence_paths", allow_empty=False
    )
    _string_list(
        item["reactivation_conditions"], "failure_family.reactivation_conditions"
    )
    denominator = _exact(item["denominator"], "failure_family.denominator", {"vector", "model", "harness"})
    for name in ("vector", "model", "harness"):
        _denominator_component(denominator[name], f"failure_family.denominator.{name}")
    _validate_actual_denominator(
        item["aggregate_actual_denominator"],
        "failure_family.aggregate_actual_denominator",
    )
    checkpoint = _checkpoint_path(item["checkpoint_path"])
    if require_files:
        _existing_regular(root, checkpoint, "failure_family checkpoint")


def _validate_prompt(value: Any, label: str, dossier_path: str) -> None:
    item = _exact(value, label, {"prompt_class", "path", "sha256"})
    if item["prompt_class"] != "LAB_AUTHORED_ACTION_PROMPT":
        raise RepositoryFirstError(
            f"{label}.prompt_class may name only a lab-authored action prompt"
        )
    path = _relpath(item["path"], f"{label}.path", (f"{dossier_path}/repository_first/prompts/",))
    if _secret_or_hidden_path(path):
        raise RepositoryFirstError(f"{label}.path names forbidden hidden or credential material")
    _sha256(item["sha256"], f"{label}.sha256")


def _validate_raw_run(record: Any, root: Path, require_files: bool) -> None:
    item = _common_record(
        record,
        "raw_run_manifest",
        {
            "run_id",
            "campaign_id",
            "role_id",
            "phase",
            "started_at_utc",
            "completed_at_utc",
            "outcome_class",
            "claim_ids",
            "significant_prompts",
            "execution_provenance",
            "verification_boundary",
            "raw_archive",
            "output_artifact_paths",
            "checkpoint_path",
            "checkpoint_id",
            "checkpoint_sha256",
            "claim_dossier_path",
            "claim_dossier_anchor_path",
            "claim_dossier_anchor_sha256",
        },
    )
    problem_id = _identifier(item["problem_id"], "raw_run_manifest.problem_id")
    run_id = _identifier(item["run_id"], "raw_run_manifest.run_id")
    _identifier(item["campaign_id"], "raw_run_manifest.campaign_id")
    _identifier(item["role_id"], "raw_run_manifest.role_id")
    _enum(item["phase"], "raw_run_manifest.phase", PHASES)
    started = _timestamp(item["started_at_utc"], "raw_run_manifest.started_at_utc")
    completed = _timestamp(item["completed_at_utc"], "raw_run_manifest.completed_at_utc")
    if completed < started:
        raise RepositoryFirstError("raw_run_manifest completion precedes start")
    _enum(
        item["outcome_class"],
        "raw_run_manifest.outcome_class",
        {"SUCCESS", "PARTIAL", "FAILURE", "INCONCLUSIVE"},
    )
    claim_ids = _string_list(
        item["claim_ids"], "raw_run_manifest.claim_ids", identifiers=True
    )
    dossier = _dossier_path(item["claim_dossier_path"], problem_id)
    dossier_anchor = _relpath(
        item["claim_dossier_anchor_path"],
        "raw_run_manifest.claim_dossier_anchor_path",
        (f"{dossier}/",),
    )
    dossier_anchor_digest = _sha256(
        item["claim_dossier_anchor_sha256"],
        "raw_run_manifest.claim_dossier_anchor_sha256",
    )
    if dossier_anchor.startswith(f"{dossier}/repository_first/"):
        raise RepositoryFirstError(
            "raw_run_manifest claim dossier anchor must name canonical dossier state outside repository_first"
        )
    prompts = _array(
        item["significant_prompts"], "raw_run_manifest.significant_prompts", 32, allow_empty=True
    )
    for index, prompt in enumerate(prompts):
        _validate_prompt(prompt, f"raw_run_manifest.significant_prompts[{index}]", dossier)
    provenance = _exact(
        item["execution_provenance"],
        "raw_run_manifest.execution_provenance",
        {"model", "harness", "effort", "planned_budget", "actual_denominator", "tool_commands"},
    )
    _validate_versioned_identity(
        provenance["model"], "raw_run_manifest.execution_provenance.model", "model_id"
    )
    _validate_versioned_identity(
        provenance["harness"],
        "raw_run_manifest.execution_provenance.harness",
        "harness_id",
    )
    effort = _exact(
        provenance["effort"],
        "raw_run_manifest.execution_provenance.effort",
        {"level", "note"},
    )
    effort_level = _enum(
        effort["level"],
        "raw_run_manifest.execution_provenance.effort.level",
        {"LOW", "MEDIUM", "HIGH", "XHIGH", "MAX", "CUSTOM", "UNKNOWN"},
    )
    if effort_level in {"CUSTOM", "UNKNOWN"}:
        _scalar_text(
            effort["note"],
            "raw_run_manifest.execution_provenance.effort.note",
            MAX_SHORT_TEXT,
            one_line=True,
        )
    elif effort["note"] is not None:
        raise RepositoryFirstError("execution effort note is only for CUSTOM or UNKNOWN")
    _validate_budget(
        provenance["planned_budget"],
        "raw_run_manifest.execution_provenance.planned_budget",
    )
    _validate_actual_denominator(
        provenance["actual_denominator"],
        "raw_run_manifest.execution_provenance.actual_denominator",
    )
    tool_commands = _array(
        provenance["tool_commands"],
        "raw_run_manifest.execution_provenance.tool_commands",
        128,
        allow_empty=True,
    )
    for index, command_value in enumerate(tool_commands):
        command = _exact(
            command_value,
            f"raw_run_manifest.execution_provenance.tool_commands[{index}]",
            {
                "tool_id",
                "version_status",
                "exact_version",
                "unknown_reason",
                "invocation_count",
                "command_manifest_path",
                "command_manifest_sha256",
            },
        )
        _validate_versioned_identity(
            {
                "tool_id": command["tool_id"],
                "version_status": command["version_status"],
                "exact_version": command["exact_version"],
                "unknown_reason": command["unknown_reason"],
            },
            f"raw_run_manifest.execution_provenance.tool_commands[{index}]",
            "tool_id",
        )
        _integer(
            command["invocation_count"],
            f"raw_run_manifest.execution_provenance.tool_commands[{index}].invocation_count",
            1,
            10**9,
        )
        command_path = _evidence_path(
            command["command_manifest_path"],
            f"raw_run_manifest.execution_provenance.tool_commands[{index}].command_manifest_path",
        )
        command_digest = _sha256(
            command["command_manifest_sha256"],
            f"raw_run_manifest.execution_provenance.tool_commands[{index}].command_manifest_sha256",
        )
        if require_files:
            _require_bound_file(
                root,
                command_path,
                command_digest,
                f"tool command manifest {index}",
            )
    boundary = _exact(
        item["verification_boundary"],
        "raw_run_manifest.verification_boundary",
        {"independence_status", "verified_scope", "unverified_scope", "evidence_paths"},
    )
    _enum(
        boundary["independence_status"],
        "raw_run_manifest.verification_boundary.independence_status",
        {"NOT_ASSESSED", "SELF_CHECKED", "INDEPENDENTLY_CHECKED"},
    )
    _string_list(
        boundary["verified_scope"],
        "raw_run_manifest.verification_boundary.verified_scope",
        allow_empty=True,
    )
    _string_list(
        boundary["unverified_scope"],
        "raw_run_manifest.verification_boundary.unverified_scope",
        allow_empty=True,
    )
    _path_list(
        boundary["evidence_paths"],
        "raw_run_manifest.verification_boundary.evidence_paths",
    )
    archive = _exact(
        item["raw_archive"],
        "raw_run_manifest.raw_archive",
        {"path", "sha256", "bytes", "availability"},
    )
    archive_path = _relpath(
        archive["path"],
        "raw_run_manifest.raw_archive.path",
        (f"research/raw_runs/archive/{problem_id}/",),
    )
    if _secret_or_hidden_path(archive_path):
        raise RepositoryFirstError("raw archive path may not name credential or hidden-prompt material")
    archive_digest = _sha256(archive["sha256"], "raw_run_manifest.raw_archive.sha256")
    archive_bytes = _integer(archive["bytes"], "raw_run_manifest.raw_archive.bytes", 0, 2**60)
    availability = _enum(
        archive["availability"],
        "raw_run_manifest.raw_archive.availability",
        {"PRESENT_LOCAL", "HASH_ONLY_PRUNED"},
    )
    _path_list(item["output_artifact_paths"], "raw_run_manifest.output_artifact_paths")
    checkpoint = _checkpoint_path(item["checkpoint_path"])
    checkpoint_id = _checkpoint_identifier(
        item["checkpoint_id"], "raw_run_manifest.checkpoint_id"
    )
    checkpoint_digest = _sha256(
        item["checkpoint_sha256"], "raw_run_manifest.checkpoint_sha256"
    )
    if PurePosixPath(checkpoint).name != f"{checkpoint_id}.md":
        raise RepositoryFirstError(
            "raw_run_manifest checkpoint filename must exactly match checkpoint_id"
        )
    if require_files:
        _existing_path(root, dossier, "raw_run_manifest claim dossier", regular=False)
        _require_bound_file(
            root,
            dossier_anchor,
            dossier_anchor_digest,
            "raw_run_manifest claim dossier anchor",
        )
        checkpoint_file = _existing_regular(
            root, checkpoint, "raw_run_manifest checkpoint"
        )
        checkpoint_data = _read_bounded_regular(
            checkpoint_file,
            "raw_run_manifest checkpoint",
            MAX_RECORD_BYTES,
        )
        if sha256_bytes(checkpoint_data) != checkpoint_digest:
            raise RepositoryFirstError(
                "raw_run_manifest checkpoint SHA-256 does not match"
            )
        memory = _research_memory_module()
        try:
            checkpoint_record = memory.parse_checkpoint(checkpoint_data, checkpoint)
        except memory.ResearchMemoryError as exc:
            raise RepositoryFirstError(
                f"raw_run_manifest checkpoint is not a canonical Durable Research Memory envelope: {exc}"
            ) from exc
        if checkpoint_record.get("checkpoint_id") != checkpoint_id:
            raise RepositoryFirstError(
                "raw_run_manifest checkpoint embedded ID does not match checkpoint_id"
            )
        if checkpoint_record.get("run_id") != run_id:
            raise RepositoryFirstError(
                "raw_run_manifest checkpoint run_id does not match"
            )
        if checkpoint_record.get("problem_ids") != [problem_id]:
            raise RepositoryFirstError(
                "raw_run_manifest checkpoint problem_ids must exactly bind problem_id"
            )
        if checkpoint_record.get("claim_ids") != claim_ids:
            raise RepositoryFirstError(
                "raw_run_manifest checkpoint claim_ids do not exactly match"
            )
        for index, prompt in enumerate(prompts):
            _require_bound_file(
                root,
                prompt["path"],
                prompt["sha256"],
                f"raw_run_manifest significant prompt {index}",
            )
        if availability == "PRESENT_LOCAL":
            _require_bound_file(root, archive_path, archive_digest, "raw archive", archive_bytes)
        else:
            candidate = root.joinpath(*PurePosixPath(archive_path).parts)
            if candidate.exists() or candidate.is_symlink():
                raise RepositoryFirstError("HASH_ONLY_PRUNED raw archive must be absent")


def _validate_axis(value: Any, axis: str) -> None:
    label = f"claim_assessment.axes.{axis}"
    item = _exact(value, label, {"axis", "status", "assessor_role_ids", "rationale", "evidence_paths"})
    if item["axis"] != axis:
        raise RepositoryFirstError(f"{label}.axis must equal {axis}; assessment axes cannot substitute")
    _enum(item["status"], f"{label}.status", AXIS_STATUSES[axis])
    _string_list(
        item["assessor_role_ids"], f"{label}.assessor_role_ids", identifiers=True
    )
    _scalar_text(item["rationale"], f"{label}.rationale")
    _path_list(item["evidence_paths"], f"{label}.evidence_paths")


def _validate_assessment(record: Any, root: Path, require_files: bool) -> None:
    item = _common_record(
        record,
        "claim_assessment",
        {"assessment_id", "campaign_id", "claim_id", "assessed_at_utc", "axes", "governance_note"},
    )
    _identifier(item["assessment_id"], "claim_assessment.assessment_id")
    _identifier(item["campaign_id"], "claim_assessment.campaign_id")
    _identifier(item["claim_id"], "claim_assessment.claim_id")
    _timestamp(item["assessed_at_utc"], "claim_assessment.assessed_at_utc")
    axes = _exact(item["axes"], "claim_assessment.axes", AXIS_STATUSES.keys())
    for axis in AXIS_STATUSES:
        _validate_axis(axes[axis], axis)
    if require_files and axes["independent_verification"]["status"] == "PASS":
        for path in axes["independent_verification"]["evidence_paths"]:
            _existing_regular(root, path, "independent verification evidence")
    if item["governance_note"] != "NO_AXIS_AUTOMATICALLY_PROMOTES_A_CLAIM":
        raise RepositoryFirstError("claim assessment must disclaim automatic promotion")


def _validate_source_use(record: Any, root: Path, require_files: bool) -> None:
    item = _common_record(
        record,
        "source_use",
        {
            "use_id",
            "campaign_id",
            "claim_id",
            "claim_statement_path",
            "claim_statement_sha256",
            "claim_hypotheses",
            "recorded_at_utc",
            "source_path",
            "original_sha256",
            "bibliographic_identity",
            "version",
            "anchors",
            "scope",
            "interface_search",
            "relation",
            "relation_audit",
        },
    )
    _identifier(item["use_id"], "source_use.use_id")
    _identifier(item["campaign_id"], "source_use.campaign_id")
    _identifier(item["claim_id"], "source_use.claim_id")
    statement_path = _evidence_path(
        item["claim_statement_path"], "source_use.claim_statement_path"
    )
    statement_digest = _sha256(
        item["claim_statement_sha256"], "source_use.claim_statement_sha256"
    )
    _string_list(item["claim_hypotheses"], "source_use.claim_hypotheses")
    _timestamp(item["recorded_at_utc"], "source_use.recorded_at_utc")
    source_path = _relpath(item["source_path"], "source_use.source_path", ("sources/",))
    digest = _sha256(item["original_sha256"], "source_use.original_sha256")
    identity = _exact(
        item["bibliographic_identity"],
        "source_use.bibliographic_identity",
        {"citation_key", "title", "authors", "identifiers"},
    )
    _identifier(identity["citation_key"], "source_use.bibliographic_identity.citation_key")
    _scalar_text(identity["title"], "source_use.bibliographic_identity.title", MAX_SHORT_TEXT, one_line=True)
    _string_list(identity["authors"], "source_use.bibliographic_identity.authors")
    identifiers = _array(
        identity["identifiers"], "source_use.bibliographic_identity.identifiers", 32, allow_empty=True
    )
    for index, identifier in enumerate(identifiers):
        entry = _exact(
            identifier,
            f"source_use.bibliographic_identity.identifiers[{index}]",
            {"scheme", "value"},
        )
        _enum(entry["scheme"], f"source identifier {index}.scheme", {"DOI", "MR", "ARXIV", "ISBN", "OTHER"})
        _scalar_text(entry["value"], f"source identifier {index}.value", MAX_SHORT_TEXT, one_line=True)
    version = _exact(
        item["version"], "source_use.version", {"version_label", "publication_date", "edition"}
    )
    _scalar_text(version["version_label"], "source_use.version.version_label", MAX_SHORT_TEXT, one_line=True)
    _optional_text(version["publication_date"], "source_use.version.publication_date")
    _optional_text(version["edition"], "source_use.version.edition")
    anchors = _array(item["anchors"], "source_use.anchors", 64)
    for index, anchor_value in enumerate(anchors):
        anchor = _exact(anchor_value, f"source_use.anchors[{index}]", {"anchor_type", "locator", "scope_note"})
        _enum(
            anchor["anchor_type"],
            f"source_use.anchors[{index}].anchor_type",
            {"PAGE", "THEOREM", "PROPOSITION", "LEMMA", "COROLLARY", "SECTION", "EQUATION", "DEFINITION"},
        )
        _scalar_text(anchor["locator"], f"source_use.anchors[{index}].locator", MAX_SHORT_TEXT, one_line=True)
        _scalar_text(anchor["scope_note"], f"source_use.anchors[{index}].scope_note")
    scope = _exact(
        item["scope"],
        "source_use.scope",
        {"source_scope", "claim_scope", "used_for", "does_not_establish"},
    )
    _scalar_text(item["scope"]["source_scope"], "source_use.scope.source_scope")
    _scalar_text(item["scope"]["claim_scope"], "source_use.scope.claim_scope")
    _string_list(scope["used_for"], "source_use.scope.used_for")
    _string_list(scope["does_not_establish"], "source_use.scope.does_not_establish")
    interface_search = _exact(
        item["interface_search"],
        "source_use.interface_search",
        {
            "hypotheses",
            "outputs",
            "invariants",
            "representations",
            "known_bottlenecks",
            "candidate_bridge_obligations",
        },
    )
    for key in ("hypotheses", "outputs", "representations"):
        _string_list(
            interface_search[key],
            f"source_use.interface_search.{key}",
            maximum=64,
        )
    for key in ("invariants", "known_bottlenecks", "candidate_bridge_obligations"):
        _string_list(
            interface_search[key],
            f"source_use.interface_search.{key}",
            maximum=64,
            allow_empty=True,
        )
    relation = _enum(
        item["relation"],
        "source_use.relation",
        {
            "EQUIVALENT",
            "SPECIALIZATION",
            "GENERALIZATION",
            "STRENGTHENING",
            "IMPLIES",
            "ANALOGY",
            "LANGUAGE_TRANSLATION",
            "NAVIGATION_CITATION",
            "PRIMARY_SOURCE",
            "UNRESOLVED",
        },
    )
    audit = item["relation_audit"]
    audited_relations = {
        "EQUIVALENT",
        "SPECIALIZATION",
        "GENERALIZATION",
        "STRENGTHENING",
        "IMPLIES",
        "LANGUAGE_TRANSLATION",
    }
    if relation in audited_relations:
        audit_item = _exact(
            audit,
            "source_use.relation_audit",
            {
                "audited_relation",
                "auditor_role_id",
                "source_scope",
                "claim_scope",
                "hypothesis_delta",
                "conclusion_delta",
                "translation_map_path",
                "evidence_paths",
            },
        )
        if audit_item["audited_relation"] != relation:
            raise RepositoryFirstError(
                "source relation cannot be promoted or relabeled without a matching audit"
            )
        _identifier(
            audit_item["auditor_role_id"],
            "source_use.relation_audit.auditor_role_id",
        )
        _scalar_text(audit_item["source_scope"], "source_use.relation_audit.source_scope")
        _scalar_text(audit_item["claim_scope"], "source_use.relation_audit.claim_scope")
        _scalar_text(
            audit_item["hypothesis_delta"],
            "source_use.relation_audit.hypothesis_delta",
        )
        _scalar_text(
            audit_item["conclusion_delta"],
            "source_use.relation_audit.conclusion_delta",
        )
        if relation == "LANGUAGE_TRANSLATION":
            translation_path = _evidence_path(
                audit_item["translation_map_path"],
                "source_use.relation_audit.translation_map_path",
            )
            if require_files:
                _existing_regular(root, translation_path, "source translation map")
        elif audit_item["translation_map_path"] is not None:
            raise RepositoryFirstError(
                "translation_map_path is permitted only for LANGUAGE_TRANSLATION"
            )
        _path_list(
            audit_item["evidence_paths"],
            "source_use.relation_audit.evidence_paths",
            allow_empty=False,
        )
        if require_files:
            for index, path in enumerate(audit_item["evidence_paths"]):
                _existing_regular(root, path, f"source relation audit evidence {index}")
    elif audit is not None:
        raise RepositoryFirstError(
            "relation_audit is reserved for exact logical or language relations"
        )
    if require_files:
        _require_bound_file(
            root,
            statement_path,
            statement_digest,
            "source_use claim statement",
        )
        _require_bound_file(root, source_path, digest, "source_use original")


def _validate_verification(record: Any, root: Path, require_files: bool) -> None:
    item = _common_record(
        record,
        "verification_coverage",
        {
            "coverage_id",
            "campaign_id",
            "claim_id",
            "recorded_at_utc",
            "coverage_matrix",
            "formal_theorem_scope",
            "environment",
            "axioms",
            "external_certificates",
            "replay",
        },
    )
    _identifier(item["coverage_id"], "verification_coverage.coverage_id")
    _identifier(item["campaign_id"], "verification_coverage.campaign_id")
    _identifier(item["claim_id"], "verification_coverage.claim_id")
    _timestamp(item["recorded_at_utc"], "verification_coverage.recorded_at_utc")
    rows = _array(item["coverage_matrix"], "verification_coverage.coverage_matrix", 128)
    row_ids: list[str] = []
    for index, row_value in enumerate(rows):
        row = _exact(
            row_value,
            f"verification_coverage.coverage_matrix[{index}]",
            {"obligation_id", "informal_scope", "method", "status", "uncovered_scope", "evidence_paths"},
        )
        row_ids.append(_identifier(row["obligation_id"], f"coverage row {index}.obligation_id"))
        _scalar_text(row["informal_scope"], f"coverage row {index}.informal_scope")
        _enum(row["method"], f"coverage row {index}.method", {"HUMAN_PROOF", "FORMAL", "COMPUTATION", "EXTERNAL_CERTIFICATE", "MIXED"})
        _enum(row["status"], f"coverage row {index}.status", {"UNCOVERED", "PARTIAL", "COVERED", "CONTESTED"})
        _optional_text(row["uncovered_scope"], f"coverage row {index}.uncovered_scope", MAX_TEXT)
        _path_list(row["evidence_paths"], f"coverage row {index}.evidence_paths")
    if len(row_ids) != len(set(row_ids)):
        raise RepositoryFirstError("verification coverage obligation IDs must be unique")
    formal = _exact(
        item["formal_theorem_scope"],
        "verification_coverage.formal_theorem_scope",
        {"status", "declarations", "excluded_scope", "correspondence_audit_paths"},
    )
    formal_status = _enum(formal["status"], "formal_theorem_scope.status", {"NONE", "PARTIAL", "COMPLETE"})
    declarations = _array(formal["declarations"], "formal_theorem_scope.declarations", 64, allow_empty=True)
    for index, declaration_value in enumerate(declarations):
        declaration = _exact(
            declaration_value,
            f"formal_theorem_scope.declarations[{index}]",
            {"declaration_id", "exact_type_path", "encoded_scope"},
        )
        _identifier(declaration["declaration_id"], f"formal declaration {index}.declaration_id")
        _evidence_path(declaration["exact_type_path"], f"formal declaration {index}.exact_type_path")
        _scalar_text(declaration["encoded_scope"], f"formal declaration {index}.encoded_scope")
    if formal_status == "NONE" and declarations:
        raise RepositoryFirstError("formal theorem scope NONE cannot list declarations")
    if formal_status != "NONE" and not declarations:
        raise RepositoryFirstError("formal theorem scope PARTIAL/COMPLETE requires declarations")
    _string_list(formal["excluded_scope"], "formal_theorem_scope.excluded_scope", allow_empty=True)
    _path_list(formal["correspondence_audit_paths"], "formal_theorem_scope.correspondence_audit_paths")
    environment = _exact(item["environment"], "verification_coverage.environment", {"tools", "libraries"})
    for group in ("tools", "libraries"):
        entries = _array(environment[group], f"verification_coverage.environment.{group}", 64, allow_empty=True)
        for index, entry_value in enumerate(entries):
            entry = _exact(entry_value, f"environment.{group}[{index}]", {"name", "version", "role"})
            _scalar_text(entry["name"], f"environment.{group}[{index}].name", MAX_SHORT_TEXT, one_line=True)
            _scalar_text(entry["version"], f"environment.{group}[{index}].version", MAX_SHORT_TEXT, one_line=True)
            _scalar_text(entry["role"], f"environment.{group}[{index}].role", MAX_SHORT_TEXT, one_line=True)
    axioms = _array(item["axioms"], "verification_coverage.axioms", 64, allow_empty=True)
    for index, axiom_value in enumerate(axioms):
        axiom = _exact(axiom_value, f"verification_coverage.axioms[{index}]", {"name", "classification", "scope", "evidence_paths"})
        _scalar_text(axiom["name"], f"axiom {index}.name", MAX_SHORT_TEXT, one_line=True)
        _enum(axiom["classification"], f"axiom {index}.classification", {"DECLARED", "IMPORTED", "UNKNOWN"})
        _scalar_text(axiom["scope"], f"axiom {index}.scope")
        _path_list(axiom["evidence_paths"], f"axiom {index}.evidence_paths")
    certificates = _array(
        item["external_certificates"], "verification_coverage.external_certificates", 64, allow_empty=True
    )
    for index, certificate_value in enumerate(certificates):
        certificate = _exact(
            certificate_value,
            f"verification_coverage.external_certificates[{index}]",
            {"certificate_id", "issuer", "scope", "local_path", "original_sha256", "verification_status"},
        )
        _identifier(certificate["certificate_id"], f"certificate {index}.certificate_id")
        _scalar_text(certificate["issuer"], f"certificate {index}.issuer", MAX_SHORT_TEXT, one_line=True)
        _scalar_text(certificate["scope"], f"certificate {index}.scope")
        path = _evidence_path(certificate["local_path"], f"certificate {index}.local_path")
        digest = _sha256(certificate["original_sha256"], f"certificate {index}.original_sha256")
        _enum(certificate["verification_status"], f"certificate {index}.verification_status", {"UNCHECKED", "VERIFIED", "REJECTED"})
        if require_files:
            _require_bound_file(root, path, digest, f"external certificate {index}")
    replay = _exact(
        item["replay"],
        "verification_coverage.replay",
        {"status", "procedure_manifest_path", "inputs", "output_paths", "tool_versions_bound"},
    )
    _enum(replay["status"], "verification_coverage.replay.status", {"NOT_RUN", "PASS", "FAIL", "PARTIAL"})
    procedure_path = _evidence_path(replay["procedure_manifest_path"], "verification_coverage.replay.procedure_manifest_path")
    inputs = _array(replay["inputs"], "verification_coverage.replay.inputs", 128, allow_empty=True)
    for index, input_value in enumerate(inputs):
        input_item = _exact(input_value, f"verification_coverage.replay.inputs[{index}]", {"path", "sha256"})
        path = _evidence_path(input_item["path"], f"replay input {index}.path")
        digest = _sha256(input_item["sha256"], f"replay input {index}.sha256")
        if require_files:
            _require_bound_file(root, path, digest, f"replay input {index}")
    _path_list(replay["output_paths"], "verification_coverage.replay.output_paths")
    _boolean(replay["tool_versions_bound"], "verification_coverage.replay.tool_versions_bound")
    if require_files:
        _existing_regular(root, procedure_path, "replay procedure manifest")


def _validate_feedback_plan(record: Any, root: Path, require_files: bool) -> None:
    item = _common_record(
        record,
        "expert_feedback_plan",
        {
            "plan_id",
            "campaign_id",
            "created_at_utc",
            "claim_ids",
            "claim_bindings",
            "expert_profile",
            "questions",
            "package_manifest_path",
            "package_manifest_sha256",
            "review",
            "human_trigger",
            "execution_state",
            "no_outbound_action",
        },
    )
    _identifier(item["plan_id"], "expert_feedback_plan.plan_id")
    _identifier(item["campaign_id"], "expert_feedback_plan.campaign_id")
    _timestamp(item["created_at_utc"], "expert_feedback_plan.created_at_utc")
    claim_ids = _string_list(
        item["claim_ids"], "expert_feedback_plan.claim_ids", identifiers=True
    )
    normalized_bindings = _claim_statement_bindings(
        item["claim_bindings"], "expert_feedback_plan.claim_bindings"
    )
    if [binding[0] for binding in normalized_bindings] != claim_ids:
        raise RepositoryFirstError(
            "expert feedback claim_bindings must exactly and in order bind claim_ids"
        )
    _scalar_text(item["expert_profile"], "expert_feedback_plan.expert_profile")
    _string_list(item["questions"], "expert_feedback_plan.questions")
    package = _relpath(
        item["package_manifest_path"],
        "expert_feedback_plan.package_manifest_path",
        ("research/repository_first/exports/",),
    )
    if not package.endswith("/manifest.json"):
        raise RepositoryFirstError("expert feedback package must name an export manifest")
    package_digest = _sha256(
        item["package_manifest_sha256"],
        "expert_feedback_plan.package_manifest_sha256",
    )
    review = _exact(item["review"], "expert_feedback_plan.review", {"status", "reviewed_at_utc", "reviewer_role_ids", "scope_note"})
    if review["status"] != "REVIEWED":
        raise RepositoryFirstError("expert feedback plan must be reviewed")
    reviewed_at = _timestamp(
        review["reviewed_at_utc"], "expert_feedback_plan.review.reviewed_at_utc"
    )
    _string_list(review["reviewer_role_ids"], "expert_feedback_plan.review.reviewer_role_ids", identifiers=True)
    _scalar_text(review["scope_note"], "expert_feedback_plan.review.scope_note")
    trigger = _exact(
        item["human_trigger"],
        "expert_feedback_plan.human_trigger",
        {
            "triggered_by_role_id",
            "triggered_at_utc",
            "disclosure_scope",
            "follow_up_owner_role_id",
        },
    )
    _identifier(
        trigger["triggered_by_role_id"],
        "expert_feedback_plan.human_trigger.triggered_by_role_id",
    )
    triggered_at = _timestamp(
        trigger["triggered_at_utc"],
        "expert_feedback_plan.human_trigger.triggered_at_utc",
    )
    if triggered_at > item["created_at_utc"]:
        raise RepositoryFirstError(
            "expert feedback human trigger cannot postdate plan creation"
        )
    if reviewed_at < item["created_at_utc"]:
        raise RepositoryFirstError(
            "expert feedback review cannot predate plan creation"
        )
    _scalar_text(
        trigger["disclosure_scope"],
        "expert_feedback_plan.human_trigger.disclosure_scope",
    )
    _identifier(
        trigger["follow_up_owner_role_id"],
        "expert_feedback_plan.human_trigger.follow_up_owner_role_id",
    )
    if item["execution_state"] != "LOCAL_ONLY_NOT_SENT":
        raise RepositoryFirstError("expert feedback plan cannot represent outbound execution")
    _boolean(item["no_outbound_action"], "expert_feedback_plan.no_outbound_action", True)
    if require_files:
        _require_bound_file(
            root,
            package,
            package_digest,
            "expert feedback export manifest",
        )
        manifest_data = _read_bounded_regular(
            root.joinpath(*PurePosixPath(package).parts),
            "expert feedback export manifest",
            MAX_RECORD_BYTES,
        )
        try:
            manifest_value = strict_json_loads(
                manifest_data.decode("utf-8"),
                "expert feedback export manifest",
            )
        except UnicodeDecodeError as exc:
            raise RepositoryFirstError(
                "expert feedback export manifest is not UTF-8"
            ) from exc
        manifest = _validate_export_manifest(manifest_value, root, True)
        if manifest["claim_ids"] != claim_ids:
            raise RepositoryFirstError(
                "expert feedback plan claim_ids do not exactly match the reviewed export"
            )
        if manifest["claim_bindings"] != item["claim_bindings"]:
            raise RepositoryFirstError(
                "expert feedback plan claim_bindings do not exactly match the reviewed export"
            )
        if item["created_at_utc"] < manifest["created_at_utc"]:
            raise RepositoryFirstError(
                "expert feedback plan creation predates the reviewed export manifest"
            )
        exported_files = {
            entry["path"]: entry["sha256"] for entry in manifest["included_files"]
        }
        for claim_id, _version, statement_path, statement_digest in normalized_bindings:
            if exported_files.get(statement_path) != statement_digest:
                raise RepositoryFirstError(
                    f"expert feedback claim {claim_id} statement preimage is not exactly bound in the reviewed export"
                )


def _validate_feedback_response(record: Any, root: Path, require_files: bool) -> None:
    item = _common_record(
        record,
        "expert_feedback_response",
        {
            "response_id",
            "campaign_id",
            "plan_id",
            "received_at_utc",
            "ingest_mode",
            "original_path",
            "original_sha256",
            "observations_path",
            "claim_implications",
            "automatic_claim_promotion",
            "no_outbound_action",
        },
    )
    _identifier(item["response_id"], "expert_feedback_response.response_id")
    _identifier(item["campaign_id"], "expert_feedback_response.campaign_id")
    _identifier(item["plan_id"], "expert_feedback_response.plan_id")
    _timestamp(item["received_at_utc"], "expert_feedback_response.received_at_utc")
    if item["ingest_mode"] != "USER_PROVIDED_LOCAL_IMPORT":
        raise RepositoryFirstError("expert feedback response must be a user-provided local import")
    dossier = f"problems/"
    original = _relpath(item["original_path"], "expert_feedback_response.original_path", (dossier, "sources/"))
    if "/repository_first/feedback_imports/" not in original and not original.startswith("sources/"):
        raise RepositoryFirstError("expert feedback original must be in dossier feedback_imports or sources")
    digest = _sha256(item["original_sha256"], "expert_feedback_response.original_sha256")
    observations = _evidence_path(item["observations_path"], "expert_feedback_response.observations_path")
    implications = _array(item["claim_implications"], "expert_feedback_response.claim_implications", 128)
    finding_ids: list[str] = []
    for index, implication_value in enumerate(implications):
        implication = _exact(
            implication_value,
            f"claim_implications[{index}]",
            {
                "finding_id",
                "claim_id",
                "claim_statement_version",
                "claim_statement_path",
                "claim_statement_sha256",
                "recommendation",
                "rationale",
            },
        )
        finding_ids.append(
            _identifier(implication["finding_id"], f"claim_implications[{index}].finding_id")
        )
        _identifier(implication["claim_id"], f"claim_implications[{index}].claim_id")
        _scalar_text(
            implication["claim_statement_version"],
            f"claim_implications[{index}].claim_statement_version",
            MAX_SHORT_TEXT,
            one_line=True,
        )
        _evidence_path(
            implication["claim_statement_path"],
            f"claim_implications[{index}].claim_statement_path",
        )
        _sha256(
            implication["claim_statement_sha256"],
            f"claim_implications[{index}].claim_statement_sha256",
        )
        _enum(implication["recommendation"], f"claim_implications[{index}].recommendation", {"NO_CHANGE", "RECHECK", "CHALLENGE", "SUPPORT"})
        _scalar_text(implication["rationale"], f"claim_implications[{index}].rationale")
    if len(finding_ids) != len(set(finding_ids)):
        raise RepositoryFirstError("expert feedback response finding_id values must be unique")
    _boolean(item["automatic_claim_promotion"], "expert_feedback_response.automatic_claim_promotion", False)
    _boolean(item["no_outbound_action"], "expert_feedback_response.no_outbound_action", True)
    if require_files:
        _require_bound_file(root, original, digest, "expert feedback original")
        _existing_regular(root, observations, "expert feedback observations")


VALIDATORS: dict[str, Callable[[Any, Path, bool], None]] = {
    "campaign": _validate_campaign,
    "phase_change": _validate_phase_change,
    "adjacent_result": _validate_adjacent_result,
    "failure_family": _validate_failure_family,
    "raw_run_manifest": _validate_raw_run,
    "claim_assessment": _validate_assessment,
    "source_use": _validate_source_use,
    "verification_coverage": _validate_verification,
    "expert_feedback_plan": _validate_feedback_plan,
    "expert_feedback_response": _validate_feedback_response,
}


def validate_record(record: Any, root: Path = ROOT, *, require_files: bool = False) -> dict[str, Any]:
    item = _object(record, "repository-first record")
    record_type = item.get("record_type")
    if not isinstance(record_type, str) or record_type not in RECORD_TYPES:
        raise RepositoryFirstError("record_type is missing or unsupported")
    _walk_key_policy(item, record_type)
    VALIDATORS[record_type](item, root, require_files)
    if len(canonical_json_bytes(item)) > MAX_RECORD_BYTES:
        raise RepositoryFirstError("record exceeds its canonical size bound")
    return item


def _safe_owner_id(value: str) -> str:
    """Return the generator-compatible normalized id for an owner name."""

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


def _validate_profile_process_steward(
    profile: dict[str, Any], policy: dict[str, Any]
) -> None:
    label = "LAB_PROFILE.json.repository_first.process_steward"
    process_steward = _scalar_text(
        policy["process_steward"],
        label,
        256,
        one_line=True,
    )
    if len(process_steward.splitlines()) != 1 or any(
        character in {"\u2028", "\u2029"}
        or unicodedata.category(character) == "Cc"
        for character in process_steward
    ):
        raise RepositoryFirstError(f"{label} must be one line without control characters")

    lab = _object(profile.get("lab"), "LAB_PROFILE.json.lab")
    modules_value = lab.get("modules")
    modules = modules_value if isinstance(modules_value, list) else []
    collaboration = lab.get("collaboration")
    if "team_collaboration" in modules:
        collaboration = _object(
            collaboration,
            "LAB_PROFILE.json.lab.collaboration for a team repository-first policy",
        )
        if process_steward != collaboration.get("steward_id"):
            raise RepositoryFirstError(
                "repository_first process_steward must exactly equal "
                "LAB_PROFILE.json.lab.collaboration.steward_id"
            )
        repository = _object(
            collaboration.get("repository"),
            "LAB_PROFILE.json.lab.collaboration.repository",
        )
        if repository.get("visibility") != "PRIVATE":
            raise RepositoryFirstError(
                "repository-first team laboratories require "
                "LAB_PROFILE.json.lab.collaboration.repository.visibility PRIVATE"
            )
        return

    owners_value = lab.get("owners")
    owners = owners_value if isinstance(owners_value, list) else []
    allowed_solo_stewards = {
        candidate
        for owner in owners
        if isinstance(owner, str)
        for candidate in (owner, _safe_owner_id(owner))
    }
    if process_steward not in allowed_solo_stewards:
        raise RepositoryFirstError(
            "repository_first process_steward must match a solo owner display name "
            "or generator-normalized owner id"
        )


def _profile_policy_enabled(root: Path) -> bool:
    path = root / "LAB_PROFILE.json"
    data = _read_bounded_regular(path, "LAB_PROFILE.json", MAX_INPUT_BYTES)
    try:
        profile = strict_json_loads(data.decode("utf-8"), "LAB_PROFILE.json")
    except UnicodeDecodeError as exc:
        raise RepositoryFirstError("LAB_PROFILE.json is not UTF-8") from exc
    profile = _object(profile, "LAB_PROFILE.json")
    policy = profile.get("repository_first")
    if policy is None:
        return False
    policy = _exact(
        policy,
        "LAB_PROFILE.json.repository_first",
        {"enabled"},
        {
            "canonical_repository_visibility",
            "raw_material_policy",
            "export_policy",
            "process_steward",
        },
    )
    enabled = policy.get("enabled")
    if not isinstance(enabled, bool):
        raise RepositoryFirstError(
            "LAB_PROFILE.json repository_first.enabled must be a boolean"
        )
    governed_fields = {
        "canonical_repository_visibility",
        "raw_material_policy",
        "export_policy",
        "process_steward",
    }
    present_governed = governed_fields & set(policy)
    if not enabled:
        if present_governed:
            raise RepositoryFirstError(
                "disabled repository_first policy must contain only enabled=false"
            )
        return False
    missing = governed_fields - set(policy)
    if missing:
        raise RepositoryFirstError(
            "enabled repository_first policy is missing: " + ", ".join(sorted(missing))
        )
    if policy["canonical_repository_visibility"] != "PRIVATE":
        raise RepositoryFirstError(
            "repository_first canonical_repository_visibility must be PRIVATE"
        )
    if policy["raw_material_policy"] != "LOCAL_UNTRACKED":
        raise RepositoryFirstError(
            "repository_first raw_material_policy must be LOCAL_UNTRACKED"
        )
    if policy["export_policy"] != "REVIEWED_ONLY":
        raise RepositoryFirstError(
            "repository_first export_policy must be REVIEWED_ONLY"
        )
    _validate_profile_process_steward(profile, policy)
    return enabled


def repository_enabled(root: Path = ROOT) -> bool:
    return _profile_policy_enabled(root)


def require_enabled(root: Path = ROOT) -> None:
    if not repository_enabled(root):
        raise RepositoryFirstError(
            "LAB_PROFILE.json repository_first.enabled is not true; write commands are dormant"
        )


def _dossier_from_record_path(relative: str) -> str:
    parts = PurePosixPath(relative).parts
    if len(parts) != 7:
        raise RepositoryFirstError(f"record path has the wrong depth: {relative}")
    if parts[0] != "problems" or parts[1] not in {"active", "backlog", "closed"}:
        raise RepositoryFirstError(f"record path is outside a problem dossier: {relative}")
    if parts[3:5] != ("repository_first", "records") or not parts[6].endswith(".json"):
        raise RepositoryFirstError(f"record path is not canonical: {relative}")
    return "/".join(parts[:3])


def canonical_record_path(record: dict[str, Any], dossier_path: str) -> str:
    record_type = record["record_type"]
    record_id = record[RECORD_ID_FIELDS[record_type]]
    return f"{dossier_path}/repository_first/records/{record_type}/{record_id}.json"


def _check_record_path(record: dict[str, Any], relative: str) -> str:
    dossier = _dossier_from_record_path(relative)
    if PurePosixPath(dossier).name != record["problem_id"]:
        raise RepositoryFirstError(f"record problem_id disagrees with dossier path: {relative}")
    expected = canonical_record_path(record, dossier)
    if relative != expected:
        raise RepositoryFirstError(f"record path must be {expected}")
    return dossier


def _scan_tree(root: Path, relative: str) -> list[str]:
    base = root.joinpath(*PurePosixPath(relative).parts)
    if not base.exists() and not base.is_symlink():
        return []
    try:
        root_info = base.lstat()
    except OSError as exc:
        raise RepositoryFirstError(f"cannot inspect {relative}: {exc}") from exc
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise RepositoryFirstError(f"{relative} must be a non-symlink directory")
    result: list[str] = []
    stack = [base]
    while stack:
        directory = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise RepositoryFirstError(f"cannot scan {directory}: {exc}") from exc
        for entry in entries:
            info = entry.stat(follow_symlinks=False)
            path = Path(entry.path)
            relative_path = path.relative_to(root).as_posix()
            if stat.S_ISLNK(info.st_mode):
                raise RepositoryFirstError(f"repository-first state contains a symlink: {relative_path}")
            if stat.S_ISDIR(info.st_mode):
                stack.append(path)
            elif stat.S_ISREG(info.st_mode):
                result.append(relative_path)
            else:
                raise RepositoryFirstError(f"repository-first state contains a special file: {relative_path}")
    return sorted(result)


def scan_records(root: Path = ROOT) -> list[tuple[dict[str, Any], str]]:
    paths: list[str] = []
    for state in ("active", "backlog", "closed"):
        state_root = root / "problems" / state
        if not state_root.is_dir():
            continue
        for dossier in sorted(state_root.iterdir(), key=lambda path: path.name):
            try:
                info = dossier.lstat()
            except OSError as exc:
                raise RepositoryFirstError(f"cannot inspect dossier {dossier}: {exc}") from exc
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                continue
            relative = dossier.relative_to(root).as_posix() + "/repository_first/records"
            for path in _scan_tree(root, relative):
                if not path.endswith(".json"):
                    raise RepositoryFirstError(f"record tree contains a non-JSON file: {path}")
                paths.append(path)
    if len(paths) > MAX_RECORDS:
        raise RepositoryFirstError("repository-first record count exceeds its bound")
    records: list[tuple[dict[str, Any], str]] = []
    for path in sorted(paths):
        _require_immutable_record_mode(root / path, path)
        data = _read_bounded_regular(root / path, path, MAX_RECORD_BYTES)
        try:
            value = strict_json_loads(data.decode("utf-8"), path)
        except UnicodeDecodeError as exc:
            raise RepositoryFirstError(f"{path} is not UTF-8") from exc
        record = validate_record(value, root, require_files=True)
        _check_record_path(record, path)
        records.append((record, path))
    return records


def _campaign_roles(campaign: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {role["role_id"]: role for role in campaign["roles"]}


def validate_cross_records(records: Sequence[tuple[dict[str, Any], str]]) -> None:
    campaigns: dict[str, tuple[dict[str, Any], str]] = {}
    raw_runs: dict[str, dict[str, Any]] = {}
    failure_families: dict[str, dict[str, Any]] = {}
    feedback_plans: dict[str, dict[str, Any]] = {}
    adjacent_claims: set[str] = set()
    for record, path in records:
        if record["record_type"] == "campaign":
            campaign_id = record["campaign_id"]
            if campaign_id in campaigns:
                raise RepositoryFirstError(f"duplicate campaign_id: {campaign_id}")
            campaigns[campaign_id] = (record, path)
        elif record["record_type"] == "raw_run_manifest":
            run_id = record["run_id"]
            if run_id in raw_runs:
                raise RepositoryFirstError(f"duplicate raw run_id: {run_id}")
            raw_runs[run_id] = record
        elif record["record_type"] == "expert_feedback_plan":
            plan_id = record["plan_id"]
            if plan_id in feedback_plans:
                raise RepositoryFirstError(f"duplicate feedback plan_id: {plan_id}")
            feedback_plans[plan_id] = record
        elif record["record_type"] == "failure_family":
            family_id = record["family_id"]
            if family_id in failure_families:
                raise RepositoryFirstError(f"duplicate failure family_id: {family_id}")
            failure_families[family_id] = record
        elif record["record_type"] == "adjacent_result":
            claim_id = record["new_claim_id"]
            if claim_id in adjacent_claims:
                raise RepositoryFirstError(f"adjacent new_claim_id is not new: {claim_id}")
            adjacent_claims.add(claim_id)

    phase_changes: dict[str, list[dict[str, Any]]] = {}
    for record, path in records:
        record_type = record["record_type"]
        if record_type == "campaign":
            continue
        campaign_id = record.get("campaign_id")
        if campaign_id not in campaigns:
            raise RepositoryFirstError(f"{path} refers to unknown campaign_id {campaign_id!r}")
        campaign, campaign_path = campaigns[campaign_id]
        if record["problem_id"] != campaign["problem_id"]:
            raise RepositoryFirstError(f"{path} crosses a campaign problem boundary")
        if _dossier_from_record_path(path) != _dossier_from_record_path(campaign_path):
            raise RepositoryFirstError(f"{path} crosses a campaign dossier boundary")
        roles = _campaign_roles(campaign)
        role_fields: list[str] = []
        if record_type == "phase_change":
            role_fields = [record["changed_by_role_id"], *record["active_role_ids"]]
            phase_changes.setdefault(campaign_id, []).append(record)
        elif record_type == "raw_run_manifest":
            role_fields = [record["role_id"]]
            if record["claim_dossier_path"] != _dossier_from_record_path(path):
                raise RepositoryFirstError(f"{path} raw manifest does not link its containing dossier")
        elif record_type == "expert_feedback_response":
            original = record["original_path"]
            if original.startswith("problems/") and not original.startswith(
                _dossier_from_record_path(path) + "/repository_first/feedback_imports/"
            ):
                raise RepositoryFirstError(
                    f"{path} feedback response crosses a dossier boundary"
                )
        elif record_type == "claim_assessment":
            for axis in AXIS_STATUSES:
                role_fields.extend(record["axes"][axis]["assessor_role_ids"])
            independent = record["axes"]["independent_verification"]
            if independent["status"] == "PASS" and not any(
                roles.get(role_id, {}).get("role_kind") == "INDEPENDENT_VERIFIER"
                for role_id in independent["assessor_role_ids"]
            ):
                raise RepositoryFirstError(
                    f"{path} independent verification PASS lacks an independent-verifier role"
                )
            if independent["status"] == "PASS":
                # Roles are labels; the same actor cannot gain independence by
                # changing labels (or actor_class). Honest self-checks remain useful.
                authors = {
                    role["actor_id"].casefold()
                    for role in roles.values()
                    if role["role_kind"] in {"CLAIM_GENERATOR", "FORMALIZER"}
                }
                if any(
                    roles.get(role_id, {}).get("actor_id", "").casefold() in authors
                    for role_id in independent["assessor_role_ids"]
                ):
                    raise RepositoryFirstError(
                        f"{path} independent verification PASS includes an author actor; "
                        "record self-check evidence without independent PASS, or use a separate verifier"
                    )
                if not independent["evidence_paths"]:
                    raise RepositoryFirstError(
                        f"{path} independent verification PASS needs verification evidence"
                    )
            human_axis = record["axes"]["human_rederivation_comprehension"]
            if human_axis["status"] == "PASS" and not any(
                roles.get(role_id, {}).get("actor_class") == "HUMAN"
                for role_id in human_axis["assessor_role_ids"]
            ):
                raise RepositoryFirstError(
                    f"{path} human re-derivation PASS lacks a HUMAN assessor"
                )
        elif record_type == "source_use" and record["relation_audit"] is not None:
            role_fields = [record["relation_audit"]["auditor_role_id"]]
        elif record_type == "expert_feedback_plan":
            role_fields = [
                *record["review"]["reviewer_role_ids"],
                record["human_trigger"]["triggered_by_role_id"],
                record["human_trigger"]["follow_up_owner_role_id"],
            ]
        for role_id in role_fields:
            if role_id not in roles:
                raise RepositoryFirstError(f"{path} refers to undeclared role_id {role_id}")
        if record_type == "expert_feedback_plan":
            dossier = _dossier_from_record_path(path)
            for binding in record["claim_bindings"]:
                if not binding["claim_statement_path"].startswith(dossier + "/"):
                    raise RepositoryFirstError(
                        f"{path} expert feedback claim binding crosses a dossier boundary"
                    )
            for field in ("triggered_by_role_id", "follow_up_owner_role_id"):
                role_id = record["human_trigger"][field]
                if roles[role_id]["actor_class"] != "HUMAN":
                    raise RepositoryFirstError(
                        f"{path} human_trigger.{field} must name a HUMAN role"
                    )
        if record_type == "adjacent_result":
            if record["new_claim_id"] in campaign["target_claim_ids"]:
                raise RepositoryFirstError(f"{path} adjacent claim ID already names a campaign target")
        elif record_type == "failure_family":
            aggregate = record["aggregate_actual_denominator"]
            aggregate_unknown = set(aggregate["unknown_fields"])
            expected_unknown: set[str] = set()
            expected_totals = {field: 0 for field in DENOMINATOR_FIELDS}
            for run_id in record["member_run_ids"]:
                run = raw_runs.get(run_id)
                if run is None or run["campaign_id"] != campaign_id:
                    raise RepositoryFirstError(f"{path} failure family refers to an unknown campaign run")
                actual = run["execution_provenance"]["actual_denominator"]
                run_unknown = set(actual["unknown_fields"])
                expected_unknown.update(run_unknown)
                for field in DENOMINATOR_FIELDS:
                    if field not in run_unknown:
                        expected_totals[field] += actual[field]
            if aggregate_unknown != expected_unknown:
                raise RepositoryFirstError(
                    f"{path} aggregate denominator unknown_fields do not preserve member unknowns"
                )
            for field in DENOMINATOR_FIELDS:
                if field not in aggregate_unknown and aggregate[field] != expected_totals[field]:
                    raise RepositoryFirstError(
                        f"{path} aggregate denominator {field} is not the member-run sum"
                    )
        if record_type == "expert_feedback_response":
            plan = feedback_plans.get(record["plan_id"])
            if plan is None or plan["campaign_id"] != campaign_id:
                raise RepositoryFirstError(f"{path} response refers to an unknown campaign feedback plan")
            if record["received_at_utc"] < plan["review"]["reviewed_at_utc"]:
                raise RepositoryFirstError(
                    f"{path} feedback response predates review of its feedback plan"
                )
            planned_bindings = {
                binding["claim_id"]: (
                    binding["claim_statement_version"],
                    binding["claim_statement_path"],
                    binding["claim_statement_sha256"],
                )
                for binding in plan["claim_bindings"]
            }
            for implication in record["claim_implications"]:
                exact_preimage = (
                    implication["claim_statement_version"],
                    implication["claim_statement_path"],
                    implication["claim_statement_sha256"],
                )
                if planned_bindings.get(implication["claim_id"]) != exact_preimage:
                    raise RepositoryFirstError(
                        f"{path} feedback finding is outside the plan's exact bound claim preimages"
                    )

    for campaign_id, changes in phase_changes.items():
        campaign = campaigns[campaign_id][0]
        changes.sort(key=lambda item: item["sequence"])
        expected_phase = campaign["initial_phase"]
        previous_id: Optional[str] = None
        previous_time = campaign["created_at_utc"]
        for expected_sequence, change in enumerate(changes, start=1):
            if change["sequence"] != expected_sequence:
                raise RepositoryFirstError(f"campaign {campaign_id} phase-change sequence has a gap")
            if change["previous_change_id"] != previous_id:
                raise RepositoryFirstError(f"campaign {campaign_id} phase-change predecessor is wrong")
            if change["from_phase"] != expected_phase:
                raise RepositoryFirstError(f"campaign {campaign_id} phase-change source is wrong")
            if change["changed_at_utc"] < previous_time:
                raise RepositoryFirstError(
                    f"campaign {campaign_id} phase-change timestamps are not monotone"
                )
            for family_id in change["prior_failure_family_ids"]:
                family = failure_families.get(family_id)
                if family is None or family["campaign_id"] != campaign_id:
                    raise RepositoryFirstError(
                        f"campaign {campaign_id} retry refers to an unknown failure family"
                    )
            expected_phase = change["to_phase"]
            previous_id = change["change_id"]
            previous_time = change["changed_at_utc"]

    for run_id, run in raw_runs.items():
        campaign = campaigns[run["campaign_id"]][0]
        if run["started_at_utc"] < campaign["created_at_utc"]:
            raise RepositoryFirstError(
                f"raw run {run_id} starts before its campaign"
            )
        expected_phase = campaign["initial_phase"]
        for change in sorted(
            phase_changes.get(run["campaign_id"], []),
            key=lambda item: item["sequence"],
        ):
            if change["changed_at_utc"] <= run["started_at_utc"]:
                expected_phase = change["to_phase"]
        if run["phase"] != expected_phase:
            raise RepositoryFirstError(
                f"raw run {run_id} phase disagrees with the campaign phase timeline"
            )


def _raw_archive_is_ignored(root: Path) -> bool:
    path = root / ".gitignore"
    data = _read_bounded_regular(path, ".gitignore", 256 * 1024)
    try:
        lines = [line.strip() for line in data.decode("utf-8").splitlines()]
    except UnicodeDecodeError as exc:
        raise RepositoryFirstError(".gitignore is not UTF-8") from exc
    if "research/raw_runs/archive/" not in lines:
        return False
    return not any(line.startswith("!research/raw_runs/archive") for line in lines)


def _validate_export_manifest(manifest: Any, root: Path, require_files: bool) -> dict[str, Any]:
    item = _exact(
        manifest,
        "export_package_manifest",
        {
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
        },
    )
    _walk_key_policy(item, "export_package_manifest")
    if item["schema_version"] != SCHEMA_VERSION or item["record_type"] != "export_package_manifest":
        raise RepositoryFirstError("invalid export manifest type/version")
    export_id = _identifier(item["export_id"], "export_id")
    created_at = _timestamp(item["created_at_utc"], "export.created_at_utc")
    expected_root = f"research/repository_first/exports/{export_id}"
    if _relpath(item["package_root"], "export.package_root") != expected_root:
        raise RepositoryFirstError(f"export.package_root must be {expected_root}")
    _scalar_text(item["purpose"], "export.purpose")
    claim_ids = _string_list(item["claim_ids"], "export.claim_ids", identifiers=True)
    claim_bindings = _claim_statement_bindings(
        item["claim_bindings"], "export.claim_bindings"
    )
    if [binding[0] for binding in claim_bindings] != claim_ids:
        raise RepositoryFirstError(
            "export claim_bindings must exactly and in order bind claim_ids"
        )
    checkpoints = _array(item["source_checkpoint_paths"], "export.source_checkpoint_paths", 128)
    checkpoint_paths = [_checkpoint_path(value, f"export.source_checkpoint_paths[{index}]") for index, value in enumerate(checkpoints)]
    if len(checkpoint_paths) != len(set(checkpoint_paths)):
        raise RepositoryFirstError("export source checkpoints contain duplicates")
    review = _exact(item["review"], "export.review", {"status", "reviewed_at_utc", "reviewer_role_ids", "scope_note"})
    if review["status"] != "REVIEWED":
        raise RepositoryFirstError("export package must be reviewed")
    reviewed_at = _timestamp(
        review["reviewed_at_utc"], "export.review.reviewed_at_utc"
    )
    if reviewed_at > created_at:
        raise RepositoryFirstError(
            "export review cannot postdate export manifest creation"
        )
    _string_list(review["reviewer_role_ids"], "export.review.reviewer_role_ids", identifiers=True)
    _scalar_text(review["scope_note"], "export.review.scope_note")
    files = _array(item["included_files"], "export.included_files", MAX_EXPORT_FILES)
    seen_paths: set[str] = set()
    for index, file_value in enumerate(files):
        entry = _exact(file_value, f"export.included_files[{index}]", {"path", "sha256", "bytes", "purpose"})
        path = _relpath(entry["path"], f"export.included_files[{index}].path")
        if path.startswith("research/raw_runs/archive/"):
            raise RepositoryFirstError("raw archives cannot enter an export package")
        if path.startswith(expected_root + "/") or _secret_or_hidden_path(path):
            raise RepositoryFirstError("export input names package output, credential, or hidden prompt material")
        if path in seen_paths:
            raise RepositoryFirstError("export included file paths must be unique")
        seen_paths.add(path)
        digest = _sha256(entry["sha256"], f"export.included_files[{index}].sha256")
        size = _integer(entry["bytes"], f"export.included_files[{index}].bytes", 0, 2**60)
        _scalar_text(entry["purpose"], f"export.included_files[{index}].purpose", MAX_SHORT_TEXT, one_line=True)
        if require_files:
            _require_bound_file(root, path, digest, f"export included file {index}", size)
    exported_files = {
        entry["path"]: entry["sha256"] for entry in item["included_files"]
    }
    for claim_id, _version, statement_path, statement_digest in claim_bindings:
        if exported_files.get(statement_path) != statement_digest:
            raise RepositoryFirstError(
                f"export claim {claim_id} statement preimage is not exactly included"
            )
    exclusions = _exact(
        item["exclusions"],
        "export.exclusions",
        {"raw_archives", "credentials", "hidden_prompts", "chain_of_thought", "outbound_actions"},
    )
    for key in exclusions:
        _boolean(exclusions[key], f"export.exclusions.{key}", True)
    _boolean(item["no_outbound_action"], "export.no_outbound_action", True)
    _boolean(item["automatic_claim_promotion"], "export.automatic_claim_promotion", False)
    digest = _sha256(item["manifest_payload_sha256"], "export.manifest_payload_sha256")
    body = dict(item)
    del body["manifest_payload_sha256"]
    if sha256_bytes(canonical_json_bytes(body)) != digest:
        raise RepositoryFirstError("export manifest payload digest does not match")
    if require_files:
        for path in checkpoint_paths:
            _existing_regular(root, path, "export source checkpoint")
    return item


def _validate_observation(observation: Any, root: Path, require_files: bool) -> dict[str, Any]:
    item = _exact(
        observation,
        "effectiveness_observation",
        {
            "schema_version",
            "record_type",
            "observation_id",
            "recorded_at_utc",
            "period",
            "collection_boundaries",
            "source_records",
            "source_set_sha256",
            "metrics",
            "axis_status_counts",
            "denominator_unknown_counts",
            "limitations",
        },
    )
    _walk_key_policy(item, "effectiveness_observation")
    if item["schema_version"] != SCHEMA_VERSION or item["record_type"] != "effectiveness_observation":
        raise RepositoryFirstError("invalid effectiveness observation type/version")
    _identifier(item["observation_id"], "observation_id")
    _timestamp(item["recorded_at_utc"], "observation.recorded_at_utc")
    period = _exact(item["period"], "observation.period", {"start", "end"})
    start = _date(period["start"], "observation.period.start")
    end = _date(period["end"], "observation.period.end")
    if end < start:
        raise RepositoryFirstError("observation period end precedes start")
    boundaries = _exact(
        item["collection_boundaries"],
        "observation.collection_boundaries",
        {"mode", "lab_local_only", "telemetry", "background_process", "fleet_scan"},
    )
    if boundaries["mode"] != "EXPLICIT_PASSIVE_LOCAL_SNAPSHOT":
        raise RepositoryFirstError("effectiveness observation mode is invalid")
    _boolean(boundaries["lab_local_only"], "observation.lab_local_only", True)
    _boolean(boundaries["telemetry"], "observation.telemetry", False)
    _boolean(boundaries["background_process"], "observation.background_process", False)
    _boolean(boundaries["fleet_scan"], "observation.fleet_scan", False)
    sources = _array(item["source_records"], "observation.source_records", MAX_RECORDS, allow_empty=True)
    bindings: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for index, source_value in enumerate(sources):
        source = _exact(source_value, f"observation.source_records[{index}]", {"path", "sha256", "record_type"})
        path = _relpath(source["path"], f"observation.source_records[{index}].path", ("problems/",))
        if path in seen_paths:
            raise RepositoryFirstError("observation source record paths must be unique")
        seen_paths.add(path)
        digest = _sha256(source["sha256"], f"observation.source_records[{index}].sha256")
        _enum(source["record_type"], f"observation.source_records[{index}].record_type", RECORD_TYPES)
        bindings.append({"path": path, "sha256": digest, "record_type": source["record_type"]})
        if require_files:
            _require_bound_file(root, path, digest, f"observation source record {index}")
    source_digest = _sha256(item["source_set_sha256"], "observation.source_set_sha256")
    if sha256_bytes(canonical_json_bytes(bindings)) != source_digest:
        raise RepositoryFirstError("observation source-set digest does not match")
    metric_names = set(RECORD_TYPES) | {"total_records", "raw_checkpoint_links", "raw_dossier_links"}
    metrics = _exact(item["metrics"], "observation.metrics", metric_names)
    for name in metric_names:
        _integer(metrics[name], f"observation.metrics.{name}", 0, MAX_RECORDS)
    if metrics["total_records"] != len(sources):
        raise RepositoryFirstError("observation total_records does not match source_records")
    axis_counts = _array(item["axis_status_counts"], "observation.axis_status_counts", 128, allow_empty=True)
    seen_axes: set[tuple[str, str]] = set()
    for index, row_value in enumerate(axis_counts):
        row = _exact(row_value, f"observation.axis_status_counts[{index}]", {"axis", "status", "count"})
        axis = _enum(row["axis"], f"axis count {index}.axis", AXIS_STATUSES)
        status_value = _enum(row["status"], f"axis count {index}.status", AXIS_STATUSES[axis])
        if (axis, status_value) in seen_axes:
            raise RepositoryFirstError("observation axis/status rows must be unique")
        seen_axes.add((axis, status_value))
        _integer(row["count"], f"axis count {index}.count", 0, MAX_RECORDS)
    denominator = _exact(
        item["denominator_unknown_counts"],
        "observation.denominator_unknown_counts",
        {"vector", "model", "harness"},
    )
    for name in denominator:
        _integer(denominator[name], f"observation.denominator_unknown_counts.{name}", 0, MAX_RECORDS)
    _string_list(item["limitations"], "observation.limitations")
    return item


def _scan_exports(root: Path) -> list[tuple[dict[str, Any], str]]:
    files = _scan_tree(root, "research/repository_first/exports")
    result: list[tuple[dict[str, Any], str]] = []
    for path in files:
        if not path.endswith("/manifest.json"):
            raise RepositoryFirstError(f"export tree contains a non-manifest file: {path}")
        _require_immutable_record_mode(root / path, path)
        data = _read_bounded_regular(root / path, path, MAX_RECORD_BYTES)
        value = strict_json_loads(data.decode("utf-8"), path)
        manifest = _validate_export_manifest(value, root, True)
        expected = f"{manifest['package_root']}/manifest.json"
        if path != expected:
            raise RepositoryFirstError(f"export manifest path must be {expected}")
        result.append((manifest, path))
    return result


def _scan_observations(root: Path) -> list[tuple[dict[str, Any], str]]:
    files = _scan_tree(root, "research/repository_first/observations")
    result: list[tuple[dict[str, Any], str]] = []
    for path in files:
        if not path.endswith(".json"):
            raise RepositoryFirstError(f"observation tree contains a non-JSON file: {path}")
        _require_immutable_record_mode(root / path, path)
        data = _read_bounded_regular(root / path, path, MAX_RECORD_BYTES)
        value = strict_json_loads(data.decode("utf-8"), path)
        observation = _validate_observation(value, root, True)
        expected = f"research/repository_first/observations/{observation['observation_id']}.json"
        if path != expected:
            raise RepositoryFirstError(f"observation path must be {expected}")
        result.append((observation, path))
    return result


def validate_repository(root: Path = ROOT) -> dict[str, Any]:
    if not repository_enabled(root):
        return {
            "schema_version": SCHEMA_VERSION,
            "policy": POLICY_ID,
            "status": "DISABLED",
            "records_validated": 0,
            "exports_validated": 0,
            "observations_validated": 0,
        }
    if not _raw_archive_is_ignored(root):
        raise RepositoryFirstError("research/raw_runs/archive/ must remain ignored by default")
    records = scan_records(root)
    validate_cross_records(records)
    exports = _scan_exports(root)
    observations = _scan_observations(root)
    return {
        "schema_version": SCHEMA_VERSION,
        "policy": POLICY_ID,
        "status": "VALID",
        "records_validated": len(records),
        "exports_validated": len(exports),
        "observations_validated": len(observations),
    }


def _ensure_safe_parent(root: Path, relative_parent: str) -> Path:
    current = root
    for part in PurePosixPath(relative_parent).parts:
        current = current / part
        try:
            current.mkdir(mode=0o755)
        except FileExistsError:
            pass
        except OSError as exc:
            raise RepositoryFirstError(f"cannot create output parent {relative_parent}: {exc}") from exc
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise RepositoryFirstError(f"output parent is not a safe directory: {current}")
    return current


def atomic_publish_noclobber(root: Path, relative: str, data: bytes, *, mode: int = 0o444) -> Path:
    relative = _relpath(relative, "output path")
    if len(data) > MAX_RECORD_BYTES:
        raise RepositoryFirstError("output exceeds its byte bound")
    target = root.joinpath(*PurePosixPath(relative).parts)
    parent = _ensure_safe_parent(root, PurePosixPath(relative).parent.as_posix())
    temporary = parent / f".repository-first-{secrets.token_hex(16)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = None
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode, follow_symlinks=False)
        try:
            os.link(temporary, target, follow_symlinks=False)
        except FileExistsError as exc:
            raise RepositoryFirstError(f"refusing to overwrite existing output: {relative}") from exc
        except OSError as exc:
            if exc.errno in {errno.EEXIST, errno.ENOTEMPTY}:
                raise RepositoryFirstError(f"refusing to overwrite existing output: {relative}") from exc
            raise RepositoryFirstError(f"atomic no-clobber publication failed: {exc}") from exc
        try:
            directory_fd = os.open(parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return target
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def record_packet(root: Path, record: Any, output_path: str) -> Path:
    require_enabled(root)
    if not _raw_archive_is_ignored(root):
        raise RepositoryFirstError("research/raw_runs/archive/ must remain ignored by default")
    item = validate_record(record, root, require_files=True)
    output = _relpath(output_path, "record output path", ("problems/active/", "problems/backlog/", "problems/closed/"))
    _check_record_path(item, output)
    dossier = _dossier_from_record_path(output)
    _existing_path(root, dossier, "record dossier", regular=False)
    candidate = root.joinpath(*PurePosixPath(output).parts)
    if candidate.exists() or candidate.is_symlink():
        raise RepositoryFirstError(f"refusing to overwrite existing output: {output}")
    existing = scan_records(root)
    validate_cross_records([*existing, (item, output)])
    return atomic_publish_noclobber(root, output, canonical_json_bytes(item))


def _validate_export_request(value: Any, *, require_review: bool = True) -> dict[str, Any]:
    _walk_key_policy(_object(value, "export request"), "export_request")
    item = _exact(
        value,
        "export request",
        {
            "schema_version",
            "export_id",
            "created_at_utc",
            "purpose",
            "claim_ids",
            "claim_bindings",
            "source_checkpoint_paths",
            "review",
            "included_files",
        },
    )
    if type(item["schema_version"]) is not int or item["schema_version"] != EXPORT_REQUEST_VERSION:
        raise RepositoryFirstError(
            "export request requires version 2 file bindings; run prepare-export, then review the exact selection"
        )
    _identifier(item["export_id"], "export request export_id")
    created_at = _timestamp(
        item["created_at_utc"], "export request created_at_utc"
    )
    _scalar_text(item["purpose"], "export request purpose")
    claim_ids = _string_list(
        item["claim_ids"], "export request claim_ids", identifiers=True
    )
    claim_bindings = _claim_statement_bindings(
        item["claim_bindings"], "export request claim_bindings"
    )
    if [binding[0] for binding in claim_bindings] != claim_ids:
        raise RepositoryFirstError(
            "export request claim_bindings must exactly and in order bind claim_ids"
        )
    checkpoints = _array(item["source_checkpoint_paths"], "export request source_checkpoint_paths", 128)
    for index, checkpoint in enumerate(checkpoints):
        _checkpoint_path(checkpoint, f"export request source checkpoint {index}")
    review = _exact(item["review"], "export request review", {"status", "reviewed_at_utc", "reviewer_role_ids", "scope_note"})
    if require_review and review["status"] != "REVIEWED":
        raise RepositoryFirstError("export request must already be reviewed")
    _enum(review["status"], "export request review status", {"PENDING", "REVIEWED"})
    if review["status"] == "REVIEWED":
        reviewed_at = _timestamp(review["reviewed_at_utc"], "export request review time")
        if reviewed_at > created_at:
            raise RepositoryFirstError("export request review cannot postdate manifest creation")
        _string_list(review["reviewer_role_ids"], "export request reviewer_role_ids", identifiers=True)
    elif review["reviewed_at_utc"] is not None or review["reviewer_role_ids"] != []:
        raise RepositoryFirstError("pending export review must not retain an earlier approval")
    _scalar_text(review["scope_note"], "export request scope_note")
    files = _array(item["included_files"], "export request included_files", MAX_EXPORT_FILES)
    included_paths: list[str] = []
    for index, file_value in enumerate(files):
        entry = _exact(file_value, f"export request included_files[{index}]", {"path", "purpose", "sha256", "bytes"})
        path = _relpath(entry["path"], f"export request included_files[{index}].path")
        if path.startswith("research/raw_runs/archive/") or _secret_or_hidden_path(path):
            raise RepositoryFirstError("export request includes forbidden raw, credential, or hidden prompt material")
        included_paths.append(path)
        _sha256(entry["sha256"], f"export request included_files[{index}].sha256")
        _integer(entry["bytes"], f"export request included_files[{index}].bytes", minimum=0)
        _scalar_text(entry["purpose"], f"export request included_files[{index}].purpose", MAX_SHORT_TEXT, one_line=True)
    if len(included_paths) != len(set(included_paths)):
        raise RepositoryFirstError("export request included paths must be unique")
    for claim_id, _version, statement_path, _statement_digest in claim_bindings:
        if statement_path not in included_paths:
            raise RepositoryFirstError(
                f"export request claim {claim_id} statement preimage is not included"
            )
    if not set(checkpoints).issubset(included_paths):
        raise RepositoryFirstError("export source checkpoints must be included in the reviewed files")
    return item


def prepare_export(root: Path, selection: Any) -> dict[str, Any]:
    """Bind current bytes for review, without inheriting any prior approval.

    Accept a v1 selection or a v2 draft/reviewed request. Read no selected file
    before validating its path. Return a draft; do not mutate the caller's data.
    """
    require_enabled(root)
    item = copy.deepcopy(_object(selection, "export selection"))
    if type(item.get("schema_version")) is not int or item["schema_version"] not in {1, 2}:
        raise RepositoryFirstError("export selection schema_version must be 1 or 2")
    item["schema_version"] = EXPORT_REQUEST_VERSION
    item["review"] = {
        "status": "PENDING", "reviewed_at_utc": None, "reviewer_role_ids": [],
        "scope_note": "Review these exact file versions, claim versions and disclosure scope before building.",
    }
    for index, value in enumerate(_array(item.get("included_files"), "export selection files", MAX_EXPORT_FILES)):
        entry = _object(value, f"export selection file {index}")
        if set(entry) not in ({"path", "purpose"}, {"path", "purpose", "sha256", "bytes"}):
            raise RepositoryFirstError("export selection files require path/purpose and optional sha256/bytes")
        entry.update(sha256="0" * 64, bytes=0)
    _validate_export_request(item, require_review=False)
    package_root = f"research/repository_first/exports/{item['export_id']}/"
    for entry in item["included_files"]:
        if entry["path"].startswith(package_root):
            raise RepositoryFirstError("export request cannot include its own output")
        target = _existing_regular(root, entry["path"], "export selection")
        entry["sha256"], entry["bytes"] = _hash_file(target)
    by_path = {entry["path"]: entry["sha256"] for entry in item["included_files"]}
    for binding in item["claim_bindings"]:
        binding["claim_statement_sha256"] = by_path[binding["claim_statement_path"]]
    return _validate_export_request(item, require_review=False)


def build_export(root: Path, request: Any) -> Path:
    require_enabled(root)
    if not _raw_archive_is_ignored(root):
        raise RepositoryFirstError("research/raw_runs/archive/ must remain ignored by default")
    item = _validate_export_request(request)
    export_id = item["export_id"]
    package_root = f"research/repository_first/exports/{export_id}"
    included: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, source in enumerate(item["included_files"]):
        path = source["path"]
        if path in seen:
            raise RepositoryFirstError("export request included paths must be unique")
        seen.add(path)
        if path.startswith(package_root + "/"):
            raise RepositoryFirstError("export request cannot include its own output")
        _require_bound_file(
            root, path, source["sha256"],
            "reviewed export source (changed files need prepare-export and fresh review)", source["bytes"]
        )
        included.append(dict(source))
    for checkpoint in item["source_checkpoint_paths"]:
        _existing_regular(root, checkpoint, "export source checkpoint")
    exported_files = {entry["path"]: entry["sha256"] for entry in included}
    for claim_id, _version, statement_path, statement_digest in (
        _claim_statement_bindings(
            item["claim_bindings"], "export request claim_bindings"
        )
    ):
        if exported_files.get(statement_path) != statement_digest:
            raise RepositoryFirstError(
                f"export request claim {claim_id} statement SHA-256 does not match the included file"
            )
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "export_package_manifest",
        "export_id": export_id,
        "created_at_utc": item["created_at_utc"],
        "package_root": package_root,
        "purpose": item["purpose"],
        "claim_ids": item["claim_ids"],
        "claim_bindings": item["claim_bindings"],
        "source_checkpoint_paths": item["source_checkpoint_paths"],
        "review": item["review"],
        "included_files": included,
        "exclusions": {
            "raw_archives": True,
            "credentials": True,
            "hidden_prompts": True,
            "chain_of_thought": True,
            "outbound_actions": True,
        },
        "no_outbound_action": True,
        "automatic_claim_promotion": False,
    }
    manifest["manifest_payload_sha256"] = sha256_bytes(canonical_json_bytes(manifest))
    _validate_export_manifest(manifest, root, True)
    output = f"{package_root}/manifest.json"
    return atomic_publish_noclobber(root, output, canonical_json_bytes(manifest), mode=0o444)


def build_observation(
    root: Path,
    observation_id: str,
    recorded_at_utc: str,
    period_start: str,
    period_end: str,
) -> Path:
    require_enabled(root)
    if not _raw_archive_is_ignored(root):
        raise RepositoryFirstError("research/raw_runs/archive/ must remain ignored by default")
    _identifier(observation_id, "observation_id")
    _timestamp(recorded_at_utc, "recorded_at_utc")
    _date(period_start, "period_start")
    _date(period_end, "period_end")
    if period_end < period_start:
        raise RepositoryFirstError("observation period end precedes start")
    records = scan_records(root)
    validate_cross_records(records)
    source_records: list[dict[str, str]] = []
    counts = {record_type: 0 for record_type in sorted(RECORD_TYPES)}
    axis_counts: dict[tuple[str, str], int] = {}
    denominator_unknown = {"vector": 0, "model": 0, "harness": 0}
    raw_checkpoint_links = 0
    raw_dossier_links = 0
    for record, path in records:
        digest, _ = _hash_file(root / path)
        source_records.append({"path": path, "sha256": digest, "record_type": record["record_type"]})
        counts[record["record_type"]] += 1
        if record["record_type"] == "claim_assessment":
            for axis in AXIS_STATUSES:
                key = (axis, record["axes"][axis]["status"])
                axis_counts[key] = axis_counts.get(key, 0) + 1
        elif record["record_type"] == "failure_family":
            for component in denominator_unknown:
                if record["denominator"][component]["status"] == "UNKNOWN":
                    denominator_unknown[component] += 1
        elif record["record_type"] == "raw_run_manifest":
            raw_checkpoint_links += 1
            raw_dossier_links += 1
    metrics: dict[str, int] = dict(counts)
    metrics["total_records"] = len(records)
    metrics["raw_checkpoint_links"] = raw_checkpoint_links
    metrics["raw_dossier_links"] = raw_dossier_links
    observation: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "effectiveness_observation",
        "observation_id": observation_id,
        "recorded_at_utc": recorded_at_utc,
        "period": {"start": period_start, "end": period_end},
        "collection_boundaries": {
            "mode": "EXPLICIT_PASSIVE_LOCAL_SNAPSHOT",
            "lab_local_only": True,
            "telemetry": False,
            "background_process": False,
            "fleet_scan": False,
        },
        "source_records": source_records,
        "source_set_sha256": sha256_bytes(canonical_json_bytes(source_records)),
        "metrics": metrics,
        "axis_status_counts": [
            {"axis": axis, "status": status_value, "count": count}
            for (axis, status_value), count in sorted(axis_counts.items())
        ],
        "denominator_unknown_counts": denominator_unknown,
        "limitations": [
            "Counts describe locally recorded workflow artifacts, not mathematical truth.",
            "The snapshot does not establish novelty, correctness, significance, or causal effectiveness.",
            "No telemetry, background process, network request, outbound action, or fleet scan was used.",
        ],
    }
    _validate_observation(observation, root, True)
    output = f"research/repository_first/observations/{observation_id}.json"
    return atomic_publish_noclobber(root, output, canonical_json_bytes(observation), mode=0o444)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="validate enabled local records")
    validate_parser.add_argument("--json", action="store_true")

    record_parser = subparsers.add_parser("record", help="publish one append-only dossier record")
    record_parser.add_argument("--input", required=True, help="lab-relative JSON path or -")
    record_parser.add_argument("--output", required=True, help="canonical dossier-relative output path")

    export_parser = subparsers.add_parser("build-export", help="build a reviewed local export manifest")
    export_parser.add_argument("--input", required=True, help="lab-relative JSON path or -")

    prepare_parser = subparsers.add_parser("prepare-export", help="bind files into a pending local review draft")
    prepare_parser.add_argument("--input", required=True, help="lab-relative selection JSON path or -")
    prepare_parser.add_argument("--output", required=True, help="new lab-relative draft JSON path")

    observe_parser = subparsers.add_parser("observe", help="write one explicit passive local summary")
    observe_parser.add_argument("--observation-id", required=True)
    observe_parser.add_argument("--recorded-at-utc", required=True)
    observe_parser.add_argument("--period-start", required=True)
    observe_parser.add_argument("--period-end", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "validate":
            report = validate_repository(ROOT)
            if arguments.json:
                print(json.dumps(report, ensure_ascii=False, sort_keys=True))
            else:
                print(
                    f"repository_first: {report['status']} "
                    f"({report['records_validated']} records, "
                    f"{report['exports_validated']} exports, "
                    f"{report['observations_validated']} observations)"
                )
        elif arguments.command == "record":
            path = record_packet(ROOT, _input_json(ROOT, arguments.input), arguments.output)
            print(path.relative_to(ROOT).as_posix())
        elif arguments.command == "prepare-export":
            draft = prepare_export(ROOT, _input_json(ROOT, arguments.input))
            output = _relpath(arguments.output, "export review draft output")
            if output in {entry["path"] for entry in draft["included_files"]}:
                raise RepositoryFirstError("export review draft cannot overwrite a selected source")
            path = atomic_publish_noclobber(ROOT, output, canonical_json_bytes(draft), mode=0o644)
            print(path.relative_to(ROOT).as_posix())
        elif arguments.command == "build-export":
            path = build_export(ROOT, _input_json(ROOT, arguments.input))
            print(path.relative_to(ROOT).as_posix())
        elif arguments.command == "observe":
            path = build_observation(
                ROOT,
                arguments.observation_id,
                arguments.recorded_at_utc,
                arguments.period_start,
                arguments.period_end,
            )
            print(path.relative_to(ROOT).as_posix())
        else:  # pragma: no cover - argparse owns this branch
            parser.error("unsupported command")
    except RepositoryFirstError as exc:
        print(f"repository_first: ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
