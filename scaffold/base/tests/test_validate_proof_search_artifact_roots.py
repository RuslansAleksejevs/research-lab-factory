from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


VALIDATOR = (
    Path(__file__).resolve().parents[1] / "scripts" / "validate_proof_search.py"
)
SPEC = importlib.util.spec_from_file_location(
    "tested_validate_proof_search_artifact_roots", VALIDATOR
)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class ProofSearchArtifactRootTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="proof-search-artifact-roots-"
        )
        self.root = Path(os.path.realpath(self.temporary.name))
        self.state_path = (
            self.root
            / "problems"
            / "active"
            / "fixture"
            / "proof_search_state.yaml"
        )
        self.state_path.parent.mkdir(parents=True)
        self.state_path.write_text("{}\n", encoding="utf-8")
        self.original_root = validator.ROOT
        validator.ROOT = self.root

    def tearDown(self) -> None:
        validator.ROOT = self.original_root
        self.temporary.cleanup()

    def test_canonical_research_track_artifact_is_accepted(self) -> None:
        witness = self.root / "research" / "tracks" / "route" / "witness.md"
        witness.parent.mkdir(parents=True)
        witness.write_text("bounded route witness\n", encoding="utf-8")

        self.assertTrue(
            validator.research_artifact_exists(
                "research/tracks/route/witness.md", self.state_path
            )
        )

    def test_non_track_research_artifact_is_rejected(self) -> None:
        witness = self.root / "research" / "unscoped" / "witness.md"
        witness.parent.mkdir(parents=True)
        witness.write_text("outside the canonical track tree\n", encoding="utf-8")

        self.assertFalse(
            validator.research_artifact_exists(
                "research/unscoped/witness.md", self.state_path
            )
        )

    def test_similarly_named_noncanonical_root_is_rejected(self) -> None:
        witness = self.root / "research-copy" / "tracks" / "witness.md"
        witness.parent.mkdir(parents=True)
        witness.write_text("not in the canonical research tree\n", encoding="utf-8")

        self.assertFalse(
            validator.research_artifact_exists(
                "research-copy/tracks/witness.md", self.state_path
            )
        )

    def test_parent_traversal_to_noncanonical_root_is_rejected(self) -> None:
        witness = self.root / "unscoped" / "witness.md"
        witness.parent.mkdir(parents=True)
        witness.write_text("outside accepted artifact roots\n", encoding="utf-8")

        self.assertFalse(
            validator.research_artifact_exists(
                "research/../unscoped/witness.md", self.state_path
            )
        )

    def test_symlink_escape_is_rejected(self) -> None:
        outside = self.root.parent / f"{self.root.name}-outside-witness.md"
        outside.write_text("outside laboratory\n", encoding="utf-8")
        try:
            link = self.root / "research" / "tracks" / "escaped.md"
            link.parent.mkdir(parents=True)
            link.symlink_to(outside)

            self.assertFalse(
                validator.research_artifact_exists(
                    "research/tracks/escaped.md", self.state_path
                )
            )
        finally:
            outside.unlink(missing_ok=True)

    def test_readme_remains_navigation_not_evidence(self) -> None:
        readme = self.root / "research" / "tracks" / "README.md"
        readme.parent.mkdir(parents=True)
        readme.write_text("navigation only\n", encoding="utf-8")

        self.assertFalse(
            validator.research_artifact_exists(
                "research/tracks/README.md", self.state_path
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
