#!/usr/bin/env python3
"""Validate the CodexStack marketplace, plugin, skill, and provenance."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "codexstack"
SKILLS = PLUGIN / "skills"
WORK = SKILLS / "work"
RUNTIME_FILES = [WORK / "SKILL.md", *sorted((WORK / "references").glob("*.md"))]
EXPECTED_REFERENCES = {"change.md", "delivery.md", "evaluate.md", "investigate.md", "review.md"}
WORD_BUDGET = 4_000
UPSTREAM_COMMIT = "fdf357fae76feff7e5f2e5aaff57f99f644b55f8"


class Validator:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.errors.append(message)

    def load_json(self, path: Path) -> dict:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.errors.append(f"{path.relative_to(ROOT)}: invalid JSON: {exc}")
            return {}
        self.require(isinstance(value, dict), f"{path.relative_to(ROOT)}: root must be an object")
        return value if isinstance(value, dict) else {}

    def finish(self, word_count: int) -> None:
        if self.errors:
            for error in self.errors:
                print(f"ERROR: {error}", file=sys.stderr)
            print(f"validation failed with {len(self.errors)} error(s)", file=sys.stderr)
            raise SystemExit(1)
        print("validation passed")
        print(f"registered skills: 1")
        print(f"lazy references: {len(EXPECTED_REFERENCES)}")
        print(f"runtime words: {word_count}/{WORD_BUDGET}")
        print("runtime dependencies: 0")


def frontmatter(path: Path, validator: Validator) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        validator.errors.append(f"{path.relative_to(ROOT)}: cannot read: {exc}")
        return {}
    match = re.match(r"\A---\n(.*?)\n---(?:\n|\Z)", text, re.DOTALL)
    validator.require(match is not None, f"{path.relative_to(ROOT)}: missing YAML frontmatter")
    if match is None:
        return {}
    values: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        validator.require(bool(separator), f"{path.relative_to(ROOT)}: malformed frontmatter line: {line}")
        if separator:
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def main() -> None:
    validator = Validator()

    manifest_path = PLUGIN / ".codex-plugin" / "plugin.json"
    marketplace_path = ROOT / ".agents" / "plugins" / "marketplace.json"
    manifest = validator.load_json(manifest_path)
    marketplace = validator.load_json(marketplace_path)

    required_manifest = {
        "name",
        "version",
        "description",
        "author",
        "homepage",
        "repository",
        "license",
        "keywords",
        "skills",
        "interface",
    }
    validator.require(
        required_manifest <= manifest.keys(),
        f"plugin manifest missing: {sorted(required_manifest - manifest.keys())}",
    )
    validator.require(manifest.get("name") == "codexstack", "plugin name must be codexstack")
    validator.require(
        bool(re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get("version", "")))),
        "plugin version must be semantic x.y.z",
    )
    validator.require(manifest.get("license") == "MIT", "plugin license must be MIT")
    validator.require(manifest.get("repository") == "https://github.com/d3vhound/codexstack", "repository URL is wrong")
    interface = manifest.get("interface")
    validator.require(isinstance(interface, dict), "plugin interface must be an object")
    if isinstance(interface, dict):
        short_description = interface.get("shortDescription")
        validator.require(
            isinstance(short_description, str) and len(short_description) <= 30,
            "plugin shortDescription must be at most 30 characters",
        )
        validator.require(
            interface.get("capabilities") == ["Interactive", "Read", "Write"],
            "plugin capabilities must declare Interactive, Read, and Write",
        )

    skills_value = manifest.get("skills")
    validator.require(isinstance(skills_value, str), "manifest skills must be a relative string path")
    if isinstance(skills_value, str):
        skills_path = (PLUGIN / skills_value).resolve()
        validator.require(inside(skills_path, PLUGIN), "manifest skills path escapes the plugin")
        validator.require(skills_path == SKILLS.resolve(), "manifest skills path must resolve to plugins/codexstack/skills")

    plugins = marketplace.get("plugins")
    validator.require(isinstance(plugins, list) and len(plugins) == 1, "marketplace must register exactly one plugin")
    if isinstance(plugins, list) and len(plugins) == 1 and isinstance(plugins[0], dict):
        entry = plugins[0]
        validator.require(entry.get("name") == "codexstack", "marketplace plugin name must be codexstack")
        source = entry.get("source")
        validator.require(isinstance(source, dict), "marketplace source must be an object")
        if isinstance(source, dict):
            validator.require(source.get("source") == "local", "marketplace source type must be local")
            local_path = source.get("path")
            validator.require(local_path == "./plugins/codexstack", "marketplace path must be ./plugins/codexstack")
            if isinstance(local_path, str):
                resolved = (ROOT / local_path).resolve()
                validator.require(resolved == PLUGIN.resolve(), "marketplace path does not resolve to the plugin")

    skill_files = sorted(SKILLS.glob("*/SKILL.md"))
    validator.require(len(skill_files) == 1, "plugin must expose exactly one registered skill")
    validator.require(skill_files == [WORK / "SKILL.md"], "the only registered skill must be work")

    metadata = frontmatter(WORK / "SKILL.md", validator)
    validator.require(metadata.get("name") == "work", "skill name must be work")
    validator.require(
        bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", metadata.get("name", ""))),
        "skill name must be lowercase kebab-case",
    )
    description = metadata.get("description", "")
    validator.require(bool(description), "skill description is required")
    validator.require(len(description) <= 1_024, "skill description exceeds 1,024 characters")

    actual_references = {path.name for path in (WORK / "references").glob("*.md")}
    validator.require(actual_references == EXPECTED_REFERENCES, "lazy reference set differs from the intended five routes")

    openai_yaml = WORK / "agents" / "openai.yaml"
    try:
        openai_text = openai_yaml.read_text(encoding="utf-8")
    except OSError as exc:
        validator.errors.append(f"{openai_yaml.relative_to(ROOT)}: cannot read: {exc}")
        openai_text = ""
    expected_openai_yaml = (
        'interface:\n'
        '  display_name: "CodexStack"\n'
        '  short_description: "Evidence-driven engineering workflows"\n'
        '  default_prompt: "Use $work to complete this engineering task with evidence and verification."\n'
        'policy:\n'
        '  allow_implicit_invocation: true\n'
    )
    validator.require(openai_text == expected_openai_yaml, "agents/openai.yaml differs from the validated schema")

    markdown_link = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for path in RUNTIME_FILES:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            validator.errors.append(f"{path.relative_to(ROOT)}: cannot read: {exc}")
            continue
        for target in markdown_link.findall(text):
            clean_target = target.split("#", 1)[0]
            if not clean_target or re.match(r"^[a-z][a-z0-9+.-]*:", clean_target, re.IGNORECASE):
                continue
            resolved = (path.parent / clean_target).resolve()
            validator.require(inside(resolved, WORK), f"{path.relative_to(ROOT)}: link escapes the skill: {target}")
            validator.require(resolved.is_file(), f"{path.relative_to(ROOT)}: broken link: {target}")

    runtime_text = "\n".join(path.read_text(encoding="utf-8") for path in RUNTIME_FILES if path.is_file())
    lowered_runtime = runtime_text.lower()
    forbidden = [
        ("cursor runtime", "cursor"),
        ("Cursor rule directory", ".cursor"),
        ("pstack mode command", "/poteto-mode"),
        ("loop command", "/loop"),
        ("Cursor question API", "askquestion"),
        ("Cursor agent field", "subagent_type"),
        ("Cursor background field", "run_in_background"),
        ("pstack agent type", "poteto-agent"),
        ("fixed Claude roster", "claude"),
        ("fixed Grok roster", "grok"),
        ("fixed model role", "fable"),
        ("fixed model role", "opus"),
        ("fixed Codex model slug", "gpt-5.6-sol-max"),
        ("Graphite-only workflow", "graphite"),
    ]
    for label, token in forbidden:
        validator.require(token not in lowered_runtime, f"runtime contains forbidden {label}: {token}")

    word_count = len(re.findall(r"\b[\w'-]+\b", runtime_text))
    validator.require(word_count <= WORD_BUDGET, f"runtime word budget exceeded: {word_count}/{WORD_BUDGET}")

    unfinished_token = "TO" + "DO"
    for path in [ROOT / "README.md", ROOT / "AGENTS.md", *RUNTIME_FILES]:
        text = path.read_text(encoding="utf-8")
        validator.require(unfinished_token not in text and "TBD" not in text, f"{path.relative_to(ROOT)}: unfinished marker")

    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    notice_text = (ROOT / "NOTICE.md").read_text(encoding="utf-8")
    validator.require("MIT License" in license_text, "LICENSE must contain the MIT license")
    validator.require("Lauren Tan" in license_text and "Lauren Tan" in notice_text, "upstream author attribution is missing")
    validator.require(UPSTREAM_COMMIT in notice_text, "NOTICE must pin the audited upstream commit")
    validator.require("MIT" in notice_text, "NOTICE must identify the upstream MIT license")

    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    validator.require(
        "codex plugin marketplace add d3vhound/codexstack" in readme_text,
        "README is missing the marketplace installation command",
    )
    validator.require(
        "codex plugin add codexstack@codexstack" in readme_text,
        "README is missing the plugin installation command",
    )

    validator.finish(word_count)


if __name__ == "__main__":
    main()
