# -*- coding: utf-8 -*-
"""t261031-26 (KI-441 / KI-443): a parked ticket must not hold a concurrency
slot, and a signed merge must not wait for one.

Measured fault this battery guards (261031, project limit 4): the holders were
t261030-35, t261031-14, t261031-17, t261031-20 - three of them blocked on work
that only an outside act could restart - while t261031-12 and t261031-06, both
human-signed and ready to merge, sat in the concurrency QUEUE for over half an
hour. The freeze that blocked two holders could only be lifted by a green line
round, and that round needed one of the queued merges to land: the queue was
waiting on itself.

Rules under test:
  (a) a ticket entering `blocked` / `awaiting-human` RELEASES its slot with its
      own truthful cause word (`blocked-wait`, never `paused` / `terminated`),
      named on the ledger face (`blocked_wait`: who, why, when, which stage) and
      on the ticket's own log;
  (b) leaving that state (retry_qc, rework, sign) re-acquires through the
      ORDINARY FIFO gate - the ticket queues behind the existing waiters and the
      acquire receipt names the parked wait it replaces;
  (c) the fail-closed stance is untouched: a holder whose liveness is unknown is
      never dropped, and a blocked-and-released ticket is NOT a zombie (it is not
      a holder, so `reconcile` can never report it in `dropped`);
  (d) the limit arithmetic counts only holders that can progress: a released
      park frees real capacity, and a MERGE CLAIM never eats a work slot;
  (e) a signed merge takes a MERGE CLAIM instead of an ordinary work slot
      (`concurrency.claim_merge`): visible on the ledger, never queued, never
      counted against the limit - so a signed merge can never starve behind work
      or a blocked holder;
  (f) replay discipline: both rules sit behind their own patch markers and the
      pre-marker command (a human-hold renew at a blocked stage, an ordinary
      `concurrency_acquire` after the merge signature) stays reachable, so a
      history recorded before them replays unchanged.

Harness: the UT-shell idiom of tests/test_t261022_merge_slot_release.py - no
Temporal runtime, no git, no network; the lane `workflow` facades are replaced
by recording stubs, and the ledger faces are driven through the public
concurrency API against a temporary projects root (`SANDBAR_PROJECTS_DIR`), so
the real `~/.sandbar` ledger is never touched.
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))

import base  # noqa: E402
import concurrency as cc  # noqa: E402
import dev_lane  # noqa: E402
import light_lane  # noqa: E402
from shared import Signature  # noqa: E402

DEV_LANE_PY = ENGINE / "dev_lane.py"
LIGHT_LANE_PY = ENGINE / "light_lane.py"

BLOCKED_PATCH = dev_lane.BLOCKED_SLOT_RELEASE_PATCH_ID
CLAIM_PATCH = dev_lane.MERGE_CLAIM_PATCH_ID
MERGE_PATCH = dev_lane.MERGE_SLOT_RELEASE_PATCH_ID

#: The concurrency command family this ticket's rules are stated in.
FAMILY = ("concurrency_acquire", "concurrency_release", "concurrency_renew",
          "concurrency_claim_merge", "concurrency_end_merge_claim",
          "prepare_human_gate", "merge")


class _Parked(Exception):
    """Sentinel: a wait point was reached (nothing after it is judged)."""


# ---------- recording workflow facade ----------

def _make_stub(patched, recorded, *, gate_receipt=None, release_receipt=None,
               merge_result=None, park=True, park_after=0):
    """Recording facade. `park=False` never parks (a directly driven helper);
    `park=True` parks at every wait point after the first `park_after` ones - the
    merge drive needs the merge gate's own wait to pass so the exit is recorded."""
    waits = {"n": 0}

    async def execute_activity(act, *a, **k):
        name = getattr(act, "__name__", str(act))
        arg = a[0] if a else None
        recorded.append((name, arg))
        if name == "concurrency_acquire":
            return dict(gate_receipt or {
                "granted": True, "already_holding": False, "reason": "",
                "position": 0, "limit": 4, "holders": 1, "waiting": 0,
                "reacquired_from": None})
        if name == "concurrency_release":
            cause = getattr(arg, "cause", "")
            return dict(release_receipt or {
                "released": True, "cause": cause, "promoted": None,
                "dropped_stale": [], "holders": 1, "waiting": 0,
                "parked": {"face": cause, "since": 1.0}})
        if name == "concurrency_renew":
            return {"renewed": True, "holding": True, "reason": "human-hold"}
        if name == "concurrency_claim_merge":
            return {"claimed": True, "already": False, "merge_claims": 1,
                    "dropped_stale": []}
        if name == "concurrency_end_merge_claim":
            return {"ended": True, "held_s": 1.5, "merge_claims": 0}
        if name == "prepare_human_gate":
            return SimpleNamespace(context_text="merge gate context")
        if name == "ui_evidence_decl":
            return {"mode": "absent", "dirs": [], "note": ""}
        if name == "bundle_out_ws_prefixes":
            return SimpleNamespace(prefixes=[], note="")
        if name == "merge":
            return dict(merge_result or {"ok": False, "action": "failed",
                                        "error": "merge_exec_fault",
                                        "reason": "merge_fault", "files": []})
        return {}

    async def wait_condition(_cond):
        waits["n"] += 1
        if park and waits["n"] > park_after:
            raise _Parked()
        return None

    def sleep(_):
        raise AssertionError("queue sleep reached: the gate was not granted")

    return SimpleNamespace(
        patched=patched,
        execute_activity=execute_activity,
        sleep=sleep,
        wait_condition=wait_condition,
        now=lambda: __import__("datetime").datetime(2026, 10, 31, 6, 0, 0),
        info=lambda: SimpleNamespace(start_time=None),
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None),
        upsert_memo=lambda *a, **k: None,
    )


def _patched_all_but(*false_ids):
    return lambda pid: pid not in false_ids


def _family(recorded):
    return [(name, getattr(arg, "cause", None), getattr(arg, "stage", None))
            for name, arg in recorded if name in FAMILY]


def _names(recorded):
    return [n for n, _c, _s in _family(recorded)]


def _bare_workflow(cls, project="proj-alpha", ticket="t261031ut"):
    """A lane workflow object built without __init__ (the UT-shell idiom): only
    the attributes the concurrency helpers and _blocked touch."""
    wf = object.__new__(cls)
    wf.ticket_id = ticket
    wf.meta = {"status": "dispatched", "log": [], "project": project,
               "stage_state": "running", "timeline": []}
    wf.timeline = []
    wf._gens = {}
    wf._retry_token = 0
    wf._rework = None
    wf._paused = False
    wf._detail_face_on = False
    wf._annex_requests = []
    wf.engine_version = 2
    return wf


def _notes(wf):
    return [row.get("note", "") for row in wf.meta.get("log", [])]


# =====================================================================
# (a) a parked state releases the slot, with its own truthful cause
# =====================================================================

@pytest.mark.parametrize("cls", [dev_lane.DevLaneWorkflow,
                                 light_lane.LightLaneWorkflow])
def test_a_blocked_stage_releases_its_slot_with_its_own_cause(monkeypatch, cls):
    recorded = []
    stub = _make_stub(_patched_all_but(), recorded, park=False)
    monkeypatch.setattr(dev_lane, "workflow", stub)
    monkeypatch.setattr(base, "workflow", stub)
    wf = _bare_workflow(cls)
    asyncio.run(wf._blocked("merge", "develop-buffer landing refused: line frozen"))
    fam = _family(recorded)
    names = [n for n, _c, _s in fam]
    assert "concurrency_release" in names, (
        "a blocked stage kept holding its slot: %r" % (names,))
    idx = names.index("concurrency_release")
    assert fam[idx][1] == "blocked-wait", (
        "the parked release must use its own cause word: %r" % (fam,))
    assert fam[idx][2] == "merge", (
        "the release receipt must name the stage it parked in: %r" % (fam,))
    assert "concurrency_renew" not in names, (
        "a parked ticket renewed a hold it must not keep: %r" % (names,))
    assert wf.meta.get("stage_state") == "blocked"


def test_the_parked_release_is_named_on_the_ticket_face(monkeypatch):
    recorded = []
    stub = _make_stub(_patched_all_but(), recorded, park=False)
    monkeypatch.setattr(dev_lane, "workflow", stub)
    monkeypatch.setattr(base, "workflow", stub)
    wf = _bare_workflow(dev_lane.DevLaneWorkflow)
    asyncio.run(wf._blocked("run_integration_tests", "engine fix pending"))
    hits = [n for n in _notes(wf) if "Blocked-wait accounting" in n]
    assert hits, "the release is not named on the ticket face: %r" % (_notes(wf)[-4:],)
    assert "slot released" in hits[0].lower(), hits[0]
    assert "run_integration_tests" in hits[0], (
        "the log line must say WHERE the ticket parked: %r" % (hits[0],))


def test_a_park_that_held_nothing_says_so_instead_of_claiming_a_release(monkeypatch):
    """Honest receipt: a ticket parked while holding no slot (for example one that
    already handed the slot back at the merge gate) must not log a release that
    never happened."""
    recorded = []
    stub = _make_stub(_patched_all_but(), recorded, park=False,
                      release_receipt={"released": False, "cause": "blocked-wait",
                                       "promoted": None, "dropped_stale": [],
                                       "holders": 1, "waiting": 0,
                                       "parked": None})
    monkeypatch.setattr(dev_lane, "workflow", stub)
    monkeypatch.setattr(base, "workflow", stub)
    wf = _bare_workflow(dev_lane.DevLaneWorkflow)
    asyncio.run(wf._blocked("merge", "merge did not close out"))
    hits = [n for n in _notes(wf) if "Blocked-wait accounting" in n]
    assert hits, _notes(wf)
    assert "no slot was held" in hits[0], hits[0]
    assert "released=" in hits[0], hits[0]


# =====================================================================
# (b) leaving the park re-acquires through the ordinary FIFO gate
# =====================================================================

def test_leaving_the_park_reacquires_through_the_fifo_queue(proj):
    root, key = proj
    _set_limit(root, key, 1)
    assert cc.acquire(key, "blocked-one")["granted"] is True
    out = cc.release(key, "blocked-one", cc.CAUSE_BLOCKED_WAIT, stage="merge")
    assert out["released"] is True
    assert out["parked"]["face"] == "blocked-wait"
    assert out["parked"]["stage"] == "merge"
    # The freed slot went to the waiter, not back to the parked ticket.
    assert cc.acquire(key, "waiter")["granted"] is True
    back = cc.acquire(key, "blocked-one")
    assert back["granted"] is False, (
        "the parked ticket jumped the queue on the way back: %r" % (back,))
    assert back["position"] == 1, back
    assert isinstance(back["reacquired_from"], dict), (
        "the re-acquire receipt must name the parked wait: %r" % (back,))
    assert back["reacquired_from"]["cause"] == "blocked-wait"
    assert back["reacquired_from"]["stage"] == "merge"
    # Taking the gate again ends the parked face (it is not a sticky marker).
    assert cc.read_state(key)["blocked_wait"] == []
    # The waiter releases; the ticket that left the park now holds normally.
    cc.release(key, "waiter", cc.CAUSE_TERMINATED)
    granted = cc.acquire(key, "blocked-one")
    assert granted["granted"] is True
    assert [h["ticket"] for h in cc.read_state(key)["holders"]] == ["blocked-one"]


def test_the_ticket_face_names_the_end_of_the_parked_wait(monkeypatch):
    """The re-acquire half is logged on the ticket's own face (who/why/when):
    the acquire receipt carries the release it replaces, and the gate prints it."""
    recorded = []
    stub = _make_stub(
        _patched_all_but(), recorded,
        gate_receipt={"granted": False, "already_holding": False,
                      "reason": "", "position": 2, "limit": 4, "holders": 4,
                      "waiting": 2,
                      "reacquired_from": {"cause": "blocked-wait",
                                          "since": time.time() - 600,
                                          "stage": "run_integration_tests"}},
        park=False)
    monkeypatch.setattr(dev_lane, "workflow", stub)
    monkeypatch.setattr(base, "workflow", stub)
    wf = _bare_workflow(dev_lane.DevLaneWorkflow)

    async def _no_sleep(_d):
        raise _Parked()

    stub.sleep = _no_sleep
    try:
        asyncio.run(wf._concurrency_gate())
    except _Parked:
        pass
    hits = [n for n in _notes(wf) if "the parked wait is over" in n]
    assert hits, "the re-acquire is not named on the ticket face: %r" % (_notes(wf),)
    assert "blocked-wait" in hits[0], hits[0]
    assert "run_integration_tests" in hits[0], hits[0]


def test_every_wake_reason_goes_through_the_ordinary_gate():
    """retry_qc, rework and every other wake converge on the phase-loop top, whose
    FIRST concurrency action is the ordinary gate - so a ticket that left a parked
    state takes its place in the queue instead of resuming with a slot."""
    for lane_py in (DEV_LANE_PY, LIGHT_LANE_PY):
        src = lane_py.read_text(encoding="utf-8")
        heads = []
        idx = 0
        while True:
            idx = src.find('while phase != "done":', idx)
            if idx < 0:
                break
            heads.append(src[idx:idx + 6000])
            idx += 1
        assert heads, "phase loop not found: %s" % lane_py
        for head in heads:
            gate_at = head.index("await self._concurrency_gate()")
            assert "_terminal_slot_release_if_pending()" in head
            assert "if self._rework is not None:" in head
            assert gate_at < head.index("if self._rework is not None:"), (
                "the loop consumes a rework before judging the slot: %s" % lane_py)


# =====================================================================
# (c) fail-closed stays: unknown liveness keeps the slot, a parked ticket
#     is never a zombie
# =====================================================================

def test_unknown_liveness_still_keeps_the_slot(proj):
    root, key = proj
    cc.acquire(key, "h1")
    cc.acquire(key, "h2")
    # Unknown: kept (fail-closed), named, never dropped.
    out = cc.reconcile(key, alive_tickets=[], unknown_tickets=["h1", "h2"])
    assert out["dropped"] == [], (
        "an unknown-liveness holder lost its slot: %r" % (out,))
    assert [h["ticket"] for h in cc.read_state(key)["holders"]] == ["h1", "h2"]
    # The proof form (dead_tickets given): a holder nobody proved dead is kept.
    out2 = cc.reconcile(key, alive_tickets=[], dead_tickets=["h1"])
    assert out2["dropped"] == ["h1"]
    assert [h["ticket"] for h in cc.read_state(key)["holders"]] == ["h2"], (
        "an unproved holder must keep its slot: %r" % (out2,))
    assert cc._classify_probe_kind("timeout") == "unknown"
    assert cc._classify_probe_kind("") == "live"
    assert cc._classify_probe_kind("not_found") == "dead"


def test_a_blocked_and_released_ticket_is_not_a_zombie(proj):
    root, key = proj
    cc.acquire(key, "parked")
    cc.release(key, "parked", cc.CAUSE_BLOCKED_WAIT, stage="merge")
    face = cc.read_state(key)
    assert face["holders"] == [], "the parked ticket still holds the slot: %r" % (face,)
    assert [e["ticket"] for e in face["blocked_wait"]] == ["parked"]
    # Reconcile can never report it as a dead HOLDER: it holds nothing.
    out = cc.reconcile(key, alive_tickets=["parked"], dead_tickets=[])
    assert out["dropped"] == [], (
        "a blocked-and-released ticket was reported as a dead holder: %r" % (out,))
    assert [e["ticket"] for e in cc.read_state(key)["blocked_wait"]] == ["parked"]
    # The legacy form prunes a parked ticket nobody could prove alive (parity
    # with the t261022 merge-wait face: not a second zombie channel).
    cc.reconcile(key, alive_tickets=[])
    assert cc.read_state(key)["blocked_wait"] == []


# =====================================================================
# (d) the limit counts only holders that can progress
# =====================================================================

def test_the_limit_counts_only_holders_that_can_progress(proj):
    root, key = proj
    _set_limit(root, key, 2)
    cc.acquire(key, "g1")
    cc.acquire(key, "g2")
    assert cc.acquire(key, "g3")["granted"] is False
    # One holder parks: real capacity comes back at once (the waiter is promoted
    # in the same locked step), and no over-limit reading appears.
    out = cc.release(key, "g1", cc.CAUSE_BLOCKED_WAIT,
                     stage="run_integration_tests")
    assert out["promoted"] == "g3", (
        "the parked slot did not reach the waiter: %r" % (out,))
    face = cc.read_state(key)
    assert [h["ticket"] for h in face["holders"]] == ["g2", "g3"]
    assert face["over_limit"] is None
    assert [e["ticket"] for e in face["blocked_wait"]] == ["g1"]
    # The limit still counts holders that CAN progress: both slots are in use, so
    # a further ticket waits instead of being admitted.
    assert cc.acquire(key, "g4")["granted"] is False
    assert cc.read_state(key)["over_limit"] is None


# =====================================================================
# (e) a signed merge consumes no work slot
# =====================================================================

def test_a_merge_claim_consumes_no_work_slot(proj):
    root, key = proj
    _set_limit(root, key, 1)
    cc.acquire(key, "worker")
    first = cc.claim_merge(key, "merger-1")
    assert first["claimed"] is True and first["already"] is False
    assert [h["ticket"] for h in cc.read_state(key)["holders"]] == ["worker"], (
        "the merge claim took a work slot: %r" % (cc.read_state(key),))
    # A second signed merge never queues behind the first: no capacity judgement.
    second = cc.claim_merge(key, "merger-2")
    assert second["claimed"] is True
    assert [e["ticket"] for e in cc.read_state(key)["merge_claims"]] == \
        ["merger-1", "merger-2"]
    # The claims do not eat the work limit either.
    assert cc.acquire(key, "another")["granted"] is False, (
        "the claim must not add capacity either - the worker still holds it")
    cc.release(key, "worker", cc.CAUSE_TERMINATED)
    assert cc.acquire(key, "another")["granted"] is True
    # Claim bookkeeping: idempotent take, idempotent end, and it is not a release.
    again = cc.claim_merge(key, "merger-1")
    assert again["already"] is True and again["merge_claims"] == 2
    ended = cc.end_merge_claim(key, "merger-1")
    assert ended["ended"] is True and ended["held_s"] >= 0.0
    assert ended["merge_claims"] == 1
    assert cc.end_merge_claim(key, "merger-1")["ended"] is False
    assert [e["ticket"] for e in cc.read_state(key)["merge_claims"]] == ["merger-2"]


def test_a_signed_merge_reaches_the_merge_step_without_a_work_slot(monkeypatch):
    """The measured starvation, at the lane level: the gate hands the slot back,
    the signature arrives, and the merge runs WITHOUT a work acquire in between."""
    recorded = []
    stub = _make_stub(_patched_all_but(), recorded, park=True, park_after=1)
    monkeypatch.setattr(dev_lane, "workflow", stub)
    monkeypatch.setattr(base, "workflow", stub)
    wf = _drive_merge(monkeypatch, stub)
    fam = _family(recorded)
    names = [n for n, _c, _s in fam]
    prep_at = names.index("prepare_human_gate")
    rel_at = names.index("concurrency_release", prep_at)
    assert fam[rel_at][1] == "merge-wait", fam
    claim_at = names.index("concurrency_claim_merge", rel_at)
    merge_at = names.index("merge", claim_at)
    assert rel_at < claim_at < merge_at, (
        "the merge step did not take its claim before merging: %r" % (names,))
    assert "concurrency_acquire" not in names[prep_at:], (
        "the signed merge waited for a work slot: %r" % (names,))
    end_at = names.index("concurrency_end_merge_claim", merge_at)
    assert end_at > merge_at, (
        "the merge claim outlived the merge activity: %r" % (names,))
    # The failed merge parks the ticket and releases whatever it held.
    blocked_at = names.index("concurrency_release", end_at)
    assert fam[blocked_at][1] == "blocked-wait", fam
    assert fam[blocked_at][2] == "merge", fam
    assert wf.meta.get("stage_state") == "blocked"


def test_the_merge_wait_face_stays_truthful_across_the_claim(proj):
    root, key = proj
    _set_limit(root, key, 1)
    cc.acquire(key, "gate-waiter")
    cc.release(key, "gate-waiter", cc.CAUSE_MERGE_WAIT)
    face = cc.read_state(key)
    assert [e["ticket"] for e in face["merge_wait"]] == ["gate-waiter"], (
        "a merge-waiting ticket must still be visible on that face: %r" % (face,))
    cc.claim_merge(key, "gate-waiter")
    face = cc.read_state(key)
    assert face["merge_wait"] == [], (
        "the signature wait ended, its face entry must go: %r" % (face,))
    assert [e["ticket"] for e in face["merge_claims"]] == ["gate-waiter"]


def test_a_stale_merge_claim_is_reclaimed_and_named(proj):
    root, key = proj
    cc.claim_merge(key, "dead-merger")
    path = root / key / cc.STATE_FILE
    doc = json.loads(path.read_text(encoding="utf-8"))
    for e in doc["merge_claims"]:
        e["since"] = time.time() - (cc.MERGE_CLAIM_STALE_S + 60)
    path.write_text(json.dumps(doc), encoding="utf-8")
    out = cc.claim_merge(key, "live-merger")
    assert out["dropped_stale"] == ["dead-merger"], (
        "a corpse claim must be dropped by name: %r" % (out,))
    assert [e["ticket"] for e in cc.read_state(key)["merge_claims"]] == \
        ["live-merger"]
    # A proved-dead holder's claim is pruned by reconcile as well.
    cc.reconcile(key, alive_tickets=[], dead_tickets=["live-merger"])
    assert cc.read_state(key)["merge_claims"] == []


# =====================================================================
# (f) replay discipline: the pre-marker command sequence is unchanged
# =====================================================================

def test_a_blocked_history_recorded_before_the_marker_still_renews(monkeypatch):
    recorded = []
    stub = _make_stub(_patched_all_but(BLOCKED_PATCH), recorded, park=False)
    monkeypatch.setattr(dev_lane, "workflow", stub)
    monkeypatch.setattr(base, "workflow", stub)
    wf = _bare_workflow(dev_lane.DevLaneWorkflow)
    asyncio.run(wf._blocked("run_integration_tests", "gate is red"))
    fam = _family(recorded)
    names = [n for n, _c, _s in fam]
    assert "concurrency_renew" in names, (
        "the pre-marker command disappeared: %r" % (names,))
    assert fam[names.index("concurrency_renew")][1] == "human-gate", fam
    assert "concurrency_release" not in names, (
        "an old history scheduled the NEW release command: %r" % (names,))


def test_a_merge_history_recorded_before_the_claim_marker_still_acquires(
        monkeypatch):
    recorded = []
    stub = _make_stub(_patched_all_but(CLAIM_PATCH), recorded, park=True,
                      park_after=1)
    monkeypatch.setattr(dev_lane, "workflow", stub)
    monkeypatch.setattr(base, "workflow", stub)
    _drive_merge(monkeypatch, stub)
    fam = _family(recorded)
    names = [n for n, _c, _s in fam]
    prep_at = names.index("prepare_human_gate")
    merge_at = names.index("merge")
    assert "concurrency_acquire" in names[prep_at:merge_at], (
        "the t261022 re-acquire the history recorded was skipped: %r" % (names,))
    assert "concurrency_claim_merge" not in names, (
        "an old history scheduled the NEW claim command: %r" % (names,))


def test_a_pre_cl1_history_schedules_no_concurrency_command(monkeypatch):
    recorded = []
    stub = _make_stub(lambda pid: False, recorded, park=False)
    monkeypatch.setattr(dev_lane, "workflow", stub)
    monkeypatch.setattr(base, "workflow", stub)
    wf = _bare_workflow(dev_lane.DevLaneWorkflow)
    asyncio.run(wf._blocked("merge", "line frozen"))
    assert [n for n, _c, _s in _family(recorded)] == [], (
        "a pre-CL-1 history replayed with concurrency commands: %r"
        % (recorded,))


def test_the_new_markers_are_single_sourced_and_guarded():
    """Source lock over both gated lane files: one definition per marker, both
    imported by the light lane, the blocked release behind its marker with the old
    renew branch reachable, and every merge gate exit taking the claim with the
    t261022 acquire retained as the fallback."""
    dev_src = DEV_LANE_PY.read_text(encoding="utf-8")
    light_src = LIGHT_LANE_PY.read_text(encoding="utf-8")
    assert dev_src.count(
        'BLOCKED_SLOT_RELEASE_PATCH_ID = "dev-lane-blocked-slot-release-v1"') == 1
    assert dev_src.count('MERGE_CLAIM_PATCH_ID = "dev-lane-merge-claim-v1"') == 1
    for marker in ("BLOCKED_SLOT_RELEASE_PATCH_ID,", "MERGE_CLAIM_PATCH_ID,"):
        assert marker in light_src, "the light lane must import %r" % marker
    # One blocked release site, and the old renew branch stays reachable there.
    assert dev_src.count("_concurrency_release(CAUSE_BLOCKED_WAIT") == 1
    blocked_head = dev_src[dev_src.index("async def _blocked(self, step_id"):]
    blocked_head = blocked_head[:blocked_head.index("self.meta[\"blocked_reason\"]")]
    assert "if workflow.patched(BLOCKED_SLOT_RELEASE_PATCH_ID):" in blocked_head
    assert "_concurrency_release(CAUSE_BLOCKED_WAIT" in blocked_head
    assert "await self._concurrency_renew(CAUSE_HUMAN_GATE)" in blocked_head
    # The honest-cause lock: the park never borrows another release word.
    assert "CAUSE_PAUSED" not in blocked_head and "CAUSE_TERMINATED" not in \
        blocked_head, "the parked release borrowed a cause that would be a lie"
    # Every merge exit: offer the claim, keep the recorded t261022 acquire.
    for lane_py in (DEV_LANE_PY, LIGHT_LANE_PY):
        src = lane_py.read_text(encoding="utf-8")
        pops = []
        idx = 0
        while True:
            idx = src.find('self._sigs.pop("merge")', idx)
            if idx < 0:
                break
            pops.append(idx)
            idx += 1
        assert pops, "no merge signature consume point: %s" % lane_py
        for pop_at in pops:
            # Window wide enough to hold the whole merge block (comments included);
            # the next signature consume point is asserted to lie outside it.
            block = src[pop_at:pop_at + 8000]
            assert 'self._sigs.pop("merge")' not in block[1:], (
                "the merge block window crossed into the next signature point: %s"
                % lane_py)
            claim_at = block.index("await self._concurrency_claim_merge()")
            guard_at = block.index("if workflow.patched(MERGE_CLAIM_PATCH_ID):")
            old_at = block.index("elif workflow.patched(MERGE_SLOT_RELEASE_PATCH_ID):")
            old_gate_at = block.index("await self._concurrency_gate()")
            assert guard_at < claim_at < old_at < old_gate_at, (
                "the merge exit is not claim-first with the t261022 branch kept: %s"
                % lane_py)
            merge_at = block.index("MergeArgs(")
            end_at = block.index("await self._concurrency_end_merge_claim()")
            assert claim_at < merge_at < end_at, (
                "the claim window is not exactly the merge activity: %s" % lane_py)


# =====================================================================
# the cause vocabulary (shape lock)
# =====================================================================

def test_the_blocked_wait_cause_is_its_own_word(proj):
    root, key = proj
    assert cc.CAUSE_BLOCKED_WAIT == "blocked-wait"
    assert cc.CAUSE_BLOCKED_WAIT not in (cc.CAUSE_PAUSED, cc.CAUSE_TERMINATED,
                                        cc.CAUSE_MERGE_WAIT, cc.CAUSE_HUMAN_GATE)
    assert cc.CAUSE_BLOCKED_WAIT != cc.REASON_HUMAN_HOLD
    cc.acquire(key, "p")
    # A pause is a pause: it must never record a blocked-wait park.
    cc.release(key, "p", cc.CAUSE_PAUSED)
    assert cc.read_state(key)["blocked_wait"] == []
    # The renew word is still refused as a release cause (rule unchanged).
    cc.acquire(key, "q")
    with pytest.raises(ValueError) as e:
        cc.release(key, "q", cc.CAUSE_HUMAN_GATE)
    assert "human-gate" in str(e.value) and "renew" in str(e.value)
    assert [h["ticket"] for h in cc.read_state(key)["holders"]] == ["q"]


# =====================================================================
# fixtures / drive helpers
# =====================================================================

@pytest.fixture()
def proj(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    key = "proj-alpha"
    (root / key).mkdir()
    (root / key / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": 3}), encoding="utf-8")
    return root, key


def _set_limit(root, key, value):
    (root / key / cc.DECL_FILE).write_text(
        json.dumps({"version": cc.DECL_VERSION, "limit": value}),
        encoding="utf-8")


def _inp():
    return SimpleNamespace(
        ticket_id="t261031ut", template_id="dev-lane", project="proj-alpha",
        title="ut", lane="", workspace="/tmp/wt", worktree="/tmp/wt",
        branch="lane/x", base_ref="main", proposal_id="", book_path="",
        epic="", acceptance_extra=None, repo_worktrees=None, project_root="",
        write_set=[], user_request="", spec="", body="", created=0,
        deliverables=[], lane_version="", develop_line_id="")


def _drive_merge(monkeypatch, stub):
    """Run the dev lane from phase "merge" with the signature already held, so the
    recorded stream covers gate entry, gate exit, the merge activity and the
    parked wait it lands in. The stub parks at the first wait_condition."""
    orig_init = dev_lane.DevLaneWorkflow._init

    def aimed_init(self, inp):
        orig_init(self, inp)
        self.meta["stage"] = "merge"
        self.meta["stage_state"] = "awaiting-human"
        self._sigs["merge"] = Signature(who="host", gate="merge",
                                        decision="approve", note="ok")

    async def no_prepare(_self):
        return None

    monkeypatch.setattr(dev_lane.DevLaneWorkflow, "_init", aimed_init)
    monkeypatch.setattr(dev_lane.DevLaneWorkflow, "_prepare_workspace_step",
                        no_prepare)
    wf = dev_lane.DevLaneWorkflow()
    try:
        asyncio.run(wf.run(_inp()))
    except _Parked:
        pass
    return wf
