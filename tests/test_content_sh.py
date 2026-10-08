"""Bounded shell-wrapper tests with a local stand-in for the Python process."""

import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class ContentShellTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="content wrapper ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        tools = self.root / "tools"
        tools.mkdir()
        self.script = tools / "content.sh"
        shutil.copyfile(REPO_ROOT / "tools/content.sh", self.script)
        # A stand-in records exactly what the shell forwards and controls its exit.
        # It does not invoke the real validator or any provider API.
        self.record = self.root / "arguments.txt"
        self.invoked = self.root / "invoked"
        interpreter = tools / "python3"
        interpreter.write_text(
            '#!/bin/sh\n'
            ': > "$TEST_INVOKED"\n'
            'printf "%s\\n" "$@" > "$TEST_ARGUMENTS"\n'
            'exit "${TEST_EXIT_CODE:-0}"\n', encoding="utf-8")
        interpreter.chmod(0o755)
        self.environment = dict(os.environ, PATH=str(tools) + os.pathsep + os.defpath,
                                TEST_ARGUMENTS=str(self.record), TEST_INVOKED=str(self.invoked),
                                TEST_EXIT_CODE="0")

    def run_command(self, *arguments):
        # Run outside the script's directory to verify its own ROOT resolution.
        return subprocess.run(["sh", str(self.script), *arguments],
                              cwd=self.root.parent, env=self.environment,
                              capture_output=True, text=True, timeout=5, check=False)

    def test_commands_forward_exact_arguments_including_spaces(self):
        output = str(self.root / "coverage report.json")
        cases = [(('validate',), []),
                 (('indexes',), ["--generate-indexes"]),
                 (('coverage', '--out', output), ["--coverage-out", output])]
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                result = self.run_command(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(self.invoked.exists())
                self.assertEqual(self.record.read_text().splitlines(),
                                 [str(self.root / "tools/validate.py"), *expected])

    def test_validator_failure_exit_code_is_preserved(self):
        self.environment["TEST_EXIT_CODE"] = "7"
        result = self.run_command("validate")
        self.assertEqual(result.returncode, 7)

    def test_help_exits_successfully_without_running_validator(self):
        for arguments in ((), ("-h",), ("--help",), ("help",)):
            with self.subTest(arguments=arguments):
                result = self.run_command(*arguments)
                self.assertEqual(result.returncode, 0)
                self.assertIn("usage: content.sh", result.stderr)
                self.assertFalse(self.invoked.exists())

    def test_invalid_command_or_coverage_arguments_exit_two(self):
        for arguments in (("unknown",), ("coverage",), ("coverage", "--out"),
                          ("coverage", "--out", ""), ("coverage", "--wrong", "report.json")):
            with self.subTest(arguments=arguments):
                result = self.run_command(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertIn("usage: content.sh", result.stderr)
                self.assertFalse(self.invoked.exists())


if __name__ == "__main__":
    unittest.main()
