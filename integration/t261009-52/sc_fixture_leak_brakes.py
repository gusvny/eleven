#!/usr/bin/env python3
"""t261009-52 L3: a planted fault-injection fixture cannot outlive its run.

KI-222 (261008 + 261010 escalation): the brake scenario
`integration/t261004-20/sc_test_anchor_brakes.py` plants a one-line fixture
under server/engine/tests/ and removed it only in a finally block — SIGINT/
SIGTERM never run a finally, so an interrupted run left the file on the tree
and an add-everything settle later committed it into a ticket's lane.

Contract (grey-box; the subprocess is the registered brake scenario, the
assertions sit on the tree + exit status, never on the scenario's internals):
  C1 SIGINT mid-run: the fixture (signalled by the brake's explicit
     `PLANTED:` stdout handshake line — the parent acts on the line, it never
     polls the tree) is ABSENT after exit, integration/test_anchors.json is
     byte-identical, and the exit is non-zero — the interrupt stays visible
     (a swallowed SIGINT would turn an interrupt into a fake-green exit).
  C2 SIGTERM: the same contract.
  C3 pre-flight leak report: with the exact 261008 residue planted by hand, a
     fresh brake run NAMES the leak (fixture path + owning scenario
     t261004-20-test-anchor-brakes) instead of silently proceeding on a dirty
     tree, and the tree is clean afterwards.
  C4 zero residue after the whole lifecycle.

Offline, zero docker/Temporal/browser, never touches 3099. The brake scenario
file missing = ENV_FAIL exit 2 (environment property, named, not a rule
violation). NOTE: this script writes ONLY the fixture path it owns (C3's
residue) — never a second face of the delivered tree.
"""
import pathlib
import queue
import signal
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib_result import ScenarioCheck  # noqa: E402
import lib_fault_injection  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
BRAKE = REPO / "integration" / "t261004-20" / "sc_test_anchor_brakes.py"
FIXTURE = REPO / "server" / "engine" / "tests" / "test_zz_t26100420_planted_anchor_case.py"
MANIFEST = REPO / "integration" / "test_anchors.json"
NAME = "t261009-52-fixture-leak-brakes"
LEAK_BODY = 'BAD = "/home/xingu/Documents/sandbar/inspection.yaml"\n'  # the exact 261008 residue (KI-222, /home shape)

_ck = ScenarioCheck(detail_cap=800, flush=True)
ok, finish = _ck.ok, _ck.finish


# ---- explicit plant handshake (t261011-22 spec §5) --------------------------
# The old face polled the filesystem (`FIXTURE.exists()` every 0.2 s under a
# 300 s deadline) while the child's stdout PIPE went UNDRAINED — minutes of
# load-dependent waiting plus a latent pipe-full block on a chatty child. The
# new face is the sanctioned handshake: the brake prints one `PLANTED: <path>`
# line the moment the fixture exists on disk (write, then flush, then line —
# so a parent acting on the line can never observe a half-written file), and
# this parent acts on that line. The bound is INJECTABLE and seconds-scale,
# never the production-scale wait; expiry is a NAMED failure.
PLANT_LINE_PREFIX = "PLANTED: "
PLANT_HANDSHAKE_BOUND_S = 60


def parse_plant_line(line):
    """The repo-relative fixture path in one handshake line, or None.

    Total on None/malformed input (a chatty child's other output lines, empty
    strings, a prefix-only line); only exact-prefix lines yield a value."""
    if not line or not str(line).startswith(PLANT_LINE_PREFIX):
        return None
    value = str(line)[len(PLANT_LINE_PREFIX):].strip()
    return value or None


def _pump(pipe, sink):
    """Drain the child's stdout into a queue on a daemon thread (fixes the
    latent undrained-PIPE block); EOF enqueues the None sentinel."""
    try:
        for line in pipe:
            sink.put(line)
    finally:
        sink.put(None)


def wait_for_plant(proc, clock=time.monotonic, bound_s=PLANT_HANDSHAKE_BOUND_S):
    """Act on the brake's PLANTED: handshake line instead of polling the tree.

    Returns (relpath, None) on the handshake, or (None, reason) with a NAMED
    reason: 'bound-expired after Ns without a PLANTED: line' (the injectable
    bound FIRED — the failure names the bound, it does not sleep a production
    scale) or 'child-exited before a PLANTED: line' (EOF sentinel). Every exit
    path is terminal: the pump thread is a daemon, the queue is abandoned with
    the child process (the caller owns killing it)."""
    sink = queue.Queue()
    threading.Thread(target=_pump, args=(proc.stdout, sink), daemon=True).start()
    end = clock() + bound_s
    while True:
        remaining = end - clock()
        if remaining <= 0:
            return None, "bound-expired after %ss without a PLANTED: line" % bound_s
        try:
            line = sink.get(timeout=remaining)
        except queue.Empty:
            continue
        if line is None:
            return None, "child-exited before a PLANTED: line"
        hit = parse_plant_line(line)
        if hit:
            return hit, None


def _wait_fixture(popen, deadline=PLANT_HANDSHAKE_BOUND_S):
    """Compatibility shim over the handshake (old callers pass a Popen): the
    deadline argument is the INJECTABLE seconds-scale bound, not a poll."""
    hit, reason = wait_for_plant(popen, bound_s=deadline)
    if reason:
        print("  note: plant handshake failed: %s (child exit=%s)"
              % (reason, popen.poll()), flush=True)
    return hit is not None


def _interrupt_case(sig, label):
    if not BRAKE.exists():
        print("ENV_FAIL: brake scenario missing: %s" % BRAKE, flush=True)
        sys.exit(2)
    manifest_before = MANIFEST.read_bytes() if MANIFEST.exists() else None
    proc = subprocess.Popen([sys.executable, str(BRAKE)], cwd=str(REPO),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)
    planted = _wait_fixture(proc)
    ok(planted, "%s: brake run planted its fixture" % label,
       "fixture %s never appeared (brake exit=%s)" % (FIXTURE.name, proc.poll()))
    if planted:
        proc.send_signal(sig)
        # The pump thread keeps draining the pipe (a full pipe can never block
        # the child mid-reclaim), so a plain wait — not communicate, whose
        # second reader would race the pump — owns the bounded exit wait.
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            ok(False, "%s: interrupted brake run exits" % label,
               "scenario ignored the signal for 60s (killed)")
            return
        ok(proc.returncode != 0, "%s: interrupt stays visible (non-zero exit)" % label,
           "exit status %r after %s (a swallowed interrupt = fake-green)"
           % (proc.returncode, sig.name))
        ok(not FIXTURE.exists(), "%s: fixture reclaimed after interrupt" % label,
           "%s survived the interrupt — the KI-222 leak shape" % FIXTURE.name)
        manifest_after = MANIFEST.read_bytes() if MANIFEST.exists() else None
        ok(manifest_before == manifest_after,
           "%s: anchor manifest byte-identical" % label,
           "test_anchors.json changed by the interrupted run")


def main():
    # C1 / C2: interruption-proof reclaim
    _interrupt_case(signal.SIGINT, "C1 SIGINT mid-run")
    _interrupt_case(signal.SIGTERM, "C2 SIGTERM mid-run")

    # C3: the pre-flight leak report (SIGKILL cannot be handled, so the NEXT
    # run must name the leak and clean it). The manual residue plant rides the
    # same exclusive planting lock as the brake scenario (acceptance rework:
    # concurrent same-tree planting collides; the spawned brake run takes the
    # lock itself, so the parent must NOT hold it across the subprocess).
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    lock_fh = lib_fault_injection.acquire_planting_lock(REPO)
    FIXTURE.write_text(LEAK_BODY, encoding="utf-8")
    lock_fh.close()  # released BEFORE the subprocess: it acquires its own
    try:
        r = subprocess.run([sys.executable, str(BRAKE)], cwd=str(REPO),  # SANCTIONED-WAIT: hard kill ceiling on the child brake run (scoped lint, seconds), never slept to
                           capture_output=True, text=True, timeout=300)
        blob = r.stdout + r.stderr
        # NOTE (arbitrate 261010): the brake run's own exit code is NOT
        # asserted here. That code is the verdict arithmetic of
        # t261004-20-test-anchor-brakes (its B1/B7 baseline-delta faces), and
        # coupling THIS scenario to it measured red exactly once (the 09:49
        # --only round) when the brake scenario's internal flake surfaced as
        # our exit-code assertion. This scenario owns the leak lifecycle only:
        # the leak is NAMED and the tree is CLEAN. The brake run's own health
        # is judged by its own registry entry.
        print("  note C3: brake run exit=%d (recorded, not asserted — "
              "t261004-20's face)" % r.returncode, flush=True)
        ok("leaked" in blob and FIXTURE.name in blob,
           "C3: the leak is named (fixture path)", "output did not name the leak")
        ok("t261004-20-test-anchor-brakes" in blob,
           "C3: the leak is named (owning scenario)",
           "output did not name the owning scenario")
    finally:
        FIXTURE.unlink(missing_ok=True)

    # C4: zero residue after the whole lifecycle
    ok(not FIXTURE.exists(), "C4: zero residue after the lifecycle",
       "%s left on the tree" % FIXTURE.name)

    finish(NAME)


if __name__ == "__main__":
    main()
