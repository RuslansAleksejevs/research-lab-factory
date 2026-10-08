from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import stat
import tempfile
import unittest
from pathlib import Path


LAB_TEMPLATE_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "repository_first", LAB_TEMPLATE_ROOT / "scripts" / "repository_first.py"
)
assert SPEC and SPEC.loader
repository_first = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repository_first)

RELEASE_SPEC = importlib.util.spec_from_file_location(
    "research_release_for_repository_first_tests",
    LAB_TEMPLATE_ROOT / "scripts" / "research_release.py",
)
assert RELEASE_SPEC and RELEASE_SPEC.loader
research_release = importlib.util.module_from_spec(RELEASE_SPEC)
RELEASE_SPEC.loader.exec_module(research_release)

MEMORY_SPEC = importlib.util.spec_from_file_location(
    "research_memory_for_repository_first_tests",
    LAB_TEMPLATE_ROOT / "scripts" / "research_memory.py",
)
assert MEMORY_SPEC and MEMORY_SPEC.loader
research_memory = importlib.util.module_from_spec(MEMORY_SPEC)
MEMORY_SPEC.loader.exec_module(research_memory)


class RepositoryFirstTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="repository-first-test-")
        self.root = Path(self.temporary.name)
        self.write_json(
            "LAB_PROFILE.json",
            {
                "repository_first": {
                    "enabled": True,
                    "canonical_repository_visibility": "PRIVATE",
                    "raw_material_policy": "LOCAL_UNTRACKED",
                    "export_policy": "REVIEWED_ONLY",
                    "process_steward": "replace-human-owner",
                },
                "lab": {
                    "owners": ["Replace Human Owner"],
                    "modules": [],
                    "collaboration": None,
                },
            },
        )
        self.write_text(
            ".gitignore",
            "# repository-first-local-raw-archive:v1\n"
            "research/raw_runs/archive/\n"
            "# /repository-first-local-raw-archive:v1\n",
        )
        files = {
            "paper/main.tex": "\\documentclass{article}\n\\begin{document}Replace manuscript.\\end{document}\n",
            "problems/active/replace-problem-id/problem.md": "exact claim\n",
            "problems/active/replace-problem-id/attempts/replace-input.md": "phase input\n",
            "problems/active/replace-problem-id/attempts/replace-run.md": "run evidence\n",
            "problems/active/replace-problem-id/proof_obligations.md": "obligations\n",
            "problems/active/replace-problem-id/source_facts.md": "source audit\n",
            "problems/active/replace-problem-id/assumptions.md": "axioms\n",
            "problems/active/replace-problem-id/computations/replace-command-manifest.json": "{}\n",
            "problems/active/replace-problem-id/computations/replace-replay-manifest.json": "{}\n",
            "problems/active/replace-problem-id/repository_first/prompts/replace-action-prompt.md": "lab-authored action prompt\n",
            "problems/active/replace-problem-id/repository_first/feedback_imports/replace-original.txt": "expert response\n",
            "problems/active/replace-problem-id/repository_first/feedback_imports/replace-observations.md": "bounded observations\n",
            "research/checkpoints/replace-checkpoint.md": "checkpoint\n",
            "sources/originals/replace-source.pdf": "preserved source bytes\n",
        }
        for path, body in files.items():
            self.write_text(path, body)
        checkpoint = json.loads(
            (LAB_TEMPLATE_ROOT / "templates" / "research_checkpoint.json").read_text(
                encoding="utf-8"
            )
        )
        checkpoint["checkpoint_id"] = "replace-checkpoint"
        checkpoint["run_id"] = "replace-run-id"
        checkpoint["problem_ids"] = ["replace-problem-id"]
        checkpoint["claim_ids"] = ["replace-target-claim-id"]
        self.write_text(
            "research/checkpoints/replace-checkpoint.md",
            research_memory.render_checkpoint(checkpoint).decode("utf-8"),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_text(self, relative: str, text: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_json(self, relative: str, value: object) -> Path:
        return self.write_text(relative, json.dumps(value, indent=2, sort_keys=True) + "\n")

    def template(self, name: str) -> dict[str, object]:
        return json.loads(
            (LAB_TEMPLATE_ROOT / "templates" / "repository_first" / name).read_text(
                encoding="utf-8"
            )
        )

    def digest(self, relative: str) -> str:
        return hashlib.sha256((self.root / relative).read_bytes()).hexdigest()

    def campaign(self) -> dict[str, object]:
        return self.template("campaign.json")

    def raw_run(self) -> dict[str, object]:
        record = self.template("raw_run_manifest.json")
        prompt = record["significant_prompts"][0]
        prompt["sha256"] = self.digest(prompt["path"])
        command = record["execution_provenance"]["tool_commands"][0]
        command["command_manifest_sha256"] = self.digest(command["command_manifest_path"])
        record["checkpoint_sha256"] = self.digest(record["checkpoint_path"])
        record["claim_dossier_anchor_sha256"] = self.digest(
            record["claim_dossier_anchor_path"]
        )
        return record

    def source_use(self) -> dict[str, object]:
        record = self.template("source_use.json")
        record["original_sha256"] = self.digest(record["source_path"])
        record["claim_statement_sha256"] = self.digest(record["claim_statement_path"])
        return record

    def feedback_response(self) -> dict[str, object]:
        record = self.template("expert_feedback_response.json")
        record["original_sha256"] = self.digest(record["original_path"])
        implication = record["claim_implications"][0]
        implication["claim_statement_sha256"] = self.digest(
            implication["claim_statement_path"]
        )
        return record

    def export_request(self) -> dict[str, object]:
        request = repository_first.prepare_export(self.root, self.template("export_request.json"))
        request["review"] = {
            "status": "REVIEWED", "reviewed_at_utc": "2026-01-01T07:00:00Z",
            "reviewer_role_ids": ["human-owner"], "scope_note": "Exact synthetic fixture files reviewed.",
        }
        return request

    def feedback_plan(self) -> dict[str, object]:
        manifest_path = repository_first.build_export(
            self.root,
            self.export_request(),
        )
        record = self.template("expert_feedback_plan.json")
        record["package_manifest_sha256"] = hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest()
        binding = record["claim_bindings"][0]
        binding["claim_statement_sha256"] = self.digest(binding["claim_statement_path"])
        return record

    def output_for(self, record: dict[str, object]) -> str:
        record_type = record["record_type"]
        record_id = record[repository_first.RECORD_ID_FIELDS[record_type]]
        return (
            "problems/active/replace-problem-id/repository_first/records/"
            f"{record_type}/{record_id}.json"
        )

    def publish(self, record: dict[str, object]) -> Path:
        return repository_first.record_packet(self.root, record, self.output_for(record))

    def test_all_templates_are_structurally_valid(self) -> None:
        template_root = LAB_TEMPLATE_ROOT / "templates" / "repository_first"
        names = []
        for path in sorted(template_root.glob("*.json")):
            names.append(path.name)
            value = json.loads(path.read_text(encoding="utf-8"))
            if path.name == "export_request.json":
                repository_first._validate_export_request(value, require_review=False)
            elif path.name == "release_request.json":
                research_release.validate_request(value)
            else:
                repository_first.validate_record(value, self.root, require_files=False)
        self.assertEqual(
            names,
            [
                "adjacent_result.json",
                "campaign.json",
                "claim_assessment.json",
                "expert_feedback_plan.json",
                "expert_feedback_response.json",
                "export_request.json",
                "failure_family.json",
                "phase_change.json",
                "raw_run_manifest.json",
                "release_request.json",
                "source_use.json",
                "verification_coverage.json",
            ],
        )

    def test_union_schema_and_every_typed_object_are_closed(self) -> None:
        schema_path = LAB_TEMPLATE_ROOT / "schemas" / "repository_first.schema.json"
        duplicate_keys = []

        def strict_pairs(pairs):
            value = {}
            for key, child in pairs:
                if key in value:
                    duplicate_keys.append(key)
                value[key] = child
            return value

        schema = json.loads(schema_path.read_text(encoding="utf-8"), object_pairs_hook=strict_pairs)
        self.assertEqual(duplicate_keys, [])
        self.assertIs(schema["additionalProperties"], False)
        non_closed = []

        def inspect(value, path="$"):
            if isinstance(value, dict):
                if value.get("type") == "object" and value.get("additionalProperties") is not False:
                    non_closed.append(path)
                for key, child in value.items():
                    inspect(child, f"{path}.{key}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    inspect(child, f"{path}[{index}]")

        inspect(schema)
        self.assertEqual(non_closed, [])

    def test_disabled_policy_is_dormant_and_does_not_scan_records(self) -> None:
        self.write_json("LAB_PROFILE.json", {"repository_first": {"enabled": False}})
        self.write_text(
            "problems/active/replace-problem-id/repository_first/records/campaign/broken.json",
            "not json and deliberately not inspected\n",
        )
        report = repository_first.validate_repository(self.root)
        self.assertEqual(report["status"], "DISABLED")
        self.assertEqual(report["records_validated"], 0)
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "write commands are dormant"):
            self.publish(self.campaign())

    def test_enabled_profile_contract_is_exact_and_private(self) -> None:
        profile = json.loads((self.root / "LAB_PROFILE.json").read_text(encoding="utf-8"))
        profile["repository_first"]["canonical_repository_visibility"] = "PUBLIC"
        self.write_json("LAB_PROFILE.json", profile)
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "must be PRIVATE"):
            repository_first.validate_repository(self.root)

    def test_solo_process_steward_matches_owner_name_or_generator_normalized_id(self) -> None:
        profile = json.loads((self.root / "LAB_PROFILE.json").read_text(encoding="utf-8"))
        profile["lab"]["owners"] = ["Research Owner"]

        profile["repository_first"]["process_steward"] = "Research Owner"
        self.write_json("LAB_PROFILE.json", profile)
        self.assertTrue(repository_first.repository_enabled(self.root))

        profile["repository_first"]["process_steward"] = "research-owner"
        self.write_json("LAB_PROFILE.json", profile)
        self.assertTrue(repository_first.repository_enabled(self.root))

        profile["repository_first"]["process_steward"] = "another-owner"
        self.write_json("LAB_PROFILE.json", profile)
        with self.assertRaisesRegex(
            repository_first.RepositoryFirstError,
            "solo owner display name or generator-normalized owner id",
        ):
            repository_first.repository_enabled(self.root)

    def test_team_process_steward_and_private_visibility_are_exact(self) -> None:
        profile = json.loads((self.root / "LAB_PROFILE.json").read_text(encoding="utf-8"))
        profile["lab"] = {
            "owners": ["Research Steward", "Research Partner"],
            "modules": ["team_collaboration"],
            "collaboration": {
                "steward_id": "research_steward",
                "repository": {"visibility": "PRIVATE"},
            },
        }
        profile["repository_first"]["process_steward"] = "research_steward"
        self.write_json("LAB_PROFILE.json", profile)
        self.assertTrue(repository_first.repository_enabled(self.root))

        profile["repository_first"]["process_steward"] = "Research Steward"
        self.write_json("LAB_PROFILE.json", profile)
        with self.assertRaisesRegex(
            repository_first.RepositoryFirstError,
            "exactly equal.*collaboration.steward_id",
        ):
            repository_first.repository_enabled(self.root)

        profile["repository_first"]["process_steward"] = "research_steward"
        profile["lab"]["collaboration"]["repository"]["visibility"] = "PUBLIC"
        self.write_json("LAB_PROFILE.json", profile)
        with self.assertRaisesRegex(
            repository_first.RepositoryFirstError,
            "repository.visibility PRIVATE",
        ):
            repository_first.repository_enabled(self.root)

    def test_process_steward_text_is_trimmed_one_line_nfc_and_at_most_256(self) -> None:
        profile = json.loads((self.root / "LAB_PROFILE.json").read_text(encoding="utf-8"))
        boundary = "x" * 256
        profile["lab"]["owners"] = [boundary]
        profile["repository_first"]["process_steward"] = boundary
        self.write_json("LAB_PROFILE.json", profile)
        self.assertTrue(repository_first.repository_enabled(self.root))

        invalid = {
            "oversize": ("x" * 257, "size bound"),
            "surrounding whitespace": (" Research Owner", "surrounding whitespace"),
            "unicode line separator": ("Research\u2028Owner", "one line"),
            "non-NFC": ("Re\u0301search Owner", "NFC Unicode"),
        }
        for case, (process_steward, message) in invalid.items():
            with self.subTest(case=case):
                profile["repository_first"]["process_steward"] = process_steward
                self.write_json("LAB_PROFILE.json", profile)
                with self.assertRaisesRegex(repository_first.RepositoryFirstError, message):
                    repository_first.repository_enabled(self.root)

    def test_cross_axis_confusion_and_overall_status_are_rejected(self) -> None:
        record = self.template("claim_assessment.json")
        record["axes"]["novelty"] = copy.deepcopy(record["axes"]["correctness"])
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "cannot substitute"):
            repository_first.validate_record(record, self.root)

        record = self.template("claim_assessment.json")
        record["overall_status"] = "PASS"
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "forbidden field"):
            repository_first.validate_record(record, self.root)

        record = self.template("claim_assessment.json")
        record["axes"]["novelty"]["status"] = "PASS"
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "must be one of"):
            repository_first.validate_record(record, self.root)

    def test_raw_git_paths_and_hidden_prompt_classes_are_rejected(self) -> None:
        record = self.raw_run()
        record["raw_archive"]["path"] = (
            "research/raw_runs/archive/replace-problem-id/.git/config"
        )
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "Git metadata"):
            repository_first.validate_record(record, self.root)

        record = self.raw_run()
        record["significant_prompts"][0]["prompt_class"] = "DEVELOPER_PROMPT"
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "lab-authored action prompt"):
            repository_first.validate_record(record, self.root)

    def test_raw_execution_provenance_represents_honest_unknowns(self) -> None:
        record = self.raw_run()
        repository_first.validate_record(record, self.root)

        bad_version = copy.deepcopy(record)
        bad_version["execution_provenance"]["model"]["exact_version"] = "invented"
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "must be null when UNKNOWN"):
            repository_first.validate_record(bad_version, self.root)

        missing_denominator = copy.deepcopy(record)
        missing_denominator["execution_provenance"]["actual_denominator"]["reasoning_tokens"] = None
        missing_denominator["execution_provenance"]["actual_denominator"]["unknown_fields"] = []
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "must be an integer"):
            repository_first.validate_record(missing_denominator, self.root)

        no_provenance = copy.deepcopy(record)
        del no_provenance["execution_provenance"]
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "missing keys"):
            repository_first.validate_record(no_provenance, self.root)

    def test_raw_run_requires_canonical_exact_checkpoint_and_dossier_anchor(self) -> None:
        raw = self.raw_run()
        self.write_text(raw["checkpoint_path"], "checkpoint\n")
        raw["checkpoint_sha256"] = self.digest(raw["checkpoint_path"])
        with self.assertRaisesRegex(
            repository_first.RepositoryFirstError,
            "canonical Durable Research Memory envelope",
        ):
            repository_first.validate_record(raw, self.root, require_files=True)

        checkpoint = json.loads(
            (LAB_TEMPLATE_ROOT / "templates" / "research_checkpoint.json").read_text(
                encoding="utf-8"
            )
        )
        checkpoint["checkpoint_id"] = "replace-checkpoint"
        checkpoint["run_id"] = "different-run-id"
        checkpoint["problem_ids"] = ["replace-problem-id"]
        checkpoint["claim_ids"] = ["replace-target-claim-id"]
        self.write_text(
            raw["checkpoint_path"],
            research_memory.render_checkpoint(checkpoint).decode("utf-8"),
        )
        raw["checkpoint_sha256"] = self.digest(raw["checkpoint_path"])
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "run_id does not match"):
            repository_first.validate_record(raw, self.root, require_files=True)

        raw = self.raw_run()
        raw["claim_dossier_anchor_path"] = "problems/active/another-problem/problem.md"
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "outside its allowed roots"):
            repository_first.validate_record(raw, self.root)

    def test_raw_checkpoint_symlinked_ancestor_is_rejected(self) -> None:
        checkpoint_directory = self.root / "research/checkpoints"
        external_directory = self.root / "external-checkpoints"
        checkpoint_directory.rename(external_directory)
        checkpoint_directory.symlink_to(external_directory, target_is_directory=True)
        raw = self.raw_run()
        with self.assertRaisesRegex(
            repository_first.RepositoryFirstError,
            "traverses a symlink",
        ):
            repository_first.validate_record(raw, self.root, require_files=True)

    def test_phase_retry_requires_failure_pointer_and_changed_search_policy(self) -> None:
        record = self.template("phase_change.json")
        record["transition_kind"] = "RETRY_AFTER_FAILURE"
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "prior_failure_family_ids"):
            repository_first.validate_record(record, self.root)

        record["prior_failure_family_ids"] = ["replace-failure-family-id"]
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "search_policy_delta"):
            repository_first.validate_record(record, self.root)

        record["search_policy_delta"] = "Exclude the failed mechanism and test a changed representation."
        repository_first.validate_record(record, self.root)

    def test_raw_run_phase_must_match_append_only_phase_timeline(self) -> None:
        self.publish(self.campaign())
        self.publish(self.template("phase_change.json"))
        raw = self.raw_run()
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "phase timeline"):
            self.publish(raw)
        raw["phase"] = "MECHANISM_DEVELOPMENT"
        self.publish(raw)

    def test_outbound_fields_are_rejected(self) -> None:
        plan = self.template("expert_feedback_plan.json")
        plan["recipient_email"] = "nobody@example.invalid"
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "forbidden field"):
            repository_first.validate_record(plan, self.root)

        request = self.template("export_request.json")
        request["outbound_action"] = "send"
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "forbidden field"):
            repository_first._validate_export_request(request)

    def test_specialization_cannot_be_promoted_or_translated_without_matching_audit(self) -> None:
        record = self.source_use()
        record["relation"] = "STRENGTHENING"
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "cannot be promoted"):
            repository_first.validate_record(record, self.root)

        record["relation_audit"] = None
        with self.assertRaises(repository_first.RepositoryFirstError):
            repository_first.validate_record(record, self.root)

        translation = self.source_use()
        translation["relation"] = "LANGUAGE_TRANSLATION"
        translation["relation_audit"]["audited_relation"] = "LANGUAGE_TRANSLATION"
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "must be a relative"):
            repository_first.validate_record(translation, self.root)

    def test_source_use_requires_structured_interface_search(self) -> None:
        source = self.source_use()
        del source["interface_search"]
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "missing keys"):
            repository_first.validate_record(source, self.root)

        source = self.source_use()
        source["interface_search"]["outputs"] = []
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "must not be empty"):
            repository_first.validate_record(source, self.root)

        source = self.source_use()
        source["interface_search"]["known_bottlenecks"] = []
        source["interface_search"]["candidate_bridge_obligations"] = []
        repository_first.validate_record(source, self.root)

    def test_expert_feedback_cannot_promote_claims(self) -> None:
        response = self.feedback_response()
        response["automatic_claim_promotion"] = True
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "must be false"):
            repository_first.validate_record(response, self.root)

        response = self.feedback_response()
        response["claim_status"] = "VERIFIED"
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "forbidden field"):
            repository_first.validate_record(response, self.root)

    def test_feedback_is_bound_to_exact_reviewed_export_and_claim_preimages(self) -> None:
        self.publish(self.campaign())
        plan = self.feedback_plan()

        bad_package = copy.deepcopy(plan)
        bad_package["package_manifest_sha256"] = "0" * 64
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "SHA-256 does not match"):
            repository_first.validate_record(bad_package, self.root, require_files=True)

        unexported_preimage = copy.deepcopy(plan)
        unexported_preimage["claim_bindings"][0]["claim_statement_path"] = (
            "problems/active/replace-problem-id/attempts/replace-run.md"
        )
        unexported_preimage["claim_bindings"][0]["claim_statement_sha256"] = self.digest(
            unexported_preimage["claim_bindings"][0]["claim_statement_path"]
        )
        with self.assertRaisesRegex(
            repository_first.RepositoryFirstError,
            "claim_bindings do not exactly match",
        ):
            repository_first.validate_record(
                unexported_preimage,
                self.root,
                require_files=True,
            )

        bogus_version = copy.deepcopy(plan)
        bogus_version["claim_bindings"][0]["claim_statement_version"] = (
            "UNBOUND-BOGUS-VERSION"
        )
        with self.assertRaisesRegex(
            repository_first.RepositoryFirstError,
            "claim_bindings do not exactly match",
        ):
            repository_first.validate_record(
                bogus_version,
                self.root,
                require_files=True,
            )

        nonhuman_trigger = copy.deepcopy(plan)
        nonhuman_trigger["plan_id"] = "replace-feedback-plan-nonhuman"
        nonhuman_trigger["human_trigger"]["triggered_by_role_id"] = "research-operator"
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "must name a HUMAN role"):
            self.publish(nonhuman_trigger)

        self.publish(plan)
        response = self.feedback_response()
        self.publish(response)

        unplanned = self.feedback_response()
        unplanned["response_id"] = "replace-feedback-response-unplanned"
        unplanned["claim_implications"][0]["claim_id"] = "unplanned-claim-id"
        with self.assertRaisesRegex(
            repository_first.RepositoryFirstError,
            "outside the plan's exact bound claim preimages",
        ):
            self.publish(unplanned)

        wrong_preimage = self.feedback_response()
        wrong_preimage["response_id"] = "replace-feedback-response-wrong-preimage"
        wrong_preimage["claim_implications"][0]["claim_statement_sha256"] = "f" * 64
        with self.assertRaisesRegex(
            repository_first.RepositoryFirstError,
            "outside the plan's exact bound claim preimages",
        ):
            self.publish(wrong_preimage)

    def test_feedback_plan_cannot_predate_reviewed_export(self) -> None:
        future_request = self.export_request()
        future_request["created_at_utc"] = "2099-01-01T07:00:00Z"
        future_request["review"]["reviewed_at_utc"] = "2099-01-01T06:59:59Z"
        manifest_path = repository_first.build_export(self.root, future_request)
        plan = self.template("expert_feedback_plan.json")
        plan["package_manifest_sha256"] = hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest()
        plan_binding = plan["claim_bindings"][0]
        plan_binding["claim_statement_sha256"] = self.digest(
            plan_binding["claim_statement_path"]
        )
        with self.assertRaisesRegex(
            repository_first.RepositoryFirstError,
            "plan creation predates the reviewed export manifest",
        ):
            repository_first.validate_record(plan, self.root, require_files=True)

    def test_feedback_response_cannot_predate_plan_review(self) -> None:
        self.publish(self.campaign())
        reviewed_plan = self.feedback_plan()
        reviewed_plan["review"]["reviewed_at_utc"] = "2026-01-01T08:00:00Z"
        self.publish(reviewed_plan)
        early_response = self.feedback_response()
        early_response["received_at_utc"] = "2026-01-01T07:30:00Z"
        with self.assertRaisesRegex(
            repository_first.RepositoryFirstError,
            "predates review of its feedback plan",
        ):
            self.publish(early_response)

    def test_export_review_cannot_postdate_manifest_creation(self) -> None:
        request = self.export_request()
        request["review"]["reviewed_at_utc"] = "2026-01-01T07:00:01Z"
        with self.assertRaisesRegex(
            repository_first.RepositoryFirstError,
            "review cannot postdate manifest creation",
        ):
            repository_first._validate_export_request(request)

    def test_bad_hashes_paths_and_raw_export_inputs_are_rejected(self) -> None:
        source = self.source_use()
        source["original_sha256"] = "BAD"
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "lowercase SHA-256"):
            repository_first.validate_record(source, self.root)

        source = self.source_use()
        source["source_path"] = "sources/../.git/config"
        with self.assertRaises(repository_first.RepositoryFirstError):
            repository_first.validate_record(source, self.root)

        request = self.template("export_request.json")
        request["included_files"][0]["path"] = (
            "research/raw_runs/archive/replace-problem-id/replace-run-id.jsonl"
        )
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "forbidden raw"):
            repository_first._validate_export_request(request, require_review=False)

        raw = self.raw_run()
        raw["significant_prompts"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "SHA-256 does not match"):
            repository_first.validate_record(raw, self.root, require_files=True)

    def test_campaign_raw_failure_chain_and_denominator_aggregation(self) -> None:
        self.publish(self.campaign())
        self.publish(self.raw_run())

        failure = self.template("failure_family.json")
        bad = copy.deepcopy(failure)
        bad["aggregate_actual_denominator"]["input_tokens"] += 1
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "not the member-run sum"):
            self.publish(bad)

        output = self.publish(failure)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o444)
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "overwrite"):
            self.publish(failure)
        report = repository_first.validate_repository(self.root)
        self.assertEqual(report["status"], "VALID")
        self.assertEqual(report["records_validated"], 3)

    def test_reviewed_export_is_hash_bound_read_only_and_no_clobber(self) -> None:
        request = self.export_request()
        manifest_path = repository_first.build_export(self.root, request)
        self.assertEqual(stat.S_IMODE(manifest_path.stat().st_mode), 0o444)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertTrue(manifest["no_outbound_action"])
        self.assertFalse(manifest["automatic_claim_promotion"])
        self.assertTrue(manifest["exclusions"]["raw_archives"])
        repository_first._validate_export_manifest(manifest, self.root, True)
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "overwrite"):
            repository_first.build_export(self.root, request)

    def test_independent_pass_rejects_author_under_another_role_or_class(self) -> None:
        for author_kind in ("CLAIM_GENERATOR", "FORMALIZER"):
            for assessor_class in ("HUMAN", "CODEX_AGENT"):
                with self.subTest(author_kind=author_kind, assessor_class=assessor_class):
                    campaign = self.campaign()
                    verifier = campaign["roles"][1]
                    author = campaign["roles"][2]
                    author["role_kind"] = author_kind
                    verifier["actor_id"] = author["actor_id"].upper()
                    verifier["actor_class"] = assessor_class
                    assessment = self.template("claim_assessment.json")
                    axis = assessment["axes"]["independent_verification"]
                    records = [(campaign, self.output_for(campaign)), (assessment, self.output_for(assessment))]
                    # A multi-role campaign and an honest NOT_RUN remain usable.
                    repository_first.validate_cross_records(records)
                    axis["status"] = "PASS"
                    axis["evidence_paths"] = ["problems/active/replace-problem-id/attempts/replace-run.md"]
                    with self.assertRaisesRegex(repository_first.RepositoryFirstError, "author actor"):
                        repository_first.validate_cross_records(records)

    def test_independent_pass_requires_separate_assessors_and_real_evidence(self) -> None:
        self.publish(self.campaign())
        assessment = self.template("claim_assessment.json")
        axis = assessment["axes"]["independent_verification"]
        axis["status"] = "PASS"
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "verification evidence"):
            self.publish(assessment)
        axis["evidence_paths"] = ["problems/active/replace-problem-id/attempts/missing.md"]
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "does not exist"):
            self.publish(assessment)
        axis["evidence_paths"] = ["problems/active/replace-problem-id/attempts/replace-run.md"]
        axis["assessor_role_ids"].append("research-operator")
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "author actor"):
            self.publish(assessment)
        axis["assessor_role_ids"].remove("research-operator")
        self.publish(assessment)
        self.assertEqual(repository_first.validate_repository(self.root)["status"], "VALID")

    def test_every_reviewed_file_rejects_later_drift_without_publishing(self) -> None:
        request = self.export_request()
        for entry in request["included_files"]:
            with self.subTest(path=entry["path"]):
                path = self.root / entry["path"]
                before = path.read_bytes()
                path.write_bytes(before + b"changed after review\n")
                with self.assertRaisesRegex(repository_first.RepositoryFirstError, "fresh review"):
                    repository_first.build_export(self.root, request)
                self.assertFalse((self.root / "research/repository_first/exports").exists())
                path.write_bytes(before)
        request["included_files"][0]["bytes"] += 1
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "byte count"):
            repository_first.build_export(self.root, request)

    def test_reprepare_updates_bindings_but_drops_prior_approval(self) -> None:
        reviewed = self.export_request()
        original = copy.deepcopy(reviewed)
        self.write_text("paper/main.tex", "new manuscript\n")
        draft = repository_first.prepare_export(self.root, reviewed)
        self.assertEqual(reviewed, original)
        self.assertEqual(draft["review"]["status"], "PENDING")
        self.assertIsNone(draft["review"]["reviewed_at_utc"])
        self.assertEqual(draft["review"]["reviewer_role_ids"], [])
        self.assertEqual(draft["included_files"][0]["sha256"], self.digest("paper/main.tex"))
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "must already be reviewed"):
            repository_first.build_export(self.root, draft)
        draft["review"] = reviewed["review"]
        repository_first.build_export(self.root, draft)

    def test_legacy_unbound_export_needs_preparation_and_new_review(self) -> None:
        legacy = self.export_request()
        legacy["schema_version"] = 1
        for entry in legacy["included_files"]:
            del entry["sha256"], entry["bytes"]
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "prepare-export"):
            repository_first.build_export(self.root, legacy)
        draft = repository_first.prepare_export(self.root, legacy)
        self.assertEqual(draft["schema_version"], 2)
        self.assertEqual(draft["review"]["status"], "PENDING")
        legacy["included_files"][0]["path"] = "../escape.tex"
        with self.assertRaises(repository_first.RepositoryFirstError):
            repository_first.prepare_export(self.root, legacy)

    def test_passive_observation_is_local_and_derived(self) -> None:
        self.publish(self.campaign())
        self.publish(self.raw_run())
        self.publish(self.template("failure_family.json"))
        path = repository_first.build_observation(
            self.root,
            "replace-observation-id",
            "2026-01-02T00:00:00Z",
            "2026-01-01",
            "2026-01-02",
        )
        observation = json.loads(path.read_text(encoding="utf-8"))
        boundaries = observation["collection_boundaries"]
        self.assertTrue(boundaries["lab_local_only"])
        self.assertFalse(boundaries["telemetry"])
        self.assertFalse(boundaries["background_process"])
        self.assertFalse(boundaries["fleet_scan"])
        self.assertEqual(observation["metrics"]["raw_run_manifest"], 1)
        self.assertEqual(observation["metrics"]["failure_family"], 1)
        self.assertEqual(observation["denominator_unknown_counts"]["model"], 1)
        repository_first._validate_observation(observation, self.root, True)

    def test_missing_raw_archive_ignore_is_fail_closed_only_when_enabled(self) -> None:
        self.write_text(".gitignore", "*.pyc\n")
        with self.assertRaisesRegex(repository_first.RepositoryFirstError, "must remain ignored"):
            repository_first.validate_repository(self.root)

    def test_helper_has_no_process_or_network_client_imports(self) -> None:
        source = (LAB_TEMPLATE_ROOT / "scripts" / "repository_first.py").read_text(
            encoding="utf-8"
        )
        for forbidden in (
            "import subprocess",
            "import socket",
            "import urllib",
            "import http.client",
            "import requests",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
