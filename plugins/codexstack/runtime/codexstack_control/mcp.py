from __future__ import annotations

import copy
import json
import math
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TextIO
from urllib.parse import urlsplit

from .controller import ControlError, RunController


PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "codexstack-control"
SERVER_VERSION = "0.3.0"
MAX_REQUEST_BYTES = 1_048_576
MAX_CONTENT_BYTES = 262_144
MAX_OUTPUT_STRING = 32_768

SERVER_INSTRUCTIONS = (
    "CodexStack controls paid Box workers. Start, message, interrupt, desktop, stop, resume, "
    "and handoff operations require explicit user authority. CodexStack never merges or deletes. "
    "Read a run immediately before mutating it and use the current prompt ID for concurrency "
    "checks. run_message queues behind the current managed prompt. To redirect active work, call "
    "run_interrupt explicitly before sending replacement direction."
)

_RUN_ID = r"^run_[0-9a-f]{20}$"
_PROMPT_ID = r"^[A-Za-z0-9_.:-]{1,255}$"
_REPOSITORY = r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
_MODEL = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
_EFFORT = r"^[a-z][a-z0-9_-]{0,31}$"


def _object_schema(
    properties: dict[str, dict[str, Any]], required: tuple[str, ...] = ()
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return schema


def _annotations(
    *,
    read_only: bool,
    destructive: bool = False,
    idempotent: bool = False,
    open_world: bool = False,
) -> dict[str, bool]:
    return {
        "readOnlyHint": read_only,
        "destructiveHint": destructive,
        "idempotentHint": idempotent,
        "openWorldHint": open_world,
    }


TOOL_METADATA: tuple[dict[str, Any], ...] = (
    {
        "name": "run_start",
        "title": "Start Box run",
        "description": (
            "Create one paid Box worker and one isolated branch after explicit user authority. "
            "Capacity is an admission limit, not a queue. The controller never merges or deletes."
        ),
        "inputSchema": _object_schema(
            {
                "repo": {
                    "type": "string",
                    "pattern": _REPOSITORY,
                    "minLength": 3,
                    "maxLength": 200,
                    "description": "Allowed repository in OWNER/REPO form.",
                },
                "goal": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 32_768,
                    "description": "Bounded worker goal. This cannot expand merge or deletion authority.",
                },
                "baseRef": {
                    "type": ["string", "null"],
                    "minLength": 1,
                    "maxLength": 200,
                    "description": "Optional base branch. It must match worker.json when supplied.",
                },
                "model": {
                    "type": ["string", "null"],
                    "pattern": _MODEL,
                    "minLength": 1,
                    "maxLength": 128,
                },
                "reasoningEffort": {
                    "type": ["string", "null"],
                    "pattern": _EFFORT,
                    "minLength": 1,
                    "maxLength": 32,
                },
                "ttlSeconds": {
                    "type": "integer",
                    "minimum": 60,
                    "maximum": 2_592_000,
                    "description": "Finite Box lifetime in seconds.",
                },
                "idempotencyKey": {
                    "type": "string",
                    "minLength": 8,
                    "maxLength": 255,
                    "description": "Stable key for safe start retries.",
                },
                "delivery": {
                    "type": "string",
                    "enum": ["read_only", "local_change", "open_pull_request"],
                    "description": "Maximum delivery action. No mode permits merge or deletion.",
                },
            },
            ("repo", "goal", "idempotencyKey", "delivery"),
        ),
        "annotations": _annotations(
            read_only=False, destructive=False, idempotent=True, open_world=True
        ),
    },
    {
        "name": "run_list",
        "title": "List runs",
        "description": "List bounded run records and refresh unreleased Box lifecycle state without mutating a worker.",
        "inputSchema": _object_schema(
            {
                "limit": {"type": "integer", "minimum": 1, "maximum": 1_000, "default": 100},
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 10_000_000,
                    "default": 0,
                },
            }
        ),
        "annotations": _annotations(read_only=True, idempotent=True, open_world=True),
    },
    {
        "name": "run_read",
        "title": "Read run",
        "description": (
            "Read one run. Refreshing may observe current Box state but does not mutate the worker. "
            "Read immediately before any steering or lifecycle action."
        ),
        "inputSchema": _object_schema(
            {
                "runId": {"type": "string", "pattern": _RUN_ID, "maxLength": 24},
                "refresh": {"type": "boolean", "default": True},
            },
            ("runId",),
        ),
        "annotations": _annotations(read_only=True, idempotent=True, open_world=True),
    },
    {
        "name": "run_wait",
        "title": "Wait for run activity",
        "description": (
            "Long-poll one run for Box events or a terminal state for at most 45 seconds. "
            "This observes managed work and does not create a patrol or queue."
        ),
        "inputSchema": _object_schema(
            {
                "runId": {"type": "string", "pattern": _RUN_ID, "maxLength": 24},
                "cursor": {
                    "type": ["string", "null"],
                    "maxLength": 4_096,
                    "description": "Opaque cursor returned by the previous wait.",
                },
                "waitSeconds": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 45,
                    "default": 0,
                },
            },
            ("runId",),
        ),
        "annotations": _annotations(read_only=True, idempotent=True, open_world=True),
    },
    {
        "name": "run_message",
        "title": "Queue follow-up message",
        "description": (
            "Queue bounded follow-up direction behind the current managed prompt on a paid Box "
            "worker. Read first and supply its exact prompt ID. Use run_interrupt before redirecting "
            "active work."
        ),
        "inputSchema": _object_schema(
            {
                "runId": {"type": "string", "pattern": _RUN_ID, "maxLength": 24},
                "message": {"type": "string", "minLength": 1, "maxLength": 32_768},
                "expectedPromptId": {
                    "type": "string",
                    "pattern": _PROMPT_ID,
                    "minLength": 1,
                    "maxLength": 255,
                },
                "idempotencyKey": {"type": "string", "minLength": 8, "maxLength": 255},
            },
            ("runId", "message", "expectedPromptId", "idempotencyKey"),
        ),
        "annotations": _annotations(
            read_only=False, destructive=False, idempotent=True, open_world=True
        ),
    },
    {
        "name": "run_interrupt",
        "title": "Interrupt active run",
        "description": (
            "Interrupt the active managed Box turn after explicit user authority. This is destructive "
            "to in-flight work. Read first and supply the exact current prompt ID."
        ),
        "inputSchema": _object_schema(
            {
                "runId": {"type": "string", "pattern": _RUN_ID, "maxLength": 24},
                "expectedPromptId": {
                    "type": "string",
                    "pattern": _PROMPT_ID,
                    "minLength": 1,
                    "maxLength": 255,
                },
            },
            ("runId", "expectedPromptId"),
        ),
        "annotations": _annotations(
            read_only=False, destructive=True, idempotent=False, open_world=True
        ),
    },
    {
        "name": "run_desktop",
        "title": "Open run desktop",
        "description": (
            "Return the local control UI route for desktop access after explicit user authority. "
            "The tool never mints, stores, or returns a signed Box desktop or preview URL."
        ),
        "inputSchema": _object_schema(
            {"runId": {"type": "string", "pattern": _RUN_ID, "maxLength": 24}},
            ("runId",),
        ),
        "annotations": _annotations(
            read_only=False, destructive=False, idempotent=True, open_world=False
        ),
    },
    {
        "name": "run_stop",
        "title": "Stop run worker",
        "description": (
            "Stop and snapshot the paid Box worker after explicit user authority. This is a "
            "destructive lifecycle action, but it does not permanently delete the Box."
        ),
        "inputSchema": _object_schema(
            {"runId": {"type": "string", "pattern": _RUN_ID, "maxLength": 24}},
            ("runId",),
        ),
        "annotations": _annotations(
            read_only=False, destructive=True, idempotent=False, open_world=True
        ),
    },
    {
        "name": "run_resume",
        "title": "Resume run worker",
        "description": (
            "Resume a stopped paid Box worker for a finite lifetime after explicit user authority. "
            "Read the run before resuming it."
        ),
        "inputSchema": _object_schema(
            {
                "runId": {"type": "string", "pattern": _RUN_ID, "maxLength": 24},
                "ttlSeconds": {"type": "integer", "minimum": 60, "maximum": 2_592_000},
            },
            ("runId", "ttlSeconds"),
        ),
        "annotations": _annotations(
            read_only=False, destructive=False, idempotent=False, open_world=True
        ),
    },
    {
        "name": "run_handoff",
        "title": "Verify run handoff",
        "description": (
            "Run exact handoff verification against Box, Git, and any declared pull request after "
            "explicit user authority. Verification can execute repository-declared commands. It "
            "never merges, closes, retargets, force-pushes, or deletes."
        ),
        "inputSchema": _object_schema(
            {"runId": {"type": "string", "pattern": _RUN_ID, "maxLength": 24}},
            ("runId",),
        ),
        "annotations": _annotations(
            read_only=False, destructive=False, idempotent=True, open_world=True
        ),
    },
)

TOOL_BY_NAME = {tool["name"]: tool for tool in TOOL_METADATA}
METHOD_METADATA: dict[str, dict[str, Any]] = {
    "initialize": {"notification": False},
    "ping": {"notification": False},
    "notifications/initialized": {"notification": True},
    "tools/list": {"notification": False},
    "tools/call": {"notification": False},
}
METHODS = frozenset(METHOD_METADATA)

_NO_RESPONSE = object()
_URL = re.compile(r"https?://[^\s<>\"'{}\[\]()]+", re.IGNORECASE)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(box_api_key|gh_token|github_token|oauth[_-]?token|authorization|"
    r"access[_-]?token|refresh[_-]?token|bearer[_-]?token|token|cookie|password|"
    r"secret|private[_-]?key)\s*(?::|=|\bis\b)\s*([^\s,;]+)"
)
_TOKEN_VALUE = re.compile(
    r"(?i)\b(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|"
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b"
)
_BEARER_VALUE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_SENSITIVE_KEY_FRAGMENTS = (
    "authorization",
    "password",
    "secret",
    "accesstoken",
    "refreshtoken",
    "bearertoken",
    "apikey",
    "token",
    "oauth",
    "credential",
    "privatekey",
    "sshkey",
    "cookie",
    "desktopurl",
    "previewurl",
    "signedurl",
)


class _RPCError(ValueError):
    def __init__(self, code: int, message: str, detail: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


class _ToolInputError(ValueError):
    pass


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _RPCError(-32602, "Invalid params", f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise _RPCError(-32602, "Invalid params", f"{label} keys must be strings")
    return value


def _strict_fields(
    value: dict[str, Any],
    *,
    allowed: set[str],
    required: set[str] = frozenset(),
    label: str,
) -> None:
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise _RPCError(
            -32602,
            "Invalid params",
            f"{label} has unknown fields: {', '.join(sorted(unknown))}",
        )
    if missing:
        raise _RPCError(
            -32602,
            "Invalid params",
            f"{label} is missing fields: {', '.join(sorted(missing))}",
        )


def _bounded_string(value: Any, label: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum or "\x00" in value:
        raise _RPCError(
            -32602,
            "Invalid params",
            f"{label} must be a string containing {minimum} to {maximum} characters",
        )
    return value


def _validate_meta(value: dict[str, Any]) -> None:
    if "_meta" in value and not isinstance(value["_meta"], dict):
        raise _RPCError(-32602, "Invalid params", "_meta must be an object")


def _safe_url(url: str, public_url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return "[redacted-url]"
    hostname = (parsed.hostname or "").lower()
    query = parsed.query.lower()
    path = parsed.path.lower()
    sensitive_query = any(
        marker in query
        for marker in (
            "token=",
            "sig=",
            "signature=",
            "expires=",
            "x-amz-",
            "authorization=",
            "session=",
        )
    )
    if sensitive_query:
        return "[redacted-url]"
    if url == public_url or url.startswith(f"{public_url}/"):
        return url
    if parsed.scheme == "https" and hostname == "github.com" and not parsed.query and not parsed.fragment:
        return url
    return "[redacted-url]"


def _safe_string(value: str, public_url: str) -> str:
    bounded = value.replace("\x00", "")[:MAX_OUTPUT_STRING]
    bounded = _BEARER_VALUE.sub("[redacted-token]", bounded)
    bounded = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[redacted]", bounded)
    bounded = _TOKEN_VALUE.sub("[redacted-token]", bounded)
    return _URL.sub(lambda match: _safe_url(match.group(0), public_url), bounded)


def _sensitive_key(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", value.lower())
    return any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS)


def _safe_output(value: Any, public_url: str, depth: int = 0) -> Any:
    if depth > 8:
        return "[truncated]"
    if isinstance(value, str):
        return _safe_string(value, public_url)
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (list, tuple)):
        return [_safe_output(item, public_url, depth + 1) for item in value[:200]]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key, item in list(value.items())[:200]:
            key = str(raw_key)[:128]
            result[key] = (
                "[redacted]"
                if _sensitive_key(key)
                else _safe_output(item, public_url, depth + 1)
            )
        return result
    return _safe_string(str(value), public_url)


def _json_text(value: dict[str, Any]) -> str:
    rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(rendered.encode("utf-8")) <= MAX_CONTENT_BYTES:
        return rendered
    return json.dumps(
        {
            "truncated": True,
            "message": "Structured result exceeds the bounded text representation",
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _tool_result(value: dict[str, Any], public_url: str) -> dict[str, Any]:
    safe = _safe_output(value, public_url)
    if not isinstance(safe, dict):
        safe = {"value": safe}
    return {
        "content": [{"type": "text", "text": _json_text(safe)}],
        "structuredContent": safe,
    }


def _tool_error(code: str, message: str, status: int, public_url: str) -> dict[str, Any]:
    safe_message = _safe_string(message, public_url)
    structured = {"error": {"code": code[:128], "message": safe_message, "status": status}}
    result = _tool_result(structured, public_url)
    result["isError"] = True
    return result


def _property_type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    return False


def _validate_property(name: str, value: Any, schema: dict[str, Any]) -> None:
    raw_types = schema.get("type")
    expected_types = [raw_types] if isinstance(raw_types, str) else raw_types
    if not isinstance(expected_types, list) or not all(
        isinstance(item, str) for item in expected_types
    ):
        raise RuntimeError(f"invalid internal schema for {name}")
    if not any(_property_type_matches(value, item) for item in expected_types):
        raise _ToolInputError(f"{name} has the wrong type")
    if value is None:
        return
    if isinstance(value, str):
        if "\x00" in value:
            raise _ToolInputError(f"{name} contains a null byte")
        minimum = schema.get("minLength", 0)
        maximum = schema.get("maxLength")
        if len(value) < minimum or (isinstance(maximum, int) and len(value) > maximum):
            upper = maximum if isinstance(maximum, int) else "the configured limit"
            raise _ToolInputError(f"{name} must contain {minimum} to {upper} characters")
        if "enum" in schema and value not in schema["enum"]:
            raise _ToolInputError(f"{name} is not an allowed value")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.fullmatch(pattern, value) is None:
            raise _ToolInputError(f"{name} has an invalid format")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise _ToolInputError(f"{name} must be finite")
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            raise _ToolInputError(f"{name} must be at least {minimum}")
        if maximum is not None and value > maximum:
            raise _ToolInputError(f"{name} must be at most {maximum}")


def _validate_tool_arguments(tool: dict[str, Any], value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _ToolInputError("arguments must be an object")
    if any(not isinstance(key, str) for key in value):
        raise _ToolInputError("argument names must be strings")
    schema = tool["inputSchema"]
    properties = schema["properties"]
    unknown = set(value) - set(properties)
    missing = set(schema.get("required", ())) - set(value)
    if unknown:
        raise _ToolInputError(f"unknown arguments: {', '.join(sorted(unknown))}")
    if missing:
        raise _ToolInputError(f"missing arguments: {', '.join(sorted(missing))}")
    for name, item in value.items():
        _validate_property(name, item, properties[name])
    return dict(value)


class MCPServer:
    """Small dependency-free MCP dispatcher shared by stdio and HTTP transports."""

    methods = METHODS
    method_metadata = METHOD_METADATA
    tools = TOOL_METADATA
    tool_metadata = TOOL_METADATA

    def __init__(self, controller: RunController, *, control_page_available: bool = False):
        self.controller = controller
        self.initialized = False
        self.control_page_available = control_page_available

    @property
    def public_url(self) -> str:
        return str(self.controller.config.public_url)

    def handle(self, request: Any) -> dict[str, Any] | None:
        """Handle one decoded JSON-RPC object and return a response or notification silence."""
        if not isinstance(request, dict):
            return self._error_response(None, -32600, "Invalid Request", "request must be an object")

        notification = (
            "id" not in request
            and request.get("jsonrpc") == "2.0"
            and isinstance(request.get("method"), str)
        )
        request_id: str | int | None = None
        try:
            unknown = set(request) - {"jsonrpc", "id", "method", "params"}
            if unknown:
                raise _RPCError(
                    -32600,
                    "Invalid Request",
                    f"request has unknown fields: {', '.join(sorted(str(item) for item in unknown))}",
                )
            if request.get("jsonrpc") != "2.0":
                raise _RPCError(-32600, "Invalid Request", "jsonrpc must be 2.0")
            method = request.get("method")
            if not isinstance(method, str) or not 1 <= len(method) <= 128 or "\x00" in method:
                raise _RPCError(-32600, "Invalid Request", "method must be a bounded string")
            if "id" in request:
                candidate = request["id"]
                if isinstance(candidate, bool) or not isinstance(candidate, (str, int)):
                    raise _RPCError(-32600, "Invalid Request", "id must be a string or integer")
                if isinstance(candidate, str) and len(candidate) > 255:
                    raise _RPCError(-32600, "Invalid Request", "string id is too long")
                request_id = candidate
            metadata = METHOD_METADATA.get(method)
            if notification and (metadata is None or metadata.get("notification") is not True):
                raise _RPCError(-32600, "Invalid Request", "method requires a request id")
            if not notification and metadata is not None and metadata.get("notification") is True:
                raise _RPCError(-32600, "Invalid Request", "notification method cannot have an id")
            params = request.get("params", {})
            if params is None:
                raise _RPCError(-32602, "Invalid params", "params must be an object")
            result = self._dispatch(method, params)
            if result is _NO_RESPONSE or notification:
                return None
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except _RPCError as exc:
            if notification:
                return None
            return self._error_response(request_id, exc.code, exc.message, exc.detail)

    def _dispatch(self, method: str, params_value: Any) -> dict[str, Any] | object:
        if method not in {"initialize", "ping"} and not self.initialized:
            raise _RPCError(-32002, "Server not initialized")
        if method == "initialize":
            params = _require_object(params_value, "initialize params")
            _strict_fields(
                params,
                allowed={"protocolVersion", "capabilities", "clientInfo", "_meta"},
                required={"protocolVersion", "capabilities", "clientInfo"},
                label="initialize params",
            )
            _validate_meta(params)
            _bounded_string(params["protocolVersion"], "protocolVersion", 1, 64)
            if not isinstance(params["capabilities"], dict):
                raise _RPCError(-32602, "Invalid params", "capabilities must be an object")
            client = _require_object(params["clientInfo"], "clientInfo")
            _strict_fields(
                client,
                allowed={"name", "title", "version"},
                required={"name", "version"},
                label="clientInfo",
            )
            _bounded_string(client["name"], "clientInfo.name", 1, 128)
            _bounded_string(client["version"], "clientInfo.version", 1, 128)
            if "title" in client:
                _bounded_string(client["title"], "clientInfo.title", 1, 256)
            self.initialized = True
            return {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": SERVER_NAME,
                    "title": "CodexStack Control",
                    "version": SERVER_VERSION,
                },
                "instructions": SERVER_INSTRUCTIONS,
            }

        if method == "ping":
            params = _require_object(params_value, "ping params")
            _strict_fields(params, allowed={"_meta"}, label="ping params")
            _validate_meta(params)
            return {}

        if method == "notifications/initialized":
            params = _require_object(params_value, "initialized params")
            _strict_fields(params, allowed={"_meta"}, label="initialized params")
            _validate_meta(params)
            self.initialized = True
            return _NO_RESPONSE

        if method == "tools/list":
            params = _require_object(params_value, "tools/list params")
            _strict_fields(params, allowed={"cursor", "_meta"}, label="tools/list params")
            _validate_meta(params)
            if "cursor" in params:
                _bounded_string(params["cursor"], "cursor", 0, 4_096)
            return {"tools": copy.deepcopy(list(self.tools))}

        if method == "tools/call":
            params = _require_object(params_value, "tools/call params")
            _strict_fields(
                params,
                allowed={"name", "arguments", "_meta"},
                required={"name"},
                label="tools/call params",
            )
            _validate_meta(params)
            name = _bounded_string(params["name"], "name", 1, 128)
            tool = TOOL_BY_NAME.get(name)
            if tool is None:
                raise _RPCError(-32602, "Invalid params", f"unknown tool: {name}")
            return self._call_tool(tool, params.get("arguments", {}))

        raise _RPCError(-32601, "Method not found", f"unsupported method: {method}")

    def _call_tool(self, tool: dict[str, Any], arguments_value: Any) -> dict[str, Any]:
        try:
            arguments = _validate_tool_arguments(tool, arguments_value)
            value = self._invoke_tool(tool["name"], arguments)
            if not isinstance(value, dict):
                value = {"value": value}
            return _tool_result(value, self.public_url)
        except ControlError as exc:
            return _tool_error(exc.code, str(exc), exc.status, self.public_url)
        except _ToolInputError as exc:
            return _tool_error("invalid_arguments", str(exc), 400, self.public_url)
        except ValueError as exc:
            return _tool_error("invalid_arguments", str(exc), 400, self.public_url)
        except Exception:
            return _tool_error(
                "internal_error",
                "The control operation failed without a safe diagnostic",
                500,
                self.public_url,
            )

    def _invoke_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "run_start":
            return self.controller.start(arguments)
        if name == "run_list":
            return {
                "runs": self.controller.list(
                    limit=arguments.get("limit", 100), offset=arguments.get("offset", 0)
                )
            }
        if name == "run_read":
            return self.controller.read(
                arguments["runId"], refresh=arguments.get("refresh", True)
            )
        if name == "run_wait":
            return self.controller.wait(
                arguments["runId"],
                cursor=arguments.get("cursor"),
                wait_seconds=arguments.get("waitSeconds", 0),
            )
        if name == "run_message":
            request = {key: value for key, value in arguments.items() if key != "runId"}
            return self.controller.message(arguments["runId"], request)
        if name == "run_interrupt":
            return self.controller.interrupt(
                arguments["runId"], expected_prompt_id=arguments["expectedPromptId"]
            )
        if name == "run_desktop":
            run_id = arguments["runId"]
            self.controller.read(run_id, refresh=False)
            return {
                "runId": run_id,
                "url": f"{self.controller.config.public_url}/runs/{run_id}?open=desktop",
                "uiRequired": not self.control_page_available,
                "detail": (
                    "Open the control page to mint browser-only desktop access"
                    if self.control_page_available
                    else "Start the optional web control service before opening this address"
                ),
            }
        if name == "run_stop":
            return self.controller.stop(arguments["runId"])
        if name == "run_resume":
            return self.controller.resume(
                arguments["runId"], ttl_seconds=arguments["ttlSeconds"]
            )
        if name == "run_handoff":
            return self.controller.handoff(arguments["runId"])
        raise RuntimeError("tool metadata and dispatch are inconsistent")

    @staticmethod
    def _error_response(
        request_id: str | int | None,
        code: int,
        message: str,
        detail: str | None = None,
    ) -> dict[str, Any]:
        error: dict[str, Any] = {"code": code, "message": message[:256]}
        if detail:
            error["data"] = {"detail": detail[:1_024]}
        return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON number: {value}")


def serve_stdio(controller: RunController, input: TextIO, output: TextIO) -> None:
    """Serve newline-delimited JSON-RPC until the input stream reaches EOF."""
    server = MCPServer(controller)
    write_lock = threading.Lock()

    def emit(response: dict[str, Any] | None) -> None:
        if response is None:
            return
        rendered = (
            json.dumps(
                response, ensure_ascii=True, separators=(",", ":"), sort_keys=True, allow_nan=False
            )
            + "\n"
        )
        with write_lock:
            output.write(rendered)
            output.flush()

    workers = min(32, max(4, controller.config.max_parallel + 2))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="codexstack-mcp") as executor:
        for raw_line in input:
            try:
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                if not isinstance(line, str):
                    raise ValueError("input line must be text")
                if not line.strip():
                    continue
                if len(line.encode("utf-8")) > MAX_REQUEST_BYTES:
                    raise ValueError("JSON-RPC line exceeds the request limit")
                request = json.loads(
                    line,
                    object_pairs_hook=_unique_object,
                    parse_constant=_reject_constant,
                )
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                emit(MCPServer._error_response(None, -32700, "Parse error"))
                continue
            if (
                isinstance(request, dict)
                and request.get("method") == "tools/call"
                and server.initialized
            ):
                executor.submit(lambda item=request: emit(server.handle(item)))
            else:
                emit(server.handle(request))


__all__ = [
    "METHODS",
    "METHOD_METADATA",
    "MCPServer",
    "PROTOCOL_VERSION",
    "SERVER_INSTRUCTIONS",
    "TOOL_METADATA",
    "serve_stdio",
]
