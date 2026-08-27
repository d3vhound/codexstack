#!/usr/bin/env python3
"""Fail-closed structural validation for the CodexStack marketplace."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "codexstack"
SKILLS = PLUGIN / "skills"
WORK = SKILLS / "work"
BOX = SKILLS / "box"
EXPECTED_SKILLS = {"work", "box"}
EXPECTED_WORK_REFERENCES = {
    "autonomy.md",
    "bugbot-triage.md",
    "change.md",
    "deliberate.md",
    "delivery.md",
    "evaluate.md",
    "gates-and-laws.md",
    "investigate.md",
    "model-setup.md",
    "orchestrate.md",
    "playbooks.md",
    "quality.md",
    "review.md",
}
EXPECTED_BOX_REFERENCES = {"security.md"}
EXPECTED_AGENT_ROLES = {"architect", "explorer", "implementer", "judge", "verifier"}
DOCUMENTED_AGENT_MODELS = {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5", "gpt-5.4"}
TOTAL_RUNTIME_WORD_BUDGET = 22_000
ENTRY_WORD_BUDGET = 1_600
REFERENCE_WORD_BUDGET = 4_000
UPSTREAM_COMMIT = "fdf357fae76feff7e5f2e5aaff57f99f644b55f8"


class Validator:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.errors.append(message)

    def read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            self.errors.append(f"{relative(path)}: cannot read: {exc}")
            return ""

    def load_json(self, path: Path) -> dict:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.errors.append(f"{relative(path)}: invalid JSON: {exc}")
            return {}
        self.require(isinstance(value, dict), f"{relative(path)}: root must be an object")
        return value if isinstance(value, dict) else {}

    def load_toml(self, path: Path) -> dict:
        try:
            value = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            self.errors.append(f"{relative(path)}: invalid TOML: {exc}")
            return {}
        self.require(isinstance(value, dict), f"{relative(path)}: root must be a table")
        return value if isinstance(value, dict) else {}

    def finish(self, word_count: int) -> None:
        if self.errors:
            for error in self.errors:
                print(f"ERROR: {error}", file=sys.stderr)
            print(f"validation failed with {len(self.errors)} error(s)", file=sys.stderr)
            raise SystemExit(1)
        print("validation passed")
        print(f"registered skills: {len(EXPECTED_SKILLS)}")
        print(f"lazy references: {len(EXPECTED_WORK_REFERENCES) + len(EXPECTED_BOX_REFERENCES)}")
        print(f"optional agent roles: {len(EXPECTED_AGENT_ROLES)}")
        print(f"runtime words: {word_count}/{TOTAL_RUNTIME_WORD_BUDGET}")
        print("runtime dependencies: standard library only")


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def frontmatter(path: Path, validator: Validator) -> dict[str, str]:
    text = validator.read(path)
    match = re.match(r"\A---\n(.*?)\n---(?:\n|\Z)", text, re.DOTALL)
    validator.require(match is not None, f"{relative(path)}: missing YAML frontmatter")
    if match is None:
        return {}
    values: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        validator.require(bool(separator), f"{relative(path)}: malformed frontmatter line: {line}")
        if separator:
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def check_marketplace(validator: Validator) -> None:
    manifest = validator.load_json(PLUGIN / ".codex-plugin" / "plugin.json")
    marketplace = validator.load_json(ROOT / ".agents" / "plugins" / "marketplace.json")
    required = {
        "name", "version", "description", "author", "homepage", "repository",
        "license", "keywords", "skills", "interface",
    }
    validator.require(required <= manifest.keys(), f"plugin manifest missing: {sorted(required - manifest.keys())}")
    validator.require(manifest.get("name") == "codexstack", "plugin name must be codexstack")
    validator.require(manifest.get("version") == "0.2.0", "plugin version must be 0.2.0")
    validator.require(manifest.get("license") == "MIT", "plugin license must be MIT")
    validator.require(manifest.get("repository") == "https://github.com/d3vhound/codexstack", "repository URL is wrong")
    validator.require(manifest.get("skills") == "./skills/", "manifest skills path must be ./skills/")
    interface = manifest.get("interface")
    validator.require(isinstance(interface, dict), "plugin interface must be an object")
    if isinstance(interface, dict):
        short = interface.get("shortDescription")
        validator.require(isinstance(short, str) and 1 <= len(short) <= 30, "plugin shortDescription must be 1-30 characters")
        validator.require(interface.get("capabilities") == ["Interactive", "Read", "Write"], "plugin capabilities are wrong")
        prompts = interface.get("defaultPrompt")
        validator.require(isinstance(prompts, list) and 1 <= len(prompts) <= 3, "plugin defaultPrompt must contain 1-3 prompts")
        if isinstance(prompts, list):
            validator.require(
                all(isinstance(prompt, str) and 1 <= len(prompt) <= 128 for prompt in prompts),
                "each plugin defaultPrompt must contain 1-128 characters",
            )

    plugins = marketplace.get("plugins")
    validator.require(isinstance(plugins, list) and len(plugins) == 1, "marketplace must register exactly one plugin")
    if isinstance(plugins, list) and len(plugins) == 1 and isinstance(plugins[0], dict):
        entry = plugins[0]
        validator.require(entry.get("name") == "codexstack", "marketplace plugin name must be codexstack")
        source = entry.get("source")
        validator.require(isinstance(source, dict), "marketplace source must be an object")
        if isinstance(source, dict):
            validator.require(source == {"source": "local", "path": "./plugins/codexstack"}, "marketplace source is not the local plugin")


def check_skill(skill: Path, allow_implicit: bool, validator: Validator) -> list[Path]:
    metadata = frontmatter(skill / "SKILL.md", validator)
    validator.require(metadata.get("name") == skill.name, f"{relative(skill)}: name must match directory")
    validator.require(bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", metadata.get("name", ""))), f"{relative(skill)}: invalid skill name")
    description = metadata.get("description", "")
    validator.require(bool(description) and len(description) <= 1_024, f"{relative(skill)}: description must be 1-1024 characters")

    entry = skill / "SKILL.md"
    entry_words = len(re.findall(r"\b[\w'-]+\b", validator.read(entry)))
    validator.require(entry_words <= ENTRY_WORD_BUDGET, f"{relative(entry)} exceeds {ENTRY_WORD_BUDGET} words")

    yaml_path = skill / "agents" / "openai.yaml"
    yaml_text = validator.read(yaml_path)
    validator.require("interface:" in yaml_text, f"{relative(yaml_path)}: missing interface")
    validator.require("display_name:" in yaml_text, f"{relative(yaml_path)}: missing display_name")
    validator.require("short_description:" in yaml_text, f"{relative(yaml_path)}: missing short_description")
    validator.require("default_prompt:" in yaml_text, f"{relative(yaml_path)}: missing default_prompt")
    expected_policy = f"allow_implicit_invocation: {str(allow_implicit).lower()}"
    validator.require(expected_policy in yaml_text, f"{relative(yaml_path)}: expected {expected_policy}")
    validator.require(f"$codexstack:{skill.name}" in yaml_text, f"{relative(yaml_path)}: default prompt must use qualified skill name")

    references = sorted((skill / "references").glob("*.md"))
    for path in references:
        words = len(re.findall(r"\b[\w'-]+\b", validator.read(path)))
        validator.require(words <= REFERENCE_WORD_BUDGET, f"{relative(path)} exceeds {REFERENCE_WORD_BUDGET} words")
    return [entry, *references]


def check_roles(validator: Validator) -> None:
    role_dir = WORK / "assets" / "agents"
    paths = sorted(role_dir.glob("*.toml"))
    validator.require({path.stem for path in paths} == EXPECTED_AGENT_ROLES, "optional custom-agent role set differs from the intended five")
    for path in paths:
        data = validator.load_toml(path)
        for key in ("name", "description", "developer_instructions"):
            validator.require(isinstance(data.get(key), str) and bool(data.get(key)), f"{relative(path)}: missing {key}")
        validator.require(data.get("name") == path.stem, f"{relative(path)}: name must match filename")
        expected_sandbox = "workspace-write" if path.stem == "implementer" else "read-only"
        validator.require(data.get("sandbox_mode") == expected_sandbox, f"{relative(path)}: sandbox must be {expected_sandbox}")
        validator.require(data.get("model") in DOCUMENTED_AGENT_MODELS, f"{relative(path)}: model must be a current documented Codex override")
    verifier_text = validator.read(role_dir / "verifier.toml")
    validator.require("PASS, ISSUES, or BLOCKED" in verifier_text, "verifier role is missing Swarm vocabulary")
    validator.require("PASS, PASS+NOTES, or FAIL" in verifier_text, "verifier role is missing PR shipping vocabulary")
    validator.require("exact PR and head SHA" in verifier_text, "verifier role must bind shipping verdicts to exact identity")


def check_links(paths: list[Path], validator: Validator) -> None:
    markdown_link = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for path in paths:
        text = validator.read(path)
        for target in markdown_link.findall(text):
            clean = target.split("#", 1)[0]
            if not clean or re.match(r"^[a-z][a-z0-9+.-]*:", clean, re.IGNORECASE):
                continue
            resolved = (path.parent / clean).resolve()
            validator.require(inside(resolved, ROOT), f"{relative(path)}: link escapes repository: {target}")
            validator.require(resolved.exists(), f"{relative(path)}: broken link: {target}")


def require_contracts(runtime_text: str, validator: Validator) -> None:
    exact_contracts = [
        "first visible plan item", "numbered states from `playbooks.md` into the plan verbatim",
        "consumer impact", "next maintainer inherits", "specific choice it changed",
        "blocking first steps", "independent workstreams", "shared mutable state", "smallest safe decomposition",
        "Ground", "Architect", "Agree", "Implement", "Scrap", "base", "graft",
        "partition", "race", "mixed", "PASS", "ISSUES", "BLOCKED",
        "Act", "Consider", "Noted", "Dismissed",
        "Direct", "Supported", "Inferred", "Speculative", "Unknown",
        "exact head SHA", "contiguous verified prefix", "state-then-wait", "explicit go",
        "zero-write stop", "coordinator", "does not edit product code",
        "Delegate implementation", "This delegation is mandatory",
        "No-comments and Interrogate", "Write the fixed skeleton", "Check the plan",
        "fresh read-only reviewer", "accepts or rejects each finding independently",
        "Figure it out", "VERIFIED", "NOT VERIFIED", "INCONCLUSIVE",
        "Reviewable evidence trail", "Attention", "reviewed by <model>",
        "Surface", "Run", "Drive", "Observe", "Isolate", "Launch", "Doctor", "Evidence", "Cleanup", "Helpers",
        "clean", "changed", "blocked", "Critique mode", "Explain first",
        "Capture a personal mode", "allow_implicit_invocation: false", "active workspace",
        "Required return fields", "kept versus reverted", "four-column status table",
        "fresh independent synthesizer", "Accepted", "Rejected", "Backlog",
        "Brand semantic primitives", "constructive invariants", "Narrow in this order", "satisfies", "structured telemetry",
        "babysit_ready", "provider_landing_gate_clear", "fresh exact-head provider snapshot",
        "Run the focused contract test before classifying", "candidate", "recurring", "strong",
        "After Babysit reaches READY, queued WAITING, or COMPLETE", "Browser-native reimplementation",
        "Per-role model setup", "inherit-parent", "arena cross-judge pool", "interrogate reviewers",
        "exact `git worktree list --porcelain -z`", "codexstack.worktree-evidence.v1", "safe is advice",
        "release-stop", "operator-authorization", "repaired-systemic-cause",
    ]
    for token in exact_contracts:
        validator.require(token in runtime_text, f"runtime is missing behavioral contract: {token}")

    principle_names = [
        "Boundary discipline", "Build the lever", "Encode lessons structurally", "Exhaust the design space",
        "Experience first", "Fix root causes", "Think from foundations", "Guard context", "Practice useful laziness",
        "Make retries idempotent", "Finish migrations", "Minimize reader load", "Model the domain", "Never block the human",
        "Outcome-Oriented Execution", "Prove the real artifact", "Redesign from First Principles", "Separate shared state",
        "Sequence verifiable units", "Subtract", "Keep type discipline",
    ]
    for name in principle_names:
        validator.require(name in runtime_text, f"runtime is missing principle contract: {name}")

    lowered = runtime_text.lower()
    forbidden = [".cursor/", "/poteto-mode", "subagent_type", "run_in_background", "poteto-agent", "claude-", "grok-"]
    for token in forbidden:
        validator.require(token not in lowered, f"runtime contains Cursor-specific executable contract: {token}")
    validator.require("for any non-trivial work" in lowered, "runtime weakens Build the lever below non-trivial work")
    validator.require("if no rerunnable artifact exists" in lowered, "runtime does not require a Build-the-lever artifact")
    validator.require("\u2014" not in runtime_text, "runtime violates the Poteto reply ban on em dashes")


def check_code_and_provenance(validator: Validator) -> None:
    required_files = [
        WORK / "scripts" / "state.py",
        WORK / "scripts" / "pr_readiness.py",
        WORK / "scripts" / "check_plan.py",
        WORK / "scripts" / "model_policy.py",
        WORK / "scripts" / "worktree_audit.py",
        WORK / "assets" / "model-policy.example.json",
        BOX / "scripts" / "doctor.py",
        BOX / "scripts" / "boxctl.py",
        ROOT / "tests" / "test_state.py",
        ROOT / "tests" / "test_pr_readiness.py",
        ROOT / "tests" / "test_check_plan.py",
        ROOT / "tests" / "test_model_policy.py",
        ROOT / "tests" / "test_worktree_audit.py",
        ROOT / "tests" / "test_behavior_contract.py",
        ROOT / "tests" / "test_box.py",
        ROOT / "docs" / "PARITY.md",
        ROOT / "docs" / "BOX.md",
    ]
    for path in required_files:
        validator.require(path.is_file(), f"missing required artifact: {relative(path)}")

    textual_files = [path for path in ROOT.rglob("*") if path.is_file() and ".git" not in path.parts]
    secret_patterns = {
        "OpenAI key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
        "GitHub token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}"),
        "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    }
    unfinished_markers = ("TO" + "DO", "T" + "BD")
    for path in textual_files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for label, pattern in secret_patterns.items():
            validator.require(pattern.search(text) is None, f"{relative(path)}: possible {label}")
        validator.require(not any(marker in text for marker in unfinished_markers), f"{relative(path)}: unfinished marker")

    license_text = validator.read(ROOT / "LICENSE")
    notice_text = validator.read(ROOT / "NOTICE.md")
    validator.require("MIT License" in license_text, "LICENSE must contain the MIT license")
    validator.require("Lauren Tan" in license_text and "Lauren Tan" in notice_text, "upstream author attribution is missing")
    validator.require(UPSTREAM_COMMIT in notice_text, "NOTICE must pin the audited upstream commit")
    validator.require("MIT" in notice_text, "NOTICE must identify the upstream MIT license")

    readme = validator.read(ROOT / "README.md")
    validator.require("codex plugin marketplace add d3vhound/codexstack" in readme, "README is missing marketplace installation")
    validator.require("codex plugin add codexstack@codexstack" in readme, "README is missing plugin installation")
    validator.require("does not automatically appear" in readme, "README must state the mobile-session limitation")


def main() -> None:
    validator = Validator()
    check_marketplace(validator)

    skill_files = sorted(SKILLS.glob("*/SKILL.md"))
    validator.require({path.parent.name for path in skill_files} == EXPECTED_SKILLS, "plugin must expose exactly work and box skills")
    work_runtime = check_skill(WORK, False, validator)
    box_runtime = check_skill(BOX, False, validator)

    work_references = {path.name for path in (WORK / "references").glob("*.md")}
    box_references = {path.name for path in (BOX / "references").glob("*.md")}
    validator.require(work_references == EXPECTED_WORK_REFERENCES, f"work reference set differs from the intended {len(EXPECTED_WORK_REFERENCES)} routes")
    validator.require(box_references == EXPECTED_BOX_REFERENCES, "box reference set must contain only security.md")
    check_roles(validator)

    runtime_paths = work_runtime + box_runtime
    runtime_text = "\n".join(validator.read(path) for path in runtime_paths)
    word_count = len(re.findall(r"\b[\w'-]+\b", runtime_text))
    validator.require(word_count <= TOTAL_RUNTIME_WORD_BUDGET, f"runtime exceeds {TOTAL_RUNTIME_WORD_BUDGET} words")
    require_contracts(runtime_text, validator)

    docs = [ROOT / "README.md", ROOT / "AGENTS.md", *sorted((ROOT / "docs").glob("*.md")), *sorted((ROOT / "evals").glob("*.md"))]
    check_links(runtime_paths + docs, validator)
    check_code_and_provenance(validator)
    validator.finish(word_count)


if __name__ == "__main__":
    main()
