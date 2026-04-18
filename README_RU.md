<div align="center">

<img src="assets/ccswitch-terminal-banner.webp" alt="banner ccswitch-terminal" width="100%">

# ccswitch-terminal

**Одна точка переключения для Claude Code, Codex CLI, Gemini CLI, OpenCode и OpenClaw**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml/badge.svg)](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Zero Dependency](https://img.shields.io/badge/zero--dependency-stdlib_only-success.svg)](#быстрый-старт)

[简体中文](README.md) | [English](README_EN.md) | [日本語](README_JA.md) | [Español](README_ES.md) | [Português](README_PT.md) | Русский

[CI](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml) | [CodeQL](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/codeql.yml) | [Issues](https://github.com/Boulea7/ccswitch-terminal/issues/new/choose) | [Changelog](CHANGELOG.md) | [Releasing](RELEASING.md) | [Contributing](CONTRIBUTING.md) | [Security](SECURITY.md) | [Support](SUPPORT.md)

</div>

---

## Что Делает

`ccswitch` — это CLI на Python standard library для тех, кто использует несколько AI-инструментов в терминале и не хочет вручную править пять разных конфигов при каждой смене provider.

- Переключает Claude Code, Codex CLI, Gemini CLI, OpenCode и OpenClaw из одного места.
- Поддерживает короткие alias, например `openrouter -> op`, чтобы потом использовать `ccsw op` или `cxsw op`. В этом README это считается основным повседневным способом работы.
- Пишет live config для Claude / Codex / Gemini и управляемые overlay для OpenCode / OpenClaw.
- Включает `profile`, `doctor`, `run`, `history`, `rollback`, `repair` и `import current`.
- Работает в fail-closed режиме, если состояние недостаточно надёжно.

Главный пример в README — `openrouter`, но тот же поток подходит и для Vertex AI, AWS-шлюзов или собственного совместимого relay.

---

## Быстрый Старт

> [!IMPORTANT]
> `ccswitch` управляет уже установленными CLI. Он не устанавливает за вас Claude Code, Codex CLI, Gemini CLI, OpenCode или OpenClaw.

### Установка через Claude Code или Codex

Скопируйте этот prompt в Claude Code или Codex. Он установит `ccswitch`, добавит первый provider, создаст alias и выполнит базовую проверку.

```text
Пожалуйста, установите ccswitch из репозитория:
https://github.com/Boulea7/ccswitch-terminal

Шаги:
1. Клонируйте в ~/ccsw
2. Выполните bash ~/ccsw/bootstrap.sh
3. Перезагрузите shell через source ~/.zshrc
4. Проверьте командой python3 ~/ccsw/ccsw.py -h

Затем добавьте один provider, используя секреты через переменные окружения:
- имя provider: openrouter
- после настройки создайте alias: `op -> openrouter`
- Claude URL: <замените на Anthropic-compatible URL из документации provider>
- env var для Claude token: OR_CLAUDE_TOKEN
- Codex URL: <замените на OpenAI-compatible URL из документации provider>
- env var для Codex token: OR_CODEX_TOKEN
- env var для Gemini key: OR_GEMINI_KEY

Запишите реальные значения в ~/ccsw/.env.local.
В ccswitch храните только ссылки вида $ENV_VAR.

После этого:
1. выполните `ccsw alias op openrouter`
2. выполните `ccsw op`
3. выполните `cxsw op`
4. выполните `ccsw show`
5. кратко объясните по-русски, что изменилось
```

Другие типичные примеры:

- `vertex` с alias `vx`
- `aws` с alias `aws`

### Ручная Установка

```bash
git clone https://github.com/Boulea7/ccswitch-terminal ~/ccsw
bash ~/ccsw/bootstrap.sh
source ~/.zshrc   # или source ~/.bashrc
python3 ~/ccsw/ccsw.py -h
```

Предпросмотр без изменения shell:

```bash
bash ~/ccsw/bootstrap.sh --dry-run
```

<details>
<summary><b>Примечания по shell</b></summary>

- После `bootstrap.sh` команда `ccsw <provider>` означает `ccsw claude <provider>`.
- `cxsw`, `gcsw`, `opsw` и `clawsw` уже содержат `eval`.
- В `fish` или PowerShell лучше использовать `python3 ccsw.py ...` и адаптировать exports под синтаксис своего shell.

</details>

---

## Первый Provider за 60 Секунд

1. Сохраните секреты в `~/ccsw/.env.local`.

```bash
OR_CLAUDE_TOKEN=<your-claude-token>
OR_CODEX_TOKEN=<your-codex-token>
OR_GEMINI_KEY=<your-gemini-key>
```

2. Добавьте provider.

```bash
ccsw add openrouter \
  --claude-url '<replace-with-your-anthropic-url>' \
  --claude-token '$OR_CLAUDE_TOKEN' \
  --codex-url '<replace-with-your-openai-url>' \
  --codex-token '$OR_CODEX_TOKEN' \
  --gemini-key '$OR_GEMINI_KEY'
```

3. Можно использовать полное имя provider или создать короткий alias.

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

4. Тот же шаблон для других provider.

```bash
ccsw alias vx vertex
ccsw alias aws aws
```

### Alias (сокращение)

Если вы собираетесь пользоваться `ccswitch` регулярно, удобнее воспринимать alias (сокращения) не как редкое сокращение, а как обычный рабочий стиль.

Простая и стабильная схема может быть такой:

| Provider | Рекомендуемый alias (сокращение) |
|----------|---------------------|
| `openrouter` | `op` |
| `vertex` | `vx` |
| `aws` | `aws` |

```bash
ccsw alias op openrouter
ccsw alias vx vertex
ccsw alias aws aws
```

После этого используйте короткие имена везде:

```bash
ccsw op
cxsw op
ccsw all vx
ccsw profile add work --codex op,vx --opencode op
ccsw profile add cloud --claude aws --codex aws,op
```

При этом alias не обязателен: `ccsw openrouter` и `cxsw openrouter` тоже работают.

---

## Основные Команды

```bash
# Переключение: alias рекомендуется, но полное имя provider тоже работает
ccsw op
cxsw op
gcsw op
opsw op
clawsw op
ccsw all op
ccsw openrouter
cxsw openrouter

ccsw list
ccsw show
ccsw add <provider>
ccsw remove <provider>
ccsw alias <alias> <provider>

ccsw profile add work --codex op,vx --opencode op
ccsw profile add cloud --claude aws --codex aws,op
ccsw profile show work
ccsw profile use work

ccsw doctor all
ccsw history --limit 20
ccsw rollback codex
ccsw repair codex
ccsw import current codex rescued-codex
ccsw run codex work -- codex exec "hello"
```

> [!NOTE]
> `gcsw op` влияет только на текущую shell-сессию. Если вы запускаете `python3 ccsw.py gemini ...` или `python3 ccsw.py codex ...` напрямую, используйте `eval "$(python3 ccsw.py ...)"`.

---

## Дополнительно

<details>
<summary><b>Секреты лучше хранить в <code>.env.local</code></b></summary>

Храните реальные токены в `~/ccsw/.env.local`, а в `ccswitch` оставляйте только ссылки вида `$ENV_VAR`.

Сам `.env.local` остаётся plain text, поэтому его нужно держать локально, без отслеживания в git.
- После успешного переключения разрешённые секреты всё равно записываются в config или activation-файлы целевого инструмента.
- Новые literal secret по умолчанию отклоняются, если явно не передать `--allow-literal-secrets`.

</details>

<details>
<summary><b>profile, doctor и run</b></summary>

```bash
ccsw profile add work --claude op --codex op,vx --gemini aws
ccsw doctor codex op --deep
ccsw run codex work -- codex exec "hello"
```

</details>

<details>
<summary><b>import, rollback и repair</b></summary>

```bash
ccsw import current claude rescued-claude
ccsw rollback codex
ccsw repair all
```

</details>

<details>
<summary><b>Переопределение директорий конфигурации</b></summary>

```bash
ccsw settings get
ccsw settings set codex_config_dir ~/.codex-alt
ccsw settings set openclaw_config_dir ~/.openclaw-alt
```

</details>

<details>
<summary><b>Заметка про Codex 0.116+</b></summary>

Для Codex `ccswitch` пишет явный `model_provider` и использует `supports_websockets = false`, когда это требуется.

</details>

---

## FAQ

<details>
<summary><b>Почему работает <code>ccsw op</code>, но не работает <code>python3 ccsw.py op</code>?</b></summary>

`ccsw op` — это shell wrapper, который устанавливает `bootstrap.sh`. Сам Python CLI по-прежнему ожидает явный subcommand.

</details>

<details>
<summary><b>Стоит ли заводить alias (сокращения) для каждого provider?</b></summary>

Обычно да. Если вы часто переключаетесь, команды вроде `ccsw op`, `cxsw op` и `ccsw all vx` короче, удобнее и лучше подходят для profile.

- `op = openrouter`
- `vx = vertex`
- `aws = aws`

</details>

<details>
<summary><b>Можно ли использовать Vertex AI, AWS или свой relay?</b></summary>

Да. `openrouter` здесь только основной пример.

</details>

---

## Что Почитать Дальше

- Основная reference-версия: [README_EN.md](README_EN.md)
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- Releasing: [RELEASING.md](RELEASING.md)
- Contributing: [CONTRIBUTING.md](CONTRIBUTING.md)
- Security: [SECURITY.md](SECURITY.md)
- Support: [SUPPORT.md](SUPPORT.md)
- Code of Conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

---

## Проверка

Для изменений в коде:

```bash
bash bootstrap.sh --dry-run
python3 ccsw.py -h
python3 -m unittest discover -s tests -q
```

Для чисто документальных изменений перепроверьте примеры команд, ссылки и согласованность публичных README.

---

## Требования

Нужен только Python 3.9+. Проект не зависит от сторонних пакетов, поэтому ничего дополнительно устанавливать через `pip` не нужно.

## License

MIT
