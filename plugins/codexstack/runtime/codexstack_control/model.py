from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any, Iterable


RUN_STATUSES = frozenset(
    {
        "starting",
        "working",
        "verifying",
        "needs_input",
        "review",
        "done",
        "failed",
        "stopped",
    }
)
ACTIVE_STATUSES = frozenset({"starting", "working", "verifying"})
DELIVERY_MODES = frozenset({"read_only", "local_change", "open_pull_request"})
BOX_ID = re.compile(r"^bx_[23456789abcdefghjkmnpqrstuvwxyz]{8}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA = re.compile(r"^[0-9a-f]{40}$")
MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
EFFORT = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
RUN_ID = re.compile(r"^run_[0-9a-f]{20}$")
PROMPT_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,255}$")
MAX_WORKER_BYTES = 65_536
MAX_GOAL_BYTES = 32_768


class ContractError(ValueError):
    pass


def now_rfc3339() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_json_object(raw: str, label: str, *, max_bytes: int = MAX_WORKER_BYTES) -> dict[str, Any]:
    if len(raw.encode("utf-8")) > max_bytes:
        raise ContractError(f"{label} exceeds {max_bytes} bytes")

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ContractError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs)
    except json.JSONDecodeError as exc:
        raise ContractError(f"{label} is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} must contain an object")
    return value


def require_fields(value: dict[str, Any], allowed: set[str], required: set[str], label: str) -> None:
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise ContractError(f"{label} has unknown fields: {', '.join(sorted(unknown))}")
    if missing:
        raise ContractError(f"{label} is missing fields: {', '.join(sorted(missing))}")


def text(value: Any, label: str, *, minimum: int = 1, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{label} must be a string")
    candidate = value.strip()
    if not minimum <= len(candidate) <= maximum:
        raise ContractError(f"{label} must contain {minimum} to {maximum} characters")
    if "\x00" in candidate:
        raise ContractError(f"{label} contains a null byte")
    return candidate


def repository(value: Any) -> str:
    candidate = text(value, "repo", maximum=200)
    if not REPOSITORY.fullmatch(candidate):
        raise ContractError("repo must use OWNER/REPO syntax")
    owner, name = candidate.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."} or owner.startswith("-") or name.startswith("-"):
        raise ContractError("repo must use a safe OWNER/REPO value")
    return candidate


def git_ref(value: Any, label: str = "baseRef") -> str:
    candidate = text(value, label, maximum=200)
    forbidden = ("..", "@{", "\\", " ", "~", "^", ":", "?", "*", "[", "//")
    if (
        candidate.startswith(("/", ".", "-"))
        or candidate.endswith(("/", ".", ".lock"))
        or any(part in candidate for part in forbidden)
        or any(ord(char) < 32 or ord(char) == 127 for char in candidate)
    ):
        raise ContractError(f"{label} is not a safe Git branch name")
    return candidate


def relative_directory(value: Any) -> str:
    candidate = text(value, "workingDirectory", maximum=512)
    path = PurePosixPath(candidate)
    if path.is_absolute() or ".." in path.parts or candidate.startswith("~"):
        raise ContractError("workingDirectory must stay inside the repository")
    return path.as_posix()


def command(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= 64:
        raise ContractError(f"{label} must be a non-empty argument array")
    result: list[str] = []
    for index, argument in enumerate(value):
        if not isinstance(argument, str) or len(argument) > 4096 or "\x00" in argument:
            raise ContractError(f"{label}[{index}] must be a string no longer than 4096 characters")
        if index == 0 and not argument:
            raise ContractError(f"{label}[0] must name an executable")
        result.append(argument)
    return tuple(result)


def command_list(value: Any, label: str) -> tuple[tuple[str, ...], ...]:
    if not isinstance(value, list) or len(value) > 32:
        raise ContractError(f"{label} must be an array with at most 32 commands")
    return tuple(command(item, f"{label}[{index}]") for index, item in enumerate(value))


@dataclass(frozen=True)
class PreviewConfig:
    command: tuple[str, ...]
    port: int

    def to_dict(self) -> dict[str, Any]:
        return {"command": list(self.command), "port": self.port}


@dataclass(frozen=True)
class WorkerConfig:
    contract_version: str
    base_ref: str
    working_directory: str
    setup: tuple[tuple[str, ...], ...]
    verify: tuple[tuple[str, ...], ...]
    preview: PreviewConfig | None

    @classmethod
    def parse(cls, raw: str) -> "WorkerConfig":
        value = load_json_object(raw, "worker.json")
        require_fields(
            value,
            {"contractVersion", "baseRef", "workingDirectory", "setup", "verify", "preview"},
            {"contractVersion", "baseRef", "setup", "verify"},
            "worker.json",
        )
        version = text(value["contractVersion"], "contractVersion", maximum=64)
        if version != "codexstack.worker.v1":
            raise ContractError("unsupported worker contractVersion")
        preview_value = value.get("preview")
        preview: PreviewConfig | None
        if preview_value is None:
            preview = None
        else:
            if not isinstance(preview_value, dict):
                raise ContractError("preview must be null or an object")
            require_fields(preview_value, {"command", "port"}, {"command", "port"}, "preview")
            port = preview_value["port"]
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535:
                raise ContractError("preview.port must be an integer from 1 to 65535")
            preview = PreviewConfig(command(preview_value["command"], "preview.command"), port)
        return cls(
            contract_version=version,
            base_ref=git_ref(value["baseRef"]),
            working_directory=relative_directory(value.get("workingDirectory", ".")),
            setup=command_list(value["setup"], "setup"),
            verify=command_list(value["verify"], "verify"),
            preview=preview,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contractVersion": self.contract_version,
            "baseRef": self.base_ref,
            "workingDirectory": self.working_directory,
            "setup": [list(item) for item in self.setup],
            "verify": [list(item) for item in self.verify],
            "preview": self.preview.to_dict() if self.preview else None,
        }

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StartRequest:
    repo: str
    goal: str
    base_ref: str | None
    model: str | None
    reasoning_effort: str | None
    ttl_seconds: int
    idempotency_key: str
    delivery: str

    @classmethod
    def parse(cls, value: Any, *, default_ttl: int) -> "StartRequest":
        if not isinstance(value, dict):
            raise ContractError("request must be an object")
        require_fields(
            value,
            {
                "repo",
                "goal",
                "baseRef",
                "model",
                "reasoningEffort",
                "ttlSeconds",
                "idempotencyKey",
                "delivery",
            },
            {"repo", "goal", "idempotencyKey"},
            "request",
        )
        goal = text(value["goal"], "goal", maximum=MAX_GOAL_BYTES)
        if len(goal.encode("utf-8")) > MAX_GOAL_BYTES:
            raise ContractError(f"goal exceeds {MAX_GOAL_BYTES} bytes")
        ttl = value.get("ttlSeconds", default_ttl)
        if isinstance(ttl, bool) or not isinstance(ttl, int) or not 60 <= ttl <= 2_592_000:
            raise ContractError("ttlSeconds must be an integer from 60 to 2592000")
        model_value = value.get("model")
        model = None if model_value is None or model_value == "" else text(model_value, "model", maximum=128)
        if model is not None and not MODEL.fullmatch(model):
            raise ContractError("model contains unsupported characters")
        effort_value = value.get("reasoningEffort")
        effort = (
            None
            if effort_value is None or effort_value == ""
            else text(effort_value, "reasoningEffort", maximum=32)
        )
        if effort is not None and not EFFORT.fullmatch(effort):
            raise ContractError("reasoningEffort contains unsupported characters")
        delivery = value.get("delivery", "open_pull_request")
        if delivery not in DELIVERY_MODES:
            raise ContractError("delivery must be read_only, local_change, or open_pull_request")
        base_value = value.get("baseRef")
        return cls(
            repo=repository(value["repo"]),
            goal=goal,
            base_ref=None if base_value is None or base_value == "" else git_ref(base_value),
            model=model,
            reasoning_effort=effort,
            ttl_seconds=ttl,
            idempotency_key=text(value["idempotencyKey"], "idempotencyKey", minimum=8, maximum=255),
            delivery=delivery,
        )


def stable_run_id(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:20]
    return f"run_{digest}"


def key_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def slug(value: str, *, limit: int = 28) -> str:
    candidate = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (candidate[:limit].rstrip("-") or "task")


def run_title(goal: str) -> str:
    first = next((line.strip() for line in goal.splitlines() if line.strip()), "Agent run")
    return first[:96]


def branch_name(run_id: str, goal: str) -> str:
    if not RUN_ID.fullmatch(run_id):
        raise ContractError("invalid run id")
    return f"codexstack/{run_id[4:16]}-{slug(goal)}"


def ensure_sha(value: Any, label: str) -> str:
    candidate = text(value, label, minimum=40, maximum=40).lower()
    if not SHA.fullmatch(candidate):
        raise ContractError(f"{label} must be a full lowercase Git SHA")
    return candidate


def ensure_box_id(value: Any) -> str:
    candidate = text(value, "boxId", maximum=128)
    if not BOX_ID.fullmatch(candidate):
        raise ContractError("invalid Box id")
    return candidate


def ensure_prompt_id(value: Any) -> str:
    candidate = text(value, "promptId", maximum=255)
    if not PROMPT_ID.fullmatch(candidate):
        raise ContractError("invalid prompt id")
    return candidate


def command_display(command_value: Iterable[str]) -> str:
    return " ".join(command_value)
