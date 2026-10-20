#!/usr/bin/env python3
"""t261018-11 terminal-face honesty — grey-box L3, offline, seconds, zero docker.

Ticket t261018-11 (host report 261018): every ticket that finished carries a
non-terminal face — status=closed while stage_state stays 'awaiting',
close_ts is missing, signatures is empty, and the merge stage's acceptance
still claims 'Human sign-off recorded' although the gate was satisfied by the
develop-buffer landing (engine:land), not by a human. Temporal reports
COMPLETED, so the frozen return snapshot is the only face a reader can ever
get: no worker is ensured, the sign signal is refused with no_poller. The
user-visible contract under test (read boundary in server/engine/client.py,
this ticket's write set):

  F1  A COMPLETED closed ticket whose frozen snapshot says awaiting + empty
      signatures + a sign-off claim must be SERVED with a terminal word
      (stage_state 'closed', never 'awaiting'), an honest gate-disposition
      line naming the landing (engine:land) instead of the sign-off claim,
      a populated close time, and a reconciliation note marking the served
      copy as reconciled (not the frozen history).
  F2  A genuinely signed ticket keeps its signature face untouched (only the
      stage word is reconciled).
  F3  When the terminal record does NOT prove the disposition, the face says
      the disposition is unreadable / not signed — never the sign-off claim,
      never a fabricated cause.
  F4  Pass-through: non-matching faces (status not closed) come out
      byte-identical; malformed snapshot (non-dict result) is a structured
      named error, never a crash.
  F5  List face, snapshot read failed (in-window hydrate degraded to the
      minimal row): the row must not pair status=closed with the waiting
      word 'awaiting' either — same terminal word + note.

Out of scope by ticket: landing path, merge-gate authority, console UI
mapping, worker ensure policy, dismissal/void semantics, inspection rows.

Intent split (no intent-level duplication): the pure-helper truth tables,
malformed-input matrices and call-site wiring belong to developer L1
(server/engine/tests/test_t261018_11_terminal_face_honesty.py); this entry
owns the served-face journey through the real command boundary over fixture
snapshots. The producer-side fix (dev_lane close-out word + static acceptance
template) is a declared follow-up ticket, not covered here.

Pre-implement tree: F1–F5 red = the named TDD signal; green required at the
integration gate / merge. client.py unimportable (temporalio missing) =
ENV_FAIL exit 2.
"""

import asyncio
import datetime
import importlib
import os
import sys

FAILS: list = []
ENVS: list = []


def _fail(sub: str, msg: str) -> None:
    FAILS.append("%s: %s" % (sub, msg))


def _env(sub: str, msg: str) -> None:
    ENVS.append("%s: %s" % (sub, msg))


REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "server", "engine"))
sys.path.insert(0, REPO)

try:
    client = importlib.import_module("client")
except Exception as e:  # noqa: BLE001 — environment, not product
    print("ENV_FAIL client.py unimportable (%s: %s)" % (type(e).__name__, e))
    sys.exit(2)

CLOSE_TS = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)

AWAITING_SNAP = {
    # Fidelity note (acceptance walkthrough gen0): the frozen return snapshot of a
    # real dev-lane workflow (dev_lane.snapshot) carries the acceptance lists AND
    # the checks/timeline maps at the TOP level, with meta holding mirrors. The
    # first fixture draft kept them only under meta — a shape no real snapshot
    # serves, so subcases A/C read red against a face the engine never produces.
    # The shape below matches dev_lane.py snapshot().
    "kind": "dev_lane",
    "status": "closed",
    "stage": "merge",
    "stage_state": "awaiting",
    "signatures": {},
    "paused": False,
    "stage_acceptance": ["Human sign-off recorded", "Merge booked + lane cleaned up"],
    "acceptance": ["Human sign-off recorded", "Merge booked + lane cleaned up"],
    "checks": {"merge": [{"check": "land", "ok": True, "by": "engine:land"}]},
    "timeline": [
        {"note": "merge done (engine:land: develop-buffer landing, proven ff366be68d51)"},
        {"note": "merge closed, workflow complete"},
    ],
    "meta": {
        "ticket_id": "t261018-05",
        "title": "buffer landing ticket",
        "status": "closed",
        "stage": "merge",
        "stage_state": "awaiting",
        "acceptance": ["Human sign-off recorded", "Merge booked + lane cleaned up"],
        "checks": {"merge": [{"check": "land", "ok": True, "by": "engine:land"}]},
        "timeline": [
            {"note": "merge done (engine:land: develop-buffer landing, proven ff366be68d51)"},
            {"note": "merge closed, workflow complete"},
        ],
    },
}


class _Attrs:
    """Dict-like stand-in for Temporal typed search attributes."""

    def __init__(self, kv=None):
        self._kv = dict(kv or {})

    def get(self, key, default=None):
        return self._kv.get(key, default)


class _Status:
    def __init__(self, name):
        self.name = name


class _Desc:
    def __init__(self, status="COMPLETED", close_time=None):
        self.status = _Status(status)
        self.close_time = close_time
        self.typed_search_attributes = _Attrs()
        self.history_length = 1


class _Handle:
    def __init__(self, snap=None, raise_on_result=False):
        self._snap = snap
        self._raise = raise_on_result
        self.run_id = "stub-run-id"
        self.result_run_id = "stub-run-id"

    async def result(self):
        if self._raise:
            raise RuntimeError("stub: snapshot read failed")
        return self._snap

    async def cancel(self):
        return None


class _QueryClient:
    def __init__(self, handle):
        self._handle = handle

    def get_workflow_handle(self, tid, **kw):
        return self._handle


class _ListWf:
    """Stub workflow execution as the list scan consumes it."""

    def __init__(self, tid, handle):
        self.id = tid
        self.status = _Status("COMPLETED")
        self.close_time = CLOSE_TS
        self.task_queue = client.TASK_QUEUE
        self.typed_search_attributes = _Attrs()
        self._handle = handle

    async def result(self):
        return await self._handle.result()


class _ListClient:
    def __init__(self, wfs):
        self._wfs = wfs
        self.handles = {}

    def get_workflow_handle(self, tid, **kw):
        h = self.handles.get(tid)
        if h is None:
            h = _Handle(None, raise_on_result=True)
            self.handles[tid] = h
        return h

    async def list_workflows(self, query):
        for wf in self._wfs:
            yield wf


def _install_query_stubs(desc, handle):
    orig_connect = client._connect
    orig_describe = getattr(client, "_describe_with_retry", None)

    async def fake_connect():
        return _QueryClient(handle)

    async def fake_describe(handle_, *a, **kw):
        return desc

    client._connect = fake_connect
    if orig_describe is not None:
        client._describe_with_retry = fake_describe
    return orig_connect, orig_describe


def _restore_query_stubs(saved):
    client._connect, (orig_desc,) = saved[0], [saved[1]]
    if orig_desc is not None:
        client._describe_with_retry = orig_desc


async def _query(snap, raise_on_result=False, status="COMPLETED"):
    handle = _Handle(snap, raise_on_result=raise_on_result)
    desc = _Desc(status=status, close_time=CLOSE_TS)
    saved = _install_query_stubs(desc, handle)
    try:
        return await client.cmd_ticket_query({"ticket_id": "t261018-05"})
    finally:
        _restore_query_stubs(saved)


def _snap_words(payload):
    """Every stage_state word the detail face carries (snapshot + ticket meta)."""
    words = []
    snap = payload.get("result", {}).get("snapshot") or {}
    if isinstance(snap, dict):
        words.append(("snapshot.stage_state", snap.get("stage_state")))
        meta = snap.get("meta")
        if isinstance(meta, dict):
            words.append(("meta.stage_state", meta.get("stage_state")))
    ticket = payload.get("result", {}).get("ticket")
    if isinstance(ticket, dict):
        words.append(("ticket.stage_state", ticket.get("stage_state")))
    return words


def _acc_items(payload):
    items = []
    result = payload.get("result", {})
    snap = result.get("snapshot") or {}
    if isinstance(snap, dict):
        meta = snap.get("meta")
        if isinstance(meta, dict) and isinstance(meta.get("acceptance"), list):
            items += [str(x) for x in meta["acceptance"]]
    ticket = result.get("ticket")
    if isinstance(ticket, dict) and isinstance(ticket.get("acceptance"), list):
        items += [str(x) for x in ticket["acceptance"]]
    if isinstance(ticket, dict) and isinstance(ticket.get("stage_acceptance"), list):
        items += [str(x) for x in ticket["stage_acceptance"]]
    return items


def _notes(payload):
    result = payload.get("result", {})
    notes = []
    snap = result.get("snapshot") or {}
    if isinstance(snap, dict):
        meta = snap.get("meta")
        if isinstance(meta, dict):
            notes.append(meta.get("terminal_face_note"))
    ticket = result.get("ticket")
    if isinstance(ticket, dict):
        notes.append(ticket.get("terminal_face_note"))
    return [n for n in notes if n]


def case_a_incident_detail_face():
    """F1: awaiting + empty signatures + sign-off claim → terminal honest face."""
    payload = asyncio.run(_query(AWAITING_SNAP))
    if not payload.get("ok"):
        _fail("A", "detail query not ok: %r" % payload.get("error"))
        return
    for key, word in _snap_words(payload):
        if word == "awaiting":
            _fail("A", "%s still serves the waiting word 'awaiting' for a "
                       "COMPLETED workflow" % key)
        if word is not None and word != "closed":
            _fail("A", "%s = %r, expected the terminal word 'closed'" % (key, word))
    items = _acc_items(payload)
    if any("Human sign-off recorded" in it for it in items):
        _fail("A", "acceptance still claims 'Human sign-off recorded' with "
                   "empty signatures")
    if not any(("land" in it.lower() or "not signed" in it.lower())
               for it in items):
        _fail("A", "no acceptance line names the real disposition (landing or "
                   "explicit not-signed); items=%r" % items)
    if not _notes(payload):
        _fail("A", "no terminal_face_note on the served face — a reader cannot "
                   "tell the reconciled copy from frozen history")
    ticket = payload.get("result", {}).get("ticket") or {}
    if not ticket.get("close_ts"):
        _fail("A", "close_ts not populated on the terminal face")


def case_b_signed_untouched():
    """F2: a real human signature keeps the acceptance face byte-identical."""
    import copy
    snap = copy.deepcopy(AWAITING_SNAP)
    snap["signatures"] = {"merge": {"who": "host", "verdict": "approve"}}
    payload = asyncio.run(_query(snap))
    if not payload.get("ok"):
        _fail("B", "detail query not ok: %r" % payload.get("error"))
        return
    items = _acc_items(payload)
    if not any("Human sign-off recorded" in it for it in items):
        _fail("B", "signed ticket's sign-off acceptance line was rewritten: %r"
                   % items)
    for key, word in _snap_words(payload):
        if word == "awaiting":
            _fail("B", "%s still 'awaiting' — the stage word must reconcile "
                       "even for signed tickets" % key)


def case_c_unreadable_disposition():
    """F3: no signature, no engine:land proof → explicit not-signed, never a claim."""
    import copy
    snap = copy.deepcopy(AWAITING_SNAP)
    snap["meta"]["checks"] = {"merge": "garbage"}
    snap["checks"] = {"merge": "garbage"}  # top-level mirror, real snapshot shape
    payload = asyncio.run(_query(snap))
    if not payload.get("ok"):
        _fail("C", "detail query not ok: %r" % payload.get("error"))
        return
    items = _acc_items(payload)
    if any("Human sign-off recorded" in it for it in items):
        _fail("C", "unreadable disposition still claims 'Human sign-off recorded'")
    if not any(("not signed" in it.lower() or "unreadable" in it.lower())
               for it in items):
        _fail("C", "no explicit unavailable/not-signed line; items=%r" % items)


def case_d_passthrough_and_malformed():
    """F4: non-matching faces pass through; non-dict result is a named error."""
    snap = dict(AWAITING_SNAP, status="dispatched", stage_state="running")
    payload = asyncio.run(_query(snap))
    if not payload.get("ok"):
        _fail("D", "pass-through face errored: %r" % payload.get("error"))
    else:
        s = payload.get("result", {}).get("snapshot") or {}
        if s.get("stage_state") != "running" or s.get("status") != "dispatched":
            _fail("D", "non-closed face was rewritten: %r" % s.get("stage_state"))
    payload = asyncio.run(_query("not-a-dict"))
    if payload.get("ok"):
        _fail("D", "non-dict snapshot served as ok")
    elif payload.get("kind") in ("terminal", "not_found"):
        _fail("D", "malformed snapshot mis-sorted into kind=%r" % payload.get("kind"))


async def _list_rows(handle, tid="t261018-05"):
    wf = _ListWf(tid, handle)
    lc = _ListClient([wf])
    lc.handles[tid] = handle
    orig = client._connect

    async def fake_connect():
        return lc

    client._connect = fake_connect
    try:
        return await client.cmd_ticket_list({})
    finally:
        client._connect = orig


def _devlane_rows(payload):
    return (payload.get("result") or {}).get("tickets") or []


def case_e_minimal_row_no_waiting_word():
    """F5: in-window closed row whose snapshot read failed → no 'awaiting' pair."""
    payload = asyncio.run(_list_rows(_Handle(None, raise_on_result=True)))
    if not payload.get("ok"):
        _fail("E", "list query not ok: %r" % payload.get("error"))
        return
    rows = _devlane_rows(payload)
    if not rows:
        _env("E", "no rows served — list shape changed, subcase not judgeable")
        return
    for row in rows:
        if row.get("status") == "closed" and row.get("stage_state") == "awaiting":
            _fail("E", "closed row still advertises the waiting word; row keys=%r"
                       % sorted(row.keys()))


def case_f_inwindow_row_reconciled():
    """F5: in-window closed row whose snapshot read succeeded → reconciled word."""
    payload = asyncio.run(_list_rows(_Handle(dict(AWAITING_SNAP))))
    if not payload.get("ok"):
        _fail("F", "list query not ok: %r" % payload.get("error"))
        return
    rows = _devlane_rows(payload)
    if not rows:
        _env("F", "no rows served — list shape changed, subcase not judgeable")
        return
    for row in rows:
        if row.get("status") == "closed" and row.get("stage_state") == "awaiting":
            _fail("F", "hydrated closed row still serves 'awaiting'")


def main():
    case_a_incident_detail_face()
    case_b_signed_untouched()
    case_c_unreadable_disposition()
    case_d_passthrough_and_malformed()
    case_e_minimal_row_no_waiting_word()
    case_f_inwindow_row_reconciled()
    if ENVS:
        for e in ENVS:
            print("ENV_FAIL %s" % e)
        sys.exit(2)
    if FAILS:
        print("FAIL t261018-11 terminal-face honesty (%d):" % len(FAILS))
        for f in FAILS:
            print("  - %s" % f)
        sys.exit(1)
    print("PASS t261018-11 terminal-face honesty: F1-F5 all green "
          "(detail face reconciled, signed untouched, unreadable honest, "
          "pass-through intact, list rows carry no waiting word)")


if __name__ == "__main__":
    main()
