#!/usr/bin/env python3
"""One-shot migration of scenarios to the final scenario/v2 shape (CD7, CD18).

Kept in the repo for audit; it is not part of content-ci. Mapping tables
live in tools/migrations/scenarios_v2_map.py. Run once:

  python3 tools/migrate_scenarios_v2.py

Changes per scenario:
  * event-level ``attach`` moves under ``client.attach`` (addendum §4.8)
  * inline ``subject``/``body`` become a static template under gen/templates/
  * every client message gets ``template`` (+ ``vars``) and, where a spec
    exists, ``gen_spec``; ``ref`` names messages that expectations point at
  * ``ingress: {doc: X}`` becomes ``{ref, file}`` or ``{ref, class, stratum, as}``
  * relation endpoints resolve to refs, pinned files or ``matter:<id>``;
    directions follow "a <kind> b" (addendum §8.2)
  * Correspondent reply templates move to gen/templates/replies/ and are
    referenced from ``expect.outbox[].reference_template``
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "migrations"))
from scenarios_v2_map import EV, FROM_FIX, IN, INLINE_SPEC, INSERT, REL  # noqa: E402
from templates_v2 import T  # noqa: E402

ORDER = ["name", "title", "seed", "profile", "gen", "transports", "status",
         "owner", "tags", "timeline", "expect"]
CLIENT_ORDER = ["ref", "persona", "channel", "claimed_from", "auth", "reply_to",
                "template", "gen_spec", "vars", "attach"]
TIME_RE = re.compile(r"^[0-9]{2}:[0-9]{2}(:[0-9]{2})?$")


class Dumper(yaml.SafeDumper):
    pass


def _str(d, s):
    if TIME_RE.match(s):
        return d.represent_scalar("tag:yaml.org,2002:str", s, style='"')
    if "\n" in s:
        return d.represent_scalar("tag:yaml.org,2002:str", s, style="|")
    return d.represent_str(s)


def _dict(d, m):
    flow = all(not isinstance(v, (dict, list)) for v in m.values()) and len(m) <= 6
    return d.represent_mapping("tag:yaml.org,2002:map", m.items(), flow_style=flow)


def _list(d, seq):
    flow = all(not isinstance(v, (dict, list)) for v in seq)
    return d.represent_sequence("tag:yaml.org,2002:seq", seq, flow_style=flow)


Dumper.add_representer(str, _str)
Dumper.add_representer(dict, _dict)
Dumper.add_representer(list, _list)


def ordered(m: dict, order: list[str]) -> dict:
    out = {k: m[k] for k in order if k in m}
    out.update({k: v for k, v in m.items() if k not in out})
    return out


def write_templates() -> None:
    tdir = ROOT / "gen" / "templates"
    rdir = tdir / "replies"
    rdir.mkdir(exist_ok=True)
    for name in ("g_status_update", "g_entity_answer", "g_bulk_digest",
                 "g_receipt_confirmation", "g_expedite_ack"):
        src = tdir / f"{name}.j2"
        if src.exists():
            src.rename(rdir / f"{name}.j2")
    for name, (purpose, body) in T.items():
        (tdir / f"{name}.j2").write_text(
            f"{{# Scripted inbound template: {purpose}. #}}\n{body}",
            encoding="utf-8")


def migrate(path: Path) -> None:
    s = yaml.safe_load(path.read_text(encoding="utf-8"))
    name = s["name"]
    tl = INSERT.get(name, []) + s["timeline"]
    offset = len(INSERT.get(name, []))
    new_tl = []
    for i, ev in enumerate(tl):
        orig = i - offset
        ev = dict(ev)
        if "ingress" in ev and orig >= 0:
            ev["ingress"] = IN[(name, orig)]
        if "client" in ev:
            c = dict(ev.pop("client"))
            attach = ev.pop("attach", None) or c.pop("attach", None) or []
            m = EV.get((name, orig))
            if "body" in ev:
                tname = name.lower()
                (ROOT / "gen" / "templates" / f"{tname}.j2").write_text(
                    f"{{# Scripted inbound template: hand-written anchor for "
                    f"{name} (moved from the scenario file). #}}\n"
                    f"Subject: {ev.pop('subject')}\n\n{ev.pop('body').rstrip()}\n",
                    encoding="utf-8")
                m = dict(template=tname)
                if name in INLINE_SPEC:
                    m["gen_spec"] = INLINE_SPEC[name]
            if m is None:
                raise SystemExit(f"no mapping for {name}[{orig}]")
            c.pop("template", None)
            for key in ("template", "gen_spec", "vars", "ref", "reply_to"):
                if key in m:
                    c[key] = m[key]
            if "persona" in m:
                c["persona"] = m["persona"]
            if "from_" in m:
                c["claimed_from"] = m["from_"]
            if c.get("claimed_from") in FROM_FIX:
                c["claimed_from"] = FROM_FIX[c["claimed_from"]]
            new_att = []
            for j, a in enumerate(attach):
                a = dict(a)
                a.update((m.get("att") or {}).get(j, {}))
                new_att.append(a)
            if new_att:
                c["attach"] = new_att
            ev["client"] = ordered(c, CLIENT_ORDER)
            if m.get("reply"):
                outbox = s["expect"].setdefault("outbox", [])
                if outbox:
                    outbox[0]["reference_template"] = m["reply"]
        new_tl.append(ordered(ev, ["at", "ingress", "client", "fault"]))
    s["timeline"] = new_tl
    if name in REL:
        s["expect"]["relations"] = REL[name]
    s["status"] = s.get("status", "draft")
    path.write_text(yaml.dump(ordered(s, ORDER), Dumper=Dumper, sort_keys=False,
                              allow_unicode=True, width=100),
                    encoding="utf-8")


def main() -> int:
    write_templates()
    for p in sorted((ROOT / "scenarios").glob("*/*.yaml")):
        migrate(p)
    print("migrated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
