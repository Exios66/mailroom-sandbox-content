#!/bin/sh
# Cut a content release locally (GitHub Actions is not used for this repo).
#
#   tools/release.sh            check, build release/, create the tag locally
#   tools/release.sh --push     ...and push the tag; with the gh CLI logged in,
#                               also create the GitHub release with the assets
#
# Preconditions: clean tree, on main, content.json version not yet tagged.
# Steps: content-ci (tools/ci.sh) -> deterministic bundle + SHA256SUMS
# (tools/build_bundle.py) -> annotated tag vX.Y.Z.
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"
PUSH=0
[ "${1:-}" = "--push" ] && PUSH=1

VERSION="$("$PY" -c 'import json;print(json.load(open("content.json"))["version"])')"
TAG="v$VERSION"

[ -z "$(git status --porcelain)" ] || { echo "working tree not clean" >&2; exit 1; }
[ "$(git rev-parse --abbrev-ref HEAD)" = "main" ] || {
    echo "release from main (on $(git rev-parse --abbrev-ref HEAD))" >&2; exit 1; }
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
    echo "tag $TAG already exists; bump content.json version first" >&2; exit 1
fi

tools/ci.sh
"$PY" tools/build_bundle.py --out release
git tag -a "$TAG" -m "mailroom-sandbox-content $TAG"
echo "tagged $TAG at $(git rev-parse --short HEAD); assets in release/"

if [ "$PUSH" = 1 ]; then
    git push origin "$TAG"
    if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
        gh release create "$TAG" "release/mailroom-sandbox-content-$TAG.tar.zst" \
            release/SHA256SUMS release/content.json \
            --title "mailroom-sandbox-content $TAG" \
            --notes "Content bundle $TAG. Verify with \`sha256sum -c SHA256SUMS\`; pin in mailroom-reloaded via sandbox/content.lock (repo, tag, commit, bundle sha256)."
    else
        echo "gh not available or not logged in: create the GitHub release for $TAG"
        echo "by hand and attach the three files in release/."
    fi
else
    echo "next: tools/release.sh --push   (or: git push origin $TAG, then upload release/*)"
fi
