"""Test package defaults that keep direct unittest runs away from real user state."""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path


_TEST_HOME = Path(tempfile.mkdtemp(prefix="ccsw-test-home-"))
atexit.register(lambda: shutil.rmtree(_TEST_HOME, ignore_errors=True))

os.environ["HOME"] = str(_TEST_HOME)
os.environ.setdefault("CCSW_HOME", str(_TEST_HOME / ".ccswitch"))
os.environ.setdefault("CCSW_FAKE_HOME", str(_TEST_HOME))
os.environ.setdefault("XDG_CONFIG_HOME", str(_TEST_HOME / ".config"))
os.environ.setdefault("XDG_DATA_HOME", str(_TEST_HOME / ".local" / "share"))
os.environ.setdefault("CCSW_LOCAL_ENV_PATH", str(_TEST_HOME / ".env.local"))

for _key in (
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "GEMINI_API_KEY",
    "OPENCODE_CONFIG",
    "OPENCLAW_CONFIG_PATH",
    "OPENCLAW_PROFILE",
):
    os.environ.pop(_key, None)
