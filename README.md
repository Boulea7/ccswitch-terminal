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

## 它是做什么的

`ccswitch` 是一个只用 Python 标准库实现的 CLI，适合同时使用多个 AI 终端工具、又不想每次都手改五套配置的人。

- 用一个入口切换 Claude Code、Codex CLI、Gemini CLI、OpenCode、OpenClaw。
- 给很长的 provider 名起短别名，比如 `openrouter -> op`，后面直接用 `ccsw op`、`cxsw op`。这也是这份 README 默认推荐的用法。
- 对 Claude / Codex / Gemini 直接写 live config，对 OpenCode / OpenClaw 生成受管 overlay。
- 自带 `profile`、`doctor`、`run`、`history`、`rollback`、`repair`、`import current` 这些实用命令。
- 遇到配置不一致、secret 解析失败、快照同步异常、runtime lease 残留时，默认直接停下，不做半成功切换。

这份 README 主要用 `openrouter` 当例子，因为很多人一眼能看懂。你也可以照样配置 Vertex AI、AWS 托管网关，或者你自己的兼容中转。把 URL 和凭据替换成服务商文档里的实际值就可以。

---

## 快速开始

> [!IMPORTANT]
> `ccswitch` 只负责管理已经装好的 CLI，不会替你安装 Claude Code、Codex CLI、Gemini CLI、OpenCode、OpenClaw。

### 用 Claude Code 或 Codex 一键安装

下面这段提示词不要折叠，直接复制到 Claude Code 或 Codex 里就能用。它会安装 `ccswitch`、添加第一个 provider、创建别名，并做基础验证。

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
- 安装后顺手创建一个别名：`op -> openrouter`
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
5. 用简短中文说明改了什么
```

如果你想换成别的例子，流程完全一样，只需要换 provider 名和别名：

- `vertex` 配 `vx`
- `aws` 配 `aws`

安装好后的常见命令可以是：

```bash
ccsw alias vx vertex
ccsw alias aws aws
ccsw vx
cxsw aws
```

### 手动安装

```bash
git clone https://github.com/Boulea7/ccswitch-terminal ~/ccsw
bash ~/ccsw/bootstrap.sh
source ~/.zshrc   # 或 source ~/.bashrc
python3 ~/ccsw/ccsw.py -h
```

如果你想先看它准备改什么：

```bash
bash ~/ccsw/bootstrap.sh --dry-run
```

<details>
<summary><b>Shell 说明</b></summary>

- `bootstrap.sh` 跑完之后，`ccsw <provider>` 默认就是 `ccsw claude <provider>`，所以 `ccsw op` 会切 Claude Code。
- `cxsw`、`gcsw`、`opsw`、`clawsw` 都是带内置 `eval` 的快捷封装。
- 如果你用的是 `fish`、PowerShell 之类的非 POSIX shell，优先用 `python3 ccsw.py ...`，再把导出的环境变量按对应 shell 的语法处理，不要直接 `source ~/.ccswitch/*.env`。

</details>

---

## 60 秒配好第一个 Provider

如果你想自己配第一条 provider，这条路径最短。

1. 先把密钥写进 `~/ccsw/.env.local`。

```bash
OR_CLAUDE_TOKEN=<your-claude-token>
OR_CODEX_TOKEN=<your-codex-token>
OR_GEMINI_KEY=<your-gemini-key>
```

2. 添加 provider。

```bash
ccsw add openrouter \
  --claude-url '<替换成你的 Anthropic 兼容地址>' \
  --claude-token '$OR_CLAUDE_TOKEN' \
  --codex-url '<替换成你的 OpenAI 兼容地址>' \
  --codex-token '$OR_CODEX_TOKEN' \
  --gemini-key '$OR_GEMINI_KEY'
```

3. 你可以直接用 provider 全名切换，也可以给它起一个短别名。

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

4. 其他 provider 也照这个模式来。

```bash
ccsw alias vx vertex
ccsw alias aws aws
```

### 别名约定

如果你准备长期用 `ccswitch`，建议把 alias 当成默认习惯，而不是偶尔才用的快捷方式。

```bash
ccsw alias op openrouter
ccsw alias vx vertex
ccsw alias aws aws
```

后面你在命令行里优先输入短名：

```bash
ccsw op
cxsw op
ccsw all vx
ccsw profile add work --codex op,vx --opencode op
```

当然，不建 alias 也能正常用，直接写 `ccsw openrouter`、`cxsw openrouter` 一样可以。

---

## 常用命令

```bash
# 切换：推荐短别名；不建 alias 时也可以直接写 provider 全名
ccsw op                         # Claude Code，前提是已经 bootstrap
cxsw op                         # Codex CLI
gcsw op                         # Gemini CLI
opsw op                         # OpenCode
clawsw op                       # OpenClaw
ccsw all op                     # 一次切全部
ccsw openrouter                 # 不使用 alias 的写法
cxsw openrouter                 # 不使用 alias 的写法

# 管理 provider
ccsw list
ccsw show
ccsw add <provider>
ccsw remove <provider>
ccsw alias <alias> <provider>

# 复用队列
ccsw profile add work --codex op,vx --opencode op
ccsw profile show work
ccsw profile use work

# 诊断和恢复
ccsw doctor all
ccsw history --limit 20
ccsw rollback codex
ccsw repair codex
ccsw import current codex rescued-codex
ccsw run codex work -- codex exec "hello"
```

> [!NOTE]
> `gcsw op` 只会影响当前 shell session。如果你直接调用 `python3 ccsw.py gemini ...` 或 `python3 ccsw.py codex ...`，记得用 `eval "$(python3 ccsw.py ...)"`。

---

## 更多功能

<details>
<summary><b>默认把 secret 放进 <code>.env.local</code></b></summary>

真实密钥建议放在 `~/ccsw/.env.local`，`ccswitch` 内部只保存 `$ENV_VAR` 引用。

```bash
# ~/ccsw/.env.local
OR_CLAUDE_TOKEN=<your-claude-token>
OR_CODEX_TOKEN=<your-codex-token>
OR_GEMINI_KEY=<your-gemini-key>
```

- `ccswitch` 运行时会自动读这个文件。
- 已经 `export` 到当前环境里的变量优先级更高。
- `.env.local` 里仍然是明文 secret。它应该只留在本地，并保持未追踪、已被 git 忽略。
- 成功切换后，解析出的真实密钥仍会写入目标工具的配置文件或激活文件。
- 新版本默认不接受新的明文 secret 持久化，除非你显式传 `--allow-literal-secrets`。

</details>

<details>
<summary><b>Profile、doctor、run</b></summary>

如果不同工具想优先使用不同 provider，就用 profile。

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

`run` 只影响这一条命令。它可以按照 profile 队列尝试下一个候选，但不会悄悄改掉你存下来的 active provider：

```bash
ccsw run codex work -- codex exec "hello"
```

</details>

<details>
<summary><b>import、rollback、repair</b></summary>

- `import current`：把当前 live config 回收进 provider store。
- `rollback`：当 live 状态仍和历史记录一致时，回退到上一个 provider。
- `repair`：处理被中断的 `run` 留下的 stale runtime lease。

```bash
ccsw import current claude rescued-claude
ccsw rollback codex
ccsw repair all
```

</details>

<details>
<summary><b>配置目录覆盖</b></summary>

如果某个 CLI 的配置目录不在默认 home 位置，可以用 `settings` 指过去。

```bash
ccsw settings get
ccsw settings set codex_config_dir ~/.codex-alt
ccsw settings set openclaw_config_dir ~/.openclaw-alt
```

WSL 下优先使用 `/mnt/c/...` 这类 POSIX 路径。

</details>

<details>
<summary><b>Codex 0.116+ 说明</b></summary>

对 Codex，`ccswitch` 现在写的是自定义 `model_provider`，不再只依赖老的根级 `openai_base_url`。

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

---

## FAQ

<details>
<summary><b>为什么 <code>ccsw op</code> 能用，但 <code>python3 ccsw.py op</code> 不行？</b></summary>

`ccsw op` 是 `bootstrap.sh` 装进去的 shell wrapper，它在省略工具名时默认补成 `claude`。而 Python CLI 本体仍然需要显式子命令，比如 `claude`、`codex`、`all`。

</details>

<details>
<summary><b>是不是建议每个 provider 都先配一个 alias？</b></summary>

建议。尤其是你会频繁切换时，alias 会让 `ccsw op`、`cxsw op`、`ccsw all vx` 这类命令更短，也更适合写进 profile。

</details>

<details>
<summary><b>为什么运行 <code>gcsw op</code> 之后 <code>$GEMINI_API_KEY</code> 还是空的？</b></summary>

先检查这三件事：

1. `command -v gcsw`
2. 你是不是还在同一个 shell session 里
3. 如果你绕过 wrapper 直接调用 `python3 ccsw.py gemini ...`，有没有写 `eval "$(python3 ccsw.py gemini ...)"`。

</details>

<details>
<summary><b><code>[claude] Skipped: token unresolved</code> 是什么意思？</b></summary>

说明这个 provider 指向了某个环境变量，例如 `$OR_CLAUDE_TOKEN`，但当前环境里没有它。把它写进 `.env.local`，或者在当前 shell 里手动 `export`。

</details>

<details>
<summary><b>除了 OpenRouter，还能不能配 Vertex AI、AWS，或者我自己的中转？</b></summary>

可以。`openrouter` 只是这份 README 里的主例子。把 URL 和凭据替换成服务商文档里的实际值，然后给它起一个你顺手的别名，比如 `vx` 或 `aws` 就行。

</details>

---

## 更多文档

- 发布说明：[CHANGELOG.md](CHANGELOG.md)
- 发布流程：[RELEASING.md](RELEASING.md)
- 贡献指南：[CONTRIBUTING.md](CONTRIBUTING.md)
- 安全说明：[SECURITY.md](SECURITY.md)
- 支持入口：[SUPPORT.md](SUPPORT.md)
- 社区规则：[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

---

## 开发与验证

如果改了代码，最少跑这一组：

```bash
bash bootstrap.sh --dry-run
python3 ccsw.py -h
python3 -m unittest discover -s tests -q
```

如果只是文档改动，至少重新检查公开文档表面、示例命令和交叉链接是不是都还对得上。

---

## 依赖

只需要 Python 3.9+，不需要额外安装第三方包。

## License

MIT

---

<div align="right">

[返回顶部](#ccswitch-terminal)

</div>
