#!/usr/bin/env python3
"""Small, explicit, credential-free wrapper around documented Box CLI commands."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


DEFAULTS: dict[str, Any] = {
    "environment": "codexstack",
    "template": "codexstack-base",
    "ttl_seconds": 43_200,
    "template_ttl_seconds": 3_600,
    "marketplace": "d3vhound/codexstack",
    "plugin": "codexstack@codexstack",
    "repositories": [],
}
PROFILE_KEYS = frozenset(DEFAULTS)
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PLUGIN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9_.-]*$"
)
BOX_ID = re.compile(r"^bx_[A-Za-z0-9]+$")
MAX_TTL = 2_592_000


class BoxctlError(RuntimeError):
    pass


class Runner:
    def run(
        self,
        command: Sequence[str],
        *,
        capture: bool = False,
        check: bool = True,
        label: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        argv = [str(part) for part in command]
        print(label or f"+ {shlex.join(argv)}", file=sys.stderr)
        try:
            return subprocess.run(
                argv,
                text=True,
                stdout=subprocess.PIPE if capture else None,
                stderr=None,
                check=check,
            )
        except FileNotFoundError as exc:
            raise BoxctlError(f"command not found: {argv[0]}") from exc
        except subprocess.CalledProcessError as exc:
            raise BoxctlError(f"command failed with exit {exc.returncode}: {argv[0]}") from exc


def load_profile(path: Path | None) -> dict[str, Any]:
    profile = dict(DEFAULTS)
    if path is None:
        return profile
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BoxctlError(f"cannot load profile {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise BoxctlError("profile root must be a JSON object")
    unknown = set(loaded) - PROFILE_KEYS
    if unknown:
        raise BoxctlError(f"unsupported profile keys: {', '.join(sorted(unknown))}")
    profile.update(loaded)
    validate_profile(profile)
    return profile


def validate_profile(profile: dict[str, Any]) -> None:
    for key in ("environment", "template"):
        value = profile.get(key)
        if not isinstance(value, str) or not NAME.fullmatch(value):
            raise BoxctlError(f"profile {key!r} must be a simple name")
    marketplace = profile.get("marketplace")
    if not isinstance(marketplace, str):
        raise BoxctlError("profile 'marketplace' must be GitHub shorthand OWNER/REPO")
    try:
        repo(marketplace)
    except argparse.ArgumentTypeError as exc:
        raise BoxctlError(
            "profile 'marketplace' must be GitHub shorthand OWNER/REPO"
        ) from exc
    plugin = profile.get("plugin")
    if not isinstance(plugin, str) or not PLUGIN.fullmatch(plugin):
        raise BoxctlError("profile 'plugin' must be PLUGIN@MARKETPLACE")
    if plugin.rsplit("@", 1)[1] != marketplace.rsplit("/", 1)[1]:
        raise BoxctlError("profile plugin marketplace must match the marketplace repository name")
    finite_ttl(profile.get("ttl_seconds"), "ttl_seconds")
    finite_ttl(profile.get("template_ttl_seconds"), "template_ttl_seconds")
    repositories(profile.get("repositories"))


def finite_ttl(value: Any, label: str = "TTL") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 60 <= value <= MAX_TTL:
        raise BoxctlError(f"{label} must be an integer from 60 to {MAX_TTL} seconds")
    return value


def port(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= number <= 65_535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return number


def simple_name(value: str, label: str) -> str:
    if not NAME.fullmatch(value):
        raise BoxctlError(f"{label} must contain only letters, digits, dot, underscore, or hyphen")
    return value


def box_id(value: str) -> str:
    if BOX_ID.fullmatch(value):
        return value
    raise argparse.ArgumentTypeError("expected a concrete bx_... identifier")


def repo(value: str) -> str:
    if not REPO.fullmatch(value):
        raise argparse.ArgumentTypeError("expected GitHub OWNER/REPO")
    owner, repository = value.split("/", 1)
    if (
        owner in {".", ".."}
        or repository in {".", ".."}
        or owner.startswith("-")
        or repository.startswith("-")
    ):
        raise argparse.ArgumentTypeError("expected GitHub OWNER/REPO")
    return value


def repositories(value: Any) -> list[tuple[str, str | None]]:
    if not isinstance(value, list):
        raise BoxctlError("profile 'repositories' must be a list")
    result: list[tuple[str, str | None]] = []
    for item in value:
        if isinstance(item, str):
            repo_name, branch = item, None
        elif isinstance(item, dict) and set(item) <= {"repo", "branch"}:
            repo_name = item.get("repo")
            branch = item.get("branch")
        else:
            raise BoxctlError("each repository must be OWNER/REPO or an object with repo and branch")
        if not isinstance(repo_name, str):
            raise BoxctlError(f"invalid repository: {repo_name!r}")
        try:
            repo(repo_name)
        except argparse.ArgumentTypeError as exc:
            raise BoxctlError(f"invalid repository: {repo_name!r}") from exc
        if branch is not None and (not isinstance(branch, str) or not NAME.fullmatch(branch)):
            raise BoxctlError(f"invalid branch for {repo_name}")
        result.append((repo_name, branch))
    return result


def require_yes(args: argparse.Namespace, action: str) -> None:
    if not getattr(args, "yes", False):
        raise BoxctlError(f"refusing to {action} without --yes")


def require_box_cli() -> None:
    if shutil.which("box") is None:
        raise BoxctlError("Box CLI not found; install it and run 'box onboard' first")


def find_box_id(output: str) -> str:
    def visit(value: Any) -> str | None:
        if isinstance(value, dict):
            for key in ("id", "boxId", "box_id"):
                candidate = value.get(key)
                if isinstance(candidate, str) and BOX_ID.fullmatch(candidate):
                    return candidate
            for child in value.values():
                found = visit(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = visit(child)
                if found:
                    return found
        return None

    for line in output.splitlines():
        try:
            found = visit(json.loads(line))
        except json.JSONDecodeError:
            found = None
        if found:
            return found
    match = re.search(r"\bbx_[A-Za-z0-9]+\b", output)
    if match:
        return match.group(0)
    raise BoxctlError("Box was created but its ID could not be parsed; run 'box list --all'")


def remote(runner: Runner, target: str, *command: str, timeout: int = 600) -> None:
    runner.run(["box", "exec", target, "--timeout", str(timeout), "--", *command])


def env_init(args: argparse.Namespace, profile: dict[str, Any], runner: Runner) -> None:
    require_yes(args, "create a private credential-bearing environment")
    name = simple_name(
        args.name if args.name is not None else profile["environment"], "environment name"
    )
    selected = repositories(profile["repositories"])
    selected.extend((item, None) for item in (args.repo or []))
    print(
        f"Creating private environment {name!r}: GitHub=yes, Agents=yes, Secrets=no, Box credentials=no.",
        file=sys.stderr,
    )
    created = False
    try:
        runner.run(["box", "env", "new", name])
        created = True
        runner.run(["box", "env", "set", name, "--safe-for-third-parties", "true"])
        for repo_name, branch in selected:
            command = ["box", "env", "add-repo", name, repo_name]
            if branch:
                command.extend(["--branch", branch])
            runner.run(command)
        runner.run(
            [
                "box",
                "env",
                "set",
                name,
                "--safe-for-third-parties",
                "false",
                "--github",
                "true",
                "--secrets",
                "false",
                "--box-credentials",
                "false",
                "--agents-credentials",
                "true",
            ]
        )
    except BoxctlError:
        if created:
            runner.run(
                ["box", "env", "set", name, "--safe-for-third-parties", "true"],
                check=False,
                label=f"+ safety fallback: protect environment {name}",
            )
        raise
    print(f"Environment ready: {name}")


def install_plugin(runner: Runner, target: str, marketplace: str, plugin: str, *, upgrade: bool) -> None:
    remote(runner, target, "codex", "plugin", "marketplace", "add", marketplace, "--json")
    if upgrade:
        marketplace_name = plugin.rsplit("@", 1)[1]
        remote(runner, target, "codex", "plugin", "marketplace", "upgrade", marketplace_name, "--json")
    remote(runner, target, "codex", "plugin", "add", plugin, "--json")


def assert_clean_template(runner: Runner, target: str) -> None:
    credential_paths = (
        "/home/user/.codex/auth.json",
        "/home/user/.claude/.credentials.json",
        "/home/user/.config/gh/hosts.yml",
        "/home/user/.config/ascii/box/config.json",
        "/home/user/.git-credentials",
        "/home/user/.ssh/id_rsa",
        "/home/user/.ssh/id_ed25519",
        "/home/user/.ssh/id_ecdsa",
        "/home/user/.ssh/id_dsa",
    )
    for path in credential_paths:
        remote(runner, target, "test", "!", "-e", path, timeout=30)


def template_build(args: argparse.Namespace, profile: dict[str, Any], runner: Runner) -> None:
    require_yes(args, "create and snapshot a credential-free template Box")
    template = simple_name(
        args.name if args.name is not None else profile["template"], "template name"
    )
    ttl = finite_ttl(args.ttl if args.ttl is not None else profile["template_ttl_seconds"])
    marketplace = profile["marketplace"]
    plugin = profile["plugin"]
    result = runner.run(
        ["box", "new", "--no-env", "--ttl", str(ttl), "--json"],
        capture=True,
        label=f"+ box new --no-env --ttl {ttl} --json",
    )
    target = find_box_id(result.stdout)
    stop_requested = False
    try:
        install_plugin(runner, target, marketplace, plugin, upgrade=False)
        assert_clean_template(runner, target)
        runner.run(["box", "snapshot", target, template])
        runner.run(["box", "stop", target])
        stop_requested = True
    finally:
        if not stop_requested:
            runner.run(
                ["box", "stop", target],
                check=False,
                label=f"+ safety cleanup: stop template source {target}",
            )
    print(
        f"Template ready: {template} (stop requested for source Box {target}; "
        "use 'box info' to confirm archived state)"
    )


def launch(args: argparse.Namespace, profile: dict[str, Any], runner: Runner) -> None:
    require_yes(args, "launch a private Box with account credentials")
    environment = simple_name(
        args.environment if args.environment is not None else profile["environment"],
        "environment name",
    )
    template = simple_name(
        args.template if args.template is not None else profile["template"], "template name"
    )
    ttl = finite_ttl(args.ttl if args.ttl is not None else profile["ttl_seconds"])
    command = [
        "box",
        "new",
        "--from",
        template,
        "--environment",
        environment,
        "--ttl",
        str(ttl),
    ]
    if args.type:
        command.extend(["--type", args.type])
    command.append("--json")
    result = runner.run(command, capture=True)
    target = find_box_id(result.stdout)
    print(target)


def dispatch(args: argparse.Namespace, profile: dict[str, Any], runner: Runner) -> None:
    command = args.command
    if command == "env-init":
        env_init(args, profile, runner)
    elif command == "template-build":
        template_build(args, profile, runner)
    elif command == "launch":
        launch(args, profile, runner)
    elif command == "login":
        require_yes(args, "store a ChatGPT login in this trusted Box")
        runner.run(
            ["box", "ssh", args.box_id, "--", "codex", "login", "--device-auth"],
            label=f"+ interactive device login in {args.box_id}",
        )
    elif command == "plugin-sync":
        require_yes(args, "update CodexStack in this Box")
        install_plugin(runner, args.box_id, profile["marketplace"], profile["plugin"], upgrade=True)
    elif command == "prompt":
        argv = ["box", "prompt", args.box_id, "--provider", "codex"]
        if args.model:
            argv.extend(["--model", args.model])
        if args.reasoning_effort:
            argv.extend(["--reasoning-effort", args.reasoning_effort])
        argv.append(args.prompt)
        runner.run(argv, label=f"+ box prompt {args.box_id} --provider codex <prompt omitted>")
    elif command == "events":
        argv = ["box", "events", args.box_id]
        if args.follow:
            argv.append("--follow")
        runner.run(argv)
    elif command == "interrupt":
        require_yes(args, "interrupt the active managed agent turn")
        runner.run(["box", "interrupt", args.box_id])
    elif command == "ssh":
        argv = ["box", "ssh", args.box_id]
        label = None
        if args.remote_command:
            remote_command = args.remote_command
            if remote_command[0] == "--":
                remote_command = remote_command[1:]
            argv.extend(["--", *remote_command])
            label = f"+ box ssh {args.box_id} -- <remote command omitted>"
        runner.run(argv, label=label)
    elif command == "forward":
        local = args.local if args.local is not None else args.remote
        runner.run(
            [
                "box",
                "forward",
                args.box_id,
                "--remote",
                str(args.remote),
                "--local",
                str(local),
                "--bind",
                "127.0.0.1",
            ]
        )
    elif command == "info":
        runner.run(["box", "info", args.box_id])
    elif command == "stop":
        require_yes(args, "snapshot and stop this Box")
        runner.run(["box", "stop", args.box_id])
    elif command == "resume":
        require_yes(args, "resume this Box")
        ttl = finite_ttl(args.ttl if args.ttl is not None else profile["ttl_seconds"])
        argv = ["box", "resume", args.box_id, "--ttl", str(ttl)]
        if args.environment:
            argv.extend(["--environment", simple_name(args.environment, "environment name")])
        runner.run(argv)
    elif command == "extend":
        require_yes(args, "extend this Box's finite lifetime")
        runner.run(["box", "extend", args.box_id, "--ttl", str(finite_ttl(args.ttl))])
    else:
        raise BoxctlError(f"unsupported command: {command}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Explicit, finite-lifetime ASCII Box controls for CodexStack."
    )
    root.add_argument("--profile", type=Path, help="credential-free JSON profile")
    commands = root.add_subparsers(dest="command", required=True)

    env = commands.add_parser("env-init", help="create the private GitHub + Agents environment")
    env.add_argument("--name")
    env.add_argument("--repo", action="append", type=repo, help="GitHub OWNER/REPO; repeatable")
    env.add_argument("--yes", action="store_true", help="confirm environment creation")

    template = commands.add_parser("template-build", help="build a credential-free named snapshot")
    template.add_argument("--name")
    template.add_argument("--ttl", type=int)
    template.add_argument("--yes", action="store_true", help="confirm Box and snapshot creation")

    new = commands.add_parser("launch", help="launch template + private environment")
    new.add_argument("--environment")
    new.add_argument("--template")
    new.add_argument("--ttl", type=int)
    new.add_argument("--type", choices=("small", "default", "large"))
    new.add_argument("--yes", action="store_true", help="confirm private Box creation")

    login = commands.add_parser("login", help="run ChatGPT device auth inside a trusted Box")
    login.add_argument("box_id", type=box_id)
    login.add_argument("--yes", action="store_true")

    sync = commands.add_parser("plugin-sync", help="upgrade the marketplace and install CodexStack")
    sync.add_argument("box_id", type=box_id)
    sync.add_argument("--yes", action="store_true")

    prompt = commands.add_parser("prompt", help="queue a managed Codex prompt")
    prompt.add_argument("box_id", type=box_id)
    prompt.add_argument("prompt")
    prompt.add_argument("--model")
    prompt.add_argument("--reasoning-effort")

    events = commands.add_parser("events", help="read managed-agent events")
    events.add_argument("box_id", type=box_id)
    events.add_argument("--follow", action="store_true")

    interrupt = commands.add_parser("interrupt", help="interrupt managed agent work")
    interrupt.add_argument("box_id", type=box_id)
    interrupt.add_argument("--yes", action="store_true")

    ssh = commands.add_parser("ssh", help="open SSH or run an argument-array command")
    ssh.add_argument("box_id", type=box_id)
    ssh.add_argument("remote_command", nargs=argparse.REMAINDER)

    forward = commands.add_parser("forward", help="forward a Box port to local loopback")
    forward.add_argument("box_id", type=box_id)
    forward.add_argument("remote", type=port)
    forward.add_argument("--local", type=port)

    info = commands.add_parser("info", help="show Box state and TTL")
    info.add_argument("box_id", type=box_id)

    stop = commands.add_parser("stop", help="snapshot and stop a Box")
    stop.add_argument("box_id", type=box_id)
    stop.add_argument("--yes", action="store_true")

    resume = commands.add_parser("resume", help="resume a Box with a finite TTL")
    resume.add_argument("box_id", type=box_id)
    resume.add_argument("--ttl", type=int)
    resume.add_argument("--environment")
    resume.add_argument("--yes", action="store_true")

    extend = commands.add_parser("extend", help="extend a Box with a finite TTL")
    extend.add_argument("box_id", type=box_id)
    extend.add_argument("--ttl", type=int, required=True)
    extend.add_argument("--yes", action="store_true")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        profile = load_profile(args.profile)
        validate_profile(profile)
        require_box_cli()
        dispatch(args, profile, Runner())
    except BoxctlError as exc:
        print(f"boxctl: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("boxctl: interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
