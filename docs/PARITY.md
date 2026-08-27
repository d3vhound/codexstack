# pstack parity ledger

CodexStack preserves pstack's operating behavior and replaces its Cursor-specific execution layer with native Codex facilities. This is a traceability ledger, not a claim that filenames or prompts are identical.

## Audit basis

The source audit covered every one of the 157 files under `cursor/plugins/pstack` at commit [`fdf357fae76feff7e5f2e5aaff57f99f644b55f8`](https://github.com/cursor/plugins/commit/fdf357fae76feff7e5f2e5aaff57f99f644b55f8), plus the user-supplied root Poteto Mode specification.

The audit included:

- the plugin manifest, README, license, and ignore rules;
- both agent roles;
- all 45 top-level skills, including all 21 principle skills;
- all 23 Poteto playbooks and the Bugbot triage reference;
- every guide page and all six guide images;
- all 20 Poteto scripts, tests, wrappers, locks, and build files;
- the `show-me-your-work` logger and template; and
- every Benny automation document and template.

The target is behavioral parity inside the documented Codex authority boundaries: the same choices, ownership rules, evidence standards, and stop conditions should occur for the same request. CodexStack compresses repeated prose into one router and thirteen lazy work contracts.

## Preserved contracts

These invariants define parity. An implementation that omits one is smaller, but it is not the same operating method.

| Contract | CodexStack behavior |
| --- | --- |
| Visible workflow gates | The first multi-step plan item reads the complete compact Principles section. The matched workflow's named states are copied verbatim before task-specific steps. A skipped gate remains visible with a concrete reason. |
| Explicit activation | Work is opt-in through `$codexstack:work`, CodexStack, Poteto mode, or a direct request for that style, then stays active for terse follow-ups until stop or task change. |
| Throughput checkpoint | Before fan-out, name blocking first steps, independent streams, shared mutable state, and the smallest safe decomposition. |
| Lead ownership | The root agent owns the outcome, inspects every result, integrates, and independently verifies. |
| Writable isolation | One owner per mutable file set, worktree, branch, state record, and stack topology. |
| Empirical posture | Inspect or probe observable facts instead of asking the user. Ask only for preference, authority, unavailable access, or an irreversible choice. |
| Change evidence | Bug: reproduce, mechanism, fix, same repro passes. Performance: baseline, cause, comparable after. Refactor: pin, reshape, equivalence. Visual: immutable baseline, zero unexplained difference. |
| Forensic evidence | Artifact, mechanism, and source map. Wrong-surface or inconclusive evidence is not a pass. |
| Deliberation | Architect, Arena, Swarm, and Interrogate retain distinct candidate, coverage, judge, and synthesis contracts. |
| Historical intent | `why` federates every available category, records nulls and unavailable sources, and uses a separate synthesizer. Its tiers remain exactly Direct, Supported, Inferred, Speculative, and Unknown. |
| Delivery identity | Readiness and review bind to the exact PR head SHA. A verified stack is only the contiguous verified prefix. |
| Autonomous boundaries | Full and stack autopilot remain different modes. They state their mode, wait for explicit `go`, and stop writes immediately on request. |
| Program control | The coordinator writes state and briefs, not product code. It pilots, maintains a bounded rolling window, reconciles agents by side effects, and finishes with zero live children. |
| Reviewable trail | Long, autonomous, multi-phase, and unattended runs keep one append-only evidence trail, audit it against actual run artifacts, and receive a fresh independent review before an `Attention` handoff. |
| Authority | Opening, checking, readiness, and landing remain separate. Merge, deployment, destructive cleanup, credential expansion, and external messages require matching authority. |
| Dual PR gates | Babysit stops on upstream-compatible `babysit_ready`. Every Land mutation separately requires a fresh exact-head `provider_landing_gate_clear` plus independent PASS or PASS+NOTES, contiguous-prefix membership, unchanged identity, and authority. |
| Proportionality and candor | Tiny work stays tiny. The agent reports false premises, gaps, negative results, and uncertainty instead of manufacturing agreement. |
| Principle trace | Every handoff names each applied principle and the specific decision it changed. Consumer impact comes before implementation detail, followed by what the maintainer inherits. |

## All 23 Poteto playbooks

The concise Codex-native numbered sequences live in `playbooks.md`. Those are the exact states copied into a visible plan. The deeper references named below supply the evidence and authority rules behind each state.

| Upstream playbook | CodexStack contract | Preserved behavior |
| --- | --- | --- |
| `authoring-a-skill` | `quality.md` | Use the native skill and plugin authoring process, keep the entry point small, validate structure, and evaluate selection. |
| `autonomous-run` | `autonomy.md` | One falsifiable predicate, event-driven wakeups with a bounded heartbeat, smallest experiment, keep or revert, and a decision trail. |
| `autopilot-full` | `autonomy.md`, `delivery.md`, `bugbot-triage.md` | Declare full mode, state then wait for `go`, assign one lifecycle owner per PR, triage automation skeptically, verify exact SHAs independently, and land only under explicit authority. |
| `autopilot-stack` | `autonomy.md`, `delivery.md`, `bugbot-triage.md` | Declare stack mode, state then wait for `go`, keep one topology writer, triage automation skeptically, validate the contiguous prefix, and never merge. |
| `babysit` | `delivery.md`, `bugbot-triage.md` | Monitor the requested scope, wake on events with a fallback heartbeat, skeptically triage automated findings through the learned rubric, and stop at the requested boundary. |
| `bug-fix` | `change.md` | Reproduce the matching user surface, isolate the mechanism, fix the root cause, and rerun the same reproduction. |
| `eval` | `evaluate.md` | Freeze cases and rubric, separate builders from judges, blind where possible, repeat consequential cases, and keep only measured improvements. |
| `feature` | `change.md`, `deliberate.md` | Define observable behavior and the authoritative data shape, test a real design fork when one exists, then verify the whole path. |
| `hillclimb` | `change.md` | Establish a score, make one bounded change, measure on equivalent inputs, keep gains, and revert losses. |
| `investigation` | `investigate.md` | Remain read-only, anchor in real code and state, separate facts from inference, and return evidence plus gaps. |
| `multi-phase-plan` | `playbooks.md`, `delivery.md`, `orchestrate.md` | Produce the fixed audited skeleton before implementation, including dependencies, unit/live/perf proof, ten independent exact-head live lanes, interaction review gates, and ordered delivery layers. |
| `opening-a-pr` | `delivery.md` | Inspect repository policy, run relevant checks, push the intended branch, open one accurate PR, and do not imply readiness or landing. |
| `orchestrate` | `orchestrate.md` | Coordinator isolation, complete briefs, durable state, pilot, rolling window, event queue, bounded retries, integration frontier, liveness reconciliation, and final child reconciliation. |
| `pause-safely` | `delivery.md`, `orchestrate.md` | Stop spawning, checkpoint exact state and ownership, reconcile children, preserve recoverable work, and leave one concrete resume action. |
| `perf-issue` | `change.md` | Capture a comparable baseline, prove the cause, change one mechanism, measure under equivalent conditions, and report cost as well as gain. |
| `prototype` | `change.md` | Define the decision and criteria, build the smallest disposable probe, compare real observations, recommend, and avoid silent production adoption. |
| `refactoring` | `change.md` | Pin behavior, move structure in verifiable units, migrate callers, delete obsolete paths, and prove equivalence beyond compilation. |
| `runtime-forensics` | `investigate.md` | Preserve the raw runtime artifact, correlate clocks and identities, trace the mechanism, and map conclusions back to source. |
| `session-pickup` | `delivery.md`, `orchestrate.md` | Rebuild state from live repository and durable records, distrust stale summaries, reconcile active work, and resume at the next safe unit. |
| `shipping` | `delivery.md` | Separate Open, Check, Ready, and Land; diagnose blockers in order; bind proof to the current head; land only when authorized. |
| `trace-forensics` | `investigate.md` | Preserve the trace, derive a timeline before a story, correlate spans with runtime and source, and label gaps. |
| `visual-parity` | `change.md` | Keep an immutable baseline, control viewport and data, compare the real render, and require zero unexplained differences. |
| `worktree-cleanup` | `delivery.md` | Resolve exact worktrees and ownership first, preserve unique work, require authority for destructive removal, and verify final Git state. |

The upstream Bugbot triage contract maps to the lazy `bugbot-triage.md` reference, routed by `review.md` and `delivery.md`. It preserves exact-head fix, evidence-backed dismiss, and high-risk ask decisions, plus the learned-pattern boundaries and post-Babysit promotion loop. A bot report never overrides direct inspection.

## Both upstream roles

| Upstream role | CodexStack mapping |
| --- | --- |
| `poteto-agent` | The `$codexstack:work` lead. It routes, owns the visible plan, delegates through complete briefs, reads results, integrates, verifies, and hands back evidence. |
| `comment-sicko` | A fresh read-only quality reviewer under `review.md` and `quality.md`. The useful behavior survives: challenge comments and suppressions, preserve only proven constraints, and let the lead accept or reject each finding. The persona does not. |

Optional Codex agent TOML files provide Explorer, Architect, Implementer, Judge, and Verifier defaults. They are accelerators, not dependencies. If only one model family is available, CodexStack uses fresh isolated contexts, discloses the fallback, and does not call agreement cross-model confirmation.

## All 21 principles

All principle contracts live in `gates-and-laws.md`; matching task references apply their concrete consequences.

| Upstream principle | Preserved operational test |
| --- | --- |
| `boundary-discipline` | Parse external data once at the boundary and keep invalid states out of trusted code. |
| `build-the-lever` | For every non-trivial task, produce the smallest rerunnable codemod, script, generator, query, verifier, or delegate-skill file. For repeated work, hand-build one unit, rerun the lever on it, and diff before fan-out. No file means the principle was not applied. |
| `encode-lessons-in-structure` | Prefer a type, test, lint rule, verifier, or script that prevents recurrence over prose that asks people to remember. |
| `exhaust-the-design-space` | For a real consequential fork, compare independent viable shapes before committing. |
| `experience-first` | Choose user delight over implementation convenience for product and UX tradeoffs, then prove the result on the real interaction surface. |
| `fix-root-causes` | Demonstrate the causal mechanism and remove it. Do not weaken the symptom or the check. |
| `foundational-thinking` | Settle load-bearing types, contracts, and proof machinery before dependent work. |
| `guard-the-context-window` | Delegate raw corpus reading and return compact evidence; resend complete briefs after compaction. |
| `laziness-protocol` | Spend rigor only where it changes risk or confidence. Avoid ceremony and duplicate deliberation. |
| `make-operations-idempotent` | A retry is safe, and interrupted work can be reconciled from observed state. |
| `migrate-callers-then-delete-legacy-apis` | Move all owned callers, keep compatibility only for a proven external contract, then delete the old path. |
| `minimize-reader-load` | Use the repository's real names, one name per concept, and the shortest complete explanation. |
| `model-the-domain` | Give domain states and transitions one authoritative representation; make illegal states hard to construct. |
| `never-block-on-the-human` | Continue reversible work and empirical discovery while waiting for a true human gate. |
| `outcome-oriented-execution` | During a planned rewrite or migration, declare phase boundaries, allow only scoped reversible intermediate instability, keep high-signal touched-area checks green, avoid throwaway compatibility, and prove the full target at completion. |
| `prove-it-works` | Exercise the real artifact on the matching surface and report what was observed. |
| `redesign-from-first-principles` | At the first integration of a new requirement, ask for the holistic day-one design and propagate it through types, code, docs, examples, and rationale. Repeated deviations reopen that design. |
| `separate-before-serializing-shared-state` | Split mutable ownership or use isolated worktrees before adding coordination or locks. |
| `sequence-verifiable-units` | Order work into independently checkable units and verify each before building on it. |
| `subtract-before-you-add` | Remove obsolete paths and accidental complexity before introducing another layer. |
| `type-system-discipline` | Represent invariants in types, validate unknown data, avoid unchecked casts, and exhaust variants. |

## All 23 auxiliary skills

| Upstream skill | CodexStack mapping |
| --- | --- |
| `architect` | `deliberate.md`: Ground, Sketch with multiple candidates, optionally Agree, Implement, and Scrap; repeated deviations reopen the design. |
| `arena` | `deliberate.md`: same frozen brief, hidden rubric, isolated candidates, cross-judge, base plus explicit grafts, and reframe on material divergence. |
| `automate-me` | `quality.md`: discover and update an existing personal mode in place, mine only active-workspace recent evidence, corroborate slices, ask a small structured interview, create an explicit-only Codex mode, and get user review before landing. |
| `blast-radius` | `investigate.md`: find the few safety facts the change depends on and climb the proof ladder toward a real execution. |
| `bro` | `quality.md`: restate in plain, concise human language without jargon. |
| `create-verification-skill` | `quality.md`: interview Surface, Run, Drive, Observe, and Isolate; generate Launch, Doctor, Drive, Evidence, Cleanup, and Helpers; map user-facing features; prove one feature end to end with surviving evidence. |
| `figure-it-out` | `autonomy.md`, `orchestrate.md`: route large, cross-cutting, unattended, or no-fit work through a framed bespoke workflow, riskiest-first units, hypothesis verdicts, an audited trail, and whole-artifact proof. |
| `how` | `investigate.md`: Explain traces the current mechanism; Critique explains first, then uses independent rubric-driven critics and lead dispositions. |
| `interrogate` | `deliberate.md`, `review.md`: same-prompt independent reviewers, agreement map, lead disposition as Act, Consider, Noted, or Dismissed. |
| `maintain-verification-skill` | `quality.md`: source-audit every feature in parallel, drive every feature live, preserve doctor, cleanup, and evidence invariants, edit verifier files only, and end clean, changed, or blocked with at most one proven PR. |
| `make-bot-ui` | Not ported. It is tied to Cursor Grok Bot routines, secret-request UI, and Tailscale hosting. Box support is separate and uses native Codex and explicit credential authority. |
| `no-comments` | `quality.md`, `review.md`: fresh review of comments and suppressions, evidence for constraints, fix accepted findings, and independent lead judgment. |
| `recall` | `investigate.md`: scope the window and workspace, combine prior context with the shared record, verify live state, and return tagged threads plus one next move. |
| `reflect` | `deliberate.md`, `quality.md`: divergent, tooling, and judgment lenses; an untrusted transcript; structural fixes first; skill edits only with approval. |
| `setup-pstack` | `model-setup.md` preserves persistent choices for every role and panel, current-value display, detected-ID validation, `inherit-parent`/`auto`, panel-size semantics, idempotent project or personal policy updates, and the verifier offer. A passive validator replaces Cursor's always-applied rule. |
| `show-me-your-work` | The program ledger and deterministic state helper record decisions, units, gates, actors, evidence, and exact revisions. Close audits the append-only trail against actual run evidence, sends it to a fresh independent reviewer, and ends with row-specific `Attention`. |
| `swarm` | `deliberate.md`: declare partition, race, or mixed mode; predeclare selection; use disjoint outputs; reconcile PASS, ISSUES, or BLOCKED. |
| `tdd` | `change.md`: add a failing regression first when the check is cheap and meaningful, then prove the same behavior after the fix. |
| `teach` | `investigate.md`: combine mechanics and calibrated intent into a plain, layered explanation; remain read-only. |
| `technical-writing` | `quality.md`: pick the document mode, use concrete repository names, cut filler, and optimize for the reader's task. |
| `typescript-best-practices` | `quality.md`: semantic TypeScript rules for domain variants, unknown boundaries, narrowing, exhaustiveness, and real tests. Repository rules win. |
| `unslop` | `quality.md`: remove filler, vague claims, synonym churn, and formatting noise without erasing human voice. |
| `why` | `investigate.md`: seven-category evidence federation, one investigator per available category, null accounting, separate synthesis, and exact confidence tiers. |

## Scripts, guides, automation, and packaging

| Upstream material | Decision in CodexStack |
| --- | --- |
| `bootstrap.ts` | Native Codex plans and plugin routing expose matched gates without a bootstrap runtime. |
| `check-plan.mjs` | `check_plan.py` passively audits the fixed multi-phase skeleton, proof blocks, dependencies, interaction gate, and delivery shape without launching agents. |
| `orch/orch.ts`, `orch/store.ts`, tests | Preserve durable state, frontier, gates, inbox, ledger, retries, stop, and reconciliation in a standard-library helper. Native Codex performs scheduling and delegation. |
| `watch-pr/*`, tests, wrapper | Preserve upstream Babysit completion for clean exact-head checks with explicit non-conflict merge states and `REVIEW_REQUIRED` or null review, while malformed, missing, or stale snapshot evidence fails closed. A separate `provider_landing_gate_clear` signal requires positive `MERGEABLE`, `CLEAN`, and approval or an explicit no-review rule; it is neither Land authority nor full merge eligibility. Stack classification scans every row by blocker tier. Native `git`, `gh`, and Codex handle observation and action. |
| `worktree-audit.sh` | `worktree_audit.py` parses exact Git-listed worktree paths and combines local merge/WIP facts with bounded current active, pinned, last-used, and exact-head PR evidence. It fails uncertain rows to review and returns advice only; native Git performs any separately authorized cleanup. |
| `package.json`, `bun.lock`, `tsconfig.json` | Not needed for the zero-dependency helpers. Removing a package runtime is an implementation change, not a behavioral change. |
| `show-me-your-work/log.sh` and TSV template | Replaced by atomic JSON state and append-only JSONL evidence records for programs, or an ignored local TSV for one bespoke run. Both retain actor, time, unit, decision, proof, and exact revision and use the same close audit. |
| Ten guide chapters and six images | Their routing, design, understanding, verification, overnight, principles, recipes, and failure modes are compressed into the router, references, README, parity ledger, and evals. |
| Benny automation pack | Intentionally excluded from core. It depends on Cursor automation facilities and broad cloud authority. CodexStack uses native bounded agents and optional ASCII Box workers. |
| `.cursor-plugin/plugin.json` | Replaced by `.codex-plugin/plugin.json` and `.agents/plugins/marketplace.json`. |
| Upstream README, license, and ignore rules | Rewritten for Codex installation and safety. Attribution and the MIT license remain. |

## Intentional Codex divergences

CodexStack does not emulate product syntax. It removes or replaces:

- Cursor `Task`, `subagent_type`, `run_in_background`, slash-command, sticky-command, provider-panel, and `.cursor` path instructions;
- hardcoded legacy model rosters, while retaining model diversity as a confidence tool;
- Graphite as a required stack and landing runtime;
- a custom agent scheduler or long-lived orchestration database;
- Cursor Grok Bot UI and Benny automations; and
- implicit authority to merge, deploy, rewrite history, delete shared work, send messages, or propagate credentials.
- upstream's non-draft PR default remains the default, while an explicit current draft request or mandatory repository policy takes precedence and is recorded.
- upstream may continue some reversible external actions inside Autonomy and routinely opens PRs at change-playbook close. CodexStack instead requires matching authority for push, PR mutation, and messages. This is an intentional Codex safety boundary outside the core workflow and proof-parity claim.

Codex-native plans, subagents, worktrees, plugins, skills, MCP, Git, and GitHub CLI replace those mechanics. Small deterministic helpers may classify state or record evidence. They never decide goals, spawn agents, or widen authority.

Optional ASCII Box support is an extension, not part of pstack parity. It makes the same plugin usable on a persistent cloud VM while keeping ChatGPT sign-in, GitHub credentials, MCP secrets, snapshots, and paid compute behind explicit user control.
