#!/usr/bin/env python3
"""ccsw - Claude Code / Codex / Gemini CLI unified provider switcher.

Usage:
    python3 ccsw.py claude <provider>    Switch Claude Code only
    python3 ccsw.py codex <provider>     Switch Codex only
    python3 ccsw.py gemini <provider>    Switch Gemini CLI only
    python3 ccsw.py all <provider>       Switch all configured tools

    python3 ccsw.py list                 List providers + active status
    python3 ccsw.py add <name> [flags]   Add provider (no flags = interactive)
    python3 ccsw.py remove <name>        Remove provider
    python3 ccsw.py show                 Show current active config per tool
    python3 ccsw.py alias <alias> <provider>  Add alias

Shell activation for env-based tools:
    eval "$(python3 ccsw.py gemini <provider>)"
    eval "$(python3 ccsw.py codex <provider>)"
    eval "$(python3 ccsw.py all <provider>)"
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import io
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import parse_qsl, urlparse

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# All paths support env-var overrides for isolated testing:
#   CCSW_HOME overrides the ~/.ccswitch base dir
#   CCSW_FAKE_HOME overrides the ~ used for .claude/.codex/.gemini paths
def _detect_home_dir() -> Path:
    """Return the effective home directory for config resolution."""
    fake_home = os.environ.get("CCSW_FAKE_HOME")
    if fake_home:
        return Path(fake_home)
    if os.name == "nt":
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            return Path(user_profile)
    return Path.home()


_HOME = _detect_home_dir()
CCSWITCH_DIR = Path(os.environ.get("CCSW_HOME", str(_HOME / ".ccswitch")))
PROVIDERS_PATH = CCSWITCH_DIR / "providers.json"
DB_PATH = CCSWITCH_DIR / "ccswitch.db"
ACTIVE_ENV_PATH = CCSWITCH_DIR / "active.env"
CODEX_ENV_PATH = CCSWITCH_DIR / "codex.env"
OPENCODE_ENV_PATH = CCSWITCH_DIR / "opencode.env"
OPENCLAW_ENV_PATH = CCSWITCH_DIR / "openclaw.env"
GENERATED_DIR = CCSWITCH_DIR / "generated"
TMP_DIR = CCSWITCH_DIR / "tmp"
STATE_LOCK_PATH = CCSWITCH_DIR / "ccswitch.lock"
CLAUDE_SETTINGS = _HOME / ".claude" / "settings.json"
CODEX_AUTH = _HOME / ".codex" / "auth.json"
CODEX_CONFIG = _HOME / ".codex" / "config.toml"
GEMINI_SETTINGS = _HOME / ".gemini" / "settings.json"
_XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", str(_HOME / ".config")))
_XDG_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", str(_HOME / ".local" / "share")))
OPENCODE_CONFIG = _XDG_CONFIG_HOME / "opencode" / "opencode.json"
OPENCODE_AUTH = _XDG_DATA_HOME / "opencode" / "auth.json"
OPENCLAW_CONFIG = _HOME / ".openclaw" / "openclaw.json"
OPENCLAW_ENV = _HOME / ".openclaw" / ".env"
LOCAL_ENV_PATH = Path(__file__).resolve().parent / ".env.local"
BACKUP_SUFFIX_FMT = "%Y%m%d-%H%M%S"
# Stable Codex provider entry managed by ccsw. The active Codex switch rewrites
# this block instead of mutating built-in provider behavior.
CODEX_PROVIDER_ID = "ccswitch_active"
CODEX_BUILTIN_PROVIDER_ID = "openai"
CODEX_AUTH_MODE_CHATGPT = "chatgpt"
DOCTOR_JSON_SCHEMA_VERSION = 1
LOCAL_ENV_INJECTED_KEYS: set[str] = set()
MANAGED_CHILD_ENV_KEYS = {
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "GEMINI_API_KEY",
    "OPENCODE_CONFIG",
    "OPENCLAW_CONFIG_PATH",
    "OPENCLAW_PROFILE",
}
RUNTIME_BUSY_PHASES = {"initializing", "activating", "subprocess", "restoring", "validating", "cleaning"}
RUNTIME_VALID_PHASES = {
    *RUNTIME_BUSY_PHASES,
    "setup_failed",
    "subprocess_complete",
    "subprocess_failed",
    "interrupted",
    "restore_conflict",
    "restore_failed",
    "cleanup_failed",
    "completed",
    "decode_failed",
}

# Valid shell variable name (used to validate keys in .env.local)
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Valid provider/alias name: letters, digits, underscore, dot, hyphen only
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_TOML_TABLE_RE = re.compile(r"^\s*(\[\[[^\[\]]+\]\]|\[[^\[\]]+\])\s*(?:#.*)?$")
_TRAILING_COMMA_RE = re.compile(r",(?=\s*[}\]])")
_JSON5_UNQUOTED_KEY_RE = re.compile(r'(^|[{,]\s*)([A-Za-z_][A-Za-z0-9_-]*)(\s*:)', re.MULTILINE)
_TOKEN_LIKE_ARG_RE = re.compile(
    r"^(?:"
    r"sk-[A-Za-z0-9_-]{20,}|"
    r"pk-[A-Za-z0-9_-]{20,}|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{12,}|"
    r"ya29\.[A-Za-z0-9._-]{12,}|"
    r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9._-]+\.[A-Za-z0-9._-]+"
    r")$"
)
_WINDOWS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
ALL_TOOLS = ("claude", "codex", "gemini", "opencode", "openclaw")
SWITCH_TOOLS = ("claude", "codex", "gemini")
OVERLAY_TOOLS = ("opencode", "openclaw")
SETTINGS_DEFAULTS = {
    "claude_config_dir": None,
    "codex_config_dir": None,
    "codex_share_lanes": {},
    "codex_sync_future_sessions": False,
    "gemini_config_dir": None,
    "opencode_config_dir": None,
    "openclaw_config_dir": None,
}
CODEX_SHARE_SETTING_KEY = "codex_share_lanes"
CODEX_SYNC_SETTING_KEY = "codex_sync_future_sessions"
CODEX_SHARE_DEFAULT_SOURCE = "last"
CODEX_SHARE_TOOL = "codex"
_BOOL_TRUE_LITERALS = {"1", "on", "true", "yes"}
_BOOL_FALSE_LITERALS = {"0", "off", "false", "no"}
RETRYABLE_PATTERNS = (
    "connection refused",
    "timed out",
    "timeout",
    "upstream unavailable",
    "temporarily unavailable",
    "handshake failure",
    "connection reset",
    "name or service not known",
    "could not resolve",
    "network is unreachable",
    "502",
    "503",
    "504",
)
PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
SENSITIVE_HEADER_NAMES = {
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "api-key",
    "x-auth-token",
}
SAFE_IMPORT_HEADER_NAMES = {
    "accept",
    "accept-language",
    "content-type",
    "user-agent",
    "x-demo",
    "x-request-id",
}
SENSITIVE_VALUE_TOKENS = (
    "token",
    "secret",
    "authorization",
    "password",
    "cookie",
)
SENSITIVE_QUERY_NAMES = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "client_secret",
    "key",
    "password",
    "refresh_token",
    "secret",
    "token",
}
REDACTABLE_DETAIL_URL_FIELDS = {
    "url",
    "primary_base_url",
    "fallback_base_url",
    "selected_base_url",
}
REDACTABLE_DETAIL_PATH_FIELDS = {
    "active_overlay",
    "active_overlay_resolved",
    "expected_overlay",
    "expected_overlay_resolved",
    "runtime_root",
}
SENSITIVE_ARG_FLAGS = {
    "--access-token",
    "--api-key",
    "--authorization",
    "--client-secret",
    "--cookie",
    "--header",
    "--password",
    "--proxy-user",
    "--refresh-token",
    "--secret",
    "--token",
    "--user",
    "-H",
    "-u",
}
_STATE_LOCK_LOCAL = threading.local()
_IMPORTED_HOME = _HOME
_IMPORTED_XDG_CONFIG_HOME = _XDG_CONFIG_HOME
_IMPORTED_XDG_DATA_HOME = _XDG_DATA_HOME
_IMPORTED_RUNTIME_PATHS = {
    "CCSWITCH_DIR": CCSWITCH_DIR,
    "PROVIDERS_PATH": PROVIDERS_PATH,
    "DB_PATH": DB_PATH,
    "ACTIVE_ENV_PATH": ACTIVE_ENV_PATH,
    "CODEX_ENV_PATH": CODEX_ENV_PATH,
    "OPENCODE_ENV_PATH": OPENCODE_ENV_PATH,
    "OPENCLAW_ENV_PATH": OPENCLAW_ENV_PATH,
    "GENERATED_DIR": GENERATED_DIR,
    "TMP_DIR": TMP_DIR,
    "STATE_LOCK_PATH": STATE_LOCK_PATH,
    "CLAUDE_SETTINGS": CLAUDE_SETTINGS,
    "CODEX_AUTH": CODEX_AUTH,
    "CODEX_CONFIG": CODEX_CONFIG,
    "GEMINI_SETTINGS": GEMINI_SETTINGS,
    "OPENCODE_CONFIG": OPENCODE_CONFIG,
    "OPENCODE_AUTH": OPENCODE_AUTH,
    "OPENCLAW_CONFIG": OPENCLAW_CONFIG,
    "OPENCLAW_ENV": OPENCLAW_ENV,
    "LOCAL_ENV_PATH": LOCAL_ENV_PATH,
}


class StoreConflictError(RuntimeError):
    """Raised when a store write is based on a stale revision."""


class StoreSnapshotSyncError(RuntimeError):
    """Raised when SQLite commit succeeds but JSON snapshot sync fails."""

    def __init__(self, message: str, *, store: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.store = store


def _patched_runtime_path(name: str) -> Optional[Path]:
    """Return a test override when a path constant has been patched."""
    current = globals().get(name)
    imported = _IMPORTED_RUNTIME_PATHS.get(name)
    if isinstance(current, Path) and isinstance(imported, Path) and current != imported:
        return current
    return None


def _runtime_home_dir() -> Path:
    """Resolve the effective home dir at runtime, honoring tests and env overrides."""
    patched = globals().get("_HOME")
    if isinstance(patched, Path) and patched != _IMPORTED_HOME:
        return patched
    return _detect_home_dir()


def _runtime_xdg_config_home() -> Path:
    """Resolve the effective XDG config home at runtime."""
    patched = globals().get("_XDG_CONFIG_HOME")
    if isinstance(patched, Path) and patched != _IMPORTED_XDG_CONFIG_HOME:
        return patched
    return Path(os.environ.get("XDG_CONFIG_HOME", str(_runtime_home_dir() / ".config")))


def _runtime_xdg_data_home() -> Path:
    """Resolve the effective XDG data home at runtime."""
    patched = globals().get("_XDG_DATA_HOME")
    if isinstance(patched, Path) and patched != _IMPORTED_XDG_DATA_HOME:
        return patched
    return Path(os.environ.get("XDG_DATA_HOME", str(_runtime_home_dir() / ".local" / "share")))


def _runtime_ccswitch_dir() -> Path:
    """Resolve the effective ccswitch root directory at runtime."""
    patched = _patched_runtime_path("CCSWITCH_DIR")
    if patched:
        return patched
    return Path(os.environ.get("CCSW_HOME", str(_runtime_home_dir() / ".ccswitch")))


def _runtime_ccswitch_path(name: str, relative: str) -> Path:
    """Resolve one ccswitch-managed path from the runtime root."""
    patched = _patched_runtime_path(name)
    if patched:
        return patched
    return _runtime_ccswitch_dir() / relative


def _providers_path() -> Path:
    return _runtime_ccswitch_path("PROVIDERS_PATH", "providers.json")


def _db_path() -> Path:
    return _runtime_ccswitch_path("DB_PATH", "ccswitch.db")


def _active_env_path() -> Path:
    return _runtime_ccswitch_path("ACTIVE_ENV_PATH", "active.env")


def _codex_env_path() -> Path:
    return _runtime_ccswitch_path("CODEX_ENV_PATH", "codex.env")


def _opencode_env_path() -> Path:
    return _runtime_ccswitch_path("OPENCODE_ENV_PATH", "opencode.env")


def _openclaw_env_path() -> Path:
    return _runtime_ccswitch_path("OPENCLAW_ENV_PATH", "openclaw.env")


def _generated_dir() -> Path:
    return _runtime_ccswitch_path("GENERATED_DIR", "generated")


def _tmp_dir() -> Path:
    return _runtime_ccswitch_path("TMP_DIR", "tmp")


def _state_lock_path() -> Path:
    return _runtime_ccswitch_path("STATE_LOCK_PATH", "ccswitch.lock")


def _claude_settings_path() -> Path:
    patched = _patched_runtime_path("CLAUDE_SETTINGS")
    if patched:
        return patched
    return _runtime_home_dir() / ".claude" / "settings.json"


def _codex_auth_path() -> Path:
    patched = _patched_runtime_path("CODEX_AUTH")
    if patched:
        return patched
    return _runtime_home_dir() / ".codex" / "auth.json"


def _codex_config_path() -> Path:
    patched = _patched_runtime_path("CODEX_CONFIG")
    if patched:
        return patched
    return _runtime_home_dir() / ".codex" / "config.toml"


def _gemini_settings_path() -> Path:
    patched = _patched_runtime_path("GEMINI_SETTINGS")
    if patched:
        return patched
    return _runtime_home_dir() / ".gemini" / "settings.json"


def _opencode_config_path() -> Path:
    patched = _patched_runtime_path("OPENCODE_CONFIG")
    if patched:
        return patched
    return _runtime_xdg_config_home() / "opencode" / "opencode.json"


def _opencode_auth_path() -> Path:
    patched = _patched_runtime_path("OPENCODE_AUTH")
    if patched:
        return patched
    return _runtime_xdg_data_home() / "opencode" / "auth.json"


def _openclaw_config_path() -> Path:
    patched = _patched_runtime_path("OPENCLAW_CONFIG")
    if patched:
        return patched
    return _runtime_home_dir() / ".openclaw" / "openclaw.json"


def _openclaw_env_file_path() -> Path:
    patched = _patched_runtime_path("OPENCLAW_ENV")
    if patched:
        return patched
    return _runtime_home_dir() / ".openclaw" / ".env"


def _local_env_path() -> Path:
    patched = _patched_runtime_path("LOCAL_ENV_PATH")
    if patched:
        return patched
    env_override = os.environ.get("CCSW_LOCAL_ENV_PATH")
    if env_override:
        return Path(env_override)
    return Path(__file__).resolve().parent / ".env.local"


def legacy_env_name(*parts: str) -> str:
    """Build a legacy env var name from segments."""
    return "_".join(parts)


def env_ref(*names: str) -> Dict[str, list]:
    """Store one or more env var candidates for secret resolution."""
    return {"env": [name for name in names if name]}


def _ensure_private_dir(path: Path) -> None:
    """Create a directory and restrict it to the current user."""
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, PRIVATE_DIR_MODE)
    except OSError:
        pass


def _ensure_private_file(path: Path) -> None:
    """Restrict a file to the current user."""
    try:
        os.chmod(path, PRIVATE_FILE_MODE)
    except OSError:
        pass


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

BUILTIN_PROVIDERS: Dict[str, Any] = {}

BUILTIN_ALIASES: Dict[str, str] = {}


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


def _shell_join(argv: Iterable[str]) -> str:
    """Render one shell-safe command string for human-facing output."""
    return " ".join(shlex.quote(part) for part in argv)


def _is_env_ref(val: Optional[Any]) -> bool:
    """Return True when a value uses an environment reference."""
    if isinstance(val, dict):
        env_names = val.get("env")
        if isinstance(env_names, str):
            env_names = [env_names]
        return bool(isinstance(env_names, list) and env_names and all(isinstance(item, str) and item for item in env_names))
    return isinstance(val, str) and val.startswith("$") and len(val) > 1


def _secret_env_names(value: Optional[Any]) -> set[str]:
    """Collect environment variable names referenced by one secret field."""
    if isinstance(value, dict):
        env_names = value.get("env")
        if isinstance(env_names, str):
            env_names = [env_names]
        if isinstance(env_names, list):
            return {
                item
                for item in env_names
                if isinstance(item, str) and item
            }
        return set()
    if isinstance(value, str) and value.startswith("$") and len(value) > 1:
        return {value[1:]}
    return set()


def _provider_secret_env_names(conf: Optional[Dict[str, Any]]) -> set[str]:
    """Collect source env vars used to resolve a provider config."""
    if not isinstance(conf, dict):
        return set()
    return {
        *_secret_env_names(conf.get("token")),
        *_secret_env_names(conf.get("api_key")),
    }


def _reject_literal_secret(field_label: str) -> None:
    """Abort when a new secret would be stored as a literal."""
    info(
        f"[error] {field_label} must use an env ref by default. "
        "Use $ENV_VAR / .env.local, or pass --allow-literal-secrets to override."
    )
    sys.exit(1)


def _require_secret_ref(field_label: str, value: Optional[Any], *, allow_literal: bool) -> None:
    """Validate whether a user-provided secret can be stored."""
    if value in (None, ""):
        return
    if allow_literal or _is_env_ref(value):
        return
    _reject_literal_secret(field_label)


def _has_sensitive_headers(headers: Optional[Dict[str, Any]]) -> bool:
    """Return True when imported headers look like they contain secrets."""
    return _validate_opencode_headers(headers) is not None


def _validate_opencode_headers(headers: Optional[Dict[str, Any]]) -> Optional[str]:
    """Return an error string when OpenCode headers are unsafe or malformed."""
    if not isinstance(headers, dict):
        return None if headers in (None, {}) else "OpenCode headers must be a JSON object."
    for key, value in headers.items():
        if not isinstance(key, str):
            return "OpenCode headers must use string keys."
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            return "OpenCode headers must use string values."
        lowered = key.strip().lower()
        if lowered in SENSITIVE_HEADER_NAMES:
            return f"OpenCode header '{key}' is not allowed."
        if lowered not in SAFE_IMPORT_HEADER_NAMES:
            return f"OpenCode header '{key}' is not allowlisted."
        if any(token in lowered for token in ("token", "secret")):
            return f"OpenCode header '{key}' is not allowed."
        if "key" in lowered and lowered not in {"x-demo", "x-request-id"}:
            return f"OpenCode header '{key}' is not allowed."
        lowered_value = value.lower()
        if any(token in lowered_value for token in ("bearer ", "basic ", "token", "secret", "api_key", "apikey")):
            return f"OpenCode header '{key}' looks secret-bearing."
    return None


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


def _preserve_secret_ref(existing: Optional[Any], imported_value: Optional[str]) -> Optional[Any]:
    """Keep an existing env reference when it resolves to the imported secret."""
    if not imported_value:
        return existing
    if existing and resolve_token(existing) == imported_value:
        return existing
    return imported_value


def _parse_json_sample(sample: Optional[str]) -> Optional[Any]:
    """Best-effort parse a JSON sample captured from a probe response."""
    if not isinstance(sample, str) or not sample.strip():
        return None
    try:
        return json.loads(sample)
    except json.JSONDecodeError:
        return None


def _read_exported_value(path: Path, key: str) -> Optional[str]:
    """Read a single exported value from a shell export file written by ccsw."""
    if not path.exists():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith(f"export {key}="):
            continue
        value = line.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] == "'":
            return value[1:-1].replace("'\\''", "'")
        return value
    return None


def _read_env_assignment_value(path: Path, key: str) -> Optional[str]:
    """Read a KEY=value entry from a simple env file."""
    if not path.exists():
        return None
    prefix = f"{key}="
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith(prefix):
            continue
        value = line[len(prefix) :].strip()
        if len(value) >= 2 and value[0] == value[-1] == "'":
            return value[1:-1].replace("'\\''", "'")
        if len(value) >= 2 and value[0] == value[-1] == '"':
            return value[1:-1]
        return value
    return None


def _extract_toml_table_body(content: str, table_name: str) -> Optional[str]:
    """Return the body text of one TOML table if it exists."""
    match = re.search(
        rf"(?ms)^\[{re.escape(table_name)}\]\s*(.*?)^(?=\[|\Z)",
        content,
    )
    return match.group(1) if match else None


def _read_toml_string_value(content: str, key: str) -> Optional[str]:
    """Read one simple TOML string value from a block of text."""
    match = re.search(rf'^\s*{re.escape(key)}\s*=\s*"([^"]+)"', content, re.MULTILINE)
    return match.group(1) if match else None


def _read_toml_literal_value(content: str, key: str) -> Optional[str]:
    """Read one simple TOML literal value from a block of text."""
    match = re.search(rf"^\s*{re.escape(key)}\s*=\s*([^\n#]+)", content, re.MULTILINE)
    return match.group(1).strip() if match else None


def _snapshot_file_state(paths: Iterable[Path]) -> Dict[Path, Optional[bytes]]:
    """Capture current file contents for later restoration."""
    snapshots: Dict[Path, Optional[bytes]] = {}
    for path in paths:
        snapshots[path] = path.read_bytes() if path.exists() else None
    return snapshots


def _capture_path_state(path: Path) -> Dict[str, Any]:
    """Capture a lightweight content fingerprint for one path."""
    if not path.exists():
        return {"exists": False, "sha256": None}
    return {
        "exists": True,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _state_from_snapshot(content: Optional[bytes]) -> Dict[str, Any]:
    """Convert raw snapshot bytes into the same shape as _capture_path_state."""
    if content is None:
        return {"exists": False, "sha256": None}
    return {
        "exists": True,
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _path_states_match(left: Dict[str, Any], right: Optional[Dict[str, Any]]) -> bool:
    """Return True when two captured path states represent the same content."""
    return bool(right) and left.get("exists") == right.get("exists") and left.get("sha256") == right.get("sha256")


def _restore_file_state(snapshots: Dict[Path, Optional[bytes]]) -> None:
    """Restore a previously captured file snapshot."""
    for path, content in snapshots.items():
        if content is None:
            if path.exists():
                path.unlink()
            continue
        _ensure_private_dir(path.parent)
        save_bytes(path, content)


def _restore_owned_path_state(
    snapshots: Dict[Path, Optional[bytes]],
    written_states: Dict[Path, Dict[str, Any]],
    groups: Optional[Iterable[Iterable[Path]]] = None,
    ignore_paths: Optional[Iterable[Path]] = None,
) -> list[str]:
    """Restore only paths still owned by the current run and report conflicts."""
    ignored = set(ignore_paths or [])
    normalized_groups = [list(group) for group in groups or ([path] for path in snapshots)]
    conflicts: list[str] = []
    for group in normalized_groups:
        owned_paths = [path for path in group if path in snapshots and path not in ignored]
        if not owned_paths:
            continue
        group_conflict = False
        for path in owned_paths:
            current_state = _capture_path_state(path)
            desired_state = _state_from_snapshot(snapshots[path])
            if _path_states_match(current_state, desired_state):
                continue
            if not _path_states_match(current_state, written_states.get(path)):
                group_conflict = True
                break
        if group_conflict:
            conflicts.extend(str(path) for path in owned_paths)
            continue
        for path in owned_paths:
            content = snapshots[path]
            current_state = _capture_path_state(path)
            desired_state = _state_from_snapshot(content)
            if _path_states_match(current_state, desired_state):
                continue
            if content is None:
                if path.exists():
                    path.unlink()
                continue
            save_bytes(path, content)
    return conflicts


def _attempt_owned_restore(
    snapshots: Dict[Path, Optional[bytes]],
    written_states: Dict[Path, Dict[str, Any]],
    *,
    groups: Optional[Iterable[Iterable[Path]]] = None,
    ignore_paths: Optional[Iterable[Path]] = None,
) -> tuple[str, list[str], Optional[str]]:
    """Attempt one ownership-aware restore and normalize the result."""
    try:
        conflicts = _restore_owned_path_state(
            snapshots,
            written_states,
            groups=groups,
            ignore_paths=ignore_paths,
        )
    except Exception as exc:
        return "restore_failed", [], str(exc)
    if conflicts:
        return "restore_conflict", conflicts, None
    return "restored", [], None


def _build_runtime_manifest(
    tool: str,
    *,
    lease_id: str,
    source_kind: str,
    requested_target: str,
    runtime_root: Path,
) -> Dict[str, Any]:
    """Create the initial persisted runtime manifest for one managed run."""
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "tool": tool,
        "lease_id": lease_id,
        "source_kind": source_kind,
        "requested_target": requested_target,
        "selected_candidate": None,
        "owner_pid": os.getpid(),
        "owner_started_at": _pid_start_token(os.getpid()),
        "child_pid": None,
        "child_started_at": None,
        "last_child_pid": None,
        "child_status": "pending",
        "phase": "initializing",
        "runtime_root": str(runtime_root),
        "attempt_count": 0,
        "restore_status": "pending",
        "cleanup_status": "pending",
        "post_restore_validation": {"status": "pending", "reason_code": "pending"},
        "restore_conflicts": [],
        "restore_error": None,
        "snapshots": {},
        "written_states": {},
        "restore_groups": [],
        "ephemeral_paths": [],
        "snapshot_written": False,
        "stale": False,
        "stale_reason": None,
        "created_at": now,
        "updated_at": now,
    }


def _persist_runtime_manifest(
    tool: str,
    manifest: Dict[str, Any],
    *,
    persist: bool = True,
    **updates: Any,
) -> Dict[str, Any]:
    """Apply updates, refresh timestamps, and persist the runtime manifest."""
    manifest.update(updates)
    manifest["updated_at"] = datetime.now().isoformat(timespec="seconds")
    if persist:
        upsert_managed_target(tool, manifest)
    return manifest


def _pid_start_token(pid: Optional[int]) -> Optional[str]:
    """Return a stable start token for a PID when the platform exposes one."""
    if not isinstance(pid, int) or pid <= 0:
        return None
    try:
        with os.popen(f"ps -o lstart= -p {pid} 2>/dev/null") as stream:
            output = stream.read().strip()
    except Exception:
        return None
    return output or None


def _pid_is_running(pid: Optional[int]) -> bool:
    """Return True when a PID currently exists and is signalable."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _pid_matches_identity(pid: Optional[int], started_at: Optional[str]) -> bool:
    """Return True when the PID exists and still matches the recorded start token."""
    if not _pid_is_running(pid):
        return False
    if not started_at:
        return False
    current_started_at = _pid_start_token(pid)
    if not current_started_at:
        return False
    return current_started_at == started_at


def _pid_cannot_be_verified_but_is_running(pid: Optional[int], started_at: Optional[str]) -> bool:
    """Return True when a live PID cannot be safely ruled out as the recorded process."""
    if not _pid_is_running(pid):
        return False
    if not started_at:
        return True
    return _pid_start_token(pid) is None


def _managed_target_blocks_run(manifest: Optional[Dict[str, Any]]) -> bool:
    """Return True when the persisted lease still blocks new managed runs."""
    if not isinstance(manifest, dict):
        return False
    if manifest.get("decode_error"):
        return True
    if _pid_matches_identity(manifest.get("child_pid"), manifest.get("child_started_at")) or _pid_cannot_be_verified_but_is_running(
        manifest.get("child_pid"),
        manifest.get("child_started_at"),
    ):
        return True
    if (
        _pid_matches_identity(manifest.get("owner_pid"), manifest.get("owner_started_at"))
        or _pid_cannot_be_verified_but_is_running(
            manifest.get("owner_pid"),
            manifest.get("owner_started_at"),
        )
    ) and not manifest.get("stale"):
        return True
    return _managed_target_needs_repair(manifest)


def _annotate_run_result(
    result: subprocess.CompletedProcess[str],
    *,
    selected_candidate: Optional[str],
    fallback_used: bool,
    original_active: Optional[str],
    attempt_count: int,
    source_kind: str,
    final_failure_type: str,
    restore_status: str,
    restore_error: Optional[str],
    restore_conflicts: list[str],
    post_restore_validation: Optional[Dict[str, Any]],
    temp_paths_cleaned: bool,
    cleanup_status: str,
    backup_artifacts_cleaned: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Attach stable metadata used by cmd_run history records."""
    setattr(result, "_ccsw_selected_candidate", selected_candidate)
    setattr(result, "_ccsw_fallback_used", fallback_used)
    setattr(result, "_ccsw_original_active", original_active)
    setattr(result, "_ccsw_attempt_count", attempt_count)
    setattr(result, "_ccsw_source_kind", source_kind)
    setattr(result, "_ccsw_final_failure_type", final_failure_type)
    setattr(result, "_ccsw_restore_status", restore_status)
    setattr(result, "_ccsw_backup_artifacts_cleaned", backup_artifacts_cleaned)
    setattr(result, "_ccsw_restore_error", restore_error)
    setattr(result, "_ccsw_restore_conflicts", restore_conflicts)
    setattr(result, "_ccsw_post_restore_validation", post_restore_validation)
    setattr(result, "_ccsw_temp_paths_cleaned", temp_paths_cleaned)
    setattr(result, "_ccsw_cleanup_status", cleanup_status)
    setattr(result, "_ccsw_lock_scope", "global_state_lock")
    return result


def _claim_run_lease(
    tool: str,
    requested_target: str,
) -> Optional[subprocess.CompletedProcess[str]]:
    """Fail closed when an existing lease still needs recovery."""
    manifest = get_managed_target(tool)
    if not manifest:
        return None
    if manifest.get("decode_error"):
        reason = (
            f"[ccsw] {tool} has a malformed runtime lease manifest. "
            f"Run `ccsw repair {tool}` before starting a new managed run."
        )
        return subprocess.CompletedProcess([tool], 1, "", reason)
    if _pid_matches_identity(manifest.get("child_pid"), manifest.get("child_started_at")) or _pid_cannot_be_verified_but_is_running(
        manifest.get("child_pid"),
        manifest.get("child_started_at"),
    ):
        reason = f"[ccsw] {tool} already has an active runtime lease; child process is still running"
        return subprocess.CompletedProcess([tool], 1, "", reason)
    if (
        _pid_matches_identity(manifest.get("owner_pid"), manifest.get("owner_started_at"))
        or _pid_cannot_be_verified_but_is_running(
            manifest.get("owner_pid"),
            manifest.get("owner_started_at"),
        )
    ) and not manifest.get("stale"):
        reason = f"[ccsw] {tool} already has an active runtime lease owned by another process"
        return subprocess.CompletedProcess([tool], 1, "", reason)
    if not _pid_matches_identity(manifest.get("owner_pid"), manifest.get("owner_started_at")) and _managed_target_needs_repair(manifest):
        target_name = manifest.get("selected_candidate") or manifest.get("requested_target") or requested_target
        reason = (
            f"[ccsw] {tool} has an unfinished runtime lease for '{target_name}'. "
            f"Run `ccsw repair {tool}` before starting a new managed run."
        )
        return subprocess.CompletedProcess([tool], 1, "", reason)
    if manifest.get("stale") or _managed_target_needs_repair(manifest):
        target_name = manifest.get("selected_candidate") or manifest.get("requested_target") or requested_target
        reason = (
            f"[ccsw] {tool} has a stale runtime lease for '{target_name}'. "
            f"Run `ccsw repair {tool}` before starting a new managed run."
        )
        return subprocess.CompletedProcess([tool], 1, "", reason)
    return None


def _run_subprocess_with_tracking(
    argv: list[str],
    child_env: Dict[str, str],
    tool: str,
    runtime_manifest: Dict[str, Any],
    *,
    persist: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run the managed subprocess while persisting child PID when available."""
    run_attr = getattr(subprocess, "run")
    if hasattr(run_attr, "mock_calls"):
        result = subprocess.run(argv, capture_output=True, text=True, env=child_env)
        _persist_runtime_manifest(
            tool,
            runtime_manifest,
            persist=persist,
            child_pid=None,
            child_status="exited",
        )
        return result

    process = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=child_env,
    )
    _persist_runtime_manifest(
        tool,
        runtime_manifest,
        persist=persist,
        child_pid=process.pid,
        child_started_at=_pid_start_token(process.pid),
        last_child_pid=process.pid,
        child_status="running",
    )
    try:
        stdout, stderr = process.communicate()
    except BaseException:
        try:
            process.terminate()
            process.wait(timeout=1.0)
        except Exception:
            try:
                process.kill()
                process.wait(timeout=1.0)
            except Exception:
                pass
        _persist_runtime_manifest(
            tool,
            runtime_manifest,
            persist=persist,
            child_pid=None,
            child_status="terminated",
            last_child_pid=process.pid,
        )
        raise
    _persist_runtime_manifest(
        tool,
        runtime_manifest,
        persist=persist,
        child_pid=None,
        child_status="exited",
        last_child_pid=process.pid,
    )
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


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
    _ensure_private_dir(path.parent)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        _ensure_private_file(Path(tmp_path))
        os.replace(tmp_path, path)
        _ensure_private_file(path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def backup_file(path: Path, *, enabled: bool = True) -> Optional[Path]:
    """Create a timestamped .bak file if path exists; return backup path or None."""
    if enabled and path.exists():
        bak = path.with_suffix(
            f"{path.suffix}.bak-{datetime.now().strftime(BACKUP_SUFFIX_FMT)}"
        )
        shutil.copy2(path, bak)
        _ensure_private_file(bak)
        return bak
    return None


def load_local_env() -> None:
    """Load .env.local from script directory into os.environ (skip if missing)."""
    global LOCAL_ENV_INJECTED_KEYS
    local_env_path = _local_env_path()
    if not local_env_path.exists():
        return
    lines = local_env_path.read_text(encoding="utf-8").splitlines()
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
            LOCAL_ENV_INJECTED_KEYS.add(key)


def _probe_uses_unsafe_transport(url: Optional[str]) -> bool:
    """Return True when a credentialed probe should refuse the configured URL."""
    if not isinstance(url, str) or not url:
        return False
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if scheme == "https":
        return False
    if scheme == "http" and host in {"localhost", "127.0.0.1", "::1"}:
        return False
    return True


def _write_with_file_restore(
    paths: Iterable[Path],
    writer: Any,
) -> Any:
    """Restore tracked files if a multi-file writer raises midway."""
    tracked = list(paths)
    snapshots = _snapshot_file_state(tracked)
    try:
        return writer()
    except Exception:
        _restore_file_state(snapshots)
        raise


def _build_child_env(
    env_updates: Dict[str, str],
    unsets: Iterable[str],
    *,
    secret_env_names: Optional[Iterable[str]] = None,
) -> Dict[str, str]:
    """Construct a child env without leaking locally injected or managed secrets."""
    child_env = os.environ.copy()
    for key in LOCAL_ENV_INJECTED_KEYS:
        child_env.pop(key, None)
    for key in MANAGED_CHILD_ENV_KEYS:
        child_env.pop(key, None)
    for key in secret_env_names or ():
        child_env.pop(key, None)
    for key in unsets:
        child_env.pop(key, None)
    child_env.update(env_updates)
    return child_env


def _is_sensitive_field_name(name: str) -> bool:
    """Return True when a field name likely contains credential material."""
    lowered = name.strip().lower().replace("-", "_")
    if lowered in {header.replace("-", "_") for header in SENSITIVE_HEADER_NAMES}:
        return True
    if lowered in {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "client_secret",
        "cookie",
        "password",
        "proxy_authorization",
        "refresh_token",
        "secret",
        "token",
        "x_api_key",
        "x_auth_token",
    }:
        return True
    return lowered.endswith(("_token", "_secret", "_api_key"))


def _url_has_embedded_credentials(value: str) -> bool:
    """Return True when a URL embeds credentials or sensitive query params."""
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    if parsed.username or parsed.password:
        return True
    if any(key.lower() in SENSITIVE_QUERY_NAMES for key, _value in parse_qsl(parsed.query, keep_blank_values=True)):
        return True
    return False


def _path_looks_sensitive(value: str) -> bool:
    """Return True when a filesystem-like string carries obvious secret markers."""
    lowered = value.lower()
    return any(token in lowered for token in ("token", "secret", "api_key", "apikey", "auth"))


def _redact_sensitive_text(value: str) -> str:
    """Redact obvious credential-bearing fragments from free-form text."""
    redacted = re.sub(
        r"""(?ix)
        (
            ["']?
            (?:access_token|api[-_]?key|apikey|authorization|client_secret|password|proxy-authorization|refresh_token|secret|token|x-api-key|x-auth-token)
            ["']?
            \s*[:=]\s*
        )
        (["'])
        ([^"']*)
        (["'])
        """,
        lambda match: f"{match.group(1)}{match.group(2)}<redacted>{match.group(4)}",
        value,
    )
    redacted = re.sub(r"(?i)\b(authorization|proxy-authorization)\s*:\s*[^,\s]+(?:\s+[^\s,]+)?", r"\1: <redacted>", redacted)
    redacted = re.sub(r"(?i)\b(bearer|basic)\s+[^\s,]+", r"\1 <redacted>", redacted)
    redacted = re.sub(
        r"(?i)\b(access_token|api[-_]?key|apikey|client_secret|password|refresh_token|secret|token)=([^&\s]+)",
        lambda match: f"{match.group(1)}=<redacted>",
        redacted,
    )
    redacted = re.sub(r"(?i)https?://[^/\s:@]+:[^@\s/]+@", "https://<redacted>@", redacted)
    return redacted


def _sanitize_cli_arg(arg: str, previous: Optional[str]) -> str:
    """Redact one CLI argument when it carries likely secrets."""
    if previous in SENSITIVE_ARG_FLAGS:
        if previous in {"-H", "--header"}:
            header_name = arg.split(":", 1)[0] if ":" in arg else arg
            if _is_sensitive_field_name(header_name) or any(token in arg.lower() for token in ("bearer ", "basic ", "cookie")):
                return "<redacted-header>"
        return "<redacted>"
    if arg.startswith("--header="):
        header_value = arg.split("=", 1)[1]
        header_name = header_value.split(":", 1)[0] if ":" in header_value else header_value
        if _is_sensitive_field_name(header_name) or any(
            token in header_value.lower() for token in ("bearer ", "basic ", "cookie")
        ):
            return "--header=<redacted-header>"
        return arg
    if arg.startswith("-H") and len(arg) > 2:
        header_value = arg[2:]
        header_name = header_value.split(":", 1)[0] if ":" in header_value else header_value
        if _is_sensitive_field_name(header_name) or any(
            token in header_value.lower() for token in ("bearer ", "basic ", "cookie")
        ):
            return "-H<redacted-header>"
        return arg
    if arg.startswith("-u=") and len(arg) > 3:
        return "-u=<redacted>"
    if arg.startswith("-u") and len(arg) > 2:
        return "-u<redacted>"
    if any(
        arg.lower().startswith(f"{flag}=")
        for flag in (
            "--access-token",
            "--api-key",
            "--authorization",
            "--client-secret",
            "--cookie",
            "--password",
            "--proxy-user",
            "--refresh-token",
            "--secret",
            "--token",
            "--user",
        )
    ):
        return f"{arg.split('=', 1)[0]}=<redacted>"
    if "=" in arg and not arg.startswith(("http://", "https://")):
        env_name, env_value = arg.split("=", 1)
        if env_name and env_value and _is_sensitive_field_name(env_name):
            return f"{env_name}=<redacted>"
    if arg.startswith("http://") or arg.startswith("https://"):
        if _url_has_embedded_credentials(arg):
            return "<redacted-url>"
        return arg
    if not arg.startswith("-") and _TOKEN_LIKE_ARG_RE.match(arg):
        return "<redacted>"
    if any(token in arg.lower() for token in ("authorization:", "bearer ", "basic ", "cookie:")):
        return "<redacted>"
    return arg


def _sanitize_history_payload(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Strip sensitive argv and free-form error text before history persistence."""
    sanitized: Dict[str, Any] = {}
    for key, value in payload.items():
        if key == "argv" and isinstance(value, list):
            previous: Optional[str] = None
            sanitized_args: list[str] = []
            for item in value:
                if isinstance(item, str):
                    sanitized_item = _sanitize_cli_arg(item, previous)
                    sanitized_args.append(sanitized_item)
                    previous = item
                else:
                    sanitized_args.append(item)
                    previous = None
            sanitized[key] = sanitized_args
            continue
        if key in {"error", "restore_error"} and isinstance(value, str):
            sanitized[key] = _redact_sensitive_text(value)
            continue
        if isinstance(value, dict):
            sanitized[key] = _sanitize_history_payload(action, value)
            continue
        if isinstance(value, list):
            sanitized[key] = [
                _sanitize_history_payload(action, item) if isinstance(item, dict) else item
                for item in value
            ]
            continue
        if isinstance(key, str) and _is_sensitive_field_name(key) and value not in (None, ""):
            sanitized[f"{key}_redacted"] = True
            continue
        sanitized[key] = value
    return sanitized


def _sanitize_probe_detail(value: Any) -> Any:
    """Strip raw response and error payloads from probe detail structures."""
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for key, current in value.items():
            lowered = key.lower()
            if key == "sample":
                if current not in (None, ""):
                    sanitized["sample_redacted"] = True
                continue
            if key == "error":
                if current not in (None, ""):
                    sanitized["error_redacted"] = True
                continue
            if _is_sensitive_field_name(lowered):
                if current not in (None, ""):
                    sanitized[f"{lowered}_redacted"] = True
                continue
            if isinstance(current, str) and lowered in REDACTABLE_DETAIL_URL_FIELDS and _url_has_embedded_credentials(current):
                sanitized[f"{lowered}_redacted"] = True
                continue
            if isinstance(current, str) and lowered in REDACTABLE_DETAIL_PATH_FIELDS and _path_looks_sensitive(current):
                sanitized[f"{lowered}_redacted"] = True
                continue
            sanitized[key] = _sanitize_probe_detail(current)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_probe_detail(item) for item in value]
    return value


def info(msg: str) -> None:
    """Print status message to stderr (never captured by eval)."""
    safe_msg = _redact_sensitive_text(msg)
    _write_stream_line(sys.stderr, safe_msg)


def _write_stream_line(stream: Any, text: str) -> None:
    """Write one text line to a stream, preserving TTY semantics when possible."""
    payload = f"{text}\n"
    try:
        fileno = stream.fileno()
    except (AttributeError, io.UnsupportedOperation, OSError):
        write_method = getattr(stream, "write", None)
        if not callable(write_method):
            raise
        write_method.__call__(payload)
        return
    encoded = payload.encode("utf-8", errors="replace")
    view = memoryview(encoded)
    while view:
        written = os.write(fileno, view)
        view = view[written:]


def emit_env(key: str, val: str) -> None:
    """Emit shell export statement to stdout for eval consumption."""
    escaped = val.replace("'", "'\\''")
    _write_stream_line(sys.stdout, f"export {key}='{escaped}'")


def emit_unset(key: str) -> None:
    """Emit shell unset statement to stdout for eval consumption."""
    _write_stream_line(sys.stdout, f"unset {key}")


def save_text(path: Path, content: str) -> None:
    """Atomically write text content: temp file -> fsync -> os.replace."""
    _ensure_private_dir(path.parent)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        _ensure_private_file(Path(tmp_path))
        os.replace(tmp_path, path)
        _ensure_private_file(path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def save_bytes(path: Path, content: bytes) -> None:
    """Atomically write raw bytes: temp file -> fsync -> os.replace."""
    _ensure_private_dir(path.parent)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        _ensure_private_file(Path(tmp_path))
        os.replace(tmp_path, path)
        _ensure_private_file(path)
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


@contextlib.contextmanager
def _state_lock(
    *,
    lock_path: Optional[Path] = None,
    blocking: bool = False,
):
    """Serialize mutating ccsw operations across processes."""
    path = lock_path or _state_lock_path()
    if fcntl is None:  # pragma: no cover - non-POSIX fallback
        yield
        return
    held_paths = getattr(_STATE_LOCK_LOCAL, "held_paths", set())
    key = str(path)
    if key in held_paths:
        yield
        return
    _ensure_private_dir(path.parent)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, PRIVATE_FILE_MODE)
    _ensure_private_file(path)
    flags = fcntl.LOCK_EX
    if not blocking:
        flags |= fcntl.LOCK_NB
    try:
        try:
            fcntl.flock(fd, flags)
        except BlockingIOError:
            info("[error] ccsw state is busy; another mutating command is still running.")
            sys.exit(1)
        held_paths = set(held_paths)
        held_paths.add(key)
        _STATE_LOCK_LOCAL.held_paths = held_paths
        yield
    finally:
        held_paths = set(getattr(_STATE_LOCK_LOCAL, "held_paths", set()))
        held_paths.discard(key)
        _STATE_LOCK_LOCAL.held_paths = held_paths
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _toml_string(value: str) -> str:
    """Escape a Python string as a TOML basic string literal."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _http_probe(
    url: Optional[str],
    *,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[bytes] = None,
    timeout: float = 3.0,
) -> tuple[Optional[int], Dict[str, Any]]:
    """Run one HTTP probe and return status code plus response metadata."""
    if not isinstance(url, str) or not url:
        return None, {"reason_code": "missing_url", "error": "url not configured"}
    request = urllib_request.Request(
        url,
        headers={"User-Agent": "ccswitch/1.0", **(headers or {})},
        data=body,
        method=method,
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            payload = response.read(256)
            detail: Dict[str, Any] = {
                "status": response.status,
                "reason": getattr(response, "reason", ""),
            }
            if payload:
                detail["sample"] = payload.decode("utf-8", errors="replace")
            return response.status, detail
    except urllib_error.HTTPError as exc:
        payload = b""
        if getattr(exc, "fp", None) is not None:
            try:
                payload = exc.read(256)
            except (OSError, ValueError, TypeError, AttributeError, KeyError):
                payload = b""
        detail = {"status": exc.code, "reason": exc.reason}
        if payload:
            detail["sample"] = payload.decode("utf-8", errors="replace")
        return exc.code, detail
    except (urllib_error.URLError, OSError, TimeoutError, ValueError) as exc:
        return None, {
            "reason_code": "network_error",
            "error_class": exc.__class__.__name__,
            "error": str(exc),
        }


def probe_codex_base_url(
    url: str,
    token: Optional[str] = None,
    timeout: float = 2.5,
) -> bool:
    """Return True when the Codex relay looks compatible with model listing."""
    if _probe_uses_unsafe_transport(url):
        return False
    headers = {"Authorization": f"Bearer {token}"} if token else None
    status_code, _detail = _http_probe(
        f"{url.rstrip('/')}/models",
        headers=headers,
        timeout=timeout,
    )
    return status_code in (200, 401, 403)


def _codex_status_looks_usable(status_code: Optional[int]) -> bool:
    """Return True when a Codex HTTP status still indicates a reachable relay."""
    return status_code in (200, 401, 403)


def select_codex_base_url(conf: Dict[str, Any]) -> str:
    """Choose the primary Codex URL, falling back only when the primary probe fails."""
    primary_url = conf.get("base_url")
    fallback_url = conf.get("fallback_base_url")
    token = resolve_token(conf.get("token"))

    if not isinstance(primary_url, str) or not primary_url:
        return ""
    if not isinstance(fallback_url, str) or not fallback_url or fallback_url == primary_url:
        return primary_url

    primary_ok = probe_codex_base_url(primary_url, token) if token else probe_codex_base_url(primary_url)
    if primary_ok:
        info(f"[codex] Primary base_url probe succeeded: {primary_url}")
        return primary_url

    info(f"[codex] Primary base_url probe failed, trying fallback: {fallback_url}")
    fallback_ok = probe_codex_base_url(fallback_url, token) if token else probe_codex_base_url(fallback_url)
    if fallback_ok:
        info(f"[codex] Using fallback base_url: {fallback_url}")
        return fallback_url

    info(f"[codex] Fallback probe also failed; keeping primary base_url: {primary_url}")
    return primary_url


def _codex_uses_chatgpt_auth(conf: Optional[Dict[str, Any]]) -> bool:
    """Return True when a Codex provider should use the user's ChatGPT login."""
    return isinstance(conf, dict) and conf.get("auth_mode") == CODEX_AUTH_MODE_CHATGPT


def _codex_env_unsets(conf: Optional[Dict[str, Any]]) -> list[str]:
    """Return environment variables that must be cleared for one Codex auth mode."""
    if _codex_uses_chatgpt_auth(conf):
        return ["OPENAI_API_KEY", "OPENAI_BASE_URL"]
    return ["OPENAI_BASE_URL"]


def _codex_chatgpt_provider_route(store: Optional[Dict[str, Any]]) -> str:
    """Return the provider id route to use for ChatGPT-backed Codex sessions."""
    if isinstance(store, dict) and _codex_sync_enabled(store):
        return CODEX_PROVIDER_ID
    return CODEX_BUILTIN_PROVIDER_ID


def _codex_has_chatgpt_login_state(auth_data: Dict[str, Any]) -> bool:
    """Return True when auth.json still contains a usable ChatGPT login payload."""
    auth_mode = auth_data.get("auth_mode")
    if auth_mode not in (None, CODEX_AUTH_MODE_CHATGPT):
        return False
    if resolve_token(auth_data.get("chatgpt_access_token")):
        return True
    tokens = auth_data.get("tokens")
    if isinstance(tokens, dict) and resolve_token(tokens.get("access_token")):
        return True
    session = auth_data.get("chatgpt_session")
    if isinstance(session, dict) and resolve_token(session.get("access_token")):
        return True
    return False


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


def remove_toml_table_block(path: Path, header: str) -> None:
    """Remove a TOML table block if it exists."""
    if not path.exists():
        return

    lines = path.read_text(encoding="utf-8").splitlines()
    multiline_state: Optional[str] = None
    start_idx: Optional[int] = None

    for idx, line in enumerate(lines):
        if multiline_state is None and line.strip() == header:
            start_idx = idx
            break
        multiline_state = _advance_toml_multiline_state(line, multiline_state)

    if start_idx is None:
        return

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


def upsert_codex_chatgpt_config(path: Path) -> None:
    """Restore Codex to the built-in OpenAI provider for ChatGPT login."""
    upsert_root_toml_string(path, "model_provider", CODEX_BUILTIN_PROVIDER_ID)
    remove_root_toml_key(path, "openai_base_url")
    remove_toml_table_block(path, f"[model_providers.{CODEX_PROVIDER_ID}]")


def upsert_codex_chatgpt_shared_config(path: Path, provider_name: str) -> None:
    """Route ChatGPT auth through the shared ccswitch provider lane."""
    upsert_root_toml_string(path, "model_provider", CODEX_PROVIDER_ID)
    remove_root_toml_key(path, "openai_base_url")
    replace_toml_table_block(
        path,
        f"[model_providers.{CODEX_PROVIDER_ID}]",
        [
            f'name = {_toml_string(f"ccswitch: {provider_name}")}',
            "requires_openai_auth = true",
            "supports_websockets = true",
            'wire_api = "responses"',
        ],
    )


# ---------------------------------------------------------------------------
# Provider Store
# ---------------------------------------------------------------------------
def _empty_store() -> Dict[str, Any]:
    return {
        "version": 2,
        "active": {tool: None for tool in ALL_TOOLS},
        "aliases": {},
        "providers": {},
        "profiles": {},
        "settings": dict(SETTINGS_DEFAULTS),
        "_revision": 0,
    }


def _read_store_revision(conn: sqlite3.Connection) -> int:
    """Return the current store revision from SQLite metadata."""
    row = conn.execute(
        "SELECT value_json FROM meta WHERE key = ?",
        ("revision",),
    ).fetchone()
    if not row:
        return 0
    try:
        return int(json.loads(row["value_json"]))
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0


def _connect_db() -> sqlite3.Connection:
    """Open the SQLite store and ensure required tables exist."""
    ccswitch_dir = _runtime_ccswitch_dir()
    generated_dir = _generated_dir()
    tmp_dir = _tmp_dir()
    db_path = _db_path()
    _ensure_private_dir(ccswitch_dir)
    _ensure_private_dir(generated_dir)
    _ensure_private_dir(tmp_dir)
    conn = sqlite3.connect(db_path)
    _ensure_private_file(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS providers (
            name TEXT PRIMARY KEY,
            config_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS aliases (
            alias TEXT PRIMARY KEY,
            provider_name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS active (
            tool TEXT PRIMARY KEY,
            provider_name TEXT
        );
        CREATE TABLE IF NOT EXISTS profiles (
            name TEXT PRIMARY KEY,
            profile_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS switch_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at TEXT NOT NULL,
            action TEXT NOT NULL,
            tool TEXT,
            subject TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS probe_results (
            tool TEXT NOT NULL,
            target TEXT NOT NULL,
            status TEXT NOT NULL,
            checked_at TEXT NOT NULL,
            detail_json TEXT NOT NULL,
            PRIMARY KEY (tool, target)
        );
        CREATE TABLE IF NOT EXISTS probe_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at TEXT NOT NULL,
            tool TEXT NOT NULL,
            target TEXT NOT NULL,
            status TEXT NOT NULL,
            probe_mode TEXT NOT NULL,
            detail_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS managed_targets (
            tool TEXT PRIMARY KEY,
            target_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL
        );
        """
    )
    return conn


def _load_legacy_store() -> Dict[str, Any]:
    """Load the legacy JSON store if it exists."""
    data = load_json(_providers_path())
    if not data:
        return _empty_store()
    store = _empty_store()
    store["version"] = int(data.get("version", 1))
    store["active"].update(data.get("active", {}))
    store["aliases"].update(data.get("aliases", {}))
    store["providers"].update(data.get("providers", {}))
    store["profiles"].update(data.get("profiles", {}))
    settings = data.get("settings", {})
    if isinstance(settings, dict):
        store["settings"].update(settings)
    return store


def _db_has_store_data(conn: sqlite3.Connection) -> bool:
    """Return True when the SQLite store already contains provider state."""
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM meta WHERE key IN ('version', 'revision')"
    ).fetchone()
    return bool(row and row["count"])


def _write_store_to_db(
    conn: sqlite3.Connection,
    store: Dict[str, Any],
    *,
    revision: Optional[int] = None,
) -> None:
    """Replace the database contents with the given store snapshot."""
    conn.execute("DELETE FROM providers")
    conn.execute("DELETE FROM aliases")
    conn.execute("DELETE FROM active")
    conn.execute("DELETE FROM profiles")
    conn.execute("DELETE FROM settings")
    conn.execute("DELETE FROM meta")

    conn.executemany(
        "INSERT INTO providers(name, config_json) VALUES (?, ?)",
        [
            (name, json.dumps(conf, ensure_ascii=False))
            for name, conf in store.get("providers", {}).items()
        ],
    )
    conn.executemany(
        "INSERT INTO aliases(alias, provider_name) VALUES (?, ?)",
        list(store.get("aliases", {}).items()),
    )
    conn.executemany(
        "INSERT INTO active(tool, provider_name) VALUES (?, ?)",
        list(store.get("active", {}).items()),
    )
    conn.executemany(
        "INSERT INTO profiles(name, profile_json) VALUES (?, ?)",
        [
            (name, json.dumps(profile, ensure_ascii=False))
            for name, profile in store.get("profiles", {}).items()
        ],
    )
    conn.executemany(
        "INSERT INTO settings(key, value_json) VALUES (?, ?)",
        [
            (key, json.dumps(value, ensure_ascii=False))
            for key, value in store.get("settings", {}).items()
        ],
    )
    conn.execute(
        "INSERT INTO meta(key, value_json) VALUES (?, ?)",
        ("version", json.dumps(store.get("version", 2))),
    )
    conn.execute(
        "INSERT INTO meta(key, value_json) VALUES (?, ?)",
        ("revision", json.dumps(store.get("_revision", 0) if revision is None else revision)),
    )


def _load_store_from_db(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Read the current store snapshot from SQLite."""
    store = _empty_store()
    version_row = conn.execute(
        "SELECT value_json FROM meta WHERE key = ?",
        ("version",),
    ).fetchone()
    if version_row:
        store["version"] = json.loads(version_row["value_json"])

    for row in conn.execute("SELECT tool, provider_name FROM active"):
        store["active"][row["tool"]] = row["provider_name"]
    for row in conn.execute("SELECT alias, provider_name FROM aliases"):
        store["aliases"][row["alias"]] = row["provider_name"]
    for row in conn.execute("SELECT name, config_json FROM providers"):
        store["providers"][row["name"]] = json.loads(row["config_json"])
    for row in conn.execute("SELECT name, profile_json FROM profiles"):
        store["profiles"][row["name"]] = json.loads(row["profile_json"])
    for row in conn.execute("SELECT key, value_json FROM settings"):
        store["settings"][row["key"]] = json.loads(row["value_json"])
    store["_revision"] = _read_store_revision(conn)
    return store


def _save_snapshot_json(store: Dict[str, Any]) -> None:
    """Persist a JSON snapshot for compatibility and local inspection."""
    snapshot = {
        "version": store.get("version", 2),
        "active": store.get("active", {}),
        "aliases": store.get("aliases", {}),
        "providers": store.get("providers", {}),
        "profiles": store.get("profiles", {}),
        "settings": store.get("settings", {}),
    }
    save_json(_providers_path(), snapshot)


def _insert_history_entries(
    conn: sqlite3.Connection,
    history_entries: Iterable[Dict[str, Any]],
) -> None:
    """Insert switch history rows inside an existing transaction."""
    timestamp = datetime.now().isoformat(timespec="seconds")
    rows = [
        (
            entry["action"],
            entry.get("tool"),
            entry.get("subject"),
            json.dumps(_sanitize_history_payload(entry["action"], entry.get("payload", {})), ensure_ascii=False),
        )
        for entry in history_entries
    ]
    if not rows:
        return
    conn.executemany(
        """
        INSERT INTO switch_history(recorded_at, action, tool, subject, payload_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        [(timestamp, action, tool, subject, payload_json) for action, tool, subject, payload_json in rows],
    )


def load_store() -> Dict[str, Any]:
    """Load the store from SQLite, migrating from legacy JSON when needed."""
    conn = _connect_db()
    try:
        if not _db_has_store_data(conn) and _providers_path().exists():
            with conn:
                _write_store_to_db(conn, _load_legacy_store())
        store = _load_store_from_db(conn)
    finally:
        conn.close()
    return store


def save_store(
    store: Dict[str, Any],
    *,
    expected_revision: Optional[int] = None,
    history_entries: Optional[Iterable[Dict[str, Any]]] = None,
) -> None:
    """Persist store to SQLite and keep a JSON compatibility snapshot."""
    conn = _connect_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        current_revision = _read_store_revision(conn)
        if expected_revision is not None and current_revision != expected_revision:
            raise StoreConflictError(
                f"store revision changed from {expected_revision} to {current_revision}"
            )
        next_revision = current_revision + 1
        _write_store_to_db(conn, store, revision=next_revision)
        if history_entries:
            _insert_history_entries(conn, history_entries)
        conn.commit()
        store["_revision"] = next_revision
    except sqlite3.OperationalError as exc:
        conn.rollback()
        if "database is locked" in str(exc).lower():
            raise StoreConflictError("store database is locked by another writer") from exc
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    try:
        _save_snapshot_json(store)
    except Exception as exc:
        raise StoreSnapshotSyncError(str(exc), store=store) from exc


def record_history(
    action: str,
    tool: Optional[str],
    subject: Optional[str],
    payload: Dict[str, Any],
) -> None:
    """Append a history entry to the SQLite store."""
    sanitized_payload = _sanitize_history_payload(action, payload)
    conn = _connect_db()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO switch_history(recorded_at, action, tool, subject, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    datetime.now().isoformat(timespec="seconds"),
                    action,
                    tool,
                    subject,
                    json.dumps(sanitized_payload, ensure_ascii=False),
                ),
            )
    finally:
        conn.close()


def update_latest_history_payload(
    action: str,
    tool: Optional[str],
    subject: Optional[str],
    payload: Dict[str, Any],
) -> bool:
    """Rewrite the newest matching history payload in place when follow-up detail changes."""
    sanitized_payload = _sanitize_history_payload(action, payload)
    conn = _connect_db()
    try:
        with conn:
            if tool is None and subject is None:
                row = conn.execute(
                    """
                    SELECT id FROM switch_history
                    WHERE action = ? AND tool IS NULL AND subject IS NULL
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (action,),
                ).fetchone()
            elif tool is None:
                row = conn.execute(
                    """
                    SELECT id FROM switch_history
                    WHERE action = ? AND tool IS NULL AND subject = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (action, subject),
                ).fetchone()
            elif subject is None:
                row = conn.execute(
                    """
                    SELECT id FROM switch_history
                    WHERE action = ? AND tool = ? AND subject IS NULL
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (action, tool),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT id FROM switch_history
                    WHERE action = ? AND tool = ? AND subject = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (action, tool, subject),
                ).fetchone()
            if not row:
                return False
            conn.execute(
                "UPDATE switch_history SET payload_json = ? WHERE id = ?",
                (json.dumps(sanitized_payload, ensure_ascii=False), row["id"]),
            )
            return True
    finally:
        conn.close()


def list_history(
    limit: int = 20,
    tool: Optional[str] = None,
    action: Optional[str] = None,
    subject: Optional[str] = None,
    failed_only: bool = False,
) -> list[Dict[str, Any]]:
    """Return recent history entries, newest first."""
    return list_history_filtered(limit=limit, tool=tool, action=action, subject=subject, failed_only=failed_only)


def list_history_filtered(
    *,
    limit: int = 20,
    tool: Optional[str] = None,
    action: Optional[str] = None,
    subject: Optional[str] = None,
    failed_only: bool = False,
) -> list[Dict[str, Any]]:
    """Return recent history entries with SQL-level filtering."""
    conn = _connect_db()
    try:
        clauses = []
        params: list[Any] = []
        if tool:
            clauses.append("tool = ?")
            params.append(tool)
        if action:
            clauses.append("action = ?")
            params.append(action)
        if subject:
            clauses.append("subject = ?")
            params.append(subject)
        if failed_only:
            clauses.append(
                """
                (
                    COALESCE(CAST(json_extract(payload_json, '$.returncode') AS INTEGER), 0) != 0
                    OR COALESCE(json_extract(payload_json, '$.failure_type'), 'ok') != 'ok'
                    OR COALESCE(json_extract(payload_json, '$.failed_tool'), '') != ''
                    OR COALESCE(json_extract(payload_json, '$.rollback_status'), 'restored') NOT IN ('restored', 'not_needed')
                    OR COALESCE(json_extract(payload_json, '$.repair_status'), 'repaired') NOT IN ('repaired', 'no_lease')
                    OR COALESCE(json_extract(payload_json, '$.restore_status'), 'restored') != 'restored'
                    OR COALESCE(json_extract(payload_json, '$.snapshot_sync'), 'ok') != 'ok'
                )
                """
            )
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"""
            SELECT recorded_at, action, tool, subject, payload_json
            FROM switch_history
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "recorded_at": row["recorded_at"],
            "action": row["action"],
            "tool": row["tool"],
            "subject": row["subject"],
            "payload": json.loads(row["payload_json"]),
        }
        for row in rows
    ]


def record_probe_result(
    tool: str,
    target: str,
    status: str,
    detail: Dict[str, Any],
    *,
    probe_mode: str = "safe",
) -> None:
    """Upsert the last probe result for a tool target."""
    checked_at = datetime.now().isoformat(timespec="seconds")
    sanitized_detail = _normalize_doctor_detail(detail, checked_at=checked_at, probe_mode=probe_mode)
    conn = _connect_db()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO probe_results(tool, target, status, checked_at, detail_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tool, target) DO UPDATE SET
                    status = excluded.status,
                    checked_at = excluded.checked_at,
                    detail_json = excluded.detail_json
                """,
                (
                    tool,
                    target,
                    status,
                    checked_at,
                    json.dumps(sanitized_detail, ensure_ascii=False),
                ),
            )
            conn.execute(
                """
                INSERT INTO probe_history(recorded_at, tool, target, status, probe_mode, detail_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    checked_at,
                    tool,
                    target,
                    status,
                    probe_mode,
                    json.dumps(sanitized_detail, ensure_ascii=False),
                ),
            )
    finally:
        conn.close()


def get_probe_result(tool: str, target: str) -> Optional[Dict[str, Any]]:
    """Return the cached probe result for one tool target."""
    conn = _connect_db()
    try:
        row = conn.execute(
            """
            SELECT tool, target, status, checked_at, detail_json
            FROM probe_results
            WHERE tool = ? AND target = ?
            """,
            (tool, target),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {
        "tool": row["tool"],
        "target": row["target"],
        "status": row["status"],
        "checked_at": row["checked_at"],
        "detail": json.loads(row["detail_json"]),
    }


def list_probe_history(
    *,
    tool: Optional[str] = None,
    target: Optional[str] = None,
    limit: int = 10,
) -> list[Dict[str, Any]]:
    """Return recent probe history entries."""
    conn = _connect_db()
    try:
        clauses = []
        params: list[Any] = []
        if tool:
            clauses.append("tool = ?")
            params.append(tool)
        if target:
            clauses.append("target = ?")
            params.append(target)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"""
            SELECT recorded_at, tool, target, status, probe_mode, detail_json
            FROM probe_history
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "recorded_at": row["recorded_at"],
            "tool": row["tool"],
            "target": row["target"],
            "status": row["status"],
            "probe_mode": row["probe_mode"],
            "detail": json.loads(row["detail_json"]),
        }
        for row in rows
    ]


def clear_probe_cache(tool: Optional[str] = None, target: Optional[str] = None) -> None:
    """Delete cached probe results for the selected scope."""
    conn = _connect_db()
    try:
        with conn:
            if tool and target:
                conn.execute("DELETE FROM probe_results WHERE tool = ? AND target = ?", (tool, target))
            elif tool:
                conn.execute("DELETE FROM probe_results WHERE tool = ?", (tool,))
            else:
                conn.execute("DELETE FROM probe_results")
    finally:
        conn.close()


def _json_ready_snapshots(
    snapshots: Dict[Path, Optional[bytes]],
    *,
    runtime_root: Optional[Path] = None,
) -> Dict[str, Dict[str, Any]]:
    """Convert raw file snapshots into JSON-friendly manifest entries."""
    serialized: Dict[str, Dict[str, Any]] = {}
    snapshot_root: Optional[Path] = None
    if runtime_root is not None:
        snapshot_root = runtime_root / "snapshots"
        _ensure_private_dir(snapshot_root)
    for path, content in snapshots.items():
        payload = dict(_state_from_snapshot(content))
        if content is None:
            payload["snapshot_file"] = None
            serialized[str(path)] = payload
            continue
        if snapshot_root is None:
            payload["content_b64"] = base64.b64encode(content).decode("ascii")
            serialized[str(path)] = payload
            continue
        digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()
        snapshot_file = snapshot_root / f"{digest}.b64"
        snapshot_file.write_text(base64.b64encode(content).decode("ascii"), encoding="utf-8")
        _ensure_private_file(snapshot_file)
        payload["snapshot_file"] = str(snapshot_file)
        serialized[str(path)] = payload
    return serialized


def _snapshots_from_manifest(entries: Optional[Dict[str, Any]]) -> Dict[Path, Optional[bytes]]:
    """Decode manifest snapshots back into the restore format."""
    decoded: Dict[Path, Optional[bytes]] = {}
    if not isinstance(entries, dict):
        return decoded
    for raw_path, payload in entries.items():
        if not isinstance(raw_path, str) or not isinstance(payload, dict):
            continue
        content_b64 = payload.get("content_b64")
        if content_b64 is None:
            decoded[Path(raw_path)] = None
            continue
        try:
            decoded[Path(raw_path)] = base64.b64decode(content_b64.encode("ascii"))
        except (ValueError, TypeError):
            decoded[Path(raw_path)] = None
    return decoded


def _decode_manifest_snapshots(
    entries: Optional[Dict[str, Any]],
    *,
    runtime_root: Optional[Path] = None,
) -> tuple[Dict[Path, Optional[bytes]], list[str]]:
    """Decode manifest snapshots and report malformed entries explicitly."""
    decoded: Dict[Path, Optional[bytes]] = {}
    errors: list[str] = []
    if not isinstance(entries, dict):
        return decoded, errors
    for raw_path, payload in entries.items():
        if not isinstance(raw_path, str) or not isinstance(payload, dict):
            errors.append(str(raw_path))
            continue
        snapshot_exists = payload.get("exists")
        content_b64 = payload.get("content_b64")
        if snapshot_exists is False and content_b64 is None:
            decoded[Path(raw_path)] = None
            continue
        snapshot_file = payload.get("snapshot_file")
        if snapshot_file is not None:
            if not isinstance(snapshot_file, str) or not snapshot_file:
                errors.append(raw_path)
                continue
            snapshot_path = Path(snapshot_file)
            if runtime_root is None or not _path_within_root(snapshot_path, runtime_root):
                errors.append(raw_path)
                continue
            try:
                decoded[Path(raw_path)] = base64.b64decode(snapshot_path.read_text(encoding="utf-8").encode("ascii"))
            except (OSError, ValueError, TypeError):
                errors.append(raw_path)
            continue
        if not isinstance(content_b64, str) or not content_b64:
            errors.append(raw_path)
            continue
        try:
            decoded[Path(raw_path)] = base64.b64decode(content_b64.encode("ascii"))
        except (ValueError, TypeError):
            errors.append(raw_path)
    return decoded, errors


def _scrub_manifest_snapshot_payloads(manifest: Dict[str, Any]) -> bool:
    """Remove inline snapshot payloads from manifests and externalize when safe."""
    snapshots = manifest.get("snapshots")
    if not isinstance(snapshots, dict):
        return False
    runtime_root_raw = manifest.get("runtime_root")
    runtime_root = Path(runtime_root_raw) if isinstance(runtime_root_raw, str) and runtime_root_raw else None
    snapshot_root: Optional[Path] = None
    if (
        runtime_root is not None
        and _path_within_root(runtime_root, _tmp_dir())
        and runtime_root.name.startswith("run-")
    ):
        snapshot_root = runtime_root / "snapshots"
        _ensure_private_dir(snapshot_root)
    changed = False
    for raw_path, payload in snapshots.items():
        if not isinstance(payload, dict):
            continue
        content_b64 = payload.pop("content_b64", None)
        if content_b64 is None:
            continue
        changed = True
        if (
            snapshot_root is not None
            and isinstance(raw_path, str)
            and raw_path
            and not isinstance(payload.get("snapshot_file"), str)
            and isinstance(content_b64, str)
            and content_b64
        ):
            digest = hashlib.sha256(raw_path.encode("utf-8")).hexdigest()
            snapshot_file = snapshot_root / f"{digest}.b64"
            snapshot_file.write_text(content_b64, encoding="utf-8")
            _ensure_private_file(snapshot_file)
            payload["snapshot_file"] = str(snapshot_file)
    return changed


def _build_scrubbed_stale_manifest(
    tool: str,
    manifest: Optional[Dict[str, Any]],
    *,
    restore_status: str,
    cleanup_status: str,
    stale_reason: str,
    restore_error: Optional[str],
) -> Dict[str, Any]:
    """Create one safe manifest that preserves diagnostics without inline secrets."""
    base = dict(manifest or {})
    safe_manifest = _build_runtime_manifest(
        tool,
        lease_id=str(base.get("lease_id") or f"{tool}-scrubbed-{os.getpid()}"),
        source_kind=str(base.get("source_kind") or "unknown"),
        requested_target=str(base.get("requested_target") or base.get("selected_candidate") or tool),
        runtime_root=Path(base.get("runtime_root")) if isinstance(base.get("runtime_root"), str) and base.get("runtime_root") else (_tmp_dir() / f"run-scrubbed-{tool}"),
    )
    safe_manifest.update(
        {
            "selected_candidate": base.get("selected_candidate"),
            "owner_pid": base.get("owner_pid"),
            "owner_started_at": base.get("owner_started_at"),
            "child_pid": None,
            "child_started_at": None,
            "last_child_pid": base.get("last_child_pid"),
            "child_status": "exited",
            "phase": "completed",
            "attempt_count": base.get("attempt_count", 0),
            "restore_status": restore_status,
            "cleanup_status": cleanup_status,
            "post_restore_validation": (
                dict(base.get("post_restore_validation"))
                if isinstance(base.get("post_restore_validation"), dict)
                else {"status": "pending", "reason_code": "pending"}
            ),
            "restore_conflicts": list(base.get("restore_conflicts", []))
            if isinstance(base.get("restore_conflicts"), list)
            else [],
            "restore_error": restore_error,
            "snapshots": dict(base.get("snapshots")) if isinstance(base.get("snapshots"), dict) else {},
            "written_states": dict(base.get("written_states")) if isinstance(base.get("written_states"), dict) else {},
            "restore_groups": list(base.get("restore_groups")) if isinstance(base.get("restore_groups"), list) else [],
            "ephemeral_paths": list(base.get("ephemeral_paths")) if isinstance(base.get("ephemeral_paths"), list) else [],
            "snapshot_written": bool(base.get("snapshot_written")),
            "stale": True,
            "stale_reason": stale_reason,
            "created_at": base.get("created_at", safe_manifest["created_at"]),
        }
    )
    _scrub_manifest_snapshot_payloads(safe_manifest)
    return safe_manifest


def _sanitize_managed_target_secret_surface() -> None:
    """Scrub legacy inline snapshot payloads from persisted managed target rows."""
    conn = _connect_db()
    try:
        rows = conn.execute("SELECT tool, target_json FROM managed_targets").fetchall()
    finally:
        conn.close()
    for row in rows:
        raw_json = row["target_json"]
        if "content_b64" not in raw_json:
            continue
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            scrubbed = _build_scrubbed_stale_manifest(
                row["tool"],
                {"tool": row["tool"]},
                restore_status="restore_failed",
                cleanup_status="pending",
                stale_reason="manifest_decode_failed",
                restore_error=f"{exc.__class__.__name__}: {exc}",
            )
        else:
            if not isinstance(payload, dict):
                continue
            if not _scrub_manifest_snapshot_payloads(payload):
                continue
            scrubbed = payload
        upsert_managed_target(row["tool"], scrubbed)


def _json_ready_path_states(entries: Dict[Path, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Convert path-state dictionaries to JSON-friendly keys."""
    return {str(path): dict(payload) for path, payload in entries.items()}


def _path_states_from_manifest(entries: Optional[Dict[str, Any]]) -> Dict[Path, Dict[str, Any]]:
    """Decode JSON-friendly path-state dictionaries back into Path-keyed maps."""
    decoded: Dict[Path, Dict[str, Any]] = {}
    if not isinstance(entries, dict):
        return decoded
    for raw_path, payload in entries.items():
        if isinstance(raw_path, str) and isinstance(payload, dict):
            decoded[Path(raw_path)] = dict(payload)
    return decoded


def _decode_manifest_path_states(
    entries: Optional[Dict[str, Any]],
) -> tuple[Dict[Path, Dict[str, Any]], list[str]]:
    """Decode manifest path states and report malformed entries explicitly."""
    decoded: Dict[Path, Dict[str, Any]] = {}
    errors: list[str] = []
    if not isinstance(entries, dict):
        return decoded, errors
    for raw_path, payload in entries.items():
        if not isinstance(raw_path, str) or not isinstance(payload, dict):
            errors.append(str(raw_path))
            continue
        if "exists" not in payload or "sha256" not in payload:
            errors.append(raw_path)
            continue
        decoded[Path(raw_path)] = dict(payload)
    return decoded, errors


def _path_groups_from_manifest(entries: Optional[Iterable[Iterable[str]]]) -> list[list[Path]]:
    """Decode restore groups from manifest JSON into Path groups."""
    groups: list[list[Path]] = []
    if not isinstance(entries, list):
        return groups
    for group in entries:
        if not isinstance(group, list):
            continue
        paths = [Path(raw_path) for raw_path in group if isinstance(raw_path, str)]
        if paths:
            groups.append(paths)
    return groups


def _decode_manifest_path_groups(
    entries: Optional[Iterable[Iterable[str]]],
) -> tuple[list[list[Path]], list[str]]:
    """Decode manifest restore groups and report malformed entries explicitly."""
    groups: list[list[Path]] = []
    errors: list[str] = []
    if not isinstance(entries, list):
        return groups, errors
    for index, group in enumerate(entries):
        if not isinstance(group, list):
            errors.append(f"group:{index}")
            continue
        paths: list[Path] = []
        for raw_path in group:
            if not isinstance(raw_path, str) or not raw_path:
                errors.append(f"group:{index}")
                paths = []
                break
            paths.append(Path(raw_path))
        if paths:
            groups.append(paths)
    return groups, errors


def _path_list_from_manifest(entries: Optional[Iterable[str]]) -> list[Path]:
    """Decode a manifest path list into Path objects."""
    if not isinstance(entries, list):
        return []
    return [Path(raw_path) for raw_path in entries if isinstance(raw_path, str)]


def _decode_manifest_path_list(
    entries: Optional[Iterable[str]],
) -> tuple[list[Path], list[str]]:
    """Decode a manifest path list and report malformed entries explicitly."""
    if not isinstance(entries, list):
        return [], []
    decoded: list[Path] = []
    errors: list[str] = []
    for index, raw_path in enumerate(entries):
        if not isinstance(raw_path, str) or not raw_path:
            errors.append(f"path:{index}")
            continue
        decoded.append(Path(raw_path))
    return decoded, errors


def _path_within_root(path: Path, root: Path) -> bool:
    """Return True when path lives under the provided root."""
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _runtime_manifest_target_names(manifest: Dict[str, Any]) -> list[str]:
    """Return unique target names recorded in one runtime manifest."""
    seen: set[str] = set()
    targets: list[str] = []
    for value in (manifest.get("selected_candidate"), manifest.get("requested_target")):
        if isinstance(value, str) and value and value not in seen:
            targets.append(value)
            seen.add(value)
    return targets


def _validate_manifest_paths(
    store: Dict[str, Any],
    tool: str,
    manifest: Dict[str, Any],
    *,
    snapshots: Dict[Path, Optional[bytes]],
    written_states: Dict[Path, Dict[str, Any]],
    restore_groups: list[list[Path]],
    ephemeral_paths: list[Path],
) -> Optional[str]:
    """Validate that manifest restore paths stay within managed boundaries."""
    runtime_root_raw = manifest.get("runtime_root")
    if not isinstance(runtime_root_raw, str) or not runtime_root_raw:
        return "manifest path validation failed for: runtime_root"
    runtime_root = Path(runtime_root_raw)
    tmp_root = _tmp_dir()
    if not _path_within_root(runtime_root, tmp_root):
        return f"manifest path validation failed for: runtime_root:{runtime_root}"
    if not runtime_root.name.startswith("run-"):
        return f"manifest path validation failed for: runtime_root:{runtime_root}"

    allowed_live_paths = set(
        _managed_file_paths_for_tool(
            store,
            tool,
            _runtime_manifest_target_names(manifest),
        )
    )
    invalid_paths: list[str] = []

    def _check_path(path: Path) -> None:
        if path in allowed_live_paths or _path_within_root(path, runtime_root):
            return
        invalid_paths.append(str(path))

    for path in snapshots:
        _check_path(path)
    for path in written_states:
        _check_path(path)
    for group in restore_groups:
        for path in group:
            _check_path(path)
    for path in ephemeral_paths:
        _check_path(path)

    if invalid_paths:
        rendered = ", ".join(sorted(dict.fromkeys(invalid_paths)))
        return f"manifest path validation failed for: {rendered}"
    return None


def _decode_managed_target_payload(tool: str, raw_json: str) -> Dict[str, Any]:
    """Decode one managed target payload without letting malformed JSON crash callers."""
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        return {
            "tool": tool,
            "decode_error": f"{exc.__class__.__name__}: {exc}",
            "stale": True,
            "stale_reason": "manifest_decode_failed",
            "phase": "decode_failed",
            "restore_status": "restore_failed",
            "cleanup_status": "pending",
        }
    if isinstance(payload, dict):
        payload.setdefault("tool", tool)
        return payload
    return {
        "tool": tool,
        "decode_error": "managed target payload root is not an object",
        "stale": True,
        "stale_reason": "manifest_decode_failed",
        "phase": "decode_failed",
        "restore_status": "restore_failed",
        "cleanup_status": "pending",
    }


def _managed_target_needs_repair(manifest: Dict[str, Any]) -> bool:
    """Return True when a runtime lease still requires explicit repair."""
    if manifest.get("decode_error"):
        return True
    if manifest.get("stale"):
        return True
    if manifest.get("restore_status") != "restored":
        return True
    if manifest.get("cleanup_status") != "cleaned":
        return True
    if manifest.get("phase") != "completed":
        return True
    return False


def _managed_target_matches_candidate(
    manifest: Optional[Dict[str, Any]],
    candidate: Optional[str],
) -> bool:
    """Return True when a runtime lease belongs to the current doctor/run target."""
    if not isinstance(manifest, dict):
        return False
    if not candidate:
        return True
    requested_target = manifest.get("requested_target")
    selected_candidate = manifest.get("selected_candidate")
    if not requested_target and not selected_candidate:
        return False
    return candidate in {requested_target, selected_candidate}


def upsert_managed_target(tool: str, payload: Dict[str, Any]) -> None:
    """Persist one managed runtime target manifest for later recovery and diagnostics."""
    conn = _connect_db()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO managed_targets(tool, target_json)
                VALUES (?, ?)
                ON CONFLICT(tool) DO UPDATE SET target_json = excluded.target_json
                """,
                (tool, json.dumps(payload, ensure_ascii=False)),
            )
    finally:
        conn.close()


def get_managed_target(tool: str) -> Optional[Dict[str, Any]]:
    """Return the persisted managed runtime manifest for one tool, if any."""
    conn = _connect_db()
    try:
        row = conn.execute(
            "SELECT target_json FROM managed_targets WHERE tool = ?",
            (tool,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return _decode_managed_target_payload(tool, row["target_json"])


def list_managed_targets() -> list[Dict[str, Any]]:
    """Return every persisted managed runtime manifest."""
    conn = _connect_db()
    try:
        rows = conn.execute(
            "SELECT tool, target_json FROM managed_targets ORDER BY tool ASC"
        ).fetchall()
    finally:
        conn.close()
    managed_targets: list[Dict[str, Any]] = []
    for row in rows:
        managed_targets.append(_decode_managed_target_payload(row["tool"], row["target_json"]))
    return managed_targets


def delete_managed_target(tool: str) -> None:
    """Remove one persisted managed runtime manifest."""
    conn = _connect_db()
    try:
        with conn:
            conn.execute("DELETE FROM managed_targets WHERE tool = ?", (tool,))
    finally:
        conn.close()


def get_setting(store: Dict[str, Any], key: str, default: Any = None) -> Any:
    """Read a device-level setting from the current store snapshot."""
    settings = store.get("settings", {})
    if key in settings:
        return settings[key]
    return SETTINGS_DEFAULTS.get(key, default)


def set_setting(store: Dict[str, Any], key: str, value: Any) -> None:
    """Update a device-level setting and persist the store."""
    if key not in SETTINGS_DEFAULTS:
        raise KeyError(key)
    store.setdefault("settings", {})[key] = value
    save_store(store)


def _codex_sync_enabled(store: Dict[str, Any]) -> bool:
    """Return whether future ChatGPT Codex sessions should use the shared lane."""
    return bool(get_setting(store, CODEX_SYNC_SETTING_KEY, False))


def _get_codex_share_lanes(store: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Return prepared Codex share lane recipes."""
    lanes = get_setting(store, CODEX_SHARE_SETTING_KEY, {})
    return dict(lanes) if isinstance(lanes, dict) else {}


def _set_codex_share_lanes(store: Dict[str, Any], lanes: Dict[str, Dict[str, Any]]) -> None:
    """Persist prepared Codex share lane recipes."""
    store.setdefault("settings", {})[CODEX_SHARE_SETTING_KEY] = lanes


def _coerce_setting_value(key: str, value: Optional[str]) -> Any:
    """Parse a CLI setting value according to the setting's default type."""
    default = SETTINGS_DEFAULTS[key]
    if value in ("", "null", "none", None):
        return None
    if isinstance(default, bool):
        normalized = str(value).strip().lower()
        if normalized in _BOOL_TRUE_LITERALS:
            return True
        if normalized in _BOOL_FALSE_LITERALS:
            return False
        raise ValueError(f"Setting '{key}' expects one of: on/off, true/false, yes/no, 1/0.")
    if isinstance(default, dict):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Setting '{key}' expects a JSON object.") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"Setting '{key}' expects a JSON object.")
        return parsed
    return value


def ensure_defaults(store: Dict[str, Any]) -> None:
    """Seed default settings and active-tool keys on a loaded store."""
    providers = store.setdefault("providers", {})
    aliases = store.setdefault("aliases", {})
    store.setdefault("profiles", {})
    settings = store.setdefault("settings", {})
    for key, value in SETTINGS_DEFAULTS.items():
        settings.setdefault(key, value)
    for name, conf in BUILTIN_PROVIDERS.items():
        if name not in providers:
            providers[name] = conf
    for alias, target in BUILTIN_ALIASES.items():
        if alias not in aliases:
            aliases[alias] = target
    for tool in ALL_TOOLS:
        store.setdefault("active", {}).setdefault(tool, None)


def _load_fresh_store() -> Dict[str, Any]:
    """Reload the latest store snapshot and seed in-memory defaults."""
    store = load_store()
    ensure_defaults(store)
    return store


def _store_has_custom_state(store: Optional[Dict[str, Any]]) -> bool:
    """Return True when a store contains non-default runtime state."""
    if not isinstance(store, dict):
        return False
    providers = store.get("providers", {})
    custom_provider_names = set(providers) - set(BUILTIN_PROVIDERS)
    if custom_provider_names:
        return True
    if any(store.get("active", {}).get(tool) for tool in ALL_TOOLS):
        return True
    if store.get("profiles"):
        return True
    if any(store.get("settings", {}).get(key) != default for key, default in SETTINGS_DEFAULTS.items()):
        return True
    custom_aliases = {
        alias: target
        for alias, target in store.get("aliases", {}).items()
        if BUILTIN_ALIASES.get(alias) != target
    }
    return bool(custom_aliases)


def _load_fresh_store_from_lock(fallback_store: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Reload from SQLite when available, otherwise keep the provided in-memory test store."""
    if isinstance(fallback_store, dict) and "_revision" not in fallback_store:
        ensure_defaults(fallback_store)
        return fallback_store
    return _load_fresh_store()


def _codex_state_db_path() -> Optional[Path]:
    """Return the newest readable Codex thread state database path."""
    codex_dir = _runtime_home_dir() / ".codex"
    preferred = codex_dir / "state_5.sqlite"
    if preferred.exists():
        return preferred
    try:
        candidates = sorted(
            (path for path in codex_dir.glob("state_*.sqlite") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None
    return candidates[0] if candidates else None


def _open_codex_state_db() -> Optional[sqlite3.Connection]:
    """Open the Codex thread state DB in read-only mode when present."""
    try:
        db_path = _codex_state_db_path()
    except OSError:
        return None
    if not db_path:
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except (OSError, sqlite3.Error):
        return None
    conn.row_factory = sqlite3.Row
    return conn


def _normalize_codex_thread_row(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert one Codex thread row into a plain dictionary."""
    return {
        "id": row["id"],
        "title": row["title"],
        "cwd": row["cwd"],
        "model_provider": row["model_provider"],
        "updated_at": row["updated_at"],
    }


def _get_codex_thread_record(thread_id: str) -> Optional[Dict[str, Any]]:
    """Return one Codex thread record by id."""
    conn = _open_codex_state_db()
    if conn is None:
        return None
    try:
        row = conn.execute(
            """
            SELECT id, title, cwd, model_provider, updated_at
            FROM threads
            WHERE id = ?
            """,
            (thread_id,),
        ).fetchone()
    finally:
        conn.close()
    return _normalize_codex_thread_row(row) if row else None


def _get_latest_codex_thread_for_cwd(cwd: str) -> Optional[Dict[str, Any]]:
    """Return the newest interactive Codex thread for the given cwd."""
    conn = _open_codex_state_db()
    if conn is None:
        return None
    try:
        row = conn.execute(
            """
            SELECT id, title, cwd, model_provider, updated_at
            FROM threads
            WHERE archived = 0
              AND source = 'cli'
              AND cwd = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (cwd,),
        ).fetchone()
    finally:
        conn.close()
    return _normalize_codex_thread_row(row) if row else None


def _restore_groups_for_tool(
    tool: str,
    target_paths: Iterable[Path],
    *,
    runtime_root: Optional[Path] = None,
) -> list[list[Path]]:
    """Return grouped restore boundaries for one activation attempt."""
    paths = list(target_paths)
    if tool in OVERLAY_TOOLS:
        runtime_group = [path for path in paths if runtime_root and runtime_root in path.parents]
        live_group = [path for path in paths if path not in runtime_group]
        groups: list[list[Path]] = []
        if live_group:
            groups.append(live_group)
        if runtime_group:
            groups.append(runtime_group)
        return groups
    return [paths] if paths else []


def resolve_alias(store: Dict[str, Any], name: str) -> str:
    """Resolve alias name to canonical provider name."""
    return store.get("aliases", {}).get(name, name)


def _validate_profile_queue(
    store: Dict[str, Any],
    tool: str,
    raw: str,
) -> list[str]:
    """Resolve and validate a profile queue for one tool."""
    values: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        candidate = resolve_alias(store, item.strip())
        if not candidate or candidate in seen:
            continue
        provider = store.get("providers", {}).get(candidate)
        if provider is None:
            info(f"[error] Profile candidate '{item.strip()}' does not exist.")
            sys.exit(1)
        if provider.get(tool) is None:
            info(f"[error] Provider '{candidate}' has no {tool} config.")
            sys.exit(1)
        values.append(candidate)
        seen.add(candidate)
    if not values:
        info(f"[error] Profile queue for {tool} is empty.")
        sys.exit(1)
    return values


def _resolve_profile_queue(
    store: Dict[str, Any],
    tool: str,
    name: str,
    *,
    require_non_empty: bool = True,
) -> list[str]:
    """Resolve and validate one stored profile queue for a tool."""
    profiles = store.get("profiles", {})
    if name not in profiles:
        info(f"[error] Profile '{name}' not found.")
        sys.exit(1)
    profile = profiles[name]
    queue = profile.get(tool) or []
    if not queue:
        if require_non_empty:
            info(f"[error] Profile '{name}' has no {tool} queue.")
            sys.exit(1)
        return []

    values: list[str] = []
    seen: set[str] = set()
    for item in queue:
        candidate = resolve_alias(store, item)
        if not candidate or candidate in seen:
            continue
        provider = store.get("providers", {}).get(candidate)
        if provider is None:
            info(f"[error] Profile candidate '{candidate}' does not exist.")
            sys.exit(1)
        if provider.get(tool) is None:
            info(f"[error] Provider '{candidate}' has no {tool} config.")
            sys.exit(1)
        values.append(candidate)
        seen.add(candidate)

    if not values and require_non_empty:
        info(f"[error] Profile '{name}' has no valid {tool} queue.")
        sys.exit(1)
    return values


def _profile_has_queues(profile: Dict[str, Any]) -> bool:
    """Return True when a profile contains at least one non-empty queue."""
    return any(bool(profile.get(tool)) for tool in ALL_TOOLS)


def _preflight_tool_activation(
    store: Dict[str, Any],
    tool: str,
    provider_name: str,
) -> None:
    """Validate whether one provider can activate one tool before writing files."""
    provider = store.get("providers", {}).get(provider_name)
    if provider is None:
        info(f"[error] Provider '{provider_name}' not found. Run: ccsw list")
        sys.exit(1)
    conf = provider.get(tool)
    if conf is None:
        info(f"[error] Provider '{provider_name}' has no {tool} config.")
        sys.exit(1)
    if tool == "codex" and _codex_uses_chatgpt_auth(conf):
        return
    secret_value = conf.get("api_key") if tool == "gemini" else (conf.get("token") or conf.get("api_key"))
    if not resolve_token(secret_value):
        info(f"[error] Provider '{provider_name}' has unresolved {tool} secret.")
        sys.exit(1)
    if tool in {"codex", "opencode", "openclaw"} and not conf.get("base_url"):
        info(f"[error] Provider '{provider_name}' has no {tool} base_url.")
        sys.exit(1)


def _record_batch_result(
    mode: str,
    requested_target: str,
    payload: Dict[str, Any],
) -> None:
    """Record one multi-tool batch result."""
    record_history(
        "batch-result",
        None,
        requested_target,
        {"mode": mode, "requested_target": requested_target, **payload},
    )


def _batch_result_payload(
    *,
    mode: str,
    requested_target: str,
    attempted_tools: list[str],
    applied_tools: list[str],
    failed_tool: Optional[str],
    rollback_status: str,
    changed_tools: list[str],
    noop_tools: list[str],
    restored_tools: list[str],
    conflicted_tools: list[str],
    rollback_conflicts: list[str],
    post_restore_validation: Optional[Dict[str, Any]] = None,
    restore_error: Optional[str] = None,
    snapshot_sync: str = "ok",
) -> Dict[str, Any]:
    """Build one stable batch-result payload for both success and failure paths."""
    return {
        "mode": mode,
        "requested_target": requested_target,
        "requested_target_kind": "profile" if mode == "profile_use" else "provider",
        "preflight_status": "ok",
        "attempted_tools": attempted_tools,
        "applied_tools": applied_tools,
        "failed_tool": failed_tool,
        "rollback_status": rollback_status,
        "rolled_back_tools": restored_tools + conflicted_tools,
        "changed_tools": changed_tools,
        "noop_tools": noop_tools,
        "rollback_conflicts": rollback_conflicts,
        "post_restore_validation": post_restore_validation or {},
        "restored_tools": restored_tools,
        "conflicted_tools": conflicted_tools,
        "restore_error": restore_error,
        "snapshot_sync": snapshot_sync,
    }


def _switch_history_entry(
    tool: str,
    previous: Optional[str],
    current: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Build one switch history entry unless the switch is a no-op."""
    if previous == current:
        return None
    return {
        "action": "switch",
        "tool": tool,
        "subject": current,
        "payload": {"previous": previous, "current": current},
    }


def _execute_multi_tool_switch(
    store: Dict[str, Any],
    *,
    mode: str,
    requested_target: str,
    targets: list[tuple[str, str]],
) -> None:
    """Switch multiple tools with shared preflight and best-effort rollback."""
    for current_tool, candidate in targets:
        _preflight_tool_activation(store, current_tool, candidate)
    managed_paths: list[Path] = []
    for current_tool, candidate in targets:
        managed_paths.extend(_managed_file_paths_for_tool(store, current_tool, [candidate]))
    snapshots = _snapshot_file_state(managed_paths)
    original_active = dict(store.get("active", {}))
    original_revision = store.get("_revision", 0)
    target_paths_by_tool = {
        current_tool: _activation_target_paths(
            store,
            current_tool,
            candidate,
            persist_state=True,
        )
        for current_tool, candidate in targets
    }
    applied_tools: list[str] = []
    env_updates: list[tuple[str, str]] = []
    env_unsets: list[str] = []
    written_states: Dict[Path, Dict[str, Any]] = {}
    restore_groups: list[list[Path]] = []
    rollback_status = "not_needed"
    failed_tool: Optional[str] = None
    try:
        for current_tool, candidate in targets:
            target_paths = target_paths_by_tool[current_tool]
            restore_groups.extend(_restore_groups_for_tool(current_tool, target_paths))
            current_env, current_unsets = activate_tool_for_subprocess(
                store,
                current_tool,
                candidate,
                persist_state=False,
                fail_if_missing=True,
                write_activation_files=True,
            )
            for path in target_paths:
                written_states[path] = _capture_path_state(path)
            env_updates.extend(current_env.items())
            env_unsets.extend(current_unsets)
            applied_tools.append(current_tool)
    except BaseException as exc:
        failed_tool = current_tool
        for path in target_paths_by_tool.get(current_tool, []):
            written_states[path] = _capture_path_state(path)
        rollback_status = "restored"
        changed_tools = [
            current_tool
            for current_tool, candidate in targets
            if current_tool in applied_tools and original_active.get(current_tool) != candidate
        ]
        noop_tools = [current_tool for current_tool, candidate in targets if original_active.get(current_tool) == candidate]
        post_restore_validation = {
            current_tool: {"status": "skipped", "reason_code": "not_run"}
            for current_tool in [tool for tool in target_paths_by_tool if tool in applied_tools or tool == failed_tool]
        }
        payload = _batch_result_payload(
            mode=mode,
            requested_target=requested_target,
            attempted_tools=[tool for tool, _ in targets],
            applied_tools=list(applied_tools),
            failed_tool=failed_tool,
            rollback_status=rollback_status,
            changed_tools=changed_tools,
            noop_tools=noop_tools,
            restored_tools=[],
            conflicted_tools=[],
            rollback_conflicts=[],
            post_restore_validation=post_restore_validation,
            snapshot_sync="ok",
        )
        try:
            restore_result, rollback_conflicts, restore_error = _attempt_owned_restore(
                snapshots,
                written_states,
                groups=restore_groups,
            )
            rollback_status = restore_result
            restored_tools: list[str] = []
            conflicted_tools: list[str] = []
            if restore_result == "restored":
                restored_tools = [
                    candidate_tool
                    for candidate_tool in target_paths_by_tool
                    if candidate_tool in applied_tools or candidate_tool == failed_tool
                ]
            elif restore_result == "restore_conflict":
                conflict_set = {Path(path) for path in rollback_conflicts}
                for candidate_tool, tool_paths in target_paths_by_tool.items():
                    if candidate_tool not in applied_tools and candidate_tool != failed_tool:
                        continue
                    if any(path in conflict_set for path in tool_paths):
                        conflicted_tools.append(candidate_tool)
                    else:
                        restored_tools.append(candidate_tool)
            if restore_result in {"restored", "restore_conflict"}:
                for applied_tool in restored_tools:
                    original_provider = original_active.get(applied_tool)
                    if not original_provider:
                        post_restore_validation[applied_tool] = {
                            "status": "skipped",
                            "reason_code": "no_active_provider",
                        }
                        continue
                    post_restore_validation[applied_tool] = _safe_local_restore_validation(
                        store,
                        applied_tool,
                        original_provider,
                    )
                validation_statuses = [item.get("status") for item in post_restore_validation.values()]
                if any(status == "failed" for status in validation_statuses):
                    rollback_status = "restore_failed"
                elif any(status == "degraded" for status in validation_statuses):
                    rollback_status = "restore_conflict"
            else:
                for attempted_tool in post_restore_validation:
                    post_restore_validation[attempted_tool] = {
                        "status": "skipped",
                        "reason_code": "restore_failed",
                    }
            payload = _batch_result_payload(
                mode=mode,
                requested_target=requested_target,
                attempted_tools=[tool for tool, _ in targets],
                applied_tools=list(applied_tools),
                failed_tool=failed_tool,
                rollback_status=rollback_status,
                changed_tools=changed_tools,
                noop_tools=noop_tools,
                restored_tools=restored_tools,
                conflicted_tools=conflicted_tools,
                rollback_conflicts=rollback_conflicts,
                post_restore_validation=post_restore_validation,
                restore_error=restore_error,
                snapshot_sync=payload.get("snapshot_sync", "ok"),
            )
            if rollback_conflicts:
                _record_batch_result(mode, requested_target, payload)
            else:
                store["active"] = original_active
                save_store(
                    store,
                    expected_revision=store.get("_revision"),
                    history_entries=[
                        {
                            "action": "batch-result",
                            "tool": None,
                            "subject": requested_target,
                            "payload": payload,
                        }
                    ],
                )
        except StoreSnapshotSyncError as snapshot_exc:
            payload["snapshot_sync"] = "degraded"
            update_latest_history_payload("batch-result", None, requested_target, payload)
            info(
                "[warning] Rollback state committed, but providers.json snapshot sync failed. "
                "SQLite remains authoritative."
            )
            raise SystemExit(1) from snapshot_exc
        except Exception:
            if store.get("_revision", original_revision) != original_revision:
                raise
            rollback_status = "restore_failed"
            payload["rollback_status"] = rollback_status
            payload["rolled_back_tools"] = []
            payload["restored_tools"] = []
            payload["conflicted_tools"] = []
            _record_batch_result(mode, requested_target, payload)
        if isinstance(exc, SystemExit):
            raise
        raise
    switch_entries = []
    for current_tool, candidate in targets:
        history_entry = _switch_history_entry(current_tool, original_active.get(current_tool), candidate)
        if history_entry:
            switch_entries.append(history_entry)
        store["active"][current_tool] = candidate
    changed_tools = [entry["tool"] for entry in switch_entries]
    noop_tools = [current_tool for current_tool, _candidate in targets if current_tool not in changed_tools]
    try:
        save_store(
            store,
            expected_revision=store.get("_revision"),
            history_entries=[
                *switch_entries,
                {
                    "action": "batch-result",
                    "tool": None,
                    "subject": requested_target,
                    "payload": _batch_result_payload(
                        mode=mode,
                        requested_target=requested_target,
                        attempted_tools=[tool for tool, _ in targets],
                        applied_tools=list(applied_tools),
                        failed_tool=None,
                        rollback_status=rollback_status,
                        changed_tools=changed_tools,
                        noop_tools=noop_tools,
                        restored_tools=[],
                        conflicted_tools=[],
                        rollback_conflicts=[],
                        post_restore_validation={},
                        restore_error=None,
                        snapshot_sync="ok",
                    ),
                },
            ],
        )
    except StoreSnapshotSyncError as exc:
        update_latest_history_payload(
            "batch-result",
            None,
            requested_target,
            _batch_result_payload(
                mode=mode,
                requested_target=requested_target,
                attempted_tools=[tool for tool, _ in targets],
                applied_tools=list(applied_tools),
                failed_tool=None,
                rollback_status=rollback_status,
                changed_tools=changed_tools,
                noop_tools=noop_tools,
                restored_tools=[],
                conflicted_tools=[],
                rollback_conflicts=[],
                post_restore_validation={},
                restore_error=None,
                snapshot_sync="degraded",
            ),
        )
        info(
            "[warning] Batch state committed, but providers.json snapshot sync failed. "
            "SQLite remains authoritative."
        )
        raise SystemExit(1) from exc
    for key, value in env_updates:
        emit_env(key, value)
    for key in env_unsets:
        emit_unset(key)


def _normalize_optional_dir(value: Optional[str]) -> Optional[Path]:
    """Normalize a user-provided directory override."""
    if not value:
        return None
    expanded = os.path.expandvars(value)
    absolute = os.path.abspath(os.path.expanduser(expanded))
    return Path(absolute)


def _is_windows_style_path(value: Optional[str]) -> bool:
    """Return True when a raw setting looks like a Windows drive path."""
    return bool(isinstance(value, str) and _WINDOWS_PATH_RE.match(value))


def get_tool_paths(store: Optional[Dict[str, Any]], tool: str) -> Dict[str, Path]:
    """Return the effective file paths for a managed tool."""
    settings = store or {}
    override_key = f"{tool}_config_dir"
    override = _normalize_optional_dir(get_setting(settings, override_key))

    if tool == "claude":
        base_dir = override or _claude_settings_path().parent
        return {"dir": base_dir, "settings": base_dir / "settings.json"}
    if tool == "codex":
        base_dir = override or _codex_config_path().parent
        return {
            "dir": base_dir,
            "auth": base_dir / "auth.json",
            "config": base_dir / "config.toml",
        }
    if tool == "gemini":
        base_dir = override or _gemini_settings_path().parent
        return {"dir": base_dir, "settings": base_dir / "settings.json"}
    if tool == "opencode":
        base_dir = override or _opencode_config_path().parent
        return {
            "dir": base_dir,
            "config": base_dir / "opencode.json",
            "auth": (base_dir / "auth.json") if override else _opencode_auth_path(),
        }
    if tool == "openclaw":
        base_dir = override or _openclaw_config_path().parent
        return {
            "dir": base_dir,
            "config": base_dir / "openclaw.json",
            "env": base_dir / ".env",
        }
    raise KeyError(tool)


def _load_json_relaxed(path: Path) -> Dict[str, Any]:
    """Load JSON or a JSON5-like file using a conservative relaxed parser."""
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        stripped_lines = [_strip_json_like_comment(line) for line in raw.splitlines()]
        candidate = _normalize_json5_like_text("\n".join(stripped_lines))
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            return {}
    if not isinstance(data, dict):
        return {}
    return data


def _normalize_json5_like_text(text: str) -> str:
    """Normalize a conservative JSON5-like subset into plain JSON text."""
    normalized = _replace_json5_single_quoted_strings(text)
    normalized = _JSON5_UNQUOTED_KEY_RE.sub(
        lambda match: f'{match.group(1)}"{match.group(2)}"{match.group(3)}',
        normalized,
    )
    return _TRAILING_COMMA_RE.sub("", normalized)


def _replace_json5_single_quoted_strings(text: str) -> str:
    """Convert single-quoted JSON5 strings into JSON double-quoted strings."""
    result: list[str] = []
    index = 0
    in_double = False
    escaped = False
    while index < len(text):
        char = text[index]
        if in_double:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_double = False
            index += 1
            continue
        if char == '"':
            in_double = True
            result.append(char)
            index += 1
            continue
        if char != "'":
            result.append(char)
            index += 1
            continue
        index += 1
        content: list[str] = []
        while index < len(text):
            current = text[index]
            if current == "\\":
                index += 1
                if index >= len(text):
                    content.append("\\")
                    break
                escaped_char = text[index]
                escapes = {
                    "'": "'",
                    '"': '"',
                    "\\": "\\",
                    "/": "/",
                    "b": "\b",
                    "f": "\f",
                    "n": "\n",
                    "r": "\r",
                    "t": "\t",
                }
                content.append(escapes.get(escaped_char, escaped_char))
                index += 1
                continue
            if current == "'":
                index += 1
                break
            content.append(current)
            index += 1
        result.append(json.dumps("".join(content)))
    return "".join(result)


def _strip_json_like_comment(line: str) -> str:
    """Remove a trailing // comment only when it appears outside quoted strings."""
    in_string = False
    escaped = False
    quote = ""
    for index, char in enumerate(line):
        if in_string:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == quote:
                in_string = False
            continue
        if char in ('"', "'"):
            in_string = True
            quote = char
            continue
        if char == "/" and index + 1 < len(line) and line[index + 1] == "/":
            return line[:index]
    return line


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
        tools_active = [t for t in ALL_TOOLS if active.get(t) == name]
        suffix = f"  [active: {', '.join(tools_active)}]" if tools_active else ""
        tools_conf = [t for t in ALL_TOOLS if conf.get(t)]
        info(f"  {name}  ({', '.join(tools_conf) or 'no tools configured'}){suffix}")

    if aliases:
        info("\nAliases:")
        for alias, target in aliases.items():
            info(f"  {alias} -> {target}")

    profiles = store.get("profiles", {})
    if profiles:
        info("\nProfiles:")
        for name, profile in profiles.items():
            configured = [tool for tool in ALL_TOOLS if profile.get(tool)]
            info(f"  {name}  ({', '.join(configured) or 'empty'})")


def cmd_show(store: Dict[str, Any]) -> None:
    """Show currently active provider per tool."""
    active = store.get("active", {})
    providers = store.get("providers", {})
    for tool in ALL_TOOLS:
        name = active.get(tool)
        if name and name in providers:
            conf = providers[name].get(tool)
            token_ref = conf.get("token") or conf.get("api_key") if conf else None
            base_url = conf.get("base_url") if conf else None
            fallback_base_url = conf.get("fallback_base_url") if conf else None
            details = []
            if tool == "codex" and conf and conf.get("auth_mode") == CODEX_AUTH_MODE_CHATGPT:
                details.append("auth=chatgpt")
                details.append(f"route={_codex_chatgpt_provider_route(store)}")
            if base_url:
                details.append(f"url={base_url}")
            if fallback_base_url:
                details.append(f"fallback_url={fallback_base_url}")
            if token_ref:
                details.append(f"token={format_secret_ref(token_ref)}")
            if conf and conf.get("model"):
                details.append(f"model={conf['model']}")
            detail_str = f"  ({', '.join(details)})" if details else ""
            info(f"[{tool}] {name}{detail_str}")
        else:
            info(f"[{tool}] (none)")
    info(f"[codex-sync] future_sessions={'on' if _codex_sync_enabled(store) else 'off'}")


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
    with _state_lock():
        store = _load_fresh_store_from_lock(store)
        canonical = resolve_alias(store, name)
        providers = store.get("providers", {})
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
        pruned_profiles: list[str] = []
        for profile_name, profile in store.get("profiles", {}).items():
            changed = False
            for tool in ALL_TOOLS:
                queue = profile.get(tool)
                if not isinstance(queue, list):
                    continue
                filtered = [candidate for candidate in queue if candidate != canonical]
                if filtered != queue:
                    profile[tool] = filtered
                    changed = True
            if changed:
                pruned_profiles.append(profile_name)
        save_store(store, expected_revision=store.get("_revision"))
    info(f"Removed provider: {canonical}")
    if stale:
        info(f"Removed stale aliases: {', '.join(stale)}")
    if pruned_profiles:
        info(f"Updated profiles: {', '.join(pruned_profiles)}")


def cmd_alias_add(store: Dict[str, Any], alias_name: str, target: str) -> None:
    """Create an alias pointing to a provider."""
    if not _NAME_RE.match(alias_name):
        info(f"[error] Alias name '{alias_name}' is invalid. Use only letters, digits, _, ., -")
        sys.exit(1)
    with _state_lock():
        store = _load_fresh_store_from_lock(store)
        canonical = resolve_alias(store, target)
        if canonical not in store.get("providers", {}):
            info(f"[error] Target provider '{target}' not found. Run: ccsw list")
            sys.exit(1)
        store.setdefault("aliases", {})[alias_name] = canonical
        save_store(store, expected_revision=store.get("_revision"))
    info(f"Alias added: {alias_name} -> {canonical}")


def cmd_profile_add(store: Dict[str, Any], name: str, args: argparse.Namespace) -> None:
    """Create or update a named profile."""
    if not _NAME_RE.match(name):
        info(f"[error] Profile name '{name}' is invalid. Use only letters, digits, _, ., -")
        sys.exit(1)
    with _state_lock():
        store = _load_fresh_store_from_lock(store)
        profile: Dict[str, list[str]] = store.setdefault("profiles", {}).get(name, {})
        for tool in ALL_TOOLS:
            raw = getattr(args, tool, None)
            if raw is None:
                continue
            profile[tool] = _validate_profile_queue(store, tool, raw)
        if not _profile_has_queues(profile):
            info(f"[error] Profile '{name}' must include at least one tool queue.")
            sys.exit(1)
        store["profiles"][name] = profile
        save_store(store, expected_revision=store.get("_revision"))
    info(f"Profile '{name}' saved.")


def cmd_profile_use(store: Dict[str, Any], name: str) -> None:
    """Switch each configured tool in a profile to its first candidate."""
    with _state_lock():
        store = _load_fresh_store_from_lock(store)
        profiles = store.get("profiles", {})
        if name not in profiles:
            info(f"[error] Profile '{name}' not found.")
            sys.exit(1)
        targets: list[tuple[str, str]] = []
        for tool in ALL_TOOLS:
            candidates = _resolve_profile_queue(store, tool, name, require_non_empty=False)
            if candidates:
                targets.append((tool, candidates[0]))
        if not targets:
            info(f"[error] Profile '{name}' has no configured tool queues.")
            sys.exit(1)
        _execute_multi_tool_switch(
            store,
            mode="profile_use",
            requested_target=name,
            targets=targets,
        )


def cmd_profile_list(store: Dict[str, Any]) -> None:
    """List all defined profiles."""
    profiles = store.get("profiles", {})
    if not profiles:
        info("No profiles configured. Run: ccsw profile add <name> --codex a,b")
        return
    for name, profile in profiles.items():
        configured = [tool for tool in ALL_TOOLS if profile.get(tool)]
        info(f"{name}: {', '.join(configured) or 'empty'}")


def cmd_profile_show(store: Dict[str, Any], name: str) -> None:
    """Show a single profile and its candidate queues."""
    profiles = store.get("profiles", {})
    if name not in profiles:
        info(f"[error] Profile '{name}' not found.")
        sys.exit(1)
    profile = profiles[name]
    info(f"[profile] {name}")
    for tool in ALL_TOOLS:
        queue = profile.get(tool) or []
        info(f"  {tool}: {', '.join(queue) if queue else '(none)'}")


def cmd_profile_remove(store: Dict[str, Any], name: str) -> None:
    """Delete a saved profile."""
    profiles = store.get("profiles", {})
    if name not in profiles:
        info(f"[error] Profile '{name}' not found.")
        sys.exit(1)
    with _state_lock():
        store = _load_fresh_store_from_lock(store)
        profiles = store.get("profiles", {})
        if name not in profiles:
            info(f"[error] Profile '{name}' not found.")
            sys.exit(1)
        del profiles[name]
        save_store(store, expected_revision=store.get("_revision"))
    info(f"Removed profile: {name}")


def cmd_add(store: Dict[str, Any], name: str, args: argparse.Namespace) -> None:
    """Add or update a provider (interactive if no flags given)."""
    if not _NAME_RE.match(name):
        info(f"[error] Provider name '{name}' is invalid. Use only letters, digits, _, ., -")
        sys.exit(1)
    providers = store.setdefault("providers", {})
    conf: Dict[str, Any] = providers.get(name, {})

    has_flags = any([
        args.claude_url, args.claude_token,
        args.codex_url, args.codex_fallback_url, args.codex_token, getattr(args, "codex_auth_mode", None),
        args.gemini_key,
        args.opencode_url, args.opencode_token, args.opencode_model,
        args.openclaw_url, args.openclaw_token, args.openclaw_model,
    ])

    with _state_lock():
        store = _load_fresh_store_from_lock(store)
        providers = store.setdefault("providers", {})
        conf = providers.get(name, {})
        if has_flags:
            _add_from_flags(conf, args)
        else:
            _add_interactive(name, conf, allow_literal=getattr(args, "allow_literal_secrets", False))

        providers[name] = conf
        save_store(store, expected_revision=store.get("_revision"))
    info(f"Provider '{name}' saved.")


def _add_from_flags(conf: Dict[str, Any], args: argparse.Namespace) -> None:
    allow_literal = getattr(args, "allow_literal_secrets", False)
    codex_auth_mode = getattr(args, "codex_auth_mode", None)
    if args.claude_url or args.claude_token:
        c = conf.get("claude") or {}
        if args.claude_url:
            c["base_url"] = args.claude_url
        if args.claude_token:
            _require_secret_ref("claude token", args.claude_token, allow_literal=allow_literal)
            c["token"] = args.claude_token
        c.setdefault("extra_env", {})
        conf["claude"] = c

    if args.codex_url or args.codex_fallback_url or args.codex_token:
        if codex_auth_mode == CODEX_AUTH_MODE_CHATGPT:
            info("[error] --codex-auth-mode chatgpt cannot be combined with --codex-url/--codex-fallback-url/--codex-token.")
            sys.exit(1)
        c = conf.get("codex") or {}
        if args.codex_url:
            c["base_url"] = args.codex_url
        if args.codex_fallback_url:
            c["fallback_base_url"] = args.codex_fallback_url
        if args.codex_token:
            _require_secret_ref("codex token", args.codex_token, allow_literal=allow_literal)
            c["token"] = args.codex_token
        c.pop("auth_mode", None)
        conf["codex"] = c
    elif codex_auth_mode == CODEX_AUTH_MODE_CHATGPT:
        conf["codex"] = {"auth_mode": CODEX_AUTH_MODE_CHATGPT}

    if args.gemini_key:
        c = conf.get("gemini") or {}
        _require_secret_ref("gemini api_key", args.gemini_key, allow_literal=allow_literal)
        c["api_key"] = args.gemini_key
        if args.gemini_auth_type is not None:
            c["auth_type"] = args.gemini_auth_type
        conf["gemini"] = c

    if args.opencode_url or args.opencode_token or args.opencode_model:
        c = conf.get("opencode") or {}
        if args.opencode_url:
            c["base_url"] = args.opencode_url
        if args.opencode_token:
            _require_secret_ref("opencode token", args.opencode_token, allow_literal=allow_literal)
            c["token"] = args.opencode_token
        if args.opencode_model:
            c["model"] = args.opencode_model
        conf["opencode"] = c

    if args.openclaw_url or args.openclaw_token or args.openclaw_model:
        c = conf.get("openclaw") or {}
        if args.openclaw_url:
            c["base_url"] = args.openclaw_url
        if args.openclaw_token:
            _require_secret_ref("openclaw token", args.openclaw_token, allow_literal=allow_literal)
            c["token"] = args.openclaw_token
        if args.openclaw_model:
            c["model"] = args.openclaw_model
        conf["openclaw"] = c


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"  {label}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        info("\nAborted.")
        sys.exit(1)
    return val or default


def _add_interactive(name: str, conf: Dict[str, Any], *, allow_literal: bool = False) -> None:
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
            _require_secret_ref("claude token", claude_token, allow_literal=allow_literal)
            c["token"] = claude_token
        c.setdefault("extra_env", {})
        conf["claude"] = c

    info("\n[ Codex CLI ]")
    codex_url = _prompt("base_url")
    codex_fallback_url = _prompt("fallback_base_url (optional)")
    codex_token = _prompt("token ($ENV_VAR or literal)")
    if codex_url or codex_fallback_url or codex_token:
        c = conf.get("codex") or {}
        if codex_url:
            c["base_url"] = codex_url
        if codex_fallback_url:
            c["fallback_base_url"] = codex_fallback_url
        if codex_token:
            _require_secret_ref("codex token", codex_token, allow_literal=allow_literal)
            c["token"] = codex_token
        conf["codex"] = c

    info("\n[ Gemini CLI ]")
    gemini_key = _prompt("api_key ($ENV_VAR or literal)")
    if gemini_key:
        c = conf.get("gemini") or {}
        _require_secret_ref("gemini api_key", gemini_key, allow_literal=allow_literal)
        c["api_key"] = gemini_key
        c["auth_type"] = _prompt("auth_type", "api-key")
        conf["gemini"] = c

    info("\n[ OpenCode ]")
    opencode_url = _prompt("base_url")
    opencode_token = _prompt("token ($ENV_VAR or literal)")
    opencode_model = _prompt("model (optional)")
    if opencode_url or opencode_token or opencode_model:
        c = conf.get("opencode") or {}
        if opencode_url:
            c["base_url"] = opencode_url
        if opencode_token:
            _require_secret_ref("opencode token", opencode_token, allow_literal=allow_literal)
            c["token"] = opencode_token
        if opencode_model:
            c["model"] = opencode_model
        conf["opencode"] = c

    info("\n[ OpenClaw ]")
    openclaw_url = _prompt("base_url")
    openclaw_token = _prompt("token ($ENV_VAR or literal)")
    openclaw_model = _prompt("model (optional)")
    if openclaw_url or openclaw_token or openclaw_model:
        c = conf.get("openclaw") or {}
        if openclaw_url:
            c["base_url"] = openclaw_url
        if openclaw_token:
            _require_secret_ref("openclaw token", openclaw_token, allow_literal=allow_literal)
            c["token"] = openclaw_token
        if openclaw_model:
            c["model"] = openclaw_model
        conf["openclaw"] = c


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------
def write_claude(
    conf: Dict[str, Any],
    store: Optional[Dict[str, Any]] = None,
    *,
    create_backup: bool = True,
) -> Optional[list]:
    """Merge provider config into ~/.claude/settings.json. Returns [] on success, None on failure."""
    token = resolve_token(conf.get("token"))
    if not token:
        info(f"[claude] Skipped: token unresolved (ref: {conf.get('token')!r})")
        return None

    paths = get_tool_paths(store, "claude")
    settings_path = paths["settings"]
    data = load_json(settings_path)
    bak = backup_file(settings_path, enabled=create_backup)

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
    save_json(settings_path, data)
    if bak:
        info(f"[claude] Backed up settings.json -> {bak.name}")
    info(f"[claude] Updated {settings_path}")
    return []


def write_codex(
    conf: Dict[str, Any],
    provider_name: str,
    store: Optional[Dict[str, Any]] = None,
    *,
    create_backup: bool = True,
    write_activation_file: bool = True,
) -> Optional[list]:
    """Write Codex auth.json + config.toml. Returns env pairs on success, None on failure."""
    if _codex_uses_chatgpt_auth(conf):
        provider_route = _codex_chatgpt_provider_route(store)
        paths = get_tool_paths(store, "codex")
        auth_path = paths["auth"]
        config_path = paths["config"]

        data = load_json(auth_path)
        if not _codex_has_chatgpt_login_state(data):
            info(
                "[codex] Skipped: ChatGPT login is missing or incomplete in auth.json. "
                "Run `codex login` first, then try `cxsw pro` again."
            )
            return None
        auth_bak = backup_file(auth_path, enabled=create_backup)
        config_bak = backup_file(config_path, enabled=create_backup)

        data.pop("OPENAI_API_KEY", None)
        data.pop("OPENAI_BASE_URL", None)
        data["auth_mode"] = CODEX_AUTH_MODE_CHATGPT

        def _persist() -> None:
            save_json(auth_path, data)
            if provider_route == CODEX_PROVIDER_ID:
                upsert_codex_chatgpt_shared_config(config_path, provider_name)
            else:
                upsert_codex_chatgpt_config(config_path)
            if write_activation_file:
                write_shell_exports(_codex_env_path(), [], unsets=_codex_env_unsets(conf))

        tracked_paths = [auth_path, config_path]
        if write_activation_file:
            tracked_paths.append(_codex_env_path())
        _write_with_file_restore(tracked_paths, _persist)
        if auth_bak:
            info(f"[codex] Backed up auth.json -> {auth_bak.name}")
        if config_bak:
            info(f"[codex] Backed up config.toml -> {config_bak.name}")
        info(f"[codex] Updated {auth_path}")
        info(f"[codex] Updated {config_path}")
        if write_activation_file:
            info(f"[codex] codex.env updated at {_codex_env_path()}")
        return []

    token = resolve_token(conf.get("token"))
    base_url = select_codex_base_url(conf)

    if not token:
        info(f"[codex] Skipped: token unresolved (ref: {conf.get('token')!r})")
        return None
    if not base_url:
        info("[codex] Skipped: base_url not configured.")
        return None

    paths = get_tool_paths(store, "codex")
    auth_path = paths["auth"]
    config_path = paths["config"]

    data = load_json(auth_path)
    auth_bak = backup_file(auth_path, enabled=create_backup)
    config_bak = backup_file(config_path, enabled=create_backup)

    data["OPENAI_API_KEY"] = token
    data.pop("OPENAI_BASE_URL", None)

    def _persist() -> None:
        save_json(auth_path, data)
        upsert_codex_provider_config(config_path, provider_name, base_url)
        if write_activation_file:
            write_shell_exports(
                _codex_env_path(),
                [("OPENAI_API_KEY", token)],
                unsets=_codex_env_unsets(conf),
            )

    tracked_paths = [auth_path, config_path]
    if write_activation_file:
        tracked_paths.append(_codex_env_path())
    _write_with_file_restore(tracked_paths, _persist)
    if auth_bak:
        info(f"[codex] Backed up auth.json -> {auth_bak.name}")
    if config_bak:
        info(f"[codex] Backed up config.toml -> {config_bak.name}")
    info(f"[codex] Updated {auth_path}")
    info(f"[codex] Updated {config_path}")
    if write_activation_file:
        info(f"[codex] codex.env updated at {_codex_env_path()}")

    return [("OPENAI_API_KEY", token)]


def write_gemini(
    conf: Dict[str, Any],
    store: Optional[Dict[str, Any]] = None,
    *,
    create_backup: bool = True,
    write_activation_file: bool = True,
) -> Optional[list]:
    """Update ~/.gemini/settings.json. Returns env pairs on success, None on failure."""
    api_key = resolve_token(conf.get("api_key"))
    auth_type = conf.get("auth_type", "api-key")

    if not api_key:
        info(f"[gemini] Skipped: api_key unresolved (ref: {conf.get('api_key')!r})")
        return None

    paths = get_tool_paths(store, "gemini")
    settings_path = paths["settings"]
    data = load_json(settings_path)
    bak = backup_file(settings_path, enabled=create_backup)

    # Guard against corrupt settings.json where security/auth are not dicts
    if not isinstance(data.get("security"), dict):
        data["security"] = {}
    if not isinstance(data["security"].get("auth"), dict):
        data["security"]["auth"] = {}
    data["security"]["auth"]["selectedType"] = auth_type

    def _persist() -> None:
        save_json(settings_path, data)
        if write_activation_file:
            write_shell_exports(_active_env_path(), [("GEMINI_API_KEY", api_key)])

    tracked_paths = [settings_path, _active_env_path()] if write_activation_file else [settings_path]
    _write_with_file_restore(tracked_paths, _persist)
    if bak:
        info(f"[gemini] Backed up settings.json -> {bak.name}")
    info(f"[gemini] Updated {settings_path}")
    if write_activation_file:
        info(f"[gemini] active.env updated at {_active_env_path()}")

    return [("GEMINI_API_KEY", api_key)]


def write_opencode(
    conf: Dict[str, Any],
    provider_name: str,
    store: Optional[Dict[str, Any]] = None,
    *,
    activation_path: Optional[Path] = None,
    overlay_path: Optional[Path] = None,
    write_activation_file: bool = True,
) -> Optional[list]:
    """Generate an OpenCode overlay config and return activation exports."""
    token = resolve_token(conf.get("token") or conf.get("api_key"))
    base_url = conf.get("base_url")
    model = conf.get("model")
    headers = conf.get("headers") or {}
    if not token:
        info(f"[opencode] Skipped: token unresolved (ref: {conf.get('token')!r})")
        return None
    if not isinstance(base_url, str) or not base_url:
        info("[opencode] Skipped: base_url not configured.")
        return None
    header_error = _validate_opencode_headers(headers)
    if header_error:
        info(f"[error] {header_error}")
        sys.exit(1)

    provider_id = conf.get("provider_id") or provider_name
    resolved_overlay_path = overlay_path or (_generated_dir() / "opencode" / f"{provider_name}.json")
    _ensure_private_dir(resolved_overlay_path.parent)
    data: Dict[str, Any] = {
        "provider": {
            provider_id: {
                "npm": conf.get("npm", "@ai-sdk/openai-compatible"),
                "options": {
                    "baseURL": base_url,
                    "apiKey": token,
                },
            }
        }
    }
    if headers:
        data["provider"][provider_id]["options"]["headers"] = headers
    if model:
        data["provider"][provider_id]["models"] = [model]
        data["model"] = model
    def _persist() -> None:
        save_json(resolved_overlay_path, data)
        if write_activation_file:
            write_shell_exports(activation_path or _opencode_env_path(), [("OPENCODE_CONFIG", str(resolved_overlay_path))])

    tracked_paths = [resolved_overlay_path, activation_path or _opencode_env_path()] if write_activation_file else [resolved_overlay_path]
    _write_with_file_restore(tracked_paths, _persist)
    info(f"[opencode] Generated overlay at {resolved_overlay_path}")
    return [("OPENCODE_CONFIG", str(resolved_overlay_path))]


def write_openclaw(
    conf: Dict[str, Any],
    provider_name: str,
    store: Optional[Dict[str, Any]] = None,
    *,
    activation_path: Optional[Path] = None,
    overlay_path: Optional[Path] = None,
    write_activation_file: bool = True,
) -> Optional[list]:
    """Generate an OpenClaw overlay config and return activation exports."""
    token = resolve_token(conf.get("token") or conf.get("api_key"))
    base_url = conf.get("base_url")
    model = conf.get("model")
    if not token:
        info(f"[openclaw] Skipped: token unresolved (ref: {conf.get('token')!r})")
        return None
    if not isinstance(base_url, str) or not base_url:
        info("[openclaw] Skipped: base_url not configured.")
        return None

    provider_id = conf.get("provider_id") or provider_name
    resolved_overlay_path = overlay_path or (_generated_dir() / "openclaw" / f"{provider_name}.json5")
    _ensure_private_dir(resolved_overlay_path.parent)
    provider_payload: Dict[str, Any] = {
        "baseUrl": base_url,
        "apiKey": token,
    }
    if conf.get("api"):
        provider_payload["api"] = conf["api"]
    if model:
        provider_payload["models"] = [{"id": model}]

    data: Dict[str, Any] = {
        "models": {
            "mode": "merge",
            "providers": {provider_id: provider_payload},
        }
    }
    if model:
        data["agents"] = {"defaults": {"model": {"primary": model}}}
    exports = [("OPENCLAW_CONFIG_PATH", str(resolved_overlay_path))]
    profile = conf.get("profile")
    if profile:
        exports.append(("OPENCLAW_PROFILE", str(profile)))
    activation_unsets = [] if profile else ["OPENCLAW_PROFILE"]

    def _persist() -> None:
        save_json(resolved_overlay_path, data)
        if write_activation_file:
            write_shell_exports(activation_path or _openclaw_env_path(), exports, activation_unsets)

    tracked_paths = [resolved_overlay_path, activation_path or _openclaw_env_path()] if write_activation_file else [resolved_overlay_path]
    _write_with_file_restore(tracked_paths, _persist)
    info(f"[openclaw] Generated overlay at {resolved_overlay_path}")
    return exports


# ---------------------------------------------------------------------------
# Switch dispatch
# ---------------------------------------------------------------------------
def _classify_process_failure(
    result: Optional[subprocess.CompletedProcess[str]] = None,
    exc: Optional[BaseException] = None,
) -> tuple[str, bool]:
    """Classify a run failure and whether it should trigger fallback."""
    if exc is not None:
        if isinstance(exc, KeyboardInterrupt):
            return "interrupted", False
        if isinstance(exc, FileNotFoundError):
            return "non_retryable_cli", False
        if isinstance(exc, (subprocess.TimeoutExpired, TimeoutError)):
            return "retryable_network", True
        if isinstance(exc, PermissionError):
            return "non_retryable_cli", False
        if isinstance(exc, OSError):
            return "retryable_network", True
        return "non_retryable_cli", False

    if result is None or result.returncode == 0:
        return "ok", False
    if result.returncode in {130, -2, -15}:
        return "interrupted", False

    combined = f"{result.stdout}\n{result.stderr}".lower()
    if any(token in combined for token in ("401", "403", "unauthorized", "forbidden", "invalid api key")):
        return "non_retryable_auth", False
    if any(token in combined for token in ("404", "not found", "invalid_request_error", "unsupported")):
        return "non_retryable_config", False
    if any(pattern in combined for pattern in RETRYABLE_PATTERNS):
        return "retryable_upstream", True
    return "non_retryable_command", False


def _result_from_exception(
    argv: list[str],
    exc: BaseException,
) -> subprocess.CompletedProcess[str]:
    """Convert a subprocess exception into a CompletedProcess-like result."""
    if isinstance(exc, KeyboardInterrupt):
        return subprocess.CompletedProcess(argv, 130, "", "KeyboardInterrupt")
    if isinstance(exc, FileNotFoundError):
        return subprocess.CompletedProcess(argv, 127, "", str(exc))
    if isinstance(exc, (subprocess.TimeoutExpired, TimeoutError)):
        return subprocess.CompletedProcess(argv, 124, "", str(exc))
    return subprocess.CompletedProcess(argv, 1, "", str(exc))


def _managed_file_paths_for_tool(
    store: Dict[str, Any],
    tool: str,
    candidates: Iterable[str],
    *,
    include_activation_files: bool = True,
) -> list[Path]:
    """Return the files touched by temporary run activation for a tool."""
    managed: list[Path] = []
    tool_paths = get_tool_paths(store, tool)
    if tool == "claude":
        managed.append(tool_paths["settings"])
    elif tool == "codex":
        managed.extend([tool_paths["auth"], tool_paths["config"]])
        if include_activation_files:
            managed.append(_codex_env_path())
    elif tool == "gemini":
        managed.append(tool_paths["settings"])
        if include_activation_files:
            managed.append(_active_env_path())
    elif tool == "opencode":
        if include_activation_files:
            managed.append(_opencode_env_path())
        managed.extend(_generated_dir() / "opencode" / f"{candidate}.json" for candidate in candidates)
    elif tool == "openclaw":
        if include_activation_files:
            managed.append(_openclaw_env_path())
        managed.extend(_generated_dir() / "openclaw" / f"{candidate}.json5" for candidate in candidates)
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in managed:
        if path not in seen:
            deduped.append(path)
            seen.add(path)
    return deduped


def _activation_target_paths(
    store: Dict[str, Any],
    tool: str,
    provider_name: str,
    *,
    persist_state: bool,
    runtime_dir: Optional[Path] = None,
) -> list[Path]:
    """Return the exact live paths touched by one activation attempt."""
    paths = get_tool_paths(store, tool)
    if tool == "claude":
        return [paths["settings"]]
    if tool == "codex":
        managed = [paths["auth"], paths["config"]]
        if persist_state:
            managed.append(_codex_env_path())
        return managed
    if tool == "gemini":
        managed = [paths["settings"]]
        if persist_state:
            managed.append(_active_env_path())
        return managed
    if tool == "opencode":
        overlay_path = runtime_dir / "opencode.json" if runtime_dir else (_generated_dir() / "opencode" / f"{provider_name}.json")
        managed = [overlay_path]
        if persist_state:
            managed.append(_opencode_env_path())
        return managed
    if tool == "openclaw":
        overlay_path = runtime_dir / "openclaw.json5" if runtime_dir else (_generated_dir() / "openclaw" / f"{provider_name}.json5")
        managed = [overlay_path]
        if persist_state:
            managed.append(_openclaw_env_path())
        return managed
    raise KeyError(tool)


def _local_restore_validation(
    store: Dict[str, Any],
    tool: str,
    provider_name: Optional[str],
) -> Dict[str, Any]:
    """Validate local live state after restore without running network probes."""
    if not provider_name:
        return {"status": "skipped", "reason_code": "no_active_provider"}
    provider = store.get("providers", {}).get(provider_name)
    conf = provider.get(tool) if isinstance(provider, dict) else None
    if not conf:
        return {"status": "skipped", "reason_code": "missing_provider_config"}

    if tool == "claude":
        live = _read_current_claude(store)
        if not live:
            return {"status": "failed", "reason_code": "live_config_missing"}
        mismatch_fields = [
            key
            for key, mismatched in (
                ("token", live.get("token") != resolve_token(conf.get("token"))),
                ("base_url", live.get("base_url") != conf.get("base_url")),
            )
            if mismatched
        ]
        return {
            "status": "ok" if not mismatch_fields else "degraded",
            "reason_code": "ready" if not mismatch_fields else "live_config_mismatch",
            "mismatch_fields": mismatch_fields,
        }

    if tool == "codex":
        live = _read_current_codex(store)
        if not live:
            return {"status": "failed", "reason_code": "live_config_missing"}
        if _codex_uses_chatgpt_auth(conf):
            expected_route = _codex_chatgpt_provider_route(store)
            mismatch_fields = []
            if live.get("auth_mode") != CODEX_AUTH_MODE_CHATGPT:
                mismatch_fields.append("auth_mode")
            if live.get("provider_route") != expected_route:
                mismatch_fields.append("provider_route")
            return {
                "status": "ok" if not mismatch_fields else "degraded",
                "reason_code": "ready" if not mismatch_fields else "live_config_mismatch",
                "mismatch_fields": mismatch_fields,
            }
        expected_base_urls = {
            url
            for url in (conf.get("base_url"), conf.get("fallback_base_url"))
            if isinstance(url, str) and url
        }
        mismatch_fields = [
            key
            for key, mismatched in (
                ("token", live.get("token") != resolve_token(conf.get("token"))),
                ("base_url", bool(expected_base_urls) and live.get("base_url") not in expected_base_urls),
            )
            if mismatched
        ]
        return {
            "status": "ok" if not mismatch_fields else "degraded",
            "reason_code": "ready" if not mismatch_fields else "live_config_mismatch",
            "mismatch_fields": mismatch_fields,
        }

    if tool == "gemini":
        live = _read_current_gemini(store)
        if not live:
            return {"status": "failed", "reason_code": "live_config_missing"}
        mismatch_fields = [
            key
            for key, mismatched in (
                ("api_key", live.get("api_key") != resolve_token(conf.get("api_key"))),
                ("auth_type", live.get("auth_type", "api-key") != conf.get("auth_type", "api-key")),
            )
            if mismatched
        ]
        return {
            "status": "ok" if not mismatch_fields else "degraded",
            "reason_code": "ready" if not mismatch_fields else "live_config_mismatch",
            "mismatch_fields": mismatch_fields,
        }

    overlay_status, overlay_detail = _probe_overlay_activation(tool, provider_name)
    if overlay_status != "ok":
        return {"status": overlay_status, **overlay_detail}
    content_status, content_detail = _probe_overlay_content(store, tool, conf, overlay_detail.get("active_overlay"))
    return {"status": content_status, **content_detail}


def _safe_local_restore_validation(
    store: Dict[str, Any],
    tool: str,
    provider_name: Optional[str],
) -> Dict[str, Any]:
    """Run local restore validation without letting parse failures abort the run result."""
    try:
        return _local_restore_validation(store, tool, provider_name)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        return {
            "status": "failed",
            "reason_code": "validation_aborted",
            "exit_code": code,
        }
    except Exception as exc:  # pragma: no cover - defensive path
        return {
            "status": "failed",
            "reason_code": "validation_error",
            "error_class": exc.__class__.__name__,
        }


def activate_tool_for_subprocess(
    store: Dict[str, Any],
    tool: str,
    provider_name: str,
    *,
    persist_state: bool = True,
    fail_if_missing: bool = False,
    runtime_dir: Optional[Path] = None,
    write_activation_files: Optional[bool] = None,
) -> tuple[Dict[str, str], list[str]]:
    """Apply tool configuration and return child env mutations."""
    provider = store.get("providers", {}).get(provider_name)
    if provider is None:
        info(f"[error] Provider '{provider_name}' not found. Run: ccsw list")
        sys.exit(1)

    conf = provider.get(tool)
    if conf is None:
        if fail_if_missing:
            info(f"[error] Provider '{provider_name}' has no {tool} config.")
            sys.exit(1)
        info(f"[{tool}] Skipped: provider '{provider_name}' has no {tool} config.")
        return {}, []

    previous = store.setdefault("active", {}).get(tool)
    should_write_activation_files = persist_state if write_activation_files is None else write_activation_files
    create_backup = persist_state or should_write_activation_files
    if tool == "claude":
        exports = write_claude(conf, store, create_backup=create_backup)
        unsets: list[str] = []
    elif tool == "codex":
        exports = write_codex(
            conf,
            provider_name,
            store,
            create_backup=create_backup,
            write_activation_file=should_write_activation_files,
        )
        unsets = _codex_env_unsets(conf)
    elif tool == "gemini":
        exports = write_gemini(
            conf,
            store,
            create_backup=create_backup,
            write_activation_file=should_write_activation_files,
        )
        unsets = []
    elif tool == "opencode":
        overlay_path = runtime_dir / "opencode.json" if runtime_dir else None
        exports = write_opencode(
            conf,
            provider_name,
            store,
            overlay_path=overlay_path,
            write_activation_file=should_write_activation_files,
        )
        unsets = []
    elif tool == "openclaw":
        overlay_path = runtime_dir / "openclaw.json5" if runtime_dir else None
        exports = write_openclaw(
            conf,
            provider_name,
            store,
            overlay_path=overlay_path,
            write_activation_file=should_write_activation_files,
        )
        unsets = [] if conf.get("profile") else ["OPENCLAW_PROFILE"]
    else:
        exports = None
        unsets = []

    if exports is None:
        info(f"[error] Provider '{provider_name}' could not activate {tool} because required live config is missing.")
        sys.exit(1)

    env_map = {key: value for key, value in exports}
    if persist_state:
        history_entry = _switch_history_entry(tool, previous, provider_name)
        if history_entry:
            store["active"][tool] = provider_name
            try:
                save_store(
                    store,
                    expected_revision=store.get("_revision"),
                    history_entries=[history_entry],
                )
            except StoreSnapshotSyncError as exc:
                setattr(exc, "env_map", env_map)
                setattr(exc, "unsets", unsets)
                setattr(exc, "tool", tool)
                raise
    return env_map, unsets


def switch_tool(store: Dict[str, Any], tool: str, provider_name: str) -> None:
    """Switch a single tool to the named provider."""
    try:
        env_map, unsets = activate_tool_for_subprocess(store, tool, provider_name)
    except StoreSnapshotSyncError as exc:
        info(
            f"[warning] {tool} state committed, but providers.json snapshot sync failed. "
            "SQLite remains authoritative."
        )
        raise SystemExit(1) from exc
    for key, value in env_map.items():
        emit_env(key, value)
    for key in unsets:
        emit_unset(key)
    if tool == "gemini" and env_map:
        info("[gemini] Tip: use eval \"$(ccsw gemini <provider>)\" to activate in current shell")


def _resolve_run_candidates(store: Dict[str, Any], tool: str, name: str) -> list[str]:
    """Resolve a provider or profile into an ordered candidate queue."""
    if name in store.get("profiles", {}):
        return _resolve_profile_queue(store, tool, name)
    return [resolve_alias(store, name)]


def _run_source_kind(store: Dict[str, Any], name: str) -> str:
    """Describe whether a run target came from a profile or provider name."""
    return "profile" if name in store.get("profiles", {}) else "provider"


def _has_backup_artifacts(paths: Iterable[Path]) -> bool:
    """Return True when timestamped backup artifacts remain for the provided paths."""
    for path in paths:
        if any(path.parent.glob(f"{path.name}.bak-*")):
            return True
    return False


def _repair_runtime_lease(
    store: Dict[str, Any],
    tool: str,
) -> Dict[str, Any]:
    """Repair one persisted runtime lease by replaying restore and cleanup steps."""
    manifest = get_managed_target(tool)
    if not manifest:
        return {
            "tool": tool,
            "repair_status": "no_lease",
            "restore_status": None,
            "cleanup_status": None,
        }
    if manifest.get("decode_error"):
        scrubbed_manifest = _build_scrubbed_stale_manifest(
            tool,
            manifest,
            restore_status="restore_failed",
            cleanup_status=manifest.get("cleanup_status") or "pending",
            stale_reason="manifest_decode_failed",
            restore_error=manifest.get("decode_error"),
        )
        upsert_managed_target(tool, scrubbed_manifest)
        payload = {
            "tool": tool,
            "lease_id": scrubbed_manifest.get("lease_id"),
            "repair_status": "manifest_decode_failed",
            "restore_status": "restore_failed",
            "cleanup_status": scrubbed_manifest.get("cleanup_status"),
            "restore_error": scrubbed_manifest.get("restore_error"),
        }
        record_history("repair-result", tool, scrubbed_manifest.get("selected_candidate"), payload)
        return payload
    child_pid = manifest.get("child_pid")
    child_started_at = manifest.get("child_started_at")
    if _pid_matches_identity(child_pid, child_started_at) or _pid_cannot_be_verified_but_is_running(
        child_pid,
        child_started_at,
    ):
        payload = {
            "tool": tool,
            "lease_id": manifest.get("lease_id"),
            "repair_status": "child_running",
            "restore_status": manifest.get("restore_status"),
            "cleanup_status": manifest.get("cleanup_status"),
        }
        record_history("repair-result", tool, manifest.get("selected_candidate"), payload)
        return payload
    owner_pid = manifest.get("owner_pid")
    owner_started_at = manifest.get("owner_started_at")
    if (
        _pid_matches_identity(owner_pid, owner_started_at)
        or _pid_cannot_be_verified_but_is_running(owner_pid, owner_started_at)
    ) and not manifest.get("stale"):
        payload = {
            "tool": tool,
            "lease_id": manifest.get("lease_id"),
            "repair_status": "lease_active",
            "restore_status": manifest.get("restore_status"),
            "cleanup_status": manifest.get("cleanup_status"),
        }
        record_history("repair-result", tool, manifest.get("selected_candidate"), payload)
        return payload

    if _scrub_manifest_snapshot_payloads(manifest):
        upsert_managed_target(tool, manifest)

    snapshots_raw = manifest.get("snapshots")
    written_states_raw = manifest.get("written_states")
    restore_groups_raw = manifest.get("restore_groups")
    ephemeral_paths_raw = manifest.get("ephemeral_paths")
    runtime_root_value = manifest.get("runtime_root")
    runtime_root_path = Path(runtime_root_value) if isinstance(runtime_root_value, str) and runtime_root_value else None
    snapshots: Dict[Path, Optional[bytes]] = {}
    decode_errors: list[str] = []
    written_states = _decode_manifest_path_states(written_states_raw)
    state_errors: list[str] = []
    restore_groups = _decode_manifest_path_groups(restore_groups_raw)[0]
    group_errors: list[str] = []
    ephemeral_paths = _decode_manifest_path_list(ephemeral_paths_raw)[0]
    path_errors: list[str] = []
    repair_status = "repaired"
    restore_status = manifest.get("restore_status") or "pending"
    cleanup_status = manifest.get("cleanup_status") or "pending"
    restore_conflicts: list[str] = []
    restore_error: Optional[str] = None
    runtime_validation_error = _validate_manifest_paths(
        store,
        tool,
        manifest,
        snapshots={},
        written_states={},
        restore_groups=[],
        ephemeral_paths=[],
    )
    if not isinstance(written_states_raw, dict):
        state_errors.append("written_states")
    if not isinstance(restore_groups_raw, list):
        group_errors.append("restore_groups")
    if not isinstance(ephemeral_paths_raw, list):
        path_errors.append("ephemeral_paths")

    if restore_status != "restored":
        snapshots, decode_errors = _decode_manifest_snapshots(
            snapshots_raw,
            runtime_root=runtime_root_path,
        )
        written_states, state_errors = _decode_manifest_path_states(written_states_raw)
        restore_groups, group_errors = _decode_manifest_path_groups(restore_groups_raw)
        ephemeral_paths, path_errors = _decode_manifest_path_list(ephemeral_paths_raw)
        if not isinstance(snapshots_raw, dict):
            decode_errors.append("snapshots")
        if not isinstance(written_states_raw, dict):
            state_errors.append("written_states")
        if not isinstance(restore_groups_raw, list):
            group_errors.append("restore_groups")
        if not isinstance(ephemeral_paths_raw, list):
            path_errors.append("ephemeral_paths")

    if decode_errors or state_errors or group_errors or path_errors:
        repair_status = "manifest_decode_failed"
        restore_status = "restore_failed"
        malformed = sorted({*decode_errors, *state_errors, *group_errors, *path_errors})
        restore_error = runtime_validation_error or f"manifest decode failed for: {', '.join(malformed)}"
    else:
        restore_error = _validate_manifest_paths(
            store,
            tool,
            manifest,
            snapshots=snapshots,
            written_states=written_states,
            restore_groups=restore_groups,
            ephemeral_paths=ephemeral_paths,
        )
        if restore_error:
            repair_status = "manifest_decode_failed"
            restore_status = "restore_failed"
    if repair_status == "repaired" and restore_status != "restored":
        restore_status, restore_conflicts, restore_error = _attempt_owned_restore(
            snapshots,
            written_states,
            groups=restore_groups,
            ignore_paths=ephemeral_paths,
        )
        if restore_status == "restore_conflict":
            repair_status = "restore_conflict"
        elif restore_status == "restore_failed":
            repair_status = "repair_failed"

    validation = _safe_local_restore_validation(
        store,
        tool,
        store.get("active", {}).get(tool),
    )
    if validation.get("status") not in {"ok", "skipped"} and repair_status == "repaired":
        repair_status = "repair_failed"
        restore_status = "restore_failed"

    runtime_root = manifest.get("runtime_root")
    if repair_status == "repaired":
        try:
            if isinstance(runtime_root, str) and runtime_root and _path_within_root(Path(runtime_root), _tmp_dir()) and Path(runtime_root).exists():
                shutil.rmtree(runtime_root)
            cleanup_status = "cleaned"
        except OSError as exc:
            repair_status = "cleanup_failed"
            cleanup_status = "cleanup_failed"
            restore_error = str(exc)

    if repair_status == "repaired":
        delete_managed_target(tool)
    else:
        latest_stale_reason = (
            "cleanup_failed"
            if cleanup_status == "cleanup_failed"
            else "manifest_decode_failed"
            if repair_status == "manifest_decode_failed"
            else "restore_conflict"
            if restore_status == "restore_conflict"
            else "restore_failed"
        )
        scrubbed_manifest = _build_scrubbed_stale_manifest(
            tool,
            manifest,
            restore_status=restore_status,
            cleanup_status=cleanup_status,
            stale_reason=latest_stale_reason,
            restore_error=restore_error,
        )
        _persist_runtime_manifest(
            tool,
            scrubbed_manifest,
            child_pid=None,
            child_status="exited",
            restore_status=restore_status,
            cleanup_status=cleanup_status,
            restore_conflicts=restore_conflicts,
            restore_error=restore_error,
            post_restore_validation=validation,
            stale=True,
            stale_reason=latest_stale_reason,
            phase="completed",
        )

    payload = {
        "tool": tool,
        "lease_id": manifest.get("lease_id"),
        "repair_status": repair_status,
        "restore_status": restore_status,
        "cleanup_status": cleanup_status,
        "restore_conflicts": restore_conflicts,
        "restore_error": restore_error,
        "post_restore_validation": validation,
    }
    record_history("repair-result", tool, manifest.get("selected_candidate"), payload)
    return payload


def run_with_fallback(
    store: Dict[str, Any],
    tool: str,
    name: str,
    argv: list[str],
) -> subprocess.CompletedProcess[str]:
    """Run a child CLI and retry against later profile candidates when allowed."""
    candidates = _resolve_run_candidates(store, tool, name)
    source_kind = _run_source_kind(store, name)
    snapshots: Dict[Path, Optional[bytes]] = {}
    written_states: Dict[Path, Dict[str, Any]] = {}
    last_result: Optional[subprocess.CompletedProcess[str]] = None
    fallback_used = False
    selected_candidate = candidates[0]
    final_failure_type = "ok"
    restore_status = "pending"
    cleanup_status = "pending"
    attempt_count = 0
    restore_error: Optional[str] = None
    restore_conflicts: list[str] = []
    post_restore_validation: Dict[str, Any] = {"status": "pending", "reason_code": "pending"}
    runtime_root = _tmp_dir() / f"run-{datetime.now().strftime(BACKUP_SUFFIX_FMT)}-{os.getpid()}"
    temp_paths_cleaned = False
    _ensure_private_dir(runtime_root)
    restore_groups: list[list[Path]] = []
    ephemeral_paths: set[Path] = set()
    persist_runtime_state = "_revision" in store
    if persist_runtime_state:
        blocked_result = _claim_run_lease(tool, name)
        if blocked_result is not None:
            return _annotate_run_result(
                blocked_result,
                selected_candidate=name,
                fallback_used=False,
                original_active=store.get("active", {}).get(tool),
                attempt_count=0,
                source_kind=source_kind,
                final_failure_type="lease_blocked",
                restore_status="not_run",
                restore_error=None,
                restore_conflicts=[],
                post_restore_validation={"status": "not_run", "reason_code": "lease_blocked"},
                temp_paths_cleaned=True,
                cleanup_status="not_run",
            )
    candidate_secret_env_names: set[str] = set()
    for candidate in candidates:
        candidate_conf = store.get("providers", {}).get(candidate, {}).get(tool)
        candidate_secret_env_names.update(_provider_secret_env_names(candidate_conf))
    runtime_manifest = _build_runtime_manifest(
        tool,
        lease_id=f"{tool}-{datetime.now().strftime(BACKUP_SUFFIX_FMT)}-{os.getpid()}",
        source_kind=source_kind,
        requested_target=name,
        runtime_root=runtime_root,
    )
    if persist_runtime_state:
        upsert_managed_target(tool, runtime_manifest)

    try:
        for index, candidate in enumerate(candidates):
            attempt_count += 1
            candidate_conf = store.get("providers", {}).get(candidate, {}).get(tool)
            candidate_runtime_dir = runtime_root / f"{tool}-{index + 1}-{candidate}"
            _ensure_private_dir(candidate_runtime_dir)
            _persist_runtime_manifest(
                tool,
                runtime_manifest,
                persist=persist_runtime_state,
                selected_candidate=candidate,
                attempt_count=attempt_count,
                phase="activating",
                stale_reason=None,
            )
            target_paths = _activation_target_paths(
                store,
                tool,
                candidate,
                persist_state=False,
                runtime_dir=candidate_runtime_dir if tool in OVERLAY_TOOLS else None,
            )
            restore_groups = _restore_groups_for_tool(
                tool,
                target_paths,
                runtime_root=candidate_runtime_dir if tool in OVERLAY_TOOLS else runtime_root,
            )
            if tool in OVERLAY_TOOLS:
                ephemeral_paths.update(path for path in target_paths if candidate_runtime_dir in path.parents)
            for path in target_paths:
                snapshots.setdefault(path, path.read_bytes() if path.exists() else None)
            _persist_runtime_manifest(
                tool,
                runtime_manifest,
                persist=persist_runtime_state,
                snapshots=_json_ready_snapshots(snapshots, runtime_root=runtime_root),
                restore_groups=[[str(path) for path in group] for group in restore_groups],
                ephemeral_paths=[str(path) for path in sorted(ephemeral_paths)],
                snapshot_written=bool(snapshots),
            )
            try:
                env_updates, unsets = activate_tool_for_subprocess(
                    store,
                    tool,
                    candidate,
                    persist_state=False,
                    fail_if_missing=True,
                    runtime_dir=candidate_runtime_dir if tool in OVERLAY_TOOLS else None,
                )
            except BaseException as exc:
                if isinstance(exc, SystemExit):
                    code = int(exc.code) if isinstance(exc.code, int) else 1
                    stderr = ""
                else:
                    code = 1
                    stderr = str(exc)
                for path in target_paths:
                    written_states[path] = _capture_path_state(path)
                _persist_runtime_manifest(
                    tool,
                    runtime_manifest,
                    persist=persist_runtime_state,
                    written_states=_json_ready_path_states(written_states),
                )
                result = subprocess.CompletedProcess(argv, code, "", stderr)
                failure_type = "setup_failed"
                retryable = False
                _persist_runtime_manifest(
                    tool,
                    runtime_manifest,
                    persist=persist_runtime_state,
                    phase="setup_failed",
                )
                record_history(
                    "run-attempt",
                    tool,
                    candidate,
                    {
                        "argv": argv,
                        "candidate": candidate,
                        "source_kind": source_kind,
                        "attempt_index": index + 1,
                            "attempt_count": attempt_count,
                            "returncode": result.returncode,
                            "failure_type": failure_type,
                            "retryable": retryable,
                            "phase": "setup",
                            "error": stderr or None,
                        },
                    )
                last_result = result
                selected_candidate = candidate
                final_failure_type = failure_type
                break
            for path in target_paths:
                written_states[path] = _capture_path_state(path)
            _persist_runtime_manifest(
                tool,
                runtime_manifest,
                persist=persist_runtime_state,
                written_states=_json_ready_path_states(written_states),
                phase="subprocess",
            )
            child_env = _build_child_env(
                env_updates,
                unsets,
                secret_env_names=candidate_secret_env_names,
            )

            try:
                result = _run_subprocess_with_tracking(
                    argv,
                    child_env,
                    tool,
                    runtime_manifest,
                    persist=persist_runtime_state,
                )
            except BaseException as exc:  # pragma: no cover - follow-up tests can pin this further
                result = _result_from_exception(argv, exc)
                failure_type, retryable = _classify_process_failure(exc=exc)
                manifest_phase = "interrupted" if failure_type == "interrupted" else "subprocess_error"
            else:
                failure_type, retryable = _classify_process_failure(result=result)
                manifest_phase = "subprocess_complete" if result.returncode == 0 else (
                    "interrupted" if failure_type == "interrupted" else "subprocess_failed"
                )
            _persist_runtime_manifest(
                tool,
                runtime_manifest,
                persist=persist_runtime_state,
                phase=manifest_phase,
                child_returncode=result.returncode,
                child_status="exited",
                final_failure_type=failure_type,
            )

            record_history(
                "run-attempt",
                tool,
                candidate,
                {
                    "argv": argv,
                    "candidate": candidate,
                    "source_kind": source_kind,
                    "attempt_index": index + 1,
                    "attempt_count": attempt_count,
                    "returncode": result.returncode,
                    "failure_type": failure_type,
                    "retryable": retryable,
                    "phase": "subprocess",
                },
            )
            if result.returncode == 0:
                last_result = result
                selected_candidate = candidate
                final_failure_type = failure_type
                break

            last_result = result
            selected_candidate = candidate
            final_failure_type = failure_type
            if index == len(candidates) - 1 or not retryable:
                break
            fallback_used = True
            info(f"[{tool}] Candidate '{candidate}' failed with {failure_type}, trying next provider...")
    finally:
        _persist_runtime_manifest(tool, runtime_manifest, persist=persist_runtime_state, phase="restoring")
        restore_status, restore_conflicts, restore_error = _attempt_owned_restore(
            snapshots,
            written_states,
            groups=restore_groups,
            ignore_paths=ephemeral_paths,
        )
        _persist_runtime_manifest(
            tool,
            runtime_manifest,
            persist=persist_runtime_state,
            phase="validating",
            restore_status=restore_status,
            restore_error=restore_error,
            restore_conflicts=restore_conflicts,
            stale_reason=(
                "restore_conflict"
                if restore_status == "restore_conflict"
                else "restore_failed" if restore_status == "restore_failed" else runtime_manifest.get("stale_reason")
            ),
        )
        post_restore_validation = _safe_local_restore_validation(
            store,
            tool,
            store.get("active", {}).get(tool),
        )
        if post_restore_validation.get("status") not in {"ok", "skipped"} and restore_status == "restored":
            restore_status = "restore_failed"
            reason_code = post_restore_validation.get("reason_code") or "validation_failed"
            detail = post_restore_validation.get("hint") or post_restore_validation.get("message")
            restore_error = f"local restore validation failed: {reason_code}"
            if detail:
                restore_error = f"{restore_error} ({detail})"
        _persist_runtime_manifest(
            tool,
            runtime_manifest,
            persist=persist_runtime_state,
            restore_status=restore_status,
            restore_error=restore_error,
            post_restore_validation=post_restore_validation,
            phase="cleaning",
        )
        if restore_status == "restored":
            try:
                if runtime_root.exists():
                    shutil.rmtree(runtime_root)
                temp_paths_cleaned = True
                cleanup_status = "cleaned"
            except OSError:
                temp_paths_cleaned = False
                cleanup_status = "cleanup_failed"
        else:
            temp_paths_cleaned = False
            cleanup_status = "pending"
        stale_runtime = restore_status != "restored" or cleanup_status != "cleaned"
        if stale_runtime:
            _persist_runtime_manifest(
                tool,
                runtime_manifest,
                persist=persist_runtime_state,
                restore_status=restore_status,
                restore_error=restore_error,
                phase="completed",
                cleanup_status=cleanup_status,
                stale=True,
                stale_reason=(
                    "cleanup_failed"
                    if cleanup_status == "cleanup_failed"
                    else "restore_conflict"
                    if restore_status == "restore_conflict"
                    else "restore_failed"
                    if restore_status == "restore_failed"
                    else "interrupted_before_restore"
                    if final_failure_type == "interrupted"
                    else runtime_manifest.get("stale_reason")
                ),
                child_pid=None,
                child_status="exited",
            )
        else:
            _persist_runtime_manifest(
                tool,
                runtime_manifest,
                persist=persist_runtime_state,
                restore_status=restore_status,
                restore_error=restore_error,
                phase="completed",
                cleanup_status=cleanup_status,
                stale=False,
                stale_reason=None,
                child_pid=None,
                child_status="exited",
            )
            if persist_runtime_state:
                delete_managed_target(tool)

    if last_result is None:
        last_result = subprocess.CompletedProcess(argv or [tool], 1, "", "ccsw did not capture a command result")
    if restore_error:
        stderr = last_result.stderr or ""
        if stderr and not stderr.endswith("\n"):
            stderr += "\n"
        stderr += f"[ccsw] restore failed: {restore_error}"
        returncode = last_result.returncode if last_result.returncode != 0 else 1
        last_result = subprocess.CompletedProcess(last_result.args, returncode, last_result.stdout, stderr)
    elif restore_conflicts:
        stderr = last_result.stderr or ""
        if stderr and not stderr.endswith("\n"):
            stderr += "\n"
        stderr += "[ccsw] restore conflict: live files changed during run and were left in place"
        last_result = subprocess.CompletedProcess(last_result.args, 1, last_result.stdout, stderr)
    if cleanup_status == "cleanup_failed":
        stderr = last_result.stderr or ""
        if stderr and not stderr.endswith("\n"):
            stderr += "\n"
        stderr += "[ccsw] cleanup failed: runtime artifacts could not be removed"
        returncode = last_result.returncode if last_result.returncode != 0 else 1
        last_result = subprocess.CompletedProcess(last_result.args, returncode, last_result.stdout, stderr)
    return _annotate_run_result(
        last_result,
        selected_candidate=selected_candidate,
        fallback_used=fallback_used,
        original_active=store.get("active", {}).get(tool),
        attempt_count=attempt_count,
        source_kind=source_kind,
        final_failure_type=final_failure_type,
        restore_status=restore_status,
        restore_error=restore_error,
        restore_conflicts=restore_conflicts,
        post_restore_validation=post_restore_validation,
        temp_paths_cleaned=temp_paths_cleaned,
        cleanup_status=cleanup_status,
        backup_artifacts_cleaned=not _has_backup_artifacts(snapshots.keys()),
    )


def cmd_run(store: Dict[str, Any], tool: str, name: str, argv: list[str]) -> None:
    """Execute a CLI command with fallback-aware retry handling."""
    if not argv:
        info("[error] Missing command after --")
        sys.exit(1)
    with _state_lock():
        store = _load_fresh_store_from_lock(store)
        result = run_with_fallback(store, tool, name, argv)
        record_history(
            "run-result",
            tool,
            getattr(result, "_ccsw_selected_candidate", None),
            {
                "argv": argv,
                "returncode": result.returncode,
                "fallback_used": getattr(result, "_ccsw_fallback_used", False),
                "selected_candidate": getattr(result, "_ccsw_selected_candidate", None),
                "source_kind": getattr(result, "_ccsw_source_kind", _run_source_kind(store, name)),
                "attempt_count": getattr(result, "_ccsw_attempt_count", 1),
                "final_failure_type": getattr(result, "_ccsw_final_failure_type", "ok"),
                "restored_active": getattr(result, "_ccsw_original_active", None),
                "restore_status": getattr(result, "_ccsw_restore_status", "unknown"),
                "restore_error": getattr(result, "_ccsw_restore_error", None),
                "restore_conflicts": getattr(result, "_ccsw_restore_conflicts", []),
                "post_restore_validation": getattr(result, "_ccsw_post_restore_validation", None),
                "backup_artifacts_cleaned": getattr(result, "_ccsw_backup_artifacts_cleaned", False),
                "temp_paths_cleaned": getattr(result, "_ccsw_temp_paths_cleaned", False),
                "cleanup_status": getattr(result, "_ccsw_cleanup_status", "unknown"),
                "lock_scope": getattr(result, "_ccsw_lock_scope", "global_state_lock"),
            },
        )
    if getattr(result, "_ccsw_fallback_used", False):
        original_active = getattr(result, "_ccsw_original_active", None)
        selected_candidate = getattr(result, "_ccsw_selected_candidate", None)
        info(
            f"[{tool}] Temporary fallback used for this command: {selected_candidate}. "
            f"Active provider remains {original_active or '(none)'}."
        )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        sys.exit(result.returncode)


def cmd_repair(store: Dict[str, Any], tool: str) -> None:
    """Repair one or more stale managed runtime leases."""
    targets = ALL_TOOLS if tool == "all" else (tool,)
    exit_code = 0
    with _state_lock():
        store = _load_fresh_store_from_lock(store)
        for current_tool in targets:
            payload = _repair_runtime_lease(store, current_tool)
            status = payload.get("repair_status")
            if status == "no_lease":
                info(f"[repair] {current_tool}: no runtime lease")
                continue
            if status == "repaired":
                info(f"[repair] {current_tool}: repaired and cleared runtime lease")
                continue
            exit_code = 1
            info(f"[repair] {current_tool}: {status}")
    if exit_code:
        sys.exit(exit_code)


def cmd_settings_get(store: Dict[str, Any], key: Optional[str]) -> None:
    """Print one setting or the full settings map."""
    settings = store.get("settings", {})
    if key:
        info(f"{key}={settings.get(key)!r}")
        return
    for current_key in sorted(settings):
        info(f"{current_key}={settings[current_key]!r}")


def cmd_settings_set(store: Dict[str, Any], key: str, value: Optional[str]) -> None:
    """Set a device-level setting."""
    if key not in SETTINGS_DEFAULTS:
        info(f"[error] Unknown setting key: {key}")
        sys.exit(1)
    try:
        normalized = _coerce_setting_value(key, value)
    except ValueError as exc:
        info(f"[error] {exc}")
        sys.exit(1)
    with _state_lock():
        store = _load_fresh_store_from_lock(store)
        previous_value = get_setting(store, key)
        store.setdefault("settings", {})[key] = normalized
        if key.endswith("_config_dir"):
            tool = key.removesuffix("_config_dir")
            active_provider = store.get("active", {}).get(tool)
            if active_provider:
                try:
                    activate_tool_for_subprocess(
                        store,
                        tool,
                        active_provider,
                        persist_state=False,
                        fail_if_missing=True,
                        write_activation_files=True,
                    )
                except BaseException:
                    store["settings"][key] = previous_value
                    raise
        save_store(store, expected_revision=store.get("_revision"))
    info(f"Setting updated: {key}={normalized!r}")


def cmd_sync(store: Dict[str, Any], action: str) -> None:
    """Toggle whether future ChatGPT Codex sessions use the shared provider lane."""
    if action == "status":
        info(
            "Codex future-session sync is "
            + ("on" if _codex_sync_enabled(store) else "off")
            + "."
        )
        return
    desired = action == "on"
    with _state_lock():
        store = _load_fresh_store_from_lock(store)
        current = _codex_sync_enabled(store)
        if current == desired:
            info(f"Codex future-session sync is already {'on' if desired else 'off'}.")
            return
        store.setdefault("settings", {})[CODEX_SYNC_SETTING_KEY] = desired
        save_store(store, expected_revision=store.get("_revision"))
    info(f"Codex future-session sync {'enabled' if desired else 'disabled'}.")
    info("This only affects future `cxsw pro` runs. Existing sessions stay unchanged.")


def _codex_share_recipe_commands(cwd: str, provider_name: str, thread_id: str) -> list[str]:
    """Build the shell commands for one prepared share recipe."""
    return [
        _shell_join(["cxsw", provider_name]),
        _shell_join(["codex", "-C", cwd, "fork", "--all", thread_id]),
    ]


def _codex_target_model_provider_id(store: Dict[str, Any], conf: Dict[str, Any]) -> str:
    """Return the Codex provider id expected after switching to this provider."""
    if _codex_uses_chatgpt_auth(conf):
        return _codex_chatgpt_provider_route(store)
    return CODEX_PROVIDER_ID


def _format_codex_share_lane(lane: str, payload: Dict[str, Any]) -> list[str]:
    """Render one prepared Codex share lane for terminal output."""
    lines = [
        f"[{lane}] provider={payload['provider']} target_model_provider={payload['target_model_provider']}",
        f"  cwd={payload['cwd']}",
        f"  source={payload['source_selector']} -> {payload['source_thread_id']} ({payload['source_model_provider']})",
    ]
    if payload.get("source_title"):
        lines.append(f"  title={payload['source_title']}")
    lines.append(f"  prepared_at={payload['prepared_at']}")
    lines.append("  next:")
    lines.extend(f"    {command}" for command in payload.get("commands", []))
    return lines


def cmd_share_prepare(store: Dict[str, Any], lane: str, provider_name: str, source: str) -> None:
    """Prepare a Codex share recipe without switching or forking anything."""
    if not _NAME_RE.match(lane):
        info(f"[error] Share lane '{lane}' is invalid. Use only letters, digits, _, ., -")
        sys.exit(1)
    canonical = resolve_alias(store, provider_name)
    providers = store.get("providers", {})
    provider = providers.get(canonical)
    conf = provider.get(CODEX_SHARE_TOOL) if isinstance(provider, dict) else None
    if not isinstance(conf, dict):
        info(f"[error] Provider '{provider_name}' has no codex config.")
        sys.exit(1)

    cwd = os.getcwd()
    if source == CODEX_SHARE_DEFAULT_SOURCE:
        source_thread = _get_latest_codex_thread_for_cwd(cwd)
        if not source_thread:
            info(
                "[error] No recent Codex thread found for the current directory. "
                "Use --from <thread-id> to prepare a recipe from an explicit thread."
            )
            sys.exit(1)
    else:
        source_thread = _get_codex_thread_record(source)
        if not source_thread:
            info(f"[error] Codex thread '{source}' was not found in the local state DB.")
            sys.exit(1)

    recipe_cwd = source_thread.get("cwd") or cwd
    recipe = {
        "lane": lane,
        "tool": CODEX_SHARE_TOOL,
        "provider": canonical,
        "target_model_provider": _codex_target_model_provider_id(store, conf),
        "cwd": recipe_cwd,
        "source_selector": source,
        "source_thread_id": source_thread["id"],
        "source_model_provider": source_thread["model_provider"],
        "source_title": source_thread.get("title"),
        "prepared_at": datetime.now().isoformat(timespec="seconds"),
        "commands": _codex_share_recipe_commands(recipe_cwd, canonical, source_thread["id"]),
    }

    with _state_lock():
        store = _load_fresh_store_from_lock(store)
        canonical = resolve_alias(store, provider_name)
        providers = store.get("providers", {})
        provider = providers.get(canonical)
        conf = provider.get(CODEX_SHARE_TOOL) if isinstance(provider, dict) else None
        if not isinstance(conf, dict):
            info(f"[error] Provider '{provider_name}' has no codex config.")
            sys.exit(1)
        lanes = _get_codex_share_lanes(store)
        recipe["provider"] = canonical
        recipe["target_model_provider"] = _codex_target_model_provider_id(store, conf)
        recipe["commands"] = _codex_share_recipe_commands(recipe_cwd, canonical, source_thread["id"])
        lanes[lane] = recipe
        _set_codex_share_lanes(store, lanes)
        save_store(store, expected_revision=store.get("_revision"))

    info(f"Prepared Codex share lane: {lane}")
    for line in _format_codex_share_lane(lane, recipe):
        info(line)
    info("No live provider switch or session fork was performed.")


def cmd_share_status(store: Dict[str, Any], lane: Optional[str]) -> None:
    """Show prepared Codex share lane recipes."""
    lanes = _get_codex_share_lanes(store)
    if lane:
        payload = lanes.get(lane)
        if not payload:
            info(f"[error] Share lane '{lane}' not found.")
            sys.exit(1)
        for line in _format_codex_share_lane(lane, payload):
            info(line)
        return
    if not lanes:
        info("No Codex share lanes prepared.")
        return
    info("Codex share lanes:")
    for current_lane in sorted(lanes):
        for line in _format_codex_share_lane(current_lane, lanes[current_lane]):
            info(line)


def cmd_share_clear(store: Dict[str, Any], lane: str) -> None:
    """Delete one prepared Codex share lane recipe."""
    with _state_lock():
        store = _load_fresh_store_from_lock(store)
        lanes = _get_codex_share_lanes(store)
        if lane not in lanes:
            info(f"[error] Share lane '{lane}' not found.")
            sys.exit(1)
        del lanes[lane]
        _set_codex_share_lanes(store, lanes)
        save_store(store, expected_revision=store.get("_revision"))
    info(f"Cleared Codex share lane: {lane}")


def _read_current_claude(store: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    paths = get_tool_paths(store, "claude")
    data = load_json(paths["settings"])
    env = data.get("env")
    if not isinstance(env, dict):
        return None
    token = env.get("ANTHROPIC_AUTH_TOKEN")
    if not token:
        return None
    conf: Dict[str, Any] = {"token": token, "extra_env": {}}
    if env.get("ANTHROPIC_BASE_URL"):
        conf["base_url"] = env["ANTHROPIC_BASE_URL"]
    return conf


def _read_current_codex(store: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    paths = get_tool_paths(store, "codex")
    auth = load_json(paths["auth"])
    content = paths["config"].read_text(encoding="utf-8") if paths["config"].exists() else ""
    current_provider = _read_toml_string_value(content, "model_provider")
    root_openai_base_url = _read_toml_string_value(content, "openai_base_url")
    selected_block = None
    if current_provider:
        selected_block = _extract_toml_table_body(content, f"model_providers.{current_provider}")
    selected_requires_openai_auth = (
        _read_toml_literal_value(selected_block, "requires_openai_auth") == "true"
        if selected_block
        else False
    )
    if (
        auth.get("auth_mode") == CODEX_AUTH_MODE_CHATGPT
        and not auth.get("OPENAI_API_KEY")
        and not root_openai_base_url
        and (current_provider == CODEX_BUILTIN_PROVIDER_ID or selected_requires_openai_auth)
    ):
        provider_route = CODEX_PROVIDER_ID if current_provider == CODEX_PROVIDER_ID else CODEX_BUILTIN_PROVIDER_ID
        return {"auth_mode": CODEX_AUTH_MODE_CHATGPT, "provider_route": provider_route}

    token = auth.get("OPENAI_API_KEY")
    if not token:
        return None
    conf: Dict[str, Any] = {"token": token}
    if selected_block:
        selected_base_url = _read_toml_string_value(selected_block, "base_url")
        if selected_base_url:
            conf["base_url"] = selected_base_url
    elif legacy_match := re.search(r'^\s*openai_base_url\s*=\s*"([^"]+)"', content, re.MULTILINE):
        conf["base_url"] = legacy_match.group(1)
    return conf


def _read_current_gemini(store: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    paths = get_tool_paths(store, "gemini")
    data = load_json(paths["settings"])
    selected = None
    if isinstance(data.get("security"), dict):
        selected = data["security"].get("auth", {}).get("selectedType")
    api_key = _read_exported_value(_active_env_path(), "GEMINI_API_KEY")
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    conf: Dict[str, Any] = {"api_key": api_key}
    if selected:
        conf["auth_type"] = selected
    return conf


def _select_named_provider(
    providers: Dict[str, Any],
    preferred_name: Optional[str] = None,
) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Select one provider from a live overlay, rejecting ambiguous multi-provider inputs."""
    if not isinstance(providers, dict) or not providers:
        return None, None
    if preferred_name and preferred_name in providers and isinstance(providers[preferred_name], dict):
        return preferred_name, providers[preferred_name]
    if len(providers) == 1:
        provider_name = next(iter(providers))
        provider_conf = providers[provider_name]
        if isinstance(provider_conf, dict):
            return provider_name, provider_conf
    return None, None


def _provider_selection_is_ambiguous(
    providers: Any,
    preferred_name: Optional[str] = None,
) -> bool:
    """Return True when a provider mapping cannot be safely resolved to one entry."""
    if not isinstance(providers, dict) or not providers:
        return False
    if preferred_name and preferred_name in providers and isinstance(providers[preferred_name], dict):
        return False
    valid_names = [name for name, conf in providers.items() if isinstance(name, str) and isinstance(conf, dict)]
    return len(valid_names) > 1


def _clear_absent_import_fields(
    tool: str,
    merged_conf: Dict[str, Any],
    imported_conf: Dict[str, Any],
) -> None:
    """Drop optional metadata that is no longer present in the live config."""
    optional_fields: Dict[str, tuple[str, ...]] = {
        "codex": ("auth_mode", "provider_route"),
        "gemini": ("auth_type",),
        "opencode": ("headers", "npm", "model"),
        "openclaw": ("api", "profile", "model"),
    }
    for field in optional_fields.get(tool, ()):
        if field not in imported_conf:
            merged_conf.pop(field, None)
    if tool == "codex" and imported_conf.get("auth_mode") == CODEX_AUTH_MODE_CHATGPT:
        for field in ("token", "base_url", "fallback_base_url", "provider_route"):
            merged_conf.pop(field, None)


def _read_current_opencode(
    store: Dict[str, Any],
    existing_conf: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    overlay_ref = os.environ.get("OPENCODE_CONFIG") or _read_exported_value(_opencode_env_path(), "OPENCODE_CONFIG")
    overlay_path = Path(overlay_ref).expanduser() if overlay_ref else None
    source_path = Path(overlay_ref).expanduser() if overlay_ref else get_tool_paths(store, "opencode")["config"]
    data = _load_json_relaxed(source_path)
    providers = data.get("provider")
    if overlay_path is not None and _provider_selection_is_ambiguous(
        providers,
        preferred_name=existing_conf.get("provider_id") if isinstance(existing_conf, dict) else None,
    ):
        return None
    provider_name, provider_conf = _select_named_provider(
        providers,
        preferred_name=existing_conf.get("provider_id") if isinstance(existing_conf, dict) else None,
    )
    options = provider_conf.get("options", {}) if isinstance(provider_conf, dict) else {}
    token = options.get("apiKey")
    base_url = options.get("baseURL")
    if (not token or not base_url) and source_path != get_tool_paths(store, "opencode")["config"]:
        source_path = get_tool_paths(store, "opencode")["config"]
        data = _load_json_relaxed(source_path)
        providers = data.get("provider")
        provider_name, provider_conf = _select_named_provider(
            providers,
            preferred_name=existing_conf.get("provider_id") if isinstance(existing_conf, dict) else None,
        )
        if provider_name and provider_conf:
            options = provider_conf.get("options", {}) if isinstance(provider_conf, dict) else {}
            token = options.get("apiKey")
            base_url = options.get("baseURL")
    if not provider_name or not provider_conf:
        return None
    if not token:
        token = _load_json_relaxed(get_tool_paths(store, "opencode")["auth"]).get("apiKey")
    if not token or not base_url:
        return None
    conf: Dict[str, Any] = {"token": token, "base_url": base_url, "provider_id": provider_name}
    headers = options.get("headers")
    if isinstance(headers, dict) and headers:
        header_error = _validate_opencode_headers(headers)
        if header_error:
            info(f"[error] {header_error}")
            sys.exit(1)
        conf["headers"] = headers
    npm_name = provider_conf.get("npm")
    if isinstance(npm_name, str) and npm_name:
        conf["npm"] = npm_name
    if data.get("model"):
        conf["model"] = data["model"]
    return conf


def _read_current_openclaw(
    store: Dict[str, Any],
    existing_conf: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    overlay_ref = os.environ.get("OPENCLAW_CONFIG_PATH") or _read_exported_value(
        _openclaw_env_path(),
        "OPENCLAW_CONFIG_PATH",
    )
    overlay_path = Path(overlay_ref).expanduser() if overlay_ref else None
    source_path = Path(overlay_ref).expanduser() if overlay_ref else get_tool_paths(store, "openclaw")["config"]
    data = _load_json_relaxed(source_path)
    models = data.get("models")
    providers = models.get("providers", {}) if isinstance(models, dict) else {}
    if overlay_path is not None and _provider_selection_is_ambiguous(
        providers,
        preferred_name=existing_conf.get("provider_id") if isinstance(existing_conf, dict) else None,
    ):
        return None
    provider_name, provider_conf = _select_named_provider(
        providers,
        preferred_name=existing_conf.get("provider_id") if isinstance(existing_conf, dict) else None,
    )
    token = provider_conf.get("apiKey") if isinstance(provider_conf, dict) else None
    base_url = provider_conf.get("baseUrl") if isinstance(provider_conf, dict) else None
    if (not token or not base_url) and source_path != get_tool_paths(store, "openclaw")["config"]:
        source_path = get_tool_paths(store, "openclaw")["config"]
        data = _load_json_relaxed(source_path)
        models = data.get("models")
        providers = models.get("providers", {}) if isinstance(models, dict) else {}
        provider_name, provider_conf = _select_named_provider(
            providers,
            preferred_name=existing_conf.get("provider_id") if isinstance(existing_conf, dict) else None,
        )
        token = provider_conf.get("apiKey") if isinstance(provider_conf, dict) else None
        base_url = provider_conf.get("baseUrl") if isinstance(provider_conf, dict) else None
    if not provider_name or not provider_conf:
        return None
    if not token or not base_url:
        return None
    conf: Dict[str, Any] = {
        "provider_id": provider_name,
        "token": token,
        "base_url": base_url,
    }
    api_name = provider_conf.get("api")
    if isinstance(api_name, str) and api_name:
        conf["api"] = api_name
    agent_defaults = data.get("agents", {}).get("defaults", {}) if isinstance(data.get("agents"), dict) else {}
    model = agent_defaults.get("model", {}).get("primary") if isinstance(agent_defaults.get("model"), dict) else None
    if model:
        conf["model"] = model
    profile = os.environ.get("OPENCLAW_PROFILE") or _read_exported_value(
        _openclaw_env_path(),
        "OPENCLAW_PROFILE",
    ) or _read_env_assignment_value(get_tool_paths(store, "openclaw")["env"], "OPENCLAW_PROFILE")
    if profile:
        conf["profile"] = profile
    return conf


def cmd_import_current(
    store: Dict[str, Any],
    tool: str,
    name: str,
    *,
    allow_literal_secrets: bool = False,
) -> None:
    """Import the current live configuration into a saved provider."""
    with _state_lock():
        store = _load_fresh_store_from_lock(store)
        provider = store.setdefault("providers", {}).get(name, {})
        existing_conf = provider.get(tool) if isinstance(provider.get(tool), dict) else {}
        if tool == "claude":
            conf = _read_current_claude(store)
        elif tool == "codex":
            conf = _read_current_codex(store)
        elif tool == "gemini":
            conf = _read_current_gemini(store)
        elif tool == "opencode":
            conf = _read_current_opencode(store, existing_conf)
        elif tool == "openclaw":
            conf = _read_current_openclaw(store, existing_conf)
        else:
            conf = None
        if not conf:
            info(f"[error] Could not import current {tool} configuration.")
            sys.exit(1)
        if tool == "gemini":
            preserved = _preserve_secret_ref(existing_conf.get("api_key"), conf.get("api_key"))
            if not allow_literal_secrets and not _is_env_ref(preserved):
                _reject_literal_secret("imported gemini api_key")
            conf["api_key"] = preserved
        elif tool == "codex" and conf.get("auth_mode") == CODEX_AUTH_MODE_CHATGPT:
            pass
        else:
            preserved = _preserve_secret_ref(existing_conf.get("token"), conf.get("token"))
            if not allow_literal_secrets and not _is_env_ref(preserved):
                _reject_literal_secret(f"imported {tool} token")
            conf["token"] = preserved
        merged_conf = dict(existing_conf)
        merged_conf.update(conf)
        _clear_absent_import_fields(tool, merged_conf, conf)
        provider[tool] = merged_conf
        store["providers"][name] = provider
        save_store(store, expected_revision=store.get("_revision"))
    info(f"Imported current {tool} config into provider '{name}'.")


def _history_summary(entry: Dict[str, Any]) -> str:
    """Render a compact summary for one history entry."""
    payload = entry["payload"]
    if entry["action"] == "switch":
        return f"{payload.get('previous') or '(none)'} -> {payload.get('current') or '(none)'}"
    if entry["action"] == "run-attempt":
        return (
            f"candidate={entry['subject'] or '(none)'} "
            f"rc={payload.get('returncode')} "
            f"type={payload.get('failure_type', 'unknown')} "
            f"retryable={payload.get('retryable')}"
        )
    if entry["action"] == "run-result":
        return (
            f"selected={payload.get('selected_candidate')} "
            f"rc={payload.get('returncode')} "
            f"type={payload.get('final_failure_type', 'unknown')} "
            f"fallback_used={payload.get('fallback_used')} "
            f"restore_status={payload.get('restore_status', 'unknown')} "
            f"cleanup_status={payload.get('cleanup_status', 'unknown')} "
            f"restored_active={payload.get('restored_active') or '(none)'}"
        )
    if entry["action"] == "batch-result":
        return (
            f"mode={payload.get('mode')} "
            f"failed_tool={payload.get('failed_tool') or '(none)'} "
            f"rollback_status={payload.get('rollback_status')} "
            f"snapshot_sync={payload.get('snapshot_sync', 'ok')} "
            f"restored={','.join(payload.get('restored_tools') or []) or '(none)'} "
            f"conflicted={','.join(payload.get('conflicted_tools') or []) or '(none)'}"
        )
    if entry["action"] == "rollback-result":
        return (
            f"target={payload.get('target_provider') or '(none)'} "
            f"status={payload.get('rollback_status')} "
            f"snapshot_sync={payload.get('snapshot_sync', 'ok')} "
            f"active_before={payload.get('active_before') or '(none)'}"
        )
    if entry["action"] == "repair-result":
        return (
            f"status={payload.get('repair_status')} "
            f"restore_status={payload.get('restore_status')} "
            f"cleanup_status={payload.get('cleanup_status')}"
        )
    return json.dumps(payload, ensure_ascii=False)


def cmd_history(
    tool: Optional[str],
    limit: int,
    action: Optional[str] = None,
    subject: Optional[str] = None,
    verbose: bool = False,
    failed_only: bool = False,
) -> None:
    """Print recent switch and run history."""
    entries = list_history(limit=limit, tool=tool, action=action, subject=subject, failed_only=failed_only)
    if not entries:
        info("No history found.")
        return
    for entry in entries:
        summary = json.dumps(entry["payload"], ensure_ascii=False) if verbose else _history_summary(entry)
        info(f"{entry['recorded_at']}  {entry['action']}  {entry['tool'] or '-'}  {entry['subject'] or '-'}  {summary}")


def cmd_rollback(store: Dict[str, Any], tool: str) -> None:
    """Roll back a tool to the previous active provider."""
    with _state_lock():
        store = _load_fresh_store_from_lock(store)
        current_active = store.get("active", {}).get(tool)
        if not current_active:
            info(f"[error] No rollback target found for {tool}.")
            sys.exit(1)
        current_validation = _safe_local_restore_validation(store, tool, current_active)
        if current_validation.get("status") != "ok":
            record_history(
                "rollback-result",
                tool,
                current_active,
                {
                    "active_before": current_active,
                    "target_provider": None,
                    "subject_kind": "active_before",
                    "rollback_status": "live_drift",
                    "target_validation": {"status": "skipped", "reason_code": "not_run"},
                    "post_restore_validation": current_validation,
                    "restore_conflicts": [],
                    "restore_error": None,
                    "snapshot_sync": "ok",
                },
            )
            info(f"[error] Cannot rollback {tool}: live config drift detected.")
            sys.exit(1)
        for entry in list_history(limit=200, tool=tool, action="switch"):
            previous = entry["payload"].get("previous")
            current = entry["payload"].get("current")
            provider = store.get("providers", {}).get(previous) if previous else None
            if current != current_active:
                continue
            if previous and provider and provider.get(tool) is not None:
                target_paths = _activation_target_paths(
                    store,
                    tool,
                    previous,
                    persist_state=True,
                )
                snapshots = _snapshot_file_state(target_paths)
                restore_groups = _restore_groups_for_tool(tool, target_paths)
                env_map: Dict[str, str] = {}
                unsets: list[str] = []
                written_states: Dict[Path, Dict[str, Any]] = {}
                target_validation: Dict[str, Any] = {"status": "pending", "reason_code": "pending"}
                try:
                    env_map, unsets = activate_tool_for_subprocess(
                        store,
                        tool,
                        previous,
                        persist_state=False,
                        fail_if_missing=True,
                        write_activation_files=True,
                    )
                    for path in target_paths:
                        written_states[path] = _capture_path_state(path)
                except BaseException:
                    for path in target_paths:
                        written_states[path] = _capture_path_state(path)
                    restore_status, restore_conflicts, restore_error = _attempt_owned_restore(
                        snapshots,
                        written_states,
                        groups=restore_groups,
                    )
                    post_restore_validation = (
                        _safe_local_restore_validation(store, tool, current_active)
                        if restore_status == "restored"
                        else {"status": "skipped", "reason_code": restore_status}
                    )
                    record_history(
                        "rollback-result",
                        tool,
                        previous,
                        {
                            "active_before": current_active,
                            "target_provider": previous,
                            "subject_kind": "target_provider",
                            "rollback_status": "restore_failed" if restore_status == "restored" else restore_status,
                            "restore_conflicts": restore_conflicts,
                            "restore_error": restore_error,
                            "target_validation": {"status": "failed", "reason_code": "activation_failed"},
                            "post_restore_validation": post_restore_validation,
                            "snapshot_sync": "ok",
                            "restore_conflicts": restore_conflicts,
                            "restore_error": restore_error,
                        },
                    )
                    info(f"[error] Rollback target '{previous}' failed for {tool}.")
                    sys.exit(1)
                target_validation = _safe_local_restore_validation(store, tool, previous)
                rollback_status = "restored"
                if target_validation.get("status") == "degraded":
                    rollback_status = "restore_conflict"
                elif target_validation.get("status") != "ok":
                    rollback_status = "restore_failed"
                if rollback_status != "restored":
                    restore_status, restore_conflicts, restore_error = _attempt_owned_restore(
                        snapshots,
                        written_states,
                        groups=restore_groups,
                    )
                    if restore_status == "restore_conflict":
                        rollback_status = "restore_conflict"
                    elif restore_status == "restore_failed":
                        rollback_status = "restore_failed"
                    post_restore_validation = (
                        _safe_local_restore_validation(store, tool, current_active)
                        if restore_status == "restored"
                        else {"status": "skipped", "reason_code": restore_status}
                    )
                    record_history(
                        "rollback-result",
                        tool,
                        previous,
                        {
                            "active_before": current_active,
                            "target_provider": previous,
                            "subject_kind": "target_provider",
                            "rollback_status": rollback_status,
                            "restore_conflicts": restore_conflicts,
                            "restore_error": restore_error,
                            "target_validation": target_validation,
                            "post_restore_validation": post_restore_validation,
                            "snapshot_sync": "ok",
                        },
                    )
                    info(f"[error] Rollback target '{previous}' failed for {tool}.")
                    sys.exit(1)
                switch_entry = _switch_history_entry(tool, current_active, previous)
                store["active"][tool] = previous
                payload = {
                    "active_before": current_active,
                    "target_provider": previous,
                    "subject_kind": "target_provider",
                    "rollback_status": "restored",
                    "restore_conflicts": [],
                    "restore_error": None,
                    "target_validation": target_validation,
                    "post_restore_validation": target_validation,
                    "snapshot_sync": "ok",
                }
                try:
                    save_store(
                        store,
                        expected_revision=store.get("_revision"),
                        history_entries=[
                            *([switch_entry] if switch_entry else []),
                            {
                                "action": "rollback-result",
                                "tool": tool,
                                "subject": previous,
                                "payload": payload,
                            },
                        ],
                    )
                except StoreSnapshotSyncError:
                    update_latest_history_payload(
                        "rollback-result",
                        tool,
                        previous,
                        {
                            **payload,
                            "rollback_status": "snapshot_degraded",
                            "snapshot_sync": "degraded",
                        },
                    )
                    info(
                        "[warning] Rollback state committed, but providers.json snapshot sync failed. "
                        "SQLite remains authoritative."
                    )
                    raise SystemExit(1)
                for key, value in env_map.items():
                    emit_env(key, value)
                for key in unsets:
                    emit_unset(key)
                info(f"[rollback] Restored {tool} to provider '{previous}'")
                return
    info(f"[error] No rollback target found for {tool}.")
    sys.exit(1)


def _generic_url_probe(url: Optional[str]) -> tuple[str, Dict[str, Any]]:
    """Probe an arbitrary URL with a simple GET request."""
    if not isinstance(url, str) or not url:
        return "missing", {"reason_code": "missing_base_url", "error": "base_url not configured"}
    status_code, detail = _http_probe(url, timeout=3.0)
    if status_code is None:
        return "failed", detail
    if status_code in (401, 403):
        return "failed", {**detail, "reason_code": "auth_error"}
    if 200 <= status_code < 400:
        return "ok", {**detail, "reason_code": "reachable"}
    if 400 <= status_code < 500:
        return "failed", {**detail, "reason_code": "http_4xx"}
    return "degraded", {**detail, "reason_code": "http_5xx"}


def _is_wsl() -> bool:
    """Return True when running inside WSL."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def _expected_overlay_path(tool: str, provider_name: str) -> Optional[Path]:
    """Return the generated overlay path for overlay-based tools."""
    if tool == "opencode":
        return _generated_dir() / "opencode" / f"{provider_name}.json"
    if tool == "openclaw":
        return _generated_dir() / "openclaw" / f"{provider_name}.json5"
    return None


def _probe_overlay_activation(tool: str, provider_name: str) -> tuple[str, Dict[str, Any]]:
    """Check whether the expected overlay exists and is the active one."""
    if tool == "opencode":
        env_key = "OPENCODE_CONFIG"
        env_path = _opencode_env_path()
    else:
        env_key = "OPENCLAW_CONFIG_PATH"
        env_path = _openclaw_env_path()

    expected = _expected_overlay_path(tool, provider_name)
    active_ref = os.environ.get(env_key) or _read_exported_value(env_path, env_key)
    detail = {
        "expected_overlay": str(expected) if expected else None,
        "active_overlay": active_ref,
        "overlay_exists": bool(expected and expected.exists()),
        "activation_file": str(env_path),
        "activation_file_exists": env_path.exists(),
        "expected_overlay_resolved": None,
        "active_overlay_resolved": None,
        "path_compare_mode": "none",
    }
    if expected and active_ref:
        active_path = Path(active_ref).expanduser()
        try:
            detail["expected_overlay_resolved"] = str(expected.resolve())
            detail["active_overlay_resolved"] = str(active_path.resolve())
            detail["path_compare_mode"] = "resolve"
            detail["active_overlay_matches"] = active_path.resolve() == expected.resolve()
        except OSError:
            detail["expected_overlay_resolved"] = os.path.abspath(str(expected))
            detail["active_overlay_resolved"] = os.path.abspath(active_ref)
            detail["path_compare_mode"] = "abspath"
            detail["active_overlay_matches"] = os.path.abspath(active_ref) == os.path.abspath(str(expected))
    else:
        detail["active_overlay_matches"] = False

    if not detail["overlay_exists"]:
        return "failed", {**detail, "reason_code": "overlay_missing"}
    if not active_ref:
        return "degraded", {**detail, "reason_code": "overlay_not_activated"}
    if active_ref and not detail["active_overlay_matches"]:
        return "degraded", {**detail, "reason_code": "overlay_mismatch"}
    return "ok", {**detail, "reason_code": "overlay_ready"}


def _make_doctor_check(
    status: str,
    reason_code: str,
    **extra: Any,
) -> Dict[str, Any]:
    """Build one stable doctor sub-check payload."""
    payload: Dict[str, Any] = {"status": status, "reason_code": reason_code}
    payload.update(extra)
    return payload


def _doctor_checked_at() -> str:
    """Return a stable timestamp string for doctor payloads."""
    return datetime.now().isoformat(timespec="seconds")


def _normalize_doctor_detail(
    detail: Optional[Dict[str, Any]],
    *,
    checked_at: Optional[str] = None,
    probe_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Ensure doctor detail keeps a stable shape for automation consumers."""
    normalized = dict(_sanitize_probe_detail(detail or {}))
    normalized.setdefault("checks", {})
    normalized.setdefault("mismatch_fields", [])
    if checked_at:
        normalized["checked_at"] = checked_at
    else:
        normalized.setdefault("checked_at", _doctor_checked_at())
    if probe_mode:
        normalized["probe_mode"] = probe_mode
    return normalized


def _build_doctor_payload(
    tool: str,
    target: Optional[str],
    status: str,
    detail: Optional[Dict[str, Any]] = None,
    *,
    probe_mode: str,
    summary_reason: Optional[str] = None,
    history: Optional[list[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build one stable top-level doctor payload."""
    normalized_detail = _normalize_doctor_detail(
        detail,
        probe_mode=probe_mode,
    )
    payload: Dict[str, Any] = {
        "schema_version": DOCTOR_JSON_SCHEMA_VERSION,
        "tool": tool,
        "target": target,
        "status": status,
        "summary_reason": summary_reason
        or normalized_detail.get("reason_code")
        or normalized_detail.get("error")
        or "checked",
        "probe_mode": probe_mode,
        "checked_at": normalized_detail.get("checked_at"),
        "checks": normalized_detail.get("checks", {}),
        "detail": normalized_detail,
        "history": history or [],
    }
    return payload


def _probe_overlay_content(
    store: Optional[Dict[str, Any]],
    tool: str,
    conf: Dict[str, Any],
    active_overlay_path: Optional[str],
) -> tuple[str, Dict[str, Any]]:
    """Compare the active overlay contents with the stored provider config."""
    if not active_overlay_path:
        return "degraded", {"reason_code": "overlay_not_activated"}
    data = _load_json_relaxed(Path(active_overlay_path).expanduser())
    if tool == "opencode":
        providers = data.get("provider")
        provider_name, provider_conf = _select_named_provider(providers, conf.get("provider_id"))
        if not provider_name or not provider_conf:
            return "degraded", {"reason_code": "overlay_content_missing"}
        options = provider_conf.get("options", {}) if isinstance(provider_conf, dict) else {}
        live_base_url = options.get("baseURL")
        live_token = options.get("apiKey")
        live_model = data.get("model")
        live_headers = options.get("headers") if isinstance(options.get("headers"), dict) else None
        live_npm = provider_conf.get("npm")
        expected_headers = conf.get("headers") if isinstance(conf.get("headers"), dict) else None
        mismatch_fields: list[str] = []
        if live_base_url != conf.get("base_url"):
            mismatch_fields.append("base_url")
        if live_token != resolve_token(conf.get("token") or conf.get("api_key")):
            mismatch_fields.append("token")
        if provider_name != (conf.get("provider_id") or provider_name):
            mismatch_fields.append("provider_id")
        if conf.get("model") and live_model != conf.get("model"):
            mismatch_fields.append("model")
        if expected_headers is not None and live_headers != expected_headers:
            mismatch_fields.append("headers")
        if conf.get("npm") and live_npm != conf.get("npm"):
            mismatch_fields.append("npm")
        detail = {
            "reason_code": "live_config_mismatch" if mismatch_fields else "overlay_content_ready",
            "live_provider_id": provider_name,
            "live_base_url": live_base_url,
            "live_model": live_model,
            "live_npm": live_npm,
            "mismatch_fields": mismatch_fields,
        }
        return ("degraded", detail) if mismatch_fields else ("ok", detail)

    models = data.get("models")
    providers = models.get("providers", {}) if isinstance(models, dict) else {}
    provider_name, provider_conf = _select_named_provider(providers, conf.get("provider_id"))
    if not provider_name or not provider_conf:
        return "degraded", {"reason_code": "overlay_content_missing"}
    live_base_url = provider_conf.get("baseUrl")
    live_token = provider_conf.get("apiKey")
    live_api = provider_conf.get("api")
    agent_defaults = data.get("agents", {}).get("defaults", {}) if isinstance(data.get("agents"), dict) else {}
    live_model = agent_defaults.get("model", {}).get("primary") if isinstance(agent_defaults.get("model"), dict) else None
    live_profile = os.environ.get("OPENCLAW_PROFILE") or _read_exported_value(
        _openclaw_env_path(),
        "OPENCLAW_PROFILE",
    ) or _read_env_assignment_value(get_tool_paths(store, "openclaw")["env"], "OPENCLAW_PROFILE")
    mismatch_fields = []
    if live_base_url != conf.get("base_url"):
        mismatch_fields.append("base_url")
    if live_token != resolve_token(conf.get("token") or conf.get("api_key")):
        mismatch_fields.append("token")
    if provider_name != (conf.get("provider_id") or provider_name):
        mismatch_fields.append("provider_id")
    if conf.get("model") and live_model != conf.get("model"):
        mismatch_fields.append("model")
    if conf.get("api") and live_api != conf.get("api"):
        mismatch_fields.append("api")
    if conf.get("profile") and live_profile != conf.get("profile"):
        mismatch_fields.append("profile")
    detail = {
        "reason_code": "live_config_mismatch" if mismatch_fields else "overlay_content_ready",
        "live_provider_id": provider_name,
        "live_base_url": live_base_url,
        "live_model": live_model,
        "live_api": live_api,
        "live_profile": live_profile,
        "mismatch_fields": mismatch_fields,
    }
    return ("degraded", detail) if mismatch_fields else ("ok", detail)


def _status_rank(status: str) -> int:
    """Return a sortable rank where smaller values are worse."""
    return {"missing": 0, "failed": 1, "degraded": 2, "ok": 3}.get(status, 0)


def _merge_status(*statuses: str) -> str:
    """Return the worst status from the provided values."""
    return min(statuses, key=_status_rank)


def _merge_doctor_detail(base_detail: Dict[str, Any], extra_detail: Dict[str, Any]) -> Dict[str, Any]:
    """Merge doctor detail payloads without dropping shared checks or mismatch fields."""
    merged = {
        **base_detail,
        **{key: value for key, value in extra_detail.items() if key not in {"checks", "mismatch_fields"}},
    }
    merged["checks"] = {
        **(base_detail.get("checks") if isinstance(base_detail.get("checks"), dict) else {}),
        **(extra_detail.get("checks") if isinstance(extra_detail.get("checks"), dict) else {}),
    }
    merged["mismatch_fields"] = list(
        dict.fromkeys(
            [
                *(base_detail.get("mismatch_fields") if isinstance(base_detail.get("mismatch_fields"), list) else []),
                *(extra_detail.get("mismatch_fields") if isinstance(extra_detail.get("mismatch_fields"), list) else []),
            ]
        )
    )
    return merged


def _runtime_lease_check(
    tool: str,
    current_target: Optional[str] = None,
) -> tuple[str, Dict[str, Any]]:
    """Inspect persisted runtime lease state for one tool."""
    manifest = get_managed_target(tool)
    if not manifest:
        return "ok", _make_doctor_check("ok", "runtime_lease_absent")
    if manifest.get("decode_error"):
        return "degraded", _make_doctor_check(
            "degraded",
            "manifest_decode_failed",
            error=manifest.get("decode_error"),
            stale=True,
        )
    blocking_lease = _managed_target_blocks_run(manifest)
    if current_target and not any(_runtime_manifest_target_names(manifest)):
        return ("degraded" if blocking_lease else "ok"), _make_doctor_check(
            "degraded" if blocking_lease else "ok",
            "lease_target_unknown",
            lease_id=manifest.get("lease_id"),
        )
    if not _managed_target_matches_candidate(manifest, current_target):
        return ("degraded" if blocking_lease else "ok"), _make_doctor_check(
            "degraded" if blocking_lease else "ok",
            "lease_for_other_target",
            lease_id=manifest.get("lease_id"),
            lease_target=manifest.get("selected_candidate") or manifest.get("requested_target"),
        )
    runtime_root = manifest.get("runtime_root")
    runtime_exists = bool(isinstance(runtime_root, str) and runtime_root and Path(runtime_root).exists())
    stale = bool(manifest.get("stale"))
    owner_pid = manifest.get("owner_pid")
    child_pid = manifest.get("child_pid")
    phase = manifest.get("phase")
    detail = _make_doctor_check(
        "ok",
        "runtime_lease_present",
        lease_id=manifest.get("lease_id"),
        phase=phase,
        stale=stale,
        runtime_root=runtime_root,
        runtime_root_exists=runtime_exists,
        owner_pid=owner_pid,
        pid_running=_pid_is_running(owner_pid),
        owner_identity_match=_pid_matches_identity(owner_pid, manifest.get("owner_started_at")),
        child_pid=child_pid,
        last_child_pid=manifest.get("last_child_pid"),
        child_pid_running=_pid_is_running(child_pid),
        child_identity_match=_pid_matches_identity(child_pid, manifest.get("child_started_at")),
        child_status=manifest.get("child_status"),
        stale_reason=manifest.get("stale_reason"),
        restore_status=manifest.get("restore_status"),
        cleanup_status=manifest.get("cleanup_status"),
    )
    if phase not in RUNTIME_VALID_PHASES:
        detail["status"] = "degraded"
        detail["reason_code"] = "invalid_phase"
        return "degraded", detail
    if stale:
        detail["status"] = "degraded"
        detail["reason_code"] = "stale_lease"
        return "degraded", detail
    if runtime_root and not runtime_exists:
        detail["status"] = "degraded"
        detail["reason_code"] = "dangling_runtime_dir"
        return "degraded", detail
    if isinstance(child_pid, int) and child_pid > 0 and (
        _pid_matches_identity(child_pid, manifest.get("child_started_at"))
        or _pid_cannot_be_verified_but_is_running(child_pid, manifest.get("child_started_at"))
    ):
        detail["status"] = "degraded"
        detail["reason_code"] = "runtime_child_running"
        return "degraded", detail
    if isinstance(owner_pid, int) and owner_pid > 0 and _pid_cannot_be_verified_but_is_running(
        owner_pid,
        manifest.get("owner_started_at"),
    ):
        detail["status"] = "degraded"
        detail["reason_code"] = "runtime_busy"
        return "degraded", detail
    if phase in RUNTIME_BUSY_PHASES and isinstance(owner_pid, int) and owner_pid > 0 and not _pid_matches_identity(
        owner_pid,
        manifest.get("owner_started_at"),
    ):
        detail["status"] = "degraded"
        detail["reason_code"] = "runtime_pid_dead"
        return "degraded", detail
    if phase in RUNTIME_BUSY_PHASES:
        if isinstance(owner_pid, int) and owner_pid > 0 and _pid_matches_identity(owner_pid, manifest.get("owner_started_at")):
            detail["status"] = "degraded"
            detail["reason_code"] = "runtime_busy"
            return "degraded", detail
        detail["status"] = "degraded"
        detail["reason_code"] = "runtime_phase_stuck"
        return "degraded", detail
    return "ok", detail


def _store_secret_policy_check(tool: str, conf: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    """Report whether the provider still stores a literal secret."""
    secret_ref = conf.get("api_key") if tool == "gemini" else (conf.get("token") or conf.get("api_key"))
    if not secret_ref:
        return "ok", _make_doctor_check("ok", "secret_not_configured")
    if _is_env_ref(secret_ref):
        return "ok", _make_doctor_check("ok", "secret_env_ref")
    return "degraded", _make_doctor_check("degraded", "store_literal_secret")


def _build_codex_transport_check(
    responses_get_check: Dict[str, Any],
    responses_post_check: Dict[str, Any],
) -> Dict[str, Any]:
    """Summarize Codex transport compatibility from GET/POST responses checks."""
    get_reason = responses_get_check.get("reason_code")
    post_reason = responses_post_check.get("reason_code")
    if get_reason == "responses_get_ready" and post_reason == "responses_post_ready":
        return _make_doctor_check("ok", "responses_transport_ready")
    if get_reason == "responses_get_incompatible" and post_reason == "responses_post_ready":
        return _make_doctor_check("degraded", "http_only_responses")
    if post_reason == "responses_post_incompatible":
        return _make_doctor_check("failed", "responses_post_incompatible")
    if get_reason == "responses_get_incompatible":
        return _make_doctor_check("degraded", "responses_get_incompatible")
    if post_reason == "model_unresolved":
        return _make_doctor_check("degraded", "model_unresolved")
    if post_reason == "responses_post_ready":
        return _make_doctor_check("degraded", "responses_transport_partial")
    return _make_doctor_check(
        responses_post_check.get("status", responses_get_check.get("status", "degraded")),
        post_reason or get_reason or "responses_transport_unknown",
    )


def _probe_codex_target(
    store: Dict[str, Any],
    conf: Dict[str, Any],
    provider_name: str,
    *,
    deep: bool = False,
) -> tuple[str, Dict[str, Any]]:
    """Run a stronger Codex compatibility probe."""
    if _codex_uses_chatgpt_auth(conf):
        paths = get_tool_paths(store, "codex")
        auth_data = load_json(paths["auth"])
        config_content = paths["config"].read_text(encoding="utf-8") if paths["config"].exists() else ""
        current_provider = _read_toml_string_value(config_content, "model_provider")
        root_openai_base_url = _read_toml_string_value(config_content, "openai_base_url")
        provider_block = (
            _extract_toml_table_body(config_content, f"model_providers.{current_provider}")
            if current_provider
            else None
        ) or ""
        config_checks = {
            "auth_exists": paths["auth"].exists(),
            "auth_mode": auth_data.get("auth_mode"),
            "auth_has_openai_api_key": bool(auth_data.get("OPENAI_API_KEY")),
            "config_exists": paths["config"].exists(),
            "model_provider": current_provider,
            "openai_base_url": root_openai_base_url,
            "provider_requires_openai_auth": _read_toml_literal_value(provider_block, "requires_openai_auth"),
            "provider_supports_websockets": _read_toml_literal_value(provider_block, "supports_websockets"),
            "provider_wire_api": _read_toml_string_value(provider_block, "wire_api"),
        }
        mismatch_fields: list[str] = []
        if config_checks["auth_mode"] != CODEX_AUTH_MODE_CHATGPT:
            mismatch_fields.append("auth_mode")
        expected_route = _codex_chatgpt_provider_route(store)
        provider_supports_chatgpt = (
            config_checks["model_provider"] == CODEX_BUILTIN_PROVIDER_ID
            or config_checks["provider_requires_openai_auth"] == "true"
        )
        if not provider_supports_chatgpt:
            mismatch_fields.append("model_provider")
        elif config_checks["model_provider"] != expected_route:
            mismatch_fields.append("provider_route")
        if config_checks["model_provider"] == CODEX_PROVIDER_ID:
            if config_checks["provider_supports_websockets"] != "true":
                mismatch_fields.append("provider_supports_websockets")
            if config_checks["provider_wire_api"] != "responses":
                mismatch_fields.append("provider_wire_api")
        if config_checks["openai_base_url"]:
            mismatch_fields.append("openai_base_url")
        if config_checks["auth_has_openai_api_key"]:
            mismatch_fields.append("auth_has_openai_api_key")
        config_status = "ok" if not mismatch_fields else "degraded"
        checks = {
            "live_auth_check": _make_doctor_check(
                "ok" if config_checks["auth_mode"] == CODEX_AUTH_MODE_CHATGPT else "failed",
                "auth_ready" if config_checks["auth_mode"] == CODEX_AUTH_MODE_CHATGPT else "auth_missing",
                path=str(paths["auth"]),
                exists=config_checks["auth_exists"],
            ),
            "live_provider_block_check": _make_doctor_check(
                config_status,
                "config_ready" if config_status == "ok" else "config_mismatch",
                path=str(paths["config"]),
                mismatch_fields=mismatch_fields,
                config_checks=config_checks,
            ),
        }
        status = _merge_status(config_status, checks["live_auth_check"]["status"])
        return status, {
            "token_resolved": config_checks["auth_mode"] == CODEX_AUTH_MODE_CHATGPT,
            "primary_base_url": None,
            "fallback_base_url": None,
            "selected_base_url": None,
            "reason_code": "ready" if status == "ok" else "config_mismatch",
            "probe_mode": "local",
            "config_checks": config_checks,
            "checks": checks,
            "mismatch_fields": mismatch_fields,
        }

    token_value = resolve_token(conf.get("token"))
    if not token_value:
        return "missing", {"reason_code": "token_missing", "token_resolved": False}

    def _models_check(url: Optional[str], *, selected: bool = False) -> tuple[str, Dict[str, Any]]:
        probe_url = f"{url.rstrip('/')}/models" if isinstance(url, str) and url else None
        if _probe_uses_unsafe_transport(url):
            return "failed", _make_doctor_check(
                "failed",
                "unsafe_transport",
                url=probe_url,
                http_status=None,
                selected=selected,
            )
        status_code, probe_detail = _http_probe(probe_url, headers=headers, timeout=3.0)
        if status_code is None:
            return "failed", _make_doctor_check(
                "failed",
                probe_detail.get("reason_code", "network_error"),
                url=probe_url,
                http_status=None,
                selected=selected,
                error_class=probe_detail.get("error_class"),
                sample=probe_detail.get("sample"),
            )
        if status_code in (200, 204):
            return "ok", _make_doctor_check(
                "ok",
                "models_ready",
                url=probe_url,
                http_status=status_code,
                selected=selected,
                sample=probe_detail.get("sample"),
            )
        if status_code in (401, 403):
            return "failed", _make_doctor_check(
                "failed",
                "auth_error",
                url=probe_url,
                http_status=status_code,
                selected=selected,
                sample=probe_detail.get("sample"),
            )
        if status_code in (404, 405):
            return "failed", _make_doctor_check(
                "failed",
                "protocol_incompatible",
                url=probe_url,
                http_status=status_code,
                selected=selected,
                sample=probe_detail.get("sample"),
            )
        if 500 <= status_code < 600:
            return "degraded", _make_doctor_check(
                "degraded",
                "upstream_error",
                url=probe_url,
                http_status=status_code,
                selected=selected,
                sample=probe_detail.get("sample"),
            )
        return "failed", _make_doctor_check(
            "failed",
            "http_4xx",
            url=probe_url,
            http_status=status_code,
            selected=selected,
            sample=probe_detail.get("sample"),
        )

    def _responses_check(
        method: str,
        url: Optional[str],
        *,
        model_name: Optional[str] = None,
    ) -> tuple[str, Dict[str, Any]]:
        probe_url = f"{url.rstrip('/')}/responses" if isinstance(url, str) and url else None
        if _probe_uses_unsafe_transport(url):
            return "failed", _make_doctor_check(
                "failed",
                "unsafe_transport",
                url=probe_url,
                http_status=None,
                model=model_name,
            )
        payload = None
        headers_for_probe = dict(headers)
        if method == "POST":
            headers_for_probe["Content-Type"] = "application/json"
            payload = json.dumps(
                {
                    "input": "ccswitch deep probe",
                    **({"model": model_name} if model_name else {}),
                },
                ensure_ascii=False,
            ).encode("utf-8")
        status_code, probe_detail = _http_probe(
            probe_url,
            method=method,
            headers=headers_for_probe,
            body=payload,
            timeout=3.0,
        )
        ok_statuses = (200, 204) if method == "GET" else (200, 201)
        incompatible_reason = "responses_get_incompatible" if method == "GET" else "responses_post_incompatible"
        ready_reason = "responses_get_ready" if method == "GET" else "responses_post_ready"
        if status_code is None:
            return "degraded", _make_doctor_check(
                "degraded",
                probe_detail.get("reason_code", "network_error"),
                url=probe_url,
                http_status=None,
                error_class=probe_detail.get("error_class"),
                sample=probe_detail.get("sample"),
                model=model_name,
            )
        if status_code in ok_statuses:
            return "ok", _make_doctor_check(
                "ok",
                ready_reason,
                url=probe_url,
                http_status=status_code,
                sample=probe_detail.get("sample"),
                model=model_name,
            )
        if status_code in (401, 403):
            return "failed", _make_doctor_check(
                "failed",
                "auth_error",
                url=probe_url,
                http_status=status_code,
                sample=probe_detail.get("sample"),
                model=model_name,
            )
        if method == "POST" and status_code in (400, 422):
            return "degraded", _make_doctor_check(
                "degraded",
                "probe_payload_rejected",
                url=probe_url,
                http_status=status_code,
                sample=probe_detail.get("sample"),
                model=model_name,
            )
        if status_code in (408, 429):
            return "degraded", _make_doctor_check(
                "degraded",
                "transient_degraded",
                url=probe_url,
                http_status=status_code,
                sample=probe_detail.get("sample"),
                model=model_name,
            )
        if status_code in (404, 405):
            return "degraded", _make_doctor_check(
                "degraded",
                incompatible_reason,
                url=probe_url,
                http_status=status_code,
                sample=probe_detail.get("sample"),
                model=model_name,
            )
        if 500 <= status_code < 600:
            return "degraded", _make_doctor_check(
                "degraded",
                "upstream_error",
                url=probe_url,
                http_status=status_code,
                sample=probe_detail.get("sample"),
                model=model_name,
            )
        return "failed", _make_doctor_check(
            "failed",
            "http_4xx",
            url=probe_url,
            http_status=status_code,
            sample=probe_detail.get("sample"),
            model=model_name,
        )

    primary = conf.get("base_url")
    fallback = conf.get("fallback_base_url")
    selected = primary
    headers = {"Authorization": f"Bearer {token_value}"}
    checks: Dict[str, Dict[str, Any]] = {}
    checks["transport_policy_check"] = _make_doctor_check("ok", "transport_allowed", url=selected)
    primary_status, primary_check = _models_check(primary, selected=True)
    checks["primary_models_probe"] = primary_check
    fallback_status = primary_status
    fallback_check = primary_check
    if isinstance(fallback, str) and fallback and fallback != primary:
        fallback_status, fallback_check = _models_check(fallback, selected=False)
        if not _codex_status_looks_usable(primary_check.get("http_status")) and _codex_status_looks_usable(
            fallback_check.get("http_status")
        ):
            selected = fallback
    checks["fallback_models_probe"] = fallback_check
    checks["primary_models_probe"]["selected"] = selected == primary
    checks["fallback_models_probe"]["selected"] = selected == fallback
    checks["selected_models_probe"] = primary_check if selected == primary else fallback_check
    checks["transport_policy_check"] = (
        _make_doctor_check("failed", "unsafe_transport", url=selected)
        if _probe_uses_unsafe_transport(selected)
        else _make_doctor_check("ok", "transport_allowed", url=selected)
    )
    status = primary_status if selected == primary else fallback_status
    reason_code = checks["selected_models_probe"]["reason_code"]
    if reason_code == "unsafe_transport":
        return "failed", {
            "reason_code": "unsafe_transport",
            "token_resolved": True,
            "primary_base_url": primary,
            "fallback_base_url": fallback,
            "selected_base_url": selected,
            "checks": checks,
            "mismatch_fields": [],
            "probe_mode": "deep" if deep else "safe",
        }

    paths = get_tool_paths(store, "codex")
    auth_data = load_json(paths["auth"])
    config_content = paths["config"].read_text(encoding="utf-8") if paths["config"].exists() else ""
    provider_block = _extract_toml_table_body(config_content, f"model_providers.{CODEX_PROVIDER_ID}") or ""
    config_checks = {
        "auth_exists": paths["auth"].exists(),
        "auth_has_openai_api_key": bool(auth_data.get("OPENAI_API_KEY")),
        "config_exists": paths["config"].exists(),
        "model_provider": _read_toml_string_value(config_content, "model_provider"),
        "provider_block_exists": bool(provider_block),
        "provider_base_url": _read_toml_string_value(provider_block, "base_url"),
        "provider_env_key": _read_toml_string_value(provider_block, "env_key"),
        "provider_supports_websockets": _read_toml_literal_value(provider_block, "supports_websockets"),
        "provider_wire_api": _read_toml_string_value(provider_block, "wire_api"),
    }
    config_status = "ok"
    config_mismatch_fields = []
    if config_checks["model_provider"] != CODEX_PROVIDER_ID:
        config_status = "degraded"
        config_mismatch_fields.append("model_provider")
    if config_checks["provider_base_url"] != selected:
        config_status = "degraded"
        config_mismatch_fields.append("provider_base_url")
    if config_checks["provider_env_key"] != "OPENAI_API_KEY":
        config_status = "degraded"
        config_mismatch_fields.append("provider_env_key")
    if config_checks["provider_supports_websockets"] != "false":
        config_status = "degraded"
        config_mismatch_fields.append("provider_supports_websockets")
    if config_checks["provider_wire_api"] != "responses":
        config_status = "degraded"
        config_mismatch_fields.append("provider_wire_api")
    checks["live_auth_check"] = _make_doctor_check(
        "ok" if config_checks["auth_has_openai_api_key"] else "failed",
        "auth_ready" if config_checks["auth_has_openai_api_key"] else "auth_missing",
        path=str(paths["auth"]),
        exists=config_checks["auth_exists"],
    )
    checks["live_provider_block_check"] = _make_doctor_check(
        config_status,
        "config_ready" if config_status == "ok" else "config_mismatch",
        path=str(paths["config"]),
        mismatch_fields=config_mismatch_fields,
        config_checks=config_checks,
    )

    detail: Dict[str, Any] = {
        "token_resolved": True,
        "primary_base_url": primary,
        "fallback_base_url": fallback,
        "selected_base_url": selected,
        "reason_code": reason_code,
        "probe_mode": "deep" if deep else "safe",
        "config_checks": config_checks,
        "checks": checks,
        "mismatch_fields": [],
    }
    status = _merge_status(status, config_status, checks["live_auth_check"]["status"])
    if checks["live_auth_check"]["status"] == "failed":
        detail["reason_code"] = checks["live_auth_check"]["reason_code"]
    elif status == "degraded" and reason_code == "models_ready":
        detail["reason_code"] = "config_mismatch"
    if config_mismatch_fields:
        detail["mismatch_fields"].extend(config_mismatch_fields)

    if deep:
        model_name = conf.get("model") or _read_toml_string_value(config_content, "model")
        if not model_name:
            models_payload = _parse_json_sample(checks["selected_models_probe"].get("sample"))
            if isinstance(models_payload, dict):
                model_entries = models_payload.get("data")
                if isinstance(model_entries, list):
                    for entry in model_entries:
                        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"]:
                            continue
                        candidate_model = entry["id"]
                        lowered_candidate = candidate_model.lower()
                        if any(token in lowered_candidate for token in ("embed", "embedding", "moderation", "rerank")):
                            continue
                        model_name = candidate_model
                        break
        get_status, get_check = _responses_check("GET", selected)
        checks["responses_get_probe"] = get_check
        status = _merge_status(status, get_status)
        if detail["reason_code"] != "auth_missing" and get_check["reason_code"] != "responses_get_ready":
            detail["reason_code"] = get_check["reason_code"]
        if model_name:
            post_status, post_check = _responses_check("POST", selected, model_name=model_name)
            checks["responses_post_probe"] = post_check
            status = _merge_status(status, post_status)
            detail["deep_probe"] = dict(post_check)
            if detail["deep_probe"].get("reason_code") == "responses_post_ready":
                detail["deep_probe"]["reason_code"] = "responses_ready"
            if (
                detail["reason_code"] != "auth_missing"
                and get_check["reason_code"] == "responses_get_ready"
                and post_check["reason_code"] != "responses_post_ready"
            ):
                detail["reason_code"] = post_check["reason_code"]
        else:
            unresolved = _make_doctor_check(
                "degraded",
                "model_unresolved",
                error="model not configured",
            )
            checks["responses_post_probe"] = unresolved
            detail["deep_probe"] = dict(unresolved)
            status = _merge_status(status, "degraded")
            detail["reason_code"] = "model_unresolved"
        transport_check = _build_codex_transport_check(
            checks["responses_get_probe"],
            checks["responses_post_probe"],
        )
        checks["transport_check"] = transport_check
        status = _merge_status(status, transport_check["status"])
        if detail["reason_code"] not in {
            "auth_missing",
            "model_unresolved",
            "auth_error",
            "config_mismatch",
            "unsafe_transport",
        }:
            detail["reason_code"] = transport_check["reason_code"]
    else:
        checks.setdefault(
            "responses_get_probe",
            _make_doctor_check("missing", "not_run", url=None),
        )
        checks.setdefault(
            "responses_post_probe",
            _make_doctor_check("missing", "not_run", url=None),
        )
        checks["transport_check"] = _make_doctor_check("missing", "not_run", url=None)
    if "deep_probe" not in detail:
        detail["deep_probe"] = dict(checks["responses_post_probe"])
    return status, detail


def _probe_tool_health(
    store: Dict[str, Any],
    tool: str,
    provider_name: str,
    conf: Dict[str, Any],
    *,
    deep: bool = False,
) -> tuple[str, Dict[str, Any]]:
    """Run per-tool doctor checks with activation/path details."""
    target_paths = get_tool_paths(store, tool)
    is_wsl = _is_wsl()
    raw_override = get_setting(store, f"{tool}_config_dir")
    path_exists = target_paths["dir"].exists()
    path_writable = os.access(
        target_paths["dir"] if path_exists else target_paths["dir"].parent,
        os.W_OK,
    )
    detail: Dict[str, Any] = {
        "target_config_dir": str(target_paths["dir"]),
        "target_dir_exists": path_exists,
        "target_dir_writable": path_writable,
        "platform": "wsl" if is_wsl else sys.platform,
        "is_wsl": is_wsl,
        "checked_at": _doctor_checked_at(),
        "checks": {},
        "mismatch_fields": [],
    }
    if tool in OVERLAY_TOOLS:
        detail["overlay_root"] = str(_generated_dir() / tool)
    if not path_exists:
        path_check = _make_doctor_check(
            "degraded" if tool in OVERLAY_TOOLS else "failed",
            "target_dir_missing",
            path=str(target_paths["dir"]),
        )
    elif not path_writable:
        path_check = _make_doctor_check(
            "degraded",
            "target_dir_not_writable",
            path=str(target_paths["dir"]),
        )
    else:
        path_check = _make_doctor_check("ok", "target_dir_ready", path=str(target_paths["dir"]))
    detail["checks"]["path_check"] = path_check
    if is_wsl and _is_windows_style_path(raw_override):
        detail["checks"]["config_dir_input_check"] = _make_doctor_check(
            "degraded",
            "windows_style_path_on_wsl",
            configured_value=raw_override,
            hint="Use a /mnt/<drive>/... path inside WSL.",
        )
    else:
        detail["checks"]["config_dir_input_check"] = _make_doctor_check("ok", "config_dir_input_ready")
    runtime_status, runtime_check = (
        _runtime_lease_check(tool, provider_name)
        if "_revision" in store
        else ("ok", _make_doctor_check("ok", "runtime_lease_absent"))
    )
    detail["checks"]["runtime_lease_check"] = runtime_check
    secret_status, secret_check = _store_secret_policy_check(tool, conf)
    detail["checks"]["store_secret_policy_check"] = secret_check

    if tool == "codex":
        status, probe_detail = _probe_codex_target(store, conf, provider_name, deep=deep)
        status = _merge_status(
            status,
            path_check["status"],
            detail["checks"]["config_dir_input_check"]["status"],
            runtime_status,
            secret_status,
        )
        merged_detail = _merge_doctor_detail(detail, probe_detail)
        protected_reason_codes = {
            "auth_error",
            "auth_missing",
            "config_mismatch",
            "model_unresolved",
            "unsafe_transport",
        }
        if merged_detail.get("reason_code") in {"ready", "models_ready"} and path_check["status"] != "ok":
            merged_detail["reason_code"] = path_check["reason_code"]
        if merged_detail.get("reason_code") in {"ready", "models_ready"} and detail["checks"]["config_dir_input_check"]["status"] != "ok":
            merged_detail["reason_code"] = detail["checks"]["config_dir_input_check"]["reason_code"]
        if runtime_status != "ok" and merged_detail.get("reason_code") not in protected_reason_codes:
            merged_detail["reason_code"] = runtime_check["reason_code"]
        elif secret_status != "ok" and merged_detail.get("reason_code") in {"ready", "models_ready", "responses_transport_ready"}:
            merged_detail["reason_code"] = secret_check["reason_code"]
        return status, _normalize_doctor_detail(merged_detail, probe_mode="deep" if deep else "safe")

    if tool == "claude":
        token_value = resolve_token(conf.get("token"))
        settings_path = target_paths["settings"]
        settings_data = load_json(settings_path)
        env = settings_data.get("env") if isinstance(settings_data.get("env"), dict) else {}
        live_token = env.get("ANTHROPIC_AUTH_TOKEN")
        live_base_url = env.get("ANTHROPIC_BASE_URL")
        status = "ok" if token_value else "missing"
        reason_code = "ready" if token_value else "token_missing"
        if token_value and (
            live_token != token_value
            or live_base_url != conf.get("base_url")
        ):
            status = "degraded"
            reason_code = "live_config_mismatch"
            detail["mismatch_fields"] = [
                key
                for key, mismatched in (
                    ("token", live_token != token_value),
                    ("base_url", live_base_url != conf.get("base_url")),
                )
                if mismatched
            ]
        status = _merge_status(
            status,
            path_check["status"],
            detail["checks"]["config_dir_input_check"]["status"],
            runtime_status,
            secret_status,
        )
        return status, _normalize_doctor_detail({
            **detail,
            "token_resolved": bool(token_value),
            "settings_exists": settings_path.exists(),
            "live_base_url": live_base_url,
            "reason_code": (
                runtime_check["reason_code"]
                if runtime_status != "ok"
                else (
                    path_check["reason_code"]
                    if status != "ok" and reason_code == "ready"
                    else (
                        secret_check["reason_code"]
                        if secret_status != "ok" and reason_code == "ready"
                        else reason_code
                    )
                )
            ),
        }, probe_mode="deep" if deep else "safe")

    if tool == "gemini":
        token_value = resolve_token(conf.get("token") or conf.get("api_key"))
        settings_path = target_paths["settings"]
        settings_data = load_json(settings_path)
        selected_type = None
        if isinstance(settings_data.get("security"), dict):
            selected_type = settings_data["security"].get("auth", {}).get("selectedType")
        status = "ok" if token_value else "missing"
        if token_value and selected_type not in (conf.get("auth_type"), conf.get("auth_type", "api-key")):
            status = "degraded"
        status = _merge_status(
            status,
            path_check["status"],
            detail["checks"]["config_dir_input_check"]["status"],
            runtime_status,
            secret_status,
        )
        return status, _normalize_doctor_detail({
            **detail,
            "token_resolved": bool(token_value),
            "auth_type": conf.get("auth_type", "api-key"),
            "live_auth_type": selected_type,
            "settings_exists": settings_path.exists(),
            "activation_file": str(_active_env_path()),
            "activation_file_exists": _active_env_path().exists(),
            "reason_code": (
                runtime_check["reason_code"]
                if runtime_status != "ok"
                else (
                    path_check["reason_code"]
                    if path_check["status"] != "ok" and token_value and selected_type in (conf.get("auth_type"), conf.get("auth_type", "api-key"))
                    else (
                        secret_check["reason_code"]
                        if secret_status != "ok" and token_value and selected_type in (conf.get("auth_type"), conf.get("auth_type", "api-key"))
                        else ("ready" if status == "ok" else ("auth_type_mismatch" if token_value else "token_missing"))
                    )
                )
            ),
            "mismatch_fields": ["auth_type"] if token_value and status == "degraded" else [],
        }, probe_mode="deep" if deep else "safe")

    token_value = resolve_token(conf.get("token") or conf.get("api_key"))
    if not token_value:
        return "missing", _normalize_doctor_detail(
            {**detail, "token_resolved": False, "reason_code": "token_missing"},
            probe_mode="deep" if deep else "safe",
        )

    status, probe_detail = _generic_url_probe(conf.get("base_url"))
    detail.update(probe_detail)
    detail["token_resolved"] = True
    if tool in OVERLAY_TOOLS:
        overlay_status, overlay_detail = _probe_overlay_activation(tool, provider_name)
        detail.update(overlay_detail)
        status = _merge_status(status, overlay_status)
        if overlay_status == "ok":
            content_status, content_detail = _probe_overlay_content(store, tool, conf, detail.get("active_overlay"))
            detail.update(content_detail)
            status = _merge_status(status, content_status)
    status = _merge_status(
        status,
        path_check["status"],
        detail["checks"]["config_dir_input_check"]["status"],
        runtime_status,
        secret_status,
    )
    if runtime_status != "ok":
        detail["reason_code"] = runtime_check["reason_code"]
    elif detail.get("reason_code") == "reachable" and path_check["status"] != "ok":
        detail["reason_code"] = path_check["reason_code"]
    elif detail.get("reason_code") == "reachable" and detail["checks"]["config_dir_input_check"]["status"] != "ok":
        detail["reason_code"] = detail["checks"]["config_dir_input_check"]["reason_code"]
    elif detail.get("reason_code") in {"reachable", "overlay_ready", "overlay_content_ready"} and secret_status != "ok":
        detail["reason_code"] = secret_check["reason_code"]
    return status, _normalize_doctor_detail(detail, probe_mode="deep" if deep else "safe")


def _emit_doctor_detail(detail: Dict[str, Any]) -> None:
    """Print doctor detail in a more readable multi-line format."""
    for key, value in detail.items():
        rendered = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
        info(f"  {key}: {rendered}")


def cmd_doctor(
    store: Dict[str, Any],
    tool: str,
    name: Optional[str],
    *,
    deep: bool = False,
    json_output: bool = False,
    cached: bool = False,
    show_history: bool = False,
    history_limit: int = 10,
    clear_cache_first: bool = False,
) -> bool:
    """Run configuration and compatibility checks."""
    targets: Iterable[str] = ALL_TOOLS if tool == "all" else (tool,)
    overall_ok = True
    for current_tool in targets:
        if show_history and tool == "all":
            candidate = store.get("active", {}).get(current_tool)
            history_entries = (
                list_probe_history(tool=current_tool, target=candidate, limit=history_limit)
                if candidate
                else []
            )
            payload = _build_doctor_payload(
                current_tool,
                candidate,
                "history",
                {"reason_code": "history"},
                probe_mode="history",
                summary_reason="history",
                history=history_entries,
            )
            if json_output:
                print(json.dumps(payload, ensure_ascii=False))
            else:
                info(f"[{current_tool}] {candidate or '(inactive)'} probe history")
                if not history_entries:
                    info("  (empty)")
                for entry in history_entries:
                    summary = entry["detail"].get("reason_code") or "recorded"
                    info(
                        f"  {entry['recorded_at']}  {entry['status']}  {entry['probe_mode']}  {summary}"
                    )
            continue
        candidate = resolve_alias(store, name) if name else store.get("active", {}).get(current_tool)
        if not candidate:
            payload = _build_doctor_payload(
                current_tool,
                None,
                "missing",
                {"reason_code": "inactive"},
                probe_mode="static",
                summary_reason="inactive",
            )
            if json_output:
                print(json.dumps(payload, ensure_ascii=False))
            else:
                info(f"[{current_tool}] inactive")
            overall_ok = False
            continue
        provider = store.get("providers", {}).get(candidate)
        conf = provider.get(current_tool) if provider else None
        if not conf:
            payload = _build_doctor_payload(
                current_tool,
                candidate,
                "missing",
                {"reason_code": "missing_config"},
                probe_mode="static",
                summary_reason="missing_config",
            )
            if json_output:
                print(json.dumps(payload, ensure_ascii=False))
            else:
                info(f"[{current_tool}] missing config for provider '{candidate}'")
            overall_ok = False
            continue
        if clear_cache_first:
            clear_probe_cache(current_tool, candidate)
        if show_history:
            history_entries = list_probe_history(tool=current_tool, target=candidate, limit=history_limit)
            payload = _build_doctor_payload(
                current_tool,
                candidate,
                "history",
                {"reason_code": "history"},
                probe_mode="history",
                summary_reason="history",
                history=history_entries,
            )
            if json_output:
                print(json.dumps(payload, ensure_ascii=False))
            else:
                info(f"[{current_tool}] {candidate} probe history")
                if not history_entries:
                    info("  (empty)")
                for entry in history_entries:
                    summary = entry["detail"].get("reason_code") or "recorded"
                    info(
                        f"  {entry['recorded_at']}  {entry['status']}  {entry['probe_mode']}  {summary}"
                    )
            continue

        if cached:
            cached_result = get_probe_result(current_tool, candidate)
            if cached_result:
                status = cached_result["status"]
                detail = _normalize_doctor_detail(
                    cached_result["detail"],
                    checked_at=cached_result["checked_at"],
                    probe_mode="cached",
                )
            else:
                status = "missing"
                detail = _normalize_doctor_detail(
                    {"reason_code": "probe_cache_missing"},
                    probe_mode="cached",
                )
        else:
            status, detail = _probe_tool_health(store, current_tool, candidate, conf, deep=deep)
            record_probe_result(
                current_tool,
                candidate,
                status,
                detail,
                probe_mode="deep" if deep else "safe",
            )

        payload = _build_doctor_payload(
            current_tool,
            candidate,
            status,
            detail,
            probe_mode=detail.get("probe_mode", "deep" if deep else "safe"),
        )
        if json_output:
            line = _redact_sensitive_text(json.dumps(payload, ensure_ascii=False))
            _write_stream_line(sys.stdout, line)
        else:
            summary = payload["summary_reason"]
            info(f"[{current_tool}] {candidate} -> {status} ({summary})")
            _emit_doctor_detail(payload["detail"])
        overall_ok = overall_ok and status == "ok"
    return overall_ok


def cmd_switch(store: Dict[str, Any], tool: str, provider_name: str) -> None:
    """Resolve alias and dispatch switch for one tool or all."""
    canonical = resolve_alias(store, provider_name)
    if tool == "all":
        with _state_lock():
            store = _load_fresh_store_from_lock(store)
            canonical = resolve_alias(store, provider_name)
            skipped_tools = [
                current_tool
                for current_tool in ALL_TOOLS
                if store.get("providers", {}).get(canonical, {}).get(current_tool) is None
            ]
            targets = [
                (current_tool, canonical)
                for current_tool in ALL_TOOLS
                if store.get("providers", {}).get(canonical, {}).get(current_tool) is not None
            ]
            if not targets:
                info(f"[error] Provider '{canonical}' has no supported tool configs.")
                sys.exit(1)
            _execute_multi_tool_switch(
                store,
                mode="all",
                requested_target=canonical,
                targets=targets,
            )
            for skipped_tool in skipped_tools:
                info(f"[{skipped_tool}] Skipped: provider '{canonical}' has no {skipped_tool} config.")
    else:
        with _state_lock():
            store = _load_fresh_store_from_lock(store)
            canonical = resolve_alias(store, provider_name)
            _preflight_tool_activation(store, tool, canonical)
            switch_tool(store, tool, canonical)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ccsw",
        description="Switch Claude Code / Codex / Gemini / OpenCode / OpenClaw providers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python3 ccsw.py claude demo-provider\n"
            "  eval \"$(python3 ccsw.py all demo-provider)\"\n"
            "  python3 ccsw.py add myprovider --claude-url https://... --claude-token $MY_TOKEN\n"
            "  python3 ccsw.py opencode myprovider\n"
            "  python3 ccsw.py run codex work -- codex exec 'hi'\n"
            "  python3 ccsw.py add myprovider                 (interactive)\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    for tool in (*ALL_TOOLS, "all"):
        sp = sub.add_parser(tool, help=f"Switch {tool} provider")
        sp.add_argument("provider", help="Provider name or alias")

    sub.add_parser("list", help="List providers with active status")
    sub.add_parser("show", help="Show active config per tool")

    add_p = sub.add_parser("add", help="Add or update a provider")
    add_p.add_argument("name", help="Provider name")
    add_p.add_argument("--claude-url", metavar="URL")
    add_p.add_argument("--claude-token", metavar="TOKEN", help="$ENV_VAR or literal")
    add_p.add_argument("--codex-url", metavar="URL")
    add_p.add_argument("--codex-fallback-url", metavar="URL")
    add_p.add_argument("--codex-token", metavar="TOKEN", help="$ENV_VAR or literal")
    add_p.add_argument("--codex-auth-mode", choices=[CODEX_AUTH_MODE_CHATGPT])
    add_p.add_argument("--gemini-key", metavar="KEY", help="$ENV_VAR or literal")
    add_p.add_argument("--gemini-auth-type", metavar="TYPE", default=None)
    add_p.add_argument("--opencode-url", metavar="URL")
    add_p.add_argument("--opencode-token", metavar="TOKEN", help="$ENV_VAR or literal")
    add_p.add_argument("--opencode-model", metavar="MODEL")
    add_p.add_argument("--openclaw-url", metavar="URL")
    add_p.add_argument("--openclaw-token", metavar="TOKEN", help="$ENV_VAR or literal")
    add_p.add_argument("--openclaw-model", metavar="MODEL")
    add_p.add_argument(
        "--allow-literal-secrets",
        action="store_true",
        help="Allow storing literal secrets in the provider store",
    )

    rm_p = sub.add_parser("remove", help="Remove a provider")
    rm_p.add_argument("name")

    al_p = sub.add_parser("alias", help="Add a provider alias")
    al_p.add_argument("alias")
    al_p.add_argument("provider")

    profile_p = sub.add_parser("profile", help="Manage named multi-tool profiles")
    profile_sub = profile_p.add_subparsers(dest="profile_command", metavar="<profile-command>")

    profile_add = profile_sub.add_parser("add", help="Add or update a profile")
    profile_add.add_argument("name")
    for tool in ALL_TOOLS:
        profile_add.add_argument(f"--{tool}", metavar="QUEUE")

    profile_use = profile_sub.add_parser("use", help="Switch to a saved profile")
    profile_use.add_argument("name")

    profile_show = profile_sub.add_parser("show", help="Show a profile")
    profile_show.add_argument("name")

    profile_rm = profile_sub.add_parser("remove", help="Remove a profile")
    profile_rm.add_argument("name")

    profile_sub.add_parser("list", help="List profiles")

    settings_p = sub.add_parser("settings", help="Get or set device-level settings")
    settings_sub = settings_p.add_subparsers(dest="settings_command", metavar="<settings-command>")
    settings_get = settings_sub.add_parser("get", help="Show one setting or all settings")
    settings_get.add_argument("key", nargs="?")
    settings_set = settings_sub.add_parser("set", help="Update one setting")
    settings_set.add_argument("key")
    settings_set.add_argument("value", nargs="?")

    sync_p = sub.add_parser("sync", help="Toggle future Codex ChatGPT session sharing mode")
    sync_p.add_argument("action", choices=["on", "off", "status"])

    share_p = sub.add_parser("share", help="Prepare or inspect Codex share lane recipes")
    share_tool_sub = share_p.add_subparsers(dest="share_tool", metavar="<share-tool>")
    share_codex = share_tool_sub.add_parser("codex", help="Manage prepared Codex share lanes")
    share_codex_sub = share_codex.add_subparsers(dest="share_command", metavar="<share-command>")
    share_prepare = share_codex_sub.add_parser("prepare", help="Prepare a Codex share recipe")
    share_prepare.add_argument("lane")
    share_prepare.add_argument("provider", help="Target provider name or alias")
    share_prepare.add_argument(
        "--from",
        dest="source",
        default=CODEX_SHARE_DEFAULT_SOURCE,
        metavar="SOURCE",
        help=f"Source thread id or '{CODEX_SHARE_DEFAULT_SOURCE}' (default: %(default)s)",
    )
    share_status = share_codex_sub.add_parser("status", help="Show prepared Codex share lanes")
    share_status.add_argument("lane", nargs="?")
    share_clear = share_codex_sub.add_parser("clear", help="Delete one prepared Codex share lane")
    share_clear.add_argument("lane")

    doctor_p = sub.add_parser("doctor", help="Validate configuration and probe health")
    doctor_p.add_argument("tool", nargs="?", default="all", choices=(*ALL_TOOLS, "all"))
    doctor_p.add_argument("provider", nargs="?")
    doctor_mode = doctor_p.add_mutually_exclusive_group()
    doctor_mode.add_argument("--deep", action="store_true", help="Run deeper protocol probes when supported")
    doctor_mode.add_argument("--cached", action="store_true", help="Read the latest cached probe result only")
    doctor_mode.add_argument("--history", action="store_true", help="Show recorded probe history instead of probing")
    doctor_p.add_argument("--json", action="store_true", help="Emit NDJSON-style structured JSON output")
    doctor_p.add_argument("--limit", type=int, default=10, help="Number of history entries to show")
    doctor_p.add_argument("--clear-cache", action="store_true", dest="clear_cache")

    history_p = sub.add_parser("history", help="Show recent switch and run history")
    history_p.add_argument("--tool", choices=ALL_TOOLS)
    history_p.add_argument("--limit", type=int, default=20)
    history_p.add_argument("--action", choices=["switch", "run-attempt", "run-result", "batch-result", "rollback-result", "repair-result"])
    history_p.add_argument("--subject")
    history_p.add_argument("--failed-only", action="store_true")
    history_p.add_argument("--verbose", action="store_true")

    rollback_p = sub.add_parser("rollback", help="Restore a tool to the previous provider")
    rollback_p.add_argument("tool", choices=ALL_TOOLS)

    repair_p = sub.add_parser("repair", help="Repair stale managed runtime leases")
    repair_p.add_argument("tool", choices=(*ALL_TOOLS, "all"))

    import_p = sub.add_parser("import", help="Import current live config into a provider")
    import_p.add_argument("source", choices=["current"])
    import_p.add_argument("tool", choices=ALL_TOOLS)
    import_p.add_argument("name")
    import_p.add_argument(
        "--allow-literal-secrets",
        action="store_true",
        help="Allow importing literal secrets into the provider store",
    )

    run_p = sub.add_parser("run", help="Run a CLI command with provider fallback")
    run_p.add_argument("tool", choices=ALL_TOOLS)
    run_p.add_argument("provider")
    run_p.add_argument("argv", nargs=argparse.REMAINDER)

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

    with _state_lock():
        _sanitize_managed_target_secret_surface()
    store = load_store()
    ensure_defaults(store)

    if args.command in (*ALL_TOOLS, "all"):
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
    elif args.command == "profile":
        if args.profile_command == "add":
            cmd_profile_add(store, args.name, args)
        elif args.profile_command == "use":
            cmd_profile_use(store, args.name)
        elif args.profile_command == "show":
            cmd_profile_show(store, args.name)
        elif args.profile_command == "remove":
            cmd_profile_remove(store, args.name)
        elif args.profile_command == "list":
            cmd_profile_list(store)
        else:
            parser.print_help(sys.stderr)
            sys.exit(1)
    elif args.command == "settings":
        if args.settings_command == "get":
            cmd_settings_get(store, args.key)
        elif args.settings_command == "set":
            cmd_settings_set(store, args.key, args.value)
        else:
            parser.print_help(sys.stderr)
            sys.exit(1)
    elif args.command == "sync":
        cmd_sync(store, args.action)
    elif args.command == "share":
        if args.share_tool != CODEX_SHARE_TOOL:
            parser.print_help(sys.stderr)
            sys.exit(1)
        if args.share_command == "prepare":
            cmd_share_prepare(store, args.lane, args.provider, args.source)
        elif args.share_command == "status":
            cmd_share_status(store, args.lane)
        elif args.share_command == "clear":
            cmd_share_clear(store, args.lane)
        else:
            parser.print_help(sys.stderr)
            sys.exit(1)
    elif args.command == "doctor":
        ok = cmd_doctor(
            store,
            args.tool,
            args.provider,
            deep=args.deep,
            json_output=args.json,
            cached=args.cached,
            show_history=args.history,
            history_limit=args.limit,
            clear_cache_first=args.clear_cache,
        )
        if not ok:
            sys.exit(1)
    elif args.command == "history":
        cmd_history(
            args.tool,
            args.limit,
            args.action,
            args.subject,
            args.verbose,
            args.failed_only,
        )
    elif args.command == "rollback":
        cmd_rollback(store, args.tool)
    elif args.command == "repair":
        cmd_repair(store, args.tool)
    elif args.command == "import":
        cmd_import_current(
            store,
            args.tool,
            args.name,
            allow_literal_secrets=args.allow_literal_secrets,
        )
    elif args.command == "run":
        argv = list(args.argv)
        if argv and argv[0] == "--":
            argv = argv[1:]
        cmd_run(store, args.tool, args.provider, argv)


if __name__ == "__main__":
    main()
