from __future__ import annotations

import hmac
import ipaddress
import json
import math
import re
import secrets
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from .controller import ControlError, RunController
from .mcp import MCPServer, PROTOCOL_VERSION
from .model import ContractError, load_json_object


MAX_JSON_BYTES = 65_536
MAX_QUERY_BYTES = 8_192
_CSRF_TOKEN = secrets.token_urlsafe(32)
_RUN_ID = r"run_[0-9a-f]{20}"
_RUN_API = re.compile(
    rf"^/api/runs/(?P<run_id>{_RUN_ID})(?:/(?P<action>events|messages|interrupt|desktop|preview|stop|resume|handoff))?$"
)
_RUN_PAGE = re.compile(rf"^/runs/{_RUN_ID}/?$")
_DNS_NAME = re.compile(
    r"^(?=.{1,253}\.?$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.?$"
)
_STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/styles.css": ("styles.css", "text/css; charset=utf-8"),
}
_STATIC_ROOT = Path(__file__).with_name("static")


def _constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def _normalized_host(value: str) -> str:
    candidate = value.rstrip(".").lower()
    try:
        return ipaddress.ip_address(candidate).compressed
    except ValueError:
        if not _DNS_NAME.fullmatch(value):
            raise ControlError("invalid Host header", code="invalid_host", status=400)
        return candidate


def _authority(value: str) -> tuple[str, int | None]:
    if not value or any(ord(char) < 33 or ord(char) == 127 for char in value):
        raise ControlError("invalid Host header", code="invalid_host", status=400)
    try:
        parsed = urlsplit(f"//{value}")
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ControlError("invalid Host header", code="invalid_host", status=400) from exc
    if (
        hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ControlError("invalid Host header", code="invalid_host", status=400)
    return _normalized_host(hostname), port


def _request_fields(
    value: dict[str, Any],
    *,
    allowed: set[str],
    required: set[str] = frozenset(),
) -> None:
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown or missing:
        raise ControlError("request fields are invalid", code="invalid_request", status=400)


class _ControlHandler(BaseHTTPRequestHandler):
    controller: RunController
    mcp_server: MCPServer
    csrf_token: str

    server_version = "CodexStack"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def version_string(self) -> str:
        return self.server_version

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        try:
            phrase = HTTPStatus(code).phrase
        except ValueError:
            code = 500
            phrase = "Internal Server Error"
        self._send_json(
            code,
            {"error": {"code": "http_error", "message": phrase}},
            head=self.command == "HEAD",
            close=True,
        )

    def do_GET(self) -> None:
        self._guard(self._get)

    def do_HEAD(self) -> None:
        self._guard(self._head)

    def do_POST(self) -> None:
        self._guard(self._post)

    def do_OPTIONS(self) -> None:
        self._guard(self._unsupported_method)

    def do_PUT(self) -> None:
        self._guard(self._unsupported_method)

    def do_PATCH(self) -> None:
        self._guard(self._unsupported_method)

    def do_DELETE(self) -> None:
        self._guard(self._unsupported_method)

    def do_TRACE(self) -> None:
        self._guard(self._unsupported_method)

    def do_CONNECT(self) -> None:
        self._guard(self._unsupported_method)

    def _guard(self, operation: Callable[[], None]) -> None:
        try:
            self._reject_unexpected_body()
            self._validate_host()
            self._validate_origin()
            self._validate_mcp_protocol_version()
            operation()
        except ControlError as exc:
            self._control_error(exc)
        except ContractError as exc:
            self._control_error(
                ControlError(str(exc), code="invalid_request", status=400)
            )
        except (BrokenPipeError, ConnectionError):
            self.close_connection = True
        except Exception:
            self._control_error(
                ControlError("internal server error", code="internal_error", status=500)
            )

    def _reject_unexpected_body(self) -> None:
        if self.command == "POST":
            return
        transfer_encoding = self.headers.get_all("Transfer-Encoding", failobj=[])
        lengths = self.headers.get_all("Content-Length", failobj=[])
        valid_empty_length = len(lengths) == 1 and lengths[0].strip() == "0"
        if transfer_encoding or (lengths and not valid_empty_length):
            self.close_connection = True
            raise ControlError(
                "request bodies are not allowed for this method",
                code="invalid_request",
                status=400,
            )

    def _target(self) -> tuple[str, str]:
        parsed = urlsplit(self.path)
        if parsed.scheme or parsed.netloc or parsed.fragment:
            raise ControlError("invalid request target", code="invalid_target", status=400)
        if len(parsed.query.encode("utf-8")) > MAX_QUERY_BYTES:
            raise ControlError("query string is too large", code="invalid_query", status=414)
        return parsed.path, parsed.query

    def _get(self) -> None:
        path, query = self._target()
        if self._is_protected(path):
            self._authorize()
        if path == "/mcp":
            self._empty_query(query)
            self._method_not_allowed("POST")
            return
        if path == "/api/config":
            self._empty_query(query)
            self._send_json(
                200,
                {
                    "maxParallel": self.controller.config.max_parallel,
                    "activeRuns": self.controller.store.count_active(),
                    "csrfToken": self.csrf_token,
                    "boxConfigured": bool(self.controller.config.box_api_key),
                },
            )
            return
        if path == "/api/runs":
            values = self._query(query, {"limit", "offset"})
            limit = self._query_integer(values, "limit", default=100, minimum=1, maximum=1_000)
            offset = self._query_integer(values, "offset", default=0, minimum=0)
            runs = self.controller.list(limit=limit, offset=offset)
            self._send_json(
                200,
                {"runs": runs, "activeRuns": self.controller.store.count_active()},
            )
            return
        match = _RUN_API.fullmatch(path)
        if match is not None:
            run_id = match.group("run_id")
            action = match.group("action")
            if action is None:
                self._empty_query(query)
                self._send_json(200, {"run": self.controller.read(run_id)})
                return
            if action == "events":
                values = self._query(query, {"cursor", "waitSeconds"})
                cursor = values.get("cursor") or None
                if cursor is not None and (len(cursor) > 4_096 or "\x00" in cursor):
                    raise ControlError("cursor is invalid", code="invalid_cursor", status=400)
                wait_seconds = self._query_float(
                    values, "waitSeconds", default=0.0, minimum=0.0, maximum=45.0
                )
                result = self.controller.wait(
                    run_id, cursor=cursor, wait_seconds=wait_seconds
                )
                self._send_json(
                    200,
                    {
                        "run": result["run"],
                        "events": result["events"],
                        "nextCursor": result.get("nextCursor"),
                    },
                )
                return
            self._empty_query(query)
            self._method_not_allowed("POST")
            return
        if path.startswith("/api/") or path == "/api":
            raise ControlError("endpoint not found", code="not_found", status=404)
        self._serve_static(path, query=query, head=False)

    def _head(self) -> None:
        path, query = self._target()
        if self._is_protected(path):
            self._authorize()
            if path == "/mcp":
                self._method_not_allowed("POST")
            else:
                self._method_not_allowed("GET", "POST")
            return
        self._serve_static(path, query=query, head=True)

    def _post(self) -> None:
        path, query = self._target()
        if self._is_protected(path):
            self._authorize()
        if path == "/mcp":
            self._empty_query(query)
            request = self._json_body()
            response = self.mcp_server.handle(request)
            if response is None:
                self._send_empty(202)
            else:
                self._send_json(200, response)
            return
        if not (path.startswith("/api/") or path == "/api"):
            self._method_not_allowed("GET", "HEAD")
            return
        self._csrf()
        self._empty_query(query)
        if path == "/api/runs":
            self._send_json(200, {"run": self.controller.start(self._json_body())})
            return
        match = _RUN_API.fullmatch(path)
        if match is None:
            raise ControlError("endpoint not found", code="not_found", status=404)
        run_id = match.group("run_id")
        action = match.group("action")
        if action is None or action == "events":
            self._method_not_allowed("GET")
            return
        body = self._json_body()
        if action == "messages":
            run = self.controller.message(run_id, body)
        elif action == "interrupt":
            _request_fields(
                body,
                allowed={"expectedPromptId", "idempotencyKey"},
                required={"expectedPromptId"},
            )
            run = self.controller.interrupt(
                run_id, expected_prompt_id=body["expectedPromptId"]
            )
        elif action == "desktop":
            _request_fields(body, allowed={"theme"})
            url = self.controller.desktop_url(run_id, theme=body.get("theme", "dark"))
            self._send_json(200, {"url": url})
            return
        elif action == "preview":
            _request_fields(body, allowed=set())
            url = self.controller.preview_url(run_id)
            self._send_json(200, {"url": url})
            return
        elif action == "stop":
            _request_fields(body, allowed={"idempotencyKey"})
            run = self.controller.stop(run_id)
        elif action == "resume":
            _request_fields(
                body,
                allowed={"ttlSeconds", "idempotencyKey"},
                required={"ttlSeconds"},
            )
            run = self.controller.resume(run_id, ttl_seconds=body["ttlSeconds"])
        else:
            _request_fields(body, allowed={"idempotencyKey"})
            run = self.controller.handoff(run_id)
        self._send_json(200, {"run": run})

    def _unsupported_method(self) -> None:
        path, _ = self._target()
        if self._is_protected(path):
            self._authorize()
            if path.startswith("/api/") or path == "/api":
                self._csrf()
        if path == "/mcp":
            self._method_not_allowed("POST")
        elif path.startswith("/api/") or path == "/api":
            self._method_not_allowed("GET", "POST")
        else:
            self._method_not_allowed("GET", "HEAD")

    def _serve_static(self, path: str, *, query: str, head: bool) -> None:
        item = _STATIC.get(path)
        if item is None and _RUN_PAGE.fullmatch(path):
            item = _STATIC["/"]
        if item is None:
            raise ControlError("resource not found", code="not_found", status=404)
        filename, content_type = item
        root = _STATIC_ROOT.resolve()
        candidate = (_STATIC_ROOT / filename).resolve()
        if candidate.parent != root:
            raise ControlError("resource not found", code="not_found", status=404)
        try:
            content = candidate.read_bytes()
        except OSError as exc:
            raise ControlError("resource not found", code="not_found", status=404) from exc
        self._send_bytes(200, content, content_type, head=head)

    def _json_body(self) -> dict[str, Any]:
        transfer_encoding = self.headers.get_all("Transfer-Encoding", failobj=[])
        if transfer_encoding:
            self.close_connection = True
            raise ControlError(
                "transfer encoding is not supported", code="invalid_request", status=400
            )
        content_types = self.headers.get_all("Content-Type", failobj=[])
        if len(content_types) != 1:
            self.close_connection = True
            raise ControlError("Content-Type must be application/json", code="invalid_content_type", status=415)
        media_type = content_types[0].split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            self.close_connection = True
            raise ControlError("Content-Type must be application/json", code="invalid_content_type", status=415)
        lengths = self.headers.get_all("Content-Length", failobj=[])
        if len(lengths) != 1:
            self.close_connection = True
            raise ControlError("Content-Length is required", code="invalid_length", status=411)
        try:
            length = int(lengths[0], 10)
        except ValueError as exc:
            self.close_connection = True
            raise ControlError("Content-Length is invalid", code="invalid_length", status=400) from exc
        if length < 0:
            self.close_connection = True
            raise ControlError("Content-Length is invalid", code="invalid_length", status=400)
        if length > MAX_JSON_BYTES:
            self.close_connection = True
            raise ControlError("request JSON exceeds 65536 bytes", code="request_too_large", status=413)
        raw = self.rfile.read(length)
        if len(raw) != length:
            self.close_connection = True
            raise ControlError("request body ended early", code="invalid_request", status=400)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ControlError("request JSON must be UTF-8", code="invalid_json", status=400) from exc
        try:
            return load_json_object(text, "request JSON", max_bytes=MAX_JSON_BYTES)
        except ContractError as exc:
            raise ControlError(str(exc), code="invalid_json", status=400) from exc

    def _query(self, query: str, allowed: set[str]) -> dict[str, str]:
        if not query:
            return {}
        try:
            parsed = parse_qs(
                query,
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=max(1, len(allowed) + 1),
            )
        except ValueError as exc:
            raise ControlError("query string is invalid", code="invalid_query", status=400) from exc
        if set(parsed) - allowed or any(len(values) != 1 for values in parsed.values()):
            raise ControlError("query string is invalid", code="invalid_query", status=400)
        return {key: values[0] for key, values in parsed.items()}

    def _empty_query(self, query: str) -> None:
        if query:
            raise ControlError("query string is not allowed", code="invalid_query", status=400)

    def _query_integer(
        self,
        values: dict[str, str],
        name: str,
        *,
        default: int,
        minimum: int,
        maximum: int | None = None,
    ) -> int:
        raw = values.get(name)
        if raw is None:
            return default
        try:
            value = int(raw, 10)
        except ValueError as exc:
            raise ControlError(f"{name} is invalid", code="invalid_query", status=400) from exc
        if value < minimum or (maximum is not None and value > maximum):
            raise ControlError(f"{name} is invalid", code="invalid_query", status=400)
        return value

    def _query_float(
        self,
        values: dict[str, str],
        name: str,
        *,
        default: float,
        minimum: float,
        maximum: float,
    ) -> float:
        raw = values.get(name)
        if raw is None:
            return default
        try:
            value = float(raw)
        except ValueError as exc:
            raise ControlError(f"{name} is invalid", code="invalid_query", status=400) from exc
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise ControlError(f"{name} is invalid", code="invalid_query", status=400)
        return value

    def _validate_host(self) -> None:
        values = self.headers.get_all("Host", failobj=[])
        if len(values) != 1:
            raise ControlError("Host header is required", code="invalid_host", status=400)
        request_host, request_port = _authority(values[0])
        public = urlsplit(self.controller.config.public_origin or "")
        if public.hostname is not None:
            public_host = _normalized_host(public.hostname)
            public_port = public.port or (443 if public.scheme == "https" else 80)
            request_public_port = request_port if request_port is not None else public_port
            if request_host == public_host and request_public_port == public_port:
                return
        expected_port = self.server.server_address[1]
        if (request_port if request_port is not None else 80) != expected_port:
            raise ControlError("invalid Host header", code="invalid_host", status=400)
        configured = _normalized_host(self.controller.config.host)
        if configured not in {"0.0.0.0", "::"}:
            loopback_config = configured == "localhost"
            try:
                loopback_config = loopback_config or ipaddress.ip_address(configured).is_loopback
            except ValueError:
                pass
            if loopback_config:
                request_is_loopback = request_host == "localhost"
                try:
                    request_is_loopback = request_is_loopback or ipaddress.ip_address(request_host).is_loopback
                except ValueError:
                    pass
                if not request_is_loopback:
                    raise ControlError("invalid Host header", code="invalid_host", status=400)
            elif request_host != configured:
                raise ControlError("invalid Host header", code="invalid_host", status=400)

    def _validate_origin(self) -> None:
        values = self.headers.get_all("Origin", failobj=[])
        if not values:
            return
        if len(values) != 1:
            raise ControlError("Origin is not allowed", code="origin_forbidden", status=403)
        try:
            origin = urlsplit(values[0])
        except ValueError as exc:
            raise ControlError(
                "Origin is not allowed", code="origin_forbidden", status=403
            ) from exc
        if (
            origin.scheme not in {"http", "https"}
            or not origin.netloc
            or origin.username is not None
            or origin.password is not None
            or origin.path
            or origin.query
            or origin.fragment
        ):
            raise ControlError("Origin is not allowed", code="origin_forbidden", status=403)

        try:
            origin_host = _normalized_host(origin.hostname or "")
            origin_port = origin.port if origin.port is not None else (443 if origin.scheme == "https" else 80)
            request_host, request_port = _authority(self.headers["Host"])
        except (ControlError, ValueError) as exc:
            raise ControlError("Origin is not allowed", code="origin_forbidden", status=403) from exc
        public = urlsplit(self.controller.config.public_origin or "")
        if public.hostname is not None:
            public_host = _normalized_host(public.hostname)
            public_port = public.port or (443 if public.scheme == "https" else 80)
            request_public_port = request_port if request_port is not None else public_port
            if (
                origin.scheme == public.scheme
                and origin_host == public_host
                and origin_port == public_port
                and request_host == public_host
                and request_public_port == public_port
            ):
                return
        if (
            origin.scheme != "http"
            or origin_host != request_host
            or origin_port != (request_port if request_port is not None else 80)
        ):
            raise ControlError("Origin is not allowed", code="origin_forbidden", status=403)

    def _validate_mcp_protocol_version(self) -> None:
        if urlsplit(self.path).path != "/mcp":
            return
        values = self.headers.get_all("MCP-Protocol-Version", failobj=[])
        if not values:
            return
        if len(values) != 1 or values[0] != PROTOCOL_VERSION:
            raise ControlError(
                "unsupported MCP protocol version",
                code="unsupported_protocol_version",
                status=400,
            )

    def _is_protected(self, path: str) -> bool:
        return path == "/mcp" or path == "/api" or path.startswith("/api/")

    def _authorize(self) -> None:
        expected = self.controller.config.token
        if expected is None:
            return
        values = self.headers.get_all("Authorization", failobj=[])
        if len(values) != 1:
            raise ControlError("authorization required", code="unauthorized", status=401)
        scheme, separator, token = values[0].partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not _constant_time_equal(token, expected):
            raise ControlError("authorization required", code="unauthorized", status=401)

    def _csrf(self) -> None:
        values = self.headers.get_all("X-CodexStack-CSRF", failobj=[])
        if len(values) != 1 or not _constant_time_equal(values[0], self.csrf_token):
            raise ControlError("CSRF token is invalid", code="csrf_forbidden", status=403)

    def _control_error(self, error: ControlError) -> None:
        status = error.status if 400 <= error.status <= 599 else 500
        code = error.code if status == error.status else "internal_error"
        message = str(error) if status == error.status else "internal server error"
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
        self._send_json(
            status,
            {"error": {"code": code, "message": message}},
            head=self.command == "HEAD",
            extra_headers=headers,
            close=self.close_connection or self.command not in {"GET", "HEAD"},
        )

    def _method_not_allowed(self, *methods: str) -> None:
        self._send_json(
            405,
            {"error": {"code": "method_not_allowed", "message": "method not allowed"}},
            head=self.command == "HEAD",
            extra_headers={"Allow": ", ".join(methods)},
            close=self.command not in {"GET", "HEAD"},
        )

    def _send_json(
        self,
        status: int,
        value: Any,
        *,
        head: bool = False,
        extra_headers: dict[str, str] | None = None,
        close: bool = False,
    ) -> None:
        try:
            body = json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ControlError("response could not be encoded", code="internal_error", status=500) from exc
        self._send_bytes(
            status,
            body,
            "application/json; charset=utf-8",
            head=head,
            extra_headers=extra_headers,
            close=close,
        )

    def _send_empty(self, status: int) -> None:
        self._send_bytes(status, b"", "application/json; charset=utf-8")

    def _send_bytes(
        self,
        status: int,
        body: bytes,
        content_type: str,
        *,
        head: bool = False,
        extra_headers: dict[str, str] | None = None,
        close: bool = False,
    ) -> None:
        if close:
            self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'none'; connect-src 'self'; form-action 'self'; "
            "frame-ancestors 'none'; frame-src https:; img-src 'self' data:; object-src 'none'; "
            "script-src 'self'; style-src 'self'",
        )
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), geolocation=(), microphone=(), payment=(), usb=()")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        if close:
            self.send_header("Connection", "close")
        if extra_headers:
            for name, value in extra_headers.items():
                self.send_header(name, value)
        self.end_headers()
        if not head and body:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionError):
                self.close_connection = True


class _IPv6ThreadingHTTPServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def create_server(controller: RunController) -> ThreadingHTTPServer:
    class Handler(_ControlHandler):
        pass

    Handler.controller = controller
    Handler.mcp_server = MCPServer(controller, control_page_available=True)
    Handler.csrf_token = _CSRF_TOKEN
    server_class: type[ThreadingHTTPServer]
    try:
        server_class = (
            _IPv6ThreadingHTTPServer
            if ipaddress.ip_address(controller.config.host).version == 6
            else ThreadingHTTPServer
        )
    except ValueError:
        server_class = ThreadingHTTPServer
    return server_class((controller.config.host, controller.config.port), Handler)


def serve(controller: RunController) -> None:
    server = create_server(controller)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
