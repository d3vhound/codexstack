from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import BinaryIO

from .controller import ControlConfig, ControlError, RunController
from .store import RunStore


class _DatabaseLease:
    def __init__(self, database: Path):
        canonical = database.expanduser().resolve(strict=False)
        try:
            if canonical.stat().st_nlink != 1:
                raise ControlError(
                    "control database hard links are not supported",
                    code="invalid_config",
                    status=409,
                )
        except FileNotFoundError:
            pass
        path = Path(f"{canonical}.lock")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        self.file: BinaryIO = os.fdopen(descriptor, "r+b", buffering=0)
        try:
            if os.name == "nt":
                import msvcrt

                if path.stat().st_size == 0:
                    self.file.write(b"0")
                    self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            self.file.close()
            raise ControlError(
                "control database is already owned by another controller process",
                code="database_in_use",
                status=409,
            ) from exc


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="codexstack-control")
    commands = root.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run the local UI and Streamable HTTP MCP")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--database", type=Path)
    serve.add_argument("--public-url")
    mcp = commands.add_parser("mcp", help="run line-delimited stdio MCP")
    mcp.add_argument("--database", type=Path)
    return root


def controller_for(args: argparse.Namespace) -> RunController:
    config = ControlConfig.from_environ()
    changes = {}
    if getattr(args, "host", None) is not None:
        changes["host"] = args.host
    if getattr(args, "port", None) is not None:
        if not 1 <= args.port <= 65_535:
            raise ControlError("port must be from 1 to 65535", code="invalid_config")
        changes["port"] = args.port
    if getattr(args, "database", None) is not None:
        changes["database"] = args.database.expanduser()
    if getattr(args, "public_url", None) is not None:
        from .controller import _public_origin

        changes["public_origin"] = _public_origin(args.public_url)
    if changes:
        config = replace(config, **changes)
    config = replace(config, database=config.database.expanduser().resolve(strict=False))
    if config.host not in {"127.0.0.1", "localhost", "::1"}:
        raise ControlError("the built-in control service must bind to loopback", code="invalid_config")
    if config.public_origin is not None and not config.token:
        raise ControlError("public control service requires a token", code="invalid_config")
    lease = _DatabaseLease(config.database)
    controller = RunController(config, store=RunStore(config.database))
    controller._database_lease = lease
    return controller


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        controller = controller_for(args)
        if args.command == "serve":
            from .http_server import serve

            serve(controller)
            return 0
        from .mcp import serve_stdio

        serve_stdio(controller, sys.stdin, sys.stdout)
        return 0
    except (ControlError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
