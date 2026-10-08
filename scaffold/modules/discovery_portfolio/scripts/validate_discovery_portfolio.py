#!/usr/bin/env python3
"""Fail-closed structural validator for the discovery portfolio module."""

from __future__ import annotations

import argparse
import json
import stat
import sys
from pathlib import Path

from discovery_portfolio_lib import (
    ENGAGEMENT_TIERS,
    PortfolioError,
    list_candidates,
    load_json,
    refresh_summary,
    safe_path,
    summary_digest,
    validate_summary_shape,
)


ROOT = Path(__file__).resolve().parents[1]


def validate(root: Path) -> dict:
    state = load_json(safe_path(root, "portfolio/portfolio_state.json", kind="file"), "portfolio state")
    expected = {
        "schema_version": 1,
        "candidate_state_source": "portfolio/candidates/*/candidate.json + events/*.json",
        "event_history": "APPEND_ONLY_HASH_CHAIN",
        "proof_search_container": "problem dossier",
        "mathematical_status_policy": "NO_AUTOMATIC_PROMOTION",
    }
    if state != expected:
        raise PortfolioError("portfolio_state.json contract mismatch")
    for relative in ("portfolio/candidates", "portfolio/exports", "portfolio/imports", "portfolio/inbox", "portfolio/spinouts"):
        safe_path(root, relative, kind="dir")
    candidates = list_candidates(root)
    summary_path = safe_path(root, "knowledge/control_room_summary.json", kind="file")
    summary = load_json(summary_path, "control-room summary")
    validate_summary_shape(summary)
    counts = {name: 0 for name in summary["candidate_counts"]}
    rechecks = 0
    engagement_counts = {name: 0 for name in ENGAGEMENT_TIERS}
    for item in candidates:
        counts[item["status"]] += 1
        engagement_counts[item["engagement_tier"]] += 1
        if item["status"] == "PARKED" and item["current_park"] and any(trigger["kind"] == "MODEL_CAPABILITY_CHANGE" for trigger in item["current_park"]["reopen_triggers"]):
            rechecks += 1
    if counts != summary["candidate_counts"] or rechecks != summary["model_recheck_count"]:
        raise PortfolioError("control-room summary is stale; run refresh-summary")
    return {
        "ok": True,
        "candidate_count": len(candidates),
        "candidate_counts": counts,
        "engagement_counts": engagement_counts,
        "summary_digest": summary_digest(summary),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root")
    args = parser.parse_args()
    root = Path(args.root).resolve() if args.root else ROOT
    try:
        result = validate(root)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except PortfolioError as exc:
        print(f"discovery portfolio validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
