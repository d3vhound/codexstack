---
name: box
description: "Provision and steer private ASCII Boxes for CodexStack with finite lifetimes, ChatGPT subscription auth, GitHub access, and portable Codex plugins, MCP servers, and skills. Use only when the user explicitly invokes Box or asks to run CodexStack in an ASCII Box."
---

# CodexStack Box

Use Box as an optional execution surface, not as a second orchestrator. Keep CodexStack's judgment in Codex and use Box for isolated compute, persistence, and remote steering.

Before any Box environment, template or snapshot, authentication, credential, remote-access, or lifecycle action, including create, launch, resume, stop, interrupt, prompt, or forward, read [security.md](references/security.md). Do not infer permission to create, resume, interrupt, stop, or reconfigure a Box from an unrelated coding request.

Resolve `BOX_SKILL` to the absolute directory containing this loaded `SKILL.md`. Every bundled helper below is relative to that directory. Never assume the user's repository contains a `plugins/codexstack` checkout.

If the user asks to see, review, approve, or revise a Box plan before any Box action, treat the entire request as plan-only. Do not create or change an environment, credentials, template or snapshot, Box lifecycle, remote access, or paid compute until the user explicitly authorizes the named action.

## Establish the two layers

1. Install and sign in to Box with `box onboard`.
2. In the Box dashboard, connect GitHub and connect **Agents → Codex → ChatGPT** with the user's ChatGPT account. This lets a private environment inject managed GitHub and Codex credentials without putting tokens in this repository.
3. Create a private environment with GitHub and Agents credentials on, Secrets and Box credentials off:

   ```bash
   python3 "$BOX_SKILL/scripts/boxctl.py" env-init \
     --repo OWNER/REPO --yes
   ```

4. Build a reusable credential-free template. The helper starts its source Box with `--no-env`, installs the public CodexStack marketplace, proves common managed credential files are absent, snapshots it, and requests a stop. Because Box archives asynchronously, confirm `archived` with `box info` before treating compute as stopped:

   ```bash
   python3 "$BOX_SKILL/scripts/boxctl.py" template-build --yes
   ```

5. Launch from the clean template and inject the private environment only at boot. The default TTL is 12 hours and is always finite:

   ```bash
   python3 "$BOX_SKILL/scripts/boxctl.py" launch --yes
   ```

Use [profile.example.json](assets/profile.example.json) with `--profile PATH` to change names, repositories, marketplace source, or TTLs. Profiles must never contain secrets.

## Authenticate Codex

Prefer the Box dashboard's native ChatGPT connection for managed `box prompt` runs. ChatGPT plan-backed Codex access, including Pro, is different from API-key billing.

For a direct interactive CLI login inside one trusted Box, use:

```bash
python3 "$BOX_SKILL/scripts/boxctl.py" login BOX_ID --yes
```

This runs `codex login --device-auth` in the Box. The user completes the one-time code in their own browser. CodexStack Box policy never copies, prints, commits, prompts with, or bakes `~/.codex/auth.json` into a reusable template. Automatic and stop snapshots of a private working Box may contain it, so keep those snapshots owner-only and never share them. A manual CLI login may not configure Box's managed `box prompt` provider; connect the Box Agents integration separately when managed prompting is required.

## Operate and steer

| Intent | Command |
| --- | --- |
| Send work | `boxctl.py prompt BOX_ID "GOAL and acceptance criteria"` |
| Watch checkpoints | `boxctl.py events BOX_ID --follow` |
| Change a running turn | `boxctl.py interrupt BOX_ID --yes`, then send a new prompt |
| Work interactively | `boxctl.py ssh BOX_ID`, then `codex` or `codex resume` |
| Forward a private port | `boxctl.py forward BOX_ID REMOTE_PORT` |
| Pause and preserve disk | `boxctl.py stop BOX_ID --yes` |
| Resume with a finite TTL | `boxctl.py resume BOX_ID --yes` |
| Inspect readiness | `python3 "$BOX_SKILL/scripts/doctor.py" --box BOX_ID` |

`box events` reports work launched through `box prompt`; it does not observe a separate Codex process started over SSH. Processes started by hand do not survive stop/resume. Use a systemd service only when the user explicitly needs a durable non-agent process.

For multiple explicitly authorized runs, prefer CodexStack's thin control service. It limits concurrent Box workers, exposes managed prompt events to the web UI and MCP, and verifies handoff state without becoming another scheduler. Mint desktop or preview access only when the operator clicks. Never return raw signed access URLs to a model or persist them.

## Keep Codex extensions portable

- Install CodexStack through its marketplace, not by copying a local Codex home directory. Run `boxctl.py plugin-sync BOX_ID --yes` after a marketplace update.
- Keep project skills in `.agents/skills/`, personal skills in `~/.agents/skills/`, or distribute them in plugins. The template carries the public plugin; repositories carry project-local skills.
- Keep MCP declarations in plugin configuration, trusted project `.codex/config.toml`, or a reconstructable setup step. Reference secret environment-variable names (`env_vars` or `bearer_token_env_var`), never literal tokens.
- Expect OAuth-backed MCP servers and plugin connectors to require a new login in a new Box or after credentials are scrubbed. Use `codex mcp login SERVER` inside the Box.
- GitHub access comes from the private Box environment. Verify with `gh auth status`; do not copy `hosts.yml` or personal access tokens.

## Mobile boundary

A standalone Codex CLI session in a Box does **not** automatically appear in the ChatGPT mobile Codex view merely because it uses the same ChatGPT account. Mobile Remote starts from a paired ChatGPT desktop app on macOS or Windows, not from the CLI. To use a Box from mobile, first add the Box as an SSH host in the desktop app and start or continue the remote-project chat through that paired desktop host. Do not promise discovery or takeover of an unrelated bare CLI thread.
