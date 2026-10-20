#!/usr/bin/env python3
"""sc_t261019_31_over_limit_named.py — an at-work count above the limit must be a
NAMED, machine-readable state on BOTH faces: the panel read face and the gate
refusal (t261019-31, host report 261019 regression; grey-box L3, real engine
public module over an isolated SANDBAR_PROJECTS_DIR root, zero docker/Temporal/
3099, no production-data writes; cost: seconds).

Incident shape: GET /sandbar-executor-panel/api/concurrency answered limit=7,
at_work=12, waiting=0 — the face silently rendered an impossible state and the
gate refused a new waiter with a generic "no room", so nobody could tell that the
face and the gate were disagreeing with each other (the limit had been lowered
under existing holders, on top of the corpse leak). This scenario pins the
contract that this state can never again be silent:

  O1 read_state names the surplus: over_limit = {limit, at_work, surplus} when
     holders exceed the limit, and is null/absent at or below the limit —
     including the unlimited case (never a phantom surplus).
  O2 the acquire refusal carries the SAME over_limit object when it refuses
     because holders still exceed the limit — one judgement, two faces.
  O3 the two faces AGREE: for the same ledger state, read_state.over_limit and
     the refusal's over_limit carry the same limit/at_work/surplus.
  O4 a human-hold holder COUNTS toward at_work and the room judgement (rule 3:
     the gate eats the slot on purpose) — an over-limit state with a human-hold
     holder in it is still named, and the waiter is still refused; the human-hold
     holder is never dropped to make room (see the sweep scenario for the
     never-swept pin).
  O5 a plain queue wait (holders below limit, waiter not at head) does NOT
     fabricate an over_limit flag — the field is the surplus alarm, not
     decoration on every refusal.

Intent split: the over-limit STATE ARISING (lowering never interrupts holders)
is pinned by t261004-32-slot-ledger S5; this scenario pins the NAMING of the
state on both faces, which did not exist before t261019-31. Pre-implement red is
the expected TDD signal; arbitrate/merge must be green.
concurrency unimportable = ENV_FAIL exit 2.

Run: python3 integration/t261019-31/sc_t261019_31_over_limit_named.py (cwd=repo root).
"""
import atexit
import json
import os
import shutil
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


def write_decl(root, key, limit):
    (root / key / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": limit}), encoding="utf-8")


def main():
    tmp = tempfile.mkdtemp(prefix="sc-t261019-31-overlimit-")
    atexit.register(shutil.rmtree, tmp, True)
    root = Path(tmp) / "projects"
    os.environ["SANDBAR_PROJECTS_DIR"] = str(root)

    # ---------- O1 the read face names the surplus (the 12/7 incident face) -----
    section("O1 read_state names the surplus; null at/below limit and when unlimited")
    key = "proj-a"
    (root / key).mkdir(parents=True)
    write_decl(root, key, 3)
    for t in ["h1", "h2", "h3"]:
        cc.acquire(key, t)
    face = cc.read_state(key)
    ok(face.get("over_limit") in (None, {}),
       "at limit exactly: no over_limit alarm")
    # the incident shape: the limit is lowered UNDER existing holders
    write_decl(root, key, 2)
    face = cc.read_state(key)
    ol = face.get("over_limit")
    ok(isinstance(ol, dict) and ol.get("limit") == 2 and ol.get("at_work") == 3
       and ol.get("surplus") == 1,
       "lowered under holders: over_limit={limit:2, at_work:3, surplus:1} is NAMED")
    key_u = "proj-unl"
    (root / key_u).mkdir(parents=True)
    write_decl(root, key_u, "unlimited")
    for t in ["u1", "u2", "u3"]:
        cc.acquire(key_u, t)
    ok(cc.read_state(key_u).get("over_limit") in (None, {}),
       "unlimited: no phantom surplus")

    # ---------- O2/O3 the gate refusal carries the same judgement ---------------
    section("O2/O3 acquire refusal carries over_limit and AGREES with the face")
    r = cc.acquire(key, "w1")  # refused: holders 3 > limit 2
    ok(r.get("granted") is False, "waiter refused while holders exceed the limit")
    rol = r.get("over_limit")
    ok(isinstance(rol, dict) and rol.get("limit") == 2 and rol.get("at_work") == 3
       and rol.get("surplus") == 1,
       "refusal names over_limit (the gate reads the same judgement)")
    ok(rol == cc.read_state(key).get("over_limit"),
       "face and gate AGREE for the same ledger state (never 12/7 silently)")

    # ---------- O4 human-hold counts, is named in the surplus, never freed ------
    section("O4 a human-hold holder counts toward at_work and is never freed to make room")
    key2 = "proj-b"
    (root / key2).mkdir(parents=True)
    write_decl(root, key2, 2)
    cc.acquire(key2, "g1")
    cc.acquire(key2, "g2")
    cc.renew(key2, "g2", cc.REASON_HUMAN_HOLD)  # rule 3: the gate eats the slot
    write_decl(root, key2, 1)  # lower under holders: surplus includes the human-hold
    face = cc.read_state(key2)
    ol = face.get("over_limit")
    ok(isinstance(ol, dict) and ol.get("at_work") == 2 and ol.get("surplus") == 1,
       "human-hold holder still counts toward at_work in the named surplus")
    r = cc.acquire(key2, "w1")
    ok(r.get("granted") is False,
       "waiter refused while a human-hold holder occupies (rule 3 holds)")
    ok("g2" in [h.get("ticket") for h in cc.read_state(key2).get("holders") or []],
       "the human-hold holder was NOT dropped to make room")

    # ---------- O5 a plain queue wait fabricates no alarm ------------------------
    section("O5 plain queue wait (below limit, not at head): no over_limit flag")
    key3 = "proj-c"
    (root / key3).mkdir(parents=True)
    write_decl(root, key3, 2)
    cc.acquire(key3, "a")
    cc.acquire(key3, "b")
    r = cc.acquire(key3, "c")  # queued behind 2 holders, no surplus
    ok(r.get("granted") is False and r.get("over_limit") in (None, {}),
       "a plain queue wait is not dressed up as an over-limit state")

    print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
