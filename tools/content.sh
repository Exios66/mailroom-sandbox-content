#!/bin/sh
# Thin local shims for contributors who don't have mailroom-reloaded
# installed. The real commands live in the mailroom-reloaded repo as
# `mailroom sandbox content ...`; these just delegate to tools/validate.py.
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

usage() {
    echo "usage: content.sh {validate|coverage --out PATH|indexes}" >&2
    echo "note: the real commands are \`mailroom sandbox content ...\`" >&2
    echo "      in the mailroom-reloaded repo." >&2
}

case "${1:-}" in
    validate)
        exec python3 "$ROOT/tools/validate.py"
        ;;
    coverage)
        if [ "${2:-}" = "--out" ] && [ -n "${3:-}" ]; then
            exec python3 "$ROOT/tools/validate.py" --coverage-out "$3"
        else
            echo "usage: content.sh coverage --out PATH" >&2
            exit 2
        fi
        ;;
    indexes)
        exec python3 "$ROOT/tools/validate.py" --generate-indexes
        ;;
    ""|-h|--help|help)
        usage
        ;;
    *)
        echo "content.sh: unknown command '$1'" >&2
        usage
        exit 2
        ;;
esac
