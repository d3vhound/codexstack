from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "plugins" / "codexstack" / "runtime"
sys.path.insert(0, str(RUNTIME))

from codexstack_control import controller, mcp, store  # noqa: E402
from tests.fake_box import BOX_ID, FakeBoxServer  # noqa: E402


def initialize_request(request_id: int = 1) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "control-test", "version": "1.0"},
        },
    }


class MCPContractTests(unittest.TestCase):
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
            port=8765,
            token="control-token",
            box_api_base=self.fake.url,
            inside_worker=False,
        )
        control = controller.RunController(
            config,
            store=store.RunStore(database),
            sleeper=lambda _: None,
            github_lookup=self.fake.github_pull,
            github_list=self.fake.github_pulls,
        )
        self.server = mcp.MCPServer(control)
        self.request_id = 10

    def rpc(self, method: str, params: object) -> dict[str, object]:
        self.request_id += 1
        response = self.server.handle(
            {
                "jsonrpc": "2.0",
                "id": self.request_id,
                "method": method,
                "params": params,
            }
        )
        self.assertIsInstance(response, dict)
        return response  # type: ignore[return-value]

    def call(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        response = self.rpc("tools/call", {"name": name, "arguments": arguments})
        self.assertNotIn("error", response)
        return response["result"]  # type: ignore[return-value]

    def test_initialize_and_tool_list_are_exact_and_safety_annotated(self) -> None:
        initialized = self.server.handle(initialize_request())
        result = initialized["result"]
        self.assertEqual(result["protocolVersion"], mcp.PROTOCOL_VERSION)
        self.assertEqual(result["serverInfo"]["name"], "codexstack-control")
        self.assertIn("never merges or deletes", result["instructions"])
        notification = self.server.handle(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        )
        self.assertIsNone(notification)
        self.assertTrue(self.server.initialized)

        listed = self.rpc("tools/list", {})["result"]["tools"]
        names = [tool["name"] for tool in listed]
        self.assertEqual(
            names,
            [
                "run_start",
                "run_list",
                "run_read",
                "run_wait",
                "run_message",
                "run_interrupt",
                "run_desktop",
                "run_stop",
                "run_resume",
                "run_handoff",
            ],
        )
        self.assertEqual(len(names), 10)
        self.assertEqual(len(set(names)), 10)
        by_name = {tool["name"]: tool for tool in listed}
        self.assertTrue(by_name["run_list"]["annotations"]["readOnlyHint"])
        self.assertTrue(by_name["run_interrupt"]["annotations"]["destructiveHint"])
        self.assertTrue(by_name["run_stop"]["annotations"]["destructiveHint"])
        self.assertFalse(by_name["run_handoff"]["annotations"]["destructiveHint"])
        self.assertTrue(by_name["run_handoff"]["annotations"]["idempotentHint"])
        self.assertTrue(by_name["run_list"]["annotations"]["openWorldHint"])
        self.assertIn("delivery", by_name["run_start"]["inputSchema"]["required"])
        for tool in listed:
            self.assertFalse(tool["inputSchema"]["additionalProperties"])

    def test_all_ten_tools_share_the_real_controller_without_exposing_signed_urls(self) -> None:
        self.server.handle(initialize_request())
        started = self.call(
            "run_start",
            {
                "repo": "octocat/control-fixture",
                "goal": "Fix the MCP fixture and prove it.",
                "baseRef": "main",
                "model": "gpt-5.6-sol",
                "reasoningEffort": "high",
                "ttlSeconds": 7200,
                "idempotencyKey": "mcp-start-0001",
                "delivery": "open_pull_request",
            },
        )
        run_id = started["structuredContent"]["id"]
        prompt_id = started["structuredContent"]["promptId"]
        listed = self.call("run_list", {"limit": 10, "offset": 0})
        self.assertEqual(listed["structuredContent"]["runs"][0]["id"], run_id)
        read = self.call("run_read", {"runId": run_id, "refresh": False})
        self.assertEqual(read["structuredContent"]["id"], run_id)

        self.fake.events_value = [
            {"id": "event-1", "type": "response", "data": {"text": "working"}}
        ]
        self.fake.next_cursor = "cursor-2"
        waited = self.call(
            "run_wait",
            {"runId": run_id, "cursor": "cursor-1", "waitSeconds": 0},
        )
        self.assertEqual(waited["structuredContent"]["nextCursor"], "cursor-2")

        messaged = self.call(
            "run_message",
            {
                "runId": run_id,
                "message": "Add one focused proof.",
                "expectedPromptId": prompt_id,
                "idempotencyKey": "mcp-message-0001",
            },
        )
        current_prompt = messaged["structuredContent"]["promptId"]
        desktop = self.call("run_desktop", {"runId": run_id})
        self.assertEqual(
            desktop["structuredContent"]["url"],
            f"http://127.0.0.1:8765/runs/{run_id}?open=desktop",
        )
        self.assertEqual(
            self.fake.requests_for("POST", f"/boxes/{BOX_ID}/desktop"),
            [],
        )
        interrupted = self.call(
            "run_interrupt",
            {"runId": run_id, "expectedPromptId": current_prompt},
        )
        self.assertEqual(interrupted["structuredContent"]["status"], "needs_input")
        stopped = self.call("run_stop", {"runId": run_id})
        self.assertEqual(stopped["structuredContent"]["status"], "stopped")
        resumed = self.call("run_resume", {"runId": run_id, "ttlSeconds": 3600})
        self.assertEqual(resumed["structuredContent"]["status"], "needs_input")

        remessaged = self.call(
            "run_message",
            {
                "runId": run_id,
                "message": "Recheck the interrupted proof and deliver it.",
                "expectedPromptId": resumed["structuredContent"]["promptId"],
                "idempotencyKey": "mcp-message-0002",
            },
        )
        self.assertEqual(remessaged["structuredContent"]["status"], "working")

        self.fake.finish_agent()
        handed = self.call("run_handoff", {"runId": run_id})
        self.assertEqual(handed["structuredContent"]["status"], "review")
        self.assertEqual(handed["structuredContent"]["prNumber"], 17)

        transcript = json.dumps(
            [
                started,
                listed,
                read,
                waited,
                messaged,
                desktop,
                interrupted,
                stopped,
                resumed,
                remessaged,
                handed,
            ],
            sort_keys=True,
        )
        self.assertNotIn("desktop.example.invalid", transcript)
        self.assertNotIn("fixture-preview-token", transcript)
        self.assertNotIn(self.fake.api_key, transcript)

    def test_bad_calls_are_bounded_tool_errors_and_unknown_methods_are_rpc_errors(self) -> None:
        self.server.handle(initialize_request())
        invalid = self.call("run_stop", {"runId": "not-a-run", "extra": True})
        self.assertTrue(invalid["isError"])
        self.assertEqual(
            invalid["structuredContent"]["error"]["code"],
            "invalid_arguments",
        )
        unknown_tool = self.rpc("tools/call", {"name": "run_merge", "arguments": {}})
        self.assertEqual(unknown_tool["error"]["code"], -32602)
        unknown_method = self.rpc("runs/delete", {})
        self.assertEqual(unknown_method["error"]["code"], -32601)
        malformed = self.server.handle({"jsonrpc": "1.0", "id": 1, "method": "ping"})
        self.assertEqual(malformed["error"]["code"], -32600)

    def test_tool_output_redacts_secrets_and_signed_urls_but_keeps_safe_links(self) -> None:
        control_url = f"{self.server.controller.config.public_url}/runs/run_{'a' * 20}"
        github_url = "https://github.com/octocat/control-fixture/pull/17"
        safe = mcp._safe_output(
            {
                "GH_TOKEN": "ghp_" + "a" * 32,
                "note": (
                    "Authorization: Bearer super-secret-bearer-value "
                    "https://preview.example.test/?token=secret"
                ),
                "pullRequest": github_url,
                "controlPage": control_url,
            },
            self.server.controller.config.public_url,
        )
        rendered = json.dumps(safe, sort_keys=True)
        self.assertNotIn("super-secret-bearer-value", rendered)
        self.assertNotIn("ghp_", rendered)
        self.assertNotIn("preview.example.test", rendered)
        self.assertIn(github_url, rendered)
        self.assertIn(control_url, rendered)

    def test_request_only_methods_never_execute_as_notifications(self) -> None:
        before = len(self.fake.requests)
        silent = self.server.handle(
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "run_list", "arguments": {}},
            }
        )
        self.assertIsNone(silent)
        self.assertEqual(len(self.fake.requests), before)
        self.assertFalse(self.server.initialized)

        self.server.handle(initialize_request())
        invalid_notification = self.server.handle(
            {
                "jsonrpc": "2.0",
                "id": 99,
                "method": "notifications/initialized",
                "params": {},
            }
        )
        self.assertEqual(invalid_notification["error"]["code"], -32600)

    def test_stdio_rejects_a_preinitialize_tool_before_parallel_dispatch(self) -> None:
        source = io.StringIO(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "run_list", "arguments": {}},
                }
            )
            + "\n"
            + json.dumps(initialize_request(2))
            + "\n"
        )
        output = io.StringIO()
        mcp.serve_stdio(self.server.controller, source, output)
        responses = {
            item["id"]: item for item in map(json.loads, output.getvalue().splitlines())
        }
        self.assertEqual(responses[1]["error"]["code"], -32002)
        self.assertEqual(responses[2]["result"]["protocolVersion"], mcp.PROTOCOL_VERSION)

    def test_stdio_escapes_lone_surrogate_request_ids(self) -> None:
        source = io.StringIO(
            json.dumps(initialize_request(1))
            + "\n"
            + '{"jsonrpc":"2.0","id":"\\ud800","method":"ping","params":{}}\n'
        )
        output = io.StringIO()
        mcp.serve_stdio(self.server.controller, source, output)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(responses[1]["id"], "\ud800")

    def test_stdio_is_line_delimited_and_rejects_duplicate_json_keys(self) -> None:
        source = io.StringIO(
            json.dumps(initialize_request(1))
            + "\n"
            + '{"jsonrpc":"2.0","id":2,"id":3,"method":"ping","params":{}}\n'
            + json.dumps(
                {"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}}
            )
            + "\n"
        )
        output = io.StringIO()
        mcp.serve_stdio(self.server.controller, source, output)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(responses[0]["id"], 1)
        self.assertEqual(responses[1]["error"]["code"], -32700)
        self.assertEqual(responses[2]["id"], 4)
        self.assertEqual(len(responses[2]["result"]["tools"]), 10)


if __name__ == "__main__":
    unittest.main()
