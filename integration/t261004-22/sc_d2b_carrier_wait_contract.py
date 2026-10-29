#!/usr/bin/env python3
"""sc_d2b_carrier_wait_contract — the D2b carrier test must wait, not sleep, and
must name its cause on a genuine failure (t261004-22, grey-box L3; fault-injection
boundary reworked in t261030-05).

Tested exit (the user-perceivable contract): the engine test file
`server/engine/tests/test_t261002_13_tmp_leaker_reclaim.py`, single case
`test_d2b_carrier_detected_through_unresolved_root`, driven as a real pytest
subprocess on the real tree. Intent: a fixed sleep there flaked under load and
blocked unrelated tickets at merge_check; the fix must (R1) poll to a deadline
instead of sleeping, (R2) name the slow-child cause on timeout instead of the
generic carrier-is-invisible message, and (R3) degrade by a named skip when
process enumeration is unavailable instead of a false red. Requirement 4 (keep
the unresolved-root regression assertion) is pinned by the green path A: the
case must still pass with real enumeration.

Fault injection (t261030-05, why the PATH stubs are gone): legs B and C used to
shadow `pgrep`/`lsof` with a stub directory on PATH. That holds only while the
probe face resolves its binaries through PATH. The sweep tool now execs absolute
paths (`/usr/bin/pgrep`, `/usr/sbin/lsof`) and adds a one-pass `lsof -nP -w -F
pcn` (t261029-38, landed on the develop line), so the stubs were bypassed: real
enumeration found the child and the engine case PASSED on both fault legs. That
is the red that froze the line — in-round receipt `summary: pass=8 fail=6` with
B3/B4 and C1..C4 red, reproduced offline and verdict-stable on that tree. The
legs therefore inject at the OS boundary instead: a `sitecustomize` shim on
PYTHONPATH answers every `pgrep`/`lsof` exec of the pytest child, whatever path
or argument form the probe face uses. Each intercepted exec is appended to a
marker file, so a fixture that cannot fabricate the fault reports the NAMED
state `probe_injection_ineffective` instead of judging the product against a
world it did not build.

Sub-cases (each drives the real test via a real venv pytest subprocess):
  A green path: probes forwarded unchanged (the boundary only counts them) ->
    pytest exit 0, "1 passed", and the carrier is seen on the FIRST poll round:
    a fixed sleep before scanning cannot buy that, and a loaded machine only
    makes one round slower, never several.
  B enumeration unavailable: every probe exec answers exit 127 (the executor
    sandbox refuses process tools; `_all_pids` then returns a named error) ->
    pytest must NOT go red for the wrong reason: exit 0 with the case skipped and
    the named reason (mentions pgrep/enumeration) visible.
  C cwd unresolvable: the probes answer, enumeration looks healthy, but only pid
    1 ever resolves a cwd, so the test's own child can never be seen: the
    deadline must fire, pytest must FAIL with the named slow-child message
    (deadline + cwd scan), and must NOT carry the generic carrier-is-invisible
    regression message. The same run proves the wait is a POLL: the engine case
    keeps asking until its deadline instead of sleeping once and guessing.

Bounds (t261030-05): no wall-clock constant decides a verdict. The green path is
 judged on round count (progress), the failing path on the deadline it names, and
the only hard bound left is the per-run subprocess budget, a hang guard. That
guard is injectable through the project's `SANDBAR_*_SECS` convention:
`SANDBAR_D2B_PYTEST_BUDGET_SECS` (default 180s; a malformed or non-positive value
is named and falls back to the default, never silently ignored).

Intent split: the poll/deadline unit matrix and the skip choice belong to the
developer L1 battery in the same test file; this scenario locks the end-to-end
subprocess face — what a reader of a red or yellow run actually sees.

Three states: venv/pytest absent = ENV_FAIL exit 2; any assertion below fails =
FAIL exit 1; all pass = PASS exit 0.

Run directly: python3 integration/t261004-22/sc_d2b_carrier_wait_contract.py (cwd = repo root).
"""
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TARGET = ("server/engine/tests/test_t261002_13_tmp_leaker_reclaim.py"
          "::test_d2b_carrier_detected_through_unresolved_root")
GENERIC_MSG = "carrier invisible through unresolved root"
#: Hang guard only (a run that never returns has to end somewhere). Injectable.
PYTEST_BUDGET_ENV = "SANDBAR_D2B_PYTEST_BUDGET_SECS"
DEFAULT_PYTEST_BUDGET_S = 180
#: Progress floors, counted from the injected boundary, never from a clock. The green
#: path sees its carrier in the first round (the engine case probes once and hits); the
#: deadline-firing path must keep probing (a poll) instead of sleeping once and judging.
MAX_GREEN_ROUNDS = 2
MIN_FAULT_ROUNDS = 5

PROBE_MODE_PASSTHROUGH = "passthrough"
PROBE_MODE_UNAVAILABLE = "unavailable"
PROBE_MODE_CWD_UNRESOLVABLE = "cwd_unresolvable"

PASS, FAIL = 0, 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def venv_python():
    for cand in (REPO / "server/engine/.venv/bin/python",
                 REPO / "server/dsh/temporal-poc/.venv/bin/python"):  # engine-venv-compat 回落路径（t260907-10；摘除票删旧路径）
        if cand.is_file():
            return str(cand)
    return None


def pytest_budget():
    """(effective hang guard in seconds, provenance string). Never silent."""
    raw = (os.environ.get(PYTEST_BUDGET_ENV) or "").strip()
    if not raw:
        return DEFAULT_PYTEST_BUDGET_S, "default"
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_PYTEST_BUDGET_S, "malformed %r -> default" % raw
    if not value > 0:
        return DEFAULT_PYTEST_BUDGET_S, "non-positive %r -> default" % raw
    return value, "env %s" % PYTEST_BUDGET_ENV


#: Probe-boundary shim. Written as the pytest child's `sitecustomize` module, so the
#: interpreter's own site hook loads it: absolute probe paths and one-pass or per-pid
#: argument forms are all covered, and the code under test needs no cooperation.
#: Every intercepted exec lands in the marker file (one line per exec, `<prog> <args>`),
#: so the scenario can count poll rounds and prove the injection was exercised.
SHIM_SRC = r'''"""Fault injection at the process-probe boundary (t261030-05).

Loaded through PYTHONPATH + sitecustomize into the pytest child. Any exec whose
program basename is pgrep or lsof is answered from SANDBAR_D2B_PROBE_MODE (mode
"passthrough" forwards to the real binary and only counts), and the exec is
appended to SANDBAR_D2B_PROBE_MARK.
"""
import os
import subprocess

MODE = os.environ.get("SANDBAR_D2B_PROBE_MODE", "")
MARK = os.environ.get("SANDBAR_D2B_PROBE_MARK", "")
PROBES = ("pgrep", "lsof")
CWD_ROW = "p1\nfcwd\nn/tmp\n"      # one-pass form: exactly one pid resolves a cwd


def _mark(prog, argv):
    if not MARK:
        return
    try:
        with open(MARK, "a", encoding="utf-8") as fh:
            fh.write("%s %s\n" % (prog, " ".join(argv)))
    except OSError:
        pass


def _answer(prog, argv):
    _mark(prog, argv)
    if MODE == "unavailable":
        return 127, ""
    if prog == "pgrep":
        return 0, "1 2\n"
    if "-p" in argv:               # per-pid form: only pid 1 resolves a cwd
        idx = argv.index("-p")
        pid = argv[idx + 1] if len(argv) > idx + 1 else ""
        return (0, CWD_ROW) if pid == "1" else (1, "")
    return 0, CWD_ROW             # one-pass form: enumeration looks healthy


class _Answered(object):
    """What a subprocess.run() caller sees instead of a real child."""

    def __init__(self, rc, out):
        self.returncode = rc
        self.args = ()
        self._out = out

    def communicate(self, input=None, timeout=None):
        return self._out, ""

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        pass

    def terminate(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_REAL_POPEN = subprocess.Popen


def _injected_popen(*args, **kwargs):
    argv = args[0] if args else kwargs.get("args")
    prog = ""
    if isinstance(argv, (list, tuple)) and argv:
        prog = os.path.basename(str(argv[0]))
    if prog in PROBES:
        _mark(prog, [str(a) for a in list(argv)[1:]])
        if MODE != "passthrough":
            rc, out = _answer(prog, [str(a) for a in list(argv)[1:]])
            return _Answered(rc, out)
    return _REAL_POPEN(*args, **kwargs)


subprocess.Popen = _injected_popen
'''


def run_case(py, mode, budget):
    """Run the target case once, with the probe boundary counting execs.

    Returns dict: rc, out, wall, probes (all intercepted execs), rounds (pgrep execs
    — one per poll round of the engine case). `rounds` 0 means the fault was NOT
    fabricated, which the caller reports as the named state
    `probe_injection_ineffective`.
    """
    work = tempfile.TemporaryDirectory(prefix="t261030-05-probe-")
    try:
        env = dict(os.environ)
        shimdir = Path(work.name) / "shim"
        shimdir.mkdir()
        (shimdir / "sitecustomize.py").write_text(SHIM_SRC, encoding="utf-8")
        prior = env.get("PYTHONPATH") or ""
        env["PYTHONPATH"] = str(shimdir) + ((os.pathsep + prior) if prior else "")
        env["SANDBAR_D2B_PROBE_MODE"] = mode
        mark = Path(work.name) / "probe-marker.txt"
        env["SANDBAR_D2B_PROBE_MARK"] = str(mark)
        t0 = time.monotonic()
        try:
            # -ra: the short summary prints skip/fail reasons — with bare -q a named
            # skip degrades to a bare "1 skipped" and the reader never sees the
            # reason (gate arbitrate gen0: B4 false red on exactly this channel).
            r = subprocess.run([py, "-m", "pytest", TARGET, "-q", "-ra"],
                               cwd=str(REPO), env=env, capture_output=True,
                               text=True, timeout=budget)
            rc, out = r.returncode, (r.stdout or "") + (r.stderr or "")
        except subprocess.TimeoutExpired:
            rc, out = -99, "pytest timed out after %ss (hang guard)" % budget
        wall = time.monotonic() - t0
        lines = []
        if mark.is_file():
            try:
                lines = [ln for ln in mark.read_text(encoding="utf-8").splitlines() if ln.strip()]
            except OSError:
                lines = []
        return {"rc": rc, "out": out, "wall": wall, "probes": len(lines),
                "rounds": sum(1 for ln in lines if ln.split(" ")[0] == "pgrep")}
    finally:
        work.cleanup()


def injection_state(leg, observed):
    """True when the fault was really fabricated; a NAMED FAIL when it was not.

    An ineffective injection is a NAMED state (t261030-05): the legs must not read
    "the probes answered anyway" as a product verdict.
    """
    if observed["probes"]:
        ok(True, "%s0 probe injection exercised (%d intercepted execs, %d poll rounds)"
                % (leg, observed["probes"], observed["rounds"]))
        return True
    ok(False, "%s0 probe injection exercised — NAMED state probe_injection_ineffective: "
              "the pytest child never exec'd pgrep/lsof through the injected boundary "
              "(the probe face changed form); this leg's product checks are NOT judged "
              "this round" % leg)
    return False


def failure_message(out):
    """The failure text a reader actually sees: pytest's own `E` lines, prefix stripped.

    C3/C4 judge THIS, not the whole log. The log also echoes the test file's source
    around the failure (`pytest.fail("... within ... cwd scan ...")`), so a substring
    search over the log is vacuously green: the t261030-05 mutation proof dropped the
    cwd wording from the message and the old whole-log assertion stayed green. An
    empty return is the named state 'the message is not readable this way', never a
    silent pass.
    """
    lines = []
    for line in out.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("E") and (stripped == "E" or stripped[1] in " \t"):
            lines.append(stripped[1:].strip())
    return "\n".join(ln for ln in lines if ln)


def main():
    py = venv_python()
    if not py or not (REPO / "server/engine/tests/test_t261002_13_tmp_leaker_reclaim.py").is_file():
        print("ENV_FAIL: engine venv/pytest or the target test file is missing (py=%s)" % py,
              file=sys.stderr)
        return 2
    budget, budget_src = pytest_budget()
    print("hang guard: %ss (%s) — no verdict below is decided by a wall-clock constant"
          % (budget, budget_src))

    print("A green path (probes forwarded unchanged, boundary only counts them)")
    run_a = run_case(py, PROBE_MODE_PASSTHROUGH, budget)
    ok(run_a["rc"] == 0, "A1 pytest exit 0 (got rc=%s)" % run_a["rc"])
    ok("1 passed" in run_a["out"], "A2 exactly the single case passed")
    ok(GENERIC_MSG not in run_a["out"], "A3 green path never shows the regression message")
    if injection_state("A", run_a):
        ok(run_a["rounds"] <= MAX_GREEN_ROUNDS,
           "A4 the carrier is seen in the first poll round (%d round(s), ceiling %d) — the "
           "wait is a poll on progress, not a sleep" % (run_a["rounds"], MAX_GREEN_ROUNDS))
    print("     wall=%.1fs rounds=%d probes=%d"
          % (run_a["wall"], run_a["rounds"], run_a["probes"]))

    print("B enumeration unavailable (every probe exec answers exit 127)")
    run_b = run_case(py, PROBE_MODE_UNAVAILABLE, budget)
    ok(run_b["rc"] == 0, "B1 not a false red (got rc=%s)" % run_b["rc"])
    ok("failed" not in run_b["out"], "B2 zero failures in the run")
    if injection_state("B", run_b):
        ok("skipped" in run_b["out"], "B3 the case is skipped, not silently passed")
        ok(("pgrep" in run_b["out"]) or ("enumeration" in run_b["out"].lower()),
           "B4 the skip names the reason (pgrep/enumeration)")
    print("     wall=%.1fs tail=%r"
          % (run_b["wall"], run_b["out"].strip().splitlines()[-1:]))

    print("C cwd unresolvable (enumeration answers, only pid 1 resolves a cwd)")
    run_c = run_case(py, PROBE_MODE_CWD_UNRESOLVABLE, budget)
    out = run_c["out"]
    msg = failure_message(out)
    if injection_state("C", run_c):     # the product face is judged only on a built world
        ok(run_c["rc"] != 0,
           "C1 a genuine failure is a failure, not a pass (got rc=%s)" % run_c["rc"])
        ok("failed" in out, "C2 the run reports the failure")
        ok(bool(msg), "C2b the failure message is readable from the run output (pytest `E` lines)")
        ok(re.search(r"within\s+~?\s*\d+(\.\d+)?\s*s", msg) is not None,
           "C3 the timeout names its deadline (within Ns)")
        ok("cwd" in msg.lower(), "C4 the timeout names the cwd scan, not just 'no hit'")
        ok(GENERIC_MSG not in out, "C5 the generic carrier-is-invisible message is NOT shown")
        ok(run_c["wall"] < budget, "C6 the burn is bounded by the hang guard, not hung (%.1fs)"
           % run_c["wall"])
        ok(run_c["rounds"] >= MIN_FAULT_ROUNDS,
           "C7 the case polls until its deadline (%d rounds, floor %d) — not one sleep and a "
           "guess" % (run_c["rounds"], MIN_FAULT_ROUNDS))
    print("     wall=%.1fs rounds=%d probes=%d message=%r"
          % (run_c["wall"], run_c["rounds"], run_c["probes"], msg.splitlines()[:1]))

    print("summary: pass=%d fail=%d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
