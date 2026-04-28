<div align="center">

<img src="assets/ccswitch-terminal-banner.webp" alt="banner de ccswitch-terminal" width="100%">

# ccswitch-terminal

**Un solo panel para Claude Code, Codex CLI, Gemini CLI, OpenCode y OpenClaw**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml/badge.svg)](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Zero Dependency](https://img.shields.io/badge/zero--dependency-stdlib_only-success.svg)](#inicio-rápido)

[简体中文](README.md) | [English](README_EN.md) | [日本語](README_JA.md) | Español | [Português](README_PT.md) | [Русский](README_RU.md)

[CI](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml) | [CodeQL](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/codeql.yml) | [Issues](https://github.com/Boulea7/ccswitch-terminal/issues/new/choose) | [Changelog](CHANGELOG.md) | [Releasing](RELEASING.md) | [Contributing](CONTRIBUTING.md) | [Security](SECURITY.md) | [Support](SUPPORT.md)

</div>

---

## Resumen

`ccswitch` es una CLI local escrita solo con la librería estándar de Python. Está pensada para quienes usan varias herramientas AI en terminal y no quieren editar archivos de configuración cada vez que cambian de provider.

Hace tres cosas:

- Cambia Claude Code, Codex CLI, Gemini CLI, OpenCode y OpenClaw desde un solo lugar.
- Mantiene providers, aliases, profiles, historial y metadatos de recuperación en un único estado local.
- Se detiene cuando secretos, configuración, runtime leases o snapshots no son lo bastante seguros para continuar.

Este README usa `openrouter -> op` como ejemplo principal. Vertex AI, gateways en AWS y servicios propios compatibles con OpenAI / Anthropic siguen el mismo patrón.

## Puntos Clave

| Función | Qué aporta |
|---------|------------|
| Cambio multi-herramienta | Un solo store de providers para Claude Code, Codex CLI, Gemini CLI, OpenCode y OpenClaw |
| Aliases cortos | Crea `openrouter -> op` y luego usa `ccsw op` y `cxsw op` |
| Colas de profile | Define un orden de providers por herramienta, por ejemplo Codex prueba `op` antes que `vx` |
| Login oficial de Codex | Guarda logins de Codex respaldados por ChatGPT como snapshots locales, por ejemplo `pro` y `pro1` |
| Ejecución de un comando | `ccsw run ...` afecta solo a ese comando y no reescribe el provider activo guardado |
| Herramientas de recuperación | `doctor`, `history`, `rollback` y `repair` ayudan a inspeccionar y recuperar el estado local |

## Inicio Rápido

> [!IMPORTANT]
> `ccswitch` administra CLIs que ya están instaladas. No instala Claude Code, Codex CLI, Gemini CLI, OpenCode ni OpenClaw por ti.

### Instalar con Claude Code o Codex

Esta es la ruta de instalación recomendada. Copia el prompt siguiente en Claude Code o Codex. Instala `ccswitch`, añade tu primer provider, crea un alias y verifica el resultado.

```text
Por favor instala ccswitch desde:
https://github.com/Boulea7/ccswitch-terminal

Pasos:
1. Clónalo en ~/ccsw
2. Ejecuta bash ~/ccsw/bootstrap.sh
3. Recarga mi shell con source ~/.zshrc
4. Verifica con python3 ~/ccsw/ccsw.py -h

Luego agrega un provider usando secretos por variables de entorno:
- nombre del provider: openrouter
- crea este alias al terminar: `op -> openrouter`
- Claude URL: <reemplaza con la URL compatible con Anthropic de la documentación del provider>
- variable de entorno para Claude token: OR_CLAUDE_TOKEN
- Codex URL: <reemplaza con la URL compatible con OpenAI de la documentación del provider>
- variable de entorno para Codex token: OR_CODEX_TOKEN
- variable de entorno para Gemini key: OR_GEMINI_KEY

Escribe los valores reales en ~/ccsw/.env.local.
Guarda en ccswitch solo referencias $ENV_VAR.

Después:
1. ejecuta `ccsw alias op openrouter`
2. ejecuta `ccsw op`
3. ejecuta `cxsw op`
4. ejecuta `ccsw show`
5. explica brevemente en español qué cambió
```

Los nombres habituales de provider pueden mantenerse simples:

| Provider | Alias |
|----------|-------|
| `openrouter` | `op` |
| `vertex` | `vx` |
| `aws` | `aws` |

### Instalación Manual

```bash
git clone https://github.com/Boulea7/ccswitch-terminal ~/ccsw
bash ~/ccsw/bootstrap.sh
source ~/.zshrc   # o source ~/.bashrc
python3 ~/ccsw/ccsw.py -h
```

Vista previa de los cambios en shell:

```bash
bash ~/ccsw/bootstrap.sh --dry-run
```

<details>
<summary><b>Notas de shell</b></summary>

- Después de `bootstrap.sh`, `ccsw <provider>` equivale a `ccsw claude <provider>`.
- `cxsw`, `gcsw`, `opsw` y `clawsw` son wrappers de conveniencia con `eval` integrado.
- Comandos como `gcsw op` afectan solo a la sesión actual de shell.
- En `fish`, PowerShell o nushell, usa `python3 ccsw.py ...` y traduce los exports a la sintaxis de ese shell.

</details>

## Configura Tu Primer Provider

1. Guarda los secretos reales en `~/ccsw/.env.local`.

```bash
OR_CLAUDE_TOKEN=<your-claude-token>
OR_CODEX_TOKEN=<your-codex-token>
OR_GEMINI_KEY=<your-gemini-key>
```

2. Agrega el provider. `ccswitch` guarda solo referencias `$ENV_VAR`.

```bash
ccsw add openrouter \
  --claude-url '<replace-with-your-anthropic-url>' \
  --claude-token '$OR_CLAUDE_TOKEN' \
  --codex-url '<replace-with-your-openai-url>' \
  --codex-token '$OR_CODEX_TOKEN' \
  --gemini-key '$OR_GEMINI_KEY'
```

3. Crea un alias y cambia de provider.

```bash
ccsw alias op openrouter
ccsw op
cxsw op
gcsw op
ccsw all op
ccsw show
```

> [!NOTE]
> `.env.local` sigue siendo texto plano. Mantenlo local, sin seguimiento y fuera de git. Los nuevos secretos literales se rechazan por defecto salvo que pases explícitamente `--allow-literal-secrets`.

## Comandos Principales

```bash
# Cambio
ccsw op                         # Claude Code
cxsw op                         # Codex CLI
gcsw op                         # Gemini CLI
opsw op                         # OpenCode
clawsw op                       # OpenClaw
ccsw all op                     # todas las herramientas configuradas

# Providers y aliases
ccsw list
ccsw show
ccsw add <provider>
ccsw remove <provider>
ccsw alias <alias> <provider>

# Colas de profile
ccsw profile add work --codex op,vx --opencode op
ccsw profile show work
ccsw profile use work

# Diagnóstico y recuperación
ccsw doctor all
ccsw doctor codex op --deep
ccsw history --limit 20
ccsw rollback codex
ccsw repair codex
ccsw import current codex rescued-codex

# Usa candidatos de un profile solo para este comando
ccsw run codex work -- codex exec "hello"
```

## Login Oficial de Codex y Varias Cuentas

Si quieres un provider solo para Codex que vuelva al login oficial de ChatGPT, añade un provider dedicado:

```bash
ccsw add pro --codex-auth-mode chatgpt
cxsw pro
```

Para mantener varias cuentas oficiales en la misma máquina, captura la cuenta actual como `pro`, luego inicia sesión y guarda la segunda cuenta como `pro1`:

```bash
ccsw capture codex pro
ccsw login codex pro1
cxsw accounts
cxsw status
cxsw pro
cxsw pro1
```

`capture` guarda el login oficial actual. `login` oculta temporalmente el `auth.json` local, ejecuta el flujo oficial `codex login` y después guarda la nueva cuenta. No ejecuta `codex logout` primero, para evitar que el refresh token de la cuenta anterior quede invalidado justo después de guardar el snapshot. Usa `accounts` y `status` para revisar snapshots locales, cuenta actual y route de Codex.

```bash
# Desactivado por defecto; solo afecta sesiones oficiales futuras de Codex
cxsw sync on
cxsw pro
cxsw sync status
cxsw sync off

# Guarda comandos sugeridos de sesión compartida sin cambiar ni hacer fork
cxsw share prepare work pro --from last
cxsw share status work
cxsw share clear work
```

<details>
<summary><b>Límites del login oficial de Codex</b></summary>

- `--codex-auth-mode chatgpt` devuelve Codex al provider integrado `openai` y elimina overrides `OPENAI_BASE_URL` / `OPENAI_API_KEY` que entrarían en conflicto con el login oficial.
- Los snapshots multi-cuenta están pensados solo para cambios secuenciales en esta máquina. No son una recomendación para copiar `~/.codex/auth.json` entre máquinas.
- `sync on` solo cambia lo que ocurre la próxima vez que ejecutes `cxsw pro`; no migra sesiones anteriores.
- `share prepare` solo guarda comandos sugeridos, como `cxsw pro` y `codex fork ...`; no entra automáticamente en una sesión.
- `ccswitch` solo gestiona `auth.json` / `config.toml` de Codex CLI y la lane del provider. Codex Apps, MCP remotos, OAuth, proxy y WebSocket siguen siendo responsabilidad de Codex. Si `codex_apps`, `openaiDeveloperDocs` o `deepwiki` fallan al iniciar MCP, ejecuta primero `cxsw status` para confirmar el estado local de la cuenta y luego revisa la versión de Codex, el proxy y la autorización MCP.

</details>

## Uso Avanzado

<details>
<summary><b>Profiles, doctor y run</b></summary>

Usa profiles cuando distintas herramientas deben preferir distintos providers:

```bash
ccsw profile add work \
  --claude op \
  --codex op,vx \
  --gemini aws

ccsw profile use work
```

`doctor` revisa configuración, rutas y estado de probes:

```bash
ccsw doctor all
ccsw doctor codex op --deep
ccsw doctor codex op --json
```

`run` afecta solo a un comando. Puede probar candidatos de profile sin cambiar el provider activo guardado:

```bash
ccsw run codex work -- codex exec "hello"
```

</details>

<details>
<summary><b>Import, rollback y repair</b></summary>

- `import current` guarda la configuración live en el store de providers.
- `rollback` vuelve al provider anterior cuando el estado live todavía coincide con el historial.
- `repair` maneja runtime leases obsoletos dejados por ejecuciones `run` interrumpidas.

```bash
ccsw import current claude rescued-claude
ccsw import current codex pro
ccsw rollback codex
ccsw repair all
```

</details>

<details>
<summary><b>Overrides de directorio de configuración</b></summary>

Usa `settings` cuando una CLI administrada guarda su configuración fuera de la ubicación home por defecto:

```bash
ccsw settings get
ccsw settings set codex_config_dir ~/.codex-alt
ccsw settings set openclaw_config_dir ~/.openclaw-alt
```

En WSL, prefiere rutas POSIX como `/mnt/c/...`.

</details>

<details>
<summary><b>Nota de configuración para Codex 0.116+</b></summary>

Para Codex, `ccswitch` escribe un bloque `model_provider` personalizado en lugar de depender solo del antiguo `openai_base_url` raíz.

```toml
model_provider = "ccswitch_active"

[model_providers.ccswitch_active]
name = "ccswitch: openrouter"
base_url = "https://api.example.com/openai/v1"
env_key = "OPENAI_API_KEY"
supports_websockets = false
wire_api = "responses"
```

Esto importa para relays compatibles con OpenAI que soportan HTTP Responses pero no el transporte Responses WebSocket.

</details>

<details>
<summary><b>Qué escribe ccswitch</b></summary>

| Herramienta | Destino principal |
|-------------|-------------------|
| Claude Code | `~/.claude/settings.json` |
| Codex CLI | `~/.codex/auth.json` y `~/.codex/config.toml` |
| Gemini CLI | `~/.gemini/settings.json` y `~/.ccswitch/active.env` |
| OpenCode | overlay generado bajo `~/.ccswitch/generated/opencode/` |
| OpenClaw | overlay generado bajo `~/.ccswitch/generated/openclaw/` |

El estado principal vive en `~/.ccswitch/ccswitch.db`, con `~/.ccswitch/providers.json` como snapshot de compatibilidad.

</details>

## FAQ

<details>
<summary><b>¿Por qué funciona <code>ccsw op</code> pero no <code>python3 ccsw.py op</code>?</b></summary>

`ccsw op` es un wrapper de shell instalado por `bootstrap.sh`. Si omites el nombre de la herramienta, usa `claude` por defecto. La CLI Python sigue esperando un subcomando explícito como `claude`, `codex` o `all`.

</details>

<details>
<summary><b>¿Conviene crear aliases para los providers?</b></summary>

Normalmente sí. Si cambias con frecuencia, comandos como `ccsw op`, `cxsw op` y `ccsw all vx` son más fáciles de escribir y reutilizar en profiles.

</details>

<details>
<summary><b>¿Qué significa <code>[claude] Skipped: token unresolved</code>?</b></summary>

El provider apunta a una variable de entorno como `$OR_CLAUDE_TOKEN`, pero esa variable no está disponible ahora. Escríbela en `.env.local` o expórtala en el shell actual.

</details>

<details>
<summary><b>¿Puedo usar Vertex AI, AWS o mi propio relay en lugar de OpenRouter?</b></summary>

Sí. `openrouter` es solo el ejemplo principal de este README. Sustituye URLs y credenciales por los valores de la documentación de tu provider y crea un alias que quieras escribir, como `vx` o `aws`.

</details>

## Más Documentación

- Notas de release completas: [CHANGELOG.md](CHANGELOG.md)
- Flujo de release: [RELEASING.md](RELEASING.md)
- Guía de contribución: [CONTRIBUTING.md](CONTRIBUTING.md)
- Política de seguridad: [SECURITY.md](SECURITY.md)
- Guía de soporte: [SUPPORT.md](SUPPORT.md)
- Reglas de la comunidad: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

## Desarrollo y Verificación

```bash
bash bootstrap.sh --dry-run
python3 ccsw.py -h
python3 -m unittest discover -s tests -q
```

Para cambios solo de documentación, revisa al menos los documentos públicos, los comandos de ejemplo y los enlaces cruzados.

## Requisitos

Solo necesitas Python 3.9+. El proyecto no depende de paquetes de terceros, así que no hay nada extra que instalar con `pip`.

## License

MIT
