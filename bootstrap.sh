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

# ── Inject smart function block ───────────────────────────────────────────────
# Marker used to detect existing installation (do not change)
MARKER="# ccsw - smart provider switcher"

if grep -qF '_CCSW_PY=' "$RC_FILE" 2>/dev/null && grep -qF 'ccsw() {' "$RC_FILE" 2>/dev/null; then
    echo "[skip] ccsw functions already present in $RC_FILE"
else
    {
        printf '\n%s\n' "$MARKER"
        # Remove old simple alias if present (idempotent on fresh installs)
        printf 'unalias ccsw 2>/dev/null || true\n'
        # Store resolved path in a variable so functions survive directory changes
        printf '_CCSW_PY=%q\n' "$CCSW_PY"
        # ccsw: smart wrapper — omitting the tool name defaults to 'claude'
        #   ccsw 88code          -> ccsw claude 88code
        #   ccsw claude 88code   -> ccsw claude 88code  (explicit)
        #   ccsw list / show / add / ...  -> pass-through
        #   ccsw --help / -h / ""         -> pass-through to python3 (shows top-level help)
        printf 'ccsw() {\n'
        printf '  case "${1:-}" in\n'
        printf '    ""|--help|-h|help|-*)\n'
        printf '      python3 "$_CCSW_PY" "$@" ;;\n'
        printf '    claude|codex|gemini|all|list|show|add|remove|alias)\n'
        printf '      python3 "$_CCSW_PY" "$@" ;;\n'
        printf '    *)\n'
        printf '      python3 "$_CCSW_PY" claude "$@" ;;\n'
        printf '  esac\n'
        printf '}\n'
        # cxsw: shortcut for codex switching (eval activates OPENAI env vars immediately)
        printf 'cxsw() { eval "$(python3 "$_CCSW_PY" codex "$@")"; }\n'
        # gcsw: shortcut for gemini switching (use with eval for env activation)
        printf 'gcsw() { python3 "$_CCSW_PY" gemini "$@"; }\n'
        # ccswitch: backward-compatible full pass-through function (quote-safe)
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
echo "  eval \"\$(gcsw myprovider)\"        # Switch Gemini (activates env var)"
echo "  eval \"\$(ccsw all 88code)\"        # Switch all tools"
echo "  ccsw add myprovider               # Add new provider (interactive)"
