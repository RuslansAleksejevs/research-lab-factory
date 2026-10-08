#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from laboratory_survey import build_snapshot
from research_memory import validate_memory


ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", "__pycache__"}


def load_object(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def load_scalar_field(path: Path, key: str, default: str) -> str:
    """Read one top-level scalar from JSON or the lab's flat YAML ledgers.

    The generated ledgers use JSON-compatible YAML, while adopted and older
    laboratories may use ordinary ``key: value`` YAML.  Resume generation only
    needs two navigation fields, so it deliberately does not attempt to parse
    arbitrary YAML or reinterpret the rest of a research record.
    """

    text = path.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = None
    if isinstance(value, dict):
        result = value.get(key)
        return str(result) if result not in {None, ""} else default

    prefix = key + ":"
    for line in text.splitlines():
        if line.startswith(prefix):
            result = line[len(prefix) :].strip()
            if not result:
                return default
            if len(result) >= 2 and result[0] == result[-1] and result[0] in {"'", '"'}:
                result = result[1:-1]
            return result or default
    return default


def active_rows(state: Dict[str, Any]) -> List[str]:
    rows: List[str] = []
    for problem_id in state.get("active_problem_ids", []):
        root = ROOT / "problems/active" / problem_id
        status_path = root / "status.yaml"
        context_path = root / "context_envelope.md"
        proof_state_path = root / "proof_search_state.yaml"
        status = "UNKNOWN"
        profile = "UNSET"
        envelope = "UNKNOWN"
        if status_path.is_file():
            status = load_scalar_field(status_path, "status", "UNKNOWN")
        if proof_state_path.is_file():
            profile = load_scalar_field(
                proof_state_path, "orchestration_profile", "UNSET"
            )
        if context_path.is_file():
            for line in context_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("Status:"):
                    envelope = line.split(":", 1)[1].strip().strip("`.")
                    break
        rows.append(f"- `{problem_id}` — status `{status}`, envelope `{envelope}`, orchestration `{profile}`.")
    return rows


def laboratory_survey_status() -> str:
    survey_state = load_object(ROOT / "knowledge/laboratory_survey_state.json")
    survey_id = survey_state.get("latest_survey_id")
    basis = survey_state.get("basis_sha256")
    if not isinstance(survey_id, str) or not isinstance(basis, str) or not basis:
        return "`NONE` — no stable whole-laboratory survey has been saved"
    try:
        current = build_snapshot(ROOT).get("inventory_sha256")
    except Exception as exc:
        return f"`UNKNOWN` — freshness check failed: {exc}"
    freshness = "FRESH" if current == basis else "STALE"
    return (
        f"`{freshness}` — `{survey_id}`; latest overview: "
        "`knowledge/laboratory_overview.md`"
    )


def durable_checkpoint_status(state: Dict[str, Any]) -> str:
    """Return the latest validated memory record, never an unbound pointer."""

    try:
        index = validate_memory()
    except Exception as exc:
        # Strict validation includes canonical records and linked evidence, so
        # a failed check does not establish that the disposable index is wrong.
        detail = " ".join(str(exc).split()).replace("`", "'")
        detail = (detail[:399] + "…") if len(detail) > 400 else detail
        status = (
            "`MEMORY_CHECK_FAILED` — run `python3 -I -B scripts/research_memory.py validate`; "
            + (detail or type(exc).__name__)
        )
        legacy = state.get("last_checkpoint")
        if isinstance(legacy, str) and legacy:
            status += f"; legacy unverified pointer: `{legacy}`"
        return status

    entries = index.get("entries", [])
    if not entries:
        return "`NONE` — no Durable Research Memory checkpoint has been recorded"
    latest = entries[-1]
    research_date = latest.get("research_date")
    if isinstance(research_date, dict):
        date_display = f"{research_date.get('start')} through {research_date.get('end')}"
    else:
        date_display = str(research_date)
    return (
        f"`{latest.get('checkpoint_id')}` — `{latest.get('outcome_status')}`, "
        f"research date `{date_display}`, `{latest.get('path')}`"
    )


def build_resume() -> str:
    profile = load_object(ROOT / "LAB_PROFILE.json")
    state = load_object(ROOT / "knowledge/research_state.yaml")
    registry = load_object(ROOT / "sources/manifests/source_registry.yaml")
    active = active_rows(state)
    priorities = state.get("current_priorities", [])
    checkpoint = durable_checkpoint_status(state)
    if active:
        blocker = "Inspect each active dossier for its highest open gap and closure gate."
        next_action = priorities[0] if isinstance(priorities, list) and priorities else "Review the active dossier state and record one discriminating next action."
    else:
        blocker = "No active problem dossier is recorded."
        next_action = priorities[0] if isinstance(priorities, list) and priorities else "Formulate or activate the next exact target."
    lines = [
        "# Resume Dashboard",
        "",
        f"- Laboratory: {profile.get('lab', {}).get('title', 'Unknown')}",
        f"- Profile status: `{profile.get('profile_status', 'UNKNOWN')}`",
        f"- Latest durable-memory record: {checkpoint}",
        f"- Ingested sources: `{len(registry.get('sources', []))}`",
        f"- Deep laboratory survey: {laboratory_survey_status()}",
        f"- Current blocker: {blocker}",
        f"- Next action: {next_action}",
        "",
        "## Active dossiers",
        "",
    ]
    lines.extend(active or ["- No active problem dossier."])
    lines.extend(["", "## Current priorities", ""])
    lines.extend([f"- {item}" for item in priorities] if isinstance(priorities, list) and priorities else ["- None recorded."])
    lines.extend(["", "This dashboard is navigation derived from structured state, not mathematical evidence.", ""])
    return "\n".join(lines)


def iter_files():
    for path in sorted(ROOT.rglob("*")):
        if any(part in SKIP for part in path.parts):
            continue
        if path.is_file():
            yield path


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the resume dashboard and create a project snapshot.")
    parser.add_argument("--improvement-proposal", action="store_true")
    parser.add_argument("--resume-only", action="store_true")
    args = parser.parse_args()
    resume = build_resume()
    (ROOT / "knowledge/resume.md").write_text(resume, encoding="utf-8")
    if args.resume_only:
        print("knowledge/resume.md")
        return 0
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if args.improvement_proposal:
        target = ROOT / "improvements/proposals" / f"{timestamp}-proposal.md"
        lines = [
            "# Improvement Proposal",
            "",
            f"Created: `{timestamp}`",
            "",
            "## Motivation",
            "",
            "## Expected benefit",
            "",
            "## Risks",
            "",
            "## Affected files",
            "",
            "## Evals and rollback",
            "",
        ]
    else:
        target = ROOT / "runs/reports" / f"snapshot-{timestamp}.md"
        files = list(iter_files())
        lines = [
            "# Project Snapshot",
            "",
            f"Created: `{timestamp}`",
            "",
            resume,
            "## Inventory summary",
            "",
            f"- Files: `{len(files)}`",
            "- Exact file inventory remains available from the filesystem and `.lab/manifest.json` origin snapshot.",
            "",
        ]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    print(target.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
