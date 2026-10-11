# Email generation — from template and spec to frozen body

This document describes how the pack's **inbound email bodies** are produced:
how a scenario message, its scripted Jinja2 template and its generation spec
become a *frozen* record in `emails/frozen/<series>.jsonl` with an audit row in
`emails/emails_index.csv`.

It is the content-side companion to the consumer contract in
`CONTENT_SPEC.md` §5 (generation modes) and §4.2–§4.3 (message shape and
template variables), and to the reloaded sandbox loader described in
[`mailroom-reloaded` `docs/SANDBOX_CONTENT.md`](https://github.com/Exios66/mailroom-reloaded/blob/main/docs/SANDBOX_CONTENT.md).

> **Who owns what.** mailroom-reloaded owns the contract (schemas, the loader,
> `content.lock`). This repo owns the content and the tooling that renders it.
> The generation layer here is the *interim* implementation of the plan's M9
> generation step; reloaded's `mailroom sandbox content build` validates a
> content tree and regenerates the smoke fixtures, but **does not generate
> frozen emails** (verified 2026-10-10). Until M9 lands in reloaded, this repo's
> `tools/build_frozen_emails.py` is the only writer of `emails/frozen/`.

---

## 1. Where generation sits in the pack

```
scenarios/<Series>/<ID>.yaml     one client message names template + gen_spec
        │
        ├── gen/templates/<template>.j2        scripted body + generation fallback
        ├── gen/specs/<id>.yaml                what the message must be (§6.3)
        └── personas/, clients/                persona sheet + registered contact
        │
        ▼   tools/build_frozen_emails.py
        │   payload guard → free/paid pool → inertness linter → conformance
        ▼
emails/frozen/<Series>.jsonl     the frozen body + freeze manifest
emails/emails_index.csv          one audit row per body (sha256 over the line)
```

Three artifacts, three jobs:

| Artifact | Role |
|---|---|
| `gen/templates/*.j2` | The **scripted** body and the generation **fallback**. Every client message renders from one (§4.3); first rendered line is `Subject: …`. |
| `gen/specs/*.yaml` | The **generation spec** (`mailroom.gen_spec/v1`): the message's label by construction — goal, `constraints.must_include`, `style`, synthetic `context`, `pool`, `expect`. A message names its spec with `gen_spec:`. |
| `emails/frozen/*.jsonl` | The **frozen** result, once. Text is produced only by the generation layer and is never hand-patched (CD16). |

`gen` mode on the scenario decides what the message *is*: `scripted` renders the
template; `frozen` / `live` / `loop` use the `gen_spec` (`CONTENT_SPEC.md` §5).
This tool freezes the `frozen` mode.

**Legacy scripted anchors.** Seven records (`em_A_0001`, `em_A_0002`,
`em_B_0001`, `em_D_0001`, `em_E_0001`, `em_E_0002`, `em_F_0001`) predate this
layer. They are `tier=scripted` scripted renders with a shorter manifest and are
not rewritten by the tool; the "starts with `Subject:` / full manifest"
invariant below applies to records the generation layer writes. `--check`
reports any record missing the layer's `template_fallback` key as legacy.

---

## 2. The generation pipeline

For each `frozen` scenario message that names a `gen_spec`, the tool runs the
stages below, in order.

### 2.1 Binding

The tool binds a spec to the message that references it and pulls the standard
template context (`CONTENT_SPEC.md` §4.3): `sender_name`, `sender_first_name`,
`sender_title` (from the persona's registered contact), `sender_email`
(`claimed_from`), `client_display_name`, `attachment_name(s)`, plus the
message's `vars`. The scripted template is rendered with that context — this
render is both the fallback body and the content anchor for the prompt.

### 2.2 Prompt (synthetic only)

The prompt carries the spec's goal, register, length, language, `must_include`
and `forbidden` tags, the synthetic `context`, the persona sheet, the attachment
names, and the rendered draft. Nothing else.

### 2.3 Payload guard (§6.5)

Free-tier providers may log and train on prompts, so nothing sensitive may leave
the machine. Before any call, the guard rejects a prompt containing:

- a real-brand blocklist token (single-source: `tools/validate.py`
  `BRAND_BLOCKLIST`),
- a non-reserved URL host (anything but `.sandbox.invalid`, `.example`, `.test`,
  `.localhost`),
- a phone number outside `+1-555-01xx`.

A blocked prompt aborts that spec (it is never sent). Dataset text is never in a
prompt: the guard only ever sees persona sheets, synthetic field values,
class/stratum labels and reference formats (`gen/policy.yaml` §6.5).

### 2.4 Model pool (`gen/pool.yaml`)

Free models first (`free_pool.seed_candidates`, minus `excluded_retiring`),
then the `paid_tier` slots and alternates. The pool is a **runtime artifact**:
it is re-verified against the OpenRouter models endpoint at sandbox up, and the
seed list is re-ordered on evidence. The 2026-10-10 verification is recorded in
the file: only `nvidia/nemotron-3-ultra-550b-a55b:free` served this API
reliably; `thinkingmachines/inkling:free` is 403 agentic-harness-only; gemma is
upstream-rate-limited; some nemotron models leak chain-of-thought into
`content` and are excluded.

### 2.5 Call and retry

One call per model, walking the ordered list. A model is skipped on a retryable
failure: HTTP 4xx/5xx (including 429 and 403), a timeout, an empty/`None`
`content`, or a response that is not an email. `temperature` is low (0.7) and
`max_tokens` capped.

### 2.6 Inertness linter (§6.5)

On the raw text: URLs and naked domains are rewritten to reserved hosts, phone
numbers to `+1-555-01xx`, and a surviving real-brand token is *unrepairable* —
the attempt fails and the next model is tried. Every rewrite is recorded in the
record's `manifest.lint_actions`.

### 2.7 Conformance (§6.3)

The text must start with a `Subject:` line, match the spec's register length
(within a ×0.5–×1.8 margin), match the language, carry at least half of the
`must_include` features, and contain no leaked meta text (prompt echo, chain of
thought, word counts). A failure regenerates with the next model.

### 2.8 Freeze

The first conforming response is frozen. Every record **written by the
generation layer** carries its **freeze manifest** (`gen/policy.yaml`):

| Field | Meaning |
|---|---|
| `model_id` | the model that produced it, or `template` for a fallback |
| `tier` | `free` \| `paid` \| `scripted` |
| `prompt_hash` | sha256 of the exact prompt |
| `attempts` | models tried |
| `refusals` | empty/refusal responses seen |
| `lint_actions` | linter rewrites applied |
| `conformance` | passed the §6.3 check |
| `template_fallback` | true when the attempt budget was exhausted |
| `frozen_at` | UTC timestamp |

### 2.9 Fallback (§6.4)

If every model fails, the record is the **scripted template** with
`tier=scripted`, `model_id=template`, `template_fallback=true`. It is never
silently relabelled frozen. Adversarial specs (injection, impersonation, threats)
frequently fall back because the models refuse — that refusal is the honest,
expected outcome, not a defect.

### 2.10 Index

`emails/emails_index.csv` gets one row per body. `sha256` is over the canonical
frozen JSONL line (`json.dumps(obj, sort_keys=True, separators=(",",":"))`,
`ensure_ascii=False`) — the same canonicalisation `tools/validate.py`
`canonical_email_json` uses. `tools/build_frozen_emails.py --check` and
`tools/validate.py` check 9 both verify index ↔ JSONL consistency.

---

## 3. Running it

The OpenRouter key is read **only** from `OPENROUTER_API_KEY` (or `--key-file`)
and is never written to the repo, a log or an index row.

```bash
# Build every prompt and run the payload guard; no network:
python3 tools/build_frozen_emails.py --dry-run

# Freeze the scripted template for one series without a key (no network):
python3 tools/build_frozen_emails.py --render-only --series D

# Generate for real (free pool first, paid fallback):
OPENROUTER_API_KEY=… python3 tools/build_frozen_emails.py --series D

# All frozen specs; skip ones already frozen free/paid; retry fallbacks:
OPENROUTER_API_KEY=… python3 tools/build_frozen_emails.py --sleep 1.5 --attempts 8

# Regenerate a spec even if it is already frozen:
OPENROUTER_API_KEY=… python3 tools/build_frozen_emails.py --spec gen_g1_frustrated_status_0601 --force

# Verify index ↔ JSONL consistency:
python3 tools/build_frozen_emails.py --check
```

A run is **resumable**: specs already frozen as `free`/`paid` are skipped, and
re-running a spec *replaces* its own record and index row (never duplicates).
`--no-paid-fallback` keeps a run on the free pool only.

After generating, the normal gate applies: `python3 tools/validate.py
--strict-coverage` (0 errors, 0 warnings) and the unit suite. Never hand-edit a
frozen body — regenerate it.

---

## 4. How reloaded consumes the result

- The pack is pinned in reloaded's `sandbox/content.lock` (repo, tag, commit,
  bundle sha256, schema_version, dataset_revision). A branch tip is never
  consumed; only a tagged release.
- The consumer's loader reads `emails/` and validates the pack; `mailroom
  sandbox content build` validates a tree and regenerates the smoke fixtures
  from `tools/export_smoke.py` — it does **not** generate frozen bodies.
- The freeze manifest and `emails_index.csv` are the provenance a conformance
  run reads back; `frozen_at` and `model_id` must stay honest so a rate or a
  fallback rate is attributable.

**Verified 2026-10-10** against a `mailroom-reloaded` checkout at `3a615af`:
`tools/check_schema_drift.py` → `schema drift: none (6 shared schema(s)
byte-identical)`, and `tools/load_with_consumer.py` →
`consumer-load: scenarios=116 personas=14 gen_specs=72 errors=0`.

## 5. Rules (do not break)

1. **Frozen text is generated, never hand-written or hand-patched** (CD16).
   Change the spec or the template, then regenerate.
2. **The key never enters the repo, a log or a PR.** Env var only.
3. **Provenance is honest.** A fallback is `tier=scripted`, not frozen.
4. **Never edit `emails_index.csv` by hand** — it is generated; regenerate it.
5. **IDs come from `ids/ranges.yaml`** (`emails` C8-frozen block, 100–9999;
   the scripted anchors live in C8-handwritten, 1–99).
6. **Everything stays synthetic** — reserved domains, `555-01xx` phones, no real
   brands. The leak scan enforces it.
