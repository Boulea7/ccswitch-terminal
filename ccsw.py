#!/usr/bin/env python3
"""ccsw - Claude Code / Codex / Gemini CLI unified provider switcher.

Usage:
    ccsw claude <provider>    Switch Claude Code only
    ccsw codex <provider>     Switch Codex only
    ccsw gemini <provider>    Switch Gemini CLI only
    ccsw all <provider>       Switch all tools

    ccsw list                 List providers + active status
    ccsw add <name> [flags]   Add provider (no flags = interactive)
    ccsw remove <name>        Remove provider
    ccsw show                 Show current active config per tool
    ccsw alias <alias> <provider>  Add alias

Gemini env activation (current shell):
    eval "$(ccsw gemini <provider>)"
    eval "$(ccsw all <provider>)"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# All paths support env-var overrides for isolated testing:
#   CCSW_HOME overrides the ~/.ccswitch base dir
#   CCSW_FAKE_HOME overrides the ~ used for .claude/.codex/.gemini paths
_HOME = Path(os.environ.get("CCSW_FAKE_HOME", str(Path.home())))
CCSWITCH_DIR = Path(os.environ.get("CCSW_HOME", str(_HOME / ".ccswitch")))
PROVIDERS_PATH = CCSWITCH_DIR / "providers.json"
ACTIVE_ENV_PATH = CCSWITCH_DIR / "active.env"
CODEX_ENV_PATH = CCSWITCH_DIR / "codex.env"
CLAUDE_SETTINGS = _HOME / ".claude" / "settings.json"
CODEX_AUTH = _HOME / ".codex" / "auth.json"
CODEX_CONFIG = _HOME / ".codex" / "config.toml"
GEMINI_SETTINGS = _HOME / ".gemini" / "settings.json"
LOCAL_ENV_PATH = Path(__file__).resolve().parent / ".env.local"
BACKUP_SUFFIX_FMT = "%Y%m%d-%H%M%S"
# Stable Codex provider entry managed by ccsw. The active Codex switch rewrites
# this block instead of mutating built-in provider behavior.
CODEX_PROVIDER_ID = "ccswitch_active"

# Valid shell variable name (used to validate keys in .env.local)
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Valid provider/alias name: letters, digits, underscore, dot, hyphen only
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_TOML_TABLE_RE = re.compile(r"^\s*(\[\[[^\[\]]+\]\]|\[[^\[\]]+\])\s*(?:#.*)?$")


def legacy_env_name(*parts: str) -> str:
    """Build a legacy env var name from segments."""
    return "_".join(parts)


def env_ref(*names: str) -> Dict[str, list]:
    """Store one or more env var candidates for secret resolution."""
    return {"env": [name for name in names if name]}


def _find_closing_quote(s: str, quote: str) -> int:
    """Return index of first unescaped closing quote in s, or -1 if not found."""
    i = 0
    while i < len(s):
        if quote == '"' and s[i] == '\\':
            i += 2  # skip escape sequence
            continue
        if s[i] == quote:
            return i
        i += 1
    return -1


def _consume_toml_single_line_string(line: str, start: int, quote: str) -> int:
    """Skip a TOML single-line string and return the next unread index."""
    i = start + 1
    while i < len(line):
        if quote == '"' and line[i] == '\\':
            i += 2
            continue
        if line[i] == quote:
            return i + 1
        i += 1
    return i


def _advance_toml_multiline_state(line: str, state: Optional[str]) -> Optional[str]:
    """Track whether the TOML scanner is currently inside a multiline string."""
    i = 0
    while i < len(line):
        if state == "basic":
            if line.startswith('"""', i):
                state = None
                i += 3
            else:
                i += 1
            continue
        if state == "literal":
            if line.startswith("'''", i):
                state = None
                i += 3
            else:
                i += 1
            continue

        if line[i] == "#":
            break
        if line.startswith('"""', i):
            state = "basic"
            i += 3
            continue
        if line.startswith("'''", i):
            state = "literal"
            i += 3
            continue
        if line[i] == '"':
            i = _consume_toml_single_line_string(line, i, '"')
            continue
        if line[i] == "'":
            i = _consume_toml_single_line_string(line, i, "'")
            continue
        i += 1
    return state


def _find_first_root_toml_table(lines: list[str]) -> Optional[int]:
    """Return the first root-level TOML table index, ignoring multiline strings."""
    multiline_state: Optional[str] = None
    for idx, line in enumerate(lines):
        if multiline_state is None and _TOML_TABLE_RE.match(line):
            return idx
        multiline_state = _advance_toml_multiline_state(line, multiline_state)
    return None

BUILTIN_PROVIDERS: Dict[str, Any] = {
    "88code": {
        "claude": {
            "base_url": "https://www.88code.ai/api",
            "token": env_ref(
                "CODE88_CLAUDE_TOKEN",
                legacy_env_name("CODE88", "ANTHROPIC", "AUTH", "TOKEN"),
            ),
            # null values explicitly remove zhipu-specific keys when switching
            "extra_env": {
                "API_TIMEOUT_MS": None,
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": None,
            },
        },
        "codex": {
            "base_url": "https://www.88code.ai/openai/v1",
            "token": env_ref(
                "CODE88_CODEX_TOKEN",
                legacy_env_name("CODE88", "OPENAI", "API", "KEY"),
            ),
        },
        "gemini": None,
    },
    "zhipu": {
        "claude": {
            "base_url": "https://open.bigmodel.cn/api/anthropic",
            "token": env_ref(
                "ZHIPU_CLAUDE_TOKEN",
                legacy_env_name("ZHIPU", "ANTHROPIC", "AUTH", "TOKEN"),
            ),
            "extra_env": {
                "API_TIMEOUT_MS": "3000000",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            },
        },
        "codex": None,
        "gemini": None,
    },
    "rightcode": {
        "claude": None,
        "codex": {
            "base_url": "https://right.codes/codex/v1",
            "token": env_ref(
                "RIGHTCODE_CODEX_TOKEN",
                legacy_env_name("RIGHTCODE", "API", "KEY"),
            ),
        },
        "gemini": None,
    },
    "anyrouter": {
        "claude": {
            "base_url": "https://anyrouter.top",
            "token": env_ref(
                "ANYROUTER_CLAUDE_TOKEN",
                legacy_env_name("ANYROUTER", "ANTHROPIC", "AUTH", "TOKEN"),
            ),
            "extra_env": {},
        },
        "codex": None,
        "gemini": None,
    },
}

BUILTIN_ALIASES: Dict[str, str] = {
    "88": "88code",
    "glm": "zhipu",
    "rc": "rightcode",
    "any": "anyrouter",
}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------
def resolve_token(val: Optional[Any]) -> Optional[str]:
    """Resolve env-backed token references or return literal values as-is."""
    if isinstance(val, dict):
        env_names = val.get("env")
        if isinstance(env_names, str):
            env_names = [env_names]
        if isinstance(env_names, list):
            for env_name in env_names:
                if isinstance(env_name, str) and env_name:
                    resolved = os.environ.get(env_name)
                    if resolved:
                        return resolved
        return None
    if isinstance(val, str) and val.startswith("$"):
        return os.environ.get(val[1:])
    return val if isinstance(val, str) else None


def format_secret_ref(val: Optional[Any]) -> str:
    """Display env references as-is; redact literal secrets."""
    if not val:
        return "(none)"
    if isinstance(val, dict):
        env_names = val.get("env")
        if isinstance(env_names, str):
            env_names = [env_names]
        if isinstance(env_names, list) and env_names:
            return " or ".join(f"${env_name}" for env_name in env_names if isinstance(env_name, str))
        return "<env-ref>"
    if isinstance(val, str) and val.startswith("$"):
        return val
    return "<redacted>"


def _abort_corrupt_json(path: Path, reason: str) -> None:
    """Back up corrupt file and abort with an error message."""
    bak = path.with_suffix(
        f"{path.suffix}.corrupt-{datetime.now().strftime(BACKUP_SUFFIX_FMT)}"
    )
    try:
        shutil.copy2(path, bak)
        info(f"[error] {path.name} {reason}; backed up to {bak.name}")
    except OSError:
        info(f"[error] {path.name} {reason} (backup failed)")
    sys.exit(1)


def load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file; abort with backup on parse error or invalid root type."""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        _abort_corrupt_json(path, "is not valid JSON")
        return {}  # unreachable; satisfies type checker
    if not isinstance(data, dict):
        _abort_corrupt_json(path, "root value is not a JSON object")
        return {}  # unreachable
    return data


def save_json(path: Path, data: Dict[str, Any]) -> None:
    """Atomically write JSON: temp file -> fsync -> os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def backup_file(path: Path) -> Optional[Path]:
    """Create a timestamped .bak file if path exists; return backup path or None."""
    if path.exists():
        bak = path.with_suffix(
            f"{path.suffix}.bak-{datetime.now().strftime(BACKUP_SUFFIX_FMT)}"
        )
        shutil.copy2(path, bak)
        return bak
    return None


def load_local_env() -> None:
    """Load .env.local from script directory into os.environ (skip if missing)."""
    if not LOCAL_ENV_PATH.exists():
        return
    lines = LOCAL_ENV_PATH.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, rest = line.partition("=")
        key = key.strip()
        if not _ENV_KEY_RE.match(key):
            continue
        value = rest.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            # single-line quoted value
            quote = value[0]
            value = value[1:-1]
            if quote == '"':
                value = value.replace('\\"', '"').replace('\\\\', '\\')
        elif value and value[0] in ('"', "'"):
            # multi-line quoted value: opening quote with no closing on same line
            quote = value[0]
            parts = [value[1:]]
            while i < len(lines):
                nxt = lines[i]
                i += 1
                pos = _find_closing_quote(nxt, quote)
                if pos != -1:
                    parts.append(nxt[:pos])
                    break
                parts.append(nxt)
            value = "\n".join(parts)
            if quote == '"':
                value = value.replace('\\"', '"').replace('\\\\', '\\')
        if key not in os.environ:
            os.environ[key] = value


def info(msg: str) -> None:
    """Print status message to stderr (never captured by eval)."""
    print(msg, file=sys.stderr)


def emit_env(key: str, val: str) -> None:
    """Emit shell export statement to stdout for eval consumption."""
    escaped = val.replace("'", "'\\''")
    print(f"export {key}='{escaped}'")


def emit_unset(key: str) -> None:
    """Emit shell unset statement to stdout for eval consumption."""
    print(f"unset {key}")


def save_text(path: Path, content: str) -> None:
    """Atomically write text content: temp file -> fsync -> os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def write_shell_exports(path: Path, pairs: list, unsets: Optional[list[str]] = None) -> None:
    """Atomically write shell activation statements to a file."""
    lines = [f"unset {key}\n" for key in (unsets or [])]
    lines.extend(
        f"export {k}='{v.replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n"
        for k, v in pairs
    )
    save_text(path, "".join(lines))


def _toml_string(value: str) -> str:
    """Escape a Python string as a TOML basic string literal."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def upsert_root_toml_value(path: Path, key: str, literal: str) -> None:
    """Set a root-level TOML value while preserving the rest of the file."""
    new_line = f"{key} = {literal}"
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    first_table_idx = _find_first_root_toml_table(lines)
    search_end = first_table_idx if first_table_idx is not None else len(lines)

    for idx in range(search_end):
        stripped = lines[idx].strip()
        if re.match(rf"^{re.escape(key)}\s*=", stripped):
            lines[idx] = new_line
            break
    else:
        insert_at = search_end
        if insert_at == 0:
            lines[0:0] = [new_line, ""] if lines else [new_line]
        elif first_table_idx is None:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(new_line)
        else:
            prefix = [""] if lines[insert_at - 1].strip() else []
            suffix = [""] if lines[insert_at].strip() else []
            lines[insert_at:insert_at] = prefix + [new_line] + suffix

    content = "\n".join(lines)
    if content:
        content += "\n"
    save_text(path, content)


def upsert_root_toml_string(path: Path, key: str, value: str) -> None:
    """Set a root-level TOML string value while preserving the rest of the file."""
    upsert_root_toml_value(path, key, _toml_string(value))


def upsert_root_toml_bool(path: Path, key: str, value: bool) -> None:
    """Set a root-level TOML boolean value while preserving the rest of the file."""
    upsert_root_toml_value(path, key, "true" if value else "false")


def remove_root_toml_key(path: Path, key: str) -> None:
    """Remove a root-level TOML key if present."""
    if not path.exists():
        return

    lines = path.read_text(encoding="utf-8").splitlines()
    first_table_idx = _find_first_root_toml_table(lines)
    search_end = first_table_idx if first_table_idx is not None else len(lines)
    new_lines = [
        line
        for idx, line in enumerate(lines)
        if idx >= search_end or not re.match(rf"^\s*{re.escape(key)}\s*=", line)
    ]

    content = "\n".join(new_lines)
    if content:
        content += "\n"
    save_text(path, content)


def replace_toml_table_block(path: Path, header: str, body_lines: list[str]) -> None:
    """Replace or append a TOML table block while preserving unrelated content."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    multiline_state: Optional[str] = None
    start_idx: Optional[int] = None
    end_idx: Optional[int] = None

    for idx, line in enumerate(lines):
        if multiline_state is None and line.strip() == header:
            start_idx = idx
            break
        multiline_state = _advance_toml_multiline_state(line, multiline_state)

    if start_idx is not None:
        multiline_state = None
        end_idx = len(lines)
        for idx in range(start_idx + 1, len(lines)):
            line = lines[idx]
            if multiline_state is None and _TOML_TABLE_RE.match(line):
                end_idx = idx
                break
            multiline_state = _advance_toml_multiline_state(line, multiline_state)
        del lines[start_idx:end_idx]
        while start_idx < len(lines) and not lines[start_idx].strip():
            del lines[start_idx]
        while start_idx > 0 and start_idx <= len(lines) and not lines[start_idx - 1].strip():
            del lines[start_idx - 1]
            start_idx -= 1

    if lines and lines[-1].strip():
        lines.append("")
    lines.extend([header, *body_lines])

    content = "\n".join(lines)
    if content:
        content += "\n"
    save_text(path, content)


def upsert_codex_provider_config(path: Path, provider_name: str, base_url: str) -> None:
    """Configure Codex to use a custom provider that disables websocket transport."""
    upsert_root_toml_string(path, "model_provider", CODEX_PROVIDER_ID)
    remove_root_toml_key(path, "openai_base_url")
    replace_toml_table_block(
        path,
        f"[model_providers.{CODEX_PROVIDER_ID}]",
        [
            f'name = {_toml_string(f"ccswitch: {provider_name}")}',
            f"base_url = {_toml_string(base_url)}",
            'env_key = "OPENAI_API_KEY"',
            "supports_websockets = false",
            'wire_api = "responses"',
        ],
    )


# ---------------------------------------------------------------------------
# Provider Store
# ---------------------------------------------------------------------------
def _empty_store() -> Dict[str, Any]:
    return {
        "version": 1,
        "active": {"claude": None, "codex": None, "gemini": None},
        "aliases": {},
        "providers": {},
    }


def load_store() -> Dict[str, Any]:
    """Load providers.json; return empty store structure if missing or empty."""
    data = load_json(PROVIDERS_PATH)
    if not data:
        return _empty_store()
    # Ensure required top-level keys exist
    data.setdefault("version", 1)
    data.setdefault("active", {"claude": None, "codex": None, "gemini": None})
    data.setdefault("aliases", {})
    data.setdefault("providers", {})
    return data


def save_store(store: Dict[str, Any]) -> None:
    """Persist store to providers.json."""
    CCSWITCH_DIR.mkdir(parents=True, exist_ok=True)
    save_json(PROVIDERS_PATH, store)


def ensure_defaults(store: Dict[str, Any]) -> None:
    """Seed built-in providers and aliases if not already present."""
    providers = store.setdefault("providers", {})
    aliases = store.setdefault("aliases", {})
    for name, conf in BUILTIN_PROVIDERS.items():
        if name not in providers:
            providers[name] = conf
    for alias, target in BUILTIN_ALIASES.items():
        if alias not in aliases:
            aliases[alias] = target


def resolve_alias(store: Dict[str, Any], name: str) -> str:
    """Resolve alias name to canonical provider name."""
    return store.get("aliases", {}).get(name, name)


# ---------------------------------------------------------------------------
# Provider management commands
# ---------------------------------------------------------------------------
def cmd_list(store: Dict[str, Any]) -> None:
    """List all providers with active markers."""
    active = store.get("active", {})
    providers = store.get("providers", {})
    aliases = store.get("aliases", {})

    if not providers:
        info("No providers configured. Run: ccsw add <name>")
        return

    info("Providers:")
    for name, conf in providers.items():
        tools_active = [t for t in ("claude", "codex", "gemini") if active.get(t) == name]
        suffix = f"  [active: {', '.join(tools_active)}]" if tools_active else ""
        tools_conf = [t for t in ("claude", "codex", "gemini") if conf.get(t)]
        info(f"  {name}  ({', '.join(tools_conf) or 'no tools configured'}){suffix}")

    if aliases:
        info("\nAliases:")
        for alias, target in aliases.items():
            info(f"  {alias} -> {target}")


def cmd_show(store: Dict[str, Any]) -> None:
    """Show currently active provider per tool."""
    active = store.get("active", {})
    providers = store.get("providers", {})
    for tool in ("claude", "codex", "gemini"):
        name = active.get(tool)
        if name and name in providers:
            conf = providers[name].get(tool)
            token_ref = conf.get("token") or conf.get("api_key") if conf else None
            base_url = conf.get("base_url") if conf else None
            details = []
            if base_url:
                details.append(f"url={base_url}")
            if token_ref:
                details.append(f"token={format_secret_ref(token_ref)}")
            detail_str = f"  ({', '.join(details)})" if details else ""
            info(f"[{tool}] {name}{detail_str}")
        else:
            info(f"[{tool}] (none)")


def cmd_remove(store: Dict[str, Any], name: str) -> None:
    """Remove a provider from the store."""
    canonical = resolve_alias(store, name)
    providers = store.get("providers", {})
    if canonical not in providers:
        info(f"[error] Provider '{canonical}' not found.")
        sys.exit(1)
    if canonical in BUILTIN_PROVIDERS:
        info(f"[error] Built-in provider '{canonical}' cannot be removed.")
        sys.exit(1)
    del providers[canonical]
    # Clear active pointers
    active = store.get("active", {})
    for tool in list(active):
        if active[tool] == canonical:
            active[tool] = None
    # Remove aliases pointing to this provider
    aliases = store.get("aliases", {})
    stale = [k for k, v in aliases.items() if v == canonical]
    for k in stale:
        del aliases[k]
    save_store(store)
    info(f"Removed provider: {canonical}")
    if stale:
        info(f"Removed stale aliases: {', '.join(stale)}")


def cmd_alias_add(store: Dict[str, Any], alias_name: str, target: str) -> None:
    """Create an alias pointing to a provider."""
    if not _NAME_RE.match(alias_name):
        info(f"[error] Alias name '{alias_name}' is invalid. Use only letters, digits, _, ., -")
        sys.exit(1)
    canonical = resolve_alias(store, target)
    if canonical not in store.get("providers", {}):
        info(f"[error] Target provider '{target}' not found. Run: ccsw list")
        sys.exit(1)
    store.setdefault("aliases", {})[alias_name] = canonical
    save_store(store)
    info(f"Alias added: {alias_name} -> {canonical}")


def cmd_add(store: Dict[str, Any], name: str, args: argparse.Namespace) -> None:
    """Add or update a provider (interactive if no flags given)."""
    if not _NAME_RE.match(name):
        info(f"[error] Provider name '{name}' is invalid. Use only letters, digits, _, ., -")
        sys.exit(1)
    providers = store.setdefault("providers", {})
    conf: Dict[str, Any] = providers.get(name, {})

    has_flags = any([
        args.claude_url, args.claude_token,
        args.codex_url, args.codex_token,
        args.gemini_key,
    ])

    if has_flags:
        _add_from_flags(conf, args)
    else:
        _add_interactive(name, conf)

    providers[name] = conf
    save_store(store)
    info(f"Provider '{name}' saved.")


def _add_from_flags(conf: Dict[str, Any], args: argparse.Namespace) -> None:
    if args.claude_url or args.claude_token:
        c = conf.get("claude") or {}
        if args.claude_url:
            c["base_url"] = args.claude_url
        if args.claude_token:
            c["token"] = args.claude_token
        c.setdefault("extra_env", {})
        conf["claude"] = c

    if args.codex_url or args.codex_token:
        c = conf.get("codex") or {}
        if args.codex_url:
            c["base_url"] = args.codex_url
        if args.codex_token:
            c["token"] = args.codex_token
        conf["codex"] = c

    if args.gemini_key:
        c = conf.get("gemini") or {}
        c["api_key"] = args.gemini_key
        if args.gemini_auth_type is not None:
            c["auth_type"] = args.gemini_auth_type
        conf["gemini"] = c


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"  {label}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        info("\nAborted.")
        sys.exit(1)
    return val or default


def _add_interactive(name: str, conf: Dict[str, Any]) -> None:
    info(f"Configuring provider: {name}")
    info("(Leave blank to skip a tool, use $ENV_VAR syntax for tokens)\n")

    info("[ Claude Code ]")
    claude_url = _prompt("base_url")
    claude_token = _prompt("token ($ENV_VAR or literal)")
    if claude_url or claude_token:
        c = conf.get("claude") or {}
        if claude_url:
            c["base_url"] = claude_url
        if claude_token:
            c["token"] = claude_token
        c.setdefault("extra_env", {})
        conf["claude"] = c

    info("\n[ Codex CLI ]")
    codex_url = _prompt("base_url")
    codex_token = _prompt("token ($ENV_VAR or literal)")
    if codex_url or codex_token:
        c = conf.get("codex") or {}
        if codex_url:
            c["base_url"] = codex_url
        if codex_token:
            c["token"] = codex_token
        conf["codex"] = c

    info("\n[ Gemini CLI ]")
    gemini_key = _prompt("api_key ($ENV_VAR or literal)")
    if gemini_key:
        c = conf.get("gemini") or {}
        c["api_key"] = gemini_key
        c["auth_type"] = _prompt("auth_type", "api-key")
        conf["gemini"] = c


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------
def write_claude(conf: Dict[str, Any]) -> Optional[list]:
    """Merge provider config into ~/.claude/settings.json. Returns [] on success, None on failure."""
    token = resolve_token(conf.get("token"))
    if not token:
        info(f"[claude] Skipped: token unresolved (ref: {conf.get('token')!r})")
        return None

    data = load_json(CLAUDE_SETTINGS)
    bak = backup_file(CLAUDE_SETTINGS)

    env: Dict[str, Any] = data.get("env") if isinstance(data.get("env"), dict) else {}
    env["ANTHROPIC_AUTH_TOKEN"] = token

    base_url = conf.get("base_url")
    if base_url:
        env["ANTHROPIC_BASE_URL"] = base_url
    else:
        env.pop("ANTHROPIC_BASE_URL", None)

    for k, v in (conf.get("extra_env") or {}).items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v

    data["env"] = env
    save_json(CLAUDE_SETTINGS, data)
    if bak:
        info(f"[claude] Backed up settings.json -> {bak.name}")
    info(f"[claude] Updated {CLAUDE_SETTINGS}")
    return []


def write_codex(conf: Dict[str, Any], provider_name: str) -> Optional[list]:
    """Write Codex auth.json + config.toml. Returns env pairs on success, None on failure."""
    token = resolve_token(conf.get("token"))
    base_url = conf.get("base_url")

    if not token:
        info(f"[codex] Skipped: token unresolved (ref: {conf.get('token')!r})")
        return None
    if not base_url:
        info("[codex] Skipped: base_url not configured.")
        return None

    data = load_json(CODEX_AUTH)
    auth_bak = backup_file(CODEX_AUTH)
    config_bak = backup_file(CODEX_CONFIG)

    data["OPENAI_API_KEY"] = token
    data.pop("OPENAI_BASE_URL", None)

    save_json(CODEX_AUTH, data)
    upsert_codex_provider_config(CODEX_CONFIG, provider_name, base_url)
    if auth_bak:
        info(f"[codex] Backed up auth.json -> {auth_bak.name}")
    if config_bak:
        info(f"[codex] Backed up config.toml -> {config_bak.name}")
    info(f"[codex] Updated {CODEX_AUTH}")
    info(f"[codex] Updated {CODEX_CONFIG}")

    write_shell_exports(CODEX_ENV_PATH, [("OPENAI_API_KEY", token)], unsets=["OPENAI_BASE_URL"])
    info(f"[codex] codex.env updated at {CODEX_ENV_PATH}")

    return [("OPENAI_API_KEY", token)]


def write_gemini(conf: Dict[str, Any]) -> Optional[list]:
    """Update ~/.gemini/settings.json. Returns env pairs on success, None on failure."""
    api_key = resolve_token(conf.get("api_key"))
    auth_type = conf.get("auth_type", "api-key")

    if not api_key:
        info(f"[gemini] Skipped: api_key unresolved (ref: {conf.get('api_key')!r})")
        return None

    data = load_json(GEMINI_SETTINGS)
    bak = backup_file(GEMINI_SETTINGS)

    # Guard against corrupt settings.json where security/auth are not dicts
    if not isinstance(data.get("security"), dict):
        data["security"] = {}
    if not isinstance(data["security"].get("auth"), dict):
        data["security"]["auth"] = {}
    data["security"]["auth"]["selectedType"] = auth_type

    save_json(GEMINI_SETTINGS, data)
    if bak:
        info(f"[gemini] Backed up settings.json -> {bak.name}")
    info(f"[gemini] Updated {GEMINI_SETTINGS}")

    write_shell_exports(ACTIVE_ENV_PATH, [("GEMINI_API_KEY", api_key)])
    info(f"[gemini] active.env updated at {ACTIVE_ENV_PATH}")

    return [("GEMINI_API_KEY", api_key)]


# ---------------------------------------------------------------------------
# Switch dispatch
# ---------------------------------------------------------------------------
def switch_tool(store: Dict[str, Any], tool: str, provider_name: str) -> None:
    """Switch a single tool to the named provider."""
    provider = store.get("providers", {}).get(provider_name)
    if provider is None:
        info(f"[error] Provider '{provider_name}' not found. Run: ccsw list")
        sys.exit(1)

    conf = provider.get(tool)
    if conf is None:
        info(f"[{tool}] Skipped: provider '{provider_name}' has no {tool} config.")
        return

    if tool == "claude":
        exports = write_claude(conf)
    elif tool == "codex":
        exports = write_codex(conf, provider_name)
    elif tool == "gemini":
        exports = write_gemini(conf)
    else:
        exports = None

    if exports is not None:
        store.setdefault("active", {})[tool] = provider_name
        save_store(store)
        for k, v in exports:
            emit_env(k, v)
        if tool == "codex":
            emit_unset("OPENAI_BASE_URL")
        if tool == "gemini":
            info("[gemini] Tip: use eval \"$(ccsw gemini <provider>)\" to activate in current shell")


def cmd_switch(store: Dict[str, Any], tool: str, provider_name: str) -> None:
    """Resolve alias and dispatch switch for one tool or all."""
    canonical = resolve_alias(store, provider_name)
    if tool == "all":
        for t in ("claude", "codex", "gemini"):
            switch_tool(store, t, canonical)
    else:
        switch_tool(store, tool, canonical)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ccsw",
        description="Switch Claude Code / Codex / Gemini CLI providers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  ccsw claude 88code\n"
            "  eval \"$(ccsw all 88code)\"\n"
            "  ccsw add myprovider --claude-url https://... --claude-token $MY_TOKEN\n"
            "  ccsw add myprovider                 (interactive)\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    for tool in ("claude", "codex", "gemini", "all"):
        sp = sub.add_parser(tool, help=f"Switch {tool} provider")
        sp.add_argument("provider", help="Provider name or alias")

    sub.add_parser("list", help="List providers with active status")
    sub.add_parser("show", help="Show active config per tool")

    add_p = sub.add_parser("add", help="Add or update a provider")
    add_p.add_argument("name", help="Provider name")
    add_p.add_argument("--claude-url", metavar="URL")
    add_p.add_argument("--claude-token", metavar="TOKEN", help="$ENV_VAR or literal")
    add_p.add_argument("--codex-url", metavar="URL")
    add_p.add_argument("--codex-token", metavar="TOKEN", help="$ENV_VAR or literal")
    add_p.add_argument("--gemini-key", metavar="KEY", help="$ENV_VAR or literal")
    add_p.add_argument("--gemini-auth-type", metavar="TYPE", default=None)

    rm_p = sub.add_parser("remove", help="Remove a provider")
    rm_p.add_argument("name")

    al_p = sub.add_parser("alias", help="Add a provider alias")
    al_p.add_argument("alias")
    al_p.add_argument("provider")

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    load_local_env()
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help(sys.stderr)
        sys.exit(1)

    store = load_store()
    ensure_defaults(store)

    if args.command in ("claude", "codex", "gemini", "all"):
        cmd_switch(store, args.command, args.provider)
    elif args.command == "list":
        cmd_list(store)
    elif args.command == "show":
        cmd_show(store)
    elif args.command == "add":
        cmd_add(store, args.name, args)
    elif args.command == "remove":
        cmd_remove(store, args.name)
    elif args.command == "alias":
        cmd_alias_add(store, args.alias, args.provider)


if __name__ == "__main__":
    main()
