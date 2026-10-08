#!/usr/bin/env python3
"""t261008-35 — the shutdown-reclaim orphan check is LOCAL to the leg (L3).

intent: the engine test file's orphan verification must judge only the leg's
OWN processes (its own process group / its own spawn ledger), never a
machine-wide process listing — a foreign lane's `sleep 30` running elsewhere
on the machine must not be able to red-light the suite, and a genuinely
orphaned child of the leg must still be caught.

Grey-box L3, offline, REAL processes, zero docker/Temporal/browser, never
touches 3099; the machine-wide `ps` form was observed failing on this very
machine (parallel lanes + `ps: Operation not permitted`).

Subcases (each names what failed, never silent green):
  A static sweep   — the target file carries no machine-wide enumeration
                     (`ps -e`-family / unfiltered `pgrep`) anywhere; the
                     defect cannot come back unnoticed.
  B decoy lock     — with a FOREIGN `sleep 30` decoy alive in its own process
                     group (exactly the condition that red-lit the old form),
                     the whole target pytest file passes. Pre-implement this
                     is RED by design (the old machine-wide assertions see the
                     decoy); red here before implement is the TDD signal.
  C teeth          — the file contains a negative test that deliberately keeps
                     a live group and proves the local probe goes RED, and
                     that test runs green. A check that cannot fail is worse
                     than the flake it replaced.

Exit code: 0 all pass / 1 any FAIL / 2 ENV_FAIL (python, pytest or /bin/sleep
unavailable — environment, not contract).
"""
import os
import re
import signal
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TARGET = os.path.join(REPO, "server", "engine", "tests",
                      "test_t261006_08_shutdown_reclaim.py")
VENV_PY = os.path.join(REPO, "server", "engine", ".venv", "bin", "python")
PY = VENV_PY if os.path.exists(VENV_PY) else sys.executable
SLEEP = "/bin/sleep"

pass_n = fail_n = 0


def ok(cond, label, detail=""):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok   " + label)
    else:
        fail_n += 1
        print("  FAIL " + label + ((" | " + str(detail)[:400]) if detail else ""))


def env_fail(why):
    print("ENV_FAIL: " + why)
    sys.exit(2)


def run_pytest(args, timeout):
    cp = subprocess.run([PY, "-m", "pytest"] + args + [TARGET],
                        cwd=REPO, capture_output=True, text=True,
                        errors="backslashreplace", timeout=timeout)
    return cp


def main():
    if not os.path.exists(PY):
        env_fail("engine python missing: %s" % PY)
    if not os.path.exists(SLEEP):
        env_fail("decoy binary missing: %s" % SLEEP)
    if not os.path.exists(TARGET):
        print("FAIL: target test file missing: %s" % TARGET)
        sys.exit(1)

    # ---- A: static sweep — no machine-wide enumeration in the whole file ----
    src = open(TARGET, encoding="utf-8", errors="backslashreplace").read()
    hits = []
    for i, line in enumerate(src.splitlines(), 1):
        if re.search(r"\bps\s+(-\w+\s+)*-e\b", line) or re.search(r"\bps\s+aux", line) \
                or re.search(r"\bpgrep\b", line):
            hits.append("%d: %s" % (i, line.strip()))
    ok(not hits, "A no machine-wide process enumeration in target file",
       "; ".join(hits[:5]))

    # ---- decoy: a FOREIGN `sleep 30` in its own process group ----
    decoy = subprocess.Popen([SLEEP, "30"], start_new_session=True)
    try:
        time.sleep(0.2)
        decoy_alive = decoy.poll() is None
        if not decoy_alive:
            env_fail("decoy refused to start (exit %s)" % decoy.returncode)

        # ---- B: the decoy lock — whole file green with a foreign sleep 30 alive ----
        try:
            cp = run_pytest(["-q", "-p", "no:cacheprovider"], 420)
            ok(cp.returncode == 0,
               "B target pytest file green with foreign `sleep 30` alive (decoy lock)",
               "exit=%s tail=%s" % (cp.returncode,
                                    (cp.stdout or cp.stderr)[-350:]))
        except subprocess.TimeoutExpired:
            ok(False, "B target pytest file green with foreign sleep 30 alive",
               "pytest timed out after 420s")

        # ---- C: teeth — a negative test proves the local probe can go RED ----
        m = re.search(r"^def (test_\w*(orphan|teeth|probe|negative)\w*)", src, re.M)
        if not m:
            ok(False, "C negative-teeth test present in target file",
               "no test matching orphan/teeth/probe/negative found")
        else:
            try:
                cp2 = run_pytest(["-q", "-p", "no:cacheprovider",
                                  "-k", m.group(1)], 120)
                ok(cp2.returncode == 0,
                   "C negative-teeth test %s runs green (probe provably can fail)" % m.group(1),
                   "exit=%s tail=%s" % (cp2.returncode,
                                        (cp2.stdout or cp2.stderr)[-350:]))
            except subprocess.TimeoutExpired:
                ok(False, "C negative-teeth test runs green", "timed out after 120s")
    finally:
        # cleanup on every path: the decoy must not outlive this scenario
        try:
            os.killpg(decoy.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            decoy.wait(timeout=10)
        except Exception:
            pass

    print("pass=%d fail=%d" % (pass_n, fail_n))
    sys.exit(1 if fail_n else 0)


if __name__ == "__main__":
    main()
