#!/usr/bin/env python3
"""Dataset join for the in-taxonomy attachment slice (C9; addendum §5, CD15).

Runs on a machine that can read Lucius-Morningstar/mailroom-dataset (a
developer machine, or a cloud session whose network policy allows
huggingface.co). It reads ONLY label and hash columns of the
``ground_truth`` config, TRAIN split, at the revision pinned in
content.json; it never reads ``doc_text`` and never copies text-derived
ground-truth fields (subject_matter, keywords, gt_fields …) into this repo.

Two steps:

  --counts   fill taxonomy/strata.csv ``rows`` (train rows per stratum) and
             mark those strata ``active``.
  --select N choose N candidate documents per (client, class, stratum) of
             clients/client_doc_mix.csv, seeded and stable, and write them
             to attachments/manifest.csv as ``source=dataset`` rows
             (att_1000+, ids/ranges.yaml block C9-dataset). Re-running
             replaces the previous dataset rows, so selection is idempotent.

Rendering (text -> PDF/DOCX, degradation pass) happens at bundle build in
mailroom-reloaded (``mailroom sandbox content build``); that step fills
sha256 / doc_id after degradation. Until then dataset rows carry the
dataset's own ``content_sha256`` in ``notes`` and a blank sha256 / doc_id.

Input (pick one):
  --ground-truth PATH   a local export of the ground_truth config
                        (.parquet needs pyarrow; .jsonl / .csv need nothing)
  --hf                  load with the ``datasets`` library (network)

Examples:
  python3 tools/build_attachments.py --hf --counts --select 3
  python3 tools/build_attachments.py --ground-truth gt_train.parquet --counts
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "Lucius-Morningstar/mailroom-dataset"
COLUMNS = ("filename", "expected", "expected_subclass", "split",
           "content_sha256", "document_id")
FIRST_ID = 1000
MANIFEST_HEADER = ["attachment_id", "file", "sha256", "doc_id", "class", "stratum",
                   "in_taxonomy", "source", "dataset_revision", "dataset_filename",
                   "degradation", "inert", "notes"]


def _read_rows(path: Path) -> list[dict]:
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq  # optional dependency
        table = pq.read_table(path, columns=[c for c in COLUMNS])
        return table.to_pylist()
    if path.suffix == ".jsonl":
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                obj = json.loads(line)
                rows.append({c: obj.get(c) for c in COLUMNS})
        return rows
    with path.open(newline="", encoding="utf-8") as f:
        return [{c: r.get(c) for c in COLUMNS} for r in csv.DictReader(f)]


def _load_hf(revision: str) -> list[dict]:
    import datasets  # optional dependency
    ds = datasets.load_dataset(REPO, "ground_truth", revision=revision, split="train")
    return [{c: r.get(c) for c in COLUMNS} for r in ds.select_columns(list(COLUMNS))]


def normalize(rows: list[dict], surface_map: dict) -> list[dict]:
    """Train rows only, each with a canonical (class, stratum)."""
    out = []
    for r in rows:
        if (r.get("split") or "train") != "train":
            continue
        cls = r.get("expected") or ""
        raw = r.get("expected_subclass") or ""
        stratum = surface_map.get(cls, {}).get(raw, raw)
        out.append({**r, "class": cls, "stratum": stratum})
    return out


def counts(rows: list[dict]) -> dict[tuple[str, str], int]:
    c: dict[tuple[str, str], int] = {}
    for r in rows:
        key = (r["class"], r["stratum"])
        c[key] = c.get(key, 0) + 1
    return c


def write_counts(root: Path, by_stratum: dict) -> list[str]:
    """Fill rows/status; return strata that the dataset has but the roster lacks."""
    path = root / "taxonomy" / "strata.csv"
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    known = set()
    for r in rows:
        key = (r["class"], r["stratum"])
        known.add(key)
        if r["in_ground_truth"] == "true":
            n = by_stratum.get(key, 0)
            r["rows"] = str(n) if n else ""
            r["status"] = "active" if n else "rows_unverified"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8")
    return sorted(f"{c}/{s}" for c, s in by_stratum if (c, s) not in known)


def _rank(revision: str, client: str, filename: str) -> str:
    return hashlib.sha256(f"{revision}|{client}|{filename}".encode()).hexdigest()


def select(root: Path, rows: list[dict], revision: str, per_stratum: int) -> int:
    with (root / "clients" / "client_doc_mix.csv").open(newline="", encoding="utf-8") as f:
        mixes = [m for m in csv.DictReader(f)
                 if m["in_taxonomy"] == "true" and float(m["weight"]) > 0]
    pool: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        pool.setdefault((r["class"], r["stratum"]), []).append(r)
    man_path = root / "attachments" / "manifest.csv"
    with man_path.open(newline="", encoding="utf-8") as f:
        kept = [r for r in csv.DictReader(f) if r.get("source") != "dataset"]
    new, n = [], FIRST_ID
    for m in sorted(mixes, key=lambda m: (m["client_id"], m["class"], m["stratum"])):
        cands = sorted(pool.get((m["class"], m["stratum"]), []),
                       key=lambda r: _rank(revision, m["client_id"], r["filename"]))
        for r in cands[:per_stratum]:
            new.append({
                "attachment_id": f"att_{n:04d}", "file": r["filename"],
                "sha256": "", "doc_id": "", "class": m["class"], "stratum": m["stratum"],
                "in_taxonomy": "true", "source": "dataset", "dataset_revision": revision,
                "dataset_filename": r["filename"], "degradation": "per_client_profile",
                "inert": "false",
                "notes": f"client={m['client_id']}; dataset content_sha256="
                         f"{r.get('content_sha256') or ''}",
            })
            n += 1
    seen, unique = set(), []
    for r in new:  # one manifest row per dataset file; first client wins
        if r["file"] not in seen:
            seen.add(r["file"])
            unique.append(r)
    for i, r in enumerate(unique):
        r["attachment_id"] = f"att_{FIRST_ID + i:04d}"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=MANIFEST_HEADER, lineterminator="\n")
    w.writeheader()
    w.writerows(kept + unique)
    man_path.write_text(buf.getvalue(), encoding="utf-8")
    return len(unique)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--ground-truth", type=Path)
    src.add_argument("--hf", action="store_true")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--counts", action="store_true")
    ap.add_argument("--select", type=int, default=0, metavar="N")
    args = ap.parse_args(argv)
    if not args.counts and not args.select:
        ap.error("nothing to do: pass --counts and/or --select N")
    revision = json.loads((args.root / "content.json").read_text())["dataset_revision"]
    surface_map = json.loads(
        (args.root / "taxonomy" / "strata.source.json").read_text())["surface_map"]
    raw = _load_hf(revision) if args.hf else _read_rows(args.ground_truth)
    rows = normalize(raw, surface_map)
    if args.counts:
        extra = write_counts(args.root, counts(rows))
        print(f"counted {len(rows)} train rows")
        if extra:
            print("dataset strata missing from the roster (re-run "
                  "tools/sync_strata.py): " + ", ".join(extra), file=sys.stderr)
            return 1
    if args.select:
        print(f"selected {select(args.root, rows, revision, args.select)} dataset rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
