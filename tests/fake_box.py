from __future__ import annotations

import copy
import json
import shlex
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit


BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
BOX_ID = "bx_23456789"
FIRST_PROMPT_ID = "prompt-1"


def default_worker() -> dict[str, Any]:
    return {
        "contractVersion": "codexstack.worker.v1",
        "baseRef": "main",
        "workingDirectory": ".",
        "setup": [["python3", "-m", "fixture.setup"]],
        "verify": [["python3", "-m", "fixture.verify"]],
        "preview": {"command": ["python3", "-m", "fixture.preview"], "port": 4173},
    }


@dataclass(frozen=True)
class RequestRecord:
    method: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    body: Any


@dataclass(frozen=True)
class Failure:
    method: str
    path: str
    status: int
    code: str
    request_id: str = "request-fixture"


class FakeBoxServer:
    """A real local HTTP service with deterministic Box and Git behavior."""

    def __init__(self, *, api_key: str = "fixture-api-key") -> None:
        self.api_key = api_key
        self.requests: list[RequestRecord] = []
        self.failures: list[Failure] = []
        self.worker = default_worker()
        self.repo = "octocat/control-fixture"
        self.origin_repo = self.repo
        self.box_id = BOX_ID
        self.box_state = "ready"
        self.ready_polls_remaining = 0
        self.can_start = True
        self.base_sha = BASE_SHA
        self.head_sha = BASE_SHA
        self.remote_branch_head: str | None = None
        self.current_branch = "main"
        self.dirty = False
        self.ancestor = True
        self.prompt_status_value = "running"
        self.prompt_count = 0
        self.events_value: list[dict[str, Any]] = []
        self.next_cursor: str | None = None
        self.process_running = True
        self.command_failures: dict[tuple[str, ...], int] = {}
        self.command_results: dict[tuple[str, ...], dict[str, Any]] = {}
        self.verify_branch: str | None = None
        self.worker_history_count = 0
        self.replacement_refs: list[str] = []
        self.shallow_repository = False
        self.grafts_present = False
        self.index_entries = ["H .codexstack/worker.json", "H app.txt"]
        self.verify_index_entries: list[str] | None = None
        self.pr: dict[str, Any] | None = None
        self.host_pr: dict[str, Any] | None = None
        self.host_pr_count = 1
        self.host_base_repo = self.repo
        self.host_head_repo = self.repo
        self.desktop_counter = 0
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    @property
    def branch(self) -> str:
        return self.current_branch

    @property
    def prompt_id(self) -> str:
        return f"prompt-{max(1, self.prompt_count)}"

    def start(self) -> "FakeBoxServer":
        self._thread.start()
        return self

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def __enter__(self) -> "FakeBoxServer":
        return self.start()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def fail_next(self, method: str, path: str, status: int, code: str) -> None:
        self.failures.append(Failure(method, path, status, code))

    def requests_for(self, method: str, path: str) -> list[RequestRecord]:
        return [item for item in self.requests if item.method == method and item.path == path]

    def finish_agent(self, *, with_pull_request: bool = True) -> None:
        self.prompt_status_value = "finished"
        self.head_sha = HEAD_SHA
        self.remote_branch_head = HEAD_SHA
        if with_pull_request:
            self.pr = {
                "number": 17,
                "url": f"https://github.com/{self.repo}/pull/17",
                "state": "OPEN",
                "isDraft": False,
                "baseRefName": self.worker["baseRef"],
                "headRefName": self.current_branch,
                "headRefOid": HEAD_SHA,
            }
            self.host_pr = copy.deepcopy(self.pr)

    def github_pull(self, repo: str, number: int) -> dict[str, Any]:
        if self.host_pr is None:
            raise RuntimeError("host GitHub fixture is unavailable")
        return {
            "number": self.host_pr.get("number"),
            "state": str(self.host_pr.get("state", "")).lower(),
            "draft": self.host_pr.get("isDraft"),
            "html_url": self.host_pr.get("url"),
            "base": {
                "ref": self.host_pr.get("baseRefName"),
                "repo": {"full_name": self.host_base_repo},
            },
            "head": {
                "ref": self.host_pr.get("headRefName"),
                "sha": self.host_pr.get("headRefOid"),
                "repo": {"full_name": self.host_head_repo},
            },
        }

    def github_pulls(self, repo: str, branch: str, _base_ref: str) -> list[dict[str, Any]]:
        if self.host_pr is None:
            return []
        if (
            self.host_pr.get("state") != "OPEN"
            or self.host_pr.get("headRefName") != branch
        ):
            return []
        return [
            {"number": self.host_pr.get("number") if index == 0 else 100 + index}
            for index in range(self.host_pr_count)
        ]

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def do_GET(self) -> None:
                self._dispatch()

            def do_POST(self) -> None:
                self._dispatch()

            def log_message(self, format: str, *args: object) -> None:
                return

            def _dispatch(self) -> None:
                parsed = urlsplit(self.path)
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw) if raw else None
                except json.JSONDecodeError:
                    body = "[invalid-json]"
                record = RequestRecord(
                    self.command,
                    parsed.path,
                    parse_qs(parsed.query, keep_blank_values=True),
                    {key.lower(): value for key, value in self.headers.items()},
                    body,
                )
                fixture.requests.append(record)
                if self.headers.get("Authorization") != f"Bearer {fixture.api_key}":
                    self._error(401, "unauthorized")
                    return
                for index, failure in enumerate(fixture.failures):
                    if failure.method == self.command and failure.path == parsed.path:
                        fixture.failures.pop(index)
                        self._error(failure.status, failure.code, failure.request_id)
                        return
                try:
                    payload, status = fixture._route(record)
                except AssertionError as exc:
                    self._error(422, "fixture_assertion", str(exc))
                    return
                if payload is None:
                    self._error(404, "not_found")
                    return
                self._json(status, payload)

            def _json(self, status: int, payload: dict[str, Any]) -> None:
                raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _error(self, status: int, code: str, request_id: str = "request-fixture") -> None:
                self._json(
                    status,
                    {
                        "ok": False,
                        "type": "error",
                        "code": code,
                        "requestId": request_id,
                        "error": {"code": code},
                    },
                )

        return Handler

    @staticmethod
    def _ok(kind: str, **fields: Any) -> dict[str, Any]:
        return {"ok": True, "type": kind, **fields}

    def _box_value(self, state: str | None = None) -> dict[str, Any]:
        return {"id": self.box_id, "state": state or self.box_state}

    def _route(self, request: RequestRecord) -> tuple[dict[str, Any] | None, int]:
        method, path, body = request.method, request.path, request.body
        base = f"/boxes/{self.box_id}"
        if (method, path) == ("GET", "/limits"):
            return self._ok(
                "limits.info",
                canStart=self.can_start,
                activeBoxes=0,
                maxActiveBoxes=100,
                billingStatus="active",
            ), 200
        if (method, path) == ("POST", "/boxes"):
            assert request.headers.get("idempotency-key")
            assert body == {
                "from": "codexstack-base",
                "environment": "codexstack",
                "ttlSeconds": 7200,
            }
            self.box_state = "provisioning"
            self.ready_polls_remaining = 1
            return self._ok(
                "box.created",
                status="provisioning",
                ttlSeconds=body["ttlSeconds"],
                box=self._box_value("provisioning"),
            ), 202
        if (method, path) == ("GET", base):
            state = self.box_state
            if state == "provisioning":
                if self.ready_polls_remaining > 0:
                    self.ready_polls_remaining -= 1
                else:
                    self.box_state = "ready"
                    state = "ready"
            return self._ok("box.info", box=self._box_value(state)), 200
        if (method, path) == ("GET", f"{base}/files"):
            expected = f"{self.repo.rsplit('/', 1)[1]}/.codexstack/worker.json"
            assert request.query == {"path": [expected]}
            content = json.dumps(self.worker)
            return self._ok(
                "file.read",
                success=True,
                path=expected,
                encoding="utf8",
                size=len(content.encode("utf-8")),
                content=content,
            ), 200
        if (method, path) == ("POST", f"{base}/commands"):
            return self._command_response(body), 200
        if method == "GET" and path.startswith(f"{base}/commands/"):
            return self._ok(
                "command.status",
                success=True,
                processId=int(path.rsplit("/", 1)[1]),
                status="running" if self.process_running else "exited",
                running=self.process_running,
                exitCode=None if self.process_running else 0,
                stdout="",
                stderr="",
            ), 200
        if (method, path) == ("POST", f"{base}/prompt"):
            self.prompt_count += 1
            self.prompt_status_value = "queued"
            return self._ok(
                "prompt.queued",
                id=self.box_id,
                promptId=self.prompt_id,
                promptRun={
                    "id": self.prompt_id,
                    "promptId": self.prompt_id,
                    "boxId": self.box_id,
                    "status": "queued",
                    "done": False,
                },
                status="queued",
                provider="codex",
            ), 202
        if method == "GET" and path.startswith(f"{base}/prompts/"):
            prompt_id = path.rsplit("/", 1)[1]
            return self._ok(
                "prompt.run",
                id=prompt_id,
                promptRun={
                    "id": prompt_id,
                    "promptId": prompt_id,
                    "boxId": self.box_id,
                    "status": self.prompt_status_value,
                    "done": self.prompt_status_value in {"finished", "failed"},
                },
            ), 200
        if (method, path) == ("GET", f"{base}/events"):
            return self._ok(
                "events.list",
                id=self.box_id,
                events=self.events_value,
                pageInfo={"nextCursor": self.next_cursor, "hasMore": False, "limit": 200},
            ), 200
        if (method, path) == ("POST", f"{base}/interrupt"):
            self.prompt_status_value = "failed"
            return self._ok("interrupt", status="interrupting"), 202
        if (method, path) == ("POST", f"{base}/desktop"):
            self.desktop_counter += 1
            return self._ok(
                "desktop",
                desktopUrl=f"https://desktop.example.invalid/session-{self.desktop_counter}",
            ), 200
        if (method, path) == ("POST", f"{base}/host"):
            assert isinstance(body, dict)
            assert body.get("port") == 4173
            assert body.get("public") is False
            assert isinstance(body.get("title"), str)
            return self._ok(
                "host.url",
                boxId=self.box_id,
                port=4173,
                url=(
                    "https://fixture-4173.on.ascii.dev"
                    "?_token=fixture-preview-token"
                ),
                access="private",
                isProtected=True,
            ), 200
        if (method, path) == ("POST", f"{base}/stop"):
            assert body == {"force": False}
            self.box_state = "archiving"
            return self._ok(
                "box.stopping", status="archiving", box=self._box_value()
            ), 202
        if (method, path) == ("POST", f"{base}/resume"):
            assert isinstance(body.get("ttlSeconds"), int)
            self.box_state = "provisioning"
            self.ready_polls_remaining = 1
            return self._ok(
                "box.resuming", status="provisioning", box=self._box_value()
            ), 202
        return None, 404

    def _command_response(self, body: Any) -> dict[str, Any]:
        assert isinstance(body, dict)
        assert isinstance(body.get("timeoutSeconds"), int)
        assert 1 <= body["timeoutSeconds"] <= 600
        assert isinstance(body.get("detached"), bool)
        if "cwd" in body:
            assert isinstance(body.get("cwd"), str)
        raw_argv = tuple(shlex.split(body.get("command", "")))
        if raw_argv and raw_argv[0] == "git":
            assert raw_argv[1:2] == ("--no-replace-objects",)
            argv = ("git", *raw_argv[2:])
        else:
            argv = raw_argv
        if argv in self.command_results:
            return dict(self.command_results[argv])
        if argv in self.command_failures:
            return self._command_result(self.command_failures[argv], stderr="fixture failure")
        if body["detached"]:
            return self._ok("command.started", processId=91, status="running")
        if argv == ("git", "remote", "get-url", "origin"):
            return self._command_result(0, stdout=f"git@github.com:{self.origin_repo}.git\n")
        if argv[:4] == ("git", "fetch", "--no-tags", "origin"):
            return self._command_result(0)
        if argv[:2] == ("git", "rev-parse") and argv[-1].startswith("origin/"):
            return self._command_result(0, stdout=f"{self.base_sha}\n")
        if argv[:2] == ("git", "show") and argv[-1].endswith(":.codexstack/worker.json"):
            return self._command_result(0, stdout=json.dumps(self.worker))
        if argv[:4] == ("git", "ls-remote", "--heads", "origin"):
            if self.remote_branch_head is None:
                return self._command_result(0)
            return self._command_result(
                0,
                stdout=f"{self.remote_branch_head}\t{argv[-1]}\n",
            )
        if argv[:3] == ("git", "show-ref", "--verify"):
            return self._command_result(1)
        if argv[:3] == ("git", "switch", "--create"):
            self.current_branch = argv[3]
            self.head_sha = argv[4]
            return self._command_result(0)
        if argv == ("git", "status", "--porcelain"):
            return self._command_result(0, stdout=" M changed.txt\n" if self.dirty else "")
        if argv == ("git", "ls-files", "-v", "-z"):
            output = "".join(f"{entry}\0" for entry in self.index_entries)
            return self._command_result(0, stdout=output)
        if argv == ("git", "branch", "--show-current"):
            return self._command_result(0, stdout=f"{self.current_branch}\n")
        if argv == ("git", "rev-parse", "HEAD"):
            return self._command_result(0, stdout=f"{self.head_sha}\n")
        if argv[:3] == ("git", "diff", "--quiet"):
            return self._command_result(0)
        if argv[:3] == ("git", "rev-list", "--count"):
            return self._command_result(0, stdout=f"{self.worker_history_count}\n")
        if argv == ("git", "for-each-ref", "--format=%(refname)", "refs/replace"):
            output = "".join(f"{ref}\n" for ref in self.replacement_refs)
            return self._command_result(0, stdout=output)
        if argv == ("git", "rev-parse", "--is-shallow-repository"):
            return self._command_result(
                0, stdout="true\n" if self.shallow_repository else "false\n"
            )
        if argv == ("git", "rev-parse", "--git-path", "info/grafts"):
            return self._command_result(0, stdout=".git/info/grafts\n")
        if argv == ("codex", "debug", "prompt-input", "probe"):
            return self._command_result(
                0,
                stdout="skill codexstack:work Contract codexstack.work.v0.3.0\n",
            )
        if argv[:3] == ("git", "merge-base", "--is-ancestor"):
            return self._command_result(0 if self.ancestor else 1)
        if argv == ("python3", "-m", "fixture.verify") and self.verify_branch:
            self.current_branch = self.verify_branch
        if argv == ("python3", "-m", "fixture.verify") and self.verify_index_entries is not None:
            self.index_entries = list(self.verify_index_entries)
        if argv in {
            ("python3", "-m", "fixture.setup"),
            ("python3", "-m", "fixture.verify"),
            ("codex", "login", "status"),
            ("gh", "auth", "status"),
            ("printf", "%s", "literal; $TOKEN"),
        }:
            return self._command_result(0)
        if argv == ("test", "!", "-e", ".git/info/grafts"):
            return self._command_result(1 if self.grafts_present else 0)
        raise AssertionError(f"unexpected fixture command: {argv!r}")

    @staticmethod
    def _command_result(exit_code: int, *, stdout: str = "", stderr: str = "") -> dict[str, Any]:
        return FakeBoxServer._ok(
            "command.finished",
            exitCode=exit_code,
            success=exit_code == 0,
            stdout=stdout,
            stderr=stderr,
            timedOut=False,
            finishedAt="2026-08-28T12:00:00Z",
        )
