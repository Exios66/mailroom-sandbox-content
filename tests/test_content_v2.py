"""Tests for the scenario v2 rules, contract schemas, ID ranges and the
strata / fixture tooling. Fixtures never modify the content pack.

Run from the repo root:
    python3 -m unittest discover -s tests -p 'test_*.py'
"""

import copy
import hashlib
import subprocess
import sys
import unittest
from pathlib import Path

from tests.test_validate import REPO_ROOT, ContentFixture
from tools import make_fixture_pdf, sync_strata, validate


class ScenarioV2Rules(ContentFixture):
    def setUp(self):
        super().setUp()
        self.seed_scenario()
        self.write_csv("taxonomy/strata.csv", [
            {"class": "contract", "stratum": "license", "in_ground_truth": "true"},
            {"class": "corporate_record", "stratum": "certificate_of_formation",
             "in_ground_truth": "false"}])
        self.write_csv("taxonomy/offtaxonomy.csv", [{"kind": "wire_instructions"}])
        self.personas = {"p_cedar": {"client_id": "cedar", "contact_id": "cedar_avery"},
                         "p_bad": {"client_id": "_adversary", "contact_id": "_none"}}

    def check_scenario(self, scenario):
        self.write_yaml("scenarios/A/A1_status.yaml", scenario)
        return self.check(validate.check_scenarios, self.personas,
                          {"cedar": {"cedar.sandbox.invalid"}})

    def client(self, scenario, index=0):
        return scenario["timeline"][index]["client"]

    def test_seed_scenario_is_clean(self):
        _, report = self.check_scenario(self.scenario)
        self.assert_clean(report)

    def test_client_message_needs_a_template(self):
        scenario = copy.deepcopy(self.scenario)
        del self.client(scenario)["template"]
        _, report = self.check_scenario(scenario)
        self.assert_error(report, "needs a template")

    def test_template_variables_must_be_supplied(self):
        self.write("gen/templates/status.j2",
                   "Subject: {{ matter_ref }}\n\nHi, {{ sender_name }}\n")
        _, report = self.check_scenario(self.scenario)
        self.assert_error(report, "needs vars ['matter_ref']")
        scenario = copy.deepcopy(self.scenario)
        self.client(scenario)["vars"] = {"matter_ref": "CD-1"}
        _, report = self.check_scenario(scenario)
        self.assert_clean(report)

    def test_adversary_persona_must_supply_contact_context(self):
        self.write("gen/templates/status.j2", "Subject: hi\n\n{{ sender_name }}\n")
        self.write_yaml("gen/specs/status.yaml", {"id": "gen_status", "persona": "p_bad"})
        scenario = copy.deepcopy(self.scenario)
        self.client(scenario)["persona"] = "p_bad"
        scenario["expect"]["trust"]["sender_level"] = "hostile"
        _, report = self.check_scenario(scenario)
        self.assert_error(report, "needs vars ['sender_name']")
        self.client(scenario)["vars"] = {"sender_name": "Spoofed Name"}
        _, report = self.check_scenario(scenario)
        self.assertTrue(report.ok(), report.errors)

    def test_template_needs_subject_line_and_valid_syntax(self):
        self.write("gen/templates/status.j2", "Hello\n")
        _, report = self.check_scenario(self.scenario)
        self.assert_error(report, "first rendered line must be 'Subject: ...'")
        self.write("gen/templates/status.j2", "Subject: {{ broken \n")
        _, report = self.check_scenario(self.scenario)
        self.assert_error(report, "template syntax error")

    def test_strata_must_exist_and_be_drawable(self):
        cases = [({"class": "contract", "stratum": "license"}, None),
                 ({"class": "off_taxonomy", "stratum": "wire_instructions"}, None),
                 ({"class": "contract", "stratum": "parties"}, "unknown stratum contract/parties"),
                 ({"class": "corporate_record", "stratum": "certificate_of_formation"},
                  "catalog_only")]
        for spec, error in cases:
            with self.subTest(spec=spec):
                scenario = copy.deepcopy(self.scenario)
                self.client(scenario)["attach"] = [spec]
                del scenario["expect"]["relations"]
                _, report = self.check_scenario(scenario)
                if error:
                    self.assert_error(report, error)
                else:
                    self.assertTrue(report.ok(), report.errors)

    def test_refs_same_as_and_reply_to(self):
        scenario = copy.deepcopy(self.scenario)
        first = scenario["timeline"][0]
        first["client"]["ref"] = "msg_one"
        first["client"]["attach"] = [{"file": "lease.txt", "ref": "doc_one"}]
        second = copy.deepcopy(first)
        second["at"] = "00:05"
        second["client"]["ref"] = "msg_two"
        second["client"]["reply_to"] = "msg_one"
        second["client"]["attach"] = [{"ref": "doc_two", "same_as": "doc_one"}]
        scenario["timeline"].append(second)
        scenario["expect"]["relations"] = [
            {"a": "doc_two", "b": "doc_one", "kind": "duplicates"}]
        _, report = self.check_scenario(scenario)
        self.assertTrue(report.ok(), report.errors)

        broken = copy.deepcopy(scenario)
        broken["timeline"][1]["client"]["ref"] = "msg_one"
        _, report = self.check_scenario(broken)
        self.assert_error(report, "duplicate ref 'msg_one'")

        broken = copy.deepcopy(scenario)
        broken["timeline"][1]["client"]["attach"][0]["same_as"] = "doc_later"
        _, report = self.check_scenario(broken)
        self.assert_error(report, "same_as 'doc_later' is not an earlier document ref")

        broken = copy.deepcopy(scenario)
        broken["timeline"][1]["client"]["reply_to"] = "msg_missing"
        _, report = self.check_scenario(broken)
        self.assert_error(report, "reply_to 'msg_missing' is not an earlier message ref")

    def test_ingress_documents_bind_refs(self):
        scenario = copy.deepcopy(self.scenario)
        scenario["timeline"].insert(0, {"at": "00:00", "ingress": {
            "ref": "filed", "class": "contract", "stratum": "license", "as": "filed.pdf"}})
        scenario["expect"]["relations"] = [{"a": "lease.txt", "b": "filed", "kind": "amends"}]
        _, report = self.check_scenario(scenario)
        self.assertTrue(report.ok(), report.errors)
        scenario["timeline"][0]["ingress"] = {"doc": "free_text_name"}
        _, report = self.check_scenario(scenario)
        self.assert_error(report, "schema violation at timeline.0.ingress")

    def test_expectation_endpoints_must_resolve(self):
        scenario = copy.deepcopy(self.scenario)
        scenario["expect"]["relations"] = [
            {"a": "matter:CD-1", "b": "matter:CD-2", "kind": "references"}]
        _, report = self.check_scenario(scenario)
        self.assert_clean(report)
        for key, value, error in (
                ("relations", [{"a": "free_text", "b": "lease.txt", "kind": "references"}],
                 "expect.relations[0].a 'free_text'"),
                ("quarantine", ["nowhere.pdf"], "expect.quarantine 'nowhere.pdf'"),
                ("soft_hold", ["nowhere.pdf"], "expect.soft_hold 'nowhere.pdf'"),
                ("docs", {"nowhere": {"state": "withdrawn"}}, "expect.docs key 'nowhere'")):
            with self.subTest(key=key):
                broken = copy.deepcopy(self.scenario)
                broken["expect"][key] = value
                _, report = self.check_scenario(broken)
                self.assert_error(report, error)

    def test_reference_template_must_exist(self):
        scenario = copy.deepcopy(self.scenario)
        scenario["expect"]["outbox"] = [{"state": "draft", "reference_template": "ack"}]
        _, report = self.check_scenario(scenario)
        self.assert_error(report, "reference_template 'ack' not in gen/templates/replies/")
        self.write("gen/templates/replies/ack.j2", "Subject: Re: ack\n")
        _, report = self.check_scenario(scenario)
        self.assert_clean(report)

    def test_fault_vocabulary_is_closed(self):
        scenario = copy.deepcopy(self.scenario)
        scenario["timeline"][0]["fault"] = "duplicate_delivery"
        _, report = self.check_scenario(scenario)
        self.assert_clean(report)
        scenario["timeline"][0]["fault"] = "make_it_weird"
        _, report = self.check_scenario(scenario)
        self.assert_error(report, "schema violation at timeline.0.fault")

    def test_client_and_ingress_never_share_an_event(self):
        scenario = copy.deepcopy(self.scenario)
        scenario["timeline"][0]["ingress"] = {"file": "lease.txt"}
        _, report = self.check_scenario(scenario)
        self.assert_error(report, "schema violation at timeline.0")

    def test_frozen_without_specs_is_one_summary_warning(self):
        scenario = copy.deepcopy(self.scenario)
        scenario["gen"] = "frozen"
        del self.client(scenario)["gen_spec"]
        _, report = self.check_scenario(scenario)
        self.assertTrue(report.ok(), report.errors)
        self.assertEqual(len(report.warnings), 1)
        self.assertIn("1 scenarios target gen frozen/live/loop", report.warnings[0])


class CoverageStrictness(ContentFixture):
    def test_strict_coverage_turns_gaps_into_errors(self):
        self.write_csv("taxonomy/strata.csv", [
            {"class": "contract", "stratum": "license", "in_ground_truth": "true"},
            {"class": "corporate_record", "stratum": "certificate_of_formation",
             "in_ground_truth": "false"}])
        _, report = self.check(validate.coverage_report, [], {})
        self.assertTrue(report.ok())
        self.assertEqual(report.warnings, ["coverage: contract/license has no client + scenario"])
        report = validate.Report()
        validate.coverage_report(self.root, [], {}, report, strict=True)
        self.assertEqual(report.errors, ["coverage: contract/license has no client + scenario"])

    def test_pinned_files_count_toward_their_manifest_stratum(self):
        self.write_csv("taxonomy/strata.csv", [
            {"class": "contract", "stratum": "license", "in_ground_truth": "true"}])
        self.write_csv("attachments/manifest.csv", [
            {"attachment_id": "att_0001", "file": "a.pdf", "class": "contract",
             "stratum": "license", "in_taxonomy": "true"}])
        mixes = [{"client_id": "cedar", "class": "contract", "stratum": "license", "weight": "1"}]
        scenarios = {"A1_x": {"timeline": [{"at": "00:00", "ingress": {"file": "a.pdf"}}]}}
        coverage, report = self.check(validate.coverage_report, mixes, scenarios)
        self.assert_clean(report)
        self.assertEqual(coverage["contract/license"]["scenarios"], ["A1_x"])


class ContractSchemas(ContentFixture):
    def test_gen_specs_behaviors_overlay_and_registry_are_schema_checked(self):
        self.write_yaml("gen/specs/bad.yaml", {"id": "gen_bad_0001"})
        self.write_yaml("personas/behavior/bad.yaml", {"persona_id": "p_bad"})
        self.write("email/overlay/example.jsonl",
                   '{"v": 1, "kind": "message", "persona_id": "p_leak"}\n')
        report = validate.Report()
        validate.check_contract_schemas(self.root, {"version": 1, "clients": {},
                                                    "labels": ["impostor"]}, report)
        joined = "\n".join(report.errors)
        for where in ("gen/specs/bad.yaml", "personas/behavior/bad.yaml",
                      "email/overlay/example.jsonl:1", "dist/registry.yaml"):
            self.assertIn(where, joined)


class IdRanges(ContentFixture):
    def test_ids_must_fall_inside_an_allocated_block(self):
        self.write_csv("attachments/manifest.csv", [
            {"attachment_id": "att_0001"}, {"attachment_id": "att_0500"},
            {"attachment_id": "att_0001"}])
        self.write_yaml("gen/specs/ok.yaml", {"id": "gen_E1_wire_0042"})
        report = validate.Report()
        validate.check_id_ranges(self.root, report)
        self.assertIn("attachments/manifest.csv: att_0500 is outside every attachments "
                      "block in ids/ranges.yaml", report.errors)
        self.assertTrue(any("duplicate id att_0001" in e for e in report.errors))
        self.assertEqual(len(report.errors), 2, report.errors)

    def test_overlapping_blocks_are_rejected(self):
        self.write_yaml("ids/ranges.yaml", {
            "schema": "mailroom.id_ranges/v1",
            "relations": [{"owner": "a", "lo": 1, "hi": 10},
                          {"owner": "b", "lo": 10, "hi": 20}]})
        report = validate.Report()
        validate.check_id_ranges(self.root, report)
        self.assertIn("ids/ranges.yaml relations: a and b overlap", report.errors)

    def test_real_content_ids_are_in_range(self):
        report = validate.Report()
        validate.check_id_ranges(REPO_ROOT, report)
        self.assertEqual(report.errors, [])


FAKE_CONFIG = '''
CONTRACT_SUBTYPES: list[dict[str, str]] = [
    {"key": "license", "label": "License Agreement", "description": "x"},
    {"key": "joint_venture", "label": "Joint Venture Agreement", "description": "x"},
]
MAUD_CONSIDERATION_TYPES: list[str] = ["all_cash", "other"]
SUBTYPE_ALIASES: dict[str, str] = {"license_agreements": "license",
                                   "joint_venture_filing": "joint_venture"}
'''
FAKE_CORPUS = '''
from .config import CONTRACT_SUBTYPE_KEYS
DOC_TYPE_SUBCLASSES: dict[str, tuple[str, ...]] = {
    "contract": tuple(CONTRACT_SUBTYPE_KEYS),
    "merger_agreement": tuple(MAUD_CONSIDERATION_TYPES),
    "corporate_record": ("bylaws", "certificate_of_formation"),
    "correspondence": ("email", "other"),
    "insurance_claim": ("auto",),
}
CORPUS_SUBCLASS_SURFACES: dict[str, tuple[str, ...]] = {
    "contract": ("License_Agreements", "Joint Venture _ Filing", "Joint Venture"),
    "merger_agreement": ("all_cash", "other"),
    "corporate_record": ("bylaws",),
    "correspondence": ("email",),
    "insurance_claim": ("auto",),
}
'''


class SyncStrata(unittest.TestCase):
    def make_checkout(self, tmp: Path) -> Path:
        src = tmp / "mailroom-reloaded"
        pkg = src / "src/mailroom_reloaded/scoring"
        pkg.mkdir(parents=True)
        (pkg / "config.py").write_text(FAKE_CONFIG, encoding="utf-8")
        (pkg / "corpus.py").write_text(FAKE_CORPUS, encoding="utf-8")
        return src

    def test_roster_flags_and_check_mode(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as t:
            tmp = Path(t)
            src = self.make_checkout(tmp)
            root = tmp / "content"
            (root / "taxonomy").mkdir(parents=True)
            self.assertEqual(sync_strata.main(["--from", str(src), "--root", str(root),
                                               "--ref", "vtest"]), 0)
            rows = (root / "taxonomy/strata.csv").read_text().splitlines()
            self.assertEqual(rows[0], ",".join(sync_strata.HEADER))
            self.assertIn("contract,joint_venture,true,true,,rows_unverified", rows)
            self.assertIn("corporate_record,certificate_of_formation,false,true,,catalog_only",
                          rows)
            self.assertIn("correspondence,other,false,true,,catalog_only", rows)
            self.assertEqual(sync_strata.main(["--from", str(src), "--root", str(root),
                                               "--check"]), 0)
            # a dataset scan fills rows; regeneration keeps them and marks active
            text = (root / "taxonomy/strata.csv").read_text().replace(
                "insurance_claim,auto,true,true,,rows_unverified",
                "insurance_claim,auto,true,true,200,rows_unverified")
            (root / "taxonomy/strata.csv").write_text(text)
            sync_strata.main(["--from", str(src), "--root", str(root)])
            self.assertIn("insurance_claim,auto,true,true,200,active",
                          (root / "taxonomy/strata.csv").read_text())
            # a hand edit is drift
            with open(root / "taxonomy/strata.csv", "a") as f:
                f.write("contract,parties,true,true,,rows_unverified\n")
            self.assertEqual(sync_strata.main(["--from", str(src), "--root", str(root),
                                               "--check"]), 1)

    def test_unknown_surface_fails_loudly(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as t:
            src = self.make_checkout(Path(t))
            corpus = src / "src/mailroom_reloaded/scoring/corpus.py"
            head, surfaces = FAKE_CORPUS.split("CORPUS_SUBCLASS_SURFACES")
            corpus.write_text(head + "CORPUS_SUBCLASS_SURFACES" + surfaces.replace(
                '"insurance_claim": ("auto",)', '"insurance_claim": ("marine",)'))
            with self.assertRaises(SystemExit):
                sync_strata.load_catalog(src)


class FixturePdf(unittest.TestCase):
    def test_deterministic_and_inert(self):
        a = make_fixture_pdf.build_pdf(["Title (v1)", "Body \\ text"])
        b = make_fixture_pdf.build_pdf(["Title (v1)", "Body \\ text"])
        self.assertEqual(a, b)
        self.assertTrue(a.startswith(b"%PDF-1.4"))
        self.assertIn(b"(Title \\(v1\\))", a)
        for marker in validate.INERT_FORBIDDEN:
            self.assertNotIn(marker, a)
        start = int(a.rsplit(b"startxref\n", 1)[1].split(b"\n")[0])
        self.assertTrue(a[start:].startswith(b"xref"))

    def test_committed_fixtures_reproduce(self):
        lines = ["Schedule C (v2)", "Asset Allocation Summary",
                 "Parties: Northgate Logistics LLC (buyer) and Bluefield Supply Co. (seller).",
                 "Matter: HP-2026-0417. Indemnification cap in section 4.2: $2,000,000.",
                 "All figures herein are fictional and synthetic."]
        data = make_fixture_pdf.build_pdf(lines)
        committed = (REPO_ROOT / "attachments/synthetic/schedule_c_v2.pdf").read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         hashlib.sha256(committed).hexdigest())


class SmokeExport(unittest.TestCase):
    def test_export_is_current_pinned_and_within_budget(self):
        from tools import export_smoke
        subprocess.run([sys.executable, str(REPO_ROOT / "tools/validate.py")],
                       capture_output=True, cwd=REPO_ROOT, check=False)
        files = export_smoke.build(REPO_ROOT)
        manifest = __import__("json").loads(files["manifest.json"])
        self.assertLessEqual(manifest["total_bytes"], 2 * 1024 * 1024)
        self.assertEqual(manifest["dataset_revision"], "ed7576b6")
        for rel, data in files.items():
            if rel.startswith("scenarios/"):
                text = data.decode()
                self.assertNotIn("stratum:", text.split("expect:")[0],
                                 f"{rel} still draws from the dataset")
        for rel in manifest["files"]:
            self.assertIn(rel, files)

    def test_unresolved_draw_and_stale_set_fail(self):
        import shutil
        from tempfile import TemporaryDirectory
        from tools import export_smoke
        with TemporaryDirectory() as t:
            root = Path(t) / "c"
            shutil.copytree(REPO_ROOT, root, ignore=shutil.ignore_patterns(".git", "release"))
            text = (root / "smoke/smoke_set.yaml").read_text()
            (root / "smoke/smoke_set.yaml").write_text(
                text.replace("  - {class: corporate_record, stratum: officer_certificate, "
                             "file: officer_certificate_tc1190.pdf}\n", ""))
            with self.assertRaisesRegex(export_smoke.SmokeError, "has no stand-in"):
                export_smoke.build(root)
            (root / "smoke/smoke_set.yaml").write_text(text.replace(
                "file: coi_unit4c.pdf, doc_id", "file: coi_unit4c.pdf, doc_id_x"))
            with self.assertRaisesRegex(export_smoke.SmokeError, "stale"):
                export_smoke.build(root)


class CoverageScenarios(unittest.TestCase):
    def test_generated_scenarios_are_current(self):
        from tools import gen_coverage_scenarios
        self.assertEqual(gen_coverage_scenarios.main(["--check"]), 0)

    def test_every_ground_truth_stratum_is_walked_once(self):
        from tools import gen_coverage_scenarios
        built = gen_coverage_scenarios.build(REPO_ROOT)
        walked = {(d["doc_type"], d["subclass"])
                  for sc in built.values() for d in sc["expect"]["docs"].values()}
        import csv
        with open(REPO_ROOT / "taxonomy/strata.csv", newline="") as f:
            gt = {(r["class"], r["stratum"]) for r in csv.DictReader(f)
                  if r["in_ground_truth"] == "true"}
        self.assertEqual(walked, gt)


class BuildAttachments(unittest.TestCase):
    def make_root(self, tmp: Path) -> Path:
        import shutil
        root = tmp / "c"
        for rel in ("content.json", "taxonomy/strata.csv", "taxonomy/strata.source.json",
                    "clients/client_doc_mix.csv", "attachments/manifest.csv"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(REPO_ROOT / rel, root / rel)
        return root

    def ground_truth(self, tmp: Path) -> Path:
        import json
        rows = [
            {"filename": "lic_a.txt", "expected": "contract",
             "expected_subclass": "License_Agreements", "split": "train",
             "content_sha256": "aa", "doc_text": "NEVER READ", "subject_matter": "NEVER"},
            {"filename": "lic_b.txt", "expected": "contract",
             "expected_subclass": "License_Agreements", "split": "train",
             "content_sha256": "bb"},
            {"filename": "lic_test.txt", "expected": "contract",
             "expected_subclass": "License_Agreements", "split": "test",
             "content_sha256": "cc"},
            {"filename": "auto_a.txt", "expected": "insurance_claim",
             "expected_subclass": "auto", "split": "train", "content_sha256": "dd"},
        ]
        p = tmp / "gt.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in rows))
        return p

    def test_counts_train_only_and_select_is_stable(self):
        from tempfile import TemporaryDirectory
        from tools import build_attachments
        with TemporaryDirectory() as t:
            tmp = Path(t)
            root, gt = self.make_root(tmp), self.ground_truth(tmp)
            argv = ["--ground-truth", str(gt), "--root", str(root), "--counts", "--select", "1"]
            self.assertEqual(build_attachments.main(argv), 0)
            strata = (root / "taxonomy/strata.csv").read_text()
            self.assertIn("contract,license,true,true,2,active", strata)
            self.assertIn("insurance_claim,auto,true,true,1,active", strata)
            manifest = (root / "attachments/manifest.csv").read_text()
            self.assertNotIn("lic_test.txt", manifest)
            self.assertNotIn("NEVER", manifest + strata)
            self.assertIn("att_1000,", manifest)
            first = manifest
            self.assertEqual(build_attachments.main(argv), 0)
            self.assertEqual((root / "attachments/manifest.csv").read_text(), first)
            report = validate.Report()
            validate.check_id_ranges(root, report)
            self.assertEqual([e for e in report.errors if "att_" in e], [])


class Bundle(unittest.TestCase):
    def test_bundle_is_reproducible_and_complete(self):
        import importlib.util
        import io
        import shutil
        import tarfile
        from tempfile import TemporaryDirectory
        from tools import build_bundle
        if importlib.util.find_spec("zstandard") is None and shutil.which("zstd") is None:
            self.skipTest("needs zstandard or zstd")
        subprocess.run([sys.executable, str(REPO_ROOT / "tools/validate.py")],
                       capture_output=True, cwd=REPO_ROOT, check=False)
        files = build_bundle.tracked_files(REPO_ROOT)
        self.assertIn("dist/registry.yaml", files)
        self.assertFalse([f for f in files if f.startswith((".github/", "release/", ".cache/"))])
        a, b = build_bundle.build_tar(REPO_ROOT, files), build_bundle.build_tar(REPO_ROOT, files)
        self.assertEqual(hashlib.sha256(a).hexdigest(), hashlib.sha256(b).hexdigest())
        with TemporaryDirectory() as t:
            self.assertEqual(build_bundle.main(["--out", t]), 0)
            sums = (Path(t) / "SHA256SUMS").read_text().splitlines()
            self.assertEqual([line.split()[1] for line in sums],
                             ["mailroom-sandbox-content-v"
                              + __import__("json").loads((REPO_ROOT / "content.json")
                                                         .read_text())["version"] + ".tar.zst",
                              "content.json"])
            for line in sums:
                digest, name = line.split()
                self.assertEqual(hashlib.sha256((Path(t) / name).read_bytes()).hexdigest(),
                                 digest)


class BundleToolchainPin(unittest.TestCase):
    """K-01: compressed bytes depend on the zstandard version, so the version is pinned."""

    def test_requirements_pin_matches_the_constant(self):
        """Verify the dependency file and bundle builder pin the same zstandard version."""
        from tools import build_bundle
        reqs = (REPO_ROOT / "tools/requirements.txt").read_text().splitlines()
        self.assertIn(f"zstandard=={build_bundle.PINNED_ZSTANDARD}", reqs)

    def test_release_build_refuses_an_unpinned_version(self):
        """Verify release mode rejects other compressor versions and accepts the pin."""
        from tools import build_bundle
        with self.assertRaises(SystemExit) as cm:
            build_bundle.check_zstandard(True, version="0.23.0")
        self.assertIn(build_bundle.PINNED_ZSTANDARD, str(cm.exception))
        self.assertEqual(build_bundle.check_zstandard(True, version=build_bundle.PINNED_ZSTANDARD),
                         build_bundle.PINNED_ZSTANDARD)

    def test_plain_build_accepts_any_version(self):
        """Verify development builds permit an unpinned compressor version."""
        from tools import build_bundle
        self.assertEqual(build_bundle.check_zstandard(False, version="0.23.0"), "0.23.0")

    def test_build_info_records_tar_digest_and_version(self):
        """Verify bundle metadata records the tar hash and compressor with two checksums."""
        import importlib.util
        import json
        from tempfile import TemporaryDirectory
        from tools import build_bundle
        if importlib.util.find_spec("zstandard") is None:
            self.skipTest("needs zstandard")
        subprocess.run([sys.executable, str(REPO_ROOT / "tools/validate.py")],
                       capture_output=True, cwd=REPO_ROOT, check=False)
        with TemporaryDirectory() as t:
            self.assertEqual(build_bundle.main(["--out", t]), 0)
            info = json.loads((Path(t) / "BUILD_INFO").read_text())
            tar = build_bundle.build_tar(REPO_ROOT, build_bundle.tracked_files(REPO_ROOT))
            self.assertEqual(info["tar_sha256"], hashlib.sha256(tar).hexdigest())
            self.assertEqual(info["zstandard"], build_bundle.zstandard_version())
            # SHA256SUMS stays exactly two lines so `sha256sum -c` keeps working
            self.assertEqual(len((Path(t) / "SHA256SUMS").read_text().splitlines()), 2)


class RealContent(unittest.TestCase):
    def test_every_scenario_message_renders(self):
        import csv
        import jinja2
        import yaml
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(REPO_ROOT / "gen/templates"),
                                 undefined=jinja2.StrictUndefined)
        with open(REPO_ROOT / "personas/personas.csv", newline="") as f:
            personas = {r["persona_id"]: r for r in csv.DictReader(f)}
        with open(REPO_ROOT / "clients/client_contacts.csv", newline="") as f:
            contacts = {r["contact_id"]: r for r in csv.DictReader(f)}
        rendered = 0
        for path in sorted((REPO_ROOT / "scenarios").glob("*/*.yaml")):
            sc = yaml.safe_load(path.read_text())
            for ev in sc["timeline"]:
                c = ev.get("client")
                if not c:
                    continue
                contact = contacts.get(personas[c["persona"]]["contact_id"], {})
                names = [a.get("as") or a.get("file") or "document.pdf"
                         for a in c.get("attach", [])]
                ctx = {"sender_email": c.get("claimed_from", ""),
                       "client_display_name": "Client",
                       "attachment_name": names[0] if names else "",
                       "attachment_names": names}
                if contact:
                    ctx.update(sender_name=contact["full_name"],
                               sender_first_name=contact["full_name"].split()[0],
                               sender_title=contact["role"])
                ctx.update(c.get("vars") or {})
                text = env.get_template(f"{c['template']}.j2").render(**ctx)
                first = text.lstrip().splitlines()[0]
                self.assertTrue(first.startswith("Subject:"), f"{path.name}: {first!r}")
                rendered += 1
        self.assertGreater(rendered, 150)

    def test_validator_passes_on_the_content_pack(self):
        out = subprocess.run([sys.executable, str(REPO_ROOT / "tools/validate.py")],
                             capture_output=True, text=True, cwd=REPO_ROOT)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
