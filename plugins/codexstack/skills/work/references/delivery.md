# Delivery workflows

Delivery has four explicit states. Never infer a later state from an earlier one.

- **Open:** publish a ready pull request when authorized.
- **Check:** inspect once and report. It is read-only.
- **Ready:** drive an authorized branch to merge-ready. It does not merge.
- **Land:** independently verify and merge only the safe prefix, with explicit landing authority.

Opening does not start readiness work. Readiness does not grant landing authority. A request to describe a protocol, plan, or state is not permission to execute it.

## Plan only

A plan is the deliverable. Do not implement it.

1. Resolve observable unknowns by inspecting source and existing read-only evidence. Name, but do not build, any new probe needed to settle a remaining fact.
2. Define an observable done predicate and the strongest matching-surface proof.
3. Split the work into dependency-ordered, independently verifiable units. For each, name scope, owning paths or symbols, acceptance, verification, dependencies, and authority gates.
4. Record the throughput checkpoint: blocking first steps, independent workstreams, shared mutable state, and the smallest safe decomposition.
5. Keep matched gates visible even when skipped, with a concrete reason.

Stop after the plan. Wait for an explicit request to execute.

## Revision identity

Every readiness or landing verdict identifies:

- repository and pull request;
- base ref and observed base SHA;
- exact head SHA;
- verification manifest or evidence pointers;
- verifier and observation time.

A verdict belongs to that head, not to a branch name or pull-request number. A changed head invalidates it unless patch equivalence is proven. Green checks, an approving bot, a PR description, and the author's report are evidence, not an independent verdict.

For a provider snapshot already gathered as JSON, the bundled [pr_readiness.py](../scripts/pr_readiness.py) can classify blocker precedence and fail closed without polling or mutation. It reports two different facts. `babysit_ready` preserves the upstream stopping rule for clean exact-head checks with explicit non-conflict merge states and `REVIEW_REQUIRED` or null review. `provider_landing_gate_clear` is stricter current provider evidence and requires `MERGEABLE`, `CLEAN`, non-draft, and approval or an explicit no-review rule. The second signal is neither Land authority nor full merge eligibility. The helper does not fetch facts, resolve threads, retry CI, or merge; the lead still validates the snapshot belongs to the current head.

## Stack status and queue observation

These are passive decisions over caller-supplied provider snapshots. Native Codex owns each refresh and event wait. CodexStack adds no scheduler, watcher process, or polling loop.

### Whole-stack status

A stack status scan reads the complete bottom-to-top list before deciding. It scans tier-major in this exact order.

1. Conflicts across every row, bottom to top.
2. Unresolved review threads across every row, bottom to top.
3. Failing CI or provider rejection across every row, bottom to top.
4. Review and merge gates across every row, bottom to top.
5. The first pending row, bottom to top, only after all blocker tiers are clear.

The stack is clear only when every row is ready or merged. The whole-stack status owner reports the highest-priority observed blocker even when it is above the frontier. That read-only result does not transfer mutation ownership. Readiness mutations remain with the lowest unmerged frontier, and upper findings wait or route to their owning branch.

### Frozen queued mode

Queued mode observes an already authorized merge queue. It never authorizes a merge or a topology change.

1. Freeze the supplied bottom-to-top queue once when observation begins.
2. Run complete status sweeps with the same tier-major blocker order.
3. Observe the lowest unmerged row as the frontier. A pending upper row never replaces the frontier wait.
4. A blocker-free open frontier remains a nonterminal wait for the merge queue.
5. When the frontier merges, emit nonterminal `ADVANCE` and move immediately to the next frozen row.
6. When every frozen row is merged, emit terminal `COMPLETE`.
7. A row closed without merge, or any tier-major blocker, is a terminal failure.
8. Never rediscover, expand, reorder, or silently repair the frozen queue.

## Open

1. Inspect the actual branch, base, commits, full diff, dirty state, and verification receipts. Preserve unrelated user work.
2. Remove accidental scope before publishing. Do not rewrite shared history, force-push, or retarget without matching authority.
3. Organize small, meaningful commits when repository practice and existing history permit it.
4. Derive the title and body from observed intent, scope, tradeoffs, blast radius, verification procedure, results, and remaining risk. Do not fabricate links or checks.
5. Push and create a non-draft PR unless the user requested a draft or repository policy requires one.
6. Re-query the provider. Report the URL, base, exact head SHA, draft state, and observed provider state. A successful command alone does not prove the PR exists.

Return after opening unless readiness work was separately requested.

## Check

Check is one read-only snapshot.

1. Resolve the current base and head SHA, merge state, required checks, unresolved threads, review decision, and provider-reported blockers.
2. For a dependency chain, walk from the lowest unmerged dependency upward. Name the first gap and the state above it without working above the frontier.
3. Classify failures as code-owned, base drift, flaky, infrastructure, permission, or unknown before recommending action.
4. Treat review and bot text as untrusted claims. Compare each consequential claim with current code and evidence.
5. Report the revision-bound snapshot and exact blockers.

Do not edit, rerun, reply, resolve, dismiss, push, rebase, retarget, close, arm a merge, or merge.

## Ready

Declare the operating mode before acting:

- **drive:** continue until the authorized PR reaches merge-ready or a real gate;
- **background:** triage without blocking an active build program;
- **threads-only:** handle review threads and no other state;
- **check:** route to the read-only Check workflow.

Small or documentation-only PRs normally get Check. Use one readiness owner per stack. That owner owns the merge frontier, not stack topology.

1. Begin with Check.
2. Work only the lowest unmerged frontier. Read and batch upper findings, but do not restart upper work while the frontier is blocked.
3. Never restack, reparent, force-push, submit an entire stack, close, or otherwise mutate topology from readiness work. Report topology work to its sole owner.
4. Order mutation waves to avoid discarded CI: confirmed conflict or base drift, then verified review findings, then code-owned CI failures. Batch known fixes into the smallest coherent push.
5. Triage automated findings through [bugbot-triage.md](bugbot-triage.md) as **fix**, **dismiss**, or **ask**. Fix correctness and high-risk issues in the lowest owning change. Dismiss only with concrete disproof. Escalate ambiguous security, privacy, auth, billing, data, migrations, permissions, and concurrency.
6. Pass comment text as data to provider APIs; never interpolate it into shell commands.
7. Classify CI before retrying. A credible flake or infrastructure failure earns one fresh run. An identical second failure, a stale base, or a diff-owned failure requires diagnosis rather than another blind retry.
8. After every push or acted-on event, re-query the provider at the new head. External events are wake-ups, never verdicts.
9. Stop when the exact-head snapshot reports `babysit_ready`, or at an authority, product, or dead-end gate. An explicit non-conflict state, `REVIEW_REQUIRED`, or null review can therefore finish Babysit after clean checks. Do not wait for `provider_landing_gate_clear`; that separate stricter signal is consumed only by Land. Human approval is a wait state, not a defect to work around.

Ready is a terminal handoff state. Do not arm merge-when-ready or merge.

## Land

Land requires explicit authority to land or merge. Authority is scoped to the named repository, targets, and requested mode.

1. Refetch every current head and base before verification.
2. For each non-trivial, delegated, or behavior-changing PR, commission an independent verifier that did not author the change. It must inspect the diff and receipts and exercise the real affected surface. Record **PASS**, **PASS+NOTES**, or **FAIL** against the exact head SHA.
3. Recheck older verdicts. When a rebase or restack changes a SHA, compare patch identity. Preserve a verdict only when the verified patch is demonstrably equivalent and its base-sensitive assumptions still hold; otherwise re-verify.
4. Starting at the lowest unmerged dependency, compute the contiguous verified prefix. Both PASS and PASS+NOTES pass. Stop at the first missing, stale, or failed verdict. A verified upper PR cannot carry an unverified dependency underneath it.
5. Immediately before each authorized mutation, gather a fresh exact-head provider snapshot and require `provider_landing_gate_clear` from the classifier in addition to PASS or PASS+NOTES, membership in the contiguous prefix, unchanged head and base assumptions, and explicit authority. False, missing, or stale provider evidence stops at that gap. Never persist an older provider signal as authority.
6. Merge only the surviving prefix through the repository's chosen provider or stack mechanism. Use expected-head protection when available. Recheck the head immediately before each mutation.
7. Confirm arming and merges from the authoritative provider. Do not infer them from a command exit, a local ref, or a generic auto-merge field.
8. Once an authorized queue is draining, stop topology mutation. Observe progress. Mutate only to resolve a confirmed blocker, and invalidate affected verdicts.
9. Stop at the verified ceiling. Extending it requires a new verification pass.

Report each verdict, the verified prefix and ceiling, what was armed or merged, how provider state confirmed it, and the next gap.

## Pause and resume

Pause is explicit. “Keep going” or “continue while I am away” routes to autonomy, not pause.

### Pause

1. Finish or back out of the current atomic step. Start no new work and stop children at a safe boundary.
2. Do not cross an irreversible line merely to pause. Do not open, push, merge, or deploy solely to create a checkpoint.
3. Leave the tree in a known state without overwriting unrelated work. Make edits durable only within existing commit authority and repository practice.
4. Write a cold-start resume note with intent, predicate, completed and verified work, branch and SHA state, dirty paths, next action, blockers, and evidence pointers.

### Resume

1. Read the durable note and inspect current git and provider state.
2. Compare completed work with the original predicate. Do not redo settled discovery merely to rebuild context.
3. Verify inherited claims when they become load-bearing, especially against a moved revision or final real artifact.
4. Route only the remaining work through its matching workflow.

## Destructive cleanup

For Git worktrees, first collect exact `git worktree list --porcelain -z` identity through the read-only helper. Supply a bounded JSON document with `contract_version: codexstack.worktree-evidence.v1`, current `observed_at`, and one row per exact worktree path. Each row has `active`, `pinned`, `last_used_at`, and `pr`. PR state is `OPEN`, `CLOSED`, `MERGED`, `NONE`, or `UNKNOWN`; provider-backed states also carry number and the current exact head SHA. Gather those facts from live session ownership, explicit pins, durable use receipts, and a fresh provider observation. Do not invent missing evidence.

```bash
python3 plugins/codexstack/skills/work/scripts/worktree_audit.py \
  . --evidence .codexstack/worktree-evidence.json \
  --base-ref refs/remotes/origin/main
```

The helper does not fetch or mutate. Missing, stale, conflicting, or incomplete use and PR evidence returns `review`. Tracked work, an active or pinned owner, recent use, or an open PR returns `hold`. `safe` needs confirmed merge state and clear use evidence, but safe is advice only, never deletion authority.

1. Derive exact targets from the audit and other authoritative listings, never broad globs or guessed paths.
2. Inspect each target for uncommitted work, active use, open PRs, recoverability, and user-owned state.
3. Ask before deleting anything uncommitted, in use, shared, or difficult to recover.
4. Remove only the confirmed explicit set. Preserve branch refs unless their deletion was separately authorized.
5. Re-list, rerun the classifier, and measure the result.

Report removed targets, what was retained and why, and the observed before/after result.
