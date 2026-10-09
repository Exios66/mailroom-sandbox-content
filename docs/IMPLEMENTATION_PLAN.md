> **Historical (2026-10-09).** The single live plan for both repositories is
> `docs/superpowers/plans/2026-10-09-mailroom-core-plan.md` in
> `Exios66/mailroom-reloaded`. It carries this repo's remaining work (Phase 4,
> X-01, X-03) and the file-placement rules (section 1.2). This file is kept
> for the audit and the design decisions CD1-CD19; do not add phases here.

# Implementation plan — mailroom-sandbox-content

- **Date:** 2026-10-08
- **Implements:** Addendum v2 (Sandbox Content Pack) §2–§6, §12.3–§12.6, §13 — the **content workstreams C1–C12**. The core plan v1.1 still governs (§6.4–§6.7, §8.3).
- **Out of scope here:** code workstreams M0–M13 in `mailroom-reloaded`. This plan lists only the contract points they must match (§6).
- **Starting point:** open PR #1 (`content/v0.1-seed`, 241 files, validator at 0 errors and 44 warnings).

---

## 1. Audit of PR #1 against the addendum

| # | Area | Finding | Severity |
|---|---|---|---|
| A1 | `taxonomy/strata.csv` | **Typed by hand, and wrong.** The addendum (§2.1) requires strata to be generated, never typed. The contract "strata" are CUAD *clause/field labels* (`parties`, `governing_law`, `cap_on_liability`…), not the 25 CUAD contract families. The merger strata (`asset_purchase`, `tender_offer`, `merger_of_equals`) and correspondence strata (`thread`, `forwarded`, `inquiry`, `cover_note`) do not exist in the dataset. Row counts are uniform placeholders (24, 45, 125…). | **Blocker** |
| A2 | Stratum references | **50 references** in `client_doc_mix.csv` (39), scenarios (9) and `attachments/manifest.csv` (4) point at those non-existent strata. | **Blocker** |
| A3 | `schemas/*.json` | Present, but `tools/validate.py` never loads them: all checks are hand-rolled and `jsonschema` is not a CI dependency. The schemas and the validator can drift without anyone noticing. | High |
| A4 | Scenario shape | `attach:` sits beside `client:` on timeline events. Addendum §4.8 nests it under `client:`. M0's acceptance test is "schemas validate the worked examples in §4", so the content has to match. | High |
| A5 | `content.json` | `dataset_revision: "v9"` is a family name, not a pin. The main repo pins `ed7576b6` (`eval/dataset.py: DEFAULT_REVISION`). | Medium |
| A6 | Scope additions | The **G-series** (12 "production-adjacent" scenarios) and **`protocol/`** (Correspondent↔Boss protocol, delegation matrix, metered operations) are not in the addendum. The G-series also uses a series letter that M0's enum will not include. | Needs decision |
| A7 | Coverage | Coverage gaps are warnings. §2.4 says an unreachable stratum **fails** the build. | Medium (becomes an error at v0.5) |
| A8 | `attachments/manifest.csv` | Contains a blank line. Off-taxonomy rows use `class=off_taxonomy, stratum=other`; that convention should be written into the spec. | Low |
| A9 | Repo visibility | The repo is **public**. §13.4 says private. | Needs owner |
| A10 | Review threads | 12 of 14 threads are confirmed addressed. I re-checked the other two (F-series verified domains, C4 quarantine binding): both are fixed on the branch. | OK |

**Verified source of truth for strata.** `mailroom-reloaded/src/mailroom_reloaded/scoring/corpus.py` has two tables. `DOC_TYPE_SUBCLASSES` is the live catalog. `CORPUS_SUBCLASS_SURFACES` is the set observed in the dataset's ground truth. Together they give:

- contract: 25 CUAD families
- merger_agreement: 5 MAUD consideration types
- corporate_record: 10 observed, 11 in the live catalog (adds `certificate_of_formation`). This matches the addendum's "10 vs 11" note exactly.
- correspondence: 8 forms, plus an `other` bucket
- insurance_claim: 6 lines

Hugging Face is blocked by this environment's network policy, so per-stratum **row counts** cannot be read from here (see §5).

---

## 2. Design decisions (I propose these; flag any you disagree with)

| ID | Decision | Rationale |
|---|---|---|
| CD1 | **Build on the merged seed** (PR #1, now on `main`): fix it on a follow-up branch. Don't start over. | Most of the content is sound and already reviewed. The defects are mechanical to fix. |
| CD2 | **Strata are generated** by `tools/sync_strata.py --from <mailroom-reloaded checkout>`. The script reads `scoring/corpus.py` at a pinned tag and writes `taxonomy/strata.csv` plus `taxonomy/strata.source.json` (repo, tag, commit, sha256). Hand edits fail CI (a regenerate-and-diff check). | §2.1 "never typed by hand". The main repo's catalog is the same vocabulary the pipeline scores against. |
| CD3 | `in_ground_truth` comes from `CORPUS_SUBCLASS_SURFACES` (after normalization). `in_live_catalog` comes from `DOC_TYPE_SUBCLASSES`. **Coverage floors apply only to `in_ground_truth=true` strata.** A stratum that exists only in the catalog (e.g. `certificate_of_formation`) cannot be backed by a real dataset attachment. | Attachments are dataset documents (§5). You cannot draw from a stratum with zero rows. |
| CD4 | The `rows` column is left blank, with `status=rows_unverified`, until a dataset scan fills it (§5 blocker B1). No invented numbers. | The current numbers are fabricated. |
| CD5 | **Migrate all 50 bad references** with an explicit mapping table (`taxonomy/migrations/0001_strata.csv`). Client mixes are re-weighted to the client descriptions in §2.2, and weights stay summing to 1.0. | Keeps the edit reviewable and reproducible. |
| CD6 | **The validator enforces the JSON Schemas** (`jsonschema` added to CI). Hand-rolled checks stay only for cross-file rules that a schema cannot express (references, sha256 values, leak scan, coverage). | One normative source (A3). |
| CD7 | **Scenario shape follows §4.8.** Message attachments go under `client.attach`. A pipeline drop that is not an email is `ingress: {doc \| class+stratum}`. All 83 scenarios are migrated by script. | M0 will validate the §4 worked examples; the content has to pass the same schema. |
| CD8 | **Schemas are owned by M0 in `mailroom-reloaded`** (§12.1, §13.3). Until M0 lands, `schemas/` here is the **draft** M0 will adopt. After that, it becomes a generated mirror, and CI checks it against the main repo's tag in `content.json → min_code_version`. | Contracts first, one owner. It also avoids blocking content work on M0. |
| CD9 | `content.json.dataset_revision` is set to the commit pin `ed7576b6`, train split only. Every manifest row carries the revision. | Reproducibility. The main repo pins the same revision. |
| CD10 | Off-taxonomy attachments use `class=off_taxonomy`, `in_taxonomy=false`, and a **descriptive stratum** (`certificate_of_insurance`, `wire_instructions`, `payoff_letter`, `regulator_notice`, `inventory_sheet`, `phone_photo`, `court_notice`). They are listed in `taxonomy/offtaxonomy.csv`, which is hand-maintained because these types are not dataset strata. | Lets §8.4 report over-blocking per off-taxonomy kind. Today they are all `other`. |
| CD11 | **Coverage becomes an ERROR** at v0.5 for `in_ground_truth` strata: each needs at least one plausible client sender **and** at least one scenario attachment spec. At v0.1 it stays a WARN. | §2.4, phased so v0.1 can merge. |
| CD12 | Coverage is reached with **one `coverage`-profile scenario per class**, `X_coverage_<class>` under series A. Each one enumerates every stratum of its class as benign submissions from plausible senders. This is in addition to topical scenarios. | Reaches all 54 GT strata without dozens of thin scenarios. It is also what the `coverage` profile needs. |
| CD13 | **The smoke subset is pinned** in `smoke/smoke_set.yaml` (6 scenarios, ~12 docs, ≤ 2 MB, `gen: scripted`). It is exported by `tools/export_smoke.py` into the exact layout M6 expects at `sandbox/fixtures/smoke/`. | §2.4, §13.1. |
| CD14 | **ID ranges are allocated** in `ids/ranges.yaml`, per agent and per series (specs, emails, attachments, relations). CI rejects IDs outside a declared range. | §12.5: avoids collisions between parallel agents. |
| CD15 | **No dataset bytes are committed.** In-taxonomy attachments are manifest rows (`dataset_filename`, `dataset_revision`, `sha256`/`doc_id` *after* degradation). The bytes are joined at bundle build on a machine that has the dataset cache. Only synthetic, off-taxonomy and adversarial blobs live in git. | §5, §13.5 licensing. |
| CD16 | **Frozen emails are produced only by the M9 generation layer** (`mailroom sandbox content build`). Until then, every email is `tier=scripted` and `model_id=template`. No hand-written text gets labeled `frozen`. | §6.3 "never hand-patched"; provenance has to be honest. |
| CD17 | `tools/` stays a **standalone stdlib + PyYAML + jsonschema** toolchain until M6 ships `mailroom sandbox content validate`. After that, `tools/` becomes the thin wrappers §13.2 describes. | Content agents can work now without installing the main repo. |

---

## 3. Target layout (changes from PR #1)

```
content.json                 # dataset_revision → ed7576b6 (CD9)
taxonomy/strata.csv          # GENERATED (CD2)
taxonomy/strata.source.json  # NEW: provenance of the generated roster
taxonomy/offtaxonomy.csv     # NEW: off-taxonomy kinds (CD10)
taxonomy/migrations/0001_strata.csv   # NEW: old→new stratum map (CD5)
taxonomy/coverage.csv        # GENERATED (already planned)
ids/ranges.yaml              # NEW (CD14)
scenarios/A/A13..A17_coverage_<class>.yaml   # NEW at v0.5 (CD12)
dist/registry.yaml           # build artifact, gitignored; built in CI + release
tools/sync_strata.py         # NEW
tools/migrate_scenarios_v2.py  # NEW, one-shot (CD7); kept for audit
tools/export_smoke.py        # NEW (CD13)
tools/build_attachments.py   # NEW, dev-machine only (needs dataset cache) (CD15)
tools/validate.py            # + jsonschema, verified-sender check, range check, coverage-as-error flag
docs/IMPLEMENTATION_PLAN.md  # this file
```

---

## 4. Phases and work packages

### Phase 1: v0.1.0 corrective (on PR #1). No external dependencies.

| WP | Content WS | Work | Acceptance |
|---|---|---|---|
| 1.1 | C2 | `sync_strata.py`, then regenerate `strata.csv` and `strata.source.json` | Roster equals `corpus.py` at v0.2.0. Regenerating produces an identical file. |
| 1.2 | C1/C2 | Migration table, then rewrite `client_doc_mix.csv`; re-weight to §2.2 | 0 invalid strata; each client sums to 1.0; class-level sums match §2.2 (e.g. harlowpryce contract 0.40 / merger 0.25 / corp 0.25 / corr 0.10) |
| 1.3 | C4–C6 | Fix stratum refs in scenarios; run `migrate_scenarios_v2.py` (CD7) | All 83 scenarios validate against `scenario.v2.json` |
| 1.4 | C9 | Manifest: fix contract strata on att_0001–0004, off-taxonomy strata (CD10), remove the blank line | sha256 and doc_id still verify |
| 1.5 | C11 | Validator: jsonschema everywhere; verified-sender ⇒ registered domain; `quarantine`/`soft_hold` entries resolve to a timeline attachment; ID-range check; `--strict-coverage` flag | 0 errors; deliberately broken fixtures in `tools/tests/` fail as expected |
| 1.6 | C11 | `tools/tests/` with a pytest suite for the validator; CI adds `jsonschema` and runs pytest | CI green |
| 1.7 | — | `content.json` revision pin; CONTENT_SPEC §3 transcribes the series definitions from the addendum and removes the resolved `[verify]` items; CHANGELOG | Docs match the files |
| 1.8 | — | Merge PR #1, tag `v0.1.0`, release bundle (tar.zst, SHA256SUMS, content.json) | `sha256sum -c` passes on the downloaded assets |

### Phase 2: v0.5.0 (B, C, D final; coverage closed). No external dependencies.

| WP | WS | Work | Acceptance |
|---|---|---|---|
| 2.1 | C2 | Client mixes extended so every GT stratum has at least one plausible sender (generated `coverage.csv`) | 0 unreachable strata |
| 2.2 | C4/C12 | Coverage scenarios A13–A17 (CD12) | Every GT stratum has at least one scenario attachment spec; `--strict-coverage` on by default |
| 2.3 | C3 | Persona behavior files validated by schema; reply templates parse (Jinja2 syntax check in CI) | All templates render with a fixture context |
| 2.4 | C4/C5 | B, C, D reviewed against §3 expected outcomes, with `status: review → frozen` | Each scenario's `expect` matches its §3 row (checklist in PR) |
| 2.5 | — | `export_smoke.py` plus registry build in the release | Smoke export ≤ 2 MB, loads with zero network (verified once M6 exists) |
| 2.6 | — | Tag `v0.5.0` | Release assets verify |

### Phase 3: v1.0.0 (blocked on externals; see §5)

| WP | WS | Needs | Work |
|---|---|---|---|
| 3.1 | C9 | B1 (dataset access) | `build_attachments.py`: join `ground_truth` on filename, train split, sample per client mix, run the seeded degradation pass, record post-degradation sha256/doc_id; fill `strata.csv.rows` |
| 3.2 | C10 | B1 | `relations_truth.csv` from the dataset's `relationships`/`related_document_ids`/`bundles`; `dataset_relation_map.csv` (verify the vocabulary first) |
| 3.3 | C7/C8 | M9 merged, plus B2 | Frozen build per series through `mailroom sandbox content build`; `emails_index.csv` provenance complete |
| 3.4 | C6 | — | E, S, T finalized; every attack class covered; adversary absent from the registry (already checked) |
| 3.5 | C12 | M9 loop mode | Review log for promoted evasions |
| 3.6 | — | — | Tag `v1.0.0`; `sandbox-nightly` runs against it |

---

## 5. External blockers (owner action)

| ID | Blocker | Blocks | Options |
|---|---|---|---|
| B1 | Hugging Face is blocked in this cloud environment (CONNECT 403) | 3.1, 3.2, strata row counts | (a) allow `huggingface.co` and `cdn-lfs*.huggingface.co` in the environment's network policy; (b) you run `tools/build_attachments.py` locally; (c) defer to v1.0 |
| B2 | OpenRouter generator key and the $10 credit (§6.4) | 3.3 | Owner purchase; key only in the `sandbox-live` environment secret |
| B3 | Repo visibility (public, but the plan says private) | Release distribution of any dataset-derived bytes | Owner setting |
| B4 | Dataset licensing for bundles that embed dataset bytes (§13.5) | 3.1 release | Owner/legal decision. Until then, bundles carry manifests only |

---

## 6. Cross-repo contract points (what M0/M6 in `mailroom-reloaded` must match)

1. `scenario/v2` shape per CD7 (`client.attach`, `ingress`), with enums from §8.1–§8.3 (+ G if kept).
2. `strata.csv` columns `class,stratum,in_ground_truth,in_live_catalog,rows,status`; the roster comes from `scoring/corpus.py`.
3. `content.lock` fields: `repo, tag, commit, bundle_sha256, schema_version, dataset_revision`.
4. Smoke fixture layout produced by `export_smoke.py` (CD13).
5. Registry `mailroom.comm.registry/v1`: class-level mix only; no adversary data, labels or scenario ids.
6. Overlay `mailroom.overlay/v1`: wire-visible fields only, `additionalProperties: false`.
7. Off-taxonomy convention (CD10).

---

## 7. Owner decisions (2026-10-08)

| Q | Decision |
|---|---|
| G-series + `protocol/` | **Keep**, recorded as amendment **AM1** in CONTENT_SPEC §11. M0 must add `G` to the series enum. |
| Dataset access (B1) | Owner will allow `huggingface.co` in the cloud environment network policy. Phase 3 (WP 3.1/3.2) runs in a session where that is in effect; `tools/build_attachments.py` is written now. |
| Schemas | Build the helper repo out fully here: `schemas/` in this repo is the enforced contract (CD8). M0 adopts it; drift checks come later. |
| Scope | Phase 1 + Phase 2 in this session. PR #1 merged to `main` before work began, so Phase 1 lands as a follow-up branch instead of on PR #1. |

---

## 8. Status (2026-10-08, end of session)

| Phase / WP | State | Notes |
|---|---|---|
| 1.1 strata generated | done | 56 catalog / 54 ground truth; `strata-drift` CI job |
| 1.2 client mixes | done | all 54 ground-truth strata reachable |
| 1.3 scenario v2 shape | done | plus CD18 (template on every message) and refs/endpoints (AM2); found and fixed reversed relations, unbound ingress docs, 96 body-less messages |
| 1.4 manifest | done | off-taxonomy kinds; 4 new synthetic fixtures |
| 1.5–1.6 validator + tests | done | all schemas enforced, ID ranges, 117 tests |
| 1.7 docs, revision pin | done | CONTENT_SPEC rewritten; `ed7576b6` |
| 1.8 tag | **not done** | 0.1.0 merged untagged; after this branch merges, run `tools/release.sh --push` on main to cut v0.5.0 |
| 2.1–2.2 coverage | done | A13–A17 generated; `--strict-coverage` in CI |
| 2.3 templates/personas | done | every message renders under StrictUndefined |
| 2.4 B/C/D review | done (agent) | `status: review`; promotion to `frozen` needs a human reviewer |
| 2.5 smoke export | done | 6 scenarios, 6 docs, ~30 KB |
| 3.1 dataset join | tooling done | run `tools/build_attachments.py --hf --counts --select 3` where huggingface.co is allowed |
| 3.2 relation truth from dataset | open | needs 3.1; verify the dataset's relationship vocabulary first |
| 3.3 frozen emails | open | needs M9 + OpenRouter key; 32 scenarios await gen specs (C7) |
| 3.4–3.6 | open | |

Additional decision taken during implementation:

| ID | Decision |
|---|---|
| CD19 | **No GitHub Actions** (owner's Actions are locked). content-ci is `tools/ci.sh`, run locally and as the versioned pre-push hook (`.githooks/`, `tools/install-hooks.sh`); releases are cut by `tools/release.sh` with a deterministic bundle (`tools/build_bundle.py`). `.github/workflows/` removed. Main-repo items that assumed hosted CI (addendum §11.6 `sandbox-smoke` / `sandbox-nightly` / `content-ci`) need the same treatment there. |
| CD18 | Every client message names a `template` (scripted body and fallback); `gen_spec` is optional. Templates render `Subject:` first; variables come from `vars` plus the standard sender context (CONTENT_SPEC §4.3). Correspondent reply shapes live in `gen/templates/replies/`. |
