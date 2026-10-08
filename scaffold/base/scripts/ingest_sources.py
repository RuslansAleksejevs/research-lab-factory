#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "sources/manifests/source_registry.yaml"
LOG = ROOT / "sources/manifests/ingestion_log.jsonl"

def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "source"

def load_registry() -> dict:
    if not REGISTRY.exists():
        return {"schema_version": 1, "sources": []}
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def load_bootstrap_tier_maps() -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    profile_path = ROOT / "LAB_PROFILE.json"
    if not profile_path.is_file():
        return {}, {}
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    materials = profile.get("bootstrap_materials", []) if isinstance(profile, dict) else []
    if not isinstance(materials, list):
        raise RuntimeError("LAB_PROFILE bootstrap_materials must be an array")
    by_path: dict[str, tuple[str, str]] = {}
    by_hash: dict[str, str] = {}
    for index, item in enumerate(materials):
        if not isinstance(item, dict):
            raise RuntimeError(f"LAB_PROFILE bootstrap_materials[{index}] must be an object")
        stored = item.get("stored_name")
        digest = item.get("sha256")
        tier = item.get("trust_tier")
        if not isinstance(stored, str) or not isinstance(digest, str) or tier not in {"A", "B", "C", "D"}:
            raise RuntimeError(f"LAB_PROFILE bootstrap_materials[{index}] is malformed")
        binding = (digest, tier)
        if stored in by_path and by_path[stored] != binding:
            raise RuntimeError(f"Conflicting bootstrap tiers for {stored}")
        if digest in by_hash and by_hash[digest] != tier:
            raise RuntimeError(f"Conflicting bootstrap tiers for SHA-256 {digest}")
        by_path[stored] = binding
        by_hash[digest] = tier
    return by_path, by_hash


def effective_trust_tier(
    path: Path,
    requested_tier: str,
    by_path: dict[str, tuple[str, str]],
    by_hash: dict[str, str],
) -> tuple[str, str, str]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"Only regular non-symlink source files may be classified: {path}")
    try:
        relative = path.relative_to(ROOT).as_posix()
    except ValueError:
        relative = ""
    digest = sha256(path)
    if relative in by_path:
        expected_digest, path_tier = by_path[relative]
        if digest != expected_digest:
            raise RuntimeError(
                f"Bootstrap input digest mismatch at {relative}: "
                f"profile={expected_digest}, current={digest}"
            )
        hash_tier = by_hash.get(digest)
        if hash_tier != path_tier:
            raise RuntimeError(f"Bootstrap path/hash tier disagreement at {relative}")
        return path_tier, "LAB_PROFILE stored_name+sha256", digest
    if digest in by_hash:
        return by_hash[digest], "LAB_PROFILE sha256", digest
    return requested_tier, "command default/override", digest

def save_registry(data: dict) -> None:
    handle, temporary_name = tempfile.mkstemp(
        prefix=".source-registry-",
        suffix=".json",
        dir=str(REGISTRY.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            output.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        temporary.replace(REGISTRY)
    finally:
        if temporary.exists():
            temporary.unlink()

def append_log(record: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

def extract_text(source: Path, source_id: str) -> tuple[str, str]:
    out_dir = ROOT / "sources/extracted/text_by_page"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{source_id}.md"
    suffix = source.suffix.lower()
    if suffix in {".md", ".txt", ".tex"}:
        text = source.read_text(encoding="utf-8", errors="replace")
        out_path.write_text(f"# Extracted Text: {source.name}\n\n## Page 1\n\n{text}\n", encoding="utf-8")
        return str(out_path.relative_to(ROOT)), "text-file"
    if suffix == ".pdf" and shutil.which("pdftotext"):
        result = subprocess.run(["pdftotext", "-layout", str(source), "-"], text=True, capture_output=True)
        if result.returncode == 0:
            pages = result.stdout.split("\f")
            lines = [f"# Extracted Text: {source.name}", ""]
            for idx, page in enumerate(pages, start=1):
                if page.strip():
                    lines.append(f"## PDF page {idx}")
                    lines.append("")
                    lines.append(page.rstrip())
                    lines.append("")
            out_path.write_text("\n".join(lines), encoding="utf-8")
            return str(out_path.relative_to(ROOT)), "pdftotext"
    note = (
        f"# Extracted Text: {source.name}\n\n"
        "Text extraction was not available in this environment. Preserve the original and rerun ingestion "
        "after installing `pdftotext`, `pypdf`, or another extraction backend. OCR was not attempted.\n"
    )
    out_path.write_text(note, encoding="utf-8")
    return str(out_path.relative_to(ROOT)), "unavailable"

def make_digest(source: Path, source_id: str, digest_path: Path, file_hash: str, trust_tier: str, extraction_path: str, extraction_method: str) -> None:
    digest_path.parent.mkdir(parents=True, exist_ok=True)
    digest = f'''# Source Digest: {source.name}

- Source ID: `{source_id}`
- Filename: `{source.name}`
- Trust tier: `{trust_tier}`
- SHA-256: `{file_hash}`
- Page convention: PDF page numbers until printed numbering is checked.
- Extraction: `{extraction_method}` via `{extraction_path}`
- Ingested: `{now()}`

## Purpose in project

To be filled after mathematical inspection.

## Section-by-section summary

Pending source reading.

## Results and definitions

Pending source reading.

## Notation, coefficients, and twists

Pending source reading.

## Project-relevant claims

Pending source reading.

## Possible gaps or conflicts

Pending source reading.
'''
    digest_path.write_text(digest, encoding="utf-8")

def ingest_file(
    path: Path,
    scope: str,
    trust_tier: str,
    dry_run: bool,
    expected_sha256: Optional[str] = None,
) -> dict:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"Only regular non-symlink source files may be ingested: {path}")
    file_hash = sha256(path)
    if expected_sha256 is not None and file_hash != expected_sha256:
        raise RuntimeError(
            f"Source changed after trust-tier classification: expected {expected_sha256}, got {file_hash}"
        )
    registry = load_registry()
    for existing in registry.get("sources", []):
        if existing.get("sha256") == file_hash:
            existing_tier = existing.get("trust_tier")
            return {
                "status": "duplicate",
                "filename": path.name,
                "source_id": existing.get("source_id"),
                "sha256": file_hash,
                "existing_trust_tier": existing_tier,
                "requested_trust_tier": trust_tier,
                "tier_conflict": existing_tier != trust_tier,
            }
    source_id = f"{slugify(path.stem)}-{file_hash[:12]}"
    originals_dir = ROOT / "sources/originals" / scope / source_id
    target = originals_dir / path.name
    digest_path = ROOT / "sources/digests" / f"{source_id}.md"
    if dry_run:
        return {"status": "would_ingest", "filename": path.name, "source_id": source_id, "sha256": file_hash}
    originals_dir.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_file() or sha256(target) != file_hash:
            raise RuntimeError(f"Content-addressed original path already exists unexpectedly: {target}")
    else:
        shutil.copy2(path, target, follow_symlinks=False)
    if sha256(target) != file_hash:
        raise RuntimeError(f"Copied original failed SHA-256 verification: {target}")
    extraction_path, extraction_method = extract_text(target, source_id)
    make_digest(path, source_id, digest_path, file_hash, trust_tier, extraction_path, extraction_method)
    record = {
        "source_id": source_id,
        "filename": path.name,
        "scope": scope,
        "trust_tier": trust_tier,
        "sha256": file_hash,
        "inbox_path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else path.name,
        "original_path": str(target.relative_to(ROOT)),
        "extracted_text": extraction_path,
        "digest": str(digest_path.relative_to(ROOT)),
        "ingested_at": now(),
    }
    registry.setdefault("sources", []).append(record)
    save_registry(registry)
    append_log({"event": "ingested", **record})
    return {"status": "ingested", **record}

def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest project sources while preserving inbox copies.")
    parser.add_argument("inbox", nargs="?", default="00_INBOX_TO_ANALYZE/priority")
    parser.add_argument("--scope", choices=["core", "external"], default="core")
    parser.add_argument("--trust-tier", choices=["A", "B", "C", "D"], default="C")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    inbox = (ROOT / args.inbox).resolve()
    if not inbox.exists():
        print(f"Inbox does not exist: {inbox}")
        return 1
    ignored_names = {"README.md", ".DS_Store"}
    files = [
        p for p in sorted(inbox.iterdir())
        if p.is_file() and not p.name.startswith(".") and p.name not in ignored_names
    ]
    if not files:
        print(f"No files to ingest in {inbox}")
        return 0
    try:
        by_path, by_hash = load_bootstrap_tier_maps()
    except Exception as exc:
        print(f"ERROR: cannot load bootstrap trust tiers: {exc}")
        return 1
    ok = True
    for item in files:
        try:
            effective_tier, tier_source, classified_digest = effective_trust_tier(
                item,
                args.trust_tier,
                by_path,
                by_hash,
            )
            result = ingest_file(
                item,
                args.scope,
                effective_tier,
                args.dry_run,
                expected_sha256=classified_digest,
            )
        except Exception as exc:
            print(json.dumps({"status": "error", "filename": item.name, "error": str(exc)}, ensure_ascii=False))
            ok = False
            continue
        result["tier_source"] = tier_source
        result["command_trust_tier"] = args.trust_tier
        result["effective_trust_tier"] = effective_tier
        if result.get("tier_conflict"):
            ok = False
        print(json.dumps(result, ensure_ascii=False))
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
