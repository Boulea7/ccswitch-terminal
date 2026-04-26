<div align="center">

<img src="assets/ccswitch-terminal-banner.webp" alt="ccswitch-terminal banner" width="100%">

# ccswitch-terminal

**Claude Code、Codex CLI、Gemini CLI、OpenCode、OpenClaw をまとめて切り替えるための 1 つの窓口**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml/badge.svg)](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Zero Dependency](https://img.shields.io/badge/zero--dependency-stdlib_only-success.svg)](#クイックスタート)

[简体中文](README.md) | [English](README_EN.md) | 日本語 | [Español](README_ES.md) | [Português](README_PT.md) | [Русский](README_RU.md)

[CI](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml) | [CodeQL](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/codeql.yml) | [Issues](https://github.com/Boulea7/ccswitch-terminal/issues/new/choose) | [Changelog](CHANGELOG.md) | [Releasing](RELEASING.md) | [Contributing](CONTRIBUTING.md) | [Security](SECURITY.md) | [Support](SUPPORT.md)

</div>

---

## 概要

`ccswitch` は Python 標準ライブラリだけで動くローカル CLI です。複数の AI ターミナルツールを使い、provider を変えるたびに設定ファイルを手で編集したくない人向けです。

主に 3 つのことをします。

- Claude Code、Codex CLI、Gemini CLI、OpenCode、OpenClaw を 1 か所から切り替えます。
- provider、alias、profile、履歴、復旧メタデータを 1 つのローカル状態にまとめます。
- secret、設定、runtime lease、snapshot が安全に続行できない状態なら停止します。

この README では `openrouter -> op` を主な例にしています。Vertex AI、AWS hosted gateway、自前の OpenAI / Anthropic 互換サービスも同じ流れで使えます。

## ハイライト

| 機能 | できること |
|------|------------|
| 複数ツールの切り替え | Claude Code、Codex CLI、Gemini CLI、OpenCode、OpenClaw を 1 つの provider store で管理 |
| 短い alias | `openrouter -> op` を作って、`ccsw op` や `cxsw op` を使う |
| profile queue | ツールごとに provider の順序を設定。例: Codex は `op` のあとに `vx` を試す |
| 公式 Codex ログイン | ChatGPT backed の Codex ログインを `pro`、`pro1` などのローカル snapshot として保存 |
| 1 コマンドだけの実行 | `ccsw run ...` はそのコマンドだけに作用し、保存済み active provider を書き換えません |
| 復旧ツール | `doctor`、`history`、`rollback`、`repair` でローカル状態を確認・復旧 |

## クイックスタート

> [!IMPORTANT]
> `ccswitch` は既にインストール済みの CLI を管理します。Claude Code、Codex CLI、Gemini CLI、OpenCode、OpenClaw 自体は先に入れておいてください。

### Claude Code または Codex でインストール

これが推奨のインストール方法です。次のプロンプトを Claude Code または Codex に貼り付けてください。`ccswitch` のインストール、最初の provider 追加、alias 作成、確認まで実行します。

```text
ccswitch を次のリポジトリからインストールしてください:
https://github.com/Boulea7/ccswitch-terminal

手順:
1. ~/ccsw に clone
2. bash ~/ccsw/bootstrap.sh を実行
3. source ~/.zshrc で shell を再読み込み
4. python3 ~/ccsw/ccsw.py -h で確認

その後、環境変数参照で provider を 1 つ追加してください:
- provider 名: openrouter
- セットアップ後にこの alias を作成: `op -> openrouter`
- Claude URL: <provider のドキュメントにある Anthropic 互換 URL に置き換える>
- Claude token 用 env var: OR_CLAUDE_TOKEN
- Codex URL: <provider のドキュメントにある OpenAI 互換 URL に置き換える>
- Codex token 用 env var: OR_CODEX_TOKEN
- Gemini key 用 env var: OR_GEMINI_KEY

実際の秘密情報は ~/ccsw/.env.local に書き込んでください。
ccswitch 側には $ENV_VAR 参照だけを保存してください。

その後:
1. `ccsw alias op openrouter` を実行
2. `ccsw op` を実行
3. `cxsw op` を実行
4. `ccsw show` を実行
5. 最後に何が変わったかを日本語で短く説明
```

よく使う provider 名はシンプルで構いません。

| Provider | Alias |
|----------|-------|
| `openrouter` | `op` |
| `vertex` | `vx` |
| `aws` | `aws` |

### 手動インストール

```bash
git clone https://github.com/Boulea7/ccswitch-terminal ~/ccsw
bash ~/ccsw/bootstrap.sh
source ~/.zshrc   # または source ~/.bashrc
python3 ~/ccsw/ccsw.py -h
```

shell への変更を先に確認する場合:

```bash
bash ~/ccsw/bootstrap.sh --dry-run
```

<details>
<summary><b>Shell メモ</b></summary>

- `bootstrap.sh` 後、`ccsw <provider>` は `ccsw claude <provider>` と同じです。
- `cxsw`、`gcsw`、`opsw`、`clawsw` は `eval` を内蔵した convenience wrapper です。
- `gcsw op` のようなコマンドは現在の shell session にだけ反映されます。
- `fish`、PowerShell、nushell では `python3 ccsw.py ...` を使い、export をその shell の書式に合わせて扱ってください。

</details>

## 最初の Provider を設定する

1. 実際の秘密情報を `~/ccsw/.env.local` に置きます。

```bash
OR_CLAUDE_TOKEN=<your-claude-token>
OR_CODEX_TOKEN=<your-codex-token>
OR_GEMINI_KEY=<your-gemini-key>
```

2. provider を追加します。`ccswitch` には `$ENV_VAR` 参照だけを保存します。

```bash
ccsw add openrouter \
  --claude-url '<replace-with-your-anthropic-url>' \
  --claude-token '$OR_CLAUDE_TOKEN' \
  --codex-url '<replace-with-your-openai-url>' \
  --codex-token '$OR_CODEX_TOKEN' \
  --gemini-key '$OR_GEMINI_KEY'
```

3. alias を作って切り替えます。

```bash
ccsw alias op openrouter
ccsw op
cxsw op
gcsw op
ccsw all op
ccsw show
```

> [!NOTE]
> `.env.local` は平文です。ローカル専用・未追跡・git ignore 済みの状態にしてください。新しい literal secret は、`--allow-literal-secrets` を明示しない限り既定で拒否されます。

## 主なコマンド

```bash
# 切り替え
ccsw op                         # Claude Code
cxsw op                         # Codex CLI
gcsw op                         # Gemini CLI
opsw op                         # OpenCode
clawsw op                       # OpenClaw
ccsw all op                     # 設定済みツールをまとめて切り替え

# Provider と alias
ccsw list
ccsw show
ccsw add <provider>
ccsw remove <provider>
ccsw alias <alias> <provider>

# Profile queue
ccsw profile add work --codex op,vx --opencode op
ccsw profile show work
ccsw profile use work

# 診断と復旧
ccsw doctor all
ccsw doctor codex op --deep
ccsw history --limit 20
ccsw rollback codex
ccsw repair codex
ccsw import current codex rescued-codex

# profile の候補 provider をこのコマンドだけで使う
ccsw run codex work -- codex exec "hello"
```

## 公式 Codex ログインと複数アカウント

公式 ChatGPT ログインへ戻る Codex-only provider が必要な場合は、専用 provider を追加します。

```bash
ccsw add pro --codex-auth-mode chatgpt
cxsw pro
```

同じマシンで複数の公式アカウントを使う場合は、現在のアカウントを `pro` として保存し、次のアカウントをログインして `pro1` として保存します。

```bash
ccsw capture codex pro
ccsw login codex pro1
cxsw pro
cxsw pro1
```

`capture` は現在の公式ログインを保存します。`login` は公式の `codex logout` / `codex login` フローを実行し、その後で新しいアカウントを保存します。現在の公式アカウントから離れる前に、`ccswitch` は snapshot を更新し、rotating refresh token が古くなる可能性を下げます。

```bash
# 既定では無効。将来の公式 Codex session だけに影響します
cxsw sync on
cxsw pro
cxsw sync status
cxsw sync off

# provider 切り替えや fork はせず、共有 session 用の推奨コマンドだけ保存します
cxsw share prepare work pro --from last
cxsw share status work
cxsw share clear work
```

<details>
<summary><b>公式 Codex ログインの境界</b></summary>

- `--codex-auth-mode chatgpt` は Codex を内蔵 `openai` provider に戻し、公式ログインと衝突する `OPENAI_BASE_URL` / `OPENAI_API_KEY` override を消します。
- 複数アカウント snapshot は、このマシン上での順次切り替えだけを想定しています。`~/.codex/auth.json` を別マシンへコピーするためのものではありません。
- `sync on` は次に `cxsw pro` を実行したときの動作だけを変えます。古い session は移行しません。
- `share prepare` は `cxsw pro` や `codex fork ...` のような推奨コマンドだけを保存します。session には自動で入りません。
- `ccswitch` が管理するのは Codex CLI のログイン状態と provider lane だけです。Codex Apps、remote MCP、OAuth、proxy、WebSocket は Codex 側の領域です。`codex_apps`、`openaiDeveloperDocs`、`deepwiki` が MCP startup で失敗する場合は、まず Codex のバージョン、proxy、MCP 認可を確認してください。

</details>

## 高度な使い方

<details>
<summary><b>Profiles、doctor、run</b></summary>

ツールごとに優先 provider が違う場合は profile を使います。

```bash
ccsw profile add work \
  --claude op \
  --codex op,vx \
  --gemini aws

ccsw profile use work
```

`doctor` は設定、パス、probe 状態を確認します。

```bash
ccsw doctor all
ccsw doctor codex op --deep
ccsw doctor codex op --json
```

`run` は 1 コマンドだけに作用します。保存済み active provider を変えずに、profile の候補を試せます。

```bash
ccsw run codex work -- codex exec "hello"
```

</details>

<details>
<summary><b>Import、rollback、repair</b></summary>

- `import current` は live config を provider store に保存します。
- `rollback` は live state が履歴と一致している場合に前の provider へ戻します。
- `repair` は中断された `run` が残した stale runtime lease を処理します。

```bash
ccsw import current claude rescued-claude
ccsw import current codex pro
ccsw rollback codex
ccsw repair all
```

</details>

<details>
<summary><b>設定ディレクトリの上書き</b></summary>

管理対象 CLI が既定の home 以外に設定を保存する場合は `settings` を使います。

```bash
ccsw settings get
ccsw settings set codex_config_dir ~/.codex-alt
ccsw settings set openclaw_config_dir ~/.openclaw-alt
```

WSL では `/mnt/c/...` のような POSIX path を優先してください。

</details>

<details>
<summary><b>Codex 0.116+ 設定メモ</b></summary>

Codex では、`ccswitch` は古い root-level `openai_base_url` だけに頼らず、custom `model_provider` block を書きます。

```toml
model_provider = "ccswitch_active"

[model_providers.ccswitch_active]
name = "ccswitch: openrouter"
base_url = "https://api.example.com/openai/v1"
env_key = "OPENAI_API_KEY"
supports_websockets = false
wire_api = "responses"
```

これは HTTP Responses には対応しているが Responses WebSocket transport には対応していない OpenAI 互換 relay で重要です。

</details>

<details>
<summary><b>ccswitch が書き込むもの</b></summary>

| ツール | 主な書き込み先 |
|--------|----------------|
| Claude Code | `~/.claude/settings.json` |
| Codex CLI | `~/.codex/auth.json` と `~/.codex/config.toml` |
| Gemini CLI | `~/.gemini/settings.json` と `~/.ccswitch/active.env` |
| OpenCode | `~/.ccswitch/generated/opencode/` 以下の生成 overlay |
| OpenClaw | `~/.ccswitch/generated/openclaw/` 以下の生成 overlay |

主状態は `~/.ccswitch/ccswitch.db` に保存され、`~/.ccswitch/providers.json` は互換 snapshot として残ります。

</details>

## FAQ

<details>
<summary><b>なぜ <code>ccsw op</code> は動くのに <code>python3 ccsw.py op</code> は動かないのですか？</b></summary>

`ccsw op` は `bootstrap.sh` が入れる shell wrapper です。ツール名を省略すると `claude` が既定になります。Python CLI 本体は `claude`、`codex`、`all` のような明示的 subcommand を必要とします。

</details>

<details>
<summary><b>provider に alias を作ったほうがいいですか？</b></summary>

たいていは便利です。頻繁に切り替えるなら、`ccsw op`、`cxsw op`、`ccsw all vx` のような短いコマンドのほうが入力しやすく、profile にも再利用しやすくなります。

</details>

<details>
<summary><b><code>[claude] Skipped: token unresolved</code> は何ですか？</b></summary>

provider が `$OR_CLAUDE_TOKEN` のような環境変数を指していますが、現在その変数がありません。`.env.local` に書くか、現在の shell で export してください。

</details>

<details>
<summary><b>OpenRouter ではなく Vertex AI、AWS、自前 relay も使えますか？</b></summary>

はい。`openrouter` はこの README の主な例です。URL と credential を provider のドキュメントにある値へ置き換え、`vx` や `aws` のような入力しやすい alias を作ってください。

</details>

## さらに読む

- 完全なリリースノート: [CHANGELOG.md](CHANGELOG.md)
- リリース手順: [RELEASING.md](RELEASING.md)
- コントリビューションガイド: [CONTRIBUTING.md](CONTRIBUTING.md)
- セキュリティポリシー: [SECURITY.md](SECURITY.md)
- サポートガイド: [SUPPORT.md](SUPPORT.md)
- コミュニティルール: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

## 開発と検証

```bash
bash bootstrap.sh --dry-run
python3 ccsw.py -h
python3 -m unittest discover -s tests -q
```

ドキュメントだけの変更でも、公開ドキュメント、サンプルコマンド、相互リンクは確認してください。

## 要件

必要なのは Python 3.9+ だけです。サードパーティ package への依存はなく、追加で `pip install` するものはありません。

## License

MIT
