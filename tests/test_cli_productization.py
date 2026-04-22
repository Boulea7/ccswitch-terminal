import base64
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from hashlib import sha256
from contextlib import redirect_stdout
from io import StringIO
from argparse import Namespace
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import Mock, patch

import ccsw
from tests.support import build_cli_env, isolated_runtime_env


class ProductizationStoreTests(unittest.TestCase):
    def test_load_store_migrates_legacy_json_into_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            providers_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "active": {"claude": "legacy", "codex": None, "gemini": None},
                        "aliases": {"lg": "legacy"},
                        "providers": {
                            "legacy": {
                                "claude": {
                                    "base_url": "https://example.com/anthropic",
                                    "token": "$LEGACY_TOKEN",
                                    "extra_env": {},
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                store = ccsw.load_store()

            self.assertTrue(db_path.exists())
            self.assertIn("legacy", store["providers"])
            self.assertEqual(store["aliases"]["lg"], "legacy")
            self.assertEqual(store["active"]["claude"], "legacy")

    def test_save_store_writes_sqlite_and_json_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {"claude": "demo", "codex": None, "gemini": None},
                "aliases": {"dm": "demo"},
                "providers": {
                    "demo": {
                        "claude": {
                            "base_url": "https://example.com",
                            "token": "$DEMO_TOKEN",
                            "extra_env": {},
                        }
                    }
                },
                "profiles": {},
                "settings": {},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.save_store(store)
                loaded = ccsw.load_store()

            self.assertTrue(db_path.exists())
            self.assertTrue(providers_path.exists())
            self.assertEqual(loaded["active"]["claude"], "demo")
            self.assertIn("demo", loaded["providers"])

    def test_cmd_sync_updates_future_session_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.save_store(store)
                reloaded = ccsw.load_store()
                ccsw.cmd_sync(reloaded, "on")
                reloaded = ccsw.load_store()
                self.assertTrue(reloaded["settings"][ccsw.CODEX_SYNC_SETTING_KEY])
                ccsw.cmd_sync(reloaded, "off")
                reloaded = ccsw.load_store()

            self.assertFalse(reloaded["settings"][ccsw.CODEX_SYNC_SETTING_KEY])

    def test_cmd_share_prepare_saves_recipe_without_touching_live_codex_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            fake_home = root / "home"
            codex_dir = fake_home / ".codex"
            codex_dir.mkdir(parents=True)
            state_db_path = codex_dir / "state_5.sqlite"
            auth_path = codex_dir / "auth.json"
            config_path = codex_dir / "config.toml"
            auth_path.write_text(json.dumps({"auth_mode": "chatgpt"}), encoding="utf-8")
            config_path.write_text('model_provider = "openai"\n', encoding="utf-8")

            conn = sqlite3.connect(state_db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE threads (
                        id TEXT PRIMARY KEY,
                        rollout_path TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL,
                        source TEXT NOT NULL,
                        model_provider TEXT NOT NULL,
                        cwd TEXT NOT NULL,
                        title TEXT NOT NULL,
                        sandbox_policy TEXT NOT NULL,
                        approval_mode TEXT NOT NULL,
                        tokens_used INTEGER NOT NULL DEFAULT 0,
                        has_user_event INTEGER NOT NULL DEFAULT 0,
                        archived INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO threads(
                        id, rollout_path, created_at, updated_at, source, model_provider,
                        cwd, title, sandbox_policy, approval_mode, tokens_used, has_user_event, archived
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "thr-test-1",
                        "/tmp/rollout.jsonl",
                        1,
                        2,
                        "cli",
                        "openai",
                        "/tmp/work",
                        "Seed thread",
                        "workspace-write",
                        "on-request",
                        0,
                        1,
                        0,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {"pro": {"codex": {"auth_mode": "chatgpt"}}},
                "profiles": {},
                "settings": {},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch.object(
                ccsw, "_HOME", fake_home
            ), patch("ccsw.os.getcwd", return_value="/tmp/work"):
                ccsw.save_store(store)
                reloaded = ccsw.load_store()
                ccsw.cmd_share_prepare(reloaded, "work", "pro", "last")
                reloaded = ccsw.load_store()

            lane = reloaded["settings"][ccsw.CODEX_SHARE_SETTING_KEY]["work"]
            self.assertEqual(lane["source_thread_id"], "thr-test-1")
            self.assertEqual(lane["target_model_provider"], "openai")
            self.assertEqual(
                lane["commands"],
                [
                    "cxsw pro",
                    "codex -C /tmp/work fork --all thr-test-1",
                ],
            )
            self.assertEqual(json.loads(auth_path.read_text(encoding="utf-8")), {"auth_mode": "chatgpt"})
            self.assertEqual(config_path.read_text(encoding="utf-8"), 'model_provider = "openai"\n')

    def test_cmd_share_prepare_rechecks_provider_inside_state_lock(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {"p": "pro"},
            "providers": {"pro": {"codex": {"auth_mode": "chatgpt"}}},
            "profiles": {},
            "settings": {},
        }
        locked_store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {},
            "profiles": {},
            "settings": {},
            "_revision": 1,
        }

        with patch("ccsw._get_latest_codex_thread_for_cwd", return_value={
            "id": "thr-test-1",
            "title": "Seed thread",
            "cwd": "/tmp/work",
            "model_provider": "openai",
            "updated_at": 2,
        }), patch("ccsw.os.getcwd", return_value="/tmp/work"), patch(
            "ccsw._load_fresh_store_from_lock", return_value=locked_store
        ), patch("ccsw.save_store") as save_store:
            with self.assertRaises(SystemExit):
                ccsw.cmd_share_prepare(store, "work", "p", "last")

        save_store.assert_not_called()


class RuntimeIsolationTests(unittest.TestCase):
    def test_runtime_paths_follow_env_overrides_after_import(self) -> None:
        with isolated_runtime_env() as paths:
            expected_root = paths["root"] / ".ccswitch"
            expected_generated = expected_root / "generated"
            expected_tmp = expected_root / "tmp"
            expected_lock = expected_root / "ccswitch.lock"

            self.assertNotEqual(ccsw.GENERATED_DIR, expected_generated)
            self.assertEqual(ccsw._runtime_ccswitch_dir(), expected_root)
            self.assertEqual(ccsw._generated_dir(), expected_generated)
            self.assertEqual(ccsw._tmp_dir(), expected_tmp)
            self.assertEqual(ccsw._state_lock_path(), expected_lock)

    def test_load_store_and_state_lock_use_isolated_runtime_root(self) -> None:
        with isolated_runtime_env() as paths:
            expected_root = paths["root"] / ".ccswitch"
            expected_generated = expected_root / "generated"
            expected_tmp = expected_root / "tmp"
            expected_db = expected_root / "ccswitch.db"
            expected_lock = expected_root / "ccswitch.lock"

            store = ccsw.load_store()
            with ccsw._state_lock():
                pass

            self.assertEqual(store["version"], 2)
            self.assertTrue(expected_root.exists())
            self.assertTrue(expected_generated.exists())
            self.assertTrue(expected_tmp.exists())
            self.assertTrue(expected_db.exists())
            self.assertTrue(expected_lock.exists())

    def test_read_current_gemini_uses_isolated_active_env_path(self) -> None:
        with isolated_runtime_env() as paths:
            gemini_dir = paths["home"] / ".gemini"
            gemini_dir.mkdir(parents=True)
            (gemini_dir / "settings.json").write_text(
                json.dumps({"security": {"auth": {"selectedType": "api-key"}}}),
                encoding="utf-8",
            )
            ccswitch_dir = paths["root"] / ".ccswitch"
            ccswitch_dir.mkdir(parents=True, exist_ok=True)
            (ccswitch_dir / "active.env").write_text(
                "export GEMINI_API_KEY='isolated-key'\n",
                encoding="utf-8",
            )

            current = ccsw._read_current_gemini(
                {
                    "version": 2,
                    "active": {tool: None for tool in ccsw.ALL_TOOLS},
                    "aliases": {},
                    "providers": {},
                    "profiles": {},
                    "settings": {},
                }
            )

        self.assertEqual(current, {"api_key": "isolated-key", "auth_type": "api-key"})

    def test_build_cli_env_drops_ambient_managed_secret_exports(self) -> None:
        with isolated_runtime_env() as paths, patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "ambient-openai",
                "GEMINI_API_KEY": "ambient-gemini",
                "OPENCODE_CONFIG": "/tmp/ambient-opencode.json",
                "OPENCLAW_CONFIG_PATH": "/tmp/ambient-openclaw.json5",
                "OPENCLAW_PROFILE": "ambient-profile",
            },
            clear=False,
        ):
            env = build_cli_env(paths)

        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("GEMINI_API_KEY", env)
        self.assertNotIn("OPENCODE_CONFIG", env)
        self.assertNotIn("OPENCLAW_CONFIG_PATH", env)
        self.assertNotIn("OPENCLAW_PROFILE", env)


class SettingsOverrideTests(unittest.TestCase):
    def test_normalize_optional_dir_expands_env_vars(self) -> None:
        with patch.dict(os.environ, {"CCSW_TEST_ROOT": "/tmp/ccsw-target"}, clear=False):
            value = ccsw._normalize_optional_dir("$CCSW_TEST_ROOT/config")

        self.assertEqual(value, Path("/tmp/ccsw-target/config"))

    def test_codex_directory_override_changes_target_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            override_dir = root / "custom-codex"

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                store = ccsw.load_store()
                ccsw.set_setting(store, "codex_config_dir", str(override_dir))
                paths = ccsw.get_tool_paths(store, "codex")

            self.assertEqual(paths["dir"], override_dir)
            self.assertEqual(paths["auth"], override_dir / "auth.json")
            self.assertEqual(paths["config"], override_dir / "config.toml")

    def test_setting_directory_override_resyncs_current_active_provider(self) -> None:
        store = {
            "version": 2,
            "active": {"claude": None, "codex": "demo", "gemini": None, "opencode": None, "openclaw": None},
            "aliases": {},
            "providers": {"demo": {"codex": {"base_url": "https://example.com/v1", "token": "x"}}},
            "profiles": {},
            "settings": dict(ccsw.SETTINGS_DEFAULTS),
        }

        with patch("ccsw.save_store"), patch("ccsw.activate_tool_for_subprocess", return_value=({}, [])) as activate:
            ccsw.cmd_settings_set(store, "codex_config_dir", "/tmp/custom-codex")

        activate.assert_called_once_with(
            store,
            "codex",
            "demo",
            persist_state=False,
            fail_if_missing=True,
            write_activation_files=True,
        )

    def test_setting_directory_override_does_not_persist_when_resync_fails(self) -> None:
        store = {
            "version": 2,
            "active": {"claude": None, "codex": "demo", "gemini": None, "opencode": None, "openclaw": None},
            "aliases": {},
            "providers": {"demo": {"codex": {"base_url": "https://example.com/v1", "token": "x"}}},
            "profiles": {},
            "settings": dict(ccsw.SETTINGS_DEFAULTS),
        }

        with patch("ccsw.save_store") as save_store, patch(
            "ccsw.activate_tool_for_subprocess",
            side_effect=SystemExit(1),
        ):
            with self.assertRaises(SystemExit):
                ccsw.cmd_settings_set(store, "codex_config_dir", "/tmp/custom-codex")

        save_store.assert_not_called()
        self.assertIsNone(store["settings"]["codex_config_dir"])

    def test_setting_directory_override_resync_does_not_append_switch_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {
                    "claude": None,
                    "codex": "demo",
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {"base_url": "https://example.com/v1", "token": "x"}
                    }
                },
                "profiles": {},
                "settings": dict(ccsw.SETTINGS_DEFAULTS),
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.save_store(store)
                with patch("ccsw.activate_tool_for_subprocess", return_value=({}, [])):
                    ccsw.cmd_settings_set(store, "codex_config_dir", "/tmp/custom-codex")
                switch_entries = ccsw.list_history(limit=10, action="switch")

        self.assertEqual(switch_entries, [])

    def test_settings_set_rejects_unknown_key(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {},
            "profiles": {},
            "settings": dict(ccsw.SETTINGS_DEFAULTS),
        }

        with self.assertRaises(SystemExit):
            ccsw.cmd_settings_set(store, "unknown_key", "value")


class OverlayWriterTests(unittest.TestCase):
    def test_write_opencode_generates_overlay_and_env_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            env_path = root / "opencode.env"
            conf = {
                "base_url": "https://relay.example.com/v1",
                "token": "demo-token",
                "model": "gpt-5.4",
                "headers": {"x-demo": "1"},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "OPENCODE_ENV_PATH", env_path
            ), patch.object(ccsw, "GENERATED_DIR", generated_dir):
                exports = ccsw.write_opencode(conf, "demo")

            overlay_path = generated_dir / "opencode" / "demo.json"
            self.assertTrue(overlay_path.exists())
            self.assertIn(("OPENCODE_CONFIG", str(overlay_path)), exports)
            content = json.loads(overlay_path.read_text(encoding="utf-8"))
            self.assertIn("provider", content)
            self.assertIn("demo", content["provider"])
            self.assertEqual(
                content["provider"]["demo"]["options"]["baseURL"],
                "https://relay.example.com/v1",
            )

    def test_write_openclaw_generates_overlay_and_env_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            env_path = root / "openclaw.env"
            conf = {
                "base_url": "https://relay.example.com/v1",
                "token": "demo-token",
                "model": "claude-sonnet-4",
                "provider_id": "demo",
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "OPENCLAW_ENV_PATH", env_path
            ), patch.object(ccsw, "GENERATED_DIR", generated_dir):
                exports = ccsw.write_openclaw(conf, "demo")

            overlay_path = generated_dir / "openclaw" / "demo.json5"
            self.assertTrue(overlay_path.exists())
            self.assertIn(("OPENCLAW_CONFIG_PATH", str(overlay_path)), exports)
            content = json.loads(overlay_path.read_text(encoding="utf-8"))
            self.assertIn("models", content)
            self.assertIn("providers", content["models"])
            self.assertIn("demo", content["models"]["providers"])


class RelaxedJsonParsingTests(unittest.TestCase):
    def test_relaxed_parser_keeps_https_urls_when_stripping_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "openclaw.json"
            path.write_text(
                '{\n  "models": {\n    "providers": {\n      "demo": {\n        "baseUrl": "https://relay.example.com/v1", // inline note\n        "apiKey": "demo"\n      }\n    }\n  }\n}\n',
                encoding="utf-8",
            )

            data = ccsw._load_json_relaxed(path)

        self.assertEqual(
            data["models"]["providers"]["demo"]["baseUrl"],
            "https://relay.example.com/v1",
        )

    def test_relaxed_parser_accepts_json5_style_keys_and_single_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "openclaw.json"
            path.write_text(
                "{\n"
                "  models: {\n"
                "    providers: {\n"
                "      demo: {\n"
                "        baseUrl: 'https://relay.example.com/v1',\n"
                "        apiKey: 'demo-token',\n"
                "      },\n"
                "    },\n"
                "  },\n"
                "}\n",
                encoding="utf-8",
            )

            data = ccsw._load_json_relaxed(path)

        self.assertEqual(data["models"]["providers"]["demo"]["baseUrl"], "https://relay.example.com/v1")
        self.assertEqual(data["models"]["providers"]["demo"]["apiKey"], "demo-token")


class ProfileAndRunTests(unittest.TestCase):
    def test_profile_add_rejects_missing_provider(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {},
            "profiles": {},
            "settings": {},
        }

        args = Namespace(
            claude=None,
            codex="missing-provider",
            gemini=None,
            opencode=None,
            openclaw=None,
        )

        with self.assertRaises(SystemExit):
            ccsw.cmd_profile_add(store, "work", args)

    def test_run_fails_when_provider_has_no_matching_tool_config(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {
                "claude-only": {
                    "claude": {
                        "base_url": "https://example.com",
                        "token": "a",
                        "extra_env": {},
                    }
                }
            },
            "profiles": {},
            "settings": {},
        }

        result = subprocess.CompletedProcess(
            args=["echo", "hi"],
            returncode=0,
            stdout="hi\n",
            stderr="",
        )

        with patch("ccsw.subprocess.run", return_value=result) as run_cmd:
            with self.assertRaises(SystemExit):
                ccsw.cmd_run(store, "opencode", "claude-only", ["echo", "hi"])

        run_cmd.assert_not_called()

    def test_profile_use_switches_each_tool_to_first_candidate(self) -> None:
        store = {
            "version": 2,
            "active": {"claude": None, "codex": None, "gemini": None, "opencode": None, "openclaw": None},
            "aliases": {},
            "providers": {
                "claude-a": {"claude": {"base_url": "https://example.com", "token": "a", "extra_env": {}}},
                "codex-a": {"codex": {"base_url": "https://example.com/v1", "token": "b"}},
            },
            "profiles": {
                "work": {
                    "claude": ["claude-a"],
                    "codex": ["codex-a"],
                }
            },
            "settings": {},
        }

        with patch("ccsw.activate_tool_for_subprocess", return_value=({}, [])) as activate, patch(
            "ccsw.save_store"
        ):
            ccsw.cmd_profile_use(store, "work")

        activate.assert_any_call(
            store,
            "claude",
            "claude-a",
            persist_state=False,
            fail_if_missing=True,
            write_activation_files=True,
        )
        activate.assert_any_call(
            store,
            "codex",
            "codex-a",
            persist_state=False,
            fail_if_missing=True,
            write_activation_files=True,
        )

    def test_run_retries_next_candidate_on_retryable_failure(self) -> None:
        store = {
            "version": 2,
            "active": {"claude": None, "codex": None, "gemini": None, "opencode": None, "openclaw": None},
            "aliases": {},
            "providers": {
                "codex-primary": {"codex": {"base_url": "https://primary.example/v1", "token": "a"}},
                "codex-backup": {"codex": {"base_url": "https://backup.example/v1", "token": "b"}},
            },
            "profiles": {"work": {"codex": ["codex-primary", "codex-backup"]}},
            "settings": {},
        }

        first = subprocess.CompletedProcess(
            args=["codex", "exec", "hi"],
            returncode=1,
            stdout="",
            stderr="connection refused",
        )
        second = subprocess.CompletedProcess(
            args=["codex", "exec", "hi"],
            returncode=0,
            stdout="ok",
            stderr="",
        )

        with patch("ccsw.activate_tool_for_subprocess", side_effect=[({}, []), ({}, [])]), patch(
            "ccsw.subprocess.run", side_effect=[first, second]
        ) as run_cmd:
            result = ccsw.run_with_fallback(store, "codex", "work", ["codex", "exec", "hi"])

        self.assertEqual(result.returncode, 0)
        self.assertEqual(run_cmd.call_count, 2)

    def test_cmd_run_keeps_original_active_provider_after_temporary_fallback(self) -> None:
        store = {
            "version": 2,
            "active": {
                "claude": None,
                "codex": "codex-original",
                "gemini": None,
                "opencode": None,
                "openclaw": None,
            },
            "aliases": {},
            "providers": {
                "codex-primary": {"codex": {"base_url": "https://primary.example/v1", "token": "a"}},
                "codex-backup": {"codex": {"base_url": "https://backup.example/v1", "token": "b"}},
                "codex-original": {"codex": {"base_url": "https://original.example/v1", "token": "c"}},
            },
            "profiles": {"work": {"codex": ["codex-primary", "codex-backup"]}},
            "settings": {},
        }

        first = subprocess.CompletedProcess(
            args=["codex", "exec", "hi"],
            returncode=1,
            stdout="",
            stderr="connection refused",
        )
        second = subprocess.CompletedProcess(
            args=["codex", "exec", "hi"],
            returncode=0,
            stdout="ok",
            stderr="",
        )

        with patch("ccsw.activate_tool_for_subprocess", side_effect=[({}, []), ({}, [])]), patch(
            "ccsw._safe_local_restore_validation",
            return_value={"status": "ok", "reason_code": "ready"},
        ), patch("ccsw.subprocess.run", side_effect=[first, second]), patch("ccsw.info") as info:
            ccsw.cmd_run(store, "codex", "work", ["codex", "exec", "hi"])

        self.assertEqual(store["active"]["codex"], "codex-original")
        info_messages = [call.args[0] for call in info.call_args_list if call.args]
        self.assertTrue(
            any("Temporary fallback used for this command" in message for message in info_messages)
        )

    def test_run_fails_when_profile_has_no_queue_for_requested_tool(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {
                "claude-a": {
                    "claude": {"base_url": "https://example.com", "token": "a", "extra_env": {}}
                }
            },
            "profiles": {"work": {"claude": ["claude-a"]}},
            "settings": {},
        }

        with patch("ccsw.info") as info:
            with self.assertRaises(SystemExit):
                ccsw.cmd_run(store, "codex", "work", ["codex", "exec", "hi"])

        messages = [call.args[0] for call in info.call_args_list if call.args]
        self.assertTrue(any("has no codex queue" in message for message in messages))

    def test_profile_use_preflights_all_targets_before_switching(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {
                "claude-a": {
                    "claude": {"base_url": "https://example.com", "token": "a", "extra_env": {}}
                }
            },
            "profiles": {
                "work": {
                    "claude": ["claude-a"],
                    "codex": ["missing-codex"],
                }
            },
            "settings": {},
        }

        with patch("ccsw.switch_tool") as switch_tool:
            with self.assertRaises(SystemExit):
                ccsw.cmd_profile_use(store, "work")

        switch_tool.assert_not_called()

    def test_profile_use_errors_when_profile_has_no_configured_tools(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {},
            "profiles": {"empty": {}},
            "settings": {},
        }

        with patch("ccsw.info") as info, patch("ccsw.switch_tool") as switch_tool:
            with self.assertRaises(SystemExit):
                ccsw.cmd_profile_use(store, "empty")

        switch_tool.assert_not_called()
        messages = [call.args[0] for call in info.call_args_list if call.args]
        self.assertTrue(any("has no configured tool queues" in message for message in messages))

    def test_profile_show_keeps_empty_profile_visible(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {},
            "profiles": {"empty": {}},
            "settings": {},
        }

        with patch("ccsw.info") as info:
            ccsw.cmd_profile_show(store, "empty")

        messages = [call.args[0] for call in info.call_args_list if call.args]
        self.assertTrue(any("[profile] empty" in message for message in messages))

    def test_profile_add_rejects_empty_profile(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {},
            "profiles": {},
            "settings": {},
        }
        args = Namespace(
            claude=None,
            codex=None,
            gemini=None,
            opencode=None,
            openclaw=None,
        )

        with self.assertRaises(SystemExit):
            ccsw.cmd_profile_add(store, "empty", args)

    def test_profile_use_preflights_activation_requirements_before_writing(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {
                "claude-a": {
                    "claude": {"base_url": "https://example.com", "token": "$CLAUDE_TOKEN", "extra_env": {}}
                },
                "codex-bad": {
                    "codex": {"base_url": "https://example.com/v1", "token": "$MISSING_CODEX_TOKEN"}
                },
            },
            "profiles": {
                "work": {
                    "claude": ["claude-a"],
                    "codex": ["codex-bad"],
                }
            },
            "settings": {},
        }

        with patch.dict(os.environ, {"CLAUDE_TOKEN": "ok"}, clear=False), patch(
            "ccsw.switch_tool"
        ) as switch_tool:
            with self.assertRaises(SystemExit):
                ccsw.cmd_profile_use(store, "work")

        switch_tool.assert_not_called()

    def test_cmd_remove_prunes_deleted_provider_from_profiles(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {"demo-alias": "demo"},
            "providers": {
                "demo": {
                    "codex": {"base_url": "https://example.com/v1", "token": "a"},
                },
                "other": {
                    "codex": {"base_url": "https://backup.example.com/v1", "token": "b"},
                },
            },
            "profiles": {
                "work": {"codex": ["demo", "other"]},
                "secondary": {"codex": ["demo"]},
            },
            "settings": {},
        }

        with patch("ccsw.save_store"):
            ccsw.cmd_remove(store, "demo")

        self.assertEqual(store["profiles"]["work"]["codex"], ["other"])
        self.assertEqual(store["profiles"]["secondary"]["codex"], [])
        self.assertNotIn("demo-alias", store["aliases"])

    def test_run_with_fallback_records_setup_failures_as_non_retryable(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {
                "codex-primary": {"codex": {"base_url": "https://primary.example/v1", "token": "a"}},
                "codex-backup": {"codex": {"base_url": "https://backup.example/v1", "token": "b"}},
            },
            "profiles": {"work": {"codex": ["codex-primary", "codex-backup"]}},
            "settings": {},
        }

        with patch(
            "ccsw.activate_tool_for_subprocess",
            side_effect=SystemExit(1),
        ), patch("ccsw.record_history") as record_history, patch("ccsw.subprocess.run") as run_cmd:
            with self.assertRaises(SystemExit):
                ccsw.cmd_run(store, "codex", "work", ["codex", "exec", "hi"])

        run_cmd.assert_not_called()
        recorded_actions = [call.args[0] for call in record_history.call_args_list]
        self.assertIn("run-attempt", recorded_actions)
        self.assertIn("run-result", recorded_actions)

    def test_run_with_fallback_does_not_leak_local_env_injected_variables_to_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_env = root / ".env.local"
            local_env.write_text(
                "\n".join(
                    [
                        "UNRELATED_LOCAL_SECRET=top-secret",
                        "ANOTHER_SECRET=shadow",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {
                    "claude": None,
                    "codex": "demo",
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {"codex": {"base_url": "https://relay.example/v1", "token": "demo-token"}}
                },
                "profiles": {},
                "settings": {},
            }
            captured_env: dict[str, str] = {}

            def _run(*_args, **kwargs):
                captured_env.update(kwargs["env"])
                return subprocess.CompletedProcess(["codex", "exec", "hi"], 0, "ok", "")

            with patch.dict(os.environ, {}, clear=True), patch.object(
                ccsw, "LOCAL_ENV_PATH", local_env
            ), patch.object(ccsw, "LOCAL_ENV_INJECTED_KEYS", set()):
                ccsw.load_local_env()
                with patch(
                    "ccsw.activate_tool_for_subprocess",
                    return_value=({"OPENAI_API_KEY": "demo-token"}, ["OPENAI_BASE_URL"]),
                ), patch(
                    "ccsw._safe_local_restore_validation",
                    return_value={"status": "ok", "reason_code": "ready"},
                ), patch("ccsw.subprocess.run", side_effect=_run):
                    result = ccsw.run_with_fallback(store, "codex", "demo", ["codex", "exec", "hi"])

        self.assertEqual(result.returncode, 0)
        self.assertEqual(captured_env["OPENAI_API_KEY"], "demo-token")
        self.assertNotIn("UNRELATED_LOCAL_SECRET", captured_env)
        self.assertNotIn("ANOTHER_SECRET", captured_env)

    def test_run_with_fallback_strips_provider_source_secret_envs_from_child(self) -> None:
        store = {
            "version": 2,
            "active": {
                "claude": None,
                "codex": "demo",
                "gemini": None,
                "opencode": None,
                "openclaw": None,
            },
            "aliases": {},
            "providers": {
                "demo": {"codex": {"base_url": "https://relay.example/v1", "token": "$SOURCE_CODEX_TOKEN"}}
            },
            "profiles": {},
            "settings": {},
        }
        captured_env: dict[str, str] = {}

        def _run(*_args, **kwargs):
            captured_env.update(kwargs["env"])
            return subprocess.CompletedProcess(["codex", "exec", "hi"], 0, "ok", "")

        with patch.dict(os.environ, {"SOURCE_CODEX_TOKEN": "source-secret"}, clear=False), patch(
            "ccsw.activate_tool_for_subprocess",
            return_value=({"OPENAI_API_KEY": "resolved-secret"}, ["OPENAI_BASE_URL"]),
        ), patch(
            "ccsw._safe_local_restore_validation",
            return_value={"status": "ok", "reason_code": "ready"},
        ), patch("ccsw.subprocess.run", side_effect=_run):
            result = ccsw.run_with_fallback(store, "codex", "demo", ["codex", "exec", "hi"])

        self.assertEqual(result.returncode, 0)
        self.assertEqual(captured_env["OPENAI_API_KEY"], "resolved-secret")
        self.assertNotIn("SOURCE_CODEX_TOKEN", captured_env)

    def test_run_setup_failure_via_activation_error_does_not_spawn_child(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {
                "demo": {"codex": {"base_url": "https://relay.example/v1", "token": "demo-token"}}
            },
            "profiles": {},
            "settings": {},
        }

        with patch(
            "ccsw.activate_tool_for_subprocess",
            side_effect=SystemExit(1),
        ), patch("ccsw.subprocess.run") as run_cmd, patch("ccsw.record_history") as record_history:
            result = ccsw.run_with_fallback(store, "codex", "demo", ["codex", "exec", "hi"])

        run_cmd.assert_not_called()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(getattr(result, "_ccsw_final_failure_type"), "setup_failed")
        self.assertEqual(getattr(result, "_ccsw_attempt_count"), 1)
        attempt_payload = record_history.call_args_list[0].args[3]
        self.assertEqual(attempt_payload["phase"], "setup")
        self.assertEqual(attempt_payload["failure_type"], "setup_failed")
        self.assertFalse(attempt_payload["retryable"])

    def test_run_setup_permission_error_is_recorded_as_setup_failure(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {
                "demo": {"codex": {"base_url": "https://relay.example/v1", "token": "demo-token"}}
            },
            "profiles": {},
            "settings": {},
        }

        with patch(
            "ccsw.activate_tool_for_subprocess",
            side_effect=PermissionError("denied"),
        ), patch("ccsw.subprocess.run") as run_cmd, patch("ccsw.record_history") as record_history:
            result = ccsw.run_with_fallback(store, "codex", "demo", ["codex", "exec", "hi"])

        run_cmd.assert_not_called()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(getattr(result, "_ccsw_final_failure_type"), "setup_failed")
        attempt_payload = record_history.call_args_list[0].args[3]
        self.assertEqual(attempt_payload["phase"], "setup")
        self.assertEqual(attempt_payload["failure_type"], "setup_failed")
        self.assertFalse(attempt_payload["retryable"])

    def test_run_prefers_profile_when_profile_and_provider_names_collide(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {
                "work": {"codex": {"base_url": "https://provider.example/v1", "token": "provider-token"}},
                "backup": {"codex": {"base_url": "https://backup.example/v1", "token": "backup-token"}},
            },
            "profiles": {"work": {"codex": ["backup"]}},
            "settings": {},
        }

        candidates = ccsw._resolve_run_candidates(store, "codex", "work")

        self.assertEqual(candidates, ["backup"])

    def test_run_with_empty_profile_name_collision_fails_closed(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {
                "work": {"codex": {"base_url": "https://provider.example/v1", "token": "provider-token"}},
            },
            "profiles": {"work": {}},
            "settings": {},
        }

        with self.assertRaises(SystemExit):
            ccsw._resolve_run_candidates(store, "codex", "work")

    def test_cmd_run_records_rich_run_result_metadata(self) -> None:
        store = {
            "version": 2,
            "active": {
                "claude": None,
                "codex": "original",
                "gemini": None,
                "opencode": None,
                "openclaw": None,
            },
            "aliases": {},
            "providers": {
                "original": {"codex": {"base_url": "https://original.example/v1", "token": "orig"}},
            },
            "profiles": {"work": {"codex": ["demo", "backup"]}},
            "settings": {},
        }
        result = subprocess.CompletedProcess(
            args=["codex", "exec", "hi"],
            returncode=1,
            stdout="",
            stderr="unsupported",
        )
        setattr(result, "_ccsw_selected_candidate", "demo")
        setattr(result, "_ccsw_fallback_used", True)
        setattr(result, "_ccsw_original_active", "original")
        setattr(result, "_ccsw_attempt_count", 2)
        setattr(result, "_ccsw_source_kind", "profile")
        setattr(result, "_ccsw_final_failure_type", "non_retryable_config")
        setattr(result, "_ccsw_restore_status", "restored")
        setattr(result, "_ccsw_backup_artifacts_cleaned", True)

        with patch("ccsw.run_with_fallback", return_value=result), patch("ccsw.record_history") as record_history:
            with self.assertRaises(SystemExit):
                ccsw.cmd_run(store, "codex", "work", ["codex", "exec", "hi"])

        payload = record_history.call_args_list[-1].args[3]
        self.assertEqual(payload["attempt_count"], 2)
        self.assertEqual(payload["source_kind"], "profile")
        self.assertEqual(payload["final_failure_type"], "non_retryable_config")
        self.assertEqual(payload["restore_status"], "restored")
        self.assertTrue(payload["backup_artifacts_cleaned"])

    def test_cmd_run_records_run_result_when_restore_fails(self) -> None:
        store = {
            "version": 2,
            "active": {
                "claude": None,
                "codex": "original",
                "gemini": None,
                "opencode": None,
                "openclaw": None,
            },
            "aliases": {},
            "providers": {
                "original": {"codex": {"base_url": "https://original.example/v1", "token": "orig"}},
            },
            "profiles": {},
            "settings": {},
        }
        result = subprocess.CompletedProcess(
            args=["codex", "exec", "hi"],
            returncode=1,
            stdout="",
            stderr="restore failed",
        )
        setattr(result, "_ccsw_selected_candidate", "demo")
        setattr(result, "_ccsw_fallback_used", False)
        setattr(result, "_ccsw_original_active", "original")
        setattr(result, "_ccsw_attempt_count", 1)
        setattr(result, "_ccsw_source_kind", "provider")
        setattr(result, "_ccsw_final_failure_type", "ok")
        setattr(result, "_ccsw_restore_status", "restore_failed")
        setattr(result, "_ccsw_backup_artifacts_cleaned", False)

        with patch("ccsw.run_with_fallback", return_value=result), patch("ccsw.record_history") as record_history:
            with self.assertRaises(SystemExit):
                ccsw.cmd_run(store, "codex", "demo", ["codex", "exec", "hi"])

        payload = record_history.call_args_list[-1].args[3]
        self.assertEqual(payload["restore_status"], "restore_failed")
        self.assertFalse(payload["backup_artifacts_cleaned"])

    def test_classify_process_failure_treats_permission_error_as_non_retryable_cli(self) -> None:
        failure_type, retryable = ccsw._classify_process_failure(exc=PermissionError("denied"))

        self.assertEqual(failure_type, "non_retryable_cli")
        self.assertFalse(retryable)

    def test_run_with_fallback_does_not_leave_backup_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            config_path = codex_dir / "config.toml"
            env_path = root / "codex.env"
            auth_path.write_text(json.dumps({"OPENAI_API_KEY": "original"}), encoding="utf-8")
            config_path.write_text('model = "gpt-5.4"\n', encoding="utf-8")
            env_path.write_text("export OPENAI_API_KEY='original'\n", encoding="utf-8")

            store = {
                "version": 2,
                "active": {
                    "claude": None,
                    "codex": "demo",
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example.com/v1",
                            "token": "original",
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }
            result = subprocess.CompletedProcess(
                args=["codex", "exec", "hi"],
                returncode=0,
                stdout="ok",
                stderr="",
            )

            with patch.object(ccsw, "CODEX_ENV_PATH", env_path), patch(
                "ccsw.select_codex_base_url",
                return_value="https://relay.example.com/v1",
            ), patch("ccsw.subprocess.run", return_value=result):
                ccsw.run_with_fallback(store, "codex", "demo", ["codex", "exec", "hi"])

            self.assertEqual(
                sorted(path.name for path in codex_dir.glob("*.bak-*")),
                [],
            )
            self.assertEqual(
                auth_path.read_text(encoding="utf-8"),
                json.dumps({"OPENAI_API_KEY": "original"}),
            )
            self.assertEqual(
                config_path.read_text(encoding="utf-8"),
                'model = "gpt-5.4"\n',
            )
            self.assertEqual(
                env_path.read_text(encoding="utf-8"),
                "export OPENAI_API_KEY='original'\n",
            )

    def test_run_restore_conflict_preserves_external_change_and_marks_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            config_path = codex_dir / "config.toml"
            auth_path.write_text(json.dumps({"OPENAI_API_KEY": "original"}), encoding="utf-8")
            config_path.write_text('model = "gpt-5.4"\n', encoding="utf-8")
            store = {
                "version": 2,
                "active": {
                    "claude": None,
                    "codex": "demo",
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example.com/v1",
                            "token": "original",
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            def _run(*_args, **_kwargs):
                auth_path.write_text(
                    json.dumps({"OPENAI_API_KEY": "external-change"}),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(["codex", "exec", "hi"], 0, "ok\n", "")

            with patch("ccsw.select_codex_base_url", return_value="https://relay.example.com/v1"), patch(
                "ccsw.subprocess.run", side_effect=_run
            ):
                result = ccsw.run_with_fallback(store, "codex", "demo", ["codex", "exec", "hi"])

            self.assertEqual(result.returncode, 1)
            self.assertIn("restore conflict", result.stderr)
            self.assertEqual(
                json.loads(auth_path.read_text(encoding="utf-8"))["OPENAI_API_KEY"],
                "external-change",
            )
            self.assertEqual(getattr(result, "_ccsw_restore_status"), "restore_conflict")
            self.assertTrue(getattr(result, "_ccsw_restore_conflicts"))

    def test_run_restore_conflict_does_not_partially_restore_codex_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            config_path = codex_dir / "config.toml"
            auth_path.write_text(json.dumps({"OPENAI_API_KEY": "original"}), encoding="utf-8")
            config_path.write_text('model = "gpt-5.4"\n', encoding="utf-8")
            store = {
                "version": 2,
                "active": {
                    "claude": None,
                    "codex": "demo",
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example.com/v1",
                            "token": "original",
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            def _run(*_args, **_kwargs):
                auth_path.write_text(
                    json.dumps({"OPENAI_API_KEY": "external-change"}),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(["codex", "exec", "hi"], 0, "ok\n", "")

            with patch("ccsw.select_codex_base_url", return_value="https://relay.example.com/v1"), patch(
                "ccsw.subprocess.run", side_effect=_run
            ):
                result = ccsw.run_with_fallback(store, "codex", "demo", ["codex", "exec", "hi"])

            self.assertEqual(result.returncode, 1)
            self.assertIn("restore conflict", result.stderr)
            self.assertEqual(
                json.loads(auth_path.read_text(encoding="utf-8"))["OPENAI_API_KEY"],
                "external-change",
            )
            self.assertIn("ccswitch_active", config_path.read_text(encoding="utf-8"))

    def test_run_invalid_live_json_is_reported_in_post_restore_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            config_path = codex_dir / "config.toml"
            auth_path.write_text(json.dumps({"OPENAI_API_KEY": "original"}), encoding="utf-8")
            config_path.write_text('model = "gpt-5.4"\n', encoding="utf-8")
            store = {
                "version": 2,
                "active": {
                    "claude": None,
                    "codex": "demo",
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example.com/v1",
                            "token": "original",
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            def _run(*_args, **_kwargs):
                auth_path.write_text("{not-json", encoding="utf-8")
                return subprocess.CompletedProcess(["codex", "exec", "hi"], 0, "ok\n", "")

            with patch("ccsw.select_codex_base_url", return_value="https://relay.example.com/v1"), patch(
                "ccsw.subprocess.run", side_effect=_run
            ):
                result = ccsw.run_with_fallback(store, "codex", "demo", ["codex", "exec", "hi"])

            validation = getattr(result, "_ccsw_post_restore_validation")
            self.assertEqual(result.returncode, 1)
            self.assertEqual(validation["status"], "failed")
            self.assertEqual(validation["reason_code"], "validation_aborted")

    def test_run_opencode_runtime_overlay_does_not_touch_persistent_generated_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            generated_dir = root / "generated"
            persistent_overlay = generated_dir / "opencode" / "demo.json"
            persistent_overlay.parent.mkdir(parents=True)
            persistent_overlay.write_text('{"persistent": true}\n', encoding="utf-8")
            persistent_hash = sha256(persistent_overlay.read_bytes()).hexdigest()
            store = {
                "version": 2,
                "_revision": 1,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "demo": {
                        "opencode": {
                            "base_url": "https://relay.example.com/v1",
                            "token": "demo-token",
                        }
                    }
                },
                "profiles": {},
                "settings": {"opencode_config_dir": str(root / "opencode-home")},
            }
            captured_env: dict[str, str] = {}

            def _run(*_args, **kwargs):
                captured_env.update(kwargs["env"])
                return subprocess.CompletedProcess(["opencode", "run"], 0, "ok", "")

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(
                ccsw, "PROVIDERS_PATH", providers_path
            ), patch.object(
                ccsw, "TMP_DIR", root / "tmp"
            ), patch.object(
                ccsw, "GENERATED_DIR", generated_dir
            ), patch(
                "ccsw.subprocess.run", side_effect=_run
            ):
                ccsw.save_store(store)
                result = ccsw.run_with_fallback(ccsw.load_store(), "opencode", "demo", ["opencode", "run"])

            self.assertEqual(result.returncode, 0)
            self.assertEqual(sha256(persistent_overlay.read_bytes()).hexdigest(), persistent_hash)
            self.assertIn("OPENCODE_CONFIG", captured_env)
            self.assertNotEqual(captured_env["OPENCODE_CONFIG"], str(persistent_overlay))

    def test_run_opencode_runtime_overlay_mutation_does_not_trigger_restore_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            generated_dir = root / "generated"
            store = {
                "version": 2,
                "_revision": 1,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "demo": {
                        "opencode": {
                            "base_url": "https://relay.example.com/v1",
                            "token": "demo-token",
                        }
                    }
                },
                "profiles": {},
                "settings": {"opencode_config_dir": str(root / "opencode-home")},
            }

            def _run(*_args, **kwargs):
                runtime_overlay = Path(kwargs["env"]["OPENCODE_CONFIG"])
                runtime_overlay.write_text('{"mutated": true}\n', encoding="utf-8")
                return subprocess.CompletedProcess(["opencode", "run"], 0, "ok", "")

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(
                ccsw, "PROVIDERS_PATH", providers_path
            ), patch.object(
                ccsw, "TMP_DIR", root / "tmp"
            ), patch.object(
                ccsw, "GENERATED_DIR", generated_dir
            ), patch(
                "ccsw.subprocess.run", side_effect=_run
            ):
                ccsw.save_store(store)
                result = ccsw.run_with_fallback(ccsw.load_store(), "opencode", "demo", ["opencode", "run"])

            self.assertEqual(result.returncode, 0)
            self.assertEqual(getattr(result, "_ccsw_restore_status"), "restored")
            self.assertEqual(getattr(result, "_ccsw_restore_conflicts"), [])

    def test_run_cleanup_failure_sets_nonzero_exit_and_cleanup_failed_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "demo": {
                        "opencode": {
                            "base_url": "https://relay.example.com/v1",
                            "token": "demo-token",
                        }
                    }
                },
                "profiles": {},
                "settings": {"opencode_config_dir": str(root / "opencode-home")},
            }
            completed = subprocess.CompletedProcess(["opencode", "run"], 0, "ok", "")

            with patch.object(ccsw, "GENERATED_DIR", generated_dir), patch(
                "ccsw.subprocess.run", return_value=completed
            ), patch("ccsw.shutil.rmtree", side_effect=OSError("cleanup denied")):
                result = ccsw.run_with_fallback(store, "opencode", "demo", ["opencode", "run"])

            self.assertEqual(result.returncode, 1)
            self.assertIn("cleanup failed", result.stderr)
            self.assertEqual(getattr(result, "_ccsw_cleanup_status"), "cleanup_failed")

    def test_cmd_run_empty_command_fails_closed(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {},
            "profiles": {},
            "settings": {},
        }

        with self.assertRaises(SystemExit):
            ccsw.cmd_run(store, "codex", "demo", [])

    def test_classify_process_failure_covers_non_retryable_auth_and_config(self) -> None:
        auth_result = subprocess.CompletedProcess(["codex"], 1, "", "401 unauthorized")
        config_result = subprocess.CompletedProcess(["codex"], 1, "", "unsupported")

        auth_failure = ccsw._classify_process_failure(result=auth_result)
        config_failure = ccsw._classify_process_failure(result=config_result)

        self.assertEqual(auth_failure, ("non_retryable_auth", False))
        self.assertEqual(config_failure, ("non_retryable_config", False))

    def test_classify_process_failure_covers_retryable_exceptions(self) -> None:
        timeout_failure = ccsw._classify_process_failure(exc=subprocess.TimeoutExpired(["codex"], 1))
        os_error_failure = ccsw._classify_process_failure(exc=OSError("connection reset"))

        self.assertEqual(timeout_failure, ("retryable_network", True))
        self.assertEqual(os_error_failure, ("retryable_network", True))


class ImportRollbackAndDoctorTests(unittest.TestCase):
    def test_doctor_cached_uses_saved_probe_result_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {"demo": {"codex": {"base_url": "https://relay.example/v1", "token": "t"}}},
                "profiles": {},
                "settings": {},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.record_probe_result(
                    "codex",
                    "demo",
                    "ok",
                    {"reason_code": "models_ready", "selected_base_url": "https://relay.example/v1"},
                )
                with patch("ccsw._probe_tool_health") as probe, patch("ccsw.info") as info:
                    ok = ccsw.cmd_doctor(store, "codex", "demo", cached=True)

        self.assertTrue(ok)
        probe.assert_not_called()
        messages = [call.args[0] for call in info.call_args_list if call.args]
        self.assertTrue(any("models_ready" in message for message in messages))

    def test_doctor_json_payload_includes_summary_reason_and_probe_mode(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {"demo": {"codex": {"base_url": "https://relay.example/v1", "token": "t"}}},
            "profiles": {},
            "settings": {},
        }

        output = StringIO()
        with patch("ccsw._probe_tool_health", return_value=("ok", {"reason_code": "models_ready"})):
            with redirect_stdout(output):
                ok = ccsw.cmd_doctor(store, "codex", "demo", json_output=True)

        self.assertTrue(ok)
        payload = json.loads(output.getvalue().strip())
        self.assertEqual(payload["summary_reason"], "models_ready")
        self.assertEqual(payload["probe_mode"], "safe")
        self.assertEqual(payload["status"], "ok")

    def test_doctor_json_payload_uses_stable_top_level_fields(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {"demo": {"codex": {"base_url": "https://relay.example/v1", "token": "t"}}},
            "profiles": {},
            "settings": {},
        }

        output = StringIO()
        with patch(
            "ccsw._probe_tool_health",
            return_value=(
                "ok",
                {
                    "reason_code": "models_ready",
                    "checks": {"primary_models_probe": {"status": "ok"}},
                    "checked_at": "2026-04-13T21:00:00",
                },
            ),
        ):
            with redirect_stdout(output):
                ok = ccsw.cmd_doctor(store, "codex", "demo", json_output=True)

        self.assertTrue(ok)
        payload = json.loads(output.getvalue().strip())
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["checked_at"], "2026-04-13T21:00:00")
        self.assertIn("checks", payload)
        self.assertIn("detail", payload)
        self.assertEqual(payload["checks"]["primary_models_probe"]["status"], "ok")

    def test_doctor_json_cached_payload_uses_stable_top_level_fields_on_cache_miss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {"demo": {"codex": {"base_url": "https://relay.example/v1", "token": "t"}}},
                "profiles": {},
                "settings": {},
            }

            output = StringIO()
            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                with redirect_stdout(output):
                    ok = ccsw.cmd_doctor(store, "codex", "demo", json_output=True, cached=True)

        self.assertFalse(ok)
        payload = json.loads(output.getvalue().strip())
        self.assertEqual(payload["status"], "missing")
        self.assertEqual(payload["probe_mode"], "cached")
        self.assertEqual(payload["summary_reason"], "probe_cache_missing")
        self.assertIn("checked_at", payload)
        self.assertIn("checks", payload)
        self.assertIn("detail", payload)
        self.assertEqual(payload["history"], [])
        self.assertEqual(payload["detail"]["reason_code"], "probe_cache_missing")

    def test_doctor_json_history_payload_uses_stable_top_level_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {"demo": {"codex": {"base_url": "https://relay.example/v1", "token": "t"}}},
                "profiles": {},
                "settings": {},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.record_probe_result("codex", "demo", "ok", {"reason_code": "models_ready"})
                output = StringIO()
                with redirect_stdout(output):
                    ok = ccsw.cmd_doctor(store, "codex", "demo", json_output=True, show_history=True, history_limit=5)

        self.assertTrue(ok)
        payload = json.loads(output.getvalue().strip())
        self.assertEqual(payload["probe_mode"], "history")
        self.assertEqual(payload["summary_reason"], "history")
        self.assertEqual(payload["status"], "history")
        self.assertIn("checked_at", payload)
        self.assertIn("checks", payload)
        self.assertIn("detail", payload)
        self.assertEqual(payload["detail"]["reason_code"], "history")
        self.assertEqual(len(payload["history"]), 1)

    def test_doctor_json_inactive_payload_uses_stable_top_level_fields(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {},
            "profiles": {},
            "settings": {},
        }

        output = StringIO()
        with redirect_stdout(output):
            ok = ccsw.cmd_doctor(store, "codex", None, json_output=True)

        self.assertFalse(ok)
        payload = json.loads(output.getvalue().strip())
        self.assertEqual(payload["status"], "missing")
        self.assertIsNone(payload["target"])
        self.assertEqual(payload["probe_mode"], "static")
        self.assertEqual(payload["summary_reason"], "inactive")
        self.assertIn("checked_at", payload)
        self.assertIn("checks", payload)
        self.assertIn("detail", payload)
        self.assertEqual(payload["history"], [])

    def test_doctor_json_missing_config_payload_uses_stable_top_level_fields(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {"demo": {"claude": {"base_url": "https://relay.example", "token": "t", "extra_env": {}}}},
            "profiles": {},
            "settings": {},
        }

        output = StringIO()
        with redirect_stdout(output):
            ok = ccsw.cmd_doctor(store, "codex", "demo", json_output=True)

        self.assertFalse(ok)
        payload = json.loads(output.getvalue().strip())
        self.assertEqual(payload["status"], "missing")
        self.assertEqual(payload["target"], "demo")
        self.assertEqual(payload["probe_mode"], "static")
        self.assertEqual(payload["summary_reason"], "missing_config")
        self.assertEqual(payload["detail"]["reason_code"], "missing_config")
        self.assertIn("checked_at", payload)
        self.assertIn("checks", payload)
        self.assertIn("detail", payload)
        self.assertEqual(payload["history"], [])

    def test_doctor_all_json_emits_one_payload_per_tool_and_returns_nonzero_on_mixed_state(self) -> None:
        store = {
            "version": 2,
            "active": {
                "claude": "demo",
                "codex": "demo",
                "gemini": None,
                "opencode": None,
                "openclaw": None,
            },
            "aliases": {},
            "providers": {
                "demo": {
                    "claude": {"base_url": "https://relay.example", "token": "t", "extra_env": {}},
                    "codex": {"base_url": "https://relay.example/v1", "token": "t"},
                }
            },
            "profiles": {},
            "settings": {},
        }

        output = StringIO()
        with patch(
            "ccsw._probe_tool_health",
            side_effect=[
                ("ok", {"reason_code": "ready"}),
                ("degraded", {"reason_code": "http_only_responses"}),
            ],
        ):
            with redirect_stdout(output):
                ok = ccsw.cmd_doctor(store, "all", None, json_output=True)

        self.assertFalse(ok)
        lines = [json.loads(line) for line in output.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(lines), len(ccsw.ALL_TOOLS))
        self.assertEqual(lines[0]["tool"], "claude")
        self.assertEqual(lines[1]["tool"], "codex")
        self.assertEqual(lines[1]["status"], "degraded")
        self.assertEqual(lines[2]["status"], "missing")

    def test_record_probe_result_redacts_sample_and_error_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.record_probe_result(
                    "codex",
                    "demo",
                    "failed",
                    {
                        "reason_code": "network_error",
                        "sample": '{"secret":"value"}',
                        "error": "raw upstream error",
                    },
                )
                cached = ccsw.get_probe_result("codex", "demo")
                history = ccsw.list_probe_history(tool="codex", target="demo", limit=1)

        self.assertNotIn("sample", cached["detail"])
        self.assertNotIn("error", cached["detail"])
        self.assertTrue(cached["detail"]["sample_redacted"])
        self.assertTrue(cached["detail"]["error_redacted"])
        self.assertNotIn("sample", history[0]["detail"])
        self.assertNotIn("error", history[0]["detail"])

    def test_record_probe_result_redacts_nested_sensitive_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.record_probe_result(
                    "codex",
                    "demo",
                    "failed",
                    {
                        "reason_code": "network_error",
                        "checks": {
                            "request": {
                                "Authorization": "Bearer secret",
                                "api_key": "secret-key",
                                "token": "secret-token",
                            }
                        },
                    },
                )
                cached = ccsw.get_probe_result("codex", "demo")

        request_detail = cached["detail"]["checks"]["request"]
        self.assertNotIn("Authorization", request_detail)
        self.assertNotIn("api_key", request_detail)
        self.assertNotIn("token", request_detail)
        self.assertTrue(request_detail["authorization_redacted"])
        self.assertTrue(request_detail["api_key_redacted"])
        self.assertTrue(request_detail["token_redacted"])

    def test_record_probe_result_redacts_sensitive_header_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.record_probe_result(
                    "codex",
                    "demo",
                    "failed",
                    {
                        "reason_code": "network_error",
                        "checks": {
                            "request": {
                                "x-api-key": "secret-key",
                                "proxy-authorization": "Bearer proxy-secret",
                                "x-auth-token": "token-secret",
                            }
                        },
                    },
                )
                cached = ccsw.get_probe_result("codex", "demo")

        request_detail = cached["detail"]["checks"]["request"]
        self.assertNotIn("x-api-key", request_detail)
        self.assertNotIn("proxy-authorization", request_detail)
        self.assertNotIn("x-auth-token", request_detail)
        self.assertTrue(request_detail["x-api-key_redacted"])
        self.assertTrue(request_detail["proxy-authorization_redacted"])
        self.assertTrue(request_detail["x-auth-token_redacted"])

    def test_record_probe_result_redacts_token_variants_and_sensitive_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.record_probe_result(
                    "codex",
                    "demo",
                    "failed",
                    {
                        "reason_code": "network_error",
                        "checks": {
                            "request": {
                                "access_token": "secret-access",
                                "refresh_token": "secret-refresh",
                                "client_secret": "secret-client",
                            }
                        },
                        "url": "https://user:pass@example.com/v1/models?api_key=secret",
                        "selected_base_url": "https://user:pass@example.com/v1?token=secret",
                        "active_overlay": "/tmp/demo-secret-token/openclaw.json5",
                    },
                )
                cached = ccsw.get_probe_result("codex", "demo")

        request_detail = cached["detail"]["checks"]["request"]
        self.assertNotIn("access_token", request_detail)
        self.assertNotIn("refresh_token", request_detail)
        self.assertNotIn("client_secret", request_detail)
        self.assertTrue(request_detail["access_token_redacted"])
        self.assertTrue(request_detail["refresh_token_redacted"])
        self.assertTrue(request_detail["client_secret_redacted"])
        self.assertNotIn("url", cached["detail"])
        self.assertNotIn("selected_base_url", cached["detail"])
        self.assertNotIn("active_overlay", cached["detail"])
        self.assertTrue(cached["detail"]["url_redacted"])
        self.assertTrue(cached["detail"]["selected_base_url_redacted"])
        self.assertTrue(cached["detail"]["active_overlay_redacted"])

    def test_build_parser_accepts_doctor_flags(self) -> None:
        parser = ccsw.build_parser()

        args = parser.parse_args(
            [
                "doctor",
                "codex",
                "demo",
                "--deep",
                "--json",
                "--limit",
                "5",
            ]
        )

        self.assertTrue(args.deep)
        self.assertTrue(args.json)
        self.assertFalse(args.cached)
        self.assertFalse(args.history)
        self.assertEqual(args.limit, 5)
        self.assertFalse(args.clear_cache)

    def test_doctor_rejects_conflicting_flag_combinations(self) -> None:
        parser = ccsw.build_parser()

        with self.assertRaises(SystemExit):
            parser.parse_args(["doctor", "codex", "demo", "--history", "--deep"])
        with self.assertRaises(SystemExit):
            parser.parse_args(["doctor", "codex", "demo", "--history", "--cached"])
        with self.assertRaises(SystemExit):
            parser.parse_args(["doctor", "codex", "demo", "--cached", "--deep"])

    def test_build_parser_accepts_repair_command(self) -> None:
        parser = ccsw.build_parser()

        args = parser.parse_args(["repair", "codex"])

        self.assertEqual(args.command, "repair")
        self.assertEqual(args.tool, "codex")

    def test_build_parser_accepts_codex_chatgpt_auth_mode_flag(self) -> None:
        parser = ccsw.build_parser()

        args = parser.parse_args(["add", "pro", "--codex-auth-mode", "chatgpt"])

        self.assertEqual(args.command, "add")
        self.assertEqual(args.name, "pro")
        self.assertEqual(args.codex_auth_mode, "chatgpt")

    def test_build_parser_accepts_sync_command(self) -> None:
        parser = ccsw.build_parser()

        args = parser.parse_args(["sync", "on"])

        self.assertEqual(args.command, "sync")
        self.assertEqual(args.action, "on")

    def test_build_parser_accepts_share_prepare_command(self) -> None:
        parser = ccsw.build_parser()

        args = parser.parse_args(["share", "codex", "prepare", "work", "pro", "--from", "last"])

        self.assertEqual(args.command, "share")
        self.assertEqual(args.share_tool, "codex")
        self.assertEqual(args.share_command, "prepare")
        self.assertEqual(args.lane, "work")
        self.assertEqual(args.provider, "pro")
        self.assertEqual(args.source, "last")

    def test_import_current_codex_prefers_ccswitch_active_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            (codex_dir / "auth.json").write_text(
                json.dumps({"OPENAI_API_KEY": "demo-token"}),
                encoding="utf-8",
            )
            (codex_dir / "config.toml").write_text(
                '\n'.join(
                    [
                        'model_provider = "ccswitch_active"',
                        "",
                        "[model_providers.other]",
                        'name = "other"',
                        'base_url = "https://wrong.example/v1"',
                        "",
                        "[model_providers.ccswitch_active]",
                        'name = "ccswitch: demo"',
                        'base_url = "https://correct.example/v1"',
                        'env_key = "OPENAI_API_KEY"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch("ccsw.save_store"):
                ccsw.cmd_import_current(store, "codex", "imported", allow_literal_secrets=True)

        self.assertEqual(
            store["providers"]["imported"]["codex"]["base_url"],
            "https://correct.example/v1",
        )

    def test_import_current_codex_prefers_selected_model_provider_before_stale_ccswitch_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            (codex_dir / "auth.json").write_text(
                json.dumps({"OPENAI_API_KEY": "demo-token"}),
                encoding="utf-8",
            )
            (codex_dir / "config.toml").write_text(
                '\n'.join(
                    [
                        'model_provider = "other"',
                        "",
                        "[model_providers.other]",
                        'name = "other"',
                        'base_url = "https://selected.example/v1"',
                        'env_key = "OPENAI_API_KEY"',
                        "",
                        "[model_providers.ccswitch_active]",
                        'name = "ccswitch: stale"',
                        'base_url = "https://stale.example/v1"',
                        'env_key = "OPENAI_API_KEY"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch("ccsw.save_store"):
                ccsw.cmd_import_current(store, "codex", "imported", allow_literal_secrets=True)

        self.assertEqual(
            store["providers"]["imported"]["codex"]["base_url"],
            "https://selected.example/v1",
        )

    def test_import_current_codex_detects_chatgpt_auth_mode_without_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            (codex_dir / "auth.json").write_text(
                json.dumps({"auth_mode": "chatgpt", "chatgpt_session": {"access_token": "demo"}}),
                encoding="utf-8",
            )
            (codex_dir / "config.toml").write_text(
                'model_provider = "openai"\n',
                encoding="utf-8",
            )

            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch("ccsw.save_store"):
                ccsw.cmd_import_current(store, "codex", "pro")

        self.assertEqual(
            store["providers"]["pro"]["codex"],
            {"auth_mode": "chatgpt"},
        )

    def test_import_current_gemini_reads_escaped_secret_from_active_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gemini_dir = root / ".gemini"
            gemini_dir.mkdir(parents=True)
            (gemini_dir / "settings.json").write_text(
                json.dumps({"security": {"auth": {"selectedType": "api-key"}}}),
                encoding="utf-8",
            )
            active_env = root / "active.env"
            active_env.write_text(
                "export GEMINI_API_KEY='demo'\\''quoted'\n",
                encoding="utf-8",
            )

            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"gemini_config_dir": str(gemini_dir)},
            }

            with patch.object(ccsw, "ACTIVE_ENV_PATH", active_env), patch("ccsw.save_store"):
                ccsw.cmd_import_current(store, "gemini", "rescued", allow_literal_secrets=True)

        self.assertEqual(
            store["providers"]["rescued"]["gemini"]["api_key"],
            "demo'quoted",
        )

    def test_import_current_gemini_prefers_active_env_over_ambient_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gemini_dir = root / ".gemini"
            gemini_dir.mkdir(parents=True)
            (gemini_dir / "settings.json").write_text(
                json.dumps({"security": {"auth": {"selectedType": "api-key"}}}),
                encoding="utf-8",
            )
            active_env = root / "active.env"
            active_env.write_text(
                "export GEMINI_API_KEY='file-key'\n",
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"gemini_config_dir": str(gemini_dir)},
            }

            with patch.object(ccsw, "ACTIVE_ENV_PATH", active_env), patch.dict(
                os.environ,
                {"GEMINI_API_KEY": "ambient-key"},
                clear=False,
            ), patch("ccsw.save_store"):
                ccsw.cmd_import_current(store, "gemini", "rescued", allow_literal_secrets=True)

        self.assertEqual(
            store["providers"]["rescued"]["gemini"]["api_key"],
            "file-key",
        )

    def test_import_current_opencode_prefers_active_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay_path = root / "active-opencode.json"
            overlay_path.write_text(
                json.dumps(
                    {
                        "provider": {
                            "demo": {
                                "options": {
                                    "baseURL": "https://relay.example.com/v1",
                                    "apiKey": "overlay-token",
                                }
                            }
                        },
                        "model": "gpt-5.4",
                    }
                ),
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"opencode_config_dir": str(root)},
            }

            with patch.dict(os.environ, {"OPENCODE_CONFIG": str(overlay_path)}, clear=False), patch(
                "ccsw.save_store"
            ):
                ccsw.cmd_import_current(store, "opencode", "overlayed", allow_literal_secrets=True)

        self.assertEqual(
            store["providers"]["overlayed"]["opencode"]["base_url"],
            "https://relay.example.com/v1",
        )
        self.assertEqual(
            store["providers"]["overlayed"]["opencode"]["token"],
            "overlay-token",
        )

    def test_import_current_opencode_imports_safe_metadata_from_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay_path = root / "active-opencode.json"
            overlay_path.write_text(
                json.dumps(
                    {
                        "provider": {
                            "demo-provider": {
                                "npm": "@ai-sdk/custom",
                                "options": {
                                    "baseURL": "https://relay.example.com/v1",
                                    "apiKey": "overlay-token",
                                    "headers": {"x-demo": "1"},
                                },
                            }
                        },
                        "model": "gpt-5.4",
                    }
                ),
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"opencode_config_dir": str(root)},
            }

            with patch.dict(os.environ, {"OPENCODE_CONFIG": str(overlay_path)}, clear=False), patch(
                "ccsw.save_store"
            ):
                ccsw.cmd_import_current(store, "opencode", "overlayed", allow_literal_secrets=True)

        imported = store["providers"]["overlayed"]["opencode"]
        self.assertEqual(imported["provider_id"], "demo-provider")
        self.assertEqual(imported["headers"], {"x-demo": "1"})
        self.assertEqual(imported["npm"], "@ai-sdk/custom")
        self.assertEqual(imported["model"], "gpt-5.4")

    def test_import_current_opencode_rejects_sensitive_headers_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay_path = root / "active-opencode.json"
            overlay_path.write_text(
                json.dumps(
                    {
                        "provider": {
                            "demo-provider": {
                                "options": {
                                    "baseURL": "https://relay.example.com/v1",
                                    "apiKey": "overlay-token",
                                    "headers": {"Authorization": "Bearer secret"},
                                },
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"opencode_config_dir": str(root)},
            }

            with patch.dict(os.environ, {"OPENCODE_CONFIG": str(overlay_path)}, clear=False):
                with self.assertRaises(SystemExit):
                    ccsw.cmd_import_current(store, "opencode", "overlayed")

    def test_import_current_opencode_rejects_non_allowlisted_headers_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay_path = root / "active-opencode.json"
            overlay_path.write_text(
                json.dumps(
                    {
                        "provider": {
                            "demo-provider": {
                                "options": {
                                    "baseURL": "https://relay.example.com/v1",
                                    "apiKey": "overlay-token",
                                    "headers": {"X-Session": "Bearer secret"},
                                },
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"opencode_config_dir": str(root)},
            }

            with patch.dict(os.environ, {"OPENCODE_CONFIG": str(overlay_path)}, clear=False):
                with self.assertRaises(SystemExit):
                    ccsw.cmd_import_current(store, "opencode", "overlayed")

    def test_import_current_opencode_clears_removed_optional_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay_path = root / "active-opencode.json"
            overlay_path.write_text(
                json.dumps(
                    {
                        "provider": {
                            "demo-provider": {
                                "options": {
                                    "baseURL": "https://relay.example.com/v1",
                                    "apiKey": "overlay-token",
                                },
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "overlayed": {
                        "opencode": {
                            "provider_id": "demo-provider",
                            "headers": {"x-stale": "1"},
                            "npm": "@ai-sdk/stale",
                            "model": "gpt-4.1",
                        }
                    }
                },
                "profiles": {},
                "settings": {},
            }

            with patch.dict(os.environ, {"OPENCODE_CONFIG": str(overlay_path)}, clear=False), patch(
                "ccsw.save_store"
            ):
                ccsw.cmd_import_current(store, "opencode", "overlayed", allow_literal_secrets=True)

        imported = store["providers"]["overlayed"]["opencode"]
        self.assertNotIn("headers", imported)
        self.assertNotIn("npm", imported)
        self.assertNotIn("model", imported)

    def test_import_current_opencode_rejects_ambiguous_multi_provider_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay_path = root / "active-opencode.json"
            overlay_path.write_text(
                json.dumps(
                    {
                        "provider": {
                            "first": {"options": {"baseURL": "https://first.example/v1", "apiKey": "one"}},
                            "second": {"options": {"baseURL": "https://second.example/v1", "apiKey": "two"}},
                        }
                    }
                ),
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"openclaw_config_dir": str(root)},
            }

            with patch.dict(os.environ, {"OPENCODE_CONFIG": str(overlay_path)}, clear=False), patch(
                "ccsw.save_store"
            ):
                with self.assertRaises(SystemExit):
                    ccsw.cmd_import_current(store, "opencode", "overlayed")

    def test_import_current_openclaw_merges_existing_safe_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay_path = root / "active-openclaw.json5"
            overlay_path.write_text(
                json.dumps(
                    {
                        "models": {
                            "providers": {
                                "demo": {
                                    "baseUrl": "https://relay.example.com/v1",
                                    "apiKey": "overlay-token",
                                    "api": "responses",
                                }
                            }
                        },
                        "agents": {"defaults": {"model": {"primary": "claude-sonnet-4"}}},
                    }
                ),
                encoding="utf-8",
            )
            env_path = root / ".env"
            env_path.write_text("OPENCLAW_PROFILE=blue-team\n", encoding="utf-8")
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "rescued": {
                        "openclaw": {
                            "api": "responses",
                            "profile": "blue-team",
                        }
                    }
                },
                "profiles": {},
                "settings": {"openclaw_config_dir": str(root)},
            }

            with patch.dict(os.environ, {"OPENCLAW_CONFIG_PATH": str(overlay_path)}, clear=False), patch(
                "ccsw.save_store"
            ):
                ccsw.cmd_import_current(store, "openclaw", "rescued", allow_literal_secrets=True)

        self.assertEqual(
            store["providers"]["rescued"]["openclaw"]["api"],
            "responses",
        )
        self.assertEqual(
            store["providers"]["rescued"]["openclaw"]["profile"],
            "blue-team",
        )
        self.assertEqual(
            store["providers"]["rescued"]["openclaw"]["base_url"],
            "https://relay.example.com/v1",
        )

    def test_import_current_openclaw_imports_safe_metadata_from_overlay_and_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay_path = root / "active-openclaw.json5"
            overlay_path.write_text(
                json.dumps(
                    {
                        "models": {
                            "providers": {
                                "demo-provider": {
                                    "baseUrl": "https://relay.example.com/v1",
                                    "apiKey": "overlay-token",
                                    "api": "responses",
                                }
                            }
                        },
                        "agents": {"defaults": {"model": {"primary": "claude-sonnet-4"}}},
                    }
                ),
                encoding="utf-8",
            )
            env_path = root / ".env"
            env_path.write_text("OPENCLAW_PROFILE=blue-team\n", encoding="utf-8")
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"openclaw_config_dir": str(root)},
            }

            with patch.dict(os.environ, {"OPENCLAW_CONFIG_PATH": str(overlay_path)}, clear=False), patch(
                "ccsw.save_store"
            ):
                ccsw.cmd_import_current(store, "openclaw", "rescued", allow_literal_secrets=True)

        imported = store["providers"]["rescued"]["openclaw"]
        self.assertEqual(imported["provider_id"], "demo-provider")
        self.assertEqual(imported["api"], "responses")
        self.assertEqual(imported["profile"], "blue-team")
        self.assertEqual(imported["model"], "claude-sonnet-4")

    def test_import_current_openclaw_clears_removed_optional_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay_path = root / "active-openclaw.json5"
            overlay_path.write_text(
                json.dumps(
                    {
                        "models": {
                            "providers": {
                                "demo-provider": {
                                    "baseUrl": "https://relay.example.com/v1",
                                    "apiKey": "overlay-token",
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "rescued": {
                        "openclaw": {
                            "provider_id": "demo-provider",
                            "api": "responses",
                            "profile": "blue-team",
                            "model": "claude-sonnet-4",
                        }
                    }
                },
                "profiles": {},
                "settings": {},
            }

            with patch.dict(os.environ, {"OPENCLAW_CONFIG_PATH": str(overlay_path)}, clear=False), patch(
                "ccsw.save_store"
            ):
                ccsw.cmd_import_current(store, "openclaw", "rescued", allow_literal_secrets=True)

        imported = store["providers"]["rescued"]["openclaw"]
        self.assertNotIn("api", imported)
        self.assertNotIn("profile", imported)
        self.assertNotIn("model", imported)

    def test_import_current_openclaw_rejects_ambiguous_multi_provider_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay_path = root / "active-openclaw.json5"
            overlay_path.write_text(
                json.dumps(
                    {
                        "models": {
                            "providers": {
                                "first": {"baseUrl": "https://first.example/v1", "apiKey": "one"},
                                "second": {"baseUrl": "https://second.example/v1", "apiKey": "two"},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"opencode_config_dir": str(root)},
            }

            with patch.dict(os.environ, {"OPENCLAW_CONFIG_PATH": str(overlay_path)}, clear=False), patch(
                "ccsw.save_store"
            ) as save_store:
                with self.assertRaises(SystemExit):
                    ccsw.cmd_import_current(store, "openclaw", "rescued")

        save_store.assert_not_called()
        self.assertNotIn("rescued", store["providers"])

    def test_import_current_openclaw_falls_back_to_config_dir_when_activation_overlay_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "openclaw.json"
            config_path.write_text(
                json.dumps(
                    {
                        "models": {
                            "providers": {
                                "demo-provider": {
                                    "baseUrl": "https://relay.example.com/v1",
                                    "apiKey": "overlay-token",
                                    "api": "responses",
                                }
                            }
                        },
                        "agents": {"defaults": {"model": {"primary": "claude-sonnet-4"}}},
                    }
                ),
                encoding="utf-8",
            )
            (root / ".env").write_text("OPENCLAW_PROFILE=blue-team\n", encoding="utf-8")
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"openclaw_config_dir": str(root)},
            }

            with patch.dict(os.environ, {}, clear=True), patch.object(
                ccsw,
                "OPENCLAW_ENV_PATH",
                root / "openclaw.env",
            ), patch("ccsw.save_store") as save_store:
                ccsw.cmd_import_current(store, "openclaw", "rescued", allow_literal_secrets=True)

        imported = store["providers"]["rescued"]["openclaw"]
        self.assertEqual(imported["provider_id"], "demo-provider")
        self.assertEqual(imported["base_url"], "https://relay.example.com/v1")
        self.assertEqual(imported["token"], "overlay-token")
        self.assertEqual(imported["api"], "responses")
        self.assertEqual(imported["model"], "claude-sonnet-4")
        self.assertEqual(imported["profile"], "blue-team")
        save_store.assert_called_once()

    def test_import_current_openclaw_falls_back_when_activation_overlay_is_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay_path = root / "active-openclaw.json5"
            overlay_path.write_text(
                json.dumps({"models": {"providers": {"demo-provider": {"apiKey": "overlay-token"}}}}),
                encoding="utf-8",
            )
            config_path = root / "openclaw.json"
            config_path.write_text(
                json.dumps(
                    {
                        "models": {
                            "providers": {
                                "demo-provider": {
                                    "baseUrl": "https://relay.example.com/v1",
                                    "apiKey": "config-token",
                                    "api": "responses",
                                }
                            }
                        },
                        "agents": {"defaults": {"model": {"primary": "claude-sonnet-4"}}},
                    }
                ),
                encoding="utf-8",
            )
            (root / ".env").write_text("OPENCLAW_PROFILE=blue-team\n", encoding="utf-8")
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"openclaw_config_dir": str(root)},
            }

            with patch.dict(os.environ, {"OPENCLAW_CONFIG_PATH": str(overlay_path)}, clear=False), patch(
                "ccsw.save_store"
            ) as save_store:
                ccsw.cmd_import_current(store, "openclaw", "rescued", allow_literal_secrets=True)

        imported = store["providers"]["rescued"]["openclaw"]
        self.assertEqual(imported["provider_id"], "demo-provider")
        self.assertEqual(imported["base_url"], "https://relay.example.com/v1")
        self.assertEqual(imported["token"], "config-token")
        self.assertEqual(imported["api"], "responses")
        self.assertEqual(imported["model"], "claude-sonnet-4")
        self.assertEqual(imported["profile"], "blue-team")
        save_store.assert_called_once()

    def test_import_switch_doctor_opencode_forms_a_closed_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay_path = root / "active-opencode.json"
            overlay_path.write_text(
                json.dumps(
                    {
                        "provider": {
                            "demo-provider": {
                                "npm": "@ai-sdk/openai-compatible",
                                "options": {
                                    "baseURL": "https://relay.example.com/v1",
                                    "apiKey": "overlay-token",
                                },
                            }
                        },
                        "model": "gpt-5.4",
                    }
                ),
                encoding="utf-8",
            )
            generated_dir = root / "generated"
            env_path = root / "opencode.env"
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"opencode_config_dir": str(root)},
            }

            with patch.dict(os.environ, {"OPENCODE_CONFIG": str(overlay_path)}, clear=False), patch(
                "ccsw.save_store"
            ):
                ccsw.cmd_import_current(store, "opencode", "rescued", allow_literal_secrets=True)

            with patch.object(ccsw, "GENERATED_DIR", generated_dir), patch.object(
                ccsw, "OPENCODE_ENV_PATH", env_path
            ), patch("ccsw.save_store"), patch("ccsw.record_history"):
                exports, _ = ccsw.activate_tool_for_subprocess(
                    store,
                    "opencode",
                    "rescued",
                    persist_state=True,
                )

                self.assertEqual(exports["OPENCODE_CONFIG"], str(generated_dir / "opencode" / "rescued.json"))
                with patch("ccsw._generic_url_probe", return_value=("ok", {"reason_code": "reachable"})):
                    status, detail = ccsw._probe_tool_health(
                        store,
                        "opencode",
                        "rescued",
                        store["providers"]["rescued"]["opencode"],
                    )

        self.assertEqual(status, "degraded")
        self.assertEqual(detail["reason_code"], "store_literal_secret")

    def test_import_switch_doctor_openclaw_forms_a_closed_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay_path = root / "active-openclaw.json5"
            overlay_path.write_text(
                json.dumps(
                    {
                        "models": {
                            "providers": {
                                "demo-provider": {
                                    "baseUrl": "https://relay.example.com/v1",
                                    "apiKey": "overlay-token",
                                    "api": "responses",
                                }
                            }
                        },
                        "agents": {"defaults": {"model": {"primary": "claude-sonnet-4"}}},
                    }
                ),
                encoding="utf-8",
            )
            generated_dir = root / "generated"
            env_path = root / "openclaw.env"
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {},
            }

            with patch.dict(
                os.environ,
                {
                    "OPENCLAW_CONFIG_PATH": str(overlay_path),
                    "OPENCLAW_PROFILE": "blue-team",
                },
                clear=False,
            ), patch("ccsw.save_store"):
                ccsw.cmd_import_current(store, "openclaw", "rescued", allow_literal_secrets=True)

            with patch.object(ccsw, "GENERATED_DIR", generated_dir), patch.object(
                ccsw, "OPENCLAW_ENV_PATH", env_path
            ), patch("ccsw.save_store"), patch("ccsw.record_history"):
                exports, _ = ccsw.activate_tool_for_subprocess(
                    store,
                    "openclaw",
                    "rescued",
                    persist_state=True,
                )

                self.assertEqual(
                    exports["OPENCLAW_CONFIG_PATH"],
                    str(generated_dir / "openclaw" / "rescued.json5"),
                )
                self.assertEqual(exports["OPENCLAW_PROFILE"], "blue-team")
                with patch("ccsw._generic_url_probe", return_value=("ok", {"reason_code": "reachable"})):
                    status, detail = ccsw._probe_tool_health(
                        store,
                        "openclaw",
                        "rescued",
                        store["providers"]["rescued"]["openclaw"],
                    )

        self.assertEqual(status, "degraded")
        self.assertEqual(detail["reason_code"], "store_literal_secret")
        self.assertEqual(detail["live_provider_id"], "demo-provider")
        self.assertEqual(detail["live_api"], "responses")
        self.assertEqual(detail["live_model"], "claude-sonnet-4")
        self.assertEqual(detail["live_profile"], "blue-team")

    def test_doctor_openclaw_reads_profile_from_config_dir_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "openclaw-home"
            config_dir.mkdir(parents=True)
            (config_dir / ".env").write_text("OPENCLAW_PROFILE=blue-team\n", encoding="utf-8")
            overlay_path = root / "generated" / "openclaw" / "rescued.json5"
            overlay_path.parent.mkdir(parents=True)
            overlay_path.write_text(
                json.dumps(
                    {
                        "models": {
                            "providers": {
                                "demo-provider": {
                                    "baseUrl": "https://relay.example.com/v1",
                                    "apiKey": "overlay-token",
                                    "api": "responses",
                                }
                            }
                        },
                        "agents": {"defaults": {"model": {"primary": "claude-sonnet-4"}}},
                    }
                ),
                encoding="utf-8",
            )
            env_path = root / "openclaw.env"
            env_path.write_text(
                f"export OPENCLAW_CONFIG_PATH='{overlay_path}'\n",
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "rescued": {
                        "openclaw": {
                            "provider_id": "demo-provider",
                            "base_url": "https://relay.example.com/v1",
                            "token": "overlay-token",
                            "api": "responses",
                            "profile": "blue-team",
                            "model": "claude-sonnet-4",
                        }
                    }
                },
                "profiles": {},
                "settings": {"openclaw_config_dir": str(config_dir)},
            }

            with patch.object(ccsw, "GENERATED_DIR", root / "generated"), patch.object(
                ccsw, "OPENCLAW_ENV_PATH", env_path
            ), patch(
                "ccsw._generic_url_probe", return_value=("ok", {"reason_code": "reachable"})
            ), patch.dict(os.environ, {}, clear=True):
                status, detail = ccsw._probe_tool_health(
                    store,
                    "openclaw",
                    "rescued",
                    store["providers"]["rescued"]["openclaw"],
                )

        self.assertEqual(status, "degraded")
        self.assertEqual(detail["live_profile"], "blue-team")
        self.assertEqual(detail["reason_code"], "store_literal_secret")

    def test_import_current_opencode_reads_auth_from_config_dir_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "opencode-home"
            config_dir.mkdir(parents=True)
            (config_dir / "opencode.json").write_text(
                json.dumps(
                    {
                        "provider": {
                            "demo-provider": {
                                "options": {
                                    "baseURL": "https://relay.example.com/v1",
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            (config_dir / "auth.json").write_text(
                json.dumps({"apiKey": "override-token"}),
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"opencode_config_dir": str(config_dir)},
            }

            with patch("ccsw.save_store"):
                ccsw.cmd_import_current(store, "opencode", "rescued", allow_literal_secrets=True)

        imported = store["providers"]["rescued"]["opencode"]
        self.assertEqual(imported["base_url"], "https://relay.example.com/v1")
        self.assertEqual(imported["token"], "override-token")

    def test_import_current_opencode_falls_back_when_activation_overlay_is_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay_path = root / "active-opencode.json"
            overlay_path.write_text(
                json.dumps(
                    {
                        "provider": {
                            "demo-provider": {
                                "options": {
                                    "apiKey": "overlay-token",
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            config_dir = root / "opencode-home"
            config_dir.mkdir(parents=True)
            (config_dir / "opencode.json").write_text(
                json.dumps(
                    {
                        "provider": {
                            "demo-provider": {
                                "options": {
                                    "baseURL": "https://relay.example.com/v1",
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            (config_dir / "auth.json").write_text(
                json.dumps({"apiKey": "config-token"}),
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"opencode_config_dir": str(config_dir)},
            }

            with patch.dict(os.environ, {"OPENCODE_CONFIG": str(overlay_path)}, clear=False), patch(
                "ccsw.save_store"
            ):
                ccsw.cmd_import_current(store, "opencode", "rescued", allow_literal_secrets=True)

        imported = store["providers"]["rescued"]["opencode"]
        self.assertEqual(imported["provider_id"], "demo-provider")
        self.assertEqual(imported["base_url"], "https://relay.example.com/v1")
        self.assertEqual(imported["token"], "config-token")

    def test_import_current_opencode_reads_auth_from_default_xdg_data_home(self) -> None:
        with isolated_runtime_env(clear=True) as env:
            opencode_config_dir = env["xdg_config"] / "opencode"
            opencode_data_dir = env["xdg_data"] / "opencode"
            opencode_config_dir.mkdir(parents=True)
            opencode_data_dir.mkdir(parents=True)
            (opencode_config_dir / "opencode.json").write_text(
                json.dumps(
                    {
                        "provider": {
                            "demo-provider": {
                                "options": {
                                    "baseURL": "https://relay.example.com/v1",
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            (opencode_data_dir / "auth.json").write_text(
                json.dumps({"apiKey": "xdg-token"}),
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {},
            }

            with patch("ccsw.save_store"):
                ccsw.cmd_import_current(store, "opencode", "rescued", allow_literal_secrets=True)

        imported = store["providers"]["rescued"]["opencode"]
        self.assertEqual(imported["base_url"], "https://relay.example.com/v1")
        self.assertEqual(imported["token"], "xdg-token")

    def test_import_current_openclaw_fails_closed_on_ambiguous_overlay_even_with_valid_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay_path = root / "active-openclaw.json5"
            overlay_path.write_text(
                json.dumps(
                    {
                        "models": {
                            "providers": {
                                "first": {"baseUrl": "https://first.example/v1", "apiKey": "one"},
                                "second": {"baseUrl": "https://second.example/v1", "apiKey": "two"},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            config_dir = root / "openclaw-home"
            config_dir.mkdir(parents=True)
            (config_dir / "openclaw.json").write_text(
                json.dumps(
                    {
                        "models": {
                            "providers": {
                                "rescued-provider": {
                                    "baseUrl": "https://relay.example.com/v1",
                                    "apiKey": "config-token",
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"openclaw_config_dir": str(config_dir)},
            }

            with patch.dict(os.environ, {"OPENCLAW_CONFIG_PATH": str(overlay_path)}, clear=False), patch(
                "ccsw.save_store"
            ) as save_store:
                with self.assertRaises(SystemExit):
                    ccsw.cmd_import_current(store, "openclaw", "rescued", allow_literal_secrets=True)

        save_store.assert_not_called()
        self.assertNotIn("rescued", store["providers"])

    def test_switch_openclaw_without_profile_clears_shell_profile_env(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {
                "demo": {
                    "openclaw": {
                        "base_url": "https://relay.example.com/v1",
                        "token": "demo-token",
                    }
                }
            },
            "profiles": {},
            "settings": {},
        }

        with patch("ccsw.save_store"), patch("ccsw.emit_env") as emit_env, patch("ccsw.emit_unset") as emit_unset:
            ccsw.switch_tool(store, "openclaw", "demo")

        emit_env.assert_any_call("OPENCLAW_CONFIG_PATH", str(ccsw._generated_dir() / "openclaw" / "demo.json5"))
        emit_unset.assert_any_call("OPENCLAW_PROFILE")

    def test_rollback_records_target_validation_and_post_restore_validation_separately(self) -> None:
        store = {
            "version": 2,
            "active": {"claude": None, "codex": "current-live", "gemini": None, "opencode": None, "openclaw": None},
            "aliases": {},
            "providers": {
                "valid-provider": {
                    "codex": {"base_url": "https://valid.example/v1", "token": "token"}
                },
                "current-live": {
                    "codex": {"base_url": "https://current.example/v1", "token": "current-token"}
                },
            },
            "profiles": {},
            "settings": {},
        }
        entries = [
            {
                "recorded_at": "2026-04-13T19:00:00",
                "action": "switch",
                "tool": "codex",
                "subject": "current-live",
                "payload": {"previous": "valid-provider", "current": "current-live"},
            },
        ]

        with patch("ccsw.list_history", return_value=entries), patch(
            "ccsw._safe_local_restore_validation",
            side_effect=[
                {"status": "ok", "reason_code": "ready"},
                {"status": "failed", "reason_code": "validation_error"},
                {"status": "ok", "reason_code": "ready"},
            ],
        ), patch("ccsw.activate_tool_for_subprocess", return_value=({}, [])), patch(
            "ccsw._activation_target_paths",
            return_value=[],
        ), patch("ccsw.record_history") as record_history:
            with self.assertRaises(SystemExit):
                ccsw.cmd_rollback(store, "codex")

        payload = record_history.call_args.args[3]
        self.assertEqual(payload["rollback_status"], "restore_failed")
        self.assertEqual(payload["target_validation"]["status"], "failed")
        self.assertEqual(payload["post_restore_validation"]["status"], "ok")

    def test_doctor_codex_keeps_generic_checks_alongside_probe_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex_dir = Path(tmp) / ".codex"
            codex_dir.mkdir()
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example/v1",
                            "token": ccsw.env_ref("DEMO_CODEX_TOKEN"),
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch.dict(os.environ, {"DEMO_CODEX_TOKEN": "demo-token"}, clear=False), patch(
                "ccsw._probe_codex_target",
                return_value=(
                    "ok",
                    {
                        "reason_code": "models_ready",
                        "checks": {
                            "selected_models_probe": {
                                "status": "ok",
                                "reason_code": "models_ready",
                            }
                        },
                        "mismatch_fields": [],
                    },
                ),
            ):
                status, detail = ccsw._probe_tool_health(
                    store,
                    "codex",
                    "demo",
                    store["providers"]["demo"]["codex"],
                )

        self.assertEqual(status, "ok")
        self.assertIn("path_check", detail["checks"])
        self.assertIn("runtime_lease_check", detail["checks"])
        self.assertIn("store_secret_policy_check", detail["checks"])
        self.assertIn("selected_models_probe", detail["checks"])

    def test_doctor_codex_keeps_auth_error_over_runtime_lease_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex_dir = Path(tmp) / ".codex"
            codex_dir.mkdir()
            store = {
                "version": 2,
                "_revision": 1,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example/v1",
                            "token": ccsw.env_ref("DEMO_CODEX_TOKEN"),
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch.dict(os.environ, {"DEMO_CODEX_TOKEN": "demo-token"}, clear=False), patch(
                "ccsw._probe_codex_target",
                return_value=(
                    "failed",
                    {
                        "reason_code": "auth_error",
                        "checks": {
                            "selected_models_probe": {
                                "status": "failed",
                                "reason_code": "auth_error",
                            }
                        },
                        "mismatch_fields": [],
                    },
                ),
            ), patch(
                "ccsw._runtime_lease_check",
                return_value=("degraded", {"status": "degraded", "reason_code": "stale_lease"}),
            ):
                status, detail = ccsw._probe_tool_health(
                    store,
                    "codex",
                    "demo",
                    store["providers"]["demo"]["codex"],
                )

        self.assertEqual(status, "failed")
        self.assertEqual(detail["reason_code"], "auth_error")
        self.assertEqual(detail["checks"]["runtime_lease_check"]["reason_code"], "stale_lease")

    def test_doctor_codex_keeps_config_mismatch_over_runtime_lease_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex_dir = Path(tmp) / ".codex"
            codex_dir.mkdir()
            store = {
                "version": 2,
                "_revision": 1,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example/v1",
                            "token": ccsw.env_ref("DEMO_CODEX_TOKEN"),
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch.dict(os.environ, {"DEMO_CODEX_TOKEN": "demo-token"}, clear=False), patch(
                "ccsw._probe_codex_target",
                return_value=(
                    "degraded",
                    {
                        "reason_code": "config_mismatch",
                        "checks": {
                            "selected_models_probe": {
                                "status": "ok",
                                "reason_code": "models_ready",
                            }
                        },
                        "mismatch_fields": ["provider_base_url"],
                    },
                ),
            ), patch(
                "ccsw._runtime_lease_check",
                return_value=("degraded", {"status": "degraded", "reason_code": "runtime_busy"}),
            ):
                status, detail = ccsw._probe_tool_health(
                    store,
                    "codex",
                    "demo",
                    store["providers"]["demo"]["codex"],
                )

        self.assertEqual(status, "degraded")
        self.assertEqual(detail["reason_code"], "config_mismatch")
        self.assertEqual(detail["checks"]["runtime_lease_check"]["reason_code"], "runtime_busy")

    def test_rollback_skips_missing_provider_and_restores_next_valid_target(self) -> None:
        store = {
            "version": 2,
            "active": {"claude": None, "codex": "current", "gemini": None, "opencode": None, "openclaw": None},
            "aliases": {},
            "providers": {
                "valid-provider": {
                    "codex": {"base_url": "https://valid.example/v1", "token": "token"}
                }
            },
            "profiles": {},
            "settings": {},
        }

        entries = [
            {
                "recorded_at": "2026-04-13T20:00:00",
                "action": "switch",
                "tool": "codex",
                "subject": "current",
                "payload": {"previous": "missing-provider", "current": "current"},
            },
            {
                "recorded_at": "2026-04-13T19:00:00",
                "action": "switch",
                "tool": "codex",
                "subject": "current",
                "payload": {"previous": "valid-provider", "current": "current"},
            },
        ]

        with patch("ccsw.list_history", return_value=entries), patch(
            "ccsw._safe_local_restore_validation",
            side_effect=[
                {"status": "ok", "reason_code": "ready"},
                {"status": "ok", "reason_code": "ready"},
            ],
        ), patch("ccsw.activate_tool_for_subprocess", return_value=({}, [])) as activate, patch(
            "ccsw._activation_target_paths",
            return_value=[],
        ), patch("ccsw.save_store"):
            ccsw.cmd_rollback(store, "codex")

        activate.assert_called_once()

    def test_rollback_skips_entries_when_current_does_not_match_active(self) -> None:
        store = {
            "version": 2,
            "active": {"claude": None, "codex": "current-live", "gemini": None, "opencode": None, "openclaw": None},
            "aliases": {},
            "providers": {
                "valid-provider": {
                    "codex": {"base_url": "https://valid.example/v1", "token": "token"}
                }
            },
            "profiles": {},
            "settings": {},
        }
        entries = [
            {
                "recorded_at": "2026-04-13T20:00:00",
                "action": "switch",
                "tool": "codex",
                "subject": "other-current",
                "payload": {"previous": "valid-provider", "current": "other-current"},
            },
            {
                "recorded_at": "2026-04-13T19:00:00",
                "action": "switch",
                "tool": "codex",
                "subject": "current-live",
                "payload": {"previous": "valid-provider", "current": "current-live"},
            },
        ]

        with patch("ccsw.list_history", return_value=entries), patch(
            "ccsw._safe_local_restore_validation",
            side_effect=[
                {"status": "ok", "reason_code": "ready"},
                {"status": "ok", "reason_code": "ready"},
            ],
        ), patch("ccsw.activate_tool_for_subprocess", return_value=({}, [])) as activate, patch(
            "ccsw._activation_target_paths",
            return_value=[],
        ), patch("ccsw.save_store"):
            ccsw.cmd_rollback(store, "codex")

        activate.assert_called_once()

    def test_rollback_errors_when_target_activation_fails(self) -> None:
        store = {
            "version": 2,
            "active": {"claude": None, "codex": "current-live", "gemini": None, "opencode": None, "openclaw": None},
            "aliases": {},
            "providers": {
                "valid-provider": {
                    "codex": {"base_url": "https://valid.example/v1", "token": "token"}
                }
            },
            "profiles": {},
            "settings": {},
        }
        entries = [
            {
                "recorded_at": "2026-04-13T19:00:00",
                "action": "switch",
                "tool": "codex",
                "subject": "current-live",
                "payload": {"previous": "valid-provider", "current": "current-live"},
            },
        ]

        with patch("ccsw.list_history", return_value=entries), patch(
            "ccsw._safe_local_restore_validation",
            return_value={"status": "ok", "reason_code": "ready"},
        ), patch("ccsw.activate_tool_for_subprocess", side_effect=SystemExit(1)), patch(
            "ccsw._activation_target_paths",
            return_value=[],
        ):
            with self.assertRaises(SystemExit):
                ccsw.cmd_rollback(store, "codex")

    def test_rollback_restores_snapshot_when_activation_partially_writes_before_failing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir()
            auth_path = codex_dir / "auth.json"
            config_path = codex_dir / "config.toml"
            auth_path.write_text(json.dumps({"OPENAI_API_KEY": "original"}), encoding="utf-8")
            config_path.write_text('model = "gpt-5.4"\n', encoding="utf-8")
            store = {
                "version": 2,
                "active": {"claude": None, "codex": "current-live", "gemini": None, "opencode": None, "openclaw": None},
                "aliases": {},
                "providers": {
                    "valid-provider": {
                        "codex": {"base_url": "https://valid.example/v1", "token": "token"}
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }
            entries = [
                {
                    "recorded_at": "2026-04-13T19:00:00",
                    "action": "switch",
                    "tool": "codex",
                    "subject": "current-live",
                    "payload": {"previous": "valid-provider", "current": "current-live"},
                },
            ]

            def _partial_write(*_args, **_kwargs):
                auth_path.write_text(json.dumps({"OPENAI_API_KEY": "corrupted"}), encoding="utf-8")
                return None

            with patch("ccsw.list_history", return_value=entries), patch(
                "ccsw._safe_local_restore_validation",
                return_value={"status": "ok", "reason_code": "ready"},
            ), patch("ccsw.write_codex", side_effect=_partial_write):
                with self.assertRaises(SystemExit):
                    ccsw.cmd_rollback(store, "codex")

            restored = json.loads(auth_path.read_text(encoding="utf-8"))
            self.assertEqual(restored["OPENAI_API_KEY"], "original")

    def test_rollback_errors_when_writer_returns_no_exports(self) -> None:
        store = {
            "version": 2,
            "active": {"claude": None, "codex": None, "gemini": None, "opencode": None, "openclaw": "current-live"},
            "aliases": {},
            "providers": {
                "rescued": {
                    "openclaw": {
                        "base_url": "https://relay.example.com/v1",
                        "token": "demo-token",
                    }
                }
            },
            "profiles": {},
            "settings": {},
        }
        entries = [
            {
                "recorded_at": "2026-04-13T19:00:00",
                "action": "switch",
                "tool": "openclaw",
                "subject": "current-live",
                "payload": {"previous": "rescued", "current": "current-live"},
            },
        ]

        with patch("ccsw.list_history", return_value=entries), patch(
            "ccsw._safe_local_restore_validation",
            return_value={"status": "ok", "reason_code": "ready"},
        ), patch(
            "ccsw.write_openclaw",
            return_value=None,
        ), patch("ccsw.save_store") as save_store, patch("ccsw.record_history") as record_history, patch(
            "ccsw.info"
        ) as info, patch(
            "ccsw._activation_target_paths",
            return_value=[],
        ), patch(
            "ccsw.emit_env"
        ), patch(
            "ccsw.emit_unset"
        ):
            with self.assertRaises(SystemExit):
                ccsw.cmd_rollback(store, "openclaw")

        save_store.assert_not_called()
        payload = record_history.call_args.args[3]
        self.assertEqual(payload["rollback_status"], "restore_failed")
        self.assertEqual(store["active"]["openclaw"], "current-live")
        messages = [call.args[0] for call in info.call_args_list if call.args]
        self.assertFalse(any("Restored openclaw" in message for message in messages))

    def test_rollback_errors_when_active_is_none(self) -> None:
        store = {
            "version": 2,
            "active": {"claude": None, "codex": None, "gemini": None, "opencode": None, "openclaw": None},
            "aliases": {},
            "providers": {
                "rescued": {
                    "openclaw": {
                        "base_url": "https://relay.example.com/v1",
                        "token": "demo-token",
                    }
                }
            },
            "profiles": {},
            "settings": {},
        }
        entries = [
            {
                "recorded_at": "2026-04-13T19:00:00",
                "action": "switch",
                "tool": "openclaw",
                "subject": "current-live",
                "payload": {"previous": "rescued", "current": "current-live"},
            },
        ]

        with patch("ccsw.list_history", return_value=entries), patch("ccsw.switch_tool") as switch_tool:
            with self.assertRaises(SystemExit):
                ccsw.cmd_rollback(store, "openclaw")

        switch_tool.assert_not_called()

    def test_generic_url_probe_marks_401_as_failed(self) -> None:
        http_error = HTTPError(
            url="https://example.com",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )

        with patch("ccsw.urllib_request.urlopen", side_effect=http_error):
            status, detail = ccsw._generic_url_probe("https://example.com")

        self.assertEqual(status, "failed")
        self.assertEqual(detail["status"], 401)

    def test_generic_url_probe_handles_http_error_without_readable_body(self) -> None:
        http_error = HTTPError(
            url="https://example.com",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )
        http_error.read = Mock(side_effect=KeyError("file"))

        with patch("ccsw.urllib_request.urlopen", side_effect=http_error):
            status, detail = ccsw._generic_url_probe("https://example.com")

        self.assertEqual(status, "failed")
        self.assertEqual(detail["status"], 401)
        self.assertNotIn("sample", detail)

    def test_list_history_filters_action_before_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.record_history("switch", "codex", "first", {"previous": None, "current": "first"})
                ccsw.record_history(
                    "run-attempt",
                    "codex",
                    "first",
                    {"returncode": 1, "failure_type": "retryable_upstream", "retryable": True},
                )
                ccsw.record_history("switch", "codex", "second", {"previous": "first", "current": "second"})

                entries = ccsw.list_history(limit=1, tool="codex", action="switch")

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["subject"], "second")
        self.assertEqual(entries[0]["action"], "switch")

    def test_cmd_history_failed_only_filters_before_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.record_history(
                    "run-attempt",
                    "codex",
                    "success-latest",
                    {"returncode": 0, "failure_type": "ok", "retryable": False},
                )
                ccsw.record_history(
                    "run-attempt",
                    "codex",
                    "failure-older",
                    {"returncode": 1, "failure_type": "retryable_upstream", "retryable": True},
                )
                with patch("ccsw.info") as info:
                    ccsw.cmd_history("codex", limit=1, failed_only=True)

        messages = [call.args[0] for call in info.call_args_list if call.args]
        self.assertTrue(any("failure-older" in message for message in messages))

    def test_cmd_history_failed_only_does_not_leak_other_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.record_history(
                    "run-attempt",
                    "gemini",
                    "gemini-failure",
                    {"returncode": 1, "failure_type": "retryable_upstream", "retryable": True},
                )
                with patch("ccsw.info") as info:
                    ccsw.cmd_history("codex", limit=10, failed_only=True)

        messages = [call.args[0] for call in info.call_args_list if call.args]
        self.assertTrue(any("No history found." in message for message in messages))

    def test_cmd_history_failed_only_includes_run_result_without_failure_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.record_history(
                    "run-result",
                    "codex",
                    "codex-failure",
                    {
                        "returncode": 1,
                        "selected_candidate": "codex-failure",
                        "final_failure_type": "lease_blocked",
                        "restore_status": "not_run",
                        "cleanup_status": "not_run",
                    },
                )
                with patch("ccsw.info") as info:
                    ccsw.cmd_history("codex", limit=10, failed_only=True)

        messages = [call.args[0] for call in info.call_args_list if call.args]
        rendered = "\n".join(messages)
        self.assertIn("codex-failure", rendered)
        self.assertIn("lease_blocked", rendered)
        self.assertIn("restore_status=not_run", rendered)
        self.assertIn("cleanup_status=not_run", rendered)

    def test_probe_overlay_activation_treats_symlink_as_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = root / "generated" / "opencode" / "demo.json"
            expected.parent.mkdir(parents=True)
            expected.write_text("{}", encoding="utf-8")
            linked_dir = root / "links"
            linked_dir.mkdir()
            symlink_path = linked_dir / "demo.json"
            symlink_path.symlink_to(expected)
            env_path = root / "opencode.env"
            env_path.write_text(f"export OPENCODE_CONFIG='{symlink_path}'\n", encoding="utf-8")

            with patch.object(ccsw, "GENERATED_DIR", root / "generated"), patch.object(
                ccsw, "OPENCODE_ENV_PATH", env_path
            ):
                status, detail = ccsw._probe_overlay_activation("opencode", "demo")

        self.assertEqual(status, "ok")
        self.assertTrue(detail["active_overlay_matches"])

    def test_doctor_claude_detects_live_settings_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claude_dir = root / ".claude"
            claude_dir.mkdir()
            (claude_dir / "settings.json").write_text(
                json.dumps(
                    {
                        "env": {
                            "ANTHROPIC_AUTH_TOKEN": "wrong-token",
                            "ANTHROPIC_BASE_URL": "https://wrong.example",
                        }
                    }
                ),
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "demo": {
                        "claude": {
                            "base_url": "https://expected.example",
                            "token": "expected-token",
                            "extra_env": {},
                        }
                    }
                },
                "profiles": {},
                "settings": {"claude_config_dir": str(claude_dir)},
            }

            status, detail = ccsw._probe_tool_health(
                store,
                "claude",
                "demo",
                store["providers"]["demo"]["claude"],
            )

        self.assertEqual(status, "degraded")
        self.assertEqual(detail["reason_code"], "live_config_mismatch")

    def test_doctor_opencode_detects_overlay_content_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            overlay_path = generated_dir / "opencode" / "demo.json"
            overlay_path.parent.mkdir(parents=True)
            overlay_path.write_text(
                json.dumps(
                    {
                        "provider": {
                            "demo-provider": {
                                "options": {
                                    "baseURL": "https://wrong.example/v1",
                                    "apiKey": "wrong-token",
                                }
                            }
                        },
                        "model": "gpt-4.1",
                    }
                ),
                encoding="utf-8",
            )
            env_path = root / "opencode.env"
            env_path.write_text(f"export OPENCODE_CONFIG='{overlay_path}'\n", encoding="utf-8")
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "demo": {
                        "opencode": {
                            "base_url": "https://expected.example/v1",
                            "token": "expected-token",
                            "provider_id": "demo-provider",
                            "model": "gpt-5.4",
                        }
                    }
                },
                "profiles": {},
                "settings": {},
            }

            with patch.object(ccsw, "GENERATED_DIR", generated_dir), patch.object(
                ccsw, "OPENCODE_ENV_PATH", env_path
            ), patch("ccsw._generic_url_probe", return_value=("ok", {"reason_code": "reachable"})):
                status, detail = ccsw._probe_tool_health(
                    store,
                    "opencode",
                    "demo",
                    store["providers"]["demo"]["opencode"],
                )

        self.assertEqual(status, "degraded")
        self.assertEqual(detail["reason_code"], "live_config_mismatch")

    def test_doctor_opencode_detects_npm_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            overlay_path = generated_dir / "opencode" / "demo.json"
            overlay_path.parent.mkdir(parents=True)
            overlay_path.write_text(
                json.dumps(
                    {
                        "provider": {
                            "demo-provider": {
                                "npm": "@ai-sdk/wrong",
                                "options": {
                                    "baseURL": "https://expected.example/v1",
                                    "apiKey": "expected-token",
                                },
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            env_path = root / "opencode.env"
            env_path.write_text(f"export OPENCODE_CONFIG='{overlay_path}'\n", encoding="utf-8")
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "demo": {
                        "opencode": {
                            "base_url": "https://expected.example/v1",
                            "token": "expected-token",
                            "provider_id": "demo-provider",
                            "npm": "@ai-sdk/expected",
                        }
                    }
                },
                "profiles": {},
                "settings": {},
            }

            with patch.object(ccsw, "GENERATED_DIR", generated_dir), patch.object(
                ccsw, "OPENCODE_ENV_PATH", env_path
            ), patch("ccsw._generic_url_probe", return_value=("ok", {"reason_code": "reachable"})):
                status, detail = ccsw._probe_tool_health(
                    store,
                    "opencode",
                    "demo",
                    store["providers"]["demo"]["opencode"],
                )

        self.assertEqual(status, "degraded")
        self.assertIn("npm", detail["mismatch_fields"])

    def test_doctor_openclaw_detects_profile_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            overlay_path = generated_dir / "openclaw" / "demo.json5"
            overlay_path.parent.mkdir(parents=True)
            overlay_path.write_text(
                json.dumps(
                    {
                        "models": {
                            "providers": {
                                "demo-provider": {
                                    "baseUrl": "https://expected.example/v1",
                                    "apiKey": "expected-token",
                                    "api": "responses",
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            env_path = root / "openclaw.env"
            env_path.write_text(
                "\n".join(
                    [
                        f"export OPENCLAW_CONFIG_PATH='{overlay_path}'",
                        "export OPENCLAW_PROFILE='wrong-team'",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "demo": {
                        "openclaw": {
                            "base_url": "https://expected.example/v1",
                            "token": "expected-token",
                            "provider_id": "demo-provider",
                            "api": "responses",
                            "profile": "blue-team",
                        }
                    }
                },
                "profiles": {},
                "settings": {"openclaw_config_dir": str(root)},
            }

            with patch.object(ccsw, "GENERATED_DIR", generated_dir), patch.object(
                ccsw, "OPENCLAW_ENV_PATH", env_path
            ), patch("ccsw._generic_url_probe", return_value=("ok", {"reason_code": "reachable"})):
                status, detail = ccsw._probe_tool_health(
                    store,
                    "openclaw",
                    "demo",
                    store["providers"]["demo"]["openclaw"],
                )

        self.assertEqual(status, "degraded")
        self.assertIn("profile", detail["mismatch_fields"])

    def test_doctor_overlay_missing_keeps_activation_reason(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {
                "demo": {
                    "opencode": {
                        "base_url": "https://expected.example/v1",
                        "token": "expected-token",
                        "provider_id": "demo-provider",
                    }
                }
            },
            "profiles": {},
            "settings": {},
        }

        with patch("ccsw._generic_url_probe", return_value=("ok", {"reason_code": "reachable"})), patch(
            "ccsw._probe_overlay_activation",
            return_value=("failed", {"reason_code": "overlay_missing", "active_overlay": None}),
        ), patch("ccsw._probe_overlay_content") as probe_content:
            status, detail = ccsw._probe_tool_health(
                store,
                "opencode",
                "demo",
                store["providers"]["demo"]["opencode"],
            )

        probe_content.assert_not_called()
        self.assertEqual(status, "failed")
        self.assertEqual(detail["reason_code"], "overlay_missing")

    def test_doctor_reports_windows_style_config_dir_on_wsl(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {
                "demo": {
                    "opencode": {
                        "base_url": "https://expected.example/v1",
                        "token": "expected-token",
                        "provider_id": "demo-provider",
                    }
                }
            },
            "profiles": {},
            "settings": {"opencode_config_dir": r"C:\\Users\\demo\\AppData\\Roaming\\OpenCode"},
        }

        with patch("ccsw._is_wsl", return_value=True), patch(
            "ccsw._generic_url_probe",
            return_value=("ok", {"reason_code": "reachable"}),
        ), patch(
            "ccsw._probe_overlay_activation",
            return_value=("ok", {"reason_code": "overlay_ready", "active_overlay": "/tmp/demo.json"}),
        ), patch(
            "ccsw._probe_overlay_content",
            return_value=("ok", {"reason_code": "overlay_content_ready"}),
        ):
            status, detail = ccsw._probe_tool_health(
                store,
                "opencode",
                "demo",
                store["providers"]["demo"]["opencode"],
            )

        self.assertEqual(status, "degraded")
        self.assertEqual(
            detail["checks"]["config_dir_input_check"]["reason_code"],
            "windows_style_path_on_wsl",
        )

    def test_rollback_ignores_run_noise_beyond_limit_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {"claude": None, "codex": "latest", "gemini": None, "opencode": None, "openclaw": None},
                "aliases": {},
                "providers": {
                    "stable": {
                        "codex": {"base_url": "https://stable.example/v1", "token": "token"}
                    }
                },
                "profiles": {},
                "settings": {},
            }

        with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
            ccsw, "DB_PATH", db_path
        ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
            ccsw.save_store(store)
            ccsw.record_history("switch", "codex", "latest", {"previous": "stable", "current": "latest"})
            for index in range(60):
                ccsw.record_history(
                    "run-attempt",
                    "codex",
                    f"noise-{index}",
                    {
                        "returncode": 1,
                        "failure_type": "retryable_upstream",
                        "retryable": True,
                    },
                )

            with patch(
                "ccsw._safe_local_restore_validation",
                side_effect=[
                    {"status": "ok", "reason_code": "ready"},
                    {"status": "ok", "reason_code": "ready"},
                ],
            ), patch("ccsw.activate_tool_for_subprocess", return_value=({}, [])) as activate, patch(
                "ccsw._activation_target_paths",
                return_value=[],
            ), patch("ccsw.save_store"):
                ccsw.cmd_rollback(store, "codex")

        activate.assert_called_once()


class SecretAndBatchBehaviorTests(unittest.TestCase):
    def test_cmd_add_rejects_literal_secret_flags_by_default(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {},
            "profiles": {},
            "settings": {},
        }
        args = Namespace(
            claude_url="https://example.com",
            claude_token="literal-secret",
            codex_url=None,
            codex_fallback_url=None,
            codex_token=None,
            gemini_key=None,
            gemini_auth_type=None,
            opencode_url=None,
            opencode_token=None,
            opencode_model=None,
            openclaw_url=None,
            openclaw_token=None,
            openclaw_model=None,
            allow_literal_secrets=False,
        )

        with self.assertRaises(SystemExit):
            ccsw.cmd_add(store, "demo", args)

    def test_cmd_add_accepts_codex_chatgpt_auth_mode_without_secret(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {},
            "profiles": {},
            "settings": {},
        }
        args = Namespace(
            claude_url=None,
            claude_token=None,
            codex_url=None,
            codex_fallback_url=None,
            codex_token=None,
            codex_auth_mode="chatgpt",
            gemini_key=None,
            gemini_auth_type=None,
            opencode_url=None,
            opencode_token=None,
            opencode_model=None,
            openclaw_url=None,
            openclaw_token=None,
            openclaw_model=None,
            allow_literal_secrets=False,
        )

        with patch("ccsw.save_store"):
            ccsw.cmd_add(store, "pro", args)

        self.assertEqual(
            store["providers"]["pro"]["codex"],
            {"auth_mode": "chatgpt"},
        )

    def test_import_current_rejects_literal_secret_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            (codex_dir / "auth.json").write_text(
                json.dumps({"OPENAI_API_KEY": "demo-token"}),
                encoding="utf-8",
            )
            (codex_dir / "config.toml").write_text(
                "\n".join(
                    [
                        'model_provider = "ccswitch_active"',
                        "[model_providers.ccswitch_active]",
                        'base_url = "https://correct.example/v1"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with self.assertRaises(SystemExit):
                ccsw.cmd_import_current(store, "codex", "imported")

    def test_import_current_preserves_existing_env_ref_when_live_secret_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            (codex_dir / "auth.json").write_text(
                json.dumps({"OPENAI_API_KEY": "demo-token"}),
                encoding="utf-8",
            )
            (codex_dir / "config.toml").write_text(
                "\n".join(
                    [
                        'model_provider = "ccswitch_active"',
                        "[model_providers.ccswitch_active]",
                        'base_url = "https://correct.example/v1"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "imported": {
                        "codex": {
                            "token": "$MATCHING_CODEX_TOKEN",
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }
            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.save_store(store)
                with patch.dict(os.environ, {"MATCHING_CODEX_TOKEN": "demo-token"}, clear=False):
                    ccsw.cmd_import_current(store, "codex", "imported")
                reloaded = ccsw.load_store()

        self.assertEqual(reloaded["providers"]["imported"]["codex"]["token"], "$MATCHING_CODEX_TOKEN")

    def test_import_current_opencode_preserves_existing_env_ref_when_live_secret_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay_path = root / "active-opencode.json"
            overlay_path.write_text(
                json.dumps(
                    {
                        "provider": {
                            "demo-provider": {
                                "options": {
                                    "baseURL": "https://relay.example.com/v1",
                                    "apiKey": "demo-token",
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "imported": {
                        "opencode": {
                            "token": "$MATCHING_OPENCODE_TOKEN",
                        }
                    }
                },
                "profiles": {},
                "settings": {},
            }

            with patch.dict(
                os.environ,
                {
                    "OPENCODE_CONFIG": str(overlay_path),
                    "MATCHING_OPENCODE_TOKEN": "demo-token",
                },
                clear=False,
            ), patch("ccsw.save_store"):
                ccsw.cmd_import_current(store, "opencode", "imported")

        self.assertEqual(store["providers"]["imported"]["opencode"]["token"], "$MATCHING_OPENCODE_TOKEN")

    def test_import_current_openclaw_preserves_existing_env_ref_when_live_secret_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay_path = root / "active-openclaw.json5"
            overlay_path.write_text(
                json.dumps(
                    {
                        "models": {
                            "providers": {
                                "demo-provider": {
                                    "baseUrl": "https://relay.example.com/v1",
                                    "apiKey": "demo-token",
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "imported": {
                        "openclaw": {
                            "token": "$MATCHING_OPENCLAW_TOKEN",
                        }
                    }
                },
                "profiles": {},
                "settings": {},
            }

            with patch.dict(
                os.environ,
                {
                    "OPENCLAW_CONFIG_PATH": str(overlay_path),
                    "MATCHING_OPENCLAW_TOKEN": "demo-token",
                },
                clear=False,
            ), patch("ccsw.save_store"):
                ccsw.cmd_import_current(store, "openclaw", "imported")

        self.assertEqual(store["providers"]["imported"]["openclaw"]["token"], "$MATCHING_OPENCLAW_TOKEN")

    def test_import_current_gemini_preserves_existing_env_ref_when_live_secret_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gemini_dir = root / ".gemini"
            gemini_dir.mkdir(parents=True)
            (gemini_dir / "settings.json").write_text(
                json.dumps({"security": {"auth": {"selectedType": "api-key"}}}),
                encoding="utf-8",
            )
            active_env_path = root / ".ccswitch" / "active.env"
            active_env_path.parent.mkdir(parents=True)
            active_env_path.write_text(
                "export GEMINI_API_KEY='demo-token'\n",
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "imported": {
                        "gemini": {
                            "api_key": "$MATCHING_GEMINI_TOKEN",
                        }
                    }
                },
                "profiles": {},
                "settings": {"gemini_config_dir": str(gemini_dir)},
            }

            with patch.object(ccsw, "ACTIVE_ENV_PATH", active_env_path), patch.dict(
                os.environ,
                {"MATCHING_GEMINI_TOKEN": "demo-token"},
                clear=False,
            ), patch("ccsw.save_store"):
                ccsw.cmd_import_current(store, "gemini", "imported")

        self.assertEqual(store["providers"]["imported"]["gemini"]["api_key"], "$MATCHING_GEMINI_TOKEN")

    def test_import_current_gemini_does_not_preserve_mismatched_env_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gemini_dir = root / ".gemini"
            gemini_dir.mkdir(parents=True)
            (gemini_dir / "settings.json").write_text(
                json.dumps({"security": {"auth": {"selectedType": "api-key"}}}),
                encoding="utf-8",
            )
            active_env_path = root / ".ccswitch" / "active.env"
            active_env_path.parent.mkdir(parents=True)
            active_env_path.write_text(
                "export GEMINI_API_KEY='live-token'\n",
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "imported": {
                        "gemini": {
                            "api_key": "$MISMATCHED_GEMINI_TOKEN",
                        }
                    }
                },
                "profiles": {},
                "settings": {"gemini_config_dir": str(gemini_dir)},
            }

            with patch.object(ccsw, "ACTIVE_ENV_PATH", active_env_path), patch.dict(
                os.environ,
                {"MISMATCHED_GEMINI_TOKEN": "store-token"},
                clear=False,
            ):
                with self.assertRaises(SystemExit):
                    ccsw.cmd_import_current(store, "gemini", "imported")

    def test_import_current_gemini_clears_stale_auth_type_when_live_setting_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gemini_dir = root / ".gemini"
            gemini_dir.mkdir(parents=True)
            (gemini_dir / "settings.json").write_text(json.dumps({"security": {"auth": {}}}), encoding="utf-8")
            active_env_path = root / ".ccswitch" / "active.env"
            active_env_path.parent.mkdir(parents=True)
            active_env_path.write_text(
                "export GEMINI_API_KEY='demo-token'\n",
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "imported": {
                        "gemini": {
                            "api_key": "$MATCHING_GEMINI_TOKEN",
                            "auth_type": "oauth",
                        }
                    }
                },
                "profiles": {},
                "settings": {"gemini_config_dir": str(gemini_dir)},
            }

            with patch.object(ccsw, "ACTIVE_ENV_PATH", active_env_path), patch.dict(
                os.environ,
                {"MATCHING_GEMINI_TOKEN": "demo-token"},
                clear=False,
            ), patch("ccsw.save_store"):
                ccsw.cmd_import_current(store, "gemini", "imported")

        self.assertEqual(store["providers"]["imported"]["gemini"]["api_key"], "$MATCHING_GEMINI_TOKEN")
        self.assertNotIn("auth_type", store["providers"]["imported"]["gemini"])

    def test_write_opencode_rejects_non_allowlisted_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            env_path = root / "opencode.env"
            conf = {
                "base_url": "https://relay.example.com/v1",
                "token": "demo-token",
                "headers": {"x-session": "unsafe"},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "OPENCODE_ENV_PATH", env_path
            ), patch.object(ccsw, "GENERATED_DIR", generated_dir):
                with self.assertRaises(SystemExit):
                    ccsw.write_opencode(conf, "demo")

    def test_switch_all_preflights_before_any_write(self) -> None:
        store = {
            "version": 2,
            "active": {tool: None for tool in ccsw.ALL_TOOLS},
            "aliases": {},
            "providers": {
                "demo": {
                    "claude": {"base_url": "https://example.com", "token": "$CLAUDE_TOKEN", "extra_env": {}},
                    "codex": {"base_url": "https://example.com/v1", "token": "$MISSING_CODEX_TOKEN"},
                }
            },
            "profiles": {},
            "settings": {},
        }

        with patch.dict(os.environ, {"CLAUDE_TOKEN": "ok"}, clear=False), patch(
            "ccsw.switch_tool"
        ) as switch_tool:
            with self.assertRaises(SystemExit):
                ccsw.cmd_switch(store, "all", "demo")

        switch_tool.assert_not_called()

    def test_run_with_fallback_strips_all_profile_candidate_secret_envs_from_child(self) -> None:
        store = {
            "version": 2,
            "active": {
                "claude": None,
                "codex": "first",
                "gemini": None,
                "opencode": None,
                "openclaw": None,
            },
            "aliases": {},
            "providers": {
                "first": {"codex": {"base_url": "https://first.example/v1", "token": "$FIRST_TOKEN"}},
                "second": {"codex": {"base_url": "https://second.example/v1", "token": "$SECOND_TOKEN"}},
            },
            "profiles": {"work": {"codex": ["first", "second"]}},
            "settings": {},
        }
        captured_envs: list[dict[str, str]] = []

        def _run(*_args, **kwargs):
            captured_envs.append(dict(kwargs["env"]))
            if len(captured_envs) == 1:
                return subprocess.CompletedProcess(["codex", "exec", "hi"], 1, "", "connection refused")
            return subprocess.CompletedProcess(["codex", "exec", "hi"], 0, "ok", "")

        with patch.dict(
            os.environ,
            {"FIRST_TOKEN": "first-secret", "SECOND_TOKEN": "second-secret"},
            clear=False,
        ), patch(
            "ccsw.activate_tool_for_subprocess",
            side_effect=[
                ({"OPENAI_API_KEY": "resolved-first"}, ["OPENAI_BASE_URL"]),
                ({"OPENAI_API_KEY": "resolved-second"}, ["OPENAI_BASE_URL"]),
            ],
        ), patch(
            "ccsw._safe_local_restore_validation",
            return_value={"status": "ok", "reason_code": "ready"},
        ), patch("ccsw.subprocess.run", side_effect=_run):
            result = ccsw.run_with_fallback(store, "codex", "work", ["codex", "exec", "hi"])

        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(captured_envs), 2)
        for child_env in captured_envs:
            self.assertNotIn("FIRST_TOKEN", child_env)
            self.assertNotIn("SECOND_TOKEN", child_env)

    def test_history_failed_only_includes_failed_batch_even_when_rollback_restored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.record_history(
                    "batch-result",
                    None,
                    "demo",
                    {
                        "mode": "switch_all",
                        "failed_tool": "codex",
                        "rollback_status": "restored",
                        "restore_status": "restored",
                        "snapshot_sync": "ok",
                        "changed_tools": ["claude", "codex"],
                        "noop_tools": [],
                        "restored_tools": ["claude", "codex"],
                        "conflicted_tools": [],
                        "post_restore_validation": {"status": "ok", "reason_code": "ready"},
                        "restore_error": None,
                    },
                )
                entries = ccsw.list_history(limit=10, failed_only=True)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["action"], "batch-result")

    def test_cmd_run_redacts_sensitive_argv_in_history_and_verbose_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {"claude": None, "codex": "demo", "gemini": None, "opencode": None, "openclaw": None},
                "aliases": {},
                "providers": {"demo": {"codex": {"base_url": "https://relay.example/v1", "token": "demo-token"}}},
                "profiles": {},
                "settings": {},
            }
            result = subprocess.CompletedProcess(["curl"], 0, "ok\n", "")
            setattr(result, "_ccsw_selected_candidate", "demo")
            setattr(result, "_ccsw_fallback_used", False)
            setattr(result, "_ccsw_original_active", "demo")
            setattr(result, "_ccsw_attempt_count", 1)
            setattr(result, "_ccsw_source_kind", "provider")
            setattr(result, "_ccsw_final_failure_type", "ok")
            setattr(result, "_ccsw_restore_status", "restored")
            setattr(result, "_ccsw_restore_error", "Authorization: Bearer secret-token")
            setattr(result, "_ccsw_restore_conflicts", [])
            setattr(result, "_ccsw_post_restore_validation", {"status": "ok", "reason_code": "ready"})
            setattr(result, "_ccsw_backup_artifacts_cleaned", True)
            setattr(result, "_ccsw_temp_paths_cleaned", True)
            setattr(result, "_ccsw_cleanup_status", "cleaned")
            setattr(result, "_ccsw_lock_scope", "global_state_lock")

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch(
                "ccsw.run_with_fallback",
                return_value=result,
            ):
                ccsw.save_store(store)
                ccsw.cmd_run(
                    ccsw.load_store(),
                    "codex",
                    "demo",
                    [
                        "curl",
                        "-H",
                        "Authorization: Bearer secret-token",
                        "https://user:pass@example.com/v1?api_key=secret",
                    ],
                )
                history_entries = ccsw.list_history(limit=5, action="run-result")
                with patch("ccsw.info") as info:
                    ccsw.cmd_history("codex", limit=5, verbose=True)

        payload = history_entries[0]["payload"]
        argv_dump = " ".join(payload["argv"])
        self.assertNotIn("secret-token", argv_dump)
        self.assertNotIn("user:pass", argv_dump)
        self.assertNotIn("api_key=secret", argv_dump)
        self.assertNotIn("Bearer secret-token", payload["restore_error"])
        verbose_output = "\n".join(call.args[0] for call in info.call_args_list if call.args)
        self.assertNotIn("secret-token", verbose_output)
        self.assertNotIn("user:pass", verbose_output)

    def test_redact_sensitive_text_redacts_json_like_error_payloads(self) -> None:
        payload = (
            'upstream returned {"authorization":"Bearer secret-token","api_key":"abc123",'
            '"token":"xyz789","safe":"ok"}'
        )

        redacted = ccsw._redact_sensitive_text(payload)

        self.assertIn('"authorization":"<redacted>"', redacted)
        self.assertIn('"api_key":"<redacted>"', redacted)
        self.assertIn('"token":"<redacted>"', redacted)
        self.assertIn('"safe":"ok"', redacted)
        self.assertNotIn("secret-token", redacted)
        self.assertNotIn("abc123", redacted)
        self.assertNotIn("xyz789", redacted)

    def test_sanitize_history_payload_redacts_user_proxy_user_and_inline_header_args(self) -> None:
        payload = ccsw._sanitize_history_payload(
            "run-result",
            {
                "argv": [
                    "curl",
                    "--user",
                    "alice:secret-one",
                    "--proxy-user",
                    "bob:secret-two",
                    "--header=Authorization: Bearer secret-three",
                    "--header=x-api-key: secret-four",
                    "https://example.com",
                ]
            },
        )

        argv_dump = " ".join(payload["argv"])
        self.assertNotIn("secret-one", argv_dump)
        self.assertNotIn("secret-two", argv_dump)
        self.assertNotIn("secret-three", argv_dump)
        self.assertNotIn("secret-four", argv_dump)
        self.assertIn("--user", payload["argv"])
        self.assertIn("--proxy-user", payload["argv"])

    def test_sanitize_history_payload_redacts_compact_short_user_args(self) -> None:
        payload = ccsw._sanitize_history_payload(
            "run-result",
            {
                "argv": [
                    "curl",
                    "-ualice:secret-one",
                    "-u=bob:secret-two",
                    "https://example.com",
                ]
            },
        )

        argv_dump = " ".join(payload["argv"])
        self.assertNotIn("secret-one", argv_dump)
        self.assertNotIn("secret-two", argv_dump)
        self.assertIn("-u<redacted>", payload["argv"])
        self.assertIn("-u=<redacted>", payload["argv"])

    def test_sanitize_history_payload_redacts_sensitive_env_assignment_args(self) -> None:
        payload = ccsw._sanitize_history_payload(
            "run-result",
            {
                "argv": [
                    "env",
                    "OPENAI_API_KEY=secret-token",
                    "MY_TOKEN=abc123",
                    "SAFE_NAME=value",
                ]
            },
        )

        argv_dump = " ".join(payload["argv"])
        self.assertNotIn("secret-token", argv_dump)
        self.assertNotIn("abc123", argv_dump)
        self.assertIn("OPENAI_API_KEY=<redacted>", payload["argv"])
        self.assertIn("MY_TOKEN=<redacted>", payload["argv"])
        self.assertIn("SAFE_NAME=value", payload["argv"])

    def test_sanitize_history_payload_redacts_token_like_positional_args(self) -> None:
        payload = ccsw._sanitize_history_payload(
            "run-result",
            {
                "argv": [
                    "somecli",
                    "login",
                    "sk-abcdefghijklmnopqrstuvwxyz123456",
                    "safe-arg",
                ]
            },
        )

        argv_dump = " ".join(payload["argv"])
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", argv_dump)
        self.assertIn("<redacted>", payload["argv"])
        self.assertIn("safe-arg", payload["argv"])


class StoreLockAndPermissionsTests(unittest.TestCase):
    def test_private_file_writers_use_restricted_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            json_path = root / "providers.json"
            env_path = root / "active.env"

            ccsw.save_json(json_path, {"demo": True})
            ccsw.write_shell_exports(env_path, [("TOKEN", "secret")])

            self.assertEqual(stat.S_IMODE(json_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(env_path.stat().st_mode), 0o600)

    def test_lock_busy_raises_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock_path = root / "ccswitch.lock"
            holder_ready = threading.Event()
            holder_release = threading.Event()

            def _holder() -> None:
                with ccsw._state_lock(lock_path=lock_path):
                    holder_ready.set()
                    holder_release.wait(timeout=5)

            thread = threading.Thread(target=_holder, daemon=True)
            thread.start()
            holder_ready.wait(timeout=5)
            try:
                with self.assertRaises(SystemExit):
                    with ccsw._state_lock(lock_path=lock_path):
                        pass
            finally:
                holder_release.set()
                thread.join(timeout=5)

    def test_save_store_raises_on_revision_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                first = ccsw.load_store()
                second = ccsw.load_store()
                first["aliases"]["a1"] = "demo-provider"
                ccsw.save_store(first, expected_revision=first["_revision"])
                second["aliases"]["a2"] = "demo-provider"
                with self.assertRaises(ccsw.StoreConflictError):
                    ccsw.save_store(second, expected_revision=second["_revision"])

    def test_save_store_conflict_is_atomic_under_interleaving_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            original_write = ccsw._write_store_to_db
            holder_started = threading.Event()
            holder_release = threading.Event()
            call_count = {"value": 0}

            def _wrapped_write(conn, store, *, revision=None):
                call_count["value"] += 1
                if call_count["value"] == 1:
                    holder_started.set()
                    holder_release.wait(timeout=5)
                return original_write(conn, store, revision=revision)

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                initial = ccsw.load_store()
                ccsw.save_store(initial)
                first = ccsw.load_store()
                second = ccsw.load_store()
                first["aliases"]["a1"] = "demo-provider"
                second["aliases"]["a2"] = "demo-provider"

                def _writer():
                    ccsw.save_store(first, expected_revision=first["_revision"])

                with patch("ccsw._write_store_to_db", side_effect=_wrapped_write):
                    thread = threading.Thread(target=_writer, daemon=True)
                    thread.start()
                    holder_started.wait(timeout=5)
                    try:
                        with self.assertRaises(ccsw.StoreConflictError):
                            ccsw.save_store(second, expected_revision=second["_revision"])
                    finally:
                        holder_release.set()
                        thread.join(timeout=5)

    def test_batch_failure_snapshot_error_does_not_duplicate_batch_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "demo": {
                        "claude": {"base_url": "https://example.com", "token": "a", "extra_env": {}},
                        "codex": {"base_url": "https://example.com/v1", "token": "b"},
                    },
                },
                "profiles": {},
                "settings": {},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.save_store(store)
                with patch(
                    "ccsw.activate_tool_for_subprocess",
                    side_effect=[({"A": "1"}, []), SystemExit(1)],
                ), patch("ccsw._save_snapshot_json", side_effect=OSError("snapshot failed")):
                    with self.assertRaises(SystemExit):
                        ccsw.cmd_switch(ccsw.load_store(), "all", "demo")
                history = ccsw.list_history(limit=10)

        self.assertEqual([entry["action"] for entry in history].count("batch-result"), 1)

    def test_cmd_alias_add_reloads_fresh_store_under_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                stale = ccsw.load_store()
                fresh = ccsw.load_store()
                fresh["providers"]["demo-provider"] = {
                    "codex": {"base_url": "https://relay.example/v1", "token": "demo-token"}
                }
                fresh["aliases"]["first"] = "demo-provider"
                ccsw.save_store(fresh, expected_revision=fresh["_revision"])
                ccsw.cmd_alias_add(stale, "second", "demo-provider")
                reloaded = ccsw.load_store()

        self.assertEqual(reloaded["aliases"]["first"], "demo-provider")
        self.assertEqual(reloaded["aliases"]["second"], "demo-provider")

    def test_batch_failure_records_batch_result_without_persisting_partial_switch_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "demo": {
                        "claude": {"base_url": "https://example.com", "token": "a", "extra_env": {}},
                        "codex": {"base_url": "https://example.com/v1", "token": "b"},
                    },
                },
                "profiles": {},
                "settings": {},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.save_store(store)
                with patch(
                    "ccsw.activate_tool_for_subprocess",
                    side_effect=[({"A": "1"}, []), SystemExit(1)],
                ):
                    with self.assertRaises(SystemExit):
                        ccsw.cmd_switch(ccsw.load_store(), "all", "demo")
                history = ccsw.list_history(limit=10)

        actions = [entry["action"] for entry in history]
        self.assertIn("batch-result", actions)
        self.assertNotIn("switch", actions)

    def test_save_store_snapshot_failure_contract_for_settings_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": dict(ccsw.SETTINGS_DEFAULTS),
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.save_store(store)
                with patch("ccsw._save_snapshot_json", side_effect=OSError("snapshot failed")):
                    with self.assertRaises(ccsw.StoreSnapshotSyncError):
                        ccsw.cmd_settings_set(ccsw.load_store(), "codex_config_dir", "/tmp/custom-codex")
                reloaded = ccsw.load_store()

        self.assertEqual(reloaded["settings"]["codex_config_dir"], "/tmp/custom-codex")


class LeaseAndRuntimeContractTests(unittest.TestCase):
    def test_load_store_does_not_scrub_managed_target_secret_surface_on_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            runtime_root = root / "tmp" / "run-codex"
            runtime_root.mkdir(parents=True)
            auth_path = root / ".codex" / "auth.json"
            auth_path.parent.mkdir(parents=True)
            auth_bytes = json.dumps({"OPENAI_API_KEY": "original"}).encode("utf-8")

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch.object(
                ccsw, "TMP_DIR", root / "tmp"
            ):
                ccsw.save_store(ccsw._empty_store())
                ccsw.upsert_managed_target(
                    "codex",
                    {
                        "tool": "codex",
                        "lease_id": "lease-inline-secret",
                        "requested_target": "demo",
                        "selected_candidate": "demo",
                        "phase": "completed",
                        "restore_status": "restore_failed",
                        "cleanup_status": "pending",
                        "stale": True,
                        "stale_reason": "restore_failed",
                        "runtime_root": str(runtime_root),
                        "snapshots": {
                            str(auth_path): {
                                "exists": True,
                                "sha256": sha256(auth_bytes).hexdigest(),
                                "content_b64": base64.b64encode(auth_bytes).decode("ascii"),
                            }
                        },
                        "written_states": {},
                        "restore_groups": [],
                        "ephemeral_paths": [],
                    },
                )
                before = ccsw.get_managed_target("codex")
                loaded = ccsw.load_store()
                after = ccsw.get_managed_target("codex")

            self.assertEqual(loaded["version"], 2)
            self.assertIn("content_b64", before["snapshots"][str(auth_path)])
            self.assertIn("content_b64", after["snapshots"][str(auth_path)])
            self.assertFalse((runtime_root / "snapshots").exists())

    def test_main_scrubs_managed_target_secret_surface_before_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            runtime_root = root / "tmp" / "run-codex"
            runtime_root.mkdir(parents=True)
            auth_path = root / ".codex" / "auth.json"
            auth_path.parent.mkdir(parents=True)
            auth_bytes = json.dumps({"OPENAI_API_KEY": "original"}).encode("utf-8")

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch.object(
                ccsw, "TMP_DIR", root / "tmp"
            ):
                ccsw.save_store(ccsw._empty_store())
                ccsw.upsert_managed_target(
                    "codex",
                    {
                        "tool": "codex",
                        "lease_id": "lease-inline-secret",
                        "requested_target": "demo",
                        "selected_candidate": "demo",
                        "phase": "completed",
                        "restore_status": "restore_failed",
                        "cleanup_status": "pending",
                        "stale": True,
                        "stale_reason": "restore_failed",
                        "runtime_root": str(runtime_root),
                        "snapshots": {
                            str(auth_path): {
                                "exists": True,
                                "sha256": sha256(auth_bytes).hexdigest(),
                                "content_b64": base64.b64encode(auth_bytes).decode("ascii"),
                            }
                        },
                        "written_states": {},
                        "restore_groups": [],
                        "ephemeral_paths": [],
                    },
                )

                with patch.object(sys, "argv", ["ccsw.py", "list"]), patch(
                    "ccsw.cmd_list"
                ) as cmd_list, patch("ccsw.load_local_env"):
                    ccsw.main()

                sanitized = ccsw.get_managed_target("codex")

            cmd_list.assert_called_once()
            self.assertNotIn("content_b64", sanitized["snapshots"][str(auth_path)])
            self.assertIn("snapshot_file", sanitized["snapshots"][str(auth_path)])
            self.assertTrue((runtime_root / "snapshots").exists())

    def test_pid_matches_identity_requires_matching_start_token(self) -> None:
        with patch("ccsw._pid_is_running", return_value=True), patch(
            "ccsw._pid_start_token",
            return_value="pid-start",
        ):
            self.assertFalse(ccsw._pid_matches_identity(1234, None))
            self.assertFalse(ccsw._pid_matches_identity(1234, "other-start"))
            self.assertTrue(ccsw._pid_matches_identity(1234, "pid-start"))

    def test_claim_run_lease_without_start_token_blocks_as_active_owner(self) -> None:
        manifest = {
            "tool": "codex",
            "lease_id": "lease-no-start",
            "requested_target": "demo",
            "selected_candidate": "demo",
            "owner_pid": os.getpid(),
            "phase": "cleaning",
            "restore_status": "restored",
            "cleanup_status": "pending",
            "stale": False,
        }

        with patch("ccsw.get_managed_target", return_value=manifest):
            result = ccsw._claim_run_lease("codex", "demo")

        self.assertIsNotNone(result)
        self.assertIn("active runtime lease owned by another process", result.stderr)

    def test_claim_run_lease_blocks_completed_lease_with_live_unverifiable_owner(self) -> None:
        manifest = {
            "tool": "codex",
            "lease_id": "lease-complete-no-start",
            "requested_target": "demo",
            "selected_candidate": "demo",
            "owner_pid": os.getpid(),
            "phase": "completed",
            "restore_status": "restored",
            "cleanup_status": "cleaned",
            "stale": False,
        }

        with patch("ccsw.get_managed_target", return_value=manifest):
            result = ccsw._claim_run_lease("codex", "demo")

        self.assertIsNotNone(result)
        self.assertIn("active runtime lease owned by another process", result.stderr)

    def test_batch_failure_restores_partially_written_failed_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            config_path = codex_dir / "config.toml"
            auth_path.write_text(json.dumps({"OPENAI_API_KEY": "original"}), encoding="utf-8")
            config_path.write_text('model = "gpt-5.4"\n', encoding="utf-8")
            store = {
                "version": 2,
                "active": {
                    "claude": "original-claude",
                    "codex": "original-codex",
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {
                        "claude": {"base_url": "https://example.com", "token": "a", "extra_env": {}},
                        "codex": {"base_url": "https://example.com/v1", "token": "b"},
                    },
                    "original-claude": {
                        "claude": {"base_url": "https://original.example", "token": "o", "extra_env": {}},
                    },
                    "original-codex": {
                        "codex": {"base_url": "https://original.example/v1", "token": "p"},
                    },
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            def _activate(_store, tool, provider_name, **_kwargs):
                if tool == "codex":
                    auth_path.write_text(json.dumps({"OPENAI_API_KEY": "half-written"}), encoding="utf-8")
                    raise SystemExit(1)
                return ({"A": "1"}, [])

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch(
                "ccsw.activate_tool_for_subprocess",
                side_effect=_activate,
            ), patch(
                "ccsw._safe_local_restore_validation",
                return_value={"status": "ok", "reason_code": "ready"},
            ):
                ccsw.save_store(store)
                with self.assertRaises(SystemExit):
                    ccsw.cmd_switch(ccsw.load_store(), "all", "demo")
                reloaded = ccsw.load_store()
                history = ccsw.list_history(limit=5)

            self.assertEqual(json.loads(auth_path.read_text(encoding="utf-8"))["OPENAI_API_KEY"], "original")
            self.assertEqual(reloaded["active"]["codex"], "original-codex")
            batch_entry = next(entry for entry in history if entry["action"] == "batch-result")
            self.assertEqual(batch_entry["payload"]["rollback_status"], "restored")
            self.assertIn("codex", batch_entry["payload"]["restored_tools"])
            self.assertEqual(batch_entry["payload"]["conflicted_tools"], [])

    def test_run_success_persists_and_clears_managed_target_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            (codex_dir / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "original"}), encoding="utf-8")
            (codex_dir / "config.toml").write_text('model = "gpt-5.4"\n', encoding="utf-8")
            store = {
                "version": 2,
                "active": {
                    "claude": None,
                    "codex": "demo",
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example.com/v1",
                            "token": "original",
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }
            observed_during_run: list[dict[str, object]] = []
            snapshot_file_observed = {"exists": False}

            def _run(*_args, **_kwargs):
                observed_during_run.extend(ccsw.list_managed_targets())
                snapshot_entry = observed_during_run[0]["snapshots"][str(codex_dir / "auth.json")]
                snapshot_file_observed["exists"] = Path(snapshot_entry["snapshot_file"]).exists()
                return subprocess.CompletedProcess(["codex", "exec", "hi"], 0, "ok\n", "")

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch(
                "ccsw.select_codex_base_url", return_value="https://relay.example.com/v1"
            ), patch(
                "ccsw._safe_local_restore_validation",
                return_value={"status": "ok", "reason_code": "ready"},
            ), patch("ccsw.subprocess.run", side_effect=_run):
                ccsw.save_store(store)
                result = ccsw.run_with_fallback(ccsw.load_store(), "codex", "demo", ["codex", "exec", "hi"])
                remaining = ccsw.list_managed_targets()

        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(observed_during_run), 1)
        self.assertEqual(observed_during_run[0]["tool"], "codex")
        self.assertEqual(observed_during_run[0]["phase"], "subprocess")
        self.assertEqual(remaining, [])
        snapshot_entry = observed_during_run[0]["snapshots"][str(codex_dir / "auth.json")]
        self.assertTrue(snapshot_entry["exists"])
        self.assertIn("snapshot_file", snapshot_entry)
        self.assertNotIn("content_b64", snapshot_entry)
        self.assertTrue(snapshot_file_observed["exists"])

    def test_run_restore_conflict_keeps_stale_managed_target_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            config_path = codex_dir / "config.toml"
            auth_path.write_text(json.dumps({"OPENAI_API_KEY": "original"}), encoding="utf-8")
            config_path.write_text('model = "gpt-5.4"\n', encoding="utf-8")
            store = {
                "version": 2,
                "active": {
                    "claude": None,
                    "codex": "demo",
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example.com/v1",
                            "token": "demo-token",
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            def _run(*_args, **_kwargs):
                auth_path.write_text(
                    json.dumps({"OPENAI_API_KEY": "external-change"}),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(["codex", "exec", "hi"], 0, "ok\n", "")

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch(
                "ccsw.select_codex_base_url", return_value="https://relay.example.com/v1"
            ), patch("ccsw.subprocess.run", side_effect=_run):
                ccsw.save_store(store)
                result = ccsw.run_with_fallback(ccsw.load_store(), "codex", "demo", ["codex", "exec", "hi"])
                remaining = ccsw.list_managed_targets()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["tool"], "codex")
        self.assertEqual(remaining[0]["phase"], "completed")
        self.assertTrue(remaining[0]["stale"])
        self.assertEqual(remaining[0]["restore_status"], "restore_conflict")
        self.assertEqual(remaining[0]["stale_reason"], "restore_conflict")

    def test_run_restore_validation_failure_keeps_stale_managed_target_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            config_path = codex_dir / "config.toml"
            auth_path.write_text(json.dumps({"OPENAI_API_KEY": "original"}), encoding="utf-8")
            config_path.write_text('model = "gpt-5.4"\n', encoding="utf-8")
            store = {
                "version": 2,
                "active": {
                    "claude": None,
                    "codex": "demo",
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example.com/v1",
                            "token": "original",
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch(
                "ccsw.select_codex_base_url", return_value="https://relay.example.com/v1"
            ), patch(
                "ccsw._safe_local_restore_validation",
                return_value={"status": "degraded", "reason_code": "config_mismatch"},
            ), patch(
                "ccsw.subprocess.run",
                return_value=subprocess.CompletedProcess(["codex", "exec", "hi"], 0, "ok\n", ""),
            ):
                ccsw.save_store(store)
                result = ccsw.run_with_fallback(ccsw.load_store(), "codex", "demo", ["codex", "exec", "hi"])
                remaining = ccsw.list_managed_targets()

        self.assertEqual(result.returncode, 1)
        self.assertIn("restore failed", result.stderr)
        self.assertEqual(len(remaining), 1)
        self.assertTrue(remaining[0]["stale"])
        self.assertEqual(remaining[0]["restore_status"], "restore_failed")
        self.assertEqual(remaining[0]["stale_reason"], "restore_failed")
        self.assertEqual(remaining[0]["post_restore_validation"]["status"], "degraded")

    def test_repair_preserves_restore_conflict_for_a_real_stale_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            config_path = codex_dir / "config.toml"
            original_auth = json.dumps({"OPENAI_API_KEY": "original"}).encode("utf-8")
            mutated_auth = json.dumps({"OPENAI_API_KEY": "mutated"}).encode("utf-8")
            auth_path.write_bytes(original_auth)
            config_path.write_text('model = "gpt-5.4"\n', encoding="utf-8")
            store = {
                "version": 2,
                "active": {
                    "claude": None,
                    "codex": "demo",
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example.com/v1",
                            "token": "demo-token",
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            def _run(*_args, **_kwargs):
                auth_path.write_bytes(mutated_auth)
                return subprocess.CompletedProcess(["codex", "exec", "hi"], 0, "ok\n", "")

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch.object(
                ccsw, "TMP_DIR", root / "tmp"
            ), patch(
                "ccsw.select_codex_base_url", return_value="https://relay.example.com/v1"
            ), patch(
                "ccsw._safe_local_restore_validation",
                return_value={"status": "ok", "reason_code": "ready"},
            ), patch("ccsw.subprocess.run", side_effect=_run):
                ccsw.save_store(store)
                result = ccsw.run_with_fallback(ccsw.load_store(), "codex", "demo", ["codex", "exec", "hi"])
                stale_manifest = ccsw.get_managed_target("codex")
                with self.assertRaises(SystemExit):
                    ccsw.cmd_repair(ccsw.load_store(), "codex")
                remaining = ccsw.get_managed_target("codex")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(getattr(result, "_ccsw_restore_status"), "restore_conflict")
        self.assertIsNotNone(stale_manifest)
        self.assertIsNotNone(remaining)
        self.assertEqual(remaining["stale_reason"], "restore_conflict")
        self.assertEqual(remaining["restore_status"], "restore_conflict")

    def test_run_refuses_to_overwrite_existing_stale_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {
                    "claude": None,
                    "codex": "demo",
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example.com/v1",
                            "token": "demo-token",
                        }
                    }
                },
                "profiles": {},
                "settings": {},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch(
                "ccsw.subprocess.Popen"
            ) as popen:
                ccsw.save_store(store)
                ccsw.upsert_managed_target(
                    "codex",
                    {
                        "tool": "codex",
                        "lease_id": "lease-stale",
                        "requested_target": "demo",
                        "selected_candidate": "demo",
                        "phase": "completed",
                        "stale": True,
                        "stale_reason": "restore_conflict",
                        "restore_status": "restore_conflict",
                        "cleanup_status": "pending",
                    },
                )
                result = ccsw.run_with_fallback(ccsw.load_store(), "codex", "demo", ["codex", "exec", "hi"])
                remaining = ccsw.get_managed_target("codex")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(remaining["lease_id"], "lease-stale")
        popen.assert_not_called()

    def test_run_refuses_to_overwrite_owner_dead_unfinished_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {
                    "claude": None,
                    "codex": "demo",
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example.com/v1",
                            "token": "demo-token",
                        }
                    }
                },
                "profiles": {},
                "settings": {},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch(
                "ccsw.subprocess.Popen"
            ) as popen:
                ccsw.save_store(store)
                ccsw.upsert_managed_target(
                    "codex",
                    {
                        "tool": "codex",
                        "lease_id": "lease-dead-owner",
                        "requested_target": "demo",
                        "selected_candidate": "demo",
                        "owner_pid": 999999,
                        "phase": "restoring",
                        "stale": False,
                        "restore_status": "pending",
                        "cleanup_status": "pending",
                    },
                )
                result = ccsw.run_with_fallback(ccsw.load_store(), "codex", "demo", ["codex", "exec", "hi"])
                remaining = ccsw.get_managed_target("codex")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(remaining["lease_id"], "lease-dead-owner")
        popen.assert_not_called()

    def test_cmd_run_records_lease_blocked_failure_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {
                    "claude": None,
                    "codex": "demo",
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example.com/v1",
                            "token": "demo-token",
                        }
                    }
                },
                "profiles": {},
                "settings": {},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.save_store(store)
                ccsw.upsert_managed_target(
                    "codex",
                    {
                        "tool": "codex",
                        "lease_id": "lease-blocked",
                        "requested_target": "demo",
                        "selected_candidate": "demo",
                        "phase": "completed",
                        "stale": True,
                        "stale_reason": "restore_failed",
                        "restore_status": "restore_failed",
                        "cleanup_status": "pending",
                    },
                )
                with self.assertRaises(SystemExit):
                    ccsw.cmd_run(ccsw.load_store(), "codex", "demo", ["codex", "exec", "hi"])
                history = ccsw.list_history(limit=5)

        run_result = next(entry for entry in history if entry["action"] == "run-result")
        self.assertEqual(run_result["payload"]["final_failure_type"], "lease_blocked")
        self.assertEqual(run_result["payload"]["restore_status"], "not_run")
        self.assertEqual(run_result["payload"]["cleanup_status"], "not_run")
        self.assertEqual(run_result["payload"]["selected_candidate"], "demo")

    def test_doctor_reports_stale_managed_target_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            runtime_root = root / "tmp" / "run-stale"
            runtime_root.mkdir(parents=True)
            store = {
                "version": 2,
                "active": {
                    "claude": None,
                    "codex": None,
                    "gemini": None,
                    "opencode": "demo",
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {
                        "opencode": {
                            "base_url": "https://relay.example.com/v1",
                            "token": ccsw.env_ref("DEMO_TOKEN"),
                            "provider_id": "demo",
                        }
                    }
                },
                "profiles": {},
                "settings": {},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch.object(
                ccsw, "TMP_DIR", root / "tmp"
            ), patch("ccsw._generic_url_probe", return_value=("ok", {"reason_code": "reachable"})), patch(
                "ccsw._probe_overlay_activation",
                return_value=("ok", {"reason_code": "overlay_ready", "active_overlay": str(runtime_root / "opencode.json")}),
            ), patch(
                "ccsw._probe_overlay_content",
                return_value=("ok", {"reason_code": "overlay_content_ready"}),
            ), patch.dict(os.environ, {"DEMO_TOKEN": "demo-token"}, clear=False):
                ccsw.save_store(store)
                ccsw.upsert_managed_target(
                    "opencode",
                    {
                        "tool": "opencode",
                        "lease_id": "lease-1",
                        "requested_target": "demo",
                        "selected_candidate": "demo",
                        "phase": "restore_conflict",
                        "runtime_root": str(runtime_root),
                        "restore_status": "restore_conflict",
                        "cleanup_status": "pending",
                        "stale": True,
                    },
                )
                status, detail = ccsw._probe_tool_health(
                    ccsw.load_store(),
                    "opencode",
                    "demo",
                    store["providers"]["demo"]["opencode"],
                )

        self.assertEqual(status, "degraded")
        self.assertEqual(detail["reason_code"], "stale_lease")
        self.assertEqual(detail["checks"]["runtime_lease_check"]["reason_code"], "stale_lease")

    def test_runtime_lease_check_degrades_when_owner_pid_is_running_without_start_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            runtime_root = root / "tmp" / "run-active"
            runtime_root.mkdir(parents=True)
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch.object(
                ccsw, "TMP_DIR", root / "tmp"
            ):
                ccsw.save_store(store)
                ccsw.upsert_managed_target(
                    "codex",
                    {
                        "tool": "codex",
                        "lease_id": "lease-active-no-start-token",
                        "requested_target": "demo",
                        "selected_candidate": "demo",
                        "owner_pid": os.getpid(),
                        "child_pid": None,
                        "phase": "completed",
                        "runtime_root": str(runtime_root),
                        "restore_status": "restore_failed",
                        "cleanup_status": "pending",
                        "stale": False,
                    },
                )
                status, detail = ccsw._runtime_lease_check("codex", "demo")

        self.assertEqual(status, "degraded")
        self.assertEqual(detail["reason_code"], "runtime_busy")

    def test_doctor_cli_reports_running_child_without_start_token_from_persisted_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            codex_dir = root / ".codex"
            codex_dir.mkdir()
            runtime_root = root / "tmp" / "run-child-active"
            runtime_root.mkdir(parents=True)
            store = {
                "version": 2,
                "active": {"claude": None, "codex": "demo", "gemini": None, "opencode": None, "openclaw": None},
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example/v1",
                            "token": ccsw.env_ref("DEMO_CODEX_TOKEN"),
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            output = StringIO()
            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch.object(
                ccsw, "TMP_DIR", root / "tmp"
            ), patch.dict(
                os.environ,
                {"DEMO_CODEX_TOKEN": "demo-token"},
                clear=False,
            ), patch(
                "ccsw._probe_codex_target",
                return_value=("ok", {"reason_code": "models_ready", "checks": {}, "mismatch_fields": []}),
            ):
                ccsw.save_store(store)
                ccsw.upsert_managed_target(
                    "codex",
                    {
                        "tool": "codex",
                        "lease_id": "lease-active-child-no-start-token",
                        "requested_target": "demo",
                        "selected_candidate": "demo",
                        "child_pid": os.getpid(),
                        "child_status": "running",
                        "phase": "subprocess",
                        "runtime_root": str(runtime_root),
                        "restore_status": "pending",
                        "cleanup_status": "pending",
                        "stale": False,
                    },
                )
                with redirect_stdout(output):
                    ok = ccsw.cmd_doctor(ccsw.load_store(), "codex", "demo", json_output=True)

        self.assertFalse(ok)
        payload = json.loads(output.getvalue().strip())
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["summary_reason"], "runtime_child_running")
        self.assertEqual(payload["checks"]["runtime_lease_check"]["reason_code"], "runtime_child_running")
        self.assertTrue(payload["checks"]["runtime_lease_check"]["child_pid_running"])
        self.assertFalse(payload["checks"]["runtime_lease_check"]["child_identity_match"])

    def test_doctor_ignores_stale_lease_for_other_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            opencode_dir = root / "opencode-home"
            opencode_dir.mkdir()
            runtime_root = root / "tmp" / "run-stale"
            runtime_root.mkdir(parents=True)
            store = {
                "version": 2,
                "active": {
                    "claude": None,
                    "codex": None,
                    "gemini": None,
                    "opencode": "demo",
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {
                        "opencode": {
                            "base_url": "https://relay.example.com/v1",
                            "token": ccsw.env_ref("DEMO_TOKEN"),
                            "provider_id": "demo",
                        }
                    },
                    "other": {
                        "opencode": {
                            "base_url": "https://relay.example.com/v1",
                            "token": ccsw.env_ref("OTHER_TOKEN"),
                            "provider_id": "other",
                        }
                    },
                },
                "profiles": {},
                "settings": {"opencode_config_dir": str(opencode_dir)},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch.object(
                ccsw, "TMP_DIR", root / "tmp"
            ), patch("ccsw._generic_url_probe", return_value=("ok", {"reason_code": "reachable"})), patch(
                "ccsw._probe_overlay_activation",
                return_value=("ok", {"reason_code": "overlay_ready", "active_overlay": str(runtime_root / "opencode.json")}),
            ), patch(
                "ccsw._probe_overlay_content",
                return_value=("ok", {"reason_code": "overlay_content_ready"}),
            ), patch.dict(os.environ, {"DEMO_TOKEN": "demo-token", "OTHER_TOKEN": "other-token"}, clear=False):
                ccsw.save_store(store)
                ccsw.upsert_managed_target(
                    "opencode",
                    {
                        "tool": "opencode",
                        "lease_id": "lease-other",
                        "requested_target": "other",
                        "selected_candidate": "other",
                        "phase": "completed",
                        "runtime_root": str(runtime_root),
                        "restore_status": "restore_conflict",
                        "cleanup_status": "pending",
                        "stale": True,
                        "stale_reason": "restore_conflict",
                    },
                )
                status, detail = ccsw._probe_tool_health(
                    ccsw.load_store(),
                    "opencode",
                    "demo",
                    store["providers"]["demo"]["opencode"],
                )

        self.assertEqual(status, "degraded")
        self.assertEqual(detail["checks"]["runtime_lease_check"]["reason_code"], "lease_for_other_target")

    def test_run_keyboard_interrupt_preserves_interrupt_semantics(self) -> None:
        store = {
            "version": 2,
            "active": {
                "claude": None,
                "codex": "demo",
                "gemini": None,
                "opencode": None,
                "openclaw": None,
            },
            "aliases": {},
            "providers": {
                "demo": {"codex": {"base_url": "https://relay.example/v1", "token": "demo-token"}}
            },
            "profiles": {},
            "settings": {},
        }

        with patch(
            "ccsw.activate_tool_for_subprocess",
            return_value=({"OPENAI_API_KEY": "demo-token"}, ["OPENAI_BASE_URL"]),
        ), patch("ccsw.subprocess.run", side_effect=KeyboardInterrupt()), patch(
            "ccsw.record_history"
        ) as record_history:
            result = ccsw.run_with_fallback(store, "codex", "demo", ["codex", "exec", "hi"])

        self.assertEqual(result.returncode, 130)
        self.assertEqual(getattr(result, "_ccsw_final_failure_type"), "interrupted")
        attempt_payload = record_history.call_args_list[0].args[3]
        self.assertEqual(attempt_payload["phase"], "subprocess")
        self.assertEqual(attempt_payload["failure_type"], "interrupted")
        self.assertFalse(attempt_payload["retryable"])

    def test_repair_rejects_active_owner_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.save_store(store)
                ccsw.upsert_managed_target(
                    "codex",
                    {
                        "tool": "codex",
                        "lease_id": "lease-active",
                        "requested_target": "demo",
                        "selected_candidate": "demo",
                        "owner_pid": os.getpid(),
                        "owner_started_at": ccsw._pid_start_token(os.getpid()),
                        "child_pid": None,
                        "phase": "cleaning",
                        "restore_status": "restored",
                        "cleanup_status": "pending",
                        "stale": False,
                    },
                )
                with self.assertRaises(SystemExit):
                    ccsw.cmd_repair(ccsw.load_store(), "codex")
                remaining = ccsw.get_managed_target("codex")

        self.assertEqual(remaining["lease_id"], "lease-active")

    def test_repair_rejects_active_owner_without_start_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            original_bytes = json.dumps({"OPENAI_API_KEY": "original"}).encode("utf-8")
            mutated_bytes = json.dumps({"OPENAI_API_KEY": "mutated"}).encode("utf-8")
            auth_path.write_text(mutated_bytes.decode("utf-8"), encoding="utf-8")
            runtime_root = root / "tmp" / "run-codex"
            runtime_root.mkdir(parents=True)
            store = {
                "version": 2,
                "active": {
                    "claude": None,
                    "codex": "demo",
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example.com/v1",
                            "token": "demo-token",
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch.object(
                ccsw, "TMP_DIR", root / "tmp"
            ), patch(
                "ccsw._safe_local_restore_validation",
                return_value={"status": "ok", "reason_code": "ready"},
            ):
                ccsw.save_store(store)
                ccsw.upsert_managed_target(
                    "codex",
                    {
                        "tool": "codex",
                        "lease_id": "lease-active-no-start-token",
                        "requested_target": "demo",
                        "selected_candidate": "demo",
                        "owner_pid": os.getpid(),
                        "child_pid": None,
                        "child_status": "exited",
                        "phase": "completed",
                        "runtime_root": str(runtime_root),
                        "restore_status": "restore_failed",
                        "cleanup_status": "pending",
                        "stale": False,
                        "snapshots": {
                            str(auth_path): {
                                "exists": True,
                                "sha256": sha256(original_bytes).hexdigest(),
                                "content_b64": "eyJPUEVOQUlfQVBJX0tFWSI6ICJvcmlnaW5hbCJ9",
                            }
                        },
                        "written_states": {
                            str(auth_path): {
                                "exists": True,
                                "sha256": sha256(mutated_bytes).hexdigest(),
                            }
                        },
                        "restore_groups": [[str(auth_path)]],
                        "ephemeral_paths": [],
                        "post_restore_validation": {"status": "pending", "reason_code": "pending"},
                    },
                )
                with self.assertRaises(SystemExit):
                    ccsw.cmd_repair(ccsw.load_store(), "codex")
                remaining = ccsw.get_managed_target("codex")
                still_mutated = json.loads(auth_path.read_text(encoding="utf-8"))

        self.assertEqual(still_mutated["OPENAI_API_KEY"], "mutated")
        self.assertEqual(remaining["lease_id"], "lease-active-no-start-token")

    def test_repair_rejects_active_child_without_start_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            original_bytes = json.dumps({"OPENAI_API_KEY": "original"}).encode("utf-8")
            mutated_bytes = json.dumps({"OPENAI_API_KEY": "mutated"}).encode("utf-8")
            auth_path.write_text(mutated_bytes.decode("utf-8"), encoding="utf-8")
            runtime_root = root / "tmp" / "run-codex-child"
            runtime_root.mkdir(parents=True)
            store = {
                "version": 2,
                "active": {
                    "claude": None,
                    "codex": "demo",
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example.com/v1",
                            "token": "demo-token",
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch.object(
                ccsw, "TMP_DIR", root / "tmp"
            ), patch(
                "ccsw._safe_local_restore_validation",
                return_value={"status": "ok", "reason_code": "ready"},
            ):
                ccsw.save_store(store)
                ccsw.upsert_managed_target(
                    "codex",
                    {
                        "tool": "codex",
                        "lease_id": "lease-active-child-no-start-token",
                        "requested_target": "demo",
                        "selected_candidate": "demo",
                        "owner_pid": None,
                        "child_pid": os.getpid(),
                        "child_status": "running",
                        "phase": "subprocess",
                        "runtime_root": str(runtime_root),
                        "restore_status": "pending",
                        "cleanup_status": "pending",
                        "stale": False,
                        "snapshots": {
                            str(auth_path): {
                                "exists": True,
                                "sha256": sha256(original_bytes).hexdigest(),
                                "content_b64": "eyJPUEVOQUlfQVBJX0tFWSI6ICJvcmlnaW5hbCJ9",
                            }
                        },
                        "written_states": {
                            str(auth_path): {
                                "exists": True,
                                "sha256": sha256(mutated_bytes).hexdigest(),
                            }
                        },
                        "restore_groups": [[str(auth_path)]],
                        "ephemeral_paths": [],
                        "post_restore_validation": {"status": "pending", "reason_code": "pending"},
                    },
                )
                with self.assertRaises(SystemExit):
                    ccsw.cmd_repair(ccsw.load_store(), "codex")
                remaining = ccsw.get_managed_target("codex")
                still_mutated = json.loads(auth_path.read_text(encoding="utf-8"))

        self.assertEqual(still_mutated["OPENAI_API_KEY"], "mutated")
        self.assertEqual(remaining["lease_id"], "lease-active-child-no-start-token")

    def test_repair_decode_error_records_manifest_decode_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.save_store(store)
                conn = sqlite3.connect(db_path)
                try:
                    conn.execute(
                        "INSERT INTO managed_targets(tool, target_json) VALUES (?, ?)",
                        ("codex", "{bad-json"),
                    )
                    conn.commit()
                finally:
                    conn.close()
                with self.assertRaises(SystemExit):
                    ccsw.cmd_repair(ccsw.load_store(), "codex")
                history = ccsw.list_history(limit=5, action="repair-result")

        repair_entry = history[0]
        self.assertEqual(repair_entry["payload"]["repair_status"], "manifest_decode_failed")
        self.assertEqual(repair_entry["payload"]["restore_status"], "restore_failed")

    def test_repair_decode_error_scrubs_secret_bearing_raw_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            secret_blob = base64.b64encode(b"inline-secret").decode("ascii")
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.save_store(store)
                conn = sqlite3.connect(db_path)
                try:
                    conn.execute(
                        "INSERT INTO managed_targets(tool, target_json) VALUES (?, ?)",
                        (
                            "codex",
                            '{"tool":"codex","snapshots":{"x":{"content_b64":"'
                            + secret_blob
                            + '"}}',
                        ),
                    )
                    conn.commit()
                finally:
                    conn.close()
                with self.assertRaises(SystemExit):
                    ccsw.cmd_repair(ccsw.load_store(), "codex")
                conn = sqlite3.connect(db_path)
                try:
                    raw_row = conn.execute(
                        "SELECT target_json FROM managed_targets WHERE tool = ?",
                        ("codex",),
                    ).fetchone()
                finally:
                    conn.close()

        if raw_row is not None:
            self.assertNotIn(secret_blob, raw_row[0])
            self.assertIn("manifest_decode_failed", raw_row[0])

    def test_repair_malformed_snapshot_does_not_delete_live_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            auth_path.write_text(json.dumps({"OPENAI_API_KEY": "mutated"}), encoding="utf-8")
            runtime_root = root / "tmp" / "run-codex"
            runtime_root.mkdir(parents=True)
            store = {
                "version": 2,
                "active": {"claude": None, "codex": "demo", "gemini": None, "opencode": None, "openclaw": None},
                "aliases": {},
                "providers": {"demo": {"codex": {"base_url": "https://relay.example.com/v1", "token": "demo-token"}}},
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch.object(
                ccsw, "TMP_DIR", root / "tmp"
            ):
                ccsw.save_store(store)
                ccsw.upsert_managed_target(
                    "codex",
                    {
                        "tool": "codex",
                        "lease_id": "lease-bad-snapshot",
                        "requested_target": "demo",
                        "selected_candidate": "demo",
                        "owner_pid": 999999,
                        "child_pid": None,
                        "child_status": "exited",
                        "phase": "completed",
                        "runtime_root": str(runtime_root),
                        "restore_status": "restore_failed",
                        "cleanup_status": "pending",
                        "stale": True,
                        "stale_reason": "restore_failed",
                        "snapshots": {
                            str(auth_path): {
                                "exists": True,
                                "sha256": "bad",
                            }
                        },
                        "written_states": {
                            str(auth_path): {
                                "exists": True,
                                "sha256": sha256(auth_path.read_bytes()).hexdigest(),
                            }
                        },
                        "restore_groups": [[str(auth_path)]],
                        "ephemeral_paths": [],
                    },
                )
                with self.assertRaises(SystemExit):
                    ccsw.cmd_repair(ccsw.load_store(), "codex")
                remaining = ccsw.get_managed_target("codex")

            self.assertEqual(json.loads(auth_path.read_text(encoding="utf-8"))["OPENAI_API_KEY"], "mutated")
            self.assertEqual(remaining["stale_reason"], "manifest_decode_failed")
            self.assertIn("manifest decode failed", remaining["restore_error"])

    def test_repair_rejects_runtime_root_that_is_not_a_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            auth_path.write_text(json.dumps({"OPENAI_API_KEY": "mutated"}), encoding="utf-8")
            runtime_root = root / "tmp" / "scratch-dir"
            runtime_root.mkdir(parents=True)
            store = {
                "version": 2,
                "active": {"claude": None, "codex": "demo", "gemini": None, "opencode": None, "openclaw": None},
                "aliases": {},
                "providers": {"demo": {"codex": {"base_url": "https://relay.example.com/v1", "token": "demo-token"}}},
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch.object(
                ccsw, "TMP_DIR", root / "tmp"
            ):
                ccsw.save_store(store)
                ccsw.upsert_managed_target(
                    "codex",
                    {
                        "tool": "codex",
                        "lease_id": "lease-scratch",
                        "requested_target": "demo",
                        "selected_candidate": "demo",
                        "owner_pid": 999999,
                        "child_pid": None,
                        "child_status": "exited",
                        "phase": "completed",
                        "runtime_root": str(runtime_root),
                        "restore_status": "restore_failed",
                        "cleanup_status": "pending",
                        "stale": True,
                        "stale_reason": "restore_failed",
                        "snapshots": {
                            str(auth_path): {
                                "exists": True,
                                "sha256": sha256(auth_path.read_bytes()).hexdigest(),
                                "content_b64": base64.b64encode(auth_path.read_bytes()).decode("ascii"),
                            }
                        },
                        "written_states": {
                            str(auth_path): {
                                "exists": True,
                                "sha256": sha256(auth_path.read_bytes()).hexdigest(),
                            }
                        },
                        "restore_groups": [[str(auth_path)]],
                        "ephemeral_paths": [],
                    },
                )
                with self.assertRaises(SystemExit):
                    ccsw.cmd_repair(ccsw.load_store(), "codex")
                remaining = ccsw.get_managed_target("codex")

        self.assertEqual(remaining["stale_reason"], "manifest_decode_failed")
        self.assertIn("runtime_root", remaining["restore_error"])

    def test_repair_failed_scrubs_inline_snapshot_payloads_from_remaining_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            auth_path.write_text(json.dumps({"OPENAI_API_KEY": "mutated"}), encoding="utf-8")
            inline_blob = base64.b64encode(auth_path.read_bytes()).decode("ascii")
            runtime_root = root / "tmp" / "scratch-dir"
            runtime_root.mkdir(parents=True)
            store = {
                "version": 2,
                "active": {"claude": None, "codex": "demo", "gemini": None, "opencode": None, "openclaw": None},
                "aliases": {},
                "providers": {"demo": {"codex": {"base_url": "https://relay.example.com/v1", "token": "demo-token"}}},
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch.object(
                ccsw, "TMP_DIR", root / "tmp"
            ):
                ccsw.save_store(store)
                ccsw.upsert_managed_target(
                    "codex",
                    {
                        "tool": "codex",
                        "lease_id": "lease-scrub-inline",
                        "requested_target": "demo",
                        "selected_candidate": "demo",
                        "owner_pid": 999999,
                        "child_pid": None,
                        "child_status": "exited",
                        "phase": "completed",
                        "runtime_root": str(runtime_root),
                        "restore_status": "restore_failed",
                        "cleanup_status": "pending",
                        "stale": True,
                        "stale_reason": "restore_failed",
                        "snapshots": {
                            str(auth_path): {
                                "exists": True,
                                "sha256": sha256(auth_path.read_bytes()).hexdigest(),
                                "content_b64": inline_blob,
                            }
                        },
                        "written_states": {
                            str(auth_path): {
                                "exists": True,
                                "sha256": sha256(auth_path.read_bytes()).hexdigest(),
                            }
                        },
                        "restore_groups": [[str(auth_path)]],
                        "ephemeral_paths": [],
                    },
                )
                with self.assertRaises(SystemExit):
                    ccsw.cmd_repair(ccsw.load_store(), "codex")
                remaining = ccsw.get_managed_target("codex")

        self.assertIsNotNone(remaining)
        self.assertNotIn("content_b64", next(iter(remaining["snapshots"].values())))

    def test_repair_missing_restore_groups_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            auth_path.write_text(json.dumps({"OPENAI_API_KEY": "mutated"}), encoding="utf-8")
            runtime_root = root / "tmp" / "run-codex"
            runtime_root.mkdir(parents=True)
            store = {
                "version": 2,
                "active": {"claude": None, "codex": "demo", "gemini": None, "opencode": None, "openclaw": None},
                "aliases": {},
                "providers": {"demo": {"codex": {"base_url": "https://relay.example.com/v1", "token": "demo-token"}}},
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch.object(
                ccsw, "TMP_DIR", root / "tmp"
            ):
                ccsw.save_store(store)
                ccsw.upsert_managed_target(
                    "codex",
                    {
                        "tool": "codex",
                        "lease_id": "lease-missing-groups",
                        "requested_target": "demo",
                        "selected_candidate": "demo",
                        "owner_pid": 999999,
                        "child_pid": None,
                        "child_status": "exited",
                        "phase": "completed",
                        "runtime_root": str(runtime_root),
                        "restore_status": "restore_failed",
                        "cleanup_status": "pending",
                        "stale": True,
                        "stale_reason": "restore_failed",
                        "snapshots": {
                            str(auth_path): {
                                "exists": False,
                                "sha256": None,
                                "content_b64": None,
                            }
                        },
                        "written_states": {
                            str(auth_path): {
                                "exists": True,
                                "sha256": sha256(auth_path.read_bytes()).hexdigest(),
                            }
                        },
                        "ephemeral_paths": [],
                    },
                )
                with self.assertRaises(SystemExit):
                    ccsw.cmd_repair(ccsw.load_store(), "codex")
                remaining = ccsw.get_managed_target("codex")

            self.assertEqual(json.loads(auth_path.read_text(encoding="utf-8"))["OPENAI_API_KEY"], "mutated")
            self.assertEqual(remaining["stale_reason"], "manifest_decode_failed")
            self.assertIn("manifest decode failed", remaining["restore_error"])

    def test_repair_rejects_manifest_paths_outside_managed_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            escape_path = root / "escape.txt"
            auth_path.write_text(json.dumps({"OPENAI_API_KEY": "mutated"}), encoding="utf-8")
            escape_path.write_text("leave-me-alone", encoding="utf-8")
            runtime_root = root / "tmp" / "run-codex"
            runtime_root.mkdir(parents=True)
            store = {
                "version": 2,
                "active": {"claude": None, "codex": "demo", "gemini": None, "opencode": None, "openclaw": None},
                "aliases": {},
                "providers": {"demo": {"codex": {"base_url": "https://relay.example.com/v1", "token": "demo-token"}}},
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch.object(
                ccsw, "TMP_DIR", root / "tmp"
            ):
                ccsw.save_store(store)
                ccsw.upsert_managed_target(
                    "codex",
                    {
                        "tool": "codex",
                        "lease_id": "lease-escape",
                        "requested_target": "demo",
                        "selected_candidate": "demo",
                        "owner_pid": 999999,
                        "child_pid": None,
                        "child_status": "exited",
                        "phase": "completed",
                        "runtime_root": str(runtime_root),
                        "restore_status": "restore_failed",
                        "cleanup_status": "pending",
                        "stale": True,
                        "stale_reason": "restore_failed",
                        "snapshots": {
                            str(auth_path): {
                                "exists": False,
                                "sha256": None,
                                "content_b64": None,
                            },
                            str(escape_path): {
                                "exists": True,
                                "sha256": sha256(b"escape").hexdigest(),
                                "content_b64": "ZXNjYXBl",
                            },
                        },
                        "written_states": {
                            str(auth_path): {"exists": True, "sha256": sha256(auth_path.read_bytes()).hexdigest()},
                            str(escape_path): {"exists": True, "sha256": sha256(escape_path.read_bytes()).hexdigest()},
                        },
                        "restore_groups": [[str(auth_path)], [str(escape_path)]],
                        "ephemeral_paths": [],
                    },
                )
                with self.assertRaises(SystemExit):
                    ccsw.cmd_repair(ccsw.load_store(), "codex")
                remaining = ccsw.get_managed_target("codex")

            self.assertEqual(escape_path.read_text(encoding="utf-8"), "leave-me-alone")
            self.assertEqual(remaining["stale_reason"], "manifest_decode_failed")
            self.assertIn("manifest path validation failed", remaining["restore_error"])

    def test_batch_restore_failed_does_not_claim_restored_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {"claude": "original-claude", "codex": None, "gemini": None, "opencode": None, "openclaw": None},
                "aliases": {},
                "providers": {
                    "demo": {
                        "claude": {"base_url": "https://example.com", "token": "a", "extra_env": {}},
                        "codex": {"base_url": "https://example.com/v1", "token": "b"},
                    },
                    "original-claude": {
                        "claude": {"base_url": "https://original.example", "token": "o", "extra_env": {}},
                    },
                },
                "profiles": {},
                "settings": {},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.save_store(store)
                with patch(
                    "ccsw.activate_tool_for_subprocess",
                    side_effect=[({"A": "1"}, []), SystemExit(1)],
                ), patch(
                    "ccsw._restore_owned_path_state",
                    side_effect=OSError("restore exploded"),
                ):
                    with self.assertRaises(SystemExit):
                        ccsw.cmd_switch(ccsw.load_store(), "all", "demo")
                history = ccsw.list_history(limit=5)

        batch_entry = next(entry for entry in history if entry["action"] == "batch-result")
        self.assertEqual(batch_entry["payload"]["rollback_status"], "restore_failed")
        self.assertEqual(batch_entry["payload"]["restored_tools"], [])

    def test_doctor_handles_malformed_managed_target_json_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            codex_dir = root / ".codex"
            codex_dir.mkdir()
            store = {
                "version": 2,
                "active": {"claude": None, "codex": "demo", "gemini": None, "opencode": None, "openclaw": None},
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example/v1",
                            "token": ccsw.env_ref("DEMO_CODEX_TOKEN"),
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch.dict(
                os.environ,
                {"DEMO_CODEX_TOKEN": "demo-token"},
                clear=False,
            ), patch(
                "ccsw._probe_codex_target",
                return_value=("ok", {"reason_code": "models_ready", "checks": {}, "mismatch_fields": []}),
            ):
                ccsw.save_store(store)
                conn = sqlite3.connect(db_path)
                try:
                    conn.execute(
                        "INSERT INTO managed_targets(tool, target_json) VALUES (?, ?)",
                        ("codex", "{bad-json"),
                    )
                    conn.commit()
                finally:
                    conn.close()
                status, detail = ccsw._probe_tool_health(
                    ccsw.load_store(),
                    "codex",
                    "demo",
                    store["providers"]["demo"]["codex"],
                )

            self.assertEqual(status, "degraded")
            self.assertEqual(detail["checks"]["runtime_lease_check"]["reason_code"], "manifest_decode_failed")

    def test_doctor_lease_target_unknown_does_not_degrade_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            codex_dir = root / ".codex"
            codex_dir.mkdir()
            store = {
                "version": 2,
                "active": {"claude": None, "codex": "demo", "gemini": None, "opencode": None, "openclaw": None},
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example/v1",
                            "token": ccsw.env_ref("DEMO_CODEX_TOKEN"),
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch.dict(
                os.environ,
                {"DEMO_CODEX_TOKEN": "demo-token"},
                clear=False,
            ), patch(
                "ccsw._probe_codex_target",
                return_value=("ok", {"reason_code": "models_ready", "checks": {}, "mismatch_fields": []}),
            ):
                ccsw.save_store(store)
                ccsw.upsert_managed_target(
                    "codex",
                    {
                        "tool": "codex",
                        "lease_id": "lease-unknown-target",
                        "phase": "completed",
                        "restore_status": "restored",
                        "cleanup_status": "cleaned",
                        "stale": False,
                    },
                )
                status, detail = ccsw._probe_tool_health(
                    ccsw.load_store(),
                    "codex",
                    "demo",
                    store["providers"]["demo"]["codex"],
                )

            self.assertEqual(status, "ok")
            self.assertEqual(detail["checks"]["runtime_lease_check"]["reason_code"], "lease_target_unknown")

    def test_doctor_invalid_runtime_phase_degrades_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            codex_dir = root / ".codex"
            codex_dir.mkdir()
            store = {
                "version": 2,
                "active": {"claude": None, "codex": "demo", "gemini": None, "opencode": None, "openclaw": None},
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example/v1",
                            "token": ccsw.env_ref("DEMO_CODEX_TOKEN"),
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch.dict(
                os.environ,
                {"DEMO_CODEX_TOKEN": "demo-token"},
                clear=False,
            ), patch(
                "ccsw._probe_codex_target",
                return_value=("ok", {"reason_code": "models_ready", "checks": {}, "mismatch_fields": []}),
            ):
                ccsw.save_store(store)
                ccsw.upsert_managed_target(
                    "codex",
                    {
                        "tool": "codex",
                        "lease_id": "lease-invalid-phase",
                        "requested_target": "demo",
                        "selected_candidate": "demo",
                        "phase": "mystery-phase",
                        "restore_status": "restored",
                        "cleanup_status": "cleaned",
                        "stale": False,
                    },
                )
                status, detail = ccsw._probe_tool_health(
                    ccsw.load_store(),
                    "codex",
                    "demo",
                    store["providers"]["demo"]["codex"],
                )

            self.assertEqual(status, "degraded")
            self.assertEqual(detail["checks"]["runtime_lease_check"]["reason_code"], "invalid_phase")

    def test_local_restore_validation_for_codex_uses_selected_base_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            (codex_dir / "auth.json").write_text(
                json.dumps({"OPENAI_API_KEY": "demo-token"}),
                encoding="utf-8",
            )
            (codex_dir / "config.toml").write_text(
                "\n".join(
                    [
                        'model_provider = "ccswitch_active"',
                        "",
                        "[model_providers.ccswitch_active]",
                        'name = "ccswitch: demo"',
                        'base_url = "https://fallback.example/v1"',
                        'env_key = "OPENAI_API_KEY"',
                        "supports_websockets = false",
                        'wire_api = "responses"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://primary.example/v1",
                            "fallback_base_url": "https://fallback.example/v1",
                            "token": "demo-token",
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            validation = ccsw._safe_local_restore_validation(store, "codex", "demo")

        self.assertEqual(validation["status"], "ok")
        self.assertEqual(validation["reason_code"], "ready")

    def test_local_restore_validation_for_codex_chatgpt_mode_uses_auth_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            (codex_dir / "auth.json").write_text(
                json.dumps({"auth_mode": "chatgpt", "chatgpt_session": {"access_token": "demo"}}),
                encoding="utf-8",
            )
            (codex_dir / "config.toml").write_text(
                'model_provider = "openai"\n',
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "pro": {
                        "codex": {
                            "auth_mode": "chatgpt",
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            validation = ccsw._safe_local_restore_validation(store, "codex", "pro")

        self.assertEqual(validation["status"], "ok")
        self.assertEqual(validation["reason_code"], "ready")

    def test_local_restore_validation_for_codex_chatgpt_sync_mode_checks_shared_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            (codex_dir / "auth.json").write_text(
                json.dumps({"auth_mode": "chatgpt", "chatgpt_session": {"access_token": "demo"}}),
                encoding="utf-8",
            )
            (codex_dir / "config.toml").write_text(
                "\n".join(
                    [
                        'model_provider = "ccswitch_active"',
                        "",
                        "[model_providers.ccswitch_active]",
                        "requires_openai_auth = true",
                        "supports_websockets = true",
                        'wire_api = "responses"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "pro": {
                        "codex": {
                            "auth_mode": "chatgpt",
                        }
                    }
                },
                "profiles": {},
                "settings": {
                    "codex_config_dir": str(codex_dir),
                    ccsw.CODEX_SYNC_SETTING_KEY: True,
                },
            }

            validation = ccsw._safe_local_restore_validation(store, "codex", "pro")

        self.assertEqual(validation["status"], "ok")
        self.assertEqual(validation["reason_code"], "ready")

    def test_claude_restore_validation_without_base_url_is_not_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claude_dir = root / ".claude"
            claude_dir.mkdir(parents=True)
            (claude_dir / "settings.json").write_text(
                json.dumps({"env": {"ANTHROPIC_AUTH_TOKEN": "demo-token"}}),
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "demo": {
                        "claude": {
                            "token": "demo-token",
                            "extra_env": {},
                        }
                    }
                },
                "profiles": {},
                "settings": {"claude_config_dir": str(claude_dir)},
            }

            validation = ccsw._safe_local_restore_validation(store, "claude", "demo")

        self.assertEqual(validation["status"], "ok")
        self.assertEqual(validation["reason_code"], "ready")

    def test_doctor_all_history_is_audit_only_even_with_inactive_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {
                    "claude": None,
                    "codex": "demo",
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {"demo": {"codex": {"base_url": "https://relay.example/v1", "token": "t"}}},
                "profiles": {},
                "settings": {},
            }

            output = StringIO()
            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.record_probe_result("codex", "demo", "ok", {"reason_code": "models_ready"})
                with redirect_stdout(output):
                    ok = ccsw.cmd_doctor(store, "all", None, json_output=True, show_history=True, history_limit=5)

        self.assertTrue(ok)
        payloads = [json.loads(line) for line in output.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(payloads), len(ccsw.ALL_TOOLS))
        self.assertTrue(all(payload["status"] == "history" for payload in payloads))

    def test_switch_all_snapshot_failure_does_not_emit_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {"base_url": "https://example.com/v1", "token": "b"},
                        "gemini": {"api_key": "g"},
                    },
                },
                "profiles": {},
                "settings": {},
            }
            stdout = StringIO()

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), redirect_stdout(stdout):
                ccsw.save_store(store)
                with patch(
                    "ccsw.activate_tool_for_subprocess",
                    side_effect=[({"OPENAI_API_KEY": "b"}, ["OPENAI_BASE_URL"]), ({"GEMINI_API_KEY": "g"}, [])],
                ), patch("ccsw._save_snapshot_json", side_effect=OSError("snapshot failed")):
                    with self.assertRaises(SystemExit):
                        ccsw.cmd_switch(ccsw.load_store(), "all", "demo")

        self.assertEqual(stdout.getvalue(), "")

    def test_batch_restore_conflict_keeps_original_active_state_in_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {
                    "claude": "original-claude",
                    "codex": "original-codex",
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {
                        "claude": {"base_url": "https://example.com", "token": "a", "extra_env": {}},
                        "codex": {"base_url": "https://example.com/v1", "token": "b"},
                    },
                    "original-claude": {
                        "claude": {"base_url": "https://original.example", "token": "o", "extra_env": {}},
                    },
                    "original-codex": {
                        "codex": {"base_url": "https://original.example/v1", "token": "p"},
                    },
                },
                "profiles": {},
                "settings": {},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.save_store(store)
                with patch(
                    "ccsw.activate_tool_for_subprocess",
                    side_effect=[({"A": "1"}, []), SystemExit(1)],
                ), patch("ccsw._restore_owned_path_state", return_value=["/tmp/conflict"]), patch(
                    "ccsw._safe_local_restore_validation",
                    return_value={"status": "ok", "reason_code": "ready"},
                ):
                    with self.assertRaises(SystemExit):
                        ccsw.cmd_switch(ccsw.load_store(), "all", "demo")
                reloaded = ccsw.load_store()
                history = ccsw.list_history(limit=5)

        self.assertEqual(reloaded["active"]["claude"], "original-claude")
        self.assertEqual(reloaded["active"]["codex"], "original-codex")
        batch_entry = next(entry for entry in history if entry["action"] == "batch-result")
        self.assertEqual(batch_entry["payload"]["rollback_status"], "restore_conflict")
        self.assertIn("changed_tools", batch_entry["payload"])
        self.assertIn("noop_tools", batch_entry["payload"])
        self.assertIn("post_restore_validation", batch_entry["payload"])

    def test_batch_failure_does_not_overlap_changed_tools_and_noop_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {
                    "claude": "demo",
                    "codex": "original-codex",
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {
                        "claude": {"base_url": "https://example.com", "token": "a", "extra_env": {}},
                        "codex": {"base_url": "https://example.com/v1", "token": "b"},
                    },
                    "original-codex": {
                        "codex": {"base_url": "https://original.example/v1", "token": "p"},
                    },
                },
                "profiles": {},
                "settings": {},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.save_store(store)
                with patch(
                    "ccsw.activate_tool_for_subprocess",
                    side_effect=[({"A": "1"}, []), SystemExit(1)],
                ), patch("ccsw._restore_owned_path_state", return_value=[]), patch(
                    "ccsw._safe_local_restore_validation",
                    return_value={"status": "ok", "reason_code": "ready"},
                ):
                    with self.assertRaises(SystemExit):
                        ccsw.cmd_switch(ccsw.load_store(), "all", "demo")
                history = ccsw.list_history(limit=5)

        batch_entry = next(entry for entry in history if entry["action"] == "batch-result")
        changed_tools = set(batch_entry["payload"]["changed_tools"])
        noop_tools = set(batch_entry["payload"]["noop_tools"])
        self.assertTrue(changed_tools.isdisjoint(noop_tools))

    def test_rollback_rejects_live_drift_and_records_result(self) -> None:
        store = {
            "version": 2,
            "active": {"claude": None, "codex": "current-live", "gemini": None, "opencode": None, "openclaw": None},
            "aliases": {},
            "providers": {
                "valid-provider": {
                    "codex": {"base_url": "https://valid.example/v1", "token": "token"}
                },
                "current-live": {
                    "codex": {"base_url": "https://current.example/v1", "token": "current-token"}
                },
            },
            "profiles": {},
            "settings": {},
        }
        entries = [
            {
                "recorded_at": "2026-04-13T19:00:00",
                "action": "switch",
                "tool": "codex",
                "subject": "current-live",
                "payload": {"previous": "valid-provider", "current": "current-live"},
            },
        ]

        with patch("ccsw.list_history", return_value=entries), patch(
            "ccsw._safe_local_restore_validation",
            return_value={"status": "degraded", "reason_code": "live_config_mismatch"},
        ), patch("ccsw.record_history") as record_history:
            with self.assertRaises(SystemExit):
                ccsw.cmd_rollback(store, "codex")

        payload = record_history.call_args.args[3]
        self.assertEqual(payload["rollback_status"], "live_drift")
        self.assertEqual(payload["target_provider"], None)
        self.assertEqual(payload["target_validation"]["status"], "skipped")
        self.assertEqual(payload["snapshot_sync"], "ok")

    def test_rollback_rejects_failed_pre_validation_and_records_live_drift(self) -> None:
        store = {
            "version": 2,
            "active": {"claude": None, "codex": "current-live", "gemini": None, "opencode": None, "openclaw": None},
            "aliases": {},
            "providers": {
                "valid-provider": {
                    "codex": {"base_url": "https://valid.example/v1", "token": "token"}
                },
                "current-live": {
                    "codex": {"base_url": "https://current.example/v1", "token": "current-token"}
                },
            },
            "profiles": {},
            "settings": {},
        }
        entries = [
            {
                "recorded_at": "2026-04-13T19:00:00",
                "action": "switch",
                "tool": "codex",
                "subject": "current-live",
                "payload": {"previous": "valid-provider", "current": "current-live"},
            },
        ]

        with patch("ccsw.list_history", return_value=entries), patch(
            "ccsw._safe_local_restore_validation",
            return_value={"status": "failed", "reason_code": "validation_error"},
        ), patch("ccsw.record_history") as record_history:
            with self.assertRaises(SystemExit):
                ccsw.cmd_rollback(store, "codex")

        payload = record_history.call_args.args[3]
        self.assertEqual(payload["rollback_status"], "live_drift")
        self.assertEqual(payload["post_restore_validation"]["status"], "failed")
        self.assertEqual(payload["target_validation"]["status"], "skipped")
        self.assertEqual(record_history.call_args.args[2], "current-live")
        self.assertEqual(payload["subject_kind"], "active_before")

    def test_rollback_snapshot_failure_updates_existing_history_entry_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            store = {
                "version": 2,
                "active": {"claude": None, "codex": "current-live", "gemini": None, "opencode": None, "openclaw": None},
                "aliases": {},
                "providers": {
                    "valid-provider": {
                        "codex": {"base_url": "https://valid.example/v1", "token": "token"}
                    },
                    "current-live": {
                        "codex": {"base_url": "https://current.example/v1", "token": "current-token"}
                    },
                },
                "profiles": {},
                "settings": {},
            }
            entries = [
                {
                    "recorded_at": "2026-04-13T19:00:00",
                    "action": "switch",
                    "tool": "codex",
                    "subject": "current-live",
                    "payload": {"previous": "valid-provider", "current": "current-live"},
                },
            ]

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path):
                ccsw.save_store(store)
                with patch("ccsw.list_history", return_value=entries), patch(
                    "ccsw._safe_local_restore_validation",
                    side_effect=[
                        {"status": "ok", "reason_code": "ready"},
                        {"status": "ok", "reason_code": "ready"},
                    ],
                ), patch(
                    "ccsw.activate_tool_for_subprocess",
                    return_value=({}, []),
                ), patch(
                    "ccsw._activation_target_paths",
                    return_value=[],
                ), patch(
                    "ccsw._save_snapshot_json",
                    side_effect=OSError("snapshot failed"),
                ):
                    with self.assertRaises(SystemExit):
                        ccsw.cmd_rollback(ccsw.load_store(), "codex")

                rollback_entries = ccsw.list_history(limit=10, action="rollback-result")

        self.assertEqual(len(rollback_entries), 1)
        self.assertEqual(rollback_entries[0]["payload"]["rollback_status"], "snapshot_degraded")
        self.assertEqual(rollback_entries[0]["payload"]["snapshot_sync"], "degraded")

    def test_run_openclaw_runtime_overlay_does_not_touch_persistent_generated_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            persistent_overlay = generated_dir / "openclaw" / "demo.json5"
            persistent_overlay.parent.mkdir(parents=True)
            persistent_overlay.write_text('{"persistent": true}\n', encoding="utf-8")
            persistent_hash = sha256(persistent_overlay.read_bytes()).hexdigest()
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "demo": {
                        "openclaw": {
                            "base_url": "https://relay.example.com/v1",
                            "token": "demo-token",
                        }
                    }
                },
                "profiles": {},
                "settings": {"openclaw_config_dir": str(root / "openclaw-home")},
            }
            captured_env: dict[str, str] = {}

            def _run(*_args, **kwargs):
                captured_env.update(kwargs["env"])
                return subprocess.CompletedProcess(["openclaw", "run"], 0, "ok", "")

            with patch.object(ccsw, "GENERATED_DIR", generated_dir), patch(
                "ccsw.subprocess.run", side_effect=_run
            ):
                result = ccsw.run_with_fallback(store, "openclaw", "demo", ["openclaw", "run"])
            self.assertEqual(result.returncode, 0)
            self.assertEqual(sha256(persistent_overlay.read_bytes()).hexdigest(), persistent_hash)
            self.assertIn("OPENCLAW_CONFIG_PATH", captured_env)
            self.assertNotEqual(captured_env["OPENCLAW_CONFIG_PATH"], str(persistent_overlay))

    def test_run_openclaw_runtime_overlay_mutation_does_not_trigger_restore_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {
                    "demo": {
                        "openclaw": {
                            "base_url": "https://relay.example.com/v1",
                            "token": "demo-token",
                        }
                    }
                },
                "profiles": {},
                "settings": {"openclaw_config_dir": str(root / "openclaw-home")},
            }

            def _run(*_args, **kwargs):
                runtime_overlay = Path(kwargs["env"]["OPENCLAW_CONFIG_PATH"])
                runtime_overlay.write_text('{"mutated": true}\n', encoding="utf-8")
                return subprocess.CompletedProcess(["openclaw", "run"], 0, "ok", "")

            with patch.object(ccsw, "GENERATED_DIR", generated_dir), patch(
                "ccsw.subprocess.run", side_effect=_run
            ):
                result = ccsw.run_with_fallback(store, "openclaw", "demo", ["openclaw", "run"])
            self.assertEqual(result.returncode, 0)
            self.assertEqual(getattr(result, "_ccsw_restore_status"), "restored")
            self.assertEqual(getattr(result, "_ccsw_restore_conflicts"), [])

    def test_repair_restores_from_manifest_and_clears_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            config_path = codex_dir / "config.toml"
            original_bytes = json.dumps({"OPENAI_API_KEY": "original"}).encode("utf-8")
            mutated_bytes = json.dumps({"OPENAI_API_KEY": "mutated"}).encode("utf-8")
            auth_path.write_text(mutated_bytes.decode("utf-8"), encoding="utf-8")
            config_path.write_text(
                "\n".join(
                    [
                        'model_provider = "ccswitch_active"',
                        "",
                        "[model_providers.ccswitch_active]",
                        'name = "ccswitch: demo"',
                        'base_url = "https://relay.example.com/v1"',
                        'env_key = "OPENAI_API_KEY"',
                        "supports_websockets = false",
                        'wire_api = "responses"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            runtime_root = root / "tmp" / "run-codex"
            runtime_root.mkdir(parents=True)
            store = {
                "version": 2,
                "active": {
                    "claude": None,
                    "codex": "demo",
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example.com/v1",
                            "token": "demo-token",
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch.object(
                ccsw, "TMP_DIR", root / "tmp"
            ), patch(
                "ccsw._safe_local_restore_validation",
                return_value={"status": "ok", "reason_code": "ready"},
            ):
                ccsw.save_store(store)
                ccsw.upsert_managed_target(
                    "codex",
                    {
                        "tool": "codex",
                        "lease_id": "lease-repair",
                        "requested_target": "demo",
                        "selected_candidate": "demo",
                        "owner_pid": os.getpid(),
                        "child_pid": None,
                        "child_status": "exited",
                        "phase": "completed",
                        "runtime_root": str(runtime_root),
                        "restore_status": "restore_failed",
                        "cleanup_status": "pending",
                        "stale": True,
                        "stale_reason": "restore_failed",
                        "snapshots": {
                            str(auth_path): {
                                "exists": True,
                                "sha256": sha256(original_bytes).hexdigest(),
                                "content_b64": "eyJPUEVOQUlfQVBJX0tFWSI6ICJvcmlnaW5hbCJ9",
                            }
                        },
                        "written_states": {
                            str(auth_path): {
                                "exists": True,
                                "sha256": sha256(mutated_bytes).hexdigest(),
                            }
                        },
                        "restore_groups": [[str(auth_path)]],
                        "ephemeral_paths": [],
                        "post_restore_validation": {"status": "pending", "reason_code": "pending"},
                    },
                )
                ccsw.cmd_repair(ccsw.load_store(), "codex")
                repaired = json.loads(auth_path.read_text(encoding="utf-8"))
                remaining = ccsw.get_managed_target("codex")
                history = ccsw.list_history(limit=5)

        self.assertEqual(repaired["OPENAI_API_KEY"], "original")
        self.assertIsNone(remaining)
        repair_entry = next(entry for entry in history if entry["action"] == "repair-result")
        self.assertEqual(repair_entry["payload"]["repair_status"], "repaired")

    def test_repair_restores_from_snapshot_file_manifest_and_clears_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            original_bytes = json.dumps({"OPENAI_API_KEY": "original"}).encode("utf-8")
            mutated_bytes = json.dumps({"OPENAI_API_KEY": "mutated"}).encode("utf-8")
            auth_path.write_text(mutated_bytes.decode("utf-8"), encoding="utf-8")
            runtime_root = root / "tmp" / "run-codex"
            snapshot_dir = runtime_root / "snapshots"
            snapshot_dir.mkdir(parents=True)
            snapshot_file = snapshot_dir / "auth.json.b64"
            snapshot_file.write_text(base64.b64encode(original_bytes).decode("ascii"), encoding="utf-8")
            store = {
                "version": 2,
                "active": {
                    "claude": None,
                    "codex": "demo",
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {
                    "demo": {
                        "codex": {
                            "base_url": "https://relay.example.com/v1",
                            "token": "demo-token",
                        }
                    }
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch.object(
                ccsw, "TMP_DIR", root / "tmp"
            ), patch(
                "ccsw._safe_local_restore_validation",
                return_value={"status": "ok", "reason_code": "ready"},
            ):
                ccsw.save_store(store)
                ccsw.upsert_managed_target(
                    "codex",
                    {
                        "tool": "codex",
                        "lease_id": "lease-repair-file",
                        "requested_target": "demo",
                        "selected_candidate": "demo",
                        "owner_pid": os.getpid(),
                        "child_pid": None,
                        "child_status": "exited",
                        "phase": "completed",
                        "runtime_root": str(runtime_root),
                        "restore_status": "restore_failed",
                        "cleanup_status": "pending",
                        "stale": True,
                        "stale_reason": "restore_failed",
                        "snapshots": {
                            str(auth_path): {
                                "exists": True,
                                "sha256": sha256(original_bytes).hexdigest(),
                                "snapshot_file": str(snapshot_file),
                            }
                        },
                        "written_states": {
                            str(auth_path): {
                                "exists": True,
                                "sha256": sha256(mutated_bytes).hexdigest(),
                            }
                        },
                        "restore_groups": [[str(auth_path)]],
                        "ephemeral_paths": [],
                        "post_restore_validation": {"status": "pending", "reason_code": "pending"},
                    },
                )
                ccsw.cmd_repair(ccsw.load_store(), "codex")
                repaired = json.loads(auth_path.read_text(encoding="utf-8"))
                remaining = ccsw.get_managed_target("codex")

        self.assertEqual(repaired["OPENAI_API_KEY"], "original")
        self.assertIsNone(remaining)

    def test_repair_inactive_tool_can_clear_lease_after_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "ccswitch.db"
            providers_path = root / "providers.json"
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            original_bytes = json.dumps({"OPENAI_API_KEY": "original"}).encode("utf-8")
            mutated_bytes = json.dumps({"OPENAI_API_KEY": "mutated"}).encode("utf-8")
            auth_path.write_text(mutated_bytes.decode("utf-8"), encoding="utf-8")
            runtime_root = root / "tmp" / "run-codex"
            runtime_root.mkdir(parents=True)
            store = {
                "version": 2,
                "active": {
                    "claude": None,
                    "codex": None,
                    "gemini": None,
                    "opencode": None,
                    "openclaw": None,
                },
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "DB_PATH", db_path
            ), patch.object(ccsw, "PROVIDERS_PATH", providers_path), patch.object(
                ccsw, "TMP_DIR", root / "tmp"
            ):
                ccsw.save_store(store)
                ccsw.upsert_managed_target(
                    "codex",
                    {
                        "tool": "codex",
                        "lease_id": "lease-inactive",
                        "requested_target": "demo",
                        "selected_candidate": "demo",
                        "owner_pid": os.getpid(),
                        "child_pid": None,
                        "child_status": "exited",
                        "phase": "completed",
                        "runtime_root": str(runtime_root),
                        "restore_status": "restore_failed",
                        "cleanup_status": "pending",
                        "stale": True,
                        "stale_reason": "restore_failed",
                        "snapshots": {
                            str(auth_path): {
                                "exists": True,
                                "sha256": sha256(original_bytes).hexdigest(),
                                "content_b64": "eyJPUEVOQUlfQVBJX0tFWSI6ICJvcmlnaW5hbCJ9",
                            }
                        },
                        "written_states": {
                            str(auth_path): {
                                "exists": True,
                                "sha256": sha256(mutated_bytes).hexdigest(),
                            }
                        },
                        "restore_groups": [[str(auth_path)]],
                        "ephemeral_paths": [],
                        "post_restore_validation": {"status": "pending", "reason_code": "pending"},
                    },
                )
                ccsw.cmd_repair(ccsw.load_store(), "codex")
                remaining = ccsw.get_managed_target("codex")
                repaired = json.loads(auth_path.read_text(encoding="utf-8"))

        self.assertIsNone(remaining)
        self.assertEqual(repaired["OPENAI_API_KEY"], "original")


if __name__ == "__main__":
    unittest.main()
