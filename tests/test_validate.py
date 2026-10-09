"""Unit tests for content validation; fixtures never modify the content pack.

Requires the same PyYAML dependency as content-ci. Run from the repo root:
    python3 -m unittest discover -s tests -p 'test_*.py'
"""

import copy
import csv
import hashlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import yaml

from tools import validate


REPO_ROOT = Path(__file__).resolve().parents[1]
CSV_SCHEMA = json.loads(
    (REPO_ROOT / "schemas/content_files.json").read_text(encoding="utf-8")
)


class ContentFixture(unittest.TestCase):
    """Small independent content roots, using the repository's CSV headers."""

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write("schemas/content_files.json", json.dumps(CSV_SCHEMA))
        # The validator checks content against the real JSON Schemas and ID
        # range allocation; the fixture root carries them like a real pack.
        for name in ("scenario.v2.json", "gen_spec.v1.json",
                     "persona_behavior.v1.json", "overlay.v1.json",
                     "registry.v1.json"):
            self.write(f"schemas/{name}",
                       (REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))
        self.write("ids/ranges.yaml",
                   (REPO_ROOT / "ids/ranges.yaml").read_text(encoding="utf-8"))

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_yaml(self, relative, value):
        return self.write(relative, yaml.safe_dump(value))

    def write_csv(self, relative, rows):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=CSV_SCHEMA["files"][relative]["header"]
            )
            writer.writeheader()
            writer.writerows(rows)
        return path

    def check(self, function, *args):
        report = validate.Report()
        result = function(self.root, *args, report)
        return result, report

    def assert_clean(self, report):
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])
        self.assertTrue(report.ok())

    def assert_error(self, report, message):
        self.assertFalse(report.ok())
        self.assertTrue(any(message in error for error in report.errors),
                        report.errors)

    def seed_clients(self):
        self.client = {
            "client_id": "cedar", "display_name": "Cedar Desk",
            "primary_domain": "cedar.sandbox.invalid",
            "callback_contact": "Avery", "callback_phone": "+1-555-0101",
            "channels": "email, phone", "send_hours": "09:00-17:00",
            "matter_format": "CD-{n}", "claim_format": "",
        }
        self.contact = {
            "contact_id": "cedar_avery", "client_id": "cedar",
            "email": "avery@cedar.sandbox.invalid", "is_registered": "true",
        }
        self.domain = {"client_id": "cedar", "domain": "cedar.sandbox.invalid"}
        self.mix = {"client_id": "cedar", "class": "contract",
                    "stratum": "lease", "weight": "1.0"}
        self.client_rows = {
            "clients/clients.csv": [self.client],
            "clients/client_contacts.csv": [self.contact],
            "clients/client_domains.csv": [self.domain],
            "clients/client_doc_mix.csv": [self.mix],
        }
        for path, rows in self.client_rows.items():
            self.write_csv(path, rows)

    def seed_persona(self):
        self.persona = {
            "persona_id": "p_cedar", "client_id": "cedar",
            "contact_id": "cedar_avery", "behavior_file": "behavior/cedar.yaml",
        }
        self.behavior = {"persona_id": "p_cedar", "escalation": {"patience_sim_min": 60, "steps": []},
                         "attachment_habits": {}}
        self.write_csv("personas/personas.csv", [self.persona])
        self.write_yaml("personas/behavior/cedar.yaml", self.behavior)

    def seed_scenario(self):
        self.scenario = {
            "name": "A1_status", "title": "Status check",
            "seed": 1, "profile": "smoke", "gen": "scripted",
            "transports": ["sim"],
            "timeline": [{"at": "00:01", "client": {
                "persona": "p_cedar", "channel": "email",
                "gen_spec": "gen_status", "template": "status",
                "claimed_from": "avery@cedar.sandbox.invalid",
                "auth": {"dkim": "pass"},
                "attach": [{"file": "lease.txt"}]}}],
            "expect": {"intent": "status_request", "signals": [
                {"kind": "status_request", "priority": "normal"}],
                "trust": {"sender_level": "verified"},
                "boss_actions": ["ack_signal"],
                "invariants": ["audit_chain_ok"],
                "relations": [{"kind": "references",
                               "a": "lease.txt", "b": "lease.txt"}]},
        }
        self.write_yaml("scenarios/A/A1_status.yaml", self.scenario)
        self.write_yaml("gen/specs/status.yaml",
                        {"id": "gen_status", "persona": "p_cedar"})
        self.write("gen/templates/status.j2", "Subject: Status, please.\n")
        self.write_csv("attachments/manifest.csv", [{"file": "lease.txt"}])


class PrimitiveTests(ContentFixture):
    def test_weights_parse_numbers_and_reject_unparseable_values(self):
        for raw, expected in (("0.25", 0.25), (" 1 ", 1.0), (0, 0.0),
                              (0.5, 0.5), ("", None), ("bad", None),
                              (None, None), ([], None), ({}, None)):
            with self.subTest(raw=raw):
                self.assertEqual(validate.parse_weight(raw), expected)

    def test_report_warnings_and_infos_do_not_fail_validation(self):
        report = validate.Report()
        report.warn("gap")
        report.info("compiled")
        self.assertTrue(report.ok())
        self.assertEqual(report.warnings, ["gap"])
        self.assertEqual(report.infos, ["compiled"])
        report.error("bad reference")
        self.assertFalse(report.ok())
        self.assertEqual(report.errors, ["bad reference"])
        self.assert_clean(validate.Report())

    def test_id_contracts(self):
        examples = {
            "client_id": ("cedar_1", "Cedar"),
            "contact_id": ("cedar_avery", "cedar-avery"),
            "persona_id": ("p_cedar", "cedar"),
            "scenario": ("T6_round_trip", "U1_round_trip"),
            "spec_id": ("gen_E1_status", "spec_status"),
            "email_id": ("em_A_0001", "em_a_0001"),
            "attachment_id": ("att_0001", "att_one"),
            "relation_id": ("rel_0001", "relation_0001"),
        }
        for kind, (valid, invalid) in examples.items():
            for value, accepted in ((valid, True), (invalid, False), ("", False)):
                with self.subTest(kind=kind, value=value):
                    report = validate.Report()
                    validate.check_id(value, kind, "fixture", report)
                    if accepted:
                        self.assert_clean(report)
                    else:
                        self.assert_error(report, f"bad {kind} id")

    def test_csv_preserves_quoted_unicode_and_multiline_values(self):
        rows = [{"client_id": "cedar", "display_name": "Cèdre, Desk\nTeam"}]
        self.write_csv("clients/clients.csv", rows)
        result, report = self.check(
            validate.check_csv_file, "clients/clients.csv",
            CSV_SCHEMA["files"]["clients/clients.csv"])
        self.assert_clean(report)
        self.assertEqual(result[0]["display_name"], rows[0]["display_name"])

    def test_csv_missing_empty_and_reordered_headers(self):
        for contents, error in ((None, "missing required file"),
                                ("", "header mismatch"),
                                ("value,id\n", "header mismatch"),
                                ("id,value\n", None)):
            with self.subTest(contents=contents):
                if contents is not None:
                    self.write("table.csv", contents)
                result, report = self.check(validate.check_csv_file, "table.csv",
                                            {"header": ["id", "value"]})
                self.assertEqual(result, [])
                if error:
                    self.assert_error(report, error)
                else:
                    self.assert_clean(report)

    def test_content_metadata_required_keys_and_versions(self):
        metadata = {"name": "fixture", "version": "1.2.3",
                    "schema_version": "2.0", "dataset_revision": "fixture",
                    "min_code_version": "0.1.0"}
        for version in ("0.0.0", "1.2.3-rc.1", "1.2", "latest", "1.2.3.4"):
            with self.subTest(version=version):
                value = dict(metadata, version=version)
                self.write("content.json", json.dumps(value))
                result, report = self.check(validate.check_content_json)
                self.assertEqual(result, value)
                if version in ("0.0.0", "1.2.3-rc.1"):
                    self.assert_clean(report)
                else:
                    self.assert_error(report, "version is not semver")
        for key in metadata:
            with self.subTest(missing=key):
                value = dict(metadata)
                del value[key]
                self.write("content.json", json.dumps(value))
                _, report = self.check(validate.check_content_json)
                self.assert_error(report, f"missing key: {key}")

    def test_missing_and_malformed_content_json(self):
        for contents, error in ((None, "missing"), ("{", "not valid JSON")):
            with self.subTest(contents=contents):
                if contents is not None:
                    self.write("content.json", contents)
                result, report = self.check(validate.check_content_json)
                self.assertEqual(result, {})
                self.assert_error(report, error)


class ClientTests(ContentFixture):
    def setUp(self):
        super().setUp()
        self.seed_clients()

    def test_valid_clients_and_cross_references_are_returned(self):
        (clients, contacts, domains, mixes), report = self.check(validate.check_clients)
        self.assert_clean(report)
        self.assertEqual(set(clients), {"cedar"})
        self.assertEqual(set(contacts), {"cedar_avery"})
        self.assertEqual(domains[0]["domain"], "cedar.sandbox.invalid")
        self.assertEqual(mixes[0]["weight"], "1.0")

    def test_invalid_identity_and_client_references(self):
        cases = [
            ("clients", "primary_domain", "cedar.example", "primary_domain"),
            ("clients", "callback_phone", "+1-212-555-1234", "callback_phone"),
            ("clients", "display_name", "GOOGLE Desk", "real brand 'google'"),
            ("client_contacts", "client_id", "missing", "unknown client_id"),
            ("client_contacts", "email", "avery@cedar.example", "contact email"),
            ("client_domains", "client_id", "missing", "unknown client_id"),
            ("client_domains", "domain", "cedar.example", "must end with"),
            ("client_doc_mix", "client_id", "missing", "unknown client_id"),
            ("client_doc_mix", "weight", "oops", "bad weight"),
        ]
        for table, field, value, error in cases:
            with self.subTest(table=table, field=field):
                path = f"clients/{table}.csv"
                rows = copy.deepcopy(self.client_rows[path])
                rows[0][field] = value
                self.write_csv(path, rows)
                _, report = self.check(validate.check_clients)
                self.assert_error(report, error)
                self.write_csv(path, self.client_rows[path])

    def test_duplicate_domains_are_rejected(self):
        self.write_csv("clients/client_domains.csv", [self.domain, self.domain])
        _, report = self.check(validate.check_clients)
        self.assert_error(report, "duplicate domain cedar.sandbox.invalid")

    def test_weights_sum_within_tolerance(self):
        for weight, accepted in (("0.499", True), ("0.501", True),
                                 ("0.489", False), ("0.511", False)):
            with self.subTest(weight=weight):
                self.write_csv("clients/client_doc_mix.csv", [
                    dict(self.mix, weight="0.5"),
                    dict(self.mix, stratum="amendment", weight=weight)])
                _, report = self.check(validate.check_clients)
                if accepted:
                    self.assert_clean(report)
                else:
                    self.assert_error(report, "weights sum to")


class PersonaTests(ContentFixture):
    def setUp(self):
        super().setUp()
        self.seed_persona()

    def check_personas(self):
        return self.check(validate.check_personas, {"cedar": {}}, {"cedar_avery": {}})

    def test_valid_persona_and_adversary_sentinel_references(self):
        for client, contact in (("cedar", "cedar_avery"), ("_adversary", "_none")):
            with self.subTest(client=client):
                self.write_csv("personas/personas.csv", [
                    dict(self.persona, client_id=client, contact_id=contact)])
                result, report = self.check_personas()
                self.assert_clean(report)
                self.assertEqual(set(result), {"p_cedar"})

    def test_unknown_references_and_duplicate_personas(self):
        for field in ("client_id", "contact_id"):
            with self.subTest(field=field):
                self.write_csv("personas/personas.csv", [dict(self.persona, **{field: "missing"})])
                _, report = self.check_personas()
                self.assert_error(report, f"unknown {field}")
        self.write_csv("personas/personas.csv", [self.persona, self.persona])
        _, report = self.check_personas()
        self.assert_error(report, "duplicate persona_id")

    def test_behavior_identity_and_required_fields(self):
        cases = [(dict(self.behavior, persona_id="p_wrong"), "persona_id mismatch")]
        for field in ("escalation", "attachment_habits"):
            behavior = dict(self.behavior)
            del behavior[field]
            cases.append((behavior, "missing escalation or attachment_habits"))
        for behavior, error in cases:
            with self.subTest(behavior=behavior):
                self.write_yaml("personas/behavior/cedar.yaml", behavior)
                _, report = self.check_personas()
                self.assert_error(report, error)

    def test_missing_and_malformed_behavior(self):
        path = self.root / "personas/behavior/cedar.yaml"
        path.unlink()
        _, report = self.check_personas()
        self.assert_error(report, "behavior file missing")
        path.write_text("[", encoding="utf-8")
        _, report = self.check_personas()
        self.assert_error(report, "YAML error")


class ScenarioTests(ContentFixture):
    def setUp(self):
        super().setUp()
        self.seed_scenario()

    def check_scenario(self, scenario):
        self.write_yaml("scenarios/A/A1_status.yaml", scenario)
        return self.check(validate.check_scenarios, {"p_cedar": {"client_id": "cedar"}},
                          {"cedar": {"cedar.sandbox.invalid"}})

    def test_valid_references_and_supported_time_formats(self):
        for at in ("00:01", "01:02:03"):
            with self.subTest(at=at):
                self.scenario["timeline"][0]["at"] = at
                (scenarios, series), report = self.check_scenario(self.scenario)
                self.assert_clean(report)
                self.assertEqual(scenarios, {"A1_status": self.scenario})
                self.assertEqual(series, {"A": ["A1_status"]})

    def test_missing_required_fields(self):
        for field in ("seed", "profile", "gen", "transports", "timeline", "expect"):
            with self.subTest(field=field):
                scenario = copy.deepcopy(self.scenario)
                del scenario[field]
                _, report = self.check_scenario(scenario)
                self.assert_error(report, f"missing required field '{field}'")

    def test_invalid_enums(self):
        cases = [
            (("profile",), "unknown", "bad profile"),
            (("gen",), "unknown", "bad gen"),
            (("transports",), ["smtp"], "bad transport"),
            (("expect", "intent"), "unknown", "bad expect.intent"),
            (("expect", "signals"), [{"kind": "unknown", "priority": "normal"}], "bad signal kind"),
            (("expect", "signals"), [{"kind": "fyi", "priority": "urgent"}], "bad priority"),
            (("expect", "trust"), {"sender_level": "unknown"}, "bad trust.sender_level"),
            (("expect", "boss_actions"), ["unknown"], "bad boss_action"),
            (("expect", "invariants"), ["unknown"], "bad invariant"),
            (("expect", "relations"), [{"kind": "teleports"}], "bad relation kind"),
        ]
        for path, value, error in cases:
            with self.subTest(path=path, value=value):
                scenario = copy.deepcopy(self.scenario)
                target = scenario
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                _, report = self.check_scenario(scenario)
                self.assert_error(report, error)

    def test_timeline_shape_and_event_time_are_checked(self):
        for timeline, error in (([], "non-empty list"), ({}, "non-empty list"),
                                ([{}], "event needs 'at'"),
                                ([{"at": "1:2"}], "bad at")):
            with self.subTest(timeline=timeline):
                _, report = self.check_scenario(dict(self.scenario, timeline=timeline))
                self.assert_error(report, error)

    def test_non_mapping_event_reports_an_error_without_crashing(self):
        _, report = self.check_scenario(dict(self.scenario, timeline=["event"]))
        self.assert_error(report, "event needs 'at'")

    def test_verified_sender_must_belong_to_personas_registered_client(self):
        for sender, accepted in (("avery@cedar.sandbox.invalid", True),
                                 ("avery@CEDAR.sandbox.invalid", True),
                                 ("avery@birch.sandbox.invalid", False),
                                 ("avery@fake.sandbox.invalid", False)):
            with self.subTest(sender=sender):
                scenario = copy.deepcopy(self.scenario)
                scenario["timeline"][0]["client"]["claimed_from"] = sender
                self.write_yaml("scenarios/A/A1_status.yaml", scenario)
                _, report = self.check(
                    validate.check_scenarios, {"p_cedar": {"client_id": "cedar"}},
                    {"cedar": {"cedar.sandbox.invalid"}, "birch": {"birch.sandbox.invalid"}})
                if accepted:
                    self.assert_clean(report)
                else:
                    self.assert_error(report, "is not registered for client 'cedar'")

    def test_unverified_sender_may_use_an_unregistered_synthetic_domain(self):
        scenario = copy.deepcopy(self.scenario)
        scenario["timeline"][0]["client"]["claimed_from"] = "avery@fake.sandbox.invalid"
        scenario["expect"]["trust"]["sender_level"] = "unverified"
        _, report = self.check_scenario(scenario)
        self.assert_clean(report)

    def test_quarantine_must_reference_an_attached_manifest_file(self):
        scenario = copy.deepcopy(self.scenario)
        scenario["expect"]["quarantine"] = ["lease.txt"]
        _, report = self.check_scenario(scenario)
        self.assert_clean(report)
        scenario["timeline"][0]["client"]["attach"] = []
        _, report = self.check_scenario(scenario)
        self.assert_error(report, "is not attached anywhere in the timeline")
        scenario["timeline"][0]["client"]["attach"] = [{"file": "lease.txt"}]
        self.write_csv("attachments/manifest.csv", [])
        _, report = self.check_scenario(scenario)
        self.assert_error(report, "expect.quarantine 'lease.txt' not in attachments/manifest.csv")

    def test_unknown_timeline_references_and_unsafe_identity(self):
        cases = [("persona", "p_missing", "unknown persona"),
                 ("gen_spec", "gen_missing", "unknown gen_spec"),
                 ("template", "missing.j2", "unknown template"),
                 ("claimed_from", "avery@cedar.example", "claimed_from must be"),
                 ("auth", {"dkim": "maybe"}, "bad auth dkim")]
        for field, value, error in cases:
            with self.subTest(field=field):
                scenario = copy.deepcopy(self.scenario)
                scenario["timeline"][0]["client"][field] = value
                _, report = self.check_scenario(scenario)
                self.assert_error(report, error)
        scenario = copy.deepcopy(self.scenario)
        scenario["timeline"][0]["client"]["attach"] = [{"file": "missing.pdf"}]
        _, report = self.check_scenario(scenario)
        self.assert_error(report, "not in attachments/manifest.csv")

    def test_possible_attack_requires_a_recognized_class(self):
        for attack_class in (None, "unknown", "injection"):
            with self.subTest(attack_class=attack_class):
                scenario = copy.deepcopy(self.scenario)
                signal = {"kind": "possible_attack", "priority": "high"}
                if attack_class is not None:
                    signal["attack_class"] = attack_class
                scenario["expect"]["signals"] = [signal]
                _, report = self.check_scenario(scenario)
                if attack_class == "injection":
                    self.assert_clean(report)
                else:
                    self.assert_error(report, "possible_attack needs attack_class")

    def test_filename_series_and_duplicate_names(self):
        _, report = self.check_scenario(dict(self.scenario, name="B1_status"))
        self.assert_error(report, "filename stem")
        self.assert_error(report, "does not start with series")
        self.write_yaml("scenarios/A/duplicate.yaml", self.scenario)
        _, report = self.check_scenario(self.scenario)
        self.assert_error(report, "duplicate scenario name")

    def test_bad_yaml_is_reported_and_other_scenarios_are_kept(self):
        for text, error in (("[", "YAML error"), ("[]", "top level must be a mapping")):
            with self.subTest(text=text):
                self.write("scenarios/A/broken.yaml", text)
                (scenarios, _), report = self.check(
                    validate.check_scenarios, {"p_cedar": {"client_id": "cedar"}},
                    {"cedar": {"cedar.sandbox.invalid"}})
                self.assert_error(report, error)
                self.assertEqual(set(scenarios), {"A1_status"})

    def test_identity_dependent_gmail_scenario_warns_without_failing(self):
        (self.root / "scenarios/A/A1_status.yaml").unlink()
        scenario = dict(self.scenario, name="E1_identity", transports=["gmail"])
        self.write_yaml("scenarios/E/E1_identity.yaml", scenario)
        _, report = self.check(validate.check_scenarios, {"p_cedar": {"client_id": "cedar"}},
                               {"cedar": {"cedar.sandbox.invalid"}})
        self.assertTrue(report.ok(), report.errors)
        self.assertEqual(len(report.warnings), 1)
        self.assertIn("identity-dependent", report.warnings[0])


class GenerationSpecTests(ContentFixture):
    def setUp(self):
        super().setUp()
        self.spec = {
            "id": "gen_status", "persona": "p_cedar", "target_client": "cedar",
            "archetype": "status", "goal": "Ask for status",
            "constraints": {"forbidden": ["real_brands", "real_urls", "working_links",
                                           "phone_numbers_outside_555_01xx"]},
            "style": {}, "pool": "free", "expect": {"intent": "status_request"},
        }

    def check_spec(self, spec):
        self.write_yaml("gen/specs/status.yaml", spec)
        return self.check(validate.check_gen_specs, {"p_cedar": {}})

    def test_valid_generation_spec(self):
        result, report = self.check_spec(self.spec)
        self.assert_clean(report)
        self.assertEqual(result, {"gen_status": self.spec})

    def test_required_fields(self):
        for field in ("persona", "target_client", "archetype", "goal",
                      "constraints", "style", "pool", "expect"):
            with self.subTest(field=field):
                spec = copy.deepcopy(self.spec)
                del spec[field]
                _, report = self.check_spec(spec)
                self.assert_error(report, f"missing '{field}'")

    def test_invalid_id_persona_and_intent(self):
        for field, value, error in (("id", "bad", "bad spec_id"),
                                    ("persona", "p_missing", "unknown persona"),
                                    ("expect", {"intent": "bad"}, "bad expect.intent")):
            with self.subTest(field=field):
                _, report = self.check_spec(dict(self.spec, **{field: value}))
                self.assert_error(report, error)

    def test_missing_safety_constraints_are_warnings(self):
        for forbidden in self.spec["constraints"]["forbidden"]:
            with self.subTest(forbidden=forbidden):
                spec = copy.deepcopy(self.spec)
                spec["constraints"]["forbidden"].remove(forbidden)
                _, report = self.check_spec(spec)
                self.assertTrue(report.ok(), report.errors)
                self.assertEqual(len(report.warnings), 1)
                self.assertIn(forbidden, report.warnings[0])

    def test_duplicate_ids_and_malformed_yaml(self):
        self.write_yaml("gen/specs/copy.yaml", self.spec)
        _, report = self.check_spec(self.spec)
        self.assert_error(report, "duplicate gen spec id")
        self.write("gen/specs/copy.yaml", "[")
        result, report = self.check_spec(self.spec)
        self.assert_error(report, "YAML error")
        self.assertEqual(set(result), {"gen_status"})


class EmailTests(ContentFixture):
    def setUp(self):
        super().setUp()
        # Explicit canonical bytes make the digest oracle independent of the helper.
        self.canonical = '{"body":"Bonjour, Zoë","email_id":"em_A_0001"}'.encode("utf-8")
        self.email = {"email_id": "em_A_0001", "body": "Bonjour, Zoë"}
        self.row = {"email_id": "em_A_0001", "tier": "scripted",
                    "sha256": hashlib.sha256(self.canonical).hexdigest()}
        self.write_csv("emails/emails_index.csv", [self.row])
        self.write("emails/frozen/A.jsonl", "\n" + json.dumps(self.email) + "\n\n")

    def test_canonical_json_sorts_nested_keys_and_preserves_unicode(self):
        self.assertEqual(validate.canonical_email_json(self.email), self.canonical)
        nested = {"z": {"b": 2, "a": 1}, "a": ["é", 2]}
        self.assertEqual(validate.canonical_email_json(nested),
                         '{"a":["é",2],"z":{"a":1,"b":2}}'.encode("utf-8"))

    def test_frozen_email_hash_ignores_json_spacing_and_key_order(self):
        _, report = self.check(validate.check_emails)
        self.assert_clean(report)

    def test_changed_body_invalidates_frozen_hash(self):
        self.write("emails/frozen/A.jsonl", json.dumps(dict(self.email, body="changed")))
        _, report = self.check(validate.check_emails)
        self.assert_error(report, "sha256 mismatch")

    def test_missing_frozen_email_or_wrong_series(self):
        for content in ("", json.dumps(dict(self.email, email_id="em_B_0001"))):
            with self.subTest(content=content):
                self.write("emails/frozen/A.jsonl", content)
                _, report = self.check(validate.check_emails)
                self.assert_error(report, "no line in emails/frozen/A.jsonl")

    def test_malformed_json_line_does_not_hide_valid_following_line(self):
        self.write("emails/frozen/A.jsonl", "{\n" + json.dumps(self.email))
        _, report = self.check(validate.check_emails)
        self.assertEqual(len(report.errors), 1)
        self.assert_error(report, "A.jsonl:1: bad JSON")

    def test_bad_email_id_and_tier(self):
        for field, value, error in (("email_id", "em_a_1", "bad email_id"),
                                    ("tier", "unknown", "bad tier")):
            with self.subTest(field=field):
                self.write_csv("emails/emails_index.csv", [dict(self.row, **{field: value})])
                _, report = self.check(validate.check_emails)
                self.assert_error(report, error)

    def test_missing_email_index_is_nonfatal(self):
        (self.root / "emails/emails_index.csv").unlink()
        _, report = self.check(validate.check_emails)
        self.assertTrue(report.ok())
        self.assertEqual(len(report.warnings), 1)
        self.assertIn("no frozen emails yet", report.warnings[0])

    def test_handwritten_front_matter(self):
        fields = {"email_id": "em_A_0001", "spec_id": "gen_status",
                  "scenario_id": "A1_status", "persona_id": "p_cedar"}
        self.write("emails/handwritten/anchor.md", "---\n" + yaml.safe_dump(fields) + "---\nHi")
        _, report = self.check(validate.check_emails)
        self.assert_clean(report)
        for field in fields:
            with self.subTest(field=field):
                partial = dict(fields)
                del partial[field]
                self.write("emails/handwritten/anchor.md", "---\n" + yaml.safe_dump(partial) + "---\nHi")
                _, report = self.check(validate.check_emails)
                self.assert_error(report, f"front matter missing '{field}'")
        for content, error in (("Hi", "missing front matter"),
                               ("---\n[\n---\nHi", "front matter error")):
            with self.subTest(content=content):
                self.write("emails/handwritten/anchor.md", content)
                _, report = self.check(validate.check_emails)
                self.assert_error(report, error)


class AttachmentTests(ContentFixture):
    def setUp(self):
        super().setUp()
        self.data = b"Synthetic fixture\n"
        digest = hashlib.sha256(self.data).hexdigest()
        self.row = {"attachment_id": "att_0001", "file": "fixture.txt",
                    "sha256": digest, "doc_id": digest[:16],
                    "source": "synthetic", "inert": "true"}
        self.write_csv("attachments/manifest.csv", [self.row])

    def test_local_attachment_search_locations(self):
        for directory in ("attachments/synthetic", "attachments/offtaxonomy",
                          "attachments/adversarial", "smoke/docs"):
            with self.subTest(directory=directory):
                path = self.write(f"{directory}/fixture.txt", self.data.decode())
                _, report = self.check(validate.check_attachments)
                self.assert_clean(report)
                path.unlink()

    def test_missing_file_and_mismatched_integrity_fields(self):
        _, report = self.check(validate.check_attachments)
        self.assert_error(report, "not found under attachments")
        self.write("attachments/synthetic/fixture.txt", self.data.decode())
        for field, error in (("sha256", "sha256 mismatch"),
                             ("doc_id", "doc_id must be first 16 hex")):
            with self.subTest(field=field):
                self.write_csv("attachments/manifest.csv", [dict(self.row, **{field: "0" * 64})])
                _, report = self.check(validate.check_attachments)
                self.assert_error(report, error)

    def test_duplicate_filenames_and_invalid_ids(self):
        self.write("attachments/synthetic/fixture.txt", self.data.decode())
        self.write_csv("attachments/manifest.csv", [self.row, dict(self.row, attachment_id="att_0002")])
        _, report = self.check(validate.check_attachments)
        self.assert_error(report, "duplicate file")
        self.write_csv("attachments/manifest.csv", [dict(self.row, attachment_id="bad")])
        _, report = self.check(validate.check_attachments)
        self.assert_error(report, "bad attachment_id")

    def test_dataset_references_require_provenance_without_local_bytes(self):
        row = dict(self.row, source="dataset", dataset_revision="revision-1",
                   dataset_filename="original.pdf")
        self.write_csv("attachments/manifest.csv", [row])
        _, report = self.check(validate.check_attachments)
        self.assert_clean(report)
        for field in ("dataset_revision", "dataset_filename"):
            with self.subTest(field=field):
                self.write_csv("attachments/manifest.csv", [dict(row, **{field: ""})])
                _, report = self.check(validate.check_attachments)
                self.assert_error(report, "needs dataset_revision + dataset_filename")

    def test_active_content_markers_are_rejected_even_with_correct_hashes(self):
        markers = (b"/JavaScript", b"/JS ", b"/Launch", b"/Win ", b"/Mac ",
                   b"MZ\x90\x00", b"\x7fELF")
        path = self.write("attachments/adversarial/fixture.txt", "")
        for marker in markers:
            with self.subTest(marker=marker):
                data = self.data + marker
                path.write_bytes(data)
                digest = hashlib.sha256(data).hexdigest()
                self.write_csv("attachments/manifest.csv", [dict(self.row, sha256=digest, doc_id=digest[:16])])
                _, report = self.check(validate.check_attachments)
                self.assertEqual(len(report.errors), 1)
                self.assert_error(report, "contains forbidden marker")

    def test_missing_manifest_warns(self):
        (self.root / "attachments/manifest.csv").unlink()
        _, report = self.check(validate.check_attachments)
        self.assertTrue(report.ok())
        self.assertEqual(report.warnings, ["attachments/manifest.csv missing"])


class RegistryTests(ContentFixture):
    def setUp(self):
        super().setUp()
        self.seed_clients()

    def compile(self, clients=None, contacts=None, domains=None, lookalikes=None):
        return self.check(
            validate.compile_registry,
            clients if clients is not None else {"cedar": self.client},
            contacts if contacts is not None else {"cedar_avery": self.contact},
            domains if domains is not None else [self.domain],
            lookalikes if lookalikes is not None else set())

    def test_registry_compiles_class_totals_and_verified_contacts_only(self):
        self.write_csv("clients/client_doc_mix.csv", [
            dict(self.mix, weight="0.3333"),
            dict(self.mix, stratum="amendment", weight="0.3333"),
            dict(self.mix, **{"class": "claim", "weight": "0.3334"})])
        contacts = {
            "z": dict(self.contact, email="z@cedar.sandbox.invalid"),
            "a": self.contact,
            "unregistered": dict(self.contact, email="outsider@cedar.sandbox.invalid", is_registered="false"),
            "other": dict(self.contact, client_id="birch", email="avery@birch.sandbox.invalid"),
        }
        domains = [dict(self.domain, domain="z.cedar.sandbox.invalid"), self.domain,
                   {"client_id": "birch", "domain": "birch.sandbox.invalid"}]
        result, report = self.compile(contacts=contacts, domains=domains)
        self.assert_clean(report)
        self.assertEqual(result, {"version": 1, "clients": {"cedar": {
            "display_name": "Cedar Desk",
            "verified_domains": ["cedar.sandbox.invalid", "z.cedar.sandbox.invalid"],
            "verified_addresses": ["avery@cedar.sandbox.invalid", "z@cedar.sandbox.invalid"],
            "callback": {"contact": "Avery", "phone": "+1-555-0101"},
            "reference_formats": {"matter": "CD-{n}", "claim": None},
            "usual_channels": ["email", "phone"], "normal_send_hours": "09:00-17:00",
            "usual_mix": {"claim": 0.333, "contract": 0.667},
        }}})
        self.assertEqual(yaml.safe_load((self.root / "dist/registry.yaml").read_text()), result)

    def test_optional_registry_fields_default_and_output_is_repeatable(self):
        minimal = {key: self.client[key] for key in ("display_name", "callback_contact", "callback_phone")}
        (self.root / "clients/client_doc_mix.csv").unlink()
        result, report = self.compile(clients={"cedar": minimal}, contacts={}, domains=[])
        self.assert_clean(report)
        client = result["clients"]["cedar"]
        self.assertEqual(client["usual_channels"], ["email"])
        self.assertEqual(client["reference_formats"], {"matter": None, "claim": None})
        self.assertEqual(client["usual_mix"], {})
        self.assertEqual(client["verified_addresses"], [])
        self.assertEqual(client["verified_domains"], [])
        before = (self.root / "dist/registry.yaml").read_bytes()
        self.compile(clients={"cedar": minimal}, contacts={}, domains=[])
        self.assertEqual((self.root / "dist/registry.yaml").read_bytes(), before)

    def test_bad_mix_weight_does_not_crash_registry_or_hide_valid_rows(self):
        self.write_csv("clients/client_doc_mix.csv", [
            dict(self.mix, weight="invalid"), self.mix])
        registry, report = self.compile()
        self.assert_clean(report)
        self.assertEqual(registry["clients"]["cedar"]["usual_mix"], {"contract": 1.0})

    def test_lookalike_leaks_are_case_insensitive(self):
        _, report = self.compile(domains=[dict(self.domain, domain="FAKE.sandbox.invalid")],
                                 lookalikes={"fake.SANDBOX.invalid"})
        self.assert_error(report, "lookalike domain")

    def test_adversarial_labels_cannot_enter_registry_fields(self):
        for word in ("IMPOSTOR", "SCENARIO_IDS", "ATTACK_CLASS"):
            with self.subTest(word=word):
                _, report = self.compile(clients={"cedar": dict(self.client, display_name=word)})
                self.assert_error(report, f"forbidden token '{word.lower()}'")

    def test_adversary_tables_are_read_separately_and_never_compiled(self):
        self.write_csv("adversary/lookalike_domains.csv", [
            {"domain": "fake.sandbox.invalid"}, {"domain": "fake.sandbox.invalid"}])
        self.write_csv("adversary/impostor_personas.csv", [{"persona_id": "p_impostor"}])
        (lookalikes, impostors), report = self.check(validate.check_adversary)
        self.assert_clean(report)
        self.assertEqual(lookalikes, {"fake.sandbox.invalid"})
        self.assertEqual(impostors, {"p_impostor"})
        registry, report = self.compile(lookalikes=lookalikes)
        self.assert_clean(report)
        self.assertNotIn("fake.sandbox.invalid", json.dumps(registry))
        self.assertNotIn("p_impostor", json.dumps(registry))


class LeakScanTests(ContentFixture):
    def scan(self, text):
        self.write("gen/specs/fixture.yaml", text)
        return self.check(validate.leak_scan)[1]

    def test_reserved_urls_and_synthetic_phones_are_accepted(self):
        for host in ("cedar.sandbox.invalid", "mail.example", "mail.test",
                     "mail.localhost", "localhost"):
            with self.subTest(host=host):
                self.assert_clean(self.scan(f"https://{host}:8080/path?q=1\n+1-555-0101"))

    def test_real_urls_and_non_synthetic_phones_are_errors(self):
        for text, error in (("https://outside.com/path", "non-reserved URL host"),
                            ("https://cedar.sandbox.invalid.evil.com", "non-reserved URL host"),
                            ("Call +1-212-555-1234.", "non-synthetic phone number"),
                            ("Call (212) 555-1234.", "non-synthetic phone number")):
            with self.subTest(text=text):
                self.assert_error(self.scan(text), error)

    def test_brand_matching_uses_word_boundaries_and_is_case_insensitive(self):
        self.assert_clean(self.scan("straight target_client integer"))
        for text in ("GOOGLE", "State Farm"):
            with self.subTest(text=text):
                report = self.scan(text)
                self.assertTrue(report.ok())
                self.assertEqual(len(report.warnings), 1)
                self.assertIn("real-brand mention", report.warnings[0])

    def test_allowlist_blanking_preserves_later_brand_warning_context(self):
        self.write("tools/brand_allowlist.txt", "# approved host\n\nGMAIL.GOOGLEAPIS.COM\n")
        self.assert_clean(self.scan("https://gmail.googleapis.com/path"))
        report = self.scan("https://gmail.googleapis.com/" + "x" * 80 + " NVIDIA tail")
        self.assertEqual(report.errors, [])
        self.assertEqual(len(report.warnings), 1)
        self.assertIn("'nvidia'", report.warnings[0])
        self.assertIn("NVIDIA tail", report.warnings[0])
        self.assert_error(self.scan("https://gmail.googleapis.com.evil.com"), "non-reserved URL host")

    def test_hex_digest_digit_runs_are_not_phone_numbers(self):
        self.assert_clean(self.scan("sha256: abc1234567890def\nprompt_hash: f012345678901a"))

    def test_pasted_text_warning_boundary_and_directory_scope(self):
        self.assert_clean(self.scan("x" * 2000))
        report = self.scan("x" * 2001)
        self.assertTrue(report.ok())
        self.assertEqual(len(report.warnings), 1)
        self.assertIn("very long line (2001 chars)", report.warnings[0])
        (self.root / "gen/specs/fixture.yaml").unlink()
        self.write("protocol/notes.md", "x" * 2001)
        _, report = self.check(validate.leak_scan)
        self.assert_clean(report)

    def test_binary_and_excluded_suffixes_do_not_break_scan(self):
        for suffix in ("pdf", "png", "bin"):
            self.write(f"attachments/fixture.{suffix}", "https://outside.com +1-212-555-1234")
        path = self.write("attachments/unreadable.docm", "")
        path.write_bytes(b"\xff\xfehttps://outside.com")
        _, report = self.check(validate.leak_scan)
        self.assert_clean(report)


class OperationsContractTests(ContentFixture):
    def setUp(self):
        super().setUp()
        self.ingress = {
            "schema": "mailroom.ingress_policy/v1",
            "sources": {source: {"rate": {"max_items_per_minute": 1, "burst": 1},
                                  "on_queue_full": "shed_to_pending"}
                        for source in ("documents", "emails", "external_correspondence")},
            "correspondent_inbox": {"max_admissions_per_hour": 1,
                                    "max_concurrent_open_threads": 1},
            "queues": {"pending": {"depth_warn": 1, "depth_max": 2}},
            "backpressure": {"never_silently_drop": True},
        }
        self.schedule = {
            "schema": "mailroom.send_schedule/v1", "active_profiles": ["smoke"],
            "models": {"tier": "free_only", "paid_tier_use": "forbidden"},
            "schedule": [{"name": "morning", "cron": "0 * * * *", "max_sends_per_window": 1}],
            "caps": {"max_sends_per_hour_total": 3},
            "doom_loop_prevention": {
                "kill_switch": {"env_var": "TEST_STOP", "file_flag": "/tmp/test-stop"},
                "circuit_breaker": {"auto_reset": False},
                "max_reply_depth_per_thread": 1, "no_auto_reply_to_auto_reply": True,
                "idempotency": {"key": "sha256(outbound_message_id + content_hash)"},
                "sends_may_not_enqueue_sends": True,
            },
        }
        self.recipients = {
            "schema": "mailroom.recipient_policy/v1",
            "closed": {"allowed_recipients": ["desk@cedar.sandbox.invalid"]},
            "egress": {"allowed_recipients": ["avery@cedar.sandbox.invalid"]},
            "external_inbound": {"allowed": False},
        }
        self.write_contracts()

    def write_contracts(self):
        self.write_yaml("email/ingress_policy.yaml", self.ingress)
        self.write_yaml("email/send_schedule.yaml", self.schedule)
        self.write_yaml("email/recipient_policy.yaml", self.recipients)

    def test_recipient_profiles_require_nonempty_lists_of_strings(self):
        for profile in ("closed", "egress"):
            for recipients, error in (([], "must be a non-empty list"),
                                      (None, "must be a non-empty list"),
                                      ("desk", "must be a non-empty list"),
                                      (["desk", 3], "entries must be strings")):
                with self.subTest(profile=profile, recipients=recipients):
                    policy = copy.deepcopy(self.recipients)
                    policy[profile]["allowed_recipients"] = recipients
                    self.write_yaml("email/recipient_policy.yaml", policy)
                    _, report = self.check(validate.check_ops_contracts)
                    self.assert_error(report, f"{profile}.allowed_recipients {error}")

    def test_external_inbound_requires_an_explicit_boolean(self):
        for allowed in (True, False, "false", 0, None):
            with self.subTest(allowed=allowed):
                policy = copy.deepcopy(self.recipients)
                policy["external_inbound"]["allowed"] = allowed
                self.write_yaml("email/recipient_policy.yaml", policy)
                _, report = self.check(validate.check_ops_contracts)
                if isinstance(allowed, bool):
                    self.assert_clean(report)
                else:
                    self.assert_error(report, "external_inbound.allowed must be a boolean")

    def test_priority_reserve_is_nonnegative_and_strictly_below_admissions_cap(self):
        for reserve in (0, 1, 2, 3, -1, "1", None):
            with self.subTest(reserve=reserve):
                policy = copy.deepcopy(self.ingress)
                policy["correspondent_inbox"].update(
                    max_admissions_per_hour=2, priority_reserve_per_hour=reserve)
                self.write_yaml("email/ingress_policy.yaml", policy)
                _, report = self.check(validate.check_ops_contracts)
                if reserve in (0, 1):
                    self.assert_clean(report)
                elif reserve in (2, 3):
                    self.assert_error(report, "must be less than max_admissions_per_hour")
                else:
                    self.assert_error(report, "priority_reserve_per_hour must be a non-negative int")

    def test_idempotency_key_distinguishes_outbound_messages(self):
        for key in ("", "sha256(thread_id + content_hash)",
                    "sha256(outbound_message_id + content_hash)"):
            with self.subTest(key=key):
                schedule = copy.deepcopy(self.schedule)
                schedule["doom_loop_prevention"]["idempotency"]["key"] = key
                self.write_yaml("email/send_schedule.yaml", schedule)
                _, report = self.check(validate.check_ops_contracts)
                if "outbound_message_id" in key:
                    self.assert_clean(report)
                else:
                    self.assert_error(report, "must include the outbound message identity")

    def test_valid_contracts_at_minimum_positive_limits(self):
        _, report = self.check(validate.check_ops_contracts)
        self.assert_clean(report)

    def test_contract_files_must_be_present_parseable_mappings(self):
        for filename in ("ingress_policy", "send_schedule", "recipient_policy"):
            for content, error in ((None, "missing"), ("[", "not valid YAML"),
                                   ("[]", "top level must be a mapping")):
                with self.subTest(filename=filename, content=content):
                    self.write_contracts()
                    path = self.root / f"email/{filename}.yaml"
                    if content is None:
                        path.unlink()
                    else:
                        path.write_text(content, encoding="utf-8")
                    _, report = self.check(validate.check_ops_contracts)
                    self.assert_error(report, f"email/{filename}.yaml")
                    self.assert_error(report, error)

    def test_contract_schema_versions_are_checked(self):
        for filename, contract in (("ingress_policy", self.ingress),
                                    ("send_schedule", self.schedule),
                                    ("recipient_policy", self.recipients)):
            with self.subTest(filename=filename):
                self.write_contracts()
                self.write_yaml(f"email/{filename}.yaml", dict(contract, schema="wrong/v1"))
                _, report = self.check(validate.check_ops_contracts)
                self.assert_error(report, "schema='wrong/v1'")

    def test_source_rates_and_inbox_limits_require_positive_integers(self):
        paths = [("sources", source, "rate", key)
                 for source in ("documents", "emails", "external_correspondence")
                 for key in ("max_items_per_minute", "burst")]
        paths += [("correspondent_inbox", key)
                  for key in ("max_admissions_per_hour", "max_concurrent_open_threads")]
        for path in paths:
            for value in (0, -1, 1.5, "1", None):
                with self.subTest(path=path, value=value):
                    policy = copy.deepcopy(self.ingress)
                    target = policy
                    for key in path[:-1]:
                        target = target[key]
                    target[path[-1]] = value
                    self.write_yaml("email/ingress_policy.yaml", policy)
                    _, report = self.check(validate.check_ops_contracts)
                    self.assert_error(report, f"{'.'.join(path)} must be a positive int")

    def test_ingress_cannot_silently_drop_items(self):
        for source in self.ingress["sources"]:
            with self.subTest(source=source):
                policy = copy.deepcopy(self.ingress)
                policy["sources"][source]["on_queue_full"] = "drop"
                self.write_yaml("email/ingress_policy.yaml", policy)
                _, report = self.check(validate.check_ops_contracts)
                self.assert_error(report, f"sources.{source}.on_queue_full")
        for value in (False, "true", None):
            with self.subTest(never_silently_drop=value):
                policy = copy.deepcopy(self.ingress)
                policy["backpressure"]["never_silently_drop"] = value
                self.write_yaml("email/ingress_policy.yaml", policy)
                _, report = self.check(validate.check_ops_contracts)
                self.assert_error(report, "backpressure.never_silently_drop must be true")

    def test_queue_max_must_strictly_exceed_warning_threshold(self):
        for maximum in (0, 1, 2):
            with self.subTest(maximum=maximum):
                self.ingress["queues"]["pending"]["depth_max"] = maximum
                self.write_contracts()
                _, report = self.check(validate.check_ops_contracts)
                if maximum == 2:
                    self.assert_clean(report)
                else:
                    self.assert_error(report, "depth_max must exceed depth_warn")

    def test_sending_safety_guards(self):
        cases = [
            (("active_profiles",), ["smoke", "production"], "must never include production"),
            (("models", "tier"), "paid", "models.tier must be free_only"),
            (("models", "paid_tier_use"), "allowed", "paid_tier_use must be forbidden"),
            (("doom_loop_prevention", "kill_switch", "env_var"), "", "needs both env_var and file_flag"),
            (("doom_loop_prevention", "kill_switch", "file_flag"), "", "needs both env_var and file_flag"),
            (("doom_loop_prevention", "circuit_breaker", "auto_reset"), True, "auto_reset must be false"),
            (("doom_loop_prevention", "max_reply_depth_per_thread"), "1", "max_reply_depth_per_thread must be set"),
            (("doom_loop_prevention", "no_auto_reply_to_auto_reply"), False,
             "no_auto_reply_to_auto_reply must be true"),
            (("doom_loop_prevention", "sends_may_not_enqueue_sends"), False,
             "sends_may_not_enqueue_sends must be true"),
        ]
        for path, value, error in cases:
            with self.subTest(path=path):
                schedule = copy.deepcopy(self.schedule)
                target = schedule
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                self.write_yaml("email/send_schedule.yaml", schedule)
                _, report = self.check(validate.check_ops_contracts)
                self.assert_error(report, error)

    def test_schedule_window_cron_and_send_limits(self):
        for field, value, error in (("cron", "0 * * *", "cron must have 5 fields"),
                                    ("cron", "0 * * * * *", "cron must have 5 fields"),
                                    ("max_sends_per_window", 0, "must be a positive int"),
                                    ("max_sends_per_window", -1, "must be a positive int"),
                                    ("max_sends_per_window", "1", "must be a positive int")):
            with self.subTest(field=field, value=value):
                schedule = copy.deepcopy(self.schedule)
                schedule["schedule"][0][field] = value
                self.write_yaml("email/send_schedule.yaml", schedule)
                _, report = self.check(validate.check_ops_contracts)
                self.assert_error(report, error)

    def test_hourly_cap_warning_boundary(self):
        for cap, warning_count in ((3, 0), (4, 1)):
            with self.subTest(cap=cap):
                self.schedule["caps"]["max_sends_per_hour_total"] = cap
                self.write_contracts()
                _, report = self.check(validate.check_ops_contracts)
                self.assertTrue(report.ok())
                self.assertEqual(len(report.warnings), warning_count)
                if warning_count:
                    self.assertIn("window caps look far below", report.warnings[0])


class DerivedOutputTests(ContentFixture):
    def test_coverage_deduplicates_and_sorts_only_positive_known_strata(self):
        self.write_csv("taxonomy/strata.csv", [{"class": "contract", "stratum": "lease", "in_ground_truth": "true"}])
        mixes = [{"client_id": client, "class": "contract", "stratum": "lease", "weight": weight}
                 for client, weight in (("z", "1"), ("a", "0.5"), ("z", "1"),
                                        ("zero", "0"), ("negative", "-1"), ("empty", ""), ("invalid", "oops"))]
        mixes.append({"client_id": "unknown", "class": "contract", "stratum": "other", "weight": "1"})
        event = {"client": {"attach": [{"class": "contract", "stratum": "lease"}]}}
        scenarios = {"A2_status": {"timeline": [event, event]},
                     "A1_status": {"timeline": [event]},
                     "A3_empty": {"timeline": [{"client": {"attach": None}}]}}
        self.write_csv("attachments/manifest.csv", [
            {"attachment_id": aid, "class": "contract", "stratum": "lease", "in_taxonomy": included}
            for aid, included in (("att_0002", "true"), ("att_0001", "true"),
                                  ("att_0002", "true"), ("att_0003", "false"))])
        coverage, report = self.check(validate.coverage_report, mixes, scenarios)
        self.assert_clean(report)
        self.assertEqual(coverage, {"contract/lease": {
            "clients": ["a", "z"], "scenarios": ["A1_status", "A2_status"],
            "attachments": ["att_0001", "att_0002"]}})
        self.assertIn("1/1 ground-truth strata", report.infos[0])

    def test_coverage_gaps_warn_without_failing(self):
        self.write_csv("taxonomy/strata.csv", [
            {"class": "contract", "stratum": name, "in_ground_truth": "true"}
            for name in ("empty", "client", "scenario")])
        mixes = [{"client_id": "cedar", "class": "contract", "stratum": "client", "weight": "1"}]
        scenarios = {"A1_status": {"timeline": [{"client": {"attach": [
            {"class": "contract", "stratum": "scenario"}]}}]}}
        _, report = self.check(validate.coverage_report, mixes, scenarios)
        self.assertTrue(report.ok())
        self.assertEqual(report.warnings, [
            "coverage: contract/client has no scenario",
            "coverage: contract/empty has no client + scenario",
            "coverage: contract/scenario has no client"])

    def test_absent_taxonomy_has_empty_coverage(self):
        coverage, report = self.check(validate.coverage_report, [], {})
        self.assert_clean(report)
        self.assertEqual(coverage, {})

    def test_generated_index_sorting_csv_escaping_and_defaults(self):
        (self.root / "scenarios").mkdir()
        scenarios = {
            "B2_status": {"title": 'Status, "please"\nMerci', "gen": "scripted",
                          "profile": "smoke", "transports": ["sim", "agentmail"],
                          "timeline": [{"client": {"persona": name}} for name in ("p_z", "p_a", "p_z")],
                          "expect": {"intent": "status_request", "signals": [{"kind": "fyi"}, {"kind": "new_info"}]},
                          "tags": ["status", "regression"], "status": "frozen", "owner": "fixture"},
            "A1_status": {"timeline": None, "expect": None, "transports": None, "tags": None},
        }
        _, report = self.check(validate.generate_indexes, scenarios, {"A": ["A1_status"], "B": ["B2_status"]})
        self.assert_clean(report)
        path = self.root / "scenarios/scenarios_index.csv"
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            rows = list(reader)
            self.assertEqual(reader.fieldnames, CSV_SCHEMA["files"]["scenarios/scenarios_index.csv"]["header"])
        self.assertEqual([row["scenario_id"] for row in rows], ["A1_status", "B2_status"])
        self.assertEqual(rows[0]["status"], "draft")
        self.assertEqual(rows[0]["client_ids"], "")
        self.assertEqual(rows[1], {
            "scenario_id": "B2_status", "series": "B", "title": 'Status, "please"\nMerci',
            "gen_mode": "scripted", "min_profile": "smoke", "transports": "sim|agentmail",
            "client_ids": "p_a|p_z", "expected_intent": "status_request",
            "expected_signal": "fyi|new_info", "tags": "status|regression",
            "status": "frozen", "owner": "fixture"})

    def test_relations_validate_ids_and_kinds(self):
        for kind in ("references", "supersedes", "duplicates", "amends", "answers",
                     "contradicts", "withdraws", "completes"):
            with self.subTest(kind=kind):
                self.write_csv("relations/relations_truth.csv", [{"relation_id": "rel_0001", "kind": kind}])
                _, report = self.check(validate.check_relations)
                self.assert_clean(report)
        self.write_csv("relations/relations_truth.csv", [{"relation_id": "bad", "kind": "bad"}])
        _, report = self.check(validate.check_relations)
        self.assert_error(report, "bad relation_id")
        self.assert_error(report, "bad kind")
        # 'unknown' is a linked_docs placeholder in the consumer, not a relation kind.
        self.write_csv("relations/relations_truth.csv", [{"relation_id": "rel_0001", "kind": "unknown"}])
        _, report = self.check(validate.check_relations)
        self.assert_error(report, "bad kind")
        (self.root / "relations/relations_truth.csv").unlink()
        _, report = self.check(validate.check_relations)
        self.assertTrue(report.ok())
        self.assertEqual(report.warnings, ["relations/relations_truth.csv missing"])


class MainTests(ContentFixture):
    """Exercise CLI orchestration against a minimal on-disk content pack."""

    def setUp(self):
        super().setUp()
        for relative in CSV_SCHEMA["files"]:
            self.write_csv(relative, [])
        self.write("content.json", json.dumps({
            "name": "fixture", "version": "1.0.0", "schema_version": "2.0",
            "dataset_revision": "fixture", "min_code_version": "0.1.0"}))
        # Reuse valid repository contracts without changing their source files.
        for filename in ("ingress_policy.yaml", "send_schedule.yaml", "recipient_policy.yaml"):
            self.write(f"email/{filename}", (REPO_ROOT / "email" / filename).read_text(encoding="utf-8"))
        self.seed_clients()
        self.seed_persona()
        self.seed_scenario()
        # This scenario only needs a template; no generation spec or attachment.
        del self.scenario["timeline"][0]["client"]["gen_spec"]
        del self.scenario["timeline"][0]["client"]["attach"]
        del self.scenario["expect"]["relations"]
        (self.root / "gen/specs/status.yaml").unlink()
        self.write_yaml("scenarios/A/A1_status.yaml", self.scenario)
        self.write_csv("attachments/manifest.csv", [])

    def run_main(self, *arguments):
        output = io.StringIO()
        with patch("sys.argv", ["validate.py", "--root", str(self.root), *arguments]), redirect_stdout(output):
            status = validate.main()
        return status, output.getvalue()

    def test_success_compiles_registry_without_rewriting_indexes(self):
        index = self.root / "scenarios/scenarios_index.csv"
        before = index.read_bytes()
        status, output = self.run_main()
        self.assertEqual(status, 0, output)
        self.assertIn("scenarios: 1 (A:1)", output)
        self.assertIn("errors: 0", output)
        registry = yaml.safe_load((self.root / "dist/registry.yaml").read_text())
        self.assertEqual(set(registry["clients"]), {"cedar"})
        self.assertEqual(index.read_bytes(), before)

    def test_cli_writes_requested_coverage_and_index(self):
        coverage_path = self.root / "coverage.json"
        status, output = self.run_main("--coverage-out", str(coverage_path), "--generate-indexes")
        self.assertEqual(status, 0, output)
        self.assertEqual(json.loads(coverage_path.read_text()), {})
        rows = validate.read_csv(self.root / "scenarios/scenarios_index.csv")
        self.assertEqual([row["scenario_id"] for row in rows], ["A1_status"])

    def test_validation_error_returns_one_and_prints_diagnostic(self):
        (self.root / "content.json").unlink()
        status, output = self.run_main()
        self.assertEqual(status, 1)
        self.assertIn("ERROR: content.json missing", output)

    def test_invalid_weight_returns_failure_after_writing_derived_outputs(self):
        self.write_csv("clients/client_doc_mix.csv", [dict(self.mix, weight="invalid"), self.mix])
        status, output = self.run_main("--coverage-out", str(self.root / "coverage.json"))
        self.assertEqual(status, 1)
        self.assertIn("bad weight 'invalid'", output)
        registry = yaml.safe_load((self.root / "dist/registry.yaml").read_text())
        self.assertEqual(registry["clients"]["cedar"]["usual_mix"], {"contract": 1.0})
        self.assertEqual(json.loads((self.root / "coverage.json").read_text()), {})

    def test_warnings_do_not_fail_and_output_is_capped_at_forty(self):
        self.write_csv("taxonomy/strata.csv", [
            {"class": "contract", "stratum": f"unused_{number}", "in_ground_truth": "true"}
            for number in range(42)])
        status, output = self.run_main()
        self.assertEqual(status, 0, output)
        self.assertIn("errors: 0, warnings: 42", output)
        self.assertEqual(sum(line.startswith("WARN:") for line in output.splitlines()), 40)
        self.assertIn("… and 2 more warnings", output)


if __name__ == "__main__":
    unittest.main()
