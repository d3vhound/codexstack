from __future__ import annotations

import http.client
import json
import socket
import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "plugins" / "codexstack" / "runtime"
sys.path.insert(0, str(RUNTIME))

from codexstack_control import controller, http_server, store  # noqa: E402
from tests.fake_box import FakeBoxServer  # noqa: E402


class ControlHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fake = FakeBoxServer().start()
        self.addCleanup(self.fake.close)
        database = Path(self.temporary.name) / "control.sqlite3"
        config = controller.ControlConfig(
            box_api_key=self.fake.api_key,
            box_environment="codexstack",
            box_template="codexstack-base",
            allowed_repos=frozenset({"octocat/control-fixture"}),
            database=database,
            max_parallel=4,
            default_ttl=43200,
            max_ttl=2592000,
            host="127.0.0.1",
            port=0,
            token="control-token",
            box_api_base=self.fake.url,
            inside_worker=False,
        )
        control = controller.RunController(
            config,
            store=store.RunStore(database),
            sleeper=lambda _: None,
        )
        self.server = http_server.create_server(control)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._close_control_server)
        self.port = self.server.server_address[1]
        status, _, config_body = self.request(
            "GET",
            "/api/config",
            headers={"Authorization": "Bearer control-token"},
        )
        self.assertEqual(status, 200)
        self.csrf = config_body["csrfToken"]

    def _close_control_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], Any]:
        request_headers = {} if headers is None else dict(headers)
        encoded: bytes | None = None
        if body is not None:
            encoded = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path, body=encoded, headers=request_headers)
            response = connection.getresponse()
            raw = response.read()
            response_headers = {name.lower(): value for name, value in response.getheaders()}
            content_type = response_headers.get("content-type", "")
            value = json.loads(raw) if raw and content_type.startswith("application/json") else raw
            return response.status, response_headers, value
        finally:
            connection.close()

    def api_headers(self, *, csrf: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": "Bearer control-token",
            "Origin": f"http://127.0.0.1:{self.port}",
        }
        if csrf:
            headers["X-CodexStack-CSRF"] = self.csrf
        return headers

    def start_via_http(self) -> dict[str, Any]:
        status, _, body = self.request(
            "POST",
            "/api/runs",
            headers=self.api_headers(csrf=True),
            body={
                "repo": "octocat/control-fixture",
                "goal": "Fix the HTTP fixture and prove it.",
                "baseRef": "main",
                "model": "gpt-5.6-sol",
                "reasoningEffort": "high",
                "ttlSeconds": 7200,
                "idempotencyKey": "http-start-0001",
                "delivery": "open_pull_request",
            },
        )
        self.assertEqual(status, 200)
        return body["run"]

    def test_static_ui_is_public_but_api_requires_bearer_auth(self) -> None:
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"CodexStack Control", body)
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual(headers["x-frame-options"], "DENY")
        self.assertIn("frame-ancestors 'none'", headers["content-security-policy"])
        self.assertNotIn("access-control-allow-origin", headers)

        status, headers, body = self.request("GET", "/api/runs")
        self.assertEqual(status, 401)
        self.assertEqual(headers["www-authenticate"], "Bearer")
        self.assertEqual(body["error"]["code"], "unauthorized")
        status, _, _ = self.request(
            "GET",
            "/api/runs",
            headers={"Authorization": "Bearer wrong-token"},
        )
        self.assertEqual(status, 401)

    def test_origin_csrf_content_type_and_duplicate_json_fail_closed(self) -> None:
        start = {"repo": "octocat/control-fixture"}
        status, _, body = self.request(
            "POST",
            "/api/runs",
            headers=self.api_headers(csrf=False),
            body=start,
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "csrf_forbidden")

        hostile = self.api_headers(csrf=True)
        hostile["Origin"] = "https://hostile.example.invalid"
        status, _, body = self.request("POST", "/api/runs", headers=hostile, body=start)
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "origin_forbidden")

        headers = self.api_headers(csrf=True)
        headers["Content-Type"] = "text/plain"
        status, _, body = self.request("POST", "/api/runs", headers=headers, body=b"{}")
        self.assertEqual(status, 415)
        self.assertEqual(body["error"]["code"], "invalid_content_type")

        duplicate = b'{"repo":"octocat/control-fixture","repo":"other/repo"}'
        status, _, body = self.request(
            "POST",
            "/api/runs",
            headers=self.api_headers(csrf=True),
            body=duplicate,
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "invalid_json")

    def test_bodyless_methods_close_on_content_length_desync_attempts(self) -> None:
        smuggled = (
            f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        request = (
            f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n"
            f"Content-Length: {len(smuggled)}\r\n\r\n"
        ).encode("ascii") + smuggled
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as connection:
            connection.sendall(request)
            connection.shutdown(socket.SHUT_WR)
            chunks: list[bytes] = []
            while True:
                chunk = connection.recv(65_536)
                if not chunk:
                    break
                chunks.append(chunk)
        response = b"".join(chunks)
        self.assertEqual(response.count(b"HTTP/1.1"), 1)
        self.assertTrue(response.startswith(b"HTTP/1.1 400"))
        self.assertIn(b"Connection: close", response)
        self.assertEqual(self.fake.requests, [])

    def test_http_ui_story_lists_events_and_requests_protected_links_only_on_click(self) -> None:
        run = self.start_via_http()
        run_id = run["id"]
        status, headers, listed = self.request(
            "GET",
            "/api/runs?limit=10&offset=0",
            headers=self.api_headers(),
        )
        self.assertEqual(status, 200)
        self.assertEqual(listed["runs"][0]["id"], run_id)
        self.assertEqual(headers["cache-control"], "no-store")
        self.fake.events_value = [
            {"id": "event-1", "type": "response", "data": {"text": "working"}}
        ]
        self.fake.next_cursor = "cursor-2"
        status, _, events = self.request(
            "GET",
            f"/api/runs/{run_id}/events?cursor=cursor-1&waitSeconds=0",
            headers=self.api_headers(),
        )
        self.assertEqual(status, 200)
        self.assertEqual(events["events"][0]["id"], "event-1")
        self.assertEqual(events["nextCursor"], "cursor-2")

        self.assertEqual(self.fake.desktop_counter, 0)
        status, desktop_headers, desktop_one = self.request(
            "POST",
            f"/api/runs/{run_id}/desktop",
            headers=self.api_headers(csrf=True),
            body={"theme": "dark"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(desktop_headers["cache-control"], "no-store")
        _, _, desktop_two = self.request(
            "POST",
            f"/api/runs/{run_id}/desktop",
            headers=self.api_headers(csrf=True),
            body={"theme": "dark"},
        )
        self.assertNotEqual(desktop_one["url"], desktop_two["url"])
        self.assertEqual(self.fake.desktop_counter, 2)

        status, preview_headers, preview = self.request(
            "POST",
            f"/api/runs/{run_id}/preview",
            headers=self.api_headers(csrf=True),
            body={},
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            preview["url"],
            "https://fixture-4173.on.ascii.dev?_token=fixture-preview-token",
        )
        self.assertEqual(preview_headers["cache-control"], "no-store")
        status, _, page = self.request("GET", f"/runs/{run_id}?open=desktop")
        self.assertEqual(status, 200)
        self.assertIn(b"Open live sandbox", page)

    def test_http_mcp_initializes_and_never_returns_raw_desktop_url(self) -> None:
        run = self.start_via_http()
        status, _, initialized = self.request(
            "POST",
            "/mcp",
            headers={
                "Authorization": "Bearer control-token",
                "Origin": f"http://127.0.0.1:{self.port}",
            },
            body={
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "http-test", "version": "1.0"},
                },
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(initialized["result"]["protocolVersion"], "2025-06-18")
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "run_desktop", "arguments": {"runId": run["id"]}},
        }
        status, headers, body = self.request(
            "POST",
            "/mcp",
            headers={
                "Authorization": "Bearer control-token",
                "Origin": f"http://127.0.0.1:{self.port}",
            },
            body=request,
        )
        self.assertEqual(status, 200)
        rendered = json.dumps(body)
        self.assertIn(f"/runs/{run['id']}?open=desktop", rendered)
        self.assertNotIn("desktop.example.invalid", rendered)
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual(self.fake.desktop_counter, 0)

    def test_http_mcp_rejects_an_unsupported_protocol_version_header(self) -> None:
        status, _, body = self.request(
            "POST",
            "/mcp",
            headers={
                "Authorization": "Bearer control-token",
                "MCP-Protocol-Version": "1900-01-01",
            },
            body={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "unsupported_protocol_version")

    def test_https_public_origin_is_an_allowlisted_proxy_identity_not_a_listener_bind(self) -> None:
        database = Path(self.temporary.name) / "public.sqlite3"
        base_config = self.server.RequestHandlerClass.controller.config
        config = replace(
            base_config,
            database=database,
            port=0,
            public_origin="https://control.example.com",
        )
        control = controller.RunController(
            config,
            store=store.RunStore(database),
            sleeper=lambda _: None,
            github_lookup=self.fake.github_pull,
            github_list=self.fake.github_pulls,
        )
        public_server = http_server.create_server(control)
        thread = threading.Thread(target=public_server.serve_forever, daemon=True)
        thread.start()
        try:
            port = public_server.server_address[1]
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            connection.request(
                "POST",
                "/mcp",
                body=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}),
                headers={
                    "Host": "control.example.com",
                    "Origin": "https://control.example.com",
                    "Authorization": "Bearer control-token",
                    "Content-Type": "application/json",
                    "MCP-Protocol-Version": "2025-06-18",
                },
            )
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 200)
            connection.close()

            hostile = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            hostile.request("GET", "/api/config", headers={"Host": "hostile.example.com"})
            denied = hostile.getresponse()
            denied.read()
            self.assertEqual(denied.status, 400)
            hostile.close()
        finally:
            public_server.shutdown()
            public_server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
