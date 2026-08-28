from __future__ import annotations

import json
import re
import shlex
import socket
from http.client import HTTPException
from ipaddress import ip_address
from pathlib import PurePosixPath
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .model import (
    EFFORT,
    MODEL,
    ContractError,
    command as validate_command,
    ensure_box_id,
    ensure_prompt_id,
    load_json_object,
    text,
)


DEFAULT_BASE_URL = "https://ascii.dev/api/box/v1"
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_HTTP_TIMEOUT_SECONDS = 620.0
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_PROMPT_BYTES = 256 * 1024
MAX_TTL_SECONDS = 2_592_000
MIN_TTL_SECONDS = 60
MAX_PROCESS_ID = 2_147_483_647
MAX_CURSOR_LENGTH = 4096
MAX_PATH_LENGTH = 4096
_SAFE_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        return None


_OPENER = build_opener(_RejectRedirects())


class BoxError(RuntimeError):
    """A transport, HTTP, or response-contract failure from Box."""

    status: int | None
    code: str
    request_id: str | None
    retryable: bool
    retryability: bool

    def __init__(
        self,
        message: str,
        *,
        status: int | None,
        code: str,
        request_id: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.request_id = request_id
        self.retryable = retryable
        self.retryability = retryable


class BoxClient:
    """Small standard-library client for the public Box v1 JSON API."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        self._api_key = _header_value(api_key, "api_key", minimum=1, maximum=4096)
        self._base_url = _base_url(base_url)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 0 < float(timeout) <= MAX_HTTP_TIMEOUT_SECONDS
        ):
            raise ContractError(
                f"timeout must be greater than 0 and at most {MAX_HTTP_TIMEOUT_SECONDS:g} seconds"
            )
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or not 1 <= max_response_bytes <= 64 * 1024 * 1024
        ):
            raise ContractError("max_response_bytes must be an integer from 1 to 67108864")
        self._timeout = float(timeout)
        self._max_response_bytes = max_response_bytes

    def limits(self) -> dict[str, Any]:
        result = self._request("GET", "/limits", retry_safe=True)
        self._expect_type(result, "limits.info")
        if not isinstance(result.get("canStart"), bool):
            raise self._contract_failure("limits")
        return result

    def create_box(
        self,
        snapshot: str,
        environment: str,
        ttl_seconds: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        snapshot_value = text(snapshot, "snapshot", maximum=255)
        environment_value = text(environment, "environment", maximum=255)
        ttl_value = _finite_ttl(ttl_seconds)
        key_value = _header_value(
            idempotency_key, "idempotency_key", minimum=8, maximum=255
        )
        result = self._request(
            "POST",
            "/boxes",
            body={
                "from": snapshot_value,
                "environment": environment_value,
                "ttlSeconds": ttl_value,
            },
            headers={"Idempotency-Key": key_value},
            retry_safe=True,
        )
        self._expect_type(result, "box.created")
        return result

    def get_box(self, box_id: str) -> dict[str, Any]:
        result = self._request("GET", _box_path(box_id), retry_safe=True)
        self._expect_type(result, "box.info")
        return result

    def read_file(self, box_id: str, path: str) -> dict[str, Any]:
        path_value = _box_file_path(path, "path")
        query = urlencode({"path": path_value})
        result = self._request(
            "GET", f"{_box_path(box_id)}/files?{query}", retry_safe=True
        )
        self._expect_type(result, "file.read")
        if (
            result.get("success") is not True
            or result.get("encoding") not in {"utf8", "base64"}
            or isinstance(result.get("size"), bool)
            or not isinstance(result.get("size"), int)
            or not isinstance(result.get("content"), str)
        ):
            raise self._contract_failure("file read")
        return result

    def command(
        self,
        box_id: str,
        argv: list[str],
        cwd: str | None,
        timeout_seconds: int,
        detached: bool,
    ) -> dict[str, Any]:
        command_value = shlex.join(validate_command(argv, "command"))
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not 1 <= timeout_seconds <= 600
        ):
            raise ContractError("timeout_seconds must be an integer from 1 to 600")
        if not isinstance(detached, bool):
            raise ContractError("detached must be a boolean")
        body: dict[str, Any] = {
            "command": command_value,
            "timeoutSeconds": timeout_seconds,
            "detached": detached,
        }
        if cwd is not None:
            body["cwd"] = _command_cwd(cwd)
        transport_timeout = self._timeout
        if not detached:
            transport_timeout = min(
                MAX_HTTP_TIMEOUT_SECONDS,
                max(self._timeout, float(timeout_seconds) + 15.0),
            )
        result = self._request(
            "POST",
            f"{_box_path(box_id)}/commands",
            body=body,
            retry_safe=False,
            timeout=transport_timeout,
        )
        if detached:
            self._expect_type(result, "command.started")
            process_id = result.get("processId")
            if (
                isinstance(process_id, bool)
                or not isinstance(process_id, int)
                or not 1 <= process_id <= MAX_PROCESS_ID
            ):
                raise self._contract_failure("detached command")
        else:
            self._expect_type(result, "command.finished")
            exit_code = result.get("exitCode")
            if (
                "exitCode" not in result
                or (exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int)))
                or not isinstance(result.get("success"), bool)
                or not isinstance(result.get("timedOut"), bool)
                or not isinstance(result.get("stdout"), str)
                or not isinstance(result.get("stderr"), str)
            ):
                raise self._contract_failure("synchronous command")
        return result

    def command_status(self, box_id: str, process_id: int) -> dict[str, Any]:
        process_value = _process_id(process_id)
        result = self._request(
            "GET",
            f"{_box_path(box_id)}/commands/{process_value}",
            retry_safe=True,
        )
        self._expect_type(result, "command.status")
        exit_code = result.get("exitCode")
        if (
            result.get("processId") != process_value
            or result.get("status") not in {"running", "exited", "lost"}
            or not isinstance(result.get("running"), bool)
            or "exitCode" not in result
            or (exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int)))
            or not isinstance(result.get("stdout"), str)
            or not isinstance(result.get("stderr"), str)
        ):
            raise self._contract_failure("command status")
        return result

    def prompt(
        self,
        box_id: str,
        prompt: str,
        model: str | None,
        reasoning_effort: str | None,
    ) -> dict[str, Any]:
        prompt_value = _prompt(prompt)
        body: dict[str, Any] = {"provider": "codex", "prompt": prompt_value}
        if model is not None:
            model_value = text(model, "model", maximum=128)
            if not MODEL.fullmatch(model_value):
                raise ContractError("model contains unsupported characters")
            body["model"] = model_value
        if reasoning_effort is not None:
            effort_value = text(reasoning_effort, "reasoning_effort", maximum=32)
            if not EFFORT.fullmatch(effort_value):
                raise ContractError("reasoning_effort contains unsupported characters")
            body["reasoningEffort"] = effort_value
        result = self._request(
            "POST",
            f"{_box_path(box_id)}/prompt",
            body=body,
            retry_safe=False,
        )
        self._expect_type(result, "prompt.queued")
        if result.get("status") != "queued" or not isinstance(result.get("promptRun"), dict):
            raise self._contract_failure("queued prompt")
        return result

    def prompt_status(self, box_id: str, prompt_id: str) -> dict[str, Any]:
        prompt_value = quote(ensure_prompt_id(prompt_id), safe="")
        result = self._request(
            "GET",
            f"{_box_path(box_id)}/prompts/{prompt_value}",
            retry_safe=True,
        )
        self._expect_type(result, "prompt.run")
        if not isinstance(result.get("promptRun"), dict):
            raise self._contract_failure("prompt status")
        return result

    def events(
        self, box_id: str, cursor: str | None, limit: int
    ) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ContractError("limit must be an integer from 1 to 200")
        parameters: list[tuple[str, str]] = [("limit", str(limit)), ("sort", "asc")]
        if cursor is not None:
            cursor_value = _opaque_value(cursor, "cursor", MAX_CURSOR_LENGTH)
            parameters.append(("cursor", cursor_value))
        result = self._request(
            "GET",
            f"{_box_path(box_id)}/events?{urlencode(parameters)}",
            retry_safe=True,
        )
        self._expect_type(result, "events.list")
        if not isinstance(result.get("events"), list) or not isinstance(result.get("pageInfo"), dict):
            raise self._contract_failure("events")
        return result

    def interrupt(self, box_id: str) -> dict[str, Any]:
        return self._request(
            "POST", f"{_box_path(box_id)}/interrupt", retry_safe=True
        )

    def stop(self, box_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"{_box_path(box_id)}/stop",
            body={"force": False},
            retry_safe=True,
        )

    def resume(self, box_id: str, ttl_seconds: int) -> dict[str, Any]:
        return self._request(
            "POST",
            f"{_box_path(box_id)}/resume",
            body={"ttlSeconds": _finite_ttl(ttl_seconds)},
            retry_safe=True,
        )

    def desktop(self, box_id: str, theme: str) -> dict[str, Any]:
        if theme not in {"light", "dark"}:
            raise ContractError("theme must be light or dark")
        query = urlencode({"theme": theme})
        return self._request(
            "POST",
            f"{_box_path(box_id)}/desktop?{query}",
            retry_safe=True,
        )

    def host(self, box_id: str, port: int, title: str | None) -> dict[str, Any]:
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535:
            raise ContractError("port must be an integer from 1 to 65535")
        body: dict[str, Any] = {"port": port, "public": False}
        if title is not None:
            body["title"] = text(title, "title", maximum=120)
        return self._request(
            "POST",
            f"{_box_path(box_id)}/host",
            body=body,
            retry_safe=True,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        retry_safe: bool,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        request_headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        if headers:
            request_headers.update(headers)
        data: bytes | None = None
        if body is not None:
            try:
                data = json.dumps(
                    body,
                    ensure_ascii=True,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise ContractError("request body is not JSON serializable") from exc
            if len(data) > MAX_REQUEST_BYTES:
                raise ContractError(f"request body exceeds {MAX_REQUEST_BYTES} bytes")
            request_headers["Content-Type"] = "application/json"
        request = Request(
            f"{self._base_url}{path}",
            data=data,
            headers=request_headers,
            method=method,
        )
        try:
            response = _OPENER.open(
                request, timeout=self._timeout if timeout is None else timeout
            )
            try:
                status = _response_status(response)
                raw = self._read_response(response, status=status, retry_safe=retry_safe)
                if not 200 <= status < 300:
                    raise self._http_error(
                        status=status,
                        raw=raw,
                        headers=getattr(response, "headers", None),
                        retry_safe=retry_safe,
                    )
                return self._success(
                    raw,
                    status=status,
                    headers=getattr(response, "headers", None),
                    retry_safe=retry_safe,
                )
            finally:
                response.close()
        except HTTPError as exc:
            try:
                try:
                    raw = self._read_response(exc, status=exc.code, retry_safe=retry_safe)
                except (TimeoutError, socket.timeout) as read_error:
                    raise BoxError(
                        "Box API request timed out while reading an HTTP error",
                        status=exc.code,
                        code="timeout",
                        retryable=retry_safe,
                    ) from read_error
                except (HTTPException, OSError) as read_error:
                    raise BoxError(
                        "Box API returned an unreadable HTTP error",
                        status=exc.code,
                        code="invalid_http_response",
                        retryable=_is_retryable(
                            exc.code, "invalid_http_response", retry_safe
                        ),
                    ) from read_error
                raise self._http_error(
                    status=exc.code,
                    raw=raw,
                    headers=exc.headers,
                    retry_safe=retry_safe,
                ) from None
            finally:
                exc.close()
        except (TimeoutError, socket.timeout) as exc:
            raise BoxError(
                "Box API request timed out",
                status=None,
                code="timeout",
                retryable=retry_safe,
            ) from exc

        except URLError as exc:
            code = (
                "timeout"
                if isinstance(getattr(exc, "reason", None), (TimeoutError, socket.timeout))
                else "network_error"
            )
            raise BoxError(
                (
                    "Box API request timed out"
                    if code == "timeout"
                    else "Box API request failed before a response was received"
                ),
                status=None,
                code=code,
                retryable=retry_safe,
            ) from exc
        except HTTPException as exc:
            raise BoxError(
                "Box API returned an invalid HTTP response",
                status=None,
                code="invalid_http_response",
                retryable=retry_safe,
            ) from exc
        except OSError as exc:
            raise BoxError(
                "Box API request failed before a response was received",
                status=None,
                code="network_error",
                retryable=retry_safe,
            ) from exc

    @staticmethod
    def _expect_type(value: Mapping[str, Any], expected: str) -> None:
        if value.get("type") != expected:
            raise BoxClient._contract_failure(expected)

    @staticmethod
    def _contract_failure(operation: str) -> BoxError:
        return BoxError(
            f"Box API returned an invalid {operation} response",
            status=200,
            code="invalid_json_response",
            retryable=False,
        )

    def _read_response(
        self, response: Any, *, status: int, retry_safe: bool
    ) -> bytes:
        raw = response.read(self._max_response_bytes + 1)
        if not isinstance(raw, bytes):
            raise BoxError(
                "Box API returned a non-byte response",
                status=status,
                code="invalid_json_response",
                retryable=_is_retryable(status, "invalid_json_response", retry_safe),
            )
        if len(raw) > self._max_response_bytes:
            raise BoxError(
                "Box API response exceeded the configured size limit",
                status=status,
                code="response_too_large",
                retryable=_is_retryable(status, "response_too_large", retry_safe),
            )
        return raw

    def _success(
        self, raw: bytes, *, status: int, headers: Any, retry_safe: bool
    ) -> dict[str, Any]:
        value = self._json_object(raw, status=status, retry_safe=retry_safe)
        if value.get("ok") is not True or not _response_type(value.get("type")):
            if value.get("ok") is False:
                raise self._error_from_envelope(
                    value, status=status, headers=headers, retry_safe=retry_safe
                )
            raise BoxError(
                "Box API returned an invalid success envelope",
                status=status,
                code="invalid_json_response",
                retryable=_is_retryable(status, "invalid_json_response", retry_safe),
            )
        return value

    def _json_object(
        self, raw: bytes, *, status: int, retry_safe: bool
    ) -> dict[str, Any]:
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BoxError(
                "Box API returned non-UTF-8 JSON",
                status=status,
                code="invalid_json_response",
                retryable=_is_retryable(status, "invalid_json_response", retry_safe),
            ) from exc
        try:
            return load_json_object(
                decoded, "Box API response", max_bytes=self._max_response_bytes
            )
        except ContractError as exc:
            raise BoxError(
                "Box API returned invalid JSON",
                status=status,
                code="invalid_json_response",
                retryable=_is_retryable(status, "invalid_json_response", retry_safe),
            ) from exc

    def _http_error(
        self,
        *,
        status: int,
        raw: bytes,
        headers: Any,
        retry_safe: bool,
    ) -> BoxError:
        try:
            value = self._json_object(raw, status=status, retry_safe=retry_safe)
        except BoxError:
            request_id = _request_id_from_headers(headers)
            return BoxError(
                "Box API returned an HTTP error with an invalid JSON envelope",
                status=status,
                code="http_error",
                request_id=request_id,
                retryable=_is_retryable(status, "http_error", retry_safe),
            )
        return self._error_from_envelope(
            value, status=status, headers=headers, retry_safe=retry_safe
        )

    @staticmethod
    def _error_from_envelope(
        value: Mapping[str, Any],
        *,
        status: int,
        headers: Any,
        retry_safe: bool,
    ) -> BoxError:
        nested = value.get("error")
        nested_value = nested if isinstance(nested, dict) else {}
        code = _error_code(value.get("code")) or _error_code(nested_value.get("code"))
        if code is None:
            code = "http_error"
        request_id = _request_id(value.get("requestId")) or _request_id_from_headers(headers)
        return BoxError(
            f"Box API request failed with {code}",
            status=status,
            code=code,
            request_id=request_id,
            retryable=_is_retryable(status, code, retry_safe),
        )


def _base_url(value: str) -> str:
    candidate = text(value, "base_url", maximum=2048).rstrip("/")
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        parsed.port
    except ValueError as exc:
        raise ContractError("base_url is not a valid HTTP URL") from exc
    if (
        any(ord(character) < 32 or ord(character) == 127 for character in candidate)
        or parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or hostname is None
        or any(character.isspace() for character in hostname)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ContractError("base_url must be an HTTP URL without credentials, query, or fragment")
    if parsed.scheme == "http" and not _loopback_host(hostname):
        raise ContractError("base_url may use HTTP only for a loopback host")
    return candidate


def _loopback_host(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def _header_value(value: Any, label: str, *, minimum: int, maximum: int) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise ContractError(f"{label} must contain {minimum} to {maximum} characters")
    if any(ord(character) < 33 or ord(character) > 126 for character in value):
        raise ContractError(f"{label} must contain visible ASCII characters only")
    return value


def _finite_ttl(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not MIN_TTL_SECONDS <= value <= MAX_TTL_SECONDS
    ):
        raise ContractError(
            f"ttl_seconds must be an integer from {MIN_TTL_SECONDS} to {MAX_TTL_SECONDS}"
        )
    return value


def _box_path(box_id: Any) -> str:
    return f"/boxes/{quote(ensure_box_id(box_id), safe='')}"


def _process_id(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= MAX_PROCESS_ID
    ):
        raise ContractError(f"process_id must be an integer from 1 to {MAX_PROCESS_ID}")
    return value


def _opaque_value(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise ContractError(f"{label} must contain 1 to {maximum} characters")
    if "\x00" in value:
        raise ContractError(f"{label} contains a null byte")
    return value


def _box_file_path(value: Any, label: str) -> str:
    candidate = _opaque_value(value, label, MAX_PATH_LENGTH)
    path = PurePosixPath(candidate)
    if ".." in path.parts or candidate.startswith("~"):
        raise ContractError(f"{label} must stay under /home/user or /tmp")
    if path.is_absolute() and not _allowed_absolute_path(path):
        raise ContractError(f"{label} must stay under /home/user or /tmp")
    return candidate


def _command_cwd(value: Any) -> str:
    candidate = _box_file_path(value, "cwd")
    path = PurePosixPath(candidate)
    if not path.is_absolute() and candidate.startswith("~"):
        raise ContractError("cwd must stay inside the Box work directory")
    return candidate


def _allowed_absolute_path(path: PurePosixPath) -> bool:
    parts = path.parts
    return parts[:3] == ("/", "home", "user") or parts[:2] == ("/", "tmp")


def _prompt(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("prompt must be a non-empty string")
    if "\x00" in value:
        raise ContractError("prompt contains a null byte")
    if len(value.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise ContractError(f"prompt exceeds {MAX_PROMPT_BYTES} bytes")
    return value


def _response_status(response: Any) -> int:
    status = getattr(response, "status", None)
    if status is None:
        status = response.getcode()
    if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
        raise BoxError(
            "Box API returned an invalid HTTP status",
            status=None,
            code="invalid_http_response",
            retryable=False,
        )
    return status


def _response_type(value: Any) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 128 and "\x00" not in value


def _error_code(value: Any) -> str | None:
    if isinstance(value, str) and _SAFE_CODE.fullmatch(value):
        return value
    return None


def _request_id(value: Any) -> str | None:
    if (
        isinstance(value, str)
        and 1 <= len(value) <= 255
        and all(32 <= ord(character) <= 126 for character in value)
    ):
        return value
    return None


def _request_id_from_headers(headers: Any) -> str | None:
    if headers is None or not hasattr(headers, "get"):
        return None
    return _request_id(headers.get("X-Request-Id") or headers.get("X-Ascii-Request-Id"))


def _is_retryable(status: int, code: str, retry_safe: bool) -> bool:
    if not retry_safe:
        return False
    return (
        status in {408, 425, 429}
        or status >= 500
        or code in {"idempotency_in_progress", "box_starting"}
    )
