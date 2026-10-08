#!/usr/bin/env python3
"""Export the pinned smoke set for mailroom-reloaded (CD13, addendum §13.1).

The export is everything a ``smoke`` run needs with zero network and no
dataset: the smoke scenarios with every {class, stratum} draw replaced by
its pinned stand-in, the pinned documents, the templates those scenarios
render, the personas they use, the compiled registry and a manifest of
sha256 values. mailroom-reloaded copies the directory verbatim to
``sandbox/fixtures/smoke/``.

  python3 tools/export_smoke.py --write-set   # refresh smoke_set.yaml documents
  python3 tools/export_smoke.py --check       # exit 1 if stale / unresolved / over budget
  python3 tools/export_smoke.py --out DIR     # write the export

Layout of DIR:
  manifest.json            content version, files {path: sha256}, total_bytes
  smoke_set.yaml
  registry.yaml            (dist/registry.yaml; run tools/validate.py first)
  scenarios/<name>.yaml    stand-ins applied; documents are always {file}
  docs/<file>
  templates/<name>.j2
  personas/personas.csv, personas/behavior/<file>.yaml
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import re
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SET = "smoke/smoke_set.yaml"
DOC_DIRS = ("attachments/synthetic", "attachments/offtaxonomy",
            "attachments/adversarial")


class SmokeError(Exception):
    pass


def _csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load(root: Path) -> tuple[dict, dict[str, dict], dict[str, dict]]:
    smoke = yaml.safe_load((root / SET).read_text(encoding="utf-8"))
    manifest = {r["file"]: r for r in _csv(root / "attachments/manifest.csv")}
    scenarios = {}
    for name in smoke["scenario_ids"]:
        hits = list((root / "scenarios").glob(f"*/{name}.yaml"))
        if len(hits) != 1:
            raise SmokeError(f"smoke scenario {name} not found")
        scenarios[name] = yaml.safe_load(hits[0].read_text(encoding="utf-8"))
    return smoke, manifest, scenarios


def resolve(smoke: dict, manifest: dict, scenarios: dict) -> tuple[dict, list[str]]:
    """Scenarios with stand-ins applied, and the ordered document list."""
    stand = {(s["class"], s["stratum"]): s["file"] for s in smoke.get("stand_ins") or []}
    files: list[str] = []
    out = {}

    def pin(spec: dict, where: str) -> dict:
        spec = dict(spec)
        if "file" not in spec and "same_as" not in spec:
            key = (spec.get("class"), spec.get("stratum"))
            if key not in stand:
                raise SmokeError(f"{where}: dataset draw {key[0]}/{key[1]} has no "
                                 f"stand-in in {SET}")
            spec["file"] = stand[key]
            for k in ("class", "stratum"):
                spec.pop(k, None)
        if "file" in spec:
            if spec["file"] not in manifest:
                raise SmokeError(f"{where}: {spec['file']} not in attachments/manifest.csv")
            if spec["file"] not in files:
                files.append(spec["file"])
        return spec

    for name, sc in scenarios.items():
        sc = copy.deepcopy(sc)
        if sc.get("gen") != "scripted":
            raise SmokeError(f"{name}: smoke scenarios must be gen: scripted")
        for i, ev in enumerate(sc["timeline"]):
            if "ingress" in ev:
                ev["ingress"] = pin(ev["ingress"], f"{name} timeline[{i}] ingress")
            client = ev.get("client") or {}
            client["attach"] = [pin(a, f"{name} timeline[{i}] attach[{j}]")
                                for j, a in enumerate(client.get("attach") or [])]
            if not client.get("attach"):
                client.pop("attach", None)
        out[name] = sc
    return out, files


def documents_block(manifest: dict, files: list[str]) -> list[dict]:
    keys = ("file", "doc_id", "sha256", "class", "stratum", "inert")
    return [{k: (manifest[f][k] == "true" if k == "inert" else manifest[f][k])
             for k in keys} for f in files]


def find_doc(root: Path, name: str) -> Path:
    for d in DOC_DIRS:
        p = root / d / name
        if p.exists():
            return p
    raise SmokeError(f"document {name} not found under {', '.join(DOC_DIRS)}")


def build(root: Path) -> dict[str, bytes]:
    """Every exported file as {relative path: bytes}."""
    smoke, manifest, scenarios = load(root)
    resolved, files = resolve(smoke, manifest, scenarios)
    if documents_block(manifest, files) != (smoke.get("documents") or []):
        raise SmokeError(f"{SET} documents block is stale; run "
                         f"tools/export_smoke.py --write-set")
    out: dict[str, bytes] = {}
    out["smoke_set.yaml"] = (root / SET).read_bytes()
    reg = root / "dist/registry.yaml"
    if not reg.exists():
        raise SmokeError("dist/registry.yaml missing; run tools/validate.py first")
    out["registry.yaml"] = reg.read_bytes()
    templates, persona_ids = set(), set()
    for name, sc in resolved.items():
        out[f"scenarios/{name}.yaml"] = yaml.safe_dump(
            sc, sort_keys=False, allow_unicode=True).encode("utf-8")
        for ev in sc["timeline"]:
            c = ev.get("client") or {}
            if c.get("template"):
                templates.add(c["template"])
            if c.get("persona"):
                persona_ids.add(c["persona"])
    for f in files:
        data = find_doc(root, f).read_bytes()
        if hashlib.sha256(data).hexdigest() != manifest[f]["sha256"]:
            raise SmokeError(f"{f}: sha256 differs from attachments/manifest.csv")
        out[f"docs/{f}"] = data
    for t in sorted(templates):
        out[f"templates/{t}.j2"] = (root / "gen/templates" / f"{t}.j2").read_bytes()
    all_rows = _csv(root / "personas/personas.csv")
    if not all_rows:
        raise SmokeError("personas/personas.csv is empty")
    rows = [r for r in all_rows if r["persona_id"] in persona_ids]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(all_rows[0].keys()), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    out["personas/personas.csv"] = buf.getvalue().encode("utf-8")
    for r in rows:
        out[f"personas/{r['behavior_file']}"] = (root / "personas" / r["behavior_file"]).read_bytes()
    content = json.loads((root / "content.json").read_text(encoding="utf-8"))
    total = sum(len(b) for b in out.values())
    if total > int(smoke.get("budget_bytes", 2 * 1024 * 1024)):
        raise SmokeError(f"smoke export is {total} bytes, over the "
                         f"{smoke.get('budget_bytes')} byte budget")
    out["manifest.json"] = (json.dumps({
        "schema": "mailroom.smoke_export/v1",
        "content_version": content["version"],
        "schema_version": content["schema_version"],
        "dataset_revision": content["dataset_revision"],
        "scenarios": list(resolved),
        "total_bytes": total,
        "files": {p: hashlib.sha256(b).hexdigest() for p, b in sorted(out.items())},
    }, indent=2) + "\n").encode("utf-8")
    return out


def write_set(root: Path) -> None:
    smoke, manifest, scenarios = load(root)
    _resolved, files = resolve(smoke, manifest, scenarios)
    text = (root / SET).read_text(encoding="utf-8")
    head = re.split(r"^documents:.*$", text, maxsplit=1, flags=re.M)[0]
    block = yaml.safe_dump({"documents": documents_block(manifest, files)},
                           sort_keys=False, default_flow_style=None, width=120)
    (root / SET).write_text(head + block, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write-set", action="store_true")
    g.add_argument("--check", action="store_true")
    g.add_argument("--out")
    args = ap.parse_args(argv)
    root = Path(args.root)
    try:
        if args.write_set:
            write_set(root)
            return 0
        files = build(root)
    except SmokeError as e:
        print(f"export_smoke: {e}", file=sys.stderr)
        return 1
    if args.out:
        out = Path(args.out)
        if out.exists():
            shutil.rmtree(out)
        for rel, data in files.items():
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            (out / rel).write_bytes(data)
    total = json.loads(files["manifest.json"])["total_bytes"]
    print(f"smoke export ok: {len(files)} files, {total} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
