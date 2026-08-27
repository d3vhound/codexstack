# Box security and platform boundaries

Read this before any Box environment, snapshot, authentication, remote-access, or lifecycle mutation.

## Trust boundary

| Surface | Contains | Rule |
| --- | --- | --- |
| Named snapshot/template | `/home/user`, installed packages, system configuration | Build only from a `box new --no-env` source. Prove managed credential files are absent before saving. |
| Private environment | Selected repositories and owner credentials | Use only for Boxes the account owner drives. Enable GitHub and Agents credentials; keep Secrets and Box credentials off until separately justified. |
| Protected environment / `--no-env` | Neutral Box-internal values and explicitly supplied per-Box values | Use for third-party or untrusted control. It receives no owner GitHub, Secrets, Box, or Agents credentials. |
| Repository/profile/prompt | Durable or observable text | Never place tokens, `auth.json`, secret values, private keys, or credential-file contents here. |

An ordinary Box environment can inject `OPENAI_API_KEY`, `CHATGPT_ACCOUNT_ID`, `~/.codex/auth.json`, `~/.config/gh/hosts.yml`, git credentials, configured secret files, and an in-Box Box token. `safe-for-third-parties=true` or `--no-env` prevents all **owner** credential categories regardless of individual toggles. Box still supplies neutral machine-internal values such as `BOX_ID` and a machine-scoped `ASCII_TOKEN`; these are not owner account credentials and are not a reason to save or expose runtime state. Converting an existing Box with `resume` or `fork --no-env` scrubs Box-managed GitHub, Codex, Claude, Box, secret-file, and common SSH credentials and is one-way; credentials added manually to other stores may remain.

After a private environment starts, the working Box and its automatic snapshots may contain injected credential files. Keep that Box private. Do not fork it into a different trust domain or save it as the reusable named template. A later `--no-env` conversion scrubs Box-managed credentials, but the conversion is one-way and does not remove every credential a user may have added manually.

Environment versions are immutable. A running Box stays pinned until an explicit `box env upgrade`. Withholding credentials on upgrade deletes the managed copies from that Box; selecting an older version does not restore them.

## Authentication

- **Preferred managed path:** connect Codex to ChatGPT on Box's Agents page, then inject Agents credentials only through the private environment. This supports `box prompt --provider codex`.
- **Trusted interactive fallback:** run `codex login --device-auth` inside the Box and complete the one-time browser code. ChatGPT login uses subscription access; an OpenAI API key uses API billing.
- Codex may cache access and refresh tokens in plaintext at `~/.codex/auth.json`. Treat it as a password. Never copy it into a template, repository, profile, prompt, log, issue, or chat.
- A direct CLI login and Box's managed Agents connection are distinct control planes. Do not assume one configures the other.
- Personal ChatGPT auth is appropriate only in a Box controlled by that user. For unattended shared CI, OpenAI recommends API keys rather than personal account auth.

## GitHub, plugins, MCP, and skills

- Connect GitHub in Box and enable GitHub only in the private environment. Keep the clean template public and credential-free.
- Reconstruct plugins with `codex plugin marketplace add`, `codex plugin marketplace upgrade`, and `codex plugin add`. Do not snapshot an authenticated Codex home.
- Project skills belong in `.agents/skills/`; personal skills use `~/.agents/skills/`; plugins can package skills. Treat any personal material placed in a snapshot as part of that snapshot.
- Put MCP definitions in the plugin or trusted Codex config. Prefer `env_vars` and `bearer_token_env_var`; never store literal bearer tokens in committed TOML.
- OAuth grants are host-local state. A new Box, a protected conversion, or a clean rebuild may require `codex mcp login SERVER` and plugin/connector reauthorization.

## Lifecycle and steering

- Default to a finite TTL. CodexStack uses 43,200 seconds; Box defaults to 3,600 and caps TTL at 2,592,000 seconds. Do not use `--no-auto-stop` by default.
- `box stop` snapshots before pausing and is recoverable. Do not expose `box delete` through the helper; deletion is irreversible.
- A named snapshot captures disk and configuration, not running processes, memory, or open ports. Manual background processes do not survive stop/resume.
- `box prompt`, `box events`, and `box interrupt` control Box-managed agent work. They do not control or observe an unrelated process launched through SSH.
- `box forward` binds locally to `127.0.0.1` by default. Keep it loopback-only. Never expose Codex app-server directly to a public or shared network; its WebSocket transport is experimental and non-loopback listeners may be unauthenticated.

## Mobile and desktop

Bare Box CLI threads are not documented as discoverable in ChatGPT mobile. The supported path is Mobile Remote through a paired ChatGPT desktop app on macOS or Windows. The desktop app can add an SSH host and start the remote Codex app-server on it; mobile connects to that desktop host. Setup cannot begin from the CLI or IDE. Use trusted SSH keys, a least-privilege remote user, and no public app-server listener.

## Primary sources

- ASCII Box: [CLI reference](https://docs.ascii.dev/box/cli-reference), [environments](https://docs.ascii.dev/box/environments), [snapshots and copies](https://docs.ascii.dev/box/snapshots), [setup and scripts](https://docs.ascii.dev/box/setup), [long-running tasks](https://docs.ascii.dev/box/long-running-tasks), [SSH access](https://docs.ascii.dev/box/ssh-access), [machine capabilities](https://docs.ascii.dev/box/machines), [API v1](https://docs.ascii.dev/box/api/v1)
- OpenAI Codex: [authentication](https://developers.openai.com/codex/auth), [pricing and subscription access](https://developers.openai.com/codex/pricing), [CLI](https://developers.openai.com/codex/cli), [developer commands](https://developers.openai.com/codex/developer-commands), [plugins](https://developers.openai.com/codex/plugins), [skills](https://developers.openai.com/codex/build-skills), [MCP](https://developers.openai.com/codex/mcp), [remote connections](https://developers.openai.com/codex/remote-connections), [app-server](https://developers.openai.com/codex/app-server)
