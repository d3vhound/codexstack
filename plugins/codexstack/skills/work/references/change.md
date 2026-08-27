# Change workflows

Use this reference when the user asked for an implementation, repair, migration, cleanup, prototype, visual match, or performance/code-quality change. Keep the process proportional: trivial safe edits may skip heavyweight comparison or delegation, but must still name the matched workflow and any skipped gates with reasons.

## Common audited loop

Every change runs through this state machine:

1. **Ground.** Read repository instructions, dirty state, entry points, current behavior, callers, types, tests, and relevant history. Recall prior decisions when the repo provides them.
2. **Frame.** State the observable acceptance condition, affected shape, blast radius, and strongest feasible proof. Use a plan only when there are multiple meaningful steps.
3. **Before proof.** Capture the current behavior on the matching surface: the same command, UI, API, workload, rendered state, artifact, or user path that demonstrates the requested concern. If blocked, record why and use the closest honest substitute.
4. **Shape.** When adding a requirement to an existing design, ask what the holistic day-one design would be and propagate it through types, code, docs, examples, and rationale. For consequential or unresolved design, compare two or three structurally different options against explicit criteria. For empirical forks, run a small probe rather than asking the user to guess.
5. **Partition.** Identify blocking work, independent slices, shared state, and safe ownership boundaries. Parallel writers need disjoint paths or separate worktrees.
6. **Implement.** Make the smallest coherent change. Delete obsolete code in the same wave. Avoid speculative abstractions, compatibility layers, and unrelated cleanup.
7. **Inspect.** Review the integrated diff and every delegated diff. Reject changes that pass by weakening the contract, hiding the symptom, or changing the verifier.
8. **After proof.** Rerun the matching-surface proof, then targeted tests/static checks. Record exact commands, artifacts, before/after observations, and residual uncertainty.
9. **Handoff.** Lead with the user-visible result, changed files, proof, risks, and next decision. Push, PR, merge, deploy, or message externally only when requested.

## Blast-radius, recall, and teach gates

- **Blast radius.** Before risky edits, map callers, consumers, persisted formats, configuration, migrations, concurrency, tests, generated artifacts, and external contracts. Prove the safety property at the narrowest level that can fail.
- **Recall.** Reuse existing project decisions, conventions, tests, notes, and prior failures before inventing a new pattern.
- **Teach.** If the user asks to learn the changed subsystem, route to the read-only Teach workflow after the change is proven: combine current mechanics with calibrated rationale and preserve uncertainty. Encode recurring engineering lessons through tests, types, checks, or focused documentation; do not add narration that code or tests already express.

## Workflow state machines

### Bug

Required states:

1. **Reported surface.** Identify the exact surface the user or failing system observed.
2. **Reproduce before.** Trigger the defect on that surface before the first fix. If unavailable, record the blocker and the closest instrumented/synthetic trigger.
3. **Hypotheses.** Trace competing causes and eliminate them with evidence.
4. **Root cause.** Confirm the causal mechanism, not just a plausible location.
5. **Regression pin.** Add a cheap failing test first when it clearly targets the failure. Skip only if the path is expensive, unclear, or lower value than direct reproduction.
6. **Fix.** Change the cause narrowly and completely. A guard that only hides the symptom is not a root-cause fix.
7. **Reproduce after.** Rerun the original matching-surface reproduction, then the regression and affected suite.

No matching-surface before/after proof means the bug fix is unverified.

### Performance

Required states:

1. **Workload.** Reproduce the reported workload or a documented equivalent.
2. **Baseline.** Capture a before metric or trace with method, sample count, and expected noise.
3. **Attribution.** Tie the cost to a source-level mechanism.
4. **Change.** Alter that mechanism only.
5. **Comparable after.** Measure the same workload with the same method.
6. **Regression gate.** Run correctness checks and report before/after/noise.

### Refactor or migration

Required states:

1. **Behavior pin.** Capture current behavior with a characterization test, snapshot, fixture, equivalence harness, or real-artifact baseline. Type checking alone is not enough.
2. **Target shape.** Name the target module, type, public call shape, and invalid states or reader burden being removed.
3. **Phase the move.** For an ordinary refactor, keep the behavior pin green after every unit. For a planned rewrite or migration, declare phase boundaries and any temporary breakage before starting. Keep high-signal checks for touched areas green; permit only scoped, reversible instability within the declared phase; require the full pin plus static and runtime proof at completion. Do not add throwaway compatibility merely to smooth an intermediate state.
4. **Migrate/delete.** Update internal callers and delete the old API in the same wave. Keep adapters only for proven external contracts.
5. **Equivalence after.** Compare old/new behavior on the real artifact or matching surface.
6. **Reader test.** If the result adds indirection without reducing risk, branches, or reader load, reconsider.

### Visual parity

Required states:

1. **Baseline capture.** Capture immutable before images/artifacts across relevant states.
2. **Harness lock.** Do not change harness, crop, viewport, threshold, seed, or baseline to make the result pass.
3. **Single visual unit.** Change one independently verifiable component or state at a time.
4. **Matching render after.** Compare on the same rendered surface.
5. **Explain diff.** Any nonzero unexplained difference is a failure, not an approximation.

### Forensics-backed fix

Required states:

1. **Artifact identity.** Identify the dump, trace, log, profile, report, capture, or incident signal and its time/window.
2. **Queryable form.** Transform large artifacts only enough to inspect dominant frames, chains, transitions, or events.
3. **Source map.** Resolve findings to files, symbols, configs, or data shapes.
4. **Mechanism check.** Confirm with a focused experiment when possible; otherwise label the finding as supported hypothesis.
5. **Fix and compare.** Change the mechanism and compare against the artifact-derived signal or a faithful reproduction.

### Feature

Proportional states:

1. **User-out behavior.** Describe the behavior from the caller or user outward.
2. **Domain shape.** Name one authoritative state machine, tagged union, reducer, table, registry, schema, or typed model before writing stateful logic.
3. **Boundaries.** Identify parsing, persistence, network, UI, compatibility, and error/recovery boundaries. Validate external data once at boundaries.
4. **Public usage.** Design public usage before internals when the feature crosses a function/module boundary.
5. **Complete path proof.** Verify the full user-facing path, including introduced failure and recovery behavior.

### Prototype

Proportional states:

1. **Decision.** State the decision the prototype will settle.
2. **Isolation.** Use scratch or an explicitly isolated branch/worktree. Production source stays unchanged unless the user asked otherwise.
3. **Light artifact.** Build the smallest artifact that exposes behavior, timing, API shape, or visual choice.
4. **Comparison surface.** Put alternatives behind one comparable surface when practical.
5. **Recommendation.** Observe directly and recommend a direction. The deliverable is the decision and throwaway artifact, not production code.

### Hillclimb

Proportional states:

1. **Harness.** Freeze a sensitive repeatable measurement and correctness gate.
2. **Target.** Define a numeric goal, minimum evidence, and stop condition.
3. **One hypothesis.** Change one hypothesis per iteration.
4. **Keep/revert.** Keep only wins that beat noise while correctness stays green; revert the rest.
5. **Log.** Record hypothesis, measurement, verdict, and commit/revert. Pivot after a plateau rather than stacking unmeasured tweaks.

### Code quality

Proportional states:

1. **Contract.** Identify whether the request is readability, typing, lint, dead code, comments, suppression, naming, or architecture.
2. **Behavior guard.** For mechanical cleanups, run existing tests/types. For semantic cleanups, pin behavior first.
3. **Smallest cleanup.** Remove narration, banners, stale comments, commented-out code, workaround essays, dead branches, and unnecessary suppressions.
4. **Suppression audit.** Keep suppressions only with a concrete reason the rule is wrong for that location; prefer fixing code or rule.
5. **Scoped proof.** Show that behavior stayed stable or the intended quality gate improved.
