from __future__ import annotations

import contextlib
import copy
import ast
import hashlib
import importlib.util
import io
import json
import os
import re
import stat
import struct
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable


LAB_TEMPLATE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = LAB_TEMPLATE_ROOT / "scripts/research_release.py"
REQUEST_SCHEMA = LAB_TEMPLATE_ROOT / "schemas/research_release_request.schema.json"
PACKAGE_SCHEMA = LAB_TEMPLATE_ROOT / "schemas/research_release_package.schema.json"
REPOSITORY_SCRIPT = LAB_TEMPLATE_ROOT / "scripts/repository_first.py"

COMPONENTS = (
    "MANUSCRIPT",
    "CLAIMS",
    "VERIFICATION",
    "SOURCES",
    "REPRODUCIBILITY",
    "CODE",
    "COMPUTATIONS",
    "FORMALIZATION",
    "CONTRIBUTIONS",
    "REVISIONS",
)

ROLE_COMPONENT = {
    "MANUSCRIPT_SOURCE": "MANUSCRIPT",
    "COMPILED_MANUSCRIPT": "MANUSCRIPT",
    "CLAIM_STATEMENT": "CLAIMS",
    "CLAIM_MAP": "CLAIMS",
    "CHECKPOINT": "CLAIMS",
    "VERIFICATION_REPORT": "VERIFICATION",
    "SOURCE_RECORD": "SOURCES",
    "BIBLIOGRAPHY": "SOURCES",
    "REPRODUCIBILITY_GUIDE": "REPRODUCIBILITY",
    "ENVIRONMENT_LOCK": "REPRODUCIBILITY",
    "SOURCE_CODE": "CODE",
    "COMPUTATION_INPUT": "COMPUTATIONS",
    "COMPUTATION_OUTPUT": "COMPUTATIONS",
    "FORMALIZATION_SOURCE": "FORMALIZATION",
    "FORMALIZATION_ARTIFACT": "FORMALIZATION",
    "CONTRIBUTION_RECORD": "CONTRIBUTIONS",
    "REVISION_HISTORY": "REVISIONS",
}


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            separators=(",", ": "),
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json_strict(path: Path) -> Any:
    duplicates: list[str] = []

    def strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            if key in value:
                duplicates.append(key)
            value[key] = child
        return value

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=strict_pairs)
    if duplicates:
        raise AssertionError(f"duplicate JSON keys in {path}: {duplicates}")
    return value


def load_helper():
    spec = importlib.util.spec_from_file_location("research_release_under_test", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_repository_helper():
    spec = importlib.util.spec_from_file_location(
        "repository_first_for_release_pipeline_test", REPOSITORY_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {REPOSITORY_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_all_object_schemas_closed(test: unittest.TestCase, schema: object) -> None:
    open_objects: list[str] = []

    def inspect(value: object, location: str = "$") -> None:
        if isinstance(value, dict):
            if (
                value.get("type") == "object"
                and value.get("additionalProperties") is not False
            ):
                open_objects.append(location)
            for key, child in value.items():
                inspect(child, f"{location}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                inspect(child, f"{location}[{index}]")

    inspect(schema)
    test.assertEqual(open_objects, [])


def assert_matches_schema(
    test: unittest.TestCase,
    instance: object,
    schema: dict[str, Any],
    *,
    root_schema: dict[str, Any] | None = None,
    location: str = "$",
) -> None:
    root_schema = root_schema or schema
    if "$ref" in schema:
        reference = schema["$ref"]
        test.assertTrue(reference.startswith("#/"), reference)
        resolved: object = root_schema
        for token in reference[2:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            test.assertIsInstance(resolved, dict)
            resolved = resolved[token]
        test.assertIsInstance(resolved, dict)
        assert_matches_schema(
            test,
            instance,
            resolved,
            root_schema=root_schema,
            location=location,
        )
    if "oneOf" in schema:
        matches = 0
        for candidate in schema["oneOf"]:
            try:
                assert_matches_schema(
                    test,
                    instance,
                    candidate,
                    root_schema=root_schema,
                    location=location,
                )
            except AssertionError:
                continue
            matches += 1
        test.assertEqual(matches, 1, f"{location} matched {matches} oneOf branches")
    if "const" in schema:
        test.assertEqual(instance, schema["const"], location)
    if "enum" in schema:
        test.assertIn(instance, schema["enum"], location)

    expected_type = schema.get("type")
    if expected_type == "object":
        test.assertIsInstance(instance, dict, location)
        required = set(schema.get("required", []))
        test.assertTrue(required.issubset(instance), f"{location} missing {required - set(instance)}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            test.assertTrue(
                set(instance).issubset(properties),
                f"{location} has extra keys {set(instance) - set(properties)}",
            )
        for key, value in instance.items():
            if key in properties:
                assert_matches_schema(
                    test,
                    value,
                    properties[key],
                    root_schema=root_schema,
                    location=f"{location}.{key}",
                )
    elif expected_type == "array":
        test.assertIsInstance(instance, list, location)
        if "minItems" in schema:
            test.assertGreaterEqual(len(instance), schema["minItems"], location)
        if "maxItems" in schema:
            test.assertLessEqual(len(instance), schema["maxItems"], location)
        if schema.get("uniqueItems"):
            encodings = [canonical_json_bytes(value) for value in instance]
            test.assertEqual(len(encodings), len(set(encodings)), location)
        if "items" in schema:
            for index, value in enumerate(instance):
                assert_matches_schema(
                    test,
                    value,
                    schema["items"],
                    root_schema=root_schema,
                    location=f"{location}[{index}]",
                )
    elif expected_type == "string":
        test.assertIsInstance(instance, str, location)
        if "minLength" in schema:
            test.assertGreaterEqual(len(instance), schema["minLength"], location)
        if "maxLength" in schema:
            test.assertLessEqual(len(instance), schema["maxLength"], location)
        if "pattern" in schema:
            test.assertIsNotNone(re.search(schema["pattern"], instance), location)
    elif expected_type == "integer":
        test.assertIsInstance(instance, int, location)
        test.assertNotIsInstance(instance, bool, location)
        if "minimum" in schema:
            test.assertGreaterEqual(instance, schema["minimum"], location)
        if "maximum" in schema:
            test.assertLessEqual(instance, schema["maximum"], location)
    elif expected_type == "boolean":
        test.assertIsInstance(instance, bool, location)
    elif expected_type == "null":
        test.assertIsNone(instance, location)


class ResearchReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.release = load_helper()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="research-release-test-")
        self.root = Path(self.temporary.name)
        self.original_root = self.release.ROOT
        self.release.ROOT = self.root
        self.initialize_profile(enabled=True)

    def initialize_profile(self, *, enabled: bool) -> None:
        if not enabled:
            self.write_json("LAB_PROFILE.json", {"repository_first": {"enabled": False}})
            return
        self.write_json(
            "LAB_PROFILE.json",
            {
                "repository_first": {
                    "enabled": True,
                    "canonical_repository_visibility": "PRIVATE",
                    "raw_material_policy": "LOCAL_UNTRACKED",
                    "export_policy": "REVIEWED_ONLY",
                    "process_steward": "human-owner",
                },
                "lab": {
                    "owners": ["Human Owner"],
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

    def tearDown(self) -> None:
        self.release.ROOT = self.original_root
        self.temporary.cleanup()

    def write_bytes(self, relative: str, data: bytes) -> Path:
        path = self.root.joinpath(*Path(relative).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def write_text(self, relative: str, text: str) -> Path:
        return self.write_bytes(relative, text.encode("utf-8"))

    def write_json(self, relative: str, value: object) -> Path:
        return self.write_bytes(relative, canonical_json_bytes(value))

    def digest(self, relative: str) -> str:
        return sha256_bytes(self.root.joinpath(*Path(relative).parts).read_bytes())

    def remap_package_path(
        self,
        request: dict[str, object],
        mapping_index: int,
        package_path: str,
    ) -> None:
        mappings = request["file_mappings"]
        self.assertIsInstance(mappings, list)
        mapping = mappings[mapping_index]
        self.assertIsInstance(mapping, dict)
        old_path = mapping["package_path"]
        component = ROLE_COMPONENT[mapping["role"]]
        mapping["package_path"] = package_path

        declarations = request["component_declarations"]
        self.assertIsInstance(declarations, list)
        declaration = next(
            item
            for item in declarations
            if isinstance(item, dict) and item.get("component") == component
        )
        declaration["paths"] = sorted(
            package_path if path == old_path else path
            for path in declaration["paths"]
        )

    def rewrite_export_manifest(
        self,
        request: dict[str, object],
        manifest: dict[str, object],
    ) -> None:
        body = dict(manifest)
        body.pop("manifest_payload_sha256", None)
        manifest["manifest_payload_sha256"] = sha256_bytes(
            canonical_json_bytes(body)
        )
        relative = request["source_export_manifest_path"]
        self.assertIsInstance(relative, str)
        path = self.root.joinpath(*Path(relative).parts)
        path.chmod(0o644)
        self.write_json(relative, manifest).chmod(0o444)
        request["source_export_manifest_sha256"] = self.digest(relative)

    def invoke(self, argv: list[str]) -> tuple[int, object, object]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = self.release.run(argv)

        def decode(value: str) -> object:
            stripped = value.strip()
            if not stripped:
                return ""
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return stripped

        return code, decode(stdout.getvalue()), decode(stderr.getvalue())

    def invoke_ok(self, argv: list[str]) -> object:
        code, output, error = self.invoke(argv)
        self.assertEqual(code, 0, error)
        return output

    def invoke_error(self, argv: list[str]) -> str:
        code, output, error = self.invoke(argv)
        self.assertNotEqual(code, 0, output)
        if isinstance(error, dict):
            return str(error.get("error", error))
        return str(error)

    def reviewed_export(
        self,
        files: dict[str, bytes],
        *,
        export_id: str = "reviewed-export",
        claim_path: str = "problems/active/p1/problem.md",
        checkpoint_path: str = "research/checkpoints/cp1.md",
    ) -> tuple[str, dict[str, object]]:
        files = dict(files)
        for relative, data in files.items():
            self.write_bytes(relative, data)
        if claim_path not in files:
            self.write_text(claim_path, "Claim C1.\n")
            files[claim_path] = b"Claim C1.\n"
        if checkpoint_path not in files:
            self.write_text(checkpoint_path, "# Durable checkpoint CP1\n")
            files[checkpoint_path] = b"# Durable checkpoint CP1\n"
        included_files = [
            {
                "path": path,
                "sha256": sha256_bytes(data),
                "bytes": len(data),
                "purpose": f"Reviewed release source: {path}",
            }
            for path, data in sorted(files.items())
        ]
        package_root = f"research/repository_first/exports/{export_id}"
        manifest: dict[str, object] = {
            "schema_version": 1,
            "record_type": "export_package_manifest",
            "export_id": export_id,
            "created_at_utc": "2026-08-23T12:00:00Z",
            "package_root": package_root,
            "purpose": "Exact human-reviewed inputs for a local research release.",
            "claim_ids": ["claim-c1"],
            "claim_bindings": [
                {
                    "claim_id": "claim-c1",
                    "claim_statement_version": "c1-v1",
                    "claim_statement_path": claim_path,
                    "claim_statement_sha256": self.digest(claim_path),
                }
            ],
            "source_checkpoint_paths": [checkpoint_path],
            "review": {
                "status": "REVIEWED",
                "reviewed_at_utc": "2026-08-23T11:59:59Z",
                "reviewer_role_ids": ["human-owner"],
                "scope_note": "Every selected file and exclusion was reviewed by a human.",
            },
            "included_files": included_files,
            "exclusions": {
                "raw_archives": True,
                "credentials": True,
                "hidden_prompts": True,
                "chain_of_thought": True,
                "outbound_actions": True,
            },
            "no_outbound_action": True,
            "automatic_claim_promotion": False,
        }
        manifest["manifest_payload_sha256"] = sha256_bytes(
            canonical_json_bytes(manifest)
        )
        relative = f"{package_root}/manifest.json"
        output = self.write_json(relative, manifest)
        output.chmod(0o444)
        return relative, manifest

    def release_request(
        self,
        *,
        audience: str = "COAUTHOR",
        release_id: str = "article-release",
        release_version: str = "v1",
        full: bool = False,
    ) -> dict[str, object]:
        files: dict[str, bytes] = {
            "manuscript/paper.tex": b"\\documentclass{article}\n\\begin{document}Claim C1.\\end{document}\n",
            "problems/active/p1/problem.md": b"Claim C1.\n",
            "research/checkpoints/cp1.md": b"# Durable checkpoint CP1\n",
        }
        mappings: list[dict[str, str]] = [
            {
                "source_path": "manuscript/paper.tex",
                "package_path": "manuscript/paper.tex",
                "role": "MANUSCRIPT_SOURCE",
                "purpose": "Human-readable manuscript source.",
            },
            {
                "source_path": "problems/active/p1/problem.md",
                "package_path": "claims/claim-c1.md",
                "role": "CLAIM_STATEMENT",
                "purpose": "Exact reviewed statement of claim C1.",
            },
            {
                "source_path": "research/checkpoints/cp1.md",
                "package_path": "claims/checkpoint-cp1.md",
                "role": "CHECKPOINT",
                "purpose": "Exact reviewed checkpoint supporting this projection.",
            },
        ]
        if audience == "PUBLIC":
            files["manuscript/paper.pdf"] = b"%PDF-1.4\n% deterministic test fixture\n"
            mappings.append(
                {
                    "source_path": "manuscript/paper.pdf",
                    "package_path": "manuscript/paper.pdf",
                    "role": "COMPILED_MANUSCRIPT",
                    "purpose": "Human-reviewed compiled manuscript bytes.",
                }
            )
        if full:
            full_members = (
                (
                    "problems/active/p1/verification.md",
                    b"# Independent verification report\n",
                    "verification/report.md",
                    "VERIFICATION_REPORT",
                    "Exact reviewed verification report.",
                ),
                (
                    "sources/source-record.json",
                    b'{"source":"S1","anchor":"Theorem 1"}\n',
                    "sources/source-record.json",
                    "SOURCE_RECORD",
                    "Exact reviewed source audit record.",
                ),
                (
                    "reproducibility/README.md",
                    b"# Replay instructions\nNo command is run by the release builder.\n",
                    "reproducibility/README.md",
                    "REPRODUCIBILITY_GUIDE",
                    "Exact reviewed reproducibility instructions.",
                ),
                (
                    "code/example.py",
                    b"print('fixture only')\n",
                    "code/example.py",
                    "SOURCE_CODE",
                    "Exact reviewed source code; it is not executed.",
                ),
                (
                    "research/computations/output.txt",
                    b"deterministic fixture output\n",
                    "computations/output.txt",
                    "COMPUTATION_OUTPUT",
                    "Exact reviewed computation output.",
                ),
                (
                    "research/formalization/Main.lean",
                    b"theorem fixture : True := by trivial\n",
                    "formalization/Main.lean",
                    "FORMALIZATION_SOURCE",
                    "Exact reviewed formalization source; it is not compiled.",
                ),
                (
                    "collaboration/contributions.md",
                    b"# Contribution record\nHuman-reviewed provenance only.\n",
                    "provenance/contributions.md",
                    "CONTRIBUTION_RECORD",
                    "Exact reviewed contribution record.",
                ),
                (
                    "manuscript/revisions.md",
                    b"# Revision history\nVersion v1.\n",
                    "provenance/revisions.md",
                    "REVISION_HISTORY",
                    "Exact reviewed revision history.",
                ),
            )
            for source_path, data, package_path, role, purpose in full_members:
                files[source_path] = data
                mappings.append(
                    {
                        "source_path": source_path,
                        "package_path": package_path,
                        "role": role,
                        "purpose": purpose,
                    }
                )
        export_path, _manifest = self.reviewed_export(
            files,
            export_id=f"reviewed-{release_id}",
        )
        component_paths = {
            component: sorted(
                mapping["package_path"]
                for mapping in mappings
                if ROLE_COMPONENT[mapping["role"]] == component
            )
            for component in COMPONENTS
        }
        declarations: list[dict[str, object]] = []
        for component in COMPONENTS:
            paths = component_paths.get(component, [])
            declarations.append(
                {
                    "component": component,
                    "status": "INCLUDED" if paths else "NOT_APPLICABLE",
                    "paths": paths,
                    "rationale": (
                        None
                        if paths
                        else f"No {component.lower()} artifact is applicable to this bounded test release."
                    ),
                }
            )
        return {
            "schema_version": 1,
            "record_type": "research_release_request",
            "release_id": release_id,
            "release_version": release_version,
            "title": "Research Artifact Release Test",
            "purpose": "Materialize the exact reviewed bytes as a local test package.",
            "audience": audience,
            "source_export_manifest_path": export_path,
            "source_export_manifest_sha256": self.digest(export_path),
            "disclosure_review": {
                "status": "REVIEWED",
                "reviewed_at_utc": "2026-08-23T12:00:01Z",
                "reviewer_role_ids": ["human-owner"],
                "scope_note": "The exact mappings and audience projection were reviewed by a human.",
            },
            "file_mappings": sorted(mappings, key=lambda item: item["package_path"]),
            "component_declarations": declarations,
            "no_outbound_action": True,
            "automatic_claim_promotion": False,
        }

    def build_release(
        self,
        request: dict[str, object] | None = None,
        *,
        input_name: str = "tmp/research-release-request.json",
    ) -> tuple[Path, object]:
        request = request or self.release_request()
        self.write_json(input_name, request)
        output = self.invoke_ok(["build", "--input", input_name])
        expected_relative = (
            "research/repository_first/releases/"
            f"{request['release_id']}/{request['release_version']}.zip"
        )
        archive = self.root.joinpath(*Path(expected_relative).parts)
        self.assertTrue(archive.is_file())
        self.assertEqual(
            output,
            {
                "archive_path": expected_relative,
                "archive_sha256": sha256_bytes(archive.read_bytes()),
            },
        )
        return archive, output

    def validate_archive(self, archive: Path) -> dict[str, object]:
        relative = archive.relative_to(self.root).as_posix()
        output = self.invoke_ok(["validate", "--archive", relative, "--json"])
        self.assertIsInstance(output, dict)
        archives = output.get("archives")
        self.assertIsInstance(archives, list)
        self.assertEqual(len(archives), 1)
        self.assertEqual(archives[0]["archive_path"], relative)
        self.assertEqual(
            archives[0]["archive_sha256"],
            sha256_bytes(archive.read_bytes()),
        )
        return output

    def replace_archive_from_entries(
        self,
        archive: Path,
        entries: list[tuple[zipfile.ZipInfo, bytes]],
    ) -> None:
        temporary = self.root / "tmp/tampered.zip"
        temporary.parent.mkdir(parents=True, exist_ok=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(temporary, "w") as output:
                for info, data in entries:
                    output.writestr(info, data)
        archive.chmod(0o644)
        archive.write_bytes(temporary.read_bytes())
        archive.chmod(0o444)
        temporary.unlink()

    def rewrite_zip(
        self,
        source: Path,
        transform: Callable[[list[tuple[zipfile.ZipInfo, bytes]]], list[tuple[zipfile.ZipInfo, bytes]]],
        *,
        target_name: str = "tampered.zip",
    ) -> Path:
        with zipfile.ZipFile(source, "r") as archive:
            entries = [(copy.copy(info), archive.read(info)) for info in archive.infolist()]
        target = source.with_name(target_name)
        transformed = transform(entries)
        with zipfile.ZipFile(target, "w") as archive:
            for info, data in transformed:
                archive.writestr(info, data)
        return target

    def zip_entries(self, path: Path) -> list[tuple[zipfile.ZipInfo, bytes]]:
        with zipfile.ZipFile(path, "r") as archive:
            return [(info, archive.read(info)) for info in archive.infolist()]

    def test_successful_package_has_exact_members_navigation_and_closed_manifest(self) -> None:
        request = self.release_request(audience="PUBLIC", full=True)
        canonical_preimages = {
            path: (
                (self.root / path).read_bytes(),
                stat.S_IMODE((self.root / path).stat().st_mode),
            )
            for path in [
                request["source_export_manifest_path"],
                *(item["source_path"] for item in request["file_mappings"]),
            ]
        }
        archive, _ = self.build_release(request)
        for path, (data, mode) in canonical_preimages.items():
            self.assertEqual((self.root / path).read_bytes(), data, path)
            self.assertEqual(stat.S_IMODE((self.root / path).stat().st_mode), mode, path)
        self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o444)
        entries = self.zip_entries(archive)
        names = [info.filename for info, _data in entries]
        requested_names = [item["package_path"] for item in request["file_mappings"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(not name.endswith("/") for name in names))
        roots = {PurePosixPath(name).parts[0] for name in names}
        self.assertEqual(len(roots), 1)
        archive_root = next(iter(roots))
        self.assertEqual(
            archive_root,
            f"research-artifact-release-{request['release_id']}-{request['release_version']}",
        )
        self.assertEqual(
            names,
            sorted(
                [
                    f"{archive_root}/README.md",
                    f"{archive_root}/manifest.json",
                    *(f"{archive_root}/{name}" for name in requested_names),
                ]
            ),
        )
        for info, _data in entries:
            self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
            self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
            self.assertEqual(info.create_system, 3)
            archived_mode = info.external_attr >> 16
            self.assertTrue(stat.S_ISREG(archived_mode), info.filename)
            self.assertEqual(stat.S_IMODE(archived_mode), 0o444)

        by_name = {info.filename: data for info, data in entries}
        for mapping in request["file_mappings"]:
            packaged = by_name[f"{archive_root}/{mapping['package_path']}"]
            source = (self.root / mapping["source_path"]).read_bytes()
            self.assertEqual(packaged, source, mapping["package_path"])
        readme = by_name[f"{archive_root}/README.md"].decode("utf-8")
        self.assertIn(request["title"], readme)
        self.assertIn(request["release_id"], readme)
        self.assertIn(request["audience"], readme)
        self.assertRegex(
            readme.lower(),
            r"not (?:access control|authentication|authorization)",
        )
        self.assertRegex(
            readme.lower(),
            r"does not (?:prove|establish|certify)",
        )

        manifest = json.loads(
            by_name[f"{archive_root}/manifest.json"].decode("utf-8")
        )
        assert_matches_schema(self, manifest, load_json_strict(PACKAGE_SCHEMA))
        self.assertEqual(manifest["record_type"], "research_release_package")
        self.assertEqual(manifest["release_id"], request["release_id"])
        self.assertEqual(manifest["release_version"], request["release_version"])
        self.assertEqual(manifest["audience"], "PUBLIC")
        self.assertTrue(manifest["no_outbound_action"])
        self.assertFalse(manifest["automatic_claim_promotion"])
        self.assertEqual(
            manifest["archive_contract"]["root_prefix"],
            f"{archive_root}/",
        )
        self.assertEqual(manifest["archive_contract"]["member_order"], names)
        self.assertEqual(
            manifest["archive_contract"]["readme_sha256"],
            sha256_bytes(by_name[f"{archive_root}/README.md"]),
        )
        self.assertEqual(
            manifest["archive_contract"]["readme_bytes"],
            len(by_name[f"{archive_root}/README.md"]),
        )
        self.assertEqual(manifest["claim_ids"], ["claim-c1"])
        self.assertEqual(
            manifest["source_checkpoint_paths"],
            ["research/checkpoints/cp1.md"],
        )
        self.assertEqual(
            {item["package_path"]: item["role"] for item in manifest["files"]},
            {item["package_path"]: item["role"] for item in request["file_mappings"]},
        )
        for item in manifest["files"]:
            data = by_name[f"{archive_root}/{item['package_path']}"]
            self.assertEqual(item["package_sha256"], sha256_bytes(data))
            self.assertEqual(item["package_bytes"], len(data))
            self.assertEqual(item["source_sha256"], item["package_sha256"])
            self.assertEqual(item["source_bytes"], item["package_bytes"])
        self.assertEqual(
            {item["component"]: item["status"] for item in manifest["components"]},
            {
                item["component"]: item["status"]
                for item in request["component_declarations"]
            },
        )
        self.assertEqual(
            manifest["source_export"]["path"],
            request["source_export_manifest_path"],
        )
        self.assertEqual(
            manifest["source_export"]["sha256"],
            request["source_export_manifest_sha256"],
        )
        report = self.validate_archive(archive)
        self.assertEqual(report["status"], "VALID")
        self.assertEqual(report["releases_validated"], 1)
        self.assertEqual(report["files_validated"], len(requested_names))
        self.assertEqual(
            report["bytes_validated"],
            sum(len((self.root / item["source_path"]).read_bytes()) for item in request["file_mappings"]),
        )

    def test_identical_inputs_are_byte_deterministic_across_independent_roots(self) -> None:
        first_request = self.release_request(audience="PUBLIC", full=True)
        first_archive, _ = self.build_release(first_request)
        first_bytes = first_archive.read_bytes()

        first_root = self.root
        with tempfile.TemporaryDirectory(prefix="research-release-independent-") as temp:
            self.root = Path(temp)
            self.release.ROOT = self.root
            self.initialize_profile(enabled=True)
            second_request = self.release_request(audience="PUBLIC", full=True)
            second_archive, _ = self.build_release(second_request)
            self.assertEqual(second_request, first_request)
            self.assertEqual(second_archive.read_bytes(), first_bytes)
        self.root = first_root
        self.release.ROOT = first_root

    def test_cli_success_reports_canonical_path_and_archive_digest(self) -> None:
        request = self.release_request(release_id="cli-digest-report")
        archive, build_report = self.build_release(
            request,
            input_name="tmp/cli-digest-report.json",
        )
        relative = archive.relative_to(self.root).as_posix()
        digest = sha256_bytes(archive.read_bytes())
        self.assertEqual(
            build_report,
            {
                "archive_path": relative,
                "archive_sha256": digest,
            },
        )

        report = self.validate_archive(archive)
        self.assertEqual(report["status"], "VALID")
        self.assertEqual(
            report["archives"],
            [
                {
                    "archive_path": relative,
                    "archive_sha256": digest,
                    "files_validated": 3,
                    "bytes_validated": sum(
                        len((self.root / item["source_path"]).read_bytes())
                        for item in request["file_mappings"]
                    ),
                }
            ],
        )

        plain = self.invoke_ok(["validate", "--archive", relative])
        self.assertIsInstance(plain, str)
        self.assertIn(relative, plain)
        self.assertIn(digest, plain)

    def test_schema_version_must_be_exact_integer_at_every_trust_boundary(self) -> None:
        invalid_versions = (("boolean", True), ("float", 1.0))
        for index, (kind, invalid) in enumerate(invalid_versions):
            with self.subTest(boundary="request", kind=kind):
                release_id = f"request-version-{index}"
                request = self.release_request(release_id=release_id)
                request["schema_version"] = invalid
                input_path = f"tmp/request-version-{index}.json"
                self.write_json(input_path, request)
                error = self.invoke_error(["build", "--input", input_path])
                self.assertRegex(error, "(?i)schema|version|integer")
                self.assertFalse(
                    (
                        self.root
                        / f"research/repository_first/releases/{release_id}/v1.zip"
                    ).exists()
                )

            with self.subTest(boundary="reviewed export", kind=kind):
                release_id = f"export-version-{index}"
                request = self.release_request(release_id=release_id)
                manifest_path = self.root / request["source_export_manifest_path"]
                manifest = load_json_strict(manifest_path)
                manifest["schema_version"] = invalid
                self.rewrite_export_manifest(request, manifest)
                input_path = f"tmp/export-version-{index}.json"
                self.write_json(input_path, request)
                error = self.invoke_error(["build", "--input", input_path])
                self.assertRegex(error, "(?i)schema|version|integer|export")
                self.assertFalse(
                    (
                        self.root
                        / f"research/repository_first/releases/{release_id}/v1.zip"
                    ).exists()
                )

            with self.subTest(boundary="package manifest", kind=kind):
                release_id = f"package-version-{index}"
                request = self.release_request(release_id=release_id)
                archive, _ = self.build_release(
                    request,
                    input_name=f"tmp/package-version-{index}.json",
                )

                def invalid_package_version(entries):
                    result = [(copy.copy(info), data) for info, data in entries]
                    manifest_index = next(
                        item_index
                        for item_index, (info, _data) in enumerate(result)
                        if info.filename.endswith("/manifest.json")
                    )
                    info, data = result[manifest_index]
                    manifest = json.loads(data.decode("utf-8"))
                    manifest["schema_version"] = invalid
                    body = dict(manifest)
                    del body["manifest_payload_sha256"]
                    manifest["manifest_payload_sha256"] = sha256_bytes(
                        canonical_json_bytes(body)
                    )
                    result[manifest_index] = (info, canonical_json_bytes(manifest))
                    return result

                self.replace_archive_from_entries(
                    archive,
                    invalid_package_version(self.zip_entries(archive)),
                )
                error = self.invoke_error(
                    [
                        "validate",
                        "--archive",
                        archive.relative_to(self.root).as_posix(),
                        "--json",
                    ]
                )
                self.assertRegex(error, "(?i)schema|version|integer|manifest")

    def test_maximum_identifiers_and_package_path_round_trip(self) -> None:
        release_id = "r" + "a" * 94 + "z"
        release_version = "v" + "1" * 95
        package_path = "a" * 255 + "/" + "b" * 254 + "/c"
        self.assertEqual(len(release_id), 96)
        self.assertEqual(len(release_version), 96)
        self.assertEqual(len(package_path), self.release.MAX_PATH)
        self.assertTrue(
            all(
                len(component.encode("utf-8"))
                <= self.release.MAX_PORTABLE_COMPONENT_BYTES
                for component in PurePosixPath(package_path).parts
            )
        )

        request = self.release_request(release_id="max-bound-fixture")
        request["release_id"] = release_id
        request["release_version"] = release_version
        self.remap_package_path(request, 0, package_path)
        archive, _ = self.build_release(
            request,
            input_name="tmp/max-bound-request.json",
        )
        expected_root = (
            f"research-artifact-release-{release_id}-{release_version}"
        )
        names = [info.filename for info, _data in self.zip_entries(archive)]
        self.assertIn(f"{expected_root}/{package_path}", names)
        manifest = json.loads(
            next(
                data
                for info, data in self.zip_entries(archive)
                if info.filename == f"{expected_root}/manifest.json"
            ).decode("utf-8")
        )
        self.assertEqual(manifest["release_id"], release_id)
        self.assertEqual(manifest["release_version"], release_version)
        self.assertIn(
            f"{expected_root}/{package_path}",
            manifest["archive_contract"]["member_order"],
        )
        self.assertEqual(self.validate_archive(archive)["status"], "VALID")

    def test_release_root_identifiers_are_canonical_and_unambiguous(self) -> None:
        invalid_pairs = (
            ("uppercase release_id", "Article", "v1"),
            ("uppercase release_version", "article", "V1"),
            ("release_id trailing dot", "article.", "v1"),
            ("release_version trailing dot", "article", "v1."),
            ("hyphenated ambiguous release_version", "article", "v1-beta"),
        )
        for index, (name, release_id, release_version) in enumerate(invalid_pairs):
            with self.subTest(case=name):
                request = self.release_request(
                    release_id=f"invalid-root-fixture-{index}"
                )
                request["release_id"] = release_id
                request["release_version"] = release_version
                input_path = f"tmp/invalid-root-{index}.json"
                self.write_json(input_path, request)
                error = self.invoke_error(["build", "--input", input_path])
                self.assertRegex(
                    error,
                    "(?i)release.id|release.version|lowercase|canonical|hyphen|dot|identifier",
                )
        releases = self.root / "research/repository_first/releases"
        self.assertEqual(
            list(releases.rglob("*.zip")) if releases.exists() else [],
            [],
        )

    def test_first_party_templates_compose_through_real_export_builder(self) -> None:
        repository_first = load_repository_helper()
        self.write_text(
            "paper/main.tex",
            "\\documentclass{article}\n\\begin{document}Exact claim.\\end{document}\n",
        )
        self.write_text(
            "problems/active/replace-problem-id/problem.md",
            "Exact reviewed claim statement.\n",
        )
        self.write_text(
            "research/checkpoints/replace-checkpoint.md",
            "# Exact reviewed checkpoint\n",
        )
        export_request = load_json_strict(
            LAB_TEMPLATE_ROOT / "templates/repository_first/export_request.json"
        )
        export_request["claim_bindings"][0]["claim_statement_sha256"] = self.digest(
            "problems/active/replace-problem-id/problem.md"
        )
        export_request = repository_first.prepare_export(self.root, export_request)
        export_request["review"] = {
            "status": "REVIEWED", "reviewed_at_utc": "2026-01-01T07:00:00Z",
            "reviewer_role_ids": ["human-owner"], "scope_note": "Exact synthetic fixture reviewed.",
        }
        export_path = repository_first.build_export(self.root, export_request)
        release_request = load_json_strict(
            LAB_TEMPLATE_ROOT / "templates/repository_first/release_request.json"
        )
        release_request["source_export_manifest_sha256"] = sha256_bytes(
            export_path.read_bytes()
        )
        archive, _ = self.build_release(
            release_request,
            input_name="tmp/first-party-template-release.json",
        )
        report = self.validate_archive(archive)
        self.assertEqual(report["status"], "VALID")
        self.assertEqual(report["files_validated"], 3)

    def test_disabled_profile_is_dormant_and_fail_closed(self) -> None:
        request = self.release_request()
        self.initialize_profile(enabled=False)
        self.write_bytes(
            "research/repository_first/releases/not-inspected/v1.zip",
            b"deliberately not a ZIP",
        )
        report = self.invoke_ok(["validate", "--json"])
        self.assertEqual(report["status"], "DISABLED")
        self.assertEqual(report["releases_validated"], 0)
        self.assertEqual(report["archives"], [])
        self.write_json("tmp/research-release-request.json", request)
        error = self.invoke_error(
            ["build", "--input", "tmp/research-release-request.json"]
        )
        self.assertRegex(error, "(?i)dormant|disabled|enabled")

        self.write_json("LAB_PROFILE.json", {})
        absent = self.invoke_ok(["validate", "--json"])
        self.assertEqual(absent["status"], "DISABLED")
        self.assertEqual(absent["archives"], [])

        malformed_policies = (
            {
                "enabled": True,
                "canonical_repository_visibility": "PUBLIC",
                "raw_material_policy": "LOCAL_UNTRACKED",
                "export_policy": "REVIEWED_ONLY",
                "process_steward": "human-owner",
            },
            {
                "enabled": True,
                "canonical_repository_visibility": "PRIVATE",
                "raw_material_policy": "TRACKED",
                "export_policy": "REVIEWED_ONLY",
                "process_steward": "human-owner",
            },
            {
                "enabled": True,
                "canonical_repository_visibility": "PRIVATE",
                "raw_material_policy": "LOCAL_UNTRACKED",
                "export_policy": "UNREVIEWED",
                "process_steward": "human-owner",
            },
            {"enabled": True},
            {"enabled": False, "process_steward": "human-owner"},
        )
        for index, policy in enumerate(malformed_policies):
            with self.subTest(profile_policy=index):
                self.write_json(
                    "LAB_PROFILE.json",
                    {
                        "repository_first": policy,
                        "lab": {
                            "owners": ["Human Owner"],
                            "modules": [],
                            "collaboration": None,
                        },
                    },
                )
                error = self.invoke_error(["validate", "--json"])
                self.assertRegex(
                    error,
                    "(?i)private|untracked|reviewed|missing|disabled|policy",
                )

    def test_profile_export_and_gitignore_have_canonical_byte_bounds(self) -> None:
        profile_path = self.root / "LAB_PROFILE.json"
        canonical_profile = profile_path.read_bytes()
        oversized_profile = canonical_profile + b" " * (
            self.release.MAX_PROFILE_BYTES + 1 - len(canonical_profile)
        )
        self.assertEqual(
            len(oversized_profile),
            self.release.MAX_PROFILE_BYTES + 1,
        )
        profile_path.write_bytes(oversized_profile)
        self.assertRegex(
            self.invoke_error(["validate", "--json"]),
            "(?is)(?=.*(?:LAB_PROFILE|profile))(?=.*(?:bound|size|large|byte))",
        )
        profile_path.write_bytes(canonical_profile)

        request = self.release_request(release_id="oversized-gitignore")
        gitignore_path = self.root / ".gitignore"
        canonical_gitignore = gitignore_path.read_bytes()
        oversized_gitignore = canonical_gitignore + b"#" * (
            self.release.MAX_GITIGNORE_BYTES + 1 - len(canonical_gitignore)
        )
        self.assertEqual(
            len(oversized_gitignore),
            self.release.MAX_GITIGNORE_BYTES + 1,
        )
        gitignore_path.write_bytes(oversized_gitignore)
        self.write_json("tmp/oversized-gitignore.json", request)
        self.assertRegex(
            self.invoke_error(
                ["build", "--input", "tmp/oversized-gitignore.json"]
            ),
            "(?is)(?=.*gitignore)(?=.*(?:bound|size|large|byte))",
        )
        self.assertFalse(
            (
                self.root
                / "research/repository_first/releases/oversized-gitignore/v1.zip"
            ).exists()
        )
        gitignore_path.write_bytes(canonical_gitignore)

        request = self.release_request(release_id="oversized-export")
        manifest_path = self.root / request["source_export_manifest_path"]
        canonical_export = manifest_path.read_bytes()
        oversized_export = canonical_export + b" " * (
            self.release.MAX_EXPORT_MANIFEST_BYTES + 1 - len(canonical_export)
        )
        self.assertEqual(
            len(oversized_export),
            self.release.MAX_EXPORT_MANIFEST_BYTES + 1,
        )
        manifest_path.chmod(0o644)
        manifest_path.write_bytes(oversized_export)
        manifest_path.chmod(0o444)
        request["source_export_manifest_sha256"] = sha256_bytes(oversized_export)
        self.write_json("tmp/oversized-export.json", request)
        self.assertRegex(
            self.invoke_error(
                ["build", "--input", "tmp/oversized-export.json"]
            ),
            "(?is)(?=.*(?:export|manifest))(?=.*(?:bound|size|large|byte))",
        )
        self.assertFalse(
            (
                self.root
                / "research/repository_first/releases/oversized-export/v1.zip"
            ).exists()
        )

    def test_build_is_no_clobber_and_preserves_original_archive(self) -> None:
        request = self.release_request()
        archive, _ = self.build_release(request)
        original = archive.read_bytes()
        self.write_json("tmp/research-release-request.json", request)
        error = self.invoke_error(
            ["build", "--input", "tmp/research-release-request.json"]
        )
        self.assertRegex(error, "(?i)overwrite|exist|clobber")
        self.assertEqual(archive.read_bytes(), original)
        self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o444)

    def test_export_manifest_binding_and_internal_hash_drift_are_rejected(self) -> None:
        request = self.release_request()
        bad_binding = copy.deepcopy(request)
        bad_binding["source_export_manifest_sha256"] = "0" * 64
        self.write_json("tmp/bad-binding.json", bad_binding)
        self.assertRegex(
            self.invoke_error(["build", "--input", "tmp/bad-binding.json"]),
            "(?i)sha|digest|hash|match",
        )

        manifest_path = self.root / request["source_export_manifest_path"]
        manifest_path.chmod(0o644)
        self.write_json("tmp/mutable-export.json", request)
        self.assertRegex(
            self.invoke_error(["build", "--input", "tmp/mutable-export.json"]),
            "(?i)mode|0444|read.only|immutable|reviewed export",
        )
        manifest_path.chmod(0o444)

        manifest = load_json_strict(manifest_path)
        manifest["purpose"] = "Changed after human review."
        manifest_path.chmod(0o644)
        self.write_json(request["source_export_manifest_path"], manifest).chmod(0o444)
        drifted = copy.deepcopy(request)
        drifted["source_export_manifest_sha256"] = self.digest(
            request["source_export_manifest_path"]
        )
        self.write_json("tmp/bad-payload.json", drifted)
        self.assertRegex(
            self.invoke_error(["build", "--input", "tmp/bad-payload.json"]),
            "(?i)payload|digest|hash|match",
        )

    def test_source_byte_and_export_hash_drift_are_rejected(self) -> None:
        request = self.release_request()
        self.write_text("manuscript/paper.tex", "changed after review\n")
        self.write_json("tmp/stale-source.json", request)
        self.assertRegex(
            self.invoke_error(["build", "--input", "tmp/stale-source.json"]),
            "(?i)sha|digest|hash|bytes|drift|match",
        )
        self.assertFalse(
            (
                self.root
                / "research/repository_first/releases/article-release/v1.zip"
            ).exists()
        )

        request = self.release_request(release_id="bad-export-source")
        manifest_path = self.root / request["source_export_manifest_path"]
        manifest = load_json_strict(manifest_path)
        manuscript = next(
            item for item in manifest["included_files"] if item["path"] == "manuscript/paper.tex"
        )
        manuscript["sha256"] = "f" * 64
        body = dict(manifest)
        del body["manifest_payload_sha256"]
        manifest["manifest_payload_sha256"] = sha256_bytes(canonical_json_bytes(body))
        manifest_path.chmod(0o644)
        self.write_json(request["source_export_manifest_path"], manifest).chmod(0o444)
        request["source_export_manifest_sha256"] = self.digest(
            request["source_export_manifest_path"]
        )
        self.write_json("tmp/bad-source-hash.json", request)
        self.assertRegex(
            self.invoke_error(["build", "--input", "tmp/bad-source-hash.json"]),
            "(?i)sha|digest|hash|bytes|match",
        )

    def test_reviewed_file_set_must_map_one_to_one(self) -> None:
        base = self.release_request()
        cases: dict[str, dict[str, object]] = {}

        missing = self.release_request(
            release_id="missing-reviewed-file",
            full=True,
        )
        missing["file_mappings"] = [
            item
            for item in missing["file_mappings"]
            if item["role"] != "REVISION_HISTORY"
        ]
        revision_component = next(
            item
            for item in missing["component_declarations"]
            if item["component"] == "REVISIONS"
        )
        revision_component.update(
            {
                "status": "OMITTED_REVIEWED",
                "paths": [],
                "rationale": "The revision component was reviewed and omitted from the projection.",
            }
        )
        cases["missing reviewed file"] = missing

        duplicate_source = copy.deepcopy(base)
        duplicate_source["file_mappings"][1]["source_path"] = duplicate_source["file_mappings"][0]["source_path"]
        cases["duplicate source"] = duplicate_source

        extra = copy.deepcopy(base)
        self.write_text("notes/unreviewed.md", "not reviewed\n")
        extra["file_mappings"].append(
            {
                "source_path": "notes/unreviewed.md",
                "package_path": "supplement/unreviewed.md",
                "role": "SOURCE_RECORD",
                "purpose": "This must not widen the reviewed selection.",
            }
        )
        sources_component = next(
            item
            for item in extra["component_declarations"]
            if item["component"] == "SOURCES"
        )
        sources_component.update(
            {
                "status": "INCLUDED",
                "paths": ["supplement/unreviewed.md"],
                "rationale": None,
            }
        )
        cases["unreviewed extra"] = extra

        for index, (name, request) in enumerate(cases.items()):
            with self.subTest(case=name):
                path = f"tmp/file-set-{index}.json"
                self.write_json(path, request)
                error = self.invoke_error(["build", "--input", path])
                self.assertRegex(error, "(?i)exact|one-to-one|duplicate|review|file|map")

    def test_claim_checkpoint_and_public_manuscript_roles_are_required(self) -> None:
        base = self.release_request()
        claimless = copy.deepcopy(base)
        next(
            item for item in claimless["file_mappings"] if item["role"] == "CLAIM_STATEMENT"
        )["role"] = "CLAIM_MAP"
        checkpointless = copy.deepcopy(base)
        next(
            item for item in checkpointless["file_mappings"] if item["role"] == "CHECKPOINT"
        )["role"] = "REVISION_HISTORY"
        public_without_pdf = copy.deepcopy(base)
        public_without_pdf["audience"] = "PUBLIC"
        public_without_source = self.release_request(
            audience="PUBLIC", release_id="public-without-source"
        )
        next(
            item
            for item in public_without_source["file_mappings"]
            if item["role"] == "MANUSCRIPT_SOURCE"
        )["role"] = "REVISION_HISTORY"

        for index, (name, request) in enumerate(
            (
                ("claim statement", claimless),
                ("checkpoint", checkpointless),
                ("public PDF", public_without_pdf),
                ("public manuscript source", public_without_source),
            )
        ):
            with self.subTest(requirement=name):
                path = f"tmp/role-{index}.json"
                self.write_json(path, request)
                error = self.invoke_error(["build", "--input", path])
                self.assertRegex(error, "(?i)claim|checkpoint|public|compiled|manuscript|role")

    def test_not_applicable_and_omitted_components_need_exact_rationales(self) -> None:
        base = self.release_request()
        inactive_index = next(
            index
            for index, item in enumerate(base["component_declarations"])
            if item["status"] == "NOT_APPLICABLE"
        )
        cases: list[dict[str, object]] = []
        for rationale in (None, ""):
            request = copy.deepcopy(base)
            request["component_declarations"][inactive_index]["rationale"] = rationale
            cases.append(request)
        omitted = copy.deepcopy(base)
        omitted["component_declarations"][inactive_index]["status"] = "OMITTED_REVIEWED"
        omitted["component_declarations"][inactive_index]["rationale"] = ""
        cases.append(omitted)
        paths_when_absent = copy.deepcopy(base)
        paths_when_absent["component_declarations"][inactive_index]["paths"] = [
            "claims/claim-c1.md"
        ]
        cases.append(paths_when_absent)

        for index, request in enumerate(cases):
            with self.subTest(case=index):
                path = f"tmp/rationale-{index}.json"
                self.write_json(path, request)
                error = self.invoke_error(["build", "--input", path])
                self.assertRegex(error, "(?i)rationale|path|empty|applicable|omitted")

        accepted = copy.deepcopy(base)
        accepted["release_id"] = "reviewed-omission"
        accepted["component_declarations"][inactive_index]["status"] = "OMITTED_REVIEWED"
        accepted["component_declarations"][inactive_index]["rationale"] = (
            "A human reviewed and intentionally omitted this component from the projection."
        )
        archive, _ = self.build_release(accepted, input_name="tmp/omitted.json")
        self.assertEqual(self.validate_archive(archive)["status"], "VALID")

    def test_unsafe_duplicate_and_reserved_package_paths_are_rejected(self) -> None:
        base = self.release_request()
        unsafe_paths = (
            "../escape.md",
            "/absolute.md",
            "claims/../escape.md",
            "claims//double.md",
            "./relative.md",
            "README.md",
            "manifest.json",
            "claims\\windows.md",
        )
        for index, package_path in enumerate(unsafe_paths):
            with self.subTest(path=package_path):
                request = copy.deepcopy(base)
                request["file_mappings"][0]["package_path"] = package_path
                path = f"tmp/package-path-{index}.json"
                self.write_json(path, request)
                error = self.invoke_error(["build", "--input", path])
                self.assertRegex(
                    error,
                    "(?i)path|relative|reserved|unsafe|component|manifest|readme",
                )

        duplicate = copy.deepcopy(base)
        duplicate["file_mappings"][1]["package_path"] = duplicate["file_mappings"][0]["package_path"]
        self.write_json("tmp/duplicate-package-path.json", duplicate)
        self.assertRegex(
            self.invoke_error(["build", "--input", "tmp/duplicate-package-path.json"]),
            "(?i)duplicate|unique|package|path",
        )

        for index, manifest_path in enumerate(("../manifest.json", "/manifest.json")):
            with self.subTest(export_manifest_path=manifest_path):
                request = copy.deepcopy(base)
                request["source_export_manifest_path"] = manifest_path
                path = f"tmp/manifest-path-{index}.json"
                self.write_json(path, request)
                error = self.invoke_error(["build", "--input", path])
                self.assertRegex(error, "(?i)path|relative|export|manifest")

        for index, source_path in enumerate(("../source.tex", "/source.tex")):
            with self.subTest(source_path=source_path):
                request = copy.deepcopy(base)
                request["file_mappings"][0]["source_path"] = source_path
                path = f"tmp/source-path-{index}.json"
                self.write_json(path, request)
                error = self.invoke_error(["build", "--input", path])
                self.assertRegex(error, "(?i)path|relative|source")

    def test_package_destinations_reject_reserved_descendants_and_file_directory_collisions(self) -> None:
        reserved_descendants = (
            "README.md/child.txt",
            "readme.MD/child.txt",
            "manifest.json/child.txt",
            "MANIFEST.JSON/child.txt",
        )
        for index, package_path in enumerate(reserved_descendants):
            with self.subTest(reserved_descendant=package_path):
                request = self.release_request(
                    release_id=f"reserved-descendant-{index}"
                )
                self.remap_package_path(request, 0, package_path)
                input_path = f"tmp/reserved-descendant-{index}.json"
                self.write_json(input_path, request)
                error = self.invoke_error(["build", "--input", input_path])
                self.assertRegex(
                    error,
                    "(?i)readme|manifest|reserved|ancestor|descendant|path|topology",
                )

        for index, paths in enumerate(
            (
                ("claims/node", "claims/node/child.md"),
                ("claims/tree/leaf.md", "claims/tree"),
            )
        ):
            with self.subTest(file_directory_collision=paths):
                request = self.release_request(
                    release_id=f"path-topology-{index}"
                )
                self.remap_package_path(request, 0, paths[0])
                self.remap_package_path(request, 1, paths[1])
                input_path = f"tmp/path-topology-{index}.json"
                self.write_json(input_path, request)
                error = self.invoke_error(["build", "--input", input_path])
                self.assertRegex(
                    error,
                    "(?i)ancestor|descendant|collision|topology|package.path|file.*directory",
                )

    def test_package_paths_enforce_windows_portability_and_component_bounds(self) -> None:
        invalid_components = tuple(
            f"bad{character}name.md" for character in '<>:"|?*'
        )
        invalid_components += (
            "trailing.",
            "trailing ",
            "CON",
            "con.txt",
            "PRN.md",
            "aux",
            "NUL.data",
            "COM1.log",
            "com9",
            "LPT1.txt",
            "lpt9",
        )
        for index, component in enumerate(invalid_components):
            with self.subTest(component=component):
                request = self.release_request(
                    release_id=f"portable-component-{index}"
                )
                self.remap_package_path(
                    request,
                    0,
                    f"claims/{component}/artifact.md"
                    if component in {"trailing.", "trailing "}
                    else f"claims/{component}",
                )
                input_path = f"tmp/portable-component-{index}.json"
                self.write_json(input_path, request)
                error = self.invoke_error(["build", "--input", input_path])
                self.assertRegex(
                    error,
                    "(?i)windows|portable|invalid|component|device|reserved|dot|space|path",
                )

        overlong_component = "é" * 128
        self.assertEqual(len(overlong_component.encode("utf-8")), 256)
        request = self.release_request(release_id="overlong-component")
        self.remap_package_path(
            request,
            0,
            f"claims/{overlong_component}",
        )
        self.write_json("tmp/overlong-component.json", request)
        self.assertRegex(
            self.invoke_error(
                ["build", "--input", "tmp/overlong-component.json"]
            ),
            "(?i)component|255|byte|bound|portable|path",
        )

        collisions = (
            ("claims/Artifact.md", "claims/artifact.md"),
            ("claims/Ａrtifact.md", "claims/artifact.md"),
        )
        for index, paths in enumerate(collisions):
            with self.subTest(portable_equivalence=paths):
                request = self.release_request(
                    release_id=f"portable-collision-{index}"
                )
                self.remap_package_path(request, 0, paths[0])
                self.remap_package_path(request, 1, paths[1])
                input_path = f"tmp/portable-collision-{index}.json"
                self.write_json(input_path, request)
                error = self.invoke_error(["build", "--input", input_path])
                self.assertRegex(
                    error,
                    "(?i)collision|equivalent|case|normal|portable|unique|package.path",
                )

    def test_export_claim_paths_are_canonical_and_export_sources_cannot_self_input(self) -> None:
        request = self.release_request(release_id="claim-outside-evidence")
        manifest_path = self.root / request["source_export_manifest_path"]
        manifest = load_json_strict(manifest_path)
        old_claim_path = manifest["claim_bindings"][0]["claim_statement_path"]
        outside_claim = "tmp/reviewed-claim-outside-evidence.md"
        outside_bytes = b"Claim C1 outside canonical evidence roots.\n"
        self.write_bytes(outside_claim, outside_bytes)
        manifest["claim_bindings"][0].update(
            {
                "claim_statement_path": outside_claim,
                "claim_statement_sha256": sha256_bytes(outside_bytes),
            }
        )
        claim_entry = next(
            item
            for item in manifest["included_files"]
            if item["path"] == old_claim_path
        )
        claim_entry.update(
            {
                "path": outside_claim,
                "sha256": sha256_bytes(outside_bytes),
                "bytes": len(outside_bytes),
            }
        )
        next(
            item
            for item in request["file_mappings"]
            if item["source_path"] == old_claim_path
        )["source_path"] = outside_claim
        self.rewrite_export_manifest(request, manifest)
        self.write_json("tmp/claim-outside-evidence.json", request)
        self.assertRegex(
            self.invoke_error(
                ["build", "--input", "tmp/claim-outside-evidence.json"]
            ),
            "(?i)claim|evidence|canonical|source.*root|path",
        )
        self.assertFalse(
            (
                self.root
                / "research/repository_first/releases/claim-outside-evidence/v1.zip"
            ).exists()
        )

        request = self.release_request(release_id="export-self-input")
        manifest_path = self.root / request["source_export_manifest_path"]
        manifest = load_json_strict(manifest_path)
        old_source = "manuscript/paper.tex"
        self_input = f"{manifest['package_root']}/nested-source.tex"
        self_input_bytes = b"reviewed export must not package its own output tree\n"
        self.write_bytes(self_input, self_input_bytes)
        source_entry = next(
            item
            for item in manifest["included_files"]
            if item["path"] == old_source
        )
        source_entry.update(
            {
                "path": self_input,
                "sha256": sha256_bytes(self_input_bytes),
                "bytes": len(self_input_bytes),
            }
        )
        next(
            item
            for item in request["file_mappings"]
            if item["source_path"] == old_source
        )["source_path"] = self_input
        self.rewrite_export_manifest(request, manifest)
        self.write_json("tmp/export-self-input.json", request)
        self.assertRegex(
            self.invoke_error(
                ["build", "--input", "tmp/export-self-input.json"]
            ),
            "(?i)export|self.input|output|forbidden|source|path",
        )
        self.assertFalse(
            (
                self.root
                / "research/repository_first/releases/export-self-input/v1.zip"
            ).exists()
        )

    def test_raw_git_credentials_hidden_prompts_and_factory_private_sources_are_rejected(self) -> None:
        base = self.release_request()
        export_path = self.root / base["source_export_manifest_path"]
        pristine_manifest = export_path.read_bytes()
        unsafe_sources = (
            "research/raw_runs/archive/run.jsonl",
            ".git/config",
            ".env",
            ".netrc",
            "credentials.json",
            "credentials/token.txt",
            "keys/id_ed25519",
            "keys/id_rsa",
            "password",
            "secrets.json",
            "prompts/system_prompt.md",
            "prompts/developer_prompt.md",
            "notes/chain_of_thought.md",
            "factory_memory/events/private.json",
            "research/repository_first/releases/older/v0.zip",
        )
        for index, unsafe_source in enumerate(unsafe_sources):
            with self.subTest(source=unsafe_source):
                request = copy.deepcopy(base)
                data = f"forbidden source {index}\n".encode("utf-8")
                self.write_bytes(unsafe_source, data)
                manifest = json.loads(pristine_manifest.decode("utf-8"))
                entry = next(
                    item
                    for item in manifest["included_files"]
                    if item["path"] == "manuscript/paper.tex"
                )
                entry.update(
                    {
                        "path": unsafe_source,
                        "sha256": sha256_bytes(data),
                        "bytes": len(data),
                    }
                )
                body = dict(manifest)
                del body["manifest_payload_sha256"]
                manifest["manifest_payload_sha256"] = sha256_bytes(
                    canonical_json_bytes(body)
                )
                export_path.chmod(0o644)
                export_path.write_bytes(canonical_json_bytes(manifest))
                export_path.chmod(0o444)
                request["source_export_manifest_sha256"] = sha256_bytes(
                    canonical_json_bytes(manifest)
                )
                next(
                    item
                    for item in request["file_mappings"]
                    if item["source_path"] == "manuscript/paper.tex"
                )["source_path"] = unsafe_source
                path = f"tmp/forbidden-source-{index}.json"
                self.write_json(path, request)
                error = self.invoke_error(["build", "--input", path])
                self.assertRegex(
                    error,
                    "(?i)raw|git|credential|secret|prompt|thought|private|forbidden|path",
                )
                export_path.chmod(0o644)
                export_path.write_bytes(pristine_manifest)
                export_path.chmod(0o444)

    def test_source_symlink_fifo_and_hardlink_are_rejected(self) -> None:
        request = self.release_request()
        source = self.root / "manuscript/paper.tex"
        request_path = "tmp/special-source.json"
        self.write_json(request_path, request)

        original = source.read_bytes()
        source.unlink()
        external = self.write_bytes("tmp/symlink-target.tex", original)
        source.symlink_to(external)
        self.assertRegex(
            self.invoke_error(["build", "--input", request_path]),
            "(?i)symlink|regular|unsafe",
        )

        source.unlink()
        source.write_bytes(original)
        alias = self.root / "tmp/hardlink-alias.tex"
        os.link(source, alias)
        self.assertRegex(
            self.invoke_error(["build", "--input", request_path]),
            "(?i)hardlink|link|regular|unsafe",
        )

        alias.unlink()
        source.unlink()
        os.mkfifo(source)
        self.assertRegex(
            self.invoke_error(["build", "--input", request_path]),
            "(?i)fifo|special|regular|unsafe",
        )

    def test_parent_substitution_races_fail_closed_for_reads_and_publication(self) -> None:
        request = self.release_request(release_id="race-guard")
        request_path = "tmp/race-request.json"
        self.write_json(request_path, request)

        original_parent = self.root / "manuscript"
        moved_parent = self.root / "manuscript-moved"
        real_open = self.release.os.open
        read_raced = False

        def racing_open(path, flags, mode=0o777, *, dir_fd=None):
            nonlocal read_raced
            if path == "paper.tex" and dir_fd is not None and not read_raced:
                read_raced = True
                original_parent.rename(moved_parent)
                original_parent.symlink_to(moved_parent.name, target_is_directory=True)
            return real_open(path, flags, mode, dir_fd=dir_fd)

        self.release.os.open = racing_open
        try:
            error = self.invoke_error(["build", "--input", request_path])
        finally:
            self.release.os.open = real_open
        self.assertTrue(read_raced)
        self.assertRegex(error, "(?i)symlink|public|identity|unsafe")

        original_parent.unlink()
        moved_parent.rename(original_parent)
        request = self.release_request(release_id="publish-race")
        self.write_json(request_path, request)
        releases = self.root / "research/repository_first/releases"
        releases.mkdir(parents=True, exist_ok=True)
        output_parent = releases / "publish-race"
        moved_output_parent = releases / "publish-race-moved"
        real_link = self.release.os.link
        publish_raced = False

        def racing_link(source, destination, *args, **kwargs):
            nonlocal publish_raced
            if not publish_raced:
                publish_raced = True
                output_parent.rename(moved_output_parent)
                output_parent.symlink_to(
                    moved_output_parent.name,
                    target_is_directory=True,
                )
            return real_link(source, destination, *args, **kwargs)

        self.release.os.link = racing_link
        try:
            error = self.invoke_error(["build", "--input", request_path])
        finally:
            self.release.os.link = real_link
        self.assertTrue(publish_raced)
        self.assertRegex(error, "(?i)symlink|public|unsafe|output")
        self.assertEqual(list(moved_output_parent.iterdir()), [])

    def test_archive_symlink_fifo_and_hardlink_are_rejected(self) -> None:
        request = self.release_request()
        archive, _ = self.build_release(request)
        relative = archive.relative_to(self.root).as_posix()
        original = archive.read_bytes()

        alias = self.root / "tmp/archive-hardlink.zip"
        alias.parent.mkdir(parents=True, exist_ok=True)
        os.link(archive, alias)
        self.assertRegex(
            self.invoke_error(["validate", "--archive", relative, "--json"]),
            "(?i)hardlink|link|regular|unsafe",
        )
        alias.unlink()

        archive.chmod(0o644)
        self.assertRegex(
            self.invoke_error(["validate", "--archive", relative, "--json"]),
            "(?i)mode|0444|read.only|immutable",
        )
        archive.chmod(0o444)

        backup = self.root / "tmp/archive-backup.zip"
        archive.chmod(0o644)
        archive.replace(backup)
        archive.symlink_to(backup)
        self.assertRegex(
            self.invoke_error(["validate", "--archive", relative, "--json"]),
            "(?i)symlink|regular|unsafe",
        )
        archive.unlink()
        archive.write_bytes(original)
        archive.chmod(0o444)

        archive.chmod(0o644)
        archive.unlink()
        os.mkfifo(archive)
        self.assertRegex(
            self.invoke_error(["validate", "--archive", relative, "--json"]),
            "(?i)fifo|special|regular|unsafe",
        )

    def test_archive_tamper_wrong_metadata_order_compression_duplicates_and_paths_fail(self) -> None:
        request = self.release_request(audience="PUBLIC")
        archive, _ = self.build_release(request)
        relative = archive.relative_to(self.root).as_posix()
        pristine = archive.read_bytes()
        original_entries = self.zip_entries(archive)

        def content_tamper(entries):
            result = [(copy.copy(info), data) for info, data in entries]
            index = next(
                i
                for i, (info, _data) in enumerate(result)
                if not info.filename.endswith("/manifest.json")
            )
            info, data = result[index]
            result[index] = (info, data + b"tamper")
            return result

        def manifest_tamper(entries):
            result = [(copy.copy(info), data) for info, data in entries]
            index = next(
                i
                for i, (info, _data) in enumerate(result)
                if info.filename.endswith("/manifest.json")
            )
            info, data = result[index]
            manifest = json.loads(data.decode("utf-8"))
            manifest["title"] = "Tampered package manifest"
            result[index] = (info, canonical_json_bytes(manifest))
            return result

        def metadata_tamper(entries):
            result = [(copy.copy(info), data) for info, data in entries]
            result[0][0].date_time = (1981, 1, 1, 0, 0, 0)
            return result

        def mode_tamper(entries):
            result = [(copy.copy(info), data) for info, data in entries]
            result[0][0].external_attr = (stat.S_IFREG | 0o644) << 16
            return result

        def platform_tamper(entries):
            result = [(copy.copy(info), data) for info, data in entries]
            result[0][0].create_system = 0
            return result

        def extra_metadata_tamper(entries):
            result = [(copy.copy(info), data) for info, data in entries]
            result[0][0].extra = b"\xfe\xca\x00\x00"
            return result

        def symlink_member(entries):
            result = [(copy.copy(info), data) for info, data in entries]
            result[0][0].external_attr = (stat.S_IFLNK | 0o777) << 16
            result[0] = (result[0][0], b"../outside")
            return result

        def compression_tamper(entries):
            result = [(copy.copy(info), data) for info, data in entries]
            result[0][0].compress_type = zipfile.ZIP_DEFLATED
            return result

        def duplicate_member(entries):
            result = [(copy.copy(info), data) for info, data in entries]
            result.append((copy.copy(result[0][0]), result[0][1]))
            return result

        def unsafe_member(entries):
            result = [(copy.copy(info), data) for info, data in entries]
            root_prefix = PurePosixPath(result[0][0].filename).parts[0]
            result[0][0].filename = f"{root_prefix}/../escape"
            return result

        def missing_member(entries):
            return [(copy.copy(info), data) for info, data in entries[:-1]]

        def extra_member(entries):
            result = [(copy.copy(info), data) for info, data in entries]
            root_prefix = PurePosixPath(result[0][0].filename).parts[0]
            info = zipfile.ZipInfo(f"{root_prefix}/extra/unreviewed.txt")
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = (stat.S_IFREG | 0o444) << 16
            result.append((info, b"not reviewed\n"))
            return result

        attacks = {
            "content": content_tamper,
            "manifest payload": manifest_tamper,
            "metadata": metadata_tamper,
            "mode": mode_tamper,
            "platform": platform_tamper,
            "extra metadata": extra_metadata_tamper,
            "symlink member": symlink_member,
            "order": lambda entries: list(reversed(entries)),
            "compression": compression_tamper,
            "duplicate": duplicate_member,
            "unsafe path": unsafe_member,
            "missing": missing_member,
            "extra": extra_member,
        }
        for name, transform in attacks.items():
            with self.subTest(attack=name):
                self.replace_archive_from_entries(archive, transform(original_entries))
                error = self.invoke_error(
                    ["validate", "--archive", relative, "--json"]
                )
                self.assertRegex(
                    error,
                    "(?i)archive|zip|member|digest|hash|metadata|mode|order|compression|duplicate|path|file",
                )
                archive.chmod(0o644)
                archive.write_bytes(pristine)
                archive.chmod(0o444)

    def test_oversized_generated_readme_and_manifest_are_rejected_before_member_reads(self) -> None:
        request = self.release_request(release_id="oversized-generated")
        archive, _ = self.build_release(
            request,
            input_name="tmp/oversized-generated.json",
        )
        relative = archive.relative_to(self.root).as_posix()
        pristine = archive.read_bytes()
        pristine_entries = self.zip_entries(archive)
        root_prefix = PurePosixPath(pristine_entries[0][0].filename).parts[0]

        for basename in ("README.md", "manifest.json"):
            with self.subTest(member=basename):
                target_name = f"{root_prefix}/{basename}"
                entries = [(copy.copy(info), data) for info, data in pristine_entries]
                target_index = next(
                    index
                    for index, (info, _data) in enumerate(entries)
                    if info.filename == target_name
                )
                info, _data = entries[target_index]
                entries[target_index] = (
                    info,
                    b"x" * (self.release.MAX_GENERATED_MEMBER_BYTES + 1),
                )
                self.replace_archive_from_entries(archive, entries)

                original_open = self.release.zipfile.ZipFile.open
                oversized_member_opened = False

                def tracking_open(instance, name, *args, **kwargs):
                    nonlocal oversized_member_opened
                    filename = name.filename if isinstance(name, zipfile.ZipInfo) else name
                    if filename == target_name:
                        oversized_member_opened = True
                    return original_open(instance, name, *args, **kwargs)

                self.release.zipfile.ZipFile.open = tracking_open
                try:
                    error = self.invoke_error(
                        ["validate", "--archive", relative, "--json"]
                    )
                finally:
                    self.release.zipfile.ZipFile.open = original_open
                self.assertFalse(
                    oversized_member_opened,
                    f"validator opened oversized generated member {target_name}",
                )
                self.assertRegex(
                    error,
                    "(?i)(readme|manifest).*(bound|size|large|8)|"
                    "(bound|size|large).*(readme|manifest)",
                )
                archive.chmod(0o644)
                archive.write_bytes(pristine)
                archive.chmod(0o444)

    def test_central_directory_member_cap_precedes_zipfile_allocation(self) -> None:
        advertised_entries = self.release.MAX_FILES + 3
        self.assertEqual(advertised_entries, 259)
        malformed = struct.pack(
            "<4s4H2LH",
            b"PK\x05\x06",
            0,
            0,
            advertised_entries,
            advertised_entries,
            0,
            0,
            0,
        )
        relative = (
            "research/repository_first/releases/central-directory-cap/v1.zip"
        )
        archive = self.write_bytes(relative, malformed)
        archive.chmod(0o444)

        original_zipfile = self.release.zipfile.ZipFile
        zipfile_allocated = False

        def tracking_zipfile(*args, **kwargs):
            nonlocal zipfile_allocated
            zipfile_allocated = True
            return original_zipfile(*args, **kwargs)

        self.release.zipfile.ZipFile = tracking_zipfile
        try:
            error = self.invoke_error(
                ["validate", "--archive", relative, "--json"]
            )
        finally:
            self.release.zipfile.ZipFile = original_zipfile
        self.assertFalse(
            zipfile_allocated,
            "validator allocated ZipFile before rejecting the advertised member count",
        )
        self.assertRegex(
            error,
            "(?i)central|director|member|entr|count|bound|258",
        )

    def test_validator_rechecks_current_export_and_source_bindings(self) -> None:
        request = self.release_request()
        archive, _ = self.build_release(request)
        relative = archive.relative_to(self.root).as_posix()
        self.assertEqual(self.validate_archive(archive)["status"], "VALID")

        source = self.root / "manuscript/paper.tex"
        source.write_text("stale after package construction\n", encoding="utf-8")
        self.assertRegex(
            self.invoke_error(["validate", "--archive", relative, "--json"]),
            "(?i)source|sha|digest|hash|stale|drift|match",
        )

        source.write_bytes(
            b"\\documentclass{article}\n\\begin{document}Claim C1.\\end{document}\n"
        )
        export_path = self.root / request["source_export_manifest_path"]
        original_export = export_path.read_bytes()
        export_path.chmod(0o644)
        export_path.write_bytes(original_export + b" \n")
        export_path.chmod(0o444)
        self.assertRegex(
            self.invoke_error(["validate", "--archive", relative, "--json"]),
            "(?i)export|sha|digest|hash|stale|drift|json|match",
        )

    def test_schemas_are_duplicate_free_and_every_object_is_closed(self) -> None:
        for path in (REQUEST_SCHEMA, PACKAGE_SCHEMA):
            with self.subTest(schema=path.name):
                schema = load_json_strict(path)
                self.assertIs(schema["additionalProperties"], False)
                assert_all_object_schemas_closed(self, schema)

    def test_schema_examples_are_structurally_valid(self) -> None:
        request_schema = load_json_strict(REQUEST_SCHEMA)
        request_example = load_json_strict(
            LAB_TEMPLATE_ROOT / "templates/repository_first/release_request.json"
        )
        assert_matches_schema(self, request_example, request_schema)
        normalized = self.release.validate_request(request_example)
        self.assertEqual(normalized["record_type"], "research_release_request")
        self.assertEqual(
            {item["component"] for item in normalized["component_declarations"]},
            set(COMPONENTS),
        )
        for schema_path in (REQUEST_SCHEMA, PACKAGE_SCHEMA):
            schema = load_json_strict(schema_path)
            for index, example in enumerate(schema.get("examples", [])):
                with self.subTest(schema=schema_path.name, example=index):
                    assert_matches_schema(self, example, schema)

    def test_helper_imports_no_process_network_or_git_clients(self) -> None:
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"), filename=str(SCRIPT))
        imported_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
        self.assertTrue(
            imported_roots.isdisjoint(
                {
                    "asyncio",
                    "ftplib",
                    "git",
                    "github",
                    "http",
                    "multiprocessing",
                    "paramiko",
                    "requests",
                    "smtplib",
                    "socket",
                    "subprocess",
                    "urllib",
                }
            ),
            imported_roots,
        )

    def test_schemas_hard_code_no_outbound_and_no_claim_promotion(self) -> None:
        for path in (REQUEST_SCHEMA, PACKAGE_SCHEMA):
            with self.subTest(schema=path.name):
                properties = load_json_strict(path)["properties"]
                self.assertIs(properties["no_outbound_action"].get("const"), True)
                self.assertIs(
                    properties["automatic_claim_promotion"].get("const"),
                    False,
                )
                forbidden = {
                    "claim_status",
                    "overall_status",
                    "publish",
                    "remote",
                    "recipient",
                    "upload",
                    "url",
                }
                self.assertTrue(forbidden.isdisjoint(properties), properties.keys())


if __name__ == "__main__":
    unittest.main()
