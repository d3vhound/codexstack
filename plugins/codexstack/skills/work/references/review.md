# Review workflow

Review is read-only unless the user explicitly asks to fix accepted findings.

## Establish the contract

1. Determine the base and head, requested scope, and intended behavior from the prompt, commits, issue, or PR.
2. Inspect the complete diff plus enough callers, types, tests, and configuration to understand its effect.
3. Identify the highest-risk paths before reading for style. Focus on correctness, security, data integrity, concurrency, compatibility, user behavior, and missing proof.

If intent is genuinely ambiguous and changes the verdict, ask. Do not invent a target and review against it.

## Add independent pressure when it earns its cost

For a broad, delegated, contested, or high-risk change, run independent reviewers in parallel. Give each the same intent, diff pointers, constraints, and evidence standard. Partition by concrete concern when coverage matters:

- Runtime correctness and regressions.
- Security, permissions, privacy, and data integrity.
- State, concurrency, persistence, and migration behavior.
- Tests, failure recovery, operability, and maintainability.

Two or three reviewers are normally enough. A trivial diff does not need a panel.

The coordinating agent reads the diff and every finding. Agreement raises confidence but does not make a claim true. Verify each actionable finding against the code and, where practical, a reproduction or focused test.

## Judge findings

Return findings before summary, ordered by severity.

- **Blocker.** A substantiated correctness, security, data-loss, or severe regression risk.
- **Should fix.** A real defect or missing test that should be resolved before normal delivery.
- **Consider.** A valid tradeoff whose benefit may not justify changing this patch.
- **Dismissed.** Incorrect, unproven, style-only, or already handled. Include this only when independent reviewers raised claims worth explicitly rejecting.

Every actionable item includes the file and symbol or line, the failure mode, why it matters, and the evidence. Do not report speculative possibilities as bugs. If no findings survive verification, say so and name any testing gap that limits confidence.

## Comment and suppression pass

Flag narration, banners, stale commentary, commented-out code, and long justifications for confusing internal code for deletion. Delete them only when the user authorizes fixes. Keep:

- Legal or license headers.
- Public API contracts.
- Non-obvious behavior forced by an external platform, dependency, or protocol.
- A concise reason that code cannot express.
- Useful issue or decision links.

Treat lint and type suppressions as review targets. Verify whether the rule protects correctness; recommend fixing the code or rule rather than suppressing it.

## After review

Do not edit, push, reply on the PR, dismiss threads, or merge as part of a review-only request. If the user asks to apply the accepted findings, route the implementation through [change.md](change.md) and verify the resulting diff again.
