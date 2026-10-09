"""Shell-behaviour tests for tools/ci.sh (strata drift) and tools/release.sh.

Each test builds a throwaway git repository in a TemporaryDirectory, copies in
the real script under test, and stubs everything heavy: the Python interpreter
for ci.sh (via PYTHON), tools/ci.sh and tools/build_bundle.py for release.sh,
and gh (on PATH). Nothing touches the network, the real repo's tags, or a real
mailroom-reloaded checkout. Git ignores the user's global and system config so
the tests do not depend on it (or on GPG tag signing).
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
TAG = "v9.9.9"
DRIFT_REMEDY = "tools/ci.sh --skip-drift"
RELOADED_REMEDY = "MAILROOM_RELOADED=/path/to/mailroom-reloaded tools/ci.sh"

# Stand-in for the Python interpreter that answers only the calls ci.sh makes.
FAKE_PYTHON = """#!/bin/sh
printf '%s\\n' "$*" >> "$TEST_PY_LOG"
case "$*" in
  *strata.source.json*) echo 0123456789abcdef0123456789abcdef01234567 ;;
  *sync_strata.py*) echo "sync_strata stub: drift found"; exit "${TEST_DRIFT_EXIT:-0}" ;;
esac
exit 0
"""

# Stand-in for tools/ci.sh inside a release tree: records its arguments, writes
# the registry the validator would, and exits as told.
FAKE_CI = """#!/bin/sh
printf 'argc=%s args=[%s]\\n' "$#" "$*" >> "$TEST_CI_LOG"
mkdir -p dist
printf '%s\\n' "$TEST_REGISTRY" > dist/registry.yaml
exit "${TEST_CI_EXIT:-0}"
"""

FAKE_BUNDLE = """import os
import pathlib
import sys

out = pathlib.Path(sys.argv[sys.argv.index("--out") + 1])
with open(os.environ["TEST_BUNDLE_LOG"], "a", encoding="utf-8") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
if int(os.environ.get("TEST_BUNDLE_EXIT", "0")):
    sys.exit(int(os.environ["TEST_BUNDLE_EXIT"]))
out.mkdir(exist_ok=True)
for name in ("mailroom-sandbox-content-v9.9.9.tar.zst", "SHA256SUMS",
             "content.json", "BUILD_INFO"):
    (out / name).write_text("stub\\n", encoding="utf-8")
"""

# Stand-in for the gh CLI: logs every call; `release create` exits as told.
FAKE_GH = """#!/bin/sh
printf '%s\\n' "$*" >> "$TEST_GH_LOG"
if [ "$1" = release ]; then exit "${TEST_GH_EXIT:-0}"; fi
exit 0
"""


def write_executable(path: Path, text: str) -> None:
    """Write a UTF-8 script with executable permissions, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


class GitSandbox(unittest.TestCase):
    """Common setup: a temporary directory, isolated git config, and helpers."""

    def setUp(self):
        """Create temporary logs and an isolated Git environment for script tests."""
        temporary = TemporaryDirectory(prefix="release scripts ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.log = self.base / "logs"
        self.log.mkdir()
        self.env = {key: value for key, value in os.environ.items()
                    # A pre-push hook exports these; they would retarget git.
                    if not key.startswith("GIT_") and key not in ("MAILROOM_RELOADED", "SKIP_DRIFT")}
        self.env.update(
            GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
            GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.invalid",
            GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.invalid",
            GIT_TERMINAL_PROMPT="0", TEST_PY_LOG=str(self.log / "py.txt"),
            TEST_CI_LOG=str(self.log / "ci.txt"), TEST_BUNDLE_LOG=str(self.log / "bundle.txt"),
            TEST_GH_LOG=str(self.log / "gh.txt"))

    def git(self, *args, cwd):
        """Run Git in the fixture environment, capturing output and raising on failure."""
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True,
                              capture_output=True, text=True)

    def read_log(self, name):
        """Return a fixture log as text, or an empty string when it is absent."""
        path = self.log / name
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def tags(self, cwd):
        """Return the tag names in the temporary Git repository."""
        return self.git("tag", "--list", cwd=cwd).stdout.split()

    def run_script(self, cwd, script, *arguments, env=None):
        """Run a shell script with captured output and the fixture environment."""
        return subprocess.run(["sh", str(script), *arguments], cwd=cwd,
                              env=self.env if env is None else env,
                              capture_output=True, text=True, timeout=60, check=False)


class CiDriftTests(GitSandbox):
    def setUp(self):
        """Create a temporary CI checkout using a stub Python interpreter."""
        super().setUp()
        self.root = self.base / "tree"
        (self.root / "tools").mkdir(parents=True)
        (self.root / "scenarios").mkdir()
        (self.root / "scenarios" / "scenarios_index.csv").write_text("id\n", encoding="utf-8")
        shutil.copyfile(REPO_ROOT / "tools" / "ci.sh", self.root / "tools" / "ci.sh")
        self.fake_python = self.base / "bin" / "fakepython"
        write_executable(self.fake_python, FAKE_PYTHON)
        self.env["PYTHON"] = str(self.fake_python)
        self.git("init", "-q", cwd=self.root)

    def ci(self, *arguments, env=None):
        """Run the copied CI script with the requested arguments and environment."""
        return self.run_script(self.root, self.root / "tools" / "ci.sh", *arguments, env=env)

    def test_fetch_failure_prints_remedies_and_exits_nonzero(self):
        # A cached checkout whose origin does not exist: the fetch fails with no
        # network access at all, deterministically.
        """Verify failed strata fetches stop CI and print both documented remedies."""
        cache = self.root / ".cache" / "mailroom-reloaded"
        self.git("init", "-q", str(cache), cwd=self.root)
        self.git("remote", "add", "origin", str(self.base / "no-such-repo"), cwd=cache)
        result = self.ci()
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("strata drift: cannot fetch mailroom-reloaded commit", output)
        self.assertIn(DRIFT_REMEDY, output)
        self.assertIn(RELOADED_REMEDY, output)
        self.assertNotIn("all checks passed", output)
        self.assertNotIn("sync_strata", self.read_log("py.txt"))

    def test_skip_drift_passes_without_fetching(self):
        """Verify an explicit drift skip avoids fetching and checking the catalog."""
        result = self.ci("--skip-drift")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("strata drift: SKIPPED", result.stdout)
        self.assertIn("content-ci: all checks passed", result.stdout)
        self.assertFalse((self.root / ".cache").exists())
        self.assertNotIn("sync_strata", self.read_log("py.txt"))

    def test_real_drift_fails_with_its_own_output(self):
        """Verify catalog drift preserves its exit status and diagnostic output."""
        reloaded = self.base / "reloaded"
        reloaded.mkdir()
        self.env.update(MAILROOM_RELOADED=str(reloaded), TEST_DRIFT_EXIT="3")
        result = self.ci()
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("sync_strata stub: drift found", result.stdout)
        self.assertNotIn("all checks passed", result.stdout)
        self.assertNotIn("cannot fetch", result.stdout + result.stderr)

    def test_checkout_path_from_environment_is_used_and_clean_drift_passes(self):
        """Verify a configured consumer checkout passes drift checks without a cache fetch."""
        reloaded = self.base / "reloaded"
        reloaded.mkdir()
        self.env.update(MAILROOM_RELOADED=str(reloaded), TEST_DRIFT_EXIT="0")
        result = self.ci()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("content-ci: all checks passed", result.stdout)
        self.assertIn(f"--from {reloaded} --check", self.read_log("py.txt"))
        self.assertFalse((self.root / ".cache").exists())


class ReleaseScriptTests(GitSandbox):
    def setUp(self):
        """Create a clean temporary main branch with stub CI, bundle, and GitHub commands."""
        super().setUp()
        self.root = self.base / "release-tree"
        (self.root / "tools").mkdir(parents=True)
        shutil.copyfile(REPO_ROOT / "tools" / "release.sh", self.root / "tools" / "release.sh")
        write_executable(self.root / "tools" / "ci.sh", FAKE_CI)
        write_executable(self.root / "tools" / "build_bundle.py", FAKE_BUNDLE)
        (self.root / "content.json").write_text('{"version": "9.9.9"}\n', encoding="utf-8")
        (self.root / ".gitignore").write_text("dist/\nrelease/\n", encoding="utf-8")
        self.bin = self.base / "bin"
        write_executable(self.bin / "gh", FAKE_GH)
        self.env.update(PYTHON=sys.executable, TEST_REGISTRY="fresh",
                        PATH=f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}")
        self.git("init", "-q", cwd=self.root)
        self.git("symbolic-ref", "HEAD", "refs/heads/main", cwd=self.root)
        self.git("add", "-A", cwd=self.root)
        self.git("commit", "-q", "-m", "release fixture", cwd=self.root)

    def release(self, *arguments, env=None):
        """Run the copied release script against the temporary repository."""
        return self.run_script(self.root, self.root / "tools" / "release.sh", *arguments, env=env)

    def write_registry(self, text):
        """Write a registry fixture with the same trailing newline as the CI stub."""
        (self.root / "dist").mkdir(exist_ok=True)
        # The stub writes with a trailing newline; match it so "fresh" is fresh.
        (self.root / "dist" / "registry.yaml").write_text(text + "\n", encoding="utf-8")

    def test_skip_drift_argument_is_refused(self):
        """Verify releases reject a drift-skip flag before CI or tagging."""
        result = self.release("--skip-drift")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refuses --skip-drift", result.stderr)
        self.assertEqual(self.tags(self.root), [])
        self.assertEqual(self.read_log("ci.txt"), "")

    def test_skip_drift_variant_arguments_are_refused(self):
        """Verify alternate drift-skip flags also fail without creating a tag."""
        for argument in ("--no-drift", "--skip-drift=yes"):
            with self.subTest(argument=argument):
                result = self.release(argument)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(self.tags(self.root), [])

    def test_skip_drift_environment_is_refused(self):
        """Verify the SKIP_DRIFT environment variable blocks release before CI or tagging."""
        self.env["SKIP_DRIFT"] = "1"
        result = self.release()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refuses SKIP_DRIFT", result.stderr)
        self.assertEqual(self.tags(self.root), [])
        self.assertEqual(self.read_log("ci.txt"), "")

    def test_unknown_arguments_are_usage_errors(self):
        """Verify unsupported or extra release arguments produce status 2 and usage text."""
        for arguments in (("--frobnicate",), ("--push", "extra")):
            with self.subTest(arguments=arguments):
                result = self.release(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertIn("usage: tools/release.sh", result.stderr)

    def test_content_ci_runs_without_arguments_and_tags(self):
        """Verify release runs full CI, builds with the compressor pin, and creates a tag."""
        self.write_registry("fresh")
        result = self.release()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.read_log("ci.txt"), "argc=0 args=[]\n")
        self.assertEqual(self.tags(self.root), [TAG])
        self.assertIn("--out release --release", self.read_log("bundle.txt"))

    def test_stale_registry_is_refused_without_tagging(self):
        """Verify a changed registry digest blocks bundling and tagging."""
        self.write_registry("old")
        self.env["TEST_REGISTRY"] = "new"  # what a fresh compile would produce
        result = self.release()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("was stale", result.stderr)
        self.assertEqual(self.tags(self.root), [])
        self.assertEqual(self.read_log("bundle.txt"), "")

    def test_missing_registry_is_refused_without_tagging(self):
        """Verify an initially missing registry blocks tagging even after CI creates it."""
        self.env["TEST_REGISTRY"] = "new"
        result = self.release()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("was missing", result.stderr)
        self.assertEqual(self.tags(self.root), [])

    def test_content_ci_failure_stops_before_tagging(self):
        """Verify CI failure stops release before tagging and reports recovery guidance."""
        self.write_registry("fresh")
        self.env["TEST_CI_EXIT"] = "1"
        result = self.release()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("release refused: content-ci failed", result.stderr)
        self.assertIn("no tag was created and nothing was pushed", result.stderr)
        self.assertEqual(self.tags(self.root), [])

    def test_bundle_failure_stops_before_tagging(self):
        """Verify a bundle build failure leaves no release tag."""
        self.write_registry("fresh")
        self.env["TEST_BUNDLE_EXIT"] = "1"
        result = self.release()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no tag was created", result.stderr)
        self.assertEqual(self.tags(self.root), [])

    def test_push_failure_with_unknown_remote_preserves_tag(self):
        """Verify an unreachable remote produces no claims of absence or deletion advice."""
        self.write_registry("fresh")
        # No origin remote: the push fails offline before any release step.
        result = self.release("--push")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("remote tag state is unknown", result.stderr)
        self.assertIn(f"  git ls-remote --tags origin refs/tags/{TAG}\n", result.stderr)
        self.assertNotIn("locally only", result.stderr)
        self.assertNotIn("nothing", result.stderr)
        self.assertNotIn("git tag -d", result.stderr)
        self.assertEqual(self.tags(self.root), [TAG])
        self.assertEqual(self.read_log("gh.txt"), "")

    def test_rejected_push_with_absent_remote_tag_prints_recovery(self):
        """Verify deletion advice is offered only after confirming remote absence."""
        self.write_registry("fresh")
        remote = self.base / "remote.git"
        self.git("init", "-q", "--bare", str(remote), cwd=self.root)
        self.git("remote", "add", "origin", str(remote), cwd=self.root)
        write_executable(remote / "hooks" / "pre-receive", "#!/bin/sh\nexit 1\n")
        result = self.release("--push")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"tag {TAG} is absent from origin", result.stderr)
        self.assertIn("locally only", result.stderr)
        self.assertIn(f"  git push origin {TAG}\n", result.stderr)
        self.assertIn(f"  git tag -d {TAG}\n", result.stderr)
        self.assertEqual(self.tags(remote), [])
        self.assertEqual(self.tags(self.root), [TAG])
        self.assertEqual(self.read_log("gh.txt"), "")

    def test_push_reports_failure_after_publishing_tag(self):
        """Verify a lost push acknowledgement does not suggest deleting the published tag."""
        self.write_registry("fresh")
        remote = self.base / "remote.git"
        self.git("init", "-q", "--bare", str(remote), cwd=self.root)
        self.git("remote", "add", "origin", str(remote), cwd=self.root)
        self.env["TEST_REAL_GIT"] = shutil.which("git")
        write_executable(self.bin / "git", """#!/bin/sh
if [ "$1" = push ]; then
    "$TEST_REAL_GIT" "$@" || exit "$?"
    exit 1
fi
exec "$TEST_REAL_GIT" "$@"
""")
        result = self.release("--push")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"tag {TAG} exists on origin", result.stderr)
        self.assertNotIn("locally only", result.stderr)
        self.assertNotIn("nothing", result.stderr)
        self.assertNotIn("git tag -d", result.stderr)
        self.assertEqual(self.tags(remote), [TAG])
        self.assertEqual(self.tags(self.root), [TAG])
        self.assertEqual(self.read_log("gh.txt"), "")

    def test_push_and_gh_release_success_path(self):
        """Verify release pushes to a local bare remote and invokes the GitHub stub."""
        self.write_registry("fresh")
        remote = self.base / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True, env=self.env)
        self.git("remote", "add", "origin", str(remote), cwd=self.root)
        result = self.release("--push")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(TAG, subprocess.run(["git", "ls-remote", "--tags", str(remote)],
                                          env=self.env, capture_output=True, text=True,
                                          check=True).stdout)
        self.assertIn(f"release create {TAG} release/mailroom-sandbox-content-{TAG}.tar.zst",
                      self.read_log("gh.txt"))

    def test_gh_release_failure_prints_copyable_retry(self):
        """Verify GitHub release failure reports the pushed tag and a complete retry command."""
        self.write_registry("fresh")
        remote = self.base / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True, env=self.env)
        self.git("remote", "add", "origin", str(remote), cwd=self.root)
        self.env["TEST_GH_EXIT"] = "1"
        result = self.release("--push")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("the tag " + TAG + " is already pushed", result.stderr)
        self.assertIn(f"  gh release create {TAG} release/mailroom-sandbox-content-{TAG}.tar.zst "
                      f"release/SHA256SUMS release/content.json release/BUILD_INFO "
                      f"--title 'mailroom-sandbox-content {TAG}' --notes 'Content bundle {TAG}.",
                      result.stderr)


if __name__ == "__main__":
    unittest.main()
