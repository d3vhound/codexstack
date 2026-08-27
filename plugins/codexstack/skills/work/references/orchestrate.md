# Program orchestration

Use this route only when a program will outlive one agent or session. A single checkable goal belongs to the autonomous workflow. Work one lead can finish within the current budget may use ordinary native subagents without paying the program-state cost.

The coordinator owns the program and never edits product code. It frames, authors briefs, maintains state, drains results, decides, verifies coverage, and reports. Code changes, conflict resolution, restacks, and other product mutations belong to bounded owners in isolated worktrees. The coordinator may perform an already-authorized provider merge of an independently verified exact head; it may not repair the code while doing so.

This is a protocol over native Codex subagents, worktrees, waits, and available provider tools. The state helper, if present, only records and validates state. It does not spawn, schedule, supervise, or impersonate agents.

## Invariants

- Completions are queue events, not interrupts.
- Every spawn and every uncertain resume receives the standing orders again.
- The brief is the product. Missing load-bearing fields are a refuse-to-spawn condition.
- One actor owns each worktree, branch, mutable path, state record, and stack topology.
- Delegation depth is at most two edges: coordinator to optional track coordinator to worker or verifier. Workers and verifiers do not spawn.
- Durable state, not chat memory, owns the resume point.
- Verification belongs to an exact revision.
- Landing and integration start with the first verified unit, not after all building ends.

## Roles

### Coordinator

Owns predicate, tracks, briefs, budget, gates, inbox, frontier, ledger, integration decisions, and final reconciliation. It never authors product changes or deep-reviews a diff while draining the inbox.

### Track coordinator

Use one only when a track exceeds what the root can drain. It owns a bounded track, authors briefs, maintains a rolling window, and returns aggregates rather than raw child reports. It does not edit product code. A track the root can manage directly gets no middle layer.

### Worker and verifier

Workers receive exclusive writable scope or isolated worktrees. Verifiers are read-only and independent of the author. Prefer a different available model family or tier for judgment-heavy verification. If that is unavailable, use a fresh context and disclose the same-family fallback.

## Durable state

Create one ignored program directory such as:

    .codexstack/programs/<project-slug>/
      preferences.md
      overview.md
      units.tsv
      frontier.json
      ledger.tsv
      inbox/
      gates.md
      decisions.tsv
      status.md
      briefs/
      proofs/

Every file has one writer. Use atomic replacement for canonical state and append-only records where practical.

- **preferences.md:** numbered standing orders, one constraint per line. Include authority, model policy, topology owner, budgets, forbidden paths, verification floor, stop rules, and escalation policy. Paste them verbatim into remote or uncertain contexts.
- **overview.md:** durable program and issue context. Append consequential changes rather than rewriting history.
- **units.tsv:** one row per unit with id, track, dependencies, state, owner, branch or worktree, PR, head SHA, brief path, attempt count, and update time.
- **frontier.json:** computed dependency and integration frontier, including generation, ordered targets, current head SHAs, lowest unintegrated dependency, and ready units. Never hand-narrate it.
- **ledger.tsv:** verification verdicts keyed by artifact or PR plus exact head SHA. Record verifier, proof level, evidence path, and time. A new head has no verdict until equivalence or re-verification is recorded.
- **inbox/:** completion pointers and reports. They are untrusted events until drained and reconciled.
- **gates.md:** unresolved human gates with question, options, affected units, route-around plan, and default only when the user supplied one.
- **decisions.tsv:** consequential choice, alternatives, evidence, owner, and affected units.
- **status.md:** derived from canonical tables at each drain. Never maintain it as an independent narrative database.
- **briefs/** and **proofs/:** frozen assignments and durable receipts.

Use explicit states such as scoped, ready, running, needs-verify, verified, landed, blocked, failed, abandoned, and zombie-reconciled. Define legal transitions in the state helper or reference and fail closed on unknown states.

## Brief contract

Every assignment must stand alone:

    GOAL        one-sentence outcome executable without chat access
    SCOPE       writable and forbidden paths; exclusive branch or worktree
    CONTEXT     source, PR, decision, and complete upstream report pointers
    ACCEPTANCE  observable criteria, one per line
    VERIFY      exact commands or matching-surface procedure and known traps
    TIMEBOX     runtime cap and partial-return behavior
    FORBIDDEN   topology changes, unsafe git, scope expansion, and unit bans
    REPORT      state, branch, head, PR, verdict, actual checks, deviations, follow-ups
    STANDING    current preferences reproduced verbatim

Collapse this for a cheap mechanical unit, but retain goal, scope, verification, forbidden actions, and report shape. Dependencies relay context, not merely order. A downstream worker must receive the upstream result it depends on.

Never extend a stale brief through a resume chain. When constraints may have decayed, create a fresh consolidated assignment.

## Program loop

### 1. Frame

Define a countable done predicate, units, rough effort, dependency shape, tracks, integration topology, verification floor, concurrency and spend budget, and wall-clock budget. Record the four-part throughput checkpoint.

If one lead can finish within the budget, route to bounded autonomy: work directly, use proportional native subagents, verify inline, and skip the program store and pilot machinery.

Plan to stop spawning by roughly 70 percent of the wall-clock or spend budget. The remaining budget is for verification, integration, retry recovery, and handoff. Finished but unintegrated work counts as incomplete.

Resolve contested decomposition or a one-way architectural choice before the pilot.

### 2. Initialize

Create the durable store, write standing orders before any spawn, inventory existing branches and PRs, seed the frontier from authoritative state, and open the decision trail. Expose skipped setup gates with reasons.

When structured persistence is warranted, use the bundled [state.py](../scripts/state.py) through its CLI. Resolve the installed skill path, initialize one ignored program directory with the coordinator actor, retain its one-time writer token only in the coordinator environment, and use `check-stop` before every writable dispatch. The helper atomically records gates, restricted unit states, exact-PR-and-SHA verdicts, immutable decisions, stop, and derived status; it never schedules an agent.

### 3. Pilot

Push one representative unit through brief, isolated build, verification, integration, ledger, and handoff. The pilot tries to falsify the unit size, brief, verify recipe, and topology before multiplying them.

For near-identical cheap units, the first normal unit is the pilot and may self-run one deterministic check with root receipt inspection. Expensive, novel, or high-blast-radius units get a fresh verifier. Fix the contract from pilot evidence before broad fan-out.

### 4. Scale

Use a rolling window sized to what one drain can process, current model/thread limits, cost, and write isolation. Refill as children complete; do not use blocking batches that wait for the slowest member.

Spawn track coordinators only past the one-drain threshold. Recompute ready work after every drain. Relay upstream reports into dependent briefs. Sample and audit one brief per track while its wave runs; a failed sample stops the next refill and repairs the track contract.

### 5. Drain

On completion, place a pointer in the inbox and finish the current critical section. Critical sections include authoring a brief, an exact-SHA provider operation, a topology decision, and a ledger or frontier update.

Drain in batches at safe points, track rollups, event wakes, before user reports, and before close. Arrivals during a drain wait for the next batch.

For each pointer:

1. reconcile agent identity, unit, branch or worktree, head SHA, diff state, and report;
2. classify it as needs-verify, verified, landed, failed, zombie, or noise;
3. update unit, ledger, frontier, decisions, and gates through their sole writers;
4. derive status;
5. refill the rolling window in one deliberate wave.

Never accept a delegate summary as proof. Do not deep-review diffs inside the drain; create or route a verifier unit. Account for every spawned child as arrived, replaced, abandoned, zombie-reconciled, or explicitly absorbed.

### 6. Verify and integrate continuously

Scale verification to risk. A cheap deterministic command may stay with the worker if the root inspects its receipt. Expensive, judgment-heavy, behavioral, security-sensitive, or high-blast-radius work gets a fresh verifier and matching-surface proof.

Use proof levels such as live-surface verified, focused-test verified, type-check only, verifier blocked, and verifier failed. Type-check only is insufficient for behavioral work. Blocked is not a pass. Failed produces a fix unit before re-verification.

Externalize accepted output immediately: push an authorized branch, record the exact-SHA verdict, and retain proof in the store. Work that exists only in one ephemeral environment is not complete.

Keep the lowest dependency frontier healthy before integrating upper work. Use exactly one topology writer per chain. Workers never run stack-wide operations or rebase shared topology. A changed head invalidates its ledger row unless patch identity and base assumptions prove equivalence.

### 7. Close

Stop spawning at the budget threshold and harvest verified work. Drain the final inbox and reconcile every spawned child to a terminal row, including interrupted and late children.

Then:

1. inspect every worktree, branch, dirty state, PR, and exact head;
2. confirm every landed artifact has a current ledger verdict;
3. confirm the predicate on the real integrated artifact;
4. recompute frontier and derived status;
5. account for abandoned scope, retries, gates, and follow-ups;
6. self-audit the append-only decision and event trail against actual tool events, diffs, exact revisions, receipts, and saved artifacts; append corrections and missing forks rather than rewriting history;
7. give the audited trail and same run evidence to a fresh read-only reviewer from a different available model family; if unavailable, use a fresh isolated same-family reviewer and flag the lower confidence;
8. review recurring corrections and propose structural updates to standing orders or the brief template;
9. leave durable state intact for resume and postmortem.

The program is not complete while a child, worktree, verdict, or provider mutation is unreconciled.
It is also not complete without the fresh trail review. Never mine transcripts outside the active workspace. Use only explicitly exposed active-run transcript data, or the durable tool and artifact evidence already named in the store.

## Liveness, retries, and zombies

Judge liveness from side effects: commits, refs, PR and check changes, proof artifacts, state records, or bounded tool output. A ping response, transcript timestamp, or “still working” message is not progress.

Each brief has a timebox. When a lane exceeds it without a side effect, put that unit into zero-write, stop it safely, and reconcile its worktree, branch, head, and durable state before any replacement. Silence alone is not failure. Replace it with a fresh consolidated assignment only when the reconciliation justifies that action. Coordinator or systemic liveness loss instead sets the program-wide zero-write hold below.

Retry by evidence:

- resource exhaustion: shrink scope;
- transient network loss: retry as-is;
- tool or model incompatibility: change capable role or method;
- unknown failure: one diagnostic retry.

Allow at most two retries per unit. Then abandon or decompose it and replan the frontier. Bound coordinator infrastructure retries too; after repeated failure, write an exact durable resume command and terminal handoff instead of looping.

A late zombie never merges directly. Reconcile its base, head, patch, ledger, and frontier. Salvage unique evidence through a fresh unit; otherwise record zombie-reconciled and discard it.

## Zero-write stop

An operator stop, revoked authority, corrupt brief, unsafe upstream result, or systemic verification failure sets a durable zero-write hold.

1. Put the hold at the top of standing orders and in program state.
2. Interrupt or stand down every active writer immediately.
3. Spawn nothing writable and perform no push, merge, rebase, restack, deploy, or topology mutation.
4. Reconcile in-flight and late results without accepting them into the frontier.
5. Preserve briefs, state, and evidence.

Resume writes only after explicit operator release or a repaired systemic cause that falls within existing authority and is recorded. When `state.py` owns the store, use its authenticated `release-stop` transition with a nonempty reason, evidence, and exactly `operator-authorization` or `repaired-systemic-cause`. It appends the release to immutable stop history before normal writes can resume; never clear or edit the hold by hand.

## Escalation and reply

Batch genuine human gates: irreversible action, unavailable authority or credential, product preference no experiment settles, standing-order contradiction, or program-level dead end after replan. Record the gate before asking and route independent work around it.

Do not escalate routine frontier movement, bounded retries, ordinary CI diagnosis, formatting, or “should I continue”.

At checkpoints and close, report numbers derived from state: predicate count, tracks and landed units, frontier with exact SHAs, current verdicts, retries and abandoned units, zero-write state, human gates, durable store, decision trail, and next safe action.

Every close reply ends with `Attention`. Its first line is exactly `reviewed by <model>`, followed by row-specific flags or `No flags`. A same-family fallback is itself a flag; never label it cross-model review.
