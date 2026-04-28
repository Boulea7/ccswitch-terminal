import unittest
import os
from pathlib import Path

import ccsw


REPO_ROOT = Path(__file__).resolve().parent.parent
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


class RepoWorkflowContractTests(unittest.TestCase):
    def test_ci_shellcheck_uses_explicit_release_version(self) -> None:
        lines = CI_WORKFLOW.read_text(encoding="utf-8").splitlines()
        shellcheck_step_start = None

        for index, line in enumerate(lines):
            if line.strip() == "- name: ShellCheck":
                shellcheck_step_start = index
                break

        self.assertIsNotNone(shellcheck_step_start, "ShellCheck step is missing from CI workflow")

        step_lines: list[str] = []
        for line in lines[shellcheck_step_start + 1 :]:
            if line.startswith("      - name:"):
                break
            step_lines.append(line)

        version_lines = [line.strip() for line in step_lines if line.strip().startswith("version:")]

        self.assertEqual(len(version_lines), 1, "ShellCheck step should pin exactly one explicit version")
        self.assertRegex(version_lines[0], r"^version:\s+v\d+\.\d+\.\d+$")
        self.assertNotIn("stable", version_lines[0])

    def test_test_package_isolates_default_runtime_state(self) -> None:
        self.assertIn("ccsw-test-home-", os.environ["HOME"])
        self.assertTrue(str(ccsw.CCSWITCH_DIR).startswith(os.environ["HOME"]))
        self.assertTrue(str(ccsw.CODEX_AUTH).startswith(os.environ["HOME"]))
        self.assertNotIn("OPENCLAW_CONFIG_PATH", os.environ)
        self.assertNotIn("OPENCLAW_PROFILE", os.environ)


if __name__ == "__main__":
    unittest.main()
