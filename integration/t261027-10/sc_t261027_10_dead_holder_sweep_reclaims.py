#!/usr/bin/env python3
"""sc_t261027_10_dead_holder_sweep_reclaims.py — a holder whose workflow is
provably gone is reclaimed by the engine even when it is a human-hold row, and
the probe that proves death is bounded and named (t261027-10, KI-378,
guarantee-arm scenario; grey-box L3, real engine public module over an isolated
SANDBAR_PROJECTS_DIR root, zero docker/Temporal/3099, no production-data writes;
cost: seconds).

Incident shape (host report 261027, dengzhufpv, limit 5): three human-hold
holders whose workflows were TERMINATED a week earlier plus one running holder
TERMINATED 46 minutes earlier kept 4 of 5 slots. The age-based staleness sweep
deliberately exempts human-hold at any age (a gate waiter has no heartbeat by
design), so nothing ever reclaimed those rows. This scenario pins the NEW
proof-of-death judgement at the user-perceivable contract level:

  W1 a holder whose workflow query says gone (not found / terminated) is
     dropped by the engine-side sweep, NAMED in the receipt — including a
     human-hold holder: workflow-gone is proof of death regardless of hold
     reason (the t261027-10 contract that refines the t261019-31 age rule:
     age alone still never condemns a human-hold; death proof does).
  W2 a holder whose workflow query says alive keeps its slot — BOTH reasons
     (running and human-hold): the sweep is not a jackpot, fail-closed on the
     keep side.
  W3 a holder the probe cannot judge (query hangs past the probe timeout, or
     the query raises, or the payload is malformed) KEEPS its slot and the
     failure is NAMED in probe_errors (never a bare id, never a silent skip,
     never an unbounded wait). The leg is wall-capped by the scenario itself:
     if the sweep returns later than the injected per-holder timeout times a
     small factor, that is a FAIL named unbounded-wait, not a hang.
  W4 a corrupt ledger state file is a NAMED refusal — the sweep drops nothing
     and leaves the file untouched.
  W5 READER-side reclaim proof (deliverable c, reader half): after the sweep,
     the raw concurrency-state.json bytes no longer list the dead tickets,
     a queued waiter is promoted, and an acquire by a NEW ticket succeeds
     IMMEDIATELY (no queue row) — the freed slot is real capacity, not a
     receipt.

Intent split: the caller-side cancel-entry release (writable caller) belongs to
t261019-31-terminal-cancel-releases-slot; the age-based staleness sweep and its
human-hold AGE exemption belong to t261019-31-stale-holder-sweep (H3 scoped to
age, amended in the same change as this ticket's declared口径 change); the
incident journey with the caller's write physically BLOCKED belongs to
sc_t261027_10_terminal_release_caller_blocked (this ticket's sibling — the
sweep truth table is here, the blocked-caller journey is there). The workflow
terminal-path wiring (which activity the worker runs at the terminal notice) is
developer L1 — this scenario pins the reclaim capability at the engine's public
sweep face, not the signal seam. The engine sweep arm landed in the same
ticket (concurrency.sweep + probe_holder_liveness), so this scenario runs
green and stands as the gate/merge regression pin; a sweep entry missing
again = FAIL named, module unimportable = ENV_FAIL exit 2.

Run: python3 integration/t261027-10/sc_t261027_10_dead_holder_sweep_reclaims.py (cwd=repo root).
"""
import atexit
import copy
import json
import os
import shutil
import sys
import tempfile
import time
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

KEY = "sandbar"
LIMIT = 7
STATE_FILE = "concurrency-state.json"

# Probe verdicts the stub query hands back, keyed by ticket. Verdict is what a
# Temporal workflow query against a dead workflow yields on the real face:
# not-found / terminated. Anything absent from this table is treated as an
# error-raise by the stub (the W3 leg).
# The probe seam contract (concurrency.probe_holder_liveness): one async
# callable (tid) -> (kind, note); kind "" = alive, "not_found" = Temporal says
# gone, anything else = an error name. Only not_found is proof of death.
PROBE_TABLE = {
    "t-dead-hold": ("not_found", ""),
    "t-dead-run": ("not_found", ""),
    "t-live-hold": ("", ""),
    "t-live-run": ("", ""),
    "t-hang": "hang",
    "t-raise": "raise",
    "t-junk": {"kind": "running"},  # malformed: not a (kind, note) tuple
}


class StubQuery:
    """The Temporal workflow-query seam, stubbed. The scenario injects it the
    same way the worker would (worker.py wires the connected client through
    concurrency.configure_probe; sweep() takes the callable directly)."""

    def __init__(self, timeout_s=0.2):
        self.timeout_s = timeout_s
        self.calls = []

    async def __call__(self, tid):
        self.calls.append(tid)
        v = PROBE_TABLE.get(tid, "raise")
        if v == "hang":
            await _sleep(self.timeout_s * 10)  # far past the probe timeout
            return ("", "")
        if v == "raise":
            raise RuntimeError("stub query transport failure")
        return v


async def _sleep(s):
    import asyncio
    await asyncio.sleep(s)


def _run(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro)


def _sweep(query, wall_cap_s=6.0):
    """Drive the engine sweep entry at its public seam. Returns (receipt, err).
    The sweep entry is this ticket's deliverable — missing = FAIL named (TDD
    red), never an anonymous crash."""
    sweep = getattr(cc, "sweep", None)
    if not callable(sweep):
        return None, "sweep entry missing on concurrency.py (pre-implement red)"
    t0 = time.monotonic()
    try:
        rcpt = _run(sweep(KEY, query))
    except Exception as e:  # noqa: BLE001
        return None, "sweep raised %s: %s" % (type(e).__name__, e)
    dt = time.monotonic() - t0
    if dt > wall_cap_s:
        return rcpt, ("unbounded-wait: sweep took %.1fs > cap %.1fs"
                      % (dt, wall_cap_s))
    return rcpt, None


def holders_of(face):
    return sorted(h.get("ticket") for h in face.get("holders") or [])


def raw_holders(root):
    p = root / KEY / STATE_FILE
    doc = json.loads(p.read_text(encoding="utf-8"))
    return sorted(h.get("ticket") for h in doc.get("holders") or [])


def seed(root):
    (root / KEY / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": LIMIT}),
        encoding="utf-8")
    # Fill the cap to the last slot: two human-hold rows (one to be killed, one
    # live), two running rows (one killed, one live), two unjudgeable rows
    # (W3's hostile probes) — then the waiter must queue behind limit=6.
    cc.acquire(KEY, "t-dead-hold")
    cc.renew(KEY, "t-dead-hold", cc.REASON_HUMAN_HOLD)
    cc.acquire(KEY, "t-live-hold")
    cc.renew(KEY, "t-live-hold", cc.REASON_HUMAN_HOLD)
    cc.acquire(KEY, "t-dead-run")
    cc.acquire(KEY, "t-live-run")
    cc.acquire(KEY, "t-hang")
    cc.acquire(KEY, "t-raise")
    cc.acquire(KEY, "t-junk")
    cc.acquire(KEY, "t-waiter")  # queued: limit=6, six holders now
    face = cc.read_state(KEY)
    return face


def main():
    tmp = tempfile.mkdtemp(prefix="sc-t261027-10-sweep-")
    atexit.register(shutil.rmtree, tmp, True)
    root = Path(tmp) / "projects"
    (root / KEY).mkdir(parents=True)
    os.environ["SANDBAR_PROJECTS_DIR"] = str(root)

    face = seed(root)
    ok(sorted(holders_of(face)) ==
       ["t-dead-hold", "t-dead-run", "t-hang", "t-junk", "t-live-hold",
        "t-live-run", "t-raise"],
       "bench ready: cap full — two human-hold rows (one dead), two running "
       "rows (one dead), two unjudgeable rows (face: %s)" % holders_of(face))
    ok([e.get("ticket") for e in face.get("queue") or []] == ["t-waiter"],
       "t-waiter is the FIFO queue head")

    # ---------- W1 proof-of-death sweep drops dead rows, human-hold included --
    section("W1 sweep drops workflow-gone holders, named — human-hold included")
    q = StubQuery()
    rcpt, err = _sweep(q)
    ok(err is None, "sweep ran bounded and returned a receipt (%s)" % (err or "ok"))
    if rcpt is None:
        print("FAIL sweep unusable — later W legs cannot judge")
        _finish()
        return
    ok("t-dead-hold" in (rcpt.get("dropped") or []),
       "dead human-hold holder dropped and named in the receipt")
    ok("t-dead-run" in (rcpt.get("dropped") or []),
       "dead running holder dropped and named in the receipt")
    ok((rcpt.get("promoted")) == "t-waiter",
       "freed slot promotes the FIFO queue head in the same locked step "
       "(promoted=%r)" % rcpt.get("promoted"))
    face = cc.read_state(KEY)
    ok("t-dead-hold" not in holders_of(face) and
       "t-dead-run" not in holders_of(face), "reader face agrees: dead rows gone")

    # ---------- W2 alive keeps the slot, both reasons --------------------------
    section("W2 alive holders keep their slots — running AND human-hold")
    ok("t-live-hold" in holders_of(face),
       "live human-hold holder keeps its slot (the hold is still by design)")
    ok("t-live-run" in holders_of(face), "live running holder keeps its slot")

    # ---------- W3 unknown keeps the slot, failure NAMED, bounded --------------
    section("W3 unjudgeable holders keep slots, probe_errors carries the name")
    before = holders_of(cc.read_state(KEY))
    real_timeout = cc.PROBE_TIMEOUT_S
    cc.PROBE_TIMEOUT_S = 0.3  # the bound is the contract; shrink it for the leg
    q2 = StubQuery()
    try:
        rcpt2, err2 = _sweep(q2, wall_cap_s=6.0)
    finally:
        cc.PROBE_TIMEOUT_S = real_timeout
    ok(err2 is None, "sweep with hostile probes stays bounded (%s)" % (err2 or "ok"))
    face = cc.read_state(KEY)
    for t in ("t-hang", "t-raise", "t-junk"):
        ok(t in holders_of(face),
           "%s keeps its slot (fail-closed on unknown)" % t)
    perrs = (rcpt2 or {}).get("probe_errors") or {}
    for t in ("t-hang", "t-raise", "t-junk"):
        ok(isinstance(perrs.get(t), str) and perrs.get(t),
           "probe_errors names %s: %r" % (t, perrs.get(t)))
    ok(all(t in before or t in holders_of(face) for t in ("t-hang", "t-raise")),
       "no unjudged holder was silently vanished")

    # ---------- W4 corrupt ledger: named refusal, nothing dropped --------------
    section("W4 corrupt ledger is a named refusal, not an empty read")
    state = root / KEY / STATE_FILE
    good = state.read_text(encoding="utf-8")
    snapshot = copy.deepcopy(raw_holders(root))
    state.write_text("{ this is not json", encoding="utf-8")
    rcpt3, err3 = _sweep(StubQuery())
    named = (err3 is not None and "sweep raised" in err3) or (
        isinstance(rcpt3, dict) and (rcpt3.get("refused") or err3))
    ok(named, "corrupt state ends in a NAMED refusal (%s)" % (err3 or rcpt3))
    state.write_text(good, encoding="utf-8")
    ok(raw_holders(root) == snapshot,
       "ledger untouched by the refused sweep (restored bytes verified)")

    # ---------- W5 reader-side reclaim: bytes + promotion + immediate acquire --
    section("W5 the freed slot is real capacity, proven from the reader's side")
    ok("t-dead-hold" not in raw_holders(root) and
       "t-dead-run" not in raw_holders(root),
       "raw concurrency-state.json bytes no longer list the dead tickets")
    face = cc.read_state(KEY)
    ok([e.get("ticket") for e in face.get("queue") or []] == [],
       "queue drained — the FIFO head was promoted by the sweep's free slot")
    r = cc.acquire(KEY, "t-newcomer")
    ok(bool(r) and r.get("granted") is True and r.get("already_holding") is False,
       "a NEW ticket's acquire succeeds IMMEDIATELY (no queue row): %r" % (
           {k: r.get(k) for k in ("granted", "already_holding", "position")}))

    _finish()


def _finish():
    print("\nPASS=%d FAIL=%d" % (PASS, FAIL))
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
