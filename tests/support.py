import http.server
import json
import os
import stat
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from socketserver import TCPServer
from typing import Iterator, Sequence
from unittest.mock import patch

MANAGED_ENV_EXPORTS = {
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "GEMINI_API_KEY",
    "OPENCODE_CONFIG",
    "OPENCLAW_CONFIG_PATH",
    "OPENCLAW_PROFILE",
}


@contextmanager
def isolated_runtime_env(*, clear: bool = False) -> Iterator[dict[str, Path]]:
    """Provide a fully isolated ccsw runtime rooted in a temp directory."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        home = root / "home"
        xdg_config = root / "xdg-config"
        xdg_data = root / "xdg-data"
        local_env = root / ".env.local"
        home.mkdir()
        xdg_config.mkdir()
        xdg_data.mkdir()
        local_env.write_text("", encoding="utf-8")
        env = {
            "CCSW_HOME": str(root / ".ccswitch"),
            "CCSW_FAKE_HOME": str(home),
            "XDG_CONFIG_HOME": str(xdg_config),
            "XDG_DATA_HOME": str(xdg_data),
            "CCSW_LOCAL_ENV_PATH": str(local_env),
        }
        with patch.dict(os.environ, env, clear=clear):
            yield {
                "root": root,
                "home": home,
                "xdg_config": xdg_config,
                "xdg_data": xdg_data,
                "local_env": local_env,
            }


def build_cli_env(paths: dict[str, Path], extra_env: dict[str, str] | None = None) -> dict[str, str]:
    """Build a subprocess-friendly environment for isolated CLI smoke tests."""
    env = os.environ.copy()
    for key in MANAGED_ENV_EXPORTS:
        env.pop(key, None)
    env.update(
        {
            "CCSW_HOME": str(paths["root"] / ".ccswitch"),
            "CCSW_FAKE_HOME": str(paths["home"]),
            "XDG_CONFIG_HOME": str(paths["xdg_config"]),
            "XDG_DATA_HOME": str(paths["xdg_data"]),
            "CCSW_LOCAL_ENV_PATH": str(paths["local_env"]),
            "HOME": str(paths["home"]),
        }
    )
    if extra_env:
        env.update(extra_env)
    return env


def run_cli(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str],
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a CLI subprocess and return its completed process object."""
    result = subprocess.run(
        list(argv),
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"command failed: {' '.join(argv)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result


def run_shell(
    shell: str,
    script: str,
    *,
    cwd: Path,
    env: dict[str, str],
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run one real shell process for wrapper/source contract tests."""
    result = subprocess.run(
        [shell, "-c", script],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"shell command failed: {shell} -c {script}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


class _StubHandler(http.server.BaseHTTPRequestHandler):
    """Serve minimal provider-compatible endpoints for subprocess smoke tests."""

    def _send(self, code: int, payload: dict) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        if self.path.endswith("/models"):
            self._send(200, {"data": [{"id": "gpt-5.4"}]})
            return
        if self.path.endswith("/responses"):
            self._send(200, {"data": []})
            return
        self._send(200, {"ok": True, "path": self.path})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.endswith("/responses"):
            self._send(200, {"id": "resp_smoke"})
            return
        self._send(200, {"ok": True, "path": self.path})

    def log_message(self, _format: str, *_args: object) -> None:
        return


@contextmanager
def stub_server() -> Iterator[str]:
    """Provide one local HTTP server for provider/probe smoke tests."""
    server = TCPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def add_provider(env: dict[str, str], ccsw_py: Path, name: str, base_url: str, *, cwd: Path) -> None:
    """Insert one full-featured provider into an isolated CLI store."""
    run_cli(
        [
            "python3",
            str(ccsw_py),
            "add",
            name,
            "--claude-url",
            f"{base_url}/anthropic/{name}",
            "--claude-token",
            f"${name.upper()}_CLAUDE_TOKEN",
            "--codex-url",
            f"{base_url}/openai/{name}/v1",
            "--codex-token",
            f"${name.upper()}_CODEX_TOKEN",
            "--gemini-key",
            f"${name.upper()}_GEMINI_KEY",
            "--opencode-url",
            f"{base_url}/opencode/{name}",
            "--opencode-token",
            f"${name.upper()}_OPENCODE_TOKEN",
            "--opencode-model",
            "gpt-5.4",
            "--openclaw-url",
            f"{base_url}/openclaw/{name}",
            "--openclaw-token",
            f"${name.upper()}_OPENCLAW_TOKEN",
            "--openclaw-model",
            "claude-sonnet-4",
        ],
        cwd=cwd,
        env=env,
        check=True,
    )


def write_executable_script(path: Path, content: str) -> Path:
    """Write one executable helper script for subprocess-driven smoke tests."""
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path
