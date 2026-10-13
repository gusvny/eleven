#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261013-06 unit battery: the merge-scene tool's guards (developer stage).

Two rounds were lost to defects in a handed-over one-liner: a bare interpreter
without `temporalio`, then an empty Temporal address. The tool
`integration/tools/merge_scene_prepare.py` replaces the one-liner, and these
cases pin the properties that would have caught both:

* the address comes from the engine's single source or an explicit override, and
  an unavailable engine tree is a named refusal (never an empty host);
* the lane is guarded before anything runs: a wrong branch, a working directory
  that is not a checkout top level, and an unknown line ref are all refused;
* the two settled shapes (a scene already present, the line already contained)
  are idempotent no-ops;
* dry-run changes nothing.

The Temporal call itself is not executed here: it is the worker/host action this
tool exists for. The fixture uses `--host`/`--namespace` so no engine tree and
no server are needed.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "integration" / "tools" / "merge_scene_prepare.py"
BRANCH = "lane/t261013-06"
LINE = "develop"
FILE = "shared.txt"

sys.path.insert(0, str(ROOT / "integration" / "tools"))
import merge_scene_prepare  # noqa: E402 — the tool's pure verdict helper


def git(repo, *args, check=True):
    proc = subprocess.run(
        ["git", "-c", "user.name=t261013-06", "-c", "user.email=t261013-06@example.invalid",
         "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"] + list(args),
        cwd=str(repo), capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise AssertionError("git %s failed: %s%s" % (" ".join(args), proc.stdout, proc.stderr))
    return proc


def write(repo, name, lines):
    path = Path(repo) / name
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def run_tool(*args):
    proc = subprocess.run([sys.executable, str(TOOL)] + list(args),
                          capture_output=True, text=True, cwd=str(args_lane(args)))
    payload = None
    if proc.stdout.strip().startswith("{"):
        payload = json.loads(proc.stdout)
    return proc.returncode, proc.stdout, proc.stderr, payload


def args_lane(args):
    if "--lane" in args:
        return args[args.index("--lane") + 1]
    return "."


class ScenePrepareTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="t261013-06-scene-")
        cls.repo = Path(cls._tmp.name) / "lane"
        cls.repo.mkdir()
        git(cls.repo, "init", "-q")
        write(cls.repo, FILE, ["base"])
        git(cls.repo, "add", "--", FILE)
        git(cls.repo, "commit", "-m", "base")
        git(cls.repo, "branch", "-m", "main")
        # The line: develop, one change.
        git(cls.repo, "checkout", "-q", "-b", LINE)
        write(cls.repo, FILE, ["base", "line"])
        git(cls.repo, "commit", "-am", "line change")
        # The lane: same region, another change -> a real conflict.
        git(cls.repo, "checkout", "-q", "-b", BRANCH, "main")
        write(cls.repo, FILE, ["base", "lane"])
        git(cls.repo, "commit", "-am", "lane change")
        cls.line_sha = git(cls.repo, "rev-parse", LINE).stdout.strip()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def dry(self, *args):
        return run_tool("--lane", str(self.repo), "--dry-run",
                        "--host", "127.0.0.1:7233", "--namespace", "default", *args)

    def test_failed_inner_merge_is_never_reported_as_a_created_scene(self):
        """Arbitration finding A, with the exact receipt the round produced.

        The invocation's ok only says the activity ran; the merge's outcome is
        the inner receipt. The failing round's own receipt carried
        `result.ok = false` while the leg printed "merge scene created" and
        exited 0.
        """
        failed = {"ok": True, "result": {"ok": False,
                                         "error": "git merge develop 失败（非冲突）: fatal: "
                                                  "Unable to write index."}}
        ok, action, conflicts, error = merge_scene_prepare.scene_receipt_verdict(failed)
        self.assertFalse(ok, "a failed inner merge must not pass")
        self.assertIn("merge failed", action)
        self.assertIn("Unable to write index", error)
        self.assertIsNone(conflicts)

    def test_receipt_verdict_reads_the_several_good_shapes(self):
        created = {"ok": True, "result": {"ok": True, "conflict_files": ["a.py", "b.py"],
                                          "up_to_date": False}}
        ok, action, conflicts, error = merge_scene_prepare.scene_receipt_verdict(created)
        self.assertTrue(ok)
        self.assertEqual(action, "merge scene created")
        self.assertEqual(conflicts, ["a.py", "b.py"])
        self.assertEqual(error, "")

        up_to_date = {"ok": True, "result": {"ok": True, "up_to_date": True}}
        ok, action, _conflicts, _error = merge_scene_prepare.scene_receipt_verdict(up_to_date)
        self.assertTrue(ok)
        self.assertIn("idempotent", action)

        clean = {"ok": True, "result": {"ok": True, "conflict_files": []}}
        ok, action, _conflicts, _error = merge_scene_prepare.scene_receipt_verdict(clean)
        self.assertTrue(ok)
        self.assertIn("no conflicts", action)

        refused = {"ok": False, "exit": 2, "error": "unavailable"}
        ok, action, _conflicts, error = merge_scene_prepare.scene_receipt_verdict(refused)
        self.assertFalse(ok)
        self.assertIn("invocation failed", action)
        self.assertEqual(error, "unavailable")

    def test_dry_run_reports_the_absent_scene_and_the_payload(self):
        before = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        rc, out, err, payload = self.dry("--line", LINE)
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(payload["scene"], "absent")
        self.assertEqual(payload["line_sha"], self.line_sha)
        self.assertEqual(payload["payload"]["worktree"], os.path.realpath(self.repo))
        self.assertEqual(payload["payload"]["base_ref"], LINE)
        self.assertEqual(payload["payload"]["branch"], BRANCH)
        self.assertEqual(payload["temporal_host"], "127.0.0.1:7233")
        self.assertEqual(payload["action"], "dry-run: no activity called")
        after = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(before, after, "dry-run must not move HEAD")
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout.strip(), "")

    def test_wrong_branch_is_refused(self):
        rc, out, err, payload = self.dry("--branch", "lane/t999999-99", "--line", LINE)
        self.assertEqual(rc, 2, out + err)
        self.assertIn("lane_branch_mismatch", payload["error"])

    def test_working_directory_must_be_the_checkout_top_level(self):
        sub = self.repo / "sub"
        sub.mkdir(exist_ok=True)
        rc, out, err, payload = run_tool("--lane", str(sub), "--dry-run",
                                         "--host", "h", "--namespace", "n", "--line", LINE)
        self.assertEqual(rc, 2, out + err)
        self.assertIn("lane_root_mismatch", payload["error"])

    def test_unknown_line_ref_is_refused(self):
        rc, out, err, payload = self.dry("--line", "no-such-line")
        self.assertEqual(rc, 2, out + err)
        self.assertIn("line_ref_unresolved", payload["error"])

    def test_missing_engine_tree_is_named_when_no_override_is_given(self):
        """No server/engine in the fixture: refuse by name, never connect empty."""
        rc, out, err, payload = run_tool("--lane", str(self.repo), "--dry-run", "--line", LINE)
        self.assertEqual(rc, 2, out + err)
        self.assertIn("engine_shared_unimportable", payload["error"])

    def test_scene_already_present_is_idempotent(self):
        repo = Path(self._tmp.name) / "conflicted"
        repo.mkdir(exist_ok=True)
        git(repo, "init", "-q")
        write(repo, FILE, ["base"])
        git(repo, "add", "--", FILE)
        git(repo, "commit", "-m", "base")
        git(repo, "branch", "-m", "main")
        git(repo, "checkout", "-q", "-b", LINE)
        write(repo, FILE, ["base", "line"])
        git(repo, "commit", "-am", "line change")
        git(repo, "checkout", "-q", "-b", BRANCH, "main")
        write(repo, FILE, ["base", "lane"])
        git(repo, "commit", "-am", "lane change")
        git(repo, "merge", "--no-edit", LINE, check=False)      # leaves MERGE_HEAD
        self.assertEqual(git(repo, "rev-parse", "--verify", "MERGE_HEAD", check=False).returncode, 0,
                         "the fixture must leave a merge in progress")
        rc, out, err, payload = run_tool("--lane", str(repo), "--line", LINE,
                                         "--host", "h", "--namespace", "n")
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(payload["scene"], "present")
        self.assertIn("idempotent", payload["action"])

    def test_line_already_contained_is_idempotent(self):
        repo = Path(self._tmp.name) / "ontop"
        repo.mkdir(exist_ok=True)
        git(repo, "init", "-q")
        write(repo, FILE, ["base"])
        git(repo, "add", "--", FILE)
        git(repo, "commit", "-m", "base")
        git(repo, "branch", "-m", "main")
        git(repo, "checkout", "-q", "-b", LINE)
        write(repo, FILE, ["base", "line"])
        git(repo, "commit", "-am", "line change")
        git(repo, "checkout", "-q", "-b", "lane/on-line", LINE)
        rc, out, err, payload = run_tool("--lane", str(repo), "--branch", "lane/on-line",
                                         "--line", LINE, "--host", "h", "--namespace", "n")
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(payload["scene"], "merged")
        self.assertIn("idempotent", payload["action"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
