import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

import ccsw


REPO_ROOT = Path(__file__).resolve().parent.parent


class UpsertRootTomlStringTests(unittest.TestCase):
    def test_inserts_before_first_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                '# comment\nmodel = "gpt-5.4"\n\n[projects."/tmp"]\ntrust_level = "trusted"\n',
                encoding="utf-8",
            )

            ccsw.upsert_root_toml_string(path, "openai_base_url", "https://example.com/v1")

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                '# comment\nmodel = "gpt-5.4"\n\nopenai_base_url = "https://example.com/v1"\n\n[projects."/tmp"]\ntrust_level = "trusted"\n',
            )

    def test_updates_existing_root_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                'model = "gpt-5.4"\nopenai_base_url = "https://old.example/v1"\n\n[projects."/tmp"]\ntrust_level = "trusted"\n',
                encoding="utf-8",
            )

            ccsw.upsert_root_toml_string(path, "openai_base_url", "https://new.example/v1")

            self.assertIn(
                'openai_base_url = "https://new.example/v1"\n',
                path.read_text(encoding="utf-8"),
            )

    def test_ignores_multiline_string_content_when_finding_first_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                'notes = """\n[not.a.table]\n"""\n\n[projects."/tmp"]\ntrust_level = "trusted"\n',
                encoding="utf-8",
            )

            ccsw.upsert_root_toml_string(path, "openai_base_url", "https://example.com/v1")

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                'notes = """\n[not.a.table]\n"""\n\nopenai_base_url = "https://example.com/v1"\n\n[projects."/tmp"]\ntrust_level = "trusted"\n',
            )

    def test_remove_root_key_preserves_other_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                'model = "gpt-5.4"\nopenai_base_url = "https://old.example/v1"\n\n[projects."/tmp"]\ntrust_level = "trusted"\n',
                encoding="utf-8",
            )

            ccsw.remove_root_toml_key(path, "openai_base_url")

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                'model = "gpt-5.4"\n\n[projects."/tmp"]\ntrust_level = "trusted"\n',
            )

    def test_upsert_codex_provider_config_replaces_legacy_base_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                'model = "gpt-5.4"\nopenai_base_url = "https://old.example/v1"\n\n[projects."/tmp"]\ntrust_level = "trusted"\n',
                encoding="utf-8",
            )

            ccsw.upsert_codex_provider_config(path, "provider-a", "https://relay-alpha.example/openai/v1")

            content = path.read_text(encoding="utf-8")
            self.assertIn('model_provider = "ccswitch_active"\n', content)
            self.assertNotIn('openai_base_url = "https://old.example/v1"\n', content)
            self.assertIn('[model_providers.ccswitch_active]\n', content)
            self.assertIn('name = "ccswitch: provider-a"\n', content)
            self.assertIn('base_url = "https://relay-alpha.example/openai/v1"\n', content)
            self.assertIn('env_key = "OPENAI_API_KEY"\n', content)
            self.assertIn('supports_websockets = false\n', content)
            self.assertIn('wire_api = "responses"\n', content)
            self.assertIn('[projects."/tmp"]\ntrust_level = "trusted"\n', content)

    def test_upsert_codex_provider_config_replaces_existing_custom_provider_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                'model = "gpt-5.4"\nmodel_provider = "ccswitch_active"\n\n[model_providers.ccswitch_active]\nname = "ccswitch: old"\nbase_url = "https://old.example/v1"\nenv_key = "OPENAI_API_KEY"\nsupports_websockets = false\nwire_api = "responses"\n\n[projects."/tmp"]\ntrust_level = "trusted"\n',
                encoding="utf-8",
            )

            ccsw.upsert_codex_provider_config(path, "provider-b", "https://relay-beta.example/codex/v1")

            content = path.read_text(encoding="utf-8")
            self.assertEqual(content.count("[model_providers.ccswitch_active]\n"), 1)
            self.assertIn('name = "ccswitch: provider-b"\n', content)
            self.assertIn('base_url = "https://relay-beta.example/codex/v1"\n', content)
            self.assertNotIn('base_url = "https://old.example/v1"\n', content)

    def test_upsert_codex_chatgpt_config_reverts_to_builtin_openai_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                'model = "gpt-5.4"\nopenai_base_url = "https://old.example/v1"\nmodel_provider = "ccswitch_active"\n\n[model_providers.ccswitch_active]\nname = "ccswitch: old"\nbase_url = "https://old.example/v1"\nenv_key = "OPENAI_API_KEY"\nsupports_websockets = false\nwire_api = "responses"\n\n[projects."/tmp"]\ntrust_level = "trusted"\n',
                encoding="utf-8",
            )

            ccsw.upsert_codex_chatgpt_config(path)

            content = path.read_text(encoding="utf-8")
            self.assertIn('model_provider = "openai"\n', content)
            self.assertNotIn('openai_base_url = "https://old.example/v1"\n', content)
            self.assertNotIn("[model_providers.ccswitch_active]\n", content)
            self.assertIn('[projects."/tmp"]\ntrust_level = "trusted"\n', content)

    def test_upsert_codex_chatgpt_shared_config_uses_requires_openai_auth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                'model = "gpt-5.4"\nopenai_base_url = "https://old.example/v1"\nmodel_provider = "openai"\n',
                encoding="utf-8",
            )

            ccsw.upsert_codex_chatgpt_shared_config(path, "pro")

            content = path.read_text(encoding="utf-8")
            self.assertIn('model_provider = "ccswitch_active"\n', content)
            self.assertIn('[model_providers.ccswitch_active]\n', content)
            self.assertIn('name = "ccswitch: pro"\n', content)
            self.assertIn("requires_openai_auth = true\n", content)
            self.assertIn("supports_websockets = true\n", content)
            self.assertIn('wire_api = "responses"\n', content)
            self.assertNotIn("openai_base_url", content)
            self.assertNotIn('env_key = "OPENAI_API_KEY"\n', content)


class CodexBaseUrlSelectionTests(unittest.TestCase):
    def test_prefers_primary_base_url_when_primary_is_available(self) -> None:
        conf = {
            "base_url": "https://relay-primary.example/v1",
            "fallback_base_url": "https://relay-backup.example/v1",
        }

        with patch("ccsw.probe_codex_base_url", return_value=True) as probe:
            selected = ccsw.select_codex_base_url(conf)

        self.assertEqual(selected, "https://relay-primary.example/v1")
        probe.assert_called_once_with("https://relay-primary.example/v1")

    def test_uses_fallback_base_url_when_primary_is_unavailable(self) -> None:
        conf = {
            "base_url": "https://relay-primary.example/v1",
            "fallback_base_url": "https://relay-backup.example/v1",
        }

        with patch("ccsw.probe_codex_base_url", side_effect=[False, True]) as probe:
            selected = ccsw.select_codex_base_url(conf)

        self.assertEqual(selected, "https://relay-backup.example/v1")
        self.assertEqual(
            probe.call_args_list,
            [
                call("https://relay-primary.example/v1"),
                call("https://relay-backup.example/v1"),
            ],
        )


class CodexDoctorProbeTests(unittest.TestCase):
    def test_probe_codex_target_chatgpt_mode_uses_local_config_checks_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            (codex_dir / "auth.json").write_text(
                json.dumps({"auth_mode": "chatgpt", "chatgpt_access_token": "demo"}),
                encoding="utf-8",
            )
            (codex_dir / "config.toml").write_text(
                'model = "gpt-5.4"\nmodel_provider = "openai"\n',
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
            conf = {
                "auth_mode": "chatgpt",
            }

            with patch("ccsw._http_probe") as http_probe:
                status, detail = ccsw._probe_codex_target(store, conf, "pro", deep=True)

        self.assertEqual(status, "ok")
        self.assertEqual(detail["reason_code"], "ready")
        self.assertEqual(detail["config_checks"]["model_provider"], "openai")
        self.assertFalse(detail["config_checks"]["auth_has_openai_api_key"])
        http_probe.assert_not_called()

    def test_probe_codex_target_deep_discovers_model_from_models_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            config_path = codex_dir / "config.toml"
            auth_path.write_text(json.dumps({"OPENAI_API_KEY": "demo-token"}), encoding="utf-8")
            config_path.write_text(
                '\n'.join(
                    [
                        'model = "gpt-5.4"',
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
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }
            conf = {
                "base_url": "https://relay.example.com/v1",
                "token": "demo-token",
            }

            with patch("ccsw._http_probe") as http_probe:
                http_probe.side_effect = [
                    (
                        200,
                        {
                            "status": 200,
                            "sample": json.dumps({"data": [{"id": "gpt-5.4"}, {"id": "gpt-4.1"}]}),
                        },
                    ),
                    (
                        200,
                        {
                            "status": 200,
                            "sample": json.dumps({"data": []}),
                        },
                    ),
                    (
                        200,
                        {
                            "status": 200,
                            "sample": json.dumps({"id": "resp_123"}),
                        },
                    ),
                ]
                status, detail = ccsw._probe_codex_target(store, conf, "demo", deep=True)

        self.assertEqual(status, "ok")
        self.assertEqual(detail["deep_probe"]["model"], "gpt-5.4")
        self.assertEqual(detail["deep_probe"]["reason_code"], "responses_ready")

    def test_probe_codex_target_reports_separate_primary_and_fallback_checks(self) -> None:
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
                        "[model_providers.ccswitch_active]",
                        'name = "ccswitch: demo"',
                        'base_url = "https://backup.example.com/v1"',
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
                "providers": {},
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }
            conf = {
                "base_url": "https://primary.example.com/v1",
                "fallback_base_url": "https://backup.example.com/v1",
                "token": "demo-token",
            }

            with patch("ccsw._http_probe") as http_probe, patch(
                "ccsw.select_codex_base_url",
                return_value="https://backup.example.com/v1",
            ):
                http_probe.side_effect = [
                    (404, {"status": 404, "sample": '{"error":"no models"}'}),
                    (200, {"status": 200, "sample": json.dumps({"data": [{"id": "gpt-5.4"}]})}),
                    (405, {"status": 405, "sample": '{"error":"method not allowed"}'}),
                    (200, {"status": 200, "sample": json.dumps({"id": "resp_123"})}),
                ]
                status, detail = ccsw._probe_codex_target(store, conf, "demo", deep=True)

        self.assertEqual(status, "degraded")
        self.assertEqual(detail["reason_code"], "http_only_responses")
        self.assertEqual(detail["checks"]["primary_models_probe"]["reason_code"], "protocol_incompatible")
        self.assertEqual(detail["checks"]["fallback_models_probe"]["reason_code"], "models_ready")
        self.assertEqual(detail["checks"]["selected_models_probe"]["selected"], True)
        self.assertEqual(detail["checks"]["responses_get_probe"]["reason_code"], "responses_get_incompatible")
        self.assertEqual(detail["checks"]["responses_post_probe"]["reason_code"], "responses_post_ready")
        self.assertEqual(detail["checks"]["transport_check"]["reason_code"], "http_only_responses")

    def test_probe_codex_target_treats_post_422_as_probe_payload_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            (codex_dir / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "demo-token"}), encoding="utf-8")
            (codex_dir / "config.toml").write_text(
                '\n'.join(
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
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }
            conf = {
                "base_url": "https://relay.example.com/v1",
                "token": "demo-token",
            }

            with patch("ccsw._http_probe") as http_probe:
                http_probe.side_effect = [
                    (200, {"status": 200, "sample": json.dumps({"data": [{"id": "gpt-5.4"}]})}),
                    (200, {"status": 200, "sample": json.dumps({"data": []})}),
                    (422, {"status": 422, "sample": '{"error":"bad payload"}'}),
                ]
                status, detail = ccsw._probe_codex_target(store, conf, "demo", deep=True)

        self.assertEqual(status, "degraded")
        self.assertEqual(detail["checks"]["responses_post_probe"]["reason_code"], "probe_payload_rejected")

    def test_probe_codex_target_treats_post_429_as_transient_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            (codex_dir / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "demo-token"}), encoding="utf-8")
            (codex_dir / "config.toml").write_text(
                '\n'.join(
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
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }
            conf = {
                "base_url": "https://relay.example.com/v1",
                "token": "demo-token",
            }

            with patch("ccsw._http_probe") as http_probe:
                http_probe.side_effect = [
                    (200, {"status": 200, "sample": json.dumps({"data": [{"id": "gpt-5.4"}]})}),
                    (200, {"status": 200, "sample": json.dumps({"data": []})}),
                    (429, {"status": 429, "sample": '{"error":"rate limit"}'}),
                ]
                status, detail = ccsw._probe_codex_target(store, conf, "demo", deep=True)

        self.assertEqual(status, "degraded")
        self.assertEqual(detail["checks"]["responses_post_probe"]["reason_code"], "transient_degraded")

    def test_probe_codex_target_keeps_config_mismatch_as_summary_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            (codex_dir / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "demo-token"}), encoding="utf-8")
            (codex_dir / "config.toml").write_text(
                '\n'.join(
                    [
                        'model_provider = "ccswitch_active"',
                        "",
                        "[model_providers.ccswitch_active]",
                        'name = "ccswitch: demo"',
                        'base_url = "https://wrong.example.com/v1"',
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
                "providers": {},
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }
            conf = {
                "base_url": "https://relay.example.com/v1",
                "token": "demo-token",
            }

            with patch("ccsw._http_probe") as http_probe:
                http_probe.side_effect = [
                    (200, {"status": 200, "sample": json.dumps({"data": [{"id": "gpt-5.4"}]})}),
                    (200, {"status": 200, "sample": json.dumps({"data": []})}),
                    (200, {"status": 200, "sample": json.dumps({"id": "resp_123"})}),
                ]
                status, detail = ccsw._probe_codex_target(store, conf, "demo", deep=True)

        self.assertEqual(status, "degraded")
        self.assertEqual(detail["reason_code"], "config_mismatch")
        self.assertEqual(detail["checks"]["transport_check"]["reason_code"], "responses_transport_ready")

    def test_probe_codex_target_keeps_auth_error_over_transport_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            (codex_dir / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "demo-token"}), encoding="utf-8")
            (codex_dir / "config.toml").write_text(
                '\n'.join(
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
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }
            conf = {
                "base_url": "https://relay.example.com/v1",
                "token": "demo-token",
            }

            with patch("ccsw._http_probe") as http_probe:
                http_probe.side_effect = [
                    (200, {"status": 200, "sample": json.dumps({"data": [{"id": "gpt-5.4"}]})}),
                    (401, {"status": 401, "sample": '{"error":"unauthorized"}'}),
                    (405, {"status": 405, "sample": '{"error":"method not allowed"}'}),
                ]
                status, detail = ccsw._probe_codex_target(store, conf, "demo", deep=True)

        self.assertEqual(status, "failed")
        self.assertEqual(detail["reason_code"], "auth_error")
        self.assertEqual(detail["checks"]["responses_get_probe"]["reason_code"], "auth_error")
        self.assertEqual(detail["checks"]["responses_post_probe"]["reason_code"], "responses_post_incompatible")

    def test_probe_codex_target_rejects_unsafe_transport(self) -> None:
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
                        "[model_providers.ccswitch_active]",
                        'name = "ccswitch: demo"',
                        'base_url = "http://relay.example.com/v1"',
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
                "providers": {},
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }
            conf = {
                "base_url": "http://relay.example.com/v1",
                "token": "demo-token",
            }

            status, detail = ccsw._probe_codex_target(store, conf, "demo", deep=True)

        self.assertEqual(status, "failed")
        self.assertEqual(detail["reason_code"], "unsafe_transport")
        self.assertEqual(detail["checks"]["transport_policy_check"]["reason_code"], "unsafe_transport")

    def test_probe_codex_target_fails_when_live_auth_file_is_missing_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            (codex_dir / "auth.json").write_text(json.dumps({}), encoding="utf-8")
            (codex_dir / "config.toml").write_text(
                '\n'.join(
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
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }
            conf = {
                "base_url": "https://relay.example.com/v1",
                "token": "demo-token",
            }

            with patch("ccsw._http_probe", return_value=(200, {"status": 200, "sample": json.dumps({"data": [{"id": "gpt-5.4"}]})})):
                status, detail = ccsw._probe_codex_target(store, conf, "demo", deep=False)

        self.assertEqual(status, "failed")
        self.assertEqual(detail["reason_code"], "auth_missing")
        self.assertEqual(detail["checks"]["live_auth_check"]["reason_code"], "auth_missing")

    def test_falls_back_to_primary_base_url_when_all_probes_fail(self) -> None:
        conf = {
            "base_url": "https://relay-primary.example/v1",
            "fallback_base_url": "https://relay-backup.example/v1",
        }

        with patch("ccsw.probe_codex_base_url", side_effect=[False, False]) as probe:
            selected = ccsw.select_codex_base_url(conf)

        self.assertEqual(selected, "https://relay-primary.example/v1")
        self.assertEqual(
            probe.call_args_list,
            [
                call("https://relay-primary.example/v1"),
                call("https://relay-backup.example/v1"),
            ],
        )


class CodexSwitchIntegrationTests(unittest.TestCase):
    def test_codex_switch_uses_custom_provider_with_env_ref_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_home = root / "home"
            fake_home.mkdir()
            codex_dir = fake_home / ".codex"
            codex_dir.mkdir(parents=True)
            (codex_dir / "config.toml").write_text(
                'model = "gpt-5.4"\n',
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["CCSW_HOME"] = str(root / ".ccswitch")
            env["CCSW_FAKE_HOME"] = str(fake_home)
            env["CCSW_LOCAL_ENV_PATH"] = str(root / ".env.local")
            env["DEMO_CODEX_TOKEN"] = "dummy-demo-token"
            (root / ".env.local").write_text("", encoding="utf-8")

            subprocess.run(
                [
                    "python3",
                    "ccsw.py",
                    "add",
                    "demo-codex",
                    "--codex-url",
                    "https://relay-beta.example/codex/v1",
                    "--codex-token",
                    "$DEMO_CODEX_TOKEN",
                ],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )

            subprocess.run(
                ["python3", "ccsw.py", "codex", "demo-codex"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )

            auth = json.loads((codex_dir / "auth.json").read_text(encoding="utf-8"))
            config = (codex_dir / "config.toml").read_text(encoding="utf-8")
            codex_env = (root / ".ccswitch" / "codex.env").read_text(encoding="utf-8")

            self.assertEqual(auth, {"OPENAI_API_KEY": "dummy-demo-token"})
            self.assertIn('name = "ccswitch: demo-codex"\n', config)
            self.assertIn('base_url = "https://relay-beta.example/codex/v1"\n', config)
            self.assertEqual(
                codex_env,
                "unset OPENAI_BASE_URL\nexport OPENAI_API_KEY='dummy-demo-token'\n",
            )

    def test_write_codex_uses_fallback_base_url_when_primary_probe_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            config_path = codex_dir / "config.toml"
            env_path = root / ".ccswitch" / "codex.env"
            config_path.write_text('model = "gpt-5.4"\n', encoding="utf-8")

            conf = {
                "base_url": "https://relay-primary.example/v1",
                "fallback_base_url": "https://relay-backup.example/v1",
                "token": "dummy-codex-token",
            }

            with patch.object(ccsw, "CODEX_AUTH", auth_path), patch.object(
                ccsw, "CODEX_CONFIG", config_path
            ), patch.object(ccsw, "CODEX_ENV_PATH", env_path), patch(
                "ccsw.probe_codex_base_url", side_effect=[False, True]
            ):
                ccsw.write_codex(conf, "relay-demo")

            auth = json.loads(auth_path.read_text(encoding="utf-8"))
            config = config_path.read_text(encoding="utf-8")
            codex_env = env_path.read_text(encoding="utf-8")

            self.assertEqual(auth, {"OPENAI_API_KEY": "dummy-codex-token"})
            self.assertIn('name = "ccswitch: relay-demo"\n', config)
            self.assertIn('base_url = "https://relay-backup.example/v1"\n', config)
            self.assertEqual(
                codex_env,
                "unset OPENAI_BASE_URL\nexport OPENAI_API_KEY='dummy-codex-token'\n",
            )

    def test_write_codex_chatgpt_mode_clears_conflicting_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            config_path = codex_dir / "config.toml"
            env_path = root / ".ccswitch" / "codex.env"
            auth_path.write_text(
                json.dumps(
                    {
                        "OPENAI_API_KEY": "old-api-key",
                        "chatgpt_access_token": "session-token",
                    }
                ),
                encoding="utf-8",
            )
            config_path.write_text(
                'model = "gpt-5.4"\nopenai_base_url = "https://relay.example/v1"\nmodel_provider = "ccswitch_active"\n\n[model_providers.ccswitch_active]\nname = "ccswitch: old"\nbase_url = "https://relay.example/v1"\nenv_key = "OPENAI_API_KEY"\nsupports_websockets = false\nwire_api = "responses"\n',
                encoding="utf-8",
            )

            conf = {
                "auth_mode": "chatgpt",
            }

            with patch.object(ccsw, "CODEX_AUTH", auth_path), patch.object(
                ccsw, "CODEX_CONFIG", config_path
            ), patch.object(ccsw, "CODEX_ENV_PATH", env_path):
                ccsw.write_codex(conf, "pro")

            auth = json.loads(auth_path.read_text(encoding="utf-8"))
            config = config_path.read_text(encoding="utf-8")
            codex_env = env_path.read_text(encoding="utf-8")

            self.assertEqual(
                auth,
                {
                    "auth_mode": "chatgpt",
                    "chatgpt_access_token": "session-token",
                },
            )
            self.assertIn('model_provider = "openai"\n', config)
            self.assertNotIn('openai_base_url = "https://relay.example/v1"\n', config)
            self.assertNotIn("[model_providers.ccswitch_active]\n", config)
            self.assertEqual(
                codex_env,
                "unset OPENAI_API_KEY\nunset OPENAI_BASE_URL\n",
            )

    def test_write_codex_chatgpt_mode_uses_shared_lane_when_sync_setting_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            config_path = codex_dir / "config.toml"
            env_path = root / ".ccswitch" / "codex.env"
            auth_path.write_text(
                json.dumps(
                    {
                        "auth_mode": "chatgpt",
                        "chatgpt_access_token": "session-token",
                        "OPENAI_API_KEY": "old-api-key",
                    }
                ),
                encoding="utf-8",
            )
            config_path.write_text(
                'model = "gpt-5.4"\nmodel_provider = "openai"\n',
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {tool: None for tool in ccsw.ALL_TOOLS},
                "aliases": {},
                "providers": {},
                "profiles": {},
                "settings": {
                    "codex_config_dir": str(codex_dir),
                    ccsw.CODEX_SYNC_SETTING_KEY: True,
                },
            }
            conf = {"auth_mode": "chatgpt"}

            with patch.object(ccsw, "CODEX_AUTH", auth_path), patch.object(
                ccsw, "CODEX_CONFIG", config_path
            ), patch.object(ccsw, "CODEX_ENV_PATH", env_path):
                ccsw.write_codex(conf, "pro", store)

            auth = json.loads(auth_path.read_text(encoding="utf-8"))
            config = config_path.read_text(encoding="utf-8")
            codex_env = env_path.read_text(encoding="utf-8")

            self.assertEqual(
                auth,
                {
                    "auth_mode": "chatgpt",
                    "chatgpt_access_token": "session-token",
                },
            )
            self.assertIn('model_provider = "ccswitch_active"\n', config)
            self.assertIn('[model_providers.ccswitch_active]\n', config)
            self.assertIn("requires_openai_auth = true\n", config)
            self.assertIn("supports_websockets = true\n", config)
            self.assertIn('wire_api = "responses"\n', config)
            self.assertNotIn('env_key = "OPENAI_API_KEY"\n', config)
            self.assertEqual(
                codex_env,
                "unset OPENAI_API_KEY\nunset OPENAI_BASE_URL\n",
            )

    def test_write_codex_chatgpt_mode_requires_existing_login_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            config_path = codex_dir / "config.toml"
            env_path = root / ".ccswitch" / "codex.env"
            auth_path.write_text(json.dumps({}), encoding="utf-8")
            config_path.write_text('model_provider = "openai"\n', encoding="utf-8")

            conf = {"auth_mode": "chatgpt"}

            with patch.object(ccsw, "CODEX_AUTH", auth_path), patch.object(
                ccsw, "CODEX_CONFIG", config_path
            ), patch.object(ccsw, "CODEX_ENV_PATH", env_path):
                result = ccsw.write_codex(conf, "pro")

            self.assertIsNone(result)
            self.assertEqual(json.loads(auth_path.read_text(encoding="utf-8")), {})
            self.assertEqual(config_path.read_text(encoding="utf-8"), 'model_provider = "openai"\n')
            self.assertFalse(env_path.exists())

    def test_codex_switch_writes_custom_provider_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_home = root / "home"
            fake_home.mkdir()
            codex_dir = fake_home / ".codex"
            codex_dir.mkdir(parents=True)
            (codex_dir / "config.toml").write_text(
                '# test config\nmodel = "gpt-5.4"\n\n[projects."/tmp"]\ntrust_level = "trusted"\n',
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["CCSW_HOME"] = str(root / ".ccswitch")
            env["CCSW_FAKE_HOME"] = str(fake_home)
            env["CCSW_LOCAL_ENV_PATH"] = str(root / ".env.local")
            env["DEMO_CODEX_TOKEN"] = "dummy-codex-token"
            (root / ".env.local").write_text("", encoding="utf-8")

            subprocess.run(
                [
                    "python3",
                    "ccsw.py",
                    "add",
                    "demo-provider",
                    "--codex-url",
                    "https://relay-alpha.example/openai/v1",
                    "--codex-token",
                    "$DEMO_CODEX_TOKEN",
                ],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )

            proc = subprocess.run(
                ["python3", "ccsw.py", "codex", "demo-provider"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )

            auth = json.loads((codex_dir / "auth.json").read_text(encoding="utf-8"))
            config = (codex_dir / "config.toml").read_text(encoding="utf-8")
            codex_env = (root / ".ccswitch" / "codex.env").read_text(encoding="utf-8")

            self.assertEqual(auth, {"OPENAI_API_KEY": "dummy-codex-token"})
            self.assertIn('model_provider = "ccswitch_active"\n', config)
            self.assertIn('[model_providers.ccswitch_active]\n', config)
            self.assertIn('name = "ccswitch: demo-provider"\n', config)
            self.assertIn('base_url = "https://relay-alpha.example/openai/v1"\n', config)
            self.assertIn('env_key = "OPENAI_API_KEY"\n', config)
            self.assertIn('supports_websockets = false\n', config)
            self.assertIn('wire_api = "responses"\n', config)
            self.assertNotIn('openai_base_url = "https://relay-alpha.example/openai/v1"\n', config)
            self.assertIn('[projects."/tmp"]\ntrust_level = "trusted"\n', config)
            self.assertEqual(
                codex_env,
                "unset OPENAI_BASE_URL\nexport OPENAI_API_KEY='dummy-codex-token'\n",
            )
            self.assertIn("export OPENAI_API_KEY='dummy-codex-token'", proc.stdout)
            self.assertIn("unset OPENAI_BASE_URL", proc.stdout)

    def test_codex_switch_to_chatgpt_auth_mode_clears_provider_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_home = root / "home"
            fake_home.mkdir()
            codex_dir = fake_home / ".codex"
            codex_dir.mkdir(parents=True)
            (codex_dir / "auth.json").write_text(
                json.dumps(
                    {
                        "auth_mode": "chatgpt",
                        "OPENAI_API_KEY": "old-provider-token",
                        "tokens": {"access_token": "session-token"},
                    }
                ),
                encoding="utf-8",
            )
            (codex_dir / "config.toml").write_text(
                'model = "gpt-5.4"\nopenai_base_url = "https://relay-alpha.example/openai/v1"\nmodel_provider = "ccswitch_active"\n\n[model_providers.ccswitch_active]\nname = "ccswitch: demo-provider"\nbase_url = "https://relay-alpha.example/openai/v1"\nenv_key = "OPENAI_API_KEY"\nsupports_websockets = false\nwire_api = "responses"\n',
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["CCSW_HOME"] = str(root / ".ccswitch")
            env["CCSW_FAKE_HOME"] = str(fake_home)
            env["CCSW_LOCAL_ENV_PATH"] = str(root / ".env.local")
            (root / ".env.local").write_text("", encoding="utf-8")

            subprocess.run(
                [
                    "python3",
                    "ccsw.py",
                    "add",
                    "pro",
                    "--codex-auth-mode",
                    "chatgpt",
                ],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            subprocess.run(
                ["python3", "ccsw.py", "capture", "codex", "pro"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )

            proc = subprocess.run(
                ["python3", "ccsw.py", "codex", "pro"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )

            auth = json.loads((codex_dir / "auth.json").read_text(encoding="utf-8"))
            config = (codex_dir / "config.toml").read_text(encoding="utf-8")
            codex_env = (root / ".ccswitch" / "codex.env").read_text(encoding="utf-8")

            self.assertEqual(
                auth,
                {
                    "auth_mode": "chatgpt",
                    "tokens": {"access_token": "session-token"},
                },
            )
            self.assertIn('model_provider = "openai"\n', config)
            self.assertNotIn("openai_base_url", config)
            self.assertNotIn("[model_providers.ccswitch_active]\n", config)
            self.assertEqual(
                codex_env,
                "unset OPENAI_API_KEY\nunset OPENAI_BASE_URL\n",
            )
            self.assertIn("unset OPENAI_API_KEY", proc.stdout)
            self.assertIn("unset OPENAI_BASE_URL", proc.stdout)

    def test_write_codex_chatgpt_mode_restores_target_snapshot_and_refreshes_active_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            config_path = codex_dir / "config.toml"
            env_path = root / ".ccswitch" / "codex.env"
            snapshot_dir = root / "codex-chatgpt"
            snapshot_dir.mkdir(parents=True)
            auth_path.write_text(
                json.dumps(
                    {
                        "auth_mode": "chatgpt",
                        "tokens": {"access_token": "live-pro", "account_id": "acct-pro"},
                        "OPENAI_API_KEY": "stale-provider-token",
                    }
                ),
                encoding="utf-8",
            )
            config_path.write_text('model = "gpt-5.4"\nmodel_provider = "openai"\n', encoding="utf-8")
            (snapshot_dir / "pro1.json").write_text(
                json.dumps(
                    {
                        "auth_mode": "chatgpt",
                        "tokens": {"access_token": "live-pro1", "account_id": "acct-pro1"},
                    }
                ),
                encoding="utf-8",
            )
            store = {
                "version": 2,
                "active": {"claude": None, "codex": "pro", "gemini": None, "opencode": None, "openclaw": None},
                "aliases": {},
                "providers": {
                    "pro": {"codex": {"auth_mode": "chatgpt", "account_id": "acct-pro"}},
                    "pro1": {"codex": {"auth_mode": "chatgpt", "account_id": "acct-pro1"}},
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "CODEX_AUTH", auth_path
            ), patch.object(ccsw, "CODEX_CONFIG", config_path), patch.object(
                ccsw, "CODEX_ENV_PATH", env_path
            ):
                ccsw.write_codex(store["providers"]["pro1"]["codex"], "pro1", store)

            auth = json.loads(auth_path.read_text(encoding="utf-8"))
            config = config_path.read_text(encoding="utf-8")
            codex_env = env_path.read_text(encoding="utf-8")
            refreshed = json.loads((snapshot_dir / "pro.json").read_text(encoding="utf-8"))

            self.assertEqual(
                auth,
                {
                    "auth_mode": "chatgpt",
                    "tokens": {"access_token": "live-pro1", "account_id": "acct-pro1"},
                },
            )
            self.assertEqual(
                refreshed,
                {
                    "auth_mode": "chatgpt",
                    "tokens": {"access_token": "live-pro", "account_id": "acct-pro"},
                },
            )
            self.assertIn('model_provider = "openai"\n', config)
            self.assertEqual(
                codex_env,
                "unset OPENAI_API_KEY\nunset OPENAI_BASE_URL\n",
            )

    def test_write_codex_chatgpt_mode_requires_snapshot_for_other_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_dir = root / ".codex"
            codex_dir.mkdir(parents=True)
            auth_path = codex_dir / "auth.json"
            config_path = codex_dir / "config.toml"
            env_path = root / ".ccswitch" / "codex.env"
            auth_path.write_text(
                json.dumps(
                    {
                        "auth_mode": "chatgpt",
                        "tokens": {"access_token": "live-pro", "account_id": "acct-pro"},
                    }
                ),
                encoding="utf-8",
            )
            config_path.write_text('model = "gpt-5.4"\nmodel_provider = "openai"\n', encoding="utf-8")
            store = {
                "version": 2,
                "active": {"claude": None, "codex": "pro", "gemini": None, "opencode": None, "openclaw": None},
                "aliases": {},
                "providers": {
                    "pro": {"codex": {"auth_mode": "chatgpt", "account_id": "acct-pro"}},
                    "pro1": {"codex": {"auth_mode": "chatgpt", "account_id": "acct-pro1"}},
                },
                "profiles": {},
                "settings": {"codex_config_dir": str(codex_dir)},
            }

            with patch.object(ccsw, "CCSWITCH_DIR", root), patch.object(
                ccsw, "CODEX_AUTH", auth_path
            ), patch.object(ccsw, "CODEX_CONFIG", config_path), patch.object(
                ccsw, "CODEX_ENV_PATH", env_path
            ):
                result = ccsw.write_codex(store["providers"]["pro1"]["codex"], "pro1", store)

            self.assertIsNone(result)
            self.assertEqual(
                json.loads(auth_path.read_text(encoding="utf-8")),
                {
                    "auth_mode": "chatgpt",
                    "tokens": {"access_token": "live-pro", "account_id": "acct-pro"},
                },
            )
            self.assertFalse((root / ".ccswitch" / "codex.env").exists())

if __name__ == "__main__":
    unittest.main()
