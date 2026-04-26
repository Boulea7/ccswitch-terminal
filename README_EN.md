<div align="center">

<img src="assets/ccswitch-terminal-banner.webp" alt="ccswitch-terminal banner" width="100%">

# ccswitch-terminal

**One switchboard for Claude Code, Codex CLI, Gemini CLI, OpenCode, and OpenClaw**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml/badge.svg)](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Zero Dependency](https://img.shields.io/badge/zero--dependency-stdlib_only-success.svg)](#quick-start)

[简体中文](README.md) | English | [日本語](README_JA.md) | [Español](README_ES.md) | [Português](README_PT.md) | [Русский](README_RU.md)

[CI](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml) | [CodeQL](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/codeql.yml) | [Issue Templates](https://github.com/Boulea7/ccswitch-terminal/issues/new/choose) | [Changelog](CHANGELOG.md) | [Releasing](RELEASING.md) | [Contributing](CONTRIBUTING.md) | [Security](SECURITY.md) | [Support](SUPPORT.md)

</div>

---

## Overview

`ccswitch` is a local, stdlib-only Python CLI for people who use several AI terminal tools and do not want to hand-edit config files whenever they change providers.

It does three things:

- Switch Claude Code, Codex CLI, Gemini CLI, OpenCode, and OpenClaw from one place.
- Keep providers, aliases, profiles, history, and recovery metadata in one local state store.
- Stop when secrets, config, runtime leases, or snapshots are not safe enough to continue.

This README uses `openrouter -> op` as the main example. Vertex AI, AWS-hosted gateways, and your own OpenAI / Anthropic-compatible services follow the same pattern.

## Highlights

| Feature | What it gives you |
|---------|-------------------|
| Multi-tool switching | One provider store for Claude Code, Codex CLI, Gemini CLI, OpenCode, and OpenClaw |
| Short aliases | Create `openrouter -> op`, then use `ccsw op` and `cxsw op` |
| Profile queues | Give each tool its own provider order, for example Codex tries `op` before `vx` |
| Official Codex login | Save ChatGPT-backed Codex logins as local snapshots such as `pro` and `pro1` |
| One-command runs | `ccsw run ...` affects only that command and does not rewrite the stored active provider |
| Recovery tools | `doctor`, `history`, `rollback`, and `repair` help inspect and recover local state |

## Quick Start

> [!IMPORTANT]
> `ccswitch` manages CLIs that are already installed. It does not install Claude Code, Codex CLI, Gemini CLI, OpenCode, or OpenClaw for you.

### Install with Claude Code or Codex

This is the recommended install path. Copy the prompt below into Claude Code or Codex. It installs `ccswitch`, adds your first provider, creates an alias, and verifies the result.

```text
Please install ccswitch from:
https://github.com/Boulea7/ccswitch-terminal

Steps:
1. Clone it to ~/ccsw
2. Run bash ~/ccsw/bootstrap.sh
3. Reload my shell with source ~/.zshrc
4. Verify with python3 ~/ccsw/ccsw.py -h

Then add one provider with env-based secrets:
- provider name: openrouter
- create this alias after setup: `op -> openrouter`
- Claude URL: <replace with the Anthropic-compatible URL from my provider docs>
- Claude token env var: OR_CLAUDE_TOKEN
- Codex URL: <replace with the OpenAI-compatible URL from my provider docs>
- Codex token env var: OR_CODEX_TOKEN
- Gemini key env var: OR_GEMINI_KEY

Write the real secret values into ~/ccsw/.env.local.
Store only $ENV_VAR references in ccswitch.

After that:
1. run `ccsw alias op openrouter`
2. run `ccsw op`
3. run `cxsw op`
4. run `ccsw show`
5. explain briefly in English what changed
```

Common provider names can stay simple:

| Provider | Alias |
|----------|-------|
| `openrouter` | `op` |
| `vertex` | `vx` |
| `aws` | `aws` |

### Manual Install

```bash
git clone https://github.com/Boulea7/ccswitch-terminal ~/ccsw
bash ~/ccsw/bootstrap.sh
source ~/.zshrc   # or source ~/.bashrc
python3 ~/ccsw/ccsw.py -h
```

Preview the shell changes first:

```bash
bash ~/ccsw/bootstrap.sh --dry-run
```

<details>
<summary><b>Shell notes</b></summary>

- After `bootstrap.sh`, `ccsw <provider>` defaults to `ccsw claude <provider>`.
- `cxsw`, `gcsw`, `opsw`, and `clawsw` are convenience wrappers with built-in `eval`.
- Commands such as `gcsw op` affect only the current shell session.
- In `fish`, PowerShell, or nushell, prefer `python3 ccsw.py ...` and translate exported env vars into that shell's syntax.

</details>

## Configure Your First Provider

1. Put real secrets in `~/ccsw/.env.local`.

```bash
OR_CLAUDE_TOKEN=<your-claude-token>
OR_CODEX_TOKEN=<your-codex-token>
OR_GEMINI_KEY=<your-gemini-key>
```

2. Add the provider. `ccswitch` stores only `$ENV_VAR` references.

```bash
ccsw add openrouter \
  --claude-url '<replace-with-your-anthropic-url>' \
  --claude-token '$OR_CLAUDE_TOKEN' \
  --codex-url '<replace-with-your-openai-url>' \
  --codex-token '$OR_CODEX_TOKEN' \
  --gemini-key '$OR_GEMINI_KEY'
```

3. Create an alias and switch.

```bash
ccsw alias op openrouter
ccsw op
cxsw op
gcsw op
ccsw all op
ccsw show
```

> [!NOTE]
> `.env.local` is still plaintext. Keep it local, untracked, and ignored by git. New literal secrets are rejected by default unless you explicitly pass `--allow-literal-secrets`.

## Core Commands

```bash
# Switching
ccsw op                         # Claude Code
cxsw op                         # Codex CLI
gcsw op                         # Gemini CLI
opsw op                         # OpenCode
clawsw op                       # OpenClaw
ccsw all op                     # all configured tools

# Providers and aliases
ccsw list
ccsw show
ccsw add <provider>
ccsw remove <provider>
ccsw alias <alias> <provider>

# Profile queues
ccsw profile add work --codex op,vx --opencode op
ccsw profile show work
ccsw profile use work

# Diagnostics and recovery
ccsw doctor all
ccsw doctor codex op --deep
ccsw history --limit 20
ccsw rollback codex
ccsw repair codex
ccsw import current codex rescued-codex

# Temporarily use profile candidates for one command
ccsw run codex work -- codex exec "hello"
```

## Official Codex Login And Multiple Accounts

If you want a Codex-only provider that switches back to the official ChatGPT login, add one dedicated provider:

```bash
ccsw add pro --codex-auth-mode chatgpt
cxsw pro
```

To keep multiple official accounts on the same machine, capture the current account as `pro`, then log in and save the second account as `pro1`:

```bash
ccsw capture codex pro
ccsw login codex pro1
cxsw pro
cxsw pro1
```

`capture` saves the current official login. `login` runs the official `codex logout` / `codex login` flow and then saves the new account. Before switching away from the current official account, `ccswitch` refreshes its own snapshot so rotating refresh tokens are less likely to go stale.

```bash
# Off by default; affects only future official Codex sessions
cxsw sync on
cxsw pro
cxsw sync status
cxsw sync off

# Save suggested share-session commands without switching or forking
cxsw share prepare work pro --from last
cxsw share status work
cxsw share clear work
```

<details>
<summary><b>Codex official-login boundaries</b></summary>

- `--codex-auth-mode chatgpt` switches Codex back to the built-in `openai` provider and clears `OPENAI_BASE_URL` / `OPENAI_API_KEY` overrides that would conflict with the official login.
- Multi-account snapshots are meant for sequential switching on this machine only. They are not a recommendation to copy `~/.codex/auth.json` between machines.
- `sync on` only changes what happens the next time you run `cxsw pro`; it does not migrate older sessions.
- `share prepare` only stores suggested commands such as `cxsw pro` and `codex fork ...`; it does not enter a session automatically.
- `ccswitch` manages the Codex CLI login state and provider lane only. Codex Apps, remote MCP servers, OAuth, proxy routing, and WebSocket transport are still owned by Codex itself. If `codex_apps`, `openaiDeveloperDocs`, or `deepwiki` fails during MCP startup, check the Codex version, proxy path, and MCP authorization first.

</details>

## Advanced Usage

<details>
<summary><b>Profiles, doctor, and run</b></summary>

Use profiles when different tools should prefer different providers:

```bash
ccsw profile add work \
  --claude op \
  --codex op,vx \
  --gemini aws

ccsw profile use work
```

`doctor` checks configuration, paths, and probe health:

```bash
ccsw doctor all
ccsw doctor codex op --deep
ccsw doctor codex op --json
```

`run` is for one command only. It can try profile candidates without changing your stored active provider:

```bash
ccsw run codex work -- codex exec "hello"
```

</details>

<details>
<summary><b>Import, rollback, and repair</b></summary>

- `import current` saves live config into the provider store.
- `rollback` returns to the previous provider when live state still matches switch history.
- `repair` handles stale runtime leases left by interrupted `run` executions.

```bash
ccsw import current claude rescued-claude
ccsw import current codex pro
ccsw rollback codex
ccsw repair all
```

</details>

<details>
<summary><b>Config directory overrides</b></summary>

Use `settings` when a managed CLI stores config somewhere other than the default home location:

```bash
ccsw settings get
ccsw settings set codex_config_dir ~/.codex-alt
ccsw settings set openclaw_config_dir ~/.openclaw-alt
```

For WSL, prefer POSIX paths such as `/mnt/c/...`.

</details>

<details>
<summary><b>Codex 0.116+ config note</b></summary>

For Codex, `ccswitch` writes a custom `model_provider` block instead of relying only on old root-level `openai_base_url` behavior.

```toml
model_provider = "ccswitch_active"

[model_providers.ccswitch_active]
name = "ccswitch: openrouter"
base_url = "https://api.example.com/openai/v1"
env_key = "OPENAI_API_KEY"
supports_websockets = false
wire_api = "responses"
```

This matters for OpenAI-compatible relays that support HTTP Responses but not the Responses WebSocket transport.

</details>

<details>
<summary><b>What ccswitch writes</b></summary>

| Tool | Main target |
|------|-------------|
| Claude Code | `~/.claude/settings.json` |
| Codex CLI | `~/.codex/auth.json` and `~/.codex/config.toml` |
| Gemini CLI | `~/.gemini/settings.json` plus `~/.ccswitch/active.env` |
| OpenCode | generated overlay under `~/.ccswitch/generated/opencode/` |
| OpenClaw | generated overlay under `~/.ccswitch/generated/openclaw/` |

Primary state lives in `~/.ccswitch/ccswitch.db`, with `~/.ccswitch/providers.json` kept as a compatibility snapshot.

</details>

## FAQ

<details>
<summary><b>Why does <code>ccsw op</code> work, but not <code>python3 ccsw.py op</code>?</b></summary>

`ccsw op` is a shell wrapper installed by `bootstrap.sh`. It defaults to `claude` when you omit the tool name. The Python CLI itself still expects an explicit subcommand such as `claude`, `codex`, or `all`.

</details>

<details>
<summary><b>Should I create aliases for providers?</b></summary>

Usually yes. If you switch often, commands such as `ccsw op`, `cxsw op`, and `ccsw all vx` are easier to type and easier to reuse in profiles.

</details>

<details>
<summary><b>What does <code>[claude] Skipped: token unresolved</code> mean?</b></summary>

The provider points at an env var such as `$OR_CLAUDE_TOKEN`, but that env var is not available right now. Put it in `.env.local` or export it in the current shell.

</details>

<details>
<summary><b>Can I use Vertex AI, AWS, or my own relay instead of OpenRouter?</b></summary>

Yes. `openrouter` is only the main example in this README. Replace URLs and credentials with the values from your provider's documentation, then create an alias you actually want to type, such as `vx` or `aws`.

</details>

## More Docs

- Full release notes: [CHANGELOG.md](CHANGELOG.md)
- Release workflow: [RELEASING.md](RELEASING.md)
- Contribution guide: [CONTRIBUTING.md](CONTRIBUTING.md)
- Security policy: [SECURITY.md](SECURITY.md)
- Support guide: [SUPPORT.md](SUPPORT.md)
- Community rules: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

## Develop & Verify

```bash
bash bootstrap.sh --dry-run
python3 ccsw.py -h
python3 -m unittest discover -s tests -q
```

For docs-only changes, at least re-check public docs, example commands, and cross-links.

## Requirements

You only need Python 3.9+. The project has no third-party package dependency, so there is nothing extra to `pip install`.

## License

MIT

<div align="right">

[Back to top](#ccswitch-terminal)

</div>
