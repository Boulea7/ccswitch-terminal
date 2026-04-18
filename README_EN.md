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

## What It Does

`ccswitch` is a stdlib-only Python CLI for people who use more than one AI terminal tool and do not want to hand-edit five different config formats every time they switch providers.

- Switch Claude Code, Codex CLI, Gemini CLI, OpenCode, and OpenClaw from one place.
- Keep long provider names readable with aliases such as `openrouter -> op`, then use `ccsw op` or `cxsw op`. This README treats aliases as the default day-to-day workflow.
- Write live config for Claude / Codex / Gemini and managed overlays for OpenCode / OpenClaw.
- Ship practical operator commands such as `profile`, `doctor`, `run`, `history`, `rollback`, `repair`, and `import current`.
- Fail closed when config, secrets, snapshot sync, or runtime leases are not safe enough to continue.

`openrouter` is the main example in this README. The same workflow also works for providers such as Vertex AI, AWS-hosted gateways, or your own compatible relay. Replace URLs and credentials with the values from your provider's docs.

---

## Quick Start

> [!IMPORTANT]
> `ccswitch` manages CLIs that are already installed. It does not install Claude Code, Codex CLI, Gemini CLI, OpenCode, or OpenClaw for you.

### Install with Claude Code or Codex

Copy this prompt into Claude Code or Codex. It installs `ccswitch`, adds your first provider, creates an alias, and verifies the result.

```text
Please install ccswitch from:
https://github.com/Boulea7/ccswitch-terminal

Steps:
1. Clone it to ~/ccsw
2. Run bash ~/ccsw/bootstrap.sh
3. Reload my shell with source ~/.zshrc
4. Verify with python3 ~/ccsw/ccsw.py -h

Then add one provider for me with env-based secrets:
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

If you want other examples, keep the same workflow and just swap the provider name:

- `vertex` with alias `vx`
- `aws` with alias `aws`

Example follow-up commands after the first install:

```bash
ccsw alias vx vertex
ccsw alias aws aws
ccsw vx
cxsw aws
```

### Manual Install

```bash
git clone https://github.com/Boulea7/ccswitch-terminal ~/ccsw
bash ~/ccsw/bootstrap.sh
source ~/.zshrc   # or source ~/.bashrc
python3 ~/ccsw/ccsw.py -h
```

If you want to preview the shell changes first:

```bash
bash ~/ccsw/bootstrap.sh --dry-run
```

<details>
<summary><b>Shell notes</b></summary>

- After `bootstrap.sh`, `ccsw <provider>` defaults to `claude`, so `ccsw op` means `ccsw claude op`.
- `cxsw`, `gcsw`, `opsw`, and `clawsw` are convenience wrappers with built-in `eval`.
- In `fish`, PowerShell, or other non-POSIX shells, prefer `python3 ccsw.py ...` and translate exported env vars into your shell syntax instead of sourcing `~/.ccswitch/*.env` directly.

</details>

---

## First Provider in 60 Seconds

If you prefer adding the first provider yourself, use this flow.

1. Put secrets in `~/ccsw/.env.local`.

```bash
OR_CLAUDE_TOKEN=<your-claude-token>
OR_CODEX_TOKEN=<your-codex-token>
OR_GEMINI_KEY=<your-gemini-key>
```

2. Add the provider.

```bash
ccsw add openrouter \
  --claude-url '<replace-with-your-anthropic-url>' \
  --claude-token '$OR_CLAUDE_TOKEN' \
  --codex-url '<replace-with-your-openai-url>' \
  --codex-token '$OR_CODEX_TOKEN' \
  --gemini-key '$OR_GEMINI_KEY'
```

3. You can switch with the full provider name directly, or create a short alias if you prefer.

```bash
ccsw openrouter
cxsw openrouter

ccsw alias op openrouter
ccsw op
cxsw op
gcsw op
ccsw all op
ccsw show
```

4. Repeat the same pattern for other providers if you want shorter names.

```bash
ccsw alias vx vertex
ccsw alias aws aws
```

### Alias (Short Name) Habit

If you plan to use `ccswitch` regularly, treat aliases (short names) as the normal way to work instead of an occasional shortcut.

Recommended shorthand can stay short, stable, and easy to remember:

| Provider | Suggested alias (short name) | Why |
|----------|------------------|-----|
| `openrouter` | `op` | primary example in this README |
| `vertex` | `vx` | shorter than `vertex`, keeps the same style as `op` |
| `aws` | `aws` | already short enough |

```bash
ccsw alias op openrouter
ccsw alias vx vertex
ccsw alias aws aws
```

Then keep using the short names everywhere:

```bash
ccsw op
cxsw op
ccsw all vx
ccsw profile add work --codex op,vx --opencode op
ccsw profile add cloud --claude aws --codex aws,op
```

You do not have to create aliases, though. `ccsw openrouter` and `cxsw openrouter` still work.

---

## Core Commands

```bash
# Switch: aliases are recommended, but full provider names still work
ccsw op                         # Claude Code, after bootstrap
cxsw op                         # Codex CLI
gcsw op                         # Gemini CLI
opsw op                         # OpenCode
clawsw op                       # OpenClaw
ccsw all op                     # all configured tools
ccsw openrouter                 # full-name form
cxsw openrouter                 # full-name form

# Manage providers
ccsw list
ccsw show
ccsw add <provider>
ccsw remove <provider>
ccsw alias <alias> <provider>

# Reusable queues
ccsw profile add work --codex op,vx --opencode op
ccsw profile add cloud --claude aws --codex aws,op
ccsw profile show work
ccsw profile use work

# Diagnostics and recovery
ccsw doctor all
ccsw history --limit 20
ccsw rollback codex
ccsw repair codex
ccsw import current codex rescued-codex
ccsw run codex work -- codex exec "hello"
```

> [!NOTE]
> `gcsw op` affects the current shell session. If you call `python3 ccsw.py gemini ...` or `python3 ccsw.py codex ...` directly, use `eval "$(python3 ccsw.py ...)"`.

---

## More Features

<details>
<summary><b>Secrets: use <code>.env.local</code> by default</b></summary>

Keep real tokens in `~/ccsw/.env.local` and store only `$ENV_VAR` references inside `ccswitch`.

```bash
# ~/ccsw/.env.local
OR_CLAUDE_TOKEN=<your-claude-token>
OR_CODEX_TOKEN=<your-codex-token>
OR_GEMINI_KEY=<your-gemini-key>
```

- `ccswitch` loads `.env.local` when it runs.
- Existing exported env vars still win.
- `.env.local` is still plaintext. Keep it local, untracked, and ignored by git.
- Successful switching still writes resolved secrets into the target tool config or activation files.
- New literal secrets are rejected by default unless you explicitly use `--allow-literal-secrets`.

</details>

<details>
<summary><b>Profiles, doctor, and run</b></summary>

Use profiles when different tools should prefer different providers.

```bash
ccsw profile add work \
  --claude op \
  --codex op,vx \
  --gemini aws

ccsw profile use work
```

`doctor` checks configuration, path resolution, and probe health:

```bash
ccsw doctor all
ccsw doctor codex op --deep
ccsw doctor codex op --json
```

`run` is for one command only. It can try the next candidate in a profile queue without silently changing your stored active provider:

```bash
ccsw run codex work -- codex exec "hello"
```

</details>

<details>
<summary><b>Import, rollback, and repair</b></summary>

- `import current` pulls live config back into the provider store.
- `rollback` restores the previous provider when the current live state still matches the recorded switch history.
- `repair` handles stale runtime lease state left by interrupted `run` executions.

```bash
ccsw import current claude rescued-claude
ccsw rollback codex
ccsw repair all
```

</details>

<details>
<summary><b>Config directory overrides</b></summary>

Use `settings` when a managed CLI stores its config somewhere other than the default home location.

```bash
ccsw settings get
ccsw settings set codex_config_dir ~/.codex-alt
ccsw settings set openclaw_config_dir ~/.openclaw-alt
```

For WSL, prefer POSIX paths such as `/mnt/c/...`.

</details>

<details>
<summary><b>Codex 0.116+ note</b></summary>

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

---

## FAQ

<details>
<summary><b>Why does <code>ccsw op</code> work, but not <code>python3 ccsw.py op</code>?</b></summary>

`ccsw op` is a shell wrapper installed by `bootstrap.sh`. It defaults to `claude` when you omit the tool name. The Python CLI itself still expects an explicit subcommand such as `claude`, `codex`, or `all`.

</details>

<details>
<summary><b>Should I create an alias (short name) for every provider?</b></summary>

Usually yes. If you switch often, aliases (short names) make commands such as `ccsw op`, `cxsw op`, and `ccsw all vx` much easier to type and easier to reuse in profiles.

A simple convention is:

- `op = openrouter`
- `vx = vertex`
- `aws = aws`

</details>

<details>
<summary><b>Why is <code>$GEMINI_API_KEY</code> still empty after <code>gcsw op</code>?</b></summary>

Check these first:

1. `command -v gcsw`
2. Are you still in the same shell session?
3. If you bypassed the wrapper and called `python3 ccsw.py gemini ...`, did you use `eval "$(python3 ccsw.py gemini ...)"`?

</details>

<details>
<summary><b>What does <code>[claude] Skipped: token unresolved</code> mean?</b></summary>

The provider points at an env var such as `$OR_CLAUDE_TOKEN`, but that env var is not available right now. Put it in `.env.local` or export it in the current shell.

</details>

<details>
<summary><b>Can I use Vertex AI, AWS, or my own relay instead of OpenRouter?</b></summary>

Yes. `openrouter` is only the main example in this README. Replace the URLs and credentials with the values from your provider's documentation, then create an alias you actually want to type, for example `vx` or `aws`.

</details>

---

## More Docs

- Full release notes: [CHANGELOG.md](CHANGELOG.md)
- Release workflow: [RELEASING.md](RELEASING.md)
- Contribution guide: [CONTRIBUTING.md](CONTRIBUTING.md)
- Security policy: [SECURITY.md](SECURITY.md)
- Support guide: [SUPPORT.md](SUPPORT.md)
- Community rules: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

---

## Develop & Verify

For code changes, the minimum verification set is:

```bash
bash bootstrap.sh --dry-run
python3 ccsw.py -h
python3 -m unittest discover -s tests -q
```

For docs-only changes, at least re-check the public docs surface, example commands, and cross-links before opening a PR.

---

## Requirements

You only need Python 3.9+. The project has no third-party package dependency, so there is nothing extra to `pip install`.

## License

MIT

---

<div align="right">

[Back to top](#ccswitch-terminal)

</div>
