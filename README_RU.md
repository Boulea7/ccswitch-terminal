# ccswitch-terminal

**Переключатель API provider для Claude Code / Codex CLI / Gemini CLI / OpenCode / OpenClaw**

[![CI](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml/badge.svg)](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml)

[简体中文](README.md) | [English](README_EN.md) | [日本語](README_JA.md) | [Español](README_ES.md) | [Português](README_PT.md) | Русский

[CI](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml) | [CodeQL](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/codeql.yml) | [Issues](https://github.com/Boulea7/ccswitch-terminal/issues/new/choose) | [Changelog](CHANGELOG.md) | [Releasing](RELEASING.md) | [Contributing](CONTRIBUTING.md) | [Security](SECURITY.md) | [Support](SUPPORT.md)

## Что это за файл

Это короткий quickstart на русском. Он держит ту же публичную поверхность по установке, проверке и базовым командам, что и остальные release-facing README. Полная документация, детали по `doctor`, `run`, `repair`, схеме истории и рабочим ограничениям находятся в [README_EN.md](README_EN.md).

## Перед началом

- Нужен Python `3.9+`
- `ccswitch` не устанавливает управляемые CLI. Сначала отдельно установите те `Claude Code`, `Codex CLI`, `Gemini CLI`, `OpenCode` или `OpenClaw`, которыми хотите управлять
- `bootstrap.sh` автоматически настраивает только rc-файлы `bash` и `zsh`
- Сгенерированные `~/.ccswitch/*.env` предназначены для POSIX shell. В `fish` или PowerShell не делайте для них прямой `source`; используйте `python3 ccsw.py ...` и переносите `export` в синтаксис вашего shell

## Минимальная установка

```bash
git clone https://github.com/Boulea7/ccswitch-terminal ~/ccsw
bash ~/ccsw/bootstrap.sh --dry-run
bash ~/ccsw/bootstrap.sh
source ~/.zshrc   # или source ~/.bashrc
python3 ~/ccsw/ccsw.py -h
```

`--dry-run` показывает план изменений и не записывает реальные файлы.

Если позже понадобится убрать bootstrap-интеграцию, удалите из rc-файла управляемый блок между `# >>> ccsw bootstrap >>>` и `# <<< ccsw bootstrap <<<`, уберите строки `source`, которые bootstrap добавил для `active.env` / `codex.env` / `opencode.env` / `openclaw.env`, перезагрузите shell и при желании вручную удалите `~/ccsw` и `~/.ccswitch`, если локальное хранилище и generated overlay больше не нужны. Отдельного флага uninstall в `bootstrap.sh` сейчас нет.

## Первая проверка

```bash
python3 ~/ccsw/ccsw.py list
python3 ~/ccsw/ccsw.py show
python3 ~/ccsw/ccsw.py doctor all --json
```

- `doctor all --json` выводит NDJSON: одна строка и один payload на каждый tool, без общей JSON-массив-обертки
- На свежей установке без active provider `doctor` может вернуть `inactive`, и это не обязательно означает, что bootstrap сломан

## Базовые команды

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

## Куда смотреть дальше

- Полное описание: [README_EN.md](README_EN.md)
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- Releasing: [RELEASING.md](RELEASING.md)
- Поддержка: [SUPPORT.md](SUPPORT.md)
- Как контрибьютить: [CONTRIBUTING.md](CONTRIBUTING.md)
- Безопасность: [SECURITY.md](SECURITY.md)
- Правила сообщества: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
