> **Historical (2026-10-09).** The single live plan for both repositories is
> [Mailroom Core Plan](https://github.com/Exios66/mailroom-reloaded/blob/main/docs/superpowers/plans/2026-10-09-mailroom-core-plan.md) in
> `Exios66/mailroom-reloaded`. It carries this repo's remaining work (Phase 4,
> X-01, X-03) and the file-placement rules (section 1.2). This file is kept
> for the audit and the design decisions CD1-CD19; do not add phases here.
>
> **Schema ownership (superseded).** The CD8 and "Schemas" entries below predate
> the change: mailroom-reloaded owns the contract and this repo's shared schemas
> are byte-for-byte mirrors of it (`tools/check_schema_drift.py`).

# Implementation plan — mailroom-sandbox-content

- **Date:** 2026-10-08 (status refreshed 2026-10-10: see section 8)
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

| WP | Content WS | Work | Acceptance | Status (2026-10-10) |
|---|---|---|---|---|
| 1.1 | C2 | `sync_strata.py`, then regenerate `strata.csv` and `strata.source.json` | Roster equals `corpus.py` at v0.2.0. Regenerating produces an identical file. | DONE. `tools/sync_strata.py` and `strata.source.json` on main; `strata-drift` step in `tools/ci.sh` (drift run not repeated 2026-10-10). |
| 1.2 | C1/C2 | Migration table, then rewrite `client_doc_mix.csv`; re-weight to §2.2 | 0 invalid strata; each client sums to 1.0; class-level sums match §2.2 (e.g. harlowpryce contract 0.40 / merger 0.25 / corp 0.25 / corr 0.10) | DONE (2026-10-08 status). Validator 0 errors on 2026-10-10. |
| 1.3 | C4–C6 | Fix stratum refs in scenarios; run `migrate_scenarios_v2.py` (CD7) | All 83 scenarios validate against `scenario.v2.json` | DONE. `scenario.v2` enforced; 116 scenarios validate with 0 errors (2026-10-10). |
| 1.4 | C9 | Manifest: fix contract strata on att_0001–0004, off-taxonomy strata (CD10), remove the blank line | sha256 and doc_id still verify | DONE (2026-10-08 status); manifest not re-checked 2026-10-10. |
| 1.5 | C11 | Validator: jsonschema everywhere; verified-sender ⇒ registered domain; `quarantine`/`soft_hold` entries resolve to a timeline attachment; ID-range check; `--strict-coverage` flag | 0 errors; deliberately broken fixtures in `tools/tests/` fail as expected | DONE. Strict CSV/YAML reader and outer guard in `tools/validate.py` (f1354ba, merged via PR #7). |
| 1.6 | C11 | `tools/tests/` with a pytest suite for the validator; CI adds `jsonschema` and runs pytest | CI green | DONE. 8 test modules in `tests/`; `tools/ci.sh` runs unittest (not re-run 2026-10-10). |
| 1.7 | — | `content.json` revision pin; CONTENT_SPEC §3 transcribes the series definitions from the addendum and removes the resolved `[verify]` items; CHANGELOG | Docs match the files | DONE. `content.json`: `dataset_revision` ed7576b6, version 0.5.0; CONTENT_SPEC rewritten (2026-10-08). |
| 1.8 | — | Merge PR #1, tag `v0.1.0`, release bundle (tar.zst, SHA256SUMS, content.json) | `sha256sum -c` passes on the downloaded assets | DONE for v0.5.0 (the first tag; no v0.1.0 tag exists). Tag at f650cfd; GitHub release published 2026-10-09; bundle sha256 matches `content.lock` (verified by download 2026-10-10). Release has no BUILD_INFO asset (cut before K-01). |

### Phase 2: v0.5.0 (B, C, D final; coverage closed). No external dependencies.

| WP | WS | Work | Acceptance | Status (2026-10-10) |
|---|---|---|---|---|
| 2.1 | C2 | Client mixes extended so every GT stratum has at least one plausible sender (generated `coverage.csv`) | 0 unreachable strata | DONE (2026-10-08 status). `--strict-coverage`: 0 errors on 2026-10-10. |
| 2.2 | C4/C12 | Coverage scenarios A13–A17 (CD12) | Every GT stratum has at least one scenario attachment spec; `--strict-coverage` on by default | DONE. A13-A17 present under `scenarios/A/` (17 A-series files). |
| 2.3 | C3 | Persona behavior files validated by schema; reply templates parse (Jinja2 syntax check in CI) | All templates render with a fixture context | DONE (2026-10-08 status). |
| 2.4 | C4/C5 | B, C, D reviewed against §3 expected outcomes, with `status: review → frozen` | Each scenario's `expect` matches its §3 row (checklist in PR) | PARTIAL. Agent review done; all scenarios still `review`/`draft` (0 frozen; promotion is C-05). Open expectation conflicts remain (K-03; content issues #8-#10). |
| 2.5 | — | `export_smoke.py` plus registry build in the release | Smoke export ≤ 2 MB, loads with zero network (verified once M6 exists) | DONE. `tools/export_smoke.py --check` runs in `tools/ci.sh`; size and zero-network load not re-measured 2026-10-10. |
| 2.6 | — | Tag `v0.5.0` | Release assets verify | DONE. Tag v0.5.0 and release assets verified 2026-10-10 (see 1.8). |

### Phase 3: v1.0.0 (blocked on externals; see §5)

| WP | WS | Needs | Work | Status (2026-10-10) |
|---|---|---|---|---|
| 3.1 | C9 | B1 (dataset access) | `build_attachments.py`: join `ground_truth` on filename, train split, sample per client mix, run the seeded degradation pass, record post-degradation sha256/doc_id; fill `strata.csv.rows` | BLOCKED (B1). `tools/build_attachments.py` exists; huggingface.co unreachable from this session on 2026-10-10; 54 `rows_unverified` rows remain. |
| 3.2 | C10 | B1 | `relations_truth.csv` from the dataset's `relationships`/`related_document_ids`/`bundles`; `dataset_relation_map.csv` (verify the vocabulary first) | BLOCKED. Needs 3.1 (C-02). |
| 3.3 | C7/C8 | M9 merged, plus B2 | Frozen build per series through `mailroom sandbox content build`; `emails_index.csv` provenance complete | BLOCKED (B2, owner OpenRouter key). Reloaded M9 state not verified here. |
| 3.4 | C6 | — | E, S, T finalized; every attack class covered; adversary absent from the registry (already checked) | PARTIAL. E 13, S 10, T 6 scenario files exist; attack-class coverage and review log not verified (C-04). |
| 3.5 | C12 | M9 loop mode | Review log for promoted evasions | OPEN. No review log for promoted evasions verified (C-04/C-05 scope). |
| 3.6 | — | — | Tag `v1.0.0`; `sandbox-nightly` runs against it | OPEN. Needs 3.1-3.5. No v1.0.0 tag. No nightly run configured (CD19: no GitHub Actions). |

---

## 5. External blockers (owner action)

Refreshed 2026-10-10. "Verified" means checked from this session on that date.

| ID | Blocker | Status (2026-10-10) | Blocks | Options / owner |
|---|---|---|---|---|
| B1 | Hugging Face is not reachable from this cloud session. Probe: `curl https://huggingface.co/api/datasets/Lucius-Morningstar/mailroom-dataset` gave no HTTP response (code 000). The 2026-10-08 note cited CONNECT 403. The owner's planned allow-listing (section 7) is not in effect here. | **BLOCKED** (verified) | 3.1, 3.2, C-01, C-02, strata row counts | (a) allow `huggingface.co` and `cdn-lfs*.huggingface.co` in the environment network policy; (b) owner runs `tools/build_attachments.py` locally; (c) defer to v1.0. Owner. |
| B2 | OpenRouter generator key and the $10 credit (section 6.4) | **OPEN**, not checked (unverified whether a key exists). The key must never be written into the repo, a log or a PR. | 3.3, C-03 | Owner purchase; key only in the `sandbox-live` environment secret. Owner. |
| B3 | Repo visibility. `Exios66/mailroom-sandbox-content` is **public** (GitHub API, 2026-10-10), and the v0.5.0 release is already published on it. The plan (section 13.4) says private. | **OPEN** (verified) | Any release that contains dataset-derived bytes; the plan's distribution rule | Owner setting: make private, or record that public is acceptable. Owner. |
| B4 | Dataset licensing for bundles that embed dataset bytes (section 13.5). The contents of the published v0.5.0 bundle were not inspected (no zstd tool or `zstandard` module in this session). | **OPEN** (unverified contents) | 3.1 release | Owner/legal decision. Until then bundles carry manifests only. |
| B5 | Session tooling: `gh` GraphQL commands (`gh release view`, `gh release download`) return 403 from Claude Code sessions. REST routes (`gh api repos/...`) work. | **Workaround in use** (verified) | Agent verification of releases and PRs | Use `gh api` REST paths. |

## 6. Cross-repo contract points (what M0/M6 in `mailroom-reloaded` must match)

Status as of 2026-10-10. Reloaded `origin/main` is 7ce8cb7. The reloaded master plan is `docs/superpowers/plans/2026-10-09-mailroom-core-plan.md`.

1. **`scenario/v2` shape** per CD7 (`client.attach`, `ingress`), enums from sections 8.1-8.3 (+ G if kept). **Not in sync:** content `schemas/scenario.v2.json` (sha256 b8b0cb...) differs from reloaded (0949d5...). The content copy has one `"unknown"` relation value that reloaded dropped. `tools/check_schema_drift.py` against the reloaded checkout reports 2 of 6 shared schemas differ (`gen_spec.v1.json`, `scenario.v2.json`). Owner: K-05 (content).
2. **`strata.csv` columns** `class,stratum,in_ground_truth,in_live_catalog,rows,status`; roster comes from `scoring/corpus.py`. Still in sync in shape. Rows: 54 still `rows_unverified`.
3. **`content.lock` fields** `repo, tag, commit, bundle_sha256, schema_version, dataset_revision` (consumer schema is closed, D11). Reloaded lock currently pins `v0.5.0` at `f650cfd`, bundle `7a32e86e...`. **Published v0.5.0 asset matches that sha256** (verified 2026-10-10). The lock's header comment still says the release is "not published yet"; that is stale and goes in the reloaded bump PR. BUILD_INFO (K-01) is a release asset, not a lock field, and v0.5.0 has none.
4. **Smoke fixture layout** produced by `export_smoke.py` (CD13). Generator check runs in `tools/ci.sh`. Consumer-side acceptance (M6) not verified here.
5. **Registry** `mailroom.comm.registry/v1`: class-level mix only; no adversary data, labels or scenario ids. `schemas/registry.v1.json` is byte-identical to reloaded (f71ade05...), verified.
6. **Overlay** `mailroom.overlay/v1`: wire-visible fields only, `additionalProperties: false`. `schemas/overlay.v1.json` is byte-identical to reloaded (5a115da2...), verified.
7. **Off-taxonomy convention** (CD10). Unchanged; reloaded side not re-checked.
8. **Consumer loader gate (K-06).** `tools/ci.sh` step 4 runs `tools/load_with_consumer.py` and `tools/check_schema_drift.py` only when `MAILROOM_RELOADED` is set. Reloaded #44 is merged (`8e8522a`), so the consumer accepts the H-series. The step was not run in this session (no reloaded checkout pinned here).
9. **Relation vocabulary (C-02).** Reloaded `relation_kinds.v1.json` is the reference. Content has no copy of `relation_kinds`, `event_kinds` or `signal_kinds` (reloaded has 9 schema files, content 6). Whether content should mirror the three extra files is open (K-05).
10. **Stale text on the reloaded side** (to fix in reloaded PRs, not here): reloaded plan header table and section 3.4 still say `f650cfd` is unpublished and content PR #5 is open; the content repo description still says "83 scenarios" (now 116 scenarios, 0 errors).

## 7. Owner decisions (2026-10-08)

| Q | Decision |
|---|---|
| G-series + `protocol/` | **Keep**, recorded as amendment **AM1** in CONTENT_SPEC §11. M0 must add `G` to the series enum. |
| Dataset access (B1) | Owner will allow `huggingface.co` in the cloud environment network policy. Phase 3 (WP 3.1/3.2) runs in a session where that is in effect; `tools/build_attachments.py` is written now. |
| Schemas | Build the helper repo out fully here: `schemas/` in this repo is the enforced contract (CD8). M0 adopts it; drift checks come later. |
| Scope | Phase 1 + Phase 2 in this session. PR #1 merged to `main` before work began, so Phase 1 lands as a follow-up branch instead of on PR #1. |

---

## 8. Status (2026-10-10)

Basis: content `origin/main` 58f4fd6 (clean tree); reloaded `origin/main` 7ce8cb7. Verified 2026-10-10: validator `--strict-coverage` (116 scenarios: A17 B8 C11 D6 E13 F5 G12 H28 S10 T6; 0 errors, 1 warning naming 32 scenarios without a `gen_spec`), 54 `rows_unverified` rows in `taxonomy/strata.csv`, schema hashes, tags, release assets, open issues and PRs. Items marked unverified in 8.6 were not checked.

### 8.1 Shipped since 2026-10-08

| Item | Evidence |
|---|---|
| Content pack v0.5.0 merged; the pinned commit | `f650cfd` (merge of content PR #4) |
| Tag `v0.5.0` (annotated, object 98415d7) and GitHub release, published 2026-10-09T20:16Z | `git ls-remote --tags`; REST `releases/tags/v0.5.0` |
| Release assets: `mailroom-sandbox-content-v0.5.0.tar.zst`, `content.json`, `SHA256SUMS`. Bundle sha256 `7a32e86e...` matches `sandbox/content.lock` | Downloaded and hashed 2026-10-10. No BUILD_INFO asset (release predates K-01) |
| H-series (H1-H28) and templates on main; content PRs #5 and #6 | `27acdba`; `67b9a3e` is an ancestor of main; PR state per reloaded plan K-00 |
| Issue forms, PR template, `AGENTS.md` | PR #15, merge `58f4fd6` |
| K-01 pin: `zstandard==0.25.0`; `--release` refuses other versions; BUILD_INFO with `tar_sha256` (code) | `840e4e8` |
| K-02 strict CSV reader, outer guard, fault-injection module and `tests/test_validate_faults.py` (FAST subset) | `f1354ba`, `9f51bc8`, `db392d5`; PR #7 (merge `7706582`) |
| K-03 contradiction lint, strict in CI; decision table (CONTENT_SPEC Appendix A); stage-2 expectation edits (14 submission scenarios, G9, H21, S1-S3, S5-S10) | `517a495`, `bb2178d`, `9eca18a`, `6a076cf`, `802abc4` |
| K-04 drift-fetch failure and release gating | `aeef202`, `168ec8d`, `a03b98d` |
| K-05 partial: drift check and mirror of `persona_behavior` (now matches); `gen_spec` mirror is stale (see 8.2) | `d2f1df5` |
| K-06 consumer-loader step in `tools/ci.sh` (gated on `MAILROOM_RELOADED`) | `5e55719`; `tests/test_load_with_consumer.py` |
| Docstrings for content tools and tests | `d2327c5` |

### 8.2 In progress or partial

| Item | State (2026-10-10) |
|---|---|
| K-01 residuals | Pin, refusal and BUILD_INFO are in code. Missing: `tests/test_build_bundle.py` (no such file); the "verification authority" paragraph is in CHANGELOG but not in CONTENT_SPEC.md. |
| K-02 | Strict reader and guard done. Missing: optional scenario size WARN (no size check in `tools/validate.py`); full fault-injection run as a unittest (tests run a FAST subset). |
| K-03 | Lint and stage-2 done. Not yet applied: B5/H5, B4, D3/D4/D6, the T6 family, F1/H16/H22-H24 priority. Owner rulings still open (content #8, #9, #10). |
| K-05 | Drift check exists and runs in `tools/ci.sh`. It **fails**: `gen_spec.v1.json` and `scenario.v2.json` differ from reloaded `origin/main`. Content `scenario.v2.json` still has one `"unknown"` relation value. |
| X-01 (content side) | v0.5.0 published and matches lock. v0.6.0 not tagged; `content.json` still says 0.5.0. |
| X-01 (reloaded side) | Lock still pins v0.5.0 with the stale "not published" header. Bump PR not made. |
| C-06 | 32 scenarios name a generation mode with no `gen_spec` (validator WARN). |
| C-04 | E, S, T files exist; coverage mapping and review log not produced. |

### 8.3 Remaining work (prioritised checklist)

Tracker column: the draft issues in the agent's scratch folder (drafts 14, 16-22) are **not filed**. The open content issues are #2, #8, #9, #10, #11, #12, #13 and #14 (verified 2026-10-10; closed issues not checked). "Draft n" below means that scratch file.

Priority 1: unblocks the v0.6.0 release and reloaded pin.

- [ ] **K-05 schema mirror.** Copy reloaded `schemas/gen_spec.v1.json` and `scenario.v2.json` from a pinned reloaded commit (never a branch tip); drop `"unknown"`; decide on the three extra reloaded schemas. Evidence: `sha256sum` pairs equal the reloaded copies (`ef3e99dc...`, `0949d535...` at 7ce8cb7); `grep -c '"unknown"' schemas/scenario.v2.json` prints 0; `python3 tools/check_schema_drift.py <reloaded>` exits 0; `MAILROOM_RELOADED=<checkout> tools/ci.sh` passes. Tracker: none filed (Draft 18).
- [ ] **K-01 residuals.** Add `tests/test_build_bundle.py`: two builds give equal sha256; a wrong `zstandard` version is refused under `--release`. Add the verification-authority paragraph to CONTENT_SPEC.md. Evidence: `python3 -m unittest tests.test_build_bundle -v` exit 0; `grep -n "verification authority" CONTENT_SPEC.md`. Tracker: none filed (Draft 16).
- [ ] **K-03 finish.** Apply the remaining rows; record owner rulings in CONTENT_SPEC Appendix A. Evidence: `python3 tools/lint_contradictions.py --strict` exit 0; one decision row per changed scenario. Tracker: content #8, #9, #10.
- [ ] **Release v0.6.0 (content).** After K-05 and K-01 residuals: bump `content.json` to 0.6.0 in its own PR, `tools/release.sh --push` on clean main. Evidence: `gh api repos/Exios66/mailroom-sandbox-content/releases/tags/v0.6.0` lists `BUILD_INFO`, the tar.zst and `SHA256SUMS`; the sha256 is recorded. Owner go-ahead per D2 (approval status unverified). Tracker: content #11. Open question for owner: v0.5.0 has no BUILD_INFO and its tag cannot move; accept that or document it.
- [ ] **Reloaded bump (X-01 reloaded side).** `mailroom sandbox content bump --tag v0.6.0` in a reloaded PR; update the stale lock header. Evidence: `git diff` of `sandbox/content.lock` shows only the bump output; `mailroom sandbox content pull`, `validate` and `mailroom sandbox conformance --content smoke` exit 0 from a clean checkout. Tracker: reloaded X-01 (Draft 14). The reloaded issue number for it was not verified (X-04 uses #14 for another item).

Priority 2: content completeness (C-series).

- [ ] **K-02 close-out.** Add a size WARN (suggested 1 MB) for scenario and template files with a test; run `python3 tools/fault_inject.py` and record 0 CRASH and 0 unexpected MISSED. Evidence: command output pasted in PR; `python3 -m unittest tests.test_validate_faults -v` names the size test. Tracker: none filed (Draft 17).
- [ ] **C-06 gen specs.** Write `gen/specs/*.yaml` for the 32 scenarios that name a generation mode without one. Evidence: `python3 tools/validate.py --strict-coverage` shows 0 warnings; `--generate-indexes` second run leaves no diff. Tracker: content #2; Draft 21.
- [ ] **C-04 E/S/T completion.** Attack-class to scenario mapping table; review log for promoted evasions (`adversary/`, `protocol/`). Evidence: mapping table in PR; no attack class in `protocol/` without a scenario. Tracker: content #2; Draft 21.

Priority 3: blocked on owner or external access.

- [ ] **C-01 dataset join (BLOCKED, B1).** Evidence: `grep -c rows_unverified taxonomy/strata.csv` goes 54 to 0 through the generator only. Tracker: content #2; Draft 19.
- [ ] **C-02 relation truth (needs C-01).** Evidence: every value in `relations/relations_truth.csv` is in reloaded `relation_kinds.v1.json`; 0 unknown. Tracker: content #2; Draft 19.
- [ ] **C-03 frozen emails (BLOCKED, B2).** Evidence: generator run with the key in the environment only; `grep -rEi "sk-or-|openrouter_api_key=" emails gen tools docs` empty; provenance on each record. Tracker: content #2; Draft 20.
- [ ] **C-05 promotion (owner step).** Owner-approved list from the reloaded plan: A13-A17, B1-B8, C1-C11, D1-D6 (30 scenarios). H-series stays `draft`. Evidence: the status diff matches the list exactly. Tracker: content #2; Draft 22.
- [ ] **C-07 v1.0.0 and nightly run.** Needs C-01 to C-05 and K-05. Evidence: tag and release `v1.0.0` with BUILD_INFO; reloaded bump; one nightly run recorded (command, date, result path). No GitHub Actions (CD19). Tracker: content #2; Draft 22.

Priority 4: housekeeping.

- [ ] Repo description still says "83 scenarios"; update to 116 (verified 2026-10-10).
- [ ] Content #2 (tracker): retarget to Phase 4 (reloaded plan X-04).
- [ ] Content #12 (strata "out of date" message in unit tests) and #13 (guard the one-shot migration map against re-runs): not reviewed here.
- [ ] Decide B3 visibility (repo is public and has a release).

### 8.4 Blockers and owners

See section 5 (B1 to B5). Owner-only actions: B1 network policy or local build; B2 key; B3 visibility; B4 licensing; release and promotion approvals (D2, C-05). Agent-doable without owner input: K-05, K-01 residuals, K-02 close-out, C-04, C-06, K-03 rows not needing a ruling.

### 8.5 Cross-repo dependencies on mailroom-reloaded

- Reloaded bump PR to v0.6.0 (or v0.5.0 first, per D2), with the stale lock header corrected. Depends on content K-05 and the v0.6.0 release.
- Reloaded plan header table and section 3.4 are stale (they say `f650cfd` is unpublished and PR #5 is open). Fix in a reloaded PR.
- K-05 requires a reloaded pinned commit for its drift check; reloaded `schemas/` remains the owner (CD8, D3). Content must not edit them.
- K-06 consumer-loader gate and strata drift need a reloaded checkout (`MAILROOM_RELOADED`); the reloaded plan K-08 (reloaded-side loader reporting) is listed as done; Boss-decision recovery is partial there. Content issue #14 is titled "content-side support for loader error reporting and Boss-decision recovery", which conflicts with the plan's "reloaded-side" label. Owner to confirm which repo owns it.
- Reloaded X-03 is superseded by K-05 (reloaded plan); no reloaded action beyond the pointer.

### 8.6 Not verified (2026-10-10)

- Test suite and `tools/fault_inject.py` were **not run**. The 213 is a grep count of `def test_`, not a test run. The 117 tests in 8.7 were counted on 2026-10-08.
- Strata drift and consumer-loader steps were not run (no reloaded checkout pinned here).
- Contents of the v0.5.0 bundle (dataset bytes or only manifests) were not inspected.
- Whether the owner has provided an OpenRouter key (B2), and whether the owner approved the v0.6.0 release (D2).
- Closed content issues were not checked, so an issue counted as "not filed" (Drafts 14, 16-22) could exist under a closed state. No open issue matches them.
- The PR-number links for content commits other than #4, #7, #15 were not verified; PRs #5 and #6 are cited from the reloaded plan.
- The 56 catalog / 54 ground-truth strata counts from 2026-10-08 were not recounted.
- Reloaded `origin/main` was used for hashes; the reloaded working tree was used only for `check_schema_drift.py`.

### 8.7 Status (2026-10-08, superseded; history)

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
