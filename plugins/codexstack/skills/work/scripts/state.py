#!/usr/bin/env python3
"""Passive, durable program state for a CodexStack coordinator.

This helper records and validates control-plane facts. It deliberately does
not launch, schedule, poll, supervise, contact providers, or mutate Git.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import secrets
import stat as statmod
import sys
import tempfile
import threading
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

try:  # Advisory cross-process serialization on POSIX.
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover - exercised only on non-POSIX Python.
    fcntl = None


CONTRACT_VERSION = "codexstack.state.v3"
UNIT_STATES = frozenset({
    "scoped", "ready", "running", "needs-verify", "verified", "landed",
    "blocked", "failed", "abandoned", "zombie-reconciled",
})
TERMINAL_UNIT_STATES = frozenset({"landed", "abandoned", "zombie-reconciled"})
UNIT_TRANSITIONS: dict[str, frozenset[str]] = {
    "scoped": frozenset({"scoped", "ready", "blocked", "abandoned"}),
    "ready": frozenset({"ready", "running", "blocked", "abandoned"}),
    "running": frozenset({"running", "needs-verify", "failed", "blocked", "abandoned", "zombie-reconciled"}),
    "needs-verify": frozenset({"needs-verify", "verified", "failed", "blocked", "abandoned", "zombie-reconciled"}),
    "verified": frozenset({"verified", "landed", "blocked", "failed", "abandoned"}),
    "landed": frozenset({"landed"}),
    "blocked": frozenset({"blocked", "ready", "failed", "abandoned", "zombie-reconciled"}),
    "failed": frozenset({"failed", "abandoned"}),
    "abandoned": frozenset({"abandoned"}),
    "zombie-reconciled": frozenset({"zombie-reconciled"}),
}
RECONCILIATION_UNIT_STATES = frozenset({"abandoned", "zombie-reconciled"})
RECONCILIATION_CLASSES = frozenset({"discarded", "noise", "observed", "zombie"})
GATE_STATES = frozenset({"pending", "blocked", "passed", "skipped"})
# These are shipping-ledger verdicts for one exact PR head. Lane reports use
# the separate PASS/ISSUES/BLOCKED vocabulary in their own records.
PR_VERDICTS = frozenset({"PASS", "PASS+NOTES", "FAIL"})
LANE_OUTCOMES = frozenset({"PASS", "ISSUES", "BLOCKED"})
STOP_RELEASE_EVIDENCE_CATEGORIES = frozenset({"operator-authorization", "repaired-systemic-cause"})
TOPOLOGY_MODES = frozenset({"dag", "stack"})
MAX_RETRIES = 2
STOP_EXIT_CODE = 3

STATE_FILE = "state.json"
LOG_FILE = "events.jsonl"
STATUS_FILE = "status.md"
FRONTIER_FILE = "frontier.json"
LOCK_FILE = ".state.lock"
REQUIRED_DIRECTORIES = ("briefs", "proofs", "inbox")


class StateError(RuntimeError):
    """A deterministic contract or authorization failure."""


_THREAD_LOCKS: dict[str, threading.Lock] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _text(value: Any, label: str, *, empty: bool = False, limit: int = 4_096) -> str:
    if not isinstance(value, str):
        raise StateError(f"{label} must be a string")
    clean = value.strip()
    if not empty and not clean:
        raise StateError(f"{label} must not be empty")
    if "\x00" in clean:
        raise StateError(f"{label} must not contain NUL")
    if len(clean) > limit:
        raise StateError(f"{label} exceeds {limit} characters")
    return clean


def _timestamp(value: Any, label: str) -> str:
    clean = _text(value, label, limit=64)
    try:
        datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StateError(f"{label} must be an ISO-8601 timestamp") from exc
    return clean


def _sha(value: Any) -> str:
    clean = _text(value, "SHA", limit=64).lower()
    if len(clean) not in {40, 64} or any(char not in "0123456789abcdef" for char in clean):
        raise StateError("SHA must be a full 40- or 64-character hexadecimal object ID")
    return clean


def _optional_sha(value: Any, label: str = "head SHA") -> str:
    if value is None or value == "":
        return ""
    try:
        return _sha(value)
    except StateError as exc:
        raise StateError(f"{label}: {exc}") from exc


def _pr(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise StateError("PR must be a positive integer")
    return value


def _optional_pr(value: Any) -> int | None:
    return None if value is None or value == "" else _pr(value)


def _relative_path(value: Any, label: str) -> str:
    clean = _text(value, label, empty=True)
    if not clean:
        return ""
    candidate = Path(clean)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise StateError(f"{label} must be a relative path without '..'")
    return clean


def _dependencies(value: Sequence[str] | None, unit_id: str) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise StateError("dependencies must be a sequence of unit ids")
    clean = [_text(item, "dependency", limit=200) for item in value]
    if unit_id in clean:
        raise StateError("a unit cannot depend on itself")
    if len(set(clean)) != len(clean):
        raise StateError("dependencies must not contain duplicates")
    return clean


def _json_value(value: Any, label: str = "metadata") -> Any:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise StateError(f"{label} must be JSON data") from exc
    if len(encoded) > 16_384:
        raise StateError(f"{label} exceeds 16384 characters")
    return decoded


def _token_digest(token: str, salt_hex: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", token.encode("utf-8"), bytes.fromhex(salt_hex), 120_000).hex()


def _reject_symlink(path: Path, label: str) -> None:
    try:
        linked = path.is_symlink()
    except OSError as exc:
        raise StateError(f"cannot inspect {label}: {exc}") from exc
    if linked:
        raise StateError(f"{label} must not be a symlink")


def _ensure_directory(path: Path, label: str) -> None:
    _reject_symlink(path, label)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StateError(f"cannot create {label}: {exc}") from exc
    _reject_symlink(path, label)
    if not path.is_dir():
        raise StateError(f"{label} must be a directory")


def _safe_open(path: Path, flags: int, mode: int, label: str) -> int:
    _reject_symlink(path, label)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags | nofollow, mode)
    except OSError as exc:
        raise StateError(f"cannot open {label}: {exc}") from exc
    try:
        opened = os.fstat(descriptor)
        try:
            current = os.lstat(path)
        except OSError as exc:
            raise StateError(f"cannot inspect {label} after opening: {exc}") from exc
        if statmod.S_ISLNK(current.st_mode) or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise StateError(f"{label} changed while opening")
        if not statmod.S_ISREG(opened.st_mode):
            raise StateError(f"{label} must be a regular file")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _atomic_write(path: Path, text: str) -> None:
    _ensure_directory(path.parent, "state directory")
    _reject_symlink(path, path.name)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            temporary = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    encoded = (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    _ensure_directory(path.parent, "state directory")
    descriptor = _safe_open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600, path.name)
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _locked(directory: Path) -> Iterator[None]:
    _ensure_directory(directory, "state directory")
    os.chmod(directory, 0o700)
    process_lock = _THREAD_LOCKS.setdefault(str(directory.resolve()), threading.Lock())
    with process_lock:
        descriptor = _safe_open(directory / LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o600, "state lock")
        try:
            os.fchmod(descriptor, 0o600)
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def _validate_writer(writer: Any) -> None:
    if not isinstance(writer, dict) or not all(isinstance(writer.get(key), str) for key in ("salt", "digest")):
        raise StateError("state writer token metadata is invalid")
    try:
        valid = writer.get("algorithm") == "pbkdf2-hmac-sha256/120000" and len(bytes.fromhex(writer["salt"])) == 16 and len(bytes.fromhex(writer["digest"])) == 32
    except ValueError:
        valid = False
    if not valid:
        raise StateError("state writer token metadata is invalid")


def _topological_order(units: dict[str, dict[str, Any]]) -> list[str]:
    pending = {unit_id: len(unit["dependencies"]) for unit_id, unit in units.items()}
    reverse: dict[str, list[str]] = {unit_id: [] for unit_id in units}
    for unit_id, unit in units.items():
        for dependency in unit["dependencies"]:
            if dependency not in units:
                raise StateError(f"unit {unit_id} has unknown dependency {dependency}")
            reverse[dependency].append(unit_id)
    available = sorted(unit_id for unit_id, count in pending.items() if count == 0)
    ordered: list[str] = []
    while available:
        unit_id = available.pop(0)
        ordered.append(unit_id)
        for child in sorted(reverse[unit_id]):
            pending[child] -= 1
            if pending[child] == 0:
                available.append(child)
                available.sort()
    if len(ordered) != len(units):
        raise StateError("unit dependencies contain a cycle")
    return ordered


def _stack_ids(value: Sequence[str] | None) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise StateError("stack ids must be a sequence of unit ids")
    clean = [_text(item, "stack unit id", limit=200) for item in value]
    if len(set(clean)) != len(clean):
        raise StateError("stack ids must not contain duplicates")
    return clean


def _validate_topology(value: Any, units: dict[str, dict[str, Any]]) -> None:
    required = {"mode", "stack_ids", "frozen"}
    if not isinstance(value, dict) or set(value) != required or value.get("mode") not in TOPOLOGY_MODES or not isinstance(value.get("frozen"), bool):
        raise StateError("state topology is invalid")
    stack_ids = _stack_ids(value["stack_ids"])
    assert stack_ids is not None
    if not value["frozen"]:
        if value["mode"] != "dag" or stack_ids:
            raise StateError("unconfigured topology must be an empty dag")
        return
    if value["mode"] == "dag":
        if stack_ids:
            raise StateError("dag topology must not contain stack ids")
        return
    if not stack_ids or set(stack_ids) != set(units) or len(stack_ids) != len(units):
        raise StateError("stack topology must contain every unit exactly once")
    for index, unit_id in enumerate(stack_ids):
        expected = [] if index == 0 else [stack_ids[index - 1]]
        if units[unit_id]["dependencies"] != expected:
            raise StateError("stack topology must be a single linear predecessor chain")


def _validate_lease(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict) or set(value) != {"holder", "issued_at", "expires_at", "evidence"}:
        raise StateError("unit lease is invalid")
    _text(value["holder"], "lease holder", limit=200)
    issued = _timestamp(value["issued_at"], "lease issued_at")
    expires = _timestamp(value["expires_at"], "lease expires_at")
    if datetime.fromisoformat(expires.replace("Z", "+00:00")) <= datetime.fromisoformat(issued.replace("Z", "+00:00")):
        raise StateError("unit lease must expire after issuance")
    _text(value["evidence"], "lease evidence", empty=True)


def _validate_liveness(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict) or set(value) != {"actor", "observed_at", "evidence"}:
        raise StateError("unit liveness is invalid")
    _text(value["actor"], "liveness actor", limit=200)
    _timestamp(value["observed_at"], "liveness observed_at")
    _text(value["evidence"], "liveness evidence", empty=True)


def _validate_unit(unit_id: str, unit: Any) -> None:
    required = {
        "contract_version", "id", "state", "track", "dependencies", "owner", "branch", "worktree", "pr",
        "head_sha", "brief", "proof", "note", "attempt", "retry_count", "retry_history", "lease", "liveness",
        "created_at", "created_by", "updated_at", "updated_by",
    }
    if not isinstance(unit, dict) or set(unit) != required or unit.get("contract_version") != CONTRACT_VERSION or unit.get("id") != unit_id:
        raise StateError("state contains an invalid unit")
    if unit["state"] not in UNIT_STATES:
        raise StateError("state contains an invalid unit state")
    _text(unit["track"], "unit track", limit=200)
    if not isinstance(unit["dependencies"], list):
        raise StateError("unit dependencies are invalid")
    _dependencies(unit["dependencies"], unit_id)
    for name, limit in (("owner", 500), ("branch", 500), ("worktree", 4096), ("proof", 4096), ("note", 4096)):
        _text(unit[name], name, empty=True, limit=limit)
    _relative_path(unit["brief"], "brief")
    _optional_pr(unit["pr"])
    _optional_sha(unit["head_sha"])
    if isinstance(unit["attempt"], bool) or not isinstance(unit["attempt"], int) or unit["attempt"] < 1:
        raise StateError("unit attempt is invalid")
    if isinstance(unit["retry_count"], bool) or not isinstance(unit["retry_count"], int) or not 0 <= unit["retry_count"] <= MAX_RETRIES:
        raise StateError("unit retry count is invalid")
    if unit["attempt"] != unit["retry_count"] + 1 or not isinstance(unit["retry_history"], list) or len(unit["retry_history"]) != unit["retry_count"]:
        raise StateError("unit retry history is invalid")
    retry_ids: set[str] = set()
    for retry in unit["retry_history"]:
        if not isinstance(retry, dict) or set(retry) != {"id", "reason", "timestamp", "actor"}:
            raise StateError("unit retry history is invalid")
        retry_id = _text(retry["id"], "retry id", limit=200)
        if retry_id in retry_ids:
            raise StateError("unit retry history is invalid")
        retry_ids.add(retry_id)
        _text(retry["reason"], "retry reason")
        _timestamp(retry["timestamp"], "retry timestamp")
        _text(retry["actor"], "retry actor", limit=200)
    _validate_lease(unit["lease"])
    _validate_liveness(unit["liveness"])
    for name in ("created_at", "updated_at"):
        _timestamp(unit[name], name)
    for name in ("created_by", "updated_by"):
        _text(unit[name], name, limit=200)


def _validate_gate(gate_id: str, gate: Any) -> None:
    required = {"contract_version", "id", "state", "reason", "created_at", "created_by", "updated_at", "updated_by"}
    if not isinstance(gate, dict) or set(gate) != required or gate.get("contract_version") != CONTRACT_VERSION or gate.get("id") != gate_id or gate.get("state") not in GATE_STATES:
        raise StateError("state contains an invalid gate")
    _text(gate["reason"], "gate reason", empty=True)
    for name in ("created_at", "updated_at"):
        _timestamp(gate[name], name)
    for name in ("created_by", "updated_by"):
        _text(gate[name], name, limit=200)


def _validate_verification(key: str, record: Any, units: dict[str, dict[str, Any]]) -> None:
    required = {"contract_version", "key", "pr", "sha", "verdict", "proof", "unit", "attempt", "created_at", "created_by", "updated_at", "updated_by"}
    if not isinstance(record, dict) or set(record) != required:
        raise StateError("state contains an invalid verification")
    pr = _pr(record.get("pr"))
    sha = _sha(record.get("sha"))
    if record.get("contract_version") != CONTRACT_VERSION or record.get("key") != key or key != f"{pr}@{sha}":
        raise StateError("state contains an invalid verification")
    if record.get("verdict") not in PR_VERDICTS:
        raise StateError("state contains an invalid verification verdict")
    _text(record["proof"], "verification proof", empty=True)
    unit_id = _text(record["unit"], "verification unit", limit=200)
    if unit_id not in units:
        raise StateError("verification links to an unknown unit")
    if isinstance(record["attempt"], bool) or not isinstance(record["attempt"], int) or record["attempt"] < 1:
        raise StateError("state contains an invalid verification")
    for name in ("created_at", "updated_at"):
        _timestamp(record[name], name)
    for name in ("created_by", "updated_by"):
        _text(record[name], name, limit=200)


def _validate_reconciliation(value: Any) -> None:
    if value is None:
        return
    required = {"classification", "note", "actor", "timestamp", "unit_state"}
    if not isinstance(value, dict) or set(value) != required or value.get("classification") not in RECONCILIATION_CLASSES:
        raise StateError("inbox reconciliation is invalid")
    _text(value["note"], "reconciliation note", empty=True)
    _text(value["actor"], "reconciliation actor", limit=200)
    _timestamp(value["timestamp"], "reconciliation timestamp")
    if value["unit_state"] is not None and value["unit_state"] not in RECONCILIATION_UNIT_STATES:
        raise StateError("inbox reconciliation is invalid")


def _validate_inbox_event(event_id: str, event: Any, units: dict[str, dict[str, Any]]) -> None:
    required = {"id", "unit", "report", "metadata", "head_sha", "received_at", "received_by", "drained_at", "drained_by", "reconciliation"}
    if not isinstance(event, dict) or set(event) != required or event.get("id") != event_id:
        raise StateError("state contains an invalid inbox event")
    _text(event_id, "event id", limit=200)
    if event.get("unit") not in units:
        raise StateError("inbox event has an unknown unit")
    _text(event["report"], "inbox report", empty=True)
    _json_value(event["metadata"])
    _optional_sha(event["head_sha"], "inbox head SHA")
    _timestamp(event["received_at"], "inbox received_at")
    _text(event["received_by"], "inbox received_by", limit=200)
    if (event["drained_at"] is None) != (event["drained_by"] is None):
        raise StateError("inbox drain metadata is invalid")
    if event["drained_at"] is not None:
        _timestamp(event["drained_at"], "inbox drained_at")
        _text(event["drained_by"], "inbox drained_by", limit=200)
    _validate_reconciliation(event["reconciliation"])


def _stop_facts(value: Any, label: str) -> dict[str, str]:
    required = {"reason", "timestamp", "actor"}
    if not isinstance(value, dict) or set(value) != required:
        raise StateError(f"{label} is invalid")
    return {
        "reason": _text(value["reason"], f"{label} reason"),
        "timestamp": _timestamp(value["timestamp"], f"{label} timestamp"),
        "actor": _text(value["actor"], f"{label} actor", limit=200),
    }


def _validate_stop_history(history: Any, stop: Any) -> None:
    if not isinstance(history, list):
        raise StateError("state stop history must be a list")
    active: dict[str, str] | None = None
    for item in history:
        if not isinstance(item, dict) or not isinstance(item.get("event"), str):
            raise StateError("state stop history is invalid")
        if item["event"] == "stop":
            if set(item) != {"event", "reason", "timestamp", "actor"} or active is not None:
                raise StateError("state stop history is invalid")
            active = _stop_facts({key: item[key] for key in ("reason", "timestamp", "actor")}, "stop history")
        elif item["event"] == "release-stop":
            required = {"event", "reason", "evidence_category", "evidence", "timestamp", "actor", "released_stop"}
            if set(item) != required or active is None:
                raise StateError("state stop history is invalid")
            _text(item["reason"], "release reason")
            if item["evidence_category"] not in STOP_RELEASE_EVIDENCE_CATEGORIES:
                raise StateError("release evidence category is invalid")
            _text(item["evidence"], "release evidence")
            _timestamp(item["timestamp"], "release timestamp")
            _text(item["actor"], "release actor", limit=200)
            released = _stop_facts(item["released_stop"], "released stop")
            if released != active:
                raise StateError("release does not match the active stop")
            active = None
        else:
            raise StateError("state stop history is invalid")
    required_stop = {"contract_version", "requested", "reason", "timestamp", "actor"}
    if not isinstance(stop, dict) or set(stop) != required_stop or stop.get("contract_version") != CONTRACT_VERSION or not isinstance(stop.get("requested"), bool):
        raise StateError("state stop record is invalid")
    if stop["requested"]:
        current = _stop_facts({key: stop[key] for key in ("reason", "timestamp", "actor")}, "stop")
        if current != active:
            raise StateError("active stop does not match stop history")
    elif stop["reason"] is not None or stop["timestamp"] is not None or stop["actor"] is not None or active is not None:
        raise StateError("state stop record is invalid")


def _validate_state(value: Any) -> dict[str, Any]:
    required = {"contract_version", "revision", "created_at", "created_by", "updated_at", "updated_by", "writer", "gates", "units", "verifications", "decisions", "inbox", "stop", "stop_history", "topology"}
    if not isinstance(value, dict) or set(value) != required or value.get("contract_version") != CONTRACT_VERSION:
        raise StateError("state contract version is unsupported")
    if isinstance(value.get("revision"), bool) or not isinstance(value.get("revision"), int) or value["revision"] < 0:
        raise StateError("state revision is invalid")
    for name in ("created_at", "updated_at"):
        _timestamp(value.get(name), name)
    for name in ("created_by", "updated_by"):
        _text(value.get(name), name, limit=200)
    _validate_writer(value["writer"])
    for name in ("gates", "units", "verifications", "decisions", "inbox"):
        if not isinstance(value.get(name), dict):
            raise StateError(f"state {name} must be an object")
    for gate_id, gate in value["gates"].items():
        if not isinstance(gate_id, str):
            raise StateError("state contains an invalid gate")
        _validate_gate(gate_id, gate)
    for unit_id, unit in value["units"].items():
        if not isinstance(unit_id, str):
            raise StateError("state contains an invalid unit")
        _validate_unit(unit_id, unit)
    _topological_order(value["units"])
    _validate_topology(value["topology"], value["units"])
    for key, record in value["verifications"].items():
        if not isinstance(key, str):
            raise StateError("state contains an invalid verification")
        _validate_verification(key, record, value["units"])
    for decision_id, decision in value["decisions"].items():
        required_decision = {"contract_version", "id", "outcome", "rationale", "timestamp", "actor"}
        if not isinstance(decision_id, str) or not isinstance(decision, dict) or set(decision) != required_decision or decision.get("contract_version") != CONTRACT_VERSION or decision.get("id") != decision_id:
            raise StateError("state contains an invalid decision")
        _text(decision["outcome"], "decision outcome")
        _text(decision["rationale"], "decision rationale", empty=True)
        _timestamp(decision["timestamp"], "decision timestamp")
        _text(decision["actor"], "decision actor", limit=200)
    for event_id, event in value["inbox"].items():
        if not isinstance(event_id, str):
            raise StateError("state contains an invalid inbox event")
        _validate_inbox_event(event_id, event, value["units"])
    _validate_stop_history(value["stop_history"], value["stop"])
    return value


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StateError(f"state is not initialized at {path.parent}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"cannot read valid state: {exc}") from exc
    return _validate_state(raw)


def _public_state(root: dict[str, Any]) -> dict[str, Any]:
    public = copy.deepcopy(root)
    public.pop("writer", None)
    return public


def _counts(records: dict[str, dict[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(record[field] for record in records.values()).items()))


def _has_current_passing_verdict(root: dict[str, Any], unit_id: str) -> bool:
    unit = root["units"][unit_id]
    pr, sha = unit["pr"], unit["head_sha"]
    if pr is None or not sha:
        return False
    verification = root["verifications"].get(f"{pr}@{sha}")
    return bool(
        verification
        and verification["unit"] == unit_id
        and verification["verdict"] in {"PASS", "PASS+NOTES"}
    )


def _frontier(root: dict[str, Any]) -> dict[str, Any]:
    units = root["units"]
    ordered = _topological_order(units)
    ready: list[str] = []
    blocked: list[str] = []
    blocked_reasons: dict[str, str] = {}
    for unit_id in ordered:
        unit = units[unit_id]
        if unit["state"] == "landed":
            continue
        reasons: list[str] = []
        if root["stop"]["requested"]:
            reasons.append("program-stopped")
        if unit["state"] == "blocked":
            reasons.append("unit-blocked")
        reasons.extend(f"waiting-for:{dependency}" for dependency in unit["dependencies"] if units[dependency]["state"] != "landed")
        if reasons:
            blocked.append(unit_id)
            blocked_reasons[unit_id] = ",".join(reasons)
        elif unit["state"] == "ready":
            ready.append(unit_id)
    landed = [unit_id for unit_id in ordered if units[unit_id]["state"] == "landed"]
    unintegrated = [unit_id for unit_id in ordered if units[unit_id]["state"] != "landed"]
    verified_ready: list[str] = []
    if not root["stop"]["requested"]:
        for unit_id in ordered:
            if _has_current_passing_verdict(root, unit_id) and all(
                _has_current_passing_verdict(root, dependency) for dependency in units[unit_id]["dependencies"]
            ):
                verified_ready.append(unit_id)
    contiguous_verified: list[str] | None = None
    contiguous_verified_complete: bool | None = None
    lowest_unintegrated: str | None = None
    contiguous_landed: list[str] | None = None
    contiguous_complete: bool | None = None
    topology = root["topology"]
    if topology["mode"] == "stack":
        contiguous_landed = []
        for unit_id in topology["stack_ids"]:
            if units[unit_id]["state"] != "landed":
                break
            contiguous_landed.append(unit_id)
        lowest_unintegrated = next(
            (unit_id for unit_id in topology["stack_ids"] if units[unit_id]["state"] != "landed"),
            None,
        )
        contiguous_complete = len(contiguous_landed) == len(topology["stack_ids"])
        contiguous_verified = []
        if not root["stop"]["requested"]:
            for unit_id in topology["stack_ids"]:
                if not _has_current_passing_verdict(root, unit_id):
                    break
                predecessor = units[unit_id]["dependencies"]
                if predecessor and predecessor[0] not in contiguous_verified:
                    break
                contiguous_verified.append(unit_id)
        contiguous_verified_complete = len(contiguous_verified) == len(topology["stack_ids"])
    return {
        "contract_version": CONTRACT_VERSION,
        "generation": root["revision"],
        "ordered_targets": ordered,
        "heads": {unit_id: units[unit_id]["head_sha"] for unit_id in ordered if units[unit_id]["head_sha"]},
        "ready": ready,
        "blocked": blocked,
        "blocked_reasons": blocked_reasons,
        "landed": landed,
        "unintegrated": unintegrated,
        "all_landed": not unintegrated,
        "lowest_unintegrated": lowest_unintegrated,
        "contiguous_landed": contiguous_landed,
        "contiguous_complete": contiguous_complete,
        "contiguous_verified": contiguous_verified,
        "contiguous_verified_complete": contiguous_verified_complete,
        "verified_ready": verified_ready,
        "topology_mode": topology["mode"],
        "stack_ids": copy.deepcopy(topology["stack_ids"]),
        "stop_requested": root["stop"]["requested"],
    }


def _summary(root: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "revision": root["revision"],
        "created_at": root["created_at"],
        "updated_at": root["updated_at"],
        "updated_by": root["updated_by"],
        "stop": {**copy.deepcopy(root["stop"]), "history_count": len(root["stop_history"])},
        "counts": {
            "gates": _counts(root["gates"], "state"),
            "units": _counts(root["units"], "state"),
            "verifications": len(root["verifications"]),
            "decisions": len(root["decisions"]),
            "inbox": len(root["inbox"]),
            "retries": sum(unit["retry_count"] for unit in root["units"].values()),
        },
        "attention": {
            "gates": sorted(key for key, gate in root["gates"].items() if gate["state"] in {"pending", "blocked"}),
            "units": sorted(key for key, unit in root["units"].items() if unit["state"] not in TERMINAL_UNIT_STATES),
        },
        "frontier": _frontier(root),
    }


def _markdown_cell(value: Any) -> str:
    if value is None or value == "":
        return "none"
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _status_markdown(root: dict[str, Any]) -> str:
    summary = _summary(root)
    frontier = summary["frontier"]
    stop = root["stop"]
    lines = [
        "# CodexStack program status", "", f"- Contract: `{CONTRACT_VERSION}`", f"- Revision: {root['revision']}",
        f"- Updated: {root['updated_at']} by {_markdown_cell(root['updated_by'])}",
        f"- Stop requested: {'yes' if stop['requested'] else 'no'}",
    ]
    if stop["requested"]:
        lines.append(f"- Stop reason: {_markdown_cell(stop['reason'])}")
    contiguous_landed = frontier["contiguous_landed"]
    contiguous_verified = frontier["contiguous_verified"]
    lines.extend([
        "", "## Frontier", "", f"- Topology: {frontier['topology_mode']}",
        f"- Lowest unintegrated: {_markdown_cell(frontier['lowest_unintegrated']) if frontier['topology_mode'] == 'stack' else 'not applicable'}",
        f"- Ready: {', '.join(frontier['ready']) or 'none'}", f"- Blocked: {', '.join(frontier['blocked']) or 'none'}",
        f"- Landed: {', '.join(frontier['landed']) or 'none'}",
        f"- Unintegrated: {', '.join(frontier['unintegrated']) or 'none'}",
        f"- All landed: {'yes' if frontier['all_landed'] else 'no'}",
        f"- Contiguous landed: {', '.join(contiguous_landed) if contiguous_landed is not None else 'not applicable'}",
        f"- Contiguous verified: {', '.join(contiguous_verified) if contiguous_verified is not None else 'not applicable'}",
        f"- Verified ready: {', '.join(frontier['verified_ready']) or 'none'}", "", "## Counts", "",
    ])
    for family in ("gates", "units"):
        rendered = ", ".join(f"{key}={value}" for key, value in summary["counts"][family].items()) or "none"
        lines.append(f"- {family.title()}: {rendered}")
    lines.extend([
        f"- Verifications: {summary['counts']['verifications']}", f"- Decisions: {summary['counts']['decisions']}",
        f"- Inbox events: {summary['counts']['inbox']}", f"- Retries: {summary['counts']['retries']}", "", "## Gates", "",
        "| Gate | State | Reason | Updated by | Updated |", "| --- | --- | --- | --- | --- |",
    ])
    for key in sorted(root["gates"]):
        row = root["gates"][key]
        lines.append(f"| {_markdown_cell(key)} | {row['state']} | {_markdown_cell(row['reason'])} | {_markdown_cell(row['updated_by'])} | {row['updated_at']} |")
    if not root["gates"]:
        lines.append("| none | none | none | none | none |")
    lines.extend([
        "", "## Units", "",
        "| Unit | State | Track | Owner | Dependencies | Branch | Worktree | PR | Head SHA | Brief | Attempt | Updated |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for key in sorted(root["units"]):
        row = root["units"][key]
        lines.append(
            f"| {_markdown_cell(key)} | {row['state']} | {_markdown_cell(row['track'])} | {_markdown_cell(row['owner'])} | "
            f"{_markdown_cell(', '.join(row['dependencies']))} | {_markdown_cell(row['branch'])} | {_markdown_cell(row['worktree'])} | "
            f"{_markdown_cell(row['pr'])} | {_markdown_cell(row['head_sha'])} | {_markdown_cell(row['brief'])} | {row['attempt']} | {row['updated_at']} |"
        )
    if not root["units"]:
        lines.append("| none | none | none | none | none | none | none | none | none | none | none | none |")
    lines.extend(["", "## Exact-head verifications", "", "| PR | SHA | Verdict | Proof | Updated |", "| --- | --- | --- | --- | --- |"])
    for key in sorted(root["verifications"]):
        row = root["verifications"][key]
        lines.append(f"| #{row['pr']} | `{row['sha']}` | {_markdown_cell(row['verdict'])} | {_markdown_cell(row['proof'])} | {row['updated_at']} |")
    if not root["verifications"]:
        lines.append("| none | none | none | none | none |")
    lines.extend(["", "## Decisions", "", "| Decision | Outcome | Rationale | Actor | Timestamp |", "| --- | --- | --- | --- | --- |"])
    for key in sorted(root["decisions"]):
        row = root["decisions"][key]
        lines.append(f"| {_markdown_cell(key)} | {_markdown_cell(row['outcome'])} | {_markdown_cell(row['rationale'])} | {_markdown_cell(row['actor'])} | {row['timestamp']} |")
    if not root["decisions"]:
        lines.append("| none | none | none | none | none |")
    return "\n".join(lines) + "\n"


def _write_derived(directory: Path, root: dict[str, Any]) -> None:
    _atomic_json(directory / FRONTIER_FILE, _frontier(root))
    _atomic_write(directory / STATUS_FILE, _status_markdown(root))


Mutator = Callable[[dict[str, Any], str, str], tuple[dict[str, Any], bool]]


class StateStore:
    """Read state freely; mutate only with the initialized writer token."""

    def __init__(self, directory: str | os.PathLike[str], token: str | None = None) -> None:
        raw = os.fspath(directory)
        if not raw.strip():
            raise StateError("state directory must not be empty")
        self.directory = Path(raw).expanduser()
        self.token = token

    @classmethod
    def initialize(cls, directory: str | os.PathLike[str], actor: str, token: str | None = None) -> tuple["StateStore", str]:
        clean_actor = _text(actor, "actor", limit=200)
        writer_token = _text(token if token is not None else secrets.token_urlsafe(32), "writer token", limit=1_024)
        store = cls(directory, writer_token)
        timestamp = _utc_now()
        salt = secrets.token_hex(16)
        root: dict[str, Any] = {
            "contract_version": CONTRACT_VERSION, "revision": 0, "created_at": timestamp, "created_by": clean_actor,
            "updated_at": timestamp, "updated_by": clean_actor,
            "writer": {"algorithm": "pbkdf2-hmac-sha256/120000", "salt": salt, "digest": _token_digest(writer_token, salt)},
            "gates": {}, "units": {}, "verifications": {}, "decisions": {}, "inbox": {},
            "stop": {"contract_version": CONTRACT_VERSION, "requested": False, "reason": None, "timestamp": None, "actor": None},
            "stop_history": [],
            "topology": {"mode": "dag", "stack_ids": [], "frozen": False},
        }
        with _locked(store.directory):
            if any((store.directory / name).exists() or (store.directory / name).is_symlink() for name in (STATE_FILE, LOG_FILE, STATUS_FILE, FRONTIER_FILE)):
                raise StateError(f"state is already initialized at {store.directory}")
            for name in REQUIRED_DIRECTORIES:
                child = store.directory / name
                _ensure_directory(child, f"required directory {name}")
                os.chmod(child, 0o700)
            _validate_state(root)
            _atomic_json(store.directory / STATE_FILE, root)
            _append_jsonl(store.directory / LOG_FILE, {"contract_version": CONTRACT_VERSION, "revision": 0, "timestamp": timestamp, "actor": clean_actor, "event": "init", "data": {"directory": str(store.directory)}})
            _write_derived(store.directory, root)
        return store, writer_token

    def _validate_layout(self) -> None:
        _reject_symlink(self.directory, "state directory")
        if not self.directory.is_dir():
            raise StateError("state directory must be a directory")
        for name in REQUIRED_DIRECTORIES:
            child = self.directory / name
            _reject_symlink(child, f"required directory {name}")
            if not child.is_dir():
                raise StateError(f"required directory {name} is missing")
        for name in (STATE_FILE, LOG_FILE, STATUS_FILE, FRONTIER_FILE, LOCK_FILE):
            _reject_symlink(self.directory / name, name)

    def _load(self) -> dict[str, Any]:
        self._validate_layout()
        return _load_json(self.directory / STATE_FILE)

    def _authorize(self, root: dict[str, Any]) -> None:
        if self.token is None:
            raise StateError("writer token is required for this command")
        if not isinstance(self.token, str):
            raise StateError("writer token is invalid")
        actual = _token_digest(self.token, root["writer"]["salt"])
        if not secrets.compare_digest(actual, root["writer"]["digest"]):
            raise StateError("writer token is invalid")

    def _mutate(self, actor: str, event: str, mutator: Mutator, *, allow_after_stop: bool = False) -> dict[str, Any]:
        clean_actor = _text(actor, "actor", limit=200)
        with _locked(self.directory):
            root = self._load()
            self._authorize(root)
            if root["stop"]["requested"] and not allow_after_stop:
                raise StateError("stop blocks product-progress mutations; only explicit reconciliation metadata is permitted")
            timestamp = _utc_now()
            result, changed = mutator(root, timestamp, clean_actor)
            if not changed:
                return copy.deepcopy(result)
            root["revision"] += 1
            root["updated_at"] = timestamp
            root["updated_by"] = clean_actor
            _validate_state(root)
            _atomic_json(self.directory / STATE_FILE, root)
            _append_jsonl(self.directory / LOG_FILE, {"contract_version": CONTRACT_VERSION, "revision": root["revision"], "timestamp": timestamp, "actor": clean_actor, "event": event, "data": copy.deepcopy(result)})
            _write_derived(self.directory, root)
            return copy.deepcopy(result)

    def gate(self, gate_id: str, state: str, actor: str, reason: str = "") -> dict[str, Any]:
        clean_id, clean_state, clean_reason = _text(gate_id, "gate id", limit=200), _text(state, "gate state", limit=30), _text(reason, "gate reason", empty=True)
        if clean_state not in GATE_STATES:
            raise StateError(f"gate state must be one of: {', '.join(sorted(GATE_STATES))}")

        def update(root: dict[str, Any], timestamp: str, clean_actor: str) -> tuple[dict[str, Any], bool]:
            previous = root["gates"].get(clean_id)
            if previous and previous["state"] == clean_state and previous["reason"] == clean_reason:
                return previous, False
            record = {"contract_version": CONTRACT_VERSION, "id": clean_id, "state": clean_state, "reason": clean_reason, "created_at": previous["created_at"] if previous else timestamp, "created_by": previous["created_by"] if previous else clean_actor, "updated_at": timestamp, "updated_by": clean_actor}
            root["gates"][clean_id] = record
            return record, True
        return self._mutate(actor, "gate", update)

    def unit(self, unit_id: str, state: str, actor: str, *, track: str | None = None, dependencies: Sequence[str] | None = None, owner: str | None = None, branch: str | None = None, worktree: str | None = None, pr: int | None = None, head_sha: str | None = None, head: str | None = None, brief: str | None = None, proof: str | None = None, note: str | None = None) -> dict[str, Any]:
        clean_id, clean_state = _text(unit_id, "unit id", limit=200), _text(state, "unit state", limit=30)
        if clean_state not in UNIT_STATES:
            raise StateError(f"unit state must be one of: {', '.join(sorted(UNIT_STATES))}")
        if head_sha is not None and head is not None and _optional_sha(head_sha) != _optional_sha(head):
            raise StateError("head and head_sha must match when both are supplied")
        supplied: dict[str, Any] = {}
        if track is not None:
            supplied["track"] = _text(track, "track", limit=200)
        clean_dependencies = _dependencies(dependencies, clean_id)
        if clean_dependencies is not None:
            supplied["dependencies"] = clean_dependencies
        for name, value, limit in (("owner", owner, 500), ("branch", branch, 500), ("worktree", worktree, 4096), ("proof", proof, 4096), ("note", note, 4096)):
            if value is not None:
                supplied[name] = _text(value, name, empty=True, limit=limit)
        if brief is not None:
            supplied["brief"] = _relative_path(brief, "brief")
        if pr is not None:
            supplied["pr"] = _optional_pr(pr)
        if head_sha is not None or head is not None:
            supplied["head_sha"] = _optional_sha(head_sha if head_sha is not None else head)

        def update(root: dict[str, Any], timestamp: str, clean_actor: str) -> tuple[dict[str, Any], bool]:
            previous = root["units"].get(clean_id)
            if previous is None and root["topology"]["mode"] == "stack" and root["topology"]["frozen"]:
                raise StateError("cannot add a unit after stack topology is frozen")
            if previous is not None and clean_state not in UNIT_TRANSITIONS[previous["state"]]:
                raise StateError(f"illegal unit transition: {previous['state']} -> {clean_state}")
            if previous is not None and previous["state"] in TERMINAL_UNIT_STATES:
                if clean_state != previous["state"] or any(previous[name] != value for name, value in supplied.items()):
                    raise StateError(f"terminal unit {clean_id} is immutable")
                return previous, False
            defaults = {"track": "default", "dependencies": [], "owner": "", "branch": "", "worktree": "", "pr": None, "head_sha": "", "brief": "", "proof": "", "note": ""}
            fields = {name: supplied.get(name, previous[name] if previous is not None else default) for name, default in defaults.items()}
            if previous is not None:
                for name in ("track", "dependencies"):
                    if name in supplied and supplied[name] != previous[name]:
                        raise StateError(f"unit {name} is immutable once declared")
                if previous["state"] in {"verified", "landed"} and fields["head_sha"] != previous["head_sha"]:
                    raise StateError("a verified unit head cannot change without a new unit lifecycle")
            if previous is not None and previous["state"] == clean_state and all(previous[name] == value for name, value in fields.items()):
                return previous, False
            record = {
                "contract_version": CONTRACT_VERSION, "id": clean_id, "state": clean_state, **fields,
                "attempt": previous["attempt"] if previous else 1, "retry_count": previous["retry_count"] if previous else 0,
                "retry_history": copy.deepcopy(previous["retry_history"]) if previous else [],
                "lease": copy.deepcopy(previous["lease"]) if previous and clean_state == "running" else None,
                "liveness": copy.deepcopy(previous["liveness"]) if previous else None,
                "created_at": previous["created_at"] if previous else timestamp, "created_by": previous["created_by"] if previous else clean_actor,
                "updated_at": timestamp, "updated_by": clean_actor,
            }
            root["units"][clean_id] = record
            return record, True
        return self._mutate(actor, "unit", update)

    def verify(self, pr: int, sha: str, verdict: str, actor: str, *, proof: str = "", unit: str = "") -> dict[str, Any]:
        clean_pr, clean_sha, clean_verdict = _pr(pr), _sha(sha), _text(verdict, "verdict", limit=30)
        if clean_verdict not in PR_VERDICTS:
            raise StateError(f"verdict must be one of: {', '.join(sorted(PR_VERDICTS))}")
        clean_proof, clean_unit, key = _text(proof, "proof", empty=True), _text(unit, "unit", empty=True, limit=200), f"{clean_pr}@{clean_sha}"

        def update(root: dict[str, Any], timestamp: str, clean_actor: str) -> tuple[dict[str, Any], bool]:
            if not clean_unit:
                raise StateError("verification unit is required")
            linked_unit = root["units"].get(clean_unit)
            if linked_unit is None:
                raise StateError(f"verification unit {clean_unit} is unknown")
            if linked_unit["pr"] != clean_pr or linked_unit["head_sha"] != clean_sha:
                raise StateError("verification PR and SHA must exactly match the linked unit")
            previous = root["verifications"].get(key)
            facts = {"verdict": clean_verdict, "proof": clean_proof, "unit": clean_unit}
            if previous and all(previous[name] == value for name, value in facts.items()):
                return previous, False
            record = {"contract_version": CONTRACT_VERSION, "key": key, "pr": clean_pr, "sha": clean_sha, **facts, "attempt": previous["attempt"] + 1 if previous else 1, "created_at": previous["created_at"] if previous else timestamp, "created_by": previous["created_by"] if previous else clean_actor, "updated_at": timestamp, "updated_by": clean_actor}
            root["verifications"][key] = record
            return record, True
        return self._mutate(actor, "verify", update)

    def decision(self, decision_id: str, outcome: str, actor: str, rationale: str = "") -> dict[str, Any]:
        clean_id, clean_outcome, clean_rationale = _text(decision_id, "decision id", limit=200), _text(outcome, "decision outcome"), _text(rationale, "rationale", empty=True)

        def update(root: dict[str, Any], timestamp: str, clean_actor: str) -> tuple[dict[str, Any], bool]:
            previous = root["decisions"].get(clean_id)
            if previous:
                if previous["outcome"] == clean_outcome and previous["rationale"] == clean_rationale:
                    return previous, False
                raise StateError(f"decision {clean_id} is immutable and already exists")
            record = {"contract_version": CONTRACT_VERSION, "id": clean_id, "outcome": clean_outcome, "rationale": clean_rationale, "timestamp": timestamp, "actor": clean_actor}
            root["decisions"][clean_id] = record
            return record, True
        return self._mutate(actor, "decision", update)

    def topology(self, mode: str, actor: str, *, stack_ids: Sequence[str] | None = None, ordered_ids: Sequence[str] | None = None) -> dict[str, Any]:
        clean_mode = _text(mode, "topology mode", limit=30)
        if clean_mode not in TOPOLOGY_MODES:
            raise StateError(f"topology mode must be one of: {', '.join(sorted(TOPOLOGY_MODES))}")
        supplied_stack = _stack_ids(stack_ids)
        supplied_order = _stack_ids(ordered_ids)
        if supplied_stack is not None and supplied_order is not None and supplied_stack != supplied_order:
            raise StateError("stack_ids and ordered_ids must match when both are supplied")
        clean_stack_ids = supplied_stack if supplied_stack is not None else supplied_order
        if clean_mode == "stack" and clean_stack_ids is None:
            raise StateError("stack topology requires explicit stack ids")
        if clean_mode == "dag" and clean_stack_ids:
            raise StateError("dag topology must not contain stack ids")
        clean_stack_ids = clean_stack_ids or []

        def update(root: dict[str, Any], timestamp: str, clean_actor: str) -> tuple[dict[str, Any], bool]:
            previous = root["topology"]
            candidate = {"mode": clean_mode, "stack_ids": clean_stack_ids, "frozen": True}
            if previous["frozen"]:
                if previous == candidate:
                    return previous, False
                raise StateError("topology is frozen and cannot be reordered or changed")
            root["topology"] = candidate
            return candidate, True
        return self._mutate(actor, "topology", update)

    def set_topology(self, mode: str, actor: str, *, stack_ids: Sequence[str] | None = None, ordered_ids: Sequence[str] | None = None) -> dict[str, Any]:
        """Compatibility alias for explicit topology configuration."""
        return self.topology(mode, actor, stack_ids=stack_ids, ordered_ids=ordered_ids)

    def retry(self, unit_id: str, actor: str, reason: str, *, retry_id: str | None = None) -> dict[str, Any]:
        clean_id, clean_reason = _text(unit_id, "unit id", limit=200), _text(reason, "retry reason")
        supplied_retry_id = _text(retry_id, "retry id", limit=200) if retry_id is not None else None

        def update(root: dict[str, Any], timestamp: str, clean_actor: str) -> tuple[dict[str, Any], bool]:
            previous = root["units"].get(clean_id)
            if previous is None:
                raise StateError(f"unit {clean_id} is unknown")
            event_id = supplied_retry_id or f"attempt-{previous['attempt'] + 1}:{clean_reason}"
            if previous["state"] != "failed":
                known_retry = any(item["id"] == event_id for item in previous["retry_history"])
                implicit_repeat = supplied_retry_id is None and bool(previous["retry_history"]) and previous["retry_history"][-1]["reason"] == clean_reason
                if known_retry or implicit_repeat:
                    return previous, False
                raise StateError("only a failed unit can be retried")
            if previous["retry_count"] >= MAX_RETRIES:
                raise StateError(f"unit retry limit of {MAX_RETRIES} has been reached")
            if any(item["id"] == event_id for item in previous["retry_history"]):
                raise StateError("retry id was already used")
            record = copy.deepcopy(previous)
            record.update({"state": "ready", "attempt": previous["attempt"] + 1, "retry_count": previous["retry_count"] + 1, "retry_history": previous["retry_history"] + [{"id": event_id, "reason": clean_reason, "timestamp": timestamp, "actor": clean_actor}], "lease": None, "updated_at": timestamp, "updated_by": clean_actor})
            root["units"][clean_id] = record
            return record, True
        return self._mutate(actor, "retry", update)

    def lease(self, unit_id: str, actor: str, ttl_seconds: int, *, evidence: str = "") -> dict[str, Any]:
        clean_id, clean_evidence = _text(unit_id, "unit id", limit=200), _text(evidence, "lease evidence", empty=True)
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 86_400:
            raise StateError("lease ttl_seconds must be an integer from 1 through 86400")

        def update(root: dict[str, Any], timestamp: str, clean_actor: str) -> tuple[dict[str, Any], bool]:
            previous = root["units"].get(clean_id)
            if previous is None:
                raise StateError(f"unit {clean_id} is unknown")
            if previous["state"] != "running":
                raise StateError("only a running unit can hold a lease")
            issued = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            expires = (issued + timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds").replace("+00:00", "Z")
            record = copy.deepcopy(previous)
            record.update({"lease": {"holder": clean_actor, "issued_at": timestamp, "expires_at": expires, "evidence": clean_evidence}, "liveness": {"actor": clean_actor, "observed_at": timestamp, "evidence": clean_evidence}, "updated_at": timestamp, "updated_by": clean_actor})
            root["units"][clean_id] = record
            return record, True
        return self._mutate(actor, "lease", update)

    def lease_status(self, unit_id: str) -> dict[str, Any]:
        clean_id = _text(unit_id, "unit id", limit=200)
        root = self._load()
        unit = root["units"].get(clean_id)
        if unit is None:
            raise StateError(f"unit {clean_id} is unknown")
        lease = copy.deepcopy(unit["lease"])
        expired = lease is not None and datetime.now(timezone.utc) >= datetime.fromisoformat(lease["expires_at"].replace("Z", "+00:00"))
        return {"contract_version": CONTRACT_VERSION, "revision": root["revision"], "unit": clean_id, "lease": lease, "liveness": copy.deepcopy(unit["liveness"]), "expired": expired}

    def enqueue(self, event_id: str, unit_id: str, actor: str, *, report: str = "", metadata: Any = None, head_sha: str | None = None) -> dict[str, Any]:
        clean_event_id, clean_unit_id = _text(event_id, "event id", limit=200), _text(unit_id, "unit id", limit=200)
        clean_report, clean_metadata, clean_head_sha = _text(report, "inbox report", empty=True), _json_value({} if metadata is None else metadata), _optional_sha(head_sha, "inbox head SHA")

        def update(root: dict[str, Any], timestamp: str, clean_actor: str) -> tuple[dict[str, Any], bool]:
            if clean_unit_id not in root["units"]:
                raise StateError(f"inbox unit {clean_unit_id} is unknown")
            previous = root["inbox"].get(clean_event_id)
            facts = {"unit": clean_unit_id, "report": clean_report, "metadata": clean_metadata, "head_sha": clean_head_sha}
            if previous is not None:
                if all(previous[name] == value for name, value in facts.items()):
                    return previous, False
                raise StateError(f"inbox event {clean_event_id} is immutable")
            record = {"id": clean_event_id, **facts, "received_at": timestamp, "received_by": clean_actor, "drained_at": None, "drained_by": None, "reconciliation": None}
            root["inbox"][clean_event_id] = record
            return record, True
        return self._mutate(actor, "inbox-enqueue", update)

    def drain(self, actor: str, *, limit: int | None = None) -> dict[str, Any]:
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
            raise StateError("drain limit must be a positive integer")

        def update(root: dict[str, Any], timestamp: str, clean_actor: str) -> tuple[dict[str, Any], bool]:
            pending = sorted((event for event in root["inbox"].values() if event["drained_at"] is None), key=lambda event: (event["received_at"], event["id"]))
            if limit is not None:
                pending = pending[:limit]
            if not pending:
                return {"events": [], "count": 0}, False
            drained: list[dict[str, Any]] = []
            for event in pending:
                event["drained_at"] = timestamp
                event["drained_by"] = clean_actor
                drained.append(copy.deepcopy(event))
            return {"events": drained, "count": len(drained)}, True
        return self._mutate(actor, "inbox-drain", update)

    def reconcile(self, event_id: str, classification: str, actor: str, *, note: str = "", unit_state: str | None = None, unit_id: str | None = None, report: str = "", metadata: Any = None, head_sha: str | None = None) -> dict[str, Any]:
        clean_event_id, clean_classification, clean_note = _text(event_id, "event id", limit=200), _text(classification, "reconciliation classification", limit=30), _text(note, "reconciliation note", empty=True)
        if clean_classification not in RECONCILIATION_CLASSES:
            raise StateError(f"reconciliation classification must be one of: {', '.join(sorted(RECONCILIATION_CLASSES))}")
        if unit_state is not None and unit_state not in RECONCILIATION_UNIT_STATES:
            raise StateError(f"reconciliation unit state must be one of: {', '.join(sorted(RECONCILIATION_UNIT_STATES))}")
        clean_unit_id = _text(unit_id, "unit id", limit=200) if unit_id is not None else None
        clean_report = _text(report, "inbox report", empty=True)
        clean_metadata = _json_value({} if metadata is None else metadata)
        clean_head_sha = _optional_sha(head_sha, "inbox head SHA")

        def update(root: dict[str, Any], timestamp: str, clean_actor: str) -> tuple[dict[str, Any], bool]:
            event = root["inbox"].get(clean_event_id)
            if event is None:
                if clean_unit_id is None:
                    raise StateError(f"inbox event {clean_event_id} is unknown; unit_id is required for late reconciliation")
                if clean_unit_id not in root["units"]:
                    raise StateError(f"inbox unit {clean_unit_id} is unknown")
                event = {"id": clean_event_id, "unit": clean_unit_id, "report": clean_report, "metadata": clean_metadata, "head_sha": clean_head_sha, "received_at": timestamp, "received_by": clean_actor, "drained_at": timestamp, "drained_by": clean_actor, "reconciliation": None}
                root["inbox"][clean_event_id] = event
            elif clean_unit_id is not None and event["unit"] != clean_unit_id:
                raise StateError(f"inbox event {clean_event_id} belongs to unit {event['unit']}")
            expected = {"classification": clean_classification, "note": clean_note, "actor": clean_actor, "timestamp": timestamp, "unit_state": unit_state}
            previous = event["reconciliation"]
            if previous is not None:
                if {key: previous[key] for key in ("classification", "note", "actor", "unit_state")} == {key: expected[key] for key in ("classification", "note", "actor", "unit_state")}:
                    return event, False
                raise StateError(f"inbox event {clean_event_id} is already reconciled")
            if unit_state is not None:
                unit = root["units"][event["unit"]]
                if unit["state"] in TERMINAL_UNIT_STATES and unit["state"] != unit_state:
                    raise StateError(f"terminal unit {event['unit']} cannot be reconciled to {unit_state}")
                if unit["state"] != unit_state:
                    if unit_state not in UNIT_TRANSITIONS[unit["state"]]:
                        raise StateError(f"illegal reconciliation transition: {unit['state']} -> {unit_state}")
                    unit.update({"state": unit_state, "lease": None, "updated_at": timestamp, "updated_by": clean_actor})
            event["reconciliation"] = expected
            if event["drained_at"] is None:
                event["drained_at"] = timestamp
                event["drained_by"] = clean_actor
            return event, True
        return self._mutate(actor, "inbox-reconcile", update, allow_after_stop=True)

    def stop(self, reason: str, actor: str) -> dict[str, Any]:
        clean_reason = _text(reason, "stop reason")

        def update(root: dict[str, Any], timestamp: str, clean_actor: str) -> tuple[dict[str, Any], bool]:
            previous = root["stop"]
            if previous["requested"]:
                if previous["reason"] == clean_reason:
                    return previous, False
                raise StateError("stop is already requested and cannot be replaced")
            record = {"contract_version": CONTRACT_VERSION, "requested": True, "reason": clean_reason, "timestamp": timestamp, "actor": clean_actor}
            root["stop"] = record
            root["stop_history"].append({"event": "stop", "reason": clean_reason, "timestamp": timestamp, "actor": clean_actor})
            return record, True
        return self._mutate(actor, "stop", update, allow_after_stop=True)

    def release_stop(self, reason: str, actor: str, *, evidence_category: str = "", evidence: str = "") -> dict[str, Any]:
        clean_reason = _text(reason, "release reason")
        clean_category = _text(evidence_category, "release evidence category", limit=100)
        if clean_category not in STOP_RELEASE_EVIDENCE_CATEGORIES:
            raise StateError(
                f"release evidence category must be one of: {', '.join(sorted(STOP_RELEASE_EVIDENCE_CATEGORIES))}"
            )
        clean_evidence = _text(evidence, "release evidence")

        def update(root: dict[str, Any], timestamp: str, clean_actor: str) -> tuple[dict[str, Any], bool]:
            active = root["stop"]
            if not active["requested"]:
                raise StateError("stop is not requested")
            released_stop = {key: active[key] for key in ("reason", "timestamp", "actor")}
            record = {
                "event": "release-stop",
                "reason": clean_reason,
                "evidence_category": clean_category,
                "evidence": clean_evidence,
                "timestamp": timestamp,
                "actor": clean_actor,
                "released_stop": released_stop,
            }
            root["stop_history"].append(record)
            root["stop"] = {"contract_version": CONTRACT_VERSION, "requested": False, "reason": None, "timestamp": None, "actor": None}
            return record, True
        return self._mutate(actor, "release-stop", update, allow_after_stop=True)

    def check_stop(self) -> dict[str, Any]:
        root = self._load()
        return {
            "contract_version": CONTRACT_VERSION,
            "revision": root["revision"],
            **copy.deepcopy(root["stop"]),
            "history": copy.deepcopy(root["stop_history"]),
        }

    def frontier(self) -> dict[str, Any]:
        return _frontier(self._load())

    def status(self) -> dict[str, Any]:
        return _summary(self._load())

    def snapshot(self) -> dict[str, Any]:
        return _public_state(self._load())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True, help="user-supplied state directory")
    parser.add_argument("--actor", default=os.environ.get("CODEXSTACK_ACTOR"))
    parser.add_argument("--token", default=os.environ.get("CODEXSTACK_WRITER_TOKEN"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="initialize state and print the writer token once")
    gate = commands.add_parser("gate", help="upsert a workflow gate")
    gate.add_argument("id")
    gate.add_argument("state", choices=sorted(GATE_STATES))
    gate.add_argument("--reason", default="")
    unit = commands.add_parser("unit", help="record a bounded work unit")
    unit.add_argument("id")
    unit.add_argument("state", choices=sorted(UNIT_STATES))
    unit.add_argument("--track")
    unit.add_argument("--depends-on", dest="dependencies", action="append")
    unit.add_argument("--owner")
    unit.add_argument("--branch")
    unit.add_argument("--worktree")
    unit.add_argument("--pr", type=int)
    unit.add_argument("--head-sha")
    unit.add_argument("--brief")
    unit.add_argument("--proof")
    unit.add_argument("--note")
    topology = commands.add_parser("topology", help="freeze dag or linear-stack topology")
    topology.add_argument("mode", choices=sorted(TOPOLOGY_MODES))
    topology.add_argument("--stack-id", dest="stack_ids", action="append")
    verify = commands.add_parser("verify", help="record evidence for an exact PR head")
    verify.add_argument("pr", type=int)
    verify.add_argument("sha")
    verify.add_argument("verdict", choices=sorted(PR_VERDICTS))
    verify.add_argument("--proof", default="")
    verify.add_argument("--unit", required=True)
    decision = commands.add_parser("decision", help="append an immutable decision")
    decision.add_argument("id")
    decision.add_argument("outcome")
    decision.add_argument("--rationale", default="")
    retry = commands.add_parser("retry", help="bounded retry of a failed unit")
    retry.add_argument("unit")
    retry.add_argument("--reason", required=True)
    retry.add_argument("--retry-id")
    lease = commands.add_parser("lease", help="record an expiring running-unit lease")
    lease.add_argument("unit")
    lease.add_argument("--ttl", type=int, required=True)
    lease.add_argument("--evidence", default="")
    lease_status = commands.add_parser("lease-status", help="read a unit lease without polling")
    lease_status.add_argument("unit")
    enqueue = commands.add_parser("enqueue", help="atomically record one inbox event")
    enqueue.add_argument("event_id")
    enqueue.add_argument("unit")
    enqueue.add_argument("--report", default="")
    enqueue.add_argument("--metadata-json", default="{}")
    enqueue.add_argument("--head-sha")
    drain = commands.add_parser("drain", help="atomically claim pending inbox events")
    drain.add_argument("--limit", type=int)
    reconcile = commands.add_parser("reconcile", help="record reconciliation metadata for one event")
    reconcile.add_argument("event_id")
    reconcile.add_argument("classification", choices=sorted(RECONCILIATION_CLASSES))
    reconcile.add_argument("--note", default="")
    reconcile.add_argument("--unit-state", choices=sorted(RECONCILIATION_UNIT_STATES))
    reconcile.add_argument("--unit")
    reconcile.add_argument("--report", default="")
    reconcile.add_argument("--metadata-json", default="{}")
    reconcile.add_argument("--head-sha")
    stop = commands.add_parser("stop", help="request a sticky cooperative stop")
    stop.add_argument("--reason", required=True)
    release = commands.add_parser("release-stop", help="release a stop with explicit audited evidence")
    release.add_argument("--reason", required=True)
    release.add_argument("--evidence-category", choices=sorted(STOP_RELEASE_EVIDENCE_CATEGORIES), required=True)
    release.add_argument("--evidence", required=True)
    commands.add_parser("check-stop", help="exit 3 when a stop was requested")
    commands.add_parser("frontier", help="print derived dependency frontier")
    commands.add_parser("status", help="print a derived state summary")
    return parser


def _actor(value: str | None) -> str:
    if value is None:
        raise StateError("--actor or CODEXSTACK_ACTOR is required for mutations")
    return value


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "init":
            store, writer_token = StateStore.initialize(arguments.dir, _actor(arguments.actor), arguments.token)
            result: dict[str, Any] = {"writer_token": writer_token, "status": store.status()}
        else:
            store = StateStore(arguments.dir, arguments.token)
            if arguments.command == "gate":
                result = store.gate(arguments.id, arguments.state, _actor(arguments.actor), arguments.reason)
            elif arguments.command == "unit":
                result = store.unit(arguments.id, arguments.state, _actor(arguments.actor), track=arguments.track, dependencies=arguments.dependencies, owner=arguments.owner, branch=arguments.branch, worktree=arguments.worktree, pr=arguments.pr, head_sha=arguments.head_sha, brief=arguments.brief, proof=arguments.proof, note=arguments.note)
            elif arguments.command == "topology":
                result = store.topology(arguments.mode, _actor(arguments.actor), stack_ids=arguments.stack_ids)
            elif arguments.command == "verify":
                result = store.verify(arguments.pr, arguments.sha, arguments.verdict, _actor(arguments.actor), proof=arguments.proof, unit=arguments.unit)
            elif arguments.command == "decision":
                result = store.decision(arguments.id, arguments.outcome, _actor(arguments.actor), arguments.rationale)
            elif arguments.command == "retry":
                result = store.retry(arguments.unit, _actor(arguments.actor), arguments.reason, retry_id=arguments.retry_id)
            elif arguments.command == "lease":
                result = store.lease(arguments.unit, _actor(arguments.actor), arguments.ttl, evidence=arguments.evidence)
            elif arguments.command == "lease-status":
                result = store.lease_status(arguments.unit)
            elif arguments.command == "enqueue":
                try:
                    metadata = json.loads(arguments.metadata_json)
                except json.JSONDecodeError as exc:
                    raise StateError("--metadata-json must contain JSON") from exc
                result = store.enqueue(arguments.event_id, arguments.unit, _actor(arguments.actor), report=arguments.report, metadata=metadata, head_sha=arguments.head_sha)
            elif arguments.command == "drain":
                result = store.drain(_actor(arguments.actor), limit=arguments.limit)
            elif arguments.command == "reconcile":
                try:
                    metadata = json.loads(arguments.metadata_json)
                except json.JSONDecodeError as exc:
                    raise StateError("--metadata-json must contain JSON") from exc
                result = store.reconcile(arguments.event_id, arguments.classification, _actor(arguments.actor), note=arguments.note, unit_state=arguments.unit_state, unit_id=arguments.unit, report=arguments.report, metadata=metadata, head_sha=arguments.head_sha)
            elif arguments.command == "stop":
                result = store.stop(arguments.reason, _actor(arguments.actor))
            elif arguments.command == "release-stop":
                result = store.release_stop(
                    arguments.reason,
                    _actor(arguments.actor),
                    evidence_category=arguments.evidence_category,
                    evidence=arguments.evidence,
                )
            elif arguments.command == "check-stop":
                result = store.check_stop()
            elif arguments.command == "frontier":
                result = store.frontier()
            elif arguments.command == "status":
                result = store.status()
            else:  # pragma: no cover - argparse prevents this branch.
                raise StateError(f"unknown command: {arguments.command}")
        print(json.dumps({"ok": True, "result": result}, sort_keys=True))
        return STOP_EXIT_CODE if arguments.command == "check-stop" and result["requested"] else 0
    except StateError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
