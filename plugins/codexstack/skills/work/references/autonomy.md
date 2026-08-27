# Autonomous workflows

Use autonomy only after the user asks Codex to continue beyond an ordinary bounded turn. A plan or protocol request is not a start signal.

## Figure it out

Use this bespoke-run route when no narrower playbook fits, when a normally focused playbook becomes large or cross-cutting, or when the human will review the work after stepping away. A standing program that will outlive one agent or session routes to [Program orchestration](orchestrate.md) instead.

1. **Frame.** State falsifiable done, quantified units and effort, known blockers, and a rigor level biased high. Reversible preparation may continue, but get one checkpoint before a multi-hour run.
2. **Design the workflow.** Write the phase list before product changes. Use atomic independently landable units, put the riskiest unknown first, and build the scaffold, baseline, harness, and verification before features. Send one-way doors through Architect. Declare safe fan-out and writable isolation.
3. **Run hypothesis units.** For each unit, state a hypothesis, make the smallest change, measure the real artifact, and keep or revert. Use exactly **VERIFIED**, **NOT VERIFIED**, or **INCONCLUSIVE**. Pair delegated work with a fresh judge, then inspect its artifact yourself.
4. **Keep the trail.** Append each consequential decision, pivot, unit, evidence pointer, and result to the canonical reviewable trail below while the run happens.
5. **Close the whole.** Exercise the integrated artifact against the framing predicate, turn recurring corrections into a type, test, lint, gate, verifier, or script, run the trail close gate, and report the designed playbook, rigor, trail path, verified scope, and open scope.

This route designs one rigorous run. It does not replace a focused single-unit playbook or the durable coordinator protocol.

## Reviewable evidence trail

Long, autonomous, multi-phase, unattended, Figure it out, and Autopilot work keeps one canonical append-only trail. Use the program decision and event records when a program store exists. Otherwise use a local ignored artifact such as `.codexstack/audit/<task-slug>.tsv`. Each entry records time, phase, decision, plain-language reason, resolvable evidence, result, actor, and exact revision when relevant. Keep it local by default. Commit it only when the stakes require an auditable artifact and commit authority exists.

Append decisions and checkpoints as they occur. Never rewrite history. Correct a bad row with a superseding row. Prefer evidence from committed rerunnable scripts. A narrative or delegate assurance is not an evidence pointer.

Before any clean handoff:

1. Self-audit every row against actual run evidence such as tool events, diffs, command output, exact revisions, state records, screenshots, and saved artifacts. If the active workspace explicitly exposes this run's transcript, it may be included. Never search another workspace or invent transcript access.
2. Confirm each row happened, each pointer resolves and supports its claim, and every material fork, revert, abandoned path, and blocker is represented. Append corrections or gaps. Do not pad the trail.
3. Give the audited trail and the same run evidence to a fresh read-only reviewer from a different available model family. The reviewer flags weak evidence, skipped proof, risky choices, scope creep, and important omissions. If another family is unavailable, use a fresh isolated same-family reviewer, disclose the lower-confidence fallback, and never call it cross-model confirmation.
4. End every reply for a run with a trail with an `Attention` section. Its first line is exactly `reviewed by <model>`, followed by row-specific flags or `No flags`. A same-family fallback is itself a flag. A run cannot claim complete if no fresh reviewer ran.

## One bounded autonomous goal

Define done as a falsifiable predicate before the first iteration: a named repro no longer fails, a specified test set passes, a measured threshold is reached, all named targets reach a provider state, or an exact artifact comparison succeeds.

1. Choose the wake mechanism from capabilities that actually exist. Prefer a real event for CI, ref movement, review, or merge changes, with a time heartbeat only as fallback. Without an event source, use a proportionate interval or the available wait/monitor mechanism. Do not invent a watcher or treat elapsed time as progress.
2. Each iteration records a mechanism-level hypothesis, makes the smallest evidence-backed change, exercises the predicate, and either keeps or fully reverts that unit.
3. Make accepted progress durable after each verified unit when commit or publication authority exists. Do not leave speculative guards or “might help” changes riding with a successful unit.
4. Append a checkpoint after every iteration: hypothesis, changed artifact or revision, accepted or reverted result, evidence, predicate state, and next move.
5. Own incidental problems only when they block the predicate or clearly belong to scope. Keep unrelated fixes isolated and subject to their own authority.
6. A plateau requires a new hypothesis, smaller probe, or changed method. It is not success. Stop only at the predicate, an explicit stop, exhausted authority, or a genuine evidenced dead end.

External events wake the loop; they never prove the predicate. A resumed loop reads its durable trail and current artifact before acting.

## State-then-wait

Autopilot has an explicit arm boundary.
The state-then-wait rule means execution requires explicit go from the user.

- If the user asks for the protocol, queue, or plan, state it and wait.
- Begin execution only after an explicit “go”, “start”, or equivalent execution command.
- Items the user marks as operator-owned remain operator-owned.
- A stop or hold immediately becomes a durable zero-write order.

Do not reinterpret silence as authorization. Once explicitly started, continue across ordinary status questions and terse steering until the predicate, a real gate, or a stop.

## Common owner loop

Both Autopilot modes use one lifecycle owner per item or PR.

1. Freeze a standalone brief with scope, acceptance, exact verification, forbidden operations, report shape, and standing orders.
2. Give the owner one isolated branch or worktree and exclusive writable scope.
3. The owner builds, proves the behavior on the matching surface, triages review claims skeptically, removes accidental scope, drives its own PR to the declared ready state, and returns the exact head SHA plus decisions and receipts.
4. Independent items run in parallel. Overlapping writes or real dependencies serialize. A branch name alone is not isolation.
5. The root reads the diff and receipts and runs a fresh independent verification swarm against the merge-ready or stack-ready exact head. For consequential work, use parallel lanes: required gates, live affected-surface behavior, and receipts/diff audit.
6. Findings return to the same owner for fix-forward. A changed head gets a fresh verdict unless patch equivalence is proven.
7. Progress means observed side effects such as commits, pushed refs, PR changes, checks, proof artifacts, or state records. Agent assurances and chat activity do not establish liveness.

The root owns verdicts, countersigns, queue state, and audits. Owners own their changes. Exactly one actor owns topology for any dependency chain.

Each lifecycle owner returns its append-only trail with the exact-head receipts. The root audits and independently reviews the collected trails before close.

## Autopilot full

Use Full for independent PRs when the user has explicitly granted landing authority.

- One owner carries each PR from brief through merge.
- Before declaring merge-ready, the owner updates from current trunk through the repository's established mechanism and proves the resulting head.
- The root never merges on the owner's self-report. It issues a clean verdict bound to the merge-ready head.
- Only a clean root verdict plus explicit program-level landing authority permits that owner to merge its PR.
- The owner refetches trunk and provider state immediately before merge. If trunk or the head moved, apply the exact-revision rules and re-verify when required.
- After a confirmed merge, the owner may take the next independent item.
- Operator-owned items stop at merge-ready. Their owner never merges them.
- A new program-level pin, budget limit, or protected invariant needs a fresh root countersign backed by verifier evidence. Absorbing a value already landed on trunk is drift, not a new raise.

Full is not a stack. Self-contained changes branch from the current trunk. Truly sequenced work waits for its dependency to land before branching, unless the user selected Stack.

## Autopilot stack

Use Stack when changes are coupled or ordered, merge authority is withheld, or the operator wants to review and land one linear chain.

- Run the same lifecycle owner and root verification loop through STACK-READY.
- No owner merges, closes, arms auto-merge, or independently changes parentage.
- A clean root verdict admits the item into one linear chain in verified or operator-specified order.
- Parallel owners build isolated changes. A single topology owner appends, reparents, restacks, or submits the chain.
- Workers never rebase the shared chain or invoke stack-wide operations.
- After topology movement, compare each previously verified patch with its new head. Re-verify every patch or base-sensitive behavior that changed.
- The terminal artifact is a bottom-up reviewable chain with exact-head verdict evidence on every link. The operator lands it.

Do not claim Graphite or any particular stack service is required. Use the repository's established mechanism and preserve these ownership and verification rules.

## Audit, liveness, and stop

Use event wakes plus a proportionate periodic audit when the environment supports them. At each audit:

1. reread the durable objective and standing orders;
2. compare every owner with observed side effects and expected runtime;
3. collect decision trails and exact revisions;
4. put a timed-out lane into unit-level zero-write, reconcile its worktree, branch, head, and durable state, then replace it with a fresh consolidated brief when safe; silence alone is not failure;
5. reconcile late results against the current head and queue before accepting them.

Bound retries. Retry a scoped resource failure with smaller scope, a transient network failure as-is, and a tool incompatibility with another capable role or method. An unknown failure gets one evidence-gathering retry. After two failed retries for an item, abandon or replan it explicitly rather than spin.

On a user stop, systemic bad brief, unsafe upstream result, or lost authority, invoke the zero-write stop:

1. record the zero-write hold durably;
2. issue the stop to every active owner immediately;
3. start no new writes, merges, pushes, or topology operations;
4. retain briefs and state for possible release;
5. reconcile every late child and dirty worktree without accepting or landing its output.

Release requires an explicit user command or a repaired, documented systemic cause within existing authority.

## Reply

For a bounded run, report the predicate, iterations, accepted and discarded units, exact artifacts, and final predicate state. If the run produced a trail, finish with its required `Attention` section.

For Autopilot, report each item, lifecycle owner, state and head SHA; root verdict and verification lanes; what merged or entered the chain; operator-owned or blocked items; countersigns; zero-write state; trail paths; and the next safe action. Finish with the required `Attention` section.
