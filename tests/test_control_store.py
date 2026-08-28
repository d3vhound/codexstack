from __future__ import annotations

import concurrent.futures
import os
import stat
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "plugins" / "codexstack" / "runtime"
sys.path.insert(0, str(RUNTIME))

from codexstack_control import store  # noqa: E402
from codexstack_control.__main__ import _DatabaseLease  # noqa: E402
from codexstack_control.controller import ControlError  # noqa: E402


def initial(run_id: str, request_hash: str = "request-a", **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": run_id,
        "requestHash": request_hash,
        "repo": "octocat/control-fixture",
        "title": "Fix the test fixture",
        "status": "starting",
        "createdAt": "2026-08-28T12:00:00Z",
        "updatedAt": "2026-08-28T12:00:00Z",
    }
    value.update(changes)
    return value


class RunStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "state" / "control.sqlite3"
        self.store = store.RunStore(self.database)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_schema_is_one_run_table_without_credential_or_ephemeral_url_columns(self) -> None:
        with sqlite3.connect(self.database) as connection:
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(agent_runs)").fetchall()
            }
        self.assertEqual(tables, [("agent_runs",)])
        self.assertNotIn("box_api_key", columns)
        self.assertNotIn("control_token", columns)
        self.assertNotIn("desktop_url", columns)
        self.assertNotIn("preview_url", columns)
        self.assertNotIn("goal", columns)
        self.assertEqual(stat.S_IMODE(self.database.stat().st_mode), 0o600)

    def test_database_process_lease_fails_closed_for_a_second_controller(self) -> None:
        first = _DatabaseLease(self.database)
        try:
            with self.assertRaises(ControlError) as occupied:
                _DatabaseLease(self.database)
            self.assertEqual(occupied.exception.code, "database_in_use")
        finally:
            first.file.close()
        replacement = _DatabaseLease(self.database)
        replacement.file.close()

    def test_database_process_lease_canonicalizes_symlink_aliases(self) -> None:
        alias = Path(self.temporary.name) / "control-alias.sqlite3"
        alias.symlink_to(self.database)
        first = _DatabaseLease(self.database)
        try:
            with self.assertRaises(ControlError) as occupied:
                _DatabaseLease(alias)
            self.assertEqual(occupied.exception.code, "database_in_use")
        finally:
            first.file.close()

    def test_database_process_lease_rejects_hardlink_aliases(self) -> None:
        alias = Path(self.temporary.name) / "control-hardlink.sqlite3"
        first = _DatabaseLease(self.database)
        try:
            os.link(self.database, alias)
            with self.assertRaises(ControlError) as rejected:
                _DatabaseLease(alias)
            self.assertEqual(rejected.exception.code, "invalid_config")
        finally:
            first.file.close()

    def test_create_is_idempotent_and_conflicting_hash_fails_closed(self) -> None:
        first, created = self.store.create(initial("run_" + "a" * 20), max_parallel=4)
        same, created_again = self.store.create(initial("run_" + "a" * 20), max_parallel=4)
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first, same)

        with self.assertRaises(store.StoreConflict):
            self.store.create(initial("run_" + "a" * 20, "request-b"), max_parallel=4)
        self.assertEqual(len(self.store.list()), 1)

    def test_capacity_holds_unreviewed_runs_until_their_box_stops(self) -> None:
        self.store.create(initial("run_" + "a" * 20), max_parallel=2)
        self.store.create(initial("run_" + "b" * 20), max_parallel=2)
        with self.assertRaisesRegex(store.CapacityError, r"2/2"):
            self.store.create(initial("run_" + "c" * 20), max_parallel=2)
        self.store.update("run_" + "a" * 20, status="review")
        with self.assertRaisesRegex(store.CapacityError, r"2/2"):
            self.store.create(initial("run_" + "c" * 20), max_parallel=2)
        self.store.update("run_" + "a" * 20, status="stopped", slotReleased=True)
        third, created = self.store.create(initial("run_" + "c" * 20), max_parallel=2)
        self.assertTrue(created)
        self.assertEqual(third["status"], "starting")
        self.assertEqual(self.store.count_active(), 2)

    def test_concurrent_capacity_admission_never_exceeds_limit(self) -> None:
        def create(index: int) -> str:
            run_id = f"run_{index:020x}"
            try:
                self.store.create(initial(run_id, f"request-{index}"), max_parallel=4)
                return "created"
            except store.CapacityError:
                return "capacity"

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
            outcomes = list(executor.map(create, range(20)))
        self.assertEqual(outcomes.count("created"), 4)
        self.assertEqual(outcomes.count("capacity"), 16)
        self.assertEqual(self.store.count_active(), 4)
        self.assertEqual(len(self.store.list()), 4)

    def test_concurrent_resume_reservations_share_the_same_capacity_gate(self) -> None:
        run_ids = ("run_" + "a" * 20, "run_" + "b" * 20)
        for index, run_id in enumerate(run_ids):
            self.store.create(
                initial(
                    run_id,
                    f"resume-request-{index}",
                    status="stopped",
                    slotReleased=True,
                )
            )

        def reserve(run_id: str) -> str:
            try:
                self.store.reserve(run_id, max_parallel=1)
                return "reserved"
            except store.CapacityError:
                return "capacity"

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(reserve, run_ids))

        self.assertEqual(outcomes.count("reserved"), 1)
        self.assertEqual(outcomes.count("capacity"), 1)
        self.assertEqual(self.store.count_active(), 1)

    def test_records_survive_reopen_and_json_fields_round_trip_canonically(self) -> None:
        run_id = "run_" + "d" * 20
        self.store.create(
            initial(
                run_id,
                workerConfig={"verify": [["python3", "-m", "unittest"]], "baseRef": "main"},
                setupReceipts=[{"success": True, "index": 0}],
            )
        )
        self.store.update(
            run_id,
            verifyReceipts='[{"success":true,"index":0}]',
            promptId="prompt-1",
            boxId="bx_23456789",
        )
        reopened = store.RunStore(self.database)
        record = reopened.get(run_id)
        self.assertEqual(record["workerConfig"]["baseRef"], "main")
        self.assertEqual(record["setupReceipts"], [{"index": 0, "success": True}])
        self.assertEqual(record["verifyReceipts"], [{"index": 0, "success": True}])
        self.assertEqual(record["promptId"], "prompt-1")

    def test_update_allowlist_and_status_enum_are_strict(self) -> None:
        run_id = "run_" + "e" * 20
        self.store.create(initial(run_id))
        with self.assertRaisesRegex(ValueError, "unknown store field"):
            self.store.update(run_id, boxApiKey="private-value")
        with self.assertRaisesRegex(ValueError, "not mutable"):
            self.store.update(run_id, repo="other/repo")
        with self.assertRaisesRegex(ValueError, "status must be"):
            self.store.update(run_id, status="merging")
        with self.assertRaises(store.RunNotFound):
            self.store.update("run_" + "f" * 20, status="stopped")

    def test_list_is_deterministic_bounded_and_paginated(self) -> None:
        for index in range(3):
            self.store.create(
                initial(
                    f"run_{index:020x}",
                    f"request-{index}",
                    createdAt=f"2026-08-28T12:00:0{index}Z",
                    updatedAt=f"2026-08-28T12:00:0{index}Z",
                    status="done",
                )
            )
        self.assertEqual(
            [item["id"] for item in self.store.list(limit=2)],
            ["run_" + f"{2:020x}", "run_" + f"{1:020x}"],
        )
        self.assertEqual(
            [item["id"] for item in self.store.list(limit=2, offset=2)],
            ["run_" + f"{0:020x}"],
        )
        for invalid in (0, 1001, True):
            with self.subTest(limit=invalid):
                with self.assertRaises(ValueError):
                    self.store.list(limit=invalid)


if __name__ == "__main__":
    unittest.main()
