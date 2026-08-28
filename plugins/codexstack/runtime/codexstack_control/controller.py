from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlencode, urlparse

from .box_client import BoxClient, BoxError
from .model import (
    ContractError,
    StartRequest,
    WorkerConfig,
    branch_name,
    ensure_box_id,
    ensure_prompt_id,
    ensure_sha,
    git_ref,
    key_hash,
    load_json_object,
    now_rfc3339,
    stable_run_id,
    text,
)
from .store import CapacityError, RunStore, StoreConflict, StoreError


TERMINAL_STATUSES = frozenset({"needs_input", "review", "done", "failed", "stopped"})
READY_BOX_STATES = frozenset({"ready", "idle", "running"})
RELEASED_BOX_STATES = frozenset({"archived", "deleted", "stopped"})
ANSI = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
SIMPLE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
START_STALE_SECONDS = 900


class ControlError(RuntimeError):
    def __init__(self, message: str, *, code: str = "control_error", status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def _protected_preview_url(value: Any, port: int) -> str:
    if not isinstance(value, str) or len(value) > 32_768 or "\x00" in value:
        raise ControlError(
            "Box did not return a protected preview", code="preview_failed", status=502
        )
    expected_suffix = f"-{port}.on.ascii.dev"
    try:
        parsed = urlparse(value)
        query = parse_qs(parsed.query, keep_blank_values=True)
        token = query.get("_token")
        valid = (
            parsed.scheme == "https"
            and parsed.username is None
            and parsed.password is None
            and parsed.port is None
            and (parsed.hostname or "").endswith(expected_suffix)
            and parsed.path in {"", "/"}
            and not parsed.fragment
            and isinstance(token, list)
            and len(token) == 1
            and bool(token[0])
        )
    except ValueError:
        valid = False
    if valid:
        return value
    raise ControlError(
        "Box did not return a protected preview", code="preview_failed", status=502
    )


def _serialized_start(method: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    @wraps(method)
    def guarded(self: "RunController", value: Any) -> dict[str, Any]:
        request = StartRequest.parse(value, default_ttl=self.config.default_ttl)
        with self._run_guard(stable_run_id(request.idempotency_key)):
            return method(self, value)

    return guarded


def _serialized_run(method: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(method)
    def guarded(self: "RunController", run_id: str, *args: Any, **kwargs: Any) -> Any:
        with self._run_guard(run_id):
            return method(self, run_id, *args, **kwargs)

    return guarded


def _assert_normal_git_index(value: str) -> None:
    """Reject index flags that can hide tracked worktree changes from Git's clean checks."""
    entries = value.split("\0")
    if entries[-1] != "" or any(
        len(entry) < 3 or entry[0] != "H" or entry[1] != " " for entry in entries[:-1]
    ):
        raise ControlError(
            "repository uses tracked index flags that can hide worktree changes",
            code="git_index_untrusted",
        )


@dataclass(frozen=True)
class ControlConfig:
    box_api_key: str | None
    box_environment: str
    box_template: str
    allowed_repos: frozenset[str]
    database: Path
    max_parallel: int = 4
    default_ttl: int = 43_200
    max_ttl: int = 2_592_000
    host: str = "127.0.0.1"
    port: int = 8_765
    token: str | None = None
    box_api_base: str = "https://ascii.dev/api/box/v1"
    inside_worker: bool = False
    public_origin: str | None = None

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> "ControlConfig":
        values = os.environ if environ is None else environ

        def integer(name: str, default: int, minimum: int, maximum: int) -> int:
            raw = values.get(name, str(default))
            try:
                value = int(raw)
            except ValueError as exc:
                raise ControlError(f"{name} must be an integer", code="invalid_config") from exc
            if not minimum <= value <= maximum:
                raise ControlError(
                    f"{name} must be from {minimum} to {maximum}", code="invalid_config"
                )
            return value

        environment = values.get("CODEXSTACK_BOX_ENVIRONMENT", "codexstack")
        template = values.get("CODEXSTACK_BOX_TEMPLATE", "codexstack-base")
        if not SIMPLE_NAME.fullmatch(environment) or not SIMPLE_NAME.fullmatch(template):
            raise ControlError("Box environment and template must be simple names", code="invalid_config")
        allowed = frozenset(
            item.strip() for item in values.get("CODEXSTACK_ALLOWED_REPOS", "").split(",") if item.strip()
        )
        from .model import repository

        for item in allowed:
            repository(item)
        host = values.get("CODEXSTACK_CONTROL_HOST", "127.0.0.1")
        port = integer("CODEXSTACK_CONTROL_PORT", 8_765, 1, 65_535)
        token = values.get("CODEXSTACK_CONTROL_TOKEN") or None
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ControlError("the built-in control service must bind to loopback", code="invalid_config")
        public_origin = _public_origin(values.get("CODEXSTACK_PUBLIC_URL"))
        if public_origin is not None and not token:
            raise ControlError("public control service requires a token", code="invalid_config")
        database = Path(
            values.get("CODEXSTACK_CONTROL_DB", str(Path.home() / ".codexstack" / "control.sqlite3"))
        ).expanduser()
        return cls(
            box_api_key=values.get("BOX_API_KEY") or None,
            box_environment=environment,
            box_template=template,
            allowed_repos=allowed,
            database=database,
            max_parallel=integer("CODEXSTACK_MAX_PARALLEL", 4, 1, 1_000),
            default_ttl=integer("CODEXSTACK_DEFAULT_TTL_SECONDS", 43_200, 60, 2_592_000),
            max_ttl=integer("CODEXSTACK_MAX_TTL", 2_592_000, 60, 2_592_000),
            host=host,
            port=port,
            token=token,
            box_api_base=values.get("CODEXSTACK_BOX_BASE_URL", "https://ascii.dev/api/box/v1").rstrip("/"),
            inside_worker=bool(values.get("BOX_ID")),
            public_origin=public_origin,
        )

    @property
    def public_url(self) -> str:
        if self.public_origin is not None:
            return self.public_origin
        display_host = "127.0.0.1" if self.host in {"0.0.0.0", "::"} else self.host
        return f"http://{display_host}:{self.port}"


def _public_origin(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    candidate = value.strip()
    try:
        parsed = urlparse(candidate)
        port = parsed.port
    except ValueError as exc:
        raise ControlError("CODEXSTACK_PUBLIC_URL is invalid", code="invalid_config") from exc
    hostname = parsed.hostname
    if (
        parsed.scheme not in {"http", "https"}
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.params
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ControlError("CODEXSTACK_PUBLIC_URL must be an HTTP origin", code="invalid_config")
    try:
        ascii_host = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ControlError("CODEXSTACK_PUBLIC_URL has an invalid host", code="invalid_config") from exc
    if not re.fullmatch(
        r"(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
        r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?",
        ascii_host,
    ):
        try:
            ascii_host = ipaddress.ip_address(ascii_host).compressed
        except ValueError as exc:
            raise ControlError("CODEXSTACK_PUBLIC_URL has an invalid host", code="invalid_config") from exc
    if parsed.scheme == "http":
        loopback = ascii_host == "localhost"
        try:
            loopback = loopback or ipaddress.ip_address(ascii_host).is_loopback
        except ValueError:
            pass
        if not loopback:
            raise ControlError("public control URL must use HTTPS", code="invalid_config")
    host_text = f"[{ascii_host}]" if ":" in ascii_host else ascii_host
    default_port = 443 if parsed.scheme == "https" else 80
    port_text = "" if port is None or port == default_port else f":{port}"
    return f"{parsed.scheme}://{host_text}{port_text}"


class RunController:
    def __init__(
        self,
        config: ControlConfig,
        *,
        store: RunStore | None = None,
        box: BoxClient | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        github_lookup: Callable[[str, int], dict[str, Any]] | None = None,
        github_list: Callable[[str, str, str], list[dict[str, Any]]] | None = None,
    ):
        self.config = config
        self.store = store or RunStore(config.database)
        self.box = box
        self._sleep = sleeper
        self._clock = clock
        self._github_lookup = github_lookup or self._github_pull_via_cli
        self._github_list = github_list or self._github_pulls_via_cli
        self._run_locks: dict[str, threading.RLock] = {}
        self._run_locks_guard = threading.Lock()

    @contextmanager
    def _run_guard(self, run_id: str) -> Any:
        with self._run_locks_guard:
            lock = self._run_locks.setdefault(run_id, threading.RLock())
        with lock:
            yield

    def _box(self) -> BoxClient:
        if self.config.inside_worker:
            raise ControlError(
                "fleet controls are disabled inside a worker Box", code="worker_boundary", status=403
            )
        if self.box is None:
            if not self.config.box_api_key:
                raise ControlError("BOX_API_KEY is required", code="missing_box_key", status=503)
            self.box = BoxClient(self.config.box_api_key, base_url=self.config.box_api_base)
        return self.box

    def _allowed(self, repo: str) -> None:
        if not self.config.allowed_repos:
            raise ControlError(
                "CODEXSTACK_ALLOWED_REPOS must explicitly allow worker repositories",
                code="repo_not_allowed",
                status=403,
            )
        if repo not in self.config.allowed_repos:
            raise ControlError(f"repository {repo} is not allowed", code="repo_not_allowed", status=403)

    @staticmethod
    def _request_hash(request: StartRequest) -> str:
        body = {
            "repo": request.repo,
            "goal": request.goal,
            "baseRef": request.base_ref,
            "model": request.model,
            "reasoningEffort": request.reasoning_effort,
            "ttlSeconds": request.ttl_seconds,
            "delivery": request.delivery,
        }
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @_serialized_start
    def start(self, value: Any) -> dict[str, Any]:
        request = StartRequest.parse(value, default_ttl=self.config.default_ttl)
        self._allowed(request.repo)
        if request.ttl_seconds > self.config.max_ttl:
            raise ControlError("ttlSeconds exceeds the controller maximum", code="invalid_ttl")
        client = self._box()
        run_id = stable_run_id(request.idempotency_key)
        existing = self.store.get(run_id)
        request_hash = self._request_hash(request)
        retry_box_create = False
        if existing is not None:
            if existing["requestHash"] != request_hash:
                raise ControlError("idempotency key was reused for another request", code="idempotency_conflict", status=409)
            if existing.get("boxId"):
                if existing["status"] == "starting" and self._start_is_stale(existing):
                    return self.store.update(
                        run_id,
                        status="needs_input",
                        statusDetail=(
                            "Start stopped after Box creation without a durable prompt receipt. No command "
                            "or prompt was replayed; inspect the Box before continuing"
                        ),
                        lastError="incomplete_start",
                    )
                return existing
            if existing["status"] == "stopped":
                return existing
            try:
                self.store.reserve(run_id, max_parallel=self.config.max_parallel)
            except CapacityError as exc:
                raise ControlError(str(exc), code="local_capacity", status=409) from exc
            self.store.update(
                run_id,
                title=f"{request.repo.rsplit('/', 1)[1]} agent {run_id[-6:]}",
                baseRef=request.base_ref,
                branch=existing.get("branch") or branch_name(run_id, request.repo.rsplit("/", 1)[1]),
                model=request.model,
                reasoningEffort=request.reasoning_effort,
                ttlSeconds=request.ttl_seconds,
                delivery=request.delivery,
                status="starting",
                statusDetail="Reconciling idempotent Box creation",
                startAttemptAt=now_rfc3339(),
                lastError=None,
            )
            retry_box_create = True
        if not retry_box_create:
            limits = client.limits()
            if limits.get("canStart") is False:
                raise ControlError("Box account capacity does not allow another worker", code="box_capacity", status=409)
            repo_name = request.repo.rsplit("/", 1)[1]
            branch = branch_name(run_id, repo_name)
            initial = {
                "id": run_id,
                "requestHash": request_hash,
                "title": f"{repo_name} agent {run_id[-6:]}",
                "repo": request.repo,
                "baseRef": request.base_ref,
                "branch": branch,
                "model": request.model,
                "reasoningEffort": request.reasoning_effort,
                "ttlSeconds": request.ttl_seconds,
                "delivery": request.delivery,
                "status": "starting",
                "statusDetail": "Reserving a Box worker",
                "createdAt": now_rfc3339(),
                "startAttemptAt": now_rfc3339(),
                "updatedAt": now_rfc3339(),
            }
            try:
                _, created = self.store.create(initial, max_parallel=self.config.max_parallel)
            except CapacityError as exc:
                raise ControlError(str(exc), code="local_capacity", status=409) from exc
            except StoreConflict as exc:
                raise ControlError(str(exc), code="idempotency_conflict", status=409) from exc
            if not created:
                record = self.store.get(run_id)
                if record is None:
                    raise ControlError("idempotent run disappeared", code="store_error", status=500)
                return record
        branch = self._record(run_id).get("branch")
        if not isinstance(branch, str) or not branch:
            raise ControlError("run branch is unavailable", code="store_error", status=500)
        try:
            created_box = client.create_box(
                snapshot=self.config.box_template,
                environment=self.config.box_environment,
                ttl_seconds=request.ttl_seconds,
                idempotency_key=request.idempotency_key,
            )
            box_id = self._extract_id(created_box, "Box")
            self.store.update(
                run_id,
                boxId=box_id,
                boxState=self._box_state(created_box),
                statusDetail="Waiting for the Box repository",
            )
            self._wait_ready(run_id, box_id)
            repo_dir = request.repo.rsplit("/", 1)[1]
            base_ref = request.base_ref
            if base_ref is None:
                file_result = client.read_file(box_id, f"{repo_dir}/.codexstack/worker.json")
                raw_config = file_result.get("content")
                if not isinstance(raw_config, str):
                    raise ControlError("Box did not return worker.json content", code="worker_contract")
                bootstrap = load_json_object(raw_config, "bootstrap worker.json")
                if "baseRef" not in bootstrap:
                    raise ControlError("bootstrap worker.json is missing baseRef", code="worker_contract")
                base_ref = git_ref(bootstrap["baseRef"])
            repo_cwd = repo_dir
            origin = self._command(box_id, ["git", "remote", "get-url", "origin"], cwd=repo_cwd)
            if self._github_repo(origin.get("stdout", "")) != request.repo.lower():
                raise ControlError("Box repository origin does not match the requested repository", code="repo_mismatch")
            self.store.update(run_id, statusDetail="Fetching the exact base revision")
            self._command(box_id, ["git", "fetch", "--no-tags", "origin", base_ref], cwd=repo_cwd)
            resolved = self._command(
                box_id, ["git", "rev-parse", f"origin/{base_ref}^{{commit}}"], cwd=repo_cwd
            )
            base_sha = ensure_sha(resolved.get("stdout", "").strip(), "baseSha")
            exact_config = self._command(
                box_id,
                ["git", "show", f"{base_sha}:.codexstack/worker.json"],
                cwd=repo_cwd,
            )
            worker = WorkerConfig.parse(exact_config.get("stdout", ""))
            if worker.base_ref != base_ref:
                raise ControlError("exact worker.json changed its own baseRef", code="worker_contract")
            if request.delivery == "open_pull_request" and not worker.verify:
                raise ControlError("open_pull_request requires at least one verify command", code="worker_contract")
            self.store.update(
                run_id,
                baseRef=worker.base_ref,
                baseSha=base_sha,
                headSha=base_sha,
                workerConfig=worker.to_dict(),
                workerConfigHash=worker.sha256(),
                previewPort=worker.preview.port if worker.preview else None,
                statusDetail="Creating the isolated branch",
            )
            remote_branch = self._command(
                box_id,
                ["git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}"],
                cwd=repo_cwd,
            )
            if remote_branch.get("stdout", "").strip():
                raise ControlError("derived remote branch already exists", code="branch_collision", status=409)
            local_branch = self._command(
                box_id,
                ["git", "show-ref", "--verify", f"refs/heads/{branch}"],
                cwd=repo_cwd,
                allowed=(0, 1),
            )
            if local_branch.get("exitCode") == 0:
                raise ControlError("derived local branch already exists", code="branch_collision", status=409)
            self._command(box_id, ["git", "switch", "--create", branch, base_sha], cwd=repo_cwd)
            setup_receipts = self._run_manifest_commands(
                box_id,
                worker.setup,
                cwd=self._working_cwd(repo_cwd, worker.working_directory),
                run_id=run_id,
                receipt_field="setupReceipts",
                detail="Running deterministic setup",
            )
            setup_branch = self._command(
                box_id, ["git", "branch", "--show-current"], cwd=repo_cwd
            )
            if setup_branch.get("stdout", "").strip() != branch:
                raise ControlError("setup changed the isolated branch", code="setup_identity")
            setup_head = self._command(box_id, ["git", "rev-parse", "HEAD"], cwd=repo_cwd)
            if ensure_sha(setup_head.get("stdout", "").strip(), "headSha") != base_sha:
                raise ControlError("setup changed the exact base commit", code="setup_identity")
            clean = self._command(box_id, ["git", "status", "--porcelain"], cwd=repo_cwd)
            if clean.get("stdout", "").strip():
                raise ControlError(
                    "setup changed the repository; commit deterministic setup separately",
                    code="setup_dirty",
                )
            rendered = self._command(
                box_id,
                ["codex", "debug", "prompt-input", "probe"],
                cwd=repo_cwd,
            )
            prompt_input = rendered.get("stdout", "")
            if not all(
                marker in prompt_input
                for marker in ("codexstack:work", "codexstack.work.v0.3.0")
            ):
                raise ControlError(
                    "Box Codex session cannot discover the required CodexStack contract",
                    code="codexstack_unavailable",
                )
            self._command(box_id, ["codex", "login", "status"], cwd=repo_cwd)
            if request.delivery == "open_pull_request":
                self._command(box_id, ["gh", "auth", "status"], cwd=repo_cwd)
            self.store.update(run_id, setupReceipts=setup_receipts, statusDetail="Starting Codex")
            queued = client.prompt(
                box_id,
                prompt=self._delivery_prompt(request, worker, run_id, branch, base_sha),
                model=request.model,
                reasoning_effort=request.reasoning_effort,
            )
            prompt_id = self._prompt_id(queued)
            return self.store.update(
                run_id,
                promptId=prompt_id,
                promptStatus="queued",
                status="working",
                statusDetail="Codex is working in the Box",
            )
        except (BoxError, ContractError, ControlError, StoreError) as exc:
            code = exc.code if isinstance(exc, (BoxError, ControlError)) else "start_failed"
            message = str(exc)
            try:
                current = self.store.get(run_id)
                failure_status = "needs_input" if current and current.get("boxId") else "failed"
                self.store.update(
                    run_id,
                    status=failure_status,
                    statusDetail=message,
                    lastError=code,
                    slotReleased=not bool(current and current.get("boxId")),
                )
            except StoreError:
                pass
            if isinstance(exc, ControlError):
                raise
            raise ControlError(message, code=code, status=502 if isinstance(exc, BoxError) else 400) from exc

    def list(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        records = self.store.list(limit=limit, offset=offset)
        refreshed: list[dict[str, Any]] = []
        for record in records:
            record = self._reconcile_stale_start(record)
            if record.get("boxId") and not record.get("slotReleased"):
                try:
                    record = self._refresh(record)
                except (BoxError, ControlError, StoreError):
                    record = self._record(record["id"])
            refreshed.append(record)
        return refreshed

    def read(self, run_id: str, *, refresh: bool = True) -> dict[str, Any]:
        record = self._reconcile_stale_start(self._record(run_id))
        if refresh and record.get("boxId") and not record.get("slotReleased"):
            try:
                record = self._refresh(record)
            except (BoxError, ControlError):
                record = self._record(run_id)
        return record

    def wait(
        self, run_id: str, *, cursor: str | None = None, wait_seconds: float = 0
    ) -> dict[str, Any]:
        if wait_seconds < 0 or wait_seconds > 45:
            raise ControlError("waitSeconds must be from 0 to 45", code="invalid_wait")
        start = self._clock()
        while True:
            record = self.read(run_id, refresh=True)
            events, next_cursor = self._events(record, cursor)
            terminal = record["status"] in TERMINAL_STATUSES
            if events or terminal or self._clock() - start >= wait_seconds:
                return {
                    "run": record,
                    "status": record["status"],
                    "events": events,
                    "nextCursor": next_cursor,
                    "terminal": terminal,
                }
            self._sleep(min(0.75, max(0.0, wait_seconds - (self._clock() - start))))

    @_serialized_run
    def message(self, run_id: str, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ControlError("message request must be an object", code="invalid_request")
        unknown = set(value) - {"message", "expectedPromptId", "idempotencyKey"}
        missing = {"message", "expectedPromptId", "idempotencyKey"} - set(value)
        if unknown or missing:
            raise ControlError("message request fields are invalid", code="invalid_request")
        message = text(value["message"], "message", maximum=32_768)
        expected = ensure_prompt_id(value["expectedPromptId"])
        idempotency = text(value["idempotencyKey"], "idempotencyKey", minimum=8, maximum=255)
        record = self._record(run_id)
        message_key = key_hash(idempotency)
        message_hash = hashlib.sha256(
            json.dumps(
                {"message": message, "expectedPromptId": expected},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if record.get("lastMessageKey") == message_key:
            if record.get("lastMessageHash") != message_hash:
                raise ControlError("idempotency key was reused for another message", code="idempotency_conflict", status=409)
            if record.get("lastMessagePromptId"):
                return record
            raise ControlError(
                "message delivery is ambiguous; inspect Box before retrying",
                code="ambiguous_message",
                status=409,
            )
        if (
            record.get("lastMessageKey")
            and not record.get("lastMessagePromptId")
        ):
            raise ControlError(
                "a previous message has an ambiguous delivery outcome; inspect or resume the Box",
                code="ambiguous_message",
                status=409,
            )
        if record["status"] in {"starting", "verifying", "stopped", "failed"}:
            raise ControlError(
                f"cannot message a run while it is {record['status']}",
                code="invalid_run_state",
                status=409,
            )
        if record.get("promptId") != expected:
            raise ControlError("active prompt changed; read the run before messaging", code="stale_prompt", status=409)
        if record.get("slotReleased"):
            raise ControlError("resume the Box before messaging", code="box_unavailable", status=409)
        self.store.update(
            run_id,
            lastMessageKey=message_key,
            lastMessageHash=message_hash,
            lastMessagePromptId=None,
        )
        try:
            queued = self._box().prompt(
                record["boxId"],
                prompt=self._followup_prompt(record, message),
                model=record.get("model"),
                reasoning_effort=record.get("reasoningEffort"),
            )
        except BoxError as exc:
            self.store.update(
                run_id,
                status="needs_input",
                statusDetail="Message delivery is ambiguous; inspect Box before retrying",
                lastError="ambiguous_message",
            )
            raise ControlError("message delivery is ambiguous", code="ambiguous_message", status=502) from exc
        prompt_id = self._prompt_id(queued)
        return self.store.update(
            run_id,
            promptId=prompt_id,
            promptStatus="queued",
            lastMessagePromptId=prompt_id,
            prNumber=None,
            prUrl=None,
            headSha=None,
            verifyReceipts=[],
            lastError=None,
            status="working",
            statusDetail="Follow-up queued",
        )

    @_serialized_run
    def interrupt(self, run_id: str, *, expected_prompt_id: str) -> dict[str, Any]:
        expected = ensure_prompt_id(expected_prompt_id)
        record = self._record(run_id)
        if record["status"] != "working":
            raise ControlError(
                f"cannot interrupt a run while it is {record['status']}",
                code="invalid_run_state",
                status=409,
            )
        if record.get("promptId") != expected:
            raise ControlError("active prompt changed; read the run before interrupting", code="stale_prompt", status=409)
        self._box().interrupt(record["boxId"])
        return self.store.update(
            run_id,
            promptStatus="failed",
            status="needs_input",
            statusDetail="Interrupted. Send a replacement prompt when ready",
        )

    @_serialized_run
    def desktop_url(self, run_id: str, *, theme: str = "dark") -> str:
        if theme not in {"light", "dark"}:
            raise ControlError("theme must be light or dark", code="invalid_theme")
        record = self._live_record(run_id, "desktop")
        result = self._box().desktop(record["boxId"], theme=theme)
        url = result.get("desktopUrl") or result.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ControlError("desktop stream is still provisioning", code="desktop_provisioning", status=409)
        return url

    @_serialized_run
    def preview_url(self, run_id: str) -> str:
        record = self._live_record(run_id, "preview")
        worker = self._worker_contract(record)
        if worker.preview is None:
            raise ControlError("this repository has no preview command", code="preview_unavailable", status=404)
        client = self._box()
        process_id = record.get("previewProcessId")
        preview_state = record.get("previewState")
        if preview_state in {"launching", "ambiguous"} and process_id is None:
            raise ControlError(
                "preview launch outcome is ambiguous; inspect the Box or resume before retrying",
                code="ambiguous_preview",
                status=409,
            )
        if process_id is not None and (
            isinstance(process_id, bool)
            or not isinstance(process_id, int)
            or not 1 <= process_id <= 2_147_483_647
        ):
            raise ControlError(
                "stored preview process identity is invalid",
                code="preview_failed",
                status=502,
            )
        running = False
        if process_id:
            try:
                process = client.command_status(record["boxId"], process_id)
                running = process.get("running") is True or process.get("status") == "running"
            except BoxError as exc:
                raise ControlError(
                    "preview process status is unavailable; retrying could duplicate it",
                    code="ambiguous_preview",
                    status=502,
                ) from exc
        if not running:
            repo_dir = record["repo"].rsplit("/", 1)[1]
            self.store.update(run_id, previewProcessId=None, previewState="launching")
            try:
                launched = client.command(
                    record["boxId"],
                    list(worker.preview.command),
                    cwd=self._working_cwd(repo_dir, worker.working_directory),
                    timeout_seconds=600,
                    detached=True,
                )
            except BoxError as exc:
                self.store.update(run_id, previewState="ambiguous")
                raise ControlError(
                    "preview launch outcome is ambiguous; inspect the Box or resume before retrying",
                    code="ambiguous_preview",
                    status=502,
                ) from exc
            process_id = launched.get("processId")
            if (
                isinstance(process_id, bool)
                or not isinstance(process_id, int)
                or not 1 <= process_id <= 2_147_483_647
            ):
                self.store.update(run_id, previewState="ambiguous")
                raise ControlError("preview process did not start", code="preview_failed", status=502)
            self.store.update(
                run_id,
                previewProcessId=process_id,
                previewPort=worker.preview.port,
                previewState="running",
            )
        hosted = client.host(record["boxId"], port=worker.preview.port, title=record["title"])
        return _protected_preview_url(hosted.get("url"), worker.preview.port)

    @_serialized_run
    def stop(self, run_id: str) -> dict[str, Any]:
        record = self._record(run_id)
        if record["status"] == "stopped" or record.get("slotReleased"):
            return record
        if not record.get("boxId"):
            return self.store.update(
                run_id,
                slotReleased=True,
                status="stopped",
                statusDetail="Incomplete reservation released",
            )
        result = self._box().stop(record["boxId"])
        return self.store.update(
            run_id,
            slotReleased=True,
            boxState=self._box_state(result) or "archiving",
            status="stopped",
            statusDetail="Box is snapshotting and stopping",
        )

    @_serialized_run
    def resume(self, run_id: str, *, ttl_seconds: int) -> dict[str, Any]:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 60 <= ttl_seconds <= self.config.max_ttl:
            raise ControlError("ttlSeconds is outside the finite controller limit", code="invalid_ttl")
        record = self._record(run_id)
        resumable_release = (
            record.get("slotReleased") is True
            and record.get("boxState") in {"archived", "stopped"}
        )
        if record["status"] != "stopped" and not resumable_release:
            raise ControlError(
                "only a stopped or archived run can resume",
                code="invalid_run_state",
                status=409,
            )
        if not record.get("boxId"):
            raise ControlError("this reservation has no Box to resume", code="box_unavailable", status=409)
        if record.get("boxState") == "deleted":
            raise ControlError("the Box was deleted and cannot resume", code="box_unavailable", status=409)
        try:
            self.store.reserve(run_id, max_parallel=self.config.max_parallel)
        except CapacityError as exc:
            raise ControlError(str(exc), code="local_capacity", status=409) from exc
        client = self._box()
        try:
            limits = client.limits()
        except BoxError as exc:
            self.store.update(run_id, slotReleased=True)
            raise ControlError(
                "Box capacity could not be checked before resume",
                code=exc.code,
                status=502,
            ) from exc
        if limits.get("canStart") is False:
            self.store.update(run_id, slotReleased=True)
            raise ControlError(
                "Box account capacity does not allow this worker to resume",
                code="box_capacity",
                status=409,
            )
        try:
            self.store.update(
                run_id,
                ttlSeconds=ttl_seconds,
                previewProcessId=None,
                previewState=None,
                promptStatus=None,
                lastMessageKey=None,
                lastMessageHash=None,
                lastMessagePromptId=None,
                lastError=None,
                status="starting",
                statusDetail="Resuming the Box",
                startAttemptAt=now_rfc3339(),
                slotReleased=False,
            )
            result = client.resume(record["boxId"], ttl_seconds=ttl_seconds)
        except BoxError as exc:
            try:
                observed = client.get_box(record["boxId"])
                state = self._box_state(observed)
            except BoxError:
                state = None
            if state in RELEASED_BOX_STATES:
                self.store.update(
                    run_id,
                    slotReleased=True,
                    boxState=state,
                    status="stopped",
                    statusDetail=f"Box is {state}. Resume to continue",
                    lastError=None,
                )
            else:
                self.store.update(
                    run_id,
                    status="needs_input",
                    statusDetail="Resume outcome is ambiguous; inspect or stop the Box",
                    lastError="ambiguous_resume",
                    slotReleased=False,
                    boxState=state or record.get("boxState"),
                )
            raise ControlError(
                "Box resume outcome is ambiguous", code="ambiguous_resume", status=502
            ) from exc
        self.store.update(
            run_id,
            boxState=self._box_state(result) or "resuming",
        )
        try:
            self._wait_ready(run_id, record["boxId"])
        except (BoxError, ControlError) as exc:
            state: str | None = None
            try:
                state = self._box_state(client.get_box(record["boxId"]))
            except BoxError:
                pass
            released = state in RELEASED_BOX_STATES
            self.store.update(
                run_id,
                boxState=state or self._record(run_id).get("boxState"),
                slotReleased=released,
                status="stopped" if released else "needs_input",
                statusDetail=(
                    f"Box is {state}. Resume to continue"
                    if released
                    else "Box resumed but readiness could not be confirmed; inspect or stop it"
                ),
                lastError=None if released else "ambiguous_resume",
            )
            raise ControlError(
                "Box resumed but readiness could not be confirmed",
                code="ambiguous_resume",
                status=502,
            ) from exc
        prompt_id = record.get("promptId")
        return self.store.update(
            run_id,
            promptId=prompt_id,
            lastError=None if prompt_id else "missing_prompt_revision",
            status="needs_input",
            statusDetail=(
                "Box resumed. Send the next prompt"
                if prompt_id
                else "Box resumed without a managed prompt revision; inspect it or start a new run"
            ),
        )

    @_serialized_run
    def handoff(self, run_id: str) -> dict[str, Any]:
        record = self._record(run_id)
        if record["status"] in {"review", "done"} and not record.get("lastError"):
            if record["delivery"] == "open_pull_request":
                number = record.get("prNumber")
                head_sha = record.get("headSha")
                try:
                    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
                        raise ControlError("stored pull request identity is invalid", code="pr_identity")
                    if self._unique_pull_number(record) != number:
                        raise ControlError("stored pull request is no longer unique", code="pr_identity")
                    self._verify_github_pull(record, number, ensure_sha(head_sha, "headSha"))
                except (ContractError, ControlError) as exc:
                    code = exc.code if isinstance(exc, ControlError) else "pr_identity"
                    self.store.update(
                        run_id,
                        status="needs_input",
                        statusDetail=str(exc),
                        lastError=code,
                    )
                    if isinstance(exc, ControlError):
                        raise
                    raise ControlError(str(exc), code=code) from exc
            return record
        if record["status"] not in {"working", "verifying", "needs_input"} or not record.get("promptId"):
            raise ControlError(
                "handoff requires the current managed prompt",
                code="invalid_run_state",
                status=409,
            )
        try:
            prompt = self._box().prompt_status(record["boxId"], record["promptId"])
            prompt_status = self._prompt_status(prompt)
            if prompt_status != "finished":
                raise ControlError("the current prompt has not finished", code="prompt_active", status=409)
            self.store.update(run_id, promptStatus=prompt_status, status="verifying", statusDetail="Verifying exact handoff")
            record = self._record(run_id)
            worker = self._worker_contract(record)
            repo_dir = record["repo"].rsplit("/", 1)[1]
            repo_cwd = repo_dir
            self._assert_plain_git_history(record["boxId"], repo_cwd)
            branch = self._command(box_id=record["boxId"], argv=["git", "branch", "--show-current"], cwd=repo_cwd)
            if branch.get("stdout", "").strip() != record["branch"]:
                raise ControlError("worker is on an unexpected branch", code="handoff_identity")
            head = self._head_and_clean(record["boxId"], repo_cwd)
            base_sha = ensure_sha(record["baseSha"], "baseSha")
            ancestor = self._command(
                record["boxId"],
                ["git", "merge-base", "--is-ancestor", base_sha, head],
                cwd=repo_cwd,
                allowed=(0, 1),
            )
            if ancestor.get("exitCode") != 0:
                raise ControlError("base SHA is not an ancestor of the worker head", code="handoff_identity")
            worker_change = self._command(
                record["boxId"],
                ["git", "diff", "--quiet", base_sha, head, "--", ".codexstack/worker.json"],
                cwd=repo_cwd,
                allowed=(0, 1),
            )
            if worker_change.get("exitCode") != 0:
                raise ControlError(
                    "worker.json changed inside a managed run", code="worker_contract_changed"
                )
            worker_history = self._command(
                record["boxId"],
                ["git", "rev-list", "--count", f"{base_sha}..{head}", "--", ".codexstack/worker.json"],
                cwd=repo_cwd,
            )
            if worker_history.get("stdout", "").strip() != "0":
                raise ControlError(
                    "worker.json was edited in managed-run history", code="worker_contract_changed"
                )
            if record["delivery"] == "read_only" and head != base_sha:
                raise ControlError("read-only worker changed Git history", code="handoff_identity")
            if record["delivery"] == "open_pull_request":
                self._pull_request(record, repo_cwd, head)
            receipts = self._run_manifest_commands(
                record["boxId"],
                worker.verify,
                cwd=self._working_cwd(repo_cwd, worker.working_directory),
                run_id=run_id,
                receipt_field="verifyReceipts",
                detail="Running declared verification",
            )
            self._assert_plain_git_history(record["boxId"], repo_cwd)
            final_branch = self._command(
                record["boxId"], ["git", "branch", "--show-current"], cwd=repo_cwd
            )
            if final_branch.get("stdout", "").strip() != record["branch"]:
                raise ControlError(
                    "verification changed the isolated branch",
                    code="verification_changed_branch",
                )
            final_head = self._head_and_clean(record["boxId"], repo_cwd)
            if final_head != head:
                raise ControlError("verification changed the exact head SHA", code="verification_changed_head")
            updates: dict[str, Any] = {
                "headSha": final_head,
                "verifyReceipts": receipts,
                "status": "done",
                "statusDetail": "Verification passed",
                "lastError": None,
            }
            if record["delivery"] == "open_pull_request":
                pr = self._pull_request(record, repo_cwd, final_head)
                updates.update(
                    status="review",
                    statusDetail="Verified pull request is ready for review",
                    prNumber=pr["number"],
                    prUrl=pr["url"],
                )
            return self.store.update(run_id, **updates)
        except (BoxError, ContractError, ControlError, StoreError) as exc:
            code = exc.code if isinstance(exc, (BoxError, ControlError)) else "handoff_failed"
            try:
                self.store.update(run_id, status="needs_input", statusDetail=str(exc), lastError=code)
            except StoreError:
                pass
            if isinstance(exc, ControlError):
                raise
            raise ControlError(str(exc), code=code, status=502 if isinstance(exc, BoxError) else 400) from exc

    def _refresh(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._run_guard(record["id"]):
            current = self._record(record["id"])
            if current.get("slotReleased") or not current.get("boxId"):
                return current
            return self._refresh_locked(current)

    def _refresh_locked(self, record: dict[str, Any]) -> dict[str, Any]:
        client = self._box()
        try:
            box_result = client.get_box(record["boxId"])
        except BoxError as exc:
            if exc.status == 404:
                terminal = record["status"] in {"review", "done"}
                return self.store.update(
                    record["id"],
                    boxState="deleted",
                    slotReleased=True,
                    status=record["status"] if terminal else "failed",
                    statusDetail=(
                        f"{record.get('statusDetail') or 'Run retained'}; Box no longer exists"
                    ),
                    lastError=record.get("lastError") if terminal else "box_deleted",
                )
            raise
        box_state = self._box_state(box_result)
        changes: dict[str, Any] = {"boxState": box_state}
        if box_state in RELEASED_BOX_STATES:
            terminal = record["status"] in {"review", "done"}
            return self.store.update(
                record["id"],
                slotReleased=True,
                boxState=box_state,
                status=record["status"] if terminal else "stopped",
                statusDetail=(
                    f"{record.get('statusDetail') or 'Verified delivery retained'}; "
                    f"Box is {box_state}"
                    if terminal
                    else f"Box is {box_state}. Resume to continue"
                ),
                lastError=record.get("lastError") if terminal else None,
            )
        if record["status"] in {"working", "verifying"} and record.get("promptId"):
            prompt = client.prompt_status(record["boxId"], record["promptId"])
            status = self._prompt_status(prompt)
            changes["promptStatus"] = status
            if status in {"sending", "queued", "running"}:
                changes.update(status="working", statusDetail="Codex is working in the Box")
            elif status == "finished" and record["status"] not in {"verifying", "review", "done"}:
                changes.update(status="needs_input", statusDetail="Agent finished. Verify the handoff")
            elif status == "finished" and record["status"] == "verifying":
                changes.update(
                    status="needs_input",
                    statusDetail="Verification was interrupted. Run handoff again",
                    lastError="verification_interrupted",
                )
            elif status == "failed":
                changes.update(status="failed", statusDetail="Box reports that the prompt failed")
        return self.store.update(record["id"], **changes)

    def _events(self, record: dict[str, Any], cursor: str | None) -> tuple[list[Any], str | None]:
        if not record.get("boxId") or record.get("slotReleased"):
            return [], cursor
        result = self._box().events(record["boxId"], cursor=cursor, limit=200)
        events = result.get("events", [])
        if not isinstance(events, list):
            events = []
        page = result.get("pageInfo")
        next_cursor = result.get("nextCursor")
        if next_cursor is None and isinstance(page, dict):
            next_cursor = page.get("nextCursor") or page.get("endCursor")
        if next_cursor is not None and not isinstance(next_cursor, str):
            next_cursor = cursor
        return [self._sanitize_event(item) for item in events[:200]], next_cursor

    def _wait_ready(self, run_id: str, box_id: str, timeout: float = 120) -> None:
        deadline = self._clock() + timeout
        while True:
            result = self._box().get_box(box_id)
            state = self._box_state(result)
            self.store.update(run_id, boxState=state)
            if state in READY_BOX_STATES:
                return
            if state in {"error", "archived"}:
                raise ControlError(f"Box entered {state}", code="box_not_ready", status=502)
            if self._clock() >= deadline:
                raise ControlError("Box did not become ready in time", code="box_timeout", status=504)
            self._sleep(1)

    def _run_manifest_commands(
        self,
        box_id: str,
        commands: tuple[tuple[str, ...], ...],
        *,
        cwd: str,
        run_id: str | None = None,
        receipt_field: str | None = None,
        detail: str = "Running command",
    ) -> list[dict[str, Any]]:
        receipts: list[dict[str, Any]] = []
        for index, argv in enumerate(commands):
            if run_id is not None:
                self.store.update(
                    run_id,
                    statusDetail=f"{detail} {index + 1}/{len(commands)}",
                )
            result = self._command(box_id, list(argv), cwd=cwd)
            receipts.append(
                {
                    "index": index,
                    "exitCode": result.get("exitCode"),
                    "success": result.get("success") is True,
                    "finishedAt": result.get("finishedAt"),
                }
            )
            if run_id is not None and receipt_field is not None:
                self.store.update(run_id, **{receipt_field: receipts})
        return receipts

    def _command(
        self,
        box_id: str,
        argv: list[str],
        *,
        cwd: str,
        allowed: tuple[int, ...] = (0,),
    ) -> dict[str, Any]:
        command_argv = (
            ["git", "--no-replace-objects", *argv[1:]]
            if argv and argv[0] == "git"
            else argv
        )
        result = self._box().command(
            box_id, command_argv, cwd=cwd, timeout_seconds=600, detached=False
        )
        exit_code = result.get("exitCode")
        timed_out = result.get("timedOut")
        success = result.get("success")
        if (
            result.get("type") != "command.finished"
            or isinstance(exit_code, bool)
            or not isinstance(exit_code, int)
            or not isinstance(success, bool)
            or not isinstance(timed_out, bool)
            or not isinstance(result.get("stdout"), str)
            or not isinstance(result.get("stderr"), str)
            or success is not (exit_code == 0)
        ):
            raise ControlError(
                "Box returned an invalid synchronous command result",
                code="command_invalid",
                status=502,
            )
        if (
            exit_code not in allowed
            or timed_out
        ):
            raise ControlError(
                f"command {argv[0]} failed with exit {exit_code}", code="command_failed", status=502
            )
        return result

    def _assert_plain_git_history(self, box_id: str, repo_cwd: str) -> None:
        replacements = self._command(
            box_id,
            ["git", "for-each-ref", "--format=%(refname)", "refs/replace"],
            cwd=repo_cwd,
        )
        shallow = self._command(
            box_id, ["git", "rev-parse", "--is-shallow-repository"], cwd=repo_cwd
        )
        graft_path = self._command(
            box_id, ["git", "rev-parse", "--git-path", "info/grafts"], cwd=repo_cwd
        ).get("stdout", "").strip()
        if (
            replacements.get("stdout", "").strip()
            or shallow.get("stdout", "").strip() != "false"
            or not graft_path
            or "\n" in graft_path
            or len(graft_path) > 4_096
        ):
            raise ControlError(
                "repository uses untrusted Git history indirection",
                code="git_history_untrusted",
            )
        graft = self._command(
            box_id, ["test", "!", "-e", graft_path], cwd=repo_cwd, allowed=(0, 1)
        )
        if graft.get("exitCode") != 0:
            raise ControlError(
                "repository uses an untrusted Git graft file",
                code="git_history_untrusted",
            )

    def _head_and_clean(self, box_id: str, repo_cwd: str) -> str:
        head = self._command(box_id, ["git", "rev-parse", "HEAD"], cwd=repo_cwd)
        sha = ensure_sha(head.get("stdout", "").strip(), "headSha")
        clean = self._command(box_id, ["git", "status", "--porcelain"], cwd=repo_cwd)
        if clean.get("stdout", "").strip():
            raise ControlError("worker repository is not clean", code="dirty_handoff")
        index = self._command(box_id, ["git", "ls-files", "-v", "-z"], cwd=repo_cwd)
        _assert_normal_git_index(index.get("stdout", ""))
        return sha

    def _pull_request(self, record: dict[str, Any], repo_cwd: str, head_sha: str) -> dict[str, Any]:
        origin = self._command(
            record["boxId"], ["git", "remote", "get-url", "origin"], cwd=repo_cwd
        )
        if self._github_repo(origin.get("stdout")) != record["repo"].lower():
            raise ControlError(
                "worker origin no longer matches the managed repository",
                code="pr_identity",
            )
        remote = self._command(
            record["boxId"],
            [
                "git",
                "ls-remote",
                "--heads",
                "origin",
                f"refs/heads/{record['branch']}",
            ],
            cwd=repo_cwd,
        )
        lines = [line for line in remote.get("stdout", "").splitlines() if line.strip()]
        expected_remote = f"{head_sha}\trefs/heads/{record['branch']}"
        if lines != [expected_remote]:
            raise ControlError("remote branch does not match the exact local head", code="pr_identity")
        number = self._unique_pull_number(record)
        self._verify_github_pull(record, number, head_sha)
        return {"number": number, "url": f"https://github.com/{record['repo']}/pull/{number}"}

    def _unique_pull_number(self, record: dict[str, Any]) -> int:
        pulls = self._github_list(record["repo"], record["branch"], record["baseRef"])
        if len(pulls) != 1 or not isinstance(pulls[0], dict):
            raise ControlError(
                "expected exactly one open pull request for the managed branch",
                code="pr_identity",
            )
        number = pulls[0].get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise ControlError("pull request identity or state failed verification", code="pr_identity")
        return number

    def _verify_github_pull(
        self, record: dict[str, Any], number: int, head_sha: str
    ) -> None:
        authoritative = self._github_lookup(record["repo"], number)
        if not isinstance(authoritative, dict):
            raise ControlError("GitHub returned an invalid pull request", code="pr_invalid", status=502)
        base = authoritative.get("base")
        head = authoritative.get("head")
        base_repo = base.get("repo") if isinstance(base, dict) else None
        head_repo = head.get("repo") if isinstance(head, dict) else None
        expected_url = f"https://github.com/{record['repo']}/pull/{number}"
        expected_repo = record["repo"].lower()
        checks = {
            "number": authoritative.get("number") == number,
            "state": str(authoritative.get("state", "")).lower() == "open",
            "draft": authoritative.get("draft") is False,
            "base": isinstance(base, dict) and base.get("ref") == record["baseRef"],
            "head": isinstance(head, dict) and head.get("ref") == record["branch"],
            "sha": isinstance(head, dict) and head.get("sha") == head_sha,
            "base_repo": isinstance(base_repo, dict)
            and str(base_repo.get("full_name", "")).lower() == expected_repo,
            "head_repo": isinstance(head_repo, dict)
            and str(head_repo.get("full_name", "")).lower() == expected_repo,
            "url": str(authoritative.get("html_url", "")).lower() == expected_url.lower(),
        }
        if not all(checks.values()):
            raise ControlError("pull request identity or state failed verification", code="pr_identity")

    @staticmethod
    def _github_pull_via_cli(repo: str, number: int) -> dict[str, Any]:
        value = RunController._github_api_via_cli(f"repos/{repo}/pulls/{number}")
        if not isinstance(value, dict):
            raise ControlError("GitHub returned an invalid pull request", code="pr_invalid", status=502)
        return value

    @staticmethod
    def _github_pulls_via_cli(repo: str, branch: str, _base_ref: str) -> list[dict[str, Any]]:
        owner = repo.split("/", 1)[0]
        query = urlencode(
            {
                "state": "open",
                "head": f"{owner}:{branch}",
                "per_page": "100",
            }
        )
        value = RunController._github_api_via_cli(f"repos/{repo}/pulls?{query}")
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise ControlError("GitHub returned an invalid pull request list", code="pr_invalid", status=502)
        return value

    @staticmethod
    def _github_api_via_cli(endpoint: str) -> Any:
        try:
            completed = subprocess.run(
                ["gh", "api", "--hostname", "github.com", "--method", "GET", endpoint],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise ControlError(
                "independent GitHub verification is unavailable on the control host",
                code="github_unavailable",
                status=502,
            ) from exc
        if completed.returncode != 0 or len(completed.stdout.encode("utf-8")) > 1_048_576:
            raise ControlError(
                "independent GitHub verification failed",
                code="github_unavailable",
                status=502,
            )
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ControlError("GitHub returned invalid JSON", code="pr_invalid", status=502) from exc
        return value

    def _delivery_prompt(
        self,
        request: StartRequest,
        worker: WorkerConfig,
        run_id: str,
        branch: str,
        base_sha: str,
    ) -> str:
        if request.delivery == "open_pull_request":
            delivery = (
                "Commit the finished changes, push this exact branch, and open one non-draft pull request "
                "against the configured base branch. Never merge, close, retarget, force-push, or deploy."
            )
        elif request.delivery == "local_change":
            delivery = (
                "Commit finished changes locally on this exact branch. Do not push, open a pull "
                "request, merge, or deploy."
            )
        else:
            delivery = "Investigate without changing files or Git history. Do not push, open a pull request, merge, or deploy."
        verify = json.dumps([list(item) for item in worker.verify], separators=(",", ":"))
        return (
            "$codexstack:work\n\n"
            f"User goal:\n{request.goal}\n\n"
            "Immutable run contract:\n"
            f"- run: {run_id}\n"
            f"- repository: {request.repo}\n"
            f"- base: {worker.base_ref} at {base_sha}\n"
            f"- branch: {branch}\n"
            f"- declared verification argv: {verify}\n"
            f"- delivery: {request.delivery}\n\n"
            "Work only in the existing repository and branch. Do not switch branches, reset, rebase, "
            "rewrite history, alter worker.json, expose credentials, or start fleet controls. Run the "
            "declared verification before delivery and report concrete evidence. "
            f"{delivery}"
        )

    @staticmethod
    def _followup_prompt(record: dict[str, Any], message: str) -> str:
        worker = record.get("workerConfig")
        verify = worker.get("verify", []) if isinstance(worker, dict) else []
        verification = json.dumps(verify, separators=(",", ":"))
        delivery = record.get("delivery") or "open_pull_request"
        if delivery == "open_pull_request":
            delivery_rule = "Keep one non-draft pull request for this exact branch. Never merge, close, retarget, force-push, or deploy."
        elif delivery == "local_change":
            delivery_rule = (
                "Commit finished changes locally on this exact branch. Do not push, open a pull "
                "request, merge, or deploy."
            )
        else:
            delivery_rule = "Remain read-only. Do not change files or Git history, push, open a pull request, merge, or deploy."
        return (
            "$codexstack:work\n\n"
            f"Operator follow-up:\n{message}\n\n"
            "Immutable continuation contract:\n"
            f"- run: {record.get('id')}\n"
            f"- repository: {record.get('repo')}\n"
            f"- base: {record.get('baseRef')} at {record.get('baseSha')}\n"
            f"- branch: {record.get('branch')}\n"
            f"- declared verification argv: {verification}\n"
            f"- delivery: {delivery}\n\n"
            "Continue only in the existing repository and branch. Do not switch branches, reset, rebase, "
            "rewrite history, alter worker.json, expose credentials, or start fleet controls. Run declared "
            f"verification before delivery and report concrete evidence. {delivery_rule}"
        )

    def _record(self, run_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"run_[0-9a-f]{20}", run_id):
            raise ControlError("invalid run id", code="invalid_run")
        record = self.store.get(run_id)
        if record is None:
            raise ControlError("run not found", code="run_not_found", status=404)
        return record

    def _reconcile_stale_start(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._run_guard(record["id"]):
            current = self._record(record["id"])
            if (
                current.get("status") != "starting"
                or not self._start_is_stale(current)
            ):
                return current
            has_box = bool(current.get("boxId"))
            return self.store.update(
                current["id"],
                status="needs_input" if has_box else "failed",
                statusDetail=(
                    "Start or resume stopped before a durable prompt receipt; inspect the Box before continuing"
                    if has_box
                    else "Start stopped before a Box was durably recorded; retry with the same idempotency key"
                ),
                lastError="incomplete_start",
                slotReleased=not has_box,
            )

    def _live_record(self, run_id: str, capability: str) -> dict[str, Any]:
        record = self._record(run_id)
        if (
            not record.get("boxId")
            or record.get("slotReleased")
            or record.get("boxState") in RELEASED_BOX_STATES
            or record.get("status") == "stopped"
        ):
            raise ControlError(
                f"resume the Box before requesting {capability}",
                code="box_unavailable",
                status=409,
            )
        return record

    @staticmethod
    def _worker_contract(record: dict[str, Any]) -> WorkerConfig:
        worker_value = record.get("workerConfig")
        expected_hash = record.get("workerConfigHash")
        if not isinstance(worker_value, dict) or not isinstance(expected_hash, str):
            raise ControlError("worker configuration is unavailable", code="worker_contract")
        worker = WorkerConfig.parse(
            json.dumps(worker_value, sort_keys=True, separators=(",", ":"))
        )
        if not hmac.compare_digest(worker.sha256(), expected_hash):
            raise ControlError(
                "stored worker configuration failed its integrity check",
                code="worker_contract_changed",
            )
        return worker

    @staticmethod
    def _extract_id(value: dict[str, Any], label: str) -> str:
        nested = value.get(label.lower())
        candidate = value.get("id") or value.get("boxId")
        if isinstance(nested, dict):
            candidate = nested.get("id") or nested.get("boxId") or candidate
        try:
            return ensure_box_id(candidate)
        except ContractError as exc:
            raise ControlError(
                f"{label} response did not include a valid id",
                code="box_invalid",
                status=502,
            ) from exc

    @staticmethod
    def _box_state(value: dict[str, Any]) -> str | None:
        nested = value.get("box")
        state = nested.get("state") if isinstance(nested, dict) else None
        candidate = state or value.get("state") or value.get("status")
        return candidate if isinstance(candidate, str) else None

    @staticmethod
    def _prompt_id(value: dict[str, Any]) -> str:
        nested = value.get("promptRun")
        candidate = value.get("promptId") or value.get("id")
        if isinstance(nested, dict):
            candidate = nested.get("promptId") or nested.get("id") or candidate
        return ensure_prompt_id(candidate)

    @staticmethod
    def _prompt_status(value: dict[str, Any]) -> str:
        nested = value.get("promptRun")
        candidate = nested.get("status") if isinstance(nested, dict) else None
        status = candidate or value.get("status")
        if status not in {"sending", "queued", "running", "finished", "failed"}:
            raise ControlError("Box returned an unknown prompt status", code="prompt_invalid", status=502)
        return status

    @staticmethod
    def _working_cwd(repo_cwd: str, relative: str) -> str:
        return repo_cwd if relative == "." else f"{repo_cwd}/{relative}"

    @staticmethod
    def _start_is_stale(record: dict[str, Any]) -> bool:
        value = record.get("startAttemptAt") or record.get("createdAt")
        if not isinstance(value, str):
            return True
        try:
            updated = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return True
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        return (datetime.now(UTC) - updated).total_seconds() >= START_STALE_SECONDS

    @staticmethod
    def _github_repo(remote: Any) -> str:
        value = str(remote).strip()
        if value.startswith("git@github.com:"):
            path = value.split(":", 1)[1]
        else:
            parsed = urlparse(value)
            if parsed.hostname != "github.com":
                return ""
            path = parsed.path.lstrip("/")
        return path.removesuffix(".git").lower()

    @classmethod
    def _sanitize_event(cls, value: Any, depth: int = 0) -> Any:
        if depth > 8:
            return "[truncated]"
        if isinstance(value, str):
            return ANSI.sub("", value.replace("\x00", ""))[:32_768]
        if isinstance(value, list):
            return [cls._sanitize_event(item, depth + 1) for item in value[:200]]
        if isinstance(value, dict):
            return {
                str(key)[:128]: cls._sanitize_event(item, depth + 1)
                for key, item in list(value.items())[:200]
            }
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)[:1_024]
