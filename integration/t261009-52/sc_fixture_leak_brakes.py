#!/usr/bin/env python3
"""t261009-52 L3: a planted fault-injection fixture cannot outlive its run.

KI-222 (261008 + 261010 escalation): the brake scenario
`integration/t261004-20/sc_test_anchor_brakes.py` plants a one-line fixture
under server/engine/tests/ and removed it only in a finally block — SIGINT/
SIGTERM never run a finally, so an interrupted run left the file on the tree
and an add-everything settle later committed it into a ticket's lane.

Contract (grey-box; the subprocess is the registered brake scenario, the
assertions sit on the tree + exit status, never on the scenario's internals):
  C1 SIGINT mid-run: the fixture (planted the moment it appears in the
     delivered tree) is ABSENT after exit, integration/test_anchors.json is
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
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib_result import ScenarioCheck  # noqa: E402
import lib_fault_injection  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
BRAKE = REPO / "integration" / "t261004-20" / "sc_test_anchor_brakes.py"
FIXTURE = REPO / "server" / "engine" / "tests" / "test_zz_t26100420_planted_anchor_case.py"
MANIFEST = REPO / "integration" / "test_anchors.json"
NAME = "t261009-52-fixture-leak-brakes"
LEAK_BODY = 'BAD = "/home/user/Documents/sandbar/inspection.yaml"\n'  # the exact 261008 residue (KI-222, /home shape)

_ck = ScenarioCheck(detail_cap=800, flush=True)
ok, finish = _ck.ok, _ck.finish


def _wait_fixture(popen, deadline=300.0):
    """Poll until the brake scenario has planted its fixture (it first runs a
    baseline lint, so the plant lands several seconds in)."""
    end = time.time() + deadline
    while time.time() < end:
        if popen.poll() is not None:
            return False
        if FIXTURE.exists():
            return True
        time.sleep(0.2)
    return False


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
        try:
            out, _ = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
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
        r = subprocess.run([sys.executable, str(BRAKE)], cwd=str(REPO),
                           capture_output=True, text=True, timeout=1200)
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
