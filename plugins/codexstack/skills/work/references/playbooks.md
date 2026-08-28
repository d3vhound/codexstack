# Matched playbooks

Use this reference for every multi-step request. Select one primary playbook. Copy its numbered states into the visible plan verbatim before task-specific work. Keep an inapplicable state and give its concrete skip reason. Add Opening a PR only when publication is authorized. These contracts use native Codex delegation and monitoring. They do not create a scheduler.

## Investigation

1. **Route.** Trace current mechanics through How. Add Why only for motivation or history.
2. **Checkpoint.** Write `throughput checkpoint n/a, read-only investigation`.
3. **Answer.** Produce a cited mechanism trace or a recommendation with explicit tradeoffs.
4. **Prose.** Apply the quality contract and remain read-only.

## Bug fix

1. **Reproduce.** Drive the reported surface and capture the failure before editing.
2. **Find the cause.** Run How and Why in parallel, trace competing hypotheses, and confirm the surviving mechanism with runtime evidence.
3. **Plan the fix.** Run Architect for any crossed function or module boundary. Delegate one narrow implementation and review its diff.
4. **Verify.** Repeat the original reproduction on the same surface and run the focused regression checks.
5. **Order the proof.** Put a cheap failing reproduction before the fix in ordered commits when that path is practical.
6. **Open.** Run Opening a PR when publication is authorized.

## Perf issue

1. **Baseline.** Capture the reported workload, environment, trace, samples, and noise.
2. **Attribute.** Use How and measurement to identify the dominant source-level mechanism. Consider elimination, division, caching, indirection, batching, redundancy, lazy work, and scheduling only when the trace supports them.
3. **Plan the fix.** Run Architect across boundaries. Delegate one bounded change, review it, and capture an after trace.
4. **Compare.** Parse comparable artifacts and reject wrong-surface or inconclusive results.
5. **Record.** Put the baseline, after value, delta, and regression cost in the delivery record.
6. **Open.** Run Opening a PR when publication is authorized.

## Hillclimb

1. **Ground.** Fix a realistic workload, one metric, direction, minimum attempts, and checkable target.
2. **Freeze the lever.** Build a sensitive repeatable harness and record baseline plus a green correctness gate.
3. **Open the trail.** Record every hypothesis, before, after, tests, and keep or revert verdict.
4. **Form one hypothesis.** Name one mechanism from the architecture model.
5. **Run one iteration.** Isolate the change, measure, keep only a win beyond noise, revert the rest, and commit each accepted win alone.
6. **Push past a plateau.** Pivot category or combine evidenced near-misses without relaxing correctness.
7. **Stop honestly.** Meet the predicate or report why the remaining ideas do not earn their cost.
8. **Open.** Run Opening a PR with accepted commits in measured order.

## Runtime forensics

1. **Capture live signal.** Drive the real surface and save the matching profile, trace, snapshot, or instrumentation.
2. **Reduce.** Extract the hot path, retainer chain, loop, or failing transition from the artifact.
3. **Prove the mechanism.** Instrument the running process or use a disposable live probe.
4. **Map to source.** Name the file, symbol, and responsible allocation or schedule point.
5. **Throughput checkpoint.** Write exactly `throughput checkpoint: n/a, read-only forensics`.
6. **Diagnose.** Return evidence and paths without a fix. Route later repair to Bug fix or Perf issue.

## Trace forensics

1. **Load.** Identify the supplied artifact and use the matching parser.
2. **Shape.** Transform bulk data into a queryable sample, frame, node, or event table.
3. **Narrow.** Find the dominant path, retainer chain, blocked thread, or wait reason.
4. **Attribute.** Resolve artifact symbols to a source file, symbol, and line or disclose the gap.
5. **Confirm.** Compare a paired capture when available. Otherwise label the strongest supported hypothesis.
6. **Throughput checkpoint.** Write exactly `throughput checkpoint: n/a, read-only forensics`.
7. **Diagnose.** Return cited evidence without changing code.

## Feature

1. **How.** Trace the affected subsystem before design.
2. **Architect.** Run parallel design exploration whenever code crosses any function or module boundary. If no boundary is crossed, keep this state with the exact reason.
3. **Throughput checkpoint.** Write blocking first steps, independent workstreams, shared mutable state, and the smallest safe decomposition as four visible items.
4. **Delegate implementation.** Give one writable Codex agent the named data shape, organizing structure, exact paths, acceptance, and proof. This delegation is mandatory. The lead reviews the complete diff.
5. **Verify.** Exercise the complete behavior on the matching surface. Treat wrong-surface or inconclusive evidence as unverified.
6. **Order delivery.** Build, verify, and commit each small unit before the next. Keep dependent pull requests in that order.
7. **No-comments and Interrogate.** Run a fresh No-comments audit before review. If the design is contested, run Interrogate before shipping.
8. **Open.** Run Opening a PR when publication is authorized.

## Refactoring

1. **Pin behavior.** Trace How and capture a characterization or equivalence harness before moving structure.
2. **Name the missing shape.** Choose the state machine, table, registry, reducer, or typed model that removes scattered assumptions.
3. **Name the target.** Define the intended types, modules, and call graph. Run Architect across any boundary.
4. **Subtract.** Remove dead paths, redundant wrappers, and orphan references before adding structure.
5. **Move safely.** Delegate scoped mechanical edits. Keep the full pin green for ordinary refactors. For a planned rewrite or migration, declare phase boundaries and scoped reversible instability, keep selected touched-area checks green, migrate callers, delete the owned legacy API, and restore full static and runtime proof at completion without throwaway compatibility.
6. **Prove equivalence.** Compare the real artifact or matching surface. Compilation alone does not pass.
7. **Measure reader load.** Revert indirection that removes no branch, risk, or hidden state.
8. **Open.** Shape ordered, independently green commits and run Opening a PR.

## Prototype

1. **Decision.** State the empirical, interaction, layout, timing, or API choice the sketch will settle.
2. **References.** Gather prior art only when the direction remains open.
3. **Isolate.** Build the lightest throwaway artifact outside production source.
4. **Compare.** Put alternatives behind one labeled surface when useful.
5. **Observe.** Drive the matching surface and capture screenshots, output, timing, or render evidence.
6. **Recommend.** Present alternatives and hand the choice to Feature or Architect. Do not ship the prototype.

## Visual parity

1. **Capture baseline.** Freeze reference renders for every relevant state before migration.
2. **Lock the harness.** Do not alter baseline, crop, viewport, seed, threshold, or component shape to pass.
3. **Migrate one unit.** Give shared primitives one owner and isolate parallel component work.
4. **Diff the render.** Compare on the matching surface and investigate every nonzero pixel difference.
5. **Open.** Run Opening a PR per independently verified component or safe batch.

## Authoring or modifying a skill

1. **Author.** Use the Codex skill-creator contract and delete prose that changes no decision.
2. **Validate.** Check frontmatter, links, referenced files, scripts, and installation shape.
3. **Exercise.** Run structural cases and any bundled verifier. State why subjective cases cannot be automated.
4. **Open.** Run Opening a PR when publication is authorized.

## Eval

1. **Frame.** Freeze the variant and a hidden rubric with three to six observable criteria.
2. **Sanitize.** Give each isolated candidate an organic project path with no evaluation language.
3. **Prompt.** Use one natural user request with no chain-eliciting cues.
4. **Run blind.** Give multiple isolated candidates the same prompt without revealing peers or rubric.
5. **Judge blind.** Give one independent judge anonymized artifacts on one shared scale.
6. **Inspect behavior.** Use tool events, opened files, diffs, and proof instead of candidate self-report.
7. **Synthesize.** Read every output, explain disagreement, and recommend promote, revise, or reject.

## Babysit

1. **Declare mode.** State drive, background, threads-only, or check before the first status read.
2. **Hold the frontier.** Work only the lowest unmerged dependency. Keep mutation ownership there even when a whole-stack status scan reports an upper blocker.
3. **Keep one owner.** Use one readiness owner per stack.
4. **Freeze topology.** Never restack, retarget, force-push, close, or merge from readiness work.
5. **Order blockers.** Read the complete bottom-to-top stack tier-major across conflicts, unresolved threads, failing CI, and review or merge gates. Only after those tiers are clear select the first bottom-to-top pending row. Call the stack clear only when every row is ready or merged.
6. **Read provider truth.** Recheck exact-head merge state after every push or acted-on event.
7. **Classify CI.** Allow one fresh run for credible flake or infrastructure, then diagnose.
8. **Triage bots skeptically.** Use [bugbot-triage.md](bugbot-triage.md) to fix, dismiss with disproof, or escalate high-risk ambiguity.
9. **Stop at ready.** Report merge-ready or the human gate. Do not land.

## Shipping

1. **Verify independently.** Bind PASS, PASS+NOTES, or FAIL from a non-author verifier to every exact head.
2. **Compute the prefix.** Land only the contiguous verified run from the lowest dependency.
3. **Recheck identity.** Invalidate changed heads unless patch equivalence and base assumptions still hold.
4. **Arm safely.** Immediately before every authorized mutation, require a fresh exact-head `provider_landing_gate_clear` in addition to the independent verdict, contiguous prefix, unchanged identity, and authority. False or missing stops at the gap. Then use the repository provider or stack mechanism with expected-head protection.
5. **Avoid unsafe auto-merge.** Never use a mechanism that collapses child branches into parents.
6. **Confirm authority.** Read arming state from the authoritative provider rather than command success.
7. **Freeze the draining queue.** Capture the authorized bottom-to-top list once. Never rediscover, expand, reorder, or repair it after the queue starts.
8. **Observe the drain.** Hold the lowest unmerged row as frontier even when an upper row is pending. Treat a merged frontier as nonterminal ADVANCE and move immediately. Treat all frozen rows merged as terminal COMPLETE. Fail on close without merge or any tier-major blocker. Native Codex owns monitoring without a CodexStack scheduler or polling loop.
9. **Stop at the ceiling.** Report what landed and the next unverified gap.

## Autonomous run

1. **Define done.** State a checkable exit predicate before the first iteration.
2. **Choose a wake.** Use native event monitoring or a bounded recurring check with a fallback heartbeat.
3. **Advance one unit.** Make the smallest evidenced change, verify, commit progress, and discard misses.
4. **Own discoveries.** Repair reversible blockers in scope and isolate unrelated fixes.
5. **Checkpoint.** Persist each iteration and its predicate delta in the decision trail.
6. **Stop honestly.** Meet the predicate or record a real dead end without relaxing it.

## Orchestrate

1. **Frame.** Count the done predicate, scope, tracks, budget, and landing cutoff. Collapse to Autonomous run if one session can finish it.
2. **Install durable state.** Record standing orders, units, frontier, ledger, inbox, gates, decisions, and derived status before spawning.
3. **Pilot.** Push one representative unit through brief, implementation, proof, integration, and ledger. Fix the contract from evidence.
4. **Scale.** Refill a bounded rolling window with complete briefs and exclusive ownership. The coordinator does not edit product code.
5. **Drain.** Reconcile inbox events in batches, record one terminal verdict per unit, and relay dependencies through fresh briefs.
6. **Land continuously.** Keep one topology owner and advance only the contiguous exact-head verified frontier under granted authority.
7. **Close.** Reconcile every child, prove the real predicate, audit the trail, and leave durable state resumable.

## Autopilot-full

1. **State then wait.** Declare scope, owner items, landing authority, proof, and stop behavior. Start only on explicit go.
2. **Assign owners.** Give each independent pull request one lifecycle owner, one exclusive branch, and the [automated-review rubric](bugbot-triage.md).
3. **Run in parallel.** Keep writers disjoint and serialize only real overlap.
4. **Verify at exact head.** The root commissions independent gates, live behavior, and diff-receipt lanes before merge.
5. **Merge one controlled unit.** Let the owner merge only after the clean root verdict and exact-head recheck.
6. **Audit liveness.** Use native monitoring, side effects, and bounded retries. Reconcile before replacing a stalled lane.
7. **Stop writes.** Record an operator stop first, block new writes immediately, and reconcile read-only.

## Autopilot-stack

1. **Run owners.** Give each pull request one build-through-ready owner with an exclusive branch, decision trail, and the [automated-review rubric](bugbot-triage.md).
2. **Audit liveness.** Use native monitoring, side effects, and bounded replacement after reconciliation.
3. **State then wait.** Do not mutate before explicit go. A stop creates an immediate zero-write hold.
4. **Verify exact heads.** Root verification covers gates, live behavior, and receipts before append.
5. **Append only.** A clean verdict adds the pull request to one linear reviewed chain. Nobody merges.
6. **Keep one topology writer.** Owners push only their branches. One root owns order and stack mutations.
7. **Absorb drift.** Recompute descendants and reverify every materially changed head.
8. **Deliver the chain.** Hand the operator the bottom-up reviewed stack and retain merge authority with them.

## Session pickup

1. **Locate the trail.** Read the bounded prior note, transcript, branch, or provider record within the active workspace.
2. **Reconstruct state.** Resolve branch, worktree, diff, commits, provider state, decisions, and open items.
3. **Diff done and pending.** Name the resume point without redoing settled discovery.
4. **Route the remainder.** Continue, ratify, override with evidence, or postmortem through the matching playbook.
5. **Verify inheritance.** Check load-bearing inherited claims against the current real artifact.

## Pause safely

1. **Reach a safe boundary.** Finish or back out of the atomic step, start nothing new, and reconcile children.
2. **Do not expand authority.** Open no PR, push no branch, and cross no irreversible line merely to pause.
3. **Make work durable.** Preserve edits under existing commit authority and disclose any known broken state.
4. **Write the resume note.** Record intent, predicate, verified progress, branch and SHA, dirty paths, next action, and evidence.

## Multi-phase or multi-PR plan

1. **Qualify.** If one obvious change in one or two files suffices, say the plan is unnecessary and stop.
2. **Settle facts.** Use Prototype for observable forks. Ask only for a product preference no run can settle.
3. **Explore.** Delegate bounded read-only slices that return entry points, conventions, tests, and file pointers.
4. **Write the fixed skeleton.** Copy every heading and block below in order. One unit or pull request owns one change and its evidence.
5. **Write cleanly.** Treat the body as a how-to. Keep explanations and references in appendices.
6. **Check the plan.** Resolve `WORK_SKILL` to the directory containing the loaded Work `SKILL.md`, run `python3 "$WORK_SKILL/scripts/check_plan.py" <plan.md>`, and fix every finding.
7. **Hand back.** Report the plan path and check output, then stop until explicit go.

Copy this skeleton without reordering or dropping headings:

```markdown
# <Program> plan

<Who changes, what changes, the enforced rule, and ordered unit ids.>

## How to read this

One box is one unit of work. Every box names the evidence that checks it. Check a box only when its evidence exists. Name the execution playbook and who may merge.

Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

## Program checklist

### Arm the program

- [ ] State this protocol and plan, then stop until explicit go.
- [ ] On go, record the exact plan path, ordered units, verification rule, authority, and done predicate.
- [ ] Read the execution, deliberation, surface-control, delivery, and other required contracts at program start.
- [ ] Arm native monitoring with a bounded heartbeat and report state from observed side effects.
- [ ] On stop, record zero-write state first and reconcile every child read-only.

### Spawn owners

- [ ] Give every unit one owner, exclusive paths or branch, complete brief, dependencies, and proof.
- [ ] Start dependent work only from its proven parent revision.
- [ ] Hold every changed interaction at its review gate.

### PR mechanics

- [ ] Commit. Create one landable ordered commit with its observed checks.
- [ ] PR. Open one ready pull request for that commit after repository checks pass.
- [ ] Ready. Stop at merge-ready until exact-head proof and every required gate pass.
- [ ] Land. Merge or append only under recorded authority plus a fresh exact-head `provider_landing_gate_clear`, independent PASS or PASS+NOTES, and contiguous-prefix proof.
- [ ] Run prose cleanup and a fresh No-comments audit before review.
- [ ] Triage automated claims against current code.
- [ ] Recheck exact base and head before the ready verdict.

### Verdict and merge

- [ ] Bind independent unit, live, perf, and diff-audit evidence to the exact head SHA.
- [ ] Accept only when every required lane is PASS. Reverify a changed head.
- [ ] Apply the named merge or append rule only under its recorded authority.

### Boot recipe

- [ ] Fetch and check out the exact head SHA in an isolated environment.
- [ ] Start the affected surface and wait for an observable ready state.
- [ ] Drive input through the matching surface tool and save named evidence paths.

## <Task as a verb phrase> (<Unit id>)

**Depends on.**

**Files.**

- [ ] <Create, edit, or delete one exact path.>

**Build.**

- [ ] <One change with its symbol and data shape.>

**You see.**

- [ ] <One observable result and pass state.>

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] <Focused test and exact command.>

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten live lanes at the exact PR head.

- [ ] Lane 1. <Independent scenario.> Save `<evidence path>`. Pass when <predicate>.
- [ ] Lane 2. <Independent scenario.> Save `<evidence path>`. Pass when <predicate>.
- [ ] Lane 3. <Independent scenario.> Save `<evidence path>`. Pass when <predicate>.
- [ ] Lane 4. <Independent scenario.> Save `<evidence path>`. Pass when <predicate>.
- [ ] Lane 5. <Independent scenario.> Save `<evidence path>`. Pass when <predicate>.
- [ ] Lane 6. <Independent scenario.> Save `<evidence path>`. Pass when <predicate>.
- [ ] Lane 7. <Independent scenario.> Save `<evidence path>`. Pass when <predicate>.
- [ ] Lane 8. <Independent scenario.> Save `<evidence path>`. Pass when <predicate>.
- [ ] Lane 9. <Independent scenario.> Save `<evidence path>`. Pass when <predicate>.
- [ ] Lane 10. <Independent scenario.> Save `<evidence path>`. Pass when <predicate>.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. <Measured property.>
- [ ] Probe. <Same procedure at base and head.>
- [ ] Baseline. <Base value recorded first.>
- [ ] Rule. <Numeric head-against-base failure threshold.>

**Review gate.** Record screenshots and video before merge for every changed interaction. Write `None. This unit changes no interaction.` only when true.

- [ ] <Post the screenshots and short video, then wait for operator approval.>

**Merge.**

- [ ] <Exact-head verdict, [automated-review triage](bugbot-triage.md), and authorized merge or append action.>

## Close the program

- [ ] Every unit has evidence, terminal state, and exact revision identity.
- [ ] Report the execution playbook's required close summary.

## Appendix A. Prototype evidence

<Questions, observations, artifact paths, and remaining unknowns.>

## Appendix B. Alternatives rejected

<Alternatives and evidence-based rejection reasons.>

## Appendix C. Risks

<Risk, owning unit, signal, and response.>

## Appendix D. Links and reading list

<Source, contracts, decision trail, and delivery records.>
```

## Worktree and simulator cleanup

1. **Audit.** Measure disk, derive targets from authoritative worktree and simulator listings, and run `worktree_audit.py` with exact-path `codexstack.worktree-evidence.v1` use and PR facts.
2. **Cross-check use.** Treat active sessions, pinned work, and user-owned state as stronger than a safe bucket.
3. **Verify candidates.** Inspect uncertain targets and sibling worktrees before deletion.
4. **Pause on loss.** Ask before deleting uncommitted, active, shared, or hard-to-recover state.
5. **Prune exactly.** Treat `safe` as advice only; remove only the authorized confirmed paths, preserve branches, then re-list and rerun the audit.
6. **Continue carefully.** Remove stale simulators or caches only from an explicit confirmed set.

## Opening a PR

1. **Inspect the worktree.** Preserve unrelated work and derive the base, head, commits, full diff, and receipts from Git.
2. **Order commits.** Rebase only with authority. Shape small landable commits that tell the verified dependency story.
3. **Clean before review.** Run the prose cleanup and a fresh No-comments audit before review. Inspect the resulting diff yourself.
4. **Write from evidence.** Use a conventional imperative title and describe why, scope, real tradeoffs, blast radius, verification, and risk.
5. **Keep delivery narrow.** Prefer independent pull requests or an explicitly ordered dependent stack.
6. **Open ready.** Publish non-draft by default. An explicit current user request or mandatory repository policy may require draft; record that precedence. Then re-read provider state and exact head.
7. **Return.** Report the URL and revision. Opening does not start Babysit or grant landing authority.

## Required return fields

Use the matched row even for a terse handoff. Do not replace it with a generic summary.

- **Investigation.** Give the evidence-backed answer and gaps. For “are we sure?”, include the lead's real judgment and reasons and reject a false premise.
- **Bug fix.** State what broke, root cause, fix, and verification; include the observed failing-then-passing reproduction output.
- **Perf issue.** Give baseline, after value, delta, and artifact path.
- **Hillclimb.** Give metric and target, baseline-to-final percent delta, iterations kept versus reverted, one line per accepted fix, trail path, and best next idea.
- **Runtime forensics.** Give captured signal, reduced finding, mechanism proof, source location, and artifact paths; name Bug fix or Perf as the next route without silently fixing.
- **Trace forensics.** Give artifact and format, reduced finding, source location, artifact paths, and whether a paired capture confirmed it.
- **Feature.** State what shipped, choices and reasons, and open decisions; show design alternatives and tradeoffs in a table when there was a real fork.
- **Refactoring.** State changed structure, held pin, equivalence proof, reader-load delta, shipped and reverted work, and confirm no new behavior.
- **Prototype.** Give variants, matching-surface evidence, tradeoffs, recommendation, and scratch path; call the artifact throwaway.
- **Visual parity.** List every migrated component or state, its diff result, immutable baseline harness path, and what remains.
- **Authoring or modifying a skill.** Give skill summary, key design decisions, and observed validation.
- **Eval.** Give variant, rubric, per-candidate notes, independent verdict, lead synthesis, and promote, revise, or reject recommendation.
- **Babysit.** Give declared mode, frontier and state, the whole stack's four-column status table, fixes versus dismissals with reasons, pending work, and human gate.
- **Shipping.** Give verified run and ceiling, each PR verdict and verifier, arming action and authoritative confirmation, landed set, and next gap.
- **Autonomous run.** Give exit condition, iteration count, accepted and discarded work, exact artifacts, and final predicate state.
- **Orchestrate.** Derive predicate count, landed tracks, PR-and-SHA frontier, verdicts, abandoned scope, human gates, store and trail paths, and PR links from state.
- **Autopilot-full.** Give each PR owner, state, head, root verdict and lanes, merged work and next ownership, countersigns, operator gates, and trail paths.
- **Autopilot-stack.** Give stack root and tip links, one exact-head verdict per link, and every parked or excluded item with reason.
- **Session pickup.** Give prior stop, inherited versus redone work, exact resume point, and outcome.
- **Pause safely.** Give current loop point, durable paths versus in-context state, commits and tree cleanliness, and first resume action; label it a pause.
- **Multi-phase or multi-PR plan.** Give plan path, unit or PR ids and dependencies, review-gated set, proven and unproven prototype claims, and check-script output.
- **Worktree and simulator cleanup.** Give disk before and after, space reclaimed, exact pruned targets, and one-line reason for each retained target.
- **Opening a PR.** Give URL and exact head revision and state explicitly that opening did not start Babysit or grant Land authority.
