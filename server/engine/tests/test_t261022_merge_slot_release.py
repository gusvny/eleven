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
from shared import ArchiveResult, MergeResult, Signature  # noqa: E402

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

def _pr_stub(recorded, receipt, poll=None, reconcile=None, patches=None, beats=1):
    """The workflow facade of the review-request tests.

    `poll` scripts what the poll activity answers (design step (c)); `reconcile`
    scripts what the post-merge reconciliation answers (design step (d), wired by
    t261103-13; the default is a delivery whose repositories all reconciled);
    `patches` limits which replay markers exist (None = all of them, the live
    case); `beats` bounds how many beat timers the park may run before the run is
    parked (a timer loop that never ends is exactly the busy loop the beat must
    not be).
    """

    def _patched(pid):
        if patches is None:
            return True
        return pid in patches

    async def execute_activity(act, *a, **k):
        name = getattr(act, "__name__", str(act))
        recorded.append((name, a[0] if a else None))
        if name == "pr_flow_deliver":
            return receipt
        if name == "pr_flow_poll":
            return poll if poll is not None else {"action": "still_open", "beat": 1}
        if name == "pr_flow_reconcile":
            return reconcile if reconcile is not None else _reconciled_receipt()
        if name == "archive_ticket":
            return ArchiveResult(ok=True, archive_path="/tmp/ticket-archive")
        if name == "teardown_lane":
            return MergeResult(ok=True)
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

    budget = {"beats": int(beats)}

    async def wait_condition(cond, timeout=None):
        # The real facade suspends until the condition holds; here a condition
        # that already holds returns at once (a seeded poller wake). With a
        # timeout the beat fires until the budget is spent, then the run parks
        # (a beat that never stops would be the busy loop the design forbids).
        recorded.append(("wait_condition", timeout))
        try:
            ready = bool(cond())
        except Exception:  # noqa: BLE001
            ready = False
        if ready:
            return None
        if timeout is None:
            raise _Parked()
        if budget["beats"] <= 0:
            raise _Parked()
        budget["beats"] -= 1
        raise asyncio.TimeoutError()

    def sleep(_):
        raise AssertionError("queue sleep reached: no slot should be taken")

    return SimpleNamespace(
        patched=_patched,
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


class _EnteredStage(Exception):
    """Sentinel: the loop entered a named phase (the test stops there)."""

    def __init__(self, stage):
        self.stage = stage
        super().__init__(stage)


def _drive_pr(monkeypatch, receipt, seed_wake=None, poll=None, patches=None,
              beats=1, stop_at_stage=None, reconcile=None):
    recorded = []
    stub = _pr_stub(recorded, receipt, poll=poll, reconcile=reconcile,
                    patches=patches, beats=beats)
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

    orig_enter = dev_lane.DevLaneWorkflow._enter

    def aimed_enter(self, step_id):
        if stop_at_stage and str(step_id) == str(stop_at_stage):
            raise _EnteredStage(step_id)
        orig_enter(self, step_id)

    monkeypatch.setattr(dev_lane.DevLaneWorkflow, "_init", aimed_init)
    monkeypatch.setattr(dev_lane.DevLaneWorkflow, "__init__", aimed_ctor)
    monkeypatch.setattr(dev_lane.DevLaneWorkflow, "_prepare_workspace_step", no_prepare)
    monkeypatch.setattr(dev_lane.DevLaneWorkflow, "_enter", aimed_enter)
    wf = dev_lane.DevLaneWorkflow()
    try:
        asyncio.run(wf.run(_inp()))
    except (_Parked, _StoppedAtMerge, _EnteredStage):
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
    second implementation), the helper's answer decides the loop's phase, and the
    park's slot release uses its own cause word.

    Step (c) adds two source locks of its own: the beat is a TIMER (never a bare
    `while True` poll), and a beat is exactly ONE activity attempt (the beat, not
    an activity retry, is the retry unit)."""
    for lane_py, expected in ((DEV_LANE_PY, 2), (LIGHT_LANE_PY, 1)):
        src = lane_py.read_text(encoding="utf-8")
        gate = ("if workflow.patched(pr_flow.PR_FLOW_DELIVERY_PATCH_ID):\n"
                "                    _pr_phase = await self._pr_flow_merge_step()\n"
                "                if _pr_phase:\n"
                "                    phase = _pr_phase\n"
                "                    continue")
        assert src.count(gate) == expected, (
            "%s: the review-request fork must sit at every merge phase site and "
            "only there (found %d, expected %d)"
            % (lane_py.name, src.count(gate), expected))
    dev_src = DEV_LANE_PY.read_text(encoding="utf-8")
    assert "pr_flow.PR_FLOW_POLL_PATCH_ID" in dev_src, (
        "the poll's replay gate is missing: a pre-step-(c) history would replay "
        "different commands")
    # t261103-13: the beat is the PROJECT's declared interval, resolved once before
    # the loop, and it falls back to pr_flow.POLL_BEAT_SECONDS (the shipped value).
    assert "timeout=beat_seconds" in dev_src, (
        "the park does not wait on a beat TIMER: a bare wait would never poll")
    assert ("beat_seconds = pr_flow.flow_options_from("
            in dev_src), (
        "the beat interval is not resolved from the park's declared options")
    assert "POLL_BEAT_SECONDS = DEFAULT_BEAT_SECONDS" in (
        ENGINE / "pr_flow.py").read_text(encoding="utf-8"), (
        "the shipped beat and the module default drifted apart")
    assert "retry_policy=PR_FLOW_POLL_RETRY" in dev_src, (
        "the poll activity is scheduled without its bounded retry policy: an "
        "unreachable platform would be retried in place instead of on the next beat")
    assert "PR_FLOW_POLL_RETRY = RetryPolicy(maximum_attempts=1)" in dev_src, (
        "the beat must be one attempt: the beat is the retry unit")
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
# t261103-07 (design step (c)) - the poll, the platform verdict, the comment round
#
# This section extends the same already-anchored engine test file for the same
# reason the step (b) section does: the write set is server/engine/ only, so
# integration/test_anchors.json (integration role) cannot be extended here and a
# new test file would be an undeclared orphan (lint L16).
#
# intent: with a ticket parked in `awaiting-remote-review`, the engine asks the
# platform on a slow bounded beat, and the PLATFORM'S ANSWER drives the ticket:
# every declared repository merged closes the ticket citing the merge per
# repository; a request closed WITHOUT a merge is a named non-acceptance and
# never a close; new comments after our last push (our own words and already
# handled ones excluded) produce exactly ONE rework round carrying the text; a
# failed beat names itself and waits for the next beat; an empty round moves
# nothing. Only the poller may wake the park, through a real ticket entry.
#
# hermetic: the platform is a fake port or a fake HTTP transport, the credential
# is never resolved from ~/.sandbar, no socket, no git, no real activity.
# ===========================================================================

PROD_MERGE = {"repo": "repo_a", "name": "repo_a", "identity": "owner/repo_a",
              "branch": "lane/x-repo_a", "number": 11,
              "url": "https://example.invalid/pull/11",
              "merged_at": "2026-11-03T09:10:00Z", "merge_commit": "abc1234"}


def _open_poll(number=11, comments=None, branch="present", name="repo_a",
               identity="owner/repo_a"):
    return {"status": "open", "number": number, "branch": branch,
            "comments": list(comments or []), "url": "",
            "detail": "", "repo": name, "name": name, "identity": identity}


def _merged_poll(number=11, name="repo_a", identity="owner/repo_a"):
    return {"status": "merged", "number": number, "branch": "",
            "comments": [], "merged_at": "2026-11-03T09:10:00Z",
            "merge_commit": "abc1234", "url": "https://example.invalid/pull/11",
            "detail": "", "repo": name, "name": name, "identity": identity}


def _parked(requests=None):
    return [dict(r) for r in (requests or [PROD_MERGE])]


class _FakePollPlatform:
    """Step (c)'s port: scripted answers per request number, every call recorded
    so a test can prove what was NOT asked (no retry inside a beat)."""

    def __init__(self, answers=None, login="sandbar-bot", raise_first=None):
        self.calls = []
        self._answers = answers or {}
        self._login = login
        self._raise = raise_first

    def poll_request(self, scope, number):
        self.calls.append((scope.get("identity"), number))
        if self._raise is not None:
            exc = self._raise
            self._raise = None
            raise exc
        answer = self._answers.get(number, {"status": "open"})
        return dict(answer) if isinstance(answer, dict) else answer

    def viewer_login(self):
        return self._login


# ---------- the verdict truth table ---------------------------------------

@pytest.mark.parametrize("answers,action,stop", [
    ({11: _merged_poll()}, pr_flow.POLL_MERGED, ""),
    ({11: {"status": "closed"}}, "", pr_flow.POLL_STOP_REQUEST_CLOSED_UNMERGED),
    ({11: {"status": "absent"}}, "", pr_flow.POLL_STOP_REQUEST_MISSING),
    ({11: _open_poll()}, pr_flow.POLL_STILL_OPEN, ""),
    ({11: {"status": "unreachable"}}, "", pr_flow.POLL_STOP_PLATFORM_UNREACHABLE),
    ({11: {"status": "rate_limited"}}, "", pr_flow.POLL_STOP_RATE_LIMITED),
    ({11: {"status": "nonsense"}}, "", pr_flow.POLL_STOP_ANSWER_AMBIGUOUS),
    ({11: {"status": "open", "branch": "deleted"}}, "",
     pr_flow.POLL_STOP_BRANCH_DELETED),
    ({11: _open_poll(comments=[{"id": "c1", "author": "human-reviewer",
                                "body": "please rename this",
                                "created_at": "2026-11-03T10:00:00Z"}])},
     pr_flow.POLL_COMMENT_ROUND, ""),
    ({11: _open_poll(comments=[{"id": "c1", "author": "sandbar-bot",
                                "body": "opened by the engine",
                                "created_at": "2026-11-03T10:00:00Z"}])},
     "", pr_flow.POLL_STOP_COMMENT_ROUND_EMPTY),
])
def test_pr_flow_step_c_verdict_truth_table(answers, action, stop):
    """One beat, one answer, one verdict - and no stop may read as a merge."""
    platform = _FakePollPlatform(answers=answers)
    verdict = pr_flow.poll_parked(platform, _parked(), own_logins=["sandbar-bot"],
                                  since_iso="2026-11-03T09:00:00+00:00", beat=3)
    assert verdict.action == action, (verdict.action, verdict.stop, verdict.detail)
    assert verdict.stop == stop, (verdict.stop, verdict.detail)
    assert verdict.beat == 3
    if stop:
        # A named stop carries a remedy and says in words that it is not a merge.
        assert pr_flow.stop_remedy(stop) and pr_flow.stop_remedy(stop) != \
            "retry after the named condition is removed", stop
        text = pr_flow.poll_text(verdict, "t261103ut")
        assert stop in text and "NOT a merge" in text, text
    if action != pr_flow.POLL_MERGED:
        assert not verdict.merged, "a non-merge answer carried a merge citation"


def test_pr_flow_step_c_all_merged_is_the_only_acceptance_and_is_cited():
    platform = _FakePollPlatform(answers={11: _merged_poll(), 12: _merged_poll(
        number=12, name="repo_b", identity="owner/repo_b")})
    requests = [PROD_MERGE, dict(PROD_MERGE, repo="repo_b", name="repo_b",
                                 identity="owner/repo_b", number=12)]
    verdict = pr_flow.poll_parked(platform, requests)
    assert verdict.action == pr_flow.POLL_MERGED
    record = pr_flow.acceptance_record(verdict, ticket_id="t261103ut",
                                  at_iso="2026-11-03T09:20:00+00:00")
    assert record["state"] == pr_flow.POLL_MERGED
    assert [r["number"] for r in record["requests"]] == [11, 12]
    assert record["cited"] == [
        "owner/repo_a#11 merged at 2026-11-03T09:10:00Z (commit abc1234)",
        "owner/repo_b#12 merged at 2026-11-03T09:10:00Z (commit abc1234)"], record["cited"]


def test_pr_flow_step_c_a_partly_merged_delivery_is_named_and_does_not_move():
    platform = _FakePollPlatform(answers={11: _merged_poll(),
                                          12: _open_poll(number=12, name="repo_b",
                                                         identity="owner/repo_b")})
    requests = [PROD_MERGE, dict(PROD_MERGE, repo="repo_b", name="repo_b",
                                 identity="owner/repo_b", number=12)]
    verdict = pr_flow.poll_parked(platform, requests)
    assert verdict.action == pr_flow.POLL_PARTLY_MERGED
    assert verdict.stop == pr_flow.POLL_STOP_PARTLY_MERGED
    assert pr_flow.poll_stop_keeps_waiting(verdict.stop), (
        "a partly merged delivery must keep the park, not block it")
    assert "owner/repo_a#11" in verdict.detail and "owner/repo_b#12" in verdict.detail
    text = pr_flow.poll_text(verdict, "t261103ut")
    assert "NOT a merge" in text and "remedy" in text, text
    assert [m["number"] for m in verdict.merged] == [11], verdict.merged


def test_pr_flow_step_c_a_closed_request_never_reads_as_a_merge():
    """Fail-closed over the sibling: one repository merged and one closed WITHOUT a
    merge is a NON-ACCEPTANCE, never a close."""
    platform = _FakePollPlatform(answers={11: _merged_poll(), 12: {"status": "closed"}})
    requests = [PROD_MERGE, dict(PROD_MERGE, repo="repo_b", name="repo_b",
                                 identity="owner/repo_b", number=12)]
    verdict = pr_flow.poll_parked(platform, requests)
    assert verdict.action == "" and verdict.stop == \
        pr_flow.POLL_STOP_REQUEST_CLOSED_UNMERGED
    assert verdict.merged == []
    text = pr_flow.poll_text(verdict, "t261103ut")
    assert "not accepted" in text and "NOT a merge" in text, text


def test_pr_flow_step_c_every_named_stop_has_a_remedy_and_a_class():
    assert pr_flow.POLL_BEAT_STOPS & pr_flow.POLL_TERMINAL_STOPS == set(), (
        "a stop cannot both wait for the next beat and need a human")
    assert (pr_flow.POLL_BEAT_STOPS | pr_flow.POLL_TERMINAL_STOPS) == \
        frozenset(pr_flow.POLL_STOP_TABLE), "a named stop has no class"
    for code in pr_flow.POLL_STOP_TABLE:
        remedy = pr_flow.stop_remedy(code)
        assert remedy and remedy != "retry after the named condition is removed", code
        assert pr_flow.is_poll_stop(code)
    # The five faces the design names, each its own name.
    for code in (pr_flow.POLL_STOP_PLATFORM_UNREACHABLE,
                 pr_flow.POLL_STOP_RATE_LIMITED,
                 pr_flow.POLL_STOP_ANSWER_AMBIGUOUS,
                 pr_flow.POLL_STOP_REQUEST_CLOSED_UNMERGED,
                 pr_flow.POLL_STOP_BRANCH_DELETED,
                 pr_flow.POLL_STOP_COMMENT_ROUND_EMPTY):
        assert code in pr_flow.POLL_STOP_TABLE


# ---------- the comment round: selection and exclusion --------------------

def test_pr_flow_step_c_comment_round_selection_excludes_own_and_handled():
    """Every comment after our last push counts - human or bot - except our own
    credential's words and the ones an earlier round already carried."""
    comments = [
        {"id": "c1", "author": "sandbar-bot", "body": "the engine's own note",
         "created_at": "2026-11-03T10:00:00Z"},                    # ours
        {"id": "c2", "author": "sandbar-bot[bot]", "body": "our bot again",
         "created_at": "2026-11-03T10:01:00Z"},                    # ours (bot form)
        {"id": "c3", "author": "human-reviewer", "body": "please rename",
         "created_at": "2026-11-03T10:02:00Z"},                    # counts
        {"id": "c4", "author": "ci-bot[bot]", "body": "a linter bot objects",
         "created_at": "2026-11-03T10:03:00Z"},                    # bot, counts
        {"id": "c5", "author": "human-reviewer", "body": "already handled",
         "created_at": "2026-11-03T10:04:00Z"},                    # handled
        {"id": "c6", "author": "human-reviewer", "body": "said before our push",
         "created_at": "2026-11-03T08:00:00Z"},                    # before the push
        {"id": "c3", "author": "human-reviewer", "body": "please rename",
         "created_at": "2026-11-03T10:02:00Z"},                    # repeated id
    ]
    selected = pr_flow.select_comment_round(
        comments, own_logins=["sandbar-bot"], handled_ids=["c5"],
        since_iso="2026-11-03T09:00:00+00:00")
    assert [c["id"] for c in selected] == ["c3", "c4"], selected
    assert selected[1]["is_bot"] is True, (
        "a bot comment counts (design requirement 5); it is recorded as a fact, "
        "not filtered")


def test_pr_flow_step_c_one_round_is_delivered_once():
    """The same comments never produce a second round: the first round records
    them, and the next beat sees an empty round and moves nothing."""
    comments = [{"id": "c3", "author": "human-reviewer", "body": "please rename",
                 "created_at": "2026-11-03T10:02:00Z"}]
    platform = _FakePollPlatform(answers={11: _open_poll(comments=comments)})
    first = pr_flow.poll_parked(platform, _parked(), own_logins=["sandbar-bot"],
                                since_iso="2026-11-03T09:00:00+00:00", beat=1)
    assert first.action == pr_flow.POLL_COMMENT_ROUND
    record = pr_flow.round_face_record(first.round.get("comments"), round_no=1,
                                       at_iso="2026-11-03T10:10:00+00:00",
                                       since_iso="2026-11-03T09:00:00+00:00")
    assert record["count"] == 1 and record["ids"] == ["c3"]
    assert "please rename" in record["text"]
    handled = pr_flow.handled_comment_ids([record])
    assert handled == ["c3"]
    second = pr_flow.poll_parked(platform, _parked(), own_logins=["sandbar-bot"],
                                 handled_ids=handled,
                                 since_iso="2026-11-03T09:00:00+00:00", beat=2)
    assert second.action == "" and second.stop == \
        pr_flow.POLL_STOP_COMMENT_ROUND_EMPTY
    assert pr_flow.poll_stop_keeps_waiting(second.stop), (
        "an empty round must not move the ticket")


# ---------- the poll is bounded -------------------------------------------

def test_pr_flow_step_c_the_poll_asks_once_per_request_and_never_retries():
    platform = _FakePollPlatform(answers={11: _merged_poll()})
    requests = [PROD_MERGE]
    pr_flow.poll_parked(platform, requests, beat=1)
    assert platform.calls == [("owner/repo_a", 11)], platform.calls
    # An unreachable answer stops the beat: the remaining requests are not asked
    # inside the same beat (the NEXT beat asks again).
    platform2 = _FakePollPlatform(answers={11: {"status": "unreachable"}})
    requests2 = [PROD_MERGE, dict(PROD_MERGE, number=12, name="repo_b",
                                 identity="owner/repo_b")]
    verdict = pr_flow.poll_parked(platform2, requests2, beat=1)
    assert verdict.stop == pr_flow.POLL_STOP_PLATFORM_UNREACHABLE
    assert platform2.calls == [("owner/repo_a", 11)], platform2.calls


def test_pr_flow_step_c_a_raising_port_is_a_named_stop_not_an_exception():
    platform = _FakePollPlatform(raise_first=RuntimeError("connection reset"))
    verdict = pr_flow.poll_parked(platform, _parked(), beat=1)
    assert verdict.stop == pr_flow.POLL_STOP_ANSWER_AMBIGUOUS, verdict.stop
    assert "RuntimeError" in verdict.detail
    # A step (a) credential stop is NOT a beat: it is raised to the caller.
    platform2 = _FakePollPlatform(
        raise_first=pr_flow.PrFlowStop(pr_flow.STOP_CREDENTIAL_REJECTED, "401"))
    with pytest.raises(pr_flow.PrFlowStop) as e:
        pr_flow.poll_parked(platform2, _parked(), beat=1)
    assert e.value.code == pr_flow.STOP_CREDENTIAL_REJECTED


def test_pr_flow_step_c_no_parked_request_is_named():
    verdict = pr_flow.poll_parked(_FakePollPlatform(), [])
    assert verdict.stop == pr_flow.POLL_STOP_NO_PARKED_REQUEST
    assert pr_flow.poll_stop_keeps_waiting(verdict.stop) is False


# ---------- the GitHub adapter (injected transport; no socket) ------------

def _transport(script):
    calls = []

    def _t(method, url, headers, body, timeout):
        calls.append((method, url))
        if not script:
            raise AssertionError("unexpected platform call: %s %s" % (method, url))
        status, payload = script.pop(0)
        return status, {}, json.dumps(payload).encode("utf-8")

    _t.calls = calls
    return _t


def test_pr_flow_step_c_github_adapter_reads_state_comments_and_branch():
    from shared import Signature as _S  # noqa: F401  (import parity with the file)

    transport = _transport([
        (200, {"number": 11, "state": "open", "merged": False,
               "html_url": "https://example.invalid/pull/11",
               "head": {"ref": "lane/x-repo_a", "sha": "deadbeef"}}),
        (200, [{"id": 5, "body": "please rename", "created_at":
                "2026-11-03T10:00:00Z",
                "user": {"login": "human-reviewer", "type": "User"}},
               {"id": 6, "body": "engine note", "created_at":
                "2026-11-03T10:01:00Z",
                "user": {"login": "sandbar-bot", "type": "Bot"}}]),
        (200, {"name": "lane/x-repo_a"}),
    ])
    platform = pr_flow.GitHubPlatform(token="ghp_" + "a" * 30, transport=transport)
    scope = {"repo": "repo_a", "name": "repo_a", "identity": "owner/repo_a",
             "branch": "lane/x-repo_a", "remote": ""}
    answer = platform.poll_request(scope, 11)
    assert answer["status"] == pr_flow.REQUEST_OPEN, answer
    assert answer["branch"] == pr_flow.BRANCH_PRESENT
    assert [c["id"] for c in answer["comments"]] == ["5", "6"]
    assert answer["comments"][1]["is_bot"] is True
    # The round then excludes our bot's own note and keeps the human's.
    selected = pr_flow.select_comment_round(answer["comments"],
                                            own_logins=["sandbar-bot"])
    assert [c["id"] for c in selected] == ["5"], selected
    assert [c[0] for c in transport.calls] == ["GET", "GET", "GET"]
    assert transport.calls[0][1].endswith("/repos/owner/repo_a/pulls/11")
    assert "/issues/11/comments" in transport.calls[1][1]
    assert "/branches/lane%2Fx-repo_a" in transport.calls[2][1]


def test_pr_flow_step_c_github_adapter_maps_merged_closed_and_absent():
    scope = {"identity": "owner/repo_a", "branch": "lane/x", "remote": ""}
    merged = pr_flow.GitHubPlatform(
        token="ghp_" + "b" * 30,
        transport=_transport([(200, {"number": 11, "state": "closed",
                                     "merged": True,
                                     "merged_at": "2026-11-03T09:10:00Z",
                                     "merge_commit_sha": "abc1234",
                                     "html_url": "u"})]))
    out = merged.poll_request(scope, 11)
    assert out["status"] == pr_flow.REQUEST_MERGED
    assert out["merge_commit"] == "abc1234" and out["merged_at"]
    closed = pr_flow.GitHubPlatform(
        token="ghp_" + "c" * 30,
        transport=_transport([(200, {"number": 11, "state": "closed",
                                     "merged": False, "html_url": "u"})]))
    assert closed.poll_request(scope, 11)["status"] == pr_flow.REQUEST_CLOSED
    absent = pr_flow.GitHubPlatform(
        token="ghp_" + "d" * 30, transport=_transport([(404, {"message": "Not Found"})]))
    assert absent.poll_request(scope, 11)["status"] == pr_flow.REQUEST_ABSENT


def test_pr_flow_step_c_github_adapter_names_rate_limits_and_the_viewer():
    scope = {"identity": "owner/repo_a", "branch": "lane/x", "remote": ""}
    limited = pr_flow.GitHubPlatform(
        token="ghp_" + "e" * 30,
        transport=_transport([(429, {"message": "API rate limit exceeded"})]))
    with pytest.raises(pr_flow.PrFlowStop) as e:
        limited.poll_request(scope, 11)
    assert e.value.code == pr_flow.POLL_STOP_RATE_LIMITED
    viewer = pr_flow.GitHubPlatform(
        token="ghp_" + "f" * 30,
        transport=_transport([(200, {"login": "sandbar-bot"})]))
    assert viewer.viewer_login() == "sandbar-bot"


# ---------- the workflow side: the answer drives the ticket ---------------

def _merged_poll_receipt(number=11, name="repo_a", identity="owner/repo_a"):
    observation = _merged_poll(number=number, name=name, identity=identity)
    return {"action": pr_flow.POLL_MERGED, "beat": 1, "stop": "", "detail": "",
            "requests": [observation],
            "merged": [{"repo": name, "name": name, "identity": identity,
                        "branch": "lane/x-%s" % name, "number": number,
                        "url": "https://example.invalid/pull/%d" % number,
                        "merged_at": "2026-11-03T09:10:00Z",
                        "merge_commit": "abc1234", "platform_merge": True}],
            "round": {}}


def test_pr_flow_step_c_a_platform_merge_closes_the_ticket(monkeypatch):
    """The merge of every declared request ends the ticket: the close-out archives,
    tears the lane down and finishes the merge stage citing the platform merge -
    and nothing lands locally."""
    wf, recorded = _drive_pr(monkeypatch, _requests_open_receipt(),
                             poll=_merged_poll_receipt())
    names = [n for n, _ in recorded]
    assert "merge" not in names, "a platform merge landed locally: %r" % (names,)
    assert "prepare_human_gate" not in names, names
    assert "archive_ticket" in names and "teardown_lane" in names, names
    assert wf.meta["status"] == "closed", wf.meta["status"]
    assert wf.meta["stage_state"] == "awaiting"
    flow = wf.meta["pr_flow"]
    assert flow["outcome"] == pr_flow.POLL_MERGED
    assert flow["closed_out"] is True
    assert flow["merge"]["cited"] == [
        "owner/repo_a#11 merged at 2026-11-03T09:10:00Z (commit abc1234)"], flow["merge"]
    checks = wf.meta["checks"]["merge"]
    assert checks and all(c["done"] for c in checks), checks
    assert all(c["by"] == dev_lane.PR_FLOW_MERGE_ACTOR for c in checks), checks
    assert any(h.get("stage") == "merge" and "abc1234" in h.get("summary", "")
               or "Merged on the platform" in h.get("summary", "")
               for h in wf.meta.get("handoffs") or []), wf.meta.get("handoffs")


def test_pr_flow_step_c_a_retry_after_a_merge_never_republishes(monkeypatch):
    """A second entry into the merge phase (a retry after a failed close-out) only
    finishes the close-out: the delivery act does not run again, so a merged branch
    cannot be republished as a second request."""
    wf, recorded = _drive_pr(monkeypatch, _requests_open_receipt(),
                             poll=_merged_poll_receipt())
    names = [n for n, _ in recorded]
    assert names.count("pr_flow_deliver") == 1, names
    assert names.count("pr_flow_poll") == 1, names


def test_pr_flow_step_c_a_comment_round_moves_the_ticket_back_once(monkeypatch):
    round_receipt = {"action": pr_flow.POLL_COMMENT_ROUND, "beat": 1,
                     "stop": "", "detail": "",
                     "requests": [_open_poll(comments=[{"id": "c3",
                                                        "author": "human-reviewer",
                                                        "body": "please rename it",
                                                        "created_at":
                                                        "2026-11-03T10:02:00Z"}])],
                     "merged": [],
                     "round": {"count": 1, "ids": ["c3"],
                               "comments": [{"id": "c3", "author": "human-reviewer",
                                             "body": "please rename it",
                                             "created_at": "2026-11-03T10:02:00Z",
                                             "is_bot": False}]}}
    wf, recorded = _drive_pr(monkeypatch, _requests_open_receipt(),
                             poll=round_receipt, stop_at_stage="implement")
    rounds = wf.meta.get("pr_comment_rounds") or []
    assert len(rounds) == 1, rounds
    assert rounds[0]["round"] == 1 and rounds[0]["ids"] == ["c3"]
    assert "please rename it" in wf.meta["last_rework_note"], wf.meta["last_rework_note"]
    assert wf.meta["status"] == "rework"
    assert wf.meta["stage"] == "implement", wf.meta["stage"]
    assert wf.meta["role"] == "developer"
    assert any(t.get("state") == "rework" and t.get("stage") == "implement"
               for t in wf.timeline), wf.timeline
    names = [n for n, _ in recorded]
    assert "run_integration_tests" not in names and "merge" not in names, names


def test_pr_flow_step_c_a_failed_beat_names_itself_and_keeps_the_park(monkeypatch):
    """An unanswerable poll is a NAMED state, the ticket stays parked (holding no
    slot) and the next beat asks again - it never blocks and never closes."""
    poll = {"action": "", "stop": pr_flow.POLL_STOP_PLATFORM_UNREACHABLE,
            "detail": "no route to host", "beat": 1, "requests": [], "merged": [],
            "round": {}}
    wf, recorded = _drive_pr(monkeypatch, _requests_open_receipt(), poll=poll,
                             beats=1)
    flow = wf.meta["pr_flow"]
    assert flow["last_stop"]["code"] == pr_flow.POLL_STOP_PLATFORM_UNREACHABLE
    assert flow["last_stop"]["waits_for_next_beat"] is True
    assert flow["last_stop"]["remedy"], flow["last_stop"]
    assert wf.meta["stage_state"] == pr_flow.AWAITING_REMOTE_REVIEW, (
        wf.meta["stage_state"], wf.meta.get("blocked_reason"))
    assert not wf.meta.get("blocked_reason"), wf.meta.get("blocked_reason")
    assert wf.meta["status"] != "closed"


def test_pr_flow_step_c_a_closed_request_blocks_by_name_never_closes(monkeypatch):
    poll = {"action": "", "stop": pr_flow.POLL_STOP_REQUEST_CLOSED_UNMERGED,
            "detail": "the platform closed owner/repo_a#11 WITHOUT a merge",
            "beat": 1, "requests": [], "merged": [], "round": {}}
    wf, recorded = _drive_pr(monkeypatch, _requests_open_receipt(), poll=poll,
                             beats=1)
    reason = str(wf.meta.get("blocked_reason") or "")
    assert pr_flow.POLL_STOP_REQUEST_CLOSED_UNMERGED in reason, reason
    assert "NOT a merge" in reason and "remedy" in reason, reason
    assert wf.meta["status"] != "closed", "a closed request closed the ticket"
    assert wf.meta.get("pr_flow", {}).get("outcome") != pr_flow.POLL_MERGED


def test_pr_flow_step_c_a_pre_step_c_history_replays_without_a_timer(monkeypatch):
    """Replay discipline: with the step (c) marker absent the park records the wake
    and re-parks - it schedules no timer and no poll, exactly as step (b) did."""
    wf, recorded = _drive_pr(
        monkeypatch, _requests_open_receipt(),
        seed_wake={"source": "poller", "note": "beat 3", "reported": {"state": "open"}},
        patches={dev_lane.pr_flow.PR_FLOW_DELIVERY_PATCH_ID})
    names = [n for n, _ in recorded]
    assert "pr_flow_poll" not in names, (
        "a history recorded before the step (c) marker scheduled a poll: %r" % (names,))
    states = [t.get("state") for t in wf.timeline]
    assert pr_flow.REMOTE_REVIEW_WAKE in states, states
    assert wf.meta["stage_state"] == pr_flow.AWAITING_REMOTE_REVIEW
    assert "outcome" not in wf.meta["pr_flow"], (
        "a pre-step-(c) replay judged the platform answer: %r"
        % (wf.meta["pr_flow"],))


# ---------- the tool-face entry: only the poller may wake the park --------

def test_pr_flow_step_c_the_wake_entry_is_the_ticket_face_and_the_poller(monkeypatch):
    """`client.remote_review_wake` is the wake's entry (this module implements every
    ticket op), it sends the workflow's own wake signal, and the source it stamps is
    the one `pr_flow.remote_review_exit` accepts - every other source is refused."""
    import client

    recorded = []

    class _Handle:
        async def signal(self, name, payload=None):
            recorded.append((name, payload))

    class _Client:
        def get_workflow_handle(self, tid):
            recorded.append(("handle", tid))
            return _Handle()

    async def _connect():
        return _Client()

    monkeypatch.setattr(client, "_connect", _connect)
    out = asyncio.run(client.remote_review_wake("t261103ut", "beat 7"))
    assert out["ok"] is True, out
    assert ("handle", "t261103ut") in recorded
    sent = [r for r in recorded if r[0] == client.REMOTE_REVIEW_WAKE_SIGNAL]
    assert sent and sent[0][1]["source"] == pr_flow.POLLER_SOURCE, recorded
    assert client.REMOTE_REVIEW_WAKE_SIGNAL == "remote_review_update"
    # The workflow carries a handler with that exact name (the entry cannot drift).
    assert "def %s(" % client.REMOTE_REVIEW_WAKE_SIGNAL in DEV_LANE_PY.read_text(
        encoding="utf-8")
    # And the judgement refuses every other source BY NAME.
    for bad in ({"source": "sign", "note": "host signed"},
                {"source": "advance"}, {"source": ""}, "not-a-payload"):
        decision = pr_flow.remote_review_exit(bad)
        assert decision.accepted is False, bad
        assert "poller" in decision.reason, decision.reason

    # Failures are named receipts, never raises.
    empty = asyncio.run(client.remote_review_wake("", "note"))
    assert empty["ok"] is False and "ticket id" in empty["error"]

    class _Broken:
        def get_workflow_handle(self, tid):
            raise RuntimeError("no such workflow")

    async def _broken():
        return _Broken()

    monkeypatch.setattr(client, "_connect", _broken)
    failed = asyncio.run(client.remote_review_wake("t-ghost", "beat 8"))
    assert failed["ok"] is False and "no such workflow" in failed["error"]


# ---------- the activity shell (the seam a workflow may not touch) --------

def _activity_payload(**over):
    base = {"ticket_id": "t261103ut", "project": "proj-alpha",
            "worktree": "", "requests": _parked(),
            "since": "2026-11-03T09:00:00+00:00", "handled_comment_ids": [],
            "beat": 2}
    base.update(over)
    return base


def test_pr_flow_step_c_the_poll_activity_answers_a_named_stop_when_the_switch_is_off(
        monkeypatch):
    """The operator turned the flow off while the ticket was parked: the beat comes
    back as a named stop for a human, never as an endless quiet wait."""
    import agent_activities as aa

    monkeypatch.setattr(pr_flow, "read_switch",
                        lambda *a, **k: pr_flow.SwitchDecision(
                            enabled=False, reason="off", repositories=(),
                            declaration="/sandbox/projects/proj-alpha/project.yaml"))
    out = asyncio.run(aa.pr_flow_poll(_activity_payload()))
    assert out["stop"] == pr_flow.POLL_STOP_SWITCH_OFF, out
    assert out["action"] == ""
    assert pr_flow.poll_stop_keeps_waiting(out["stop"]) is False


def test_pr_flow_step_c_the_poll_activity_asks_the_platform_once_per_beat(monkeypatch):
    """The activity resolves the credential and the platform inside itself, asks
    the platform once, and returns a scrubbed receipt (never the token)."""
    import agent_activities as aa

    fake = _FakePollPlatform(answers={
        11: _open_poll(comments=[{"id": "c1", "author": "human-reviewer",
                                  "body": "please rename",
                                  "created_at": "2026-11-03T10:00:00Z"}])},
        login="sandbar-bot")
    monkeypatch.setattr(pr_flow, "read_switch",
                        lambda *a, **k: pr_flow.SwitchDecision(
                            enabled=True, reason="on",
                            repositories=("owner/repo_a",),
                            declaration="/sandbox/projects/proj-alpha/project.yaml"))
    monkeypatch.setattr(pr_flow, "resolve_credential",
                        lambda **k: pr_flow.Credential(secret="ghp_" + "a" * 30))
    monkeypatch.setattr(pr_flow, "platform_from_credential",
                        lambda credential, **k: fake)
    out = asyncio.run(aa.pr_flow_poll(_activity_payload()))
    assert out["action"] == pr_flow.POLL_COMMENT_ROUND, out
    assert [c["id"] for c in out["round"]["comments"]] == ["c1"], out["round"]
    assert fake.calls == [("owner/repo_a", 11)], fake.calls
    assert "ghp_" not in json.dumps(out), "the token rode out on the receipt"
    assert aa.pr_flow_poll in aa.ALL_AGENT_ACTIVITIES


def test_pr_flow_step_c_the_poll_activity_maps_an_unbuildable_client_to_a_beat(monkeypatch):
    import agent_activities as aa

    monkeypatch.setattr(pr_flow, "read_switch",
                        lambda *a, **k: pr_flow.SwitchDecision(
                            enabled=True, reason="on",
                            repositories=("owner/repo_a",),
                            declaration="/sandbox/projects/proj-alpha/project.yaml"))

    def _boom(**k):
        raise RuntimeError("no sandbox home")

    monkeypatch.setattr(pr_flow, "resolve_credential", _boom)
    out = asyncio.run(aa.pr_flow_poll(_activity_payload()))
    assert out["stop"] == pr_flow.POLL_STOP_PLATFORM_UNREACHABLE, out
    assert pr_flow.poll_stop_keeps_waiting(out["stop"]) is True


def test_pr_flow_step_c_a_quiet_beat_does_not_grow_the_history(monkeypatch):
    """Three quiet beats update the face but mark the timeline once: a beat every
    five minutes must not grow the ticket history without bound."""
    poll = {"action": pr_flow.POLL_STILL_OPEN, "beat": 1, "stop": "", "detail": "",
            "requests": [_open_poll()], "merged": [], "round": {}}
    wf, _recorded = _drive_pr(monkeypatch, _requests_open_receipt(), poll=poll,
                              beats=3)
    marks = [t for t in wf.timeline
             if t.get("state") == pr_flow.AWAITING_REMOTE_REVIEW]
    assert len(marks) == 2, (
        "expected the park entry plus ONE still-open mark for three quiet beats, "
        "got %d: %r" % (len(marks), [t.get("reason") for t in marks]))
    assert wf.meta["pr_flow"]["last_beat"] == 3, wf.meta["pr_flow"]["last_beat"]
    assert wf.meta["stage_state"] == pr_flow.AWAITING_REMOTE_REVIEW


def test_pr_flow_step_c_a_stop_wins_over_an_action_in_one_receipt():
    """A receipt that claims an action AND a stop is read as the stop: no receipt
    can close a ticket by carrying the word "merged" on the side."""
    raw = {"action": pr_flow.POLL_MERGED,
           "stop": pr_flow.POLL_STOP_ANSWER_AMBIGUOUS, "beat": 2}
    verdict = pr_flow.poll_verdict_from(raw)
    assert verdict.stop == pr_flow.POLL_STOP_ANSWER_AMBIGUOUS
    assert verdict.action == pr_flow.POLL_MERGED     # the decoder is faithful
    assert pr_flow.poll_text(verdict, "t").startswith(
        "review-request poll stopped"), pr_flow.poll_text(verdict, "t")


def test_pr_flow_step_c_an_unreadable_receipt_is_a_failed_beat():
    for raw in ({}, {"beat": 4}, "not-a-receipt", None):
        verdict = pr_flow.poll_verdict_from(raw)
        assert verdict.stop == pr_flow.POLL_STOP_ANSWER_AMBIGUOUS, raw
        assert pr_flow.poll_stop_keeps_waiting(verdict.stop), raw


def test_pr_flow_step_c_a_round_needs_to_know_which_comments_are_ours():
    """Without the credential's login the poll cannot tell our own words apart, so
    it refuses to form a round (a bounce of our own comments would restart the work
    forever). The next beat asks again."""
    platform = _FakePollPlatform(answers={11: _open_poll(comments=[
        {"id": "c1", "author": "human-reviewer", "body": "please rename",
         "created_at": "2026-11-03T10:00:00Z"}])})
    verdict = pr_flow.poll_parked(platform, _parked(), beat=1)
    assert verdict.action == ""
    assert verdict.stop == pr_flow.POLL_STOP_ANSWER_AMBIGUOUS, verdict.stop
    assert "login" in verdict.detail, verdict.detail


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


# ===========================================================================
# t261103-13 (step (d) wired into the step (c) close-out) - a platform merge
# never ends a ticket before this machine's target branch catches up
#
# The section lives in this file for the same reason steps (b), (c) and (d) do:
# the write set is server/engine/ only, the shared anchor manifest
# (integration/test_anchors.json) is owned by the integration role, and a NEW
# server/engine/tests/test_*.py would be the L16 "anchor missing" error. This file
# is already anchored and already carries the whole review-request flow, of which
# this wiring is the last link.
#
# intent: the platform's merge settles the delivery but does not catch this
# machine up. The close-out must therefore ask the EXISTING reconciliation act
# first, per repository, and close only when every declared repository is proved
# caught up; every named stop (local drift, content mismatch, partial
# reconciliation, missing branch, unreachable remote) keeps the ticket OPEN with
# its reason and remedy on the ticket face. A history recorded before this wiring
# replays step (c)'s close-out verbatim (no reconciliation command). The park's
# beat interval and wake entry come from the project declaration, with the shipped
# values as the defaults, and a malformed value is a named refusal.
#
# hermetic: the git runner and the platform are injected (or a real LOCAL repo is
# used through file transport), the credential is never resolved from ~/.sandbar,
# no socket, no docker, no port 3099, no Temporal, no real project ledger.
# ===========================================================================

import inspect  # noqa: E402  (the source locks below read one method's own text)

#: One reconciled repository, in the act's own row shape.
RECONCILE_ROW_A = {"repo": "repo_a", "name": "repo_a", "identity": "owner/repo_a",
                   "target": "main", "remote": "origin", "state": "reconciled",
                   "stop": "", "remedy": "", "before": SHA_A, "after": SHA_B,
                   "head": SHA_B, "advanced": True, "head_matches_reported": True,
                   "detail": "fast-forwarded 'refs/heads/main' from aaaaaaaaaaaa "
                             "to bbbbbbbbbbbb; tree equals the platform-reported tree"}
RECONCILE_ROW_B = {"repo": "repo_b", "name": "repo_b", "identity": "owner/repo_b",
                   "target": "main", "remote": "origin", "state": "reconciled",
                   "stop": "", "remedy": "", "before": SHA_C, "after": SHA_A,
                   "head": SHA_A, "advanced": True, "head_matches_reported": True,
                   "detail": "fast-forwarded 'refs/heads/main' from cccccccccccc "
                             "to aaaaaaaaaaaa"}


def _reconciled_receipt(rows=None):
    rows = [dict(r) for r in (rows or (RECONCILE_ROW_A,))]
    return {"state": pr_flow.RECONCILE_RECONCILED, "stop": "",
            "detail": "%d of %d repositories fast-forwarded and content-verified"
                      % (len(rows), len(rows)),
            "terminal": True, "keeps_ticket_open": False, "retryable": False,
            "repositories": rows}


def _reconcile_stop_receipt(code, rows=None, detail="a named stop"):
    return {"state": pr_flow.ACTION_STOP, "stop": code, "detail": detail,
            "terminal": False, "keeps_ticket_open": True, "retryable": True,
            "repositories": [dict(r) for r in (rows or (RECONCILE_ROW_A,))]}


def _partial_receipt():
    stopped = dict(RECONCILE_ROW_B)
    stopped.update({"state": pr_flow.REPO_STATE_STOPPED,
                    "stop": pr_flow.RECONCILE_STOP_LOCAL_DRIFT,
                    "remedy": pr_flow.stop_remedy(pr_flow.RECONCILE_STOP_LOCAL_DRIFT),
                    "detail": "the local branch is not an ancestor of the fetched head"})
    return {"state": pr_flow.RECONCILE_PARTIAL,
            "stop": pr_flow.RECONCILE_STOP_PARTIAL_RECONCILIATION,
            "detail": "1 of 2 repositories reconciled (repo_a) and 1 stopped (repo_b)",
            "terminal": False, "keeps_ticket_open": True, "retryable": True,
            "repositories": [dict(RECONCILE_ROW_A), stopped]}


def _names(recorded):
    return [n for n, _ in recorded]


# ---------- 1. the close-out order: reconcile, then archive, then teardown ---

def test_pr_flow_step_d_the_close_out_reconciles_before_it_closes(monkeypatch):
    """A merged delivery closes ONLY after the reconciliation ran, and the receipt
    names every reconciled repository."""
    wf, recorded = _drive_pr(monkeypatch, _requests_open_receipt(),
                             poll=_merged_poll_receipt(),
                             reconcile=_reconciled_receipt(
                                 [RECONCILE_ROW_A, RECONCILE_ROW_B]))
    names = _names(recorded)
    assert "pr_flow_reconcile" in names, names
    assert names.index("pr_flow_reconcile") < names.index("archive_ticket"), (
        "the ticket was archived before the local branch was reconciled: %r" % (names,))
    assert names.index("pr_flow_reconcile") < names.index("teardown_lane"), names
    assert wf.meta["status"] == "closed", wf.meta["status"]
    record = wf.meta["pr_flow"]["reconcile"]
    assert record["reconciled"] is True and record["keeps_ticket_open"] is False, record
    # the receipt names each reconciled repository, twice over: on the face and in
    # the merge stage's evidence/handoff (a reader must not need the console).
    assert len(record["cited"]) == 2, record
    assert "repo_a" in record["cited"][0] and "owner/repo_a" in record["cited"][0]
    assert "repo_b" in record["cited"][1]
    evidence = " ".join(str(c.get("evidence") or "")
                        for c in wf.meta["checks"]["merge"])
    assert "reconciled" in evidence and "repo_a" in evidence and "repo_b" in evidence, (
        evidence)
    summaries = [str(h.get("summary") or "") for h in wf.meta.get("handoffs") or []]
    assert any("reconciled locally" in s and "repo_a" in s for s in summaries), summaries
    # the platform merge is still the acceptance record
    assert wf.meta["pr_flow"]["merge"]["cited"] == [
        "owner/repo_a#11 merged at 2026-11-03T09:10:00Z (commit abc1234)"]


def test_pr_flow_step_d_a_retry_after_a_failed_archive_does_not_reconcile_twice(
        monkeypatch):
    """A retry of the close-out after a failed archive repeats only what did not
    finish: it archives again, and it does NOT fast-forward a branch it already
    proved caught up. (The window simulated here is the measured one: the
    reconciliation succeeded and the archive did not.)"""
    wf, recorded = _drive_pr(monkeypatch, _requests_open_receipt(),
                             poll=_merged_poll_receipt())
    assert _names(recorded).count("pr_flow_reconcile") == 1, _names(recorded)
    # the failed-archive window: nothing was archived, so the close-out did not
    # record its completion - and the reconcile answer is already on the face.
    wf.meta["pr_flow"].pop("closed_out", None)
    assert asyncio.run(wf._pr_flow_finish_close()) == "done"
    names = _names(recorded)
    assert names.count("pr_flow_reconcile") == 1, (
        "the retry fast-forwarded the branch again: %r" % (names,))
    assert names.count("archive_ticket") == 2, names
    evidence = " ".join(str(c.get("evidence") or "")
                        for c in wf.meta["checks"]["merge"])
    assert "reconciled" in evidence and "repo_a" in evidence, evidence


# ---------- 2. every reconcile stop keeps the ticket open, named -----------

@pytest.mark.parametrize("code", [
    pr_flow.RECONCILE_STOP_LOCAL_DRIFT,
    pr_flow.RECONCILE_STOP_CONTENT_MISMATCH,
    pr_flow.RECONCILE_STOP_BRANCH_MISSING,
    pr_flow.RECONCILE_STOP_REMOTE_UNREACHABLE,
    pr_flow.RECONCILE_STOP_SWITCH_OFF,
    pr_flow.RECONCILE_STOP_RECEIPT_UNREADABLE,
    pr_flow.RECONCILE_STOP_SET_UNUSABLE,
])
def test_pr_flow_step_d_a_reconcile_stop_keeps_the_ticket_open(monkeypatch, code):
    """The measured fault this ticket closes: the ticket closed while the local
    branch stayed behind. Every stop now keeps it open, named, with its remedy -
    and nothing is archived or torn down while the branch is unproved."""
    wf, recorded = _drive_pr(monkeypatch, _requests_open_receipt(),
                             poll=_merged_poll_receipt(),
                             reconcile=_reconcile_stop_receipt(code))
    names = _names(recorded)
    assert "archive_ticket" not in names, (
        "%s: the ticket was archived although the reconciliation stopped" % code)
    assert "teardown_lane" not in names, (code, names)
    assert wf.meta["status"] != "closed", "%s: the ticket closed anyway" % code
    reason = str(wf.meta.get("blocked_reason") or "")
    assert code in reason, (code, reason)
    assert pr_flow.stop_remedy(code) in reason, (code, reason)
    assert "post-merge reconciliation" in reason and "ticket stays open" in reason, reason
    record = wf.meta["pr_flow"]["reconcile"]
    assert record["keeps_ticket_open"] is True and record["stop"] == code, record
    assert record["remedy"], record
    assert any(t.get("state") == "blocked" for t in wf.timeline), wf.timeline
    assert wf.meta["stage"] == "merge", wf.meta["stage"]


def test_pr_flow_step_d_a_partial_reconciliation_names_both_repositories(monkeypatch):
    """A partly reconciled delivery is the named non-terminal state: the caught-up
    repository and the stopped one are both on the face, and the ticket waits."""
    wf, recorded = _drive_pr(monkeypatch, _requests_open_receipt(),
                             poll=_merged_poll_receipt(), reconcile=_partial_receipt())
    reason = str(wf.meta.get("blocked_reason") or "")
    assert pr_flow.RECONCILE_STOP_PARTIAL_RECONCILIATION in reason, reason
    assert "repo_a" in reason and "repo_b" in reason, reason
    assert wf.meta["status"] != "closed"
    assert "archive_ticket" not in _names(recorded)


# ---------- 3. replay safety: a pre-wiring history closes as it recorded ----

def test_pr_flow_step_d_a_pre_wiring_history_closes_without_reconciling(monkeypatch):
    """A history recorded before this wiring carries the delivery and poll markers
    and nothing else: it replays step (c)'s close-out verbatim - archive, teardown,
    closed - and schedules NO reconciliation command."""
    wf, recorded = _drive_pr(
        monkeypatch, _requests_open_receipt(), poll=_merged_poll_receipt(),
        patches={pr_flow.PR_FLOW_DELIVERY_PATCH_ID, pr_flow.PR_FLOW_POLL_PATCH_ID})
    names = _names(recorded)
    assert "pr_flow_reconcile" not in names, (
        "a pre-wiring history reconciled retroactively: %r" % (names,))
    assert "archive_ticket" in names and "teardown_lane" in names, names
    assert wf.meta["status"] == "closed", wf.meta["status"]
    assert "reconcile" not in wf.meta["pr_flow"], wf.meta["pr_flow"]
    assert "options" not in wf.meta["pr_flow"], (
        "a pre-wiring history gained a face key it never recorded: %r"
        % (wf.meta["pr_flow"],))


def test_pr_flow_step_d_the_wiring_is_gated_at_exactly_one_place():
    """Source lock: the reconciliation is called from the close-out and nowhere
    else, behind its own patched() marker, and the wiring builds no git command."""
    dev_src = DEV_LANE_PY.read_text(encoding="utf-8")
    marker = "workflow.patched(pr_flow.PR_FLOW_RECONCILE_PATCH_ID)"
    assert dev_src.count(marker) == 2, (
        "the wiring's replay gate must guard exactly two places: the close-out's "
        "reconciliation and the park-option stamping (found %d)" % dev_src.count(marker))
    close_src = inspect.getsource(dev_lane.DevLaneWorkflow._pr_flow_finish_close)
    assert ("if " + marker + ":") in close_src, close_src
    assert close_src.index(marker) < close_src.index("archive_ticket"), (
        "the reconciliation gate sits after the archive: the ticket could be "
        "archived before the local branch was proved caught up")
    assert dev_src.count("_pr_flow_reconcile_before_close(") == 2, (
        "the close-out must call the reconciliation exactly once")
    body = inspect.getsource(dev_lane.DevLaneWorkflow._pr_flow_reconcile_before_close)
    assert "pr_flow_reconcile" in body and "execute_activity" in body, body
    assert body.count("execute_activity") == 1, (
        "the wiring schedules more than the one act: %r" % (body,))
    for token in ("git ", "subprocess", "_git_argv", "rev-parse", "--ff-only"):
        assert token not in body, (
            "the wiring builds its own git command (%r): the act is the one "
            "implementation" % token)


# ---------- 4. no destructive git verb on the close-out path ----------------

class _RecordingGit:
    """A git runner that records every argv the act's chokepoint built, and hands
    each one to ONE scripted repository (so its modelled branch state persists
    from command to command)."""

    def __init__(self, inner=None):
        self.inner = inner or _FakeGit()
        self.calls = []

    def __call__(self, argv, env, timeout):
        self.calls.append(list(argv))
        return self.inner(argv, env, timeout)

    def verbs(self):
        return [argv[3] for argv in self.calls]


def _reconcile_activity_payload(worktree, requests=None, **over):
    base = {"ticket_id": "t261103ut", "project": "proj-alpha",
            "worktree": str(worktree),
            "requests": [dict(r) for r in (requests if requests is not None else [
                {"repo": "", "name": "root", "identity": "owner/repo_a",
                 "branch": "lane/x", "number": 11}])],
            "target_branch": "main"}
    base.update(over)
    return base


def _on_switch(**over):
    decision = pr_flow.SwitchDecision(
        enabled=True, reason="on", repositories=("owner/repo_a",),
        declaration="/sandbox/projects/proj-alpha/project.yaml",
        beat_seconds=over.get("beat_seconds", 0),
        wake_entry=over.get("wake_entry", ""))
    return decision


def _wire_activity(monkeypatch, platform, switch=None):
    import agent_activities as aa
    monkeypatch.setattr(pr_flow, "read_switch",
                        lambda *a, **k: switch or _on_switch())
    monkeypatch.setattr(pr_flow, "resolve_credential",
                        lambda **k: pr_flow.Credential(secret="ghp_" + "a" * 30))
    monkeypatch.setattr(pr_flow, "platform_from_credential",
                        lambda credential, **k: platform)
    return aa


def test_pr_flow_step_d_the_close_out_path_issues_no_destructive_git_verb(
        tmp_path, monkeypatch):
    """The property the design forbids breaking, measured on the path the close-out
    actually takes: the act's chokepoint built every command line, the only
    mutating one is a fast-forward to the merged head, and no command in the list
    rewrites history, forces an update or discards work."""
    git = _RecordingGit()
    monkeypatch.setattr(pr_flow, "_default_git_runner", git)
    aa = _wire_activity(monkeypatch, _FakeMergePlatform(sha=SHA_B, tree=TREE_B))
    lane = tmp_path / "lane"
    lane.mkdir()
    out = asyncio.run(aa.pr_flow_reconcile(_reconcile_activity_payload(lane)))
    assert out["state"] == pr_flow.RECONCILE_RECONCILED, out
    assert out["keeps_ticket_open"] is False, out
    assert git.calls, "the act issued no git command at all"
    for argv in git.calls:
        assert argv[0] == "git" and argv[1] == "-C", argv
        verb = argv[3]
        assert verb in pr_flow.ALLOWED_GIT_VERBS, argv
        for token in argv[4:]:
            assert token not in pr_flow.FORBIDDEN_GIT_VERBS, argv
            assert token not in pr_flow.FORBIDDEN_GIT_ARGS, argv
            assert not token.startswith(pr_flow.FORCED_UPDATE_PREFIX), argv
    assert git.verbs().count("merge") == 1, git.calls
    merge_argv = [argv for argv in git.calls if argv[3] == "merge"][0]
    assert merge_argv[4:] == ["--ff-only", SHA_B], merge_argv
    # every command ran in the lane this ticket owns
    assert {argv[2] for argv in git.calls} == {str(lane)}, git.calls
    # and the act is the one implementation: the shell calls it by name
    shell = inspect.getsource(aa.pr_flow_reconcile)
    assert "pr_flow.reconcile_after_merge(" in shell, shell
    assert "_git_argv" not in shell and "subprocess" not in shell, shell
    assert aa.pr_flow_reconcile in aa.ALL_AGENT_ACTIVITIES


def test_pr_flow_step_d_the_reconcile_activity_refuses_before_any_git_call(
        tmp_path, monkeypatch):
    """The shell's own refusals: a switch turned off while parked, and a park
    record that resolves outside the lane. Both keep the ticket open by name and
    touch neither git nor the platform."""
    git = _RecordingGit()
    monkeypatch.setattr(pr_flow, "_default_git_runner", git)
    platform = _FakeMergePlatform(sha=SHA_B, tree=TREE_B)
    lane = tmp_path / "lane"
    lane.mkdir()

    off = _wire_activity(monkeypatch, platform,
                         switch=pr_flow.SwitchDecision(enabled=False, reason="off",
                                                       repositories=(),
                                                       declaration="project.yaml"))
    out = asyncio.run(off.pr_flow_reconcile(_reconcile_activity_payload(lane)))
    assert out["stop"] == pr_flow.RECONCILE_STOP_SWITCH_OFF, out
    assert out["keeps_ticket_open"] is True
    assert pr_flow.stop_remedy(pr_flow.RECONCILE_STOP_SWITCH_OFF) not in (
        "retry after the named condition is removed",)

    on = _wire_activity(monkeypatch, platform)
    escaping = asyncio.run(on.pr_flow_reconcile(_reconcile_activity_payload(
        lane, [{"repo": "../outside", "name": "root", "identity": "owner/repo_a"}])))
    assert escaping["stop"] == pr_flow.RECONCILE_STOP_SET_UNUSABLE, escaping
    assert "escapes the lane" in escaping["detail"], escaping
    assert escaping["keeps_ticket_open"] is True
    norequests = asyncio.run(on.pr_flow_reconcile(_reconcile_activity_payload(
        lane, [])))
    assert norequests["stop"] == pr_flow.RECONCILE_STOP_SET_UNUSABLE, norequests
    assert git.calls == [], git.calls
    assert platform.calls == [], platform.calls


def test_pr_flow_step_d_the_activity_reconciles_a_real_repository(real_clone,
                                                                 monkeypatch):
    """End to end on a real repository, through the activity the close-out calls:
    the local branch ends on the merged content (file bytes included), and the
    worktree stays clean."""
    origin, seed, clone = real_clone
    _advance_origin(seed)
    head = _git(["rev-parse", "refs/heads/main"], cwd=origin)
    tree = _git(["rev-parse", "refs/heads/main^{tree}"], cwd=origin)
    assert _git(["rev-parse", "refs/heads/main"], cwd=clone) != head

    aa = _wire_activity(monkeypatch, _FakeMergePlatform(sha=head, tree=tree))
    out = asyncio.run(aa.pr_flow_reconcile(_reconcile_activity_payload(
        clone, [{"repo": ".", "name": "root", "identity": "owner/repo_a",
                 "branch": "lane/x", "number": 11}])))
    assert out["state"] == pr_flow.RECONCILE_RECONCILED, out
    assert _git(["rev-parse", "refs/heads/main"], cwd=clone) == head
    assert _git(["rev-parse", "refs/heads/main^{tree}"], cwd=clone) == tree
    assert (clone / "second.txt").read_text(encoding="utf-8") == "second\n"
    assert _git(["status", "--porcelain"], cwd=clone) == ""
    assert out["repositories"][0]["advanced"] is True


# ---------- 5. the wiring's decoder: silence is never a close --------------

def test_pr_flow_step_d_an_unreadable_receipt_is_a_refusal_not_a_close():
    for raw in ({}, {"state": "whatever"}, "not-a-receipt", None, 7):
        verdict = pr_flow.reconcile_verdict_from(raw)
        assert pr_flow.reconcile_allows_close(verdict) is False, raw
        record = pr_flow.reconcile_record(verdict, ticket_id="t", at_iso="now")
        assert record["reconciled"] is False and record["keeps_ticket_open"] is True
        assert record["stop"] == pr_flow.RECONCILE_STOP_RECEIPT_UNREADABLE, record
        assert record["remedy"] and record["detail"], record
    # a receipt that says both "reconciled" and "keep me open" cannot close
    contradictory = pr_flow.reconcile_verdict_from({
        "state": pr_flow.RECONCILE_RECONCILED, "keeps_ticket_open": True,
        "repositories": [dict(RECONCILE_ROW_A)]})
    assert pr_flow.reconcile_allows_close(contradictory) is False
    # and the act's own answer round-trips
    ok = pr_flow.reconcile_verdict_from(_reconciled_receipt())
    assert pr_flow.reconcile_allows_close(ok) is True
    citation = pr_flow.reconcile_citation(
        pr_flow.reconcile_record(ok, ticket_id="t", at_iso="now"))
    assert "owner/repo_a" in citation and "main" in citation, citation


def test_pr_flow_step_d_the_off_answer_is_not_a_close_permission():
    """The act answers `not_applicable` when the switch is off. On the close-out
    path that must never read as "the branch already caught up"."""
    off = pr_flow.reconcile_verdict_from({
        "state": pr_flow.RECONCILE_OFF, "detail": "the project switch is off",
        "terminal": False, "keeps_ticket_open": False, "repositories": []})
    assert pr_flow.reconcile_allows_close(off) is False
    record = pr_flow.reconcile_record(off, ticket_id="t", at_iso="now")
    assert record["keeps_ticket_open"] is True and record["cited"] == []


# ---------- 6. the beat interval and the wake entry come from the declaration

def _declaration(**block):
    lines = ["github_pr:", "  enabled: true", "  repositories:", "    - owner/repo_a"]
    for key, value in block.items():
        lines.insert(2, "  %s: %s" % (key, value))
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize("text,beat,wake,source", [
    (_declaration(), pr_flow.DEFAULT_BEAT_SECONDS, pr_flow.DEFAULT_WAKE_ENTRY,
     "default"),
    (_declaration(beat_seconds=120), 120, pr_flow.DEFAULT_WAKE_ENTRY, "declaration"),
    (_declaration(wake_entry="my-poller --ticket <ticket_id>"),
     pr_flow.DEFAULT_BEAT_SECONDS, "my-poller --ticket <ticket_id>", "declaration"),
    (_declaration(beat_seconds=600, wake_entry="'/opt/bin/wake <ticket_id>'"),
     600, "/opt/bin/wake <ticket_id>", "declaration"),
    (_declaration(beat_seconds=pr_flow.MIN_BEAT_SECONDS),
     pr_flow.MIN_BEAT_SECONDS, pr_flow.DEFAULT_WAKE_ENTRY, "declaration"),
    (_declaration(beat_seconds=pr_flow.MAX_BEAT_SECONDS),
     pr_flow.MAX_BEAT_SECONDS, pr_flow.DEFAULT_WAKE_ENTRY, "declaration"),
])
def test_pr_flow_step_d_the_park_options_resolve_from_the_declaration(
        text, beat, wake, source):
    """Truth table: a declaration that names neither keeps the shipped values, a
    declared value is used as written, and the face says where each came from."""
    switch = pr_flow.parse_switch(text)
    assert switch.enabled is True, switch
    options = switch.options()
    assert options.beat_seconds == beat, options
    assert options.wake_entry == wake, options
    assert options.source == source, options
    assert options.face()["beat_seconds"] == beat
    # and the option never rides on the switch's own face (that face is asserted
    # key for key by the step (a) section)
    assert set(switch.face()) == {"enabled", "reason", "repositories", "declaration"}


@pytest.mark.parametrize("key,value,code", [
    ("beat_seconds", "abc", pr_flow.STOP_DECLARATION_BEAT_INVALID),
    ("beat_seconds", "-5", pr_flow.STOP_DECLARATION_BEAT_INVALID),
    ("beat_seconds", "5", pr_flow.STOP_DECLARATION_BEAT_INVALID),
    ("beat_seconds", "0", pr_flow.STOP_DECLARATION_BEAT_INVALID),
    ("beat_seconds", "120.5", pr_flow.STOP_DECLARATION_BEAT_INVALID),
    ("beat_seconds", str(pr_flow.MAX_BEAT_SECONDS + 1),
     pr_flow.STOP_DECLARATION_BEAT_INVALID),
    ("wake_entry", "''", pr_flow.STOP_DECLARATION_WAKE_INVALID),
    ("wake_entry", "a\tb", pr_flow.STOP_DECLARATION_WAKE_INVALID),
    ("wake_entry", "x" * (pr_flow.MAX_WAKE_ENTRY_CHARS + 1),
     pr_flow.STOP_DECLARATION_WAKE_INVALID),
])
def test_pr_flow_step_d_a_malformed_park_option_is_a_named_refusal(key, value, code):
    """A present-but-unusable value is never read as "use the default": the
    refusal names the key, and its remedy names the key too."""
    with pytest.raises(pr_flow.PrFlowStop) as e:
        pr_flow.parse_switch(_declaration(**{key: value}))
    assert e.value.code == code, (key, value, e.value.code)
    assert key in e.value.message(), e.value.message()
    assert key in pr_flow.stop_remedy(code), pr_flow.stop_remedy(code)
    assert pr_flow.stop_remedy(code) != "retry after the named condition is removed"


def test_pr_flow_step_d_the_park_uses_the_declared_beat(monkeypatch):
    """The park's timer is the project's declared interval, and the face records
    both options so an outside poller knows how to wake this ticket."""
    receipt = dict(_requests_open_receipt())
    receipt["options"] = {"beat_seconds": 120,
                          "wake_entry": "my-poller --ticket <ticket_id>",
                          "source": "declaration"}
    poll = {"action": pr_flow.POLL_STILL_OPEN, "beat": 1, "stop": "", "detail": "",
            "requests": [_open_poll()], "merged": [], "round": {}}
    wf, recorded = _drive_pr(monkeypatch, receipt, poll=poll, beats=2)
    timeouts = {arg for name, arg in recorded if name == "wait_condition" and arg}
    assert timeouts == {120}, timeouts
    opts = wf.meta["pr_flow"]["options"]
    assert opts["beat_seconds"] == 120, opts
    assert opts["wake_entry"] == "my-poller --ticket <ticket_id>", opts


def test_pr_flow_step_d_an_older_receipt_parks_on_the_shipped_beat(monkeypatch):
    """Replay: a delivery receipt recorded before the option existed carries no
    options at all, and the park must then beat exactly as it always did."""
    poll = {"action": pr_flow.POLL_STILL_OPEN, "beat": 1, "stop": "", "detail": "",
            "requests": [_open_poll()], "merged": [], "round": {}}
    wf, recorded = _drive_pr(monkeypatch, _requests_open_receipt(), poll=poll,
                             beats=1)
    timeouts = {arg for name, arg in recorded if name == "wait_condition" and arg}
    assert timeouts == {pr_flow.POLL_BEAT_SECONDS}, timeouts
    opts = wf.meta["pr_flow"]["options"]
    assert opts["beat_seconds"] == pr_flow.POLL_BEAT_SECONDS, opts
    assert opts["source"] == "default", opts


def test_pr_flow_step_d_an_unusable_recorded_option_falls_back_and_says_so():
    """The receipt decoder's own edge: a value that cannot come from a validated
    declaration (a hand-edited face) falls back to the shipped value AND names the
    fallback, so it is never a silent substitution."""
    for raw in (None, {}, {"options": None}, {"options": []}, {"options": {}}):
        options = pr_flow.flow_options_from(raw)
        assert options.beat_seconds == pr_flow.DEFAULT_BEAT_SECONDS, raw
        assert options.wake_entry == pr_flow.DEFAULT_WAKE_ENTRY, raw
    bad = pr_flow.flow_options_from({"options": {"beat_seconds": "soon",
                                                 "wake_entry": "\x00"}})
    assert bad.beat_seconds == pr_flow.DEFAULT_BEAT_SECONDS
    assert bad.wake_entry == pr_flow.DEFAULT_WAKE_ENTRY
    assert "fallback" in bad.source, bad
