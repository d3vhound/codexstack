# Change workflows

Use the common loop, then apply the gate for the request type.

## Common loop

1. **Ground.** Read applicable repository guidance, current changes, entry points, callers, tests, types, and relevant history. Establish what the product does now.
2. **Frame.** State the observable acceptance condition, affected data shape, likely boundaries, and strongest feasible verification. Use a plan only when the task has multiple meaningful steps.
3. **Settle the shape.** If the design is consequential and unresolved, compare two or three structurally different sketches against explicit criteria. If the fork is observable, run a small isolated probe instead of asking the user to guess.
4. **Partition.** Identify blocking work, independent slices, shared state, and the smallest safe ownership boundaries. Parallel writers require disjoint paths or separate worktrees.
5. **Implement.** Make the smallest coherent change. Delete obsolete code in the same wave. Avoid speculative abstractions, compatibility layers, and unrelated cleanup.
6. **Inspect.** Review every delegated diff and the integrated result. Reject code that passes checks by weakening the contract, hiding the symptom, or changing the verifier.
7. **Verify.** Exercise the acceptance condition on the matching surface, then run targeted tests and static checks. Record exact commands and observed outcomes.
8. **Handoff.** Report the user-visible result, the main design choice, changed files, verification, and remaining risk. Open a PR, push, or merge only when requested.

## Bug

Required gates:

1. Reproduce the defect before the first fix. Drive the same surface the user reported. If direct reproduction is blocked, state why and instrument or synthesize the trigger as far as possible.
2. Trace competing hypotheses and eliminate them with evidence. Confirm the causal mechanism, not merely a plausible location.
3. Add a cheap regression test first when one clearly targets the failure. Do not force a low-value test through an expensive or unclear integration path.
4. Fix the cause with the narrowest complete change. A guard that only hides the failure is not a root-cause fix.
5. Rerun the original reproduction after the change. Then run the regression and affected suite.

No reproduction means the result is unverified, even if a test passes.

## Feature

Required gates:

1. Describe the behavior from the caller or user outward.
2. Name one authoritative domain shape before writing stateful logic. Prefer a state machine, tagged union, reducer, table, registry, or typed model over scattered flags and repeated conditionals.
3. Identify parsing, persistence, network, UI, and compatibility boundaries. Validate external data once at those boundaries.
4. Design the public usage before internals when the feature crosses a function or module boundary.
5. Verify the complete user-facing path, including error and recovery behavior that the change introduces.

## Refactor or migration

Required gates:

1. Pin current behavior with a characterization test, snapshot, recorded baseline, or equivalence harness before structure moves. Type checking alone is not a behavior contract.
2. Name the target module, type, and call shape. The new structure must delete branches, invalid states, or reader burden rather than add indirection.
3. Remove dead weight first. Move in small units while the behavior pin stays green.
4. Migrate all internal callers and delete the old API in the same wave. Keep a compatibility adapter only for a proven external contract.
5. Compare old and new behavior on the real artifact. If reader load did not fall, reconsider the refactor.

## Performance or forensics-backed fix

For a one-off performance issue:

1. Reproduce the reported workload and capture a baseline trace or metric.
2. Attribute the cost to a source-level mechanism.
3. Change that mechanism.
4. Capture a comparable result with the same workload and measurement method.
5. Report the before, after, noise or sample count, and regression checks.

For sustained hill-climbing:

1. Freeze a sensitive, repeatable measurement harness and a correctness gate.
2. Define a numeric target and minimum evidence needed to stop.
3. Run one hypothesis per iteration. Measure before and after; keep it only if it beats noise while correctness remains green. Revert the rest.
4. Log each hypothesis, measurement, verdict, and commit or revert. Pivot after a plateau rather than stacking unmeasured tweaks.

## Prototype

- Use an isolated scratch directory. Production source stays unchanged.
- State the decision the prototype will settle.
- Build the lightest artifact that exposes the behavior, timing, or visual choice.
- Put alternatives behind one comparison surface when practical.
- Observe the result directly and recommend a direction. The output is the decision and throwaway artifact, not production code.

## Visual parity

1. Capture an immutable baseline across the relevant states before editing.
2. Do not alter the harness, crop, threshold, or baseline to make the result pass.
3. Change one independently verifiable component or state at a time.
4. Compare on the matching rendered surface. A nonzero unexplained difference is a failure, not an acceptable approximation.

## Code quality

- Comments explain a non-obvious external constraint, public contract, legal requirement, or why the code cannot express the reason itself. Remove narration, banners, commented-out code, and workaround essays.
- Suppressions require a concrete reason the rule is wrong for this location. Prefer fixing the code or the rule.
- Keep the final diff scoped. Preserve unrelated dirty-worktree changes.
