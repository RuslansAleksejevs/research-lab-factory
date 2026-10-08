#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = MODULE_ROOT / "scripts/chatgpt_pro_bridge.py"
PROMPT_TEMPLATE = MODULE_ROOT / "templates/chatgpt_pro_browser_prompt.md"
INTAKE_TEMPLATE = MODULE_ROOT / "templates/chatgpt_pro_response_intake.md"


def launch_prompt(problem_id: str = "20000101-example") -> str:
    digest = "a" * 64
    return f"""# Parallel External-Model Launch Prompt

## Run identity and exposure

- Problem ID: {problem_id}
- Frozen target ID and SHA-256: target-v1 {digest}
- Candidate ID and SHA-256, if auditing: candidate-v1 {digest}
- Orchestration profile: `FULL`
- Role: ADVERSARIAL_VERIFIER
- Context mode: VERIFICATION
- Approach family or instruction to propose a new mechanism: audit the supplied route
- Prior artifacts visible: candidate proof and source digest
- Favored route disclosed: yes
- Affirmative-answer prior supplied: no

## Exact task

For every object X satisfying hypotheses H1 and H2, determine whether the
canonical map f_X is an isomorphism. Preserve the stated coefficient ring,
grading convention, naturality requirement, and all quantifiers. Either give a
complete proof, a checked counterexample, or the exact unresolved obligation.

## Project-specific checks

Check domains and codomains, degree shifts, coefficient changes, naturality,
empty objects, and every use of duality.

## Files supplied

No source body is supplied. Exact source statements needed for the task are
quoted in this capsule and bound locally by SHA-256.

## Known state

- Closed inputs: the construction of f_X.
- Open obligations: injectivity and compatibility with the grading.
- Known counterexamples or boundary failures: H2 cannot be dropped.
- Blocked mechanism families visible to this run: none.
- Anti-goals and non-solutions: do not prove only finite-dimensional X.

## Requested output

Return the exact target restatement, verdict, auditable argument, load-bearing
steps, source gaps, adversarial checks, strongest result, exact gap, and intake
priorities. Do not silently weaken the target or self-certify.
"""


class ChatGPTProBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="chatgpt-pro-bridge-test-")
        self.root = Path(self.temp.name)
        (self.root / "templates").mkdir(parents=True)
        shutil.copy2(PROMPT_TEMPLATE, self.root / "templates/chatgpt_pro_browser_prompt.md")
        shutil.copy2(INTAKE_TEMPLATE, self.root / "templates/chatgpt_pro_response_intake.md")
        (self.root / "problems/active/example").mkdir(parents=True)
        (self.root / "sources").mkdir(parents=True)
        (self.root / "knowledge").mkdir(parents=True)
        self.launch = self.root / "problems/active/example/parallel_llm_launch_prompt.md"
        self.launch.write_text(launch_prompt(), encoding="utf-8")
        self.source = self.root / "sources/primary.txt"
        self.source.write_text("Theorem 2. Exact source statement.\n", encoding="utf-8")
        self.ledger = self.root / "knowledge/results_ledger.yaml"
        self.ledger.write_text('{"results": [], "sentinel": "unchanged"}\n', encoding="utf-8")
        self.run_counter = 0

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_id(self, label: str) -> str:
        self.run_counter += 1
        return f"20000101T0000{self.run_counter:02d}Z-{label}"

    def command(self, *args: str, expect: int = 0) -> dict:
        process = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), "--json", *args],
            cwd=str(self.root),
            text=True,
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(
            process.returncode,
            expect,
            msg=f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}",
        )
        return json.loads(process.stdout)

    def prepare(self, run_id: str, expect: int = 0) -> dict:
        return self.command(
            "prepare",
            "--run-id",
            run_id,
            "--problem-id",
            "20000101-example",
            "--role",
            "ADVERSARIAL_VERIFIER",
            "--context-mode",
            "VERIFICATION",
            "--launch-prompt",
            "problems/active/example/parallel_llm_launch_prompt.md",
            "--source-file",
            "sources/primary.txt",
            expect=expect,
        )

    def approve(self, run_id: str, expect: int = 0) -> dict:
        return self.command(
            "approve",
            "--run-id",
            run_id,
            "--actor",
            "user",
            "--reason",
            "explicit test authorization for this exact prompt",
            expect=expect,
        )

    def dispatch(self, run_id: str, label: str = "GPT-5.6 Sol Pro", expect: int = 0) -> dict:
        return self.command(
            "record-dispatch",
            "--run-id",
            run_id,
            "--actor",
            "codex-browser",
            "--confirmed-model",
            "gpt-5.6-sol-pro",
            "--visible-model-label",
            label,
            "--chat-url",
            f"https://chatgpt.com/c/{run_id}",
            expect=expect,
        )

    def test_complete_lifecycle_is_hash_bound_and_nonpromoting(self) -> None:
        run_id = self.run_id("lifecycle")
        initial_ledger = self.ledger.read_bytes()
        prepared = self.prepare(run_id)
        self.assertEqual(prepared["state"], "PREPARED")
        self.assertFalse(prepared["mathematical_status_changed"])

        denied = self.dispatch(run_id, expect=2)
        self.assertIn("lacks explicit approval", denied["error"])
        self.assertFalse((self.root / f"runs/external_llm/chatgpt_pro/{run_id}/dispatch.json").exists())

        approved = self.approve(run_id)
        self.assertEqual(approved["state"], "APPROVED")
        dispatched = self.dispatch(run_id)
        self.assertEqual(dispatched["state"], "DISPATCHED")

        run_dir = self.root / f"runs/external_llm/chatgpt_pro/{run_id}"
        (run_dir / "raw_response.md").write_text(
            "# External Pro Report\n\n## Run and verdict\n"
            f"Run ID: `{run_id}`. Verdict: `GAP_FOUND`.\n\n"
            "## Exact target restatement\nThe target retains H1 and H2.\n\n"
            "## Result\nThe proposed argument does not establish injectivity.\n\n"
            "## Load-bearing steps\nThe kernel calculation is missing.\n\n"
            "## Source and dependency audit\nNo external theorem was verified.\n\n"
            "## Adversarial audit\nDropping H2 gives a boundary failure.\n\n"
            "## Remaining gap\nGS3: prove the kernel vanishes.\n\n"
            "## Codex intake priorities\nCheck the kernel calculation first.\n",
            encoding="utf-8",
        )
        imported = self.command("import-response", "--run-id", run_id)
        self.assertEqual(imported["state"], "RESPONSE_CAPTURED_UNVERIFIED")
        self.assertFalse(imported["mathematical_status_changed"])
        response_manifest = json.loads((run_dir / "response_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(response_manifest["status"], "UNVERIFIED_EXTERNAL_OUTPUT")
        self.assertIs(response_manifest["claim_status_changes_authorized"], False)
        self.assertEqual(self.ledger.read_bytes(), initial_ledger)

    def test_source_drift_blocks_approval(self) -> None:
        run_id = self.run_id("source-drift")
        self.prepare(run_id)
        self.source.write_text("Changed theorem bytes.\n", encoding="utf-8")
        result = self.approve(run_id, expect=2)
        self.assertIn("source bytes drifted", result["error"])

    def test_prompt_tampering_invalidates_approval_and_dispatch(self) -> None:
        run_id = self.run_id("prompt-drift")
        self.prepare(run_id)
        self.approve(run_id)
        prompt = self.root / f"runs/external_llm/chatgpt_pro/{run_id}/prompt.txt"
        prompt.write_text(prompt.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")
        result = self.dispatch(run_id, expect=2)
        self.assertIn("no longer matches", result["error"])

    def test_non_pro_visible_label_is_rejected_without_fallback(self) -> None:
        run_id = self.run_id("no-fallback")
        self.prepare(run_id)
        self.approve(run_id)
        result = self.dispatch(run_id, label="Extra High", expect=2)
        self.assertIn("does not identify a Pro option", result["error"])
        self.assertFalse((self.root / f"runs/external_llm/chatgpt_pro/{run_id}/dispatch.json").exists())

    def test_non_chatgpt_dispatch_url_is_rejected(self) -> None:
        run_id = self.run_id("url-boundary")
        self.prepare(run_id)
        self.approve(run_id)
        result = self.command(
            "record-dispatch",
            "--run-id",
            run_id,
            "--actor",
            "codex-browser",
            "--confirmed-model",
            "gpt-5.6-sol-pro",
            "--visible-model-label",
            "Pro",
            "--chat-url",
            "https://example.com/fake-chat",
            expect=2,
        )
        self.assertIn("chatgpt.com", result["error"])

    def test_duplicate_run_never_overwrites_existing_packet(self) -> None:
        run_id = self.run_id("no-overwrite")
        self.prepare(run_id)
        prompt = self.root / f"runs/external_llm/chatgpt_pro/{run_id}/prompt.txt"
        original = prompt.read_bytes()
        result = self.prepare(run_id, expect=2)
        self.assertIn("run already exists", result["error"])
        self.assertEqual(prompt.read_bytes(), original)

    def test_symlink_source_is_rejected(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        link = self.root / "sources/link.txt"
        link.symlink_to(self.source)
        run_id = self.run_id("symlink")
        result = self.command(
            "prepare",
            "--run-id",
            run_id,
            "--problem-id",
            "20000101-example",
            "--role",
            "ADVERSARIAL_VERIFIER",
            "--context-mode",
            "VERIFICATION",
            "--launch-prompt",
            "problems/active/example/parallel_llm_launch_prompt.md",
            "--source-file",
            "sources/link.txt",
            expect=2,
        )
        self.assertIn("symlink", result["error"])

    def test_response_tampering_is_detected_after_import(self) -> None:
        run_id = self.run_id("response-drift")
        self.prepare(run_id)
        self.approve(run_id)
        self.dispatch(run_id)
        run_dir = self.root / f"runs/external_llm/chatgpt_pro/{run_id}"
        response = run_dir / "raw_response.md"
        response.write_text(
            "# External Pro Report\n\n" + "Auditable mathematical response. " * 10,
            encoding="utf-8",
        )
        self.command("import-response", "--run-id", run_id)
        response.write_text(response.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")
        result = self.command("status", "--run-id", run_id, "--verify", expect=2)
        self.assertIn("no longer matches", result["error"])

    def test_unicode_problem_id_is_portable(self) -> None:
        run_id = self.run_id("unicode-problem")
        result = self.command(
            "prepare",
            "--run-id",
            run_id,
            "--problem-id",
            "20260716-тестовая-теорема",
            "--role",
            "PROOF_GENERATOR",
            "--context-mode",
            "BLIND_GENERATION",
            "--launch-prompt",
            "problems/active/example/parallel_llm_launch_prompt.md",
            "--source-file",
            "sources/primary.txt",
        )
        self.assertEqual(result["problem_id"], "20260716-тестовая-теорема")


if __name__ == "__main__":
    unittest.main()
