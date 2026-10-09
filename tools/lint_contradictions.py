#!/usr/bin/env python3
"""Contradiction lint for scenario expectations (plan item K-03, stage 1).

Groups scenarios by (client template set, expect.intent) and reports groups
whose members disagree on:

  * expect.outbox: compared as the set of (intent, state) pairs, so an empty
    list and a non-empty list always disagree. A scenario with no ``outbox``
    key asserts nothing and is not compared.
  * priority: the highest ``expect.signals[].priority`` of the scenario
    (low < normal < high < critical). A scenario with no priority-bearing
    signal is not compared.

Grouping key: the sorted set of distinct ``timeline[].client.template``
values, plus ``expect.intent``. Scenarios with no client message (ingress or
fault only) are skipped. Companion messages are part of the template set, so
a scenario only groups with scenarios that send exactly the same templates.
Cross-template comparisons are out of scope for this lint.

A scenario is exempt from comparison when it carries a top-level, non-empty
string ``contrast: "<reason>"``. The scenario schema requires the reason to
contain at least one non-whitespace character.

Modes: default prints WARN lines and exits 0; ``--strict`` exits 1 when any
unexempted disagreement exists. Exit 2 when a scenario file cannot be read.

Usage:
  python3 tools/lint_contradictions.py [--root DIR] [--strict]
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple, Optional

ROOT = Path(__file__).resolve().parent.parent

PRIORITY_RANK = {"low": 0, "normal": 1, "high": 2, "critical": 3}


class Finding(NamedTuple):
    """One disagreement: members of a group that differ on one field."""
    templates: tuple          # sorted distinct client templates
    intent: str               # expect.intent shared by the group
    field: str                # "outbox" or "priority"
    members: tuple            # ((scenario_name, label), ...), sorted by name


class Stats(NamedTuple):
    scenarios: int
    groups: int               # groups with two or more comparable members
    exempt: tuple             # ((scenario_name, reason), ...)
    skipped: tuple            # scenario names with no client message


# ----------------------------------------------------------- pure functions


def group_key(scenario: dict) -> Optional[tuple]:
    """(sorted client templates, intent), or None when not groupable."""
    expect = scenario.get("expect") or {}
    intent = expect.get("intent")
    templates = set()
    for item in scenario.get("timeline") or []:
        client = item.get("client") if isinstance(item, dict) else None
        if isinstance(client, dict) and client.get("template"):
            templates.add(str(client["template"]))
    if not intent or not templates:
        return None
    return (tuple(sorted(templates)), str(intent))


def exempt_reason(scenario: dict) -> Optional[str]:
    """The top-level ``contrast`` reason, or None when absent or blank."""
    reason = scenario.get("contrast")
    if isinstance(reason, str) and reason.strip():
        return reason.strip()
    return None


def outbox_signature(scenario: dict) -> Optional[frozenset]:
    """Set of (intent, state) for expect.outbox; None when the key is absent."""
    expect = scenario.get("expect") or {}
    if "outbox" not in expect:
        return None
    items = expect.get("outbox") or []
    return frozenset((item.get("intent"), item.get("state"))
                     for item in items if isinstance(item, dict))


def outbox_label(signature: frozenset) -> str:
    """Format an outbox signature as sorted intent/state pairs, or [] if empty."""
    if not signature:
        return "[]"
    pairs = sorted(signature, key=lambda p: (str(p[0]), str(p[1])))
    return "[" + ", ".join(f"{intent}/{state}" for intent, state in pairs) + "]"


def priority_signature(scenario: dict) -> Optional[str]:
    """Highest signal priority, or None when no signal carries one."""
    expect = scenario.get("expect") or {}
    ranked = [PRIORITY_RANK[s["priority"]]
              for s in expect.get("signals") or []
              if isinstance(s, dict) and s.get("priority") in PRIORITY_RANK]
    if not ranked:
        return None
    top = max(ranked)
    return next(name for name, rank in PRIORITY_RANK.items() if rank == top)


def find_disagreements(scenarios: list) -> tuple:
    """Return (findings, stats) for a list of scenario dicts. Pure."""
    groups = defaultdict(list)
    exempt = []
    skipped = []
    ordered = sorted(scenarios, key=lambda s: str(s.get("name", "")))
    for scenario in ordered:
        name = str(scenario.get("name", ""))
        key = group_key(scenario)
        if key is None:
            skipped.append(name)
            continue
        reason = exempt_reason(scenario)
        if reason is not None:
            exempt.append((name, reason))
            continue
        groups[key].append(scenario)

    findings = []
    comparable = 0
    for key in sorted(groups):
        members = groups[key]
        if len(members) < 2:
            continue
        comparable += 1
        for field, signature, label in (
                ("outbox", outbox_signature, outbox_label),
                ("priority", priority_signature, str)):
            values = [(str(m.get("name", "")), signature(m)) for m in members]
            values = [(n, v) for n, v in values if v is not None]
            if len({v for _, v in values}) > 1:
                findings.append(Finding(
                    templates=key[0], intent=key[1], field=field,
                    members=tuple((n, label(v)) for n, v in values)))

    findings.sort(key=lambda f: (f.members[0][0], f.field))
    stats = Stats(scenarios=len(ordered), groups=comparable,
                  exempt=tuple(exempt), skipped=tuple(skipped))
    return findings, stats


def format_finding(finding: Finding) -> str:
    """Return a warning naming the disputed field, group, and member values."""
    members = ", ".join(f"{name}={label}" for name, label in finding.members)
    templates = ",".join(finding.templates)
    return (f"WARN: {finding.field} disagreement in group "
            f"template=[{templates}] intent={finding.intent}: {members}")


# ------------------------------------------------------------------- CLI


def load_scenarios(root: Path) -> list:
    """Load scenarios/<series>/*.yaml under root, sorted by path."""
    import yaml  # deferred so the pure functions above need no PyYAML

    scenario_dir = root / "scenarios"
    if not scenario_dir.is_dir():
        raise ValueError(f"{scenario_dir}: scenarios directory is missing or not a directory")
    loaded = []
    for path in sorted(scenario_dir.glob("*/*.yaml")):
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        if not isinstance(data, dict):
            raise ValueError(f"{path}: top level must be a mapping")
        loaded.append(data)
    return loaded


def main(argv: Optional[list] = None) -> int:
    """Report disagreements; return 1 for strict failures, 2 for read errors, else 0."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT,
                        help="content repo root (default: this checkout)")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 when any unexempted disagreement exists")
    args = parser.parse_args(argv)

    import yaml

    try:
        scenarios = load_scenarios(args.root)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: cannot load scenarios: {exc}", file=sys.stderr)
        return 2

    findings, stats = find_disagreements(scenarios)
    for finding in findings:
        print(format_finding(finding))
    print(f"lint_contradictions: scenarios={stats.scenarios} "
          f"comparable_groups={stats.groups} disagreements={len(findings)} "
          f"exempt={len(stats.exempt)} no_client_message={len(stats.skipped)}")
    return 1 if (args.strict and findings) else 0


if __name__ == "__main__":
    sys.exit(main())
