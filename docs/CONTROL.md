# CodexStack control plane

CodexStack's control plane is a thin local surface over managed [ASCII Box prompts](https://docs.ascii.dev/box/api/v1) and GitHub. It gives one operator a Cursor-like run inbox, transcript, review pane, and matching MCP tools without becoming another cloud-agent platform.

The v0 boundary is deliberate:

- Box owns compute, prompt state, event streams, files, snapshots, desktop sessions, and hosted previews.
- GitHub owns branches, pull requests, and check state.
- CodexStack stores one `AgentRun` table in SQLite and reconciles those two authorities.
- The installed plugin launches the controller over stdio. Optional UI mode serves the browser and an HTTP MCP endpoint from one loopback process. There is no second scheduler or worker daemon.

An `AgentRun` records the run id, Box and prompt ids, repository, exact base SHA, branch, requested model, status, creation time, optional PR identity, and optional preview port. Prompt bodies, signed desktop and preview URLs, Box events, access tokens, and Box API keys are never stored.

## Concurrency model

One start creates one writable Box and one branch. `CODEXSTACK_MAX_PARALLEL` defaults to `4`, but it is only an admission limit for unreleased Box reservations. Needs-input, review, failed, and local-change runs keep their slot while their Box remains available. Stop the run or let Box archive it to release capacity. The limit does not create four permanent patrol agents, queue work, or replenish a fleet in the background.

Native Codex subagents may work inside a Box under `$codexstack:work`. The v0 UI intentionally shows Box-level workers, not a fabricated nested-agent tree. Box account limits and ChatGPT plan limits remain separate constraints. See [Box billing and limits](https://docs.ascii.dev/box/billing).

## Repository contract

Each controlled repository commits `.codexstack/worker.json`. Commands are JSON argument arrays, not shell fragments, so the controller can validate and execute each boundary without a second command language.

```json
{
  "contractVersion": "codexstack.worker.v1",
  "baseRef": "main",
  "workingDirectory": ".",
  "setup": [
    ["npm", "ci"]
  ],
  "verify": [
    ["npm", "test"],
    ["npm", "run", "typecheck"]
  ],
  "preview": {
    "command": ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"],
    "port": 3000
  }
}
```

Use an empty `setup` array when the Box template already contains everything required. An open-PR run requires at least one `verify` command. Set `preview` to `null` when the repository has no browser surface. Keep secrets out of this file. The exact base SHA, branch, requested authority, and run id are dynamic controller state, not repository-granted authority.

## Start the local service

Build the credential-free template and private owner environment described in [BOX.md](BOX.md), then configure the controller:

```bash
export BOX_API_KEY="..."
export CODEXSTACK_ALLOWED_REPOS="owner/repository,owner/second-repository"
export CODEXSTACK_BOX_ENVIRONMENT="codexstack"
export CODEXSTACK_BOX_TEMPLATE="codexstack-base"
export CODEXSTACK_CONTROL_DB="$PWD/.codexstack/control.sqlite3"
export CODEXSTACK_MAX_PARALLEL="4"

gh auth status

PYTHONPATH=plugins/codexstack/runtime \
  python3 -m codexstack_control serve
```

Open `http://127.0.0.1:8765`. The built-in server always binds to loopback; `CODEXSTACK_CONTROL_PORT` can change its port. `CODEXSTACK_CONTROL_TOKEN` is optional on loopback. The UI keeps a supplied token in session storage and never puts it in a URL.

For a private mobile-browser view, put an operator-controlled HTTPS tunnel or reverse proxy in front of the loopback listener, preserve its public `Host`, and set both `CODEXSTACK_PUBLIC_URL=https://control.example.com` and a high-entropy `CODEXSTACK_CONTROL_TOKEN`. The built-in server still refuses a non-loopback bind. This is a single-operator browser path, not a hosted ChatGPT Work MCP or multi-user OAuth service.

Other relevant settings are `CODEXSTACK_DEFAULT_TTL_SECONDS`, which defaults to `43200`, and `CODEXSTACK_BOX_BASE_URL`, which is intended for tests or an explicitly selected compatible Box endpoint.

## Run lifecycle and PR guarantee

An open-PR run follows one fail-closed sequence:

1. Enforce the local admission limit and confirm Box can start another machine.
2. Create or reconcile a Box with a finite TTL and an idempotency key.
3. Read a bootstrap `.codexstack/worker.json` only to identify the requested base.
4. Fetch the base, resolve its full SHA, reread and strictly validate `worker.json` from that exact commit, and create `codexstack/<run-id>-<slug>` from the same revision.
5. Run each declared setup command in order and require a clean tracked worktree afterward.
6. Start one managed Box prompt that activates `$codexstack:work`, implements the scoped goal, runs verification, commits, pushes, and opens one non-draft PR. It is never authorized to merge.
7. On handoff, rerun every declared verification command through a separate controller request at the unchanged local head. Reject dirty state, Git history indirection, and tracked index flags that can hide worktree changes.
8. Query the remote branch in the worker and query GitHub again from the controller host through authenticated `gh api`. Require the expected repository owner, open non-draft state, base and head branch, and identical local, remote, and PR head SHAs.

An agent's final prose is not delivery evidence. A changed head invalidates verification. A missing or mismatched PR moves the run to a state that needs human action instead of being rounded up to success. CodexStack never merges, force-pushes, rebases shared work, retargets, closes, or deletes a PR.

The independent guarantee in this gate is PR identity: the controller proves that the local branch, pushed branch, and GitHub PR name the same exact commit. Declared checks still execute inside the same mutable, credentialed Box that authored the change. Their receipts are useful operational evidence, not tamper-resistant attestation against a hostile or compromised worker OS; Git clean/smudge filters and other same-user process state make that impossible to promise from the working checkout alone. Repositories that require independent test proof must enforce required GitHub CI and base-branch protection with no worker bypass. The controller reports those provider checks for review but does not impersonate them.

## Monitor and steer

The UI has four working areas:

- Left rail: Active, Needs You, Review, and Done runs.
- Center: streamed assistant messages with collapsible command and tool results.
- Right pane: branch, changed files, verification, PR, preview, and live sandbox controls.
- Bottom composer: **Send next** and **Interrupt & redirect**.

Prompt status is fetched separately from Box events and remains the lifecycle authority. All unreleased workers are refreshed, including workers not selected in the UI. A finished worker enters **Needs You** until the operator or an authorized MCP coordinator explicitly calls `run_handoff`; the UI never treats a finished turn as automatic delivery. **Send next** wraps the operator message in the same immutable `$codexstack:work` contract. **Interrupt & redirect** explicitly interrupts the Box-wide managed turn before sending replacement direction. A `codex` process started over SSH is outside the [Box event feed](https://docs.ascii.dev/box/api/reference/agent/list-box-events) and cannot appear as a managed UI run.

Desktop and preview links are browser capabilities. **Open live sandbox** requests a fresh authenticated [desktop-streaming URL](https://docs.ascii.dev/box/desktop-streaming) when clicked; Box desktop URLs expire after ten minutes. Preview starts only the repository-declared command, then requests a protected machine-readable [application hosting URL](https://docs.ascii.dev/box/hosting) from Box's hosting endpoint. Box returns the same protected URL for a Box and port, so it is requested only when clicked but is not described as freshly rotated. Neither signed URL is persisted or returned through MCP. The loopback HTTP process is inside the same local trust boundary as other processes running as that OS user, so MCP redaction is not an isolation boundary against a local process that can directly call the API.

## Codex MCP

The installed plugin launches its bundled standard-input server from the installed plugin's `runtime` directory. It does not require a source checkout or a prestarted localhost daemon. Inspect it with `codex mcp list`. The bundled timeout is six hours because deterministic setup and verification are synchronous, bounded operations.

The optional controller runtime currently requires `python3` on macOS, Linux, or Box. The core skills remain usable without it. One process owns each control database; a second stdio or UI process fails closed instead of racing Box mutations. Concurrent MCP tool calls inside that owner remain independent across run ids.

Use Codex's `writes` approval policy so read tools remain automatic and paid or mutating tools prompt:

```toml
[plugins."codexstack@codexstack".mcp_servers.codexstack_control]
enabled = true
default_tools_approval_mode = "writes"
```

When using the web UI, run one controller process only. Disable the bundled stdio server and point a separately named MCP entry at the UI process:

```toml
[plugins."codexstack@codexstack".mcp_servers.codexstack_control]
enabled = false

[mcp_servers.codexstack_control_ui]
url = "http://127.0.0.1:8765/mcp"
bearer_token_env_var = "CODEXSTACK_CONTROL_TOKEN"
default_tools_approval_mode = "writes"
tool_timeout_sec = 21600
```

The MCP surface is intentionally small:

```text
run_start       run_list        run_read       run_wait
run_message     run_interrupt   run_desktop    run_stop
run_resume      run_handoff
```

Tool descriptions preserve paid-compute and mutation boundaries. `run_start` requires an explicit delivery mode. `run_desktop` returns a control-page address, never the signed Box URL, and says when the optional UI service must be started. Do not run the stdio and HTTP controller against the same database at the same time. See [Codex MCP](https://developers.openai.com/codex/mcp).

This v0 does not advertise a fake hosted MCP URL. ChatGPT Work cannot reach a local stdio process or another machine's loopback listener. A hosted plugin MCP would need real HTTPS, OAuth, and per-user authorization. The optional HTTPS tunnel above exposes only the single-operator browser UI.

## Security boundaries

- The controller keeps `BOX_API_KEY` server-side. Worker Boxes receive selected GitHub and Codex credentials but no fleet-level Box credential.
- `CODEXSTACK_ALLOWED_REPOS` is an explicit start allowlist. Repository config cannot expand repository or merge authority.
- The controller exposes no merge operation. A GitHub-capable worker still holds credentials, so a technical no-merge guarantee also requires base-branch rules with required review or checks and no bypass for the worker identity. Prompt text is policy, not credential isolation.
- Strict JSON parsing rejects duplicate and unknown fields. Repository commands are bounded argument arrays.
- The SQLite database and sidecar files are owner-readable only. Goals remain in Box prompts and are represented locally only by a request hash and neutral run title.
- Mutating HTTP calls require the same-origin CSRF value. The service does not enable cross-origin access.
- Signed URLs use `no-store` responses and are minted only on operator clicks.
- Box creation can be retried with its idempotency key. Ambiguous command and prompt writes are reconciled instead of blindly replayed.
- Finite TTL, ordinary stop, and resume are supported. Permanent Box deletion is not exposed.

## Verification status

The controller is covered offline against a fake Box HTTP service so requests, authentication, idempotency, event cursors, lifecycle transitions, persistence, MCP calls, and the HTTP/UI-route contract can be exercised without paid compute. JavaScript syntax is checked with Node, but browser rendering and interaction remain unproven until a browser-engine canary runs. These checks prove the local contract, not the provider integration.

A real authenticated Box-to-tested-PR run, including live desktop, preview, ChatGPT plan-backed Codex use, GitHub push, and PR verification, remains unproven until an owner runs the canary with their private environment. Do not describe an offline fake-Box pass as a live provider pass.

## Deliberately rejected in v0

| Alternative | Reason rejected |
| --- | --- |
| A second cloud-agent platform | Box already owns execution, lifecycle, events, files, previews, and desktops. |
| Queues or a background scheduler | Explicit starts plus a bounded admission limit cover the single-operator workflow. |
| A custom worker daemon | Managed Box prompts already provide the observable execution path. |
| Codex app-server | It adds another session protocol before structured nested transcripts or approvals justify it. |
| ACP or A2A | There is no cross-provider negotiation problem in the v0 run path. |
| A React build and dependency surface | A small static UI keeps installation, startup, and audits inside the standard-library service. |
| A hosted multi-user MCP endpoint | ChatGPT Work access requires a real deployment, OAuth, and per-user policy. |

The service isolates the Box adapter from the run model so another execution harness could implement the same contract later. V0 makes no claim of supporting such an adapter: managed Codex prompts on Box are the only implemented execution path.

CodexStack preserves the throughput and evidence obligations of Lauren Tan's Poteto/pstack work while expressing them through Codex-native skills, MCP, authority checks, and Box boundaries. It is an independent adaptation and is not affiliated with or endorsed by Lauren Tan, Cursor, ASCII, or OpenAI.
