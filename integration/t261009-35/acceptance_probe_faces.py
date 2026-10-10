#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261009-35 acceptance probe (manual walkthrough evidence, NOT a registered
scenario): drive a REAL engine pause on a fixture-template scratch ticket —
the only journey that is alive in the current environment (dev-lane stub
journey is red environment-wide, see t260908-01 L3 same failure) — then assert
BOTH faces (ticket-list row via server/engine/client.py; ticket detail via
server/tools/ticket.py op=show, reader-side true path against the REAL
worktree) carry the same pause pair, and return to False/'' after resume.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
REPO = os.path.dirname(INTEG)
sys.path.insert(0, INTEG)
sys.path.insert(0, os.path.join(INTEG, "t260904-02"))
sys.path.insert(0, os.path.join(INTEG, "t260908-01"))
sys.path.insert(0, HERE)

import stage_docker  # noqa: E402
from lib_gate import (Fail, cleanup, port_listening, poc_python,  # noqa: E402
                      require_bench, require_stage, stage_down)
import sc_ticket_pause_gate as P  # noqa: E402
import sc_ticket_detail_pause_faces as SC  # noqa: E402  (tk_show / list_row)

FIXTURE_TEMPLATE_ID = "fixture-two-step"


def main():
    fail = Fail("t261009-35 acceptance probe: pause pair on both faces")
    bench = require_bench(fail)
    py = poc_python(bench)
    workers = []
    stage_mod, stage = None, None
    try:
        stage_mod, stage = require_stage(fail, "t26100935-probe-%d" % os.getpid(),
                                         "stage-probe-%d" % os.getpid())
        fe = int(stage["ports"]["temporal"])
        fail.check(port_listening(fe), "L0 stage temporal %d alive" % fe)
        fail.check(fe not in stage_docker.FORBIDDEN_PORTS, "L0 port guard")
        P.build_fixture(fail)

        tid = "dpf-probe-%x" % os.getpid()
        tmpl = os.environ.get("PROBE_TEMPLATE") or FIXTURE_TEMPLATE_ID
        use_fixture = tmpl == FIXTURE_TEMPLATE_ID
        w = P.start_worker(py, stage, tid, fixture_templates=use_fixture)
        workers.append(w)
        r = P.ticket_start(py, stage, tid, tmpl,
                           extra={"SANDBAR_FIXTURE_TEMPLATES": "1"} if use_fixture else None)
        if not fail.check(r.get("ok") is True, "L1 fixture scratch ticket opened"):
            fail.bail("cannot proceed", 1)
        P.wait_snap(fail, py, stage, tid,
                    lambda x: bool(x.get("stage")) and x.get("stage_state") == "running",
                    "L1 first segment running", 240)

        # A1 absence normalization: detail face reports False / '' before pause
        ok, detail = SC.tk_show(py, stage, tid)
        if fail.check(ok, "A1 show ok before pause"):
            fail.check(detail.get("paused") is False,
                       "A1 detail paused=False pre-pause (got %r)" % detail.get("paused"))
            fail.check(detail.get("paused_phase") == "",
                       "A1 detail paused_phase='' pre-pause (got %r)" % detail.get("paused_phase"))

        # A2 real engine pause -> at_gate
        p = P.signal_pause(py, stage, tid, "e2e-host", "acceptance probe pause")
        fail.check(p.get("ok") is True, "A2 pause op accepted")
        P.wait_snap(fail, py, stage, tid,
                    lambda x: x.get("paused") is True and x.get("paused_phase") == "at_gate",
                    "A2 engine at paused/at_gate", 240)

        # A3 detail face carries the pair (ticket.py _v2_query fix face)
        ok, detail = SC.tk_show(py, stage, tid)
        if fail.check(ok, "A3 show ok while paused"):
            fail.check(detail.get("paused") is True,
                       "A3 detail paused=True (got %r)" % detail.get("paused"))
            fail.check(detail.get("paused_phase") == "at_gate",
                       "A3 detail paused_phase=at_gate (got %r)" % detail.get("paused_phase"))
            fail.check(isinstance(detail.get("paused"), bool)
                       and isinstance(detail.get("paused_phase"), str),
                       "A3 types bool/str (console button derivation seam)")

        # A4 list row same values at the same instant (one source, two faces)
        row = SC.list_row(py, stage, tid)
        if fail.check(row is not None, "A4 ticket-list has row"):
            fail.check(row.get("paused") is True and row.get("paused_phase") == "at_gate",
                       "A4 row paused/at_gate matches detail (got %r/%r)"
                       % (row.get("paused"), row.get("paused_phase")))

        # A5 resume -> both faces back to False/''
        P.signal_resume(py, stage, tid, "e2e-host", "acceptance probe resume")
        P.wait_snap(fail, py, stage, tid, lambda x: x.get("paused") is False,
                    "A5 engine cleared paused", 240)
        ok, detail = SC.tk_show(py, stage, tid)
        if fail.check(ok, "A5 show ok after resume"):
            fail.check(detail.get("paused") is False and detail.get("paused_phase") == "",
                       "A5 detail back to False/'' (got %r/%r)"
                       % (detail.get("paused"), detail.get("paused_phase")))
        row = SC.list_row(py, stage, tid)
        if row is not None:
            fail.check(row.get("paused") is False,
                       "A5 row paused=False after resume (got %r)" % row.get("paused"))
    finally:
        for proc in workers:
            P.stop_worker(fail, proc, "teardown")
        if stage_mod is not None and stage is not None:
            try:
                stage_down(stage_mod, stage)
            except Exception:
                pass
        cleanup(P.G.get("tmp") or "")
    fail.finish()


if __name__ == "__main__":
    main()
