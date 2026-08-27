#!/usr/bin/env python3
"""Read-only, Git-derived worktree audit for CodexStack.

The helper inspects only paths returned by ``git worktree list``. It performs
no fetch, provider call, transcript search, scheduling, mutation, or deletion.
Current-use and PR facts may be supplied in one bounded JSON evidence document
or directly to :func:`audit_repository` as the same fields.

Evidence schema::

    {
      "contract_version": "codexstack.worktree-evidence.v1",
      "observed_at": 1700000000,
      "worktrees": [
        {
          "path": "/exact/path/from/git/worktree/list",
          "active": false,
          "pinned": false,
          "last_used_at": null,
          "pr": {"state": "NONE"}
        }
      ]
    }

PR states are ``OPEN``, ``CLOSED``, ``MERGED``, ``NONE``, or ``UNKNOWN``.
OPEN, CLOSED, and MERGED require a positive ``number`` and the exact current
``head_sha``. A ``safe`` result is advice, never permission to remove a tree.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import selectors
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable


CONTRACT_VERSION = "codexstack.worktree-audit.v1"
EVIDENCE_VERSION = "codexstack.worktree-evidence.v1"
MAX_EVIDENCE_BYTES = 1_048_576
MAX_EVIDENCE_ROWS = 256
MAX_WORKTREES = 256
MAX_GIT_OUTPUT = 8_388_608
MAX_PATH_CHARS = 4_096
MAX_SIZE_ENTRIES = 1_000_000
DEFAULT_SIZE_ENTRIES = 200_000
DEFAULT_EVIDENCE_AGE = 86_400
MAX_EVIDENCE_AGE = 2_592_000
RECENT_USE_SECONDS = 4 * 86_400
FUTURE_SKEW_SECONDS = 300
GIT_TIMEOUT_SECONDS = 30

SHA_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,254}\Z")
PR_STATES = {"OPEN", "CLOSED", "MERGED", "NONE", "UNKNOWN"}
HOLD_CODES = {
    "tracked_wip",
    "workspace_pinned",
    "workspace_active",
    "workspace_recently_used",
    "open_pr",
}
REVIEW_CODES = {
    "worktree_unavailable",
    "inspection_incomplete",
    "size_incomplete",
    "age_unknown",
    "use_evidence_missing",
    "merge_state_unknown",
    "unmerged_no_pr",
    "unmerged_closed_pr",
    "unmerged_pr_unknown",
}


class InputError(ValueError):
    """An input cannot safely identify a bounded audit target."""


class GitError(RuntimeError):
    """A local Git inspection did not complete within the contract."""


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise InputError(f"{label} must be an integer greater than or equal to {minimum}")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value.lower()):
        raise InputError(f"{label} must be a full 40- or 64-character hexadecimal object ID")
    return value.lower()


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise InputError(f"{label} must be a boolean")
    return value


def _path_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_PATH_CHARS:
        raise InputError(f"{label} must contain 1 to {MAX_PATH_CHARS} characters")
    if "\x00" in value or any(ord(character) < 32 for character in value):
        raise InputError(f"{label} contains a control character")
    return value


def _has_symlink_component(path: Path) -> bool:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False


def _repository_path(path_text: str, root: Path | None = None) -> Path:
    text = _path_text(path_text, "repository path")
    raw = Path(text)
    if ".." in raw.parts:
        raise InputError("repository path must not contain parent components")
    candidate = raw if raw.is_absolute() else (root or Path.cwd()) / raw
    if _has_symlink_component(candidate):
        raise InputError("repository path must not contain symlinks")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise InputError("repository path must name an accessible directory") from exc
    if not resolved.is_dir():
        raise InputError("repository path must name a directory")
    result = _git(resolved, ["rev-parse", "--show-toplevel"])
    if result[0] != 0:
        raise InputError("repository path is not inside a Git worktree")
    try:
        top = Path(result[1].decode("utf-8", "strict").strip())
    except UnicodeDecodeError as exc:
        raise InputError("Git repository path must be valid UTF-8") from exc
    if not top.is_absolute() or _has_symlink_component(top):
        raise InputError("Git returned an unsafe repository path")
    try:
        top = top.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise InputError("Git repository path is not accessible") from exc
    return top


def _safe_evidence_path(path_text: str, root: Path) -> tuple[Path, str]:
    text = _path_text(path_text, "evidence path")
    relative = Path(text)
    if relative.is_absolute():
        raise InputError("evidence path must be relative to the current directory")
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise InputError("evidence path must not contain dot or parent components")
    if any(part.startswith("-") for part in relative.parts):
        raise InputError("evidence path contains an unsafe component")
    try:
        base = root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise InputError("evidence root is not accessible") from exc
    candidate = base.joinpath(relative)
    cursor = base
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise InputError("evidence path must not contain symlinks")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(base)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise InputError("evidence path must name an existing file below the current directory") from exc
    return resolved, relative.as_posix()


def _no_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"evidence JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def load_evidence(path_text: str, root: Path | None = None) -> dict[str, Any]:
    """Read one bounded, regular JSON file without following symlinks."""
    path, _display = _safe_evidence_path(path_text, root or Path.cwd())
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise InputError(f"cannot open evidence file: {exc.strerror or exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise InputError("evidence path must name a regular file")
        if metadata.st_size > MAX_EVIDENCE_BYTES:
            raise InputError(f"evidence file exceeds {MAX_EVIDENCE_BYTES} bytes")
        chunks: list[bytes] = []
        remaining = MAX_EVIDENCE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
    finally:
        os.close(descriptor)
    if len(data) > MAX_EVIDENCE_BYTES:
        raise InputError(f"evidence file exceeds {MAX_EVIDENCE_BYTES} bytes")
    if b"\x00" in data:
        raise InputError("evidence file contains a NUL byte")
    try:
        text = data.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise InputError("evidence file must be valid UTF-8") from exc
    try:
        value = json.loads(text, object_pairs_hook=_no_duplicate_object)
    except InputError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise InputError("evidence file must contain valid bounded JSON") from exc
    if not isinstance(value, dict):
        raise InputError("evidence document must be an object")
    return value


def _git(cwd: Path, arguments: Iterable[str]) -> tuple[int, bytes, bytes]:
    command = [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.pager=cat",
        "-C",
        os.fspath(cwd),
        *arguments,
    ]
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
    except OSError as exc:
        raise GitError(f"local Git inspection failed: {exc}") from exc
    assert process.stdout is not None and process.stderr is not None
    streams = {process.stdout: bytearray(), process.stderr: bytearray()}
    selector = selectors.DefaultSelector()
    for stream in streams:
        selector.register(stream, selectors.EVENT_READ)
    deadline = time.monotonic() + GIT_TIMEOUT_SECONDS
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.wait()
                raise GitError(
                    f"local Git inspection exceeded {GIT_TIMEOUT_SECONDS} seconds"
                )
            events = selector.select(remaining)
            if not events and process.poll() is not None:
                events = [(key, selectors.EVENT_READ) for key in selector.get_map().values()]
            for key, _mask in events:
                stream = key.fileobj
                chunk = os.read(stream.fileno(), 65_536)
                if not chunk:
                    selector.unregister(stream)
                    stream.close()
                    continue
                streams[stream].extend(chunk)
                if sum(len(value) for value in streams.values()) > MAX_GIT_OUTPUT:
                    process.kill()
                    process.wait()
                    raise GitError(f"local Git output exceeds {MAX_GIT_OUTPUT} bytes")
        return_code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        raise GitError(
            f"local Git inspection exceeded {GIT_TIMEOUT_SECONDS} seconds"
        ) from exc
    finally:
        selector.close()
        for stream in streams:
            if not stream.closed:
                stream.close()
    return return_code, bytes(streams[process.stdout]), bytes(streams[process.stderr])


def _decode_git(value: bytes, label: str) -> str:
    try:
        return value.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise InputError(f"{label} returned by Git must be valid UTF-8") from exc


def _worktree_rows(repository: Path) -> list[dict[str, Any]]:
    code, output, _error = _git(repository, ["worktree", "list", "--porcelain", "-z"])
    if code != 0:
        raise GitError("git worktree list failed")
    sections = [section for section in output.split(b"\x00\x00") if section]
    if not sections:
        raise GitError("git worktree list returned no worktrees")
    if len(sections) > MAX_WORKTREES:
        raise InputError(f"repository has more than {MAX_WORKTREES} worktrees")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, section in enumerate(sections):
        fields = [field for field in section.split(b"\x00") if field]
        row: dict[str, Any] = {"main": index == 0}
        for field in fields:
            key, separator, raw_value = field.partition(b" ")
            name = _decode_git(key, "worktree metadata key")
            value = _decode_git(raw_value, f"worktree {name}") if separator else True
            row[name] = value
        path = row.get("worktree")
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise InputError("Git worktree list returned a non-absolute path")
        _path_text(path, "Git worktree path")
        if path in seen:
            raise InputError("Git worktree list returned a duplicate path")
        seen.add(path)
        head = row.get("HEAD")
        if isinstance(head, str) and set(head) != {"0"}:
            row["HEAD"] = _sha(head, f"HEAD for {path}")
        else:
            row["HEAD"] = None
        rows.append(row)
    return rows


def _validate_ref(value: str) -> str:
    if not isinstance(value, str) or not REF_RE.fullmatch(value):
        raise InputError("base ref contains unsafe characters")
    if (
        value.startswith("-")
        or value.endswith(("/", "."))
        or ".." in value
        or "//" in value
        or "@{" in value
        or any(part.startswith(".") for part in value.split("/"))
    ):
        raise InputError("base ref is not a safe Git ref")
    return value


def _resolve_base(repository: Path, base_ref: str) -> dict[str, Any]:
    ref = _validate_ref(base_ref)
    code, output, _error = _git(
        repository, ["rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"]
    )
    if code != 0:
        return {"ref": ref, "state": "unavailable", "sha": None}
    try:
        sha = _sha(_decode_git(output, "base ref").strip(), "base ref object ID")
    except InputError:
        return {"ref": ref, "state": "unavailable", "sha": None}
    return {"ref": ref, "state": "resolved", "sha": sha}


def _validate_evidence(
    value: dict[str, Any] | None,
    worktrees: list[dict[str, Any]],
    *,
    now: int,
    max_age: int,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    if value is None:
        return {}, {"provided": False, "observed_at": None, "age_seconds": None}
    if not isinstance(value, dict):
        raise InputError("evidence fields must be an object")
    allowed_top = {"contract_version", "observed_at", "worktrees"}
    extras = sorted(set(value) - allowed_top)
    if extras:
        raise InputError(f"evidence document contains unsupported field {extras[0]!r}")
    if value.get("contract_version") != EVIDENCE_VERSION:
        raise InputError(f"evidence contract_version must be {EVIDENCE_VERSION}")
    observed = _integer(value.get("observed_at"), "observed_at")
    if observed > now + FUTURE_SKEW_SECONDS:
        raise InputError("evidence observed_at is too far in the future")
    age = max(0, now - observed)
    if age > max_age:
        raise InputError(f"evidence is stale by {age - max_age} seconds")
    rows = value.get("worktrees")
    if not isinstance(rows, list):
        raise InputError("evidence worktrees must be an array")
    if len(rows) > MAX_EVIDENCE_ROWS:
        raise InputError(f"evidence contains more than {MAX_EVIDENCE_ROWS} worktrees")
    candidates = {row["worktree"]: row for row in worktrees if not row["main"]}
    normalized: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise InputError(f"worktrees[{index}] must be an object")
        allowed = {"path", "active", "pinned", "last_used_at", "pr"}
        extra = sorted(set(raw) - allowed)
        if extra:
            raise InputError(f"worktrees[{index}] contains unsupported field {extra[0]!r}")
        path = _path_text(raw.get("path"), f"worktrees[{index}].path")
        if not Path(path).is_absolute() or ".." in Path(path).parts:
            raise InputError(f"worktrees[{index}].path must be an exact absolute Git worktree path")
        if path not in candidates:
            raise InputError(f"worktrees[{index}].path is not an exact candidate path from Git")
        if path in normalized:
            raise InputError(f"duplicate evidence for worktree {path!r}")
        active = _boolean(raw.get("active"), f"worktrees[{index}].active")
        pinned = _boolean(raw.get("pinned"), f"worktrees[{index}].pinned")
        if "last_used_at" not in raw:
            raise InputError(f"worktrees[{index}].last_used_at is required; use null when absent")
        last_used = raw["last_used_at"]
        if last_used is not None:
            last_used = _integer(last_used, f"worktrees[{index}].last_used_at")
            if last_used > observed + FUTURE_SKEW_SECONDS:
                raise InputError(f"worktrees[{index}].last_used_at is newer than the evidence")
        pr_raw = raw.get("pr")
        if pr_raw is None:
            pr = {"state": "UNKNOWN", "number": None, "head_sha": None}
        else:
            if not isinstance(pr_raw, dict):
                raise InputError(f"worktrees[{index}].pr must be an object")
            extra_pr = sorted(set(pr_raw) - {"state", "number", "head_sha"})
            if extra_pr:
                raise InputError(f"worktrees[{index}].pr contains unsupported field {extra_pr[0]!r}")
            state = pr_raw.get("state")
            if state not in PR_STATES:
                raise InputError(f"worktrees[{index}].pr.state must be one of {sorted(PR_STATES)}")
            if state in {"OPEN", "CLOSED", "MERGED"}:
                number = _integer(pr_raw.get("number"), f"worktrees[{index}].pr.number", minimum=1)
                head = _sha(pr_raw.get("head_sha"), f"worktrees[{index}].pr.head_sha")
                candidate_head = candidates[path].get("HEAD")
                if head != candidate_head:
                    raise InputError(f"worktrees[{index}].pr.head_sha is stale for the current worktree head")
                pr = {"state": state, "number": number, "head_sha": head}
            else:
                if set(pr_raw) - {"state"}:
                    raise InputError(f"worktrees[{index}].pr {state} must not carry number or head_sha")
                pr = {"state": state, "number": None, "head_sha": None}
        normalized[path] = {
            "active": active,
            "pinned": pinned,
            "last_used_at": last_used,
            "pr": pr,
        }
    return normalized, {"provided": True, "observed_at": observed, "age_seconds": age}


def _apparent_size(path: Path, max_entries: int) -> tuple[int | None, bool, int]:
    try:
        root_stat = path.lstat()
    except OSError:
        return None, False, 0
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
        return None, False, 0
    total = root_stat.st_size
    entries = 0
    stack = [path]
    complete = True
    while stack:
        directory = stack.pop()
        try:
            children = os.scandir(directory)
        except OSError:
            complete = False
            continue
        with children:
            for entry in children:
                entries += 1
                if entries > max_entries:
                    return None, False, entries
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError:
                    complete = False
                    continue
                total += metadata.st_size
                if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
                    stack.append(Path(entry.path))
    return total, complete, entries


def _dirty(repository: Path) -> dict[str, Any]:
    code, output, _error = _git(
        repository, ["status", "--porcelain=v1", "-z", "--untracked-files=all"]
    )
    if code != 0:
        return {"kind": "unknown", "tracked": None, "untracked": None}
    records = output.split(b"\x00")
    tracked = 0
    untracked = 0
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 3 or record[2:3] != b" ":
            return {"kind": "unknown", "tracked": None, "untracked": None}
        status_code = record[:2]
        if status_code == b"??":
            untracked += 1
        elif status_code != b"!!":
            tracked += 1
            if b"R" in status_code or b"C" in status_code:
                if index >= len(records) or not records[index]:
                    return {"kind": "unknown", "tracked": None, "untracked": None}
                index += 1
    if tracked and untracked:
        kind = "mixed"
    elif tracked:
        kind = "wip"
    elif untracked:
        kind = "scratch"
    else:
        kind = "clean"
    return {"kind": kind, "tracked": tracked, "untracked": untracked}


def _remote(repository: Path, branch_ref: Any, head: str | None) -> dict[str, Any]:
    if not isinstance(branch_ref, str) or not branch_ref.startswith("refs/heads/"):
        return {"state": "detached", "ref": None, "ahead_by": None, "behind_by": None}
    branch = branch_ref.removeprefix("refs/heads/")
    code, output, _error = _git(
        repository, ["for-each-ref", "--format=%(upstream)", "--count=1", branch_ref]
    )
    upstream = _decode_git(output, "branch upstream").strip() if code == 0 else ""
    if not upstream:
        fallback = f"refs/remotes/origin/{branch}"
        exists, _output, _error = _git(repository, ["show-ref", "--verify", "--quiet", fallback])
        upstream = fallback if exists == 0 else ""
    if not upstream:
        return {"state": "no_remote", "ref": None, "ahead_by": None, "behind_by": None}
    if head is None:
        return {"state": "unknown", "ref": upstream, "ahead_by": None, "behind_by": None}
    code, output, _error = _git(
        repository, ["rev-list", "--left-right", "--count", f"{upstream}...{head}"]
    )
    if code != 0:
        return {"state": "unknown", "ref": upstream, "ahead_by": None, "behind_by": None}
    fields = _decode_git(output, "remote divergence").split()
    try:
        behind, ahead = (int(fields[0]), int(fields[1]))
    except (IndexError, ValueError):
        return {"state": "unknown", "ref": upstream, "ahead_by": None, "behind_by": None}
    if ahead == 0 and behind == 0:
        state = "pushed"
    elif ahead and not behind:
        state = "ahead"
    elif behind and not ahead:
        state = "behind"
    else:
        state = "diverged"
    return {"state": state, "ref": upstream, "ahead_by": ahead, "behind_by": behind}


def _age(repository: Path, head: str | None, now: int) -> tuple[int | None, int | None]:
    if head is None:
        return None, None
    code, output, _error = _git(repository, ["show", "-s", "--format=%ct", head])
    if code != 0:
        return None, None
    try:
        timestamp = int(_decode_git(output, "commit timestamp").strip())
    except (ValueError, InputError):
        return None, None
    return max(0, now - timestamp) // 86_400, timestamp


def _merge(repository: Path, head: str | None, base: dict[str, Any]) -> dict[str, Any]:
    if head is None or base["state"] != "resolved":
        return {"state": "unknown", "via": None}
    code, _output, _error = _git(repository, ["merge-base", "--is-ancestor", head, base["sha"]])
    if code == 0:
        return {"state": "merged", "via": "git_ancestor"}
    if code == 1:
        return {"state": "unmerged", "via": "git_ancestor"}
    return {"state": "unknown", "via": None}


def _reason(code: str, effect: str, **detail: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code, "effect": effect}
    result.update(detail)
    return result


def _classify(
    *,
    path: str,
    head: str | None,
    branch_ref: Any,
    base: dict[str, Any],
    evidence: dict[str, Any] | None,
    now: int,
    max_entries: int,
) -> dict[str, Any]:
    worktree = Path(path)
    accessible = worktree.exists() and worktree.is_dir() and not _has_symlink_component(worktree)
    if accessible:
        size, size_complete, size_entries = _apparent_size(worktree, max_entries)
        try:
            dirty = _dirty(worktree)
            remote = _remote(worktree, branch_ref, head)
            age_days, commit_time = _age(worktree, head, now)
            merge = _merge(worktree, head, base)
        except (GitError, InputError):
            dirty = {"kind": "unknown", "tracked": None, "untracked": None}
            remote = {"state": "unknown", "ref": None, "ahead_by": None, "behind_by": None}
            age_days, commit_time = None, None
            merge = {"state": "unknown", "via": None}
    else:
        size, size_complete, size_entries = None, False, 0
        dirty = {"kind": "unknown", "tracked": None, "untracked": None}
        remote = {"state": "unknown", "ref": None, "ahead_by": None, "behind_by": None}
        age_days, commit_time = None, None
        merge = {"state": "unknown", "via": None}

    branch = (
        branch_ref.removeprefix("refs/heads/")
        if isinstance(branch_ref, str) and branch_ref.startswith("refs/heads/")
        else None
    )
    if evidence is None:
        use = {
            "evidence": "missing",
            "active": None,
            "pinned": None,
            "last_used_at": None,
            "recent": None,
        }
        pr = {"state": "UNKNOWN", "number": None, "head_sha": None}
    else:
        last_used = evidence["last_used_at"]
        recent = last_used is not None and max(0, now - last_used) <= RECENT_USE_SECONDS
        use = {
            "evidence": "present",
            "active": evidence["active"],
            "pinned": evidence["pinned"],
            "last_used_at": last_used,
            "recent": recent,
        }
        pr = evidence["pr"]

    reasons: list[dict[str, Any]] = []
    if not accessible:
        reasons.append(_reason("worktree_unavailable", "review"))
    if not size_complete:
        reasons.append(
            _reason("size_incomplete", "review", entries_scanned=size_entries, limit=max_entries)
        )
    if dirty["kind"] == "unknown":
        reasons.append(_reason("inspection_incomplete", "review", surface="dirty"))
    elif dirty["tracked"]:
        reasons.append(_reason("tracked_wip", "hold", count=dirty["tracked"]))
    if dirty["untracked"]:
        reasons.append(_reason("untracked_scratch", "info", count=dirty["untracked"]))
    if age_days is None:
        reasons.append(_reason("age_unknown", "review"))

    if use["evidence"] == "missing":
        reasons.append(_reason("use_evidence_missing", "review"))
    else:
        if use["pinned"]:
            reasons.append(_reason("workspace_pinned", "hold"))
        if use["active"]:
            reasons.append(_reason("workspace_active", "hold"))
        if use["recent"]:
            reasons.append(
                _reason("workspace_recently_used", "hold", last_used_at=use["last_used_at"])
            )

    if pr["state"] == "OPEN":
        reasons.append(_reason("open_pr", "hold", number=pr["number"]))

    effective_merged = merge["state"] == "merged" or pr["state"] == "MERGED"
    if merge["state"] == "merged":
        reasons.append(_reason("git_merge_confirmed", "safe", base_ref=base["ref"]))
    elif pr["state"] == "MERGED":
        reasons.append(_reason("merged_pr_confirmed", "safe", number=pr["number"]))
    elif merge["state"] == "unknown":
        reasons.append(_reason("merge_state_unknown", "review", base_ref=base["ref"]))
    elif pr["state"] == "NONE":
        reasons.append(_reason("unmerged_no_pr", "review"))
    elif pr["state"] == "CLOSED":
        reasons.append(_reason("unmerged_closed_pr", "review", number=pr["number"]))
    elif pr["state"] == "UNKNOWN":
        reasons.append(_reason("unmerged_pr_unknown", "review"))

    codes = {reason["code"] for reason in reasons}
    if codes & HOLD_CODES:
        bucket = "hold"
    elif codes & REVIEW_CODES or not effective_merged:
        bucket = "review"
    else:
        bucket = "safe"
    return {
        "path": path,
        "head_sha": head,
        "branch": branch,
        "size_bytes": size,
        "size_complete": size_complete,
        "size_entries": size_entries,
        "age_days": age_days,
        "commit_time": commit_time,
        "merge": merge,
        "dirty": dirty,
        "remote": remote,
        "pr": pr,
        "use": use,
        "bucket": bucket,
        "reasons": reasons,
    }


def audit_repository(
    repository: str | Path = ".",
    *,
    evidence: dict[str, Any] | None = None,
    now: int | None = None,
    base_ref: str = "refs/remotes/origin/main",
    max_evidence_age: int = DEFAULT_EVIDENCE_AGE,
    max_size_entries: int = DEFAULT_SIZE_ENTRIES,
    root: Path | None = None,
) -> dict[str, Any]:
    """Return a deterministic read-only audit for all non-main worktrees."""
    observed_now = int(time.time()) if now is None else _integer(now, "now")
    evidence_age = _integer(max_evidence_age, "max_evidence_age", minimum=1)
    if evidence_age > MAX_EVIDENCE_AGE:
        raise InputError(f"max_evidence_age must not exceed {MAX_EVIDENCE_AGE}")
    size_limit = _integer(max_size_entries, "max_size_entries", minimum=1)
    if size_limit > MAX_SIZE_ENTRIES:
        raise InputError(f"max_size_entries must not exceed {MAX_SIZE_ENTRIES}")
    repo = _repository_path(os.fspath(repository), root=root)
    rows = _worktree_rows(repo)
    base = _resolve_base(repo, base_ref)
    evidence_rows, evidence_summary = _validate_evidence(
        evidence, rows, now=observed_now, max_age=evidence_age
    )
    candidates = [
        _classify(
            path=row["worktree"],
            head=row.get("HEAD"),
            branch_ref=row.get("branch"),
            base=base,
            evidence=evidence_rows.get(row["worktree"]),
            now=observed_now,
            max_entries=size_limit,
        )
        for row in rows
        if not row["main"]
    ]
    candidates.sort(
        key=lambda item: (
            -(item["size_bytes"] if isinstance(item["size_bytes"], int) else -1),
            item["path"],
        )
    )
    counts = {bucket: sum(row["bucket"] == bucket for row in candidates) for bucket in ("safe", "hold", "review")}
    return {
        "contract_version": CONTRACT_VERSION,
        "repository": os.fspath(repo),
        "main_worktree": rows[0]["worktree"],
        "base": base,
        "evidence": evidence_summary,
        "limits": {
            "max_evidence_age_seconds": evidence_age,
            "max_size_entries_per_worktree": size_limit,
        },
        "summary": {"candidates": len(candidates), **counts},
        "worktrees": candidates,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Classify Git-derived linked worktrees without fetching, scanning transcripts, "
            "calling a provider, changing state, or deleting anything."
        ),
        epilog=(
            "A safe bucket is advice only. Supply --evidence with explicit active, pinned, "
            "last-used, and optional PR facts before acting."
        ),
    )
    parser.add_argument("repository", nargs="?", default=".", help="repository path (default: current directory)")
    parser.add_argument("--evidence", help="relative path to a bounded JSON evidence document")
    parser.add_argument("--base-ref", default="refs/remotes/origin/main", help="already-fetched merge base ref")
    parser.add_argument("--now", type=int, help="epoch seconds for reproducible age and freshness results")
    parser.add_argument(
        "--max-evidence-age",
        type=int,
        default=DEFAULT_EVIDENCE_AGE,
        help=f"maximum evidence age in seconds (default: {DEFAULT_EVIDENCE_AGE})",
    )
    parser.add_argument(
        "--max-size-entries",
        type=int,
        default=DEFAULT_SIZE_ENTRIES,
        help=f"maximum filesystem entries sized per worktree (default: {DEFAULT_SIZE_ENTRIES})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    try:
        evidence = load_evidence(arguments.evidence) if arguments.evidence else None
        payload = audit_repository(
            arguments.repository,
            evidence=evidence,
            now=arguments.now,
            base_ref=arguments.base_ref,
            max_evidence_age=arguments.max_evidence_age,
            max_size_entries=arguments.max_size_entries,
        )
    except (InputError, GitError) as exc:
        print(
            json.dumps(
                {"contract_version": CONTRACT_VERSION, "error": str(exc)},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
