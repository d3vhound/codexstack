# Repository guidance

CodexStack is a Codex plugin distributed through the marketplace in this repository. Skills own judgment; tiny standard-library scripts enforce only state, revision, and plan-shape invariants.

## Source of truth

- The plugin manifest is plugins/codexstack/.codex-plugin/plugin.json.
- The engineering entry point is plugins/codexstack/skills/work/SKILL.md.
- The explicit cloud-environment entry point is plugins/codexstack/skills/box/SKILL.md.
- The thin Box control runtime is plugins/codexstack/runtime/codexstack_control/.
- Repository setup and verification are declared in .codexstack/worker.json.
- Supporting contracts live beside each skill in references/.
- The repository marketplace is .agents/plugins/marketplace.json.

## Constraints

- Keep the engineering router concise and progressively disclose only matched references.
- Keep both skills explicit-only. Work mirrors Poteto Mode activation; Box also handles authentication and remote hosts.
- Use native Codex plans, subagents, worktrees, plugins, MCP, and model controls. Optional role templates may name currently documented Codex models but the workflow must degrade when they are unavailable.
- Do not add Cursor paths, slash-command assumptions, Graphite-only workflows, or a second agent scheduler.
- Every multi-step plan must expose matched gates and retain skipped gates with reasons.
- Program coordinators do not edit product code. One actor owns each mutable target and stack topology.
- Preserve read-only boundaries and explicit user authority for merges, deployments, shared-history rewrites, PR closure or retargeting, destructive cleanup, and external communication.
- Preserve the upstream license and NOTICE attribution.
- Update README.md and evals/scenarios.md when behavior changes.

## Verification

Run all repository checks:

~~~bash
python3 scripts/validate.py
python3 -m unittest discover -s tests -v
~~~

For a release, also run the current OpenAI skill and plugin validators and forward-test the relevant scenarios in evals/scenarios.md.
