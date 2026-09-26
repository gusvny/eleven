#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""260927 · 套件段「跑不完 + 零信号 + 归因错」结构性病灶的回归棒（L1，零 IO）。

现场（t260927-01 期 20260927 事件史，宿主钉死）：
  `run_inspection_suite` 23:41:19 scheduled（start_to_close=SUITE_TO=5100s）→ 01:06:19
  ACTIVITY_TASK_TIMED_OUT（恰 85min）→ 紧接着 teardown_lane → 中央工人日志在超时后
  2.5min 才出现该活动一行 `ran=0 pass=0 fail=0`，其回执 error 是 `admin.log` 的
  FileNotFoundError。真因是**活动超时**，但迟到孤儿回执把它伪装成了中性 ran=0。

三条回归（对应宿主验收口径 ②③④）：
  ① 总预算耗尽的回执形状与点名（走 INTEG_SUMMARY 的 budget 块 → 发现清单 → 票面段）；
  ② 迟到孤儿回执**不得覆盖权威回执**（换名落盘 + error 点名 + 台账扫描不当畸形件）；
  ③ 工作流超时分支具名（`suite_timeout=True` + 非空 error 点名超时值；一般故障两态可辨）。

零 IO、零 Temporal：纯函数 + 临时目录 + 桩（既有测试的 fake/stub 手法）。
"""
import asyncio
import json
import os
import sys

import pytest

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ENGINE)
sys.path.insert(0, os.path.join(ENGINE, "..", "tools"))

import agent_activities as aa  # noqa: E402
import inspection_deadman as deadman  # noqa: E402
import inspection_flow as flow  # noqa: E402

# 执行器模块（只读 import：注册表是数据，模块顶层零 IO 零重依赖）——跨模块单源锁要
# 直读它的常量与纯函数，不靠字符串复述。
RUNNER_DIR = os.path.join(os.path.dirname(ENGINE), "..", "integration")
sys.path.insert(0, os.path.abspath(RUNNER_DIR))
import run_scenarios as rs  # noqa: E402


# ========================================================================================
# ① 总预算耗尽的回执形状与点名
# ========================================================================================

#: 执行器总预算耗尽的**真实** stdout 形态（与 run_scenarios._budget_exhausted_exit 同源；
#: 跨模块同串由本文件的 test_runner_budget_faces_are_single_source 反向钉住）。
BUDGET_STDOUT = (
    "PASS [a-scenario] (1.2s)\n"
    "FAIL [__budget__] 总预算耗尽（5400s）：已跑 1/319 条、未跑 318 条——执行器自行收口，"
    "不等外层硬杀（260927 套件段预算纪律）\n"
    "ENV_FAIL [b-scenario] exit=2 (0.0s)\n    总预算耗尽：未开跑（池=main）——本条不是跑红，"
    "是没验到（容量面）\n"
    "SCENARIOS ran=1 pass=1 fail=0 env_fail=318 na=0 (5401s)\n"
    "INTEG_BUDGET_EXHAUSTED 总预算耗尽：已跑 1/319 条、未跑 318 条、墙钟 5401s／预算 5400s\n"
    'INTEG_SUMMARY {"ran": 1, "pass": 1, "fail": 0, "not_checked": 318, "wall_s": 5401.0,'
    ' "expected": 319, "budget": {"exhausted": true, "budget_sec": 5400, "unrun_count": 318,'
    ' "unrun": ["b-scenario", "c-scenario"]}}\n'
)


def test_budget_signal_parsed_from_executor_stdout():
    """闸侧解析：标记行 + INTEG_SUMMARY 的 budget 块 → 结构化未跑清单（计数与名字都在）。"""
    import verify_lane as vl
    face = vl._parse_budget_signal(BUDGET_STDOUT)
    assert face.get("exhausted") is True
    assert face.get("unrun_count") == 318
    assert face.get("unrun") == ["b-scenario", "c-scenario"]
    assert face.get("budget_sec") == 5400
    assert "INTEG_BUDGET_EXHAUSTED" in face.get("line", "")
    # 无信号（老执行器形态）= 零分支，绝不凭空造一个「预算耗尽」出来
    assert vl._parse_budget_signal("PASS [x] (1.0s)\n") == {}
    assert vl._parse_budget_signal("") == {}


def test_budget_receipt_becomes_named_finding_and_face_section():
    """回执形状与点名（必做②）：预算耗尽 ⇒ 一条**独立可见发现**（high、suggest=false、
    未跑批清单在证据里），进票面 suite 段的可读字段；且绝不落成中性 ran=0 的沉默。"""
    receipt = {
        "ticket_id": "t260927-01", "ran": 1, "passed": 1, "failed": 0, "env_fail": 318,
        "error": "", "details": [],
        "budget": {"exhausted": True, "budget_sec": 5400, "unrun_count": 318,
                   "unrun": ["b-scenario", "c-scenario"]},
        "report_path": "/out/inspection/inspection-x-20260927-suite.json",
    }
    findings = deadman.suite_findings(receipt)
    budget_findings = [f for f in findings if "总预算耗尽" in str(f.get("subject", ""))]
    assert len(budget_findings) == 1, [f.get("subject") for f in findings]
    f = budget_findings[0]
    assert f["severity"] == "high"
    assert f["suggest"] is False          # 容量/预算面，开「修码票」是错配
    assert "未跑批清单" in f["evidence"] and "b-scenario" in f["evidence"]
    assert "不是产品红" in f["evidence"]
    # 票面段（face["suite"]）透出预算块与两笔分相墙钟（缺键不乱造）
    section = deadman.suite_section(receipt)
    assert section["budget"]["unrun_count"] == 318
    assert section["error"] == ""
    assert deadman.suite_green(section) is False     # 没跑完=不绿（红线：不得以截断换绿）
    # 反向自证：没有 budget 键的旧回执**零新键**（老路径逐字节不变）
    old = {k: v for k, v in receipt.items() if k != "budget"}
    assert "budget" not in deadman.suite_section(old)
    assert not [x for x in deadman.suite_findings(old) if "总预算耗尽" in str(x.get("subject"))]


def test_runner_self_cuts_off_at_total_budget(tmp_path, monkeypatch):
    """端到端（进程内直调执行器）：总预算到点 ⇒ 执行器**自行收口**返回（不是被硬杀）——
    exit=2（容量面环境红，绝不 0 冒充绿、也绝不 1 诬成产品红）、未跑条目逐条点名
    （ENV_FAIL 行）、`INTEG_BUDGET_EXHAUSTED` 标记行与 INTEG_SUMMARY 的 budget 块在场。
    这正是 t260927-01 缺失的那一段：旧形态下活动被 Temporal 判死，套件连「跑到哪」的
    话都说不出来。"""

    # 注册表桩（走 only_scenarios 单源消费路径，不触真注册表）：3 条 fast 条。
    monkeypatch.setattr(rs, "SCENARIOS", [
        ("zzz-a", "预算耗尽用例：条 a", "true", "ro"),
        ("zzz-b", "预算耗尽用例：条 b", "true", "ro"),
        ("zzz-c", "预算耗尽用例：条 c", "true", "ro"),
    ])
    monkeypatch.setattr(rs, "batch_consumers", lambda entries: [])
    monkeypatch.setattr(rs, "batch_preboot", lambda consumers: True)
    monkeypatch.setattr(rs, "batch_teardown", lambda: None)
    monkeypatch.setattr(rs, "_sweep_residue_stages", lambda: None)
    monkeypatch.setattr(rs, "_docker_hygiene", lambda: None)
    # 点名面单源：main() 的 only_scenarios 参数是**已解析名单**（解析器吃逗号串），
    # 这里直给名单，绕开逗号切分（桩的是消费面不是解析面）。
    monkeypatch.setattr(rs, "parse_only_scenarios", lambda raw: list(raw or []))

    # 单调钟桩（确定性吃光预算，不靠真 sleep 的抖动）：每次读钟比上次多 10 秒——
    # 第 1 条记录 t0（建立基准），第 2 条起预算已尽（3 条全部进未跑清单）。
    clock = {"n": 0.0}

    def _mono():
        clock["n"] += 10.0
        return clock["n"]
    monkeypatch.setattr(rs.time, "monotonic", _mono, raising=True)

    monkeypatch.setenv(rs.RUN_BUDGET_ENV, "2")
    monkeypatch.setenv("SANDBAR_POOL_CONC", "1")
    monkeypatch.chdir(tmp_path)                    # 报告落档 out/ 不脏工作树
    # 收口用 os._exit 立刻退（不 join 存活线程，见 _budget_exhausted_exit 头注）——
    # 进程内测里把它换成抛 SystemExit（同一个 os 对象，生产语义不变），否则会杀掉 pytest。
    def _exit_as_raise(code):
        raise SystemExit(code)
    monkeypatch.setattr(os, "_exit", _exit_as_raise, raising=True)

    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        with pytest.raises(SystemExit) as ei:
            rs.main(only_scenarios=["zzz-a", "zzz-b", "zzz-c"])
    out = buf.getvalue()
    assert ei.value.code == 2, out[-2000:]
    assert "INTEG_BUDGET_EXHAUSTED" in out, out[-2000:]
    assert "总预算耗尽" in out
    assert "ENV_FAIL [zzz-a] exit=2" in out, "未跑条没有被逐条点名"
    assert "ENV_FAIL [zzz-b] exit=2" in out
    assert "ENV_FAIL [zzz-c] exit=2" in out
    assert "FAIL [__budget__]" in out
    # 一条都没跑（钟桩让预算在前奏就尽）——但**不是零信号**：预算标记行与未跑清单都在
    assert "SCENARIOS ran=3 pass=0 fail=0 env_fail=3" in out, out[-1200:]
    # 闸侧能把这轮读成「预算耗尽」而不是零信号
    import verify_lane as vl
    face = vl._parse_budget_signal(out)
    assert face.get("exhausted") is True
    assert set(face.get("unrun") or []) == {"zzz-a", "zzz-b", "zzz-c"}, face


def test_runner_budget_faces_are_single_source():
    """跨模块单源锁：执行器的预算标记串 / env 键 / 闸的解析前缀 / 引擎的下发 env 四处
    必须同串——改一侧不改另一侧，就是下一次「预算耗尽读不出来」。"""
    import verify_lane as vl
    assert rs.RUN_BUDGET_ENV == "SANDBAR_INTEG_RUN_BUDGET_SEC"
    assert vl.BUDGET_SIGNAL_PREFIX in open(
        os.path.join(os.path.abspath(RUNNER_DIR), "run_scenarios.py"),
        encoding="utf-8").read(), "闸的解析前缀在执行器里找不到=读不出预算耗尽"
    assert rs.RUN_BUDGET_ENV in open(
        os.path.join(ENGINE, "agent_activities.py"), encoding="utf-8").read(), \
        "引擎侧没有下发预算 env=执行器永远收不到预算"
    # 供给预算 env 同款单源（闸读 / 引擎下发）
    assert vl.SUPPLY_TIMEOUT_ENV in open(
        os.path.join(ENGINE, "agent_activities.py"), encoding="utf-8").read()
    # 预算解析纯函数：缺省/畸形/非正 → 0（不启用），正数原样
    assert rs.parse_run_budget(None) == 0.0
    assert rs.parse_run_budget("") == 0.0
    assert rs.parse_run_budget("abc") == 0.0
    assert rs.parse_run_budget("0") == 0.0
    assert rs.parse_run_budget("-5") == 0.0
    assert rs.parse_run_budget("5400") == 5400.0



# ========================================================================================
# ② 迟到孤儿回执不得覆盖权威回执
# ========================================================================================

def test_late_orphan_receipt_never_overwrites_authoritative(tmp_path):
    """必做③：活动超时后孤儿进程的迟到回执换名落 `-suite-late[-N].json`，
    **权威回执字节不变**；迟到件自己带 late/late_error 点名（error 非空=不中性）。"""
    inst, period = "integration-tests", "20260927"
    canon = tmp_path / ("inspection-%s-%s-suite.json" % (inst, period))
    authoritative = {"ticket_id": "t260927-01", "ran": 319, "passed": 319, "error": ""}
    canon.write_text(json.dumps(authoritative, ensure_ascii=False), encoding="utf-8")
    before = canon.read_bytes()

    orphan = {"ticket_id": "t260927-01", "ran": 0, "passed": 0, "failed": 0, "env_fail": 0,
              "error": "活动超时后孤儿进程：泳道目录已不在（…）——本回执不代表套件结果"}
    late_reason = "活动超时后孤儿进程：泳道目录已不在（/repo/.lane/inspection-x-20260927）"
    out = flow.write_inspection_suite_receipt_impl(
        inst, period, orphan, tmp_path, late_error=late_reason)
    assert out["late"] is True
    assert out["file"].endswith("-suite-late.json"), out["file"]
    assert canon.read_bytes() == before, "权威回执被迟到孤儿件覆盖（t260927-01 病根）"
    late_doc = json.loads((tmp_path / out["file"]).read_text(encoding="utf-8"))
    assert late_doc["late"] is True and late_doc["late_error"] == late_reason
    assert "不代表套件结果" in late_doc["error"]
    # 第二件迟到件：**再换号**，绝不覆写第一件（无静默覆盖纪律）
    out2 = flow.write_inspection_suite_receipt_impl(
        inst, period, dict(orphan), tmp_path, late_error=late_reason)
    assert out2["file"].endswith("-suite-late-2.json"), out2["file"]
    assert (tmp_path / out["file"]).exists() and (tmp_path / out2["file"]).exists()
    # 迟到件不进台账畸形桶、也不冒充台账（dead-man 漏跑核查零污染）
    led = deadman.ledger_periods(tmp_path, inst)
    assert led["malformed"] == [], led["malformed"]
    assert led["periods"] == set()
    # 迟到件上票面/发现面要点名「不代表套件结果」（不得被当套件结论消费）
    receipt = dict(orphan, late=True, late_error=late_reason,
                   report_path=str(tmp_path / out["file"]))
    subjects = [str(f.get("subject")) for f in deadman.suite_findings(receipt)]
    assert any("迟到孤儿件" in s for s in subjects), subjects
    section = deadman.suite_section(receipt)
    assert section["late"] is True and section["late_error"] == late_reason
    assert section["ok"] is False


def test_late_receipt_judgement_is_pure_and_two_state(tmp_path):
    """迟到判据两态可辨（泳道不在 / 越过宽限窗）；正常轮（泳道在、未越窗）**不判迟到**
    ——不把正常长轮（供给吃满 + 跑者吃满）误降级成 late。"""
    lane = tmp_path / "lane"
    lane.mkdir()
    suite_to, budget = 10800.0, 6600.0
    grace = aa._late_grace_sec(budget, suite_to)
    assert grace >= suite_to, "宽限窗必须容得下「活动超时 + 收尾」，否则正常长轮被判迟到"
    # 正常态：泳道在 + 墙钟在窗内 → 不迟到
    assert aa._late_suite_receipt_reason(str(lane), 100.0, budget, suite_to) == ""
    assert aa._late_suite_receipt_reason(str(lane), grace - 1.0, budget, suite_to) == ""
    # 态①：泳道不在（teardown 已腾空）→ 迟到，点名「不代表套件结果」
    why = aa._late_suite_receipt_reason(str(tmp_path / "gone"), 10.0, budget, suite_to)
    assert "活动超时后孤儿进程" in why and "不代表套件结果" in why
    # 态②：泳道在但越过宽限窗（> 活动超时 + 收尾余量）→ 迟到
    why2 = aa._late_suite_receipt_reason(str(lane), grace + 1.0, budget, suite_to)
    assert "宽限窗" in why2 and "不代表套件结果" in why2
    # 三项载荷全缺 → 兜底窗；窗内不判迟到（老载荷/老回放零误伤）
    assert aa._late_grace_sec(0.0, 0.0) == aa.SUITE_LATE_GRACE_FALLBACK_SEC
    assert aa._late_suite_receipt_reason(str(lane), 60.0) == ""


# ========================================================================================
# ③ 工作流超时分支具名
# ========================================================================================

def _sdk_activity_timeout():
    """Temporal 活动 start_to_close 到点的**真形态**：SDK 抛 temporalio.exceptions.
    TimeoutError（带 type=START_TO_CLOSE）；ActivityError 是「活动失败」另一族，不承载
    超时——本构造照 SDK 签名，判据只认类型不认文案。"""
    from temporalio.exceptions import TimeoutError as ActivityTimeoutError, TimeoutType
    return ActivityTimeoutError("activity task timed out", type=TimeoutType.START_TO_CLOSE,
                                last_heartbeat_details=[])


def _activity_error_wrapping(cause):
    """包装层形态：ActivityError 的因果链上挂超时（判据要穿透包装，不能只看最外层）。"""
    from temporalio.exceptions import ActivityError
    err = ActivityError("activity failed", scheduled_event_id=1, started_event_id=2,
                        identity="worker", activity_type="run_inspection_suite",
                        activity_id="7", retry_state=None)
    err.__cause__ = cause
    return err


def test_timeout_is_named_and_distinct_from_generic_failure():
    """必做④：超时与一般故障两态可辨且都具名——超时 ⇒ suite_timeout=True + error
    点名「套件段超时：SUITE_TO=<n>s 内未返回」；一般故障 ⇒ suite_timeout=False +
    error 点名异常类型。判据只认类型不认文案（文案随 SDK 版本漂移）。"""
    to = _sdk_activity_timeout()
    assert flow.is_activity_timeout_error(to) is True
    assert flow.is_activity_timeout_error(asyncio.TimeoutError()) is True
    assert flow.is_activity_timeout_error(_activity_error_wrapping(to)) is True
    assert flow.is_activity_timeout_error(RuntimeError("boom")) is False
    assert flow.is_activity_timeout_error(ValueError("timeout")) is False  # 文案不算判据
    assert flow.is_activity_timeout_error(
        _activity_error_wrapping(RuntimeError("boom"))) is False           # 穿透后仍不是超时

    r_to = flow.suite_failure_receipt(to, 10800)
    assert r_to["suite_timeout"] is True
    assert r_to["suite_timeout_sec"] == 10800.0
    assert "套件段超时" in r_to["error"] and "10800" in r_to["error"]
    assert "不代表套件结果" in r_to["error"]
    assert (r_to["ran"], r_to["passed"], r_to["failed"], r_to["env_fail"]) == (0, 0, 0, 0)

    r_gen = flow.suite_failure_receipt(RuntimeError("boom"), 10800)
    assert r_gen["suite_timeout"] is False and r_gen["suite_timeout_sec"] == 0.0
    assert "RuntimeError" in r_gen["error"] and "套件段超时" not in r_gen["error"]
    # 两态进发现清单都是 high「套件未跑成」，但**读得出是哪一态**（error 点名）
    for r in (r_to, r_gen):
        fs = deadman.suite_findings(r)
        assert fs and fs[0]["severity"] == "high" and fs[0]["suggest"] is False
    sec_to = deadman.suite_section(r_to)
    assert sec_to["suite_timeout"] is True and sec_to["ok"] is False
    assert "suite_timeout" not in deadman.suite_section(r_gen)


def test_workflow_suite_branch_names_timeout_and_grates_teardown():
    """源码面锁（工作流侧接线）：超时分支经 suite_failure_receipt 具名、拆泳道前有宽限
    sleep、活动 args 三笔预算在下单面上（run/supply/suite_timeout）——四者任缺即红。"""
    import inspect as _inspect
    src = _inspect.getsource(flow.InspectionPeriodicWorkflow._run_suite)
    assert "suite_failure_receipt(e, SUITE_TO.total_seconds())" in src
    assert '"run_budget_sec"' in src and '"supply_timeout_sec"' in src \
        and '"suite_timeout_sec"' in src
    assert "start_to_close_timeout=SUITE_TO" in src
    # 超时后的宽限 sleep 在 **if run_suite: 守卫内**的调用点（不在 _run_suite 里——
    # 拆泳道发生在 _run_suite 之后，宽限必须卡在「跑完 → 拆」之间）
    insp = _inspect.getsource(
        flow.InspectionPeriodicWorkflow._run_inspect_period_flow)
    assert 'if suite_section.get("suite_timeout"):' in insp
    assert "workflow.sleep(SUITE_TIMEOUT_TEARDOWN_GRACE)" in insp
    assert "SUITE_TIMEOUT_TEARDOWN_GRACE" in insp
    # 宽限窗必须**远小于**活动超时（不把预算吃进拆泳道），且拆泳道仍留在守卫块内
    assert 0 < flow.SUITE_TIMEOUT_TEARDOWN_GRACE.total_seconds() <= 300
    assert flow.SUITE_TIMEOUT_TEARDOWN_GRACE.total_seconds() \
        < flow.SUITE_TO.total_seconds() / 10


def test_object_new_workflow_stub_never_crashes_on_timeout():
    """object.__new__ 桩态（signal handler 直调同款手法）也走得通异常分类：
    活动调用抛超时 → 回执具名，绝不把期票搞崩（业务拒绝不 raise 的既有纪律）。"""
    wf = object.__new__(flow.InspectionPeriodicWorkflow)
    assert wf is not None
    receipt = flow.suite_failure_receipt(_sdk_activity_timeout(), 10800)
    assert receipt["suite_timeout"] is True
    assert json.dumps(receipt, ensure_ascii=False)  # 可序列化（回执要落盘/上票面）
