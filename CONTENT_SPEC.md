# Content spec — mailroom-sandbox-content

The contract between this content pack and the mailroom-reloaded sandbox.
Normative file formats are the JSON Schemas in `schemas/`; this document
explains them. Where this document and a schema disagree, the schema wins.

## 1. Formats (addendum v2 §12.4)

Tabular, one row per entity, bulk-editable → **CSV**. Nested or behavioral
→ **YAML**. Free text → **JSONL** or **Markdown**.

| Path | Format | Grain | Notes |
|---|---|---|---|
| `clients/clients.csv` | CSV | one row per client | `primary_domain` must end `.sandbox.invalid`; `callback_phone` must match `+1-555-01xx`; display names must not collide with real brands (ERROR) |
| `clients/client_contacts.csv` | CSV | one row per contact | contact emails must be `*.sandbox.invalid` |
| `clients/client_domains.csv` | CSV | one row per domain | registered domains only — lookalikes are **not** here, they live in `adversary/` |
| `clients/client_doc_mix.csv` | CSV | one row per client × class × stratum | weights per client must sum to 1.0; stratum must exist in `taxonomy/strata.csv`; only class-level mix is compiled into the registry |
| `personas/personas.csv` | CSV | one row per persona | each row points at `behavior/<persona_id>.yaml` |
| `personas/behavior/*.yaml` | YAML | nested persona behavior | must carry matching `persona_id`, `escalation`, and `attachment_habits` |
| `scenarios/<Series>/*.yaml` | YAML | one scenario per file | `mailroom.scenario/v2`; filename stem must equal `name`; name must start with the series letter |
| `gen/specs/*.yaml` | YAML | one generation spec per file | `id` must match `gen_*`; must declare `persona`, `target_client`, `archetype`, `goal`, `constraints`, `style`, `pool`, `expect` |
| `emails/emails_index.csv` | CSV | one row per frozen email | `sha256` is over the canonical frozen JSONL line (sorted keys, compact separators) |
| `emails/frozen/<series>.jsonl` | JSONL | one email object per line | free text bodies; `email_id` must exist in the index with a matching sha256 |
| `emails/handwritten/*.md` | Markdown | one email per file | YAML front matter with `email_id`, `spec_id`, `scenario_id`, `persona_id` |
| `attachments/manifest.csv` | CSV | one row per attachment | local files: `sha256` verified and `doc_id` = first 16 hex of sha256; `inert=true` files must contain no active-content markers |
| `relations/relations_truth.csv` | CSV | one row per relation | `kind` from the eight relation kinds |
| `adversary/lookalike_domains.csv` | CSV | one row per lookalike domain | sandbox-only; never compiled into the registry |
| `adversary/impostor_personas.csv` | CSV | one row per impostor persona | sandbox-only; never compiled into the registry |
| `taxonomy/strata.csv` | CSV | one row per class × stratum | stratum names are **provisional** until verified against the dataset (see [verify]) |
| `scenarios/scenarios_index.csv`, `taxonomy/coverage.csv`, `gen/gen_specs_index.csv` | CSV | generated | written by `tools/validate.py --generate-indexes` / coverage; never hand-edit |

## 2. ID conventions (addendum v2 §12.6)

| Entity | Pattern | Example |
|---|---|---|
| Clients | slug | `tricountytitle` |
| Contacts | `<clientprefix>_<name>` | `tc_kalvarado` |
| Personas | `p_<client>_<role>` | `p_tricounty_real` |
| Scenarios | `<Series><n>_<slug>` | `E1_lookalike_wire_change` |
| Generation specs | `gen_<archetype>_<nnnn>` | `gen_E1_wire_change_0042` |
| Emails | `em_<series>_<nnnn>` | `em_E_0042` |
| Attachments | `att_<nnnn>` | `att_0001` |
| Relations | `rel_<nnnn>` | `rel_0001` |

CI enforces these as regexes: scenario `^[A-GST][0-9]+_[a-z0-9_]+$`
(series letters A–G, S, T only),
persona `^p_[a-z0-9_]+$`, spec `^gen_[a-zA-Z0-9_]+$`, email
`^em_[A-Z]_[0-9]+$`, attachment `^att_[0-9]+$`, relation `^rel_[0-9]+$`.

## 3. Scenario series (addendum v2 §3)

Nine series directories under `scenarios/`: `A`, `B`, `C`, `D`, `E`, `F`,
`G`, `S`, `T`. One agent owns one series end to end.

- **G-series is production-adjacent.** It covers realistic external
  communications the Correspondent handles in production-adjacent
  operation: frustrated processing-status requests, document-entity
  extraction requests and corrections, bulk status and summary requests,
  re-extraction after amendment, receipt confirmations, forwarded-chain
  timelines, expedite requests, client-stated court deadlines, access-scope
  questions, and repeat questions. All G scenarios are benign
  (`overblocking.benign_hard_actions: 0`); extraction corrections produce
  `contradicts` relations and are never auto-linked.

- **E-series is identity-dependent.** It covers lookalike / impostor /
  credential scenarios (e.g. `E1_lookalike_wire_change`). E-series scenarios
  are **not valid on the gmail leg** — auth there is genuine, so a scenario
  that asserts synthetic auth results cannot run on it (CI warns if an
  E-series scenario lists the `gmail` transport).
- Valid **transports** per scenario: `sim`, `agentmail`, `gmail`.
- Valid **profiles**: `smoke`, `demo`, `prod_like`, `chaos`, `coverage`.
- Scenario **status** moves `draft` → `review` → `frozen` → `deprecated`.
  Only `frozen` scenarios feed frozen email bodies and CI-gated runs.

[verify] Full per-series definitions live in addendum v2 §3 and are not yet
transcribed here — confirm each series' scope before adding scenarios to it.

## 4. Generation modes (addendum v2 §6.2)

| Mode | Meaning | CI-gated? |
|---|---|---|
| `scripted` | Fully deterministic content (hand-written or templated) | yes |
| `frozen` | Generated once, then snapshotted; sha256 pinned in `emails_index.csv` | yes |
| `live` | Generated at run time by the sandbox | no |
| `loop` | Interactive persona-loop generation | no |

Only `frozen` + `scripted` gate CI. A scenario with `gen: live` or
`gen: loop` may exist in the repo, but its outputs are never asserted by
content-ci.

## 5. Hold lanes

Outbound correspondence that is not auto-approved lands in a hold lane:

- **`comms/pending`** — soft lane. Held for review; releasable by the boss
  (`release_attachments`, `approve_outbound`).
- **`comms/quarantine`** — hard lane. Held with attachments quarantined;
  requires human review (`quarantine_attachments`, `request_human_review`).

Scenario `expect` blocks assert which lane a message should land in via
`soft_hold` / `quarantine` lists and the `hold_attachments` /
`quarantine_attachments` / `release_attachments` boss actions.

## 6. Registry vs adversary separation

The Correspondent never sees the whole repo. It reads the **compiled
registry** (`dist/registry.yaml`, built by `tools/validate.py` from
`clients/`): display name, verified domains, verified addresses, callback
contact/phone, reference formats, usual channels, send hours, and the
**class-level** document mix. The registry never contains stratum-level
weights, lookalike domains, impostor personas, or scenario labels
(`scenario_ids`, `attack_class`, `impostor`).

`adversary/` is sandbox-only attack material. CI compiles the registry and
then asserts that no lookalike domain and none of the forbidden tokens
(`impostor`, `scenario_ids`, `attack_class`) appear anywhere in the compiled
blob. A leak is an ERROR.

## 7. Email infrastructure map (`email/`)

| Piece | Role |
|---|---|
| Sender pool | The real inboxes the sandbox sends from on each leg |
| Overlay contract | `mailroom.overlay/v1`: `kind=message` records carry wire-visible fields only (`provider_message_id`, `from`, `display`, synthetic `auth` results); `kind=route` records map a virtual `*.sandbox.invalid` address to a real sender-pool inbox. Records carry no persona ids, scenario ids, or labels — ever. |
| AgentMail | Leg honored by `comms/channels/agentmail.py` **only** when `MAILROOM_ENV=sandbox`; the sandbox gateway writes `overlay/overlay.jsonl`, mounted read-only into the Correspondent container |
| Gmail sandbox | Genuine-auth leg; identity-dependent (E-series) scenarios are not valid here |
| Recipient policy | Who may receive sandbox mail on each leg |
| Ingress policy | Metered admission rates, inbox capacity, backpressure |
| Send schedule | Scheduled free-model outbound windows + doom-loop guards |

File-level contracts now exist for all of the above; the remaining
[verify] items are the live-service values (AgentMail host/limits,
Gmail token lifetime) confirmed at sandbox-up, tracked in §10.

## 8. content-ci checks

`tools/validate.py` (exit 0 = clean, 1 = any ERROR; WARNs never fail):

1. `content.json` shape and semver.
2. CSV headers / row rules per `schemas/content_files.json`.
3. Scenario YAMLs: strict validation against `schemas/scenario.v2.json`
   (jsonschema) plus required fields and enums (intents, signal kinds,
   attack classes, trust levels, relation kinds, boss actions, invariants,
   profiles, gen modes, transports, priorities, tiers, auth results);
   filename stem must equal `name`; name must match `^[A-GST]`.
4. Cross-references: persona ids, client ids, spec ids, attachment files.
   `expect.quarantine` entries must be attached in the timeline and present
   in the attachment manifest. A `verified` sender must write from a domain
   registered to the persona's client.
5. Leak scan: no real brands in client names, no non-`555-01xx` phone
   numbers, no real URLs, no pasted dataset text.
6. Registry compile excludes `adversary/` (lookalikes, impostors, labels).
7. `emails_index.csv` ↔ frozen JSONL sha256 consistency.
8. Attachment manifest sha256 / `doc_id` verification for local files;
   inert files checked for active-content markers.
9. Ops contracts: `email/ingress_policy.yaml`, `email/send_schedule.yaml`,
   and `email/recipient_policy.yaml` must parse and satisfy their schemas
   (positive caps, sandbox/demo-only send profiles, free-model-only sends,
   kill switch + circuit breaker present, priority reserve < hourly cap,
   idempotency key includes the outbound message identity).
10. Coverage report (strata × clients × scenarios × attachments).

Optional flags: `--generate-indexes` writes `scenarios_index.csv`;
`--coverage-out PATH` writes the coverage map as JSON.

## 9. Compatibility policy

- **Schema major must match.** `content.json` declares `schema_version`
  (currently `2.0`). mailroom-reloaded declares the schema major it
  understands; a bundle whose major version differs is refused.
- **Code version window.** `content.json` declares `min_code_version` and
  `max_code_version` (currently `0.1.0` / `0.2.0`). A mailroom-reloaded
  checkout outside that window must not consume the bundle.
- **Pinning.** Consumers never track a branch. `sandbox/content.lock` in
  mailroom-reloaded pins repo + tag + commit + bundle sha256 of the
  release tarball.

## 10. [verify] — content-side open items

- **Dataset stratum names are provisional.** `taxonomy/strata.csv` rows
  marked `provisional` must be verified against the dataset before they
  gate coverage.
- **GLM / DeepSeek model slugs.** Generation pools that name GLM or DeepSeek
  models must use the exact slugs from the addendum; confirm before adding
  `gen/specs` entries that reference them.
- **AgentMail plan limits.** Confirm the sandbox's AgentMail plan limits
  (send volume, inbox count) before sizing the sender pool in `email/`.
