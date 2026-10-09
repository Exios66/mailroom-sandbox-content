#!/usr/bin/env python3
"""Check that content's schemas/ mirror the consumer's schemas byte-for-byte.

mailroom-reloaded owns the contract. Every schema here that also exists in the
consumer's schemas/ directory must be an exact copy of it. Schemas that only
exist here are content-only and are not compared.

Usage:
  python3 tools/check_schema_drift.py [MAILROOM_RELOADED_CHECKOUT]

The checkout defaults to the MAILROOM_RELOADED environment variable. With
neither set, the check is skipped and exits 0.

Exit status: 0 when every shared schema is identical (or the check is
skipped), 1 when any shared schema differs, 2 when the given checkout has no
schemas/ directory or no shared schemas.
"""

from __future__ import annotations

import argparse
import filecmp
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SKIP_MESSAGE = "schema drift check skipped: set MAILROOM_RELOADED"


def compare(content_dir: Path, consumer_dir: Path) -> tuple[list[str], list[str], list[str]]:
    """Return (drifted, shared, local_only) file names for the two schema dirs.

    A file is shared when the same name exists in both directories; it drifts
    when the bytes differ. Files present only in content_dir are local_only.
    """
    drifted: list[str] = []
    shared: list[str] = []
    local_only: list[str] = []
    for path in sorted(content_dir.iterdir()):
        if not path.is_file():
            continue
        counterpart = consumer_dir / path.name
        if not counterpart.is_file():
            local_only.append(path.name)
            continue
        shared.append(path.name)
        if not filecmp.cmp(path, counterpart, shallow=False):
            drifted.append(path.name)
    return drifted, shared, local_only


def main(argv: list[str] | None = None, environ=None) -> int:
    """Compare shared schemas; return 0 for equal/skipped, 1 for drift, or 2 for a bad checkout."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("checkout", nargs="?", default=None,
                        help="mailroom-reloaded checkout (default: $MAILROOM_RELOADED)")
    parser.add_argument("--content", type=Path, default=None,
                        help=argparse.SUPPRESS)  # tests: content schemas dir
    args = parser.parse_args(argv)

    environ = os.environ if environ is None else environ
    checkout = args.checkout or environ.get("MAILROOM_RELOADED", "")
    if not checkout:
        print(SKIP_MESSAGE)
        return 0

    consumer_dir = Path(checkout) / "schemas"
    if not consumer_dir.is_dir():
        print(f"schema drift check: no schemas/ directory in {checkout}", file=sys.stderr)
        return 2

    content_dir = args.content or (ROOT / "schemas")
    drifted, shared, local_only = compare(content_dir, consumer_dir)
    for name in drifted:
        print(f"DRIFT {name}")
    for name in local_only:
        print(f"content-only (not compared): {name}")
    if not shared:
        print(f"schema drift check: no shared schemas in {consumer_dir}", file=sys.stderr)
        return 2
    if drifted:
        print(f"schema drift: {len(drifted)} of {len(shared)} shared schema(s) differ "
              f"from {consumer_dir}", file=sys.stderr)
        return 1
    print(f"schema drift: none ({len(shared)} shared schema(s) byte-identical)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
