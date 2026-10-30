#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261030-25 (KI-429) — the isolation battery: a staged round owns its
projects root, and the instrument that proves it has teeth.

The incident: a fixture ran the REAL line-round runner with the projects-root
seam unset, so the round's face fell back to "the project whose ledger the run
row lands in" — the PRODUCTION project. Six ``run-*`` directories appeared in
``~/.sandbar/projects/sandbar/data/develop/rounds/``, each citing a revision
that is not a git object in this repo, and the tick-entry reconciliation booked
certifications and a freeze from them.

Two legs, both offline (no docker, no Temporal, no network, never touches
3099 or the console):

- I1 ISOLATION: a round staged exactly as the fixture stages it (its own
  projects root via ``SANDBAR_PROJECTS_DIR``, its own face dir, its own run
  root) leaves BOTH the substituted projects root and the REAL projects root
  byte-unchanged. The real root is the one that must never move; the
  substituted root is watched too, because "isolated" must not be achieved by
  writing somewhere else.
- I2 MUTATION PROOF: the same round with the projects-root pin REMOVED writes
  the substituted root — the watcher reports the exact paths (a new
  ``run-*`` directory, a runs-store append). This runs with ``HOME`` pointed
  at the decoy, so the unpinned fallback lands in the decoy and the real root
  is still asserted unchanged. If I1's instrument could not see the leak, I2
  would be CLEAN and this battery would be lying.

The watcher is the same one the bisect harness uses
(``integration/t261030-25/lib_real_root_watch.py``): content hashes over the
rounds tree, the delivery ledger, the guard/pointer files and the runs store —
never a count, because the round face's rolling retention can replace one
directory with another and leave the count identical (that is exactly how the
incident survived its first hunt).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "integration"

sys.path.insert(0, str(INTEG))
sys.path.insert(0, str(INTEG / "t261030-25"))
import lib_real_root_watch as real_root  # noqa: E402

PROJECT_KEY = "sandbar"
RUNNER = INTEG / "line_round_runner.py"

STUB = (
    "import json, os, subprocess, sys, time\n"
    "cwd = os.getcwd()\n"
    "sys.path.insert(0, os.path.join(cwd, 'integration'))\n"
    "import scenario_ledger as sl\n"
    "verdicts = json.loads(os.environ.get('STUB_VERDICTS', '[\"pass\"]'))\n"
    "rev = subprocess.run(['git', '-C', cwd, 'rev-parse', 'HEAD'],\n"
    "                     capture_output=True, text=True).stdout.strip()\n"
    "rid = sl.mint_run_id()\n"
    "fp_sha = hashlib_sha\n"
    "now = time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())\n"
    "rows = [{'ts': now, 'commit': rev, 'env_fp': fp_sha,\n"
    "         'conc_width': 1, 'pool': 'ro', 'scenario': 'sc_%d' % i,\n"
    "         'verdict': v, 'wall_s': 0.1,\n"
    "         'source': 'lane:line-round', 'ticket': '', 'run': rid}\n"
    "        for i, v in enumerate(verdicts)]\n"
    "sl.append_records(rows)\n"
    "counts = {'ran': len(rows), 'passed': verdicts.count('pass'),\n"
    "          'failed': verdicts.count('fail'),\n"
    "          'env_failed': verdicts.count('env_fail')}\n"
    "hdr = {'v': sl.RUN_HEADER_V, 'id': rid,\n"
    "       'repos': [{'repo': 'src', 'revision': rev}],\n"
    "       'suite': 'full', 'source': 'lane:line-round',\n"
    "       'env_fp': fp_sha, 'conc_width': 1, 'pool': 'ro',\n"
    "       'started_at': int(time.time() * 1000), 'duration_s': 0.1,\n"
    "       'cases': counts, 'verdict': sl.run_verdict(counts)}\n"
    "sl.append_run_header(hdr)\n"
    "for i, v in enumerate(verdicts):\n"
    "    fmt = {'pass': 'PASS [sc_%d] (0.1s)',\n"
    "           'fail': 'FAIL [sc_%d] exit=1 (0.1s)'}[v]\n"
    "    print(fmt % i, flush=True)\n"
    "print('INTEG_SUMMARY %s' % json.dumps({'ran': len(rows),\n"
    "      'run_id': rid}), flush=True)\n"
)


class StagedRound(unittest.TestCase):
    """A staged round in a temp world whose HOME is a decoy, so even a leak
    cannot reach the real projects root."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        # the decoy "real" projects root that an unpinned round would use
        # (it is what $HOME resolves to, never the production home)
        self.decoy_project = self.home / ".sandbar" / "projects" / PROJECT_KEY
        (self.decoy_project / "data" / "develop").mkdir(parents=True)
        (self.decoy_project / "ledger").mkdir(parents=True)
        (self.decoy_project / "data" / "develop" / "lines.json").write_text(
            json.dumps([{"line_id": "develop-buffer",
                         "repositories": [{"name": "src",
                                           "branch": "main"}]}]),
            encoding="utf-8")
        # the staged project root the fixture OWNS
        self.projects = self.base / "projects"
        (self.projects / PROJECT_KEY / "data" / "develop").mkdir(
            parents=True)
        (self.projects / PROJECT_KEY / "data" / "develop"
         / "lines.json").write_text(
            json.dumps([{"line_id": "develop-buffer",
                         "repositories": [{"name": "src",
                                           "branch": "main"}]}]),
            encoding="utf-8")
        self.face = self.base / "face" / "data" / "develop"
        self.face.mkdir(parents=True)
        self.run_root = self.base / "run"
        self.src = self.make_repo()
        self.stub = self.base / "stub_suite.py"
        self.stub.write_text(STUB.replace("hashlib_sha",
                                          "'0' * 64"), encoding="utf-8")
        self.real_before = real_root.snapshot(PROJECT_KEY)

    def tearDown(self):
        try:
            after = real_root.snapshot(PROJECT_KEY)
            self.assertEqual(real_root.diff(self.real_before, after),
                             ([], [], []),
                             "this battery wrote the REAL projects root: %s"
                             % real_root.describe(self.real_before, after))
        finally:
            self.tmp.cleanup()

    def make_repo(self):
        src = self.base / "src"
        (src / "integration").mkdir(parents=True)
        (src / "integration" / "run_scenarios.py").write_text("# stub\n")
        shutil.copyfile(INTEG / "scenario_ledger.py",
                        src / "integration" / "scenario_ledger.py")
        (src / "server" / "engine").mkdir(parents=True)
        shutil.copyfile(ROOT / "server" / "engine" / "failure_protocol.py",
                        src / "server" / "engine" / "failure_protocol.py")
        for argv in (["git", "init", "-q", str(src)],
                     ["git", "-C", str(src), "add", "-A"],
                     ["git", "-C", str(src), "commit", "-qm", "t"]):
            subprocess.run(argv, check=True, capture_output=True)
        return src

    def staged_env(self, pinned=True):
        rev = subprocess.run(["git", "-C", str(self.src), "rev-parse",
                              "HEAD"], capture_output=True, text=True
                             ).stdout.strip()
        env = dict(os.environ)
        env["HOME"] = str(self.home)  # a leak lands in the decoy, not production
        env.update({
            "SANDBAR_LINE_ROUND_CANDIDATES": json.dumps(
                [{"repo": "src", "revision": rev}]),
            "SANDBAR_LINE_ROUND_RUN_ROOT": str(self.run_root),
            "SANDBAR_LINE_ROUND_REPO_PATH_SRC": str(self.src),
            "SANDBAR_LINE_ROUND_SUITE_CMD": "%s %s" % (sys.executable,
                                                       self.stub),
            "SANDBAR_LINE_ROUND_FACE_DIR": str(self.face),
        })
        if pinned:
            env["SANDBAR_PROJECTS_DIR"] = str(self.projects)
        else:
            env.pop("SANDBAR_PROJECTS_DIR", None)
            env.pop("SANDBAR_LINE_ROUND_FACE_DIR", None)  # the incident shape
        return env

    def run_round(self, pinned=True):
        # wait bound injectable (L25): seconds in practice, generous cap only
        cap = float(os.environ.get("T261030_RUNNER_TIMEOUT_S", "180"))
        return subprocess.run([sys.executable, str(RUNNER)],
                              env=self.staged_env(pinned),
                              capture_output=True, text=True, timeout=cap)

    def watch(self, root):
        return real_root.snapshot(PROJECT_KEY, root=root)


class Isolated(unittest.TestCase):
    def setUp(self):
        self.case = StagedRound("run")
        self.case.setUp()

    def tearDown(self):
        self.case.tearDown()

    def test_i1_a_staged_round_writes_neither_root(self):
        staged_before = self.case.watch(self.case.projects / PROJECT_KEY)
        decoy_before = self.case.watch(self.case.decoy_project)
        proc = self.case.run_round(pinned=True)
        self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
        # a round really ran (a header came back), then nothing moved
        staged_after = self.case.watch(self.case.projects / PROJECT_KEY)
        self.assertEqual(real_root.diff(staged_before, staged_after),
                         ([], [], []),
                         "the staged round escaped its own projects root: %s"
                         % real_root.describe(staged_before, staged_after))
        decoy_after = self.case.watch(self.case.decoy_project)
        self.assertEqual(real_root.diff(decoy_before, decoy_after),
                         ([], [], []),
                         "an ISOLATED round must not publish anywhere else: %s"
                         % real_root.describe(decoy_before, decoy_after))

    def test_i2_mutation_proof_the_instrument_sees_the_leak(self):
        """The same round with the seams REMOVED (the incident shape) writes
        the decoy projects root — the watcher names it. This is the mutation
        proof that I1 is not vacuous; it runs against the decoy because a
        test may never demonstrate a leak by leaking into production."""
        before = self.case.watch(self.case.decoy_project)
        proc = self.case.run_round(pinned=False)
        self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
        after = self.case.watch(self.case.decoy_project)
        added, removed, changed = real_root.diff(before, after)
        self.assertTrue(
            any(p.startswith("data/develop/rounds/run-") for p in added),
            "the leak was not visible to the watcher (added=%r)" % (added,))
        self.assertTrue(
            "ledger/scenario-runs.jsonl" in added + changed,
            "the leaked run row was not visible (added=%r changed=%r)"
            % (added, changed))


if __name__ == "__main__":
    unittest.main()
