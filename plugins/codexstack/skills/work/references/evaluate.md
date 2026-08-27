# Evaluation workflow

Evaluate a skill, prompt, workflow, model-role policy, or structural variant through blinded artifact evidence. Do not tell candidates what behavior is being measured.

## Frame

1. Name the decision the suite will make.
2. Define three to six observable criteria plus hard safety gates. Keep the scoring rubric outside every candidate-visible path and prompt.
3. Choose organic tasks that expose the behavior without naming it.
4. Include an appropriate control, such as current version, plugin-disabled, or unchanged configuration. Absolute safety and correctness gates outrank relative scores.
5. Predeclare promotion, rejection, and inconclusive rules.

A useful suite includes:

- at least one realistic non-trivial task;
- a trivial task that should avoid orchestration;
- a negative or adversarial case;
- a boundary case for authority, write isolation, or evidence;
- a resume, revision-drift, or failure-recovery case when evaluating long-running behavior.

## Blind

Candidate-visible prompts, filenames, directory names, fixtures, and environment labels must not reveal evaluation, scoring, comparison, hidden principles, candidate identity, or the desired process.

- Use project-shaped names, not candidate or judge labels.
- Give each candidate only the context an ordinary user task would provide.
- Do not ask candidates to list skills, principles, reasoning, or rubric compliance. Grade observable behavior.
- Do not tell candidates that other candidates exist.
- Judges may know they are judging, but see randomized sanitized labels, never model, variant, skill, or control identity.
- Each semantic judge scores all comparable outputs in one pass on one rubric. Separate judge prompts create calibration drift.

If isolation or blinding fails, label the run unblinded. Do not claim a causal workflow effect.

## Cross model and variant

Use model diversity as a crossed factor, not a confound.

1. Represent each tested variant on the same candidate model families or capability tiers where access permits.
2. Run multiple capable families or tiers for consequential behavior claims. Use more than one run when stochastic variance could decide the outcome.
3. Give every candidate the same frozen task, resources, authority, time budget, and reasoning policy for its matched comparison.
4. Use at least one semantic judge from a different available family or tier than the candidate selected as the proposed base.
5. When only one family or override is available, use fresh isolated contexts, disclose the same-family limitation, and do not call agreement cross-model confirmation.

Deterministic artifact checks remain primary. Model consensus directs inspection; it does not establish correctness.

## Isolate

- Use equivalent clean repositories, worktrees, or directories.
- Separate candidate writes, fixtures, hidden checks, judge packets, and results.
- Use separate Codex sessions or profiles for enabled and disabled controls with the intended skill and plugin configuration.
- Freeze starting commits, dependencies, fixtures, environment variables, and capability availability.
- Prevent candidates from reading sibling outputs, hidden rubrics, or judge artifacts.
- Keep secret values and unrelated transcripts outside all environments.

When evaluating a workflow rather than a model, hold the candidate-model distribution constant across variants. When evaluating model robustness, declare model variation as the independent variable.

## Run

1. Start matched candidates in parallel with the same organic prompt.
2. Capture only available, authorized evidence: starting and ending SHAs, files and commands observed, native agent activity, mutations, exit codes, test output, provider effects, timing, and final artifacts.
3. Run deterministic hidden checks against each artifact. Include checks for required absences such as no write during read-only mode, no merge without authority, or no orchestration on the trivial case.
4. Build sanitized semantic packets from artifacts and observable chronology. Remove model, variant, path, and ordering clues.
5. Give all comparable packets and the frozen rubric to each blinded judge in one pass.

Do not rely on candidate self-reports or invent transcript access. If the environment exposes authorized local traces, use them only within the active workspace and grade observed actions rather than claimed intent.

## Synthesize

The lead reads every candidate artifact, deterministic result, and judge verdict.

1. Reconcile semantic disagreement against raw artifacts.
2. Separate workflow failure, candidate dropout, verifier defect, environment failure, and insufficient evidence.
3. Report hard-gate results before aggregate scores.
4. Analyze results by variant and model family or tier so one strong model cannot hide a fragile workflow.
5. Record evidence paths, exact revisions, run counts, variance, limitations, and the promotion decision.

Never promote from one lucky run. Repeat decision-changing scenarios. A variant that wins averages but violates a hard safety gate fails.

## Reply

Report the decision, suite and controls, blinding status, model-diversity coverage, hard gates, criterion results, judge agreement and disagreements, evidence locations, limitations, and whether to promote, revise, reject, or rerun.
