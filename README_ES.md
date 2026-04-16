# ccswitch-terminal

**Conmutador de providers API para Claude Code / Codex CLI / Gemini CLI / OpenCode / OpenClaw**

[![CI](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml/badge.svg)](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml)

[简体中文](README.md) | [English](README_EN.md) | [日本語](README_JA.md) | Español | [Português](README_PT.md) | [Русский](README_RU.md)

[CI](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml) | [CodeQL](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/codeql.yml) | [Issues](https://github.com/Boulea7/ccswitch-terminal/issues/new/choose) | [Changelog](CHANGELOG.md) | [Releasing](RELEASING.md) | [Contributing](CONTRIBUTING.md) | [Security](SECURITY.md) | [Support](SUPPORT.md)

## Qué incluye este README

Este archivo es un quickstart en español. Mantiene la misma superficie pública de instalación, verificación y comandos básicos que el resto de los README de lanzamiento. La referencia completa, los detalles de `doctor`, `run`, `repair`, el esquema de historial y las notas operativas están en [README_EN.md](README_EN.md).

## Antes de empezar

- Necesitas Python `3.9+`
- `ccswitch` no instala las CLIs gestionadas. Instala antes cualquier `Claude Code`, `Codex CLI`, `Gemini CLI`, `OpenCode` u `OpenClaw` que quieras administrar
- `bootstrap.sh` solo configura automáticamente archivos rc de `bash` y `zsh`
- Los archivos `~/.ccswitch/*.env` generados son fragmentos para shells POSIX. En `fish` o PowerShell no los hagas `source` directamente; usa `python3 ccsw.py ...` y adapta los `export` a la sintaxis de tu shell

## Instalación mínima

```bash
git clone https://github.com/Boulea7/ccswitch-terminal ~/ccsw
bash ~/ccsw/bootstrap.sh --dry-run
bash ~/ccsw/bootstrap.sh
source ~/.zshrc   # o source ~/.bashrc
python3 ~/ccsw/ccsw.py -h
```

`--dry-run` muestra lo que cambiaría sin escribir archivos reales.

Si más adelante quieres desinstalar la integración de bootstrap, elimina del rc file el bloque gestionado entre `# >>> ccsw bootstrap >>>` y `# <<< ccsw bootstrap <<<`, borra también las líneas `source` que bootstrap añadió para `active.env` / `codex.env` / `opencode.env` / `openclaw.env`, recarga tu shell y, si ya no necesitas el store local ni los overlays generados, elimina manualmente `~/ccsw` y `~/.ccswitch`. Por ahora `bootstrap.sh` no incluye una bandera de uninstall.

## Comprobación inicial

```bash
python3 ~/ccsw/ccsw.py list
python3 ~/ccsw/ccsw.py show
python3 ~/ccsw/ccsw.py doctor all --json
```

- `doctor all --json` emite NDJSON: una línea y un payload por herramienta, sin array contenedor
- En una instalación nueva sin provider activo, `doctor` puede devolver `inactive` y eso no implica que bootstrap haya fallado

## Comandos básicos

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

## Más información

- Referencia completa: [README_EN.md](README_EN.md)
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- Releasing: [RELEASING.md](RELEASING.md)
- Soporte: [SUPPORT.md](SUPPORT.md)
- Cómo contribuir: [CONTRIBUTING.md](CONTRIBUTING.md)
- Reportes de seguridad: [SECURITY.md](SECURITY.md)
- Normas de la comunidad: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
