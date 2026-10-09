#!/bin/sh
# Cut a content release locally (GitHub Actions is not used for this repo).
#
#   tools/release.sh            check, build release/, create the tag locally
#   tools/release.sh --push     ...and push the tag; with the gh CLI logged in,
#                               also create the GitHub release with the assets
#
# Preconditions: clean tree, on main, content.json version not yet tagged.
# Steps: content-ci (tools/ci.sh, strata drift always runs) -> dist/registry.yaml
# must be a fresh compile (not stale, not missing) -> deterministic bundle and
# SHA256SUMS (tools/build_bundle.py --release, pinned zstandard) -> annotated tag.
# Nothing skips drift: --skip-drift and a SKIP_DRIFT variable are refused.
set -eu

usage() { echo "usage: tools/release.sh [--push]" >&2; exit 2; }

PUSH=0
case "${1:-}" in
    "") ;;
    --push) PUSH=1 ;;
    --skip-drift|--no-drift|--skip*)
        echo "release.sh refuses --skip-drift: a release always runs the strata drift check." >&2
        echo "give it a mailroom-reloaded checkout instead:" >&2
        echo "  MAILROOM_RELOADED=/path/to/mailroom-reloaded tools/release.sh" >&2
        exit 1 ;;
    *) usage ;;
esac
[ "$#" -le 1 ] || usage
if [ -n "${SKIP_DRIFT:-}" ]; then
    echo "release.sh refuses SKIP_DRIFT: a release always runs the strata drift check." >&2
    exit 1
fi

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"

VERSION="$("$PY" -c 'import json;print(json.load(open("content.json"))["version"])')"
TAG="v$VERSION"
NOTES="Content bundle $TAG. Verify with: sha256sum -c SHA256SUMS; pin in mailroom-reloaded via sandbox/content.lock (repo, tag, commit, bundle sha256)."
REG="dist/registry.yaml"

[ -z "$(git status --porcelain)" ] || { echo "working tree not clean" >&2; exit 1; }
[ "$(git rev-parse --abbrev-ref HEAD)" = "main" ] || {
    echo "release from main (on $(git rev-parse --abbrev-ref HEAD))" >&2; exit 1; }
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
    echo "tag $TAG already exists; bump content.json version first" >&2; exit 1
fi

# Before tagging, every failure lands here: no tag, nothing pushed.
TAGGED=0
on_exit() {
    status=$?
    if [ "$status" -ne 0 ] && [ "$TAGGED" = 0 ]; then
        echo "" >&2
        echo "release stopped before tagging: no tag was created and nothing was pushed." >&2
        echo "fix the failure above, then rerun: tools/release.sh$( [ "$PUSH" = 1 ] && echo ' --push' )" >&2
        echo "release.sh itself writes only ignored outputs (dist/, release/); if git status" >&2
        echo "lists changes, they came from tools/ci.sh's generated files: review them." >&2
    fi
}
trap on_exit EXIT

# The registry is generated and gitignored, so git status cannot see it going
# stale, and file mtimes lie after clone or copy. Instead: digest what is on
# disk, let content-ci recompile it from the current inputs, and refuse if the
# digest changed (the compile is deterministic: sorted keys, safe_dump).
registry_digest() {
    if [ -f "$REG" ]; then
        "$PY" -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$REG"
    else
        echo missing
    fi
}
registry_before="$(registry_digest)"

if ! tools/ci.sh; then
    echo "release refused: content-ci failed (see above). Drift is not optional for a release." >&2
    echo "if the strata fetch failed, rerun with a checkout:" >&2
    echo "  MAILROOM_RELOADED=/path/to/mailroom-reloaded tools/release.sh" >&2
    exit 1
fi

registry_after="$(registry_digest)"
if [ "$registry_before" != "$registry_after" ]; then
    if [ "$registry_before" = missing ]; then was=missing; else was=stale; fi
    echo "refused: $REG was $was; content-ci recompiled it from the current inputs." >&2
    echo "a release must not rest on a registry that was not a fresh compile." >&2
    echo "the recompiled file is now current: rerun tools/release.sh" >&2
    exit 1
fi

"$PY" tools/build_bundle.py --out release --release
git tag -a "$TAG" -m "mailroom-sandbox-content $TAG"
TAGGED=1
echo "tagged $TAG at $(git rev-parse --short HEAD); assets in release/"

if [ "$PUSH" = 1 ]; then
    if ! git push origin "$TAG"; then
        echo "git push origin $TAG failed: the tag exists locally only; nothing is published." >&2
        echo "retry exactly:" >&2
        echo "  git push origin $TAG" >&2
        echo "or drop the local tag and start over (nothing was pushed):" >&2
        echo "  git tag -d $TAG" >&2
        exit 1
    fi
    if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
        if ! gh release create "$TAG" "release/mailroom-sandbox-content-$TAG.tar.zst" \
                release/SHA256SUMS release/content.json release/BUILD_INFO \
                --title "mailroom-sandbox-content $TAG" --notes "$NOTES"; then
            echo "gh release create failed; the tag $TAG is already pushed." >&2
            echo "retry only the GitHub release, from the repo root, exactly:" >&2
            echo "  gh release create $TAG release/mailroom-sandbox-content-$TAG.tar.zst release/SHA256SUMS release/content.json release/BUILD_INFO --title 'mailroom-sandbox-content $TAG' --notes '$NOTES'" >&2
            exit 1
        fi
    else
        echo "gh not available or not logged in: create the GitHub release for $TAG"
        echo "by hand and attach the four files in release/."
    fi
else
    echo "next: tools/release.sh --push   (or: git push origin $TAG, then upload release/*)"
fi
