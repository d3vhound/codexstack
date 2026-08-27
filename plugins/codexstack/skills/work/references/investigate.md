# Investigation workflows

Investigations are read-only. The deliverable is an evidence-backed explanation, diagnosis, recommendation, or decision brief. Do not create code changes, branches, PRs, messages, or durable external writes unless the user expands the task.

## Shared investigation loop

1. **Ground.** Identify the question, affected surface, entry points, current repo guidance, dirty state, and available evidence sources.
2. **Classify.** Decide whether the user is asking **how** the system works, **why** it has this shape, blast radius, runtime diagnosis, captured-artifact forensics, recall, or teach.
3. **Federate evidence.** Use all relevant available evidence categories by default, but do not pretend unavailable connectors exist.
4. **Separate synthesis.** Keep raw category findings separate from the final synthesis. Resolve contradictions explicitly.
5. **Handoff.** Lead with the answer, cite nearby evidence, include confidence tiers, and name what would change the conclusion.

## Confidence tiers

Use these exact labels:

- **Direct.** The claim is stated by the relevant source or directly observed in source/runtime/artifact evidence.
- **Supported.** Multiple signals or a strong primary signal support the claim, with limited inference.
- **Inferred.** The claim follows from structure, timing, or behavior, but no direct source states it.
- **Speculative.** Plausible but weakly evidenced; useful only as a hypothesis or next check.
- **Unknown.** Evidence is unavailable, contradictory without resolution, or not yet inspected.

## How the system works

Use **Explain** by default for mechanism questions. Trace from a real entry point to its effect:

1. Identify trigger, inputs, owning types, and user-visible or caller-visible surface.
2. Follow callers, callees, state transitions, boundaries, side effects, and generated artifacts.
3. Read implementation and tests. Do not infer behavior from filenames.
4. If broad, assign distinct read-only slices such as data model, request flow, persistence, UI, tests, observability, or deployment. When native delegation is unavailable, trace the same slices sequentially and disclose the degraded topology rather than inventing investigators. Each slice reports null findings when applicable.
5. Synthesize separately from the slice notes and state confidence per important claim.

Return only the sections the question needs: overview, key concepts, runtime/data flow, important files/symbols, gotchas, gaps.

### Critique mode

Use Critique for “are we sure?”, “is this good?”, architectural challenge, or requests for problems and improvements. Complete Explain first. Criticism without the current mechanism is guesswork.

Then give multiple independent fresh read-only critics the explanation, current artifact or exact revision, relevant file paths, evidence, and one shared rubric. Cover abstraction fit, data model, boundary discipline, evolution readiness, complexity versus value, and repository consistency. Critics inspect the code themselves and report each structural issue with severity, concrete evidence, and practical impact. Prefer model-family diversity; if it is unavailable, disclose fresh same-family contexts and do not call agreement cross-model confirmation.

Reconcile through the [Interrogate](deliberate.md) mechanics. The lead reads the cited code and assigns each finding exactly **Act**, **Consider**, **Noted**, or **Dismissed**. Agreement prioritizes inspection and never proves a claim. Present the standalone explanation first, then the disposition table. Critique remains read-only unless the user separately asks for a change.

## Why it has this shape

Code shows what exists, not necessarily intent. Anchor the target with files, symbols, owners, line history, and recent commits, then federate across available source categories.

Build a coverage map for exactly these seven evidence categories. Source control is always available through the repository; discover configured plugins/MCP for the other six. Spawn one read-only investigator per available category, in parallel. Never collapse categories into one investigator merely to save context.

1. **Source control history.** Git history plus provider PRs/reviews, code comments, tests, migrations, and release notes.
2. **Issue or ticket tracking.** Issues, product forcing functions, customer reports, project context, scope changes, and acceptance criteria.
3. **Long-form documents.** PRDs, specs, RFCs, ADRs, postmortems, runbooks, and meeting notes.
4. **Real-time team chat.** Decision threads, incident channels, author discussion, and rationale never formalized elsewhere.
5. **Infrastructure observability.** Metrics, logs, traces, monitors, dashboards, and incident timelines.
6. **Error or exception tracking.** Issues, events, stack traces, releases, and first/last-seen correlations.
7. **Product analytics warehouse.** Usage, experiment or flag exposure, billing/data events, distributions, and migration/query history.

Each category report must say one of:

- **Found.** Include exact evidence and confidence.
- **Null.** Searched successfully and found nothing relevant.
- **Unavailable.** Connector, permission, index, artifact, or time range was not available.
- **Skipped.** Not relevant enough for this question; include why.

Then synthesize separately:

1. Separate direct intent evidence from inference.
2. Surface contradictions instead of silently choosing the neatest story.
3. Never retrofit a satisfying rationale from present code shape.
4. Use decisive language only for **Direct** evidence.

## Blast radius

Use this for “what would this affect?”, “is this safe?”, “can we change X?”, and architectural decisions.

1. Map callers, consumers, persisted formats, configuration, generated artifacts, tests, concurrency, permissions, deployment, and external contracts.
2. Identify the safety property the proposed change depends on.
3. Push every load-bearing fact down this proof ladder as cheaply as possible: assertion only; exact source line; demonstrate the bad path cannot reach; execute the real shipped code; reproduce in the running application. A grep result or convincing writeup is not execution. Anything below executed real code remains unproven unless that rung is unavailable or disproportionate.
4. Compare options against explicit criteria: behavior, migration cost, failure modes, operability, reversibility, and user impact.
5. Recommend a path, tradeoffs, confidence tier, and evidence that would change the recommendation.

Use competing design candidates only for consequential unresolved forks. If the answer is empirical, prefer a small probe.

## Recall

Use this when the user asks to remember, continue prior work, or align with existing project knowledge.

1. Classify the request. One specific prior session routes to pickup/resume; a named topic across recent work routes here.
2. Lock the time window, topic, and active workspace before searching. Default “recent” to seven days, state that choice, exclude the current session, and never read another workspace without permission.
3. For a large authorized history corpus, partition bounded time slices among read-only investigators. Sort by real modification time, search the topic before opening records, keep raw transcripts out of the lead context, and return per-session goal, decisions, open threads, corrections, and artifact identifiers. Do not assume transcript locations or access that the environment does not expose.
4. When the topic names a feature, file, subsystem, or bug, run the available seven-category Why sweep in parallel for current state, failed prior attempts, and continuing reports. Record null/unavailable categories. Pure activity recall with no named target may skip this sweep with that reason.
5. Verify PRs, branches, tickets, tests, and reversions against current repository/provider state. A transcript or agent claim is history, not current truth.
6. Return a capsule of at most five bullets; one status-tagged line per thread; at most five recurring problems; and one concrete next move. Separate remembered facts from inference and sanitize private context.

Do not apply recalled preferences as authority for external writes or risky changes unless the current request authorizes them.

## Teach

Use this when the user asks for explanation, onboarding, or transfer of understanding.

1. Orient in the actual implementation, then run the matching **How** and **Why** investigations in parallel when the subject is a subsystem. A small change may need only one, with the skipped route explained.
2. Decide the few ideas the user needs from their question and existing context; do not quiz them for a level.
3. Start with the smallest plain definition, then layer current mechanism, historical rationale, edge cases, and where to look next. A symbol catalog is reference, not teaching.
4. Preserve Why's confidence language exactly. Reword for clarity, but never turn Speculative or Inferred rationale into fact.
5. Use a small progressive sequence of diagrams only when three or more moving parts make the model easier to learn. Avoid one crowded all-at-once diagram, quizzes, pacing theater, and code edits.

## Runtime or captured-artifact diagnosis

Keep diagnosis separate from implementation unless the user asks for a fix.

- **Live symptom.** Capture the signal on the matching surface, reduce it to the hot path, retention chain, loop, race, allocation source, or failing transition, then use existing non-persistent observability to test the mechanism. If code/config instrumentation is required, ask for change authority.
- **Captured artifact.** Identify the artifact format, time/window, transform large data only enough to query it, find dominant frames/chains/transitions/events, resolve symbols, and compare paired captures when available.

Map findings to files and symbols. Without source mapping or confirming experiment, label the result as **Supported** or **Inferred**, not **Direct**.

## Handoff

Lead with the answer. Cite files, symbols, commits, artifacts, links, or category reports close to the claims they support. Include null/unavailable reports when they affect confidence. Do not create a code change, branch, PR, external message, or durable write.
