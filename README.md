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
| `scenarios/` | One YAML per scenario under `<Series>/` (series `A`–`G`, `S`, `T`); `scenarios_index.csv` is generated |
| `gen/` | Generation specs (`specs/*.yaml`) and templates (`templates/`); `gen_specs_index.csv` is generated |
| `emails/` | `emails_index.csv`, frozen bodies (`frozen/<series>.jsonl`), hand-written anchors (`handwritten/*.md`) |
| `attachments/` | `manifest.csv` plus `synthetic/`, `offtaxonomy/`, `adversarial/` fixture files |
| `relations/` | `relations_truth.csv`, `dataset_relation_map.csv` |
| `adversary/` | Sandbox-only attack fixtures: `lookalike_domains.csv`, `impostor_personas.csv`. **Never compiled into the registry.** |
| `email/` | Email infrastructure config: sender pool, overlay contract, AgentMail, Gmail sandbox, recipient policy |
| `taxonomy/` | `strata.csv` (document classes × strata); `coverage.csv` is generated |
| `smoke/` | Smoke-set fixtures (the smallest runnable pack) |
| `dist/` | Generated at validation time (`registry.yaml`); gitignored, never committed |
| `tools/` | `validate.py` (content CI), `content.sh` (thin local shims), `brand_allowlist.txt` (leak-scan allowlist) |
| `.github/workflows/` | `content-ci.yml` (PR/main validation), `release.yml` (tag → tarball + GitHub release) |

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

1. Land content changes on `main` (content-ci green).
2. Bump `version` in `content.json` (semver) in its own PR.
3. Push a tag `vX.Y.Z`. That is the only trigger for a release.
4. `.github/workflows/release.yml` runs `tools/validate.py`; on success it
   builds `mailroom-sandbox-content-<tag>.tar.zst` (excluding `dist/`, `.git`,
   `.github`), writes `SHA256SUMS` over the tarball and `content.json`, and
   creates a GitHub release attaching all three.
5. Consumers move with `mailroom sandbox content bump --tag vX.Y.Z` in
   mailroom-reloaded, which refreshes `sandbox/content.lock`.

## Contributing

- **One agent owns one series.** Pick up a series directory under
  `scenarios/` and own its scenarios end to end (spec → timeline → frozen
  emails → attachments). Coordinate cross-series changes in the PR.
- **Validate before you PR.** Run `python3 tools/validate.py` from the repo
  root, or `tools/content.sh validate` if you don't have mailroom-reloaded
  installed. content-ci runs the same validator: ERRORs fail the build,
  WARNs don't.
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
