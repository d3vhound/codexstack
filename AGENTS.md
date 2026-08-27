# Repository guidance

CodexStack is a skills-only Codex plugin distributed through the marketplace in this repository.

## Source of truth

- The plugin manifest is plugins/codexstack/.codex-plugin/plugin.json.
- The runtime entry point is plugins/codexstack/skills/work/SKILL.md.
- Supporting playbooks live beside that skill in references/.
- The repository marketplace is .agents/plugins/marketplace.json.

## Constraints

- Keep one registered runtime skill unless a new entry point has a genuinely distinct goal.
- Keep all runtime instructions under 4,000 words.
- Use native Codex concepts. Do not add Cursor paths, slash-command modes, hardcoded model rosters, Graphite-only workflows, or custom orchestration dependencies.
- Preserve read-only boundaries and explicit user authority for merges, deployments, shared-history rewrites, PR closure or retargeting, destructive cleanup, and external communication.
- Preserve the upstream license and NOTICE attribution.
- Update README.md and evals/scenarios.md when behavior changes.

## Verification

Run:

~~~bash
python3 scripts/validate.py
~~~

For a release, also run the current OpenAI skill and plugin validators and forward-test the relevant scenarios in evals/scenarios.md.
