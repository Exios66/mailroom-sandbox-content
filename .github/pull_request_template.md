## Summary

<!-- One or two sentences: what this PR does. -->

## Type of change

<!-- Tick all that apply. -->

- [ ] Scenario content
- [ ] Schema / contract
- [ ] Tooling
- [ ] Docs
- [ ] Release

## Why

<!-- Motivation, linked issues ("Closes #12"), policy sources for scenario expectations. -->

## Changes

<!-- Bullet the files or areas changed. Do not list hand edits to generated files: there must be none. -->

## Validation

<!-- Local only: this repo has no hosted CI. Tick what you actually ran; note skips under "Not verified". -->

- [ ] `tools/ci.sh` passes (no `--skip-*` flags)
- [ ] Validator strict coverage: `python3 tools/validate.py --strict-coverage`
- [ ] Contradictions lint strict: `python3 tools/lint_contradictions.py --strict`
- [ ] Generated files current: `tools/gen_coverage_scenarios.py --check`, `tools/validate.py --generate-indexes`, `tools/export_smoke.py --check`
- [ ] Consumer loader and schema drift: `MAILROOM_RELOADED=/path/to/mailroom-reloaded tools/ci.sh`
- [ ] Strata drift: `tools/ci.sh` without `--skip-drift`

## Synthetic-data & safety

- [ ] No real personal data, real companies, or dataset text
- [ ] Any brand name in body text is listed in `tools/brand_allowlist.txt`
- [ ] Passwords and fixtures are marked synthetic

## Release impact

- [ ] `version` in `content.json` bumped (own PR per README)
- [ ] `CHANGELOG.md` entry added
- [ ] Tag to be cut via `tools/release.sh`
- [ ] Downstream `mailroom sandbox content bump --tag vX.Y.Z` needed in mailroom-reloaded

## Not verified / follow-ups

<!-- Be explicit about every gate skipped and every claim not checked. -->

<!-- Fill this block; agents must keep the exact shape. Use null or [] when empty. -->
```yaml
agent-report:
  schema: 1
  change_type: scenario|schema|tooling|docs|release
  scopes: []            # paths or series, e.g. scenarios/H, tools/validate.py
  linked_issues: []     # "#12" style
  stack_parent: null    # PR number this is stacked on, or null
  gates:
    ci_sh: pass|fail|skipped
    strict_coverage: pass|fail|skipped
    contradictions_strict: pass|fail|skipped
    consumer_loader: pass|fail|skipped
    strata_drift: pass|fail|skipped
  version_bump: none|patch|minor|major
  not_verified: []
  follow_ups: []
```
