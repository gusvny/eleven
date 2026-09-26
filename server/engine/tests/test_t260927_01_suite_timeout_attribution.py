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
import re
import sys
import sys as _sys

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
    budget_findings = [f for f in findings
                       if "budget exhausted" in str(f.get("subject", "")).lower()]
    assert len(budget_findings) == 1, [f.get("subject") for f in findings]
    f = budget_findings[0]
    assert f["severity"] == "high"
    assert f["suggest"] is False          # 容量/预算面，开「修码票」是错配
    assert "unrun batch list" in f["evidence"] and "b-scenario" in f["evidence"]
    assert "NOT a product red" in f["evidence"]
    # 票面段（face["suite"]）透出预算块与两笔分相墙钟（缺键不乱造）
    section = deadman.suite_section(receipt)
    assert section["budget"]["unrun_count"] == 318
    assert section["error"] == ""
    assert deadman.suite_green(section) is False     # 没跑完=不绿（红线：不得以截断换绿）
    # 反向自证：没有 budget 键的旧回执**零新键**（老路径逐字节不变）
    old = {k: v for k, v in receipt.items() if k != "budget"}
    assert "budget" not in deadman.suite_section(old)
    assert not [x for x in deadman.suite_findings(old)
                if "budget exhausted" in str(x.get("subject")).lower()]


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


def test_suite_activity_end_to_end_writes_receipt_with_budget_plan(tmp_path, monkeypatch):
    """端到端（真活动函数 + 假 admin 子进程）：`run_inspection_suite` **必须**写得出回执，
    且回执带 budget_plan 四层数字 + 代码身份（worker_module_mtime）。

    这条锁是被**活体自查找出的两个真 bug** 立的（单测此前只覆盖 `_run_scenarios`）：
      ①`budget_plan` 引用了 `_run_scenarios` 的局部变量 → NameError，回执缺整个计划面；
      ②回执落盘把 `now_fn` 传成 None → 'NoneType' object is not callable，**回执整份写不出**
        （每轮巡检都丢权威件）。两者都只在真活动路径现形。
    """
    import asyncio
    import inspect as _inspect
    lane = tmp_path / "lane"
    (lane / "server").mkdir(parents=True)
    monkeypatch.setenv("SANDBAR_INSPECTION_DIR", str(tmp_path / "out"))

    class _Proc:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def _fake_create(*argv, **kw):
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)
    out = asyncio.run(aa.run_inspection_suite({
        "ticket_id": "t260927-01", "worktree": str(lane),
        "instance_id": "integration-tests", "period": "20260928", "base_ref": "abc",
        "run_budget_sec": flow.SUITE_RUN_BUDGET_SEC,
        "supply_timeout_sec": flow.INTEG_SUPPLY_TO_SEC,
        "suite_timeout_sec": flow.SUITE_TO.total_seconds()}))
    r = out["result"]
    assert out["ok"] is True
    assert not r.get("receipt_error"), r.get("receipt_error")     # 落盘不失败（bug②）
    assert r.get("report_path"), "权威回执没落盘"
    doc = json.loads(open(r["report_path"], encoding="utf-8").read())
    plan = doc.get("budget_plan") or {}
    assert not plan.get("error"), plan                            # 计划面无异常（bug①）
    assert plan["exec_timeout_sec"] == int(aa.inspect_integ_exec_timeout_sec())
    assert plan["runner_cutoff_sec"] == int(aa.inspection_runner_cutoff(
        aa.inspect_integ_exec_timeout_sec(), flow.SUITE_RUN_BUDGET_SEC))
    assert plan["supply_timeout_sec"] == int(flow.INTEG_SUPPLY_TO_SEC)
    assert plan["chain_timeout_sec"] == int(aa.inspection_chain_timeout(
        aa.inspect_integ_exec_timeout_sec(), flow.INTEG_SUPPLY_TO_SEC))
    assert plan["suite_to_sec"] == int(flow.SUITE_TO.total_seconds())
    assert plan["worker_module_mtime"], "代码身份证人缺席（未重启 worker 时无从判版本）"
    assert doc["chain_gate_sec"] == plan["chain_timeout_sec"]
    # 落盘必须显式传可调用 now_fn（不许 None——那是让整份回执写不出的形态）
    src = _inspect.getsource(aa.run_inspection_suite)
    assert "INSPECTION_DIR, time.time, " in src


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
    # 进度件 env：三方（闸 / 引擎 / 执行器）同一串——路径不一致=读不到已完成面
    assert vl.PROGRESS_ENV == aa.SANDBAR_INTEG_PROGRESS_ENV == rs.PROGRESS_ENV, \
        (vl.PROGRESS_ENV, aa.SANDBAR_INTEG_PROGRESS_ENV, rs.PROGRESS_ENV)
    # 预算解析纯函数：缺省/畸形/非正 → 0（不启用），正数原样
    assert rs.parse_run_budget(None) == 0.0
    assert rs.parse_run_budget("") == 0.0
    assert rs.parse_run_budget("abc") == 0.0
    assert rs.parse_run_budget("0") == 0.0
    assert rs.parse_run_budget("-5") == 0.0
    assert rs.parse_run_budget("5400") == 5400.0



# ========================================================================================
# ①b 执行器专属墙（260927 第二刀，宿主实测校准）
# ========================================================================================

def test_inspection_exec_timeout_is_derived_and_bounded():
    """宿主实测（t260928-01：`场景执行器整体超时（>3000s）` wall=3003.3s）→ 巡检链要有
    **专属执行器墙**：缺省 ≥5400（实测 2630s 的 2× 量级）、自成一档、且与既有预算成对：
      BATCH_TIMEOUT_SEC(3000) ≤ 执行器超时(6000) < 跑者总预算(6600) < SUITE_TO(10800)
    另两条（跑者自收口早于执行器墙 / 链不越活动超时）也必须成立——否则「点名收口」
    又变回「硬杀」。
    """
    exec_to = aa.inspect_integ_exec_timeout_sec()
    cutoff = aa.inspection_runner_cutoff(exec_to, flow.SUITE_RUN_BUDGET_SEC)
    chain = aa.inspection_chain_timeout(exec_to, flow.INTEG_SUPPLY_TO_SEC)
    suite_to = flow.SUITE_TO.total_seconds()
    assert aa.BATCH_TIMEOUT_SEC <= exec_to, (aa.BATCH_TIMEOUT_SEC, exec_to)
    assert exec_to >= 5400, exec_to                                  # 宿主下限
    assert exec_to < flow.SUITE_RUN_BUDGET_SEC < suite_to, \
        (exec_to, flow.SUITE_RUN_BUDGET_SEC, suite_to)
    assert cutoff < exec_to, (cutoff, exec_to)                       # 跑者先自行收口，再被墙兜底
    assert cutoff >= 5400, cutoff                                    # 跑者实得墙钟不缩水
    assert chain < suite_to, (chain, suite_to)                       # 链不越活动超时
    assert cutoff <= flow.SUITE_RUN_BUDGET_SEC                       # 收口点不超活动级预算
    # 每票集测段（缺省 0）：链截止逐字回落内层守卫
    assert aa._inspection_gate_timeout(0.0, 0.0) == float(aa.INTEG_GUARD_SEC)


def test_inspection_exec_timeout_env_and_chain_clamp(monkeypatch):
    """env 可覆盖执行器墙（运维契约面；畸形/非正/空白回落缺省=不静默猜 0）；活动侧链截止
    被活动超时 SUITE_TO 夹紧（env 抬过头也不许越过硬上界）。"""
    import inspect as _inspect
    assert aa.INSPECT_INTEG_EXEC_TIMEOUT_ENV == "SANDBAR_INSPECT_INTEG_EXEC_TIMEOUT_SEC"
    assert aa.INSPECT_INTEG_EXEC_TIMEOUT_DEFAULT_SEC >= 5400
    monkeypatch.delenv(aa.INSPECT_INTEG_EXEC_TIMEOUT_ENV, raising=False)
    assert aa.inspect_integ_exec_timeout_sec() == aa.INSPECT_INTEG_EXEC_TIMEOUT_DEFAULT_SEC
    monkeypatch.setenv(aa.INSPECT_INTEG_EXEC_TIMEOUT_ENV, "7200")
    assert aa.inspect_integ_exec_timeout_sec() == 7200.0
    for bad in ("abc", "0", "-9", "   "):
        monkeypatch.setenv(aa.INSPECT_INTEG_EXEC_TIMEOUT_ENV, bad)
        assert aa.inspect_integ_exec_timeout_sec() == \
            aa.INSPECT_INTEG_EXEC_TIMEOUT_DEFAULT_SEC, bad   # 畸形不静默猜 0
    monkeypatch.delenv(aa.INSPECT_INTEG_EXEC_TIMEOUT_ENV, raising=False)
    # 链夹紧：env 把执行器墙抬到活动超时之上时，链截止仍 ≤ SUITE_TO
    body = _inspect.getsource(aa._run_scenarios)
    assert "_chain_to = min(_chain_to" in body, "链截止未被 SUITE_TO 夹紧=env 抬过头就硬杀"


def test_payload_carries_exec_wall_cutoff_and_progress(tmp_path, monkeypatch):
    """接线锁（端到端缝，假 admin.py 回显下单面）：巡检轮把**执行器墙**放进
    `integ_timeout_sec` 载荷、把**跑者收口点**与**进度件路径**放进 env；每票集测段
    逐字回落旧值（payload=BATCH_TIMEOUT_SEC、无预算/进度 env）。"""
    import asyncio
    lane = tmp_path / "lane"
    (lane / "server").mkdir(parents=True)
    seen = {}

    class _Proc:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def _fake_create(*argv, **kw):
        seen["payload"] = json.loads(argv[-1])
        seen["env"] = {k: v for k, v in (kw.get("env") or {}).items()
                       if k.startswith("SANDBAR_INTEG") or k.startswith("SANDBAR_SUPPLY")}
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)
    asyncio.run(aa._run_scenarios(lane, "t260927-01", ledger_source="inspection",
                                  run_budget_sec=flow.SUITE_RUN_BUDGET_SEC,
                                  supply_timeout_sec=flow.INTEG_SUPPLY_TO_SEC))
    exec_to = aa.inspect_integ_exec_timeout_sec()
    assert seen["payload"]["integ_timeout_sec"] == int(exec_to)
    assert int(seen["env"]["SANDBAR_INTEG_RUN_BUDGET_SEC"]) == \
        int(aa.inspection_runner_cutoff(exec_to, flow.SUITE_RUN_BUDGET_SEC))
    assert seen["env"][aa.SANDBAR_INTEG_PROGRESS_ENV].endswith("integ-progress.json")
    assert int(seen["env"]["SANDBAR_SUPPLY_TIMEOUT_SEC"]) == int(flow.INTEG_SUPPLY_TO_SEC)
    seen.clear()
    asyncio.run(aa._run_scenarios(lane, "t260927-01", ledger_source="lane:t260927-01"))
    assert seen["payload"]["integ_timeout_sec"] == aa.BATCH_TIMEOUT_SEC
    assert "SANDBAR_INTEG_RUN_BUDGET_SEC" not in seen["env"]
    assert aa.SANDBAR_INTEG_PROGRESS_ENV not in seen["env"]


def test_interrupted_and_unproduced_are_named_separately(tmp_path):
    """宿主要求②：执行器被打断的两态**分开点名**（禁止裸 ran=0）——
    ①「已跑 N 条但无汇总」（进度件可读）；②「未产出任何结果」。
    两态在「验道读点 / 回执 / 发现清单 / 票面段」四处都可辨。"""
    import inspect as _inspect
    import verify_lane as vl
    prog = str(tmp_path / "integ-progress.json")
    with open(prog, "w", encoding="utf-8") as fh:
        json.dump({"ran": 12, "pass": 10, "fail": 2, "env_fail": 0,
                   "last": "t260927-x", "done": ["s%d" % i for i in range(12)]}, fh)
    got = vl._read_runner_progress(prog)
    assert got["ran"] == 12 and got["last"] == "t260927-x"
    # 缺失/畸形/零条目 → {}（=「未产出任何结果」，绝不伪造 ran=0 把被打断说成 0 场景）
    assert vl._read_runner_progress("") == {}
    assert vl._read_runner_progress(str(tmp_path / "nope.json")) == {}
    with open(prog, "w", encoding="utf-8") as fh:
        fh.write("{half json")
    assert vl._read_runner_progress(prog) == {}
    with open(prog, "w", encoding="utf-8") as fh:
        json.dump({"ran": 0, "done": []}, fh)
    assert vl._read_runner_progress(prog) == {}
    # 发现清单两态
    f_int = deadman.suite_findings({"error": "场景执行器整体超时（>6000s）：已跑 12 条但无汇总",
                                    "ran": 12, "passed": 10, "failed": 2, "env_fail": 0,
                                    "interrupted": True,
                                    "progress": {"last": "t260927-x", "path": "/x/prog.json"},
                                    "details": []})
    subj_int = [str(f["subject"]) for f in f_int]
    assert any("interrupted" in s.lower() and "12" in s for s in subj_int), subj_int
    assert not any("did not run to completion" in s for s in subj_int), subj_int
    f_bare = deadman.suite_findings({"error": "verify_lane integ 无有效输出（exit=1）",
                                     "ran": 0, "details": []})
    subj_bare = [str(f["subject"]) for f in f_bare]
    assert any("did not run to completion" in s for s in subj_bare), subj_bare
    assert not any("interrupted" in s.lower() for s in subj_bare), subj_bare
    # 票面段带 interrupted/progress（可下钻）
    sec = deadman.suite_section({"error": "x", "ran": 12, "interrupted": True,
                                 "progress": {"last": "t260927-x"}})
    assert sec["interrupted"] is True and sec["progress"]["last"] == "t260927-x"
    # 活动侧：验道 err 路径也把已完成面带上（不再把 ran 丢成 0）
    src = _inspect.getsource(aa._run_scenarios)
    assert "out_err = IntegrationRunResult(warnings=list(_warnings), error=_err, ran=_n" in src
    assert "interrupted=True" in src
    assert "read_integ_progress" in src


# ========================================================================================
# ①c 宿主追加三项：超时部分输出 / 混版本接缝 WARN / budget_env 可见 + 报告英文面
# ========================================================================================

def test_executor_timeout_keeps_partial_output_and_reaps_group(tmp_path, monkeypatch):
    """1①（宿主 finding①）：执行器超时**必须**取回部分输出并解析已完成的规范行/
    `INTEG_BUDGET` 标记（`partial=true` + `runner_used_sec` 点名），且用 Popen+进程组
    回收（裸 kill 会漏孙进程）。两态（有进度 / 无进度）分开点名。"""
    import inspect as _inspect
    import subprocess as _sp
    import verify_lane as vl
    lane = tmp_path / "lane"
    lane.mkdir()
    (lane / "verify.yaml").write_text(
        "schema: v1\nlanes:\n  code:\n    write_allow:\n      - src/\n"
        "integration:\n  cmd: sleep 30\n", "utf-8")
    src = _inspect.getsource(vl._integ)
    assert "subprocess.Popen(" in src, "执行器未走 Popen=超时拿不到部分输出"
    assert "os.killpg(os.getpgid(proc.pid)" in src, "超时未按进程组回收（孙进程会漏）"
    assert "partial" in src and "stdout_tail" in src
    # 态①：进度件有内容 → ran=N + interrupted/partial 双键 + runner_used_sec 在场
    prog = lane / "out" / "integ-progress.json"
    prog.parent.mkdir(parents=True, exist_ok=True)
    prog.write_text(json.dumps({"ran": 7, "pass": 6, "fail": 1, "env_fail": 0,
                                "last": "sc-7", "done": ["x"] * 7}), "utf-8")
    monkeypatch.setenv(vl.PROGRESS_ENV, str(prog))
    r1 = vl._integ({"lane": "integ", "path": str(lane), "integ_timeout_sec": 2})
    assert r1["interrupted"] is True and r1["partial"] is True
    assert r1["ran"] == 7 and r1["pass"] == 6 and r1["fail"] == 1
    assert isinstance(r1["runner_used_sec"], float) and r1["runner_used_sec"] >= 0
    assert "ran but there is no summary" in r1["err"] and r1["progress"]["last"] == "sc-7"
    assert r1["green"] is False
    # 态②：进度件缺席/零条目 → 「未产出任何场景结果」（真零），ran=0 且**点名不是绿**
    prog.unlink()
    r2 = vl._integ({"lane": "integ", "path": str(lane), "integ_timeout_sec": 2})
    assert r2["ran"] == 0 and r2["interrupted"] is True
    assert "no scenario results at all" in r2["err"] and 'NOT "0 scenarios green"' in r2["err"]
    # 部分输出里已完成的规范行也要进回执（stdout_tail + scenarios）
    assert "stdout_tail" in r2 and "scenarios" in r2


def test_mixed_version_seam_warns_and_never_pretends(tmp_path, monkeypatch):
    """1②（宿主 finding②）：巡检形态（台账来源=inspection）却**两个预算面都缺**时，
    闸侧必须落**显式 WARN 进回执**（`warnings`），不静默回落 3000 硬杀；
    worker 侧选中**不认预算键的泳道旧副本**时同样响亮 WARN（不假装认得）。"""
    import verify_lane as vl
    lane = tmp_path / "lane"
    lane.mkdir()
    (lane / "verify.yaml").write_text(
        "schema: v1\nlanes:\n  code:\n    write_allow:\n      - src/\n"
        "integration:\n  cmd: true\n", "utf-8")
    monkeypatch.setenv("SANDBAR_INTEG_LEDGER_SOURCE", "inspection")
    monkeypatch.delenv(vl.INTEG_TIMEOUT_ENV, raising=False)
    monkeypatch.delenv("SANDBAR_INTEG_RUN_BUDGET_SEC", raising=False)
    r = vl._integ({"lane": "integ", "path": str(lane)})      # 巡检形态 + 无任何预算面
    assert r.get("warnings"), "混版本接缝没有 WARN（静默回落 3000 会再演 t260928-01）"
    assert "mixed-version seam" in r["warnings"][0]
    # 给了执行器墙（或预算 env）→ 不再是混版本，WARN 不出现
    r2 = vl._integ({"lane": "integ", "path": str(lane), "integ_timeout_sec": 60})
    assert not r2.get("warnings")
    monkeypatch.setenv("SANDBAR_INTEG_RUN_BUDGET_SEC", "600")
    r3 = vl._integ({"lane": "integ", "path": str(lane)})
    assert not r3.get("warnings")
    monkeypatch.delenv("SANDBAR_INTEG_RUN_BUDGET_SEC", raising=False)
    # 非巡检形态（每票集测）零 WARN——缺省语义逐字不变
    monkeypatch.setenv("SANDBAR_INTEG_LEDGER_SOURCE", "lane:t260927-01")
    assert not vl._integ({"lane": "integ", "path": str(lane)}).get("warnings")
    # worker 侧：泳道旧副本不认预算键 → WARN（不假装认得）
    stale_lane = tmp_path / "stale"
    (stale_lane / "server" / "tools").mkdir(parents=True)
    (stale_lane / "server" / "admin.py").write_text("# stub", "utf-8")
    (stale_lane / "server" / "tools" / "verify_lane.py").write_text(
        "# pre-fix copy: no budget awareness\n", "utf-8")
    assert aa.lane_verify_lane_stale(stale_lane, stale_lane / "server" / "admin.py") is True
    # 新副本（含标记）→ 不判陈旧（不制造假 WARN）
    (stale_lane / "server" / "tools" / "verify_lane.py").write_text(
        "PROGRESS_ENV = 'x'\ndef _parse_budget_signal(s): return {}\n"
        "SANDBAR_INTEG_RUN_BUDGET_SEC = 'y'\n", "utf-8")
    assert aa.lane_verify_lane_stale(stale_lane, stale_lane / "server" / "admin.py") is False


def test_budget_env_visibility_is_additive(tmp_path, monkeypatch):
    """1③（宿主 finding③）：`INTEG_SUMMARY` 带 additive 键 `budget_env=present|absent`
    ——「env 缺席静默不启用」这条混版本难查的根，现在一行可判；缺省语义不变。"""
    class _Proc:
        returncode = 0

        async def communicate(self):
            return b"", b""

    seen = {}

    class _P:
        returncode = 0

        def __init__(self, out):
            self.stdout = out
            self.returncode = 0

    src = open(os.path.join(os.path.abspath(RUNNER_DIR), "run_scenarios.py"),
               encoding="utf-8").read()
    assert 'budget_env": "present" if run_budget > 0 else "absent"' in src
    assert src.count('"budget_env"') >= 2      # 正常汇总 + 预算耗尽收口面同键

    import asyncio
    lane = tmp_path / "lane"
    (lane / "server").mkdir(parents=True)

    async def _fake_create(*argv, **kw):
        seen["env"] = kw.get("env") or {}
        return _Proc()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)
    asyncio.run(aa._run_scenarios(lane, "t260927-01", ledger_source="inspection",
                                  run_budget_sec=flow.SUITE_RUN_BUDGET_SEC,
                                  supply_timeout_sec=flow.INTEG_SUPPLY_TO_SEC))
    assert seen["env"]["SANDBAR_INTEG_RUN_BUDGET_SEC"]           # present 形态
    # 真实执行器跑一轮，读回 INTEG_SUMMARY 的 budget_env
    import subprocess as _sp
    repo_root = os.path.dirname(os.path.abspath(RUNNER_DIR))     # <repo>（integration/ 的父目录）
    out = _sp.run([_sys.executable, "-B", "integration/run_scenarios.py",
                   "--only", "t260924-05-inspection-suite-ran-parity"],
                  cwd=repo_root,
                  capture_output=True, text=True, timeout=300,
                  env=dict(os.environ, SANDBAR_INTEG_ALLOW_CONCURRENT="1")).stdout
    summ = [ln for ln in out.splitlines() if ln.startswith("INTEG_SUMMARY ")]
    assert summ, out[-800:]
    assert json.loads(summ[0][len("INTEG_SUMMARY "):])["budget_env"] == "absent"


def test_report_text_is_english_and_prompt_requires_english():
    """(2) 宿主令「report 用英语写」：引擎自产的**发现面**文案（标题/证据/建议）为英文；
    inspect 段 prompt 明确要求 subject/why/suggestion 用英文且**数据不译**。
    锚点=行为（真调纯函数读文本），不是源码抄写。"""
    import re as _re
    import inspection_inspect as ins
    han = _re.compile(r"[\u4e00-\u9fff]")
    cases = [
        # 260927 收尾：ran=0 那条原先的中文豁免已随宿主改锚同批英文化（今无豁免）
        deadman.suite_findings({"error": "", "ran": 0, "details": []}),
        deadman.suite_findings({"ran": 2, "failed": 2,
                                "details": [{"name": "a", "exit": 1},
                                            {"name": "b", "exit": 1}]}),
        deadman.suite_findings({"ran": 1, "env_fail": 1,
                                "details": [{"name": "a", "exit": 2}]}),
        deadman.suite_findings({"ran": 1, "interrupted": True,
                                "progress": {"last": "x"}, "details": []}),
        deadman.suite_findings({"ran": 1, "late": True, "late_error": "orphan",
                                "details": []}),
        deadman.suite_findings({"ran": 1, "details": [],
                                "budget": {"exhausted": True, "unrun_count": 2,
                                           "unrun": ["a", "b"]}}),
        deadman.suite_findings("junk"),
        deadman.deadman_findings(["20260901"], "inst", "0 7 * * *", 7),
        deadman.skip_findings(2, 1, {"workflow": "old"}, []),
        deadman.skip_findings(None, None, {"workflow": "old"}, ["20260901"]),
    ]
    for fs in cases:
        for f in fs:
            for k in ("subject", "evidence", "suggestion"):
                assert not han.search(str(f.get(k) or "")), \
                    "报告制品含中文（宿主令：report 用英语写）：%r=%r" % (k, f.get(k))
    # 豁免集**已空**（260927 收尾：原 ran=0 中文 subject 已英文化，场景锚同批改；
    # 此处一旦再冒中文即红——不许悄悄长回豁免）
    han2 = _re.compile(r"[\u4e00-\u9fff]")
    leftovers = [f for f in deadman.suite_findings({"error": "", "ran": 0, "details": []})
                 if han2.search(str(f.get("subject") or ""))]
    assert leftovers == [], [f.get("subject") for f in leftovers]
    # prompt 侧：英文要求在场，且「数据不译」显式
    p = ins.build_inspect_prompt("i", "20260927", "test", "/tmp/base", "abc", 10)
    assert "in English" in p and "verbatim" in p
    assert "输出契约" in p                       # 既有契约块仍在（只加不减）


# ========================================================================================
# ④ 报告面零 CJK 守门（宿主令 260927 收尾：报告用英文写）
# ========================================================================================

#: 数据字段白名单（这些键的值是**数据**：引文/路径/命令原文/标识符——不译，允许任意语言）。
#: 判据只允许放这些键，键名写死=扩白名单必须显式改代码（不许静默放宽）。
REPORT_DATA_KEYS = frozenset({
    "evidence", "quote", "path", "cmd", "command", "output_tail", "stdout_tail",
    "instance_id", "period", "ticket_id", "report_path", "worktree", "base_ref",
    "baseline_ref", "id", "source_ticket", "verdict_note", "subject_data",
    "scan", "file", "suggest", "severity", "confidence", "who", "note_data",
    "arm", "kind", "why_data", "excerpt", "snippet", "match",
})


def _walk_report_strings(obj, key=None, path=""):
    """递归收集报告制品里的字符串值 → [(路径, 键, 值)]（白名单键除外）。"""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += _walk_report_strings(v, key=k, path="%s.%s" % (path, k))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out += _walk_report_strings(v, key=key, path="%s[%d]" % (path, i))
    elif isinstance(obj, str):
        if key not in REPORT_DATA_KEYS:
            out.append((path, key, obj))
    return out


def _report_cjk(artifact, allow_keys=frozenset()):
    han = re.compile(r"[\u4e00-\u9fff]")
    return [(p_, k, v_) for (p_, k, v_) in _walk_report_strings(artifact)
            if k not in allow_keys and han.search(v_)]


def test_report_face_has_no_cjk_except_data_fields():
    """报告面零 CJK 守门：**所有会进报告制品/票面的引擎自产文案必须英文**。

    覆盖面（三件制品 + 票面）：
      ①发现清单（suite 全态 + 漏跑 + 跳火）；
      ②face（build_ticket_face：含 suite 段、开票建议 title/urgency、notes）；
      ③落账文档（`_ledger_doc` = face + stage/status/timeline）；
      ④套件回执（具名超时回执 + 落盘文档）。
    豁免**只有数据字段白名单**（quote/path/cmd/标识符等）——新增豁免必须改代码（可见）。
    """
    import inspection_flow as flow
    han = re.compile(r"[\u4e00-\u9fff]")
    receipt = {"ticket_id": "t260927-01", "ran": 2, "passed": 1, "failed": 1, "env_fail": 0,
               "error": "", "results": "missing intentionally",
               "details": [{"name": "sc-a", "exit": 1, "output_tail": "boom"}]}
    findings = []
    for r in ({"error": "boom", "ran": 0, "details": []},
              {"error": "", "ran": 0, "details": []},
              {"ran": 2, "passed": 0, "failed": 2,
               "details": [{"name": "a", "exit": 1}, {"name": "b", "exit": 1}]},
              {"ran": 1, "env_fail": 1, "details": [{"name": "a", "exit": 2}]},
              {"ran": 1, "interrupted": True, "progress": {"last": "x"}, "details": []},
              {"ran": 1, "late": True, "late_error": "orphan", "details": []},
              {"ran": 1, "details": [],
               "budget": {"exhausted": True, "unrun_count": 1, "unrun": ["a"]}},
              "junk", None, {"ran": "many"}):
        findings += deadman.suite_findings(r)
    findings += deadman.deadman_findings(["20260901", "20260902"], "inst", "0 7 * * *", 7)
    findings += deadman.skip_findings(2, 1, {"workflow": "old"}, [])
    findings += deadman.skip_findings(None, None, {"workflow": "old"}, ["20260901"])
    bad = _report_cjk(findings)
    assert bad == [], "发现清单含非数据中文：%r" % bad[:4]
    # ② face（含 suite 段与开票建议）
    section = deadman.suite_section(receipt)
    face = flow.build_ticket_face(
        "t260927-01", "integration-tests", "20260927",
        {"findings": [], "summary": {"high": 0, "med": 0, "low": 0}, "heartbeat": False,
         "meta": {"scope": {"scope_files": 3, "diff_error": "x", "ki_note": "y"}}},
        extra_findings=findings, suite=section)
    bad = _report_cjk(face, allow_keys=frozenset({"red_line_data"}))
    assert bad == [], "票面 face 含非数据中文：%r" % bad[:4]
    assert not han.search(flow.INSPECTION_RED_LINE), "红线文案未英文化"
    for s_ in [t["title"] for t in face["suggested_fix_tickets"]] + \
              [t["urgency"] for t in face["suggested_fix_tickets"]]:
        assert not han.search(s_), s_
    # ③ 落账文档（_ledger_doc：face + timeline）
    wf = object.__new__(flow.InspectionPeriodicWorkflow)
    wf.face = dict(face)
    wf.stage = "close"
    wf.stage_state = "done"
    wf.status = "closed"
    wf.timeline = [{"at": "2026-09-27T00:00:00+00:00", "stage": "suite", "state": "running",
                    "reason": "Running the full integration suite in the inspection lane "
                              "(lane base abc)"}]
    doc = wf._ledger_doc()
    bad = _report_cjk(doc)
    assert bad == [], "落账文档含非数据中文：%r" % bad[:4]
    # ④ 套件回执（具名超时/故障两态 + 落盘文档）
    for r_ in (flow.suite_failure_receipt(_sdk_activity_timeout(), 10800),
               flow.suite_failure_receipt(RuntimeError("boom"), 10800)):
        assert _report_cjk(r_) == [], _report_cjk(r_)[:3]


def test_report_face_cjk_gate_has_teeth():
    """守门自证（有牙齿）：白名单外的中文必须被抓到——不然「零 CJK」是空话。"""
    assert _report_cjk({"subject": "套件红：x"}) != []
    assert _report_cjk({"subject": "套件红：x"}, allow_keys=frozenset({"subject"})) == []
    assert _report_cjk({"evidence": "数据里的中文不译：引文/路径"}) == []      # 数据字段豁免
    assert _report_cjk({"urgency": "立即开票"}) != []
    assert _report_cjk({"a": {"b": ["中文"]}}) != []


def test_engine_reason_literals_are_english():
    """静态锁：`inspection_flow` 里进报告面的**实参文案**（`_enter`/`_blocked` 的 reason，
    即 ledger 的 `timeline[].reason` 与 `blocked_reason`）零 CJK——动态守门只能覆盖
    我构造得出的路径，本锁覆盖其余分支（含 blocked/produce 轨）。"""
    import ast as _ast
    import inspection_flow as flow
    han = re.compile(r"[\u4e00-\u9fff]")
    src = open(flow.__file__, encoding="utf-8").read()
    bad = []
    for node in _ast.walk(_ast.parse(src)):
        if isinstance(node, _ast.Call):
            nm = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if nm in ("_enter", "_blocked"):
                for arg in node.args:
                    for n in _ast.walk(arg):
                        if isinstance(n, _ast.Constant) and isinstance(n.value, str) \
                                and han.search(n.value):
                            bad.append((nm, n.lineno, n.value[:60]))
    assert bad == [], "报告面 reason 含中文：%r" % bad[:5]


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

    late_reason = aa._late_suite_receipt_reason(
        "/repo/.lane/inspection-x-20260927", 10.0, 6600.0, 10800.0)
    assert late_reason.startswith("Late orphan after activity timeout")
    orphan = {"ticket_id": "t260927-01", "ran": 0, "passed": 0, "failed": 0, "env_fail": 0,
              "error": late_reason}
    out = flow.write_inspection_suite_receipt_impl(
        inst, period, orphan, tmp_path, late_error=late_reason)
    assert out["late"] is True
    assert out["file"].endswith("-suite-late.json"), out["file"]
    assert canon.read_bytes() == before, "权威回执被迟到孤儿件覆盖（t260927-01 病根）"
    late_doc = json.loads((tmp_path / out["file"]).read_text(encoding="utf-8"))
    assert late_doc["late"] is True and late_doc["late_error"] == late_reason
    assert "does NOT represent the suite result" in late_doc["error"]
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
    assert any("late orphan" in s.lower() for s in subjects), subjects
    # 引擎自产的迟到原因必须是英文（报告制品面，宿主令 260927）——真调判据函数，不读夹具
    produced = aa._late_suite_receipt_reason(
        str(tmp_path / "gone-lane"), 10.0, 6600.0, 10800.0)
    assert produced.startswith("Late orphan after activity timeout")
    import re as _re
    assert not _re.search(r"[\u4e00-\u9fff]", produced), produced
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
    # 态①：泳道不在（teardown 已腾空）→ 迟到，点名「不代表套件结果」（英文报告制品）
    why = aa._late_suite_receipt_reason(str(tmp_path / "gone"), 10.0, budget, suite_to)
    assert "Late orphan after activity timeout" in why
    assert "does NOT represent the suite result" in why
    # 态②：泳道在但越过宽限窗（> 活动超时 + 收尾余量）→ 迟到
    why2 = aa._late_suite_receipt_reason(str(lane), grace + 1.0, budget, suite_to)
    assert "grace window" in why2 and "does NOT represent the suite result" in why2
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
    assert "Suite stage timed out" in r_to["error"] and "10800" in r_to["error"]
    assert "NOT a suite result" in r_to["error"]
    assert (r_to["ran"], r_to["passed"], r_to["failed"], r_to["env_fail"]) == (0, 0, 0, 0)

    r_gen = flow.suite_failure_receipt(RuntimeError("boom"), 10800)
    assert r_gen["suite_timeout"] is False and r_gen["suite_timeout_sec"] == 0.0
    assert "RuntimeError" in r_gen["error"] and "timed out:" not in r_gen["error"]
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
