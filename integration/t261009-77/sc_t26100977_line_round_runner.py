#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26100977_line_round_runner.py — t261009-77, the declared line-round
runner satisfies the engine's contract end to end (grey-box L3, real
develop_certify.resolve_runner + a real git fixture tree + a stub suite,
offline seconds, zero docker/Temporal-server, the real ledgers never written).

intent (the user-perceivable behavior; sources = the ticket contract +
develop_certify.resolve_runner's docstring + docs/reference/
ledger-record-models-v1.md section A run record):
    A. Header contract end to end: with the runner command declared in the
       worker env and a candidate set given, the callable resolve_runner
       builds returns exactly one JSON header (id=run-, the cases counts)
       and exit 0. The header is the one the stub suite wrote into THIS
       round's ledger (the runner never recounts, never invents).
    B. The candidates set is what runs (own tree): the stub records the
       SANDBAR_LINE_ROUND_CANDIDATES it received, its cwd and that cwd's
       git HEAD — the set is byte-equal, cwd is NOT the source checkout,
       the clone HEAD equals the candidate revision, the source checkout
       stays clean, reuse is off (a ran==0 header is no proof).
    C. Red is a proof: a stub header with failed=1 -> the runner still
       exits 0 and returns the red header (red opens the freeze path,
       never could_not_run).
    D. Could-not-run honesty: a stub that exits nonzero with stderr ->
       CouldNotRun carrying that stderr tail (that is what the round's
       record names; never a fabricated header).
    E. Timeout face: a hanging stub + SANDBAR_LINE_ROUND_RUNNER_TIMEOUT_S=1
       -> CouldNotRun named runner_timeout.
    F. An inherited gate-owner env must not steal the proof: worker env
       carrying SANDBAR_INTEG_LEDGER_OWNER=gate (the worker's interactive
       single-writer knob) -> the header is still produced (review_plan
       condition C1).
    G. Whole-round face: run_line_round with the real runner over a temp
       delivery ledger lands exactly one certification row citing the run
       id; the second ask idles (the range is closed).

Layering / intent split (no intent-level duplication):
  - run record store/CLI contract (minting, refusals, interrupted runs)
    -> t261009-11-run-record-store;
  - both driver write faces (executor top-driver / gate) -> t261009-11
    -run-record-drivers;
  - ledger reuse and trust -> t260930-01 / t260922-12 families;
  - round decision logic / certification model truth tables -> the
    t261009-30 line-round family. This entry owns ONE asset contract: the
    declared runner command turns a candidate revision set into one real
    run header. The malformed-input matrix and process-group reclaim are
    developer L1 (integration/tests/test_t261009_77_line_round_runner.py).

Env seams the scenario declares to the runner (declaration faces the
runner implements): SANDBAR_LINE_ROUND_REPO_PATH_<NAME> (per-repo source
checkout, plan-declared), SANDBAR_LINE_ROUND_RUN_ROOT (this round's own
tree root — never inside the source checkout), SUITE_PROBE_OUT (where the
stub writes its probe face for the scenario to read back).

Three states: git or develop_certify missing = ENV_FAIL exit 2; a locked
runner face missing = FAIL named (TDD signal), must be green at
arbitrate/merge.
"""
import atexit
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NAME = "t261009-77-line-round-runner"

sys.path.insert(0, str(REPO / "integration"))
from lib_env import clean_narrowing_env  # noqa: E402
from lib_result import ScenarioCheck  # noqa: E402

_ck = ScenarioCheck(detail_cap=600, flush=True)
ok = _ck.ok
finish = _ck.finish
env_fail = _ck.env_fail

_TMP = None


def _cleanup():
    if _TMP is not None:
        shutil.rmtree(str(_TMP), ignore_errors=True)


atexit.register(_cleanup)

# Engine module (the truth source face; never copied, never stubbed)
sys.path.insert(0, str(REPO / "server" / "engine"))
try:
    import develop_certify as dc  # noqa: E402
except Exception as e:  # noqa: BLE001
    env_fail("develop_certify unimportable", "%s: %s" % (type(e).__name__, e))
    sys.exit(2)

LINE = {"line_id": "develop-buffer", "repo": "sandbar"}


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, timeout=120)


# ---------------------------------------------------------------- fixture

_STUB = '''#!/usr/bin/env python3
# Stub full suite: the fixture stand-in for integration/run_scenarios.py.
# Writes ONE run-stamped row + ONE validated header into the ledger dir the
# runner pointed this round at, prints the INTEG_SUMMARY line, and records a
# probe face (candidates, cwd, HEAD, inherited knobs) where SUITE_PROBE_OUT
# names (outside the run tree, which the runner reclaims).
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
if mode == "slow":
    time.sleep(30)
    sys.exit(0)
if mode == "boom":
    sys.stderr.write("stub-boom: injected suite crash\\n")
    sys.exit(3)

candidates = json.loads(os.environ["SANDBAR_LINE_ROUND_CANDIDATES"])
ledger = Path(os.environ["SANDBAR_SCENARIO_LEDGER_DIR"])
ledger.mkdir(parents=True, exist_ok=True)
head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                      capture_output=True, text=True).stdout.strip()
probe_out = os.environ.get("SUITE_PROBE_OUT", "")
if probe_out:
    Path(probe_out).write_text(json.dumps({
        "candidates": candidates,
        "cwd": os.getcwd(),
        "head": head,
        "owner": os.environ.get("SANDBAR_INTEG_LEDGER_OWNER", ""),
        "reuse": os.environ.get("SANDBAR_LEDGER_REUSE", ""),
    }), encoding="utf-8")

run_id = sl.mint_run_id()
row = {
    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "commit": head,
    "env_fp": hashlib.sha256(b"stub-suite").hexdigest(),
    "conc_width": 1,
    "pool": "serial",
    "scenario": "stub-line-round",
    "verdict": "fail" if mode == "red" else "pass",
    "wall_s": 0.1,
    "source": "lane:stub",
    "ticket": "t261009-77",
    "run": run_id,
}
clean, why = sl.validate_row(row)
if clean is None:
    sys.stderr.write("stub row refused: %s\\n" % why)
    sys.exit(2)
if sl.append_records([clean])["written"] != 1:
    sys.stderr.write("stub row not written\\n")
    sys.exit(2)
cases = ({"ran": 1, "passed": 0, "failed": 1, "env_failed": 0}
         if mode == "red" else
         {"ran": 1, "passed": 1, "failed": 0, "env_failed": 0})
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


def _build_fixture(tmp):
    """A real clean git tree: the candidate source the runner clones from.
    Commits the stub suite + the ledger module so the CLONE can run them."""
    src = tmp / "source"
    src.mkdir()
    r = _git("init", "-q", cwd=src)
    if r.returncode != 0:
        env_fail("git init failed", (r.stderr or "")[-300:])
        sys.exit(2)
    _git("config", "user.email", "scenario@example.invalid", cwd=src)
    _git("config", "user.name", "scenario", cwd=src)
    (src / "integration").mkdir()
    shutil.copy2(str(REPO / "integration" / "scenario_ledger.py"),
                 str(src / "integration" / "scenario_ledger.py"))
    # scenario_ledger lazily loads the verdict vocabulary from the engine
    # tree (server/engine relative to its own location) — same fixture
    # technique as the t261009-11 drivers scenario.
    eng = src / "server" / "engine"
    eng.mkdir(parents=True)
    shutil.copy2(str(REPO / "server" / "engine" / "failure_protocol.py"),
                 str(eng / "failure_protocol.py"))
    tools = src / "tools"
    tools.mkdir()
    (tools / "stub_suite.py").write_text(_STUB, encoding="utf-8")
    (src / "integration" / "run_scenarios.py").write_text(
        "# fixture stand-in: the primary-tree marker the runner detects\\n",
        encoding="utf-8")
    (src / ".gitignore").write_text("__pycache__/\\n", encoding="utf-8")
    _git("add", "-A", cwd=src)
    r = _git("commit", "-q", "-m", "fixture: line-round runner stand",
             cwd=src)
    if r.returncode != 0:
        env_fail("fixture commit failed", (r.stderr or "")[-300:])
        sys.exit(2)
    head = _git("rev-parse", "HEAD", cwd=src).stdout.strip()
    return src, head


def _declare_runner(src, head, tmp, mode, extra=None):
    """The production seam exactly as an operator sets it: the runner command
    in the worker env, the suite knob pointing at the stub inside the tree,
    this round's own tree root named."""
    env = clean_narrowing_env()
    env["SANDBAR_LINE_ROUND_RUNNER"] = (
        "python3 %s/integration/line_round_runner.py" % str(REPO))
    env["SANDBAR_LINE_ROUND_REPO_PATH_SANDBAR"] = str(src)
    env["SANDBAR_LINE_ROUND_SUITE_CMD"] = "python3 tools/stub_suite.py %s" % mode
    env["SANDBAR_LINE_ROUND_RUNNER_TIMEOUT_S"] = "120"
    env["SANDBAR_LINE_ROUND_RUN_ROOT"] = str(tmp / ("runroot-" + mode))
    env.update({k: str(v) for k, v in (extra or {}).items()})
    return env


# ---------------------------------------------------------------- main

def main():
    global _TMP
    _TMP = Path(tempfile.mkdtemp(prefix="t26100977-runner-"))
    src, head = _build_fixture(_TMP)
    candidates = [{"repo": "sandbar", "revision": head}]

    # ---- A: header contract end to end ----
    env = _declare_runner(src, head, _TMP, "green", extra={
        "SUITE_PROBE_OUT": str(_TMP / "probe-green.json")})
    runner = dc.resolve_runner(LINE, env)
    header = None
    ok(runner is not None,
       "A1 runner declared -> callable (not runner_missing)")
    if runner is not None:
        try:
            header = runner(candidates)
            err = None
        except dc.CouldNotRun as e:
            header, err = None, str(e)
        ok(err is None and isinstance(header, dict),
           "A2 candidate set -> one header dict, no CouldNotRun",
           "" if err is None else "CouldNotRun:%s" % err)
        if isinstance(header, dict):
            ok(str(header.get("id", "")).startswith("run-")
               and isinstance(header.get("cases"), dict),
               "A4 header shape: run- id + cases counts",
               json.dumps(header)[:200])

    # ---- B: the candidates set is what runs, in a tree of its own ----
    if isinstance(header, dict):
        probe_path = _TMP / "probe-green.json"
        ok(probe_path.is_file(), "B1 the stub's probe face exists",
           str(probe_path))
        if probe_path.is_file():
            probe = json.loads(probe_path.read_text(encoding="utf-8"))
            ok(probe.get("candidates") == candidates,
               "B2 stub received the candidate set byte-equal",
               json.dumps(probe.get("candidates"))[:200])
            cwd = str(probe.get("cwd", ""))
            ok(cwd and not os.path.realpath(cwd).startswith(
                   os.path.realpath(str(src)) + os.sep),
               "B3 suite ran in its own tree, not the delivered checkout",
               cwd[:200])
            ok(probe.get("head") == head,
               "B4 clone HEAD == candidate revision",
               ("%s != %s" % (probe.get("head"), head))[:200])
            ok(probe.get("reuse") in ("0", "off", "false", "no"),
               "B5 suite env disables ledger reuse (ran==0 header is no "
               "proof)", "reuse=%r" % probe.get("reuse"))
            st = _git("status", "--porcelain", cwd=src)
            ok(st.returncode == 0 and not st.stdout.strip(),
               "B6 source checkout untouched by the round")

    # ---- F: an inherited gate-owner env must not steal the proof ----
    env = _declare_runner(src, head, _TMP, "green2",
                          extra={"SANDBAR_INTEG_LEDGER_OWNER": "gate",
                                 "SUITE_PROBE_OUT":
                                     str(_TMP / "probe-owner.json")})
    runner = dc.resolve_runner(LINE, env)
    if runner is not None:
        try:
            header_f = runner(candidates)
            err = None
        except dc.CouldNotRun as e:
            header_f, err = None, str(e)
        ok(err is None and isinstance(header_f, dict) and
           str(header_f.get("id", "")).startswith("run-"),
           "F gate-owner env inherited -> header still produced",
           "" if err is None else "CouldNotRun:%s" % err)
        probe_f = _TMP / "probe-owner.json"
        if probe_f.is_file():
            owner = json.loads(
                probe_f.read_text(encoding="utf-8")).get("owner", "x")
            ok(owner == "",
               "F2 the owner flag was neutralized before the suite ran",
               "owner=%r" % owner)

    # ---- C: red is a proof ----
    env = _declare_runner(src, head, _TMP, "red")
    runner = dc.resolve_runner(LINE, env)
    if runner is not None:
        try:
            header_r = runner(candidates)
            err = None
        except dc.CouldNotRun as e:
            header_r, err = None, str(e)
        ok(err is None and isinstance(header_r, dict)
           and header_r.get("verdict") == "red",
           "C completed-but-red round -> red header, exit 0 "
           "(never CouldNotRun)",
           "" if err is None else "CouldNotRun:%s" % err)

    # ---- D: could-not-run honesty (nonzero suite, stderr named) ----
    env = _declare_runner(src, head, _TMP, "boom")
    runner = dc.resolve_runner(LINE, env)
    if runner is not None:
        try:
            runner(candidates)
            err = None
        except dc.CouldNotRun as e:
            err = str(e)
        ok(err is not None and "stub-boom" in err,
           "D nonzero suite -> CouldNotRun naming the runner's stderr",
           str(err)[:200])

    # ---- E: the engine's timeout owns the wall clock ----
    env = _declare_runner(src, head, _TMP, "slow",
                          extra={"SANDBAR_LINE_ROUND_RUNNER_TIMEOUT_S": "1"})
    runner = dc.resolve_runner(LINE, env)
    if runner is not None:
        try:
            runner(candidates)
            err = None
        except dc.CouldNotRun as e:
            err = str(e)
        ok(err is not None and err.startswith("runner_timeout"),
           "E timeout -> CouldNotRun named runner_timeout", str(err)[:120])

    # ---- G: the whole-round face at engine level ----
    # The injected seams are the ENGINE'S OWN ledger faces (read_rows/
    # append_rows over a temp delivery ledger) — the production writer is
    # what stamps seq inside the critical section, so the records' shared
    # ordering space is the real one, not a scenario imitation.
    dl_path = _TMP / "delivery" / "ledger.jsonl"
    dl_path.parent.mkdir(parents=True, exist_ok=True)

    def read_rows():
        return dc.read_rows(str(dl_path))

    def append_rows(batch):
        return dc.append_rows(batch, str(dl_path))

    landing = {"kind": "landing", "id": "ldg-scenario0001", "ticket": "t-x",
               "line": "develop-buffer", "actor": "host",
               "repos": candidates, "at": 1}
    append_rows([landing])
    guard = _TMP / "delivery" / "guard"
    guard.parent.mkdir(parents=True, exist_ok=True)
    env = _declare_runner(src, head, _TMP, "green3")
    runner = dc.resolve_runner(LINE, env)
    if runner is not None:
        # The engine's tick passes the LINE ID STRING to run_line_round —
        # records carry `line` and _of_kind matches it verbatim; only
        # resolve_runner takes the declaration object.
        line_id = LINE["line_id"]
        try:
            res = dc.run_line_round(line_id, "change", str(guard), runner,
                                    read_rows, append_rows,
                                    judged_by="scenario", booked_red="v1",
                                    now_ms=2)
            err = None
        except (dc.CouldNotRun, dc.CertifyError) as e:
            res, err = None, "%s:%s" % (type(e).__name__, e)
        rounds = (res or {}).get("rounds", [])
        rows, _ = read_rows()
        certs = [r for r in rows if r.get("kind") == "certification"]
        ok(err is None and rounds
           and rounds[0].get("state") in ("certified", "red"),
           "G1 one round on the real line face -> certification recorded",
           str(err or json.dumps(rounds)[:200]))
        ok(len(certs) == 1
           and str(certs[0].get("run", "")).startswith("run-"),
           "G2 certification cites the run id (cost per ticket is "
           "measurable)",
           json.dumps(certs[-1] if certs else {})[:200])
        try:
            res2 = dc.run_line_round(line_id, "change", str(guard), runner,
                                     read_rows, append_rows,
                                     judged_by="scenario", booked_red="v1",
                                     now_ms=2)
            err2 = None
        except (dc.CouldNotRun, dc.CertifyError) as e:
            res2, err2 = None, "%s:%s" % (type(e).__name__, e)
        ok(err2 is None and res2.get("end", {}).get("state") == "idle",
           "G3 second ask idles: the range is closed, no double "
           "certification",
           str(err2 or res2.get("end"))[:120])

    finish(NAME)


if __name__ == "__main__":
    main()
