# CodexStack on ASCII Box

ASCII Box is CodexStack's optional cloud execution layer. The recommended setup is deliberately simple: freeze public tooling into a credential-free template, then inject narrowly scoped account access from a private Box environment each time a Box starts.

## What this gives you

- disposable Linux compute with Codex CLI, `git`, `gh`, Node, Python, SSH, snapshots, and finite TTLs;
- ChatGPT plan-backed Codex login, including Pro, without an OpenAI API key;
- managed prompts, event streaming, interruption, and interactive SSH steering;
- reproducible CodexStack plugin, skill, and MCP setup instead of copying a workstation home directory;
- an SSH path from the ChatGPT desktop app for supported mobile handoff.

The Box skill is explicit-only. Invoke `$codexstack:box`; ordinary CodexStack work does not create cloud resources or move credentials.

## 1. Install and connect accounts

Install the Box CLI and complete its browser onboarding:

```bash
curl -fsSL https://box.ascii.dev/install | sh
box onboard
box status
```

Open `box dashboard` and make two connections:

1. Under the environment settings, connect GitHub.
2. Under **Agents → Codex → ChatGPT**, choose **Sign in with ChatGPT** and use a ChatGPT account or workspace with Codex access. Pro is included but is not required.

ChatGPT login consumes subscription Codex allowances. Supplying `OPENAI_API_KEY` is a different path billed as API usage. For a headless direct login, `codex login --device-auth` is the supported native flow; enable device-code login in ChatGPT security settings first if necessary.

## 2. Create the private environment

Copy and edit the credential-free example if you need custom names or repositories:

```bash
cp plugins/codexstack/skills/box/assets/profile.example.json ./box-profile.json
```

Do not add tokens or secret values to that file. Then create the environment:

```bash
python3 plugins/codexstack/skills/box/scripts/boxctl.py \
  --profile ./box-profile.json env-init --yes
```

The helper configures this exact posture:

| Setting | Value | Why |
| --- | --- | --- |
| Safe for third parties | Off | This environment is only for Boxes you control. |
| GitHub | On | Selected repositories clone in and `gh`/push can authenticate. |
| Secrets | Off | App and deployment secrets require a separate, deliberate decision. |
| Box credentials | Off | Owner Box credentials are withheld, so the Box cannot manage its own lifecycle through them. |
| Agents credentials | On | Codex receives the Box-managed ChatGPT login. |

`box env new` initially enables all credential categories. The helper immediately protects the new environment, adds repositories while protected, and only then atomically applies the intended private posture. If setup fails, it attempts to leave the environment protected.

For any Box controlled by another person or processing untrusted instructions, use `box new --no-env` or a `safe-for-third-parties=true` environment instead. Never attach the private environment.

## 3. Build the clean template

```bash
python3 plugins/codexstack/skills/box/scripts/boxctl.py \
  --profile ./box-profile.json template-build --yes
```

This starts a short-lived Box with `--no-env`, installs the public `d3vhound/codexstack` marketplace and plugin, checks that common Codex, GitHub, git, Box, and SSH credential files are absent, saves `codexstack-base`, and requests a stop for the source Box. Box archives asynchronously; use `box info BOX_ID` to confirm `archived` before treating compute as stopped. Here, “credential-free” means free of **your owner credentials**; Box still supplies neutral machine identity while a Box runs. A template stores disk state; an environment supplies credentials later. Do not build templates by forking an authenticated work Box.

## 4. Launch and verify

```bash
BOX_ID="$(python3 plugins/codexstack/skills/box/scripts/boxctl.py \
  --profile ./box-profile.json launch --yes)"

python3 plugins/codexstack/skills/box/scripts/doctor.py --box "$BOX_ID"
```

The default TTL is 43,200 seconds (12 hours). The helper rejects infinite lifetimes and TTLs outside Box's documented 60-second to 30-day range. Extend deliberately:

```bash
python3 plugins/codexstack/skills/box/scripts/boxctl.py \
  extend "$BOX_ID" --ttl 86400 --yes
```

If the Box-managed Codex login is unavailable but this is a private trusted Box, start native device authentication:

```bash
python3 plugins/codexstack/skills/box/scripts/boxctl.py login "$BOX_ID" --yes
```

Complete the printed link and one-time code in your browser. OpenAI documents auth-file transfer as a fallback for trusted headless setups, but CodexStack Box policy intentionally has no command to copy `~/.codex/auth.json`; that file can contain plaintext access and refresh tokens and Box snapshots persist home-directory state.

## 5. Prompt, watch, and steer

Managed mode is best for many parallel Boxes:

```bash
python3 plugins/codexstack/skills/box/scripts/boxctl.py \
  prompt "$BOX_ID" "Implement the scoped goal; run the matching tests; report evidence."

python3 plugins/codexstack/skills/box/scripts/boxctl.py events "$BOX_ID" --follow
```

To redirect an active managed turn, interrupt explicitly and send a replacement prompt:

```bash
python3 plugins/codexstack/skills/box/scripts/boxctl.py interrupt "$BOX_ID" --yes
python3 plugins/codexstack/skills/box/scripts/boxctl.py prompt "$BOX_ID" "New direction..."
```

For interactive work:

```bash
python3 plugins/codexstack/skills/box/scripts/boxctl.py ssh "$BOX_ID"
codex
# Later: codex resume
```

`box events` only contains runs launched through `box prompt`; it cannot see a separate CLI process started over SSH. Stop preserves disk and ends compute billing after snapshotting:

```bash
python3 plugins/codexstack/skills/box/scripts/boxctl.py stop "$BOX_ID" --yes
python3 plugins/codexstack/skills/box/scripts/boxctl.py resume "$BOX_ID" --yes
```

The helper intentionally omits permanent deletion. Use Box's native destructive command only after reviewing the exact target and accepting that it cannot be recovered. A private working Box can contain injected credentials in its disk snapshots, so keep it private and never promote it to the shared named template.

## Plugins, MCP, and skills

Refresh CodexStack inside a running Box with:

```bash
python3 plugins/codexstack/skills/box/scripts/boxctl.py plugin-sync "$BOX_ID" --yes
```

Start a new Codex session after plugin installation or update. Keep project skills under `.agents/skills/`, personal skills under `~/.agents/skills/`, and reusable capabilities in plugins. A project repository therefore carries its own durable skill layer while the template provides CodexStack.

Codex MCP configuration can live in plugin configuration, user `~/.codex/config.toml`, or trusted project `.codex/config.toml`. Configure secret references, not values:

```toml
[mcp_servers.example]
url = "https://mcp.example.com/mcp"
bearer_token_env_var = "EXAMPLE_MCP_TOKEN"
```

Inspect with `codex mcp list`. OAuth-backed servers use `codex mcp login SERVER` and may require a fresh connection in each new clean Box or after a `--no-env` scrub. Plugin-provided connectors can likewise require reauthorization.

## Desktop and mobile

Signing the Box CLI into the same ChatGPT account does **not** make a standalone Box CLI thread automatically appear in the ChatGPT mobile Codex section. OpenAI's supported Mobile Remote architecture requires the ChatGPT desktop app on macOS or Windows to be online and paired with the phone; pairing cannot begin from the CLI or IDE.

For Box-backed mobile work:

1. Run `box ssh BOX_ID` once so Box creates or refreshes and authorizes its managed key at `~/.ssh/ascii_box_ed25519`.
2. Run `box info BOX_ID` and copy the current Box IP into a concrete alias on the desktop machine:

   ```sshconfig
   Host codexstack-box
     HostName BOX_IP
     User user
     IdentityFile ~/.ssh/ascii_box_ed25519
     IdentitiesOnly yes
   ```

3. Prove the alias works with `ssh codexstack-box`. A resumed Box can have a different IP, so refresh `HostName` from `box info` when needed.
4. In ChatGPT desktop **Settings → Connections → SSH**, add `codexstack-box` and choose the remote repository folder.
5. Start or continue the chat through that desktop remote project, then pair Mobile Remote from the same ChatGPT desktop account and workspace.

The desktop app starts Codex app-server through SSH on the Box. The phone connects to the paired desktop host, not directly to a bare CLI session. OpenAI does not document retroactive discovery or takeover of unrelated standalone CLI threads, so do not rely on it.

For custom tooling only, `codex app-server --listen ws://127.0.0.1:4500` plus `box forward BOX_ID --remote 4500 --local 4500` can create a loopback tunnel. WebSocket app-server transport is experimental; never bind it to a public interface or expose it with `box host`.

## Sources

- ASCII: [Box quickstart](https://docs.ascii.dev/box/quickstart), [CLI reference](https://docs.ascii.dev/box/cli-reference), [environments](https://docs.ascii.dev/box/environments), [snapshots](https://docs.ascii.dev/box/snapshots), [long-running tasks](https://docs.ascii.dev/box/long-running-tasks), [SSH access](https://docs.ascii.dev/box/ssh-access), [machine capabilities](https://docs.ascii.dev/box/machines), [API v1](https://docs.ascii.dev/box/api/v1)
- OpenAI: [Codex authentication](https://developers.openai.com/codex/auth), [pricing](https://developers.openai.com/codex/pricing), [CLI](https://developers.openai.com/codex/cli), [developer commands](https://developers.openai.com/codex/developer-commands), [plugins](https://developers.openai.com/codex/plugins), [skills](https://developers.openai.com/codex/build-skills), [MCP](https://developers.openai.com/codex/mcp), [remote connections](https://developers.openai.com/codex/remote-connections), [app-server](https://developers.openai.com/codex/app-server)
