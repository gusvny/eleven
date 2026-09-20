"""t260913-01 dev_lane sign 的 marker 分支（authorize 丢失可见化）+ 三模板 marker
fail-closed 锁（零 Temporal，stub dev_lane.workflow 同 t260912-03 套路）。

覆盖（方案 v2 L4 + review C-负锁/R7/R8b 的机械子用例）：
  - marker 分支四子用例：
    ① authorize 在场 + gate=marker → intake 正常（gate 被标记占用也不比对 merge）；
    ② authorize 缺失 + gate=marker → refused want=sign(authorize)、why 点名
      「载荷解析失败」（与「非人审等待中」可辨）、不落账、不进 _sigs、log 记名；
    ③ 不带 authorize 的普通签字（gate=merge 在人门等待中）→ 既有语义逐字节不变；
    ④ 普通签字非人审态拒收文案逐字节不变（含 gate="" 的旧复现形态 want="sign()"）。
  - 三模板 marker 形态 fail-closed（marker 绝不产生放行）：
    base（非人门段拒 + 人门段 gate 不符拒）/ workflows（gate∉HUMAN_GATES 招）/
    inspection_flow（validate_close_signature gate≠CLOSE_GATE_ID 拒 + handler 面）。
  - 毒载荷排除说明（R7）：authorize=123 这类类型不兼容载荷在 value_to_type 抛
    TypeError → workflow task 重试循环（毒消息）——负锁用例只用 decode-safe 形状
    （缺字段/裸 dict），不构造毒载荷。
"""
import datetime
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import base  # noqa: E402
import dev_lane  # noqa: E402
import inspection_flow  # noqa: E402
import shared  # noqa: E402
import workflows  # noqa: E402
from shared import (  # noqa: E402
    AUTHZ_SIGNAL_GATE_MARKER as MARKER,
    HumanAuthorization,
    Signature,
    Stage,
)

NOW = 1_757_000_000
NOW_DT = datetime.datetime(2026, 9, 13, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _mk_wf(meta=None, timeline=None, refused=None):
    """免 Temporal 运行时的 DevLaneWorkflow 壳（t260912-03 单测同款套路）。"""
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: False, now=lambda: NOW_DT,
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None))
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = dict(meta or {})
    wf.timeline = list(timeline or [])
    wf.refused = list(refused or [])
    wf._sigs = {}
    wf.results = {}
    wf.ticket_id = str((meta or {}).get("ticket_id") or "t-ut")
    return wf


def _sign(wf, sig):
    fn = dev_lane.DevLaneWorkflow.__dict__["sign"]
    fn = getattr(fn, "__func__", fn)
    fn(wf, sig)


def _auth(**kw):
    base_kw = dict(kind="protected_path", who="宿主",
                   scope=["integration/baselines"], reason="修期望值",
                   expires=int(NOW_DT.timestamp()) + 3600)
    base_kw.update(kw)
    return HumanAuthorization(**base_kw)


BLOCKED = {"stage": "arbitrate", "stage_state": "blocked", "ticket_id": "t-ut"}


# ---------- marker 分支四子用例 ----------

def test_marker_gate_without_authorize_is_named_parse_failure():
    wf = _mk_wf(BLOCKED)
    _sign(wf, Signature(who="宿主", gate=MARKER))
    assert len(wf.refused) == 1
    assert wf.refused[0]["want"] == "sign(authorize)"
    assert "载荷解析失败" in wf.refused[0]["why"]  # 与「非人审等待中」可辨（验收 C）
    assert "不按普通签字处理" in wf.refused[0]["why"]
    assert wf._sigs == {}                          # 不落签字
    assert "authorizations" not in wf.meta         # 不落账
    assert any("载荷解析失败" in (e.get("note") or "") for e in wf.meta.get("log", []))


def test_marker_gate_with_authorize_takes_intake():
    wf = _mk_wf(BLOCKED)
    _sign(wf, Signature(who="宿主", gate=MARKER, decision="approve",
                        authorize=_auth()))
    assert wf.refused == []                              # 不走 marker 拒收
    assert len(wf.meta["authorizations"]) == 1           # intake 正常落账
    assert wf._sigs == {}                                # 也不当普通签字收下


def test_plain_sign_at_merge_gate_unchanged():
    wf = _mk_wf({"stage": "merge", "stage_state": "awaiting-human"})
    sig = Signature(who="宿主", gate="merge", decision="approve", note="ok")
    _sign(wf, sig)
    assert wf.refused == [] and wf._sigs["merge"] is sig  # 既有语义逐字节不变（验收 E）


def test_plain_sign_refusal_wording_unchanged():
    wf = _mk_wf(BLOCKED)
    _sign(wf, Signature(who="宿主", gate="merge"))
    assert wf.refused[0]["want"] == "sign(merge)"
    assert wf.refused[0]["why"] == "当前步 arbitrate 非人审等待中，签字无效"


def test_empty_gate_plain_sign_refusal_wording_unchanged():
    """260913 生产复现的原始形态（gate=""）：仍是普通签字路径的旧文案——marker 分支
    只认 gate=保留值，普通签字面零扩权（验收 E 的可辨性边界）。"""
    wf = _mk_wf(BLOCKED)
    _sign(wf, Signature(who="宿主", gate=""))
    assert wf.refused[0]["want"] == "sign()"
    assert wf.refused[0]["why"] == "当前步 arbitrate 非人审等待中，签字无效"
    assert "authorizations" not in wf.meta


# ---------- 三模板 marker 形态 fail-closed（绝不放行） ----------

def _stub_wf_logger(mod):
    old = mod.workflow
    mod.workflow = SimpleNamespace(
        logger=SimpleNamespace(warn=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               info=lambda *a, **k: None))
    return old


def test_base_marker_gate_refused_on_non_human_stage():
    wf = object.__new__(base.TicketWorkflowBase)
    wf.refused = []
    wf._sigs = {}
    wf.meta = {"stage": "whatever"}
    wf.STAGES = ()
    fn = base.TicketWorkflowBase.__dict__["sign"]
    fn = getattr(fn, "__func__", fn)
    fn(wf, Signature(who="宿主", gate=MARKER))
    assert len(wf.refused) == 1 and wf._sigs == {}   # fail-closed


def test_base_marker_gate_refused_on_human_stage_gate_mismatch():
    wf = object.__new__(base.TicketWorkflowBase)
    wf.refused = []
    wf._sigs = {}
    wf.meta = {"stage": "gate1"}
    wf.STAGES = (Stage(id="gate1", name="门", role="developer", exit="human"),)
    fn = base.TicketWorkflowBase.__dict__["sign"]
    fn = getattr(fn, "__func__", fn)
    fn(wf, Signature(who="宿主", gate=MARKER))
    assert len(wf.refused) == 1 and "gate" in wf.refused[0]["why"]
    assert wf._sigs == {}   # marker 永不落签字


def test_workflows_marker_gate_refused():
    wf = object.__new__(workflows.ContentPipelineWorkflow)
    wf.refused_attempts = []
    wf._sigs = {}
    wf.signatures = {}
    old = _stub_wf_logger(workflows)
    try:
        fn = workflows.ContentPipelineWorkflow.__dict__["sign"]
        fn = getattr(fn, "__func__", fn)
        fn(wf, Signature(who="宿主", gate=MARKER))
    finally:
        workflows.workflow = old
    assert len(wf.refused_attempts) == 1
    assert wf._sigs == {} and wf.signatures == {}


def test_inspection_marker_gate_refused():
    # 纯函数面：gate≠CLOSE_GATE_ID → 拒
    payload, err = inspection_flow.validate_close_signature(
        Signature(who="宿主", gate=MARKER, decision="approve"))
    assert payload is None and "签字 gate 不匹配" in err
    # handler 面：authorize 缺失 + marker gate → _gate_err、不落签字
    wf = object.__new__(inspection_flow.InspectionPeriodicWorkflow)
    wf._gate_err = ""
    wf._close_sig = None
    old = _stub_wf_logger(inspection_flow)
    try:
        fn = inspection_flow.InspectionPeriodicWorkflow.__dict__["sign"]
        fn = getattr(fn, "__func__", fn)
        fn(wf, Signature(who="宿主", gate=MARKER, decision="approve"))
    finally:
        inspection_flow.workflow = old
    assert wf._close_sig is None and "gate 不匹配" in wf._gate_err
