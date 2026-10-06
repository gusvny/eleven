#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261006-08 scenario 3 — TERM-first reclaim keeps the temp/log lifecycle
bound to the activity's terminal path (KI-210 + R4; grey-box L3, offline, REAL
child processes, zero docker).

User-perceivable contract (incident face: the failed activity left a 49 MB
baseline copy in TMPDIR; the ticket body measures the family at 3468
sandbar-* entries / ~415 MB, largest a 151 MB orphan log — the newly-created
subset is what this ticket owns):
- T1 the engine's terminal-path reclamation signals TERM before KILL, so a
  suite that installs a signal hook (run_scenarios' lib_tmp_reclaim
  face) gets to reclaim its own temp fixtures before dying: after the reap,
  the fixture temp dir the child created is GONE and the child's TERM receipt
  is written (a KILL-only reaper leaks both);
- T2 if TERM is not answered within the bounded window the escalation still
  ends the tree (a sticky child that ignores TERM is KILLed — reclaim never
  hangs the shutdown);
- T3 the three long spawn sites' terminal paths route through the SHARED
  reaper instead of diverging bare kills (KI-009 single-point discipline):
  a bare `p.kill()` left inside a long site's timeout branch = FAIL;
- T4 non-regression: the repo-level sweeper for historical/SIGKILL residue
  (integration/tools/sweep_tmp_fixtures.py) is still in place — this ticket
  owns the newly-created subset only, the sweeper owns the rest (declared
  split; removing the sweeper = FAIL).

Intent split: reaping correctness/granularity = scenario 1; roll-call and
machine receipt = scenario 2; this entry owns the TERM-first ordering and the
temp-dir lifecycle face. Pre-implement = FAIL naming the missing face
(TDD-phase red expected); green at arbitrate/merge. Engine venv fallback chain
exhausted = ENV_FAIL exit 2. Run (cwd = repo root):
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
  integration/t261006-08/sc_t26100608_term_first_tmp_lifecycle.py
"""
from __future__ import annotations

import asyncio
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_t26100608 import (  # noqa: E402
    ENGINE, ROOT, import_engine_module, ok, section, spawn_child, summary,
    env_fail, wait_gone,
)

if not (ENGINE / "agent_activities.py").is_file():
    env_fail("engine agent_activities.py missing under %s" % ENGINE)
aa = import_engine_module("agent_activities")
if aa is None:
    env_fail("engine venv cannot import agent_activities (temporalio missing?)")


def safe_reap(proc, tag):
    """Drive the engine reaper; a raising face is a named FAIL, never a raw
    traceback (the tree under test may be mid-flight)."""
    try:
        import asyncio as _a
        _a.new_event_loop().run_until_complete(reap(proc, tag))
        return None
    except Exception as e:  # noqa: BLE001
        return "%s: %s" % (type(e).__name__, e)

reap = getattr(aa, "reap_spawn_group", None)


def main():
    if reap is None:
        ok(False, "missing face: agent_activities.reap_spawn_group "
              "(t261006-08 Step 1 not landed — TDD-phase red expected)")
        summary("term-first-tmp-lifecycle")
        return

    tmp = Path(tempfile.mkdtemp(prefix="sandbar-sc-t26100608-"))

    # ---- T1 TERM-first: suite reclaims its own temp fixtures -----------------
    section("T1 TERM-first reclaim lets the child clean its temp dir")
    fixture_dir = tmp / "baseline-copy"
    fixture_dir.mkdir()
    (fixture_dir / "big.bin").write_bytes(b"x" * 1024)
    import time
    p, receipt2 = spawn_child("tmpclean", tmp, payload=fixture_dir)
    time.sleep(0.5)  # let the child install its SIGTERM handler before reaping
    err = safe_reap(p, "sc-t1")
    ok(err is None, "T1 reap call itself clean (%s)" % (err or "ok"))
    ok(wait_gone(p, 20), "T1 child ended by the reaper")
    ok(receipt2.is_file() and "term" in receipt2.read_text(),
       "T1 child received SIGTERM (not KILL) — the R4 lever fired")
    ok(not fixture_dir.exists(),
       "T1 temp fixture dir reclaimed on the terminal path (49 MB-class leak face)")

    # ---- T2 escalation still ends a TERM-resisting tree ----------------------
    section("T2 KILL escalation bounds a TERM-resisting child")
    p2, _ = spawn_child("sticky", tmp)
    t0 = time.monotonic()
    err = safe_reap(p2, "sc-t2")
    ok(err is None, "T2 reap call itself clean (%s)" % (err or "ok"))
    wall = time.monotonic() - t0
    ok(wait_gone(p2, 30), "T2 sticky child ended (KILL escalation)")
    ok(wall < 120, "T2 bounded wall clock (%.1fs; shutdown must not hang)" % wall)

    # ---- T3 long sites route through the shared reaper (source lock) ---------
    section("T3 long spawn sites use the single-point reaper, no bare kills")
    src_txt = (ENGINE / "agent_activities.py").read_text("utf-8")
    for fn in ("run_handover_leg", "_run_scenarios", "_reprobe_red_body"):
        m = re.search(r"(?:async )?def %s\(.*?(?=\n(?:async )?def |\Z)" % fn,
                      src_txt, re.S)
        ok(m is not None, "T3 function located: %s" % fn)
        if m:
            body = m.group(0)
            bare = re.search(r"^\s*p\.kill\(\)", body, re.M)
            ok(bare is None,
               "T3 %s: no bare p.kill() in the terminal path (single-point reap)"
               % fn)
            ok("reap_spawn_group" in body or "killpg" in body,
               "T3 %s: group-granular reclaim present" % fn)

    # ---- T4 sweeper for the historical subset is still in place --------------
    section("T4 historical-subset sweeper stays in place (declared split)")
    sweeper = ROOT / "integration" / "tools" / "sweep_tmp_fixtures.py"
    ok(sweeper.is_file(),
       "T4 sweep_tmp_fixtures.py present (owns SIGKILL survivors / history)")

    summary("term-first-tmp-lifecycle")


if __name__ == "__main__":
    main()
