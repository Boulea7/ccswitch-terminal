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

## Обзор

`ccswitch` — локальная CLI на Python standard library для тех, кто использует несколько AI-инструментов в терминале и не хочет вручную редактировать конфиги при каждой смене provider.

Она делает три вещи:

- Переключает Claude Code, Codex CLI, Gemini CLI, OpenCode и OpenClaw из одного места.
- Хранит providers, aliases, profiles, историю и метаданные восстановления в одном локальном состоянии.
- Останавливается, если secrets, config, runtime leases или snapshots недостаточно безопасны для продолжения.

В этом README главный пример — `openrouter -> op`. Vertex AI, AWS-hosted gateways и собственные OpenAI / Anthropic-compatible сервисы используют тот же шаблон.

## Основные Возможности

| Возможность | Что даёт |
|-------------|----------|
| Переключение нескольких инструментов | Один provider store для Claude Code, Codex CLI, Gemini CLI, OpenCode и OpenClaw |
| Короткие aliases | Создайте `openrouter -> op`, затем используйте `ccsw op` и `cxsw op` |
| Profile queues | Задайте порядок providers для каждого инструмента, например Codex пробует `op` перед `vx` |
| Официальный Codex login | Сохраняйте Codex logins через ChatGPT как локальные snapshots, например `pro` и `pro1` |
| Запуск одной команды | `ccsw run ...` влияет только на эту команду и не переписывает сохранённый active provider |
| Инструменты восстановления | `doctor`, `history`, `rollback` и `repair` помогают проверить и восстановить локальное состояние |

## Быстрый Старт

> [!IMPORTANT]
> `ccswitch` управляет уже установленными CLI. Он не устанавливает Claude Code, Codex CLI, Gemini CLI, OpenCode или OpenClaw за вас.

### Установка через Claude Code или Codex

Это рекомендуемый путь установки. Скопируйте prompt ниже в Claude Code или Codex. Он установит `ccswitch`, добавит первый provider, создаст alias и проверит результат.

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

Обычные имена provider можно держать простыми:

| Provider | Alias |
|----------|-------|
| `openrouter` | `op` |
| `vertex` | `vx` |
| `aws` | `aws` |

### Ручная Установка

```bash
git clone https://github.com/Boulea7/ccswitch-terminal ~/ccsw
bash ~/ccsw/bootstrap.sh
source ~/.zshrc   # или source ~/.bashrc
python3 ~/ccsw/ccsw.py -h
```

Предпросмотр изменений shell:

```bash
bash ~/ccsw/bootstrap.sh --dry-run
```

<details>
<summary><b>Примечания по shell</b></summary>

- После `bootstrap.sh` команда `ccsw <provider>` эквивалентна `ccsw claude <provider>`.
- `cxsw`, `gcsw`, `opsw` и `clawsw` — convenience wrappers со встроенным `eval`.
- Команды вроде `gcsw op` влияют только на текущую shell-сессию.
- В `fish`, PowerShell или nushell лучше использовать `python3 ccsw.py ...` и перевести exports в синтаксис этого shell.

</details>

## Настройка Первого Provider

1. Сохраните реальные secrets в `~/ccsw/.env.local`.

```bash
OR_CLAUDE_TOKEN=<your-claude-token>
OR_CODEX_TOKEN=<your-codex-token>
OR_GEMINI_KEY=<your-gemini-key>
```

2. Добавьте provider. `ccswitch` хранит только ссылки вида `$ENV_VAR`.

```bash
ccsw add openrouter \
  --claude-url '<replace-with-your-anthropic-url>' \
  --claude-token '$OR_CLAUDE_TOKEN' \
  --codex-url '<replace-with-your-openai-url>' \
  --codex-token '$OR_CODEX_TOKEN' \
  --gemini-key '$OR_GEMINI_KEY'
```

3. Создайте alias и переключитесь.

```bash
ccsw alias op openrouter
ccsw op
cxsw op
gcsw op
ccsw all op
ccsw show
```

> [!NOTE]
> `.env.local` остаётся plain text. Держите его локально, без отслеживания в git и в ignore. Новые literal secrets по умолчанию отклоняются, если явно не передать `--allow-literal-secrets`.

## Основные Команды

```bash
# Переключение
ccsw op                         # Claude Code
cxsw op                         # Codex CLI
gcsw op                         # Gemini CLI
opsw op                         # OpenCode
clawsw op                       # OpenClaw
ccsw all op                     # все настроенные инструменты

# Providers и aliases
ccsw list
ccsw show
ccsw add <provider>
ccsw remove <provider>
ccsw alias <alias> <provider>

# Profile queues
ccsw profile add work --codex op,vx --opencode op
ccsw profile show work
ccsw profile use work

# Диагностика и восстановление
ccsw doctor all
ccsw doctor codex op --deep
ccsw history --limit 20
ccsw rollback codex
ccsw repair codex
ccsw import current codex rescued-codex

# Использовать кандидатов profile только для этой команды
ccsw run codex work -- codex exec "hello"
```

## Официальный Codex Login и Несколько Аккаунтов

Если нужен Codex-only provider, который возвращает официальный ChatGPT login, добавьте отдельный provider:

```bash
ccsw add pro --codex-auth-mode chatgpt
cxsw pro
```

Чтобы держать несколько официальных аккаунтов на одной машине, сохраните текущий аккаунт как `pro`, затем войдите и сохраните второй аккаунт как `pro1`:

```bash
ccsw capture codex pro
ccsw login codex pro1
cxsw accounts
cxsw status
cxsw pro
cxsw pro1
```

`capture` сохраняет текущий официальный login. `login` временно скрывает локальный `auth.json`, запускает официальный поток `codex login`, а затем сохраняет новый аккаунт. Он не запускает `codex logout` первым, чтобы refresh token старого аккаунта не становился недействительным сразу после сохранения snapshot. Используйте `accounts` и `status`, чтобы проверить локальные snapshots, текущий аккаунт и route Codex.

```bash
# По умолчанию выключено; влияет только на будущие официальные Codex sessions
cxsw sync on
cxsw pro
cxsw sync status
cxsw sync off

# Сохраняет предлагаемые команды shared session без переключения и fork
cxsw share prepare work pro --from last
cxsw share status work
cxsw share clear work
```

<details>
<summary><b>Границы официального Codex login</b></summary>

- `--codex-auth-mode chatgpt` возвращает Codex к встроенному provider `openai` и очищает overrides `OPENAI_BASE_URL` / `OPENAI_API_KEY`, которые конфликтовали бы с официальным login.
- Multi-account snapshots предназначены только для последовательного переключения на этой машине. Это не рекомендация копировать `~/.codex/auth.json` между машинами.
- `sync on` меняет только поведение следующего запуска `cxsw pro`; старые sessions не мигрируют.
- `share prepare` только сохраняет предлагаемые команды, например `cxsw pro` и `codex fork ...`; он не входит в session автоматически.
- `ccswitch` управляет только `auth.json` / `config.toml` Codex CLI и provider lane. Codex Apps, remote MCP servers, OAuth, proxy routing и WebSocket transport остаются зоной Codex. Если `codex_apps`, `openaiDeveloperDocs` или `deepwiki` падают при MCP startup, сначала выполните `cxsw status`, чтобы проверить локальное состояние аккаунта, затем проверьте версию Codex, proxy и MCP authorization.

</details>

## Расширенное Использование

<details>
<summary><b>Profiles, doctor и run</b></summary>

Используйте profiles, когда разные инструменты должны предпочитать разные providers:

```bash
ccsw profile add work \
  --claude op \
  --codex op,vx \
  --gemini aws

ccsw profile use work
```

`doctor` проверяет config, пути и состояние probes:

```bash
ccsw doctor all
ccsw doctor codex op --deep
ccsw doctor codex op --json
```

`run` влияет только на одну команду. Он может пробовать кандидатов profile, не меняя сохранённый active provider:

```bash
ccsw run codex work -- codex exec "hello"
```

</details>

<details>
<summary><b>Import, rollback и repair</b></summary>

- `import current` сохраняет live config в provider store.
- `rollback` возвращает предыдущий provider, если live state всё ещё совпадает с историей.
- `repair` обрабатывает stale runtime leases, оставшиеся после прерванных `run`.

```bash
ccsw import current claude rescued-claude
ccsw import current codex pro
ccsw rollback codex
ccsw repair all
```

</details>

<details>
<summary><b>Переопределение директорий конфигурации</b></summary>

Используйте `settings`, если управляемая CLI хранит config не в стандартном home:

```bash
ccsw settings get
ccsw settings set codex_config_dir ~/.codex-alt
ccsw settings set openclaw_config_dir ~/.openclaw-alt
```

Для WSL предпочтительны POSIX paths вроде `/mnt/c/...`.

</details>

<details>
<summary><b>Заметка по config для Codex 0.116+</b></summary>

Для Codex `ccswitch` пишет custom `model_provider` block вместо опоры только на старый root-level `openai_base_url`.

```toml
model_provider = "ccswitch_active"

[model_providers.ccswitch_active]
name = "ccswitch: openrouter"
base_url = "https://api.example.com/openai/v1"
env_key = "OPENAI_API_KEY"
supports_websockets = false
wire_api = "responses"
```

Это важно для OpenAI-compatible relays, которые поддерживают HTTP Responses, но не поддерживают Responses WebSocket transport.

</details>

<details>
<summary><b>Что записывает ccswitch</b></summary>

| Инструмент | Основное место записи |
|------------|-----------------------|
| Claude Code | `~/.claude/settings.json` |
| Codex CLI | `~/.codex/auth.json` и `~/.codex/config.toml` |
| Gemini CLI | `~/.gemini/settings.json` и `~/.ccswitch/active.env` |
| OpenCode | generated overlay в `~/.ccswitch/generated/opencode/` |
| OpenClaw | generated overlay в `~/.ccswitch/generated/openclaw/` |

Основное состояние хранится в `~/.ccswitch/ccswitch.db`, а `~/.ccswitch/providers.json` остаётся compatibility snapshot.

</details>

## FAQ

<details>
<summary><b>Почему работает <code>ccsw op</code>, но не работает <code>python3 ccsw.py op</code>?</b></summary>

`ccsw op` — shell wrapper, установленный `bootstrap.sh`. Если имя инструмента не указано, он использует `claude` по умолчанию. Python CLI всё ещё ожидает явный subcommand, например `claude`, `codex` или `all`.

</details>

<details>
<summary><b>Стоит ли создавать aliases для providers?</b></summary>

Обычно да. Если вы часто переключаетесь, команды вроде `ccsw op`, `cxsw op` и `ccsw all vx` проще вводить и проще использовать в profiles.

</details>

<details>
<summary><b>Что означает <code>[claude] Skipped: token unresolved</code>?</b></summary>

Provider указывает на env var вроде `$OR_CLAUDE_TOKEN`, но сейчас этой переменной нет. Добавьте её в `.env.local` или экспортируйте в текущем shell.

</details>

<details>
<summary><b>Можно ли использовать Vertex AI, AWS или свой relay вместо OpenRouter?</b></summary>

Да. `openrouter` — только главный пример в этом README. Замените URLs и credentials значениями из документации provider и создайте alias, который удобно вводить, например `vx` или `aws`.

</details>

## Дополнительная Документация

- Полные release notes: [CHANGELOG.md](CHANGELOG.md)
- Release workflow: [RELEASING.md](RELEASING.md)
- Руководство по вкладу: [CONTRIBUTING.md](CONTRIBUTING.md)
- Security policy: [SECURITY.md](SECURITY.md)
- Support guide: [SUPPORT.md](SUPPORT.md)
- Правила сообщества: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

## Разработка и Проверка

```bash
bash bootstrap.sh --dry-run
python3 ccsw.py -h
python3 -m unittest discover -s tests -q
```

Для docs-only изменений как минимум проверьте публичные документы, примеры команд и перекрёстные ссылки.

## Требования

Нужен только Python 3.9+. У проекта нет зависимости от third-party packages, поэтому ничего дополнительно устанавливать через `pip` не нужно.

## License

MIT
