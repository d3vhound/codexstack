from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "plugins" / "codexstack" / "runtime"
sys.path.insert(0, str(RUNTIME))

from codexstack_control import model  # noqa: E402


def worker_value(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "contractVersion": "codexstack.worker.v1",
        "baseRef": "main",
        "workingDirectory": ".",
        "setup": [["python3", "-m", "pip", "install", "-e", "."]],
        "verify": [["python3", "-m", "unittest"]],
        "preview": {"command": ["python3", "-m", "http.server", "4173"], "port": 4173},
    }
    value.update(changes)
    return value


def worker_json(**changes: object) -> str:
    return json.dumps(worker_value(**changes))


def start_value(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "repo": "octocat/control-fixture",
        "goal": "Fix the exact regression and prove it.",
        "baseRef": "main",
        "model": "gpt-5.6-sol",
        "reasoningEffort": "high",
        "ttlSeconds": 7200,
        "idempotencyKey": "fixture-start-0001",
        "delivery": "open_pull_request",
    }
    value.update(changes)
    return value


class WorkerContractTests(unittest.TestCase):
    def test_full_contract_round_trips_to_canonical_hash(self) -> None:
        first = model.WorkerConfig.parse(worker_json())
        reordered = {
            "verify": [["python3", "-m", "unittest"]],
            "preview": {"port": 4173, "command": ["python3", "-m", "http.server", "4173"]},
            "setup": [["python3", "-m", "pip", "install", "-e", "."]],
            "workingDirectory": ".",
            "baseRef": "main",
            "contractVersion": "codexstack.worker.v1",
        }
        second = model.WorkerConfig.parse(json.dumps(reordered))

        self.assertEqual(first, second)
        self.assertEqual(first.sha256(), second.sha256())
        self.assertEqual(json.loads(first.canonical_json()), first.to_dict())
        self.assertEqual(first.preview.port, 4173)  # type: ignore[union-attr]
        self.assertIsInstance(first.setup[0], tuple)

    def test_minimal_contract_supplies_safe_optional_defaults(self) -> None:
        parsed = model.WorkerConfig.parse(
            json.dumps(
                {
                    "contractVersion": "codexstack.worker.v1",
                    "baseRef": "release/v1",
                    "setup": [],
                    "verify": [],
                }
            )
        )
        self.assertEqual(parsed.working_directory, ".")
        self.assertIsNone(parsed.preview)
        self.assertEqual(parsed.setup, ())
        self.assertEqual(parsed.verify, ())

    def test_json_is_bounded_object_without_duplicates_or_unknown_fields(self) -> None:
        invalid = (
            "[]",
            '{"contractVersion":"codexstack.worker.v1","contractVersion":"other",'
            '"baseRef":"main","setup":[],"verify":[]}',
            worker_json(extra="not allowed"),
            worker_json(contractVersion="codexstack.worker.v2"),
            worker_json(baseRef=None),
        )
        for raw in invalid:
            with self.subTest(raw=raw[:80]):
                with self.assertRaises(model.ContractError):
                    model.WorkerConfig.parse(raw)

        oversized = json.dumps(
            {
                "contractVersion": "codexstack.worker.v1",
                "baseRef": "main",
                "setup": [],
                "verify": [],
                "padding": "x" * model.MAX_WORKER_BYTES,
            }
        )
        with self.assertRaisesRegex(model.ContractError, "exceeds"):
            model.WorkerConfig.parse(oversized)

    def test_refs_and_working_directories_cannot_escape_or_smuggle_git_syntax(self) -> None:
        for value in ("../main", ".hidden", "main..other", "main@{1}", "main lock", "a\\b", "x.lock", "--upload-pack=bad"):
            with self.subTest(base=value):
                with self.assertRaisesRegex(model.ContractError, "safe Git"):
                    model.WorkerConfig.parse(worker_json(baseRef=value))

        for value in ("/tmp", "../app", "packages/../../secret", "~/repo"):
            with self.subTest(directory=value):
                with self.assertRaisesRegex(model.ContractError, "inside the repository"):
                    model.WorkerConfig.parse(worker_json(workingDirectory=value))

    def test_commands_are_argument_arrays_with_bounded_shape(self) -> None:
        invalid_setup = (
            "npm test",
            [[]],
            [["", "test"]],
            [["python3", None]],
            [["x\x00y"]],
            [["x"] * 65],
            [["x"], *[["x"] for _ in range(32)]],
        )
        for setup in invalid_setup:
            with self.subTest(setup=repr(setup)[:80]):
                with self.assertRaises(model.ContractError):
                    model.WorkerConfig.parse(worker_json(setup=setup))

    def test_preview_requires_exact_command_and_port_contract(self) -> None:
        invalid = (
            {},
            {"command": ["serve"]},
            {"port": 3000},
            {"command": "serve", "port": 3000},
            {"command": ["serve"], "port": True},
            {"command": ["serve"], "port": 0},
            {"command": ["serve"], "port": 65536},
            {"command": ["serve"], "port": 3000, "host": "0.0.0.0"},
        )
        for preview in invalid:
            with self.subTest(preview=preview):
                with self.assertRaises(model.ContractError):
                    model.WorkerConfig.parse(worker_json(preview=preview))


class StartContractTests(unittest.TestCase):
    def test_start_request_parses_strictly_and_applies_defaults(self) -> None:
        parsed = model.StartRequest.parse(
            {
                "repo": "octocat/control-fixture",
                "goal": "Inspect only",
                "idempotencyKey": "fixture-key",
            },
            default_ttl=43200,
        )
        self.assertEqual(parsed.ttl_seconds, 43200)
        self.assertEqual(parsed.delivery, "open_pull_request")
        self.assertIsNone(parsed.base_ref)
        self.assertIsNone(parsed.model)
        self.assertIsNone(parsed.reasoning_effort)

    def test_start_request_rejects_unknown_missing_and_unsafe_values(self) -> None:
        cases = (
            {**start_value(), "unexpected": True},
            {key: value for key, value in start_value().items() if key != "repo"},
            start_value(repo="octocat"),
            start_value(repo="../repo"),
            start_value(baseRef="main..old"),
            start_value(model="gpt model"),
            start_value(reasoningEffort="High"),
            start_value(ttlSeconds=True),
            start_value(ttlSeconds=59),
            start_value(idempotencyKey="short"),
            start_value(delivery="merge_pull_request"),
        )
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(model.ContractError):
                    model.StartRequest.parse(value, default_ttl=43200)

    def test_goal_limit_is_measured_in_bytes_as_well_as_characters(self) -> None:
        value = start_value(goal="é" * (model.MAX_GOAL_BYTES // 2 + 1))
        with self.assertRaisesRegex(model.ContractError, "bytes"):
            model.StartRequest.parse(value, default_ttl=43200)

    def test_run_and_branch_identity_are_deterministic_and_bounded(self) -> None:
        run_id = model.stable_run_id("fixture-start-0001")
        self.assertRegex(run_id, r"^run_[0-9a-f]{20}$")
        self.assertEqual(run_id, model.stable_run_id("fixture-start-0001"))
        branch = model.branch_name(run_id, "Fix: Exact / Auth Regression !!!")
        self.assertRegex(branch, r"^codexstack/[0-9a-f]{12}-fix-exact-auth-regression$")
        self.assertLessEqual(len(branch), 64)
        self.assertNotIn("fixture-start-0001", branch)

    def test_external_identifiers_are_full_and_strict(self) -> None:
        sha = "a" * 40
        self.assertEqual(model.ensure_sha(sha, "headSha"), sha)
        self.assertEqual(model.ensure_sha("A" * 40, "headSha"), sha)
        for box_id in ("bx_23456789", "bx_abcdefgh", "bx_f7k2q9hd"):
            with self.subTest(box_id=box_id):
                self.assertEqual(model.ensure_box_id(box_id), box_id)
        for box_id in ("bx_AbC123", "bx_0", "bx_abcde0gh"):
            with self.subTest(box_id=box_id):
                with self.assertRaises(model.ContractError):
                    model.ensure_box_id(box_id)
        self.assertEqual(model.ensure_prompt_id("prompt:123"), "prompt:123")
        for value in ("a" * 39, "g" * 40):
            with self.subTest(sha=value):
                with self.assertRaises(model.ContractError):
                    model.ensure_sha(value, "headSha")


if __name__ == "__main__":
    unittest.main()
