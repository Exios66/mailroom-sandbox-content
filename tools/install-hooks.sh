#!/bin/sh
# Point git at the repo's versioned hooks: content-ci runs before every push.
set -eu
git -C "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)" config core.hooksPath .githooks
echo "hooks installed: tools/ci.sh runs on git push"
