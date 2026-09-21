"""t260917-08 单测：agent bash 沙箱不可用成为一等环境信号（env_fail），勿与阶段 status 混同。

覆盖口径（=create_plan v2 方案 UT-A..UT-J + review gen1 附条件 C1/C2 + 非阻塞 N1/N2/N3）：
  A. 默认值重放安全（老回执/在途实例缺新键零破坏——gate_refusal 带默认先例，t260915-01②）。
  B. normalize_handover_runs 全组合（absent/ok/malformed/超限/非串条目/空 cmd/dropped
     记名/空列表合法）+ 解析点透传（activity _read_result 行为断言；base/dev_lane
     归一点源码锁）。
  C. classify_env_block 矩阵（t260917-05 日志原话桩串 / KI-083 消息 / 负例 / 空 /
     乱码——岗位纪律：外部输入畸形用例用固定桩串复现，不靠真外部源）。
  D. _apply_env_signal 双源归因（自报优先/扫描补位/无信号零改动/读败不拦交付链）
     + 四路挂点源码锁（M1）+ N2 桩回执读回不丢信号 + N1 复用 _log_tail 源码锁。
  E. agent_env_failed_reason / env_note_for 文案矩阵（畸形不抛，R4 空清单不洗白）。
  F. dev_lane._agent_failed_why / _block_agent_failed 路由（_mk_wf 壳族先例，免
     Temporal）+ 源码锁（内联字面量恰 2 处、M3 冲突消解变体接线）。
  G. 移交命令债表行为断言（review C1 裁定①）：put/take/clear——产出命令→拾取→销账不
     重复执行；集测后段产出命令留债到下一轮集测；同段回执重写替换；本轮亲自完成验证
     →旧命令销账；env_fail 空清单不蒸发旧债；畸形债条容忍。
  H. run_handover_leg 三路全终态（过/败/超时 kill 排空——KI-009 同款纪律）+ 畸形
     命令不执行（fail-closed）+ 桩旋钮不漏进命令子进程（L4）+ 输出截断 + R3 dict
     重建点源码锁。
  I. 旋钮入族源码锁（三新旋钮∈TEST_STUB_ENV_KNOBS；命令/verify_lane 剥除面同源；
     命令超时=执行面容量参数非判定放宽）。
  J. 契约块与义务句在场（build_stage_prompt 行为断言 + FLOW_BRIEF['implement']/
     ['arbitrate'] C2 义务句源码锁 + 仲裁/走查上下文接线源码锁）。

UT 全程禁网络/真 Temporal/真 git（conftest 只加 sys.path）；H 的子进程命令只跑
python3 -c 短命令，cwd=tempfile 目录，超时路 kill+wait 排空（不留僵尸）。
运行：主树 venv `.../engine/.venv/bin/python -m pytest server/engine/tests/test_t260917_08_env_fail_signal.py -q`。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import agent_activities  # noqa: E402
import dev_lane  # noqa: E402
import shared  # noqa: E402
from shared import StageResult  # noqa: E402

PY = sys.executable

# t260917-05 implement agent 日志原话（工单正文逐字）——环境归因词表的实证锚。
T0505_LOG = ("被阻塞：bash 沙箱 sandbox_apply: Operation not permitted（三种模式均拒），"
             "pytest/node/场景/build 一行未跑")
# KI-083 实证形态（探针实测 exit 71 fail-closed）。
KI083_LOG = "dsh: no sandbox backend is usable（fail-closed，exit 71）"


# ---------- 壳（test_t260917_01 _mk_wf 族同款，免 Temporal） ----------

async def _wake_immediately(cond) -> None:
    return None


def _mk_wf(meta: dict | None = None):
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: pid == dev_lane.DETAIL_FACE_PATCH_ID,
        now=lambda: NOW_DT,
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None),
        wait_condition=_wake_immediately)
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = dict(meta or {})
    wf.timeline = []
    wf._gens = {}
    wf._retry_token = 1
    wf._rework = None
    wf.results = {}
    wf.ticket_id = "t-ut"
    wf._detail_face_on = True
    wf.engine_version = 2
    return wf


import datetime  # noqa: E402

NOW_DT = datetime.datetime(2026, 9, 17, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _src(name: str) -> str:
    return (POC / name).read_text(encoding="utf-8")


def _receipt(tmp: Path, body: dict) -> Path:
    p = tmp / "result.json"
    p.write_text(json.dumps(body, ensure_ascii=False), "utf-8")
    return p


# ---------- A. 默认值重放安全 ----------

def test_a1_stage_result_defaults_replay_safe():
    r = StageResult()
    assert r.env_fail is False
    assert r.env_reason == ""
    assert r.handover_runs == []
    assert r.handover_dropped == []


def test_a2_integration_run_defaults_replay_safe():
    ir = shared.IntegrationRunResult()
    assert (ir.handover_ran, ir.handover_passed, ir.handover_failed) == (0, 0, 0)
    args = shared.IntegrationRunArgs(ticket_id="t", worktree="w")
    assert args.handover_runs == []


def test_a3_named_collision_guard_doc_in_source():
    # M2：IntegrationRunResult.env_fail（int 计数，入闸）× StageResult.env_fail
    # （bool 位，不入闸）同名异型——互指防混读注记必须钉在 shared.py 源面。
    src = _src("shared.py")
    assert "同名异型" in src and "不入闸口径" in src


# ---------- B. normalize_handover_runs 全组合 + 解析点透传 ----------

def test_b1_absent_key_is_not_an_error():
    assert shared.normalize_handover_runs(None) == ([], "absent", [])


def test_b2_two_valid_legs_ok_shape():
    raw = [{"name": "ut", "cmd": "pytest -q"}, {"name": "sc", "cmd": "node x.mjs"}]
    legs, shape, dropped = shared.normalize_handover_runs(raw)
    assert shape == "ok" and dropped == []
    assert legs == [{"name": "ut", "cmd": "pytest -q"},
                    {"name": "sc", "cmd": "node x.mjs"}]


def test_b3_empty_list_is_legal_shape_not_malformed():
    # agent 显式声明「无可交接」=合法空（R4 语义层裁定当不当已验证，形状层不误标）
    assert shared.normalize_handover_runs([]) == ([], "ok", [])


def test_b4_non_list_is_malformed_named():
    for junk in ("pytest -q", 42, {"name": "a", "cmd": "b"}, 3.14):
        legs, shape, dropped = shared.normalize_handover_runs(junk)
        assert legs == [] and shape == "malformed"
        assert dropped == ["handover_runs 非列表"]


def test_b5_per_item_validation_named_drops_never_silent():
    raw = [
        "裸字符串",                                   # 条目0:非对象
        7,                                            # 条目1:非对象
        {},                                           # 条目2:name/cmd 缺失
        {"name": "only-name"},                        # 条目3:cmd 缺失
        {"name": "", "cmd": "c"},                     # 条目4:name 空
        {"name": "n", "cmd": "   "},                  # 条目5:cmd 空白
        {"name": "长" * 200, "cmd": "echo ok"},       # 条目6:name 超限→截断保留
        {"name": "n", "cmd": "rm -rf " + "x" * 600},  # 条目7:cmd 超限→整条丢弃不截断执行
    ]
    legs, shape, dropped = shared.normalize_handover_runs(raw)
    assert len(legs) == 1
    assert legs[0]["name"] == "长" * shared.HANDOVER_NAME_MAX      # 截断保留（名字无害）
    assert legs[0]["cmd"] == "echo ok"
    assert len(dropped) == 8                                        # 逐条记名，不静默丢
    # （条目0-5 与条目7 共 7 条整条丢弃 + 条目6 截断保留仍记名 1 条）
    assert any("条目7" in d and "不截断执行" in d for d in dropped)
    assert any("条目0" in d for d in dropped)


def test_b8_leg_cap_tail_dropped_named():
    raw = [{"name": "l%d" % i, "cmd": "echo %d" % i} for i in range(25)]
    legs, shape, dropped = shared.normalize_handover_runs(raw)
    assert shape == "ok" and len(legs) == shared.HANDOVER_MAX_LEGS
    assert len(dropped) == 5 and dropped[0].startswith("条目20")


def test_b9_whitespace_stripped():
    legs, shape, _ = shared.normalize_handover_runs(
        [{"name": "  a ", "cmd": " pytest -q "}])
    assert shape == "ok" and legs == [{"name": "a", "cmd": "pytest -q"}]


def test_b10_read_result_passthrough_parse_point1(tmp_path):
    p = _receipt(tmp_path, {
        "status": "ok", "summary": "s", "env_fail": True, "env_reason": "沙箱 deny",
        "handover_runs": [{"name": "a", "cmd": "c"}],
        "handover_dropped": ["条目9:cmd 超 500 字符整条丢弃（不截断执行）"]})
    res = agent_activities._read_result(p)
    assert res is not None
    assert res.env_fail is True and res.env_reason == "沙箱 deny"
    assert res.handover_runs == [{"name": "a", "cmd": "c"}]
    assert res.handover_dropped == ["条目9:cmd 超 500 字符整条丢弃（不截断执行）"]


def test_b11_read_result_old_receipt_zero_change(tmp_path):
    p = _receipt(tmp_path, {"status": "ok", "summary": "老回执无新键"})
    res = agent_activities._read_result(p)
    assert res is not None and res.env_fail is False
    assert res.handover_runs == [] and res.handover_dropped == []


def test_b12_parse_points_source_lock():
    base_src = _src("base.py")
    dev_src = _src("dev_lane.py")
    # 三解析点（base 归一化 / dev_lane 归一化 / activity _read_result 行为断言见 B10）
    assert 'normalize_handover_runs(raw.get("handover_runs"))' in base_src
    assert 'normalize_handover_runs(raw.get("handover_runs"))' in dev_src
    # 两处 results 台面 dict 均带 env_note 单源注记（票面可见不依赖日志）
    assert '"env_note"' in base_src and '"env_note"' in dev_src


# ---------- C. classify_env_block 矩阵 ----------

def test_c1_marker_hits_from_real_evidence():
    why = agent_activities.classify_env_block(T0505_LOG)
    assert "agent bash 沙箱不可用" in why and "sandbox_apply" in why
    why = agent_activities.classify_env_block(KI083_LOG)
    assert "agent bash 沙箱不可用" in why and "no sandbox backend is usable" in why
    # 大小写不敏感（spawn 输出大小写不定）
    assert agent_activities.classify_env_block("SANDBOX_UNAVAILABLE: no runner") != ""


def test_c2_negatives_zero_signal():
    for text in ("pytest 12 passed", "verdict=pass 全部通过",
                 "mkdir: Operation not permitted",   # 非沙箱词表内的杂音不误挂
                 ""):
        assert agent_activities.classify_env_block(text) == ""


def test_c3_malformed_never_raise():
    for junk in (None, 123, ["x"], {}, b"bytes"):
        assert agent_activities.classify_env_block(junk) == ""


# ---------- D. _apply_env_signal 双源归因 + 挂点/复用源码锁 ----------

def _log_with(tmp_path, text: str) -> str:
    p = tmp_path / "agent.log"
    p.write_text(text, "utf-8")
    return str(p)


def test_d1_self_report_priority_not_overwritten(tmp_path):
    res = StageResult(status="ok", env_fail=True, env_reason="agent 自报：bash 全拒")
    out = agent_activities._apply_env_signal(
        res, _log_with(tmp_path, T0505_LOG), "t-ut", "implement")
    assert out is res                                   # 原样保留（不改写自报）
    assert out.env_reason == "agent 自报：bash 全拒"


def test_d2_scan_fills_when_self_report_absent(tmp_path):
    res = StageResult(status="ok")
    out = agent_activities._apply_env_signal(
        res, _log_with(tmp_path, T0505_LOG), "t-ut", "implement")
    assert out.env_fail is True
    assert out.env_reason.startswith("[worker 归因] ")   # 与自报可分辨
    assert "sandbox_apply" in out.env_reason


def test_d3_no_signal_zero_change(tmp_path):
    r1 = agent_activities._apply_env_signal(
        StageResult(status="ok"), str(tmp_path / "missing.log"), "t-ut", "implement")
    assert r1.env_fail is False and r1.env_reason == ""
    r2 = agent_activities._apply_env_signal(
        StageResult(status="ok"), _log_with(tmp_path, "pytest 全绿"), "t-ut", "implement")
    assert r2.env_fail is False and r2.env_reason == ""


def test_d4_log_read_failure_never_blocks_delivery_chain(tmp_path):
    # 读败（日志路径是个目录）→ 跳过无信号，不硬造不抛（fail 方向=回退现状）
    res = StageResult(status="ok")
    out = agent_activities._apply_env_signal(res, str(tmp_path), "t-ut", "implement")
    assert out is res and out.env_fail is False


def test_d5_four_path_hooks_source_lock():
    # M1：挂点=幂等缓存+真 spawn 恰两处；stub 路径（旋钮直注）与 lane_dsh 预检
    # 拒绝路径有意不挂（拒绝证据含 sandbox 字样会污染归因，gate_refusal 已是真因）。
    # t260921-04：env 归位后同位再接集成禁跑执法归位（res = …; return _apply_…），
    # 本锁随挂点形态忠实更新，锁的意图不变：两代挂点都须双路在场，漂移必绊。
    src = _src("agent_activities.py")
    assert src.count("_apply_env_signal(") == 3          # def + 2 调用点
    assert src.count("_apply_integration_discipline(") == 3   # def + 2 调用点
    assert "res = _apply_env_signal(cached" in src
    assert "res = _apply_env_signal(res" in src
    assert "return _apply_integration_discipline(res, cwd, args)" in src
    assert "return _apply_env_signal(stub" not in src


def test_d6_stub_receipt_roundtrip_no_signal_loss_n2(tmp_path):
    # N2：桩回执六字段+新字段成套落盘 → 幂等缓存路径 _read_result 读回不丢信号。
    dropped_note = "条目3:cmd 超 500 字符整条丢弃（不截断执行）"
    p = _receipt(tmp_path, {
        "status": "ok", "summary": "[stub] x", "env_fail": True,
        "env_reason": "旋钮注入", "handover_runs": [{"name": "a", "cmd": "c"}],
        "handover_dropped": [dropped_note]})
    res = agent_activities._read_result(p)
    assert res.env_fail is True and res.env_reason == "旋钮注入"
    assert res.handover_runs == [{"name": "a", "cmd": "c"}]
    assert res.handover_dropped == [dropped_note]


def test_d7_classify_reads_via_existing__log_tail_n1():
    # N1：归类读日志复用既有 _log_tail 读取面（单字符面 20000 容量参数），不另造。
    src = _src("agent_activities.py")
    assert "_log_tail(log_file, 20000)" in src


# ---------- E. 文案矩阵（要求①② + R4） ----------

def test_e1_env_failed_reason_full_text():
    res = StageResult(status="failed", env_fail=True,
                      env_reason="sandbox_apply: Operation not permitted")
    why = shared.agent_env_failed_reason(res)
    assert "\n" not in why
    assert "agent 沙箱不可用（环境）" in why                    # 点名环境（要求②）
    assert "sandbox_apply" in why                              # 真因摘录在场
    assert "不停摆" in why and "retry_qc" in why and "rework" in why  # 后续出路
    assert "非实现缺位" in why                                  # 与实现缺位分开（要求①）


def test_e2_zero_change_for_non_env_or_non_failed():
    assert shared.agent_env_failed_reason(
        StageResult(status="ok", env_fail=True)) == ""         # ok+env_fail≠失败文案
    assert shared.agent_env_failed_reason(StageResult(status="failed")) == ""
    assert shared.agent_env_failed_reason(
        StageResult(status="failed", env_fail=False, env_reason="x")) == ""


def test_e3_malformed_never_raise_and_reason_missing_fallback():
    for junk in (None, 123, [], {}):
        assert shared.agent_env_failed_reason(junk) == ""
    duck = SimpleNamespace(status="failed", env_fail=True)      # 无 env_reason 属性
    why = shared.agent_env_failed_reason(duck)
    assert "agent 沙箱不可用（环境）" in why and "原因未声明" in why


def test_e4_env_note_single_source_matrix():
    legs = [{"name": "n%d" % i, "cmd": "c%d" % i} for i in range(4)]
    # 非 env_fail → 零注记零回归
    assert shared.env_note_for(StageResult(status="ok")) == ""
    # 有命令 → 交接语义 + 前 3 名
    note = shared.env_note_for(StageResult(status="ok", env_fail=True,
                                           handover_runs=legs[:2]))
    assert "移交 2 条命令待执行" in note and "n0" in note and "n1" in note and "等" not in note
    note = shared.env_note_for(StageResult(status="ok", env_fail=True,
                                           handover_runs=legs))
    assert "移交 4 条命令待执行" in note and note.endswith("等") and "n3" not in note
    # 空清单 → R4 fail-closed：不当已验证
    note = shared.env_note_for(StageResult(status="ok", env_fail=True))
    assert "未验证且无移交命令" in note and "不当作已验证" in note
    # 空清单 + 弃单 → 弃 N 条记名（M4 三面落面的单源措辞）
    note = shared.env_note_for(StageResult(
        status="ok", env_fail=True,
        handover_dropped=["条目0:非对象", "条目1:cmd 缺失", "条目2:非对象"]))
    assert "弃 3 条" in note and "条目0:非对象" in note and "条目2" not in note  # 只摘前 2


# ---------- F. dev_lane 路由 + 源码锁（要求②） ----------

def test_f1_env_failure_routed_to_env_text():
    wf = _mk_wf()
    res = StageResult(status="failed", summary="实现未完成",
                      env_fail=True, env_reason="沙箱三种模式均拒")
    why = wf._agent_failed_why(res)
    assert "agent 沙箱不可用（环境）" in why
    assert "沙箱三种模式均拒" in why and "不停摆" in why


def test_f2_legacy_text_preserved_verbatim_for_non_env():
    wf = _mk_wf()
    assert wf._agent_failed_why(
        StageResult(status="failed", summary="产品红原因")) == "agent 报失败：产品红原因"
    assert wf._agent_failed_why(StageResult(status="failed")) == "agent 报失败：failed"
    # default 参数（M3 冲突消解变体用）保持旧句式可注入
    assert wf._agent_failed_why(
        StageResult(status="failed"), default="agent 报失败：旧样") == "agent 报失败：旧样"


def test_f3_block_agent_failed_lands_blocked_with_env_text():
    wf = _mk_wf()
    res = StageResult(status="failed", env_fail=True, env_reason="沙箱 deny")
    asyncio.run(wf._block_agent_failed("implement", res))
    entries = [e for e in wf.timeline if e.get("state") == "blocked"]
    assert len(entries) == 1 and entries[0]["stage"] == "implement"
    assert "agent 沙箱不可用（环境）" in entries[0]["reason"]


def test_f4_source_locks_routing_sites_and_m3_variant():
    src = _src("dev_lane.py")
    # 内联「agent 报失败：%s」字面量恰 2 处（路由器缺省 + M3 变体缺省）——其余站
    # 全部改走单点路由，杜绝再有站漏挂 env 归因。
    assert src.count('"agent 报失败：%s"') == 2
    assert src.count("self._agent_failed_why(") == 5            # _block_agent_failed+3 站+M3
    assert 'await self._blocked("create_plan", self._agent_failed_why(res))' in src
    # M3：冲突消解变体一并路由——轮次前缀保留、后半路由（旧内联变体不得复辟）
    assert '"冲突消解第 %d 轮：%s"' in src
    assert '"冲突消解第 %d 轮 agent 报失败' not in src


# ---------- G. 移交命令债表（review C1 行为断言） ----------

LEGS_IMPL = [{"name": "impl-ut", "cmd": "python3 -c 'print(1)'"},
             {"name": "impl-lint", "cmd": "python3 integration/lint_tests.py"}]
LEGS_DESIGN = [{"name": "design-sc", "cmd": "python3 integration/t260917-08/sc_x.py"}]


def _env_res(**kw):
    base = dict(status="failed", env_fail=True)
    base.update(kw)
    return StageResult(**base)


def _names(legs) -> list:
    """债表条目={stage,name,cmd}（stage=来源段，防跨段误销）；断言投影到 name 序列。"""
    return [l["name"] for l in legs]


def test_g1_put_take_clear_no_double_execution():
    wf = _mk_wf()
    wf._handover_debt_put("implement", _env_res(handover_runs=LEGS_IMPL))
    assert [l["name"] for l in wf._handover_debt_legs()] == ["impl-ut", "impl-lint"]
    # 集测段拾取并真跑后销账 → 下一轮集测不再重复执行（C1 防重复执行）
    wf._handover_debt_clear()
    assert wf._handover_debt_legs() == []


def test_g2_post_integ_stage_debt_survives_to_next_integ_round():
    # C1 场景：集测之后的段（design_integration_tests）产出命令 → 留债可见 → rework 回
    # implement → 下一轮集测自然拾取（债在销账前恒在册）。
    wf = _mk_wf()
    wf._handover_debt_put("design_integration_tests",
                          _env_res(handover_runs=LEGS_DESIGN))
    assert _names(wf._handover_debt_legs()) == ["design-sc"]
    # 别段（implement）本轮亲自完成验证，不得误销 design 的债
    wf._handover_debt_put("implement", StageResult(status="ok"))
    assert _names(wf._handover_debt_legs()) == ["design-sc"]


def test_g3_same_stage_receipt_rewrite_replaces_not_accumulates():
    wf = _mk_wf()
    wf._handover_debt_put("implement", _env_res(handover_runs=LEGS_IMPL))
    newer = [{"name": "impl-new", "cmd": "echo new"}]
    wf._handover_debt_put("implement", _env_res(handover_runs=newer))
    assert _names(wf._handover_debt_legs()) == ["impl-new"]     # 同段替换，无跨代重复


def test_g4_own_verification_clears_own_stale_legs():
    # 本段重进且亲自跑完验证（无 env 信号）→ 本段旧命令销账：过期命令再代跑=失败命令误伤仲裁
    wf = _mk_wf()
    wf._handover_debt_put("implement", _env_res(handover_runs=LEGS_IMPL))
    wf._handover_debt_put("design_integration_tests",
                          _env_res(handover_runs=LEGS_DESIGN))
    wf._handover_debt_put("implement", StageResult(status="ok"))
    assert _names(wf._handover_debt_legs()) == ["design-sc"]
    assert any("销账" in str(e.get("note") or "") for e in wf.meta["log"])


def test_g5_env_fail_zero_legs_keeps_old_debt_visible():
    # R4：env_fail=true 且空清单=未验证——旧命令是唯一在册验证记录，清了=轨迹蒸发
    wf = _mk_wf()
    wf._handover_debt_put("implement", _env_res(handover_runs=LEGS_IMPL))
    wf._handover_debt_put("implement", _env_res(handover_runs=[]))
    assert _names(wf._handover_debt_legs()) == ["impl-ut", "impl-lint"]


def test_g6_junk_debt_entries_tolerated_never_crash():
    wf = _mk_wf()
    wf.meta["env_handover_pending"] = [
        "裸串", 42, {"stage": "implement"},                      # 无 cmd → 不入单
        {"stage": "implement", "name": "n", "cmd": "echo real"}]
    assert wf._handover_debt_legs() == [{"stage": "implement", "name": "n",
                                         "cmd": "echo real"}]
    # 债表带残条时 put 仍可用（畸形条目被替换面滤除）
    wf._handover_debt_put("implement", _env_res(handover_runs=LEGS_IMPL))
    assert [l["name"] for l in wf._handover_debt_legs()] == ["impl-ut", "impl-lint"]


def test_g7_integ_site_wired_to_debt_source_lock():
    src = _src("dev_lane.py")
    assert "handover_runs=self._handover_debt_legs()" in src     # 派单面=债表单源
    assert "self._handover_debt_clear()" in src                  # 真跑后销账
    assert "self._handover_debt_put(step_id, res)" in src        # 回执归一后入债


# ---------- H. run_handover_leg 三路全终态 + L4 + R3 ----------

def test_h1_pass_leg_exit_zero_tail_captured():
    r = asyncio.run(agent_activities.run_handover_leg(
        {"name": "ok-leg", "cmd": "%s -c \"print('hello-ut')\"" % PY},
        cwd=Path(tempfile.gettempdir())))
    assert r["exit"] == 0 and r["name"] == "ok-leg"
    assert "hello-ut" in r["output_tail"]


def test_h2_fail_leg_exit_nonzero_visible():
    r = asyncio.run(agent_activities.run_handover_leg(
        {"name": "red-leg", "cmd": "%s -c 'import sys; sys.exit(3)'" % PY},
        cwd=Path(tempfile.gettempdir())))
    assert r["exit"] == 3


def test_h3_timeout_killed_and_drained_no_zombie():
    r = asyncio.run(agent_activities.run_handover_leg(
        {"name": "slow-leg", "cmd": "%s -c 'import time; time.sleep(30)'" % PY},
        cwd=Path(tempfile.gettempdir()), timeout=1.0))
    assert r["exit"] not in (0, None)                           # 已被 kill（信号态）
    assert "超时" in r["output_tail"]


def test_h4_malformed_cmd_fails_as_command_not_refused():
    # 260920 改走 shell（宿主令「A」）：shell 语法错误不再「拒执行」，而是命令自己非零退出
    # ——记败交仲裁，仍 fail-closed（不猜着放过）；空命令仍不执行。
    r1 = asyncio.run(agent_activities.run_handover_leg(
        {"name": "bad", "cmd": "echo 'unbalanced"}, cwd=Path(tempfile.gettempdir())))
    assert r1["exit"] not in (0, None) and r1["output_tail"]     # shell 报的语法错在尾串里
    r2 = asyncio.run(agent_activities.run_handover_leg(
        {"name": "empty", "cmd": "   "}, cwd=Path(tempfile.gettempdir())))
    assert r2["exit"] is None and "为空" in r2["output_tail"]


def test_h6_env_prefixed_shell_command_runs_regression():
    # 实案 t260920-01 回归：环境变量前缀的 shell 命令必须能跑（旧实现把前缀当程序名 →
    # FileNotFoundError → 打死整段集测）。
    r = asyncio.run(agent_activities.run_handover_leg(
        {"name": "env-prefix",
         "cmd": "PYTHONPYCACHEPREFIX=/tmp/ut-pycache %s -c \"print('env-prefix-ok')\"" % PY},
        cwd=Path(tempfile.gettempdir())))
    assert r["exit"] == 0 and "env-prefix-ok" in r["output_tail"]


def test_h7_shell_metachars_and_pipeline_supported():
    r = asyncio.run(agent_activities.run_handover_leg(
        {"name": "meta", "cmd": "echo aa && echo bb | tr a-z A-Z"},
        cwd=Path(tempfile.gettempdir())))
    assert r["exit"] == 0 and "aa" in r["output_tail"] and "BB" in r["output_tail"]


def test_h8_timeout_reaped_by_process_group_no_orphan():
    # 进程组回收：shell 派生的孙进程也必须被收走（只 kill shell 会留孤儿）。
    r = asyncio.run(agent_activities.run_handover_leg(
        {"name": "slow-group", "cmd": "sleep 30 & sleep 30"},
        cwd=Path(tempfile.gettempdir()), timeout=1.0))
    assert r["exit"] not in (0, None)
    assert "超时" in r["output_tail"] and "进程组" in r["output_tail"]


def test_h9_one_bad_command_does_not_kill_the_batch():
    # 260920：单条起飞异常只记名失败，其余命令照跑（一条命令的毛病不得毁整段证据面）。
    class Boom:
        def __str__(self):
            raise RuntimeError("boom-str")
    res = asyncio.run(agent_activities.run_handover_legs(
        [{"name": "boom", "cmd": Boom()},
         {"name": "good", "cmd": "echo still-alive"}],
        cwd=Path(tempfile.gettempdir())))
    assert res["ran"] == 2 and res["passed"] == 1 and res["failed"] == 1
    boom = [d for d in res["details"] if "boom" in d["name"]][0]
    assert boom["exit"] == -1 and "起飞异常" in boom["output_tail"]
    good = [d for d in res["details"] if "good" in d["name"]][0]
    assert good["exit"] == 0 and "still-alive" in good["output_tail"]


def test_h5_stub_knobs_stripped_from_leg_subprocess_l4():
    # 桩旋钮不得漏进命令进程换假行为（R2/L4 机械面）；对照组普通变量正常透传。
    saved = {k: os.environ.get(k) for k in ("SANDBAR_AGENT_STUB",
                                            "SANDBAR_AGENT_STUB_ENV_FAIL",
                                            "SANDBAR_WATCH_INTERVAL_SEC",
                                            "SANDBAR_UT_CONTROL")}
    try:
        os.environ["SANDBAR_AGENT_STUB"] = "1"
        os.environ["SANDBAR_AGENT_STUB_ENV_FAIL"] = "1"
        os.environ["SANDBAR_WATCH_INTERVAL_SEC"] = "7"
        os.environ["SANDBAR_UT_CONTROL"] = "visible"
        probe = ("import os; print(os.environ.get('SANDBAR_AGENT_STUB','MISS'),"
                 "os.environ.get('SANDBAR_AGENT_STUB_ENV_FAIL','MISS'),"
                 "os.environ.get('SANDBAR_WATCH_INTERVAL_SEC','MISS'),"
                 "os.environ.get('SANDBAR_UT_CONTROL','MISS'))")
        r = asyncio.run(agent_activities.run_handover_leg(
            {"name": "env-probe", "cmd": "%s -c \"%s\"" % (PY, probe)},
            cwd=Path(tempfile.gettempdir())))
        assert r["exit"] == 0
        assert "MISS MISS MISS" in r["output_tail"]             # 三族旋钮全被剥除
        assert "visible" in r["output_tail"]                    # 非旋钮面透传如常
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_h6_output_tail_truncated_to_800():
    r = asyncio.run(agent_activities.run_handover_leg(
        {"name": "noisy", "cmd": "%s -c \"print('x' * 5000)\"" % PY},
        cwd=Path(tempfile.gettempdir())))
    assert len(r["output_tail"]) <= 800 and r["output_tail"].endswith("x")


def test_h7_r3_dict_rebuild_point_source_lock():
    # R3：dict 回退重建点漏写新键=命令跑了回执仍显 0（报文与事实相反）
    src = _src("dev_lane.py")
    for key in ("handover_ran", "handover_passed", "handover_failed"):
        assert '%s=int(rraw.get("%s") or 0)' % (key, key) in src


# ---------- I. 旋钮入族 + 剥除面同源（review R2） ----------

def test_i1_new_knobs_in_test_stub_family():
    for k in ("SANDBAR_AGENT_STUB_ENV_FAIL", "SANDBAR_AGENT_STUB_ENV_REASON",
              "SANDBAR_AGENT_STUB_HANDOVER"):
        assert k in shared.TEST_STUB_ENV_KNOBS, k


def test_i2_strip_face_single_discipline_source_lock():
    # verify_lane 子进程 env 与移交命令子进程 env 同一句剥除判据（两处，不多不少）
    src = _src("agent_activities.py")
    assert src.count("if k not in TEST_STUB_ENV_KNOBS and "
                     "k not in WORKER_ROUTING_ENV_KNOBS") == 2


def test_i3_leg_timeout_is_capacity_not_verdict_relaxation():
    assert agent_activities.HANDOVER_LEG_TIMEOUT_SEC == \
        agent_activities.INTEG_CMD_TIMEOUT_SEC


# ---------- J. 契约块与义务句在场（要求③ + C2） ----------

def test_j1_generic_contract_block_in_prompt():
    st = shared.Stage(id="implement", name="实现", role="developer")
    prompt = shared.build_stage_prompt("t-ut", {"title": "x"}, st, [],
                                       "/tmp/r.json", 1, "")
    assert "环境不可用契约" in prompt
    assert "env_fail" in prompt and "handover_runs" in prompt
    assert "票不停摆" in prompt
    assert "不许谎报" in prompt and "不许用 status=ok 掩盖" in prompt


def test_j2_flow_brief_implement_carries_env_contract():
    b = dev_lane.FLOW_BRIEF["implement"]
    assert "环境不可用契约" in b and "env_fail" in b and "handover_runs" in b
    assert "票不停摆" in b


def test_j3_flow_brief_arbitrate_duty_sentences_c2():
    b = dev_lane.FLOW_BRIEF["arbitrate"]
    # R5②：失败命令不得因单列计数放行
    assert "失败命令=验证未过" in b and "不得因命令单列计数而放行" in b
    # R4：env_fail 段=验证未闭环，不得当已验证
    assert "验证未闭环" in b and "不得当已验证" in b


def test_j4_arb_acc_context_wiring_source_lock():
    # R4/R5 接线：仲裁/走查上下文都注入移交命令结果行 + 环境受限段点名行
    src = _src("dev_lane.py")
    assert "【移交验证命令（t260917-08）】" in src
    assert "【环境受限段（未验证声明）】" in src
    assert 'arb_ctx += "\\n" + _hv_ctx' in src
    assert "_hv_ctx" in src.split("acc_ctx = ")[1].split("if workflow.patched")[0]
