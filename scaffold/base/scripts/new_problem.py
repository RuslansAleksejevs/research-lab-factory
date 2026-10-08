#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import unicodedata
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_RELATIVE = Path("problems/templates/problem_dossier")
TOKEN_PATTERN = re.compile(r"\{\{(TITLE|TRACK|DATE|PROBLEM_ID|STATEMENT)\}\}")
RENDERED_SUFFIXES = {".md", ".yaml", ".json", ".txt", ".tex", ".bib", ".toml"}
JSON_COMPATIBLE_SUFFIXES = {".json", ".yaml"}
MULTILINE_TEXT_SUFFIXES = {".md", ".txt"}
SLUG_BASE_MAX_BYTES = 120
SLUG_HASH_LENGTH = 10


class ProblemCreationError(RuntimeError):
    pass


def normalized_title(value: str) -> str:
    title = value.strip()
    if not title:
        raise ProblemCreationError("Problem title is required")
    if len(title.splitlines()) != 1 or any(
        character in {"\r", "\n", "\u2028", "\u2029"}
        or unicodedata.category(character) == "Cc"
        for character in title
    ):
        raise ProblemCreationError("Problem title must be a safe single line")
    if TOKEN_PATTERN.search(title):
        raise ProblemCreationError("Problem title contains a reserved template token")
    return title


def truncate_utf8(text: str, max_bytes: int) -> str:
    result: List[str] = []
    used = 0
    for character in text:
        size = len(character.encode("utf-8"))
        if used + size > max_bytes:
            break
        result.append(character)
        used += size
    return "".join(result).rstrip("-")


def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).strip().casefold()
    characters: List[str] = []
    separator_pending = False
    for character in normalized:
        if character.isalnum():
            if separator_pending and characters:
                characters.append("-")
            characters.append(character)
            separator_pending = False
        elif characters:
            separator_pending = True
    base = "".join(characters).strip("-")
    shortened = truncate_utf8(base, SLUG_BASE_MAX_BYTES)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:SLUG_HASH_LENGTH]
    needs_suffix = not shortened or shortened != base or any(ord(character) > 127 for character in normalized)
    if not shortened:
        return f"problem-{digest}"
    return f"{shortened}-{digest}" if needs_suffix else shortened


def load_profile(root: Path) -> Dict[str, object]:
    path = root / "LAB_PROFILE.json"
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ProblemCreationError(f"Cannot parse {path}: {exc}") from exc
    if not isinstance(profile, dict):
        raise ProblemCreationError("LAB_PROFILE.json must contain an object")
    return profile


def valid_tracks(root: Path) -> List[str]:
    profile = load_profile(root)
    research = profile.get("research")
    if not isinstance(research, dict):
        raise ProblemCreationError("LAB_PROFILE.json has no research object")
    tracks = research.get("tracks")
    if not isinstance(tracks, list):
        raise ProblemCreationError("LAB_PROFILE.json research.tracks must be an array")
    result = [item.get("id") for item in tracks if isinstance(item, dict) and isinstance(item.get("id"), str)]
    if not result:
        raise ProblemCreationError("LAB_PROFILE.json declares no valid tracks")
    return result


def load_research_state(root: Path) -> Dict[str, object]:
    path = root / "knowledge/research_state.yaml"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ProblemCreationError(f"Cannot parse {path}: {exc}") from exc
    if not isinstance(state, dict):
        raise ProblemCreationError("research_state.yaml must contain an object")
    active = state.get("active_problem_ids")
    if not isinstance(active, list) or not all(isinstance(item, str) for item in active):
        raise ProblemCreationError("research_state.active_problem_ids must be an array of strings")
    return state


def save_research_state(root: Path, state: Dict[str, object]) -> None:
    path = root / "knowledge/research_state.yaml"
    handle, temporary_name = tempfile.mkstemp(prefix=".research-state-", suffix=".json", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            output.write(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def scan_template(template: Path) -> None:
    if not template.is_dir() or template.is_symlink():
        raise ProblemCreationError(f"Missing or unsafe problem template: {template}")
    for path in template.rglob("*"):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ProblemCreationError(f"Symlink in problem template: {path}")
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise ProblemCreationError(f"Special file in problem template: {path}")


def render_file(path: Path, tokens: Dict[str, str]) -> None:
    suffix = path.suffix.lower()
    if suffix not in RENDERED_SUFFIXES:
        return
    text = path.read_text(encoding="utf-8")

    if suffix in JSON_COMPATIBLE_SUFFIXES:
        if any(match.group(1) == "STATEMENT" for match in TOKEN_PATTERN.finditer(text)):
            raise ProblemCreationError(
                f"STATEMENT token is allowed only in Markdown/text templates: {path}"
            )

        def replace_json_string_content(match: re.Match[str]) -> str:
            # Files with .yaml suffixes in this scaffold are deliberately JSON
            # documents. Tokens occur inside JSON string literals, so insert an
            # escaped string fragment and validate the complete document below.
            return json.dumps(tokens[match.group(1)], ensure_ascii=False)[1:-1]

        text = TOKEN_PATTERN.sub(replace_json_string_content, text)
    else:
        if suffix not in MULTILINE_TEXT_SUFFIXES and any(
            match.group(1) == "STATEMENT" for match in TOKEN_PATTERN.finditer(text)
        ):
            raise ProblemCreationError(
                f"STATEMENT token is allowed only in Markdown/text templates: {path}"
            )
        text = TOKEN_PATTERN.sub(lambda match: tokens[match.group(1)], text)

    remaining = TOKEN_PATTERN.findall(text)
    if remaining:
        raise ProblemCreationError(f"Unresolved problem tokens in {path}: {remaining}")
    if suffix in JSON_COMPATIBLE_SUFFIXES:
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProblemCreationError(f"Rendered structured template is invalid: {path}: {exc}") from exc
    path.write_text(text, encoding="utf-8")


def publish_directory_noreplace(stage: Path, target: Path) -> None:
    """Atomically publish a directory without replacing an existing target."""
    if os.name == "nt":
        try:
            os.rename(stage, target)
        except FileExistsError as exc:
            raise ProblemCreationError(f"Problem dossier already exists: {target}") from exc
        except OSError as exc:
            raise ProblemCreationError(f"Atomic dossier publication failed: {exc}") from exc
        return

    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(stage)
    target_bytes = os.fsencode(target)
    if sys.platform == "darwin":
        try:
            rename_noreplace = libc.renamex_np
        except AttributeError as exc:
            raise ProblemCreationError("Atomic no-clobber publication is unavailable") from exc
        rename_noreplace.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        rename_noreplace.restype = ctypes.c_int
        result = rename_noreplace(source_bytes, target_bytes, 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        try:
            rename_noreplace = libc.renameat2
        except AttributeError as exc:
            raise ProblemCreationError("Atomic no-clobber publication is unavailable") from exc
        rename_noreplace.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename_noreplace.restype = ctypes.c_int
        result = rename_noreplace(-100, source_bytes, -100, target_bytes, 1)
    else:
        raise ProblemCreationError(
            f"Atomic no-clobber publication is unsupported on {sys.platform}"
        )

    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise ProblemCreationError(f"Problem dossier already exists: {target}")
    raise ProblemCreationError(
        f"Atomic dossier publication failed: {os.strerror(error_number)}"
    )


def create_problem(
    root: Path,
    title: str,
    track: str,
    statement: str = "To be formulated precisely.",
    date_override: Optional[str] = None,
) -> Path:
    title = normalized_title(title)
    if TOKEN_PATTERN.search(statement):
        raise ProblemCreationError("Problem statement contains a reserved template token")
    tracks = valid_tracks(root)
    research_state = load_research_state(root)
    if track not in tracks:
        raise ProblemCreationError(f"Invalid track {track!r}; valid tracks: {', '.join(tracks)}")
    today = date_override or date.today().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", today):
        raise ProblemCreationError("Date must use YYYY-MM-DD")
    problem_id = f"{today.replace('-', '')}-{slugify(title)}"
    active = root / "problems/active"
    target = active / problem_id
    if target.exists() or target.is_symlink():
        raise ProblemCreationError(f"Problem dossier already exists: {target}")
    template = root / TEMPLATE_RELATIVE
    scan_template(template)
    active.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".new-problem-", dir=str(active)))
    try:
        # Preserve any raced-in link as a link so the staged-template scan
        # rejects it instead of dereferencing external content.
        shutil.copytree(template, stage, dirs_exist_ok=True, copy_function=shutil.copy2, symlinks=True)
        scan_template(stage)
        tokens = {
            "TITLE": title,
            "TRACK": track,
            "DATE": today,
            "PROBLEM_ID": problem_id,
            "STATEMENT": statement if statement.strip() else "To be formulated precisely.",
        }
        for path in stage.rglob("*"):
            if path.is_file():
                render_file(path, tokens)
        publish_directory_noreplace(stage, target)
        stage = None  # type: ignore[assignment]
        try:
            active = list(research_state.get("active_problem_ids", []))
            active.append(problem_id)
            research_state["active_problem_ids"] = sorted(set(active))
            priorities = research_state.get("current_priorities")
            if isinstance(priorities, list) and not priorities:
                research_state["current_priorities"] = [
                    f"Review, type, and freeze the target in {problem_id}"
                ]
            save_research_state(root, research_state)
        except Exception:
            if target.exists():
                shutil.rmtree(target)
            raise
        return target
    finally:
        if stage is not None and stage.exists():
            shutil.rmtree(stage)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an article-scoped mathematical problem dossier.")
    parser.add_argument("--title", required=True)
    parser.add_argument("--track", default="")
    parser.add_argument("--statement", default="To be formulated precisely.")
    parser.add_argument("--date", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        profile = load_profile(ROOT)
        research = profile.get("research", {})
        default_track = research.get("default_track") if isinstance(research, dict) else None
        track = args.track.strip() or (default_track if isinstance(default_track, str) else "")
        today = args.date.strip() or date.today().isoformat()
        title = normalized_title(args.title)
        problem_id = f"{today.replace('-', '')}-{slugify(title)}"
        if args.dry_run:
            if track not in valid_tracks(ROOT):
                raise ProblemCreationError(f"Invalid track {track!r}")
            print((ROOT / "problems/active" / problem_id).relative_to(ROOT))
            return 0
        target = create_problem(ROOT, title, track, args.statement, today)
        print(target.relative_to(ROOT))
        return 0
    except ProblemCreationError as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
