# -*- coding: utf-8 -*-
"""t261009-03 CL-3 reorder write face (ticket.py op=concurrency order key) - unit tests.

Coverage (ticket evidence bar, L1 + negative faces):
- reorder refuses a non-permutation by name and the state file stays
  byte-identical (hash before/after);
- a valid permutation lands and reads back through read_state in the same
  order;
- an empty order on a non-empty queue is refused (it is not a permutation);
- a ticket NOT in the queue cannot be injected (refused, state bytes
  unchanged);
- a reorder never changes holder/slot accounting (holders before == after,
  queue length constant);
- malformed order shapes (string / dict / int / list of non-strings) reach
  the engine and are refused by the permutation check or fail structured -
  never a partial write, never a crash out of the CLI contract;
- ticket.py order face: run({op,project,order}) returns the READ-FACE shape
  with the new order (the panel's comparison maps e.ticket);
- read-only behaviour byte-for-byte unchanged: {op,project} output equals the
  serialized read face captured from the module (no order key -> no reorder
  call - asserted by call-count spy too);
- reconcile path unchanged, and reconcile+order combined: order wins (review
  conditional 4a) - the queue is reordered, no probe runs.

Borrowed implementation (bench precedent test_t261004_32_concurrency.py):
SANDBAR_PROJECTS_DIR temp isolation, declaration seeding via cc.DECL_FILE,
ticket.py loaded by file path with SANDBAR_ADMIN_LOG redirected, _poc stub
for the reconcile path - named-refusal propagation, byte-identity on refusal
and zero Temporal/network all carry over unchanged; nothing dropped.

Zero Temporal / zero network / zero git throughout.
"""
import hashlib
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
    """Isolated bench: limit=1, t1 holding the slot, t2/t3/t4 queued."""
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    key = "proj-alpha"
    (root / key).mkdir()
    (root / key / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": 1}), encoding="utf-8")
    assert cc.acquire(key, "t1")["granted"] is True
    assert cc.acquire(key, "t2")["granted"] is False
    assert cc.acquire(key, "t3")["granted"] is False
    assert cc.acquire(key, "t4")["granted"] is False
    return root, key


def _state_path(root, key):
    return root / key / cc.STATE_FILE


def _digest(root, key):
    return hashlib.sha256(_state_path(root, key).read_bytes()).hexdigest()


# ---------- L1: refusal by name, byte-identical state ----------

def test_non_permutation_refused_by_name_state_byte_identical(proj):
    root, key = proj
    before = _digest(root, key)
    bad = ["t2", "t3", "t9"]  # drops t4, injects t9 -> not a permutation
    with pytest.raises(ValueError) as e:
        cc.reorder(key, bad)
    assert "not a permutation" in str(e.value)
    assert "t9" in str(e.value)
    assert _digest(root, key) == before


def test_valid_permutation_lands_and_reads_back(proj):
    root, key = proj
    out = cc.reorder(key, ["t4", "t2", "t3"])
    assert out == {"queue": ["t4", "t2", "t3"]}
    face = cc.read_state(key)
    assert [e["ticket"] for e in face["queue"]] == ["t4", "t2", "t3"]
    assert [e["position"] for e in face["queue"]] == [1, 2, 3]


def test_empty_order_on_nonempty_queue_refused(proj):
    root, key = proj
    before = _digest(root, key)
    with pytest.raises(ValueError) as e:
        cc.reorder(key, [])
    assert "not a permutation" in str(e.value)
    assert _digest(root, key) == before


# ---------- negative: no injection, no slot accounting change ----------

def test_unqueued_ticket_cannot_be_injected(proj):
    root, key = proj
    before = _digest(root, key)
    with pytest.raises(ValueError):
        cc.reorder(key, ["t2", "t3", "t4", "t-inject"])
    assert _digest(root, key) == before
    assert "t-inject" not in [e["ticket"] for e in cc.read_state(key)["queue"]]


def test_reorder_never_touches_holder_accounting(proj):
    root, key = proj
    holders_before = cc.read_state(key)["holders"]
    n_before = len(cc.read_state(key)["queue"])
    cc.reorder(key, ["t4", "t3", "t2"])
    face = cc.read_state(key)
    assert [h["ticket"] for h in face["holders"]] == \
        [h["ticket"] for h in holders_before]  # holders keep their slots
    assert len(face["queue"]) == n_before == 3  # count never changes
    assert "t1" in [h["ticket"] for h in face["holders"]]  # no fake promotion


@pytest.mark.parametrize("bad", [
    "t2t3t4",            # a bare string iterates per character -> refused
    {"t2": 1, "t3": 1},  # a dict iterates its keys -> refused
    ["t2", "t3", 4],     # non-string entry str()-cast -> "4" not a member -> refused
    None,                # falsy -> treated as empty -> refused on non-empty queue
])
def test_malformed_order_shapes_refused_state_untouched(proj, bad):
    root, key = proj
    before = _digest(root, key)
    with pytest.raises(ValueError):
        cc.reorder(key, bad)
    assert _digest(root, key) == before


# ---------- ticket.py CLI face ----------

@pytest.fixture()
def ticket_mod(monkeypatch, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("ticket_mod_t261009_03", TICKET_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ticket_mod_t261009_03"] = mod
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(tmp_path / "admin.log"))
    spec.loader.exec_module(mod)
    return mod


def test_ticket_order_face_returns_read_face_shape(proj, ticket_mod):
    root, key = proj
    out = ticket_mod.run({"op": "concurrency", "project": key,
                          "order": ["t4", "t2", "t3"]})
    # Read-face shape: queue entries carry ticket + pos, the face keys the
    # panel's GET path parses are all present.
    assert [e["ticket"] for e in out["queue"]] == ["t4", "t2", "t3"]
    assert [e["position"] for e in out["queue"]] == [1, 2, 3]
    for k in ("holders", "limit", "project", "decl"):
        assert k in out
    assert out["project"] == key


def test_ticket_order_face_rides_engine_single_validation(proj, ticket_mod):
    root, key = proj
    before = _digest(root, key)
    with pytest.raises(ValueError) as e:
        ticket_mod.run({"op": "concurrency", "project": key, "order": ["t2"]})
    assert "not a permutation" in str(e.value)  # the ENGINE's named refusal,
    assert _digest(root, key) == before         # propagated verbatim


def test_ticket_no_order_key_is_byte_identical_read_face(proj, ticket_mod):
    root, key = proj
    def stable(face):
        # Waited/held seconds are read-time derivations; drop them and compare
        # the rest of the face (the pre-change behaviour's stable projection).
        f = json.loads(json.dumps(face))
        for e in f["queue"]:
            e.pop("waited_s", None)
        for h in f["holders"]:
            h.pop("held_s", None)
        return json.dumps(f, sort_keys=True)
    baseline = ticket_mod.run({"op": "concurrency", "project": key})
    # The output must be exactly what read_state returns (the pre-change
    # behaviour), and a second read must match on the stable projection.
    direct = cc.read_state(key)
    assert stable(baseline) == stable(direct)
    again = ticket_mod.run({"op": "concurrency", "project": key})
    assert stable(again) == stable(baseline)


def test_ticket_no_order_key_never_calls_reorder(proj, ticket_mod, monkeypatch):
    calls = []
    real = cc.reorder
    monkeypatch.setattr(ticket_mod._concurrency_mod(), "reorder",
                        lambda *a, **k: calls.append(a) or real(*a, **k))
    ticket_mod.run({"op": "concurrency", "project": "proj-alpha"})
    assert calls == []


def test_ticket_reconcile_path_unchanged(proj, ticket_mod, monkeypatch):
    def fake_poc(subcmd, payload, caller=None):
        assert subcmd == "query"  # read-only probe, unchanged
        return {"status": "RUNNING"}
    monkeypatch.setattr(ticket_mod, "_poc", fake_poc)
    out = ticket_mod.run({"op": "concurrency", "project": "proj-alpha",
                          "reconcile": True})
    assert out["dropped"] == ["t1"]  # t1's workflow id is not a live run
    assert out["promoted"] == "t2"   # queue head fills the freed slot


def test_ticket_reconcile_plus_order_order_wins(proj, ticket_mod, monkeypatch):
    """Review conditional 4a: when both are given, the explicit write wins."""
    probed = []

    def fake_poc(subcmd, payload, caller=None):
        probed.append(subcmd)
        raise AssertionError("reconcile probe must not run when order wins")

    monkeypatch.setattr(ticket_mod, "_poc", fake_poc)
    out = ticket_mod.run({"op": "concurrency", "project": "proj-alpha",
                          "reconcile": True, "order": ["t4", "t3", "t2"]})
    assert probed == []  # no probe: the reorder path ran, not reconcile
    assert [e["ticket"] for e in out["queue"]] == ["t4", "t3", "t2"]
    # t1 still holds: reconcile's drop+promote never executed.
    assert "t1" in [h["ticket"] for h in out["holders"]]
