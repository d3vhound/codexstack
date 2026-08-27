# Evaluation workflow

Use this route to test a skill, prompt, workflow, or structural variant without telling candidates what behavior is being measured.

## Frame

1. Name the variant and the decision the evaluation will make.
2. Define three to six observable criteria and hard safety gates. Keep the rubric from candidates.
3. Choose an organic user prompt. Do not mention evaluation, principles, hidden checks, or the desired process.
4. Establish a plugin-disabled or current-version control when comparison adds useful signal. Absolute gates still matter more than beating the control.

## Isolate

- Give each candidate an equivalent clean workspace with only the context an ordinary task would have.
- Keep candidates, fixtures, hidden checks, and judge artifacts in separate paths.
- For code-writing candidates, isolate writes with distinct worktrees or directories.
- Use the same model and reasoning when testing the workflow itself. Vary them only when model robustness is the question.
- Run enabled and plugin-disabled controls in separate clean Codex sessions or profiles with the intended skill configuration. If candidates can see the rubric or cannot be isolated from CodexStack, label the comparison unblinded and do not claim a causal skill effect.

## Run

1. Start candidates in parallel with the same prompt.
2. Capture observable chronology where available: files read, commands, agent activity, mutations, test outcomes, and final artifact.
3. Run deterministic hidden checks against the artifact. Grade behavior from events, diffs, exit codes, and runtime results rather than the candidate's description.
4. Give sanitized outputs and the hidden rubric to one blinded judge only for criteria that need semantic judgment. Hide model, variant, and skill identities.

## Synthesize

- Read every candidate result and the judge verdict.
- Reconcile disagreements against raw artifacts.
- Distinguish workflow failure, verifier failure, environment failure, and candidate dropout.
- Report hard-gate results, criterion scores, evidence paths, and the decision.

Do not promote a variant from one lucky run. Repeat meaningful scenarios, include negative and boundary cases, and retain a trivial task that should avoid orchestration.
