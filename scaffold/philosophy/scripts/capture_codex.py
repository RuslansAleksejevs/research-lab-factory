#!/usr/bin/env python3
"""Opt-in, bounded capture of original, reviewed visible Codex rollout records.

This is a filtered local import, not a provider request/response recorder.
"""
from __future__ import annotations

import argparse
from collections import Counter
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys

from research_archive import Archive

TOP_KEYS = {"timestamp", "ordinal", "type", "payload"}
META_KEYS = {"turn_id", "create_time", "content_item_kinds"}
COMMON_KEYS = {"type", "id", "internal_chat_message_metadata_passthrough"}
PAYLOAD_KEYS = {
    "message": COMMON_KEYS | {"role", "content", "phase", "channel"},
    "function_call": COMMON_KEYS | {"name", "namespace", "arguments", "call_id", "status"},
    "custom_tool_call": COMMON_KEYS | {"name", "namespace", "input", "call_id", "status"},
    "function_call_output": COMMON_KEYS | {"call_id", "output"},
    "custom_tool_call_output": COMMON_KEYS | {"call_id", "output"},
}
CALL_TYPES = {"function_call", "custom_tool_call"}
OUTPUT_TYPES = {"function_call_output", "custom_tool_call_output"}
TOOL_TYPES = CALL_TYPES | OUTPUT_TYPES
KNOWN_OMISSIONS = {
    "session_meta", "world_state", "turn_context", "event_msg", "token_usage_record",
    "inter_agent_communication_metadata", "compacted",
}
# Deliberately conservative: original call/output bytes are retained or omitted,
# never redacted and then labelled original. Review cannot override this filter.
SENSITIVE_MARKERS = (
    ".codex/sessions", ".codex/state_", "base_instructions", "encrypted_content",
    "<system>", "<developer>", "<|im_start|>system", "<|im_start|>developer",
)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def strict_json(value):
    """A parsed safe duplicate must never conceal unsafe original record bytes."""
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = item
        return result
    def constant(value):
        raise ValueError("non-finite JSON constant: " + value)
    return json.loads(value, object_pairs_hook=pairs, parse_constant=constant)


def valid_timestamp(value):
    if not isinstance(value, str):
        return False
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def observed_model(payload, source_line):
    """Project two safe configuration scalars; never retain the runtime envelope."""
    if not isinstance(payload, dict):
        return {"status": "unknown", "reason": "native turn context is unavailable or unsupported"}
    model = payload.get("model")
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", model):
        return {"status": "unknown", "reason": "native model identifier unavailable or unsupported"}
    effort = payload.get("effort")
    if not isinstance(effort, str) or effort not in {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}:
        effort = None
    return {"status": "known", "value": {"model": model, "reasoning_effort": effort},
            "source": "native-turn-context-observation", "source_line": source_line,
            "boundary": "Reported local configuration; exact backend identity and thinking duration unverified"}


def regular_file(path: Path):
    """Open a regular source through no-follow directory descriptors."""
    path = path.absolute()
    if ".." in path.parts:
        raise ValueError("source path may not contain parent traversal")
    directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            try:
                next_directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            except OSError as exc:
                raise ValueError("source directory is unavailable or contains a symlink") from exc
            os.close(directory)
            directory = next_directory
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except OSError as exc:
            raise ValueError("source is unavailable or a symlink") from exc
    finally:
        os.close(directory)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError("source must be a regular file")
    return os.fdopen(fd, "rb")


def resolve_session(session_id: str, expected_cwd: Path, state_db: Path | None = None) -> Path:
    """One bound-id metadata query; never enumerate tasks or scan session paths."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", session_id):
        raise ValueError("invalid session id")
    db = state_db or Path.home() / ".codex" / "state_5.sqlite"
    with regular_file(db):
        pass
    connection = sqlite3.connect(db.absolute().as_uri() + "?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT id, rollout_path, cwd FROM threads WHERE id = ?", (session_id,)
        ).fetchall()
    finally:
        connection.close()
    if len(rows) != 1 or rows[0][0] != session_id:
        raise ValueError("exact session identity not found")
    if Path(rows[0][2]).absolute() != expected_cwd.absolute():
        raise ValueError("session database cwd does not match expected project")
    return Path(rows[0][1])


def text_blocks(value, types):
    return (isinstance(value, list) and bool(value)
            and all(isinstance(c, dict) and set(c) == {"type", "text"}
                    and c["type"] in types and isinstance(c["text"], str) for c in value))


def classify(record, line_number, reviewed_tools, blocked_calls):
    if not isinstance(record, dict) or not set(record) <= TOP_KEYS:
        return "unknown_record_shape"
    if not valid_timestamp(record.get("timestamp")) or ("ordinal" in record and type(record["ordinal"]) is not int):
        return "unknown_record_metadata"
    typ = record.get("type")
    if typ != "response_item":
        return "excluded:" + str(typ) if typ in KNOWN_OMISSIONS else "unknown_record_type"
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return "unknown_payload_shape"
    subtype = payload.get("type")
    if subtype in {"reasoning", "agent_message"}:
        return "excluded:" + subtype
    if subtype not in PAYLOAD_KEYS:
        return "unknown_response_item_type"
    if not set(payload) <= PAYLOAD_KEYS[subtype]:
        return "unknown_payload_fields"
    for field in ("id", "role", "phase", "channel", "status", "name", "namespace", "call_id"):
        if field in payload and payload[field] is not None and not isinstance(payload[field], str):
            return "unknown_payload_scalar"
    meta = payload.get("internal_chat_message_metadata_passthrough", {})
    if not isinstance(meta, dict) or not set(meta) <= META_KEYS:
        return "unknown_metadata_fields"
    if ("turn_id" in meta and not isinstance(meta["turn_id"], str)) or ("create_time" in meta and not isinstance(meta["create_time"], (int, float))):
        return "unknown_metadata_value"
    if "content_item_kinds" in meta and (not isinstance(meta["content_item_kinds"], list) or any(not isinstance(k, str) for k in meta["content_item_kinds"])):
        return "unknown_metadata_value"
    if subtype == "message":
        role = payload.get("role")
        if role not in {"user", "assistant"}:
            return "excluded:message_role:" + str(role)
        if role == "user":
            if meta.get("content_item_kinds") != ["user.text"]:
                return "excluded:non_user_text_context"
            if not text_blocks(payload.get("content"), {"input_text"}):
                return "unknown_user_content"
        else:
            phase = payload.get("phase", payload.get("channel"))
            if phase == "analysis" or payload.get("channel") == "analysis":
                return "excluded:non_visible_assistant_phase"
            if phase not in {"commentary", "final", "final_answer"}:
                return "unknown_assistant_phase"
            if not text_blocks(payload.get("content"), {"output_text"}):
                return "unknown_assistant_content"
        return None
    call_id = payload.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        return "unknown_tool_call_id"
    if call_id in blocked_calls:
        return "excluded:blocked_tool_call"
    if subtype in CALL_TYPES:
        body = payload.get("arguments" if subtype == "function_call" else "input")
        if not isinstance(body, str) or not isinstance(payload.get("name"), str):
            return "unknown_tool_call_shape"
    else:
        body = payload.get("output")
        if not isinstance(body, str) and not text_blocks(body, {"text", "input_text", "output_text"}):
            return "unknown_tool_output_shape"
        if not isinstance(body, str):
            body = "\n".join(item["text"] for item in body)
    if any(marker in body for marker in SENSITIVE_MARKERS):
        return "excluded:sensitive_tool_body"
    if line_number not in reviewed_tools:
        return "withheld:tool_body_not_reviewed"
    return None


def capture(archive_root: Path, source: Path, session_id: str, expected_cwd: Path,
            *, start_line: int = 1, end_line: int | None = None,
            reviewed_tool_lines=(), run_id: str | None = None, target_lab: Path | None = None,
            technical_transfer: bool = False, max_bytes: int = 64 * 1024 * 1024):
    if start_line < 1 or (end_line is not None and end_line < start_line):
        raise ValueError("invalid source line range")
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    target = (target_lab or expected_cwd).absolute()
    if any(".." in path.parts for path in (archive_root, expected_cwd, target)):
        raise ValueError("project and archive paths may not contain parent traversal")
    cross_root = target != expected_cwd.absolute()
    if cross_root and not technical_transfer:
        raise ValueError("cross-project capture requires explicit technical transfer")
    if cross_root and end_line is None:
        raise ValueError("technical transfer requires an explicit closed line range")
    if archive_root.absolute() != target / "research" / "archive":
        raise ValueError("archive must be the exact target laboratory research/archive")
    with regular_file(target / "LAB_PROFILE.json") as profile_stream:
        profile = strict_json(profile_stream.read())
    with regular_file(target / ".lab" / "philosophy.json") as marker_stream:
        marker = strict_json(marker_stream.read())
    if (not isinstance(profile, dict) or not isinstance(profile.get("lab"), dict)
            or profile["lab"].get("kind") != "PHILOSOPHY_PROGRAM"):
        raise ValueError("capture target must be an identified philosophy laboratory")
    if (not isinstance(marker, dict) or marker.get("schema_version") != 1
            or marker.get("kernel") != "philosophy.v1"
            or marker.get("archive_format") != "research-archive.v1"):
        raise ValueError("capture target philosophy marker is invalid")
    reviewed = set(reviewed_tool_lines)
    if any(not isinstance(n, int) or n < start_line or (end_line is not None and n > end_line) for n in reviewed):
        raise ValueError("reviewed tool lines must be within selected range")
    with regular_file(source) as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > max_bytes:
            raise ValueError("source exceeds bounded capture size")
        snapshot = stream.read(before.st_size)
        after = os.fstat(stream.fileno())
    if len(snapshot) != before.st_size or after.st_size < before.st_size:
        raise ValueError("source truncated during snapshot")
    cutoff = snapshot.rfind(b"\n") + 1
    complete = snapshot[:cutoff]
    raw_lines = complete.splitlines(keepends=True)
    if not raw_lines:
        raise ValueError("source has no complete session metadata record")
    first = strict_json(raw_lines[0])
    if not isinstance(first, dict):
        raise ValueError("invalid session metadata record")
    meta = first.get("payload", {})
    if not isinstance(meta, dict):
        raise ValueError("invalid session metadata payload")
    if first.get("type") != "session_meta" or meta.get("id") != session_id:
        raise ValueError("source session identity mismatch")
    if not isinstance(meta.get("cwd"), str) or Path(meta["cwd"]).absolute() != expected_cwd.absolute():
        raise ValueError("source cwd does not match expected project")
    records = []
    for line_number, raw in enumerate(raw_lines, 1):
        try:
            record = strict_json(raw)
        except (ValueError, UnicodeError) as exc:
            raise ValueError(f"malformed complete JSONL record at line {line_number}") from exc
        records.append((line_number, raw, record))
    upper = min(end_line or len(records), len(records))
    if start_line > len(records) or (end_line is not None and end_line > len(records)):
        raise ValueError("selected range extends past complete source records")
    # Safety checks consider all call metadata in this exact source so a reviewed
    # result cannot bypass a blocked call situated before the selected range.
    blocked = set()
    model_at_line = {}
    model = {"status": "unknown", "reason": "no preceding native model observation"}
    for number, _, record in records:
        payload = record.get("payload", {}) if isinstance(record, dict) else {}
        if isinstance(record, dict) and record.get("type") == "turn_context":
            model = observed_model(payload, number)
        model_at_line[number] = model
        if isinstance(payload, dict) and payload.get("type") in CALL_TYPES:
            why = classify(record, number, {number}, set())
            if why:
                blocked.add(payload.get("call_id"))
    selected, excluded = [], Counter()
    selected_call_ids, selected_output_ids = set(), set()
    outputs_without_preceding_calls = False
    for number, raw, record in records[start_line - 1:upper]:
        why = classify(record, number, reviewed, blocked)
        if why:
            excluded[why] += 1
            continue
        selected.append((number, raw, record))
        payload = record["payload"]
        if payload["type"] in CALL_TYPES:
            selected_call_ids.add(payload["call_id"])
        elif payload["type"] in OUTPUT_TYPES:
            selected_output_ids.add(payload["call_id"])
            if payload["call_id"] not in selected_call_ids:
                outputs_without_preceding_calls = True
    gaps = []
    limitations = ["provider_request_envelopes_unavailable", "future_records_not_captured",
                   "excluded_runtime_and_hidden_records", "no_claim_of_full_provider_capture",
                   "model_is_reported_configuration_not_backend_attestation", "thinking_duration_unavailable"]
    if start_line > 1 or upper < len(records):
        limitations.append("bounded_range_omits_other_source_records")
    if end_line is None:
        gaps.append("live_source_snapshot_not_finalized")
    if len(snapshot) != cutoff:
        gaps.append("partial_tail_withheld")
    if after.st_size > before.st_size:
        gaps.append("source_grew_during_snapshot")
    if any(key.startswith("unknown") for key in excluded):
        gaps.append("unknown_schema_records_withheld")
    if any(key in {"excluded:sensitive_tool_body", "excluded:blocked_tool_call"} for key in excluded):
        gaps.append("sensitive_tool_bodies_withheld")
    if any(key.startswith("withheld") for key in excluded):
        gaps.append("unreviewed_tool_bodies_withheld")
    if selected_call_ids - selected_output_ids:
        gaps.append("selected_tool_calls_without_selected_results")
    if selected_output_ids - selected_call_ids:
        gaps.append("selected_tool_results_without_selected_calls")
    elif outputs_without_preceding_calls:
        gaps.append("selected_tool_results_without_preceding_selected_calls")
    report = {
        "format": "codex-visible-selection.v1", "session_id": session_id,
        "source_basename": source.name, "cwd_binding_verified": True,
        "target_identity_verified": True, "technical_transfer": bool(cross_root),
        "source_snapshot_bytes": len(snapshot), "source_complete_bytes": cutoff,
        "source_snapshot_sha256": digest(snapshot), "partial_tail_bytes": len(snapshot) - cutoff,
        "complete_source_lines": len(records), "selected_range": [start_line, upper],
        "reviewed_tool_lines": sorted(reviewed), "captured_records": len(selected),
        "excluded_counts": dict(sorted(excluded.items())), "coverage_gaps": gaps,
        "status": "INCOMPLETE" if gaps else "BOUNDED_COMPLETE",
        "gaps": gaps, "exclusions": [{"reason": k, "count": v} for k, v in sorted(excluded.items())],
        "limitations": limitations,
        "capture_status": "filtered_selection", "full_provider_capture": False,
        "raw_records": [{"source_line": n, "sha256": digest(raw), "bytes": len(raw)} for n, raw, _ in selected],
    }
    archive = Archive(archive_root)
    archive.init()
    run_id = run_id or "codex:" + session_id
    report["run_id"] = run_id
    raw_event_ids = []
    calls = {}
    tool_pairs = []
    bindings = {key: [] for key in ("method", "instruction", "config", "input")}
    for number, raw, record in selected:
        sha = archive.put(raw)
        payload = record["payload"]
        role = payload.get("role", "tool" if payload["type"] in OUTPUT_TYPES else "assistant")
        stored = archive.append({
            "kind": "capture.raw_record", "actor": {"id": "codex:" + role, "role": role},
            "timestamp": record["timestamp"], "model": model_at_line[number],
            "session_id": session_id, "run_id": run_id,
            "operation_id": f"codex-source-line:{session_id}:{number}", "attempt_id": "capture-v1",
            "parents": [],
            "inputs": [], "outputs": [sha], "bindings": bindings,
            "payload": {"format": report["format"], "source_basename": source.name,
                        "source_line": number, "raw_sha256": sha,
                        "source_type": payload["type"], "call_id": payload.get("call_id"),
                        "source_timestamp": record["timestamp"],
                        "source_timestamp_provenance": "local-native-record; clock not independently attested",
                        "cwd_binding_verified": True},
        }, delivery_key=f"codex-visible-v1:{session_id}:{number}")
        raw_event_ids.append(stored["id"])
        if payload["type"] in CALL_TYPES:
            calls[payload["call_id"]] = stored["id"]
        elif payload["type"] in OUTPUT_TYPES and payload["call_id"] in calls:
            tool_pairs.append((payload["call_id"], calls[payload["call_id"]], stored["id"]))
    tool_link_ids = []
    for call_id, call_event, output_event in tool_pairs:
        pair_sha = digest((call_event + "\n" + output_event).encode())
        link = archive.append({
            "kind": "capture.tool_link", "actor": {"id": "codex-capture-adapter", "role": "tool"},
            "session_id": session_id, "run_id": run_id,
            "operation_id": "codex-tool-link:" + pair_sha, "attempt_id": "capture-v1",
            "parents": [call_event, output_event], "inputs": [], "outputs": [], "bindings": bindings,
            "payload": {"call_id": call_id, "call_event_id": call_event, "output_event_id": output_event,
                        "boundary": "Native call-ID correspondence; no claim of tool correctness"},
        }, delivery_key="codex-tool-link-v1:" + pair_sha)
        tool_link_ids.append(link["id"])
    report["raw_event_ids"] = raw_event_ids
    report["tool_link_ids"] = tool_link_ids
    encoded_report = (json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()
    sha = archive.put(encoded_report)
    coverage = archive.append({
        "kind": "capture.coverage", "actor": {"id": "codex-capture-adapter", "role": "tool"},
        "session_id": session_id, "run_id": run_id, "operation_id": "codex-capture-report:" + sha,
        "attempt_id": "capture-v1", "parents": raw_event_ids + tool_link_ids, "inputs": [], "outputs": [sha],
        "bindings": bindings, "payload": {"capture_status": "filtered_selection", "report_sha256": sha,
                                             "status": report["status"], "gaps": gaps,
                                             "exclusions": report["exclusions"]},
    }, delivery_key="codex-visible-report-v1:" + sha)
    report["coverage_event_id"] = coverage["id"]
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--source", type=Path, help="Exact local rollout; never a directory")
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--session-id")
    identity.add_argument("--current", action="store_true", help="Explicit opt-in to current thread exact-ID lookup")
    parser.add_argument("--expected-cwd", type=Path, required=True, help="Explicit exact authorized project root; factory use is only a technical demonstration")
    parser.add_argument("--target-lab", type=Path, help="Exact target philosophy laboratory; defaults to expected cwd")
    parser.add_argument("--technical-transfer", action="store_true", help="Explicitly allow a bounded technical capture from expected cwd into target lab")
    parser.add_argument("--run-id", help="Bind this capture to the authorized local round run")
    parser.add_argument("--start-line", type=int, default=1)
    parser.add_argument("--end-line", type=int)
    parser.add_argument("--reviewed-tool-lines", default="", help="Comma-separated exact tool record lines whose bodies were reviewed")
    parser.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024)
    args = parser.parse_args(argv)
    session_id = os.environ.get("CODEX_THREAD_ID") if args.current else args.session_id
    if not session_id:
        parser.error("current CODEX_THREAD_ID is unavailable; supply exact --session-id")
    try:
        reviewed = [int(item) for item in args.reviewed_tool_lines.split(",") if item]
        source = args.source or resolve_session(session_id, args.expected_cwd)
        result = capture(args.archive, source, session_id, args.expected_cwd,
                         start_line=args.start_line, end_line=args.end_line,
                         reviewed_tool_lines=reviewed, run_id=args.run_id, target_lab=args.target_lab,
                         technical_transfer=args.technical_transfer, max_bytes=args.max_bytes)
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(2, f"capture failed: {exc}\n")
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
