import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ccsw


REPO_ROOT = Path(__file__).resolve().parent.parent


class CodexWebsocketConfigTests(unittest.TestCase):
    def test_third_party_provider_defaults_to_false(self) -> None:
        self.assertFalse(ccsw._codex_supports_websockets({"base_url": "https://relay.example/v1"}))

    def test_chatgpt_future_sync_defaults_to_true(self) -> None:
        store = ccsw._empty_store()
        store["settings"][ccsw.CODEX_SYNC_SETTING_KEY] = True
        self.assertTrue(ccsw._codex_supports_websockets({"auth_mode": "chatgpt"}, store))

    def test_third_party_explicit_true_is_persisted_and_written(self) -> None:
        parser = ccsw.build_parser()
        args = parser.parse_args(
            [
                "add",
                "relay",
                "--codex-url",
                "https://relay.example/v1",
                "--codex-token",
                "$RELAY_TOKEN",
                "--codex-websockets",
                "true",
            ]
        )
        conf = {}
        ccsw._add_from_flags(conf, args)
        self.assertTrue(conf["codex"]["supports_websockets"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            ccsw.upsert_codex_provider_config(
                path,
                "relay",
                "https://relay.example/v1",
                supports_websockets=conf["codex"]["supports_websockets"],
            )
            self.assertIn("supports_websockets = true\n", path.read_text(encoding="utf-8"))

    def test_websocket_only_update_preserves_captured_chatgpt_auth_mode(self) -> None:
        parser = ccsw.build_parser()
        args = parser.parse_args(["add", "pro", "--codex-websockets", "false"])
        conf = {
            "codex": {
                "auth_mode": "chatgpt",
                "account_id": "acct-pro",
            }
        }
        ccsw._add_from_flags(conf, args)
        self.assertEqual(
            conf["codex"],
            {
                "auth_mode": "chatgpt",
                "account_id": "acct-pro",
                "supports_websockets": False,
            },
        )

    def test_cli_websocket_only_update_preserves_chatgpt_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = os.environ.copy()
            env.update(
                {
                    "CCSW_HOME": str(root / ".ccswitch"),
                    "CCSW_FAKE_HOME": str(root / "home"),
                    "CCSW_LOCAL_ENV_PATH": str(root / ".env.local"),
                }
            )
            (root / "home").mkdir()
            (root / ".env.local").write_text("", encoding="utf-8")
            for args in (
                ("add", "pro", "--codex-auth-mode", "chatgpt"),
                ("add", "pro", "--codex-websockets", "false"),
            ):
                subprocess.run(
                    [sys.executable, "ccsw.py", *args],
                    cwd=REPO_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=True,
                )
            providers = json.loads((root / ".ccswitch" / "providers.json").read_text(encoding="utf-8"))
            self.assertEqual(
                providers["providers"]["pro"]["codex"],
                {"auth_mode": "chatgpt", "supports_websockets": False},
            )

    def test_cli_websocket_only_update_preserves_third_party_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = os.environ.copy()
            env.update(
                {
                    "CCSW_HOME": str(root / ".ccswitch"),
                    "CCSW_FAKE_HOME": str(root / "home"),
                    "CCSW_LOCAL_ENV_PATH": str(root / ".env.local"),
                    "RELAY_TOKEN": "relay-token",
                }
            )
            (root / "home").mkdir()
            (root / ".env.local").write_text("", encoding="utf-8")
            for args in (
                ("add", "relay", "--codex-url", "https://relay.example/v1", "--codex-token", "$RELAY_TOKEN"),
                ("add", "relay", "--codex-websockets", "true"),
            ):
                subprocess.run(
                    [sys.executable, "ccsw.py", *args],
                    cwd=REPO_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=10,
                )
            providers = json.loads((root / ".ccswitch" / "providers.json").read_text(encoding="utf-8"))
            self.assertEqual(
                providers["providers"]["relay"]["codex"],
                {
                    "base_url": "https://relay.example/v1",
                    "token": "$RELAY_TOKEN",
                    "supports_websockets": True,
                },
            )

    def test_cli_websocket_only_update_fails_for_fresh_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = os.environ.copy()
            env.update(
                {
                    "CCSW_HOME": str(root / ".ccswitch"),
                    "CCSW_FAKE_HOME": str(root / "home"),
                    "CCSW_LOCAL_ENV_PATH": str(root / ".env.local"),
                }
            )
            (root / "home").mkdir()
            (root / ".env.local").write_text("", encoding="utf-8")
            for value in ("false", "true"):
                result = subprocess.run(
                    [sys.executable, "ccsw.py", "add", f"fresh-{value}", "--codex-websockets", value],
                    cwd=REPO_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("--codex-auth-mode chatgpt", result.stdout + result.stderr)
            self.assertFalse((root / ".ccswitch" / "providers.json").exists())

    def test_chatgpt_explicit_false_is_written_to_shared_lane(self) -> None:
        parser = ccsw.build_parser()
        args = parser.parse_args(
            ["add", "pro", "--codex-auth-mode", "chatgpt", "--codex-websockets", "false"]
        )
        conf = {}
        ccsw._add_from_flags(conf, args)
        self.assertFalse(conf["codex"]["supports_websockets"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            ccsw.upsert_codex_chatgpt_shared_config(
                path, "pro", supports_websockets=conf["codex"]["supports_websockets"]
            )
            self.assertIn("supports_websockets = false\n", path.read_text(encoding="utf-8"))

    def test_provider_switch_keeps_each_persisted_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_home = root / "home"
            codex_dir = fake_home / ".codex"
            codex_dir.mkdir(parents=True)
            (codex_dir / "config.toml").write_text('model = "gpt-5.4"\n', encoding="utf-8")
            env = os.environ.copy()
            env.update(
                {
                    "CCSW_HOME": str(root / ".ccswitch"),
                    "CCSW_FAKE_HOME": str(fake_home),
                    "CCSW_LOCAL_ENV_PATH": str(root / ".env.local"),
                    "ENABLED_TOKEN": "enabled-token",
                    "DISABLED_TOKEN": "disabled-token",
                }
            )
            (root / ".env.local").write_text("", encoding="utf-8")

            def run(*args: str) -> None:
                subprocess.run(
                    [sys.executable, "ccsw.py", *args],
                    cwd=REPO_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=True,
                )

            run(
                "add", "enabled", "--codex-url", "https://enabled.example/v1",
                "--codex-token", "$ENABLED_TOKEN", "--codex-websockets", "true",
            )
            run(
                "add", "disabled", "--codex-url", "https://disabled.example/v1",
                "--codex-token", "$DISABLED_TOKEN", "--codex-websockets", "false",
            )
            run("codex", "enabled")
            self.assertIn("supports_websockets = true\n", (codex_dir / "config.toml").read_text(encoding="utf-8"))
            run("codex", "disabled")
            self.assertIn("supports_websockets = false\n", (codex_dir / "config.toml").read_text(encoding="utf-8"))
            run("codex", "enabled")
            self.assertIn("supports_websockets = true\n", (codex_dir / "config.toml").read_text(encoding="utf-8"))

    def test_import_current_chatgpt_preserves_shared_lane_websocket_setting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auth = root / "auth.json"
            config = root / "config.toml"
            snapshot = root / "pro.json"
            auth.write_text(
                '{"auth_mode": "chatgpt", "tokens": {"access_token": "session", "account_id": "acct-pro"}}',
                encoding="utf-8",
            )
            config.write_text(
                'model_provider = "ccswitch_active"\n\n'
                '[model_providers.ccswitch_active]\n'
                'requires_openai_auth = true\n'
                'supports_websockets = false\n'
                'wire_api = "responses"\n',
                encoding="utf-8",
            )
            store = ccsw._empty_store()
            store["settings"][ccsw.CODEX_SYNC_SETTING_KEY] = True
            paths = {"auth": auth, "config": config}
            with patch.object(ccsw, "get_tool_paths", return_value=paths), patch.object(
                ccsw, "_codex_chatgpt_snapshot_path", return_value=snapshot
            ), patch.object(ccsw, "_load_fresh_store_from_lock", return_value=store), patch.object(
                ccsw, "save_store"
            ):
                ccsw.cmd_import_current(store, "codex", "pro")
            self.assertEqual(
                store["providers"]["pro"]["codex"]["supports_websockets"],
                False,
            )

    def test_import_current_chatgpt_clears_stale_websocket_setting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auth = root / "auth.json"
            config = root / "config.toml"
            snapshot = root / "pro.json"
            auth.write_text(
                '{"auth_mode": "chatgpt", "tokens": {"access_token": "session", "account_id": "acct-pro"}}',
                encoding="utf-8",
            )
            config.write_text('model_provider = "openai"\n', encoding="utf-8")
            store = ccsw._empty_store()
            store["providers"]["pro"] = {
                "codex": {"auth_mode": "chatgpt", "account_id": "acct-pro", "supports_websockets": False}
            }
            paths = {"auth": auth, "config": config}
            with patch.object(ccsw, "get_tool_paths", return_value=paths), patch.object(
                ccsw, "_codex_chatgpt_snapshot_path", return_value=snapshot
            ), patch.object(ccsw, "_load_fresh_store_from_lock", return_value=store), patch.object(
                ccsw, "save_store"
            ):
                ccsw.cmd_import_current(store, "codex", "pro")
            self.assertNotIn("supports_websockets", store["providers"]["pro"]["codex"])

    def test_restore_validation_checks_provider_websocket_value(self) -> None:
        store = ccsw._empty_store()
        store["providers"]["relay"] = {
            "codex": {
                "token": "$RELAY_TOKEN",
                "base_url": "https://relay.example/v1",
                "supports_websockets": True,
            }
        }
        live = {
            "token": "resolved-token",
            "base_url": "https://relay.example/v1",
            "supports_websockets": False,
        }
        with patch.object(ccsw, "_read_current_codex", return_value=live), patch.object(
            ccsw, "resolve_token", return_value="resolved-token"
        ):
            result = ccsw._local_restore_validation(store, "codex", "relay")
        self.assertEqual(result["status"], "degraded")
        self.assertIn("supports_websockets", result["mismatch_fields"])

    def test_restore_validation_checks_chatgpt_shared_lane_websocket_value(self) -> None:
        store = ccsw._empty_store()
        store["providers"]["pro"] = {
            "codex": {"auth_mode": "chatgpt", "supports_websockets": False}
        }
        live = {
            "auth_mode": "chatgpt",
            "provider_route": ccsw.CODEX_PROVIDER_ID,
            "supports_websockets": True,
        }
        with patch.object(ccsw, "_read_current_codex", return_value=live):
            result = ccsw._local_restore_validation(store, "codex", "pro")
        self.assertEqual(result["status"], "degraded")
        self.assertIn("supports_websockets", result["mismatch_fields"])

    def test_explicit_false_uses_shared_lane_even_when_sync_is_off(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir()
            auth_path = codex_dir / "auth.json"
            config_path = codex_dir / "config.toml"
            env_path = root / "codex.env"
            auth_path.write_text(
                '{"auth_mode": "chatgpt", "chatgpt_access_token": "session"}',
                encoding="utf-8",
            )
            config_path.write_text('model_provider = "openai"\n', encoding="utf-8")
            store = ccsw._empty_store()
            store["settings"]["codex_config_dir"] = str(codex_dir)
            store["settings"][ccsw.CODEX_SYNC_SETTING_KEY] = False
            conf = {"auth_mode": "chatgpt", "supports_websockets": False}
            self.assertEqual(
                ccsw._codex_chatgpt_provider_route(store, conf),
                ccsw.CODEX_PROVIDER_ID,
            )
            with patch.object(ccsw, "CODEX_ENV_PATH", env_path):
                ccsw.write_codex(conf, "pro", store)
            content = config_path.read_text(encoding="utf-8")
            self.assertIn('model_provider = "ccswitch_active"\n', content)
            self.assertIn("supports_websockets = false\n", content)

    def test_doctor_uses_provider_specific_websocket_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auth = root / "auth.json"
            config = root / "config.toml"
            auth.write_text('{"auth_mode": "chatgpt", "chatgpt_access_token": "session"}', encoding="utf-8")
            config.write_text(
                'model_provider = "ccswitch_active"\n\n'
                '[model_providers.ccswitch_active]\n'
                'requires_openai_auth = true\n'
                'supports_websockets = false\n'
                'wire_api = "responses"\n',
                encoding="utf-8",
            )
            store = ccsw._empty_store()
            store["settings"][ccsw.CODEX_SYNC_SETTING_KEY] = True
            store["providers"]["pro"] = {"codex": {"auth_mode": "chatgpt", "supports_websockets": False}}
            paths = {"auth": auth, "config": config}
            with patch.object(ccsw, "get_tool_paths", return_value=paths), patch.object(
                ccsw, "_codex_chatgpt_snapshot_exists", return_value=True
            ):
                status, detail = ccsw._probe_codex_target(store, store["providers"]["pro"]["codex"], "pro")
            self.assertEqual(status, "ok")
            self.assertEqual(detail["config_checks"]["expected_supports_websockets"], False)


if __name__ == "__main__":
    unittest.main()
