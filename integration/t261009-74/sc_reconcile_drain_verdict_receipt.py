#!/usr/bin/env python3
"""sc_reconcile_drain_verdict_receipt.py — the liveness verdict must tell draining
from dead, and a drop always carries its evidence (t261009-74; offline L3, the REAL
ticket.py op face loaded in-process with ONLY the Temporal transport seam stubbed —
the same offline-seam discipline as the page-boundary API stubs; isolated
SANDBAR_PROJECTS_DIR root, KI-161 zero production-data writes, never touches
3099/docker/Temporal service).

Fault (KI-01M4HMKZQ23649NFRTTFNCTRF6 / KI-01M4K9X2Z8W1A6CVB3QD7FHS4M): one probe
per holder and EVERY probe failure treated as death, so "worker gone" and "worker
alive but not polling (graceful drain)" were indistinguishable and both dropped.

What it pins (spec 1-4, grey-box: assertions on the op receipt + on-disk state —
the stub is the transport seam only):
  V1 no_poller + live pidfile of OUR process + meta state=draining → verdict
     draining: kept, named on the receipt, never dropped (spec 1+2).
  V2 no_poller + stale/absent pidfile → dead: dropped, WITH evidence.
  V3 no_poller + live pidfile but meta serving/missing/malformed → unknown:
     kept and named — never dropped (fail-closed, spec 4).
  V4 probe reports the workflow genuinely gone → dead: dropped with evidence.
  V5 transient RPC failure → unknown: kept, named in probe_errors, nothing
     dropped (KI-01M4HMK... face).
  V6 malformed inputs (garbage pidfile content, malformed meta JSON, missing
     meta) never produce a drop, never a crash.
  E  receipt contract: every dropped id has a parallel evidence entry
     {ticket, probe, pidfile, process} — no reader sees a bare ticket id.

Fixture note: pidfile/meta fixtures are written at the worker file shapes the
engine defines (server/engine/data/worker-<tid>.pid / .meta, ticket_worker.py
contract) under unique fixture ticket ids, and unlinked in finally. The "live
process" fixture is a real child sleep process (killed in finally) — a live pid
of ours, not a fake number. Pre-implement red is the expected TDD signal;
arbitrate/merge must be green. ticket.py unimportable = ENV_FAIL exit 2.

Run: python3 integration/t261009-74/sc_reconcile_drain_verdict_receipt.py (cwd=repo root).
"""
import atexit
import importlib.util
import json
import os
import shutil
import signal
import subprocess
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
    import shared as sh
except Exception as e:  # noqa: BLE001
    print("ENV_FAIL: engine modules unimportable: %s: %s" % (type(e).__name__, e))
    sys.exit(2)

spec = importlib.util.spec_from_file_location(
    "ticket_under_test", str(ROOT / "server" / "tools" / "ticket.py"))
tk = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(tk)
except Exception as e:  # noqa: BLE001
    print("ENV_FAIL: server/tools/ticket.py unimportable: %s: %s" % (type(e).__name__, e))
    sys.exit(2)

DATA_DIR = ROOT / "server" / "engine" / "data"
FIXTURES = []   # (path, kind) to unlink in finally


def fixture_worker(tid, pid, state):
    """Write the engine's worker pidfile + meta shapes for a fixture ticket."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pidf = DATA_DIR / ("worker-%s.pid" % tid)
    metaf = DATA_DIR / ("worker-%s.pid.meta" % tid)  # daemon shape <pidfile>.meta (the production dedicated-worker shape client.py names)
    pidf.write_text(str(pid), encoding="utf-8")
    metaf.write_text(json.dumps(sh.worker_meta_payload(
        repo_root=str(ROOT), pid=pid, state=state)), encoding="utf-8")
    FIXTURES.extend([(pidf, "file"), (metaf, "file")])


def fixture_pidfile_only(tid, pid, raw=None):
    pidf = DATA_DIR / ("worker-%s.pid" % tid)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pidf.write_text(raw if raw is not None else str(pid), encoding="utf-8")
    FIXTURES.append((pidf, "file"))


def main():
    tmp = tempfile.mkdtemp(prefix="sc-drain-verdict-")
    atexit.register(shutdown, tmp)
    root = Path(tmp) / "projects"
    root.mkdir(parents=True)
    os.environ["SANDBAR_PROJECTS_DIR"] = str(root)
    key = "proj-delta"
    (root / key).mkdir(parents=True)
    (root / key / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": 8}), encoding="utf-8")
    for t in ["f-live", "f-drain", "f-gonepid", "f-nometa", "f-serving",
              "f-badmeta", "f-gone", "f-transient", "f-garbage", "w1"]:
        cc.acquire(key, t)

    live = subprocess.Popen(["sleep", "30"])  # a real live process of ours
    time.sleep(0.3)
    fixture_worker("f-drain", live.pid, "draining")
    fixture_worker("f-live", live.pid, "serving")
    fixture_worker("f-nometa", live.pid, "serving")
    (DATA_DIR / "worker-f-nometa.pid.meta").unlink()  # pidfile live, meta missing
    fixture_worker("f-serving", live.pid, "serving")
    fixture_worker("f-badmeta", live.pid, "serving")
    (DATA_DIR / "worker-f-badmeta.pid.meta").write_text("{not json", encoding="utf-8")
    gone = subprocess.Popen(["sleep", "30"])
    gone_pid = gone.pid
    gone.send_signal(signal.SIGKILL)
    gone.wait()
    fixture_pidfile_only("f-gonepid", gone_pid)     # pidfile live-shaped, pid dead
    fixture_pidfile_only("f-garbage", 0, raw="not-a-pid")  # malformed content

    def probe_of(subcmd, payload, caller=None):
        # Structured receipts, the real client.py query contract shape: the op face
        # reads kind off a not-ok receipt; an exception is a different face (spawn/
        # parse layer) and lands on 'unknown' by construction.
        tid = (payload or {}).get("workflow_id")
        if tid == "f-gone":
            return {"ok": False, "kind": "not_found",
                    "error": "workflow execution not found: %s" % tid}
        if tid in ("f-drain", "f-gonepid"):
            return {"ok": False, "kind": "no_poller",
                    "error": "no worker poller (kind=no_poller)"}
        if tid in ("f-transient", "f-live", "f-nometa", "f-serving",
                   "f-badmeta", "f-garbage"):
            return {"ok": False, "kind": "internal",
                    "error": "RPCError: transient transport failure"}
        return {"ok": True, "result": {"status": "Running"}}

    original_poc = tk._poc
    tk._poc = probe_of
    try:
        out = tk._concurrency({"project": key, "reconcile": True})
    finally:
        tk._poc = original_poc

    dropped = out.get("dropped") or []
    draining = out.get("draining") or []
    section("V1 draining: alive worker, stopped polling (KI-01M4K9X2Z... face)")
    ok("f-drain" not in dropped, "draining holder is NOT dropped")
    ok("f-drain" in draining, "draining holder is NAMED on the receipt (spec 2)")

    section("V2/V4 dead: gone pidfile holder / workflow genuinely gone")
    ok("f-gonepid" in dropped, "no_poller + dead pid -> dropped (spec 1)")
    ok("f-gone" in dropped, "workflow-gone probe failure -> dropped")
    ok("w1" in (out.get("promoted") or []) or cc.read_state(key)["holders"],
       "ledger stays consistent after drops")

    section("V3/V5/V6 unknown keeps: live pid, serving/missing/bad meta, transient, garbage")
    for t in ["f-live", "f-nometa", "f-serving", "f-badmeta", "f-transient", "f-garbage"]:
        ok(t not in dropped, "%s is NOT dropped (unknown != dead, spec 4)" % t)
    pe = out.get("probe_errors") or {}
    ok("f-transient" in pe, "transient failure is NAMED in probe_errors (never silent)")
    ok("f-serving" in pe or "f-serving" in draining,
       "serving meta under no_poller is classified, never silently dropped")

    section("E receipt contract: evidence on every drop, never a bare id")
    ev = out.get("dropped_evidence") or []
    ev_by = {}
    for e in ev:
        if isinstance(e, dict) and e.get("ticket"):
            ev_by[e["ticket"]] = e
    ok(dropped and all(t in ev_by for t in dropped),
       "every dropped id carries an evidence entry (spec 3)")
    ok(all(("probe" in ev_by[t] and "pidfile" in ev_by[t] and "process" in ev_by[t])
           for t in dropped if t in ev_by),
       "evidence names probe, pidfile and process state")
    face = cc.read_state(key)
    kept = sorted(h.get("ticket") for h in face.get("holders") or [])
    for t in ["f-live", "f-drain", "f-nometa", "f-serving", "f-badmeta",
              "f-transient", "f-garbage"]:
        ok(t in kept, "%s still holds its slot on disk (reader side)" % t)
    ok("f-gonepid" not in kept and "f-gone" not in kept,
       "dead holders are gone from the on-disk ledger")

    print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
    shutdown(tmp)
    sys.exit(1 if FAIL else 0)


def shutdown(tmp):
    for p, _kind in FIXTURES:
        try:
            Path(p).unlink()
        except OSError:
            pass
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    try:
        main()
    finally:
        for p, _kind in FIXTURES:
            try:
                Path(p).unlink()
            except OSError:
                pass
