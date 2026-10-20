# -*- coding: utf-8 -*-
"""t261019-31: terminal tickets keep their concurrency slot forever + the
over-limit state is never named (KI-01M533EHPA0AYQ2Y2GCNGXS4SD, plan
.sandbar/plan_t261019_31.md, review gen0 R1-R4 addressed).

Coverage:
- Piece 1 (client.py): the three slot-holding terminal entries (cmd_cancel,
  cmd_ticket_cancel, cmd_ticket_close_out) release the slot right after
  terminate succeeds — receipt names the release or names the refusal; a
  ledger refusal never fails the cancel; the already-terminal idempotent
  branch touches no ledger.
- Piece 2 (concurrency.py): the already-holding acquire refreshes `since`
  (holder heartbeat); the stale-holder sweep drops stale RUNNING holders by
  name and can promote the waiting head in the same call; a HUMAN-HOLD holder
  is NEVER swept at any age (review R1, ticket authority: "do not release a
  human-gate holder") and always counts toward at_work/room; fail-closed on
  an unprovable `since` within the running population; over_limit named on
  both read_state and the acquire refusal (root cause 2: never a silent 12/7).

Zero Temporal / zero network / zero git; declaration root injected into a
temp dir via SANDBAR_PROJECTS_DIR (test_t261004_32_concurrency bench pattern);
Temporal handles stubbed (test_t260922_10_cancel_entry FakeHandle pattern).
"""
import asyncio
import json
import time

import pytest

import client  # noqa: E402
import concurrency as cc  # noqa: E402
import shared  # noqa: E402


@pytest.fixture
def proj(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    key = "proj-alpha"
    (root / key).mkdir()
    return root, key


def _decl(root, key, value):
    (root / key / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": value}),
        encoding="utf-8")


def _holders(root, key):
    doc = json.loads((root / key / cc.STATE_FILE).read_text(encoding="utf-8"))
    return [h["ticket"] for h in doc["holders"]]


def _write_state(root, key, doc):
    (root / key / cc.STATE_FILE).write_text(
        json.dumps(doc), encoding="utf-8")


def _run(coro):
    return asyncio.run(coro)


def _res(r):
    """client receipts are wrapped {"ok": ..., "result": {...}} (+ gate keys)."""
    return r.get("result") if isinstance(r, dict) and "result" in r else r


# ---------- Fake Temporal faces (test_t260922_10_cancel_entry pattern) ----------

class FakeSearchAttrs:
    def __init__(self, project=""):
        self._p = project

    def get(self, key):
        return self._p


class FakeDesc:
    def __init__(self, status="RUNNING", project=""):
        self.status = type("ExecStatus", (), {"name": status})()
        self.typed_search_attributes = FakeSearchAttrs(project)


class FakeHandle:
    def __init__(self, status="RUNNING", project=""):
        self.status_name = status
        self.project = project
        self.terminated = False

    async def query(self, name):
        return {"meta": {"project": self.project or "proj-alpha"},
                "workflow_class": "DevLaneWorkflow",
                "template_id": "dev-lane", "refused": [], "authorizations": []}

    async def describe(self):
        return FakeDesc(self.status_name, self.project)

    async def signal(self, name, payload):
        pass

    async def terminate(self, reason=""):
        self.terminated = True


class FakeClient:
    def __init__(self, handle):
        self.handle = handle

    def get_workflow_handle(self, tid):
        return self.handle


def _patch_connect(monkeypatch, fake):
    monkeypatch.setattr(client, "_connect",
                        lambda: asyncio.sleep(0, result=fake))


# ---------- Piece 2: heartbeat + stale-holder sweep ----------

def test_acquire_on_already_holding_refreshes_heartbeat(proj):
    root, key = proj
    _decl(root, key, 3)
    cc.acquire(key, "t1")
    doc = json.loads((root / key / cc.STATE_FILE).read_text(encoding="utf-8"))
    old = doc["holders"][0]["since"]
    assert cc.acquire(key, "t1")["already_holding"] is True
    doc = json.loads((root / key / cc.STATE_FILE).read_text(encoding="utf-8"))
    assert doc["holders"][0]["since"] >= old


def test_stale_running_holder_swept_named_freed_next_poll(proj):
    """Ticket 29's main-green rule: acquire never grants on holders it is
    itself about to condemn. The sweep still drops + names the corpse; the
    freed slot serves the waiter on its NEXT poll (bounded by its backoff)."""
    root, key = proj
    _decl(root, key, 1)
    now = time.time()
    # Corpse holder + a live waiter already queued (the 261019 incident shape).
    _write_state(root, key, {
        "version": cc.STATE_VERSION,
        "holders": [{"ticket": "dead", "since": now - cc.HOLDER_STALE_S - 10,
                     "reason": cc.REASON_RUNNING}],
        "queue": [{"ticket": "waiter", "since": now}]})
    r = cc.acquire(key, "waiter")
    assert r["granted"] is False                    # no same-call jackpot
    assert r["dropped_stale_holders"] == ["dead"]   # but named, and really dropped
    assert _holders(root, key) == []
    r2 = cc.acquire(key, "waiter")                  # next poll: the slot is free
    assert r2["granted"] is True
    assert _holders(root, key) == ["waiter"]


def test_fresh_running_holder_never_swept(proj):
    root, key = proj
    _decl(root, key, 2)
    now = time.time()
    _write_state(root, key, {
        "version": cc.STATE_VERSION,
        "holders": [{"ticket": "alive", "since": now - 60,
                     "reason": cc.REASON_RUNNING}],
        "queue": []})
    r = cc.acquire(key, "t-new")
    assert r["granted"] is True             # 1 holder < limit 2 -> room
    assert r.get("dropped_stale_holders") == []
    assert "alive" in _holders(root, key)


def test_running_holder_unprovable_since_counts_stale(proj):
    root, key = proj
    _decl(root, key, 1)
    now = time.time()
    _write_state(root, key, {
        "version": cc.STATE_VERSION,
        "holders": [{"ticket": "corpse", "since": None,
                     "reason": cc.REASON_RUNNING}],
        "queue": [{"ticket": "waiter", "since": now}]})
    r = cc.acquire(key, "waiter")
    assert r["granted"] is False                    # room judged pre-sweep
    assert r["dropped_stale_holders"] == ["corpse"]
    assert cc.acquire(key, "waiter")["granted"] is True


def test_human_hold_holder_never_swept_even_past_window(proj):
    """Review R1 regression (the gen0 reject reason): a human-hold holder has no
    heartbeat by design; the sweep must never release it, whatever its age —
    and it must keep counting toward at_work/room."""
    root, key = proj
    _decl(root, key, 1)
    now = time.time()
    _write_state(root, key, {
        "version": cc.STATE_VERSION,
        "holders": [{"ticket": "gate-waiter",
                     "since": now - cc.HOLDER_STALE_S * 10,
                     "reason": cc.REASON_HUMAN_HOLD}],
        "queue": [{"ticket": "waiter", "since": now}]})
    r = cc.acquire(key, "waiter")
    assert r["granted"] is False
    assert r.get("dropped_stale_holders") == []
    assert _holders(root, key) == ["gate-waiter"]
    assert r["holders"] == 1
    face = cc.read_state(key)
    assert face["holders"][0]["ticket"] == "gate-waiter"


def test_human_hold_holder_malformed_since_also_exempt(proj):
    root, key = proj
    _decl(root, key, 1)
    _write_state(root, key, {
        "version": cc.STATE_VERSION,
        "holders": [{"ticket": "gate-waiter", "since": "not-a-number",
                     "reason": cc.REASON_HUMAN_HOLD}],
        "queue": [{"ticket": "waiter", "since": time.time()}]})
    r = cc.acquire(key, "waiter")
    assert r["granted"] is False
    assert r.get("dropped_stale_holders") == []
    assert _holders(root, key) == ["gate-waiter"]


# ---------- Piece 2: over_limit named on both faces ----------

def test_read_state_names_over_limit(proj):
    root, key = proj
    _decl(root, key, 1)
    now = time.time()
    _write_state(root, key, {
        "version": cc.STATE_VERSION,
        "holders": [{"ticket": "a", "since": now, "reason": cc.REASON_RUNNING},
                    {"ticket": "b", "since": now, "reason": cc.REASON_HUMAN_HOLD}],
        "queue": []})
    face = cc.read_state(key)
    assert face["limit"] == 1
    assert face["over_limit"] == {"limit": 1, "at_work": 2, "surplus": 1}


def test_read_state_over_limit_null_at_or_below_limit(proj):
    root, key = proj
    _decl(root, key, 2)
    cc.acquire(key, "a")
    face = cc.read_state(key)
    assert face["over_limit"] is None


def test_acquire_refusal_carries_over_limit(proj):
    root, key = proj
    _decl(root, key, 1)
    now = time.time()
    # Over-limit: one human-hold holder against a limit lowered to... none here —
    # make it truly over: two holders, limit 1.
    _write_state(root, key, {
        "version": cc.STATE_VERSION,
        "holders": [{"ticket": "gate-waiter", "since": now,
                     "reason": cc.REASON_HUMAN_HOLD},
                    {"ticket": "other", "since": now,
                     "reason": cc.REASON_RUNNING}],
        "queue": []})
    r = cc.acquire(key, "t-new")
    assert r["granted"] is False
    assert r["over_limit"] == {"limit": 1, "at_work": 2, "surplus": 1}
    # Full-but-legal (at_work == limit) is NOT over: the flag must be absent/null.
    _write_state(root, key, {
        "version": cc.STATE_VERSION,
        "holders": [{"ticket": "gate-waiter", "since": now,
                     "reason": cc.REASON_HUMAN_HOLD}],
        "queue": [{"ticket": "waiter", "since": now}]})
    r2 = cc.acquire(key, "waiter")
    assert r2["granted"] is False
    assert r2.get("over_limit") is None


# ---------- Piece 1: client.py terminal entries release the slot ----------

def test_ticket_cancel_releases_slot_and_promotes(proj, monkeypatch, tmp_path):
    root, key = proj
    _decl(root, key, 1)
    assert cc.acquire(key, "victim")["granted"] is True
    h = FakeHandle(project=key)
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(tmp_path / "admin.log"))
    monkeypatch.delenv(shared.CALLER_PROJECT_ENV, raising=False)
    res = _res(_run(client.cmd_ticket_cancel(
        {"ticket_id": "victim", "who": "ops", "reason": "cleanup",
         "caller_project": key})))
    assert res.get("terminated") is True
    slot = res.get("slot_released")
    assert slot is not None and slot.get("released") is True
    assert _holders(root, key) == []


def test_cancel_succeeds_even_when_ledger_refuses(proj, monkeypatch, tmp_path):
    root, key = proj
    _decl(root, key, 1)
    cc.acquire(key, "victim")
    # Corrupt the ledger: the release must refuse by name, the cancel must not.
    (root / key / cc.STATE_FILE).write_text("{not json", encoding="utf-8")
    h = FakeHandle(project=key)
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(tmp_path / "admin.log"))
    monkeypatch.delenv(shared.CALLER_PROJECT_ENV, raising=False)
    res = _res(_run(client.cmd_ticket_cancel(
        {"ticket_id": "victim", "who": "ops", "reason": "cleanup",
         "caller_project": key})))
    assert res.get("terminated") is True
    slot = res.get("slot_released")
    assert slot.get("released") is False
    assert "reconcile=true" in slot.get("reason", ""), \
        "the note must tell the operator how to repair the slot"


def test_ticket_cancel_already_terminal_touches_no_ledger(proj, monkeypatch, tmp_path):
    root, key = proj
    _decl(root, key, 1)
    assert cc.acquire(key, "holder")["granted"] is True
    h = FakeHandle(status="COMPLETED", project=key)
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(tmp_path / "admin.log"))
    monkeypatch.delenv(shared.CALLER_PROJECT_ENV, raising=False)
    res = _res(_run(client.cmd_ticket_cancel(
        {"ticket_id": "holder", "who": "ops", "reason": "r",
         "caller_project": key})))
    assert res.get("already_terminal") is True
    assert _holders(root, key) == ["holder"]
    assert "slot_released" not in res


def test_release_slot_after_cancel_missing_project_named_skip(proj):
    """Fail-visible, not fatal, never guessed: no project key -> named skip
    (main's t261019-40 contract: an unknown project must never free another
    project's slot)."""
    slot = client._release_slot_after_cancel("", "t1")
    assert slot == {"released": False, "reason": "project_unknown"}


def test_release_helper_human_gate_cause_refused_by_name(proj):
    """Rule 3 stays intact at the engine function the helper calls: the ledger
    refuses human-gate as a release cause — the helper only ever passes
    terminated, this pins the refusal wording exists."""
    root, key = proj
    _decl(root, key, 2)
    cc.acquire(key, "g")
    cc.renew(key, "g", cc.REASON_HUMAN_HOLD)
    with pytest.raises(ValueError) as e:
        cc.release(key, "g", cc.CAUSE_HUMAN_GATE)
    assert "human-gate" in str(e.value)
    assert _holders(root, key) == ["g"]
