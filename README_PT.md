<div align="center">

<img src="assets/ccswitch-terminal-banner.webp" alt="banner do ccswitch-terminal" width="100%">

# ccswitch-terminal

**Um único painel para Claude Code, Codex CLI, Gemini CLI, OpenCode e OpenClaw**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml/badge.svg)](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Zero Dependency](https://img.shields.io/badge/zero--dependency-stdlib_only-success.svg)](#início-rápido)

[简体中文](README.md) | [English](README_EN.md) | [日本語](README_JA.md) | [Español](README_ES.md) | Português | [Русский](README_RU.md)

[CI](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/ci.yml) | [CodeQL](https://github.com/Boulea7/ccswitch-terminal/actions/workflows/codeql.yml) | [Issues](https://github.com/Boulea7/ccswitch-terminal/issues/new/choose) | [Changelog](CHANGELOG.md) | [Releasing](RELEASING.md) | [Contributing](CONTRIBUTING.md) | [Security](SECURITY.md) | [Support](SUPPORT.md)

</div>

---

## Visão Geral

`ccswitch` é uma CLI local feita só com a biblioteca padrão do Python. Ela é para quem usa várias ferramentas AI no terminal e não quer editar arquivos de configuração toda vez que troca de provider.

Ela faz três coisas:

- Alterna Claude Code, Codex CLI, Gemini CLI, OpenCode e OpenClaw em um só lugar.
- Mantém providers, aliases, profiles, histórico e metadados de recuperação em um único estado local.
- Para quando segredos, configuração, runtime leases ou snapshots não estão seguros o bastante para continuar.

Este README usa `openrouter -> op` como exemplo principal. Vertex AI, gateways em AWS e serviços próprios compatíveis com OpenAI / Anthropic seguem o mesmo padrão.

## Destaques

| Recurso | O que oferece |
|---------|---------------|
| Troca multi-ferramenta | Um único store de providers para Claude Code, Codex CLI, Gemini CLI, OpenCode e OpenClaw |
| Aliases curtos | Crie `openrouter -> op` e depois use `ccsw op` e `cxsw op` |
| Filas de profile | Defina a ordem de providers por ferramenta, por exemplo Codex tenta `op` antes de `vx` |
| Login oficial do Codex | Salve logins do Codex com ChatGPT como snapshots locais, como `pro` e `pro1` |
| Execução de um comando | `ccsw run ...` afeta só aquele comando e não reescreve o provider ativo salvo |
| Recuperação | `doctor`, `history`, `rollback` e `repair` ajudam a inspecionar e recuperar o estado local |

## Início Rápido

> [!IMPORTANT]
> `ccswitch` gerencia CLIs já instaladas. Ele não instala Claude Code, Codex CLI, Gemini CLI, OpenCode nem OpenClaw para você.

### Instalar com Claude Code ou Codex

Este é o caminho de instalação recomendado. Copie o prompt abaixo para Claude Code ou Codex. Ele instala `ccswitch`, adiciona o primeiro provider, cria um alias e verifica o resultado.

```text
Por favor instale o ccswitch a partir de:
https://github.com/Boulea7/ccswitch-terminal

Passos:
1. Faça clone em ~/ccsw
2. Execute bash ~/ccsw/bootstrap.sh
3. Recarregue meu shell com source ~/.zshrc
4. Verifique com python3 ~/ccsw/ccsw.py -h

Depois adicione um provider usando segredos por variáveis de ambiente:
- nome do provider: openrouter
- crie este alias após a configuração: `op -> openrouter`
- Claude URL: <substitua pela URL compatível com Anthropic da documentação do provider>
- env var do Claude token: OR_CLAUDE_TOKEN
- Codex URL: <substitua pela URL compatível com OpenAI da documentação do provider>
- env var do Codex token: OR_CODEX_TOKEN
- env var da Gemini key: OR_GEMINI_KEY

Escreva os valores reais em ~/ccsw/.env.local.
Guarde no ccswitch apenas referências $ENV_VAR.

Depois:
1. execute `ccsw alias op openrouter`
2. execute `ccsw op`
3. execute `cxsw op`
4. execute `ccsw show`
5. explique brevemente em português o que mudou
```

Nomes comuns de provider podem continuar simples:

| Provider | Alias |
|----------|-------|
| `openrouter` | `op` |
| `vertex` | `vx` |
| `aws` | `aws` |

### Instalação Manual

```bash
git clone https://github.com/Boulea7/ccswitch-terminal ~/ccsw
bash ~/ccsw/bootstrap.sh
source ~/.zshrc   # ou source ~/.bashrc
python3 ~/ccsw/ccsw.py -h
```

Prévia das mudanças no shell:

```bash
bash ~/ccsw/bootstrap.sh --dry-run
```

<details>
<summary><b>Notas sobre shell</b></summary>

- Depois de `bootstrap.sh`, `ccsw <provider>` equivale a `ccsw claude <provider>`.
- `cxsw`, `gcsw`, `opsw` e `clawsw` são wrappers de conveniência com `eval` integrado.
- Comandos como `gcsw op` afetam apenas a sessão atual do shell.
- Em `fish`, PowerShell ou nushell, prefira `python3 ccsw.py ...` e traduza os exports para a sintaxe desse shell.

</details>

## Configure Seu Primeiro Provider

1. Coloque os segredos reais em `~/ccsw/.env.local`.

```bash
OR_CLAUDE_TOKEN=<your-claude-token>
OR_CODEX_TOKEN=<your-codex-token>
OR_GEMINI_KEY=<your-gemini-key>
```

2. Adicione o provider. `ccswitch` guarda apenas referências `$ENV_VAR`.

```bash
ccsw add openrouter \
  --claude-url '<replace-with-your-anthropic-url>' \
  --claude-token '$OR_CLAUDE_TOKEN' \
  --codex-url '<replace-with-your-openai-url>' \
  --codex-token '$OR_CODEX_TOKEN' \
  --gemini-key '$OR_GEMINI_KEY'
```

3. Crie um alias e troque.

```bash
ccsw alias op openrouter
ccsw op
cxsw op
gcsw op
ccsw all op
ccsw show
```

> [!NOTE]
> `.env.local` continua sendo texto puro. Mantenha-o local, sem versionamento e ignorado pelo git. Novos segredos literais são rejeitados por padrão, a menos que você passe explicitamente `--allow-literal-secrets`.

## Comandos Principais

```bash
# Troca
ccsw op                         # Claude Code
cxsw op                         # Codex CLI
gcsw op                         # Gemini CLI
opsw op                         # OpenCode
clawsw op                       # OpenClaw
ccsw all op                     # todas as ferramentas configuradas

# Providers e aliases
ccsw list
ccsw show
ccsw add <provider>
ccsw remove <provider>
ccsw alias <alias> <provider>

# Filas de profile
ccsw profile add work --codex op,vx --opencode op
ccsw profile show work
ccsw profile use work

# Diagnóstico e recuperação
ccsw doctor all
ccsw doctor codex op --deep
ccsw history --limit 20
ccsw rollback codex
ccsw repair codex
ccsw import current codex rescued-codex

# Use candidatos de um profile só para este comando
ccsw run codex work -- codex exec "hello"
```

## Login Oficial do Codex e Múltiplas Contas

Se você quer um provider só para Codex que volte ao login oficial do ChatGPT, adicione um provider dedicado:

```bash
ccsw add pro --codex-auth-mode chatgpt
cxsw pro
```

Para manter várias contas oficiais na mesma máquina, capture a conta atual como `pro`, depois faça login e salve a segunda conta como `pro1`:

```bash
ccsw capture codex pro
ccsw login codex pro1
cxsw accounts
cxsw status
cxsw pro
cxsw pro1
```

`capture` salva o login oficial atual. `login` oculta temporariamente o `auth.json` local, executa o fluxo oficial `codex login` e depois salva a nova conta. Ele não executa `codex logout` primeiro, para evitar que o refresh token da conta anterior seja invalidado logo após o snapshot ser salvo. Use `accounts` e `status` para inspecionar snapshots locais, conta atual e route do Codex.

```bash
# Desativado por padrão; afeta apenas sessões oficiais futuras do Codex
cxsw sync on
cxsw pro
cxsw sync status
cxsw sync off

# Salva comandos sugeridos de sessão compartilhada sem trocar nem fazer fork
cxsw share prepare work pro --from last
cxsw share status work
cxsw share clear work
```

<details>
<summary><b>Limites do login oficial do Codex</b></summary>

- `--codex-auth-mode chatgpt` devolve o Codex ao provider integrado `openai` e remove overrides `OPENAI_BASE_URL` / `OPENAI_API_KEY` que entrariam em conflito com o login oficial.
- Snapshots multi-conta foram pensados só para trocas sequenciais nesta máquina. Eles não são uma recomendação para copiar `~/.codex/auth.json` entre máquinas.
- `sync on` só muda o que acontece na próxima execução de `cxsw pro`; ele não migra sessões antigas.
- `share prepare` só salva comandos sugeridos, como `cxsw pro` e `codex fork ...`; ele não entra automaticamente em uma sessão.
- `ccswitch` só gerencia `auth.json` / `config.toml` do Codex CLI e a lane do provider. Codex Apps, MCP remoto, OAuth, proxy e WebSocket continuam sendo responsabilidade do Codex. Se `codex_apps`, `openaiDeveloperDocs` ou `deepwiki` falharem ao iniciar MCP, execute primeiro `cxsw status` para confirmar o estado local da conta e depois verifique a versão do Codex, o proxy e a autorização MCP.

</details>

## Uso Avançado

<details>
<summary><b>Profiles, doctor e run</b></summary>

Use profiles quando ferramentas diferentes devem preferir providers diferentes:

```bash
ccsw profile add work \
  --claude op \
  --codex op,vx \
  --gemini aws

ccsw profile use work
```

`doctor` verifica configuração, caminhos e estado de probes:

```bash
ccsw doctor all
ccsw doctor codex op --deep
ccsw doctor codex op --json
```

`run` afeta apenas um comando. Ele pode tentar candidatos de profile sem mudar o provider ativo salvo:

```bash
ccsw run codex work -- codex exec "hello"
```

</details>

<details>
<summary><b>Import, rollback e repair</b></summary>

- `import current` salva a configuração live no store de providers.
- `rollback` volta ao provider anterior quando o estado live ainda corresponde ao histórico.
- `repair` lida com runtime leases antigos deixados por execuções `run` interrompidas.

```bash
ccsw import current claude rescued-claude
ccsw import current codex pro
ccsw rollback codex
ccsw repair all
```

</details>

<details>
<summary><b>Overrides de diretório de configuração</b></summary>

Use `settings` quando uma CLI gerenciada salva configuração fora do local home padrão:

```bash
ccsw settings get
ccsw settings set codex_config_dir ~/.codex-alt
ccsw settings set openclaw_config_dir ~/.openclaw-alt
```

No WSL, prefira caminhos POSIX como `/mnt/c/...`.

</details>

<details>
<summary><b>Nota de configuração para Codex 0.116+</b></summary>

Para Codex, `ccswitch` escreve um bloco `model_provider` personalizado em vez de depender apenas do antigo `openai_base_url` raiz.

```toml
model_provider = "ccswitch_active"

[model_providers.ccswitch_active]
name = "ccswitch: openrouter"
base_url = "https://api.example.com/openai/v1"
env_key = "OPENAI_API_KEY"
supports_websockets = false
wire_api = "responses"
```

Isso importa para relays compatíveis com OpenAI que suportam HTTP Responses, mas não o transporte Responses WebSocket.

</details>

<details>
<summary><b>O que ccswitch escreve</b></summary>

| Ferramenta | Destino principal |
|------------|-------------------|
| Claude Code | `~/.claude/settings.json` |
| Codex CLI | `~/.codex/auth.json` e `~/.codex/config.toml` |
| Gemini CLI | `~/.gemini/settings.json` e `~/.ccswitch/active.env` |
| OpenCode | overlay gerado em `~/.ccswitch/generated/opencode/` |
| OpenClaw | overlay gerado em `~/.ccswitch/generated/openclaw/` |

O estado principal fica em `~/.ccswitch/ccswitch.db`, com `~/.ccswitch/providers.json` mantido como snapshot de compatibilidade.

</details>

## FAQ

<details>
<summary><b>Por que <code>ccsw op</code> funciona e <code>python3 ccsw.py op</code> não?</b></summary>

`ccsw op` é um wrapper de shell instalado por `bootstrap.sh`. Quando você omite o nome da ferramenta, ele usa `claude` por padrão. A CLI Python ainda espera um subcomando explícito como `claude`, `codex` ou `all`.

</details>

<details>
<summary><b>Vale a pena criar aliases para providers?</b></summary>

Na maioria dos casos, sim. Se você troca bastante, comandos como `ccsw op`, `cxsw op` e `ccsw all vx` são mais fáceis de digitar e reutilizar em profiles.

</details>

<details>
<summary><b>O que significa <code>[claude] Skipped: token unresolved</code>?</b></summary>

O provider aponta para uma variável de ambiente como `$OR_CLAUDE_TOKEN`, mas essa variável não está disponível agora. Coloque-a em `.env.local` ou exporte no shell atual.

</details>

<details>
<summary><b>Posso usar Vertex AI, AWS ou meu próprio relay em vez de OpenRouter?</b></summary>

Sim. `openrouter` é apenas o exemplo principal deste README. Substitua URLs e credenciais pelos valores da documentação do provider e crie um alias que você realmente queira digitar, como `vx` ou `aws`.

</details>

## Mais Documentação

- Notas completas de release: [CHANGELOG.md](CHANGELOG.md)
- Fluxo de release: [RELEASING.md](RELEASING.md)
- Guia de contribuição: [CONTRIBUTING.md](CONTRIBUTING.md)
- Política de segurança: [SECURITY.md](SECURITY.md)
- Guia de suporte: [SUPPORT.md](SUPPORT.md)
- Regras da comunidade: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

## Desenvolvimento e Verificação

```bash
bash bootstrap.sh --dry-run
python3 ccsw.py -h
python3 -m unittest discover -s tests -q
```

Para mudanças só de documentação, revise ao menos os documentos públicos, comandos de exemplo e links cruzados.

## Requisitos

Você só precisa de Python 3.9+. O projeto não depende de pacotes de terceiros, então não há nada extra para instalar com `pip`.

## License

MIT
