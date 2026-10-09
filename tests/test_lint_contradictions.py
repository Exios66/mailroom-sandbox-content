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
        findings, stats = lint.find_disagreements([
            scenario("S1_a", priority="normal", outbox=[]),
            scenario("S2_b", priority="normal", outbox=[])])
        self.assertEqual(findings, [])
        self.assertEqual(stats.groups, 1)

    def test_priority_disagreement_is_reported(self):
        findings, _ = lint.find_disagreements([
            scenario("S1_a", priority="normal", outbox=[]),
            scenario("S2_b", priority="high", outbox=[])])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].field, "priority")
        self.assertEqual(findings[0].members,
                         (("S1_a", "normal"), ("S2_b", "high")))

    def test_outbox_empty_vs_draft_is_reported(self):
        findings, _ = lint.find_disagreements([
            scenario("T1_a", outbox=[]),
            scenario("T2_b", outbox=DRAFT)])
        self.assertEqual([f.field for f in findings], ["outbox"])
        self.assertEqual(findings[0].members,
                         (("T1_a", "[]"),
                          ("T2_b", "[status_request/draft]")))

    def test_outbox_kind_difference_is_reported(self):
        complaint = [{"intent": "complaint", "state": "draft"}]
        findings, _ = lint.find_disagreements([
            scenario("T1_a", outbox=DRAFT),
            scenario("T2_b", outbox=complaint)])
        self.assertEqual([f.field for f in findings], ["outbox"])

    def test_same_outbox_kind_different_order_agrees(self):
        two = [{"intent": "status_request", "state": "draft"},
               {"intent": "complaint", "state": "draft"}]
        flipped = list(reversed(two))
        findings, _ = lint.find_disagreements([
            scenario("T1_a", outbox=two),
            scenario("T2_b", outbox=flipped)])
        self.assertEqual(findings, [])

    def test_absent_outbox_is_not_compared(self):
        findings, _ = lint.find_disagreements([
            scenario("T1_a", outbox=None),
            scenario("T2_b", outbox=DRAFT)])
        self.assertEqual(findings, [])

    def test_priority_is_the_highest_signal_priority(self):
        multi = scenario("E1_a", outbox=[], priority="critical")
        multi["expect"]["signals"].append({"kind": "fyi", "priority": "high"})
        findings, _ = lint.find_disagreements([
            multi, scenario("E2_b", outbox=[], priority="critical")])
        self.assertEqual(findings, [])

    def test_different_template_is_not_grouped(self):
        findings, stats = lint.find_disagreements([
            scenario("S1_a", template="one", priority="normal", outbox=[]),
            scenario("S2_b", template="two", priority="high", outbox=[])])
        self.assertEqual(findings, [])
        self.assertEqual(stats.groups, 0)

    def test_different_intent_is_not_grouped(self):
        findings, _ = lint.find_disagreements([
            scenario("S1_a", intent="unrelated", priority="normal", outbox=[]),
            scenario("S2_b", intent="general_question", priority="high",
                     outbox=[])])
        self.assertEqual(findings, [])

    def test_template_set_must_match_exactly(self):
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
        findings, stats = lint.find_disagreements([
            scenario("S1_a", priority="normal", outbox=[]),
            scenario("S2_b", priority="high", outbox=[],
                     contrast="sandbox self-test, not a Correspondent value")])
        self.assertEqual(findings, [])
        self.assertEqual(stats.exempt[0][0], "S2_b")
        self.assertIn("sandbox self-test", stats.exempt[0][1])

    def test_contrast_leaves_remaining_disagreement(self):
        findings, _ = lint.find_disagreements([
            scenario("S1_a", priority="normal", outbox=[]),
            scenario("S2_b", priority="high", outbox=[]),
            scenario("S3_c", priority="critical", outbox=[],
                     contrast="out of scope")])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].members,
                         (("S1_a", "normal"), ("S2_b", "high")))

    def test_blank_contrast_does_not_exempt(self):
        findings, _ = lint.find_disagreements([
            scenario("S1_a", priority="normal", outbox=[]),
            scenario("S2_b", priority="high", outbox=[], contrast="   ")])
        self.assertEqual(len(findings), 1)

    def test_contrast_must_be_a_string(self):
        self.assertIsNone(lint.exempt_reason(
            {"name": "X", "contrast": ["not", "a", "string"]}))


class FormatTest(unittest.TestCase):
    def test_warn_line_names_group_field_and_members(self):
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
        for data in scenarios:
            series = data["name"][0]
            path = root / "scenarios" / series / f"{data['name']}.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(yaml.safe_dump(data, sort_keys=False),
                            encoding="utf-8")

    def run_main(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = lint.main(argv)
        return code, out.getvalue()

    def test_default_mode_warns_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_tree(root, [
                scenario("S1_a", priority="normal", outbox=[]),
                scenario("S2_b", priority="high", outbox=[])])
            code, text = self.run_main(["--root", str(root)])
        self.assertEqual(code, 0)
        self.assertIn("WARN: priority disagreement", text)

    def test_strict_mode_exits_one_on_disagreement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_tree(root, [
                scenario("S1_a", priority="normal", outbox=[]),
                scenario("S2_b", priority="high", outbox=[])])
            code, _ = self.run_main(["--root", str(root), "--strict"])
        self.assertEqual(code, 1)

    def test_strict_mode_exits_zero_when_clean(self):
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
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "scenarios" / "S" / "S1_bad.yaml"
            bad.parent.mkdir(parents=True)
            bad.write_text("name: [unclosed\n", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                code, _ = self.run_main(["--root", str(root)])
        self.assertEqual(code, 2)

    def test_pack_default_mode_exits_zero(self):
        code, text = self.run_main(["--root", str(REPO_ROOT)])
        self.assertEqual(code, 0)
        self.assertIn("lint_contradictions: scenarios=", text)


if __name__ == "__main__":
    unittest.main()
