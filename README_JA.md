# ccswitch-terminal

**Claude Code / Codex CLI / Gemini CLI / OpenCode / OpenClaw 向け API provider 切り替えツール**

[![CI](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml/badge.svg)](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml)

[简体中文](README.md) | [English](README_EN.md) | 日本語 | [Español](README_ES.md) | [Português](README_PT.md) | [Русский](README_RU.md)

[CI](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml) | [CodeQL](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/codeql.yml) | [Issues](https://github.com/Boulea7/ccswitch-terminal/issues/new/choose) | [Changelog](CHANGELOG.md) | [Releasing](RELEASING.md) | [Contributing](CONTRIBUTING.md) | [Security](SECURITY.md) | [Support](SUPPORT.md)

## この README について

これは日本語の quickstart です。ほかの release-facing README と同じ公開インストール面、確認手順、基本コマンドをそろえる前提で保っています。完全な仕様、運用メモ、履歴スキーマ、`doctor` / `run` / `repair` の詳細は [README_EN.md](README_EN.md) を参照してください。

## 始める前に

- Python `3.9+` が必要です
- `ccswitch` は既存の CLI を切り替えるためのツールです。管理したい `Claude Code` / `Codex CLI` / `Gemini CLI` / `OpenCode` / `OpenClaw` は先に各自でインストールしてください
- `bootstrap.sh` が自動設定するのは `bash` / `zsh` の rc ファイルです
- 生成される `~/.ccswitch/*.env` は POSIX shell 向けです。`fish` や PowerShell では直接 `source` せず、`python3 ccsw.py ...` の出力をその shell の記法に合わせて使ってください

## 最短インストール

```bash
git clone https://github.com/Boulea7/ccswitch-terminal ~/ccsw
bash ~/ccsw/bootstrap.sh --dry-run
bash ~/ccsw/bootstrap.sh
source ~/.zshrc   # または source ~/.bashrc
python3 ~/ccsw/ccsw.py -h
```

`--dry-run` は rc ファイルや state を書き換えず、予定されている変更だけを表示します。

bootstrap を後で外したい場合は、rc ファイルから `# >>> ccsw bootstrap >>>` 〜 `# <<< ccsw bootstrap <<<` の managed block と、bootstrap が追加した `active.env` / `codex.env` / `opencode.env` / `openclaw.env` の source 行を削除し、shell を再読み込みしてください。ローカル store や生成 overlay も不要なら `~/ccsw` と `~/.ccswitch` も手動で削除できます。現時点では専用の uninstall フラグはありません。

## 最初の確認

```bash
python3 ~/ccsw/ccsw.py list
python3 ~/ccsw/ccsw.py show
python3 ~/ccsw/ccsw.py doctor all --json
```

- `doctor all --json` は tool ごとに 1 行ずつ出る NDJSON です。全 tool をまとめた 1 個の JSON 配列ではありません
- fresh install 直後で active provider がまだ無い場合、`doctor` が `inactive` を返しても bootstrap 失敗とは限りません

## 基本コマンド

```bash
ccsw openrouter
cxsw openrouter
gcsw openrouter
ccsw all openrouter
ccsw profile use work
ccsw history --limit 20
ccsw rollback codex
ccsw repair codex
ccsw run codex work -- codex exec "hello"
```

## さらに読む

- 完全ドキュメント: [README_EN.md](README_EN.md)
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- Releasing: [RELEASING.md](RELEASING.md)
- サポート窓口: [SUPPORT.md](SUPPORT.md)
- コントリビュート: [CONTRIBUTING.md](CONTRIBUTING.md)
- セキュリティ報告: [SECURITY.md](SECURITY.md)
- コミュニティルール: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
