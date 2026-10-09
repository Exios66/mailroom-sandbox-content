# Changelog

All notable changes to the mailroom-sandbox-content pack.

## [Unreleased]

### Fixed
- **The release bundle sha256 was not reproducible across `zstandard`
  versions** (same commit: 0.25.0 gives the sha256 pinned in
  `content.lock`, 0.23.0 gives a different one). `tools/requirements.txt` pins
  `zstandard==0.25.0`; `build_bundle.py --release` (used by `release.sh`)
  refuses any other version; the new `BUILD_INFO` asset records the version
  and `tar_sha256` (digest of the uncompressed tar, compressor-independent).
  The published asset's bytes remain what a downloader verifies. `SHA256SUMS`
  is unchanged (still `sha256sum -c` clean).
- **The validator crashed or silently accepted bad CSV and YAML input**
  (plan K-02). Four crash paths are closed: a UTF-8 BOM on a CSV header
  (now accepted and stripped), a short CSV row, a NUL byte in a CSV, and a
  corrupt `ids/ranges.yaml`. Two silent accepts are closed: a row with extra
  cells, and a duplicate `client_id` in `clients.csv`. One strict reader,
  `read_csv_strict` in `tools/validate.py`, now reads every CSV the validator
  opens; YAML and JSON parse errors and non-mapping roots are reported as
  ERRORs. An outer guard prints `ERROR internal: <type>: <msg>` and exits 2
  instead of a traceback (exit 1 is still a validation ERROR). New
  `tests/test_validate_faults.py` covers the reader and seven fault cases
  end to end. `tools/fault_inject.py` exposes `MUTATIONS` and `main(argv)`
  so the tests can reuse the mutations.

### Added
- `tools/lint_contradictions.py` and `docs/CONTRADICTION_AUDIT.md` (plan K-03,
  stage 1): the linter groups scenarios by client template set and
  `expect.intent` and reports groups whose members disagree on `expect.outbox`
  or priority (`--strict` exits 1; a top-level `contrast` string exempts a
  scenario, but the schema does not allow that key yet). The audit checks each
  reported finding and the brief's named scenarios against the delegation
  matrix and protocol. No scenario was edited. Tests in
  `tests/test_lint_contradictions.py`. Not yet wired into `tools/ci.sh`.
- `tools/fault_inject.py`: fault-injection harness for the validator (28
  mutations; classifies CLEAN-FAIL / CRASH / MISSED). Seed for the K-02 tests.
- **H-series ("held-out") scenarios**: 28 scenarios under `scenarios/H/`
  (H1–H28), at least three per family A–G, S and T, each tagged `heldout`
  and rendered from a new inbound template (`gen/templates/h_*.j2`).
  Authored from the delegation matrix, the Correspondent↔Boss protocol and
  the policy sources only; expectations are derived from the delegation
  matrix, never from the Correspondent's behaviour or conformance output.
- The scenario `name` series now admits `H`
  (`schemas/scenario.v2.json`, `^[A-HST][0-9]+_[a-z0-9_]+$`) with an H ID
  block (`1500–1599`) in `ids/ranges.yaml`, preparing a held-out batch for a
  future run via the consumer's `mailroom sandbox conformance --heldout`
  after human approval and scenario freeze.
- `tools/check_schema_drift.py`: compares each schema here that mailroom-reloaded
  also ships byte-for-byte with that checkout (path argument or
  `MAILROOM_RELOADED`); prints `DRIFT <file>` and exits 1 on any difference,
  exits 0 when skipped without a checkout. Tests in
  `tests/test_check_schema_drift.py`. Not yet wired into `tools/ci.sh`.

### Changed
- `CONTENT_SPEC.md` §3 and `README.md` list the new H (held-out) series;
  `tools/validate.py` accepts the H-series name pattern.
- **Schema sync (K-05).** mailroom-reloaded owns the contract.
  `schemas/gen_spec.v1.json` and `schemas/persona_behavior.v1.json` are now
  byte-for-byte copies of the consumer's, which are stricter (closed objects,
  required `constraints.forbidden`); the pack validates against them with 0
  errors. `schemas/scenario.v2.json` is **not** synced: the consumer's name
  pattern `^[A-GST][0-9]+_[a-z0-9_]+$` rejects all 28 H-series scenarios, so
  the content copy stays until the consumer admits the H series.
- **`unknown` is no longer a relation kind.** mailroom-reloaded's
  `relation_kinds.v1.json` allows the eight kinds only (`unknown` is a
  `linked_docs` placeholder). No pack file uses it, so `tools/validate.py`
  and its test drop it. `schemas/scenario.v2.json` still lists it until that
  file is synced.
- `CONTENT_SPEC.md` and `README.md` say mailroom-reloaded owns the contract
  and shared schemas are mirrors checked by `tools/check_schema_drift.py`.

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
- Release bundle now includes the compiled `dist/registry.yaml` (the old
  workflow excluded it with `dist/`).

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
  ranges, drawable strata, resolvable endpoints; strata drift check.
- 117 unit tests (was 87), including a render of every scenario message.

### Changed
- **No GitHub Actions.** `.github/workflows/` removed (the owner's Actions
  are locked). content-ci runs locally as `tools/ci.sh` and as the git
  pre-push hook (`tools/install-hooks.sh`); releases are cut with
  `tools/release.sh`, which builds a deterministic bundle with
  `tools/build_bundle.py` (same commit, same sha256) and tags locally;
  `--push` publishes through the `gh` CLI when it is logged in.
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
