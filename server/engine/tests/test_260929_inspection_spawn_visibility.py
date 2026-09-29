"""260929 单测（KI-129 修法② / KI-131「仍未修」块）：起票裁决必须落可观测面。

病根（260929 宿主实报「集成测试的巡检没有了」的机制半边）：自动班
（cron → schedule → InspectionPeriodicSpawnWorkflow → spawn_inspection_period）
去重命中时**只有 50ms 的返回值** `{"deduped":true,"triggered":false}`——无新票、无报告、
无告警。09-27 起每天如此（09-26 换期处置提前消费了 09-27…10-02 六期），deadman 也看不见
（它只认台账文件，而台账恰是提前服务留下的）。本单测锁两件事：

  ①裁决口径（纯函数 spawn_decision_of）：什么算「本期该跑而没跑」（alarm）——
    起票失败 / 期槽被非终态票占住 / 期槽被判已服务但台账缺失；已服务且台账在场不告警；
  ②两个可观测面真的写了：台账目录 `inspection-spawn.jsonl` 一行 + admin.log 一行
    （写失败只在回执点名，绝不抛、绝不静默）；且 **.jsonl 不进 deadman 期号集合**
    ——写下「本期没跑」绝不能被读成「本期跑过」（否则漏跑核查反被自己的记录骗过）。

UT 全程禁网络/真 Temporal：admin.log 走 SANDBAR_ADMIN_LOG 隔离，台账目录走 tmp_path。
运行：server/engine/.venv/bin/python -B -m pytest \
      server/engine/tests/test_260929_inspection_spawn_visibility.py -q
"""
import json
import os
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import inspection_ticketing as tick  # noqa: E402
import inspection_deadman as deadman  # noqa: E402

INST = "integration-tests"
PERIOD = "20260929"


def _ok(**result):
    return {"ok": True, "result": result}


def _dedup_live():
    return _ok(triggered=False, deduped=True, dedup_source="sa_query",
               ticket_id="t260927-01", period_state="live", stale_pointer_cleared=None)


def _dedup_served():
    return _ok(triggered=False, deduped=True, dedup_source="sa_query",
               ticket_id="t260929-01", period_state="completed",
               reopen_hint="该期已服务；要重跑请带 reopen_reason 具名重开")


def _triggered():
    return _ok(triggered=True, deduped=False, ticket_id="t260929-30",
               period_state="claimed", scan_mode="prefix")


# ---------------- ①裁决口径（纯函数） ----------------

def test_failed_spawn_alarms_with_the_named_error():
    d = tick.spawn_decision_of({"ok": False, "error": "声明决议失败：实例不在声明里"})
    assert d["decision"] == "failed"
    assert d["alarm"] is True
    assert "声明决议失败" in d["note"], "错误必须精确：note 要点名真因，不许说「没有 X」"


def test_live_slot_occupant_alarms_ki129():
    d = tick.spawn_decision_of(_dedup_live())
    assert d["decision"] == "deduped" and d["period_state"] == "live"
    assert d["alarm"] is True, "期槽被非终态票占住＝本期真丢，必须告警（KI-129 形态）"
    assert "t260927-01" in d["note"] and "换期" in d["note"]


def test_served_slot_with_ledger_is_normal_no_alarm(tmp_path):
    (tmp_path / tick.ledger_file_name(INST, PERIOD)).write_text("{}", encoding="utf-8")
    d = tick.spawn_decision_of(_dedup_served(), ledger_dir=tmp_path,
                               instance_id=INST, period=PERIOD)
    assert d["decision"] == "deduped" and d["alarm"] is False, "已服务且有台账＝合法（提前服务/重开）"
    assert "服务过" in d["note"] and "天前" in d["note"], "note 要点明本班不是本期第一次服务"
    assert "reopen_reason" in d["note"], "note 要给重跑入口"


def test_served_slot_without_ledger_alarms_ki131(tmp_path):
    d = tick.spawn_decision_of(_dedup_served(), ledger_dir=tmp_path,
                               instance_id=INST, period=PERIOD)
    assert d["alarm"] is True, "期槽被判已服务却无台账＝跑过没出报告，本班不会重跑它（KI-131）"
    assert "台账不在场" in d["note"]


def test_triggered_is_recorded_but_never_alarms():
    d = tick.spawn_decision_of(_triggered())
    assert d["decision"] == "triggered" and d["alarm"] is False
    assert d["ticket_id"] == "t260929-30"


@pytest.mark.parametrize("res", [None, [], "boom", {"ok": True}, {"ok": True, "result": None}])
def test_malformed_receipts_degrade_without_raising(res):
    d = tick.spawn_decision_of(res)      # 畸形外部输入：降级不抛（本层纪律）
    assert d["decision"] in ("failed", "deduped")
    assert isinstance(d["note"], str) and d["note"]


# ---------------- ②两个面真的写了 ----------------

@pytest.fixture()
def isolated_audit(tmp_path, monkeypatch):
    """admin.log 隔离（绝不许 UT 碰真 server/admin.log——KI-161 同族纪律）。"""
    log = tmp_path / "admin.log"
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(log))
    return log


def test_note_writes_journal_and_admin_log(tmp_path, isolated_audit):
    led = tmp_path / "ledger"
    led.mkdir()
    # 真实 09-29 形态：该期台账在场（提前服务留下的），本次自动班去重跳过
    (led / tick.ledger_file_name(INST, PERIOD)).write_text("{}", encoding="utf-8")
    note = tick.note_spawn_decision(led, INST, PERIOD, _dedup_served(), face="cron")
    # ①台账目录一行（.jsonl）
    jlines = (led / tick.SPAWN_JOURNAL_NAME).read_text("utf-8").strip().splitlines()
    assert len(jlines) == 1
    row = json.loads(jlines[0])
    assert row["instance"] == INST and row["period"] == PERIOD and row["face"] == "cron"
    assert row["decision"] == "deduped" and row["period_state"] == "completed"
    assert row["alarm"] is False and row["ticket_id"] == "t260929-01"
    assert isinstance(row["at"], float)
    # ②admin.log 一行（sub=inspection-spawn；audit_call 单一收口）
    alogs = isolated_audit.read_text("utf-8").strip().splitlines()
    assert len(alogs) == 1
    aline = json.loads(alogs[0])
    assert aline["sub"] == "inspection-spawn" and aline["ok"] is True
    assert '"decision": "deduped"' in aline["summary"]
    assert note["journal_path"].endswith(tick.SPAWN_JOURNAL_NAME)
    assert note["audit_call_id"] and "audit_write_failed" not in note
    assert "journal_error" not in note


def test_note_alarms_reach_the_journal(tmp_path, isolated_audit):
    led = tmp_path / "ledger"
    tick.note_spawn_decision(led, INST, PERIOD, _dedup_live(), face="cron")
    row = json.loads((led / tick.SPAWN_JOURNAL_NAME).read_text("utf-8").strip())
    assert row["alarm"] is True and row["period_state"] == "live"


def test_journal_is_append_only(tmp_path, isolated_audit):
    led = tmp_path / "ledger"
    for res in (_dedup_live(), _triggered(), _dedup_served()):
        tick.note_spawn_decision(led, INST, PERIOD, res, face="cron")
    rows = [json.loads(x) for x in
            (led / tick.SPAWN_JOURNAL_NAME).read_text("utf-8").strip().splitlines()]
    assert [r["decision"] for r in rows] == ["deduped", "triggered", "deduped"], \
        "起票裁决必须逐次留痕（覆盖写＝审计断链）"


def test_journal_never_counts_as_a_ledger_period(tmp_path, isolated_audit):
    """写下「本期没跑」绝不能被读成「本期跑过」——漏跑核查的会计面不许被自己的记录骗过。"""
    led = tmp_path / "ledger"
    tick.note_spawn_decision(led, INST, PERIOD, _dedup_live(), face="cron")
    led_info = deadman.ledger_periods(led, INST)
    assert led_info["periods"] == set(), "起票日志（.jsonl）不得进期号集合"
    assert led_info["malformed"] == [], "起票日志也不得进畸形桶（旧口径：.jsonl 全跳过）"
    # 反向样本：真台账在场时照旧计期——会计面没被本改动搞坏
    (led / tick.ledger_file_name(INST, PERIOD)).write_text("{}", encoding="utf-8")
    assert deadman.ledger_periods(led, INST)["periods"] == {PERIOD}


def test_journal_write_failure_is_named_not_raised(tmp_path, isolated_audit):
    """台账目录不可写（此处＝路径被普通文件占住）：点名进回执，绝不抛、绝不静默。"""
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("x", encoding="utf-8")
    note = tick.note_spawn_decision(blocked, INST, PERIOD, _dedup_live(), face="cron")
    assert note["journal_error"], "审计缺失必须点名（绝不静默）"
    assert note["decision"] == "deduped" and note["alarm"] is True, "写盘失败不得改变裁决本身"


def test_ledger_name_matches_engine_single_source():
    """台账名两处编码（本模块 / inspection_flow.inspection_ledger_name）不得漂移。"""
    import inspection_flow as flow
    for inst, period in ((INST, PERIOD), ("docs-sync", "20261001"),
                         ("integration-tests", "20260929-2")):
        assert tick.ledger_file_name(inst, period) == flow.inspection_ledger_name(inst, period)


# ---------------- ③运行期目录隔离看守（260929 实测漏网的机械面） ----------------

def test_files_that_execute_the_write_path_isolate_runtime_dirs():
    """凡**真执行**起票裁决写路径的测试文件，必须隔离两个运行期目录。

    实测教训（260929 夜）：test_t260917_02_inspection_redirect.py 直接调
    spawn_inspection_period（桩注入），而本修法给该活动新增了落盘面 ⇒ 夹具数据
    （period=20260901 / ticket=t260917-01）被打进生产 out/inspection/ 与
    server/admin.log 共 6 行（KI-161「测试面写生产数据目录」同族，这次是**我们自己的
    修正**引入的）。本条把它钉成机械看守：命令面文件一旦执行写路径，缺隔离即红。"""
    import re
    tests_dir = Path(__file__).resolve().parent
    call = re.compile(r"(spawn_inspection_period\(|trigger_inspection_period\(|"
                      r"_with_spawn_decision\(|cmd_trigger\()")
    offenders = []
    for f in sorted(tests_dir.glob("test_*.py")):
        src = f.read_text("utf-8")
        if not call.search(src):
            continue
        has_admin = "SANDBAR_ADMIN_LOG" in src
        has_ledger = ("SANDBAR_INSPECTION_DIR" in src) or ("ledger_dir" in src)
        if not (has_admin and has_ledger):
            offenders.append("%s(admin_log=%s, ledger=%s)" % (f.name, has_admin, has_ledger))
    assert not offenders, (
        "以下测试文件执行了「起票裁决」写路径却未隔离运行期目录（夹具会写进生产台账/"
        "admin.log）：" + "；".join(offenders))
