from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "laboratory_stewardship.py"
SPEC = importlib.util.spec_from_file_location("laboratory_stewardship_under_test", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
steward = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(steward)


class LaboratoryStewardshipTests(unittest.TestCase):
    def make_lab(self, root: Path) -> None:
        for relative in (
            ".lab",
            "knowledge",
            "research/checkpoints",
            "results/unresolved",
            "sources/manifests",
            "problems/active/p1",
            "runs/laboratory_surveys",
            "runs/laboratory_stewardship",
            "scripts",
        ):
            (root / relative).mkdir(parents=True, exist_ok=True)
        files = {
            "LAB_PROFILE.json": (
                '{"template":{"id":"math-research-lab-template"},'
                '"lab":{"title":"Test Lab"}}\n'
            ),
            ".lab/manifest.json": (
                '{"schema_version":1,'
                '"template_id":"math-research-lab-template"}\n'
            ),
            "PROJECT_CHARTER.md": "# Charter\n",
            "BACKLOG.md": "# Backlog\n",
            "knowledge/results_ledger.yaml": '{"results":[]}\n',
            "knowledge/research_state.yaml": '{"laboratory_status":"ACTIVE"}\n',
            "knowledge/known_warnings.md": "# Warnings\n\n- stale link\n",
            "knowledge/resume.md": "# Old resume\n",
            "knowledge/laboratory_overview.md": "# No survey\n",
            "knowledge/laboratory_survey_state.json": (
                '{"schema_version":1,"basis_sha256":null,"freshness":"NONE"}\n'
            ),
            "problems/active/p1/status.yaml": '{"status":"UNKNOWN"}\n',
            "sources/manifests/source_registry.yaml": '{"sources":[]}\n',
        }
        for relative, text in files.items():
            (root / relative).write_text(text, encoding="utf-8")
        ordinary_stub = "raise SystemExit(0)\n"
        for name in (
            "doctor.py",
            "validate_lab.py",
            "validate_ledgers.py",
            "validate_proof_search.py",
            "run_evals.py",
        ):
            (root / "scripts" / name).write_text(ordinary_stub, encoding="utf-8")
        (root / "scripts/snapshot_project_state.py").write_text(
            "import json\n"
            "from pathlib import Path\n"
            "state=json.loads(Path('knowledge/laboratory_survey_state.json').read_text())\n"
            "Path('knowledge/resume.md').write_text('# Refreshed resume: '+state['freshness']+'\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )

    def complete_diagnosis(self, packet: Path) -> None:
        (packet / "diagnosis.md").write_text(
            "# Diagnosis\n\n"
            "The complete local audit reconciled tracks, dossiers, ledgers, checkpoints, "
            "sources, failures, outputs, and next directions. This synthetic fixture has "
            "one mechanical warning repair and no mathematical status claim.\n",
            encoding="utf-8",
        )

    def stage_plan(self, root: Path, run_id: str, changes, deferred=None) -> Path:
        packet = root / "runs/laboratory_stewardship" / run_id
        plan_path = packet / "repair_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["changes"] = changes
        plan["deferred"] = deferred or []
        plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        return packet

    def change(self, root: Path, packet: Path, relative: str, after: str, **overrides):
        target = root / relative
        staged = packet / "staged" / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(after, encoding="utf-8")
        before = target.read_bytes() if target.exists() else None
        item = {
            "id": overrides.pop("id", "repair-001"),
            "action": "UPDATE" if before is not None else "ADD",
            "path": relative,
            "repair_class": "MECHANICAL_HYGIENE",
            "reason": "repair a synthetic deterministic defect",
            "evidence_paths": [],
            "before_sha256": steward.sha256_bytes(before) if before is not None else None,
            "after_sha256": steward.sha256_bytes(staged.read_bytes()),
            "mathematical_effect": "NONE",
            "protected_evidence": None,
            "status_transitions": [],
        }
        item.update(overrides)
        return item

    def authoritative_dossier_evidence(
        self, root: Path, problem_id: str, status: str
    ):
        dossier = root / "problems" / "closed" / problem_id
        dossier.mkdir(parents=True, exist_ok=True)
        target_id = f"{problem_id}-target-v1"
        candidate_id = f"{problem_id}-candidate-v1"
        candidate_sha256 = steward.sha256_bytes(candidate_id.encode("utf-8"))
        report_sha256 = steward.sha256_bytes(f"{problem_id}-report".encode("utf-8"))
        closure_sha256 = steward.sha256_bytes(f"{problem_id}-closure".encode("utf-8"))
        verifier_id = f"{problem_id}-verifier-i3"
        route_id = f"{problem_id}-route"
        state = {
            "problem_id": problem_id,
            "global_status": status,
            "candidate_route_id": route_id,
            "candidate_proof_id": candidate_id,
            "candidate_artifact_sha256": candidate_sha256,
            "target_binding": {"target_id": target_id},
            "independent_verifier": {
                "id": verifier_id,
                "assigned": True,
                "completed": True,
                "independent_of_candidate": True,
                "independence_level": "I3",
                "verdict": "PASS",
                "report_sha256": report_sha256,
            },
            "closure_evidence": {
                "closure_manifest_sha256": closure_sha256,
            },
            "routes": [
                {
                    "id": route_id,
                    "status": steward.AUTHORITATIVE_DOSSIER_STATUSES[status],
                    "verification_gate": "I3_PASSED",
                }
            ],
        }
        state_path = dossier / "proof_search_state.yaml"
        state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
        relative = state_path.relative_to(root).as_posix()
        return {
            "status_field": "",
            "claim_id": problem_id,
            "problem_id": problem_id,
            "authoritative_status": status,
            "proof_search_state": relative,
            "proof_search_state_sha256": steward.sha256_bytes(state_path.read_bytes()),
            "target_id": target_id,
            "candidate_id": candidate_id,
            "candidate_artifact_sha256": candidate_sha256,
            "verifier_id": verifier_id,
            "verifier_report_sha256": report_sha256,
            "closure_manifest_sha256": closure_sha256,
        }

    def dossier_status_transition(self, evidence, field, from_status="ABSENT"):
        return {
            "kind": "EXISTING_DOSSIER_STATUS",
            "status_field": field,
            "claim_id": evidence["claim_id"],
            "problem_id": evidence["problem_id"],
            "from_status": from_status,
            "to_status": evidence["authoritative_status"],
            "exact_scope_artifact": evidence["proof_search_state"],
            "exact_scope_sha256": evidence["proof_search_state_sha256"],
        }

    def complete_report(self, packet: Path) -> str:
        sections = []
        for index in range(12):
            sections.append(
                f"## {index}. Completed section {index}\n\n"
                f"Section {index} records concrete post-repair evidence for this synthetic "
                "fixture, its explicit limitation, and the next auditable action. No hidden "
                "mathematical promotion or deletion is represented here.\n"
            )
        report = (
            "# Laboratory Stewardship Report\n\n"
            "Stewardship report status: COMPLETE\n\n"
            "The synthetic laboratory is coherent after the planned mechanical repair. "
            "No mathematical status changed, no external search ran, and no evidence was deleted.\n\n"
            + "\n".join(sections)
        )
        (packet / "report.md").write_text(report, encoding="utf-8")
        return report

    def test_structural_validation_uses_origin_specific_validator(self):
        with tempfile.TemporaryDirectory(prefix="steward-validator-generated-") as temp:
            root = Path(temp)
            self.make_lab(root)
            self.assertEqual(
                steward.structural_validation_command(root),
                (
                    "lab-structure",
                    [sys.executable, "scripts/validate_lab.py"],
                ),
            )

        with tempfile.TemporaryDirectory(prefix="steward-validator-legacy-") as temp:
            root = Path(temp)
            self.make_lab(root)
            manifest = json.loads((root / ".lab/manifest.json").read_text())
            manifest["origin_kind"] = "LEGACY_ADOPTED"
            (root / ".lab/manifest.json").write_text(
                json.dumps(manifest) + "\n", encoding="utf-8"
            )
            (root / "scripts/lab_state.py").write_text(
                "raise SystemExit(0)\n", encoding="utf-8"
            )
            (root / "scripts/validate_lab.py").unlink()
            self.assertEqual(
                steward.structural_validation_command(root),
                (
                    "lab-state",
                    [sys.executable, "scripts/lab_state.py", "check"],
                ),
            )

    def test_structural_validation_rejects_unknown_origin_and_missing_validator(self):
        with tempfile.TemporaryDirectory(prefix="steward-validator-origin-") as temp:
            root = Path(temp)
            self.make_lab(root)
            manifest = json.loads((root / ".lab/manifest.json").read_text())
            manifest["origin_kind"] = "UNREVIEWED"
            (root / ".lab/manifest.json").write_text(
                json.dumps(manifest) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(
                steward.StewardshipError, "unsupported laboratory origin_kind"
            ):
                steward.structural_validation_command(root)

        with tempfile.TemporaryDirectory(prefix="steward-validator-missing-") as temp:
            root = Path(temp)
            self.make_lab(root)
            (root / "scripts/validate_lab.py").unlink()
            with self.assertRaisesRegex(
                steward.StewardshipError, "structural validator"
            ):
                steward.structural_validation_command(root)

    def test_successful_transaction_backs_up_validates_and_publishes_bound_survey(self):
        with tempfile.TemporaryDirectory(prefix="steward-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            run_id = "r-success"
            steward.start_run(root, run_id, "DEEP_LOCAL")
            packet = root / "runs/laboratory_stewardship" / run_id
            self.complete_diagnosis(packet)
            item = self.change(
                root,
                packet,
                "knowledge/known_warnings.md",
                "# Warnings\n\n- none currently recorded\n",
            )
            self.stage_plan(root, run_id, [item])
            prepared = steward.prepare_run(root, run_id)
            self.assertEqual(prepared["status"], "PREPARED")
            self.assertEqual(
                (packet / "before/knowledge/known_warnings.md").read_text(),
                "# Warnings\n\n- stale link\n",
            )
            applied = steward.apply_run(root, run_id)
            self.assertEqual(applied["status"], "APPLIED")
            report = self.complete_report(packet)
            result, code = steward.finalize_run(root, run_id)
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "COMPLETED")
            manifest = json.loads((packet / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "COMPLETED")
            self.assertEqual(
                (root / "knowledge/resume.md").read_text(),
                "# Refreshed resume: FRESH\n",
            )
            self.assertEqual((root / "knowledge/laboratory_overview.md").read_text(), report)
            survey_state = json.loads(
                (root / "knowledge/laboratory_survey_state.json").read_text()
            )
            self.assertEqual(survey_state["freshness"], "FRESH")
            self.assertEqual(len(survey_state["external_bindings"]), 1)

    def test_prepare_rejects_traversal_without_live_write(self):
        with tempfile.TemporaryDirectory(prefix="steward-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            run_id = "r-traversal"
            steward.start_run(root, run_id, "DEEP_LOCAL")
            packet = root / "runs/laboratory_stewardship" / run_id
            self.complete_diagnosis(packet)
            item = {
                "id": "repair-001",
                "action": "ADD",
                "path": "../escape.md",
                "repair_class": "MECHANICAL_HYGIENE",
                "reason": "invalid",
                "evidence_paths": [],
                "before_sha256": None,
                "after_sha256": "0" * 64,
                "mathematical_effect": "NONE",
                "protected_evidence": None,
                "status_transitions": [],
            }
            self.stage_plan(root, run_id, [item])
            with self.assertRaises(steward.StewardshipError):
                steward.prepare_run(root, run_id)
            self.assertFalse((root.parent / "escape.md").exists())

    def test_prepare_rejects_append_only_rewrite_and_unsupported_promotion(self):
        with tempfile.TemporaryDirectory(prefix="steward-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            checkpoint = root / "research/checkpoints/c1.md"
            checkpoint.write_text("old checkpoint\n", encoding="utf-8")
            run_id = "r-append-only"
            steward.start_run(root, run_id, "DEEP_LOCAL")
            packet = root / "runs/laboratory_stewardship" / run_id
            self.complete_diagnosis(packet)
            item = self.change(root, packet, "research/checkpoints/c1.md", "rewritten\n")
            self.stage_plan(root, run_id, [item])
            with self.assertRaisesRegex(steward.StewardshipError, "append-only"):
                steward.prepare_run(root, run_id)

        with tempfile.TemporaryDirectory(prefix="steward-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            run_id = "r-false-promotion"
            steward.start_run(root, run_id, "DEEP_LOCAL")
            packet = root / "runs/laboratory_stewardship" / run_id
            self.complete_diagnosis(packet)
            item = self.change(
                root,
                packet,
                "problems/active/p1/status.yaml",
                '{"status":"VERIFIED_PROOF"}\n',
                repair_class="PROTECTED_STATUS_TRANSITION",
                mathematical_effect="RECORD_EXISTING_VERDICT",
            )
            self.stage_plan(root, run_id, [item])
            with self.assertRaisesRegex(steward.StewardshipError, "protected_evidence"):
                steward.prepare_run(root, run_id)

    def test_drift_after_prepare_blocks_apply(self):
        with tempfile.TemporaryDirectory(prefix="steward-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            run_id = "r-drift"
            steward.start_run(root, run_id, "STANDARD_LOCAL")
            packet = root / "runs/laboratory_stewardship" / run_id
            self.complete_diagnosis(packet)
            item = self.change(
                root, packet, "knowledge/known_warnings.md", "# Warnings\n\n- repaired\n"
            )
            self.stage_plan(root, run_id, [item])
            steward.prepare_run(root, run_id)
            (root / "BACKLOG.md").write_text("# Concurrent change\n", encoding="utf-8")
            with self.assertRaisesRegex(steward.StewardshipError, "drifted"):
                steward.apply_run(root, run_id)
            self.assertIn("stale link", (root / "knowledge/known_warnings.md").read_text())

    def test_partial_apply_records_exact_journal_and_preimages(self):
        with tempfile.TemporaryDirectory(prefix="steward-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            (root / "knowledge/source_map.md").write_text("# Old map\n", encoding="utf-8")
            run_id = "r-partial"
            steward.start_run(root, run_id, "DEEP_LOCAL")
            packet = root / "runs/laboratory_stewardship" / run_id
            self.complete_diagnosis(packet)
            first = self.change(
                root,
                packet,
                "knowledge/known_warnings.md",
                "# Warnings\n\n- repaired\n",
                id="repair-001",
            )
            second = self.change(
                root,
                packet,
                "knowledge/source_map.md",
                "# New map\n",
                id="repair-002",
            )
            self.stage_plan(root, run_id, [first, second])
            steward.prepare_run(root, run_id)
            original_replace = steward.atomic_replace

            def fail_second(path, data, lab_root, mode=0o644, **kwargs):
                if path == root / "knowledge/source_map.md":
                    raise steward.StewardshipError("synthetic second-write failure")
                return original_replace(path, data, lab_root, mode, **kwargs)

            with mock.patch.object(steward, "atomic_replace", side_effect=fail_second):
                with self.assertRaisesRegex(steward.StewardshipError, "synthetic"):
                    steward.apply_run(root, run_id)
            manifest = json.loads((packet / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "PARTIAL_APPLY")
            self.assertEqual(manifest["applied_paths"], ["knowledge/known_warnings.md"])
            journal = [json.loads(line) for line in (packet / "apply_journal.jsonl").read_text().splitlines()]
            self.assertEqual([entry["event"] for entry in journal], ["INTENT", "APPLIED", "INTENT"])
            self.assertEqual(
                (packet / "before/knowledge/source_map.md").read_text(), "# Old map\n"
            )

    def test_exact_strong_status_vocabulary_rejects_negative_substrings(self):
        self.assertFalse(steward.strong_status("PLAUSIBLE_UNVERIFIED"))
        self.assertFalse(steward.strong_status("NOT_ESTABLISHED"))
        self.assertTrue(steward.strong_status("PASS"))
        self.assertTrue(steward.strong_status("VERIFIED_INTERNAL"))

    def test_prepare_rejects_status_and_stable_entry_removal(self):
        with tempfile.TemporaryDirectory(prefix="steward-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            run_id = "r-status-delete"
            steward.start_run(root, run_id, "DEEP_LOCAL")
            packet = root / "runs/laboratory_stewardship" / run_id
            self.complete_diagnosis(packet)
            item = self.change(
                root,
                packet,
                "problems/active/p1/status.yaml",
                '{"note":"status was removed"}\n',
            )
            self.stage_plan(root, run_id, [item])
            with self.assertRaisesRegex(steward.StewardshipError, "removes status"):
                steward.prepare_run(root, run_id)

        with tempfile.TemporaryDirectory(prefix="steward-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            ledger = root / "knowledge/results_ledger.yaml"
            ledger.write_text(
                '{"results":[{"claim_id":"C-1","status":"UNKNOWN"}]}\n',
                encoding="utf-8",
            )
            run_id = "r-entry-delete"
            steward.start_run(root, run_id, "DEEP_LOCAL")
            packet = root / "runs/laboratory_stewardship" / run_id
            self.complete_diagnosis(packet)
            item = self.change(root, packet, "knowledge/results_ledger.yaml", '{"results":[]}\n')
            self.stage_plan(root, run_id, [item])
            with self.assertRaisesRegex(steward.StewardshipError, "stable structured identities"):
                steward.prepare_run(root, run_id)

    def test_verified_result_artifact_add_is_forbidden_in_v1(self):
        with tempfile.TemporaryDirectory(prefix="steward-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            run_id = "r-verified-add"
            steward.start_run(root, run_id, "DEEP_LOCAL")
            packet = root / "runs/laboratory_stewardship" / run_id
            self.complete_diagnosis(packet)
            item = self.change(
                root,
                packet,
                "results/verified/unsupported.md",
                "# Unsupported promotion\n",
            )
            self.stage_plan(root, run_id, [item])
            with self.assertRaisesRegex(steward.StewardshipError, "verified-result artifacts"):
                steward.prepare_run(root, run_id)

        with tempfile.TemporaryDirectory(prefix="steward-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            run_id = "r-verified-casefold-add"
            steward.start_run(root, run_id, "DEEP_LOCAL")
            packet = root / "runs/laboratory_stewardship" / run_id
            self.complete_diagnosis(packet)
            item = self.change(
                root,
                packet,
                "results/Verified/unsupported.md",
                "# Unsupported case-variant promotion\n",
            )
            self.stage_plan(root, run_id, [item])
            with self.assertRaisesRegex(steward.StewardshipError, "verified-result artifacts"):
                steward.prepare_run(root, run_id)

    def test_cross_claim_protected_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="steward-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            target_path = root / "problems/active/p1/target.md"
            target_path.write_text("Exact target A\n", encoding="utf-8")
            closure_path = root / "problems/active/p1/closure.json"
            closure_path.write_text(
                '{"problem_id":"p1","target_id":"TARGET-A",'
                '"global_status":"VERIFIED_PROOF"}\n',
                encoding="utf-8",
            )
            verifier_path = root / "problems/active/p1/verifier.json"
            verifier_path.write_text('{"verdict":"PASS"}\n', encoding="utf-8")
            state_path = root / "problems/active/p1/proof_search_state.yaml"
            state = {
                "problem_id": "p1",
                "global_status": "VERIFIED_PROOF",
                "target_binding": {
                    "target_id": "TARGET-A",
                    "artifact": "problems/active/p1/target.md",
                    "artifact_sha256": steward.sha256_bytes(target_path.read_bytes()),
                },
                "independent_verifier": {
                    "independence_level": "I3",
                    "verdict": "PASS",
                    "completed": True,
                    "report": "problems/active/p1/verifier.json",
                    "report_sha256": steward.sha256_bytes(verifier_path.read_bytes()),
                },
                "closure_evidence": {
                    "closure_manifest": "problems/active/p1/closure.json",
                    "closure_manifest_sha256": steward.sha256_bytes(closure_path.read_bytes()),
                },
            }
            state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
            evidence = {
                "claim_id": "TARGET-B",
                "problem_id": "p1",
                "target_id": "TARGET-A",
                "gate": "PROOF_I3",
                "independence_level": "I3",
                "verdict": "PASS",
                "exact_scope_artifact": "problems/active/p1/target.md",
                "exact_scope_sha256": steward.sha256_bytes(target_path.read_bytes()),
                "proof_search_state": "problems/active/p1/proof_search_state.yaml",
                "proof_search_state_sha256": steward.sha256_bytes(state_path.read_bytes()),
                "closure_manifest": "problems/active/p1/closure.json",
                "closure_manifest_sha256": steward.sha256_bytes(closure_path.read_bytes()),
                "verifier_report": "problems/active/p1/verifier.json",
                "verifier_report_sha256": steward.sha256_bytes(verifier_path.read_bytes()),
            }
            with self.assertRaisesRegex(steward.StewardshipError, "identities disagree"):
                steward.validate_protected_evidence(root, evidence, set())

    def test_apply_resumes_after_all_live_writes_before_commit(self):
        with tempfile.TemporaryDirectory(prefix="steward-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            run_id = "r-apply-recover"
            steward.start_run(root, run_id, "DEEP_LOCAL")
            packet = root / "runs/laboratory_stewardship" / run_id
            self.complete_diagnosis(packet)
            item = self.change(
                root,
                packet,
                "knowledge/known_warnings.md",
                "# Warnings\n\n- recovered repair\n",
            )
            self.stage_plan(root, run_id, [item])
            steward.prepare_run(root, run_id)
            original_create = steward.atomic_create

            def fail_commit(path, data, lab_root, mode=0o644):
                if path == packet / "after.sha256":
                    raise steward.StewardshipError("synthetic post-write crash")
                return original_create(path, data, lab_root, mode)

            with mock.patch.object(steward, "atomic_create", side_effect=fail_commit):
                with self.assertRaisesRegex(steward.StewardshipError, "post-write crash"):
                    steward.apply_run(root, run_id)
            self.assertEqual(
                json.loads((packet / "manifest.json").read_text())["status"],
                "PARTIAL_APPLY",
            )
            recovered, code = steward.resume_run(root, run_id)
            self.assertEqual(code, 0)
            self.assertEqual(recovered["status"], "APPLIED")
            events = [
                json.loads(line)["event"]
                for line in (packet / "apply_journal.jsonl").read_text().splitlines()
            ]
            self.assertIn("RECOVERED", events)

    def test_finalize_resumes_after_validated_completion_before_survey(self):
        with tempfile.TemporaryDirectory(prefix="steward-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            run_id = "r-finalize-recover"
            steward.start_run(root, run_id, "DEEP_LOCAL")
            packet = root / "runs/laboratory_stewardship" / run_id
            self.complete_diagnosis(packet)
            item = self.change(
                root,
                packet,
                "knowledge/known_warnings.md",
                "# Warnings\n\n- repaired before final recovery\n",
            )
            self.stage_plan(root, run_id, [item])
            steward.prepare_run(root, run_id)
            steward.apply_run(root, run_id)
            self.complete_report(packet)
            with mock.patch.object(
                steward.survey,
                "start_survey",
                side_effect=steward.survey.SurveyError("synthetic survey-start crash"),
            ):
                with self.assertRaisesRegex(steward.StewardshipError, "survey-start crash"):
                    steward.finalize_run(root, run_id)
            self.assertTrue((packet / "completion_basis.json").is_file())
            self.assertEqual(
                json.loads((packet / "manifest.json").read_text())["status"],
                "VALIDATED_PENDING_SURVEY",
            )
            recovered, code = steward.resume_run(root, run_id)
            self.assertEqual(code, 0)
            self.assertEqual(recovered["status"], "COMPLETED")

    def test_untouched_report_template_cannot_finalize(self):
        template = SCRIPT.parents[1] / "templates/laboratory_stewardship_report.md"
        with self.assertRaisesRegex(steward.StewardshipError, "incomplete"):
            steward.validate_completed_report(template.read_bytes())

    def test_start_refuses_arbitrary_directory(self):
        with tempfile.TemporaryDirectory(prefix="steward-not-lab-") as temp:
            with self.assertRaisesRegex(steward.StewardshipError, "laboratory root"):
                steward.start_run(Path(temp), "r-invalid-root", "DEEP_LOCAL")

    def test_update_preserves_and_revalidates_file_mode(self):
        with tempfile.TemporaryDirectory(prefix="steward-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            target = root / "knowledge/known_warnings.md"
            os.chmod(target, 0o600)
            run_id = "r-mode"
            steward.start_run(root, run_id, "DEEP_LOCAL")
            packet = root / "runs/laboratory_stewardship" / run_id
            self.complete_diagnosis(packet)
            item = self.change(root, packet, "knowledge/known_warnings.md", "# Fixed\n")
            self.stage_plan(root, run_id, [item])
            steward.prepare_run(root, run_id)
            frozen = json.loads((packet / "frozen_plan.json").read_text())
            self.assertEqual(frozen["changes"][0]["before_mode"], 0o600)
            self.assertEqual(frozen["changes"][0]["after_mode"], 0o600)
            steward.apply_run(root, run_id)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_status_transition_must_belong_to_declared_claim(self):
        with tempfile.TemporaryDirectory(prefix="steward-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            ledger = root / "knowledge/results_ledger.yaml"
            ledger.write_text(
                '{"results":['
                '{"claim_id":"CLAIM-A","status":"UNKNOWN"},'
                '{"claim_id":"CLAIM-B","status":"UNKNOWN"}]}\n',
                encoding="utf-8",
            )
            scope = root / "problems/active/p1/target-a.md"
            history = root / "problems/active/p1/history-a.md"
            scope.write_text("Exact claim A\n", encoding="utf-8")
            history.write_text("Claim A status history\n", encoding="utf-8")
            run_id = "r-cross-claim-status"
            steward.start_run(root, run_id, "DEEP_LOCAL")
            packet = root / "runs/laboratory_stewardship" / run_id
            self.complete_diagnosis(packet)
            after = (
                '{"results":['
                '{"claim_id":"CLAIM-A","status":"UNKNOWN"},'
                '{"claim_id":"CLAIM-B","status":"PLAUSIBLE_UNVERIFIED"}]}\n'
            )
            item = self.change(
                root,
                packet,
                "knowledge/results_ledger.yaml",
                after,
                repair_class="EVIDENCE_RECONCILIATION",
                status_transitions=[
                    {
                        "kind": "CONSERVATIVE_RECONCILIATION",
                        "status_field": "results[1].status",
                        "claim_id": "CLAIM-A",
                        "from_status": "UNKNOWN",
                        "to_status": "PLAUSIBLE_UNVERIFIED",
                        "exact_scope_artifact": "problems/active/p1/target-a.md",
                        "exact_scope_sha256": steward.sha256_bytes(scope.read_bytes()),
                        "history_artifact": "problems/active/p1/history-a.md",
                    }
                ],
            )
            self.stage_plan(root, run_id, [item])
            with self.assertRaisesRegex(steward.StewardshipError, "not owned"):
                steward.prepare_run(root, run_id)

    def test_non_json_structured_after_image_is_rejected_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix="steward-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            run_id = "r-non-json-yaml"
            steward.start_run(root, run_id, "DEEP_LOCAL")
            packet = root / "runs/laboratory_stewardship" / run_id
            self.complete_diagnosis(packet)
            item = self.change(
                root,
                packet,
                "knowledge/hidden_status.yaml",
                '"status": "VERIFIED_INTERNAL"\n',
            )
            self.stage_plan(root, run_id, [item])
            with self.assertRaisesRegex(steward.StewardshipError, "JSON-compatible"):
                steward.prepare_run(root, run_id)

    def test_atomic_replace_detects_same_inode_concurrent_edit(self):
        with tempfile.TemporaryDirectory(prefix="steward-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            run_id = "r-replace-race"
            steward.start_run(root, run_id, "DEEP_LOCAL")
            packet = root / "runs/laboratory_stewardship" / run_id
            self.complete_diagnosis(packet)
            target = root / "knowledge/known_warnings.md"
            item = self.change(
                root, packet, "knowledge/known_warnings.md", "# Planned repair\n"
            )
            self.stage_plan(root, run_id, [item])
            steward.prepare_run(root, run_id)
            original_replace = steward.survey.atomic_replace

            def race_replace(path, data, lab_root, mode=0o644, **kwargs):
                if path == target:
                    target.write_text("# Concurrent same-inode edit\n", encoding="utf-8")
                return original_replace(path, data, lab_root, mode, **kwargs)

            with mock.patch.object(
                steward.survey, "atomic_replace", side_effect=race_replace
            ):
                with self.assertRaisesRegex(steward.StewardshipError, "bytes changed"):
                    steward.apply_run(root, run_id)
            self.assertEqual(target.read_text(), "# Concurrent same-inode edit\n")

    def test_validator_mutation_of_planned_target_is_drift(self):
        with tempfile.TemporaryDirectory(prefix="steward-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            run_id = "r-validator-mutation"
            steward.start_run(root, run_id, "DEEP_LOCAL")
            packet = root / "runs/laboratory_stewardship" / run_id
            self.complete_diagnosis(packet)
            item = self.change(
                root,
                packet,
                "knowledge/known_warnings.md",
                "# Planned validated repair\n",
            )
            self.stage_plan(root, run_id, [item])
            steward.prepare_run(root, run_id)
            steward.apply_run(root, run_id)
            self.complete_report(packet)
            (root / "scripts/doctor.py").write_text(
                "from pathlib import Path\n"
                "Path('knowledge/known_warnings.md').write_text('# Validator mutation\\n')\n",
                encoding="utf-8",
            )
            result, code = steward.finalize_run(root, run_id)
            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "DRIFT_DETECTED")

    def test_status_owner_cannot_move_by_reordering_stable_ids(self):
        with tempfile.TemporaryDirectory(prefix="steward-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            ledger = root / "knowledge/results_ledger.yaml"
            ledger.write_text(
                '{"results":['
                '{"id":"A","status":"VERIFIED_INTERNAL"},'
                '{"id":"B","status":"UNKNOWN"}]}\n',
                encoding="utf-8",
            )
            run_id = "r-owner-swap"
            steward.start_run(root, run_id, "DEEP_LOCAL")
            packet = root / "runs/laboratory_stewardship" / run_id
            self.complete_diagnosis(packet)
            item = self.change(
                root,
                packet,
                "knowledge/results_ledger.yaml",
                '{"results":['
                '{"id":"B","status":"VERIFIED_INTERNAL"},'
                '{"id":"A","status":"UNKNOWN"}]}\n',
            )
            self.stage_plan(root, run_id, [item])
            with self.assertRaisesRegex(steward.StewardshipError, "relocates a status"):
                steward.prepare_run(root, run_id)
            ambiguous_before = (
                b'{"results":[{"id":"B","target_id":"A","status":"VERIFIED_INTERNAL"},'
                b'{"id":"D","target_id":"C","status":"UNKNOWN"}]}'
            )
            ambiguous_after = (
                b'{"results":[{"id":"D","target_id":"C","status":"VERIFIED_INTERNAL"},'
                b'{"id":"B","target_id":"A","status":"UNKNOWN"}]}'
            )
            self.assertNotEqual(
                steward.status_claim_bindings(ambiguous_before),
                steward.status_claim_bindings(ambiguous_after),
            )

    def test_proof_gate_cannot_authorize_refutation_or_formal_status(self):
        with tempfile.TemporaryDirectory(prefix="steward-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            scope = root / "problems/active/p1/target.md"
            scope.write_text("Exact positive theorem target\n", encoding="utf-8")
            base = {
                "kind": "EXISTING_VERDICT",
                "status_field": "results[0].status",
                "claim_id": "TARGET-A",
                "from_status": "UNKNOWN",
                "exact_scope_artifact": "problems/active/p1/target.md",
                "exact_scope_sha256": steward.sha256_bytes(scope.read_bytes()),
                "problem_id": "p1",
                "target_id": "TARGET-A",
                "gate": "PROOF_I3",
                "independence_level": "I3",
                "verdict": "PASS",
            }
            for destination in ("REFUTED", "FORMALLY_VERIFIED"):
                transition = dict(base, to_status=destination)
                with self.assertRaisesRegex(steward.StewardshipError, "proof-established"):
                    steward.validate_status_transition(
                        root,
                        transition,
                        [("results[0].status", "UNKNOWN", destination)],
                        set(),
                    )
            conservative = {
                "kind": "CONSERVATIVE_RECONCILIATION",
                "status_field": "results[0].status",
                "claim_id": "TARGET-A",
                "from_status": "UNKNOWN",
                "to_status": "COMPUTER_CHECKED",
                "exact_scope_artifact": "problems/active/p1/target.md",
                "exact_scope_sha256": steward.sha256_bytes(scope.read_bytes()),
                "history_artifact": "problems/active/p1/target.md",
            }
            with self.assertRaisesRegex(steward.StewardshipError, "non-decisive"):
                steward.validate_status_transition(
                    root,
                    conservative,
                    [("results[0].status", "UNKNOWN", "COMPUTER_CHECKED")],
                    set(),
                )

    def test_multi_dossier_index_status_sync_uses_one_binding_per_transition(self):
        with tempfile.TemporaryDirectory(prefix="steward-index-sync-") as temp:
            root = Path(temp)
            self.make_lab(root)
            state_path = root / "knowledge/research_state.yaml"
            state_path.write_text(
                '{"laboratory_status":"ACTIVE","completed_problem_ids":[],'
                '"dossiers":[],"tracks":{"synthetic":{"status":"ACTIVE"}}}\n',
                encoding="utf-8",
            )
            (root / "knowledge/laboratory_dashboard.md").write_text(
                "# Old dashboard\n", encoding="utf-8"
            )
            (root / "problems/INDEX.md").write_text(
                "# Old problem index\n", encoding="utf-8"
            )
            proof = self.authoritative_dossier_evidence(
                root, "p-proof", "VERIFIED_PROOF"
            )
            counterexample = self.authoritative_dossier_evidence(
                root, "p-counterexample", "VERIFIED_COUNTEREXAMPLE"
            )
            run_id = "r-index-sync-multi"
            steward.start_run(root, run_id, "DEEP_LOCAL")
            packet = root / "runs/laboratory_stewardship" / run_id
            self.complete_diagnosis(packet)
            after_state = json.dumps(
                {
                    "laboratory_status": "ACTIVE",
                    "completed_problem_ids": ["p-proof", "p-counterexample"],
                    "dossiers": [
                        {
                            "problem_id": "p-proof",
                            "global_status": "VERIFIED_PROOF",
                        },
                        {
                            "problem_id": "p-counterexample",
                            "global_status": "VERIFIED_COUNTEREXAMPLE",
                        },
                    ],
                    "tracks": {"synthetic": {"status": "COMPLETE"}},
                }
            ) + "\n"
            proof["status_field"] = "dossiers[0].global_status"
            counterexample["status_field"] = "dossiers[1].global_status"
            state_change = self.change(
                root,
                packet,
                "knowledge/research_state.yaml",
                after_state,
                id="sync-terminal-dossiers",
                repair_class="EVIDENCE_RECONCILIATION",
                mathematical_effect="SYNCHRONIZE_EXISTING_DOSSIER_STATUS",
                index_status_evidence=[proof, counterexample],
                status_transitions=[
                    self.dossier_status_transition(
                        proof, "dossiers[0].global_status"
                    ),
                    self.dossier_status_transition(
                        counterexample, "dossiers[1].global_status"
                    ),
                ],
            )
            dashboard_change = self.change(
                root,
                packet,
                "knowledge/laboratory_dashboard.md",
                "# Reconciled dashboard\n",
                id="refresh-dashboard-navigation",
            )
            problem_index_change = self.change(
                root,
                packet,
                "problems/INDEX.md",
                "# Reconciled problem index\n",
                id="refresh-problem-navigation",
            )
            self.stage_plan(
                root,
                run_id,
                [state_change, dashboard_change, problem_index_change],
            )
            prepared = steward.prepare_run(root, run_id)
            self.assertEqual(prepared["status"], "PREPARED")
            self.assertTrue((packet / "protected_preflight.json").is_file())
            applied = steward.apply_run(root, run_id)
            self.assertEqual(applied["status"], "APPLIED")
            self.assertEqual(
                json.loads(state_path.read_text(encoding="utf-8"))[
                    "completed_problem_ids"
                ],
                ["p-proof", "p-counterexample"],
            )

    def test_index_status_evidence_rejects_wrong_hash_path_and_planned_source(self):
        with tempfile.TemporaryDirectory(prefix="steward-index-evidence-") as temp:
            root = Path(temp)
            self.make_lab(root)
            evidence = self.authoritative_dossier_evidence(
                root, "p-proof", "VERIFIED_PROOF"
            )
            evidence["status_field"] = "problem_summaries[0].status"
            wrong_hash = dict(evidence, proof_search_state_sha256="0" * 64)
            with self.assertRaisesRegex(steward.StewardshipError, "digest mismatch"):
                steward.validate_index_status_evidence(root, [wrong_hash], set())

            noncanonical = root / "knowledge/proof_search_state.yaml"
            source = root / evidence["proof_search_state"]
            noncanonical.write_bytes(source.read_bytes())
            wrong_path = dict(
                evidence,
                proof_search_state="knowledge/proof_search_state.yaml",
                proof_search_state_sha256=steward.sha256_bytes(noncanonical.read_bytes()),
            )
            with self.assertRaisesRegex(
                steward.StewardshipError, "canonical dossier"
            ):
                steward.validate_index_status_evidence(root, [wrong_path], set())

            with self.assertRaisesRegex(
                steward.StewardshipError, "pre-exist and remain immutable"
            ):
                steward.validate_index_status_evidence(
                    root, [evidence], {evidence["proof_search_state"]}
                )

            wrong_claim = dict(evidence, claim_id="another-problem")
            with self.assertRaisesRegex(
                steward.StewardshipError, "canonical dossier problem_id"
            ):
                steward.validate_index_status_evidence(root, [wrong_claim], set())

    def test_index_status_evidence_rejects_status_and_counterexample_mismatch(self):
        with tempfile.TemporaryDirectory(prefix="steward-index-status-") as temp:
            root = Path(temp)
            self.make_lab(root)
            evidence = self.authoritative_dossier_evidence(
                root, "p-proof", "VERIFIED_PROOF"
            )
            evidence["status_field"] = "problem_summaries[0].status"
            wrong_status = dict(
                evidence, authoritative_status="VERIFIED_COUNTEREXAMPLE"
            )
            with self.assertRaisesRegex(
                steward.StewardshipError, "problem/status binding"
            ):
                steward.validate_index_status_evidence(root, [wrong_status], set())

        with tempfile.TemporaryDirectory(prefix="steward-index-counterexample-") as temp:
            root = Path(temp)
            self.make_lab(root)
            evidence = self.authoritative_dossier_evidence(
                root, "p-counterexample", "VERIFIED_COUNTEREXAMPLE"
            )
            evidence["status_field"] = "problem_summaries[0].status"
            state_path = root / evidence["proof_search_state"]
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["routes"][0]["status"] = "CLOSED_PROOF"
            state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
            evidence["proof_search_state_sha256"] = steward.sha256_bytes(
                state_path.read_bytes()
            )
            with self.assertRaisesRegex(
                steward.StewardshipError, "terminal route disagrees"
            ):
                steward.validate_index_status_evidence(root, [evidence], set())

    def test_index_status_sync_rejects_missing_evidence(self):
        with tempfile.TemporaryDirectory(prefix="steward-index-missing-") as temp:
            root = Path(temp)
            self.make_lab(root)
            evidence = self.authoritative_dossier_evidence(
                root, "p-proof", "VERIFIED_PROOF"
            )
            state_path = root / "knowledge/research_state.yaml"
            state_path.write_text(
                '{"laboratory_status":"ACTIVE","problem_summaries":[]}\n',
                encoding="utf-8",
            )
            run_id = "r-index-missing-evidence"
            steward.start_run(root, run_id, "DEEP_LOCAL")
            packet = root / "runs/laboratory_stewardship" / run_id
            self.complete_diagnosis(packet)
            field = "problem_summaries[0].status"
            item = self.change(
                root,
                packet,
                "knowledge/research_state.yaml",
                '{"laboratory_status":"ACTIVE","problem_summaries":['
                '{"problem_id":"p-proof","status":"VERIFIED_PROOF"}]}\n',
                repair_class="EVIDENCE_RECONCILIATION",
                mathematical_effect="SYNCHRONIZE_EXISTING_DOSSIER_STATUS",
                index_status_evidence=[],
                status_transitions=[self.dossier_status_transition(evidence, field)],
            )
            self.stage_plan(root, run_id, [item])
            with self.assertRaisesRegex(
                steward.StewardshipError, "requires index_status_evidence"
            ):
                steward.prepare_run(root, run_id)

    def test_index_status_sync_rejects_noncanonical_projection_target(self):
        with tempfile.TemporaryDirectory(prefix="steward-index-target-") as temp:
            root = Path(temp)
            self.make_lab(root)
            evidence = self.authoritative_dossier_evidence(
                root, "p-proof", "VERIFIED_PROOF"
            )
            ledger = root / "knowledge/results_ledger.yaml"
            ledger.write_text(
                '{"results":[{"problem_id":"p-proof","status":"UNKNOWN"}]}\n',
                encoding="utf-8",
            )
            run_id = "r-index-wrong-target"
            steward.start_run(root, run_id, "DEEP_LOCAL")
            packet = root / "runs/laboratory_stewardship" / run_id
            self.complete_diagnosis(packet)
            field = "results[0].status"
            evidence["status_field"] = field
            item = self.change(
                root,
                packet,
                "knowledge/results_ledger.yaml",
                '{"results":[{"problem_id":"p-proof",'
                '"status":"VERIFIED_PROOF"}]}\n',
                repair_class="EVIDENCE_RECONCILIATION",
                mathematical_effect="SYNCHRONIZE_EXISTING_DOSSIER_STATUS",
                index_status_evidence=[evidence],
                status_transitions=[
                    self.dossier_status_transition(
                        evidence, field, from_status="UNKNOWN"
                    )
                ],
            )
            self.stage_plan(root, run_id, [item])
            with self.assertRaisesRegex(
                steward.StewardshipError, "target is not canonical"
            ):
                steward.prepare_run(root, run_id)

    def test_index_status_sync_rejects_strong_aggregate_track_promotion(self):
        with self.assertRaisesRegex(
            steward.StewardshipError, "aggregate track to a strong status"
        ):
            steward.index_status_pairs(
                [("tracks.synthetic.status", "ACTIVE", "VERIFIED_PROOF")]
            )
        with self.assertRaisesRegex(
            steward.StewardshipError, "only dossier global_status"
        ):
            steward.index_status_pairs(
                [("tracks.synthetic.status", None, "COMPLETE")]
            )

    def test_supplemental_problem_index_is_hash_bound_and_no_follow(self):
        with tempfile.TemporaryDirectory(prefix="steward-index-snapshot-") as temp:
            root = Path(temp)
            self.make_lab(root)
            problem_index = root / "problems/INDEX.md"
            problem_index.write_text("# Problem index\n", encoding="utf-8")
            value = steward.snapshot(root)
            paths = {item["path"]: item for item in value["files"]}
            self.assertEqual(
                paths["problems/INDEX.md"]["sha256"],
                steward.sha256_bytes(problem_index.read_bytes()),
            )
            problem_index.unlink()
            problem_index.symlink_to(root / "BACKLOG.md")
            with self.assertRaisesRegex(steward.StewardshipError, "symlink"):
                steward.snapshot(root)


if __name__ == "__main__":
    unittest.main()
