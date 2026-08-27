from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BOX_SCRIPTS = ROOT / "plugins" / "codexstack" / "skills" / "box" / "scripts"


def load_script(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, BOX_SCRIPTS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves postponed annotations through the defining module.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


boxctl = load_script("codexstack_boxctl_tests", "boxctl.py")
doctor = load_script("codexstack_box_doctor_tests", "doctor.py")


BOX_ID = "bx_AbC123"


class FakeRunner:
    def __init__(self, stdout: str | None = None, fail_at: int | None = None) -> None:
        self.stdout = stdout if stdout is not None else json.dumps({"id": BOX_ID}) + "\n"
        self.fail_at = fail_at
        self.calls: list[dict[str, object]] = []

    def run(
        self,
        command,
        *,
        capture: bool = False,
        check: bool = True,
        label: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        call = {
            "command": list(command),
            "capture": capture,
            "check": check,
            "label": label,
        }
        self.calls.append(call)
        if self.fail_at == len(self.calls):
            raise boxctl.BoxctlError("injected failure")
        return subprocess.CompletedProcess(
            list(command), 0, stdout=self.stdout if capture else "", stderr=""
        )

    @property
    def commands(self) -> list[list[str]]:
        return [call["command"] for call in self.calls]  # type: ignore[misc]


def default_profile(**changes) -> dict:
    profile = dict(boxctl.DEFAULTS)
    profile.update(changes)
    boxctl.validate_profile(profile)
    return profile


def arguments(*argv: str) -> argparse.Namespace:
    return boxctl.parser().parse_args(list(argv))


def quiet_dispatch(args: argparse.Namespace, profile: dict, runner: FakeRunner) -> None:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        boxctl.dispatch(args, profile, runner)


class ProfileAndIdentifierTests(unittest.TestCase):
    def write_profile(self, value) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "profile.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_profile_is_an_allowlist_and_rejects_secret_bearing_keys(self) -> None:
        valid = {
            "environment": "private-codex",
            "template": "clean-base",
            "ttl_seconds": 7200,
            "template_ttl_seconds": 600,
            "marketplace": "octocat/codexstack",
            "plugin": "codexstack@codexstack",
            "repositories": [{"repo": "octocat/app", "branch": "main"}],
        }
        loaded = boxctl.load_profile(self.write_profile(valid))
        self.assertEqual(loaded, valid)

        for key in ("token", "secret", "auth_json", "environment_variables", "mcp"):
            with self.subTest(key=key):
                path = self.write_profile({key: "must-not-be-portable"})
                with self.assertRaisesRegex(boxctl.BoxctlError, "unsupported profile keys"):
                    boxctl.load_profile(path)

        path = self.write_profile(
            {"repositories": [{"repo": "octocat/app", "token": "credential-material"}]}
        )
        with self.assertRaisesRegex(boxctl.BoxctlError, "each repository"):
            boxctl.load_profile(path)

    def test_profile_rejects_non_objects_and_values_that_could_smuggle_arguments(self) -> None:
        with self.assertRaisesRegex(boxctl.BoxctlError, "root must be a JSON object"):
            boxctl.load_profile(self.write_profile(["not", "an", "object"]))

        bad_profiles = [
            {"environment": "prod --secrets true"},
            {"template": "base\n--no-auto-stop"},
            {"marketplace": "octocat/repo; touch PWNED"},
            {"marketplace": "../repo"},
            {"plugin": "-x@codexstack"},
            {"plugin": "codexstack@elsewhere"},
            {"repositories": [{"repo": "octocat/app", "branch": "main --force"}]},
        ]
        for value in bad_profiles:
            with self.subTest(value=value):
                with self.assertRaises(boxctl.BoxctlError):
                    boxctl.load_profile(self.write_profile(value))

    def test_ttl_is_always_finite_and_within_box_limits(self) -> None:
        self.assertEqual(boxctl.finite_ttl(60), 60)
        self.assertEqual(boxctl.finite_ttl(boxctl.MAX_TTL), boxctl.MAX_TTL)
        for invalid in (True, False, 59, boxctl.MAX_TTL + 1, 60.0, "3600", None):
            with self.subTest(value=invalid):
                with self.assertRaisesRegex(boxctl.BoxctlError, "integer from 60"):
                    boxctl.finite_ttl(invalid)

    def test_box_ids_and_github_shorthand_are_strict(self) -> None:
        for valid in (BOX_ID, "bx_0"):
            self.assertEqual(boxctl.box_id(valid), valid)
        for invalid in (
            "bx_",
            "bx_has-hyphen",
            "BX_ABC",
            "abc123",
            "bx_abc/def",
            "bx_abc --force",
            "bx_abc\nself",
            "current",
            "self",
        ):
            with self.subTest(box_id=invalid):
                with self.assertRaises(argparse.ArgumentTypeError):
                    boxctl.box_id(invalid)

        self.assertEqual(boxctl.repo("octocat/hello-world"), "octocat/hello-world")
        for invalid in (
            "octocat",
            "/hello-world",
            "octocat/",
            "../hello-world",
            "octocat/..",
            "-octocat/hello-world",
            "octocat/-hello-world",
            "octocat/one/two",
            "https://github.com/octocat/hello-world",
            "octocat/hello world",
            "octocat/hello-world;rm",
            "octocat\\hello-world",
            "octocat/hello-world\n--branch main",
        ):
            with self.subTest(repo=invalid):
                with self.assertRaises(argparse.ArgumentTypeError):
                    boxctl.repo(invalid)


class MutationBoundaryTests(unittest.TestCase):
    def test_lifecycle_and_credential_mutations_require_explicit_yes(self) -> None:
        cases = (
            ("env-init",),
            ("template-build",),
            ("launch",),
            ("login", BOX_ID),
            ("plugin-sync", BOX_ID),
            ("interrupt", BOX_ID),
            ("stop", BOX_ID),
            ("resume", BOX_ID),
            ("extend", BOX_ID, "--ttl", "3600"),
        )
        for argv in cases:
            with self.subTest(command=argv[0]):
                runner = FakeRunner()
                with self.assertRaisesRegex(boxctl.BoxctlError, "without --yes"):
                    quiet_dispatch(arguments(*argv), default_profile(), runner)
                self.assertEqual(runner.calls, [])

    def test_destructive_delete_force_and_unbounded_lifetime_are_not_exposed(self) -> None:
        root = boxctl.parser()
        subparsers = next(
            action for action in root._actions if isinstance(action, argparse._SubParsersAction)
        )
        self.assertNotIn("delete", subparsers.choices)
        all_options = {
            option
            for parser in (root, *subparsers.choices.values())
            for action in parser._actions
            for option in action.option_strings
        }
        self.assertNotIn("--force", all_options)
        self.assertNotIn("--no-auto-stop", all_options)


class CommandConstructionTests(unittest.TestCase):
    def test_env_init_is_fail_closed_and_enables_only_github_and_agents(self) -> None:
        profile = default_profile(
            repositories=[{"repo": "octocat/app", "branch": "develop"}]
        )
        runner = FakeRunner()
        quiet_dispatch(
            arguments("env-init", "--repo", "octocat/docs", "--yes"), profile, runner
        )
        self.assertEqual(
            runner.commands,
            [
                ["box", "env", "new", "codexstack"],
                ["box", "env", "set", "codexstack", "--safe-for-third-parties", "true"],
                [
                    "box", "env", "add-repo", "codexstack", "octocat/app",
                    "--branch", "develop",
                ],
                ["box", "env", "add-repo", "codexstack", "octocat/docs"],
                [
                    "box", "env", "set", "codexstack",
                    "--safe-for-third-parties", "false",
                    "--github", "true",
                    "--secrets", "false",
                    "--box-credentials", "false",
                    "--agents-credentials", "true",
                ],
            ],
        )

        failed = FakeRunner(fail_at=3)
        with self.assertRaisesRegex(boxctl.BoxctlError, "injected failure"):
            quiet_dispatch(arguments("env-init", "--yes"), profile, failed)
        self.assertEqual(
            failed.commands[-1],
            ["box", "env", "set", "codexstack", "--safe-for-third-parties", "true"],
        )
        self.assertFalse(failed.calls[-1]["check"])

    def test_template_is_built_from_no_env_verified_snapshotted_and_stop_requested(self) -> None:
        runner = FakeRunner(stdout=json.dumps({"box": {"id": BOX_ID}}) + "\n")
        quiet_dispatch(arguments("template-build", "--ttl", "600", "--yes"), default_profile(), runner)

        self.assertEqual(
            runner.commands[:3],
            [
                ["box", "new", "--no-env", "--ttl", "600", "--json"],
                [
                    "box", "exec", BOX_ID, "--timeout", "600", "--",
                    "codex", "plugin", "marketplace", "add", "d3vhound/codexstack", "--json",
                ],
                [
                    "box", "exec", BOX_ID, "--timeout", "600", "--",
                    "codex", "plugin", "add", "codexstack@codexstack", "--json",
                ],
            ],
        )
        credential_paths = {
            "/home/user/.codex/auth.json",
            "/home/user/.claude/.credentials.json",
            "/home/user/.config/gh/hosts.yml",
            "/home/user/.config/ascii/box/config.json",
            "/home/user/.git-credentials",
            "/home/user/.ssh/id_rsa",
            "/home/user/.ssh/id_ed25519",
            "/home/user/.ssh/id_ecdsa",
            "/home/user/.ssh/id_dsa",
        }
        probes = runner.commands[3:-2]
        self.assertEqual(len(probes), len(credential_paths))
        self.assertEqual({command[-1] for command in probes}, credential_paths)
        for command in probes:
            self.assertEqual(
                command[:-1],
                ["box", "exec", BOX_ID, "--timeout", "30", "--", "test", "!", "-e"],
            )
        self.assertEqual(
            runner.commands[-2:],
            [
                ["box", "snapshot", BOX_ID, "codexstack-base"],
                ["box", "stop", BOX_ID],
            ],
        )
        self.assertTrue(runner.calls[0]["capture"])
        self.assertNotIn("--no-auto-stop", runner.commands[0])

    def test_launch_uses_clean_template_private_environment_and_finite_ttl(self) -> None:
        runner = FakeRunner()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
            boxctl.dispatch(
                arguments(
                    "launch", "--environment", "private", "--template", "clean",
                    "--ttl", "7200", "--type", "large", "--yes",
                ),
                default_profile(),
                runner,
            )
        self.assertEqual(
            runner.commands,
            [[
                "box", "new", "--from", "clean", "--environment", "private",
                "--ttl", "7200", "--type", "large", "--json",
            ]],
        )
        self.assertEqual(stdout.getvalue().strip(), BOX_ID)

    def test_prompt_uses_argument_array_and_redacts_the_prompt_from_logs(self) -> None:
        prompt = "Fix auth; literal $TOKEN and `uname` must stay data"
        runner = FakeRunner()
        quiet_dispatch(
            arguments(
                "prompt", BOX_ID, prompt, "--model", "gpt-5.6-sol",
                "--reasoning-effort", "high",
            ),
            default_profile(),
            runner,
        )
        self.assertEqual(
            runner.commands,
            [[
                "box", "prompt", BOX_ID, "--provider", "codex",
                "--model", "gpt-5.6-sol", "--reasoning-effort", "high", prompt,
            ]],
        )
        label = runner.calls[0]["label"]
        self.assertEqual(label, f"+ box prompt {BOX_ID} --provider codex <prompt omitted>")
        self.assertNotIn(prompt, str(label))

    def test_forward_stop_and_resume_use_safe_exact_arguments(self) -> None:
        runner = FakeRunner()
        profile = default_profile()
        quiet_dispatch(arguments("forward", BOX_ID, "3000", "--local", "8080"), profile, runner)
        quiet_dispatch(arguments("stop", BOX_ID, "--yes"), profile, runner)
        quiet_dispatch(
            arguments(
                "resume", BOX_ID, "--ttl", "3600", "--environment", "private", "--yes"
            ),
            profile,
            runner,
        )
        self.assertEqual(
            runner.commands,
            [
                [
                    "box", "forward", BOX_ID, "--remote", "3000", "--local", "8080",
                    "--bind", "127.0.0.1",
                ],
                ["box", "stop", BOX_ID],
                [
                    "box", "resume", BOX_ID, "--ttl", "3600",
                    "--environment", "private",
                ],
            ],
        )
        flattened = [part for command in runner.commands for part in command]
        self.assertNotIn("--force", flattened)
        self.assertNotIn("--no-auto-stop", flattened)


class DoctorTests(unittest.TestCase):
    def test_doctor_rejects_untrusted_box_identifiers(self) -> None:
        self.assertEqual(doctor.box_id(BOX_ID), BOX_ID)
        for invalid in ("bx_", "other", "bx_ok --json", "bx_ok/../../auth"):
            with self.subTest(value=invalid):
                with self.assertRaises(argparse.ArgumentTypeError):
                    doctor.box_id(invalid)

    def test_doctor_does_not_print_or_explicitly_read_credential_contents(self) -> None:
        commands: list[tuple[str, ...]] = []
        invocations: list[dict[str, object]] = []

        def which(executable: str) -> str | None:
            return {"box": "/opt/bin/box", "codex": "/opt/bin/codex"}.get(executable)

        def run(command, **kwargs):
            commands.append(tuple(command))
            invocations.append(kwargs)
            stdout = '[{"name":"codexstack"}]' if "plugin" in command else ""
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

        output = io.StringIO()
        with (
            mock.patch.object(sys, "argv", ["doctor.py", "--box", BOX_ID, "--strict"]),
            mock.patch.object(doctor.shutil, "which", side_effect=which),
            mock.patch.object(doctor.subprocess, "run", side_effect=run),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(doctor.main(), 0)

        self.assertEqual(
            commands,
            [
                ("/opt/bin/box", "--help"),
                ("/opt/bin/box", "status"),
                ("/opt/bin/codex", "--version"),
                ("/opt/bin/box", "info", BOX_ID),
                ("/opt/bin/box", "exec", BOX_ID, "--timeout", "30", "--", "codex", "--version"),
                (
                    "/opt/bin/box", "exec", BOX_ID, "--timeout", "30", "--",
                    "codex", "login", "status",
                ),
                (
                    "/opt/bin/box", "exec", BOX_ID, "--timeout", "30", "--",
                    "gh", "auth", "status",
                ),
                (
                    "/opt/bin/box", "exec", BOX_ID, "--timeout", "30", "--",
                    "codex", "plugin", "list", "--json",
                ),
                (
                    "/opt/bin/box", "exec", BOX_ID, "--timeout", "30", "--",
                    "codex", "mcp", "list",
                ),
            ],
        )
        forbidden_reads = (
            "cat", "printenv", "env", "auth.json", "hosts.yml", "config.json",
            "OPENAI_API_KEY", "CHATGPT_ACCOUNT_ID",
        )
        rendered = "\n".join(" ".join(command) for command in commands)
        for forbidden in forbidden_reads:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered)
        self.assertTrue(all(call["stdin"] is subprocess.DEVNULL for call in invocations))
        self.assertTrue(all(call["stderr"] is subprocess.DEVNULL for call in invocations))
        self.assertIn("PASS", output.getvalue())
        self.assertNotIn("credential-material", output.getvalue())


if __name__ == "__main__":
    unittest.main()
