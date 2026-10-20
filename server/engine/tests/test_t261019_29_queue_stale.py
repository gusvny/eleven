# -*- coding: utf-8 -*-
"""261019 measured starvation loop - the slot queue's two holes.

Incident (Temporal event histories are the authority): four queued tickets
(t261019-16/-18/-19/-27) were terminated by the SERVER with
`Workflow history count exceeds limit.` — each history stopped at ~51,200
events, built from 4,653 `concurrency_acquire` activities plus 4,653 timers
(the flat 5-second waiter re-poll, ~11 events per round, ~5 hours). Because
`acquire` puts the ticket in the queue and promotes out of it, each corpse's
promotion then parked a slot that nobody would ever release: five of seven
slots were held by dead tickets while nine live tickets queued for hours.

Coverage here (the activity-side truth; the workflow-side backoff is pinned
by the wiring test at the bottom):
- a queue entry's `since` is a HEARTBEAT: every poll refreshes it, so
  staleness is provable from the ledger alone;
- `_is_stale`: expired / missing / non-numeric heartbeat is stale
  (fail-closed: an entry that cannot prove it is alive never takes a slot);
- a dead head never blocks the queue: `acquire` prunes corpses ahead of the
  waiter and names them (`dropped_stale`);
- a live entry is never pruned, and pruning never touches the caller's own
  entry;
- `release` / `reconcile` promote the first LIVE head, never a corpse, and
  name what they dropped;
- the workflow side: dev_lane declares the backoff patch id and a capped
  poll ceiling, and the gate sleeps through the delay helper (a regression
  that reintroduces a flat sleep is red).

Zero Temporal / zero network / zero git; the declaration root is injected
into a temp dir via SANDBAR_PROJECTS_DIR.
"""
import json
import os
import re
import sys

import pytest

import concurrency as cc  # noqa: E402

DEV_LANE_PY = os.path.join(os.path.dirname(__file__), "..", "dev_lane.py")


@pytest.fixture
def proj(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    key = "proj-alpha"
    (root / key).mkdir()
    (root / key / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": 1}), encoding="utf-8")
    return root, key


def _state(root, key):
    return json.loads((root / key / cc.STATE_FILE).read_text(encoding="utf-8"))


def _seed(root, key, *, holders=(), queue=()):
    now = 1_700_000_000.0
    doc = {"version": 1,
           "holders": [{"ticket": t, "since": now, "reason": "running"}
                       for t in holders],
           "queue": [{"ticket": t, "since": since} for t, since in queue]}
    (root / key / cc.STATE_FILE).write_text(json.dumps(doc), encoding="utf-8")
    return doc


def _age(monkeypatch, seconds):
    """Pin the module clock so heartbeat arithmetic is exact."""
    base = 1_800_000_000.0
    monkeypatch.setattr(cc.time, "time", lambda: base + seconds)
    return base


# ---------- the predicate ----------

def test_heartbeat_expired_is_stale():
    entry = {"ticket": "x", "since": 100.0}
    assert cc._is_stale(entry, 100.0 + cc.QUEUE_STALE_S - 1) is False
    assert cc._is_stale(entry, 100.0 + cc.QUEUE_STALE_S + 1) is True


@pytest.mark.parametrize("entry", [{"ticket": "x"}, {"ticket": "x", "since": None},
                                   {"ticket": "x", "since": "not-a-number"},
                                   {"ticket": "x", "since": ""}])
def test_unprovable_heartbeat_is_stale_fail_closed(entry):
    assert cc._is_stale(entry, 5.0) is True


# ---------- acquire: heartbeat + corpse pruning ----------

def test_acquire_refreshes_the_waiters_heartbeat(proj, monkeypatch):
    root, key = proj
    _seed(root, key, holders=("holder",), queue=(("waiter", 1.0),))
    _age(monkeypatch, 60)
    r = cc.acquire(key, "waiter")
    assert r["granted"] is False and r["position"] == 1
    entry = next(e for e in _state(root, key)["queue"] if e["ticket"] == "waiter")
    assert entry["since"] == pytest.approx(1_800_000_060.0), \
        "each poll must refresh `since`, or staleness cannot be told apart"


def test_acquire_drops_corpse_heads_and_names_them(proj, monkeypatch):
    root, key = proj
    _seed(root, key, holders=("holder",),
          queue=(("corpse-a", 1.0), ("corpse-b", 2.0), ("waiter", 1_800_000_050.0)))
    _age(monkeypatch, 60)   # corpses are ~57 years old, the waiter is 10 s old
    r = cc.acquire(key, "waiter")
    assert r["granted"] is False
    assert r["position"] == 1, "the waiter is now the head: corpses were cleared"
    assert r["dropped_stale"] == ["corpse-a", "corpse-b"]
    assert [e["ticket"] for e in _state(root, key)["queue"]] == ["waiter"]


def test_acquire_never_prunes_the_callers_own_entry(proj, monkeypatch):
    root, key = proj
    _seed(root, key, holders=("holder",), queue=(("slow-elder", 1.0),))
    _age(monkeypatch, 60)
    # The caller's own entry is ancient too: it must be refreshed, not pruned.
    r = cc.acquire(key, "slow-elder")
    assert r["dropped_stale"] == []
    assert [e["ticket"] for e in _state(root, key)["queue"]] == ["slow-elder"]


def test_a_live_entry_ahead_is_kept(proj, monkeypatch):
    root, key = proj
    _seed(root, key, holders=("holder",),
          queue=(("live-head", 1_800_000_055.0), ("waiter", 1_800_000_055.0)))
    _age(monkeypatch, 60)
    r = cc.acquire(key, "waiter")
    assert r["dropped_stale"] == []
    assert r["position"] == 2
    assert [e["ticket"] for e in _state(root, key)["queue"]] == ["live-head", "waiter"]


# ---------- release / reconcile promote a live head only ----------

def test_release_skips_a_corpse_head_and_promotes_the_next_live_one(proj, monkeypatch):
    root, key = proj
    # Seeded directly (no acquire in between: acquire prunes corpses itself —
    # that is the sibling test above). Here the release path's own skip is
    # what stands between a dead head and a live slot.
    _seed(root, key, holders=("holder",),
          queue=(("corpse", 1.0), ("live-waiter", 1_800_000_055.0)))
    _age(monkeypatch, 60)
    r = cc.release(key, "holder", cause="terminated")
    assert r["dropped_stale"] == ["corpse"]
    assert r["promoted"] == "live-waiter"
    st = _state(root, key)
    assert [h["ticket"] for h in st["holders"]] == ["live-waiter"]
    assert st["queue"] == []


def test_release_promotes_nobody_when_every_waiter_is_dead(proj, monkeypatch):
    root, key = proj
    _seed(root, key, holders=("holder",), queue=(("corpse", 1.0),))
    _age(monkeypatch, 60)
    r = cc.release(key, "holder", cause="terminated")
    assert r["promoted"] is None
    assert r["dropped_stale"] == ["corpse"]
    st = _state(root, key)
    assert st["holders"] == [] and st["queue"] == []


def test_reconcile_promotes_a_live_head_only(proj, monkeypatch):
    root, key = proj
    _seed(root, key, holders=("zombie",),
          queue=(("corpse", 1.0), ("live-waiter", 1_800_000_055.0)))
    _age(monkeypatch, 60)
    r = cc.reconcile(key, alive_tickets=())
    assert r["dropped"] == ["zombie"]
    assert r["dropped_stale"] == ["corpse"]
    assert r["promoted"] == "live-waiter"


# ---------- the workflow side: bounded backoff, patch-guarded ----------

def test_dev_lane_declares_a_capped_backoff_behind_a_patch():
    src = open(DEV_LANE_PY, encoding="utf-8").read()
    assert "CONC_GATE_POLL_MAX" in src
    assert "CONC_GATE_BACKOFF_PATCH_ID" in src
    assert re.search(r'CONC_GATE_BACKOFF_PATCH_ID\s*=\s*"[^"]+"', src)
    assert "workflow.patched(self.CONC_GATE_BACKOFF_PATCH_ID)" in src, \
        "the backoff must be patch-guarded: histories recorded at the flat " \
        "5 s poll replay only if the duration decision is behind a marker"
    assert "await workflow.sleep(self._conc_gate_delay(polls))" in src, \
        "the gate must sleep through the helper; a flat sleep reintroduces " \
        "the history blow-up (~51,200 events in ~5 h)"
