"""t260922-10 记名清场入口（ticket.py op=cancel → client.py ticket-cancel →
workflow.cancel_notice）单测：拒收矩阵 / 留痕先于终结与三方同串 / 已终态幂等 /
跨项目闸一致（含 cross_project_uses 记名）/ KI-081 对账兜底 / 清场记名落账。

行为级真链路归引擎集成闸（run_integration_tests 机械跑）；本文件全程禁网络/
真 Temporal：ticket 层 _poc 桩（test_ticket_cli 的 tk 夹具同款）、client 层
FakeHandle/FakeClient 桩（test_t260915_12_t02 同款，扩 describe().status 供幂等
闸）、workflow 层离线桩实例（test_ticket_pause 纯离线纪律同款——handler 不触
workflow.* 运行时 API，宿主成员用桩实例供给）。

review 实施条件绑定：
  条1（回执不超诺）→ test_cancel_receipt_honest_copy；
  条2（KI-081：signal 已 ack、handler 未承接仍终结/同串/admin.log 有账）
      → test_cancel_ki081_signal_acked_without_handler_processing；
  条3（CONTINUED_AS_NEW 属活票，不得谎报已终态）
      → test_cancel_continued_as_new_still_alive。
"""
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import audit
import client
import shared
from base import TicketCrossProjectMixin, TicketWorkflowBase
from dev_lane import DevLaneWorkflow

REPO = Path(__file__).resolve().parents[3]
TICKET_PY = REPO / "server" / "tools" / "ticket.py"

# _write_gate 读快照 meta.project 判闸（t02 同款 SNAP；项目=sandbar，与 env 身份配对）
SNAP = {"meta": {"project": "sandbar"}, "workflow_class": "DevLaneWorkflow",
        "template_id": "dev-lane", "refused": [], "authorizations": []}


# ---------- client 层桩（t02 同款 + describe().status） ----------

class FakeSearchAttrs:
    def __init__(self, project=""):
        self._p = project

    def get(self, key):
        return self._p


class FakeDesc:
    def __init__(self, status="RUNNING", project=""):
        self.status = type("ExecStatus", (), {"name": status})()
        self.typed_search_attributes = FakeSearchAttrs(project)


class FakeHandle:
    """事件次序用单一列表记录：signal 与 terminate 的先后即「留痕先于终结」的机械
    断言面（服务端串行落账的桩投影）。terminate_exc 模拟终结期竞态（自然完单等）。"""
    def __init__(self, snap=None, status="RUNNING", project="", desc_exc=None,
                 terminate_exc=None):
        self._snap = snap if snap is not None else SNAP
        self.status_name = status
        self.project = project
        self.desc_exc = desc_exc
        self.terminate_exc = terminate_exc
        self.events = []          # ("signal", name, payload) | ("terminate", reason)
        self.terminated = None

    async def query(self, name):
        return self._snap

    async def describe(self):
        if self.desc_exc is not None:
            raise self.desc_exc
        return FakeDesc(self.status_name, self.project)

    async def signal(self, name, payload):
        self.events.append(("signal", name, payload))

    async def terminate(self, reason=""):
        if self.terminate_exc is not None:
            raise self.terminate_exc
        self.events.append(("terminate", reason))
        self.terminated = reason

    @property
    def signals(self):
        return [(e[1], e[2]) for e in self.events if e[0] == "signal"]


class FakeClient:
    def __init__(self, handle):
        self.handle = handle

    def get_workflow_handle(self, tid):
        return self.handle


async def _raise(e):
    raise e


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    """admin.log 指 tmp + 身份 env 清零（t02 _iso 同款隔离）。"""
    log = tmp_path / "admin.log"
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(log))
    monkeypatch.delenv(shared.CALLER_PROJECT_ENV, raising=False)
    monkeypatch.delenv(audit.ENTRY_ENV, raising=False)
    monkeypatch.delenv(audit.CALL_ID_ENV, raising=False)
    return log


def _patch_connect(monkeypatch, fake):
    monkeypatch.setattr(client, "_connect", lambda: asyncio.sleep(0, result=fake))


def _run(coro):
    return asyncio.run(coro)


REASON = "工作空间 /var/folders/T/t260910-* 已不存在，retry_qc 复现失败"


# ---------- client 层：先留痕后终结 + 三方同串（验收②） ----------

def test_cancel_stamp_then_terminate_same_string(monkeypatch):
    h = FakeHandle()
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "sandbar")
    r = _run(client.cmd_ticket_cancel({"ticket_id": "t1", "who": "ops", "reason": REASON}))
    assert r["ok"] and r["result"]["terminated"] is True
    assert r["result"]["who"] == "ops"
    # 次序机械面：留痕（signal）严格先于终结（terminate）——验收②顺序可验
    assert [e[0] for e in h.events] == ["signal", "terminate"]
    name, payload = h.signals[0]
    assert name == "cancel_notice"
    assert payload["who"] == "ops" and payload["reason"] == REASON
    assert payload["caller_project"] == "sandbar"
    assert payload["cross_project_note"] == ""
    # 同串（== 精确对比，不做模糊匹配）：信号载荷 × terminate reason × 回执 三方同一串
    assert payload["reason"] == h.terminated == r["result"]["reason"] == REASON


def test_cancel_cross_project_with_flag_stamped_and_recorded(monkeypatch):
    """验收④带旗侧：越权旗放行 + 盖章随载荷下发（workflow 侧落 cross_project_uses）。"""
    h = FakeHandle()
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "dengzhufpv")
    r = _run(client.cmd_ticket_cancel({"ticket_id": "t1", "who": "integration",
                                       "reason": "代管清场残渣票",
                                       "cross_project": {"by": "integration",
                                                         "reason": "代管清场残渣票"}}))
    assert r["ok"] and r["cross_project_used"] is True
    _, payload = h.signals[0]
    assert payload["caller_project"] == "dengzhufpv"
    assert payload["cross_project_note"] == "代管清场残渣票"
    assert h.terminated == "代管清场残渣票"


def test_cancel_undeclared_sentinel_no_false_notice(monkeypatch):
    """C3 分档：ticket-cancel 已盖章（workflow 侧落 cross_project_uses）——回执不得
    谎称「查询面列不出」（该诚实口径只属 _UNSTAMPED_NOTICE_OPS 的裸 cancel）。"""
    monkeypatch.setenv(shared.UNDECLARED_POLICY_ENV, "record")  # t260925-08：记名=旋钮显式
    h = FakeHandle()
    _patch_connect(monkeypatch, FakeClient(h))
    r = _run(client.cmd_ticket_cancel({"ticket_id": "t1", "who": "ops", "reason": "r"}))
    assert r["ok"] and r["identity_class"] == "undeclared"
    _, payload = h.signals[0]
    assert payload["caller_project"] == shared.CALLER_UNDECLARED_MARK  # 哨兵章=记名靠它
    assert "cross_project_uses 列不出" not in (r.get("cross_project_notice") or "")


# ---------- client 层：幂等（验收③） ----------

@pytest.mark.parametrize("status", ["TERMINATED", "COMPLETED", "CANCELED", "FAILED"])
def test_cancel_already_terminal_idempotent(monkeypatch, status):
    h = FakeHandle(status=status)
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "sandbar")
    r = _run(client.cmd_ticket_cancel({"ticket_id": "t1", "who": "ops", "reason": "r"}))
    assert r["ok"] and r["result"]["already_terminal"] is True
    assert r["result"]["exec_status"] == status
    assert "already terminal" in r["result"]["note"]
    assert h.events == []      # 不改动任何东西：零信号、零终结、零闸读取副作用
    assert r["result"]["reason"] == "r"   # 回执与请求一致（不吞不改编）


def test_cancel_continued_as_new_still_alive(monkeypatch):
    """review 条3：CONTINUED_AS_NEW 属未收口（_EXEC_ALIVE_OK 家族口径，巡检 watcher
    换代中）——KI-025 红线：不许把活票谎报成「已终态」，必须走闸照常处理。"""
    h = FakeHandle(status="CONTINUED_AS_NEW")
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "sandbar")
    r = _run(client.cmd_ticket_cancel({"ticket_id": "t1", "who": "ops", "reason": "r"}))
    assert r["ok"] and "already_terminal" not in r["result"]
    assert [e[0] for e in h.events] == ["signal", "terminate"]


# ---------- client 层：结构化拒收矩阵（验收①④，拒绝=零副作用） ----------

def test_cancel_cross_project_refused_zero_side_effect(monkeypatch):
    """验收④无旗侧：declared 异项目 → cross_project_refused 点名双项目+票号，零写。"""
    h = FakeHandle()
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "dengzhufpv")
    r = _run(client.cmd_ticket_cancel({"ticket_id": "t1", "who": "ops", "reason": "r"}))
    assert r["ok"] is False and r["kind"] == "cross_project_refused"
    assert "dengzhufpv" in r["error"] and "sandbar" in r["error"] and "t1" in r["error"]
    assert h.events == []      # fail-closed：不留痕、不终结


def test_cancel_gate_snapshot_transient_no_terminate(monkeypatch):
    """C2①：闸前置快照读取瞬时失败 ≠ 越权 → transient 拒收，绝不无闸放行 terminate。"""
    h = FakeHandle()
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setattr(client, "_query_snapshot_with_retry",
                        lambda handle, **k: _raise(TimeoutError("deadline exceeded")))
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "sandbar")
    r = _run(client.cmd_ticket_cancel({"ticket_id": "t1", "who": "ops", "reason": "r"}))
    assert r["ok"] is False and r["kind"] == "transient"
    assert h.events == []


def test_cancel_not_found_and_describe_transient(monkeypatch):
    h = FakeHandle(desc_exc=RuntimeError("workflow not found: t1"))
    _patch_connect(monkeypatch, FakeClient(h))
    r = _run(client.cmd_ticket_cancel({"ticket_id": "t1", "who": "ops", "reason": "r"}))
    assert r["ok"] is False and r["kind"] == "not_found" and h.events == []

    h2 = FakeHandle(desc_exc=TimeoutError("deadline exceeded"))
    _patch_connect(monkeypatch, FakeClient(h2))
    r2 = _run(client.cmd_ticket_cancel({"ticket_id": "t1", "who": "ops", "reason": "r"}))
    assert r2["ok"] is False and r2["kind"] == "transient"
    assert "未执行任何动作" in r2["error"] and h2.events == []


def test_cancel_malformed_args_refused_before_connect(monkeypatch, ):
    """参数拒收必须发生在连接之前（畸形输入 fail-closed；_connect 炸=证明没被调）。"""
    _patch_connect(monkeypatch, None)
    monkeypatch.setattr(client, "_connect",
                        lambda: (_ for _ in ()).throw(AssertionError("must not connect")))
    missing = [{}, {"ticket_id": "t1"}, {"ticket_id": "t1", "who": "x"},
               {"ticket_id": "t1", "who": "   ", "reason": "r"},
               {"ticket_id": "t1", "who": "x", "reason": ""},
               {"ticket_id": "t1", "who": "x", "reason": "  \n  "}]
    for args in missing:
        r = _run(client.cmd_ticket_cancel(args))
        assert r["ok"] is False and r.get("error")
        assert r["error"].startswith("ticket-cancel requires")   # single copy exit, named in plain words
    for args in ({"ticket_id": "t1", "who": "x", "reason": []},
                 {"ticket_id": "t1", "who": "x", "reason": {"a": 1}},
                 {"ticket_id": "t1", "who": "x", "reason": 123}):
        # 非串 reason 不做 str() 静默归一（场景②R4 契约）：归一会造假非空放行
        r = _run(client.cmd_ticket_cancel(args))
        assert r["ok"] is False
        assert r["error"].startswith("ticket-cancel 的 reason 需为字符串")


def test_cancel_reason_over_limit_refused(monkeypatch):
    _patch_connect(monkeypatch, None)
    monkeypatch.setattr(client, "_connect",
                        lambda: (_ for _ in ()).throw(AssertionError("must not connect")))
    r = _run(client.cmd_ticket_cancel({"ticket_id": "t1", "who": "x",
                                       "reason": "长" * (shared.CROSS_PROJECT_NOTE_LIMIT + 1)}))
    assert r["ok"] is False and "exceeds limit" in r["error"]


def test_cancel_terminate_failure_after_stamp(monkeypatch):
    """先留痕后终结的失败分支：signal 已出手、terminate 失败 → 结构化 _err 且写明
    「信号已入事件历史、本次未终结」，不裸栈、不谎报 terminated。"""
    h = FakeHandle(terminate_exc=RuntimeError("workflow execution already completed"))
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "sandbar")
    r = _run(client.cmd_ticket_cancel({"ticket_id": "t1", "who": "ops", "reason": "r"}))
    assert r["ok"] is False
    assert "已入事件历史" in r["error"] and "未终结" in r["error"]
    assert [e[0] for e in h.events] == ["signal"]   # 留痕在，终结未发生


def test_cancel_receipt_honest_copy(monkeypatch):
    """review 条1：回执不超诺——delivered 语义=signal 已落事件历史；权威对账=事件
    历史×admin.log 同串；票面留痕明写「终结前窗口尽力面」。"""
    h = FakeHandle()
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "sandbar")
    r = _run(client.cmd_ticket_cancel({"ticket_id": "t1", "who": "ops", "reason": REASON}))
    res = r["result"]
    assert res["delivered"] is True and res["signal"] == "cancel_notice"
    note = res["receipt_note"]
    assert "事件历史" in note and "admin.log" in note
    assert "窗口" in note and "尽力面" in note


def test_cancel_ki081_signal_acked_without_handler_processing(monkeypatch, _iso):
    """review 条2（KI-081）：老 worker 静默丢新信号——signal 被 server ack 但 handler
    未承接（桩形态=signal 只落事件记录、无任何 workflow 状态承接）。断言对账面不依赖
    handler 承接：仍终结、回执仍带同串 reason；回执即 main()/_emit→audit_call 的落账
    源（summary=receipt JSON）⇒ admin.log 行含同串（800 字符截断内，正常长度 reason
    全文在账）。"""
    h = FakeHandle()
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "sandbar")
    reason = "KI081-同串对账锚-9f2c"
    r = _run(client.cmd_ticket_cancel({"ticket_id": "t1", "who": "ops", "reason": reason}))
    assert r["ok"] and h.terminated == reason            # 仍终结
    assert r["result"]["reason"] == reason               # 回执同串（→admin.log summary）
    assert "KI081-同串对账锚-9f2c" in json.dumps(r, ensure_ascii=False)


# ---------- workflow 层：cancel_notice handler（离线桩实例） ----------

class _StubWf(TicketCrossProjectMixin):
    """离线桩实例：mixin 宿主成员最小实现（_now_*/_log 桩；meta/refused/timeline 真
    容器）。与 test_ticket_pause 纯离线纪律同款——不触 workflow.* 运行时 API。"""
    def __init__(self, project="sandbar"):
        self.meta = {"project": project, "stage": "implement", "status": "dispatched"}
        self.refused = []
        self.timeline = []

    def _now_epoch(self):
        return 1758506400

    def _now_iso(self):
        return "2026-09-22T10:00:00"

    def _log(self, note, status=None):
        self.meta.setdefault("log", []).append(
            {"ts": self._now_epoch(), "status": status or self.meta.get("status", ""),
             "note": note})

    def _touch(self):
        self.meta["updated"] = self._now_epoch()


def test_cancel_notice_wiring_mixin_single_point():
    """两类 workflow 均可调（继承自共享 mixin），且 DevLaneWorkflow 自身零私有定义
    （dev_lane.py 零改动=A3.5 协调的机械审计面，test_mixin_wiring 同款口径）。"""
    assert callable(getattr(TicketWorkflowBase, "cancel_notice", None))
    assert callable(getattr(DevLaneWorkflow, "cancel_notice", None))
    assert "cancel_notice" not in DevLaneWorkflow.__dict__
    assert "cancel_notice" in TicketCrossProjectMixin.__dict__


def test_cancel_notice_accepts_and_leaves_trace():
    wf = _StubWf(project="sandbar")
    TicketCrossProjectMixin.cancel_notice(
        wf, {"who": "ops", "reason": REASON, "caller_project": "",
             "cross_project_note": ""})
    log = wf.meta.get("log") or []
    assert len(log) == 1 and "ops" in log[-1]["note"] and REASON in log[-1]["note"]
    assert wf.timeline[-1]["state"] == "cancel-noticed"
    assert REASON in wf.timeline[-1]["reason"] and "ops" in wf.timeline[-1]["reason"]
    assert "cross_project_uses" not in wf.meta        # 同项目闸=allow 零记名
    assert wf.refused == []


@pytest.mark.parametrize("req", [
    "not-a-dict",
    {"reason": "r"},                                   # who 缺
    {"who": "ops"},                                    # reason 缺
    {"who": "  ", "reason": "r"},                      # who 纯空白
    {"who": "ops", "reason": "  "},                    # reason 纯空白
])
def test_cancel_notice_malformed_refused_zero_side_effect(req):
    """畸形输入（含非 dict 载荷）：refused[] 落账（留痕在拒收面），业务面零副作用。"""
    wf = _StubWf(project="sandbar")
    TicketCrossProjectMixin.cancel_notice(wf, req)
    assert len(wf.refused) == 1
    assert wf.refused[0]["want"] == "cancel_notice"
    assert "log" not in wf.meta and wf.timeline == []
    assert "cross_project_uses" not in wf.meta


def test_cancel_notice_cross_project_recorded():
    """验收④带旗侧（workflow 第二道）：越权旗记名入 cross_project_uses（by/reason
    原文），受理留痕照落。"""
    wf = _StubWf(project="proj-b")
    TicketCrossProjectMixin.cancel_notice(
        wf, {"who": "integration", "reason": "代管清场",
             "caller_project": "proj-a", "cross_project_note": "代管清场"})
    uses = wf.meta["cross_project_uses"]
    assert uses[-1]["op"] == "cancel"
    assert uses[-1]["by"] == "integration"
    assert uses[-1]["reason"] == "代管清场"             # 原文（≤300 既有截断口径内）
    assert wf.timeline[-1]["state"] == "cancel-noticed"
    assert "代管清场" in (wf.meta.get("log") or [{}])[-1]["note"]


def test_cancel_notice_cross_project_without_flag_refused():
    """验收④无旗侧（workflow 第二道兜底）：declared 异项目无旗 → refused+log 点名
    「谁要动谁的票」，零记名零受理。"""
    wf = _StubWf(project="proj-b")
    TicketCrossProjectMixin.cancel_notice(
        wf, {"who": "integration", "reason": "r",
             "caller_project": "proj-a", "cross_project_note": ""})
    assert wf.refused and "proj-a" in wf.refused[-1]["why"] and "proj-b" in wf.refused[-1]["why"]
    assert "cross_project_uses" not in wf.meta
    assert wf.timeline == []
    assert len(wf.meta.get("log") or []) == 1          # 只落闸拒收 log，无受理 log


def test_cancel_notice_undeclared_sentinel_recorded(monkeypatch):
    """B 策略（旋钮显式 record）：未声明身份（哨兵章）→ allow_record 记名放行。"""
    monkeypatch.setenv(shared.UNDECLARED_POLICY_ENV, "record")  # t260925-08 翻严后须显式
    wf = _StubWf(project="proj-b")
    TicketCrossProjectMixin.cancel_notice(
        wf, {"who": "ops", "reason": "r",
             "caller_project": shared.CALLER_UNDECLARED_MARK, "cross_project_note": ""})
    uses = wf.meta["cross_project_uses"]
    assert uses[-1]["op"] == "cancel" and uses[-1]["caller_project"] == shared.CALLER_UNDECLARED_MARK


# ---------- ticket 层：包装层（_poc 桩，tk 夹具同款） ----------

@pytest.fixture()
def tk(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("ticket_mod_cancel_test", TICKET_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ticket_mod_cancel_test"] = mod
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(tmp_path / "admin.log"))
    monkeypatch.delenv("SANDBAR_CLIENT_ENTRY", raising=False)
    monkeypatch.delenv("SANDBAR_CLIENT_CALL_ID", raising=False)
    monkeypatch.delenv("SANDBAR_CALLER_PROJECT", raising=False)
    spec.loader.exec_module(mod)
    calls = []
    real_poc = mod._poc                    # 留真实现：KI-067 族用例要压 _poc 自身路径

    def fake_poc(subcmd, payload, caller=None):
        calls.append((subcmd, payload, caller))
        return {"ok": True, "result": {"terminated": True,
                                       "reason": payload.get("reason"),
                                       "who": payload.get("who")}}

    monkeypatch.setattr(mod, "_poc", fake_poc)
    mod._real_poc = real_poc
    mod._calls = calls
    return mod


def test_ticket_cancel_forwards_shape(tk):
    r = tk.run({"op": "cancel", "id": "t1", "by": "integration", "reason": REASON})
    assert r["terminated"] is True and r["reason"] == REASON
    subcmd, payload, _caller = tk._calls[0]
    assert subcmd == "ticket-cancel"                    # 不与裸 cancel/写 op 混用
    assert payload == {"op": "cancel", "ticket_id": "t1",
                       "who": "integration", "reason": REASON}


def test_ticket_cancel_who_alias_double_read(tk):
    tk.run({"op": "cancel", "id": "t1", "who": "ops-x", "reason": "r"})
    assert tk._calls[0][1]["who"] == "ops-x"            # by|who 双读（_who 同族）


@pytest.mark.parametrize("args", [
    {"op": "cancel", "reason": "r"},                          # id 缺
    {"op": "cancel", "id": "t1", "reason": "r"},              # who 缺
    {"op": "cancel", "id": "t1", "who": "  ", "reason": "r"}, # who 纯空白
    {"op": "cancel", "id": "t1", "who": "x"},                 # reason 缺
    {"op": "cancel", "id": "t1", "who": "x", "reason": ""},   # reason 空
    {"op": "cancel", "id": "t1", "who": "x", "reason": " \n "},
])
def test_ticket_cancel_refusals_zero_poc(args, tk):
    """验收①：reason/who/id 空=结构化拒收（ValueError 带 kind 通道），
    _poc 零调用=拒绝零副作用（连 Temporal 子进程都不 spawn）。"""
    with pytest.raises(ValueError) as ei:
        tk.run(dict(args))
    assert "cancel" in str(ei.value)
    assert tk._calls == []


@pytest.mark.parametrize("bad_reason", [["x"], {"a": 1}, 123])
def test_ticket_cancel_non_string_reason_refused_not_normalized(tk, bad_reason):
    """场景②R4 契约（包装层同口径）：非串 reason 不得 str() 归一放行——["x"] 归一
    会变 "['x']" 非空穿透；清场理由是对账锚，类型畸形=结构化拒收。"""
    with pytest.raises(ValueError) as ei:
        tk.run({"op": "cancel", "id": "t1", "who": "x", "reason": bad_reason})
    assert "reason" in str(ei.value) and "字符串" in str(ei.value)
    assert tk._calls == []


def test_ticket_cancel_flag_passthrough(tk):
    tk.run({"op": "cancel", "id": "t1", "by": "x", "reason": "r",
            "cross_project": {"by": "x", "reason": "代管清场"}})
    subcmd, payload, _caller = tk._calls[0]
    assert payload["cross_project"] == {"by": "x", "reason": "代管清场"}


def test_ticket_cancel_schema_declares_entry(tk):
    """KI-079 族：说明书=实际入口——op enum 含 cancel、reason 键已宣告
    （additionalProperties:false 下缺宣告=入口不可达）。"""
    props = tk.TOOL["parameters"]["properties"]
    assert "cancel" in props["op"]["enum"]
    assert "reason" in props
    assert tk.TOOL["parameters"]["additionalProperties"] is False


def test_ticket_cancel_cli_reason_empty_structured_exit(tk, tmp_path, monkeypatch):
    """验收①CLI 形态：reason 空=零 Temporal spawn 路径，可真子进程压——退出 1 +
    一行 {ok:false}（不抛栈、不空输出）。"""
    env = dict(os.environ)
    env["SANDBAR_ADMIN_LOG"] = str(tmp_path / "cli-admin.log")
    env.pop("SANDBAR_CALLER_PROJECT", None)
    proc = subprocess.run(
        [sys.executable, str(TICKET_PY),
         json.dumps({"op": "cancel", "id": "t1", "who": "x", "reason": ""},
                    ensure_ascii=False)],
        cwd=str(REPO), capture_output=True, text=True, env=env, timeout=60)
    assert proc.returncode == 1
    out = proc.stdout.strip()
    assert out        # 绝不空输出
    parsed = json.loads(out.splitlines()[-1])
    assert parsed["ok"] is False and "reason" in parsed["error"]


def test_ticket_cancel_cli_happy_admin_log_same_string(tk, tmp_path, capsys):
    """验收②admin.log 侧（包装层行）：_cli 成功路径审计行 summary 含同一 reason 串。"""
    rc = tk._cli([json.dumps({"op": "cancel", "id": "t1", "by": "ops",
                              "reason": "CLI-对账串-7a1d"}, ensure_ascii=False)])
    assert rc == 0
    rows = [json.loads(x)
            for x in (tmp_path / "admin.log").read_text(encoding="utf-8").splitlines()]
    row = [r for r in rows if r.get("sub") == "ticket.cancel"][-1]
    assert row["ok"] is True
    assert "CLI-对账串-7a1d" in row["summary"]          # 同串入账（==精确 grep 可中）


def test_ticket_cancel_cli_downstream_failure_structured(tk, capsys, monkeypatch):
    """KI-067 族（review 意3）：下游 client 子进程失败 → 本入口必须非零退出+非空
    结构化错误，绝不静默空输出（本正向链正是当年静默失败链的形状，防回潮）。"""
    def boom(subcmd, payload, caller=None):
        raise ValueError("Temporal 调用失败（temporal server/worker 在线？）: no route")

    monkeypatch.setattr(tk, "_poc", boom)
    rc = tk._cli([json.dumps({"op": "cancel", "id": "t1", "by": "x", "reason": "r"},
                             ensure_ascii=False)])
    out = capsys.readouterr().out.strip()
    assert rc == 1 and out
    parsed = json.loads(out.splitlines()[-1])
    assert parsed["ok"] is False and "Temporal" in parsed["error"]


def test_ticket_cancel_poc_non_json_stdout_raises(tk, monkeypatch):
    """KI-067 族补充：下游回执非 JSON（老版本/栈溢出页）→ 结构化 ValueError，
    不把垃圾当成功。恢复真 _poc（fixture 默认桩会绕过 subprocess 路径）。"""
    class _FakeProc:
        stdout = "not-json<error>"
        stderr = "boom"
        returncode = 1

    monkeypatch.setattr(tk, "_poc", tk._real_poc)
    monkeypatch.setattr(tk.subprocess, "run",
                        lambda *a, **k: _FakeProc())
    with pytest.raises(ValueError) as ei:
        tk.run({"op": "cancel", "id": "t1", "by": "x", "reason": "r"})
    assert "非 JSON" in str(ei.value)


# ---------- client 层：终态 face 增量（S4，纯函数） ----------

def test_terminated_reason_of_extracts_reason():
    # 桩继承 Exception（真 temporalio WorkflowFailureError/TerminatedError 同族），
    # 继承 BaseException 会被 _terminal_failure_face 的 except Exception 漏接。
    term = type("TerminatedError", (Exception,), {})
    err = term("workflow execution terminated")
    err.reason = "清场对账串"
    outer = type("WorkflowFailureError", (Exception,), {})("workflow failed")
    outer.__cause__ = err
    assert client._terminated_reason_of(outer) == "清场对账串"
    # 直接命中顶层
    assert client._terminated_reason_of(err) == "清场对账串"


def test_terminated_reason_of_malformed_chain_never_fabricates():
    # 空串/非串 reason / 无 reason / cause 断链（非 BaseException 对象）/ None → 一律 ''
    e1 = type("T", (Exception,), {})("x")
    e1.reason = "   "
    assert client._terminated_reason_of(e1) == ""
    e2 = type("T", (Exception,), {})("x")
    e2.reason = 12345
    assert client._terminated_reason_of(e2) == ""
    e3 = type("T", (Exception,), {})("plain failure")
    assert client._terminated_reason_of(e3) == ""
    # __cause__ 直接赋非异常值会被 CPython 拒（TypeError），用 property 桩模拟
    # 「__cause__ 是非异常对象」的畸形形态（_failure_reason_of 同款防御注释口径）。
    class _WeirdCause(Exception):
        __cause__ = property(lambda self: "not-an-exception")

    assert client._terminated_reason_of(_WeirdCause("x")) == ""
    assert client._terminated_reason_of(None) == ""


def test_terminal_face_carries_terminate_reason_keys(monkeypatch):
    """face 增量键 additive 落位：TERMINATED 形态（result() 抛带 reason 的链）→
    terminate_reason/terminate_reason_available 在场；既有键零改动。"""
    term = type("TerminatedError", (Exception,), {})
    cause = term("workflow execution terminated")
    cause.reason = REASON
    failure = type("WorkflowFailureError", (Exception,), {})("x")
    failure.__cause__ = cause

    class _Handle:
        async def result(self):
            raise failure

    desc = FakeDesc("TERMINATED", "sandbar")
    face = _run(client._terminal_failure_face("t1", _Handle(), desc, "TERMINATED"))
    assert face["terminate_reason"] == REASON
    assert face["terminate_reason_available"] is True
    # 既有键不回归（t260919-02 契约：kind/文案零退化，face 只加载荷）
    assert face["exec_status"] == "TERMINATED"
    assert face["snapshot_available"] is False
    assert face["project"] == "sandbar"


def test_terminal_face_no_terminate_reason_for_failure_shape(monkeypatch):
    """FAILED 形态（异常链无 reason 属性）→ terminate_reason 不可得，不编造。"""
    app = type("ApplicationError", (Exception,), {})("agent stage failed")
    failure = type("WorkflowFailureError", (Exception,), {})("x")
    failure.__cause__ = app

    class _Handle:
        async def result(self):
            raise failure

    face = _run(client._terminal_failure_face("t1", _Handle(), FakeDesc("FAILED"), "FAILED"))
    assert face["terminate_reason_available"] is False
    assert face["terminate_reason"] == ""
