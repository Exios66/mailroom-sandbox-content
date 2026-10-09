"""tools/load_with_consumer.py and the consumer-loader step of tools/ci.sh (K-06).

Offline and fast. A fake mailroom-reloaded checkout with the same loader API
(load_content, ValidationReport.errors, ContentSet) is built in a temp dir. The
script runs as a subprocess so every case imports from scratch. The ci.sh cases
run a copy of ci.sh in a temp git repo with a stub interpreter, never the real
validator and never the full CI.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "load_with_consumer.py"

# Stands in for the consumer's package __init__, which fails without heavy deps.
HEAVY_PACKAGE_INIT = "import definitely_missing_heavy_dependency\n"

FAKE_SCHEMA = (
    '{"type": "object", "required": ["name"], "properties": {"name": '
    '{"type": "string", "pattern": "^[A-G][0-9]+_[a-z0-9_]+$"}}}\n'
)

FAKE_LOADER = textwrap.dedent('''\
    """Stand-in for mailroom_reloaded.sandbox.content.loader (same API shape)."""
    from __future__ import annotations

    from dataclasses import dataclass, field
    import json
    from pathlib import Path
    import re

    import yaml

    SCHEMA_PATH = Path(__file__).resolve().parents[4] / "schemas" / "scenario.v2.json"


    @dataclass
    class ValidationReport:
        errors: list[str] = field(default_factory=list)
        checked: int = 0


    @dataclass
    class ContentSet:
        root: Path
        kind: str
        meta: dict
        scenarios: dict
        registry: dict
        personas: dict
        gen_specs: dict
        report: ValidationReport


    def load_content(root=".", *, strict=False):
        root = Path(root)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        pattern = re.compile(schema["properties"]["name"]["pattern"])
        report = ValidationReport()
        scenarios = {}
        for path in sorted((root / "scenarios").rglob("*.yaml")):
            obj = yaml.safe_load(path.read_text(encoding="utf-8"))
            report.checked += 1
            name = str(obj.get("name", ""))
            if not pattern.match(name):
                report.errors.append(
                    f"{path.relative_to(root)}: name: {name!r} does not match {pattern.pattern!r}")
            scenarios[path.stem] = obj
        registry_path = root / "dist" / "registry.yaml"
        registry = yaml.safe_load(registry_path.read_text(encoding="utf-8")) if registry_path.is_file() else {}
        if not registry:
            report.errors.append("missing registry: dist/registry.yaml")
        meta = json.loads((root / "content.json").read_text(encoding="utf-8"))
        content = ContentSet(root, "content", meta, scenarios, registry, {}, {}, report)
        if strict and report.errors:
            raise ValueError("content invalid:\\n" + "\\n".join(report.errors))
        return content
    ''')


def tree_snapshot(root: Path) -> set:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


class LoadWithConsumerTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="consumer load ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.checkout = self.root / "mailroom-reloaded"
        self.content = self.root / "content"

    def write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def make_checkout(self, *, package_init=HEAVY_PACKAGE_INIT, loader=FAKE_LOADER):
        base = self.checkout / "src" / "mailroom_reloaded"
        self.write(base / "__init__.py", package_init)
        self.write(base / "sandbox" / "__init__.py", '"""Sandbox."""\n')
        self.write(base / "sandbox" / "content" / "__init__.py", '"""Content."""\n')
        self.write(base / "sandbox" / "content" / "loader.py", loader)
        self.write(self.checkout / "schemas" / "scenario.v2.json", FAKE_SCHEMA)

    def make_content(self, scenarios, *, registry=True):
        self.write(self.content / "content.json", '{"schema_version": "2.0"}\n')
        for rel, text in scenarios.items():
            self.write(self.content / "scenarios" / rel, text)
        if registry:
            self.write(self.content / "dist" / "registry.yaml", "clients: []\n")

    def run_script(self, *arguments, env=None):
        environment = dict(os.environ)
        environment.pop("MAILROOM_RELOADED", None)
        environment.update(env or {})
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            capture_output=True, text=True, timeout=60, env=environment, check=False)

    def run_load(self, *extra):
        return self.run_script("--reloaded", str(self.checkout),
                               "--content", str(self.content), *extra)

    def test_clean_load_exits_zero_and_prints_summary(self):
        self.make_checkout()
        self.make_content({"G1_good.yaml": "name: G1_good\n",
                           "A2_also_good.yaml": "name: A2_also_good\n"})
        result = self.run_load()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("ERROR", result.stdout)
        self.assertEqual(result.stdout.strip().splitlines()[-1],
                         "consumer-load: scenarios=2 personas=0 gen_specs=0 errors=0")

    def test_load_errors_exit_one_and_name_the_file(self):
        self.make_checkout()
        self.make_content({"G1_good.yaml": "name: G1_good\n",
                           "H/H1_bad.yaml": "name: H1_bad\n"})
        result = self.run_load()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        error_lines = [line for line in result.stdout.splitlines() if line.startswith("ERROR ")]
        self.assertEqual(len(error_lines), 1)
        self.assertIn("ERROR scenarios/H/H1_bad.yaml: name: 'H1_bad'", error_lines[0])
        self.assertEqual(result.stdout.strip().splitlines()[-1],
                         "consumer-load: scenarios=2 personas=0 gen_specs=0 errors=1")

    def test_missing_registry_is_a_load_error(self):
        self.make_checkout()
        self.make_content({"G1_good.yaml": "name: G1_good\n"}, registry=False)
        result = self.run_load()
        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR missing registry: dist/registry.yaml", result.stdout)

    def test_missing_checkout_path_exits_two_without_traceback(self):
        self.make_content({"G1_good.yaml": "name: G1_good\n"})
        result = self.run_script("--reloaded", str(self.root / "nowhere"),
                                 "--content", str(self.content))
        self.assertEqual(result.returncode, 2)
        self.assertIn("checkout not found", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_directory_without_loader_exits_two(self):
        self.checkout.mkdir()
        self.make_content({"G1_good.yaml": "name: G1_good\n"})
        result = self.run_load()
        self.assertEqual(result.returncode, 2)
        self.assertIn("is not a mailroom-reloaded checkout", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_import_failure_exits_two_with_reason(self):
        self.make_checkout(loader="import definitely_missing_module_for_test\n")
        self.make_content({"G1_good.yaml": "name: G1_good\n"})
        result = self.run_load()
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot import the loader", result.stderr)
        self.assertIn("definitely_missing_module_for_test", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_no_checkout_given_exits_two(self):
        self.make_checkout()
        self.make_content({"G1_good.yaml": "name: G1_good\n"})
        result = self.run_script("--content", str(self.content))
        self.assertEqual(result.returncode, 2)
        self.assertIn("MAILROOM_RELOADED", result.stderr)

    def test_environment_variable_selects_the_checkout(self):
        self.make_checkout()
        self.make_content({"G1_good.yaml": "name: G1_good\n"})
        result = self.run_script("--content", str(self.content),
                                 env={"MAILROOM_RELOADED": str(self.checkout)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_package_init_is_used_when_it_imports(self):
        self.make_checkout(package_init="")
        self.make_content({"G1_good.yaml": "name: G1_good\n"})
        result = self.run_load()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("note:", result.stderr)

    def test_heavy_package_init_falls_back_with_a_note(self):
        self.make_checkout()
        self.make_content({"G1_good.yaml": "name: G1_good\n"})
        result = self.run_load()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("note: package __init__ not importable", result.stderr)

    def test_checkout_and_content_are_not_written_to(self):
        self.make_checkout()
        self.make_content({"G1_good.yaml": "name: G1_good\n"})
        before = (tree_snapshot(self.checkout), tree_snapshot(self.content))
        result = self.run_load()
        self.assertEqual(result.returncode, 0, result.stderr)
        after = (tree_snapshot(self.checkout), tree_snapshot(self.content))
        self.assertEqual(before, after)
        self.assertFalse(any("__pycache__" in name for name in after[0]))


class CiConsumerStepTests(unittest.TestCase):
    """Run a copy of ci.sh whose interpreter is a stub that only logs its calls."""

    def setUp(self):
        temporary = TemporaryDirectory(prefix="ci consumer ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        tools = self.root / "tools"
        tools.mkdir()
        shutil.copyfile(REPO_ROOT / "tools" / "ci.sh", tools / "ci.sh")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.stub = tools / "stub-python"
        self.stub.write_text(
            '#!/bin/sh\n'
            'printf "%s\\n" "$*" >> "$CI_TEST_LOG"\n'
            'if [ -n "${CI_TEST_FAIL:-}" ]; then\n'
            '    case "$*" in *"$CI_TEST_FAIL"*) exit 1 ;; esac\n'
            'fi\n'
            'exit 0\n', encoding="utf-8")
        self.stub.chmod(0o755)
        self.log = self.root / "calls.log"

    def run_ci(self, *arguments, env=None, fail=None):
        environment = dict(os.environ)
        environment.pop("MAILROOM_RELOADED", None)
        environment.update(PYTHON=str(self.stub), CI_TEST_LOG=str(self.log))
        if fail:
            environment["CI_TEST_FAIL"] = fail
        environment.update(env or {})
        return subprocess.run(["sh", str(self.root / "tools" / "ci.sh"), *arguments],
                              cwd=self.root.parent, capture_output=True, text=True,
                              timeout=60, env=environment, check=False)

    def calls(self):
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def test_unset_prints_loud_skipped_notice_and_passes(self):
        result = self.run_ci("--skip-drift")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("consumer loader: SKIPPED (MAILROOM_RELOADED unset)", result.stdout)
        self.assertIn("NOT CHECKED AGAINST mailroom-reloaded", result.stdout)
        self.assertIn("MAILROOM_RELOADED=/path/to/mailroom-reloaded tools/ci.sh", result.stdout)
        self.assertIn("content-ci: all checks passed", result.stdout)
        self.assertFalse(any("load_with_consumer" in c or "check_schema_drift" in c
                             for c in self.calls()))

    def test_set_runs_loader_then_drift_with_the_checkout(self):
        result = self.run_ci("--skip-drift", env={"MAILROOM_RELOADED": "/fake/reloaded"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("consumer loader: SKIPPED", result.stdout)
        self.assertIn("== consumer loader\n", result.stdout)
        calls = self.calls()
        self.assertIn(f"tools/load_with_consumer.py --reloaded /fake/reloaded --content {self.root}",
                      calls)
        self.assertIn("tools/check_schema_drift.py /fake/reloaded", calls)

    def test_loader_failure_fails_the_run_and_drift_still_runs(self):
        result = self.run_ci("--skip-drift", env={"MAILROOM_RELOADED": "/fake/reloaded"},
                             fail="load_with_consumer")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("consumer checks FAILED", result.stderr)
        self.assertNotIn("content-ci: all checks passed", result.stdout)
        self.assertTrue(any("check_schema_drift" in c for c in self.calls()))

    def test_drift_failure_fails_the_run(self):
        result = self.run_ci("--skip-drift", env={"MAILROOM_RELOADED": "/fake/reloaded"},
                             fail="check_schema_drift")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("consumer checks FAILED", result.stderr)

    def test_skip_consumer_skips_quietly_even_when_set(self):
        result = self.run_ci("--skip-drift", "--skip-consumer",
                             env={"MAILROOM_RELOADED": "/fake/reloaded"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("consumer loader: SKIPPED (--skip-consumer)", result.stdout)
        self.assertNotIn("NOT CHECKED", result.stdout)
        self.assertFalse(any("load_with_consumer" in c for c in self.calls()))

    def test_unknown_argument_is_a_usage_error(self):
        result = self.run_ci("--bogus")
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage: tools/ci.sh", result.stderr)


if __name__ == "__main__":
    unittest.main()
