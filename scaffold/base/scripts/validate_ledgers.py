#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
LEDGERS = [
    ROOT / "knowledge/results_ledger.yaml",
    ROOT / "knowledge/conjectures_ledger.yaml",
    ROOT / "knowledge/examples_ledger.yaml",
    ROOT / "knowledge/open_questions.yaml",
    ROOT / "knowledge/research_state.yaml",
    ROOT / "sources/manifests/source_registry.yaml",
]
VERIFIED = {"VERIFIED_INTERNAL", "VERIFIED_USING_CITED_RESULTS", "FORMALLY_VERIFIED"}


def load_object(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected an object")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_project_file(value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("missing project-relative path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe path {value!r}")
    path = ROOT / relative
    current = ROOT
    for part in relative.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError as exc:
            raise ValueError(f"missing file {value!r}") from exc
        if stat.S_ISLNK(mode):
            raise ValueError(f"symlink component in {value!r}")
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes project {value!r}") from exc
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"missing or unsafe file {value!r}")
    return path


def validate_sources(data: Dict[str, Any], errors: List[str]) -> None:
    sources = data.get("sources", [])
    if not isinstance(sources, list):
        errors.append("source_registry.sources must be an array")
        return
    seen_ids = set()
    seen_hashes = set()
    seen_original_paths = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"source[{index}] must be an object")
            continue
        source_id = source.get("source_id")
        digest = source.get("sha256")
        original_path = source.get("original_path")
        if not isinstance(source_id, str) or not source_id:
            errors.append(f"source[{index}] lacks source_id")
        elif source_id in seen_ids:
            errors.append(f"duplicate source_id: {source_id}")
        else:
            seen_ids.add(source_id)
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append(f"source[{index}] has invalid sha256")
        elif digest in seen_hashes:
            errors.append(f"duplicate source hash should have been deduplicated: {digest}")
        else:
            seen_hashes.add(digest)
        if source.get("trust_tier") not in {"A", "B", "C", "D"}:
            errors.append(f"source[{index}] has invalid trust_tier")
        if original_path in seen_original_paths:
            errors.append(f"two registry entries share original_path: {original_path}")
        else:
            seen_original_paths.add(original_path)
        try:
            original = safe_project_file(original_path)
            if isinstance(digest, str) and sha256(original) != digest:
                errors.append(f"source hash mismatch at {original_path}")
        except Exception as exc:
            errors.append(f"source[{index}] original error: {exc}")
        for key in ["extracted_text", "digest"]:
            try:
                safe_project_file(source.get(key))
            except Exception as exc:
                errors.append(f"source[{index}] {key} error: {exc}")


def validate_bootstrap_tiers(data: Dict[str, Any], errors: List[str]) -> None:
    profile_path = ROOT / "LAB_PROFILE.json"
    try:
        profile = load_object(profile_path)
    except Exception as exc:
        errors.append(f"cannot validate bootstrap tiers: {exc}")
        return
    materials = profile.get("bootstrap_materials", [])
    if not isinstance(materials, list):
        errors.append("LAB_PROFILE bootstrap_materials must be an array")
        return
    registered = {
        source.get("sha256"): source
        for source in data.get("sources", [])
        if isinstance(source, dict) and isinstance(source.get("sha256"), str)
    }
    path_bindings: Dict[str, tuple[str, str]] = {}
    for index, material in enumerate(materials):
        if not isinstance(material, dict):
            errors.append(f"bootstrap_materials[{index}] must be an object")
            continue
        digest = material.get("sha256")
        expected_tier = material.get("trust_tier")
        stored_name = material.get("stored_name")
        if (
            not isinstance(digest, str)
            or expected_tier not in {"A", "B", "C", "D"}
            or not isinstance(stored_name, str)
        ):
            errors.append(f"bootstrap_materials[{index}] has invalid path, hash, or tier")
            continue
        path_bindings[stored_name] = (digest, expected_tier)
        source = registered.get(digest)
        if source is not None and source.get("trust_tier") != expected_tier:
            errors.append(
                f"bootstrap tier mismatch for {digest}: "
                f"profile={expected_tier}, registry={source.get('trust_tier')}"
            )
    for source in data.get("sources", []):
        if not isinstance(source, dict):
            continue
        inbox_path = source.get("inbox_path")
        if inbox_path not in path_bindings:
            continue
        expected_digest, expected_tier = path_bindings[inbox_path]
        if source.get("sha256") != expected_digest:
            errors.append(
                f"bootstrap path hash mismatch for {inbox_path}: "
                f"profile={expected_digest}, registry={source.get('sha256')}"
            )
        if source.get("trust_tier") != expected_tier:
            errors.append(
                f"bootstrap path tier mismatch for {inbox_path}: "
                f"profile={expected_tier}, registry={source.get('trust_tier')}"
            )


def validate_research_state(data: Dict[str, Any], errors: List[str]) -> None:
    active_ids = data.get("active_problem_ids", [])
    if not isinstance(active_ids, list) or not all(isinstance(item, str) for item in active_ids):
        errors.append("research_state.active_problem_ids must be an array of strings")
        return
    if len(active_ids) != len(set(active_ids)):
        errors.append("research_state.active_problem_ids contains duplicates")
    active_root = ROOT / "problems/active"
    actual = sorted(path.name for path in active_root.iterdir() if path.is_dir() and not path.name.startswith("."))
    declared = sorted(active_ids)
    if actual != declared:
        errors.append(f"active problem state mismatch: declared={declared}, actual={actual}")


def main() -> int:
    errors: List[str] = []
    loaded: Dict[Path, Dict[str, Any]] = {}
    for path in LEDGERS:
        try:
            loaded[path] = load_object(path)
            print(f"OK parse {path.relative_to(ROOT)}")
        except Exception as exc:
            errors.append(f"cannot parse {path.relative_to(ROOT)}: {exc}")
    results_path = ROOT / "knowledge/results_ledger.yaml"
    if results_path in loaded:
        data = loaded[results_path]
        allowed = set(data.get("allowed_statuses", []))
        for result in data.get("results", []):
            if not isinstance(result, dict):
                errors.append("result entry must be an object")
                continue
            status = result.get("status")
            if status not in allowed:
                errors.append(f"result {result.get('id')}: invalid status {status}")
            if status in VERIFIED and not result.get("verifier_report"):
                errors.append(f"result {result.get('id')}: verified status requires verifier_report")
    source_path = ROOT / "sources/manifests/source_registry.yaml"
    if source_path in loaded:
        validate_sources(loaded[source_path], errors)
        validate_bootstrap_tiers(loaded[source_path], errors)
    state_path = ROOT / "knowledge/research_state.yaml"
    if state_path in loaded:
        validate_research_state(loaded[state_path], errors)
    for error in errors:
        print(f"FAIL {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
