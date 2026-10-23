#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26101202_case_timeout_reaps_group.py — t261012-02, a hung case must
not eat the round: the per-case budget is REAL and a case leaves zero live
descendants (grey-box L3, the REAL integration/run_scenarios.py `_run_entry`
driven in an isolated driver subprocess with an injected small budget, real
child/grandchild process trees, offline seconds, zero docker/Temporal/
browser, never touches 3099/7233).

The incident (ticket body, measured round round-20261011T183337Z-50912):
one case hung 10+ minutes with 0.87s CPU, blocked in select/poll on a
subprocess pipe whose write end a live grandchild held while the direct
/bin/sh child was already defunct. CPython's subprocess.run() re-calls
communicate() WITH NO TIMEOUT after killing the direct child, so the 900s
per-case budget never fires; the round's only exit is the outer runner cap
(~1 hour of machine time reading as "the suite is just slow").

intent (user-perceivable contract; three basis sources exhausted — ticket
user_request + requirements (1)(2)(4); no unclosed KI row names this face
(KI-210's reaper contract is the ENGINE activity face, t261006-08 — a
different carrier, deliberately not re-asserted here); the component
promise is the suite runner's own: one case's timeout red lands within the
case budget plus a small margin, always):
  A. THE measured defect: a case whose child forks a pipe-holding
     grandchild and exits is timed out by the runner WITHIN the injected
     budget + a small margin, judged as a named timeout red, and the WHOLE
     process group (child AND grandchild) is dead when the entry returns.
     Pre-fix this leg reds with the named "budget did not fire" verdict —
     the TDD signal.
  B. Zero live descendants on a NORMAL exit: a case that backgrounds a
     sleeper and ends 0 leaves no live descendant behind.
  C. Zero live descendants on a RED exit: same, case ends nonzero.
  D. Diagnostics do not regress: the timeout verdict's tail still carries
     the case's pre-timeout stdout (the file-redirect evidence), and the
     evidence names the timeout (never a bare silent loss).

self-discipline (this scenario must never itself hang): every driver run
goes through a child python with start_new_session=True, stdout to a FILE
(never PIPE), and a HARD outer deadline (injected budget + outer margin);
on expiry the driver's whole group is SIGKILLed and the leg FAILS by name
— the harness never waits on an inherited pipe, which is the very defect
under repair.

intent split: the runner's spawn-site source lock (start_new_session, no
PIPE) and the hang-twice named-deferral face belong to
t261012-02-case-spawn-contract (sibling entry); the engine activity
reaper/shutdown roll-call belongs to t261006-08; the stage-lease named-red
convergence stays with stage_docker's own entries.

Three states: python3 absent = ENV_FAIL exit 2; legs A-C red on the
pre-implementation tree are the expected TDD signal — green required at
the integration gate / merge.
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
ROOT = os.path.dirname(INTEG)
sys.path.insert(0, INTEG)
import lib_result  # noqa: E402

NAME = "t261012-02-case-timeout-reaps-group"
BUDGET_S = 3          # injected per-case budget (CMD_TIMEOUT), seconds
OUTER_MARGIN_S = 12   # hard outer cap on the driver child = BUDGET + this
SLEEPER_S = 120       # fixture grandchild lifetime (never reached)

_RESULTS = []


def emit(leg, ok, reason, evidence=""):
    _RESULTS.append(lib_result.spec_line(
        "%s:%s" % (NAME, leg),
        "pass" if ok else "fail",
        cause="self",
        reason=reason[:400],
        evidence=lib_result.evidence_one_line(evidence)[:800],
        suite=NAME))


def _driver_source():
    """Child driver: import the REAL runner module, inject the small
    budget, run ONE entry through _run_entry, print the result tuple as
    JSON. Run inside its own process so a pre-fix hang cannot take the
    scenario down."""
    return r'''
import json, os, sys
sys.path.insert(0, sys.argv[1])
import run_scenarios
run_scenarios.CMD_TIMEOUT = float(sys.argv[3])
name, cmd = sys.argv[4], sys.argv[5]
res = run_scenarios._run_entry((name, "fixture", cmd))
print("DRIVER_JSON:" + json.dumps(list(res), default=str), flush=True)
'''


def drive_entry(tag, case_cmd):
    """Run one _run_entry call in an isolated child with a hard outer
    deadline. Returns (driver_rc, result_tuple_or_None, wall_s, killed)."""
    with tempfile.TemporaryFile(mode="w+") as out:
        t0 = time.time()
        proc = subprocess.Popen(
            [sys.executable, "-c", _driver_source(), INTEG,
             "unused", str(BUDGET_S), "%s-entry" % tag, case_cmd],
            stdout=out, stderr=subprocess.STDOUT,
            start_new_session=True, cwd=ROOT)
        try:
            proc.wait(timeout=BUDGET_S + OUTER_MARGIN_S)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            proc.wait(timeout=10)
            out.seek(0)
            return proc.returncode, None, time.time() - t0, True
        wall = time.time() - t0
        out.seek(0)
        text = out.read()
    payload = None
    for ln in text.splitlines():
        if ln.startswith("DRIVER_JSON:"):
            payload = json.loads(ln[len("DRIVER_JSON:"):])
    return proc.returncode, payload, wall, False


def pid_alive(pid_path):
    """Reader-side probe: the fixture recorded its pids here; ESRCH = dead."""
    try:
        with open(pid_path) as fh:
            pids = [int(x) for x in fh.read().split() if x.strip()]
    except OSError:
        return None  # fixture never wrote: treat as inconclusive-dead
    alive = []
    for pid in pids:
        try:
            os.kill(pid, 0)
            alive.append(pid)
        except (ProcessLookupError, OverflowError):
            pass
        except PermissionError:
            alive.append(pid)  # exists but not ours = alive
    return alive


def _case_spawn_sleeper(pidfile, marker="", front_sleep=0):
    """A /bin/sh case that forks a pipe-holding grandchild (the incident
    shape): the direct child echoes a marker (pre-timeout stdout evidence),
    forks the grandchild (inherits the case's stdout write end), records
    its pid, then — with front_sleep > 0 — STAYS ALIVE past the budget, so
    the old no-timeout communicate() had to block on the grandchild's pipe
    forever. This is the round-20261011 shape, not merely an orphan."""
    py = (
        "import subprocess,sys;"
        "g=subprocess.Popen([sys.executable,'-c',"
        "'import time;time.sleep(%d)']);"
        "open(%r,'a').write(str(g.pid)+'\\n')" % (SLEEPER_S, pidfile))
    tail = ("sleep %d;" % front_sleep) if front_sleep else ""
    return "echo %s; %s; %s" % (marker, "python3 -c %r" % py, tail)


def main():
    if not sys.executable:
        print("ENV_FAIL: python3 unavailable")
        return 2
    tmp = tempfile.mkdtemp(prefix="t26101202-")

    # ---- A. the measured defect: budget fires on a pipe-hanging tree ----
    pida = os.path.join(tmp, "pids_a")
    cmd_a = _case_spawn_sleeper(pida, "BEFORE_HANG", front_sleep=SLEEPER_S)
    rc, payload, wall, killed = drive_entry("timeout", cmd_a)
    if killed:
        emit("A", False,
             "per-case budget did not fire: driver killed at outer cap "
             "(%.1fs) while the entry was still running — the per-case "
             "budget is still decorative" % wall,
             "cmd=%s" % cmd_a)
    else:
        ok_rc = payload is not None and payload[1] == -9
        ok_wall = wall < BUDGET_S + OUTER_MARGIN_S
        alive = pid_alive(pida)
        emit("A", ok_rc and ok_wall and not alive,
             "timeout red must land within budget+margin and the whole "
             "group must be dead"
             + ("" if ok_rc else "; entry did not judge rc=-9 timeout")
             + ("" if ok_wall else "; wall %.1fs exceeded budget+margin"
                % wall)
             + ("; alive descendants: %s" % alive if alive else ""),
             "wall=%.1fs budget=%ds rc=%s tail=%r"
             % (wall, BUDGET_S,
                payload[1] if payload else None,
                (payload[2] if payload else "")[:200]))
        # D. diagnostics not regressed: named timeout cause in the tail and
        # the case's pre-timeout stdout kept in the evidence field (the
        # 6-tuple's out; tail is the human line, out is the evidence face).
        if payload is not None:
            tail = payload[2] or ""
            out = payload[5] if len(payload) > 5 else tail
            emit("D", ("timeout" in tail or "超时" in tail)
                 and "BEFORE_HANG" in out,
                 "timeout evidence must name the cause and keep the "
                 "case's pre-timeout stdout",
                 "tail=%r out_has_marker=%s"
                 % (tail[:300], "BEFORE_HANG" in out))
        else:
            emit("D", False, "no verdict returned — nothing to read",
                 "driver rc=%s" % rc)

    # ---- B/C. zero live descendants on normal and red exits ----
    for leg, tail_cmd, want_rc in (("B", "true", 0), ("C", "exit 7", 7)):
        pidf = os.path.join(tmp, "pids_%s" % leg)
        cmd = _case_spawn_sleeper(pidf, "BG_%s" % leg) + " " + tail_cmd
        rc, payload, wall, killed = drive_entry("normal-%s" % leg, cmd)
        if killed:
            emit(leg, False,
                 "ordinary case hung the driver at the outer cap (%.1fs)"
                 % wall, "cmd=%s" % cmd)
            continue
        alive = pid_alive(pidf)
        ok = (payload is not None and payload[1] == want_rc and not alive)
        emit(leg, ok,
             "case ending %s must leave zero live descendants"
             % ("normally" if want_rc == 0 else "red")
             + ("" if payload and payload[1] == want_rc
                else "; wrong rc: %s" % (payload[1] if payload else None))
             + ("; alive: %s" % alive if alive else ""),
             "wall=%.1fs rc=%s" % (wall,
                                   payload[1] if payload else None))

    # hygiene: judged leftovers are reaped by name before exit, so the
    # fixture never donates 120s sleepers to the machine (the verdicts
    # above were already emitted from the reader-side probes).
    import shutil
    for pf in (pida,
               os.path.join(tmp, "pids_B"), os.path.join(tmp, "pids_C")):
        try:
            for pid in open(pf).read().split():
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except (ProcessLookupError, ValueError, PermissionError):
                    pass
        except OSError:
            pass
    shutil.rmtree(tmp, ignore_errors=True)  # zero residue (L8 hygiene)
    counts = {"pass": 0, "fail": 0, "env_fail": 0, "na": 0}
    for ln in _RESULTS:
        row = json.loads(ln)
        counts[row["status"] if row["status"] != "not-checked"
               else "env_fail"] += 1
    for ln in _RESULTS:
        sys.stdout.write(ln)
    print("SUMMARY pass=%(pass)d fail=%(fail)d env_fail=%(env_fail)d "
          "na=%(na)d" % counts, flush=True)
    return 1 if counts["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
