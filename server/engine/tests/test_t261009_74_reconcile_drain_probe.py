# -*- coding: utf-8 -*-
"""t261009-74 reconcile liveness: draining is not dead (KI-01M4HMKZQ23649NFRTTFNCTRF6,
KI-01M4K9X2Z8W1A6CVB3QD7FHS4M).

Coverage (dispatch spec items 1-5, review_plan conditional items):
- THREE named verdicts: live / draining / dead, plus fail-closed `unknown`
  (spec 1, 4). Classification is keyed on the STRUCTURED kind of the probe
  receipt (client.py {ok,error,kind}), never on free-form error text (review
  comment 1); unknown kinds and transient errors keep the slot by design —
  asserted deliberately, not accidentally (review comment 2).
- A draining holder (pidfile live + meta state=draining, pids matching) KEEPS
  its slot and is named on the receipt; slot accounting counts it (spec 2).
- Every dropped id carries evidence {ticket, probe, pidfile, process} — no
  bare ids on the receipt (spec 3, review comment 3).
- Regression: a genuinely dead holder is still dropped and the queue head is
  promoted as before (spec 5).
- Malformed inputs (garbage pidfile, malformed meta JSON, missing files) never
  produce a drop (external-input discipline).

Zero Temporal / zero network / zero git; the declaration root and the
engine-data dir (pidfile/meta fixture home) are injected into tmp_path.
"""
import json
import os
import sys

import pytest

import concurrency as cc  # noqa: E402
import shared  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TICKET_PY = os.path.join(REPO, "server", "tools", "ticket.py")


@pytest.fixture
def proj(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    key = "proj-alpha"
    (root / key).mkdir()
    return root, key, tmp_path


def _decl(root, key, doc):
    p = root / key / cc.DECL_FILE
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _set_limit(root, key, value):
    return _decl(root, key, {"version": cc.DECL_VERSION, "limit": value})


@pytest.fixture
def ticket_mod(monkeypatch, tmp_path, proj):
    """Load ticket.py by file path; point its engine-data dir at tmp so the
    pidfile/meta fixtures never touch the real repo tree."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ticket_mod_t261009_74", TICKET_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ticket_mod_t261009_74"] = mod
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(tmp_path / "admin.log"))
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_ENGINE_DATA_DIR", tmp_path / "data")
    return mod


def _write_pidfile(tmp_path, tid, pid):
    d = tmp_path / "data"
    d.mkdir(exist_ok=True)
    (d / ("worker-%s.pid" % tid)).write_text(str(pid), encoding="utf-8")


def _write_meta(tmp_path, tid, state, pid):
    d = tmp_path / "data"
    d.mkdir(exist_ok=True)
    shared.write_worker_meta(str(d / ("worker-%s.pid.meta" % tid)),
                             pid=pid, state=state)


# ---------- engine face: draining keeps its slot, dead still drops ----------

def test_engine_reconcile_draining_keeps_slot_named(proj):
    root, key, _tmp = proj
    _set_limit(root, key, 2)
    cc.acquire(key, "t-live")
    cc.acquire(key, "t-drain")
    cc.acquire(key, "t-queued")          # over limit -> queued
    out = cc.reconcile(key, ["t-live"], ["t-drain"])
    assert out["dropped"] == []          # draining is NOT a zombie
    assert out["draining"] == ["t-drain"]  # named on the receipt (spec 2)
    assert out["holders"] == 2           # slot accounting counts the drainer
    assert out["promoted"] is None       # no room: the draining slot is a real slot
    assert [h["ticket"] for h in cc.read_state(key)["holders"]] == \
        ["t-live", "t-drain"]


def test_engine_reconcile_no_draining_arg_behavior_unchanged(proj):
    root, key, _tmp = proj
    _set_limit(root, key, 2)
    cc.acquire(key, "t-a")
    out = cc.reconcile(key, ["t-a"])
    assert out["dropped"] == [] and out["draining"] == []


def test_engine_reconcile_dead_still_dropped_and_promotes(proj):
    """Spec (5) regression: a dead holder is dropped and the queue head is
    promoted inside the same locked step, exactly as before."""
    root, key, _tmp = proj
    _set_limit(root, key, 1)
    cc.acquire(key, "t-dead")
    cc.acquire(key, "t-next")            # queued
    out = cc.reconcile(key, [], [])
    assert out["dropped"] == ["t-dead"]
    assert out["promoted"] == "t-next"
    assert out["draining"] == []
    assert out["holders"] == 1


def test_engine_reconcile_draining_in_alive_set_counts_once(proj):
    root, key, _tmp = proj
    _set_limit(root, key, 2)
    cc.acquire(key, "t-a")
    out = cc.reconcile(key, ["t-a"], ["t-a"])
    assert out["dropped"] == [] and out["draining"] == []
    assert out["holders"] == 1


# ---------- verdict matrix (pure, ticket.py side) ----------

def _ev(process="gone", pidfile="stale", meta="missing", meta_state="",
        meta_pid=None):
    return {"probe": "", "pidfile": pidfile, "process": process, "pid": 4242,
            "meta": meta, "meta_state": meta_state, "meta_pid": meta_pid}


VERDICT = None


@pytest.fixture
def verdict(ticket_mod):
    return ticket_mod._probe_verdict


def test_verdict_live_when_probe_answers(verdict):
    assert verdict("", _ev()) == "live"


def test_verdict_not_found_is_dead(verdict):
    assert verdict("not_found", _ev()) == "dead"


def test_verdict_no_poller_live_process_draining_meta(verdict):
    ev = _ev(process="alive", pidfile="live", meta="ok", meta_state="draining",
             meta_pid=4242)
    assert verdict("no_poller", ev) == "draining"


def test_verdict_no_poller_pid_mismatch_is_unknown(verdict):
    """pidfile points at a RECYCLED pid (the meta names a stranger): the
    evidence cannot prove our worker is the live process -> unknown, keep."""
    ev = _ev(process="alive", pidfile="live", meta="ok", meta_state="draining",
             meta_pid=999999)
    assert verdict("no_poller", ev) == "unknown"


def test_verdict_no_poller_process_gone_is_dead(verdict):
    assert verdict("no_poller", _ev(process="gone", pidfile="stale")) == "dead"
    assert verdict("no_poller", _ev(process="gone", pidfile="absent")) == "dead"


def test_verdict_no_poller_meta_serving_is_unknown(verdict):
    ev = _ev(process="alive", pidfile="live", meta="ok", meta_state="serving",
             meta_pid=4242)
    assert verdict("no_poller", ev) == "unknown"


def test_verdict_no_poller_meta_missing_or_malformed_is_unknown(verdict):
    for st in ("missing", "malformed", "read_error"):
        ev = _ev(process="alive", pidfile="live", meta=st)
        assert verdict("no_poller", ev) == "unknown", st


def test_verdict_unrecognized_kinds_never_drop(verdict):
    """Review comment 2, deliberate: transient RPC / internal / future kinds
    keep the slot. Fail-closed = do-not-drop-on-unknown."""
    for kind in ("transient", "internal", "cross_project_refused", "", "weird"):
        if kind == "":
            continue  # empty kind = answered = live, covered above
        assert verdict(kind, _ev()) == "unknown", kind


# ---------- ticket.py op face (stubbed probe, zero Temporal) ----------

def test_face_draining_holder_kept_and_named(proj, ticket_mod, monkeypatch):
    root, key, tmp = proj
    _set_limit(root, key, 2)
    cc.acquire(key, "t-drain")
    cc.acquire(key, "t-dead")
    _write_pidfile(tmp, "t-drain", os.getpid())
    _write_meta(tmp, "t-drain", "draining", os.getpid())

    def fake_poc(subcmd, payload, caller=None):
        assert subcmd == "query"
        tid = payload.get("workflow_id")
        if tid == "t-drain":
            return {"ok": False, "kind": "no_poller",
                    "error": "no_poller: queue ... has 0 live pollers"}
        return {"ok": False, "kind": "not_found",
                "error": "ticket does not exist: t-dead (no such workflow in Temporal)"}

    monkeypatch.setattr(ticket_mod, "_poc", fake_poc)
    out = ticket_mod.run({"op": "concurrency", "project": key, "reconcile": True})
    assert out["dropped"] == ["t-dead"]
    assert out["draining"] == ["t-drain"]          # named, kept (spec 2)
    assert out["holders"] == 1                     # the drainer's slot survives
    assert [h["ticket"] for h in cc.read_state(key)["holders"]] == ["t-drain"]
    assert "t-drain" not in out["probe_errors"]    # a healthy drain is not an error
    assert out["probe_errors"]["t-dead"].startswith("dead (kind=not_found)")
    # Spec (3): every dropped id carries its evidence — never a bare id.
    assert [e["ticket"] for e in out["dropped_evidence"]] == out["dropped"]
    (ev,) = out["dropped_evidence"]
    assert ev["probe"] == "not_found"
    assert ev["pidfile"] and ev["process"] in ("alive", "gone")


def test_face_transient_error_keeps_slot_and_names_it(proj, ticket_mod, monkeypatch):
    """The KI-01M4HMKZQ23649NFRTTFNCTRF6 shape: a momentarily unreachable probe
    must NOT drop a working ticket. Kept + named, nothing dropped."""
    root, key, _tmp = proj
    _set_limit(root, key, 2)
    cc.acquire(key, "t-working")

    def fake_poc(subcmd, payload, caller=None):
        return {"ok": False, "kind": "transient",
                "error": "query_timeout: the snapshot query timed out ..."}

    monkeypatch.setattr(ticket_mod, "_poc", fake_poc)
    out = ticket_mod.run({"op": "concurrency", "project": key, "reconcile": True})
    assert out["dropped"] == [] and out["dropped_evidence"] == []
    assert out["draining"] == []
    assert out["holders"] == 1                     # the working ticket keeps its slot
    assert out["probe_errors"]["t-working"].startswith("kept (transient)")


def test_face_spawn_failure_keeps_slot(proj, ticket_mod, monkeypatch):
    """_poc raising (temporal down, non-JSON) is unprovable -> keep."""
    root, key, _tmp = proj
    _set_limit(root, key, 2)
    cc.acquire(key, "t-w")

    def fake_poc(subcmd, payload, caller=None):
        raise ValueError("Temporal call failed (is temporal server/worker online? ...)")

    monkeypatch.setattr(ticket_mod, "_poc", fake_poc)
    out = ticket_mod.run({"op": "concurrency", "project": key, "reconcile": True})
    assert out["dropped"] == [] and out["holders"] == 1
    assert out["probe_errors"]["t-w"].startswith("kept (unknown)")


def test_face_malformed_pidfile_never_drops(proj, ticket_mod, monkeypatch):
    """External-input discipline: garbage pidfile content (and no meta) with a
    no_poller probe cannot prove death -> the holder keeps its slot."""
    root, key, tmp = proj
    _set_limit(root, key, 2)
    cc.acquire(key, "t-garbage")
    d = tmp / "data"
    d.mkdir(exist_ok=True)
    (d / "worker-t-garbage.pid").write_bytes(b"\xff\xfe not-a-pid \x00")

    def fake_poc(subcmd, payload, caller=None):
        return {"ok": False, "kind": "no_poller", "error": "no_poller: 0 live pollers"}

    monkeypatch.setattr(ticket_mod, "_poc", fake_poc)
    out = ticket_mod.run({"op": "concurrency", "project": key, "reconcile": True})
    assert out["dropped"] == [] and out["holders"] == 1
    assert out["probe_errors"]["t-garbage"].startswith("kept (no_poller)")


def test_face_malformed_meta_json_never_drops(proj, ticket_mod, monkeypatch):
    root, key, tmp = proj
    _set_limit(root, key, 2)
    cc.acquire(key, "t-badmeta")
    _write_pidfile(tmp, "t-badmeta", os.getpid())
    d = tmp / "data"
    (d / "worker-t-badmeta.pid.meta").write_text("{not json", encoding="utf-8")

    def fake_poc(subcmd, payload, caller=None):
        return {"ok": False, "kind": "no_poller", "error": "no_poller: 0 live pollers"}

    monkeypatch.setattr(ticket_mod, "_poc", fake_poc)
    out = ticket_mod.run({"op": "concurrency", "project": key, "reconcile": True})
    assert out["dropped"] == [] and out["holders"] == 1


def test_face_no_poller_and_process_gone_drops(proj, ticket_mod, monkeypatch):
    """The t261009-46 restart shape END state: once the worker process itself is
    gone (stale pidfile), no_poller + gone = a real zombie -> dropped, with
    evidence naming the dead process."""
    root, key, tmp = proj
    _set_limit(root, key, 2)
    cc.acquire(key, "t-zombie")
    _write_pidfile(tmp, "t-zombie", 2 ** 22)  # an (almost surely) dead pid

    def fake_poc(subcmd, payload, caller=None):
        return {"ok": False, "kind": "no_poller", "error": "no_poller: 0 live pollers"}

    monkeypatch.setattr(ticket_mod, "_poc", fake_poc)
    out = ticket_mod.run({"op": "concurrency", "project": key, "reconcile": True})
    assert out["dropped"] == ["t-zombie"]
    (ev,) = out["dropped_evidence"]
    assert ev["probe"] == "no_poller" and ev["process"] == "gone"
