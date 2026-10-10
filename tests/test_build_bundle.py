"""Reproducibility and release-guard tests for tools/build_bundle.py (plan K-01).

The bundle build must be byte-reproducible from the same commit, and
``--release`` must refuse a ``zstandard`` version other than the pinned one
(the compressed bytes, and so the sha256 pinned in ``sandbox/content.lock``,
change with the compressor version). Each test builds from a throwaway git
repository; nothing touches the network, the real repo's tags, or a real
mailroom-reloaded checkout.
"""

import hashlib
import io
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools import build_bundle


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "build_bundle.py"
BUNDLE_NAME = "mailroom-sandbox-content-v0.0.0.tar.zst"


def sha256(path: Path) -> str:
    """Return the hex sha256 of a file's bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_tar_names(bundle: Path) -> list[str]:
    """Decompress a .tar.zst bundle and return its member names."""
    import zstandard
    tar_bytes = zstandard.ZstdDecompressor().decompress(bundle.read_bytes())
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tar:
        return tar.getnames()


class BuildBundleReproTests(unittest.TestCase):
    def setUp(self):
        """Create a small committed git fixture with a registry and content.json."""
        temporary = TemporaryDirectory(prefix="build-bundle ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "tree"
        (self.root / "clients").mkdir(parents=True)
        (self.root / "dist").mkdir()
        (self.root / "release").mkdir()
        (self.root / "content.json").write_text('{"version": "0.0.0"}\n', encoding="utf-8")
        (self.root / "clients" / "clients.csv").write_text("client_id\ncedar\n", encoding="utf-8")
        (self.root / "dist" / "registry.yaml").write_text("registry: {}\n", encoding="utf-8")
        (self.root / "release" / "junk.txt").write_text("excluded\n", encoding="utf-8")
        # Git must not read the user's global/system config or a pre-push hook's exports.
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith("GIT_")}
        self.env.update(
            GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
            GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.invalid",
            GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.invalid")
        for command in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "fixture"]):
            subprocess.run(["git", *command], cwd=self.root, env=self.env, check=True,
                           capture_output=True)

    def build(self, out: Path, *arguments: str):
        """Run the real build_bundle.py CLI against the fixture into ``out``."""
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), "--out", str(out),
             *arguments],
            cwd=self.root, env=self.env, capture_output=True, text=True, timeout=120)

    def test_two_builds_of_the_same_commit_are_byte_identical(self):
        """Verify the bundle sha256 and BUILD_INFO tar_sha256 match across two builds."""
        out1, out2 = self.base / "out1", self.base / "out2"
        first, second = self.build(out1), self.build(out2)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(sha256(out1 / BUNDLE_NAME), sha256(out2 / BUNDLE_NAME))
        info1 = json.loads((out1 / "BUILD_INFO").read_text(encoding="utf-8"))
        info2 = json.loads((out2 / "BUILD_INFO").read_text(encoding="utf-8"))
        self.assertEqual(info1["tar_sha256"], info2["tar_sha256"])
        self.assertEqual(info1["zstandard"], build_bundle.PINNED_ZSTANDARD)

    def test_excluded_and_untracked_files_never_ship(self):
        """Verify release/, .cache/ and untracked files stay out of the bundle."""
        (self.root / "untracked.txt").write_text("nope\n", encoding="utf-8")
        out = self.base / "out3"
        result = self.build(out)
        self.assertEqual(result.returncode, 0, result.stderr)
        names = read_tar_names(out / BUNDLE_NAME)
        self.assertNotIn("release/junk.txt", names)
        self.assertNotIn("untracked.txt", names)
        self.assertIn("content.json", names)
        self.assertIn("dist/registry.yaml", names)

    def test_missing_registry_is_refused(self):
        """Verify a build without dist/registry.yaml exits 1 with the remedy."""
        (self.root / "dist" / "registry.yaml").unlink()
        result = self.build(self.base / "out4")
        self.assertEqual(result.returncode, 1)
        self.assertIn("run tools/validate.py first", result.stderr)


class ReleaseVersionGuardTests(unittest.TestCase):
    def test_pin_matches_requirements(self):
        """Verify PINNED_ZSTANDARD equals the exact pin in tools/requirements.txt."""
        requirements = (REPO_ROOT / "tools" / "requirements.txt").read_text(encoding="utf-8")
        active = [
            line.split("#", 1)[0].strip()
            for line in requirements.splitlines()
        ]
        pins = [
            line for line in active
            if re.match(r"zstandard\s*(?:[=<>!~;\[]|$)", line, re.IGNORECASE)
        ]
        self.assertEqual(pins, [f"zstandard=={build_bundle.PINNED_ZSTANDARD}"])

    def test_release_refuses_a_non_pinned_version(self):
        """Verify --release rejects another zstandard version with the clear message."""
        with self.assertRaises(SystemExit) as caught:
            build_bundle.check_zstandard(True, "0.23.0")
        message = str(caught.exception)
        self.assertIn(f"release builds need zstandard=={build_bundle.PINNED_ZSTANDARD}", message)
        self.assertIn("0.23.0", message)
        self.assertIn("content.lock", message)

    def test_non_release_accepts_any_version(self):
        """Verify a non-release build returns any version without refusing."""
        self.assertEqual(build_bundle.check_zstandard(False, "0.23.0"), "0.23.0")

    def test_main_release_refuses_when_the_installed_version_is_wrong(self):
        """Verify main(--release) refuses when the installed zstandard is not pinned."""
        with TemporaryDirectory() as tmp, \
                patch.object(build_bundle, "zstandard_version", return_value="0.23.0"):
            with self.assertRaises(SystemExit) as caught:
                build_bundle.main(["--root", tmp, "--out", str(Path(tmp) / "out"),
                                   "--release"])
        self.assertIn("release builds need zstandard==", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
