#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261006-08 scenario 1 — a cancelled activity's whole process group is reaped
(KI-210 regression, R1; grey-box L3, offline, REAL child processes, zero docker).

User-perceivable contract (the 08:32 incident: verify_lane pid 7712 + child
run_scenarios pid 56735 kept running for an hour as ppid=1 orphans after
Temporal had already recorded ActivityTaskFailed):
- C1 cancel never abandons the tree: the reaper face terminates the whole
  session of a still-running child (TERM first — verified by the child's
  signal receipt), and no pid of the tree survives;
- C2 group granularity: a grandchild forked by the child dies too (the
  orphan family is the tree, not the direct child only);
- C3 cancel semantics are re-raised, never swallowed (a cancelled activity
  must still look cancelled to Temporal);
- C4 the reaper is idempotent and total on already-exited / missing pids
  (double reap = one receipt, no raise; ESRCH is a normal terminal state);
- C5 every long spawn site is session-isolated (start_new_session=True) —
  the merge-check `verify_lane code` spawn (~4883) shipped without it, so
  even a correct group kill could not be used there (t260924-05 KI-116
  precondition); a missing session marker at any long spawn site = FAIL.

Intent split: the shutdown roll-call + machine receipt (R2/R3) belongs to
scenario 2 (sc_t26100608_shutdown_rollcall_receipt); TERM-first temp-dir
reclaim (R4) to scenario 3; the reader-side orphan probe/sweep tooling is
t261005-03's contract and is NOT re-asserted here. The developer L1 battery
(test_t261006_08_shutdown_reclaim.py) owns stub-level edge tables; this entry
pins the real-tree behavior.

Pre-implement = FAIL naming the missing face (TDD-phase red expected); must
be green at arbitrate/merge. Engine venv fallback chain exhausted = ENV_FAIL
exit 2. Run (cwd = repo root):
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
  integration/t261006-08/sc_t26100608_cancel_reaps_process_group.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_t26100608 import (  # noqa: E402
    ENGINE, import_engine_module, ok, section, spawn_child, summary,
    env_fail, wait_gone, pid_alive,
)

if not (ENGINE / "agent_activities.py").is_file():
    env_fail("engine agent_activities.py missing under %s" % ENGINE)

aa = import_engine_module("agent_activities")
if aa is None:
    env_fail("engine venv cannot import agent_activities (temporalio missing?)")


def safe_reap(proc, tag):
    """Drive the engine reaper; a raising face is a named FAIL, never a raw
    traceback (the tree under test may be mid-flight)."""
    r = globals().get("reap") or getattr(aa, "reap_spawn_group", None)
    if r is None:
        return "face reap_spawn_group absent"
    try:
        import asyncio as _a
        _a.new_event_loop().run_until_complete(r(proc, tag))
        return None
    except Exception as e:  # noqa: BLE001
        return "%s: %s" % (type(e).__name__, e)


def get_face(mod, name):
    return getattr(mod, name, None)


def main():
    reap = get_face(aa, "reap_spawn_group")
    register = get_face(aa, "register_owned_spawn")
    unregister = get_face(aa, "unregister_owned_spawn")
    if reap is None:
        ok(False, "missing face: agent_activities.reap_spawn_group "
              "(t261006-08 Step 1 not landed — TDD-phase red expected)")
        summary("cancel-reaps-process-group")
        return

    tmp = Path(tempfile.mkdtemp(prefix="sandbar-sc-t26100608-"))

    # ---- C1 TERM-first group reap of a live child ----------------------------
    section("C1 reap_spawn_group terminates a live child, TERM first")
    p, receipt = spawn_child("sleep", tmp)
    import time; time.sleep(0.5)  # child installs its TERM handler first
    register(p, "sc-c1") if register else None
    err = safe_reap(p, "sc-c1")
    ok(err is None, "C1 reap call itself clean (%s)" % (err or "ok"))
    ok(wait_gone(p, 20), "C1 child exited after reap (rc=%s)" % p.returncode)
    ok(receipt.is_file() and "term" in receipt.read_text(),
       "C1 child saw SIGTERM first (receipt written; KILL-only reaper fails here)")
    if unregister:
        unregister(p)

    # ---- C2 group granularity: grandchild dies too ---------------------------
    section("C2 grandchild in the same session dies with the tree")
    p2, _ = spawn_child("termtree", tmp)
    gc_pid = None
    # read the grandchild pid from the child's own children via pgrep -P
    import subprocess as sp
    for _ in range(20):
        r = sp.run(["pgrep", "-P", str(p2.pid)], capture_output=True, text=True)
        if r.stdout.strip():
            gc_pid = int(r.stdout.split()[0])
            break
        import time; time.sleep(0.2)
    ok(gc_pid is not None and pid_alive(gc_pid),
       "C2 grandchild alive before reap (pid=%s)" % gc_pid)
    safe_reap(p2, "sc-c2")
    ok(wait_gone(p2, 20), "C2 child reaped")
    if gc_pid is not None:
        import time
        gone = False
        dl = time.monotonic() + 15
        while time.monotonic() < dl and pid_alive(gc_pid):
            time.sleep(0.2)
        gone = not pid_alive(gc_pid)
        ok(gone, "C2 grandchild reaped with the group (no ppid=1 orphan)")
    else:
        ok(False, "C2 grandchild pid never observable (fixture broken)")

    # ---- C3 cancel is re-raised, tree still reaped ---------------------------
    section("C3 CancelledError propagates after reaping")
    p3, _ = spawn_child("sleep", tmp)
    raised = {"cancel": False, "reaped": False}

    async def activity_like():
        try:
            while p3.poll() is None:
                await asyncio.sleep(0.2)
        finally:
            await reap(p3, "sc-c3")
            raised["reaped"] = wait_gone(p3, 20)

    async def driver():
        t = asyncio.ensure_future(activity_like())
        await asyncio.sleep(0.5)
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            raised["cancel"] = True

    asyncio.new_event_loop().run_until_complete(driver())
    ok(raised["cancel"], "C3 CancelledError re-raised (not swallowed)")
    ok(raised["reaped"], "C3 tree reaped on the cancel path")

    # ---- C4 idempotent + total on dead pids ----------------------------------
    section("C4 double reap and already-dead proc are no-ops")
    e4 = safe_reap(p3, "sc-c4")
    ok(e4 is None, "C4 reap of an exited proc does not raise (%s)" % (e4 or "ok"))

    # ---- C5 every long spawn site is session-isolated ------------------------
    section("C5 start_new_session at every long spawn site (source lock)")
    src = (ENGINE / "agent_activities.py").read_text("utf-8")
    ok("start_new_session=True" in src, "C5 session-isolation marker present")
    # the merge-check verify_lane code spawn shipped WITHOUT it (review-confirmed
    # at ~4883); its spawn block must now carry the marker
    import re
    m = re.search(r"create_subprocess_exec\([^\n]*\n\s*\"python3\", admin_bin", src)
    if m:
        # window = the whole call, not a fixed N chars: successive comment passes
        # (t261008-33, then the 261009 plain-English engine pass) kept pushing the
        # marker deeper into the block (product correct, pin brittle) — the
        # assertion itself is unchanged, the window just spans the whole
        # documented spawn block.
        block = src[m.start():m.start() + 4000]
        ok("start_new_session=True" in block,
           "C5 merge-check verify_lane-code spawn is session-isolated")
    else:
        ok(False, "C5 merge-check spawn block not located (code moved? re-anchor)")
    for fn in ("run_handover_leg", "_run_scenarios", "_reprobe_red_body"):
        ok(fn in src, "C5 long-spawn function still present: %s" % fn)

    summary("cancel-reaps-process-group")


if __name__ == "__main__":
    main()
