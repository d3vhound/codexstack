# Evaluation record

Recorded on 2026-08-27 while preparing CodexStack 0.2.0.

## Passed

- Repository validator: 2 registered skills, 14 lazy references, 5 optional agent roles, 21,719 of 22,000 runtime words, and standard-library-only runtime helpers.
- Executable contract suite: 126 tests passed.
- Official OpenAI validators: both skills valid and the plugin valid.
- Codex CLI 0.150.1 detected the active ChatGPT login, added the local marketplace, and installed `codexstack@codexstack` 0.2.0.

## Not executed

Fresh-model runs of scenarios 7 and 12 were attempted but are **UNEXECUTED**, not passed or failed. In this managed development runtime, a nested `codex exec` did not start a thread before the 30-second bound, including for a control prompt that requested only `OK`. No workflow decision or plugin behavior was observable.

The complete 29-case catalog in [`scenarios.md`](scenarios.md) therefore remains a forward-evaluation suite to run in a normal Codex terminal or isolated Box. Unit and structural results above must not be presented as fresh-model behavioral parity.
