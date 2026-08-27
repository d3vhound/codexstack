from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins" / "codexstack" / "skills" / "work" / "scripts" / "check_plan.py"
SPEC = importlib.util.spec_from_file_location("codexstack_check_plan", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
check_plan = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = check_plan
SPEC.loader.exec_module(check_plan)


RULE = check_plan.RULE


def lanes() -> str:
    return "\n".join(
        f"- [ ] Lane {number}. Exercise case {number}. Save `proof/lane-{number}.png`. Pass when case {number} is visible."
        for number in range(1, 11)
    )


def pr_section(pr_id: str, dependency: str, interaction: bool = False) -> str:
    if interaction:
        gate = """**Review gate.** The operator reviews before merge.

- [ ] Save the interaction screenshot at `proof/review.png`.
- [ ] Save the interaction video at `proof/review.mp4`.
- [ ] Ask the operator to accept both artifacts.
"""
    else:
        gate = f"**Review gate.** None. {pr_id} changes no user interaction.\n"
    return f"""## Build {pr_id} ({pr_id})

**Depends on.** {dependency}

**Files.**

- [ ] Edit `src/{pr_id}.py`.

**Build.**

- [ ] Add the {pr_id} boundary.

**You see.**

- [ ] The command prints `{pr_id} ready`.

**Verify, unit.** {RULE}

- [ ] Add `tests/{pr_id}.py`. Run `python -m unittest`.

**Verify, live.** {RULE} Ten live lanes at the exact PR head.

{lanes()}

**Verify, perf.** {RULE}

- [ ] Metric. Measure elapsed milliseconds.
- [ ] Probe. Run `python benchmark.py` at trunk and head.
- [ ] Baseline. Record the trunk value first.
- [ ] Rule. Fail when head is more than 10 percent slower.

{gate}
**Merge.**

- [ ] Merge only after PASS at the exact head SHA.
"""


def valid_plan() -> str:
    return f"""# Release plan

This plan ships two dependency-ordered changes.
Each change carries revision-bound evidence.

## How to read this

One box is one unit of work. Every box names the evidence that checks it.
Check a box only when its evidence exists.
Use the CodexStack delivery playbook.
{RULE}

## Program checklist

### Arm the program

- [ ] Wait for the operator's explicit go.
- [ ] Honor a zero-write stop before more work.

### Spawn owners

- [ ] Follow the dependency graph in PR section order.
- [ ] Keep file ownership exclusive and disjoint.
- [ ] Hold each interaction review gate for the operator.

### PR mechanics

- [ ] Commit. Create one landable ordered commit.
- [ ] PR. Open one ready pull request for that commit.
- [ ] Ready. Stop at merge-ready without inferring merge authority.
- [ ] Land. Merge only with explicit authority.

### Verdict and merge

- [ ] Record PASS against the exact head SHA before merge.

### Boot recipe

- [ ] Exercise the real surface and save each evidence artifact.

{pr_section("PR-1", "None.")}
{pr_section("PR-2", "PR-1.", interaction=True)}
## Close the program

- [ ] Every box has evidence.

## Appendix A. Prototype evidence

No open prototype questions remain.
"""


def replace_once(text: str, old: str, new: str) -> str:
    if old not in text:
        raise AssertionError(f"fixture expected an occurrence of {old!r}")
    return text.replace(old, new, 1)


class CheckPlanAuditTests(unittest.TestCase):
    def test_valid_plan_reports_revision_proof_shape_and_dependencies(self) -> None:
        payload = check_plan.audit_text(valid_plan()).payload()
        self.assertTrue(payload["valid"], payload["diagnostics"])
        self.assertEqual(payload["summary"], {
            "pr_sections": 2, "problems": 0, "explicit_skips": 0
        })
        self.assertEqual(payload["prs"][0]["depends_on"], [])
        self.assertEqual(payload["prs"][1]["depends_on"], ["PR-1"])
        self.assertEqual(payload["prs"][0]["boxes"]["Verify, live."], 10)
        self.assertEqual(payload["contract_version"], check_plan.CONTRACT_VERSION)

    def test_required_blocks_stay_in_exact_order(self) -> None:
        plan = valid_plan()
        plan = replace_once(
            plan,
            "**Files.**\n\n- [ ] Edit `src/PR-1.py`.\n\n**Build.**",
            "**Build.**\n\n- [ ] Add the PR-1 boundary.\n\n**Files.**",
        )
        codes = {item["code"] for item in check_plan.audit_text(plan).payload()["diagnostics"]}
        self.assertIn("pr.blocks", codes)

    def test_verification_rule_is_required_in_all_three_blocks(self) -> None:
        plan = replace_once(valid_plan(), f"**Verify, unit.** {RULE}", "**Verify, unit.** Run tests.")
        diagnostics = check_plan.audit_text(plan).payload()["diagnostics"]
        self.assertTrue(any(item["code"] == "verify.rule" for item in diagnostics))

    def test_live_proof_requires_ten_ordered_lanes_artifacts_and_predicates(self) -> None:
        plan = replace_once(
            valid_plan(),
            "- [ ] Lane 4. Exercise case 4. Save `proof/lane-4.png`. Pass when case 4 is visible.",
            "- [ ] Lane 9. Exercise case 4 without evidence.",
        )
        codes = [item["code"] for item in check_plan.audit_text(plan).payload()["diagnostics"]]
        self.assertIn("live.count", codes)
        self.assertIn("live.artifact", codes)
        self.assertIn("live.predicate", codes)

    def test_perf_proof_has_metric_probe_baseline_and_numeric_rule_order(self) -> None:
        plan = replace_once(valid_plan(), "- [ ] Baseline. Record the trunk value first.\n", "")
        diagnostics = check_plan.audit_text(plan).payload()["diagnostics"]
        self.assertTrue(any(item["code"] == "perf.items" for item in diagnostics))

        no_threshold = replace_once(
            valid_plan(),
            "- [ ] Rule. Fail when head is more than 10 percent slower.",
            "- [ ] Rule. Reject a material regression.",
        )
        self.assertTrue(any(
            item["code"] == "perf.threshold"
            for item in check_plan.audit_text(no_threshold).payload()["diagnostics"]
        ))

    def test_review_gate_requires_concrete_none_reason_or_interaction_artifacts(self) -> None:
        no_reason = replace_once(
            valid_plan(),
            "**Review gate.** None. PR-1 changes no user interaction.",
            "**Review gate.** None.",
        )
        self.assertTrue(any(
            item["code"] == "review.reason"
            for item in check_plan.audit_text(no_reason).payload()["diagnostics"]
        ))

        no_video = replace_once(
            valid_plan(),
            "- [ ] Save the interaction video at `proof/review.mp4`.\n",
            "",
        )
        self.assertTrue(any(
            item["code"] == "review.evidence" and "video" in item["message"]
            for item in check_plan.audit_text(no_video).payload()["diagnostics"]
        ))

    def test_dependencies_must_be_unique_known_and_topologically_earlier(self) -> None:
        cases = [
            ("**Depends on.** PR-1.\n\n**Files.**", "**Depends on.** PR-2.\n\n**Files.**", "pr.dependency-order"),
            ("**Depends on.** PR-1.\n\n**Files.**", "**Depends on.** PR-9.\n\n**Files.**", "pr.dependency-unknown"),
            ("**Depends on.** PR-1.\n\n**Files.**", "**Depends on.** PR-1, PR-1.\n\n**Files.**", "pr.dependencies"),
        ]
        for old, new, code in cases:
            with self.subTest(code=code):
                plan = replace_once(valid_plan(), old, new)
                diagnostics = check_plan.audit_text(plan).payload()["diagnostics"]
                self.assertTrue(any(item["code"] == code for item in diagnostics), diagnostics)

    def test_commit_pr_ready_land_layers_are_required_in_order(self) -> None:
        missing = replace_once(
            valid_plan(),
            "- [ ] Ready. Stop at merge-ready without inferring merge authority.\n",
            "",
        )
        self.assertTrue(any(
            item["code"] == "program.delivery-layer"
            for item in check_plan.audit_text(missing).payload()["diagnostics"]
        ))
        reversed_plan = replace_once(
            valid_plan(),
            "- [ ] Commit. Create one landable ordered commit.\n- [ ] PR. Open one ready pull request for that commit.",
            "- [ ] PR. Open one ready pull request for that commit.\n- [ ] Commit. Create one landable ordered commit.",
        )
        self.assertTrue(any(
            item["code"] == "program.delivery-order"
            for item in check_plan.audit_text(reversed_plan).payload()["diagnostics"]
        ))

    def test_program_phases_need_boxes_and_core_codex_markers(self) -> None:
        missing_marker = replace_once(
            valid_plan(),
            "- [ ] Honor a zero-write stop before more work.\n",
            "",
        )
        self.assertTrue(any(
            item["code"] == "program.marker" and "zero-write" in item["message"]
            for item in check_plan.audit_text(missing_marker).payload()["diagnostics"]
        ))

        empty_boot = replace_once(
            valid_plan(),
            "- [ ] Exercise the real surface and save each evidence artifact.\n",
            "",
        )
        self.assertTrue(any(
            item["code"] == "program.evidence"
            for item in check_plan.audit_text(empty_boot).payload()["diagnostics"]
        ))

    def test_explicit_skip_needs_a_concrete_reason_and_cannot_mix_with_boxes(self) -> None:
        unit = (
            f"**Verify, unit.** {RULE}\n\n"
            "- [ ] Add `tests/PR-1.py`. Run `python -m unittest`."
        )
        skipped = f"**Verify, unit.** {RULE} Skipped. Generated output has no executable unit boundary."
        payload = check_plan.audit_text(replace_once(valid_plan(), unit, skipped)).payload()
        self.assertTrue(payload["valid"], payload["diagnostics"])
        self.assertEqual(payload["summary"]["explicit_skips"], 1)
        self.assertEqual(payload["skips"][0]["block"], "Verify, unit.")

        vague = replace_once(valid_plan(), unit, f"**Verify, unit.** {RULE} Skip: N/A")
        diagnostics = check_plan.audit_text(vague).payload()["diagnostics"]
        self.assertTrue(any(item["code"] == "skip.reason" for item in diagnostics))

        mixed = replace_once(
            valid_plan(),
            f"**Build.**\n\n- [ ] Add the PR-1 boundary.",
            "**Build.** Skipped. Existing generated code owns this boundary.\n\n- [ ] Add the PR-1 boundary.",
        )
        self.assertTrue(any(
            item["code"] == "skip.ambiguous"
            for item in check_plan.audit_text(mixed).payload()["diagnostics"]
        ))

    def test_prose_rules_ignore_fenced_and_inline_code(self) -> None:
        plan = valid_plan() + "\n```text\ncode: okay \u2014 okay\n```\n"
        self.assertTrue(check_plan.audit_text(plan).payload()["valid"])
        bad = replace_once(valid_plan(), "This plan ships", "This plan: ships")
        bad = bad.replace("revision-bound", "revision\u2014bound", 1)
        codes = {item["code"] for item in check_plan.audit_text(bad).payload()["diagnostics"]}
        self.assertIn("prose.mid-colon", codes)
        self.assertIn("prose.long-dash", codes)

    def test_unclosed_frontmatter_and_fences_fail_closed(self) -> None:
        frontmatter = check_plan.audit_text("---\ntitle: plan\n").payload()["diagnostics"]
        self.assertTrue(any(item["code"] == "frontmatter.unclosed" for item in frontmatter))
        fence = check_plan.audit_text(valid_plan() + "\n```\n").payload()["diagnostics"]
        self.assertTrue(any(item["code"] == "fence.unclosed" for item in fence))


class CheckPlanBoundaryAndCliTests(unittest.TestCase):
    def test_path_reader_rejects_absolute_parent_symlink_binary_and_oversize_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = root / "docs" / "plan.md"
            good.parent.mkdir()
            good.write_text(valid_plan(), encoding="utf-8")
            text, display = check_plan.read_plan("docs/plan.md", root)
            self.assertEqual(text, valid_plan())
            self.assertEqual(display, "docs/plan.md")

            for unsafe in (str(good), "../plan.md", "-plan.md", "plan.txt"):
                with self.subTest(unsafe=unsafe), self.assertRaises(check_plan.InputError):
                    check_plan.read_plan(unsafe, root)

            link = root / "link.md"
            link.symlink_to(good)
            with self.assertRaisesRegex(check_plan.InputError, "symlink"):
                check_plan.read_plan("link.md", root)

            binary = root / "binary.md"
            binary.write_bytes(b"\xff")
            with self.assertRaisesRegex(check_plan.InputError, "UTF-8"):
                check_plan.read_plan("binary.md", root)

            huge = root / "huge.md"
            huge.write_bytes(b"x" * (check_plan.MAX_BYTES + 1))
            with self.assertRaisesRegex(check_plan.InputError, "exceeds"):
                check_plan.read_plan("huge.md", root)

    def test_cli_json_is_stable_and_human_mode_reports_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "plan.md"
            path.write_text(valid_plan(), encoding="utf-8")
            old_cwd = Path.cwd()
            try:
                os.chdir(root)
                json_out = io.StringIO()
                with contextlib.redirect_stdout(json_out):
                    code = check_plan.main(["plan.md", "--json"])
                self.assertEqual(code, 0)
                payload = json.loads(json_out.getvalue())
                self.assertTrue(payload["valid"])

                path.write_text(replace_once(valid_plan(), "## Close the program", "## Finish"), encoding="utf-8")
                stdout = io.StringIO()
                stderr = io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = check_plan.main(["plan.md"])
                self.assertEqual(code, 1)
                self.assertIn("close.missing", stderr.getvalue())
                self.assertIn("problems", stdout.getvalue())
                self.assertNotIn("\u2014", stdout.getvalue() + stderr.getvalue())
            finally:
                os.chdir(old_cwd)

    def test_cli_input_error_is_json_and_uses_exit_two(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = check_plan.main(["../outside.md", "--json"])
        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 2)
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["diagnostics"][0]["code"], "input.invalid")

    def test_checker_is_passive_stdlib_and_contains_no_long_dash_literal(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("subprocess", "socket", "urllib", "requests", "time.sleep", "schedule"):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("\u2014", source)


if __name__ == "__main__":
    unittest.main()
