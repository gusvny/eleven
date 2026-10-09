#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261008-47 — the engine's UI-visible copy must be English (L1 regression suite).

Three faces pinned here:

  A. Parser re-keying regression (order-bearing): the lane-watchdog round-count /
     wall-time derivation keys on the STRUCTURED timeline fields (stage +
     state=running + gen) and never on the human reason text. Proven over an
     OLD-format timeline (Chinese marker rows, exactly what stored history looks
     like), a NEW-format one (English rows), and a mixed one (old ticket keeps its
     Chinese rows; history is data). A timeline with neither marker degrades to a
     NAMED note, never a silent zero.

  B. The CJK guard (ui_copy_guard): narrow by construction — emission-point
     anchored (arg-precise), comments/log lines/other args are structurally out;
     planted-literal narrowness proof; unparseable source is a named finding.

  C. Fixture-ticket face (L3, unit-level): driving _mark/_handoff on a stub ticket
     object yields English timeline reasons and handoff summaries, attempt numbers
     preserved; stage acceptance items are English; an OLD Chinese row in a
     history timeline is untouched by both the parser (A) and the guard (B).
     The panel-label side of L3 is covered by the updated workbench fixture test
     lane-parallel-states.mjs (same change set).

Run: repo root `server/engine/.venv/bin/python -m pytest
server/engine/tests/test_t261008_47_english_ticket_face.py -q`
(UT discipline: no network / no real Temporal / no real git).
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))
REPO = POC.parent.parent

import inspection_lane_watchdog as lw  # noqa: E402
import ui_copy_guard as guard  # noqa: E402

NOW = 1_794_307_200.0


def _iso(ts: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def _run_row(at: float, gen: int, reason: str) -> dict:
    return {"at": _iso(at), "stage": "run_integration_tests",
            "state": "running", "gen": gen, "reason": reason}


def _snapshot(timeline, gens=None):
    return {"stage": "run_integration_tests", "stage_state": "running",
            "status": "dispatched", "gens": gens if gens is not None else {},
            "results": {}, "timeline": timeline,
            "meta": {"created": NOW - 86400, "updated": NOW,
                     "log": [{"ts": NOW, "note": "stub"}]}}


# ===================================================================================
# A. parser re-keying regression (structured fields, not the reason text)
# ===================================================================================

OLD_ROW = "进入本步（第 %d 次）"     # what already-stored tickets carry  # copy-lang-allow:fixture
NEW_ROW = "Entered step (attempt %d)"


def _both_format_fixtures(gap=1800.0, last_ago=600.0):
    """The same three-round schedule in old and new copy; returns
    (old_snapshot, new_snapshot, expected_entries, expected_last_seconds)."""
    starts = [NOW - 2 * gap, NOW - gap, NOW - last_ago]
    entries = list(starts)
    old_tl = [_run_row(t, i + 1, OLD_ROW % (i + 1)) for i, t in enumerate(starts)]
    new_tl = [_run_row(t, i + 1, NEW_ROW % (i + 1)) for i, t in enumerate(starts)]
    # the run_integration_tests "done" rows in between must not count as rounds
    for tl in (old_tl, new_tl):
        for i, t in enumerate(starts):
            tl.append({"at": _iso(t + gap * 0.4), "stage": "run_integration_tests",
                       "state": "done", "gen": i + 1, "reason": "suite finished"})
    return _snapshot(old_tl), _snapshot(new_tl), entries, last_ago


def test_a1_old_format_rows_derive_rounds_and_wall_time():
    old_snap, new_snap, entries, last = _both_format_fixtures()
    f_old = lw.facts_from_snapshot("t-old", "sandbar", old_snap, now_ts=NOW)
    assert f_old["suite_rounds"] == 3
    assert f_old["suite_entries"] == pytest.approx(entries)
    text, last_sec = lw._wall_text(f_old["suite_entries"], NOW)
    assert "in flight" in text
    assert last_sec == pytest.approx(last)
    assert not [n for n in f_old["parse_notes"] if "timeline" in n]


def test_a2_new_format_rows_derive_the_same_numbers():
    old_snap, new_snap, entries, _ = _both_format_fixtures()
    f_new = lw.facts_from_snapshot("t-new", "sandbar", new_snap, now_ts=NOW)
    f_old = lw.facts_from_snapshot("t-old", "sandbar", old_snap, now_ts=NOW)
    assert f_new["suite_rounds"] == f_old["suite_rounds"] == 3
    assert f_new["suite_entries"] == pytest.approx(f_old["suite_entries"])
    # and identical to the old-format derivation, element by element
    assert [round(x, 6) for x in f_new["suite_entries"]] == \
           [round(x, 6) for x in f_old["suite_entries"]]


def test_a3_mixed_old_and_new_rows_in_one_timeline():
    _, new_snap, entries, _ = _both_format_fixtures()
    mixed = [_run_row(entries[0], 1, OLD_ROW % 1),      # stored old row
             _run_row(entries[1], 2, NEW_ROW % 2),      # post-change row
             _run_row(entries[2], 3, NEW_ROW % 3)]
    f = lw.facts_from_snapshot("t-mixed", "sandbar", _snapshot(mixed), now_ts=NOW)
    assert f["suite_rounds"] == 3
    assert f["suite_entries"] == pytest.approx(entries)


def test_a4_reason_text_alone_is_never_a_key():
    # right copy, wrong stage → zero rounds (the reason text must not rescue it)
    tl = [_run_row(NOW - 60, 1, NEW_ROW % 1)]
    tl[-1]["stage"] = "merge_check"
    f = lw.facts_from_snapshot("t-wrongstage", "sandbar", _snapshot(tl), now_ts=NOW)
    assert f["suite_rounds"] == 0
    # wrong state → zero rounds
    tl2 = [_run_row(NOW - 60, 1, NEW_ROW % 1)]
    tl2[-1]["state"] = "done"
    f2 = lw.facts_from_snapshot("t-wrongstate", "sandbar", _snapshot(tl2), now_ts=NOW)
    assert f2["suite_rounds"] == 0


def test_a5_neither_marker_degrades_to_named_notes_not_silent_zero():
    # timeline present but no running rows at all
    f = lw.facts_from_snapshot("t-empty", "sandbar", _snapshot([]), now_ts=NOW)
    assert f["suite_rounds"] == 0 and f["suite_entries"] == []
    assert not f["parse_notes"], "no note is owed when there is genuinely no marker"
    text, sec = lw._wall_text([], NOW)
    assert text == "" and sec == 0.0
    # timeline absent entirely → the existing named note (not invented wording)
    snap = _snapshot([])
    del snap["timeline"]
    f2 = lw.facts_from_snapshot("t-absent", "sandbar", snap, now_ts=NOW)
    assert f2["suite_rounds"] == 0
    assert any("timeline absent/not a list" in n for n in f2["parse_notes"])
    # rows present but every at unparseable → the existing named note
    bad = [_run_row(NOW, 1, NEW_ROW % 1)]
    bad[0]["at"] = "not-a-timestamp"
    f3 = lw.facts_from_snapshot("t-badat", "sandbar", _snapshot(bad), now_ts=NOW)
    assert any("unparseable at" in n for n in f3["parse_notes"])
    assert f3["suite_entries"] == []


def test_a6_malformed_structured_fields_fail_closed():
    # gen not an int / missing → entry still counts by position, no crash
    tl = [{"at": _iso(NOW - 60), "stage": "run_integration_tests",
           "state": "running", "gen": "two", "reason": NEW_ROW % 1},
          {"at": _iso(NOW - 30), "stage": "run_integration_tests",
           "state": "running", "reason": NEW_ROW % 2},
          "not-even-a-dict"]
    f = lw.facts_from_snapshot("t-malformed", "sandbar", _snapshot(tl), now_ts=NOW)
    assert f["suite_rounds"] == 2
    assert any("not an object" in n for n in f["parse_notes"])


# ===================================================================================
# B. the CJK guard — narrow by construction, planted-literal proof
# ===================================================================================

def test_b1_planted_cjk_in_copy_position_is_named_file_line_literal(tmp_path):
    src = textwrap.dedent('''
        def f(self):
            self._mark("merge", "running", "进入本步（第 1 次）")  # copy-lang-allow:fixture
    ''')
    p = tmp_path / "planted.py"
    p.write_text(src, encoding="utf-8")
    fs = guard.scan_paths([str(p)])
    assert len(fs) == 1
    assert fs[0]["file"].endswith("planted.py")
    assert fs[0]["line"] == 3
    assert "进入本步" in fs[0]["literal"]  # copy-lang-allow:fixture


def test_b2_narrowness_log_line_and_comment_and_data_args_are_out(tmp_path):
    src = textwrap.dedent('''
        # 进入本步 in a comment — out  # copy-lang-allow:fixture
        def f(self):
            self._log("进入本步 in a log line — operator surface, out")   # noqa  # copy-lang-allow:fixture
            self._mark("merge", "进入本步state位置是数据", "Entered step (attempt 1)")  # copy-lang-allow:fixture
            self._auto_rework("implement", "send back", who="谁", fallback="审核")  # copy-lang-allow:fixture
            STAGE = Stage(id="merge", name="合并（人审）",  # copy-lang-allow:fixture
                          desc="English only",
                          acceptance=("Human sign-off",))
    ''')
    p = tmp_path / "narrow.py"
    p.write_text(src, encoding="utf-8")
    assert guard.scan_paths([str(p)]) == []


def test_b3_every_anchor_position_is_checked(tmp_path):
    src = textwrap.dedent('''
        def f(self):
            self._blocked("merge_check", "红灯：%s" % x)  # copy-lang-allow:fixture
            self._handoff("merge", "合并完成 %s" % cid, report="中文报告")  # copy-lang-allow:fixture
            self._finish("merge", by="w", evidence="落账：x")  # copy-lang-allow:fixture
            self._auto_rework("implement", "打回（第 %d 轮）" % n, who="w", fallback="m")  # copy-lang-allow:fixture
            Stage(id="s", name="数据键不查", desc="中文描述",  # copy-lang-allow:fixture
                  acceptance=("人审签字", "English ok"))  # copy-lang-allow:fixture
    ''')
    p = tmp_path / "anchors.py"
    p.write_text(src, encoding="utf-8")
    kinds = sorted(f["kind"] for f in guard.scan_paths([str(p)]))
    assert kinds == ["acceptance", "desc", "evidence", "note", "report", "summary", "why"]


def test_b4_commit_subject_anchor_is_dataflow_wide(tmp_path):
    """Every `git commit -m` writer site is covered by the msg=->-m dataflow
    anchor, not just one hand-named function; a msg that never reaches -m is
    out (narrowness holds)."""
    src = textwrap.dedent('''
        def _settle_merge_core(wt, ticket_id, round_no):
            msg = ("%s conflict resolution (round %d)" % (ticket_id, round_no))
            p = _git(["commit", "--no-edit", "-m", msg], wt)
            return p

        def _settle_stage(wt, ticket_id, stage_id, gen, n):
            msg = ("%s %s：worker 代落盘（gen%d，%d 项改动）" % (ticket_id, stage_id, gen, n))  # copy-lang-allow:fixture
            p = _git(["commit", "-m", msg], wt)
            return p

        def _squash_merge(repo, ticket_id, branch):
            msg = ("%s squash 收口（一单一提交）\\n\\n来源 %s" % (ticket_id, branch))  # copy-lang-allow:fixture
            c = _git(["commit", "-m", msg], repo)
            return c

        def _other(wt):
            msg = "log-only 中文 in a function without a git commit is out of the anchor"  # copy-lang-allow:fixture
            return msg
    ''')
    p = tmp_path / "commit.py"
    p.write_text(src, encoding="utf-8")
    fs = guard.scan_paths([str(p)])
    assert len(fs) == 2, [guard.format_finding(f) for f in fs]
    assert sorted(f["line"] for f in fs) == [8, 13]
    assert all(f["kind"] == "commit-subject" for f in fs)


def test_b5_unparseable_source_is_a_named_finding_not_a_crash(tmp_path):
    p = tmp_path / "broken.py"
    p.write_text("def f(:\n    pass 中文", encoding="utf-8")  # copy-lang-allow:fixture
    fs = guard.scan_paths([str(p)])
    assert len(fs) == 1 and fs[0]["kind"] == "unparseable"


def test_b6_exemptions_are_an_explicit_named_list(tmp_path):
    p = tmp_path / "exempt.py"
    p.write_text('self._mark("s", "running", "特批字面量")\n', encoding="utf-8")  # copy-lang-allow:fixture
    assert len(guard.scan_paths([str(p)])) == 1
    guard.EXEMPTIONS.add(("exempt.py", 1, "reason", "特批字面量"))  # copy-lang-allow:fixture
    try:
        assert guard.scan_paths([str(p)]) == []
    finally:
        guard.EXEMPTIONS.clear()
    assert guard.EXEMPTIONS == set(), "the shipped default list stays empty"


def test_b7_live_engine_scan_is_green():
    """The real guard over the real engine files: zero findings after t261008-47."""
    fs = guard.scan_paths([str(POC / n) for n in
                           ("dev_lane.py", "light_lane.py", "agent_activities.py")])
    assert fs == [], [guard.format_finding(f) for f in fs]


# ===================================================================================
# C. fixture-ticket face (L3, unit level)
# ===================================================================================

def _stub_ticket():
    wf = SimpleNamespace()
    wf.ticket_id = "t-stub"
    wf.timeline = []
    wf.meta = {}
    wf._detail_face_on = True
    wf._now_iso = lambda: _iso(NOW)
    wf._now_epoch = lambda: NOW
    wf._gens = {}
    wf._gen = lambda step: wf._gens.get(step, 1)
    wf._ledger_enqueue = lambda entry: None
    wf.engine_version = "ut-stub"
    return wf


@pytest.fixture(autouse=True)
def _plain_workflow_logger(monkeypatch):
    """_mark logs via temporalio.workflow.logger, which refuses to run outside a
    workflow event loop — swap in a plain stdlib logger for the stub ticket."""
    import logging
    import dev_lane
    monkeypatch.setattr(dev_lane.workflow, "logger", logging.getLogger("ut-stub"))


def test_c1_stage_entry_reason_is_english_with_attempt_preserved():
    import dev_lane
    wf = _stub_ticket()
    for gen in (1, 2):
        wf._gens["create_plan"] = gen
        dev_lane.DevLaneWorkflow._mark(wf, "create_plan", "running",
                                       "Entered step (attempt %d)" % gen)
    reasons = [e["reason"] for e in wf.timeline]
    assert reasons == ["Entered step (attempt 1)", "Entered step (attempt 2)"]
    assert all(not guard.CJK.search(r) for r in reasons)
    assert [e["gen"] for e in wf.timeline] == [1, 2], "attempt numbers are data: kept"


def test_c2_all_stage_acceptance_items_carry_no_cjk():
    import dev_lane
    import light_lane
    for cls in (dev_lane.DevLaneWorkflow, light_lane.LightLaneWorkflow):
        for st in cls.STAGES:
            for item in st.acceptance:
                assert not guard.CJK.search(item), "%s.%s: %r" % (cls.__name__, st.id, item)


def test_c3_handoff_summaries_are_english_and_history_rows_untouched():
    import dev_lane
    wf = _stub_ticket()
    dev_lane.DevLaneWorkflow._handoff(wf, "merge", "Merge completed abc1234")
    dev_lane.DevLaneWorkflow._handoff(wf, "arbitrate",
                                      "code-fault back to implement (round %d)" % 2,
                                      report="integration test report")
    hs = wf.meta["handoffs"]
    assert [h["summary"] for h in hs] == [
        "Merge completed abc1234", "code-fault back to implement (round 2)"]
    assert all(not guard.CJK.search(h["summary"]) for h in hs)
    # history is data: an old Chinese row appended to the timeline is neither
    # rewritten nor filtered — it still renders, and the parser still reads it.
    wf.timeline.append({"at": _iso(NOW - 3600), "stage": "implement",
                        "state": "running", "gen": 1,
                        "reason": OLD_ROW % 1})
    reasons = [e["reason"] for e in wf.timeline]
    assert any(OLD_ROW % 1 == r for r in reasons), "stored history must not be rewritten"
    f = lw.facts_from_snapshot("t-history", "sandbar",
                               _snapshot(list(wf.timeline)), now_ts=NOW)
    assert f["suite_rounds"] == 0          # it is not a run_integration_tests row
    # the old row's at feeds last_activity_at (max over timeline/log/updated; the
    # stub meta pins updated/log at NOW, so the max is NOW — the row was read)
    assert f["last_activity_at"] == pytest.approx(NOW)


def test_c4_guard_leaves_a_source_file_with_history_shaped_data_alone(tmp_path):
    """The negative case at the source level: Chinese literals inside data
    structures/comments (simulating stored rows) do not trip the guard."""
    src = textwrap.dedent('''
        STORED = [{"stage": "implement", "state": "running",
                   "reason": "进入本步（第 1 次）"}]  # history is data  # copy-lang-allow:fixture
        def render(rows):
            return rows  # 面板原样渲染历史行  # copy-lang-allow:fixture
    ''')
    p = tmp_path / "history_data.py"
    p.write_text(src, encoding="utf-8")
    assert guard.scan_paths([str(p)]) == []
