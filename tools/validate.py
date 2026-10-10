#!/usr/bin/env python3
"""Content CI validator for mailroom-sandbox-content.

Checks (addendum v2 §13.4, workstream C11):
  1. content.json shape and semver
  2. CSV headers / row rules per schemas/content_files.json
  3. Scenario YAMLs against scenario.v2 required fields + enums
  4. Cross-references: persona_ids, client_ids, spec_ids, attachment files
  5. Leak scan: no real brands in client names, no non-555 phone numbers,
     no real URLs, no pasted dataset text
  6. Registry compile excludes adversary/ (lookalikes, impostors)
  7. emails_index.csv <-> frozen JSONL sha256 consistency
  8. Attachment manifest sha256 / doc_id verification for local files
  9. Coverage report (strata x clients x scenarios x attachments)

Usage:
  python3 tools/validate.py [--root DIR] [--generate-indexes] [--coverage-out PATH]

Exit 0 when no ERRORs, 1 on ERRORs, 2 on an internal failure (one
`ERROR internal:` line on stderr, never a traceback). WARNs never fail the build.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------- constants

INTENTS = {
    "status_request", "missing_document_followup", "document_submission",
    "correction_or_amendment", "duplicate_submission", "complaint",
    "urgent_deadline", "general_question", "unrelated", "auto_reply",
    "bounce", "spam_or_phishing", "possible_prompt_injection",
    "legal_notice", "privacy_request", "payment_or_identity_change",
    "conflicting_instructions", "retraction_or_withdrawal",
    "disclosure_request",
}
SIGNAL_KINDS = {
    "new_info", "doc_relation", "status_request", "missing_doc",
    "correction", "complaint", "urgent", "possible_attack", "fyi",
    "legal_notice", "privacy_request", "payment_change",
}
ATTACK_CLASSES = {
    "impersonation", "payment_fraud", "credential_phish", "injection",
    "exfiltration", "malicious_attachment", "other",
}
TRUST_LEVELS = {"verified", "unverified", "suspicious", "hostile"}
RELATION_KINDS = {
    "references", "supersedes", "duplicates", "amends", "answers",
    "contradicts", "withdraws", "completes",
}
# K-02 optional size cap: an oversized scenario or template file is a WARN, not
# an ERROR (plan item K-02, "optional cap (e.g. 1 MB) ... as a WARN first"). The
# threshold is far above the largest real file; it catches a runaway generator
# or an accidental blob. Promote to ERROR once the pack has settled.
MAX_CONTENT_BYTES = 1_000_000
BOSS_ACTIONS = {
    "ack_signal", "dismiss_signal", "link_documents", "annotate_document",
    "raise_priority", "request_human_review", "task_correspondent",
    "approve_outbound", "hold_attachments", "quarantine_attachments",
    "release_attachments", "recommend_callback",
}
INVARIANTS = {
    "audit_chain_ok", "no_stuck_docs", "fast_path_two_calls", "comms_offpath",
}
PROFILES = {"smoke", "demo", "prod_like", "chaos", "coverage"}
GEN_MODES = {"scripted", "frozen", "live", "loop"}
TRANSPORTS = {"sim", "agentmail", "gmail"}
PRIORITIES = {"low", "normal", "high", "critical"}
TIERS = {"free", "paid", "scripted", "template", "handwritten"}
AUTH_RESULTS = {"pass", "fail", "none", "softfail", "temperror", "permerror"}

# Variables the sandbox runner supplies to every inbound template (CONTENT_SPEC
# §4.1). CONTACT_CONTEXT comes from the persona's registered contact, so
# adversary personas (no contact) must pass those through ``vars``.
CONTACT_CONTEXT = {"sender_name", "sender_first_name", "sender_title"}
STANDARD_TEMPLATE_CONTEXT = CONTACT_CONTEXT | {
    "sender_email", "client_display_name", "attachment_name", "attachment_names",
}

ID_PATTERNS = {
    "client_id": re.compile(r"^[a-z0-9_]+$"),
    "persona_id": re.compile(r"^p_[a-z0-9_]+$"),
    "contact_id": re.compile(r"^[a-z0-9_]+$"),
    "scenario": re.compile(r"^[A-HST][0-9]+_[a-z0-9_]+$"),
    "spec_id": re.compile(r"^gen_[a-zA-Z0-9_]+$"),
    "email_id": re.compile(r"^em_[A-Z]_[0-9]+$"),
    "attachment_id": re.compile(r"^att_[0-9]+$"),
    "relation_id": re.compile(r"^rel_[0-9]+$"),
}

PHONE_RE = re.compile(
    # Lookarounds keep hex digests (sha256 / prompt_hash) from matching:
    # a 10+ digit run embedded in [0-9a-f] is a digest, not a phone number.
    r"(?<![0-9a-fA-F])\+?1?[-.\s]?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?"
    r"[0-9]{4}(?![0-9a-fA-F])"
)
URL_RE = re.compile(r"https?://([A-Za-z0-9.-]+)(?::[0-9]+)?(?:[/?#][^\s\"']*)?")
RESERVED_URL_HOSTS = (".sandbox.invalid", ".example", ".test", ".localhost",
                      "localhost")

# Well-known real brands / firms a fictional client must not collide with.
BRAND_BLOCKLIST = [
    "american family", "amfam", "state farm", "allstate", "progressive",
    "geico", "usaa", "travelers", "liberty mutual", "nationwide",
    "farmers insurance", "hartford", "chubb", "aig",
    "jpmorgan", "chase bank", "wells fargo", "bank of america", "citibank",
    "goldman sachs", "morgan stanley", "u.s. bank", "us bank", "pnc",
    "capital one", "american express", "visa", "mastercard",
    "google", "alphabet inc", "microsoft", "apple inc", "amazon",
    "meta platforms", "facebook", "tesla", "nvidia", "intel",
    "walmart", "costco", "home depot", "lowes", "best buy",
    "fedex", "dhl", "delta air", "united airlines",
    "american airlines", "southwest airlines",
    "marriott", "hilton", "hyatt", "starbucks", "mcdonald",
    "coca-cola", "pepsi", "nike", "disney", "netflix",
]

# Byte markers that must never appear in a file flagged inert=true.
INERT_FORBIDDEN = [
    b"/JavaScript", b"/JS ", b"/Launch", b"/Win ", b"/Mac ",
    b"MZ\x90\x00", b"\x7fELF",
]


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def info(self, msg: str) -> None:
        self.infos.append(msg)

    def ok(self) -> bool:
        return not self.errors


def read_csv_strict(path: Path, rep: Report | None = None, *,
                    label: str | None = None, want: list[str] | None = None,
                    key: str | None = None) -> list[dict]:
    """The one CSV reader the validator uses. It never raises on file content.

    Faults are appended to ``rep`` as ERRORs (``rep=None`` discards them, for
    re-reads of a file another check already reports):
      - NUL byte or bytes that are not UTF-8: the whole file is dropped
      - UTF-8 BOM: accepted and stripped
      - duplicate header name, or header != ``want``: the whole file is dropped
      - row whose cell count differs from the header (short or extra cells):
        that row is dropped
      - repeated value of ``key``: the later row is dropped
    Blank lines are skipped. Line numbers are the csv reader's line count.
    """
    rep = rep if rep is not None else Report()
    name = label or path.name
    try:
        data = path.read_bytes()
    except OSError as e:
        rep.error(f"{name}: unreadable: {e}")
        return []
    if b"\x00" in data:
        line = data[:data.index(b"\x00")].count(b"\n") + 1
        rep.error(f"{name} line {line}: NUL byte (binary or corrupt data)")
        return []
    try:
        text = data.decode("utf-8-sig")  # a leading BOM is stripped
    except UnicodeDecodeError as e:
        rep.error(f"{name}: not UTF-8 (byte {e.start}): {e.reason}")
        return []
    reader = csv.reader(io.StringIO(text, newline=""))
    rows: list[dict] = []
    try:
        header = next((r for r in reader if r), None) or []
        dups = sorted({h for h in header if header.count(h) > 1})
        if dups:
            rep.error(f"{name}: duplicate header name(s) {dups}")
            return []
        if want is not None and header != want:
            rep.error(f"{name}: header mismatch.\n  want {want}\n  got  {header}")
            return []
        key_at = header.index(key) if key is not None and key in header else None
        first_line: dict[str, int] = {}
        for record in reader:
            line = reader.line_num
            if not record:
                continue
            if len(record) != len(header):
                rep.error(f"{name} line {line}: row has {len(record)} cells, "
                          f"header has {len(header)}")
                continue
            if key_at is not None:
                value = record[key_at]
                if value in first_line:
                    rep.error(f"{name} line {line}: duplicate {key} {value!r} "
                              f"(first at line {first_line[value]})")
                    continue
                first_line[value] = line
            rows.append(dict(zip(header, record)))
    except csv.Error as e:
        rep.error(f"{name} line {reader.line_num}: malformed CSV: {e}")
        return []
    return rows


def read_csv(path: Path) -> list[dict]:
    """Strict read with errors discarded: for a file another check reports."""
    return read_csv_strict(path)


def load_yaml(path: Path):
    import yaml
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_json_file(path: Path, rel: str, rep: Report):
    """Parse one JSON file. Unreadable or invalid input is an ERROR and None."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        rep.error(f"{rel} is unreadable: {e}")
    except ValueError as e:  # JSONDecodeError and UnicodeDecodeError
        rep.error(f"{rel} is not valid JSON: {e}")
    return None


def read_text_or_error(path: Path, rel: str, rep: Report) -> str | None:
    """Read one UTF-8 text file. Unreadable input is an ERROR and None."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, ValueError) as e:
        rep.error(f"{rel} is unreadable: {e}")
    return None


def content_files(root: Path) -> defaultdict:
    """Header declarations from schemas/content_files.json, keyed by path.
    A missing or malformed index gives no declarations; the per-file checks
    then report the missing header, and check_content_files_index reports why."""
    try:
        files = json.loads((root / "schemas" / "content_files.json")
                           .read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError, TypeError):
        files = {}
    return defaultdict(dict, files if isinstance(files, dict) else {})


def check_content_files_index(root: Path, rep: Report) -> None:
    """Report a missing or malformed content file index and its files mapping."""
    rel = "schemas/content_files.json"
    p = root / rel
    if not p.exists():
        rep.error(f"{rel} missing")
        return
    data = load_json_file(p, rel, rep)
    if data is not None and not (isinstance(data, dict)
                                 and isinstance(data.get("files"), dict)):
        rep.error(f"{rel}: top level must be a mapping with a 'files' mapping")


def parse_weight(raw) -> float | None:
    """Parse a mix weight without raising; None means unparseable.
    check_clients reports the bad row; downstream users skip it."""
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- checks

def check_ops_contracts(root: Path, rep: Report) -> None:
    """Validate the metered-operations contracts: ingress policy and
    send schedule. These are the anti-doom-loop, anti-overload configs."""
    specs = {
        "email/ingress_policy.yaml": "mailroom.ingress_policy/v1",
        "email/send_schedule.yaml": "mailroom.send_schedule/v1",
        "email/recipient_policy.yaml": "mailroom.recipient_policy/v1",
    }
    for rel, want_schema in specs.items():
        p = root / rel
        if not p.exists():
            rep.error(f"{rel} missing")
            continue
        try:
            data = load_yaml(p)
        except Exception as e:  # noqa: BLE001 - surface any YAML failure
            rep.error(f"{rel} is not valid YAML: {e}")
            continue
        if not isinstance(data, dict):
            rep.error(f"{rel}: top level must be a mapping")
            continue
        if data.get("schema") != want_schema:
            rep.error(f"{rel}: schema={data.get('schema')!r}, want {want_schema!r}")

    # Recipient policy shape ------------------------------------------
    p = root / "email/recipient_policy.yaml"
    if p.exists():
        try:
            rp = load_yaml(p)
        except Exception:  # noqa: BLE001 - already reported above
            rp = None
        if isinstance(rp, dict):
            for profile in ("closed", "egress"):
                prof = rp.get(profile) or {}
                recips = prof.get("allowed_recipients")
                if not isinstance(recips, list) or not recips:
                    rep.error(f"recipient_policy: {profile}.allowed_recipients "
                              f"must be a non-empty list")
                elif not all(isinstance(r, str) for r in recips):
                    rep.error(f"recipient_policy: {profile}.allowed_recipients "
                              f"entries must be strings")
            ext = rp.get("external_inbound") or {}
            if not isinstance(ext.get("allowed"), bool):
                rep.error("recipient_policy: external_inbound.allowed must be "
                          "a boolean")

    # Ingress policy shape -------------------------------------------
    p = root / "email/ingress_policy.yaml"
    if p.exists():
        try:
            pol = load_yaml(p)
        except Exception:  # noqa: BLE001 - already reported above
            pol = None
        if isinstance(pol, dict):
            for src in ("documents", "emails", "external_correspondence"):
                s = (pol.get("sources") or {}).get(src) or {}
                rate = s.get("rate") or {}
                for k in ("max_items_per_minute", "burst"):
                    v = rate.get(k)
                    if not isinstance(v, int) or v <= 0:
                        rep.error(f"ingress_policy: sources.{src}.rate.{k} "
                                  f"must be a positive int")
                if s.get("on_queue_full") not in ("shed_to_pending",):
                    rep.error(f"ingress_policy: sources.{src}.on_queue_full "
                              f"must be shed_to_pending (never silent drop)")
            inbox = pol.get("correspondent_inbox") or {}
            for k in ("max_admissions_per_hour", "max_concurrent_open_threads"):
                v = inbox.get(k)
                if not isinstance(v, int) or v <= 0:
                    rep.error(f"ingress_policy: correspondent_inbox.{k} "
                              f"must be a positive int")
            reserve = inbox.get("priority_reserve_per_hour", 0)
            cap = inbox.get("max_admissions_per_hour", 0)
            if not isinstance(reserve, int) or reserve < 0:
                rep.error("ingress_policy: correspondent_inbox."
                          "priority_reserve_per_hour must be a non-negative int")
            elif isinstance(cap, int) and reserve >= cap:
                rep.error("ingress_policy: priority_reserve_per_hour must be "
                          "less than max_admissions_per_hour")
            qs = pol.get("queues") or {}
            for qn, q in qs.items():
                if not isinstance(q, dict):
                    continue
                if q.get("depth_max", 1) <= q.get("depth_warn", 0):
                    rep.error(f"ingress_policy: queues.{qn}.depth_max must "
                              f"exceed depth_warn")
            bp = pol.get("backpressure") or {}
            if bp.get("never_silently_drop") is not True:
                rep.error("ingress_policy: backpressure.never_silently_drop "
                          "must be true")

    # Send schedule shape ---------------------------------------------
    p = root / "email/send_schedule.yaml"
    if p.exists():
        try:
            sch = load_yaml(p)
        except Exception:  # noqa: BLE001 - already reported above
            sch = None
        if isinstance(sch, dict):
            if "production" in (sch.get("active_profiles") or []):
                rep.error("send_schedule: active_profiles must never include "
                          "production")
            models = sch.get("models") or {}
            if models.get("tier") != "free_only":
                rep.error("send_schedule: models.tier must be free_only")
            if models.get("paid_tier_use") != "forbidden":
                rep.error("send_schedule: models.paid_tier_use must be forbidden")
            total_window = 0
            for w in sch.get("schedule") or []:
                cron = str(w.get("cron", ""))
                if len(cron.split()) != 5:
                    rep.error(f"send_schedule: window {w.get('name')!r} cron "
                              f"must have 5 fields")
                v = w.get("max_sends_per_window")
                if not isinstance(v, int) or v <= 0:
                    rep.error(f"send_schedule: window {w.get('name')!r} "
                              f"max_sends_per_window must be a positive int")
                else:
                    total_window += v
            # hourly windows fire ~1-3x/hour each; window caps must fit the cap
            cap = (sch.get("caps") or {}).get("max_sends_per_hour_total")
            if isinstance(cap, int) and total_window * 3 < cap:
                rep.warn("send_schedule: window caps look far below the hourly "
                         "cap; check the arithmetic")
            doom = sch.get("doom_loop_prevention") or {}
            ks = doom.get("kill_switch") or {}
            if not ks.get("env_var") or not ks.get("file_flag"):
                rep.error("send_schedule: doom_loop_prevention.kill_switch "
                          "needs both env_var and file_flag")
            cb = doom.get("circuit_breaker") or {}
            if cb.get("auto_reset") is not False:
                rep.error("send_schedule: circuit_breaker.auto_reset must be "
                          "false (human reset only)")
            if not isinstance(doom.get("max_reply_depth_per_thread"), int):
                rep.error("send_schedule: max_reply_depth_per_thread must be set")
            if doom.get("no_auto_reply_to_auto_reply") is not True:
                rep.error("send_schedule: no_auto_reply_to_auto_reply must be true")
            idem = doom.get("idempotency") or {}
            key = str(idem.get("key", ""))
            if "outbound_message_id" not in key:
                rep.error("send_schedule: doom_loop_prevention.idempotency.key "
                          "must include the outbound message identity so "
                          "distinct approved sends are never conflated")
            if doom.get("sends_may_not_enqueue_sends") is not True:
                rep.error("send_schedule: sends_may_not_enqueue_sends must be true")


def check_content_json(root: Path, rep: Report) -> dict:
    """Report invalid pack metadata and return its mapping, or {} if unreadable."""
    p = root / "content.json"
    if not p.exists():
        rep.error("content.json missing")
        return {}
    data = load_json_file(p, "content.json", rep)
    if data is None:
        return {}
    if not isinstance(data, dict):
        rep.error("content.json: top level must be a mapping")
        return {}
    for key in ("name", "version", "schema_version",
                "dataset_revision", "min_code_version"):
        if key not in data:
            rep.error(f"content.json missing key: {key}")
    if "version" in data and not re.match(
            r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$", str(data["version"])):
        rep.error(f"content.json version is not semver: {data['version']}")
    return data


def check_csv_file(root: Path, rel: str, spec: dict, rep: Report,
                   key: str | None = None) -> list[dict]:
    """Read rows using the declared header and optional unique key, reporting errors."""
    p = root / rel
    if not p.exists():
        rep.error(f"missing required file: {rel}")
        return []
    if spec.get("header") is None:
        rep.error(f"{rel}: no header declared in schemas/content_files.json")
        return []
    return read_csv_strict(p, rep, label=rel, want=spec["header"], key=key)


def check_id(value: str, kind: str, where: str, rep: Report) -> None:
    """Record an error when value does not match the requested ID kind."""
    pat = ID_PATTERNS[kind]
    if not pat.match(value if isinstance(value, str) else ""):
        rep.error(f"{where}: bad {kind} id: {value!r}")


def check_clients(root: Path, rep: Report) -> tuple[dict, dict, dict, dict]:
    """Validate client data and return clients, contacts, domain rows, and mix rows."""
    spec = content_files(root)
    clients = {r["client_id"]: r for r in
               check_csv_file(root, "clients/clients.csv",
                              spec["clients/clients.csv"], rep, key="client_id")}
    contacts = {r["contact_id"]: r for r in
                check_csv_file(root, "clients/client_contacts.csv",
                               spec["clients/client_contacts.csv"], rep,
                               key="contact_id")}
    domains = check_csv_file(root, "clients/client_domains.csv",
                             spec["clients/client_domains.csv"], rep)
    mixes = check_csv_file(root, "clients/client_doc_mix.csv",
                           spec["clients/client_doc_mix.csv"], rep)

    for cid, c in clients.items():
        check_id(cid, "client_id", "clients.csv", rep)
        dom = c.get("primary_domain", "")
        if not dom.endswith(".sandbox.invalid"):
            rep.error(f"clients.csv {cid}: primary_domain must end with "
                      f".sandbox.invalid, got {dom!r}")
        phone = c.get("callback_phone", "")
        if not re.fullmatch(r"\+1-555-01\d\d", phone or ""):
            rep.error(f"clients.csv {cid}: callback_phone must match "
                      f"+1-555-01xx, got {phone!r}")
        # fictional-name collision check (ERROR level for client names)
        blob = f"{c.get('display_name','')} {dom}".lower()
        for brand in BRAND_BLOCKLIST:
            if brand in blob:
                rep.error(f"clients.csv {cid}: fictional name collides with "
                          f"real brand {brand!r}")

    for co_id, co in contacts.items():
        check_id(co_id, "contact_id", "client_contacts.csv", rep)
        if co["client_id"] not in clients:
            rep.error(f"client_contacts.csv {co_id}: unknown client_id "
                      f"{co['client_id']!r}")
        email = co.get("email", "")
        if email and not email.endswith(".sandbox.invalid"):
            rep.error(f"client_contacts.csv {co_id}: contact email must be "
                      f"*.sandbox.invalid, got {email!r}")

    seen_domains: dict[str, str] = {}
    for d in domains:
        dom = d["domain"]
        if not dom.endswith(".sandbox.invalid"):
            rep.error(f"client_domains.csv: {dom!r} must end with "
                      f".sandbox.invalid")
        if d["client_id"] not in clients:
            rep.error(f"client_domains.csv {dom}: unknown client_id")
        if dom in seen_domains:
            rep.error(f"client_domains.csv: duplicate domain {dom}")
        seen_domains[dom] = d["client_id"]

    # mix weights per client sum to 1.0
    weights: dict[str, float] = {}
    for m in mixes:
        if m["client_id"] not in clients:
            rep.error(f"client_doc_mix.csv: unknown client_id "
                      f"{m['client_id']!r}")
            continue
        try:
            w = parse_weight(m["weight"])
            if w is None:
                raise ValueError(m["weight"])
            weights[m["client_id"]] = weights.get(m["client_id"], 0.0) + w
        except ValueError:
            rep.error(f"client_doc_mix.csv: bad weight {m['weight']!r}")
    for cid, total in weights.items():
        if abs(total - 1.0) > 0.01:
            rep.error(f"client_doc_mix.csv {cid}: weights sum to {total:.3f}, "
                      f"want 1.0")
    return clients, contacts, domains, mixes


def check_personas(root: Path, clients: dict, contacts: dict,
                   rep: Report) -> dict:
    """Validate persona references and behavior files; return rows keyed by persona ID."""
    spec = content_files(root)
    rows = check_csv_file(root, "personas/personas.csv",
                          spec["personas/personas.csv"], rep)
    personas = {}
    for r in rows:
        pid = r["persona_id"]
        check_id(pid, "persona_id", "personas.csv", rep)
        if pid in personas:
            rep.error(f"personas.csv: duplicate persona_id {pid}")
        personas[pid] = r
        if r["client_id"] not in clients and r["client_id"] != "_adversary":
            rep.error(f"personas.csv {pid}: unknown client_id "
                      f"{r['client_id']!r}")
        if r["contact_id"] not in contacts and r["contact_id"] != "_none":
            rep.error(f"personas.csv {pid}: unknown contact_id "
                      f"{r['contact_id']!r}")
        bf = root / "personas" / r["behavior_file"]
        if not bf.exists():
            rep.error(f"personas.csv {pid}: behavior file missing: "
                      f"{r['behavior_file']}")
            continue
        try:
            beh = load_yaml(bf)
        except Exception as e:  # noqa: BLE001
            rep.error(f"personas/{r['behavior_file']}: YAML error: {e}")
            continue
        if not isinstance(beh, dict) or beh.get("persona_id") != pid:
            rep.error(f"personas/{r['behavior_file']}: persona_id mismatch")
        if "escalation" not in beh or "attachment_habits" not in beh:
            rep.error(f"personas/{r['behavior_file']}: missing escalation or "
                      f"attachment_habits")
    return personas


def load_strata(root: Path, rep: Report | None = None
                ) -> tuple[dict, set[tuple[str, str]]]:
    """(strata rows keyed by (class, stratum), off-taxonomy (class, kind) pairs).
    Pass ``rep`` from the one check that reports these files; None discards."""
    strata: dict[tuple[str, str], dict] = {}
    p = root / "taxonomy" / "strata.csv"
    if p.exists():
        for r in read_csv_strict(p, rep, label="taxonomy/strata.csv"):
            strata[(r.get("class"), r.get("stratum"))] = r
    off: set[tuple[str, str]] = set()
    p = root / "taxonomy" / "offtaxonomy.csv"
    if p.exists():
        off = {("off_taxonomy", r.get("kind"))
               for r in read_csv_strict(p, rep, label="taxonomy/offtaxonomy.csv")}
    return strata, off


def template_variables(root: Path, rep: Report) -> dict[str, set[str]] | None:
    """Undeclared variables per inbound template (None: jinja2 missing)."""
    try:
        import jinja2
        import jinja2.meta
    except ImportError:
        rep.warn("jinja2 not installed; skipping template parse and variable "
                 "checks (pip install jinja2)")
        return None
    env = jinja2.Environment()
    out: dict[str, set[str]] = {}
    tdir = root / "gen" / "templates"
    for sub in ("", "replies"):
        for tf in sorted((tdir / sub).glob("*.j2")):
            rel = tf.relative_to(root)
            if tf.stat().st_size > MAX_CONTENT_BYTES:
                rep.warn(f"{rel}: {tf.stat().st_size} bytes exceeds the "
                         f"{MAX_CONTENT_BYTES}-byte cap (WARN; plan K-02)")
            try:
                ast_ = env.parse(tf.read_text(encoding="utf-8"))
            except jinja2.TemplateSyntaxError as e:
                rep.error(f"{rel}: template syntax error: {e}")
                continue
            if not sub:
                out[tf.stem] = set(jinja2.meta.find_undeclared_variables(ast_))
                first = [ln for ln in tf.read_text(encoding="utf-8").splitlines()
                         if ln.strip() and not ln.lstrip().startswith("{#")]
                if not first or not first[0].startswith("Subject:"):
                    rep.error(f"{rel}: first rendered line must be 'Subject: ...'")
    return out


def check_scenarios(root: Path, personas: dict, domains_by_client: dict,
                    rep: Report) -> tuple[dict, dict]:
    """Validate scenario schemas and references; return scenarios and names by series."""
    scenarios: dict[str, dict] = {}
    by_series: dict[str, list[str]] = {}
    # Strict schema validation: manual checks below cover cross-references,
    # but field shapes/formats are the schema's job.
    schema_validator = None
    try:
        from jsonschema import Draft202012Validator
        schema_validator = Draft202012Validator(json.loads(
            (root / "schemas" / "scenario.v2.json").read_text(encoding="utf-8")))
    except ImportError:
        rep.warn("jsonschema not installed; skipping strict scenario schema "
                 "validation (pip install jsonschema)")
    except Exception as e:  # noqa: BLE001 - bad schema file is a real error
        rep.error(f"schemas/scenario.v2.json unreadable: {e}")
    spec_personas: dict[str, str] = {}
    for spec_file in sorted((root / "gen" / "specs").glob("*.yaml")):
        try:
            spec = load_yaml(spec_file)
            spec_personas[spec["id"]] = spec.get("persona", "")
        except Exception:  # noqa: BLE001 - reported by check_gen_specs
            pass
    attach_files = set()
    man = root / "attachments" / "manifest.csv"
    if man.exists():
        # check_attachments reports manifest faults; this read only collects names
        attach_files = {r.get("file") for r in read_csv(man)}
    template_vars = template_variables(root, rep)
    templates = {p.stem for p in (root / "gen" / "templates").glob("*.j2")}
    replies = {p.stem for p in (root / "gen" / "templates" / "replies").glob("*.j2")}
    strata, offtax = load_strata(root, rep)
    awaiting_specs: list[str] = []

    scen_dir = root / "scenarios"
    for series_dir in sorted(scen_dir.iterdir()):
        if not series_dir.is_dir():
            continue
        series = series_dir.name
        for yf in sorted(series_dir.glob("*.yaml")):
            stem = yf.stem
            if yf.stat().st_size > MAX_CONTENT_BYTES:
                rep.warn(f"scenarios/{series}/{yf.name}: {yf.stat().st_size} "
                         f"bytes exceeds the {MAX_CONTENT_BYTES}-byte cap "
                         f"(WARN; plan K-02)")
            try:
                s = load_yaml(yf)
            except Exception as e:  # noqa: BLE001
                rep.error(f"scenarios/{series}/{yf.name}: YAML error: {e}")
                continue
            if not isinstance(s, dict):
                rep.error(f"scenarios/{series}/{yf.name}: top level must be "
                          f"a mapping")
                continue
            if schema_validator is not None:
                for error in schema_validator.iter_errors(s):
                    path = ".".join(str(p) for p in error.absolute_path)
                    rep.error(f"scenarios/{series}/{yf.name}: schema violation "
                              f"at {path or '<root>'}: {error.message[:160]}")
            name = s.get("name", "")
            if stem != name:
                rep.error(f"scenarios/{series}/{yf.name}: filename stem "
                          f"{stem!r} != name {name!r}")
            check_id(name, "scenario", f"scenarios/{series}/{yf.name}", rep)
            if not name.startswith(series):
                rep.error(f"scenarios/{series}/{yf.name}: name {name!r} does "
                          f"not start with series {series!r}")
            if name in scenarios:
                rep.error(f"duplicate scenario name: {name}")
            scenarios[name] = s
            by_series.setdefault(series, []).append(name)

            for field in ("seed", "profile", "gen", "transports",
                          "timeline", "expect"):
                if field not in s:
                    rep.error(f"{name}: missing required field {field!r}")
            if s.get("profile") not in PROFILES:
                rep.error(f"{name}: bad profile {s.get('profile')!r}")
            if s.get("gen") not in GEN_MODES:
                rep.error(f"{name}: bad gen {s.get('gen')!r}")
            for t in s.get("transports", []):
                if t not in TRANSPORTS:
                    rep.error(f"{name}: bad transport {t!r}")
            # identity-dependent scenarios must not claim the gmail leg
            if series == "E" and "gmail" in s.get("transports", []):
                rep.warn(f"{name}: E-series (identity-dependent) lists the "
                         f"gmail leg; auth is genuine there (see §3.8)")

            tl = s.get("timeline", [])
            if not isinstance(tl, list) or not tl:
                rep.error(f"{name}: timeline must be a non-empty list")
                continue
            doc_refs: set[str] = set()
            msg_refs: set[str] = set()
            pinned_here: set[str] = set()

            def bind_ref(ref, kind, where):
                if not ref:
                    return
                if ref in doc_refs or ref in msg_refs:
                    rep.error(f"{where}: duplicate ref {ref!r}")
                (doc_refs if kind == "doc" else msg_refs).add(ref)

            def check_doc(spec, where, allow_same_as):
                if not isinstance(spec, dict):
                    rep.error(f"{where}: must be a mapping")
                    return
                if spec.get("file"):
                    pinned_here.add(spec["file"])
                    if spec["file"] not in attach_files:
                        rep.error(f"{where}: attachment file {spec['file']!r} "
                                  f"not in attachments/manifest.csv")
                cls, stratum = spec.get("class"), spec.get("stratum")
                if cls and stratum:
                    if (cls, stratum) in offtax:
                        pass
                    elif (cls, stratum) not in strata:
                        rep.error(f"{where}: unknown stratum {cls}/{stratum} "
                                  f"(taxonomy/strata.csv, offtaxonomy.csv)")
                    elif strata[(cls, stratum)].get("in_ground_truth") != "true":
                        rep.error(f"{where}: {cls}/{stratum} has no dataset "
                                  f"rows (catalog_only); it cannot be drawn")
                same = spec.get("same_as")
                if same:
                    if not allow_same_as:
                        rep.error(f"{where}: same_as is only valid on attachments")
                    elif same not in doc_refs:
                        rep.error(f"{where}: same_as {same!r} is not an "
                                  f"earlier document ref")
                bind_ref(spec.get("ref"), "doc", where)

            for i, ev in enumerate(tl):
                where = f"{name} timeline[{i}]"
                if not isinstance(ev, dict) or "at" not in ev:
                    rep.error(f"{where}: event needs 'at'")
                    continue
                if not re.fullmatch(r"[0-9]{2}:[0-9]{2}(:[0-9]{2})?",
                                    str(ev["at"])):
                    rep.error(f"{where}: bad at {ev['at']!r}")
                if isinstance(ev.get("ingress"), dict):
                    check_doc(ev["ingress"], f"{where} ingress", False)
                cl = ev.get("client")
                if not isinstance(cl, dict):
                    continue
                pid = cl.get("persona", "")
                if pid not in personas:
                    rep.error(f"{where}: unknown persona {pid!r}")
                gs = cl.get("gen_spec")
                if gs and gs not in spec_personas:
                    rep.error(f"{where}: unknown gen_spec {gs!r}")
                elif gs and spec_personas[gs] != pid:
                    rep.warn(f"{where}: gen_spec {gs} is written for persona "
                             f"{spec_personas[gs]!r}, event uses {pid!r}")
                tp = cl.get("template")
                if not tp:
                    rep.error(f"{where}: client message needs a template "
                              f"(scripted body and generation fallback)")
                elif tp not in templates:
                    rep.error(f"{where}: unknown template {tp!r}")
                elif template_vars is not None and tp in template_vars:
                    # (a template that failed to parse is already an error)
                    persona = personas.get(pid) or {}
                    standard = set(STANDARD_TEMPLATE_CONTEXT)
                    if persona.get("contact_id") in ("", "_none", None):
                        standard -= CONTACT_CONTEXT
                    supplied = standard | set((cl.get("vars") or {}).keys())
                    missing = sorted(template_vars[tp] - supplied)
                    if missing:
                        rep.error(f"{where}: template {tp!r} needs vars "
                                  f"{missing} (not supplied by vars or the "
                                  f"standard context)")
                cf = cl.get("claimed_from", "")
                if cf and not cf.endswith(".sandbox.invalid"):
                    rep.error(f"{where}: claimed_from must be "
                              f"*.sandbox.invalid, got {cf!r}")
                auth = cl.get("auth", {}) or {}
                for k, v in auth.items():
                    if v not in AUTH_RESULTS:
                        rep.error(f"{where}: bad auth {k}={v!r}")
                rt = cl.get("reply_to")
                if rt and rt not in msg_refs:
                    rep.error(f"{where}: reply_to {rt!r} is not an earlier "
                              f"message ref")
                for j, a in enumerate(cl.get("attach", []) or []):
                    check_doc(a, f"{where} attach[{j}]", True)
                bind_ref(cl.get("ref"), "msg", where)

            if s.get("gen") in ("frozen", "live", "loop") and not any(
                    isinstance(ev, dict) and (ev.get("client") or {}).get("gen_spec")
                    for ev in tl):
                awaiting_specs.append(name)

            exp = s.get("expect", {})
            if exp.get("intent") not in INTENTS:
                rep.error(f"{name}: bad expect.intent "
                          f"{exp.get('intent')!r}")
            for i, sig in enumerate(exp.get("signals", []) or []):
                if not isinstance(sig, dict):
                    rep.error(f"{name}: expect.signals[{i}] must be a mapping")
                    continue
                if sig.get("kind") not in SIGNAL_KINDS:
                    rep.error(f"{name}: bad signal kind {sig.get('kind')!r}")
                if sig.get("kind") == "possible_attack" and \
                        sig.get("attack_class") not in ATTACK_CLASSES:
                    rep.error(f"{name}: possible_attack needs attack_class")
                if sig.get("priority") not in PRIORITIES:
                    rep.error(f"{name}: bad priority {sig.get('priority')!r}")
            trust = exp.get("trust", {}) or {}
            if trust and trust.get("sender_level") not in TRUST_LEVELS:
                rep.error(f"{name}: bad trust.sender_level")
            # a "verified" sender must write from a domain registered to the
            # persona's client; anything else is a spoof and must not be
            # asserted as verified.
            if trust.get("sender_level") == "verified":
                for i, ev in enumerate(tl):
                    if not isinstance(ev, dict):
                        continue  # already reported as "event needs 'at'"
                    cl = ev.get("client") or {}
                    pid = cl.get("persona", "")
                    cf = cl.get("claimed_from", "")
                    if not pid or not cf:
                        continue
                    cid = (personas.get(pid) or {}).get("client_id", "")
                    dom = cf.split("@")[-1].lower()
                    registered = domains_by_client.get(cid, set())
                    if dom not in registered:
                        rep.error(f"{name} timeline[{i}]: claimed_from domain "
                                  f"{dom!r} is not registered for client "
                                  f"{cid!r} but trust.sender_level is verified")
            for b in exp.get("boss_actions", []) or []:
                if b not in BOSS_ACTIONS:
                    rep.error(f"{name}: bad boss_action {b!r}")
            for inv in exp.get("invariants", []) or []:
                if inv not in INVARIANTS:
                    rep.error(f"{name}: bad invariant {inv!r}")
            for i, ob in enumerate(exp.get("outbox", []) or []):
                rt = (ob or {}).get("reference_template") if isinstance(ob, dict) else None
                if rt and rt not in replies:
                    rep.error(f"{name}: expect.outbox[{i}].reference_template "
                              f"{rt!r} not in gen/templates/replies/")
            # Every expectation endpoint must bind to something the harness
            # can resolve deterministically: a ref, a pinned file attached in
            # this timeline, or (relations only) a matter id.
            refs = doc_refs | msg_refs

            def resolves(x, allow_matter=False):
                if allow_matter and isinstance(x, str) and x.startswith("matter:"):
                    return True
                return x in refs or x in pinned_here
            for i, rel in enumerate(exp.get("relations", []) or []):
                if not isinstance(rel, dict):
                    rep.error(f"{name}: expect.relations[{i}] must be a mapping")
                    continue
                if rel.get("kind") not in RELATION_KINDS:
                    rep.error(f"{name}: bad relation kind {rel.get('kind')!r}")
                for end in ("a", "b"):
                    if not resolves(rel.get(end), allow_matter=True):
                        rep.error(f"{name}: expect.relations[{i}].{end} "
                                  f"{rel.get(end)!r} is not a ref, a pinned "
                                  f"file in the timeline, or matter:<id>")
            for lane in ("quarantine", "soft_hold"):
                for q in exp.get(lane, []) or []:
                    if q in pinned_here and q not in attach_files:
                        rep.error(f"{name}: expect.{lane} {q!r} not in "
                                  f"attachments/manifest.csv")
                    elif not resolves(q):
                        rep.error(f"{name}: expect.{lane} {q!r} is not "
                                  f"attached anywhere in the timeline")
            for key in (exp.get("docs") or {}):
                if not resolves(key):
                    rep.error(f"{name}: expect.docs key {key!r} is not a ref "
                              f"or a pinned file in the timeline")
    if awaiting_specs:
        rep.warn(f"{len(awaiting_specs)} scenarios target gen frozen/live/loop "
                 f"but no message names a gen_spec yet (rendered from templates "
                 f"until C7 specs land): {', '.join(sorted(awaiting_specs)[:6])}"
                 f"{' …' if len(awaiting_specs) > 6 else ''}")
    return scenarios, by_series


def check_gen_specs(root: Path, personas: dict, rep: Report) -> dict:
    """Report invalid generation specs and return loaded mappings keyed by spec ID."""
    specs = {}
    for yf in sorted((root / "gen" / "specs").glob("*.yaml")):
        try:
            s = load_yaml(yf)
        except Exception as e:  # noqa: BLE001
            rep.error(f"gen/specs/{yf.name}: YAML error: {e}")
            continue
        if not isinstance(s, dict):
            rep.error(f"gen/specs/{yf.name}: top level must be a mapping")
            continue
        sid = s.get("id", "")
        check_id(sid, "spec_id", f"gen/specs/{yf.name}", rep)
        if sid in specs:
            rep.error(f"duplicate gen spec id: {sid}")
        specs[sid] = s
        for field in ("persona", "target_client", "archetype", "goal",
                      "constraints", "style", "pool", "expect"):
            if field not in s:
                rep.error(f"gen spec {sid}: missing {field!r}")
        if s.get("persona") not in personas:
            rep.error(f"gen spec {sid}: unknown persona "
                      f"{s.get('persona')!r}")
        forb = (s.get("constraints") or {}).get("forbidden", []) or []
        for must in ("real_brands", "real_urls", "working_links",
                     "phone_numbers_outside_555_01xx"):
            if must not in forb:
                rep.warn(f"gen spec {sid}: constraints.forbidden should "
                         f"include {must!r}")
        exp = s.get("expect", {}) or {}
        if exp.get("intent") not in INTENTS:
            rep.error(f"gen spec {sid}: bad expect.intent")
    return specs


def canonical_email_json(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def check_emails(root: Path, rep: Report) -> None:
    """Check frozen email hashes and index entries, plus handwritten front matter."""
    spec = content_files(root)
    idx_path = root / "emails" / "emails_index.csv"
    if not idx_path.exists():
        rep.warn("emails/emails_index.csv missing (no frozen emails yet)")
        return
    rows = check_csv_file(root, "emails/emails_index.csv",
                          spec["emails/emails_index.csv"], rep)
    # group frozen lines by series
    frozen: dict[str, dict[str, dict]] = {}
    for jf in sorted((root / "emails" / "frozen").glob("*.jsonl")):
        series = jf.stem
        text = read_text_or_error(jf, f"emails/frozen/{jf.name}", rep)
        if text is None:
            continue
        for ln, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError as e:  # JSONDecodeError
                rep.error(f"emails/frozen/{jf.name}:{ln}: bad JSON: {e}")
                continue
            if not isinstance(obj, dict):
                rep.error(f"emails/frozen/{jf.name}:{ln}: must be a JSON object")
                continue
            eid = obj.get("email_id", "")
            frozen.setdefault(series, {})[eid] = obj
    for r in rows:
        eid = r["email_id"]
        check_id(eid, "email_id", "emails_index.csv", rep)
        m = re.fullmatch(r"em_([A-Z])_[0-9]+", eid)
        if not m:
            continue
        series = m.group(1)
        obj = frozen.get(series, {}).get(eid)
        if obj is None:
            rep.error(f"emails_index.csv {eid}: no line in "
                      f"emails/frozen/{series}.jsonl")
            continue
        want = r["sha256"]
        got = hashlib.sha256(canonical_email_json(obj)).hexdigest()
        if want != got:
            rep.error(f"emails_index.csv {eid}: sha256 mismatch "
                      f"(manifest {want[:12]}… vs computed {got[:12]}…)")
        if r.get("tier") not in TIERS:
            rep.error(f"emails_index.csv {eid}: bad tier {r.get('tier')!r}")
    # handwritten anchors: markdown with front matter
    for mf in sorted((root / "emails" / "handwritten").glob("*.md")):
        text = read_text_or_error(mf, f"emails/handwritten/{mf.name}", rep)
        if text is None:
            continue
        if not text.startswith("---"):
            rep.error(f"emails/handwritten/{mf.name}: missing front matter")
            continue
        try:
            import yaml
            fm = yaml.safe_load(text.split("---", 2)[1])
        except Exception as e:  # noqa: BLE001
            rep.error(f"emails/handwritten/{mf.name}: front matter error: {e}")
            continue
        if not isinstance(fm, dict):
            rep.error(f"emails/handwritten/{mf.name}: front matter must be a "
                      f"mapping")
            continue
        for field in ("email_id", "spec_id", "scenario_id", "persona_id"):
            if field not in (fm or {}):
                rep.error(f"emails/handwritten/{mf.name}: front matter "
                          f"missing {field!r}")


def check_attachments(root: Path, rep: Report) -> None:
    """Check attachment IDs, provenance, file hashes, and inert-content restrictions."""
    spec = content_files(root)
    man_path = root / "attachments" / "manifest.csv"
    if not man_path.exists():
        rep.warn("attachments/manifest.csv missing")
        return
    rows = check_csv_file(root, "attachments/manifest.csv",
                          spec["attachments/manifest.csv"], rep)
    seen_files: set[str] = set()
    for r in rows:
        aid = r["attachment_id"]
        check_id(aid, "attachment_id", "attachments/manifest.csv", rep)
        fname = r["file"]
        if fname in seen_files:
            rep.error(f"attachments/manifest.csv: duplicate file {fname!r}")
        seen_files.add(fname)
        src = r.get("source", "")
        if src == "dataset":
            if not r.get("dataset_revision") or not r.get(
                    "dataset_filename"):
                rep.error(f"attachments/manifest.csv {aid}: dataset source "
                          f"needs dataset_revision + dataset_filename")
            # dataset bytes are never redistributed; nothing to hash locally
            continue
        # local file: verify sha256 and doc_id
        found = None
        for sub in ("synthetic", "offtaxonomy", "adversarial"):
            cand = root / "attachments" / sub / fname
            if cand.exists():
                found = cand
                break
        if found is None:
            # smoke fixtures may live under smoke/; check there too
            cand = root / "smoke" / "docs" / fname
            if cand.exists():
                found = cand
        if found is None:
            rep.error(f"attachments/manifest.csv {aid}: file {fname!r} not "
                      f"found under attachments/*/")
            continue
        data = found.read_bytes()
        got_sha = hashlib.sha256(data).hexdigest()
        if r.get("sha256") and r["sha256"] != got_sha:
            rep.error(f"attachments/manifest.csv {aid}: sha256 mismatch for "
                      f"{fname}")
        if r.get("doc_id") and r["doc_id"] != got_sha[:16]:
            rep.error(f"attachments/manifest.csv {aid}: doc_id must be "
                      f"first 16 hex of sha256")
        if r.get("inert") == "true":
            for marker in INERT_FORBIDDEN:
                if marker in data:
                    rep.error(f"attachments/manifest.csv {aid}: inert file "
                              f"{fname} contains forbidden marker "
                              f"{marker!r}")


def check_relations(root: Path, rep: Report) -> None:
    """Validate relation IDs and kinds, warning when the truth CSV is absent."""
    spec = content_files(root)
    p = root / "relations" / "relations_truth.csv"
    if not p.exists():
        rep.warn("relations/relations_truth.csv missing")
        return
    for r in check_csv_file(root, "relations/relations_truth.csv",
                            spec["relations/relations_truth.csv"], rep):
        check_id(r["relation_id"], "relation_id", "relations_truth.csv", rep)
        if r.get("kind") not in RELATION_KINDS:
            rep.error(f"relations_truth.csv {r['relation_id']}: bad kind "
                      f"{r.get('kind')!r}")


def check_adversary(root: Path, rep: Report) -> tuple[set[str], set[str]]:
    """Read adversary CSVs and return sets of lookalike domains and impostor IDs."""
    spec = content_files(root)
    lookalikes: set[str] = set()
    impostors: set[str] = set()
    p = root / "adversary" / "lookalike_domains.csv"
    if p.exists():
        for r in check_csv_file(root, "adversary/lookalike_domains.csv",
                                spec["adversary/lookalike_domains.csv"], rep):
            lookalikes.add(r["domain"])
    p = root / "adversary" / "impostor_personas.csv"
    if p.exists():
        for r in check_csv_file(root, "adversary/impostor_personas.csv",
                                spec["adversary/impostor_personas.csv"], rep):
            impostors.add(r["persona_id"])
    return lookalikes, impostors


def compile_registry(root: Path, clients: dict, contacts: dict,
                     domains: list[dict], lookalikes: set[str],
                     rep: Report) -> dict:
    """Build the registry the Correspondent reads; assert adversary stays out."""
    import yaml
    reg = {"version": 1, "clients": {}}
    dom_by_client: dict[str, list[str]] = {}
    addr_by_client: dict[str, list[str]] = {}
    for d in domains:
        dom_by_client.setdefault(d["client_id"], []).append(d["domain"])
    for _co_id, co in contacts.items():
        if co.get("is_registered") == "true":
            addr_by_client.setdefault(co["client_id"], []).append(co["email"])
    # class-level mix only; never stratum-level weights (§2.3)
    mix_by_client: dict[str, dict[str, float]] = {}
    man = root / "clients" / "client_doc_mix.csv"
    if man.exists():
        for m in read_csv(man):  # check_clients reports manifest faults
            w = parse_weight(m.get("weight"))
            if w is None:
                continue  # already reported as an error by check_clients
            mix_by_client.setdefault(m.get("client_id"), {})
            mix_by_client[m.get("client_id")][m.get("class")] = \
                mix_by_client[m.get("client_id")].get(m.get("class"), 0.0) + w
    for cid, c in clients.items():
        reg["clients"][cid] = {
            "display_name": c["display_name"],
            "verified_domains": sorted(dom_by_client.get(cid, [])),
            "verified_addresses": sorted(addr_by_client.get(cid, [])),
            "callback": {"contact": c["callback_contact"],
                         "phone": c["callback_phone"]},
            "reference_formats": {"matter": c.get("matter_format") or None,
                                  "claim": c.get("claim_format") or None},
            "usual_channels": [x.strip() for x in
                               (c.get("channels") or "email").split(",")],
            "normal_send_hours": c.get("send_hours", ""),
            "usual_mix": {k: round(v, 3) for k, v in
                          sorted(mix_by_client.get(cid, {}).items())},
        }
    # adversary must never leak into the registry
    blob = json.dumps(reg).lower()
    for dom in lookalikes:
        if dom.lower() in blob:
            rep.error(f"registry compile: lookalike domain {dom!r} leaked "
                      f"into the registry")
    for word in ("impostor", "scenario_ids", "attack_class"):
        if word in blob:
            rep.error(f"registry compile: forbidden token {word!r} in "
                      f"registry")
    dist = root / "dist"
    dist.mkdir(exist_ok=True)
    (dist / "registry.yaml").write_text(
        yaml.safe_dump(reg, sort_keys=True, allow_unicode=True),
        encoding="utf-8")
    rep.info(f"compiled dist/registry.yaml ({len(reg['clients'])} clients)")
    return reg


def leak_scan(root: Path, rep: Report) -> None:
    allow_path = root / "tools" / "brand_allowlist.txt"
    allow = set()
    if allow_path.exists():
        allow = {l.strip().lower() for l in
                 allow_path.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.strip().startswith("#")}
    scan_dirs = ["clients", "adversary", "personas", "taxonomy", "scenarios",
                 "gen", "emails", "attachments", "relations", "email",
                 "smoke", "protocol"]
    for d in scan_dirs:
        base = root / d
        if not base.exists():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file() or f.suffix in {".pdf", ".png", ".bin"}:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="strict")
            except (UnicodeDecodeError, ValueError):
                continue
            rel = str(f.relative_to(root))
            low = text.lower()
            # Allowlisted substrings (dataset provenance names, documented
            # allowlist hostnames) are blanked before scanning so embedded
            # brand substrings (e.g. "google" in "gmail.googleapis.com")
            # don't trip the scan. Blanking preserves length so indices
            # still align with the original text.
            low_scan = low
            for a in allow:
                if a:
                    low_scan = low_scan.replace(a, " " * len(a))
            # real-brand mentions in body text (WARN; client names are ERROR
            # in check_clients). Single-word entries use word boundaries so
            # schema field names (target_client) and ordinary words
            # ("straight" vs "aig") don't trip the scan.
            for brand in BRAND_BLOCKLIST:
                if " " in brand:
                    m = re.search(re.escape(brand), low_scan)
                else:
                    m = re.search(r"\b" + re.escape(brand) + r"\b", low_scan)
                if m:
                    # find a snippet
                    i = m.start()
                    snip = text[max(0, i - 30):i + 40].replace("\n", " ")
                    rep.warn(f"{rel}: real-brand mention {brand!r} …{snip}…")
                    break
            # phone numbers outside 555-01xx
            for m in PHONE_RE.finditer(text):
                if "555-01" not in m.group(0):
                    rep.error(f"{rel}: non-synthetic phone number "
                              f"{m.group(0)!r}")
                    break
            # real URLs
            for m in URL_RE.finditer(text):
                host = m.group(1).lower()
                if not (host.endswith(RESERVED_URL_HOSTS)
                        or host in allow):
                    rep.error(f"{rel}: non-reserved URL host {host!r}")
                    break
            # pasted-text heuristic for generation inputs
            if rel.startswith(("gen/specs", "emails/handwritten")):
                for ln, line in enumerate(text.splitlines(), 1):
                    if len(line) > 2000:
                        rep.warn(f"{rel}:{ln}: very long line "
                                 f"({len(line)} chars); possible pasted "
                                 f"dataset text")
                        break


def schema_validator(root: Path, name: str, rep: Report):
    """A Draft 2020-12 validator for schemas/<name>, or None (reported)."""
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return None  # check_scenarios already warns once
    try:
        return Draft202012Validator(json.loads(
            (root / "schemas" / name).read_text(encoding="utf-8")))
    except Exception as e:  # noqa: BLE001 - bad schema file is a real error
        rep.error(f"schemas/{name} unreadable: {e}")
        return None


def report_schema(validator, obj, where: str, rep: Report) -> None:
    if validator is None:
        return
    for error in validator.iter_errors(obj):
        path = ".".join(str(p) for p in error.absolute_path)
        rep.error(f"{where}: schema violation at {path or '<root>'}: "
                  f"{error.message[:160]}")


def check_contract_schemas(root: Path, registry: dict | None,
                           rep: Report) -> None:
    """Every content file with a JSON Schema is validated against it (CD6)."""
    v = schema_validator(root, "gen_spec.v1.json", rep)
    for yf in sorted((root / "gen" / "specs").glob("*.yaml")):
        try:
            report_schema(v, load_yaml(yf), f"gen/specs/{yf.name}", rep)
        except Exception:  # noqa: BLE001 - YAML errors reported elsewhere
            pass
    v = schema_validator(root, "persona_behavior.v1.json", rep)
    for yf in sorted((root / "personas" / "behavior").glob("*.yaml")):
        try:
            report_schema(v, load_yaml(yf), f"personas/behavior/{yf.name}", rep)
        except Exception:  # noqa: BLE001 - YAML errors reported elsewhere
            pass
    v = schema_validator(root, "overlay.v1.json", rep)
    ov = root / "email" / "overlay" / "example.jsonl"
    text = read_text_or_error(ov, "email/overlay/example.jsonl", rep) if ov.exists() else None
    if text is not None:
        for ln, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError as e:  # JSONDecodeError
                rep.error(f"email/overlay/example.jsonl:{ln}: bad JSON: {e}")
                continue
            report_schema(v, obj, f"email/overlay/example.jsonl:{ln}", rep)
    if registry is not None:
        report_schema(schema_validator(root, "registry.v1.json", rep),
                      registry, "dist/registry.yaml", rep)


ID_RANGE_KINDS = {
    # kind in ids/ranges.yaml -> (where the ids live, regex capturing nnnn)
    "generation_specs": re.compile(r"^gen_.*_([0-9]{4})$"),
    "emails": re.compile(r"^em_[A-Z]_([0-9]+)$"),
    "attachments": re.compile(r"^att_([0-9]+)$"),
    "relations": re.compile(r"^rel_([0-9]+)$"),
}


def collect_ids(root: Path) -> dict[str, list[tuple[str, str]]]:
    """(id, where) per range kind, from every file that mints IDs."""
    out: dict[str, list[tuple[str, str]]] = {k: [] for k in ID_RANGE_KINDS}
    for yf in sorted((root / "gen" / "specs").glob("*.yaml")):
        try:
            out["generation_specs"].append((load_yaml(yf)["id"],
                                            f"gen/specs/{yf.name}"))
        except Exception:  # noqa: BLE001 - reported by check_gen_specs
            pass
    for kind, rel, col in (("emails", "emails/emails_index.csv", "email_id"),
                           ("attachments", "attachments/manifest.csv",
                            "attachment_id"),
                           ("relations", "relations/relations_truth.csv",
                            "relation_id")):
        p = root / rel
        if p.exists():
            out[kind] += [(r.get(col, ""), rel) for r in read_csv(p)]
    return out


def _block_ok(b) -> bool:
    """Return whether an allocation block has integer bounds and an owner key."""
    return (isinstance(b, dict) and isinstance(b.get("lo"), int)
            and isinstance(b.get("hi"), int) and "owner" in b)


def check_id_ranges(root: Path, rep: Report) -> None:
    """Report malformed or overlapping allocations, duplicate IDs, and unallocated IDs."""
    p = root / "ids" / "ranges.yaml"
    if not p.exists():
        rep.error("ids/ranges.yaml missing (ID range allocation, §12.5)")
        return
    try:
        ranges = load_yaml(p)
    except Exception as e:  # noqa: BLE001 - any YAML failure is a reported error
        rep.error(f"ids/ranges.yaml is not valid YAML: {e}")
        return
    if ranges is None:
        ranges = {}
    if not isinstance(ranges, dict):
        rep.error("ids/ranges.yaml: top level must be a mapping")
        return
    if ranges.get("schema") != "mailroom.id_ranges/v1":
        rep.error("ids/ranges.yaml: schema must be mailroom.id_ranges/v1")
    bad_kinds: set[str] = set()
    for kind, blocks in ranges.items():
        if kind == "schema":
            continue
        if blocks is None:
            blocks = []
        if not isinstance(blocks, list) or not all(_block_ok(b) for b in blocks):
            rep.error(f"ids/ranges.yaml {kind}: each block needs integer lo, "
                      f"integer hi and an owner")
            bad_kinds.add(kind)
            continue
        spans = sorted((b["lo"], b["hi"], b["owner"]) for b in blocks)
        for (lo1, hi1, o1), (lo2, _hi2, o2) in zip(spans, spans[1:]):
            if lo2 <= hi1:
                rep.error(f"ids/ranges.yaml {kind}: {o1} and {o2} overlap")
    for kind, ids in collect_ids(root).items():
        if kind in bad_kinds:
            continue  # the block list itself is reported above
        blocks = ranges.get(kind) or []
        seen: dict[str, str] = {}
        for ident, where in ids:
            if ident in seen:
                rep.error(f"{where}: duplicate id {ident} (also in {seen[ident]})")
            seen[ident] = where
            m = ID_RANGE_KINDS[kind].match(ident if isinstance(ident, str) else "")
            if not m:
                continue  # malformed ids are reported by check_id
            n = int(m.group(1))
            if not any(b["lo"] <= n <= b["hi"] for b in blocks):
                rep.error(f"{where}: {ident} is outside every {kind} block "
                          f"in ids/ranges.yaml")


def scenario_doc_specs(sc: dict):
    """Yield every document spec in a scenario: ingress docs and attachments."""
    for ev in sc.get("timeline", []) or []:
        if not isinstance(ev, dict):
            continue
        if isinstance(ev.get("ingress"), dict):
            yield ev["ingress"]
        for a in (ev.get("client") or {}).get("attach", []) or []:
            if isinstance(a, dict):
                yield a


def coverage_report(root: Path, mixes: list[dict], scenarios: dict,
                    rep: Report, strict: bool = False) -> dict:
    """Addendum §2.4: every ground-truth stratum needs at least one plausible
    sender (client mix) and one scenario attachment spec. Catalog-only strata
    have no dataset rows and are reported but never required. ``strict``
    turns gaps into errors (the build-time test)."""
    strata, _off = load_strata(root)
    cov: dict[tuple[str, str], dict] = {}
    for key, row in strata.items():
        if row.get("in_ground_truth") == "true":
            cov[key] = {"clients": set(), "scenarios": set(),
                        "attachments": set()}
    for m in mixes:
        key = (m["class"], m["stratum"])
        w = parse_weight(m.get("weight", 0) or 0)
        if key in cov and w is not None and w > 0:
            cov[key]["clients"].add(m["client_id"])
    pinned: dict[str, tuple[str, str]] = {}
    man = root / "attachments" / "manifest.csv"
    if man.exists():
        for r in read_csv(man):  # check_attachments reports manifest faults
            key = (r.get("class", ""), r.get("stratum", ""))
            pinned[r.get("file")] = key
            if key in cov and r.get("in_taxonomy") == "true":
                cov[key]["attachments"].add(r.get("attachment_id"))
    for name, sc in scenarios.items():
        for spec in scenario_doc_specs(sc):
            key = (spec.get("class"), spec.get("stratum"))
            if spec.get("file") in pinned:
                key = pinned[spec["file"]]
            if key in cov:
                cov[key]["scenarios"].add(name)
    uncovered = [k for k, v in cov.items()
                 if not v["clients"] or not v["scenarios"]]
    report = rep.error if strict else rep.warn
    for cls, stratum in sorted(uncovered):
        v = cov[(cls, stratum)]
        missing = [w for w, ok in (("client", v["clients"]),
                                   ("scenario", v["scenarios"])) if not ok]
        report(f"coverage: {cls}/{stratum} has no {' + '.join(missing)}")
    rep.info(f"coverage: {len(cov) - len(uncovered)}/{len(cov)} ground-truth "
             f"strata have a client and a scenario")
    return {f"{c}/{s}": {k: sorted(vv) for k, vv in v.items()}
            for (c, s), v in sorted(cov.items())}


def generate_indexes(root: Path, scenarios: dict, by_series: dict,
                     rep: Report) -> None:
    rows = []
    for name in sorted(scenarios):
        s = scenarios[name]
        series = name[0]
        exp = s.get("expect", {}) or {}
        sigs = exp.get("signals", []) or []
        client_ids = sorted({(ev.get("client") or {}).get("persona", "")
                             for ev in s.get("timeline", []) or []
                             if ev.get("client")})
        rows.append({
            "scenario_id": name,
            "series": series,
            "title": s.get("title", ""),
            "gen_mode": s.get("gen", ""),
            "min_profile": s.get("profile", ""),
            "transports": "|".join(s.get("transports", []) or []),
            "client_ids": "|".join(c for c in client_ids if c),
            "expected_intent": exp.get("intent", ""),
            "expected_signal": "|".join(sig.get("kind", "")
                                        for sig in sigs),
            "tags": "|".join(s.get("tags", []) or []),
            "status": s.get("status", "draft"),
            "owner": s.get("owner", ""),
        })
    out = root / "scenarios" / "scenarios_index.csv"
    if rows:
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        rep.info(f"wrote {out.relative_to(root)} ({len(rows)} scenarios)")


def run_checks() -> int:
    """Parse CLI options, validate and compile the pack, and return 1 on reported errors."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent
                                          .parent))
    ap.add_argument("--generate-indexes", action="store_true")
    ap.add_argument("--coverage-out", default=None)
    ap.add_argument("--strict-coverage", action="store_true",
                    help="coverage gaps are errors (addendum §2.4)")
    args = ap.parse_args()
    root = Path(args.root)
    rep = Report()

    check_content_json(root, rep)
    check_content_files_index(root, rep)
    check_ops_contracts(root, rep)
    clients, contacts, domains, mixes = check_clients(root, rep)
    domains_by_client: dict[str, set] = {}
    for d in domains:
        domains_by_client.setdefault(d["client_id"], set()).add(
            d["domain"].lower())
    personas = check_personas(root, clients, contacts, rep)
    scenarios, by_series = check_scenarios(root, personas,
                                             domains_by_client, rep)
    check_gen_specs(root, personas, rep)
    check_emails(root, rep)
    check_attachments(root, rep)
    check_relations(root, rep)
    lookalikes, _impostors = check_adversary(root, rep)
    registry = None
    if clients:
        registry = compile_registry(root, clients, contacts, domains,
                                    lookalikes, rep)
    check_contract_schemas(root, registry, rep)
    check_id_ranges(root, rep)
    leak_scan(root, rep)
    cov = coverage_report(root, mixes, scenarios, rep,
                          strict=args.strict_coverage)
    if args.coverage_out:
        Path(args.coverage_out).write_text(json.dumps(cov, indent=2),
                                           encoding="utf-8")
    if args.generate_indexes:
        generate_indexes(root, scenarios, by_series, rep)

    n_scen = len(scenarios)
    print(f"scenarios: {n_scen} "
          f"({', '.join(f'{k}:{len(v)}' for k, v in sorted(by_series.items()))})")
    print(f"errors: {len(rep.errors)}, warnings: {len(rep.warnings)}")
    for e in rep.errors:
        print(f"ERROR: {e}")
    for w in rep.warnings[:40]:
        print(f"WARN: {w}")
    if len(rep.warnings) > 40:
        print(f"… and {len(rep.warnings) - 40} more warnings")
    return 0 if rep.ok() else 1


def main() -> int:
    """Exit 0 on success, 1 on validation ERRORs, 2 on an internal failure.
    The outer guard turns any unexpected exception into one ERROR line rather
    than a bare traceback."""
    try:
        return run_checks()
    except Exception as e:  # noqa: BLE001 - last-resort guard, see docstring
        print(f"ERROR internal: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
