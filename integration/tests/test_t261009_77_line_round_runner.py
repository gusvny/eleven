#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261009-77 L1 unit battery: the line round runner (developer stage).

Runs the runner as a real subprocess against a stub suite command and a real
tiny git fixture repo — offline seconds, zero docker/Temporal/port/console,
never touches 3099. The stub suite writes its run record through the REAL
``integration/scenario_ledger.py`` store, so the header the runner relays is
one the store validated (the relay is exercised against the real recount and
schema checks, not against a hand-made dict).

Legs:
- A header contract (green): one JSON stdout line, the ledger's own header;
  the stub's receipt proves the candidates, cwd (the clone), reuse-off,
  owner-neutralization and pinned git sha it received.
- B red is a proof: a completed-but-red round relays the red header, exit 0.
- C malformed candidate matrix (fixed payloads): each a named nonzero exit,
  zero stdout lines.
- D could-not-run matrix: no summary / no run id / header missing / clone
  failure / source missing / suite command unresolvable.
- E inherited gate-owner env neutralized (review C1).
- F run tree must not overlap the source checkout (named refusal).
- G SIGTERM reclaims the process group and the run tree (no orphan suite).
"""
import contextlib
import io
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "integration" / "line_round_runner.py"

sys.path.insert(0, str(RUNNER.parent))
import line_round_runner as runner  # noqa: E402

ENV_FP = "a" * 64

STUB_SUITE = r'''
import json, os, sys, time
sys.path.insert(0, os.environ["SUITE_INTEGRATION_DIR"])
import scenario_ledger as mod
receipt = {
    "candidates": os.environ.get("SANDBAR_LINE_ROUND_CANDIDATES"),
    "cwd": os.getcwd(),
    "reuse": os.environ.get("SANDBAR_LEDGER_REUSE"),
    "owner": os.environ.get("SANDBAR_INTEG_LEDGER_OWNER"),
    "source_env": os.environ.get("SANDBAR_INTEG_LEDGER_SOURCE"),
    "ticket_env": os.environ.get("SANDBAR_TICKET_ID"),
    "git_sha": os.environ.get("SANDBAR_GIT_SHA"),
    "ledger_dir": os.environ.get("SANDBAR_SCENARIO_LEDGER_DIR"),
    "pid": os.getpid(),
}
with open(os.environ["SUITE_RECEIPT"], "w") as fh:
    json.dump(receipt, fh)
sleep_s = os.environ.get("SUITE_SLEEP_S", "")
if sleep_s:
    time.sleep(float(sleep_s))
if os.environ.get("SUITE_NO_SUMMARY"):
    sys.exit(2)
commit = os.environ["SUITE_COMMIT"]
mode = os.environ.get("SUITE_MODE", "green")
green = mode == "green"
counts = {"ran": 2, "passed": 2 if green else 1, "failed": 0 if green else 1,
          "env_failed": 0}
spec_cases = [
    {"name": "stub-a", "status": "pass", "suite": "stub", "dur_s": 0.01},
    {"name": "stub-b", "status": "pass" if green else "fail",
     "suite": "stub", "dur_s": 0.01},
]
run_id = mod.mint_run_id()
import datetime
ts = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
rows = [{
    "ts": ts, "commit": commit, "env_fp": "a" * 64, "conc_width": 1,
    "pool": "stub", "scenario": c["name"],
    "verdict": "pass" if c["status"] == "pass" else "fail",
    "wall_s": c["dur_s"], "source": "lane:line-round", "ticket": "line-round",
    "run": run_id,
} for c in spec_cases]
mod.append_records(rows)
if not os.environ.get("SUITE_SKIP_HEADER"):
    hdr = {"v": mod.RUN_HEADER_V, "id": run_id,
           "repos": [{"repo": "sandbar", "revision": commit}],
           "suite": "full", "source": "lane:line-round", "env_fp": "a" * 64,
           "conc_width": 1, "pool": "stub",
           "started_at": int(time.time() * 1000), "duration_s": 0.1,
           "cases": counts, "verdict": mod.run_verdict(counts)}
    mod.append_run_header(hdr)
summary = {"ran": counts["ran"], "pass": counts["passed"],
           "fail": counts["failed"], "not_checked": 0}
if not os.environ.get("SUITE_NO_RUNID"):
    summary["run_id"] = run_id
print("INTEG_SUMMARY " + json.dumps(summary))
sys.exit(0 if green else 1)
'''


def make_source_repo(tmp):
    """A tiny git repo whose HEAD carries integration/run_scenarios.py —
    just enough for the runner's primary-tree detection; the suite itself is
    the stub (the fixture is the run's own tree, not the suite's)."""
    src = Path(tmp) / "source-sandbar"
    (src / "integration").mkdir(parents=True)
    (src / "integration" / "run_scenarios.py").write_text("# stub tree\n")
    run = subprocess.run
    for argv in (
            ["git", "init", "-q", str(src)],
            ["git", "-C", str(src), "config", "user.email", "t@t"],
            ["git", "-C", str(src), "config", "user.name", "t"],
            ["git", "-C", str(src), "add", "-A"],
            ["git", "-C", str(src), "commit", "-qm", "fixture"],
    ):
        proc = run(argv, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError("git fixture failed: %s: %s"
                               % (argv, proc.stderr))
    sha = run(["git", "-C", str(src), "rev-parse", "HEAD"],
              capture_output=True, text=True).stdout.strip()
    return src, sha


class Leg(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="t26100977-ut-")
        self.tmp = Path(self._tmp.name)
        self.src, self.sha = make_source_repo(self.tmp)
        self.integration_src = ROOT / "integration"
        stub = self.tmp / "stub_suite.py"
        stub.write_text(STUB_SUITE)
        self.stub = stub
        self.receipt = self.tmp / "receipt.json"

    def tearDown(self):
        self._tmp.cleanup()

    def base_env(self, run_root, extra=None):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("SANDBAR_")}
        env["SANDBAR_LINE_ROUND_REPO_PATH_SANDBAR"] = str(self.src)
        env["SANDBAR_LINE_ROUND_RUN_ROOT"] = str(run_root)
        env["SANDBAR_LINE_ROUND_RUN_STATE_DIR"] = str(self.tmp / "state")
        # t261012-06: the runner's face dir must be pinned into this tmp
        # tree — an un-pinned resolution writes round dirs into the
        # production face dir this machine may own
        env["SANDBAR_LINE_ROUND_FACE_DIR"] = str(self.tmp / "face")
        env["SUITE_INTEGRATION_DIR"] = str(self.integration_src)
        env["SUITE_RECEIPT"] = str(self.receipt)
        env["SUITE_COMMIT"] = self.sha
        # default suite = the stub; individual legs override on purpose
        env.setdefault("SANDBAR_LINE_ROUND_SUITE_CMD",
                       "%s %s" % (sys.executable, shlex.quote(str(self.stub))))
        env.update(extra or {})
        return env

    def candidates(self):
        return json.dumps([{"repo": "sandbar", "revision": self.sha}])

    def run_runner(self, env):
        return subprocess.run(
            [sys.executable, str(RUNNER)], env=env,
            capture_output=True, text=True, timeout=120)

    # ---- A: header contract (green) ----

    def test_a_header_contract_green(self):
        run_root = self.tmp / "runA"
        proc = self.run_runner(self.base_env(run_root, {
            "SANDBAR_LINE_ROUND_CANDIDATES": self.candidates(),
        }))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1, proc.stdout)
        header = json.loads(lines[0])
        self.assertTrue(header["id"].startswith("run-"))
        self.assertEqual(header["cases"]["ran"], 2)
        self.assertEqual(header["verdict"], "green")
        receipt = json.loads(self.receipt.read_text())
        self.assertEqual(json.loads(receipt["candidates"]),
                         json.loads(self.candidates()))
        self.assertTrue(os.path.realpath(receipt["cwd"]).startswith(os.path.realpath(str(run_root))))
        self.assertEqual(receipt["reuse"], "0")
        self.assertIsNone(receipt["owner"])
        self.assertIsNone(receipt["ticket_env"])
        self.assertEqual(receipt["git_sha"], self.sha)
        # the run tree is reclaimed on the success path
        self.assertFalse(run_root.exists())

    # ---- B: a completed-but-red round is a proof, not could-not-run ----

    def test_b_red_is_proof(self):
        proc = self.run_runner(self.base_env(self.tmp / "runB", {
            "SANDBAR_LINE_ROUND_CANDIDATES": self.candidates(),
            "SUITE_MODE": "red",
        }))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        header = json.loads(proc.stdout.strip())
        self.assertEqual(header["verdict"], "red")
        self.assertEqual(header["cases"]["failed"], 1)

    # ---- C: malformed candidate matrix (fixed payloads, no external source) ----

    def test_c_malformed_candidates_matrix(self):
        payloads = [
            ("candidates_env_unset", None),
            ("candidates_not_json", "{not json"),
            ("candidates_not_nonempty_list", "{}"),
            ("candidates_not_nonempty_list", "[]"),
            ("candidate_member_malformed", '[{"revision": "abc"}]'),
            ("candidate_member_malformed", '[{"repo": "sandbar"}]'),
        ]
        seen, tried = set(), 0
        for name, raw in payloads:
            tried += 1
            env = self.base_env(self.tmp / "runC", {
                "SANDBAR_LINE_ROUND_CANDIDATES": raw or "",
            })
            proc = self.run_runner(env)
            self.assertEqual(proc.returncode, 2, (name, proc.stdout))
            self.assertEqual(proc.stdout, "", name)
            self.assertIn(name, proc.stderr, name)
            seen.add(name)
        self.assertEqual(tried, 6)
        self.assertEqual(len(seen), 4)

    # ---- D: could-not-run matrix ----

    def test_d_no_summary(self):
        proc = self.run_runner(self.base_env(self.tmp / "runD1", {
            "SANDBAR_LINE_ROUND_CANDIDATES": self.candidates(),
            "SUITE_NO_SUMMARY": "1",
        }))
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")
        self.assertIn("integ_summary_missing", proc.stderr)

    def test_d_run_id_missing(self):
        proc = self.run_runner(self.base_env(self.tmp / "runD2", {
            "SANDBAR_LINE_ROUND_CANDIDATES": self.candidates(),
            "SUITE_NO_RUNID": "1",
        }))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("run_id_missing_from_summary", proc.stderr)

    def test_d_header_missing_interrupted_run(self):
        proc = self.run_runner(self.base_env(self.tmp / "runD3", {
            "SANDBAR_LINE_ROUND_CANDIDATES": self.candidates(),
            "SUITE_SKIP_HEADER": "1",
        }))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("run_header_missing", proc.stderr)

    def test_d_clone_failure(self):
        bad = self.tmp / "not-a-repo"
        bad.mkdir()
        env = self.base_env(self.tmp / "runD4", {
            "SANDBAR_LINE_ROUND_CANDIDATES": self.candidates(),
        })
        env["SANDBAR_LINE_ROUND_REPO_PATH_SANDBAR"] = str(bad)
        proc = self.run_runner(env)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("clone_failed", proc.stderr)

    def test_d_source_missing(self):
        env = self.base_env(self.tmp / "runD5", {
            "SANDBAR_LINE_ROUND_CANDIDATES": self.candidates(),
        })
        env["SANDBAR_LINE_ROUND_REPO_PATH_SANDBAR"] = \
            str(self.tmp / "no-such-dir")
        proc = self.run_runner(env)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("source_missing", proc.stderr)

    def test_d_suite_cmd_unresolvable(self):
        proc = self.run_runner(self.base_env(self.tmp / "runD6", {
            "SANDBAR_LINE_ROUND_CANDIDATES": self.candidates(),
            "SANDBAR_LINE_ROUND_SUITE_CMD":
                "definitely-missing-binary-t26100977",
        }))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("suite_unreachable", proc.stderr)

    # ---- E: inherited gate-owner env neutralized (review C1) ----

    def test_e_gate_owner_env_neutralized(self):
        env = self.base_env(self.tmp / "runE", {
            "SANDBAR_LINE_ROUND_CANDIDATES": self.candidates(),
            "SANDBAR_INTEG_LEDGER_OWNER": "gate",
            "SANDBAR_TICKET_ID": "t9999",
        })
        proc = self.run_runner(env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        receipt = json.loads(self.receipt.read_text())
        self.assertIsNone(receipt["owner"])
        self.assertIsNone(receipt["ticket_env"])
        self.assertEqual(receipt["source_env"], "lane:line-round")

    # ---- F: the run tree never overlaps the source checkout ----

    def test_f_tree_overlaps_source_refused(self):
        env = self.base_env(str(self.src), {
            "SANDBAR_LINE_ROUND_CANDIDATES": self.candidates(),
        })
        proc = self.run_runner(env)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("tree_overlaps_source_checkout", proc.stderr)
        self.assertEqual(
            subprocess.run(["git", "-C", str(self.src), "status",
                            "--porcelain"],
                           capture_output=True, text=True).stdout,
            "")

    # ---- G: SIGTERM reclaims the process group and the run tree ----

    def test_g_sigterm_reclaims(self):
        run_root = self.tmp / "runG"
        env = self.base_env(run_root, {
            "SANDBAR_LINE_ROUND_CANDIDATES": self.candidates(),
            "SUITE_SLEEP_S": "30",
        })
        proc = subprocess.Popen([sys.executable, str(RUNNER)], env=env,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        deadline = time.time() + 30
        while not self.receipt.exists() and time.time() < deadline:
            time.sleep(0.05)
        self.assertTrue(self.receipt.exists(), "stub never started")
        stub_pid = json.loads(self.receipt.read_text())["pid"]
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=30)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("runner_signaled", err)
        self.assertEqual(out, "")
        self.assertFalse(run_root.exists(), "run tree not reclaimed")
        with self.assertRaises(OSError):
            os.kill(stub_pid, 0)  # the suite did not outlive the runner


class ExclusionDefaultT26101612(unittest.TestCase):
    """t261016-12: the pool-exclusion default is "run every pool".

    The docstring always said exclusion is opt-in diagnostics; the constant
    said "exclusive", so every round without the env var was narrowed and
    wrote no run record — no header, no certification, ever. These legs pin
    the contract at the pure-function level (no subprocess):
    (a) env var ABSENT  -> exclusion "" (a full round, not a narrowed one);
    (b) env var = pool  -> that pool, and the suite argv narrows + the
        stderr announcement still names the narrowing (stable substrings
        only — the copy is a surface, not the contract);
    (c) env var = ""    -> byte-identical argv and stderr to (a);
    (d) env var = "   " -> stripped to "" (whitespace is not a pool name).
    """

    def env(self, **kw):
        return dict(kw)

    def test_a_absent_env_var_is_full_pool(self):
        self.assertEqual(runner.exclude_pools_value(self.env()), "")

    def test_b_named_pool_narrows_and_announces(self):
        env = self.env(**{runner.EXCLUDE_POOLS_ENV: "exclusive"})
        self.assertEqual(runner.exclude_pools_value(env), "exclusive")
        argv = runner.suite_argv(env)
        self.assertIn("--exclude-pools", argv)
        self.assertEqual(argv[argv.index("--exclude-pools") + 1], "exclusive")
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            runner.suite_argv(env)
        err = captured.getvalue()
        self.assertIn("NARROWED", err)
        self.assertIn("NO certification", err)

    def test_c_empty_value_matches_absent_byte_for_byte(self):
        empty = self.env(**{runner.EXCLUDE_POOLS_ENV: ""})
        absent = self.env()
        self.assertEqual(runner.exclude_pools_value(empty), "")
        argv = runner.suite_argv(absent)
        self.assertNotIn("--exclude-pools", argv)
        self.assertEqual(runner.suite_argv(empty), argv)
        for env in (empty, absent):
            captured = io.StringIO()
            with contextlib.redirect_stderr(captured):
                runner.suite_argv(env)
            self.assertEqual(captured.getvalue(), "")

    def test_d_whitespace_value_is_stripped_to_full_pool(self):
        env = self.env(**{runner.EXCLUDE_POOLS_ENV: "   "})
        self.assertEqual(runner.exclude_pools_value(env), "")
        argv = runner.suite_argv(env)
        self.assertNotIn("--exclude-pools", argv)


if __name__ == "__main__":
    unittest.main()
