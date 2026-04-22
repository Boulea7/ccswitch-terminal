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

## Qué Hace

`ccswitch` es una herramienta CLI escrita solo con la librería estándar de Python para quienes usan varias herramientas AI en terminal y no quieren editar cinco formatos de configuración cada vez que cambian de provider.

- Cambia Claude Code, Codex CLI, Gemini CLI, OpenCode y OpenClaw desde un solo lugar.
- Usa alias cortos como `openrouter -> op`, y después ejecuta `ccsw op` o `cxsw op`. En este README, esa es la forma recomendada de uso diario.
- Escribe live config para Claude / Codex / Gemini y overlays gestionados para OpenCode / OpenClaw.
- Incluye `profile`, `doctor`, `run`, `history`, `rollback`, `repair` e `import current`.
- Falla de forma segura si la configuración, los secretos o el estado runtime no son lo bastante fiables.

`openrouter` es el ejemplo principal de este README, pero el mismo flujo sirve para Vertex AI, gateways sobre AWS o tu propio relay compatible.

---

## Inicio Rápido

> [!IMPORTANT]
> `ccswitch` administra CLIs que ya están instaladas. No instala Claude Code, Codex CLI, Gemini CLI, OpenCode ni OpenClaw por ti.

### Instalar con Claude Code o Codex

Copia este prompt en Claude Code o Codex. Instala `ccswitch`, agrega tu primer provider, crea un alias y valida el resultado.

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
- Claude URL: <reemplaza con la URL Anthropic-compatible de la documentación del provider>
- variable de entorno para Claude token: OR_CLAUDE_TOKEN
- Codex URL: <reemplaza con la URL OpenAI-compatible de la documentación del provider>
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

Otros ejemplos comunes:

- `vertex` con alias `vx`
- `aws` con alias `aws`

### Instalación Manual

```bash
git clone https://github.com/Boulea7/ccswitch-terminal ~/ccsw
bash ~/ccsw/bootstrap.sh
source ~/.zshrc   # o source ~/.bashrc
python3 ~/ccsw/ccsw.py -h
```

Vista previa sin tocar tu shell:

```bash
bash ~/ccsw/bootstrap.sh --dry-run
```

<details>
<summary><b>Notas de shell</b></summary>

- Después de `bootstrap.sh`, `ccsw <provider>` equivale a `ccsw claude <provider>`.
- `cxsw`, `gcsw`, `opsw` y `clawsw` ya traen `eval`.
- En `fish` o PowerShell, usa `python3 ccsw.py ...` y adapta los exports al shell correspondiente.

</details>

---

## Primer Provider en 60 Segundos

1. Guarda secretos en `~/ccsw/.env.local`.

```bash
OR_CLAUDE_TOKEN=<your-claude-token>
OR_CODEX_TOKEN=<your-codex-token>
OR_GEMINI_KEY=<your-gemini-key>
```

2. Agrega el provider.

```bash
ccsw add openrouter \
  --claude-url '<replace-with-your-anthropic-url>' \
  --claude-token '$OR_CLAUDE_TOKEN' \
  --codex-url '<replace-with-your-openai-url>' \
  --codex-token '$OR_CODEX_TOKEN' \
  --gemini-key '$OR_GEMINI_KEY'
```

3. Puedes usar el nombre completo del provider o crear un alias corto.

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

4. Repite el mismo patrón para otros providers.

```bash
ccsw alias vx vertex
ccsw alias aws aws
```

### Alias (abreviatura)

Si vas a usar `ccswitch` con frecuencia, resulta más cómodo usar alias (abreviaturas) en el día a día en lugar de dejarlos solo como atajos ocasionales.

Una convención corta y estable puede ser:

| Provider | Alias sugerido (abreviatura) |
|----------|----------------|
| `openrouter` | `op` |
| `vertex` | `vx` |
| `aws` | `aws` |

```bash
ccsw alias op openrouter
ccsw alias vx vertex
ccsw alias aws aws
```

Luego usa siempre los nombres cortos:

```bash
ccsw op
cxsw op
ccsw all vx
ccsw profile add work --codex op,vx --opencode op
ccsw profile add cloud --claude aws --codex aws,op
```

Si no quieres alias, también puedes usar `ccsw openrouter` o `cxsw openrouter`.

---

## Comandos Principales

```bash
# Cambio: se recomienda alias, pero el nombre completo también funciona
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

cxsw sync on|off|status
cxsw share prepare <lane> <provider> --from last
cxsw share status [lane]
cxsw share clear <lane>

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
> `gcsw op` afecta la shell actual. Si llamas `python3 ccsw.py gemini ...` o `python3 ccsw.py codex ...` directamente, usa `eval "$(python3 ccsw.py ...)"`.

---

## Más Funciones

<details>
<summary><b>Usa <code>.env.local</code> para secretos</b></summary>

Guarda tokens reales en `~/ccsw/.env.local` y deja referencias `$ENV_VAR` en `ccswitch`.

`.env.local` sigue siendo texto plano. Mantenlo local, sin seguimiento y fuera de git.
- Después de un switch correcto, los secretos resueltos siguen escribiéndose en los archivos de config o activación del tool de destino.
- Los nuevos secretos literales se rechazan por defecto salvo que uses `--allow-literal-secrets`.

</details>

<details>
<summary><b>Profiles, doctor y run</b></summary>

Usa `profile` para colas reutilizables, `doctor` para validación y `run` para un solo comando con fallback temporal.

```bash
ccsw profile add work --claude op --codex op,vx --gemini aws
ccsw doctor codex op --deep
ccsw run codex work -- codex exec "hello"
```

</details>

<details>
<summary><b>Import, rollback y repair</b></summary>

```bash
ccsw import current claude rescued-claude
ccsw rollback codex
ccsw repair all
```

</details>

<details>
<summary><b>Overrides de directorio de config</b></summary>

```bash
ccsw settings get
ccsw settings set codex_config_dir ~/.codex-alt
ccsw settings set openclaw_config_dir ~/.openclaw-alt
```

</details>

<details>
<summary><b>Nota sobre Codex 0.116+</b></summary>

`ccswitch` escribe un `model_provider` explícito para Codex y marca `supports_websockets = false` cuando corresponde.

`cxsw pro` sigue usando la lane integrada `openai` por defecto. Solo si activas `cxsw sync on` y luego vuelves a ejecutar `cxsw pro`, las sesiones oficiales futuras pasan a la lane compartida. Las sesiones existentes no se migran.

`cxsw share prepare ...` no cambia el provider ni hace `fork` de una sesión automáticamente. Solo guarda la receta con los siguientes comandos sugeridos, como `cxsw ...` y `codex fork ...`.

</details>

---

## FAQ

<details>
<summary><b>¿Por qué funciona <code>ccsw op</code> pero no <code>python3 ccsw.py op</code>?</b></summary>

`ccsw op` es un wrapper de shell instalado por `bootstrap.sh`. El CLI Python sigue esperando un subcomando explícito.

</details>

<details>
<summary><b>¿Conviene crear alias (abreviaturas) para cada provider?</b></summary>

Sí, en la mayoría de los casos. Si cambias seguido, comandos como `ccsw op`, `cxsw op` o `ccsw all vx` son más cortos y además encajan mejor en los profiles.

- `op = openrouter`
- `vx = vertex`
- `aws = aws`

</details>

<details>
<summary><b>¿Puedo usar Vertex AI, AWS o mi propio relay?</b></summary>

Sí. `openrouter` es solo el ejemplo principal de este README.

</details>

---

## Más Documentación

- Referencia principal: [README_EN.md](README_EN.md)
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- Releasing: [RELEASING.md](RELEASING.md)
- Contributing: [CONTRIBUTING.md](CONTRIBUTING.md)
- Security: [SECURITY.md](SECURITY.md)
- Support: [SUPPORT.md](SUPPORT.md)
- Code of Conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

---

## Verificación

Para cambios de código:

```bash
bash bootstrap.sh --dry-run
python3 ccsw.py -h
python3 -m unittest discover -s tests -q
```

Para cambios solo de documentación, vuelve a revisar comandos de ejemplo, enlaces y consistencia entre los README públicos.

---

## Requisitos

Solo necesitas Python 3.9+. El proyecto no depende de paquetes externos, así que no hace falta instalar nada más con `pip`.

## License

MIT
