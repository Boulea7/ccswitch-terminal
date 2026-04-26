<div align="center">

<img src="assets/ccswitch-terminal-banner.webp" alt="ccswitch-terminal banner" width="100%">

# ccswitch-terminal

**把 Claude Code、Codex CLI、Gemini CLI、OpenCode、OpenClaw 放到同一个切换面板里**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml/badge.svg)](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Zero Dependency](https://img.shields.io/badge/zero--dependency-stdlib_only-success.svg)](#快速开始)

简体中文 | [English](README_EN.md) | [日本語](README_JA.md) | [Español](README_ES.md) | [Português](README_PT.md) | [Русский](README_RU.md)

[CI 工作流](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml) | [CodeQL](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/codeql.yml) | [Issue 模板](https://github.com/Boulea7/ccswitch-terminal/issues/new/choose) | [变更日志](CHANGELOG.md) | [发布流程](RELEASING.md) | [贡献指南](CONTRIBUTING.md) | [安全说明](SECURITY.md) | [支持](SUPPORT.md)

</div>

---

## 项目简介

`ccswitch` 是一个只用 Python 标准库实现的本地 CLI。它适合同时使用多个 AI 终端工具、又不想反复手改配置文件的人。

它做三件事：

- 用一个入口切换 Claude Code、Codex CLI、Gemini CLI、OpenCode、OpenClaw。
- 把 provider、alias、profile、历史记录、恢复信息放在同一套本地状态里。
- 遇到 secret 缺失、配置冲突、runtime lease 残留或快照异常时停止操作，避免半成功的配置写入。

这份 README 用 `openrouter -> op` 当主示例。Vertex AI、AWS 托管网关、自建 OpenAI / Anthropic 兼容服务也可以按同样方式配置。

## 功能亮点

| 功能 | 说明 |
|------|------|
| 多工具切换 | Claude Code、Codex CLI、Gemini CLI、OpenCode、OpenClaw 共用一套 provider 管理 |
| 短别名 | `openrouter -> op` 后可以直接用 `ccsw op`、`cxsw op` |
| Profile 队列 | 给不同工具设置不同候选 provider，例如 Codex 先用 `op`，失败时再试 `vx` |
| 官方 Codex 登录态 | 支持把官方 ChatGPT 登录态保存为 `pro`、`pro1` 等本地快照后顺序切换 |
| 临时运行 | `ccsw run ...` 只影响当前命令，不悄悄改掉已保存的 active provider |
| 诊断与恢复 | `doctor`、`history`、`rollback`、`repair` 用于检查和恢复本地状态 |

## 快速开始

> [!IMPORTANT]
> `ccswitch` 管理的是已经安装好的 CLI。Claude Code、Codex CLI、Gemini CLI、OpenCode、OpenClaw 本身需要你先安装好。

### 用 Claude Code 或 Codex 安装

这是最推荐的安装入口。把下面这段提示词复制到 Claude Code 或 Codex，它会安装 `ccswitch`、添加第一个 provider、创建 alias，并做基础验证。

```text
请帮我安装 ccswitch：
https://github.com/Boulea7/ccswitch-terminal

步骤：
1. 克隆到 ~/ccsw
2. 运行 bash ~/ccsw/bootstrap.sh
3. 重新加载 shell：source ~/.zshrc
4. 用 python3 ~/ccsw/ccsw.py -h 验证安装

然后帮我添加一个 provider，要求使用环境变量引用密钥：
- provider 名称：openrouter
- 安装后创建别名：`op -> openrouter`
- Claude URL：<替换成服务商文档里的 Anthropic 兼容地址>
- Claude token 环境变量：OR_CLAUDE_TOKEN
- Codex URL：<替换成服务商文档里的 OpenAI 兼容地址>
- Codex token 环境变量：OR_CODEX_TOKEN
- Gemini key 环境变量：OR_GEMINI_KEY

把真实密钥写入 ~/ccsw/.env.local。
在 ccswitch 配置里只保存 $ENV_VAR 引用。

完成后继续执行：
1. `ccsw alias op openrouter`
2. `ccsw op`
3. `cxsw op`
4. `ccsw show`
5. 最后用简体中文简短说明改了什么
```

常见 provider 命名可以保持简单：

| Provider | Alias |
|----------|-------|
| `openrouter` | `op` |
| `vertex` | `vx` |
| `aws` | `aws` |

### 手动安装

```bash
git clone https://github.com/Boulea7/ccswitch-terminal ~/ccsw
bash ~/ccsw/bootstrap.sh
source ~/.zshrc   # 或 source ~/.bashrc
python3 ~/ccsw/ccsw.py -h
```

想先看安装脚本准备改什么：

```bash
bash ~/ccsw/bootstrap.sh --dry-run
```

<details>
<summary><b>Shell 说明</b></summary>

- `bootstrap.sh` 完成后，`ccsw <provider>` 默认等价于 `ccsw claude <provider>`。
- `cxsw`、`gcsw`、`opsw`、`clawsw` 都是带内置 `eval` 的快捷封装。
- `gcsw op` 这类命令只影响当前 shell session。
- 如果使用 `fish`、PowerShell 或 nushell，优先调用 `python3 ccsw.py ...`，再把导出的环境变量按对应 shell 语法处理。

</details>

## 配置第一个 Provider

1. 把真实密钥写进 `~/ccsw/.env.local`。

```bash
OR_CLAUDE_TOKEN=<your-claude-token>
OR_CODEX_TOKEN=<your-codex-token>
OR_GEMINI_KEY=<your-gemini-key>
```

2. 添加 provider。`ccswitch` 中只保存 `$ENV_VAR` 引用。

```bash
ccsw add openrouter \
  --claude-url '<替换成你的 Anthropic 兼容地址>' \
  --claude-token '$OR_CLAUDE_TOKEN' \
  --codex-url '<替换成你的 OpenAI 兼容地址>' \
  --codex-token '$OR_CODEX_TOKEN' \
  --gemini-key '$OR_GEMINI_KEY'
```

3. 创建 alias 并切换。

```bash
ccsw alias op openrouter
ccsw op
cxsw op
gcsw op
ccsw all op
ccsw show
```

> [!NOTE]
> `.env.local` 仍然是明文文件。它应该只留在本地，并保持未追踪、已被 git 忽略。新版本默认拒绝新的明文 secret 持久化，除非显式传 `--allow-literal-secrets`。

## 常用命令

```bash
# 切换
ccsw op                         # Claude Code
cxsw op                         # Codex CLI
gcsw op                         # Gemini CLI
opsw op                         # OpenCode
clawsw op                       # OpenClaw
ccsw all op                     # 一次切全部

# Provider 和 alias
ccsw list
ccsw show
ccsw add <provider>
ccsw remove <provider>
ccsw alias <alias> <provider>

# Profile 队列
ccsw profile add work --codex op,vx --opencode op
ccsw profile show work
ccsw profile use work

# 诊断和恢复
ccsw doctor all
ccsw doctor codex op --deep
ccsw history --limit 20
ccsw rollback codex
ccsw repair codex
ccsw import current codex rescued-codex

# 当前命令临时使用 profile 候选 provider
ccsw run codex work -- codex exec "hello"
```

## Codex 官方登录与多账号

如果你想给 Codex CLI 保留一个“切回官方 ChatGPT 登录态”的入口，可以添加一个 Codex-only provider：

```bash
ccsw add pro --codex-auth-mode chatgpt
cxsw pro
```

如果要在同一台机器上保留多个官方账号，可以把当前账号保存为 `pro`，再登录并保存第二个账号为 `pro1`：

```bash
ccsw capture codex pro
ccsw login codex pro1
cxsw pro
cxsw pro1
```

`capture` 会保存当前官方登录态；`login` 会运行官方 `codex logout` / `codex login`，再保存新账号。离开当前官方账号前，`ccswitch` 会刷新它自己的快照，以降低 refresh token 轮换后快照变旧的概率。

```bash
# 默认关闭，只影响后续新开的官方 Codex 会话
cxsw sync on
cxsw pro
cxsw sync status
cxsw sync off

# 只保存共享会话的下一步建议，不自动切 provider 或 fork
cxsw share prepare work pro --from last
cxsw share status work
cxsw share clear work
```

<details>
<summary><b>Codex 官方登录态的边界</b></summary>

- `--codex-auth-mode chatgpt` 会把 Codex 切回内置 `openai` provider，并清掉 `OPENAI_BASE_URL` / `OPENAI_API_KEY` 这类会和官方登录态冲突的覆盖项。
- 多账号快照只适合这台机器上的顺序切换，不适合手动复制 `~/.codex/auth.json` 做跨机器共享。
- `sync on` 只影响之后再次执行的 `cxsw pro`，不会迁移旧会话。
- `share prepare` 只保存建议命令，例如 `cxsw pro` 和 `codex fork ...`，不会自动进入会话。
- `ccswitch` 只管理 Codex CLI 的登录态和 provider lane。Codex Apps、remote MCP server、OAuth、代理和 WebSocket 连接由 Codex 自己处理；如果看到 `codex_apps`、`openaiDeveloperDocs`、`deepwiki` 之类 MCP 启动失败，优先检查 Codex 版本、网络代理和 MCP 授权。

</details>

## 进阶功能

<details>
<summary><b>Profile、doctor、run</b></summary>

Profile 适合给不同工具设置不同候选 provider：

```bash
ccsw profile add work \
  --claude op \
  --codex op,vx \
  --gemini aws

ccsw profile use work
```

`doctor` 用来检查配置、路径和 probe 状态：

```bash
ccsw doctor all
ccsw doctor codex op --deep
ccsw doctor codex op --json
```

`run` 只影响这一条命令。它可以按 profile 队列尝试候选 provider，但不会改掉保存的 active provider：

```bash
ccsw run codex work -- codex exec "hello"
```

</details>

<details>
<summary><b>import、rollback、repair</b></summary>

- `import current`：把当前 live config 保存进 provider store。
- `rollback`：当 live 状态仍和历史记录一致时，回到上一个 provider。
- `repair`：处理被中断的 `run` 留下的 stale runtime lease。

```bash
ccsw import current claude rescued-claude
ccsw import current codex pro
ccsw rollback codex
ccsw repair all
```

</details>

<details>
<summary><b>配置目录覆盖</b></summary>

如果某个 CLI 的配置目录不在默认 home 位置，可以用 `settings` 指过去：

```bash
ccsw settings get
ccsw settings set codex_config_dir ~/.codex-alt
ccsw settings set openclaw_config_dir ~/.openclaw-alt
```

WSL 下优先使用 `/mnt/c/...` 这类 POSIX 路径。

</details>

<details>
<summary><b>Codex 0.116+ 配置说明</b></summary>

对 Codex，`ccswitch` 写的是自定义 `model_provider`，不再只依赖老的根级 `openai_base_url`。

```toml
model_provider = "ccswitch_active"

[model_providers.ccswitch_active]
name = "ccswitch: openrouter"
base_url = "https://api.example.com/openai/v1"
env_key = "OPENAI_API_KEY"
supports_websockets = false
wire_api = "responses"
```

这对“支持 HTTP Responses、但不支持 Responses WebSocket”的 OpenAI 兼容中转尤其重要。

</details>

<details>
<summary><b>ccswitch 会写哪些文件</b></summary>

| 工具 | 主要写入位置 |
|------|--------------|
| Claude Code | `~/.claude/settings.json` |
| Codex CLI | `~/.codex/auth.json` 和 `~/.codex/config.toml` |
| Gemini CLI | `~/.gemini/settings.json` 和 `~/.ccswitch/active.env` |
| OpenCode | `~/.ccswitch/generated/opencode/` 下的 overlay |
| OpenClaw | `~/.ccswitch/generated/openclaw/` 下的 overlay |

主状态存放在 `~/.ccswitch/ccswitch.db`，`~/.ccswitch/providers.json` 继续保留作兼容快照。

</details>

## FAQ

<details>
<summary><b>为什么 <code>ccsw op</code> 能用，但 <code>python3 ccsw.py op</code> 不行？</b></summary>

`ccsw op` 是 `bootstrap.sh` 装进去的 shell wrapper，它在省略工具名时默认补成 `claude`。Python CLI 本体仍然需要显式子命令，比如 `claude`、`codex`、`all`。

</details>

<details>
<summary><b>是不是建议每个 provider 都配 alias？</b></summary>

建议。频繁切换时，`ccsw op`、`cxsw op`、`ccsw all vx` 这类短命令更好输入，也更适合写进 profile。

</details>

<details>
<summary><b><code>[claude] Skipped: token unresolved</code> 是什么意思？</b></summary>

说明这个 provider 指向了某个环境变量，例如 `$OR_CLAUDE_TOKEN`，但当前环境里没有它。把它写进 `.env.local`，或者在当前 shell 里手动 `export`。

</details>

<details>
<summary><b>除了 OpenRouter，还能不能配 Vertex AI、AWS，或者自己的中转？</b></summary>

可以。`openrouter` 只是这份 README 的主示例。把 URL 和凭据替换成服务商文档里的实际值，再给它起一个顺手的别名，比如 `vx` 或 `aws`。

</details>

## 更多文档

- 发布说明：[CHANGELOG.md](CHANGELOG.md)
- 发布流程：[RELEASING.md](RELEASING.md)
- 贡献指南：[CONTRIBUTING.md](CONTRIBUTING.md)
- 安全说明：[SECURITY.md](SECURITY.md)
- 支持入口：[SUPPORT.md](SUPPORT.md)
- 社区规则：[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

## 开发与验证

```bash
bash bootstrap.sh --dry-run
python3 ccsw.py -h
python3 -m unittest discover -s tests -q
```

如果只是文档改动，至少重新检查公开文档、示例命令和交叉链接。

## 依赖

需要 Python 3.9+。项目本身不依赖第三方包，也不需要额外 `pip install`。

## License

MIT

<div align="right">

[返回顶部](#ccswitch-terminal)

</div>
