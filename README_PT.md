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

## O Que Faz

`ccswitch` é uma CLI feita só com a biblioteca padrão do Python para quem usa várias ferramentas AI no terminal e não quer editar cinco formatos de configuração toda vez que troca de provider.

- Alterna Claude Code, Codex CLI, Gemini CLI, OpenCode e OpenClaw em um só lugar.
- Aceita aliases curtos como `openrouter -> op`, então depois você usa `ccsw op` ou `cxsw op`. Neste README, esse é o fluxo recomendado para o uso diário.
- Escreve live config para Claude / Codex / Gemini e overlays gerenciados para OpenCode / OpenClaw.
- Inclui `profile`, `doctor`, `run`, `history`, `rollback`, `repair` e `import current`.
- Para em modo fail-closed quando o estado não está seguro o bastante.

O exemplo principal deste README usa `openrouter`, mas o mesmo fluxo serve para Vertex AI, gateways em AWS ou um relay compatível seu.

---

## Início Rápido

> [!IMPORTANT]
> `ccswitch` gerencia CLIs já instaladas. Ele não instala Claude Code, Codex CLI, Gemini CLI, OpenCode nem OpenClaw para você.

### Instalar com Claude Code ou Codex

Copie este prompt para o Claude Code ou Codex. Ele instala `ccswitch`, adiciona o primeiro provider, cria um alias e faz a verificação básica.

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

Outros exemplos comuns:

- `vertex` com alias `vx`
- `aws` com alias `aws`

### Instalação Manual

```bash
git clone https://github.com/Boulea7/ccswitch-terminal ~/ccsw
bash ~/ccsw/bootstrap.sh
source ~/.zshrc   # ou source ~/.bashrc
python3 ~/ccsw/ccsw.py -h
```

Prévia sem alterar o shell:

```bash
bash ~/ccsw/bootstrap.sh --dry-run
```

<details>
<summary><b>Notas sobre shell</b></summary>

- Depois de `bootstrap.sh`, `ccsw <provider>` equivale a `ccsw claude <provider>`.
- `cxsw`, `gcsw`, `opsw` e `clawsw` já incluem `eval`.
- Em `fish` ou PowerShell, prefira `python3 ccsw.py ...` e adapte os exports ao shell usado.

</details>

---

## Primeiro Provider em 60 Segundos

1. Coloque os segredos em `~/ccsw/.env.local`.

```bash
OR_CLAUDE_TOKEN=<your-claude-token>
OR_CODEX_TOKEN=<your-codex-token>
OR_GEMINI_KEY=<your-gemini-key>
```

2. Adicione o provider.

```bash
ccsw add openrouter \
  --claude-url '<replace-with-your-anthropic-url>' \
  --claude-token '$OR_CLAUDE_TOKEN' \
  --codex-url '<replace-with-your-openai-url>' \
  --codex-token '$OR_CODEX_TOKEN' \
  --gemini-key '$OR_GEMINI_KEY'
```

3. Você pode usar o nome completo do provider ou criar um alias curto.

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

4. Faça o mesmo com outros providers.

```bash
ccsw alias vx vertex
ccsw alias aws aws
```

### Alias (abreviação)

Se você vai usar `ccswitch` com frequência, fica mais natural usar alias (abreviações) no dia a dia em vez de deixá-los só como atalhos ocasionais.

Uma convenção simples pode ser:

| Provider | Alias sugerido (abreviação) |
|----------|----------------|
| `openrouter` | `op` |
| `vertex` | `vx` |
| `aws` | `aws` |

```bash
ccsw alias op openrouter
ccsw alias vx vertex
ccsw alias aws aws
```

Depois disso, use os nomes curtos no dia a dia:

```bash
ccsw op
cxsw op
ccsw all vx
ccsw profile add work --codex op,vx --opencode op
ccsw profile add cloud --claude aws --codex aws,op
```

Se preferir, você ainda pode usar `ccsw openrouter` e `cxsw openrouter`.

---

## Comandos Principais

```bash
# Troca: alias é o caminho recomendado, mas o nome completo também funciona
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
> `gcsw op` afeta apenas a shell atual. Se você chamar `python3 ccsw.py gemini ...` ou `python3 ccsw.py codex ...` diretamente, use `eval "$(python3 ccsw.py ...)"`.

---

## Mais Recursos

<details>
<summary><b>Segredos em <code>.env.local</code></b></summary>

Guarde os tokens reais em `~/ccsw/.env.local` e deixe só referências `$ENV_VAR` no store do `ccswitch`.

`.env.local` continua sendo texto puro. Mantenha esse arquivo local, sem versionamento e fora do git.
- Depois de um switch bem-sucedido, os segredos resolvidos ainda são escritos nos arquivos de config ou ativação da ferramenta de destino.
- Novos segredos literais são rejeitados por padrão, a menos que você use `--allow-literal-secrets`.

</details>

<details>
<summary><b>profile, doctor e run</b></summary>

```bash
ccsw profile add work --claude op --codex op,vx --gemini aws
ccsw doctor codex op --deep
ccsw run codex work -- codex exec "hello"
```

</details>

<details>
<summary><b>import, rollback e repair</b></summary>

```bash
ccsw import current claude rescued-claude
ccsw rollback codex
ccsw repair all
```

</details>

<details>
<summary><b>Overrides de diretório de config</b></summary>

```bash
ccsw settings get
ccsw settings set codex_config_dir ~/.codex-alt
ccsw settings set openclaw_config_dir ~/.openclaw-alt
```

</details>

<details>
<summary><b>Nota sobre Codex 0.116+</b></summary>

`ccswitch` escreve um `model_provider` explícito para o Codex e usa `supports_websockets = false` quando necessário.

`cxsw pro` continua usando a lane integrada `openai` por padrão. Só depois de ativar `cxsw sync on` e executar `cxsw pro` novamente é que as sessões oficiais futuras entram na lane compartilhada. Sessões antigas não são migradas.

`cxsw share prepare ...` não troca o provider nem faz `fork` de sessão automaticamente. Ele só salva a receita com os próximos comandos sugeridos, como `cxsw ...` e `codex fork ...`.

</details>

---

## FAQ

<details>
<summary><b>Por que <code>ccsw op</code> funciona e <code>python3 ccsw.py op</code> não?</b></summary>

`ccsw op` é um wrapper de shell instalado por `bootstrap.sh`. A CLI Python continua exigindo um subcomando explícito.

</details>

<details>
<summary><b>Vale a pena criar alias (abreviações) para cada provider?</b></summary>

Na maioria dos casos, sim. Se você troca bastante, comandos como `ccsw op`, `cxsw op` e `ccsw all vx` ficam mais rápidos de digitar e também funcionam melhor dentro de profiles.

- `op = openrouter`
- `vx = vertex`
- `aws = aws`

</details>

<details>
<summary><b>Posso usar Vertex AI, AWS ou meu próprio relay?</b></summary>

Sim. `openrouter` é só o exemplo principal deste README.

</details>

---

## Mais Documentação

- Referência principal: [README_EN.md](README_EN.md)
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- Releasing: [RELEASING.md](RELEASING.md)
- Contributing: [CONTRIBUTING.md](CONTRIBUTING.md)
- Security: [SECURITY.md](SECURITY.md)
- Support: [SUPPORT.md](SUPPORT.md)
- Code of Conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

---

## Verificação

Para mudanças de código:

```bash
bash bootstrap.sh --dry-run
python3 ccsw.py -h
python3 -m unittest discover -s tests -q
```

Para mudanças só de docs, revise exemplos, links e consistência entre os README públicos.

---

## Requisitos

Você só precisa de Python 3.9+. O projeto não depende de pacotes de terceiros, então não há nada extra para instalar com `pip`.

## License

MIT
