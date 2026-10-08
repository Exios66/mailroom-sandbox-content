#!/usr/bin/env python3
"""Generate the coverage-profile scenarios (CD12, addendum §2.4).

One scenario per dataset class, ``A<13+i>_coverage_<class>``. Each walks
every ground-truth stratum of its class as a benign submission from the
client whose document mix weights that stratum most (ties: client id), so
the ``coverage`` profile exercises every stratum with a plausible sender.
Every message is benign: the scenario asserts zero hard actions, which
makes these the over-blocking baseline per class and stratum (§8.4).

The files are GENERATED from clients/client_doc_mix.csv,
clients/client_contacts.csv, personas/personas.csv and
taxonomy/strata.csv; edit those, then re-run:

  python3 tools/gen_coverage_scenarios.py          # write
  python3 tools/gen_coverage_scenarios.py --check  # exit 1 on drift
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from migrate_scenarios_v2 import Dumper, ordered, ORDER  # noqa: E402

import yaml  # noqa: E402

CLASSES = ("contract", "merger_agreement", "corporate_record",
           "correspondence", "insurance_claim")
FIRST_NUMBER = 13
SEED_BASE = 1700
MATTER = {  # client -> matter/claim reference used in cover notes
    "harlowpryce": "HP-2026-07{n:02d}", "northstar": "NA-2026-07{n:02d}",
    "tricountytitle": "TC-2026-07{n:02d}", "okafor": "claim CL-5590{n:02d}",
    "cedarridge": "CR-2026-07{n:02d}", "lakeshore": "LS-2026-07{n:02d}",
    "vega": "claim VG-2026-07{n:02d}", "stateca": "SCA-2026-07{n:02d}",
    "prairielabs": "the company records file", "brightwater": "the property file",
}
LABEL = {"contract": "agreement", "merger_agreement": "merger agreement",
         "corporate_record": "record", "correspondence": "letter",
         "insurance_claim": "claim document"}


def read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build(root: Path) -> dict[str, dict]:
    strata = [r for r in read(root / "taxonomy/strata.csv")
              if r["in_ground_truth"] == "true"]
    mixes = read(root / "clients/client_doc_mix.csv")
    contacts = {r["contact_id"]: r for r in read(root / "clients/client_contacts.csv")}
    persona_by_client = {}
    for p in read(root / "personas/personas.csv"):
        if p["role"] == "real" and p["client_id"] not in persona_by_client:
            persona_by_client[p["client_id"]] = p
    out: dict[str, dict] = {}
    for i, cls in enumerate(CLASSES):
        number = FIRST_NUMBER + i
        name = f"A{number}_coverage_{cls}"
        timeline = []
        docs = {}
        for j, row in enumerate(r for r in strata if r["class"] == cls):
            stratum = row["stratum"]
            senders = sorted(((-float(m["weight"]), m["client_id"]) for m in mixes
                              if m["class"] == cls and m["stratum"] == stratum
                              and float(m["weight"]) > 0))
            if not senders:
                raise SystemExit(f"{cls}/{stratum} has no sender in client_doc_mix.csv; "
                                 f"add one before generating coverage scenarios")
            client = senders[0][1]
            persona = persona_by_client[client]
            ref = f"doc_{stratum}"
            timeline.append({"at": f"{j // 60:02d}:{j % 60:02d}", "client": {
                "ref": f"msg_{stratum}",
                "persona": persona["persona_id"], "channel": "email",
                "claimed_from": contacts[persona["contact_id"]]["email"],
                "auth": {"spf": "pass", "dkim": "pass", "dmarc": "pass"},
                "template": "document_submission",
                "vars": {"document_title": f"the {stratum.replace('_', ' ')} "
                                           f"{LABEL[cls]}",
                         "matter_ref": MATTER[client].format(n=j + 1),
                         "note": "For the file."},
                "attach": [{"ref": ref, "class": cls, "stratum": stratum,
                            "in_taxonomy": True}],
            }})
            docs[ref] = {"doc_type": cls, "subclass": stratum}
        out[name] = ordered({
            "name": name,
            "title": f"Coverage: every ground-truth {cls} stratum from its most "
                     f"plausible sender; all benign (GENERATED)",
            "seed": SEED_BASE + number, "profile": "coverage", "gen": "scripted",
            "transports": ["sim"], "status": "review", "owner": "C2-coverage",
            "tags": ["coverage", "generated", cls],
            "timeline": timeline,
            "expect": {
                "intent": "document_submission",
                "signals": [{"kind": "new_info", "priority": "normal"}],
                "trust": {"sender_level": "verified"},
                "docs": docs,
                "quarantine": [], "soft_hold": [],
                "overblocking": {"benign_hard_actions": 0},
                "invariants": ["audit_chain_ok", "no_stuck_docs",
                               "fast_path_two_calls", "comms_offpath"],
            },
        }, ORDER)
    return out


def render(scenario: dict) -> str:
    return ("# GENERATED by tools/gen_coverage_scenarios.py; do not edit.\n"
            + yaml.dump(scenario, Dumper=Dumper, sort_keys=False,
                        allow_unicode=True, width=100))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root)
    stale = []
    for name, scenario in build(root).items():
        path = root / "scenarios" / "A" / f"{name}.yaml"
        text = render(scenario)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(str(path.relative_to(root)))
        else:
            path.write_text(text, encoding="utf-8")
    if stale:
        print("coverage scenarios out of date: " + ", ".join(stale)
              + "; run tools/gen_coverage_scenarios.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
