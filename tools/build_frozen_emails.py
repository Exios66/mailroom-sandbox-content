#!/usr/bin/env python3
"""Frozen email generation layer (plan C-03; addendum v2 §6.2-§6.5).

This is the interim M9 generation layer for the content repo. It reads the
generation specs (``gen/specs/*.yaml``) and the scenario message that references
each one, builds a *synthetic-only* prompt (payload guard, §6.5), calls a free
OpenRouter model drawn from ``gen/pool.yaml``, applies the inertness linter,
runs the conformance check (§6.3), and freezes the result into
``emails/frozen/<series>.jsonl`` plus ``emails/emails_index.csv``.

Honesty rules (CD16, §6.3): frozen text is produced only here, is never
hand-patched, and every record carries its provenance (model_id, tier,
prompt_hash, attempts, lint_actions, conformance, frozen_at). When generation
fails the attempt budget, the record falls back to the scenario's scripted
template with ``template_fallback=true`` and ``tier=scripted`` — it is never
silently relabelled frozen.

The OpenRouter key is read from ``OPENROUTER_API_KEY`` (or ``--key-file``) and
is never written to the repo, a log or an index row. A payload guard blocks any
prompt that would carry dataset text, a real URL/phone or a real brand, so
nothing sensitive leaves the machine.

Usage::

    OPENROUTER_API_KEY=... python3 tools/build_frozen_emails.py            # generate all
    python3 tools/build_frozen_emails.py --dry-run                         # build prompts only
    python3 tools/build_frozen_emails.py --render-only                     # no network: scripted
    python3 tools/build_frozen_emails.py --series E --limit 5              # subset
    python3 tools/build_frozen_emails.py --check                           # verify index<->jsonl
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

# Reuse the validator's single sources of truth for the leak rules.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate as V  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SPECS = ROOT / "gen" / "specs"
TEMPLATES = ROOT / "gen" / "templates"
FROZEN = ROOT / "emails" / "frozen"
INDEX = ROOT / "emails" / "emails_index.csv"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

INDEX_HEADER = [
    "email_id", "spec_id", "scenario_id", "persona_id", "lang", "register",
    "words", "tier", "model_id", "prompt_hash", "sha256", "lint_actions",
    "conformance", "template_fallback", "frozen_at",
]

SYSTEM_PROMPT = (
    "You rewrite inbound business email for a fully synthetic testing sandbox. "
    "You are given a brief and a draft. Produce ONE email body that keeps every "
    "factual detail of the draft (references, names, dates, attachments) but "
    "varies the wording to match the requested register and length. "
    "Output ONLY the email, beginning with a 'Subject:' line. "
    "Never invent real companies, real URLs or real phone numbers; use only the "
    "synthetic details supplied. Do not add commentary, notes or explanation."
)

# must_include tag -> tokens that count as evidence the feature is present.
FEATURE_TOKENS = {
    "urgency": ("urgent", "asap", "immediately", "today", "time-sensitive",
                "priority", "deadline"),
    "call_suppression": ("cannot take calls", "email only", "do not call",
                         "email confirmation", "no calls"),
    "pending_closing_reference": ("closing", "closing date", "funding"),
    "emotional_language": ("frustrat", "disappoint", "upset", "angry",
                           "unacceptable", "appalled"),
    "complaint_subject": ("complaint", "complain", "concern"),
    "specific_grievance": ("request", "no one", "unanswered", "no response",
                           "still waiting", "third"),
}

# TAG -> fallback: any underscore token longer than 3 chars, or the tag itself.
_WORD_RE = re.compile(r"[a-z0-9]+")
_META_RE = re.compile(
    r"(?i)(\bcount words\b|\bword count\b|let'?s count|let me count|"
    r"\bstep \d|\banalysis:|\breasoning:|\bnote to self\b|"
    r"\bas an ai\b|\bi cannot\b|```|"
    r"thinking process|analyze the request|archetype:|must convey:|"
    r"known facts|forbidden:)")


def _tokens(tag: str) -> tuple[str, ...]:
    if tag in FEATURE_TOKENS:
        return FEATURE_TOKENS[tag]
    return tuple(t for t in _WORD_RE.findall(tag.lower()) if len(t) > 3)


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def now_utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Loading the pack
# --------------------------------------------------------------------------- #
def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def load_specs() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in sorted(SPECS.glob("*.yaml")):
        spec = yaml.safe_load(f.read_text(encoding="utf-8"))
        out[spec["id"]] = spec
    return out


def scenario_bindings() -> dict[str, dict]:
    """spec_id -> binding for every message that names a gen_spec when the
    scenario is in frozen mode. Companion messages without a spec are ignored."""
    out: dict[str, dict] = {}
    for f in sorted((ROOT / "scenarios").glob("*/*.yaml")):
        s = yaml.safe_load(f.read_text(encoding="utf-8"))
        if s.get("gen") != "frozen":
            continue
        series = f.parent.name
        for ev in s.get("timeline") or []:
            if not isinstance(ev, dict):
                continue
            cl = ev.get("client")
            if not isinstance(cl, dict) or not cl.get("gen_spec"):
                continue
            sid = cl["gen_spec"]
            out[sid] = {
                "scenario": s["name"],
                "series": series,
                "persona": cl.get("persona"),
                "template": cl.get("template"),
                "vars": cl.get("vars") or {},
                "claimed_from": cl.get("claimed_from", ""),
                "attachments": [a.get("file") for a in (cl.get("attach") or [])
                                if isinstance(a, dict) and a.get("file")],
                "reply_to_sender": bool(
                    (s.get("expect") or {}).get("outbox")),
            }
    return out


def personas() -> dict[str, dict]:
    out = {}
    for r in read_csv(ROOT / "personas" / "personas.csv"):
        out[r["persona_id"]] = r
    return out


def behavior(persona_row: dict) -> dict:
    rel = persona_row.get("behavior_file")
    if not rel:
        return {}
    p = ROOT / "personas" / "behavior" / Path(rel).name
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def clients() -> dict[str, dict]:
    return {r["client_id"]: r for r in read_csv(ROOT / "clients" / "clients.csv")}


def contacts() -> dict[str, dict]:
    return {r["contact_id"]: r
            for r in read_csv(ROOT / "clients" / "client_contacts.csv")}


def render_template(name: str, ctx: dict) -> str:
    import jinja2
    src = (TEMPLATES / f"{name}.j2").read_text(encoding="utf-8")
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    rendered = env.from_string(src).render(**ctx)
    return rendered.strip("\n") + "\n"


def message_context(persona_row: dict, vars_: dict, attachment: str | None,
                    claimed_from: str = "") -> dict:
    """Standard context (§4.3) + vars, exactly as the validator builds it."""
    cl = clients().get(persona_row.get("client_id"), {})
    ct = contacts().get(persona_row.get("contact_id"), {})
    ctx = {
        "sender_name": ct.get("full_name", ""),
        "sender_first_name": (ct.get("full_name", "").split(" ")[0]
                              if ct.get("full_name") else ""),
        "sender_title": ct.get("role", ""),
        "sender_email": claimed_from,
        "client_display_name": cl.get("display_name", ""),
        "attachment_name": attachment or "",
        "attachment_names": [attachment] if attachment else [],
    }
    ctx.update(vars_)
    return ctx


# --------------------------------------------------------------------------- #
# Prompt, guard, linter, conformance
# --------------------------------------------------------------------------- #
def _length_range(spec: dict) -> tuple[int, int]:
    rng = re.findall(r"\d+", str((spec.get("style") or {}).get("length", "")))
    if len(rng) >= 2:
        return int(rng[0]), int(rng[1])
    return 40, 140


def length_lo(spec: dict) -> int:
    return _length_range(spec)[0]


def length_hi(spec: dict) -> int:
    return _length_range(spec)[1]


def style_length_hint(spec: dict) -> str:
    lo, hi = _length_range(spec)
    return str((lo + hi) // 2)


def build_prompt(spec: dict, binding: dict, persona_row: dict, sheet: dict,
                 draft: str) -> str:
    lines = [
        f"Archetype: {spec.get('archetype', '')}",
        f"Goal: {spec.get('goal', '')}",
        f"Register: {(spec.get('style') or {}).get('register', 'neutral')}",
        f"Length: {(spec.get('style') or {}).get('length', 'natural')}",
        f"Language: {(spec.get('style') or {}).get('language', 'en')}",
    ]
    must = (spec.get("constraints") or {}).get("must_include") or []
    if must:
        lines.append("Must convey: " + ", ".join(must))
    forbidden = (spec.get("constraints") or {}).get("forbidden") or []
    if forbidden:
        lines.append("Forbidden: " + ", ".join(forbidden))
    ctx = spec.get("context") or {}
    if ctx:
        lines.append("Known facts (synthetic): " +
                     "; ".join(f"{k}={v}" for k, v in ctx.items()))
    if sheet:
        tone = sheet.get("tone") or ""
        reg = sheet.get("register") or ""
        lines.append(f"Sender persona — tone: {tone}; style: {reg}")
    atts = binding.get("attachments") or spec.get("attachments") or []
    if atts:
        lines.append("Attachments to reference by name: " + ", ".join(atts))
    lines.append("")
    lines.append(
        f"Write between {length_lo(spec)} and {length_hi(spec)} words "
        f"(aim for ~{style_length_hint(spec)}). Keep the draft's facts and "
        "structure. Do not add sections, explanations, word counts or "
        "analysis. Output only the email and stop immediately after the "
        "sign-off line.")
    lines.append("Draft to rewrite:")
    lines.append(draft.strip())
    return "\n".join(lines)


def payload_guard(prompt: str) -> str | None:
    """Return a reason if the prompt must not leave the machine (§6.5)."""
    low = prompt.lower()
    for brand in V.BRAND_BLOCKLIST:
        pat = (re.escape(brand) if " " in brand
               else r"\b" + re.escape(brand) + r"\b")
        if re.search(pat, low):
            return f"real-brand/protected token {brand!r} in prompt"
    for m in V.URL_RE.finditer(prompt):
        host = m.group(1).lower()
        if not host.endswith(V.RESERVED_URL_HOSTS):
            return f"non-reserved URL host {host!r} in prompt"
    for m in V.PHONE_RE.finditer(prompt):
        if "555-01" not in m.group(0):
            return f"non-synthetic phone {m.group(0)!r} in prompt"
    return None


def inertness_linter(text: str) -> tuple[str, list[str]]:
    """Rewrite risky surface forms (§6.5). Raises ValueError when a real brand
    survives (unrepairable -> the attempt fails and is regenerated)."""
    actions: list[str] = []
    low = text.lower()
    for brand in V.BRAND_BLOCKLIST:
        pat = (re.escape(brand) if " " in brand
               else r"\b" + re.escape(brand) + r"\b")
        if re.search(pat, low):
            raise ValueError(f"real brand {brand!r} in output (unrepairable)")

    def _url(m: re.Match) -> str:
        host = m.group(1).lower()
        if host.endswith(V.RESERVED_URL_HOSTS):
            return m.group(0)
        actions.append(f"url:{host}->example.sandbox.invalid")
        return "https://example.sandbox.invalid/"

    text = V.URL_RE.sub(_url, text)
    # Naked domains (no scheme) -> reserved.
    def _dom(m: re.Match) -> str:
        if m.group(0).lower().endswith(".sandbox.invalid"):
            return m.group(0)
        actions.append(f"domain:{m.group(0)}->sandbox.invalid")
        return m.group(1) + ".sandbox.invalid"

    text = re.sub(r"\b([A-Za-z0-9-]+)\.(?:com|net|org|io|ai|co|gov|edu)\b",
                  _dom, text)

    def _phone(m: re.Match) -> str:
        if "555-01" in m.group(0):
            return m.group(0)
        actions.append("phone->+1-555-0100")
        return "+1-555-0100"

    text = re.sub(r"\+?1?[-. ()]?\d{3}[-. )]?\d{3}[-. ]?\d{4}", _phone, text)
    return text, actions


def conformance(spec: dict, text: str) -> tuple[bool, str]:
    """Best-effort §6.3 conformance: signal words, length and language."""
    body = text
    words = body.split()
    style = spec.get("style") or {}
    length = str(style.get("length", ""))
    rng = re.findall(r"\d+", length)
    if len(rng) >= 2:
        lo, hi = int(rng[0]), int(rng[1])
        if not (lo * 0.5 <= len(words) <= hi * 1.8):
            return False, f"length {len(words)} outside {lo}-{hi} (x0.5-1.8)"
    lang = (style.get("language") or "en").lower()
    if not lang.startswith("en") and not re.search(r"[À-ÿñáéíóú]", body):
        return False, f"expected {lang} text"
    must = (spec.get("constraints") or {}).get("must_include") or []
    if must:
        low = body.lower()
        hits = sum(1 for tag in must
                   if any(tok in low for tok in _tokens(tag)))
        if hits < max(1, (len(must) + 1) // 2):
            return False, f"only {hits}/{len(must)} must_include features"
    if not re.search(r"^\s*subject:", body, re.IGNORECASE | re.MULTILINE):
        return False, "no Subject: line"
    if _META_RE.search(body):
        return False, "meta/reasoning text leaked into the body"
    return True, "ok"


# --------------------------------------------------------------------------- #
# OpenRouter client
# --------------------------------------------------------------------------- #
class Retryable(Exception):
    pass


class OpenRouter:
    def __init__(self, key: str, timeout: int = 90, max_tokens: int = 700,
                 temperature: float = 0.7):
        self.key = key
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.last_model = None  # the concrete model the provider served

    def __call__(self, model: str, prompt: str) -> str:
        body = json.dumps({
            "model": model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": prompt}],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }).encode("utf-8")
        req = urllib.request.Request(
            OPENROUTER_URL, data=body,
            headers={"Authorization": f"Bearer {self.key}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", "replace")[:160]
            except Exception:  # noqa: BLE001
                detail = ""
            raise Retryable(f"HTTP {e.code} {detail}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise Retryable(str(e)) from e
        try:
            content = data["choices"][0]["message"].get("content")
        except (KeyError, IndexError) as e:
            raise Retryable(f"bad response shape: {str(data)[:200]}") from e
        if content is None:
            raise Retryable("empty content (reasoning/refusal)")
        if isinstance(content, list):  # some providers return content parts
            content = "".join(p.get("text", "") for p in content
                              if isinstance(p, dict))
        # Provenance: when a router alias (e.g. openrouter/free) is asked, the
        # response names the concrete model that actually served it.
        self.last_model = data.get("model") or model
        return content


def strip_fences(text: str | None) -> str:
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    # Drop common preambles before the Subject line.
    m = re.search(r"(?im)^\s*subject:", text)
    if m and m.start() > 0:
        text = text[m.start():]
    return text.strip() + "\n"


def model_tier(model: str) -> str:
    """Honest provenance: the free router counts as free, not paid."""
    return "free" if (model.endswith(":free") or model == "openrouter/free") \
        else "paid"


def paid_models(pool: dict) -> list[str]:
    tier = pool.get("paid_tier", {}) or {}
    out = [s["model"] for s in tier.get("slots", []) if s.get("model")]
    out += [a["model"] for a in tier.get("alternates", []) if a.get("model")]
    return out


def free_models(pool: dict) -> list[str]:
    excl = set(pool.get("free_pool", {}).get("excluded_retiring", []) or [])
    seeds = pool.get("free_pool", {}).get("seed_candidates", []) or []
    models = [m for m in seeds if m not in excl]
    router = (pool.get("free_pool", {}).get("discovery", {}) or {}).get(
        "router_fallback")
    if router:
        models.append(router)
    return models


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
def generate_one(spec, binding, persona_row, sheet, client, models, *,
                 attempts: int, sleep: float, log=print) -> dict:
    draft = render_template(binding["template"],
                            message_context(persona_row, binding["vars"],
                                            (binding["attachments"] or [None])[0],
                                            binding.get("claimed_from", "")))
    prompt = build_prompt(spec, binding, persona_row, sheet, draft)
    reason = payload_guard(prompt)
    if reason:
        raise SystemExit(f"payload guard blocked {spec['id']}: {reason}")
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    lint_actions: list[str] = []
    refusals = 0
    used = 0
    for i in range(min(attempts, len(models))):
        model = models[i]
        used += 1
        if sleep and used > 1:
            time.sleep(sleep)
        try:
            raw = client(model, prompt)
        except Retryable as e:
            log(f"  [{spec['id']}] {model} retryable: {e}")
            continue
        served = getattr(client, "last_model", None) or model
        text = strip_fences(raw)
        if not text or len(text.split()) < 5:
            refusals += 1
            log(f"  [{spec['id']}] {model} empty/refusal")
            continue
        try:
            text, acts = inertness_linter(text)
        except ValueError as e:
            log(f"  [{spec['id']}] {model} linter unrepairable: {e}")
            continue
        ok, why = conformance(spec, text)
        if not ok:
            log(f"  [{spec['id']}] {model} conformance fail: {why}")
            continue
        lint_actions = acts
        return freeze_record(spec, binding, text, draft, served,
                             prompt_hash, used, refusals, lint_actions,
                             tier=model_tier(served), fallback=False)

    # Attempt budget exhausted -> scripted fallback (§6.4), honestly labelled.
    log(f"  [{spec['id']}] fallback to scripted template after {used} attempts")
    return freeze_record(spec, binding, draft, draft, "template",
                         prompt_hash, used, refusals, [], tier="scripted",
                         fallback=True)


def freeze_record(spec, binding, text, draft, model, prompt_hash, attempts,
                  refusals, lint_actions, *, tier, fallback) -> dict:
    text = text.strip("\n") + "\n"
    m = re.search(r"(?im)^\s*subject:\s*(.+)$", text)
    subject = m.group(1).strip() if m else (binding["scenario"])
    return {
        "email_id": "",  # assigned at write time
        "spec_id": spec["id"],
        "scenario_id": binding["scenario"],
        "persona_id": binding["persona"],
        "headers": {"subject": subject},
        "body": text,
        "attachments": binding.get("attachments") or [],
        "manifest": {
            "model_id": model,
            "tier": tier,
            "prompt_hash": prompt_hash,
            "attempts": attempts,
            "refusals": refusals,
            "lint_actions": lint_actions,
            "conformance": True,
            "template_fallback": fallback,
            "frozen_at": now_utc(),
        },
    }


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def load_existing() -> tuple[dict[str, dict], list[dict]]:
    records: dict[str, dict] = {}
    for f in sorted(FROZEN.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                o = json.loads(line)
                records[o["email_id"]] = o
    rows = read_csv(INDEX) if INDEX.exists() else []
    return records, rows


def next_ids(existing: dict[str, dict], series: str, n: int) -> list[str]:
    used = {int(e.split("_")[-1]) for e in existing if e.split("_")[1] == series}
    start = 100
    while start in used:
        start += 1
    return [f"em_{series}_{start + i:04d}" for i in range(n)]


def index_row(rec: dict, spec: dict, lang: str) -> dict:
    man = rec["manifest"]
    return {
        "email_id": rec["email_id"],
        "spec_id": rec["spec_id"],
        "scenario_id": rec.get("scenario_id", spec.get("archetype", "")),
        "persona_id": rec["persona_id"],
        "lang": lang,
        "register": (spec.get("style") or {}).get("register", ""),
        "words": str(len(rec["body"].split())),
        "tier": man["tier"],
        "model_id": man["model_id"],
        "prompt_hash": man["prompt_hash"],
        "sha256": hashlib.sha256(canonical(rec)).hexdigest(),
        "lint_actions": json.dumps(man["lint_actions"]),
        "conformance": "true" if man["conformance"] else "false",
        "template_fallback": "true" if man["template_fallback"] else "false",
        "frozen_at": man["frozen_at"],
    }


def dedupe_by_spec(records: dict[str, dict],
                   rows: list[dict]) -> tuple[dict[str, dict], list[dict], set]:
    """One record per spec_id. Keep the best: generated over fallback, then the
    newest. A regenerated spec must never leave two rows behind."""
    best: dict[str, tuple] = {}
    for r in rows:
        eid = r["email_id"]
        man = (records.get(eid) or {}).get("manifest", {})
        score = (0 if man.get("template_fallback") else 1,
                 1 if r.get("tier") in ("free", "paid") else 0, eid)
        sid = r["spec_id"]
        if sid not in best or score > best[sid][0]:
            best[sid] = (score, eid)
    keep = {v[1] for v in best.values()}
    drop = {r["email_id"] for r in rows if r["email_id"] not in keep}
    return ({e: r for e, r in records.items() if e not in drop},
            [r for r in rows if r["email_id"] not in drop], drop)


def write_outputs(records: dict[str, dict], rows: list[dict]) -> None:
    records, rows, _ = dedupe_by_spec(records, rows)
    FROZEN.mkdir(parents=True, exist_ok=True)
    by_series: dict[str, list[dict]] = {}
    for rec in records.values():
        by_series.setdefault(rec["email_id"].split("_")[1], []).append(rec)
    for series, recs in by_series.items():
        recs.sort(key=lambda r: r["email_id"])
        path = FROZEN / f"{series}.jsonl"
        path.write_text(
            "\n".join(canonical(r).decode("utf-8") for r in recs) + "\n",
            encoding="utf-8")
    rows.sort(key=lambda r: r["email_id"])
    with INDEX.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=INDEX_HEADER, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in INDEX_HEADER})


def check(root: Path = ROOT) -> int:
    records, rows = load_existing()
    bad = 0
    for r in rows:
        rec = records.get(r["email_id"])
        if not rec:
            print(f"ERROR {r['email_id']}: no frozen JSONL line")
            bad += 1
            continue
        got = hashlib.sha256(canonical(rec)).hexdigest()
        if got != r.get("sha256"):
            print(f"ERROR {r['email_id']}: sha256 mismatch")
            bad += 1
    for eid in records:
        if eid not in {r["email_id"] for r in rows}:
            print(f"ERROR {eid}: JSONL line with no index row")
            bad += 1
    seen: dict[str, str] = {}
    for r in rows:
        sid = r["spec_id"]
        if sid in seen:
            print(f"ERROR duplicate spec_id {sid!r}: {seen[sid]} and "
                  f"{r['email_id']}")
            bad += 1
        seen[sid] = r["email_id"]
    legacy = [e for e, r in records.items()
              if "template_fallback" not in (r.get("manifest") or {})]
    if legacy:
        print(f"note: {len(legacy)} legacy scripted anchor(s) predate the "
              f"generation layer: {', '.join(sorted(legacy))}")
    print(f"check: {len(rows)} index rows, {len(records)} jsonl records, "
          f"{bad} problem(s)")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", action="append", default=[],
                    help="only this spec id (repeatable)")
    ap.add_argument("--series", help="only this series letter")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--attempts", type=int, default=8,
                    help="models to try per email (free first, then paid)")
    ap.add_argument("--sleep", type=float, default=3.0,
                    help="seconds between calls (rate headroom)")
    ap.add_argument("--dry-run", action="store_true",
                    help="build prompts and validate the guard, no calls")
    ap.add_argument("--render-only", action="store_true",
                    help="no network: freeze the scripted template, tier=scripted")
    ap.add_argument("--no-paid-fallback", action="store_true",
                    help="stay on the free pool only; never fall back to paid")
    ap.add_argument("--check", action="store_true",
                    help="verify index <-> jsonl then exit")
    ap.add_argument("--dedupe", action="store_true",
                    help="collapse duplicate spec_id rows, rewrite, then check")
    ap.add_argument("--force", action="store_true",
                    help="regenerate specs that already have a frozen record")
    ap.add_argument("--key-file", help="read the key from this file")
    args = ap.parse_args(argv)

    if args.check:
        return check()
    if args.dedupe:
        records, rows = load_existing()
        records, rows, drop = dedupe_by_spec(records, rows)
        write_outputs(records, rows)
        print(f"deduped: removed {len(drop)} record(s): {sorted(drop)}")
        return check()

    specs = load_specs()
    bindings = scenario_bindings()
    pool = yaml.safe_load((ROOT / "gen" / "pool.yaml").read_text(encoding="utf-8"))
    models = free_models(pool)
    if not args.no_paid_fallback:
        models = models + paid_models(pool)
    prows = personas()
    existing, rows = load_existing()
    have = {r["spec_id"] for r in rows if r.get("tier") in ("free", "paid")}

    targets = [sid for sid in sorted(bindings) if sid in specs]
    if args.spec:
        targets = [s for s in targets if s in set(args.spec)]
    if args.series:
        targets = [s for s in targets if bindings[s]["series"] == args.series]
    if not args.force:
        targets = [s for s in targets if s not in have]
    if args.limit:
        targets = targets[: args.limit]

    if not targets:
        print("nothing to generate (use --force to regenerate)")
        return 0

    key = os.environ.get("OPENROUTER_API_KEY", "")
    if args.key_file:
        key = Path(args.key_file).read_text(encoding="utf-8").strip()

    if args.render_only:
        def client(model, prompt):
            raise Retryable("render-only")
    elif not args.dry_run:
        if not key:
            print("ERROR: set OPENROUTER_API_KEY (or --key-file)",
                  file=sys.stderr)
            return 2
        client = OpenRouter(key)

    print(f"generating {len(targets)} spec(s) "
          f"({len(free_models(pool))} free + "
          f"{len(paid_models(pool))} paid models available)")
    # Replace any existing record for a regenerated spec (a fallback retried
    # later must overwrite its own row, never add a duplicate).
    old_by_spec = {r["spec_id"]: r["email_id"] for r in rows}
    new_records: dict[str, dict] = {}
    new_rows: list[dict] = []
    ok = fallback = 0
    for sid in targets:
        spec = specs[sid]
        binding = bindings[sid]
        prow = prows.get(binding["persona"], {})
        sheet = behavior(prow)
        if args.dry_run:
            draft = render_template(binding["template"], message_context(
                prow, binding["vars"], (binding["attachments"] or [None])[0],
                binding.get("claimed_from", "")))
            prompt = build_prompt(spec, binding, prow, sheet, draft)
            reason = payload_guard(prompt)
            print(f"{sid}: prompt {len(prompt)} chars; guard "
                  f"{'BLOCKED: ' + reason if reason else 'ok'}")
            continue
        rec = generate_one(spec, binding, prow, sheet, client, models,
                           attempts=args.attempts, sleep=args.sleep)
        series = binding["series"]
        eid = old_by_spec.get(sid) or next_ids(
            {**existing, **new_records}, series, 1)[0]
        rec["email_id"] = eid
        new_records[eid] = rec
        new_rows.append(index_row(rec, spec,
                                  (spec.get("style") or {}).get("language", "en")))
        if rec["manifest"]["template_fallback"]:
            fallback += 1
        else:
            ok += 1

    if args.dry_run:
        return 0
    merged_records = {e: r for e, r in existing.items()
                      if r["spec_id"] not in set(targets)}
    merged_records.update(new_records)
    merged_rows = [r for r in rows if r["spec_id"] not in set(targets)] + new_rows
    write_outputs(merged_records, merged_rows)
    print(f"wrote {len(new_rows)} record(s): {ok} generated, {fallback} fallback")
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
