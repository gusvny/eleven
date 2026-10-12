#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared fixture for the t261011-26 round-visibility scenarios.

The same technique as the t261009-77 runner scenario: a REAL clean git
fixture tree (the candidate source the runner clones from), a stub suite
committed inside it, and the REAL integration/line_round_runner.py driven
as a subprocess through the operator-facing env seams.

This ticket's declared seam additions (from the reviewed plan, the
implement step's contract):
  - SANDBAR_LINE_ROUND_FACE_DIR  face-dir override (tests); when unset the
    runner scans SANDBAR_PROJECTS_DIR (or ~/.sandbar/projects) for the
    project whose data/develop/lines.json declares a candidate repo;
  - stable paths under the face dir: rounds/current.json while the round
    runs (absence = idle), rounds/<run_id>/face.json (terminal record) and
    rounds/<run_id>/suite.log (retained evidence).

Nothing here is copied from the production runner; the runner file itself
is executed as the black box under test.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RUNNER = REPO / "integration" / "line_round_runner.py"
FACE_DIR_ENV = "SANDBAR_LINE_ROUND_FACE_DIR"
CURRENT = "rounds/current.json"


def run_stub(mode):
    """The stub suite source. Same ledger contract as the t261009-77 stub
    (one run-stamped row + one validated header + INTEG_SUMMARY), plus the
    suite log vocabulary the face parser reads: PASS/FAIL/ENV_FAIL blocks
    copied verbatim from run_scenarios.py's block shapes."""
    return '''#!/usr/bin/env python3
"""Stub full suite: the fixture stand-in for integration/run_scenarios.py."""
import datetime
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integration"))
import scenario_ledger as sl

mode = sys.argv[1]
if mode == "hang":
    # hang mode IS the fixture: the test SIGTERM-reclaims the runner long
    # before this bound fires
    # SANCTIONED-WAIT: the never-ending suite IS the fixture under test
    time.sleep(120)
    sys.exit(0)
if mode == "boom":
    sys.stderr.write("stub-boom: injected suite crash\\n")
    sys.exit(3)

candidates = json.loads(os.environ["SANDBAR_LINE_ROUND_CANDIDATES"])
ledger = Path(os.environ["SANDBAR_SCENARIO_LEDGER_DIR"])
ledger.mkdir(parents=True, exist_ok=True)
head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                      capture_output=True, text=True).stdout.strip()

run_id = sl.mint_run_id()
scen = {"green": [("sc_alpha", "PASS"), ("sc_beta", "PASS")],
        "slow": [("sc_slow_a", "PASS"), ("sc_slow_b", "PASS")],
        "red": [("sc_red_one", "FAIL")],
        "envfail": [("sc_env_one", "ENV_FAIL")]}[mode]

for name, verdict in scen:
    if verdict == "PASS":
        print("PASS [%s] (0.1s)" % name, flush=True)
    elif verdict == "ENV_FAIL":
        print("ENV_FAIL [%s] exit=2 (0.1s)\\n    stub: missing thing" % name,
              flush=True)
    else:
        print("FAIL [%s] exit=1 (0.1s)\\n    stub: product red" % name,
              flush=True)
    if mode == "slow":
        time.sleep(2.5)

cases = {
    "ran": len(scen),
    "passed": sum(1 for _, v in scen if v == "PASS"),
    "failed": sum(1 for _, v in scen if v == "FAIL"),
    "env_failed": sum(1 for _, v in scen if v == "ENV_FAIL"),
}
for name, verdict in scen:
    row = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "commit": head,
        "env_fp": hashlib.sha256(b"stub-suite").hexdigest(),
        "conc_width": 1,
        "pool": "serial",
        "scenario": name,
        "verdict": {"PASS": "pass", "FAIL": "fail",
                    "ENV_FAIL": "env_fail"}[verdict],
        "wall_s": 0.1,
        "source": "lane:stub",
        "ticket": "t261011-26",
        "run": run_id,
    }
    clean, why = sl.validate_row(row)
    if clean is None:
        sys.stderr.write("stub row refused: %s\\n" % why)
        sys.exit(2)
    if sl.append_records([clean])["written"] != 1:
        sys.stderr.write("stub row not written\\n")
        sys.exit(2)
header = {
    "v": sl.RUN_HEADER_V,
    "id": run_id,
    "repos": candidates,
    "suite": "full",
    "source": "lane:stub",
    "env_fp": row["env_fp"],
    "conc_width": 1,
    "pool": "serial",
    "started_at": int(time.time() * 1000),
    "duration_s": 0.1,
    "cases": cases,
    "verdict": sl.run_verdict(cases),
}
if sl.append_run_header(header)["written"] != 1:
    sys.stderr.write("stub header refused\\n")
    sys.exit(2)
print("INTEG_SUMMARY " + json.dumps(
    {"ran": cases["ran"], "passed": cases["passed"],
     "failed": cases["failed"], "env_failed": cases["env_failed"],
     "run_id": run_id}))
sys.exit(0)
'''


def _git(*args, cwd):
    # git over a tiny local fixture tree - seconds in practice; leak guard
    # SANCTIONED-WAIT: ceiling on a sanctioned child-process git call
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True,
                          # SANCTIONED-WAIT: leak-guard ceiling, seconds-scale
                          timeout=120)


class Fixture:
    """A real git fixture tree + per-round temp dirs; tmp reclaimed on exit."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="t26101126-"))
        atexit.register(self.cleanup)
        self.src = self.tmp / "source"
        self.src.mkdir()
        r = _git("init", "-q", cwd=self.src)
        if r.returncode != 0:
            raise RuntimeError("git init failed: %s" % (r.stderr or "")[-300:])
        _git("config", "user.email", "scenario@example.invalid", cwd=self.src)
        _git("config", "user.name", "scenario", cwd=self.src)
        (self.src / "integration").mkdir()
        shutil.copy2(str(REPO / "integration" / "scenario_ledger.py"),
                     str(self.src / "integration" / "scenario_ledger.py"))
        eng = self.src / "server" / "engine"
        eng.mkdir(parents=True)
        shutil.copy2(str(REPO / "server" / "engine" / "failure_protocol.py"),
                     str(eng / "failure_protocol.py"))
        tools = self.src / "tools"
        tools.mkdir()
        (tools / "stub_suite.py").write_text(run_stub("green"),
                                             encoding="utf-8")
        (self.src / "integration" / "run_scenarios.py").write_text(
            "# fixture stand-in\n", encoding="utf-8")
        (self.src / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
        _git("add", "-A", cwd=self.src)
        r = _git("commit", "-q", "-m", "fixture: round visibility stand",
                 cwd=self.src)
        if r.returncode != 0:
            raise RuntimeError("fixture commit failed: %s"
                               % (r.stderr or "")[-300:])
        self.head = _git("rev-parse", "HEAD", cwd=self.src).stdout.strip()

    def cleanup(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def face_dir(self, name):
        d = self.tmp / ("face-" + name)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _round_env(self, mode, face_dir=None, projects_dir=None, env_extra=None):
        run_root = self.tmp / ("runroot-%s-%d" % (mode, int(time.time() * 1000)))
        state_dir = self.tmp / ("state-%s-%d" % (mode, int(time.time() * 1000)))
        ledger = self.tmp / ("ledger-%s-%d" % (mode, int(time.time() * 1000)))
        env = dict(os.environ)
        env.update({
            "SANDBAR_LINE_ROUND_CANDIDATES":
                json.dumps([{"repo": "sandbar", "revision": self.head}]),
            "SANDBAR_LINE_ROUND_SUITE_CMD":
                "python3 tools/stub_suite.py " + mode,
            "SANDBAR_LINE_ROUND_REPO_PATH_SANDBAR": str(self.src),
            "SANDBAR_LINE_ROUND_RUN_ROOT": str(run_root),
            "SANDBAR_LINE_ROUND_RUN_STATE_DIR": str(state_dir),
            "SANDBAR_SCENARIO_LEDGER_DIR": str(ledger),
        })
        env.pop("SANDBAR_PROJECTS_DIR", None)
        env.pop(FACE_DIR_ENV, None)
        if face_dir is not None:
            env[FACE_DIR_ENV] = str(face_dir)
        if projects_dir is not None:
            env["SANDBAR_PROJECTS_DIR"] = str(projects_dir)
        for k, v in (env_extra or {}).items():
            env[k] = v
        return env

    def run_round(self, mode, face_dir=None, env_extra=None, projects_dir=None,
                  timeout=90):
        """Run the REAL runner as a subprocess; returns the CompletedProcess
        and the run root it used. mode is passed to the stub suite."""
        env = self._round_env(mode, face_dir, projects_dir, env_extra)
        proc = subprocess.run(
            [sys.executable, "-B", str(RUNNER)],
            capture_output=True, text=True, env=env, timeout=timeout,
            cwd=str(REPO))
        return proc

    def run_round_bg(self, mode, face_dir=None, env_extra=None,
                     projects_dir=None):
        """Start the round WITHOUT waiting (Popen) so the test can poll the
        live face while the suite actually runs. Returns (Popen, env)."""
        env = self._round_env(mode, face_dir, projects_dir, env_extra)
        proc = subprocess.Popen(
            [sys.executable, "-B", str(RUNNER)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=env, cwd=str(REPO))
        return proc, env


def seed_run_dir(face_dir, run_id, age_orders=0, live_pointer=False):
    """Seed an old run dir (and optionally a live current.json naming it) the
    way previous rounds would have left them."""
    d = face_dir / "rounds" / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "face.json").write_text(json.dumps(
        {"run_id": run_id, "state": "done", "outcome":
            {"verdict": "green", "reason": "seeded"}}), encoding="utf-8")
    (d / "suite.log").write_text("PASS [seed_%s] (0.1s)\n" % run_id,
                                 encoding="utf-8")
    old = time.time() - 86400 * (30 + age_orders)
    os.utime(str(d), (old, old))
    if live_pointer:
        (face_dir / CURRENT).parent.mkdir(parents=True, exist_ok=True)
        (face_dir / CURRENT).write_text(json.dumps(
            {"run_id": run_id, "state": "running"}), encoding="utf-8")
    return d
