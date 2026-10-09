#!/usr/bin/env python3
"""Load this pack through mailroom-reloaded's own content loader (plan K-06).

mailroom-reloaded owns the contract: its loader
``mailroom_reloaded.sandbox.content.loader.load_content`` and its ``schemas/``
decide whether the pack is valid. This script imports that loader from a
checkout and loads the content directory with it, so a contract change in the
consumer fails here rather than only in the consumer's own CI.

Usage:
  python3 tools/load_with_consumer.py [--reloaded PATH] [--content PATH]

--reloaded defaults to $MAILROOM_RELOADED; --content defaults to this repo.

Output: one ``ERROR <file>: <message>`` line per error (the path is relative to
the content directory), then the summary line
``consumer-load: scenarios=N personas=N gen_specs=N errors=N``.

Exit status: 0 when the load reports no errors, 1 on load errors, 2 when the
checkout is missing or invalid, its loader cannot be imported, a dependency is
missing, or the content path is not a content directory. Expected conditions
print a reason on stderr and never a traceback.

The content directory needs dist/registry.yaml, which tools/validate.py
compiles (tools/ci.sh runs the validator first). This script only reads: it
sets ``sys.dont_write_bytecode`` before importing, so nothing is written into
the content repo or the consumer checkout.

Imports: the consumer's package __init__ pulls in the OpenTelemetry SDK and
pydantic-settings, which a validator does not need. The script imports the real
package first. Only if that fails does it register a bare ``mailroom_reloaded``
package whose __path__ is the checkout's source, so the loader's own submodules
(compat, lock, loader) load without running the package __init__. The loader
itself needs only yaml and jsonschema.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
LOADER_REL = Path("src/mailroom_reloaded/sandbox/content/loader.py")
SCHEMA_REL = Path("schemas/scenario.v2.json")
PACKAGE = "mailroom_reloaded"


def _purge_package() -> None:
    for name in [m for m in sys.modules if m == PACKAGE or m.startswith(PACKAGE + ".")]:
        del sys.modules[name]


def import_loader(checkout: Path):
    """Return the consumer's loader module, imported from ``checkout``.

    Raise ImportError with a one-line reason when neither the real package nor
    the bare-package fallback can import the loader from this checkout.
    """
    src = (checkout / "src").resolve()
    expected = (checkout / LOADER_REL).resolve()
    sys.path.insert(0, str(src))
    try:
        from mailroom_reloaded.sandbox.content import loader
        note = None
    except Exception as exc:  # noqa: BLE001 - any failure falls back to the bare package
        note = f"{type(exc).__name__}: {exc}"
        _purge_package()
        bare = types.ModuleType(PACKAGE)
        bare.__path__ = [str(src / PACKAGE)]
        sys.modules[PACKAGE] = bare
        try:
            from mailroom_reloaded.sandbox.content import loader
        except Exception as exc2:  # noqa: BLE001 - reported as a reason, not a traceback
            raise ImportError(f"{type(exc2).__name__}: {exc2} "
                              f"(package __init__ also failed: {note})") from exc2
    if Path(loader.__file__).resolve() != expected:
        raise ImportError(f"imported {loader.__file__}, not {expected}")
    if note is not None:
        print(f"note: package __init__ not importable here ({note}); "
              f"loaded the loader without it", file=sys.stderr)
    return loader


def main(argv: list[str] | None = None, environ=None) -> int:
    sys.dont_write_bytecode = True  # never write __pycache__ into the consumer checkout
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reloaded", default=None,
                        help="mailroom-reloaded checkout (default: $MAILROOM_RELOADED)")
    parser.add_argument("--content", default=str(ROOT),
                        help="content directory to load (default: this repo)")
    args = parser.parse_args(argv)

    environ = os.environ if environ is None else environ
    reloaded = args.reloaded or environ.get("MAILROOM_RELOADED", "")
    if not reloaded:
        print("consumer load: no mailroom-reloaded checkout: pass --reloaded PATH "
              "or set MAILROOM_RELOADED", file=sys.stderr)
        return 2
    checkout = Path(reloaded)
    if not checkout.is_dir():
        print(f"consumer load: mailroom-reloaded checkout not found: {checkout}",
              file=sys.stderr)
        return 2
    for rel in (LOADER_REL, SCHEMA_REL):
        if not (checkout / rel).is_file():
            print(f"consumer load: {checkout} is not a mailroom-reloaded checkout "
                  f"(missing {rel})", file=sys.stderr)
            return 2

    content = Path(args.content)
    if not ((content / "content.json").is_file() or (content / "manifest.json").is_file()):
        print(f"consumer load: not a content directory (no content.json): {content}",
              file=sys.stderr)
        return 2

    try:
        loader = import_loader(checkout)
    except ImportError as exc:
        print(f"consumer load: cannot import the loader from {checkout}: {exc}",
              file=sys.stderr)
        print("consumer load: the loader needs yaml and jsonschema: "
              "python3 -m pip install -r tools/requirements.txt", file=sys.stderr)
        return 2

    try:
        cs = loader.load_content(content)
    except ImportError as exc:
        print(f"consumer load: missing dependency for the consumer loader: {exc}",
              file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - a load failure is reported, not raised
        print(f"ERROR {content}: {type(exc).__name__}: {exc}")
        print("consumer-load: scenarios=0 personas=0 gen_specs=0 errors=1")
        return 1

    errors = list(cs.report.errors)
    for message in errors:
        print(f"ERROR {message}")
    print(f"consumer-load: scenarios={len(cs.scenarios)} personas={len(cs.personas)} "
          f"gen_specs={len(cs.gen_specs)} errors={len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
