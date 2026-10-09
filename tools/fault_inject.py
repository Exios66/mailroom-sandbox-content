"""Fault-inject a copy of the content repo; record how tools/validate.py reacts.

Usage: python3 -I tools/fault_inject.py <repo root> <empty scratch dir>
Seed for workstream K-04 (docs/superpowers/plans/2026-10-09-mailroom-core-plan.md in
mailroom-reloaded). Read-only against the repo: every mutation runs in a copy.
must_fail mutations that report CRASH or MISSED are defects; csv_crlf is a
legitimate accept (the csv module handles CRLF).

Outcome classes:
  CLEAN-FAIL       exit > 0, no traceback or internal error (clean rejection)
  CRASH            traceback, internal error, or termination by signal
  MISSED           exit 0 (bad input accepted)
  EXPECTED-ACCEPT  exit 0 for csv_crlf (valid input accepted)
"""
import pathlib
import shutil
import subprocess
import sys


def fresh(src, work, tag):
    """Copy src into work/tag, excluding Git metadata and generated artifacts."""
    dst = work / tag
    shutil.copytree(
        src, dst, ignore=shutil.ignore_patterns(".git", "release", ".cache", "__pycache__")
    )
    return dst


def first(p, pat):
    """Return the first path in sorted glob matches; raise if none match."""
    return sorted(p.glob(pat))[0]


def m_bad_yaml(r):
    """Replace a series A scenario with malformed YAML in scratch root r."""
    first(r, "scenarios/A/*.yaml").write_text("name: [unclosed\n  - x: {", encoding="utf-8")


def m_non_utf8(r):
    """Write invalid UTF-8 bytes to a series A scenario in scratch root r."""
    first(r, "scenarios/A/*.yaml").write_bytes(b"name: \xff\xfe\x00bad\n")


def m_empty_yaml(r):
    """Empty a series B scenario file in scratch root r."""
    first(r, "scenarios/B/*.yaml").write_text("", encoding="utf-8")


def m_yaml_list_root(r):
    """Replace a series B scenario mapping with a YAML list in r."""
    first(r, "scenarios/B/*.yaml").write_text("- a\n- b\n", encoding="utf-8")


def m_dup_scenario_name(r):
    """Copy one series C scenario over another to duplicate its name in r."""
    a = sorted(r.glob("scenarios/C/*.yaml"))
    a[1].write_text(a[0].read_text(encoding="utf-8"), encoding="utf-8")


def m_csv_bom_header(r):
    """Prepend a UTF-8 BOM to the client CSV header in scratch root r."""
    p = r / "clients/clients.csv"
    p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())


def m_csv_crlf(r):
    """Convert client CSV newlines to valid CRLF line endings in r."""
    p = r / "clients/clients.csv"
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))


def m_csv_empty(r):
    """Empty the relation truth CSV in scratch root r."""
    (r / "relations/relations_truth.csv").write_text("", encoding="utf-8")


def m_content_json_invalid(r):
    """Replace content.json with invalid JSON in scratch root r."""
    (r / "content.json").write_text("{not json", encoding="utf-8")


def m_content_json_missing_key(r):
    """Remove schema_version from content.json in scratch root r."""
    import json
    p = r / "content.json"
    d = json.loads(p.read_text())
    d.pop("schema_version")
    p.write_text(json.dumps(d))


def m_content_json_version_type(r):
    """Set the content version to an integer in scratch root r."""
    import json
    p = r / "content.json"
    d = json.loads(p.read_text())
    d["version"] = 5
    p.write_text(json.dumps(d))


def m_missing_template(r):
    """Delete the first inbound template in scratch root r."""
    first(r, "gen/templates/*.j2").unlink()


def m_template_syntax(r):
    """Replace an inbound template with malformed Jinja syntax in r."""
    first(r, "gen/templates/*.j2").write_text("Subject: {{ unclosed\n{% if %}", encoding="utf-8")


def m_template_undefined_var(r):
    """Reference an undefined variable in an inbound template in r."""
    first(r, "gen/templates/*.j2").write_text("Subject: hi\n{{ no_such_var }}", encoding="utf-8")


def m_real_domain_leak(r):
    """Append a real-domain URL to an inbound template in scratch root r."""
    p = first(r, "gen/templates/*.j2")
    p.write_text(p.read_text(encoding="utf-8") + "\nSee https://www.chase.com/login\n", encoding="utf-8")


def m_real_phone(r):
    """Replace the first synthetic client phone prefix with a real one in r."""
    p = r / "clients/clients.csv"
    p.write_text(p.read_text(encoding="utf-8").replace("+1-555-01", "+1-212-55", 1), encoding="utf-8")


def m_missing_attachment_file(r):
    """Delete the first synthetic attachment in scratch root r."""
    first(r, "attachments/synthetic/*").unlink()


def m_attachment_hash_mismatch(r):
    """Append bytes to a synthetic PDF without updating its manifest in r."""
    p = first(r, "attachments/synthetic/*.pdf")
    p.write_bytes(p.read_bytes() + b"\n%tamper\n")


def m_lookalike_in_registry_source(r):
    """Add an adversary domain to the client domain registry source in r."""
    import csv
    dom = next(csv.DictReader(open(r / "adversary/lookalike_domains.csv", encoding="utf-8")))["domain"]
    p = r / "clients/client_domains.csv"
    lines = p.read_text(encoding="utf-8").splitlines()
    hdr = lines[0].split(",")
    row = lines[1].split(",")
    row[hdr.index("domain")] = dom
    lines.append(",".join(row))
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def m_schema_file_corrupt(r):
    """Replace the scenario schema with invalid JSON in scratch root r."""
    (r / "schemas/scenario.v2.json").write_text("{ broken", encoding="utf-8")


def m_missing_dir(r):
    """Remove the taxonomy directory from scratch root r."""
    shutil.rmtree(r / "taxonomy")


def m_ids_ranges_corrupt(r):
    """Replace the ID allocation file with malformed YAML in r."""
    (r / "ids/ranges.yaml").write_text(": : :\n", encoding="utf-8")


def m_huge_scenario(r):
    """Append a five-million-character comment to a series D scenario in r."""
    p = first(r, "scenarios/D/*.yaml")
    p.write_text(p.read_text(encoding="utf-8") + "\n# " + "x" * 5_000_000 + "\n", encoding="utf-8")


def m_yaml_anchor_bomb(r):
    """Write nested YAML aliases with exponential expansion to a scenario in r."""
    bomb = "a: &a [x,x,x,x,x,x,x,x,x]\n"
    prev = "a"
    for i in range(9):
        bomb += f"{chr(98+i)}: &{chr(98+i)} [*{prev},*{prev},*{prev},*{prev},*{prev},*{prev},*{prev},*{prev},*{prev}]\n"
        prev = chr(98 + i)
    first(r, "scenarios/E/*.yaml").write_text(bomb, encoding="utf-8")


def m_symlink_escape(r):
    """Replace a synthetic attachment with a symlink to /etc/passwd in r."""
    p = first(r, "attachments/synthetic/*")
    p.unlink()
    p.symlink_to("/etc/passwd")


def m_short_row(r):
    """Truncate the second client CSV data row to three cells in r."""
    p = r / "clients/clients.csv"
    lines = p.read_text(encoding="utf-8").splitlines()
    lines[2] = ",".join(lines[2].split(",")[:3])
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def m_extra_columns(r):
    """Append two extra cells to the second client CSV data row in r."""
    p = r / "clients/clients.csv"
    lines = p.read_text(encoding="utf-8").splitlines()
    lines[2] += ",extra,cells"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def m_duplicate_client_key(r):
    """Append a duplicate of the first client CSV data row in r."""
    p = r / "clients/clients.csv"
    lines = p.read_text(encoding="utf-8").splitlines()
    lines.append(lines[1])
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def m_nul_in_csv(r):
    """Append a row containing a NUL byte to the client CSV in r."""
    p = r / "clients/clients.csv"
    p.write_bytes(p.read_bytes() + b"\x00garbage,row\n")


MUTATIONS = [(n[2:], f) for n, f in sorted(globals().items()) if n.startswith("m_") and callable(f)]


def run_validator(root):
    """Run the same strict checks for the baseline and every mutation."""
    return subprocess.run(
        [sys.executable, "tools/validate.py", "--strict-coverage"],
        cwd=root, capture_output=True, text=True, timeout=120,
    )


def classify(src, work, name, fn):
    """Apply one mutation to a fresh copy of src and classify validator behaviour."""
    root = fresh(src, work, name)
    try:
        fn(root)
    except Exception as e:  # noqa: BLE001
        return (name, "SETUP-ERR", str(e)[:80])
    try:
        proc = run_validator(root)
    except subprocess.TimeoutExpired:
        return (name, "HANG", ">120s")
    err = proc.stderr + proc.stdout
    if "Traceback" in err or "ERROR internal:" in err:
        last = [ln for ln in err.strip().splitlines() if ln.strip()][-1][:110]
        return (name, "CRASH", last)
    if proc.returncode == 0:
        result = "EXPECTED-ACCEPT" if name == "csv_crlf" else "MISSED"
        return (name, result, "exit 0")
    if proc.returncode < 0:
        return (name, "CRASH", f"signal {-proc.returncode}")
    return (name, "CLEAN-FAIL", f"exit {proc.returncode}")


def main(argv):
    """Validate paths and baseline before running and reporting mutations."""
    src = pathlib.Path(argv[1]).resolve()
    work = pathlib.Path(argv[2]).resolve()
    if work == src or src in work.parents:
        print("ERROR: scratch directory must be outside the source tree", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    baseline = fresh(src, work, "baseline")
    try:
        proc = run_validator(baseline)
    except subprocess.TimeoutExpired:
        print("BASELINE-FAIL: validation timed out (>120s)", file=sys.stderr)
        return 1
    if proc.returncode != 0:
        print(f"BASELINE-FAIL: exit {proc.returncode}", file=sys.stderr)
        print((proc.stdout + proc.stderr).strip(), file=sys.stderr)
        return 1
    results = [classify(src, work, name, fn) for name, fn in MUTATIONS]
    w = max(len(r[0]) for r in results)
    for n, c, d in results:
        print(f"{n:<{w}}  {c:<15}  {d}")
    from collections import Counter
    print(Counter(c for _, c, _ in results))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
