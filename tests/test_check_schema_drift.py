"""tools/check_schema_drift.py: byte-for-byte schema mirror check.

Uses two temporary trees: a content schemas/ directory and a stand-in
mailroom-reloaded checkout with its own schemas/ directory.
"""

import contextlib
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools import check_schema_drift as drift


class SchemaDriftTests(unittest.TestCase):
    def setUp(self):
        """Create isolated content and consumer schema directories for each test."""
        temporary = TemporaryDirectory(prefix="schema drift ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.content = self.root / "content" / "schemas"
        self.consumer = self.root / "mailroom-reloaded"
        (self.consumer / "schemas").mkdir(parents=True)
        self.content.mkdir(parents=True)

    def write(self, directory: Path, name: str, data: bytes) -> None:
        """Write exact fixture bytes to a named file in the given directory."""
        (directory / name).write_bytes(data)

    def run_check(self, *arguments, environ=None):
        """Run the drift CLI against fixtures and return status, stdout, and stderr."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = drift.main([*arguments, "--content", str(self.content)],
                              environ=environ if environ is not None else {})
        return code, out.getvalue(), err.getvalue()

    def test_equal_schemas_exit_zero(self):
        """Verify byte-identical shared schemas pass without drift warnings."""
        self.write(self.content, "gen_spec.v1.json", b'{"title": "x"}\n')
        self.write(self.consumer / "schemas", "gen_spec.v1.json", b'{"title": "x"}\n')
        code, out, _ = self.run_check(str(self.consumer))
        self.assertEqual(code, 0)
        self.assertNotIn("DRIFT", out)
        self.assertIn("none (1 shared", out)

    def test_one_byte_difference_is_drift(self):
        """Verify a single extra byte identifies only the changed shared schema."""
        self.write(self.content, "gen_spec.v1.json", b'{"title": "x"}\n')
        self.write(self.consumer / "schemas", "gen_spec.v1.json", b'{"title": "x"} \n')
        self.write(self.content, "registry.v1.json", b"{}")
        self.write(self.consumer / "schemas", "registry.v1.json", b"{}")
        code, out, _ = self.run_check(str(self.consumer))
        self.assertEqual(code, 1)
        self.assertEqual([line for line in out.splitlines() if line.startswith("DRIFT ")],
                         ["DRIFT gen_spec.v1.json"])

    def test_structurally_equal_but_textually_different_is_drift(self):
        # The contract is byte identity: same JSON with different spacing still drifts.
        """Verify JSON whitespace differences violate the byte-identity contract."""
        self.write(self.content, "overlay.v1.json", b'{"a":1}')
        self.write(self.consumer / "schemas", "overlay.v1.json", b'{"a": 1}')
        code, out, _ = self.run_check(str(self.consumer))
        self.assertEqual(code, 1)
        self.assertIn("DRIFT overlay.v1.json", out)

    def test_missing_counterpart_is_content_only_not_drift(self):
        """Verify schemas absent from the consumer are reported as content-only."""
        self.write(self.content, "local_only.v1.json", b"{}")
        self.write(self.content, "shared.v1.json", b"{}")
        self.write(self.consumer / "schemas", "shared.v1.json", b"{}")
        code, out, _ = self.run_check(str(self.consumer))
        self.assertEqual(code, 0)
        self.assertNotIn("DRIFT", out)
        self.assertIn("content-only (not compared): local_only.v1.json", out)
        self.assertIn("none (1 shared", out)

    def test_consumer_only_schemas_are_ignored(self):
        """Verify schemas unique to the consumer do not enter the comparison."""
        self.write(self.content, "shared.v1.json", b"{}")
        self.write(self.consumer / "schemas", "shared.v1.json", b"{}")
        self.write(self.consumer / "schemas", "consumer_only.v1.json", b"{}")
        code, out, _ = self.run_check(str(self.consumer))
        self.assertEqual(code, 0)
        self.assertNotIn("consumer_only", out)

    def test_checkout_from_environment(self):
        """Verify MAILROOM_RELOADED supplies the consumer checkout when no path is given."""
        self.write(self.content, "shared.v1.json", b"{}")
        self.write(self.consumer / "schemas", "shared.v1.json", b"[]")
        code, out, _ = self.run_check(environ={"MAILROOM_RELOADED": str(self.consumer)})
        self.assertEqual(code, 1)
        self.assertIn("DRIFT shared.v1.json", out)

    def test_argument_takes_precedence_over_environment(self):
        """Verify an explicit checkout overrides the environment path."""
        self.write(self.content, "shared.v1.json", b"{}")
        self.write(self.consumer / "schemas", "shared.v1.json", b"{}")
        empty = self.root / "empty-checkout"
        (empty / "schemas").mkdir(parents=True)
        code, _, _ = self.run_check(str(self.consumer),
                                    environ={"MAILROOM_RELOADED": str(empty)})
        self.assertEqual(code, 0)

    def test_no_checkout_is_skipped_with_exit_zero(self):
        """Verify an unconfigured checkout produces the skip message and succeeds."""
        code, out, _ = self.run_check(environ={})
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "schema drift check skipped: set MAILROOM_RELOADED")

    def test_empty_environment_value_is_skipped(self):
        """Verify an empty checkout environment value skips the comparison."""
        code, out, _ = self.run_check(environ={"MAILROOM_RELOADED": ""})
        self.assertEqual(code, 0)
        self.assertIn("skipped: set MAILROOM_RELOADED", out)

    def test_checkout_without_schemas_directory_is_an_error(self):
        """Verify a checkout lacking schemas exits with status 2 and a diagnostic."""
        code, _, err = self.run_check(str(self.root / "missing"))
        self.assertEqual(code, 2)
        self.assertIn("no schemas/ directory", err)


if __name__ == "__main__":
    unittest.main()
