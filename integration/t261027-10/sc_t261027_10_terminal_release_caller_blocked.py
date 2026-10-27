#!/usr/bin/env python3
"""sc_t261027_10_terminal_release_caller_blocked.py — the incident journey: a
terminal ticket's slot is returned even when the ending caller CANNOT write the
concurrency ledger (t261027-10, KI-378 ①, deliverables a+c; grey-box L3, the
real client.py named cancel entry loaded in-process with ONLY the Temporal
transport seam stubbed (FakeHandle/FakeClient pattern of
t261019-31-terminal-cancel-releases-slot), real concurrency ledger over an
isolated SANDBAR_PROJECTS_DIR root, caller-side write physically blocked by
dropping the project directory to read-only, zero docker/Temporal/3099, no
production-data writes; cost: seconds).

Incident shape (host report 261027, dengzhufpv): the cancel caller ran in an
agent sandbox with no write access to ~/.sandbar — the release failed with
PermissionError on concurrency-state.json.lock, the receipt honestly said
released:false, the workflow was terminated, and nothing ever reclaimed the row.

  K1 cancelling a slot-holding ticket with the caller's write BLOCKED still
     succeeds (terminated=true) and the release receipt is HONEST:
     released=false with a NAMED reason (a write/permission failure, not a
     bare "failed"). If the sandbox cannot reproduce the block, that is a FAIL
     named could-not-reproduce — never a silent pass.
  K2 the defect face is pinned honestly: after the blocked cancel the READER
     side (read_state + the raw concurrency-state.json bytes) still lists the
     ticket — this is the incident, not a pass condition.
  K3 the engine-side reclaim WITHOUT any caller write returns the slot: after
     the engine arm runs (the probe says the workflow is gone), the reader face
     AND the raw state-file bytes no longer list the ticket, the FIFO waiter is
     promoted, and an acquire by a NEW ticket succeeds IMMEDIATELY —
     deliverable (c)'s reader-side proof. The engine arm must run with the
     caller's write STILL blocked: the reclaim does not depend on the caller.
  K4 the reclaim verdict is fail-closed: a holder the probe cannot judge keeps
     its slot even in this blocked-caller world (no jackpot from a dead probe).

Intent split: the caller-side release when the caller CAN write belongs to
t261019-31-terminal-cancel-releases-slot (C1-C4, not re-asserted); the sweep
truth table (drop/keep/unknown/corrupt/bounds) belongs to this ticket's
sibling sc_t261027_10_dead_holder_sweep_reclaims — this scenario owns the
BLOCKED-CALLER journey end to end; the workflow terminal-notice wiring (which
signal sets which flag, which activity the worker runs) is developer L1
(UT-shell), because a real workflow run is out of this offline scenario's
reach — what is pinned here is the user-perceivable contract the ticket
demands: blocked caller write, terminal ending, slot still returned, next
acquire immediate. The engine sweep arm landed in the same ticket, so K1-K4
run green as the gate/merge regression pin (K1/K2 alone passing = the
incident back). client.py/concurrency unimportable (no temporalio SDK) =
ENV_FAIL exit 2.

Run: python3 integration/t261027-10/sc_t261027_10_terminal_release_caller_blocked.py (cwd=repo root).
"""
import atexit
import asyncio
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "server" / "engine"))

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def section(t):
    print("\n%s" % t)


try:
    import concurrency as cc
except Exception as e:  # noqa: BLE001
    print("ENV_FAIL: server/engine/concurrency.py unimportable: %s: %s"
          % (type(e).__name__, e))
    sys.exit(2)

try:
    import client
except Exception as e:  # noqa: BLE001
    print("ENV_FAIL: server/engine/client.py unimportable (temporalio SDK "
          "present?): %s: %s" % (type(e).__name__, e))
    sys.exit(2)

KEY = "sandbar"
LIMIT = 4
STATE_FILE = "concurrency-state.json"


class FakeSearchAttrs:
    def __init__(self, project=""):
        self._project = project

    def get(self, key):
        return self._project


class FakeDesc:
    def __init__(self, status="RUNNING", project=""):
        from types import SimpleNamespace
        self.status = SimpleNamespace(name=status)
        self.typed_search_attributes = FakeSearchAttrs(project)


class FakeHandle:
    def __init__(self, desc):
        self._desc = desc
        self.terminated = []

    async def describe(self):
        return self._desc

    async def signal(self, name, payload):
        return None

    async def terminate(self, reason=""):
        self.terminated.append(reason)


class FakeClient:
    def __init__(self, handle):
        self._handle = handle

    def get_workflow_handle(self, tid):
        return self._handle


class DeadQuery:
    """The probe seam stubbed (contract: (kind, note) tuple, "" = alive,
    "not_found" = Temporal says gone): both t-dead-* workflows are gone (the
    incident's Terminated rows), the rest are alive."""

    async def __call__(self, tid):
        if tid in ("t-dead-a", "t-dead-b"):
            return ("not_found", "")
        return ("", "")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


_SNAP = {"meta": {"project": KEY}, "workflow_class": "DevLaneWorkflow",
         "template_id": "dev-lane", "refused": [], "authorizations": []}


def _stub_snapshot_seam():
    client._query_snapshot_with_retry = (
        lambda handle, timeout=0: asyncio.sleep(0, result=_SNAP))


def holders_of(face):
    return sorted(h.get("ticket") for h in face.get("holders") or [])


def raw_holders(root):
    p = root / KEY / STATE_FILE
    doc = json.loads(p.read_text(encoding="utf-8"))
    return sorted(h.get("ticket") for h in doc.get("holders") or [])


def _block_write(proj_dir):
    os.chmod(proj_dir, stat.S_IRUSR | stat.S_IXUSR)  # r-x: no write


def _allow_write(proj_dir):
    os.chmod(proj_dir, stat.S_IRWXU)


def main():
    tmp = tempfile.mkdtemp(prefix="sc-t261027-10-blocked-")
    atexit.register(shutil.rmtree, tmp, True)
    root = Path(tmp) / "projects"
    proj = root / KEY
    proj.mkdir(parents=True)
    os.environ["SANDBAR_PROJECTS_DIR"] = str(root)
    (proj / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": LIMIT}),
        encoding="utf-8")
    cc.acquire(KEY, "t-dead-a")   # cancelled in K1, caller write blocked
    cc.acquire(KEY, "t-dead-b")   # a second corpse (the incident had several)
    cc.acquire(KEY, "t-other")    # alive
    cc.acquire(KEY, "t-filler")   # alive: the cap is exactly full
    cc.acquire(KEY, "t-waiter")   # queued behind limit=4 holders
    face = cc.read_state(KEY)
    ok([e.get("ticket") for e in face.get("queue") or []] == ["t-waiter"],
       "bench ready: two dead + two alive holders fill the cap, t-waiter queued")

    # the second corpse's cancel happened "a week ago" (the incident shape) —
    # only its dead holder row remains; no caller write is in play for it

    # ---------- K1 blocked-caller cancel: honest receipt, cancel fine ---------
    section("K1 caller cannot write the ledger: cancel succeeds, receipt honest")
    h = FakeHandle(FakeDesc("RUNNING", project=KEY))
    client._connect = lambda: asyncio.sleep(0, result=FakeClient(h))
    os.environ[getattr(__import__("shared"), "CALLER_PROJECT_ENV")] = KEY
    _stub_snapshot_seam()
    _block_write(proj)
    try:
        out = _run(client.cmd_ticket_cancel(
            {"ticket_id": "t-dead-a", "who": "integration",
             "reason": "blocked-caller incident journey"}))
    finally:
        _allow_write(proj)  # the caller's sandbox dies here; the engine lives on
    res = out.get("result") if isinstance(out, dict) else None
    ok(isinstance(out, dict) and out.get("ok") is True,
       "cancel succeeds despite the blocked ledger write")
    ok(bool(res) and res.get("terminated") is True, "receipt says terminated=true")
    rel = (res or {}).get("slot_released") or {}
    if rel.get("released") is False and rel.get("reason"):
        ok(True, "release receipt is honest: released=false, reason=%r"
           % rel.get("reason"))
        ok(any(w in str(rel.get("reason")).lower()
               for w in ("permission", "denied", "read-only", "write", "errno")),
           "the named reason points at the WRITE failure, not a bare 'failed'")
    else:
        ok(False, "could-not-reproduce: caller release did NOT fail behind the "
                  "read-only project dir (rel=%r) — the block did not bite"
           % (rel,))

    # ---------- K2 the leak exists (the incident face, honestly pinned) -------
    section("K2 after the blocked cancel the slot is still held — the incident")
    ok("t-dead-a" in holders_of(cc.read_state(KEY))
       and "t-dead-b" in holders_of(cc.read_state(KEY)),
       "reader face still lists both dead tickets (KI-378 ① reproduced)")
    ok("t-dead-a" in raw_holders(root) and "t-dead-b" in raw_holders(root),
       "raw state-file bytes still list both dead tickets")

    # ---------- K3 engine reclaim WITHOUT the caller: slot returned ----------
    # The engine arm runs where the WORKER runs — a process with write access
    # to the projects root. The deliverable contract is that the reclaim does
    # not depend on the ENDING CALLER's write access (K1 proved that access
    # was absent); the sweep here runs with write access, the way worker.py
    # wires it, and must return the slot the blocked caller could not.
    section("K3 engine-side reclaim (worker's write, not the caller's): slot returned")
    try:
        sweep = getattr(cc, "sweep", None)
        if not callable(sweep):
            ok(False, "engine reclaim entry missing on concurrency.py "
                      "(pre-implement red)")
        else:
            rcpt = _run(sweep(KEY, DeadQuery()))
            ok(isinstance(rcpt, dict)
               and sorted(rcpt.get("dropped") or []) == ["t-dead-a", "t-dead-b"],
               "engine arm drops BOTH dead holders and names them")
    except Exception as e:  # noqa: BLE001
        ok(False, "engine reclaim raised: %s: %s" % (type(e).__name__, e))
    face = cc.read_state(KEY)
    ok("t-dead-a" not in holders_of(face)
       and "t-dead-b" not in holders_of(face),
       "READER face no longer lists the dead tickets after the engine arm")
    ok("t-dead-a" not in raw_holders(root)
       and "t-dead-b" not in raw_holders(root),
       "raw state-file bytes no longer list the dead tickets (deliverable c)")
    ok("t-other" in holders_of(face) and "t-filler" in holders_of(face),
       "the live holders keep their slots (fail-closed on the keep side)")
    ok([e.get("ticket") for e in face.get("queue") or []] == [],
       "FIFO waiter promoted into the freed slot, queue drained")
    r = cc.acquire(KEY, "t-newcomer")
    ok(bool(r) and r.get("granted") is True and r.get("already_holding") is False,
       "a NEW ticket's acquire succeeds IMMEDIATELY (deliverable c): %r"
       % {k: r.get(k) for k in ("granted", "already_holding", "position")})

    # ---------- K4 fail-closed: an unjudgeable holder is never a jackpot ------
    section("K4 probe cannot judge a holder: the slot stays held, failure named")
    cc.release(KEY, "t-other", cc.CAUSE_TERMINATED)  # make room
    cc.acquire(KEY, "t-blind")  # a holder the probe will fail to judge

    class BlindQuery:
        async def __call__(self, tid):
            raise RuntimeError("probe transport down")

    sweep = getattr(cc, "sweep", None)
    if callable(sweep):
        rcpt2 = _run(sweep(KEY, BlindQuery()))
        face = cc.read_state(KEY)
        ok("t-blind" in holders_of(face),
           "unjudgeable holder keeps its slot (fail-closed on unknown)")
        perr = ((rcpt2 or {}).get("probe_errors") or {}).get("t-blind")
        ok(isinstance(perr, str) and perr,
           "probe_errors names t-blind: %r" % (perr,))

    print("\nPASS=%d FAIL=%d" % (PASS, FAIL))
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
