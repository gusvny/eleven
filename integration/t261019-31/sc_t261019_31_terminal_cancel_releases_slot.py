#!/usr/bin/env python3
"""sc_t261019_31_terminal_cancel_releases_slot.py — a ticket cancelled through an
engine-side terminal entry must release its concurrency slot in the same operation
(t261019-31, KI-01M533EHPA0AYQ2Y2GCNGXS4SD regression; grey-box L3, the real
client.py cancel entry loaded in-process with ONLY the Temporal transport seam
stubbed (FakeHandle/FakeClient, test_t260922_10_cancel_entry pattern), real
concurrency ledger over an isolated SANDBAR_PROJECTS_DIR root, zero
docker/Temporal/3099, never touches production data; cost: seconds).

Incident shape (host report 261019, sandbar project): five already-cancelled
tickets still held slots (52.3h/66.0h/37.6h/36.8h/1.6h after their cancel) because
cancel/terminate never passes the normal close-out path, so nothing releases the
slot — the face read at_work=12 against a limit of 7 with only seven tickets alive.
Integration had to release the corpses by hand through the engine's writer. This
scenario pins the structural fix at the user-perceivable contract level:

  C1 cancelling a slot-holding ticket through the named cancel entry releases the
     slot in the SAME operation: the receipt says terminated=true AND names the
     release (slot_released.released=true with the freed-slot bookkeeping),
     the queue head is promoted, and the READER-side face (concurrency.read_state
     — what the panel serves) no longer lists the ticket. Writer ok is not
     evidence; the reader's face is.
  C2 cancelling a ticket that holds no slot still succeeds and gets a no-op
     release receipt (released=false), never an error — a cancel must not be
     held hostage by bookkeeping (best-effort by contract).
  C3 an already-terminal ticket keeps the idempotent receipt (already_terminal,
     zero action) and the ledger is untouched — no release is fabricated for a
     ticket that was never released-or-held by this call.
  C4 when the ledger REFUSES (malformed state file), the cancel still succeeds
     (terminated=true) and the refusal is NAMED on the receipt
     (slot_released.reason) — no silent swallow (KI discipline: a refusal
     must be visible), no exception escaping into the cancel path.

Intent split: the release/renew truth tables of the ledger itself belong to
t261004-32-slot-ledger (S2/S3) and are not re-asserted here; the client-entry
HOOK (which entry releases, and what the receipt names) is this scenario's
object. Human-gate holders are covered by the sweep scenario of this ticket and
by t261004-32-slot-ledger S3 — never released here either (C1 uses a running
holder only). Pre-implement red is the expected TDD signal; arbitrate/merge must
be green. client.py / concurrency unimportable (no temporalio SDK) = ENV_FAIL
exit 2.

Run: python3 integration/t261019-31/sc_t261019_31_terminal_cancel_releases_slot.py (cwd=repo root).
"""
import asyncio
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

try:
    import client
except Exception as e:  # noqa: BLE001
    print("ENV_FAIL: server/engine/client.py unimportable (temporalio SDK "
          "present?): %s: %s" % (type(e).__name__, e))
    sys.exit(2)

KEY = "sandbar"  # the cancel entries read the caller identity env; the registry
                 # identity "sandbar" must pair with the isolated root's project
LIMIT = 2


# ---------- Temporal transport stubs (test_t260922_10_cancel_entry pattern) ----
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


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# the cross-project gate reads the ticket snapshot through this seam; stub it at
# the same transport-seam level (project=sandbar, paired with the caller env)
_SNAP = {"meta": {"project": KEY}, "workflow_class": "DevLaneWorkflow",
         "template_id": "dev-lane", "refused": [], "authorizations": []}


def _stub_snapshot_seam():
    client._query_snapshot_with_retry = (
        lambda handle, timeout=0: asyncio.sleep(0, result=_SNAP))


def holders_of(face):
    return sorted(h.get("ticket") for h in face.get("holders") or [])


def main():
    tmp = tempfile.mkdtemp(prefix="sc-t261019-31-cancel-")
    atexit.register(shutil.rmtree, tmp, True)
    root = Path(tmp) / "projects"
    (root / KEY).mkdir(parents=True)
    os.environ["SANDBAR_PROJECTS_DIR"] = str(root)
    (root / KEY / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": LIMIT}), encoding="utf-8")
    # a holder + a waiter, the incident's minimum shape: fill the cap with two
    # holders first, so the third acquire is QUEUED at the head
    cc.acquire(KEY, "t-holder")
    cc.acquire(KEY, "t-second")
    cc.acquire(KEY, "t-waiter")  # queued behind limit=2 holders, FIFO head
    face = cc.read_state(KEY)
    ok([e.get("ticket") for e in face.get("queue") or []] == ["t-waiter"],
       "bench ready: t-waiter queued behind limit=%d holders" % LIMIT)

    # ---------- C1 cancel of a holder releases the slot in the same operation ----
    section("C1 named cancel of a holder: slot released, queue head promoted, reader agrees")
    h = FakeHandle(FakeDesc("RUNNING", project=KEY))
    client._connect = lambda: asyncio.sleep(0, result=FakeClient(h))
    os.environ[getattr(__import__("shared"), "CALLER_PROJECT_ENV")] = KEY
    _stub_snapshot_seam()
    out = _run(client.cmd_ticket_cancel(
        {"ticket_id": "t-holder", "who": "integration", "reason": "sc cleanup"}))
    res = out.get("result") if isinstance(out, dict) else None
    ok(isinstance(out, dict) and out.get("ok") is True,
       "cancel succeeds (ok receipt, no exception)")
    ok(bool(res) and res.get("terminated") is True, "receipt says terminated=true")
    rel = (res or {}).get("slot_released")
    ok(isinstance(rel, dict) and rel.get("released") is True,
       "receipt NAMES the slot release (slot_released.released=true)")
    ok(bool(rel) and rel.get("promoted") == "t-waiter",
       "queue head promoted in the same operation (promoted=t-waiter)")
    face = cc.read_state(KEY)
    ok("t-holder" not in holders_of(face),
       "READER-side face no longer lists the cancelled ticket (the panel view)")
    ok("t-waiter" in holders_of(face), "promoted waiter is now a holder reader-side")

    # ---------- C2 cancel of a non-holder: no-op release receipt, cancel fine ----
    section("C2 cancel of a ticket holding no slot: no-op release, never an error")
    cc.acquire(KEY, "t-third")  # refill a holder slot under the promoted waiter
    h2 = FakeHandle(FakeDesc("RUNNING", project=KEY))
    client._connect = lambda: asyncio.sleep(0, result=FakeClient(h2))
    out = _run(client.cmd_ticket_cancel(
        {"ticket_id": "t-ghost", "who": "integration", "reason": "no slot held"}))
    res = out.get("result") if isinstance(out, dict) else None
    ok(isinstance(out, dict) and out.get("ok") is True,
       "cancel of a non-holder still succeeds")
    rel = (res or {}).get("slot_released")
    ok(isinstance(rel, dict) and rel.get("released") is False,
       "release receipt is an honest no-op (released=false), not a fake true")

    # ---------- C3 already-terminal ticket: idempotent, ledger untouched ---------
    section("C3 already-terminal ticket: idempotent receipt, ledger untouched")
    before = holders_of(cc.read_state(KEY))
    h3 = FakeHandle(FakeDesc("COMPLETED", project=KEY))
    client._connect = lambda: asyncio.sleep(0, result=FakeClient(h3))
    out = _run(client.cmd_ticket_cancel(
        {"ticket_id": "t-second", "who": "integration", "reason": "already done"}))
    res = out.get("result") if isinstance(out, dict) else None
    ok(isinstance(out, dict) and out.get("ok") is True and
       (res or {}).get("already_terminal") is True,
       "already-terminal keeps the idempotent receipt")
    ok(holders_of(cc.read_state(KEY)) == before,
       "ledger untouched by the idempotent branch (no release fabricated)")

    # ---------- C4 ledger refuses: cancel succeeds, refusal is NAMED -------------
    section("C4 malformed ledger: cancel still succeeds, refusal named on the receipt")
    state_p = root / KEY / cc.STATE_FILE
    state_p.write_text("{not json at all", encoding="utf-8")
    h4 = FakeHandle(FakeDesc("RUNNING", project=KEY))
    client._connect = lambda: asyncio.sleep(0, result=FakeClient(h4))
    out = _run(client.cmd_ticket_cancel(
        {"ticket_id": "t-third", "who": "integration", "reason": "ledger broken"}))
    res = out.get("result") if isinstance(out, dict) else None
    ok(isinstance(out, dict) and out.get("ok") is True and
       (res or {}).get("terminated") is True,
       "cancel still succeeds when the ledger refuses (best-effort by contract)")
    rel = (res or {}).get("slot_released")
    ok(isinstance(rel, dict) and rel.get("released") is False and
       str(rel.get("reason") or "").strip(),
       "refusal is NAMED (slot_released.reason non-empty), never swallowed")

    print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
