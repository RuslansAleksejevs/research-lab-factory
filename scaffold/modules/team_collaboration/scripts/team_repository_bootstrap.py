#!/usr/bin/env python3
"""Hash-bound, explicit repository bootstrap for a configured team laboratory.

``plan`` and ``status`` never execute Git, ``gh``, or any network operation.
``apply`` is the only execution path and requires a byte-exact plan digest, the
configured steward, a literal confirmation, inventory drift checks, and (for a
public repository) a unanimous disclosure review. Authentication remains an
external concern of the installed ``gh`` CLI; this program accepts and records
no token or credential.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from team_collaboration import (
    CollaborationError,
    FileLock,
    HANDLE_RE,
    SHA256_RE,
    artifact_bindings,
    exact_consensus,
    json_bytes,
    load_json_file,
    load_team,
    member_ids,
    real_directory,
    regular_file,
    relative_path,
    require_member,
    root_path,
    safe_line,
    sha256_bytes,
    sha256_file,
    update_summary,
    utc_now,
    validate_id,
    validate_timestamp,
    write_new,
)


REPOSITORY_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._/-]{0,98}[A-Za-z0-9])?$")
EMAIL_RE = re.compile(r"^[^\s@<>]+@[^\s@<>]+$")
PLAN_VISIBILITIES = {"LOCAL_ONLY", "PRIVATE", "PUBLIC"}
EXCLUDED_PREFIXES = (
    Path("collaboration/repository/plans"),
    Path("collaboration/repository/reviews"),
    Path("collaboration/repository/receipts"),
)
EXCLUDED_FILES = {
    Path("collaboration/.team-collaboration.lock"),
    Path("knowledge/.control-room-summary.lock"),
    Path("knowledge/control_room_summary.json"),
}


def _is_excluded(relative: Path) -> bool:
    if relative in EXCLUDED_FILES:
        return True
    return any(relative == prefix or prefix in relative.parents for prefix in EXCLUDED_PREFIXES)


def _safe_tree_name(name: str, label: str) -> None:
    if name in {"", ".", ".."} or any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise CollaborationError(f"unsafe {label} name in repository baseline")


def baseline_inventory(root: Path) -> List[Dict[str, Any]]:
    """Inventory all baseline files while rejecting links and special files."""

    result: List[Dict[str, Any]] = []
    stack: List[Path] = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(os.scandir(str(directory)), key=lambda entry: entry.name)
        except OSError as exc:
            raise CollaborationError(f"cannot scan repository baseline: {exc}") from exc
        for entry in entries:
            _safe_tree_name(entry.name, "path component")
            path = Path(entry.path)
            relative = path.relative_to(root)
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise CollaborationError(f"cannot inspect baseline entry {relative.as_posix()}: {exc}") from exc
            if stat.S_ISLNK(info.st_mode):
                raise CollaborationError(f"repository baseline contains a symlink: {relative.as_posix()}")
            if relative.parts and relative.parts[0] == ".git":
                raise CollaborationError("laboratory already contains .git; repository bootstrap is not applicable")
            if _is_excluded(relative):
                # The exclusion itself must still be a real directory/file; its
                # append-only contents are operational records, not baseline.
                if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                    raise CollaborationError(f"excluded baseline entry is special: {relative.as_posix()}")
                continue
            if stat.S_ISDIR(info.st_mode):
                stack.append(path)
            elif stat.S_ISREG(info.st_mode):
                result.append(
                    {
                        "path": relative.as_posix(),
                        "sha256": sha256_file(path),
                        "bytes": info.st_size,
                    }
                )
            else:
                raise CollaborationError(f"repository baseline contains a special file: {relative.as_posix()}")
    return sorted(result, key=lambda item: item["path"])


def inventory_digest(inventory: List[Dict[str, Any]]) -> str:
    data = json.dumps(inventory, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return sha256_bytes(data)


def _validate_repository_name(value: str) -> str:
    if not REPOSITORY_NAME_RE.fullmatch(value) or value in {".", ".."} or value.endswith(".git"):
        raise CollaborationError("repository name is invalid")
    return value


def _validate_branch(value: str) -> str:
    if (
        not BRANCH_RE.fullmatch(value)
        or ".." in value
        or "//" in value
        or value.endswith((".", "/"))
        or value.startswith("/")
    ):
        raise CollaborationError("default branch name is invalid")
    return value


def _validate_email(value: str) -> str:
    email = safe_line(value, "Git author email", maximum=254)
    if not EMAIL_RE.fullmatch(email):
        raise CollaborationError("Git author email is invalid")
    return email


def _configured_handles(team: Dict[str, Any]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for member in team["members"]:
        handle = member["github_handle"]
        if handle is not None:
            result[str(member["id"])] = str(handle)
    return result


def _validate_remote_identity(
    team: Dict[str, Any], owner_handle: Optional[str], collaborator_handles: Sequence[str]
) -> Tuple[Dict[str, str], List[Dict[str, str]]]:
    handles = _configured_handles(team)
    steward = str(team["steward_id"])
    owner = owner_handle or ""
    if not HANDLE_RE.fullmatch(owner):
        raise CollaborationError("owner handle must be a valid exact GitHub handle")
    configured_owner = handles.get(steward)
    if configured_owner is not None and owner.casefold() != configured_owner.casefold():
        raise CollaborationError("owner handle conflicts with the steward handle fixed in the profile")
    collaborator_members = [item for item in member_ids(team) if item != steward]
    supplied = list(collaborator_handles)
    if len(supplied) != len(collaborator_members):
        raise CollaborationError(
            "supply one collaborator handle per non-steward member in collaboration.members order"
        )
    if any(not HANDLE_RE.fullmatch(item) for item in supplied):
        raise CollaborationError("a collaborator GitHub handle is invalid")
    all_handles = [owner, *supplied]
    if len({item.casefold() for item in all_handles}) != len(all_handles):
        raise CollaborationError("owner and collaborator GitHub handles must be unique")
    mappings: List[Dict[str, str]] = []
    for member_id, supplied_handle in zip(collaborator_members, supplied):
        configured = handles.get(member_id)
        if configured is not None and supplied_handle.casefold() != configured.casefold():
            raise CollaborationError(
                f"collaborator handle conflicts with the profile handle for member {member_id}"
            )
        mappings.append({"member_id": member_id, "handle": supplied_handle})
    return {"member_id": steward, "handle": owner}, mappings


def _profile_sha(root: Path) -> str:
    return sha256_file(regular_file(root, Path("LAB_PROFILE.json"), "LAB_PROFILE"))


def _team_sha(root: Path) -> str:
    return sha256_file(regular_file(root, Path("collaboration/team.json"), "team configuration"))


def create_plan(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    team = load_team(root)
    actor = require_member(team, args.created_by, "plan creator")
    if actor != team["steward_id"]:
        raise CollaborationError("only the configured steward may create a repository plan")
    plan_id = validate_id(args.plan_id, "plan ID")
    visibility = args.visibility
    if visibility not in PLAN_VISIBILITIES:
        raise CollaborationError("repository visibility must be explicitly LOCAL_ONLY, PRIVATE, or PUBLIC")
    profile_visibility = team["repository"]["visibility"]
    if profile_visibility in {"PRIVATE", "PUBLIC"} and visibility != profile_visibility:
        raise CollaborationError("plan visibility conflicts with the profile's reviewed repository intent")
    name = _validate_repository_name(args.repository_name)
    branch = _validate_branch(args.default_branch)
    author_name = safe_line(args.git_author_name, "Git author name", maximum=200)
    author_email = _validate_email(args.git_author_email)
    if visibility == "LOCAL_ONLY":
        if args.owner_handle is not None or args.collaborator_handle:
            raise CollaborationError("LOCAL_ONLY plan cannot contain GitHub handles")
        owner: Optional[Dict[str, str]] = None
        collaborators: List[Dict[str, str]] = []
    else:
        owner, collaborators = _validate_remote_identity(team, args.owner_handle, args.collaborator_handle)
    inventory = baseline_inventory(root)
    if not inventory:
        raise CollaborationError("repository baseline is empty")
    created_at = validate_timestamp(args.created_at or utc_now(), "plan created-at")
    value: Dict[str, Any] = {
        "schema_version": 1,
        "record_type": "team_repository_bootstrap_plan",
        "plan_id": plan_id,
        "created_at": created_at,
        "created_by_member_id": actor,
        "profile_sha256": _profile_sha(root),
        "team_configuration_sha256": _team_sha(root),
        "repository": {
            "provider": "LOCAL_GIT" if visibility == "LOCAL_ONLY" else "GITHUB",
            "visibility": visibility,
            "name": name,
            "owner": owner,
            "full_name": None if owner is None else f"{owner['handle']}/{name}",
            "collaborators": collaborators,
        },
        "git": {
            "default_branch": branch,
            "author_name": author_name,
            "author_email": author_email,
            "baseline_commit_message": safe_line(args.baseline_commit_message, "baseline commit message", maximum=300),
        },
        "baseline": {
            "files": inventory,
            "inventory_sha256": inventory_digest(inventory),
            "excluded_operational_prefixes": [item.as_posix() + "/" for item in EXCLUDED_PREFIXES],
            "excluded_derived_files": sorted(item.as_posix() for item in EXCLUDED_FILES),
        },
        "public_disclosure_review_required": visibility == "PUBLIC",
        "apply_requirements": {
            "exact_plan_sha256": True,
            "steward_confirmation_literal": "APPLY_EXACT_PLAN",
            "reject_inventory_drift": True,
        },
        "credentials": "NOT_ACCEPTED_OR_STORED",
        "generation_or_automatic_apply": False,
    }
    relative = Path("collaboration/repository/plans") / f"{plan_id}.json"
    path = write_new(root, relative, json_bytes(value), "repository bootstrap plan")
    plan_sha = sha256_file(path)
    update_summary(
        root,
        lambda summary: summary.__setitem__(
            "repository", {"state": "PENDING", "visibility": visibility}
        ),
    )
    return {
        "status": "PLANNED",
        "plan": relative.as_posix(),
        "plan_sha256": plan_sha,
        "visibility": visibility,
        "file_count": len(inventory),
        "git_initialized": False,
        "external_actions_performed": False,
    }


def _load_plan(root: Path, value: str) -> Tuple[Dict[str, Any], Path, Path]:
    relative = relative_path(value, "repository plan")
    expected_parent = Path("collaboration/repository/plans")
    if relative.parent != expected_parent or relative.suffix != ".json":
        raise CollaborationError("repository plan must be a direct JSON child of collaboration/repository/plans")
    plan = load_json_file(root, relative, "repository bootstrap plan")
    required = {
        "schema_version", "record_type", "plan_id", "created_at", "created_by_member_id",
        "profile_sha256", "team_configuration_sha256", "repository", "git", "baseline",
        "public_disclosure_review_required", "apply_requirements", "credentials",
        "generation_or_automatic_apply",
    }
    if set(plan) != required or plan.get("schema_version") != 1 or plan.get("record_type") != "team_repository_bootstrap_plan":
        raise CollaborationError("repository plan has an unsupported shape")
    plan_id = validate_id(str(plan.get("plan_id", "")), "stored plan ID")
    if relative.stem != plan_id:
        raise CollaborationError("repository plan filename disagrees with plan ID")
    validate_timestamp(str(plan.get("created_at", "")), "stored plan created_at")
    for key in ("profile_sha256", "team_configuration_sha256"):
        if not isinstance(plan.get(key), str) or not SHA256_RE.fullmatch(plan[key]):
            raise CollaborationError(f"repository plan {key} is invalid")
    repository = plan.get("repository")
    if not isinstance(repository, dict) or set(repository) != {
        "provider", "visibility", "name", "owner", "full_name", "collaborators"
    }:
        raise CollaborationError("repository plan repository object is invalid")
    visibility = repository.get("visibility")
    if visibility not in PLAN_VISIBILITIES:
        raise CollaborationError("repository plan visibility is invalid")
    name_value = repository.get("name")
    if not isinstance(name_value, str) or name_value != _validate_repository_name(name_value):
        raise CollaborationError("repository plan name is invalid")
    team = load_team(root)
    creator = require_member(team, str(plan.get("created_by_member_id", "")), "stored plan creator")
    if creator != team["steward_id"]:
        raise CollaborationError("stored repository plan creator is not the configured steward")
    profile_visibility = team["repository"]["visibility"]
    if profile_visibility in {"PRIVATE", "PUBLIC"} and visibility != profile_visibility:
        raise CollaborationError("stored plan visibility conflicts with profile intent")
    if visibility == "LOCAL_ONLY":
        if repository != {
            "provider": "LOCAL_GIT",
            "visibility": "LOCAL_ONLY",
            "name": name_value,
            "owner": None,
            "full_name": None,
            "collaborators": [],
        }:
            raise CollaborationError("LOCAL_ONLY repository plan fields are invalid")
    else:
        owner_value = repository.get("owner")
        collaborators_value = repository.get("collaborators")
        if (
            repository.get("provider") != "GITHUB"
            or not isinstance(owner_value, dict)
            or set(owner_value) != {"member_id", "handle"}
            or not isinstance(collaborators_value, list)
            or not all(isinstance(item, dict) and set(item) == {"member_id", "handle"} for item in collaborators_value)
        ):
            raise CollaborationError("remote repository member-handle mapping is invalid")
        canonical_owner, canonical_collaborators = _validate_remote_identity(
            team,
            owner_value.get("handle") if isinstance(owner_value.get("handle"), str) else None,
            [item.get("handle", "") for item in collaborators_value],
        )
        if owner_value != canonical_owner or collaborators_value != canonical_collaborators:
            raise CollaborationError("remote repository handles are not deterministically member-bound")
        if repository.get("full_name") != f"{canonical_owner['handle']}/{name_value}":
            raise CollaborationError("remote repository full_name is inconsistent")
    git = plan.get("git")
    if not isinstance(git, dict) or set(git) != {"default_branch", "author_name", "author_email", "baseline_commit_message"}:
        raise CollaborationError("repository plan git object is invalid")
    if not all(isinstance(git.get(key), str) for key in git):
        raise CollaborationError("repository plan git values must be strings")
    _validate_branch(git["default_branch"])
    safe_line(git["author_name"], "stored Git author name", maximum=200)
    _validate_email(git["author_email"])
    safe_line(git["baseline_commit_message"], "stored commit message", maximum=300)
    baseline = plan.get("baseline")
    if not isinstance(baseline, dict) or set(baseline) != {
        "files", "inventory_sha256", "excluded_operational_prefixes", "excluded_derived_files"
    }:
        raise CollaborationError("repository plan baseline object is invalid")
    files = baseline.get("files")
    if not isinstance(files, list) or not all(isinstance(item, dict) and set(item) == {"path", "sha256", "bytes"} for item in files):
        raise CollaborationError("repository plan baseline files are invalid")
    normalized_paths: List[str] = []
    for item in files:
        path_value = item.get("path")
        digest_value = item.get("sha256")
        byte_count = item.get("bytes")
        if not isinstance(path_value, str):
            raise CollaborationError("repository plan baseline path is invalid")
        parsed = relative_path(path_value, "stored baseline file")
        if parsed.as_posix() != path_value or _is_excluded(parsed) or parsed.parts[0] == ".git":
            raise CollaborationError("repository plan baseline contains an unsafe or excluded path")
        for component in parsed.parts:
            _safe_tree_name(component, "stored path component")
        if not isinstance(digest_value, str) or not SHA256_RE.fullmatch(digest_value):
            raise CollaborationError("repository plan baseline digest is invalid")
        if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
            raise CollaborationError("repository plan baseline byte count is invalid")
        normalized_paths.append(path_value)
    if normalized_paths != sorted(normalized_paths) or len(normalized_paths) != len(set(normalized_paths)):
        raise CollaborationError("repository plan baseline paths must be sorted and unique")
    if baseline.get("inventory_sha256") != inventory_digest(files):
        raise CollaborationError("repository plan inventory digest is invalid")
    if baseline.get("excluded_operational_prefixes") != [item.as_posix() + "/" for item in EXCLUDED_PREFIXES] or baseline.get("excluded_derived_files") != sorted(item.as_posix() for item in EXCLUDED_FILES):
        raise CollaborationError("repository plan exclusions are invalid")
    exact_apply_requirements = {
        "exact_plan_sha256": True,
        "steward_confirmation_literal": "APPLY_EXACT_PLAN",
        "reject_inventory_drift": True,
    }
    if plan.get("apply_requirements") != exact_apply_requirements:
        raise CollaborationError("repository plan apply requirements are invalid")
    if plan.get("public_disclosure_review_required") is not (visibility == "PUBLIC"):
        raise CollaborationError("repository plan public-disclosure requirement is invalid")
    if plan.get("credentials") != "NOT_ACCEPTED_OR_STORED" or plan.get("generation_or_automatic_apply") is not False:
        raise CollaborationError("repository plan safety declarations are invalid")
    path = root / relative
    return plan, path, relative


def _validate_disclosure_review(root: Path, value: str, plan_sha: str, team: Dict[str, Any]) -> Tuple[Dict[str, Any], Path]:
    relative = relative_path(value, "public disclosure review")
    if relative.parent != Path("collaboration/repository/reviews") or relative.suffix != ".json":
        raise CollaborationError("public disclosure review must be a direct JSON child of collaboration/repository/reviews")
    review = load_json_file(root, relative, "public disclosure review")
    if set(review) != {"schema_version", "record_type", "plan_sha256", "reviewed_at", "approved_by_member_ids", "decision", "checks"}:
        raise CollaborationError("public disclosure review has an unsupported shape")
    if review.get("schema_version") != 1 or review.get("record_type") != "public_repository_disclosure_review":
        raise CollaborationError("public disclosure review schema is invalid")
    if review.get("plan_sha256") != plan_sha:
        raise CollaborationError("public disclosure review is bound to a different plan")
    validate_timestamp(str(review.get("reviewed_at", "")), "public disclosure reviewed_at")
    exact_consensus(team, review.get("approved_by_member_ids", []), "public disclosure approvers")
    checks = review.get("checks")
    expected_checks = {"no_credentials_or_secrets", "rights_to_publish", "private_material_removed", "research_exposure_intentionally_approved"}
    if review.get("decision") != "APPROVED" or not isinstance(checks, dict) or set(checks) != expected_checks or any(checks[key] is not True for key in expected_checks):
        raise CollaborationError("public disclosure review is not unanimously approved on every required check")
    return review, root / relative


def _receipt_records(root: Path) -> List[Tuple[Dict[str, Any], Path]]:
    directory = real_directory(root, Path("collaboration/repository/receipts"), "repository receipts")
    result: List[Tuple[Dict[str, Any], Path]] = []
    for path in sorted(directory.iterdir()):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise CollaborationError(f"unsafe repository receipt entry: {path.name}")
        if path.name == "README.md":
            continue
        if path.suffix != ".json":
            raise CollaborationError(f"unexpected repository receipt entry: {path.name}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("record_type") != "team_repository_bootstrap_receipt":
            raise CollaborationError(f"invalid repository receipt: {path.name}")
        result.append((value, path))
    return result


def run_command(command: Sequence[str], root: Path, *, timeout: int = 120) -> None:
    """Execute one typed command without persisting stdout, stderr, or environment."""

    try:
        completed = subprocess.run(
            list(command), cwd=str(root), text=True, capture_output=True, timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CollaborationError(f"external command could not complete: {type(exc).__name__}") from exc
    if completed.returncode != 0:
        # Raw output may include URLs or authentication diagnostics and is never
        # copied into a receipt or raised into machine-readable output.
        raise CollaborationError(f"external command failed with exit code {completed.returncode}")


def _git_head(root: Path, git_executable: str) -> str:
    completed = subprocess.run(
        [git_executable, "rev-parse", "HEAD"], cwd=str(root), text=True,
        capture_output=True, timeout=20, check=False,
    )
    value = completed.stdout.strip()
    if completed.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40,64}", value):
        raise CollaborationError("cannot read the created baseline commit")
    return value


def _write_receipt(root: Path, plan: Dict[str, Any], plan_sha: str, attempt_id: str, value: Dict[str, Any]) -> Path:
    value.update(
        {
            "schema_version": 1,
            "record_type": "team_repository_bootstrap_receipt",
            "attempt_id": attempt_id,
            "plan_id": plan["plan_id"],
            "plan_sha256": plan_sha,
            "recorded_at": utc_now(),
            "credentials_recorded": False,
        }
    )
    relative = Path("collaboration/repository/receipts") / f"{attempt_id}.json"
    return write_new(root, relative, json_bytes(value), "repository bootstrap receipt")


def apply_plan(root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    team = load_team(root)
    actor = require_member(team, args.approved_by, "apply approver")
    if actor != team["steward_id"]:
        raise CollaborationError("only the configured steward may apply a repository plan")
    if args.confirm_external_actions != "APPLY_EXACT_PLAN":
        raise CollaborationError("apply requires --confirm-external-actions APPLY_EXACT_PLAN")
    attempt_id = validate_id(args.attempt_id, "attempt ID")
    plan, plan_path, plan_relative = _load_plan(root, args.plan)
    plan_sha = sha256_file(plan_path)
    if not SHA256_RE.fullmatch(args.approved_plan_sha256 or "") or args.approved_plan_sha256 != plan_sha:
        raise CollaborationError("approved plan SHA-256 does not match the exact plan bytes")
    if plan["created_by_member_id"] != team["steward_id"]:
        raise CollaborationError("repository plan was not created by the configured steward")
    if plan["profile_sha256"] != _profile_sha(root) or plan["team_configuration_sha256"] != _team_sha(root):
        raise CollaborationError("profile or team configuration drifted after repository planning")
    actual_inventory = baseline_inventory(root)
    if actual_inventory != plan["baseline"]["files"]:
        raise CollaborationError("repository baseline drifted after planning")
    matching_receipts = [item for item, _ in _receipt_records(root) if item.get("plan_sha256") == plan_sha]
    if matching_receipts:
        success = next((item for item in matching_receipts if item.get("outcome") == "SUCCESS"), None)
        if success is not None:
            return {"status": "ALREADY_APPLIED", "plan_sha256": plan_sha, "receipt_attempt_id": success.get("attempt_id")}
        raise CollaborationError("this plan has a failed receipt; inspect actual state and create a fresh plan")
    receipt_target = root / "collaboration/repository/receipts" / f"{attempt_id}.json"
    if receipt_target.exists() or receipt_target.is_symlink():
        raise CollaborationError("repository attempt ID already has a receipt")
    visibility = plan["repository"]["visibility"]
    review_sha: Optional[str] = None
    if visibility == "PUBLIC":
        if not args.public_disclosure_review:
            raise CollaborationError("PUBLIC apply requires an exact public disclosure review")
        _, review_path = _validate_disclosure_review(root, args.public_disclosure_review, plan_sha, team)
        review_sha = sha256_file(review_path)
    elif args.public_disclosure_review is not None:
        raise CollaborationError("a disclosure review is accepted only for PUBLIC apply")

    git_executable = shutil.which("git")
    if git_executable is None:
        raise CollaborationError("git executable is unavailable")
    gh_executable: Optional[str] = None
    if visibility in {"PRIVATE", "PUBLIC"}:
        gh_executable = shutil.which("gh")
        if gh_executable is None:
            raise CollaborationError("gh executable is unavailable for remote setup")

    steps: List[Dict[str, str]] = []
    current_step = "git_init"
    try:
        update_summary(root, lambda summary: summary.__setitem__("repository", {"state": "PENDING", "visibility": visibility}))
        run_command([git_executable, "init", "-b", plan["git"]["default_branch"]], root)
        steps.append({"step": current_step, "status": "COMPLETED"})
        current_step = "git_stage_exact_baseline"
        paths = [item["path"] for item in plan["baseline"]["files"]]
        for offset in range(0, len(paths), 100):
            run_command([git_executable, "add", "--", *paths[offset : offset + 100]], root)
        steps.append({"step": current_step, "status": "COMPLETED"})
        current_step = "git_baseline_commit"
        run_command(
            [
                git_executable,
                "-c", f"user.name={plan['git']['author_name']}",
                "-c", f"user.email={plan['git']['author_email']}",
                "commit", "--no-gpg-sign", "-m", plan["git"]["baseline_commit_message"],
            ],
            root,
        )
        steps.append({"step": current_step, "status": "COMPLETED"})
        if visibility in {"PRIVATE", "PUBLIC"}:
            assert gh_executable is not None
            current_step = "github_repository_create_and_push"
            visibility_flag = "--public" if visibility == "PUBLIC" else "--private"
            run_command(
                [
                    gh_executable, "repo", "create", plan["repository"]["full_name"],
                    visibility_flag, "--source", str(root), "--remote", "origin", "--push",
                ],
                root,
            )
            steps.append({"step": current_step, "status": "COMPLETED"})
            for collaborator in plan["repository"]["collaborators"]:
                handle = collaborator["handle"]
                current_step = f"github_invite:{handle}"
                run_command(
                    [
                        gh_executable, "api", "--method", "PUT",
                        f"repos/{plan['repository']['full_name']}/collaborators/{handle}",
                        "-f", "permission=push",
                    ],
                    root,
                )
                steps.append({"step": current_step, "status": "COMPLETED"})
        commit_sha = _git_head(root, git_executable)
    except CollaborationError as exc:
        steps.append({"step": current_step, "status": "FAILED"})
        receipt = _write_receipt(
            root, plan, plan_sha, attempt_id,
            {
                "outcome": "ERROR",
                "approved_by_member_id": actor,
                "visibility": visibility,
                "completed_steps": steps,
                "failed_step": current_step,
                "error_class": type(exc).__name__,
                "public_disclosure_review_sha256": review_sha,
                "baseline_commit_sha": None,
                "external_state_may_be_partial": bool(steps),
            },
        )
        update_summary(root, lambda summary: summary.__setitem__("repository", {"state": "ERROR", "visibility": visibility}))
        raise CollaborationError(f"repository apply failed at {current_step}; inspect receipt {receipt.name}") from exc

    receipt = _write_receipt(
        root, plan, plan_sha, attempt_id,
        {
            "outcome": "SUCCESS",
            "approved_by_member_id": actor,
            "visibility": visibility,
            "completed_steps": steps,
            "failed_step": None,
            "error_class": None,
            "public_disclosure_review_sha256": review_sha,
            "baseline_commit_sha": commit_sha,
            "external_state_may_be_partial": False,
        },
    )
    state = "LOCAL_ONLY" if visibility == "LOCAL_ONLY" else "CONNECTED"
    update_summary(root, lambda summary: summary.__setitem__("repository", {"state": state, "visibility": visibility}))
    return {
        "status": state,
        "plan": plan_relative.as_posix(),
        "plan_sha256": plan_sha,
        "receipt": receipt.relative_to(root).as_posix(),
        "baseline_commit_sha": commit_sha,
    }


def repository_status(root: Path) -> Dict[str, Any]:
    team = load_team(root)
    summary = load_json_file(root, Path("knowledge/control_room_summary.json"), "Control Room summary")
    # update_summary's strict validator is intentionally reused without a write.
    from team_collaboration import validate_summary

    validate_summary(summary)
    git_path = root / ".git"
    if git_path.is_symlink():
        raise CollaborationError(".git cannot be a symlink")
    if git_path.exists() and not git_path.is_dir():
        raise CollaborationError(".git must be a real directory when present")
    plan_directory = real_directory(root, Path("collaboration/repository/plans"), "repository plans")
    plan_count = sum(1 for path in plan_directory.iterdir() if path.is_file() and not path.is_symlink() and path.suffix == ".json")
    receipts = _receipt_records(root)
    latest = receipts[-1][0] if receipts else None
    return {
        "status": "OK",
        "configured_member_count": len(member_ids(team)),
        "summary_repository": summary["repository"],
        "git_directory_present": git_path.is_dir(),
        "plan_count": plan_count,
        "receipt_count": len(receipts),
        "latest_receipt": None if latest is None else {
            "attempt_id": latest.get("attempt_id"),
            "outcome": latest.get("outcome"),
            "recorded_at": latest.get("recorded_at"),
        },
        "external_actions_performed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="laboratory root")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--plan-id", required=True)
    plan.add_argument("--created-by", required=True)
    plan.add_argument("--created-at")
    plan.add_argument("--visibility", choices=sorted(PLAN_VISIBILITIES), required=True)
    plan.add_argument("--repository-name", required=True)
    plan.add_argument("--owner-handle")
    plan.add_argument(
        "--collaborator-handle",
        action="append",
        default=[],
        help="repeat once per non-steward member, in collaboration.members order",
    )
    plan.add_argument("--default-branch", default="main")
    plan.add_argument("--git-author-name", required=True)
    plan.add_argument("--git-author-email", required=True)
    plan.add_argument("--baseline-commit-message", default="Initialize research laboratory")

    apply = sub.add_parser("apply")
    apply.add_argument("--plan", required=True)
    apply.add_argument("--approved-plan-sha256", required=True)
    apply.add_argument("--approved-by", required=True)
    apply.add_argument("--attempt-id", required=True)
    apply.add_argument("--confirm-external-actions", required=True)
    apply.add_argument("--public-disclosure-review")

    sub.add_parser("status")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = root_path(args.root)
        if args.command == "status":
            result = repository_status(root)
        else:
            real_directory(root, Path("collaboration"), "collaboration directory")
            with FileLock(root / "collaboration/.team-collaboration.lock", "team collaboration"):
                result = create_plan(root, args) if args.command == "plan" else apply_plan(root, args)
    except CollaborationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(result.get("status", "OK"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
