# CodexStack

Poteto-grade engineering for Codex, without the Cursor runtime.

CodexStack gives Codex the part of pstack that creates throughput: visible gates, evidence before claims, model-diverse deliberation, isolated writable ownership, exact-revision delivery, and bounded autonomous programs. The port is intentionally small. Native Codex plans, subagents, worktrees, skills, plugins, and MCP do the work; CodexStack supplies the operating contract.

## Install

Add this repository as a Codex plugin marketplace, then install the plugin:

```bash
codex plugin marketplace add d3vhound/codexstack
codex plugin add codexstack@codexstack
```

Start a new Codex session. Then ask for the outcome in normal language:

```text
Reproduce the account-switching bug, fix the root cause, and prove the same repro passes.

Explain how cancellation works and why this boundary exists. Do not change code.

Build this feature. Use independent agents where that improves confidence or speed.

Run this as a durable program. Stop all writes if I say stop.
```

The core workflow is explicit-only, like upstream Poteto Mode. Invoke `$codexstack:work` or directly ask for CodexStack/Poteto-style execution; terse follow-ups then remain inside that workflow:

```text
$codexstack:work Check whether PR 418 is ready. Do not merge it.
```

The IDE can install the core skill directly from [`plugins/codexstack/skills/work`](plugins/codexstack/skills/work). Invoke a standalone install as `$work`.

## What you get

The lead agent still owns the result. Subagent reports are evidence, not proof.

- Every matched gate appears in the plan. A skipped gate stays visible with a concrete reason.
- The first multi-step plan item reads the full compact Principles contract. The selected one of 23 matched playbooks is then copied verbatim into the plan before task-specific work.
- Before fan-out, Codex identifies blocking first steps, independent streams, shared mutable state, and the smallest safe split.
- Every non-trivial task produces a rerunnable lever file that performs or proves the work. Repeated work gets a hand-built pilot, a lever rerun, and a diff before scale.
- Architect, Arena, Swarm, and Interrogate use different topologies for design, competing candidates, coverage, and adversarial judgment.
- Bug, performance, refactor, and visual work use explicit before-and-after evidence state machines.
- `how` traces current mechanics and Critique explains before challenging architecture. `why` searches each available historical evidence category and labels confidence as Direct, Supported, Inferred, Speculative, or Unknown.
- Large, cross-cutting, no-fit, and unattended runs use a bespoke Figure it out workflow. They close with an audited append-only evidence trail, a fresh reviewer, and row-specific `Attention` flags.
- Project verifier creation interviews the repository, maps user features, and proves one real path. Maintenance source-checks and live-drives every mapped feature without editing product code.
- PR verdicts bind to the exact head SHA. A changed head invalidates the verdict until it is checked again.
- Full autopilot may land only with explicit authority. Stack autopilot maintains one ordered topology and never merges.
- A program coordinator owns briefs, state, gates, and reconciliation. It does not edit product code.
- Trivial work stays trivial. Read-only work stays read-only.
- The handoff leads with consumer and maintainer impact, then traces each applied principle to the concrete decision it changed.

The core has one router with lazy reference files instead of dozens of overlapping commands. See [the parity ledger](docs/PARITY.md) for the full source-to-contract mapping.

Optional Explorer, Architect, Implementer, Judge, and Verifier templates live in [`plugins/codexstack/skills/work/assets/agents`](plugins/codexstack/skills/work/assets/agents). Copy only the roles you want into a repository's `.codex/agents/` directory or your user-level `~/.codex/agents/` directory. Review their model names and sandbox modes first; the core workflow works without them.

Per-role models and panel sizes are also configurable. Ask `$codexstack:work` to configure CodexStack models. It detects only model IDs exposed to the active session, shows every role and panel, validates the selection, and writes a project or personal policy. `inherit-parent` and `auto` remain portable fallbacks.

Five standard-library helpers enforce the small pieces native orchestration should not guess. [`state.py`](plugins/codexstack/skills/work/scripts/state.py) keeps atomic program state, topology-safe frontiers, leases, inbox, audited stop and release history, and exact-SHA verdicts. [`pr_readiness.py`](plugins/codexstack/skills/work/scripts/pr_readiness.py) classifies already-fetched PR snapshots and advances a frozen owner/repository/PR queue while rechecking changed heads. It reports upstream-compatible `babysit_ready` separately from the stricter evidence-only `provider_landing_gate_clear`. Babysit stops on the first; every authorized Land mutation additionally requires a fresh exact-head second signal plus independent proof, contiguous-prefix membership, unchanged identity, and authority. [`check_plan.py`](plugins/codexstack/skills/work/scripts/check_plan.py) audits the fixed multi-phase proof skeleton. [`worktree_audit.py`](plugins/codexstack/skills/work/scripts/worktree_audit.py) classifies exact Git worktree records from bounded local and supplied PR/use evidence without deleting anything. [`model_policy.py`](plugins/codexstack/skills/work/scripts/model_policy.py) validates persistent role choices against model IDs already observed in the current session. None launches, polls, schedules, fetches, merges, or deletes.

## Optional cloud agents with ASCII Box

ASCII Box can run the same Codex workflow in a persistent Ubuntu VM. Its native Codex sign-in can use ChatGPT plan-backed Codex access, including your Pro subscription. Choose **Sign in with ChatGPT** in Box instead of supplying an OpenAI API key.

One-time setup:

1. In the Box dashboard, create a private environment named `codexstack`.
2. Keep **Safe for third parties** off for this owner-only environment. Enable GitHub credentials and Agents credentials. Leave Box credentials off unless a task truly needs nested Box control.
3. Under **Agents → Codex → ChatGPT**, choose **Sign in with ChatGPT** and finish the device flow with your ChatGPT account.
4. Never share a box or snapshot created from this credential-bearing environment.

Launch and steer a worker:

```bash
box new --environment codexstack --ttl 43200
box prompt <box-id> --provider codex 'Use $codexstack:work. Fix the bug, prove it, and open a PR. Do not merge.'
box events <box-id> --follow
```

To redirect a running managed turn, use `box interrupt <box-id>` and then send the revised `box prompt`. Use `box ssh <box-id>` for an interactive shell. Inside the box, verify access and install CodexStack once if the image does not already contain it:

```bash
codex login status
gh auth status
codex plugin marketplace add d3vhound/codexstack
codex plugin add codexstack@codexstack
codex mcp list
```

Box snapshots preserve `/home/user`, so Codex login state, plugin installs, user skills, and GitHub CLI configuration survive stop and resume. Snapshots can therefore contain credentials. Build reusable warm templates with `--no-env`, then start private copies with the private environment attached.

Commit only portable configuration:

| Concern | Portable project path | Keep out of Git |
| --- | --- | --- |
| Skills | `.agents/skills/` | Private transcript-derived skills unless intended |
| MCP registration | `.codex/config.toml` | Tokens, cookies, and OAuth artifacts |
| Plugin marketplace | `.agents/plugins/marketplace.json` | Installed-account state and credentials |
| GitHub workflow | Repository files | `~/.config/gh/hosts.yml` and tokens |

Use environment-variable names in committed MCP configuration, not secret values. Provider OAuth may need a one-time reconnect inside a new Box. The Box skill is explicit because launching paid compute and changing credential injection are authority-bearing actions:

```text
$codexstack:box Check this Box for Codex, GitHub, plugin, skill, and MCP readiness. Make no changes.
```

See the [ASCII Box quickstart](https://docs.ascii.dev/box/quickstart), [environments](https://docs.ascii.dev/box/environments), [long-running tasks](https://docs.ascii.dev/box/long-running-tasks), and [snapshot model](https://docs.ascii.dev/box/snapshots).

### Does a Box CLI session appear in ChatGPT mobile?

No. A standalone `codex` or `box prompt --provider codex` session on a Linux Box does not automatically appear in ChatGPT mobile just because it uses the same ChatGPT account.

The supported mobile route is [Codex Remote](https://developers.openai.com/codex/remote-connections): pair the mobile app with ChatGPT desktop on macOS or Windows, add the Box as an SSH host in the desktop app, and start or continue the chat through that connected host. Existing unrelated CLI threads are not imported into mobile.

## Behavioral parity, native implementation

CodexStack is a behavioral carbon copy of pstack's core workflow and proof obligations, not a file-for-file clone. Codex-native authority boundaries remain stricter for external mutations such as pushes, PR changes, merges, deployments, and messages.

| Preserved | Codex-native replacement |
| --- | --- |
| Poteto routing, explicit sticky mode, and matched gates | One explicit-only Codex skill router with natural-language steering after activation and lazy references |
| All 23 playbook step sequences | One matched-playbook registry whose numbered states are copied verbatim into native Codex plans |
| Candidate panels, investigators, judges, and workers | Native Codex subagents with optional model-role templates |
| Independent writable ownership | Codex worktrees or disjoint file scopes |
| Durable program frontier, ledger, and stop state | A small deterministic state helper; Codex remains the scheduler |
| PR watcher policy and exact-revision proof | A deterministic readiness classifier plus native GitHub tools |
| Multi-phase plan lint | A passive standard-library checker for unit, live, perf, interaction, dependency, and delivery proof blocks |
| Skill, review, and verification discipline | Codex skills, plugin packaging, and independent verification |

CodexStack does not port Cursor `Task` calls, `subagent_type`, slash commands, sticky-command UI, `.cursor` paths, Graphite as a requirement, the Cursor provider roster, Grok Bot UI, or Benny automation. It does not add a second agent scheduler. Merges, deployments, destructive operations, credential expansion, and external messages remain behind explicit user authority.

## Validate

```bash
python3 scripts/validate.py
python3 -m unittest discover -s tests -v
```

[`evals/scenarios.md`](evals/scenarios.md) is the forward-evaluation catalog for real Codex sessions. Executable unit tests enforce the critical runtime contracts and fail-closed helpers in CI. The [evaluation record](evals/RESULTS.md) separates what passed from the fresh-model cases this managed development runtime could not start.

## Sources and attribution

- [pstack](https://github.com/cursor/plugins/tree/main/pstack), audited at commit [`fdf357fae76feff7e5f2e5aaff57f99f644b55f8`](https://github.com/cursor/plugins/commit/fdf357fae76feff7e5f2e5aaff57f99f644b55f8)
- [OpenAI Codex authentication](https://developers.openai.com/codex/auth)
- [OpenAI Codex plugins](https://developers.openai.com/codex/plugins)
- [OpenAI Codex skills](https://developers.openai.com/codex/build-skills)
- [OpenAI Codex subagents](https://developers.openai.com/codex/agent-configuration/subagents)
- [OpenAI Codex MCP](https://developers.openai.com/codex/mcp)
- [OpenAI Codex worktrees](https://developers.openai.com/codex/environments/git-worktrees)
- [ASCII Box documentation](https://docs.ascii.dev/box)

See [`NOTICE.md`](NOTICE.md) for attribution. CodexStack is an independent adaptation. It is not affiliated with or endorsed by Lauren Tan, Cursor, ASCII, or OpenAI.

MIT licensed.
