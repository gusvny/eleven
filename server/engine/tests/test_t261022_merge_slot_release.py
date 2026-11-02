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
