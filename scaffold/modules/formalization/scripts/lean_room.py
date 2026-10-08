#!/usr/bin/env python3
"""Fail-closed state and shared primitives for the laboratory Lean Room."""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import errno
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


STATE_RELATIVE = Path("research/formalization/lean_room_state.json")
EVENTS_RELATIVE = Path("research/formalization/lean_room_events.jsonl")
LOCK_RELATIVE = Path("research/formalization/.lean_room_state.lock")
STATE_SCHEMA_VERSION = 1
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_DISABLED = 3
EXIT_STATE = 4
EXIT_VALIDATION = 5
EXIT_BUILD = 6
EXIT_EVIDENCE = 7
IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
LEAN_NAME_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*\Z"
)
PINNED_TOOLCHAIN_RE = re.compile(
    r"(?:leanprover/lean4:)?v\d+\.\d+\.\d+(?:-(?:rc|beta)\d+)?\Z"
)
LEAN_ROOM_SANDBOX_PROFILE_ID = "macos-seatbelt-deny-default-v1"
LEAN_ROOM_BUILD_COMMAND_SCHEMA = (
    "<pinned-lake>",
    "--no-cache",
    "build",
    "LeanRoomCase",
)
LEAN_ROOM_AUDIT_COMMAND_SCHEMA = (
    "<pinned-lake>",
    "env",
    "<pinned-lean>",
    "<generated-audit-file>",
)
# Lean Room v1 is intentionally narrow.  A contract may choose any subset of
# this list, but it cannot extend the trusted boundary by writing an arbitrary
# axiom name into a locally editable JSON file.
LEAN_ROOM_V1_ALLOWED_AXIOMS = frozenset(
    {
        "propext",
        "Classical.choice",
        "Quot.sound",
    }
)


class LeanRoomError(RuntimeError):
    """Base exception carrying a stable process exit code."""

    exit_code = EXIT_STATE


class RoomDisabledError(LeanRoomError):
    exit_code = EXIT_DISABLED


class ValidationError(LeanRoomError):
    exit_code = EXIT_VALIDATION


class EvidenceError(LeanRoomError):
    exit_code = EXIT_EVIDENCE


@dataclass(frozen=True)
class RoomStatus:
    effective_state: str
    valid: bool
    configured_state: str | None
    sequence: int
    diagnostic: str
    artifact: Path
    artifact_sha256: str | None
    data: Mapping[str, Any] | None

    @property
    def enabled(self) -> bool:
        return self.valid and self.effective_state == "enabled"

    def as_dict(self, root: Path | None = None) -> dict[str, Any]:
        artifact = self.artifact
        if root is not None:
            try:
                artifact_text = artifact.relative_to(root).as_posix()
            except ValueError:
                artifact_text = str(artifact)
        else:
            artifact_text = str(artifact)
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "effective_state": self.effective_state,
            "configured_state": self.configured_state,
            "valid": self.valid,
            "sequence": self.sequence,
            "diagnostic": self.diagnostic,
            "artifact": artifact_text,
            "artifact_sha256": self.artifact_sha256,
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def discover_root(explicit: str | Path | None = None) -> Path:
    """Find the laboratory root without relying on the caller's cwd."""
    if explicit is not None:
        candidate = Path(explicit).expanduser().resolve()
        if not candidate.is_dir():
            raise ValidationError(f"Lean Room root is not a directory: {candidate}")
        return candidate
    starts = [Path(__file__).resolve().parent, Path.cwd().resolve()]
    seen: set[Path] = set()
    for start in starts:
        for candidate in (start, *start.parents):
            if candidate in seen:
                continue
            seen.add(candidate)
            if (candidate / "AGENTS.md").is_file() and (
                candidate / "LAB_PROFILE.json"
            ).is_file():
                return candidate
    raise ValidationError(
        "Cannot discover laboratory root (expected AGENTS.md and LAB_PROFILE.json)"
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValidationError(f"Expected a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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


def atomic_write_bytes(path: Path, content: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValidationError(f"Refusing to replace symlink: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        try:
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except OSError:
            pass
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, pretty_json_bytes(value))


def _ensure_state_directory(root: Path) -> Path:
    current = root
    for part in STATE_RELATIVE.parent.parts:
        current = current / part
        if current.is_symlink():
            raise ValidationError(
                f"Lean Room state directory component is a symlink: {current}"
            )
        try:
            current.mkdir(mode=0o755)
        except FileExistsError:
            pass
        if current.is_symlink() or not current.is_dir():
            raise ValidationError(f"Unsafe Lean Room state directory: {current}")
    return current


def _state_paths_are_safe(root: Path) -> tuple[bool, str | None]:
    try:
        reject_symlink_components(root / STATE_RELATIVE.parent, root)
    except ValidationError as exc:
        return False, str(exc)
    directory = root / STATE_RELATIVE.parent
    if directory.exists() and not directory.is_dir():
        return False, f"Lean Room state parent is not a directory: {directory}"
    for relative in (STATE_RELATIVE, EVENTS_RELATIVE, LOCK_RELATIVE):
        path = root / relative
        if path.is_symlink():
            return False, f"Lean Room control artifact is a symlink: {path}"
        if path.exists() and not path.is_file():
            return False, f"Lean Room control artifact is not a regular file: {path}"
    return True, None


@contextlib.contextmanager
def state_lock(root: Path) -> Iterator[None]:
    _ensure_state_directory(root)
    lock_path = root / LOCK_RELATIVE
    if lock_path.is_symlink():
        raise ValidationError(f"Lean Room lock path is a symlink: {lock_path}")
    try:
        descriptor = os.open(
            lock_path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise ValidationError(f"Cannot safely open Lean Room state lock: {exc}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValidationError("Lean Room state lock is not a regular file")
        try:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except ImportError:
            pass
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
        except ImportError:
            pass
        os.close(descriptor)


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def read_room_status(root: Path) -> RoomStatus:
    path = root / STATE_RELATIVE
    paths_safe, path_error = _state_paths_are_safe(root)
    if not paths_safe:
        return RoomStatus(
            "disabled",
            False,
            None,
            0,
            f"unsafe state storage; fail-closed: {path_error}",
            path,
            None,
            None,
        )
    if not path.is_file():
        return RoomStatus(
            "disabled",
            False,
            None,
            0,
            "state artifact is missing; fail-closed",
            path,
            None,
            None,
        )
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return RoomStatus(
            "disabled",
            False,
            None,
            0,
            f"state artifact is malformed; fail-closed: {exc}",
            path,
            None,
            None,
        )
    errors: list[str] = []
    if not isinstance(data, dict):
        errors.append("top level is not an object")
        data = {}
    if data.get("schema_version") != STATE_SCHEMA_VERSION:
        errors.append("unsupported schema_version")
    configured = data.get("state")
    if configured not in {"enabled", "disabled"}:
        errors.append("state is not enabled or disabled")
    sequence = data.get("sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        errors.append("sequence is not a nonnegative integer")
        sequence = 0
    if not _valid_timestamp(data.get("updated_at_utc")):
        errors.append("updated_at_utc is not an RFC3339 UTC timestamp")
    for key in ("actor", "reason"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            errors.append(f"{key} is empty")
    digest = sha256_bytes(raw)
    if errors:
        return RoomStatus(
            "disabled",
            False,
            configured if isinstance(configured, str) else None,
            sequence,
            "state artifact is invalid; fail-closed: " + "; ".join(errors),
            path,
            digest,
            data,
        )
    return RoomStatus(
        configured,
        True,
        configured,
        sequence,
        f"Lean Room is {configured}",
        path,
        digest,
        data,
    )


def require_room_enabled(root: Path, action: str) -> RoomStatus:
    status = read_room_status(root)
    if not status.enabled:
        raise RoomDisabledError(
            f"Lean Room disabled: refusing {action}. {status.diagnostic}"
        )
    return status


def require_same_room_binding(
    root: Path, expected: RoomStatus, action: str
) -> RoomStatus:
    current = read_room_status(root)
    if (
        not current.enabled
        or expected.artifact_sha256 is None
        or current.sequence != expected.sequence
        or current.artifact_sha256 != expected.artifact_sha256
    ):
        raise RoomDisabledError(
            f"Lean Room state changed since {action} began; refusing stale publication"
        )
    return current


def _append_event(root: Path, path: Path, event: Mapping[str, Any]) -> None:
    _ensure_state_directory(root)
    reject_symlink_components(path, root)
    if path.is_symlink():
        raise ValidationError(f"Lean Room event log is a symlink: {path}")
    payload = canonical_json_bytes(event)
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_APPEND
            | os.O_CREAT
            | getattr(os, "O_NOFOLLOW", 0),
            0o644,
        )
    except OSError as exc:
        raise ValidationError(f"Cannot safely open Lean Room event log: {exc}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValidationError("Lean Room event log is not a regular file")
        with os.fdopen(descriptor, "ab", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def transition_room(
    root: Path, requested_state: str, actor: str, reason: str
) -> tuple[RoomStatus, bool]:
    if requested_state not in {"enabled", "disabled"}:
        raise ValidationError(f"Invalid Lean Room state: {requested_state}")
    actor = actor.strip()
    reason = reason.strip()
    if not actor or not reason:
        raise ValidationError("Lean Room transition requires nonempty actor and reason")
    state_path = root / STATE_RELATIVE
    event_path = root / EVENTS_RELATIVE
    _ensure_state_directory(root)
    reject_symlink_components(state_path, root)
    reject_symlink_components(event_path, root)
    if state_path.is_symlink() or event_path.is_symlink():
        raise ValidationError("Refusing Lean Room transition through a symlink")
    with state_lock(root):
        previous = read_room_status(root)
        changed = not previous.valid or previous.effective_state != requested_state
        sequence = previous.sequence + 1 if changed else previous.sequence
        timestamp = utc_now()
        new_data = {
            "schema_version": STATE_SCHEMA_VERSION,
            "state": requested_state,
            "sequence": sequence,
            "updated_at_utc": timestamp,
            "actor": actor,
            "reason": reason,
        }
        event = {
            "schema_version": STATE_SCHEMA_VERSION,
            "record_type": "lean_room_state_event",
            "event_at_utc": timestamp,
            "actor": actor,
            "reason": reason,
            "previous_effective_state": previous.effective_state,
            "previous_state_valid": previous.valid,
            "requested_state": requested_state,
            "resulting_state": requested_state,
            "changed": changed,
            "state_sequence": sequence,
        }
        # On a real transition the durable state is authoritative. An idempotent
        # request does not rewrite it, but is still retained in the audit log.
        if changed:
            atomic_write_json(state_path, new_data)
        _append_event(root, event_path, event)
        result = read_room_status(root)
        if not result.valid or result.effective_state != requested_state:
            raise LeanRoomError("Lean Room state transition did not persist safely")
        return result, changed


def validate_identifier(value: str, label: str) -> str:
    if not IDENTIFIER_RE.fullmatch(value) or value in {".", ".."} or ".." in value:
        raise ValidationError(
            f"Unsafe {label}: {value!r}; use 1-128 ASCII letters, digits, dot, dash, underscore"
        )
    return value


def validate_lean_name(value: str, label: str = "Lean declaration name") -> str:
    if not LEAN_NAME_RE.fullmatch(value):
        raise ValidationError(f"Unsafe or unsupported {label}: {value!r}")
    return value


def declaration_audit_bytes(declaration: str, exact_type: str) -> bytes:
    """Canonical generated source used for the exact-type and axiom audit.

    A plain ``example : expected := @decl`` is not an exact-type check: Lean's
    elaborator may silently insert a user-defined coercion from the declaration
    type to ``expected``.  The generated command compares the raw constant type
    with the separately elaborated expected type using kernel definitional
    equality, before constructing a private wrapper whose transitive axioms are
    also printed.
    """
    declaration = validate_lean_name(declaration)
    if not isinstance(exact_type, str) or not exact_type.strip():
        raise ValidationError("exact Lean type must be a nonempty string")
    if (
        any(token in exact_type for token in ("\n", "\r", ";", "#", "--", "/-", "-/", ":="))
        or len(exact_type) > 16000
    ):
        raise ValidationError("exact Lean type contains audit-source injection syntax")
    return (
        "import LeanRoomCase\n"
        "import Lean.Elab.Command\n\n"
        "set_option autoImplicit false\n\n"
        "namespace LeanRoomAuditHarness\n\n"
        "syntax (name := leanRoomExactTypeCmd) "
        '"#lean_room_exact_type " ident " : " term : command\n\n'
        "@[command_elab leanRoomExactTypeCmd] meta def elabLeanRoomExactType : "
        "Lean.Elab.Command.CommandElab\n"
        "  | `(#lean_room_exact_type $decl:ident : $expected:term) =>\n"
        "      Lean.Elab.Command.liftTermElabM do\n"
        "        let declName ← Lean.resolveGlobalConstNoOverload decl\n"
        "        let actualType ← Lean.Meta.inferType "
        "(← Lean.Meta.mkConstWithFreshMVarLevels declName)\n"
        "        let expectedType ← Lean.Elab.Term.elabType expected\n"
        "        Lean.Elab.Term.synthesizeSyntheticMVarsNoPostponing\n"
        "        unless ← Lean.Meta.isDefEq actualType expectedType do\n"
        '          Lean.throwError "Lean Room exact-type mismatch: kernel definitional equality failed"\n'
        "  | _ => Lean.Elab.throwUnsupportedSyntax\n\n"
        "end LeanRoomAuditHarness\n\n"
        f"#lean_room_exact_type {declaration} : ({exact_type})\n\n"
        f"private theorem leanRoomGeneratedExactTarget : ({exact_type}) := @{declaration}\n\n"
        f"#print {declaration}\n"
        f"#print axioms {declaration}\n"
        "#print axioms leanRoomGeneratedExactTarget\n"
    ).encode("utf-8")


def validate_toolchain(value: str) -> str:
    value = value.strip()
    if not PINNED_TOOLCHAIN_RE.fullmatch(value):
        raise ValidationError(
            "Lean toolchain must be an exact pin such as leanprover/lean4:v4.20.0"
        )
    return value


def ensure_within(path: Path, parent: Path, label: str) -> Path:
    resolved_parent = parent.resolve()
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(resolved_parent)
    except ValueError as exc:
        raise ValidationError(f"{label} escapes {resolved_parent}: {path}") from exc
    return resolved


def reject_symlink_components(path: Path, stop: Path) -> None:
    absolute_stop = Path(os.path.abspath(stop))
    absolute_path = Path(os.path.abspath(path))
    try:
        relative = absolute_path.relative_to(absolute_stop)
    except ValueError as exc:
        raise ValidationError(f"Path is outside Lean Room root: {path}") from exc
    current = absolute_stop
    if current.is_symlink():
        raise ValidationError(f"Symlink is not allowed in Lean Room path: {current}")
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValidationError(f"Symlink is not allowed in Lean Room path: {current}")


def case_path(root: Path, problem_id: str, case_id: str, must_exist: bool = True) -> Path:
    problem_id = validate_identifier(problem_id, "problem id")
    case_id = validate_identifier(case_id, "case id")
    active = root / "problems/active"
    problem = active / problem_id
    ensure_within(problem, active, "problem path")
    reject_symlink_components(problem, root)
    if not problem.is_dir():
        raise ValidationError(f"Active problem dossier does not exist: {problem}")
    result = problem / "formalization/cases" / case_id
    ensure_within(result, problem, "Lean case path")
    reject_symlink_components(result, root)
    if must_exist and not result.is_dir():
        raise ValidationError(f"Lean case does not exist: {result}")
    return result


def safe_relative_file(root: Path, relative: str, label: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValidationError(f"Unsafe {label}: {relative!r}")
    # Keep the lexical path for the symlink walk.  Using ensure_within()'s
    # resolved return value here would erase evidence that an ancestor was a
    # symlink pointing to another location inside the root.
    target = root / candidate
    ensure_within(target, root, label)
    reject_symlink_components(target, root)
    if target.is_symlink() or not target.is_file():
        raise ValidationError(f"Missing regular {label}: {target}")
    return target


def safe_append_container(case: Path, relative: str) -> Path:
    """Create/validate an append-only case container without following symlinks."""
    rel = Path(relative)
    if rel.is_absolute() or not rel.parts or any(part in {"", ".", ".."} for part in rel.parts):
        raise ValidationError(f"Unsafe append-only container path: {relative!r}")
    target = ensure_within(case / rel, case, "append-only container")
    current = case
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise ValidationError(f"Symlink append-only container is forbidden: {current}")
        try:
            current.mkdir(mode=0o755)
        except FileExistsError:
            pass
        if current.is_symlink() or not current.is_dir():
            raise ValidationError(f"Unsafe append-only container: {current}")
    return target


def scan_regular_tree(base: Path, exclude_top: Sequence[str] = ()) -> list[Path]:
    if base.is_symlink() or not base.is_dir():
        raise ValidationError(f"Expected regular directory: {base}")
    excluded = set(exclude_top)
    result: list[Path] = []
    for path in sorted(base.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(base)
        if ".git" in relative.parts:
            raise ValidationError(f"Embedded .git metadata is forbidden in Lean project: {path}")
        if relative.parts and relative.parts[0] in excluded:
            continue
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValidationError(f"Symlink in Lean project: {path}")
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValidationError(f"Special file in Lean project: {path}")
        result.append(path)
    return result


def project_tree_inventory(project: Path) -> tuple[list[dict[str, Any]], str]:
    files = scan_regular_tree(project, exclude_top=(".lake",))
    inventory: list[dict[str, Any]] = []
    tree = hashlib.sha256()
    tree.update(b"lean-room-project-tree-v1\0")
    for path in files:
        relative = path.relative_to(project).as_posix()
        content = path.read_bytes()
        file_digest = sha256_bytes(content)
        inventory.append(
            {"path": relative, "size": len(content), "sha256": file_digest}
        )
        encoded_path = relative.encode("utf-8")
        tree.update(len(encoded_path).to_bytes(8, "big"))
        tree.update(encoded_path)
        tree.update(len(content).to_bytes(8, "big"))
        tree.update(content)
    return inventory, tree.hexdigest()


def publish_directory_noreplace(stage: Path, target: Path) -> None:
    """Atomically publish a directory while refusing every existing target."""
    if os.name == "nt":
        try:
            os.rename(stage, target)
        except FileExistsError as exc:
            raise ValidationError(f"Lean case already exists: {target}") from exc
        return
    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(stage)
    target_bytes = os.fsencode(target)
    if sys.platform == "darwin":
        try:
            rename_noreplace = libc.renamex_np
        except AttributeError as exc:
            raise ValidationError("Atomic no-clobber publication is unavailable") from exc
        rename_noreplace.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        rename_noreplace.restype = ctypes.c_int
        result = rename_noreplace(source_bytes, target_bytes, 0x00000004)
    elif sys.platform.startswith("linux"):
        try:
            rename_noreplace = libc.renameat2
        except AttributeError as exc:
            raise ValidationError("Atomic no-clobber publication is unavailable") from exc
        rename_noreplace.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename_noreplace.restype = ctypes.c_int
        result = rename_noreplace(-100, source_bytes, -100, target_bytes, 1)
    else:
        raise ValidationError(
            f"Atomic no-clobber publication is unsupported on {sys.platform}"
        )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise ValidationError(f"Lean case already exists: {target}")
    raise ValidationError(
        f"Atomic Lean case publication failed: {os.strerror(error_number)}"
    )


def normalized_contract_sha256(contract: Mapping[str, Any]) -> str:
    """Hash a contract with its self-binding field normalized to null."""
    normalized = json.loads(json.dumps(contract, ensure_ascii=False))
    freeze = normalized.get("freeze")
    if not isinstance(freeze, dict):
        raise ValidationError("Contract freeze section is missing")
    freeze["frozen_contract_sha256"] = None
    return sha256_bytes(canonical_json_bytes(normalized))


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValidationError(f"Missing regular {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Cannot parse {label} as JSON-compatible YAML: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must contain a JSON object")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect or atomically change the fail-closed Lean Room state."
    )
    parser.add_argument("--root", help="laboratory root (normally auto-discovered)")
    subparsers = parser.add_subparsers(dest="command", required=True)
    status = subparsers.add_parser("status", help="show effective state")
    status.add_argument("--json", action="store_true", help="machine-readable output")
    for command in ("enable", "disable"):
        transition = subparsers.add_parser(command, help=f"atomically {command} the room")
        transition.add_argument("--actor", default="user", help="audit actor identifier")
        transition.add_argument(
            "--reason",
            default=(
                "Explicit one-sentence Lean Room activation"
                if command == "enable"
                else "Explicit one-sentence Lean Room shutdown"
            ),
            help="nonempty audit reason",
        )
        transition.add_argument("--json", action="store_true", help="machine-readable output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        root = discover_root(args.root)
        if args.command == "status":
            status = read_room_status(root)
            if args.json:
                print(json.dumps(status.as_dict(root), ensure_ascii=False, sort_keys=True))
            else:
                print(status.diagnostic)
                print(f"State artifact: {status.artifact}")
            return EXIT_OK if status.enabled else EXIT_DISABLED
        requested = "enabled" if args.command == "enable" else "disabled"
        status, changed = transition_room(root, requested, args.actor, args.reason)
        payload = status.as_dict(root)
        payload["changed"] = changed
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            action = "changed" if changed else "already set (audit event appended)"
            print(f"Lean Room {requested}: {action}")
            print(f"Sequence: {status.sequence}")
        return EXIT_OK
    except LeanRoomError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
