#!/usr/bin/env python3
"""Portable local research archive. Python 3.9+, standard library only.

Canonical records are immutable objects and events; every view is derived.
This module records supplied material, never obtains hidden reasoning or
claims complete capture of a host application's conversation.
"""
import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import uuid

VERSION = 1
if __name__ == '__main__':
    sys.modules.setdefault('research_archive', sys.modules[__name__])
HEX = re.compile(r"^[0-9a-f]{64}$")
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
TERMINALS = {"operation.completed", "operation.failed", "operation.interrupted"}
BINDINGS = ("method", "instruction", "config", "input")
EXTRA_FORMAT_PATHS = {"format/" + name for name in (
    "research_timeline.py", "philosophy_round.py", "candidate_birth.schema.json", "TIMELINE.md", "ROUND.md")}


class ArchiveError(ValueError):
    pass


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _safe_path(path):
    """Reject symlinks, including ancestors; do not resolve away their evidence."""
    path = Path(os.path.abspath(str(path)))
    for part in reversed([path] + list(path.parents)):
        try:
            mode = part.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise ArchiveError("symlink forbidden: " + str(part))
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise ArchiveError("special file forbidden: " + str(part))
    return path


def _read(path):
    path = _safe_path(path)
    before = path.lstat()
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise ArchiveError("not a regular file: " + str(path))
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ArchiveError("file changed while opening: " + str(path))
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read()
        after = os.fstat(fd)
        current = path.lstat()
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(opened, field) != getattr(after, field) or
               getattr(after, field) != getattr(current, field) for field in fields):
            raise ArchiveError("file changed while reading: " + str(path))
        return data
    finally:
        os.close(fd)


def _json(path):
    try:
        return json.loads(_read(path))
    except (ValueError, UnicodeError) as exc:
        raise ArchiveError("invalid JSON: " + str(path)) from exc


def _fsync_dir(path):
    fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _publish(path, data):
    """Durable no-clobber publish. Interrupted temporary files are audit evidence."""
    path = _safe_path(path)
    tmp = path.parent / (".tmp-" + uuid.uuid4().hex)
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(fd)
        os.fchmod(fd, 0o400)
        os.link(str(tmp), str(path), follow_symlinks=False)
        _fsync_dir(path.parent)
        tmp.unlink()
        _fsync_dir(path.parent)
    except FileExistsError:
        tmp.unlink()
        raise ArchiveError("refusing to overwrite: " + str(path))
    finally:
        os.close(fd)


def _require_id(value, name):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise ArchiveError("invalid " + name)


def _digest_list(value, name):
    if not isinstance(value, list) or any(not isinstance(x, str) or not HEX.fullmatch(x) for x in value):
        raise ArchiveError(name + " must be an array of SHA-256 object digests")


def _check_event(event):
    if not isinstance(event, dict) or type(event.get("schema_version")) is not int or event["schema_version"] != VERSION:
        raise ArchiveError("unsupported event schema")
    required = {"id", "sequence", "timestamp", "recorded_at", "timestamp_source", "origin", "kind", "actor", "session_id",
                "run_id", "operation_id", "attempt_id", "parents", "inputs", "outputs",
                "bindings", "model", "cost", "payload", "delivery_key", "request_sha256",
                "previous_sha256", "sha256", "schema_version"}
    if set(event) != required:
        raise ArchiveError("event fields differ from schema")
    for name in ("id", "kind", "session_id", "run_id", "operation_id", "attempt_id"):
        _require_id(event.get(name), name)
    if not isinstance(event.get("sequence"), int) or isinstance(event["sequence"], bool) or not 1 <= event["sequence"] <= 999999999999:
        raise ArchiveError("invalid event sequence")
    for field in ("timestamp", "recorded_at"):
        if not isinstance(event.get(field), str):
            raise ArchiveError(field + " required")
        try:
            stamp = datetime.datetime.fromisoformat(event[field].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError()
        except ValueError as exc:
            raise ArchiveError(field + " must include timezone") from exc
    if event["timestamp_source"] not in ("supplied-event-time", "archive-clock-event-time-unknown"):
        raise ArchiveError("invalid timestamp provenance")
    for name in ("origin", "actor"):
        if not isinstance(event.get(name), dict):
            raise ArchiveError(name + " required")
    _require_id(event["origin"].get("archive_id"), "origin archive_id")
    for name in ("id", "role"):
        _require_id(event["actor"].get(name), "actor " + name)
    parents = event.get("parents")
    if not isinstance(parents, list) or any(not isinstance(p, str) for p in parents) or len(set(parents)) != len(parents):
        raise ArchiveError("parents must be unique event IDs")
    for parent in parents:
        _require_id(parent, "parent")
    for name in ("inputs", "outputs"):
        _digest_list(event.get(name), name)
    if not isinstance(event.get("bindings"), dict) or set(event["bindings"]) != set(BINDINGS):
        raise ArchiveError("bindings require method, instruction, config, input")
    for key in BINDINGS:
        _digest_list(event["bindings"][key], "bindings." + key)
    for name in ("model", "cost"):
        value = event.get(name)
        if not isinstance(value, dict) or value.get("status") not in ("known", "unknown"):
            raise ArchiveError(name + " requires explicit known/unknown status")
        if value["status"] == "unknown" and (not isinstance(value.get("reason"), str) or not value["reason"]):
            raise ArchiveError(name + " unknown requires reason")
        if value["status"] == "known" and "value" not in value:
            raise ArchiveError(name + " known requires value")
    if not isinstance(event.get("payload"), dict):
        raise ArchiveError("payload must be an object")
    if not isinstance(event.get("delivery_key"), str) or not 1 <= len(event["delivery_key"]) <= 500:
        raise ArchiveError("delivery key must contain 1..500 characters")
    for name in ("sha256", "request_sha256"):
        if not isinstance(event.get(name), str) or not HEX.fullmatch(event[name]):
            raise ArchiveError("invalid " + name)
    if event["previous_sha256"] is not None and not HEX.fullmatch(str(event["previous_sha256"])):
        raise ArchiveError("invalid previous_sha256")
    unsigned = dict(event)
    unsigned.pop("sha256")
    if sha(canonical(unsigned)) != event["sha256"]:
        raise ArchiveError("event digest mismatch")


def _refs(event):
    return set(event["inputs"] + event["outputs"] +
               [digest for values in event["bindings"].values() for digest in values])


class Archive:
    def __init__(self, root):
        self.root = _safe_path(root)

    def init(self):
        if not self.root.exists():
            self.root.mkdir(parents=True, exist_ok=True)
            _fsync_dir(self.root.parent)
        with self._lock(initializing=True):
            identity = self.root / "archive.json"
            if identity.exists():
                self._identity()
                return self
            unexpected = [p for p in self.root.iterdir() if p.name != ".lock"]
            if unexpected:
                raise ArchiveError("initialization requires empty destination")
            for name in ("objects", "events"):
                (self.root / name).mkdir()
            _publish(identity, canonical({"schema_version": VERSION, "archive_id": "archive-" + uuid.uuid4().hex,
                                          "created_at": now()}))
        return self

    def _identity(self):
        identity = _json(self.root / "archive.json")
        if not isinstance(identity, dict) or type(identity.get("schema_version")) is not int or identity["schema_version"] != VERSION:
            raise ArchiveError("unsupported archive format")
        _require_id(identity.get("archive_id"), "archive_id")
        for name in ("objects", "events"):
            if not _safe_path(self.root / name).is_dir():
                raise ArchiveError("missing archive directory: " + name)
        return identity

    @contextlib.contextmanager
    def _lock(self, initializing=False):
        _safe_path(self.root)
        if not initializing:
            self._identity()
        fd = os.open(str(self.root / ".lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ArchiveError("lock is not regular")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def put(self, data):
        if not isinstance(data, bytes):
            raise TypeError("put requires exact bytes")
        digest = sha(data)
        with self._lock():
            path = self.root / "objects" / digest
            if path.exists():
                if _read(path) != data:
                    raise ArchiveError("corrupt existing object; refusing repair/overwrite")
            else:
                _publish(path, data)
        return digest

    def get(self, digest):
        _digest_list([digest], "digest")
        data = _read(self.root / "objects" / digest)
        if sha(data) != digest:
            raise ArchiveError("object digest mismatch: " + digest)
        return data

    def _records(self):
        records, errors, temporaries = [], [], []
        for path in sorted((self.root / "events").iterdir()):
            if path.name.startswith(".tmp-"):
                temporaries.append("events/" + path.name)
                continue
            try:
                event = _json(path)
                _check_event(event)
                if path.name != "%012d.json" % event["sequence"]:
                    raise ArchiveError("event filename/sequence mismatch")
                if _read(path) != canonical(event):
                    raise ArchiveError("event bytes are not canonical")
                records.append(event)
            except (ArchiveError, OSError, TypeError, KeyError) as exc:
                errors.append({"path": "events/" + path.name, "error": str(exc)})
        return records, errors, temporaries

    def _scope(self):
        path = self.root / "scope.json"
        if not path.exists():
            return {"omitted_events": []}
        scope = _json(path)
        if not isinstance(scope, dict) or scope.get("schema_version") != VERSION or not isinstance(scope.get("omitted_events"), list):
            raise ArchiveError("invalid scope record")
        for item in scope["omitted_events"]:
            if not isinstance(item, dict) or set(item) != {"id", "sequence", "sha256", "previous_sha256", "delivery_key_sha256"}:
                raise ArchiveError("invalid omitted event commitment")
            _require_id(item["id"], "omitted event id")
            if not isinstance(item["sequence"], int) or not 1 <= item["sequence"] <= 999999999999:
                raise ArchiveError("invalid omitted sequence")
            _digest_list([item["sha256"]], "omitted digest")
            _digest_list([item["delivery_key_sha256"]], "omitted delivery key digest")
            if item["previous_sha256"] is not None:
                _digest_list([item["previous_sha256"]], "omitted previous digest")
        return scope

    def _audit(self):
        self._identity()
        records, errors, temporaries = self._records()
        omitted = self._scope()["omitted_events"]
        commitments = sorted(records + omitted, key=lambda x: x["sequence"])
        seqs = [x["sequence"] for x in commitments]
        gaps = []
        frontier = 0
        for sequence in sorted(set(seqs)):
            if sequence > frontier + 1:
                if sequence - frontier <= 1000 and len(gaps) < 1000:
                    gaps.extend(range(frontier + 1, sequence))
                else:
                    gaps.append({"from": frontier + 1, "through": sequence - 1})
            frontier = sequence
        if gaps:
            errors.append({"error": "unexplained sequence gaps", "sequences": gaps})
        if len(seqs) != len(set(seqs)):
            errors.append({"error": "duplicate sequence"})
        ids, deliveries, referenced = set(), set(), set()
        previous = None
        for item in commitments:
            if item["previous_sha256"] != previous:
                errors.append({"error": "broken event hash chain", "id": item["id"]})
            previous = item["sha256"]
            if item["id"] in ids:
                errors.append({"error": "duplicate event ID", "id": item["id"]})
            ids.add(item["id"])
        seen, attempts = {}, {}
        for event in records:
            if event["delivery_key"] in deliveries:
                errors.append({"error": "duplicate delivery key", "id": event["id"]})
            deliveries.add(event["delivery_key"])
            if any(p not in seen for p in event["parents"]):
                errors.append({"error": "missing or non-causal parent", "id": event["id"]})
            try:
                self._transition(event, seen, attempts)
            except ArchiveError as exc:
                errors.append({"error": str(exc), "id": event["id"]})
            seen[event["id"]] = event
            referenced.update(_refs(event))
        present = set()
        for path in sorted((self.root / "objects").iterdir()):
            if path.name.startswith(".tmp-"):
                temporaries.append("objects/" + path.name)
                continue
            try:
                if not HEX.fullmatch(path.name):
                    raise ArchiveError("invalid object name")
                self.get(path.name)
                present.add(path.name)
            except (ArchiveError, OSError) as exc:
                errors.append({"path": "objects/" + path.name, "error": str(exc)})
        for digest in sorted(referenced - present):
            errors.append({"error": "missing or damaged referenced object", "sha256": digest})
        allowed = {"archive.json", "objects", "events", ".lock", "scope.json", "format", "bundle_manifest.json"}
        for path in self.root.iterdir():
            if path.name.startswith(".tmp-"):
                temporaries.append(path.name)
            elif path.name not in allowed:
                errors.append({"path": path.name, "error": "unexpected archive entry"})
        if (self.root / "format").exists() or (self.root / "bundle_manifest.json").exists():
            try:
                manifest = _json(self.root / "bundle_manifest.json")
                expected = {name: meta for name, meta in manifest["files"].items() if name.startswith("format/")}
                actual = {"format/" + path.name for path in (self.root / "format").iterdir()}
                if actual != set(expected):
                    raise ArchiveError("imported interpretation file set changed")
                for name, meta in manifest["files"].items():
                    if not (name in {"archive.json", "scope.json", "format/archive_event.schema.json", "format/ARCHIVE_FORMAT.md", "format/research_archive.py"}
                            or name in EXTRA_FORMAT_PATHS
                            or re.fullmatch(r"events/[0-9]{12}\.json", name) or re.fullmatch(r"objects/[0-9a-f]{64}", name)):
                        raise ArchiveError("invalid retained manifest path")
                    data = _read(self.root / name)
                    if meta != {"sha256": sha(data), "size": len(data)}:
                        raise ArchiveError("imported committed bytes changed: " + name)
            except (ArchiveError, OSError, KeyError, TypeError) as exc:
                errors.append({"error": str(exc), "path": "format"})
        incomplete = [{"attempt_id": key, "operation_id": value["start"]["operation_id"],
                       "started_event": value["start"]["id"], "status": "unresolved"}
                      for key, value in sorted(attempts.items()) if value["terminal"] is None]
        return {"ok": not errors, "schema_version": VERSION, "event_count": len(records),
                "errors": errors, "temporary_files": sorted(temporaries),
                "orphan_objects": sorted(present - referenced), "sequence_gaps": gaps,
                "omitted_events": omitted, "incomplete_attempts": incomplete,
                "recovery_policy": "read-only; unresolved attempts never imply success"}

    @staticmethod
    def _transition(event, seen, attempts):
        if 'timeline_version' in event['payload']:
            from research_timeline import _validate_one
            try:
                _validate_one(event, seen)
            except (KeyError, TypeError) as exc:
                raise ArchiveError('malformed typed timeline event: ' + str(exc)) from exc
        kind, attempt = event["kind"], event["attempt_id"]
        if kind == "operation.started":
            if attempt in attempts:
                raise ArchiveError("attempt already started; retry requires a new attempt_id")
            attempts[attempt] = {"start": event, "terminal": None}
        elif kind in TERMINALS:
            state = attempts.get(attempt)
            if not state or state["terminal"]:
                raise ArchiveError("terminal requires one unterminated start")
            start = state["start"]
            if start["id"] not in event["parents"]:
                raise ArchiveError("terminal must causally reference its start")
            if any(event[k] != start[k] for k in ("session_id", "run_id", "operation_id")):
                raise ArchiveError("terminal/start provenance mismatch")
            if event["bindings"] != start["bindings"]:
                raise ArchiveError("terminal/start exact version bindings differ")
            state["terminal"] = event
        elif kind in ("candidate.branch", "candidate.merge", "candidate.reject", "candidate.reopen",
                      "method.switch", "correction", "decision"):
            minimum = 2 if kind == "candidate.merge" else 1
            if len(event["parents"]) < minimum:
                raise ArchiveError(kind + " requires causal parent(s)")

    def validate(self):
        try:
            with self._lock():
                return self._audit()
        except (ArchiveError, OSError, KeyError, TypeError) as exc:
            return {"ok": False, "schema_version": VERSION, "errors": [{"error": str(exc)}],
                    "event_count": None, "temporary_files": [], "orphan_objects": [],
                    "sequence_gaps": [], "omitted_events": [], "incomplete_attempts": [],
                    "recovery_policy": "read-only; unresolved attempts never imply success"}

    def recover(self):
        """Audit only. Recovery decisions themselves must be new events."""
        return self.validate()

    def events(self):
        with self._lock():
            report = self._audit()
            if not report["ok"]:
                raise ArchiveError("archive integrity failed: " + json.dumps(report["errors"]))
            return self._records()[0]

    def append(self, event, delivery_key):
        request = json.loads(canonical(event))
        request_hash = sha(canonical(request))
        if not isinstance(delivery_key, str) or not 1 <= len(delivery_key) <= 500:
            raise ArchiveError("delivery key must contain 1..500 characters")
        reserved = {"sequence", "delivery_key", "request_sha256", "previous_sha256", "sha256", "schema_version", "recorded_at", "timestamp_source"}
        if not isinstance(request, dict) or set(request) & reserved:
            raise ArchiveError("append request contains reserved fields")
        with self._lock():
            report = self._audit()
            if not report["ok"]:
                raise ArchiveError("archive integrity failed; recover before appending")
            records = self._records()[0]
            for existing in records:
                if existing["delivery_key"] == delivery_key:
                    if existing["request_sha256"] != request_hash:
                        raise ArchiveError("delivery key conflict")
                    return existing
            if any(x["delivery_key_sha256"] == sha(delivery_key.encode("utf-8")) for x in self._scope()["omitted_events"]):
                raise ArchiveError("delivery key belongs to an explicitly omitted event; recover its original record")
            prior = sorted(records + self._scope()["omitted_events"], key=lambda x: x["sequence"])
            item = dict(request)
            item.setdefault("id", "event-" + uuid.uuid4().hex)
            item["recorded_at"] = now()
            item["timestamp_source"] = "supplied-event-time" if "timestamp" in request else "archive-clock-event-time-unknown"
            item.setdefault("timestamp", item["recorded_at"])
            item.setdefault("origin", {"archive_id": self._identity()["archive_id"]})
            for name in ("parents", "inputs", "outputs"):
                item.setdefault(name, [])
            item.setdefault("bindings", {key: [] for key in BINDINGS})
            for name in ("model", "cost"):
                item.setdefault(name, {"status": "unknown", "reason": "not supplied by capture source"})
            item.setdefault("payload", {})
            item.update(schema_version=VERSION, sequence=prior[-1]["sequence"] + 1 if prior else 1,
                        delivery_key=delivery_key, request_sha256=request_hash,
                        previous_sha256=prior[-1]["sha256"] if prior else None)
            item["sha256"] = sha(canonical(item))
            _check_event(item)
            if any(x["id"] == item["id"] for x in prior):
                raise ArchiveError("event ID already exists")
            seen = {x["id"]: x for x in records}
            if any(parent not in seen for parent in item["parents"]):
                raise ArchiveError("missing parent; selected export must include parent closure")
            for digest in _refs(item):
                self.get(digest)
            attempts = {}
            chronological_seen = {}
            for existing in records:
                self._transition(existing, chronological_seen, attempts)
                chronological_seen[existing['id']] = existing
            self._transition(item, seen, attempts)
            _publish(self.root / "events" / ("%012d.json" % item["sequence"]), canonical(item))
            return item

    def view(self):
        records = self.events()
        attempts = {}
        branches = []
        for event in records:
            if event["kind"] == "operation.started":
                attempts[event["attempt_id"]] = {"operation_id": event["operation_id"],
                                                "start": event["id"], "status": "unresolved"}
            elif event["kind"] in TERMINALS:
                attempts[event["attempt_id"]].update(status=event["kind"].split(".")[1], terminal=event["id"])
            if event["kind"].startswith(("candidate.", "method.")) or event["kind"] in ("correction", "decision"):
                branches.append({key: event[key] for key in ("id", "kind", "parents", "bindings", "payload")})
        return {"schema_version": VERSION, "events": records, "attempts": attempts, "branches": branches,
                "notice": "Derived view; archive events and exact objects remain canonical."}

    def markdown(self):
        view = self.view()
        lines = ["# Research archive", "", view["notice"], ""]
        for event in view["events"]:
            lines.extend(["## " + event["id"], "", "- Kind: `" + event["kind"] + "`",
                          "- Event time: " + event["timestamp"] + " (" + event["timestamp_source"] + ")",
                          "- Recorded at: " + event["recorded_at"], "- Actor: " + event["actor"]["id"] + " / " + event["actor"]["role"],
                          "- Operation / attempt: `" + event["operation_id"] + "` / `" + event["attempt_id"] + "`",
                          "- Parents: " + ", ".join(event["parents"]), "", "```json",
                          json.dumps(event["payload"], ensure_ascii=False, indent=2), "```", ""])
        return "\n".join(lines)

    def export(self, destination, event_ids=None):
        """Export a directory bundle with exact parent closure; destination must not exist."""
        destination = _safe_path(destination)
        with self._lock():
            report = self._audit()
            if not report["ok"]:
                raise ArchiveError("cannot export damaged archive")
            records = self._records()[0]
            by_id = {event["id"]: event for event in records}
            selected = set(by_id) if event_ids is None else set(event_ids)
            if not selected <= set(by_id):
                raise ArchiveError("unknown selected event")
            pending = list(selected)
            while pending:
                for parent in by_id[pending.pop()]["parents"]:
                    if parent not in selected:
                        selected.add(parent)
                        pending.append(parent)
            included = [event for event in records if event["id"] in selected]
            omitted = list(self._scope()["omitted_events"])
            for event in records:
                if event["id"] not in selected:
                    commitment = {k: event[k] for k in ("id", "sequence", "sha256", "previous_sha256")}
                    commitment["delivery_key_sha256"] = sha(event["delivery_key"].encode("utf-8"))
                    omitted.append(commitment)
            refs = set().union(*[_refs(event) for event in included]) if included else set()
            files = {"archive.json": _read(self.root / "archive.json"),
                     "scope.json": canonical({"schema_version": VERSION, "selected_event_ids": sorted(selected),
                                               "omitted_events": sorted(omitted, key=lambda x: x["sequence"]),
                                               "omission_policy": "Unselected event bodies, unrelated objects, temporary files and derived views omitted."})}
            for event in included:
                rel = "events/%012d.json" % event["sequence"]
                files[rel] = _read(self.root / rel)
            for digest in sorted(refs):
                files["objects/" + digest] = self.get(digest)
            # Imported archives carry their exact interpretation materials forward.
            formats = {"archive_event.schema.json": Path(__file__).resolve().parent.parent / "schemas" / "archive_event.schema.json",
                       "ARCHIVE_FORMAT.md": Path(__file__).resolve().parent.parent / "docs" / "ARCHIVE_FORMAT.md",
                       "research_archive.py": Path(__file__)}
            optional_formats = {
                "research_timeline.py": Path(__file__).resolve().parent / "research_timeline.py",
                "philosophy_round.py": Path(__file__).resolve().parent / "philosophy_round.py",
                "candidate_birth.schema.json": Path(__file__).resolve().parent.parent / "schemas" / "candidate_birth.schema.json",
                "TIMELINE.md": Path(__file__).resolve().parent.parent / "docs" / "TIMELINE.md",
                "ROUND.md": Path(__file__).resolve().parent.parent / "workflows" / "ROUND.md",
            }
            for name, source in optional_formats.items():
                if source.exists() or (self.root / "format" / name).exists():
                    formats[name] = source
            for name, source in formats.items():
                carried = self.root / "format" / name
                files["format/" + name] = _read(carried if carried.exists() else source)
            manifest = {"bundle_version": VERSION, "archive_id": self._identity()["archive_id"],
                        "files": {name: {"sha256": sha(data), "size": len(data)} for name, data in sorted(files.items())}}
            destination.mkdir()  # exclusive; a failed bundle is inspectable, never clobbered
            for folder in ("objects", "events", "format"):
                (destination / folder).mkdir()
            for name, data in files.items():
                _publish(destination / name, data)
            _publish(destination / "manifest.json", canonical(manifest))  # bundle commit point
            _fsync_dir(destination.parent)
            return manifest

    @classmethod
    def import_bundle(cls, bundle, destination):
        bundle, destination = _safe_path(bundle), _safe_path(destination)
        if not bundle.is_dir():
            raise ArchiveError("bundle must be a directory")
        files = {}
        def visit(directory, prefix=""):
            for entry in sorted(directory.iterdir()):
                rel = prefix + entry.name
                mode = entry.lstat().st_mode
                if stat.S_ISDIR(mode):
                    if rel not in ("objects", "events", "format"):
                        raise ArchiveError("unexpected bundle directory: " + rel)
                    visit(entry, rel + "/")
                elif stat.S_ISREG(mode) and entry.lstat().st_nlink == 1:
                    files[rel] = _read(entry)
                else:
                    raise ArchiveError("bundle links/special files forbidden: " + rel)
        visit(bundle)
        try:
            manifest = json.loads(files.pop("manifest.json"))
        except (KeyError, ValueError) as exc:
            raise ArchiveError("missing/invalid bundle commit manifest") from exc
        if manifest.get("bundle_version") != VERSION or not isinstance(manifest.get("files"), dict):
            raise ArchiveError("unsupported bundle manifest")
        declared = manifest["files"]
        required = {"archive.json", "scope.json", "format/archive_event.schema.json", "format/ARCHIVE_FORMAT.md", "format/research_archive.py"}
        optional_formats = {"format/" + name for name in (
            "research_timeline.py", "philosophy_round.py", "candidate_birth.schema.json", "TIMELINE.md", "ROUND.md")}
        if set(declared) != set(files) or not required <= set(files):
            raise ArchiveError("bundle missing or undeclared files")
        for name, data in files.items():
            valid = name in required or name in optional_formats or re.fullmatch(r"events/[0-9]{12}\.json", name) or re.fullmatch(r"objects/[0-9a-f]{64}", name)
            if not valid or ".." in Path(name).parts or Path(name).is_absolute():
                raise ArchiveError("invalid/traversing bundle path")
            if declared[name] != {"sha256": sha(data), "size": len(data)}:
                raise ArchiveError("bundle hash/size mismatch: " + name)
        identity = json.loads(files["archive.json"])
        if identity.get("archive_id") != manifest.get("archive_id"):
            raise ArchiveError("bundle identity mismatch")
        # Validate all data in owned staging before touching the destination.
        # No imported script is executed: this runtime validates data only.
        with tempfile.TemporaryDirectory(prefix=".archive-import-", dir=str(destination.parent)) as temporary:
            staging = Path(temporary)
            for folder in ("objects", "events", "format"):
                (staging / folder).mkdir()
            for name, data in files.items():
                _publish(staging / name, data)
            _publish(staging / "bundle_manifest.json", canonical(manifest))
            result = cls(staging).validate()
            if not result["ok"]:
                raise ArchiveError("imported event semantics invalid: " + json.dumps(result["errors"]))
            if destination.exists():
                if not destination.is_dir() or any(destination.iterdir()):
                    raise ArchiveError("import requires empty destination")
            else:
                destination.mkdir()
            with cls(destination)._lock(initializing=True):
                if any(p.name != ".lock" for p in destination.iterdir()):
                    raise ArchiveError("import destination changed")
                for folder in ("objects", "events", "format"):
                    (destination / folder).mkdir()
                for name, data in files.items():
                    if name != "archive.json":
                        _publish(destination / name, data)
                _publish(destination / "bundle_manifest.json", canonical(manifest))
                _publish(destination / "archive.json", files["archive.json"])  # archive commit point
        _fsync_dir(destination.parent)
        return cls(destination)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="archive", help="archive directory, default: archive")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    put = sub.add_parser("put")
    put.add_argument("file", help="exact input bytes; '-' for stdin")
    append = sub.add_parser("append")
    append.add_argument("--event", required=True, help="JSON request file")
    append.add_argument("--delivery-key", required=True)
    sub.add_parser("validate")
    sub.add_parser("recover")
    view = sub.add_parser("view")
    view.add_argument("--format", choices=("json", "markdown"), default="markdown")
    export = sub.add_parser("export")
    export.add_argument("destination")
    export.add_argument("--event-id", action="append", default=None)
    imp = sub.add_parser("import")
    imp.add_argument("bundle")
    args = parser.parse_args(argv)
    try:
        archive = Archive(args.root)
        if args.command == "init":
            archive.init()
            result = archive._identity()
        elif args.command == "put":
            result = {"sha256": archive.put(sys.stdin.buffer.read() if args.file == "-" else _read(args.file))}
        elif args.command == "append":
            result = archive.append(_json(args.event), args.delivery_key)
        elif args.command in ("validate", "recover"):
            result = archive.validate()
        elif args.command == "view":
            if args.format == "markdown":
                print(archive.markdown())
                return 0
            result = archive.view()
        elif args.command == "export":
            result = archive.export(args.destination, args.event_id)
        else:
            result = Archive.import_bundle(args.bundle, args.root).validate()
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result.get("ok", True) else 1
    except (ArchiveError, OSError, ValueError, TypeError) as exc:
        print("archive: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
