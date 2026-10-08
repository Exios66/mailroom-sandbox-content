# Changelog

All notable changes to the mailroom-sandbox-content pack.

## 0.1.0 — 2026-10-08

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
  `A`–`F`, `S`, `T` (no scenarios yet); `gen/specs` and `gen/templates`
  skeletons; `emails/frozen` and `emails/handwritten` skeletons.
- **Registry + smoke skeletons**: `clients/`, `personas/` (with
  `behavior/`), `relations/`, `adversary/`, `attachments/`
  (`synthetic/`, `offtaxonomy/`, `adversarial/`), `email/`, and `smoke/`
  directory skeletons with no rows yet.
- **Docs + CI seed**: `README.md`, `CONTENT_SPEC.md`, `CODEOWNERS`,
  `content-ci.yml` (validate on PR and main pushes), `release.yml`
  (tag → tarball + SHA256SUMS + GitHub release), and `tools/content.sh`
  local shims.
