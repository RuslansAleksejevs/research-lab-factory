"""Exact-target, opt-in installation of a reviewed local bootstrap payload.

This is not a module registry or an executable hook interface. Closed protocols
have server-owned commands and separate isolated namespaces. Ordinary
generation does not even read the local registry when the option is absent.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


REGISTRY = "profiles/local_layers/registry.json"
RECEIPT = ".lab/local_bootstrap_layer.json"
PROTOCOLS = {
    "course-notes.v1": ("course", "course/course.py", "course"),
    "ai-research.v1": ("ai_safety", "ai_safety/lab.py", "research/ai_safety"),
}
ROOT_DOCUMENTS = {"START_HERE.md", "SETUP_REPORT.md"}
IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,127}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
RESERVED_COMPONENTS = {"agents.md", "agents.override.md", "user_preferences.md", "lab_profile.json"}
MAX_CONTROL_BYTES = 2 * 1024 * 1024
MAX_AGENTS_BYTES = 32768


class LocalLayerError(RuntimeError):
    pass


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def object_keys(value: Any, keys: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise LocalLayerError(f"{label} must contain exactly {sorted(keys)}")
    return value


def parse(content: bytes, label: str) -> dict:
    if len(content) > MAX_CONTROL_BYTES:
        raise LocalLayerError(f"Oversized {label}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite constant {value}")

    try:
        result = json.loads(content.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=reject_constant)
    except (UnicodeError, ValueError) as exc:
        raise LocalLayerError(f"Invalid {label}: {exc}") from exc
    if not isinstance(result, dict):
        raise LocalLayerError(f"{label} must be an object")
    return result


def relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 240:
        raise LocalLayerError(f"Invalid {label}")
    parts = value.split("/")
    if any(not COMPONENT.fullmatch(part) or part in {".", ".."} for part in parts):
        raise LocalLayerError(f"Unsafe {label}: {value!r}")
    return value


def checked_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise LocalLayerError(f"Invalid SHA-256 for {label}")
    return value


def validate_option(option: Any) -> None:
    object_keys(option, {"id", "expected_sha256"}, "bootstrap.local_layer")
    if not isinstance(option["id"], str) or not IDENTIFIER.fullmatch(option["id"]):
        raise LocalLayerError("bootstrap.local_layer.id is invalid")
    checked_digest(option["expected_sha256"], "bootstrap.local_layer.expected_sha256")


def folded(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def tree_files(root: Path) -> set[str]:
    """No symlinks, special files, or Unicode/case aliases in the whole payload."""
    if not stat.S_ISDIR(root.lstat().st_mode):
        raise LocalLayerError(f"Local layer payload must be a real directory: {root}")
    seen: set[str] = set()
    files: set[str] = set()
    for current, directories, names in os.walk(root, followlinks=False):
        for name in directories + names:
            path = Path(current) / name
            relative = path.relative_to(root).as_posix()
            key = folded(relative)
            if key in seen:
                raise LocalLayerError(f"Casefold collision in local payload: {relative}")
            seen.add(key)
            mode = path.lstat().st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise LocalLayerError(f"Symlink or special file in local payload: {relative}")
            if stat.S_ISREG(mode):
                files.add(relative)
    return files


@dataclass
class BoundLayer:
    root: Path
    reader: Callable[[Path, str], bytes]
    manifest: dict
    snapshots: dict[str, bytes]
    manifest_path: str

    @property
    def namespace(self) -> str:
        return PROTOCOLS[self.manifest["protocol"]][0]

    @property
    def helper(self) -> str:
        return PROTOCOLS[self.manifest["protocol"]][1]

    @property
    def data_namespace(self) -> str:
        return PROTOCOLS[self.manifest["protocol"]][2]

    def summary(self) -> dict:
        return {
            "id": self.manifest["id"],
            "directory_name": self.manifest["directory_name"],
            "protocol": self.manifest["protocol"],
            "manifest_sha256": sha256(self.snapshots[self.manifest_path]),
            "registry_sha256": sha256(self.snapshots[REGISTRY]),
            "files": [dict(item) for item in self.manifest["files"]],
            "agent_instructions": dict(self.manifest["agent_instructions"]),
            "validation_commands": [
                ["python3", self.helper, action]
                for action in ("self-test", "build", "validate")
            ],
        }

    @property
    def payload_relative(self) -> str:
        return str(Path(self.manifest_path).parent / "payload")

    def verify_sources(self) -> None:
        expected = {
            item["source"] for item in self.manifest["files"]
        } | {self.manifest["agent_instructions"]["source"]}
        if tree_files(self.root / self.payload_relative) != expected:
            raise LocalLayerError("Local layer payload file inventory changed")
        for relative, original in self.snapshots.items():
            if self.reader(self.root / relative, "local layer bound source") != original:
                raise LocalLayerError(f"Local layer source changed after review: {relative}")


def load_layer(request: dict, root: Path, reader: Callable[[Path, str], bytes]) -> BoundLayer | None:
    if "local_layer" not in request["bootstrap"]:
        return None
    option = request["bootstrap"]["local_layer"]
    validate_option(option)
    snapshots: dict[str, bytes] = {}

    def read(relative: str) -> bytes:
        label = "local bootstrap layer"
        if relative == REGISTRY:
            label = ("local bootstrap layer registry (bootstrap.local_layer requires a "
                     "separately installed private add-on; omit this option in the public kit)")
        content = reader(root / relative, label)
        snapshots[relative] = content
        return content

    registry = object_keys(parse(read(REGISTRY), REGISTRY), {"schema_version", "layers"}, "local layer registry")
    if type(registry["schema_version"]) is not int or registry["schema_version"] != 1 or not isinstance(registry["layers"], list):
        raise LocalLayerError("Unsupported local layer registry")
    ids: set[str] = set()
    targets: set[str] = set()
    selected = None
    for entry in registry["layers"]:
        object_keys(entry, {"id", "directory_name", "manifest"}, "local layer registry entry")
        identifier = entry["id"]
        directory = entry["directory_name"]
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier) or identifier in ids:
            raise LocalLayerError("Invalid or duplicate local layer registry id")
        if not isinstance(directory, str) or not directory or folded(directory) in targets:
            raise LocalLayerError("Invalid or duplicate local layer target")
        ids.add(identifier)
        targets.add(folded(directory))
        expected_path = f"profiles/local_layers/{identifier}/manifest.json"
        if entry["manifest"] != expected_path:
            raise LocalLayerError("Local layer registry manifest is not the fixed bundle path")
        if identifier == option["id"]:
            selected = entry
    if selected is None:
        raise LocalLayerError("Requested local bootstrap layer is not registered")
    if request["lab"]["directory_name"] != selected["directory_name"]:
        raise LocalLayerError("Local bootstrap layer is authorized only for its exact registered destination")
    manifest_path = selected["manifest"]
    content = read(manifest_path)
    if sha256(content) != option["expected_sha256"]:
        raise LocalLayerError("Local layer manifest differs from request's reviewed SHA-256")
    manifest = object_keys(parse(content, manifest_path), {
        "schema_version", "id", "directory_name", "protocol", "files", "agent_instructions",
    }, "local layer manifest")
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
            or manifest["id"] != selected["id"] or manifest["directory_name"] != selected["directory_name"]
            or not isinstance(manifest["protocol"], str)
            or manifest["protocol"] not in PROTOCOLS):
        raise LocalLayerError("Local layer manifest identity, destination, or protocol mismatch")
    namespace, helper, data_namespace = PROTOCOLS[manifest["protocol"]]
    if not isinstance(manifest["files"], list) or not manifest["files"] or len(manifest["files"]) > 200:
        raise LocalLayerError("Local layer files must be a bounded non-empty array")
    sources: set[str] = set()
    destinations: set[str] = set()
    payload = str(Path(manifest_path).parent / "payload")
    for entry in manifest["files"]:
        object_keys(entry, {"source", "destination", "ownership", "sha256"}, "local layer file")
        source = relative_path(entry["source"], "local layer source")
        destination = relative_path(entry["destination"], "local layer destination")
        if any(folded(part) in RESERVED_COMPONENTS for part in destination.split("/")):
            raise LocalLayerError(f"Reserved local layer destination: {destination}")
        if not (destination.startswith(namespace + "/")
                or destination.startswith(data_namespace + "/") or destination in ROOT_DOCUMENTS):
            raise LocalLayerError(f"Local layer destination is outside its isolated namespace: {destination}")
        if entry["ownership"] not in {"lab-owned", "generated-once"}:
            raise LocalLayerError("Local layer ownership must be lab-owned or generated-once")
        if (namespace != data_namespace and destination.startswith(namespace + "/")
                and entry["ownership"] != "generated-once"):
            raise LocalLayerError("Local layer runtime assets must be generated-once; live records belong in the data namespace")
        if (namespace != data_namespace and destination.startswith(data_namespace + "/")
                and entry["ownership"] != "lab-owned"):
            raise LocalLayerError("Local layer data namespace must be lab-owned; protected assets belong in the runtime namespace")
        if folded(source) in sources or folded(destination) in destinations:
            raise LocalLayerError("Duplicate or casefold-colliding local layer file")
        sources.add(folded(source))
        destinations.add(folded(destination))
        digest = checked_digest(entry["sha256"], source)
        if sha256(read(f"{payload}/{source}")) != digest:
            raise LocalLayerError(f"Local layer payload digest mismatch: {source}")
    for path in destinations:
        if any(parent in destinations for parent in (str(p) for p in Path(path).parents) if parent != "."):
            raise LocalLayerError("A local layer file is an ancestor of another file")
    helpers = [item for item in manifest["files"] if item["destination"] == helper]
    if len(helpers) != 1 or helpers[0]["ownership"] != "generated-once":
        raise LocalLayerError("The fixed protocol helper must be an explicit generated-once file")
    fragment = object_keys(manifest["agent_instructions"], {"source", "sha256"}, "local layer instructions")
    source = relative_path(fragment["source"], "local layer instruction source")
    if folded(source) in sources:
        raise LocalLayerError("The instruction fragment must be a separate payload file")
    fragment_bytes = read(f"{payload}/{source}")
    if sha256(fragment_bytes) != checked_digest(fragment["sha256"], "local layer instructions"):
        raise LocalLayerError("Local layer instruction digest mismatch")
    try:
        text = fragment_bytes.decode("utf-8")
    except UnicodeError as exc:
        raise LocalLayerError("Local layer instructions must be UTF-8") from exc
    if not text.strip() or len(fragment_bytes) > 65536 or "<!-- local-bootstrap-layer:" in text or "\x00" in text:
        raise LocalLayerError("Local layer instruction fragment is empty, oversized, or contains a reserved marker")
    layer = BoundLayer(root, reader, manifest, snapshots, manifest_path)
    layer.verify_sources()
    return layer


def stage_path(stage: Path, relative: str, *, absent: bool = False) -> Path:
    current = stage
    for part in Path(relative).parts:
        if not stat.S_ISDIR(current.lstat().st_mode):
            raise LocalLayerError(f"Unsafe local layer destination parent: {current}")
        matches = [p for p in current.iterdir() if folded(p.name) == folded(part)]
        if matches and (len(matches) != 1 or matches[0].name != part):
            raise LocalLayerError(f"Casefold collision at local layer destination: {relative}")
        current = current / part
        if current.exists() or current.is_symlink():
            mode = current.lstat().st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise LocalLayerError(f"Symlink or special local layer destination: {relative}")
        elif current != stage / relative:
            current.mkdir(mode=0o755)
    if absent and (current.exists() or current.is_symlink()):
        raise LocalLayerError(f"Local layer refuses to overwrite existing destination: {relative}")
    return current


def write_new(stage: Path, relative: str, content: bytes) -> None:
    path = stage_path(stage, relative, absent=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    with os.fdopen(descriptor, "wb") as handle:
        os.fchmod(handle.fileno(), 0o644)
        handle.write(content)
    if path.read_bytes() != content:
        raise LocalLayerError(f"Local layer copy verification failed: {relative}")


def install_layer(stage: Path, layer: BoundLayer) -> dict:
    layer.verify_sources()
    # All destinations are checked before the first copied file. A pre-existing
    # namespace tree is a collision, even when a proposed leaf does not yet exist.
    stage_path(stage, layer.namespace, absent=True)
    if layer.data_namespace != layer.namespace:
        stage_path(stage, layer.data_namespace, absent=True)
    for item in layer.manifest["files"]:
        stage_path(stage, item["destination"], absent=True)
    stage_path(stage, RECEIPT, absent=True)
    agents = stage_path(stage, "AGENTS.md")
    if not agents.is_file():
        raise LocalLayerError("Generated AGENTS.md is missing")
    before = agents.read_bytes()
    marker = f"<!-- local-bootstrap-layer:{layer.manifest['id']} -->".encode()
    if b"<!-- local-bootstrap-layer:" in before:
        raise LocalLayerError("Generated AGENTS.md already has a local layer")
    fragment = layer.snapshots[f"{layer.payload_relative}/{layer.manifest['agent_instructions']['source']}"]
    after = before + b"\n\n" + marker + b"\n" + fragment + b"\n<!-- /local-bootstrap-layer -->\n"
    if len(after) > MAX_AGENTS_BYTES:
        raise LocalLayerError("Local layer append exceeds the 32768-byte root instruction budget")
    for item in layer.manifest["files"]:
        write_new(stage, item["destination"], layer.snapshots[f"{layer.payload_relative}/{item['source']}"])
    agents.write_bytes(after)
    if agents.read_bytes() != after:
        raise LocalLayerError("Local layer AGENTS append verification failed")
    receipt = {
        "schema_version": 1,
        **layer.summary(),
        "agents_append": {"path": "AGENTS.md", "before_sha256": sha256(before), "after_sha256": sha256(after)},
        "validation": [],
        "provenance_scope": "Reviewed local bootstrap layer; no mathematical claim established.",
    }
    write_new(stage, RECEIPT, (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
    layer.verify_sources()
    return receipt


def extend_ownership(ownership: dict, layer: BoundLayer | None) -> None:
    if layer is None:
        return
    generated = ownership.setdefault("generated_once_paths", [])
    prefixes = ownership.setdefault("lab_owned_prefixes", [])
    for item in layer.manifest["files"]:
        if item["ownership"] == "generated-once" and item["destination"] not in generated:
            generated.append(item["destination"])
        elif item["ownership"] == "lab-owned" and not item["destination"].startswith(layer.data_namespace + "/"):
            prefixes.append(item["destination"])
    if RECEIPT not in generated:
        generated.append(RECEIPT)
    if layer.data_namespace + "/" not in prefixes:
        prefixes.append(layer.data_namespace + "/")


def verify_install(stage: Path, layer: BoundLayer, initial: bool = False) -> None:
    """Re-bind staged executable/instructions immediately before execution."""
    for item in layer.manifest["files"]:
        if initial or item["ownership"] == "generated-once":
            path = stage_path(stage, item["destination"])
            if not path.is_file() or sha256(path.read_bytes()) != item["sha256"]:
                raise LocalLayerError(f"Installed local layer payload changed: {item['destination']}")
            if stat.S_IMODE(path.lstat().st_mode) != 0o644:
                raise LocalLayerError(f"Installed local layer payload mode changed: {item['destination']}")
    receipt = parse(stage_path(stage, RECEIPT).read_bytes(), RECEIPT)
    summary = layer.summary()
    if any(receipt.get(key) != value for key, value in summary.items()):
        raise LocalLayerError("Installed local layer receipt differs from bound source")
    agents = stage_path(stage, "AGENTS.md").read_bytes()
    fragment = layer.snapshots[f"{layer.payload_relative}/{layer.manifest['agent_instructions']['source']}"]
    suffix = (f"\n\n<!-- local-bootstrap-layer:{layer.manifest['id']} -->\n".encode()
              + fragment + b"\n<!-- /local-bootstrap-layer -->\n")
    binding = receipt.get("agents_append", {})
    if (not agents.endswith(suffix) or sha256(agents) != binding.get("after_sha256")
            or sha256(agents[:-len(suffix)]) != binding.get("before_sha256")):
        raise LocalLayerError("Installed local layer instruction append changed")


def protected_snapshot(stage: Path, layer: BoundLayer) -> dict[str, tuple]:
    generated = {item["destination"] for item in layer.manifest["files"] if item["ownership"] == "generated-once"}
    mutable_root = {item["destination"] for item in layer.manifest["files"] if item["ownership"] == "lab-owned"}
    result = {}
    for relative in tree_files(stage):
        if relative in generated or not (relative.startswith(layer.data_namespace + "/") or relative in mutable_root):
            path = stage / relative
            result[relative] = (sha256(path.read_bytes()), stat.S_IMODE(path.lstat().st_mode))
    protected_directories = {layer.namespace, layer.data_namespace}
    for relative in generated:
        protected_directories.update(str(path) for path in Path(relative).parents if str(path) != ".")
    for path in stage.rglob("*"):
        relative = path.relative_to(stage).as_posix()
        if path.is_dir() and (relative in protected_directories or not relative.startswith(layer.data_namespace + "/")):
            result[relative + "/"] = (stat.S_IMODE(path.lstat().st_mode),)
    return result


def run_validation(stage: Path, layer: BoundLayer, gate: Callable) -> list[dict]:
    layer.verify_sources()
    verify_install(stage, layer, initial=True)
    before = protected_snapshot(stage, layer)
    results = []
    for action in ("self-test", "build", "validate"):
        verify_install(stage, layer)
        results.append(gate(stage, f"local-layer-{action}", [sys.executable, layer.helper, action]))
        if protected_snapshot(stage, layer) != before:
            raise LocalLayerError(f"Local layer {action} changed protected staged files")
    receipt_path = stage_path(stage, RECEIPT)
    receipt = parse(receipt_path.read_bytes(), RECEIPT)
    receipt["validation"] = results
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    layer.verify_sources()
    return results
