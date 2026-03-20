import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

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

            ccsw.upsert_codex_provider_config(path, "88code", "https://www.88code.ai/openai/v1")

            content = path.read_text(encoding="utf-8")
            self.assertIn('model_provider = "ccswitch_active"\n', content)
            self.assertNotIn('openai_base_url = "https://old.example/v1"\n', content)
            self.assertIn('[model_providers.ccswitch_active]\n', content)
            self.assertIn('name = "ccswitch: 88code"\n', content)
            self.assertIn('base_url = "https://www.88code.ai/openai/v1"\n', content)
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

            ccsw.upsert_codex_provider_config(path, "rightcode", "https://right.codes/codex/v1")

            content = path.read_text(encoding="utf-8")
            self.assertEqual(content.count("[model_providers.ccswitch_active]\n"), 1)
            self.assertIn('name = "ccswitch: rightcode"\n', content)
            self.assertIn('base_url = "https://right.codes/codex/v1"\n', content)
            self.assertNotIn('base_url = "https://old.example/v1"\n', content)


class CodexSwitchIntegrationTests(unittest.TestCase):
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
            env["CODE88_CODEX_TOKEN"] = "dummy-codex-token"

            proc = subprocess.run(
                ["python3", "ccsw.py", "codex", "88code"],
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
            self.assertIn('name = "ccswitch: 88code"\n', config)
            self.assertIn('base_url = "https://www.88code.ai/openai/v1"\n', config)
            self.assertIn('env_key = "OPENAI_API_KEY"\n', config)
            self.assertIn('supports_websockets = false\n', config)
            self.assertIn('wire_api = "responses"\n', config)
            self.assertNotIn('openai_base_url = "https://www.88code.ai/openai/v1"\n', config)
            self.assertIn('[projects."/tmp"]\ntrust_level = "trusted"\n', config)
            self.assertEqual(
                codex_env,
                "unset OPENAI_BASE_URL\nexport OPENAI_API_KEY='dummy-codex-token'\n",
            )
            self.assertIn("export OPENAI_API_KEY='dummy-codex-token'", proc.stdout)
            self.assertIn("unset OPENAI_BASE_URL", proc.stdout)


if __name__ == "__main__":
    unittest.main()
