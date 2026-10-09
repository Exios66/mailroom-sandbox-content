#!/bin/sh
# content-ci, run locally (GitHub Actions is not used for this repo).
#
# Runs every check the old .github/workflows/content-ci.yml ran:
#   1. validator with strict coverage (compiles dist/registry.yaml)
#   2. unit tests
#   3. generated files are current (coverage scenarios, scenario index,
#      smoke documents block)
#   4. strata drift: taxonomy/strata.csv vs mailroom-reloaded's catalogue at
#      the commit pinned in taxonomy/strata.source.json
#
# Usage: tools/ci.sh [--skip-drift]
# Strata drift needs a mailroom-reloaded checkout: set MAILROOM_RELOADED to
# one, or the script fetches the pinned commit into .cache/ (needs network).
# A failed fetch stops the run with the remedies; it is never a pass.
# --skip-drift is for local work only: tools/release.sh never passes it.
# Installed as the pre-push hook by tools/install-hooks.sh.
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"
SKIP_DRIFT=0
[ "${1:-}" = "--skip-drift" ] && SKIP_DRIFT=1

step() { printf '\n== %s\n' "$1"; }

step "dependencies"
"$PY" -c "import yaml, jsonschema, jinja2" 2>/dev/null || {
    echo "missing deps: $PY -m pip install -r tools/requirements.txt" >&2; exit 1; }

step "validator (strict coverage)"
"$PY" tools/validate.py --strict-coverage

step "unit tests"
"$PY" -m unittest discover -s tests -p 'test_*.py'

step "generated files are current"
"$PY" tools/gen_coverage_scenarios.py --check
"$PY" tools/validate.py --generate-indexes > /dev/null
git diff --exit-code -- scenarios/scenarios_index.csv
"$PY" tools/export_smoke.py --check

if [ "$SKIP_DRIFT" = 1 ]; then
    step "strata drift: SKIPPED (--skip-drift)"
else
    step "strata drift"
    COMMIT="$("$PY" -c 'import json;print(json.load(open("taxonomy/strata.source.json"))["commit"])')"
    SRC="${MAILROOM_RELOADED:-}"
    if [ -z "$SRC" ]; then
        SRC="$ROOT/.cache/mailroom-reloaded"
        if [ ! -d "$SRC/.git" ]; then
            git init -q "$SRC"
            git -C "$SRC" remote add origin https://github.com/Exios66/mailroom-reloaded.git
        fi
        # Fetch failures (offline, no such commit on origin) end the run here
        # with the remedies; the raw git error is kept only as detail.
        if ! fetch_err="$(git -C "$SRC" fetch -q --depth 1 origin "$COMMIT" 2>&1 &&
                          git -C "$SRC" checkout -q FETCH_HEAD 2>&1)"; then
            {
                printf 'strata drift: cannot fetch mailroom-reloaded commit %s into %s\n' "$COMMIT" "$SRC"
                printf '  (no network, or the pinned commit is not on origin)\n'
                printf '  git said:\n'
                printf '%s\n' "$fetch_err" | sed 's/^/    /'
                printf '  remedies (a failed fetch is not a pass):\n'
                printf '    tools/ci.sh --skip-drift\n'
                printf '    MAILROOM_RELOADED=/path/to/mailroom-reloaded tools/ci.sh\n'
            } >&2
            exit 1
        fi
    fi
    "$PY" tools/sync_strata.py --from "$SRC" --check
fi

printf '\ncontent-ci: all checks passed\n'
