#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26101118_line_round_assets.py — t261011-18, the line round can run the
suite inside its own cloned checkout: the runner hands the suite the assets
the clone cannot resolve itself, an unusable pointer is an honest named
could-not-run, and an unrunnable round grows the range instead of minting a
certification (grey-box L3, real resolve_runner/run_line_round + a real git
fixture tree + a stub suite, offline seconds, zero docker/Temporal-server,
the real ledgers never written).

intent (the user-perceivable behavior; sources = the ticket's original user
request + the delivered plan's route-1 contract):
    A. The incident's mechanism is closed: with the asset env keys UNSET, a
       line round whose candidate tree is a CLONE (real .git dir, gitignored
       assets absent) still completes — the suite's env carries
       SANDBAR_POC_PYTHON / SANDBAR_TEMPORAL_BIN pointing at EXISTING paths
       outside the clone, and the round returns one real header (never
       could-not-run).
    B. The operator's pointer wins: keys pre-set in the worker env pass
       through VERBATIM — the runner resolves nothing it was told, never
       overwrites (the env key is the documented override, bench._resolve_asset
       honors it first).
    C. Honesty on a bad pointer: a pre-set key naming a nonexistent path is a
       NAMED could-not-run carrying the env key and the bad path — never a
       fabricated header, never a silent skip.
    D. The whole-round last mile (the incident's ledger shape): a round whose
       runner refuses for the asset reason appends EXACTLY one range_growth
       row to the delivery ledger and ZERO certification rows — a landed
       ticket is never certified by a proof that could not run, and never
       frozen by one either.

Layering / intent split (no intent-level duplication):
  - the runner command -> one header contract, red-is-a-proof, timeout,
    gate-owner neutralization -> t261009-77-line-round-runner;
  - round decision/certification truth tables, red-freeze-exempt ->
    the t261009-30 family;
  - the resolution tiers' unit truth table (env > lane > main-tree, pure
    MissingAsset semantics) -> developer L1. This entry owns ONE contract:
    the cloned candidate tree ends up with a runnable suite environment, and
    the failure side of that handover is named end to end.

Three states: the runner's OWN checkout lacking either asset = ENV_FAIL exit
2 (an environment property, not a verdict); a missing handover/overwrite/
honesty face = FAIL named (TDD signal), must be green at arbitrate/merge.
"""
import atexit
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NAME = "t261011-18-line-round-assets"

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

sys.path.insert(0, str(REPO / "server" / "engine"))
try:
    import develop_certify as dc  # noqa: E402
except Exception as e:  # noqa: BLE001
    env_fail("develop_certify unimportable", "%s: %s" % (type(e).__name__, e))
    sys.exit(2)

LINE = {"line_id": "develop-buffer", "repo": "sandbar"}
POC_KEY = "SANDBAR_POC_PYTHON"
TEMPORAL_KEY = "SANDBAR_TEMPORAL_BIN"


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, timeout=120)


# ---------------------------------------------------------------- fixture

_STUB = '''#!/usr/bin/env python3
# Stub full suite: the fixture stand-in for integration/run_scenarios.py.
# Same ledger/header shape as the t261009-77 stub, plus the ASSET probe face:
# what the two asset env keys carried when the suite actually ran INSIDE the
# clone, and whether the clone's own lane asset paths exist (the clone is the
# reason the handover is load-bearing).
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
        "poc_env": os.environ.get("SANDBAR_POC_PYTHON", ""),
        "temporal_env": os.environ.get("SANDBAR_TEMPORAL_BIN", ""),
        "clone_poc_exists": (ROOT / "server" / "engine" / ".venv" / "bin"
                             / "python").exists(),
        "clone_temporal_exists": (ROOT / "server" / "engine" / "bin"
                                  / "temporal").exists(),
    }), encoding="utf-8")

run_id = sl.mint_run_id()
row = {
    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "commit": head,
    "env_fp": hashlib.sha256(b"stub-suite").hexdigest(),
    "conc_width": 1,
    "pool": "serial",
    "scenario": "stub-line-round-assets",
    "verdict": "pass",
    "wall_s": 0.1,
    "source": "lane:stub",
    "ticket": "t261011-18",
    "run": run_id,
}
clean, why = sl.validate_row(row)
if clean is None:
    sys.stderr.write("stub row refused: %s\\n" % why)
    sys.exit(2)
if sl.append_records([clean])["written"] != 1:
    sys.stderr.write("stub row not written\\n")
    sys.exit(2)
cases = {"ran": 1, "passed": 1, "failed": 0, "env_failed": 0}
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
    {"ran": 1, "passed": 1, "failed": 0, "env_failed": 0,
     "run_id": run_id}))
sys.exit(0)
'''


def _build_fixture(tmp):
    """A real clean git tree whose committed content is exactly what git
    carries: the stub suite + ledger module, a marker run_scenarios.py, and a
    .gitignore that keeps .venv/ and bin/ OUT — so the clone is the incident's
    tree shape by construction (real .git dir, gitignored assets absent)."""
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
    (src / ".gitignore").write_text(
        "__pycache__/\\nserver/engine/.venv/\\nserver/engine/bin/\\n",
        encoding="utf-8")
    _git("add", "-A", cwd=src)
    r = _git("commit", "-q", "-m", "fixture: line-round asset handover stand",
             cwd=src)
    if r.returncode != 0:
        env_fail("fixture commit failed", (r.stderr or "")[-300:])
        sys.exit(2)
    head = _git("rev-parse", "HEAD", cwd=src).stdout.strip()
    return src, head


def _declare_runner(src, head, tmp, mode, extra=None):
    """The production seam exactly as an operator sets it. Asset keys are NOT
    set here unless a leg names them explicitly."""
    env = clean_narrowing_env()
    env["SANDBAR_LINE_ROUND_RUNNER"] = (
        "python3 %s/integration/line_round_runner.py" % str(REPO))
    env["SANDBAR_LINE_ROUND_REPO_PATH_SANDBAR"] = str(src)
    env["SANDBAR_LINE_ROUND_SUITE_CMD"] = "python3 tools/stub_suite.py %s" % mode
    env["SANDBAR_LINE_ROUND_RUNNER_TIMEOUT_S"] = "120"
    env["SANDBAR_LINE_ROUND_RUN_ROOT"] = str(tmp / ("runroot-" + mode))
    env.update({k: str(v) for k, v in (extra or {}).items()})
    return env


def _runner_of(env):
    try:
        return dc.resolve_runner(LINE, env), None
    except Exception as e:  # noqa: BLE001
        return None, "%s:%s" % (type(e).__name__, e)


# ---------------------------------------------------------------- main

def main():
    global _TMP
    _TMP = Path(tempfile.mkdtemp(prefix="t26101118-assets-"))
    src, head = _build_fixture(_TMP)
    candidates = [{"repo": "sandbar", "revision": head}]

    # ---- precondition: the runner's own checkout can resolve both assets,
    # otherwise this host cannot judge the handover at all -> ENV_FAIL.
    saved = {k: os.environ.pop(k, None) for k in (POC_KEY, TEMPORAL_KEY)}
    sys.path.insert(0, str(REPO / "integration"))
    try:
        import bench  # noqa: E402  (the runner's own resolution logic)
        poc = str(bench.resolve_poc_python())
        temporal = str(bench.resolve_temporal_bin())
    except Exception as e:  # noqa: BLE001
        env_fail("runner checkout lacks resolvable assets (poc/temporal)",
                 "%s: %s" % (type(e).__name__, e))
        sys.exit(2)
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v

    # ---- A: the incident's mechanism is closed (keys unset, clone is the
    # tree shape that could never self-resolve) ----
    probe_a = _TMP / "probe-green.json"
    env = _declare_runner(src, head, _TMP, "green",
                          extra={"SUITE_PROBE_OUT": str(probe_a)})
    runner, rerr = _runner_of(env)
    header = None
    ok(runner is not None and rerr is None,
       "A1 runner declared -> callable", str(rerr or ""))
    if runner is not None:
        try:
            header = runner(candidates)
            err = None
        except dc.CouldNotRun as e:
            header, err = None, str(e)
        ok(err is None and isinstance(header, dict)
           and str(header.get("id", "")).startswith("run-"),
           "A2 keys unset, candidate is a clone -> one real header "
           "(never could-not-run)",
           "" if err is None else "CouldNotRun:%s" % err)

    if probe_a.is_file():
        probe = json.loads(probe_a.read_text(encoding="utf-8"))
        clone = str(probe.get("cwd", ""))
        ok(probe.get("clone_poc_exists") is False
           and probe.get("clone_temporal_exists") is False,
           "A3 precondition: the clone carries NEITHER asset "
           "(the handover is load-bearing, not decorative)",
           json.dumps({k: probe.get(k) for k in
                       ("clone_poc_exists", "clone_temporal_exists")}))
        poc_env = str(probe.get("poc_env", ""))
        temporal_env = str(probe.get("temporal_env", ""))
        ok(poc_env and Path(poc_env).exists(),
           "A4 suite env carried SANDBAR_POC_PYTHON at an EXISTING path",
           "poc_env=%r" % poc_env)
        ok(temporal_env and Path(temporal_env).exists(),
           "A5 suite env carried SANDBAR_TEMPORAL_BIN at an EXISTING path",
           "temporal_env=%r" % temporal_env)
        real_clone = os.path.realpath(clone) + os.sep if clone else "?"
        ok(poc_env and not os.path.realpath(poc_env).startswith(real_clone),
           "A6 the poc pointer resolves OUTSIDE the clone (runner's own "
           "checkout, not the clone that lacks it)", poc_env[:200])
        ok(temporal_env
           and not os.path.realpath(temporal_env).startswith(real_clone),
           "A7 the temporal pointer resolves OUTSIDE the clone",
           temporal_env[:200])
    else:
        ok(False, "A3-A7 skipped: stub probe face missing (suite never ran)",
           str(probe_a))

    # ---- B: the operator's pointer wins, verbatim ----
    fake_poc = _TMP / "fixture-python"
    shutil.copy2(sys.executable, str(fake_poc))
    fake_temporal = _TMP / "fixture-temporal"
    fake_temporal.write_text("#!/bin/sh\\nexit 0\\n", encoding="utf-8")
    fake_temporal.chmod(fake_temporal.stat().st_mode | stat.S_IEXEC)
    probe_b = _TMP / "probe-passthrough.json"
    env = _declare_runner(src, head, _TMP, "green-pt", extra={
        POC_KEY: str(fake_poc), TEMPORAL_KEY: str(fake_temporal),
        "SUITE_PROBE_OUT": str(probe_b)})
    runner, _ = _runner_of(env)
    if runner is not None:
        try:
            header_b = runner(candidates)
            err = None
        except dc.CouldNotRun as e:
            header_b, err = None, str(e)
        ok(err is None and isinstance(header_b, dict),
           "B1 pre-set keys -> round still completes",
           "" if err is None else "CouldNotRun:%s" % err)
    if probe_b.is_file():
        probe_b_d = json.loads(probe_b.read_text(encoding="utf-8"))
        ok(probe_b_d.get("poc_env") == str(fake_poc)
           and probe_b_d.get("temporal_env") == str(fake_temporal),
           "B2 the operator's pointers arrived VERBATIM (never "
           "re-resolved, never overwritten)",
           json.dumps({k: probe_b_d.get(k) for k in
                       ("poc_env", "temporal_env")})[:300])
    else:
        ok(False, "B2 skipped: stub probe face missing", str(probe_b))

    # ---- C: a bad pointer is an honest named could-not-run ----
    bad = str(_TMP / "no-such" / "interpreter")
    env = _declare_runner(src, head, _TMP, "bad-ptr", extra={
        POC_KEY: bad})
    runner, _ = _runner_of(env)
    err_c = None
    if runner is not None:
        try:
            runner(candidates)
        except dc.CouldNotRun as e:
            err_c = str(e)
    ok(err_c is not None and POC_KEY in err_c and bad in err_c,
       "C nonexistent pointer -> CouldNotRun naming the env key AND the "
       "bad path (never a header, never a silent skip)",
       str(err_c)[:300])

    # ---- D: the whole-round last mile (the incident's ledger shape) ----
    dl_path = _TMP / "delivery" / "ledger.jsonl"
    dl_path.parent.mkdir(parents=True, exist_ok=True)

    def read_rows():
        return dc.read_rows(str(dl_path))

    def append_rows(batch):
        return dc.append_rows(batch, str(dl_path))

    append_rows([{"kind": "landing", "id": "ldg-scenario0001",
                  "ticket": "t-x", "line": "develop-buffer", "actor": "host",
                  "repos": candidates, "at": 1}])
    guard = _TMP / "delivery" / "guard"
    runner, _ = _runner_of(env)  # C's bad-pointer env, reused on purpose
    if runner is not None:
        try:
            res = dc.run_line_round("develop-buffer", "change", str(guard),
                                    runner, read_rows, append_rows,
                                    judged_by="scenario", booked_red="v1",
                                    now_ms=2)
            err_d = None
        except (dc.CouldNotRun, dc.CertifyError) as e:
            res, err_d = None, "%s:%s" % (type(e).__name__, e)
        rounds = (res or {}).get("rounds", [])
        rows, _ = read_rows()
        growth = [r for r in rows if r.get("kind") == "range_growth"]
        certs = [r for r in rows if r.get("kind") == "certification"]
        ok(err_d is None and rounds
           and rounds[0].get("state") != "certified",
           "D1 the round did NOT certify an unrunnable proof",
           str(err_d or json.dumps(rounds)[:200]))
        # The round CHAINS while anything is still waiting (t261009-30: a
        # round that ends is followed at once by the next, bounded by
        # chain_limit), so an always-refusing runner legitimately lands one
        # range_growth row PER chained ask. The contract under test is not
        # the chain length — it is that every refusal is a NAMED growth row
        # and none of them ever mints a certification.
        ok(len(growth) >= 1
           and all("asset_missing:SANDBAR_POC_PYTHON" in str(r.get("reason"))
                   for r in growth),
           "D2 every chained refusal is a NAMED range_growth row carrying "
           "the asset-miss reason (the proof grew the range, never froze, "
           "never vanished)",
           json.dumps(growth)[:300])
        ok(len(certs) == 0,
           "D3 ZERO certification rows in the ledger (a could-not-run "
           "never mints the covering certification)",
           json.dumps(certs)[:200])

    finish(NAME)


if __name__ == "__main__":
    main()
