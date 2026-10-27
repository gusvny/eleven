# -*- coding: utf-8 -*-
"""t261028-06 (KI-378): a terminal holder gives its slot back, and the repair
entry is bounded and names its refusal.

Measured defect: a ticket that ends while holding a concurrency slot leaves its
holder row in <projects>/<key>/concurrency-state.json forever (on project-vision 4
of 5 slots were held by workflows TERMINATED a week earlier), and the declared
repair entry `ticket.py op=concurrency reconcile=true` produced no output and no
state change for 4+ minutes (process alive, blocked on a socket, state file
byte-identical), so the operator hand-edited the JSON.

t261027-10 already landed the bounded ASYNC probe and the proof-of-death sweep
that the worker runs when an acquire is refused on a saturated project. The
gaps closed here are the ones that ticket named as debt:

(a) TERMINAL HOLDER RELEASES ITS SLOT. Chosen mechanism (one place): the
    READER-side proof-of-death verdict in the engine
    (`probe_holder_liveness` / `probe_holders_bounded` + `reconcile`). No new
    end-path release is invented — a workflow TERMINATED from outside runs no
    engine code, so only a reader-side judgement can reach it. `reconcile` now
    takes the PROVED-dead set explicitly (`dead_tickets`): only holders the
    probe proved gone lose their slot, and the drop is NAMED (dropped +
    dropped_evidence + probe_errors). Anything unprovable — a timeout, a probe
    fault, a holder that entered the ledger after the caller's snapshot — KEEPS
    its slot (fail-closed, the draining/unknown stance) and is named in
    kept_unclassified.

(b) RECONCILE IS BOUNDED AND NAMES ITS REFUSAL. `concurrency.probe_holders_bounded`
    runs every probe on its own daemon thread under ONE shared deadline, so N
    hung probes cost about one bound; a timeout is kind `timeout`, classified
    unknown (slot kept) and named in probe_errors; the receipt always comes
    back with probed / probe_timeout_s / probe_hung / elapsed_s / unknown /
    changed, and `changed` separates "nothing to reap" from "the reap worked".

Zero Temporal, zero network, zero git, no live projects store: the projects
root is a tmp dir injected via SANDBAR_PROJECTS_DIR, the engine-data dir (pidfile
/ meta) is a tmp dir, and the probe is a stub.
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))

import concurrency as cc  # noqa: E402

REPO = ENGINE.parent.parent
TICKET_PY = REPO / "server" / "tools" / "ticket.py"


@pytest.fixture
def proj(tmp_path, monkeypatch):
    """Isolated bench: projects root at tmp, one project with limit=3."""
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    key = "proj-alpha"
    (root / key).mkdir()
    (root / key / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": 3}), encoding="utf-8")
    return root, key, tmp_path


@pytest.fixture
def ticket_mod(monkeypatch, proj):
    """Load ticket.py by file path; its probe timeout is the engine constant,
    so the test patches that module's copy (ticket.py loads concurrency.py by
    file path: a second module object, same source)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ticket_mod_t261028_02",
                                                  str(TICKET_PY))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ticket_mod_t261028_02"] = mod
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(proj[2] / "admin.log"))
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_ENGINE_DATA_DIR", proj[2] / "data")
    return mod


def _holders(root, key):
    doc = json.loads((root / key / cc.STATE_FILE).read_text(encoding="utf-8"))
    return [h.get("ticket") for h in doc.get("holders") or []]


def _seed(root, key, holders, queue=None):
    (root / key / cc.STATE_FILE).write_text(
        json.dumps({"version": cc.STATE_VERSION, "holders": holders,
                    "queue": queue or []}, ensure_ascii=False), encoding="utf-8")


def _terminal(tid):
    return {"ticket": tid, "since": time.time(), "reason": "human-hold"}


# ---------- (a) the terminal-holder verdict ----------

def test_bounded_probe_classifies_terminal_holder_dead_and_names_it(proj):
    """The verdict table of the blocking driver: not_found is the ONLY proof of
    death; an answered probe is live; every other kind is unknown (kept)."""
    def probe(tid):
        return {"t-dead": ("not_found", "workflow gone (not_found)"),
                "t-live": ("", ""),
                "t-weird": ("no_poller", "workerd not polling")}[tid]

    out = cc.probe_holders_bounded(probe, ["t-dead", "t-live", "t-weird"], 5.0)
    res = out["results"]
    assert res["t-dead"]["verdict"] == "dead"
    assert res["t-dead"]["kind"] == "not_found"
    assert "workflow gone" in res["t-dead"]["note"]      # named, never bare
    assert res["t-live"]["verdict"] == "live"
    assert res["t-weird"]["verdict"] == "unknown"        # fail-closed
    assert "no_poller" in res["t-weird"]["kind"]
    assert out["hung"] == []


def test_bounded_probe_raise_and_malformed_are_unknown_named(proj):
    """A probe fault is classified, never raised: a broken probe cannot clear a
    slot, and the reader still learns which check failed."""
    def boom(tid):
        raise RuntimeError("temporal socket refused")

    out = cc.probe_holders_bounded(boom, ["t1"], 5.0)
    assert out["results"]["t1"]["verdict"] == "unknown"
    assert "RuntimeError" in out["results"]["t1"]["note"]
    assert "temporal socket refused" in out["results"]["t1"]["note"]

    for bad in (None, ("",), ("a", "b", "c"), (1, 2)):
        out = cc.probe_holders_bounded(lambda t, b=bad: b, ["t1"], 5.0)
        assert out["results"]["t1"]["verdict"] == "unknown", bad
        assert "malformed probe result" in out["results"]["t1"]["note"], bad


def test_reconcile_without_probe_refuses_named(proj):
    with pytest.raises(ValueError) as e:
        cc.probe_holders_bounded(None, ["t1"], 1.0)
    assert "no probe callable" in str(e.value)


def test_reconcile_drops_only_the_proved_dead_and_names_the_drop(proj):
    """Engine face of (a): the proof set decides. A proved-dead holder loses
    the slot and is named in `dropped`; a holder nobody classified (the ledger
    changed after the caller's snapshot) KEEPS its slot and is named in
    kept_unclassified — the fail-closed stance, applied to the repair entry."""
    root, key, _tmp = proj
    cc.acquire(key, "t-proved-dead")
    cc.acquire(key, "t-appeared-late")
    out = cc.reconcile(key, alive_tickets=[],
                       dead_tickets=["t-proved-dead"])
    assert out["dropped"] == ["t-proved-dead"]
    assert out["kept_unclassified"] == ["t-appeared-late"]
    assert _holders(root, key) == ["t-appeared-late"]
    assert any(h["ticket"] == "t-appeared-late"
               for h in cc.read_state(key)["holders"])


# ---------- (b) reconcile is bounded, names the refusal, always receipts ----------

def test_hung_probe_is_bounded_unknown_named_and_the_receipt_returns(
        proj, ticket_mod, monkeypatch):
    """The measured fault, pinned: a probe that never answers (a socket with no
    deadline) must not hold the command. The bound is real (seconds, not
    minutes), the verdict is unknown so the slot is KEPT, the reason is NAMED,
    and the receipt comes back with the honest `changed: False`."""
    root, key, _tmp = proj
    cc.acquire(key, "t-hung")
    conc = ticket_mod._concurrency_mod()
    monkeypatch.setattr(conc, "PROBE_TIMEOUT_S", 0.2)

    def hanging_poc(subcmd, payload, caller=None):
        time.sleep(30)          # a socket that never answers
        raise AssertionError("unreachable")

    monkeypatch.setattr(ticket_mod, "_poc", hanging_poc)
    t0 = time.monotonic()
    out = ticket_mod.run({"op": "concurrency", "project": key,
                          "reconcile": True})
    wall = time.monotonic() - t0

    assert wall < 10, "the probe bound must be real, not decorative (%.1fs)" % wall
    assert out["bounded"] is True
    assert out["probe_timeout_s"] == 0.2
    assert out["probe_hung"] == ["t-hung"]
    assert out["probed"] == 1
    # unprovable -> the slot is KEPT, fail-closed
    assert out["dropped"] == [] and out["dropped_evidence"] == []
    assert out["holders"] == 1
    assert out["unknown"] == ["t-hung"]
    assert out["changed"] is False           # never a silent "success"
    # and the refusal is NAMED, never a bare ticket id
    assert out["probe_errors"]["t-hung"].startswith("kept (timeout)")
    assert "timed out after" in out["probe_errors"]["t-hung"]
    assert _holders(root, key) == ["t-hung"]  # reader side: the row is still there


def test_two_hung_probes_cost_about_one_bound(proj, ticket_mod, monkeypatch):
    """The bound is shared, not per holder: otherwise N dead holders on a
    10-slot project would still be a minutes-scale block."""
    root, key, _tmp = proj
    for tid in ("t-h1", "t-h2", "t-h3"):
        cc.acquire(key, tid)
    conc = ticket_mod._concurrency_mod()
    monkeypatch.setattr(conc, "PROBE_TIMEOUT_S", 0.2)

    def hanging_poc(subcmd, payload, caller=None):
        time.sleep(30)

    monkeypatch.setattr(ticket_mod, "_poc", hanging_poc)
    t0 = time.monotonic()
    out = ticket_mod.run({"op": "concurrency", "project": key,
                          "reconcile": True})
    wall = time.monotonic() - t0
    assert wall < 10
    assert out["probed"] == 3 and out["probe_hung"] == ["t-h1", "t-h2", "t-h3"]
    assert out["dropped"] == [] and out["holders"] == 3
    assert out["changed"] is False


def test_spawned_query_is_killed_at_the_probe_bound(proj, ticket_mod,
                                                    monkeypatch):
    """Resource lifecycle of the bounded probe: the seam bound alone would leave
    the spawned query running until its generic 900 s bound — an orphaned child
    per probe, which is the very process the incident report saw blocked. The
    spawn bound is lowered to the probe bound for the batch, so the child is
    killed, and the generic bound is restored afterwards."""
    root, key, _tmp = proj
    cc.acquire(key, "t-hung")
    conc = ticket_mod._concurrency_mod()
    monkeypatch.setattr(conc, "PROBE_TIMEOUT_S", 0.2)
    seen = []

    class _Proc:
        stdout = '{"ok": false, "kind": "not_found", "error": "gone"}'
        stderr = ""

    def fake_run(cmd, **kwargs):
        seen.append(kwargs.get("timeout"))
        return _Proc()

    monkeypatch.setattr(ticket_mod.subprocess, "run", fake_run)
    out = ticket_mod.run({"op": "concurrency", "project": key,
                          "reconcile": True})
    assert seen == [0.2], seen                       # the child cannot outlive it
    assert ticket_mod._POC_TIMEOUT_S == 900          # restored for generic ops
    assert out["dropped"] == ["t-hung"]              # and the probe still worked


# ---------- (a) a dead holder IS reaped, by the repair entry ----------

def test_repair_entry_reaps_a_terminal_holder_and_promotes(proj, ticket_mod,
                                                           monkeypatch):
    """The project-vision shape driven through the declared repair entry: a
    TERMINATED workflow's human-hold row is proved gone (not_found), dropped by
    name with its evidence, the queue head takes the freed slot, and the next
    acquire is immediate — all reader-side, no caller write."""
    root, key, _tmp = proj
    _seed(root, key, holders=[_terminal("t-terminated-a-week-ago")],
          queue=[{"ticket": "t-waiter", "since": time.time()}])
    probed = []

    def fake_poc(subcmd, payload, caller=None):
        probed.append((subcmd, payload.get("workflow_id")))
        return {"ok": False, "kind": "not_found",
                "error": "workflow execution not found: %s"
                         % payload.get("workflow_id")}

    monkeypatch.setattr(ticket_mod, "_poc", fake_poc)
    out = ticket_mod.run({"op": "concurrency", "project": key,
                          "reconcile": True})

    assert probed == [("query", "t-terminated-a-week-ago")]  # read-only probe
    assert out["dropped"] == ["t-terminated-a-week-ago"]
    assert out["promoted"] == "t-waiter"
    assert out["changed"] is True
    assert out["unknown"] == [] and out["probe_hung"] == []
    # named with evidence — a dead holder is never a silent row removal
    (ev,) = out["dropped_evidence"]
    assert ev["ticket"] == "t-terminated-a-week-ago" and ev["probe"] == "not_found"
    assert out["probe_errors"]["t-terminated-a-week-ago"].startswith(
        "dead (kind=not_found)")
    # reader side: the row left the ledger and the freed slot is usable now
    assert _holders(root, key) == ["t-waiter"]
    assert cc.acquire(key, "t-next")["granted"] is True


def test_repair_entry_keeps_an_unprovable_holder_and_says_so(proj, ticket_mod,
                                                            monkeypatch):
    """Fail-closed half of (a), through the entry: a probe that fails to answer
    in a way that proves nothing (transient RPC) leaves the slot alone, names
    the holder, and reports that nothing changed."""
    root, key, _tmp = proj
    cc.acquire(key, "t-maybe-alive")

    def fake_poc(subcmd, payload, caller=None):
        return {"ok": False, "kind": "transient",
                "error": "query_timeout: the snapshot query timed out"}

    monkeypatch.setattr(ticket_mod, "_poc", fake_poc)
    out = ticket_mod.run({"op": "concurrency", "project": key,
                          "reconcile": True})
    assert out["dropped"] == [] and out["holders"] == 1
    assert out["changed"] is False
    assert out["probe_errors"]["t-maybe-alive"].startswith("kept (transient)")
    assert _holders(root, key) == ["t-maybe-alive"]
