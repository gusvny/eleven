#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261011-18 L1 unit battery: the line round hands the suite its assets
(developer stage).

The incident: the suite runs with cwd = a CLONE whose .git is a directory,
so bench's main-tree fallback (main_root_of, gitfile-only) returns None and
the gitignored .venv / temporal binary are absent in the run tree — the
suite env-fails, never writes a header, and no certification can be minted.
The fix (ticket route 1): the runner resolves SANDBAR_POC_PYTHON /
SANDBAR_TEMPORAL_BIN from its OWN checkout and exports them into the suite
env; a genuinely absent asset is a named could-not-run before any spawn.

Offline seconds, zero docker/Temporal/port/console, never touches 3099.
Reuses the t261009-77 harness shape: real runner subprocess, stub suite, a
tiny git fixture repo; the stub suite records the asset env it received.
"""
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "integration" / "line_round_runner.py"
POC_ENV = "SANDBAR_POC_PYTHON"
BIN_ENV = "SANDBAR_TEMPORAL_BIN"


def expected_assets():
    """Where the runner's own checkout CAN resolve the assets to: the
    worktree's main tree when this checkout is a worktree (bench's
    gitfile fallback), else the checkout itself. Existence is the
    environment's honest truth and decides which outcome legs B/D assert."""
    sys.path.insert(0, str(ROOT / "integration"))
    try:
        import bench
    finally:
        sys.path.remove(str(ROOT / "integration"))
    base = bench.main_root_of(ROOT) or ROOT
    return (base / "server" / "engine" / ".venv" / "bin" / "python",
            base / "server" / "engine" / "bin" / "temporal")

STUB_SUITE = r'''
import json, os, sys, time
sys.path.insert(0, os.environ["SUITE_INTEGRATION_DIR"])
import scenario_ledger as mod
receipt = {
    "poc_python": os.environ.get("SANDBAR_POC_PYTHON"),
    "temporal_bin": os.environ.get("SANDBAR_TEMPORAL_BIN"),
    "git_sha": os.environ.get("SANDBAR_GIT_SHA"),
}
with open(os.environ["SUITE_RECEIPT"], "w") as fh:
    json.dump(receipt, fh)
counts = {"ran": 1, "passed": 1, "failed": 0, "env_failed": 0}
run_id = mod.mint_run_id()
import datetime
ts = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
mod.append_records([{
    "ts": ts, "commit": os.environ["SUITE_COMMIT"], "env_fp": "a" * 64,
    "conc_width": 1, "pool": "stub", "scenario": "stub-a",
    "verdict": "pass", "wall_s": 0.01, "source": "lane:line-round",
    "ticket": "line-round", "run": run_id,
}])
hdr = {"v": mod.RUN_HEADER_V, "id": run_id,
       "repos": [{"repo": "sandbar", "revision": os.environ["SUITE_COMMIT"]}],
       "suite": "full", "source": "lane:line-round", "env_fp": "a" * 64,
       "conc_width": 1, "pool": "stub",
       "started_at": int(time.time() * 1000), "duration_s": 0.1,
       "cases": counts, "verdict": mod.run_verdict(counts)}
mod.append_run_header(hdr)
print("INTEG_SUMMARY " + json.dumps(
    {"ran": 1, "pass": 1, "fail": 0, "not_checked": 0, "run_id": run_id}))
'''


def make_source_repo(tmp):
    """A tiny git repo whose HEAD carries integration/run_scenarios.py —
    the runner's primary-tree detection is all it needs to satisfy."""
    src = Path(tmp) / "source-sandbar"
    (src / "integration").mkdir(parents=True)
    (src / "integration" / "run_scenarios.py").write_text("# stub tree\n")
    for argv in (
            ["git", "init", "-q", str(src)],
            ["git", "-C", str(src), "config", "user.email", "t@t"],
            ["git", "-C", str(src), "config", "user.name", "t"],
            ["git", "-C", str(src), "add", "-A"],
            ["git", "-C", str(src), "commit", "-qm", "fixture"],
    ):
        proc = subprocess.run(argv, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError("git fixture failed: %s: %s"
                               % (argv, proc.stderr))
    sha = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    return src, sha


class AssetEnvLeg(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="t26101118-ut-")
        self.tmp = Path(self._tmp.name)
        self.src, self.sha = make_source_repo(self.tmp)
        stub = self.tmp / "stub_suite.py"
        stub.write_text(STUB_SUITE)
        self.stub = stub
        self.receipt = self.tmp / "receipt.json"

    def tearDown(self):
        self._tmp.cleanup()

    def base_env(self, extra=None):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("SANDBAR_")}
        env["SANDBAR_LINE_ROUND_REPO_PATH_SANDBAR"] = str(self.src)
        env["SANDBAR_LINE_ROUND_RUN_ROOT"] = str(self.tmp / "run")
        env["SANDBAR_LINE_ROUND_RUN_STATE_DIR"] = str(self.tmp / "state")
        # t261012-06: the runner's face dir must be pinned into this tmp
        # tree — an un-pinned resolution writes round dirs into the
        # production face dir this machine may own
        env["SANDBAR_LINE_ROUND_FACE_DIR"] = str(self.tmp / "face")
        env["SANDBAR_LINE_ROUND_CANDIDATES"] = json.dumps(
            [{"repo": "sandbar", "revision": self.sha}])
        env["SUITE_INTEGRATION_DIR"] = str(ROOT / "integration")
        env["SUITE_RECEIPT"] = str(self.receipt)
        env["SUITE_COMMIT"] = self.sha
        env["SANDBAR_LINE_ROUND_SUITE_CMD"] = "%s %s" % (
            sys.executable, shlex.quote(str(self.stub)))
        env.update(extra or {})
        return env

    def run_runner(self, env):
        return subprocess.run(
            [sys.executable, str(RUNNER)], env=env,
            capture_output=True, text=True, timeout=120)

    # ---- A: declared keys pass through verbatim (override wins) ----

    def test_a_declared_keys_pass_through(self):
        poc = self.tmp / "fixture-python"
        binp = self.tmp / "fixture-temporal"
        poc.write_text("#!/bin/sh\n")
        binp.write_text("#!/bin/sh\n")
        proc = self.run_runner(self.base_env(
            {POC_ENV: str(poc), BIN_ENV: str(binp)}))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        receipt = json.loads(self.receipt.read_text())
        self.assertEqual(receipt["poc_python"], str(poc))
        self.assertEqual(receipt["temporal_bin"], str(binp))

    # ---- B: unset keys are resolved from the runner's own checkout ----

    def test_b_keys_resolved_from_own_checkout(self):
        proc = self.run_runner(self.base_env())
        expected_poc, expected_bin = expected_assets()
        have = expected_poc.exists() and expected_bin.exists()
        if have:
            self.assertEqual(proc.returncode, 0, proc.stderr)
            receipt = json.loads(self.receipt.read_text())
            self.assertEqual(Path(receipt["poc_python"]).resolve(),
                             expected_poc.resolve())
            self.assertEqual(Path(receipt["temporal_bin"]).resolve(),
                             expected_bin.resolve())
        else:
            # honest miss in an asset-less environment: named could-not-run
            self.assertEqual(proc.returncode, 2)
            self.assertIn("asset_missing:", proc.stderr)
            self.assertNotIn("INTEG_SUMMARY", proc.stdout)

    # ---- C: a genuinely absent declared asset is a named could-not-run ----
    #
    # Why this variant and not the line's (t261013-06, the develop-line carrier):
    # the line's copy asserted the dead-pointer FALLBACK (`asset_pointer_dead`,
    # exit 0 after a local resolution). Main rolled that fallback back by host
    # order (commit 50d4bf61, recorded in notes/debts/known-issues.md as "the
    # fallback overrode the contract"), and this carrier delivers main's batch,
    # so the strict variant below is the sanctioned contract. The replaced
    # assertions are listed with their reasons in
    # integration/t261013-06/merge_deviations.json.

    def test_c_absent_asset_named_before_spawn(self):
        bad = str(self.tmp / "nope" / "python")
        proc = self.run_runner(self.base_env(
            {POC_ENV: bad, BIN_ENV: str(self.stub)}))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("LINE_ROUND_RUNNER could_not_run:", proc.stderr)
        self.assertIn("asset_missing:%s" % POC_ENV, proc.stderr)
        self.assertIn(bad, proc.stderr)
        # never a header, never a certification, never a silent skip
        self.assertEqual(proc.stdout.strip(), "")
        self.assertFalse(self.receipt.exists())

    # ---- D: empty-string keys count as unset (resolved, not passed) ----

    def test_d_blank_keys_resolved_not_passed(self):
        proc = self.run_runner(self.base_env({POC_ENV: "  ", BIN_ENV: ""}))
        expected_poc, expected_bin = expected_assets()
        if expected_poc.exists() and expected_bin.exists():
            self.assertEqual(proc.returncode, 0, proc.stderr)
            receipt = json.loads(self.receipt.read_text())
            # blank strings are not handed to the suite
            self.assertNotEqual(receipt["poc_python"].strip(), "")
            self.assertNotEqual((receipt["temporal_bin"] or "").strip(), "")
        else:
            self.assertEqual(proc.returncode, 2)
            self.assertIn("asset_missing:", proc.stderr)


if __name__ == "__main__":
    unittest.main()
