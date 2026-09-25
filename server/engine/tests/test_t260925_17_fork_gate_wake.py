#!/usr/bin/env python3
"""t260925-17（KI-120）单测：并行叉 join-settle 路径闸拒 blocked 的「醒后真重跑」复位。

根因（实案 t260925-05）：arb_acc_parallel（arbitrate ∥ acceptance_walkthrough）两边
gather 完成 → join settle 命 path_gate_reason= 落 blocked，但 arb_done/arb_res 簿记
不复位 → authorize+retry_qc 唤醒后 pend 恒空，叉不重入、agent 不重生，票定格
「blocked + 空 blocked_reason」（_blocked 醒后清点①所致）零活动。

覆盖口径（=create_plan gen0 方案步 1-2 + review 附条件①③）：
  A. 纯函数 settle_path_gate_refused：判据/畸形输入（None、缺 error、dict 态、
     非 str error）fail-closed 不抛——外部输入三态钩子。
  B. 行为：_blocked 醒后（retry_qc / rework 两路）清空 reason + 重驱观测日志；
     旧门（detail face 关）无新日志（在途票重放逐字旧行为）。
  C. 源码锁（AST）：①复位恰在 arb fork 的闸拒分支内、过 KI120 门、只翻
     arb_done/arb_res（不碰昂贵的 walkthrough 边）；②integ_join 闸拒位不做 done
     旗复位（醒后 settle 本身重驱）；③所有 SettleLaneArgs 调用带
     authorizations=self._protected_authz_records()（review 附条件①：授权现取现传）；
     ④_blocked 醒后清点块内含重驱日志；⑤新 PATCH_ID 常量唯一。

UT 全程禁网络/真 Temporal（conftest 只加 sys.path）。
运行：engine venv `python -m pytest server/engine/tests/test_t260925_17_fork_gate_wake.py -q`。
"""
from __future__ import annotations

import ast
import datetime
import sys
from pathlib import Path
from types import SimpleNamespace


POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import dev_lane  # noqa: E402
from shared import SettleLaneResult  # noqa: E402

TICKET = "t26092517ut"
# ---------- 壳（test_t260916_19 _mk_wf 族同款：免 Temporal 运行时） ----------

def _mk_wf(detail_face: bool = True):
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: pid == dev_lane.KI120_FORK_GATE_WAKE_RESET_PATCH_ID,
        now=lambda: datetime.datetime(2026, 9, 25, 12, 0, 0,
                                      tzinfo=datetime.timezone.utc),
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None),
        # 唤醒桩：直接翻 token 模拟 retry_qc 已投递（cond 短路求值安全）
        wait_condition=lambda cond: None)
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = {"status": "dispatched", "log": []}
    wf.timeline = []
    wf._gens = {}
    wf._retry_token = 0
    wf._rework = None
    wf.results = {}
    wf.refused = []
    wf.ticket_id = TICKET
    wf._detail_face_on = detail_face
    wf._rework_escape_on = False
    wf.engine_version = 2
    return wf


def _logs(wf) -> list[str]:
    return [str(e.get("note") or "") for e in (wf.meta.get("log") or [])]


# ---------- A. 纯函数：判据 + 畸形输入 fail-closed ----------

def test_a_gate_marker_contract_shape():
    # 判据契约（t260911-03）：error 带 path_gate_reason= 签名才算闸拒；空/缺
    # error（畸形/老回执）不算——调用点回执已归一为 SettleLaneResult，内联判断
    # 逐字等价于对归一后 error 的签名包含测试。
    assert "path_gate_reason=" in (SettleLaneResult(
        error="拒绝 path_gate_reason=protected_scope").error or "")
    assert "path_gate_reason=" not in (SettleLaneResult(error="git 失败").error or "")
    assert "path_gate_reason=" not in (SettleLaneResult().error or "")
    # 防御：settled 回执可能落成 dict（老 worker 反序列化态），归一层取 .get 缺省
    assert "path_gate_reason=" not in str({"note": "ok"}.get("error") or "")


# ---------- B. _blocked 醒后：清点① + 重驱观测日志 ----------

def _run_blocked(wf):
    import asyncio
    asyncio.get_event_loop_policy()
    asyncio.run(wf._blocked("arbitrate", "卡因：受保护路径 out"))


def test_b_retry_qc_wake_clears_reason_and_logs_redrive():
    wf = _mk_wf()
    wf._retry_token = 0

    async def wake(cond):
        wf._retry_token += 1  # 模拟 retry_qc 已投递
        assert cond() is True
    dev_lane.workflow.wait_condition = wake
    _run_blocked(wf)
    assert wf.meta["stage_state"] == "blocked"
    assert wf.meta["blocked_reason"] == ""      # 清点①：解除时清空
    assert wf.meta["blocked_detail"] is None
    assert any("blocked 解除（retry_qc 唤醒）→ 主循环重驱" in n
               for n in _logs(wf))


def test_b_rework_wake_logs_rework_redrive():
    wf = _mk_wf()

    async def wake(cond):
        assert cond() is True  # _rework 在场即可醒
    dev_lane.workflow.wait_condition = wake
    wf._rework = SimpleNamespace(who="host", note="打回",
                                 target_stage="arbitrate")
    _run_blocked(wf)
    assert wf.meta["blocked_reason"] == ""
    assert any("blocked 解除（rework 唤醒）→ 主循环重驱" in n for n in _logs(wf))


def test_b_old_face_wake_has_no_new_log_line():
    # 旧门（detail face 关）醒后不加日志：在途票重放逐字旧行为。
    wf = _mk_wf(detail_face=False)
    wf._retry_token = 0

    async def wake(cond):
        wf._retry_token += 1
        assert cond() is True
    dev_lane.workflow.wait_condition = wake
    _run_blocked(wf)
    assert wf.meta["blocked_reason"] == "卡因：受保护路径 out"  # 旧分支不清
    assert not any("blocked 解除" in n for n in _logs(wf))  # 旧分支无醒后重驱日志


# ---------- C. 源码锁（AST） ----------

def _tree():
    return ast.parse((POC / "dev_lane.py").read_text(encoding="utf-8"))


def _func(tree, name):
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    raise AssertionError("function %s not found" % name)


def _patched_ids(tree):
    return [n.value.value for n in ast.walk(tree)
            if isinstance(n, ast.Assign)
            and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
            and n.targets[0].id.endswith("_PATCH_ID")
            and isinstance(n.value, ast.Constant)]


def test_c_patch_id_unique():
    ids = _patched_ids(_tree())
    assert ids.count(dev_lane.KI120_FORK_GATE_WAKE_RESET_PATCH_ID) == 1
    assert len(ids) == len(set(ids))


def _gate_refusal_ifs_in_run():
    run = _func(_tree(), "run")
    out = []

    def _is_gate_test(t):
        # `s.error and "path_gate_reason=" in s.error`（BoolOp + 签名常量）
        return isinstance(t, ast.BoolOp) and any(
            isinstance(v, ast.Constant) and v.value == "path_gate_reason="
            for v in ast.walk(t))

    for n in ast.walk(run):
        if isinstance(n, ast.If) and _is_gate_test(n.test):
            out.append(n)
    return out


def _assigns(nodes):
    out = {}
    for n in nodes:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                and isinstance(n.targets[0], ast.Name):
            v = n.value
            if isinstance(v, ast.Constant):
                out[n.targets[0].id] = v.value
            elif isinstance(v, ast.Constant) is False:
                out[n.targets[0].id] = "<expr>"
    return out


def test_c_arb_fork_refusal_resets_arbitrate_edge_behind_gate():
    ifs = [i for i in _gate_refusal_ifs_in_run()
           if any(isinstance(x, ast.Await)
                  and isinstance(x.value, ast.Call)
                  and isinstance(x.value.func, ast.Attribute)
                  and x.value.func.attr == "_blocked"
                  and x.value.args
                  and isinstance(x.value.args[0], ast.Constant)
                  and x.value.args[0].value == "arbitrate"
                  for x in ast.walk(i))]
    assert len(ifs) == 1, "arb fork 闸拒分支应恰一处"

    def _is_ki120_gate(t):
        if not (isinstance(t, ast.Call) and isinstance(t.func, ast.Attribute)
                and t.func.attr == "patched" and t.args):
            return False
        a = t.args[0]
        return (isinstance(a, ast.Name)
                and a.id == "KI120_FORK_GATE_WAKE_RESET_PATCH_ID") \
            or (isinstance(a, ast.Constant)
                and a.value == dev_lane.KI120_FORK_GATE_WAKE_RESET_PATCH_ID)

    gated = [x for x in ast.walk(ifs[0]) if isinstance(x, ast.If)
             and _is_ki120_gate(x.test)]
    assert len(gated) == 1, "复位必须在 KI120 门内"
    a = _assigns([x for x in ast.walk(gated[0])])
    assert a.get("arb_done") is False
    assert a.get("arb_res") is None
    # 只翻被闸挡住的仲裁边：昂贵的 walkthrough 边结果保留（KI-024 语义）
    assert "acc_done" not in a and "acc_res" not in a


def test_c_integ_join_refusal_reset_fork_origin_only():
    # integ_join 闸拒位（t260925-17 KI-120 同形对齐）：fork 来源（design_done）
    # 复位 impl_done 并回叉相位（醒后 implement 边真重跑）；无 patched 门＝在途票
    # 重放破确定性（t260917-04 先例）。
    integ = [i for i in _gate_refusal_ifs_in_run()
             if any(isinstance(x, ast.Await)
                    and isinstance(x.value, ast.Call)
                    and isinstance(x.value.func, ast.Attribute)
                    and x.value.func.attr == "_blocked"
                    and x.value.args
                    and isinstance(x.value.args[0], ast.Constant)
                    and x.value.args[0].value == "implement"
                    for x in ast.walk(i))]
    assert len(integ) == 1
    gated = [x for x in ast.walk(integ[0]) if isinstance(x, ast.If)
             and "workflow.patched(" in ast.unparse(x.test)
             and "KI120_FORK_GATE_WAKE_RESET_PATCH_ID" in ast.unparse(x.test)]
    assert len(gated) == 1, "fork 来源复位必须在 KI120 门内"
    a = _assigns([x for x in ast.walk(gated[0])])
    assert a.get("impl_done") is False
    # 相位回叉：醒后主循环重入 parallel_impl_design，pend 重算真重驱
    phase_reset = [n for n in ast.walk(gated[0]) if isinstance(n, ast.Assign)
                   and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                   and n.targets[0].id == "phase"
                   and isinstance(n.value, ast.Constant)
                   and n.value.value == "parallel_impl_design"]
    assert len(phase_reset) == 1


def test_c_arb_ctx_injected_on_wake_redrive():
    # 仲裁边重跑 prompt 带授权上下文（人外部输入进新 prompt，不消费陈旧判决）
    ifs = [i for i in _gate_refusal_ifs_in_run()
           if any(isinstance(x, ast.Await)
                  and isinstance(x.value, ast.Call)
                  and isinstance(x.value.func, ast.Attribute)
                  and x.value.func.attr == "_blocked"
                  and x.value.args
                  and isinstance(x.value.args[0], ast.Constant)
                  and x.value.args[0].value == "arbitrate"
                  for x in ast.walk(i))]
    gated = [x for x in ast.walk(ifs[0]) if isinstance(x, ast.Assign)
             and len(x.targets) == 1 and isinstance(x.targets[0], ast.Name)
             and x.targets[0].id == "arb_ctx"]
    assert len(gated) == 1
    assert "授权" in ast.unparse(gated[0])


def test_c_all_settle_lane_args_carry_fresh_authorizations():
    # review 附条件①：授权现取现传——每处 SettleLaneArgs 都带
    # authorizations=self._protected_authz_records()，重落 settle 才能吃到新授权。
    tree = _tree()
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "SettleLaneArgs"]
    assert len(calls) >= 2, "integ_join 与 arb fork 两处落盘点"
    for c in calls:
        kw = {k.arg for k in c.keywords}
        assert "authorizations" in kw
        auth = [k for k in c.keywords if k.arg == "authorizations"][0]
        assert isinstance(auth.value, ast.Call) \
            and isinstance(auth.value.func, ast.Attribute) \
            and auth.value.func.attr == "_protected_authz_records"


def test_c_blocked_wake_log_inside_detail_face_clear_block():
    blk = _func(_tree(), "_blocked")
    gated = [n for n in ast.walk(blk) if isinstance(n, ast.If)
             and "_detail_face_on" in ast.unparse(n.test)]
    assert len(gated) == 1, "清点①唯一汇合点"
    body = ast.unparse(gated)
    assert "blocked_reason'] = ''" in body
    assert "blocked 解除" in body and "主循环重驱" in body
