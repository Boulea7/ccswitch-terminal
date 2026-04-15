#!/usr/bin/env bash
# bootstrap.sh - Install ccsw smart shell functions

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CCSW_PY="$SCRIPT_DIR/ccsw.py"
BOOTSTRAP_HOME="${BOOTSTRAP_HOME:-$HOME}"
CCSWITCH_DIR="$BOOTSTRAP_HOME/.ccswitch"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        *)
            echo "[error] Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

note_action() {
    if [[ "$DRY_RUN" == "1" ]]; then
        echo "[dry-run] $1"
    fi
}

# Detect rc file
ENV_SHELL="$(printenv SHELL 2>/dev/null || true)"
CURRENT_SHELL="$(ps -p $$ -o comm= 2>/dev/null || echo "")"
if [[ -n "${BOOTSTRAP_RC_FILE:-}" ]]; then
    RC_FILE="$BOOTSTRAP_RC_FILE"
elif [[ "$ENV_SHELL" == */zsh ]]; then
    RC_FILE="$HOME/.zshrc"
elif [[ "$ENV_SHELL" == */bash ]]; then
    RC_FILE="$HOME/.bashrc"
elif [[ -f "$HOME/.zshrc" ]]; then
    RC_FILE="$HOME/.zshrc"
elif [[ -f "$HOME/.bashrc" ]]; then
    RC_FILE="$HOME/.bashrc"
elif [[ "$CURRENT_SHELL" == *zsh* ]]; then
    RC_FILE="$HOME/.zshrc"
else
    RC_FILE="$HOME/.bashrc"
fi

# Verify ccsw.py exists
if [[ ! -f "$CCSW_PY" ]]; then
    echo "[error] ccsw.py not found at: $CCSW_PY" >&2
    exit 1
fi

# Verify python3 is available
if ! command -v python3 &>/dev/null; then
    echo "[error] python3 not found. Please install Python 3.9+." >&2
    exit 1
fi

if [[ "$DRY_RUN" == "1" ]]; then
    note_action "Would create $CCSWITCH_DIR, $CCSWITCH_DIR/generated, and $CCSWITCH_DIR/tmp"
    note_action "Would update shell rc file: $RC_FILE"
else
    mkdir -p "$CCSWITCH_DIR"
    mkdir -p "$CCSWITCH_DIR/generated" "$CCSWITCH_DIR/tmp"
    chmod 700 "$CCSWITCH_DIR" "$CCSWITCH_DIR/generated" "$CCSWITCH_DIR/tmp"
    chmod +x "$CCSW_PY"
fi

# ── Inject / upgrade smart function block ─────────────────────────────────────
MARKER="# ccsw - smart provider switcher"
MANAGED_START="# >>> ccsw bootstrap >>>"
MANAGED_END="# <<< ccsw bootstrap <<<"
CCSW_PY_QUOTED="$(printf '%q' "$CCSW_PY")"
WRAPPER_BLOCK="$(
    BOOTSTRAP_MARKER="$MARKER" \
    BOOTSTRAP_MANAGED_START="$MANAGED_START" \
    BOOTSTRAP_MANAGED_END="$MANAGED_END" \
    BOOTSTRAP_CCSW_PY_QUOTED="$CCSW_PY_QUOTED" \
    BOOTSTRAP_CCSWITCH_DIR="$CCSWITCH_DIR" \
    python3 <<'PYEOF'
import os

template = """{managed_start}
{marker}
unalias ccsw 2>/dev/null || true
_CCSW_PY={ccsw_py}
# ccsw: smart wrapper — omitting the tool name defaults to 'claude'
#   ccsw demo-provider -> ccsw claude demo-provider
#   ccsw codex/gemini/opencode/openclaw/all/profile/rollback -> eval when exports may be emitted
#   ccsw repair/show/... -> pass-through
ccsw() {{
  case "${{1:-}}" in
    ""|--help|-h|help|-*)
      python3 "$_CCSW_PY" "$@" ;;
    codex|gemini|opencode|openclaw|all|profile|rollback)
      eval "$(python3 "$_CCSW_PY" "$@")" ;;
    claude|list|show|add|remove|alias|settings|doctor|history|repair|import|run)
      python3 "$_CCSW_PY" "$@" ;;
    *)
      python3 "$_CCSW_PY" claude "$@" ;;
  esac
}}
# cxsw: codex shortcut (eval built-in, activates OPENAI_API_KEY and refreshes the custom Codex provider config)
cxsw() {{ eval "$(python3 "$_CCSW_PY" codex "$@")"; }}
# gcsw: gemini shortcut (eval built-in, activates GEMINI_API_KEY)
gcsw() {{ eval "$(python3 "$_CCSW_PY" gemini "$@")"; }}
# opsw: opencode shortcut (eval built-in, activates OPENCODE_CONFIG)
opsw() {{ eval "$(python3 "$_CCSW_PY" opencode "$@")"; }}
# clawsw: openclaw shortcut (eval built-in, activates OPENCLAW_CONFIG_PATH)
clawsw() {{ eval "$(python3 "$_CCSW_PY" openclaw "$@")"; }}
# ccswitch: backward-compatible full pass-through
ccswitch() {{ python3 "$_CCSW_PY" "$@"; }}
# ccsw - load active Gemini API key
[ -f "{ccswitch_dir}/active.env" ] && source "{ccswitch_dir}/active.env"
# ccsw - load active Codex API key and clear legacy base URL env
[ -f "{ccswitch_dir}/codex.env" ] && source "{ccswitch_dir}/codex.env"
# ccsw - load active OpenCode overlay
[ -f "{ccswitch_dir}/opencode.env" ] && source "{ccswitch_dir}/opencode.env"
# ccsw - load active OpenClaw overlay
[ -f "{ccswitch_dir}/openclaw.env" ] && source "{ccswitch_dir}/openclaw.env"
{managed_end}
"""

print(
    template.format(
        managed_start=os.environ["BOOTSTRAP_MANAGED_START"],
        marker=os.environ["BOOTSTRAP_MARKER"],
        ccsw_py=os.environ["BOOTSTRAP_CCSW_PY_QUOTED"],
        ccswitch_dir=os.environ["BOOTSTRAP_CCSWITCH_DIR"],
        managed_end=os.environ["BOOTSTRAP_MANAGED_END"],
    ),
    end="",
)
PYEOF
)"

WRAPPER_STATUS="$(
    BOOTSTRAP_RC="$RC_FILE" \
    BOOTSTRAP_BLOCK="$WRAPPER_BLOCK" \
    BOOTSTRAP_MARKER="$MARKER" \
    BOOTSTRAP_MANAGED_START="$MANAGED_START" \
    BOOTSTRAP_MANAGED_END="$MANAGED_END" \
    BOOTSTRAP_APPLY="$([[ "$DRY_RUN" == "1" ]] && echo 0 || echo 1)" \
    python3 <<'PYEOF'
import os
import pathlib
import re

rc = pathlib.Path(os.environ["BOOTSTRAP_RC"])
block = os.environ["BOOTSTRAP_BLOCK"]
marker = os.environ["BOOTSTRAP_MARKER"]
managed_start = os.environ["BOOTSTRAP_MANAGED_START"]
managed_end = os.environ["BOOTSTRAP_MANAGED_END"]
apply_changes = os.environ["BOOTSTRAP_APPLY"] == "1"

block_text = block if block.endswith("\n") else block + "\n"
existing = rc.read_text() if rc.exists() else ""
managed_pattern = re.compile(
    rf"(?ms)^{re.escape(managed_start)}\n.*?^{re.escape(managed_end)}\n?"
)
legacy_patterns = [
    re.compile(rf"(?m)^{re.escape(marker)}\n?"),
    re.compile(r'(?m)^unalias ccsw 2>/dev/null \|\| true\n?'),
    re.compile(r'(?m)^_CCSW_PY=.*\n?'),
    re.compile(r'(?ms)^ccsw\(\) \{\n.*?^}\n?'),
    re.compile(r'(?m)^cxsw\(\) \{.*\}\n?'),
    re.compile(r'(?m)^gcsw\(\) \{.*\}\n?'),
    re.compile(r'(?m)^opsw\(\) \{.*\}\n?'),
    re.compile(r'(?m)^clawsw\(\) \{.*\}\n?'),
    re.compile(r'(?m)^ccswitch\(\) \{.*\}\n?'),
    re.compile(r'(?m)^# ccsw - load active Gemini API key\n?'),
    re.compile(r'(?m)^# ccsw - load active Codex API key and clear legacy base URL env\n?'),
    re.compile(r'(?m)^# ccsw - load active OpenCode overlay\n?'),
    re.compile(r'(?m)^# ccsw - load active OpenClaw overlay\n?'),
    re.compile(r'(?m)^#? ?\[ -f ".*?/active\.env" \] && source ".*?/active\.env"\n?'),
    re.compile(r'(?m)^#? ?\[ -f ".*?/codex\.env" \] && source ".*?/codex\.env"\n?'),
    re.compile(r'(?m)^#? ?\[ -f ".*?/opencode\.env" \] && source ".*?/opencode\.env"\n?'),
    re.compile(r'(?m)^#? ?\[ -f ".*?/openclaw\.env" \] && source ".*?/openclaw\.env"\n?'),
]
starts = []
if any(pattern.search(existing) for pattern in legacy_patterns):
    for pattern in legacy_patterns:
        starts.extend(match.start() for match in pattern.finditer(existing))

def compose(before: str, block_value: str, after: str) -> str:
    parts = []
    stripped_before = before.rstrip("\n")
    stripped_after = after.lstrip("\n")
    if stripped_before:
        parts.append(stripped_before)
    parts.append(block_value.rstrip("\n"))
    if stripped_after:
        parts.append(stripped_after)
    return "\n\n".join(parts) + "\n"

def strip_legacy_env_lines(text: str) -> str:
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped in {
            "# ccsw - load active Gemini API key",
            "# ccsw - load active Codex API key and clear legacy base URL env",
            "# ccsw - load active OpenCode overlay",
            "# ccsw - load active OpenClaw overlay",
        }:
            continue
        if any(token in line for token in ("active.env", "codex.env", "opencode.env", "openclaw.env")) and "source" in line:
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)
    if text.endswith("\n"):
        cleaned += "\n"
    return cleaned

managed_match = managed_pattern.search(existing)
if managed_match:
    sentinel = "__CCSW_MANAGED_BLOCK__"
    tagged = existing[:managed_match.start()] + sentinel + existing[managed_match.end():]
    cleaned_tagged = tagged
    for pattern in legacy_patterns:
        cleaned_tagged = pattern.sub("", cleaned_tagged)
    before, after = cleaned_tagged.split(sentinel, 1)
    before = strip_legacy_env_lines(before)
    after = strip_legacy_env_lines(after)
    updated = compose(before, block_text, after)
elif starts:
    insert_at = min(starts)
    sentinel = "__CCSW_MANAGED_BLOCK__"
    tagged = existing[:insert_at] + sentinel + existing[insert_at:]
    cleaned_tagged = tagged
    for pattern in legacy_patterns:
        cleaned_tagged = pattern.sub("", cleaned_tagged)
    before, after = cleaned_tagged.split(sentinel, 1)
    before = strip_legacy_env_lines(before)
    after = strip_legacy_env_lines(after)
    updated = compose(before, block_text, after)
else:
    updated = compose(strip_legacy_env_lines(existing), block_text, "")

status = "skip" if updated == existing else "updated" if (managed_match or starts) else "installed"
if apply_changes and status != "skip":
    rc.write_text(updated)
print(status)
PYEOF
)"

case "$WRAPPER_STATUS" in
    skip)
        echo "[skip] ccsw functions already up-to-date in $RC_FILE"
        ;;
    updated)
        if [[ "$DRY_RUN" == "1" ]]; then
            note_action "Would rewrite managed wrapper block in $RC_FILE"
        else
            echo "[updated] Rewrote ccsw wrapper block in $RC_FILE"
        fi
        ;;
    installed)
        if [[ "$DRY_RUN" == "1" ]]; then
            note_action "Would append managed wrapper block to $RC_FILE"
        else
            echo "[ok]   Added ccsw/cxsw/gcsw/opsw/clawsw functions to $RC_FILE"
        fi
        ;;
    *)
        echo "[error] Unexpected wrapper status: $WRAPPER_STATUS" >&2
        exit 1
        ;;
esac

echo ""
if [[ "$DRY_RUN" == "1" ]]; then
    echo "Dry-run complete! No files were written."
else
    echo "Installation complete!"
fi
echo ""
echo "Reload your shell:"
echo "  source $RC_FILE"
echo ""
echo "Quick start (after you configure at least one provider):"
echo "  ccsw list                         # List available providers"
echo "  ccsw show                         # Show active provider per tool"
echo "  ccsw <provider>                   # Switch Claude Code (short form)"
echo "  ccsw claude <provider>            # Switch Claude Code (explicit)"
echo "  cxsw <provider>                   # Switch Codex"
echo "  gcsw <provider>                   # Switch Gemini"
echo "  opsw <provider>                   # Switch OpenCode"
echo "  clawsw <provider>                 # Switch OpenClaw"
echo "  ccsw all <provider>               # Switch all configured tools"
echo "  ccsw settings get                 # Show config-dir overrides"
echo "  ccsw settings set codex_config_dir ~/.codex-alt"
echo "  ccsw import current codex saved   # Save current live Codex config as a provider"
echo "                                   # Default import keeps only matching env refs; use --allow-literal-secrets to override"
echo "  ccsw import current opencode saved # Import active OpenCode config + non-sensitive metadata"
echo "                                   # OpenCode auth fallback now follows opencode_config_dir as well"
echo "  ccsw import current openclaw saved # Import active OpenClaw overlay + controlled metadata"
echo "  ccsw doctor all                   # Safe doctor: one result per tool + runtime lease diagnostics"
echo "                                   # On a fresh install with no active provider, 'inactive' is expected"
echo "  ccsw doctor codex saved --deep    # Optional deeper Codex HTTP Responses compatibility probe"
echo "  ccsw doctor codex saved --json    # Stable NDJSON payload for automation, including runtime_lease_check"
echo "  ccsw doctor codex saved --cached  # Read the latest probe cache only"
echo "  ccsw doctor codex saved --clear-cache --json"
echo "  ccsw profile add work --codex primary,backup"
echo "  ccsw profile use work             # Strict fail-closed multi-tool switch; empty profiles are rejected"
echo "  ccsw history --tool codex --failed-only"
echo "                                   # Includes failed rollback/repair/batch results, not only non-zero subprocess exits"
echo "  ccsw history --tool codex --action rollback-result"
echo "  ccsw rollback codex               # Fail closed on live drift; records rollback-result"
echo "  ccsw repair codex                 # Replay restore/cleanup from a stale runtime lease; malformed manifests fail closed"
echo "  ccsw settings set openclaw_config_dir ~/.openclaw-alt"
echo "  ccsw run codex work -- codex exec 'hello'"
echo "                                   # Locked managed-restore execution with persisted lease/manifest; still not full isolate"
echo "  ccsw run openclaw work -- openclaw run"
echo "                                   # OpenClaw uses a per-run temp overlay and does not rewrite the persistent generated overlay"
echo "  ccsw add myprovider               # Add new provider (interactive)"
echo "                                   # New secrets should use \$ENV_VAR / .env.local by default"
echo "                                   # Snapshot sync failure now exits without emitting shell exports"
echo ""
echo "bootstrap.sh auto-configures zsh/bash rc files. For other POSIX-compatible shells, source the generated env files manually."
echo "For fish, PowerShell, or nushell, call python3 ccsw.py directly and bridge env vars in your shell profile."
