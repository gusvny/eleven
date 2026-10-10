# -*- coding: utf-8 -*-
"""t261004-32 project concurrency limit (CL-1 engine half) - unit tests.

Coverage (ticket acceptance bar + review_plan conditional-pass items):
- Declaration matrix fail-closed (rule 9): absent / unreadable / malformed
  JSON / non-object / wrong version / missing limit key / 0 / 11 / "3" / null /
  false - each a named refusal quoting the declaration path; never a silent
  unlimited, never a default-3 fallback (review item 4);
- Boundaries: limit 1 and 10 accepted, "unlimited" accepted;
- Slot ledger: FIFO queue, over-limit refusal, position/waited_s readable
  (rule 8, read-only face);
- Slot lifetime ruling (review item 2): acquire on an already-holding ticket
  is immediate (already_holding); a human-gate renew (human-hold) keeps the
  holder count unchanged; post-signature re-acquire never re-queues (review
  item 3 regression bar); the queue head is promoted when a slot frees;
- Pause/terminal real release + idempotent double release; reorder must be a
  permutation of the current queue;
- Lowering the limit touches no holder (rule 5, only the next acquire);
- Malformed state file = named refusal (never treated as an empty ledger);
- reconcile: stale holders dropped by name + queue-head promotion (review
  item 5);
- Audit: record_limit_change refuses an empty by (KI-193);
- Mechanical wiring guard (review residual risk): both dev_lane and
  light_lane run() bodies open with the gate call - a missed wiring is red,
  never a silent bypass;
- ticket.py read face / reconcile face (_poc stub injected, zero Temporal).

Zero Temporal / zero network / zero git throughout; the declaration root is
injected into a temp dir via SANDBAR_PROJECTS_DIR.
"""
import json
import os
import sys

import pytest

import concurrency as cc  # noqa: E402
import shared  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TICKET_PY = os.path.join(REPO, "server", "tools", "ticket.py")
DEV_LANE_PY = os.path.join(os.path.dirname(__file__), "..", "dev_lane.py")
LIGHT_LANE_PY = os.path.join(os.path.dirname(__file__), "..", "light_lane.py")


@pytest.fixture
def proj(tmp_path, monkeypatch):
    """Isolated bench: declaration root at tmp + one project declared limit=2.
    Returns (root, key)."""
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    key = "proj-alpha"
    (root / key).mkdir()
    return root, key


def _decl(root, key, doc):
    p = root / key / cc.DECL_FILE
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _set_limit(root, key, value):
    return _decl(root, key, {"version": cc.DECL_VERSION, "limit": value})


# ---------- declaration matrix: fail-closed, named refusals (rule 9) ----------

def test_absent_declaration_named_refusal(proj):
    root, key = proj
    with pytest.raises(ValueError) as e:
        cc.load_limit(key)
    assert cc.DECL_FILE in str(e.value) and str(root / key) in str(e.value)


def test_unreadable_declaration_named_refusal(proj):
    root, key = proj
    p = root / key / cc.DECL_FILE
    p.write_bytes(b"\xff\xfe\x00\x01bad-utf8")
    with pytest.raises(ValueError) as e:
        cc.load_limit(key)
    assert cc.DECL_FILE in str(e.value)


@pytest.mark.parametrize("raw", ["{not json", "[]", '"a string"', "3"])
def test_malformed_declaration_named_refusal(proj, raw):
    root, key = proj
    (root / key / cc.DECL_FILE).write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError) as e:
        cc.load_limit(key)
    assert cc.DECL_FILE in str(e.value)


@pytest.mark.parametrize("doc", [
    {"version": 2, "limit": 3},
    {"limit": 3},                              # version missing
    {"version": 1},                            # limit missing (missing key != unlimited)
    {"version": 1, "limit": 0},
    {"version": 1, "limit": 11},
    {"version": 1, "limit": "3"},
    {"version": 1, "limit": None},
    {"version": 1, "limit": False},            # bool is an int subclass - must be named
    {"version": 1, "limit": 2.5},
])
def test_declaration_matrix_named_refusal(proj, doc):
    root, key = proj
    _decl(root, key, doc)
    with pytest.raises(ValueError) as e:
        cc.load_limit(key)
    assert cc.DECL_FILE in str(e.value)


@pytest.mark.parametrize("value,expect", [
    (1, 1), (10, 10), (3, 3), ("unlimited", None),
])
def test_declaration_boundaries_accepted(proj, value, expect):
    root, key = proj
    _set_limit(root, key, value)
    assert cc.load_limit(key) == expect


def test_empty_project_key_refuses():
    with pytest.raises(ValueError):
        cc.load_limit("")
    with pytest.raises(ValueError):
        cc.load_limit("../escape")


# ---------- slot ledger ----------

def test_fifo_queue_and_positions(proj):
    root, key = proj
    _set_limit(root, key, 1)
    assert cc.acquire(key, "t1")["granted"] is True
    r2 = cc.acquire(key, "t2")
    assert (r2["granted"], r2["position"]) == (False, 1)
    r3 = cc.acquire(key, "t3")
    assert (r3["granted"], r3["position"]) == (False, 2)
    face = cc.read_state(key)
    assert [e["ticket"] for e in face["queue"]] == ["t2", "t3"]
    assert face["queue"][0]["position"] == 1
    assert face["queue"][0]["waited_s"] >= 0
    # FIFO: on release the head is promoted; a later arrival cannot cut in
    out = cc.release(key, "t1", cc.CAUSE_TERMINATED)
    assert out["promoted"] == "t2"
    face = cc.read_state(key)
    assert [h["ticket"] for h in face["holders"]] == ["t2"]
    assert [e["ticket"] for e in face["queue"]] == ["t3"]
    assert face["queue"][0]["position"] == 1


def test_unlimited_admits_all(proj):
    root, key = proj
    _set_limit(root, key, "unlimited")
    for i in range(12):
        assert cc.acquire(key, "t%d" % i)["granted"] is True
    assert cc.read_state(key)["unlimited"] is True
    assert len(cc.read_state(key)["holders"]) == 12


def test_acquire_on_holder_immediate_no_window(proj):
    """Review items 2+3 ruling bar: slot lifetime = the whole lane run; a
    renewal opens no window and never re-queues."""
    root, key = proj
    _set_limit(root, key, 1)
    assert cc.acquire(key, "t1")["granted"] is True
    assert cc.acquire(key, "t2")["granted"] is False
    again = cc.acquire(key, "t1")
    assert again["granted"] is True and again["already_holding"] is True
    # The human gate eats the slot: after renew to human-hold the holder count
    # is unchanged and the queue does not move
    assert cc.renew(key, "t1", cc.REASON_HUMAN_HOLD) == {
        "renewed": True, "holding": True, "reason": cc.REASON_HUMAN_HOLD}
    assert len(cc.read_state(key)["holders"]) == 1
    # Post-signature continuation (no re-queue): the ticket is still the
    # holder and t2 is still the queue head
    assert cc.acquire(key, "t1")["already_holding"] is True
    assert cc.read_state(key)["queue"][0]["ticket"] == "t2"


def test_renew_non_holder_reports_not_holding(proj):
    root, key = proj
    _set_limit(root, key, 1)
    assert cc.renew(key, "ghost", cc.REASON_RUNNING) == {
        "renewed": False, "holding": False}


def test_renew_reason_vocabulary_refuses_other_values(proj):
    root, key = proj
    _set_limit(root, key, 1)
    with pytest.raises(ValueError):
        cc.renew(key, "t", "paused")  # pause is a real release (release()), not a renew word


def test_release_paused_and_idempotent(proj):
    root, key = proj
    _set_limit(root, key, 1)
    cc.acquire(key, "t1")
    cc.acquire(key, "t2")
    out = cc.release(key, "t1", cc.CAUSE_PAUSED)
    assert out["released"] is True and out["promoted"] == "t2"
    # Idempotent: releasing the same ticket again is a harmless receipt that
    # leaves the ledger untouched
    out2 = cc.release(key, "t1", cc.CAUSE_PAUSED)
    assert out2["released"] is False and out2["promoted"] is None
    assert len(cc.read_state(key)["holders"]) == 1


def test_release_cause_vocabulary_refuses(proj):
    root, key = proj
    _set_limit(root, key, 1)
    cc.acquire(key, "t1")
    with pytest.raises(ValueError):
        cc.release(key, "t1", "vibes")
    # Rule 3: the human gate eats the slot on purpose - human-gate is never a
    # real release word (regression bar for test-design defect #1: mis-wiring
    # rule 3 to release must refuse loudly, never silently drop the slot).
    with pytest.raises(ValueError) as e:
        cc.release(key, "t1", cc.CAUSE_HUMAN_GATE)
    assert "human-gate" in str(e.value) and "renew" in str(e.value)
    assert [h["ticket"] for h in cc.read_state(key)["holders"]] == ["t1"]


def test_release_removes_from_queue_too(proj):
    """A cancelled queued ticket must not keep its queue position (cancel
    means out of the queue)."""
    root, key = proj
    _set_limit(root, key, 1)
    cc.acquire(key, "t1")
    cc.acquire(key, "t2")
    cc.release(key, "t2", cc.CAUSE_TERMINATED)
    assert [e["ticket"] for e in cc.read_state(key)["queue"]] == []


def test_reorder_must_be_permutation(proj):
    root, key = proj
    _set_limit(root, key, 1)
    cc.acquire(key, "t1")
    cc.acquire(key, "t2")
    cc.acquire(key, "t3")
    with pytest.raises(ValueError):
        cc.reorder(key, ["t3"])
    with pytest.raises(ValueError):
        cc.reorder(key, ["t2", "t3", "ghost"])
    assert cc.reorder(key, ["t3", "t2"])["queue"] == ["t3", "t2"]
    cc.release(key, "t1", cc.CAUSE_TERMINATED)
    assert [h["ticket"] for h in cc.read_state(key)["holders"]] == ["t3"]


def test_priority_enters_queue_head_but_never_exceeds(proj):
    root, key = proj
    _set_limit(root, key, 1)
    cc.acquire(key, "t1")
    cc.acquire(key, "t2")
    assert cc.acquire(key, "period-1", priority=True)["position"] == 1
    assert cc.acquire(key, "t2")["position"] == 2  # an already-queued ticket is not displaced by priority
    assert cc.release(key, "t1", cc.CAUSE_TERMINATED)["promoted"] == "period-1"


def test_lowering_limit_never_touches_holders(proj):
    """Rule 5: lowering only affects the next acquire; holders stay byte-identical."""
    root, key = proj
    _set_limit(root, key, 3)
    for t in ("t1", "t2", "t3"):
        assert cc.acquire(key, t)["granted"] is True
    _set_limit(root, key, 1)
    face = cc.read_state(key)
    assert [h["ticket"] for h in face["holders"]] == ["t1", "t2", "t3"]
    r = cc.acquire(key, "t4")
    assert r["granted"] is False
    # After one release the held count is still above the lowered limit: the
    # queue keeps waiting for the next free slot
    cc.release(key, "t1", cc.CAUSE_TERMINATED)
    assert cc.acquire(key, "t4")["granted"] is False


def test_malformed_state_file_named_refusal(proj):
    root, key = proj
    _set_limit(root, key, 1)
    (root / key / cc.STATE_FILE).write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        cc.acquire(key, "t1")
    assert cc.STATE_FILE in str(e.value)
    with pytest.raises(ValueError):
        cc.read_state(key)
    (root / key / cc.STATE_FILE).write_text(
        json.dumps({"version": 99, "holders": "x", "queue": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        cc.release(key, "t1", cc.CAUSE_PAUSED)


def test_reconcile_drops_stale_named_and_promotes(proj):
    """Review item 5: a zombie holder killed mid-stage is cleared by reconcile
    with named output, and the queue head is promotable afterwards."""
    root, key = proj
    _set_limit(root, key, 1)
    cc.acquire(key, "t-dead")
    cc.acquire(key, "t-next")
    out = cc.reconcile(key, alive_tickets=[])
    assert out["dropped"] == ["t-dead"]
    assert out["promoted"] == "t-next"
    assert [h["ticket"] for h in cc.read_state(key)["holders"]] == ["t-next"]
    # A live holder is not mistakenly cleared
    cc.acquire(key, "t-alive")
    assert cc.reconcile(key, alive_tickets=["t-alive", "t-next"])["dropped"] == []


# ---------- audit (KI-193: by is never caller-asserted) ----------

def test_audit_refuses_empty_by(proj):
    root, key = proj
    _set_limit(root, key, 1)
    with pytest.raises(ValueError):
        cc.record_limit_change(key, "", 3, 5)
    row = cc.record_limit_change(key, "panel", 3, 5)
    assert row["by"] == "panel" and row["from"] == 3 and row["to"] == 5


# ---------- mechanical wiring guard (review residual risk: a missed wiring is red) ----------

def _run_head(path, lines=60):
    src = open(path, encoding="utf-8").read()
    heads = []
    idx = 0
    while True:
        idx = src.find("async def run(self, inp", idx)
        if idx < 0:
            break
        heads.append("".join(src[idx:idx + 4000].splitlines(True)[:lines]))
        idx += 1
    return heads


@pytest.mark.parametrize("lane_py", [DEV_LANE_PY, LIGHT_LANE_PY])
def test_every_run_body_opens_with_the_concurrence_gate(lane_py):
    """Both lanes' run() bodies must pass the slot gate before consuming any
    execute_activity - one unwired lane = that lane bypasses the limit
    entirely, which must be red."""
    heads = _run_head(lane_py)
    assert heads, "run() not found: %s" % lane_py
    for head in heads:
        gate = head.find("_concurrency_gate()")
        first_act = head.find("execute_activity(")
        assert gate >= 0 and (first_act < 0 or gate < first_act), (
            "run() body does not open with the concurrency slot gate: %s" % lane_py)


@pytest.mark.parametrize("lane_py", [DEV_LANE_PY, LIGHT_LANE_PY])
def test_release_points_wired(lane_py):
    src = open(lane_py, encoding="utf-8").read()
    assert "_concurrency_release_if_paused()" in src   # pause accounting
    assert "CAUSE_TERMINATED" in src                    # terminal accounting
    assert "CAUSE_HUMAN_GATE" in src                    # human-gate human-hold


# ---------- ticket.py read face / reconcile face ----------

@pytest.fixture()
def ticket_mod(monkeypatch, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("ticket_mod_t261004_32", TICKET_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ticket_mod_t261004_32"] = mod
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(tmp_path / "admin.log"))
    spec.loader.exec_module(mod)
    return mod


def test_ticket_concurrency_read_face(proj, ticket_mod):
    root, key = proj
    _set_limit(root, key, 2)
    cc.acquire(key, "t1")
    out = ticket_mod.run({"op": "concurrency", "project": key})
    assert out["limit"] == 2 and out["unlimited"] is False
    assert [h["ticket"] for h in out["holders"]] == ["t1"]
    assert out["decl"].endswith(cc.DECL_FILE)


def test_ticket_concurrency_requires_project(ticket_mod):
    with pytest.raises(ValueError):
        ticket_mod.run({"op": "concurrency"})


def test_ticket_concurrency_reconcile_uses_readonly_probe(proj, ticket_mod, monkeypatch):
    """reconcile probes liveness through a stubbed read-only client.py query:
    a holder whose probe answers kind=not_found (workflow gone) is a zombie,
    cleared by name with evidence; a query that succeeds is kept. Zero
    Temporal. (t261009-74: the stub carries the structured kind — free-text
    matching is not the classification anchor.)"""
    root, key = proj
    _set_limit(root, key, 1)
    cc.acquire(key, "t-dead")
    cc.acquire(key, "t-alive")
    probed = []

    def fake_poc(subcmd, payload, caller=None):
        probed.append((subcmd, payload.get("workflow_id")))
        if payload.get("workflow_id") == "t-dead":
            return {"ok": False, "error": "ticket does not exist: t-dead (no such workflow in Temporal)",
                    "kind": "not_found"}
        return {"ok": True, "result": {"ok": True, "snapshot": {}}}

    monkeypatch.setattr(ticket_mod, "_poc", fake_poc)
    out = ticket_mod.run({"op": "concurrency", "project": key, "reconcile": True})
    # Only holders are probed (a queued ticket holds no slot, nothing to clear);
    # with limit=1 t-alive is in the queue.
    assert [p[1] for p in probed] == ["t-dead"]
    assert all(p[0] == "query" for p in probed)          # read-only probe
    assert out["dropped"] == ["t-dead"]
    assert out["promoted"] == "t-alive"                  # head promoted after the clear
    assert out["probe_errors"]["t-dead"].startswith("dead (kind=not_found)")
    # t261009-74 spec (3): a dropped id never appears bare — evidence rides along.
    (drev,) = out["dropped_evidence"]
    assert drev["ticket"] == "t-dead"
    assert drev["probe"] == "not_found"
    assert drev["pidfile"] and drev["process"] in ("alive", "gone")


# ---------- shared / module face zero regression ----------

def test_declarations_live_in_perkey_root_not_repo(proj):
    """Rule 7: the declaration path lives under the machine-level per-key root,
    never in the repository's controlled config."""
    root, key = proj
    _set_limit(root, key, 1)
    p = cc.declaration_path(key)
    assert p.startswith(str(root))
    assert str(shared.REPO_ROOT) not in p or str(root) in p


def test_stdlib_only_loader_face_has_no_activities():
    """When ticket.py loads this module without temporalio: the activity
    registry is empty but the ledger face is complete. This test process has
    temporalio (engine venv), so only the shape contract is pinned here:
    CONCURRENCY_ACTIVITIES is a tuple of named callables."""
    names = [getattr(a, "__name__", "") for a in cc.CONCURRENCY_ACTIVITIES]
    assert names == ["concurrency_acquire", "concurrency_release",
                     "concurrency_renew"]
