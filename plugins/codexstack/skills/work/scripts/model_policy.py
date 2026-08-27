#!/usr/bin/env python3
"""Validate a CodexStack per-role model policy against observed model IDs."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any


CONTRACT = "codexstack.models.v1"
ALIASES = frozenset({"inherit-parent", "auto"})
SCALAR_ROLES = frozenset({
    "feature, refactoring",
    "bug-fix",
    "perf-issue",
    "hillclimb",
    "judgment and prose",
    "hardest tasks",
    "how explorer",
    "how explainer",
    "why investigators",
    "why synthesizer",
    "reflect tooling",
    "reflect judgment, divergent, synthesizer",
    "swarm workers",
})
PANEL_ROLES = frozenset({
    "how critics",
    "arena runners",
    "arena cross-judge pool",
    "architect runners",
    "interrogate reviewers",
})
ALL_ROLES = SCALAR_ROLES | PANEL_ROLES
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+/-]{0,127}\Z")
MAX_BYTES = 65_536
MAX_PANEL = 16


class PolicyError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise PolicyError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _model(value: Any, label: str) -> str:
    if not isinstance(value, str) or not MODEL_ID.fullmatch(value):
        raise PolicyError(f"{label} must be a valid model ID or alias")
    return value


def _available(values: list[str]) -> set[str]:
    models = {_model(value, "available model") for value in values}
    if models & ALIASES:
        raise PolicyError("available models must contain real IDs, not aliases")
    return models


def load_policy(path_text: str) -> dict[str, Any]:
    path = Path(path_text)
    if path.is_absolute() or ".." in path.parts:
        raise PolicyError("policy path must be relative and may not contain '..'")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise PolicyError(f"cannot inspect policy: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise PolicyError("policy must be a regular non-symlink file")
    if metadata.st_size > MAX_BYTES:
        raise PolicyError(f"policy exceeds {MAX_BYTES} bytes")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise PolicyError("policy must be a regular non-symlink file")
            if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
                raise PolicyError("policy changed while it was being opened")
            payload = handle.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            raise PolicyError(f"policy exceeds {MAX_BYTES} bytes")
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot read policy JSON: {exc}") from exc
    if not isinstance(value, dict) or set(value) != {"contract", "roles"}:
        raise PolicyError("policy must contain only contract and roles")
    if value["contract"] != CONTRACT:
        raise PolicyError(f"policy contract must be {CONTRACT}")
    if not isinstance(value["roles"], dict):
        raise PolicyError("roles must be an object")
    unknown = sorted(set(value["roles"]) - ALL_ROLES)
    if unknown:
        raise PolicyError(f"unknown roles: {', '.join(unknown)}")
    return value


def validate_policy(value: dict[str, Any], available: set[str]) -> dict[str, Any]:
    roles = value["roles"]
    normalized: dict[str, str | list[str]] = {}
    unavailable: set[str] = set()
    for role in sorted(roles):
        selected = roles[role]
        if role in SCALAR_ROLES:
            models = [_model(selected, role)]
            normalized[role] = models[0]
        else:
            if not isinstance(selected, list) or not 1 <= len(selected) <= MAX_PANEL:
                raise PolicyError(f"{role} must be a list of 1 through {MAX_PANEL} model IDs or aliases")
            models = [_model(item, role) for item in selected]
            normalized[role] = models
        unavailable.update(model for model in models if model not in ALIASES and model not in available)
    if unavailable:
        raise PolicyError(f"unavailable model IDs: {', '.join(sorted(unavailable))}")
    missing = sorted(ALL_ROLES - set(roles))
    return {
        "contract": CONTRACT,
        "valid": True,
        "roles": normalized,
        "fallback_roles": missing,
        "panel_sizes": {
            role: len(normalized[role])
            for role in sorted(PANEL_ROLES & set(normalized))
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("policy", help="relative path to the JSON policy")
    parser.add_argument("--available", action="append", default=[], metavar="MODEL_ID")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        result = validate_policy(load_policy(arguments.policy), _available(arguments.available))
    except PolicyError as exc:
        print(json.dumps({"contract": CONTRACT, "valid": False, "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
