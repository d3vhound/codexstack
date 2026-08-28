#!/usr/bin/env python3
"""Read-only readiness checks for local ASCII Box and an optional remote Box."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass


BOX_ID = re.compile(r"^bx_[23456789abcdefghjkmnpqrstuvwxyz]{8}$")


@dataclass(frozen=True)
class Check:
    name: str
    command: tuple[str, ...] | None
    required: bool = True
    missing: str | None = None
    contains: str | None = None


def execute(check: Check, timeout: int) -> bool:
    if check.command is None:
        ok = False
        detail = check.missing or "not found"
    else:
        try:
            result = subprocess.run(
                list(check.command),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE if check.contains else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
                timeout=timeout,
            )
            ok = result.returncode == 0 and (
                check.contains is None or check.contains in (result.stdout or "")
            )
            if result.returncode != 0:
                detail = f"exit {result.returncode}"
            elif check.contains is not None and not ok:
                detail = f"missing {check.contains}"
            else:
                detail = "ready"
        except subprocess.TimeoutExpired:
            ok = False
            detail = f"timed out after {timeout}s"
        except OSError as exc:
            ok = False
            detail = exc.strerror or type(exc).__name__

    state = "PASS" if ok else ("FAIL" if check.required else "WARN")
    print(f"{state:4}  {check.name}: {detail}")
    return ok or not check.required


def local_command(executable: str, *args: str) -> tuple[str, ...] | None:
    path = shutil.which(executable)
    return (path, *args) if path else None


def remote(box_executable: str, box_id: str, *command: str) -> tuple[str, ...]:
    return (box_executable, "exec", box_id, "--timeout", "30", "--", *command)


def box_id(value: str) -> str:
    if BOX_ID.fullmatch(value):
        return value
    raise argparse.ArgumentTypeError("expected a concrete bx_... identifier")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check Box, Codex, GitHub, plugin, and MCP readiness without printing secrets."
    )
    parser.add_argument("--box", dest="box_id", type=box_id, help="also check this running Box")
    parser.add_argument("--timeout", type=int, default=30, help="seconds per check (default: 30)")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat optional local Codex and remote GitHub/MCP checks as required",
    )
    args = parser.parse_args()
    if not 1 <= args.timeout <= 120:
        parser.error("--timeout must be between 1 and 120 seconds")
    return args


def main() -> int:
    args = parse_args()
    box_path = shutil.which("box")
    checks = [
        Check("Box CLI installed", (box_path, "--help") if box_path else None, missing="install from box.ascii.dev"),
        Check("Box account authenticated", (box_path, "status") if box_path else None),
        Check(
            "local Codex CLI installed",
            local_command("codex", "--version"),
            required=args.strict,
            missing="optional on the control machine",
        ),
    ]

    if args.box_id:
        if not box_path:
            checks.append(Check("remote checks", None, missing="Box CLI unavailable"))
        else:
            checks.extend(
                [
                    Check("Box is reachable", (box_path, "info", args.box_id)),
                    Check(
                        "remote Codex CLI",
                        remote(box_path, args.box_id, "codex", "--version"),
                    ),
                    Check(
                        "remote ChatGPT/Codex login",
                        remote(box_path, args.box_id, "codex", "login", "status"),
                    ),
                    Check(
                        "remote GitHub login",
                        remote(box_path, args.box_id, "gh", "auth", "status"),
                        required=args.strict,
                    ),
                    Check(
                        "CodexStack plugin installed",
                        remote(
                            box_path,
                            args.box_id,
                            "codex",
                            "plugin",
                            "list",
                            "--json",
                        ),
                        contains="codexstack",
                    ),
                    Check(
                        "remote MCP configuration readable",
                        remote(box_path, args.box_id, "codex", "mcp", "list"),
                        required=args.strict,
                    ),
                ]
            )

    results = [execute(check, args.timeout) for check in checks]
    print(
        "\nCodexStack did not inspect or print credential contents; "
        "the checked CLIs may read their own auth stores."
    )
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
