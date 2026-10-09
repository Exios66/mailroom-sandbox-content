# mailroom-sandbox-content

Synthetic clients, scenarios, emails, manifests, and email-infrastructure
config for the **mailroom-reloaded** testing sandbox — the fixtures the
**Correspondent** (external-communications agent) exercises against.

This repo is the *content pack*; it is being built out **before** the full
mailroom-reloaded plan, and mailroom-reloaded consumes it as a pinned,
versioned dependency. Nothing here runs the sandbox itself — it only
describes the world the sandbox pretends to live in.

The content contract lives in [`CONTENT_SPEC.md`](CONTENT_SPEC.md).
Release history lives in [`CHANGELOG.md`](CHANGELOG.md).

## Directory layout

| Path | What lives there |
|---|---|
| `content.json` | Pack identity: name, semver version, `schema_version`, `dataset_revision`, `min_code_version` / `max_code_version` |
| `schemas/` | JSON Schemas for every content file (`content_files.json`, `registry.v1.json`, `scenario.v2.json`, `gen_spec.v1.json`, `overlay.v1.json`, `persona_behavior.v1.json`) |
| `clients/` | Client registry sources: `clients.csv`, `client_contacts.csv`, `client_domains.csv`, `client_doc_mix.csv` |
| `personas/` | `personas.csv` plus `behavior/<persona_id>.yaml` persona behavior files |
| `scenarios/` | One YAML per scenario under `<Series>/` (series `A`–`H`, `S`, `T`; `H` is the held-out batch, see the consumer's `docs/HELD_OUT_SCENARIOS.md`); `scenarios_index.csv` is generated |
| `gen/` | Generation specs (`specs/*.yaml`), inbound message templates (`templates/*.j2`, every scenario message renders from one) and expected Correspondent replies (`templates/replies/`) |
| `emails/` | `emails_index.csv`, frozen bodies (`frozen/<series>.jsonl`), hand-written anchors (`handwritten/*.md`) |
| `attachments/` | `manifest.csv` plus `synthetic/`, `offtaxonomy/`, `adversarial/` fixture files |
| `relations/` | `relations_truth.csv`, `dataset_relation_map.csv` |
| `adversary/` | Sandbox-only attack fixtures: `lookalike_domains.csv`, `impostor_personas.csv`. **Never compiled into the registry.** |
| `email/` | Email infrastructure config: sender pool, overlay contract, AgentMail, Gmail sandbox, recipient policy, ingress metering policy, scheduled-send contract |
| `protocol/` | Correspondent↔Boss interaction protocol, delegation matrix, and metered-operations runtime contract (ingress metering, scheduled sending, doom-loop guards, separate-process topology) |
| `taxonomy/` | `strata.csv` (**generated** from mailroom-reloaded's subclass catalogue by `tools/sync_strata.py`), `strata.source.json` (its provenance), `offtaxonomy.csv` (off-taxonomy kinds), `migrations/` (audit trail of stratum renames) |
| `smoke/` | The pinned smoke subset; `tools/export_smoke.py` exports it for `sandbox/fixtures/smoke/` ([smoke/README.md](smoke/README.md)) |
| `ids/` | `ranges.yaml`: ID blocks per workstream so parallel agents never collide |
| `dist/` | Generated at validation time (`registry.yaml`); gitignored, shipped inside the release bundle |
| `tools/` | `ci.sh` (content-ci, local), `release.sh` + `build_bundle.py` (local release), `install-hooks.sh`, `validate.py`, `sync_strata.py`, `gen_coverage_scenarios.py`, `export_smoke.py`, `build_attachments.py` (dataset join), `make_fixture_pdf.py`, `content.sh` (local shims); see CONTENT_SPEC §10 |
| `docs/` | `IMPLEMENTATION_PLAN.md`: audit, design decisions (CD1–CD18) and phases for this repo |
| `.githooks/` | `pre-push`: runs `tools/ci.sh` before every push (install with `tools/install-hooks.sh`). **This repo does not use GitHub Actions**; all checks and releases run locally. |

## How mailroom-reloaded consumes this repo

mailroom-reloaded pins a content bundle in `sandbox/content.lock`, which
records four things: **repo**, **tag**, **commit**, and the **bundle sha256**.
A bundle is never consumed from a branch tip — only from a tagged release.

From inside the mailroom-reloaded repo:

| Command | Effect |
|---|---|
| `mailroom sandbox content pull` | Fetch the pinned bundle (verifies sha256 against the lock) |
| `mailroom sandbox content validate` | Run this repo's `tools/validate.py` against the pulled bundle |
| `mailroom sandbox content build` | Compile `dist/registry.yaml` and derived indexes for a sandbox run |
| `mailroom sandbox content bump --tag vX.Y.Z` | Re-pin the lock to a new released tag (updates tag, commit, sha256) |
| `mailroom sandbox content status` | Show the pinned tag/commit/sha256 and whether the local bundle matches |

The Correspondent reads the **compiled registry** (`dist/registry.yaml`):
verified domains and addresses, callback contact/phone, reference formats,
usual channels, and class-level document mix. The registry never contains
lookalike domains, impostor personas, or scenario labels — the validator
fails the build if any adversary material leaks in.

## Release flow

Releases are cut locally; GitHub Actions is not used.

1. Land content changes on `main` with `tools/ci.sh` passing.
2. Bump `version` in `content.json` (semver) in its own PR.
3. On a clean `main`, run `tools/release.sh`. It runs `tools/ci.sh`, builds
   `release/mailroom-sandbox-content-vX.Y.Z.tar.zst` with
   `tools/build_bundle.py --release` (deterministic: tracked files plus the
   compiled `dist/registry.yaml`; same commit and same pinned `zstandard`,
   same sha256), writes `SHA256SUMS` over the tarball and `content.json`
   plus `BUILD_INFO` (zstandard version and `tar_sha256`, the digest of the
   uncompressed tar), and creates the annotated tag `vX.Y.Z` locally. The
   compressed bytes change with the `zstandard` version, so `--release`
   refuses any version but the one in `tools/requirements.txt`.
4. `tools/release.sh --push` also pushes the tag and, if the `gh` CLI is
   logged in, creates the GitHub release with the four files. Without
   `gh`, push the tag and attach `release/*` to a release by hand.
5. A downloader verifies the **published asset's bytes** against
   `sandbox/content.lock`; a local rebuild is an audit (compare `tar_sha256`
   in `BUILD_INFO` if the compressor version differs).
6. Consumers move with `mailroom sandbox content bump --tag vX.Y.Z` in
   mailroom-reloaded, which refreshes `sandbox/content.lock`.

## Contributing

- **One agent owns one series.** Pick up a series directory under
  `scenarios/` and own its scenarios end to end (spec → timeline → frozen
  emails → attachments). Coordinate cross-series changes in the PR.
- **Run content-ci locally before you PR.** `pip install -r
  tools/requirements.txt`, then `tools/ci.sh` from the repo root (validator with
  strict coverage, unit tests, generated-file checks, strata drift). There
  is no hosted CI: run `tools/install-hooks.sh` once so it runs on every
  `git push`. ERRORs fail; WARNs don't. Reviewers should not merge a PR
  whose author has not run it.
- **Never hand-edit generated files** (`taxonomy/strata.csv`, the
  `A13`–`A17` coverage scenarios, `scenarios_index.csv`, the smoke
  `documents` block). Re-run their generator; CI diffs them.
- **Mint IDs inside your block** in `ids/ranges.yaml`.
- Read [`CONTENT_SPEC.md`](CONTENT_SPEC.md) before adding files — ID
  conventions, formats, and the registry/adversary separation are enforced
  by CI, not by convention.
- Reviews are routed by `CODEOWNERS` (currently all `@Exios66`); per-directory
  delegation notes there mark where series ownership will land.

## Data-handling notes

- **Everything here is synthetic and fictional.** No real client names, no
  real people, no real companies.
- **All domains are `*.sandbox.invalid`.** Never a resolvable domain.
- **All phone numbers are `+1-555-01xx`.** The validator errors on anything
  else.
- **No real brand names** anywhere in content (CI leak scan).
- **Dataset bytes are never redistributed.** Attachments sourced from the
  dataset are referenced by `dataset_revision` + `dataset_filename` in
  `attachments/manifest.csv` only; no dataset content is committed here.
- **The `correspondence` document class is attachable but never a prompt
  input.** Correspondence fixtures may be attached to messages; they are
  never fed into generation prompts.
- **`adversary/` is sandbox-only.** Lookalike domains and impostor personas
  exist so the sandbox can test defenses; they are never compiled into the
  registry the Correspondent reads.
