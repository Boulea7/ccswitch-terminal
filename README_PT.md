# ccswitch-terminal

**Alternador de providers API para Claude Code / Codex CLI / Gemini CLI / OpenCode / OpenClaw**

[![CI](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml/badge.svg)](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml)

[简体中文](README.md) | [English](README_EN.md) | [日本語](README_JA.md) | [Español](README_ES.md) | Português | [Русский](README_RU.md)

[CI](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml) | [CodeQL](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/codeql.yml) | [Issues](https://github.com/Boulea7/ccswitch-terminal/issues/new/choose) | [Changelog](CHANGELOG.md) | [Releasing](RELEASING.md) | [Contributing](CONTRIBUTING.md) | [Security](SECURITY.md) | [Support](SUPPORT.md)

## Sobre este README

Este arquivo é um quickstart em português. Ele mantém a mesma superfície pública de instalação, verificação e comandos básicos usada pelos demais READMEs de release. A documentação completa, incluindo detalhes de `doctor`, `run`, `repair`, schema de histórico e notas operacionais, está em [README_EN.md](README_EN.md).

## Antes de começar

- Você precisa de Python `3.9+`
- `ccswitch` não instala as CLIs gerenciadas. Instale antes qualquer `Claude Code`, `Codex CLI`, `Gemini CLI`, `OpenCode` ou `OpenClaw` que queira controlar
- `bootstrap.sh` configura automaticamente apenas os arquivos rc de `bash` e `zsh`
- Os arquivos `~/.ccswitch/*.env` gerados são snippets de shell POSIX. Em `fish` ou PowerShell, não use `source` neles diretamente; execute `python3 ccsw.py ...` e traduza os `export` para a sintaxe do seu shell

## Instalação mínima

```bash
git clone https://github.com/Boulea7/ccswitch-terminal ~/ccsw
bash ~/ccsw/bootstrap.sh --dry-run
bash ~/ccsw/bootstrap.sh
source ~/.zshrc   # ou source ~/.bashrc
python3 ~/ccsw/ccsw.py -h
```

`--dry-run` mostra o que seria alterado sem gravar arquivos reais.

Se depois você quiser remover a integração do bootstrap, apague do arquivo rc o bloco gerenciado entre `# >>> ccsw bootstrap >>>` e `# <<< ccsw bootstrap <<<`, remova também as linhas de `source` adicionadas para `active.env` / `codex.env` / `opencode.env` / `openclaw.env`, recarregue o shell e, se não precisar mais do store local nem dos overlays gerados, remova manualmente `~/ccsw` e `~/.ccswitch`. No momento `bootstrap.sh` não oferece uma flag de uninstall.

## Verificação inicial

```bash
python3 ~/ccsw/ccsw.py list
python3 ~/ccsw/ccsw.py show
python3 ~/ccsw/ccsw.py doctor all --json
```

- `doctor all --json` emite NDJSON: uma linha e um payload por ferramenta, sem array agregador
- Em uma instalação nova sem provider ativo, `doctor` pode retornar `inactive` sem que isso signifique falha do bootstrap

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

## Onde continuar

- Documentação completa: [README_EN.md](README_EN.md)
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- Releasing: [RELEASING.md](RELEASING.md)
- Suporte: [SUPPORT.md](SUPPORT.md)
- Contribuição: [CONTRIBUTING.md](CONTRIBUTING.md)
- Relatos de segurança: [SECURITY.md](SECURITY.md)
- Regras da comunidade: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
