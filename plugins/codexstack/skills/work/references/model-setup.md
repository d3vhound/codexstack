# Per-role model setup

Use this workflow only when the user asks to configure CodexStack models. It changes a persistent preference, so inspect first, show the complete proposed mapping, and write only after confirmation.

## Policy and precedence

CodexStack may read a project policy at `.agents/codexstack-models.json` or a personal policy at `~/.agents/codexstack-models.json`. The project policy wins as a whole. If neither exists, use available model controls and the qualitative defaults in the Work skill. Missing role keys fall back to those defaults.

`inherit-parent` and `auto` both mean omit the subagent model override. In a panel list each entry still creates one fresh agent, so list length is panel size. For `arena cross-judge pool`, prefer an available family or tier different from the parent and selected base. `swarm workers` is the default for each worker unless a declared race assigns models per arm.

## Setup states

1. **Detect.** Enumerate only model IDs exposed by the current Codex agent controls, installed model picker, or another authoritative current source. Codex CLI does not promise a universal subscription-entitlement listing. If no authoritative list is exposed, ask the user to paste the available IDs. Never guess a real ID. The two aliases are always valid.
2. **Load.** Read the selected project or personal policy if it exists. Otherwise load `../assets/model-policy.example.json`. Read-only inspection needs no write authority.
3. **Show every role.** Present the effective value and source for all scalar roles: `feature, refactoring`; `bug-fix`; `perf-issue`; `hillclimb`; `judgment and prose`; `hardest tasks`; `how explorer`; `how explainer`; `why investigators`; `why synthesizer`; `reflect tooling`; `reflect judgment, divergent, synthesizer`; and `swarm workers`. Then show all panel lists and counts: `how critics`; `arena runners`; `arena cross-judge pool`; `architect runners`; and `interrogate reviewers`. Mark unavailable real IDs.
4. **Confirm.** Ask whether to keep the complete mapping or change named roles. Offer only detected IDs, `inherit-parent`, and `auto`. Preserve repeated alias entries because they preserve independent panel seats.
5. **Validate.** Every real ID must be in the detected set and every panel must contain 1 through 16 entries. Run the passive validator with one flag per detected model:

   ```bash
   python3 plugins/codexstack/skills/work/scripts/model_policy.py \
     .agents/codexstack-models.json \
     --available gpt-example-a --available gpt-example-b
   ```

   For the personal policy, run from the home directory and use `.agents/codexstack-models.json`. Do not expose or copy unrelated user configuration. A failed validation blocks use of that policy.
6. **Write idempotently.** After explicit confirmation, replace the selected JSON policy with the whole confirmed mapping, run validation again, and show the result. Preserve the prior bytes until the candidate is valid so a failure can be restored exactly. The change applies to new delegations; it does not alter agents already running.
7. **Use.** At each delegation, load the winning policy once. Omit `model` for an alias. Otherwise pass the exact validated ID. If Codex still rejects a formerly observed ID, use an available same-family equivalent or inherit the parent for the current run, disclose the fallback, and offer a separate policy update. Do not block useful read-only investigation on a stale preference.
8. **Offer verification once.** Inspect for a project verifier or real interaction harness. If neither exists, offer once to create a project-local verification skill. A decline ends setup without pressure.

The validator is read-only, standard-library-only, and does not discover entitlements or write Codex configuration. Optional agent TOMLs remain copyable role defaults, not the persistent policy itself.
