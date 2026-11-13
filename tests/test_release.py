"""Tests for the release path: notes generation and the publish script.

`tools/publish_release.sh` is the exact script the CI release job runs.  Here it
runs against a stub `gh` that records its arguments, so the publishing *logic*
(checksum gate, verdict gate, create-vs-update, --clobber, asset assertion) is
executed without network access.  This does not prove that GitHub accepted an
upload; only a real workflow run can show that.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import release_notes  # noqa: E402

STUB_GH = """#!/bin/sh
# Stub `gh` for the publish script: records argv, answers the queries it makes.
state="$PC5_STUB_DIR"
echo "$@" >> "$state/calls.log"
cmd="$1"
shift
if [ "$cmd" = "release" ]; then
  sub="$1"
  shift
  tag="$1"
  shift
  case "$sub" in
    view)
      if [ -f "$state/releases.txt" ] && grep -qx "$tag" "$state/releases.txt"; then
        case "$*" in
          *"--json assets"*) [ -f "$state/assets.txt" ] && cat "$state/assets.txt" ;;
          *) echo "$tag" ;;
        esac
        exit 0
      fi
      exit 1
      ;;
    create|edit)
      echo "$tag" >> "$state/releases.txt"
      exit 0
      ;;
    upload)
      for a in "$@"; do
        case "$a" in
          *.iso|*.sha256|*.json) basename "$a" >> "$state/assets.txt" ;;
        esac
      done
      exit 0
      ;;
  esac
fi
exit 0
"""


class ReleaseNotesTests(unittest.TestCase):
    def record(self, **overrides):
        build = {
            "schema": "pc5.build-metadata/1",
            "version": "0.2.0",
            "tag": "v0.2.0",
            "commit": "a" * 40,
            "build_id": "b" * 40,
            "source_date_epoch": 1794515355,
            "toolchain": {"cc": "gcc (Debian) 12.2.0", "os": "Linux 6.1 x86_64"},
            "artifact": {
                "name": "pc5.iso",
                "bytes": 96256,
                "sectors": 47,
                "sha256": "c" * 64,
            },
            "verification": {
                "verdict": "PASS",
                "checks": [
                    {"name": "iso_structure", "checks": 32, "failures": 0},
                    {"name": "emulated_boot", "checks": 25, "failures": 0},
                    {"name": "kernel_unit", "checks": 35, "failures": 0},
                    {"name": "host_tests", "tests": 24, "failures": 0},
                ],
            },
        }
        build.update(overrides)
        return {"sha256": "c" * 64, "build": build}

    def test_notes_state_every_measured_result(self):
        text = release_notes.render(self.record())
        self.assertIn("PC5 0.2.0", text)
        self.assertIn("96256 bytes", text)
        self.assertIn("ISO structure and checksums: 32 (0 failures)", text)
        self.assertIn("emulated boot (v86/SeaBIOS): 25 (0 failures)", text)
        self.assertIn("kernel unit tests: 35 (0 failures)", text)
        self.assertIn("host tool tests: 24 (0 failures)", text)
        self.assertIn("does not run genuine PS5 system software", text)

    def test_notes_never_invent_a_number(self):
        text = release_notes.render(self.record(verification={"verdict": "PASS", "checks": []}))
        self.assertIn("not run", text)
        self.assertNotIn("0 failures", text)


class PublishScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pc5-publish-")
        self.dist = os.path.join(self.tmp, "dist")
        os.makedirs(self.dist)
        self.state = os.path.join(self.tmp, "state")
        os.makedirs(self.state)
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        gh = os.path.join(self.bin, "gh")
        with open(gh, "w", encoding="utf-8") as fh:
            fh.write(STUB_GH)
        os.chmod(gh, os.stat(gh).st_mode | stat.S_IEXEC)
        self.assets(verdict="PASS")

    def assets(self, verdict="PASS", corrupt_checksum=False):
        payload = b"\xeb\x05PC5K" + bytes(4096)
        with open(os.path.join(self.dist, "pc5.iso"), "wb") as fh:
            fh.write(payload)
        digest = __import__("hashlib").sha256(payload).hexdigest()
        stamp = "0" * 64 if corrupt_checksum else digest
        with open(os.path.join(self.dist, "pc5.iso.sha256"), "w", encoding="utf-8") as fh:
            fh.write(f"{stamp}  pc5.iso\n")
        info = {
            "sha256": digest,
            "build": {
                "version": "0.2.0",
                "commit": "a" * 40,
                "artifact": {"sha256": digest, "bytes": len(payload), "sectors": 2},
                "verification": {"verdict": verdict, "checks": []},
            },
        }
        with open(os.path.join(self.dist, "build-info.json"), "w", encoding="utf-8") as fh:
            json.dump(info, fh)

    def run_publish(self, tag="v0.2.0"):
        env = dict(os.environ)
        env["PATH"] = self.bin + os.pathsep + env["PATH"]
        env["PC5_STUB_DIR"] = self.state
        return subprocess.run(
            ["sh", os.path.join(ROOT, "tools", "publish_release.sh"),
             "--tag", tag, "--dist", self.dist],
            capture_output=True,
            text=True,
            env=env,
        )

    def calls(self):
        path = os.path.join(self.state, "calls.log")
        return open(path, encoding="utf-8").read() if os.path.exists(path) else ""

    def test_publishes_three_assets_and_is_idempotent(self):
        first = self.run_publish()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertIn("creating release v0.2.0", first.stdout)
        for asset in ("pc5.iso", "pc5.iso.sha256", "build-info.json"):
            self.assertIn(asset, self.calls())
        self.assertIn("--clobber", self.calls())

        second = self.run_publish()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("exists, updating its notes", second.stdout)
        self.assertIn("release edit v0.2.0", self.calls())
        self.assertIn("carries pc5.iso, pc5.iso.sha256 and build-info.json", second.stdout)

    def test_refuses_a_failing_verdict(self):
        self.assets(verdict="FAIL")
        run = self.run_publish()
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("refusing to publish", run.stderr)
        self.assertNotIn("upload", self.calls())

    def test_refuses_a_bad_checksum(self):
        self.assets(corrupt_checksum=True)
        run = self.run_publish()
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("FAILED", (run.stdout + run.stderr))
        self.assertNotIn("upload", self.calls())

    def test_refuses_missing_assets(self):
        os.remove(os.path.join(self.dist, "build-info.json"))
        run = self.run_publish()
        self.assertEqual(run.returncode, 2)
        self.assertIn("missing asset", run.stderr)


class CiLayoutTests(unittest.TestCase):
    """The pipeline file lives in ci/ until the workflow permission exists."""

    def test_pipeline_file_is_present_and_complete(self):
        candidates = [
            os.path.join(ROOT, ".github", "workflows", "build.yml"),
            os.path.join(ROOT, "ci", "build.yml"),
        ]
        found = [p for p in candidates if os.path.exists(p)]
        self.assertTrue(found, "no pipeline file in .github/workflows/ or ci/")
        text = open(found[0], encoding="utf-8").read()
        self.assertIn("SOURCE_DATE_EPOCH", text)
        self.assertIn("tools/publish_release.sh", text)
        self.assertIn("startsWith(github.ref, 'refs/tags/')", text)

    def test_readme_explains_activation_when_not_installed(self):
        active = os.path.join(ROOT, ".github", "workflows", "build.yml")
        if os.path.exists(active):
            self.skipTest("pipeline is active")
        readme = os.path.join(ROOT, "ci", "README.md")
        self.assertTrue(os.path.exists(readme))
        text = open(readme, encoding="utf-8").read()
        self.assertIn("git mv ci/build.yml .github/workflows/build.yml", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
