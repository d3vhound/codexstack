from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .model import RUN_STATUSES, now_rfc3339


class StoreError(RuntimeError):
    """Base class for durable run store failures."""


class StoreConflict(StoreError):
    """The run id already exists for a different request."""


class CapacityError(StoreError):
    """The configured active-run capacity has been reached."""

    def __init__(self, active: int, limit: int) -> None:
        self.active = active
        self.limit = limit
        super().__init__(f"active run capacity reached ({active}/{limit})")


class RunNotFound(StoreError):
    """The requested run does not exist."""


_COLUMN_DEFINITIONS: dict[str, str] = {
    "id": "TEXT PRIMARY KEY",
    "request_hash": "TEXT NOT NULL DEFAULT ''",
    "title": "TEXT",
    "repo": "TEXT",
    "base_ref": "TEXT",
    "base_sha": "TEXT",
    "branch": "TEXT",
    "head_sha": "TEXT",
    "model": "TEXT",
    "reasoning_effort": "TEXT",
    "ttl_seconds": "INTEGER",
    "delivery": "TEXT",
    "status": "TEXT NOT NULL DEFAULT 'starting'",
    "status_detail": "TEXT",
    "box_id": "TEXT",
    "box_state": "TEXT",
    "prompt_id": "TEXT",
    "prompt_status": "TEXT",
    "created_at": "TEXT NOT NULL DEFAULT ''",
    "start_attempt_at": "TEXT",
    "updated_at": "TEXT NOT NULL DEFAULT ''",
    "pr_number": "INTEGER",
    "pr_url": "TEXT",
    "preview_port": "INTEGER",
    "preview_process_id": "INTEGER",
    "preview_state": "TEXT",
    "worker_config_json": "TEXT",
    "worker_config_hash": "TEXT",
    "setup_receipts_json": "TEXT NOT NULL DEFAULT '[]'",
    "verify_receipts_json": "TEXT NOT NULL DEFAULT '[]'",
    "last_error": "TEXT",
    "last_message_key": "TEXT",
    "last_message_hash": "TEXT",
    "last_message_prompt_id": "TEXT",
    "slot_released": "INTEGER NOT NULL DEFAULT 0",
}

_COLUMNS = tuple(_COLUMN_DEFINITIONS)
_JSON_COLUMNS = frozenset(
    {"worker_config_json", "setup_receipts_json", "verify_receipts_json"}
)
_OUTPUT_KEYS: dict[str, str] = {
    "id": "id",
    "request_hash": "requestHash",
    "title": "title",
    "repo": "repo",
    "base_ref": "baseRef",
    "base_sha": "baseSha",
    "branch": "branch",
    "head_sha": "headSha",
    "model": "model",
    "reasoning_effort": "reasoningEffort",
    "ttl_seconds": "ttlSeconds",
    "delivery": "delivery",
    "status": "status",
    "status_detail": "statusDetail",
    "box_id": "boxId",
    "box_state": "boxState",
    "prompt_id": "promptId",
    "prompt_status": "promptStatus",
    "created_at": "createdAt",
    "start_attempt_at": "startAttemptAt",
    "updated_at": "updatedAt",
    "pr_number": "prNumber",
    "pr_url": "prUrl",
    "preview_port": "previewPort",
    "preview_process_id": "previewProcessId",
    "preview_state": "previewState",
    "worker_config_json": "workerConfig",
    "worker_config_hash": "workerConfigHash",
    "setup_receipts_json": "setupReceipts",
    "verify_receipts_json": "verifyReceipts",
    "last_error": "lastError",
    "last_message_key": "lastMessageKey",
    "last_message_hash": "lastMessageHash",
    "last_message_prompt_id": "lastMessagePromptId",
    "slot_released": "slotReleased",
}

_INPUT_ALIASES = {column: column for column in _COLUMNS}
_INPUT_ALIASES.update({key: column for column, key in _OUTPUT_KEYS.items()})
_INPUT_ALIASES.update(
    {
        "worker_config": "worker_config_json",
        "workerConfigJson": "worker_config_json",
        "setup_receipts": "setup_receipts_json",
        "setupReceiptsJson": "setup_receipts_json",
        "verify_receipts": "verify_receipts_json",
        "verifyReceiptsJson": "verify_receipts_json",
    }
)

_MUTABLE_COLUMNS = frozenset(
    {
        "title",
        "base_ref",
        "base_sha",
        "branch",
        "head_sha",
        "model",
        "reasoning_effort",
        "ttl_seconds",
        "delivery",
        "status",
        "status_detail",
        "start_attempt_at",
        "box_id",
        "box_state",
        "prompt_id",
        "prompt_status",
        "pr_number",
        "pr_url",
        "preview_port",
        "preview_process_id",
        "preview_state",
        "worker_config_json",
        "worker_config_hash",
        "setup_receipts_json",
        "verify_receipts_json",
        "last_error",
        "last_message_key",
        "last_message_hash",
        "last_message_prompt_id",
        "slot_released",
    }
)


class RunStore:
    """SQLite-backed storage for agent run state."""

    def __init__(self, database: str | os.PathLike[str], *, busy_timeout_ms: int = 5_000) -> None:
        if isinstance(busy_timeout_ms, bool) or not isinstance(busy_timeout_ms, int):
            raise TypeError("busy_timeout_ms must be an integer")
        if busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms must be non-negative")

        self.database = os.fspath(database)
        if self.database == ":memory:":
            raise ValueError("RunStore requires a durable SQLite database path")
        self.busy_timeout_ms = busy_timeout_ms
        Path(self.database).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._initialize_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.database,
            timeout=self.busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            self._secure_state_files()
            yield connection
        finally:
            connection.close()
            self._secure_state_files()

    def _secure_state_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            path = Path(f"{self.database}{suffix}")
            try:
                path.chmod(0o600)
            except FileNotFoundError:
                continue

    def _initialize_schema(self) -> None:
        definitions = ",\n                    ".join(
            f'"{column}" {definition}' for column, definition in _COLUMN_DEFINITIONS.items()
        )
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS agent_runs (
                        {definitions}
                    )
                    """
                )
                existing = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(agent_runs)").fetchall()
                }
                for column, definition in _COLUMN_DEFINITIONS.items():
                    if column not in existing:
                        connection.execute(
                            f'ALTER TABLE agent_runs ADD COLUMN "{column}" {definition}'
                        )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS agent_runs_status_idx "
                    "ON agent_runs(status)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS agent_runs_created_idx "
                    "ON agent_runs(created_at DESC, id DESC)"
                )
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise

    def create(
        self,
        initial: Mapping[str, Any],
        max_parallel: int | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Create a run atomically, returning ``(record, was_created)``."""
        if max_parallel is not None and (
            isinstance(max_parallel, bool)
            or not isinstance(max_parallel, int)
            or max_parallel < 1
        ):
            raise ValueError("max_parallel must be a positive integer or None")

        values = self._normalize_input(initial, allowed=frozenset(_COLUMNS))
        missing = {"id", "request_hash"} - set(values)
        if missing:
            names = ", ".join(_OUTPUT_KEYS[column] for column in sorted(missing))
            raise ValueError(f"create is missing required fields: {names}")
        if not isinstance(values["id"], str) or not values["id"]:
            raise ValueError("id must be a non-empty string")
        if not isinstance(values["request_hash"], str) or not values["request_hash"]:
            raise ValueError("requestHash must be a non-empty string")

        timestamp = now_rfc3339()
        values.setdefault("status", "starting")
        values.setdefault("created_at", timestamp)
        values.setdefault("updated_at", values["created_at"])
        values.setdefault("setup_receipts_json", "[]")
        values.setdefault("verify_receipts_json", "[]")
        values.setdefault("slot_released", 0)
        self._validate_status(values.get("status"))

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT * FROM agent_runs WHERE id = ?", (values["id"],)
                ).fetchone()
                if existing is not None:
                    if existing["request_hash"] != values["request_hash"]:
                        raise StoreConflict(
                            f"run {values['id']} already exists for a different request"
                        )
                    record = self._record(existing)
                    connection.execute("COMMIT")
                    return record, False

                if max_parallel is not None:
                    active = self._count_active(connection)
                    if active >= max_parallel:
                        raise CapacityError(active, max_parallel)

                insert_values = {column: values.get(column) for column in _COLUMNS}
                columns_sql = ", ".join(f'"{column}"' for column in _COLUMNS)
                placeholders = ", ".join("?" for _ in _COLUMNS)
                connection.execute(
                    f"INSERT INTO agent_runs ({columns_sql}) VALUES ({placeholders})",
                    tuple(insert_values[column] for column in _COLUMNS),
                )
                row = connection.execute(
                    "SELECT * FROM agent_runs WHERE id = ?", (values["id"],)
                ).fetchone()
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        if row is None:
            raise StoreError("created run could not be read back")
        return self._record(row), True

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM agent_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return None if row is None else self._record(row)

    def list(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1_000:
            raise ValueError("limit must be an integer from 1 to 1000")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_runs "
                "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._record(row) for row in rows]

    def count_active(self) -> int:
        with self._connection() as connection:
            return self._count_active(connection)

    def reserve(self, run_id: str, *, max_parallel: int) -> dict[str, Any]:
        if isinstance(max_parallel, bool) or not isinstance(max_parallel, int) or max_parallel < 1:
            raise ValueError("max_parallel must be a positive integer")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM agent_runs WHERE id = ?", (run_id,)
                ).fetchone()
                if row is None:
                    raise RunNotFound(f"run {run_id} does not exist")
                if not bool(row["slot_released"]):
                    connection.execute("COMMIT")
                    return self._record(row)
                active = self._count_active(connection)
                if active >= max_parallel:
                    raise CapacityError(active, max_parallel)
                connection.execute(
                    "UPDATE agent_runs SET slot_released = 0, updated_at = ? WHERE id = ?",
                    (now_rfc3339(), run_id),
                )
                row = connection.execute(
                    "SELECT * FROM agent_runs WHERE id = ?", (run_id,)
                ).fetchone()
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        if row is None:
            raise StoreError("reserved run could not be read back")
        return self._record(row)

    def update(
        self,
        run_id: str,
        changes: Mapping[str, Any] | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        """Apply an allowlisted partial update and return the resulting run."""
        combined: dict[str, Any] = {}
        if changes is not None:
            if not isinstance(changes, Mapping):
                raise TypeError("changes must be a mapping")
            combined.update(changes)
        overlap = set(combined).intersection(fields)
        if overlap:
            raise ValueError(f"duplicate update fields: {', '.join(sorted(overlap))}")
        combined.update(fields)
        if not combined:
            existing = self.get(run_id)
            if existing is None:
                raise RunNotFound(f"run {run_id} does not exist")
            return existing

        values = self._normalize_input(combined, allowed=_MUTABLE_COLUMNS)
        self._validate_status(values.get("status"))
        values["updated_at"] = now_rfc3339()
        assignments = ", ".join(f'"{column}" = ?' for column in values)
        parameters = [*values.values(), run_id]

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute(
                    f"UPDATE agent_runs SET {assignments} WHERE id = ?", parameters
                )
                if cursor.rowcount != 1:
                    raise RunNotFound(f"run {run_id} does not exist")
                row = connection.execute(
                    "SELECT * FROM agent_runs WHERE id = ?", (run_id,)
                ).fetchone()
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        if row is None:
            raise StoreError("updated run could not be read back")
        return self._record(row)

    @staticmethod
    def _count_active(connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM agent_runs WHERE slot_released = 0"
        ).fetchone()
        if row is None:
            raise StoreError("active run count failed")
        return int(row["count"])

    @staticmethod
    def _validate_status(status: Any) -> None:
        if status is not None and status not in RUN_STATUSES:
            allowed = ", ".join(sorted(RUN_STATUSES))
            raise ValueError(f"status must be one of: {allowed}")

    @staticmethod
    def _normalize_input(
        values: Mapping[str, Any], *, allowed: frozenset[str]
    ) -> dict[str, Any]:
        if not isinstance(values, Mapping):
            raise TypeError("store values must be a mapping")
        normalized: dict[str, Any] = {}
        for key, value in values.items():
            if not isinstance(key, str) or key not in _INPUT_ALIASES:
                raise ValueError(f"unknown store field: {key!r}")
            column = _INPUT_ALIASES[key]
            if column not in allowed:
                raise ValueError(f"store field is not mutable: {key}")
            if column in normalized:
                raise ValueError(f"duplicate store field: {key}")
            if column in _JSON_COLUMNS:
                value = RunStore._encode_json(value, _OUTPUT_KEYS[column])
            normalized[column] = value
        return normalized

    @staticmethod
    def _encode_json(value: Any, label: str) -> str | None:
        if value is None:
            return None
        try:
            decoded = json.loads(value) if isinstance(value, str) else value
            return json.dumps(decoded, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"{label} must be JSON-serializable") from exc

    @staticmethod
    def _record(row: sqlite3.Row) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for column in _COLUMNS:
            value = row[column]
            if column in _JSON_COLUMNS and value is not None:
                try:
                    value = json.loads(value)
                except (TypeError, json.JSONDecodeError) as exc:
                    raise StoreError(f"stored {_OUTPUT_KEYS[column]} is invalid JSON") from exc
            result[_OUTPUT_KEYS[column]] = value
        result["slotReleased"] = bool(result["slotReleased"])
        return result
