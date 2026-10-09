"""Tests for tools/lint_contradictions.py: grouping and contrast logic on tiny
synthetic scenario dicts, plus the CLI exit codes on a throwaway tree.
Fixtures never modify the content pack.

Run from the repo root:
    python3 -m unittest discover -s tests -t .
"""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import yaml

from tools import lint_contradictions as lint

REPO_ROOT = Path(__file__).resolve().parent.parent

DRAFT = [{"intent": "status_request", "state": "draft", "to_sender": True}]


def scenario(name, template="routine_check", intent="unrelated",
             priority="normal", outbox=None, contrast=None):
    """Build a minimal client scenario with optional outbox expectations and contrast."""
    expect = {"intent": intent,
              "signals": [{"kind": "fyi", "priority": priority}]}
    if outbox is not None:
        expect["outbox"] = outbox
    data = {"name": name,
            "timeline": [{"at": "00:02", "client": {
                "persona": "p_test", "channel": "email", "template": template}}],
            "expect": expect}
    if contrast is not None:
        data["contrast"] = contrast
    return data


class GroupingTest(unittest.TestCase):
    def test_agreeing_members_produce_no_finding(self):
        """Verify matching expectations form one group without findings."""
        findings, stats = lint.find_disagreements([
            scenario("S1_a", priority="normal", outbox=[]),
            scenario("S2_b", priority="normal", outbox=[])])
        self.assertEqual(findings, [])
        self.assertEqual(stats.groups, 1)

    def test_priority_disagreement_is_reported(self):
        """Verify conflicting priorities identify the field and both member values."""
        findings, _ = lint.find_disagreements([
            scenario("S1_a", priority="normal", outbox=[]),
            scenario("S2_b", priority="high", outbox=[])])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].field, "priority")
        self.assertEqual(findings[0].members,
                         (("S1_a", "normal"), ("S2_b", "high")))

    def test_outbox_empty_vs_draft_is_reported(self):
        """Verify an empty outbox conflicts with an expected draft."""
        findings, _ = lint.find_disagreements([
            scenario("T1_a", outbox=[]),
            scenario("T2_b", outbox=DRAFT)])
        self.assertEqual([f.field for f in findings], ["outbox"])
        self.assertEqual(findings[0].members,
                         (("T1_a", "[]"),
                          ("T2_b", "[status_request/draft]")))

    def test_outbox_kind_difference_is_reported(self):
        """Verify different expected outbox intents produce a disagreement."""
        complaint = [{"intent": "complaint", "state": "draft"}]
        findings, _ = lint.find_disagreements([
            scenario("T1_a", outbox=DRAFT),
            scenario("T2_b", outbox=complaint)])
        self.assertEqual([f.field for f in findings], ["outbox"])

    def test_same_outbox_kind_different_order_agrees(self):
        """Verify outbox comparison ignores the order of intent/state pairs."""
        two = [{"intent": "status_request", "state": "draft"},
               {"intent": "complaint", "state": "draft"}]
        flipped = list(reversed(two))
        findings, _ = lint.find_disagreements([
            scenario("T1_a", outbox=two),
            scenario("T2_b", outbox=flipped)])
        self.assertEqual(findings, [])

    def test_absent_outbox_is_not_compared(self):
        """Verify an omitted outbox expectation makes no assertion to compare."""
        findings, _ = lint.find_disagreements([
            scenario("T1_a", outbox=None),
            scenario("T2_b", outbox=DRAFT)])
        self.assertEqual(findings, [])

    def test_priority_is_the_highest_signal_priority(self):
        """Verify only the highest signal priority determines the comparison."""
        multi = scenario("E1_a", outbox=[], priority="critical")
        multi["expect"]["signals"].append({"kind": "fyi", "priority": "high"})
        findings, _ = lint.find_disagreements([
            multi, scenario("E2_b", outbox=[], priority="critical")])
        self.assertEqual(findings, [])

    def test_different_template_is_not_grouped(self):
        """Verify scenarios using distinct templates form no comparable group."""
        findings, stats = lint.find_disagreements([
            scenario("S1_a", template="one", priority="normal", outbox=[]),
            scenario("S2_b", template="two", priority="high", outbox=[])])
        self.assertEqual(findings, [])
        self.assertEqual(stats.groups, 0)

    def test_different_intent_is_not_grouped(self):
        """Verify distinct expected intents prevent priority comparisons."""
        findings, _ = lint.find_disagreements([
            scenario("S1_a", intent="unrelated", priority="normal", outbox=[]),
            scenario("S2_b", intent="general_question", priority="high",
                     outbox=[])])
        self.assertEqual(findings, [])

    def test_template_set_must_match_exactly(self):
        """Verify an extra companion template prevents grouping with a single-template case."""
        companion = scenario("E1_a", template="attack", priority="critical",
                             outbox=[])
        companion["timeline"].append({"at": "00:03", "client": {
            "persona": "p_test", "channel": "email", "template": "companion"}})
        findings, stats = lint.find_disagreements([
            companion, scenario("E2_b", template="attack", priority="high",
                                outbox=[])])
        self.assertEqual(findings, [])
        self.assertEqual(stats.groups, 0)

    def test_scenario_without_client_message_is_skipped(self):
        """Verify a fault-only timeline is recorded as skipped."""
        bare = {"name": "S8_bare", "timeline": [{"at": "00:00",
                                                 "fault": "x"}],
                "expect": {"intent": "unrelated",
                           "signals": [{"kind": "fyi", "priority": "critical"}],
                           "outbox": []}}
        findings, stats = lint.find_disagreements([
            bare, scenario("S1_a", priority="normal", outbox=[])])
        self.assertEqual(findings, [])
        self.assertEqual(stats.skipped, ("S8_bare",))


class ContrastTest(unittest.TestCase):
    def test_contrast_exempts_member(self):
        """Verify a nonblank contrast reason exempts a scenario and is retained in stats."""
        findings, stats = lint.find_disagreements([
            scenario("S1_a", priority="normal", outbox=[]),
            scenario("S2_b", priority="high", outbox=[],
                     contrast="sandbox self-test, not a Correspondent value")])
        self.assertEqual(findings, [])
        self.assertEqual(stats.exempt[0][0], "S2_b")
        self.assertIn("sandbox self-test", stats.exempt[0][1])

    def test_contrast_leaves_remaining_disagreement(self):
        """Verify exempting one member preserves disagreement between remaining members."""
        findings, _ = lint.find_disagreements([
            scenario("S1_a", priority="normal", outbox=[]),
            scenario("S2_b", priority="high", outbox=[]),
            scenario("S3_c", priority="critical", outbox=[],
                     contrast="out of scope")])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].members,
                         (("S1_a", "normal"), ("S2_b", "high")))

    def test_blank_contrast_does_not_exempt(self):
        """Verify whitespace-only contrast text cannot suppress a disagreement."""
        findings, _ = lint.find_disagreements([
            scenario("S1_a", priority="normal", outbox=[]),
            scenario("S2_b", priority="high", outbox=[], contrast="   ")])
        self.assertEqual(len(findings), 1)

    def test_contrast_must_be_a_string(self):
        """Verify a list cannot serve as an exemption reason."""
        self.assertIsNone(lint.exempt_reason(
            {"name": "X", "contrast": ["not", "a", "string"]}))


class FormatTest(unittest.TestCase):
    def test_warn_line_names_group_field_and_members(self):
        """Verify warning text includes the group key, disputed field, and member values."""
        findings, _ = lint.find_disagreements([
            scenario("S1_a", priority="normal", outbox=[]),
            scenario("S2_b", priority="high", outbox=[])])
        self.assertEqual(
            lint.format_finding(findings[0]),
            "WARN: priority disagreement in group "
            "template=[routine_check] intent=unrelated: "
            "S1_a=normal, S2_b=high")


class CliTest(unittest.TestCase):
    def write_tree(self, root, scenarios):
        """Write scenario fixtures beneath their series directories in the temporary root."""
        for data in scenarios:
            series = data["name"][0]
            path = root / "scenarios" / series / f"{data['name']}.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(yaml.safe_dump(data, sort_keys=False),
                            encoding="utf-8")

    def run_main(self, argv):
        """Invoke the lint CLI and return its status and captured stdout."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = lint.main(argv)
        return code, out.getvalue()

    def test_default_mode_warns_and_exits_zero(self):
        """Verify default mode prints disagreements without failing."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_tree(root, [
                scenario("S1_a", priority="normal", outbox=[]),
                scenario("S2_b", priority="high", outbox=[])])
            code, text = self.run_main(["--root", str(root)])
        self.assertEqual(code, 0)
        self.assertIn("WARN: priority disagreement", text)

    def test_strict_mode_exits_one_on_disagreement(self):
        """Verify strict mode fails when comparable scenarios disagree."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_tree(root, [
                scenario("S1_a", priority="normal", outbox=[]),
                scenario("S2_b", priority="high", outbox=[])])
            code, _ = self.run_main(["--root", str(root), "--strict"])
        self.assertEqual(code, 1)

    def test_strict_mode_exits_zero_when_clean(self):
        """Verify strict mode succeeds after the differing member is exempted."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_tree(root, [
                scenario("S1_a", priority="normal", outbox=[]),
                scenario("S2_b", priority="normal", outbox=[],
                         contrast="documented")])
            code, text = self.run_main(["--root", str(root), "--strict"])
        self.assertEqual(code, 0)
        self.assertNotIn("WARN:", text)

    def test_unreadable_scenario_exits_two(self):
        """Verify malformed scenario YAML produces CLI status 2."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "scenarios" / "S" / "S1_bad.yaml"
            bad.parent.mkdir(parents=True)
            bad.write_text("name: [unclosed\n", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                code, _ = self.run_main(["--root", str(root)])
        self.assertEqual(code, 2)

    def test_missing_or_non_directory_scenarios_exits_two(self):
        """A bad root reports a load error rather than a successful empty scan."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for is_file in (False, True):
                with self.subTest(is_file=is_file):
                    if is_file:
                        (root / "scenarios").write_text("not a directory")
                    err = io.StringIO()
                    with contextlib.redirect_stderr(err):
                        code, text = self.run_main(["--root", str(root)])
                    self.assertEqual(code, 2)
                    self.assertIn("ERROR: cannot load scenarios:", err.getvalue())
                    self.assertNotIn("lint_contradictions: scenarios=", text)

    def test_existing_empty_scenarios_directory_exits_zero(self):
        """An intentionally empty scenarios directory is still a valid input."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scenarios").mkdir()
            code, text = self.run_main(["--root", str(root), "--strict"])
        self.assertEqual(code, 0)
        self.assertIn("scenarios=0", text)

    def test_pack_default_mode_exits_zero(self):
        """Verify the repository content pack can be linted in advisory mode."""
        code, text = self.run_main(["--root", str(REPO_ROOT)])
        self.assertEqual(code, 0)
        self.assertIn("lint_contradictions: scenarios=", text)


if __name__ == "__main__":
    unittest.main()
