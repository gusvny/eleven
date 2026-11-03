# -*- coding: utf-8 -*-
"""t261022 (host order 261022): a ticket waiting at the MERGE human gate
RELEASES its concurrency slot, and takes it back (ordinary FIFO) when it
leaves the gate.

Measured fault this ticket closes: a ticket parked at the merge gate kept its
slot for the whole signature wait, so seven merge-waiting tickets held all ten
slots for hours and the delivery line froze. Before t261022 the gate did an
atomic renew (`CAUSE_HUMAN_GATE` -> reason `human-hold`) and kept holding.

Rules under test:
  (a) entering the merge gate releases the slot with its OWN cause
      (`CAUSE_MERGE_WAIT` = "merge-wait"), named on the ticket log and on the
      ledger face (`merge_wait`) so the panel can tell a merge-wait release
      from a zombie holder;
  (b) leaving the gate (signature, rework, refused signature) needs the slot
      back before any further work. t261031-26 later narrowed this half: the
      SIGNATURE path now takes a MERGE CLAIM (no work slot, never queued, so a
      signed merge cannot starve) and only the pre-claim histories still replay
      the ordinary `_concurrency_gate()` FIFO acquire. Both branches are pinned
      below, because the replay contract is the older one;
  (c) every OTHER blocked stage was understood to keep its slot (rule 3). That
      half is SUPERSEDED by t261031-26 too: a blocked/awaiting-human ticket now
      releases with its own `blocked-wait` cause (measured 261031: three of four
      slots held by blocked tickets while two signed merges queued). The rule
      this file still owns is the REPLAY contract: a history recorded before the
      t261031-26 marker keeps the human-hold renew it recorded;
  (d) replay safety: the release sits behind `MERGE_SLOT_RELEASE_PATCH_ID` and
      the OLD renew call stays reachable as the else branch, so a history
      recorded before the marker schedules exactly the commands it always did
      (TMPRL1100 discipline — a parked merge-waiting ticket replays today).

Harness: the UT-shell idiom of tests/test_t261005_14_gate_replay_compat.py —
no Temporal runtime, the `workflow` facade of BOTH modules on the path
(dev_lane and base, which carries the pause gate and the event-ledger mixin)
is replaced by a recording stub, and `run()` is driven from phase "merge" to
the gate. Zero network, zero git, zero real activities.
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))

import base  # noqa: E402
import concurrency as cc  # noqa: E402
import dev_lane  # noqa: E402
import light_lane  # noqa: E402,F401  (source locks below read its file)
import shared  # noqa: E402
from shared import Signature  # noqa: E402

DEV_LANE_PY = ENGINE / "dev_lane.py"
LIGHT_LANE_PY = ENGINE / "light_lane.py"

#: Activity names that decide this ticket's behaviour; the ledger/prompt
#: activities in between are not asserted (their count is not this contract).
FAMILY = ("concurrency_acquire", "concurrency_release", "concurrency_renew",
          "prepare_human_gate", "merge")

MERGE_PATCH = dev_lane.MERGE_SLOT_RELEASE_PATCH_ID


class _Parked(Exception):
    """Sentinel: the merge gate reached its signature wait."""


class _StoppedAtMerge(Exception):
    """Sentinel: the merge activity was reached (nothing after it is judged)."""


# ---------- the recording workflow facade ----------

def _make_stub(patched, recorded, park):
    async def execute_activity(act, *a, **k):
        name = getattr(act, "__name__", str(act))
        recorded.append((name, a[0] if a else None))
        if name == "concurrency_acquire":
            return {"granted": True, "already_holding": False, "reason": "",
                    "position": 0, "limit": 10, "holders": 1, "waiting": 0}
        if name == "concurrency_release":
            return {"released": True, "cause": getattr(a[0], "cause", ""),
                    "promoted": None, "dropped_stale": [], "holders": 1,
                    "waiting": 0}
        if name == "concurrency_renew":
            return {"renewed": True, "holding": True, "reason": "human-hold"}
        if name == "prepare_human_gate":
            return SimpleNamespace(context_text="merge gate context")
        if name == "ui_evidence_decl":
            return {"mode": "absent", "dirs": [], "note": ""}
        if name == "bundle_out_ws_prefixes":
            return SimpleNamespace(prefixes=[], note="")
        if name == "merge":
            raise _StoppedAtMerge()
        return {}

    async def wait_condition(_cond):
        if park:
            raise _Parked()
        return None

    def sleep(_):
        raise AssertionError("queue sleep reached: the gate was not granted")

    return SimpleNamespace(
        patched=patched,
        execute_activity=execute_activity,
        sleep=sleep,
        wait_condition=wait_condition,
        now=lambda: __import__("datetime").datetime(2026, 10, 22, 9, 0, 0),
        info=lambda: SimpleNamespace(start_time=None),
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None),
        upsert_memo=lambda *a, **k: None,
    )


def _inp():
    """Minimal TicketInput: every attribute _init/run read on this path."""
    return SimpleNamespace(
        ticket_id="t261022ut", template_id="dev-lane", project="proj-alpha",
        title="ut", lane="", workspace="/tmp/wt", worktree="/tmp/wt",
        branch="lane/x", base_ref="main", proposal_id="", book_path="",
        epic="", acceptance_extra=None, repo_worktrees=None, project_root="",
        write_set=[], user_request="", spec="", body="", created=0,
        deliverables=[], lane_version="", develop_line_id="")


def _patched_all_but(*false_ids):
    return lambda pid: pid not in false_ids


def _drive_merge(monkeypatch, patched, park=False, seed_sig=True):
    """Run dev-lane from phase "merge" to the gate.

    park=True stops AT the signature wait (gate entry), park=False seeds the
    signature and stops at the merge activity (gate exit).
    """
    recorded = []
    stub = _make_stub(patched, recorded, park)
    monkeypatch.setattr(dev_lane, "workflow", stub)
    # base carries the pause gate and the event-ledger mixin used inside run().
    monkeypatch.setattr(base, "workflow", stub)

    orig_init = dev_lane.DevLaneWorkflow._init

    def aimed_init(self, inp):
        orig_init(self, inp)
        self.meta["stage"] = "merge"
        self.meta["stage_state"] = "awaiting-human"
        if seed_sig:
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
    except (_Parked, _StoppedAtMerge):
        pass
    return wf, recorded


def _family(recorded):
    """(name, cause) for the activities this contract is about."""
    return [(name, getattr(arg, "cause", None))
            for name, arg in recorded if name in FAMILY]


# ---------- (a) entering the merge gate releases with its own cause ----------

def test_entering_the_merge_gate_releases_the_slot_with_merge_wait(monkeypatch):
    wf, recorded = _drive_merge(monkeypatch, _patched_all_but(), park=True)
    fam = _family(recorded)
    names = [n for n, _ in fam]
    assert "concurrency_release" in names, (
        "the merge gate did not release the slot: %r" % (names,))
    idx = names.index("concurrency_release")
    assert fam[idx][1] == "merge-wait", (
        "the merge gate must release with its OWN cause word: %r" % (fam,))
    assert idx > names.index("prepare_human_gate"), (
        "the gate must be prepared first (the human reads the context): %r"
        % (names,))
    assert "merge" not in names, "the ticket is parked at the gate, not merging"
    assert "concurrency_renew" not in names, (
        "a merge-waiting ticket must not renew a hold it no longer has: %r"
        % (names,))
    assert wf.meta.get("stage_state") == "awaiting-human"


def test_the_ticket_face_logs_the_merge_wait_release(monkeypatch):
    wf, _recorded = _drive_merge(monkeypatch, _patched_all_but(), park=True)
    notes = [row.get("note", "") for row in wf.meta.get("log", [])]
    hits = [n for n in notes if "Merge-wait accounting" in n]
    assert hits, "the release is not named on the ticket face: %r" % (notes[-6:],)
    assert "slot released" in hits[0].lower(), hits[0]


# ---------- (b) leaving the gate re-acquires (never jumps the queue) ----------

def test_leaving_the_merge_gate_claims_the_merge_instead_of_a_work_slot(monkeypatch):
    """t261031-26 replaced the ordinary re-acquire with a MERGE CLAIM on the
    signature path (a signed merge queued behind work starved the whole project).
    What this file still owns: the gate hands the slot back, and the merge runs
    AFTER an accounting step that names itself - never silently slot-less."""
    wf, recorded = _drive_merge(monkeypatch, _patched_all_but(), park=False)
    names = [n for n, _a in recorded]
    assert "concurrency_release" in names, names
    idx_rel = names.index("concurrency_release")
    assert getattr(recorded[idx_rel][1], "cause", "") == "merge-wait", names
    assert "merge" in names, "the drive never reached the merge activity: %r" % (names,)
    idx_merge = names.index("merge")
    assert "concurrency_claim_merge" in names[idx_rel + 1:idx_merge], (
        "the ticket merged without taking its merge claim first: %r" % (names,))
    assert "concurrency_acquire" not in names[idx_rel + 1:idx_merge], (
        "a signed merge still waits for a work slot: %r" % (names,))
    assert wf.meta.get("stage_state") == "running"


def test_a_pre_claim_history_still_takes_the_ordinary_slot(monkeypatch):
    """The t261022 half stays pinned where it belongs: a history that recorded the
    FIFO acquire after the signature (marker absent) replays exactly that."""
    wf, recorded = _drive_merge(monkeypatch,
                                _patched_all_but(
                                    dev_lane.MERGE_CLAIM_PATCH_ID),
                                park=False)
    names = [n for n, _a in recorded]
    idx_rel = names.index("concurrency_release")
    idx_merge = names.index("merge")
    assert "concurrency_acquire" in names[idx_rel + 1:idx_merge], (
        "the recorded FIFO re-acquire disappeared: %r" % (names,))
    assert "concurrency_claim_merge" not in names, (
        "an old history scheduled the NEW claim activity: %r" % (names,))
    assert wf.meta.get("stage_state") == "running"


def test_the_rework_exit_requeues_at_the_main_loop_gate():
    """A rework leaving the merge gate goes back through the main loop, whose
    FIRST concurrency action is the ordinary gate — so the send-back takes its
    place in the queue instead of running on without a slot."""
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
            assert "await self._concurrency_gate()" in head, lane_py
            assert "if self._rework is not None:" in head, lane_py
            assert head.index("await self._concurrency_gate()") < \
                head.index("if self._rework is not None:"), (
                    "the loop consumes a rework BEFORE judging the slot: %s"
                    % lane_py)


# ---------- (c) every other blocked stage keeps holding its slot ----------

def _blocked_workflow():
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.ticket_id = "t261022ut"
    wf.meta = {"status": "dispatched", "log": [], "project": "proj-alpha",
               "stage_state": "running"}
    wf.timeline = []
    wf._gens = {}
    wf._retry_token = 0
    wf._rework = None
    wf._paused = False
    wf._detail_face_on = False
    wf._annex_requests = []
    wf.engine_version = 2
    return wf


def test_an_old_history_still_renews_the_blocked_hold(monkeypatch):
    """SUPERSEDED RULE, REPLAY HALF (t261031-26): the human-hold renew of a
    blocked stage is no longer the live rule, but a history recorded before the
    t261031-26 marker still replays it - so the branch must stay reachable."""
    recorded = []
    stub = _make_stub(_patched_all_but(dev_lane.BLOCKED_SLOT_RELEASE_PATCH_ID),
                      recorded, park=False)
    monkeypatch.setattr(dev_lane, "workflow", stub)
    monkeypatch.setattr(base, "workflow", stub)
    wf = _blocked_workflow()
    asyncio.run(wf._blocked("run_integration_tests", "gate is red"))
    fam = _family(recorded)
    names = [n for n, _ in fam]
    assert "concurrency_renew" in names, (
        "the pre-t261031-26 command disappeared: %r" % (names,))
    assert fam[names.index("concurrency_renew")][1] == "human-gate", fam
    assert "concurrency_release" not in names, (
        "an old history scheduled the NEW release command: %r" % (names,))


def test_merge_wait_is_used_by_the_merge_gate_only():
    """The named cause is wired at exactly the merge gate sites: one release per
    gate block and nowhere else (no other blocked stage can start leaking), and
    the marker is single-sourced (defined once, imported by the other lane)."""
    dev_src = DEV_LANE_PY.read_text(encoding="utf-8")
    light_src = LIGHT_LANE_PY.read_text(encoding="utf-8")
    assert dev_src.count('MERGE_SLOT_RELEASE_PATCH_ID = "dev-lane-merge-slot-release-v1"') == 1, (
        "the merge-slot marker must be defined exactly once (light_lane imports it)")
    assert "MERGE_SLOT_RELEASE_PATCH_ID," in light_src, (
        "the light lane must import the one marker")
    for lane_py, expected in ((DEV_LANE_PY, 2), (LIGHT_LANE_PY, 1)):
        src = lane_py.read_text(encoding="utf-8")
        assert src.count("_concurrency_release(CAUSE_MERGE_WAIT)") == expected, (
            "%s: the merge-wait release must sit at every merge gate block and "
            "only there" % lane_py.name)
    # Rule 3 sites are untouched: the blocked-stage renew still asks for
    # CAUSE_HUMAN_GATE (dev-lane blocked wait + quickmanual parked work stage).
    assert dev_src.count("await self._concurrency_renew(CAUSE_HUMAN_GATE)") >= 3, (
        "the blocked-stage holds must still renew with the human-gate cause")


# ---------- (d) old histories replay unchanged ----------

def test_a_history_recorded_before_the_marker_keeps_the_old_commands(monkeypatch):
    """In-flight replay: the concurrency gate family is active (post CL-1) but
    the merge-slot marker is absent — the gate must take the OLD renew branch and
    must not schedule the new acquire (any divergence here is TMPRL1100)."""
    wf, recorded = _drive_merge(monkeypatch,
                                _patched_all_but(MERGE_PATCH), park=False)
    fam = _family(recorded)
    names = [n for n, _ in fam]
    assert "concurrency_renew" in names, (
        "the old history's renew disappeared: %r — the else branch must stay "
        "reachable" % (names,))
    assert fam[names.index("concurrency_renew")][1] == "human-gate", fam
    assert "concurrency_release" not in names, (
        "an old history scheduled the NEW release command: %r" % (names,))
    idx_prep = names.index("prepare_human_gate")
    assert "concurrency_acquire" not in names[idx_prep:], (
        "an old history scheduled the NEW re-acquire before the merge: %r"
        % (names,))


def test_a_pre_cl1_history_schedules_no_concurrency_command_at_all(monkeypatch):
    _wf, recorded = _drive_merge(monkeypatch, lambda pid: False, park=False)
    names = [n for n, _ in recorded]
    assert [n for n in names if n in FAMILY] == ["prepare_human_gate", "merge"], (
        "a pre-CL-1 history replayed with concurrency commands: %r" % (names,))


def test_every_merge_gate_block_is_patch_guarded_and_reacquires():
    """One source lock per acceptance rule, over all three lane files: the merge
    gate block carries the patched release + the reachable old renew branch, and
    the gate exit calls the ordinary gate before the merge activity."""
    for lane_py in (DEV_LANE_PY, LIGHT_LANE_PY):
        src = lane_py.read_text(encoding="utf-8")
        heads = []
        idx = 0
        while True:
            idx = src.find('HumanGatePrep(ticket_id=self.ticket_id, stage_id="merge"',
                           idx)
            if idx < 0:
                break
            heads.append(src[idx:idx + 4000])
            idx += 1
        assert heads, "merge gate block not found: %s" % lane_py
        for head in heads:
            assert "if workflow.patched(MERGE_SLOT_RELEASE_PATCH_ID):" in head, \
                lane_py
            gate_guard = head.index(
                "if workflow.patched(MERGE_SLOT_RELEASE_PATCH_ID):")
            release_at = head.index("await self._concurrency_release(CAUSE_MERGE_WAIT)")
            renew_at = head.index("await self._concurrency_renew(CAUSE_HUMAN_GATE)")
            assert gate_guard < release_at and release_at < renew_at, (
                "the merge gate release is not behind the marker with the old "
                "renew branch kept reachable: %s" % lane_py)
        # Gate exit: the ordinary gate is judged before the merge activity.
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
            merge_at = src.find("MergeArgs(", pop_at)
            assert merge_at > pop_at, lane_py
            # t261031-26: the live path takes the merge claim; the t261022 FIFO
            # acquire stays reachable as the fallback for recorded histories.
            claim_at = src.find("await self._concurrency_claim_merge()", pop_at)
            gate_at = src.find("await self._concurrency_gate()", pop_at)
            assert pop_at < claim_at < merge_at, (
                "the gate exit does not take its merge claim before merging: %s"
                % lane_py)
            assert pop_at < gate_at < merge_at, (
                "the t261022 fallback acquire is no longer reachable: %s" % lane_py)


# ---------- the ledger face (why this is not a zombie channel) ----------

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


def test_the_ledger_names_the_merge_wait_and_clears_it_on_reacquire(proj):
    root, key = proj
    cc.acquire(key, "g1")
    out = cc.release(key, "g1", cc.CAUSE_MERGE_WAIT)
    assert out["released"] is True and out["cause"] == "merge-wait"
    face = cc.read_state(key)
    assert [h["ticket"] for h in face["holders"]] == [], (
        "the merge gate kept the slot: %r" % (face["holders"],))
    assert [e["ticket"] for e in face["merge_wait"]] == ["g1"], (
        "the ledger does not record the merge-wait release: %r" % (face,))
    # Taking the gate again drops the face entry (it is not a sticky marker).
    back = cc.acquire(key, "g1")
    assert back["granted"] is True
    assert cc.read_state(key)["merge_wait"] == []


def test_a_merge_wait_release_never_jumps_the_queue(proj):
    root, key = proj
    _set_limit(root, key, 1)
    cc.acquire(key, "holder")          # A
    cc.acquire(key, "b-waiter")        # queued 1
    cc.acquire(key, "c-waiter")        # queued 2
    out = cc.release(key, "holder", cc.CAUSE_MERGE_WAIT)
    assert out["promoted"] == "b-waiter", (
        "the freed slot did not advance the head of the queue: %r" % (out,))
    back = cc.acquire(key, "holder")   # the ticket leaving the gate
    assert back["granted"] is False, "the gate leaver jumped the queue: %r" % (back,)
    assert back["position"] == 2, (
        "the gate leaver must take its place behind the existing waiters: %r"
        % (back,))
    assert [e["ticket"] for e in cc.read_state(key)["queue"]] == \
        ["c-waiter", "holder"]


def test_the_merge_wait_face_never_becomes_a_zombie_channel(proj):
    root, key = proj
    cc.acquire(key, "g1")
    cc.acquire(key, "g2")
    cc.release(key, "g1", cc.CAUSE_MERGE_WAIT)
    cc.release(key, "g2", cc.CAUSE_MERGE_WAIT)
    # Reconcile never reports a merge waiter as a dead HOLDER (it holds nothing),
    # and it does not drop a healthy one.
    out = cc.reconcile(key, alive_tickets=["g1", "g2"])
    assert out["dropped"] == [], (
        "a merge-waiting ticket was reported as a dead holder: %r" % (out,))
    assert [e["ticket"] for e in cc.read_state(key)["merge_wait"]] == ["g1", "g2"]
    # A terminal release (cancel/close-out) clears the face by name.
    cc.release(key, "g1", cc.CAUSE_TERMINATED)
    assert [e["ticket"] for e in cc.read_state(key)["merge_wait"]] == ["g2"]
    # Reconcile prunes a gate waiter nobody could prove alive, and keeps a live
    # one (fail-closed stance of the holder list, same locked step).
    cc.reconcile(key, alive_tickets=["g2"])
    assert [e["ticket"] for e in cc.read_state(key)["merge_wait"]] == ["g2"]
    cc.reconcile(key, alive_tickets=[])
    assert cc.read_state(key)["merge_wait"] == []


def test_limit_one_merge_waiter_and_a_fresh_ticket_both_progress(proj):
    """The measured starvation shape, end to end: with one slot, the ticket
    waiting for its merge signature must not block a fresh ticket from
    starting, and its own approval must not deadlock against that fresh
    ticket's slot."""
    root, key = proj
    _set_limit(root, key, 1)
    cc.acquire(key, "merger")
    assert cc.release(key, "merger", cc.CAUSE_MERGE_WAIT)["released"] is True
    fresh = cc.acquire(key, "fresh")
    assert fresh["granted"] is True, (
        "the fresh ticket could not start while the other one waits at the "
        "merge gate: %r" % (fresh,))
    # Approval arrives while the fresh ticket still runs: the gate leaver takes
    # its place in the queue (no deadlock, no jump).
    waiting = cc.acquire(key, "merger")
    assert waiting["granted"] is False and waiting["position"] == 1, waiting
    # The ordinary release promotes it; the gate leaver then holds again.
    cc.release(key, "fresh", cc.CAUSE_TERMINATED)
    back = cc.acquire(key, "merger")
    assert back["granted"] is True, (
        "the approved merge could not take a slot after the fresh ticket "
        "released it: %r" % (back,))


def test_a_limit_decrease_does_not_strand_merge_waiters(proj):
    root, key = proj
    _set_limit(root, key, 3)
    for t in ("m1", "m2", "m3"):
        assert cc.acquire(key, t)["granted"] is True
    for t in ("m1", "m2", "m3"):
        assert cc.release(key, t, cc.CAUSE_MERGE_WAIT)["released"] is True
    assert cc.read_state(key)["holders"] == []
    _set_limit(root, key, 1)
    assert cc.read_state(key)["limit"] == 1
    assert cc.acquire(key, "m1")["granted"] is True
    second = cc.acquire(key, "m2")
    third = cc.acquire(key, "m3")
    assert second["granted"] is False and second["position"] == 1, second
    assert third["granted"] is False and third["position"] == 2, third
    cc.release(key, "m1", cc.CAUSE_TERMINATED)
    assert [h["ticket"] for h in cc.read_state(key)["holders"]] == ["m2"], (
        "a lowered limit stranded the merge waiters: %r"
        % (cc.read_state(key),))


def test_the_merge_wait_cause_is_its_own_word(proj):
    """Shape lock: the cause is a distinct word, so no reader can mistake a
    merge-wait release for a pause, a terminal release or a human-hold."""
    assert cc.CAUSE_MERGE_WAIT == "merge-wait"
    assert cc.CAUSE_MERGE_WAIT not in (cc.CAUSE_PAUSED, cc.CAUSE_TERMINATED,
                                       cc.CAUSE_HUMAN_GATE)
    assert cc.CAUSE_MERGE_WAIT != cc.REASON_HUMAN_HOLD
    # The blocked-stage human gate is still a renew word, refused as a release
    # cause (the existing t261004-32 assertion, re-read here against the widened
    # release vocabulary of t261022).
    root, key = proj
    cc.acquire(key, "h")
    with pytest.raises(ValueError) as e:
        cc.release(key, "h", cc.CAUSE_HUMAN_GATE)
    assert "human-gate" in str(e.value) and "renew" in str(e.value)
    assert [h["ticket"] for h in cc.read_state(key)["holders"]] == ["h"]


# ===========================================================================
# t261103-05 (design step (b)) - the review-request delivery act and its park
#
# This section lives in this file because it owns the same mechanical question
# (which parked state releases the working slot, and with which truthful cause
# word) plus the delivery act that produces the park. The ticket's write set is
# server/engine/ only, so the shared anchor manifest
# (integration/test_anchors.json, owned by the integration role) cannot be
# extended from this lane: the new tests therefore extend an ALREADY anchored
# engine test file instead of adding an undeclared one (lint L16). Step (a)
# (t261103-04) tests its own switch/credential faces in
# tests/test_t261004_44_deliver_refusal.py; this section does not re-test them -
# it tests what step (b) does WITH them.
#
# intent: with the project switch ON, a delivery that passed the machine gate
# (merge_check green) opens exactly ONE review request per changed repository,
# rewrites an existing request for the same branch instead of opening a second,
# parks the ticket in the named awaiting-remote-review state holding no working
# slot, and turns every failure face into a named, retry-safe stop. With the
# switch OFF nothing changes.
#
# hermetic: the platform is injected (a fake port / a fake HTTP transport), the
# switch decision is a plain value, no test opens a socket, reads ~/.sandbar,
# touches git or schedules a real activity.
# ===========================================================================

import pr_flow  # noqa: E402  (stdlib-only core: no temporalio, no IO)


class _FakePlatform:
    """The platform port, scripted per repository and branch. Records every call
    so a test can prove what was NOT called (no duplicate create, no local
    landing)."""

    def __init__(self, find=None, create=None, update=None, branch=None):
        self.calls = []
        self._find = find or (lambda scope: {"status": "absent", "number": 0, "url": ""})
        self._create = create or (lambda scope, title, body:
                                  {"status": "created", "number": 101,
                                   "url": "https://example.invalid/pull/101"})
        self._update = update or (lambda scope, number, title, body:
                                  {"status": "updated", "number": number,
                                   "url": "https://example.invalid/pull/%d" % number})
        self._branch = branch or (lambda scope: {"status": "pushed", "detail": ""})

    def find_request(self, scope):
        self.calls.append(("find", scope.get("repo"), scope.get("branch")))
        return self._find(scope)

    def ensure_branch(self, scope):
        self.calls.append(("branch", scope.get("repo"), scope.get("branch")))
        return self._branch(scope)

    def create_request(self, scope, title, body):
        self.calls.append(("create", scope.get("repo"), scope.get("branch")))
        return self._create(scope, title, body)

    def update_request(self, scope, number, title, body):
        self.calls.append(("update", scope.get("repo"), scope.get("branch")))
        return self._update(scope, number, title, body)

    def kinds(self, kind):
        return [c for c in self.calls if c[0] == kind]


DECLARED = ("owner/repo_a", "owner/repo_b", "owner/repo_c")


def _scope(repo, changed=True, name=None, branch=None, identity=None):
    """One entry of the engine's per-repository change-set knowledge."""
    return {"repo": repo, "name": name or (repo or "root"),
            "branch": branch or ("lane/x-%s" % (repo or "root")),
            "tree": "/tmp/%s" % (repo or "root"),
            "remote": "git@github.com:%s.git" % (identity or ("owner/%s" % (repo or "repo_a"))),
            "changed": changed}


def _on(repos=DECLARED):
    """Step (a)'s switch decision, ON with the declared repository set."""
    return pr_flow.SwitchDecision(enabled=True, reason="on",
                                  repositories=tuple(repos),
                                  declaration="/sandbox/projects/proj-alpha/project.yaml")


def _off(reason="absent"):
    return pr_flow.SwitchDecision(enabled=False, reason=reason, repositories=(),
                                  declaration="/sandbox/projects/proj-alpha/project.yaml")


def _payload(**over):
    base = {
        "ticket_id": "t261103ut",
        "title": "PR flow step (b)",
        "project": "proj-alpha",
        "branch": "lane/x",
        "base_ref": "main",
        "target_branch": "main",
        "gate_rows": [{"gate": "merge_check", "item": "Lane branch has commits",
                       "green": True},
                      {"gate": "merge_check", "item": "Worktree is clean", "green": True}],
        "evidence": ["Ticket face `t261103ut` (Temporal workflow history)"],
        "ticket_pointer": "python3 server/tools/ticket.py show t261103ut",
        "scopes": [_scope("")],
    }
    base.update(over)
    return base


# ---------- the negative control: OFF is today's path ----------------------

def test_pr_flow_switch_off_lands_locally_and_touches_nothing():
    """OFF means today's path: no platform is built, no scope is derived, no
    request is created - the design's default-off promise."""
    built = []

    def factory():
        built.append(1)
        return _FakePlatform()

    def must_not_derive():
        raise AssertionError("the change set was derived with the switch off")

    verdict = pr_flow.run_delivery(_payload(), _off(), platform_factory=factory,
                                   scope_provider=must_not_derive)
    assert verdict.action == pr_flow.ACTION_LOCAL_LANDING, verdict
    assert verdict.switch == "absent"
    assert built == [], "the off switch still built a platform client"
    assert verdict.requests == []


def test_pr_flow_no_switch_read_at_all_is_off():
    verdict = pr_flow.run_delivery(_payload(), None)
    assert verdict.action == pr_flow.ACTION_LOCAL_LANDING, verdict


def test_pr_flow_a_precondition_stop_surfaces_by_name_with_a_remedy():
    """A step (a) refusal is reported by its own code, with an actionable remedy
    and the duplicate-safety promise - never downgraded to "off" (that would land
    the delivery locally behind the operator's back)."""
    verdict = pr_flow.stop_verdict(pr_flow.STOP_CREDENTIAL_MISSING,
                                   "no credential file for the enabled switch")
    assert verdict.action == pr_flow.ACTION_STOP
    assert verdict.stop == pr_flow.STOP_CREDENTIAL_MISSING
    assert verdict.retryable is True
    text = pr_flow.stop_text(verdict, "t261103ut")
    assert pr_flow.STOP_CREDENTIAL_MISSING in text
    assert "credential" in text and "remedy" in text
    assert "no second request" in text
    assert "no remedy recorded" not in text


# ---------- the request body: what a reviewer sees -------------------------

def test_pr_flow_request_body_carries_the_reviewer_facts():
    body = pr_flow.build_request_body(
        ticket_id="t261103ut", title="PR flow step (b)", project="proj-alpha",
        repo="repo_b", identity="owner/repo_b", branch="lane/x-repo_b",
        target_branch="main",
        gate_items=["- `merge_check` - Lane branch has commits",
                    "- `merge_check` - Worktree is clean"],
        evidence=["Ticket face `t261103ut` (Temporal workflow history)",
                  "Lane worktree: /tmp/wt"],
        ticket_pointer="python3 server/tools/ticket.py show t261103ut")
    assert body["title"].startswith("[t261103ut] PR flow step (b)")
    text = body["body"]
    for needle in ("t261103ut", "PR flow step (b)", "repo_b", "owner/repo_b",
                   "lane/x-repo_b", "merge_check", "Lane branch has commits",
                   "Ticket face `t261103ut`", "ticket.py show t261103ut"):
        assert needle in text, "the request body is missing %r:\n%s" % (needle, text)


def test_pr_flow_request_body_is_pure_and_the_title_is_bounded():
    kwargs = dict(ticket_id="t1", title="x" * 500, project="p", repo="",
                  identity="owner/n", branch="b", target_branch="main",
                  gate_items=["- g"], evidence=["e"], ticket_pointer="p")
    assert pr_flow.build_request_body(**kwargs) == pr_flow.build_request_body(**kwargs)
    body = pr_flow.build_request_body(**kwargs)
    assert len(body["title"]) <= pr_flow.TITLE_LIMIT
    assert body["title"].startswith("[t1] ")


# ---------- one request per changed repository ----------------------------

def test_pr_flow_one_request_per_changed_repository():
    platform = _FakePlatform()
    verdict = pr_flow.run_delivery(
        _payload(scopes=[_scope("repo_a"), _scope("repo_b"),
                         _scope("repo_c", changed=False)]),
        _on(), platform_factory=lambda: platform)
    assert verdict.action == pr_flow.ACTION_REQUESTS_OPEN, verdict
    assert [r["repo"] for r in verdict.requests] == ["repo_a", "repo_b"], verdict.requests
    assert [c[1] for c in platform.kinds("create")] == ["repo_a", "repo_b"], (
        "an unchanged repository was published: %r" % (platform.calls,))
    assert platform.kinds("update") == []
    assert [r["identity"] for r in verdict.requests] == ["owner/repo_a", "owner/repo_b"]
    assert all(r["action"] == "created" and r["number"] == 101
               for r in verdict.requests), verdict.requests


def test_pr_flow_no_changed_repository_is_a_named_stop():
    platform = _FakePlatform()
    verdict = pr_flow.run_delivery(
        _payload(scopes=[_scope("repo_a", changed=False)]), _on(),
        platform_factory=lambda: platform)
    assert verdict.action == pr_flow.ACTION_STOP
    assert verdict.stop == pr_flow.DELIVERY_STOP_NO_CHANGED_REPOSITORY, verdict
    assert verdict.retryable is True
    assert platform.calls == [], "a stop still talked to the platform: %r" % (platform.calls,)


def test_pr_flow_change_set_derivation_error_is_a_named_stop():
    verdict = pr_flow.run_delivery(
        _payload(), _on(), platform_factory=lambda: _FakePlatform(),
        scope_provider=lambda: {"error": "multi-repo lane manifest corrupted"})
    assert verdict.stop == pr_flow.DELIVERY_STOP_CHANGE_SET_UNREADABLE, verdict
    assert "corrupted" in verdict.detail


def test_pr_flow_repository_must_be_identified_and_declared():
    """Least privilege: a request is only opened on a repository the project
    declaration names. An unidentified remote, and an identity outside the
    declared set, are each a NAMED stop - never a guess, never a silent skip
    (a skip would silently narrow what a person reviews)."""
    # (i) no GitHub remote at all
    platform = _FakePlatform()
    verdict = pr_flow.run_delivery(
        _payload(scopes=[dict(_scope("repo_a"), remote="https://gitlab.com/o/n.git")]),
        _on(), platform_factory=lambda: platform)
    assert verdict.stop == pr_flow.DELIVERY_STOP_REPOSITORY_UNIDENTIFIED, verdict
    # (ii) identified, but not in the declaration
    verdict = pr_flow.run_delivery(
        _payload(scopes=[_scope("repo_a", identity="someone/else")]), _on(),
        platform_factory=lambda: platform)
    assert verdict.stop == pr_flow.DELIVERY_STOP_REPOSITORY_NOT_DECLARED, verdict
    assert "owner/repo_a" in verdict.detail and "someone/else" in verdict.detail, (
        verdict.detail)
    assert platform.calls == [], "a stop still published: %r" % (platform.calls,)


# ---------- idempotency by branch ----------------------------------------

def test_pr_flow_existing_request_is_rewritten_not_duplicated():
    platform = _FakePlatform(find=lambda scope: {"status": "found", "number": 7,
                                                 "url": "https://example.invalid/pull/7"})
    first = pr_flow.run_delivery(_payload(), _on(), platform_factory=lambda: platform)
    second = pr_flow.run_delivery(_payload(), _on(), platform_factory=lambda: platform)
    assert first.action == second.action == pr_flow.ACTION_REQUESTS_OPEN
    assert platform.kinds("create") == [], (
        "a request was opened for a branch that already has one: %r" % (platform.calls,))
    assert len(platform.kinds("update")) == 2
    assert [r["action"] for r in second.requests] == ["updated"]
    assert [r["number"] for r in second.requests] == [7]


def test_pr_flow_ambiguous_create_never_becomes_a_second_request():
    """The ambiguous face: the create may or may not have landed. The retry
    re-reads the platform first, finds the request the first attempt created and
    rewrites it - the create is called exactly once across both runs."""
    state = {"created": False, "creates": 0}

    def find(scope):
        if state["created"]:
            return {"status": "found", "number": 42, "url": "u42"}
        return {"status": "absent", "number": 0, "url": ""}

    def create(scope, title, body):
        state["creates"] += 1
        state["created"] = True          # it DID land; only the answer was lost
        raise pr_flow.PrFlowStop(pr_flow.DELIVERY_STOP_PLATFORM_AMBIGUOUS,
                                 "read timeout after the create was accepted")

    platform = _FakePlatform(find=find, create=create)
    first = pr_flow.run_delivery(_payload(), _on(), platform_factory=lambda: platform)
    assert first.action == pr_flow.ACTION_STOP
    assert first.stop == pr_flow.DELIVERY_STOP_PLATFORM_AMBIGUOUS, first
    second = pr_flow.run_delivery(_payload(), _on(), platform_factory=lambda: platform)
    assert second.action == pr_flow.ACTION_REQUESTS_OPEN, second
    assert [r["action"] for r in second.requests] == ["updated"]
    assert state["creates"] == 1, "a retry opened a second request"


def test_pr_flow_partial_stop_keeps_the_published_request_and_retry_completes():
    """Two repositories, the second one unreachable: the stop names it, the first
    request stays recorded, and the retry finishes the job without a duplicate."""
    state = {"repo_b_ok": False, "creates": []}

    def find(scope):
        if scope["repo"] == "repo_b" and not state["repo_b_ok"]:
            raise pr_flow.PrFlowStop(pr_flow.DELIVERY_STOP_PLATFORM_UNREACHABLE,
                                     "connection timed out")
        if scope["repo"] in state["creates"]:
            return {"status": "found",
                    "number": 100 + state["creates"].index(scope["repo"]), "url": ""}
        return {"status": "absent", "number": 0, "url": ""}

    def create(scope, title, body):
        state["creates"].append(scope["repo"])
        return {"status": "created",
                "number": 100 + state["creates"].index(scope["repo"]), "url": ""}

    platform = _FakePlatform(find=find, create=create)
    scopes = [_scope("repo_a"), _scope("repo_b")]
    first = pr_flow.run_delivery(_payload(scopes=scopes), _on(),
                                 platform_factory=lambda: platform)
    assert first.action == pr_flow.ACTION_STOP
    assert first.stop == pr_flow.DELIVERY_STOP_PLATFORM_UNREACHABLE, first
    assert [r["repo"] for r in first.requests] == ["repo_a"], (
        "a published request was lost by the stop: %r" % (first.requests,))
    state["repo_b_ok"] = True
    second = pr_flow.run_delivery(_payload(scopes=scopes), _on(),
                                  platform_factory=lambda: platform)
    assert second.action == pr_flow.ACTION_REQUESTS_OPEN, second
    assert sorted(state["creates"]) == ["repo_a", "repo_b"], state["creates"]
    assert [r["action"] for r in second.requests] == ["updated", "created"], (
        second.requests)


# ---------- every failure face is named and retry-safe -------------------

@pytest.mark.parametrize("code", sorted(pr_flow.DELIVERY_STOP_TABLE))
def test_pr_flow_every_delivery_stop_is_named_retry_safe_and_has_a_remedy(code):
    assert pr_flow.is_delivery_stop(code) is True
    verdict = pr_flow.stop_verdict(code, "detail")
    assert verdict.action == pr_flow.ACTION_STOP and verdict.stop == code
    assert verdict.retryable is True
    assert pr_flow.stop_remedy(code) not in ("", "retry after the named condition "
                                                 "is removed")
    assert code in pr_flow.stop_text(verdict, "t261103ut")


@pytest.mark.parametrize("exc_code", [
    pr_flow.DELIVERY_STOP_PLATFORM_UNREACHABLE,
    pr_flow.DELIVERY_STOP_PLATFORM_REFUSED,
    pr_flow.DELIVERY_STOP_PLATFORM_AMBIGUOUS,
])
def test_pr_flow_each_placement_failure_is_the_named_stop(exc_code):
    def create(scope, title, body):
        raise pr_flow.PrFlowStop(exc_code, "platform said no (%s)" % exc_code)

    platform = _FakePlatform(create=create)
    verdict = pr_flow.run_delivery(_payload(), _on(), platform_factory=lambda: platform)
    assert verdict.action == pr_flow.ACTION_STOP
    assert verdict.stop == exc_code, verdict
    assert verdict.retryable is True
    assert len(platform.kinds("create")) == 1


def test_pr_flow_unbuildable_platform_is_a_named_stop():
    def factory():
        raise pr_flow.PrFlowStop(pr_flow.STOP_CREDENTIAL_MISSING,
                                 "no credential file for the enabled switch")

    verdict = pr_flow.run_delivery(_payload(), _on(), platform_factory=factory)
    assert verdict.stop == pr_flow.STOP_CREDENTIAL_MISSING, verdict
    assert "no credential file" in verdict.detail


def test_pr_flow_refuses_to_publish_without_evidence():
    verdict = pr_flow.run_delivery(_payload(gate_rows=[]), _on(),
                                   platform_factory=lambda: _FakePlatform())
    assert verdict.stop == pr_flow.DELIVERY_STOP_NO_EVIDENCE, verdict


def test_pr_flow_refuses_a_red_gate_row():
    verdict = pr_flow.run_delivery(
        _payload(gate_rows=[{"gate": "merge_check", "item": "Worktree is clean",
                             "green": False}]),
        _on(), platform_factory=lambda: _FakePlatform())
    assert verdict.stop == pr_flow.DELIVERY_STOP_GATE_NOT_GREEN, verdict


# ---------- the waiting state: named, no slot, poller-only exit ----------

def test_pr_flow_waiting_state_exit_is_the_poller_only():
    ok = pr_flow.remote_review_exit({"source": "poller", "note": "beat 7",
                                     "reported": {"merged": False}})
    assert ok.accepted is True and ok.record["source"] == "poller"
    assert ok.record["reported"] == {"merged": False}
    for bad in ({"source": "sign"}, {"source": "advance"}, {"source": ""},
                {"note": "no source"}, {}, None, "poller", 7):
        out = pr_flow.remote_review_exit(bad)
        assert out.accepted is False, bad
        assert "poller" in out.reason, out.reason
    assert pr_flow.AWAITING_REMOTE_REVIEW == "awaiting-remote-review"
    assert pr_flow.REMOTE_REVIEW_WAKE == "remote-review-wake"


def test_pr_flow_awaiting_record_names_the_requests_and_the_exit_channel():
    verdict = pr_flow.DeliveryVerdict(
        action=pr_flow.ACTION_REQUESTS_OPEN,
        requests=[{"repo": "repo_a", "name": "repo_a", "identity": "owner/repo_a",
                   "branch": "lane/x-repo_a", "number": 3, "url": "u",
                   "action": "created"}])
    rec = pr_flow.awaiting_record(verdict, ticket_id="t261103ut", project="p",
                                  at_iso="2026-11-03T00:00:00+00:00")
    assert rec["state"] == pr_flow.AWAITING_REMOTE_REVIEW
    assert rec["exit_channel"] == "poller"
    assert rec["requests"][0]["number"] == 3


# ---------- the secret never rides out on a receipt ----------------------

def test_pr_flow_secret_never_reaches_a_delivery_receipt():
    """The platform can echo the token back in an error text; every string the
    act returns is scrubbed, so no receipt, no stop and no detail carries it."""
    pr_flow.forget_secrets()
    token = "ghp_" + "Q" * 36
    pr_flow.register_secret(token)
    try:
        def create(scope, title, body):
            raise pr_flow.PrFlowStop(pr_flow.DELIVERY_STOP_PLATFORM_REFUSED,
                                     "422 bad token %s for %s" % (token, "owner/repo_a"))

        platform = _FakePlatform(create=create)
        verdict = pr_flow.run_delivery(_payload(), _on(),
                                      platform_factory=lambda: platform)
        for surface in (json.dumps(verdict.to_dict(), ensure_ascii=False),
                        pr_flow.stop_text(verdict, "t261103ut"),
                        str(verdict.detail), str(verdict.stop)):
            assert token not in surface, surface
            assert token[:12] not in surface, surface
        assert pr_flow.REDACTED in verdict.detail
        # the platform object itself never prints the token
        plat = pr_flow.GitHubPlatform(token=token,
                                      transport=lambda *a, **k: (200, {}, b"{}"))
        assert token not in repr(plat) and token not in str(plat)
    finally:
        pr_flow.forget_secrets()


# ---------- the GitHub adapter (injected transport; no socket) -----------

def test_pr_flow_github_adapter_maps_statuses_to_named_stops():
    def transport(status, payload):
        def _t(method, url, headers, body, timeout):
            return status, {}, json.dumps(payload).encode("utf-8")
        return _t

    scope = {"repo": "", "name": "root", "branch": "lane/x", "tree": "/tmp/x",
             "remote": "git@github.com:owner/name.git", "changed": True}

    plat = pr_flow.GitHubPlatform(token="ghp_" + "A" * 36,
                                  transport=transport(200, []))
    assert plat.find_request(scope)["status"] == "absent"

    plat = pr_flow.GitHubPlatform(token="ghp_" + "A" * 36,
                                  transport=transport(200, [{"number": 5,
                                                             "html_url": "u"}]))
    assert plat.find_request(scope) == {"status": "found", "number": 5, "url": "u",
                                        "detail": ""}

    plat = pr_flow.GitHubPlatform(token="ghp_" + "A" * 36,
                                  transport=transport(200, [{"number": 5},
                                                            {"number": 6}]))
    two = plat.find_request(scope)
    assert two["status"] == "ambiguous" and "one request per branch" in two["detail"]

    plat = pr_flow.GitHubPlatform(token="ghp_" + "A" * 36,
                                  transport=transport(201, {"number": 9,
                                                            "html_url": "u9"}))
    assert plat.create_request(scope, "title", "body") == {
        "status": "created", "number": 9, "url": "u9", "detail": ""}

    plat = pr_flow.GitHubPlatform(token="ghp_" + "A" * 36,
                                  transport=transport(201, {}))
    with pytest.raises(pr_flow.PrFlowStop) as e:
        plat.create_request(scope, "title", "body")
    assert e.value.code == pr_flow.DELIVERY_STOP_PLATFORM_AMBIGUOUS

    cases = [(401, pr_flow.STOP_CREDENTIAL_REJECTED),
             (403, pr_flow.DELIVERY_STOP_PLATFORM_REFUSED),
             (422, pr_flow.DELIVERY_STOP_PLATFORM_REFUSED),
             (500, pr_flow.DELIVERY_STOP_PLATFORM_UNREACHABLE),
             (429, pr_flow.DELIVERY_STOP_PLATFORM_UNREACHABLE),
             (418, pr_flow.DELIVERY_STOP_PLATFORM_AMBIGUOUS)]
    for status, code in cases:
        plat = pr_flow.GitHubPlatform(token="ghp_" + "A" * 36,
                                      transport=transport(status, {"message": "m"}))
        with pytest.raises(pr_flow.PrFlowStop) as e:
            plat.create_request(scope, "title", "body")
        assert e.value.code == code, (status, e.value.code, code)


def test_pr_flow_github_adapter_never_puts_the_token_in_argv():
    token = "ghp_" + "B" * 36
    seen = {}

    def git_runner(argv, env, timeout):
        seen["argv"] = argv
        seen["env"] = env
        return 0, "Everything up-to-date"

    plat = pr_flow.GitHubPlatform(token=token, git_runner=git_runner)
    out = plat.ensure_branch({"repo": "", "branch": "lane/x", "tree": "/tmp/x"})
    assert out["status"] == "present", out
    assert token not in " ".join(seen["argv"]), (
        "the credential leaked into the git argv: %r" % (seen["argv"],))
    assert seen["env"].get("GIT_CONFIG_KEY_0", "").startswith("http."), seen["env"]
    assert seen["env"].get("GIT_CONFIG_COUNT") == "1"

    def failing(argv, env, timeout):
        return 128, "fatal: Authentication failed for 'https://github.com/o/n.git/'"

    plat = pr_flow.GitHubPlatform(token=token, git_runner=failing)
    with pytest.raises(pr_flow.PrFlowStop) as e:
        plat.ensure_branch({"repo": "", "branch": "lane/x", "tree": "/tmp/x"})
    assert e.value.code == pr_flow.STOP_CREDENTIAL_REJECTED


def test_pr_flow_repo_identity_parsing():
    assert pr_flow.parse_repo_identity("git@github.com:owner/name.git") == "owner/name"
    assert pr_flow.parse_repo_identity("https://github.com/owner/name.git") == "owner/name"
    assert pr_flow.parse_repo_identity("ssh://git@github.com/owner/name/") == "owner/name"
    assert pr_flow.parse_repo_identity("https://gitlab.com/owner/name") == ""
    assert pr_flow.parse_repo_identity("") == ""


# ---------- the workflow side: the park, the slot, no local landing ------

def _pr_stub(recorded, receipt):
    async def execute_activity(act, *a, **k):
        name = getattr(act, "__name__", str(act))
        recorded.append((name, a[0] if a else None))
        if name == "pr_flow_deliver":
            return receipt
        if name == "concurrency_acquire":
            return {"granted": True, "already_holding": False, "reason": "",
                    "position": 0, "limit": 10, "holders": 1, "waiting": 0}
        if name == "ui_evidence_decl":
            return {"mode": "absent", "dirs": [], "note": ""}
        if name == "bundle_out_ws_prefixes":
            return SimpleNamespace(prefixes=[], note="")
        if name == "concurrency_release":
            return {"released": True, "cause": getattr(a[0], "cause", ""),
                    "promoted": None, "dropped_stale": [], "holders": 0, "waiting": 0}
        if name == "concurrency_renew":
            return {"renewed": True, "holding": True, "reason": "human-hold"}
        if name == "prepare_human_gate":
            return SimpleNamespace(context_text="merge gate context")
        if name == "merge":
            raise _StoppedAtMerge()
        return {}

    async def wait_condition(cond):
        # The real facade suspends until the condition holds; here a condition
        # that already holds returns at once (a seeded poller wake), anything
        # else parks the run at its first wait.
        try:
            ready = bool(cond())
        except Exception:  # noqa: BLE001
            ready = False
        if ready:
            return None
        raise _Parked()

    def sleep(_):
        raise AssertionError("queue sleep reached: no slot should be taken")

    return SimpleNamespace(
        patched=lambda pid: True,
        execute_activity=execute_activity,
        sleep=sleep,
        wait_condition=wait_condition,
        now=lambda: __import__("datetime").datetime(2026, 11, 3, 9, 0, 0),
        info=lambda: SimpleNamespace(start_time=None),
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None),
        upsert_memo=lambda *a, **k: None,
    )


def _drive_pr(monkeypatch, receipt, seed_wake=None):
    recorded = []
    stub = _pr_stub(recorded, receipt)
    monkeypatch.setattr(dev_lane, "workflow", stub)
    monkeypatch.setattr(base, "workflow", stub)
    orig_init = dev_lane.DevLaneWorkflow._init
    orig_ctor = dev_lane.DevLaneWorkflow.__init__

    def aimed_init(self, inp):
        orig_init(self, inp)
        self.meta["stage"] = "merge"
        self.meta["stage_state"] = "awaiting-human"

    def aimed_ctor(self):
        orig_ctor(self)
        if seed_wake is not None:
            self._pr_wake = dict(seed_wake)

    async def no_prepare(_self):
        return None

    monkeypatch.setattr(dev_lane.DevLaneWorkflow, "_init", aimed_init)
    monkeypatch.setattr(dev_lane.DevLaneWorkflow, "__init__", aimed_ctor)
    monkeypatch.setattr(dev_lane.DevLaneWorkflow, "_prepare_workspace_step", no_prepare)
    wf = dev_lane.DevLaneWorkflow()
    try:
        asyncio.run(wf.run(_inp()))
    except (_Parked, _StoppedAtMerge):
        pass
    return wf, recorded


def _requests_open_receipt():
    return {"action": pr_flow.ACTION_REQUESTS_OPEN, "switch": "on",
            "requests": [{"repo": "repo_a", "name": "repo_a",
                          "identity": "owner/repo_a",
                          "branch": "lane/x-repo_a", "number": 11,
                          "url": "https://example.invalid/pull/11",
                          "action": "created"}]}


def test_pr_flow_park_releases_the_slot_and_never_lands_locally(monkeypatch):
    wf, recorded = _drive_pr(monkeypatch, _requests_open_receipt())
    names = [n for n, _ in recorded]
    assert "merge" not in names, "a request delivery still landed locally: %r" % (names,)
    assert "prepare_human_gate" not in names, (
        "the parked ticket still opened the local merge gate: %r" % (names,))
    releases = [(n, getattr(a, "cause", "")) for n, a in recorded
                if n == "concurrency_release"]
    assert releases == [("concurrency_release", "remote-review-wait")], releases
    assert wf.meta["stage_state"] == pr_flow.AWAITING_REMOTE_REVIEW, wf.meta["stage_state"]
    assert wf.meta["pr_flow"]["state"] == pr_flow.AWAITING_REMOTE_REVIEW
    assert [r["number"] for r in wf.meta["pr_requests"]] == [11]
    assert any(t.get("state") == pr_flow.AWAITING_REMOTE_REVIEW for t in wf.timeline), (
        "the park left no named timeline entry: %r" % (wf.timeline,))


def test_pr_flow_park_refuses_a_non_poller_wake_and_stays_parked(monkeypatch):
    wf, _recorded = _drive_pr(monkeypatch, _requests_open_receipt(),
                              seed_wake={"source": "sign", "note": "host signed"})
    assert wf.meta["stage_state"] == pr_flow.AWAITING_REMOTE_REVIEW
    wakes = wf.meta.get("remote_review_wakes") or []
    assert wakes and wakes[0]["accepted"] is False, wakes
    assert "poller" in wakes[0]["reason"]
    assert any("awaiting-remote-review" in str(r.get("want", ""))
               for r in wf.refused), wf.refused
    states = [t.get("state") for t in wf.timeline]
    assert pr_flow.REMOTE_REVIEW_WAKE not in states, (
        "a non-poller wake left the park: %r" % (states,))


def test_pr_flow_park_leaves_only_on_a_poller_wake(monkeypatch):
    """The park's exit is the poller's wake and nothing else: the poller wake is
    recorded, the ticket lands in the named wake state, and what the platform
    reported is NOT judged here (that is step (c)), so it re-parks."""
    wf, _recorded = _drive_pr(monkeypatch, _requests_open_receipt(),
                              seed_wake={"source": "poller", "note": "beat 3",
                                         "reported": {"state": "open"}})
    wakes = wf.meta.get("remote_review_wakes") or []
    assert wakes and wakes[0]["accepted"] is True, wakes
    assert wakes[0]["reported"] == {"state": "open"}
    states = [t.get("state") for t in wf.timeline]
    assert pr_flow.REMOTE_REVIEW_WAKE in states, (
        "the poller wake did not leave the park: %r" % (states,))
    assert wf.meta["stage_state"] == pr_flow.AWAITING_REMOTE_REVIEW


def test_pr_flow_named_stop_blocks_the_merge_phase_by_name(monkeypatch):
    receipt = pr_flow.stop_verdict(pr_flow.DELIVERY_STOP_PLATFORM_UNREACHABLE,
                                   "no route to host").to_dict()
    wf, recorded = _drive_pr(monkeypatch, receipt)
    names = [n for n, _ in recorded]
    assert "merge" not in names and "prepare_human_gate" not in names, names
    assert pr_flow.DELIVERY_STOP_PLATFORM_UNREACHABLE in (
        wf.meta.get("blocked_reason") or ""), wf.meta.get("blocked_reason")


def test_pr_flow_switch_off_receipt_takes_the_ordinary_gate(monkeypatch):
    """Negative control on the workflow side: an OFF receipt (or a receipt with no
    verdict at all) falls through to today's merge gate - the park is never
    entered by accident."""
    wf, recorded = _drive_pr(monkeypatch, {"action": pr_flow.ACTION_LOCAL_LANDING,
                                           "switch": "off"})
    names = [n for n, _ in recorded]
    assert "prepare_human_gate" in names, names
    assert wf.meta["stage_state"] == "awaiting-human", wf.meta["stage_state"]
    assert "pr_requests" not in wf.meta


# ---------- source locks: the wiring cannot drift ------------------------

def test_pr_flow_merge_sites_are_gated_and_poller_only():
    """Every merge phase site forks through the SAME patched gate + helper (no
    second implementation), and the park's slot release uses its own cause word."""
    for lane_py, expected in ((DEV_LANE_PY, 2), (LIGHT_LANE_PY, 1)):
        src = lane_py.read_text(encoding="utf-8")
        gate = ("if workflow.patched(pr_flow.PR_FLOW_DELIVERY_PATCH_ID) \\\n"
                "                        and await self._pr_flow_merge_step():")
        assert src.count(gate) == expected, (
            "%s: the review-request fork must sit at every merge phase site and "
            "only there (found %d, expected %d)"
            % (lane_py.name, src.count(gate), expected))
    dev_src = DEV_LANE_PY.read_text(encoding="utf-8")
    assert dev_src.count("_concurrency_release(CAUSE_REMOTE_REVIEW_WAIT") == 1, (
        "the remote-review park must release the slot at exactly one site")
    assert "def remote_review_update(" in dev_src, (
        "the park has no poller wake signal - it could never leave the state")
    assert pr_flow.AWAITING_REMOTE_REVIEW in dev_src
    assert cc.CAUSE_REMOTE_REVIEW_WAIT == "remote-review-wait"
    assert cc.CAUSE_REMOTE_REVIEW_WAIT not in (cc.CAUSE_PAUSED, cc.CAUSE_TERMINATED,
                                               cc.CAUSE_HUMAN_GATE,
                                               cc.CAUSE_MERGE_WAIT,
                                               cc.CAUSE_BLOCKED_WAIT)


def test_pr_flow_remote_review_release_parks_on_the_ledger_face(proj):
    """The release is accepted by the ledger and parks under its own cause word,
    so a reader can tell where the ticket waits (never a zombie holder)."""
    root, key = proj
    cc.acquire(key, "pr1")
    out = cc.release(key, "pr1", cc.CAUSE_REMOTE_REVIEW_WAIT, stage="merge")
    assert out["released"] is True and out["cause"] == "remote-review-wait", out
    assert out["parked"]["face"] == "blocked-wait"
    assert out["parked"]["cause"] == "remote-review-wait"
    face = cc.read_state(key)["blocked_wait"]
    assert [(e["ticket"], e["cause"], e["stage"]) for e in face] == [
        ("pr1", "remote-review-wait", "merge")], face
    assert cc.read_state(key)["holders"] == []
    re_acq = cc.acquire(key, "pr1")
    assert re_acq["granted"] is True, re_acq
    assert re_acq.get("reacquired_from", {}).get("cause") == "remote-review-wait", re_acq


# ===========================================================================
# t261103-08 (design step (d)) - reconcile the local target branch after the
# platform merged: a fast-forward plus a content check, nothing else.
#
# The section lives in this file for the same reason step (b)'s does: the write
# set is server/engine/ only, so the shared anchor manifest
# (integration/test_anchors.json, owned by the integration role) cannot be
# extended from this lane, and a NEW server/engine/tests/test_*.py would be the
# L16 "anchor missing" error. This file is already anchored and already carries
# the review-request flow, of which step (d) is the closing act.
#
# intent: after the platform reports a merge, the local target branch catches up
# ONLY by a fast-forward whose content equals the content the platform reported
# as merged. A branch that carries other work (not an ancestor), a branch whose
# content differs, an unreadable remote, an absent branch and a partly
# reconciled multi-repository delivery are each a NAMED outcome; every refusal
# leaves the branch byte-identical, and no path can spell a history-rewriting,
# forced or discarding git command.
#
# hermetic: two harnesses. A scripted git (every command line recorded, the
# repository state modelled in memory) covers the whole decision surface
# exactly; three cases run against a REAL repository cloned from a REAL local
# bare remote in tmp_path (file transport only - no network, no ~/.sandbar, no
# docker, no port 3099, no Temporal). The platform is always injected.
# ===========================================================================

import ast      # noqa: E402  (the source-level guard reads pr_flow.py's AST)
import subprocess  # noqa: E402  (the real-git harness runs git on tmp dirs only)

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40
TREE_A = "1" * 40
TREE_B = "2" * 40
TREE_X = "3" * 40


class _FakeGit:
    """One scripted local repository, plus a record of every command line.

    The model is deliberately small: a local branch, a fetched remote head, a
    tree per commit, and one scripted answer per verb. That is enough to judge
    the decision surface, and it makes "the branch was left alone" a plain fact
    (the modelled branch sha did not move).
    """

    def __init__(self, local=SHA_A, head=SHA_B, trees=None, ancestry=0,
                 fetch=(0, ""), merge_code=0, merge_text="Fast-forward",
                 after_local=None, after_tree=None, missing=()):
        self.local = local
        self.head = head
        self.trees = dict(trees if trees is not None else
                          {SHA_A: TREE_A, SHA_B: TREE_B})
        self.ancestry = ancestry
        self.fetch = fetch
        self.merge_code = merge_code
        self.merge_text = merge_text
        self.after_local = after_local
        self.after_tree = after_tree
        self.missing = set(missing)
        self.calls = []          # [(verb, args_tuple)]
        self.merges = 0

    # -- the runner interface --
    def __call__(self, argv, env, timeout):
        verb = argv[3]
        args = tuple(argv[4:])
        self.calls.append((verb, args))
        if verb == "fetch":
            return self.fetch
        if verb == "merge-base":
            return self.ancestry, ""
        if verb == "merge":
            self.merges += 1
            if self.merge_code != 0:
                return self.merge_code, self.merge_text
            self.local = self.after_local or args[-1]
            return 0, self.merge_text
        if verb == "rev-parse":
            rev = args[-1]
            if rev in self.missing:
                return 128, "fatal: Needed a single revision\n"
            if rev == "FETCH_HEAD":
                return 0, self.head + "\n"
            if rev.startswith("refs/heads/"):
                return 0, self.local + "\n"
            if rev.endswith("^{tree}"):
                sha = rev[:-len("^{tree}")]
                if self.after_tree and self.merges and sha == self.local:
                    return 0, self.after_tree + "\n"
                tree = self.trees.get(sha)
                if not tree:
                    return 128, "fatal: Not a valid object name\n"
                return 0, tree + "\n"
            return 128, "fatal: unknown revision\n"
        return 127, "scripted git: unexpected verb %r\n" % (verb,)

    def verbs(self):
        return [verb for verb, _args in self.calls]


class _FakeMergePlatform:
    """The platform port for step (d): what it reports as merged, per identity."""

    def __init__(self, sha=SHA_B, tree=TREE_B, status="merged", raises=None):
        self.sha = sha
        self.tree = tree
        self.status = status
        self.raises = raises
        self.calls = []

    def merge_record(self, scope):
        self.calls.append(dict(scope))
        if self.raises is not None:
            raise self.raises
        if self.status == "absent":
            return {"status": "absent", "sha": "", "tree": "",
                    "detail": "no commit on that branch"}
        return {"status": "merged", "sha": self.sha, "tree": self.tree,
                "detail": ""}


def _rec_switch(enabled=True, reason="on"):
    return pr_flow.SwitchDecision(
        enabled=enabled, reason=reason,
        repositories=("owner/repo_a", "owner/repo_b"),
        declaration="/sandbox/projects/proj-alpha/project.yaml")


def _rec_entry(path, identity="owner/repo_a", name=None, target="main"):
    return {"repo": str(path), "name": name or "root", "identity": identity,
            "target_branch": target, "remote_name": "origin"}


def _rec_payload(entries, **over):
    base = {"repositories": entries, "target_branch": "main",
            "remote_name": "origin"}
    base.update(over)
    return base


def _assert_no_destructive_command(calls):
    """Every command line the act issued is allowlisted (verb and tokens)."""
    forbidden = set(pr_flow.FORBIDDEN_GIT_VERBS) | set(pr_flow.FORBIDDEN_GIT_ARGS)
    for verb, args in calls:
        assert verb in pr_flow.ALLOWED_GIT_VERBS, (verb, args)
        for token in args:
            assert token not in forbidden, (verb, token)
            assert not token.startswith("--force"), (verb, token)


# ---------- 1. the happy path: a fast-forward plus a content check ---------

def test_reconcile_fast_forwards_and_verifies_the_merged_content(tmp_path):
    git = _FakeGit(local=SHA_A, head=SHA_B)
    platform = _FakeMergePlatform(sha=SHA_B, tree=TREE_B)
    verdict = pr_flow.reconcile_after_merge(
        _rec_payload([_rec_entry(tmp_path / "repo_a")]), _rec_switch(),
        platform=platform, git_runner=git)
    assert verdict.state == pr_flow.RECONCILE_RECONCILED, verdict.to_dict()
    assert (verdict.terminal, verdict.keeps_ticket_open) == (True, False)
    row = verdict.repositories[0]
    assert row["state"] == pr_flow.REPO_STATE_RECONCILED
    assert (row["before"], row["after"], row["head"]) == (SHA_A, SHA_B, SHA_B)
    assert row["advanced"] is True
    assert row["local_tree"] == row["reported_tree"] == TREE_B
    assert git.local == SHA_B, "the scripted branch did not end on the merged head"
    # exactly one mutating command, and it is the fast-forward to that commit
    assert git.verbs().count("merge") == 1
    merge_args = [args for verb, args in git.calls if verb == "merge"][0]
    assert merge_args == ("--ff-only", SHA_B), merge_args
    assert git.verbs().index("fetch") < git.verbs().index("merge"), git.calls
    _assert_no_destructive_command(git.calls)
    # the receipt is a plain, JSON-safe face (nothing secret, nothing live)
    face = verdict.to_dict()
    assert set(face) == {"state", "stop", "detail", "terminal",
                         "keeps_ticket_open", "retryable", "repositories"}
    text = pr_flow.reconcile_text(verdict, "t261103ut")
    assert pr_flow.RECONCILE_RECONCILED in text and "root" in text


def test_reconcile_names_every_repository_of_a_multi_repo_delivery(tmp_path):
    a, b = tmp_path / "repo_a", tmp_path / "repo_b"
    gits = {str(a): _FakeGit(local=SHA_A, head=SHA_B),
            str(b): _FakeGit(local=SHA_C, head=SHA_A,
                             trees={SHA_C: TREE_A, SHA_A: TREE_B})}
    platform = _FakeMergePlatform(sha=SHA_B, tree=TREE_B)

    def runner(argv, env, timeout):
        return gits[argv[2]](argv, env, timeout)

    verdict = pr_flow.reconcile_after_merge(
        _rec_payload([_rec_entry(a, identity="owner/repo_a", name="a"),
                      _rec_entry(b, identity="owner/repo_b", name="b")]),
        _rec_switch(), platform=platform, git_runner=runner)
    assert verdict.state == pr_flow.RECONCILE_RECONCILED, verdict.to_dict()
    assert [r["name"] for r in verdict.repositories] == ["a", "b"]
    assert [c["identity"] for c in platform.calls] == ["owner/repo_a",
                                                       "owner/repo_b"]
    assert gits[str(a)].local == SHA_B and gits[str(b)].local == SHA_A
    for git in gits.values():
        _assert_no_destructive_command(git.calls)


def test_reconcile_is_idempotent_when_the_branch_is_already_there(tmp_path):
    git = _FakeGit(local=SHA_B, head=SHA_B)
    verdict = pr_flow.reconcile_after_merge(
        _rec_payload([_rec_entry(tmp_path / "repo_a")]), _rec_switch(),
        platform=_FakeMergePlatform(sha=SHA_B, tree=TREE_B), git_runner=git)
    assert verdict.state == pr_flow.RECONCILE_RECONCILED, verdict.to_dict()
    assert verdict.repositories[0]["advanced"] is False
    _assert_no_destructive_command(git.calls)


# ---------- 2. the default-off control -------------------------------------

def test_reconcile_with_the_switch_off_touches_nothing(tmp_path):
    """OFF (and "no switch read at all") is not a no-op success: it is the named
    not-applicable answer, and no git command and no platform read happens."""
    git = _FakeGit()
    platform = _FakeMergePlatform()
    payload = _rec_payload([_rec_entry(tmp_path / "repo_a")])
    for switch in (_rec_switch(enabled=False, reason="off"), None):
        verdict = pr_flow.reconcile_after_merge(payload, switch,
                                               platform=platform, git_runner=git)
        assert verdict.state == pr_flow.RECONCILE_OFF, verdict.to_dict()
        assert (verdict.terminal, verdict.keeps_ticket_open) == (False, False)
    assert git.calls == [] and platform.calls == []


def test_reconcile_refuses_an_unusable_repository_set(tmp_path):
    """An absent, empty or malformed set is a named stop, never a silent "done"
    (a reconciliation that looked at nothing must not read as reconciled)."""
    for payload in ({}, {"repositories": []}, {"repositories": [42]},
                    {"repositories": [{"name": "root"}]},
                    {"repositories": [{"repo": "   "}]}):
        git = _FakeGit()
        verdict = pr_flow.reconcile_after_merge(payload, _rec_switch(),
                                                platform=_FakeMergePlatform(),
                                                git_runner=git)
        assert verdict.stop == pr_flow.RECONCILE_STOP_SET_UNUSABLE, verdict.to_dict()
        assert verdict.state == pr_flow.ACTION_STOP
        assert verdict.keeps_ticket_open is True
        assert git.calls == [], "a git command ran with no usable repository set"


# ---------- 3. the refusals leave the branch byte-identical ---------------

def test_local_drift_stops_named_and_leaves_the_branch_untouched(tmp_path):
    """The measured shape: the local branch carries work the merged remote state
    does not. No fast-forward exists, so nothing may move."""
    git = _FakeGit(local=SHA_A, head=SHA_B, ancestry=1)
    verdict = pr_flow.reconcile_after_merge(
        _rec_payload([_rec_entry(tmp_path / "repo_a")]), _rec_switch(),
        platform=_FakeMergePlatform(sha=SHA_B, tree=TREE_B), git_runner=git)
    assert verdict.state == pr_flow.ACTION_STOP
    assert verdict.stop == pr_flow.RECONCILE_STOP_LOCAL_DRIFT, verdict.to_dict()
    assert verdict.keeps_ticket_open is True and verdict.terminal is False
    row = verdict.repositories[0]
    assert row["before"] == SHA_A and row["after"] == ""
    assert "untouched" in row["detail"]
    assert git.local == SHA_A, "the branch moved on a drift refusal"
    assert "merge" not in git.verbs(), git.calls
    _assert_no_destructive_command(git.calls)


def test_content_mismatch_stops_before_the_branch_moves(tmp_path):
    """The fetched head is not the content the platform reported as merged: the
    act refuses BEFORE the fast-forward, so the branch cannot have moved."""
    git = _FakeGit(local=SHA_A, head=SHA_B, trees={SHA_A: TREE_A, SHA_B: TREE_X})
    verdict = pr_flow.reconcile_after_merge(
        _rec_payload([_rec_entry(tmp_path / "repo_a")]), _rec_switch(),
        platform=_FakeMergePlatform(sha=SHA_B, tree=TREE_B), git_runner=git)
    assert verdict.stop == pr_flow.RECONCILE_STOP_CONTENT_MISMATCH, verdict.to_dict()
    assert "NOT advanced" in verdict.repositories[0]["detail"]
    assert git.local == SHA_A, "the branch moved on a content mismatch"
    assert "merge" not in git.verbs(), git.calls
    _assert_no_destructive_command(git.calls)


def test_a_post_act_mismatch_is_named_and_nothing_is_rewritten(tmp_path):
    """A branch that does not end where the act put it (a race, or a git that
    lies) is read back and named; the act does not chase it with a second
    command."""
    drifted = _FakeGit(local=SHA_A, head=SHA_B, after_local=SHA_C,
                       trees={SHA_A: TREE_A, SHA_B: TREE_B, SHA_C: TREE_B})
    verdict = pr_flow.reconcile_after_merge(
        _rec_payload([_rec_entry(tmp_path / "repo_a")]), _rec_switch(),
        platform=_FakeMergePlatform(sha=SHA_B, tree=TREE_B), git_runner=drifted)
    assert verdict.stop == pr_flow.RECONCILE_STOP_LOCAL_DRIFT, verdict.to_dict()
    assert "nothing further is attempted" in verdict.repositories[0]["detail"]
    assert drifted.merges == 1, "a second mutating command was issued"
    _assert_no_destructive_command(drifted.calls)

    late = _FakeGit(local=SHA_A, head=SHA_B, after_tree=TREE_X)
    verdict = pr_flow.reconcile_after_merge(
        _rec_payload([_rec_entry(tmp_path / "repo_a")]), _rec_switch(),
        platform=_FakeMergePlatform(sha=SHA_B, tree=TREE_B), git_runner=late)
    assert verdict.stop == pr_flow.RECONCILE_STOP_CONTENT_MISMATCH, verdict.to_dict()
    assert "nothing is rewritten to hide it" in verdict.repositories[0]["detail"]
    assert late.merges == 1, "a second mutating command was issued"


@pytest.mark.parametrize("label,git_kwargs,platform,expected", [
    ("local-branch-absent", {"missing": ("refs/heads/main",)},
     _FakeMergePlatform(), pr_flow.RECONCILE_STOP_BRANCH_MISSING),
    ("remote-ref-absent", {"fetch": (128, "fatal: couldn't find remote ref "
                                           "refs/heads/main\n")},
     _FakeMergePlatform(), pr_flow.RECONCILE_STOP_BRANCH_MISSING),
    ("platform-has-no-branch", {}, _FakeMergePlatform(status="absent"),
     pr_flow.RECONCILE_STOP_BRANCH_MISSING),
    ("remote-unreachable", {"fetch": (128, "fatal: unable to access https://"
                                            "github.com/o/r.git/: Could not "
                                            "resolve host: github.com\n")},
     _FakeMergePlatform(), pr_flow.RECONCILE_STOP_REMOTE_UNREACHABLE),
    ("platform-unreadable", {},
     _FakeMergePlatform(raises=RuntimeError("socket closed")),
     pr_flow.RECONCILE_STOP_REMOTE_UNREACHABLE),
    ("ancestry-unanswerable", {"ancestry": 128}, _FakeMergePlatform(),
     pr_flow.RECONCILE_STOP_REMOTE_UNREACHABLE),
])
def test_every_read_failure_is_named_and_moves_nothing(tmp_path, label,
                                                       git_kwargs, platform,
                                                       expected):
    git = _FakeGit(local=SHA_A, head=SHA_B, **git_kwargs)
    verdict = pr_flow.reconcile_after_merge(
        _rec_payload([_rec_entry(tmp_path / "repo_a")]), _rec_switch(),
        platform=platform, git_runner=git)
    assert verdict.stop == expected, (label, verdict.to_dict())
    assert verdict.keeps_ticket_open is True and verdict.terminal is False
    assert git.local == SHA_A, "%s: the branch moved" % label
    assert "merge" not in git.verbs(), (label, git.calls)
    assert verdict.repositories[0]["remedy"], "a named stop lost its remedy"
    _assert_no_destructive_command(git.calls)


def test_a_repository_without_an_identity_is_named_before_any_git_call(tmp_path):
    git = _FakeGit()
    entry = {"repo": str(tmp_path / "repo_a"), "name": "root", "remote_name": "origin"}
    verdict = pr_flow.reconcile_after_merge(_rec_payload([entry]), _rec_switch(),
                                            platform=_FakeMergePlatform(),
                                            git_runner=git)
    assert verdict.stop == pr_flow.DELIVERY_STOP_REPOSITORY_UNIDENTIFIED, \
        verdict.to_dict()
    assert git.calls == []
    assert verdict.repositories[0]["remedy"]


# ---------- 4. the partial multi-repository state (non-terminal) ----------

def test_a_partial_multi_repo_reconciliation_keeps_the_ticket_open(tmp_path):
    a, b = tmp_path / "repo_a", tmp_path / "repo_b"
    gits = {str(a): _FakeGit(local=SHA_A, head=SHA_B),
            str(b): _FakeGit(local=SHA_C, head=SHA_A, ancestry=1,
                             trees={SHA_C: TREE_A, SHA_A: TREE_B})}
    platform = _FakeMergePlatform(sha=SHA_B, tree=TREE_B)

    def runner(argv, env, timeout):
        return gits[argv[2]](argv, env, timeout)

    verdict = pr_flow.reconcile_after_merge(
        _rec_payload([_rec_entry(a, identity="owner/repo_a", name="a"),
                      _rec_entry(b, identity="owner/repo_b", name="b")]),
        _rec_switch(), platform=platform, git_runner=runner)
    assert verdict.state == pr_flow.RECONCILE_PARTIAL, verdict.to_dict()
    assert verdict.stop == pr_flow.RECONCILE_STOP_PARTIAL_RECONCILIATION
    assert (verdict.terminal, verdict.keeps_ticket_open) == (False, True)
    assert verdict.retryable is True
    rows = {r["name"]: r for r in verdict.repositories}
    assert rows["a"]["state"] == pr_flow.REPO_STATE_RECONCILED
    assert rows["b"]["stop"] == pr_flow.RECONCILE_STOP_LOCAL_DRIFT
    assert gits[str(a)].local == SHA_B, "the reconcilable repository was not caught up"
    assert gits[str(b)].local == SHA_C, "the stopped repository moved"
    text = pr_flow.reconcile_text(verdict, "t261103ut")
    assert "a" in text and "b" in text and "ticket stays open" in text
    assert pr_flow.stop_remedy(pr_flow.RECONCILE_STOP_PARTIAL_RECONCILIATION)


# ---------- 5. the vocabulary: every stop, one remedy line -----------------

def test_every_reconcile_stop_is_named_and_carries_a_remedy():
    constants = {value for key, value in vars(pr_flow).items()
                 if key.startswith("RECONCILE_STOP_") and isinstance(value, str)}
    assert constants == set(pr_flow.RECONCILE_STOP_TABLE)
    assert {pr_flow.RECONCILE_STOP_REMOTE_UNREACHABLE,
            pr_flow.RECONCILE_STOP_LOCAL_DRIFT,
            pr_flow.RECONCILE_STOP_CONTENT_MISMATCH,
            pr_flow.RECONCILE_STOP_PARTIAL_RECONCILIATION,
            pr_flow.RECONCILE_STOP_BRANCH_MISSING} <= constants
    for code in constants:
        assert pr_flow.is_reconcile_stop(code) is True
        remedy = pr_flow.stop_remedy(code)
        assert remedy and "retry after the named condition is removed" != remedy, (
            "%s lost its remedy line" % code)
        assert pr_flow.RECONCILE_STOP_TABLE[code], code
    assert pr_flow.is_reconcile_stop("") is False
    assert pr_flow.is_reconcile_stop(pr_flow.STOP_CREDENTIAL_MISSING) is False


# ---------- 6. the mechanical promise: no destructive git verb exists ------

def _pr_flow_source():
    return (ENGINE / "pr_flow.py").read_text(encoding="utf-8")


def _literals_outside_docstrings_and_guard_tables(source):
    """Every string constant except docstrings and the guard tables' own words."""
    tree = ast.parse(source)
    excluded = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            first = body[0] if body else None
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                excluded.add(id(first.value))
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and (
                        target.id.startswith("FORBIDDEN_")
                        or target.id == "FORCED_UPDATE_PREFIX"):
                    for inner in ast.walk(node.value):
                        if isinstance(inner, ast.Constant):
                            excluded.add(id(inner))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in excluded:
            out.append(node.value)
    return out


def test_the_module_cannot_spell_a_destructive_git_command():
    """Two halves of one promise. Statics: no string in the module (outside its
    own guard tables and its prose) spells a history-rewriting, forced or
    discarding command. Dynamics: the one chokepoint refuses such a shape, so a
    future edit cannot reach a git argument list that does harm."""
    forbidden = ((set(pr_flow.FORBIDDEN_GIT_VERBS)
                  - set(pr_flow.FORBIDDEN_GIT_VERBS_COMMON_WORDS))
                 | set(pr_flow.FORBIDDEN_GIT_ARGS))
    assert pr_flow.FORBIDDEN_GIT_VERBS_COMMON_WORDS, (
        "the scan exemption list must stay an explicit, reviewed list")
    source = _pr_flow_source()
    for text in _literals_outside_docstrings_and_guard_tables(source):
        for token in text.split():
            assert token not in forbidden, (
                "pr_flow.py carries the git token %r in a string: %r"
                % (token, text[:80]))
            assert not token.startswith(pr_flow.FORCED_UPDATE_PREFIX), (
                "pr_flow.py carries a forced-update flag: %r" % (text[:80],))
    # there is exactly ONE place that spells a git command line
    assert source.count('"git", "-C"') == 1, (
        "a second git command-line builder appeared in pr_flow.py")
    # and it refuses every shape that would rewrite, force or discard
    for verb in pr_flow.FORBIDDEN_GIT_VERBS:
        with pytest.raises(ValueError):
            pr_flow._git_argv("/tmp/x", verb, "--help")
        assert verb not in pr_flow.ALLOWED_GIT_VERBS
    for arg in pr_flow.FORBIDDEN_GIT_ARGS:
        with pytest.raises(ValueError):
            pr_flow._git_argv("/tmp/x", "fetch", arg)
    for arg in (pr_flow.FORCED_UPDATE_PREFIX, "--force-with-lease", "-f"):
        with pytest.raises(ValueError):
            pr_flow._git_argv("/tmp/x", "push", arg)
    with pytest.raises(ValueError):
        pr_flow._git_argv("/tmp/x", "kill-everything")
    with pytest.raises(ValueError):
        pr_flow._git_argv("/tmp/x")
    for verb in pr_flow.ALLOWED_GIT_VERBS:
        assert pr_flow._git_argv("/tmp/x", verb, "ref") == [
            "git", "-C", "/tmp/x", verb, "ref"]


def test_the_module_has_exactly_one_place_that_can_run_a_process():
    """The gated runner is the only code that can spawn anything; no shell path
    exists beside it."""
    source = _pr_flow_source()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            segment = ast.get_source_segment(source, node) or ""
            if "subprocess" in segment:
                assert node.name == "_default_git_runner", (
                    "a process can be spawned from %r as well" % node.name)
    for banned in ("os.system", "os.popen", "os.execv", "os.execvp",
                   "os.spawnv", "shell=True"):
        assert banned not in source, banned


# ---------- 7. the real-git proof: byte identity on every refusal ---------

def _git(args, cwd):
    proc = subprocess.run(["git"] + list(args), cwd=str(cwd),
                          capture_output=True, text=True)
    assert proc.returncode == 0, "git %s failed in %s: %s" % (
        " ".join(args), cwd, proc.stderr)
    return proc.stdout.strip()


def _git_setup(path):
    _git(["init", "-b", "main"], cwd=path)
    _git(["config", "user.email", "ut@example.com"], cwd=path)
    _git(["config", "user.name", "ut"], cwd=path)


def _worktree_bytes(root):
    """Every tracked-or-untracked file's bytes outside .git (the whole tree)."""
    out = {}
    for path in sorted(root.rglob("*")):
        if ".git" in path.parts or not path.is_file():
            continue
        out[str(path.relative_to(root))] = path.read_bytes()
    return out


def _fingerprint(repo):
    """(branch sha, branch tree, dirty status, worktree bytes): byte identity."""
    return (_git(["rev-parse", "refs/heads/main"], cwd=repo),
            _git(["rev-parse", "refs/heads/main^{tree}"], cwd=repo),
            _git(["status", "--porcelain"], cwd=repo),
            _worktree_bytes(repo))


@pytest.fixture
def real_clone(tmp_path):
    """A real clone of a real LOCAL bare remote - file transport, no network."""
    origin = tmp_path / "origin.git"
    _git(["init", "--bare", "-b", "main", str(origin)], cwd=tmp_path)
    seed = tmp_path / "seed"
    seed.mkdir()
    _git_setup(seed)
    (seed / "README.md").write_text("base\n", encoding="utf-8")
    _git(["add", "-A"], cwd=seed)
    _git(["commit", "-m", "base"], cwd=seed)
    _git(["remote", "add", "origin", str(origin)], cwd=seed)
    _git(["push", "-u", "origin", "main"], cwd=seed)
    clone = tmp_path / "clone"
    _git(["clone", str(origin), str(clone)], cwd=tmp_path)
    _git(["config", "user.email", "ut@example.com"], cwd=clone)
    _git(["config", "user.name", "ut"], cwd=clone)
    return origin, seed, clone


def _advance_origin(seed, name="second.txt", text="second\n"):
    (seed / name).write_text(text, encoding="utf-8")
    _git(["add", "-A"], cwd=seed)
    _git(["commit", "-m", "advance " + name], cwd=seed)
    _git(["push", "origin", "main"], cwd=seed)


def _real_verdict(clone, platform, target="main"):
    return pr_flow.reconcile_after_merge(
        _rec_payload([_rec_entry(clone, identity="owner/repo_a",
                                 target=target)]),
        _rec_switch(), platform=platform)


def test_real_fast_forward_brings_the_clone_to_the_merged_content(real_clone):
    origin, seed, clone = real_clone
    _advance_origin(seed)
    head = _git(["rev-parse", "refs/heads/main"], cwd=origin)
    tree = _git(["rev-parse", "refs/heads/main^{tree}"], cwd=origin)
    before = _git(["rev-parse", "refs/heads/main"], cwd=clone)
    assert before != head

    verdict = _real_verdict(clone, _FakeMergePlatform(sha=head, tree=tree))
    assert verdict.state == pr_flow.RECONCILE_RECONCILED, verdict.to_dict()
    assert _git(["rev-parse", "refs/heads/main"], cwd=clone) == head
    assert _git(["rev-parse", "refs/heads/main^{tree}"], cwd=clone) == tree
    assert (clone / "second.txt").read_text(encoding="utf-8") == "second\n"
    assert _git(["status", "--porcelain"], cwd=clone) == ""
    assert verdict.repositories[0]["advanced"] is True

    # a retry (the production path after a later repository stopped) is a no-op:
    # the branch is already there, so the same act answers reconciled again with
    # nothing advanced - and it still moves no ref beyond the fetch's own cache
    after_first = _fingerprint(clone)
    again = _real_verdict(clone, _FakeMergePlatform(sha=head, tree=tree))
    assert again.state == pr_flow.RECONCILE_RECONCILED, again.to_dict()
    assert again.repositories[0]["advanced"] is False
    assert _fingerprint(clone) == after_first


def test_real_local_drift_refusal_leaves_the_branch_byte_identical(real_clone):
    """The local clone carries its own commit; the remote advanced from the same
    base. Byte identity is measured on the real repository: branch sha, branch
    tree, worktree status and every file's bytes. The fetch's own tracking cache
    (refs/remotes/origin/main) is outside this promise on purpose - it is a
    read cache of the remote, never the work; refs/heads/main is the branch."""
    origin, seed, clone = real_clone
    (clone / "local.txt").write_text("local work\n", encoding="utf-8")
    _git(["add", "-A"], cwd=clone)
    _git(["commit", "-m", "local work"], cwd=clone)
    _advance_origin(seed)
    head = _git(["rev-parse", "refs/heads/main"], cwd=origin)
    tree = _git(["rev-parse", "refs/heads/main^{tree}"], cwd=origin)
    before = _fingerprint(clone)
    log_before = _git(["log", "--format=%H %s"], cwd=clone)

    verdict = _real_verdict(clone, _FakeMergePlatform(sha=head, tree=tree))
    assert verdict.stop == pr_flow.RECONCILE_STOP_LOCAL_DRIFT, verdict.to_dict()
    assert verdict.keeps_ticket_open is True
    assert _fingerprint(clone) == before, (
        "the drift refusal changed the branch or the worktree")
    assert _git(["log", "--format=%H %s"], cwd=clone) == log_before


def test_real_content_mismatch_refusal_rewrites_nothing(real_clone):
    """The platform reports a tree the fetched head does not carry: the act
    refuses before the fast-forward and the real branch stays where it was."""
    origin, seed, clone = real_clone
    _advance_origin(seed)
    head = _git(["rev-parse", "refs/heads/main"], cwd=origin)
    wrong_tree = _git(["rev-parse", "refs/heads/main^{tree}"], cwd=clone)
    assert wrong_tree != _git(["rev-parse", "refs/heads/main^{tree}"], cwd=origin)
    before = _fingerprint(clone)

    verdict = _real_verdict(clone, _FakeMergePlatform(sha=head, tree=wrong_tree))
    assert verdict.stop == pr_flow.RECONCILE_STOP_CONTENT_MISMATCH, verdict.to_dict()
    assert _fingerprint(clone) == before, (
        "the content-mismatch refusal changed the branch or the worktree")


# ---------- 8. the act consumes step (b), and a broken runner is named ------

def test_reconcile_consumes_the_step_b_park_record(tmp_path):
    """Step (d) reads what step (b) already published (`requests`: repository
    path, identity, branch), so no caller has to reshape it."""
    git = _FakeGit(local=SHA_A, head=SHA_B)
    park = {"requests": [{"repo": str(tmp_path / "repo_a"), "name": "root",
                          "identity": "owner/repo_a", "branch": "lane/x",
                          "number": 101, "url": "", "action": "created"}],
            "target_branch": "main"}
    verdict = pr_flow.reconcile_after_merge(
        park, _rec_switch(), platform=_FakeMergePlatform(sha=SHA_B, tree=TREE_B),
        git_runner=git)
    assert verdict.state == pr_flow.RECONCILE_RECONCILED, verdict.to_dict()
    assert verdict.repositories[0]["identity"] == "owner/repo_a"
    assert git.local == SHA_B
    _assert_no_destructive_command(git.calls)


def test_a_fully_stopped_multi_repo_delivery_adopts_nothing(tmp_path):
    a, b = tmp_path / "repo_a", tmp_path / "repo_b"
    gits = {str(a): _FakeGit(local=SHA_A, head=SHA_B, ancestry=1),
            str(b): _FakeGit(local=SHA_C, head=SHA_A,
                             fetch=(128, "fatal: Could not resolve host: "
                                         "github.com\n"))}

    def runner(argv, env, timeout):
        return gits[argv[2]](argv, env, timeout)

    verdict = pr_flow.reconcile_after_merge(
        _rec_payload([_rec_entry(a, identity="owner/repo_a", name="a"),
                      _rec_entry(b, identity="owner/repo_b", name="b")]),
        _rec_switch(), platform=_FakeMergePlatform(sha=SHA_B, tree=TREE_B),
        git_runner=runner)
    assert verdict.state == pr_flow.ACTION_STOP, verdict.to_dict()
    assert verdict.stop == pr_flow.RECONCILE_STOP_LOCAL_DRIFT
    assert verdict.keeps_ticket_open is True and verdict.terminal is False
    assert [r["stop"] for r in verdict.repositories] == [
        pr_flow.RECONCILE_STOP_LOCAL_DRIFT,
        pr_flow.RECONCILE_STOP_REMOTE_UNREACHABLE]
    assert "none of the 2 repositories reconciled" in verdict.detail
    assert gits[str(a)].local == SHA_A and gits[str(b)].local == SHA_C


def test_a_broken_git_runner_is_a_named_stop_and_moves_nothing(tmp_path):
    """An injected runner that raises, or answers something unusable, means the
    act cannot know what git did: a named stop, never an assumed advance."""
    def raising(argv, env, timeout):
        raise OSError("git is not installed")

    def malformed(argv, env, timeout):
        return "ok"

    def unparsable_code(argv, env, timeout):
        return "zero", ""

    for runner in (raising, malformed, unparsable_code):
        verdict = pr_flow.reconcile_after_merge(
            _rec_payload([_rec_entry(tmp_path / "repo_a")]), _rec_switch(),
            platform=_FakeMergePlatform(sha=SHA_B, tree=TREE_B),
            git_runner=runner)
        assert verdict.stop == pr_flow.RECONCILE_STOP_REMOTE_UNREACHABLE, \
            verdict.to_dict()
        assert verdict.keeps_ticket_open is True
        assert verdict.repositories[0]["detail"]


def test_the_github_adapter_reports_the_merged_tree_on_the_target_branch():
    """The real port's half of the content check: a GET on the target branch's
    commit, answering the commit sha and its tree sha; an absent branch and every
    platform refusal stay named. No request body is sent, nothing is written."""
    seen = {}

    def transport(status, payload):
        def _t(method, url, headers, body, timeout):
            seen.update({"method": method, "url": url, "body": body,
                         "auth": headers.get("Authorization", "")})
            return status, {}, json.dumps(payload).encode("utf-8")
        return _t

    scope = {"repo": "", "name": "root", "identity": "owner/name",
             "target_branch": "main", "remote": "git@github.com:owner/name.git"}

    platform = pr_flow.GitHubPlatform(token="ghp_" + "C" * 36, transport=transport(
        200, {"sha": SHA_B, "commit": {"tree": {"sha": TREE_B}}}))
    out = platform.merge_record(scope)
    assert out["status"] == "merged" and out["sha"] == SHA_B
    assert out["tree"] == TREE_B and out["target"] == "main"
    assert seen["method"] == "GET", seen
    assert seen["url"].endswith("/repos/owner/name/commits/main"), seen["url"]
    assert seen["body"] is None, "the merge read must not send a body"

    absent = pr_flow.GitHubPlatform(token="ghp_" + "C" * 36,
                                    transport=transport(404, {"message": "Not Found"}))
    assert absent.merge_record(scope)["status"] == "absent"

    for status, code in ((401, pr_flow.STOP_CREDENTIAL_REJECTED),
                         (429, pr_flow.DELIVERY_STOP_PLATFORM_UNREACHABLE),
                         (500, pr_flow.DELIVERY_STOP_PLATFORM_UNREACHABLE),
                         (418, pr_flow.DELIVERY_STOP_PLATFORM_AMBIGUOUS)):
        platform = pr_flow.GitHubPlatform(
            token="ghp_" + "C" * 36, transport=transport(status, {"message": "m"}))
        with pytest.raises(pr_flow.PrFlowStop) as e:
            platform.merge_record(scope)
        assert e.value.code == code, (status, e.value.code, code)

    shapeless = pr_flow.GitHubPlatform(token="ghp_" + "C" * 36,
                                       transport=transport(200, {"sha": SHA_A}))
    with pytest.raises(pr_flow.PrFlowStop) as e:
        shapeless.merge_record(scope)
    assert e.value.code == pr_flow.DELIVERY_STOP_PLATFORM_AMBIGUOUS
