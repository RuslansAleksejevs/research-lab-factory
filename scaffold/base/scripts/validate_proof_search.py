#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[1]

GLOBAL_STATUSES = {
    "UNINITIALIZED",
    "CONTRACT_FROZEN",
    "SEARCHING",
    "AUDIT_CANDIDATE",
    "UNDER_AUDIT",
    "VERIFIED_PROOF",
    "VERIFIED_COUNTEREXAMPLE",
    "CONDITIONAL_RESULT",
    "CHECKPOINT_INCOMPLETE",
    "EXHAUSTED_CURRENT_MECHANISMS",
}
ROUTE_STATUSES = {
    "SEED",
    "ACTIVE",
    "CANDIDATE",
    "UNDER_AUDIT",
    "BLOCKED",
    "REFUTED",
    "MERGED",
    "PARKED",
    "CLOSED_PROOF",
    "CLOSED_COUNTEREXAMPLE",
}
GAP_CLASSES = {"GS0", "GS1", "GS2", "GS3", "GS4", "GS5"}
SOURCE_GATES = {"OPEN", "CLOSED", "NOT_APPLICABLE"}
VERIFICATION_GATES = {
    "NOT_READY",
    "I3_REQUIRED",
    "I3_ASSIGNED",
    "I3_PASSED",
    "NOT_REQUIRED",
}
NOVELTY_GATES = {"OPEN", "CLOSED", "NOT_REQUIRED"}
SEARCH_MODES = {
    "BLIND_GENERATION",
    "PROJECT_AWARE",
    "LITERATURE_AWARE",
    "VERIFICATION",
    "MIXED_WITH_PARTITIONS",
}
ORCHESTRATION_PROFILES = {"LIGHT", "FULL"}
REOPEN_BASES = {
    "NEW_BURDEN_REDUCING_MECHANISM",
    "EXACT_SOURCE_CLOSURE",
    "STRICTLY_NARROWER_REFORMULATION",
    "DIRECT_CHECKED_CLOSURE",
}
GAP_DISCHARGE_BASES = {
    "DIRECT_PROOF",
    "EXACT_SOURCE",
    "FORMAL_CERTIFICATE",
    "CHECKED_COMPUTATION",
}
DISCOVERY_OPERATORS = {
    "REPRESENTATION_CHANGE",
    "STRUCTURAL_DECOMPOSITION",
    "INVARIANT_OBSTRUCTION",
    "DUALITY_ADJUNCTION",
    "LOCAL_TO_GLOBAL",
    "MINIMAL_WITNESS",
    "COMPUTATIONAL_MICROEXPERIMENT",
    "HYPOTHESIS_ABLATION",
    "SOURCE_THEOREM_MINING",
    "CHECKER_FORMALIZATION",
    "SYNTHESIS_NEW_COMPATIBILITY",
}
ALLOWED_ROUTE_TRANSITIONS = {
    "SEED": {"ACTIVE", "PARKED", "BLOCKED", "REFUTED", "MERGED"},
    "ACTIVE": {"CANDIDATE", "BLOCKED", "REFUTED", "PARKED", "MERGED"},
    "CANDIDATE": {"UNDER_AUDIT", "ACTIVE", "BLOCKED", "REFUTED", "PARKED", "MERGED"},
    "UNDER_AUDIT": {
        "CLOSED_PROOF",
        "CLOSED_COUNTEREXAMPLE",
        "CANDIDATE",
        "ACTIVE",
        "BLOCKED",
        "REFUTED",
    },
    "BLOCKED": {"ACTIVE", "CANDIDATE", "PARKED", "MERGED"},
    "PARKED": {"SEED", "ACTIVE", "BLOCKED", "REFUTED", "MERGED"},
    "REFUTED": set(),
    "MERGED": set(),
    "CLOSED_PROOF": set(),
    "CLOSED_COUNTEREXAMPLE": set(),
}

REQUIRED_PATHS = [
    "workflows/hard_math_search_orchestration.md",
    "templates/context_envelope.md",
    "templates/approach_registry.md",
    "templates/attack_surface.md",
    "templates/search_round_report.md",
    "templates/proof_search_state.yaml",
    "templates/candidate_lineage.md",
    "templates/verifier_exposure_log.md",
    "templates/verifier_exposure_manifest.yaml",
    "templates/verifier_report_manifest.yaml",
    "templates/proof_obligations_manifest.yaml",
    "templates/source_audit_manifest.yaml",
    "templates/attack_surface_exit_manifest.yaml",
    "templates/dependency_snapshot_manifest.yaml",
    "templates/audit_packet_manifest.yaml",
    "templates/closure_manifest.yaml",
    "templates/search_wave_manifest.yaml",
    "templates/redirected_wave_waiver_manifest.yaml",
    "templates/reopen_manifest.yaml",
    "templates/gap_discharge_manifest.yaml",
    "templates/historical_backfill_manifest.yaml",
    "templates/waiver_assessment_manifest.yaml",
    "problems/templates/problem_dossier/context_envelope.md",
    "problems/templates/problem_dossier/approach_registry.md",
    "problems/templates/problem_dossier/attack_surface.md",
    "problems/templates/problem_dossier/proof_search_state.yaml",
    "problems/templates/problem_dossier/candidate_lineage.md",
    "problems/templates/problem_dossier/verifier_reports/exposure_log.template.md",
    "problems/templates/problem_dossier/search_rounds/README.md",
    "evals/regression/proof_search_invalid_states/README.md",
]

MANIFEST_TEMPLATE_TYPES = {
    "templates/verifier_exposure_manifest.yaml": "verifier_exposure",
    "templates/verifier_report_manifest.yaml": "decisive_verifier_report",
    "templates/proof_obligations_manifest.yaml": "proof_obligations_evidence",
    "templates/source_audit_manifest.yaml": "source_audit_evidence",
    "templates/attack_surface_exit_manifest.yaml": "attack_surface_exit_evidence",
    "templates/dependency_snapshot_manifest.yaml": "candidate_dependency_snapshot",
    "templates/audit_packet_manifest.yaml": "proof_audit_packet",
    "templates/closure_manifest.yaml": "proof_search_closure",
    "templates/search_wave_manifest.yaml": "proof_search_wave",
    "templates/redirected_wave_waiver_manifest.yaml": "redirected_wave_waiver",
    "templates/reopen_manifest.yaml": "blocked_route_reopen",
    "templates/gap_discharge_manifest.yaml": "gap_discharge",
    "templates/historical_backfill_manifest.yaml": "historical_route_backfill",
    "templates/waiver_assessment_manifest.yaml": "redirected_wave_waiver_assessment",
}

EXPECTED_EVAL_IDS = {
    "proof-search-anchoring",
    "proof-search-pseudo-diversity",
    "proof-search-equivalent-strength-lemma",
    "proof-search-premature-success",
    "proof-search-blocked-route-reopening",
    "proof-search-same-model-self-certification",
    "proof-search-blind-literature-mode-confusion",
    "proof-search-long-open-status-aversion",
}

REQUIRED_FIXTURE_HEADINGS = {
    "## Capability under test",
    "## Scenario",
    "## Evaluation prompt",
    "## Pass criteria",
    "## Hard failures",
    "## Gold disposition",
}
REQUIRED_FIXTURE_METADATA = {
    "eval_id",
    "category",
    "target",
    "fixture_version",
    "execution_mode",
    "grader",
    "threshold",
    "expected_global_status",
    "expected_route_status",
}


def add(checks: list[tuple[bool, str]], passed: bool, message: str) -> None:
    checks.append((passed, message))


def is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_allowed_str(value: Any, allowed: set[str]) -> bool:
    return isinstance(value, str) and value in allowed


def is_nonempty_str_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(is_nonempty_str(item) for item in value)
    )


def is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(is_nonempty_str(item) for item in value)


def is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_front_matter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    result: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip()
    return result


def validate_fixture_files(checks: list[tuple[bool, str]]) -> None:
    fixtures = sorted((ROOT / "evals/adversarial").glob("proof_search_*.md"))
    found_ids: set[str] = set()
    for path in fixtures:
        text = path.read_text(encoding="utf-8")
        metadata = parse_front_matter(text)
        eval_id = metadata.get("eval_id", "")
        add(checks, is_nonempty_str(eval_id), f"{path.relative_to(ROOT)} has eval_id")
        add(checks, eval_id not in found_ids, f"unique eval_id {eval_id or '<missing>'}")
        found_ids.add(eval_id)
        for field in REQUIRED_FIXTURE_METADATA:
            add(
                checks,
                is_nonempty_str(metadata.get(field)),
                f"{path.name} has metadata {field}",
            )
        add(
            checks,
            metadata.get("expected_global_status") in GLOBAL_STATUSES,
            f"{path.name} has canonical expected global status",
        )
        add(
            checks,
            metadata.get("expected_route_status") in ROUTE_STATUSES,
            f"{path.name} has canonical expected route status",
        )
        for heading in REQUIRED_FIXTURE_HEADINGS:
            add(checks, heading in text, f"{path.name} contains {heading}")
    add(
        checks,
        EXPECTED_EVAL_IDS.issubset(found_ids),
        "proof-search adversarial fixture set is complete",
    )


def validate_negative_state_fixtures(checks: list[tuple[bool, str]]) -> None:
    fixture_dir = ROOT / "evals/regression/proof_search_invalid_states"
    fixtures = sorted(fixture_dir.glob("*.yaml"))
    add(checks, bool(fixtures), "proof-search negative state fixtures exist")
    for path in fixtures:
        data, error = load_state(path)
        label = path.relative_to(ROOT)
        add(checks, error is None, f"{label} negative fixture parses")
        if data is None:
            continue
        expected = data.get("_expected_failure_fragment")
        add(
            checks,
            is_nonempty_str(expected),
            f"{label} declares expected failure fragment",
        )
        local_checks: list[tuple[bool, str]] = []
        validate_state(path, local_checks)
        failures = [message for passed, message in local_checks if not passed]
        add(
            checks,
            any(isinstance(expected, str) and expected in message for message in failures),
            f"{label} is rejected for its intended invariant",
        )


def validate_positive_state_fixtures(checks: list[tuple[bool, str]]) -> None:
    fixture_dir = ROOT / "evals/regression/proof_search_valid_states"
    fixtures = sorted(fixture_dir.glob("*.yaml"))
    add(checks, bool(fixtures), "proof-search positive state fixtures exist")
    for path in fixtures:
        local_checks: list[tuple[bool, str]] = []
        validate_state(path, local_checks)
        failures = [message for passed, message in local_checks if not passed]
        label = path.relative_to(ROOT)
        add(
            checks,
            not failures,
            f"{label} satisfies every structural closure invariant"
            + (f"; first failure: {failures[0]}" if failures else ""),
        )


def validate_state_mutation_regressions(checks: list[tuple[bool, str]]) -> None:
    path = ROOT / "evals/regression/proof_search_valid_states/verified_proof.yaml"
    base, error = load_state(path)
    add(checks, error is None and base is not None, "mutation-regression base state loads")
    if base is None:
        return

    def cloned() -> dict[str, Any]:
        return json.loads(json.dumps(base))

    cases: list[tuple[str, dict[str, Any], str]] = []

    target_swap = cloned()
    target_swap["problem_id"] = "FERMATS-LAST-THEOREM"
    cases.append(
        (
            "wrong target identity",
            target_swap,
            "target artifact binds problem and target IDs",
        )
    )

    evidence_swap = cloned()
    candidate_path = evidence_swap["closure_evidence"]["candidate_artifact"]
    candidate_digest = evidence_swap["closure_evidence"]["candidate_artifact_sha256"]
    for field in ("proof_obligations", "source_audit", "attack_surface_exit"):
        evidence_swap["closure_evidence"][field] = candidate_path
        evidence_swap["closure_evidence"][f"{field}_sha256"] = candidate_digest
    cases.append(
        (
            "closure evidence role substitution",
            evidence_swap,
            "verified closure has typed evidence: proof_obligations",
        )
    )

    polyglot_roles = cloned()
    shared_path = polyglot_roles["closure_evidence"]["proof_obligations"]
    shared_digest = polyglot_roles["closure_evidence"][
        "proof_obligations_sha256"
    ]
    for field in ("proof_obligations", "source_audit", "attack_surface_exit"):
        polyglot_roles["closure_evidence"][field] = shared_path
        polyglot_roles["closure_evidence"][f"{field}_sha256"] = shared_digest
    cases.append(
        (
            "one polyglot file reused for all closure roles",
            polyglot_roles,
            "closure evidence roles use pairwise-distinct artifacts",
        )
    )

    report_swap = cloned()
    report_swap["independent_verifier"]["report"] = report_swap[
        "independent_verifier"
    ]["exposure_log"]
    report_swap["independent_verifier"]["report_sha256"] = report_swap[
        "independent_verifier"
    ]["exposure_log_sha256"]
    cases.append(
        (
            "exposure log substituted for verifier report",
            report_swap,
            "completed verifier report exists in a verifier-report area",
        )
    )

    renamed_exposure = cloned()
    renamed_report_path = (
        "evals/regression/proof_search_invalid_states/"
        "verifier_report_from_exposure.md"
    )
    renamed_exposure["independent_verifier"]["report"] = renamed_report_path
    renamed_exposure["independent_verifier"]["report_sha256"] = file_sha256(
        ROOT / renamed_report_path
    )
    cases.append(
        (
            "renamed exposure log used as verifier report",
            renamed_exposure,
            "completed verifier report binds verifier and candidate",
        )
    )

    missing_bundle_lineage = cloned()
    missing_bundle_lineage["candidate_lineage"]["originating_run_ids"].append(
        "EVAL-UNRECORDED-GENERATOR"
    )
    cases.append(
        (
            "lineage ID absent from report and exposure bundle",
            missing_bundle_lineage,
            "completed verifier evidence bundle records all lineage IDs",
        )
    )

    historical_reuse = cloned()
    historical_reuse["historical_verifiers"].append(
        {
            "id": historical_reuse["independent_verifier"]["id"],
            "candidate_id": historical_reuse["candidate_proof_id"],
            "candidate_artifact": historical_reuse["closure_evidence"][
                "candidate_artifact"
            ],
            "candidate_artifact_sha256": historical_reuse[
                "candidate_artifact_sha256"
            ],
            "report_sha256": historical_reuse["independent_verifier"][
                "report_sha256"
            ],
            "independence_level": "I2",
            "completed": True,
            "verdict": "PASS",
            "decisive": False,
            "report": historical_reuse["independent_verifier"]["report"],
        }
    )
    cases.append(
        (
            "historical I2 run reused as I3",
            historical_reuse,
            "decisive verifier run ID has no prior historical exposure record",
        )
    )

    deleted_history = cloned()
    route = deleted_history["routes"][0]
    evidence = route["transitions"][0]["evidence"]
    evidence_sha256 = route["transitions"][0]["evidence_sha256"]
    route["transitions"] = [
        {
            "round": 1,
            "from_status": None,
            "to_status": "ACTIVE",
            "initialization_kind": "NEW_SEED",
            "reason": "history deleted",
            "evidence": evidence,
            "evidence_sha256": evidence_sha256,
            "reopen_basis": None,
            "reopen_evidence": None,
            "reopen_evidence_sha256": None,
        }
    ]
    cases.append(
        (
            "deleted history replaced by null-to-active",
            deleted_history,
            "new route initializes as SEED",
        )
    )

    historical_backfill_bypass = cloned()
    audit_transitions = historical_backfill_bypass["routes"][0]["transitions"][-2:]
    historical_backfill_bypass["routes"][0]["transitions"] = [
        {
            "round": 0,
            "from_status": None,
            "to_status": "CANDIDATE",
            "initialization_kind": "HISTORICAL_BACKFILL",
            "reason": "deleted history hidden as backfill",
            "evidence": evidence,
            "evidence_sha256": evidence_sha256,
            "reopen_basis": None,
            "reopen_evidence": None,
            "reopen_evidence_sha256": None,
        }
    ] + audit_transitions
    cases.append(
        (
            "historical backfill used to delete blocked/reopen history",
            historical_backfill_bypass,
            "has typed historical-backfill manifest",
        )
    )

    nonmonotone = cloned()
    nonmonotone["routes"][0]["transitions"][-1]["round"] = 0
    cases.append(
        (
            "nonmonotone transition rounds",
            nonmonotone,
            "round is nondecreasing",
        )
    )

    irrelevant_reopen = cloned()
    reopen_transition = next(
        transition
        for transition in irrelevant_reopen["routes"][0]["transitions"]
        if transition.get("from_status") == "BLOCKED"
    )
    reopen_transition["reopen_evidence"] = evidence
    reopen_transition["reopen_evidence_sha256"] = evidence_sha256
    cases.append(
        (
            "reopen evidence unrelated to blocker",
            irrelevant_reopen,
            "typed reopen manifest binds blocker and evidence",
        )
    )

    one_way_merge = cloned()
    merged_gap = "unresolved merged dependency"
    one_way_merge["routes"].append(
        {
            "id": "EVAL-MERGED-PARENT",
            "family": "synthetic unresolved parent",
            "idea_fingerprint": "fixture::merge::unresolved::v1",
            "status": "MERGED",
            "gap_class": "GS3",
            "independence_lineage": "EVAL-GENERATOR-2",
            "strongest_artifact": evidence,
            "candidate_id": None,
            "strongest_artifact_sha256": None,
            "parent_route_ids": [],
            "inherited_gaps": [],
            "merged_into": "EVAL-A1",
            "transitions": [
                {
                    "round": 0,
                    "from_status": None,
                    "to_status": "SEED",
                    "initialization_kind": "NEW_SEED",
                    "reason": "synthetic merge route registered",
                    "evidence": evidence,
                    "evidence_sha256": evidence_sha256,
                    "reopen_basis": None,
                    "reopen_evidence": None,
                    "reopen_evidence_sha256": None,
                },
                {
                    "round": 0,
                    "from_status": "SEED",
                    "to_status": "ACTIVE",
                    "reason": "synthetic merge route activated",
                    "evidence": evidence,
                    "evidence_sha256": evidence_sha256,
                    "reopen_basis": None,
                    "reopen_evidence": None,
                    "reopen_evidence_sha256": None,
                },
                {
                    "round": 1,
                    "from_status": "ACTIVE",
                    "to_status": "MERGED",
                    "reason": "synthetic route merged one way",
                    "evidence": evidence,
                    "evidence_sha256": evidence_sha256,
                    "reopen_basis": None,
                    "reopen_evidence": None,
                    "reopen_evidence_sha256": None,
                },
            ],
            "exact_gap": merged_gap,
            "gap_id": "EVAL-MERGED-GAP",
            "exact_gap_sha256": text_sha256(merged_gap),
            "source_gate": "NOT_APPLICABLE",
            "verification_gate": "NOT_READY",
            "novelty_gate": "NOT_REQUIRED",
            "blocked_reason": None,
            "reopen_condition": None,
        }
    )
    cases.append(
        (
            "one-way merge drops parent dependency",
            one_way_merge,
            "MERGED edge is reciprocal in surviving route parents",
        )
    )

    post_audit_dependency_change = json.loads(json.dumps(one_way_merge))
    child = post_audit_dependency_change["routes"][0]
    child["parent_route_ids"] = ["EVAL-MERGED-PARENT"]
    child["inherited_gaps"] = [
        {
            "source_route_id": "EVAL-MERGED-PARENT",
            "source_gap_id": "EVAL-MERGED-GAP",
            "source_gap_class": "GS3",
            "source_gap_statement_sha256": text_sha256(merged_gap),
            "status": "CLOSED",
            "evidence": child["transitions"][3]["reopen_evidence"],
            "evidence_sha256": child["transitions"][3][
                "reopen_evidence_sha256"
            ],
            "discharge_manifest": child["transitions"][3]["reopen_manifest"],
            "discharge_manifest_sha256": child["transitions"][3][
                "reopen_manifest_sha256"
            ],
        }
    ]
    cases.append(
        (
            "dependency graph changed after decisive audit",
            post_audit_dependency_change,
            "dependency snapshot matches complete candidate ancestry",
        )
    )

    terminal_gap_resolution = cloned()
    terminal_route = next(
        route
        for route in terminal_gap_resolution["routes"]
        if route.get("id") == terminal_gap_resolution["candidate_route_id"]
    )
    terminal_verifier = terminal_gap_resolution["independent_verifier"]
    terminal_before = terminal_route["exact_gap_sha256"]
    terminal_after_text = "No remaining gap after the decisive I3 report."
    terminal_after = text_sha256(terminal_after_text)
    terminal_route["exact_gap"] = terminal_after_text
    terminal_route["exact_gap_sha256"] = terminal_after
    terminal_transition = terminal_route["transitions"][-1]
    terminal_transition["evidence"] = terminal_verifier["report"]
    terminal_transition["evidence_sha256"] = terminal_verifier["report_sha256"]
    terminal_transition["gap_update_kind"] = "DECISIVE_GATE_RESOLUTION"
    terminal_transition["gap_statement_sha256_before"] = terminal_before
    terminal_transition["gap_statement_sha256_after"] = terminal_after

    terminal_checks: list[tuple[bool, str]] = []
    validate_state(path, terminal_checks, state_override=terminal_gap_resolution)
    terminal_failures = [
        message for passed, message in terminal_checks if not passed
    ]
    add(
        checks,
        not terminal_failures,
        "explicit terminal gap-resolution metadata preserves the immutable assignment snapshot"
        + (f"; first failure: {terminal_failures[0]}" if terminal_failures else ""),
    )

    terminal_missing_before = json.loads(json.dumps(terminal_gap_resolution))
    terminal_missing_before["routes"][0]["transitions"][-1].pop(
        "gap_statement_sha256_before"
    )
    cases.append(
        (
            "terminal gap resolution omits the assignment digest",
            terminal_missing_before,
            "dependency snapshot matches complete candidate ancestry",
        )
    )

    terminal_parent_change = json.loads(json.dumps(terminal_gap_resolution))
    terminal_parent_change["routes"][0]["parent_route_ids"] = ["EVAL-UNKNOWN-PARENT"]
    cases.append(
        (
            "terminal gap resolution changes route ancestry",
            terminal_parent_change,
            "dependency snapshot matches complete candidate ancestry",
        )
    )

    terminal_non_i3 = json.loads(json.dumps(terminal_gap_resolution))
    terminal_non_i3["independent_verifier"]["independence_level"] = "I2"
    cases.append(
        (
            "terminal gap resolution lacks a decisive I3 verifier",
            terminal_non_i3,
            "dependency snapshot matches complete candidate ancestry",
        )
    )

    terminal_evidence_mismatch = json.loads(json.dumps(terminal_gap_resolution))
    fallback_transition = terminal_evidence_mismatch["routes"][0]["transitions"][0]
    terminal_evidence_mismatch["routes"][0]["transitions"][-1]["evidence"] = (
        fallback_transition["evidence"]
    )
    terminal_evidence_mismatch["routes"][0]["transitions"][-1][
        "evidence_sha256"
    ] = fallback_transition["evidence_sha256"]
    cases.append(
        (
            "terminal gap resolution is not bound to the decisive report",
            terminal_evidence_mismatch,
            "dependency snapshot matches complete candidate ancestry",
        )
    )

    terminal_second_rewrite = json.loads(json.dumps(terminal_gap_resolution))
    terminal_second_text = "A second unrecorded post-close gap rewrite."
    terminal_second_rewrite["routes"][0]["exact_gap"] = terminal_second_text
    terminal_second_rewrite["routes"][0]["exact_gap_sha256"] = text_sha256(
        terminal_second_text
    )
    cases.append(
        (
            "terminal gap resolution is rewritten a second time",
            terminal_second_rewrite,
            "dependency snapshot matches complete candidate ancestry",
        )
    )

    add(
        checks,
        report_text_records_no_unresolved_issues(
            "Unresolved objections: none\nRequired repairs: none"
        ),
        "canonical empty-objection prose is accepted",
    )
    add(
        checks,
        report_text_records_no_unresolved_issues(
            "Objections: **NONE**\nRequired repairs: **NONE**"
        ),
        "historical empty-objection prose is accepted",
    )
    add(
        checks,
        not report_text_records_no_unresolved_issues(
            "Objections: **GS1**\nRequired repairs: **ONE**"
        ),
        "nonempty historical objections or repairs are rejected",
    )

    for case_name, mutated_state, expected_fragment in cases:
        local_checks: list[tuple[bool, str]] = []
        validate_state(path, local_checks, state_override=mutated_state)
        failures = [message for passed, message in local_checks if not passed]
        add(
            checks,
            any(expected_fragment in message for message in failures),
            f"mutation regression rejects {case_name}",
        )

    exhaustion_path = (
        ROOT / "evals/regression/proof_search_valid_states/exhausted_with_waiver.yaml"
    )
    exhaustion_base, exhaustion_error = load_state(exhaustion_path)
    add(
        checks,
        exhaustion_error is None and exhaustion_base is not None,
        "exhaustion mutation-regression base state loads",
    )
    if exhaustion_base is not None:
        unrelated_report = (
            ROOT
            / "evals/regression/proof_search_valid_states/artifacts/transition_report.md"
        )
        mutated_exhaustion = json.loads(json.dumps(exhaustion_base))
        mutated_exhaustion["outcome_record"]["initial_wave_report"] = str(
            unrelated_report.relative_to(ROOT)
        )
        mutated_exhaustion["outcome_record"]["initial_wave_report_sha256"] = (
            file_sha256(unrelated_report)
        )
        local_checks = []
        validate_state(
            exhaustion_path, local_checks, state_override=mutated_exhaustion
        )
        failures = [message for passed, message in local_checks if not passed]
        add(
            checks,
            any("typed initial-wave report" in message for message in failures),
            "mutation regression rejects unrelated exhaustion report",
        )

        unrelated_waiver = json.loads(json.dumps(exhaustion_base))
        candidate_artifact = (
            "evals/regression/proof_search_valid_states/artifacts/candidate.md"
        )
        candidate_artifact_sha256 = file_sha256(ROOT / candidate_artifact)
        unrelated_waiver["outcome_record"][
            "redirected_wave_waiver_evidence"
        ] = candidate_artifact
        unrelated_waiver["outcome_record"][
            "redirected_wave_waiver_evidence_sha256"
        ] = candidate_artifact_sha256
        unrelated_waiver["outcome_record"]["waiver_assessment"] = candidate_artifact
        unrelated_waiver["outcome_record"][
            "waiver_assessment_sha256"
        ] = candidate_artifact_sha256
        local_checks = []
        validate_state(
            exhaustion_path, local_checks, state_override=unrelated_waiver
        )
        failures = [message for passed, message in local_checks if not passed]
        add(
            checks,
            any("typed waiver assessment" in message for message in failures),
            "mutation regression rejects unrelated waiver evidence",
        )

    redirected_path = (
        ROOT
        / "evals/regression/proof_search_valid_states/exhausted_with_redirected_wave.yaml"
    )
    redirected_base, redirected_error = load_state(redirected_path)
    add(
        checks,
        redirected_error is None and redirected_base is not None,
        "redirected-wave mutation-regression base state loads",
    )
    if redirected_base is not None:
        duplicate_manifest_path = (
            "evals/regression/proof_search_invalid_states/"
            "duplicate_redirected_wave_manifest.json"
        )
        duplicate_wave = json.loads(json.dumps(redirected_base))
        duplicate_wave["outcome_record"][
            "redirected_wave_manifest"
        ] = duplicate_manifest_path
        duplicate_wave["outcome_record"][
            "redirected_wave_manifest_sha256"
        ] = file_sha256(ROOT / duplicate_manifest_path)
        local_checks = []
        validate_state(redirected_path, local_checks, state_override=duplicate_wave)
        failures = [message for passed, message in local_checks if not passed]
        add(
            checks,
            any(
                "redirected-wave manifest binds target and report" in message
                for message in failures
            ),
            "mutation regression rejects duplicate redirected wave",
        )


def load_state(path: Path) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(data, dict):
        return None, "top-level value is not an object"
    return data, None


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def resolve_artifact(raw: Any, state_path: Path) -> Optional[Path]:
    if not is_nonempty_str(raw):
        return None
    candidate = Path(raw)
    candidates = [candidate] if candidate.is_absolute() else [ROOT / candidate, state_path.parent / candidate]
    for resolved in candidates:
        try:
            canonical = resolved.resolve()
        except OSError:
            continue
        if (
            canonical.is_file()
            and canonical.name.lower() != "readme.md"
            and is_within(canonical, ROOT.resolve())
        ):
            return canonical
    return None


def artifact_exists(raw: Any, state_path: Path) -> bool:
    if not is_nonempty_str(raw):
        return False
    return resolve_artifact(raw, state_path) is not None


def research_artifact_exists(raw: Any, state_path: Path) -> bool:
    artifact = resolve_artifact(raw, state_path)
    if artifact is None:
        return False
    rel = artifact.relative_to(ROOT.resolve())
    if rel.parts[:2] == ("research", "tracks") or rel.parts[0] in {
        "problems",
        "research_reports",
        "paper",
        "computations",
        "formalization",
        "runs",
    }:
        return True
    eval_root = (ROOT / "evals").resolve()
    return is_within(state_path.resolve(), eval_root) and is_within(artifact, eval_root)


def exposure_log_exists(raw: Any, state_path: Path) -> bool:
    artifact = resolve_artifact(raw, state_path)
    return (
        artifact is not None
        and research_artifact_exists(raw, state_path)
        and ("exposure" in artifact.name.lower() or "verifier_reports" in artifact.parts)
        and artifact.suffix.lower() in {".md", ".tex", ".json", ".txt"}
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_matches_sha256(raw: Any, expected: Any, state_path: Path) -> bool:
    artifact = resolve_artifact(raw, state_path)
    return (
        artifact is not None
        and is_sha256(expected)
        and file_sha256(artifact) == expected
    )


def same_artifact(first: Any, second: Any, state_path: Path) -> bool:
    first_path = resolve_artifact(first, state_path)
    second_path = resolve_artifact(second, state_path)
    return first_path is not None and first_path == second_path


def load_json_artifact(raw: Any, state_path: Path) -> Optional[dict[str, Any]]:
    artifact = resolve_artifact(raw, state_path)
    if artifact is None:
        return None
    try:
        data = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def role_artifact_exists(raw: Any, state_path: Path, role: str) -> bool:
    artifact = resolve_artifact(raw, state_path)
    if artifact is None or not research_artifact_exists(raw, state_path):
        return False
    name = artifact.name.lower().replace("-", "_")
    role_tokens = {
        "target": ("target", "context_envelope", "problem"),
        "proof_obligations": ("proof_obligation", "obligations"),
        "source_audit": ("source", "citation", "crosswalk", "bibliograph"),
        "attack_surface": ("attack_surface", "attack"),
        "closure_manifest": ("closure_manifest",),
        "exposure_manifest": ("exposure_manifest",),
        "report_manifest": ("report_manifest", "verifier_manifest"),
        "proof_obligations_manifest": ("proof_obligations_manifest",),
        "source_audit_manifest": ("source_audit_manifest",),
        "attack_surface_exit_manifest": ("attack_surface_exit_manifest",),
        "dependency_snapshot": ("dependency_snapshot",),
        "audit_packet": ("audit_packet",),
        "wave_report": ("wave", "round_report", "search_round"),
        "wave_manifest": ("wave_manifest",),
        "waiver_manifest": ("waiver_manifest",),
        "gap_discharge_manifest": ("gap_discharge",),
        "reopen_manifest": ("reopen_manifest",),
        "backfill_manifest": ("backfill_manifest",),
        "waiver_assessment": ("waiver_assessment",),
    }
    return any(token in name for token in role_tokens[role])


def report_binds_candidate(
    raw: Any,
    candidate_id: Any,
    candidate_digest: Any,
    verifier_id: Any,
    state_path: Path,
    required_tokens: Optional[list[str]] = None,
) -> bool:
    artifact = resolve_artifact(raw, state_path)
    if (
        artifact is None
        or artifact.suffix.lower() not in {".md", ".tex", ".json", ".txt"}
        or not is_nonempty_str(candidate_id)
        or not is_sha256(candidate_digest)
        or not is_nonempty_str(verifier_id)
    ):
        return False
    try:
        text = artifact.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    base = (
        candidate_id in text
        and candidate_digest in text
        and verifier_id in text
    )
    return base and all(
        is_nonempty_str(token) and token in text for token in (required_tokens or [])
    )


def text_artifact_contains(raw: Any, tokens: list[str], state_path: Path) -> bool:
    artifact = resolve_artifact(raw, state_path)
    if artifact is None or artifact.suffix.lower() not in {".md", ".tex", ".json", ".txt"}:
        return False
    try:
        text = artifact.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    return bool(tokens) and all(is_nonempty_str(token) and token in text for token in tokens)


def report_text_records_no_unresolved_issues(text: str) -> bool:
    canonical = (
        "Unresolved objections: none",
        "Required repairs: none",
    )
    historical = (
        "Objections: **NONE**",
        "Required repairs: **NONE**",
    )
    return all(token in text for token in canonical) or all(
        token in text for token in historical
    )


def report_records_no_unresolved_issues(raw: Any, state_path: Path) -> bool:
    artifact = resolve_artifact(raw, state_path)
    if artifact is None or artifact.suffix.lower() not in {".md", ".tex", ".json", ".txt"}:
        return False
    try:
        text = artifact.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    return report_text_records_no_unresolved_issues(text)


def same_string_set(value: Any, expected: list[str]) -> bool:
    return is_str_list(value) and len(value) == len(set(value)) and set(value) == set(expected)


def manifest_artifact_binding_matches(
    manifest: dict[str, Any],
    state_path: Path,
    *,
    artifact: Any,
    artifact_sha256: Any,
) -> bool:
    return (
        same_artifact(manifest.get("artifact"), artifact, state_path)
        and manifest.get("artifact_sha256") == artifact_sha256
        and artifact_matches_sha256(artifact, artifact_sha256, state_path)
    )


def closure_evidence_role_manifest_matches(
    manifest: Optional[dict[str, Any]],
    state_path: Path,
    *,
    record_type: str,
    state: dict[str, Any],
    target_binding: dict[str, Any],
    closure_evidence: dict[str, Any],
    artifact_field: str,
) -> bool:
    if manifest is None:
        return False
    base = (
        manifest.get("schema_version") == 1
        and manifest.get("record_type") == record_type
        and manifest.get("problem_id") == state.get("problem_id")
        and manifest.get("target_id") == target_binding.get("target_id")
        and manifest.get("target_sha256") == target_binding.get("artifact_sha256")
        and manifest.get("candidate_id") == state.get("candidate_proof_id")
        and manifest.get("candidate_sha256")
        == state.get("candidate_artifact_sha256")
        and manifest_artifact_binding_matches(
            manifest,
            state_path,
            artifact=closure_evidence.get(artifact_field),
            artifact_sha256=closure_evidence.get(f"{artifact_field}_sha256"),
        )
    )
    if not base:
        return False
    if record_type == "proof_obligations_evidence":
        valid = (
            is_nonempty_str_list(manifest.get("obligation_ids"))
            and is_str_list(manifest.get("open_obligation_ids"))
            and is_allowed_str(manifest.get("highest_gap_class"), GAP_CLASSES)
            and type(manifest.get("all_substantive_closed")) is bool
        )
        if state.get("global_status") in {"VERIFIED_PROOF", "VERIFIED_COUNTEREXAMPLE"}:
            valid = valid and (
                manifest.get("open_obligation_ids") == []
                and manifest.get("highest_gap_class") == "GS0"
                and manifest.get("all_substantive_closed") is True
            )
        return valid
    if record_type == "source_audit_evidence":
        source_gate = manifest.get("source_gate")
        valid = (
            is_allowed_str(source_gate, SOURCE_GATES)
            and is_str_list(manifest.get("checked_claim_ids"))
            and is_str_list(manifest.get("unchecked_load_bearing_imports"))
            and (
                source_gate != "NOT_APPLICABLE"
                or is_nonempty_str(manifest.get("not_applicable_reason"))
            )
        )
        if state.get("global_status") in {"VERIFIED_PROOF", "VERIFIED_COUNTEREXAMPLE"}:
            valid = valid and source_gate in {"CLOSED", "NOT_APPLICABLE"} and not manifest.get(
                "unchecked_load_bearing_imports"
            )
        return valid
    if record_type == "attack_surface_exit_evidence":
        valid = (
            is_nonempty_str_list(manifest.get("attack_ids"))
            and is_str_list(manifest.get("unresolved_failures"))
            and manifest.get("status") in {"PASS", "FAIL", "INCONCLUSIVE"}
        )
        if state.get("global_status") in {"VERIFIED_PROOF", "VERIFIED_COUNTEREXAMPLE"}:
            valid = valid and manifest.get("status") == "PASS" and not manifest.get(
                "unresolved_failures"
            )
        return valid
    return False


def canonical_dependency_routes(
    state: dict[str, Any], candidate_route_id: Any
) -> Optional[list[dict[str, Any]]]:
    routes = state.get("routes")
    if not isinstance(routes, list) or not is_nonempty_str(candidate_route_id):
        return None
    routes_by_id = {
        route.get("id"): route
        for route in routes
        if isinstance(route, dict) and is_nonempty_str(route.get("id"))
    }
    if candidate_route_id not in routes_by_id:
        return None
    selected: set[str] = set()
    pending = [candidate_route_id]
    while pending:
        route_id = pending.pop()
        if route_id in selected:
            continue
        route = routes_by_id.get(route_id)
        if not isinstance(route, dict):
            return None
        selected.add(route_id)
        parents = route.get("parent_route_ids")
        if not is_str_list(parents):
            return None
        pending.extend(parents)
    snapshot: list[dict[str, Any]] = []
    for route_id in sorted(selected):
        route = routes_by_id[route_id]
        inherited_items: list[dict[str, Any]] = []
        inherited = route.get("inherited_gaps")
        if not isinstance(inherited, list):
            return None
        for item in inherited:
            if not isinstance(item, dict):
                return None
            inherited_items.append(
                {
                    "id": item.get("id"),
                    "source_route_id": item.get("source_route_id"),
                    "source_gap_id": item.get("source_gap_id"),
                    "source_gap_class": item.get("source_gap_class"),
                    "source_gap_statement_sha256": item.get(
                        "source_gap_statement_sha256"
                    ),
                    "status": item.get("status"),
                    "discharge_manifest": item.get("discharge_manifest"),
                    "discharge_manifest_sha256": item.get(
                        "discharge_manifest_sha256"
                    ),
                }
            )
        inherited_items.sort(
            key=lambda item: (
                str(item.get("source_route_id")), str(item.get("source_gap_id"))
            )
        )
        snapshot.append(
            {
                "route_id": route_id,
                "parent_route_ids": sorted(route.get("parent_route_ids", [])),
                "gap_id": route.get("gap_id"),
                "gap_class": route.get("gap_class"),
                "gap_statement_sha256": route.get("exact_gap_sha256"),
                "inherited_gaps": inherited_items,
            }
        )
    return snapshot


def dependency_graph_is_acyclic(routes_by_id: dict[str, dict[str, Any]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(route_id: str) -> bool:
        if route_id in visiting:
            return False
        if route_id in visited:
            return True
        route = routes_by_id.get(route_id)
        if not isinstance(route, dict) or not is_str_list(route.get("parent_route_ids")):
            return False
        visiting.add(route_id)
        for parent_id in route.get("parent_route_ids", []):
            if parent_id not in routes_by_id or not visit(parent_id):
                return False
        visiting.remove(route_id)
        visited.add(route_id)
        return True

    return all(visit(route_id) for route_id in routes_by_id)


def terminal_gap_resolution_snapshot_matches(
    snapshot_routes: Any,
    expected_routes: Any,
    *,
    state: dict[str, Any],
    state_path: Path,
) -> bool:
    """Accept one explicit post-verdict gap-description update.

    The immutable audit packet binds the assignment-time dependency snapshot.
    After the decisive verifier closes that exact candidate, mutable state may
    replace only the candidate route's gap statement with the resolved wording.
    Every structural dependency and both before/after digests remain explicit.
    """
    if not isinstance(snapshot_routes, list) or not isinstance(expected_routes, list):
        return False
    if len(snapshot_routes) != len(expected_routes):
        return False

    snapshot_by_id = {
        item.get("route_id"): item
        for item in snapshot_routes
        if isinstance(item, dict) and is_nonempty_str(item.get("route_id"))
    }
    expected_by_id = {
        item.get("route_id"): item
        for item in expected_routes
        if isinstance(item, dict) and is_nonempty_str(item.get("route_id"))
    }
    if (
        len(snapshot_by_id) != len(snapshot_routes)
        or len(expected_by_id) != len(expected_routes)
        or set(snapshot_by_id) != set(expected_by_id)
    ):
        return False

    candidate_route_id = state.get("candidate_route_id")
    if not is_nonempty_str(candidate_route_id) or candidate_route_id not in snapshot_by_id:
        return False
    for route_id in snapshot_by_id:
        snapshot_route = snapshot_by_id[route_id]
        expected_route = expected_by_id[route_id]
        if route_id != candidate_route_id:
            if snapshot_route != expected_route:
                return False
            continue
        for field in (
            "route_id",
            "parent_route_ids",
            "gap_id",
            "gap_class",
            "inherited_gaps",
        ):
            if snapshot_route.get(field) != expected_route.get(field):
                return False

    before_digest = snapshot_by_id[candidate_route_id].get("gap_statement_sha256")
    after_digest = expected_by_id[candidate_route_id].get("gap_statement_sha256")
    if not is_sha256(before_digest) or not is_sha256(after_digest) or before_digest == after_digest:
        return False

    routes = state.get("routes")
    if not isinstance(routes, list):
        return False
    candidate_route = next(
        (
            route
            for route in routes
            if isinstance(route, dict) and route.get("id") == candidate_route_id
        ),
        None,
    )
    verifier = state.get("independent_verifier")
    if not isinstance(candidate_route, dict) or not isinstance(verifier, dict):
        return False
    transitions = candidate_route.get("transitions")
    if not isinstance(transitions, list) or not transitions or not isinstance(transitions[-1], dict):
        return False
    terminal = transitions[-1]

    return (
        state.get("global_status") == "VERIFIED_PROOF"
        and candidate_route.get("status") == "CLOSED_PROOF"
        and candidate_route.get("verification_gate") == "I3_PASSED"
        and verifier.get("assigned") is True
        and verifier.get("completed") is True
        and verifier.get("independence_level") == "I3"
        and verifier.get("verdict") in {"PASS", "VERIFIED"}
        and terminal.get("from_status") == "UNDER_AUDIT"
        and terminal.get("to_status") == "CLOSED_PROOF"
        and terminal.get("gap_update_kind") == "DECISIVE_GATE_RESOLUTION"
        and terminal.get("gap_statement_sha256_before") == before_digest
        and terminal.get("gap_statement_sha256_after") == after_digest
        and same_artifact(terminal.get("evidence"), verifier.get("report"), state_path)
        and terminal.get("evidence_sha256") == verifier.get("report_sha256")
        and artifact_matches_sha256(
            verifier.get("report"), verifier.get("report_sha256"), state_path
        )
    )


def dependency_snapshot_matches(
    manifest: Optional[dict[str, Any]],
    state_path: Path,
    *,
    state: dict[str, Any],
    target_binding: dict[str, Any],
) -> bool:
    if manifest is None:
        return False
    expected_routes = canonical_dependency_routes(
        state, state.get("candidate_route_id")
    )
    snapshot_routes = manifest.get("routes")
    routes_match = expected_routes is not None and (
        snapshot_routes == expected_routes
        or terminal_gap_resolution_snapshot_matches(
            snapshot_routes,
            expected_routes,
            state=state,
            state_path=state_path,
        )
    )
    return (
        manifest.get("schema_version") == 1
        and manifest.get("record_type") == "candidate_dependency_snapshot"
        and manifest.get("problem_id") == state.get("problem_id")
        and manifest.get("target_id") == target_binding.get("target_id")
        and manifest.get("target_sha256") == target_binding.get("artifact_sha256")
        and manifest.get("candidate_id") == state.get("candidate_proof_id")
        and manifest.get("candidate_sha256")
        == state.get("candidate_artifact_sha256")
        and manifest.get("candidate_route_id") == state.get("candidate_route_id")
        and routes_match
    )


def audit_packet_matches(
    manifest: Optional[dict[str, Any]],
    state_path: Path,
    *,
    state: dict[str, Any],
    target_binding: dict[str, Any],
    candidate_lineage: dict[str, Any],
    closure_evidence: dict[str, Any],
) -> bool:
    if manifest is None:
        return False
    bindings = (
        ("target_artifact", "target_sha256", target_binding.get("artifact"), target_binding.get("artifact_sha256")),
        ("candidate_artifact", "candidate_sha256", closure_evidence.get("candidate_artifact"), closure_evidence.get("candidate_artifact_sha256")),
        ("candidate_lineage", "candidate_lineage_sha256", candidate_lineage.get("lineage_artifact"), candidate_lineage.get("lineage_artifact_sha256")),
        ("proof_obligations", "proof_obligations_sha256", closure_evidence.get("proof_obligations"), closure_evidence.get("proof_obligations_sha256")),
        ("proof_obligations_manifest", "proof_obligations_manifest_sha256", closure_evidence.get("proof_obligations_manifest"), closure_evidence.get("proof_obligations_manifest_sha256")),
        ("source_audit", "source_audit_sha256", closure_evidence.get("source_audit"), closure_evidence.get("source_audit_sha256")),
        ("source_audit_manifest", "source_audit_manifest_sha256", closure_evidence.get("source_audit_manifest"), closure_evidence.get("source_audit_manifest_sha256")),
        ("attack_surface_exit", "attack_surface_exit_sha256", closure_evidence.get("attack_surface_exit"), closure_evidence.get("attack_surface_exit_sha256")),
        ("attack_surface_exit_manifest", "attack_surface_exit_manifest_sha256", closure_evidence.get("attack_surface_exit_manifest"), closure_evidence.get("attack_surface_exit_manifest_sha256")),
        ("dependency_snapshot", "dependency_snapshot_sha256", closure_evidence.get("dependency_snapshot"), closure_evidence.get("dependency_snapshot_sha256")),
    )
    return (
        manifest.get("schema_version") == 1
        and manifest.get("record_type") == "proof_audit_packet"
        and manifest.get("problem_id") == state.get("problem_id")
        and manifest.get("target_id") == target_binding.get("target_id")
        and manifest.get("candidate_id") == state.get("candidate_proof_id")
        and all(
            same_artifact(manifest.get(path_field), expected_path, state_path)
            and manifest.get(hash_field) == expected_hash
            for path_field, hash_field, expected_path, expected_hash in bindings
        )
        and all(
            artifact_matches_sha256(expected_path, expected_hash, state_path)
            for _, _, expected_path, expected_hash in bindings
        )
        and closure_evidence_role_manifest_matches(
            load_json_artifact(
                closure_evidence.get("proof_obligations_manifest"), state_path
            ),
            state_path,
            record_type="proof_obligations_evidence",
            state=state,
            target_binding=target_binding,
            closure_evidence=closure_evidence,
            artifact_field="proof_obligations",
        )
        and closure_evidence_role_manifest_matches(
            load_json_artifact(
                closure_evidence.get("source_audit_manifest"), state_path
            ),
            state_path,
            record_type="source_audit_evidence",
            state=state,
            target_binding=target_binding,
            closure_evidence=closure_evidence,
            artifact_field="source_audit",
        )
        and closure_evidence_role_manifest_matches(
            load_json_artifact(
                closure_evidence.get("attack_surface_exit_manifest"), state_path
            ),
            state_path,
            record_type="attack_surface_exit_evidence",
            state=state,
            target_binding=target_binding,
            closure_evidence=closure_evidence,
            artifact_field="attack_surface_exit",
        )
        and dependency_snapshot_matches(
            load_json_artifact(closure_evidence.get("dependency_snapshot"), state_path),
            state_path,
            state=state,
            target_binding=target_binding,
        )
    )


def packet_entries_match_audit_packet(
    entries: Any, audit_packet: Optional[dict[str, Any]], state_path: Path
) -> bool:
    if not isinstance(entries, list) or audit_packet is None:
        return False
    role_fields = {
        "target": ("target_artifact", "target_sha256"),
        "candidate": ("candidate_artifact", "candidate_sha256"),
        "candidate_lineage": ("candidate_lineage", "candidate_lineage_sha256"),
        "proof_obligations": ("proof_obligations", "proof_obligations_sha256"),
        "proof_obligations_manifest": ("proof_obligations_manifest", "proof_obligations_manifest_sha256"),
        "source_audit": ("source_audit", "source_audit_sha256"),
        "source_audit_manifest": ("source_audit_manifest", "source_audit_manifest_sha256"),
        "attack_surface_exit": ("attack_surface_exit", "attack_surface_exit_sha256"),
        "attack_surface_exit_manifest": ("attack_surface_exit_manifest", "attack_surface_exit_manifest_sha256"),
        "dependency_snapshot": ("dependency_snapshot", "dependency_snapshot_sha256"),
    }
    entries_by_role = {
        entry.get("role"): entry for entry in entries if isinstance(entry, dict)
    }
    if set(entries_by_role) != set(role_fields) or len(entries) != len(role_fields):
        return False
    return all(
        same_artifact(
            entries_by_role[role].get("path"), audit_packet.get(path_field), state_path
        )
        and entries_by_role[role].get("sha256") == audit_packet.get(hash_field)
        for role, (path_field, hash_field) in role_fields.items()
    )


def exposure_manifest_matches(
    manifest: Optional[dict[str, Any]],
    state_path: Path,
    *,
    problem_id: Any,
    target_id: Any,
    target_sha256: Any,
    candidate_id: Any,
    candidate_sha256: Any,
    verifier_id: Any,
    originating_run_ids: list[str],
    material_repair_run_ids: list[str],
    audit_packet: Any,
    audit_packet_sha256: Any,
    exposure_log: Any,
    exposure_log_sha256: Any,
) -> bool:
    if manifest is None:
        return False
    audit_packet_manifest = load_json_artifact(audit_packet, state_path)
    return (
        manifest.get("schema_version") == 1
        and manifest.get("record_type") == "verifier_exposure"
        and manifest.get("problem_id") == problem_id
        and manifest.get("target_id") == target_id
        and manifest.get("target_sha256") == target_sha256
        and manifest.get("candidate_id") == candidate_id
        and manifest.get("candidate_sha256") == candidate_sha256
        and manifest.get("verifier_id") == verifier_id
        and same_string_set(manifest.get("originating_run_ids"), originating_run_ids)
        and same_string_set(manifest.get("material_repair_run_ids"), material_repair_run_ids)
        and same_artifact(manifest.get("audit_packet"), audit_packet, state_path)
        and manifest.get("audit_packet_sha256") == audit_packet_sha256
        and artifact_matches_sha256(audit_packet, audit_packet_sha256, state_path)
        and packet_entries_match_audit_packet(
            manifest.get("packet_entries"), audit_packet_manifest, state_path
        )
        and same_artifact(manifest.get("exposure_log"), exposure_log, state_path)
        and manifest.get("exposure_log_sha256") == exposure_log_sha256
        and is_nonempty_str_list(manifest.get("material_withheld"))
        and is_nonempty_str(manifest.get("assigned_by"))
        and is_nonempty_str(manifest.get("assigned_at"))
    )


def report_manifest_matches(
    manifest: Optional[dict[str, Any]],
    state_path: Path,
    *,
    problem_id: Any,
    target_id: Any,
    target_sha256: Any,
    candidate_id: Any,
    candidate_sha256: Any,
    verifier_id: Any,
    independence_level: Any,
    verdict: Any,
    exposure_log: Any,
    exposure_log_sha256: Any,
    exposure_manifest: Any,
    exposure_manifest_sha256: Any,
    audit_packet: Any,
    audit_packet_sha256: Any,
    report: Any,
    report_sha256: Any,
) -> bool:
    if manifest is None:
        return False
    unresolved = manifest.get("unresolved_objections")
    repairs = manifest.get("required_repairs")
    base = (
        manifest.get("schema_version") == 1
        and manifest.get("record_type") == "decisive_verifier_report"
        and manifest.get("problem_id") == problem_id
        and manifest.get("target_id") == target_id
        and manifest.get("target_sha256") == target_sha256
        and manifest.get("candidate_id") == candidate_id
        and manifest.get("candidate_sha256") == candidate_sha256
        and manifest.get("verifier_id") == verifier_id
        and manifest.get("independence_level") == independence_level
        and manifest.get("verdict") == verdict
        and is_allowed_str(manifest.get("highest_gap_class"), GAP_CLASSES)
        and is_str_list(unresolved)
        and is_str_list(repairs)
        and is_nonempty_str_list(manifest.get("checked_obligation_ids"))
        and is_nonempty_str_list(manifest.get("checked_attack_ids"))
        and is_nonempty_str_list(manifest.get("type_checks"))
        and is_nonempty_str_list(manifest.get("source_checks"))
        and is_nonempty_str_list(manifest.get("counterexample_checks"))
        and is_nonempty_str(manifest.get("decisive_lemma_check"))
        and is_nonempty_str(manifest.get("circularity_check"))
        and same_artifact(manifest.get("audit_packet"), audit_packet, state_path)
        and manifest.get("audit_packet_sha256") == audit_packet_sha256
        and artifact_matches_sha256(audit_packet, audit_packet_sha256, state_path)
        and same_artifact(manifest.get("exposure_log"), exposure_log, state_path)
        and manifest.get("exposure_log_sha256") == exposure_log_sha256
        and same_artifact(
            manifest.get("exposure_manifest"), exposure_manifest, state_path
        )
        and manifest.get("exposure_manifest_sha256") == exposure_manifest_sha256
        and same_artifact(manifest.get("report"), report, state_path)
        and manifest.get("report_sha256") == report_sha256
    )
    if not base:
        return False
    if verdict in {"PASS", "VERIFIED"}:
        return manifest.get("highest_gap_class") == "GS0" and not unresolved and not repairs
    return True


def closure_manifest_matches(
    manifest: Optional[dict[str, Any]],
    state_path: Path,
    *,
    state: dict[str, Any],
    target_binding: dict[str, Any],
    candidate_lineage: dict[str, Any],
    verifier: dict[str, Any],
    closure_evidence: dict[str, Any],
) -> bool:
    if manifest is None:
        return False
    return (
        manifest.get("schema_version") == 1
        and manifest.get("record_type") == "proof_search_closure"
        and manifest.get("global_status") == state.get("global_status")
        and manifest.get("problem_id") == state.get("problem_id")
        and manifest.get("target_id") == target_binding.get("target_id")
        and manifest.get("target_sha256") == target_binding.get("artifact_sha256")
        and same_artifact(
            manifest.get("target_artifact"), target_binding.get("artifact"), state_path
        )
        and manifest.get("candidate_id") == state.get("candidate_proof_id")
        and manifest.get("candidate_sha256")
        == state.get("candidate_artifact_sha256")
        and same_artifact(
            manifest.get("candidate_artifact"),
            closure_evidence.get("candidate_artifact"),
            state_path,
        )
        and same_artifact(
            manifest.get("proof_obligations"),
            closure_evidence.get("proof_obligations"),
            state_path,
        )
        and manifest.get("proof_obligations_sha256")
        == closure_evidence.get("proof_obligations_sha256")
        and same_artifact(
            manifest.get("proof_obligations_manifest"),
            closure_evidence.get("proof_obligations_manifest"),
            state_path,
        )
        and manifest.get("proof_obligations_manifest_sha256")
        == closure_evidence.get("proof_obligations_manifest_sha256")
        and same_artifact(
            manifest.get("source_audit"), closure_evidence.get("source_audit"), state_path
        )
        and manifest.get("source_audit_sha256")
        == closure_evidence.get("source_audit_sha256")
        and same_artifact(
            manifest.get("source_audit_manifest"),
            closure_evidence.get("source_audit_manifest"),
            state_path,
        )
        and manifest.get("source_audit_manifest_sha256")
        == closure_evidence.get("source_audit_manifest_sha256")
        and same_artifact(
            manifest.get("attack_surface_exit"),
            closure_evidence.get("attack_surface_exit"),
            state_path,
        )
        and manifest.get("attack_surface_exit_sha256")
        == closure_evidence.get("attack_surface_exit_sha256")
        and same_artifact(
            manifest.get("attack_surface_exit_manifest"),
            closure_evidence.get("attack_surface_exit_manifest"),
            state_path,
        )
        and manifest.get("attack_surface_exit_manifest_sha256")
        == closure_evidence.get("attack_surface_exit_manifest_sha256")
        and same_artifact(
            manifest.get("dependency_snapshot"),
            closure_evidence.get("dependency_snapshot"),
            state_path,
        )
        and manifest.get("dependency_snapshot_sha256")
        == closure_evidence.get("dependency_snapshot_sha256")
        and same_artifact(
            manifest.get("audit_packet"), closure_evidence.get("audit_packet"), state_path
        )
        and manifest.get("audit_packet_sha256")
        == closure_evidence.get("audit_packet_sha256")
        and same_artifact(
            manifest.get("candidate_lineage"),
            candidate_lineage.get("lineage_artifact"),
            state_path,
        )
        and manifest.get("candidate_lineage_sha256")
        == candidate_lineage.get("lineage_artifact_sha256")
        and manifest.get("verifier_id") == verifier.get("id")
        and same_artifact(
            manifest.get("exposure_log"), verifier.get("exposure_log"), state_path
        )
        and manifest.get("exposure_log_sha256") == verifier.get("exposure_log_sha256")
        and same_artifact(
            manifest.get("exposure_manifest"),
            verifier.get("exposure_manifest"),
            state_path,
        )
        and manifest.get("exposure_manifest_sha256")
        == verifier.get("exposure_manifest_sha256")
        and same_artifact(manifest.get("verifier_report"), verifier.get("report"), state_path)
        and manifest.get("verifier_report_sha256") == verifier.get("report_sha256")
        and same_artifact(
            manifest.get("report_manifest"), verifier.get("report_manifest"), state_path
        )
        and manifest.get("report_manifest_sha256")
        == verifier.get("report_manifest_sha256")
        and manifest.get("verdict") == verifier.get("verdict")
        and manifest.get("highest_gap_class") == "GS0"
        and manifest.get("open_obligations") == []
    )


def gap_discharge_manifest_matches(
    manifest: Optional[dict[str, Any]],
    state_path: Path,
    *,
    state: dict[str, Any],
    target_binding: dict[str, Any],
    child_route_id: str,
    inherited_gap: dict[str, Any],
) -> bool:
    if manifest is None:
        return False
    return (
        manifest.get("schema_version") == 1
        and manifest.get("record_type") == "gap_discharge"
        and manifest.get("problem_id") == state.get("problem_id")
        and manifest.get("target_id") == target_binding.get("target_id")
        and manifest.get("target_sha256") == target_binding.get("artifact_sha256")
        and manifest.get("child_route_id") == child_route_id
        and manifest.get("source_route_id") == inherited_gap.get("source_route_id")
        and manifest.get("source_gap_id") == inherited_gap.get("source_gap_id")
        and manifest.get("source_gap_class") == inherited_gap.get("source_gap_class")
        and manifest.get("source_gap_statement_sha256")
        == inherited_gap.get("source_gap_statement_sha256")
        and manifest.get("discharge_basis") in GAP_DISCHARGE_BASES
        and same_artifact(
            manifest.get("evidence"), inherited_gap.get("evidence"), state_path
        )
        and manifest.get("evidence_sha256") == inherited_gap.get("evidence_sha256")
        and text_artifact_contains(
            inherited_gap.get("evidence"),
            [
                inherited_gap.get("source_gap_id"),
                inherited_gap.get("source_gap_statement_sha256"),
            ],
            state_path,
        )
    )


def reopen_manifest_matches(
    manifest: Optional[dict[str, Any]],
    state_path: Path,
    *,
    state: dict[str, Any],
    target_binding: dict[str, Any],
    route_id: Any,
    transition: dict[str, Any],
) -> bool:
    if manifest is None:
        return False
    return (
        manifest.get("schema_version") == 1
        and manifest.get("record_type") == "blocked_route_reopen"
        and manifest.get("problem_id") == state.get("problem_id")
        and manifest.get("target_id") == target_binding.get("target_id")
        and manifest.get("target_sha256") == target_binding.get("artifact_sha256")
        and manifest.get("route_id") == route_id
        and manifest.get("blocked_gap_id") == transition.get("blocked_gap_id")
        and manifest.get("blocked_gap_class") == transition.get("blocked_gap_class")
        and manifest.get("blocked_gap_statement_sha256")
        == transition.get("blocked_gap_statement_sha256")
        and manifest.get("reopen_basis") == transition.get("reopen_basis")
        and manifest.get("result_status") == transition.get("to_status")
        and manifest.get("result_candidate_id")
        == transition.get("result_candidate_id")
        and manifest.get("result_candidate_sha256")
        == transition.get("result_candidate_sha256")
        and same_artifact(
            manifest.get("evidence"), transition.get("reopen_evidence"), state_path
        )
        and manifest.get("evidence_sha256")
        == transition.get("reopen_evidence_sha256")
        and text_artifact_contains(
            transition.get("reopen_evidence"),
            [
                transition.get("blocked_gap_id"),
                transition.get("blocked_gap_statement_sha256"),
            ],
            state_path,
        )
    )


def historical_backfill_manifest_matches(
    manifest: Optional[dict[str, Any]],
    state_path: Path,
    *,
    state: dict[str, Any],
    target_binding: dict[str, Any],
    route_id: Any,
    transition: dict[str, Any],
) -> bool:
    if manifest is None:
        return False
    source_artifacts = manifest.get("source_artifacts")
    return (
        manifest.get("schema_version") == 1
        and manifest.get("record_type") == "historical_route_backfill"
        and manifest.get("problem_id") == state.get("problem_id")
        and manifest.get("target_id") == target_binding.get("target_id")
        and manifest.get("target_sha256") == target_binding.get("artifact_sha256")
        and manifest.get("route_id") == route_id
        and manifest.get("initial_status") == transition.get("to_status")
        and is_nonempty_str(manifest.get("backfilled_at"))
        and isinstance(source_artifacts, list)
        and bool(source_artifacts)
        and all(
            isinstance(item, dict)
            and artifact_matches_sha256(
                item.get("path"), item.get("sha256"), state_path
            )
            for item in source_artifacts
        )
        and any(
            isinstance(item, dict)
            and same_artifact(
                item.get("path"), transition.get("evidence"), state_path
            )
            and item.get("sha256") == transition.get("evidence_sha256")
            for item in source_artifacts
        )
    )


def waiver_assessment_matches(
    manifest: Optional[dict[str, Any]],
    state_path: Path,
    *,
    state: dict[str, Any],
    target_binding: dict[str, Any],
    outcome_record: dict[str, Any],
) -> bool:
    if manifest is None:
        return False
    assessments = manifest.get("operator_assessments")
    if not isinstance(assessments, list):
        return False
    operators = [
        item.get("operator") for item in assessments if isinstance(item, dict)
    ]
    return (
        manifest.get("schema_version") == 1
        and manifest.get("record_type")
        == "redirected_wave_waiver_assessment"
        and manifest.get("problem_id") == state.get("problem_id")
        and manifest.get("target_id") == target_binding.get("target_id")
        and manifest.get("target_sha256") == target_binding.get("artifact_sha256")
        and same_artifact(
            manifest.get("initial_wave_manifest"),
            outcome_record.get("initial_wave_manifest"),
            state_path,
        )
        and manifest.get("initial_wave_manifest_sha256")
        == outcome_record.get("initial_wave_manifest_sha256")
        and manifest.get("impossibility_claim")
        == outcome_record.get("redirected_wave_waiver_reason")
        and len(operators) == len(set(operators))
        and set(operators) == DISCOVERY_OPERATORS
        and all(
            isinstance(item, dict)
            and item.get("status") in {"TESTED", "UNAVAILABLE", "NOT_APPLICABLE"}
            and is_nonempty_str(item.get("reason"))
            for item in assessments
        )
    )


def wave_manifest_matches(
    manifest: Optional[dict[str, Any]],
    state_path: Path,
    *,
    state: dict[str, Any],
    target_binding: dict[str, Any],
    wave_type: str,
    report: Any,
    report_sha256: Any,
    initial_wave_manifest: Any = None,
    initial_wave_manifest_sha256: Any = None,
) -> bool:
    if manifest is None:
        return False
    manifest_route_ids = manifest.get("route_ids") if manifest else None
    state_route_ids = {
        route.get("id")
        for route in state.get("routes", [])
        if isinstance(route, dict) and isinstance(route.get("id"), str)
    }
    failure_artifacts = manifest.get("failure_artifacts") if manifest else None
    base = (
        manifest.get("schema_version") == 1
        and manifest.get("record_type") == "proof_search_wave"
        and manifest.get("wave_type") == wave_type
        and manifest.get("problem_id") == state.get("problem_id")
        and manifest.get("target_id") == target_binding.get("target_id")
        and manifest.get("target_sha256") == target_binding.get("artifact_sha256")
        and type(manifest.get("round_number")) is int
        and type(state.get("current_round")) is int
        and 0 <= manifest.get("round_number") <= state.get("current_round")
        and same_artifact(manifest.get("report"), report, state_path)
        and manifest.get("report_sha256") == report_sha256
        and is_nonempty_str_list(manifest.get("route_ids"))
        and set(manifest_route_ids).issubset(state_route_ids)
        and is_nonempty_str_list(manifest.get("mechanisms_tested"))
        and is_str_list(failure_artifacts)
        and all(
            research_artifact_exists(failure_artifact, state_path)
            for failure_artifact in failure_artifacts
        )
    )
    if not base:
        return False
    if wave_type == "INITIAL":
        return (
            manifest.get("initial_wave_manifest") is None
            and manifest.get("initial_wave_manifest_sha256") is None
            and manifest.get("triggering_failure_artifacts") == []
            and manifest.get("mechanism_delta") == []
            and manifest.get("discriminating_question") is None
        )
    initial_manifest = load_json_artifact(initial_wave_manifest, state_path)
    if wave_type == "REDIRECTED" and initial_manifest is not None:
        triggering = manifest.get("triggering_failure_artifacts")
        initial_failures = initial_manifest.get("failure_artifacts")
        mechanism_delta = manifest.get("mechanism_delta")
        initial_mechanisms = initial_manifest.get("mechanisms_tested")
        return (
            same_artifact(
                manifest.get("initial_wave_manifest"),
                initial_wave_manifest,
                state_path,
            )
            and manifest.get("initial_wave_manifest_sha256")
            == initial_wave_manifest_sha256
            and artifact_matches_sha256(
                initial_wave_manifest, initial_wave_manifest_sha256, state_path
            )
            and type(initial_manifest.get("round_number")) is int
            and manifest.get("round_number") > initial_manifest.get("round_number")
            and is_nonempty_str_list(triggering)
            and is_str_list(initial_failures)
            and set(triggering).issubset(set(initial_failures))
            and is_nonempty_str_list(mechanism_delta)
            and is_nonempty_str_list(initial_mechanisms)
            and len(mechanism_delta) == len(set(mechanism_delta))
            and set(mechanism_delta).isdisjoint(set(initial_mechanisms))
            and all(item in manifest.get("mechanisms_tested", []) for item in mechanism_delta)
            and is_nonempty_str(manifest.get("discriminating_question"))
        )
    return False


def waiver_manifest_matches(
    manifest: Optional[dict[str, Any]],
    state_path: Path,
    *,
    state: dict[str, Any],
    target_binding: dict[str, Any],
    outcome_record: dict[str, Any],
) -> bool:
    if manifest is None:
        return False
    assessment_manifest = load_json_artifact(
        outcome_record.get("waiver_assessment"), state_path
    )
    unavailable_from_assessment = (
        [
            item.get("operator")
            for item in assessment_manifest.get("operator_assessments", [])
            if isinstance(item, dict)
            and item.get("status") in {"UNAVAILABLE", "NOT_APPLICABLE"}
        ]
        if isinstance(assessment_manifest, dict)
        else []
    )
    return (
        manifest.get("schema_version") == 1
        and manifest.get("record_type") == "redirected_wave_waiver"
        and manifest.get("problem_id") == state.get("problem_id")
        and manifest.get("target_id") == target_binding.get("target_id")
        and manifest.get("target_sha256") == target_binding.get("artifact_sha256")
        and manifest.get("reason")
        == outcome_record.get("redirected_wave_waiver_reason")
        and same_artifact(
            manifest.get("initial_wave_manifest"),
            outcome_record.get("initial_wave_manifest"),
            state_path,
        )
        and manifest.get("initial_wave_manifest_sha256")
        == outcome_record.get("initial_wave_manifest_sha256")
        and same_artifact(
            manifest.get("evidence"),
            outcome_record.get("redirected_wave_waiver_evidence"),
            state_path,
        )
        and manifest.get("evidence_sha256")
        == outcome_record.get("redirected_wave_waiver_evidence_sha256")
        and same_string_set(
            manifest.get("unavailable_operators"), unavailable_from_assessment
        )
        and same_artifact(
            manifest.get("waiver_assessment"),
            outcome_record.get("waiver_assessment"),
            state_path,
        )
        and manifest.get("waiver_assessment_sha256")
        == outcome_record.get("waiver_assessment_sha256")
        and artifact_matches_sha256(
            outcome_record.get("waiver_assessment"),
            outcome_record.get("waiver_assessment_sha256"),
            state_path,
        )
        and waiver_assessment_matches(
            assessment_manifest,
            state_path,
            state=state,
            target_binding=target_binding,
            outcome_record=outcome_record,
        )
    )


def verifier_report_exists(raw: Any, state_path: Path) -> bool:
    artifact = resolve_artifact(raw, state_path)
    if artifact is None:
        return False
    rel = artifact.relative_to(ROOT.resolve())
    in_verifier_dir = "verifier_reports" in rel.parts
    report_named = any(
        token in artifact.name.lower()
        for token in ("verifier", "verification", "audit", "report")
    )
    in_report_area = in_verifier_dir or rel.parts[0] == "research_reports"
    return in_report_area and report_named and artifact.suffix.lower() in {
        ".md",
        ".tex",
        ".pdf",
    }


def validate_state(
    path: Path,
    checks: list[tuple[bool, str]],
    state_override: Optional[dict[str, Any]] = None,
) -> None:
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        rel = str(path)
    state, error = (state_override, None) if state_override is not None else load_state(path)
    add(checks, error is None, f"{rel} parses as JSON-compatible YAML")
    if state is None:
        return

    schema_version = state.get("schema_version")
    problem_id = state.get("problem_id")
    global_status = state.get("global_status")
    mode = state.get("mode")
    orchestration_profile = state.get("orchestration_profile")
    add(
        checks,
        type(schema_version) is int and schema_version == 1,
        f"{rel} schema_version is integer 1",
    )
    add(checks, is_nonempty_str(problem_id), f"{rel} has string problem_id")
    add(
        checks,
        is_allowed_str(global_status, GLOBAL_STATUSES),
        f"{rel} has allowed global_status",
    )
    if global_status == "UNINITIALIZED":
        add(
            checks,
            mode is None or is_allowed_str(mode, SEARCH_MODES),
            f"{rel} uninitialized state has null or allowed mode",
        )
        add(
            checks,
            orchestration_profile is None
            or is_allowed_str(orchestration_profile, ORCHESTRATION_PROFILES),
            f"{rel} uninitialized state has null or allowed orchestration profile",
        )
    else:
        add(
            checks,
            is_allowed_str(mode, SEARCH_MODES),
            f"{rel} initialized state has allowed mode",
        )
        add(
            checks,
            is_allowed_str(orchestration_profile, ORCHESTRATION_PROFILES),
            f"{rel} initialized state has allowed orchestration profile",
        )
    current_round = state.get("current_round")
    add(
        checks,
        type(current_round) is int and current_round >= 0,
        f"{rel} has nonnegative current_round",
    )
    candidate_route_id = state.get("candidate_route_id")
    candidate_proof_id = state.get("candidate_proof_id")
    candidate_artifact_sha256 = state.get("candidate_artifact_sha256")
    add(
        checks,
        candidate_route_id is None or is_nonempty_str(candidate_route_id),
        f"{rel} candidate_route_id is null or nonempty string",
    )
    add(
        checks,
        candidate_proof_id is None or is_nonempty_str(candidate_proof_id),
        f"{rel} candidate_proof_id is null or nonempty string",
    )
    add(
        checks,
        candidate_artifact_sha256 is None or is_sha256(candidate_artifact_sha256),
        f"{rel} candidate_artifact_sha256 is null or SHA-256",
    )
    target_binding = state.get("target_binding")
    add(checks, isinstance(target_binding, dict), f"{rel} has target_binding object")
    target_id = None
    target_artifact = None
    target_artifact_sha256 = None
    if isinstance(target_binding, dict):
        for field in ("target_id", "artifact", "artifact_sha256"):
            add(checks, field in target_binding, f"{rel} target binding records {field}")
        target_id = target_binding.get("target_id")
        target_artifact = target_binding.get("artifact")
        target_artifact_sha256 = target_binding.get("artifact_sha256")
        if global_status == "UNINITIALIZED":
            add(
                checks,
                target_id is None and target_artifact is None and target_artifact_sha256 is None,
                f"{rel} uninitialized target binding is empty",
            )
        else:
            add(checks, is_nonempty_str(target_id), f"{rel} initialized state has target ID")
            add(
                checks,
                role_artifact_exists(target_artifact, path, "target"),
                f"{rel} initialized state has typed target artifact",
            )
            add(
                checks,
                artifact_matches_sha256(target_artifact, target_artifact_sha256, path),
                f"{rel} target artifact digest matches",
            )
            add(
                checks,
                text_artifact_contains(
                    target_artifact,
                    [
                        token
                        for token in (problem_id, target_id)
                        if isinstance(token, str)
                    ],
                    path,
                ),
                f"{rel} target artifact binds problem and target IDs",
            )
    for field in (
        "information_partitions_recorded",
        "statement_frozen",
        "attack_surface_ready",
        "approach_registry_ready",
        "independent_refutation_active",
    ):
        add(checks, type(state.get(field)) is bool, f"{rel} has boolean {field}")

    if mode == "MIXED_WITH_PARTITIONS":
        add(
            checks,
            state.get("information_partitions_recorded") is True,
            f"{rel} mixed mode records information partitions",
        )

    candidate_lineage = state.get("candidate_lineage")
    add(checks, isinstance(candidate_lineage, dict), f"{rel} has candidate_lineage object")
    originating_run_ids: list[str] = []
    material_repair_run_ids: list[str] = []
    if isinstance(candidate_lineage, dict):
        for field in (
            "originating_run_ids",
            "material_repair_run_ids",
            "lineage_artifact",
            "lineage_artifact_sha256",
        ):
            add(checks, field in candidate_lineage, f"{rel} candidate lineage records {field}")
        raw_originating = candidate_lineage.get("originating_run_ids")
        raw_repairs = candidate_lineage.get("material_repair_run_ids")
        add(checks, is_str_list(raw_originating), f"{rel} originating run IDs are strings")
        add(checks, is_str_list(raw_repairs), f"{rel} material-repair run IDs are strings")
        if is_str_list(raw_originating):
            originating_run_ids = raw_originating
            add(
                checks,
                len(originating_run_ids) == len(set(originating_run_ids)),
                f"{rel} originating run IDs are unique",
            )
        if is_str_list(raw_repairs):
            material_repair_run_ids = raw_repairs
            add(
                checks,
                len(material_repair_run_ids) == len(set(material_repair_run_ids)),
                f"{rel} material-repair run IDs are unique",
            )

    closure_evidence = state.get("closure_evidence")
    verifier = state.get("independent_verifier")
    add(checks, isinstance(verifier, dict), f"{rel} has independent_verifier object")
    if isinstance(verifier, dict):
        for field in (
            "id",
            "candidate_id",
            "candidate_artifact_sha256",
            "report_sha256",
            "exposure_log",
            "exposure_log_sha256",
            "exposure_manifest",
            "exposure_manifest_sha256",
            "audit_packet",
            "audit_packet_sha256",
            "report_manifest",
            "report_manifest_sha256",
        ):
            add(checks, field in verifier, f"{rel} verifier records {field}")
        for field in ("required", "assigned", "completed"):
            add(
                checks,
                type(verifier.get(field)) is bool,
                f"{rel} verifier has boolean {field}",
            )
        add(
            checks,
            verifier.get("independent_of_candidate") is None
            or type(verifier.get("independent_of_candidate")) is bool,
            f"{rel} verifier independence flag is null or boolean",
        )
        independence_level = verifier.get("independence_level")
        verdict = verifier.get("verdict")
        add(
            checks,
            independence_level is None
            or is_allowed_str(independence_level, {"I0", "I1", "I2", "I3"}),
            f"{rel} verifier has allowed independence level",
        )
        add(
            checks,
            verdict is None
            or is_allowed_str(verdict, {"PASS", "FAIL", "INCONCLUSIVE", "VERIFIED"}),
            f"{rel} verifier has allowed verdict",
        )
        if verifier.get("completed") is True:
            add(
                checks,
                verifier.get("assigned") is True,
                f"{rel} completed verifier was assigned",
            )
            add(
                checks,
                is_allowed_str(independence_level, {"I0", "I1", "I2", "I3"}),
                f"{rel} completed verifier records independence level",
            )
            add(
                checks,
                is_allowed_str(verdict, {"PASS", "FAIL", "INCONCLUSIVE", "VERIFIED"}),
                f"{rel} completed verifier records verdict",
            )
            add(
                checks,
                verifier_report_exists(verifier.get("report"), path),
                f"{rel} completed verifier report exists in a verifier-report area",
            )
            add(
                checks,
                artifact_matches_sha256(
                    verifier.get("report"), verifier.get("report_sha256"), path
                ),
                f"{rel} completed verifier report digest matches",
            )
            add(
                checks,
                report_binds_candidate(
                    verifier.get("report"),
                    verifier.get("candidate_id"),
                    verifier.get("candidate_artifact_sha256"),
                    verifier.get("id"),
                    path,
                    required_tokens=(
                        [
                            token
                            for token in (
                                target_id,
                                target_artifact_sha256,
                                verdict,
                                independence_level,
                                "Highest surviving gap",
                            )
                            if isinstance(token, str)
                        ]
                        + (
                            [
                                "Unresolved objections",
                                "Required repairs",
                            ]
                            if verdict not in {"PASS", "VERIFIED"}
                            else []
                        )
                    ),
                )
                and (
                    verdict not in {"PASS", "VERIFIED"}
                    or report_records_no_unresolved_issues(
                        verifier.get("report"), path
                    )
                ),
                f"{rel} completed verifier report binds verifier and candidate",
            )
            report_tokens = [
                token
                for token in [
                    problem_id,
                    target_id,
                    target_artifact_sha256,
                    verifier.get("id"),
                    verifier.get("candidate_id"),
                    verifier.get("candidate_artifact_sha256"),
                ]
                + originating_run_ids
                + material_repair_run_ids
                if isinstance(token, str)
            ]
            add(
                checks,
                text_artifact_contains(verifier.get("report"), report_tokens, path)
                or text_artifact_contains(
                    verifier.get("exposure_log"), report_tokens, path
                ),
                f"{rel} completed verifier evidence bundle records all lineage IDs",
            )
            add(
                checks,
                role_artifact_exists(
                    verifier.get("report_manifest"), path, "report_manifest"
                ),
                f"{rel} completed verifier has typed report manifest",
            )
            add(
                checks,
                artifact_matches_sha256(
                    verifier.get("report_manifest"),
                    verifier.get("report_manifest_sha256"),
                    path,
                ),
                f"{rel} completed verifier report-manifest digest matches",
            )
            add(
                checks,
                report_manifest_matches(
                    load_json_artifact(verifier.get("report_manifest"), path),
                    path,
                    problem_id=problem_id,
                    target_id=target_id,
                    target_sha256=target_artifact_sha256,
                    candidate_id=verifier.get("candidate_id"),
                    candidate_sha256=verifier.get("candidate_artifact_sha256"),
                    verifier_id=verifier.get("id"),
                    independence_level=independence_level,
                    verdict=verdict,
                    exposure_log=verifier.get("exposure_log"),
                    exposure_log_sha256=verifier.get("exposure_log_sha256"),
                    exposure_manifest=verifier.get("exposure_manifest"),
                    exposure_manifest_sha256=verifier.get(
                        "exposure_manifest_sha256"
                    ),
                    audit_packet=verifier.get("audit_packet"),
                    audit_packet_sha256=verifier.get("audit_packet_sha256"),
                    report=verifier.get("report"),
                    report_sha256=verifier.get("report_sha256"),
                ),
                f"{rel} completed verifier report manifest matches state and verdict",
            )
        if verifier.get("assigned") is True:
            add(
                checks,
                role_artifact_exists(
                    verifier.get("audit_packet"), path, "audit_packet"
                ),
                f"{rel} assigned verifier has typed audit packet",
            )
            add(
                checks,
                artifact_matches_sha256(
                    verifier.get("audit_packet"),
                    verifier.get("audit_packet_sha256"),
                    path,
                ),
                f"{rel} assigned verifier audit-packet digest matches",
            )
            if (
                isinstance(target_binding, dict)
                and isinstance(candidate_lineage, dict)
                and isinstance(closure_evidence, dict)
            ):
                add(
                    checks,
                    audit_packet_matches(
                        load_json_artifact(verifier.get("audit_packet"), path),
                        path,
                        state=state,
                        target_binding=target_binding,
                        candidate_lineage=candidate_lineage,
                        closure_evidence=closure_evidence,
                    ),
                    f"{rel} assigned verifier audit packet binds dependency/evidence snapshot",
                )
            add(
                checks,
                is_nonempty_str(verifier.get("id")),
                f"{rel} assigned verifier has id",
            )
            add(
                checks,
                is_nonempty_str(verifier.get("candidate_id")),
                f"{rel} assigned verifier records frozen candidate ID",
            )
            add(
                checks,
                is_sha256(verifier.get("candidate_artifact_sha256")),
                f"{rel} assigned verifier records frozen candidate digest",
            )
            add(
                checks,
                exposure_log_exists(verifier.get("exposure_log"), path),
                f"{rel} assigned verifier has exposure-lineage artifact",
            )
            add(
                checks,
                artifact_matches_sha256(
                    verifier.get("exposure_log"),
                    verifier.get("exposure_log_sha256"),
                    path,
                ),
                f"{rel} assigned verifier exposure-lineage digest matches",
            )
            add(
                checks,
                report_binds_candidate(
                    verifier.get("exposure_log"),
                    verifier.get("candidate_id"),
                    verifier.get("candidate_artifact_sha256"),
                    verifier.get("id"),
                    path,
                ),
                f"{rel} assigned verifier exposure log binds verifier and candidate",
            )
            exposure_tokens = [
                token
                for token in [
                    problem_id,
                    target_id,
                    target_artifact_sha256,
                    verifier.get("id"),
                    verifier.get("candidate_id"),
                    verifier.get("candidate_artifact_sha256"),
                ]
                + originating_run_ids
                + material_repair_run_ids
                if isinstance(token, str)
            ]
            add(
                checks,
                text_artifact_contains(
                    verifier.get("exposure_log"), exposure_tokens, path
                ),
                f"{rel} assigned verifier exposure log records all lineage IDs",
            )
            add(
                checks,
                role_artifact_exists(
                    verifier.get("exposure_manifest"), path, "exposure_manifest"
                ),
                f"{rel} assigned verifier has typed exposure manifest",
            )
            add(
                checks,
                artifact_matches_sha256(
                    verifier.get("exposure_manifest"),
                    verifier.get("exposure_manifest_sha256"),
                    path,
                ),
                f"{rel} assigned verifier exposure-manifest digest matches",
            )
            add(
                checks,
                exposure_manifest_matches(
                    load_json_artifact(verifier.get("exposure_manifest"), path),
                    path,
                    problem_id=problem_id,
                    target_id=target_id,
                    target_sha256=target_artifact_sha256,
                    candidate_id=verifier.get("candidate_id"),
                    candidate_sha256=verifier.get("candidate_artifact_sha256"),
                    verifier_id=verifier.get("id"),
                    originating_run_ids=originating_run_ids,
                    material_repair_run_ids=material_repair_run_ids,
                    audit_packet=verifier.get("audit_packet"),
                    audit_packet_sha256=verifier.get("audit_packet_sha256"),
                    exposure_log=verifier.get("exposure_log"),
                    exposure_log_sha256=verifier.get("exposure_log_sha256"),
                ),
                f"{rel} assigned verifier exposure manifest matches state",
            )
        if verifier.get("independence_level") == "I3":
            add(
                checks,
                verifier.get("independent_of_candidate") is True,
                f"{rel} I3 verifier is independent of candidate generation/repair",
            )
            add(
                checks,
                is_nonempty_str(verifier.get("id"))
                and verifier.get("id")
                not in set(originating_run_ids + material_repair_run_ids),
                f"{rel} I3 verifier ID is disjoint from generator/material-repair IDs",
            )
        if state.get("candidate_route_id") is not None or state.get("candidate_proof_id") is not None:
            add(
                checks,
                verifier.get("required") is True,
                f"{rel} candidate requires independent verifier",
            )
        if is_allowed_str(
            state.get("global_status"),
            {"VERIFIED_PROOF", "VERIFIED_COUNTEREXAMPLE"},
        ):
            add(
                checks,
                verifier.get("assigned") is True,
                f"{rel} VERIFIED state has assigned verifier",
            )
            add(
                checks,
                verifier.get("completed") is True,
                f"{rel} VERIFIED state has completed verifier",
            )
            add(
                checks,
                is_nonempty_str(verifier.get("report")),
                f"{rel} VERIFIED state names verifier report",
            )
            add(
                checks,
                is_nonempty_str(verifier.get("id")),
                f"{rel} VERIFIED state names decisive verifier",
            )
            add(
                checks,
                verifier.get("independent_of_candidate") is True,
                f"{rel} VERIFIED state records verifier independence",
            )
            add(
                checks,
                verifier.get("independence_level") == "I3",
                f"{rel} VERIFIED state has I3 decisive verifier",
            )
            add(
                checks,
                is_allowed_str(verifier.get("verdict"), {"PASS", "VERIFIED"}),
                f"{rel} VERIFIED state has passing verifier verdict",
            )
            report = verifier.get("report")
            add(
                checks,
                verifier_report_exists(report, path),
                f"{rel} VERIFIED state verifier report exists in a verifier-report area",
            )

    historical_verifiers = state.get("historical_verifiers")
    add(checks, isinstance(historical_verifiers, list), f"{rel} has historical_verifiers list")
    if isinstance(historical_verifiers, list):
        historical_ids: set[str] = set()
        for index, historical in enumerate(historical_verifiers):
            label = f"{rel} historical_verifier[{index}]"
            add(checks, isinstance(historical, dict), f"{label} is an object")
            if not isinstance(historical, dict):
                continue
            verifier_id = historical.get("id")
            add(checks, is_nonempty_str(verifier_id), f"{label} has id")
            add(
                checks,
                isinstance(verifier_id, str) and verifier_id not in historical_ids,
                f"{label} id is unique",
            )
            if isinstance(verifier_id, str):
                historical_ids.add(verifier_id)
            add(
                checks,
                is_allowed_str(
                    historical.get("independence_level"),
                    {"I0", "I1", "I2", "I3"},
                ),
                f"{label} has allowed independence level",
            )
            add(checks, type(historical.get("completed")) is bool, f"{label} has completed flag")
            add(checks, type(historical.get("decisive")) is bool, f"{label} has decisive flag")
            add(
                checks,
                is_allowed_str(
                    historical.get("verdict"),
                    {"PASS", "FAIL", "INCONCLUSIVE", "VERIFIED"},
                ),
                f"{label} has allowed verdict",
            )
            add(
                checks,
                is_nonempty_str(historical.get("candidate_id")),
                f"{label} records candidate ID",
            )
            if historical.get("completed") is True:
                add(
                    checks,
                    verifier_report_exists(historical.get("report"), path),
                    f"{label} report exists in a verifier-report area",
                )
                add(
                    checks,
                    research_artifact_exists(historical.get("candidate_artifact"), path),
                    f"{label} candidate artifact exists",
                )
                add(
                    checks,
                    artifact_matches_sha256(
                        historical.get("candidate_artifact"),
                        historical.get("candidate_artifact_sha256"),
                        path,
                    ),
                    f"{label} candidate digest matches",
                )
                add(
                    checks,
                    artifact_matches_sha256(
                        historical.get("report"), historical.get("report_sha256"), path
                    ),
                    f"{label} report digest matches",
                )
            if historical.get("decisive") is True:
                add(
                    checks,
                    historical.get("completed") is True
                    and historical.get("independence_level") == "I3"
                    and is_allowed_str(
                        historical.get("verdict"), {"PASS", "VERIFIED"}
                    ),
                    f"{label} decisive audit is completed passing I3",
                )
                add(
                    checks,
                    report_binds_candidate(
                        historical.get("report"),
                        historical.get("candidate_id"),
                        historical.get("candidate_artifact_sha256"),
                        historical.get("id"),
                        path,
                    ),
                    f"{label} decisive report binds verifier and candidate",
                )
        if isinstance(verifier, dict) and verifier.get("assigned") is True:
            add(
                checks,
                all(
                    not isinstance(historical, dict)
                    or historical.get("id") != verifier.get("id")
                    for historical in historical_verifiers
                ),
                f"{rel} decisive verifier run ID has no prior historical exposure record",
            )

    closure_evidence = state.get("closure_evidence")
    add(checks, isinstance(closure_evidence, dict), f"{rel} has closure_evidence object")
    if isinstance(closure_evidence, dict):
        for field in (
            "candidate_id",
            "candidate_artifact",
            "candidate_artifact_sha256",
            "proof_obligations",
            "proof_obligations_sha256",
            "proof_obligations_manifest",
            "proof_obligations_manifest_sha256",
            "source_audit",
            "source_audit_sha256",
            "source_audit_manifest",
            "source_audit_manifest_sha256",
            "attack_surface_exit",
            "attack_surface_exit_sha256",
            "attack_surface_exit_manifest",
            "attack_surface_exit_manifest_sha256",
            "dependency_snapshot",
            "dependency_snapshot_sha256",
            "audit_packet",
            "audit_packet_sha256",
            "closure_manifest",
            "closure_manifest_sha256",
        ):
            add(checks, field in closure_evidence, f"{rel} closure evidence records {field}")
        if isinstance(verifier, dict) and verifier.get("assigned") is True:
            add(
                checks,
                is_nonempty_str(closure_evidence.get("candidate_id"))
                and verifier.get("candidate_id") == closure_evidence.get("candidate_id"),
                f"{rel} assigned verifier audits the frozen closure candidate ID",
            )
            add(
                checks,
                is_sha256(closure_evidence.get("candidate_artifact_sha256"))
                and verifier.get("candidate_artifact_sha256")
                == closure_evidence.get("candidate_artifact_sha256"),
                f"{rel} assigned verifier audits the frozen closure candidate digest",
            )

    outcome_record = state.get("outcome_record")
    add(checks, isinstance(outcome_record, dict), f"{rel} has outcome_record object")
    if isinstance(outcome_record, dict):
        for field in (
            "exact_assumptions",
            "strongest_result",
            "strongest_artifact",
            "exact_remaining_gaps",
            "exhaustion_rationale",
            "redirected_wave_completed",
            "redirected_wave_waiver",
            "redirected_wave_waiver_reason",
            "redirected_wave_waiver_evidence",
            "redirected_wave_waiver_evidence_sha256",
            "initial_wave_report",
            "initial_wave_report_sha256",
            "redirected_wave_report",
            "redirected_wave_report_sha256",
            "initial_wave_manifest",
            "initial_wave_manifest_sha256",
            "redirected_wave_manifest",
            "redirected_wave_manifest_sha256",
            "waiver_manifest",
            "waiver_manifest_sha256",
            "waiver_assessment",
            "waiver_assessment_sha256",
        ):
            add(checks, field in outcome_record, f"{rel} outcome record includes {field}")
        add(
            checks,
            is_str_list(outcome_record.get("exact_assumptions")),
            f"{rel} outcome assumptions are a list",
        )
        add(
            checks,
            is_str_list(outcome_record.get("exact_remaining_gaps")),
            f"{rel} outcome gaps are a list",
        )
        add(
            checks,
            type(outcome_record.get("redirected_wave_completed")) is bool,
            f"{rel} outcome redirected-wave flag is boolean",
        )
        add(
            checks,
            type(outcome_record.get("redirected_wave_waiver")) is bool,
            f"{rel} outcome redirected-wave waiver flag is boolean",
        )

    routes = state.get("routes")
    add(checks, isinstance(routes, list), f"{rel} has routes list")
    if not isinstance(routes, list):
        return
    route_ids: set[str] = set()
    for index, route in enumerate(routes):
        label = f"{rel} route[{index}]"
        add(checks, isinstance(route, dict), f"{label} is an object")
        if not isinstance(route, dict):
            continue
        route_id = route.get("id")
        add(checks, is_nonempty_str(route_id), f"{label} has id")
        add(
            checks,
            isinstance(route_id, str) and route_id not in route_ids,
            f"{label} id is unique",
        )
        if isinstance(route_id, str):
            route_ids.add(route_id)
        family = route.get("family")
        fingerprint = route.get("idea_fingerprint")
        lineage = route.get("independence_lineage")
        add(
            checks,
            is_nonempty_str(family),
            f"{label} has family",
        )
        add(
            checks,
            is_nonempty_str(fingerprint),
            f"{label} has idea fingerprint",
        )
        add(
            checks,
            is_allowed_str(route.get("status"), ROUTE_STATUSES),
            f"{label} has allowed status",
        )
        add(
            checks,
            is_allowed_str(route.get("gap_class"), GAP_CLASSES),
            f"{label} has allowed gap class",
        )
        add(
            checks,
            is_nonempty_str(lineage),
            f"{label} records independence lineage",
        )
        strongest_artifact = route.get("strongest_artifact")
        route_candidate_id = route.get("candidate_id")
        strongest_artifact_sha256 = route.get("strongest_artifact_sha256")
        exact_gap = route.get("exact_gap")
        gap_id = route.get("gap_id")
        exact_gap_sha256 = route.get("exact_gap_sha256")
        source_gate = route.get("source_gate")
        verification_gate = route.get("verification_gate")
        novelty_gate = route.get("novelty_gate")
        add(checks, "strongest_artifact" in route, f"{label} records strongest artifact")
        add(checks, "candidate_id" in route, f"{label} records candidate ID field")
        add(
            checks,
            route_candidate_id is None or is_nonempty_str(route_candidate_id),
            f"{label} candidate ID is null or nonempty string",
        )
        add(
            checks,
            strongest_artifact_sha256 is None or is_sha256(strongest_artifact_sha256),
            f"{label} strongest-artifact digest is null or SHA-256",
        )
        add(checks, isinstance(exact_gap, str), f"{label} records exact gap string")
        add(checks, is_nonempty_str(gap_id), f"{label} records stable gap ID")
        add(
            checks,
            isinstance(exact_gap, str)
            and is_sha256(exact_gap_sha256)
            and text_sha256(exact_gap) == exact_gap_sha256,
            f"{label} exact-gap digest matches",
        )
        add(
            checks,
            is_allowed_str(source_gate, SOURCE_GATES),
            f"{label} has allowed source gate",
        )
        add(
            checks,
            is_allowed_str(verification_gate, VERIFICATION_GATES),
            f"{label} has allowed verification gate",
        )
        add(
            checks,
            is_allowed_str(novelty_gate, NOVELTY_GATES),
            f"{label} has allowed novelty gate",
        )
        parent_route_ids = route.get("parent_route_ids")
        inherited_gaps = route.get("inherited_gaps")
        transitions = route.get("transitions")
        add(checks, is_str_list(parent_route_ids), f"{label} parent route IDs are strings")
        if is_str_list(parent_route_ids):
            add(
                checks,
                len(parent_route_ids) == len(set(parent_route_ids)),
                f"{label} parent route IDs are unique",
            )
        add(checks, isinstance(inherited_gaps, list), f"{label} has inherited-gaps list")
        inherited_gap_ids: set[str] = set()
        if isinstance(inherited_gaps, list):
            for gap_index, inherited_gap in enumerate(inherited_gaps):
                gap_label = f"{label} inherited_gap[{gap_index}]"
                add(checks, isinstance(inherited_gap, dict), f"{gap_label} is an object")
                if not isinstance(inherited_gap, dict):
                    continue
                inherited_gap_id = inherited_gap.get("id")
                add(checks, is_nonempty_str(inherited_gap_id), f"{gap_label} has id")
                add(
                    checks,
                    isinstance(inherited_gap_id, str)
                    and inherited_gap_id not in inherited_gap_ids,
                    f"{gap_label} id is unique",
                )
                if isinstance(inherited_gap_id, str):
                    inherited_gap_ids.add(inherited_gap_id)
                add(
                    checks,
                    is_nonempty_str(inherited_gap.get("source_route_id")),
                    f"{gap_label} names source route",
                )
                add(
                    checks,
                    is_nonempty_str(inherited_gap.get("source_gap_id")),
                    f"{gap_label} names source gap ID",
                )
                add(
                    checks,
                    is_allowed_str(inherited_gap.get("source_gap_class"), GAP_CLASSES),
                    f"{gap_label} has source gap class",
                )
                add(
                    checks,
                    is_sha256(inherited_gap.get("source_gap_statement_sha256")),
                    f"{gap_label} has source gap-statement digest",
                )
                add(
                    checks,
                    is_allowed_str(inherited_gap.get("status"), {"OPEN", "CLOSED"}),
                    f"{gap_label} has open/closed status",
                )
                if inherited_gap.get("status") == "CLOSED":
                    add(
                        checks,
                        research_artifact_exists(inherited_gap.get("evidence"), path),
                        f"{gap_label} has discharge evidence",
                    )
                    add(
                        checks,
                        artifact_matches_sha256(
                            inherited_gap.get("evidence"),
                            inherited_gap.get("evidence_sha256"),
                            path,
                        ),
                        f"{gap_label} discharge-evidence digest matches",
                    )
                    add(
                        checks,
                        role_artifact_exists(
                            inherited_gap.get("discharge_manifest"),
                            path,
                            "gap_discharge_manifest",
                        ),
                        f"{gap_label} has typed discharge manifest",
                    )
                    add(
                        checks,
                        artifact_matches_sha256(
                            inherited_gap.get("discharge_manifest"),
                            inherited_gap.get("discharge_manifest_sha256"),
                            path,
                        ),
                        f"{gap_label} discharge-manifest digest matches",
                    )
        add(
            checks,
            route.get("merged_into") is None or is_nonempty_str(route.get("merged_into")),
            f"{label} merged_into is null or route ID",
        )
        add(checks, isinstance(transitions, list) and bool(transitions), f"{label} has transition history")
        previous_to: Optional[str] = None
        previous_round: Optional[int] = None
        if isinstance(transitions, list):
            for transition_index, transition in enumerate(transitions):
                transition_label = f"{label} transition[{transition_index}]"
                add(checks, isinstance(transition, dict), f"{transition_label} is an object")
                if not isinstance(transition, dict):
                    continue
                from_status = transition.get("from_status")
                to_status = transition.get("to_status")
                add(
                    checks,
                    from_status is None or is_allowed_str(from_status, ROUTE_STATUSES),
                    f"{transition_label} has allowed from_status",
                )
                add(
                    checks,
                    is_allowed_str(to_status, ROUTE_STATUSES),
                    f"{transition_label} has allowed to_status",
                )
                transition_round = transition.get("round")
                add(
                    checks,
                    type(transition_round) is int
                    and transition_round >= 0
                    and type(current_round) is int
                    and transition_round <= current_round,
                    f"{transition_label} has valid round",
                )
                if transition_index == 0:
                    initialization_kind = transition.get("initialization_kind")
                    add(
                        checks,
                        from_status is None,
                        f"{transition_label} initial transition starts from null",
                    )
                    add(
                        checks,
                        initialization_kind in {"NEW_SEED", "HISTORICAL_BACKFILL"},
                        f"{transition_label} records initialization kind",
                    )
                    if initialization_kind == "NEW_SEED":
                        add(
                            checks,
                            to_status == "SEED",
                            f"{transition_label} new route initializes as SEED",
                        )
                    if initialization_kind == "HISTORICAL_BACKFILL":
                        add(
                            checks,
                            is_allowed_str(
                                to_status,
                                {"SEED", "CANDIDATE", "BLOCKED", "REFUTED", "PARKED"},
                            ),
                            f"{transition_label} historical backfill uses allowed initial status",
                        )
                        add(
                            checks,
                            role_artifact_exists(
                                transition.get("backfill_manifest"),
                                path,
                                "backfill_manifest",
                            ),
                            f"{transition_label} has typed historical-backfill manifest",
                        )
                        add(
                            checks,
                            artifact_matches_sha256(
                                transition.get("backfill_manifest"),
                                transition.get("backfill_manifest_sha256"),
                                path,
                            ),
                            f"{transition_label} historical-backfill manifest digest matches",
                        )
                        if isinstance(target_binding, dict):
                            add(
                                checks,
                                historical_backfill_manifest_matches(
                                    load_json_artifact(
                                        transition.get("backfill_manifest"), path
                                    ),
                                    path,
                                    state=state,
                                    target_binding=target_binding,
                                    route_id=route_id,
                                    transition=transition,
                                ),
                                f"{transition_label} historical backfill binds target, route, and sources",
                            )
                else:
                    add(
                        checks,
                        isinstance(from_status, str)
                        and is_allowed_str(to_status, ALLOWED_ROUTE_TRANSITIONS.get(from_status, set())),
                        f"{transition_label} follows allowed transition graph",
                    )
                if previous_round is not None:
                    add(
                        checks,
                        type(transition_round) is int and transition_round >= previous_round,
                        f"{transition_label} round is nondecreasing",
                    )
                add(
                    checks,
                    is_nonempty_str(transition.get("reason")),
                    f"{transition_label} records reason",
                )
                add(
                    checks,
                    research_artifact_exists(transition.get("evidence"), path),
                    f"{transition_label} evidence exists",
                )
                add(
                    checks,
                    artifact_matches_sha256(
                        transition.get("evidence"),
                        transition.get("evidence_sha256"),
                        path,
                    ),
                    f"{transition_label} evidence digest matches",
                )
                if transition_index > 0:
                    add(
                        checks,
                        from_status == previous_to,
                        f"{transition_label} continues prior status",
                    )
                if from_status == "REFUTED":
                    add(checks, False, f"{transition_label} does not reopen REFUTED route")
                if from_status == "BLOCKED" and is_allowed_str(
                    to_status, ALLOWED_ROUTE_TRANSITIONS["BLOCKED"]
                ):
                    add(
                        checks,
                        is_allowed_str(transition.get("reopen_basis"), REOPEN_BASES),
                        f"{transition_label} has authorized reopen basis",
                    )
                    add(
                        checks,
                        is_nonempty_str(transition.get("blocked_gap_id")),
                        f"{transition_label} records blocked gap ID",
                    )
                    add(
                        checks,
                        is_allowed_str(
                            transition.get("blocked_gap_class"), {"GS3", "GS4"}
                        ),
                        f"{transition_label} records blocked gap class",
                    )
                    add(
                        checks,
                        is_sha256(transition.get("blocked_gap_statement_sha256")),
                        f"{transition_label} records blocked gap-statement digest",
                    )
                    add(
                        checks,
                        research_artifact_exists(
                            transition.get("reopen_evidence"), path
                        ),
                        f"{transition_label} has checked reopen evidence",
                    )
                    add(
                        checks,
                        artifact_matches_sha256(
                            transition.get("reopen_evidence"),
                            transition.get("reopen_evidence_sha256"),
                            path,
                        ),
                        f"{transition_label} reopen-evidence digest matches",
                    )
                    if to_status in {"CANDIDATE", "UNDER_AUDIT"}:
                        add(
                            checks,
                            transition.get("result_candidate_id") == route_candidate_id,
                            f"{transition_label} result candidate ID matches route",
                        )
                        add(
                            checks,
                            transition.get("result_candidate_sha256")
                            == strongest_artifact_sha256,
                            f"{transition_label} result candidate digest matches route",
                        )
                    add(
                        checks,
                        role_artifact_exists(
                            transition.get("reopen_manifest"), path, "reopen_manifest"
                        ),
                        f"{transition_label} has typed reopen manifest",
                    )
                    add(
                        checks,
                        artifact_matches_sha256(
                            transition.get("reopen_manifest"),
                            transition.get("reopen_manifest_sha256"),
                            path,
                        ),
                        f"{transition_label} reopen-manifest digest matches",
                    )
                    add(
                        checks,
                        reopen_manifest_matches(
                            load_json_artifact(transition.get("reopen_manifest"), path),
                            path,
                            state=state,
                            target_binding=target_binding,
                            route_id=route_id,
                            transition=transition,
                        ),
                        f"{transition_label} typed reopen manifest binds blocker and evidence",
                    )
                previous_to = to_status if isinstance(to_status, str) else None
                previous_round = transition_round if type(transition_round) is int else previous_round
            if transitions:
                add(
                    checks,
                    isinstance(transitions[-1], dict)
                    and transitions[-1].get("to_status") == route.get("status"),
                    f"{label} current status matches final transition",
                )
        if is_allowed_str(
            route.get("status"),
            {"CANDIDATE", "UNDER_AUDIT", "CLOSED_PROOF", "CLOSED_COUNTEREXAMPLE"},
        ):
            add(
                checks,
                research_artifact_exists(strongest_artifact, path),
                f"{label} candidate/closed route research artifact exists",
            )
            add(
                checks,
                is_nonempty_str(route_candidate_id),
                f"{label} candidate/closed route has canonical candidate ID",
            )
            add(
                checks,
                artifact_matches_sha256(
                    strongest_artifact, strongest_artifact_sha256, path
                ),
                f"{label} candidate/closed route artifact digest matches",
            )
        if route.get("status") == "BLOCKED":
            add(checks, is_nonempty_str(exact_gap), f"{label} blocked route records exact gap")
            add(
                checks,
                is_allowed_str(route.get("gap_class"), {"GS3", "GS4"}),
                f"{label} blocked route has GS3/GS4",
            )
            add(checks, is_nonempty_str(route.get("blocked_reason")), f"{label} records blocker")
            add(
                checks,
                is_nonempty_str(route.get("reopen_condition")),
                f"{label} records reopen condition",
            )
        if is_allowed_str(
            route.get("status"),
            {"SEED", "ACTIVE", "CANDIDATE", "UNDER_AUDIT"},
        ):
            add(
                checks,
                is_allowed_str(route.get("gap_class"), GAP_CLASSES)
                and route.get("gap_class") not in {"GS4", "GS5"},
                f"{label} live route has no GS4/GS5",
            )
        if is_allowed_str(
            route.get("status"), {"CLOSED_PROOF", "CLOSED_COUNTEREXAMPLE"}
        ):
            add(checks, route.get("gap_class") == "GS0", f"{label} closed route has GS0")
            add(
                checks,
                is_allowed_str(source_gate, {"CLOSED", "NOT_APPLICABLE"}),
                f"{label} closed route has closed or inapplicable source gate",
            )
            add(
                checks,
                verification_gate == "I3_PASSED",
                f"{label} closed route has passed I3 verification gate",
            )
        if route.get("status") == "REFUTED":
            add(checks, route.get("gap_class") == "GS5", f"{label} refuted route has GS5")
            add(
                checks,
                research_artifact_exists(strongest_artifact, path),
                f"{label} refuted route fatal-witness artifact exists in research area",
            )

    routes_by_id = {
        route.get("id"): route
        for route in routes
        if isinstance(route, dict) and isinstance(route.get("id"), str)
    }
    add(
        checks,
        dependency_graph_is_acyclic(routes_by_id),
        f"{rel} route dependency graph is acyclic",
    )
    for route_id, route in routes_by_id.items():
        label = f"{rel} route[{route_id}]"
        parents = route.get("parent_route_ids")
        inherited = route.get("inherited_gaps")
        if is_str_list(parents):
            add(
                checks,
                all(parent_id in routes_by_id and parent_id != route_id for parent_id in parents),
                f"{label} parent routes exist and are not self",
            )
            inherited_source_ids = (
                {
                    item.get("source_route_id")
                    for item in inherited
                    if isinstance(item, dict)
                }
                if isinstance(inherited, list)
                else set()
            )
            for parent_id in parents:
                parent = routes_by_id.get(parent_id)
                if isinstance(parent, dict) and parent.get("gap_class") != "GS0":
                    add(
                        checks,
                        parent_id in inherited_source_ids,
                        f"{label} inherits unresolved gap from parent {parent_id}",
                    )
        if isinstance(inherited, list):
            for inherited_gap in inherited:
                if not isinstance(inherited_gap, dict):
                    continue
                source_route_id = inherited_gap.get("source_route_id")
                source_route = routes_by_id.get(source_route_id)
                add(
                    checks,
                    isinstance(source_route, dict),
                    f"{label} inherited gap names existing source route",
                )
                if isinstance(source_route, dict):
                    add(
                        checks,
                        inherited_gap.get("source_gap_id") == source_route.get("gap_id"),
                        f"{label} inherited gap ID matches parent",
                    )
                    add(
                        checks,
                        inherited_gap.get("source_gap_class")
                        == source_route.get("gap_class"),
                        f"{label} inherited gap class matches parent",
                    )
                    add(
                        checks,
                        inherited_gap.get("source_gap_statement_sha256")
                        == source_route.get("exact_gap_sha256"),
                        f"{label} inherited gap statement digest matches parent",
                    )
                if inherited_gap.get("status") == "CLOSED":
                    add(
                        checks,
                        gap_discharge_manifest_matches(
                            load_json_artifact(
                                inherited_gap.get("discharge_manifest"), path
                            ),
                            path,
                            state=state,
                            target_binding=target_binding,
                            child_route_id=route_id,
                            inherited_gap=inherited_gap,
                        ),
                        f"{label} typed discharge manifest binds exact parent gap",
                    )
            open_inherited = [
                item
                for item in inherited
                if isinstance(item, dict) and item.get("status") == "OPEN"
            ]
            if open_inherited:
                add(
                    checks,
                    route.get("gap_class") != "GS0"
                    and not is_allowed_str(
                        route.get("status"),
                        {"CLOSED_PROOF", "CLOSED_COUNTEREXAMPLE"},
                    ),
                    f"{label} cannot close while inherited gaps remain open",
                )
        if route.get("status") == "MERGED":
            merged_into = route.get("merged_into")
            add(
                checks,
                isinstance(merged_into, str)
                and merged_into in routes_by_id
                and merged_into != route_id,
                f"{label} MERGED route names surviving route",
            )
            surviving_route = routes_by_id.get(merged_into)
            add(
                checks,
                isinstance(surviving_route, dict)
                and route_id in surviving_route.get("parent_route_ids", []),
                f"{label} MERGED edge is reciprocal in surviving route parents",
            )
    if is_allowed_str(
        global_status,
        {
            "AUDIT_CANDIDATE",
            "UNDER_AUDIT",
            "VERIFIED_PROOF",
            "VERIFIED_COUNTEREXAMPLE",
        },
    ):
        bound_route = (
            routes_by_id.get(candidate_route_id)
            if isinstance(candidate_route_id, str)
            else None
        )
        add(checks, is_nonempty_str(candidate_proof_id), f"{rel} frozen candidate has canonical ID")
        add(checks, is_sha256(candidate_artifact_sha256), f"{rel} frozen candidate has SHA-256")
        add(checks, isinstance(bound_route, dict), f"{rel} frozen candidate names route")
        if isinstance(bound_route, dict):
            add(
                checks,
                bound_route.get("candidate_id") == candidate_proof_id,
                f"{rel} route candidate ID matches canonical candidate ID",
            )
            add(
                checks,
                bound_route.get("strongest_artifact_sha256")
                == candidate_artifact_sha256,
                f"{rel} route candidate digest matches canonical digest",
            )
            add(
                checks,
                artifact_matches_sha256(
                    bound_route.get("strongest_artifact"),
                    candidate_artifact_sha256,
                    path,
                ),
                f"{rel} canonical candidate digest matches route artifact content",
            )
        if isinstance(closure_evidence, dict):
            add(
                checks,
                closure_evidence.get("candidate_id") == candidate_proof_id,
                f"{rel} closure candidate ID matches canonical candidate ID",
            )
            add(
                checks,
                closure_evidence.get("candidate_artifact_sha256")
                == candidate_artifact_sha256,
                f"{rel} closure candidate digest matches canonical digest",
            )
            add(
                checks,
                artifact_matches_sha256(
                    closure_evidence.get("candidate_artifact"),
                    candidate_artifact_sha256,
                    path,
                ),
                f"{rel} closure candidate digest matches candidate artifact content",
            )
            if isinstance(bound_route, dict):
                add(
                    checks,
                    same_artifact(
                        closure_evidence.get("candidate_artifact"),
                        bound_route.get("strongest_artifact"),
                        path,
                    ),
                    f"{rel} route and closure bind the same candidate artifact",
                )
        add(
            checks,
            bool(originating_run_ids),
            f"{rel} frozen candidate records originating run IDs",
        )
        if isinstance(candidate_lineage, dict):
            lineage_artifact = candidate_lineage.get("lineage_artifact")
            lineage_digest = candidate_lineage.get("lineage_artifact_sha256")
            add(
                checks,
                research_artifact_exists(lineage_artifact, path),
                f"{rel} frozen candidate lineage artifact exists",
            )
            add(
                checks,
                artifact_matches_sha256(lineage_artifact, lineage_digest, path),
                f"{rel} frozen candidate lineage artifact digest matches",
            )
            lineage_tokens = [
                token
                for token in [
                    problem_id,
                    target_id,
                    target_artifact_sha256,
                    candidate_proof_id,
                    candidate_artifact_sha256,
                ]
                + originating_run_ids
                + material_repair_run_ids
                if isinstance(token, str)
            ]
            add(
                checks,
                text_artifact_contains(lineage_artifact, lineage_tokens, path),
                f"{rel} lineage artifact binds candidate and run IDs",
            )
        if isinstance(verifier, dict) and verifier.get("assigned") is True:
            add(
                checks,
                verifier.get("candidate_id") == candidate_proof_id,
                f"{rel} assigned verifier candidate ID matches canonical candidate",
            )
            add(
                checks,
                verifier.get("candidate_artifact_sha256")
                == candidate_artifact_sha256,
                f"{rel} assigned verifier digest matches canonical candidate",
            )
    if global_status == "UNINITIALIZED":
        add(checks, state.get("statement_frozen") is False, f"{rel} uninitialized statement is not frozen")
        add(checks, current_round == 0, f"{rel} uninitialized state is at round 0")
        add(checks, candidate_route_id is None, f"{rel} uninitialized state has no candidate route")
        add(checks, candidate_proof_id is None, f"{rel} uninitialized state has no candidate proof")
        add(checks, not routes, f"{rel} uninitialized state has no registered routes")
    if is_allowed_str(global_status, {
        "CONTRACT_FROZEN",
        "SEARCHING",
        "AUDIT_CANDIDATE",
        "UNDER_AUDIT",
        "VERIFIED_PROOF",
        "VERIFIED_COUNTEREXAMPLE",
        "CONDITIONAL_RESULT",
        "CHECKPOINT_INCOMPLETE",
        "EXHAUSTED_CURRENT_MECHANISMS",
    }):
        add(checks, state.get("statement_frozen") is True, f"{rel} initialized contract is frozen")
    if global_status == "SEARCHING":
        add(checks, state.get("attack_surface_ready") is True, f"{rel} searching state has attack surface")
        add(checks, state.get("approach_registry_ready") is True, f"{rel} searching state has registry")
        add(
            checks,
            any(
                isinstance(route, dict)
                and is_allowed_str(route.get("status"), {"SEED", "ACTIVE"})
                for route in routes
            ),
            f"{rel} searching state has seed/active route",
        )
        if orchestration_profile == "FULL":
            add(
                checks,
                state.get("independent_refutation_active") is True,
                f"{rel} FULL searching state has an independent refutation branch",
            )
    if is_allowed_str(
        state.get("global_status"), {"AUDIT_CANDIDATE", "UNDER_AUDIT"}
    ):
        candidate_route = (
            routes_by_id.get(candidate_route_id)
            if isinstance(candidate_route_id, str)
            else None
        )
        add(checks, candidate_route is not None, f"{rel} candidate state names existing route")
        add(checks, is_nonempty_str(candidate_proof_id), f"{rel} candidate state has proof ID/version")
        for field in ("statement_frozen", "attack_surface_ready", "approach_registry_ready"):
            add(checks, state.get(field) is True, f"{rel} candidate state has {field}")
        if isinstance(closure_evidence, dict):
            add(
                checks,
                is_nonempty_str(closure_evidence.get("candidate_id")),
                f"{rel} candidate state records canonical candidate ID",
            )
            add(
                checks,
                role_artifact_exists(
                    closure_evidence.get("proof_obligations"), path, "proof_obligations"
                ),
                f"{rel} candidate state has typed proof-obligation artifact",
            )
            add(
                checks,
                artifact_matches_sha256(
                    closure_evidence.get("proof_obligations"),
                    closure_evidence.get("proof_obligations_sha256"),
                    path,
                ),
                f"{rel} candidate proof-obligation digest matches",
            )
            add(
                checks,
                role_artifact_exists(
                    closure_evidence.get("attack_surface_exit"), path, "attack_surface"
                ),
                f"{rel} candidate state has typed attack-surface artifact",
            )
            add(
                checks,
                artifact_matches_sha256(
                    closure_evidence.get("attack_surface_exit"),
                    closure_evidence.get("attack_surface_exit_sha256"),
                    path,
                ),
                f"{rel} candidate attack-surface digest matches",
            )
        if isinstance(candidate_route, dict):
            add(
                checks,
                is_allowed_str(
                    candidate_route.get("status"), {"CANDIDATE", "UNDER_AUDIT"}
                ),
                f"{rel} candidate route has candidate/audit status",
            )
            add(
                checks,
                is_allowed_str(candidate_route.get("gap_class"), {"GS0", "GS1", "GS2"}),
                f"{rel} audit candidate has at most a local/source gap",
            )
            add(
                checks,
                is_allowed_str(
                    candidate_route.get("verification_gate"),
                    {"I3_REQUIRED", "I3_ASSIGNED"},
                ),
                f"{rel} audit candidate has pending/assigned I3 gate",
            )
            if candidate_route.get("source_gate") == "CLOSED" and isinstance(
                closure_evidence, dict
            ):
                add(
                    checks,
                    role_artifact_exists(
                        closure_evidence.get("source_audit"), path, "source_audit"
                    ),
                    f"{rel} audit candidate with closed source gate has typed source-audit artifact",
                )
                add(
                    checks,
                    artifact_matches_sha256(
                        closure_evidence.get("source_audit"),
                        closure_evidence.get("source_audit_sha256"),
                        path,
                    ),
                    f"{rel} candidate source-audit digest matches",
                )
        if global_status == "UNDER_AUDIT":
            add(
                checks,
                isinstance(candidate_route, dict)
                and candidate_route.get("status") == "UNDER_AUDIT",
                f"{rel} UNDER_AUDIT state names UNDER_AUDIT route",
            )
            if isinstance(verifier, dict):
                add(
                    checks,
                    verifier.get("required") is True
                    and verifier.get("assigned") is True
                    and verifier.get("independence_level") == "I3",
                    f"{rel} UNDER_AUDIT has assigned I3 verifier",
                )
            if isinstance(candidate_route, dict):
                add(
                    checks,
                    candidate_route.get("verification_gate") == "I3_ASSIGNED",
                    f"{rel} UNDER_AUDIT route records I3_ASSIGNED gate",
                )
    if state.get("global_status") == "VERIFIED_PROOF":
        closed_route = (
            routes_by_id.get(candidate_route_id)
            if isinstance(candidate_route_id, str)
            else None
        )
        add(
            checks,
            isinstance(closed_route, dict) and closed_route.get("status") == "CLOSED_PROOF",
            f"{rel} VERIFIED_PROOF names CLOSED_PROOF route",
        )
    if state.get("global_status") == "VERIFIED_COUNTEREXAMPLE":
        closed_route = (
            routes_by_id.get(candidate_route_id)
            if isinstance(candidate_route_id, str)
            else None
        )
        add(
            checks,
            isinstance(closed_route, dict)
            and closed_route.get("status") == "CLOSED_COUNTEREXAMPLE",
            f"{rel} VERIFIED_COUNTEREXAMPLE names CLOSED_COUNTEREXAMPLE route",
        )
    if is_allowed_str(
        state.get("global_status"),
        {"VERIFIED_PROOF", "VERIFIED_COUNTEREXAMPLE"},
    ):
        for field in ("statement_frozen", "attack_surface_ready", "approach_registry_ready"):
            add(checks, state.get(field) is True, f"{rel} verified closure has {field}")
        add(checks, is_nonempty_str(candidate_proof_id), f"{rel} verified closure has canonical candidate ID")
        if isinstance(closure_evidence, dict):
            add(
                checks,
                closure_evidence.get("candidate_id") == candidate_proof_id,
                f"{rel} verified closure records canonical candidate ID",
            )
            for field, role in (
                ("proof_obligations", "proof_obligations"),
                ("source_audit", "source_audit"),
                ("attack_surface_exit", "attack_surface"),
            ):
                add(
                    checks,
                    role_artifact_exists(closure_evidence.get(field), path, role),
                    f"{rel} verified closure has typed evidence: {field}",
                )
                add(
                    checks,
                    artifact_matches_sha256(
                        closure_evidence.get(field),
                        closure_evidence.get(f"{field}_sha256"),
                        path,
                    ),
                    f"{rel} verified closure evidence digest matches: {field}",
                )
            typed_role_specs = (
                (
                    "proof_obligations",
                    "proof_obligations_manifest",
                    "proof_obligations_evidence",
                ),
                ("source_audit", "source_audit_manifest", "source_audit_evidence"),
                (
                    "attack_surface_exit",
                    "attack_surface_exit_manifest",
                    "attack_surface_exit_evidence",
                ),
            )
            role_paths = [
                resolve_artifact(closure_evidence.get(field), path)
                for field, _, _ in typed_role_specs
            ]
            add(
                checks,
                all(role_path is not None for role_path in role_paths)
                and len(set(role_paths)) == len(role_paths),
                f"{rel} closure evidence roles use pairwise-distinct artifacts",
            )
            for artifact_field, manifest_field, record_type in typed_role_specs:
                add(
                    checks,
                    role_artifact_exists(
                        closure_evidence.get(manifest_field), path, manifest_field
                    ),
                    f"{rel} verified closure has typed role manifest: {manifest_field}",
                )
                add(
                    checks,
                    artifact_matches_sha256(
                        closure_evidence.get(manifest_field),
                        closure_evidence.get(f"{manifest_field}_sha256"),
                        path,
                    ),
                    f"{rel} verified role-manifest digest matches: {manifest_field}",
                )
                if isinstance(target_binding, dict):
                    add(
                        checks,
                        closure_evidence_role_manifest_matches(
                            load_json_artifact(
                                closure_evidence.get(manifest_field), path
                            ),
                            path,
                            record_type=record_type,
                            state=state,
                            target_binding=target_binding,
                            closure_evidence=closure_evidence,
                            artifact_field=artifact_field,
                        ),
                        f"{rel} typed role manifest binds target/candidate and {artifact_field}",
                    )
            for manifest_field, role in (
                ("dependency_snapshot", "dependency_snapshot"),
                ("audit_packet", "audit_packet"),
            ):
                add(
                    checks,
                    role_artifact_exists(
                        closure_evidence.get(manifest_field), path, role
                    ),
                    f"{rel} verified closure has {manifest_field}",
                )
                add(
                    checks,
                    artifact_matches_sha256(
                        closure_evidence.get(manifest_field),
                        closure_evidence.get(f"{manifest_field}_sha256"),
                        path,
                    ),
                    f"{rel} verified {manifest_field} digest matches",
                )
            if isinstance(target_binding, dict):
                add(
                    checks,
                    dependency_snapshot_matches(
                        load_json_artifact(
                            closure_evidence.get("dependency_snapshot"), path
                        ),
                        path,
                        state=state,
                        target_binding=target_binding,
                    ),
                    f"{rel} dependency snapshot matches complete candidate ancestry",
                )
            if (
                isinstance(target_binding, dict)
                and isinstance(candidate_lineage, dict)
            ):
                add(
                    checks,
                    audit_packet_matches(
                        load_json_artifact(closure_evidence.get("audit_packet"), path),
                        path,
                        state=state,
                        target_binding=target_binding,
                        candidate_lineage=candidate_lineage,
                        closure_evidence=closure_evidence,
                    ),
                    f"{rel} audit packet binds exact target/candidate/dependency/evidence snapshot",
                )
            if isinstance(verifier, dict):
                add(
                    checks,
                    same_artifact(
                        closure_evidence.get("audit_packet"),
                        verifier.get("audit_packet"),
                        path,
                    )
                    and closure_evidence.get("audit_packet_sha256")
                    == verifier.get("audit_packet_sha256"),
                    f"{rel} closure and decisive verifier bind the same audit packet",
                )
            add(
                checks,
                role_artifact_exists(
                    closure_evidence.get("closure_manifest"), path, "closure_manifest"
                ),
                f"{rel} verified closure has typed closure manifest",
            )
            add(
                checks,
                artifact_matches_sha256(
                    closure_evidence.get("closure_manifest"),
                    closure_evidence.get("closure_manifest_sha256"),
                    path,
                ),
                f"{rel} verified closure manifest digest matches",
            )
            if (
                isinstance(target_binding, dict)
                and isinstance(candidate_lineage, dict)
                and isinstance(verifier, dict)
            ):
                add(
                    checks,
                    closure_manifest_matches(
                        load_json_artifact(
                            closure_evidence.get("closure_manifest"), path
                        ),
                        path,
                        state=state,
                        target_binding=target_binding,
                        candidate_lineage=candidate_lineage,
                        verifier=verifier,
                        closure_evidence=closure_evidence,
                    ),
                    f"{rel} typed closure manifest binds target, proof, evidence, and verdict",
                )
    if global_status == "CONDITIONAL_RESULT":
        add(checks, is_nonempty_str(candidate_proof_id), f"{rel} conditional result has version ID")
        add(
            checks,
            isinstance(candidate_route_id, str) and candidate_route_id in routes_by_id,
            f"{rel} conditional result names existing route",
        )
        if isinstance(outcome_record, dict):
            add(
                checks,
                is_nonempty_str_list(outcome_record.get("exact_assumptions")),
                f"{rel} conditional result records exact assumptions",
            )
            add(
                checks,
                is_nonempty_str(outcome_record.get("strongest_result")),
                f"{rel} conditional result names strongest result",
            )
            add(
                checks,
                research_artifact_exists(outcome_record.get("strongest_artifact"), path),
                f"{rel} conditional result artifact exists",
            )
    if global_status == "CHECKPOINT_INCOMPLETE":
        add(checks, is_nonempty_str(state.get("last_checkpoint")), f"{rel} checkpoint has timestamp/ID")
        if isinstance(outcome_record, dict):
            add(
                checks,
                is_nonempty_str(outcome_record.get("strongest_result")),
                f"{rel} checkpoint records strongest result",
            )
            add(
                checks,
                research_artifact_exists(outcome_record.get("strongest_artifact"), path),
                f"{rel} checkpoint strongest artifact exists",
            )
            add(
                checks,
                is_nonempty_str_list(outcome_record.get("exact_remaining_gaps")),
                f"{rel} checkpoint records exact remaining gaps",
            )
    if global_status == "EXHAUSTED_CURRENT_MECHANISMS":
        live_statuses = {"SEED", "ACTIVE", "CANDIDATE", "UNDER_AUDIT", "PARKED"}
        add(
            checks,
            all(
                isinstance(route, dict)
                and not is_allowed_str(route.get("status"), live_statuses)
                for route in routes
            ),
            f"{rel} exhausted state has no live routes",
        )
        if isinstance(outcome_record, dict):
            redirected_completed = outcome_record.get("redirected_wave_completed") is True
            redirected_waived = outcome_record.get("redirected_wave_waiver") is True
            add(
                checks,
                redirected_completed != redirected_waived,
                f"{rel} exhausted state records exactly one redirected-wave completion/waiver",
            )
            add(
                checks,
                role_artifact_exists(
                    outcome_record.get("initial_wave_report"), path, "wave_report"
                ),
                f"{rel} exhausted state has typed initial-wave report",
            )
            add(
                checks,
                artifact_matches_sha256(
                    outcome_record.get("initial_wave_report"),
                    outcome_record.get("initial_wave_report_sha256"),
                    path,
                ),
                f"{rel} initial-wave report digest matches",
            )
            add(
                checks,
                role_artifact_exists(
                    outcome_record.get("initial_wave_manifest"), path, "wave_manifest"
                ),
                f"{rel} exhausted state has typed initial-wave manifest",
            )
            add(
                checks,
                artifact_matches_sha256(
                    outcome_record.get("initial_wave_manifest"),
                    outcome_record.get("initial_wave_manifest_sha256"),
                    path,
                ),
                f"{rel} initial-wave manifest digest matches",
            )
            if isinstance(target_binding, dict):
                add(
                    checks,
                    wave_manifest_matches(
                        load_json_artifact(
                            outcome_record.get("initial_wave_manifest"), path
                        ),
                        path,
                        state=state,
                        target_binding=target_binding,
                        wave_type="INITIAL",
                        report=outcome_record.get("initial_wave_report"),
                        report_sha256=outcome_record.get("initial_wave_report_sha256"),
                    ),
                    f"{rel} initial-wave manifest binds target and report",
                )
            if redirected_completed:
                add(
                    checks,
                    type(current_round) is int and current_round >= 2,
                    f"{rel} exhausted state completed at least two rounds",
                )
                add(
                    checks,
                    role_artifact_exists(
                        outcome_record.get("redirected_wave_report"),
                        path,
                        "wave_report",
                    ),
                    f"{rel} exhausted state has typed redirected-wave report",
                )
                add(
                    checks,
                    artifact_matches_sha256(
                        outcome_record.get("redirected_wave_report"),
                        outcome_record.get("redirected_wave_report_sha256"),
                        path,
                    ),
                    f"{rel} redirected-wave report digest matches",
                )
                add(
                    checks,
                    role_artifact_exists(
                        outcome_record.get("redirected_wave_manifest"),
                        path,
                        "wave_manifest",
                    ),
                    f"{rel} exhausted state has typed redirected-wave manifest",
                )
                add(
                    checks,
                    artifact_matches_sha256(
                        outcome_record.get("redirected_wave_manifest"),
                        outcome_record.get("redirected_wave_manifest_sha256"),
                        path,
                    ),
                    f"{rel} redirected-wave manifest digest matches",
                )
                add(
                    checks,
                    not same_artifact(
                        outcome_record.get("initial_wave_report"),
                        outcome_record.get("redirected_wave_report"),
                        path,
                    ),
                    f"{rel} initial and redirected waves have distinct reports",
                )
                if isinstance(target_binding, dict):
                    add(
                        checks,
                        wave_manifest_matches(
                            load_json_artifact(
                                outcome_record.get("redirected_wave_manifest"), path
                            ),
                            path,
                            state=state,
                            target_binding=target_binding,
                            wave_type="REDIRECTED",
                            report=outcome_record.get("redirected_wave_report"),
                            report_sha256=outcome_record.get(
                                "redirected_wave_report_sha256"
                            ),
                            initial_wave_manifest=outcome_record.get(
                                "initial_wave_manifest"
                            ),
                            initial_wave_manifest_sha256=outcome_record.get(
                                "initial_wave_manifest_sha256"
                            ),
                        ),
                        f"{rel} redirected-wave manifest binds target and report",
                    )
            if redirected_waived:
                add(
                    checks,
                    type(current_round) is int and current_round >= 1,
                    f"{rel} exhausted waiver follows an initial round",
                )
                add(
                    checks,
                    is_nonempty_str(outcome_record.get("redirected_wave_waiver_reason")),
                    f"{rel} exhausted state records precise redirected-wave waiver reason",
                )
                add(
                    checks,
                    artifact_matches_sha256(
                        outcome_record.get("redirected_wave_waiver_evidence"),
                        outcome_record.get(
                            "redirected_wave_waiver_evidence_sha256"
                        ),
                        path,
                    ),
                    f"{rel} redirected-wave waiver-evidence digest matches",
                )
                add(
                    checks,
                    role_artifact_exists(
                        outcome_record.get("waiver_assessment"),
                        path,
                        "waiver_assessment",
                    ),
                    f"{rel} exhausted state has typed waiver assessment",
                )
                add(
                    checks,
                    artifact_matches_sha256(
                        outcome_record.get("waiver_assessment"),
                        outcome_record.get("waiver_assessment_sha256"),
                        path,
                    ),
                    f"{rel} waiver-assessment digest matches",
                )
                add(
                    checks,
                    same_artifact(
                        outcome_record.get("redirected_wave_waiver_evidence"),
                        outcome_record.get("waiver_assessment"),
                        path,
                    )
                    and outcome_record.get(
                        "redirected_wave_waiver_evidence_sha256"
                    )
                    == outcome_record.get("waiver_assessment_sha256"),
                    f"{rel} waiver evidence is the typed waiver assessment",
                )
                if isinstance(target_binding, dict):
                    add(
                        checks,
                        waiver_assessment_matches(
                            load_json_artifact(
                                outcome_record.get("waiver_assessment"), path
                            ),
                            path,
                            state=state,
                            target_binding=target_binding,
                            outcome_record=outcome_record,
                        ),
                        f"{rel} waiver assessment covers canonical discovery operators",
                    )
                add(
                    checks,
                    role_artifact_exists(
                        outcome_record.get("waiver_manifest"), path, "waiver_manifest"
                    ),
                    f"{rel} exhausted state has typed waiver manifest",
                )
                add(
                    checks,
                    artifact_matches_sha256(
                        outcome_record.get("waiver_manifest"),
                        outcome_record.get("waiver_manifest_sha256"),
                        path,
                    ),
                    f"{rel} waiver-manifest digest matches",
                )
                if isinstance(target_binding, dict):
                    add(
                        checks,
                        waiver_manifest_matches(
                            load_json_artifact(
                                outcome_record.get("waiver_manifest"), path
                            ),
                            path,
                            state=state,
                            target_binding=target_binding,
                            outcome_record=outcome_record,
                        ),
                        f"{rel} waiver manifest binds target, initial wave, and evidence",
                    )
            add(
                checks,
                is_nonempty_str(outcome_record.get("strongest_result")),
                f"{rel} exhausted state records strongest result",
            )
            add(
                checks,
                research_artifact_exists(outcome_record.get("strongest_artifact"), path),
                f"{rel} exhausted state strongest artifact exists",
            )
            add(
                checks,
                is_nonempty_str_list(outcome_record.get("exact_remaining_gaps")),
                f"{rel} exhausted state records exact remaining gaps",
            )
            add(
                checks,
                is_nonempty_str(outcome_record.get("exhaustion_rationale")),
                f"{rel} exhausted state records exhaustion rationale",
            )


def validate_workflow_contract(checks: list[tuple[bool, str]]) -> None:
    path = ROOT / "workflows/hard_math_search_orchestration.md"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8").lower()
    required_concepts = {
        "`light`": "LIGHT orchestration profile",
        "`full`": "FULL orchestration profile",
        "canonical mutable": "canonical machine state",
        "`target_binding`": "content-bound frozen target",
        "blind_generation": "blind-generation mode",
        "literature_aware": "literature-aware mode",
        "family-generation operators": "proof-family discovery operators",
        "sha-256": "content-bound frozen candidates",
        "originating-run": "structured generator/verifier lineage",
        "transition history": "route transition history",
        "inherited-gap": "merge gap inheritance",
        "gap_discharge_manifest": "typed inherited-gap discharge",
        "idea fingerprint": "idea fingerprint",
        "gap-strength": "gap-strength classification",
        "blocked": "blocked-route state",
        "reopen": "reopening rule",
        "reopen_manifest": "typed blocked-route reopening",
        "independent verifier": "independent final verifier",
        "report_manifest": "typed decisive-verifier report",
        "audit_packet_manifest": "immutable verifier audit packet",
        "pairwise-distinct": "distinct closure-evidence roles",
        "closure_manifest": "typed proof closure",
        "historical_backfill_manifest": "typed historical backfill",
        "redirected": "failure-driven redirected wave",
        "mechanism_delta": "redirected-wave mechanism delta",
        "search_wave_manifest": "typed exhaustion wave",
        "redirected_wave_waiver_manifest": "typed exhaustion waiver",
        "waiver_assessment_manifest": "canonical-operator waiver assessment",
        "structural consistency and content identity only": "structural-validation limitation",
        "residual": "honest residual outcome",
    }
    for needle, label in required_concepts.items():
        add(checks, needle in text, f"orchestration workflow includes {label}")


def validate_manifest_templates(checks: list[tuple[bool, str]]) -> None:
    for relative_path, record_type in MANIFEST_TEMPLATE_TYPES.items():
        path = ROOT / relative_path
        data, error = load_state(path)
        add(checks, error is None and data is not None, f"{relative_path} parses as JSON")
        if data is None:
            continue
        add(
            checks,
            data.get("schema_version") == 1,
            f"{relative_path} has schema version 1",
        )
        add(
            checks,
            data.get("record_type") == record_type,
            f"{relative_path} has record type {record_type}",
        )


def run_checks(state_paths: Optional[list[Path]] = None) -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    for rel in REQUIRED_PATHS:
        add(checks, (ROOT / rel).exists(), f"required proof-search artifact {rel}")
    validate_fixture_files(checks)
    validate_positive_state_fixtures(checks)
    validate_state_mutation_regressions(checks)
    validate_negative_state_fixtures(checks)
    validate_workflow_contract(checks)
    validate_manifest_templates(checks)

    if state_paths is None:
        state_paths = [
            ROOT / "templates/proof_search_state.yaml",
            ROOT / "problems/templates/problem_dossier/proof_search_state.yaml",
        ]
        state_paths.extend(sorted((ROOT / "problems/active").glob("*/proof_search_state.yaml")))
    for path in state_paths:
        if path.exists():
            validate_state(path, checks)
        else:
            add(checks, False, f"state file exists: {path}")
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate proof-search workflow structure; this does not validate mathematics."
    )
    parser.add_argument(
        "states",
        nargs="*",
        type=Path,
        help="Optional proof_search_state.yaml files to validate.",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    state_paths = [path.resolve() for path in args.states] if args.states else None
    checks = run_checks(state_paths)
    if not args.quiet:
        for passed, message in checks:
            print(f"{'PASS' if passed else 'FAIL'}: {message}")
    return 0 if all(passed for passed, _ in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
