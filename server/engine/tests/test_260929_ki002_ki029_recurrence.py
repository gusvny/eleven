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


def test_all_three_guards_use_the_single_helper():
    src = Path(aa.__file__).read_text("utf-8")
    assert src.count("if polls >= effective_max_polls(args):") == 3, \
        "三处守卫（通用步/arbitrate/acceptance_walkthrough）都必须走单点兜底"
    assert "if args.max_polls and polls >= args.max_polls:" not in src, \
        "旧的死分支（恒 0 ⇒ 恒不进入）不许复活"


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
