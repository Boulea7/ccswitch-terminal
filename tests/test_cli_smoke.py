import json
import unittest
from pathlib import Path

import ccsw
from tests.support import (
    add_provider,
    build_cli_env,
    isolated_runtime_env,
    run_cli,
    stub_server,
    write_executable_script,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
CCSW_PY = REPO_ROOT / "ccsw.py"


class CliSmokeTests(unittest.TestCase):
    def test_direct_cli_help_and_missing_subcommand_contracts(self) -> None:
        with isolated_runtime_env() as paths:
            env = build_cli_env(paths)
            help_result = run_cli(
                ["python3", str(CCSW_PY), "-h"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            empty_result = run_cli(
                ["python3", str(CCSW_PY)],
                cwd=REPO_ROOT,
                env=env,
            )
            profile_result = run_cli(
                ["python3", str(CCSW_PY), "profile"],
                cwd=REPO_ROOT,
                env=env,
            )
            settings_result = run_cli(
                ["python3", str(CCSW_PY), "settings"],
                cwd=REPO_ROOT,
                env=env,
            )
            doctor_conflict = run_cli(
                ["python3", str(CCSW_PY), "doctor", "codex", "demo", "--deep", "--cached"],
                cwd=REPO_ROOT,
                env=env,
            )

        self.assertEqual(help_result.returncode, 0)
        self.assertIn("usage: ccsw", help_result.stdout)
        self.assertEqual(help_result.stderr, "")
        self.assertNotEqual(empty_result.returncode, 0)
        self.assertEqual(empty_result.stdout, "")
        self.assertIn("usage: ccsw", empty_result.stderr)
        self.assertNotEqual(profile_result.returncode, 0)
        self.assertIn("usage: ccsw", profile_result.stderr)
        self.assertNotEqual(settings_result.returncode, 0)
        self.assertIn("usage: ccsw", settings_result.stderr)
        self.assertNotEqual(doctor_conflict.returncode, 0)
        self.assertEqual(doctor_conflict.stdout, "")
        self.assertIn("not allowed with argument", doctor_conflict.stderr)

    def test_direct_cli_switch_stream_contract_by_tool(self) -> None:
        with stub_server() as base_url, isolated_runtime_env() as paths:
            env = build_cli_env(
                paths,
                {
                    "ALPHA_CLAUDE_TOKEN": "alpha-claude",
                    "ALPHA_CODEX_TOKEN": "alpha-codex",
                    "ALPHA_GEMINI_KEY": "alpha-gemini",
                    "ALPHA_OPENCODE_TOKEN": "alpha-opencode",
                    "ALPHA_OPENCLAW_TOKEN": "alpha-openclaw",
                },
            )
            add_provider(env, CCSW_PY, "alpha", base_url, cwd=REPO_ROOT)

            claude = run_cli(["python3", str(CCSW_PY), "claude", "alpha"], cwd=REPO_ROOT, env=env, check=True)
            codex = run_cli(["python3", str(CCSW_PY), "codex", "alpha"], cwd=REPO_ROOT, env=env, check=True)
            gemini = run_cli(["python3", str(CCSW_PY), "gemini", "alpha"], cwd=REPO_ROOT, env=env, check=True)
            opencode = run_cli(["python3", str(CCSW_PY), "opencode", "alpha"], cwd=REPO_ROOT, env=env, check=True)
            openclaw = run_cli(["python3", str(CCSW_PY), "openclaw", "alpha"], cwd=REPO_ROOT, env=env, check=True)

        self.assertEqual(claude.stdout, "")
        self.assertIn("[claude]", claude.stderr)
        self.assertIn("export OPENAI_API_KEY='alpha-codex'", codex.stdout)
        self.assertIn("[codex]", codex.stderr)
        self.assertIn("export GEMINI_API_KEY='alpha-gemini'", gemini.stdout)
        self.assertIn("[gemini]", gemini.stderr)
        self.assertIn("export OPENCODE_CONFIG=", opencode.stdout)
        self.assertIn("[opencode]", opencode.stderr)
        self.assertIn("export OPENCLAW_CONFIG_PATH=", openclaw.stdout)
        self.assertIn("[openclaw]", openclaw.stderr)

    def test_switch_all_via_cli_updates_all_and_emits_exports(self) -> None:
        with stub_server() as base_url, isolated_runtime_env() as paths:
            env = build_cli_env(
                paths,
                {
                    "ALPHA_CLAUDE_TOKEN": "alpha-claude",
                    "ALPHA_CODEX_TOKEN": "alpha-codex",
                    "ALPHA_GEMINI_KEY": "alpha-gemini",
                    "ALPHA_OPENCODE_TOKEN": "alpha-opencode",
                    "ALPHA_OPENCLAW_TOKEN": "alpha-openclaw",
                },
            )
            add_provider(env, CCSW_PY, "alpha", base_url, cwd=REPO_ROOT)

            switch_all = run_cli(
                ["python3", str(CCSW_PY), "all", "alpha"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            show = run_cli(
                ["python3", str(CCSW_PY), "show"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            store = ccsw.load_store()

        self.assertIn("export OPENAI_API_KEY='alpha-codex'", switch_all.stdout)
        self.assertIn("export GEMINI_API_KEY='alpha-gemini'", switch_all.stdout)
        self.assertIn("export OPENCODE_CONFIG=", switch_all.stdout)
        self.assertIn("export OPENCLAW_CONFIG_PATH=", switch_all.stdout)
        self.assertEqual(store["active"]["claude"], "alpha")
        self.assertEqual(store["active"]["codex"], "alpha")
        self.assertEqual(store["active"]["gemini"], "alpha")
        self.assertEqual(store["active"]["opencode"], "alpha")
        self.assertEqual(store["active"]["openclaw"], "alpha")
        self.assertIn("[claude] alpha", show.stderr)
        self.assertIn("[codex] alpha", show.stderr)
        self.assertIn("[gemini] alpha", show.stderr)

    def test_switch_all_via_cli_fail_closed_on_unresolved_secret_without_exports(self) -> None:
        with stub_server() as base_url, isolated_runtime_env() as paths:
            env = build_cli_env(
                paths,
                {
                    "BROKEN_CLAUDE_TOKEN": "broken-claude",
                    "BROKEN_GEMINI_KEY": "broken-gemini",
                    "BROKEN_OPENCODE_TOKEN": "broken-opencode",
                    "BROKEN_OPENCLAW_TOKEN": "broken-openclaw",
                },
            )
            add_provider(env, CCSW_PY, "broken", base_url, cwd=REPO_ROOT)

            switch_all = run_cli(
                ["python3", str(CCSW_PY), "all", "broken"],
                cwd=REPO_ROOT,
                env=env,
            )
            store = ccsw.load_store()

        self.assertNotEqual(switch_all.returncode, 0)
        self.assertEqual(switch_all.stdout, "")
        self.assertIn("unresolved codex secret", switch_all.stderr)
        self.assertTrue(all(store["active"][tool] is None for tool in ccsw.ALL_TOOLS))

    def test_switch_all_via_cli_reports_skipped_tools_for_partial_provider(self) -> None:
        with stub_server() as base_url, isolated_runtime_env() as paths:
            env = build_cli_env(
                paths,
                {
                    "FULL_CLAUDE_TOKEN": "full-claude",
                    "FULL_CODEX_TOKEN": "full-codex",
                    "FULL_GEMINI_KEY": "full-gemini",
                    "FULL_OPENCODE_TOKEN": "full-opencode",
                    "FULL_OPENCLAW_TOKEN": "full-openclaw",
                    "PARTIAL_CLAUDE_TOKEN": "partial-claude",
                },
            )
            add_provider(env, CCSW_PY, "full", base_url, cwd=REPO_ROOT)
            run_cli(
                [
                    "python3",
                    str(CCSW_PY),
                    "add",
                    "partial",
                    "--claude-url",
                    f"{base_url}/anthropic/partial",
                    "--claude-token",
                    "$PARTIAL_CLAUDE_TOKEN",
                ],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            run_cli(["python3", str(CCSW_PY), "all", "full"], cwd=REPO_ROOT, env=env, check=True)

            switch_partial = run_cli(
                ["python3", str(CCSW_PY), "all", "partial"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            store = ccsw.load_store()

        self.assertIn("[claude]", switch_partial.stderr)
        self.assertIn("[codex] Skipped: provider 'partial' has no codex config.", switch_partial.stderr)
        self.assertIn("[gemini] Skipped: provider 'partial' has no gemini config.", switch_partial.stderr)
        self.assertEqual(store["active"]["claude"], "partial")
        self.assertEqual(store["active"]["codex"], "full")
        self.assertEqual(store["active"]["gemini"], "full")

    def test_eval_based_gemini_and_all_switching_via_direct_cli_shell_contract(self) -> None:
        with stub_server() as base_url, isolated_runtime_env() as paths:
            env = build_cli_env(
                paths,
                {
                    "ALPHA_CLAUDE_TOKEN": "alpha-claude",
                    "ALPHA_CODEX_TOKEN": "alpha-codex",
                    "ALPHA_GEMINI_KEY": "alpha-gemini",
                    "ALPHA_OPENCODE_TOKEN": "alpha-opencode",
                    "ALPHA_OPENCLAW_TOKEN": "alpha-openclaw",
                },
            )
            add_provider(env, CCSW_PY, "alpha", base_url, cwd=REPO_ROOT)

            gemini_eval = run_cli(
                [
                    "bash",
                    "-lc",
                    "\n".join(
                        [
                            f'eval "$(python3 "{CCSW_PY}" gemini alpha)"',
                            'printf "%s\\n" "${GEMINI_API_KEY-unset}"',
                        ]
                    ),
                ],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            all_eval = run_cli(
                [
                    "bash",
                    "-lc",
                    "\n".join(
                        [
                            f'eval "$(python3 "{CCSW_PY}" all alpha)"',
                            'printf "%s\\n" "$OPENAI_API_KEY|$GEMINI_API_KEY|$OPENCODE_CONFIG|$OPENCLAW_CONFIG_PATH"',
                        ]
                    ),
                ],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )

        self.assertEqual(gemini_eval.stdout.strip(), "alpha-gemini")
        self.assertEqual(
            all_eval.stdout.strip(),
            "alpha-codex|alpha-gemini|"
            f"{paths['root'] / '.ccswitch' / 'generated' / 'opencode' / 'alpha.json'}|"
            f"{paths['root'] / '.ccswitch' / 'generated' / 'openclaw' / 'alpha.json5'}",
        )

    def test_direct_cli_doctor_all_settings_profile_and_import_current_smoke(self) -> None:
        with stub_server() as base_url, isolated_runtime_env() as paths:
            env = build_cli_env(
                paths,
                {
                    "ALPHA_CLAUDE_TOKEN": "alpha-claude",
                    "ALPHA_CODEX_TOKEN": "alpha-codex",
                    "ALPHA_GEMINI_KEY": "alpha-gemini",
                    "ALPHA_OPENCODE_TOKEN": "alpha-opencode",
                    "ALPHA_OPENCLAW_TOKEN": "alpha-openclaw",
                },
            )
            add_provider(env, CCSW_PY, "alpha", base_url, cwd=REPO_ROOT)
            run_cli(["python3", str(CCSW_PY), "all", "alpha"], cwd=REPO_ROOT, env=env, check=True)

            doctor_all = run_cli(
                ["python3", str(CCSW_PY), "doctor", "all", "--json"],
                cwd=REPO_ROOT,
                env=env,
            )
            settings_before = run_cli(
                ["python3", str(CCSW_PY), "settings", "get", "gemini_config_dir"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            settings_set_null = run_cli(
                ["python3", str(CCSW_PY), "settings", "set", "gemini_config_dir", "null"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            settings_after = run_cli(
                ["python3", str(CCSW_PY), "settings", "get", "gemini_config_dir"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            run_cli(
                [
                    "python3",
                    str(CCSW_PY),
                    "profile",
                    "add",
                    "work",
                    "--claude",
                    "alpha",
                    "--gemini",
                    "alpha",
                ],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            profile_list = run_cli(
                ["python3", str(CCSW_PY), "profile", "list"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            profile_show = run_cli(
                ["python3", str(CCSW_PY), "profile", "show", "work"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            profile_remove = run_cli(
                ["python3", str(CCSW_PY), "profile", "remove", "work"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            profile_list_after = run_cli(
                ["python3", str(CCSW_PY), "profile", "list"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            import_claude = run_cli(
                [
                    "python3",
                    str(CCSW_PY),
                    "import",
                    "current",
                    "claude",
                    "rescued-claude",
                    "--allow-literal-secrets",
                ],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            import_gemini = run_cli(
                [
                    "python3",
                    str(CCSW_PY),
                    "import",
                    "current",
                    "gemini",
                    "rescued-gemini",
                    "--allow-literal-secrets",
                ],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            store = ccsw.load_store()

        doctor_lines = [json.loads(line) for line in doctor_all.stdout.splitlines() if line.strip()]
        doctor_statuses = {line["tool"]: line["status"] for line in doctor_lines}
        self.assertEqual(doctor_all.returncode, 1)
        self.assertEqual(len(doctor_lines), len(ccsw.ALL_TOOLS))
        self.assertEqual([line["tool"] for line in doctor_lines], list(ccsw.ALL_TOOLS))
        self.assertEqual(
            doctor_statuses,
            {
                "claude": "ok",
                "codex": "ok",
                "gemini": "ok",
                "opencode": "degraded",
                "openclaw": "degraded",
            },
        )
        self.assertEqual(settings_before.stderr.strip(), "gemini_config_dir=None")
        self.assertIn("Setting updated: gemini_config_dir=None", settings_set_null.stderr)
        self.assertEqual(settings_after.stderr.strip(), "gemini_config_dir=None")
        self.assertIn("work: claude, gemini", profile_list.stderr)
        self.assertIn("[profile] work", profile_show.stderr)
        self.assertIn("claude: alpha", profile_show.stderr)
        self.assertIn("gemini: alpha", profile_show.stderr)
        self.assertIn("Removed profile: work", profile_remove.stderr)
        self.assertIn("No profiles configured.", profile_list_after.stderr)
        self.assertIn("Imported current claude config", import_claude.stderr)
        self.assertIn("Imported current gemini config", import_gemini.stderr)
        self.assertEqual(
            store["providers"]["rescued-claude"]["claude"]["token"],
            "alpha-claude",
        )
        self.assertEqual(
            store["providers"]["rescued-gemini"]["gemini"]["api_key"],
            "alpha-gemini",
        )

    def test_direct_cli_repair_all_and_failed_history_verbose_smoke(self) -> None:
        with stub_server() as base_url, isolated_runtime_env() as paths:
            env = build_cli_env(
                paths,
                {
                    "ALPHA_CLAUDE_TOKEN": "alpha-claude",
                    "ALPHA_CODEX_TOKEN": "alpha-codex",
                    "ALPHA_GEMINI_KEY": "alpha-gemini",
                    "ALPHA_OPENCODE_TOKEN": "alpha-opencode",
                    "ALPHA_OPENCLAW_TOKEN": "alpha-openclaw",
                },
            )
            add_provider(env, CCSW_PY, "alpha", base_url, cwd=REPO_ROOT)
            run_cli(["python3", str(CCSW_PY), "codex", "alpha"], cwd=REPO_ROOT, env=env, check=True)
            failed_run = run_cli(
                [
                    "python3",
                    str(CCSW_PY),
                    "run",
                    "gemini",
                    "alpha",
                    "--",
                    "python3",
                    "-c",
                    "import sys; sys.stderr.write('boom\\n'); raise SystemExit(1)",
                ],
                cwd=REPO_ROOT,
                env=env,
            )

            auth_path = paths["home"] / ".codex" / "auth.json"
            config_path = paths["home"] / ".codex" / "config.toml"
            runtime_root = paths["root"] / ".ccswitch" / "tmp" / "run-smoke-repair-all"
            runtime_root.mkdir(parents=True, exist_ok=True)
            manifest = ccsw._build_runtime_manifest(
                "codex",
                lease_id="codex-smoke-all-lease",
                source_kind="provider",
                requested_target="alpha",
                runtime_root=runtime_root,
            )
            manifest.update(
                {
                    "selected_candidate": "alpha",
                    "phase": "completed",
                    "stale": True,
                    "stale_reason": "restore_failed",
                    "restore_status": "restore_failed",
                    "cleanup_status": "pending",
                    "owner_pid": 999999,
                    "owner_started_at": "dead-process",
                    "snapshots": ccsw._json_ready_snapshots(
                        {
                            auth_path: auth_path.read_bytes(),
                            config_path: config_path.read_bytes(),
                        }
                    ),
                    "written_states": ccsw._json_ready_path_states(
                        {
                            auth_path: ccsw._capture_path_state(auth_path),
                            config_path: ccsw._capture_path_state(config_path),
                        }
                    ),
                    "restore_groups": [[str(auth_path), str(config_path)]],
                    "ephemeral_paths": [],
                    "snapshot_written": True,
                }
            )
            ccsw.upsert_managed_target("codex", manifest)

            repair_all = run_cli(
                ["python3", str(CCSW_PY), "repair", "all"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            history_failed = run_cli(
                ["python3", str(CCSW_PY), "history", "--failed-only", "--verbose", "--limit", "10"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )

        self.assertNotEqual(failed_run.returncode, 0)
        self.assertIn("[repair] claude: no runtime lease", repair_all.stderr)
        self.assertIn("[repair] codex: repaired and cleared runtime lease", repair_all.stderr)
        self.assertIn("[repair] gemini: no runtime lease", repair_all.stderr)
        self.assertIn("run-result", history_failed.stderr)
        self.assertIn('"returncode": 1', history_failed.stderr)
        self.assertIn('"final_failure_type": "non_retryable_command"', history_failed.stderr)
        self.assertIn("run-attempt", history_failed.stderr)

    def test_profile_use_and_import_current_opencode_openclaw_via_cli(self) -> None:
        with stub_server() as base_url, isolated_runtime_env() as paths:
            env = build_cli_env(
                paths,
                {
                    "ALPHA_CLAUDE_TOKEN": "alpha-claude",
                    "ALPHA_CODEX_TOKEN": "alpha-codex",
                    "ALPHA_GEMINI_KEY": "alpha-gemini",
                    "ALPHA_OPENCODE_TOKEN": "alpha-opencode",
                    "ALPHA_OPENCLAW_TOKEN": "alpha-openclaw",
                },
            )
            add_provider(env, CCSW_PY, "alpha", base_url, cwd=REPO_ROOT)
            run_cli(
                [
                    "python3",
                    str(CCSW_PY),
                    "profile",
                    "add",
                    "work",
                    "--claude",
                    "alpha",
                    "--codex",
                    "alpha",
                    "--gemini",
                    "alpha",
                    "--opencode",
                    "alpha",
                    "--openclaw",
                    "alpha",
                ],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )

            profile_use = run_cli(
                ["python3", str(CCSW_PY), "profile", "use", "work"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            show = run_cli(
                ["python3", str(CCSW_PY), "show"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            import_opencode = run_cli(
                [
                    "python3",
                    str(CCSW_PY),
                    "import",
                    "current",
                    "opencode",
                    "rescued-opencode",
                    "--allow-literal-secrets",
                ],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            import_openclaw = run_cli(
                [
                    "python3",
                    str(CCSW_PY),
                    "import",
                    "current",
                    "openclaw",
                    "rescued-openclaw",
                    "--allow-literal-secrets",
                ],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )

            store = ccsw.load_store()
            opencode_overlay_exists = (
                paths["root"] / ".ccswitch" / "generated" / "opencode" / "alpha.json"
            ).exists()
            openclaw_overlay_exists = (
                paths["root"] / ".ccswitch" / "generated" / "openclaw" / "alpha.json5"
            ).exists()

        self.assertIn("export OPENCODE_CONFIG=", profile_use.stdout)
        self.assertIn("export OPENCLAW_CONFIG_PATH=", profile_use.stdout)
        self.assertIn("[opencode] alpha", show.stderr)
        self.assertIn("[openclaw] alpha", show.stderr)
        self.assertIn("Imported current opencode config", import_opencode.stderr)
        self.assertIn("Imported current openclaw config", import_openclaw.stderr)
        self.assertTrue(opencode_overlay_exists)
        self.assertTrue(openclaw_overlay_exists)
        self.assertEqual(store["active"]["opencode"], "alpha")
        self.assertEqual(store["active"]["openclaw"], "alpha")
        self.assertEqual(
            store["providers"]["rescued-opencode"]["opencode"]["provider_id"],
            "alpha",
        )
        self.assertEqual(
            store["providers"]["rescued-openclaw"]["openclaw"]["provider_id"],
            "alpha",
        )

    def test_import_current_openclaw_accepts_json5_style_config(self) -> None:
        with isolated_runtime_env() as paths:
            env = build_cli_env(paths)
            openclaw_dir = paths["home"] / ".openclaw"
            openclaw_dir.mkdir(parents=True, exist_ok=True)
            (openclaw_dir / "openclaw.json").write_text(
                "{\n"
                "  models: {\n"
                "    providers: {\n"
                "      demo: {\n"
                "        baseUrl: 'https://relay.example.com/v1',\n"
                "        apiKey: 'demo-token',\n"
                "        api: 'responses',\n"
                "      },\n"
                "    },\n"
                "  },\n"
                "  agents: {\n"
                "    defaults: {\n"
                "      model: {\n"
                "        primary: 'claude-sonnet-4',\n"
                "      },\n"
                "    },\n"
                "  },\n"
                "}\n",
                encoding="utf-8",
            )
            (openclaw_dir / ".env").write_text("OPENCLAW_PROFILE=work\n", encoding="utf-8")

            import_result = run_cli(
                [
                    "python3",
                    str(CCSW_PY),
                    "import",
                    "current",
                    "openclaw",
                    "rescued-openclaw",
                    "--allow-literal-secrets",
                ],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            store = ccsw.load_store()

        self.assertIn("Imported current openclaw config", import_result.stderr)
        imported = store["providers"]["rescued-openclaw"]["openclaw"]
        self.assertEqual(imported["base_url"], "https://relay.example.com/v1")
        self.assertEqual(imported["token"], "demo-token")
        self.assertEqual(imported["api"], "responses")
        self.assertEqual(imported["model"], "claude-sonnet-4")
        self.assertEqual(imported["profile"], "work")

    def test_run_profile_fallback_records_history_via_cli(self) -> None:
        with stub_server() as base_url, isolated_runtime_env() as paths:
            env = build_cli_env(
                paths,
                {
                    "FIRST_CLAUDE_TOKEN": "first-claude",
                    "FIRST_CODEX_TOKEN": "first-codex",
                    "FIRST_GEMINI_KEY": "first-gemini",
                    "FIRST_OPENCODE_TOKEN": "first-opencode",
                    "FIRST_OPENCLAW_TOKEN": "first-openclaw",
                    "SECOND_CLAUDE_TOKEN": "second-claude",
                    "SECOND_CODEX_TOKEN": "second-codex",
                    "SECOND_GEMINI_KEY": "second-gemini",
                    "SECOND_OPENCODE_TOKEN": "second-opencode",
                    "SECOND_OPENCLAW_TOKEN": "second-openclaw",
                },
            )
            add_provider(env, CCSW_PY, "first", base_url, cwd=REPO_ROOT)
            add_provider(env, CCSW_PY, "second", base_url, cwd=REPO_ROOT)
            run_cli(
                [
                    "python3",
                    str(CCSW_PY),
                    "profile",
                    "add",
                    "work",
                    "--codex",
                    "first,second",
                ],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            run_cli(
                ["python3", str(CCSW_PY), "codex", "first"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            child = write_executable_script(
                paths["root"] / "child.py",
                "\n".join(
                    [
                        "import os, sys",
                        "token = os.environ.get('OPENAI_API_KEY')",
                        "if token == 'first-codex':",
                        "    sys.stderr.write('connection refused\\n')",
                        "    raise SystemExit(1)",
                        "print(token)",
                    ]
                )
                + "\n",
            )

            run_result = run_cli(
                ["python3", str(CCSW_PY), "run", "codex", "work", "--", "python3", str(child)],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            history_result = run_cli(
                ["python3", str(CCSW_PY), "history", "--tool", "codex", "--action", "run-result", "--limit", "5"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            store = ccsw.load_store()
            history_entries = ccsw.list_history(limit=5, tool="codex", action="run-result")

        self.assertIn("second-codex", run_result.stdout)
        self.assertIn("Temporary fallback used for this command: second", run_result.stderr)
        self.assertEqual(store["active"]["codex"], "first")
        self.assertEqual(history_entries[0]["payload"]["selected_candidate"], "second")
        self.assertTrue(history_entries[0]["payload"]["fallback_used"])
        self.assertEqual(history_entries[0]["payload"]["restore_status"], "restored")
        self.assertIn("selected=second", history_result.stderr)
        self.assertIn("fallback_used=True", history_result.stderr)

    def test_rollback_via_cli_restores_previous_provider(self) -> None:
        with stub_server() as base_url, isolated_runtime_env() as paths:
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
            add_provider(env, CCSW_PY, "alpha", base_url, cwd=REPO_ROOT)
            add_provider(env, CCSW_PY, "beta", base_url, cwd=REPO_ROOT)
            run_cli(["python3", str(CCSW_PY), "codex", "alpha"], cwd=REPO_ROOT, env=env, check=True)
            run_cli(["python3", str(CCSW_PY), "codex", "beta"], cwd=REPO_ROOT, env=env, check=True)
            rollback = run_cli(
                ["python3", str(CCSW_PY), "rollback", "codex"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            history_result = run_cli(
                ["python3", str(CCSW_PY), "history", "--tool", "codex", "--action", "rollback-result", "--limit", "5"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            store = ccsw.load_store()
            auth = json.loads((paths["home"] / ".codex" / "auth.json").read_text(encoding="utf-8"))

        self.assertIn("[rollback] Restored codex to provider 'alpha'", rollback.stderr)
        self.assertEqual(store["active"]["codex"], "alpha")
        self.assertEqual(auth["OPENAI_API_KEY"], "alpha-codex")
        self.assertIn("status=restored", history_result.stderr)
        self.assertIn("target=alpha", history_result.stderr)

    def test_repair_then_doctor_via_cli_clears_stale_lease(self) -> None:
        with stub_server() as base_url, isolated_runtime_env() as paths:
            env = build_cli_env(
                paths,
                {
                    "ALPHA_CLAUDE_TOKEN": "alpha-claude",
                    "ALPHA_CODEX_TOKEN": "alpha-codex",
                    "ALPHA_GEMINI_KEY": "alpha-gemini",
                    "ALPHA_OPENCODE_TOKEN": "alpha-opencode",
                    "ALPHA_OPENCLAW_TOKEN": "alpha-openclaw",
                },
            )
            add_provider(env, CCSW_PY, "alpha", base_url, cwd=REPO_ROOT)
            run_cli(["python3", str(CCSW_PY), "codex", "alpha"], cwd=REPO_ROOT, env=env, check=True)

            store = ccsw.load_store()
            auth_path = paths["home"] / ".codex" / "auth.json"
            config_path = paths["home"] / ".codex" / "config.toml"
            runtime_root = paths["root"] / ".ccswitch" / "tmp" / "run-smoke-repair"
            runtime_root.mkdir(parents=True, exist_ok=True)
            manifest = ccsw._build_runtime_manifest(
                "codex",
                lease_id="codex-smoke-lease",
                source_kind="provider",
                requested_target="alpha",
                runtime_root=runtime_root,
            )
            manifest.update(
                {
                    "selected_candidate": "alpha",
                    "phase": "completed",
                    "stale": True,
                    "stale_reason": "restore_failed",
                    "restore_status": "restore_failed",
                    "cleanup_status": "pending",
                    "owner_pid": 999999,
                    "owner_started_at": "dead-process",
                    "snapshots": ccsw._json_ready_snapshots(
                        {
                            auth_path: auth_path.read_bytes(),
                            config_path: config_path.read_bytes(),
                        }
                    ),
                    "written_states": ccsw._json_ready_path_states(
                        {
                            auth_path: ccsw._capture_path_state(auth_path),
                            config_path: ccsw._capture_path_state(config_path),
                        }
                    ),
                    "restore_groups": [[str(auth_path), str(config_path)]],
                    "ephemeral_paths": [],
                    "snapshot_written": True,
                }
            )
            ccsw.upsert_managed_target("codex", manifest)

            doctor_before = run_cli(
                ["python3", str(CCSW_PY), "doctor", "codex", "alpha", "--json"],
                cwd=REPO_ROOT,
                env=env,
            )
            repair = run_cli(
                ["python3", str(CCSW_PY), "repair", "codex"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            doctor_after = run_cli(
                ["python3", str(CCSW_PY), "doctor", "codex", "alpha", "--json"],
                cwd=REPO_ROOT,
                env=env,
            )

        before_payload = json.loads(doctor_before.stdout.strip())
        after_payload = json.loads(doctor_after.stdout.strip())
        self.assertEqual(doctor_before.returncode, 1)
        self.assertEqual(before_payload["summary_reason"], "stale_lease")
        self.assertEqual(before_payload["checks"]["runtime_lease_check"]["reason_code"], "stale_lease")
        self.assertIn("[repair] codex: repaired and cleared runtime lease", repair.stderr)
        self.assertEqual(doctor_after.returncode, 0)
        self.assertEqual(after_payload["status"], "ok")
        self.assertEqual(after_payload["checks"]["runtime_lease_check"]["reason_code"], "runtime_lease_absent")

    def test_settings_override_codex_via_cli_writes_to_override_dir(self) -> None:
        with stub_server() as base_url, isolated_runtime_env() as paths:
            override_dir = paths["root"] / "alt-codex"
            env = build_cli_env(
                paths,
                {
                    "ALPHA_CLAUDE_TOKEN": "alpha-claude",
                    "ALPHA_CODEX_TOKEN": "alpha-codex",
                    "ALPHA_GEMINI_KEY": "alpha-gemini",
                    "ALPHA_OPENCODE_TOKEN": "alpha-opencode",
                    "ALPHA_OPENCLAW_TOKEN": "alpha-openclaw",
                },
            )
            add_provider(env, CCSW_PY, "alpha", base_url, cwd=REPO_ROOT)
            settings_set = run_cli(
                ["python3", str(CCSW_PY), "settings", "set", "codex_config_dir", str(override_dir)],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            switch_codex = run_cli(
                ["python3", str(CCSW_PY), "codex", "alpha"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            doctor = run_cli(
                ["python3", str(CCSW_PY), "doctor", "codex", "alpha", "--json"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            imported = run_cli(
                [
                    "python3",
                    str(CCSW_PY),
                    "import",
                    "current",
                    "codex",
                    "rescued-codex",
                    "--allow-literal-secrets",
                ],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            auth_exists = (override_dir / "auth.json").exists()
            config_exists = (override_dir / "config.toml").exists()
            default_auth_exists = (paths["home"] / ".codex" / "auth.json").exists()

        doctor_payload = json.loads(doctor.stdout.strip())
        self.assertIn("Setting updated: codex_config_dir=", settings_set.stderr)
        self.assertIn("export OPENAI_API_KEY='alpha-codex'", switch_codex.stdout)
        self.assertTrue(auth_exists)
        self.assertTrue(config_exists)
        self.assertFalse(default_auth_exists)
        self.assertEqual(doctor_payload["detail"]["target_config_dir"], str(override_dir))
        self.assertIn("Imported current codex config", imported.stderr)

    def test_doctor_cached_history_and_run_missing_command_via_cli(self) -> None:
        with stub_server() as base_url, isolated_runtime_env() as paths:
            env = build_cli_env(
                paths,
                {
                    "ALPHA_CLAUDE_TOKEN": "alpha-claude",
                    "ALPHA_CODEX_TOKEN": "alpha-codex",
                    "ALPHA_GEMINI_KEY": "alpha-gemini",
                    "ALPHA_OPENCODE_TOKEN": "alpha-opencode",
                    "ALPHA_OPENCLAW_TOKEN": "alpha-openclaw",
                },
            )
            add_provider(env, CCSW_PY, "alpha", base_url, cwd=REPO_ROOT)
            run_cli(["python3", str(CCSW_PY), "codex", "alpha"], cwd=REPO_ROOT, env=env, check=True)
            run_cli(
                ["python3", str(CCSW_PY), "doctor", "codex", "alpha", "--json"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            cached = run_cli(
                ["python3", str(CCSW_PY), "doctor", "codex", "alpha", "--cached", "--json"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            history = run_cli(
                ["python3", str(CCSW_PY), "doctor", "codex", "alpha", "--history", "--json"],
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            missing_cmd = run_cli(
                ["python3", str(CCSW_PY), "run", "codex", "alpha", "--"],
                cwd=REPO_ROOT,
                env=env,
            )

        cached_payload = json.loads(cached.stdout.strip())
        history_payload = json.loads(history.stdout.strip())
        self.assertEqual(cached_payload["status"], "ok")
        self.assertEqual(cached_payload["probe_mode"], "cached")
        self.assertEqual(history_payload["status"], "history")
        self.assertEqual(history_payload["probe_mode"], "history")
        self.assertNotEqual(missing_cmd.returncode, 0)
        self.assertEqual(missing_cmd.stdout, "")
        self.assertIn("Missing command after --", missing_cmd.stderr)


if __name__ == "__main__":
    unittest.main()
