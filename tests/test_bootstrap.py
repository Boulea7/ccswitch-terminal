import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Optional

from tests.support import add_provider, build_cli_env, isolated_runtime_env, run_shell, stub_server


REPO_ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP = REPO_ROOT / "bootstrap.sh"
CCSW_PY = REPO_ROOT / "ccsw.py"
BASH_SHELL = shutil.which("bash") or "/bin/bash"
ZSH_SHELL = shutil.which("zsh")
DETECTED_ZSH_SHELL = ZSH_SHELL or "/bin/zsh"
REAL_WRAPPER_SHELLS = tuple(shell for shell in (BASH_SHELL, ZSH_SHELL) if shell)


class BootstrapScriptTests(unittest.TestCase):
    def _make_env(
        self,
        root: Path,
        bootstrap_home: Path,
        *,
        shell: str = DETECTED_ZSH_SHELL,
        rc_file: Optional[Path] = None,
    ) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(root),
                "SHELL": shell,
                "BOOTSTRAP_HOME": str(bootstrap_home),
                "CCSW_HOME": str(bootstrap_home / ".ccswitch"),
                "CCSW_FAKE_HOME": str(root),
            }
        )
        if rc_file is not None:
            env["BOOTSTRAP_RC_FILE"] = str(rc_file)
        else:
            env.pop("BOOTSTRAP_RC_FILE", None)
        return env

    def _run_bootstrap(self, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(BOOTSTRAP), *args],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )

    def _legacy_wrapper_block(self, ccsw_py: str) -> str:
        return "\n".join(
            [
                "# ccsw - smart provider switcher",
                'unalias ccsw 2>/dev/null || true',
                f'_CCSW_PY={ccsw_py}',
                "ccsw() {",
                '  case "${1:-}" in',
                '    ""|--help|-h|help|-*)',
                '      python3 "$_CCSW_PY" "$@" ;;',
                "    claude|codex|gemini|all|list|show|add|remove|alias)",
                '      python3 "$_CCSW_PY" "$@" ;;',
                "    *)",
                '      python3 "$_CCSW_PY" claude "$@" ;;',
                "  esac",
                "}",
                'cxsw() { eval "$(python3 "$_CCSW_PY" codex "$@")"; }',
                'gcsw() { python3 "$_CCSW_PY" gemini "$@"; }',
                'ccswitch() { python3 "$_CCSW_PY" "$@"; }',
                "",
            ]
        )

    def test_bootstrap_dry_run_does_not_modify_real_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_home = root / "bootstrap-home"
            rc_file = root / ".testrc"
            rc_file.write_text("# existing rc\n", encoding="utf-8")
            env = self._make_env(root, bootstrap_home, rc_file=rc_file)
            result = self._run_bootstrap(env, "--dry-run")

            self.assertIn("[dry-run]", result.stdout)
            self.assertFalse((bootstrap_home / ".ccswitch").exists())
            self.assertEqual(rc_file.read_text(encoding="utf-8"), "# existing rc\n")

    def test_bootstrap_non_dry_run_installs_wrappers_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_home = root / "bootstrap-home"
            rc_file = root / ".testrc"
            rc_file.write_text("# existing rc\n", encoding="utf-8")
            env = self._make_env(root, bootstrap_home, rc_file=rc_file)
            first = self._run_bootstrap(env)
            second = self._run_bootstrap(env)

            rc_content = rc_file.read_text(encoding="utf-8")
            ccswitch_dir = bootstrap_home / ".ccswitch"

            self.assertIn("Installation complete!", first.stdout)
            self.assertIn("[skip] ccsw functions already up-to-date", second.stdout)
            self.assertTrue((ccswitch_dir / "generated").exists())
            self.assertTrue((ccswitch_dir / "tmp").exists())
            self.assertEqual(rc_content.count("ccsw() {"), 1)
            self.assertEqual(rc_content.count("cxsw() {"), 1)
            self.assertEqual(rc_content.count('gcsw() { eval "$(python3 "$_CCSW_PY" gemini "$@")"; }'), 1)
            self.assertEqual(rc_content.count('opsw() { eval "$(python3 "$_CCSW_PY" opencode "$@")"; }'), 1)
            self.assertEqual(rc_content.count('clawsw() { eval "$(python3 "$_CCSW_PY" openclaw "$@")"; }'), 1)
            self.assertEqual(rc_content.count('source "' + str(ccswitch_dir / "active.env") + '"'), 1)
            self.assertEqual(rc_content.count('source "' + str(ccswitch_dir / "codex.env") + '"'), 1)
            self.assertEqual(rc_content.count('source "' + str(ccswitch_dir / "opencode.env") + '"'), 1)
            self.assertEqual(rc_content.count('source "' + str(ccswitch_dir / "openclaw.env") + '"'), 1)
            self.assertIn("codex|gemini|opencode|openclaw|all|profile|rollback", rc_content)
            self.assertIn("claude|list|show|add|remove|alias|settings|sync|share|capture|login|accounts|status|doctor|history|repair|import|run", rc_content)
            self.assertIn('python3 "$_CCSW_PY" sync "$@"', rc_content)
            self.assertIn('python3 "$_CCSW_PY" share codex "$@"', rc_content)
            self.assertIn('python3 "$_CCSW_PY" capture codex "$@"', rc_content)
            self.assertIn('python3 "$_CCSW_PY" login codex "$@"', rc_content)
            self.assertIn('python3 "$_CCSW_PY" accounts codex "$@"', rc_content)
            self.assertIn('python3 "$_CCSW_PY" status codex "$@"', rc_content)

    def test_bootstrap_upgrades_legacy_wrapper_block_and_refreshes_ccsw_py(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_home = root / "bootstrap-home"
            rc_file = root / ".testrc"
            rc_file.write_text(
                "# existing rc\n"
                + self._legacy_wrapper_block("/tmp/old-ccswitch/ccsw.py")
                + "# tail\n",
                encoding="utf-8",
            )
            env = self._make_env(root, bootstrap_home, rc_file=rc_file)

            result = self._run_bootstrap(env)
            rc_content = rc_file.read_text(encoding="utf-8")

            self.assertIn("Installation complete!", result.stdout)
            self.assertIn("[updated]", result.stdout)
            self.assertIn("# >>> ccsw bootstrap >>>", rc_content)
            self.assertIn("# <<< ccsw bootstrap <<<", rc_content)
            self.assertEqual(rc_content.count("ccsw() {"), 1)
            self.assertEqual(rc_content.count('gcsw() { eval "$(python3 "$_CCSW_PY" gemini "$@")"; }'), 1)
            self.assertNotIn('gcsw() { python3 "$_CCSW_PY" gemini "$@"; }', rc_content)
            self.assertNotIn("/tmp/old-ccswitch/ccsw.py", rc_content)
            self.assertIn(f"_CCSW_PY={str(REPO_ROOT / 'ccsw.py')}", rc_content)
            self.assertIn("codex|gemini|opencode|openclaw|all", rc_content)
            self.assertIn("codex|gemini|opencode|openclaw|all|profile|rollback", rc_content)
            self.assertIn("claude|list|show|add|remove|alias|settings|sync|share|capture|login|accounts|status|doctor|history|repair|import|run", rc_content)
            self.assertIn('python3 "$_CCSW_PY" sync "$@"', rc_content)
            self.assertIn('python3 "$_CCSW_PY" share codex "$@"', rc_content)
            self.assertIn('python3 "$_CCSW_PY" capture codex "$@"', rc_content)
            self.assertIn('python3 "$_CCSW_PY" login codex "$@"', rc_content)
            self.assertIn('python3 "$_CCSW_PY" accounts codex "$@"', rc_content)
            self.assertIn('python3 "$_CCSW_PY" status codex "$@"', rc_content)

    def test_bootstrap_uses_bashrc_by_default_for_bash_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_home = root / "bootstrap-home"
            bashrc = root / ".bashrc"
            env = self._make_env(root, bootstrap_home, shell="/bin/bash")

            result = self._run_bootstrap(env)

            self.assertIn("Installation complete!", result.stdout)
            self.assertTrue(bashrc.exists())
            self.assertIn("# >>> ccsw bootstrap >>>", bashrc.read_text(encoding="utf-8"))
            self.assertFalse((root / ".zshrc").exists())

    def test_bootstrap_uses_zshrc_by_default_for_zsh_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_home = root / "bootstrap-home"
            zshrc = root / ".zshrc"
            env = self._make_env(root, bootstrap_home, shell=DETECTED_ZSH_SHELL)

            result = self._run_bootstrap(env)

            self.assertIn("Installation complete!", result.stdout)
            self.assertTrue(zshrc.exists())
            self.assertIn("# >>> ccsw bootstrap >>>", zshrc.read_text(encoding="utf-8"))
            self.assertFalse((root / ".bashrc").exists())

    def test_bootstrap_prefers_explicit_rc_file_over_shell_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_home = root / "bootstrap-home"
            explicit_rc = root / ".custom-rc"
            env = self._make_env(root, bootstrap_home, shell=DETECTED_ZSH_SHELL, rc_file=explicit_rc)

            result = self._run_bootstrap(env)

            self.assertIn("Installation complete!", result.stdout)
            self.assertTrue(explicit_rc.exists())
            self.assertIn("# >>> ccsw bootstrap >>>", explicit_rc.read_text(encoding="utf-8"))
            self.assertFalse((root / ".zshrc").exists())

    def test_bootstrap_rejects_unknown_argument(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_home = root / "bootstrap-home"
            env = self._make_env(root, bootstrap_home)

            result = subprocess.run(
                ["bash", str(BOOTSTRAP), "--bad-flag"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Unknown argument", result.stderr)

    def test_generated_ccsw_wrapper_passes_repair_through_after_sourcing_rc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_home = root / "bootstrap-home"
            rc_file = root / ".testrc"
            rc_file.write_text("# existing rc\n", encoding="utf-8")
            env = self._make_env(root, bootstrap_home, rc_file=rc_file)

            self._run_bootstrap(env)

            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-c", f'source "{rc_file}"; ccsw repair codex'],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("[repair] codex: no runtime lease", result.stderr)
            self.assertEqual(result.stdout, "")

    def test_source_rc_rehydrates_generated_env_files_in_bash_and_zsh(self) -> None:
        for shell in REAL_WRAPPER_SHELLS:
            with self.subTest(shell=shell), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                bootstrap_home = root / "bootstrap-home"
                rc_file = root / ".testrc"
                rc_file.write_text("# existing rc\n", encoding="utf-8")
                env = self._make_env(root, bootstrap_home, shell=shell, rc_file=rc_file)

                self._run_bootstrap(env)
                ccswitch_dir = bootstrap_home / ".ccswitch"
                (ccswitch_dir / "active.env").write_text("export GEMINI_API_KEY='gemini-live'\n", encoding="utf-8")
                (ccswitch_dir / "codex.env").write_text(
                    "export OPENAI_API_KEY='codex-live'\nunset OPENAI_BASE_URL\n",
                    encoding="utf-8",
                )
                (ccswitch_dir / "opencode.env").write_text(
                    "export OPENCODE_CONFIG='/tmp/opencode-live.json'\n",
                    encoding="utf-8",
                )
                (ccswitch_dir / "openclaw.env").write_text(
                    "export OPENCLAW_CONFIG_PATH='/tmp/openclaw-live.json5'\n",
                    encoding="utf-8",
                )

                result = run_shell(
                    shell,
                    "\n".join(
                        [
                            'export OPENAI_BASE_URL="legacy-url"',
                            f'source "{rc_file}"',
                            'printf "%s\\n" "$GEMINI_API_KEY|$OPENAI_API_KEY|$OPENCODE_CONFIG|$OPENCLAW_CONFIG_PATH|${OPENAI_BASE_URL-unset}"',
                        ]
                    ),
                    cwd=REPO_ROOT,
                    env=env,
                    check=True,
                )

                self.assertEqual(
                    result.stdout.strip(),
                    "gemini-live|codex-live|/tmp/opencode-live.json|/tmp/openclaw-live.json5|unset",
                )

    def test_bootstrap_rewrites_source_lines_into_one_current_managed_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_home = root / "bootstrap-home"
            old_home = root / "old-bootstrap-home"
            old_ccswitch_dir = old_home / ".ccswitch"
            rc_file = root / ".testrc"
            rc_file.write_text(
                "\n".join(
                    [
                        "# ccsw - load active Gemini API key",
                        f'[ -f "{old_ccswitch_dir / "active.env"}" ] && source "{old_ccswitch_dir / "active.env"}"',
                        "# ccsw - load active Codex API key and clear legacy base URL env",
                        f'# [ -f "{old_ccswitch_dir / "codex.env"}" ] && source "{old_ccswitch_dir / "codex.env"}"',
                        "# ccsw - load active OpenCode overlay",
                        f'# [ -f "{old_ccswitch_dir / "opencode.env"}" ] && source "{old_ccswitch_dir / "opencode.env"}"',
                        "# ccsw - load active OpenClaw overlay",
                        f'# [ -f "{old_ccswitch_dir / "openclaw.env"}" ] && source "{old_ccswitch_dir / "openclaw.env"}"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            env = self._make_env(root, bootstrap_home, rc_file=rc_file)

            result = self._run_bootstrap(env)
            rc_content = rc_file.read_text(encoding="utf-8")
            ccswitch_dir = bootstrap_home / ".ccswitch"

            self.assertIn("Installation complete!", result.stdout)
            self.assertEqual(
                rc_content.count(f'source "{ccswitch_dir / "active.env"}"'),
                1,
            )
            self.assertEqual(
                rc_content.count(f'source "{ccswitch_dir / "codex.env"}"'),
                1,
            )
            self.assertEqual(
                rc_content.count(f'source "{ccswitch_dir / "opencode.env"}"'),
                1,
            )
            self.assertEqual(
                rc_content.count(f'source "{ccswitch_dir / "openclaw.env"}"'),
                1,
            )
            self.assertNotIn(str(old_ccswitch_dir / "active.env"), rc_content)
            self.assertNotIn(str(old_ccswitch_dir / "codex.env"), rc_content)
            self.assertNotIn(str(old_ccswitch_dir / "opencode.env"), rc_content)
            self.assertNotIn(str(old_ccswitch_dir / "openclaw.env"), rc_content)

    def test_bootstrap_preserves_non_ccswitch_source_lines_with_generic_env_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_home = root / "bootstrap-home"
            old_home = root / "old-bootstrap-home"
            old_ccswitch_dir = old_home / ".ccswitch"
            custom_env_dir = root / "custom-envs"
            unrelated_active = custom_env_dir / "active.env"
            unrelated_codex = custom_env_dir / "codex.env"
            rc_file = root / ".testrc"
            unrelated_active_line = f'[ -f "{unrelated_active}" ] && source "{unrelated_active}"'
            unrelated_codex_line = f'[ -f "{unrelated_codex}" ] && source "{unrelated_codex}"'
            rc_file.write_text(
                "\n".join(
                    [
                        "# existing rc",
                        unrelated_active_line,
                        unrelated_codex_line,
                        "# ccsw - load active Gemini API key",
                        f'[ -f "{old_ccswitch_dir / "active.env"}" ] && source "{old_ccswitch_dir / "active.env"}"',
                        "# ccsw - load active Codex API key and clear legacy base URL env",
                        f'[ -f "{old_ccswitch_dir / "codex.env"}" ] && source "{old_ccswitch_dir / "codex.env"}"',
                        "# ccsw - load active OpenCode overlay",
                        f'[ -f "{old_ccswitch_dir / "opencode.env"}" ] && source "{old_ccswitch_dir / "opencode.env"}"',
                        "# ccsw - load active OpenClaw overlay",
                        f'[ -f "{old_ccswitch_dir / "openclaw.env"}" ] && source "{old_ccswitch_dir / "openclaw.env"}"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            env = self._make_env(root, bootstrap_home, rc_file=rc_file)

            self._run_bootstrap(env)
            rc_content = rc_file.read_text(encoding="utf-8")

            self.assertIn(unrelated_active_line, rc_content)
            self.assertIn(unrelated_codex_line, rc_content)
            self.assertNotIn(str(old_ccswitch_dir / "active.env"), rc_content)
            self.assertNotIn(str(old_ccswitch_dir / "codex.env"), rc_content)
            self.assertNotIn(str(old_ccswitch_dir / "opencode.env"), rc_content)
            self.assertNotIn(str(old_ccswitch_dir / "openclaw.env"), rc_content)

    def test_bootstrap_preserves_foreign_dot_ccswitch_source_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_home = root / "bootstrap-home"
            foreign_ccswitch_dir = root / "foreign" / ".ccswitch"
            rc_file = root / ".testrc"
            foreign_active_line = (
                f'[ -f "{foreign_ccswitch_dir / "active.env"}" ] && '
                f'source "{foreign_ccswitch_dir / "active.env"}"'
            )
            rc_file.write_text(
                "\n".join(
                    [
                        "# existing rc",
                        foreign_active_line,
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            env = self._make_env(root, bootstrap_home, rc_file=rc_file)

            self._run_bootstrap(env)
            rc_content = rc_file.read_text(encoding="utf-8")

            self.assertIn(foreign_active_line, rc_content)

    def test_bootstrap_preserves_multiple_foreign_dot_ccswitch_source_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_home = root / "bootstrap-home"
            foreign_ccswitch_dir = root / "foreign" / ".ccswitch"
            rc_file = root / ".testrc"
            foreign_active_line = (
                f'[ -f "{foreign_ccswitch_dir / "active.env"}" ] && '
                f'source "{foreign_ccswitch_dir / "active.env"}"'
            )
            foreign_codex_line = (
                f'[ -f "{foreign_ccswitch_dir / "codex.env"}" ] && '
                f'source "{foreign_ccswitch_dir / "codex.env"}"'
            )
            rc_file.write_text(
                "\n".join(
                    [
                        "# existing rc",
                        foreign_active_line,
                        foreign_codex_line,
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            env = self._make_env(root, bootstrap_home, rc_file=rc_file)

            self._run_bootstrap(env)
            rc_content = rc_file.read_text(encoding="utf-8")

            self.assertIn(foreign_active_line, rc_content)
            self.assertIn(foreign_codex_line, rc_content)

    def test_bootstrap_preserves_foreign_dot_ccswitch_line_after_legacy_comment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_home = root / "bootstrap-home"
            foreign_ccswitch_dir = root / "foreign" / ".ccswitch"
            rc_file = root / ".testrc"
            foreign_active_line = (
                f'[ -f "{foreign_ccswitch_dir / "active.env"}" ] && '
                f'source "{foreign_ccswitch_dir / "active.env"}"'
            )
            rc_file.write_text(
                "\n".join(
                    [
                        "# existing rc",
                        "# ccsw - load active Gemini API key",
                        foreign_active_line,
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            env = self._make_env(root, bootstrap_home, rc_file=rc_file)

            self._run_bootstrap(env)
            rc_content = rc_file.read_text(encoding="utf-8")

            self.assertIn(foreign_active_line, rc_content)

    def test_bootstrap_prefers_existing_zshrc_when_shell_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_home = root / "bootstrap-home"
            zshrc = root / ".zshrc"
            zshrc.write_text("# existing zshrc\n", encoding="utf-8")
            env = self._make_env(root, bootstrap_home, shell="")
            env.pop("SHELL", None)

            result = self._run_bootstrap(env)

            self.assertIn("Installation complete!", result.stdout)
            self.assertIn("# >>> ccsw bootstrap >>>", zshrc.read_text(encoding="utf-8"))
            self.assertFalse((root / ".bashrc").exists())

    def test_shell_wrappers_apply_expected_dispatch_contract(self) -> None:
        for shell in REAL_WRAPPER_SHELLS:
            with self.subTest(shell=shell), stub_server() as base_url, isolated_runtime_env() as paths:
                env = build_cli_env(
                    paths,
                    {
                        "ALPHA_CLAUDE_TOKEN": "alpha-claude",
                        "ALPHA_CODEX_TOKEN": "alpha-codex",
                        "ALPHA_GEMINI_KEY": "alpha-gemini",
                        "ALPHA_OPENCODE_TOKEN": "alpha-opencode",
                        "ALPHA_OPENCLAW_TOKEN": "alpha-openclaw",
                        "BETA_CLAUDE_TOKEN": "beta-claude",
                        "BETA_CODEX_TOKEN": "beta-codex",
                        "BETA_GEMINI_KEY": "beta-gemini",
                        "BETA_OPENCODE_TOKEN": "beta-opencode",
                        "BETA_OPENCLAW_TOKEN": "beta-openclaw",
                    },
                )
                rc_file = paths["root"] / ".testrc"
                rc_file.write_text("# existing rc\n", encoding="utf-8")
                env.update(
                    {
                        "SHELL": shell,
                        "BOOTSTRAP_HOME": str(paths["root"]),
                        "BOOTSTRAP_RC_FILE": str(rc_file),
                    }
                )

                self._run_bootstrap(env)
                add_provider(env, CCSW_PY, "alpha", base_url, cwd=REPO_ROOT)

                default_switch = run_shell(
                    shell,
                    f'source "{rc_file}"; ccsw alpha',
                    cwd=REPO_ROOT,
                    env=env,
                    check=True,
                )
                codex_switch = run_shell(
                    shell,
                    "\n".join(
                        [
                            f'source "{rc_file}"',
                            "ccsw codex alpha",
                            'printf "%s\\n" "${OPENAI_API_KEY-unset}"',
                        ]
                    ),
                    cwd=REPO_ROOT,
                    env=env,
                    check=True,
                )
                alias_switch = run_shell(
                    shell,
                    "\n".join(
                        [
                            f'source "{rc_file}"',
                            "cxsw alpha",
                            'printf "%s\\n" "${OPENAI_API_KEY-unset}"',
                        ]
                    ),
                    cwd=REPO_ROOT,
                    env=env,
                    check=True,
                )
                all_switch = run_shell(
                    shell,
                    "\n".join(
                        [
                            f'source "{rc_file}"',
                            "ccsw all alpha",
                            'printf "%s\\n" "$OPENAI_API_KEY|$GEMINI_API_KEY|$OPENCODE_CONFIG|$OPENCLAW_CONFIG_PATH"',
                        ]
                    ),
                    cwd=REPO_ROOT,
                    env=env,
                    check=True,
                )
                passthrough = run_shell(
                    shell,
                    "\n".join(
                        [
                            f'source "{rc_file}"',
                            "ccswitch list",
                        ]
                    ),
                    cwd=REPO_ROOT,
                    env=env,
                    check=True,
                )

                self.assertEqual(default_switch.stdout, "")
                self.assertIn("[claude]", default_switch.stderr)
                self.assertEqual(codex_switch.stdout.strip(), "alpha-codex")
                self.assertEqual(alias_switch.stdout.strip(), "alpha-codex")
                self.assertEqual(
                    all_switch.stdout.strip(),
                    "alpha-codex|alpha-gemini|"
                    f"{paths['root'] / '.ccswitch' / 'generated' / 'opencode' / 'alpha.json'}|"
                    f"{paths['root'] / '.ccswitch' / 'generated' / 'openclaw' / 'alpha.json5'}",
                )
                self.assertIn("Providers:", passthrough.stderr)
                self.assertEqual(passthrough.stdout, "")

    def test_shell_wrappers_cover_gcsw_opsw_clawsw_and_passthrough_commands(self) -> None:
        for shell in REAL_WRAPPER_SHELLS:
            with self.subTest(shell=shell), stub_server() as base_url, isolated_runtime_env() as paths:
                env = build_cli_env(
                    paths,
                    {
                        "ALPHA_CLAUDE_TOKEN": "alpha-claude",
                        "ALPHA_CODEX_TOKEN": "alpha-codex",
                        "ALPHA_GEMINI_KEY": "alpha-gemini",
                        "ALPHA_OPENCODE_TOKEN": "alpha-opencode",
                        "ALPHA_OPENCLAW_TOKEN": "alpha-openclaw",
                        "BETA_CLAUDE_TOKEN": "beta-claude",
                        "BETA_CODEX_TOKEN": "beta-codex",
                        "BETA_GEMINI_KEY": "beta-gemini",
                        "BETA_OPENCODE_TOKEN": "beta-opencode",
                        "BETA_OPENCLAW_TOKEN": "beta-openclaw",
                    },
                )
                rc_file = paths["root"] / ".testrc"
                rc_file.write_text("# existing rc\n", encoding="utf-8")
                env.update(
                    {
                        "SHELL": shell,
                        "BOOTSTRAP_HOME": str(paths["root"]),
                        "BOOTSTRAP_RC_FILE": str(rc_file),
                    }
                )

                self._run_bootstrap(env)
                add_provider(env, CCSW_PY, "alpha", base_url, cwd=REPO_ROOT)
                add_provider(env, CCSW_PY, "beta", base_url, cwd=REPO_ROOT)
                child = paths["root"] / "print_gemini.py"
                child.write_text(
                    "\n".join(
                        [
                            "import os",
                            "print(os.environ.get('GEMINI_API_KEY', 'unset'))",
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )

                gemini_switch = run_shell(
                    shell,
                    "\n".join(
                        [
                            f'source "{rc_file}"',
                            "gcsw alpha",
                            'printf "%s\\n" "${GEMINI_API_KEY-unset}"',
                        ]
                    ),
                    cwd=REPO_ROOT,
                    env=env,
                    check=True,
                )
                opencode_switch = run_shell(
                    shell,
                    "\n".join(
                        [
                            f'source "{rc_file}"',
                            "opsw alpha",
                            'printf "%s\\n" "${OPENCODE_CONFIG-unset}"',
                        ]
                    ),
                    cwd=REPO_ROOT,
                    env=env,
                    check=True,
                )
                openclaw_switch = run_shell(
                    shell,
                    "\n".join(
                        [
                            f'source "{rc_file}"',
                            "clawsw alpha",
                            'printf "%s\\n" "${OPENCLAW_CONFIG_PATH-unset}"',
                        ]
                    ),
                    cwd=REPO_ROOT,
                    env=env,
                    check=True,
                )
                settings_get = run_shell(
                    shell,
                    "\n".join(
                        [
                            f'source "{rc_file}"',
                            "ccsw settings get gemini_config_dir",
                        ]
                    ),
                    cwd=REPO_ROOT,
                    env=env,
                    check=True,
                )
                profile_commands = run_shell(
                    shell,
                    "\n".join(
                        [
                            f'source "{rc_file}"',
                            "ccsw profile add work --gemini alpha",
                            "ccsw profile show work",
                        ]
                    ),
                    cwd=REPO_ROOT,
                    env=env,
                    check=True,
                )
                profile_use = run_shell(
                    shell,
                    "\n".join(
                        [
                            f'source "{rc_file}"',
                            "ccsw profile use work",
                            'printf "%s\\n" "${GEMINI_API_KEY-unset}"',
                        ]
                    ),
                    cwd=REPO_ROOT,
                    env=env,
                    check=True,
                )
                rollback_env = run_shell(
                    shell,
                    "\n".join(
                        [
                            f'source "{rc_file}"',
                            "ccsw codex alpha",
                            "ccsw codex beta",
                            "ccsw rollback codex",
                            'printf "%s\\n" "${OPENAI_API_KEY-unset}"',
                        ]
                    ),
                    cwd=REPO_ROOT,
                    env=env,
                    check=True,
                )
                doctor_json = run_shell(
                    shell,
                    "\n".join(
                        [
                            f'source "{rc_file}"',
                            "ccsw doctor gemini alpha --json",
                        ]
                    ),
                    cwd=REPO_ROOT,
                    env=env,
                    check=True,
                )
                run_passthrough = run_shell(
                    shell,
                    "\n".join(
                        [
                            f'source "{rc_file}"',
                            f'ccsw run gemini alpha -- python3 "{child}"',
                        ]
                    ),
                    cwd=REPO_ROOT,
                    env=env,
                    check=True,
                )
                history_verbose = run_shell(
                    shell,
                    "\n".join(
                        [
                            f'source "{rc_file}"',
                            "ccsw history --tool gemini --action run-result --limit 1 --verbose",
                        ]
                    ),
                    cwd=REPO_ROOT,
                    env=env,
                    check=True,
                )

                self.assertEqual(gemini_switch.stdout.strip(), "alpha-gemini")
                self.assertEqual(
                    opencode_switch.stdout.strip(),
                    str(paths["root"] / ".ccswitch" / "generated" / "opencode" / "alpha.json"),
                )
                self.assertEqual(
                    openclaw_switch.stdout.strip(),
                    str(paths["root"] / ".ccswitch" / "generated" / "openclaw" / "alpha.json5"),
                )
                self.assertEqual(settings_get.stdout, "")
                self.assertIn("gemini_config_dir=None", settings_get.stderr)
                self.assertIn("Profile 'work' saved.", profile_commands.stderr)
                self.assertIn("[profile] work", profile_commands.stderr)
                self.assertEqual(profile_use.stdout.strip(), "alpha-gemini")
                self.assertEqual(rollback_env.stdout.strip(), "alpha-codex")
                self.assertIn("[rollback] Restored codex to provider 'alpha'", rollback_env.stderr)
                self.assertTrue(doctor_json.stdout.strip())
                self.assertEqual(json.loads(doctor_json.stdout)["tool"], "gemini")
                self.assertIn("alpha-gemini", run_passthrough.stdout)
                self.assertIn('"selected_candidate": "alpha"', history_verbose.stderr)


if __name__ == "__main__":
    unittest.main()
