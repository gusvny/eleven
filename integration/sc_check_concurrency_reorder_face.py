#!/usr/bin/env python3
"""check_concurrency_reorder_face.py — CL-3 reorder write face, offline L3 face
(t261009-03; sc_check_inspection_produce_chain offline pattern).

What it pins (ticket evidence bar, L3 + the review's "authored scenario" bar):
  A WRITE face (real CLI subprocess, isolated projects root): the exact args
    the panel host posts ({op:'concurrency', project, order}) land through
    `python3 server/tools/ticket.py '<json>'` — the ticket moves, and the
    subsequent read face (GET shape) returns the NEW order. One reader face,
    zero local order state.
  B REFUSAL faces (state bytes byte-identical on every refusal):
    a stale order (queue changed between the panel's read and its POST) is
    refused by name with the engine's permutation text; an empty order on a
    non-empty queue is refused (not a permutation); an unqueued id cannot be
    injected.
  C PANEL SEAM source-lock: node.ts forwards {project, order} through
    callTool('ticket', ...) and never fakes success on a queue mismatch
    (neutral 409 text); the sidebar's null/stale-face guard sets the visible
    order-notice line (the "drag looked inert" fix) and the notice element
    renders it (role=alert) — reachable without dev tools.
  D SEMANTICS: only the queue order changes — holders keep their slots, the
    queue count never changes, no reorder can promote a queued ticket.

Run directly: python3 integration/sc_check_concurrency_reorder_face.py (cwd=repo root).
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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


def section(title):
    print("\n%s" % title)


import concurrency as cc  # noqa: E402

TICKET_CLI = [sys.executable, "-B", str(ROOT / "server" / "tools" / "ticket.py")]


def cli(args, env):
    """One direct-spawn CLI call: the same shape runAdminCli drives."""
    r = subprocess.run(TICKET_CLI + [json.dumps(args)], env=env,
                       capture_output=True, text=True, timeout=60)
    return r


def main():
    tmp = tempfile.mkdtemp(prefix="sc-reorder-")
    shutil.rmtree(tmp, ignore_errors=True)  # reclaim at exit (L8 hygiene)
    import atexit
    atexit.register(shutil.rmtree, tmp, True)
    root = Path(tmp) / "projects"
    (root / "proj-alpha").mkdir(parents=True)
    # Isolation MUST cover the IN-PROCESS engine calls too (shared.perkey_projects_root
    # reads the env fresh per call): without this the cc.acquire/read_state legs hit the
    # production projects root and fail closed (and would otherwise write there — KI-161).
    os.environ["SANDBAR_PROJECTS_DIR"] = str(root)
    os.environ["SANDBAR_ADMIN_LOG"] = str(Path(tmp) / "admin.log")
    env = dict(os.environ)
    env["SANDBAR_PROJECTS_DIR"] = str(root)
    env["SANDBAR_ADMIN_LOG"] = str(Path(tmp) / "admin.log")
    key = "proj-alpha"
    (root / key / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": 1}), encoding="utf-8")
    for i, t in enumerate(["t1", "t2", "t3", "t4"]):
        cc.acquire(key, t)  # t1 holds the slot; t2/t3/t4 queue FIFO

    def digest():
        return hashlib.sha256((root / key / cc.STATE_FILE).read_bytes()).hexdigest()

    def queue_of_cli_read():
        r = cli({"op": "concurrency", "project": key}, env)
        assert r.returncode == 0, r.stderr
        return [e["ticket"] for e in json.loads(r.stdout)["result"]["queue"]]

    # ---------- A write face: the panel's POST args land via the real CLI ----------
    section("A write face (real CLI subprocess, isolated projects root)")
    ok(queue_of_cli_read() == ["t2", "t3", "t4"], "baseline read face: FIFO queue")
    r = cli({"op": "concurrency", "project": key, "order": ["t4", "t2", "t3"]}, env)
    ok(r.returncode == 0, "reorder POST exits 0")
    out = json.loads(r.stdout)["result"]
    ok([e["ticket"] for e in out["queue"]] == ["t4", "t2", "t3"],
       "reply carries the new order in the read-face shape")
    ok(queue_of_cli_read() == ["t4", "t2", "t3"],
       "subsequent GET (read face) returns the new order — one reader face")
    ok(out.get("project") == key and "holders" in out and "limit" in out,
       "reply is the full read face, not a bare queue")

    # ---------- D semantics: only the queue order changes ----------
    section("D reorder semantics (holders keep slots, count constant)")
    face = cc.read_state(key)
    ok([h["ticket"] for h in face["holders"]] == ["t1"],
       "holder slot untouched by the reorder above")
    ok(len(face["queue"]) == 3, "queue count never changes")
    ok("t-inject" not in [e["ticket"] for e in face["queue"]], "no injected member")

    # ---------- B refusal faces: named, byte-identical state ----------
    # A STALE order needs a MEMBERSHIP change, not a re-permutation: the engine
    # lawfully applies any permutation of the CURRENT members (a same-membership
    # re-order is a valid move, not a stale one). Release the holder so the queue
    # head promotes OUT of the queue (real engine release, never hand-edited
    # state) - the previously read full order is then no longer a permutation.
    section("B refusal faces (named, state byte-identical)")
    ok(cc.release(key, "t1", cause="paused").get("promoted") == "t4",
       "membership mutation: paused holder releases, reordered head promotes out")
    before = digest()
    r = cli({"op": "concurrency", "project": key,
             "order": ["t4", "t2", "t3"]}, env)  # stale: t4 is no longer queued
    body = json.loads(r.stdout)
    ok(r.returncode == 1 and body.get("ok") is False, "stale order -> structured refusal, exit 1")
    ok("not a permutation" in str(body.get("error")), "refusal names the permutation check")
    ok(digest() == before, "state file byte-identical after the refusal")
    r = cli({"op": "concurrency", "project": key, "order": []}, env)
    ok(r.returncode == 1 and "not a permutation" in json.loads(r.stdout)["error"],
       "empty order on a non-empty queue is refused (not a permutation)")
    ok(digest() == before, "state byte-identical after the empty-order refusal")
    r = cli({"op": "concurrency", "project": key,
             "order": ["t2", "t3", "t-inject"]}, env)
    ok(r.returncode == 1, "unqueued id cannot be injected (refused)")
    ok(digest() == before, "state byte-identical after the injection attempt")

    # ---------- C panel seam source-lock ----------
    section("C panel seam source-lock (node.ts + sidebar)")
    node_src = (ROOT / "server/plugins/workbench/node.ts").read_text("utf-8")
    side_src = (ROOT / "server/plugins/workbench/src/client/sidebar.tsx").read_text("utf-8")
    ok("{ op: 'concurrency', project, order }" in node_src,
       "POST forwards {project, order} through callTool('ticket', ...)")
    ok("differs from the requested order" in node_src
       and "refusing to fake success" in node_src,
       "queue-mismatch branch refuses with the neutral named text (no fake success)")
    ok("ignored the order key" not in node_src,
       "the stale 'write face not landed' claim is retired with the face landed")
    ok("the queue face is unavailable or stale — no move made" in side_src
       and "wb-order-notice" in side_src and 'role="alert"' in side_src,
       "guard refusal sets the visible notice line; element renders it (no dev tools)")

    print("\n%d passed, %d failed" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
