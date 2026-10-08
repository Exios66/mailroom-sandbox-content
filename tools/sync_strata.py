#!/usr/bin/env python3
"""Generate taxonomy/strata.csv from a mailroom-reloaded checkout.

Addendum v2 §2.1: stratum names are never typed by hand. The roster comes
from the main repo's canonical subclass catalogue:

  src/mailroom_reloaded/scoring/corpus.py
    DOC_TYPE_SUBCLASSES       -> in_live_catalog
    CORPUS_SUBCLASS_SURFACES  -> in_ground_truth (surfaces normalized to keys)
  src/mailroom_reloaded/scoring/config.py
    CONTRACT_SUBTYPES, MAUD_CONSIDERATION_TYPES, SUBTYPE_ALIASES

Importing the package pulls in OpenTelemetry and friends, so the tables are
read with ``ast`` and evaluated in a namespace holding only ``tuple`` and
the constants they reference.

The ``rows`` column is owned by the dataset scan (tools/build_attachments.py)
and is carried over from the existing file; it is blank until that scan runs.

Usage:
  python3 tools/sync_strata.py --from ../mailroom-reloaded [--ref v0.2.0]
  python3 tools/sync_strata.py --from ../mailroom-reloaded --check
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path

CORPUS = "src/mailroom_reloaded/scoring/corpus.py"
CONFIG = "src/mailroom_reloaded/scoring/config.py"
CLASS_ORDER = ("contract", "merger_agreement", "corporate_record",
               "correspondence", "insurance_claim")
HEADER = ["class", "stratum", "in_ground_truth", "in_live_catalog", "rows",
          "status"]
_KEY_RE = re.compile(r"[^a-z0-9]")


def _assignments(path: Path) -> dict[str, ast.expr]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                out[node.target.id] = node.value
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value
    return out


def _eval(expr: ast.expr, names: dict) -> object:
    code = compile(ast.Expression(expr), "<catalog>", "eval")
    return eval(code, {"__builtins__": {}}, dict(names))  # noqa: S307 - restricted


def load_catalog(src: Path) -> tuple[dict, dict]:
    """Return (live_catalog, ground_truth_keys) as {class: [stratum, ...]}."""
    cfg = _assignments(src / CONFIG)
    subtypes = ast.literal_eval(cfg["CONTRACT_SUBTYPES"])
    contract_keys = [s["key"] for s in subtypes]
    maud = ast.literal_eval(cfg["MAUD_CONSIDERATION_TYPES"])
    aliases = ast.literal_eval(cfg["SUBTYPE_ALIASES"])

    corpus = _assignments(src / CORPUS)
    names = {"tuple": tuple, "CONTRACT_SUBTYPE_KEYS": contract_keys,
             "MAUD_CONSIDERATION_TYPES": maud}
    live = _eval(corpus["DOC_TYPE_SUBCLASSES"], names)
    surfaces = ast.literal_eval(corpus["CORPUS_SUBCLASS_SURFACES"])

    def norm_contract(surface: str) -> str:
        key = _KEY_RE.sub("", surface.lower())
        by_key = {_KEY_RE.sub("", k): k for k in contract_keys}
        if key in by_key:
            return by_key[key]
        by_alias = {_KEY_RE.sub("", a): v for a, v in aliases.items()}
        if key in by_alias:
            return by_alias[key]
        for s in subtypes:  # mirrors scoring.equivalences.normalize_subtype
            label = _KEY_RE.sub("", s["label"].lower())
            if key == label or key.startswith(label[:8]):
                return s["key"]
        raise SystemExit(f"cannot normalize contract surface {surface!r}")

    gt: dict[str, list[str]] = {}
    for cls in CLASS_ORDER:
        keys = []
        for surface in surfaces.get(cls, ()):
            k = norm_contract(surface) if cls == "contract" else surface
            if k not in live.get(cls, ()):
                raise SystemExit(f"{cls}: ground-truth surface {surface!r} "
                                 f"-> {k!r} is not in the live catalog")
            if k not in keys:
                keys.append(k)
        gt[cls] = keys
    return {c: list(live[c]) for c in CLASS_ORDER}, gt


def build_rows(live: dict, gt: dict, old_rows: dict) -> list[dict]:
    rows = []
    for cls in CLASS_ORDER:
        for stratum in live[cls]:
            in_gt = stratum in gt[cls]
            n = old_rows.get((cls, stratum), "")
            if not in_gt:
                status = "catalog_only"
            elif n:
                status = "active"
            else:
                status = "rows_unverified"
            rows.append({"class": cls, "stratum": stratum,
                         "in_ground_truth": str(in_gt).lower(),
                         "in_live_catalog": "true", "rows": n,
                         "status": status})
    return rows


def render(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=HEADER, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def _git(src: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(src), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def source_record(src: Path, ref: str | None) -> dict:
    def sha(rel: str) -> str:
        return hashlib.sha256((src / rel).read_bytes()).hexdigest()
    return {
        "repo": "Exios66/mailroom-reloaded",
        "ref": ref or _git(src, "describe", "--tags", "--always"),
        "commit": _git(src, "rev-parse", "HEAD"),
        "files": {CORPUS: sha(CORPUS), CONFIG: sha(CONFIG)},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="src", required=True,
                    help="path to a mailroom-reloaded checkout")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--ref", default=None, help="tag/ref label to record")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if taxonomy/strata.csv differs from the catalog")
    args = ap.parse_args(argv)
    src, root = Path(args.src), Path(args.root)
    out = root / "taxonomy" / "strata.csv"

    old_rows: dict = {}
    if out.exists():
        with out.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if (r.get("rows") or "").strip().isdigit():
                    old_rows[(r["class"], r["stratum"])] = r["rows"].strip()

    live, gt = load_catalog(src)
    text = render(build_rows(live, gt, old_rows))
    if args.check:
        current = out.read_text(encoding="utf-8") if out.exists() else ""
        if current != text:
            print("taxonomy/strata.csv is out of date with the mailroom-reloaded "
                  "catalog; run tools/sync_strata.py --from <checkout>",
                  file=sys.stderr)
            return 1
        print("taxonomy/strata.csv matches the catalog")
        return 0
    out.write_text(text, encoding="utf-8")
    (root / "taxonomy" / "strata.source.json").write_text(
        json.dumps(source_record(src, args.ref), indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    n_gt = sum(len(v) for v in gt.values())
    n_live = sum(len(v) for v in live.values())
    print(f"wrote taxonomy/strata.csv: {n_live} catalog strata, "
          f"{n_gt} in ground truth")
    return 0


if __name__ == "__main__":
    sys.exit(main())
