# Investigation workflows

Investigations are read-only. Their deliverable is an evidence-backed explanation, diagnosis, or recommendation.

## How the system works

For a narrow question, trace it directly. For a subsystem that spans multiple areas, delegate two to four distinct read-only slices such as data model, request flow, persistence, UI, or tests.

Trace from a real entry point to its effect:

1. Identify the trigger, inputs, and owning types.
2. Follow callers, callees, state transitions, boundaries, and side effects.
3. Read the implementation and tests. Do not infer behavior from filenames.
4. Reconcile agent findings against the source.

Return only the sections the question needs:

- Overview.
- Key concepts.
- Runtime or data flow.
- Where the important code lives.
- Gotchas and unresolved gaps.

## Why it has this shape

Code shows what exists, not necessarily why. Anchor the target with files, symbols, line history, and recent commits, then search relevant evidence sources that are actually available:

- Git history, blame, commit messages, pull requests, review threads, and tests.
- Issues or project trackers for product and business constraints.
- Design docs, decision records, and postmortems for alternatives and rationale.
- Team chat for real-time decisions that never reached formal documentation.
- Metrics, traces, incidents, error tracking, and analytics for operational forcing functions.

Search categories in parallel when several are likely to matter. Do not require every connector for every question. Report searched sources that returned nothing when that absence changes confidence.

For every claim about intent:

- Cite the exact source when possible.
- Separate direct evidence from inference.
- Surface contradictions instead of silently selecting one story.
- State gaps and confidence. Use decisive language only for direct evidence.

Never retrofit a satisfying rationale from the present code shape.

## Blast radius or an architectural decision

1. Map callers, consumers, persisted formats, configuration, tests, concurrency, and external contracts.
2. Identify the safety property the change depends on.
3. Prove that property with a targeted execution, query, or fixture when feasible.
4. Compare options against explicit criteria such as behavior, migration cost, failure modes, operability, and reversibility.
5. Give a recommendation, tradeoffs, and what evidence would change it.

Use competing design candidates only for a consequential unresolved fork. A small probe is better when the answer is empirical.

## Runtime or captured-artifact diagnosis

Keep diagnosis separate from implementation unless the user asks for a fix.

- **Live symptom.** Capture the relevant signal on the matching surface, reduce it to the hot path, retention chain, loop, or failing transition, then use existing non-persistent observability to test the mechanism. If code or configuration instrumentation is required, ask for change authority.
- **Captured artifact.** Identify the format, transform large data into a queryable form, find the dominant frames or chains, resolve symbols, and compare paired captures when available.

Map the finding to files and symbols. Without source mapping or a confirming experiment, label it as the strongest supported hypothesis rather than a confirmed cause.

## Handoff

Lead with the answer. Cite files, symbols, commits, artifacts, or links close to the claims they support. Name uncertainty plainly. Do not create a code change, branch, or PR.
