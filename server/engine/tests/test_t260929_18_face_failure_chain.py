"""t260929-18 票面失败文案带真实根因（异常链下钻，单一定义点=shared）。

工单验收对应：
  (a) Temporal 形包链（ActivityError with cause，SDK 异常类进程内直构）→
      format_agent_stage_failure 的票面文案含活动真实报错，不再只剩
      "Activity task failed" 壳；
  (b) reverse lock：worker_terminated 专用文案恒赢过链下钻（t260916-29 契约）；
  (c) 畸形矩阵：无链 / cause 非异常 / 成环 / 超深链 / 全链空消息 → 显式
      「根因不可得」或保底旧文案，绝不炸、绝不编造。

**超深链语义（review 意见②的口径钉死）**：取封顶（REASON_CHAIN_MAX_DEPTH=8）内
能走到的**最深一层真实消息**——链被截断不谎称「不可得」（真实消息在手）；
「不可得」只用于全链没有任何层携带非空消息的形态。本文件的 (c) 超深用例按此
断言 deepest-reachable，与实现同向。

**根=最外层的去重口径（review 意见③）**：链上无更深层非空消息（level 0）时
逐字维持旧文案，不追加「根因」段——同一句不打印两遍（老形态字节兼容）。

UT 零网络/零 Temporal/零 git（conftest 纪律）；照搬清单见实现交接报告：
[depth>cap] 保（就地停）；[非异常 cause] 保（就地停）；[全链空消息] 保
（→ 不可得）；[成环] 新增（id 复见即停）；[.cause 优先遍历] 新增（client 旧走法
只认 __cause__）；[500 字截断] 保。
"""
import pathlib
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import client as client_mod  # noqa: E402
import shared  # noqa: E402
from shared import (  # noqa: E402
    REASON_CHAIN_MAX_DEPTH,
    REASON_MAX_CHARS,
    WORKER_TERMINATED_ERROR_TYPE,
    chain_failure_reason,
    exception_chain_note,
    format_agent_stage_failure,
)
from temporalio.exceptions import ActivityError, ApplicationError  # noqa: E402

REAL_DETAIL = ("agent 未写结果文件 result.json（rc=1）；挪开留证后发 retry_qc 重写本段")


def _activity_error(cause, msg="Activity task failed"):
    """工作流侧形态的 ActivityError：底层错误经 __cause__ 挂链（SDK 语义）。"""
    ae = ActivityError(msg, scheduled_event_id=1, started_event_id=2, identity="ut",
                       activity_type="implement", activity_id="7", retry_state=None)
    ae.__cause__ = cause
    return ae


def _app_err(msg):
    return ApplicationError(msg, type=WORKER_TERMINATED_ERROR_TYPE, non_retryable=True)


# ---------- (a) 真实 Temporal 形包链：票面带真实根因 ----------

def test_a_face_carries_real_activity_message():
    """ActivityError("Activity task failed") 包 RuntimeError(真实明细)：
    票面必须含真实明细，且点名来源层（第 1 层 + 类型）。"""
    exc = _activity_error(RuntimeError(REAL_DETAIL))
    msg = format_agent_stage_failure("t260929-15", "implement", exc, gen=2)
    assert REAL_DETAIL in msg
    assert "Activity task failed" in msg          # 最外层壳仍如实呈现（不丢真）
    assert "root cause (level 1 on the chain, RuntimeError)" in msg
    assert "worker terminated externally" not in msg
    # 旧文案本就不含票号/段号/次数（仅 worker 停机分支有）——维持该形状不扩面。
    assert "(ticket " not in msg


def test_a_cause_first_walk_finds_temporal_cause_attr():
    """.cause 优先遍历（新增守卫，client 旧走法只认 __cause__）：Temporal 新版
    SDK 把底层错误挂在异常的 cause 属性上——鸭子面（SimpleNamespace.cause）复现
    该形态，.cause 在场时必须赢过缺省的 __cause__ 兜底。"""
    inner = RuntimeError(REAL_DETAIL)
    mid = RuntimeError("mid shell")
    mid.__cause__ = inner
    duck = SimpleNamespace(cause=mid)        # .cause 挂真链，无 __cause__
    found = chain_failure_reason(duck)
    assert found[0] == 2 and found[2] == REAL_DETAIL
    note = exception_chain_note(duck)
    assert REAL_DETAIL in note and "level 2 on the chain, RuntimeError" in note


def test_a_deepest_of_three_level_chain_wins():
    """三层链取最深非空消息（ActivityError → ApplicationError → RuntimeError）。"""
    mid = ApplicationError("activity failure detail", non_retryable=True)
    mid.__cause__ = RuntimeError(REAL_DETAIL)
    exc = _activity_error(mid)
    found = chain_failure_reason(exc)
    assert found[0] == 2 and found[1] == "RuntimeError" and found[2] == REAL_DETAIL
    assert REAL_DETAIL in format_agent_stage_failure("t", "s", exc)


# ---------- (b) reverse lock：worker_terminated 文案恒赢 ----------

def test_b_worker_terminated_wording_beats_chain_digging():
    """链上再多消息，worker_terminated 专用文案也一字不变（t260916-29 契约②）。"""
    exc = _activity_error(_app_err("worker 被外部终止…t-x/implement gen=1"),
                          msg="Activity task failed")
    exc.__cause__.__cause__ = RuntimeError(REAL_DETAIL)
    msg = format_agent_stage_failure("t-x", "implement", exc)
    assert msg.startswith("worker terminated externally (shutdown/reload); the activity was cancelled")
    assert REAL_DETAIL not in msg and "root cause" not in msg


def test_b_classify_negative_still_digs_chain():
    """KI-093 反例（普通活动失败）不误归 worker 停机，且链下钻照常带根因。"""
    exc = _activity_error(RuntimeError(REAL_DETAIL))
    assert shared.classify_worker_termination(exc) is False
    assert REAL_DETAIL in format_agent_stage_failure("t-x", "implement", exc)


# ---------- (c) 畸形矩阵：不炸、不编造 ----------

def test_c_no_chain_keeps_legacy_wording_byte_for_byte():
    """根=最外层（无链/level 0）：逐字维持旧文案（防同句双打，review 意见③）。"""
    exc = RuntimeError("headless agent exited (rc=1)")
    assert format_agent_stage_failure("t-1", "create_plan", exc) == \
        "agent activity failure (already retried): RuntimeError: headless agent exited (rc=1)"
    assert exception_chain_note(exc) == ""


def test_c_none_and_non_exception_input():
    """None / 非异常输入：不进链下钻，旧文案保底，不炸。"""
    assert format_agent_stage_failure("t-1", "s", None) == \
        "agent activity failure (already retried): NoneType: None"
    assert format_agent_stage_failure("t-1", "s", "stray-string") == \
        "agent activity failure (already retried): str: stray-string"
    assert chain_failure_reason(None) is None


def test_c_cause_not_an_exception():
    """cause 挂非异常对象（类属性遮蔽描述子模拟 C 扩展/反序列化脏链）：就地停，
    已见层的消息照常返回，不炸不编造。"""
    class _WeirdCause(RuntimeError):
        __cause__ = "not-an-exception"      # 类属性遮蔽 BaseException 描述子
    found = chain_failure_reason(_WeirdCause("outer msg"))
    assert found[0] == 0 and found[2] == "outer msg"
    assert format_agent_stage_failure("t-1", "s", _WeirdCause("outer msg")) == \
        "agent activity failure (already retried): _WeirdCause: outer msg"


def test_c_cyclic_chain_no_hang_no_fabrication():
    """成环（自环/互环/鸭子 .cause 环）：停在已见层，真实消息在手不谎称不可得。"""
    loop = RuntimeError("loop msg")
    loop.__cause__ = loop
    found = chain_failure_reason(loop)
    assert found is not None and found[2] == "loop msg"
    a, b = RuntimeError("a msg"), RuntimeError("b msg")
    a.__cause__, b.__cause__ = b, a
    assert chain_failure_reason(a)[2] in ("a msg", "b msg")
    sn = SimpleNamespace()
    sn.cause = sn                            # 鸭子链自环
    chain_failure_reason(sn)                 # 不炸即达标（str(sn) 非空则如实收）


def test_c_all_empty_messages_reason_unobtainable():
    """全链没有任何层携带非空消息 → None + 票面显式「根因不可得」，绝不编造。"""
    empty = ActivityError("", scheduled_event_id=1, started_event_id=2,
                          identity="ut", activity_type="x", activity_id="1",
                          retry_state=None)
    empty.__cause__ = RuntimeError("   ")
    assert chain_failure_reason(empty) is None
    msg = format_agent_stage_failure("t-1", "s", empty)
    assert "root cause unavailable" in msg
    assert "agent activity failure (already retried)" in msg
    assert "root cause (level" not in msg          # never fabricated


def test_c_over_deep_chain_returns_deepest_reachable():
    """超深链（>封顶）：口径=取封顶内最深一层真实消息（见文件头语义钉死），
    不是「不可得」——测试与实现同向（review 意见②）。"""
    cur = RuntimeError("level%d" % (REASON_CHAIN_MAX_DEPTH + 3))
    for i in range(REASON_CHAIN_MAX_DEPTH + 2, -1, -1):
        nxt = RuntimeError("level%d" % i)
        nxt.__cause__ = cur
        cur = nxt
    found = chain_failure_reason(cur)
    assert found is not None
    assert found[0] == REASON_CHAIN_MAX_DEPTH - 1
    assert found[2] == "level%d" % (REASON_CHAIN_MAX_DEPTH - 1)
    assert "root cause unavailable" not in format_agent_stage_failure("t-1", "s", cur)


def test_c_truncation_cap():
    """超长消息截 REASON_MAX_CHARS（500）字。"""
    huge = RuntimeError("x" * 5000)
    found = chain_failure_reason(_activity_error(huge))
    assert len(found[2]) == REASON_MAX_CHARS
    msg = format_agent_stage_failure("t-1", "s", _activity_error(huge))
    assert "root cause (level 1 on the chain, RuntimeError)" in msg


def test_c_duck_typed_namespace_chain():
    """鸭子链（SimpleNamespace.cause，classify 同款容忍面）：不炸，按同判据走。"""
    inner = SimpleNamespace(cause=None)      # str 非空——鸭子面如实收它（不装异常）
    outer = SimpleNamespace(cause=inner)
    found = chain_failure_reason(outer)
    assert found is not None                 # 不炸即达标；形态如实不判异常类型


# ---------- 单一定义点 / 客户端委托 ----------

def test_client_failure_reason_of_delegates_to_shared():
    """client._failure_reason_of 委托 shared.chain_failure_reason（单走法），
    常量为 shared 别名（防漂移）。"""
    assert client_mod.TERMINAL_FACE_CAUSE_DEPTH == REASON_CHAIN_MAX_DEPTH
    assert client_mod.TERMINAL_FACE_REASON_MAX_CHARS == REASON_MAX_CHARS
    try:
        raise RuntimeError("套件 boom")
    except RuntimeError as e:
        outer = ApplicationError("Workflow execution failed", non_retryable=True)
        outer.__cause__ = e
    assert client_mod._failure_reason_of(outer) == "套件 boom"
    assert client_mod._failure_reason_of(None) == ""
    empty = RuntimeError("")
    empty.__cause__ = RuntimeError("  ")
    assert client_mod._failure_reason_of(empty) == ""


def test_exception_chain_note_shared_by_side_channels():
    """侧通道后缀：level>0 给「根因」段；level 0 / 无消息给空串（不加空尾巴）。"""
    exc = _activity_error(RuntimeError(REAL_DETAIL))
    note = exception_chain_note(exc)
    assert note.startswith("; root cause (level 1 on the chain, RuntimeError): ")
    assert REAL_DETAIL in note
    assert exception_chain_note(RuntimeError("plain")) == ""
    empty = RuntimeError("  ")
    empty.__cause__ = RuntimeError("")
    assert exception_chain_note(empty) == ""


def test_replay_determinism_same_object_same_text():
    """replay 安全口径：同一异常对象重复格式化 → 逐字节相同（纯函数零状态）。"""
    exc = _activity_error(RuntimeError(REAL_DETAIL))
    first = format_agent_stage_failure("t-1", "implement", exc, gen=1)
    for _ in range(3):
        assert format_agent_stage_failure("t-1", "implement", exc, gen=1) == first
