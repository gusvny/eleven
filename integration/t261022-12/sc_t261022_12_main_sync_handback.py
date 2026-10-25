#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t261022_12_main_sync_handback.py — quickmanual lane main-sync conflict is
handed back to the work stage, resolved by the owning session, and the lane
completes (t261022-12, grey-box L3, docker stage temporal-only + real quickmanual
ticket + programmable stub brain + fixture repo).

intent (the user-perceivable behavior this entry owns — the measured fault:
a quickmanual ticket whose pre-gate main sync hit a conflict wedged itself,
because the shared resolution loop asked for an `implement` stage the
quickmanual template deliberately does not have):

  H1. THE HANDBACK: a quickmanual ticket parked at work whose settle+gate path
      merges a now-conflicting main does NOT wedge and does NOT dispatch any
      agent: the ticket lands back on its own working stage (`work`) awaiting
      its session, and no `implement` activity appears on the timeline or in
      the stub-brain ledger (no agent stage may be invented for a lane that
      has none).
  H2. THE REASON: the reason the session sees names the conflicting file, the
      merge that failed, and the exact way out (resolve in the worktree and
      signal work_done again).
  H3. THE RESOLUTION LOOP CLOSES: the owning session resolves the conflict
      markers in the lane worktree (without git commit) and signals work_done
      again; the lane settles the open merge and proceeds through the machine
      gate to the human merge gate, with the merged state visible on the
      public main_sync face.

Intent split (no duplication): sc_quickmanual_journey owns the healthy
session-driven journey (no conflict); developer L1 owns the workflow-level
stub matrices including the replay-gate-off path; sc_quickmanual_faces and
sc_t261022_12_handback_faces own the registration/chain/vocabulary faces; this
entry uniquely owns the real-Temporal conflict handback journey.

Assertions land only on public faces (client receipts, snapshot keys, timeline,
fixture git end state, the scenario-owned stub ledger); docker/stage/engine-venv
missing = ENV_FAIL exit 2; pre-implement red is the expected TDD signal, must be
green at arbitrate/merge; zero contact with 3099.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
REPO = os.path.dirname(INTEG)
sys.path.insert(0, INTEG)
sys.path.insert(0, os.path.join(INTEG, "t260904-02"))
sys.path.insert(0, os.path.join(INTEG, "quickmanual-lane"))

# Reuse the journey's harness single points (env, fixture, worker, waits) —
# shared helpers, not duplicated scenarios.
import sc_quickmanual_journey as J  # noqa: E402
from lib_gate import Fail, accepted, poc_python, require_bench, require_stage  # noqa: E402

TID = "qm-handback-%d" % os.getpid()
SESSION = "e2e-handback-session-01"
SESSION_ROLE = "host"
CONFLICT_FILE = "README.md"          # exists in the fixture base (a repo clone)
WRITE_SET = [J.WRITE_FILE, CONFLICT_FILE]
LANE_LINE = "lane side edit (t261022-12 handback scenario)\n"
MAIN_LINE = "main side edit (t261022-12 handback scenario)\n"
RESOLVED_LINE = "resolved line (lane + main semantics kept)\n"


def main() -> int:
    fail = Fail("t261022-12 quickmanual main-sync conflict handback e2e")
    stats = {"pass": 0}

    def check(cond, msg):
        r = fail.check(cond, msg)
        if r:
            stats["pass"] += 1
        return r

    stage_mod = None
    J.G["tmp"] = tempfile.mkdtemp(prefix="sandbar-qm-handback-")
    atexit.register(lambda: shutil.rmtree(J.G["tmp"], ignore_errors=True)
                    if not os.environ.get("SANDBAR_QMLE2E_KEEP_TMP") else None)
    J.G["gate_ledger"] = os.path.join(J.G["tmp"], "gate-ledger.jsonl")
    J.G["stub_ledger"] = os.path.join(J.G["tmp"], "stub-ledger.jsonl")
    J.G["stub"] = os.path.join(J.G["tmp"], "qm_stub.py")
    with open(J.G["stub"], "w", encoding="utf-8") as f:
        f.write(J.STUB_SRC)
    try:
        # ---------- L0 environment (missing pieces = ENV_FAIL inside require_*) ----------
        bench = require_bench(fail)
        py = poc_python(bench)
        stage_mod, stage = require_stage(fail, "qm-hb-%d" % os.getpid(),
                                         "qm-hb-%d" % os.getpid())

        # ---------- L1 fixture ----------
        J.build_fixture(fail)

        # ---------- H0: create the ticket, park at work ----------
        J.start_worker(py, stage, TID)
        _rc, br = J.git("rev-parse", "--short", "HEAD")
        base_ref = (br or "").strip()
        create = dict(template_id="quickmanual-lane", project=J.PROJECT_KEY,
                      base_ref=base_ref, caller_project=J.PROJECT_KEY,
                      write_set=WRITE_SET)
        _rc, out = J.run_poc_client(py, "ticket-start", dict(
            create, ticket_id=TID,
            title="[e2e] quickmanual main-sync conflict handback (t261022-12)",
            user_request="integration e2e: the gate's main sync must hand a "
                         "conflict back to the session, not wedge the lane",
            evidence={"kind": "l1_battery", "name": "test_quickmanual_lane.py"},
            # SANCTIONED-WAIT: bounded client call, not a state wait
        ), J.env_for(stage), timeout=300)
        good, why = accepted(out, TID)
        check(good, "H0 quickmanual ticket accepted (%s)" % why)
        snap = J.wait_snap(fail, py, stage, TID,
                           lambda x: x.get("stage") == "work"
                           and x.get("stage_state") == "awaiting",
                           "H0 ticket parks at work awaiting its session", 420)

        # ---------- H0: the session works in the lane worktree (no commit) ----------
        ws = str((((snap or {}).get("meta") or {}).get("workspace") or {}).get("path") or "")
        check(bool(ws and os.path.isdir(ws)),
              "H0 the lane worktree is on the public snapshot face (%r)" % (ws,))
        if not (ws and os.path.isdir(ws)):
            fail.finish()
            return 1
        with open(os.path.join(ws, J.WRITE_FILE), "w", encoding="utf-8") as f:
            f.write("quickmanual handback e2e: the session's repair\n")
        rf = os.path.join(ws, CONFLICT_FILE)
        with open(rf, encoding="utf-8") as f:
            readme = f.read()
        with open(rf, "w", encoding="utf-8") as f:
            f.write(LANE_LINE + readme)   # same head line -> merge conflict

        # ---------- H0: main moves on the SAME lines while the lane is parked ----------
        rf_main = os.path.join(J.G["fixture"], CONFLICT_FILE)
        with open(rf_main, encoding="utf-8") as f:
            readme_main = f.read()
        with open(rf_main, "w", encoding="utf-8") as f:
            f.write(MAIN_LINE + readme_main)
        J.git("add", CONFLICT_FILE)
        J.git("-c", "user.email=e2e@quickmanual.test", "-c",
              "user.name=quickmanual-e2e", "commit", "-m",
              "t261022-12 scenario: main moves on the conflict lines")
        _rc, mv = J.git("rev-parse", "--short", "HEAD")
        check(bool((mv or "").strip()),
              "H0 main moved on the same lines (commit %s)" % (mv or "?").strip())

        # ---------- H1: work_done -> settle -> gate main sync conflicts -> handback ----------
        r = J.cli(py, stage, "ticket", {"op": "work_done", "ticket_id": TID,
                                        "session": SESSION, "role": SESSION_ROLE})
        check(r.get("ok") is True,
              "H1 the first work_done is accepted (%s)"
              % str(r.get("error") or "")[:120])
        snap2 = J.wait_snap(fail, py, stage, TID,
                            lambda x: x.get("stage") == "work"
                            and x.get("stage_state") == "awaiting"
                            and bool(x.get("blocked_reason")),
                            "H1 the conflicted ticket lands back on work awaiting "
                            "its session (no wedge, no agent)", 420)
        if snap2 is None:
            fail.finish()
            return 1
        reason = str(snap2.get("blocked_reason") or "")
        check(CONFLICT_FILE in reason,
              "H2 the reason names the conflicting file (%r...)" % reason[:160])
        check("merge main" in reason,
              "H2 the reason names the merge that failed (%r...)" % reason[:160])
        check("work_done" in reason,
              "H2 the reason names the way out: resolve and signal work_done "
              "again (%r...)" % reason[:160])
        tl = [str(e.get("stage") or "") for e in (snap2.get("timeline") or [])]
        check("implement" not in tl,
              "H1 no implement stage on the timeline (got %r)" % tl)
        check("implement" not in J.stub_stages_of(TID),
              "H1 no implement dispatch in the stub-brain ledger (got %r)"
              % J.stub_stages_of(TID))
        check(J.stub_stages_of(TID) == [],
              "H1 the stub-brain ledger stays empty: no agent was ever spawned")

        # ---------- H3: the owning session resolves, no git commit ----------
        with open(rf, encoding="utf-8") as f:
            marked = f.read()
        check("<<<<<<<" in marked,
              "H3 the worktree really holds conflict markers before resolution")
        with open(rf, "w", encoding="utf-8") as f:
            f.write(RESOLVED_LINE + readme)   # both semantics kept, markers gone
        r = J.cli(py, stage, "ticket", {"op": "work_done", "ticket_id": TID,
                                        "session": SESSION, "role": SESSION_ROLE})
        check(r.get("ok") is True,
              "H3 the second work_done is accepted (%s)"
              % str(r.get("error") or "")[:120])

        # ---------- H3: the lane settles the open merge and reaches the human gate ----------
        snap3 = J.wait_snap(fail, py, stage, TID,
                            lambda x: x.get("stage") == "merge"
                            and x.get("stage_state") == "awaiting-human",
                            "H3 after the session's resolution the lane reaches the "
                            "human merge gate", 600)
        if snap3 is None:
            fail.finish()
            return 1
        ms = ((snap3.get("meta") or {}).get("main_sync") or {})
        # The verify tree includes moved main: the recorded main_sha is the
        # commit main moved to, and the mode is the LAST sync receipt (the
        # settle round lands "merged"; the next gate round overwrites it with
        # the up_to_date fast path - both prove the tree carried moved main).
        check(str(ms.get("mode") or "") in ("merged", "up_to_date")
              and str(ms.get("main_sha") or "").startswith((mv or "").strip()[:7]),
              "H3 the public main_sync face shows the verified tree carried moved "
              "main (want main_sha~%s, got %r)" % ((mv or "?").strip()[:7], ms))
        tl3 = [str(e.get("stage") or "") for e in (snap3.get("timeline") or [])]
        check("implement" not in tl3,
              "H3 still no implement stage on the timeline after the full journey")
        check(J.stub_stages_of(TID) == [],
              "H3 the stub-brain ledger is STILL empty for the whole journey")
        # the resolved content really landed (reader-side evidence on the git face)
        _rc, shown = J.git("show", "HEAD:%s" % CONFLICT_FILE, cwd=ws)
        check("resolved line" in (shown or ""),
              "H3 the resolved file is on the lane's committed tip")
    finally:
        try:
            J.stop_all_workers(fail, "t261022-12 handback e2e")
        except Exception:
            pass
        try:
            if stage_mod is not None:
                from lib_gate import stage_down  # noqa: E402
                stage_down(stage_mod, quiet=True)
        except Exception:
            pass
    print("t261022-12 main-sync handback e2e: %d checks passed" % stats["pass"])
    fail.finish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
