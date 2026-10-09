"""Hardening tests: the strict CSV reader, the outer guard, and fast fault cases.

The fault cases reuse the mutations in tools/fault_inject.py. Each one runs
against a temporary copy of the pack; the repository is never modified.
Run from the repo root:
    python3 -m unittest discover -s tests -p 'test_*.py'
"""

import shutil
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tools import fault_inject, validate


REPO_ROOT = Path(__file__).resolve().parents[1]
FAST_FAULTS = ("short_row", "extra_columns", "duplicate_client_key", "nul_in_csv",
               "ids_ranges_corrupt", "bad_yaml", "content_json_invalid")
HEADER = ["client_id", "display_name"]


class StrictCsvTests(unittest.TestCase):
    def setUp(self):
        """Create a temporary CSV path and register automatic cleanup."""
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "t.csv"

    def read(self, data, **options):
        """Write fixture bytes and return strictly parsed rows with their validation report."""
        self.path.write_bytes(data)
        report = validate.Report()
        rows = validate.read_csv_strict(self.path, report, label="t.csv", **options)
        return rows, report

    def assert_error(self, report, text):
        """Assert validation failed with an error containing the requested text."""
        self.assertFalse(report.ok())
        self.assertTrue(any(text in error for error in report.errors), report.errors)

    def test_clean_file_and_crlf_are_accepted(self):
        """Verify both LF and CRLF CSV rows parse without errors."""
        for data in (b"client_id,display_name\ncedar,Cedar\n",
                     b"client_id,display_name\r\ncedar,Cedar\r\n"):
            with self.subTest(data=data):
                rows, report = self.read(data, want=HEADER)
                self.assertEqual(rows, [{"client_id": "cedar", "display_name": "Cedar"}])
                self.assertEqual(report.errors, [])

    def test_bom_is_stripped_and_header_still_matches(self):
        """Verify a UTF-8 BOM is removed before matching CSV column names."""
        rows, report = self.read(b"\xef\xbb\xbfclient_id,display_name\ncedar,Cedar\n",
                                 want=HEADER)
        self.assertEqual(report.errors, [])
        self.assertEqual(rows[0]["client_id"], "cedar")

    def test_short_row_is_dropped_and_named_by_line(self):
        """Verify a short row is reported by line number while valid rows survive."""
        rows, report = self.read(b"client_id,display_name\ncedar\nharlow,Harlow\n",
                                 want=HEADER)
        self.assertEqual([r["client_id"] for r in rows], ["harlow"])
        self.assert_error(report, "t.csv line 2: row has 1 cells, header has 2")

    def test_extra_cells_are_rejected(self):
        """Verify rows wider than the CSV header are rejected with their cell count."""
        rows, report = self.read(b"client_id,display_name\ncedar,Cedar,extra,cells\n",
                                 want=HEADER)
        self.assertEqual(rows, [])
        self.assert_error(report, "t.csv line 2: row has 4 cells, header has 2")

    def test_nul_byte_rejects_the_file(self):
        """Verify a NUL byte rejects the entire CSV and reports its line number."""
        rows, report = self.read(b"client_id,display_name\ncedar,Cedar\n\x00x,y\n",
                                 want=HEADER)
        self.assertEqual(rows, [])
        self.assert_error(report, "t.csv line 3: NUL byte")

    def test_duplicate_header_names_are_rejected(self):
        """Verify duplicate CSV column names reject the file."""
        rows, report = self.read(b"client_id,client_id\ncedar,cedar\n")
        self.assertEqual(rows, [])
        self.assert_error(report, "duplicate header name(s) ['client_id']")

    def test_header_mismatch_and_empty_file_are_rejected(self):
        """Verify reordered headers and empty files fail the declared header check."""
        for data in (b"display_name,client_id\ncedar,Cedar\n", b""):
            with self.subTest(data=data):
                rows, report = self.read(data, want=HEADER)
                self.assertEqual(rows, [])
                self.assert_error(report, "header mismatch")

    def test_duplicate_key_keeps_the_first_row(self):
        """Verify duplicate keys report both line numbers and preserve the first row."""
        rows, report = self.read(
            b"client_id,display_name\ncedar,Cedar\ncedar,Again\nharlow,Harlow\n",
            want=HEADER, key="client_id")
        self.assertEqual([r["display_name"] for r in rows], ["Cedar", "Harlow"])
        self.assert_error(report, "t.csv line 3: duplicate client_id 'cedar' "
                                  "(first at line 2)")

    def test_non_utf8_rejects_the_file(self):
        """Verify invalid UTF-8 rejects the CSV with a decoding diagnostic."""
        rows, report = self.read(b"client_id,display_name\ncedar,\xff\n", want=HEADER)
        self.assertEqual(rows, [])
        self.assert_error(report, "not UTF-8")


class OuterGuardTests(unittest.TestCase):
    def test_unexpected_exception_exits_2_with_one_line(self):
        """Verify the outer guard converts unexpected failures into one error and status 2."""
        err = StringIO()
        with patch.object(validate, "run_checks", side_effect=RuntimeError("boom")), \
                redirect_stderr(err):
            status = validate.main()
        self.assertEqual(status, 2)
        self.assertEqual(err.getvalue(), "ERROR internal: RuntimeError: boom\n")

    def test_non_mapping_ids_ranges_is_reported_not_raised(self):
        """Verify a list in the ID allocation file produces a validation error."""
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "ids").mkdir()
            (Path(tmp) / "ids" / "ranges.yaml").write_text("- a\n- b\n", encoding="utf-8")
            report = validate.Report()
            validate.check_id_ranges(Path(tmp), report)
        self.assertTrue(any("top level must be a mapping" in e for e in report.errors),
                        report.errors)


class FaultCaseTests(unittest.TestCase):
    def test_fast_fault_cases_fail_cleanly_end_to_end(self):
        """Verify selected mutations fail validation without tracebacks or internal errors."""
        mutations = dict(fault_inject.MUTATIONS)
        for name in FAST_FAULTS:
            with self.subTest(fault=name), TemporaryDirectory() as tmp:
                root = Path(tmp) / "pack"
                shutil.copytree(REPO_ROOT, root, ignore=shutil.ignore_patterns(
                    ".git", "release", ".cache", "__pycache__"))
                mutations[name](root)
                proc = subprocess.run(
                    [sys.executable, "tools/validate.py", "--strict-coverage"],
                    cwd=root, capture_output=True, text=True, timeout=300)
                output = proc.stdout + proc.stderr
                self.assertNotEqual(proc.returncode, 0, output[-2000:])
                self.assertNotIn("Traceback", output)
                self.assertNotIn("ERROR internal", output)


if __name__ == "__main__":
    unittest.main()
