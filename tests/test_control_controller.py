from __future__ import annotations

import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "plugins" / "codexstack" / "runtime"
sys.path.insert(0, str(RUNTIME))

from codexstack_control import controller, model, store  # noqa: E402
from tests.fake_box import BASE_SHA, BOX_ID, HEAD_SHA, FakeBoxServer  # noqa: E402


def start_request(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "repo": "octocat/control-fixture",
        "goal": "Fix the exact authentication regression and prove it.",
        "baseRef": "main",
        "model": "gpt-5.6-sol",
        "reasoningEffort": "high",
        "ttlSeconds": 7200,
        "idempotencyKey": "fixture-start-0001",
        "delivery": "open_pull_request",
    }
    value.update(changes)
    return value


class ControlConfigTests(unittest.TestCase):
    def test_remote_display_url_requires_https_and_token_while_listener_stays_loopback(self) -> None:
        with self.assertRaisesRegex(controller.ControlError, "must bind to loopback"):
            controller.ControlConfig.from_environ(
                {"CODEXSTACK_CONTROL_HOST": "0.0.0.0", "CODEXSTACK_CONTROL_TOKEN": "secret"}
            )
        with self.assertRaisesRegex(controller.ControlError, "requires a token"):
            controller.ControlConfig.from_environ(
                {"CODEXSTACK_PUBLIC_URL": "https://control.example.com"}
            )
        with self.assertRaisesRegex(controller.ControlError, "must use HTTPS"):
            controller.ControlConfig.from_environ(
                {
                    "CODEXSTACK_PUBLIC_URL": "http://control.example.com",
                    "CODEXSTACK_CONTROL_TOKEN": "secret",
                }
            )

        config = controller.ControlConfig.from_environ(
            {
                "CODEXSTACK_PUBLIC_URL": "https://Control.Example.com:443/",
                "CODEXSTACK_CONTROL_TOKEN": "secret",
            }
        )
        self.assertEqual(config.public_url, "https://control.example.com")
        self.assertEqual(config.host, "127.0.0.1")


class GitIndexTrustTests(unittest.TestCase):
    def test_real_git_assume_unchanged_and_skip_worktree_flags_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            subprocess.run(["git", "init", "-q", str(repository)], check=True)
            subprocess.run(
                ["git", "-C", str(repository), "config", "user.email", "fixture@example.invalid"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repository), "config", "user.name", "Fixture"], check=True
            )
            tracked = repository / "app.txt"
            tracked.write_text("committed\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repository), "add", "app.txt"], check=True)
            subprocess.run(
                ["git", "-C", str(repository), "commit", "-q", "-m", "fixture"], check=True
            )

            for enable, disable in (
                ("--assume-unchanged", "--no-assume-unchanged"),
                ("--skip-worktree", "--no-skip-worktree"),
            ):
                with self.subTest(flag=enable):
                    subprocess.run(
                        ["git", "-C", str(repository), "update-index", enable, "app.txt"],
                        check=True,
                    )
                    output = subprocess.check_output(
                        ["git", "-C", str(repository), "ls-files", "-v", "-z"], text=True
                    )
                    with self.assertRaises(controller.ControlError) as untrusted:
                        controller._assert_normal_git_index(output)
                    self.assertEqual(untrusted.exception.code, "git_index_untrusted")
                    subprocess.run(
                        ["git", "-C", str(repository), "update-index", disable, "app.txt"],
                        check=True,
                    )


class ControlGithubTests(unittest.TestCase):
    @mock.patch("codexstack_control.controller.subprocess.run")
    def test_host_github_lookup_uses_bounded_noninteractive_gh_api(self, run: mock.Mock) -> None:
        value = {"number": 17, "state": "open"}
        run.return_value = subprocess.CompletedProcess(
            ["gh"], 0, stdout=json.dumps(value), stderr=""
        )
        self.assertEqual(
            controller.RunController._github_pull_via_cli("octocat/control-fixture", 17),
            value,
        )
        command = run.call_args.args[0]
        self.assertEqual(
            command,
            [
                "gh",
                "api",
                "--hostname",
                "github.com",
                "--method",
                "GET",
                "repos/octocat/control-fixture/pulls/17",
            ],
        )
        self.assertIs(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs["timeout"], 30)

    @mock.patch("codexstack_control.controller.subprocess.run")
    def test_host_github_list_pins_github_and_exact_head_base(self, run: mock.Mock) -> None:
        value = [{"number": 17}]
        run.return_value = subprocess.CompletedProcess(
            ["gh"], 0, stdout=json.dumps(value), stderr=""
        )
        self.assertEqual(
            controller.RunController._github_pulls_via_cli(
                "octocat/control-fixture", "codexstack/run-1", "main"
            ),
            value,
        )
        command = run.call_args.args[0]
        self.assertEqual(command[:6], ["gh", "api", "--hostname", "github.com", "--method", "GET"])
        self.assertIn("state=open", command[6])
        self.assertIn("head=octocat%3Acodexstack%2Frun-1", command[6])
        self.assertNotIn("base=", command[6])

    @mock.patch("codexstack_control.controller.subprocess.run")
    def test_host_github_lookup_fails_closed_for_transport_and_invalid_output(
        self, run: mock.Mock
    ) -> None:
        cases = (
            (subprocess.CompletedProcess(["gh"], 1, stdout="", stderr="denied"), "github_unavailable"),
            (subprocess.CompletedProcess(["gh"], 0, stdout="{", stderr=""), "pr_invalid"),
            (subprocess.CompletedProcess(["gh"], 0, stdout="[]", stderr=""), "pr_invalid"),
            (
                subprocess.CompletedProcess(["gh"], 0, stdout="x" * 1_048_577, stderr=""),
                "github_unavailable",
            ),
        )
        for completed, code in cases:
            with self.subTest(code=code, length=len(completed.stdout)):
                run.return_value = completed
                with self.assertRaises(controller.ControlError) as raised:
                    controller.RunController._github_pull_via_cli(
                        "octocat/control-fixture", 17
                    )
                self.assertEqual(raised.exception.code, code)

        run.side_effect = subprocess.TimeoutExpired(["gh"], 30)
        with self.assertRaises(controller.ControlError) as timed_out:
            controller.RunController._github_pull_via_cli("octocat/control-fixture", 17)
        self.assertEqual(timed_out.exception.code, "github_unavailable")


class ControllerHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fake = FakeBoxServer().start()
        self.addCleanup(self.fake.close)
        database = Path(self.temporary.name) / "control.sqlite3"
        self.config = controller.ControlConfig(
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
        self.store = store.RunStore(database)
        self.control = controller.RunController(
            self.config,
            store=self.store,
            sleeper=lambda _: None,
            github_lookup=self.fake.github_pull,
            github_list=self.fake.github_pulls,
        )

    def start_run(self, **changes: object) -> dict[str, object]:
        return self.control.start(start_request(**changes))

    def command_argv(self) -> list[tuple[str, ...]]:
        commands: list[tuple[str, ...]] = []
        for item in self.fake.requests_for("POST", f"/boxes/{BOX_ID}/commands"):
            argv = tuple(shlex.split(item.body["command"]))
            if argv[:2] == ("git", "--no-replace-objects"):
                argv = ("git", *argv[2:])
            commands.append(argv)
        return commands


class ControllerStartTests(ControllerHarness):
    def test_full_start_uses_exact_base_branch_setup_and_delivery_prompt(self) -> None:
        run = self.start_run()
        expected_id = model.stable_run_id("fixture-start-0001")
        expected_branch = model.branch_name(expected_id, "control-fixture")

        self.assertEqual(run["id"], expected_id)
        self.assertEqual(run["boxId"], BOX_ID)
        self.assertEqual(run["baseRef"], "main")
        self.assertEqual(run["baseSha"], BASE_SHA)
        self.assertEqual(run["headSha"], BASE_SHA)
        self.assertEqual(run["branch"], expected_branch)
        self.assertEqual(run["promptId"], "prompt-1")
        self.assertEqual(run["promptStatus"], "queued")
        self.assertEqual(run["status"], "working")
        self.assertEqual(run["setupReceipts"], [
            {
                "index": 0,
                "exitCode": 0,
                "success": True,
                "finishedAt": "2026-08-28T12:00:00Z",
            }
        ])

        commands = self.command_argv()
        self.assertEqual(
            commands,
            [
                ("git", "remote", "get-url", "origin"),
                ("git", "fetch", "--no-tags", "origin", "main"),
                ("git", "rev-parse", "origin/main^{commit}"),
                ("git", "show", f"{BASE_SHA}:.codexstack/worker.json"),
                (
                    "git",
                    "ls-remote",
                    "--heads",
                    "origin",
                    f"refs/heads/{expected_branch}",
                ),
                ("git", "show-ref", "--verify", f"refs/heads/{expected_branch}"),
                ("git", "switch", "--create", expected_branch, BASE_SHA),
                ("python3", "-m", "fixture.setup"),
                ("git", "branch", "--show-current"),
                ("git", "rev-parse", "HEAD"),
                ("git", "status", "--porcelain"),
                ("codex", "debug", "prompt-input", "probe"),
                ("codex", "login", "status"),
                ("gh", "auth", "status"),
            ],
        )
        setup_request = self.fake.requests_for("POST", f"/boxes/{BOX_ID}/commands")[7]
        self.assertEqual(setup_request.body["cwd"], "control-fixture")
        prompt = self.fake.requests_for("POST", f"/boxes/{BOX_ID}/prompt")[0].body["prompt"]
        self.assertIn("$codexstack:work", prompt)
        self.assertIn(start_request()["goal"], prompt)
        self.assertIn(f"base: main at {BASE_SHA}", prompt)
        self.assertIn(f"branch: {expected_branch}", prompt)
        self.assertIn('declared verification argv: [["python3","-m","fixture.verify"]]', prompt)
        self.assertIn("open one non-draft pull request", prompt)
        self.assertIn("Never merge, close, retarget, force-push, or deploy", prompt)
        self.assertNotIn(start_request()["goal"], run["title"])
        self.assertNotIn("authentication", run["branch"])

        database_bytes = self.config.database.read_bytes()
        self.assertNotIn(self.fake.api_key.encode(), database_bytes)

    def test_start_is_idempotent_and_reused_key_with_new_request_is_rejected(self) -> None:
        first = self.start_run()
        requests_after_first = len(self.fake.requests)
        second = self.start_run()
        self.assertEqual(first, second)
        self.assertEqual(len(self.fake.requests), requests_after_first)

    def test_lost_box_create_response_retries_only_the_idempotent_create(self) -> None:
        request = model.StartRequest.parse(start_request(), default_ttl=43200)
        run_id = model.stable_run_id(request.idempotency_key)
        self.store.create(
            {
                "id": run_id,
                "requestHash": self.control._request_hash(request),
                "title": "Incomplete start",
                "repo": request.repo,
                "status": "starting",
                "statusDetail": "Creating branch",
                "createdAt": "2020-01-01T00:00:00Z",
                "updatedAt": "2020-01-01T00:00:00Z",
            }
        )

        reconciled = self.start_run()

        self.assertEqual(reconciled["status"], "working")
        self.assertEqual(
            len(self.fake.requests_for("POST", "/boxes")),
            1,
        )
        self.assertEqual(
            len(self.fake.requests_for("POST", f"/boxes/{BOX_ID}/prompt")),
            1,
        )

        with self.assertRaises(controller.ControlError) as raised:
            self.start_run(goal="A different operation")
        self.assertEqual(raised.exception.code, "idempotency_conflict")
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(len(self.fake.requests_for("POST", "/boxes")), 1)

    def test_repo_allowlist_box_capacity_and_local_capacity_fail_before_creation(self) -> None:
        with self.assertRaises(controller.ControlError) as denied:
            self.control.start(start_request(repo="other/repository"))
        self.assertEqual(denied.exception.code, "repo_not_allowed")
        self.assertEqual(self.fake.requests, [])

        self.fake.can_start = False
        with self.assertRaises(controller.ControlError) as provider_capacity:
            self.start_run()
        self.assertEqual(provider_capacity.exception.code, "box_capacity")
        self.assertEqual(self.fake.requests_for("POST", "/boxes"), [])

        self.fake.can_start = True
        self.config = controller.ControlConfig(**{**self.config.__dict__, "max_parallel": 1})
        self.control = controller.RunController(
            self.config,
            store=self.store,
            sleeper=lambda _: None,
            github_lookup=self.fake.github_pull,
            github_list=self.fake.github_pulls,
        )
        self.start_run()
        with self.assertRaises(controller.ControlError) as local_capacity:
            self.start_run(idempotencyKey="fixture-start-0002", goal="Second task")
        self.assertEqual(local_capacity.exception.code, "local_capacity")

    def test_setup_failure_never_queues_codex(self) -> None:
        self.fake.command_failures[("python3", "-m", "fixture.setup")] = 7
        with self.assertRaises(controller.ControlError) as failed:
            self.start_run()
        self.assertEqual(failed.exception.code, "command_failed")
        record = self.store.list()[0]
        self.assertEqual(record["status"], "needs_input")
        self.assertEqual(self.fake.requests_for("POST", f"/boxes/{BOX_ID}/prompt"), [])

    def test_dirty_setup_never_queues_codex(self) -> None:
        self.fake.dirty = True
        with self.assertRaises(controller.ControlError) as dirty:
            self.start_run()
        self.assertEqual(dirty.exception.code, "setup_dirty")
        self.assertEqual(self.store.list()[0]["status"], "needs_input")
        self.assertEqual(self.fake.requests_for("POST", f"/boxes/{BOX_ID}/prompt"), [])

    def test_branch_collision_never_switches_or_prompts(self) -> None:
        self.fake.remote_branch_head = HEAD_SHA
        with self.assertRaises(controller.ControlError) as raised:
            self.start_run()
        self.assertEqual(raised.exception.code, "branch_collision")
        commands = self.command_argv()
        self.assertNotIn(("git", "switch", "--create"), [item[:3] for item in commands])
        self.assertEqual(self.fake.requests_for("POST", f"/boxes/{BOX_ID}/prompt"), [])


class ControllerInteractionTests(ControllerHarness):
    def test_list_refreshes_workers_that_are_not_selected(self) -> None:
        run = self.start_run()
        self.fake.finish_agent()
        self.assertEqual(self.store.get(run["id"])["status"], "working")

        listed = self.control.list()

        self.assertEqual(listed[0]["status"], "needs_input")
        self.assertEqual(listed[0]["promptStatus"], "finished")

    def test_wait_uses_prompt_status_and_sanitizes_cursor_events(self) -> None:
        run = self.start_run()
        self.fake.prompt_status_value = "running"
        self.fake.events_value = [
            {
                "id": "event-1",
                "type": "response",
                "data": {"text": "hello\x1b[31m world\x00", "is_streaming": True},
            }
        ]
        self.fake.next_cursor = "cursor-2"
        waited = self.control.wait(run["id"], cursor="cursor-1", wait_seconds=0)
        self.assertEqual(waited["status"], "working")
        self.assertFalse(waited["terminal"])
        self.assertEqual(waited["nextCursor"], "cursor-2")
        self.assertEqual(waited["events"][0]["data"]["text"], "hello world")
        event_request = self.fake.requests_for("GET", f"/boxes/{BOX_ID}/events")[-1]
        self.assertEqual(event_request.query["cursor"], ["cursor-1"])

        self.fake.events_value = []
        self.fake.prompt_status_value = "finished"
        refreshed = self.control.read(run["id"])
        self.assertEqual(refreshed["promptStatus"], "finished")
        self.assertEqual(refreshed["status"], "needs_input")

    def test_follow_up_requires_current_prompt_and_is_idempotent(self) -> None:
        run = self.start_run()
        with self.assertRaises(controller.ControlError) as stale:
            self.control.message(
                run["id"],
                {
                    "message": "Continue",
                    "expectedPromptId": "prompt-stale",
                    "idempotencyKey": "message-key-0001",
                },
            )
        self.assertEqual(stale.exception.code, "stale_prompt")
        initial_prompt_count = len(self.fake.requests_for("POST", f"/boxes/{BOX_ID}/prompt"))

        value = {
            "message": "Add the focused regression proof.",
            "expectedPromptId": run["promptId"],
            "idempotencyKey": "message-key-0001",
        }
        delivered = self.control.message(run["id"], value)
        self.assertEqual(delivered["promptId"], "prompt-2")
        same = self.control.message(run["id"], value)
        self.assertEqual(same["promptId"], "prompt-2")
        self.assertEqual(
            len(self.fake.requests_for("POST", f"/boxes/{BOX_ID}/prompt")),
            initial_prompt_count + 1,
        )
        follow_up = self.fake.requests_for("POST", f"/boxes/{BOX_ID}/prompt")[-1].body["prompt"]
        self.assertIn("$codexstack:work", follow_up)
        self.assertIn(value["message"], follow_up)
        self.assertIn(f"branch: {run['branch']}", follow_up)
        self.assertIn("Never merge, close, retarget, force-push, or deploy", follow_up)
        with self.assertRaises(controller.ControlError) as conflict:
            self.control.message(
                run["id"],
                {
                    "message": "Different text",
                    "expectedPromptId": "prompt-2",
                    "idempotencyKey": "message-key-0001",
                },
            )
        self.assertEqual(conflict.exception.code, "idempotency_conflict")

    def test_failed_follow_up_is_ambiguous_and_never_automatically_retried(self) -> None:
        run = self.start_run()
        path = f"/boxes/{BOX_ID}/prompt"
        self.fake.fail_next("POST", path, 503, "provider_unavailable")
        value = {
            "message": "Continue after inspection",
            "expectedPromptId": run["promptId"],
            "idempotencyKey": "ambiguous-message-0001",
        }
        with self.assertRaises(controller.ControlError) as first:
            self.control.message(run["id"], value)
        self.assertEqual(first.exception.code, "ambiguous_message")
        self.assertEqual(len(self.fake.requests_for("POST", path)), 2)
        with self.assertRaises(controller.ControlError) as repeated:
            self.control.message(run["id"], value)
        self.assertEqual(repeated.exception.code, "ambiguous_message")
        self.assertEqual(len(self.fake.requests_for("POST", path)), 2)

    def test_failed_later_follow_up_does_not_reuse_an_older_delivery_receipt(self) -> None:
        run = self.start_run()
        first = self.control.message(
            run["id"],
            {
                "message": "First follow-up",
                "expectedPromptId": run["promptId"],
                "idempotencyKey": "message-key-first",
            },
        )
        path = f"/boxes/{BOX_ID}/prompt"
        self.fake.fail_next("POST", path, 503, "provider_unavailable")
        value = {
            "message": "Second follow-up",
            "expectedPromptId": first["promptId"],
            "idempotencyKey": "message-key-second",
        }
        with self.assertRaises(controller.ControlError) as failed:
            self.control.message(run["id"], value)
        self.assertEqual(failed.exception.code, "ambiguous_message")
        request_count = len(self.fake.requests_for("POST", path))
        with self.assertRaises(controller.ControlError) as repeated:
            self.control.message(run["id"], value)
        self.assertEqual(repeated.exception.code, "ambiguous_message")
        self.assertEqual(len(self.fake.requests_for("POST", path)), request_count)

    def test_ambiguous_message_blocks_every_new_key_and_binds_the_expected_prompt(self) -> None:
        run = self.start_run()
        path = f"/boxes/{BOX_ID}/prompt"
        self.fake.fail_next("POST", path, 503, "provider_unavailable")
        with self.assertRaises(controller.ControlError) as ambiguous:
            self.control.message(
                run["id"],
                {
                    "message": "Potentially accepted direction",
                    "expectedPromptId": run["promptId"],
                    "idempotencyKey": "ambiguous-key-one",
                },
            )
        self.assertEqual(ambiguous.exception.code, "ambiguous_message")
        request_count = len(self.fake.requests_for("POST", path))
        with self.assertRaises(controller.ControlError) as blocked:
            self.control.message(
                run["id"],
                {
                    "message": "A different direction must not bypass ambiguity",
                    "expectedPromptId": run["promptId"],
                    "idempotencyKey": "ambiguous-key-two",
                },
            )
        self.assertEqual(blocked.exception.code, "ambiguous_message")
        self.assertEqual(len(self.fake.requests_for("POST", path)), request_count)

        self.store.update(
            run["id"],
            lastMessageKey=model.key_hash("crash-window-key"),
            lastMessageHash="f" * 64,
            lastMessagePromptId=None,
            lastError=None,
        )
        with self.assertRaises(controller.ControlError) as crashed:
            self.control.message(
                run["id"],
                {
                    "message": "Do not overwrite a crash-window marker",
                    "expectedPromptId": run["promptId"],
                    "idempotencyKey": "after-crash-key",
                },
            )
        self.assertEqual(crashed.exception.code, "ambiguous_message")

    def test_reusing_message_key_with_another_expected_prompt_conflicts(self) -> None:
        run = self.start_run()
        value = {
            "message": "One exact request",
            "expectedPromptId": run["promptId"],
            "idempotencyKey": "full-request-key",
        }
        self.control.message(run["id"], value)
        with self.assertRaises(controller.ControlError) as conflict:
            self.control.message(run["id"], {**value, "expectedPromptId": "prompt-2"})
        self.assertEqual(conflict.exception.code, "idempotency_conflict")

    def test_interrupt_is_revision_guarded_and_stateful(self) -> None:
        run = self.start_run()
        with self.assertRaises(controller.ControlError) as stale:
            self.control.interrupt(run["id"], expected_prompt_id="prompt-stale")
        self.assertEqual(stale.exception.code, "stale_prompt")
        self.assertEqual(self.fake.requests_for("POST", f"/boxes/{BOX_ID}/interrupt"), [])
        interrupted = self.control.interrupt(run["id"], expected_prompt_id=run["promptId"])
        self.assertEqual(interrupted["status"], "needs_input")
        self.assertEqual(interrupted["promptStatus"], "failed")

    def test_desktop_preview_stop_and_resume_keep_ephemeral_urls_out_of_state(self) -> None:
        run = self.start_run()
        desktop_one = self.control.desktop_url(run["id"])
        desktop_two = self.control.desktop_url(run["id"])
        preview_one = self.control.preview_url(run["id"])
        preview_two = self.control.preview_url(run["id"])
        self.assertNotEqual(desktop_one, desktop_two)
        self.assertEqual(preview_one, preview_two)
        self.assertEqual(
            preview_one,
            "https://fixture-4173.on.ascii.dev?_token=fixture-preview-token",
        )
        record = self.store.get(run["id"])
        self.assertEqual(record["previewProcessId"], 91)
        detached = [
            item
            for item in self.fake.requests_for("POST", f"/boxes/{BOX_ID}/commands")
            if item.body.get("detached") is True
        ]
        self.assertEqual(len(detached), 1)
        database_bytes = self.config.database.read_bytes()
        self.assertNotIn(b"desktop.example.invalid", database_bytes)
        self.assertNotIn(b"fixture-preview-token", database_bytes)

        stopped = self.control.stop(run["id"])
        self.assertEqual(stopped["status"], "stopped")
        self.assertEqual(stopped["boxState"], "archiving")
        resumed = self.control.resume(run["id"], ttl_seconds=3600)
        self.assertEqual(resumed["status"], "needs_input")
        self.assertEqual(resumed["boxState"], "ready")
        self.assertEqual(resumed["ttlSeconds"], 3600)
        self.assertIsNone(resumed["previewProcessId"])
        self.assertEqual(resumed["promptId"], run["promptId"])

    def test_released_box_rejects_desktop_and_preview_without_side_effects(self) -> None:
        run = self.start_run()
        self.control.stop(run["id"])
        command_count = len(self.fake.requests_for("POST", f"/boxes/{BOX_ID}/commands"))
        for operation in (
            lambda: self.control.desktop_url(run["id"]),
            lambda: self.control.preview_url(run["id"]),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises(controller.ControlError) as unavailable:
                    operation()
                self.assertEqual(unavailable.exception.code, "box_unavailable")
        self.assertEqual(self.fake.desktop_counter, 0)
        self.assertEqual(
            len(self.fake.requests_for("POST", f"/boxes/{BOX_ID}/commands")),
            command_count,
        )

    def test_lost_preview_launch_response_is_never_replayed(self) -> None:
        run = self.start_run()
        client = self.control._box()
        original_command = client.command

        def lose_response(*args: object, **kwargs: object) -> dict[str, object]:
            result = original_command(*args, **kwargs)
            if kwargs.get("detached") is True:
                raise controller.BoxError(
                    "lost preview response",
                    status=None,
                    code="network_error",
                    retryable=False,
                )
            return result

        with mock.patch.object(client, "command", side_effect=lose_response):
            with self.assertRaises(controller.ControlError) as ambiguous:
                self.control.preview_url(run["id"])
        self.assertEqual(ambiguous.exception.code, "ambiguous_preview")
        detached_count = sum(
            item.body.get("detached") is True
            for item in self.fake.requests_for("POST", f"/boxes/{BOX_ID}/commands")
        )
        with self.assertRaises(controller.ControlError) as blocked:
            self.control.preview_url(run["id"])
        self.assertEqual(blocked.exception.code, "ambiguous_preview")
        self.assertEqual(
            sum(
                item.body.get("detached") is True
                for item in self.fake.requests_for("POST", f"/boxes/{BOX_ID}/commands")
            ),
            detached_count,
        )

    def test_preview_requires_an_integer_process_identity(self) -> None:
        run = self.start_run()
        self.fake.command_results[("python3", "-m", "fixture.preview")] = {
            "ok": True,
            "type": "command.started",
            "processId": "process-91",
            "status": "running",
        }
        with self.assertRaises(controller.ControlError) as invalid:
            self.control.preview_url(run["id"])
        self.assertEqual(invalid.exception.code, "ambiguous_preview")
        self.assertEqual(self.store.get(run["id"])["previewState"], "ambiguous")

    def test_resume_transport_failure_restores_a_released_state(self) -> None:
        run = self.start_run()
        self.control.stop(run["id"])
        self.fake.box_state = "archived"
        self.fake.fail_next("POST", f"/boxes/{BOX_ID}/resume", 503, "provider_unavailable")
        with self.assertRaises(controller.ControlError) as failed:
            self.control.resume(run["id"], ttl_seconds=3600)
        self.assertEqual(failed.exception.code, "ambiguous_resume")
        record = self.store.get(run["id"])
        self.assertEqual(record["status"], "stopped")
        self.assertTrue(record["slotReleased"])
        self.assertEqual(record["boxState"], "archived")
        self.assertEqual(record["promptId"], run["promptId"])

    def test_resume_without_a_prompt_revision_never_claims_send_next_is_available(self) -> None:
        run = self.start_run()
        self.control.stop(run["id"])
        self.fake.box_state = "archived"
        self.store.update(run["id"], promptId=None, promptStatus=None)

        resumed = self.control.resume(run["id"], ttl_seconds=3600)
        self.assertEqual(resumed["status"], "needs_input")
        self.assertIsNone(resumed["promptId"])
        self.assertEqual(resumed["lastError"], "missing_prompt_revision")
        self.assertNotIn("Send the next prompt", resumed["statusDetail"])

    def test_stale_resume_retains_the_prompt_revision_for_recovery(self) -> None:
        run = self.start_run()
        self.fake.prompt_status_value = "failed"
        self.store.update(
            run["id"],
            status="starting",
            statusDetail="Resuming the Box",
            startAttemptAt=model.now_rfc3339(),
            slotReleased=False,
        )
        in_flight = self.control.read(run["id"], refresh=True)
        self.assertEqual(in_flight["status"], "starting")

        self.store.update(
            run["id"],
            startAttemptAt="2020-01-01T00:00:00Z",
        )
        recovered = self.control.read(run["id"], refresh=True)
        self.assertEqual(recovered["status"], "needs_input")
        self.assertEqual(recovered["promptId"], run["promptId"])

        messaged = self.control.message(
            run["id"],
            {
                "message": "Continue after the recovered resume.",
                "expectedPromptId": recovered["promptId"],
                "idempotencyKey": "recovered-resume-message",
            },
        )
        self.assertEqual(messaged["status"], "working")

    def test_read_reconciles_a_stale_incomplete_start(self) -> None:
        run_id = "run_" + "c" * 20
        self.store.create(
            {
                "id": run_id,
                "requestHash": "stale-request",
                "repo": "octocat/control-fixture",
                "status": "starting",
                "createdAt": "2020-01-01T00:00:00Z",
                "startAttemptAt": "2020-01-01T00:00:00Z",
                "updatedAt": "2020-01-01T00:00:00Z",
            }
        )
        reconciled = self.control.read(run_id)
        self.assertEqual(reconciled["status"], "failed")
        self.assertTrue(reconciled["slotReleased"])
        self.assertEqual(reconciled["lastError"], "incomplete_start")

    def test_released_box_preserves_verified_delivery(self) -> None:
        run = self.start_run()
        self.fake.finish_agent()
        handed = self.control.handoff(run["id"])
        self.assertEqual(handed["status"], "review")

        self.fake.box_state = "archived"
        refreshed = self.control.read(run["id"])

        self.assertEqual(refreshed["status"], "review")
        self.assertEqual(refreshed["boxState"], "archived")
        self.assertTrue(refreshed["slotReleased"])
        self.assertEqual(refreshed["prNumber"], 17)
        self.assertIn("Box is archived", refreshed["statusDetail"])

    def test_archived_delivery_can_resume_after_github_proof_becomes_stale(self) -> None:
        run = self.start_run()
        self.fake.finish_agent()
        handed = self.control.handoff(run["id"])
        self.fake.box_state = "archived"
        archived = self.control.read(run["id"])
        self.assertEqual(archived["status"], "review")
        self.assertTrue(archived["slotReleased"])

        self.fake.host_pr["headRefOid"] = BASE_SHA
        with self.assertRaises(controller.ControlError) as stale:
            self.control.handoff(run["id"])
        self.assertEqual(stale.exception.code, "pr_identity")
        invalidated = self.store.get(run["id"])
        self.assertEqual(invalidated["status"], "needs_input")
        self.assertTrue(invalidated["slotReleased"])

        resumed = self.control.resume(run["id"], ttl_seconds=3600)
        self.assertEqual(resumed["status"], "needs_input")
        self.assertFalse(resumed["slotReleased"])
        self.assertEqual(resumed["boxState"], "ready")


class ControllerHandoffTests(ControllerHarness):
    def test_exact_open_non_draft_pull_request_reaches_review(self) -> None:
        run = self.start_run()
        self.fake.finish_agent()
        handed = self.control.handoff(run["id"])
        self.assertEqual(handed["status"], "review")
        self.assertEqual(handed["headSha"], HEAD_SHA)
        self.assertEqual(handed["prNumber"], 17)
        self.assertEqual(
            handed["prUrl"],
            "https://github.com/octocat/control-fixture/pull/17",
        )
        self.assertEqual(handed["verifyReceipts"][0]["success"], True)
        commands = self.command_argv()
        self.assertIn(("python3", "-m", "fixture.verify"), commands)
        self.assertFalse(any(item[:3] == ("gh", "pr", "view") for item in commands))
        self.assertFalse(any(item[:3] == ("gh", "pr", "merge") for item in commands))

    def test_concurrent_handoffs_verify_once_and_return_the_same_review(self) -> None:
        run = self.start_run()
        self.fake.finish_agent()
        self.control.read(run["id"])

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: self.control.handoff(run["id"]), range(2)))

        self.assertEqual([item["status"] for item in results], ["review", "review"])
        commands = self.command_argv()
        self.assertEqual(commands.count(("python3", "-m", "fixture.verify")), 1)

    def test_review_revalidation_rejects_a_later_duplicate_pull_request(self) -> None:
        run = self.start_run()
        self.fake.finish_agent()
        handed = self.control.handoff(run["id"])
        self.assertEqual(handed["status"], "review")

        self.fake.host_pr_count = 2
        with self.assertRaises(controller.ControlError) as duplicate:
            self.control.handoff(run["id"])
        self.assertEqual(duplicate.exception.code, "pr_identity")
        self.assertEqual(self.store.get(run["id"])["status"], "needs_input")

    def test_handoff_requires_finished_prompt_clean_identity_and_passing_verify(self) -> None:
        run = self.start_run()
        with self.assertRaises(controller.ControlError) as active:
            self.control.handoff(run["id"])
        self.assertEqual(active.exception.code, "prompt_active")

        self.fake.finish_agent()
        self.fake.dirty = True
        with self.assertRaises(controller.ControlError) as dirty:
            self.control.handoff(run["id"])
        self.assertEqual(dirty.exception.code, "dirty_handoff")
        self.fake.dirty = False
        self.fake.command_failures[("python3", "-m", "fixture.verify")] = 9
        with self.assertRaises(controller.ControlError) as verification:
            self.control.handoff(run["id"])
        self.assertEqual(verification.exception.code, "command_failed")
        self.assertEqual(self.store.get(run["id"])["status"], "needs_input")

    def test_handoff_rejects_false_success_timed_out_verification(self) -> None:
        run = self.start_run()
        self.fake.finish_agent()
        self.fake.command_results[("python3", "-m", "fixture.verify")] = {
            "ok": True,
            "type": "command.finished",
            "exitCode": 0,
            "success": False,
            "timedOut": True,
            "stdout": "",
            "stderr": "timed out",
        }
        with self.assertRaises(controller.ControlError) as failed:
            self.control.handoff(run["id"])
        self.assertEqual(failed.exception.code, "command_invalid")
        self.assertEqual(self.store.get(run["id"])["status"], "needs_input")

    def _assert_invalid_verify_result(self, result: dict[str, object]) -> None:
        self.fake.command_results[("python3", "-m", "fixture.verify")] = result
        run = self.start_run()
        self.fake.finish_agent()
        with self.assertRaises(controller.ControlError) as invalid:
            self.control.handoff(run["id"])
        self.assertEqual(invalid.exception.code, "invalid_json_response")

    def test_handoff_rejects_boolean_command_exit_code(self) -> None:
        self._assert_invalid_verify_result(
            {
                "ok": True,
                "type": "command.finished",
                "exitCode": False,
                "success": True,
                "timedOut": False,
                "stdout": "",
                "stderr": "",
            }
        )

    def test_handoff_rejects_float_command_exit_code(self) -> None:
        self._assert_invalid_verify_result(
            {
                "ok": True,
                "type": "command.finished",
                "exitCode": 0.0,
                "success": True,
                "timedOut": False,
                "stdout": "",
                "stderr": "",
            }
        )

    def test_handoff_rejects_missing_command_timeout_field(self) -> None:
        self._assert_invalid_verify_result(
            {
                "ok": True,
                "type": "command.finished",
                "exitCode": 0,
                "success": True,
                "stdout": "",
                "stderr": "",
            }
        )

    def test_handoff_rejects_changed_origin_and_multiple_open_pulls(self) -> None:
        run = self.start_run()
        self.fake.finish_agent()
        self.fake.origin_repo = "attacker/substitute"
        with self.assertRaises(controller.ControlError) as wrong_origin:
            self.control.handoff(run["id"])
        self.assertEqual(wrong_origin.exception.code, "pr_identity")

        self.fake.origin_repo = self.fake.repo
        self.fake.host_pr_count = 2
        with self.assertRaises(controller.ControlError) as duplicates:
            self.control.handoff(run["id"])
        self.assertEqual(duplicates.exception.code, "pr_identity")

    def test_handoff_rechecks_branch_after_verification(self) -> None:
        run = self.start_run()
        self.fake.finish_agent()
        self.fake.verify_branch = "main"
        with self.assertRaises(controller.ControlError) as changed:
            self.control.handoff(run["id"])
        self.assertEqual(changed.exception.code, "verification_changed_branch")
        self.assertEqual(self.store.get(run["id"])["status"], "needs_input")

    def test_handoff_authenticates_the_stored_worker_contract(self) -> None:
        run = self.start_run()
        self.fake.finish_agent()
        changed = dict(run["workerConfig"])
        changed["verify"] = []
        self.store.update(run["id"], workerConfig=changed)
        command_count = len(self.fake.requests_for("POST", f"/boxes/{BOX_ID}/commands"))
        with self.assertRaises(controller.ControlError) as tampered:
            self.control.handoff(run["id"])
        self.assertEqual(tampered.exception.code, "worker_contract_changed")
        self.assertEqual(
            len(self.fake.requests_for("POST", f"/boxes/{BOX_ID}/commands")),
            command_count,
        )

    def test_handoff_rejects_worker_contract_edits_reverted_in_later_commits(self) -> None:
        run = self.start_run()
        self.fake.finish_agent()
        self.fake.worker_history_count = 2
        with self.assertRaises(controller.ControlError) as changed:
            self.control.handoff(run["id"])
        self.assertEqual(changed.exception.code, "worker_contract_changed")

    def test_handoff_rejects_git_replacements(self) -> None:
        run = self.start_run()
        self.fake.finish_agent()
        self.fake.replacement_refs = ["refs/replace/" + HEAD_SHA]
        with self.assertRaises(controller.ControlError) as untrusted:
            self.control.handoff(run["id"])
        self.assertEqual(untrusted.exception.code, "git_history_untrusted")

    def test_handoff_rejects_shallow_history(self) -> None:
        run = self.start_run()
        self.fake.finish_agent()
        self.fake.shallow_repository = True
        with self.assertRaises(controller.ControlError) as untrusted:
            self.control.handoff(run["id"])
        self.assertEqual(untrusted.exception.code, "git_history_untrusted")

    def test_handoff_rejects_git_grafts(self) -> None:
        run = self.start_run()
        self.fake.finish_agent()
        self.fake.grafts_present = True
        with self.assertRaises(controller.ControlError) as untrusted:
            self.control.handoff(run["id"])
        self.assertEqual(untrusted.exception.code, "git_history_untrusted")

    def test_handoff_rejects_index_flags_that_hide_changes_before_verification(self) -> None:
        run = self.start_run()
        self.fake.finish_agent()
        self.fake.index_entries = ["H .codexstack/worker.json", "h app.txt"]
        with self.assertRaises(controller.ControlError) as untrusted:
            self.control.handoff(run["id"])
        self.assertEqual(untrusted.exception.code, "git_index_untrusted")
        self.assertNotIn(("python3", "-m", "fixture.verify"), self.command_argv())

    def test_handoff_rejects_index_flags_added_during_verification(self) -> None:
        run = self.start_run()
        self.fake.finish_agent()
        self.fake.verify_index_entries = ["H .codexstack/worker.json", "S app.txt"]
        with self.assertRaises(controller.ControlError) as untrusted:
            self.control.handoff(run["id"])
        self.assertEqual(untrusted.exception.code, "git_index_untrusted")
        self.assertIn(("python3", "-m", "fixture.verify"), self.command_argv())

    def test_wrong_pull_request_state_or_exact_head_never_reaches_review(self) -> None:
        for field, bad_value in (
            ("state", "CLOSED"),
            ("isDraft", True),
            ("baseRefName", "develop"),
            ("headRefName", "other-branch"),
            ("headRefOid", BASE_SHA),
            ("number", 0),
            ("url", "https://example.invalid/pull/17"),
        ):
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as directory, FakeBoxServer() as fake:
                    database = Path(directory) / "control.sqlite3"
                    run_store = store.RunStore(database)
                    config = replace(
                        self.config,
                        box_api_key=fake.api_key,
                        box_api_base=fake.url,
                        database=database,
                    )
                    control = controller.RunController(
                        config,
                        store=run_store,
                        sleeper=lambda _: None,
                        github_lookup=fake.github_pull,
                        github_list=fake.github_pulls,
                    )
                    run = control.start(start_request())
                    fake.finish_agent()
                    fake.host_pr[field] = bad_value
                    with self.assertRaises(controller.ControlError) as raised:
                        control.handoff(run["id"])
                    self.assertEqual(raised.exception.code, "pr_identity")
                    self.assertEqual(run_store.get(run["id"])["status"], "needs_input")


if __name__ == "__main__":
    unittest.main()
