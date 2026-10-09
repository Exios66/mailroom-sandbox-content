#!/usr/bin/env python3
"""Build the release bundle locally (replaces the GitHub Actions release job).

Writes, under release/:
  mailroom-sandbox-content-vX.Y.Z.tar.zst   deterministic content bundle
  SHA256SUMS                                tarball + content.json (bare names)
  content.json                              copy, so the assets sit together
  BUILD_INFO                                zstandard version and the sha256 of the
                                            uncompressed tar (audit aid, see below)

The tarball is reproducible: files come from ``git ls-files`` at HEAD (so
untracked or ignored files never ship), plus the compiled
dist/registry.yaml; entries are sorted, with fixed mtime, owner and modes.
The same commit always yields the same sha256, which is what
mailroom-reloaded pins in sandbox/content.lock.

Requires the ``zstandard`` Python module; the zstd binary is not used because
its bytes can differ. The compressed bytes also depend on the zstandard
version: 0.25.0 and 0.23.0 emit different bytes for the same tar. So the
version is pinned (tools/requirements.txt, PINNED_ZSTANDARD), ``--release``
refuses any other version, and BUILD_INFO records ``tar_sha256`` (the
uncompressed tar, independent of the compressor) so two builds can be compared
even when their .tar.zst bytes differ. The bytes of the *published* asset are
what a downloader verifies against sandbox/content.lock.

Run tools/validate.py first so dist/registry.yaml is fresh; tools/release.sh
does both.

  python3 tools/build_bundle.py [--out release] [--release]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDE_PREFIXES = (".github/", ".githooks/", "release/", ".cache/")
MTIME = 1767225600  # 2026-01-01T00:00:00Z: fixed so bundles are reproducible
PINNED_ZSTANDARD = "0.25.0"  # keep equal to tools/requirements.txt (a test checks)
ZSTD_LEVEL = 19


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], check=True,
                         capture_output=True).stdout.decode()
    files = [f for f in out.split("\0") if f and not f.startswith(EXCLUDE_PREFIXES)]
    return sorted(set(files) | {"dist/registry.yaml"})


def build_tar(root: Path, files: list[str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for rel in files:
            data = (root / rel).read_bytes()
            info = tarfile.TarInfo(rel)
            info.size = len(data)
            info.mtime = MTIME
            info.mode = 0o755 if rel.endswith(".sh") else 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def zstandard_version() -> str:
    """Return the installed zstandard version, or exit if the module is missing."""
    try:
        import zstandard
    except ImportError:
        raise SystemExit("need the zstandard module (pip install -r tools/requirements.txt)")
    return zstandard.__version__


def check_zstandard(release: bool, version: str | None = None) -> str:
    """Return the zstandard version; under ``release`` exit unless it is the pinned one."""
    version = version or zstandard_version()
    if release and version != PINNED_ZSTANDARD:
        raise SystemExit(
            f"release builds need zstandard=={PINNED_ZSTANDARD} (found {version}): the "
            "compressed bytes, and so the sha256 pinned in content.lock, change with the "
            "version. Run: pip install -r tools/requirements.txt")
    return version


def build_info(version: str, tar: bytes) -> str:
    """Return the BUILD_INFO text: compressor facts plus the uncompressed tar digest."""
    return json.dumps({"compressor": "zstandard", "level": ZSTD_LEVEL,
                       "tar_sha256": hashlib.sha256(tar).hexdigest(),
                       "zstandard": version}, indent=1, sort_keys=True) + "\n"


def zstd(data: bytes) -> bytes:
    """One compressor path only: the zstd binary and the module can emit
    different bytes, which would change the sha256 pinned in content.lock."""
    import zstandard
    return zstandard.ZstdCompressor(level=ZSTD_LEVEL, threads=0,
                                    write_content_size=True).compress(data)


def main(argv: list[str] | None = None) -> int:
    """Write the bundle, metadata, and checksums; return 1 if the registry is missing."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--release", action="store_true",
                    help="refuse a zstandard version other than the pinned one")
    args = ap.parse_args(argv)
    zver = check_zstandard(args.release)
    root = args.root
    out = args.out or root / "release"
    if not (root / "dist" / "registry.yaml").is_file():
        print("dist/registry.yaml missing; run tools/validate.py first", file=sys.stderr)
        return 1
    version = json.loads((root / "content.json").read_text())["version"]
    name = f"mailroom-sandbox-content-v{version}.tar.zst"
    tar = build_tar(root, tracked_files(root))
    blob = zstd(tar)
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_bytes(blob)
    (out / "BUILD_INFO").write_text(build_info(zver, tar))
    shutil.copy(root / "content.json", out / "content.json")
    sums = "".join(f"{hashlib.sha256((out / f).read_bytes()).hexdigest()}  {f}\n"
                   for f in (name, "content.json"))
    (out / "SHA256SUMS").write_text(sums)
    print(sums, end="")
    print(f"zstandard {zver} (pinned {PINNED_ZSTANDARD}); see BUILD_INFO", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
