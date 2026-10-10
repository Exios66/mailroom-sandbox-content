"""Guard tests for the historical scenario v2 migration (issue #13).

``tools/migrate_scenarios_v2.py`` already ran; re-running it would revert edits
made afterwards (for example G9's ``outbox: []``). ``main`` must refuse unless
the explicit ``--confirm-historical-rerun`` flag is passed. The helpers stay
importable for ``tools/gen_coverage_scenarios.py``.
"""

import io
from pathlib import Path
import unittest
from unittest.mock import patch
from contextlib import redirect_stderr, redirect_stdout

from tools import gen_coverage_scenarios, migrate_scenarios_v2


class MigrationGuardTests(unittest.TestCase):
    def test_main_refuses_without_the_explicit_flag(self):
        """Verify a bare run is refused, writes nothing, and returns 2."""
        err = io.StringIO()
        with patch.object(migrate_scenarios_v2, "write_templates") as templates, \
                patch.object(migrate_scenarios_v2, "migrate") as migrate, \
                redirect_stderr(err):
            status = migrate_scenarios_v2.main([])
        self.assertEqual(status, 2)
        self.assertIn("historical one-shot", err.getvalue())
        self.assertIn(migrate_scenarios_v2.HISTORICAL_FLAG, err.getvalue())
        templates.assert_not_called()
        migrate.assert_not_called()

    def test_main_refuses_on_any_other_argument(self):
        """Verify unrelated arguments do not accidentally unblock the run."""
        with patch.object(migrate_scenarios_v2, "write_templates") as templates, \
                redirect_stderr(io.StringIO()):
            status = migrate_scenarios_v2.main(["--force"])
        self.assertEqual(status, 2)
        templates.assert_not_called()

    def test_main_runs_only_with_the_flag(self):
        """Verify the explicit flag lets the run proceed (helpers stubbed)."""
        with patch.object(migrate_scenarios_v2, "write_templates") as templates, \
                patch.object(migrate_scenarios_v2, "migrate") as migrate, \
                patch.object(migrate_scenarios_v2, "ROOT", Path("/nonexistent")), \
                redirect_stdout(io.StringIO()):
            status = migrate_scenarios_v2.main([migrate_scenarios_v2.HISTORICAL_FLAG])
        self.assertEqual(status, 0)
        templates.assert_called_once()
        migrate.assert_not_called()  # no scenarios under the patched root

    def test_helpers_stay_importable_for_the_coverage_generator(self):
        """Verify gen_coverage_scenarios still imports its shared helpers."""
        self.assertEqual(gen_coverage_scenarios.ORDER, migrate_scenarios_v2.ORDER)
        self.assertEqual(gen_coverage_scenarios.Dumper.__name__, "Dumper")
        self.assertTrue(callable(gen_coverage_scenarios.ordered))


if __name__ == "__main__":
    unittest.main()
