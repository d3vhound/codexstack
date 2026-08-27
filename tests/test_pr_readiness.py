from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "plugins"
    / "codexstack"
    / "skills"
    / "work"
    / "scripts"
    / "pr_readiness.py"
)
SPEC = importlib.util.spec_from_file_location("codexstack_pr_readiness", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
readiness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(readiness)


HEAD = "a" * 40
OLD_HEAD = "b" * 40


def passing(name: str = "test", sha: str = HEAD) -> dict:
    return {
        "name": name,
        "head_sha": sha,
        "status": "COMPLETED",
        "conclusion": "SUCCESS",
    }


def failed(name: str = "test", sha: str = HEAD) -> dict:
    return {
        "name": name,
        "head_sha": sha,
        "status": "COMPLETED",
        "conclusion": "FAILURE",
    }


def pending(name: str = "test", sha: str = HEAD) -> dict:
    return {
        "name": name,
        "head_sha": sha,
        "status": "IN_PROGRESS",
        "conclusion": None,
    }


def snapshot(pr: int = 42) -> dict:
    return {
        "contract_version": readiness.CONTRACT_VERSION,
        "pr": pr,
        "head_sha": HEAD,
        "state": "OPEN",
        "mergeable": "MERGEABLE",
        "merge_state_status": "CLEAN",
        "review_decision": "APPROVED",
        "is_draft": False,
        "unresolved_threads": 0,
        "checks": [passing()],
        "head_rollup": {"head_sha": HEAD, "state": "SUCCESS"},
    }


def changed(pr: int, **changes) -> dict:
    value = snapshot(pr)
    value.update(changes)
    return value


class PrReadinessTests(unittest.TestCase):
    def verdict(self, **changes) -> dict:
        value = snapshot()
        value.update(changes)
        return readiness.classify(value)

    def test_exact_clean_head_finishes_babysitting_and_clears_provider_gate(self) -> None:
        verdict = self.verdict()
        self.assertEqual(verdict["status"], "ready")
        self.assertTrue(verdict["babysit_ready"])
        self.assertTrue(verdict["provider_landing_gate_clear"])
        self.assertNotIn("ready_for_merge", verdict)
        self.assertTrue(verdict["terminal"])
        self.assertEqual(verdict["proof"]["head_sha"], HEAD)
        self.assertEqual(verdict["proof"]["passing_checks"], ["test"])
        self.assertEqual(verdict["contract_version"], readiness.CONTRACT_VERSION)

    def test_merged_is_babysit_complete_but_has_no_provider_gate_proof(self) -> None:
        merged = readiness.classify(
            {"pr": 42, "head_sha": HEAD, "state": "MERGED"}
        )
        self.assertEqual(merged["status"], "merged")
        self.assertTrue(merged["babysit_ready"])
        self.assertFalse(merged["provider_landing_gate_clear"])
        closed = readiness.classify(
            {"pr": 42, "head_sha": HEAD, "state": "CLOSED"}
        )
        self.assertEqual(closed["status"], "blocked")
        self.assertEqual(
            closed["reason"],
            {"kind": "closed_without_merge", "tier": "review_merge_gate"},
        )

    def test_conflict_outranks_threads_failures_and_review_gate(self) -> None:
        verdict = self.verdict(
            mergeable="CONFLICTING",
            unresolved_threads=3,
            checks=[failed()],
            review_decision="CHANGES_REQUESTED",
        )
        self.assertEqual(verdict["reason"]["tier"], "conflict")
        self.assertEqual(verdict["reason"]["kind"], "merge_conflict")

    def test_threads_outrank_failing_checks_and_review_gate(self) -> None:
        verdict = self.verdict(
            unresolved_threads=[{"id": "t1"}],
            checks=[failed()],
            is_draft=True,
        )
        self.assertEqual(
            verdict["reason"],
            {"kind": "unresolved_threads", "tier": "threads", "count": 1},
        )

    def test_failing_checks_outrank_review_gate(self) -> None:
        verdict = self.verdict(
            checks=[failed("build")], review_decision="CHANGES_REQUESTED"
        )
        self.assertEqual(verdict["status"], "blocked")
        self.assertEqual(verdict["reason"]["tier"], "failing_checks")
        self.assertEqual(
            verdict["reason"]["checks"],
            [{"name": "build", "conclusion": "FAILURE"}],
        )

    def test_upstream_merge_assessment_truth_table_is_exhaustive(self) -> None:
        rollups = ("ERROR", "EXPECTED", "FAILURE", "PENDING", "SUCCESS", None)
        for merge_state in readiness.MERGE_STATES:
            for rollup_state in rollups:
                if merge_state in {"CONFLICTING", "DIRTY"}:
                    expected = "blocked"
                elif merge_state == "BLOCKED" and rollup_state in {
                    "ERROR",
                    "FAILURE",
                }:
                    expected = "blocked"
                else:
                    expected = "ready"
                with self.subTest(
                    merge_state=merge_state, rollup_state=rollup_state
                ):
                    verdict = self.verdict(
                        merge_state_status=merge_state,
                        head_rollup={"head_sha": HEAD, "state": rollup_state},
                    )
                    self.assertEqual(verdict["status"], expected)
                    self.assertEqual(
                        verdict["babysit_ready"], expected == "ready"
                    )

    def test_blocked_requires_exact_head_rollup_evidence(self) -> None:
        missing = self.verdict(merge_state_status="BLOCKED", head_rollup=None)
        self.assertEqual(missing["status"], "pending")
        self.assertEqual(missing["reason"]["kind"], "head_rollup_unavailable")
        stale = self.verdict(
            merge_state_status="BLOCKED",
            head_rollup={"head_sha": OLD_HEAD, "state": "FAILURE"},
        )
        self.assertEqual(stale["status"], "pending")
        self.assertEqual(stale["reason"]["kind"], "stale_head_evidence")

    def test_review_required_and_null_review_match_upstream_ready_policy(self) -> None:
        for review in ("REVIEW_REQUIRED", None):
            with self.subTest(review=review):
                verdict = self.verdict(review_decision=review)
                self.assertEqual(verdict["status"], "ready")
                self.assertTrue(verdict["babysit_ready"])
                self.assertFalse(verdict["provider_landing_gate_clear"])

    def test_provider_landing_signal_is_stricter_and_not_merge_authority(self) -> None:
        strict = self.verdict()
        self.assertTrue(strict["provider_landing_gate_clear"])

        no_review_required = self.verdict(
            review_decision=None, allow_unapproved=True
        )
        self.assertTrue(no_review_required["provider_landing_gate_clear"])
        self.assertEqual(
            no_review_required["proof"]["approval"], "explicitly_not_required"
        )

        cases = [
            {"review_decision": "REVIEW_REQUIRED"},
            {"review_decision": None},
            {"merge_state_status": "BEHIND"},
            {
                "merge_state_status": "BLOCKED",
                "head_rollup": {"head_sha": HEAD, "state": "SUCCESS"},
            },
            {"is_draft": True, "allow_draft": True},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                verdict = self.verdict(**changes)
                self.assertTrue(verdict["babysit_ready"])
                self.assertFalse(verdict["provider_landing_gate_clear"])

    def test_pending_draft_waits_but_changes_requested_is_an_immediate_gate(self) -> None:
        draft = self.verdict(checks=[pending("build")], is_draft=True)
        self.assertEqual(draft["status"], "pending")
        self.assertEqual(draft["reason"]["kind"], "checks_pending")

        changed_review = self.verdict(
            checks=[pending("build")], review_decision="CHANGES_REQUESTED"
        )
        self.assertEqual(changed_review["status"], "blocked")
        self.assertEqual(changed_review["reason"]["kind"], "changes_requested")

        settled_draft = self.verdict(is_draft=True)
        self.assertEqual(settled_draft["status"], "blocked")
        self.assertEqual(settled_draft["reason"]["kind"], "draft_pr")
        allowed = self.verdict(is_draft=True, allow_draft=True)
        self.assertEqual(allowed["status"], "ready")

    def test_absent_unknown_and_stale_check_evidence_fails_closed(self) -> None:
        cases = [
            ([], None, "checks_unavailable"),
            (
                [
                    {
                        "name": "build",
                        "head_sha": HEAD,
                        "status": "ALIEN",
                        "conclusion": None,
                    }
                ],
                None,
                "unknown_check_state",
            ),
            ([passing("build", OLD_HEAD)], None, "stale_head_evidence"),
            (
                [{"name": "build", "status": "COMPLETED", "conclusion": "SUCCESS"}],
                None,
                "stale_head_evidence",
            ),
        ]
        for checks, rollup, reason in cases:
            with self.subTest(reason=reason):
                verdict = self.verdict(checks=checks, head_rollup=rollup)
                self.assertEqual(verdict["status"], "pending")
                self.assertFalse(verdict["babysit_ready"])
                self.assertFalse(verdict["provider_landing_gate_clear"])
                self.assertEqual(verdict["reason"]["kind"], reason)

    def test_review_gate_is_separate_from_ci_but_still_revision_bound(self) -> None:
        review_gate = {
            "name": "Code Review Gate",
            "kind": "review_gate",
            "head_sha": HEAD,
            "status": "COMPLETED",
            "conclusion": "FAILURE",
        }
        verdict = self.verdict(checks=[review_gate])
        self.assertEqual(verdict["status"], "ready")
        self.assertEqual(verdict["proof"]["passing_checks"], [])

        stale_gate = copy.deepcopy(review_gate)
        stale_gate["head_sha"] = OLD_HEAD
        stale = self.verdict(checks=[stale_gate])
        self.assertEqual(stale["status"], "pending")
        self.assertEqual(stale["reason"]["kind"], "stale_head_evidence")

    def test_explicit_github_unknown_sentinels_preserve_upstream_policy(self) -> None:
        for changes in (
            {"mergeable": "UNKNOWN"},
            {"merge_state_status": "UNKNOWN"},
            {"mergeable": "UNKNOWN", "merge_state_status": "UNKNOWN"},
        ):
            with self.subTest(changes=changes):
                verdict = self.verdict(**changes)
                self.assertEqual(verdict["status"], "ready")
                self.assertTrue(verdict["babysit_ready"])
                self.assertFalse(verdict["provider_landing_gate_clear"])

    def test_unrecognized_or_missing_provider_facts_fail_closed(self) -> None:
        cases = [
            ({"merge_state_status": "FUTURE_STATE"}, "unknown_merge_state"),
            ({"review_decision": "DISMISSED"}, "unknown_review_decision"),
        ]
        for changes, reason in cases:
            with self.subTest(changes=changes):
                verdict = self.verdict(**changes)
                self.assertEqual(verdict["status"], "pending")
                self.assertEqual(verdict["reason"]["kind"], reason)

        for missing, reason in [
            ("mergeable", "unknown_merge_state"),
            ("merge_state_status", "unknown_merge_state"),
            ("review_decision", "review_decision_unavailable"),
            ("is_draft", "draft_state_unavailable"),
        ]:
            with self.subTest(missing=missing):
                value = snapshot()
                value.pop(missing)
                verdict = readiness.classify(value)
                self.assertEqual(verdict["status"], "pending")
                self.assertEqual(verdict["reason"]["kind"], reason)

    def test_missing_thread_evidence_fails_closed_before_ci(self) -> None:
        value = snapshot()
        value.pop("unresolved_threads")
        value["checks"] = [failed()]
        verdict = readiness.classify(value)
        self.assertEqual(verdict["status"], "pending")
        self.assertEqual(verdict["reason"]["tier"], "threads")

    def test_pr_and_head_identifiers_are_strict(self) -> None:
        with self.assertRaisesRegex(readiness.InputError, "positive integer"):
            readiness.classify({"pr": True, "head_sha": HEAD, "state": "MERGED"})
        with self.assertRaisesRegex(
            readiness.InputError, "full 40- or 64-character"
        ):
            readiness.classify({"pr": 1, "head_sha": "short", "state": "MERGED"})


class StackReadinessTests(unittest.TestCase):
    def test_upstack_conflict_outranks_frontier_failing_ci(self) -> None:
        verdict = readiness.classify_stack(
            [
                changed(10, checks=[failed("frontier")]),
                changed(11, mergeable="CONFLICTING"),
            ]
        )
        self.assertEqual(verdict["status"], "blocked")
        self.assertEqual(verdict["reason"]["tier"], "conflict")
        self.assertEqual(verdict["blocker"], {"pr": 11, "head_sha": HEAD})

    def test_tier_major_threads_outrank_failing_ci(self) -> None:
        verdict = readiness.classify_stack(
            [
                changed(20, checks=[failed("frontier")]),
                changed(21, unresolved_threads=1),
            ]
        )
        self.assertEqual(verdict["reason"]["tier"], "threads")
        self.assertEqual(verdict["blocker"]["pr"], 21)

    def test_tier_major_failing_ci_outranks_merge_gate(self) -> None:
        verdict = readiness.classify_stack(
            [
                changed(30, review_decision="CHANGES_REQUESTED"),
                changed(31, checks=[failed("upstack")]),
            ]
        )
        self.assertEqual(verdict["reason"]["tier"], "failing_checks")
        self.assertEqual(verdict["blocker"]["pr"], 31)

    def test_merge_gate_outranks_pending_and_first_pending_is_bottom_to_top(self) -> None:
        gated = readiness.classify_stack(
            [
                changed(40, checks=[pending("frontier")]),
                changed(41, review_decision="CHANGES_REQUESTED"),
            ]
        )
        self.assertEqual(gated["reason"]["tier"], "review_merge_gate")
        self.assertEqual(gated["blocker"]["pr"], 41)

        waiting = readiness.classify_stack(
            [
                changed(50),
                changed(51, checks=[pending("middle")]),
                changed(52, checks=[pending("top")]),
            ]
        )
        self.assertEqual(waiting["status"], "pending")
        self.assertEqual(waiting["frontier"], {"pr": 51, "head_sha": HEAD})
        self.assertFalse(waiting["terminal"])

    def test_clear_requires_every_row_ready_or_merged_and_preserves_heads(self) -> None:
        merged = {"pr": 61, "head_sha": OLD_HEAD, "state": "MERGED"}
        verdict = readiness.classify_stack([changed(60), merged])
        self.assertEqual(verdict["status"], "clear")
        self.assertTrue(verdict["babysit_ready"])
        self.assertTrue(verdict["provider_landing_gate_clear"])
        self.assertEqual(
            verdict["prs"],
            [{"pr": 60, "head_sha": HEAD}, {"pr": 61, "head_sha": OLD_HEAD}],
        )

        all_open = readiness.classify_stack([changed(62), changed(63)])
        self.assertTrue(all_open["provider_landing_gate_clear"])

        all_merged = readiness.classify_stack(
            [
                {"pr": 64, "head_sha": HEAD, "state": "MERGED"},
                {"pr": 65, "head_sha": OLD_HEAD, "state": "MERGED"},
            ]
        )
        self.assertTrue(all_merged["provider_landing_gate_clear"])

    def test_stack_is_nonempty_bounded_and_unambiguous(self) -> None:
        with self.assertRaisesRegex(readiness.InputError, "nonempty"):
            readiness.classify_stack([])
        with self.assertRaisesRegex(readiness.InputError, "at most"):
            readiness.classify_stack(
                [changed(index + 1) for index in range(readiness.MAX_STACK_ROWS + 1)]
            )
        with self.assertRaisesRegex(readiness.InputError, "duplicate PR"):
            readiness.classify_stack([changed(70), changed(70)])


class QueueTransitionTests(unittest.TestCase):
    OWNER = "owner"
    REPO = "repo"

    def identities(self, *prs: int) -> list[dict]:
        return [
            {"owner": self.OWNER, "repo": self.REPO, "pr": pr} for pr in prs
        ]

    def observed_identities(self, *prs: int, sha: str = HEAD) -> list[dict]:
        return [
            {
                "owner": self.OWNER,
                "repo": self.REPO,
                "pr": pr,
                "head_sha": sha,
            }
            for pr in prs
        ]

    def row(self, pr: int, **changes) -> dict:
        value = snapshot(pr)
        value.update(owner=self.OWNER, repo=self.REPO)
        value.update(changes)
        return value

    def rows(self, *prs: int) -> list[dict]:
        return [self.row(pr) for pr in prs]

    def merged(self, pr: int, sha: str = HEAD) -> dict:
        return {
            "owner": self.OWNER,
            "repo": self.REPO,
            "pr": pr,
            "head_sha": sha,
            "state": "MERGED",
        }

    def test_initialize_freezes_exact_bottom_to_top_order_without_mutating_input(self) -> None:
        identities = self.identities(100, 101, 102)
        original = copy.deepcopy(identities)
        state = readiness.initialize_queue(identities)
        self.assertEqual(identities, original)
        self.assertEqual(state["frozen"], original)
        self.assertEqual(state["frontier"], original[0])
        self.assertEqual(state["merged"], [])
        self.assertEqual(state["generation"], 0)
        self.assertEqual(state["history_start_generation"], 0)
        self.assertEqual(state["history"][0]["kind"], "INITIALIZED")
        self.assertEqual(state["order"], "bottom-to-top")
        self.assertEqual(
            state["repository"], {"owner": self.OWNER, "repo": self.REPO}
        )
        self.assertEqual(len(state["frozen_digest"]), 64)

        normalized = readiness.initialize_queue(
            [{"owner": "OwNeR", "repo": "RePo", "pr": 103}]
        )
        self.assertEqual(normalized["frozen"], self.identities(103))
        with self.assertRaisesRegex(readiness.InputError, "one normalized repository"):
            readiness.initialize_queue(
                [
                    {"owner": self.OWNER, "repo": self.REPO, "pr": 104},
                    {"owner": self.OWNER, "repo": "other", "pr": 105},
                ]
            )

    def test_snapshot_rejects_expansion_missing_and_reorder(self) -> None:
        state = readiness.initialize_queue(self.identities(110, 111))
        exact = self.rows(110, 111)
        cases = [
            (exact + [self.row(112)], "every frozen row"),
            (exact[:1], "every frozen row"),
            ([exact[1], exact[0]], "exact frozen repository and PR order"),
        ]
        cross_repo = copy.deepcopy(exact)
        cross_repo[1]["repo"] = "other"
        cases.append((cross_repo, "exact frozen repository and PR order"))
        for rows, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(readiness.InputError, message):
                    readiness.apply_queue_snapshot(state, rows)

    def test_caller_state_rejects_frozen_expansion_reorder_and_substitution(self) -> None:
        state = readiness.initialize_queue(self.identities(120, 121))
        mutations = []
        expanded = copy.deepcopy(state)
        expanded["frozen"].append(
            {"owner": self.OWNER, "repo": self.REPO, "pr": 122}
        )
        mutations.append(expanded)
        reordered = copy.deepcopy(state)
        reordered["frozen"].reverse()
        mutations.append(reordered)
        substituted = copy.deepcopy(state)
        substituted["frozen"][1]["repo"] = "other"
        mutations.append(substituted)
        for mutation in mutations:
            with self.subTest(frozen=mutation["frozen"]):
                with self.assertRaisesRegex(
                    readiness.InputError,
                    "frozen_digest|one normalized repository",
                ):
                    readiness.apply_queue_snapshot(mutation, self.rows(120, 121))

    def test_new_head_is_reclassified_and_old_head_proof_becomes_pending(self) -> None:
        state = readiness.initialize_queue(self.identities(125))
        first = readiness.apply_queue_snapshot(state, self.rows(125))
        self.assertEqual(first["event"]["frontier"]["head_sha"], HEAD)

        refreshed = self.row(125)
        refreshed["head_sha"] = OLD_HEAD
        refreshed["checks"] = [passing(sha=OLD_HEAD)]
        refreshed["head_rollup"] = {"head_sha": OLD_HEAD, "state": "SUCCESS"}
        second = readiness.apply_queue_snapshot(first["state"], [refreshed])
        self.assertEqual(second["event"]["kind"], "WAITING")
        self.assertEqual(second["event"]["frontier"]["head_sha"], OLD_HEAD)
        self.assertEqual(second["state"]["frontier"]["head_sha"], OLD_HEAD)

        stale = copy.deepcopy(refreshed)
        stale["checks"] = [passing(sha=HEAD)]
        third = readiness.apply_queue_snapshot(second["state"], [stale])
        self.assertEqual(third["event"]["kind"], "WAITING")
        self.assertEqual(third["event"]["reason"]["kind"], "frontier_pending")
        self.assertEqual(
            third["event"]["reason"]["detail"]["kind"], "stale_head_evidence"
        )

    def test_upper_pending_does_not_replace_the_lowest_unmerged_frontier(self) -> None:
        state = readiness.initialize_queue(self.identities(130, 131))
        rows = self.rows(130, 131)
        rows[1]["checks"] = [pending("upper")]
        result = readiness.apply_queue_snapshot(state, rows)
        self.assertEqual(result["event"]["kind"], "WAITING")
        self.assertEqual(result["event"]["frontier"], self.observed_identities(130)[0])
        self.assertEqual(result["event"]["reason"]["kind"], "merge_queue")
        self.assertFalse(result["event"]["terminal"])

    def test_any_upper_blocker_is_terminal_and_tier_major(self) -> None:
        cases = [
            (
                [self.row(140, checks=[failed("frontier")]), self.row(141, mergeable="CONFLICTING")],
                "conflict",
                141,
            ),
            (
                [self.row(142, checks=[failed("frontier")]), self.row(143, unresolved_threads=1)],
                "threads",
                143,
            ),
            (
                [self.row(144, review_decision="CHANGES_REQUESTED"), self.row(145, checks=[failed("upper")])],
                "failing_checks",
                145,
            ),
            (
                [
                    self.row(146, checks=[pending("frontier")]),
                    {
                        "owner": self.OWNER,
                        "repo": self.REPO,
                        "pr": 147,
                        "head_sha": HEAD,
                        "state": "CLOSED",
                    },
                ],
                "review_merge_gate",
                147,
            ),
        ]
        for rows, tier, blocker_pr in cases:
            with self.subTest(tier=tier):
                state = readiness.initialize_queue(
                    self.identities(rows[0]["pr"], rows[1]["pr"])
                )
                result = readiness.apply_queue_snapshot(state, rows)
                self.assertEqual(result["event"]["kind"], "BLOCKER")
                self.assertTrue(result["event"]["terminal"])
                self.assertEqual(result["event"]["reason"]["tier"], tier)
                self.assertEqual(result["event"]["blocker"]["pr"], blocker_pr)
                self.assertEqual(result["state"]["phase"], "blocked")

    def test_advance_is_nonterminal_and_state_transition_is_immutable(self) -> None:
        initial = readiness.initialize_queue(self.identities(150, 151, 152))
        first = readiness.apply_queue_snapshot(initial, self.rows(150, 151, 152))
        self.assertEqual(first["event"]["kind"], "WAITING")
        waiting_state = first["state"]
        before = copy.deepcopy(waiting_state)

        rows = [
            self.merged(150),
            self.row(151),
            self.row(152, checks=[pending("top")]),
        ]
        second = readiness.apply_queue_snapshot(waiting_state, rows)
        self.assertEqual(waiting_state, before)
        self.assertEqual(second["event"]["kind"], "ADVANCE")
        self.assertFalse(second["event"]["terminal"])
        self.assertEqual(second["event"]["previous_frontier"]["pr"], 150)
        self.assertEqual(second["event"]["frontier"]["pr"], 151)
        self.assertEqual(
            second["event"]["newly_merged"], self.observed_identities(150)
        )
        self.assertEqual(second["state"]["generation"], 2)
        self.assertEqual(
            [entry["kind"] for entry in second["state"]["history"]],
            ["INITIALIZED", "WAITING", "ADVANCE"],
        )

        third = readiness.apply_queue_snapshot(second["state"], rows)
        self.assertEqual(third["event"]["kind"], "WAITING")
        self.assertEqual(third["event"]["frontier"]["pr"], 151)
        self.assertEqual(third["event"]["reason"]["kind"], "merge_queue")

    def test_complete_requires_every_frozen_row_merged(self) -> None:
        state = readiness.initialize_queue(self.identities(160, 161))
        partial = readiness.apply_queue_snapshot(
            state, [self.merged(160), self.row(161)]
        )
        self.assertEqual(partial["event"]["kind"], "ADVANCE")
        self.assertNotEqual(partial["state"]["phase"], "complete")

        complete = readiness.apply_queue_snapshot(
            partial["state"], [self.merged(160), self.merged(161)]
        )
        self.assertEqual(complete["event"]["kind"], "COMPLETE")
        self.assertTrue(complete["event"]["terminal"])
        self.assertEqual(complete["state"]["phase"], "complete")
        self.assertIsNone(complete["state"]["frontier"])
        self.assertEqual(complete["state"]["frozen"], self.identities(160, 161))
        self.assertEqual(
            complete["state"]["merged"], self.observed_identities(160, 161)
        )
        with self.assertRaisesRegex(readiness.InputError, "terminal event"):
            readiness.apply_queue_snapshot(
                complete["state"], [self.merged(160), self.merged(161)]
            )

    def test_closed_without_merge_is_terminal(self) -> None:
        state = readiness.initialize_queue(self.identities(170, 171))
        result = readiness.apply_queue_snapshot(
            state,
            [
                {
                    "owner": self.OWNER,
                    "repo": self.REPO,
                    "pr": 170,
                    "head_sha": HEAD,
                    "state": "CLOSED",
                },
                self.row(171),
            ],
        )
        self.assertEqual(result["event"]["kind"], "BLOCKER")
        self.assertEqual(result["event"]["reason"]["kind"], "closed_without_merge")
        self.assertTrue(result["event"]["terminal"])

    def test_merged_frozen_rows_must_remain_present_and_cannot_reopen(self) -> None:
        state = readiness.initialize_queue(self.identities(180, 181))
        advanced = readiness.apply_queue_snapshot(
            state, [self.merged(180), self.row(181)]
        )
        with self.assertRaisesRegex(readiness.InputError, "every frozen row"):
            readiness.apply_queue_snapshot(advanced["state"], [self.row(181)])
        with self.assertRaisesRegex(readiness.InputError, "must remain represented"):
            readiness.apply_queue_snapshot(
                advanced["state"], [self.row(180), self.row(181)]
            )
        waiting = readiness.apply_queue_snapshot(
            advanced["state"], [self.merged(180), self.row(181)]
        )
        self.assertEqual(waiting["state"]["frozen"], self.identities(180, 181))
        self.assertEqual(waiting["state"]["merged"], self.observed_identities(180))

    def test_history_is_bounded_while_generation_remains_monotonic(self) -> None:
        state = readiness.initialize_queue(self.identities(190))
        for _ in range(readiness.MAX_QUEUE_HISTORY + 3):
            result = readiness.apply_queue_snapshot(state, self.rows(190))
            state = result["state"]
        self.assertEqual(state["generation"], readiness.MAX_QUEUE_HISTORY + 3)
        self.assertEqual(len(state["history"]), readiness.MAX_QUEUE_HISTORY)
        self.assertEqual(
            state["history_start_generation"],
            state["generation"] - readiness.MAX_QUEUE_HISTORY + 1,
        )
        self.assertEqual(state["history"][-1]["generation"], state["generation"])


class PrReadinessCliTests(unittest.TestCase):
    def test_queue_init_and_apply_are_deterministic_json_operations(self) -> None:
        init_input = {
            "operation": "queue_init",
            "frozen": [
                {"owner": "owner", "repo": "repo", "pr": 200},
                {"owner": "owner", "repo": "repo", "pr": 201},
            ],
        }
        stdout = io.StringIO()
        with mock.patch.object(
            sys, "stdin", io.StringIO(json.dumps(init_input))
        ), contextlib.redirect_stdout(stdout):
            self.assertEqual(readiness.main([]), 0)
        initialized = json.loads(stdout.getvalue())
        self.assertEqual(initialized["event"]["kind"], "INITIALIZED")

        first = snapshot(200)
        first.update(owner="owner", repo="repo")
        second = changed(201, checks=[pending("upper")])
        second.update(owner="owner", repo="repo")
        apply_input = {
            "operation": "queue_apply",
            "queue_state": initialized["state"],
            "stack": [first, second],
        }
        outputs = []
        for _ in range(2):
            stdout = io.StringIO()
            with mock.patch.object(
                sys, "stdin", io.StringIO(json.dumps(apply_input))
            ), contextlib.redirect_stdout(stdout):
                self.assertEqual(readiness.main([]), 0)
            outputs.append(stdout.getvalue())
        self.assertEqual(outputs[0], outputs[1])
        applied = json.loads(outputs[0])
        self.assertEqual(applied["event"]["kind"], "WAITING")
        self.assertEqual(applied["event"]["frontier"]["pr"], 200)

    def test_reads_single_file_and_stack_stdin_and_always_emits_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "snapshot.json"
            source.write_text(json.dumps(snapshot()), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = readiness.main([str(source)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["status"], "ready")

        stack_input = io.StringIO(
            json.dumps(
                {
                    "contract_version": readiness.CONTRACT_VERSION,
                    "stack": [changed(80), changed(81)],
                }
            )
        )
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdin", stack_input), contextlib.redirect_stdout(
            stdout
        ):
            code = readiness.main([])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "clear")

        stderr = io.StringIO()
        with mock.patch.object(
            sys, "stdin", io.StringIO("not json")
        ), contextlib.redirect_stderr(stderr):
            code = readiness.main([])
        self.assertEqual(code, 2)
        error = json.loads(stderr.getvalue())
        self.assertEqual(error["status"], "error")
        self.assertFalse(error["babysit_ready"])
        self.assertFalse(error["provider_landing_gate_clear"])


if __name__ == "__main__":
    unittest.main()
