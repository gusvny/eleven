#!/usr/bin/env python3
"""sc_t261019_31_stale_holder_sweep.py — a running holder that stopped
heartbeating is swept by the next acquire and frees its slot; a human-hold holder
is NEVER swept at any age (t261019-31, KI-01M533EHPA0AYQ2Y2GCNGXS4SD backstop
arm; grey-box L3, real engine public module over an isolated
SANDBAR_PROJECTS_DIR root, zero docker/Temporal/3099, no production-data writes;
cost: seconds).

Incident shape: five corpse holders (dead 1.6h..66.0h) kept seven live tickets
queued — nothing ever judged holder freshness, so only a human with the panel
could break the wedge. The backstop fix makes the ledger self-healing. This
scenario pins the user-perceivable contract:

  H1 a running holder whose heartbeat is older than the declared window is
     dropped by the NEXT acquire and NAMED in the receipt
     (dropped_stale_holders); the freed slot serves the waiter on the waiter's
     NEXT poll (a bounded one-poll delay: acquire never grants on holders it
     is itself about to condemn — the t261019-29 main-green contract — and a
     waiter re-polls within its declared backoff, 5 s..120 s, so the corpse
     can never hold the slot for more than one backoff).
  H2 a fresh running holder is never dropped (the sweep is not a jackpot).
  H3 a human-hold holder is NEVER swept BY AGE, whatever its age — and even with a
     malformed/unprovable `since` (the ticket authority: "do not release a
     human-gate holder (that hold is by design)"; a gate waiter has no heartbeat
     by design, so age alone must never condemn it). It keeps counting toward
     at_work and the room judgement. (t261027-10 refines this contract: a
     human-hold holder may still be dropped on PROOF OF DEATH via the
     workflow probe — an age-independent judgement owned by
     integration/t261027-10/sc_t261027_10_dead_holder_sweep_reclaims.py;
     the age rule pinned here is unchanged.)
  H4 the heartbeat exists: acquire on an already-holding running ticket refreshes
     its `since` (a live lane working long stages must not be swept from under
     itself by a slow stage).
  H5 fail-closed: a RUNNING holder that cannot prove freshness (missing /
     non-numeric `since`) counts stale and is dropped — an unprovable holder
     never wedges the cap (the KI's own failure mode).

Fixture note: holders are created through the engine's own writer
(acquire/renew); backdating only rewrites the `since` field in the state file to
simulate elapsed time — no sleeping, no production data. Reader-side assertions
read concurrency.read_state (the face the panel serves), not the raw file.

Intent split: the acquire/release/renew truth tables belong to
t261004-32-slot-ledger; the queue-side corpse sweep belongs to the 261019
backoff fix (queue entries, not holders); the cancel-entry release hook belongs
to sc_t261019_31_terminal_cancel_releases_slot. Holder freshness + the
human-hold exemption is this scenario's object alone. Pre-implement red is the
expected TDD signal; arbitrate/merge must be green.
concurrency unimportable = ENV_FAIL exit 2.

Run: python3 integration/t261019-31/sc_t261019_31_stale_holder_sweep.py (cwd=repo root).
"""
import atexit
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

# the declared window; missing constant pre-implement = FAIL (TDD red), not crash
WINDOW = getattr(cc, "HOLDER_STALE_S", None)


def backdate(root, key, ticket, seconds_ago, since=None):
    """Rewrite ONE holder's `since` in the state file (fixture: simulate elapsed
    time without sleeping; `since=None` removes the field for the fail-closed
    row)."""
    p = Path(root) / key / cc.STATE_FILE
    doc = json.loads(p.read_text(encoding="utf-8"))
    for h in doc.get("holders") or []:
        if h.get("ticket") == ticket:
            if since is None and seconds_ago is None:
                h.pop("since", None)
            else:
                h["since"] = (time.time() - seconds_ago) if seconds_ago else since
    p.write_text(json.dumps(doc), encoding="utf-8")


def holders_of(face):
    return sorted(h.get("ticket") for h in face.get("holders") or [])


def main():
    tmp = tempfile.mkdtemp(prefix="sc-t261019-31-sweep-")
    atexit.register(shutil.rmtree, tmp, True)
    root = Path(tmp) / "projects"
    os.environ["SANDBAR_PROJECTS_DIR"] = str(root)
    key = "proj-sweep"
    (root / key).mkdir(parents=True)
    (root / key / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": 2}), encoding="utf-8")
    if WINDOW is None:
        ok(False, "HOLDER_STALE_S is declared by the engine (holder freshness "
                  "window exists)")
    else:
        ok(True, "HOLDER_STALE_S is declared by the engine (%ds)" % WINDOW)
    old = (WINDOW + 120) if WINDOW else 6 * 3600 + 120

    # ---------- H1 stale running holder swept; freed slot serves the waiter -----
    section("H1 stale running holder: swept by next acquire, NAMED, slot reused in-call")
    cc.acquire(key, "corpse")
    cc.acquire(key, "fresh")
    cc.acquire(key, "w1")  # queued (limit 2)
    backdate(root, key, "corpse", old)
    r = cc.acquire(key, "w1")  # the QUEUE HEAD polls; room was judged pre-sweep
    dropped = r.get("dropped_stale_holders")
    ok("corpse" in (dropped or []),
       "sweep NAMED the stale holder in the receipt (dropped_stale_holders)")
    face = cc.read_state(key)
    ok("corpse" not in holders_of(face), "stale holder gone from the reader face")
    ok(r.get("granted") is False,
       "no same-call jackpot: acquire never grants on a holder it just "
       "condemned (t261019-29 contract, main-green)")
    r2 = cc.acquire(key, "w1")  # the waiter's NEXT poll: the slot is already free
    ok(r2.get("granted") is True,
       "freed corpse slot serves the waiter on the next poll (bounded by the "
       "waiter backoff)")

    # ---------- H2 fresh running holder never dropped ----------------------------
    section("H2 a fresh running holder is never dropped")
    key2 = "proj-fresh"
    (root / key2).mkdir(parents=True)
    (root / key2 / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": 1}), encoding="utf-8")
    cc.acquire(key2, "alive")
    cc.acquire(key2, "w")
    r = cc.acquire(key2, "w")
    ok("alive" not in (r.get("dropped_stale_holders") or []),
       "fresh holder not in dropped_stale_holders")
    ok("alive" in holders_of(cc.read_state(key2)),
       "fresh holder still holds its slot reader-side")
    ok(r.get("granted") is False, "waiter still queued (a live holder is not stolen)")

    # ---------- H3 human-hold holder NEVER swept at any age / malformed since ---
    section("H3 human-hold holder: never swept (old age AND unprovable since)")
    key3 = "proj-gate"
    (root / key3).mkdir(parents=True)
    (root / key3 / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": 2}), encoding="utf-8")
    cc.acquire(key3, "gate-old")
    cc.acquire(key3, "gate-bad")
    cc.renew(key3, "gate-old", cc.REASON_HUMAN_HOLD)
    cc.renew(key3, "gate-bad", cc.REASON_HUMAN_HOLD)
    backdate(root, key3, "gate-old", old)       # older than the window
    backdate(root, key3, "gate-bad", None)      # cannot prove freshness
    cc.acquire(key3, "gate-older-still")        # holder 3: queued
    r = cc.acquire(key3, "w-gate")
    ok(not ({"gate-old", "gate-bad"} & set(r.get("dropped_stale_holders") or [])),
       "neither human-hold holder appears in dropped_stale_holders")
    face = cc.read_state(key3)
    ok({"gate-old", "gate-bad"} <= set(holders_of(face)),
       "both human-hold holders STILL hold their slots reader-side (ticket "
       "authority: the hold is by design)")
    ol = face.get("over_limit")
    ok(ol is None or ol.get("at_work", 0) >= 2,
       "human-hold holders keep counting toward at_work")

    # ---------- H4 the holder heartbeat exists ----------------------------------
    section("H4 acquire on an already-holding ticket refreshes its heartbeat")
    key4 = "proj-beat"
    (root / key4).mkdir(parents=True)
    (root / key4 / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": 2}), encoding="utf-8")
    cc.acquire(key4, "worker")
    backdate(root, key4, "worker", old // 2)  # age it toward the window
    before = json.loads((root / key4 / cc.STATE_FILE).read_text(encoding="utf-8"))
    b_since = next(h["since"] for h in before["holders"] if h["ticket"] == "worker")
    time.sleep(1.1)
    r = cc.acquire(key4, "worker")  # the heartbeat call
    ok(r.get("granted") is True and r.get("already_holding") is True,
       "already-holding acquire is granted immediately (renew semantics intact)")
    after = json.loads((root / key4 / cc.STATE_FILE).read_text(encoding="utf-8"))
    a_since = next(h["since"] for h in after["holders"] if h["ticket"] == "worker")
    ok(a_since > b_since, "heartbeat refreshed: since moved forward reader-side")

    # ---------- H5 fail-closed: unprovable running holder counts stale ----------
    section("H5 a running holder with missing since counts stale (fail-closed)")
    key5 = "proj-fc"
    (root / key5).mkdir(parents=True)
    (root / key5 / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": 1}), encoding="utf-8")
    cc.acquire(key5, "ghost")
    backdate(root, key5, "ghost", None)  # strip since
    r = cc.acquire(key5, "w")  # queues, sweeps, names — room judged pre-sweep
    ok("ghost" in (r.get("dropped_stale_holders") or []),
       "unprovable running holder is dropped and NAMED (never wedges the cap)")
    ok(r.get("granted") is False,
       "no same-call jackpot (t261019-29 contract)")
    ok(cc.acquire(key5, "w").get("granted") is True,
       "its slot serves the waiter on the next poll")

    print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
