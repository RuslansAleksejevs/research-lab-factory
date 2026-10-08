#!/usr/bin/env python3
"""Build and trust-check a frozen Lean case in an offline disposable sandbox."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import pwd
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from lean_room import (
    EXIT_BUILD,
    EXIT_DISABLED,
    EXIT_OK,
    EXIT_VALIDATION,
    LEAN_ROOM_AUDIT_COMMAND_SCHEMA,
    LEAN_ROOM_BUILD_COMMAND_SCHEMA,
    LEAN_ROOM_SANDBOX_PROFILE_ID,
    LEAN_ROOM_V1_ALLOWED_AXIOMS,
    LeanRoomError,
    RoomDisabledError,
    RoomStatus,
    ValidationError,
    atomic_write_bytes,
    atomic_write_json,
    case_path,
    declaration_audit_bytes,
    discover_root,
    project_tree_inventory,
    publish_directory_noreplace,
    read_room_status,
    require_room_enabled,
    safe_append_container,
    safe_relative_file,
    scan_regular_tree,
    reject_symlink_components,
    sha256_bytes,
    sha256_file,
    pretty_json_bytes,
    state_lock,
    utc_now,
)
from validate_lean_case import validate_case


AXIOM_BLOCK_RE = re.compile(r"depends on axioms:\s*\[([^\]]*)\]", re.DOTALL)


class BuildFailure(LeanRoomError):
    exit_code = EXIT_BUILD


@dataclass(frozen=True)
class StateBinding:
    sequence: int
    artifact_sha256: str


@dataclass(frozen=True)
class StateControl:
    role: str
    root: Path
    binding: StateBinding
    artifact: Path

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "state_sequence": self.binding.sequence,
            "state_artifact": self.artifact.relative_to(self.root).as_posix(),
            "state_artifact_sha256": self.binding.artifact_sha256,
        }


@dataclass(frozen=True)
class StateGuard:
    controls: tuple[StateControl, ...]

    def matches(self) -> bool:
        return all(
            state_binding_matches(control.root, control.binding)
            for control in self.controls
        )


@dataclass(frozen=True)
class BoundInput:
    label: str
    path: Path
    artifact: str
    sha256: str
    size: int

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "artifact": self.artifact,
            "sha256": self.sha256,
            "size": self.size,
        }


@dataclass(frozen=True)
class InputSnapshot:
    contract: dict[str, Any]
    bound_files: tuple[BoundInput, ...]
    source_inventory: tuple[dict[str, Any], ...]
    source_tree_sha256: str

    @property
    def contract_binding(self) -> BoundInput:
        return next(item for item in self.bound_files if item.label == "contract")


@dataclass
class CommandResult:
    logical_argv: list[str]
    wrapped_argv: list[str]
    started_at: str
    finished_at: str
    exit_code: int
    output: bytes
    aborted_room_state: bool = False
    timed_out: bool = False

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "logical_argv": self.logical_argv,
            "wrapped_argv": self.wrapped_argv,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "aborted_room_state": self.aborted_room_state,
            "timed_out": self.timed_out,
            "output_sha256": sha256_bytes(self.output),
        }


def _binding(status: RoomStatus) -> StateBinding:
    if not status.enabled or status.artifact_sha256 is None:
        raise RoomDisabledError(f"Lean Room disabled: {status.diagnostic}")
    return StateBinding(status.sequence, status.artifact_sha256)


def state_binding_matches(root: Path, binding: StateBinding) -> bool:
    current = read_room_status(root)
    return (
        current.enabled
        and current.sequence == binding.sequence
        and current.artifact_sha256 == binding.artifact_sha256
    )


def _state_guard(root: Path, initial_status: RoomStatus) -> StateGuard:
    controls = [
        StateControl("case_root", root, _binding(initial_status), initial_status.artifact)
    ]
    control_root_value = os.environ.get("LEAN_ROOM_CONTROL_ROOT")
    if control_root_value:
        control_root = discover_root(control_root_value)
        if control_root != root:
            status = require_room_enabled(
                control_root, "Lean verification canonical control"
            )
            controls.append(
                StateControl(
                    "canonical_control_root",
                    control_root,
                    _binding(status),
                    status.artifact,
                )
            )
    return StateGuard(tuple(controls))


@contextlib.contextmanager
def _locked_state_guard(guard: StateGuard):
    """Lock every control root in deterministic order for final publication."""
    with contextlib.ExitStack() as stack:
        roots = sorted({control.root for control in guard.controls}, key=str)
        for root in roots:
            stack.enter_context(state_lock(root))
        yield


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        process.terminate()
    try:
        process.wait(timeout=1.0)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        process.kill()
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        pass


def run_guarded(
    guard: StateGuard,
    logical_argv: list[str],
    wrapped_argv: list[str],
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
) -> CommandResult:
    if not guard.matches():
        return CommandResult(
            logical_argv,
            wrapped_argv,
            utc_now(),
            utc_now(),
            EXIT_DISABLED,
            b"Lean Room state changed before command start.\n",
            aborted_room_state=True,
        )
    started_at = utc_now()
    start = time.monotonic()
    try:
        process = subprocess.Popen(
            wrapped_argv,
            cwd=str(cwd),
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            start_new_session=True,
        )
    except OSError as exc:
        return CommandResult(
            logical_argv,
            wrapped_argv,
            started_at,
            utc_now(),
            127,
            f"Cannot start command: {exc}\n".encode("utf-8"),
        )
    aborted = False
    timed_out = False
    output = b""
    while True:
        try:
            output, _ = process.communicate(timeout=0.20)
            break
        except subprocess.TimeoutExpired:
            if not guard.matches():
                aborted = True
                _terminate_process_group(process)
                output, _ = process.communicate()
                break
            if time.monotonic() - start > timeout_seconds:
                timed_out = True
                _terminate_process_group(process)
                output, _ = process.communicate()
                break
    if aborted:
        output += b"\nLean Room state changed; process group terminated.\n"
        exit_code = EXIT_DISABLED
    elif timed_out:
        output += b"\nLean Room command timed out; process group terminated.\n"
        exit_code = 124
    else:
        exit_code = int(process.returncode or 0)
    return CommandResult(
        logical_argv,
        wrapped_argv,
        started_at,
        utc_now(),
        exit_code,
        output,
        aborted_room_state=aborted,
        timed_out=timed_out,
    )


def _base_environment(
    build_root: Path,
    toolchain: str,
    toolchain_root: Path,
    lean_path: Path,
    lake_path: Path,
    elan_home: Path,
) -> dict[str, str]:
    account = pwd.getpwuid(os.getuid())
    isolated_home = build_root / "home"
    temporary = build_root / "tmp"
    isolated_home.mkdir()
    temporary.mkdir()
    return {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(isolated_home),
        "USER": account.pw_name,
        "LOGNAME": account.pw_name,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TMPDIR": str(temporary),
        "ELAN_HOME": str(elan_home),
        "ELAN_TOOLCHAIN": toolchain,
        "ELAN_AUTO_INSTALL": "0",
        "ELAN_NO_UPDATE_CHECK": "1",
        "LEAN_SYSROOT": str(toolchain_root),
        "LEAN": str(lean_path),
        "LAKE": str(lake_path),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ALLOW_PROTOCOL": "file",
        "NO_PROXY": "",
    }


def _escape_sandbox_literal(value: Path | str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def sandbox_profile(
    build_root: Path,
    toolchain_root: Path,
    extra_read_paths: Sequence[Path] = (),
) -> str:
    read_paths = [
        "/System",
        "/usr",
        "/bin",
        "/sbin",
        "/Library/Apple",
        "/Library/Developer",
        "/private/etc",
        "/dev",
        str(toolchain_root),
        str(build_root),
        str(build_root.resolve()),
        *(str(path) for path in extra_read_paths),
    ]
    read_rules = " ".join(
        f'(subpath "{_escape_sandbox_literal(path)}")' for path in read_paths
    )
    metadata_paths: set[str] = set()
    for value in read_paths:
        candidate = Path(value)
        for ancestor in (candidate, *candidate.parents):
            rendered = str(ancestor)
            if rendered != "/":
                metadata_paths.add(rendered)
    metadata_rules = " ".join(
        f'(literal "{_escape_sandbox_literal(path)}")'
        for path in sorted(metadata_paths)
    )
    executable_rules = " ".join(
        f'(subpath "{_escape_sandbox_literal(path)}")'
        for path in [str(toolchain_root), str(build_root), str(build_root.resolve()), *(str(path) for path in extra_read_paths)]
    )
    writable = _escape_sandbox_literal(build_root)
    writable_resolved = _escape_sandbox_literal(build_root.resolve())
    return (
        "(version 1)\n"
        "(deny default)\n"
        '(import "system.sb")\n'
        "(allow process*)\n"
        "(allow sysctl-read)\n"
        f"(allow file-read-metadata file-test-existence {metadata_rules})\n"
        f"(allow file-read* file-test-existence {read_rules})\n"
        f"(allow file-map-executable {executable_rules})\n"
        f'(allow file-write* (subpath "{writable}") (subpath "{writable_resolved}") (literal "/dev/null") (literal "/dev/tty"))\n'
        "(deny network*)\n"
    )


def _wrapped(profile: str, logical: list[str]) -> list[str]:
    sandbox = Path("/usr/bin/sandbox-exec")
    if sys.platform != "darwin" or sandbox.is_symlink() or not sandbox.is_file():
        raise ValidationError(
            "no enforceable Lean Room network/filesystem isolation backend is available"
        )
    return [str(sandbox), "-p", profile, *logical]


def _copy_frozen_project(source: Path, target: Path) -> None:
    def ignore(directory: str, names: list[str]) -> set[str]:
        directory_path = Path(directory)
        if directory_path == source:
            return {name for name in names if name in {".lake", ".git"}}
        return {name for name in names if name == ".git"}

    shutil.copytree(source, target, symlinks=False, ignore=ignore)
def _dependency_preflight(project: Path) -> None:
    manifest_path = project / "lake-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    packages = manifest.get("packages", [])
    if packages:
        raise ValidationError(
            "dependency-bearing cases are not certifiable by Lean Room v1"
        )
    packages_dir = manifest.get("packagesDir", ".lake/packages")
    if Path(packages_dir).is_absolute() or ".." in Path(packages_dir).parts:
        raise ValidationError("Lake packagesDir escapes frozen project")
    for package in packages:
        if not isinstance(package, dict):
            raise ValidationError("invalid Lake package manifest entry")
        if package.get("type") == "path" or "path" in package:
            raise ValidationError("path dependencies are forbidden")
        name = package.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise ValidationError("unsafe Lake package name")
        local = project / packages_dir / name
        if local.is_symlink() or not local.is_dir():
            raise ValidationError(f"offline dependency is not materialized locally: {name}")


def _bound_input(label: str, path: Path, artifact: str) -> BoundInput:
    if path.is_symlink() or not path.is_file():
        raise ValidationError(f"missing regular verifier input: {artifact}")
    return BoundInput(
        label=label,
        path=path,
        artifact=artifact,
        sha256=sha256_file(path),
        size=path.stat().st_size,
    )


def _capture_inputs(
    root: Path,
    case: Path,
    validated_contract: Mapping[str, Any],
    source_inventory: list[dict[str, Any]],
    source_digest: str,
) -> InputSnapshot:
    contract_path = case / "formalization_contract.yaml"
    contract_binding = _bound_input("contract", contract_path, "formalization_contract.yaml")
    try:
        captured_contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"contract changed during verifier input capture: {exc}") from exc
    if captured_contract != validated_contract:
        raise ValidationError("contract changed between validation and verifier input capture")

    bound: list[BoundInput] = [contract_binding]
    for label, key in (
        ("informal_target", "target_binding"),
        ("proof_obligations", "obligation_binding"),
    ):
        binding = captured_contract.get(key)
        if not isinstance(binding, dict):
            raise ValidationError(f"missing {key} during verifier input capture")
        artifact = binding.get("artifact")
        expected = binding.get("artifact_sha256")
        if not isinstance(artifact, str) or not isinstance(expected, str):
            raise ValidationError(f"incomplete {key} during verifier input capture")
        path = safe_relative_file(root, artifact, label)
        captured = _bound_input(label, path, artifact)
        if captured.sha256 != expected:
            raise ValidationError(f"{label} changed during verifier input capture")
        bound.append(captured)

    freeze = captured_contract.get("freeze")
    if not isinstance(freeze, dict):
        raise ValidationError("missing freeze bindings during verifier input capture")
    for gate, field in (("LR0", "lr0_snapshot_id"), ("LR1", "lr1_snapshot_id")):
        snapshot_id = freeze.get(field)
        if not isinstance(snapshot_id, str):
            raise ValidationError(f"missing {gate} snapshot id during verifier input capture")
        directory = case / "evidence/freezes" / snapshot_id
        reject_symlink_components(directory, case)
        for path in scan_regular_tree(directory):
            relative = path.relative_to(case).as_posix()
            bound.append(_bound_input(f"freeze:{gate}", path, relative))

    return InputSnapshot(
        contract=captured_contract,
        bound_files=tuple(bound),
        source_inventory=tuple(source_inventory),
        source_tree_sha256=source_digest,
    )


def _input_mutations(snapshot: InputSnapshot, source_project: Path) -> list[str]:
    mutations: list[str] = []
    for item in snapshot.bound_files:
        try:
            current_sha256 = sha256_file(item.path)
            current_size = item.path.stat().st_size
        except (OSError, ValidationError):
            mutations.append(f"{item.label}:{item.artifact}:missing-or-unsafe")
            continue
        if current_sha256 != item.sha256 or current_size != item.size:
            mutations.append(f"{item.label}:{item.artifact}:changed")
    try:
        current_inventory, current_digest = project_tree_inventory(source_project)
    except ValidationError:
        mutations.append("project:unsafe")
    else:
        if current_digest != snapshot.source_tree_sha256:
            mutations.append("project:tree-digest-changed")
        if current_inventory != list(snapshot.source_inventory):
            mutations.append("project:inventory-changed")
    return mutations


def _binary_mutations(bindings: Mapping[str, Mapping[str, Any]]) -> list[str]:
    mutations: list[str] = []
    for name, binding in bindings.items():
        artifact = binding.get("artifact")
        if not isinstance(artifact, str):
            mutations.append(f"binary:{name}:binding-missing")
            continue
        path = Path(artifact)
        try:
            current_sha256 = sha256_file(path)
            current_size = path.stat().st_size
        except (OSError, ValidationError):
            mutations.append(f"binary:{name}:missing-or-unsafe")
            continue
        if current_sha256 != binding.get("sha256") or current_size != binding.get("size"):
            mutations.append(f"binary:{name}:changed")
    return mutations


def _axioms_from_output(output: bytes) -> set[str]:
    text = output.decode("utf-8", errors="replace")
    result: set[str] = set()
    for match in AXIOM_BLOCK_RE.finditer(text):
        for item in match.group(1).split(","):
            item = item.strip()
            if item:
                result.add(item)
    if "does not depend on any axioms" in text:
        return result
    if not AXIOM_BLOCK_RE.search(text):
        raise ValidationError("could not parse #print axioms output")
    return result


def _build_artifacts(build_project: Path) -> list[dict[str, Any]]:
    build = build_project / ".lake/build"
    if not build.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for path in sorted(build.rglob("*")):
        if path.is_file() and not path.is_symlink() and path.suffix in {".olean", ".ilean"}:
            result.append(
                {
                    "path": path.relative_to(build_project).as_posix(),
                    "sha256": sha256_file(path),
                    "size": path.stat().st_size,
                }
            )
    return result


def _load_build_template(root: Path) -> dict[str, Any]:
    path = root / "templates/lean_room/build_manifest.yaml"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot load build manifest template: {exc}") from exc
    if not isinstance(value, dict) or value.get("record_type") != "lean_build_run":
        raise ValidationError("invalid build manifest template")
    return value


def _publish_run(
    case: Path,
    guard: StateGuard,
    input_snapshot: InputSnapshot,
    source_project: Path,
    binary_bindings: Mapping[str, Mapping[str, Any]],
    run_id: str,
    manifest: dict[str, Any],
    command_results: Sequence[CommandResult],
    log: bytes,
    source_digest: str,
    inventory: list[dict[str, Any]],
    audit_source: bytes,
    axiom_output: bytes,
    allow_abort_tombstone: bool,
) -> Path:
    runs = safe_append_container(case, "evidence/runs")
    stage = Path(tempfile.mkdtemp(prefix=f".{run_id}.stage-", dir=str(runs)))
    target = runs / run_id
    try:
        if allow_abort_tombstone:
            tombstone = {
                "schema_version": 1,
                "record_type": "lean_build_run_tombstone",
                "case_id": manifest.get("case_id"),
                "problem_id": manifest.get("problem_id"),
                "run_id": run_id,
                "started_at": manifest.get("started_at"),
                "finished_at": manifest.get("finished_at"),
                "status": "ABORTED_ROOM_DISABLED",
                "result": "ABORTED_ROOM_DISABLED",
                "failure_class": "ROOM_STATE_CHANGED",
                "failure_summary": manifest.get("failure_summary"),
                "initial_room_state_binding": manifest.get("room_state_check"),
                "artifact_policy": "minimal tombstone only; no build outputs retained",
                "certificate_eligible": False,
                "automatic_math_status_change": False,
            }
            atomic_write_json(stage / "build_manifest.yaml", tombstone)
            publish_directory_noreplace(stage, target)
            return target
        atomic_write_bytes(stage / "build.log", log)
        command_output_dir = stage / "command_outputs"
        command_output_dir.mkdir()
        for index, command in enumerate(command_results, start=1):
            atomic_write_bytes(
                command_output_dir / f"{index:03d}.log",
                command.output,
            )
        atomic_write_bytes(stage / "source_tree.sha256", (source_digest + "\n").encode("ascii"))
        atomic_write_json(stage / "source_tree_inventory.json", inventory)
        atomic_write_bytes(stage / "declaration_audit.lean", audit_source)
        atomic_write_bytes(stage / "axioms.txt", axiom_output)
        manifest["log"].update(
            {
                "artifact": "build.log",
                "sha256": sha256_file(stage / "build.log"),
                "complete_untruncated": True,
            }
        )
        atomic_write_json(stage / "build_manifest.yaml", manifest)
        with _locked_state_guard(guard):
            if not guard.matches():
                raise RoomDisabledError(
                    "Lean Room state changed before evidence publication"
                )
            mutations = _input_mutations(input_snapshot, source_project)
            mutations.extend(_binary_mutations(binary_bindings))
            if mutations:
                raise ValidationError(
                    "verifier inputs changed before evidence publication: "
                    + "; ".join(mutations)
                )
            publish_directory_noreplace(stage, target)
        return target
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def verify(args: argparse.Namespace) -> tuple[Path, str, int]:
    root = discover_root(args.root)
    initial_status = require_room_enabled(root, "Lean verification")
    guard = _state_guard(root, initial_status)
    report = validate_case(root, args.problem_id, args.case_id, verification_ready=True)
    if not report.ok or report.contract is None or report.source_tree_sha256 is None:
        raise ValidationError("verification-ready validation failed: " + "; ".join(report.issues))
    case = report.case
    freeze = report.contract.get("freeze")
    snapshot_id = freeze.get("lr1_snapshot_id") if isinstance(freeze, dict) else None
    if not isinstance(snapshot_id, str):
        raise ValidationError("verification-ready contract lacks LR1 snapshot id")
    source_project = case / "evidence/freezes" / snapshot_id / "project.snapshot"
    reject_symlink_components(source_project, case)
    source_inventory, source_digest = project_tree_inventory(source_project)
    if source_digest != report.source_tree_sha256:
        raise ValidationError("source tree changed during verification preflight")
    input_snapshot = _capture_inputs(
        root, case, report.contract, source_inventory, source_digest
    )
    contract = input_snapshot.contract
    _dependency_preflight(source_project)
    environment_contract = contract["environment"]
    toolchain = environment_contract["lean_toolchain"]
    formal = contract["formal_target"]
    declaration = formal["declaration_name"]
    exact_type = formal["exact_type"]
    requested_axioms = set(
        contract["trusted_boundary"].get("permitted_axioms", [])
    )
    unsupported_axioms = requested_axioms - LEAN_ROOM_V1_ALLOWED_AXIOMS
    if unsupported_axioms:
        raise ValidationError(
            "contract requests axioms outside the Lean Room v1 hard allowlist: "
            + ", ".join(sorted(unsupported_axioms))
        )
    permitted_axioms = requested_axioms & LEAN_ROOM_V1_ALLOWED_AXIOMS
    run_started = utc_now()
    run_id = (
        "RUN-"
        + run_started.replace("-", "").replace(":", "").replace(".", "")
        + "-"
        + source_digest[:12]
    )
    command_results: list[CommandResult] = []
    audit_source = declaration_audit_bytes(declaration, exact_type)
    axiom_output = b""
    reported_axioms: set[str] = set()
    unpermitted_axioms: list[str] = []
    version_outputs: dict[str, str | None] = {
        "lean": None,
        "lake": None,
        "elan": None,
    }
    result = "FAIL"
    failure_class: str | None = None
    failure_summary: str | None = None
    gates = {"LR2": "FAIL", "LR3": "FAIL"}
    exit_code = EXIT_BUILD
    artifacts: list[dict[str, Any]] = []
    binary_bindings: dict[str, dict[str, Any]] = {}
    final_input_mutations: list[str] = []
    with tempfile.TemporaryDirectory(prefix="lean-room-build-") as temporary_name:
        build_root = Path(temporary_name)
        build_project = build_root / "project"
        _copy_frozen_project(source_project, build_project)
        (build_root / "audit").mkdir()
        audit_path = build_root / "audit/declaration_audit.lean"
        audit_path.write_bytes(audit_source)
        sandbox = Path("/usr/bin/sandbox-exec")
        if sandbox.is_symlink() or not sandbox.is_file() or sys.platform != "darwin":
            raise ValidationError("macOS sandbox-exec is required; no fallback is allowed")
        account_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        if not account_home.is_absolute() or account_home.is_symlink():
            raise ValidationError("OS account home is unsafe for pinned toolchain lookup")
        elan_home = account_home / ".elan"
        toolchain_component = toolchain.replace("/", "--").replace(":", "---")
        toolchain_root = elan_home / "toolchains" / toolchain_component
        lean_path = toolchain_root / "bin/lean"
        lake_path = toolchain_root / "bin/lake"
        elan_path = elan_home / "bin/elan"
        for path in (elan_home, toolchain_root, lean_path, lake_path, elan_path):
            reject_symlink_components(path, account_home)
        if not toolchain_root.is_dir() or toolchain_root.is_symlink():
            raise ValidationError(
                f"pinned toolchain is not installed locally: {toolchain}"
            )
        for name, path in (("lean", lean_path), ("lake", lake_path), ("elan", elan_path)):
            if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
                raise ValidationError(f"pinned {name} executable is unavailable or unsafe")
            binary_bindings[name] = {
                "artifact": str(path),
                "sha256": sha256_file(path),
                "size": path.stat().st_size,
            }
        base_env = _base_environment(
            build_root,
            toolchain,
            toolchain_root,
            lean_path,
            lake_path,
            elan_home,
        )
        profile = sandbox_profile(
            build_root,
            toolchain_root,
            (elan_path, lean_path, lake_path),
        )
        tools_ok = True
        for version_name, version_logical in (
            ("elan", [str(elan_path), "--version"]),
            ("lean", [str(lean_path), "--version"]),
            ("lake", [str(lake_path), "--version"]),
        ):
            version_result = run_guarded(
                guard,
                version_logical,
                _wrapped(profile, version_logical),
                build_project,
                base_env,
                min(args.timeout, 30.0),
            )
            command_results.append(version_result)
            if version_result.aborted_room_state:
                result, failure_class, failure_summary, exit_code = (
                    "ABORTED_ROOM_DISABLED",
                    "ROOM_STATE_CHANGED",
                    f"Room state changed during {version_name} version check",
                    EXIT_DISABLED,
                )
                tools_ok = False
                break
            rendered_version = version_result.output.decode(
                "utf-8", errors="replace"
            ).strip()
            if version_result.exit_code != 0 or not rendered_version:
                failure_class = "TOOLCHAIN_VERSION_CHECK_FAILED"
                failure_summary = f"pinned {version_name} version check failed"
                exit_code = EXIT_VALIDATION
                tools_ok = False
                break
            version_outputs[version_name] = rendered_version
        expected_version = toolchain.rsplit(":v", 1)[-1].lstrip("v")
        if tools_ok and (
            expected_version not in (version_outputs["lean"] or "")
            or expected_version not in (version_outputs["lake"] or "")
        ):
            failure_class = "TOOLCHAIN_VERSION_MISMATCH"
            failure_summary = "Lean/Lake version output does not match the frozen toolchain"
            exit_code = EXIT_VALIDATION
            tools_ok = False

        if tools_ok:
                build_logical = [
                    str(lake_path),
                    "--no-cache",
                    "build",
                    "LeanRoomCase",
                ]
                build_result = run_guarded(
                    guard,
                    build_logical,
                    _wrapped(profile, build_logical),
                    build_project,
                    base_env,
                    args.timeout,
                )
                command_results.append(build_result)
                if build_result.aborted_room_state:
                    result, failure_class, failure_summary, exit_code = (
                        "ABORTED_ROOM_DISABLED",
                        "ROOM_STATE_CHANGED",
                        "Room state changed during Lake build",
                        EXIT_DISABLED,
                    )
                elif build_result.exit_code != 0:
                    failure_class = "BUILD_FAILED"
                    failure_summary = "offline clean Lake build failed"
                else:
                    gates["LR2"] = "PASS"
                    probe_logical = [
                        str(lake_path),
                        "env",
                        str(lean_path),
                        str(audit_path),
                    ]
                    probe_result = run_guarded(
                        guard,
                        probe_logical,
                        _wrapped(profile, probe_logical),
                        build_project,
                        base_env,
                        args.timeout,
                    )
                    command_results.append(probe_result)
                    axiom_output = probe_result.output
                    if probe_result.aborted_room_state:
                        result, failure_class, failure_summary, exit_code = (
                            "ABORTED_ROOM_DISABLED",
                            "ROOM_STATE_CHANGED",
                            "Room state changed during declaration audit",
                            EXIT_DISABLED,
                        )
                    elif probe_result.exit_code != 0:
                        failure_class = "DECLARATION_OR_TYPE_MISMATCH"
                        failure_summary = "kernel rejected exact declaration/type audit"
                        exit_code = EXIT_VALIDATION
                    else:
                        try:
                            reported_axioms = _axioms_from_output(axiom_output)
                        except ValidationError as exc:
                            failure_class = "AXIOM_REPORT_UNPARSEABLE"
                            failure_summary = str(exc)
                            exit_code = EXIT_VALIDATION
                        else:
                            unpermitted_axioms = sorted(
                                reported_axioms - permitted_axioms
                            )
                            if unpermitted_axioms:
                                failure_class = "UNPERMITTED_AXIOMS"
                                failure_summary = "unpermitted axioms: " + ", ".join(
                                    unpermitted_axioms
                                )
                                exit_code = EXIT_VALIDATION
                            else:
                                _, work_digest = project_tree_inventory(build_project)
                                if work_digest != source_digest:
                                    failure_class = "SOURCE_TREE_MUTATION"
                                    failure_summary = (
                                        "disposable source tree mutation detected during build"
                                    )
                                    exit_code = EXIT_VALIDATION
                                elif not guard.matches():
                                    result, failure_class, failure_summary, exit_code = (
                                        "ABORTED_ROOM_DISABLED",
                                        "ROOM_STATE_CHANGED",
                                        "Room state changed before PASS publication",
                                        EXIT_DISABLED,
                                    )
                                else:
                                    gates["LR3"] = "PASS"
                                    result = "PASS"
                                    failure_class = None
                                    failure_summary = None
                                    exit_code = EXIT_OK
                    artifacts = _build_artifacts(build_project)

        if result != "ABORTED_ROOM_DISABLED":
            final_input_mutations = _input_mutations(input_snapshot, source_project)
            final_input_mutations.extend(_binary_mutations(binary_bindings))
            final_report = validate_case(
                root, args.problem_id, args.case_id, verification_ready=True
            )
            if not final_report.ok:
                final_input_mutations.append("verification-ready-validation-failed")
            if final_input_mutations:
                result = "FAIL"
                failure_class = "INPUT_MUTATION"
                failure_summary = "verifier inputs changed during run: " + "; ".join(
                    final_input_mutations
                )
                gates = {"LR2": "FAIL", "LR3": "FAIL"}
                exit_code = EXIT_VALIDATION

        finished = utc_now()
        log_parts: list[bytes] = []
        for index, command in enumerate(command_results, start=1):
            log_parts.append(
                (
                    f"===== command {index} =====\n"
                    + json.dumps(command.wrapped_argv, ensure_ascii=False)
                    + "\n"
                ).encode("utf-8")
                + command.output
                + (b"\n" if not command.output.endswith(b"\n") else b"")
            )
        log = b"".join(log_parts)
        manifest = _load_build_template(root)
        manifest.update(
            {
                "case_id": args.case_id,
                "problem_id": args.problem_id,
                "run_id": run_id,
                "run_kind": args.run_kind,
                "runner_id": args.runner_id,
                "started_at": run_started,
                "finished_at": finished,
                "status": result,
                "toolchain": toolchain,
                "result": result,
                "failure_class": failure_class,
                "failure_summary": failure_summary,
            }
        )
        manifest["room_state_check"].update(
            {
                "state": initial_status.effective_state,
                "state_sequence": guard.controls[0].binding.sequence,
                "state_artifact": initial_status.artifact.relative_to(root).as_posix(),
                "state_artifact_sha256": guard.controls[0].binding.artifact_sha256,
                "checked_at": run_started,
                "state_binding_still_current_at_finish": guard.matches(),
                "control_bindings": [
                    control.manifest_entry() for control in guard.controls
                ],
            }
        )
        manifest["contract"].update(
            {
                "artifact": "formalization_contract.yaml",
                "sha256": input_snapshot.contract_binding.sha256,
            }
        )
        target_binding = contract["target_binding"]
        manifest["target_binding"].update(
            {
                "target_id": target_binding.get("target_id"),
                "target_sha256": target_binding.get("artifact_sha256"),
                "target_artifact": target_binding.get("artifact"),
                "obligation_ids": contract["obligation_binding"].get("obligation_ids", []),
                "obligation_artifact": contract["obligation_binding"].get("artifact"),
                "obligation_sha256": contract["obligation_binding"].get("artifact_sha256"),
            }
        )
        manifest["clean_build"].update(
            {
                "fresh_build_root": "isolated disposable copy",
                "dirty_input_detected": False,
                "network_disabled": True,
                "dependency_fetch_performed": False,
                "unrecorded_generated_source_detected": result == "FAIL" and failure_class == "SOURCE_TREE_MUTATION",
                "sandbox_backend": LEAN_ROOM_SANDBOX_PROFILE_ID,
                "logical_command_schemas": {
                    "build": list(LEAN_ROOM_BUILD_COMMAND_SCHEMA),
                    "declaration_audit": list(LEAN_ROOM_AUDIT_COMMAND_SCHEMA),
                },
            }
        )
        manifest["environment"].update(
            {
                "operating_system": platform.platform(),
                "architecture": platform.machine(),
                "lean_version_output": version_outputs["lean"],
                "lake_version_output": version_outputs["lake"],
                "elan_version_output": version_outputs["elan"],
                "lean_toolchain": toolchain,
                "binary_bindings": binary_bindings,
                "environment_allowlist": sorted(base_env),
                "trusted_boundary_notes": [
                    "deny-default macOS Seatbelt profile",
                    "network denied",
                    "writes confined to disposable build root",
                    "reads confined to system runtime, Elan/toolchain, and disposable build root",
                    "local OS account, filesystem integrity, pinned Lean/Lake/Elan bytes, macOS Seatbelt, and the Lean kernel remain in the TCB",
                ],
            }
        )
        manifest["input_bindings"].update(
            {
                "source_tree_inventory": "source_tree_inventory.json",
                "source_tree_inventory_sha256": sha256_bytes(
                    pretty_json_bytes(list(input_snapshot.source_inventory))
                ),
                "source_tree_sha256_before": source_digest,
                "bound_files": [
                    item.manifest_entry() for item in input_snapshot.bound_files
                ],
                "lr0_snapshot_id": contract["freeze"].get("lr0_snapshot_id"),
                "lr1_snapshot_id": contract["freeze"].get("lr1_snapshot_id"),
                "lean_toolchain_sha256": environment_contract.get("lean_toolchain_sha256"),
                "lakefile_sha256": environment_contract.get("lakefile_sha256"),
                "lake_manifest_sha256": environment_contract.get("lake_manifest_sha256"),
                "dependencies": environment_contract.get("dependencies", []),
            }
        )
        manifest["commands"] = [item.wrapped_argv for item in command_results]
        manifest["command_results"] = []
        for index, item in enumerate(command_results, start=1):
            entry = item.manifest_entry()
            entry["output_artifact"] = f"command_outputs/{index:03d}.log"
            manifest["command_results"].append(entry)
        manifest["declaration_checks"] = [
            {
                "declaration_name": declaration,
                "exact_type": exact_type,
                "audit_artifact": "declaration_audit.lean",
                "type_check_mode": "kernel_definitional_equality_without_coercion",
                "axiom_check_subjects": [
                    declaration,
                    "private generated exact-target wrapper",
                ],
                "kernel_check_passed": gates["LR3"] == "PASS",
            }
        ]
        manifest["forbidden_construct_scan"].update(
            {
                "scanner_version": "lean-room-static-v1",
                "paths_scanned": [item["path"] for item in source_inventory],
                "findings": [],
                "authorized_findings": [],
                "passed": True,
            }
        )
        manifest["axiom_reports"] = [
            {
                "declaration_name": declaration,
                "audit_subjects": [
                    declaration,
                    "private generated exact-target wrapper",
                ],
                "artifact": "axioms.txt",
                "artifact_sha256": sha256_bytes(axiom_output),
                "permitted_axioms": sorted(permitted_axioms),
                "reported_axioms": sorted(reported_axioms),
                "unpermitted_axioms": unpermitted_axioms,
            }
        ]
        manifest["output_bindings"].update(
            {
                "source_tree_sha256_after": source_digest,
                "source_tree_unchanged": not any(
                    item.startswith("project:") for item in final_input_mutations
                )
                and failure_class != "SOURCE_TREE_MUTATION",
                "build_artifacts": artifacts,
            }
        )
        manifest["gates"].update(gates)
        aborted = result == "ABORTED_ROOM_DISABLED"
        try:
            published = _publish_run(
                case,
                guard,
                input_snapshot,
                source_project,
                binary_bindings,
                run_id,
                manifest,
                command_results,
                log,
                source_digest,
                source_inventory,
                audit_source,
                axiom_output,
                allow_abort_tombstone=aborted,
            )
        except RoomDisabledError:
            manifest["status"] = manifest["result"] = "ABORTED_ROOM_DISABLED"
            manifest["failure_class"] = "ROOM_STATE_CHANGED"
            manifest["failure_summary"] = "Room state changed during final evidence publication"
            exit_code = EXIT_DISABLED
            published = _publish_run(
                case,
                guard,
                input_snapshot,
                source_project,
                binary_bindings,
                run_id,
                manifest,
                command_results,
                log + b"\nRoom state changed during final publication.\n",
                source_digest,
                source_inventory,
                audit_source,
                axiom_output,
                allow_abort_tombstone=True,
            )
        return published, manifest["result"], exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline-build a frozen Lean Room case.")
    parser.add_argument("--root", help="laboratory root (normally auto-discovered)")
    parser.add_argument("problem_id")
    parser.add_argument("case_id")
    parser.add_argument("--runner-id", default="lean-room-builder")
    parser.add_argument(
        "--run-kind",
        choices=("candidate", "independent", "certification"),
        default="candidate",
    )
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout <= 0:
        print("ERROR: timeout must be positive", file=sys.stderr)
        return EXIT_VALIDATION
    try:
        path, result, exit_code = verify(args)
        payload = {"result": result, "evidence": str(path), "exit_code": exit_code}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            print(f"Lean verification result: {result}")
            print(f"Evidence: {path}")
        return exit_code
    except LeanRoomError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: verifier infrastructure failure: {exc}", file=sys.stderr)
        return EXIT_VALIDATION


if __name__ == "__main__":
    raise SystemExit(main())
