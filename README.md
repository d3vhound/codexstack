# CodexStack

Depth before scale. Evidence before done.

CodexStack is a concise, Codex-native engineering workflow for non-trivial code work. It teaches Codex to understand the system first, use subagents only across real seams, make the smallest coherent change, and prove the result on the real artifact.

It is an independent adaptation of [pstack](https://github.com/cursor/plugins/tree/main/pstack) for Codex. It preserves the engineering method without carrying over Cursor-specific commands, model panels, agents, rules, Graphite runtime, or automation machinery.

## Install

~~~bash
codex plugin marketplace add d3vhound/codexstack
codex plugin add codexstack@codexstack
~~~

Start a new Codex session after installation.

Plugins are available in the Codex CLI and the ChatGPT desktop app:

- Codex CLI: invoke $codexstack:work.
- ChatGPT desktop: type @ and select CodexStack's Work skill.

The Codex IDE extension supports standalone skills rather than plugins. In the IDE, ask the skill installer to install the skill directly from:

~~~text
https://github.com/d3vhound/codexstack/tree/main/plugins/codexstack/skills/work
~~~

Invoke that standalone IDE install as $work.

## Use in Codex CLI

Invoke the workflow explicitly:

~~~text
$codexstack:work Reproduce this bug, fix the root cause, and prove the behavior.

$codexstack:work Explain how cancellation works and why it was designed this way. Do not change code.

$codexstack:work Review this branch adversarially. Report only findings you can substantiate.

$codexstack:work Build this feature. Use parallel agents where the work is truly independent, then verify it end to end.
~~~

Codex can also select it implicitly when the request calls for the workflow.

## The loop

~~~text
Classify → define observable done → ground → isolate work
→ make the smallest justified change → prove the real artifact
→ add fresh review when risk warrants it → hand back evidence
~~~

CodexStack keeps one registered skill and loads only the playbook the task needs:

| Route | Use |
| --- | --- |
| Change | Bugs, features, refactors, performance, prototypes, visual parity |
| Investigate | How, why, blast radius, architectural decisions, forensics |
| Review | Diffs, branches, PRs, architecture, comments and suppressions |
| Delivery | Plans, PR readiness, landing, long runs, pause/resume, cleanup |
| Evaluate | Blinded skill, prompt, and workflow tests |

## Why this shape

The audited pstack snapshot contains 45 top-level skills, 23 playbooks, about 85,000 words of Markdown, and more than 6,000 lines of scripts. Its durable behavior is much smaller. The quality comes from routing, evidence, isolation, verification, and lead-agent ownership.

CodexStack translates the underlying ideas into native Codex primitives:

| pstack / Cursor | CodexStack |
| --- | --- |
| Slash-command mode and many leaf skills | One $codexstack:work router with lazy references |
| Cursor task agents and fixed model panels | Native Codex subagents that inherit the user's model and reasoning |
| Cursor todo lists | Codex plans only when the work is genuinely multi-step |
| Shared agent writes | Disjoint scopes or separate Codex worktrees/checkouts |
| Cursor rules and sticky mode | Skill activation; optional project guidance belongs in AGENTS.md |
| Cursor loop command | A bounded exit predicate with durable checkpoints |
| Graphite-only PR shipping | Repository-native Git and GitHub flow, with stack tools only when the repo uses them |
| Custom PR watcher and orchestration database | Native tools and concise policy; no bundled runtime |
| Benny automation pack | Deferred as a separate future integration |

The package has no MCP server, hook, model dependency, executable runtime, or third-party package.

## What it deliberately changes

- Trivial edits stay trivial. No mandatory plan or subagent theater.
- Read-only questions remain read-only.
- Parallelism is proportional and bounded. One writable target has one owner.
- Models are not hardcoded. Codex and the user own model selection.
- Real behavior is the proof. Compilation and agent summaries are not enough.
- Review findings are verified and judged, not blindly aggregated.
- Merges, deployments, destructive cleanup, and external communication stay behind user authority.
- Comment cleanup is a code-quality rule, not a persona.

## Validate

~~~bash
python3 scripts/validate.py
~~~

The validator checks the marketplace, plugin manifest, skill metadata, reference graph, runtime word budget, provenance, and accidental Cursor-only instructions. CI runs the same command.

Behavioral cases live in [evals/scenarios.md](evals/scenarios.md). They cover trivial work, read-only investigation, a root-cause bug, a domain-shaped feature, an empirical fork, a behavior-preserving migration, parallel package work, and PR safety.

## Sources

- [pstack source](https://github.com/cursor/plugins/tree/main/pstack), audited at commit [fdf357f](https://github.com/cursor/plugins/commit/fdf357fae76feff7e5f2e5aaff57f99f644b55f8).
- [OpenAI: Build skills](https://developers.openai.com/codex/build-skills).
- [OpenAI: Codex subagents](https://developers.openai.com/codex/agent-configuration/subagents).
- [OpenAI: AGENTS.md](https://developers.openai.com/codex/agent-configuration/agents-md).
- [OpenAI: Package plugins](https://developers.openai.com/plugins/build/plugins).

See [NOTICE.md](NOTICE.md) for attribution. CodexStack is not affiliated with or endorsed by Lauren Tan, Cursor, or OpenAI.

## License

MIT.
