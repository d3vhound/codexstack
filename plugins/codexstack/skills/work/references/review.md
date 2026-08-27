# Review workflow

Review is read-only unless the user explicitly authorizes fixes. Never edit, push, reply, dismiss, resolve, merge, or message externally during review-only work.

## No-comments gate

Before review, commission a fresh read-only reviewer on the exact diff. It audits every added or changed comment, suppression, ignored error, disabled check, and workaround, demanding evidence for constraints that remain. The lead reads the diff and evidence, then accepts or rejects each finding independently. Only an authorized writer fixes accepted findings and reruns proof. The reviewer never mutates the artifact or supplies its own proof.

## State machine

1. **Contract.** Resolve base, head, scope, intent, and constraints from the prompt and repository evidence.
2. **Diff.** Inspect the complete diff plus affected callers, types, tests, config, migrations, generated artifacts, and runtime paths.
3. **Risk.** Prioritize correctness, security, privacy, data, concurrency, compatibility, behavior, operability, and missing proof over style.
4. **Pressure.** For broad, contested, or high-risk work, give two or three fresh reviewers the same intent, revision, constraints, and evidence standard. Partition by concern only when coverage earns its cost.
5. **Reconcile.** The lead reads cited code and every claim, then marks it confirmed, partial, contradicted, duplicate, or dismissed. Agreement raises confidence but proves nothing. Verify actionable claims with current code and practical read-only proof.
6. **Triage.** Return surviving findings before summary, ordered by severity. If none survive, say so and name proof gaps. Ask only when genuine ambiguity changes the verdict.

## Read-only boundary

Reading repository and linked evidence, plus non-mutating verification, is allowed. Without fix authority, never change source, tests, snapshots, locks, generated files, comments, suppressions, provider state, or verifier logic. For authorized fixes, use [change.md](change.md), limit scope, and review the resulting diff again.

## Findings and bot triage

Every actionable finding gives severity, file and symbol or line, failure mode, impact, evidence, and remediation or the minimum question.

- **Blocker.** Substantiated correctness, security, privacy, data-loss, severe-regression, or unsafe-release risk.
- **Should fix.** A real defect, compatibility break, missing migration or proof, or material maintenance risk.
- **Consider.** A supported tradeoff that may not justify changing this patch.
- **Dismissed.** Incorrect, unproven, style-only, duplicate, handled, or outside scope. Include useful disproof.

Never promote speculation to a bug. For automation, load [bugbot-triage.md](bugbot-triage.md) and label each finding **fix**, **dismiss**, or **ask**. Expose the disposition instead of forwarding bot claims.

## Comments and suppressions

Challenge narration, stale commentary, dead code, essays, and unexplained suppressions. Preserve legal headers, public contracts, concise external constraints, migration or incident rationale, and useful links. Prefer clear code or correct configuration over another comment.

## Output

Lead with findings. Give disposition, location, failure and impact, evidence, and fix or question. Then summarize exact revision and scope, proof, confidence, and gaps. Claim only supported confidence.
