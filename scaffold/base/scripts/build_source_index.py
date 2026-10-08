#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "sources/manifests/source_registry.yaml"

def main() -> int:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    sources = data.get("sources", [])
    lines = ["# Source Map", "", f"Updated: {datetime.now(timezone.utc).replace(microsecond=0).isoformat()}", ""]
    if not sources:
        lines.append("No sources ingested yet.")
    else:
        lines.extend(["| Source ID | Filename | Tier | Original | Digest |", "| --- | --- | --- | --- | --- |"])
        for src in sources:
            lines.append(f"| `{src.get('source_id')}` | {src.get('filename')} | {src.get('trust_tier')} | `{src.get('original_path')}` | `{src.get('digest')}` |")
    (ROOT / "knowledge/source_map.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ROOT / "sources/manifests/source_index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Updated knowledge/source_map.md and sources/manifests/source_index.md")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
