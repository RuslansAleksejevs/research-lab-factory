#!/usr/bin/env python3
"""Static, read-only validation for one Lean Room case."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from lean_room import (
    EXIT_OK,
    EXIT_VALIDATION,
    LEAN_ROOM_AUDIT_COMMAND_SCHEMA,
    LEAN_ROOM_BUILD_COMMAND_SCHEMA,
    LeanRoomError,
    ValidationError,
    case_path,
    discover_root,
    load_json_object,
    normalized_contract_sha256,
    project_tree_inventory,
    reject_symlink_components,
    safe_relative_file,
    scan_regular_tree,
    sha256_file,
    validate_lean_name,
    validate_toolchain,
)


SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
UNRESOLVED_RE = re.compile(r"\{\{[^{}\r\n]+\}\}")
DECLARATION_RE = re.compile(
    r"(?m)(?:^|\s)(?:protected\s+)?(?:theorem|lemma)\s+([A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*)"
)
NAMESPACE_RE = re.compile(r"^\s*namespace\s+([A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*)\s*$")
END_RE = re.compile(r"^\s*end(?:\s+([A-Za-z_][A-Za-z0-9_']*))?\s*$")
CANONICAL_LOCAL_IMPORT_RE = re.compile(
    r"import\s+([A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*)\Z"
)
FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sorry", re.compile(r"\bsorry\b")),
    ("admit", re.compile(r"\badmit\b")),
    ("sorryAx", re.compile(r"\bsorryAx\b")),
    ("project axiom", re.compile(r"\b(?:axiom|axioms|constant|constants)\b")),
    ("native_decide", re.compile(r"\bnative_decide\b")),
    (
        "external bit-vector certificate or solver",
        re.compile(r"\bbv_(?:check|decide\??)\b"),
    ),
    ("unsafe", re.compile(r"\bunsafe\b")),
    ("foreign/extern", re.compile(r"(?:\bextern\b|@\[\s*implemented_by\b)")),
    ("run_tac", re.compile(r"\brun_tac\b")),
    (
        "unbound elaboration-time file input",
        re.compile(r"(?:\binclude_str\b|\bcompile_time_search_path%)"),
    ),
    (
        "module header or import modifier",
        re.compile(r"(?m)^\s*(?:module|private|public|meta)\b"),
    ),
    ("executable command", re.compile(r"(?:#\s*(?:eval|run)\b|\brun_cmd\b)")),
    ("opaque declaration", re.compile(r"\bopaque\b")),
    ("partial declaration", re.compile(r"\bpartial\b")),
    ("initializer", re.compile(r"\b(?:initialize|builtin_initialize)\b")),
    ("custom elaborator", re.compile(r"\b(?:elab|elab_rules|macro|macro_rules|syntax)\b")),
    (
        "custom notation",
        re.compile(
            r"\b(?:notation|infix|infixl|infixr|prefix|postfix|mixfix)\b"
        ),
    ),
    (
        "elaborator registration",
        re.compile(
            r"(?:@\[\s*(?:builtin_)?(?:command|term|tactic)_elab\b|"
            r"\b(?:builtin_)?(?:command|term|tactic)_elab\b|"
            r"\b[A-Za-z_][A-Za-z0-9_]*(?:_parser|_elab|_macro)\b|"
            r"\b(?:CommandElab|TermElab|TacticElab)\b)"
        ),
    ),
    ("attribute declaration", re.compile(r"@\[")),
    (
        "metaprogramming API",
        re.compile(
            r"\b(?:Lean\.(?:Elab|Meta|Parser|Core|Environment|Declaration)|"
            r"Lean\.addDecl|addAndCompile|"
            r"Declaration\.(?:axiomDecl|opaqueDecl|thmDecl|defnDecl)|"
            r"by_elab|run_elab|run_meta|mkSorry(?:FromSyntheticMVar)?)\b"
        ),
    ),
    (
        "Lean metaprogramming import",
        re.compile(
            r"(?m)^\s*(?:(?:public|private|meta)\s+)*import\s+(?:Lean|Lake)(?:\.|\s|$)"
        ),
    ),
    ("plugin", re.compile(r"\bplugin\b")),
    ("autoImplicit enabled", re.compile(r"\bset_option\s+autoImplicit\s+true\b")),
)
LAKEFILE_FORBIDDEN_RE = re.compile(
    r"(?i)(?:\[\[\s*(?:lean_exe|extern_lib|script)|\b(?:postUpdate|facet|moreLinkArgs|weakLinkArgs|plugin|foreign|--update|try-cache|no-cache|fetch)\b)"
)
LAKEFILE_ALLOWED_SECTION_RE = re.compile(r"^\[\[(lean_lib|require)\]\]$")
LAKEFILE_ALLOWED_TOP_KEYS = {"name", "version", "defaultTargets"}
LAKEFILE_ALLOWED_SECTION_KEYS = {
    "lean_lib": {"name", "srcDir", "globs"},
    "require": {"name", "git", "rev"},
}
PRECOMPILED_SUFFIXES = {
    ".olean", ".ilean", ".o", ".a", ".so", ".dylib", ".dll", ".bc", ".c", ".cpp"
}
CANONICAL_LAKEFILE_RE = re.compile(
    r'\Aname = "(?P<name>[A-Za-z_][A-Za-z0-9_]{0,119})"\n'
    r'version = "0\.1\.0"\n'
    r'defaultTargets = \["LeanRoomCase"\]\n\n'
    r'\[\[lean_lib\]\]\n'
    r'name = "LeanRoomCase"\n'
    r'globs = \["Main", "LeanRoomCase"\]\n\Z'
)


@dataclass
class ValidationReport:
    root: Path
    case: Path
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_tree_sha256: str | None = None
    contract: dict[str, Any] | None = None
    declared_theorems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "record_type": "lean_case_static_validation",
            "case": self.case.relative_to(self.root).as_posix(),
            "ok": self.ok,
            "issues": self.issues,
            "warnings": self.warnings,
            "source_tree_sha256": self.source_tree_sha256,
            "declared_theorems": self.declared_theorems,
        }


def strip_lean_comments_and_strings(text: str) -> str:
    """Remove nested comments and strings while retaining line structure."""
    output: list[str] = []
    index = 0
    block_depth = 0
    in_string = False
    while index < len(text):
        pair = text[index : index + 2]
        char = text[index]
        if block_depth:
            if pair == "/-":
                block_depth += 1
                output.extend("  ")
                index += 2
            elif pair == "-/":
                block_depth -= 1
                output.extend("  ")
                index += 2
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
            continue
        if in_string:
            if char == "\\" and index + 1 < len(text):
                output.extend("  ")
                index += 2
            elif char == '"':
                in_string = False
                output.append(" ")
                index += 1
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
            continue
        if pair == "/-":
            block_depth = 1
            output.extend("  ")
            index += 2
        elif pair == "--":
            while index < len(text) and text[index] != "\n":
                output.append(" ")
                index += 1
        elif char == '"':
            in_string = True
            output.append(" ")
            index += 1
        else:
            output.append(char)
            index += 1
    return "".join(output)


def declared_theorems(text: str) -> set[str]:
    stripped = strip_lean_comments_and_strings(text)
    namespace_stack: list[str] = []
    result: set[str] = set()
    for line in stripped.splitlines():
        namespace_match = NAMESPACE_RE.match(line)
        if namespace_match:
            namespace_stack.extend(namespace_match.group(1).split("."))
            continue
        end_match = END_RE.match(line)
        if end_match and namespace_stack:
            named = end_match.group(1)
            if named and named in namespace_stack:
                while namespace_stack and namespace_stack[-1] != named:
                    namespace_stack.pop()
            if namespace_stack:
                namespace_stack.pop()
            continue
        for match in DECLARATION_RE.finditer(line):
            name = match.group(1)
            if "." in name or not namespace_stack:
                result.add(name)
            else:
                result.add(".".join([*namespace_stack, name]))
    return result


def _is_nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value))


def _check_bound_artifact(
    report: ValidationReport,
    binding: Any,
    artifact_key: str,
    hash_key: str,
    label: str,
    required: bool,
) -> None:
    if not isinstance(binding, dict):
        report.issues.append(f"missing {label} binding object")
        return
    artifact = binding.get(artifact_key)
    expected = binding.get(hash_key)
    if artifact is None and expected is None and not required:
        return
    if not _is_nonempty(artifact) or not _is_sha(expected):
        report.issues.append(f"{label} binding is incomplete")
        return
    try:
        path = safe_relative_file(report.root, artifact, label)
        problem = report.case.parents[2]
        try:
            path.relative_to(problem)
        except ValueError:
            report.issues.append(f"{label} must be inside the same problem dossier")
            return
        try:
            path.relative_to(problem / "formalization/cases")
        except ValueError:
            pass
        else:
            report.issues.append(f"{label} cannot bind a Lean case artifact")
            return
        actual = sha256_file(path)
        if actual != expected:
            report.issues.append(f"{label} SHA-256 mismatch")
    except ValidationError as exc:
        report.issues.append(str(exc))


def _validate_contract_schema(
    report: ValidationReport, contract: dict[str, Any], verification_ready: bool
) -> None:
    if contract.get("schema_version") != 1:
        report.issues.append("contract schema_version must be 1")
    if contract.get("record_type") != "lean_formalization_contract":
        report.issues.append("contract record_type must be lean_formalization_contract")
    if contract.get("problem_id") != report.case.parents[2].name:
        report.issues.append("contract problem_id does not match case path")
    if contract.get("case_id") != report.case.name:
        report.issues.append("contract case_id does not match case path")
    status = contract.get("status")
    if status not in {"DRAFT", "FROZEN"}:
        report.issues.append("contract status must be DRAFT or FROZEN")
    if verification_ready and status != "FROZEN":
        report.issues.append("verification-ready case requires contract status FROZEN")
    required_bindings = verification_ready or bool(
        isinstance(contract.get("freeze"), dict)
        and contract["freeze"].get("lr0_contract_frozen")
    )
    target = contract.get("target_binding")
    _check_bound_artifact(
        report, target, "artifact", "artifact_sha256", "target artifact", required_bindings
    )
    if required_bindings and (not isinstance(target, dict) or not _is_nonempty(target.get("target_id"))):
        report.issues.append("target_id is required after LR0")
    obligation = contract.get("obligation_binding")
    _check_bound_artifact(
        report,
        obligation,
        "artifact",
        "artifact_sha256",
        "proof-obligation artifact",
        required_bindings,
    )
    obligation_ids = obligation.get("obligation_ids") if isinstance(obligation, dict) else None
    if required_bindings and (
        not isinstance(obligation_ids, list)
        or not obligation_ids
        or not all(_is_nonempty(item) for item in obligation_ids)
    ):
        report.issues.append("nonempty obligation_ids are required after LR0")
    informal = contract.get("informal_claim")
    if not isinstance(informal, dict) or not _is_nonempty(informal.get("statement")):
        report.issues.append("informal_claim.statement is required")
    obligations = contract.get("correspondence_obligations")
    if not isinstance(obligations, list) or not obligations or not all(
        _is_nonempty(item) for item in obligations
    ):
        report.issues.append("nonempty correspondence_obligations are required")


def _validate_project(
    report: ValidationReport,
    contract: dict[str, Any],
    verification_ready: bool,
    allow_missing_declaration: bool = False,
) -> None:
    case = report.case
    project = case / "project"
    try:
        inventory, tree_digest = project_tree_inventory(project)
    except ValidationError as exc:
        report.issues.append(str(exc))
        return
    report.source_tree_sha256 = tree_digest
    required = [
        project / "lean-toolchain",
        project / "lakefile.toml",
        project / "lake-manifest.json",
    ]
    for path in required:
        if path.is_symlink() or not path.is_file():
            report.issues.append(f"missing required project file: {path.name}")
    if (project / "lakefile.lean").exists():
        report.issues.append("executable lakefile.lean is forbidden; use lakefile.toml")
    lakefile_path = project / "lakefile.toml"
    if lakefile_path.is_file():
        lakefile_text = lakefile_path.read_text(encoding="utf-8")
        if LAKEFILE_FORBIDDEN_RE.search(lakefile_text):
            report.issues.append("forbidden executable or network-capable Lake configuration")
        current_section: str | None = None
        for line_number, raw_line in enumerate(lakefile_text.splitlines(), start=1):
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("[["):
                match = LAKEFILE_ALLOWED_SECTION_RE.fullmatch(line)
                if not match:
                    report.issues.append(
                        f"unsupported Lake configuration section at line {line_number}: {line}"
                    )
                    current_section = None
                else:
                    current_section = match.group(1)
                continue
            if "=" not in line:
                report.issues.append(f"invalid Lake configuration line {line_number}")
                continue
            key = line.split("=", 1)[0].strip()
            allowed = (
                LAKEFILE_ALLOWED_TOP_KEYS
                if current_section is None
                else LAKEFILE_ALLOWED_SECTION_KEYS[current_section]
            )
            if key not in allowed:
                report.issues.append(
                    f"unsupported Lake configuration key at line {line_number}: {key}"
                )
        canonical_match = CANONICAL_LAKEFILE_RE.fullmatch(lakefile_text)
        manifest_name = None
        try:
            manifest_name = load_json_object(
                project / "lake-manifest.json", "lake manifest"
            ).get("name")
        except ValidationError:
            pass
        if canonical_match is None or canonical_match.group("name") != manifest_name:
            report.issues.append(
                "lakefile.toml must equal the canonical dependency-free v1 library configuration"
            )

    local_modules = {
        entry["path"][:-5].replace("/", ".")
        for entry in inventory
        if entry["path"].endswith(".lean")
    }
    for entry in inventory:
        path = project / entry["path"]
        if path.suffix.casefold() in PRECOMPILED_SUFFIXES:
            report.issues.append(f"precompiled or foreign source artifact forbidden: project/{entry['path']}")
        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        unresolved = UNRESOLVED_RE.search(raw)
        if unresolved:
            report.issues.append(
                f"unresolved template token in project/{entry['path']}: {unresolved.group(0)}"
            )
        if path.suffix == ".lean":
            stripped = strip_lean_comments_and_strings(raw)
            for label, pattern in FORBIDDEN_PATTERNS:
                if pattern.search(stripped):
                    report.issues.append(
                        f"forbidden construct: {label} in project/{entry['path']}"
                    )
            for line_number, raw_line in enumerate(stripped.splitlines(), start=1):
                line = raw_line.strip()
                if not line.startswith("import"):
                    continue
                match = CANONICAL_LOCAL_IMPORT_RE.fullmatch(line)
                if match is None:
                    report.issues.append(
                        "only canonical unmodified local imports are allowed in "
                        f"Lean Room v1: project/{entry['path']}:{line_number}"
                    )
                    continue
                module_name = match.group(1)
                if module_name not in local_modules:
                    report.issues.append(
                        "Lean Room v1 import must resolve to a source module in the "
                        f"frozen project: {module_name} in project/{entry['path']}"
                    )

    correspondence = case / "formal_correspondence.md"
    if correspondence.is_symlink() or not correspondence.is_file():
        report.issues.append("missing formal_correspondence.md")
    else:
        try:
            token = UNRESOLVED_RE.search(correspondence.read_text(encoding="utf-8"))
            if token:
                report.issues.append(
                    f"unresolved template token in formal_correspondence.md: {token.group(0)}"
                )
        except UnicodeDecodeError:
            report.issues.append("formal_correspondence.md is not UTF-8")

    formal = contract.get("formal_target")
    if not isinstance(formal, dict):
        report.issues.append("formal_target object is missing")
        return
    source_name = formal.get("source_file")
    declaration_name = formal.get("declaration_name")
    if not _is_nonempty(source_name):
        report.issues.append("formal_target.source_file is required")
        return
    try:
        source = safe_relative_file(project, source_name, "formal target source")
    except ValidationError as exc:
        report.issues.append(str(exc))
        return
    if source.suffix != ".lean":
        report.issues.append("formal target source must be a .lean file")
    try:
        declaration_name = validate_lean_name(declaration_name)
    except (ValidationError, TypeError) as exc:
        report.issues.append(str(exc))
        return
    declared = declared_theorems(source.read_text(encoding="utf-8"))
    report.declared_theorems = sorted(declared)
    if declaration_name not in declared and not allow_missing_declaration:
        report.issues.append(
            f"formal target declaration not found: {declaration_name} in {source_name}"
        )
    if verification_ready and not _is_nonempty(formal.get("exact_type")):
        report.issues.append("formal_target.exact_type is required for verification")
    exact_type = formal.get("exact_type")
    if _is_nonempty(exact_type) and (
        any(token in exact_type for token in ("\n", "\r", ";", "#", "--", "/-", "-/", ":="))
        or re.search(r"(?:^|\W)(?:_|\?[_A-Za-z0-9]*|by|sorry)(?:$|\W)", exact_type)
        or len(exact_type) > 16000
    ):
        report.issues.append("formal_target.exact_type contains audit-source injection syntax")

    environment = contract.get("environment")
    if not isinstance(environment, dict):
        report.issues.append("environment object is missing")
        return
    try:
        toolchain = validate_toolchain(environment.get("lean_toolchain", ""))
    except ValidationError as exc:
        report.issues.append(str(exc))
        toolchain = None
    toolchain_path = project / "lean-toolchain"
    if toolchain and toolchain_path.is_file():
        if toolchain_path.read_text(encoding="utf-8").strip() != toolchain:
            report.issues.append("lean-toolchain does not match contract pin")
    digest_bindings = (
        ("lean_toolchain_sha256", toolchain_path),
        ("lakefile_sha256", project / "lakefile.toml"),
        ("lake_manifest_sha256", project / "lake-manifest.json"),
    )
    for field_name, path in digest_bindings:
        expected = environment.get(field_name)
        if path.is_file() and expected is not None:
            if not _is_sha(expected) or sha256_file(path) != expected:
                report.issues.append(f"environment.{field_name} mismatch")
        elif verification_ready:
            report.issues.append(f"environment.{field_name} is required")
    if environment.get("network_allowed_during_certificate_build") is not False:
        report.issues.append("certificate build network policy must be false")
    if environment.get("allowed_build_commands") != [
        list(LEAN_ROOM_BUILD_COMMAND_SCHEMA),
        list(LEAN_ROOM_AUDIT_COMMAND_SCHEMA),
    ]:
        report.issues.append("environment.allowed_build_commands is not the canonical v1 schema")
    try:
        manifest = load_json_object(project / "lake-manifest.json", "lake manifest")
        packages = manifest.get("packages")
        if (
            set(manifest)
            != {"version", "packagesDir", "packages", "name", "lakeDir"}
            or manifest.get("version") != "1.1.0"
            or manifest.get("packagesDir") != ".lake/packages"
            or manifest.get("lakeDir") != ".lake"
            or not isinstance(manifest.get("name"), str)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,119}", manifest["name"])
        ):
            report.issues.append(
                "lake-manifest.json must equal the canonical dependency-free v1 manifest shape"
            )
        if not isinstance(packages, list):
            report.issues.append("lake manifest packages must be a list")
        elif packages:
            report.issues.append(
                "dependency-bearing cases are not certifiable by Lean Room v1"
            )
        elif environment.get("dependency_free") is True and packages:
            report.issues.append("dependency-free contract has Lake packages")
        elif environment.get("dependency_free") is False and not packages:
            report.issues.append("dependency-bearing contract has no Lake packages")
        for package in packages if isinstance(packages, list) else []:
            if not isinstance(package, dict):
                report.issues.append("invalid Lake package manifest entry")
                continue
            revision = package.get("rev") or package.get("inputRev")
            if package.get("type") == "path" or "path" in package:
                report.issues.append("path dependencies are forbidden in Lean Room builds")
            if package.get("type") == "git" and not (
                isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{40,64}", revision)
            ):
                report.issues.append("unpinned dependency in Lake manifest")
    except ValidationError as exc:
        report.issues.append(str(exc))


def _validate_freeze_and_history(
    report: ValidationReport, contract: dict[str, Any], verification_ready: bool
) -> None:
    freeze = contract.get("freeze")
    if not isinstance(freeze, dict):
        report.issues.append("freeze object is missing")
        return
    lr0 = freeze.get("lr0_contract_frozen")
    lr1 = freeze.get("lr1_sources_frozen")
    if verification_ready and (lr0 is not True or lr1 is not True):
        report.issues.append("verification-ready case requires LR0 and LR1 freezes")
    lr0_hash = freeze.get("lr0_payload_sha256")
    if lr0 is True:
        from freeze_lean_case import lr0_payload_sha256, validate_lr0_readiness

        actual = lr0_payload_sha256(contract)
        if not _is_sha(lr0_hash) or lr0_hash != actual:
            report.issues.append("LR0 frozen payload mutation detected")
        report.issues.extend(validate_lr0_readiness(contract))
        _validate_freeze_snapshot(report, contract, "LR0", freeze.get("lr0_snapshot_id"))
    if lr1 is True:
        if report.source_tree_sha256 != freeze.get("frozen_source_tree_sha256"):
            report.issues.append("source tree mutation detected after LR1")
        environment = contract.get("environment")
        if not isinstance(environment, dict) or environment.get("source_tree_sha256") != report.source_tree_sha256:
            report.issues.append("frozen environment source-tree digest mismatch")
        frozen_contract_hash = freeze.get("frozen_contract_sha256")
        if not _is_sha(frozen_contract_hash) or frozen_contract_hash != normalized_contract_sha256(contract):
            report.issues.append("frozen contract SHA-256 mismatch")
        _validate_freeze_snapshot(report, contract, "LR1", freeze.get("lr1_snapshot_id"))
    runs = report.case / "evidence/runs"
    try:
        reject_symlink_components(runs, report.case)
        runs_safe = not runs.is_symlink()
    except ValidationError as exc:
        report.issues.append(f"unsafe historical run container: {exc}")
        runs_safe = False
    if runs_safe and runs.is_dir() and report.source_tree_sha256:
        for digest_path in sorted(runs.glob("*/source_tree.sha256")):
            try:
                reject_symlink_components(digest_path, report.case)
            except ValidationError as exc:
                report.issues.append(f"unsafe historical source digest: {exc}")
                continue
            if digest_path.is_symlink() or not digest_path.is_file():
                report.issues.append(f"unsafe historical source digest: {digest_path}")
                continue
            historical = digest_path.read_text(encoding="ascii", errors="replace").strip()
            if not SHA256_RE.fullmatch(historical):
                report.issues.append(f"malformed historical source digest: {digest_path}")
            elif historical != report.source_tree_sha256:
                report.issues.append(
                    f"source tree mutation detected against evidence: {digest_path.relative_to(report.case)}"
                )


def _validate_freeze_snapshot(
    report: ValidationReport,
    live_contract: dict[str, Any],
    gate: str,
    snapshot_id: Any,
) -> None:
    if not isinstance(snapshot_id, str) or not re.fullmatch(
        rf"{gate}-[A-Za-z0-9._-]+", snapshot_id
    ):
        report.issues.append(f"{gate} freeze snapshot id is missing or unsafe")
        return
    directory = report.case / "evidence/freezes" / snapshot_id
    try:
        reject_symlink_components(directory, report.case)
    except ValidationError as exc:
        report.issues.append(f"unsafe {gate} freeze snapshot: {exc}")
        return
    if directory.is_symlink() or not directory.is_dir():
        report.issues.append(f"{gate} freeze snapshot directory is missing")
        return
    try:
        scan_regular_tree(directory)
    except ValidationError as exc:
        report.issues.append(f"unsafe {gate} freeze snapshot: {exc}")
        return
    try:
        manifest = load_json_object(directory / "freeze_manifest.yaml", f"{gate} freeze manifest")
        snapshot = load_json_object(directory / "contract.snapshot.yaml", f"{gate} contract snapshot")
    except ValidationError as exc:
        report.issues.append(str(exc))
        return
    if (
        manifest.get("schema_version") != 1
        or manifest.get("record_type") != "lean_freeze_snapshot"
        or manifest.get("case_id") != live_contract.get("case_id")
        or manifest.get("problem_id") != live_contract.get("problem_id")
        or manifest.get("gate") != gate
        or manifest.get("snapshot_id") != snapshot_id
        or manifest.get("navigation_only") is not False
        or manifest.get("automatic_math_status_change") is not False
    ):
        report.issues.append(f"{gate} freeze manifest binding mismatch")
    snapshot_hash = sha256_file(directory / "contract.snapshot.yaml")
    if manifest.get("contract_snapshot_sha256") != snapshot_hash:
        report.issues.append(f"{gate} contract snapshot SHA-256 mismatch")
    from freeze_lean_case import lr0_payload_sha256

    if lr0_payload_sha256(snapshot) != lr0_payload_sha256(live_contract):
        report.issues.append(f"{gate} snapshot does not bind the live LR0 payload")
    bindings = manifest.get("gate_bindings")
    live_freeze = live_contract.get("freeze")
    if not isinstance(bindings, dict) or not isinstance(live_freeze, dict):
        report.issues.append(f"{gate} freeze gate bindings are missing")
    elif gate == "LR0" and (
        bindings.get("frozen_at") != live_freeze.get("lr0_frozen_at")
        or bindings.get("frozen_by") != live_freeze.get("lr0_frozen_by")
        or bindings.get("lr0_payload_sha256") != live_freeze.get("lr0_payload_sha256")
    ):
        report.issues.append("LR0 freeze gate bindings differ from the live contract")
    elif gate == "LR1" and (
        bindings.get("frozen_at") != live_freeze.get("lr1_frozen_at")
        or bindings.get("frozen_by") != live_freeze.get("lr1_frozen_by")
        or bindings.get("lr0_payload_sha256") != live_freeze.get("lr0_payload_sha256")
        or bindings.get("source_tree_sha256")
        != live_freeze.get("frozen_source_tree_sha256")
        or bindings.get("frozen_contract_sha256")
        != live_freeze.get("frozen_contract_sha256")
    ):
        report.issues.append("LR1 freeze gate bindings differ from the live contract")
    if gate == "LR0":
        preserved = manifest.get("preserved_artifacts")
        expected = {
            "informal_target": live_contract.get("target_binding"),
            "proof_obligations": live_contract.get("obligation_binding"),
        }
        if not isinstance(preserved, list):
            report.issues.append("LR0 snapshot preserved_artifacts list is missing")
        else:
            seen: set[str] = set()
            for item in preserved:
                if not isinstance(item, dict):
                    report.issues.append("invalid LR0 preserved artifact entry")
                    continue
                kind = item.get("kind")
                binding = expected.get(kind)
                if not isinstance(kind, str) or binding is None or kind in seen:
                    report.issues.append("unexpected or duplicate LR0 preserved artifact")
                    continue
                seen.add(kind)
                snapshot_artifact = item.get("snapshot_artifact")
                if not isinstance(snapshot_artifact, str):
                    report.issues.append(f"{kind} LR0 snapshot artifact path is missing")
                    continue
                try:
                    preserved_path = safe_relative_file(
                        directory, snapshot_artifact, f"{kind} LR0 snapshot artifact"
                    )
                    actual_sha256 = sha256_file(preserved_path)
                    actual_size = preserved_path.stat().st_size
                except (ValidationError, OSError) as exc:
                    report.issues.append(str(exc))
                    continue
                if not isinstance(binding, dict) or (
                    item.get("source_artifact") != binding.get("artifact")
                    or item.get("sha256") != binding.get("artifact_sha256")
                ):
                    report.issues.append(f"{kind} LR0 preserved binding mismatch")
                if item.get("sha256") != actual_sha256 or item.get("size") != actual_size:
                    report.issues.append(f"{kind} LR0 preserved snapshot digest mismatch")
            if seen != set(expected):
                report.issues.append("LR0 snapshot does not preserve both target artifacts")
    if gate == "LR1":
        live_hash = sha256_file(report.case / "formalization_contract.yaml")
        if snapshot_hash != live_hash:
            report.issues.append("LR1 contract snapshot differs from frozen live contract")
        inventory_path = directory / "source_tree_inventory.json"
        digest_path = directory / "source_tree.sha256"
        project_snapshot = directory / "project.snapshot"
        try:
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            current_inventory, current_digest = project_tree_inventory(report.case / "project")
            snapshot_inventory, snapshot_digest = project_tree_inventory(project_snapshot)
            if (
                manifest.get("source_tree_inventory_artifact")
                != "source_tree_inventory.json"
                or manifest.get("source_tree_inventory_sha256")
                != sha256_file(inventory_path)
                or manifest.get("source_tree_digest_artifact")
                != "source_tree.sha256"
                or manifest.get("source_tree_digest_artifact_sha256")
                != sha256_file(digest_path)
                or manifest.get("project_snapshot_artifact") != "project.snapshot"
                or manifest.get("project_snapshot_file_count") != len(snapshot_inventory)
                or manifest.get("project_snapshot_tree_sha256") != snapshot_digest
            ):
                report.issues.append("LR1 freeze manifest source snapshot binding mismatch")
            if inventory != current_inventory:
                report.issues.append("LR1 source inventory snapshot mismatch")
            if snapshot_inventory != inventory or snapshot_digest != current_digest:
                report.issues.append("LR1 full project snapshot mismatch")
            if digest_path.read_text(encoding="ascii").strip() != current_digest:
                report.issues.append("LR1 source digest snapshot mismatch")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
            report.issues.append(f"invalid LR1 source snapshot: {exc}")


def validate_case(
    root: Path,
    problem_id: str,
    case_id: str,
    verification_ready: bool = False,
    allow_missing_declaration: bool = False,
) -> ValidationReport:
    case = case_path(root, problem_id, case_id)
    report = ValidationReport(root=root, case=case)
    try:
        contract = load_json_object(
            case / "formalization_contract.yaml", "formalization contract"
        )
        report.contract = contract
    except ValidationError as exc:
        report.issues.append(str(exc))
        return report
    try:
        contract_text = (case / "formalization_contract.yaml").read_text(encoding="utf-8")
        token = UNRESOLVED_RE.search(contract_text)
        if token:
            report.issues.append(f"unresolved template token in contract: {token.group(0)}")
    except UnicodeDecodeError:
        report.issues.append("formalization contract is not UTF-8")
    _validate_contract_schema(report, contract, verification_ready)
    _validate_project(report, contract, verification_ready, allow_missing_declaration)
    _validate_freeze_and_history(report, contract, verification_ready)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Statically validate one Lean Room case.")
    parser.add_argument("--root", help="laboratory root (normally auto-discovered)")
    parser.add_argument("problem_id")
    parser.add_argument("case_id")
    parser.add_argument(
        "--verification-ready",
        action="store_true",
        help="require FROZEN LR0/LR1 state and all build bindings",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = discover_root(args.root)
        report = validate_case(
            root, args.problem_id, args.case_id, args.verification_ready
        )
        if args.json:
            print(json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True))
        else:
            for issue in report.issues:
                print(f"FAIL: {issue}")
            for warning in report.warnings:
                print(f"WARN: {warning}")
            if report.ok:
                mode = "verification-ready" if args.verification_ready else "static"
                print(f"PASS: Lean case {mode} validation")
                print(f"Source tree SHA-256: {report.source_tree_sha256}")
        return EXIT_OK if report.ok else EXIT_VALIDATION
    except LeanRoomError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
