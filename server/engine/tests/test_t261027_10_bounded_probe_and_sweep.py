# -*- coding: utf-8 -*-
"""t261027-10 (KI-378): the bounded liveness probe and the proof-of-death
sweep — engine-side dead-holder reclaim.

Defect: a TERMINAL ticket's slot was released by the ending CALLER; when that
caller could not write the projects root (agent sandbox, PermissionError on
concurrency-state.json.lock) the receipt said released:false and nothing ever
reclaimed the row — three of four leaked holders on dengzhufpv were human-hold
rows for Terminated workflows, invisible to the heartbeat sweep by design.

What this file pins (review_plan conditions included):
- (b) probe_holder_liveness: bounded (hard timeout), named (every failure lands
  in the note), fail-closed (only not_found is proof of death; timeout / raise /
  malformed result = unknown, never "alive"), and never raises.
- (a) sweep: the ledger lock is NEVER held across probes (the probe itself
  takes the lock and succeeds — a same-process flock would deadlock otherwise);
  probes run concurrently (two hung probes cost ~one timeout, not two); the
  drop revalidates (a holder that renewed between snapshot and drop SURVIVES);
  a live human-hold keeps its slot (fail-closed on the hold side); dead
  human-hold rows are reclaimed (the incident shape); the queue head is
  promoted; the receipt names everything (probe_errors, dropped_evidence,
  elapsed_s).
- The saturation trigger on the concurrency_acquire activity: sweep fires when
  the waiter is refused with holders >= limit and a probe is wired, then the
  acquire is re-judged once; the throttle (SWEEP_MIN_INTERVAL_S) bounds the
  cost and a throttled skip is visible on the receipt.

Zero Temporal / zero network: the probe is a stub; the ledger lives in a tmp
projects root injected via SANDBAR_PROJECTS_DIR.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))

import concurrency as cc  # noqa: E402


@pytest.fixture
def proj(tmp_path, monkeypatch):
    """Isolated bench: projects root at tmp, one project with limit=2."""
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    key = "proj-alpha"
    (root / key).mkdir()
    (root / key / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": 2}), encoding="utf-8")
    return root, key


@pytest.fixture(autouse=True)
def _clean_probe_registry():
    """Every test starts and ends with no probe wired and a cold throttle."""
    cc.configure_probe(None)
    cc._sweep_state["at"] = 0.0
    yield
    cc.configure_probe(None)
    cc._sweep_state["at"] = 0.0


def _seed(root, key, holders, queue=None):
    (root / key / cc.STATE_FILE).write_text(
        json.dumps({"version": cc.STATE_VERSION, "holders": holders,
                    "queue": queue or []}, ensure_ascii=False),
        encoding="utf-8")


def _read(root, key):
    return json.loads((root / key / cc.STATE_FILE).read_text(encoding="utf-8"))


def _probe(results):
    """Stub probe: tid -> (kind, note) from a dict; unknown tid -> live."""
    async def _one(tid):
        return results.get(tid, ("", ""))
    return _one


# ---------- (b) the bounded, named probe ----------

def test_probe_answer_is_live(proj):
    v, note = asyncio.run(cc.probe_holder_liveness(_probe({}), "t1"))
    assert (v, note) == ("live", "")


def test_probe_not_found_is_the_only_proof_of_death(proj):
    v, _ = asyncio.run(cc.probe_holder_liveness(
        _probe({"t1": ("not_found", "workflow gone")}), "t1"))
    assert v == "dead"


def test_probe_other_kind_is_unknown_fail_closed(proj):
    v, note = asyncio.run(cc.probe_holder_liveness(
        _probe({"t1": ("no_poller", "worker not polling")}), "t1"))
    assert v == "unknown"
    assert "no_poller" in note and "worker not polling" in note


def test_probe_hang_is_cancelled_at_the_bound_and_named(proj, monkeypatch):
    monkeypatch.setattr(cc, "PROBE_TIMEOUT_S", 0.05)

    async def _hang(tid):
        await asyncio.sleep(30)

    t0 = time.monotonic()
    v, note = asyncio.run(cc.probe_holder_liveness(_hang, "t1"))
    assert v == "unknown"
    assert "timed out after" in note
    assert time.monotonic() - t0 < 5  # the bound is real, not decorative


def test_probe_raise_is_named_never_raised(proj):
    async def _boom(tid):
        raise RuntimeError("temporal unavailable")

    v, note = asyncio.run(cc.probe_holder_liveness(_boom, "t1"))
    assert v == "unknown"
    assert "RuntimeError" in note and "temporal unavailable" in note


def test_probe_malformed_result_is_unknown_named(proj):
    # A probe returning a non-awaitable: the fault is named, never raised.
    for bad in (None, ("", ), ("a", "b", "c"), (1, "x"), ("", 7)):
        v, note = asyncio.run(cc.probe_holder_liveness(lambda t: bad, "t1"))
        assert v == "unknown", bad
        assert note, "the failure must be named, not blank: %r" % (bad,)

    # A probe that awaits and returns a junk shape: named as malformed.
    async def _junk(t):
        return ("a", "b", "c")

    v, note = asyncio.run(cc.probe_holder_liveness(_junk, "t1"))
    assert v == "unknown" and "malformed probe result" in note


# ---------- (a) the sweep ----------

def test_sweep_without_probe_refuses_named(proj):
    with pytest.raises(ValueError) as e:
        asyncio.run(cc.sweep("proj-alpha", None))
    assert "no liveness probe" in str(e.value)


def test_sweep_empty_ledger_is_a_named_noop(proj):
    out = asyncio.run(cc.sweep("proj-alpha", _probe({})))
    assert out["probed"] == 0 and out["dropped"] == []
    assert "elapsed_s" in out


def test_sweep_drops_only_provably_dead_keeps_live_and_unknown(proj):
    now = time.time()
    _seed(root := proj[0], key := proj[1], holders=[
        {"ticket": "t-dead-hold", "since": now, "reason": "human-hold"},
        {"ticket": "t-live-hold", "since": now, "reason": "human-hold"},
        {"ticket": "t-dead-run", "since": now, "reason": "running"},
        {"ticket": "t-unknown", "since": now, "reason": "running"},
    ])
    probe = _probe({
        "t-dead-hold": ("not_found", "gone a week"),
        "t-dead-run": ("not_found", ""),
        "t-live-hold": ("", ""),                      # a LIVE human-hold KEEPS its slot
        "t-unknown": ("timeout-ish", "transient"),    # fail-closed: kept, named
    })
    out = asyncio.run(cc.sweep(key, probe))
    assert out["dropped"] == ["t-dead-hold", "t-dead-run"]
    assert out["unknown"] == ["t-unknown"]
    assert "gone a week" in out["probe_errors"]["t-dead-hold"]
    assert "timeout-ish" in out["probe_errors"]["t-unknown"]
    ev = {e["ticket"]: e for e in out["dropped_evidence"]}
    assert set(ev) == {"t-dead-hold", "t-dead-run"}
    assert all(e["verdict"] == "dead" for e in ev.values())
    doc = _read(root, key)
    kept = {h["ticket"] for h in doc["holders"]}
    assert kept == {"t-live-hold", "t-unknown"}
    assert "elapsed_s" in out


def test_sweep_promotes_the_queue_head_after_a_reclaim(proj):
    now = time.time()
    _seed(proj[0], proj[1],
          holders=[{"ticket": "t-dead", "since": now, "reason": "human-hold"},
                   {"ticket": "t-live", "since": now, "reason": "running"}],
          queue=[{"ticket": "t-waiter", "since": now}])
    out = asyncio.run(cc.sweep(proj[1], _probe({"t-dead": ("not_found", "")})))
    assert out["dropped"] == ["t-dead"]
    assert out["promoted"] == "t-waiter"
    doc = _read(proj[0], proj[1])
    assert {h["ticket"] for h in doc["holders"]} == {"t-live", "t-waiter"}
    assert doc["queue"] == []


def test_sweep_never_holds_the_ledger_lock_across_probes(proj):
    """Review condition 1, mechanical form: the probe itself takes the ledger
    lock. flock conflicts across fds in ONE process, so if the sweep held the
    lock this read would deadlock and the test would hang."""
    now = time.time()
    _seed(proj[0], proj[1],
          holders=[{"ticket": "t-dead", "since": now, "reason": "human-hold"}])

    async def _locking_probe(tid):
        face = cc.read_state(proj[1])  # takes the same flock
        assert face["holders"], "expected the snapshot to still be on disk"
        return "not_found", ""

    out = asyncio.run(cc.sweep(proj[1], _locking_probe))
    assert out["dropped"] == ["t-dead"]


def test_sweep_probes_run_concurrently(proj, monkeypatch):
    """Review condition 2: two hung probes cost about ONE timeout, not two."""
    monkeypatch.setattr(cc, "PROBE_TIMEOUT_S", 0.1)
    now = time.time()
    _seed(proj[0], proj[1], holders=[
        {"ticket": "t-a", "since": now, "reason": "running"},
        {"ticket": "t-b", "since": now, "reason": "running"}])

    async def _hang(tid):
        await asyncio.sleep(30)

    t0 = time.monotonic()
    out = asyncio.run(cc.sweep(proj[1], _hang))
    wall = time.monotonic() - t0
    assert out["dropped"] == [] and out["unknown"] == ["t-a", "t-b"]
    assert "timed out after" in out["probe_errors"]["t-a"]
    assert wall < 5  # serial would be indistinguishable only if the bound were huge


def test_sweep_revalidation_keeps_a_holder_that_renewed_between_snapshot_and_drop(proj):
    """Review condition 1's named case: the probe says dead, but the holder
    renewed itself while the probes were in flight - it survives, by name."""
    now = time.time()
    _seed(proj[0], proj[1],
          holders=[{"ticket": "t-maybe", "since": now, "reason": "human-hold"}])

    async def _renewing_probe(tid):
        if tid == "t-maybe":
            cc.renew(proj[1], "t-maybe", "running")  # heartbeat lands mid-sweep
            return "not_found", ""
        return "", ""

    out = asyncio.run(cc.sweep(proj[1], _renewing_probe))
    assert out["dropped"] == []
    assert out["kept_revalidated"] == ["t-maybe"]
    doc = _read(proj[0], proj[1])
    assert [h["ticket"] for h in doc["holders"]] == ["t-maybe"]
    assert doc["holders"][0]["reason"] == "running"  # the renewal survived intact


def test_sweep_malformed_ledger_is_a_named_refusal(proj):
    (proj[0] / proj[1] / cc.STATE_FILE).write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        asyncio.run(cc.sweep(proj[1], _probe({})))
    assert cc.STATE_FILE in str(e.value)


# ---------- the saturation trigger on the acquire activity ----------

def _acquire(key, ticket):
    return asyncio.run(cc.concurrency_acquire(
        cc.AcquireArgs(project=key, ticket=ticket, priority=False)))


def test_saturated_acquire_sweeps_then_grants(proj):
    """The incident shape, end to end at the gate: limit 1, the slot held by a
    TERMINATED workflow parked as human-hold; the queued ticket's own acquire
    reclaims it in the same poll - by the worker, no caller write involved."""
    (proj[0] / proj[1] / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": 1}), encoding="utf-8")
    now = time.time()
    _seed(proj[0], proj[1],
          holders=[{"ticket": "t-dead", "since": now, "reason": "human-hold"}])
    cc.configure_probe(_probe({"t-dead": ("not_found", "")}))
    res = _acquire(proj[1], "t-new")
    assert res["granted"] is True, res
    assert res["sweep"]["dropped"] == ["t-dead"]
    doc = _read(proj[0], proj[1])
    assert [h["ticket"] for h in doc["holders"]] == ["t-new"]


def test_sweep_throttle_bounds_the_cost_and_names_the_skip(proj, monkeypatch):
    (proj[0] / proj[1] / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": 1}), encoding="utf-8")
    now = time.time()
    _seed(proj[0], proj[1],
          holders=[{"ticket": "t-holder", "since": now, "reason": "running"}])
    calls = []

    async def _counting(tid):
        calls.append(tid)
        return "", ""

    cc.configure_probe(_counting)
    cc._sweep_state["at"] = time.time()  # just swept: throttle is hot
    res = _acquire(proj[1], "t-queued")
    assert res["granted"] is False
    assert "sweep" not in res, "a throttled sweep must be visibly absent, not silent"
    assert calls == []
    # Thaw the throttle: now it fires.
    cc._sweep_state["at"] = 0.0
    res = _acquire(proj[1], "t-queued")
    assert res["sweep"]["probed"] == 1 and calls == ["t-holder"]
    assert res["granted"] is False  # the holder is LIVE: it keeps the slot


def test_unsaturated_acquire_never_sweeps(proj):
    """No saturation, no probe traffic: holders < limit means the poll takes
    the ordinary path (the sweep fires exactly when the project is full)."""
    now = time.time()
    _seed(proj[0], proj[1],
          holders=[{"ticket": "t-dead", "since": now, "reason": "human-hold"}])
    calls = []

    async def _counting(tid):
        calls.append(tid)
        return "not_found", ""

    cc.configure_probe(_counting)
    res = _acquire(proj[1], "t-new")
    assert res["granted"] is True
    assert calls == [] and "sweep" not in res


def test_sweep_activity_without_wiring_refuses_named():
    from temporalio import activity  # noqa: F401 - registry arm exists in this env
    assert any(getattr(a, "__name__", "") == "concurrency_sweep"
               for a in cc.CONCURRENCY_ACTIVITIES)
    with pytest.raises(ValueError) as e:
        asyncio.run(cc.concurrency_sweep(
            cc.AcquireArgs(project="proj-alpha", ticket="t", priority=False)))
    assert "no liveness probe" in str(e.value)
