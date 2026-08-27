from __future__ import annotations

import concurrent.futures
import contextlib
import importlib.util
import io
import json
import stat
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins" / "codexstack" / "skills" / "work" / "scripts" / "state.py"
SPEC = importlib.util.spec_from_file_location("codexstack_state", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(state)


TOKEN = "coordinator-writer-token-for-tests"
SHA_A = "a" * 40
SHA_B = "b" * 40


class StateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name) / "program"
        self.store, returned = state.StateStore.initialize(self.directory, actor="lead", token=TOKEN)
        self.assertEqual(returned, TOKEN)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def raw_state(self) -> dict:
        return json.loads((self.directory / state.STATE_FILE).read_text(encoding="utf-8"))

    def events(self) -> list[dict]:
        return [json.loads(line) for line in (self.directory / state.LOG_FILE).read_text(encoding="utf-8").splitlines()]

    def create_running(self, unit_id: str = "api") -> dict:
        self.store.unit(
            unit_id,
            "scoped",
            "lead",
            track="core",
            owner="worker-1",
            branch=f"work/{unit_id}",
            worktree=f"trees/{unit_id}",
            pr=17,
            head_sha=SHA_A,
            brief=f"briefs/{unit_id}.md",
        )
        self.store.unit(unit_id, "ready", "lead")
        return self.store.unit(unit_id, "running", "lead")

    def test_initialize_is_private_atomic_and_derives_status_frontier(self) -> None:
        for name in state.REQUIRED_DIRECTORIES:
            child = self.directory / name
            self.assertTrue(child.is_dir())
            self.assertEqual(stat.S_IMODE(child.stat().st_mode), 0o700)
        for name in (state.STATE_FILE, state.LOG_FILE, state.STATUS_FILE, state.FRONTIER_FILE):
            self.assertEqual(stat.S_IMODE((self.directory / name).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o700)
        raw = self.raw_state()
        self.assertEqual(raw["contract_version"], state.CONTRACT_VERSION)
        self.assertEqual(raw["revision"], 0)
        self.assertEqual(raw["inbox"], {})
        self.assertNotEqual(raw["writer"]["digest"], TOKEN)
        self.assertNotIn(TOKEN, (self.directory / state.STATE_FILE).read_text(encoding="utf-8"))
        self.assertEqual(self.events()[0]["event"], "init")
        self.assertEqual(json.loads((self.directory / state.FRONTIER_FILE).read_text())["generation"], 0)
        markdown = (self.directory / state.STATUS_FILE).read_text(encoding="utf-8")
        self.assertIn("# CodexStack program status", markdown)
        self.assertNotIn("\N{EM DASH}", markdown)

    def test_capability_and_immutable_decisions(self) -> None:
        with self.assertRaisesRegex(state.StateError, "writer token is invalid"):
            state.StateStore(self.directory, "wrong").gate("review", "pending", "worker")
        with self.assertRaisesRegex(state.StateError, "writer token is required"):
            state.StateStore(self.directory).unit("u", "scoped", "worker")
        first = self.store.decision("storage", "sqlite", "architect", "single writer")
        revision = self.store.status()["revision"]
        self.assertEqual(self.store.decision("storage", "sqlite", "architect", "single writer"), first)
        self.assertEqual(self.store.status()["revision"], revision)
        with self.assertRaisesRegex(state.StateError, "immutable"):
            self.store.decision("storage", "postgres", "architect", "changed")

    def test_unit_contract_strict_transitions_and_dependency_frontier(self) -> None:
        base = self.store.unit(
            "base",
            "scoped",
            "lead",
            track="core",
            owner="agent-a",
            branch="work/base",
            worktree="trees/base",
            pr=11,
            head_sha=SHA_A,
            brief="briefs/base.md",
        )
        self.assertEqual(base["attempt"], 1)
        self.assertEqual(base["track"], "core")
        self.assertEqual(base["dependencies"], [])
        self.assertEqual(base["head_sha"], SHA_A)
        self.assertEqual(base["branch"], "work/base")
        self.assertEqual(base["worktree"], "trees/base")
        self.assertEqual(base["pr"], 11)
        self.assertEqual(base["brief"], "briefs/base.md")
        self.store.unit("base", "ready", "lead")
        downstream = self.store.unit("downstream", "ready", "lead", track="core", dependencies=["base"])
        self.assertEqual(downstream["dependencies"], ["base"])
        before = self.store.frontier()
        self.assertEqual(before["ready"], ["base"])
        self.assertEqual(before["blocked"], ["downstream"])
        self.assertEqual(before["blocked_reasons"]["downstream"], "waiting-for:base")
        self.store.unit("base", "running", "lead")
        self.store.unit("base", "needs-verify", "lead")
        self.store.unit("base", "verified", "lead")
        self.store.unit("base", "landed", "lead")
        frontier = self.store.frontier()
        self.assertEqual(frontier["ordered_targets"], ["base", "downstream"])
        self.assertEqual(frontier["ready"], ["downstream"])
        self.assertEqual(frontier["landed"], ["base"])
        self.assertEqual(frontier["unintegrated"], ["downstream"])
        self.assertFalse(frontier["all_landed"])
        self.assertIsNone(frontier["lowest_unintegrated"])
        self.assertIsNone(frontier["contiguous_landed"])
        self.assertIsNone(frontier["contiguous_complete"])
        with self.assertRaisesRegex(state.StateError, "illegal unit transition"):
            self.store.unit("base", "running", "lead")
        with self.assertRaisesRegex(state.StateError, "unknown dependency"):
            self.store.unit("bad", "scoped", "lead", dependencies=["unknown"])
        with self.assertRaisesRegex(state.StateError, "dependencies.*immutable"):
            self.store.unit("downstream", "ready", "lead", dependencies=[])

    def test_exact_sha_verdicts_are_enum_constrained_and_idempotent(self) -> None:
        self.store.unit("api-a", "scoped", "lead", pr=17, head_sha=SHA_A)
        self.store.unit("api-b", "scoped", "lead", pr=17, head_sha=SHA_B)
        first = self.store.verify(17, SHA_A.upper(), "PASS", "verifier", proof="tests", unit="api-a")
        self.assertEqual(first["key"], f"17@{SHA_A}")
        revision = self.store.status()["revision"]
        self.assertEqual(self.store.verify(17, SHA_A, "PASS", "verifier", proof="tests", unit="api-a"), first)
        self.assertEqual(self.store.status()["revision"], revision)
        changed = self.store.verify(17, SHA_A, "PASS+NOTES", "verifier-2", proof="regression", unit="api-a")
        self.assertEqual(changed["attempt"], 2)
        second_head = self.store.verify(17, SHA_B, "FAIL", "verifier", unit="api-b")
        self.assertEqual(second_head["key"], f"17@{SHA_B}")
        with self.assertRaisesRegex(state.StateError, "verdict must be one of"):
            self.store.verify(17, SHA_A, "ISSUES", "verifier", unit="api-a")
        with self.assertRaisesRegex(state.StateError, "full 40- or 64-character"):
            self.store.verify(17, "abc", "PASS", "verifier", unit="api-a")

    def test_verification_must_link_to_a_current_known_unit_pr_and_head(self) -> None:
        self.store.unit("linked", "scoped", "lead", pr=7, head_sha=SHA_A)
        with self.assertRaisesRegex(state.StateError, "unit is required"):
            self.store.verify(7, SHA_A, "PASS", "verifier")
        with self.assertRaisesRegex(state.StateError, "unit missing is unknown"):
            self.store.verify(7, SHA_A, "PASS", "verifier", unit="missing")
        with self.assertRaisesRegex(state.StateError, "exactly match"):
            self.store.verify(8, SHA_A, "PASS", "verifier", unit="linked")
        with self.assertRaisesRegex(state.StateError, "exactly match"):
            self.store.verify(7, SHA_B, "PASS", "verifier", unit="linked")
        verified = self.store.verify(7, SHA_A, "PASS", "verifier", unit="linked")
        self.assertEqual(verified["unit"], "linked")

    def test_frontier_contiguous_verified_uses_ledger_current_head_and_dependencies(self) -> None:
        self.store.unit("base", "verified", "lead", pr=1, head_sha=SHA_A)
        self.store.unit("child", "verified", "lead", dependencies=["base"], pr=2, head_sha=SHA_B)
        self.store.unit("revision", "running", "lead", dependencies=["child"], pr=3, head_sha=SHA_A)
        self.store.topology("stack", "lead", stack_ids=["base", "child", "revision"])
        frontier = self.store.frontier()
        self.assertEqual(frontier["contiguous_verified"], [])
        self.assertEqual(frontier["contiguous_landed"], [])
        self.assertEqual(frontier["lowest_unintegrated"], "base")
        self.assertFalse(frontier["contiguous_complete"])

        self.store.verify(2, SHA_B, "PASS+NOTES", "verifier", unit="child")
        self.assertEqual(self.store.frontier()["contiguous_verified"], [])

        self.store.verify(1, SHA_A, "PASS", "verifier", unit="base")
        self.assertEqual(self.store.frontier()["ordered_targets"], ["base", "child", "revision"])
        self.assertEqual(self.store.frontier()["contiguous_verified"], ["base", "child"])
        self.assertEqual(self.store.frontier()["verified_ready"], ["base", "child"])
        self.store.verify(3, SHA_A, "PASS", "verifier", unit="revision")
        self.assertEqual(self.store.frontier()["contiguous_verified"], ["base", "child", "revision"])

        self.store.unit("revision", "running", "lead", head_sha=SHA_B)
        self.assertEqual(self.store.frontier()["contiguous_verified"], ["base", "child"])
        self.store.verify(3, SHA_B, "PASS", "verifier", unit="revision")
        self.assertEqual(self.store.frontier()["contiguous_verified"], ["base", "child", "revision"])
        self.store.verify(3, SHA_B, "FAIL", "verifier", unit="revision")
        self.assertEqual(self.store.frontier()["contiguous_verified"], ["base", "child"])

        self.store.stop("hold", "lead")
        frontier = self.store.frontier()
        self.assertEqual(frontier["contiguous_verified"], [])
        self.assertTrue(frontier["stop_requested"])

    def test_dag_uses_verified_ready_without_an_arbitrary_verified_prefix(self) -> None:
        self.store.unit("alpha", "scoped", "lead", pr=1, head_sha=SHA_A)
        self.store.unit("beta", "scoped", "lead", pr=2, head_sha=SHA_B)
        self.store.unit("join", "scoped", "lead", dependencies=["alpha", "beta"], pr=3, head_sha="c" * 40)
        self.assertEqual(self.store.frontier()["topology_mode"], "dag")
        self.assertIsNone(self.store.frontier()["contiguous_verified"])

        self.store.verify(2, SHA_B, "PASS", "verifier", unit="beta")
        self.assertEqual(self.store.frontier()["verified_ready"], ["beta"])
        self.store.verify(1, SHA_A, "PASS", "verifier", unit="alpha")
        self.assertEqual(self.store.frontier()["verified_ready"], ["alpha", "beta"])
        self.store.verify(3, "c" * 40, "PASS+NOTES", "verifier", unit="join")
        self.assertEqual(self.store.frontier()["verified_ready"], ["alpha", "beta", "join"])

        self.store.unit("beta", "ready", "lead")
        self.store.unit("beta", "running", "lead")
        self.store.unit("beta", "needs-verify", "lead")
        self.store.unit("beta", "verified", "lead")
        self.store.unit("beta", "landed", "lead")
        frontier = self.store.frontier()
        self.assertEqual(frontier["landed"], ["beta"])
        self.assertEqual(frontier["unintegrated"], ["alpha", "join"])
        self.assertIsNone(frontier["lowest_unintegrated"])
        self.assertIsNone(frontier["contiguous_landed"])

    def test_stack_topology_rejects_reorder_branch_gap_and_late_additions(self) -> None:
        self.store.unit("base", "scoped", "lead")
        self.store.unit("child", "scoped", "lead", dependencies=["base"])
        with self.assertRaisesRegex(state.StateError, "single linear predecessor chain"):
            self.store.topology("stack", "lead", stack_ids=["child", "base"])
        self.store.topology("stack", "lead", stack_ids=["base", "child"])
        with self.assertRaisesRegex(state.StateError, "frozen"):
            self.store.topology("stack", "lead", stack_ids=["child", "base"])
        with self.assertRaisesRegex(state.StateError, "cannot add a unit"):
            self.store.unit("late", "scoped", "lead")

        other = Path(self.temporary.name) / "branched"
        other_store, _ = state.StateStore.initialize(other, actor="lead", token="branch-token")
        other_store.unit("base", "scoped", "lead")
        other_store.unit("left", "scoped", "lead", dependencies=["base"])
        other_store.unit("right", "scoped", "lead", dependencies=["base"])
        with self.assertRaisesRegex(state.StateError, "single linear predecessor chain"):
            other_store.topology("stack", "lead", stack_ids=["base", "left", "right"])
        with self.assertRaisesRegex(state.StateError, "every unit exactly once"):
            other_store.topology("stack", "lead", stack_ids=["base", "left"])

    def test_inbox_enqueue_and_drain_are_atomic_exactly_once_under_concurrency(self) -> None:
        self.create_running()

        def enqueue_once(_: int) -> dict:
            return state.StateStore(self.directory, TOKEN).enqueue(
                "event-1", "api", "lead", report="finished", metadata={"proof": "x"}, head_sha=SHA_A
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            returned = list(executor.map(enqueue_once, range(16)))
        self.assertTrue(all(item["id"] == "event-1" for item in returned))
        self.assertEqual(len(self.store.snapshot()["inbox"]), 1)

        def drain_once(_: int) -> int:
            return state.StateStore(self.directory, TOKEN).drain("lead")["count"]

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            counts = list(executor.map(drain_once, range(4)))
        self.assertEqual(sum(counts), 1)
        self.assertEqual(self.store.drain("lead"), {"events": [], "count": 0})
        with self.assertRaisesRegex(state.StateError, "immutable"):
            self.store.enqueue("event-1", "api", "lead", report="different")

    def test_retry_is_bounded_and_lease_liveness_is_explicit_read_only(self) -> None:
        self.create_running("retryable")
        lease = self.store.lease("retryable", "worker-1", 60, evidence="commit observed")
        self.assertEqual(lease["lease"]["holder"], "worker-1")
        revision = self.store.status()["revision"]
        live = self.store.lease_status("retryable")
        self.assertFalse(live["expired"])
        self.assertEqual(self.store.status()["revision"], revision)
        self.store.unit("retryable", "failed", "lead")
        first = self.store.retry("retryable", "lead", "transient")
        self.assertEqual((first["attempt"], first["retry_count"], first["state"]), (2, 1, "ready"))
        self.assertEqual(self.store.retry("retryable", "lead", "transient"), first)
        self.store.unit("retryable", "running", "lead")
        self.store.unit("retryable", "failed", "lead")
        second = self.store.retry("retryable", "lead", "resource", retry_id="retry-2")
        self.assertEqual((second["attempt"], second["retry_count"]), (3, 2))
        self.store.unit("retryable", "running", "lead")
        self.store.unit("retryable", "failed", "lead")
        with self.assertRaisesRegex(state.StateError, "retry limit"):
            self.store.retry("retryable", "lead", "third", retry_id="retry-3")

    def test_stop_blocks_every_progress_mutation_and_allows_late_reconciliation_only(self) -> None:
        self.create_running("late")
        self.store.stop("operator hold", "lead")
        revision = self.store.status()["revision"]
        for operation in (
            lambda: self.store.unit("late", "needs-verify", "lead"),
            lambda: self.store.verify(17, SHA_A, "PASS", "verifier", unit="late"),
            lambda: self.store.enqueue("event-after-stop", "late", "lead"),
            lambda: self.store.drain("lead"),
            lambda: self.store.lease("late", "lead", 60),
            lambda: self.store.gate("review", "pending", "lead"),
            lambda: self.store.decision("ship", "no", "lead"),
        ):
            with self.assertRaisesRegex(state.StateError, "stop blocks product-progress"):
                operation()
        self.assertTrue(self.store.check_stop()["requested"])
        self.assertEqual(self.store.status()["revision"], revision)
        reconciled = self.store.reconcile(
            "late-after-stop",
            "zombie",
            "lead",
            unit_id="late",
            unit_state="zombie-reconciled",
            report="late completion",
            metadata={"head": SHA_A},
            head_sha=SHA_A,
        )
        self.assertEqual(reconciled["reconciliation"]["classification"], "zombie")
        self.assertEqual(self.store.snapshot()["units"]["late"]["state"], "zombie-reconciled")
        self.assertEqual(self.store.frontier()["ready"], [])
        revision = self.store.status()["revision"]
        self.assertEqual(self.store.stop("operator hold", "lead")["requested"], True)
        self.assertEqual(self.store.status()["revision"], revision)
        with self.assertRaisesRegex(state.StateError, "stop blocks product-progress"):
            self.store.unit("late", "zombie-reconciled", "lead")

    def test_release_stop_is_explicit_audited_and_restores_progress_writes(self) -> None:
        self.create_running("held")
        with self.assertRaisesRegex(state.StateError, "stop is not requested"):
            self.store.release_stop(
                "resume", "lead", evidence_category="operator-authorization", evidence="ticket-1"
            )
        self.store.stop("operator hold", "lead")
        with self.assertRaisesRegex(state.StateError, "evidence category must not be empty"):
            self.store.release_stop("resume", "lead", evidence="ticket-1")
        with self.assertRaisesRegex(state.StateError, "release evidence must not be empty"):
            self.store.release_stop("resume", "lead", evidence_category="operator-authorization")
        with self.assertRaisesRegex(state.StateError, "evidence category must be one of"):
            self.store.release_stop("resume", "lead", evidence_category="informal", evidence="ticket-1")
        with self.assertRaisesRegex(state.StateError, "stop blocks product-progress"):
            self.store.gate("held-gate", "pending", "lead")
        reconciled = self.store.reconcile("held-late", "observed", "lead", unit_id="held")
        self.assertEqual(reconciled["reconciliation"]["classification"], "observed")

        released = self.store.release_stop(
            "operator authorization received",
            "lead",
            evidence_category="operator-authorization",
            evidence="approval ticket 42",
        )
        self.assertEqual(released["event"], "release-stop")
        self.assertFalse(self.store.check_stop()["requested"])
        history = self.store.check_stop()["history"]
        self.assertEqual([entry["event"] for entry in history], ["stop", "release-stop"])
        self.assertEqual(history[0]["reason"], "operator hold")
        self.assertEqual(history[1]["released_stop"], {"reason": "operator hold", "timestamp": history[0]["timestamp"], "actor": "lead"})
        self.assertEqual(history[1]["evidence_category"], "operator-authorization")
        self.store.gate("held-gate", "pending", "lead")

        self.store.stop("systemic verification hold", "lead")
        self.store.release_stop(
            "system repaired",
            "lead",
            evidence_category="repaired-systemic-cause",
            evidence="incident 9 repaired and verified",
        )
        history = self.store.snapshot()["stop_history"]
        self.assertEqual([entry["event"] for entry in history], ["stop", "release-stop", "stop", "release-stop"])
        self.assertEqual(history[-1]["evidence_category"], "repaired-systemic-cause")
        audited = [event["event"] for event in self.events() if event["event"] in {"stop", "release-stop"}]
        self.assertEqual(audited, ["stop", "release-stop", "stop", "release-stop"])

    def test_corrupt_unknown_and_unrecognized_schema_fail_closed(self) -> None:
        self.create_running()
        path = self.directory / state.STATE_FILE
        path.write_text("not json", encoding="utf-8")
        with self.assertRaisesRegex(state.StateError, "cannot read valid state"):
            self.store.status()

        other = Path(self.temporary.name) / "other"
        other_store, _ = state.StateStore.initialize(other, actor="lead", token="other-token")
        other_store.unit("u", "scoped", "lead")
        raw = json.loads((other / state.STATE_FILE).read_text(encoding="utf-8"))
        raw["units"]["u"]["state"] = "mystery"
        (other / state.STATE_FILE).write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(state.StateError, "invalid unit state"):
            other_store.status()

        versioned = Path(self.temporary.name) / "versioned"
        versioned_store, _ = state.StateStore.initialize(versioned, actor="lead", token="version-token")
        raw = json.loads((versioned / state.STATE_FILE).read_text(encoding="utf-8"))
        raw["contract_version"] = "codexstack.state.v1"
        (versioned / state.STATE_FILE).write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(state.StateError, "contract version is unsupported"):
            versioned_store.status()

    def test_symlinked_roots_directories_and_files_are_rejected(self) -> None:
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        linked_root = Path(self.temporary.name) / "linked-root"
        linked_root.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(state.StateError, "state directory must not be a symlink"):
            state.StateStore.initialize(linked_root, actor="lead", token="another-token")

        required_link = self.directory / "briefs"
        required_link.rmdir()
        required_link.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(state.StateError, "required directory briefs must not be a symlink"):
            self.store.status()

        clean = Path(self.temporary.name) / "clean"
        clean_store, _ = state.StateStore.initialize(clean, actor="lead", token="clean-token")
        external_state = Path(self.temporary.name) / "external-state.json"
        external_state.write_text("{}", encoding="utf-8")
        (clean / state.STATE_FILE).unlink()
        (clean / state.STATE_FILE).symlink_to(external_state)
        with self.assertRaisesRegex(state.StateError, "state.json must not be a symlink"):
            clean_store.status()

    def test_no_scheduling_implementation(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("subprocess", source)
        self.assertNotIn("threading.Thread", source)
        self.assertNotIn("time.sleep", source)


class StateCliTests(unittest.TestCase):
    def test_cli_round_trip_new_frontier_and_stop_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = str(Path(temporary) / "program")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = state.main(["--dir", directory, "--actor", "lead", "--token", TOKEN, "init"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["result"]["writer_token"], TOKEN)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = state.main([
                    "--dir", directory, "--actor", "lead", "--token", TOKEN, "unit", "api", "scoped",
                    "--track", "core", "--branch", "work/api", "--worktree", "trees/api", "--pr", "9",
                    "--head-sha", SHA_A, "--brief", "briefs/api.md",
                ])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["result"]["head_sha"], SHA_A)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = state.main(["--dir", directory, "frontier"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["result"]["ordered_targets"], ["api"])
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = state.main(["--dir", directory, "--actor", "lead", "--token", TOKEN, "stop", "--reason", "pause"])
            self.assertEqual(code, 0)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = state.main(["--dir", directory, "check-stop"])
            self.assertEqual(code, state.STOP_EXIT_CODE)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = state.main([
                    "--dir", directory, "--actor", "lead", "--token", TOKEN, "release-stop",
                    "--reason", "approved", "--evidence-category", "operator-authorization",
                    "--evidence", "ticket-42",
                ])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["result"]["evidence_category"], "operator-authorization")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = state.main(["--dir", directory, "check-stop"])
            self.assertEqual(code, 0)
            self.assertFalse(json.loads(output.getvalue())["result"]["requested"])


if __name__ == "__main__":
    unittest.main()
