"""260929 单测（宿主令追改）：声明式空转 —— 「没有新 change 就不干啥」。

宿主 260929 令：simplify-face 改每天一次，且**无新变更就空转不干活**。空转不是「悄悄的
跳过」，而是一等状态，本单测锁四件事：

  ①判据（纯函数 no_change_skip）：上次运行基点 sha == 当前 main HEAD ⇒ 空转；任一侧读不出
    或形态不合 ⇒ **不跳**（假跳＝静默漏跑，比浪费一次贵得多）；
  ②读面：last_run_base 从台账里取「最近一次真跑过」的期号与基点（lane/suite/scan_meta 三处
    任一）；spawn_skip_periods 从起票裁决日志取已解释的空转期号（坏行容错）；
  ③裁决记录：空转落一行 decision=skipped-no-change 且 **alarm=False**（按声明判定无事可做
    ≠ 该跑而没跑）；
  ④**漏跑核查不许报假警**：同一期号，无记录时报漏跑；有该记录时不算漏跑并单列
    skipped_no_change（CLI deadman --offline 实盘对照，两个方向都测）。

运行：server/engine/.venv/bin/python -B -m pytest \
      server/engine/tests/test_260929_inspection_no_change_skip.py -q
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import inspection_decl as decl_mod  # noqa: E402
import inspection_ticketing as tick  # noqa: E402
import inspection_trigger as trig  # noqa: E402

INST = "simplify-face"
SHA = "29b915423e134b38fa99fcf3249e639bd2ed4867"
OTHER = "0f1e2d3c4b5a69788796a5b4c3d2e1f009182736"

DECL_YAML = """schema: v1
instances:
  - id: simplify-face
    enabled: true
    project_key: sandbar
    scan_face: simplify
    skip_when_unchanged: true
    tz: Asia/Shanghai
    schedule:
      kind: cron
      cron: 30 9 * * *
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
"""


# ---------------- ①判据（纯函数） ----------------

def test_same_head_means_skip():
    v = tick.no_change_skip(SHA, SHA, last_period="20260928")
    assert v["unchanged"] is True
    assert SHA[:7] in v["why"] and "20260928" in v["why"]


def test_moved_head_means_run():
    assert tick.no_change_skip(SHA, OTHER)["unchanged"] is False


@pytest.mark.parametrize("last,head", [
    ("", SHA), (SHA, ""), ("", ""), ("not-a-sha", "not-a-sha"),
    ("abc", "abc"), (SHA[:6], SHA[:6]), ("HEAD", "HEAD"),
])
def test_illegible_bases_never_skip(last, head):
    """判不准**不跳**：宁可多跑一次，绝不假跳（假跳＝静默漏跑）。"""
    assert tick.no_change_skip(last, head)["unchanged"] is False


# ---------------- ②读面 ----------------

def _ledger(d, period, base):
    (d / tick.ledger_file_name(INST, period)).write_text(
        json.dumps({"period": period, "lane": {"base_ref": base}}), encoding="utf-8")


def test_last_run_base_picks_the_newest_period(tmp_path):
    _ledger(tmp_path, "20260927", OTHER)
    _ledger(tmp_path, "20260928", SHA)
    got = tick.last_run_base(tmp_path, INST)
    assert got == {"period": "20260928", "base_ref": SHA}


def test_last_run_base_falls_back_to_suite_and_scan_meta(tmp_path):
    (tmp_path / tick.ledger_file_name(INST, "20260928")).write_text(
        json.dumps({"suite": {"base_ref": OTHER}}), encoding="utf-8")
    assert tick.last_run_base(tmp_path, INST)["base_ref"] == OTHER
    (tmp_path / tick.ledger_file_name(INST, "20260928")).write_text(
        json.dumps({"scan_meta": {"inspect": {"base_head": SHA}}}), encoding="utf-8")
    assert tick.last_run_base(tmp_path, INST)["base_ref"] == SHA


def test_last_run_base_is_empty_when_nothing_ran(tmp_path):
    assert tick.last_run_base(tmp_path, INST) == {"period": "", "base_ref": ""}
    # 台账在但读不出基点（畸形/无该键）→ 也当读不出（不跳）
    (tmp_path / tick.ledger_file_name(INST, "20260928")).write_text("{not json", encoding="utf-8")
    assert tick.last_run_base(tmp_path, INST)["base_ref"] == ""


def test_spawn_skip_periods_reads_only_own_instance_and_tolerates_garbage(tmp_path):
    p = tmp_path / tick.SPAWN_JOURNAL_NAME
    p.write_text("\n".join([
        "not json at all",
        json.dumps({"instance": INST, "period": "20260929",
                    "decision": "skipped-no-change"}),
        json.dumps({"instance": "integration-tests", "period": "20260929",
                    "decision": "skipped-no-change"}),   # 别的实例：不算
        json.dumps({"instance": INST, "period": "20260930", "decision": "triggered"}),
        "",
    ]), encoding="utf-8")
    assert tick.spawn_skip_periods(tmp_path, INST) == {"20260929"}


def test_no_journal_is_empty_not_an_error(tmp_path):
    assert tick.spawn_skip_periods(tmp_path, INST) == set()


# ---------------- ③裁决记录 ----------------

def test_skip_decision_is_recorded_without_alarm(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(tmp_path / "admin.log"))
    res = {"ok": True, "result": {
        "triggered": False, "deduped": False, "skipped": "no-new-changes",
        "skipped_because": "main 无新变更（HEAD 仍为 %s，与上次运行（期 20260928）的基点相同）"
                           "——按声明 skip_when_unchanged 空转不干活" % SHA[:7],
        "instance": INST, "period": "20260929"}}
    note = tick.note_spawn_decision(tmp_path, INST, "20260929", res, face="cron")
    assert note["decision"] == "skipped-no-change"
    assert note["alarm"] is False, "按声明空转 ≠ 该跑而没跑，不许告警"
    assert "无新变更" in note["note"]
    row = json.loads((tmp_path / tick.SPAWN_JOURNAL_NAME).read_text("utf-8").strip())
    assert row["decision"] == "skipped-no-change" and row["alarm"] is False


# ---------------- ④漏跑核查不报假警（CLI 实盘两方向） ----------------

def _past_period(days_ago: int) -> str:
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y%m%d")


def _deadman(tmp_path, ledger_dir, decl_path):
    args = trig.argparse.Namespace(
        instance=INST, ledger_dir=str(ledger_dir), decl_path=str(decl_path),
        lookback_days=7, grace_days=0, offline=True)
    return asyncio.run(trig.cmd_deadman(args))


def _fixtures(tmp_path):
    decl_path = tmp_path / "inspection.yaml"
    decl_path.write_text(DECL_YAML, encoding="utf-8")
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    return decl_path, ledger


def test_deadman_reports_a_real_miss(tmp_path):
    decl_path, ledger = _fixtures(tmp_path)
    period = _past_period(3)
    res = _deadman(tmp_path, ledger, decl_path)
    assert res["ok"] is True, res
    assert period in res["result"]["missed"], "没跑又没记录＝漏跑，必须报"
    assert res["result"]["alarmed"] is True


def test_deadman_does_not_cry_wolf_over_a_declared_skip(tmp_path):
    """一期「按声明空转」+ 其余期都真跑过 ⇒ 漏跑为空且**不告警**（这条记录足以让那天
    不响警报：审计面既不说谎，也不报警报成噪声）。"""
    import inspection_deadman as deadman
    decl_path, ledger = _fixtures(tmp_path)
    fires = [f.strftime("%Y%m%d") for f in
             deadman.expected_fires("30 9 * * *", datetime.now(), 7)]
    assert len(fires) >= 3, fires
    period = fires[-1]
    for key in fires[:-1]:                     # 其余期真跑过（有台账）
        _ledger(ledger, key, SHA)
    (ledger / tick.SPAWN_JOURNAL_NAME).write_text(
        json.dumps({"instance": INST, "period": period, "decision": "skipped-no-change",
                    "alarm": False, "note": "main 无新变更"}) + "\n", encoding="utf-8")
    res = _deadman(tmp_path, ledger, decl_path)
    assert res["ok"] is True, res
    assert res["result"]["missed"] == [], "按声明判定无事可做 + 其余期有台账 ⇒ 零漏跑"
    assert res["result"]["skipped_no_change"] == [period], "但要能看见它为什么没跑"
    assert res["result"]["alarmed"] is False


def test_deadman_still_reports_the_other_missing_periods(tmp_path):
    """空转记录只解释它自己那一期——别的缺日照报（不许被一条记录整体洗白）。"""
    decl_path, ledger = _fixtures(tmp_path)
    skipped, missed = _past_period(2), _past_period(4)
    (ledger / tick.SPAWN_JOURNAL_NAME).write_text(
        json.dumps({"instance": INST, "period": skipped, "decision": "skipped-no-change"}) + "\n",
        encoding="utf-8")
    res = _deadman(tmp_path, ledger, decl_path)
    assert skipped not in res["result"]["missed"]
    assert missed in res["result"]["missed"], "别的缺日照旧报（绝不整体洗白）"


# ---------------- 声明面 ----------------

def test_decl_parses_the_skip_switch_and_threads_it_into_the_plan(tmp_path):
    p = tmp_path / "inspection.yaml"
    p.write_text(DECL_YAML, encoding="utf-8")
    decl = decl_mod.load_inspection_decl(p)
    it = decl.instance(INST)
    assert it.skip_when_unchanged is True
    plan = decl_mod._plan_from_decl(decl, INST)
    assert plan["skip_when_unchanged"] is True
    specs = decl_mod.build_schedule_specs(decl)
    assert specs and specs[0]["skip_when_unchanged"] is True


def test_decl_rejects_a_non_boolean_switch(tmp_path):
    p = tmp_path / "inspection.yaml"
    p.write_text(DECL_YAML.replace("skip_when_unchanged: true", "skip_when_unchanged: yes"),
                 encoding="utf-8")
    with pytest.raises(decl_mod.DeclError) as ei:
        decl_mod.load_inspection_decl(p)
    assert "skip_when_unchanged" in str(ei.value)


# ---------------- 生产声明：空转开关不变量（t261004-20 改写） ----------------

# Change-driven scan faces (260929 host order): the skip switch means "no new
# change since the last run ⇒ idle", which is only meaningful for a face whose
# workload IS the change stream. Vocabulary owned here until the production
# decl module grows the constant (write-set boundary; see lane handoff).
CHANGE_DRIVEN_FACES = ("simplify",)


def assert_skip_flags_lawful(decl, raw_text=None):
    """Invariant seam (t261004-20): takes a parsed declaration, never a machine
    path — the deliberate-red demo runs this against a tmp-path decl copy.

    Locked (the 260929 decision itself): a skip_when_unchanged flag is lawful
    only on an instance whose scan face is change-driven, and the reason for the
    flag is written in the declaration (a full-line comment inside the instance
    block — the zero-dependency parser drops comments, so the reason is checked
    on the raw text). NOT locked: WHICH instances carry the flag, nor any
    current cron string — that set is a production snapshot and changes lawfully.
    """
    for it in decl.instances:
        if not it.skip_when_unchanged:
            continue
        assert it.scan_face in CHANGE_DRIVEN_FACES, (
            "instance %s: skip_when_unchanged is only lawful on a change-driven "
            "face %s, got %r" % (it.id, CHANGE_DRIVEN_FACES, it.scan_face))
        if raw_text is not None:
            lines = raw_text.splitlines()
            for no, line in enumerate(lines):
                if line.strip() == "skip_when_unchanged: true":
                    # the reason lives anywhere in this instance's block: scan up to
                    # the block head (the "- id:" line that opens the item)
                    start = no
                    while start > 0 and not lines[start].lstrip().startswith("- id:"):
                        start -= 1
                    # the reason may also sit in the comment banner right above the
                    # "- id:" line (the usual place a rule is quoted) — include it
                    head = start - 1
                    while head >= 0 and (lines[head].strip().startswith("#")
                                         or not lines[head].strip()):
                        head -= 1
                    block = lines[head + 1:no + 1]
                    assert any(l.strip().startswith("#") for l in block), (
                        "instance %s: the skip flag needs its reason written in the "
                        "declaration (a comment inside the instance block)" % it.id)
                    break
            else:
                raise AssertionError("skip_when_unchanged: true not found in raw text")


def test_production_declaration_skip_flags_are_lawful():
    """Production declaration: the skip switch lands only on change-driven faces,
    and its reason is written in the declaration (the 260929 decision itself).

    Path resolved from the repository root (t261004-20): this test inspects the
    tree it runs in; binding the writing host's machine-absolute path would make
    a lane worktree read the main checkout instead (wrong tree).
    """
    repo = POC.parent.parent
    decl_path = repo / "inspection.yaml"
    raw = decl_path.read_text(encoding="utf-8")
    decl = decl_mod.load_inspection_decl(decl_path)
    assert_skip_flags_lawful(decl, raw_text=raw)
    # tz invariant kept (same 260929 batch: missing tz falls to UTC and shifts the
    # human clock) — locked on flagged instances only, not on any clock literal.
    for it in decl.instances:
        if it.skip_when_unchanged:
            assert it.tz, "instance %s: explicit tz required" % it.id
