from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAYBOOKS = (
    ROOT
    / "plugins"
    / "codexstack"
    / "skills"
    / "work"
    / "references"
    / "playbooks.md"
)
EVALS = ROOT / "evals" / "scenarios.md"
REVIEW = (
    ROOT
    / "plugins"
    / "codexstack"
    / "skills"
    / "work"
    / "references"
    / "review.md"
)
BUGBOT = PLAYBOOKS.parent / "bugbot-triage.md"
DELIVERY = (
    ROOT
    / "plugins"
    / "codexstack"
    / "skills"
    / "work"
    / "references"
    / "delivery.md"
)
AUTONOMY = PLAYBOOKS.parent / "autonomy.md"
INVESTIGATE = PLAYBOOKS.parent / "investigate.md"
ORCHESTRATE = PLAYBOOKS.parent / "orchestrate.md"
QUALITY = PLAYBOOKS.parent / "quality.md"
WORK_SKILL = PLAYBOOKS.parent.parent / "SKILL.md"
DELIBERATE = PLAYBOOKS.parent / "deliberate.md"
GATES = PLAYBOOKS.parent / "gates-and-laws.md"

PLAYBOOK_NAMES = (
    "Investigation",
    "Bug fix",
    "Perf issue",
    "Hillclimb",
    "Runtime forensics",
    "Trace forensics",
    "Feature",
    "Refactoring",
    "Prototype",
    "Visual parity",
    "Authoring or modifying a skill",
    "Eval",
    "Babysit",
    "Shipping",
    "Autonomous run",
    "Orchestrate",
    "Autopilot-full",
    "Autopilot-stack",
    "Session pickup",
    "Pause safely",
    "Multi-phase or multi-PR plan",
    "Worktree and simulator cleanup",
    "Opening a PR",
)

MINIMUM_STEPS = {
    "Investigation": 4,
    "Bug fix": 6,
    "Perf issue": 6,
    "Hillclimb": 8,
    "Runtime forensics": 5,
    "Trace forensics": 6,
    "Feature": 8,
    "Refactoring": 8,
    "Prototype": 6,
    "Visual parity": 5,
    "Authoring or modifying a skill": 4,
    "Eval": 7,
    "Babysit": 9,
    "Shipping": 9,
    "Autonomous run": 6,
    "Orchestrate": 7,
    "Autopilot-full": 7,
    "Autopilot-stack": 8,
    "Session pickup": 5,
    "Pause safely": 4,
    "Multi-phase or multi-PR plan": 7,
    "Worktree and simulator cleanup": 6,
    "Opening a PR": 7,
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def sections(text: str) -> dict[str, str]:
    starts = []
    for name in PLAYBOOK_NAMES:
        marker = f"## {name}\n"
        offset = text.find(marker)
        if offset < 0:
            raise AssertionError(f"missing playbook heading {name!r}")
        starts.append((offset, name))
    starts.sort()
    result = {}
    for index, (offset, name) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(text)
        result[name] = text[offset:end]
    return result


def ordered_positions(text: str, tokens: tuple[str, ...]) -> list[int]:
    positions = [text.find(token) for token in tokens]
    if any(position < 0 for position in positions):
        missing = [token for token, position in zip(tokens, positions) if position < 0]
        raise AssertionError(f"missing ordered tokens {missing!r}")
    return positions


class PlaybookContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = read(PLAYBOOKS)
        cls.sections = sections(cls.text)

    def test_all_upstream_playbooks_have_copyable_numbered_states(self) -> None:
        self.assertEqual(set(self.sections), set(PLAYBOOK_NAMES))
        for name, section in self.sections.items():
            with self.subTest(playbook=name):
                steps = re.findall(r"(?m)^(\d+)\. \*\*[^*]+\.\*\*", section)
                numbers = [int(step) for step in steps]
                self.assertEqual(numbers, list(range(1, len(numbers) + 1)))
                self.assertGreaterEqual(len(numbers), MINIMUM_STEPS[name])

    def test_foundations_units_and_subtraction_preserve_sequence(self) -> None:
        gates = read(GATES)
        for token in (
            "core data structures and types",
            "Trace dominant access paths",
            "land shared CI, lint, test, and type scaffolds before dependent features",
            "Verify the current unit green before advancing",
            "before additions, refactors, or rewrites, remove obsolete",
        ):
            self.assertIn(token, gates)

    def test_forensics_keep_the_read_only_throughput_checkpoint(self) -> None:
        for name in ("Runtime forensics", "Trace forensics"):
            section = self.sections[name]
            self.assertIn("**Throughput checkpoint.**", section)
            self.assertIn("throughput checkpoint: n/a, read-only forensics", section)
            self.assertIn("**Diagnose.**", section)

    def test_feature_preserves_delegation_and_review_separation(self) -> None:
        feature = self.sections["Feature"]
        positions = ordered_positions(
            feature,
            (
                "1. **How.**",
                "2. **Architect.**",
                "3. **Throughput checkpoint.**",
                "4. **Delegate implementation.**",
                "5. **Verify.**",
                "6. **Order delivery.**",
                "7. **No-comments and Interrogate.**",
                "8. **Open.**",
            ),
        )
        self.assertEqual(positions, sorted(positions))
        self.assertIn("whenever code crosses any function or module boundary", feature)
        self.assertIn("This delegation is mandatory", feature)
        self.assertIn("The lead reviews the complete diff", feature)
        self.assertIn("fresh No-comments audit before review", feature)
        self.assertIn("If the design is contested, run Interrogate", feature)
        self.assertIn("commit each small unit before the next", feature)
        self.assertIn("dependent pull requests in that order", feature)

    def test_multi_phase_contract_has_fixed_audited_proof_blocks(self) -> None:
        plan = self.sections["Multi-phase or multi-PR plan"]
        positions = ordered_positions(
            plan,
            (
                "# <Program> plan",
                "## How to read this",
                "## Program checklist",
                "### Arm the program",
                "### Spawn owners",
                "### PR mechanics",
                "### Verdict and merge",
                "### Boot recipe",
                "## <Task as a verb phrase> (<Unit id>)",
                "**Verify, unit.**",
                "**Verify, live.**",
                "**Verify, perf.**",
                "**Review gate.**",
                "**Merge.**",
                "## Close the program",
                "## Appendix A. Prototype evidence",
                "## Appendix B. Alternatives rejected",
                "## Appendix C. Risks",
                "## Appendix D. Links and reading list",
            ),
        )
        self.assertEqual(positions, sorted(positions))
        verification_rule = (
            "Tests alone are not sufficient verification. A PR is verified only "
            "when its unit, live, and perf boxes are all checked."
        )
        self.assertGreaterEqual(plan.count(verification_rule), 4)
        self.assertIn("scripts/check_plan.py <plan.md>", plan)
        self.assertIn("Ten live lanes at the exact PR head", plan)
        for lane in range(1, 11):
            self.assertIn(f"Lane {lane}.", plan)
        for layer in ("Commit.", "PR.", "Ready.", "Land."):
            self.assertIn(layer, plan)
        self.assertIn("screenshots and video before merge", plan)
        self.assertIn("stop until explicit go", plan)
        self.assertIn("exact head SHA", plan)

    def test_delivery_contract_keeps_review_and_landing_separate(self) -> None:
        opening = self.sections["Opening a PR"]
        self.assertIn("fresh No-comments audit before review", opening)
        self.assertIn("small landable commits", opening)
        self.assertIn("Opening does not start Babysit", opening)
        self.assertIn("grant landing authority", opening)

        shipping = self.sections["Shipping"]
        self.assertIn("contiguous verified run", shipping)
        self.assertIn("exact head", shipping)
        self.assertIn("independent", shipping)
        delivery = read(DELIVERY)
        self.assertIn("Stop when the exact-head snapshot reports `babysit_ready`", delivery)
        self.assertIn("Do not wait for `provider_landing_gate_clear`", delivery)
        self.assertIn("fresh exact-head provider snapshot", delivery)
        self.assertIn("require `provider_landing_gate_clear`", delivery)
        self.assertIn("in addition to PASS or PASS+NOTES", delivery)
        self.assertIn("False, missing, or stale provider evidence stops", delivery)
        self.assertIn("explicit current user request or mandatory repository policy", opening)

    def test_playbook_return_registry_preserves_decision_evidence(self) -> None:
        registry = self.text[self.text.index("## Required return fields") :]
        self.assertIn("**Hillclimb.**", registry)
        self.assertIn("iterations kept versus reverted", registry)
        self.assertIn("trail path", registry)
        self.assertIn("best next idea", registry)
        self.assertIn("**Visual parity.**", registry)
        self.assertIn("every migrated component or state", registry)
        self.assertIn("immutable baseline harness path", registry)
        self.assertIn("**Feature.**", registry)
        self.assertIn("choices and reasons", registry)
        self.assertIn("design alternatives and tradeoffs in a table", registry)
        self.assertIn("**Babysit.**", registry)
        self.assertIn("four-column status table", registry)
        self.assertIn("fixes versus dismissals with reasons", registry)
        for name in PLAYBOOK_NAMES:
            self.assertIn(f"**{name}.**", registry)

    def test_stack_status_is_whole_list_and_tier_major(self) -> None:
        delivery = read(DELIVERY)
        positions = ordered_positions(
            delivery,
            (
                "Conflicts across every row, bottom to top.",
                "Unresolved review threads across every row, bottom to top.",
                "Failing CI or provider rejection across every row, bottom to top.",
                "Review and merge gates across every row, bottom to top.",
                "The first pending row, bottom to top, only after all blocker tiers are clear.",
            ),
        )
        self.assertEqual(positions, sorted(positions))
        self.assertIn("reads the complete bottom-to-top list before deciding", delivery)
        self.assertIn("clear only when every row is ready or merged", delivery)
        self.assertIn("does not transfer mutation ownership", delivery)
        self.assertIn("lowest unmerged frontier", delivery)

    def test_queued_mode_is_frozen_and_frontier_driven(self) -> None:
        delivery = read(DELIVERY)
        queued = delivery[delivery.index("### Frozen queued mode") :]
        positions = ordered_positions(
            queued,
            (
                "Freeze the supplied bottom-to-top queue once",
                "Observe the lowest unmerged row as the frontier",
                "emit nonterminal `ADVANCE`",
                "emit terminal `COMPLETE`",
                "closed without merge",
                "Never rediscover, expand, reorder, or silently repair the frozen queue",
            ),
        )
        self.assertEqual(positions, sorted(positions))
        self.assertIn("pending upper row never replaces the frontier wait", queued)
        self.assertIn("move immediately to the next frozen row", queued)
        self.assertIn("any tier-major blocker", queued)
        self.assertIn("never authorizes a merge or a topology change", queued)
        self.assertIn("Native Codex owns each refresh and event wait", delivery)
        self.assertIn("adds no scheduler, watcher process, or polling loop", delivery)

        babysit = self.sections["Babysit"]
        shipping = self.sections["Shipping"]
        self.assertIn("whole-stack status scan", babysit)
        self.assertIn("complete bottom-to-top stack tier-major", babysit)
        self.assertIn("Capture the authorized bottom-to-top list once", shipping)
        self.assertIn("Native Codex owns monitoring", shipping)

    def test_no_comments_is_a_fresh_read_only_review_gate(self) -> None:
        review = read(REVIEW)
        self.assertIn("commission a fresh read-only reviewer", review)
        self.assertIn("audits every added or changed comment", review)
        self.assertIn("accepts or rejects each finding independently", review)
        self.assertIn("reviewer never mutates", review)

    def test_bugbot_triage_preserves_learned_decision_boundaries(self) -> None:
        triage = read(BUGBOT)
        for disposition in ("**fix**", "**dismiss**", "**ask**"):
            self.assertIn(disposition, triage)
        for confidence in ("`candidate`", "`recurring`", "`strong`"):
            self.assertIn(confidence, triage)
        for pattern in (
            "Intentional visual change",
            "Verified upstack use",
            "Temporary duplication",
            "Enforced invariant",
            "Owner-declared follow-up",
            "Self-withdrawn finding",
            "Browser-native reimplementation",
            "Stale security finding",
            "Narrow error condition",
        ):
            self.assertIn(pattern, triage)
        self.assertIn("Accessibility, focus visibility, keyboard behavior, contrast", triage)
        self.assertIn("default to fix", triage)
        self.assertIn("Run the focused contract test before classifying", triage)
        self.assertIn("exact effective guard before the side effect", triage)
        self.assertIn("`ENOENT`", triage)
        self.assertIn("`EACCES`", triage)
        self.assertIn("persistent reference, not private memory", triage)
        self.assertIn("After Babysit reaches READY, queued WAITING, or COMPLETE", triage)
        self.assertIn("separate reviewable change", triage)
        self.assertIn("[bugbot-triage.md](bugbot-triage.md)", read(REVIEW))
        self.assertIn("[bugbot-triage.md](bugbot-triage.md)", read(DELIVERY))
        for route in ("Babysit", "Autopilot-full", "Autopilot-stack", "Multi-phase or multi-PR plan"):
            self.assertIn("(bugbot-triage.md)", self.sections[route])

    def test_figure_it_out_and_trail_close_are_auditable(self) -> None:
        work = read(WORK_SKILL)
        autonomy = read(AUTONOMY)
        orchestrate = read(ORCHESTRATE)
        self.assertIn("large or cross-cutting bespoke run", work)
        self.assertIn("work the human will review after stepping away", work)
        for token in (
            "1. **Frame.**",
            "2. **Design the workflow.**",
            "3. **Run hypothesis units.**",
            "4. **Keep the trail.**",
            "5. **Close the whole.**",
            "VERIFIED",
            "NOT VERIFIED",
            "INCONCLUSIVE",
        ):
            self.assertIn(token, autonomy)
        self.assertIn("canonical append-only trail", autonomy)
        self.assertIn("Self-audit every row against actual run evidence", autonomy)
        self.assertIn("fresh read-only reviewer from a different available model family", autonomy)
        self.assertIn("reviewed by <model>", autonomy)
        self.assertIn("same-family fallback is itself a flag", autonomy)
        self.assertIn("self-audit the append-only decision and event trail", orchestrate)
        self.assertIn("Every close reply ends with `Attention`", orchestrate)
        self.assertIn("authenticated `release-stop` transition", orchestrate)
        self.assertIn("operator-authorization", orchestrate)
        self.assertIn("repaired-systemic-cause", orchestrate)

    def test_how_has_explain_then_independent_critique(self) -> None:
        investigate = read(INVESTIGATE)
        self.assertIn("Use **Explain** by default", investigate)
        self.assertIn("Complete Explain first", investigate)
        self.assertIn("multiple independent fresh read-only critics", investigate)
        self.assertIn("abstraction fit", investigate)
        self.assertIn("data model", investigate)
        self.assertIn("boundary discipline", investigate)
        self.assertIn("evolution readiness", investigate)
        self.assertIn("complexity versus value", investigate)
        for disposition in ("**Act**", "**Consider**", "**Noted**", "**Dismissed**"):
            self.assertIn(disposition, investigate)
        self.assertIn("Critique remains read-only", investigate)

    def test_verifier_create_and_maintain_preserve_live_contract(self) -> None:
        quality = read(QUALITY)
        for token in ("**Surface**", "**Run**", "**Drive**", "**Observe**", "**Isolate**"):
            self.assertIn(token, quality)
        for token in ("**Launch**", "**Doctor**", "**Evidence**", "**Cleanup**", "**Helpers**"):
            self.assertIn(token, quality)
        self.assertIn("feature map with a README index and one file per feature", quality)
        self.assertIn("confirm evidence survived", quality)
        self.assertIn("one concurrent read-only source lane per feature", quality)
        self.assertIn("drives every mapped feature live", quality)
        self.assertIn("Product code is read-only", quality)
        self.assertIn("at most one authorized PR", quality)
        for outcome in ("**clean**", "**changed**", "**blocked**"):
            self.assertIn(outcome, quality)

    def test_automate_me_updates_an_explicit_private_mode(self) -> None:
        work = read(WORK_SKILL)
        quality = read(QUALITY)
        self.assertIn("Automate me", work)
        self.assertIn("Find matching `*-mode` skills recursively", quality)
        self.assertIn("update in place as the default", quality)
        self.assertIn("active workspace", quality)
        self.assertIn("Never glob across unrelated workspaces", quality)
        self.assertIn("corroborate patterns across at least two slices", quality)
        self.assertIn("one or two small structured questions", quality)
        self.assertIn("allow_implicit_invocation: false", quality)
        self.assertIn("Show the draft to the user", quality)
        self.assertIn("never push directly to the main branch", quality)

    def test_reflect_uses_three_fresh_lenses_and_a_separate_gate(self) -> None:
        deliberate = read(DELIBERATE)
        self.assertIn("one Swarm `partition` with three fresh parallel read-only reviewers", deliberate)
        for lens in ("**divergent**", "**tooling**", "**judgment**"):
            self.assertIn(lens, deliberate)
        self.assertIn("fresh independent synthesizer", deliberate)
        for outcome in ("**Accepted**", "**Rejected**", "**Backlog**"):
            self.assertIn(outcome, deliberate)
        self.assertIn("Present the full synthesis before changing anything", deliberate)
        self.assertIn("do not auto-file a backlog item", deliberate)

    def test_typescript_rules_preserve_semantics_without_overstrengthening(self) -> None:
        quality = read(QUALITY)
        for token in (
            "Brand semantic primitives",
            "constructive invariants",
            "Do not over-strengthen",
            "Narrow in this order",
            "honest user-defined guard",
            "Prefer `satisfies`",
            "`Pick`, `Omit`, `Parameters`, `ReturnType`, `Awaited`, or `typeof`",
            "Prefer object arguments",
            "structured telemetry",
            "Do not ship `console.log`",
        ):
            self.assertIn(token, quality)

    def test_runtime_contract_is_codex_native_and_clean(self) -> None:
        forbidden = (
            ".cursor/",
            "/poteto-mode",
            "subagent_type",
            "run_in_background",
            "poteto-agent",
            "claude-",
            "grok-",
        )
        lowered = self.text.lower()
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, lowered)
        self.assertNotIn("\u2014", self.text)
        in_fence = False
        for line_number, line in enumerate(self.text.splitlines(), start=1):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            prose = re.sub(r"`[^`]*`", "", line)
            if ":" in prose:
                self.assertTrue(
                    prose.rstrip().endswith(":"),
                    f"mid-sentence colon on line {line_number}",
                )

    def test_behavior_eval_names_the_executable_contract_suite(self) -> None:
        evals = read(EVALS)
        self.assertIn(
            "python3 -m unittest discover -s tests -p 'test_behavior_contract.py' -v",
            evals,
        )
        self.assertIn("## 20. Stack status and frozen queue preserve their frontiers", evals)
        self.assertIn("## 28. Automated review triage learns without bot churn", evals)
        self.assertIn("## 29. Model setup preserves role and panel intent", evals)


if __name__ == "__main__":
    unittest.main()
