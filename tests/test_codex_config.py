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


class CodexSwitchIntegrationTests(unittest.TestCase):
    def test_codex_switch_writes_new_style_config(self) -> None:
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
            self.assertIn('openai_base_url = "https://www.88code.ai/openai/v1"\n', config)
            self.assertIn('[projects."/tmp"]\ntrust_level = "trusted"\n', config)
            self.assertEqual(
                codex_env,
                "unset OPENAI_BASE_URL\nexport OPENAI_API_KEY='dummy-codex-token'\n",
            )
            self.assertIn("export OPENAI_API_KEY='dummy-codex-token'", proc.stdout)
            self.assertIn("unset OPENAI_BASE_URL", proc.stdout)


if __name__ == "__main__":
    unittest.main()
