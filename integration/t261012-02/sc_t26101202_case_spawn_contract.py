#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26101202_case_spawn_contract.py — t261012-02, the runner's spawn
contract: sessions isolated, no inherited pipe, and a twice-hung entry is
skipped BY NAME (grey-box L2/L3, source-lock faces over the REAL
integration/run_scenarios.py and integration/stage_docker.py plus one
behaviour leg through the real `_run_entry`, offline seconds, zero
docker/Temporal/browser, never touches 3099/7233).

intent (user-perceivable contract; basis: ticket requirement (2) — nothing
a case spawns may outlive it and no case/helper may hold a pipe the runner
waits on; requirement (4) — CMD_TIMEOUT stays the 900s ceiling, no silent
global cut; requirement (4) tail — a twice-hung case is skipped BY NAME
with the reason on the round's face/log, never silently):
  S1. SOURCE LOCK (runner): the case spawn site in `_run_entry` carries
      start_new_session=True and routes stdout/stderr to files or
      DEVNULL — never capture_output / subprocess.PIPE. The C5 source-lock
      shape of t261006-08, applied to the case-spawn seam.
  S2. SOURCE LOCK (stage helpers): every stage_docker.py spawn that
      launches the module's own long-lived helper CLI carries
      start_new_session=True and never a PIPE stdout — a helper outliving
      its case holds at most a file, never a pipe the runner waits on.
  S3. BEHAVIOUR: an entry that already timed out earlier in the same
      round, scheduled a second time, is skipped BY NAME with the reason
      in the verdict tail (which lands on the round face/log), and the named deferral itself does not burn another case budget.
  S4. BUDGET LADDER: the stage-wait ceiling default plus its heartbeat
      grace stays strictly under CMD_TIMEOUT (a contended wait's named red
      always lands inside the case budget), and CMD_TIMEOUT stays at the
      declared 900s ceiling — a silent global cut is a red by name.

intent split: the timeout/group-reap behaviour faces (real child and
grandchild process trees) belong to t261012-02-case-timeout-reaps-group;
the engine activity reaper and shutdown roll-call stay with t261006-08;
the stage-lease named-red convergence truth tables stay with
stage_docker's own entries.

Three states: python3 absent = ENV_FAIL exit 2; S1/S3 red on the
pre-implementation tree are the expected TDD signal — green required at
the integration gate / merge. S2/S4 are green-today regression locks.
"""
import ast
import json
import signal
import subprocess
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
ROOT = os.path.dirname(INTEG)
sys.path.insert(0, INTEG)
import lib_result  # noqa: E402

NAME = "t261012-02-case-spawn-contract"
RUNNER = os.path.join(INTEG, "run_scenarios.py")
STAGE = os.path.join(INTEG, "stage_docker.py")
CMD_TIMEOUT_CEILING = 900
BUDGET_S = 3

_RESULTS = []


def emit(leg, ok, reason, evidence=""):
    _RESULTS.append(lib_result.spec_line(
        "%s:%s" % (NAME, leg),
        "pass" if ok else "fail",
        cause="self",
        reason=reason[:400],
        evidence=lib_result.evidence_one_line(evidence)[:800],
        suite=NAME))


def _func_source(path, func_name):
    """Adversarial read: pull one function's source out of a real file by
    AST — never trust a line-number guess."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == func_name:
            with open(path, encoding="utf-8") as fh:
                lines = fh.read().splitlines(keepends=True)
            return "".join(lines[node.lineno - 1:node.end_lineno])
    return None


def leg_s1():
    """AST-judged (never comment/substring matched): the spawn call inside
    `_run_entry` must carry start_new_session=True and must not route
    stdout/stderr through capture_output or subprocess.PIPE."""
    with open(RUNNER, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=RUNNER)
    spawn_calls = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == "_run_entry":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) \
                        and isinstance(sub.func, ast.Attribute) \
                        and isinstance(sub.func.value, ast.Name) \
                        and sub.func.value.id == "subprocess" \
                        and sub.func.attr in ("run", "Popen"):
                    spawn_calls.append(sub)
    if not spawn_calls:
        emit("S1", False, "no subprocess run/Popen call found inside "
              "_run_entry — the case spawn moved; name the new seam",
              RUNNER)
        return
    problems = []

    def _is_true(node):
        return isinstance(node, ast.Constant) and node.value is True

    for call in spawn_calls:
        kw = {k.arg: k.value for k in call.keywords if k.arg}
        if "start_new_session" not in kw \
                or not _is_true(kw["start_new_session"]):
            problems.append("line %d: spawn lacks start_new_session=True"
                            % call.lineno)
        if "capture_output" in kw:
            problems.append("line %d: spawn uses capture_output (a pipe)"
                            % call.lineno)
        for key in ("stdout", "stderr"):
            v = kw.get(key)
            if isinstance(v, ast.Attribute) and v.attr == "PIPE":
                problems.append("line %d: %s=subprocess.PIPE"
                                % (call.lineno, key))
    emit("S1", not problems,
         "runner case spawn must carry start_new_session=True and never "
         "a PIPE" + ("; " + "; ".join(problems) if problems else ""),
         "file=%s spawn_calls=%d" % (RUNNER, len(spawn_calls)))


def leg_s2():
    """Every long-lived stage-helper spawn (stage_docker.py's own hold/ensure
    CLI re-invoked as a daemon) must be session-isolated and pipe-free. A
    helper spawn = a subprocess.Popen inside a function that launches this
    module's own hold CLI ('hold' argv / --project) — judged by AST on the
    enclosing function, never a line-number guess."""
    with open(STAGE, encoding="utf-8") as fh:
        text = fh.read()
    tree = ast.parse(text, filename=STAGE)
    problems = []
    helper_call_sites = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        func_src = ast.get_source_segment(text, node) or ""
        if "subprocess.Popen" not in func_src:
            continue
        is_helper_fn = ('"--project"' in func_src or "'--project'" in func_src
                        or '"hold"' in func_src or "'hold'" in func_src)
        if not is_helper_fn:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                    and isinstance(sub.func.value, ast.Name) \
                    and sub.func.value.id == "subprocess" \
                    and sub.func.attr == "Popen":
                seg = ast.get_source_segment(text, sub) or ""
                helper_call_sites.append(sub.lineno)
                if "start_new_session=True" not in seg:
                    problems.append("line %d: helper spawn lacks "
                                    "start_new_session=True" % sub.lineno)
                if "PIPE" in seg:
                    problems.append("line %d: helper spawn holds a PIPE "
                                    "stdout" % sub.lineno)
    if not helper_call_sites:
        problems.append("no helper spawn site found — the recognition "
                        "pattern needs revisiting, never a silent pass")
    emit("S2", not problems,
         "stage helper spawns must be session-isolated and pipe-free"
         + ("; " + "; ".join(problems) if problems else ""),
         "file=%s helper_sites=%s" % (STAGE, helper_call_sites))


def leg_s3():
    """Second scheduling of an entry that already timed out this round is
    skipped by name, promptly, with the reason in the tail."""
    driver = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
import run_scenarios
run_scenarios.CMD_TIMEOUT = float(sys.argv[2])
name, cmd = sys.argv[3], sys.argv[4]
t0 = time.time()
first = run_scenarios._run_entry((name, "fixture", cmd))
t1 = time.time()
second = run_scenarios._run_entry((name, "fixture", cmd))
t2 = time.time()
print("DRIVER_JSON:" + json.dumps(
    {"first": list(first), "second": list(second),
     "first_wall": t1 - t0, "second_wall": t2 - t1,
     "budget": float(sys.argv[2])}, default=str), flush=True)
'''
    # the 120s is never waited out — the driver's own group kill ends the leg
    # at the injected budget (S3 asserts the skip verdict returns quickly).
    # SANCTIONED-WAIT: hung fixture for the named-deferral leg; killed at injected budget
    sleeper = ("python3 -c 'import time;time.sleep(120)'")
    with tempfile.TemporaryFile(mode="w+") as out:
        proc = subprocess.Popen(
            [sys.executable, "-c", driver, INTEG, str(BUDGET_S),
             "t261012-02-hang-twice", sleeper],
            stdout=out, stderr=subprocess.STDOUT,
            start_new_session=True, cwd=ROOT)
        try:
            proc.wait(timeout=BUDGET_S * 3 + 20)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait(timeout=10)
            emit("S3", False,
                 "hang-twice guard unjudgeable: driver exceeded the outer "
                 "cap — the first entry call itself did not converge on "
                 "the budget", "see case-timeout-reaps-group leg A")
            return
        out.seek(0)
        text = out.read()
    payload = None
    for ln in text.splitlines():
        if ln.startswith("DRIVER_JSON:"):
            payload = json.loads(ln[len("DRIVER_JSON:"):])
    if payload is None:
        emit("S3", False, "no driver payload — driver died before judging",
             text[-300:])
        return
    first, second = payload["first"], payload["second"]
    second_wall = payload["second_wall"]
    if first[1] != -9:
        emit("S3", False,
             "fixture entry did not time out on first scheduling (%r) — "
             "precondition broken" % first[1], first[2][:200])
        return
    ok = (second[1] != -9 and second_wall < payload["budget"]
          and second[0] == "t261012-02-hang-twice"
          and ("hung-twice" in (second[2] or "")
               or "already timed out" in (second[2] or ""))
          and bool((second[2] or "").strip()))
    emit("S3", ok,
         "second scheduling of a hung entry must be a named skip "
         "(entry name + reason in the tail) and must not burn another "
         "budget",
         "second_rc=%s second_wall=%.1fs budget=%s tail=%r"
         % (second[1], second_wall, payload["budget"], second[2][:200]))


def leg_s4():
    """CMD_TIMEOUT stays the ceiling; the stage-wait ladder stays under it."""
    sys.path.insert(0, INTEG)
    try:
        import run_scenarios
        import stage_docker
    except Exception as ex:  # noqa: BLE001
        print("ENV_FAIL: integration modules unimportable: %r" % (ex,))
        return "env"
    ceiling = run_scenarios.CMD_TIMEOUT
    ceiling_default = getattr(run_scenarios, "CMD_TIMEOUT", None)
    wait_ceiling = getattr(stage_docker, "DEFAULT_WORKING_PEER_CEILING_S",
                           None)
    problems = []
    if ceiling != CMD_TIMEOUT_CEILING:
        problems.append("CMD_TIMEOUT is %r, declared ceiling is %d — a "
                        "global cut must never land silently"
                        % (ceiling, CMD_TIMEOUT_CEILING))
    if wait_ceiling is None:
        problems.append("stage_docker.DEFAULT_WORKING_PEER_CEILING_S "
                        "absent — budget-ladder guard unjudgeable")
    elif not wait_ceiling + 60 < ceiling:
        # 60s: generous grace over the 20s heartbeat window; the contended
        # wait's named red must land inside the case budget with margin.
        problems.append("wait ceiling %s + grace is not under CMD_TIMEOUT "
                        "%s" % (wait_ceiling, ceiling))
    emit("S4", not problems,
         "budget ladder: stage-wait ceiling + grace < CMD_TIMEOUT, and "
         "CMD_TIMEOUT stays the declared 900s"
         + ("; " + "; ".join(problems) if problems else ""),
         "CMD_TIMEOUT=%r wait_ceiling=%r" % (ceiling_default, wait_ceiling))
    return "ok"


def main():
    leg_s1()
    leg_s2()
    leg_s3()
    if leg_s4() == "env":
        return 2
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
