# Changelog

All notable changes to the mailroom-sandbox-content pack.

## 0.5.0 — 2026-10-08

Corrective and build-out release (docs/IMPLEMENTATION_PLAN.md, phases 1–2).
0.1.0 was merged but never tagged; 0.5.0 is the first release.

### Fixed
- **Strata were hand-typed and wrong.** Contract "strata" were CUAD clause
  labels and several merger/correspondence strata do not exist in the
  dataset. `taxonomy/strata.csv` is now generated from mailroom-reloaded's
  subclass catalogue (`tools/sync_strata.py`, v0.2.0): 56 catalog strata,
  54 in ground truth, row counts blank until the dataset scan. 50 stale
  references were migrated (`taxonomy/migrations/0001_strata.csv`).
- **Client mixes** rewritten to the addendum §2.2 class weights; every
  ground-truth stratum now has a plausible sender.
- **Messages had no body.** 96 client messages named neither a template nor
  a spec. Every message now has a scripted `template` (+ `vars`); the
  Correspondent-side `g_*` reply templates moved to
  `gen/templates/replies/` and are referenced from
  `expect.outbox[].reference_template`.
- **Expectations could not bind.** Relation endpoints were free text and
  ingress docs named files that did not exist. Scenarios now use
  scenario-local refs; endpoints must resolve. Reversed relations (A3, B1,
  B3, A5, B6) fixed; A4's "duplicate" is now the same document
  (`same_as`).
- Sender addresses match each persona's registered contact; spec personas
  match their scenarios; B/C/D/F expectations aligned with addendum §3/§8.
- Release: the compiled `dist/registry.yaml` now ships in the bundle.

### Added
- Final `mailroom.scenario/v2` shape (CONTENT_SPEC §4, amendment AM2):
  `client.attach` (addendum §4.8), `ingress` `{file}` or
  `{class, stratum, as}`, `ref`, `same_as`, `group`, `reply_to`, closed
  `fault` vocabulary.
- 49 new inbound templates (11 of them the D/F hand-written bodies moved out of scenario files); 4 synthetic fixtures (`schedule_c_v2.pdf`,
  `lease_v1_unit4b.pdf`, `okafor_claim_letter_cl558201.pdf`,
  `officer_certificate_tc1190.pdf`); `taxonomy/offtaxonomy.csv`.
- Coverage scenarios A13–A17, generated; content-ci runs
  `--strict-coverage`.
- Smoke export (`tools/export_smoke.py`) for `sandbox/fixtures/smoke/`:
  6 scenarios, 6 documents, ~30 KB, zero network.
- `tools/build_attachments.py` (dataset counts + selection; label/hash
  columns only), `tools/make_fixture_pdf.py`, `ids/ranges.yaml`.
- Validator: every JSON Schema enforced, template variables checked, ID
  ranges, drawable strata, resolvable endpoints; CI strata-drift job.
- 117 unit tests (was 87), including a render of every scenario message.

### Changed
- `content.json`: 0.5.0, `dataset_revision` `ed7576b6` (train split),
  code window 0.2.0–0.3.0.
- Amendments to addendum v2 recorded in CONTENT_SPEC §13 (AM1 G-series and
  `protocol/`, AM2 scenario shape, AM3 strata count, AM4 relation
  direction).

## 0.1.0 — 2026-10-08 (merged, not tagged)

Seed release: the content contract, the validator, and the skeleton the
series owners will fill in.

- **Content contract** (`schemas/`): `content_files.json` (CSV headers and
  row rules), `registry.v1.json`, `scenario.v2.json` (`mailroom.scenario/v2`),
  `gen_spec.v1.json`, `overlay.v1.json` (`mailroom.overlay/v1`), and
  `persona_behavior.v1.json`.
- **Pack identity** (`content.json`): version `0.1.0`, `schema_version`
  `2.0`, `dataset_revision` `v9`, code window `0.1.0`–`0.2.0`.
- **Taxonomy seed** (`taxonomy/strata.csv`): document classes × strata;
  rows still marked `provisional` are not yet verified against the dataset.
- **Validator** (`tools/validate.py`, workstream C11): the nine content-ci
  checks — content.json shape, CSV headers, scenario YAMLs, cross-references,
  leak scan, adversary-free registry compile, frozen-email sha256
  consistency, attachment manifest verification, and the coverage report.
  Also compiles `dist/registry.yaml` and can generate `scenarios_index.csv`
  and the coverage map.
- **Scenario series skeletons**: `scenarios/` directories for series
  `A`–`G`, `S`, `T` (83 scenarios landed: A:12, B:8, C:11, D:6, E:13, F:5,
  G:12, S:10, T:6); `gen/specs` (40 generation specs) and `gen/templates`
  skeletons; `emails/frozen` (scripted frozen renders) and
  `emails/handwritten` (7 worked-example anchors).
- **Registry + smoke skeletons**: `clients/` (10 clients, 12 contacts,
  registered domains, doc mixes), `personas/` (14 personas with
  `behavior/` state machines), `relations/` (8 ground-truth relations),
  `adversary/` (lookalikes, impostors, 7-class attack catalogue),
  `attachments/` (13 synthetic/off-taxonomy/inert fixtures with sha256
  manifest), `email/` (AgentMail sender pool, overlay contract, Gmail
  sandbox config, recipient policy, ingress policy, send schedule), and
  `smoke/` (6-scenario, 13-document smoke set).
- **Docs + CI seed**: `README.md`, `CONTENT_SPEC.md`, `CODEOWNERS`,
  `content-ci.yml` (validate on PR and main pushes), `release.yml`
  (tag → tarball + SHA256SUMS + GitHub release), and `tools/content.sh`
  local shims.
