#!/usr/bin/env python3
"""Audit a CodexStack multi-PR plan without changing external state.

The checker reads one Markdown file below the current directory. It validates a
fixed program skeleton, topological PR order, revision-bound proof blocks, and
explicit delivery gates. It never invokes git, a provider, a timer, or an
agent.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence


CONTRACT_VERSION = "codexstack.check-plan.v1"
MAX_BYTES = 1_048_576
MAX_LINES = 20_000
MAX_LINE_BYTES = 16_384
MAX_SECTIONS = 512

RULE = (
    "Tests alone are not sufficient verification. A PR is verified only when "
    "its unit, live, and perf boxes are all checked."
)
LIVE_RULE = "Ten live lanes at the exact PR head"
SUB_BLOCKS = (
    "Depends on.",
    "Files.",
    "Build.",
    "You see.",
    "Verify, unit.",
    "Verify, live.",
    "Verify, perf.",
    "Review gate.",
    "Merge.",
)
PROGRAM_H3 = (
    "Arm the program",
    "Spawn owners",
    "PR mechanics",
    "Verdict and merge",
    "Boot recipe",
)
DELIVERY_LAYERS = ("Commit.", "PR.", "Ready.", "Land.")
PROGRAM_MARKERS = {
    "Arm the program": ("explicit go", "zero-write"),
    "Spawn owners": ("depend", "exclusive", "review gate"),
    "Verdict and merge": ("exact head sha", "pass"),
    "Boot recipe": ("real surface", "evidence"),
}
HOW_TO_READ_MARKERS = (
    "One box is one unit of work",
    "names the evidence",
    "Check a box only when its evidence exists",
    "playbook",
    RULE,
)
PERF_ITEMS = ("Metric.", "Probe.", "Baseline.", "Rule.")

BOX_RE = re.compile(r"^\s*-\s+\[([ xX])\]\s+(.+?)\s*$")
BLOCK_RE = re.compile(r"^\*\*([^*]+)\*\*(.*)$")
PR_TITLE_RE = re.compile(r"^(.+?)\s+\(([^()]+)\)\s*$")
PR_ID_RE = re.compile(r"(?:#[1-9][0-9]*|[A-Za-z0-9][A-Za-z0-9._-]{0,63})\Z")
SKIP_RE = re.compile(r"\bskip(?:ped)?(?:\.|:)\s*(.*)", re.IGNORECASE)
FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


class InputError(ValueError):
    """The requested plan file is outside the bounded input contract."""


@dataclass(frozen=True)
class SourceLine:
    number: int
    text: str
    code: bool = False


@dataclass
class Section:
    title: str
    line: int
    body: list[SourceLine] = field(default_factory=list)


@dataclass
class Block:
    name: str
    line: int
    rest: str
    lines: list[SourceLine] = field(default_factory=list)


@dataclass(frozen=True)
class Diagnostic:
    line: int
    code: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {"line": self.line, "code": self.code, "message": self.message}


@dataclass
class Audit:
    path: str
    diagnostics: list[Diagnostic] = field(default_factory=list)
    prs: list[dict[str, Any]] = field(default_factory=list)
    skips: list[dict[str, Any]] = field(default_factory=list)

    def fail(self, line: int, code: str, message: str) -> None:
        self.diagnostics.append(Diagnostic(max(1, line), code, message))

    def payload(self) -> dict[str, Any]:
        diagnostics = sorted(
            self.diagnostics,
            key=lambda item: (item.line, item.code, item.message),
        )
        return {
            "contract_version": CONTRACT_VERSION,
            "path": self.path,
            "valid": not diagnostics,
            "summary": {
                "pr_sections": len(self.prs),
                "problems": len(diagnostics),
                "explicit_skips": len(self.skips),
            },
            "prs": self.prs,
            "skips": self.skips,
            "diagnostics": [item.as_dict() for item in diagnostics],
        }


def _safe_path(path_text: str, root: Path) -> tuple[Path, str]:
    if not isinstance(path_text, str) or not path_text or len(path_text) > 1_024:
        raise InputError("plan path must contain 1 to 1024 characters")
    relative = Path(path_text)
    if relative.is_absolute():
        raise InputError("plan path must be relative to the current directory")
    if relative.suffix != ".md":
        raise InputError("plan path must end in .md")
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise InputError("plan path must not contain dot or parent components")
    for part in relative.parts:
        if part.startswith("-") or any(ord(character) < 32 for character in part):
            raise InputError("plan path contains an unsafe component")

    try:
        base = root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise InputError("current directory is not an accessible directory") from exc
    candidate = base.joinpath(relative)
    cursor = base
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise InputError("plan path must not contain symlinks")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(base)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise InputError("plan path must name an existing file below the current directory") from exc
    return resolved, relative.as_posix()


def read_plan(path_text: str, root: Path | None = None) -> tuple[str, str]:
    """Read one bounded UTF-8 Markdown file below root."""
    path, display = _safe_path(path_text, root or Path.cwd())
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise InputError(f"cannot open plan file: {exc.strerror or exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise InputError("plan path must name a regular file")
        if metadata.st_size > MAX_BYTES:
            raise InputError(f"plan file exceeds {MAX_BYTES} bytes")
        chunks: list[bytes] = []
        remaining = MAX_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
    finally:
        os.close(descriptor)
    if len(data) > MAX_BYTES:
        raise InputError(f"plan file exceeds {MAX_BYTES} bytes")
    if b"\x00" in data:
        raise InputError("plan file contains a NUL byte")
    if any(len(line) > MAX_LINE_BYTES for line in data.splitlines()):
        raise InputError(f"plan line exceeds {MAX_LINE_BYTES} bytes")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError("plan file must be valid UTF-8") from exc
    if len(text.splitlines()) > MAX_LINES:
        raise InputError(f"plan file exceeds {MAX_LINES} lines")
    return text, display


def _source_lines(text: str, audit: Audit) -> list[SourceLine]:
    raw = text.splitlines()
    start = 0
    if raw and raw[0] == "---":
        try:
            start = raw.index("---", 1) + 1
        except ValueError:
            audit.fail(1, "frontmatter.unclosed", "frontmatter has no closing delimiter")
            start = len(raw)

    lines: list[SourceLine] = []
    fence_character: str | None = None
    fence_length = 0
    for index in range(start, len(raw)):
        text_line = raw[index]
        match = FENCE_RE.match(text_line)
        was_code = fence_character is not None
        if match:
            marker = match.group(1)
            if fence_character is None:
                fence_character = marker[0]
                fence_length = len(marker)
                was_code = True
            elif marker[0] == fence_character and len(marker) >= fence_length:
                was_code = True
                fence_character = None
                fence_length = 0
        line = SourceLine(index + 1, text_line, was_code)
        lines.append(line)
        if line.code:
            continue
        prose = re.sub(r"`[^`]*`", "`", text_line)
        prose = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", prose)
        prose = re.sub(r"\]\([^)]*\)", "]", prose)
        if re.search(r"[\u2013\u2014]", prose):
            audit.fail(line.number, "prose.long-dash", "prose contains a long dash")
        if re.search(r"[\u2018\u2019\u201c\u201d]", prose):
            audit.fail(line.number, "prose.curly-quote", "prose contains a curly quote")
        if re.search(r":\s+\S", prose):
            audit.fail(line.number, "prose.mid-colon", "prose contains a mid-sentence colon")
    if fence_character is not None:
        audit.fail(len(raw) or 1, "fence.unclosed", "code fence has no closing delimiter")
    return lines


def _sections(lines: list[SourceLine], audit: Audit) -> list[Section]:
    result: list[Section] = []
    for line in lines:
        if not line.code and line.text.startswith("## "):
            result.append(Section(line.text[3:].strip(), line.number))
        elif result:
            result[-1].body.append(line)
    if len(result) > MAX_SECTIONS:
        audit.fail(1, "sections.too-many", f"plan has more than {MAX_SECTIONS} H2 sections")
    return result


def _body_text(section: Section) -> str:
    return "\n".join(line.text for line in section.body)


def _boxes(lines: list[SourceLine]) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    for line in lines:
        if line.code:
            continue
        match = BOX_RE.match(line.text)
        if match:
            result.append((line.number, match.group(2)))
    return result


def _blocks(section: Section) -> list[Block]:
    result: list[Block] = []
    for line in section.body:
        if line.code:
            continue
        match = BLOCK_RE.match(line.text)
        if match and match.group(1) in SUB_BLOCKS:
            result.append(Block(match.group(1), line.number, match.group(2).strip()))
        elif result:
            result[-1].lines.append(line)
    return result


def _skip_reason(text: str) -> tuple[bool, str | None]:
    match = SKIP_RE.search(text)
    if not match:
        return False, None
    reason = match.group(1).strip()
    normalized = re.sub(r"[^a-z0-9]+", " ", reason.lower()).strip()
    rejected = {"", "na", "n a", "none", "not applicable", "reason", "tbd", "todo"}
    concrete = (
        normalized not in rejected
        and "<" not in reason
        and ">" not in reason
        and len(re.findall(r"[A-Za-z0-9]+", reason)) >= 3
    )
    return True, reason if concrete else None


def _block_skip(block: Block, audit: Audit, pr_id: str) -> str | None:
    texts = [block.rest, *(line.text for line in block.lines if not line.code)]
    found = False
    for text in texts:
        present, reason = _skip_reason(text)
        if not present:
            continue
        found = True
        if reason is None:
            audit.fail(block.line, "skip.reason", f"{pr_id} {block.name} has no concrete skip reason")
            return None
        audit.skips.append(
            {"pr": pr_id, "block": block.name, "line": block.line, "reason": reason}
        )
        return reason
    return "" if found else None


def _program_check(program: Section, audit: Audit) -> None:
    headings = [
        (line.text[4:].strip(), line.number)
        for line in program.body
        if not line.code and line.text.startswith("### ")
    ]
    cursor = 0
    positions: dict[str, int] = {}
    for expected in PROGRAM_H3:
        match = next(
            (
                (index, line)
                for index, (title, line) in enumerate(headings[cursor:], cursor)
                if title.startswith(expected)
            ),
            None,
        )
        if match is None:
            audit.fail(program.line, "program.heading", f'Program checklist lacks "### {expected}" in order')
            continue
        positions[expected] = match[0]
        cursor = match[0] + 1

    for expected, heading_index in positions.items():
        start_line = headings[heading_index][1]
        end_line = headings[heading_index + 1][1] if heading_index + 1 < len(headings) else None
        body_lines = [
            line
            for line in program.body
            if line.number > start_line and (end_line is None or line.number < end_line)
        ]
        evidence_boxes = _boxes(body_lines)
        skip = _block_skip(Block(expected, start_line, "", body_lines), audit, "program")
        if skip and evidence_boxes:
            audit.fail(start_line, "skip.ambiguous", f"Program {expected} has both boxes and a skip")
        elif not skip and not evidence_boxes:
            audit.fail(start_line, "program.evidence", f"Program {expected} has no box or concrete skip reason")
        if skip:
            continue
        lower_body = "\n".join(line.text.lower() for line in body_lines)
        for marker in PROGRAM_MARKERS.get(expected, ()):
            if marker not in lower_body:
                audit.fail(start_line, "program.marker", f'Program {expected} lacks "{marker}"')

    mechanics_start = next(
        (line.number for line in program.body if not line.code and line.text.startswith("### PR mechanics")),
        None,
    )
    next_heading = None
    if mechanics_start is not None:
        next_heading = next(
            (
                line.number
                for line in program.body
                if not line.code and line.number > mechanics_start and line.text.startswith("### ")
            ),
            None,
        )
    mechanics_lines = [
        line
        for line in program.body
        if mechanics_start is not None
        and line.number > mechanics_start
        and (next_heading is None or line.number < next_heading)
    ]
    mechanics_boxes = _boxes(mechanics_lines)
    layer_positions: list[int] = []
    for layer in DELIVERY_LAYERS:
        at = next((line for line, text in mechanics_boxes if text.startswith(layer)), None)
        if at is None:
            audit.fail(
                mechanics_start or program.line,
                "program.delivery-layer",
                f'PR mechanics lacks a "{layer}" box',
            )
        else:
            layer_positions.append(at)
    if len(layer_positions) == len(DELIVERY_LAYERS) and layer_positions != sorted(layer_positions):
        audit.fail(
            mechanics_start or program.line,
            "program.delivery-order",
            "PR mechanics must order Commit, PR, Ready, then Land",
        )


def _audit_pr(section: Section, audit: Audit) -> tuple[str | None, list[str]]:
    title_match = PR_TITLE_RE.fullmatch(section.title)
    valid_id = False
    if not title_match:
        audit.fail(section.line, "pr.title", f'{section.title} must end with a unique PR id in parentheses')
        pr_id = f"invalid-line-{section.line}"
    else:
        pr_id = title_match.group(2).strip()
        if not PR_ID_RE.fullmatch(pr_id):
            audit.fail(section.line, "pr.id", f'{pr_id} is not a valid PR id')
        else:
            valid_id = True

    blocks = _blocks(section)
    names = [block.name for block in blocks]
    if tuple(names) != SUB_BLOCKS:
        audit.fail(
            section.line,
            "pr.blocks",
            f'{pr_id} sub-blocks are [{", ".join(names)}], expected [{", ".join(SUB_BLOCKS)}]',
        )
    by_name = {block.name: block for block in blocks}
    counts = {name: len(_boxes(block.lines)) for name, block in by_name.items()}
    dependencies: list[str] = []

    depends = by_name.get("Depends on.")
    if depends:
        value = depends.rest.strip()
        if value == "None.":
            dependencies = []
        else:
            if value.endswith("."):
                value = value[:-1]
            parts = [part.strip() for part in value.split(",") if part.strip()]
            if not parts or any(not PR_ID_RE.fullmatch(part) for part in parts):
                audit.fail(depends.line, "pr.dependencies", f'{pr_id} Depends on must be "None." or a comma-separated PR id list')
            elif len(parts) != len(set(parts)):
                audit.fail(depends.line, "pr.dependencies", f"{pr_id} names a dependency more than once")
            else:
                dependencies = parts

    required_boxes = ("Files.", "Build.", "You see.", "Verify, unit.", "Merge.")
    for name in required_boxes:
        block = by_name.get(name)
        if block is None:
            continue
        skip = _block_skip(block, audit, pr_id)
        box_count = counts.get(name, 0)
        if skip and box_count:
            audit.fail(block.line, "skip.ambiguous", f"{pr_id} {name} has both boxes and a skip")
        elif not skip and box_count == 0:
            audit.fail(block.line, "pr.evidence", f"{pr_id} {name} has no box or concrete skip reason")

    for name in ("Verify, unit.", "Verify, live.", "Verify, perf."):
        block = by_name.get(name)
        if block and not block.rest.startswith(RULE):
            audit.fail(block.line, "verify.rule", f"{pr_id} {name} does not open with the verification rule")

    live = by_name.get("Verify, live.")
    if live:
        skip = _block_skip(live, audit, pr_id)
        live_boxes = _boxes(live.lines)
        if skip and live_boxes:
            audit.fail(live.line, "skip.ambiguous", f"{pr_id} Verify, live. has both lanes and a skip")
        elif not skip:
            if LIVE_RULE not in live.rest:
                audit.fail(live.line, "live.rule", f'{pr_id} Verify, live. lacks "{LIVE_RULE}"')
            lane_numbers: list[int] = []
            for line, text in live_boxes:
                match = re.match(r"^Lane (\d+)\. ", text)
                if not match:
                    audit.fail(line, "live.lane", f"{pr_id} live box is not a numbered lane")
                    continue
                lane_numbers.append(int(match.group(1)))
                if not re.search(r"Save `[^`]+`", text):
                    audit.fail(line, "live.artifact", f"{pr_id} lane {match.group(1)} names no saved artifact")
                if "Pass when" not in text:
                    audit.fail(line, "live.predicate", f"{pr_id} lane {match.group(1)} has no pass predicate")
            if lane_numbers != list(range(1, 11)):
                audit.fail(live.line, "live.count", f"{pr_id} lanes are {lane_numbers}, expected 1 through 10 in order")

    perf = by_name.get("Verify, perf.")
    if perf:
        skip = _block_skip(perf, audit, pr_id)
        perf_boxes = _boxes(perf.lines)
        if skip and perf_boxes:
            audit.fail(perf.line, "skip.ambiguous", f"{pr_id} Verify, perf. has both boxes and a skip")
        elif not skip:
            items = [text.split(" ", 1)[0] for _, text in perf_boxes]
            if tuple(items) != PERF_ITEMS:
                audit.fail(perf.line, "perf.items", f'{pr_id} perf boxes are [{", ".join(items)}], expected [{", ".join(PERF_ITEMS)}]')
            elif len(perf_boxes) == 4:
                details = [text.lower() for _, text in perf_boxes]
                if not re.search(r"\b(?:base|trunk)\b", details[1]) or "head" not in details[1]:
                    audit.fail(perf_boxes[1][0], "perf.probe", f"{pr_id} perf Probe must compare base or trunk with head")
                if not re.search(r"\b(?:base|trunk)\b", details[2]):
                    audit.fail(perf_boxes[2][0], "perf.baseline", f"{pr_id} perf Baseline must record base or trunk first")
                if not re.search(r"\d", details[3]):
                    audit.fail(perf_boxes[3][0], "perf.threshold", f"{pr_id} perf Rule names no numeric failure threshold")

    gate = by_name.get("Review gate.")
    if gate:
        gate_boxes = _boxes(gate.lines)
        if gate.rest.startswith("None."):
            reason = gate.rest[5:].strip()
            if len(re.findall(r"[A-Za-z0-9]+", reason)) < 3:
                audit.fail(gate.line, "review.reason", f"{pr_id} Review gate None needs a concrete non-interaction reason")
            if gate_boxes:
                audit.fail(gate.line, "review.ambiguous", f"{pr_id} Review gate says None but has boxes")
        else:
            gate_text = "\n".join(line.text.lower() for line in gate.lines)
            if not gate_boxes:
                audit.fail(gate.line, "review.evidence", f"{pr_id} interaction Review gate has no box")
            for word in ("screenshot", "video", "operator"):
                if word not in gate_text:
                    audit.fail(gate.line, "review.evidence", f'{pr_id} interaction Review gate lacks "{word}" evidence')

    audit.prs.append(
        {
            "id": pr_id,
            "title": section.title,
            "line": section.line,
            "depends_on": dependencies,
            "boxes": {name: counts.get(name, 0) for name in SUB_BLOCKS if name != "Depends on."},
        }
    )
    return (pr_id if valid_id else None), dependencies


def audit_text(text: str, path: str = "plan.md") -> Audit:
    """Return structural diagnostics for one already-bounded plan string."""
    audit = Audit(path)
    lines = _source_lines(text, audit)
    sections = _sections(lines, audit)
    find = lambda title: next((section for section in sections if section.title == title), None)

    h1_index = next(
        (index for index, line in enumerate(lines) if not line.code and line.text.startswith("# ")),
        None,
    )
    if h1_index is None:
        audit.fail(1, "plan.h1", "plan has no H1 title")

    how_to_read = find("How to read this")
    if how_to_read is None:
        audit.fail(1, "plan.how-to-read", 'plan has no "## How to read this" section')
    elif h1_index is not None:
        intro = [
            line
            for line in lines[h1_index + 1 :]
            if line.number < how_to_read.line and line.text.strip()
        ]
        if len(intro) >= 10:
            audit.fail(lines[h1_index].number, "plan.intro", f"intro is {len(intro)} lines, fewer than ten required")
        body = _body_text(how_to_read)
        for marker in HOW_TO_READ_MARKERS:
            if marker not in body:
                audit.fail(how_to_read.line, "plan.how-to-read", f'How to read this lacks "{marker}"')

    program = find("Program checklist")
    if program is None:
        audit.fail(1, "program.missing", 'plan has no "## Program checklist" section')
    else:
        _program_check(program, audit)

    close = find("Close the program")
    if close is None:
        audit.fail(1, "close.missing", 'plan has no "## Close the program" section')

    program_index = sections.index(program) if program in sections else -1
    close_index = sections.index(close) if close in sections else -1
    pr_sections = (
        sections[program_index + 1 : close_index]
        if program_index >= 0 and close_index > program_index
        else []
    )
    if not pr_sections:
        audit.fail(1, "pr.missing", "plan has no PR sections between Program checklist and Close the program")

    identities: list[tuple[str | None, list[str], int]] = []
    for section in pr_sections:
        pr_id, dependencies = _audit_pr(section, audit)
        identities.append((pr_id, dependencies, section.line))

    known = [pr_id for pr_id, _, _ in identities if pr_id]
    if len(known) != len(set(known)):
        duplicates = sorted({pr_id for pr_id in known if known.count(pr_id) > 1})
        audit.fail(1, "pr.duplicate", f'duplicate PR ids are [{", ".join(duplicates)}]')
    index_by_id = {
        pr_id: index
        for index, (pr_id, _, _) in enumerate(identities)
        if pr_id is not None
    }
    for index, (pr_id, dependencies, line) in enumerate(identities):
        if pr_id is None:
            continue
        for dependency in dependencies:
            if dependency not in index_by_id:
                audit.fail(line, "pr.dependency-unknown", f"{pr_id} depends on unknown {dependency}")
            elif index_by_id[dependency] >= index:
                audit.fail(line, "pr.dependency-order", f"{pr_id} depends on {dependency}, which is not an earlier PR section")

    if close_index >= 0:
        tail = sections[close_index + 1 :]
        for section in tail:
            if not section.title.startswith("Appendix"):
                audit.fail(section.line, "appendix.order", f'"## {section.title}" after Close the program is not an appendix')
        if not any("Prototype evidence" in section.title for section in tail):
            audit.fail(close.line, "appendix.prototype", 'plan has no "## Appendix ... Prototype evidence" section')
    return audit


def audit_path(path_text: str, root: Path | None = None) -> Audit:
    text, display = read_plan(path_text, root)
    return audit_text(text, display)


def _input_error(path: str, message: str) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "path": path,
        "valid": False,
        "summary": {"pr_sections": 0, "problems": 1, "explicit_skips": 0},
        "prs": [],
        "skips": [],
        "diagnostics": [{"line": 1, "code": "input.invalid", "message": message}],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit one CodexStack multi-PR Markdown plan.")
    parser.add_argument("plan", help="relative .md path below the current directory")
    parser.add_argument("--json", action="store_true", help="emit one JSON document")
    arguments = parser.parse_args(argv)
    try:
        audit = audit_path(arguments.plan)
        payload = audit.payload()
    except InputError as exc:
        payload = _input_error(arguments.plan, str(exc))
        if arguments.json:
            print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        else:
            print(f"{arguments.plan}:1: input.invalid: {exc}", file=sys.stderr)
            print("0 PR sections, 1 problem, 0 explicit skips")
        return 2

    if arguments.json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        for pr in payload["prs"]:
            counts = " ".join(
                f'{name.lower().replace(" ", "-").replace(",", "").rstrip(".")}={count}'
                for name, count in pr["boxes"].items()
            )
            dependencies = ",".join(pr["depends_on"]) or "none"
            print(f'{pr["id"]} depends={dependencies} {counts}')
        for diagnostic in payload["diagnostics"]:
            print(
                f'{payload["path"]}:{diagnostic["line"]}: {diagnostic["code"]}: {diagnostic["message"]}',
                file=sys.stderr,
            )
        summary = payload["summary"]
        noun = "problem" if summary["problems"] == 1 else "problems"
        print(
            f'{summary["pr_sections"]} PR sections, {summary["problems"]} {noun}, '
            f'{summary["explicit_skips"]} explicit skips'
        )
    return 0 if payload["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
