from __future__ import annotations

import json
import shlex
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "plugins" / "codexstack" / "runtime"
sys.path.insert(0, str(RUNTIME))

from codexstack_control import box_client, model  # noqa: E402
from tests.fake_box import BOX_ID, FakeBoxServer  # noqa: E402


class BoxHttpContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeBoxServer().start()
        self.addCleanup(self.fake.close)
        self.client = box_client.BoxClient(
            self.fake.api_key,
            base_url=self.fake.url,
            timeout=2,
        )

    def test_create_uses_bearer_json_and_exact_idempotency_contract(self) -> None:
        limits = self.client.limits()
        created = self.client.create_box(
            "codexstack-base",
            "codexstack",
            7200,
            "fixture-start-0001",
        )
        self.assertTrue(limits["canStart"])
        self.assertEqual(created["type"], "box.created")
        self.assertEqual(created["status"], "provisioning")
        self.assertEqual(created["box"]["id"], BOX_ID)

        request = self.fake.requests_for("POST", "/boxes")[0]
        self.assertEqual(request.headers["authorization"], "Bearer fixture-api-key")
        self.assertEqual(request.headers["accept"], "application/json")
        self.assertEqual(request.headers["content-type"], "application/json")
        self.assertEqual(request.headers["idempotency-key"], "fixture-start-0001")
        self.assertEqual(
            request.body,
            {"from": "codexstack-base", "environment": "codexstack", "ttlSeconds": 7200},
        )

    def test_files_commands_prompts_events_and_lifecycle_use_documented_paths(self) -> None:
        self.client.get_box(BOX_ID)
        worker = self.client.read_file(BOX_ID, "control-fixture/.codexstack/worker.json")
        command = self.client.command(
            BOX_ID,
            ["printf", "%s", "literal; $TOKEN"],
            cwd="/home/user/control-fixture",
            timeout_seconds=600,
            detached=False,
        )
        prompt = self.client.prompt(
            BOX_ID,
            "Run $codexstack:work with `literal` data",
            model="gpt-5.6-sol",
            reasoning_effort="high",
        )
        self.client.prompt_status(BOX_ID, prompt["promptId"])
        self.client.events(BOX_ID, cursor="cursor / opaque", limit=200)
        self.client.interrupt(BOX_ID)
        desktop = self.client.desktop(BOX_ID, theme="dark")
        hosted = self.client.host(BOX_ID, port=4173, title="Fixture preview")
        stopped = self.client.stop(BOX_ID)
        resumed = self.client.resume(BOX_ID, ttl_seconds=7200)

        self.assertEqual(json.loads(worker["content"])["baseRef"], "main")
        self.assertTrue(command["success"])
        self.assertEqual(desktop["desktopUrl"], "https://desktop.example.invalid/session-1")
        self.assertEqual(
            hosted["url"],
            "https://fixture-4173.on.ascii.dev?_token=fixture-preview-token",
        )
        self.assertEqual(stopped["box"]["state"], "archiving")
        self.assertEqual(resumed["box"]["state"], "provisioning")

        command_request = self.fake.requests_for("POST", f"/boxes/{BOX_ID}/commands")[0]
        self.assertEqual(
            command_request.body,
            {
                "command": shlex.join(["printf", "%s", "literal; $TOKEN"]),
                "timeoutSeconds": 600,
                "detached": False,
                "cwd": "/home/user/control-fixture",
            },
        )
        prompt_request = self.fake.requests_for("POST", f"/boxes/{BOX_ID}/prompt")[0]
        self.assertEqual(
            prompt_request.body,
            {
                "provider": "codex",
                "prompt": "Run $codexstack:work with `literal` data",
                "model": "gpt-5.6-sol",
                "reasoningEffort": "high",
            },
        )
        events = self.fake.requests_for("GET", f"/boxes/{BOX_ID}/events")[0]
        self.assertEqual(events.query["limit"], ["200"])
        self.assertEqual(events.query["sort"], ["asc"])
        self.assertEqual(events.query["cursor"], ["cursor / opaque"])
        desktop_request = self.fake.requests_for("POST", f"/boxes/{BOX_ID}/desktop")[0]
        self.assertEqual(desktop_request.query, {"theme": ["dark"]})
        host_request = self.fake.requests_for("POST", f"/boxes/{BOX_ID}/host")[-1]
        self.assertEqual(
            host_request.body,
            {
                "port": 4173,
                "public": False,
                "title": "Fixture preview",
            },
        )

    def test_detached_command_status_and_timeout_shape_are_explicit(self) -> None:
        launched = self.client.command(
            BOX_ID,
            ["python3", "-m", "fixture.preview"],
            cwd="/home/user/control-fixture",
            timeout_seconds=600,
            detached=True,
        )
        status = self.client.command_status(BOX_ID, launched["processId"])
        self.assertEqual(launched["processId"], 91)
        self.assertTrue(status["running"])
        self.assertEqual(
            self.fake.requests[-1].path,
            f"/boxes/{BOX_ID}/commands/91",
        )

    def test_http_errors_are_structured_and_requests_are_never_retried(self) -> None:
        self.fake.fail_next("GET", "/limits", 429, "rate_limited")
        with self.assertRaises(box_client.BoxError) as raised:
            self.client.limits()
        error = raised.exception
        self.assertEqual(error.status, 429)
        self.assertEqual(error.code, "rate_limited")
        self.assertEqual(error.request_id, "request-fixture")
        self.assertTrue(error.retryable)
        self.assertEqual(len(self.fake.requests_for("GET", "/limits")), 1)

        path = f"/boxes/{BOX_ID}/commands"
        self.fake.fail_next("POST", path, 503, "box_starting")
        with self.assertRaises(box_client.BoxError) as command_error:
            self.client.command(
                BOX_ID,
                ["true"],
                cwd="/home/user/control-fixture",
                timeout_seconds=600,
                detached=False,
            )
        self.assertFalse(command_error.exception.retryable)
        self.assertEqual(len(self.fake.requests_for("POST", path)), 1)
        self.assertNotIn(self.fake.api_key, str(command_error.exception))

    def test_synchronous_command_requires_the_documented_exit_code_field(self) -> None:
        self.fake.command_results[("missing-exit-code",)] = {
            "ok": True,
            "type": "command.finished",
            "success": True,
            "stdout": "",
            "stderr": "",
            "timedOut": False,
        }
        with self.assertRaises(box_client.BoxError) as invalid:
            self.client.command(
                BOX_ID,
                ["missing-exit-code"],
                cwd="/home/user/control-fixture",
                timeout_seconds=600,
                detached=False,
            )
        self.assertEqual(invalid.exception.code, "invalid_json_response")

    def test_invalid_inputs_fail_before_network(self) -> None:
        cases = (
            lambda: self.client.get_box("self"),
            lambda: self.client.read_file(BOX_ID, "../../private"),
            lambda: self.client.command(BOX_ID, [""], "/home/user/repo", 600, False),
            lambda: self.client.command(BOX_ID, ["true"], "/root", 600, False),
            lambda: self.client.command(BOX_ID, ["true"], "/home/user/repo", 0, False),
            lambda: self.client.prompt(BOX_ID, "", None, None),
            lambda: self.client.events(BOX_ID, cursor="", limit=200),
            lambda: self.client.events(BOX_ID, cursor=None, limit=201),
            lambda: self.client.desktop(BOX_ID, theme="system"),
            lambda: self.client.host(BOX_ID, port=0, title=None),
            lambda: self.client.resume(BOX_ID, ttl_seconds=59),
        )
        for operation in cases:
            before = len(self.fake.requests)
            with self.subTest(operation=operation):
                with self.assertRaises(model.ContractError):
                    operation()
                self.assertEqual(len(self.fake.requests), before)

    def test_client_rejects_keys_and_base_urls_that_can_smuggle_headers_or_credentials(self) -> None:
        with self.assertRaises(model.ContractError):
            box_client.BoxClient("line\nbreak", base_url=self.fake.url)
        with self.assertRaises(model.ContractError):
            box_client.BoxClient("key", base_url="https://user:pass@example.invalid/v1")
        with self.assertRaises(model.ContractError):
            box_client.BoxClient("key", base_url="file:///tmp/socket")
        with self.assertRaises(model.ContractError):
            box_client.BoxClient("key", base_url="http://example.invalid/v1")
        with self.assertRaises(model.ContractError):
            box_client.BoxClient("key", base_url="http://[::1")

    def test_redirects_are_rejected_without_forwarding_authority_headers(self) -> None:
        source_headers: list[dict[str, str]] = []
        target_headers: list[dict[str, str]] = []

        class TargetHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                target_headers.append({key.lower(): value for key, value in self.headers.items()})
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                return

        target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
        target_thread = threading.Thread(target=target.serve_forever, daemon=True)
        target_thread.start()
        target_url = f"http://127.0.0.1:{target.server_address[1]}/capture"

        class SourceHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                if length:
                    self.rfile.read(length)
                source_headers.append({key.lower(): value for key, value in self.headers.items()})
                self.send_response(307)
                self.send_header("Location", target_url)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                return

        source = ThreadingHTTPServer(("127.0.0.1", 0), SourceHandler)
        source_thread = threading.Thread(target=source.serve_forever, daemon=True)
        source_thread.start()
        try:
            client = box_client.BoxClient(
                "redirect-fixture-key",
                base_url=f"http://127.0.0.1:{source.server_address[1]}",
                timeout=2,
            )
            with self.assertRaises(box_client.BoxError) as raised:
                client.create_box(
                    "codexstack-base",
                    "codexstack",
                    7200,
                    "redirect-start-0001",
                )
            self.assertEqual(raised.exception.status, 307)
            self.assertEqual(len(source_headers), 1)
            self.assertEqual(source_headers[0]["authorization"], "Bearer redirect-fixture-key")
            self.assertEqual(source_headers[0]["idempotency-key"], "redirect-start-0001")
            self.assertEqual(target_headers, [])
        finally:
            source.shutdown()
            source.server_close()
            source_thread.join(timeout=5)
            target.shutdown()
            target.server_close()
            target_thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
