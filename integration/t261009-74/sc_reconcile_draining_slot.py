#!/usr/bin/env python3
"""sc_reconcile_draining_slot.py — reconcile liveness: a draining holder keeps its
slot (t261009-74; offline L3, real engine public module + real ticket.py CLI
subprocess, isolated SANDBAR_PROJECTS_DIR root, sc_check_concurrency_reorder_face
pattern; KI-161: zero production-data writes, never touches 3099/docker/Temporal).

Fault being pinned (KI-01M4HMKZQ23649NFRTTFNCTRF6 / KI-01M4K9X2Z8W1A6CVB3QD7FHS4M):
op=concurrency reconcile:true treated EVERY probe failure as death, so a holder
whose worker was alive-but-not-polling (graceful drain, up to
SANDBAR_WORKER_GRACEFUL_SHUTDOWN_SEC after any restart) was dropped: slot
accounting undercounted (7 of 8 while 8 lanes held work) and the receipt read
"nobody is managing that ticket", pushing a steward toward a forced handover.

What it pins (spec items 1-5, user-perceivable contract):
  D1 draining keeps its slot and is NAMED on the receipt ("draining: [id]");
     only genuinely dead holders are dropped.
  D2 dropped ids always carry evidence {ticket, probe, pidfile, process} —
     no reader ever sees a bare dropped ticket id (spec 3).
  D3 a draining holder counts AGAINST the limit: with limit reached by
     draining holders the queue head is NOT promoted (the slot is a fact
     about a lane that still holds work, spec 2).
  D4 regression (spec 5): a genuinely dead holder is still dropped and the
     queue head still promotes in the same step (promoted-from as before);
     the omitted-argument call keeps today's behavior byte-for-byte.
  C1 CLI face over the real ticket.py child with Temporal UNREACHABLE
     (offline = exactly the "probe momentarily unreachable" incident shape,
     KI-01M4HMK...): nothing is dropped, holders keep their slots, every
     holder is named in probe_errors — fail-closed means "do not drop on
     unknown", never "drop on unknown" (spec 4).

Pre-implement red is the expected TDD signal; arbitrate/merge must be green.
Engine module unavailable = ENV_FAIL exit 2.

Run: python3 integration/t261009-74/sc_reconcile_draining_slot.py (cwd=repo root).
"""
import atexit
import json
import os
import shutil
import subprocess
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
    print("ENV_FAIL: server/engine/concurrency.py unimportable: %s: %s" % (type(e).__name__, e))
    sys.exit(2)

TICKET_CLI = [sys.executable, "-B", str(ROOT / "server" / "tools" / "ticket.py")]


def holders_of(face):
    return sorted(h.get("ticket") for h in face.get("holders") or [])


def main():
    tmp = tempfile.mkdtemp(prefix="sc-drain-slot-")
    atexit.register(shutil.rmtree, tmp, True)
    root = Path(tmp) / "projects"
    (root / "proj-alpha").mkdir(parents=True)
    os.environ["SANDBAR_PROJECTS_DIR"] = str(root)
    env = dict(os.environ)
    env["SANDBAR_PROJECTS_DIR"] = str(root)
    key = "proj-alpha"
    (root / key / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": 3}), encoding="utf-8")
    for t in ["h-live", "h-drain", "h-dead", "w1", "w2"]:
        cc.acquire(key, t)
    # holders: h-live, h-drain, h-dead (limit 3); queue: w1, w2 (FIFO)

    # ---------- D1/D2 engine face: draining keeps, dead drops with evidence ----------
    section("D1/D2 engine reconcile face (draining named, dead dropped with evidence)")
    out = None
    try:
        out = cc.reconcile(key, ["h-live"], draining_tickets=["h-drain"])
    except TypeError as e:
        ok(False, "reconcile accepts draining_tickets (%s: %s)" % (type(e).__name__, e))
    if out is not None:
        ok("h-drain" not in (out.get("dropped") or []),
           "draining holder is NOT dropped (KI-01M4K9X2Z... face)")
        ok("h-dead" in (out.get("dropped") or []), "dead holder is dropped")
        ok("h-drain" in (out.get("draining") or []),
           "receipt NAMES the draining holder (draining: [id], spec 2)")
        ok((out.get("dropped") or []) == ["h-dead"],
           "exactly the dead holder is dropped")
        # Evidence fields live on the ticket.py receipt (the reader's face) — the
        # evidence matrix is pinned by t261009-74-reconcile-drain-verdict-receipt E.
        face = cc.read_state(key)
        ok("h-drain" in holders_of(face) and "h-live" in holders_of(face),
           "draining + live holders still hold their slots reader-side")
        ok("h-dead" not in holders_of(face), "dead holder is gone reader-side")

    # ---------- D3 draining counts against the limit ----------
    section("D3 draining counts against the limit (no promotion past the cap)")
    key2 = "proj-beta"
    (root / key2).mkdir(parents=True, exist_ok=True)
    (root / key2 / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": 2}), encoding="utf-8")
    for t in ["d1", "d2", "w9"]:
        cc.acquire(key2, t)
    try:
        out2 = cc.reconcile(key2, [], draining_tickets=["d1", "d2"])
        ok(out2.get("promoted") is None,
           "both slots draining at limit=2 -> the queued head is NOT promoted (spec 2)")
        ok(len(out2.get("dropped") or []) == 0, "nothing dropped when both drain")
        ok("d1" in (out2.get("draining") or []) and "d2" in (out2.get("draining") or []),
           "both draining holders named on the receipt")
    except TypeError as e:
        ok(False, "reconcile draining_tickets face (%s: %s)" % (type(e).__name__, e))

    # ---------- D4 regression: dead still drops, promotion still follows ----------
    section("D4 regression (dead drops, queue head promotes; omitted arg = old behavior)")
    # Fresh project: D1's reconcile already consumed h-dead/w1 on proj-alpha.
    key4 = "proj-eps"
    (root / key4).mkdir(parents=True, exist_ok=True)
    (root / key4 / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": 2}), encoding="utf-8")
    for t in ["e1", "e2", "ew"]:
        cc.acquire(key4, t)
    try:
        out3 = cc.reconcile(key4, ["e1"])
        ok(out3.get("dropped") == ["e2"],
           "omitted draining arg: dead holder still dropped (spec 5)")
        ok(out3.get("promoted") == "ew",
           "queue head promoted in the same step (promoted-from as before)")
    except TypeError as e:
        ok(False, "reconcile back-compat face (%s: %s)" % (type(e).__name__, e))

    # ---------- C1 CLI face, Temporal unreachable: transient never drops ----------
    section("C1 real ticket.py CLI, probe unreachable (KI-01M4HMK... regression face)")
    key3 = "proj-gamma"
    (root / key3).mkdir(parents=True, exist_ok=True)
    (root / key3 / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": 2}), encoding="utf-8")
    for t in ["g1", "g2"]:
        cc.acquire(key3, t)
    r = subprocess.run(TICKET_CLI + [json.dumps(
        {"op": "concurrency", "project": key3, "reconcile": True})],
        env=env, capture_output=True, text=True, timeout=120)
    ok(r.returncode == 0, "reconcile CLI exits 0 when the probe face is unreachable")
    try:
        body = json.loads(r.stdout)
        res = body.get("result") or {}
        ok((res.get("dropped") or []) == [],
           "unreachable probe drops NOTHING (fail-closed = keep on unknown, spec 4)")
        ok(holders_of(cc.read_state(key3)) == ["g1", "g2"],
           "both holders keep their slots on disk (reader side, not the receipt)")
        pe = res.get("probe_errors") or {}
        ok(set(pe.keys()) >= {"g1", "g2"},
           "every holder is NAMED in probe_errors (never a silent keep)")
    except ValueError as e:
        ok(False, "reconcile receipt parses as JSON (%s: %s)" % (type(e).__name__, e))

    print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
