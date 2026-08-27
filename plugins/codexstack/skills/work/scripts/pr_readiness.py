#!/usr/bin/env python3
"""Classify already-fetched GitHub PR snapshots without side effects.

``status`` and ``babysit_ready`` preserve pstack's watcher policy. A clean PR
may finish babysitting with REVIEW_REQUIRED or no review decision, and GitHub
merge states such as BEHIND, BLOCKED, HAS_HOOKS, and UNSTABLE do not alone
prevent that result. BLOCKED is refused only when the exact-head rollup is
ERROR or FAILURE.

``provider_landing_gate_clear`` is deliberately narrower. It requires an open,
non-draft, blocker-free PR with exact-head clean CI, MERGEABLE plus CLEAN
provider evidence, and APPROVED review. A repository that explicitly has no
review requirement may set ``allow_unapproved`` for a null review decision.
This field is evidence only. It is not Land authority and is not a complete
merge-eligibility decision. On a stack result, merged rows are neutral and the
field means that every still-open row clears this narrow evidence gate.

The input boundary is stricter than pstack's live provider reader. Missing,
stale, malformed, or unrecognized evidence stays pending because this script
receives a snapshot and cannot refresh it. GitHub's explicit UNKNOWN merge
sentinels remain accepted by the babysitting policy, as they are upstream, but
never clear the provider landing gate. Every check and supplied rollup must
identify the exact ``head_sha``. A bounded ``{"stack": [...]}`` document is
classified bottom-to-top with the same tier-major stack ordering as pstack.
Queue operations freeze normalized owner, repository, PR identity, and order,
not commit identity. Every new queue observation is classified against its
current exact head, so a rebase or force-push invalidates old proof without
changing the frozen queue.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


CONTRACT_VERSION = "codexstack.pr-readiness.v1"
QUEUE_CONTRACT_VERSION = "codexstack.pr-queue.v1"
MAX_STACK_ROWS = 128
MAX_QUEUE_HISTORY = 256

MERGEABLE = {"MERGEABLE", "CONFLICTING", "UNKNOWN"}
MERGE_STATES = {
    "BEHIND",
    "BLOCKED",
    "CLEAN",
    "CONFLICTING",
    "DIRTY",
    "DRAFT",
    "HAS_HOOKS",
    "UNKNOWN",
    "UNSTABLE",
}
NONCONFLICT_MERGE_STATES = {
    "BEHIND",
    "BLOCKED",
    "CLEAN",
    "DRAFT",
    "HAS_HOOKS",
    "UNKNOWN",
    "UNSTABLE",
}
REVIEWS = {"APPROVED", "CHANGES_REQUESTED", "REVIEW_REQUIRED", None}
ROLLUPS = {"ERROR", "EXPECTED", "FAILURE", "PENDING", "SUCCESS", None}
PENDING_STATUSES = {
    "EXPECTED",
    "IN_PROGRESS",
    "PENDING",
    "QUEUED",
    "REQUESTED",
    "WAITING",
}
PASSING_CONCLUSIONS = {"NEUTRAL", "SKIPPED", "SUCCESS"}
FAILING_CONCLUSIONS = {
    "ACTION_REQUIRED",
    "CANCELLED",
    "FAILURE",
    "STALE",
    "STARTUP_FAILURE",
    "TIMED_OUT",
}
BLOCKER_TIERS = ("conflict", "threads", "failing_checks", "review_merge_gate")
OWNER_PART = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
REPO_PART = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


class InputError(ValueError):
    """The JSON shape cannot identify a bounded, exact revision snapshot."""


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError(f"{label} must be an object")
    return value


def _pr(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InputError("pr must be a positive integer")
    return value


def _sha(value: Any, label: str = "head_sha") -> str:
    if not isinstance(value, str):
        raise InputError(f"{label} must be a string")
    clean = value.lower()
    if len(clean) not in {40, 64} or any(
        character not in "0123456789abcdef" for character in clean
    ):
        raise InputError(
            f"{label} must be a full 40- or 64-character hexadecimal object ID"
        )
    return clean


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise InputError(f"{label} must be a boolean")
    return value


def _result(
    pr: int,
    head_sha: str,
    status: str,
    *,
    tier: str | None,
    kind: str,
    provider_landing_gate_clear: bool = False,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reason: dict[str, Any] = {"kind": kind}
    if tier is not None:
        reason["tier"] = tier
    if detail:
        reason.update(detail)
    return {
        "contract_version": CONTRACT_VERSION,
        "pr": pr,
        "head_sha": head_sha,
        "status": status,
        "babysit_ready": status in {"ready", "merged"},
        "provider_landing_gate_clear": provider_landing_gate_clear,
        "terminal": status in {"blocked", "merged", "ready"},
        "reason": reason,
    }


def _thread_count(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise InputError(
            "unresolved_threads must be a non-negative integer or an array"
        )
    if isinstance(value, int):
        if value < 0:
            raise InputError("unresolved_threads must not be negative")
        return value
    if isinstance(value, list):
        return len(value)
    raise InputError("unresolved_threads must be a non-negative integer or an array")


def _check_name(check: dict[str, Any], index: int) -> str:
    name = check.get("name")
    if not isinstance(name, str) or not name.strip():
        return f"check[{index}]"
    return name.strip()


def classify(value: Any) -> dict[str, Any]:
    """Return pstack-compatible babysitting status for one exact PR head."""
    snapshot = _object(value, "input")
    input_contract = snapshot.get("contract_version")
    if input_contract is not None and input_contract != CONTRACT_VERSION:
        raise InputError(f"contract_version must be {CONTRACT_VERSION}")
    pr = _pr(snapshot.get("pr"))
    head_sha = _sha(snapshot.get("head_sha"))
    state = snapshot.get("state")
    if state == "MERGED":
        return _result(pr, head_sha, "merged", tier=None, kind="already_merged")
    if state == "CLOSED":
        return _result(
            pr,
            head_sha,
            "blocked",
            tier="review_merge_gate",
            kind="closed_without_merge",
        )
    if state != "OPEN":
        return _result(
            pr,
            head_sha,
            "pending",
            tier="review_merge_gate",
            kind="unknown_pr_state",
            detail={"observed": state},
        )

    mergeable = snapshot.get("mergeable")
    merge_state = snapshot.get("merge_state_status")
    if mergeable == "CONFLICTING" or merge_state in {"CONFLICTING", "DIRTY"}:
        return _result(
            pr,
            head_sha,
            "blocked",
            tier="conflict",
            kind="merge_conflict",
            detail={"mergeable": mergeable, "merge_state_status": merge_state},
        )

    threads = _thread_count(snapshot.get("unresolved_threads"))
    if threads is None:
        return _result(
            pr,
            head_sha,
            "pending",
            tier="threads",
            kind="threads_unavailable",
        )
    if threads:
        return _result(
            pr,
            head_sha,
            "blocked",
            tier="threads",
            kind="unresolved_threads",
            detail={"count": threads},
        )

    checks_value = snapshot.get("checks")
    if checks_value is None:
        checks: list[Any] = []
    elif isinstance(checks_value, list):
        checks = checks_value
    else:
        raise InputError("checks must be an array")

    failures: list[dict[str, str]] = []
    pending: list[str] = []
    unknown: list[str] = []
    stale: list[str] = []
    passing: list[str] = []
    for index, raw_check in enumerate(checks):
        check = _object(raw_check, f"checks[{index}]")
        name = _check_name(check, index)
        try:
            exact_sha = _sha(check.get("head_sha"), f"checks[{index}].head_sha")
        except InputError:
            stale.append(name)
            continue
        if exact_sha != head_sha:
            stale.append(name)
            continue
        if check.get("kind") == "review_gate" or name == "Code Review Gate":
            continue
        status = check.get("status")
        conclusion = check.get("conclusion")
        if status in PENDING_STATUSES:
            pending.append(name)
        elif status == "COMPLETED" and conclusion in PASSING_CONCLUSIONS:
            passing.append(name)
        elif status == "COMPLETED" and conclusion in FAILING_CONCLUSIONS:
            failures.append({"name": name, "conclusion": conclusion})
        else:
            unknown.append(name)

    rollup_supplied = snapshot.get("head_rollup") is not None
    rollup_state: Any = None
    rollup_stale = False
    rollup_unknown = False
    if rollup_supplied:
        rollup = _object(snapshot["head_rollup"], "head_rollup")
        try:
            rollup_sha = _sha(rollup.get("head_sha"), "head_rollup.head_sha")
        except InputError:
            rollup_stale = True
        else:
            rollup_stale = rollup_sha != head_sha
        rollup_state = rollup.get("state")
        rollup_unknown = rollup_state not in ROLLUPS

    if failures:
        return _result(
            pr,
            head_sha,
            "blocked",
            tier="failing_checks",
            kind="checks_failed",
            detail={"checks": failures},
        )
    if (
        merge_state == "BLOCKED"
        and rollup_supplied
        and not rollup_stale
        and rollup_state in {"ERROR", "FAILURE"}
    ):
        return _result(
            pr,
            head_sha,
            "blocked",
            tier="failing_checks",
            kind="github_merge_refusal",
            detail={
                "merge_state_status": "BLOCKED",
                "head_rollup_state": rollup_state,
            },
        )

    review_present = "review_decision" in snapshot
    review = snapshot.get("review_decision")
    draft_present = "is_draft" in snapshot
    is_draft = (
        _boolean(snapshot["is_draft"], "is_draft") if draft_present else None
    )
    allow_draft = _boolean(snapshot.get("allow_draft", False), "allow_draft")
    allow_unapproved = _boolean(
        snapshot.get("allow_unapproved", False), "allow_unapproved"
    )
    if review_present and review not in REVIEWS:
        review_unknown = True
    else:
        review_unknown = not review_present

    ci_incomplete = bool(
        pending
        or stale
        or rollup_stale
        or unknown
        or rollup_unknown
        or not checks
        or (merge_state == "BLOCKED" and not rollup_supplied)
    )

    # pstack checks merge gates after failing CI but before waiting CI. Draft is
    # the sole exception and waits for pending evidence before reporting its gate.
    if review == "CHANGES_REQUESTED":
        return _result(
            pr,
            head_sha,
            "blocked",
            tier="review_merge_gate",
            kind="changes_requested",
        )
    if is_draft is True and not allow_draft and not ci_incomplete:
        return _result(
            pr,
            head_sha,
            "blocked",
            tier="review_merge_gate",
            kind="draft_pr",
        )

    if pending:
        return _result(
            pr,
            head_sha,
            "pending",
            tier="failing_checks",
            kind="checks_pending",
            detail={"checks": sorted(pending)},
        )
    if stale or rollup_stale:
        detail: dict[str, Any] = {"checks": sorted(stale)}
        if rollup_stale:
            detail["head_rollup"] = "not_for_current_head"
        return _result(
            pr,
            head_sha,
            "pending",
            tier="failing_checks",
            kind="stale_head_evidence",
            detail=detail,
        )
    if unknown or rollup_unknown:
        detail = {"checks": sorted(unknown)}
        if rollup_unknown:
            detail["head_rollup_state"] = rollup_state
        return _result(
            pr,
            head_sha,
            "pending",
            tier="failing_checks",
            kind="unknown_check_state",
            detail=detail,
        )
    if not checks:
        return _result(
            pr,
            head_sha,
            "pending",
            tier="failing_checks",
            kind="checks_unavailable",
        )
    if merge_state == "BLOCKED" and not rollup_supplied:
        return _result(
            pr,
            head_sha,
            "pending",
            tier="failing_checks",
            kind="head_rollup_unavailable",
        )

    if mergeable not in MERGEABLE or merge_state not in MERGE_STATES:
        return _result(
            pr,
            head_sha,
            "pending",
            tier="review_merge_gate",
            kind="unknown_merge_state",
            detail={"mergeable": mergeable, "merge_state_status": merge_state},
        )
    if mergeable not in {"MERGEABLE", "UNKNOWN"} or merge_state not in NONCONFLICT_MERGE_STATES:
        return _result(
            pr,
            head_sha,
            "pending",
            tier="review_merge_gate",
            kind="merge_state_unavailable",
            detail={"mergeable": mergeable, "merge_state_status": merge_state},
        )
    if not draft_present:
        return _result(
            pr,
            head_sha,
            "pending",
            tier="review_merge_gate",
            kind="draft_state_unavailable",
        )
    if review_unknown:
        return _result(
            pr,
            head_sha,
            "pending",
            tier="review_merge_gate",
            kind=(
                "unknown_review_decision"
                if review_present
                else "review_decision_unavailable"
            ),
            detail={"observed": review} if review_present else None,
        )

    provider_clear = bool(
        mergeable == "MERGEABLE"
        and merge_state == "CLEAN"
        and is_draft is False
        and (review == "APPROVED" or (review is None and allow_unapproved))
    )
    merge_basis = "rollup" if merge_state == "BLOCKED" else "merge_state"
    return {
        **_result(
            pr,
            head_sha,
            "ready",
            tier=None,
            kind="babysitting_complete",
            provider_landing_gate_clear=provider_clear,
        ),
        "proof": {
            "head_sha": head_sha,
            "passing_checks": sorted(passing),
            "unresolved_threads": 0,
            "mergeable": mergeable,
            "merge_state_status": merge_state,
            "github_merge_basis": merge_basis,
            "head_rollup_state": rollup_state if rollup_supplied else None,
            "review_decision": review,
            "approval": (
                "explicitly_not_required"
                if review is None and allow_unapproved
                else "provider_decision"
            ),
            "draft": "allowed" if is_draft else "not_draft",
        },
    }


def classify_stack(value: Any) -> dict[str, Any]:
    """Classify a nonempty bottom-to-top stack with tier-major precedence."""
    if not isinstance(value, list):
        raise InputError("stack must be an array")
    if not value:
        raise InputError("stack must be nonempty and ordered bottom-to-top")
    if len(value) > MAX_STACK_ROWS:
        raise InputError(f"stack must contain at most {MAX_STACK_ROWS} rows")

    rows = [classify(row) for row in value]
    seen: set[int] = set()
    for row in rows:
        if row["pr"] in seen:
            raise InputError(f"stack contains duplicate PR {row['pr']}")
        seen.add(row["pr"])

    base = {
        "contract_version": CONTRACT_VERSION,
        "scope": "stack",
        "order": "bottom-to-top",
        "rows": rows,
    }
    for tier in BLOCKER_TIERS:
        for row in rows:
            if row["status"] == "blocked" and row["reason"].get("tier") == tier:
                return {
                    **base,
                    "status": "blocked",
                    "babysit_ready": False,
                    "provider_landing_gate_clear": False,
                    "terminal": True,
                    "blocker": {"pr": row["pr"], "head_sha": row["head_sha"]},
                    "reason": row["reason"],
                }
    for row in rows:
        if row["status"] == "pending":
            return {
                **base,
                "status": "pending",
                "babysit_ready": False,
                "provider_landing_gate_clear": False,
                "terminal": False,
                "frontier": {"pr": row["pr"], "head_sha": row["head_sha"]},
                "reason": row["reason"],
            }
    if not all(row["status"] in {"ready", "merged"} for row in rows):
        raise RuntimeError("stack has no classified decision")
    return {
        **base,
        "status": "clear",
        "babysit_ready": True,
        "provider_landing_gate_clear": all(
            row["provider_landing_gate_clear"]
            for row in rows
            if row["status"] == "ready"
        ),
        "terminal": True,
        "prs": [
            {"pr": row["pr"], "head_sha": row["head_sha"]} for row in rows
        ],
        "reason": {"kind": "whole_stack_babysitting_complete"},
    }


QUEUE_EVENT_KINDS = {"INITIALIZED", "WAITING", "ADVANCE", "BLOCKER", "COMPLETE"}


def _identity(value: Any, label: str) -> dict[str, Any]:
    row = _object(value, label)
    return {
        "pr": _pr(row.get("pr")),
        "head_sha": _sha(row.get("head_sha"), f"{label}.head_sha"),
    }


def _repository_part(value: Any, label: str) -> str:
    pattern = OWNER_PART if label.endswith(".owner") else REPO_PART
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise InputError(f"{label} is not a normalized GitHub name")
    if value in {".", ".."} or (label.endswith(".owner") and "--" in value):
        raise InputError(f"{label} is invalid")
    return value.lower()


def _repository_identity(value: Any, label: str) -> dict[str, str]:
    row = _object(value, label)
    return {
        "owner": _repository_part(row.get("owner"), f"{label}.owner"),
        "repo": _repository_part(row.get("repo"), f"{label}.repo"),
    }


def _pr_identity(value: Any, label: str) -> dict[str, Any]:
    row = _object(value, label)
    return {
        **_repository_identity(row, label),
        "pr": _pr(row.get("pr")),
    }


def _observed_queue_identity(value: Any, label: str) -> dict[str, Any]:
    row = _object(value, label)
    return {
        **_pr_identity(row, label),
        "head_sha": _sha(row.get("head_sha"), f"{label}.head_sha"),
    }


def _frontier_identity(value: Any, label: str) -> dict[str, Any]:
    row = _object(value, label)
    identity: dict[str, Any] = _pr_identity(row, label)
    if "head_sha" in row:
        identity["head_sha"] = _sha(row["head_sha"], f"{label}.head_sha")
    return identity


def _identity_key(value: dict[str, Any]) -> tuple[str, str, int]:
    return value["owner"], value["repo"], value["pr"]


def _frozen_digest(frozen: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        frozen, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _frozen_identities(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise InputError("frozen queue must be an array")
    if not value:
        raise InputError("frozen queue must be nonempty and ordered bottom-to-top")
    if len(value) > MAX_STACK_ROWS:
        raise InputError(f"frozen queue must contain at most {MAX_STACK_ROWS} rows")
    frozen = [
        _pr_identity(row, f"frozen[{index}]") for index, row in enumerate(value)
    ]
    repositories = {(row["owner"], row["repo"]) for row in frozen}
    if len(repositories) != 1:
        raise InputError("frozen queue must belong to one normalized repository")
    seen: set[tuple[str, str, int]] = set()
    for row in frozen:
        key = _identity_key(row)
        if key in seen:
            raise InputError(f"frozen queue contains duplicate PR {row['pr']}")
        seen.add(key)
    return frozen


def _queue_history_record(event: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {
        "generation": event["generation"],
        "kind": event["kind"],
        "terminal": event["terminal"],
    }
    for key in ("frontier", "previous_frontier", "blocker"):
        if key in event:
            record[key] = event[key]
    if "newly_merged" in event:
        record["newly_merged"] = event["newly_merged"]
    if "frozen_count" in event:
        record["frozen_count"] = event["frozen_count"]
    if "remaining" in event:
        record["remaining"] = event["remaining"]
    if "merged_count" in event:
        record["merged_count"] = event["merged_count"]
    reason = event.get("reason")
    if isinstance(reason, dict):
        record["reason_kind"] = reason.get("kind")
        if "tier" in reason:
            record["reason_tier"] = reason["tier"]
    return json.loads(json.dumps(record, allow_nan=False, sort_keys=True))


def initialize_queue(value: Any) -> dict[str, Any]:
    """Freeze generation-zero PR identity and bottom-to-top order."""
    frozen = _frozen_identities(value)
    frontier = dict(frozen[0])
    event = {
        "generation": 0,
        "kind": "INITIALIZED",
        "terminal": False,
        "frontier": frontier,
        "frozen_count": len(frozen),
    }
    return {
        "contract_version": QUEUE_CONTRACT_VERSION,
        "repository": {"owner": frozen[0]["owner"], "repo": frozen[0]["repo"]},
        "order": "bottom-to-top",
        "phase": "active",
        "generation": 0,
        "frozen": frozen,
        "frozen_digest": _frozen_digest(frozen),
        "merged": [],
        "frontier": frontier,
        "history_start_generation": 0,
        "history": [_queue_history_record(event)],
    }


def _nonnegative_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InputError(f"{label} must be a non-negative integer")
    return value


def _validated_queue_state(value: Any) -> dict[str, Any]:
    state = _object(value, "queue_state")
    if state.get("contract_version") != QUEUE_CONTRACT_VERSION:
        raise InputError(f"queue_state.contract_version must be {QUEUE_CONTRACT_VERSION}")
    if state.get("order") != "bottom-to-top":
        raise InputError("queue_state.order must be bottom-to-top")
    frozen = _frozen_identities(state.get("frozen"))
    repository = _repository_identity(state.get("repository"), "queue_state.repository")
    if any(
        row["owner"] != repository["owner"] or row["repo"] != repository["repo"]
        for row in frozen
    ):
        raise InputError("queue_state.repository must match every frozen PR")
    frozen_digest = state.get("frozen_digest")
    if frozen_digest != _frozen_digest(frozen):
        raise InputError("queue_state frozen identities do not match frozen_digest")
    generation = _nonnegative_integer(state.get("generation"), "queue_state.generation")
    phase = state.get("phase")
    if phase not in {"active", "blocked", "complete"}:
        raise InputError("queue_state.phase must be active, blocked, or complete")

    merged_value = state.get("merged")
    if not isinstance(merged_value, list):
        raise InputError("queue_state.merged must be an array")
    merged = [
        _observed_queue_identity(row, f"queue_state.merged[{index}]")
        for index, row in enumerate(merged_value)
    ]
    frozen_by_key = {_identity_key(row): row for row in frozen}
    merged_keys = [_identity_key(row) for row in merged]
    if len(set(merged_keys)) != len(merged_keys):
        raise InputError("queue_state.merged must not contain duplicates")
    if any(key not in frozen_by_key for key in merged_keys):
        raise InputError("queue_state.merged must contain only frozen identities")
    expected_merged_keys = [
        _identity_key(row) for row in frozen if _identity_key(row) in set(merged_keys)
    ]
    if [_identity_key(row) for row in merged] != expected_merged_keys:
        raise InputError("queue_state.merged must preserve frozen order")

    active = [row for row in frozen if _identity_key(row) not in set(merged_keys)]
    frontier_value = state.get("frontier")
    frontier = (
        None
        if frontier_value is None
        else _frontier_identity(frontier_value, "queue_state.frontier")
    )
    expected_frontier = None if not active else active[0]
    if (None if frontier is None else _identity_key(frontier)) != (
        None if expected_frontier is None else _identity_key(expected_frontier)
    ):
        raise InputError("queue_state.frontier must be the lowest unmerged frozen identity")
    if phase == "complete" and active:
        raise InputError("complete queue state must have every frozen row merged")
    if phase != "complete" and not active:
        raise InputError("non-complete queue state must retain an unmerged frontier")

    history = state.get("history")
    if not isinstance(history, list) or not history:
        raise InputError("queue_state.history must be a nonempty array")
    if len(history) > MAX_QUEUE_HISTORY:
        raise InputError(f"queue_state.history must contain at most {MAX_QUEUE_HISTORY} events")
    clean_history: list[dict[str, Any]] = []
    previous_generation: int | None = None
    for index, raw_record in enumerate(history):
        record = _object(raw_record, f"queue_state.history[{index}]")
        record_generation = _nonnegative_integer(
            record.get("generation"), f"queue_state.history[{index}].generation"
        )
        if previous_generation is not None and record_generation != previous_generation + 1:
            raise InputError("queue_state.history generations must be consecutive")
        previous_generation = record_generation
        if record.get("kind") not in QUEUE_EVENT_KINDS:
            raise InputError(f"queue_state.history[{index}].kind is invalid")
        if not isinstance(record.get("terminal"), bool):
            raise InputError(f"queue_state.history[{index}].terminal must be a boolean")
        try:
            clean_history.append(
                json.loads(json.dumps(record, allow_nan=False, sort_keys=True))
            )
        except (TypeError, ValueError) as exc:
            raise InputError("queue_state.history must contain JSON values") from exc
    history_start = _nonnegative_integer(
        state.get("history_start_generation"),
        "queue_state.history_start_generation",
    )
    if clean_history[0]["generation"] != history_start:
        raise InputError("queue_state.history_start_generation must match history")
    if clean_history[-1]["generation"] != generation:
        raise InputError("queue_state history must end at the current generation")
    expected_last_kinds = {
        "active": {"INITIALIZED", "WAITING", "ADVANCE"},
        "blocked": {"BLOCKER"},
        "complete": {"COMPLETE"},
    }
    if clean_history[-1]["kind"] not in expected_last_kinds[phase]:
        raise InputError("queue_state phase must match its final history event")
    return {
        "contract_version": QUEUE_CONTRACT_VERSION,
        "repository": repository,
        "order": "bottom-to-top",
        "phase": phase,
        "generation": generation,
        "frozen": frozen,
        "frozen_digest": frozen_digest,
        "merged": merged,
        "frontier": frontier,
        "history_start_generation": history_start,
        "history": clean_history,
    }


def _queue_snapshot_rows(
    value: Any, frozen: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise InputError("queue snapshot must be an array")
    if len(value) != len(frozen):
        raise InputError("queue snapshot must contain every frozen row exactly once")
    rows: list[dict[str, Any]] = []
    for index, raw_row in enumerate(value):
        row = _object(raw_row, f"queue_snapshot[{index}]")
        observed = _observed_queue_identity(row, f"queue_snapshot[{index}]")
        expected = frozen[index]
        if _identity_key(observed) != _identity_key(expected):
            raise InputError(
                "queue snapshot must preserve exact frozen repository and PR order"
            )
        rows.append(row)
    return rows


def _next_queue_state(
    state: dict[str, Any],
    event: dict[str, Any],
    merged: list[dict[str, Any]],
    frontier: dict[str, Any] | None,
    phase: str,
) -> dict[str, Any]:
    history = [*state["history"], _queue_history_record(event)]
    if len(history) > MAX_QUEUE_HISTORY:
        history = history[-MAX_QUEUE_HISTORY:]
    return {
        "contract_version": QUEUE_CONTRACT_VERSION,
        "repository": dict(state["repository"]),
        "order": "bottom-to-top",
        "phase": phase,
        "generation": event["generation"],
        "frozen": [dict(row) for row in state["frozen"]],
        "frozen_digest": state["frozen_digest"],
        "merged": [dict(row) for row in merged],
        "frontier": None if frontier is None else dict(frontier),
        "history_start_generation": history[0]["generation"],
        "history": history,
    }


def apply_queue_snapshot(state_value: Any, snapshot_value: Any) -> dict[str, Any]:
    """Apply one full frozen-queue observation and return a new state plus event."""
    state = _validated_queue_state(state_value)
    if state["phase"] != "active":
        raise InputError("queue transitions stop after a terminal event")
    snapshots = _queue_snapshot_rows(snapshot_value, state["frozen"])
    observed_identities = [
        _observed_queue_identity(snapshot, f"queue_snapshot[{index}]")
        for index, snapshot in enumerate(snapshots)
    ]
    rows = [classify(snapshot) for snapshot in snapshots]
    old_merged_keys = {_identity_key(row) for row in state["merged"]}
    for identity, row in zip(observed_identities, rows):
        if _identity_key(identity) in old_merged_keys and row["status"] != "merged":
            raise InputError("an already-merged frozen row must remain represented as merged")
    merged = [
        identity
        for identity, row in zip(observed_identities, rows)
        if row["status"] == "merged"
    ]
    merged_keys = {_identity_key(row) for row in merged}
    active_pairs = [
        (identity, row)
        for identity, row in zip(observed_identities, rows)
        if row["status"] != "merged"
    ]
    generation = state["generation"] + 1

    for tier in BLOCKER_TIERS:
        for identity, row in active_pairs:
            if row["status"] == "blocked" and row["reason"].get("tier") == tier:
                event = {
                    "contract_version": QUEUE_CONTRACT_VERSION,
                    "generation": generation,
                    "kind": "BLOCKER",
                    "terminal": True,
                    "blocker": dict(identity),
                    "reason": row["reason"],
                }
                frontier = active_pairs[0][0]
                next_state = _next_queue_state(
                    state, event, merged, frontier, "blocked"
                )
                return {"contract_version": QUEUE_CONTRACT_VERSION, "event": event, "state": next_state}

    if not active_pairs:
        event = {
            "contract_version": QUEUE_CONTRACT_VERSION,
            "generation": generation,
            "kind": "COMPLETE",
            "terminal": True,
            "merged_count": len(merged),
            "merged": [dict(row) for row in merged],
        }
        next_state = _next_queue_state(state, event, merged, None, "complete")
        return {"contract_version": QUEUE_CONTRACT_VERSION, "event": event, "state": next_state}

    frontier = active_pairs[0][0]
    newly_merged = [
        row for row in merged if _identity_key(row) not in old_merged_keys
    ]
    if _identity_key(state["frontier"]) in merged_keys:
        previous_frontier = next(
            identity
            for identity in observed_identities
            if _identity_key(identity) == _identity_key(state["frontier"])
        )
        event = {
            "contract_version": QUEUE_CONTRACT_VERSION,
            "generation": generation,
            "kind": "ADVANCE",
            "terminal": False,
            "previous_frontier": dict(previous_frontier),
            "frontier": dict(frontier),
            "newly_merged": [dict(row) for row in newly_merged],
            "remaining": len(active_pairs),
        }
    else:
        frontier_row = active_pairs[0][1]
        reason = (
            {"kind": "frontier_pending", "detail": frontier_row["reason"]}
            if frontier_row["status"] == "pending"
            else {"kind": "merge_queue", "unmerged_count": len(active_pairs)}
        )
        event = {
            "contract_version": QUEUE_CONTRACT_VERSION,
            "generation": generation,
            "kind": "WAITING",
            "terminal": False,
            "frontier": dict(frontier),
            "reason": reason,
        }
    next_state = _next_queue_state(state, event, merged, frontier, "active")
    return {"contract_version": QUEUE_CONTRACT_VERSION, "event": event, "state": next_state}


def _classify_document(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("operation") == "queue_init":
        state = initialize_queue(value.get("frozen"))
        return {
            "contract_version": QUEUE_CONTRACT_VERSION,
            "event": state["history"][-1],
            "state": state,
        }
    if isinstance(value, dict) and value.get("operation") == "queue_apply":
        return apply_queue_snapshot(value.get("queue_state"), value.get("stack"))
    if isinstance(value, dict) and "stack" in value:
        contract = value.get("contract_version")
        if contract is not None and contract != CONTRACT_VERSION:
            raise InputError(f"contract_version must be {CONTRACT_VERSION}")
        return classify_stack(value["stack"])
    return classify(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", nargs="?", default="-", help="JSON file, or - for stdin")
    parser.add_argument("--pretty", action="store_true", help="indent output JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.file == "-":
            raw = sys.stdin.read()
        else:
            raw = Path(arguments.file).read_text(encoding="utf-8")
        verdict = _classify_document(json.loads(raw))
    except (InputError, json.JSONDecodeError, OSError) as exc:
        print(
            json.dumps(
                {
                    "contract_version": CONTRACT_VERSION,
                    "status": "error",
                    "babysit_ready": False,
                    "provider_landing_gate_clear": False,
                    "error": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(verdict, indent=2 if arguments.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
