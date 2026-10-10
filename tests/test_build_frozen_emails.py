"""Unit tests for the frozen email generation layer (plan C-03).

Offline: the pure helpers and a fake generation client are exercised; no
network and no OpenRouter key are required.
"""
import hashlib
import json
import re
import unittest
from tools import build_frozen_emails as B


class PayloadGuardTest(unittest.TestCase):
    def test_allows_synthetic(self):
        self.assertIsNone(B.payload_guard(
            "Email dwhitcomb@harlowpryce.sandbox.invalid about HP-2026-0417; "
            "call +1-555-0142."))

    def test_blocks_real_url(self):
        self.assertIn("non-reserved", B.payload_guard("see https://acme-corp.com/x"))

    def test_blocks_real_phone(self):
        self.assertIn("phone", B.payload_guard("ring me on 212-555-9876"))

    def test_blocks_real_brand(self):
        self.assertIn("brand", B.payload_guard("our partners at Google will call"))


class InertnessLinterTest(unittest.TestCase):
    def test_rewrites_url_domain_phone(self):
        text, actions = B.inertness_linter(
            "Go to https://acme-corp.com/pay, or acme.io, or call 212-555-9876.")
        self.assertIn("example.sandbox.invalid", text)
        self.assertIn("acme.sandbox.invalid", text)
        self.assertIn("+1-555-0100", text)
        self.assertTrue(actions)

    def test_keeps_reserved(self):
        text, actions = B.inertness_linter(
            "Write to dwhitcomb@harlowpryce.sandbox.invalid or +1-555-0142.")
        self.assertIn("harlowpryce.sandbox.invalid", text)
        self.assertIn("+1-555-0142", text)
        self.assertEqual(actions, [])

    def test_rejects_real_brand(self):
        with self.assertRaises(ValueError):
            B.inertness_linter("We spoke to State Farm about the claim.")


class ConformanceTest(unittest.TestCase):
    SPEC = {
        "style": {"length": "10-40 words", "language": "en"},
        "constraints": {"must_include": ["urgency"]},
    }

    def test_passes_conforming(self):
        ok, why = B.conformance(self.SPEC, "Subject: now\n\nThis is urgent today.")
        self.assertTrue(ok, why)

    def test_fails_without_subject(self):
        ok, _ = B.conformance(self.SPEC, "urgent please act now")
        self.assertFalse(ok)

    def test_fails_wrong_length(self):
        ok, _ = B.conformance(self.SPEC, "Subject: x\n\n" + "word " * 200)
        self.assertFalse(ok)


class CanonicalTest(unittest.TestCase):
    def test_sorted_and_compact(self):
        raw = B.canonical({"b": 1, "a": 2})
        self.assertEqual(raw, b'{"a":2,"b":1}')
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         hashlib.sha256(b'{"a":2,"b":1}').hexdigest())


class StripFencesTest(unittest.TestCase):
    def test_drops_preamble_and_fences(self):
        out = B.strip_fences("Sure, here you go:\n```\nSubject: Hi\n\nBody\n```")
        self.assertTrue(out.startswith("Subject: Hi"))


class FreeModelsTest(unittest.TestCase):
    def test_excludes_retiring_and_appends_router(self):
        pool = {"free_pool": {
            "seed_candidates": ["a/x:free", "b/y:free"],
            "excluded_retiring": ["b/y:free"],
            "discovery": {"router_fallback": "openrouter/free"}}}
        self.assertEqual(B.free_models(pool), ["a/x:free", "openrouter/free"])


class GenerateOneTest(unittest.TestCase):
    """End to end against a real spec/binding with a fake client."""

    @classmethod
    def setUpClass(cls):
        specs = B.load_specs()
        bindings = B.scenario_bindings()
        sid = next(s for s in sorted(bindings) if s in specs)
        cls.spec = specs[sid]
        cls.binding = bindings[sid]
        cls.prow = B.personas().get(cls.binding["persona"], {})
        cls.sheet = B.behavior(cls.prow)

    def _draft(self):
        return B.render_template(
            self.binding["template"],
            B.message_context(self.prow, self.binding["vars"],
                              (self.binding["attachments"] or [None])[0],
                              self.binding.get("claimed_from", "")))

    def _conforming(self):
        must = (self.spec.get("constraints") or {}).get("must_include") or []
        style = self.spec.get("style") or {}
        lo = int((re.findall(r"\d+", str(style.get("length", "20-80"))) or
                  ["20"])[0])
        feat = " ".join(m.replace("_", " ") for m in must)
        filler = " ".join("detail" for _ in range(max(0, int(lo * 0.7))))
        return f"Subject: update\n\n{feat} {filler}\n"

    def test_generated_record_is_free_tier(self):
        conforming = self._conforming()
        rec = B.generate_one(self.spec, self.binding, self.prow, self.sheet,
                             lambda m, p: conforming, ["m/x:free"], attempts=2,
                             sleep=0, log=lambda *a: None)
        self.assertEqual(rec["manifest"]["tier"], "free")
        self.assertFalse(rec["manifest"]["template_fallback"])
        self.assertTrue(rec["body"].startswith("Subject:"))
        self.assertEqual(rec["spec_id"], self.spec["id"])

    def test_all_failures_fall_back_to_scripted(self):
        def boom(model, prompt):
            raise B.Retryable("nope")
        rec = B.generate_one(self.spec, self.binding, self.prow, self.sheet,
                             boom, ["m/x:free"], attempts=2, sleep=0,
                             log=lambda *a: None)
        self.assertTrue(rec["manifest"]["template_fallback"])
        self.assertEqual(rec["manifest"]["tier"], "scripted")
        self.assertEqual(rec["manifest"]["model_id"], "template")

    def test_every_prompt_passes_the_guard(self):
        specs = B.load_specs()
        prows = B.personas()
        for sid, binding in B.scenario_bindings().items():
            spec = specs.get(sid)
            if not spec:
                continue
            prow = prows.get(binding["persona"], {})
            draft = B.render_template(
                binding["template"],
                B.message_context(prow, binding["vars"],
                                  (binding["attachments"] or [None])[0],
                                  binding.get("claimed_from", "")))
            prompt = B.build_prompt(spec, binding, prow, B.behavior(prow), draft)
            self.assertIsNone(B.payload_guard(prompt), f"{sid}: guard tripped")


class RepoCheckTest(unittest.TestCase):
    def test_index_and_jsonl_are_consistent(self):
        # Multi-test runners may run this before generation; treat absence as OK.
        records, rows = B.load_existing()
        if not rows:
            self.skipTest("no frozen emails yet")
        for r in rows:
            rec = records.get(r["email_id"])
            self.assertIsNotNone(rec, r["email_id"])
            self.assertEqual(
                hashlib.sha256(B.canonical(rec)).hexdigest(), r["sha256"],
                r["email_id"])


if __name__ == "__main__":
    unittest.main()
