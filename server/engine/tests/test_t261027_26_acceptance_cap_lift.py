#!/usr/bin/env python3
"""t261027-26 (KI-382) unit battery: the acceptance cap has a named human lift, and
the counter counts real findings only.

Measured 261027 on t261026-18: the ticket sat blocked at "acceptance walkthrough
send-back 4 rounds over limit (cap 2)" with a green gate and walkthrough reports that
named no failed acceptance item, and no human op could lift it (`op=authorize` covers
`protected_path` / `arbitration_verdict` only).

The approved plan (revision 1) lands three behaviours:

  * the blocked face names the exit (`shared.acceptance_cap_blocked_text`, shaped like
    `_ARBITRATION_CAP_EXITS`) — the exit is a cap lift carried by `op=ruling`
    (`lift=acceptance_cap report=<token> reason=<why>`), and the citation must be the
    walkthrough report the stop overrides;
  * a failed receipt is classified before any counter logic: environment refusal /
    front-door refusal / empty report = a stop with the counter untouched; a readable
    report that names no failed acceptance item = an observation, and the ticket
    proceeds to merge_check; only a named finding reaches the counter;
  * every new branch is replay-safe: the receipt classification sits behind a
    per-round `#<seq>` patch id (KI-061 shape, so in-flight tickets reach it), and the
    lift is gated on a note grammar plus new state that no pre-fix history carries.

This file is the L1 half: truth tables for the pure functions, the intake matrix on a
bare workflow shell, and the real main loop driven with stubbed activities (the
`FakeMachine` rig of test_t261026_37_fork_selfheal.py) so the counter, the observation
route and the lift consumption are proven as behaviour, not as source text.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import dev_lane  # noqa: E402
import shared  # noqa: E402
from shared import (  # noqa: E402
    HostRulingRequest,
    IntegrationRunResult,
    ReworkRequest,
    SettleLaneResult,
)

TICKET = "t26102726ut"
NOW_DT = datetime.datetime(2026, 10, 26, 12, 0, 0, tzinfo=datetime.timezone.utc)
NOW = int(NOW_DT.timestamp())
TOKEN3 = "stage_acceptance_walkthrough_gen3.json"
SRC_DL = (POC / "dev_lane.py").read_text("utf-8")
SRC_SH = (POC / "shared.py").read_text("utf-8")
SRC_AZ = (POC / "authz_gates.py").read_text("utf-8")

PASS_TABLE = "\n".join([
    "Acceptance walkthrough at HEAD ed0dc444",
    "",
    "| # | acceptance item | verdict | evidence |",
    "|---|---|---|---|",
    "| 1 | ticket face shows the named way out | PASS | blocked text names op=ruling |",
    "| 2 | counter counts real findings | PASS | reports name no item; gate fail-closed otherwise |",
    "| 3 | machine gate green | PASS | ran=2 pass=2 |",
    "| 4 | docs updated | PASS | ops doc section present |",
])
FAIL_TABLE = PASS_TABLE.replace(
    "| 2 | counter counts real findings | PASS |",
    "| 2 | counter counts real findings | FAIL |")


# ---------------------------------------------------------------------------
# T1 - the lift grammar and its validation (pure truth table)
# ---------------------------------------------------------------------------

def _lift(note, who="host", stop=TOKEN3):
    return shared.acceptance_cap_lift(note, who, stop)


def test_t1_valid_lift_records_the_citation():
    rec, err = _lift("lift=acceptance_cap report=%s reason=the remaining red is a "
                     "doc nit, signed anyway" % TOKEN3)
    assert err == "" and isinstance(rec, dict)
    assert rec["report_token"] == TOKEN3 and rec["report_gen"] == 3
    assert rec["who"] == "host" and rec["uses"] == []
    assert "signed anyway" in rec["reason"]


@pytest.mark.parametrize("note", [
    "  LIFT = acceptance_cap   report = 3   reason = ok  ",
    "context line\nlift=acceptance_cap report=3 reason=ok",
    "lift = acceptance_cap report=stage_acceptance_walkthrough_gen3.json reason=ok",
])
def test_t1_variants_are_accepted(note):
    rec, err = _lift(note)
    assert err == "" and isinstance(rec, dict) and rec["report_gen"] == 3, (rec, err)


@pytest.mark.parametrize("note", [
    "the host said the word lift= in prose, nothing else",
    "blocked on lift=approve once, long ago",
    "",
    "ordinary ruling: please re-run the gate",
])
def test_t1_notes_without_the_marker_stay_ordinary(note):
    assert _lift(note) == (None, "")


@pytest.mark.parametrize("prefix,suffix", [
    ("- ", ""), ("* ", ""), ("+ ", ""), ("1. ", ""), ("2) ", ""),
    ("> ", ""), ("`", "`"), ("```\n", "\n```"), ('"', '"'),
    # arbitration F2 (261027): emphasis and table-cell shapes were silent no-ops
    ("**", "**"), ("*", "*"), ("_", "_"), ("__", "__"), ("~~", "~~"),
    ("| ", " |"), ("(", ")"), ("[", "]"), ("    ", ""),
])
def test_t1_a_pasted_lift_line_still_arms(prefix, suffix):
    """The face prints the line and operators paste it with chat/list decoration. A
    silent no-op here would be a defect of the named exit itself (integration finding,
    261027)."""
    rec, err = _lift(prefix + "lift=acceptance_cap report=%s reason=ok" % TOKEN3 + suffix)
    assert err == "" and isinstance(rec, dict) and rec["report_gen"] == 3, (rec, err)


def test_t1_decoration_does_not_turn_prose_into_a_lift():
    # a prose mention of the word "lift=" with no grammar stays an ordinary ruling
    for note in ("the host said the word lift= in prose, nothing else",
                 "blocked on lift=approve once, long ago",
                 "- please lift the cap when you can"):
        assert _lift(note) == (None, "")


@pytest.mark.parametrize("note", [
    "- please send lift=acceptance_cap report=3 reason=ok later",
    "1. the ruling about lift=acceptance_cap is pending",
    "context: lift=acceptance_cap report=3 reason=ok",
])
def test_t1_a_mid_line_grammar_is_refused_by_name_never_silent(note):
    """Arbitration F2 (261027): the operator must never believe a lift is armed while the
    note is silently stored as an ordinary ruling."""
    rec, err = _lift(note)
    assert rec is None and err.strip(), (rec, err)
    assert "does not start a line" in err


@pytest.mark.parametrize("note,frag", [
    ("lift=acceptance-cap report=3 reason=x", "unknown lift kind"),
    ("lift=acceptance_cap reason=x", "must cite the walkthrough report"),
    ("lift=acceptance_cap report=not-a-report reason=x", "not a walkthrough report token"),
    ("lift=acceptance_cap report=stage_merge_check_gen3.json reason=x",
     "not a walkthrough report token"),
    ("lift=acceptance_cap report=stage_acceptance_walkthrough_gen9.json reason=x",
     "cite the stopped report"),
    ("lift=acceptance_cap report=%s reason=  " % TOKEN3, "missing reason"),
    ("lift=acceptance_cap report=%s" % TOKEN3, "missing reason"),
])
def test_t1_malformed_lifts_are_refused_by_name(note, frag):
    rec, err = _lift(note)
    assert rec is None and frag in err, (rec, err)


def test_t1_missing_stop_is_refused():
    rec, err = _lift("lift=acceptance_cap report=%s reason=x" % TOKEN3, stop="")
    assert rec is None and "no acceptance cap stop" in err


@pytest.mark.parametrize("who,frag", [
    ("developer", "self-authorize"),
    ("  INTEGRATION ", "self-authorize"),
    ("ops-agent", "self-authorize"),
    ("", "missing who"),
    (None, "missing who"),
    ("x" * 80, "who too long"),
])
def test_t1_agent_or_bad_identity_is_refused(who, frag):
    rec, err = _lift("lift=acceptance_cap report=%s reason=x" % TOKEN3, who=who)
    assert rec is None and frag in err


def test_t1_non_string_note_is_not_a_lift():
    for bad in (None, b"lift=acceptance_cap report=3 reason=x", {"note": "x"}):
        assert shared.acceptance_cap_lift(bad, "host", TOKEN3) == (None, "")


def test_t1_two_marker_lines_first_wins_deterministically():
    """The grammar puts `reason=` last, so a second `lift=` line can only be a new
    statement; the first line is the one that is read (deterministic, bounded)."""
    note = ("lift=acceptance_cap report=3 reason=first\n"
            "lift=acceptance_cap report=9 reason=second")
    rec, err = _lift(note)
    assert err == "" and rec["report_gen"] == 3 and rec["reason"] == "first"


# ---------------------------------------------------------------------------
# T2 - the live filter (expiry / single use / latest wins / malformed)
# ---------------------------------------------------------------------------

def _rec(at, token=TOKEN3, used_at=None):
    d = {"who": "host", "at": at, "report_token": token, "reason": "r", "uses": []}
    if used_at:
        d["used_at"] = used_at
    return d


def test_t2_live_lift_is_returned():
    got = shared.acceptance_lift_live([_rec(NOW)], NOW)
    assert got is not None and got["who"] == "host"


def test_t2_expired_lift_is_dead():
    old = NOW - shared.ACCEPTANCE_CAP_LIFT_TTL_SEC - 1
    assert shared.acceptance_lift_live([_rec(old)], NOW) is None


def test_t2_used_lift_is_dead():
    assert shared.acceptance_lift_live([_rec(NOW, used_at=NOW)], NOW) is None


def test_t2_latest_wins():
    older = _rec(NOW - 60)
    newer = dict(_rec(NOW), who="second")
    assert shared.acceptance_lift_live([older, newer], NOW)["who"] == "second"


@pytest.mark.parametrize("bad", [
    None, "x", [None], [{}], [{"at": "abc", "report_token": TOKEN3}],
    [{"at": NOW}], [{"at": NOW, "report_token": ""}],
])
def test_t2_malformed_records_are_skipped(bad):
    assert shared.acceptance_lift_live(bad, NOW) is None


# ---------------------------------------------------------------------------
# T3 - one derivation for the report token
# ---------------------------------------------------------------------------

def test_t3_token_equals_the_result_file_name():
    for gen in (0, 1, 7):
        assert shared.acceptance_report_token("acceptance_walkthrough", gen) == \
            os.path.basename(shared.result_file_for(
                TICKET, "acceptance_walkthrough", gen, None))


@pytest.mark.parametrize("text,want", [
    (TOKEN3, 3), ("3", 3), (" 4 ", 4), (None, None), (b"3", None), ("", None),
    ("stage_merge_check_gen3.json", None), ("not-a-report", None),
    ("stage_acceptance_walkthrough_gen_x.json", None), (7, None),
])
def test_t3_reader_truth_table(text, want):
    assert shared.parse_acceptance_report_token(text) == want


# ---------------------------------------------------------------------------
# T4 - the blocked face names a truthful exit
# ---------------------------------------------------------------------------

def test_t4_prefix_is_byte_identical_and_exit_is_named():
    text = shared.acceptance_cap_blocked_text(4, 2, TOKEN3)
    assert text.startswith("acceptance walkthrough send-back 4 rounds over limit (cap 2)")
    for frag in ("op=ruling", "op=rework", "op=pause", "lift=acceptance_cap",
                 "report=%s" % TOKEN3, "retry_qc", "single use",
                 "%d h" % (shared.ACCEPTANCE_CAP_LIFT_TTL_SEC // 3600),
                 "recorded on the ticket face"):
        assert frag in text, frag
    assert "no wake-up" in text.lower()
    # the grammar is printed plain: a wrapped line is what the paste test above tolerates,
    # but the face must not hand the operator decoration in the first place
    assert "lift=acceptance_cap report=%s" % TOKEN3 in text
    assert "`lift=acceptance_cap" not in text


def test_t4_every_named_op_exists_in_the_human_cli():
    import re
    text = shared.acceptance_cap_blocked_text(4, 2, TOKEN3)
    cli = (POC.parent / "tools" / "ticket.py").read_text("utf-8")
    ops = sorted(set(re.findall(r"op=([a-z_]+)", text)))
    assert ops, "the face names no exit"
    for op in ops:
        assert ("'%s'" % op) in cli, "the face names op=%s, which the CLI does not have" % op


def test_t4_the_stop_stays_a_persons_stop():
    text = shared.acceptance_cap_blocked_text(4, 2, TOKEN3)
    assert shared.classify_stop_tier(text)[0] == shared.STOP_TIER_JUDGEMENT


@pytest.mark.parametrize("rounds,cap", [(None, None), ("x", 2), (-1, 0)])
def test_t4_malformed_arguments_do_not_raise(rounds, cap):
    assert "acceptance walkthrough send-back" in shared.acceptance_cap_blocked_text(
        rounds, cap, "")


# ---------------------------------------------------------------------------
# T5 - intake discipline on a bare workflow shell
# ---------------------------------------------------------------------------

def _shell(meta=None, patched=False):
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: patched, now=lambda: NOW_DT,
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None))
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = dict(meta or {})
    wf.timeline = []
    wf.refused = []
    wf.ticket_id = TICKET
    return wf


def _ruling(wf, note, who="host"):
    fn = dev_lane.DevLaneWorkflow.__dict__["host_ruling"]
    fn = getattr(fn, "__func__", fn)
    fn(wf, HostRulingRequest(who=who, note=note))


def _blocked_shell(**extra):
    meta = {"stage": "acceptance_walkthrough", "stage_state": "blocked",
            "acc_cap_stop": {"rounds": 4, "report_gen": 3, "report_token": TOKEN3,
                             "finding_sig": "abc", "at": NOW},
            "status": "dispatched", "project": "ut"}
    meta.update(extra)
    return _shell(meta)


def test_t5_valid_lift_arms_and_records_on_the_face():
    wf = _blocked_shell()
    _ruling(wf, "lift=acceptance_cap report=%s reason=accept the remaining nit" % TOKEN3)
    recs = wf.meta.get("acceptance_cap_lifts") or []
    assert len(recs) == 1 and recs[0]["report_token"] == TOKEN3
    assert recs[0]["at"] == NOW and recs[0]["uses"] == []
    armed = [e for e in wf.timeline if e.get("state") == "authorized"]
    assert armed and "armed" in armed[0]["reason"] and TOKEN3 in armed[0]["reason"]
    assert any("acceptance cap lift armed" in e["note"] for e in wf.meta.get("log") or [])
    assert wf.meta.get("updated") == NOW            # _touch after the write
    assert wf.refused == []
    # the ruling itself still lands (the prompt keeps the operator's words)
    assert (wf.meta.get("host_rulings") or [])[0]["note"].startswith("lift=")


@pytest.mark.parametrize("note,frag", [
    ("lift=acceptance_cap reason=x", "must cite the walkthrough report"),
    ("lift=acceptance_cap report=stage_acceptance_walkthrough_gen9.json reason=x",
     "cite the stopped report"),
    ("lift=acceptance_cap report=%s" % TOKEN3, "missing reason"),
])
def test_t5_refused_lift_writes_nothing_and_says_so(note, frag):
    wf = _blocked_shell()
    _ruling(wf, note)
    assert len(wf.refused) == 1 and frag in wf.refused[0]["why"]
    assert "NOT recorded" in wf.refused[0]["why"]
    assert "acceptance_cap_lifts" not in wf.meta and "host_rulings" not in wf.meta
    assert wf.timeline == []


def test_t5_agent_identity_cannot_arm_a_lift():
    wf = _blocked_shell()
    _ruling(wf, "lift=acceptance_cap report=%s reason=x" % TOKEN3, who="developer")
    assert wf.refused and "self-authorize" in wf.refused[0]["why"]
    assert "acceptance_cap_lifts" not in wf.meta


def test_t5_lift_without_a_stop_is_refused():
    wf = _shell({"stage": "acceptance_walkthrough", "status": "dispatched",
                 "project": "ut"})
    _ruling(wf, "lift=acceptance_cap report=%s reason=x" % TOKEN3)
    assert wf.refused and "no acceptance cap stop" in wf.refused[0]["why"]
    assert "acceptance_cap_lifts" not in wf.meta


def test_t5_ordinary_ruling_is_byte_identical():
    wf = _blocked_shell()
    _ruling(wf, "please re-run the gate after the env fix")
    assert wf.meta["host_rulings"] == [
        {"ts": NOW_DT.isoformat(timespec="seconds"), "who": "host",
         "note": "please re-run the gate after the env fix"}]
    assert "acceptance_cap_lifts" not in wf.meta and wf.timeline == []
    assert wf.refused == []


def test_t5_lift_records_are_bounded():
    meta = {"stage": "acceptance_walkthrough", "status": "dispatched", "project": "ut",
            "acc_cap_stop": {"rounds": 4, "report_token": TOKEN3, "at": NOW},
            "acceptance_cap_lifts": [dict(_rec(NOW - 200 + i), who="h%d" % i)
                                     for i in range(shared.ACCEPTANCE_CAP_LIFT_MAX_RECORDS)]}
    wf = _shell(meta)
    _ruling(wf, "lift=acceptance_cap report=%s reason=ok" % TOKEN3)
    recs = wf.meta["acceptance_cap_lifts"]
    assert len(recs) == shared.ACCEPTANCE_CAP_LIFT_MAX_RECORDS
    assert recs[-1]["report_token"] == TOKEN3


# ---------------------------------------------------------------------------
# T6 - the real main loop with stubbed activities
# ---------------------------------------------------------------------------

class _Terminal(Exception):
    """Sentinel: the loop reached merge_check (the success terminal of this rig)."""


class _Blocked(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _res(status="ok", summary="", report="", env_fail=False, env_reason="",
         refusal=None):
    return dev_lane.StageResult(
        status=status, summary=summary, report=report, deliverables=[],
        files_changed=[], files_changed_shape="ok", evidence="ut",
        gate_refusal=refusal, env_fail=env_fail, env_reason=env_reason,
        handover_runs=[], handover_dropped=[])


class FakeMachine:
    """Scripted brain: implement/design/test/arbitrate/walkthrough, plus host actions
    scripted per blocked stop."""

    def __init__(self, acc=(), verdict="pass", scripts=()):
        self.acc = list(acc)
        self.verdict = verdict
        self.scripts = list(scripts)     # callables(wf), one per blocked stop
        self.calls = []
        self.blocks = []

    def spawn(self, stage):
        self.calls.append(stage)
        if stage == "acceptance_walkthrough":
            return self.acc.pop(0) if self.acc else _res(summary="walkthrough ok")
        if stage == "arbitrate":
            return _res(summary="verdict=%s arbitration done" % self.verdict)
        return _res(summary="[ut] %s done" % stage)

    def block(self, wf):
        reason = str(wf.meta.get("blocked_reason") or "")
        self.blocks.append(reason)
        if not self.scripts:
            raise _Blocked(reason)
        self.scripts.pop(0)(wf)


def _mk_wf(machine, patched=lambda pid: True):
    dev_lane.workflow = SimpleNamespace(
        patched=patched, now=lambda: NOW_DT,
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None),
        upsert_memo=lambda *a, **k: None, sleep=lambda *a, **k: asyncio.sleep(0),
        wait_condition=None)
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.ticket_id = TICKET
    wf.timeline = []
    wf._gens = {}
    wf._retry_token = 0
    wf._rework = None
    wf._arb_over_limit_seq = 0
    wf._acc_verdict_seq = 0
    wf.results = {}
    wf.refused = []
    wf.signatures = {}
    wf.gate_runs = []
    wf.engine_version = 2
    wf.machine = machine

    async def _wait_condition(cond):
        machine.block(wf)
        wf._retry_token += 1
        assert cond(), "wait_condition predicate still false after the host action"

    dev_lane.workflow.wait_condition = _wait_condition

    async def _execute_activity(activity, args, **kw):
        name = getattr(activity, "name", None) or getattr(activity, "__name__", "") \
            or str(activity)
        if name in ("implement", "design_integration_tests", "arbitrate",
                    "acceptance_walkthrough"):
            return machine.spawn(name)
        if name == "settle_lane":
            return SettleLaneResult(note="clean", lane_commits=1, error="")
        if name == "run_integration_tests":
            return IntegrationRunResult(ran=1, passed=1, failed=0, env_fail=0,
                                        details=[{"name": "ut", "cmd": "", "exit": 0,
                                                  "output_tail": ""}])
        if name == "merge_check":
            raise _Terminal()
        if name in ("concurrency_acquire", "concurrency_renew", "concurrency_release",
                    "concurrency_release_if_paused"):
            return {"granted": True, "holding": True, "reason": "", "released": True,
                    "position": 0, "limit": 1, "waiting": 0, "promoted": False,
                    "dropped_stale": []}
        return {"ok": True, "note": "ut", "error": "", "phase": "", "stop": False,
                "files": [], "names": [], "mode": "none", "reason": "",
                "surfaces": [], "members": [], "own_members": [], "budget_min": 0,
                "own_error": "", "blocked_reason": "", "warning": "",
                "lane_commits": 1, "git_error": "", "shots_path_error": "",
                "png_count": 0, "prefixes": [], "mode_absent": "absent",
                "dir": "absent", "dirs": []}

    dev_lane.workflow.execute_activity = _execute_activity

    async def _noop():
        return None

    wf._pause_gate = _noop
    wf._concurrency_release_if_paused = _noop
    wf._drain_annex_requests = _noop
    wf._ledger_flush = _noop
    wf._ledger_enqueue = lambda entry: None

    async def _prep_ws():
        wf.meta["stage"] = "parallel_impl_design"

    wf._prepare_workspace_step = _prep_ws
    return wf


def _run_journey(machine, patched=lambda pid: True):
    wf = _mk_wf(machine, patched)
    wf.meta = {
        "id": TICKET, "workflow_id": "dev-lane", "project": "ut", "title": "ut",
        "role": "developer", "lane": "worktree",
        "workspace": "/tmp/ut-t261027-26", "worktree": "/tmp/ut-t261027-26",
        "branch": "ut", "base_ref": "main", "stage": "parallel_impl_design",
        "stage_state": "running", "write_set": ["docs/"], "no_file_changes": False,
        "path_gate": False, "path_gate_rules": {}, "repo_worktrees": [],
        "project_root": "", "acceptance": [], "checks": {}, "deliverables": [],
        "user_request": "ut", "spec": "", "body": "", "pending": [], "handoffs": [],
        "status": "dispatched", "created": 0, "updated": 0, "log": [],
    }
    try:
        asyncio.run(dev_lane.DevLaneWorkflow.run(wf, SimpleNamespace(
            ticket_id=TICKET, template_id="dev-lane", project="ut", title="ut",
            lane="worktree", workspace="/tmp/ut-t261027-26",
            worktree="/tmp/ut-t261027-26", branch="ut", base_ref="main",
            proposal_id="", book_path="", epic="", write_set=["docs/"],
            deliverables=[], user_request="ut", spec="", body="", created=0)))
    except _Terminal:
        wf.meta["_reached"] = "merge_check"
    except _Blocked as b:
        wf.meta["_reached"] = "blocked"
        wf.meta["_block_reason"] = b.reason
    return wf


def _arm_lift(wf):
    """Host action at a blocked cap: send the lift ruling (the real handler)."""
    stop = wf.meta["acc_cap_stop"]
    _ruling(wf, "lift=acceptance_cap report=%s reason=the remaining nit is accepted "
                "by the host" % stop["report_token"])


def _named(index=2):
    return _res(status="failed", summary="walkthrough found a failed item",
                report=FAIL_TABLE if index == 2 else
                "acceptance item %d failed: the CLI exits 1" % index)


def test_t6a_repeated_named_finding_reaches_the_cap_and_names_the_exit():
    machine = FakeMachine(acc=[_named(), _named(), _named()])
    wf = _run_journey(machine)
    assert wf.meta["_reached"] == "blocked", wf.meta.get("_reached")
    reason = wf.meta["_block_reason"]
    assert reason.startswith("acceptance walkthrough send-back 3 rounds over limit (cap 2)")
    assert "op=ruling" in reason and "lift=acceptance_cap" in reason
    stop = wf.meta.get("acc_cap_stop") or {}
    assert stop.get("rounds") == 3 and stop.get("report_token")


def test_t6b_the_lift_proceeds_past_the_cap_without_another_walkthrough_run():
    machine = FakeMachine(acc=[_named(), _named(), _named()])
    machine.scripts = [_arm_lift]
    wf = _run_journey(machine)
    assert wf.meta["_reached"] == "merge_check", wf.meta.get("_reached")
    # no extra walkthrough spawn for the lifted report
    assert machine.calls.count("acceptance_walkthrough") == 3, machine.calls
    rec = (wf.meta.get("acceptance_cap_lifts") or [])[0]
    assert rec.get("used_at") and rec["uses"], rec
    # the ticket face (timeline, not meta) carries armed + used
    states = [(e.get("state"), e.get("reason") or "") for e in wf.timeline]
    armed = [r for s, r in states if s == "authorized" and "armed" in r]
    used = [r for s, r in states if s == "authorized" and "used" in r]
    assert armed and "host" in armed[0] and rec["report_token"] in armed[0]
    assert used and rec["report_token"] in used[0]
    handoffs = [h for h in wf.meta.get("handoffs") or [] if h.get("stage") == "acceptance"]
    assert handoffs and "cap lifted" in handoffs[-1]["summary"]
    assert "acc_cap_stop" not in wf.meta


def test_t6c_a_receipt_that_names_no_item_proceeds_and_never_counts():
    no_finding = _res(status="failed",
                      summary="walkthrough reported failure, no item named",
                      report="The walkthrough found no defect; all four acceptance "
                             "items answered at the unchanged HEAD ed0dc444.")
    machine = FakeMachine(acc=[no_finding])
    wf = _run_journey(machine)
    assert wf.meta["_reached"] == "merge_check", wf.meta.get("_reached")
    assert machine.calls.count("acceptance_walkthrough") == 1, machine.calls
    assert "acc_cap_stop" not in wf.meta
    assert not [e for e in wf.timeline if e.get("state") == "blocked"]
    handoffs = [h for h in wf.meta.get("handoffs") or [] if h.get("stage") == "acceptance"]
    assert handoffs and "observation" in handoffs[-1]["summary"]
    assert "not a send-back" in handoffs[-1]["summary"].lower()


def test_t6d_an_empty_receipt_is_a_stop_not_an_observation():
    machine = FakeMachine(acc=[_res(status="failed", summary="", report="")])
    wf = _run_journey(machine)
    assert wf.meta["_reached"] == "blocked", wf.meta.get("_reached")
    assert "without writing a report" in wf.meta["_block_reason"]
    assert machine.calls.count("acceptance_walkthrough") == 1
    assert "acc_cap_stop" not in wf.meta


def test_t6e_an_environment_receipt_is_a_stop_and_names_the_cause():
    machine = FakeMachine(acc=[_res(status="failed", summary="",
                                    report="partial evidence",
                                    env_fail=True, env_reason="no sandbox backend")])
    wf = _run_journey(machine)
    assert wf.meta["_reached"] == "blocked", wf.meta.get("_reached")
    assert "agent sandbox unavailable" in wf.meta["_block_reason"]
    assert "acc_cap_stop" not in wf.meta


def test_t6f_a_front_door_refusal_is_a_stop_not_an_observation():
    machine = FakeMachine(acc=[_res(status="failed", summary="receipt refused",
                                    report="probe change outside the stage write set",
                                    refusal={"reason_code": "unauthorized_path"})])
    wf = _run_journey(machine)
    assert wf.meta["_reached"] == "blocked", wf.meta.get("_reached")
    assert "unauthorized_path" in wf.meta["_block_reason"]
    assert "acc_cap_stop" not in wf.meta


def test_t6g_a_new_finding_each_round_keeps_iterating():
    machine = FakeMachine(acc=[_named(2), _named(3), _named(4),
                               _res(summary="walkthrough ok")])
    wf = _run_journey(machine)
    assert wf.meta["_reached"] == "merge_check", wf.meta.get("_reached")
    assert machine.calls.count("implement") >= 3, machine.calls
    assert not [e for e in wf.timeline if e.get("state") == "blocked"]


# ---------------------------------------------------------------------------
# T7 - the detector truth table
# ---------------------------------------------------------------------------

def _find(summary="", report=""):
    return shared.acceptance_sendback_finding(summary, report)


def test_t7_the_measured_field_shape_is_not_a_finding():
    got = _find("walkthrough complete, all items answered", PASS_TABLE)
    assert got["named"] is False and got["basis"] == "none"


def test_t7_a_fail_row_names_its_item():
    got = _find("walkthrough found one failed item", FAIL_TABLE)
    assert got["named"] is True and "2" in got["items"] and got["basis"] == "table"


@pytest.mark.parametrize("report", [
    "acceptance item 3 failed: the ops doc section is missing",
    "验收项 2 失败：票面未点名出路",  # copy-lang-allow:t261027-26-vocabulary
    "第 2 条未通过：计数器仍按轮次累加",  # copy-lang-allow:t261027-26-vocabulary
])
def test_t7_prose_findings_name_the_item(report):
    got = _find("", report)
    assert got["named"] is True and got["items"]


@pytest.mark.parametrize("report", [
    "the walkthrough found no defect; all four acceptance items answered at ed0dc444",
    "the gate says fail-closed for a missing token; item 4 passed",
    "第 3 轮走查失败，代码未变",  # copy-lang-allow:t261027-26-vocabulary
    "item 2 is green and item 3 passed",
])
def test_t7_passing_text_never_names_a_finding(report):
    assert _find("", report)["named"] is False


def test_t7_the_marker_is_the_prompt_contract_shape():
    assert _find("", "failed_item=2")["named"] is True
    assert _find("", "failed_items=2,3")["items"][:2] == ["2", "3"]
    assert _find("", "failed_item=none")["named"] is False
    assert _find("", "failed_item=NONE")["named"] is False


@pytest.mark.parametrize("summary,report", [
    ("", ""), (None, None), (b"bytes", b"report"), ({"s": "x"}, {"r": "y"}), ("  ", "\n"),
])
def test_t7_no_readable_text_is_malformed_never_a_clean_no_finding(summary, report):
    got = _find(summary, report)
    assert got["named"] is False and got["basis"] == "malformed"


def test_t7_bounds_hold_on_a_hostile_receipt():
    huge = "x" * 400_000 + "\nitem 2 failed"
    got = _find("", huge)
    assert isinstance(got, dict) and isinstance(got["items"], list)
    many = "failed_items=" + ",".join(str(i) for i in range(1, 60))
    assert len(_find("", many)["items"]) <= 16


# ---------------------------------------------------------------------------
# T8 - the in-flight escape (memoized patched face)
# ---------------------------------------------------------------------------

class MemoPatched:
    """Mirrors the SDK memoization: the first verdict per id sticks; ids already
    evaluated during a pre-fix replay are frozen False."""

    def __init__(self, replay_upto=0):
        self.memo = {}
        self.replay_upto = replay_upto      # rounds 1..N were replayed (frozen False)
        self.seen = []

    def __call__(self, pid):
        if pid in self.memo:
            return self.memo[pid]
        self.seen.append(pid)
        verdict = True
        if "#" in pid:
            try:
                seq = int(pid.rsplit("#", 1)[1])
                verdict = seq > self.replay_upto
            except ValueError:
                verdict = True
        self.memo[pid] = verdict
        return verdict


def test_t8_historical_rounds_keep_the_old_rule_and_the_live_round_gets_the_new():
    no_finding = _res(status="failed", summary="no item named",
                      report="the walkthrough found no defect at HEAD ed0dc444")
    # round 1 was replayed from the pre-fix history (frozen False); round 2 is live
    machine = FakeMachine(acc=[no_finding, no_finding])
    wf = _run_journey(machine, patched=MemoPatched(replay_upto=1))
    assert wf.meta["_reached"] == "merge_check", wf.meta.get("_reached")
    # the old rule took round 1 as a send-back (implement re-ran), the new rule took
    # round 2 as an observation
    assert machine.calls.count("implement") >= 2, machine.calls
    assert machine.calls.count("acceptance_walkthrough") == 2, machine.calls
    ids = [pid for pid in dev_lane.workflow.patched.seen if "acceptance-verdict" in pid]
    assert ids[:2] == ["t261027-26-acceptance-verdict-v1#1",
                       "t261027-26-acceptance-verdict-v1#2"], ids


def test_t8_the_lift_works_while_the_verdict_gate_is_frozen_false():
    """The in-flight face: the per-round gate is memoized False (an old history), so
    the counter keeps its old rule — and the human exit must still work, because it is
    gated on the new grammar plus the stop record, not on workflow.patched()."""
    machine = FakeMachine(acc=[_named(3), _named(3), _named(3)])
    machine.scripts = [_arm_lift]
    wf = _run_journey(
        machine, patched=lambda pid: False if "acceptance-verdict" in pid else True)
    assert wf.meta["_reached"] == "merge_check", wf.meta.get("_reached")
    assert (wf.meta.get("acceptance_cap_lifts") or [])[0].get("used_at")


def test_t8_a_lift_for_a_replaced_stop_is_named_and_revoked():
    """c6: a lift must cite the stop it overrides. If a newer stop replaced that one,
    the mismatch is named once, the lift is revoked (it can never fire later) and the
    stop record is cleared."""
    wf = _blocked_shell()
    _ruling(wf, "lift=acceptance_cap report=%s reason=accept the nit" % TOKEN3)
    # a newer stop replaced the one the lift was cut for
    wf.meta["acc_cap_stop"] = {"rounds": 5, "report_gen": 4,
                               "report_token": "stage_acceptance_walkthrough_gen4.json",
                               "finding_sig": "def", "at": NOW}
    assert wf._acceptance_lift_ready("acceptance") is False
    named = [e for e in wf.timeline if "revoked" in (e.get("reason") or "")]
    assert named and TOKEN3 in named[0]["reason"]
    rec = wf.meta["acceptance_cap_lifts"][0]
    assert rec.get("revoked_at") and "overrides" in str(rec.get("revoked_reason"))
    assert "acc_cap_stop" not in wf.meta
    # repeated loop passes do not spam the face, and a revoked lift is never live again
    assert wf._acceptance_lift_ready("acceptance") is False
    assert len([e for e in wf.timeline if "revoked" in (e.get("reason") or "")]) == 1
    assert shared.acceptance_lift_live(wf.meta["acceptance_cap_lifts"], NOW) is None


def test_t8_a_consumed_rework_retires_the_armed_lift():
    """Arbitration F1 (261027): a lift armed at the cap must not survive a human rework.

    Measured before this fix: LIFT+REWORK ended at merge_check with 3 walkthrough and 3
    arbitrate spawns, while the rework-only control needed 4/4 — the lift was consumed
    against the PRE-rework report, so the ticket skipped the arbitrate edge and the
    verification round the human asked for, and the handoff claimed acceptance."""
    def named():
        return _res(status="failed", summary="walkthrough found a failed item",
                    report="acceptance item 2 failed: the CLI exits 1")

    def rework(wf):
        wf.rework(ReworkRequest(note="fix it instead", who="host",
                                target_stage="implement"))

    def arm_then_rework(wf):
        _arm_lift(wf)
        rework(wf)

    lifted = FakeMachine(acc=[named(), named(), named(),
                              _res(summary="walkthrough ok")])
    lifted.scripts = [arm_then_rework]
    wf_l = _run_journey(lifted)

    control = FakeMachine(acc=[named(), named(), named(),
                               _res(summary="walkthrough ok")])
    control.scripts = [rework]
    _run_journey(control)

    # the lifted path re-verifies exactly like the control (no skipped round)
    assert lifted.calls.count("acceptance_walkthrough") == 4, lifted.calls
    assert lifted.calls.count("arbitrate") == 4, lifted.calls
    assert lifted.calls.count("acceptance_walkthrough") == \
        control.calls.count("acceptance_walkthrough")
    # the lift was retired, never consumed, and the stop record is gone
    rec = (wf_l.meta.get("acceptance_cap_lifts") or [])[0]
    assert rec.get("revoked_at") and not rec.get("used_at"), rec
    assert "rework was consumed" in str(rec.get("revoked_reason"))
    assert "acc_cap_stop" not in wf_l.meta
    assert any("acceptance cap lift revoked" in (e.get("reason") or "")
               for e in wf_l.timeline)
    # the face never claims the human accepted a finding they asked to fix
    assert not any("cap lifted" in (h.get("summary") or "")
                   for h in (wf_l.meta.get("handoffs") or []))
    assert wf_l.meta["_reached"] == "merge_check"


def test_t8_the_stopped_report_must_still_be_the_latest_round():
    """F1 belt-and-braces: even without a rework, a lift whose stopped report is no
    longer the latest walkthrough round is revoked, not applied."""
    wf = _blocked_shell()
    _ruling(wf, "lift=acceptance_cap report=%s reason=accept the nit" % TOKEN3)
    wf._gens = {"acceptance_walkthrough": 6}      # the anchor is gen 5 -> stop gen 3 is old
    assert wf._acceptance_lift_ready("acceptance") is False
    rec = wf.meta["acceptance_cap_lifts"][0]
    assert rec.get("revoked_at") and "latest walkthrough round" in str(rec.get("revoked_reason"))
    assert "acc_cap_stop" not in wf.meta


def test_t8_a_pre_fix_ruling_note_replays_the_old_handler_path():
    wf = _blocked_shell()
    _ruling(wf, "old ruling from before the fix: re-run the gate")
    assert "acceptance_cap_lifts" not in wf.meta
    assert wf.timeline == [] and wf.refused == []


# ---------------------------------------------------------------------------
# T9 - source locks (one producer, one guard, the right order)
# ---------------------------------------------------------------------------

def _window(start_marker, end_marker, src=SRC_DL, after=0):
    a = src.index(start_marker, after)
    b = src.index(end_marker, a)
    return src[a:b]


def test_t9_both_cap_sites_record_the_stop_and_use_the_shared_text():
    assert SRC_DL.count('self.meta["acc_cap_stop"] = {') == 2
    assert SRC_DL.count("acceptance_cap_blocked_text(") == 2   # exactly the two sites
    assert SRC_DL.count("acceptance_cap_blocked_text") == 3     # + the shared import
    assert SRC_DL.count("acceptance walkthrough send-back") == 0, \
        "no inline duplicate of the cap sentence may remain"


def test_t9_the_verdict_gate_wraps_the_whole_block_in_both_branches():
    assert SRC_DL.count("if self._acc_verdict_gate():") == 2
    for cls in ("env", "refused", "empty", "observe"):
        assert SRC_DL.count('if _cls == "%s":' % cls) == 2, cls
    # the classification sits after the lane-dsh continue and before the increment
    serial = _window('self._lane_dsh_refusal(res)', "acc_rounds += 1")
    assert "self._acc_verdict_gate()" in serial and 'if _cls == "observe":' in serial
    forked = _window('self._lane_dsh_refusal(acc_res)', "acc_rounds += 1")
    assert "self._acc_verdict_gate()" in forked and 'if _cls == "observe":' in forked


def test_t9_the_gate_builds_a_per_round_id():
    body = _window("def _acc_verdict_gate", "def _acceptance_receipt_class")
    assert 'workflow.patched("%s#%d" % (ACC_WALKTHROUGH_VERDICT_PATCH_ID' in body
    assert 'self._acc_verdict_seq = int(getattr(self, "_acc_verdict_seq", 0)) + 1' in body
    assert SRC_DL.count('ACC_WALKTHROUGH_VERDICT_PATCH_ID = "t261027-26-acceptance-verdict-v1"') == 1


def test_t9_the_lift_consumes_at_the_loop_top_only_for_the_acceptance_phases():
    body = _window("def _acceptance_lift_ready", "def _acceptance_lift_step")
    assert 'phase not in ("acceptance", "arb_acc_parallel")' in body
    assert 'self.meta.get("acc_cap_stop")' in body
    assert "acceptance_lift_live(" in body
    top = _window("# 1.5) t261027-26", "# 2) create_plan")
    assert "self._acceptance_lift_ready(phase)" in top
    assert 'phase = "merge_check"' in top
    # the rework branch runs first (c1: a rework sent in the same breath wins)
    rework = SRC_DL.index("if self._rework is not None:")
    assert rework < SRC_DL.index("self._acceptance_lift_ready(phase)")


def test_t9_the_identity_guard_has_one_definition_and_two_call_sites():
    assert SRC_SH.count("def identity_refusal(") == 1
    assert "shared.identity_refusal(" in SRC_AZ
    assert "err = identity_refusal(who)" in SRC_SH       # the lift intake
    assert SRC_AZ.count("identity_refusal(") == 1


def test_t9_the_intake_precedes_the_ruling_append_and_touches():
    a = SRC_DL.index("_lift, _lift_err = acceptance_cap_lift(")
    b = SRC_DL.index('self.meta.setdefault("host_rulings", []).append(', a)
    assert "NOT recorded" in SRC_DL[a:b]
    assert SRC_DL.index("self._touch()", a) > a


def test_t9_the_parallel_branch_also_resets_on_a_new_finding():
    forked = _window('self._lane_dsh_refusal(acc_res)', "acc_rounds += 1")
    assert '_sig != _prev_sig' in forked and "acc_rounds = 0" in forked, \
        "the fork path must reset the bounce counter on a new finding too"


def test_t9_the_brief_names_the_marker_the_detector_reads():
    briefs = getattr(dev_lane.DevLaneWorkflow, "FLOW_BRIEF_SET", {}) or {}
    brief = str(briefs.get("acceptance_walkthrough") or "")
    assert "failed_item" in brief
    assert "observation" in brief
