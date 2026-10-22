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
  (b) leaving the gate (signature, rework, refused signature) re-acquires
      through the ordinary `_concurrency_gate()` before any further work — the
      ticket queues behind the existing waiters and never jumps;
  (c) every OTHER blocked stage keeps holding its slot (rule 3 unchanged: the
      blocked wait renews to human-hold, it never releases);
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

def test_leaving_the_merge_gate_reacquires_the_slot_before_merge_work(monkeypatch):
    wf, recorded = _drive_merge(monkeypatch, _patched_all_but(), park=False)
    fam = _family(recorded)
    names = [n for n, _ in fam]
    assert "concurrency_release" in names, names
    idx_rel = names.index("concurrency_release")
    assert names[idx_rel] == "concurrency_release"
    assert fam[idx_rel][1] == "merge-wait", fam
    assert "merge" in names, "the drive never reached the merge activity: %r" % (names,)
    idx_merge = names.index("merge")
    assert "concurrency_acquire" in names[idx_rel + 1:idx_merge], (
        "the ticket merged WITHOUT taking the slot back first: %r" % (names,))
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

def test_a_blocked_stage_still_renews_its_hold(monkeypatch):
    recorded = []
    stub = _make_stub(_patched_all_but(), recorded, park=False)
    monkeypatch.setattr(dev_lane, "workflow", stub)
    monkeypatch.setattr(base, "workflow", stub)
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
    asyncio.run(wf._blocked("run_integration_tests", "gate is red"))
    fam = _family(recorded)
    names = [n for n, _ in fam]
    assert "concurrency_renew" in names, (
        "a blocked stage must keep its hold (rule 3): %r" % (names,))
    assert fam[names.index("concurrency_renew")][1] == "human-gate", fam
    assert "concurrency_release" not in names, (
        "a blocked stage released its slot — rule 3 broken: %r" % (names,))


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
            gate_at = src.find("await self._concurrency_gate()", pop_at)
            assert pop_at < gate_at < merge_at, (
                "the gate exit does not take the slot back before merging: %s"
                % lane_py)


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
