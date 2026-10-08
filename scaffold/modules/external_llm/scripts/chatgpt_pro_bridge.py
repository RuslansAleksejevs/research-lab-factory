#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-z0-9][a-z0-9-]{0,47}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ROLES = {
    "PROOF_GENERATOR",
    "ADVERSARIAL_VERIFIER",
    "COUNTEREXAMPLE_HUNTER",
    "STRATEGY_CRITIC",
}
CONTEXT_MODES = {
    "BLIND_GENERATION",
    "PROJECT_AWARE",
    "LITERATURE_AWARE",
    "VERIFICATION",
}
REQUIRED_HEADINGS = (
    "## Run identity and exposure",
    "## Exact task",
    "## Project-specific checks",
    "## Files supplied",
    "## Known state",
    "## Requested output",
)
DEFAULT_MAX_CONTEXT_BYTES = 131_072
HARD_MAX_CONTEXT_BYTES = 524_288
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class BridgeError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(value: Dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def root_path(value: str | None) -> Path:
    root = DEFAULT_ROOT if value is None else Path(value).expanduser()
    if not root.is_absolute():
        root = (Path.cwd() / root).absolute()
    try:
        mode = root.lstat().st_mode
    except OSError as exc:
        raise BridgeError(f"cannot inspect laboratory root: {exc}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise BridgeError("laboratory root must be a real directory, not a link")
    return root


def relative_path(value: str, label: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise BridgeError(f"{label} must be a safe root-relative path")
    return path


def regular_file(root: Path, relative: Path, label: str) -> Path:
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise BridgeError(f"cannot inspect {label} {relative.as_posix()}: {exc}") from exc
        if stat.S_ISLNK(mode):
            raise BridgeError(f"{label} cannot contain a symlink: {relative.as_posix()}")
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(mode):
            raise BridgeError(f"{label} has a non-directory parent: {relative.as_posix()}")
    if not stat.S_ISREG(current.lstat().st_mode):
        raise BridgeError(f"{label} must be a regular file: {relative.as_posix()}")
    return current


def read_utf8_file(root: Path, relative: Path, label: str, max_bytes: int) -> tuple[Path, bytes, str]:
    path = regular_file(root, relative, label)
    data = path.read_bytes()
    if not data:
        raise BridgeError(f"{label} is empty")
    if len(data) > max_bytes:
        raise BridgeError(f"{label} exceeds {max_bytes} UTF-8 bytes")
    if b"\x00" in data:
        raise BridgeError(f"{label} contains a NUL byte")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BridgeError(f"{label} must be UTF-8 text: {exc}") from exc
    return path, data, text


def validate_run_id(run_id: str) -> None:
    if not RUN_ID_RE.fullmatch(run_id):
        raise BridgeError("run ID must match YYYYMMDDTHHMMSSZ-lowercase-label")


def validate_atom(value: str, label: str) -> None:
    if (
        not value
        or len(value) > 128
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or Path(value).name != value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise BridgeError(f"{label} contains unsafe characters")


def run_directory(root: Path, run_id: str) -> Path:
    validate_run_id(run_id)
    return root / "runs" / "external_llm" / "chatgpt_pro" / run_id


def load_object(path: Path, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise BridgeError(f"cannot parse {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise BridgeError(f"{label} must contain a JSON object")
    return value


def write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
    except FileExistsError as exc:
        raise BridgeError(f"refusing to overwrite existing record: {path.name}") from exc


def validate_context(text: str) -> None:
    missing = [heading for heading in REQUIRED_HEADINGS if heading not in text]
    if missing:
        raise BridgeError("launch prompt lacks required headings: " + ", ".join(missing))
    forbidden = ["{{", "}}", "[required]"]
    if any(marker in text for marker in forbidden):
        raise BridgeError("launch prompt still contains an unfilled template marker")
    exact_task = text.split("## Exact task", 1)[1].split("## Project-specific checks", 1)[0].strip()
    if len(exact_task) < 80:
        raise BridgeError("launch prompt exact task is too short to be standalone")
    required_fields = {
        "Problem ID": r"^- Problem ID:\s*(\S.+)$",
        "Frozen target": r"^- Frozen target ID and SHA-256:\s*(\S.+)$",
        "Role": r"^- Role:\s*(\S.+)$",
    }
    for label, pattern in required_fields.items():
        if not re.search(pattern, text, flags=re.MULTILINE):
            raise BridgeError(f"launch prompt has no completed {label} field")


def source_records(root: Path, values: Iterable[str]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, value in enumerate(values, start=1):
        relative = relative_path(value, f"source file {index}")
        key = relative.as_posix().casefold()
        if key in seen:
            raise BridgeError(f"duplicate source file: {relative.as_posix()}")
        seen.add(key)
        path = regular_file(root, relative, f"source file {index}")
        records.append(
            {
                "path": relative.as_posix(),
                "display_name": path.name,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    return records


def verify_source_records(root: Path, records: Any) -> None:
    if not isinstance(records, list):
        raise BridgeError("manifest source_files must be an array")
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise BridgeError(f"manifest source_files[{index}] must be an object")
        relative = relative_path(str(record.get("path", "")), f"manifest source file {index}")
        path = regular_file(root, relative, f"manifest source file {index}")
        expected = record.get("sha256")
        if not isinstance(expected, str) or not SHA256_RE.fullmatch(expected):
            raise BridgeError(f"manifest source_files[{index}] has an invalid digest")
        if sha256_file(path) != expected or path.stat().st_size != record.get("bytes"):
            raise BridgeError(f"source bytes drifted before dispatch: {relative.as_posix()}")


def render_template(template: str, replacements: Dict[str, str]) -> str:
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    leftovers = sorted(set(re.findall(r"\{\{[A-Z0-9_]+\}\}", rendered)))
    if leftovers:
        raise BridgeError("unresolved prompt template tokens: " + ", ".join(leftovers))
    return rendered


def prepare(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    validate_run_id(args.run_id)
    validate_atom(args.problem_id, "problem ID")
    if args.role not in ROLES:
        raise BridgeError(f"unsupported role: {args.role}")
    if args.context_mode not in CONTEXT_MODES:
        raise BridgeError(f"unsupported context mode: {args.context_mode}")
    if args.max_context_bytes < 1024 or args.max_context_bytes > HARD_MAX_CONTEXT_BYTES:
        raise BridgeError(f"max context bytes must be between 1024 and {HARD_MAX_CONTEXT_BYTES}")

    launch_relative = relative_path(args.launch_prompt, "launch prompt")
    _, context_data, context_text = read_utf8_file(
        root, launch_relative, "launch prompt", args.max_context_bytes
    )
    validate_context(context_text)
    records = source_records(root, args.source_file)

    template_relative = Path("templates/chatgpt_pro_browser_prompt.md")
    _, _, template_text = read_utf8_file(
        root, template_relative, "ChatGPT Pro prompt template", 256 * 1024
    )
    if records:
        public_bindings = "\n".join(
            f"- `source-{index}`: SHA-256 `{record['sha256']}`"
            for index, record in enumerate(records, start=1)
        )
    else:
        public_bindings = "- None. The capsule is self-contained project text."
    prompt_text = render_template(
        template_text,
        {
            "RUN_ID": args.run_id,
            "ROLE": args.role,
            "CONTEXT_MODE": args.context_mode,
            "SOURCE_BINDINGS": public_bindings,
            "CONTEXT_PACKET": context_text.rstrip(),
        },
    ).rstrip() + "\n"
    prompt_data = prompt_text.encode("utf-8")
    if len(prompt_data) > HARD_MAX_CONTEXT_BYTES + 256 * 1024:
        raise BridgeError("rendered browser prompt is unexpectedly large")

    manifest = {
        "schema_version": 1,
        "adapter": "chatgpt_ui_sol_pro",
        "requested_model": "gpt-5.6-sol-pro",
        "run_id": args.run_id,
        "problem_id": args.problem_id,
        "role": args.role,
        "context_mode": args.context_mode,
        "prepared_at": utc_now(),
        "launch_prompt": {
            "path": launch_relative.as_posix(),
            "sha256": sha256_bytes(context_data),
            "bytes": len(context_data),
        },
        "context_packet": {
            "path": "context_packet.md",
            "sha256": sha256_bytes(context_data),
            "bytes": len(context_data),
        },
        "browser_prompt": {
            "path": "prompt.txt",
            "sha256": sha256_bytes(prompt_data),
            "bytes": len(prompt_data),
        },
        "source_files": records,
        "transmission_scope": {
            "context_packet_embedded": True,
            "source_bodies_transmitted_automatically": False,
            "browser_message_requires_explicit_approval": True,
        },
    }

    target = run_directory(root, args.run_id)
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise BridgeError(f"run already exists: {args.run_id}")
    stage = parent / f".{args.run_id}.stage-{uuid.uuid4().hex}"
    stage.mkdir(mode=0o700)
    try:
        write_new(stage / "context_packet.md", context_data)
        write_new(stage / "prompt.txt", prompt_data)
        write_new(stage / "manifest.json", json_bytes(manifest))
        os.rename(stage, target)
    except Exception:
        if stage.is_dir() and not stage.is_symlink():
            shutil.rmtree(stage)
        raise
    return status(root, args.run_id, verify=True)


def manifest_for(root: Path, run_id: str) -> tuple[Path, Dict[str, Any]]:
    directory = run_directory(root, run_id)
    if not directory.is_dir() or directory.is_symlink():
        raise BridgeError(f"unknown or unsafe run: {run_id}")
    manifest_path = regular_file(root, directory.relative_to(root) / "manifest.json", "run manifest")
    manifest = load_object(manifest_path, "run manifest")
    if manifest.get("schema_version") != 1 or manifest.get("run_id") != run_id:
        raise BridgeError("run manifest identity is invalid")
    if manifest.get("adapter") != "chatgpt_ui_sol_pro":
        raise BridgeError("run manifest adapter is invalid")
    return directory, manifest


def verify_packet(root: Path, run_id: str, *, require_sources: bool) -> tuple[Path, Dict[str, Any]]:
    directory, manifest = manifest_for(root, run_id)
    for field, expected_name in (("context_packet", "context_packet.md"), ("browser_prompt", "prompt.txt")):
        record = manifest.get(field)
        if not isinstance(record, dict) or record.get("path") != expected_name:
            raise BridgeError(f"manifest {field} record is invalid")
        path = regular_file(root, directory.relative_to(root) / expected_name, field)
        data = path.read_bytes()
        if sha256_bytes(data) != record.get("sha256") or len(data) != record.get("bytes"):
            raise BridgeError(f"{expected_name} no longer matches its prepared manifest")
    if require_sources:
        verify_source_records(root, manifest.get("source_files"))
    return directory, manifest


def approve(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    validate_atom(args.actor, "approval actor")
    if len(args.reason.strip()) < 10:
        raise BridgeError("approval reason must describe the explicit user authorization")
    directory, manifest = verify_packet(root, args.run_id, require_sources=True)
    if (directory / "dispatch.json").exists() or (directory / "response_manifest.json").exists():
        raise BridgeError("cannot approve a run after dispatch or response capture")
    prompt = manifest["browser_prompt"]
    record = {
        "schema_version": 1,
        "run_id": args.run_id,
        "approved_at": utc_now(),
        "approved_by": args.actor,
        "reason": args.reason.strip(),
        "destination": "https://chatgpt.com/",
        "approved_adapter": "chatgpt_ui_sol_pro",
        "approved_model": "gpt-5.6-sol-pro",
        "prompt_sha256": prompt["sha256"],
        "prompt_bytes": prompt["bytes"],
    }
    write_new(directory / "approval.json", json_bytes(record))
    return status(root, args.run_id, verify=True)


def approval_for(directory: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
    path = directory / "approval.json"
    if not path.is_file() or path.is_symlink():
        raise BridgeError("run lacks explicit approval for the exact prompt")
    approval = load_object(path, "approval record")
    prompt = manifest["browser_prompt"]
    if approval.get("run_id") != manifest.get("run_id"):
        raise BridgeError("approval run identity mismatch")
    if approval.get("prompt_sha256") != prompt.get("sha256") or approval.get("prompt_bytes") != prompt.get("bytes"):
        raise BridgeError("approval does not bind the prepared browser prompt")
    if approval.get("approved_model") != "gpt-5.6-sol-pro":
        raise BridgeError("approval does not bind GPT-5.6 Sol Pro")
    return approval


def record_dispatch(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    validate_atom(args.actor, "dispatch actor")
    if args.confirmed_model != "gpt-5.6-sol-pro":
        raise BridgeError("dispatch must confirm gpt-5.6-sol-pro exactly")
    visible = args.visible_model_label.strip()
    if not visible or "pro" not in visible.casefold():
        raise BridgeError("visible model label does not identify a Pro option")
    parsed = urlparse(args.chat_url)
    if parsed.scheme != "https" or parsed.hostname not in {"chatgpt.com", "www.chatgpt.com"}:
        raise BridgeError("chat URL must be an https://chatgpt.com conversation URL")
    directory, manifest = verify_packet(root, args.run_id, require_sources=True)
    approval = approval_for(directory, manifest)
    if (directory / "response_manifest.json").exists():
        raise BridgeError("cannot record dispatch after response capture")
    record = {
        "schema_version": 1,
        "run_id": args.run_id,
        "adapter": "chatgpt_ui_sol_pro",
        "requested_model": "gpt-5.6-sol-pro",
        "confirmed_model": args.confirmed_model,
        "visible_model_label": visible,
        "model_evidence_kind": "USER_INTERFACE_OBSERVATION_NOT_ATTESTATION",
        "chat_url": args.chat_url,
        "dispatched_at": utc_now(),
        "dispatched_by": args.actor,
        "prompt_sha256": manifest["browser_prompt"]["sha256"],
        "approval_sha256": sha256_file(directory / "approval.json"),
        "approved_at": approval["approved_at"],
    }
    write_new(directory / "dispatch.json", json_bytes(record))
    return status(root, args.run_id, verify=True)


def dispatch_for(directory: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
    path = directory / "dispatch.json"
    if not path.is_file() or path.is_symlink():
        raise BridgeError("run has not been dispatched")
    dispatch = load_object(path, "dispatch record")
    if dispatch.get("run_id") != manifest.get("run_id"):
        raise BridgeError("dispatch run identity mismatch")
    if dispatch.get("prompt_sha256") != manifest["browser_prompt"]["sha256"]:
        raise BridgeError("dispatch does not bind the prepared browser prompt")
    if dispatch.get("confirmed_model") != "gpt-5.6-sol-pro":
        raise BridgeError("dispatch does not confirm GPT-5.6 Sol Pro")
    return dispatch


def import_response(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    directory, manifest = verify_packet(root, args.run_id, require_sources=False)
    approval_for(directory, manifest)
    dispatch = dispatch_for(directory, manifest)
    relative = directory.relative_to(root) / "raw_response.md"
    _, response_data, response_text = read_utf8_file(root, relative, "raw browser response", MAX_RESPONSE_BYTES)
    if len(response_text.strip()) < 80:
        raise BridgeError("raw browser response is too short to be an auditable report")
    response_sha = sha256_bytes(response_data)
    record = {
        "schema_version": 1,
        "run_id": args.run_id,
        "adapter": "chatgpt_ui_sol_pro",
        "requested_model": "gpt-5.6-sol-pro",
        "visible_model_label": dispatch["visible_model_label"],
        "captured_at": utc_now(),
        "raw_response_path": "raw_response.md",
        "raw_response_sha256": response_sha,
        "raw_response_bytes": len(response_data),
        "prompt_sha256": manifest["browser_prompt"]["sha256"],
        "status": "UNVERIFIED_EXTERNAL_OUTPUT",
        "claim_status_changes_authorized": False,
    }
    intake_template_path = Path("templates/chatgpt_pro_response_intake.md")
    _, _, intake_template = read_utf8_file(
        root, intake_template_path, "ChatGPT Pro intake template", 256 * 1024
    )
    intake = render_template(
        intake_template,
        {
            "RUN_ID": args.run_id,
            "VISIBLE_MODEL_LABEL": dispatch["visible_model_label"],
            "PROMPT_SHA256": manifest["browser_prompt"]["sha256"],
            "RESPONSE_SHA256": response_sha,
        },
    )
    manifest_path = directory / "response_manifest.json"
    intake_path = directory / "intake.md"
    if manifest_path.exists() or manifest_path.is_symlink() or intake_path.exists() or intake_path.is_symlink():
        raise BridgeError("refusing to overwrite an existing response record")
    write_new(intake_path, intake.encode("utf-8"))
    try:
        # The response manifest is the commit marker used by current_state().
        # Publish it last so a partial intake can never appear complete.
        write_new(manifest_path, json_bytes(record))
    except Exception:
        try:
            intake_path.unlink()
        except OSError:
            pass
        raise
    return status(root, args.run_id, verify=True)


def current_state(directory: Path) -> str:
    if (directory / "response_manifest.json").is_file():
        return "RESPONSE_CAPTURED_UNVERIFIED"
    if (directory / "dispatch.json").is_file():
        return "DISPATCHED"
    if (directory / "approval.json").is_file():
        return "APPROVED"
    return "PREPARED"


def verify_complete_state(root: Path, run_id: str) -> tuple[Path, Dict[str, Any], List[str]]:
    directory, manifest = verify_packet(root, run_id, require_sources=False)
    state = current_state(directory)
    warnings: List[str] = []
    if state in {"APPROVED", "DISPATCHED", "RESPONSE_CAPTURED_UNVERIFIED"}:
        approval_for(directory, manifest)
    if state in {"DISPATCHED", "RESPONSE_CAPTURED_UNVERIFIED"}:
        dispatch_for(directory, manifest)
    if state == "RESPONSE_CAPTURED_UNVERIFIED":
        response_path = regular_file(
            root, directory.relative_to(root) / "raw_response.md", "raw browser response"
        )
        response_manifest = load_object(directory / "response_manifest.json", "response manifest")
        if response_manifest.get("raw_response_sha256") != sha256_file(response_path):
            raise BridgeError("raw browser response no longer matches its response manifest")
        if response_manifest.get("status") != "UNVERIFIED_EXTERNAL_OUTPUT":
            raise BridgeError("response manifest overstates external evidence")
        if response_manifest.get("claim_status_changes_authorized") is not False:
            raise BridgeError("response manifest improperly authorizes claim status changes")
        regular_file(root, directory.relative_to(root) / "intake.md", "response intake")
    try:
        verify_source_records(root, manifest.get("source_files"))
    except BridgeError as exc:
        if state in {"PREPARED", "APPROVED"}:
            raise
        warnings.append(str(exc))
    return directory, manifest, warnings


def status(root: Path, run_id: str, *, verify: bool) -> Dict[str, Any]:
    if verify:
        directory, manifest, warnings = verify_complete_state(root, run_id)
    else:
        directory, manifest = manifest_for(root, run_id)
        warnings = []
    state = current_state(directory)
    result: Dict[str, Any] = {
        "valid": True,
        "run_id": run_id,
        "state": state,
        "adapter": manifest.get("adapter"),
        "requested_model": manifest.get("requested_model"),
        "problem_id": manifest.get("problem_id"),
        "role": manifest.get("role"),
        "context_mode": manifest.get("context_mode"),
        "run_directory": directory.relative_to(root).as_posix(),
        "prompt_path": (directory.relative_to(root) / "prompt.txt").as_posix(),
        "prompt_sha256": manifest.get("browser_prompt", {}).get("sha256"),
        "source_binding_count": len(manifest.get("source_files", [])),
        "warnings": warnings,
        "mathematical_status_changed": False,
    }
    if state == "RESPONSE_CAPTURED_UNVERIFIED":
        response = load_object(directory / "response_manifest.json", "response manifest")
        result["response_sha256"] = response.get("raw_response_sha256")
        result["intake_path"] = (directory.relative_to(root) / "intake.md").as_posix()
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare and audit a human-gated ChatGPT Pro browser exchange."
    )
    parser.add_argument("--root", help="laboratory root; defaults to the script's parent project")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="freeze a compressed browser prompt")
    prepare_parser.add_argument("--run-id", required=True)
    prepare_parser.add_argument("--problem-id", required=True)
    prepare_parser.add_argument("--role", required=True, choices=sorted(ROLES))
    prepare_parser.add_argument("--context-mode", required=True, choices=sorted(CONTEXT_MODES))
    prepare_parser.add_argument("--launch-prompt", required=True)
    prepare_parser.add_argument("--source-file", action="append", default=[])
    prepare_parser.add_argument("--max-context-bytes", type=int, default=DEFAULT_MAX_CONTEXT_BYTES)

    approve_parser = subparsers.add_parser("approve", help="bind explicit user approval")
    approve_parser.add_argument("--run-id", required=True)
    approve_parser.add_argument("--actor", required=True)
    approve_parser.add_argument("--reason", required=True)

    dispatch_parser = subparsers.add_parser("record-dispatch", help="record a successful Pro UI submission")
    dispatch_parser.add_argument("--run-id", required=True)
    dispatch_parser.add_argument("--actor", required=True)
    dispatch_parser.add_argument("--confirmed-model", required=True)
    dispatch_parser.add_argument("--visible-model-label", required=True)
    dispatch_parser.add_argument("--chat-url", required=True)

    import_parser = subparsers.add_parser("import-response", help="bind an exact raw browser response")
    import_parser.add_argument("--run-id", required=True)

    status_parser = subparsers.add_parser("status", help="inspect and optionally verify a run")
    status_parser.add_argument("--run-id", required=True)
    status_parser.add_argument("--verify", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        root = root_path(args.root)
        if args.command == "prepare":
            result = prepare(root, args)
        elif args.command == "approve":
            result = approve(root, args)
        elif args.command == "record-dispatch":
            result = record_dispatch(root, args)
        elif args.command == "import-response":
            result = import_response(root, args)
        elif args.command == "status":
            result = status(root, args.run_id, verify=args.verify)
        else:
            raise BridgeError(f"unsupported command: {args.command}")
    except BridgeError as exc:
        if args.json:
            print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        else:
            print(f"ERROR {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"OK {result['run_id']} {result['state']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
