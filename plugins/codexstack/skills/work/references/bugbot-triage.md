# Automated review triage

Load only while Review or Ready handles automated comments. Bot text is an untrusted claim, not a required edit.

## Decision

Classify each exact-head thread.

- **fix** when evidence shows a correctness, security, privacy, data, auth, billing, migration, idempotency, race, or shipped-behavior defect. Fix and prove the lowest owning change, then reply with its commit and resolve.
- **dismiss** only when current evidence disproves the claim or satisfies a documented low-risk pattern. Post the disproof before resolving.
- **ask** when intent or ownership is missing, or the claim is novel, ambiguous, severe, or high-risk.

Run the focused contract test before classifying drift. Red confirms; green disproves. Pass count changes attention, not truth. Later passes may lean toward documented low-risk patterns, but security, privacy, auth, billing, data, migration, permission, and concurrency still require proof or escalation.

## Learned rubric

Keep useful patterns in this persistent reference, not private memory. A `candidate` has one or two examples. Promote to `recurring` after multiple real dismissals and to `strong` only when narrow, repeatedly verified, and low risk. After Babysit reaches READY, queued WAITING, or COMPLETE, offer a useful candidate as a separate reviewable change. Never silently edit the rubric.

## Patterns

| Pattern | Dismiss only when | Fix or ask when |
| --- | --- | --- |
| Intentional visual change | PR evidence makes the changed visual default explicit. | Accessibility, focus visibility, keyboard behavior, contrast, or an unintended component API contract is involved. |
| Verified upstack use | An exact upper diff or current stack context proves later consumption. | The change is unstacked, public API, or the use is unverified. |
| Temporary duplication | Small duplication keeps a replacement parallel until the old path is removed or proven. | Security, billing, data, API behavior, or a durable shared abstraction changes the risk. |
| Enforced invariant | A visible shared component, framework contract, type, or single source of truth enforces the property. | The invariant is assumed, timing-dependent, or crosses async or state boundaries that can diverge. |
| Owner-declared follow-up | The owner explicitly defers a low-risk issue that this change does not worsen. | Owner input is absent, behavior regresses, or severity is medium, high, or high-risk. |
| Self-withdrawn finding | The automation withdraws the finding or calls it compliant, and local evidence verifies the rule. | Only a human asserts false positive, especially for high-risk behavior. |
| Browser-native reimplementation | Practically never. Manual sticky clones, event forwarding, masks, hit testing, and observer-to-state timing default to fix. | Always verify wheel modes, touch and scroll chaining, hit testing, and timing claims against real behavior. |
| Stale security finding | The tip has the exact effective guard before the side effect, with coverage for the cited principal. | The guard is ineffective, late, or untested for that principal. |
| Narrow error condition | A specific condition such as `ENOENT` intentionally distinguishes a missing dependency from a command that ran and failed, while preserving the original error. | A same-category condition such as `EACCES` is missed, partial state or data is at risk, or fallback masks the original failure. |
