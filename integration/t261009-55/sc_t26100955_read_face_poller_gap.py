#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26100955_read_face_poller_gap.py — the ticket read face survives a poller
gap BY NAME (t261009-55 spec items 3+4, KI-01M4GF5R8NHQNATH7WD7SKF94X addendum;
grey-box L2, offline seconds, zero docker/Temporal/3099).

intent (user-perceivable contract):
  A ticket's snapshot is read through a Temporal QUERY that a poller on that
  ticket's queue must answer. While the queue has no live poller (console
  restart handover, draining, or a shed poller) the read fails — and the face
  must NOT render stage=None plus a bogus updated timestamp (which reads as
  "stuck/empty" instead of "the answer is temporarily unreachable"). The failed
  read degrades BY NAME to the durable facts still readable without a poller
  (workflow status from describe; last known stage/time from the engine's stage
  memo — authoritative for "where was this ticket last seen", never for the
  stage DECISION) and labels the missing read
  unavailable(<named cause> @ queue=<q> ticket=<tid>), using the engine's own
  classification (no_poller vs query_timeout). While an orphaned STARTED
  workflow task is waiting out its start_to_close timeout, the face says the
  ticket is waiting on the platform — not stuck. The receipt's kind and wording
  stay byte-identical (t260919-02 discipline: add keys, never change
  semantics).

faces asserted (the landed public contract of server/engine/client.py):
  R1 a classified no_poller receipt + fixture describe => the receipt carries a
     durable block with the unavailable(no_poller @ queue/ticket) label, the
     memo-sourced last stage (never a guessed one), and a memo-sourced updated
     only when the memo actually has a timestamp; the receipt kind/wording are
     unchanged (additive-only face).
  R2 a query_timeout-shaped receipt (live pollers present => KIND_TRANSIENT) =>
     the label names query_timeout — the two causes are distinguishable.
  R3 the orphan-window note names STARTED + start_to_close + "waiting on the
     platform, not stuck" (spec item 4; timeout unchanged).
  R4 malformed durable inputs (memo read raises / memo without stage keys /
     stub describe without memo()) => the receipt is returned unchanged (never
     a half-made face), no crash, no invented facts (external-input
     three-state).
  R5 the healthy read path is untouched: a snapshot that answers still goes
     through the existing named read (no degrade involved).

seam binding (grey-box, shallow): `_augment_read_failure_receipt` +
`_orphan_window_note` + `_classify_snapshot_failure`, all module-level in
client.py; assertions are face-level only. Update the binding only if the
public contract surface itself is renamed.

Green expected (implementation landed in this lane, commit bed08c45).
temporalio / client.py unimportable = ENV_FAIL exit 2.
"""
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CLIENT = REPO / "server" / "engine" / "client.py"

fails = []
n = 0


def check(cond, label, detail=""):
    global n
    n += 1
    if cond:
        print("ok   R%d %s" % (n, label))
    else:
        fails.append("R%d %s %s" % (n, label, detail))
        print("FAIL R%d %s %s" % (n, label, detail))


sys.path.insert(0, str(REPO / "server" / "engine"))  # client.py imports `shared`
spec = importlib.util.spec_from_file_location("client_under_test", CLIENT)
try:
    cl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cl)
except Exception as exc:  # noqa: BLE001
    print("ENV_FAIL: client.py unimportable (temporalio in venv?): %r" % exc)
    sys.exit(2)

TID = "t26100955-r"
QUEUE = cl.ticket_task_queue(TID)
TS = 1750000000


class Desc:
    """Fixture describe-shaped object: status name + memo() over a dict."""

    def __init__(self, memo=None, memo_raises=False, no_memo=False):
        self.status = type("S", (), {"name": "RUNNING"})()
        self._memo = memo if memo is not None else {}
        self._raises = memo_raises
        if no_memo:
            self.memo = None  # stub without the memo face

    async def memo(self):
        if self._raises:
            raise RuntimeError("memo boom")
        return self._memo


GOOD_MEMO = {cl.STAGE_MEMO_KEY: "implement",
             cl.STAGE_MEMO_HISTORY_KEY: [{"stage": "implement", "ts": TS}]}


def no_poller_receipt():
    return cl._classify_snapshot_failure(
        TimeoutError("query timed out"), TID, QUEUE,
        {"available": True, "live_pollers": 0, "queue": QUEUE, "ticket": TID})


def timeout_receipt():
    return cl._classify_snapshot_failure(
        TimeoutError("query timed out"), TID, QUEUE,
        {"available": True, "live_pollers": 1, "queue": QUEUE})


async def augment(receipt, desc):
    return await cl._augment_read_failure_receipt(receipt, TID, None, desc)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def main():
    for seam in ("_augment_read_failure_receipt", "_orphan_window_note",
                 "_classify_snapshot_failure"):
        check(callable(getattr(cl, seam, None)),
              "R0 seam %s exported by client.py" % seam, "missing")

    # ---- R1 no_poller degrade: durable block, additive-only receipt
    r = no_poller_receipt()
    kind_before, err_before = r.get("kind"), r.get("error")
    out = run(augment(r, Desc(GOOD_MEMO)))
    check(str(out.get("kind")) == str(kind_before)
          and str(out.get("error")) == str(err_before),
          "R1 receipt kind/wording unchanged (additive-only)", json.dumps(out)[:200])
    d = (out.get("face") or {}).get("durable") or {}
    check(d.get("unavailable") == "unavailable(no_poller @ queue=%s ticket=%s)"
          % (QUEUE, TID),
          "R1 label names cause+queue+ticket exactly", json.dumps(d))
    check(d.get("last_stage") == "implement" and d.get("last_stage_available"),
          "R1 memo-sourced last stage survives", json.dumps(d))
    check(d.get("updated_ts") == TS and d.get("updated"),
          "R1 updated sourced from the memo history, not fabricated",
          json.dumps({k: d.get(k) for k in ("updated_ts", "updated")}))

    # ---- R2 query_timeout distinguishable (live pollers => transient wording)
    out2 = run(augment(timeout_receipt(), Desc(GOOD_MEMO)))
    d2 = (out2.get("face") or {}).get("durable") or {}
    check(str(d2.get("unavailable", "")).startswith("unavailable(query_timeout"),
          "R2 query_timeout cause named on the face", json.dumps(d2))
    check("no_poller" not in str(d2.get("unavailable")),
          "R2 causes are distinguishable (no cross-contamination)", json.dumps(d2))

    # ---- R3 orphan window note
    note = cl._orphan_window_note("no_poller")
    check("STARTED" in note and "start_to_close" in note
          and "not stuck" in note and "499" in note,
          "R3 orphan window named as a platform wait", note)
    d3 = ((run(augment(no_poller_receipt(), Desc(GOOD_MEMO)))
           .get("face") or {}).get("durable") or {})
    check("waiting on the platform" in str(d3.get("orphan_window_note")),
          "R3 note lands on the degraded face", json.dumps(d3.get("orphan_window_note")))

    # ---- R4 malformed durable inputs: receipt unchanged, no crash
    for desc, tag in ((Desc(memo_raises=True), "memo read raises"),
                      (Desc({"junk": 1}), "memo without stage keys"),
                      (Desc(no_memo=True), "stub describe without memo()")):
        base = no_poller_receipt()
        try:
            o = run(augment(base, desc))
        except Exception as exc:  # noqa: BLE001
            check(False, "R4 %s crashes the augment" % tag, repr(exc))
            continue
        check(str(o.get("error")) == str(base.get("error"))
              and str(o.get("kind")) == str(base.get("kind")),
              "R4 %s => receipt unchanged (never half-made)" % tag,
              json.dumps(o)[:160])
        d4 = (o.get("face") or {}).get("durable") or {}
        check("unavailable" in json.dumps(d4) or not d4,
              "R4 %s => no invented durable facts" % tag, json.dumps(d4))

    # ---- R5 healthy path untouched
    class GoodHandle:
        async def query(self, name, **kw):
            return {"meta": {"stage": "review"}}

    snap = run(cl._query_snapshot_with_retry(GoodHandle(), timeout=1.0))
    check(isinstance(snap, dict) and snap.get("meta", {}).get("stage") == "review",
          "R5 healthy snapshot still answers through the named read", repr(snap))

    print("SUMMARY %d checks, %d failures" % (n, len(fails)))
    if fails:
        for f in fails:
            print("FAILED: %s" % f)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
