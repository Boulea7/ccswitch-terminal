#!/usr/bin/env bash
# bootstrap.sh - Install ccsw smart shell functions

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CCSW_PY="$SCRIPT_DIR/ccsw.py"
CCSWITCH_DIR="$HOME/.ccswitch"

# Detect rc file
if [[ "${SHELL:-}" == */zsh ]]; then
    RC_FILE="$HOME/.zshrc"
elif [[ "${SHELL:-}" == */bash ]]; then
    RC_FILE="$HOME/.bashrc"
else
    CURRENT_SHELL="$(ps -p $$ -o comm= 2>/dev/null || echo "")"
    if [[ "$CURRENT_SHELL" == *zsh* ]]; then
        RC_FILE="$HOME/.zshrc"
    else
        RC_FILE="$HOME/.bashrc"
    fi
fi

# Verify ccsw.py exists
if [[ ! -f "$CCSW_PY" ]]; then
    echo "[error] ccsw.py not found at: $CCSW_PY" >&2
    exit 1
fi

# Verify python3 is available
if ! command -v python3 &>/dev/null; then
    echo "[error] python3 not found. Please install Python 3.8+." >&2
    exit 1
fi

mkdir -p "$CCSWITCH_DIR"
chmod +x "$CCSW_PY"

# ── Inject / upgrade smart function block ─────────────────────────────────────
# Up-to-date marker: gcsw has eval built-in (v2+)
MARKER="# ccsw - smart provider switcher"

if grep -qF 'gcsw() { eval' "$RC_FILE" 2>/dev/null; then
    echo "[skip] ccsw functions already up-to-date in $RC_FILE"
elif grep -qF '_CCSW_PY=' "$RC_FILE" 2>/dev/null; then
    # Old installation found — patch gcsw and ccsw in-place
    UPGRADE_RC="$RC_FILE" python3 <<'PYEOF'
import os, pathlib

rc = pathlib.Path(os.environ["UPGRADE_RC"])
text = rc.read_text()

# Patch 1: gcsw — add eval wrapper
text = text.replace(
    'gcsw() { python3 "$_CCSW_PY" gemini "$@"; }',
    'gcsw() { eval "$(python3 "$_CCSW_PY" gemini "$@")"; }'
)

# Patch 2: ccsw — split gemini|all into its own eval branch
old_branch = (
    '    claude|codex|gemini|all|list|show|add|remove|alias)\n'
    '      python3 "$_CCSW_PY" "$@" ;;'
)
new_branch = (
    '    gemini|all)\n'
    '      eval "$(python3 "$_CCSW_PY" "$@")" ;;\n'
    '    claude|codex|list|show|add|remove|alias)\n'
    '      python3 "$_CCSW_PY" "$@" ;;'
)
text = text.replace(old_branch, new_branch)

rc.write_text(text)
PYEOF
    echo "[updated] Upgraded gcsw and ccsw in $RC_FILE"
else
    # Fresh install — inject full function block
    {
        printf '\n%s\n' "$MARKER"
        # Remove old simple alias if present (idempotent on fresh installs)
        printf 'unalias ccsw 2>/dev/null || true\n'
        # Store resolved path so functions survive directory changes
        printf '_CCSW_PY=%q\n' "$CCSW_PY"
        # ccsw: smart wrapper — omitting the tool name defaults to 'claude'
        #   ccsw 88code        -> ccsw claude 88code
        #   ccsw gemini/all    -> eval activated automatically
        #   ccsw list/show/... -> pass-through
        printf 'ccsw() {\n'
        printf '  case "${1:-}" in\n'
        printf '    ""|--help|-h|help|-*)\n'
        printf '      python3 "$_CCSW_PY" "$@" ;;\n'
        printf '    gemini|all)\n'
        printf '      eval "$(python3 "$_CCSW_PY" "$@")" ;;\n'
        printf '    claude|codex|list|show|add|remove|alias)\n'
        printf '      python3 "$_CCSW_PY" "$@" ;;\n'
        printf '    *)\n'
        printf '      python3 "$_CCSW_PY" claude "$@" ;;\n'
        printf '  esac\n'
        printf '}\n'
        # cxsw: codex shortcut (eval built-in, activates OPENAI env vars)
        printf 'cxsw() { eval "$(python3 "$_CCSW_PY" codex "$@")"; }\n'
        # gcsw: gemini shortcut (eval built-in, activates GEMINI_API_KEY)
        printf 'gcsw() { eval "$(python3 "$_CCSW_PY" gemini "$@")"; }\n'
        # ccswitch: backward-compatible full pass-through
        printf 'ccswitch() { python3 "$_CCSW_PY" "$@"; }\n'
    } >> "$RC_FILE"
    echo "[ok]   Added ccsw/cxsw/gcsw functions to $RC_FILE"
fi

# ── Inject active.env source line ─────────────────────────────────────────────
SOURCE_LINE="[ -f \"$CCSWITCH_DIR/active.env\" ] && source \"$CCSWITCH_DIR/active.env\""

if grep -qF "$SOURCE_LINE" "$RC_FILE" 2>/dev/null; then
    echo "[skip] active.env source line already present in $RC_FILE"
else
    {
        echo ""
        echo "# ccsw - load active Gemini API key"
        echo "$SOURCE_LINE"
    } >> "$RC_FILE"
    echo "[ok]   Added active.env source line to $RC_FILE"
fi

CODEX_SOURCE_LINE="[ -f \"$CCSWITCH_DIR/codex.env\" ] && source \"$CCSWITCH_DIR/codex.env\""

if grep -qF "$CODEX_SOURCE_LINE" "$RC_FILE" 2>/dev/null; then
    echo "[skip] codex.env source line already present in $RC_FILE"
else
    {
        echo ""
        echo "# ccsw - load active Codex API key and base URL"
        echo "$CODEX_SOURCE_LINE"
    } >> "$RC_FILE"
    echo "[ok]   Added codex.env source line to $RC_FILE"
fi

echo ""
echo "Installation complete!"
echo ""
echo "Reload your shell:"
echo "  source $RC_FILE"
echo ""
echo "Quick start:"
echo "  ccsw list                         # List available providers"
echo "  ccsw 88code                       # Switch Claude Code (short form)"
echo "  ccsw claude 88code                # Switch Claude Code (explicit)"
echo "  cxsw 88code                       # Switch Codex"
echo "  gcsw myprovider                   # Switch Gemini"
echo "  ccsw all 88code                   # Switch all tools"
echo "  ccsw add myprovider               # Add new provider (interactive)"
