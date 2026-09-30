"""260929 单测：KI-002 与 KI-029 **复发**的两处直修（simplify 巡检 20260929 期审出）。

两处都不是新病，是既有 KI 复发（同族复发＝第 N 次：要么没修透，要么修了没守住）：

  ① **KI-002**：`AgentStageArgs.max_polls` 缺省 0 且注释承诺「activity 侧常量」——**没有这个
     常量**，于是三处轮询上限守卫恒为死码，卡死的 agent 只能等 Temporal 平台超时（回执里
     没有结果文件路径、没有轮询数，诊断被引偏）。修法：兑现常量（由步预算派生 ⇒ 假红风险=0：
     上限必落在平台超时之前、任何本来能跑完的步子之后），显式值（集成场景压超时路径）逐字不变。
  ② **KI-029**：连接失败被记成 kind=internal（5xx 语义）而不是 transient（刷新即好）——
     而模块头的分类表就是契约。修法：`_connect()` 翻成带 kind 的类型 + main() 兜底单点分类
     （本文件 14 个 `await _connect()` 全在分类块之外，逐点补 try 是 14 处重复，单点才对）。

运行：server/engine/.venv/bin/python -B -m pytest \
      server/engine/tests/test_260929_ki002_ki029_recurrence.py -q
"""
import ast
import json
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
import client as cl  # noqa: E402


# ---------------- ① KI-002 ----------------

def test_activity_side_constant_exists_and_is_derived_from_the_step_budget():
    assert aa.DEFAULT_MAX_POLLS > 0, "「activity 侧常量」必须真的存在（KI-002 病根就是它不存在）"
    cap_sec = aa.DEFAULT_MAX_POLLS * aa.POLL_SEC
    budget = aa.DEFAULT_STEP_BUDGET_SEC
    assert cap_sec <= budget - aa.DEFAULT_MAX_POLLS_MARGIN_SEC, \
        "上限必须落在平台超时之前（否则等于没有兜底）"
    assert cap_sec >= budget - aa.DEFAULT_MAX_POLLS_MARGIN_SEC - aa.POLL_SEC, \
        "上限不许比「平台超时−余量」早太多（那会杀本来能跑完的慢步＝假红）"


def test_explicit_values_win_and_missing_values_fall_back():
    class A:
        max_polls = 0

    class B:
        max_polls = 2

    class C:
        max_polls = 50

    class D:                      # 畸形/负数/缺属性 → 缺省兜底，绝不「立即触发」
        max_polls = -3

    class E:
        max_polls = "junk"

    assert aa.effective_max_polls(A()) == aa.DEFAULT_MAX_POLLS
    assert aa.effective_max_polls(object()) == aa.DEFAULT_MAX_POLLS
    assert aa.effective_max_polls(D()) == aa.DEFAULT_MAX_POLLS
    assert aa.effective_max_polls(E()) == aa.DEFAULT_MAX_POLLS
    assert aa.effective_max_polls(B()) == 2, "显式值逐字不变（集成场景靠它压超时路径）"
    assert aa.effective_max_polls(C()) == 50


def test_all_three_stages_route_through_the_single_poll_helper():
    """t261001-03：轮询循环三份逐字副本合一（_wait_for_agent_result）。

    反证锚：修复前的代码里没有 _wait_for_agent_result 这个名字，且旧守卫
    "if polls >= effective_max_polls(args):" 恰好出现 3 次 —— 本用例对修复前
    源码为红（守卫计数断言失败），对修复后源码为绿。"""
    import re
    src = Path(aa.__file__).read_text("utf-8")
    assert src.count("async def _wait_for_agent_result(") == 1, \
        "轮询循环的实现必须恰有一份（复制=KI-002/KI-029 族修复漏改一处的温床）"
    assert len(re.findall(r"await _wait_for_agent_result\(", src)) == 3, \
        "三站（通用步/arbitrate/acceptance_walkthrough）都必须改走共享 helper"
    assert src.count("if polls >= effective_max_polls(args):") == 1, \
        "KI-002 上限守卫只住在共享 helper 里（旧三副本不许复活）"
    assert "if args.max_polls and polls >= args.max_polls:" not in src, \
        "旧的死分支（恒 0 ⇒ 恒不进入）不许复活"
    # cap 仍逐段生效：各段超时文案自我点名（措辞逐字锁现状）
    for wording in ("等结果文件超时（%d 次轮询 × %ds）：%s",
                    "等仲裁结果超时（%d 轮询）：%s",
                    "等验收报告超时（%d 轮询）：%s"):
        assert wording in src, "段名超时文案漂移：%r" % wording


class _FakeActivity:
    beats = []

    def heartbeat(self, payload):
        self.beats.append(json.loads(payload))


class _FakeProc:
    def __init__(self):
        self.reaped = []
        self.rc = None

    def poll(self):
        return self.rc

    def reap(self, *a):
        self.reaped.append(a)


def _stage_args(max_polls=3):
    from types import SimpleNamespace
    return SimpleNamespace(max_polls=max_polls, gen=1,
                           ticket_id="t261001-03", log_file="")


@pytest.fixture()
def poll_env(monkeypatch):
    """共享 helper 的行为级夹具：假 activity（心跳入账）+ 真 asyncio 睡 0 秒。"""
    monkeypatch.setattr(aa, "activity", _FakeActivity())
    monkeypatch.setattr(aa, "POLL_SEC", 0)
    _FakeActivity.beats = []          # 类级入账，逐用例清零
    return _FakeProc()


@pytest.mark.parametrize("label,gone,wording", [
    ("stage_impl", "headless", "等结果文件超时"),
    ("arbitrate", "arbitrate", "等仲裁结果超时"),
    ("acceptance_walkthrough", "acceptance", "等验收报告超时"),
])
def test_cap_fires_per_stage_through_the_shared_helper(poll_env, tmp_path,
                                                       label, gone, wording):
    """KI-002 复发杆的行为面：三站共享 helper 下，上限仍逐段触发且超时文案点名段名。"""
    import asyncio
    proc = poll_env
    rfile = tmp_path / "result.json"          # 永不就绪
    args = _stage_args(max_polls=3)

    async def _run():
        return await aa._wait_for_agent_result(
            args, rfile, proc, {}, tmp_path, label, gone,
            lambda r: r,
            lambda polls: "%s（%d 轮询）" % (wording, polls))

    with pytest.raises(RuntimeError) as ei:
        asyncio.run(_run())
    assert wording in str(ei.value)
    assert proc.reaped == [(args.ticket_id, label)], \
        "超时路径 finally 兜底 reap 必须在位（失败路径也收尸）"
    beats = _FakeActivity.beats
    assert [b["stage"] for b in beats] == [label] * 3
    assert [b["polls"] for b in beats] == [0, 1, 2]
    for b in beats:
        assert set(b) == {"stage", "gen", "polls", "session_kb"}, \
            "心跳 payload 键不许漂移"


def test_shared_helper_settles_through_on_result(poll_env, tmp_path):
    """结果文件就绪 → on_result 处理链 → 返回值即回执（成功路径 reap 在链内）。"""
    import asyncio
    proc = poll_env
    rfile = tmp_path / "result.json"
    rfile.write_text(json.dumps({
        "status": "ok", "summary": "s", "report": "r",
        "deliverables": [], "files_changed": []}), "utf-8")
    args = _stage_args(max_polls=3)
    touched = []

    def _on_result(res):
        touched.append(res.status)
        proc.reap(args.ticket_id, "stage_impl")
        return res

    out = asyncio.run(aa._wait_for_agent_result(
        args, rfile, proc, {}, tmp_path, "stage_impl", "headless",
        _on_result, lambda polls: "t"))
    assert out.status == "ok" and touched == ["ok"]
    assert proc.reaped == [(args.ticket_id, "stage_impl")] * 2, \
        "结果就绪路径：reap 发生在 on_result 链内（settle 前收尸，KI-009），finally 对已收尸 proc 幂等"


def test_shared_helper_raises_named_when_proc_exits_without_result(poll_env, tmp_path):
    """进程先退出且无结果文件 → raise（点名 where 标签），先 reap 再 raise，finally 二次 reap。"""
    import asyncio
    proc = poll_env
    proc.rc = 7
    args = _stage_args(max_polls=3)
    # wedge 隔离面不属本票（t260922-11 自有复发杆）——此处静默桩掉，只看退出路径序
    import unittest.mock as um
    with um.patch.object(aa, "_wedge_quarantine_once", lambda *a, **k: None):
        async def _run():
            return await aa._wait_for_agent_result(
                args, tmp_path / "missing.json", proc, {}, tmp_path,
                "arbitrate", "arbitrate", lambda r: r, lambda polls: "t")

        with pytest.raises(RuntimeError) as ei:
            asyncio.run(_run())
    assert "arbitrate" in str(ei.value) and "7" in str(ei.value)
    assert proc.reaped == [("t261001-03", "arbitrate")] * 2


def test_shared_comment_points_at_a_real_constant():
    import shared
    src = Path(shared.__file__).read_text("utf-8")
    assert "DEFAULT_MAX_POLLS" in src, \
        "shared.AgentStageArgs.max_polls 的注释必须指向**真实存在**的常量（KI-002 病根=注释撒谎）"


# ---------------- ② KI-029 ----------------

def test_connect_failure_is_typed_as_transient(monkeypatch):
    class Boom:
        @staticmethod
        async def connect(*a, **kw):
            raise RuntimeError("Failed client connect: tcp connect error")

    monkeypatch.setattr(cl, "Client", Boom)
    with pytest.raises(cl.TransientConnectError) as ei:
        import asyncio
        asyncio.run(cl._connect())
    assert "瞬时" in str(ei.value) and getattr(ei.value, "kind", "") == cl.KIND_TRANSIENT


def test_infra_error_classification_single_point():
    assert cl._classify_infra_error(cl.TransientConnectError("x"))["kind"] == cl.KIND_TRANSIENT
    assert cl._classify_infra_error(RuntimeError("boom"))["kind"] == cl.KIND_INTERNAL, \
        "非连接类异常照旧 internal——不许把真 bug 洗成「重试即可」"
    assert cl._classify_infra_error(ValueError("bad"))["kind"] == cl.KIND_INTERNAL
    out = cl._classify_infra_error(cl.TransientConnectError("连接 temporal server 失败（...）"))
    assert out["ok"] is False and "TransientConnectError" in out["error"], \
        "报错必须精确：说清哪类失败，不许含糊"


def test_main_classifies_at_the_boundary_not_per_call_site():
    """全族判据：本文件 14 个 await _connect() 都不在分类块里（实测），修法只能是单点分类。"""
    src = Path(cl.__file__).read_text("utf-8")
    tree = ast.parse(src)
    sites = [n.lineno for n in ast.walk(tree)
             if isinstance(n, ast.Await) and isinstance(n.value, ast.Call)
             and isinstance(n.value.func, ast.Name) and n.value.func.id == "_connect"]
    assert len(sites) >= 10, "连接点数量异常（本文件实测 14 处），锁失效即复核"
    assert "result = _classify_infra_error(e)" in src, \
        "兜底必须走分类单点（逐点补 try = 14 处重复，且新副本还会漏）"
    assert 'raise TransientConnectError(' in src and "kind = KIND_TRANSIENT" in src, \
        "类型必须自带 kind（不靠文案匹配猜）"


def test_transient_kind_is_https_mapped_as_retryable():
    """契约面：KIND_TRANSIENT 是既有枚举值（消费者按它路由 503/重试），没有新造类。"""
    assert cl.KIND_TRANSIENT == "transient"
    assert cl.TransientConnectError.kind == cl.KIND_TRANSIENT
    assert issubclass(cl.TransientConnectError, RuntimeError), \
        "子类化 RuntimeError：既有 except RuntimeError 行为零变化"
