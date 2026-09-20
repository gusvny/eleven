"""t260916-29 worker 真·优雅停 + 取消可辨 + 重跑兜底（纯函数面 + 守卫面 + 接线锚，零 Temporal）。

覆盖（对齐工单验收①② UT 子用例；端到端场景在 selfcheck_worker_graceful_stop.py）：
  - worker.graceful_shutdown_timeout_sec：env 容错矩阵（缺省/畸形/NaN/Inf/负/显式 0 逃生门）；
  - worker._worker_extra_kwargs：Worker(...) 接线单一真源（timedelta 形状 + env 敏感）；
  - shared.classify_worker_termination：沿 .cause / __cause__ 链认 worker_terminated
    （SDK 工作流侧经 __cause__ 挂底层错误，converter.py:1095-1096）；畸形输入
    （None/野对象/cause 环/超深链）一律 False 不炸；
  - KI-093 场景级负例：「兄弟边被杀」（普通活动失败，无 worker_shutdown 取消细节）
    不得归类 worker_terminated——归因只在证据充分时成立（C2）；
  - shared.format_agent_stage_failure：worker_terminated → 票面点名「worker 被外部终止」
    + 票号/段号；其余逐字维持旧文案「agent 活动故障（已重试）：…」（改文案不改控制流）；
  - shared.retry_once_on_worker_termination：gate/类判/只重跑一次/取消不吞 四态；
  - agent_activities.worker_termination_guard：在飞记账四结局 + 停机取消→可辨
    ApplicationError（票/段/gen/attempt 在 message）；
  - C4 票面锚：dev_lane._blocked 落 meta.blocked_reason 后含「worker 被外部终止」
    + 票号段号（用户可感知面，KI-048 钉面）；
  - 接线锚（防漂移 tripwire）：run_worker 走 _worker_extra_kwargs/_graceful_shutdown；
    四个长活动汇聚点包 worker_termination_guard；守卫在 _run_agent_stage_impl 之外
    （KI-093 纪律：不碰内部 reap 粒度/进程组逻辑）。

UT 零网络/零 Temporal/零 git（conftest 纪律）；SDK 异常类经进程内直构。
"""
import asyncio
import inspect
import pathlib
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import agent_activities  # noqa: E402
import dev_lane  # noqa: E402
import shared  # noqa: E402
import worker  # noqa: E402
from agent_activities import worker_termination_guard  # noqa: E402
from shared import (  # noqa: E402
    WORKER_SHUTDOWN_RETRY_PATCH_ID,
    WORKER_TERMINATED_ERROR_TYPE,
    classify_worker_termination,
    format_agent_stage_failure,
    retry_once_on_worker_termination,
)
from temporalio.exceptions import ApplicationError, ActivityError  # noqa: E402


# ---------- SDK 异常构造助手 ----------

def _app_err(msg="worker 被外部终止（停机/重载），活动已取消：t-x/implement gen=1 attempt=2",
             type=WORKER_TERMINATED_ERROR_TYPE):
    return ApplicationError(msg, type=type, non_retryable=True)


def _activity_error(cause=None, msg="Activity task failed"):
    """构造工作流侧形态的 ActivityError：底层错误经 __cause__ 挂链（SDK 语义）。"""
    ae = ActivityError(msg, scheduled_event_id=1, started_event_id=2, identity="ut",
                       activity_type="implement", activity_id="7", retry_state=None)
    if cause is not None:
        ae.__cause__ = cause
    return ae


def _worker_terminated_error():
    return _activity_error(_app_err())


# ---------- graceful_shutdown_timeout_sec（env 容错矩阵） ----------

@pytest.mark.parametrize("raw,expected", [
    (None, worker.GRACEFUL_SHUTDOWN_DEFAULT_SEC),   # 未设 → 缺省 1800s
    ("", worker.GRACEFUL_SHUTDOWN_DEFAULT_SEC),     # 空白 → 缺省
    ("   ", worker.GRACEFUL_SHUTDOWN_DEFAULT_SEC),
    ("junk", worker.GRACEFUL_SHUTDOWN_DEFAULT_SEC),  # 畸形 → 缺省
    ("nan", worker.GRACEFUL_SHUTDOWN_DEFAULT_SEC),  # NaN → 缺省
    ("inf", worker.GRACEFUL_SHUTDOWN_DEFAULT_SEC),  # Inf → 缺省
    ("-inf", worker.GRACEFUL_SHUTDOWN_DEFAULT_SEC),
    ("-5", worker.GRACEFUL_SHUTDOWN_DEFAULT_SEC),   # 负数不得意外变「立即取消」
    ("0", 0.0),                                     # 显式 0 = 旧「立即取消」逃生门
    ("60", 60.0),
    ("42.5", 42.5),
    (" 90 ", 90.0),                                 # 带空白可解析
])
def test_graceful_timeout_matrix(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv(worker.GRACEFUL_SHUTDOWN_ENV, raising=False)
    else:
        monkeypatch.setenv(worker.GRACEFUL_SHUTDOWN_ENV, raw)
    assert worker.graceful_shutdown_timeout_sec() == expected


def test_graceful_default_constant_is_thirty_minutes():
    assert worker.GRACEFUL_SHUTDOWN_DEFAULT_SEC == 1800.0
    assert worker.GRACEFUL_SHUTDOWN_ENV == "SANDBAR_WORKER_GRACEFUL_SHUTDOWN_SEC"


def test_worker_extra_kwargs_shape(monkeypatch):
    monkeypatch.setenv(worker.GRACEFUL_SHUTDOWN_ENV, "42")
    kw = worker._worker_extra_kwargs()
    assert set(kw) == {"graceful_shutdown_timeout"}
    assert isinstance(kw["graceful_shutdown_timeout"], timedelta)
    assert kw["graceful_shutdown_timeout"] == timedelta(seconds=42)
    monkeypatch.delenv(worker.GRACEFUL_SHUTDOWN_ENV, raising=False)
    assert worker._worker_extra_kwargs()["graceful_shutdown_timeout"] == timedelta(
        seconds=worker.GRACEFUL_SHUTDOWN_DEFAULT_SEC)


def test_worker_wiring_tripwire():
    """接线锚：run_worker 必须经 _worker_extra_kwargs 构造 Worker、经 _graceful_shutdown
    停机；停机面必点名在飞（要求①）。源面断言，防止后人改回裸 Worker(...)。"""
    src_run = inspect.getsource(worker.run_worker)
    assert "_worker_extra_kwargs()" in src_run
    assert "_graceful_shutdown(workers, run_tasks, watch_task)" in src_run
    src_stop = inspect.getsource(worker._graceful_shutdown)
    assert "_log_shutdown_disposition" in src_stop
    assert "shutdown()" in src_stop
    assert "_log_shutdown_outcome" in src_stop


# ---------- classify_worker_termination ----------

def test_classify_positive_activity_error_chain():
    assert classify_worker_termination(_worker_terminated_error()) is True


def test_classify_positive_direct_application_error():
    assert classify_worker_termination(_app_err()) is True


def test_classify_positive_cause_attr_chain():
    """鸭子类型链：.cause 属性挂在普通对象上（非 __cause__）也能走通——分类只认证据
    （type=worker_terminated），不挑载体。"""
    mid = SimpleNamespace(cause=_app_err())
    assert classify_worker_termination(SimpleNamespace(cause=mid)) is True


def test_classify_positive_two_level_chain():
    a = _app_err()
    b = ApplicationError("outer", type="other_type")
    b.__cause__ = a
    assert classify_worker_termination(b) is True


def test_classify_negative_infra_failures():
    for exc in (TimeoutError("x"), RuntimeError("boom"),
                asyncio.CancelledError(),
                _app_err(type="ActivityPause"),        # 同型不同 type
                _activity_error(TimeoutError("heartbeat timeout")),
                _activity_error(RuntimeError("agent rc!=0"))):
        assert classify_worker_termination(exc) is False, type(exc).__name__


def test_classify_negative_ki093_sibling_reap_is_not_worker_termination():
    """C2 场景级负例（KI-093）：并行段「兄弟边被杀」的症状=在飞 agent 的进程被
    reap 连带杀掉→activity 抛普通 RuntimeError（未写结果文件）→工作流侧
    ActivityError(__cause__=RuntimeError)。它没有 worker_shutdown 取消细节，
    绝不能被归类 worker_terminated——否则 KI-093 症状被洗成 worker 停机。"""
    exc = _activity_error(RuntimeError(
        "headless agent 退出（rc=-9）但未写结果文件 result.json（日志 worker.log）"))
    assert classify_worker_termination(exc) is False
    assert "活动故障（已重试）" in format_agent_stage_failure("t-x", "implement", exc)


def test_classify_malformed_inputs_fail_closed():
    assert classify_worker_termination(None) is False
    assert classify_worker_termination(object()) is False
    assert classify_worker_termination("worker_terminated") is False  # 字符串不是异常链
    weird = SimpleNamespace(cause=object())  # cause 挂野对象（鸭子链面，py 不许 __cause__ 挂非异常）
    assert classify_worker_termination(weird) is False
    sn = SimpleNamespace(cause=None)
    sn.cause = sn  # .cause 自环
    assert classify_worker_termination(sn) is False
    loop = RuntimeError("loop")
    loop.__cause__ = loop  # 自环
    assert classify_worker_termination(loop) is False
    a, b = RuntimeError("a"), RuntimeError("b")
    a.__cause__, b.__cause__ = b, a  # 互环
    assert classify_worker_termination(a) is False
    deep = _app_err()
    for _ in range(12):  # 超深链（>8 层封顶）：证据不可信，不归因
        cur = RuntimeError("wrap")
        cur.__cause__ = deep
        deep = cur
    assert classify_worker_termination(deep) is False


def test_classify_depth_cap_still_finds_shallow_chain():
    wrap = RuntimeError("wrap")
    wrap.__cause__ = _app_err()
    assert classify_worker_termination(wrap) is True


# ---------- format_agent_stage_failure ----------

def test_format_worker_terminated_names_ticket_stage_gen():
    msg = format_agent_stage_failure("t260916-29", "implement",
                                     _worker_terminated_error(), gen=2)
    assert "worker 被外部终止（停机/重载）" in msg
    assert "活动已取消" in msg
    assert "t260916-29" in msg and "implement" in msg
    assert "第 2 次" in msg


def test_format_worker_terminated_without_gen():
    msg = format_agent_stage_failure("t-1", "arbitrate", _worker_terminated_error())
    assert "worker 被外部终止" in msg and "t-1" in msg and "arbitrate" in msg
    assert "第" not in msg


def test_format_legacy_text_unchanged_for_other_failures():
    """改文案不改旧语义：非 worker 停机失败逐字维持旧文案（票面老读者兼容）。"""
    exc = RuntimeError("headless agent 退出（rc=1）")
    assert format_agent_stage_failure("t-1", "create_plan", exc) == \
        "agent 活动故障（已重试）：RuntimeError: headless agent 退出（rc=1）"
    assert format_agent_stage_failure("t-1", "create_plan", None) == \
        "agent 活动故障（已重试）：NoneType: None"


# ---------- retry_once_on_worker_termination ----------

def _run_async(coro):
    return asyncio.run(coro)


def _retry_call(flavors, gate=True, on_retry=None):
    """flavors: 每次执行的异常列表（None=成功返回值）。返回 (结果, 调用次数)。"""
    calls = {"n": 0}

    async def run_once():
        n = calls["n"]
        calls["n"] += 1
        exc = flavors[n] if n < len(flavors) else None
        if exc is not None:
            raise exc
        return "ok-%d" % n

    async def scenario():
        return await retry_once_on_worker_termination(run_once, gate=gate,
                                                      on_retry=on_retry)

    return _run_async(scenario()), calls["n"]


def test_retry_once_retries_worker_termination_once():
    res, n = _retry_call([_worker_terminated_error()])
    assert res == "ok-1" and n == 2  # 恰好重跑一次


def test_retry_once_no_third_run_when_retry_also_fails():
    calls = {"n": 0}

    async def run_once():
        calls["n"] += 1
        raise _worker_terminated_error() if calls["n"] == 1 else RuntimeError("again")

    async def scenario():
        await retry_once_on_worker_termination(run_once, gate=True)

    with pytest.raises(RuntimeError):
        _run_async(scenario())
    assert calls["n"] == 2  # 第二次失败不再第三跑


def test_retry_once_skips_non_worker_failures():
    with pytest.raises(ValueError):
        _retry_call([ValueError("business fault")])
    calls = {"n": 0}

    async def run_once():
        calls["n"] += 1
        raise ValueError("business fault")

    async def scenario():
        await retry_once_on_worker_termination(run_once, gate=True)

    with pytest.raises(ValueError):
        _run_async(scenario())
    assert calls["n"] == 1  # 非 worker 停机类：不重跑


def test_retry_once_gate_closed_never_retries():
    calls = {"n": 0}

    async def run_once():
        calls["n"] += 1
        raise _worker_terminated_error()

    async def scenario():
        await retry_once_on_worker_termination(run_once, gate=False)

    with pytest.raises(ActivityError):
        _run_async(scenario())
    assert calls["n"] == 1  # patched 门关（老 history 重放）：永不重跑


def test_retry_once_on_retry_callback_gets_exception():
    seen = []

    def on_retry(e):
        seen.append(e)

    res, n = _retry_call([_worker_terminated_error()], on_retry=on_retry)
    assert res == "ok-1" and n == 2 and len(seen) == 1
    assert classify_worker_termination(seen[0])


def test_retry_once_does_not_swallow_cancel():
    """CancelledError 是 BaseException：不进 except Exception，取消语义不吞。"""
    calls = {"n": 0}

    async def run_once():
        calls["n"] += 1
        raise asyncio.CancelledError()

    async def scenario():
        await retry_once_on_worker_termination(run_once, gate=True)

    with pytest.raises(asyncio.CancelledError):
        _run_async(scenario())
    assert calls["n"] == 1


def test_retry_patch_id_declared():
    assert WORKER_SHUTDOWN_RETRY_PATCH_ID == "agent-stage-worker-shutdown-retry"


# ---------- worker_termination_guard（注册表 + 归因转换） ----------

def _fake_info(attempt=3):
    agent_activities._activity_info = lambda: SimpleNamespace(  # noqa: E731
        workflow_id="wf-ut", activity_id="act-7", attempt=attempt)


@pytest.fixture(autouse=True)
def _restore_activity_info(monkeypatch):
    real_info = agent_activities._activity_info
    real_shutdown_probe = agent_activities._cancel_is_worker_shutdown
    yield
    agent_activities._activity_info = real_info
    agent_activities._cancel_is_worker_shutdown = real_shutdown_probe


def test_guard_completes_and_books():
    _fake_info()
    async def scenario():
        async with worker_termination_guard("t-1", "create_plan", 0):
            assert len(agent_activities.inflight_stage_snapshot()) == 1
            entry = agent_activities.inflight_stage_snapshot()[0]
            assert entry["ticket"] == "t-1" and entry["stage"] == "create_plan"
            assert entry["outcome"] == "running"
            return "done"
    assert _run_async(scenario()) == "done"
    assert agent_activities.inflight_stage_snapshot() == []  # 出栈：在飞快照只含在飞
    recent = agent_activities.recent_stage_outcomes()
    assert recent[0]["outcome"] == "completed" and recent[0]["attempt"] == 3


def test_guard_books_failure_and_reraises():
    _fake_info()
    async def scenario():
        async with worker_termination_guard("t-1", "implement", 1):
            raise RuntimeError("boom")
    with pytest.raises(RuntimeError):
        _run_async(scenario())
    assert agent_activities.recent_stage_outcomes()[0]["outcome"] == "failed"


def test_guard_non_shutdown_cancel_reraises_cancelled():
    """非停机取消（工作流主动取消等）：原样 re-raise CancelledError，不改道。"""
    _fake_info()
    monkey_flag = False
    agent_activities._cancel_is_worker_shutdown = lambda: monkey_flag

    async def scenario():
        async with worker_termination_guard("t-1", "implement", 0):
            raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        _run_async(scenario())
    assert agent_activities.recent_stage_outcomes()[0]["outcome"] == "cancelled"


def test_guard_shutdown_cancel_converts_to_typed_error():
    """要求②核心：worker 停机取消 → ApplicationError(type=worker_terminated)，
    message 带票/段/gen/attempt；工作流侧 classify 认得。"""
    _fake_info(attempt=5)
    agent_activities._cancel_is_worker_shutdown = lambda: True

    async def scenario():
        async with worker_termination_guard("t260916-29", "design_integration_tests", 1):
            raise asyncio.CancelledError()
    with pytest.raises(ApplicationError) as ei:
        _run_async(scenario())
    assert ei.value.type == WORKER_TERMINATED_ERROR_TYPE
    assert "t260916-29" in str(ei.value) and "design_integration_tests" in str(ei.value)
    assert "gen=1" in str(ei.value) and "attempt=5" in str(ei.value)
    assert agent_activities.recent_stage_outcomes()[0]["outcome"] == "worker_terminated"
    assert classify_worker_termination(ei.value) is True


def test_cancel_probe_fail_closed(monkeypatch):
    """取消细节拿不到（SDK 漂移/无上下文）→ False：宁可旧语义，不冒认停机。"""
    monkeypatch.setattr(agent_activities.activity, "cancellation_details",
                        lambda: None, raising=False)
    assert agent_activities._cancel_is_worker_shutdown() is False

    def boom():
        raise RuntimeError("sdk drift")
    monkeypatch.setattr(agent_activities.activity, "cancellation_details", boom,
                        raising=False)
    assert agent_activities._cancel_is_worker_shutdown() is False

    monkeypatch.setattr(agent_activities.activity, "cancellation_details",
                        lambda: SimpleNamespace(worker_shutdown=True), raising=False)
    assert agent_activities._cancel_is_worker_shutdown() is True
    monkeypatch.setattr(agent_activities.activity, "cancellation_details",
                        lambda: SimpleNamespace(worker_shutdown=0), raising=False)
    assert agent_activities._cancel_is_worker_shutdown() is False


def test_guard_snapshot_is_copy():
    _fake_info()
    async def scenario():
        async with worker_termination_guard("t-1", "implement", 0):
            snap = agent_activities.inflight_stage_snapshot()
            snap[0]["ticket"] = "tampered"
            return agent_activities.inflight_stage_snapshot()[0]["ticket"]
    assert _run_async(scenario()) == "t-1"  # 快照是拷贝，改不进内表


# ---------- C4：票面锚（meta.blocked_reason） ----------

def test_blocked_reason_surface_names_worker_termination(monkeypatch):
    """验收②的用户可感知面：catch 位文案经 dev_lane._blocked 落 meta.blocked_reason
    （KI-048 钉面），断言含「worker 被外部终止」+票号段号。UT 壳=object.__new__（
    _blocked 注释里点名的防御口径），workflow 模块打假。"""
    fake_workflow = SimpleNamespace(
        wait_condition=lambda cond: _noop(),
        patched=lambda *a, **k: False,
        now=lambda: datetime(2026, 9, 16, 12, 0, 0),
        logger=SimpleNamespace(info=lambda *a, **k: None))
    monkeypatch.setattr(dev_lane, "workflow", fake_workflow)
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = {}
    wf.timeline = []
    wf._gens = {}
    wf.ticket_id = "t260916-29"
    wf._retry_token = 0
    wf._rework = None
    msg = format_agent_stage_failure(wf.ticket_id, "implement",
                                     _worker_terminated_error(),
                                     gen=wf._gen("implement"))
    asyncio.new_event_loop().run_until_complete(wf._blocked("implement", msg))
    reason = wf.meta["blocked_reason"]
    assert "worker 被外部终止（停机/重载）" in reason
    assert "t260916-29" in reason and "implement" in reason
    assert wf.meta["stage_state"] == "blocked"
    # 非 worker 停机失败：blocked_reason 维持旧文案（不误点名）
    wf2 = object.__new__(dev_lane.DevLaneWorkflow)
    wf2.meta, wf2.timeline, wf2._gens, wf2.ticket_id = {}, [], {}, "t-2"
    wf2._retry_token, wf2._rework = 0, None
    asyncio.new_event_loop().run_until_complete(wf2._blocked(
        "implement", format_agent_stage_failure("t-2", "implement",
                                                RuntimeError("boom"))))
    assert wf2.meta["blocked_reason"].startswith("agent 活动故障（已重试）：RuntimeError")


async def _noop():
    return None


# ---------- 汇聚点接线锚（KI-093 纪律 + 防漂移） ----------

def test_guard_covers_four_long_activity_chokepoints():
    for fn in ("_make_stage_activity",):
        assert "worker_termination_guard" in inspect.getsource(
            getattr(agent_activities, fn))
    for fn in ("arbitrate", "acceptance_walkthrough", "run_integration_tests"):
        assert "worker_termination_guard" in inspect.getsource(
            getattr(agent_activities, fn)), fn


def test_guard_is_outside_stage_impl_body_ki093_discipline():
    """KI-093 纪律锚：守卫包在 _run_agent_stage_impl 外面，impl 内部的
    KI-009 finally 全路径 reap / 进程组逻辑零触碰（守卫源不进 impl 函数体）。"""
    impl_src = inspect.getsource(agent_activities._run_agent_stage_impl)
    assert "worker_termination_guard" not in impl_src
    assert "proc.reap" in impl_src  # KI-009 收尾原样在场
